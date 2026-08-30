"""Observe player sessions and draw their Mission Editor route on the F10 map."""

from __future__ import annotations

import asyncio
import logging
import math

from example_support import open_example_session, run_example

from moosebridge import (
    FlightGroupRoute, MooseBridgeClient, PlayerAircraftEvent, RouteNavigator,
    format_navigation_status,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
PLAYER_NAME: str | None = "funkyfranky"
TEST_CYCLES = 2
COMMAND_TIMEOUT_SECONDS = 10.0
EVENT_TIMEOUT_SECONDS = 3600.0
DRAW_ROUTE_ON_ENTER = True
ROUTE_SOURCE = "mission_editor"  # "current" uses OPSGROUP:GetWaypoints() instead.
ROUTE_OVERLAY_ID = "navigation-player-route"
MONITOR_NAVIGATION = True
NAVIGATION_INTERVAL_SECONDS = 2.0
INITIAL_TARGET_WAYPOINT = 2  # Python's route progress, NOT the cockpit selection.
WAYPOINT_CAPTURE_RADIUS_M = 500.0
NAVIGATION_MAX_SAMPLE_GAP_SECONDS = 10.0


async def show_route(
    bridge: MooseBridgeClient, event: PlayerAircraftEvent, *, draw: bool = True,
) -> FlightGroupRoute:
    """Read a player's FLIGHTGROUP route and draw it for that coalition."""

    if not event.opsgroup_id:
        raise ValueError("No FLIGHTGROUP associated with this player; create it in the mission first.")
    route = await bridge.get_flightgroup_route(
        event.opsgroup_id, route_source=ROUTE_SOURCE, timeout=COMMAND_TIMEOUT_SECONDS,
    )
    coalition = route.coalition or event.coalition
    if coalition not in {"blue", "red", "neutral"}:
        raise ValueError("Cannot determine the route coalition; refusing a public F10 overlay.")
    print(f"Flight route: {route.opsgroup_id}, source={route.route_source}", flush=True)
    for wp in route.waypoints:
        print(
            f"  WP {wp.index}: {wp.name} "
            f"lat={wp.latitude:.6f} lon={wp.longitude:.6f} "
            f"alt={wp.altitude_m} m ({wp.altitude_type or 'unknown reference'}) "
            f"speed={wp.speed_mps} m/s type={wp.waypoint_type or '-'}",
            flush=True,
        )
    if draw:
        await bridge.draw_debug_overlay(
            ROUTE_OVERLAY_ID, [route.to_map_line()], coalition=coalition,
            replace=True, timeout=COMMAND_TIMEOUT_SECONDS,
        )
        print(
            f"F10: cyan route drawn ({len(route.waypoints)} waypoints, "
            f"{len(route.waypoints) - 1} segments, coalition={coalition})",
            flush=True,
        )
    return route


async def monitor_navigation(
    bridge: MooseBridgeClient, event: PlayerAircraftEvent, navigator: RouteNavigator,
) -> None:
    """Poll only this player's unit; the lifecycle loop cancels this task on leave."""

    session_key = event.player_name or event.unit_id
    if not event.unit_id:
        raise ValueError("Navigation requires the player's UNIT: id")
    print(
        f"NAV: sampling {event.unit_id} every {NAVIGATION_INTERVAL_SECONDS:g}s; "
        f"initial target WP {INITIAL_TARGET_WAYPOINT}, capture radius "
        f"{WAYPOINT_CAPTURE_RADIUS_M:g}m; bearings are TRUE, not magnetic.",
        flush=True,
    )
    while not bridge.state.mission_ended and session_key in bridge.state.active_player_aircraft:
        try:
            position = await bridge.coords(event.unit_id, format="ll", timeout=COMMAND_TIMEOUT_SECONDS)
            if bridge.state.mission_ended or session_key not in bridge.state.active_player_aircraft:
                return
            if position.object_id != event.unit_id:
                raise ValueError("Received coordinates for a different unit")
            solution = navigator.update(
                x=position.x, z=position.z,
                latitude=position.latitude, longitude=position.longitude,
                mission_time=(position.ack or {}).get("mission_time"),
            )
            for index in solution.reached_waypoint_indexes:
                print(f"NAV: waypoint {index} reached horizontally", flush=True)
            print(format_navigation_status(solution), flush=True)
            if solution.route_complete:
                print("NAV: final waypoint reached horizontally; landing has NOT been checked.", flush=True)
                return
        except (ConnectionError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
            print(f"NAV: position unavailable ({exc}); no new guidance, retrying.", flush=True)
        await asyncio.sleep(NAVIGATION_INTERVAL_SECONDS)


async def stop_navigation_tasks(
    tasks: dict[str, asyncio.Task[None]], session_key: str | None = None,
) -> None:
    """Cancel and await pending position requests before cleaning up the session."""

    if session_key is None:
        pending = list(tasks.values())
        tasks.clear()
    else:
        task = tasks.pop(session_key, None)
        pending = [task] if task is not None else []
    for task in pending:
        task.cancel()
    for result in await asyncio.gather(*pending, return_exceptions=True):
        if isinstance(result, Exception):
            logging.warning("Navigation task stopped with an error: %s", result)


def describe_active_sessions(bridge: MooseBridgeClient) -> None:
    """Print the active player-aircraft state mirrored by Python."""

    sessions = bridge.state.active_player_aircraft
    if not sessions:
        print("Python state: no active player aircraft sessions", flush=True)
        return
    print(f"Python state: {len(sessions)} active player aircraft session(s)", flush=True)
    for key, session in sessions.items():
        print(
            "  "
            f"{key}: unit={session.get('unit_id') or '-'} "
            f"group={session.get('group_id') or '-'} "
            f"opsgroup={session.get('opsgroup_id') or '-'} "
            f"type={session.get('aircraft_type') or '-'}",
            flush=True,
        )


async def run() -> int:
    """Run the DCS-facing lifecycle monitor."""

    if TEST_CYCLES < 1:
        raise ValueError("TEST_CYCLES must be at least 1")
    if not math.isfinite(NAVIGATION_INTERVAL_SECONDS) or NAVIGATION_INTERVAL_SECONDS <= 0:
        raise ValueError("NAVIGATION_INTERVAL_SECONDS must be positive and finite")

    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="player-aircraft-lifecycle-test",
        display_name="Player Aircraft Lifecycle Test",
    )
    bridge = session.bridge
    filters = {"player_name": PLAYER_NAME} if PLAYER_NAME else None
    completed_cycles = 0
    entered_players: set[str] = set()
    leave_counts: dict[str, int] = {}
    overlay_drawn = False
    navigation_tasks: dict[str, asyncio.Task[None]] = {}

    print(
        f"Connected to MoosePyBridge control API at "
        f"{CONTROL_HOST}:{CONTROL_PORT}",
        flush=True,
    )
    if PLAYER_NAME:
        print(f"Player filter: {PLAYER_NAME}", flush=True)
    print("Enter the aircraft slot, inspect the route on F10, then leave the slot.", flush=True)
    print("Waiting for player.aircraft.entered ...", flush=True)

    cursor = await bridge.server.event_cursor()
    initial_cursor = cursor
    try:
        while completed_cycles < TEST_CYCLES:
            message = await bridge.server.wait_for_event(
                "player.aircraft.*",
                filters=filters,
                timeout=EVENT_TIMEOUT_SECONDS,
                after_id=cursor,
            )
            cursor = str(message.get("id") or "") or cursor
            if message.get("event") == "mission.ended":
                await stop_navigation_tasks(navigation_tasks)
                entered_players.clear()
                leave_counts.clear()
                initial_cursor = cursor
                overlay_drawn = False
                print("Mission ended; waiting for the next mission.", flush=True)
                continue

            event = PlayerAircraftEvent.from_message(message)
            session_key = event.player_name or event.unit_id or "<unknown session>"
            action = "ENTER" if event.entered else "LEAVE"
            print(
                f"\n{action}: player={event.player_name or '-'} "
                f"unit={event.unit_id or '-'} group={event.group_id or '-'} "
                f"opsgroup={event.opsgroup_id or '-'} type={event.aircraft_type or '-'}",
                flush=True,
            )
            describe_active_sessions(bridge)

            if event.entered:
                await stop_navigation_tasks(navigation_tasks, session_key)
                entered_players.add(session_key)
                if session_key not in bridge.state.active_player_aircraft:
                    print("FAIL: enter event did not create the Python session", flush=True)
                    return 1
                print("PASS: Python session was created", flush=True)
                if DRAW_ROUTE_ON_ENTER or MONITOR_NAVIGATION:
                    route = await show_route(bridge, event, draw=DRAW_ROUTE_ON_ENTER)
                    overlay_drawn = DRAW_ROUTE_ON_ENTER
                    if MONITOR_NAVIGATION:
                        navigator = RouteNavigator(
                            route,
                            initial_target_index=INITIAL_TARGET_WAYPOINT,
                            capture_radius_m=WAYPOINT_CAPTURE_RADIUS_M,
                            max_sample_gap_s=NAVIGATION_MAX_SAMPLE_GAP_SECONDS,
                        )
                        navigation_tasks[session_key] = asyncio.create_task(
                            monitor_navigation(bridge, event, navigator),
                        )
                print("Waiting for player.aircraft.left ...", flush=True)
                continue

            await stop_navigation_tasks(navigation_tasks, session_key)
            if session_key not in entered_players:
                print("FAIL: leave event arrived without a matching enter event", flush=True)
                return 1
            if session_key in bridge.state.active_player_aircraft:
                print("FAIL: leave event did not remove the Python session", flush=True)
                return 1

            entered_players.remove(session_key)
            if overlay_drawn:
                await bridge.clear_debug_overlay(ROUTE_OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
                overlay_drawn = False
                print("F10: player route removed", flush=True)
            completed_cycles += 1
            leave_counts[session_key] = leave_counts.get(session_key, 0) + 1
            print(
                f"PASS: Python session was removed; cycle {completed_cycles}/{TEST_CYCLES} complete",
                flush=True,
            )
            # DCS can emit PlayerLeaveUnit twice within a few milliseconds. Give
            # the socket reader time to receive a possible duplicate and verify
            # that Lua forwarded only one normalized event for this session.
            await asyncio.sleep(0.25)
            session_filter = (
                {"player_name": event.player_name}
                if event.player_name
                else {"unit_id": event.unit_id}
            )
            history = await bridge.server.query_events(
                "player.aircraft.left",
                filters=session_filter,
                after_id=initial_cursor,
            )
            received_leave_count = len(history["events"])
            if received_leave_count != leave_counts[session_key]:
                print(
                    "FAIL: Python received duplicate player.aircraft.left events "
                    f"({received_leave_count} received, {leave_counts[session_key]} expected)",
                    flush=True,
                )
                return 1
            print("PASS: no duplicate leave event reached Python", flush=True)
            if completed_cycles < TEST_CYCLES:
                print("Waiting for player.aircraft.entered ...", flush=True)
    finally:
        await stop_navigation_tasks(navigation_tasks)
        if overlay_drawn and not bridge.state.mission_ended:
            try:
                await bridge.clear_debug_overlay(ROUTE_OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
            except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
                logging.warning("Could not remove route overlay: %s", exc)
        bridge.close()

    print("\nPLAYER AIRCRAFT LIFECYCLE TEST PASSED", flush=True)
    return 0


def main() -> int:
    """Run the monitor and provide concise errors for manual testing."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
