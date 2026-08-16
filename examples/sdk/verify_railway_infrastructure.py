"""Verify one normalized railway location against nearby DCS scenery.

The MoosePyBridge daemon and a DCS mission using the current bridge Lua files
must already be running. Edit the constants below; no command-line arguments
are required.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import (  # noqa: E402
    DebugMarkup,
    DebugMarkupPoint,
    MooseBridgeClient,
    RailwayLocation,
    RailwayImportanceTier,
    RailwayLocationKind,
    ScenerySurvey,
    StrategicVerificationRegistry,
    TheaterRailwayInfrastructure,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient  # noqa: E402
from moosebridge.control_sdk import sdk_from_control_client  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
RAILWAY_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-railway-infrastructure.geojson"
VERIFICATIONS_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-strategic-verifications.json"

# Select STATION, FREIGHT_TERMINAL, RAIL_YARD, DEPOT, JUNCTION, or BRIDGE.
# Set an exact location name or object ID, or leave both None to select the
# nearest representative location of this kind to REFERENCE_OBJECT_ID.
LOCATION_KIND = RailwayLocationKind.BRIDGE
LOCATION_NAME: str | None = None
LOCATION_ID: str | None = "RAILWAY_BRIDGE:GermanyCW:26e7bb286c8a6793"
REFERENCE_OBJECT_ID = "AIRBASE:Laage"
# Automatic selection first considers this tier and higher. If none exist,
# it falls back to the nearest strategic candidate and finally any candidate.
MINIMUM_IMPORTANCE_TIER = RailwayImportanceTier.CRITICAL

SURVEY_RADIUS_M = 1_000.0
LOCATOR_RADIUS_M = 5_000.0
MAX_SCENERY_OBJECTS = 300
MAX_PRINTED_OBJECTS = 50
DRAW_F10_OVERLAY = True
MAX_DRAWN_OBJECTS = 75
OVERLAY_ID = "railway-infrastructure-verification"


def distance_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(value)))


async def select_location(
    bridge: MooseBridgeClient,
    artifact: TheaterRailwayInfrastructure,
) -> tuple[RailwayLocation, float | None]:
    candidates = tuple(location for location in artifact.locations if location.kind is LOCATION_KIND)
    if not candidates:
        raise ValueError(f"No {LOCATION_KIND.value} locations are present in {RAILWAY_PATH.name}")
    if LOCATION_ID is not None:
        matches = tuple(location for location in candidates if location.location_id == LOCATION_ID)
        if not matches:
            raise ValueError(f"Railway location ID not found for {LOCATION_KIND.value}: {LOCATION_ID}")
        return matches[0], None
    if LOCATION_NAME is not None:
        matches = tuple(
            location for location in candidates
            if (location.name or "").casefold() == LOCATION_NAME.casefold()
        )
        if not matches:
            raise ValueError(f"Railway location name not found for {LOCATION_KIND.value}: {LOCATION_NAME}")
        if len(matches) > 1:
            raise ValueError(f"Railway location name is not unique: {LOCATION_NAME} ({len(matches)} matches)")
        return matches[0], None
    reference = await bridge.coords(REFERENCE_OBJECT_ID, format="ll", timeout=COMMAND_TIMEOUT_SECONDS)
    if reference.latitude is None or reference.longitude is None:
        raise ValueError(f"DCS returned no WGS84 coordinate for {REFERENCE_OBJECT_ID}")
    tier_rank = {
        RailwayImportanceTier.LOCAL: 0,
        RailwayImportanceTier.MEDIUM: 1,
        RailwayImportanceTier.HIGH: 2,
        RailwayImportanceTier.CRITICAL: 3,
    }
    preferred = tuple(
        location for location in candidates
        if tier_rank[location.importance_tier] >= tier_rank[MINIMUM_IMPORTANCE_TIER]
    )
    selection_pool = preferred or tuple(location for location in candidates if location.strategic_candidate) or candidates
    location = min(
        selection_pool,
        key=lambda item: distance_m(reference.latitude, reference.longitude, item.latitude, item.longitude),
    )
    distance = distance_m(reference.latitude, reference.longitude, location.latitude, location.longitude)
    return location, distance


def format_location(location: RailwayLocation, reference_distance_m: float | None) -> None:
    print("Railway infrastructure location")
    print("=" * 96)
    print(f"Object ID       : {location.location_id}")
    print(f"Name            : {location.name or 'unnamed'}")
    print(f"Kind            : {location.kind.value.replace('_', ' ')}")
    print(f"Importance      : {location.importance_score:.1f} ({location.importance_tier.value})")
    print(f"Strategic       : {location.strategic_candidate}")
    print(f"Members         : {location.member_count}")
    print(f"Track length    : {location.track_length_m / 1_000:.2f} km")
    print(f"Branches        : {location.branch_count or '-'}")
    print(f"Position        : {location.latitude:.5f}, {location.longitude:.5f}")
    if reference_distance_m is not None:
        print(f"Reference       : {REFERENCE_OBJECT_ID}, {reference_distance_m / 1_000:.1f} km")
    print(f"Source          : {location.source}")
    print(f"Source objects  : {len(location.source_ids)}")
    if "network_analysis_complete" in location.properties:
        print("Network analysis")
        print(f"  Complete      : {location.properties.get('network_analysis_complete')}")
        print(f"  Disconnected  : {location.properties.get('network_disconnected_if_lost')}")
        print(f"  Alternative   : {location.properties.get('network_alternative_route_found')}")
        added = location.properties.get("network_detour_added_m")
        ratio = location.properties.get("network_detour_ratio")
        print(f"  Added distance: {float(added) / 1_000:.1f} km" if added is not None else "  Added distance: -")
        print(f"  Detour ratio  : {float(ratio):.2f}" if ratio is not None else "  Detour ratio  : -")
        print(f"  Impact score  : {float(location.properties.get('network_criticality_score') or 0):.1f}")


def format_strategic_verification(location: RailwayLocation) -> None:
    verification = StrategicVerificationRegistry.load(VERIFICATIONS_PATH).get(location.location_id)
    print("\nStrategic DCS verification")
    print("=" * 96)
    print(f"Registry        : {VERIFICATIONS_PATH}")
    if verification is None:
        print("Status          : not mapped")
        print("Next step       : Select concrete objects below and add them in the web-map DCS verification panel.")
        return
    print(f"Status          : {verification.state.value}")
    print(f"Admitted        : {verification.admitted}")
    completeness = "complete" if verification.observation_complete else "partial"
    print(f"Observed objects: {len(verification.observed_objects)} ({completeness})")
    print(f"Target components: {len(verification.target_components)}")
    for component in verification.target_components:
        print(f"  {component.object_id} | {component.role} | {component.weight:g}")
    if verification.notes:
        print(f"Notes           : {verification.notes}")


def format_survey(location: RailwayLocation, survey: ScenerySurvey) -> None:
    objects = sorted(
        survey.objects,
        key=lambda item: distance_m(location.latitude, location.longitude, item.latitude, item.longitude),
    )
    print("\nDCS scenery survey")
    print("=" * 96)
    print(f"Radius          : {survey.radius_m:.0f} m")
    print(f"Objects         : {len(objects)}{' (truncated)' if survey.truncated else ''}")
    if not objects:
        print("No addressable DCS scenery objects were found in the survey area.")
        return
    print(f"\n{'Distance':>9}  {'Object ID':<24} {'Type':<27} Display name")
    print(f"{'-' * 9}  {'-' * 24} {'-' * 27} {'-' * 24}")
    for item in objects[:MAX_PRINTED_OBJECTS]:
        distance = distance_m(location.latitude, location.longitude, item.latitude, item.longitude)
        print(
            f"{distance:8.0f}m  {item.object_id[:24]:<24} "
            f"{(item.type_name or '-')[:27]:<27} {item.display_name or '-'}"
        )
    print("\nCopy only visually confirmed object IDs into the web-map DCS verification panel.")
    print("Component format: SCENERY:<id> | railway component | 1.0")


def location_color(kind: RailwayLocationKind) -> tuple[float, float, float, float]:
    return {
        RailwayLocationKind.STATION: (0.31, 0.33, 0.32, 1.0),
        RailwayLocationKind.FREIGHT_TERMINAL: (0.46, 0.34, 0.55, 1.0),
        RailwayLocationKind.RAIL_YARD: (0.48, 0.39, 0.20, 1.0),
        RailwayLocationKind.DEPOT: (0.42, 0.36, 0.28, 1.0),
        RailwayLocationKind.JUNCTION: (0.09, 0.44, 0.47, 1.0),
        RailwayLocationKind.BRIDGE: (0.65, 0.42, 0.15, 1.0),
    }[kind]


async def run() -> int:
    if not RAILWAY_PATH.is_file():
        print(f"Railway-infrastructure artifact not found: {RAILWAY_PATH}")
        print("Run: python tools/build_railway_infrastructure.py")
        return 2
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    try:
        status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    except OSError as exc:
        print(f"MoosePyBridge daemon is not reachable at {CONTROL_HOST}:{CONTROL_PORT}: {exc}")
        return 3
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 4
    bridge: MooseBridgeClient = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    location, reference_distance = await select_location(
        bridge,
        TheaterRailwayInfrastructure.load(RAILWAY_PATH),
    )
    format_location(location, reference_distance)
    format_strategic_verification(location)
    survey = await bridge.survey_scenery(
        location.latitude,
        location.longitude,
        radius_m=SURVEY_RADIUS_M,
        max_results=MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    format_survey(location, survey)
    if not DRAW_F10_OVERLAY:
        return 0

    color = location_color(location.kind)
    marks = [
        DebugMarkup(
            "point",
            (DebugMarkupPoint(location.latitude, location.longitude),),
            color=(1.0, 0.0, 0.85, 1.0),
            fill_color=(1.0, 0.0, 0.85, 0.08),
            radius_m=LOCATOR_RADIUS_M,
        ),
        DebugMarkup(
            "point",
            (DebugMarkupPoint(location.latitude, location.longitude),),
            color=color,
            fill_color=(*color[:3], 0.12),
            radius_m=SURVEY_RADIUS_M,
        ),
    ]
    marks.extend(
        DebugMarkup(
            "point",
            (DebugMarkupPoint(item.latitude, item.longitude),),
            color=(0.1, 0.8, 0.9, 1.0),
            fill_color=(0.1, 0.8, 0.9, 0.25),
            radius_m=20,
        )
        for item in survey.objects[:MAX_DRAWN_OBJECTS]
    )
    drawn = False
    try:
        await bridge.draw_debug_overlay(OVERLAY_ID, marks, replace=True, timeout=COMMAND_TIMEOUT_SECONDS)
        drawn = True
        await asyncio.to_thread(
            input,
            "Inspect the 5 km magenta locator, 1 km survey area, and cyan scenery objects in DCS F10, then press Enter ... ",
        )
    finally:
        if drawn:
            await bridge.clear_debug_overlay(OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
