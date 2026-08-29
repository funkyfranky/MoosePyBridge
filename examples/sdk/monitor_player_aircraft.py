"""Live-test player aircraft sessions through the normal control API workflow."""

from __future__ import annotations

import asyncio
import logging

from example_support import open_example_session, run_example

from moosebridge import MooseBridgeClient, PlayerAircraftEvent
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
PLAYER_NAME: str | None = "funkyfranky"
TEST_CYCLES = 2
COMMAND_TIMEOUT_SECONDS = 10.0
EVENT_TIMEOUT_SECONDS = 3600.0


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

    print(
        f"Connected to MoosePyBridge control API at "
        f"{CONTROL_HOST}:{CONTROL_PORT}",
        flush=True,
    )
    if PLAYER_NAME:
        print(f"Player filter: {PLAYER_NAME}", flush=True)
    print("Start the DCS mission, enter the aircraft slot, then leave it again.", flush=True)
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
                entered_players.clear()
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
                entered_players.add(session_key)
                if session_key not in bridge.state.active_player_aircraft:
                    print("FAIL: enter event did not create the Python session", flush=True)
                    return 1
                print("PASS: Python session was created", flush=True)
                print("Waiting for player.aircraft.left ...", flush=True)
                continue

            if session_key not in entered_players:
                print("FAIL: leave event arrived without a matching enter event", flush=True)
                return 1
            if session_key in bridge.state.active_player_aircraft:
                print("FAIL: leave event did not remove the Python session", flush=True)
                return 1

            entered_players.remove(session_key)
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
        bridge.close()

    print("\nPLAYER AIRCRAFT LIFECYCLE TEST PASSED", flush=True)
    return 0


def main() -> int:
    """Run the monitor and provide concise errors for manual testing."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
