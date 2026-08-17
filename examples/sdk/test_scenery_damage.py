"""Explode one verified fixed DCS scenery object and assess the result.

The MoosePyBridge daemon and a live DCS mission must be running. Configure a
normalized theater feature and an object from its saved scenery baseline below.
The script never changes the saved verification baseline.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from example_support import (
    load_example_scenery_feature,
    open_example_session,
    run_example,
)

from moosebridge import (  # noqa: E402
    InfrastructureStateAssessment,
    SceneryObjectSnapshot,
    StrategicVerificationRegistry,
)
from moosebridge.control import DEFAULT_CONTROL_PORT  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

# Copy a normalized Object ID from the web map. None searches all bundled
# theater profiles; set an explicit profile path only to resolve ambiguity.
#FEATURE_ID = "BRIDGE:Caucasus:4d482fb330eb"
FEATURE_ID = "MARITIME_SITE:faee9372f262ce51"
THEATER_PROFILE: str | Path | None = None

# Select one object from the saved observation baseline. None chooses the first
# live-queryable target component, then the first live-queryable baseline object.
# Batumi examples: SCENERY:85667046, SCENERY:71976691, SCENERY:71977578.
#TARGET_OBJECT_ID: str | None = "SCENERY:70254625"
TARGET_OBJECT_ID: str | None = "SCENERY:71978148"


# Destructive live-DCS action. Run once with False and review the exact target.
ARM_EXPLOSION = True
EXPLOSION_POWER_KG_TNT = 500.0
EXPLOSION_DELAY_SECONDS = 5.0
POST_EXPLOSION_SETTLE_SECONDS = 10.0
ALLOW_REPEATED_DAMAGE = False


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


def select_target(
    requested_id: str | None,
    baseline_ids: tuple[str, ...],
    target_component_ids: tuple[str, ...],
    resolved: tuple[SceneryObjectSnapshot, ...],
) -> SceneryObjectSnapshot | None:
    by_id = {item.object_id: item for item in resolved}
    if requested_id is not None:
        return by_id.get(requested_id)
    for object_id in (*target_component_ids, *baseline_ids):
        candidate = by_id.get(object_id)
        if candidate is not None and candidate.queryable:
            return candidate
    return None


def print_available_targets(resolved: tuple[SceneryObjectSnapshot, ...]) -> None:
    queryable = tuple(item for item in resolved if item.queryable)
    print("Live-queryable baseline objects:")
    if not queryable:
        print("  none")
        return
    for item in queryable:
        print(f"  {item.object_id} | {item.type_name or 'unknown type'}")


async def run() -> int:
    theater, theater_paths, feature = load_example_scenery_feature(FEATURE_ID, THEATER_PROFILE)
    verification_path = theater_paths.path("strategic_verifications")
    registry = StrategicVerificationRegistry.load(verification_path).bind_theater(theater.theater_id)
    verification = registry.get(feature.object_id)
    if verification is None or not verification.observed_objects:
        print(f"No saved DCS scenery baseline exists for: {feature.object_id}")
        print("Run examples/sdk/verify_scenery_representation.py first with:")
        print(f'  OBJECT_ID = "{feature.object_id}"')
        return 2

    baseline_by_id = {item.object_id: item for item in verification.observed_objects}
    if TARGET_OBJECT_ID is not None and TARGET_OBJECT_ID not in baseline_by_id:
        print(f"Target object is not part of the saved baseline: {TARGET_OBJECT_ID}")
        print("Available baseline objects:")
        for item in verification.observed_objects:
            print(f"  {item.object_id} | {item.type_name or 'unknown type'}")
        return 2

    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge
    baseline_ids = tuple(baseline_by_id)
    positions = {
        item.object_id: (item.latitude, item.longitude)
        for item in verification.observed_objects
        if item.latitude is not None and item.longitude is not None
    }
    resolution = await bridge.resolve_scenery_objects(
        baseline_ids,
        positions=positions,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    target = select_target(
        TARGET_OBJECT_ID,
        baseline_ids,
        tuple(item.object_id for item in verification.target_components),
        resolution.objects,
    )

    print("Scenery damage test")
    print("=" * 96)
    print(f"Theater          : {theater.theater_id}")
    print(f"Feature          : {feature.name or feature.object_id}")
    print(f"Feature ID       : {feature.object_id}")
    print(f"Category         : {feature.category.replace('_', ' ')}")
    print(f"Saved baseline   : {len(baseline_ids)} object(s)")
    print(f"Live queryable   : {sum(item.queryable for item in resolution.objects)}/{len(baseline_ids)}")
    print(f"Explosion        : {EXPLOSION_POWER_KG_TNT:g} kg TNT after {EXPLOSION_DELAY_SECONDS:g}s")
    print(f"Armed            : {ARM_EXPLOSION}")

    if target is None:
        print("\nNo live-queryable target could be selected; explosion aborted.")
        print_available_targets(resolution.objects)
        return 2
    if not target.queryable:
        print(f"\nSelected target is not live-queryable in DCS: {target.object_id}")
        print("Its saved position is useful for reference, but not for a reliable damage comparison.")
        print_available_targets(resolution.objects)
        return 2

    print(f"Target object    : {target.object_id}")
    print(f"DCS type         : {target.type_name or '-'}")
    print(f"Target life      : {target.life if target.life is not None else 'unavailable'}")
    print(f"Target position  : x={target.x:.3f} y={target.y:.3f} z={target.z:.3f}")
    print()

    before = await bridge.assess_scenery_verification(
        feature,
        verification,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    print_assessment("Before explosion", before)
    target_before = next((item for item in before.objects if item.object_id == target.object_id), None)
    if target_before is None or target_before.condition == "unknown":
        print("\nTarget has no reliable current state; explosion aborted.")
        return 2
    if target_before.condition != "intact" and not ALLOW_REPEATED_DAMAGE:
        print("\nTarget is already damaged or destroyed; explosion aborted.")
        print("Set ALLOW_REPEATED_DAMAGE=True only when that is intentional.")
        return 2

    if not ARM_EXPLOSION:
        print("\nDRY RUN: Set ARM_EXPLOSION=True after reviewing the selected feature and object.")
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
        if str((event.get("payload") or {}).get("object_id") or "") == target.object_id
    )
    for event in events:
        bridge.state.apply_message(event)
    print(f"Destruction event: {'received' if matching_events else 'not received'}")

    after = await bridge.assess_scenery_verification(
        feature,
        verification,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    print()
    print_assessment("After explosion", after)
    target_after = next((item for item in after.objects if item.object_id == target.object_id), None)
    print()
    print(f"State transition : {before.state.value} -> {after.state.value}")
    print(f"Damage transition: {format_percent(before.damage_min)} -> {format_percent(after.damage_min)} minimum")
    if target_after is not None:
        print(
            f"Target transition: {target_before.condition} ({format_percent(target_before.health)}) -> "
            f"{target_after.condition} ({format_percent(target_after.health)})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
