from __future__ import annotations

import asyncio
import json

from moosebridge import (
    CaptureBehavior,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveComponent,
    ObjectiveKind,
    ObjectiveStatus,
    OwnershipPolicy,
    StrategicObjective,
    StrategicObjectiveRegistry,
    capture_actions,
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
