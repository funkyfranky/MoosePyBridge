"""Recommend one bounded blue/red strategic portfolio without executing it."""

from __future__ import annotations

import argparse

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    RelationshipState,
    StrategicDecisionConfig,
    StrategicObjectiveGenerationConfig,
    StrategicVerificationRegistry,
    TheaterContext,
    TheaterInfrastructureSites,
    TheaterRailwayInfrastructure,
    TheaterSettlements,
    TheaterTransportInfrastructure,
    format_bilateral_strategic_recommendation,
    format_conflict_readiness,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


# Editable example configuration.
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH.with_name("Caucasus_topography.json")
BLUE_INTEL_ID = "INTEL:Blue Intel"
RED_INTEL_ID = "INTEL:Red Intel"
MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE = 10
MAX_CONCURRENT_GOALS_PER_COALITION = 1
DEFENSE_DURATION_SECONDS = 1800.0
DESTROY_REQUIRED_DAMAGE = 0.70
REJECTION_PRINT_LIMIT = 12
RETAIN_DECISION_AUDIT = True
REQUIRE_WAR = True


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
        client_id="bilateral-strategy-recommendation-example",
        display_name="Bilateral Strategy Recommendation Example",
    )
    bridge = session.bridge
    readiness = await bridge.assess_conflict_readiness(
        theater=context,
        intel_ids={"blue": BLUE_INTEL_ID, "red": RED_INTEL_ID},
        objective_config=StrategicObjectiveGenerationConfig(
            maximum_geographic_objectives_per_category_per_scope=(
                MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE
            ),
        ),
        register_objectives=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    print(format_conflict_readiness(readiness))
    readiness.require_ready()

    await bridge.refresh_diplomacy_state()
    if REQUIRE_WAR and bridge.relationship.state is not RelationshipState.WAR:
        raise ValueError(
            "relationship must be war; run examples/sdk/declare_war.py or disable REQUIRE_WAR"
        )

    registry_counts_before = (
        len(bridge.strategic_objectives()),
        len(bridge.strategic_goals()),
        len(bridge.operational_plans()),
    )
    recommendation = await bridge.recommend_bilateral_strategy(
        readiness,
        config=StrategicDecisionConfig(
            max_concurrent_goals=MAX_CONCURRENT_GOALS_PER_COALITION,
            defense_duration_s=DEFENSE_DURATION_SECONDS,
            destroy_required_damage=DESTROY_REQUIRED_DAMAGE,
        ),
        retain_audit=RETAIN_DECISION_AUDIT,
    )
    registry_counts_after = (
        len(bridge.strategic_objectives()),
        len(bridge.strategic_goals()),
        len(bridge.operational_plans()),
    )
    if registry_counts_after != registry_counts_before:
        raise RuntimeError(
            "recommendation mode modified strategic registries: "
            f"{registry_counts_before} -> {registry_counts_after}"
        )

    print()
    print(
        format_bilateral_strategic_recommendation(
            recommendation,
            rejection_limit=REJECTION_PRINT_LIMIT,
        )
    )
    missing = [
        portfolio.coalition
        for portfolio in recommendation.portfolios
        if not portfolio.selected
    ]
    if missing:
        print(
            "\nNO SELECTION: "
            + ", ".join(missing)
            + ". Inspect deferred/rejected reason codes above."
        )
        return 1
    print("\nPASS: both coalitions selected a feasible recommendation; no AUFTRAG was created.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=THEATER_PROFILE)
    args = parser.parse_args()
    return run_example(lambda: run(args.profile))


if __name__ == "__main__":
    raise SystemExit(main())
