"""Minimal rule-based controller for one coalition's strategic conflict loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .operational import OperationalPlan, OperationalPlanStatus
from .operational_execution import OperationalPlanExecution
from .pictures import TacticalPicture
from .strategic import (
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
    normalize_coalition,
)
from .strategic_selection import StrategicGoalPortfolio
from .strategic_goals import StrategicGoalGenerationConfig, evaluate_strategic_objective

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


@dataclass(slots=True, frozen=True)
class ConflictControllerConfig:
    """Conservative limits and policy for one coalition controller."""

    coalition: str = "blue"
    intel_id: str = "INTEL:Blue Intel"
    controller_id: str = "rule_based_conflict.blue"
    declare_war_if_needed: bool = True
    war_reason: str = "Start the autonomous conflict simulation"
    max_concurrent_goals: int = 1
    defense_duration_s: float = 1800.0
    destroy_required_damage: float = 0.7
    mission_timeout_s: float = 3600.0

    def __post_init__(self) -> None:
        coalition = normalize_coalition(self.coalition) or ""
        if coalition not in {"blue", "red"}:
            raise ValueError("conflict controller coalition must be blue or red")
        if not self.intel_id.strip() or not self.controller_id.strip():
            raise ValueError("conflict controller requires intel_id and controller_id")
        if self.max_concurrent_goals < 1:
            raise ValueError("max_concurrent_goals must be at least one")
        if self.defense_duration_s <= 0 or self.mission_timeout_s <= 0:
            raise ValueError("controller durations must be positive")
        if not 0 <= self.destroy_required_damage <= 1:
            raise ValueError("destroy_required_damage must be between zero and one")
        object.__setattr__(self, "coalition", coalition)


@dataclass(slots=True, frozen=True)
class ConflictControllerIssue:
    """One skipped or failed controller decision."""

    objective_id: str
    stage: str
    message: str


@dataclass(slots=True, frozen=True)
class ConflictControllerCycle:
    """Auditable result of one bounded strategic decision cycle."""

    coalition: str
    mission_time: float | None
    generated_goal_ids: tuple[str, ...]
    generated_plan_ids: tuple[str, ...]
    portfolio: StrategicGoalPortfolio
    executions: tuple[OperationalPlanExecution, ...]
    issues: tuple[ConflictControllerIssue, ...]


class RuleBasedConflictController:
    """Generate, select, approve, and execute a small strategic portfolio."""

    def __init__(self, client: MooseBridgeClient, config: ConflictControllerConfig | None = None) -> None:
        self.client = client
        self.config = config or ConflictControllerConfig()
        self._cycle_number = 0

    async def ensure_war(self) -> bool:
        """Restore diplomacy and optionally declare war; return whether war was declared."""

        from .diplomacy import RelationshipState

        await self.client.refresh_diplomacy_state()
        if self.client.relationship.state is RelationshipState.WAR:
            return False
        if not self.config.declare_war_if_needed:
            raise ValueError("conflict controller requires relationship state war")
        self.client.declare_war(self.config.coalition, reason=self.config.war_reason)
        await self.client.persist_diplomacy_state()
        return True

    async def run_cycle(
        self,
        *,
        execute: bool = True,
        on_event: Callable[[object], None] | None = None,
    ) -> ConflictControllerCycle:
        """Run one bounded decision cycle using coalition-private INTEL."""

        configured_objectives = self.client.strategic_objectives()
        await self.client.snapshot_statics()
        picture = await self.client.refresh_tactical_picture(
            self.config.coalition,
            self.config.intel_id,
        )
        for objective in configured_objectives:
            if self.client.strategic_objective(objective.objective_id) is None:
                self.client.add_strategic_objective(objective, sync=False)
        await self.ensure_war()
        # Planning and portfolio reservations must use current COHORT availability
        # and group strength, especially after SetGrouping() changes in MOOSE.
        await self.client.refresh_legion_state()
        self.client.sync_strategic_objectives(source=f"{self.config.controller_id}.cycle")
        self._cycle_number += 1
        generated_goals, generated_plans, issues = self._prepare_candidates(picture)
        plans = self._owned_nonterminal_plans()
        portfolio = self.client.select_strategic_goal_portfolio(
            self.config.coalition,
            plans=plans,
            max_concurrent_goals=self.config.max_concurrent_goals,
        )

        executions: list[OperationalPlanExecution] = []
        if execute:
            for selection in portfolio.selected:
                plan = self.client.operational_plan(selection.plan_id)
                if plan is None or plan.status is OperationalPlanStatus.EXECUTING:
                    continue
                assessment = await self.client.refresh_and_validate_operational_plan(plan)
                if not assessment.feasible:
                    issues.append(
                        ConflictControllerIssue(
                            self.client.strategic_goal(plan.goal_id).objective_id,
                            "validation",
                            "selected plan became infeasible during final validation",
                        )
                    )
                    continue
                self.client.approve_operational_plan(
                    plan,
                    reason=f"Approved by {self.config.controller_id} cycle {self._cycle_number}",
                )
                try:
                    execution = await self.client.execute_plan(
                        plan,
                        mission_timeout_s=self.config.mission_timeout_s,
                        on_event=on_event,
                    )
                except Exception as exc:
                    issues.append(
                        ConflictControllerIssue(
                            self.client.strategic_goal(plan.goal_id).objective_id,
                            "execution",
                            str(exc),
                        )
                    )
                else:
                    executions.append(execution)

        return ConflictControllerCycle(
            coalition=self.config.coalition,
            mission_time=picture.clock.mission_time if picture.clock else None,
            generated_goal_ids=tuple(goal.goal_id for goal in generated_goals),
            generated_plan_ids=tuple(plan.plan_id for plan in generated_plans),
            portfolio=portfolio,
            executions=tuple(executions),
            issues=tuple(issues),
        )

    def _prepare_candidates(
        self,
        picture: TacticalPicture,
    ) -> tuple[list[StrategicGoal], list[OperationalPlan], list[ConflictControllerIssue]]:
        goals: list[StrategicGoal] = []
        plans: list[OperationalPlan] = []
        issues: list[ConflictControllerIssue] = []
        for objective in self.client.strategic_objectives():
            desired = evaluate_strategic_objective(
                objective,
                self.config.coalition,
                relationship=self.client.relationship,
            ).action
            existing = self._open_goal_for_objective(objective.objective_id)
            if existing is not None and existing.action is not desired:
                if existing.status is StrategicGoalStatus.PLANNED:
                    self.client.cancel_strategic_goal(existing, reason="objective state changed before selection")
        generation = self.client.generate_strategic_goals(
            self.config.coalition,
            generation_id=f"CYCLE:{self._cycle_number}",
            config=StrategicGoalGenerationConfig(
                defense_duration_s=self.config.defense_duration_s,
                destroy_required_damage=self.config.destroy_required_damage,
            ),
            metadata={"conflict_controller": self.config.controller_id},
        )
        for goal in generation.goals:
            objective = self.client.strategic_objective(goal.objective_id)
            if objective is None:
                continue
            desired = goal.action
            token = objective.objective_id.removeprefix("OBJECTIVE:").replace(" ", "-")
            try:
                plan_id = (
                    f"PLAN:{self.config.coalition}:{desired.value}:{token}:"
                    f"CYCLE:{self._cycle_number}"
                )
                if desired is StrategicGoalAction.CAPTURE:
                    plan = self.client.propose_capture_plan(goal, picture, plan_id=plan_id)
                elif desired is StrategicGoalAction.DEFEND:
                    plan = self.client.propose_defend_plan(goal, picture, plan_id=plan_id)
                else:
                    plan = self.client.propose_destroy_plan(goal, picture, plan_id=plan_id)
                plan.metadata["conflict_controller"] = self.config.controller_id
                self.client.add_operational_plan(plan)
            except Exception as exc:
                self.client.cancel_strategic_goal(goal, reason=f"planning failed: {exc}")
                issues.append(ConflictControllerIssue(objective.objective_id, "planning", str(exc)))
                continue
            goals.append(goal)
            plans.append(plan)
        return goals, plans, issues

    def _desired_action(self, objective: StrategicObjective) -> StrategicGoalAction | None:
        return evaluate_strategic_objective(objective, self.config.coalition).action

    def _open_goal_for_objective(self, objective_id: str) -> StrategicGoal | None:
        for goal in self.client.strategic_goals(
            coalition=self.config.coalition,
            objective_id=objective_id,
        ):
            if (
                goal.metadata.get("conflict_controller") == self.config.controller_id
                and goal.status in {StrategicGoalStatus.PLANNED, StrategicGoalStatus.ACTIVE}
            ):
                return goal
        return None

    def _owned_nonterminal_plans(self) -> tuple[OperationalPlan, ...]:
        terminal = {
            OperationalPlanStatus.COMPLETED,
            OperationalPlanStatus.FAILED,
            OperationalPlanStatus.CANCELLED,
        }
        return tuple(
            plan
            for plan in self.client.operational_plans()
            if plan.metadata.get("conflict_controller") == self.config.controller_id
            and plan.status not in terminal
        )


__all__ = [
    "ConflictControllerConfig",
    "ConflictControllerCycle",
    "ConflictControllerIssue",
    "RuleBasedConflictController",
]
