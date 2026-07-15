"""Periodically print MOOSE INTEL contacts and clusters.

Run against an already running MoosePyBridge daemon/control server. This script
has no command-line parameters on purpose; edit the constants below while
experimenting with the SDK.

    PYTHONPATH=python python examples/sdk/monitor_intel.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import MooseBridgeClient, MooseBridgeCommandError, format_intel_status
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


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

    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    await print_intel_loop(bridge)
    return 0


async def async_main() -> int:
    """Run the INTEL monitor client."""

    try:
        return await run()
    except MooseBridgeCommandError as exc:
        print(f"DCS rejected INTEL snapshot command: {exc}")
        print(f"ACK: {exc.ack}")
        return 4
    except KeyboardInterrupt:
        print()
        return 130


def main() -> int:
    """Run the script entry point."""

    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
