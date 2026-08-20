"""Strategic objective and goal lifecycle behind the public SDK facade."""

from __future__ import annotations

from typing import Any

from .diplomacy import CoalitionRelationship
from .infrastructure_sites import TheaterInfrastructureSites
from .operational import OperationalPlanRegistry
from .railway_infrastructure import TheaterRailwayInfrastructure
from .settlements import TheaterSettlements
from .state import MooseBridgeState
from .strategic import (
    ObjectiveEvent,
    StrategicGoal,
    StrategicGoalEvent,
    StrategicGoalRegistry,
    StrategicObjective,
    StrategicObjectiveRegistry,
)
from .strategic_feedback import (
    StrategicFeedbackMonitor,
    StrategicFeedbackPolicy,
)
from .strategic_goals import (
    StrategicGoalGenerationConfig,
    StrategicGoalGenerationResult,
    generate_strategic_goals,
)
from .strategic_objectives import (
    StrategicObjectiveGenerationConfig,
    StrategicObjectiveGenerationResult,
    generate_strategic_objectives,
)
from .strategic_scope import StrategicTerritoryScope
from .strategic_selection import StrategicGoalPortfolioSelector
from .strategic_verification import StrategicVerificationRegistry
from .transport_infrastructure import TheaterTransportInfrastructure


class StrategicPlanningService:
    """Own strategic registries and their state-transition rules."""

    def __init__(self, *, persistent_shortfall_s: float = 300.0) -> None:
        self.objectives = StrategicObjectiveRegistry()
        self.goals = StrategicGoalRegistry(self.objectives)
        self.plans = OperationalPlanRegistry(self.goals)
        self.feedback = StrategicFeedbackMonitor(
            self.goals,
            self.plans,
            persistent_shortfall_s=persistent_shortfall_s,
        )
        self.feedback_policy = StrategicFeedbackPolicy(
            self.objectives,
            self.goals,
            self.plans,
        )
        self.goal_selector = StrategicGoalPortfolioSelector(
            self.objectives,
            self.goals,
            self.plans,
        )
        self._goal_generation_number = 0

    def clear_mission(self) -> None:
        """Discard all mission-scoped strategic state."""

        self.feedback.clear()
        self.plans.clear()
        self.goals.clear()
        self.objectives.clear()
        self._goal_generation_number = 0

    def add_objective(
        self,
        objective: StrategicObjective,
        *,
        replace: bool = False,
    ) -> StrategicObjective:
        return self.objectives.add(objective, replace=replace)

    def remove_objective(
        self,
        objective: StrategicObjective | str,
        *,
        mission_time: float,
    ) -> StrategicObjective:
        removed = self.objectives.remove(objective)
        self.goals.sync(mission_time=mission_time, source="objective.removed")
        return removed

    def objective(self, objective_id: str) -> StrategicObjective | None:
        return self.objectives.get(objective_id)

    def objective_list(self, **filters: Any) -> tuple[StrategicObjective, ...]:
        return self.objectives.filter(**filters)

    def sync_objectives(
        self,
        state: MooseBridgeState,
        *,
        mission_time: float,
        source: str,
    ) -> tuple[ObjectiveEvent, ...]:
        events = self.objectives.sync(state, source=source)
        self.goals.sync(mission_time=mission_time, source=source)
        return events

    def generate_objectives(
        self,
        state: MooseBridgeState,
        scope: StrategicTerritoryScope,
        *,
        settlements: TheaterSettlements | None = None,
        transport: TheaterTransportInfrastructure | None = None,
        railway: TheaterRailwayInfrastructure | None = None,
        infrastructure: TheaterInfrastructureSites | None = None,
        verifications: StrategicVerificationRegistry | None = None,
        config: StrategicObjectiveGenerationConfig | None = None,
        register: bool = True,
        replace: bool = False,
        mission_time: float,
    ) -> StrategicObjectiveGenerationResult:
        result = generate_strategic_objectives(
            state,
            scope,
            settlements=settlements,
            transport=transport,
            railway=railway,
            infrastructure=infrastructure,
            verifications=verifications,
            config=config,
        )
        if not register:
            return result

        generated_ids = {objective.objective_id for objective in result.objectives}
        if replace:
            for existing in self.objectives.all():
                if existing.metadata.get("generated") and existing.objective_id not in generated_ids:
                    self.objectives.remove(existing)
        for objective in result.objectives:
            existing = self.objectives.get(objective.objective_id)
            if existing is not None and not replace:
                continue
            self.objectives.add(objective, replace=existing is not None)
        self.sync_objectives(
            state,
            mission_time=mission_time,
            source="strategic_objective_generation",
        )
        return result

    def add_goal(
        self,
        goal: StrategicGoal,
        *,
        replace: bool = False,
        activate: bool = False,
        mission_time: float,
    ) -> StrategicGoal:
        added = self.goals.add(goal, replace=replace)
        if activate:
            self.activate_goal(added, mission_time=mission_time)
        return added

    def generate_goals(
        self,
        coalition: str,
        *,
        relationship: CoalitionRelationship,
        mission_time: float,
        config: StrategicGoalGenerationConfig | None = None,
        register: bool = True,
        generation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> StrategicGoalGenerationResult:
        self._goal_generation_number += 1
        resolved_generation_id = generation_id or f"AUTO:{self._goal_generation_number}"
        result = generate_strategic_goals(
            self.objective_list(),
            coalition,
            relationship=relationship,
            existing_goals=self.goal_list(),
            mission_time=mission_time,
            generation_id=resolved_generation_id,
            config=config,
            metadata=metadata,
        )
        if register:
            for goal in result.goals:
                self.goals.add(goal)
        return result

    def activate_goal(self, goal: StrategicGoal | str, *, mission_time: float) -> StrategicGoal:
        activated = self.goals.activate(goal, mission_time=mission_time)
        self.goals.sync(mission_time=mission_time, source="current_state")
        return activated

    def cancel_goal(
        self,
        goal: StrategicGoal | str,
        *,
        mission_time: float,
        reason: str | None = None,
    ) -> StrategicGoal:
        return self.goals.cancel(goal, mission_time=mission_time, reason=reason)

    def complete_goal(
        self,
        goal: StrategicGoal | str,
        *,
        achieved: bool,
        mission_time: float,
        reason: str | None = None,
    ) -> StrategicGoal:
        return self.goals.complete_manual(
            goal,
            achieved=achieved,
            mission_time=mission_time,
            reason=reason,
        )

    def remove_goal(self, goal: StrategicGoal | str) -> StrategicGoal:
        return self.goals.remove(goal)

    def goal(self, goal_id: str) -> StrategicGoal | None:
        return self.goals.get(goal_id)

    def goal_list(self, **filters: Any) -> tuple[StrategicGoal, ...]:
        return self.goals.filter(**filters)

    def sync_goals(self, *, mission_time: float, source: str) -> tuple[StrategicGoalEvent, ...]:
        return self.goals.sync(mission_time=mission_time, source=source)
