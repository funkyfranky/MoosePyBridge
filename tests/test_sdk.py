from __future__ import annotations

import asyncio
from typing import Any

from moosebridge.protocol import BridgeCommand
from moosebridge.sdk import Auftrag_ARTY, Auftrag_BAI, CoordinateResult, DistanceResult, MooseBridgeClient, NearestResult
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
        assert seen == ["AUFTRAG:1 auftrag.status status=Started Planned->Started"]

    asyncio.run(scenario())


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
