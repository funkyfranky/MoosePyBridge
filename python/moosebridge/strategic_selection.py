"""Capacity-aware selection of multiple concurrent strategic goals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .diplomacy import CoalitionDoctrine, CoalitionDoctrinePreset, CoalitionRelationship
from .legions import Cohort, Legion
from .operational import (
    OperationalPlan,
    OperationalPlanAssessment,
    OperationalPlanRegistry,
    OperationalPlanStatus,
)
from .strategic import (
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalRegistry,
    StrategicGoalStatus,
    StrategicObjective,
    StrategicObjectiveRegistry,
    normalize_coalition,
)


@dataclass(slots=True, frozen=True)
class StrategicGoalSelection:
    """Admission result for one goal and its candidate operational plan."""

    goal_id: str
    plan_id: str
    selected: bool
    reason: str
    goal_priority: float
    objective_priority: float
    strategic_value: float
    deadline_mission_time: float | None
    doctrine_tier: int
    reserved_assets: tuple[tuple[str, int], ...] = ()
    assessment: OperationalPlanAssessment | None = None


@dataclass(slots=True, frozen=True)
class StrategicGoalPortfolio:
    """Auditable set of concurrently admissible strategic goals."""

    coalition: str
    mission_time: float | None
    decisions: tuple[StrategicGoalSelection, ...]
    reserved_assets: tuple[tuple[str, int], ...]

    @property
    def selected(self) -> tuple[StrategicGoalSelection, ...]:
        return tuple(item for item in self.decisions if item.selected)

    @property
    def deferred(self) -> tuple[StrategicGoalSelection, ...]:
        return tuple(item for item in self.decisions if not item.selected)


class StrategicGoalPortfolioSelector:
    """Greedily admit prioritized goals without overbooking COHORT assets."""

    _TERMINAL_PLAN_STATUSES = {
        OperationalPlanStatus.COMPLETED,
        OperationalPlanStatus.FAILED,
        OperationalPlanStatus.CANCELLED,
    }
    _TERMINAL_GOAL_STATUSES = {
        StrategicGoalStatus.ACHIEVED,
        StrategicGoalStatus.FAILED,
        StrategicGoalStatus.CANCELLED,
    }

    def __init__(
        self,
        objectives: StrategicObjectiveRegistry,
        goals: StrategicGoalRegistry,
        plans: OperationalPlanRegistry,
    ) -> None:
        self.objectives = objectives
        self.goals = goals
        self.plans = plans

    def select(
        self,
        coalition: str,
        *,
        legions: Iterable[Legion],
        cohorts: Iterable[Cohort],
        mission_time: float | None = None,
        plans: Iterable[OperationalPlan] | None = None,
        max_concurrent_goals: int | None = None,
        relationship: CoalitionRelationship | None = None,
        doctrine: CoalitionDoctrine | None = None,
    ) -> StrategicGoalPortfolio:
        """Select multiple plans in priority order against one capacity ledger."""

        coalition = normalize_coalition(coalition) or ""
        if coalition not in {"blue", "red"}:
            raise ValueError("strategic goal portfolios require coalition blue or red")
        if max_concurrent_goals is not None and max_concurrent_goals < 1:
            raise ValueError("max_concurrent_goals must be at least one")

        legion_items = tuple(legions)
        cohort_items = tuple(cohorts)
        candidate_plans = tuple(plans) if plans is not None else self.plans.all()
        candidates: list[tuple[OperationalPlan, StrategicGoal, StrategicObjective]] = []
        seen_goals: set[str] = set()
        for plan in candidate_plans:
            if plan.coalition != coalition or plan.status in self._TERMINAL_PLAN_STATUSES:
                continue
            goal = self.goals.get(plan.goal_id)
            if goal is None or goal.status in self._TERMINAL_GOAL_STATUSES:
                continue
            objective = self.objectives.get(goal.objective_id)
            if objective is None:
                continue
            if goal.goal_id in seen_goals:
                raise ValueError(f"multiple candidate plans for strategic goal: {goal.goal_id}")
            seen_goals.add(goal.goal_id)
            candidates.append((plan, goal, objective))

        candidates.sort(key=lambda item: self._priority_key(item[1], item[2], doctrine))
        reservations: dict[str, int] = {}
        decisions: list[StrategicGoalSelection] = []
        selected_count = 0
        for plan, goal, objective in candidates:
            doctrine_tier = _doctrine_tier(goal, doctrine)
            if relationship is not None:
                allowed, reason = relationship.allows_goal(goal.action, objective)
                if not allowed:
                    decisions.append(
                        self._decision(
                            plan,
                            goal,
                            objective,
                            False,
                            reason,
                            doctrine_tier=doctrine_tier,
                        )
                    )
                    continue
            if plan.status is OperationalPlanStatus.BLOCKED:
                decisions.append(
                    self._decision(
                        plan,
                        goal,
                        objective,
                        False,
                        "plan is blocked and requires replanning",
                        doctrine_tier=doctrine_tier,
                    )
                )
                continue
            if max_concurrent_goals is not None and selected_count >= max_concurrent_goals:
                decisions.append(
                    self._decision(
                        plan,
                        goal,
                        objective,
                        False,
                        "portfolio concurrency limit reached",
                        doctrine_tier=doctrine_tier,
                    )
                )
                continue
            if plan.status is OperationalPlanStatus.EXECUTING:
                decisions.append(
                    self._decision(
                        plan,
                        goal,
                        objective,
                        True,
                        "plan is already executing",
                        doctrine_tier=doctrine_tier,
                    )
                )
                selected_count += 1
                continue
            assessment = self.plans.validate(
                plan,
                legions=legion_items,
                cohorts=cohort_items,
                mission_time=mission_time,
                update_plan=False,
                reserved_assets=reservations,
            )
            if not assessment.feasible:
                decisions.append(
                    self._decision(
                        plan,
                        goal,
                        objective,
                        False,
                        "insufficient remaining portfolio capacity or invalid plan constraint",
                        doctrine_tier=doctrine_tier,
                        assessment=assessment,
                    )
                )
                continue
            plan_reservations = _concurrent_plan_reservations(assessment)
            for cohort_id, count in plan_reservations.items():
                reservations[cohort_id] = reservations.get(cohort_id, 0) + count
            decisions.append(
                self._decision(
                    plan,
                    goal,
                    objective,
                    True,
                    "admitted within remaining portfolio capacity",
                    doctrine_tier=doctrine_tier,
                    reservations=plan_reservations,
                    assessment=assessment,
                )
            )
            selected_count += 1

        return StrategicGoalPortfolio(
            coalition,
            mission_time,
            tuple(decisions),
            tuple(sorted(reservations.items())),
        )

    @staticmethod
    def _priority_key(
        goal: StrategicGoal,
        objective: StrategicObjective,
        doctrine: CoalitionDoctrine | None,
    ) -> tuple[int, float, float, float, float, str]:
        deadline = goal.deadline_mission_time if goal.deadline_mission_time is not None else float("inf")
        return (
            _doctrine_tier(goal, doctrine),
            -goal.priority,
            -objective.priority,
            -objective.strategic_value,
            deadline,
            goal.goal_id,
        )

    @staticmethod
    def _decision(
        plan: OperationalPlan,
        goal: StrategicGoal,
        objective: StrategicObjective,
        selected: bool,
        reason: str,
        *,
        doctrine_tier: int,
        reservations: dict[str, int] | None = None,
        assessment: OperationalPlanAssessment | None = None,
    ) -> StrategicGoalSelection:
        return StrategicGoalSelection(
            goal.goal_id,
            plan.plan_id,
            selected,
            reason,
            goal.priority,
            objective.priority,
            objective.strategic_value,
            goal.deadline_mission_time,
            doctrine_tier,
            tuple(sorted((reservations or {}).items())),
            assessment,
        )


def _concurrent_plan_reservations(assessment: OperationalPlanAssessment) -> dict[str, int]:
    """Reserve each COHORT's largest simultaneous use in any one phase."""

    by_phase: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for requirement in assessment.requirements:
        for allocation in requirement.allocations:
            by_phase[requirement.phase_id][allocation.cohort_id] += allocation.count
    result: dict[str, int] = {}
    for phase_allocations in by_phase.values():
        for cohort_id, count in phase_allocations.items():
            result[cohort_id] = max(result.get(cohort_id, 0), count)
    return result


def _doctrine_tier(goal: StrategicGoal, doctrine: CoalitionDoctrine | None) -> int:
    """Return a small transparent preference tier; zero is preferred."""

    if doctrine is None or doctrine.preset is CoalitionDoctrinePreset.BALANCED:
        return 0
    defensive = goal.action in {StrategicGoalAction.DEFEND, StrategicGoalAction.PROTECT}
    if doctrine.preset in {CoalitionDoctrinePreset.PASSIVE, CoalitionDoctrinePreset.DEFENSIVE}:
        if defensive:
            return 0
        if goal.action in {StrategicGoalAction.DISABLE, StrategicGoalAction.INTERDICT}:
            return 1
        return 2
    if defensive:
        return 2
    if doctrine.preset is CoalitionDoctrinePreset.AGGRESSIVE:
        return 0 if goal.action in {StrategicGoalAction.DESTROY, StrategicGoalAction.CAPTURE} else 1
    return 0 if goal.action in {
        StrategicGoalAction.CAPTURE,
        StrategicGoalAction.DESTROY,
        StrategicGoalAction.INTERDICT,
        StrategicGoalAction.DISABLE,
    } else 1


__all__ = [
    "StrategicGoalPortfolio",
    "StrategicGoalPortfolioSelector",
    "StrategicGoalSelection",
]
