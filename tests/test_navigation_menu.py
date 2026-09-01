from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from moosebridge import FlightGroupRoute, MooseBridgeState
from moosebridge.navigation import NavigationSolution
from moosebridge.navigation_menu import NavigationMenuController, cockpit_status, reference_unit
from moosebridge.sdk import CoordinateResult


def route(group="Hornet"):
    return FlightGroupRoute.from_payload({
        "opsgroup_id": f"OPSGROUP:{group}", "route_source": "mission_editor", "coalition": "blue",
        "waypoints": [{"index": i, "name": f"WP {i}", "x": x, "z": 0,
                       "latitude": x / 100000, "longitude": 0}
                      for i, x in enumerate((0, 10000, 20000), 1)],
    })


def event(action="status", *, group="Hornet", session="1", owner="run", closed=False):
    return {"event": "player.menu.closed" if closed else "player.menu.selected", "payload": {
        "menu_id": "navigation", "owner_id": owner, "session_id": session,
        "group_id": f"GROUP:{group}", "action": action,
    }}


class Bridge:
    def __init__(self):
        self.state = MooseBridgeState()
        self.server = self
        self.calls, self.routes, self.positions = [], [], []
        self.context = {
            "owner_id": "run", "session_id": "1", "group_id": "GROUP:Hornet",
            "theater_id": "Caucasus",
            "opsgroup_id": "OPSGROUP:Hornet", "group_sessions": [{"unit_id": "UNIT:Hornet-1"}],
        }
        self.x = 0
        self.selection_serial = 0
        self.airbases = []
        self.flight_status = {
            "owner_id": "run", "session_id": "1", "group_id": "GROUP:Hornet",
            "unit_id": "UNIT:Hornet-1", "altitude_msl_m": 3048,
            "terrain_elevation_m": 0, "velocity_mps": {"x": 100, "y": 0, "z": 0},
        }

    async def send_command(self, command, **kwargs):
        self.calls.append(command)
        result = deepcopy(self.context) if command.action.endswith(".context") else {}
        if command.action.endswith(".flight_status"):
            result = deepcopy(self.flight_status)
        if command.action.endswith(".navaids.page"):
            result = {"navaid_revision": command.params["navaid_revision"] + 1}
        if command.action.endswith(".navaids.initialize"):
            result = {"types": {kind: {"initialized": True, "navaid_revision": 1, "page": 0}
                                for kind in command.params["types"]}}
        if command.action.endswith(".airfields.resolve"):
            requested = set(command.params["airbase_ids"])
            matched = [deepcopy(item) for item in self.airbases if item["airbase_id"] in requested]
            result = {"theater_id": command.params["theater_id"], "airbases": matched,
                      "unresolved_airbase_ids": sorted(requested.difference(item["airbase_id"] for item in matched))}
        if command.action.endswith(".airfields.initialize"):
            result = {"initialized": True, "airfield_revision": 1, "page": 0}
        if command.action.endswith(".airfields.page"):
            result = {"airfield_revision": command.params["airfield_revision"] + 1}
        if command.action.endswith(".message") and command.params.get("station_key"):
            self.selection_serial += 1
            result = {"selection_id": str(self.selection_serial)}
        return {"ok": True, "result": result}

    async def get_flightgroup_route(self, object_id, **kwargs):
        self.routes.append((object_id, kwargs))
        return route(object_id.removeprefix("OPSGROUP:"))

    async def coords(self, object_id, **kwargs):
        self.positions.append(object_id)
        return CoordinateResult(object_id=object_id, format="ll", x=self.x, z=0,
                                latitude=self.x / 100000, longitude=0, ack={"mission_time": 10})

    def messages(self):
        return [c.params["text"] for c in self.calls if c.action.endswith(".message")]


def test_route_show_hide_are_guarded_and_do_not_start_polling():
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event("route_show"))
        await controller.handle(event("route_show"))
        await controller.handle(event("route_hide"))
        overlays = [c for c in bridge.calls if c.action.endswith(".overlay")]
        assert [c.params["show"] for c in overlays] == [True, True, False]
        assert len(overlays[0].params["features"][0]["points"]) == 3
        assert overlays[0].params["features"][0]["color"] == [0.0, 1.0, 1.0, 1.0]
        assert all(c.params["owner_id"] == "run" and c.params["session_id"] == "1" for c in overlays)
        assert all("coalition" not in c.params and "overlay_id" not in c.params for c in overlays)
        assert len(bridge.routes) == 1 and not bridge.positions
        await controller.close()
    asyncio.run(scenario())


def test_flight_status_is_fresh_on_demand_without_flightgroup_or_navigation_changes(capsys):
    async def scenario():
        bridge = Bridge()
        bridge.context["opsgroup_id"] = None
        bridge.flight_status.update(true_airspeed_mps=150, estimated_ias_mps=125, mach_number=0.45)
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event("flight_status"))
        first = bridge.messages()[-1]
        assert "10,000 ft MSL" in first
        assert "IAS: 243.0 kt | TAS: 291.6 kt" in first
        assert "GS: 194.4 kt | Mach: 0.450" in first
        assert bridge.calls[-1].params["duration_s"] == 15
        bridge.flight_status["altitude_msl_m"] = 6096
        bridge.flight_status["estimated_ias_mps"] = None
        await controller.handle(event("flight_status"))
        assert "20,000 ft MSL" in bridge.messages()[-1]
        assert "IAS: N/A" in bridge.messages()[-1]  # Never reuse the previous sample.
        assert not bridge.routes and not bridge.positions
        state = controller.groups[("GROUP:Hornet", "1")]
        assert state.route is None and state.navigator is None and state.hints is None
        assert [c.action.rsplit(".", 1)[-1] for c in bridge.calls] == [
            "flight_status", "message", "flight_status", "message",
        ]
        assert all(c.params["unit_id"] == "UNIT:Hornet-1" for c in bridge.calls if c.action.endswith(".message"))
        assert first in capsys.readouterr().out
        await controller.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["owner_id", "session_id", "group_id", "invalid_altitude", "mission_end", "stale_reply"])
def test_flight_status_rejects_invalid_or_stale_results(failure, capsys):
    async def scenario():
        bridge = Bridge()
        if failure in {"owner_id", "session_id", "group_id"}:
            bridge.flight_status[failure] = "another-session"
        elif failure == "invalid_altitude":
            bridge.flight_status["altitude_msl_m"] = float("nan")
        original = bridge.send_command

        async def send(command, **kwargs):
            if failure == "stale_reply" and command.action.endswith(".message"):
                raise RuntimeError("Flight status reference aircraft changed")
            result = await original(command, **kwargs)
            if failure == "mission_end":
                bridge.state.reset_mission()
            return result
        bridge.send_command = send
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event("flight_status"))
        assert not any(text.startswith("Flight status |") for text in bridge.messages())
        assert "Flight status |" not in capsys.readouterr().out
        assert not bridge.routes and not bridge.positions
        await controller.close()
    asyncio.run(scenario())


def test_status_uses_player_unit_and_retains_progress_when_route_is_hidden():
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event())
        assert "Leg: WP 1 -> WP 2" in bridge.messages()[-1]
        assert "TRUE" in bridge.messages()[-1] and "Cross-track error" in bridge.messages()[-1]
        bridge.x = 10000
        await controller.handle(event())
        assert "Leg: WP 2 -> WP 3" in bridge.messages()[-1]
        await controller.handle(event("route_hide"))
        bridge.x = 0
        await controller.handle(event())
        assert "Leg: WP 2 -> WP 3" in bridge.messages()[-1]
        assert set(bridge.positions) == {"UNIT:Hornet-1"}
        assert controller.groups[("GROUP:Hornet", "1")].hints is None
        await controller.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["hints_off", "closed", "shutdown"])
def test_hints_are_idempotent_periodic_and_cancelled(action):
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", sample_interval=0.001, hint_interval=0.002)
        await controller.handle(event("hints_on"))
        task = controller.groups[("GROUP:Hornet", "1")].hints
        await controller.handle(event("hints_on"))
        assert controller.groups[("GROUP:Hornet", "1")].hints is task
        for _ in range(100):
            if len(bridge.positions) >= 4:
                break
            await asyncio.sleep(0.001)
        assert len(bridge.positions) >= 4
        assert len([text for text in bridge.messages() if "Leg: WP 1 -> WP 2" in text]) >= 2
        if action == "closed":
            await controller.handle(event(closed=True))
            assert not controller.groups
        elif action == "hints_off":
            await controller.handle(event("hints_off"))
        else:
            await controller.close()
        count = len(bridge.positions)
        await asyncio.sleep(0.003)
        assert task.done() and len(bridge.positions) == count
        await controller.close()
    asyncio.run(scenario())


def test_final_waypoint_is_not_landing_and_does_not_start_hints():
    async def scenario():
        bridge = Bridge()
        bridge.x = 10000
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event())
        bridge.x = 20000
        await controller.handle(event("hints_on"))
        assert "landing status not checked" in bridge.messages()[-1]
        assert controller.groups[("GROUP:Hornet", "1")].hints is None
        await controller.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["missing_route", "multiple_aircraft", "wrong_position", "stale_context"])
def test_invalid_navigation_reports_to_group_without_starting_hints(failure):
    async def scenario():
        bridge = Bridge()
        if failure == "missing_route":
            bridge.context["opsgroup_id"] = None
        elif failure == "multiple_aircraft":
            bridge.context["group_sessions"].append({"unit_id": "UNIT:Wingman"})
        else:
            original = bridge.coords

            async def coords(*args, **kwargs):
                if failure == "stale_context":
                    bridge.context["session_id"] = "respawn"
                    return await original(*args, **kwargs)
                return await original("UNIT:OtherAircraft")
            bridge.coords = coords
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event("hints_on"))
        assert bridge.messages() and "Navigation:" in bridge.messages()[-1]
        state = controller.groups[("GROUP:Hornet", "1")]
        assert state.hints is None and state.navigator is None
        assert not any(c.action.endswith(".overlay") for c in bridge.calls)
        await controller.close()
    asyncio.run(scenario())


def test_multiple_seats_of_same_unit_are_not_ambiguous():
    assert reference_unit({"group_sessions": [{"unit_id": "UNIT:A"}, {"unit_id": "UNIT:A"}]}) == "UNIT:A"


@pytest.mark.parametrize("cross_track,expected", [
    (-125, "125 m left"), (125, "125 m right"), (0, "0 m on track"), (None, "N/A"),
])
def test_cockpit_output_is_english_without_translating_user_defined_names(cross_track, expected):
    # These names are user data, not project-authored interface text.
    solution = NavigationSolution(
        from_waypoint_index=1, target_waypoint_index=2, target_name="K\u00fcstenpunkt",
        distance_m=1852, bearing_true_deg=90, cross_track_m=cross_track,
        along_track_m=0, leg_length_m=1852, reached_waypoint_indexes=(), route_complete=True,
    )
    text = cockpit_status("UNIT:\u00dcberflug", solution)
    assert text == (
        "Navigation status | Reference: \u00dcberflug\n"
        "Leg: WP 1 -> WP 2 | Target: K\u00fcstenpunkt\n"
        "Distance: 1.00 NM | Bearing: 90.0 deg TRUE\n"
        f"Cross-track error: {expected}\n"
        "Route complete horizontally; landing status not checked."
    )


def test_navigation_feedback_and_errors_are_english():
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event("route_show"))
        assert bridge.messages()[-1] == "F10 route displayed: 3 waypoints (own coalition)."
        await controller.handle(event("route_hide"))
        assert bridge.messages()[-1] == "Route hidden on the F10 map."
        await controller.handle(event("hints_on"))
        assert bridge.messages()[-1].startswith("Navigation hints enabled (approximately every 10 s).")
        await controller.handle(event("hints_on"))
        assert bridge.messages()[-1] == "Navigation hints are already enabled."
        await controller.handle(event("hints_off"))
        assert bridge.messages()[-1] == "Navigation hints disabled."
        bridge.context["opsgroup_id"] = None
        await controller.handle(event("status"))
        assert bridge.messages()[-1] == "Navigation: No FLIGHTGROUP available. Please create it in the mission."
        await controller.close()
    asyncio.run(scenario())


def test_foreign_owner_is_ignored_and_old_close_does_not_reset_new_group_session():
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event(owner="other"))
        assert not bridge.calls
        await controller.handle(event())
        bridge.context["session_id"] = "2"
        await controller.handle(event(session="2"))
        await controller.handle(event(closed=True))
        assert ("GROUP:Hornet", "1") not in controller.groups
        assert ("GROUP:Hornet", "2") in controller.groups
        await controller.close()
    asyncio.run(scenario())


def test_two_groups_have_independent_trackers_and_hint_tasks():
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", sample_interval=10)
        await controller.handle(event("hints_on"))
        first = controller.groups[("GROUP:Hornet", "1")]
        first_task = first.hints
        bridge.context.update(group_id="GROUP:Other", opsgroup_id="OPSGROUP:Other", session_id="2",
                              group_sessions=[{"unit_id": "UNIT:Other-1"}])
        await controller.handle(event("hints_on", group="Other", session="2"))
        other = controller.groups[("GROUP:Other", "2")]
        assert first.navigator is not other.navigator
        assert other.unit_id == "UNIT:Other-1"
        await controller.handle(event(closed=True))
        assert first_task.done() and not other.hints.done()
        await controller.close()
        assert other.hints is None
    asyncio.run(scenario())


def test_mission_ending_during_position_query_does_not_emit_guidance():
    async def scenario():
        bridge = Bridge()
        original = bridge.coords

        async def coords(*args, **kwargs):
            bridge.state.reset_mission()
            return await original(*args, **kwargs)
        bridge.coords = coords
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(event("hints_on"))
        assert not bridge.messages()
        assert controller.groups[("GROUP:Hornet", "1")].hints is None
        await controller.close()
    asyncio.run(scenario())


def test_vscode_script_delegates_to_persistent_application(monkeypatch):
    examples = Path(__file__).resolve().parents[1] / "examples/sdk"
    monkeypatch.syspath_prepend(str(examples))
    example = runpy.run_path(str(examples / "run_navigation_menu.py"))

    async def scenario():
        config = object()
        application = SimpleNamespace(run=AsyncMock(return_value=0))
        monkeypatch.setitem(example["run"].__globals__, "load_navigation_config", lambda path: config)
        def factory(value):
            assert value is config
            return application
        monkeypatch.setitem(example["run"].__globals__, "NavigationApplication", factory)
        assert await example["run"]() == 0
        application.run.assert_awaited_once()
    asyncio.run(scenario())
