from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from moosebridge.audit import AUDIT_SCHEMA_VERSION, AuditRetentionConfig, AuditStore, latest_attempt_records
from moosebridge.operational_audit import (
    goal_from_snapshot,
    goal_snapshot,
    objective_from_snapshot,
    objective_snapshot,
)
from moosebridge.strategic import (
    CaptureBehavior,
    ComponentHealthEstimate,
    GoalCondition,
    GoalConditionMatch,
    ObjectiveComponent,
    ObjectiveKind,
    ObjectiveStatus,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalEffect,
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


def _execution_payload(session="session", generation=0, attempt="PLAN:1/ATTEMPT:1", **extra):
    return {
        "audit_session_id": session, "mission_generation": generation,
        "plan_id": "PLAN:1", "attempt_id": attempt, "attempt_number": 1,
        "status": "executing", **extra,
    }


def test_compaction_preserves_attempts_diplomacy_and_coordinator_recovery(tmp_path) -> None:
    from moosebridge.strategic_coordinator import BilateralConflictCoordinator, StrategicCoordinatorConfig
    from moosebridge.clock import DcsTime
    import asyncio

    path = tmp_path / "audit.jsonl"
    config = AuditRetentionConfig(max_bytes=100_000, history_records=2)
    store = AuditStore(path, retention=config, active_scope=("session", 0))
    for i in range(8):
        store.append("operational_plan.execution", _execution_payload(events=list(range(i))))
        store.append("strategic.diplomacy_state", {
            "audit_session_id": "session", "mission_generation": 0, "incidents": list(range(i)),
        })
    store.append("operational_plan.execution", _execution_payload(
        attempt="PLAN:1/ATTEMPT:2", attempt_number=2, status="completed",
    ))
    scope = {"audit_session_id": "session", "mission_generation": 0}
    store.append("strategic_conflict_cycle", {
        **scope, "coalition": "blue", "cycle_number": 1, "started_mission_time": 100,
        "status": "blocked", "attempts": [{
            "candidate_id": "candidate", "objective_id": "objective", "status": "blocked",
            "cooldown_until": 400,
        }],
    })
    store.append("strategic_conflict_cycle", {
        **scope, "coalition": "blue", "cycle_number": 2, "started_mission_time": 200,
        "status": "no_selection", "attempts": [],
    })
    # A delayed older cycle must not replace the current schedule or cooldown.
    store.append("strategic_conflict_cycle", {
        **scope, "coalition": "blue", "cycle_number": 1, "started_mission_time": 50,
        "status": "blocked", "attempts": [{
            "candidate_id": "candidate", "objective_id": "objective", "status": "blocked",
            "cooldown_until": 350,
        }],
    })
    for i in range(10):
        store.append("strategic_decision", {**scope, "sequence": i})

    async def recover(source):
        class Server:
            async def query_audit_records(self, record_type=None, latest_attempts=False):
                records = source.query(record_type=record_type)
                # The fixture snapshots are deliberately not coordinator-owned.
                return records
        client = SimpleNamespace(
            state=SimpleNamespace(audit_session_id="session", mission_generation=0, clock=DcsTime(200)),
            server=Server(),
        )
        coordinator = BilateralConflictCoordinator(client, None, StrategicCoordinatorConfig())
        await coordinator._load_audit_state()
        return coordinator.cooldowns, coordinator._cycle_numbers, coordinator._not_before_mission_time

    expected_recovery = asyncio.run(recover(store))
    store.compact()
    store.close()
    reloaded = AuditStore(path, retention=config)
    attempts = reloaded.query(record_type="operational_plan.execution")
    assert len(attempts) == 2
    assert attempts[0]["payload"]["events"] == list(range(7))
    assert attempts[1]["payload"]["status"] == "completed"
    assert len(reloaded.query(record_type="strategic.diplomacy_state")) == 1
    assert len(reloaded.query(record_type="strategic_decision")) == 2
    assert asyncio.run(recover(reloaded)) == expected_recovery
    assert expected_recovery[0][0].available_mission_time == 400
    assert expected_recovery[2]["blue"] == 500


def test_compaction_keeps_active_scope_and_separates_reused_attempt_ids(tmp_path) -> None:
    store = AuditStore(tmp_path / "audit.jsonl", retention=AuditRetentionConfig(100_000, 0, 2),
                       active_scope=("active", 0))
    store.append("operational_plan.execution", _execution_payload("active", status="executing"))
    store.append("operational_plan.execution", _execution_payload("old", status="completed"))
    store.append("operational_plan.execution", _execution_payload("newer", status="failed"))
    assert len(latest_attempt_records(store.query())) == 3
    store.compact()
    assert [record["payload"]["audit_session_id"] for record in store.query()] == ["active", "newer"]
    assert store.query()[0]["payload"]["status"] == "executing"
    store.close()


def test_large_checkpoint_is_preserved_and_overshoot_reported(tmp_path) -> None:
    store = AuditStore(tmp_path / "audit.jsonl", retention=AuditRetentionConfig(256, 2))
    store.append("operational_plan.execution", _execution_payload(events=["x" * 1024]))
    store.append("strategic_decision", {"explanation": "not required for recovery"})
    status = store.compact()
    assert len(store.query()) == 1
    assert status["protected_over_target"] is True
    assert status["protected_bytes"] > 256
    store.close()
    assert AuditStore(store.path).query()[0]["payload"]["events"] == ["x" * 1024]


@pytest.mark.parametrize("persistent", [False, True])
def test_retention_bounds_repeated_history_in_memory_and_on_disk(tmp_path, persistent) -> None:
    path = tmp_path / "audit.jsonl" if persistent else None
    store = AuditStore(path, retention=AuditRetentionConfig(4096, 3))
    for i in range(120):
        store.append("strategic_decision", {"sequence": i, "explanation": "x" * 200})
    assert store.status()["compactions"] > 0
    assert store.status()["indexed_bytes"] < 4096
    if path:
        assert path.stat().st_size == store.status()["file_bytes"] < 4096
    assert store.query()[-1]["payload"]["sequence"] == 119
    store.close()


def test_disabled_retention_keeps_full_history_and_detaches_payload(tmp_path) -> None:
    store = AuditStore(tmp_path / "audit.jsonl", retention=AuditRetentionConfig(0))
    payload = {"events": []}
    store.append("test", payload)
    payload["events"].append("later")
    for i in range(20):
        store.append("test", {"i": i})
    store.compact()
    assert len(store.query()) == 21
    assert store.query()[0]["payload"]["events"] == []
    store.close()


def test_failed_atomic_replace_preserves_original_and_append_stream(tmp_path, monkeypatch) -> None:
    import moosebridge.audit as audit

    path = tmp_path / "audit.jsonl"
    store = AuditStore(path, retention=AuditRetentionConfig(100_000, 1))
    store.append("test", {"i": 1})
    store.append("test", {"i": 2})
    original = path.read_bytes()
    def fail_replace(*args):
        raise OSError("replace failed")
    monkeypatch.setattr(audit.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.compact()
    assert path.read_bytes() == original
    assert len(store.query()) == 2
    store.append("test", {"i": 3})
    store.close()
    assert len(AuditStore(path).query()) == 3
    assert list(tmp_path.glob("*.tmp")) == []


def test_existing_large_file_compacts_at_open_and_reloads(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    original = AuditStore(path, retention=AuditRetentionConfig(0))
    for i in range(80):
        original.append("operational_plan.execution", _execution_payload(events=list(range(i))))
    original.close()
    original_size = path.stat().st_size
    store = AuditStore(path, retention=AuditRetentionConfig(2048, 2))
    assert path.stat().st_size == original_size  # Constructor is read-only.
    store.open()
    assert path.stat().st_size < 2048
    store.close()
    assert AuditStore(path).query()[0]["payload"]["events"] == list(range(79))


def test_append_after_partial_trailing_record_survives_restart(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text('{"partial":', encoding="utf-8")
    store = AuditStore(path)
    store.append("test", {"saved": True})
    store.close()
    assert AuditStore(path).query()[0]["payload"] == {"saved": True}


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
        component_health_estimates={
            "STATIC:Warehouse": ComponentHealthEstimate(0.6, "auftrag_summary:AUFTRAG:7", 120.0)
        },
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

    destroy = StrategicGoal(
        goal_id="GOAL:Damage Depot",
        name="Damage Depot",
        coalition="blue",
        action=StrategicGoalAction.DESTROY,
        objective_id=objective.objective_id,
        required_damage=0.7,
    )
    restored_destroy = goal_from_snapshot(goal_snapshot(destroy))
    assert restored_destroy.required_damage == 0.7
    assert restored_destroy.success_conditions == (GoalCondition.health_at_most(0.3),)

    runway_denial = StrategicGoal(
        goal_id="GOAL:Deny runway",
        name="Deny runway",
        coalition="blue",
        action=StrategicGoalAction.DISABLE,
        objective_id=objective.objective_id,
        effect=StrategicGoalEffect.DENY_RUNWAY,
    )
    restored_runway_denial = goal_from_snapshot(goal_snapshot(runway_denial))
    assert restored_runway_denial.effect is StrategicGoalEffect.DENY_RUNWAY
    assert restored_runway_denial == runway_denial
