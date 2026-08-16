"""Validate M109/MLRS range selection and submit weapon-specific ARTY missions.

The MooseBridge daemon and DCS mission are assumed to be running. Configure the
COHORT and target ids below; this example takes no command-line arguments.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

from example_support import open_example_session, run_example

from moosebridge import (
    Auftrag_ARTY,
    FireSupportAssignment,
    MooseBridgeClient,
    StrategicMissionResolver,
    UnitAmmunition,
)
from moosebridge.control import DEFAULT_CONTROL_PORT
from moosebridge.strategic import normalize_coalition


@dataclass(frozen=True)
class ArtilleryTest:
    name: str
    cohort_id: str
    target_id: str
    nshots: int
    radius_m: float
    enabled: bool = True


TESTS = (
    ArtilleryTest(
        name="M109 conventional shells",
        cohort_id="COHORT:Paladin Laage",
        target_id="GROUP:Ground-17",
        nshots=6,
        radius_m=50,
    ),
    ArtilleryTest(
        name="M270 MLRS rockets",
        cohort_id="COHORT:M270 Laage",
        target_id="GROUP:Ground-17",
        nshots=6,
        radius_m=100,
    ),
)

COALITION = "blue"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 20.0
OUTCOME_TIMEOUT_SECONDS = 1_800.0

SUBMIT_MISSIONS = True
WAIT_FOR_COMPLETION = True


def target_payload(bridge: MooseBridgeClient, object_id: str) -> dict[str, object]:
    """Return the latest mirrored target payload."""

    prefix = object_id.partition(":")[0].upper()
    collection = {
        "GROUP": bridge.state.groups,
        "UNIT": bridge.state.units,
        "STATIC": bridge.state.statics,
    }.get(prefix)
    if collection is None:
        raise ValueError(f"Unsupported ARTY target type: {object_id}")
    payload = collection.get(object_id)
    if not isinstance(payload, Mapping):
        raise ValueError(f"Target is absent from the latest snapshot: {object_id}")
    return dict(payload)


def coalition_ammunition(bridge: MooseBridgeClient) -> tuple[UnitAmmunition, ...]:
    """Return observed ammunition belonging to the configured coalition."""

    selected = []
    for ammunition in bridge.state.ammunition_objects.values():
        group = bridge.state.groups.get(ammunition.group_id or "")
        unit = bridge.state.units.get(ammunition.unit_id)
        payload = group if isinstance(group, Mapping) else unit
        if isinstance(payload, Mapping) and normalize_coalition(payload.get("coalition")) == COALITION:
            selected.append(ammunition)
    return tuple(selected)


async def prepare_target_data(bridge: MooseBridgeClient, object_id: str) -> dict[str, object]:
    """Combine snapshot identity data with coordinates resolved by DCS."""

    payload = target_payload(bridge, object_id)
    coordinates = await bridge.coords(object_id, timeout=COMMAND_TIMEOUT_SECONDS)
    if coordinates.x is None or coordinates.z is None:
        raise ValueError(f"DCS returned no usable coordinates for {object_id}")
    payload.update(
        {
            "x": coordinates.x,
            "y": coordinates.y,
            "z": coordinates.z,
            "speed_mps": payload.get("speed_mps", payload.get("speed", 0)),
        }
    )
    return payload


def print_resolution(
    test: ArtilleryTest,
    cohort_type: str,
    fire_support: FireSupportAssignment,
) -> None:
    """Print the selected fire-support envelope."""

    print(f"Test             : {test.name}")
    print(f"COHORT           : {test.cohort_id}")
    print(f"DCS type         : {cohort_type}")
    print(f"Target           : {test.target_id}")
    print(f"Weapon flag      : {fire_support.weapon_flag.name} ({int(fire_support.weapon_flag)})")
    print(f"Distance         : {fire_support.distance_m / 1_000:.3f} km")
    print(
        f"Python profile   : {fire_support.minimum_m / 1_000:.3f}-"
        f"{fire_support.maximum_m / 1_000:.3f} km"
    )
    if fire_support.configured_maximum_m is None:
        configured = "missing"
    else:
        configured = (
            f"{float(fire_support.configured_minimum_m or 0.0) / 1_000:.3f}-"
            f"{fire_support.configured_maximum_m / 1_000:.3f} km"
        )
    print(f"MOOSE configured : {configured}")
    print(f"Range sync       : {'required' if fire_support.range_sync_required else 'not required'}")
    print(f"COHORT engage    : {fire_support.engage_range_m / 1_000:.3f} km")
    print(f"Mission range    : {fire_support.mission_range_m / 1_000:.3f} km")
    print(f"Required movement: {fire_support.required_relocation_m / 1_000:.3f} km")
    print(f"Range source     : {fire_support.range_source.value}")
    print(f"Ammunition source: {fire_support.ammunition_source}")
    print(
        "Current rounds   : "
        f"{fire_support.current_rounds if fire_support.current_rounds is not None else 'template'}"
    )
    print(
        f"Weapon ids       : {', '.join(fire_support.weapon_ids) if fire_support.weapon_ids else '-'}"
    )


async def run_test(
    bridge: MooseBridgeClient,
    resolver: StrategicMissionResolver,
    test: ArtilleryTest,
) -> bool:
    """Resolve and optionally execute one artillery test."""

    print()
    print(test.name)
    print("=" * len(test.name))
    cohort = bridge.cohort(test.cohort_id)
    if cohort is None:
        print(f"ERROR: COHORT not found: {test.cohort_id}")
        return False
    if not cohort.unit_type:
        print(f"ERROR: COHORT has no DCS unit type: {test.cohort_id}")
        return False
    legion = bridge.legion(cohort.legion_id or "")
    if legion is None:
        print(f"ERROR: Parent LEGION not found: {cohort.legion_id or '-'}")
        return False

    data = await prepare_target_data(bridge, test.target_id)
    resolution = resolver.resolve(
        test.target_id,
        target_data=data,
        cohorts=(cohort,),
        legions=(legion,),
        ammunition=coalition_ammunition(bridge),
        weapon_ranges=bridge.weapon_range_registry,
    )
    support = resolution.fire_support
    if resolution.selected.mission_type != "ARTY" or support is None:
        origin_x = cohort.x if cohort.x is not None else legion.x
        origin_z = cohort.z if cohort.z is not None else legion.z
        if origin_x is not None and origin_z is not None:
            distance = math.hypot(float(data["x"]) - origin_x, float(data["z"]) - origin_z)
            print(f"Distance: {distance / 1_000:.3f} km")
        print("ERROR: ARTY is not feasible for this COHORT/target combination.")
        print(f"Resolver candidates: {', '.join(item.mission_type for item in resolution.candidates)}")
        return False

    print_resolution(test, cohort.unit_type, support)
    if not SUBMIT_MISSIONS:
        print("Result           : validated only; submission disabled")
        return True

    if support.range_sync_required:
        sync_ack = await bridge.set_cohort_weapon_range(
            test.cohort_id,
            support.weapon_flag,
            support.minimum_m,
            support.maximum_m,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        sync_result = sync_ack.get("result") if isinstance(sync_ack.get("result"), Mapping) else {}
        previous_maximum = sync_result.get("previous_maximum_m")
        previous = "missing" if previous_maximum is None else f"{float(previous_maximum) / 1_000:.3f} km"
        print(
            f"MOOSE synchronized: {previous} -> "
            f"{float(sync_result.get('maximum_m') or 0.0) / 1_000:.3f} km"
        )

    auftrag = Auftrag_ARTY(
        target=test.target_id,
        nshots=test.nshots,
        radius_m=test.radius_m,
    )
    auftrag.set_weapon_type(support.weapon_flag)
    auftrag.set_required_assets(1)
    ack = await bridge.add_auftrag(
        auftrag,
        coalition=COALITION,
        cohort=test.cohort_id,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    result = ack.get("result") if isinstance(ack.get("result"), Mapping) else {}
    print(f"AUFTRAG          : {result.get('auftrag_id') or '-'}")
    print(f"ACK weapon_type  : {result.get('weapon_type')}")
    if result.get("weapon_type") != int(support.weapon_flag):
        print("ERROR: ACK weapon_type differs from the resolver selection.")
        return False

    if WAIT_FOR_COMPLETION:
        outcome = await bridge.get_auftrag_summary(
            auftrag,
            timeout_s=OUTCOME_TIMEOUT_SECONDS,
            on_status=print,
        )
        print(f"MOOSE success    : {outcome.success}")
        print(f"Summary          : {outcome.to_dict()}")
    return True


async def run() -> int:
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="arty-weapon-test",
        display_name="ARTY Weapon Selection Test",
    )
    bridge: MooseBridgeClient = session.bridge
    await bridge.refresh_legion_state()
    await bridge.snapshot_groups()
    await bridge.snapshot_units()
    await bridge.snapshot_statics()
    await bridge.snapshot_ammunition()

    resolver = StrategicMissionResolver()
    results = []
    for test in TESTS:
        if test.enabled:
            results.append(await run_test(bridge, resolver, test))

    if not results:
        print("No artillery tests are enabled.")
        return 1
    print()
    print(f"Completed: {sum(results)}/{len(results)} artillery test(s) passed.")
    return 0 if all(results) else 2


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
