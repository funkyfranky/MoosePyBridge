"""Verify one normalized infrastructure site against nearby DCS scenery.

The MoosePyBridge daemon and a DCS mission using the current MooseBridge.lua
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
    EnergySite,
    FuelStorageSite,
    InfrastructureSite,
    InfrastructureSiteKind,
    IndustrialSite,
    MaritimeSite,
    MilitarySite,
    MooseBridgeClient,
    ScenerySurvey,
    TheaterInfrastructureSites,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient  # noqa: E402
from moosebridge.control_sdk import sdk_from_control_client  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
SITES_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-infrastructure-sites.geojson"

# Select ENERGY, FUEL_STORAGE, MILITARY, INDUSTRIAL, or MARITIME. Set an exact site name, or leave
# None to use the nearest admitted site to REFERENCE_OBJECT_ID.
SITE_KIND = InfrastructureSiteKind.FUEL_STORAGE
SITE_NAME: str | None = None
REFERENCE_OBJECT_ID = "AIRBASE:Laage"
SURVEY_RADIUS_M = 750.0
MAX_SCENERY_OBJECTS = 250
MAX_PRINTED_OBJECTS = 40
DRAW_F10_OVERLAY = True
MAX_DRAWN_OBJECTS = 50
OVERLAY_ID = "infrastructure-site-verification"


def distance_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(value)))


async def select_site(bridge: MooseBridgeClient, artifact: TheaterInfrastructureSites) -> InfrastructureSite:
    candidates = tuple(site for site in artifact.sites if site.kind is SITE_KIND)
    if not candidates:
        raise ValueError(f"No {SITE_KIND.value} sites are present in {SITES_PATH.name}")
    if SITE_NAME is not None:
        matches = tuple(site for site in candidates if (site.name or "").casefold() == SITE_NAME.casefold())
        if not matches:
            raise ValueError(f"{SITE_KIND.value} site not found: {SITE_NAME}")
        if len(matches) > 1:
            raise ValueError(f"Site name is not unique: {SITE_NAME} ({len(matches)} matches)")
        return matches[0]
    reference = await bridge.coords(REFERENCE_OBJECT_ID, format="ll", timeout=COMMAND_TIMEOUT_SECONDS)
    if reference.latitude is None or reference.longitude is None:
        raise ValueError(f"DCS returned no WGS84 coordinate for {REFERENCE_OBJECT_ID}")
    return min(
        candidates,
        key=lambda site: distance_m(reference.latitude, reference.longitude, site.latitude, site.longitude),
    )


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
    print(f"Verification    : {site.verification_state.value}")


def format_survey(site: InfrastructureSite, survey: ScenerySurvey) -> None:
    objects = sorted(
        survey.objects,
        key=lambda item: distance_m(site.latitude, site.longitude, item.latitude, item.longitude),
    )
    print("\nDCS scenery survey")
    print("=" * 88)
    print(f"Radius          : {survey.radius_m:.0f} m")
    print(f"Objects         : {len(objects)}{' (truncated)' if survey.truncated else ''}")
    if not objects:
        print("No addressable DCS scenery objects were found in the survey area.")
        return
    print(f"\n{'Distance':>9}  {'Object ID':<24} {'Type':<25} Display name")
    print(f"{'-' * 9}  {'-' * 24} {'-' * 25} {'-' * 24}")
    for item in objects[:MAX_PRINTED_OBJECTS]:
        distance = distance_m(site.latitude, site.longitude, item.latitude, item.longitude)
        print(f"{distance:8.0f}m  {item.object_id[:24]:<24} {(item.type_name or '-')[:25]:<25} {item.display_name or '-'}")


async def run() -> int:
    if not SITES_PATH.is_file():
        print(f"Infrastructure-site artifact not found: {SITES_PATH}")
        print("Run: python tools/build_infrastructure_sites.py")
        return 2
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3
    bridge: MooseBridgeClient = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    site = await select_site(bridge, TheaterInfrastructureSites.load(SITES_PATH))
    format_site(site)
    survey = await bridge.survey_scenery(
        site.latitude,
        site.longitude,
        radius_m=SURVEY_RADIUS_M,
        max_results=MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    format_survey(site, survey)
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
        await asyncio.to_thread(input, "Inspect the site and cyan scenery objects in DCS F10, then press Enter ... ")
    finally:
        if drawn:
            await bridge.clear_debug_overlay(OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
