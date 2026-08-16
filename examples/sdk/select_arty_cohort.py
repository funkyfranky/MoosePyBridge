"""Select and execute the best of several artillery COHORTs.

The MooseBridge daemon and DCS mission are assumed to be running. Configure the
constants below; this example takes no command-line arguments.
"""

from __future__ import annotations

from collections.abc import Mapping

from example_support import open_example_session, run_example

from moosebridge import Auftrag_ARTY, MooseBridgeClient, StrategicMissionResolver
from moosebridge.control import DEFAULT_CONTROL_PORT

from test_arty_weapon_selection import coalition_ammunition, prepare_target_data


COALITION = "blue"
COHORT_IDS = (
    "COHORT:Paladin Laage",
    "COHORT:M270 Laage",
)
TARGET_ID = "GROUP:Ground-17"

CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 20.0
OUTCOME_TIMEOUT_SECONDS = 1_800.0

NSHOTS = 6
RADIUS_M = 75.0
SUBMIT_SELECTED_MISSION = True
WAIT_FOR_COMPLETION = True


def print_candidates(resolution: object) -> None:
    candidates = getattr(resolution, "fire_support_candidates", ())
    selected = getattr(resolution, "fire_support", None)
    timing = {
        (item.cohort_id, item.weapon_flag): item.estimated_time_to_effect_s
        for item in getattr(resolution, "assignments", ())
        if item.weapon_flag is not None
    }
    print("Qualified fire-support candidates")
    print("=================================")
    for rank, item in enumerate(candidates, start=1):
        marker = "SELECTED" if item is selected else "candidate"
        rounds = item.current_rounds if item.current_rounds is not None else "template"
        performance = item.mission_performance if item.mission_performance is not None else "-"
        eta = timing.get((item.cohort_id, item.weapon_flag))
        print(
            f"{rank:>2}. {item.cohort_id} [{marker}]\n"
            f"    type={item.dcs_type} flag={item.weapon_flag.name} "
            f"distance={item.distance_m / 1_000:.3f}km "
            f"range={item.minimum_m / 1_000:.3f}-{item.maximum_m / 1_000:.3f}km\n"
            f"    movement={item.required_relocation_m / 1_000:.3f}km "
            f"estimated_effect={eta:.0f}s "
            f"ammo={item.ammunition_source}:{rounds} "
            f"performance={performance} available={item.available_assets} "
            f"sync={'yes' if item.range_sync_required else 'no'}"
        )


async def run() -> int:
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="arty-cohort-selection-test",
        display_name="ARTY COHORT Selection Test",
    )
    bridge: MooseBridgeClient = session.bridge
    await bridge.refresh_legion_state()
    await bridge.snapshot_groups()
    await bridge.snapshot_units()
    await bridge.snapshot_statics()
    await bridge.snapshot_ammunition()

    cohorts = tuple(cohort for object_id in COHORT_IDS if (cohort := bridge.cohort(object_id)) is not None)
    missing = [object_id for object_id in COHORT_IDS if bridge.cohort(object_id) is None]
    if missing:
        print(f"Missing COHORTs: {', '.join(missing)}")
        return 1
    legion_ids = {cohort.legion_id for cohort in cohorts if cohort.legion_id}
    legions = tuple(legion for object_id in legion_ids if (legion := bridge.legion(object_id)) is not None)

    target_data = await prepare_target_data(bridge, TARGET_ID)
    resolution = StrategicMissionResolver().resolve(
        TARGET_ID,
        target_data=target_data,
        cohorts=cohorts,
        legions=legions,
        ammunition=coalition_ammunition(bridge),
        weapon_ranges=bridge.weapon_range_registry,
    )
    print_candidates(resolution)

    support = resolution.fire_support
    if resolution.selected.mission_type != "ARTY" or support is None:
        alternatives = ", ".join(item.mission_type for item in resolution.candidates)
        print(f"No ARTY assignment is feasible. Resolver candidates: {alternatives}")
        return 2
    print()
    print(f"Selected: {support.cohort_id} with {support.weapon_flag.name}")
    if not SUBMIT_SELECTED_MISSION:
        return 0

    if support.range_sync_required:
        ack = await bridge.set_cohort_weapon_range(
            support.cohort_id,
            support.weapon_flag,
            support.minimum_m,
            support.maximum_m,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        result = ack.get("result") if isinstance(ack.get("result"), Mapping) else {}
        print(
            "Range synchronized: "
            f"{float(result.get('minimum_m') or 0.0) / 1_000:.3f}-"
            f"{float(result.get('maximum_m') or 0.0) / 1_000:.3f}km"
        )

    auftrag = Auftrag_ARTY(target=TARGET_ID, nshots=NSHOTS, radius_m=RADIUS_M)
    auftrag.set_weapon_type(support.weapon_flag)
    auftrag.set_required_assets(1)
    ack = await bridge.add_auftrag(
        auftrag,
        coalition=COALITION,
        cohort=support.cohort_id,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    result = ack.get("result") if isinstance(ack.get("result"), Mapping) else {}
    print(f"AUFTRAG: {result.get('auftrag_id') or '-'} weapon_type={result.get('weapon_type')}")

    if WAIT_FOR_COMPLETION:
        outcome = await bridge.get_auftrag_summary(
            auftrag,
            timeout_s=OUTCOME_TIMEOUT_SECONDS,
            on_status=print,
        )
        print(f"MOOSE success: {outcome.success}")
        print(outcome.to_dict())
    return 0


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
