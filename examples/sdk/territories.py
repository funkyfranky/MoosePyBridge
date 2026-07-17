"""Read passive MOOSE TERRITORY objects through the Python SDK.

The MoosePyBridge daemon/control server and its DCS connection are assumed to
be running. Change the constants below while experimenting with the SDK.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import MooseBridgeClient, Territory
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0

TERRITORY_ID = "TERRITORY:Territory North"
CHANGE_OWNER = False
NEW_COALITION = "red"


def print_territory(territory: Territory) -> None:
    """Print the stable strategic attributes of one territory."""

    print(
        f"{territory.object_id}: coalition={territory.coalition} "
        f"shape={territory.shape} vertices={len(territory.vertices)} "
        f"zone={territory.zone_name}"
    )


async def inspect_territories(bridge: MooseBridgeClient) -> None:
    """Refresh, query, and optionally update passive territories."""

    await bridge.refresh_territory_state()

    print("Territories:")
    for territory in bridge.territories():
        print_territory(territory)

    selected = bridge.territory(TERRITORY_ID)
    if selected is None:
        print(f"\n{TERRITORY_ID} is not present in the current snapshot.")
        return

    print("\nSelected:")
    print_territory(selected)

    if CHANGE_OWNER:
        await bridge.set_territory_coalition(TERRITORY_ID, NEW_COALITION)
        updated = bridge.territory(TERRITORY_ID)
        if updated is not None:
            print("\nAfter coalition change:")
            print_territory(updated)


async def run() -> int:
    """Connect to the existing daemon and inspect its territory mirror."""

    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    await inspect_territories(bridge)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
