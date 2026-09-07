"""Run bilateral strategic conflict until the current DCS mission ends."""

from __future__ import annotations

import argparse

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    BilateralConflictCoordinator,
    DEFAULT_THEATER_PROFILE_PATH,
    RelationshipState,
    StrategicCoordinatorConfig,
    StrategicCycleStatus,
    StrategicDecisionConfig,
    StrategicObjectiveGenerationConfig,
    StrategicVerificationRegistry,
    TheaterContext,
    TheaterInfrastructureSites,
    TheaterRailwayInfrastructure,
    TheaterSettlements,
    TheaterTransportInfrastructure,
    format_bilateral_conflict_run,
    format_conflict_readiness,
    format_relationship,
    format_strategic_coalition_cycle,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


# Editable example configuration.
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
MISSION_TIMEOUT_SECONDS = 3_600.0
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH.with_name("Caucasus_topography.json")
BLUE_INTEL_ID = "INTEL:Blue Intel"
RED_INTEL_ID = "INTEL:Red Intel"

# "manual" requires examples/sdk/declare_war.py (or another operator action)
# before this script starts. "automatic" declares war when needed.
WAR_START_MODE = "manual"
AUTOMATIC_WAR_DECLARING_COALITION = "blue"
AUTOMATIC_WAR_REASON = "Start mission-bound bilateral conflict control"

BLUE_DECISION_CADENCE_SECONDS = 60.0
RED_DECISION_CADENCE_SECONDS = 75.0
COMPLETED_COOLDOWN_SECONDS = 900.0
BLOCKED_COOLDOWN_SECONDS = 300.0
FAILED_COOLDOWN_SECONDS = 600.0
COORDINATOR_POLL_SECONDS = 2.0
MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE = 10
MAX_CONCURRENT_GOALS_PER_COALITION = 1
DEFENSE_DURATION_SECONDS = 1_800.0
DESTROY_REQUIRED_DAMAGE = 0.70
RETAIN_DECISION_AUDIT = True
PRINT_EXECUTION_EVENTS = True


def _load_context(profile_path) -> TheaterContext:
    theater, paths = load_example_theater(profile_path)
    return TheaterContext(
        theater_id=theater.theater_id,
        settlements=TheaterSettlements.load(paths.path("settlements")),
        transport=TheaterTransportInfrastructure.load(paths.path("transport_infrastructure")),
        railway=TheaterRailwayInfrastructure.load(paths.path("railway_infrastructure")),
        infrastructure=TheaterInfrastructureSites.load(paths.path("infrastructure_sites")),
        verifications=StrategicVerificationRegistry.load(
            paths.path("strategic_verifications")
        ).bind_theater(theater.theater_id),
    )


async def _prepare_relationship(bridge) -> None:
    mode = WAR_START_MODE.strip().casefold()
    if mode not in {"manual", "automatic"}:
        raise ValueError("WAR_START_MODE must be 'manual' or 'automatic'")

    await bridge.refresh_diplomacy_state()
    if bridge.relationship.state is RelationshipState.WAR:
        return
    if mode == "manual":
        raise ValueError(
            "relationship must be war in manual mode; run examples/sdk/declare_war.py"
        )

    bridge.declare_war(
        AUTOMATIC_WAR_DECLARING_COALITION,
        reason=AUTOMATIC_WAR_REASON,
    )
    # This snapshot coordinates clients in the current mission generation. It
    # is not restored into a later DCS mission.
    await bridge.persist_diplomacy_state()


async def run(profile_path=THEATER_PROFILE) -> int:
    context = _load_context(profile_path)
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="mission-conflict-coordinator-example",
        display_name="Mission Conflict Coordinator Example",
    )
    bridge = session.bridge
    objective_config = StrategicObjectiveGenerationConfig(
        maximum_geographic_objectives_per_category_per_scope=(
            MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE
        ),
    )

    async def assess_readiness():
        return await bridge.assess_conflict_readiness(
            theater=context,
            intel_ids={"blue": BLUE_INTEL_ID, "red": RED_INTEL_ID},
            objective_config=objective_config,
            register_objectives=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )

    readiness = await assess_readiness()
    print(format_conflict_readiness(readiness))
    readiness.require_ready()
    await _prepare_relationship(bridge)
    print()
    print(format_relationship(bridge.relationship))

    coordinator = BilateralConflictCoordinator(
        bridge,
        assess_readiness,
        StrategicCoordinatorConfig(
            blue_cadence_s=BLUE_DECISION_CADENCE_SECONDS,
            red_cadence_s=RED_DECISION_CADENCE_SECONDS,
            completed_cooldown_s=COMPLETED_COOLDOWN_SECONDS,
            blocked_cooldown_s=BLOCKED_COOLDOWN_SECONDS,
            failed_cooldown_s=FAILED_COOLDOWN_SECONDS,
            poll_interval_s=COORDINATOR_POLL_SECONDS,
            mission_timeout_s=MISSION_TIMEOUT_SECONDS,
            retain_audit=RETAIN_DECISION_AUDIT,
            decision=StrategicDecisionConfig(
                max_concurrent_goals=MAX_CONCURRENT_GOALS_PER_COALITION,
                defense_duration_s=DEFENSE_DURATION_SECONDS,
                destroy_required_damage=DESTROY_REQUIRED_DAMAGE,
            ),
        ),
    )

    def print_event(coalition, event) -> None:
        if PRINT_EXECUTION_EVENTS:
            print(f"[{coalition}] {event}")

    def print_cycle(cycle) -> None:
        print(format_strategic_coalition_cycle(cycle))

    print(
        "\nRunning bilateral conflict for the current mission generation. "
        "The process stops at mission end; press Ctrl+C for an operator stop."
    )
    result = await coordinator.run_until_mission_end(
        on_event=print_event,
        on_cycle=print_cycle,
    )
    print()
    print(format_bilateral_conflict_run(result))

    stopped = {
        coalition: bool(result.coalition(coalition))
        and result.coalition(coalition)[-1].status is StrategicCycleStatus.MISSION_CHANGED
        for coalition in ("blue", "red")
    }
    if not all(stopped.values()):
        raise RuntimeError(f"mission-bound coordinator stopped unexpectedly: {stopped}")

    print("\nPASS: mission end stopped both coalition workers without following the next mission.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=THEATER_PROFILE)
    args = parser.parse_args()
    return run_example(lambda: run(args.profile))


if __name__ == "__main__":
    raise SystemExit(main())
