"""Read passive MOOSE TERRITORY objects through the Python SDK.

The MoosePyBridge daemon/control server and its DCS connection are assumed to
be running. Change the constants below while experimenting with the SDK.
"""

from __future__ import annotations

from example_support import open_example_session, run_example

from moosebridge import MooseBridgeClient, Territory
from moosebridge.control import DEFAULT_CONTROL_PORT


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

    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge
    await inspect_territories(bridge)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
