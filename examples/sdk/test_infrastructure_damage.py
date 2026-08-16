"""Damage one verified DCS scenery object and reassess its infrastructure site.

The MoosePyBridge daemon and a live DCS mission must be running. Review the
constants below before enabling the explosion. The script never changes the
saved verification baseline.
"""

from __future__ import annotations

import asyncio
from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (  # noqa: E402
    DEFAULT_THEATER_PROFILE_PATH,
    InfrastructureStateAssessment,
    StrategicVerificationRegistry,
    TheaterInfrastructureSites,
)
from moosebridge.control import DEFAULT_CONTROL_PORT  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH
THEATER, THEATER_PATHS = load_example_theater(THEATER_PROFILE)
SITES_PATH = THEATER_PATHS.path("infrastructure_sites")
VERIFICATIONS_PATH = THEATER_PATHS.path("strategic_verifications")

# Select a verified infrastructure site and one object from its observed DCS
# baseline. The defaults match the Recknitztal-Kaserne example.
SITE_ID = "MILITARY_SITE:88ed34fd505620ec"
TARGET_OBJECT_ID = "SCENERY:139943968"

# Destructive live-DCS action. Keep False until the selected object and power
# have been reviewed in the initial output.
ARM_EXPLOSION = True
EXPLOSION_POWER_KG_TNT = 500.0
EXPLOSION_DELAY_SECONDS = 5.0
POST_EXPLOSION_SETTLE_SECONDS = 10.0

SURVEY_RADIUS_M = 750.0
MAX_SCENERY_OBJECTS = 2000
ALLOW_REPEATED_DAMAGE = True


def format_percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def print_assessment(title: str, assessment: InfrastructureStateAssessment) -> None:
    print(title)
    print("=" * len(title))
    health = format_percent(assessment.health_min)
    if assessment.health_max != assessment.health_min:
        health = f"{health}..{format_percent(assessment.health_max)}"
    damage = format_percent(assessment.damage_min)
    if assessment.damage_max != assessment.damage_min:
        damage = f"{damage}..{format_percent(assessment.damage_max)}"
    print(f"State           : {assessment.state.value}")
    print(f"Health          : {health}")
    print(f"Damage          : {damage}")
    print(f"Evidence        : {'complete' if assessment.complete else 'bounded estimate'}")
    print(f"Baseline objects: {assessment.baseline_count}")
    print(
        "Objects         : "
        f"{assessment.intact_count} intact, {assessment.damaged_count} damaged, "
        f"{assessment.destroyed_count} destroyed, {assessment.unknown_count} unknown"
    )
    changed = tuple(item for item in assessment.objects if item.condition != "intact")
    if changed:
        print("Changed evidence:")
        for item in changed:
            print(
                f"  {item.object_id}: {item.condition} "
                f"health={format_percent(item.health)} source={item.source}"
            )


async def run() -> int:
    sites = TheaterInfrastructureSites.load(SITES_PATH)
    registry = StrategicVerificationRegistry.load(VERIFICATIONS_PATH).bind_theater(THEATER.theater_id)
    site = next((item for item in sites.sites if item.site_id == SITE_ID), None)
    if site is None:
        raise ValueError(f"Infrastructure site not found: {SITE_ID}")
    verification = registry.get(SITE_ID)
    if verification is None:
        print(f"No saved DCS verification exists for: {SITE_ID}")
        print("Create the immutable baseline first:")
        print("  1. Set OBJECT_ID to this site in examples/sdk/verify_scenery_representation.py.")
        print("  2. Keep SAVE_OBSERVED_BASELINE=True and run that script with DCS connected.")
        print("  3. Inspect the overlay and press Enter to save the baseline.")
        return 2
    if not verification.observed_objects:
        print(f"The saved verification has no observed-object baseline: {SITE_ID}")
        print("Run examples/sdk/verify_scenery_representation.py once before this damage test.")
        return 2
    baseline = next(
        (item for item in verification.observed_objects if item.object_id == TARGET_OBJECT_ID),
        None,
    )
    if baseline is None:
        print(f"Target object is not part of the saved baseline: {TARGET_OBJECT_ID}")
        print("Available baseline objects:")
        for item in verification.observed_objects:
            print(f"  {item.object_id} | {item.type_name or 'unknown type'}")
        return 2

    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge

    print("Infrastructure damage test")
    print("=" * 88)
    print(f"Site             : {site.name or site.site_id}")
    print(f"Site ID          : {site.site_id}")
    print(f"Target object    : {baseline.object_id}")
    print(f"DCS type         : {baseline.type_name or '-'}")
    print(f"Explosion        : {EXPLOSION_POWER_KG_TNT:g} kg TNT after {EXPLOSION_DELAY_SECONDS:g}s")
    print(f"Armed            : {ARM_EXPLOSION}")
    print()

    before = await bridge.assess_infrastructure_site(
        site,
        verification,
        radius_m=SURVEY_RADIUS_M,
        max_results=MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    print_assessment("Before explosion", before)
    target_before = next((item for item in before.objects if item.object_id == TARGET_OBJECT_ID), None)
    if target_before is None or target_before.condition == "unknown":
        print("\nTarget is not currently observable; explosion aborted.")
        return 2
    if target_before.condition != "intact" and not ALLOW_REPEATED_DAMAGE:
        print("\nTarget is already damaged or destroyed; explosion aborted.")
        print("Set ALLOW_REPEATED_DAMAGE=True only when that is intentional.")
        return 2

    survey = await bridge.survey_scenery(
        site.latitude,
        site.longitude,
        radius_m=SURVEY_RADIUS_M,
        max_results=MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    target = next((item for item in survey.objects if item.object_id == TARGET_OBJECT_ID), None)
    if target is None:
        print("\nTarget coordinates are unavailable in the current DCS survey; explosion aborted.")
        return 2
    print(f"Target position  : x={target.x:.3f} y={target.y:.3f} z={target.z:.3f}")

    if not ARM_EXPLOSION:
        print("\nDRY RUN: Set ARM_EXPLOSION=True after reviewing the selected site and object.")
        return 0

    cursor = await bridge.server.event_cursor()
    ack = await bridge.explode_point(
        target.x,
        target.z,
        EXPLOSION_POWER_KG_TNT,
        y=target.y,
        delay=EXPLOSION_DELAY_SECONDS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    print("\nExplosion scheduled")
    print("=" * 19)
    print(f"ACK              : {ack.get('id', '-')}")
    print(f"Position         : x={result.get('x', '-')} y={result.get('y', '-')} z={result.get('z', '-')}")
    await asyncio.sleep(EXPLOSION_DELAY_SECONDS + POST_EXPLOSION_SETTLE_SECONDS)

    history = await bridge.server.query_events("object.destroyed", after_id=cursor)
    events = tuple(item for item in history.get("events") or () if isinstance(item, dict))
    matching_events = tuple(
        event
        for event in events
        if str((event.get("payload") or {}).get("object_id") or "") == TARGET_OBJECT_ID
    )
    for event in events:
        bridge.state.apply_message(event)
    print(f"Destruction event: {'received' if matching_events else 'not received'}")

    after = await bridge.assess_infrastructure_site(
        site,
        verification,
        radius_m=SURVEY_RADIUS_M,
        max_results=MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    print()
    print_assessment("After explosion", after)
    print()
    print(f"State transition : {before.state.value} -> {after.state.value}")
    print(f"Damage transition: {format_percent(before.damage_min)} -> {format_percent(after.damage_min)} minimum")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
