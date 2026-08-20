"""Focused tests for mission-scoped strategic planning state."""

from __future__ import annotations

from moosebridge import (
    CoalitionRelationship,
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    RelationshipState,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
)
from moosebridge.strategic_planning_service import StrategicPlanningService


def _enemy_zone() -> StrategicObjective:
    return StrategicObjective(
        objective_id="OBJECTIVE:Enemy Zone",
        name="Enemy Zone",
        kind=ObjectiveKind.OPSZONE,
        control_object_id="OPSZONE:Enemy Zone",
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        owner="red",
    )


def _enemy_depot() -> StrategicObjective:
    return StrategicObjective(
        objective_id="OBJECTIVE:Enemy Depot",
        name="Enemy Depot",
        kind=ObjectiveKind.DEPOT,
        control_object_id=None,
        ownership_policy=OwnershipPolicy.FIXED,
        owner="red",
        components=(ObjectiveComponent("STATIC:Enemy Depot"),),
        strategic_value=80.0,
        priority=70.0,
    )


def test_service_owns_dependent_objective_and_goal_lifecycle() -> None:
    service = StrategicPlanningService()
    objective = service.add_objective(_enemy_zone())
    goal = service.add_goal(
        StrategicGoal(
            goal_id="GOAL:Capture Enemy Zone",
            name="Capture Enemy Zone",
            coalition="blue",
            action=StrategicGoalAction.CAPTURE,
            objective_id=objective.objective_id,
        ),
        activate=True,
        mission_time=10.0,
    )

    assert goal.status is StrategicGoalStatus.ACTIVE

    removed = service.remove_objective(objective, mission_time=20.0)

    assert removed is objective
    assert service.objective(objective.objective_id) is None
    assert goal.status is StrategicGoalStatus.FAILED
    assert goal.failure_reason == "objective_removed"


def test_service_reset_clears_mission_state_and_generation_counter() -> None:
    service = StrategicPlanningService()
    relationship = CoalitionRelationship()
    relationship.state = RelationshipState.WAR
    service.add_objective(_enemy_depot())

    first = service.generate_goals(
        "blue",
        relationship=relationship,
        mission_time=10.0,
    )

    assert len(first.goals) == 1
    assert first.goals[0].metadata["generation_id"] == "AUTO:1"
    assert service.goal_list() == first.goals
    assert service.feedback.events

    service.clear_mission()

    assert service.objective_list() == ()
    assert service.goal_list() == ()
    assert service.plans.all() == ()
    assert service.feedback.events == ()

    service.add_objective(_enemy_depot())
    after_reset = service.generate_goals(
        "blue",
        relationship=relationship,
        mission_time=20.0,
    )

    assert len(after_reset.goals) == 1
    assert after_reset.goals[0].metadata["generation_id"] == "AUTO:1"
