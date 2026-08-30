"""Control route display and navigation hints from the DCS group radio menu.

Start the normal daemon and DCS mission, then Run Python File in VS Code.
Works before or after slot entry. Ctrl+C removes this run's menus and F10 lines.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from example_support import open_example_session, run_example

from moosebridge.control import DEFAULT_CONTROL_PORT
from moosebridge.navigation_menu import NavigationMenuController, configure_navigation_menu


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
EVENT_TIMEOUT_SECONDS = 5.0  # Also check mission status when no menu event arrives.
NAVIGATION_INTERVAL_SECONDS = 2.0
HINT_INTERVAL_SECONDS = 10.0
INITIAL_TARGET_WAYPOINT = 2
WAYPOINT_CAPTURE_RADIUS_M = 500.0
NAVIGATION_MAX_SAMPLE_GAP_SECONDS = 10.0


async def run() -> int:
    session = await open_example_session(
        CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS,
        client_id="navigation-menu", display_name="Navigation Menu",
    )
    bridge = session.bridge
    owner_id = str(uuid4())
    controller = None
    attempted_enable = False
    mission_ended = False
    try:
        controller = NavigationMenuController(
            bridge, owner_id, sample_interval=NAVIGATION_INTERVAL_SECONDS,
            hint_interval=HINT_INTERVAL_SECONDS, timeout=COMMAND_TIMEOUT_SECONDS,
            initial_target=INITIAL_TARGET_WAYPOINT, capture_radius_m=WAYPOINT_CAPTURE_RADIUS_M,
            max_sample_gap_s=NAVIGATION_MAX_SAMPLE_GAP_SECONDS,
        )
        cursor = await bridge.server.event_cursor()
        attempted_enable = True
        await configure_navigation_menu(bridge, owner_id, enabled=True, timeout=COMMAND_TIMEOUT_SECONDS)
        generation = bridge.state.mission_generation
        print(f"Connected to MoosePyBridge control API at {CONTROL_HOST}:{CONTROL_PORT}", flush=True)
        print("Radio menu > F10 Other > Navigation enabled for occupied and future player groups.", flush=True)
        print("Route anzeigen / Route ausblenden / Navigationsstatus / Hinweise ein / Hinweise aus", flush=True)
        print("Route and hints start OFF. Bearings are TRUE; cockpit waypoints are unchanged.", flush=True)
        print("Status requires one player aircraft per group and its FLIGHTGROUP. Ctrl+C to stop.", flush=True)
        while True:
            try:
                message = await bridge.server.wait_for_event(
                    "player.menu.*", filters={"owner_id": owner_id},
                    after_id=cursor, timeout=EVENT_TIMEOUT_SECONDS,
                )
            except (TimeoutError, RuntimeError) as exc:
                # The control API currently reports a server-side wait timeout
                # as RuntimeError; do not swallow unrelated command failures.
                if not isinstance(exc, TimeoutError) and not str(exc).startswith("control.event.wait timed out after "):
                    raise
                status = await session.control.status(timeout=COMMAND_TIMEOUT_SECONDS)
                if status.get("mission_ended") or status.get("mission_generation") != generation:
                    mission_ended = True
                    print("Mission ended/reset; navigation menu stopped.", flush=True)
                    return 0
                if not status.get("connected"):
                    raise ConnectionError("DCS disconnected; restart this script after reconnect.")
                continue
            cursor = str(message.get("id") or "") or cursor
            if message.get("event") == "mission.ended":
                mission_ended = True
                print("Mission ended; navigation menu stopped. Run again for the next mission.", flush=True)
                return 0
            await controller.handle(message)
            if bridge.state.mission_ended or bridge.state.mission_generation != generation:
                mission_ended = True
                print("Mission ended/reset; navigation menu stopped.", flush=True)
                return 0
    finally:
        if controller is not None:
            await controller.close()
        if attempted_enable and not mission_ended and not bridge.state.mission_ended:
            try:
                await configure_navigation_menu(bridge, owner_id, enabled=False, timeout=COMMAND_TIMEOUT_SECONDS)
            except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
                logging.warning("Could not remove navigation menus: %s", exc)
        bridge.close()


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
