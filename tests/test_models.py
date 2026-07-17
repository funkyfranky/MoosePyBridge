"""Tests for typed MOOSE Bridge snapshot models."""

from moosebridge.models import Auftrag, Intel, IntelCluster, IntelContact, OpsGroup, OpsZone, TargetSnapshot, Territory
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
        "latitude": 54.10851,
        "longitude": 12.64489,
    }

    zone = OpsZone.from_payload(payload)

    assert zone.object_id == "OPSZONE:Town Fight"
    assert zone.state == "Empty"
    assert zone.zone_type == "Circular"
    assert zone.zone_radius == 3000
    assert zone.owner_current_name == "neutral"
    assert zone.latitude == 54.10851
    assert zone.longitude == 12.64489


def test_territory_model_and_coalition_event() -> None:
    payload = {
        "object_id": "TERRITORY:North",
        "dcs_name": "North",
        "object_type": "TERRITORY",
        "category": "TERRITORY",
        "source": "database.TERRITORIES",
        "name": "North",
        "zone_name": "Territory North",
        "zone_class_name": "ZONE_POLYGON",
        "coalition": "blue",
        "shape": "polygon",
        "x": 150,
        "z": 250,
        "latitude": 54.05,
        "longitude": 12.05,
        "vertices": [
            {"x": 100, "z": 200, "latitude": 54.0, "longitude": 12.0},
            {"x": 200, "z": 200, "latitude": 54.0, "longitude": 12.1},
            {"x": 150, "z": 300, "latitude": 54.1, "longitude": 12.05},
        ],
    }
    territory = Territory.from_payload(payload)

    assert territory.zone_name == "Territory North"
    assert territory.coalition == "blue"
    assert len(territory.vertices) == 3
    assert territory.vertices[1].x == 200

    state = MooseBridgeState()
    state.apply_message({"type": "snapshot", "kind": "territories", "payload": {"territories": [payload]}})
    assert state.territory("TERRITORY:North") == territory

    changed = dict(payload, coalition="red")
    state.apply_message(
        {
            "type": "event",
            "event": "territory.coalition_changed",
            "payload": {"territory_id": "TERRITORY:North", "territory": changed},
        }
    )
    assert state.territory("TERRITORY:North").coalition == "red"  # type: ignore[union-attr]


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


def test_intel_models_from_payload() -> None:
    intel = Intel.from_payload(
        {
            "object_id": "INTEL:BlueIntel",
            "dcs_name": "BlueIntel",
            "object_type": "INTEL",
            "alias": "BlueIntel",
            "coalition": "blue",
            "state": "Running",
            "is_running": True,
            "contact_count": 1,
            "cluster_count": 1,
            "agent_count": 3,
            "alive_agent_count": 2,
            "agent_ids": ["GROUP:EWR-1", "GROUP:AWACS-1", "GROUP:Dead-1"],
        }
    )
    contact = IntelContact.from_payload(
        {
            "object_id": "INTELCONTACT:BlueIntel:Ground-1",
            "dcs_name": "Ground-1",
            "object_type": "INTELCONTACT",
            "intel_id": "INTEL:BlueIntel",
            "target_object_id": "GROUP:Ground-1",
            "contact_type": "Ground",
            "threat_level": 7,
            "recce": "EWR-1",
            "x": 10,
            "z": 20,
            "latitude": 54.1,
            "longitude": 12.2,
        }
    )
    cluster = IntelCluster.from_payload(
        {
            "object_id": "INTELCLUSTER:BlueIntel:1",
            "dcs_name": "Cluster 1",
            "object_type": "INTELCLUSTER",
            "intel_id": "INTEL:BlueIntel",
            "index": 1,
            "size": 1,
            "contact_ids": ["INTELCONTACT:BlueIntel:Ground-1"],
            "threat_level_sum": 7,
        }
    )

    assert intel.object_id == "INTEL:BlueIntel"
    assert intel.is_running is True
    assert intel.agent_count == 3
    assert intel.alive_agent_count == 2
    assert intel.agent_ids == ["GROUP:EWR-1", "GROUP:AWACS-1", "GROUP:Dead-1"]
    assert contact.target_object_id == "GROUP:Ground-1"
    assert contact.threat_level == 7
    assert contact.latitude == 54.1
    assert contact.longitude == 12.2
    assert cluster.contact_ids == ["INTELCONTACT:BlueIntel:Ground-1"]


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


def test_state_indexes_intel_snapshots_and_events() -> None:
    state = MooseBridgeState()

    state.apply_message(
        {
            "type": "snapshot",
            "kind": "intels",
            "payload": {"intels": [{"object_id": "INTEL:BlueIntel", "dcs_name": "BlueIntel", "object_type": "INTEL"}]},
        }
    )
    state.apply_message(
        {
            "type": "event",
            "event": "intel.new_contact",
            "payload": {
                "contact": {
                    "object_id": "INTELCONTACT:BlueIntel:Ground-1",
                    "dcs_name": "Ground-1",
                    "object_type": "INTELCONTACT",
                    "intel_id": "INTEL:BlueIntel",
                    "target_object_id": "GROUP:Ground-1",
                }
            },
        }
    )

    assert state.intel("INTEL:BlueIntel") is not None
    assert state.intel_contact("INTELCONTACT:BlueIntel:Ground-1") is not None
    assert [contact.object_id for contact in state.contacts_for_intel("INTEL:BlueIntel")] == ["INTELCONTACT:BlueIntel:Ground-1"]

    state.apply_message(
        {
            "type": "event",
            "event": "intel.lost_contact",
            "payload": {
                "contact": {
                    "object_id": "INTELCONTACT:BlueIntel:Ground-1",
                    "dcs_name": "Ground-1",
                    "object_type": "INTELCONTACT",
                    "intel_id": "INTEL:BlueIntel",
                }
            },
        }
    )

    assert state.intel_contact("INTELCONTACT:BlueIntel:Ground-1") is None


def test_state_tracks_dcs_clock_for_each_snapshot_kind() -> None:
    state = MooseBridgeState()

    state.apply_message(
        {
            "type": "snapshot",
            "source": "dcs",
            "sequence": 42,
            "mission_time": 10.25,
            "dcs_time": 86_410.5,
            "mission_date": "2026/07/15",
            "wall_time": "2026-07-15T10:00:00Z",
            "kind": "intels",
            "payload": {"intels": []},
        }
    )

    assert state.clock is not None
    assert state.clock.mission_time == 10.25
    assert state.clock.day_offset == 1
    assert state.clock.time_of_day == "00:00:10"
    assert state.clock.mission_date == "2026/07/15"
    assert state.clock.dcs_date == "2026/07/16"
    assert state.clock.mission_elapsed == "00:00:10"
    assert state.snapshot_clocks["intels"] is state.clock


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
