from __future__ import annotations

import asyncio
import json

from moosebridge import (
    CaptureBehavior,
    GoalCondition,
    GoalEvaluationMode,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveComponent,
    ObjectiveKind,
    ObjectiveStatus,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
    StrategicObjectiveRegistry,
    capture_actions,
    format_strategic_goal,
)
from moosebridge.state import MooseBridgeState


def test_dcs_managed_composite_objective_tracks_owner_and_weighted_health() -> None:
    state = MooseBridgeState()
    state.apply_message(
        {
            "type": "snapshot",
            "kind": "airbases",
            "payload": {"airbases": [{"object_id": "AIRBASE:Parchim", "coalition": 2}]},
        }
    )
    state.apply_message(
        {
            "type": "snapshot",
            "kind": "statics",
            "payload": {
                "statics": [
                    {"object_id": "STATIC:Depot-1", "alive": True},
                    {"object_id": "STATIC:Depot-2", "alive": False},
                ]
            },
        }
    )
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Parchim",
        name="Parchim Airbase",
        kind=ObjectiveKind.AIRBASE,
        control_object_id="AIRBASE:Parchim",
        ownership_policy=OwnershipPolicy.DCS_MANAGED,
        components=(
            ObjectiveComponent("STATIC:Depot-1", role="storage", weight=0.75),
            ObjectiveComponent("STATIC:Depot-2", role="storage", weight=0.25),
        ),
        strategic_value=80,
        priority=60,
    )
    registry = StrategicObjectiveRegistry()
    registry.add(objective)

    events = registry.sync(state, source="snapshot.airbases")

    assert objective.owner == "blue"
    assert objective.health == 0.75
    assert objective.status is ObjectiveStatus.DEGRADED
    assert events[0].event == "objective.control_changed"
    assert events[0].source == "snapshot.airbases"

    state.apply_message(
        {
            "type": "snapshot",
            "kind": "airbases",
            "payload": {"airbases": [{"object_id": "AIRBASE:Parchim", "coalition_name": "red"}]},
        }
    )
    events = registry.sync(state, source="airbase.coalition_changed")

    assert objective.owner == "red"
    assert len(events) == 1
    assert events[0].previous_owner == "blue"
    assert events[0].owner == "red"


def test_moose_managed_opszone_controls_owner_and_contested_state() -> None:
    state = MooseBridgeState()
    state.apply_message(
        {
            "type": "snapshot",
            "kind": "opszones",
            "payload": {
                "opszones": [
                    {
                        "object_id": "OPSZONE:Town Fight",
                        "dcs_name": "Town Fight",
                        "object_type": "OPSZONE",
                        "owner_current_name": "red",
                        "is_contested": True,
                    }
                ]
            },
        }
    )
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Town Fight",
        name="Town Fight",
        kind=ObjectiveKind.OPSZONE,
        control_object_id="OPSZONE:Town Fight",
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
    )
    registry = StrategicObjectiveRegistry()
    registry.add(objective)

    events = registry.sync(state, source="opszone.owner_changed")

    assert objective.owner == "red"
    assert objective.contested is True
    assert objective.status is ObjectiveStatus.CONTESTED
    assert {event.event for event in events} == {"objective.control_changed", "objective.contested"}


def test_territory_inherited_objective_uses_territory_coalition() -> None:
    state = MooseBridgeState()
    state.apply_message(
        {
            "type": "snapshot",
            "kind": "territories",
            "payload": {
                "territories": [
                    {
                        "object_id": "TERRITORY:North",
                        "dcs_name": "North",
                        "object_type": "TERRITORY",
                        "coalition": "blue",
                    }
                ]
            },
        }
    )
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Northern Infrastructure",
        name="Northern Infrastructure",
        kind=ObjectiveKind.INFRASTRUCTURE,
        control_object_id="TERRITORY:North",
        ownership_policy=OwnershipPolicy.TERRITORY_INHERITED,
    )
    registry = StrategicObjectiveRegistry()
    registry.add(objective)

    registry.sync(state)

    assert objective.owner == "blue"
    assert objective.status is ObjectiveStatus.OPERATIONAL


def test_capture_actions_only_return_components_requiring_explicit_work() -> None:
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Depot",
        name="Depot",
        kind=ObjectiveKind.DEPOT,
        control_object_id="OPSZONE:Depot",
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        components=(
            ObjectiveComponent("STATIC:Warehouse", capture_behavior=CaptureBehavior.RESPAWN_FOR_NEW_OWNER),
            ObjectiveComponent("STATIC:Shed", capture_behavior=CaptureBehavior.KEEP),
        ),
    )
    registry = StrategicObjectiveRegistry()
    registry.add(objective)
    state = MooseBridgeState()
    state.apply_message(
        {
            "type": "snapshot",
            "kind": "opszones",
            "payload": {
                "opszones": [
                    {
                        "object_id": "OPSZONE:Depot",
                        "dcs_name": "Depot",
                        "object_type": "OPSZONE",
                        "owner_current_name": "red",
                    }
                ]
            },
        }
    )

    control_event = next(event for event in registry.sync(state) if event.event == "objective.control_changed")

    assert [item.object_id for item in capture_actions(control_event, objective)] == ["STATIC:Warehouse"]


def test_registry_supports_runtime_filtering_and_removal() -> None:
    registry = StrategicObjectiveRegistry()
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Dynamic",
        name="Dynamic target",
        kind=ObjectiveKind.CUSTOM,
        control_object_id=None,
        ownership_policy=OwnershipPolicy.FIXED,
        owner="blue",
        priority=75,
    )
    registry.add(objective)

    assert registry.filter(owner="blue", minimum_priority=70) == (objective,)
    assert registry.remove("OBJECTIVE:Dynamic") is objective
    assert registry.get("OBJECTIVE:Dynamic") is None


def test_sdk_registry_updates_from_server_messages_without_polling() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        objective = StrategicObjective(
            objective_id="OBJECTIVE:Parchim",
            name="Parchim",
            kind=ObjectiveKind.AIRBASE,
            control_object_id="AIRBASE:Parchim",
            ownership_policy=OwnershipPolicy.DCS_MANAGED,
        )
        bridge.add_strategic_objective(objective)

        await server._handle_line(
            json.dumps(
                {
                    "type": "snapshot",
                    "kind": "airbases",
                    "payload": {"airbases": [{"object_id": "AIRBASE:Parchim", "coalition": "blue"}]},
                }
            )
        )

        assert bridge.strategic_objective("OBJECTIVE:Parchim") is objective
        assert objective.owner == "blue"
        assert objective.status is ObjectiveStatus.OPERATIONAL
        assert bridge.objectives.events[-1].source == "snapshot.airbases"

    asyncio.run(scenario())


def test_normalized_airbase_and_opszone_events_update_authoritative_state() -> None:
    state = MooseBridgeState()
    state.apply_message(
        {
            "type": "event",
            "event": "airbase.coalition_changed",
            "payload": {
                "airbase": {"object_id": "AIRBASE:Parchim", "coalition": "red"},
            },
        }
    )
    state.apply_message(
        {
            "type": "event",
            "event": "opszone.owner_changed",
            "payload": {
                "opszone": {
                    "object_id": "OPSZONE:Town Fight",
                    "dcs_name": "Town Fight",
                    "object_type": "OPSZONE",
                    "owner_current_name": "blue",
                    "is_contested": False,
                },
            },
        }
    )

    assert state.airbases["AIRBASE:Parchim"]["coalition"] == "red"
    assert state.opszone("OPSZONE:Town Fight").owner_current_name == "blue"  # type: ignore[union-attr]


def test_base_captured_event_updates_objective_once_end_to_end() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        objective = StrategicObjective(
            objective_id="OBJECTIVE:Parchim",
            name="Parchim Airbase",
            kind=ObjectiveKind.AIRBASE,
            control_object_id="AIRBASE:Parchim",
            ownership_policy=OwnershipPolicy.DCS_MANAGED,
        )
        bridge.add_strategic_objective(objective)
        await server._handle_line(
            json.dumps(
                {
                    "type": "snapshot",
                    "kind": "airbases",
                    "payload": {"airbases": [{"object_id": "AIRBASE:Parchim", "coalition": "blue"}]},
                }
            )
        )
        baseline = len(bridge.objectives.events)
        captured = {
            "type": "event",
            "event": "airbase.coalition_changed",
            "mission_time": 125.5,
            "payload": {
                "airbase_id": "AIRBASE:Parchim",
                "previous_coalition": "blue",
                "coalition": "red",
                "capturing_unit_id": "UNIT:Red Armor-1",
                "airbase": {
                    "object_id": "AIRBASE:Parchim",
                    "name": "Parchim",
                    "category": "Airdrome",
                    "coalition": "red",
                },
            },
        }

        await server._handle_line(json.dumps(captured))
        await server._handle_line(json.dumps(captured))

        emitted = bridge.objectives.events[baseline:]
        assert objective.owner == "red"
        assert server.state.airbases["AIRBASE:Parchim"]["category"] == "Airdrome"
        assert [event.event for event in emitted] == ["objective.control_changed"]
        assert emitted[0].previous_owner == "blue"
        assert emitted[0].owner == "red"
        assert emitted[0].source == "airbase.coalition_changed"

    asyncio.run(scenario())


def test_sdk_waits_for_normalized_objective_control_event() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        objective = StrategicObjective(
            objective_id="OBJECTIVE:Parchim",
            name="Parchim",
            kind=ObjectiveKind.AIRBASE,
            control_object_id="AIRBASE:Parchim",
            ownership_policy=OwnershipPolicy.DCS_MANAGED,
        )
        bridge.add_strategic_objective(objective)
        await server._handle_line(
            json.dumps(
                {
                    "type": "snapshot",
                    "kind": "airbases",
                    "payload": {"airbases": [{"object_id": "AIRBASE:Parchim", "coalition": "blue"}]},
                }
            )
        )

        waiter = asyncio.create_task(
            bridge.wait_for_objective_event(
                objective_id="OBJECTIVE:Parchim",
                timeout=1.0,
            )
        )
        await asyncio.sleep(0)
        assert server._event_waiters[0][0] == "airbase.coalition_changed"
        await server._handle_line(
            json.dumps(
                {
                    "type": "event",
                    "id": "event-capture-1",
                    "event": "airbase.coalition_changed",
                    "payload": {
                        "airbase": {"object_id": "AIRBASE:Parchim", "coalition": "red"},
                    },
                }
            )
        )
        event = await waiter

        assert event.event == "objective.control_changed"
        assert event.previous_owner == "blue"
        assert event.owner == "red"

    asyncio.run(scenario())


def test_fixed_objective_rejects_external_event_wait() -> None:
    async def scenario() -> None:
        bridge = MooseBridgeClient(MooseBridgeServer())
        bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Fixed",
                name="Fixed",
                kind=ObjectiveKind.CUSTOM,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
                owner="blue",
            )
        )

        try:
            await bridge.wait_for_objective_event(objective_id="OBJECTIVE:Fixed", timeout=0.01)
        except ValueError as exc:
            assert "no external ownership event" in str(exc)
        else:
            raise AssertionError("Expected fixed objective wait to fail")

    asyncio.run(scenario())


def test_strategic_goal_rejects_neutral_or_shared_ownership() -> None:
    for coalition in ("neutral", "all", ""):
        try:
            StrategicGoal(
                goal_id="GOAL:Invalid",
                name="Invalid",
                coalition=coalition,
                action=StrategicGoalAction.CAPTURE,
                objective_id="OBJECTIVE:Target",
            )
        except ValueError as exc:
            assert "blue or red" in str(exc)
        else:
            raise AssertionError(f"Coalition {coalition!r} should be rejected")


def test_capture_goal_is_achieved_by_airbase_event_and_stays_completed() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Tutow",
                name="Tutow",
                kind=ObjectiveKind.AIRBASE,
                control_object_id="AIRBASE:Tutow",
                ownership_policy=OwnershipPolicy.DCS_MANAGED,
            )
        )
        await server._handle_line(
            json.dumps(
                {
                    "type": "snapshot",
                    "kind": "airbases",
                    "mission_time": 100,
                    "payload": {"airbases": [{"object_id": "AIRBASE:Tutow", "coalition": "red"}]},
                }
            )
        )
        goal = bridge.add_strategic_goal(
            StrategicGoal(
                goal_id="GOAL:Capture Tutow",
                name="Capture Tutow",
                coalition="blue",
                action=StrategicGoalAction.CAPTURE,
                objective_id="OBJECTIVE:Tutow",
                priority=90,
            ),
            activate=True,
        )
        assert goal.status is StrategicGoalStatus.ACTIVE

        await server._handle_line(
            json.dumps(
                {
                    "type": "event",
                    "event": "airbase.coalition_changed",
                    "mission_time": 150,
                    "payload": {"airbase": {"object_id": "AIRBASE:Tutow", "coalition": "blue"}},
                }
            )
        )

        assert goal.status is StrategicGoalStatus.ACHIEVED
        assert goal.completed_mission_time == 150
        assert bridge.goals.events[-1].event == "goal.achieved"
        assert bridge.strategic_goals(coalition="blue", status="achieved") == (goal,)

        await server._handle_line(
            json.dumps(
                {
                    "type": "event",
                    "event": "airbase.coalition_changed",
                    "mission_time": 200,
                    "payload": {"airbase": {"object_id": "AIRBASE:Tutow", "coalition": "red"}},
                }
            )
        )
        assert goal.status is StrategicGoalStatus.ACHIEVED

    asyncio.run(scenario())


def test_defend_goal_is_evaluated_at_deadline_from_heartbeat() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        objective = bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Depot",
                name="Depot",
                kind=ObjectiveKind.DEPOT,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
                owner="blue",
            )
        )
        objective.status = ObjectiveStatus.OPERATIONAL
        goal = bridge.add_strategic_goal(
            StrategicGoal(
                goal_id="GOAL:Defend Depot",
                name="Defend Depot",
                coalition="blue",
                action=StrategicGoalAction.DEFEND,
                objective_id=objective.objective_id,
                deadline_mission_time=600,
            ),
            activate=True,
        )
        assert goal.evaluation_mode is GoalEvaluationMode.AT_DEADLINE
        assert goal.status is StrategicGoalStatus.ACTIVE

        waiter = asyncio.create_task(
            bridge.wait_for_strategic_goal_event(goal.goal_id, timeout=1.0)
        )
        await asyncio.sleep(0)
        await server._handle_line(json.dumps({"type": "heartbeat", "source": "dcs", "mission_time": 599}))
        assert goal.status is StrategicGoalStatus.ACTIVE
        await server._handle_line(json.dumps({"type": "heartbeat", "source": "dcs", "mission_time": 600}))
        event = await waiter
        assert goal.status is StrategicGoalStatus.ACHIEVED
        assert event.event == "goal.achieved"

    asyncio.run(scenario())


def test_destroy_goal_follows_object_destroyed_event_without_polling() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Armor",
                name="Armor",
                kind=ObjectiveKind.FORCE,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
                owner="red",
                components=(ObjectiveComponent("UNIT:Armor-1"),),
            )
        )
        await server._handle_line(
            json.dumps(
                {
                    "type": "snapshot",
                    "kind": "units",
                    "payload": {"units": [{"object_id": "UNIT:Armor-1", "alive": True}]},
                }
            )
        )
        goal = bridge.add_strategic_goal(
            StrategicGoal(
                goal_id="GOAL:Destroy Armor",
                name="Destroy Armor",
                coalition="blue",
                action=StrategicGoalAction.DESTROY,
                objective_id="OBJECTIVE:Armor",
            ),
            activate=True,
        )

        await server._handle_line(
            json.dumps(
                {
                    "type": "event",
                    "event": "object.destroyed",
                    "mission_time": 75,
                    "payload": {
                        "object_id": "UNIT:Armor-1",
                        "object_type": "UNIT",
                        "object": {"object_id": "UNIT:Armor-1", "object_type": "UNIT", "alive": False},
                    },
                }
            )
        )

        assert bridge.strategic_objective("OBJECTIVE:Armor").status is ObjectiveStatus.DESTROYED  # type: ignore[union-attr]
        assert goal.status is StrategicGoalStatus.ACHIEVED

    asyncio.run(scenario())


def test_destroy_goal_uses_weighted_required_damage() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Depot",
                name="Depot",
                kind=ObjectiveKind.DEPOT,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
                owner="red",
                components=(
                    ObjectiveComponent("STATIC:Main", weight=0.75),
                    ObjectiveComponent("STATIC:Reserve", weight=0.25),
                ),
            )
        )
        await server._handle_line(
            json.dumps(
                {
                    "type": "snapshot",
                    "kind": "statics",
                    "payload": {
                        "statics": [
                            {"object_id": "STATIC:Main", "alive": True},
                            {"object_id": "STATIC:Reserve", "alive": True},
                        ]
                    },
                }
            )
        )
        weighted = bridge.add_strategic_goal(
            StrategicGoal(
                goal_id="GOAL:Damage Depot",
                name="Damage Depot",
                coalition="blue",
                action=StrategicGoalAction.DESTROY,
                objective_id="OBJECTIVE:Depot",
                required_damage=0.75,
            ),
            activate=True,
        )
        strict = bridge.add_strategic_goal(
            StrategicGoal(
                goal_id="GOAL:Destroy Depot",
                name="Destroy Depot",
                coalition="blue",
                action=StrategicGoalAction.DESTROY,
                objective_id="OBJECTIVE:Depot",
                required_damage=1.0,
            ),
            activate=True,
        )

        await server._handle_line(
            json.dumps(
                {
                    "type": "event",
                    "event": "object.destroyed",
                    "mission_time": 75,
                    "payload": {
                        "object_id": "STATIC:Main",
                        "object_type": "STATIC",
                        "object": {"object_id": "STATIC:Main", "object_type": "STATIC", "alive": False},
                    },
                }
            )
        )

        objective = bridge.strategic_objective("OBJECTIVE:Depot")
        assert objective is not None
        assert objective.health == 0.25
        assert weighted.status is StrategicGoalStatus.ACHIEVED
        assert strict.status is StrategicGoalStatus.ACTIVE

        await server._handle_line(
            json.dumps(
                {
                    "type": "event",
                    "event": "object.destroyed",
                    "mission_time": 80,
                    "payload": {
                        "object_id": "STATIC:Reserve",
                        "object_type": "STATIC",
                        "object": {"object_id": "STATIC:Reserve", "object_type": "STATIC", "alive": False},
                    },
                }
            )
        )

        assert objective.health == 0.0
        assert strict.status is StrategicGoalStatus.ACHIEVED
        assert "required_damage=100.0%" in format_strategic_goal(strict)

    asyncio.run(scenario())


def test_required_damage_is_rejected_for_non_destroy_goal() -> None:
    try:
        StrategicGoal(
            goal_id="GOAL:Invalid",
            name="Invalid",
            coalition="blue",
            action=StrategicGoalAction.CAPTURE,
            objective_id="OBJECTIVE:Town",
            required_damage=0.5,
        )
    except ValueError as exc:
        assert "only valid for DESTROY" in str(exc)
    else:
        raise AssertionError("Non-DESTROY goals must reject required_damage")


def test_component_health_evidence_is_cumulative_until_explicitly_cleared() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Depot Evidence",
            name="Depot Evidence",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            components=(ObjectiveComponent("STATIC:Evidence", weight=1.0),),
        ),
        sync=False,
    )

    first = bridge.objectives.record_component_health(
        objective,
        "STATIC:Evidence",
        0.4,
        source="auftrag_summary:AUFTRAG:1",
        mission_time=10.0,
    )
    retained = bridge.objectives.record_component_health(
        objective,
        "STATIC:Evidence",
        0.7,
        source="auftrag_summary:AUFTRAG:2",
        mission_time=20.0,
    )

    assert retained is first
    assert objective.component_health_estimates["STATIC:Evidence"].health == 0.4

    bridge.objectives.clear_component_health(objective, "STATIC:Evidence")
    assert objective.component_health_estimates == {}


def test_custom_goal_conditions_and_manual_completion_are_supported() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Custom",
            name="Custom",
            kind=ObjectiveKind.CUSTOM,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Manual",
            name="Manual decision",
            coalition="blue",
            action=StrategicGoalAction.INTERDICT,
            objective_id="OBJECTIVE:Custom",
            evaluation_mode=GoalEvaluationMode.MANUAL,
            success_conditions=(GoalCondition.owner_is("blue"),),
        ),
        activate=True,
    )

    bridge.complete_strategic_goal(goal, achieved=False, reason="commander_decision")

    assert goal.status is StrategicGoalStatus.FAILED
    assert goal.failure_reason == "commander_decision"
    rendered = format_strategic_goal(goal)
    assert "action=interdict coalition=blue status=failed" in rendered
    assert "success: owner_is=blue" in rendered
