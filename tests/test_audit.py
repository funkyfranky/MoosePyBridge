from __future__ import annotations

import json
import logging

from moosebridge.audit import AUDIT_SCHEMA_VERSION, AuditStore, latest_attempt_records
from moosebridge.operational_audit import (
    goal_from_snapshot,
    goal_snapshot,
    objective_from_snapshot,
    objective_snapshot,
)
from moosebridge.strategic import (
    CaptureBehavior,
    GoalCondition,
    GoalConditionMatch,
    ObjectiveComponent,
    ObjectiveKind,
    ObjectiveStatus,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
)


def test_audit_store_survives_restart_and_keeps_latest_attempt_snapshots(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    first = AuditStore(path)
    first.append(
        "operational_plan.execution",
        {"plan_id": "PLAN:1", "attempt_id": "PLAN:1/ATTEMPT:1", "attempt_number": 1, "status": "executing"},
    )
    first.append(
        "operational_plan.execution",
        {"plan_id": "PLAN:1", "attempt_id": "PLAN:1/ATTEMPT:1", "attempt_number": 1, "status": "completed"},
    )
    first.close()

    second = AuditStore(path)
    records = second.query(record_type="operational_plan.execution", plan_id="PLAN:1")
    latest = latest_attempt_records(records)

    assert len(records) == 2
    assert len(latest) == 1
    assert latest[0]["schema_version"] == AUDIT_SCHEMA_VERSION
    assert latest[0]["payload"]["status"] == "completed"


def test_audit_store_ignores_invalid_lines_but_loads_valid_records(tmp_path, caplog) -> None:
    path = tmp_path / "audit.jsonl"
    valid = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "record_type": "test",
        "recorded_at": "2026-08-04T10:00:00Z",
        "payload": {"plan_id": "PLAN:1"},
    }
    path.write_text("not json\n" + json.dumps(valid) + "\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        store = AuditStore(path)

    assert store.query(record_type="test") == (valid,)
    assert "Ignoring invalid audit record" in caplog.text


def test_strategic_audit_snapshots_roundtrip_typed_fields() -> None:
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Depot",
        name="Depot",
        kind=ObjectiveKind.DEPOT,
        control_object_id="TERRITORY:North",
        ownership_policy=OwnershipPolicy.TERRITORY_INHERITED,
        components=(
            ObjectiveComponent(
                "STATIC:Warehouse",
                role="storage",
                weight=2.5,
                capture_behavior=CaptureBehavior.RESPAWN_FOR_NEW_OWNER,
            ),
        ),
        owner="red",
        status=ObjectiveStatus.DEGRADED,
        health=0.6,
        contested=True,
    )
    goal = StrategicGoal(
        goal_id="GOAL:Capture Depot",
        name="Capture Depot",
        coalition="blue",
        action=StrategicGoalAction.CAPTURE,
        objective_id=objective.objective_id,
        status=StrategicGoalStatus.ACTIVE,
        success_conditions=(GoalCondition.owner_is("blue"), GoalCondition.contested_is(False)),
        success_match=GoalConditionMatch.ALL,
    )

    restored_objective = objective_from_snapshot(objective_snapshot(objective))
    restored_goal = goal_from_snapshot(goal_snapshot(goal))

    assert restored_objective == objective
    assert restored_objective.components[0].capture_behavior is CaptureBehavior.RESPAWN_FOR_NEW_OWNER
    assert restored_goal == goal
    assert restored_goal.success_conditions == goal.success_conditions
