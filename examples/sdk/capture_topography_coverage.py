"""Capture DCS mission zones that define offline topography detail coverage.

Create zones named `Topography All`, `Topography Low ...`, and
`Topography High ...` in the mission editor. Multiple zones per level are
allowed. The daemon and DCS mission are assumed to be running.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import TopographyDetailLevel, coverage_from_picture
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
THEATER_ID = "GermanyCW"
OUTPUT_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-coverage.geojson"


async def run() -> int:
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    picture = await bridge.refresh_global_picture()
    coverage = coverage_from_picture(picture.to_geojson(), theater_id=THEATER_ID)
    coverage.save(OUTPUT_PATH)

    print(f"Topography coverage written: {OUTPUT_PATH}")
    print(f"Bounds: south={coverage.bounds[0]:.5f} west={coverage.bounds[1]:.5f} north={coverage.bounds[2]:.5f} east={coverage.bounds[3]:.5f}")
    for level in TopographyDetailLevel:
        areas = [area for area in coverage.areas if area.level is level]
        print(f"  {level.value}: {len(areas)} zone(s)")
        for area in areas:
            print(f"    {area.object_id}")
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        print("Required zone names begin with: Topography All, Topography Low, or Topography High")
        return 4
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
