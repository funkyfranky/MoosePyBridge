from __future__ import annotations

import asyncio
from typing import Any

from moosebridge.protocol import BridgeCommand
from moosebridge.sdk import CoordinateResult, DistanceResult, MooseBridgeClient, NearestResult
from moosebridge.state import MooseBridgeState


class FakeSdkServer:
    def __init__(self) -> None:
        self.state = MooseBridgeState(connected=True)
        self.commands: list[tuple[BridgeCommand, float]] = []

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
        return {"ok": True, "result": {"action": command.action, "params": command.params}}

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


def test_sdk_nearest_refreshes_snapshot_and_filters_results() -> None:
    async def scenario() -> None:
        server = FakeSdkServer()
        client = MooseBridgeClient(server)  # type: ignore[arg-type]

        results = await client.nearest("units", "ZONE:Town Fight", coalition="red", alive=True, limit=2)

        assert all(isinstance(result, NearestResult) for result in results)
        assert [result.object_id for result in results] == ["UNIT:Near", "UNIT:Far"]
        assert [command.action for command, _ in server.commands] == ["object.coords", "snapshot.units"]

    asyncio.run(scenario())
