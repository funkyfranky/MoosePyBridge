"""Run a bounded recurring strategic conflict for both coalitions."""

from __future__ import annotations

import argparse
import asyncio

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    BilateralConflictCoordinator,
    DEFAULT_THEATER_PROFILE_PATH,
    RelationshipState,
    StrategicCoordinatorConfig,
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
CYCLES_PER_COALITION = 3
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
REQUIRE_WAR = True
REQUIRE_AUFTRAG_PER_COALITION = True


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


async def run(profile_path=THEATER_PROFILE) -> int:
    context = _load_context(profile_path)
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="bilateral-conflict-coordinator-example",
        display_name="Bilateral Conflict Coordinator Example",
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

    await bridge.refresh_diplomacy_state()
    if REQUIRE_WAR and bridge.relationship.state is not RelationshipState.WAR:
        raise ValueError(
            "relationship must be war; run examples/sdk/declare_war.py or disable REQUIRE_WAR"
        )

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
        print(f"[{coalition}] {event}")

    def print_cycle(cycle) -> None:
        print(
            f"[{cycle.coalition}] cycle {cycle.cycle_number} "
            f"finished: {cycle.status.value}, attempts={len(cycle.attempts)}"
        )
        if cycle.reason:
            print(f"[{cycle.coalition}] reason: {cycle.reason}")

    print(
        "\nRunning bounded bilateral conflict coordination "
        f"({CYCLES_PER_COALITION} cycles per coalition). Press Ctrl+C to stop."
    )
    result = await coordinator.run(
        cycles_per_coalition=CYCLES_PER_COALITION,
        on_event=print_event,
        on_cycle=print_cycle,
    )
    print()
    print(format_bilateral_conflict_run(result))

    failures: list[str] = []
    for coalition in ("blue", "red"):
        cycles = result.coalition(coalition)
        if len(cycles) != CYCLES_PER_COALITION:
            failures.append(
                f"{coalition}: received {len(cycles)}/{CYCLES_PER_COALITION} cycles"
            )
        if REQUIRE_AUFTRAG_PER_COALITION and not any(
            attempt.execution is not None and attempt.execution.missions
            for cycle in cycles
            for attempt in cycle.attempts
        ):
            failures.append(f"{coalition}: no coordinator execution created an AUFTRAG")
    if failures:
        raise RuntimeError("; ".join(failures))

    print("\nPASS: both coalitions completed the bounded recurring conflict run.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=THEATER_PROFILE)
    args = parser.parse_args()
    return run_example(lambda: run(args.profile))


if __name__ == "__main__":
    raise SystemExit(main())
