from __future__ import annotations

import asyncio
from dataclasses import replace
import math
from pathlib import Path
import runpy
from typing import Any

import pytest

from moosebridge import FlightGroupRoute, PlayerAircraftEvent, RouteNavigator, format_navigation_status
from moosebridge.sdk import CoordinateResult
from moosebridge.state import MooseBridgeState


def route() -> FlightGroupRoute:
    return FlightGroupRoute.from_payload({
        "opsgroup_id": "OPSGROUP:Hornet", "route_source": "mission_editor", "coalition": "blue",
        "waypoints": [
            {
                "index": i, "name": f"WP {i}", "x": x, "z": z,
                "latitude": latitude, "longitude": longitude,
            }
            for i, (x, z, latitude, longitude) in enumerate((
                (0, 0, 0, 0), (10000, 0, 0.09, 0), (10000, 10000, 0.09, 0.09),
            ), 1)
        ],
    })


def update(nav: RouteNavigator, x: float, z: float, time: float | None = None):
    return nav.update(x=x, z=z, latitude=x * 0.000009, longitude=z * 0.000009, mission_time=time)


@pytest.mark.parametrize("z,side", [(1000, "right"), (-1000, "left"), (0, "on track")])
def test_northbound_leg_distance_and_signed_cross_track(z: float, side: str) -> None:
    result = update(RouteNavigator(route()), 5000, z)
    assert result.target_waypoint_index == 2
    assert result.distance_m == pytest.approx(math.hypot(5000, z))
    assert result.distance_nm == pytest.approx(result.distance_m / 1852)
    assert result.along_track_m == 5000
    assert result.leg_length_m == 10000
    assert result.cross_track_m == z
    assert result.cross_track_side == side
    assert not result.route_complete


def test_eastbound_leg_north_side_is_left() -> None:
    result = update(RouteNavigator(route(), initial_target_index=3), 11000, 5000)
    assert result.cross_track_m == -1000
    assert result.cross_track_side == "left"


def test_true_bearing_and_dateline() -> None:
    north = update(RouteNavigator(route()), 0, 0)
    assert north.bearing_true_deg == pytest.approx(0)
    original = route()
    dateline = replace(original, waypoints=(
        replace(original.waypoints[0], latitude=0, longitude=179.9),
        replace(original.waypoints[1], x=0, z=20000, latitude=0, longitude=-179.9),
    ))
    result = RouteNavigator(dateline).update(x=0, z=0, latitude=0, longitude=179.9)
    assert result.bearing_true_deg == pytest.approx(90)


def test_waypoint_sequence_is_monotonic_and_final_capture_is_sticky() -> None:
    nav = RouteNavigator(route())
    assert update(nav, 0, 0).target_waypoint_index == 2
    reached = update(nav, 10000, 0)
    assert reached.reached_waypoint_indexes == (2,)
    assert reached.target_waypoint_index == 3
    assert update(nav, 0, 0).target_waypoint_index == 3
    final = update(nav, 10000, 10000)
    assert final.reached_waypoint_indexes == (3,)
    assert final.route_complete
    assert final.bearing_true_deg is None
    assert final.distance_m == 0
    again = update(nav, 10000, 12000)
    assert again.route_complete and not again.reached_waypoint_indexes


def test_manual_next_previous_sequence_and_capture_guard():
    nav = RouteNavigator(route())
    assert nav.target_waypoint_index == 2
    assert nav.select_next_waypoint() and nav.target_waypoint_index == 3
    assert not nav.select_next_waypoint()  # Last waypoint is the upper bound.
    assert nav.select_previous_waypoint() and nav.target_waypoint_index == 2
    assert not nav.select_previous_waypoint()  # WP 1 remains the route anchor.

    # Selecting Previous while inside WP 2 must not auto-advance immediately.
    guarded = update(nav, 10000, 0, 1)
    assert guarded.target_waypoint_index == 2 and not guarded.reached_waypoint_indexes
    update(nav, 8000, 0, 2)  # Leaving the capture circle arms automatic capture again.
    captured = update(nav, 10000, 0, 3)
    assert captured.reached_waypoint_indexes == (2,)
    assert captured.target_waypoint_index == 3


def test_previous_waypoint_reopens_completed_route():
    nav = RouteNavigator(route(), initial_target_index=3)
    assert update(nav, 10000, 10000).route_complete
    assert nav.select_previous_waypoint()
    result = update(nav, 9000, 0)
    assert not result.route_complete and result.target_waypoint_index == 2


def test_sampled_flyby_captures_within_corridor() -> None:
    nav = RouteNavigator(route())
    update(nav, 9000, -1000, 10)
    result = update(nav, 11000, 1000, 12)
    assert result.reached_waypoint_indexes == (2,)


@pytest.mark.parametrize("offset,time", [(2000, 12), (0, 30), (0, 9), (0, None)])
def test_flyby_does_not_capture_far_off_track_or_across_stale_samples(offset: float, time: float | None) -> None:
    nav = RouteNavigator(route())
    update(nav, 9000, offset, 10)
    result = update(nav, 11000, offset, time)
    assert not result.reached_waypoint_indexes
    assert result.target_waypoint_index == 2


def test_first_sample_beyond_waypoint_does_not_skip_it() -> None:
    result = update(RouteNavigator(route()), 20000, 0, 1)
    assert not result.reached_waypoint_indexes
    assert result.target_waypoint_index == 2


def test_duplicate_waypoint_coordinates_are_safe() -> None:
    original = route()
    duplicate = replace(original, waypoints=(
        original.waypoints[0], replace(original.waypoints[1], x=0, z=0, latitude=0),
        original.waypoints[2],
    ))
    nav = RouteNavigator(duplicate)
    undefined = update(nav, 2000, 0)
    assert undefined.cross_track_m is None
    assert "zero-length leg" in format_navigation_status(undefined)
    assert update(nav, 0, 0).reached_waypoint_indexes == (2,)


@pytest.mark.parametrize("kwargs", [
    {"capture_radius_m": 0}, {"capture_radius_m": float("nan")},
    {"initial_target_index": 1}, {"initial_target_index": 4},
    {"max_sample_gap_s": -1},
])
def test_invalid_configuration_is_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RouteNavigator(route(), **kwargs)


def test_invalid_position_is_rejected_without_advancing() -> None:
    nav = RouteNavigator(route())
    with pytest.raises(ValueError):
        nav.update(x=float("inf"), z=0, latitude=0, longitude=0)
    with pytest.raises(ValueError):
        nav.update(x=10000, z=0, latitude=91, longitude=0)
    assert update(nav, 0, 0).target_waypoint_index == 2
    assert "deg true" in format_navigation_status(update(nav, 0, 0))


def test_live_monitor_queries_unit_and_is_cancelled_on_leave(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "sdk"
    monkeypatch.syspath_prepend(str(examples))
    example = runpy.run_path(str(examples / "monitor_player_aircraft.py"))

    class Bridge:
        def __init__(self):
            self.state = MooseBridgeState()
            self.state.active_player_aircraft["Pilot"] = {"unit_id": "UNIT:Hornet"}
            self.calls = []
            self.queried = asyncio.Event()

        async def coords(self, object_id: str, **kwargs):
            self.calls.append((object_id, kwargs))
            self.queried.set()
            return CoordinateResult(
                object_id=object_id, format="ll", x=0, z=0, latitude=0, longitude=0,
                ack={"mission_time": 1},
            )

    async def scenario() -> None:
        bridge = Bridge()
        event = PlayerAircraftEvent("player.aircraft.entered", "Pilot", "UNIT:Hornet")
        task = asyncio.create_task(example["monitor_navigation"](bridge, event, RouteNavigator(route())))
        tasks = {"Pilot": task}
        await bridge.queried.wait()
        await asyncio.sleep(0)
        bridge.state.active_player_aircraft.clear()
        await example["stop_navigation_tasks"](tasks, "Pilot")
        assert task.done() and not tasks
        assert len(bridge.calls) == 1
        assert bridge.calls[0][0] == "UNIT:Hornet"
        assert bridge.calls[0][1]["format"] == "ll"
    asyncio.run(scenario())
    assert "NAV WP 1->2" in capsys.readouterr().out


def test_monitor_does_not_publish_position_after_mission_end(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "sdk"
    monkeypatch.syspath_prepend(str(examples))
    example = runpy.run_path(str(examples / "monitor_player_aircraft.py"))

    class Bridge:
        def __init__(self):
            self.state = MooseBridgeState()
            self.state.active_player_aircraft["Pilot"] = {}

        async def coords(self, object_id: str, **kwargs):
            self.state.reset_mission()
            return CoordinateResult(
                object_id=object_id, format="ll", x=0, z=0, latitude=0, longitude=0,
            )

    asyncio.run(example["monitor_navigation"](
        Bridge(), PlayerAircraftEvent("player.aircraft.entered", "Pilot", "UNIT:Hornet"),
        RouteNavigator(route()),
    ))
    assert "NAV WP" not in capsys.readouterr().out


@pytest.mark.parametrize("boundary", ["player.aircraft.left", "mission.ended"])
def test_example_lifecycle_stops_navigation_and_owns_only_its_overlay(
    boundary: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    examples = Path(__file__).resolve().parents[1] / "examples" / "sdk"
    monkeypatch.syspath_prepend(str(examples))
    example = runpy.run_path(str(examples / "monitor_player_aircraft.py"))
    globals_ = example["run"].__globals__
    monkeypatch.setitem(globals_, "TEST_CYCLES", 1)
    monkeypatch.setitem(globals_, "PLAYER_NAME", "Pilot")

    class Bridge:
        def __init__(self):
            self.state = MooseBridgeState(connected=True)
            self.server = self
            self.wait_count = 0
            self.position_count = 0
            self.position_requested = asyncio.Event()
            self.closed = False
            self.cleared = []

        async def event_cursor(self):
            return "baseline"

        async def wait_for_event(self, *args, **kwargs):
            self.wait_count += 1
            if self.wait_count > 2:
                raise TimeoutError("end of test")
            if self.wait_count == 2:
                await self.position_requested.wait()
            message = {
                "id": f"e{self.wait_count}", "type": "event",
                "event": "player.aircraft.entered" if self.wait_count == 1 else boundary,
                "payload": {
                    "player_name": "Pilot", "unit_id": "UNIT:Hornet",
                    "opsgroup_id": "OPSGROUP:Hornet", "coalition": "blue",
                },
            }
            self.state.apply_message(message)
            return message

        async def query_events(self, *args, **kwargs):
            return {"events": [{}]}

        async def get_flightgroup_route(self, *args, **kwargs):
            return route()

        async def draw_debug_overlay(self, *args, **kwargs):
            return {"ok": True}

        async def clear_debug_overlay(self, overlay_id, **kwargs):
            self.cleared.append(overlay_id)

        async def coords(self, object_id, **kwargs):
            self.position_count += 1
            self.position_requested.set()
            return CoordinateResult(
                object_id=object_id, format="ll", x=0, z=0, latitude=0, longitude=0,
            )

        def close(self):
            self.closed = True

    async def scenario() -> None:
        bridge = Bridge()

        async def open_session(*args, **kwargs):
            return SimpleNamespace(bridge=bridge)

        monkeypatch.setitem(globals_, "open_example_session", open_session)
        if boundary == "mission.ended":
            with pytest.raises(TimeoutError, match="end of test"):
                await example["run"]()
            assert not bridge.cleared  # Mission ending already removes its F10 shapes.
        else:
            assert await example["run"]() == 0
            assert bridge.cleared == ["navigation-player-route"]
        assert bridge.position_count == 1
        assert bridge.closed
        assert not bridge.state.active_player_aircraft
        assert not [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
    asyncio.run(scenario())
