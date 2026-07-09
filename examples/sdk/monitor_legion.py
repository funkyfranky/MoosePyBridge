from __future__ import annotations

import asyncio

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import MooseBridgeClient
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client
from moosebridge.diagnostics import format_legion_status


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
INTERVAL_SECONDS = 10.0

LEGION_ID = "LEGION:Brigade Laage"  # oder None fuer alle LEGIONs


def print_legion_status(bridge: MooseBridgeClient, legion_id: str | None = None) -> None:
    print()
    print(format_legion_status(bridge, legion_id))


async def main() -> None:
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)

    status = await control.status()
    if not status.get("connected"):
        print("DCS ist nicht mit dem laufenden MoosePyBridge-Daemon verbunden.")
        return

    bridge = sdk_from_control_client(control, timeout=10.0)

    while True:
        await bridge.refresh_legion_state()

        print_legion_status(bridge, LEGION_ID)

        await asyncio.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
