"""Tests for typed MOOSE Bridge snapshot models."""

from moosebridge.models import Auftrag, OpsGroup, OpsZone, TargetSnapshot
from moosebridge.state import MooseBridgeState


def test_opszone_model_from_payload() -> None:
    payload = {
        "object_id": "OPSZONE:Town Fight",
        "dcs_name": "Town Fight",
        "object_type": "OPSZONE",
        "category": "OPSZONE",
        "source": "database.OPSZONES",
        "state": "Empty",
        "zone_type": "Circular",
        "zone_radius": 3000,
        "owner_current_name": "neutral",
        "x": -33711.171875,
        "z": -510211,
    }

    zone = OpsZone.from_payload(payload)

    assert zone.object_id == "OPSZONE:Town Fight"
    assert zone.state == "Empty"
    assert zone.zone_type == "Circular"
    assert zone.zone_radius == 3000
    assert zone.owner_current_name == "neutral"


def test_opsgroup_model_from_payload() -> None:
    payload = {
        "object_id": "OPSGROUP:Aerial-1",
        "dcs_name": "Aerial-1",
        "object_type": "OPSGROUP",
        "category": "FLIGHTGROUP",
        "source": "database.FLIGHTGROUPS",
        "coalition": "blue",
        "state": "Parking",
        "alive": True,
        "active": True,
        "auftrag_current_id": "AUFTRAG:1",
        "auftrag_queue_ids": ["AUFTRAG:1"],
        "detected_group_ids": ["GROUP:Enemy-1"],
    }

    group = OpsGroup.from_payload(payload)

    assert group.object_id == "OPSGROUP:Aerial-1"
    assert group.category == "FLIGHTGROUP"
    assert group.coalition == "blue"
    assert group.auftrag_current_id == "AUFTRAG:1"
    assert group.auftrag_queue_ids == ["AUFTRAG:1"]
    assert group.detected_group_ids == ["GROUP:Enemy-1"]


def test_target_snapshot_from_payload() -> None:
    payload = {
        "object_id": "TARGET:1",
        "name": "Town Fight",
        "state": "Alive",
        "category": "Zone",
        "x": -33711.171875,
        "y": 0,
        "z": -510211,
        "objects": [
            {
                "id": 1,
                "type": "OpsZone",
                "name": "Town Fight",
                "object_id": "OPSZONE:Town Fight",
                "status": "Alive",
                "n0": 1,
                "n_dead": 0,
                "n_destroyed": 0,
                "life": 1,
                "life0": 1,
                "x": -33711.171875,
                "z": -510211,
            }
        ],
    }

    target = TargetSnapshot.from_payload(payload)

    assert target.object_id == "TARGET:1"
    assert target.name == "Town Fight"
    assert target.category == "Zone"
    assert target.x == -33711.171875
    assert len(target.objects) == 1
    assert target.objects[0].object_id == "OPSZONE:Town Fight"
    assert target.objects[0].type == "OpsZone"


def test_zone_target_is_not_remapped_to_opszone() -> None:
    payload = {
        "object_id": "TARGET:1",
        "name": "Town Fight",
        "category": "Zone",
        "objects": [
            {
                "id": 1,
                "type": "Zone",
                "name": "Town Fight",
                "object_id": "ZONE:Town Fight",
            }
        ],
    }

    target = TargetSnapshot.from_payload(payload)

    assert target.objects[0].type == "Zone"
    assert target.objects[0].object_id == "ZONE:Town Fight"


def test_auftrag_model_from_payload() -> None:
    payload = {
        "object_id": "AUFTRAG:1",
        "dcs_name": "Auftrag Nr. 1",
        "object_type": "AUFTRAG",
        "category": "Patrol Zone",
        "auftragsnummer": 1,
        "name": "Auftrag Nr. 1",
        "type": "Patrol Zone",
        "status": "scheduled",
        "prio": 50,
        "urgent": False,
        "assigned_group_ids": ["OPSGROUP:Aerial-1"],
        "legion_names": ["US AW Batumi"],
        "target": {
            "object_id": "TARGET:1",
            "name": "Town Fight",
            "category": "Zone",
            "objects": [{"id": 1, "type": "OpsZone", "name": "Town Fight", "object_id": "OPSZONE:Town Fight"}],
        },
    }

    auftrag = Auftrag.from_payload(payload)

    assert auftrag.object_id == "AUFTRAG:1"
    assert auftrag.auftragsnummer == 1
    assert auftrag.type == "Patrol Zone"
    assert auftrag.status == "scheduled"
    assert auftrag.prio == 50
    assert auftrag.assigned_group_ids == ["OPSGROUP:Aerial-1"]
    assert auftrag.legion_names == ["US AW Batumi"]
    assert auftrag.target is not None
    assert auftrag.target.object_id == "TARGET:1"
    assert auftrag.target.objects[0].object_id == "OPSZONE:Town Fight"


def test_state_indexes_typed_ops_models() -> None:
    state = MooseBridgeState()

    state.apply_message(
        {
            "type": "snapshot",
            "kind": "auftraege",
            "payload": {
                "auftraege": [
                    {
                        "object_id": "AUFTRAG:1",
                        "dcs_name": "Auftrag Nr. 1",
                        "object_type": "AUFTRAG",
                        "type": "Patrol Zone",
                    }
                ]
            },
        }
    )

    assert state.auftraege["AUFTRAG:1"]["type"] == "Patrol Zone"
    assert state.auftrag_objects["AUFTRAG:1"].type == "Patrol Zone"


def test_state_indexes_objects_snapshot() -> None:
    state = MooseBridgeState()

    state.apply_message(
        {
            "type": "snapshot",
            "kind": "objects",
            "payload": {
                "objects": [
                    {
                        "object_id": "GROUP:Armor-1",
                        "dcs_name": "Armor-1",
                        "object_type": "GROUP",
                    }
                ]
            },
        }
    )

    assert state.objects["GROUP:Armor-1"]["dcs_name"] == "Armor-1"


def test_state_resolves_group_auftrag_relationships() -> None:
    state = MooseBridgeState()

    state.apply_message(
        {
            "type": "snapshot",
            "kind": "opsgroups",
            "payload": {
                "opsgroups": [
                    {
                        "object_id": "OPSGROUP:Aerial-1",
                        "dcs_name": "Aerial-1",
                        "object_type": "OPSGROUP",
                        "auftrag_current_id": "AUFTRAG:1",
                        "auftrag_queue_ids": ["AUFTRAG:1", "AUFTRAG:2"],
                    }
                ]
            },
        }
    )
    state.apply_message(
        {
            "type": "snapshot",
            "kind": "auftraege",
            "payload": {
                "auftraege": [
                    {
                        "object_id": "AUFTRAG:1",
                        "dcs_name": "Auftrag Nr. 1",
                        "object_type": "AUFTRAG",
                        "type": "Patrol Zone",
                    },
                    {
                        "object_id": "AUFTRAG:2",
                        "dcs_name": "Auftrag Nr. 2",
                        "object_type": "AUFTRAG",
                        "type": "CAP",
                    },
                ]
            },
        }
    )

    assert state.opsgroup("OPSGROUP:Aerial-1") is not None
    assert state.auftrag("AUFTRAG:1") is not None
    assert state.current_auftrag_for_group("OPSGROUP:Aerial-1").type == "Patrol Zone"
    assert [auftrag.object_id for auftrag in state.queued_auftraege_for_group("OPSGROUP:Aerial-1")] == [
        "AUFTRAG:1",
        "AUFTRAG:2",
    ]
