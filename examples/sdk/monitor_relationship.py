"""Monitor the shared coalition relationship and strategic doctrines.

The MoosePyBridge daemon and map server are assumed to be running. The map
server ingests Kill events and tolerated border violations; this client reads
the resulting mission-scoped state and its recent incident history.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import format_coalition_doctrine, format_relationship
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
INTERVAL_SECONDS = 5.0
COMMAND_TIMEOUT_SECONDS = 15.0

INCIDENT_LIMIT = 20


async def run() -> int:
    control = MooseBridgeControlClient(
        CONTROL_HOST,
        CONTROL_PORT,
        client_id="relationship-monitor",
        display_name="Relationship Monitor",
    )
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    await control.get_state(("groups", "territories"), timeout=COMMAND_TIMEOUT_SECONDS)

    while True:
        restored = await bridge.refresh_diplomacy_state()
        if not restored:
            await bridge.persist_diplomacy_state()

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Coalition relationship")
        print("-" * 90)
        print(format_relationship(bridge.relationship, incident_limit=INCIDENT_LIMIT))
        print(format_coalition_doctrine("blue", bridge.coalition_doctrines.get("blue")))
        print(format_coalition_doctrine("red", bridge.coalition_doctrines.get("red")))
        print(flush=True)
        await asyncio.sleep(INTERVAL_SECONDS)


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
