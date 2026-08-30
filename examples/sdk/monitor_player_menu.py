"""Enable a MOOSE group radio test menu and print its Python-console clicks.

Run the normal daemon and DCS mission first, then Run Python File in VS Code.
Already occupied groups are supported. Stop with Ctrl+C; no flight is needed.
Only one menu test owns the mission at a time; a new run replaces the old one.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from example_support import open_example_session, run_example

from moosebridge import BridgeCommand, MooseBridgeClient
from moosebridge.control import DEFAULT_CONTROL_PORT
from moosebridge.sdk import require_ok


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
EVENT_TIMEOUT_SECONDS = 3600.0


async def configure_menu(bridge: MooseBridgeClient, owner_id: str, *, enabled: bool) -> dict:
    """Enable the test for occupied groups, or remove only this run's menus."""

    return require_ok(await bridge.server.send_command(
        BridgeCommand(
            action="player.menu.test.configure",
            params={"enabled": enabled, "owner_id": owner_id},
        ),
        timeout=COMMAND_TIMEOUT_SECONDS,
    ))


async def run() -> int:
    """Receive clicks through the normal daemon, not a separate test server."""

    session = await open_example_session(
        CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS,
        client_id="player-menu-test", display_name="Player Menu Test",
    )
    bridge = session.bridge
    owner_id = str(uuid4())
    attempted_enable = False
    mission_ended = False
    clicks = 0
    try:
        cursor = await bridge.server.event_cursor()
        attempted_enable = True  # Cleanup even if a successful enable loses its ACK.
        await configure_menu(bridge, owner_id, enabled=True)
        print(f"Connected to MoosePyBridge control API at {CONTROL_HOST}:{CONTROL_PORT}", flush=True)
        print("Menu enabled for occupied player groups (also on later slot entry).", flush=True)
        print("Radio menu > F10 Other > MoosePyBridge Test:", flush=True)
        print("  Nachricht anzeigen: MOOSE MESSAGE to your group.", flush=True)
        print("  Python-Konsole: print one received click below.", flush=True)
        print("Group-scoped: DCS does not identify the clicking player. Ctrl+C to stop.", flush=True)
        while True:
            try:
                message = await bridge.server.wait_for_event(
                    "player.menu.selected",
                    filters={"owner_id": owner_id, "action": "python_console"},
                    after_id=cursor,
                    timeout=EVENT_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                continue
            cursor = str(message.get("id") or "") or cursor
            if message.get("event") == "mission.ended":
                mission_ended = True
                print("Mission ended; menu test stopped. Run again for the next mission.", flush=True)
                return 0
            payload = message.get("payload") or {}
            # Do not attribute a shared group-menu click to any individual pilot.
            occupants = ", ".join(
                str(item.get("player_name") or item.get("unit_id") or "unknown")
                for item in payload.get("group_sessions", [])
            ) or "unknown"
            clicks += 1
            print(
                f"MENU CLICK {clicks}: group={payload.get('group_id') or '-'} "
                f"action={payload.get('action')} | group occupants: {occupants}",
                flush=True,
            )
    finally:
        if attempted_enable and not mission_ended and not bridge.state.mission_ended:
            try:
                await configure_menu(bridge, owner_id, enabled=False)
            except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
                logging.warning("Could not remove test menus: %s", exc)
        bridge.close()


def main() -> int:
    """Use shared connection diagnostics and Ctrl+C handling."""

    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
