from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import runpy
from typing import Any

import pytest

from moosebridge import FlightGroupRoute, MooseBridgeClient, PlayerAircraftEvent
from moosebridge.protocol import BridgeCommand
from moosebridge.state import MooseBridgeState


def route_payload() -> dict[str, Any]:
    return {
        "opsgroup_id": "OPSGROUP:Test Hornet",
        "group_id": "GROUP:Test Hornet",
        "coalition": "blue",
        "route_source": "mission_editor",
        "waypoints": [
            {
                "index": index,
                "name": f"Route point {index}",
                "latitude": 42 + index / 100,
                "longitude": 41 + index / 100,
                "x": -240000 + index * 100,
                "z": 616000 + index * 100,
                "altitude_m": 1000,
                "altitude_type": "RADIO" if index == 2 else "BARO",
                "speed_mps": 150,
                "type": "Land" if index == 3 else "Turning Point",
                "action": "Landing" if index == 3 else "Turning Point",
            }
            for index in range(1, 4)
        ],
    }


class RouteServer:
    def __init__(self) -> None:
        self.state = MooseBridgeState(connected=True)
        self.commands: list[BridgeCommand] = []
        self.result = route_payload()

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        self.commands.append(command)
        if command.action == "flightgroup.route.get":
            return {"ok": True, "result": deepcopy(self.result)}
        return {"ok": True, "result": {}}


def test_me_route_retains_landing_altitude_reference_and_point_order() -> None:
    route = FlightGroupRoute.from_payload(route_payload())
    assert route.waypoints[-1].waypoint_type == "Land"
    assert route.waypoints[1].altitude_type == "RADIO"
    assert route.waypoints[1].altitude_m == 1000
    assert route.waypoints[1].speed_mps == 150
    line = route.to_map_line()
    assert line.kind == "line"
    assert line.mark_count == 2
    assert line.color == (0, 1, 1, 1)
    assert [p.latitude for p in line.points] == [42.01, 42.02, 42.03]
    assert all(p.altitude == 0 for p in line.points)  # RADIO is not converted to ASL.


@pytest.mark.parametrize("field,value", [
    ("latitude", 91), ("longitude", float("nan")),
    ("speed_mps", -1), ("x", True), ("index", 0),
])
def test_route_rejects_invalid_waypoint_data(field: str, value: Any) -> None:
    payload = route_payload()
    payload["waypoints"][0][field] = value
    with pytest.raises(ValueError):
        FlightGroupRoute.from_payload(payload)


def test_route_does_not_sort_or_skip_invalid_indexes() -> None:
    payload = route_payload()
    payload["waypoints"].reverse()
    with pytest.raises(ValueError, match="ordered"):
        FlightGroupRoute.from_payload(payload)


def test_route_requires_two_points_to_draw_and_limits_size() -> None:
    payload = route_payload()
    payload["waypoints"] = payload["waypoints"][:1]
    route = FlightGroupRoute.from_payload(payload)
    with pytest.raises(ValueError, match="at least 2"):
        route.to_map_line()
    payload["waypoints"] *= 502
    with pytest.raises(ValueError, match="501"):
        FlightGroupRoute.from_payload(payload)


def test_sdk_reads_route_and_draws_only_a_coalition_overlay() -> None:
    async def scenario() -> None:
        server = RouteServer()
        with MooseBridgeClient(server) as bridge:
            route = await bridge.get_flightgroup_route("OPSGROUP:Test Hornet")
            await bridge.draw_debug_overlay("route-test", [route.to_map_line()], coalition=route.coalition)
        read, draw = server.commands
        assert read.action == "flightgroup.route.get"
        assert read.params == {"opsgroup_id": "OPSGROUP:Test Hornet", "route_source": "mission_editor"}
        assert draw.action == "map.overlay.draw"
        assert draw.params["coalition"] == "blue"
        assert draw.params["replace"] is True
        assert draw.params["features"][0]["kind"] == "line"
        assert len(draw.params["features"][0]["points"]) == 3
        assert not server.state.active_player_aircraft
    asyncio.run(scenario())


@pytest.mark.parametrize("object_id,source", [
    ("GROUP:Test Hornet", "mission_editor"),
    ("OPSGROUP:", "mission_editor"),
    ("OPSGROUP:Test Hornet", "other"),
])
def test_sdk_rejects_invalid_route_request_without_sending(object_id: str, source: str) -> None:
    async def scenario() -> None:
        server = RouteServer()
        with MooseBridgeClient(server) as bridge:
            with pytest.raises(ValueError):
                await bridge.get_flightgroup_route(object_id, route_source=source)
        assert not server.commands
    asyncio.run(scenario())


def test_sdk_checks_response_identity_and_supports_current_route() -> None:
    async def scenario() -> None:
        server = RouteServer()
        with MooseBridgeClient(server) as bridge:
            server.result["route_source"] = "current"
            assert (await bridge.get_flightgroup_route(
                "OPSGROUP:Test Hornet", route_source="current",
            )).route_source == "current"
            server.result["opsgroup_id"] = "OPSGROUP:Other"
            with pytest.raises(ValueError, match="different flight route"):
                await bridge.get_flightgroup_route("OPSGROUP:Test Hornet", route_source="current")
    asyncio.run(scenario())


def test_example_draws_route_from_enter_event(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "sdk"
    monkeypatch.syspath_prepend(str(examples))
    example = runpy.run_path(str(examples / "monitor_player_aircraft.py"))

    async def scenario() -> None:
        server = RouteServer()
        with MooseBridgeClient(server) as bridge:
            await example["show_route"](bridge, PlayerAircraftEvent(
                event_name="player.aircraft.entered", player_name="Pilot",
                unit_id="UNIT:Hornet", opsgroup_id="OPSGROUP:Test Hornet",
                coalition="blue",
            ))
        assert [c.action for c in server.commands] == ["flightgroup.route.get", "map.overlay.draw"]
    asyncio.run(scenario())
    output = capsys.readouterr().out
    assert "WP 3:" in output
    assert "cyan route drawn (3 waypoints, 2 segments, coalition=blue)" in output
