"""Propose, validate, and execute runway denial against a DCS airdrome."""

from __future__ import annotations

import uuid

from example_support import open_example_session, run_example

from moosebridge import (
    ObjectiveKind,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
    format_operational_plan_assessment,
    format_operational_plan_execution,
)
from moosebridge.control import DEFAULT_CONTROL_PORT
from moosebridge.pictures import TacticalPicture


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
CLIENT_ID = "runway-denial-planner-example"
CLIENT_DISPLAY_NAME = "Runway Denial Planner Example"

COALITION = "blue"
AIRBASE_ID = "AIRBASE:Tutow"
OBJECTIVE_ID = "OBJECTIVE:Tutow Airbase"
GOAL_ID = "GOAL:Blue deny Tutow runway"
PLAN_ID_PREFIX = "PLAN:Blue deny Tutow runway"

APPROVE_IF_FEASIBLE = True
EXECUTE_IF_APPROVED = True


async def run() -> int:
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id=CLIENT_ID,
        display_name=CLIENT_DISPLAY_NAME,
    )
    bridge = session.bridge
    await bridge.snapshot_airbases()
    airbase = bridge.state.airbases.get(AIRBASE_ID)
    if airbase is None:
        print(f"Airbase is unavailable: {AIRBASE_ID}")
        return 1
    if str(airbase.get("category") or "").lower() != "airdrome":
        print(f"BOMBRUNWAY requires an Airdrome; {AIRBASE_ID} is {airbase.get('category')!r}.")
        return 1

    mission_time = bridge.state.clock.mission_time if bridge.state.clock else None
    if mission_time is None:
        print("DCS mission time is unavailable.")
        return 1
    run_id = f"{mission_time:.3f}-{uuid.uuid4().hex[:8]}"

    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id=OBJECTIVE_ID,
            name="Tutow Airbase",
            kind=ObjectiveKind.AIRBASE,
            control_object_id=AIRBASE_ID,
            ownership_policy=OwnershipPolicy.DCS_MANAGED,
            strategic_value=80,
        )
    )
    bridge.sync_strategic_objectives(source="runway_denial.example")
    if objective.owner == COALITION:
        print(f"Refusing to deny a friendly runway: {AIRBASE_ID}")
        return 1

    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=GOAL_ID,
            name="Deny Tutow runway",
            coalition=COALITION,
            action=StrategicGoalAction.DISABLE,
            objective_id=objective.objective_id,
            priority=80,
        ),
        activate=True,
    )
    picture = TacticalPicture(coalition=COALITION, intel_id="INTEL:Not required", clock=bridge.state.clock)
    plan = bridge.add_operational_plan(
        bridge.propose_disable_plan(
            goal,
            picture,
            plan_id=f"{PLAN_ID_PREFIX}/RUN:{run_id}",
        )
    )
    assessment = await bridge.refresh_and_validate_operational_plan(plan)
    if assessment.feasible and APPROVE_IF_FEASIBLE:
        bridge.approve_operational_plan(plan, reason="Runway-denial example approved")

    print(format_operational_plan_assessment(plan, assessment))
    if not assessment.feasible:
        return 2
    if not APPROVE_IF_FEASIBLE:
        print("\nPlan is feasible but remains unapproved.")
        return 0
    if not EXECUTE_IF_APPROVED:
        print("\nPlan is approved but execution is disabled.")
        return 0

    print("\nExecuting runway denial through the coalition COMMANDER ...")
    execution = await bridge.execute_plan(plan, on_event=print)
    print()
    print(format_operational_plan_execution(execution))
    return 0 if goal.status.value == "achieved" else 2


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
