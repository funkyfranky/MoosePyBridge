"""Verify one normalized theater feature against fixed DCS scenery objects.

The MoosePyBridge daemon and a DCS mission using the current bridge Lua files
must already be running. Copy an object ID from the web map and edit OBJECT_ID.
The workflow never considers mission-defined units, groups, or static objects.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

from shapely.geometry import Point, shape

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (  # noqa: E402
    DEFAULT_THEATER_PROFILE_PATH,
    DebugMarkup,
    DebugMarkupPoint,
    MooseBridgeClient,
    ObservedDcsObject,
    ScenerySurvey,
    SceneryVerificationFeature,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
    TheaterDataPaths,
    TheaterDataProfile,
    assess_infrastructure_state,
    resolve_scenery_verification_feature,
)
from moosebridge.control import DEFAULT_CONTROL_PORT  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

# Copy the object ID from the web-map detail panel. Supported normalized source
# types are infrastructure sites, railway locations, settlements, road bridges,
# and transport junctions.
OBJECT_ID = "BRIDGE:Caucasus:4d482fb330eb"

# None searches the bundled theater profiles and selects the one containing
# OBJECT_ID. Set a profile path only to resolve a deliberately ambiguous ID.
THEATER_PROFILE: str | Path | None = None

# None automatically covers a bounded polygon footprint. Point features use the
# default radius. Set an explicit value for a deliberately different survey.
SURVEY_RADIUS_M: float | None = None
SAVE_OBSERVED_BASELINE = False
REPLACE_OBSERVED_BASELINE = False
DRAW_F10_OVERLAY = True

# Safety and display limits. DCS scenery.search accepts at most 5 km and 2,000
# results. A survey that reaches either limit remains explicitly partial.
DEFAULT_POINT_SURVEY_RADIUS_M = 1_000.0
MINIMUM_AREA_SURVEY_RADIUS_M = 500.0
SURVEY_MARGIN_M = 50.0
MAXIMUM_SURVEY_RADIUS_M = 5_000.0
MAX_SCENERY_OBJECTS = 2_000
MAX_PRINTED_OBJECTS = 50
MAX_DRAWN_OBJECTS = 75
MAX_FOOTPRINT_POINTS = 180
LOCATOR_RADIUS_M = 5_000.0
OVERLAY_ID = "scenery-representation-verification"


def distance_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(value)))


def select_feature() -> tuple[TheaterDataProfile, TheaterDataPaths, SceneryVerificationFeature]:
    profile_paths = (
        (Path(THEATER_PROFILE),)
        if THEATER_PROFILE is not None
        else tuple(sorted(DEFAULT_THEATER_PROFILE_PATH.parent.glob("*_topography.json")))
    )
    if not profile_paths:
        raise ValueError("No theater profiles are available for automatic object lookup")

    loaded_profiles = [load_example_theater(path) for path in profile_paths]
    id_parts = OBJECT_ID.split(":")
    theater_hint = id_parts[1].casefold() if len(id_parts) >= 3 else None
    hinted_profiles = [
        item for item in loaded_profiles
        if theater_hint is not None and item[0].theater_id.casefold() == theater_hint
    ]
    candidates = hinted_profiles or loaded_profiles
    matches: list[tuple[TheaterDataProfile, TheaterDataPaths, SceneryVerificationFeature]] = []
    failures: list[str] = []
    for theater, theater_paths in candidates:
        try:
            feature = resolve_scenery_verification_feature(
                theater.theater_id,
                OBJECT_ID,
                {
                    key: theater_paths.path(key)
                    for key in (
                        "infrastructure_sites",
                        "railway_infrastructure",
                        "settlements",
                        "transport_infrastructure",
                    )
                },
            )
        except ValueError as exc:
            failures.append(f"{theater.theater_id}: {exc}")
            continue
        if feature is not None:
            matches.append((theater, theater_paths, feature))

    if len(matches) > 1:
        theaters = ", ".join(item[0].theater_id for item in matches)
        raise ValueError(
            f"Normalized theater feature is ambiguous across {theaters}: {OBJECT_ID}. "
            "Set THEATER_PROFILE explicitly."
        )
    if not matches:
        searched = ", ".join(item[0].theater_id for item in candidates)
        detail = f" ({'; '.join(failures)})" if failures else ""
        raise ValueError(
            f"Normalized theater feature not found in {searched}: {OBJECT_ID}{detail}"
        )
    return matches[0]


def feature_geometry(feature: SceneryVerificationFeature):
    return shape(feature.geometry)


def has_area_footprint(feature: SceneryVerificationFeature) -> bool:
    geometry = feature_geometry(feature)
    return not geometry.is_empty and geometry.geom_type in {"Polygon", "MultiPolygon"}


def required_footprint_radius_m(feature: SceneryVerificationFeature) -> float | None:
    geometry = feature_geometry(feature)
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    return max(
        distance_m(feature.latitude, feature.longitude, latitude, longitude)
        for latitude, longitude in (
            (min_lat, min_lon),
            (min_lat, max_lon),
            (max_lat, min_lon),
            (max_lat, max_lon),
        )
    ) + SURVEY_MARGIN_M


def survey_radius_m(feature: SceneryVerificationFeature) -> float:
    if SURVEY_RADIUS_M is not None:
        if not 0 < SURVEY_RADIUS_M <= MAXIMUM_SURVEY_RADIUS_M:
            raise ValueError("SURVEY_RADIUS_M must be in range 0..5000 or None")
        return SURVEY_RADIUS_M
    required = required_footprint_radius_m(feature)
    if required is None:
        return DEFAULT_POINT_SURVEY_RADIUS_M
    return min(MAXIMUM_SURVEY_RADIUS_M, max(MINIMUM_AREA_SURVEY_RADIUS_M, required))


def footprint_fully_covered(feature: SceneryVerificationFeature, radius_m: float) -> bool:
    required = required_footprint_radius_m(feature)
    return required is None or required <= radius_m


def classify_survey_objects(
    feature: SceneryVerificationFeature,
    survey: ScenerySurvey,
) -> tuple[list, list]:
    objects = sorted(
        survey.objects,
        key=lambda item: distance_m(feature.latitude, feature.longitude, item.latitude, item.longitude),
    )
    if not has_area_footprint(feature):
        return objects, []
    footprint = feature_geometry(feature)
    included = []
    nearby = []
    for item in objects:
        target = included if footprint.covers(Point(item.longitude, item.latitude)) else nearby
        target.append(item)
    return included, nearby


def observation_complete(feature: SceneryVerificationFeature, survey: ScenerySurvey) -> bool:
    return not survey.truncated and footprint_fully_covered(feature, survey.radius_m)


def load_verification_registry(
    theater_id: str,
    verifications_path: Path,
) -> StrategicVerificationRegistry:
    return StrategicVerificationRegistry.load(verifications_path).bind_theater(theater_id)


def format_feature(feature: SceneryVerificationFeature, theater_id: str) -> None:
    properties = feature.properties
    print("Scenery representation verification")
    print("=" * 96)
    print(f"Theater         : {theater_id}")
    print(f"Object ID       : {feature.object_id}")
    print(f"Name            : {feature.name or 'unnamed'}")
    print(f"Type            : {properties.get('object_type') or feature.layer}")
    print(f"Category        : {feature.category.replace('_', ' ')}")
    print(f"Artifact        : {feature.artifact_key}")
    importance = properties.get("importance_score")
    tier = properties.get("importance_tier")
    if importance is not None:
        print(f"Importance      : {float(importance):.1f}" + (f" ({tier})" if tier else ""))
    print(f"Position        : {feature.latitude:.5f}, {feature.longitude:.5f}")
    print(f"Geometry        : {feature.geometry.get('type') or 'unknown'}")
    print(f"Source          : {feature.source}")


def format_verification(
    feature: SceneryVerificationFeature,
    theater_id: str,
    verifications_path: Path,
) -> None:
    verification = load_verification_registry(theater_id, verifications_path).get(feature.object_id)
    print("\nSaved DCS verification")
    print("=" * 96)
    print(f"Registry        : {verifications_path}")
    if verification is None:
        print("Status          : not mapped")
        print("Observed objects: 0")
        print("Target components: 0")
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


def format_survey(
    feature: SceneryVerificationFeature,
    survey: ScenerySurvey,
    included: list,
    nearby: list,
) -> None:
    complete = observation_complete(feature, survey)
    print("\nDCS scenery survey")
    print("=" * 96)
    print(f"Radius          : {survey.radius_m:.0f} m")
    print(f"Objects         : {len(survey.objects)}{' (truncated)' if survey.truncated else ''}")
    print(f"Baseline set    : {len(included)}")
    print(f"Nearby context  : {len(nearby)}")
    print(f"Completeness    : {'complete' if complete else 'partial'}")
    if not footprint_fully_covered(feature, survey.radius_m):
        required = required_footprint_radius_m(feature)
        print(
            "Warning         : footprint exceeds the 5 km DCS survey limit "
            f"(approximately {required / 1_000:.1f} km required)"
        )
    if survey.truncated:
        print("Warning         : DCS returned the maximum number of scenery objects")
    if not included:
        print("No fixed DCS scenery objects were found in the verification area.")
        return
    print(f"\n{'Distance':>9}  {'Object ID':<24} {'Type':<27} Display name")
    print(f"{'-' * 9}  {'-' * 24} {'-' * 27} {'-' * 24}")
    for item in included[:MAX_PRINTED_OBJECTS]:
        distance = distance_m(feature.latitude, feature.longitude, item.latitude, item.longitude)
        print(
            f"{distance:8.0f}m  {item.object_id[:24]:<24} "
            f"{(item.type_name or '-')[:27]:<27} {item.display_name or '-'}"
        )
    print("\nThe complete baseline set is retained for later damage assessment.")
    print("Select only a small target subset in the web-map DCS verification panel.")
    print("Target format: SCENERY:<id> | infrastructure component | 1.0")


def save_observed_baseline(
    feature: SceneryVerificationFeature,
    survey: ScenerySurvey,
    included: list,
    theater_id: str,
    verifications_path: Path,
) -> StrategicSiteVerification:
    registry = load_verification_registry(theater_id, verifications_path)
    current = registry.get(feature.object_id)
    observed = tuple(
        ObservedDcsObject(
            object_id=item.object_id,
            type_name=item.type_name or "",
            display_name=item.display_name or item.name or "",
            latitude=item.latitude,
            longitude=item.longitude,
            life=item.life,
            exists=item.exists,
        )
        for item in included
    )
    observed_ids = {item.object_id for item in observed}
    verification = StrategicSiteVerification(
        source_id=feature.object_id,
        state=current.state if current is not None else "unverified",
        observed_objects=observed,
        observation_complete=observation_complete(feature, survey),
        target_components=tuple(
            component
            for component in (current.target_components if current is not None else ())
            if component.object_id in observed_ids
        ),
        notes=current.notes if current is not None else "",
    )
    registry.upsert(verification)
    registry.save(verifications_path)
    return verification


def assess_current_survey(
    bridge: MooseBridgeClient,
    feature: SceneryVerificationFeature,
    survey: ScenerySurvey,
    included: list,
    theater_id: str,
    verifications_path: Path,
) -> None:
    verification = load_verification_registry(theater_id, verifications_path).get(feature.object_id)
    if verification is None or not verification.observed_objects:
        print("\nCurrent state: no saved observation baseline")
        return
    current = tuple(
        ObservedDcsObject(
            object_id=item.object_id,
            type_name=item.type_name or "",
            display_name=item.display_name or item.name or "",
            latitude=item.latitude,
            longitude=item.longitude,
            life=item.life,
            exists=item.exists,
        )
        for item in included
    )
    assessment = assess_infrastructure_state(
        verification,
        current,
        destroyed_object_ids=bridge.state.destroyed_object_ids,
        current_observation_complete=observation_complete(feature, survey),
    )
    health = "unknown" if assessment.health_min is None else f"{assessment.health_min * 100:.1f}%"
    if assessment.health_max != assessment.health_min and assessment.health_max is not None:
        health += f"..{assessment.health_max * 100:.1f}%"
    print("\nCurrent scenery state")
    print("=" * 96)
    print(f"State           : {assessment.state.value}")
    print(f"Health          : {health}")
    print(f"Evidence        : {'complete' if assessment.complete else 'bounded estimate'}")
    print(
        "Objects         : "
        f"{assessment.intact_count} intact, {assessment.damaged_count} damaged, "
        f"{assessment.destroyed_count} destroyed, {assessment.unknown_count} unknown"
    )


def footprint_markups(
    feature: SceneryVerificationFeature,
    color: tuple[float, float, float, float],
) -> list[DebugMarkup]:
    geometry = feature_geometry(feature)
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return []
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
    markups: list[DebugMarkup] = []
    remaining = MAX_FOOTPRINT_POINTS
    for polygon in polygons:
        if remaining < 2:
            break
        coordinates = list(polygon.exterior.coords)
        if len(coordinates) > remaining:
            step = max(1, math.ceil((len(coordinates) - 1) / max(1, remaining - 1)))
            coordinates = coordinates[:-1:step]
            coordinates.append(coordinates[0])
        remaining -= len(coordinates)
        if len(coordinates) >= 2:
            markups.append(DebugMarkup(
                "line",
                tuple(
                    DebugMarkupPoint(latitude=latitude, longitude=longitude)
                    for longitude, latitude in coordinates
                ),
                color=color,
                line_type=2,
            ))
    return markups


def feature_color(feature: SceneryVerificationFeature) -> tuple[float, float, float, float]:
    return {
        "infrastructure_sites": (0.46, 0.34, 0.55, 1.0),
        "railway_infrastructure": (0.31, 0.33, 0.32, 1.0),
        "settlements": (0.68, 0.27, 0.24, 1.0),
        "transport_infrastructure": (0.09, 0.44, 0.47, 1.0),
    }.get(feature.artifact_key, (0.3, 0.3, 0.3, 1.0))


def overlay_markups(
    feature: SceneryVerificationFeature,
    radius_m: float,
    included: list,
    nearby: list,
) -> list[DebugMarkup]:
    color = feature_color(feature)
    marks = [
        DebugMarkup(
            "point",
            (DebugMarkupPoint(feature.latitude, feature.longitude),),
            color=(1.0, 0.0, 0.85, 1.0),
            fill_color=(1.0, 0.0, 0.85, 0.04),
            radius_m=max(LOCATOR_RADIUS_M, radius_m),
        ),
        DebugMarkup(
            "point",
            (DebugMarkupPoint(feature.latitude, feature.longitude),),
            color=color,
            fill_color=(*color[:3], 0.08),
            radius_m=radius_m,
        ),
    ]
    marks.extend(footprint_markups(feature, color))
    marks.extend(
        DebugMarkup(
            "point",
            (DebugMarkupPoint(item.latitude, item.longitude),),
            color=(0.2, 1.0, 0.35, 1.0),
            fill_color=(0.2, 1.0, 0.35, 0.25),
            radius_m=25,
        )
        for item in included[:MAX_DRAWN_OBJECTS]
    )
    remaining = max(0, MAX_DRAWN_OBJECTS - len(included))
    marks.extend(
        DebugMarkup(
            "point",
            (DebugMarkupPoint(item.latitude, item.longitude),),
            color=(0.1, 0.8, 0.9, 0.75),
            fill_color=(0.1, 0.8, 0.9, 0.12),
            radius_m=15,
        )
        for item in nearby[:remaining]
    )
    return marks


async def run() -> int:
    theater, theater_paths, feature = select_feature()
    verifications_path = theater_paths.path("strategic_verifications")
    radius_m = survey_radius_m(feature)
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge: MooseBridgeClient = session.bridge

    format_feature(feature, theater.theater_id)
    format_verification(feature, theater.theater_id, verifications_path)
    survey = await bridge.survey_scenery(
        feature.latitude,
        feature.longitude,
        radius_m=radius_m,
        max_results=MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    included, nearby = classify_survey_objects(feature, survey)
    format_survey(feature, survey, included, nearby)
    assess_current_survey(
        bridge,
        feature,
        survey,
        included,
        theater.theater_id,
        verifications_path,
    )

    if not DRAW_F10_OVERLAY:
        return 0
    drawn = False
    try:
        await bridge.draw_debug_overlay(
            OVERLAY_ID,
            overlay_markups(feature, radius_m, included, nearby),
            replace=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        drawn = True
        await asyncio.to_thread(
            input,
            "Inspect the feature outline, green baseline objects, and cyan context in DCS F10, then press Enter ... ",
        )
        if SAVE_OBSERVED_BASELINE:
            current = load_verification_registry(
                theater.theater_id,
                verifications_path,
            ).get(feature.object_id)
            if current is not None and current.observed_objects and not REPLACE_OBSERVED_BASELINE:
                print(
                    "Existing observation baseline preserved. "
                    "Set REPLACE_OBSERVED_BASELINE=True to replace it deliberately."
                )
            else:
                verification = save_observed_baseline(
                    feature,
                    survey,
                    included,
                    theater.theater_id,
                    verifications_path,
                )
                completeness = "complete" if verification.observation_complete else "partial"
                print(
                    f"Saved {len(verification.observed_objects)} SCENERY object(s) as a "
                    f"{completeness} baseline: {verifications_path}"
                )
    finally:
        if drawn:
            await bridge.clear_debug_overlay(OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
