"""Draw a bounded OSM topography sample on the native DCS F10 map.

The daemon/control server and DCS mission are assumed to be running. This
example intentionally has no command-line parameters; edit the constants below.
Load the updated MooseBridge.lua into the mission before running it.
"""

from __future__ import annotations

import asyncio
from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    DebugMarkup,
    DebugMarkupPoint,
    MooseBridgeClient,
    TheaterTopography,
    TopographyLayer,
    build_topography_debug_overlay,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH
_, THEATER_PATHS = load_example_theater(THEATER_PROFILE)
TOPOGRAPHY_PATH = THEATER_PATHS.path("topography_preview")
CENTER_OBJECT_ID = "AIRBASE:Laage"
RADIUS_KM = 10.0
# Test one layer at a time. For water, small ponds and fragments are excluded
# so major lakes and waterways remain visible within the markup budget.
LAYERS = (TopographyLayer.WATER,)
MAX_GEOMETRY_PARTS = 60
MAX_DCS_MARKUPS = 300
SIMPLIFY_METERS = 100.0
MINIMUM_WATER_AREA_M2 = 20_000.0
OVERLAY_ID = "topography-verification"
COALITION = "all"


async def run() -> int:
    if not TOPOGRAPHY_PATH.is_file():
        print(f"Topography cache not found: {TOPOGRAPHY_PATH}")
        return 4

    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge: MooseBridgeClient = session.bridge
    center = await bridge.coords(CENTER_OBJECT_ID, format="ll", timeout=COMMAND_TIMEOUT_SECONDS)
    if center.latitude is None or center.longitude is None:
        print(f"DCS did not return WGS84 coordinates for {CENTER_OBJECT_ID}.")
        return 5

    print(f"Loading topography: {TOPOGRAPHY_PATH}", flush=True)
    topography = TheaterTopography.load(TOPOGRAPHY_PATH)
    features = build_topography_debug_overlay(
        topography,
        latitude=center.latitude,
        longitude=center.longitude,
        radius_m=RADIUS_KM * 1_000,
        layers=LAYERS,
        max_features=MAX_GEOMETRY_PARTS,
        max_marks=MAX_DCS_MARKUPS,
        simplify_meters=SIMPLIFY_METERS,
        minimum_polygon_area_m2=MINIMUM_WATER_AREA_M2,
    )
    center_marker = DebugMarkup(
        "point",
        (DebugMarkupPoint(center.latitude, center.longitude),),
        color=(1.0, 0.0, 1.0, 1.0),
        fill_color=(1.0, 0.0, 1.0, 0.03),
        radius_m=500.0,
    )
    features = (center_marker, *features)
    if not features:
        print("No selected topography features intersect the test area.")
        return 6

    mark_count = sum(feature.mark_count for feature in features)
    print(
        f"Drawing {len(features)} geometry part(s), {mark_count} native markups, "
        f"centered on {CENTER_OBJECT_ID} within {RADIUS_KM:.1f} km ...",
        flush=True,
    )
    print(f"DCS center: x={center.x:.1f} y={center.y:.1f} z={center.z:.1f}", flush=True)
    drawn = False
    try:
        ack = await bridge.draw_debug_overlay(
            OVERLAY_ID,
            features,
            coalition=COALITION,
            replace=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        drawn = True
        print(ack.get("result") or ack, flush=True)
        await asyncio.to_thread(input, "Inspect the DCS F10 map, then press Enter to remove the overlay ... ")
    finally:
        if drawn:
            clear_ack = await bridge.clear_debug_overlay(OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
            print(f"Overlay removed: {clear_ack.get('result') or clear_ack}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
