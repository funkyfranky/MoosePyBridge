"""Verify one normalized infrastructure site against nearby DCS scenery.

The MoosePyBridge daemon and a DCS mission using the current MooseBridge.lua
must already be running. Edit the constants below; no command-line arguments
are required.
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
    EnergySite,
    FuelStorageSite,
    InfrastructureSite,
    IndustrialSite,
    MaritimeSite,
    MilitarySite,
    MooseBridgeClient,
    ObservedDcsObject,
    ScenerySurvey,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
    TheaterInfrastructureSites,
    assess_infrastructure_state,
)
from moosebridge.control import DEFAULT_CONTROL_PORT  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH
_, THEATER_PATHS = load_example_theater(THEATER_PROFILE)
SITES_PATH = THEATER_PATHS.path("infrastructure_sites")
VERIFICATIONS_PATH = THEATER_PATHS.path("strategic_verifications")

# Copy the object ID from the web-map detail panel.
SITE_ID = "MILITARY_SITE:88ed34fd505620ec"

# Verification workflow options.
SURVEY_RADIUS_M = 750.0
DRAW_F10_OVERLAY = True
SAVE_OBSERVED_BASELINE = False
REPLACE_OBSERVED_BASELINE = False

# Internal display and safety limits. These normally do not need adjustment.
_MAX_SCENERY_OBJECTS = 250
_MAX_PRINTED_OBJECTS = 40
_MAX_DRAWN_OBJECTS = 50
_MAX_FOOTPRINT_POINTS = 160
_OVERLAY_ID = "infrastructure-site-verification"


def distance_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(value)))


def select_site(artifact: TheaterInfrastructureSites) -> InfrastructureSite:
    matches = tuple(site for site in artifact.sites if site.site_id == SITE_ID)
    if not matches:
        raise ValueError(f"Infrastructure site ID not found: {SITE_ID}")
    return matches[0]


def format_site(site: InfrastructureSite) -> None:
    print(f"{site.kind.value.replace('_', ' ').title()} site")
    print("=" * 88)
    print(f"Object ID       : {site.site_id}")
    print(f"Name            : {site.name or 'unnamed'}")
    if isinstance(site, EnergySite):
        print(f"Energy sources  : {', '.join(source.value for source in site.energy_sources)}")
        print(f"Output          : {site.output_mw:.1f} MW" if site.output_mw is not None else "Output          : unknown")
    elif isinstance(site, FuelStorageSite):
        print(f"Roles           : {', '.join(role.value for role in site.storage_roles)}")
        print(f"Commodities     : {', '.join(value.value for value in site.commodities)}")
        capacity = f"{site.capacity_m3:,.0f} m3" if site.capacity_m3 is not None else "unknown"
        print(f"Known capacity  : {capacity}")
        print(f"Components      : {len(site.component_ids)}")
    elif isinstance(site, MilitarySite):
        print(f"Roles           : {', '.join(role.value for role in site.roles)}")
        area = f"{site.footprint_area_m2 / 1_000_000:,.2f} km2" if site.footprint_area_m2 is not None else "unknown"
        print(f"Footprint       : {area}")
        print(f"Importance      : {site.importance_score:.1f} ({site.importance_tier.value})")
        print(f"Targetable      : {bool(site.properties.get('targetable_candidate'))}")
        print(f"Historical fit  : {site.properties.get('historical_fit') or 'unverified'}")
        print(f"Components      : {len(site.component_ids)}")
    elif isinstance(site, IndustrialSite):
        print(f"Roles           : {', '.join(role.value for role in site.roles)}")
        print(f"Products        : {', '.join(site.products) if site.products else 'unknown'}")
        area = f"{site.footprint_area_m2:,.0f} m2" if site.footprint_area_m2 is not None else "unknown"
        print(f"Footprint       : {area}")
        print(f"Importance      : {site.importance_score:.1f} ({site.importance_tier.value})")
        print(f"Scale           : {site.properties.get('scale') or 'unknown'}")
        print(f"Strategic       : {bool(site.properties.get('strategic_candidate'))}")
        print(f"Components      : {len(site.component_ids)}")
    elif isinstance(site, MaritimeSite):
        print(f"Roles           : {', '.join(role.value for role in site.roles)}")
        print(f"Cargo           : {', '.join(value.value for value in site.cargo_types) if site.cargo_types else 'unknown'}")
        area = f"{site.footprint_area_m2 / 1_000_000:,.2f} km2" if site.footprint_area_m2 is not None else "unknown"
        quay = f"{site.quay_length_m / 1_000:,.2f} km" if site.quay_length_m is not None else "unknown"
        print(f"Footprint       : {area}")
        print(f"Quay length     : {quay}")
        print(f"Berths          : {site.berth_count}")
        print(f"Importance      : {site.importance_score:.1f} ({site.importance_tier.value})")
        print(f"Strategic       : {bool(site.properties.get('strategic_candidate'))}")
        print(f"Components      : {len(site.component_ids)}")
    print(f"Position        : {site.latitude:.5f}, {site.longitude:.5f}")
    print(f"Source          : {site.source}")
    print(f"Confidence      : {site.confidence:.2f}")
    print(f"Source evidence : {site.verification_state.value}")


def format_strategic_verification(site: InfrastructureSite) -> None:
    verification = StrategicVerificationRegistry.load(VERIFICATIONS_PATH).get(site.site_id)
    print("\nStrategic DCS verification")
    print("=" * 88)
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


def format_survey(site: InfrastructureSite, survey: ScenerySurvey) -> None:
    objects = sorted(
        survey.objects,
        key=lambda item: distance_m(site.latitude, site.longitude, item.latitude, item.longitude),
    )
    footprint_objects, nearby_objects = classify_survey_objects(site, objects)
    print("\nDCS scenery survey")
    print("=" * 88)
    print(f"Radius          : {survey.radius_m:.0f} m")
    print(f"Objects         : {len(objects)}{' (truncated)' if survey.truncated else ''}")
    print(f"Within footprint: {len(footprint_objects)}")
    print(f"Nearby only     : {len(nearby_objects)}")
    if not objects:
        print("No addressable DCS scenery objects were found in the survey area.")
        return
    if not footprint_objects:
        print("No addressable DCS scenery objects were found inside the site footprint.")
        return
    print(f"\n{'Distance':>9}  {'Object ID':<24} {'Type':<25} Display name")
    print(f"{'-' * 9}  {'-' * 24} {'-' * 25} {'-' * 24}")
    for item in footprint_objects[:_MAX_PRINTED_OBJECTS]:
        distance = distance_m(site.latitude, site.longitude, item.latitude, item.longitude)
        print(f"{distance:8.0f}m  {item.object_id[:24]:<24} {(item.type_name or '-')[:25]:<25} {item.display_name or '-'}")
    print("\nAll visually confirmed in-footprint objects will form the observation baseline.")
    print("Select only a small target subset in the web-map DCS verification panel.")
    print("Target format: SCENERY:<id> | infrastructure component | 1.0")


def classify_survey_objects(
    site: InfrastructureSite,
    objects: tuple | list,
) -> tuple[list, list]:
    """Separate DCS objects inside the normalized footprint from nearby context."""

    footprint = shape(site.geometry)
    if footprint.is_empty or footprint.geom_type not in {"Polygon", "MultiPolygon"}:
        return list(objects), []
    inside = []
    nearby = []
    for item in objects:
        target = inside if footprint.covers(Point(item.longitude, item.latitude)) else nearby
        target.append(item)
    return inside, nearby


def footprint_fully_covered(site: InfrastructureSite, radius_m: float) -> bool:
    """Return whether the circular survey contains the complete site footprint."""

    footprint = shape(site.geometry)
    if footprint.is_empty or footprint.geom_type not in {"Polygon", "MultiPolygon"}:
        return False
    min_lon, min_lat, max_lon, max_lat = footprint.bounds
    corners = ((min_lat, min_lon), (min_lat, max_lon), (max_lat, min_lon), (max_lat, max_lon))
    return all(
        distance_m(site.latitude, site.longitude, latitude, longitude) <= radius_m
        for latitude, longitude in corners
    )


def save_observed_baseline(
    site: InfrastructureSite,
    survey: ScenerySurvey,
    footprint_objects: list,
) -> StrategicSiteVerification:
    """Persist the confirmed footprint inventory without changing target selection."""

    registry = StrategicVerificationRegistry.load(VERIFICATIONS_PATH)
    current = registry.get(site.site_id)
    verification = StrategicSiteVerification(
        source_id=site.site_id,
        state=current.state if current is not None else "unverified",
        observed_objects=tuple(
            ObservedDcsObject(
                object_id=item.object_id,
                type_name=item.type_name or "",
                display_name=item.display_name or item.name or "",
                latitude=item.latitude,
                longitude=item.longitude,
                life=item.life,
                exists=item.exists,
            )
            for item in footprint_objects
        ),
        observation_complete=not survey.truncated and footprint_fully_covered(site, survey.radius_m),
        target_components=current.target_components if current is not None else (),
        notes=current.notes if current is not None else "",
    )
    registry.upsert(verification)
    registry.save(VERIFICATIONS_PATH)
    return verification


def assess_current_survey(
    bridge: MooseBridgeClient,
    site: InfrastructureSite,
    survey: ScenerySurvey,
    footprint_objects: list,
) -> None:
    verification = StrategicVerificationRegistry.load(VERIFICATIONS_PATH).get(site.site_id)
    if verification is None or not verification.observed_objects:
        print("\nInfrastructure state: no observation baseline exists yet")
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
        for item in footprint_objects
    )
    assessment = assess_infrastructure_state(
        verification,
        current,
        destroyed_object_ids=bridge.state.destroyed_object_ids,
        current_observation_complete=not survey.truncated and footprint_fully_covered(site, survey.radius_m),
    )
    health = (
        "unknown"
        if assessment.health_min is None
        else f"{assessment.health_min * 100:.1f}-{assessment.health_max * 100:.1f}%"
    )
    print("\nInfrastructure state")
    print("=" * 88)
    print(f"State           : {assessment.state.value}")
    print(f"Health range    : {health}")
    print(f"Assessment      : {'complete' if assessment.complete else 'partial'}")
    print(f"Baseline objects: {assessment.baseline_count}")
    print(f"Intact          : {assessment.intact_count}")
    print(f"Damaged         : {assessment.damaged_count}")
    print(f"Destroyed       : {assessment.destroyed_count}")
    print(f"Unknown         : {assessment.unknown_count}")
    changed = tuple(item for item in assessment.objects if item.condition in {"damaged", "destroyed"})
    for item in changed[:_MAX_PRINTED_OBJECTS]:
        health_text = "unknown" if item.health is None else f"{item.health * 100:.1f}%"
        print(f"  {item.object_id} condition={item.condition} health={health_text} source={item.source}")


def footprint_markups(site: InfrastructureSite, color: tuple[float, float, float, float]) -> list[DebugMarkup]:
    """Create bounded F10 outlines for the normalized site footprint."""

    footprint = shape(site.geometry)
    if footprint.is_empty:
        return []
    polygons = [footprint] if footprint.geom_type == "Polygon" else list(getattr(footprint, "geoms", ()))
    markups: list[DebugMarkup] = []
    remaining = _MAX_FOOTPRINT_POINTS
    for polygon in polygons:
        if polygon.geom_type != "Polygon" or remaining < 2:
            continue
        coordinates = list(polygon.exterior.coords)
        if len(coordinates) > remaining:
            step = max(1, math.ceil((len(coordinates) - 1) / max(1, remaining - 1)))
            coordinates = coordinates[:-1:step]
            coordinates.append(coordinates[0])
        remaining -= len(coordinates)
        if len(coordinates) >= 2:
            markups.append(DebugMarkup(
                "line",
                tuple(DebugMarkupPoint(latitude=latitude, longitude=longitude) for longitude, latitude in coordinates),
                color=color,
                line_type=2,
            ))
    return markups


async def run() -> int:
    if not SITES_PATH.is_file():
        print(f"Infrastructure-site artifact not found: {SITES_PATH}")
        print("Run: python tools/build_infrastructure_sites.py")
        return 2
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge: MooseBridgeClient = session.bridge
    site = select_site(TheaterInfrastructureSites.load(SITES_PATH))
    format_site(site)
    format_strategic_verification(site)
    survey = await bridge.survey_scenery(
        site.latitude,
        site.longitude,
        radius_m=SURVEY_RADIUS_M,
        max_results=_MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    format_survey(site, survey)
    footprint_objects, nearby_objects = classify_survey_objects(site, list(survey.objects))
    assess_current_survey(bridge, site, survey, footprint_objects)
    if not DRAW_F10_OVERLAY:
        return 0
    site_color = (
        (0.09, 0.44, 0.47, 1.0) if isinstance(site, MaritimeSite)
        else (0.46, 0.34, 0.55, 1.0) if isinstance(site, IndustrialSite)
        else (0.42, 0.35, 0.28, 1.0) if isinstance(site, MilitarySite)
        else (0.75, 0.42, 0.12, 1.0) if isinstance(site, FuelStorageSite)
        else (1.0, 0.75, 0.0, 1.0)
    )
    marks = [DebugMarkup(
        "point",
        (DebugMarkupPoint(site.latitude, site.longitude),),
        color=site_color,
        fill_color=(*site_color[:3], 0.08),
        radius_m=SURVEY_RADIUS_M,
    )]
    marks.extend(footprint_markups(site, site_color))
    marks.extend(
        DebugMarkup(
            "point",
            (DebugMarkupPoint(item.latitude, item.longitude),),
            color=(0.2, 1.0, 0.35, 1.0),
            fill_color=(0.2, 1.0, 0.35, 0.3),
            radius_m=25,
        )
        for item in footprint_objects[:_MAX_DRAWN_OBJECTS]
    )
    remaining_marks = max(0, _MAX_DRAWN_OBJECTS - len(footprint_objects))
    marks.extend(
        DebugMarkup(
            "point",
            (DebugMarkupPoint(item.latitude, item.longitude),),
            color=(0.1, 0.8, 0.9, 0.75),
            fill_color=(0.1, 0.8, 0.9, 0.12),
            radius_m=15,
        )
        for item in nearby_objects[:remaining_marks]
    )
    drawn = False
    try:
        await bridge.draw_debug_overlay(_OVERLAY_ID, marks, replace=True, timeout=COMMAND_TIMEOUT_SECONDS)
        drawn = True
        await asyncio.to_thread(
            input,
            "Inspect the footprint, green in-footprint objects, and cyan nearby objects in DCS F10, then press Enter ... ",
        )
        if SAVE_OBSERVED_BASELINE:
            current = StrategicVerificationRegistry.load(VERIFICATIONS_PATH).get(site.site_id)
            if current is not None and current.observed_objects and not REPLACE_OBSERVED_BASELINE:
                print("Existing observation baseline preserved. Set REPLACE_OBSERVED_BASELINE=True to replace it deliberately.")
            else:
                verification = save_observed_baseline(site, survey, footprint_objects)
                completeness = "complete" if verification.observation_complete else "partial"
                print(
                    f"Saved {len(verification.observed_objects)} observed object(s) as a {completeness} baseline: "
                    f"{VERIFICATIONS_PATH}"
                )
    finally:
        if drawn:
            await bridge.clear_debug_overlay(_OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
