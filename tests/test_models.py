"""Tests for typed MOOSE Bridge snapshot models."""

from moosebridge.models import Auftrag, OpsGroup, OpsZone
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
    }

    auftrag = Auftrag.from_payload(payload)

    assert auftrag.object_id == "AUFTRAG:1"
    assert auftrag.auftragsnummer == 1
    assert auftrag.type == "Patrol Zone"
    assert auftrag.status == "scheduled"
    assert auftrag.prio == 50
    assert auftrag.assigned_group_ids == ["OPSGROUP:Aerial-1"]


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
