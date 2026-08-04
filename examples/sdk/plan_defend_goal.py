"""Propose, validate, and execute a deadline-based OPSZONE defense plan."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import (
    ObjectiveKind,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
    format_operational_plan_assessment,
    format_operational_plan_execution,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
CLIENT_ID = "defend-planner-example"
CLIENT_DISPLAY_NAME = "Defend Planner Example"

COALITION = "blue"
INTEL_ID = "INTEL:Blue Intel"
OPSZONE_ID = "OPSZONE:Town Fight"
OBJECTIVE_ID = "OBJECTIVE:Town Fight"
GOAL_ID = "GOAL:Blue defend Town Fight"
PLAN_ID = "PLAN:Blue defend Town Fight"
DEFENSE_DURATION_SECONDS = 1_800.0

APPROVE_IF_FEASIBLE = True
EXECUTE_IF_APPROVED = True


async def main() -> int:
    control = MooseBridgeControlClient(
        CONTROL_HOST,
        CONTROL_PORT,
        client_id=CLIENT_ID,
        display_name=CLIENT_DISPLAY_NAME,
    )
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the MooseBridge daemon.")
        return 1

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    await bridge.snapshot_opszones()
    picture = await bridge.refresh_tactical_picture(COALITION, INTEL_ID)
    mission_time = bridge.state.clock.mission_time if bridge.state.clock else None
    if mission_time is None:
        print("DCS mission time is unavailable.")
        return 1

    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id=OBJECTIVE_ID,
            name="Town Fight",
            kind=ObjectiveKind.OPSZONE,
            control_object_id=OPSZONE_ID,
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        )
    )
    bridge.sync_strategic_objectives(source="defend.example")
    if objective.owner != COALITION:
        print(f"{OPSZONE_ID} is owned by {objective.owner or 'unknown'}, not {COALITION}.")
        return 2

    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=GOAL_ID,
            name="Defend Town Fight",
            coalition=COALITION,
            action=StrategicGoalAction.DEFEND,
            objective_id=OBJECTIVE_ID,
            priority=90,
            deadline_mission_time=mission_time + DEFENSE_DURATION_SECONDS,
        )
    )
    plan = bridge.add_operational_plan(
        bridge.propose_defend_plan(goal, picture, plan_id=PLAN_ID)
    )
    assessment = await bridge.refresh_and_validate_operational_plan(plan)
    if assessment.feasible and APPROVE_IF_FEASIBLE:
        bridge.approve_operational_plan(plan, reason="Defend example approved")

    print(format_operational_plan_assessment(plan, assessment))
    if plan.status.value == "approved" and EXECUTE_IF_APPROVED:
        print("\nExecuting DEFEND plan through the coalition COMMANDER ...")
        execution = await bridge.execute_plan(
            plan,
            mission_timeout_s=DEFENSE_DURATION_SECONDS + 600,
            on_event=print,
        )
        print()
        print(format_operational_plan_execution(execution))
    elif assessment.feasible and not APPROVE_IF_FEASIBLE:
        print("\nPlan is feasible but remains unapproved.")
    elif plan.status.value == "approved":
        print("\nPlan is approved but execution is disabled.")
    return 0 if assessment.feasible else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

