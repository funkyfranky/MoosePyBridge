"""Compare sampled OSM roads with the nearest native DCS road positions.

The daemon/control server and DCS mission are assumed to be running. Edit the
constants below; this example intentionally has no command-line parameters.
The mission must contain the current MooseBridge.lua.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import statistics
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import (
    DebugMarkup,
    MooseBridgeClient,
    TheaterTopography,
    build_road_verification_points,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

TOPOGRAPHY_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-mv-simplified.geojson"
CENTER_OBJECT_ID = "AIRBASE:Laage"
RADIUS_KM = 10.0
SAMPLE_SPACING_M = 500.0
# Each displaced sample also needs one connector line; 100 samples therefore
# remain within the bridge limit of 200 geometry parts.
MAX_SAMPLE_POINTS = 100
CONFIRMED_DISTANCE_M = 50.0
DISPLACED_DISTANCE_M = 200.0
POINT_RADIUS_M = 55.0
OVERLAY_ID = "road-alignment-verification"

CONFIRMED_COLOR = (0.0, 0.9, 0.1, 1.0)
DISPLACED_COLOR = (1.0, 0.8, 0.0, 1.0)
MISSING_COLOR = (1.0, 0.05, 0.0, 1.0)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


async def run() -> int:
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3
    if not TOPOGRAPHY_PATH.is_file():
        print(f"Topography cache not found: {TOPOGRAPHY_PATH}")
        return 4

    bridge: MooseBridgeClient = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    center = await bridge.coords(CENTER_OBJECT_ID, format="ll", timeout=COMMAND_TIMEOUT_SECONDS)
    if center.latitude is None or center.longitude is None:
        print(f"DCS did not return WGS84 coordinates for {CENTER_OBJECT_ID}.")
        return 5

    print(f"Loading topography: {TOPOGRAPHY_PATH}", flush=True)
    topography = TheaterTopography.load(TOPOGRAPHY_PATH)
    points = build_road_verification_points(
        topography,
        latitude=center.latitude,
        longitude=center.longitude,
        radius_m=RADIUS_KM * 1_000,
        spacing_m=SAMPLE_SPACING_M,
        max_points=MAX_SAMPLE_POINTS,
    )
    if not points:
        print("No OSM road samples were found in the test area.")
        return 6

    print(f"Comparing {len(points)} OSM samples with native DCS roads ...", flush=True)
    matches = await bridge.closest_road_points(points, timeout=COMMAND_TIMEOUT_SECONDS)
    distances = [match.distance_m for match in matches]
    confirmed = sum(distance <= CONFIRMED_DISTANCE_M for distance in distances)
    displaced = sum(CONFIRMED_DISTANCE_M < distance <= DISPLACED_DISTANCE_M for distance in distances)
    missing = sum(distance > DISPLACED_DISTANCE_M for distance in distances)

    print("\nRoad alignment", flush=True)
    print("=" * 80, flush=True)
    print(f"Area             : {CENTER_OBJECT_ID}, radius {RADIUS_KM:.1f} km", flush=True)
    print(f"Samples          : {len(matches)} at about {SAMPLE_SPACING_M:.0f} m spacing", flush=True)
    print(f"Confirmed <= 50m: {confirmed:3d} ({confirmed / len(matches):6.1%})", flush=True)
    print(f"Displaced <=200m: {displaced:3d} ({displaced / len(matches):6.1%})", flush=True)
    print(f"No close match   : {missing:3d} ({missing / len(matches):6.1%})", flush=True)
    print(f"Median / p90 / max: {statistics.median(distances):.1f} / {_percentile(distances, 0.9):.1f} / {max(distances):.1f} m", flush=True)

    features: list[DebugMarkup] = []
    for match in matches:
        if match.distance_m <= CONFIRMED_DISTANCE_M:
            color = CONFIRMED_COLOR
        elif match.distance_m <= DISPLACED_DISTANCE_M:
            color = DISPLACED_COLOR
        else:
            color = MISSING_COLOR
        features.append(
            DebugMarkup(
                "point",
                (match.input_point,),
                color=color,
                fill_color=(*color[:3], 0.35),
                radius_m=POINT_RADIUS_M,
            )
        )
        if match.distance_m > CONFIRMED_DISTANCE_M:
            features.append(DebugMarkup("line", (match.input_point, match.road_point), color=color))

    drawn = False
    try:
        ack = await bridge.draw_debug_overlay(
            OVERLAY_ID,
            features,
            replace=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        drawn = True
        print(f"\nDCS overlay: {ack.get('result') or ack}", flush=True)
        print("Green=confirmed, yellow=displaced, red=no close DCS road match.", flush=True)
        await asyncio.to_thread(input, "Inspect the DCS F10 map, then press Enter to remove the overlay ... ")
    finally:
        if drawn:
            ack = await bridge.clear_debug_overlay(OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
            print(f"Overlay removed: {ack.get('result') or ack}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
