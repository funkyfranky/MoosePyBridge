from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import MooseBridgeClient, format_commander_status
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
INTERVAL_SECONDS = 10.0
COMMANDER_ID: str | None = None  # For example: "COMMANDER:Blue Command"


async def main() -> None:
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status()
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return

    bridge: MooseBridgeClient = sdk_from_control_client(control, timeout=10.0)
    while True:
        await bridge.refresh_legion_state()
        print()
        print(format_commander_status(bridge, COMMANDER_ID))
        await asyncio.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
