"""Run one conservative autonomous strategic cycle for blue."""

from __future__ import annotations

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    ConflictControllerConfig,
    GroundMobilityNetwork,
    MooseBridgeClient,
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    RuleBasedConflictController,
    StrategicObjective,
    format_operational_plan_assessment,
    format_operational_plan_execution,
    format_relationship,
    format_strategic_goal_portfolio,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 15.0
EXECUTE_SELECTED_PLAN = True
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH
_, THEATER_PATHS = load_example_theater(THEATER_PROFILE)
GROUND_MOBILITY_PATH = THEATER_PATHS.path("ground_mobility")

COALITION = "blue"
INTEL_ID = "INTEL:Blue Intel"


def add_scenario_objectives(bridge: MooseBridgeClient) -> None:
    """Register the small test mission's known strategic objectives."""

    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Town Fight",
            name="Town Fight",
            kind=ObjectiveKind.OPSZONE,
            control_object_id="OPSZONE:Town Fight",
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
            strategic_value=90,
            priority=90,
        )
    )
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Blue Camp Alpha",
            name="Blue Camp Alpha",
            kind=ObjectiveKind.OPSZONE,
            control_object_id="OPSZONE:Blue Camp Alpha",
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
            strategic_value=80,
            priority=80,
        )
    )
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Red Supply Depot",
            name="Red Supply Depot",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(
                ObjectiveComponent("STATIC:Red Depot Alpha Main", role="main storage", weight=0.5),
                ObjectiveComponent("STATIC:Red Depot Alpha Ammo", role="ammo storage", weight=0.3),
                ObjectiveComponent("STATIC:Red Depot Alpha Fuel", role="fuel storage", weight=0.2),
            ),
            strategic_value=70,
            priority=70,
        )
    )


async def run() -> int:
    ground_mobility = GroundMobilityNetwork.load(GROUND_MOBILITY_PATH)
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="blue-conflict-controller",
        display_name="Blue Conflict Controller",
        sdk_options={"ground_mobility": ground_mobility},
    )
    bridge = session.bridge
    add_scenario_objectives(bridge)
    controller = RuleBasedConflictController(
        bridge,
        ConflictControllerConfig(
            coalition=COALITION,
            intel_id=INTEL_ID,
            max_concurrent_goals=1,
        ),
    )

    mode = "EXECUTE" if EXECUTE_SELECTED_PLAN else "DRY RUN"
    print(f"Running one bounded blue strategic decision cycle [{mode}] ...")
    cycle = await controller.run_cycle(execute=EXECUTE_SELECTED_PLAN, on_event=print)
    print()
    print(format_relationship(bridge.relationship))
    print()
    print(format_strategic_goal_portfolio(cycle.portfolio))
    for selection in cycle.portfolio.selected:
        plan = bridge.operational_plan(selection.plan_id)
        assessment = bridge.plans.assessment(selection.plan_id)
        if plan is not None and assessment is not None:
            print()
            print(format_operational_plan_assessment(plan, assessment))
    if cycle.portfolio.selected and not EXECUTE_SELECTED_PLAN:
        print()
        print("Dry run: selected plans were not approved or submitted to DCS.")
        print("Set EXECUTE_SELECTED_PLAN = True to execute the selected plan.")
    for execution in cycle.executions:
        print()
        print(format_operational_plan_execution(execution))
    if cycle.issues:
        print()
        print("Controller issues:")
        for issue in cycle.issues:
            print(f"  {issue.objective_id} {issue.stage}: {issue.message}")
    return 0 if cycle.portfolio.selected and not cycle.issues else 2


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
