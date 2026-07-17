from __future__ import annotations

import asyncio
from typing import Any

from moosebridge.auftraege import (
    Auftrag_ARTY,
    Auftrag_AIRDEFENSE,
    Auftrag_AMMOSUPPLY,
    Auftrag_ANTISHIP,
    Auftrag_AWACS,
    Auftrag_BAI,
    Auftrag_BOMBCARPET,
    Auftrag_BOMBRUNWAY,
    Auftrag_CAP,
    Auftrag_CAPTUREZONE,
    Auftrag_CAS,
    Auftrag_CASENHANCED,
    Auftrag_ESCORT,
    Auftrag_EWR,
    Auftrag_FAC,
    Auftrag_FACA,
    Auftrag_FUELSUPPLY,
    Auftrag_GROUNDATTACK,
    Auftrag_GROUNDESCORT,
    Auftrag_INTERCEPT,
    Auftrag_NAVALENGAGEMENT,
    Auftrag_NOTHING,
    Auftrag_ONGUARD,
    Auftrag_ORBIT,
    Auftrag_PATROLZONE,
    Auftrag_RESCUEHELO,
    Auftrag_REARMING,
    Auftrag_SEAD,
    Auftrag_STRAFING,
    Auftrag_STRIKE,
    Auftrag_TANKER,
    Auftrag_TROOPTRANSPORT,
    AuftragEvent,
    GeneralSet,
    GroupSet,
)
from moosebridge.protocol import BridgeCommand
from moosebridge.diagnostics import (
    format_cohort_assets,
    format_global_picture_status,
    format_intel_status,
    format_legion_status,
    format_mission_summary,
)
from moosebridge.models import OpsZone, Territory
from moosebridge.sdk import CoordinateResult, DistanceResult, GlobalPicture, MooseBridgeClient, NearestResult, TacticalPicture
from moosebridge.state import MooseBridgeState


class FakeSdkServer:
    def __init__(self) -> None:
        self.state = MooseBridgeState(connected=True)
        self.commands: list[tuple[BridgeCommand, float]] = []
        self.events_to_emit: list[dict[str, Any]] = []

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        self.commands.append((command, timeout))
        if command.action == "object.coords":
            return {
                "ok": True,
                "result": {
                    "action": "object.coords",
                    "object_id": command.params["object_id"],
                    "format": command.params.get("format", "xyz"),
                    "x": 0,
                    "y": 1,
                    "z": 0,
                    "mgrs": "33U UV 00000 00000",
                },
            }
        if command.action == "object.distance":
            return {
                "ok": True,
                "result": {
                    "action": "object.distance",
                    "object_id_a": command.params["object_id_a"],
                    "object_id_b": command.params["object_id_b"],
                    "distance_m": 1852,
                    "distance_km": 1.852,
                    "distance_nm": 1,
                },
            }
        if command.action == "time.get":
            return {
                "ok": True,
                "type": "ack",
                "source": "dcs",
                "sequence": 7,
                "mission_time": 3_661.25,
                "dcs_time": 90_061.25,
                "mission_date": "2026/07/15",
                "wall_time": "2026-07-15T10:00:00Z",
                "result": {"action": "time.get"},
            }
        if command.action == "snapshot.units":
            self.state.apply_message(
                {
                    "type": "snapshot",
                    "kind": "units",
                    "payload": {
                        "units": [
                            {"object_id": "UNIT:Near", "coalition": "red", "alive": True, "x": 100, "z": 0},
                            {"object_id": "UNIT:Far", "coalition": "red", "alive": True, "x": 1000, "z": 0},
                            {"object_id": "UNIT:Blue", "coalition": "blue", "alive": True, "x": 10, "z": 0},
                        ]
                    },
                }
            )
            return {"ok": True, "result": {"kind": "units", "count": 3}}
        if command.action == "snapshot.auftraege":
            self.state.apply_message(
                {
                    "type": "snapshot",
                    "kind": "auftraege",
                    "payload": {
                        "auftraege": [
                            {
                                "object_id": "AUFTRAG:1",
                                "type": "BAI",
                                "status": "Done",
                                "summary_available": True,
                                "summary": {
                                    "success": True,
                                    "damage": 100,
                                    "Ntargets0": 1,
                                    "Ntargets": 0,
                                    "Ndestroyed": 1,
                                },
                            }
                        ]
                    },
                }
            )
            return {"ok": True, "result": {"kind": "auftraege", "count": 1}}
        if command.action.startswith("auftrag.create_"):
            return {"ok": True, "result": {"action": command.action, "params": command.params, "auftrag_id": "AUFTRAG:1"}}
        return {"ok": True, "result": {"action": command.action, "params": command.params}}

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        event = self.events_to_emit.pop(0) if self.events_to_emit else {
            "type": "event",
            "id": "event-evaluated",
            "event": "auftrag.evaluated",
            "payload": {
                "event": "auftrag.evaluated",
                "auftrag_id": (filters or {}).get("auftrag_id", "AUFTRAG:1"),
                "auftrag_type": "BAI",
                "status": "Done",
                "summary": {
                    "success": True,
                    "damage": 100,
                    "Ntargets0": 1,
                    "Ntargets": 0,
                    "Ndestroyed": 1,
                },
            },
        }
        self.state.apply_message(event)
        return event

    async def snapshot_groups(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.groups", params={}))

    async def snapshot_units(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.units", params={}))

    async def snapshot_statics(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.statics", params={}))

    async def snapshot_airbases(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.airbases", params={}))

    async def snapshot_zones(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.zones", params={}))

    async def snapshot_territories(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.territories", params={}))

    async def snapshot_opszones(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.opszones", params={}))

    async def snapshot_opsgroups(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.opsgroups", params={}))

    async def snapshot_auftraege(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.auftraege", params={}))

    async def snapshot_cohorts(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.cohorts", params={}))

    async def snapshot_legions(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.legions", params={}))

    async def snapshot_intels(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.intels", params={}))

    async def snapshot_intel_contacts(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.intel_contacts", params={}))

    async def snapshot_intel_clusters(self) -> dict[str, Any]:
        return await self.send_command(BridgeCommand(action="snapshot.intel_clusters", params={}))


def test_sdk_coords_returns_typed_result() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        result = await client.coords("ZONE:Town Fight", format="mgrs", timeout=4.0)

        assert isinstance(result, CoordinateResult)
        assert result.object_id == "ZONE:Town Fight"
        assert result.format == "mgrs"
        command, timeout = server.commands[0]
        assert command.action == "object.coords"
        assert command.params == {"object_id": "ZONE:Town Fight", "format": "mgrs"}
        assert timeout == 4.0

    asyncio.run(scenario())


def test_sdk_distance_returns_typed_result() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        result = await client.distance("GROUP:Aerial-1", "ZONE:Town Fight")

        assert isinstance(result, DistanceResult)
        assert result.distance_m == 1852
        assert result.distance_nm == 1
        assert server.commands[0][0].params == {"object_id_a": "GROUP:Aerial-1", "object_id_b": "ZONE:Town Fight"}

    asyncio.run(scenario())


def test_sdk_territory_access_and_coalition_command() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        server.state.apply_message(
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
                        },
                        {
                            "object_id": "TERRITORY:South",
                            "dcs_name": "South",
                            "object_type": "TERRITORY",
                            "coalition": "red",
                        },
                    ]
                },
            }
        )
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        assert client.territory("TERRITORY:North") is not None
        assert [item.object_id for item in client.territories("blue")] == ["TERRITORY:North"]
        await client.snapshot_territories()
        await client.set_territory_coalition("TERRITORY:North", "red", timeout=4)

        assert server.commands[-2][0].action == "snapshot.territories"
        command, timeout = server.commands[-1]
        assert command.action == "territory.set_coalition"
        assert command.params == {"territory_id": "TERRITORY:North", "coalition": "red"}
        assert timeout == 4

    asyncio.run(scenario())


def test_sdk_get_time_returns_typed_dcs_clock() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        clock = await client.get_time(timeout=4.0)

        assert clock.mission_time == 3_661.25
        assert clock.dcs_time == 90_061.25
        assert clock.day_offset == 1
        assert clock.mission_date == "2026/07/15"
        assert clock.dcs_date == "2026/07/16"
        assert clock.time_of_day == "01:01:01"
        assert clock.mission_elapsed == "01:01:01"
        assert clock.wall_time == "2026-07-15T10:00:00Z"
        assert server.commands[0][0].action == "time.get"
        assert server.commands[0][1] == 4.0

    asyncio.run(scenario())


def test_sdk_draw_zone_validates_and_sends_flat_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        await client.draw_zone("ZONE:Town Fight", coalition="blue", color="red", line_type="dashed")

        command = server.commands[0][0]
        assert command.action == "zone.draw"
        assert command.params == {"object_id": "ZONE:Town Fight", "coalition": "blue", "color": "red", "line_type": 2}

    asyncio.run(scenario())


def test_sdk_snapshot_kind_uses_short_kind() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        await client.snapshot_kind("units")

        assert server.commands[0][0].action == "snapshot.units"

    asyncio.run(scenario())


def test_sdk_add_intel_agent_sends_semantic_command() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        ack = await client.add_intel_agent("INTEL:BlueIntel", "GROUP:Blue EWR", timeout=4.0)

        assert ack["result"]["action"] == "intel.add_agent"
        command, timeout = server.commands[0]
        assert command.action == "intel.add_agent"
        assert command.params == {"intel_id": "INTEL:BlueIntel", "agent_id": "GROUP:Blue EWR"}
        assert timeout == 4.0

    asyncio.run(scenario())


def test_sdk_legion_convenience_methods_return_typed_state() -> None:
    server = FakeSdkServer()
    client = MooseBridgeClient(server)  # type: ignore[arg-type]

    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [
                    {
                        "object_id": "LEGION:Wing Parchim",
                        "dcs_name": "Wing Parchim",
                        "object_type": "LEGION",
                        "category": "AIRWING",
                        "state": "Running",
                        "coalition": "blue",
                        "auftrag_queue_ids": ["AUFTRAG:1"],
                    }
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:F-4E Parchim Alpha",
                        "dcs_name": "F-4E Parchim Alpha",
                        "object_type": "COHORT",
                        "legion_id": "LEGION:Wing Parchim",
                        "stock_asset_count": 2,
                        "mission_types": ["BAI", "CAP"],
                        "payloads_by_mission": {"BAI": {"available_count": 1, "total_available": 1}},
                    }
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "auftraege",
            "payload": {
                "auftraege": [
                    {
                        "object_id": "AUFTRAG:1",
                        "dcs_name": "AUFTRAG:1",
                        "object_type": "AUFTRAG",
                        "type": "BAI",
                        "status": "Queued",
                    }
                ]
            },
        }
    )

    legion = client.legion("LEGION:Wing Parchim")
    cohorts = client.cohorts_of_legion("LEGION:Wing Parchim")
    missions = client.missions_of_legion("LEGION:Wing Parchim")

    assert legion is not None
    assert legion.state == "Running"
    assert client.cohort("COHORT:F-4E Parchim Alpha") is cohorts[0]
    assert [cohort.stock_asset_count for cohort in cohorts] == [2]
    assert [mission.type for mission in missions] == ["BAI"]
    assert [mission.status for mission in missions] == ["Queued"]
    assert [cohort.object_id for cohort in client.ready_cohorts_of_legion("LEGION:Wing Parchim", "BAI")] == [
        "COHORT:F-4E Parchim Alpha"
    ]
    assert client.available_missions_of_cohort("COHORT:F-4E Parchim Alpha") == ["BAI", "CAP"]
    assert client.available_missions_of_cohort("COHORT:F-4E Parchim Alpha", require_payload=True) == ["BAI"]


def test_sdk_refresh_helpers_request_expected_snapshots() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        assert await client.refresh_legion_state() is server.state
        assert [command.action for command, _ in server.commands] == [
            "snapshot.legions",
            "snapshot.cohorts",
            "snapshot.auftraege",
        ]

        server.commands.clear()

        assert await client.refresh_ops_state() is server.state
        assert [command.action for command, _ in server.commands] == [
            "snapshot.opszones",
            "snapshot.opsgroups",
            "snapshot.auftraege",
            "snapshot.legions",
            "snapshot.cohorts",
        ]

        server.commands.clear()

        assert await client.refresh_intel_state() is server.state
        assert [command.action for command, _ in server.commands] == [
            "snapshot.intels",
            "snapshot.intel_contacts",
            "snapshot.intel_clusters",
        ]

    asyncio.run(scenario())


def test_sdk_build_tactical_picture_filters_by_coalition_and_intel() -> None:
    server = FakeSdkServer()
    client = MooseBridgeClient(server)  # type: ignore[arg-type]

    server.state.apply_message(
        {
            "type": "heartbeat",
            "source": "dcs",
            "sequence": 5,
            "mission_time": 120.0,
            "dcs_time": 43_320.0,
            "mission_date": "2026/07/15",
            "wall_time": "2026-07-15T10:00:00Z",
        }
    )

    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "intels",
            "payload": {
                "intels": [
                    {
                        "object_id": "INTEL:BlueIntel",
                        "dcs_name": "BlueIntel",
                        "object_type": "INTEL",
                        "coalition": "blue",
                    }
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "intel_contacts",
            "payload": {
                "intel_contacts": [
                    {
                        "object_id": "INTELCONTACT:BlueIntel:Bandit",
                        "dcs_name": "Bandit",
                        "object_type": "INTELCONTACT",
                        "intel_id": "INTEL:BlueIntel",
                        "target_object_id": "GROUP:Bandit",
                        "contact_type": "Air",
                        "threat_level": 8,
                        "x": 1000,
                        "z": 2000,
                        "latitude": 54.1,
                        "longitude": 12.1,
                    },
                    {
                        "object_id": "INTELCONTACT:RedIntel:Friendly",
                        "dcs_name": "Friendly",
                        "object_type": "INTELCONTACT",
                        "intel_id": "INTEL:RedIntel",
                        "target_object_id": "GROUP:Friendly",
                        "x": 50,
                        "z": 60,
                        "latitude": 54.2,
                        "longitude": 12.2,
                    },
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [
                    {
                        "object_id": "LEGION:Wing Parchim",
                        "dcs_name": "Wing Parchim",
                        "object_type": "LEGION",
                        "coalition": "blue",
                        "auftrag_queue_ids": ["AUFTRAG:1"],
                        "x": 10,
                        "z": 20,
                        "latitude": 53.4,
                        "longitude": 11.8,
                    },
                    {
                        "object_id": "LEGION:Red Wing",
                        "dcs_name": "Red Wing",
                        "object_type": "LEGION",
                        "coalition": "red",
                        "x": 30,
                        "z": 40,
                        "latitude": 53.5,
                        "longitude": 11.9,
                    },
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "opsgroups",
            "payload": {
                "opsgroups": [
                    {
                        "object_id": "OPSGROUP:Blue CAP",
                        "dcs_name": "Blue CAP",
                        "object_type": "OPSGROUP",
                        "coalition": "blue",
                        "auftrag_current_id": "AUFTRAG:1",
                        "x": 100,
                        "z": 200,
                        "latitude": 54.3,
                        "longitude": 12.3,
                    },
                    {
                        "object_id": "OPSGROUP:Red CAP",
                        "dcs_name": "Red CAP",
                        "object_type": "OPSGROUP",
                        "coalition": "red",
                        "x": 300,
                        "z": 400,
                        "latitude": 54.4,
                        "longitude": 12.4,
                    },
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "auftraege",
            "payload": {
                "auftraege": [
                    {
                        "object_id": "AUFTRAG:1",
                        "dcs_name": "AUFTRAG:1",
                        "object_type": "AUFTRAG",
                        "type": "CAP",
                        "status": "Executing",
                        "target": {
                            "object_id": "ZONE:CAP",
                            "name": "CAP",
                            "x": 500,
                            "z": 600,
                            "latitude": 54.5,
                            "longitude": 12.5,
                        },
                    }
                ]
            },
        }
    )

    picture = client.build_tactical_picture("blue", "INTEL:BlueIntel")
    geojson = picture.to_geojson()
    layers = [feature["properties"]["layer"] for feature in geojson["features"]]

    assert isinstance(picture, TacticalPicture)
    assert [contact.object_id for contact in picture.contacts] == ["INTELCONTACT:BlueIntel:Bandit"]
    assert [legion.object_id for legion in picture.legions] == ["LEGION:Wing Parchim"]
    assert [group.object_id for group in picture.opsgroups] == ["OPSGROUP:Blue CAP"]
    assert [mission.object_id for mission in picture.missions] == ["AUFTRAG:1"]
    assert geojson["type"] == "FeatureCollection"
    assert geojson["properties"]["scope"] == "tactical"
    assert geojson["properties"]["coordinate_system"] == "WGS84"
    assert geojson["properties"]["mission_time"] == 120.0
    assert geojson["properties"]["mission_elapsed"] == "00:02:00"
    assert geojson["properties"]["dcs_time_of_day"] == "12:02:00"
    assert geojson["properties"]["mission_date"] == "2026/07/15"
    assert geojson["properties"]["dcs_date"] == "2026/07/15"
    assert "known_enemy_contacts" in layers
    assert "friendly_opsgroups" in layers
    assert "friendly_legions" in layers
    assert "missions" in layers
    contact_feature = next(feature for feature in geojson["features"] if feature["properties"]["layer"] == "known_enemy_contacts")
    assert contact_feature["geometry"]["coordinates"] == [12.1, 54.1]
    assert contact_feature["properties"]["x"] == 1000.0
    assert contact_feature["properties"]["z"] == 2000.0


def test_sdk_build_global_picture_exports_truth_snapshots_to_geojson() -> None:
    server = FakeSdkServer()
    client = MooseBridgeClient(server)  # type: ignore[arg-type]

    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "groups",
            "payload": {
                "groups": [
                    {
                        "object_id": "GROUP:Ground-1",
                        "dcs_name": "Ground-1",
                        "object_type": "GROUP",
                        "coalition": "red",
                        "x": 100,
                        "z": 200,
                        "latitude": 54.2,
                        "longitude": 12.3,
                    }
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "zones",
            "payload": {
                "zones": [
                    {
                        "object_id": "ZONE:Town Fight",
                        "dcs_name": "Town Fight",
                        "object_type": "ZONE",
                        "radius": 1000,
                        "x": 300,
                        "z": 400,
                        "latitude": 54.4,
                        "longitude": 12.5,
                    }
                ]
            },
        }
    )

    picture = client.build_global_picture()
    geojson = picture.to_geojson()

    assert isinstance(picture, GlobalPicture)
    assert geojson["properties"]["scope"] == "global"
    assert geojson["properties"]["coordinate_system"] == "WGS84"
    assert [feature["properties"]["layer"] for feature in geojson["features"]] == ["groups", "zones"]
    assert geojson["features"][0]["geometry"]["coordinates"] == [12.3, 54.2]
    assert geojson["features"][0]["properties"]["x"] == 100
    assert geojson["features"][0]["properties"]["z"] == 200
    assert geojson["features"][1]["properties"]["radius_m"] == 1000
    assert picture.validate() == []
    assert "validation: errors=0 warnings=0" in format_global_picture_status(picture)


def test_global_picture_exports_polygon_zone_geometry() -> None:
    picture = GlobalPicture(
        zones=[
            {
                "object_id": "ZONE:Polygon",
                "dcs_name": "Polygon",
                "object_type": "ZONE",
                "category": "ZONE",
                "shape": "polygon",
                "vertices": [
                    {"x": 100, "z": 200, "latitude": 54.0, "longitude": 12.0},
                    {"x": 200, "z": 200, "latitude": 54.0, "longitude": 12.1},
                    {"x": 150, "z": 300, "latitude": 54.1, "longitude": 12.05},
                ],
            }
        ]
    )

    feature = picture.to_geojson()["features"][0]

    assert feature["geometry"] == {
        "type": "Polygon",
        "coordinates": [[[12.0, 54.0], [12.1, 54.0], [12.05, 54.1], [12.0, 54.0]]],
    }
    assert feature["properties"]["shape"] == "polygon"
    assert "radius_m" not in feature["properties"]
    assert "vertices" not in feature["properties"]


def test_global_picture_uses_linked_polygon_geometry_for_opszone() -> None:
    picture = GlobalPicture(
        zones=[
            {
                "object_id": "ZONE:Capture Area",
                "dcs_name": "Capture Area",
                "object_type": "ZONE",
                "shape": "polygon",
                "vertices": [
                    {"latitude": 54.0, "longitude": 12.0},
                    {"latitude": 54.0, "longitude": 12.1},
                    {"latitude": 54.1, "longitude": 12.05},
                ],
            }
        ],
        opszones=[
            OpsZone.from_payload(
                {
                    "object_id": "OPSZONE:Capture Alpha",
                    "dcs_name": "Capture Alpha",
                    "zone_name": "Capture Area",
                    "owner_current_name": "blue",
                    "is_contested": True,
                }
            )
        ],
    )

    opszone = next(feature for feature in picture.to_geojson()["features"] if feature["properties"]["layer"] == "opszones")

    assert opszone["geometry"]["type"] == "Polygon"
    assert opszone["properties"]["coalition"] == "blue"
    assert opszone["properties"]["contested"] is True
    assert opszone["properties"]["shape"] == "polygon"


def test_global_picture_exports_typed_territory_polygon() -> None:
    territory = Territory.from_payload(
        {
            "object_id": "TERRITORY:North",
            "dcs_name": "North",
            "name": "North",
            "object_type": "TERRITORY",
            "coalition": "blue",
            "shape": "polygon",
            "zone_name": "Territory North",
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
    )
    picture = GlobalPicture(territories=[territory])

    feature = picture.to_geojson()["features"][0]

    assert picture.counts()["territories"] == 1
    assert feature["properties"]["layer"] == "territories"
    assert feature["properties"]["coalition"] == "blue"
    assert feature["properties"]["zone_name"] == "Territory North"
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["geometry"]["coordinates"][0][0] == [12.0, 54.0]
    assert picture.validate() == []


def test_global_picture_validator_reports_broken_truth_references() -> None:
    picture = GlobalPicture(
        groups=[
            {"object_id": "GROUP:Known", "alive": True},
            {"object_id": "GROUP:Known", "x": 1, "z": 2},
        ],
        units=[{"object_id": "UNIT:Orphan", "group_name": "Missing", "alive": True, "x": 1, "z": 2}],
        zones=[{"object_id": "ZONE:Broken", "radius": 0, "x": 1, "z": 2}],
    )

    issues = picture.validate()
    codes = {issue.code for issue in issues}

    assert "duplicate_object_id" in codes
    assert "alive_without_position" in codes
    assert "unit_group_missing" in codes
    assert "invalid_zone_radius" in codes


def test_sdk_refresh_picture_helpers_request_expected_snapshots() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        assert isinstance(await client.refresh_tactical_picture("blue", "INTEL:BlueIntel"), TacticalPicture)
        assert [command.action for command, _ in server.commands] == [
            "snapshot.intels",
            "snapshot.intel_contacts",
            "snapshot.intel_clusters",
            "snapshot.opszones",
            "snapshot.opsgroups",
            "snapshot.auftraege",
            "snapshot.legions",
            "snapshot.cohorts",
        ]

        server.commands.clear()

        assert isinstance(await client.refresh_global_picture(), GlobalPicture)
        assert [command.action for command, _ in server.commands] == ["snapshot.all"]

    asyncio.run(scenario())


def test_diagnostics_format_intel_status_uses_sdk_state() -> None:
    server = FakeSdkServer()
    client = MooseBridgeClient(server)  # type: ignore[arg-type]

    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "intels",
            "payload": {
                "intels": [
                    {
                        "object_id": "INTEL:BlueIntel",
                        "dcs_name": "BlueIntel",
                        "object_type": "INTEL",
                        "state": "Running",
                        "coalition": "blue",
                        "is_running": True,
                        "agent_count": 3,
                        "alive_agent_count": 2,
                        "agent_ids": ["GROUP:EWR-1", "GROUP:AWACS-1", "GROUP:Dead-1"],
                    }
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "intel_contacts",
            "payload": {
                "intel_contacts": [
                    {
                        "object_id": "INTELCONTACT:BlueIntel:Ground-1",
                        "dcs_name": "Ground-1",
                        "object_type": "INTELCONTACT",
                        "intel_id": "INTEL:BlueIntel",
                        "target_object_id": "GROUP:Ground-1",
                        "contact_type": "Ground",
                        "threat_level": 5,
                    }
                ]
            },
        }
    )

    text = format_intel_status(client, "INTEL:BlueIntel", timestamp=False)

    assert "INTEL:BlueIntel" in text
    assert "contacts=1" in text
    assert "agents=2/3" in text
    assert "GROUP:Ground-1" in text


def test_diagnostics_format_legion_status_uses_sdk_state() -> None:
    server = FakeSdkServer()
    client = MooseBridgeClient(server)  # type: ignore[arg-type]

    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [
                    {
                        "object_id": "LEGION:Wing Parchim",
                        "dcs_name": "Wing Parchim",
                        "object_type": "LEGION",
                        "state": "Running",
                        "coalition": "blue",
                        "auftrag_queue_ids": ["AUFTRAG:1"],
                    }
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:F-4E Parchim Alpha",
                        "dcs_name": "F-4E Parchim Alpha",
                        "object_type": "COHORT",
                        "legion_id": "LEGION:Wing Parchim",
                        "stock_asset_count": 2,
                        "spawned_asset_count": 1,
                        "mission_types": ["BAI"],
                    }
                ]
            },
        }
    )
    server.state.apply_message(
        {
            "type": "snapshot",
            "kind": "auftraege",
            "payload": {
                "auftraege": [
                    {
                        "object_id": "AUFTRAG:1",
                        "dcs_name": "AUFTRAG:1",
                        "object_type": "AUFTRAG",
                        "type": "BAI",
                        "status": "Queued",
                    }
                ]
            },
        }
    )

    cohort = client.cohort("COHORT:F-4E Parchim Alpha")
    mission = client.missions_of_legion("LEGION:Wing Parchim")[0]

    assert cohort is not None
    assert "stock=2" in format_cohort_assets(cohort)
    assert "type=BAI" in format_mission_summary(mission)
    report = format_legion_status(client, "LEGION:Wing Parchim", timestamp=False)
    assert "LEGION:Wing Parchim" in report
    assert "missions=1" in report
    assert "COHORT:F-4E Parchim Alpha" in report


def test_sdk_nearest_refreshes_snapshot_and_filters_results() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        results = await client.nearest("units", "ZONE:Town Fight", coalition="red", alive=True, limit=2)

        assert all(isinstance(result, NearestResult) for result in results)
        assert [result.object_id for result in results] == ["UNIT:Near", "UNIT:Far"]
        assert [command.action for command, _ in server.commands] == ["object.coords", "snapshot.units"]

    asyncio.run(scenario())


def test_sdk_add_auftrag_to_legion_uses_moose_like_object() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_bai"
        assert command.params == {
            "target": "UNIT:Ground-1-1",
            "altitude_ft": 15000,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_mission_lifecycle_commands_use_known_mission_ids() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")
        await client.cancel_mission(auftrag)
        await client.pause_mission("AUFTRAG:1")
        await client.resume_mission("AUFTRAG:1")

        assert [command.action for command, _ in server.commands] == [
            "auftrag.create_bai",
            "auftrag.cancel",
            "auftrag.pause",
            "auftrag.resume",
        ]
        assert [command.params for command, _ in server.commands[1:]] == [
            {"object_id": "AUFTRAG:1"},
            {"object_id": "AUFTRAG:1"},
            {"object_id": "AUFTRAG:1"},
        ]

    asyncio.run(scenario())


def test_sdk_assign_mission_targets_existing_mission() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        server.state.apply_message(
            {
                "type": "snapshot",
                "kind": "auftraege",
                "payload": {
                    "auftraege": [
                        {
                            "object_id": "AUFTRAG:7",
                            "dcs_name": "AUFTRAG:7",
                            "object_type": "AUFTRAG",
                            "type": "BAI",
                            "status": "Queued",
                        }
                    ]
                },
            }
        )
        mission = client.auftrag("AUFTRAG:7")
        assert mission is not None

        await client.assign_mission(mission, legion="LEGION:Wing Parchim", cohort="COHORT:F-4E Parchim Alpha")

        command = server.commands[0][0]
        assert command.action == "auftrag.assign"
        assert command.params == {
            "object_id": "AUFTRAG:7",
            "legion_id": "LEGION:Wing Parchim",
            "cohort_id": "COHORT:F-4E Parchim Alpha",
        }

    asyncio.run(scenario())


def test_sdk_assign_mission_requires_one_assignment_target() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        try:
            await client.assign_mission("AUFTRAG:1")
        except ValueError as exc:
            assert "exactly one" in str(exc)
        else:
            raise AssertionError("Expected ValueError")

    asyncio.run(scenario())


def test_sdk_add_auftrag_includes_optional_timing_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)

        assert auftrag.set_time(start=600, stop="13:00") is auftrag
        assert auftrag.set_duration(duration=1800) is auftrag
        assert auftrag.set_required_assets(min_count=2, max_count=4) is auftrag

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.params == {
            "target": "UNIT:Ground-1-1",
            "altitude_ft": 15000,
            "clock_start": 600,
            "clock_stop": "13:00",
            "duration": 1800,
            "required_assets_min": 2,
            "required_assets_max": 4,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_set_required_assets_defaults_max_to_min() -> None:
    auftrag = Auftrag_BAI(target="UNIT:Ground-1-1")

    auftrag.set_required_assets(min_count=3)

    assert auftrag.timing_params() == {"required_assets_min": 3, "required_assets_max": 3}


def test_sdk_add_auftrag_to_opsgroup_uses_opsgroup_id() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_ARTY(target="UNIT:Ground-1-1", nshots=6)

        await client.add_auftrag(auftrag=auftrag, opsgroup="OPSGROUP:Group-1")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_arty"
        assert command.params == {
            "target": "UNIT:Ground-1-1",
            "nshots": 6,
            "opsgroup_id": "OPSGROUP:Group-1",
        }

    asyncio.run(scenario())


def test_sdk_add_bombrunway_auftrag_to_legion_uses_bombrunway_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_BOMBRUNWAY(target="AIRBASE:Parchim", altitude_ft=25000)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_bombrunway"
        assert command.params == {
            "target": "AIRBASE:Parchim",
            "altitude_ft": 25000,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_bombcarpet_auftrag_to_legion_uses_bombcarpet_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_BOMBCARPET(target="GROUP:Convoy", altitude_ft=25000, carpet_length_m=500)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_bombcarpet"
        assert command.params == {
            "target": "GROUP:Convoy",
            "altitude_ft": 25000,
            "carpet_length_m": 500,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_groundescort_auftrag_to_legion_uses_groundescort_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_GROUNDESCORT(target="GROUP:Convoy", orbit_distance_nm=1.5, target_types=("Ground vehicles",))

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_groundescort"
        assert command.params == {
            "target": "GROUP:Convoy",
            "orbit_distance_nm": 1.5,
            "target_types": ["Ground vehicles"],
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_ammosupply_auftrag_to_legion_uses_ammosupply_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_AMMOSUPPLY(zone="ZONE:Forward Depot")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Logistics")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_ammosupply"
        assert command.params == {
            "zone": "ZONE:Forward Depot",
            "legion_id": "LEGION:Ground Logistics",
        }

    asyncio.run(scenario())


def test_sdk_add_airdefense_auftrag_to_legion_uses_airdefense_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_AIRDEFENSE(zone="ZONE:Forward SAM")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Air Defense")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_airdefense"
        assert command.params == {
            "zone": "ZONE:Forward SAM",
            "legion_id": "LEGION:Air Defense",
        }

    asyncio.run(scenario())


def test_sdk_add_onguard_auftrag_to_legion_uses_onguard_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_ONGUARD(target="ZONE:Guard Point")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Brigade")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_onguard"
        assert command.params == {
            "target": "ZONE:Guard Point",
            "legion_id": "LEGION:Ground Brigade",
        }

    asyncio.run(scenario())


def test_sdk_add_nothing_auftrag_to_legion_uses_nothing_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_NOTHING(zone="ZONE:Relax")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Brigade")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_nothing"
        assert command.params == {
            "zone": "ZONE:Relax",
            "legion_id": "LEGION:Ground Brigade",
        }

    asyncio.run(scenario())


def test_sdk_add_ewr_auftrag_to_legion_uses_ewr_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_EWR(zone="ZONE:EWR Site")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Radar Net")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_ewr"
        assert command.params == {
            "zone": "ZONE:EWR Site",
            "legion_id": "LEGION:Radar Net",
        }

    asyncio.run(scenario())


def test_sdk_add_fuelsupply_auftrag_to_legion_uses_fuelsupply_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_FUELSUPPLY(zone="ZONE:Forward Depot")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Logistics")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_fuelsupply"
        assert command.params == {
            "zone": "ZONE:Forward Depot",
            "legion_id": "LEGION:Ground Logistics",
        }

    asyncio.run(scenario())


def test_sdk_add_rearming_auftrag_to_legion_uses_rearming_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_REARMING(zone="ZONE:Forward Depot")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Logistics")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_rearming"
        assert command.params == {
            "zone": "ZONE:Forward Depot",
            "legion_id": "LEGION:Ground Logistics",
        }

    asyncio.run(scenario())


def test_sdk_add_groundattack_auftrag_to_legion_uses_groundattack_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_GROUNDATTACK(target="GROUP:Enemy Convoy", speed_kts=25, formation="Vee")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Brigade")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_groundattack"
        assert command.params == {
            "target": "GROUP:Enemy Convoy",
            "speed_kts": 25,
            "formation": "Vee",
            "legion_id": "LEGION:Ground Brigade",
        }

    asyncio.run(scenario())


def test_sdk_add_antiship_auftrag_to_legion_uses_antiship_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_ANTISHIP(target="GROUP:Enemy Ships", altitude_ft=2000)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_antiship"
        assert command.params == {
            "target": "GROUP:Enemy Ships",
            "altitude_ft": 2000,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_navalengagement_auftrag_to_legion_uses_navalengagement_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_NAVALENGAGEMENT(target="UNIT:Target Ship", speed_kts=18, depth_m=20)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Naval Group")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_navalengagement"
        assert command.params == {
            "target": "UNIT:Target Ship",
            "speed_kts": 18,
            "depth_m": 20,
            "legion_id": "LEGION:Naval Group",
        }

    asyncio.run(scenario())


def test_sdk_add_escort_auftrag_to_legion_uses_escort_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_ESCORT(
            target="GROUP:Package Lead",
            offset_x=-100,
            offset_y=0,
            offset_z=200,
            engage_max_distance_nm=32,
            target_types=("Air",),
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_escort"
        assert command.params == {
            "target": "GROUP:Package Lead",
            "offset_x": -100,
            "offset_y": 0,
            "offset_z": 200,
            "engage_max_distance_nm": 32,
            "target_types": ["Air"],
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_rescuehelo_auftrag_to_legion_uses_rescuehelo_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_RESCUEHELO(target="UNIT:Carrier-1")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Rescue Detachment")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_rescuehelo"
        assert command.params == {
            "target": "UNIT:Carrier-1",
            "legion_id": "LEGION:Rescue Detachment",
        }

    asyncio.run(scenario())


def test_sdk_add_trooptransport_auftrag_to_legion_uses_trooptransport_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_TROOPTRANSPORT(
            transport_groups=("GROUP:Infantry-1", "GROUP:Infantry-2"),
            dropoff="ZONE:LZ Bravo",
            pickup="ZONE:LZ Alpha",
            pickup_radius_m=100,
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Helo Lift")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_trooptransport"
        assert command.params == {
            "transport_groups": ["GROUP:Infantry-1", "GROUP:Infantry-2"],
            "dropoff": "ZONE:LZ Bravo",
            "pickup": "ZONE:LZ Alpha",
            "pickup_radius_m": 100,
            "legion_id": "LEGION:Helo Lift",
        }

    asyncio.run(scenario())


def test_group_set_serializes_to_flat_params_value() -> None:
    group_set = GroupSet("GROUP:Infantry-1", "GROUP:Infantry-2")

    assert group_set.object_ids == ("GROUP:Infantry-1", "GROUP:Infantry-2")
    assert group_set.to_params_value() == ["GROUP:Infantry-1", "GROUP:Infantry-2"]
    assert isinstance(group_set, GeneralSet)


def test_group_set_rejects_non_group_object_ids() -> None:
    try:
        GroupSet("UNIT:Infantry-1")
    except ValueError as exc:
        assert "GROUP:<name>" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_sdk_add_trooptransport_accepts_group_set() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        troops = GroupSet("GROUP:Infantry-1", "GROUP:Infantry-2")
        auftrag = Auftrag_TROOPTRANSPORT(
            transport_groups=troops,
            dropoff="ZONE:LZ Bravo",
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Helo Lift")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_trooptransport"
        assert command.params == {
            "transport_groups": ["GROUP:Infantry-1", "GROUP:Infantry-2"],
            "dropoff": "ZONE:LZ Bravo",
            "legion_id": "LEGION:Helo Lift",
        }

    asyncio.run(scenario())


def test_sdk_add_trooptransport_accepts_single_group_string() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_TROOPTRANSPORT(
            transport_groups="GROUP:Infantry-1",
            dropoff="ZONE:LZ Bravo",
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Helo Lift")

        command = server.commands[0][0]
        assert command.params["transport_groups"] == ["GROUP:Infantry-1"]

    asyncio.run(scenario())


def test_sdk_add_orbit_auftrag_to_legion_uses_orbit_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_ORBIT(
            target="ZONE:CAP Station",
            altitude_ft=15000,
            speed_kts=300,
            heading_deg=90,
            leg_nm=20,
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_orbit"
        assert command.params == {
            "target": "ZONE:CAP Station",
            "altitude_ft": 15000,
            "speed_kts": 300,
            "heading_deg": 90,
            "leg_nm": 20,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_awacs_auftrag_to_legion_uses_awacs_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_AWACS(
            target="ZONE:AWACS Track",
            altitude_ft=30000,
            speed_kts=350,
            heading_deg=270,
            leg_nm=10,
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_awacs"
        assert command.params == {
            "target": "ZONE:AWACS Track",
            "altitude_ft": 30000,
            "speed_kts": 350,
            "heading_deg": 270,
            "leg_nm": 10,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_tanker_auftrag_to_legion_uses_tanker_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_TANKER(
            target="ZONE:Tanker Track",
            altitude_ft=20000,
            speed_kts=300,
            heading_deg=270,
            leg_nm=10,
            refuel_system=1,
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_tanker"
        assert command.params == {
            "target": "ZONE:Tanker Track",
            "altitude_ft": 20000,
            "speed_kts": 300,
            "heading_deg": 270,
            "leg_nm": 10,
            "refuel_system": 1,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_cap_auftrag_to_legion_uses_cap_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_CAP(
            zone="ZONE:Town Fight",
            altitude_ft=15000,
            speed_kts=300,
            coordinate="ZONE:CAP Station",
            heading_deg=90,
            leg_nm=20,
            target_types=("Air",),
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_cap"
        assert command.params == {
            "zone": "ZONE:Town Fight",
            "altitude_ft": 15000,
            "speed_kts": 300,
            "coordinate": "ZONE:CAP Station",
            "heading_deg": 90,
            "leg_nm": 20,
            "target_types": ["Air"],
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_cas_auftrag_to_legion_uses_cas_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_CAS(
            zone="ZONE:Town Fight",
            altitude_ft=12000,
            speed_kts=280,
            heading_deg=45,
            leg_nm=12,
            target_types=("Ground Units", "Light armed ships"),
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_cas"
        assert command.params == {
            "zone": "ZONE:Town Fight",
            "altitude_ft": 12000,
            "speed_kts": 280,
            "heading_deg": 45,
            "leg_nm": 12,
            "target_types": ["Ground Units", "Light armed ships"],
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_casenhanced_auftrag_to_legion_uses_casenhanced_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_CASENHANCED(
            zone="ZONE:Town Fight",
            altitude_ft=2000,
            speed_kts=250,
            range_max_nm=25,
            no_engage_zones=("ZONE:Friendly Area",),
            target_types=("Ground Units", "Light armed ships"),
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_casenhanced"
        assert command.params == {
            "zone": "ZONE:Town Fight",
            "altitude_ft": 2000,
            "speed_kts": 250,
            "range_max_nm": 25,
            "no_engage_zones": ["ZONE:Friendly Area"],
            "target_types": ["Ground Units", "Light armed ships"],
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_fac_auftrag_to_legion_uses_fac_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_FAC(
            zone="ZONE:Town Fight",
            speed_kts=80,
            altitude_ft=2000,
            frequency_mhz=133,
            modulation=0,
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Brigade")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_fac"
        assert command.params == {
            "zone": "ZONE:Town Fight",
            "speed_kts": 80,
            "altitude_ft": 2000,
            "frequency_mhz": 133,
            "modulation": 0,
            "legion_id": "LEGION:Ground Brigade",
        }

    asyncio.run(scenario())


def test_sdk_add_patrolzone_auftrag_to_legion_uses_patrolzone_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_PATROLZONE(zone="ZONE:Patrol Area", speed_kts=20, altitude_ft=2000, formation="Off Road")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Brigade")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_patrolzone"
        assert command.params == {
            "zone": "ZONE:Patrol Area",
            "speed_kts": 20,
            "altitude_ft": 2000,
            "formation": "Off Road",
            "legion_id": "LEGION:Ground Brigade",
        }

    asyncio.run(scenario())


def test_sdk_add_capturezone_auftrag_to_legion_uses_capturezone_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_CAPTUREZONE(
            opszone="OPSZONE:Town Fight",
            capture_coalition="blue",
            speed_kts=20,
            altitude_ft=2000,
            formation="Off Road",
            stay_in_zone_time_s=300,
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Brigade")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_capturezone"
        assert command.params == {
            "opszone": "OPSZONE:Town Fight",
            "capture_coalition": "blue",
            "speed_kts": 20,
            "altitude_ft": 2000,
            "formation": "Off Road",
            "stay_in_zone_time_s": 300,
            "legion_id": "LEGION:Ground Brigade",
        }

    asyncio.run(scenario())


def test_sdk_add_capturezone_auftrag_allows_omitted_speed() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_CAPTUREZONE(opszone="OPSZONE:Town Fight", capture_coalition="blue")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Ground Brigade")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_capturezone"
        assert command.params == {
            "opszone": "OPSZONE:Town Fight",
            "capture_coalition": "blue",
            "legion_id": "LEGION:Ground Brigade",
        }

    asyncio.run(scenario())


def test_sdk_add_faca_auftrag_to_legion_uses_faca_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_FACA(
            target="GROUP:Ground-1",
            designation="LASER",
            data_link=False,
            frequency_mhz=133,
            modulation=0,
        )

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_faca"
        assert command.params == {
            "target": "GROUP:Ground-1",
            "designation": "LASER",
            "data_link": False,
            "frequency_mhz": 133,
            "modulation": 0,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_sead_auftrag_to_legion_uses_sead_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_SEAD(target="UNIT:SA-11-1", altitude_ft=25000)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_sead"
        assert command.params == {
            "target": "UNIT:SA-11-1",
            "altitude_ft": 25000,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_intercept_auftrag_to_legion_uses_intercept_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_INTERCEPT(target="GROUP:Bandit-1")

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_intercept"
        assert command.params == {
            "target": "GROUP:Bandit-1",
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_strike_auftrag_to_legion_uses_strike_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_STRIKE(target="ZONE:Factory", altitude_ft=2000, engage_weapon_type=1)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_strike"
        assert command.params == {
            "target": "ZONE:Factory",
            "altitude_ft": 2000,
            "engage_weapon_type": 1,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_strafing_auftrag_to_legion_uses_strafing_params() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_STRAFING(target="GROUP:Convoy", altitude_ft=1000, length_m=300)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")

        command = server.commands[0][0]
        assert command.action == "auftrag.create_strafing"
        assert command.params == {
            "target": "GROUP:Convoy",
            "altitude_ft": 1000,
            "length_m": 300,
            "legion_id": "LEGION:Wing Parchim",
        }

    asyncio.run(scenario())


def test_sdk_add_auftrag_requires_one_assignment_target() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_BAI(target="GROUP:Ground-1")

        try:
            await client.add_auftrag(auftrag=auftrag)
        except ValueError as exc:
            assert "exactly one" in str(exc)
        else:
            raise AssertionError("Expected ValueError")

    asyncio.run(scenario())


def test_sdk_get_auftrag_summary_waits_for_object_created_by_add() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)

        await client.add_auftrag(auftrag=auftrag, legion="LEGION:Wing Parchim")
        summary = await client.get_auftrag_summary(auftrag, timeout_s=1.0, interval_s=0.01)

        assert summary.auftrag_id == "AUFTRAG:1"
        assert summary.success is True
        assert summary.n_destroyed == 1
        assert [command.action for command, _ in server.commands] == ["auftrag.create_bai"]

    asyncio.run(scenario())


def test_sdk_get_auftrag_summary_accepts_direct_auftrag_id() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        summary = await client.get_auftrag_summary("AUFTRAG:1", timeout_s=1.0, interval_s=0.01)

        assert summary.success is True

    asyncio.run(scenario())


def test_sdk_get_auftrag_summary_calls_status_callback_for_intermediate_events() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        server.events_to_emit = [
            {
                "type": "event",
                "id": "event-started",
                "event": "auftrag.status",
                "payload": {
                    "event": "auftrag.status",
                    "auftrag_id": "AUFTRAG:1",
                    "fsm_event": "Started",
                    "status": "Started",
                    "from": "Planned",
                    "to": "Started",
                },
            },
            {
                "type": "event",
                "id": "event-evaluated",
                "event": "auftrag.evaluated",
                "payload": {
                    "event": "auftrag.evaluated",
                    "auftrag_id": "AUFTRAG:1",
                    "auftrag_type": "BAI",
                    "status": "Done",
                    "summary": {"success": True, "Ndestroyed": 1},
                },
            },
        ]
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        seen: list[str] = []

        summary = await client.get_auftrag_summary("AUFTRAG:1", timeout_s=1.0, on_status=lambda event: seen.append(str(event)))

        assert summary.success is True
        assert seen == ["AUFTRAG:1 Started status=Started Planned->Started"]

    asyncio.run(scenario())


def test_sdk_get_auftrag_summary_deduplicates_repeated_status_events() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        queued_event = {
            "type": "event",
            "event": "auftrag.status",
            "payload": {
                "event": "auftrag.status",
                "auftrag_id": "AUFTRAG:1",
                "fsm_event": "Queued",
                "status": "queued",
                "from": "planned",
                "to": "queued",
            },
        }
        server.events_to_emit = [
            {**queued_event, "id": "event-queued-1"},
            {**queued_event, "id": "event-queued-2"},
            {**queued_event, "id": "event-queued-3"},
            {
                "type": "event",
                "id": "event-evaluated",
                "event": "auftrag.evaluated",
                "payload": {
                    "event": "auftrag.evaluated",
                    "auftrag_id": "AUFTRAG:1",
                    "auftrag_type": "BAI",
                    "status": "Done",
                    "summary": {"success": True, "Ndestroyed": 1},
                },
            },
        ]
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        seen: list[str] = []

        summary = await client.get_auftrag_summary("AUFTRAG:1", timeout_s=1.0, on_status=lambda event: seen.append(str(event)))

        assert summary.success is True
        assert seen == ["AUFTRAG:1 Queued status=queued planned->queued"]

    asyncio.run(scenario())


def test_auftrag_event_uses_fsm_event_for_display() -> None:
    event = {
        "type": "event",
        "event": "auftrag.status",
        "payload": {
            "auftrag_id": "AUFTRAG:1",
            "fsm_event": "Executing",
            "status": "executing",
            "from": "started",
            "to": "executing",
        },
    }

    assert str(AuftragEvent.from_message(event)) == "AUFTRAG:1 Executing status=executing started->executing"


def test_auftrag_event_displays_cancel_event() -> None:
    event = {
        "type": "event",
        "event": "auftrag.status",
        "payload": {
            "auftrag_id": "AUFTRAG:1",
            "fsm_event": "Cancel",
            "status": "cancelled",
            "from": "started",
            "to": "cancelled",
        },
    }

    assert str(AuftragEvent.from_message(event)) == "AUFTRAG:1 Cancel status=cancelled started->cancelled"


def test_sdk_get_auftrag_summary_requires_known_object() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]
        auftrag = Auftrag_BAI(target="GROUP:Ground-1")

        try:
            await client.get_auftrag_summary(auftrag, timeout_s=0.01, interval_s=0.01)
        except ValueError as exc:
            assert "add_auftrag" in str(exc)
        else:
            raise AssertionError("Expected ValueError")

    asyncio.run(scenario())
