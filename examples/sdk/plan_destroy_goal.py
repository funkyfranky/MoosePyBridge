"""Propose, validate, and execute a weighted strategic DESTROY plan."""

from __future__ import annotations

import uuid

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    GroundMobilityNetwork,
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
    format_operational_plan_assessment,
    format_operational_plan_execution,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH
_, THEATER_PATHS = load_example_theater(THEATER_PROFILE)
GROUND_MOBILITY_PATH = THEATER_PATHS.path("ground_mobility")
CLIENT_ID = "destroy-planner-example"
CLIENT_DISPLAY_NAME = "Destroy Planner Example"

COALITION = "blue"
INTEL_ID = "INTEL:Blue Intel"
OBJECTIVE_ID = "OBJECTIVE:Red Supply Depot"
GOAL_ID = "GOAL:Blue damage Red Supply Depot"
PLAN_ID_PREFIX = "PLAN:Blue damage Red Supply Depot"

# Replace these ids with objects from the DCS mission. Weights describe each
# component's share of the objective's total functional health.
COMPONENTS = (
    ObjectiveComponent("STATIC:Red Depot Alpha Main", role="main storage", weight=0.5),
    ObjectiveComponent("STATIC:Red Depot Alpha Ammo", role="ammo storage", weight=0.3),
    ObjectiveComponent("STATIC:Red Depot Alpha Fuel", role="fuel storage", weight=0.2),
)
REQUIRED_DAMAGE = 0.7
MAX_STRIKE_ROUNDS = 3

APPROVE_IF_FEASIBLE = True
EXECUTE_IF_APPROVED = True


async def run() -> int:
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id=CLIENT_ID,
        display_name=CLIENT_DISPLAY_NAME,
        sdk_options={"ground_mobility": GroundMobilityNetwork.load(GROUND_MOBILITY_PATH)},
    )
    bridge = session.bridge
    await bridge.snapshot_statics()
    mission_time = bridge.state.clock.mission_time if bridge.state.clock else None
    if mission_time is None:
        print("DCS mission time is unavailable.")
        return 1
    run_id = f"{mission_time:.3f}-{uuid.uuid4().hex[:8]}"

    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id=OBJECTIVE_ID,
            name="Red Supply Depot",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=COMPONENTS,
            strategic_value=80,
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=GOAL_ID,
            name="Damage Red Supply Depot",
            coalition=COALITION,
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
            priority=80,
            required_damage=REQUIRED_DAMAGE,
        ),
        activate=True,
    )

    for strike_round in range(1, MAX_STRIKE_ROUNDS + 1):
        picture = await bridge.refresh_tactical_picture(COALITION, INTEL_ID)
        plan_id = f"{PLAN_ID_PREFIX}/RUN:{run_id}/ROUND:{strike_round}"
        plan = bridge.add_operational_plan(
            bridge.propose_destroy_plan(goal, picture, plan_id=plan_id)
        )
        assessment = await bridge.refresh_and_validate_operational_plan(plan)
        if assessment.feasible and APPROVE_IF_FEASIBLE:
            bridge.approve_operational_plan(
                plan,
                reason=f"Destroy example strike round {strike_round} approved",
            )

        print(format_operational_plan_assessment(plan, assessment))
        if not assessment.feasible:
            return 2
        if not APPROVE_IF_FEASIBLE:
            print("\nPlan is feasible but remains unapproved.")
            return 0
        if not EXECUTE_IF_APPROVED:
            print("\nPlan is approved but execution is disabled.")
            return 0

        print(f"\nExecuting DESTROY strike round {strike_round} through the coalition COMMANDER ...")
        execution = await bridge.execute_plan(plan, on_event=print)
        print()
        print(format_operational_plan_execution(execution))
        if goal.status.value == "achieved":
            return 0
        if strike_round < MAX_STRIKE_ROUNDS:
            print("\nDamage threshold not reached. Replanning against damaged components ...\n")

    print(f"\nDamage threshold was not reached after {MAX_STRIKE_ROUNDS} approved strike rounds.")
    return 2


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
