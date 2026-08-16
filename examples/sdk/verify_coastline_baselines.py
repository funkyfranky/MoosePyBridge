"""Validate competing coastline baselines against native DCS terrain data.

The daemon/control server and DCS mission are assumed to be running. This
example intentionally has no command-line parameters. It reads the offline
Natural Earth/OSM comparison artifact and asks DCS to classify every point at
which the two baselines disagree.
"""

from __future__ import annotations

import asyncio
from collections import Counter
import json
from typing import Any

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import DEFAULT_THEATER_PROFILE_PATH, DebugMarkup, DebugMarkupPoint, MooseBridgeClient
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH
_, THEATER_PATHS = load_example_theater(THEATER_PROFILE)
COMPARISON_PATH = THEATER_PATHS.path("surface_comparison")
OVERLAY_ID = "coastline-baseline-verification"
POINT_RADIUS_M = 1_500.0

OSM_MATCH_COLOR = (0.0, 0.85, 0.15, 1.0)
REFERENCE_MATCH_COLOR = (1.0, 0.65, 0.0, 1.0)


def load_disagreements(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("comparison artifact must be a GeoJSON FeatureCollection")

    disagreements: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}
        coordinates = geometry.get("coordinates")
        if (
            geometry.get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
            or properties.get("reference") not in {"land", "water"}
            or properties.get("candidate") not in {"land", "water"}
        ):
            raise ValueError("comparison artifact contains an invalid disagreement feature")
        disagreements.append(feature)
    return disagreements


async def run() -> int:
    if not COMPARISON_PATH.is_file():
        print(f"Comparison artifact not found: {COMPARISON_PATH}")
        print("Run tools/compare_surface_regions.py first.")
        return 4

    disagreements = load_disagreements(COMPARISON_PATH)
    if not disagreements:
        print("The comparison artifact contains no coastline disagreements.")
        return 0

    points = [
        DebugMarkupPoint(
            latitude=float(feature["geometry"]["coordinates"][1]),
            longitude=float(feature["geometry"]["coordinates"][0]),
        )
        for feature in disagreements
    ]
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge: MooseBridgeClient = session.bridge

    print(f"Loading disagreements: {COMPARISON_PATH}", flush=True)
    print(f"Comparing {len(points)} points with native DCS surfaces ...", flush=True)
    surfaces = await bridge.surface_types(points, timeout=COMMAND_TIMEOUT_SECONDS)

    verdicts: Counter[str] = Counter()
    dcs_types: Counter[str] = Counter()
    markups: list[DebugMarkup] = []

    print("\nCoastline baseline validation")
    print("=" * 100)
    print(" #   Latitude   Longitude  Reference  OSM        DCS             Result")
    print("---  ---------  ---------  ---------  ---------  --------------  ----------------")
    for index, (feature, point, surface) in enumerate(
        zip(disagreements, points, surfaces, strict=True),
        start=1,
    ):
        properties = feature["properties"]
        reference = str(properties["reference"])
        candidate = str(properties["candidate"])
        dcs_class = "water" if surface.is_water else "land"
        dcs_types[surface.surface_name] += 1

        if candidate == dcs_class:
            verdict = "osm_matches"
            result = "OSM matches DCS"
            color = OSM_MATCH_COLOR
        elif reference == dcs_class:
            verdict = "reference_matches"
            result = "reference matches DCS"
            color = REFERENCE_MATCH_COLOR
        else:
            # The two source classes are complementary, so this should only be
            # reachable if DCS introduces an unsupported coarse classification.
            verdict = "unresolved"
            result = "unresolved"
            color = (1.0, 0.0, 0.0, 1.0)
        verdicts[verdict] += 1

        print(
            f"{index:2d}  {point.latitude:9.5f}  {point.longitude:9.5f}  "
            f"{reference:9s}  {candidate:9s}  {surface.surface_name:14s}  {result}"
        )
        markups.append(
            DebugMarkup(
                "point",
                (point,),
                color=color,
                fill_color=(*color[:3], 0.45),
                radius_m=POINT_RADIUS_M,
            )
        )

    osm_matches = verdicts["osm_matches"]
    reference_matches = verdicts["reference_matches"]
    print("\nResult")
    print("=" * 100)
    print(f"OSMCoastline matches DCS : {osm_matches:2d}/{len(points)}")
    print(f"Current reference matches: {reference_matches:2d}/{len(points)}")
    print(f"Unresolved               : {verdicts['unresolved']:2d}/{len(points)}")
    print("DCS surface types        : " + ", ".join(
        f"{name}={count}" for name, count in sorted(dcs_types.items())
    ))
    if osm_matches > reference_matches:
        print("Recommendation            : Prefer the OSMCoastline baseline for this comparison area.")
    elif reference_matches > osm_matches:
        print("Recommendation            : Keep the current reference baseline for this comparison area.")
    else:
        print("Recommendation            : No clear winner; expand the comparison area or resolution.")

    drawn = False
    try:
        ack = await bridge.draw_debug_overlay(
            OVERLAY_ID,
            markups,
            replace=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        drawn = True
        print(f"\nDCS overlay: {ack.get('result') or ack}")
        print("Green=OSMCoastline matches DCS, orange=current reference matches DCS.")
        await asyncio.to_thread(input, "Inspect the DCS F10 map, then press Enter to remove the overlay ... ")
    finally:
        if drawn:
            ack = await bridge.clear_debug_overlay(
                OVERLAY_ID,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
            print(f"Overlay removed: {ack.get('result') or ack}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
