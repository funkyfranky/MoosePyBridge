"""Compare OSM land/water samples with native DCS terrain classifications.

The daemon/control server and DCS mission are assumed to be running. Edit the
constants below; this example intentionally has no command-line parameters.
The mission must contain the current MooseBridge.lua.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import (
    DebugMarkup,
    MooseBridgeClient,
    TheaterTopography,
    build_surface_verification_points,
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
SHORELINE_CLEARANCE_M = 50.0
MAX_SAMPLE_POINTS = 180
POINT_RADIUS_M = 65.0
OVERLAY_ID = "surface-alignment-verification"

LAND_MATCH_COLOR = (0.0, 0.85, 0.15, 1.0)
WATER_MATCH_COLOR = (0.0, 0.65, 1.0, 1.0)
MISMATCH_COLOR = (1.0, 0.05, 0.0, 1.0)


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
    expected = build_surface_verification_points(
        topography,
        latitude=center.latitude,
        longitude=center.longitude,
        radius_m=RADIUS_KM * 1_000,
        spacing_m=SAMPLE_SPACING_M,
        boundary_clearance_m=SHORELINE_CLEARANCE_M,
        max_points=MAX_SAMPLE_POINTS,
    )
    if not expected:
        print("No OSM land/water samples were generated in the test area.")
        return 6

    print(f"Comparing {len(expected)} OSM samples with native DCS surfaces ...", flush=True)
    actual = await bridge.surface_types(
        [sample.point for sample in expected],
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    comparisons = list(zip(expected, actual, strict=True))
    matches = [sample.expected_surface == ("water" if surface.is_water else "land") for sample, surface in comparisons]
    expected_counts = Counter(sample.expected_surface for sample, _ in comparisons)
    dcs_counts = Counter(surface.surface_name for _, surface in comparisons)
    land_matches = sum(
        sample.expected_surface == "land" and not surface.is_water for sample, surface in comparisons
    )
    water_matches = sum(
        sample.expected_surface == "water" and surface.is_water for sample, surface in comparisons
    )
    osm_land_dcs_water = sum(
        sample.expected_surface == "land" and surface.is_water for sample, surface in comparisons
    )
    osm_water_dcs_land = sum(
        sample.expected_surface == "water" and not surface.is_water for sample, surface in comparisons
    )

    print("\nSurface alignment", flush=True)
    print("=" * 80, flush=True)
    print(f"Area                 : {CENTER_OBJECT_ID}, radius {RADIUS_KM:.1f} km", flush=True)
    print(f"Samples              : {len(comparisons)} (land grid {SAMPLE_SPACING_M:.0f} m, water oversampled)", flush=True)
    print(f"Shoreline clearance  : {SHORELINE_CLEARANCE_M:.0f} m", flush=True)
    print(f"Agreement            : {sum(matches):3d}/{len(matches)} ({sum(matches) / len(matches):6.1%})", flush=True)
    print(f"OSM land / DCS land  : {land_matches:3d}/{expected_counts['land']}", flush=True)
    print(f"OSM water / DCS water: {water_matches:3d}/{expected_counts['water']}", flush=True)
    print(f"OSM land / DCS water : {osm_land_dcs_water:3d}", flush=True)
    print(f"OSM water / DCS land : {osm_water_dcs_land:3d}", flush=True)
    print("DCS surface types    : " + ", ".join(f"{name}={count}" for name, count in sorted(dcs_counts.items())), flush=True)

    features: list[DebugMarkup] = []
    for sample, surface in comparisons:
        matches_expected = sample.expected_surface == ("water" if surface.is_water else "land")
        if not matches_expected:
            color = MISMATCH_COLOR
        elif sample.expected_surface == "water":
            color = WATER_MATCH_COLOR
        else:
            color = LAND_MATCH_COLOR
        features.append(
            DebugMarkup(
                "point",
                (sample.point,),
                color=color,
                fill_color=(*color[:3], 0.4),
                radius_m=POINT_RADIUS_M,
            )
        )

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
        print("Green=land agreement, cyan=water agreement, red=OSM/DCS mismatch.", flush=True)
        await asyncio.to_thread(input, "Inspect the DCS F10 map, then press Enter to remove the overlay ... ")
    finally:
        if drawn:
            ack = await bridge.clear_debug_overlay(OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
            print(f"Overlay removed: {ack.get('result') or ack}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
