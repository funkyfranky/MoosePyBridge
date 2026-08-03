from __future__ import annotations

import asyncio
import json

from moosebridge import (
    DestroyedObjectEvent,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveComponent,
    ObjectiveKind,
    ObjectiveStatus,
    OwnershipPolicy,
    StrategicObjective,
)
from moosebridge.state import MooseBridgeState


def destroyed_message() -> dict[str, object]:
    return {
        "type": "event",
        "id": "event-unit-lost-1",
        "event": "object.destroyed",
        "mission_time": 125.5,
        "payload": {
            "object_id": "UNIT:Armor-1-1",
            "object_type": "UNIT",
            "group_id": "GROUP:Armor-1",
            "dcs_event_time": 125.25,
            "dcs_event_name": "S_EVENT_UNIT_LOST",
            "object": {
                "object_id": "UNIT:Armor-1-1",
                "dcs_name": "Armor-1-1",
                "object_type": "UNIT",
                "group_name": "Armor-1",
                "coalition": "red",
                "alive": False,
                "active": False,
                "x": 100,
                "y": 20,
                "z": 200,
                "latitude": 54.1,
                "longitude": 12.2,
            },
            "group": {
                "object_id": "GROUP:Armor-1",
                "alive": True,
                "active": True,
                "unit_count": 2,
                "alive_unit_count": 1,
            },
        },
    }


def test_destroyed_object_event_model() -> None:
    event = DestroyedObjectEvent.from_message(destroyed_message())

    assert event.object_id == "UNIT:Armor-1-1"
    assert event.group_id == "GROUP:Armor-1"
    assert event.coalition == "red"
    assert event.mission_time == 125.5
    assert event.dcs_event_time == 125.25
    assert event.dcs_event_name == "S_EVENT_UNIT_LOST"


def test_object_destroyed_event_updates_state_without_snapshot() -> None:
    state = MooseBridgeState()
    state.units["UNIT:Armor-1-1"] = {
        "object_id": "UNIT:Armor-1-1",
        "dcs_type": "T-72B",
        "alive": True,
        "active": True,
        "x": 100,
        "z": 200,
    }
    state.groups["GROUP:Armor-1"] = {
        "object_id": "GROUP:Armor-1",
        "alive": True,
        "unit_count": 2,
        "alive_unit_count": 2,
    }
    state.ammunition["UNIT:Armor-1-1"] = {"object_id": "UNIT:Armor-1-1"}
    state.ammunition_objects["UNIT:Armor-1-1"] = object()  # type: ignore[assignment]

    state.apply_message(destroyed_message())

    unit = state.units["UNIT:Armor-1-1"]
    assert unit["alive"] is False
    assert unit["active"] is False
    assert unit["dcs_type"] == "T-72B"
    assert unit["x"] == 100
    assert state.groups["GROUP:Armor-1"]["alive_unit_count"] == 1
    assert "UNIT:Armor-1-1" not in state.ammunition
    assert "UNIT:Armor-1-1" not in state.ammunition_objects
    report = state.loss_reports["LOSS:event-unit-lost-1"]
    assert report["target_object_id"] == "UNIT:Armor-1-1"
    assert report["victim_coalition"] == "red"
    assert report["visible_to"] == ["blue", "red"]
    assert report["confidence"] == "confirmed"
    assert report["longitude"] == 12.2


def test_loss_report_is_visible_in_both_tactical_pictures_and_global_truth() -> None:
    server = MooseBridgeServer()
    bridge = MooseBridgeClient(server)
    server.state.apply_message(destroyed_message())

    blue = bridge.build_tactical_picture("blue", "INTEL:Blue")
    red = bridge.build_tactical_picture("red", "INTEL:Red")
    global_picture = bridge.build_global_picture()

    assert len(blue.loss_reports) == 1
    assert len(red.loss_reports) == 1
    assert blue.to_geojson()["features"][0]["properties"]["perspective"] == "enemy_loss"
    assert red.to_geojson()["features"][0]["properties"]["perspective"] == "friendly_loss"
    global_feature = next(
        feature
        for feature in global_picture.to_geojson()["features"]
        if feature["properties"]["layer"] == "loss_reports"
    )
    assert global_feature["properties"]["perspective"] == "global_truth"


def test_unit_lost_updates_strategic_component_health() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        await server._handle_line(
            json.dumps(
                {
                    "type": "snapshot",
                    "kind": "units",
                    "payload": {
                        "units": [
                            {
                                "object_id": "UNIT:Armor-1-1",
                                "alive": True,
                                "active": True,
                            }
                        ]
                    },
                }
            )
        )
        objective = bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Armor-1-1",
                name="Armor component",
                kind=ObjectiveKind.FORCE,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
                owner="red",
                components=(ObjectiveComponent("UNIT:Armor-1-1"),),
            )
        )
        assert objective.status is ObjectiveStatus.OPERATIONAL

        await server._handle_line(json.dumps(destroyed_message()))

        assert objective.health == 0.0
        assert objective.status is ObjectiveStatus.DESTROYED
        assert bridge.objectives.events[-1].event == "objective.destroyed"
        assert bridge.objectives.events[-1].source == "object.destroyed"

    asyncio.run(scenario())


def test_sdk_waits_for_one_unit_lost_event() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        waiter = asyncio.create_task(
            bridge.wait_for_object_destroyed("UNIT:Armor-1-1", timeout=1.0)
        )
        await asyncio.sleep(0)
        assert server._event_waiters[0][0] == "object.destroyed"
        assert server._event_waiters[0][1] == {"object_id": "UNIT:Armor-1-1"}

        await server._handle_line(json.dumps(destroyed_message()))
        event = await waiter

        assert event.object_id == "UNIT:Armor-1-1"
        assert bridge.state.units[event.object_id]["alive"] is False

    asyncio.run(scenario())
