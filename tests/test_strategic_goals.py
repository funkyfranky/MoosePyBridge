"""Tests for coalition-specific strategic-goal derivation."""

from __future__ import annotations

from moosebridge import (
    CoalitionRelationship,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    RelationshipState,
    StrategicGoalAction,
    StrategicObjective,
    format_strategic_goal_generation,
    generate_strategic_goals,
)


def _objective(
    name: str,
    kind: ObjectiveKind,
    owner: str | None,
    *,
    contested: bool = False,
    components: tuple[ObjectiveComponent, ...] = (),
    metadata: dict[str, object] | None = None,
) -> StrategicObjective:
    managed = kind is ObjectiveKind.OPSZONE
    return StrategicObjective(
        objective_id=f"OBJECTIVE:{name}",
        name=name,
        kind=kind,
        control_object_id=f"OPSZONE:{name}" if managed else None,
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED if managed else OwnershipPolicy.FIXED,
        owner=owner,
        contested=contested,
        components=components,
        strategic_value=80,
        priority=70,
        metadata=metadata or {},
    )


def test_war_derives_only_currently_executable_actions() -> None:
    relationship = CoalitionRelationship()
    relationship.state = RelationshipState.WAR
    objectives = (
        _objective("Enemy Zone", ObjectiveKind.OPSZONE, "red"),
        _objective("Contested Camp", ObjectiveKind.OPSZONE, "blue", contested=True),
        _objective(
            "Enemy Depot",
            ObjectiveKind.DEPOT,
            "red",
            components=(ObjectiveComponent("STATIC:Depot"),),
        ),
        _objective(
            "Neutral Depot",
            ObjectiveKind.DEPOT,
            "neutral",
            components=(ObjectiveComponent("STATIC:Neutral"),),
        ),
        _objective("Enemy Airbase", ObjectiveKind.AIRBASE, "red"),
        _objective(
            "Outside",
            ObjectiveKind.OPSZONE,
            "red",
            metadata={"scope_state": "out_of_scope"},
        ),
    )

    result = generate_strategic_goals(
        objectives,
        "blue",
        relationship=relationship,
        mission_time=100,
        generation_id="TEST",
    )

    assert {goal.action for goal in result.goals} == {
        StrategicGoalAction.CAPTURE,
        StrategicGoalAction.DEFEND,
        StrategicGoalAction.DESTROY,
    }
    assert {goal.objective_id for goal in result.goals} == {
        "OBJECTIVE:Enemy Zone",
        "OBJECTIVE:Contested Camp",
        "OBJECTIVE:Enemy Depot",
    }
    defend = next(goal for goal in result.goals if goal.action is StrategicGoalAction.DEFEND)
    assert defend.deadline_mission_time == 1900
    destroy = next(goal for goal in result.goals if goal.action is StrategicGoalAction.DESTROY)
    assert destroy.required_damage == 0.7
    reasons = {item.objective_id: item.reason for item in result.rejected}
    assert "neutral" in reasons["OBJECTIVE:Neutral Depot"]
    assert "no supported" in reasons["OBJECTIVE:Enemy Airbase"]
    assert "outside strategic scope" in reasons["OBJECTIVE:Outside"]


def test_relationship_blocks_offense_but_keeps_defense() -> None:
    result = generate_strategic_goals(
        (
            _objective("Enemy Zone", ObjectiveKind.OPSZONE, "red"),
            _objective("Contested Camp", ObjectiveKind.OPSZONE, "blue", contested=True),
        ),
        "blue",
        relationship=CoalitionRelationship(),
        mission_time=100,
    )

    assert [goal.action for goal in result.goals] == [StrategicGoalAction.DEFEND]
    capture = next(item for item in result.rejected if item.objective_id == "OBJECTIVE:Enemy Zone")
    assert capture.action is StrategicGoalAction.CAPTURE
    assert "peace" in capture.reason


def test_sdk_registers_once_and_reports_auditable_decisions() -> None:
    client = MooseBridgeClient(MooseBridgeServer())
    client.relationship.state = RelationshipState.WAR
    client.add_strategic_objective(_objective("Enemy Zone", ObjectiveKind.OPSZONE, "red"), sync=False)

    first = client.generate_strategic_goals("blue", generation_id="TEST")
    second = client.generate_strategic_goals("blue", generation_id="TEST-2")

    assert len(first.goals) == 1
    assert second.goals == ()
    assert "open goal already exists" in second.rejected[0].reason
    rendered = format_strategic_goal_generation(first)
    assert "coalition=blue" in rendered
    assert "capture=1" in rendered

