"""Periodically inspect the global DCS/MOOSE truth picture.

The MoosePyBridge daemon/control server and its DCS connection are assumed to
be running. This example intentionally has no command-line parameters; change
the constants below while experimenting with the SDK.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import MooseBridgeCommandError, format_global_picture_status
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT

INTERVAL_SECONDS = 5.0
COMMAND_TIMEOUT_SECONDS = 15.0
ISSUE_LIMIT = 25
RUN_ONCE = False
DEBUG = False

WRITE_GEOJSON = True
GEOJSON_PATH = REPO_ROOT / "tmp" / "global_picture.geojson"


def write_geojson(path: Path, data: dict[str, object]) -> None:
    """Atomically replace the generated GeoJSON file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary_path.replace(path)


async def run() -> int:
    """Connect to the daemon and monitor the global picture."""

    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)

    while True:
        picture = await bridge.refresh_global_picture()
        print(format_global_picture_status(picture, issue_limit=ISSUE_LIMIT), flush=True)

        if WRITE_GEOJSON:
            write_geojson(GEOJSON_PATH, picture.to_geojson())
            print(f"GeoJSON written: {GEOJSON_PATH}", flush=True)

        if RUN_ONCE:
            return 0
        print()
        await asyncio.sleep(INTERVAL_SECONDS)


async def async_main() -> int:
    """Run the global-picture monitor with readable errors."""

    try:
        return await run()
    except MooseBridgeCommandError as exc:
        print(f"DCS rejected the global snapshot command: {exc}")
        print(f"ACK: {exc.ack}")
        return 4


def main() -> int:
    """Run the example entry point."""

    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
