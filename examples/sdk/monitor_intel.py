"""Periodically print MOOSE INTEL contacts and clusters.

Run against an already running MoosePyBridge daemon/control server. This script
has no command-line parameters on purpose; edit the constants below while
experimenting with the SDK.

    PYTHONPATH=python python examples/sdk/monitor_intel.py
"""

from __future__ import annotations

import asyncio
import json

from example_support import REPO_ROOT, open_example_session, run_example

from moosebridge import MooseBridgeClient, format_intel_status
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT

# Set this to a concrete id such as "INTEL:BlueIntel" to focus one INTEL object.
# Leave it as None to list all INTEL objects known to the bridge.
INTEL_ID: str | None = None
TACTICAL_COALITION = "blue"

INTERVAL_SECONDS = 5.0
COMMAND_TIMEOUT_SECONDS = 10.0
CONTACT_LIMIT = 20
CLUSTER_LIMIT = 10
RUN_ONCE = False
DEBUG = False

# Optional: write a tactical GeoJSON file whenever INTEL_ID is set.
WRITE_GEOJSON = True
GEOJSON_PATH = REPO_ROOT / "tmp" / "tactical_intel.geojson"


async def print_intel_loop(bridge: MooseBridgeClient) -> None:
    """Refresh INTEL snapshots and print a readable status report."""

    while True:
        await bridge.refresh_intel_state()
        print(
            format_intel_status(
                bridge,
                INTEL_ID,
                contact_limit=CONTACT_LIMIT,
                cluster_limit=CLUSTER_LIMIT,
            ),
            flush=True,
        )

        if INTEL_ID and WRITE_GEOJSON:
            picture = bridge.build_tactical_picture(TACTICAL_COALITION, INTEL_ID)
            GEOJSON_PATH.parent.mkdir(parents=True, exist_ok=True)
            GEOJSON_PATH.write_text(json.dumps(picture.to_geojson(), indent=2), encoding="utf-8")
            print(f"\nGeoJSON written: {GEOJSON_PATH}", flush=True)

        if RUN_ONCE:
            return

        print()
        await asyncio.sleep(INTERVAL_SECONDS)


async def run() -> int:
    """Use an already running daemon/control server and monitor INTEL."""

    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    await print_intel_loop(session.bridge)
    return 0


def main() -> int:
    """Run the script entry point."""

    return run_example(run, debug=DEBUG)


if __name__ == "__main__":
    raise SystemExit(main())
