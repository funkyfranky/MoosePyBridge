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

from example_support import load_example_scenery_feature, open_example_session, run_example

from moosebridge import (  # noqa: E402
    DEFAULT_THEATER_PROFILE_PATH,
    DebugMarkup,
    DebugMarkupPoint,
    MooseBridgeClient,
    ObservedDcsObject,
    ScenerySurvey,
    SceneryVerificationFeature,
    SceneryVerificationMarker,
    SceneryZoneAssignment,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
    StrategicVerificationState,
    VerifiedDcsComponent,
    assess_infrastructure_state,
    latest_scenery_verification_marker,
    scenery_zone_assignments,
)
from moosebridge.control import DEFAULT_CONTROL_PORT  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

# Copy the object ID from the web-map detail panel. Supported normalized source
# types are infrastructure sites, railway locations, settlements, road bridges,
# and transport junctions.
OBJECT_ID = "MARITIME_SITE:faee9372f262ce51"

# None searches the bundled theater profiles and selects the one containing
# OBJECT_ID. Set a profile path only to resolve a deliberately ambiguous ID.
THEATER_PROFILE: str | Path | None = None

# None automatically covers a bounded polygon footprint. Point features use the
# default radius. Set an explicit value for a deliberately different survey.
SURVEY_RADIUS_M: float | None = None

# "optional" uses an active F10 marker when one already exists, "wait" waits
# for one after startup, and "off" always uses the normalized source position.
# Marker text: verify OBJECT_ID. Later lines may contain `radius 250m` or
# `radius 2km`; any other lines are retained as a note.
F10_MARKER_MODE = "optional"
F10_MARKER_WAIT_SECONDS = 300.0
SAVE_OBSERVED_BASELINE = True
REPLACE_OBSERVED_BASELINE = True
DRAW_F10_OVERLAY = True

# Safety and display limits. DCS scenery.search accepts at most 5 km and 2,000
# results. A survey that reaches either limit remains explicitly partial.
DEFAULT_POINT_SURVEY_RADIUS_M = 1_000.0
MARKER_POINT_SURVEY_RADIUS_M = 500.0
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


def feature_geometry(feature: SceneryVerificationFeature):
    return shape(feature.geometry)


def has_area_footprint(feature: SceneryVerificationFeature) -> bool:
    geometry = feature_geometry(feature)
    return not geometry.is_empty and geometry.geom_type in {"Polygon", "MultiPolygon"}


def required_footprint_radius_m(
    feature: SceneryVerificationFeature,
    center_latitude: float | None = None,
    center_longitude: float | None = None,
) -> float | None:
    geometry = feature_geometry(feature)
    if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    latitude_origin = feature.latitude if center_latitude is None else center_latitude
    longitude_origin = feature.longitude if center_longitude is None else center_longitude
    return max(
        distance_m(latitude_origin, longitude_origin, latitude, longitude)
        for latitude, longitude in (
            (min_lat, min_lon),
            (min_lat, max_lon),
            (max_lat, min_lon),
            (max_lat, max_lon),
        )
    ) + SURVEY_MARGIN_M


def survey_radius_m(
    feature: SceneryVerificationFeature,
    marker: SceneryVerificationMarker | None = None,
) -> float:
    if SURVEY_RADIUS_M is not None:
        if not 0 < SURVEY_RADIUS_M <= MAXIMUM_SURVEY_RADIUS_M:
            raise ValueError("SURVEY_RADIUS_M must be in range 0..5000 or None")
        return SURVEY_RADIUS_M
    if marker is not None and marker.radius_m is not None:
        return marker.radius_m
    required = required_footprint_radius_m(
        feature,
        marker.latitude if marker is not None else None,
        marker.longitude if marker is not None else None,
    )
    if required is None:
        return MARKER_POINT_SURVEY_RADIUS_M if marker is not None else DEFAULT_POINT_SURVEY_RADIUS_M
    return min(MAXIMUM_SURVEY_RADIUS_M, max(MINIMUM_AREA_SURVEY_RADIUS_M, required))


def footprint_fully_covered(
    feature: SceneryVerificationFeature,
    radius_m: float,
    center_latitude: float | None = None,
    center_longitude: float | None = None,
) -> bool:
    required = required_footprint_radius_m(feature, center_latitude, center_longitude)
    return required is None or required <= radius_m + 1.0


def classify_survey_objects(
    feature: SceneryVerificationFeature,
    survey: ScenerySurvey,
) -> tuple[list, list]:
    objects = sorted(
        survey.objects,
        key=lambda item: distance_m(
            survey.center.latitude,
            survey.center.longitude,
            item.latitude,
            item.longitude,
        ),
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


def observation_complete(
    feature: SceneryVerificationFeature,
    survey: ScenerySurvey,
    assignments: tuple[SceneryZoneAssignment, ...] = (),
) -> bool:
    assigned_ids = {item.scenery_object_id for item in assignments}
    surveyed_ids = {item.object_id for item in survey.objects}
    if assigned_ids:
        return assigned_ids.issubset(surveyed_ids)
    return not survey.truncated and footprint_fully_covered(
        feature,
        survey.radius_m,
        survey.center.latitude,
        survey.center.longitude,
    )


def merge_survey_objects(
    survey: ScenerySurvey,
    exact_objects: tuple,
) -> ScenerySurvey:
    """Add exact Assign-As resolutions without duplicating spatial results."""

    by_id = {item.object_id: item for item in survey.objects}
    by_id.update({item.object_id: item for item in exact_objects})
    return ScenerySurvey(
        center=survey.center,
        radius_m=survey.radius_m,
        objects=tuple(by_id.values()),
        truncated=survey.truncated,
    )


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
    assignments: tuple[SceneryZoneAssignment, ...],
) -> None:
    complete = observation_complete(feature, survey, assignments)
    print("\nDCS scenery survey")
    print("=" * 96)
    print(f"Radius          : {survey.radius_m:.0f} m")
    print(f"Objects         : {len(survey.objects)}{' (truncated)' if survey.truncated else ''}")
    print(f"Baseline set    : {len(included)}")
    print(f"Nearby context  : {len(nearby)}")
    print(f"Completeness    : {'complete' if complete else 'partial'}")
    if assignments:
        queryable_count = sum(item.queryable for item in included)
        print(f"Live queryable  : {queryable_count}/{len(included)}")
    if not assignments and not footprint_fully_covered(
        feature,
        survey.radius_m,
        survey.center.latitude,
        survey.center.longitude,
    ):
        required = required_footprint_radius_m(
            feature,
            survey.center.latitude,
            survey.center.longitude,
        )
        if required is not None and required > MAXIMUM_SURVEY_RADIUS_M:
            print(
                "Warning         : footprint exceeds the 5 km DCS survey limit "
                f"(approximately {required / 1_000:.1f} km required)"
            )
        elif required is not None:
            print(
                "Warning         : survey does not cover the complete footprint "
                f"({required:.0f} m required, {survey.radius_m:.0f} m surveyed)"
            )
    if survey.truncated and not assignments:
        print("Warning         : DCS returned the maximum number of scenery objects")
    if assignments and not complete:
        missing_ids = sorted(
            {item.scenery_object_id for item in assignments}
            - {item.object_id for item in survey.objects}
        )
        if missing_ids:
            print(f"Warning         : assigned object(s) missing from survey: {', '.join(missing_ids)}")
    if not included:
        print("No fixed DCS scenery objects were selected for the observation baseline.")
        return
    print(f"\n{'Distance':>9}  {'Object ID':<24} {'Type':<27} Display name")
    print(f"{'-' * 9}  {'-' * 24} {'-' * 27} {'-' * 24}")
    for item in included[:MAX_PRINTED_OBJECTS]:
        distance = distance_m(
            survey.center.latitude,
            survey.center.longitude,
            item.latitude,
            item.longitude,
        )
        print(
            f"{distance:8.0f}m  {item.object_id[:24]:<24} "
            f"{(item.type_name or '-')[:27]:<27} {item.display_name or '-'}"
        )
    if assignments:
        print("\nAssign As objects form the exact DCS observation baseline.")
        print("Other surveyed objects are retained only as visual context.")
        if any(not item.queryable for item in included):
            print("Objects omitted by the DCS runtime scan retain an unknown live state.")
        if has_area_footprint(feature):
            print("Select a small target subset in the web-map panel after saving the baseline.")
    else:
        print("\nThe complete baseline set is retained for later damage assessment.")
    if not has_area_footprint(feature):
        print("Point-feature Assign As objects are also selected as exact targets.")
    print("The web-map panel remains available for manual target edits.")
    print("Target format: SCENERY:<id> | infrastructure component | 1.0")


def format_assignments(
    assignments: tuple[SceneryZoneAssignment, ...],
    survey: ScenerySurvey,
) -> None:
    surveyed_by_id = {item.object_id: item for item in survey.objects}
    print("\nMission Editor Assign As")
    print("=" * 96)
    if not assignments:
        print("Assignments     : 0")
        print("Hint            : name an Assign As zone after the normalized Object ID")
        return
    print(f"Assignments     : {len(assignments)}")
    for assignment in assignments:
        found = surveyed_by_id.get(assignment.scenery_object_id)
        if found is None:
            availability = "reference unavailable"
        elif found.queryable:
            availability = "resolved in DCS"
        else:
            availability = "assigned; live state unavailable"
        print(f"  {assignment.zone_name} -> {assignment.scenery_object_id} ({availability})")


def format_marker(
    feature: SceneryVerificationFeature,
    marker: SceneryVerificationMarker | None,
) -> None:
    print("\nF10 verification marker")
    print("=" * 96)
    if marker is None:
        print("Marker          : none; normalized source position is used")
        print(f"Command         : verify {feature.object_id}")
        return
    offset = distance_m(
        feature.latitude,
        feature.longitude,
        marker.latitude,
        marker.longitude,
    )
    print(f"Marker ID       : {marker.marker_id}")
    print(f"Survey position : {marker.latitude:.5f}, {marker.longitude:.5f}")
    print(f"Source offset   : {offset:.0f} m")
    if marker.radius_m is not None:
        print(f"Survey radius   : {marker.radius_m:.0f} m")
    if marker.player_name:
        print(f"Player          : {marker.player_name}")
    if marker.note:
        print(f"Note            : {marker.note}")


async def resolve_verification_marker(
    bridge: MooseBridgeClient,
    feature: SceneryVerificationFeature,
) -> SceneryVerificationMarker | None:
    mode = F10_MARKER_MODE.strip().casefold()
    if mode not in {"off", "optional", "wait"}:
        raise ValueError("F10_MARKER_MODE must be 'off', 'optional', or 'wait'")
    if mode == "off":
        return None

    history = await bridge.server.query_events("map.marker.*")
    events = [item for item in history.get("events", []) if isinstance(item, dict)]
    marker = latest_scenery_verification_marker(events, feature.object_id)
    if marker is not None and marker.option_errors:
        raise ValueError(
            f"F10 marker {marker.marker_id} has invalid options: "
            + "; ".join(marker.option_errors)
        )
    if marker is not None or mode == "optional":
        return marker

    print("\nWaiting for an F10 verification marker.")
    print(f"Create or edit a marker with this first line: verify {feature.object_id}")
    cursor = str(history.get("latest_event_id") or "") or None
    deadline = asyncio.get_running_loop().time() + F10_MARKER_WAIT_SECONDS
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(
                f"No F10 verification marker received within {F10_MARKER_WAIT_SECONDS:g} seconds"
            )
        event = await bridge.server.wait_for_event(
            "map.marker.*",
            timeout=remaining,
            after_id=cursor,
        )
        if str(event.get("event") or "") == "mission.ended":
            raise RuntimeError("DCS mission ended while waiting for an F10 verification marker")
        events.append(event)
        cursor = str(event.get("id") or "") or cursor
        marker = latest_scenery_verification_marker(events, feature.object_id)
        if marker is not None:
            if marker.option_errors:
                raise ValueError(
                    f"F10 marker {marker.marker_id} has invalid options: "
                    + "; ".join(marker.option_errors)
                )
            return marker


def include_assigned_objects(
    feature: SceneryVerificationFeature,
    included: list,
    nearby: list,
    survey: ScenerySurvey,
    assignments: tuple[SceneryZoneAssignment, ...],
) -> tuple[list, list]:
    assigned_ids = {item.scenery_object_id for item in assignments}
    if not assigned_ids:
        return included, nearby
    ordered = sorted(
        survey.objects,
        key=lambda item: distance_m(
            survey.center.latitude,
            survey.center.longitude,
            item.latitude,
            item.longitude,
        ),
    )
    if not has_area_footprint(feature):
        return (
            [item for item in ordered if item.object_id in assigned_ids],
            [item for item in ordered if item.object_id not in assigned_ids],
        )
    return (
        [item for item in ordered if item.object_id in assigned_ids],
        [item for item in ordered if item.object_id not in assigned_ids],
    )


def save_observed_baseline(
    feature: SceneryVerificationFeature,
    survey: ScenerySurvey,
    included: list,
    assignments: tuple[SceneryZoneAssignment, ...],
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
    assigned_ids = {
        assignment.scenery_object_id
        for assignment in assignments
        if assignment.scenery_object_id in observed_ids
    }
    if assignments and not has_area_footprint(feature):
        target_components = tuple(
            VerifiedDcsComponent(
                object_id=object_id,
                role="Mission Editor assigned scenery object",
            )
            for object_id in sorted(assigned_ids)
        )
    else:
        target_components = tuple(
            component
            for component in (current.target_components if current is not None else ())
            if component.object_id in observed_ids
        )
    verification = StrategicSiteVerification(
        source_id=feature.object_id,
        state=(
            StrategicVerificationState.REPRESENTED
            if observed
            else current.state if current is not None else StrategicVerificationState.UNVERIFIED
        ),
        observed_objects=observed,
        observation_complete=observation_complete(feature, survey, assignments),
        target_components=target_components,
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
    assignments: tuple[SceneryZoneAssignment, ...],
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
        if item.queryable
    )
    assessment = assess_infrastructure_state(
        verification,
        current,
        destroyed_object_ids=bridge.state.destroyed_object_ids,
        current_observation_complete=(
            observation_complete(feature, survey, assignments)
            and all(item.queryable for item in included)
        ),
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
    survey_latitude: float,
    survey_longitude: float,
    included: list,
    nearby: list,
    assigned_object_ids: set[str],
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
            (DebugMarkupPoint(survey_latitude, survey_longitude),),
            color=color,
            fill_color=(*color[:3], 0.08),
            radius_m=radius_m,
        ),
    ]
    if distance_m(feature.latitude, feature.longitude, survey_latitude, survey_longitude) > 1:
        marks.extend((
            DebugMarkup(
                "line",
                (
                    DebugMarkupPoint(feature.latitude, feature.longitude),
                    DebugMarkupPoint(survey_latitude, survey_longitude),
                ),
                color=(1.0, 0.8, 0.0, 1.0),
                line_type=2,
            ),
            DebugMarkup(
                "point",
                (DebugMarkupPoint(survey_latitude, survey_longitude),),
                color=(1.0, 0.8, 0.0, 1.0),
                fill_color=(1.0, 0.8, 0.0, 0.35),
                radius_m=60,
            ),
        ))
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
    marks.extend(
        DebugMarkup(
            "point",
            (DebugMarkupPoint(item.latitude, item.longitude),),
            color=(1.0, 0.8, 0.0, 1.0),
            fill_color=(1.0, 0.8, 0.0, 0.3),
            radius_m=45,
        )
        for item in survey_objects_for_ids((*included, *nearby), assigned_object_ids)
    )
    return marks


def survey_objects_for_ids(objects, object_ids: set[str]) -> list:
    return [item for item in objects if item.object_id in object_ids]


async def run() -> int:
    theater, theater_paths, feature = load_example_scenery_feature(OBJECT_ID, THEATER_PROFILE)
    verifications_path = theater_paths.path("strategic_verifications")
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge: MooseBridgeClient = session.bridge
    await bridge.snapshot_zones()
    assignments = scenery_zone_assignments(feature.object_id, bridge.state.zones)
    marker = await resolve_verification_marker(bridge, feature)
    radius_m = survey_radius_m(feature, marker)
    survey_latitude = marker.latitude if marker is not None else feature.latitude
    survey_longitude = marker.longitude if marker is not None else feature.longitude

    format_feature(feature, theater.theater_id)
    format_verification(feature, theater.theater_id, verifications_path)
    format_marker(feature, marker)
    survey = await bridge.survey_scenery(
        survey_latitude,
        survey_longitude,
        radius_m=radius_m,
        max_results=MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if assignments:
        resolution = await bridge.resolve_scenery_objects(
            (item.scenery_object_id for item in assignments),
            zone_names={item.scenery_object_id: item.zone_name for item in assignments},
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        survey = merge_survey_objects(survey, resolution.objects)
    included, nearby = classify_survey_objects(feature, survey)
    included, nearby = include_assigned_objects(feature, included, nearby, survey, assignments)
    format_survey(feature, survey, included, nearby, assignments)
    format_assignments(assignments, survey)
    if not DRAW_F10_OVERLAY:
        assess_current_survey(
            bridge,
            feature,
            survey,
            included,
            assignments,
            theater.theater_id,
            verifications_path,
        )
        return 0
    drawn = False
    try:
        await bridge.draw_debug_overlay(
            OVERLAY_ID,
            overlay_markups(
                feature,
                radius_m,
                survey_latitude,
                survey_longitude,
                included,
                nearby,
                {item.scenery_object_id for item in assignments},
            ),
            replace=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        drawn = True
        await asyncio.to_thread(
            input,
            "Inspect the feature outline, green baseline, cyan context, and yellow assigned targets in DCS F10, then press Enter ... ",
        )
        if SAVE_OBSERVED_BASELINE:
            current = load_verification_registry(
                theater.theater_id,
                verifications_path,
            ).get(feature.object_id)
            upgrade_incomplete_assignment_baseline = (
                current is not None
                and not current.observation_complete
                and bool(assignments)
                and observation_complete(feature, survey, assignments)
            )
            if (
                current is not None
                and current.observed_objects
                and not REPLACE_OBSERVED_BASELINE
                and not upgrade_incomplete_assignment_baseline
            ):
                print(
                    "Existing observation baseline preserved. "
                    "Set REPLACE_OBSERVED_BASELINE=True to replace it deliberately."
                )
            else:
                if upgrade_incomplete_assignment_baseline:
                    print("Upgrading the partial baseline from the complete Assign As mapping.")
                verification = save_observed_baseline(
                    feature,
                    survey,
                    included,
                    assignments,
                    theater.theater_id,
                    verifications_path,
                )
                completeness = "complete" if verification.observation_complete else "partial"
                print(
                    f"Saved {len(verification.observed_objects)} SCENERY object(s) as a "
                    f"{completeness} baseline: {verifications_path}"
                )
        assess_current_survey(
            bridge,
            feature,
            survey,
            included,
            assignments,
            theater.theater_id,
            verifications_path,
        )
    finally:
        if drawn:
            await bridge.clear_debug_overlay(OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
