"""Generate scope-bounded strategic objectives for the running DCS mission."""

from __future__ import annotations

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    ConflictControllerConfig,
    RuleBasedConflictController,
    StrategicObjectiveGenerationConfig,
    StrategicVerificationRegistry,
    TheaterInfrastructureSites,
    TheaterRailwayInfrastructure,
    TheaterSettlements,
    TheaterTransportInfrastructure,
    format_strategic_goal_generation,
    format_strategic_goal_portfolio,
    format_strategic_objective_generation,
    format_relationship,
    format_strategic_scope,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
COALITION = "blue"
INTEL_ID = "INTEL:Blue Intel"
MAX_CONCURRENT_GOALS = 3
# False keeps the current diplomacy state. Set True only when this preview is
# explicitly allowed to declare war through the conflict controller.
MANAGE_RELATIONSHIP = False
OBJECTIVE_PREVIEW_LIMIT = 30
MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE = 10

THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH
_, THEATER_PATHS = load_example_theater(THEATER_PROFILE)
SETTLEMENTS_PATH = THEATER_PATHS.path("settlements")
TRANSPORT_PATH = THEATER_PATHS.path("transport_infrastructure")
RAILWAY_PATH = THEATER_PATHS.path("railway_infrastructure")
INFRASTRUCTURE_PATH = THEATER_PATHS.path("infrastructure_sites")
VERIFICATIONS_PATH = THEATER_PATHS.path("strategic_verifications")


async def run() -> int:
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge
    await bridge.refresh_global_picture()
    await bridge.refresh_diplomacy_state()
    scope = bridge.build_strategic_scope()
    result = bridge.generate_strategic_objectives(
        settlements=TheaterSettlements.load(SETTLEMENTS_PATH),
        transport=TheaterTransportInfrastructure.load(TRANSPORT_PATH),
        railway=TheaterRailwayInfrastructure.load(RAILWAY_PATH),
        infrastructure=TheaterInfrastructureSites.load(INFRASTRUCTURE_PATH),
        verifications=StrategicVerificationRegistry.load(VERIFICATIONS_PATH),
        config=StrategicObjectiveGenerationConfig(
            maximum_geographic_objectives_per_category_per_scope=(
                MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE
            ),
        ),
    )

    print(format_strategic_scope(scope))
    print()
    print(format_strategic_objective_generation(result))
    print("\nGenerated objectives")
    print("=" * 90)
    for objective in result.objectives[:OBJECTIVE_PREVIEW_LIMIT]:
        targetable = "yes" if objective.metadata.get("targetable") else "no"
        print(
            f"{objective.objective_id} owner={objective.owner or '-'} kind={objective.kind.value} "
            f"value={objective.strategic_value:.1f} targetable={targetable} name={objective.name}"
        )
    controller = RuleBasedConflictController(
        bridge,
        ConflictControllerConfig(
            coalition=COALITION,
            intel_id=INTEL_ID,
            controller_id=f"strategic-preview.{COALITION}",
            max_concurrent_goals=MAX_CONCURRENT_GOALS,
        ),
    )
    cycle = await controller.run_cycle(execute=False, manage_relationship=MANAGE_RELATIONSHIP)

    print()
    print(format_relationship(bridge.relationship))
    print()
    print(format_strategic_goal_generation(cycle.goal_generation))
    print()
    print(format_strategic_goal_portfolio(cycle.portfolio))
    if cycle.issues:
        print("\nPlanning issues")
        print("=" * 90)
        for issue in cycle.issues:
            print(f"{issue.objective_id} stage={issue.stage}: {issue.message}")
    if len(result.objectives) > OBJECTIVE_PREVIEW_LIMIT:
        print(f"\nObjective list shows {OBJECTIVE_PREVIEW_LIMIT}/{len(result.objectives)} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
