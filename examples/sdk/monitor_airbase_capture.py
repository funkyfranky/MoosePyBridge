"""Create a CAPTURE goal and wait for DCS to satisfy it."""

from __future__ import annotations

from example_support import open_example_session, run_example

from moosebridge import (
    ObjectiveKind,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
    format_strategic_goal,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
EVENT_TIMEOUT_SECONDS = 3600.0

AIRBASE_ID = "AIRBASE:Tutow"
OBJECTIVE_ID = "OBJECTIVE:Tutow"
OBJECTIVE_NAME = f"{AIRBASE_ID.removeprefix('AIRBASE:')} Airbase"
GOAL_ID = "GOAL:Blue capture Tutow"
GOAL_NAME = "Capture Tutow"
CAPTURING_COALITION = "blue"


def print_objective(objective: StrategicObjective) -> None:
    print(f"Objective : {objective.objective_id}")
    print(f"Name      : {objective.name}")
    print(f"Owner     : {objective.owner or 'unknown'}")
    print(f"Status    : {objective.status.value}")


async def run() -> int:
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge
    await bridge.snapshot_airbases()
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id=OBJECTIVE_ID,
            name=OBJECTIVE_NAME,
            kind=ObjectiveKind.AIRBASE,
            control_object_id=AIRBASE_ID,
            ownership_policy=OwnershipPolicy.DCS_MANAGED,
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=GOAL_ID,
            name=GOAL_NAME,
            coalition=CAPTURING_COALITION,
            action=StrategicGoalAction.CAPTURE,
            objective_id=OBJECTIVE_ID,
            priority=90,
        ),
        activate=True,
    )

    print("Initial state")
    print("=============")
    print_objective(objective)
    print()
    print(format_strategic_goal(goal))

    if goal.status is StrategicGoalStatus.ACHIEVED:
        print("\nGoal is already achieved in the current DCS state.")
        return 0

    print()
    print(f"Waiting for {CAPTURING_COALITION} to capture {AIRBASE_ID} ...")

    event = await bridge.wait_for_strategic_goal_event(
        GOAL_ID,
        timeout=EVENT_TIMEOUT_SECONDS,
    )

    print()
    print("Goal achieved")
    print("=============")
    print(f"Source : {event.source}")
    print(f"Time   : {event.mission_time}")
    print()
    print_objective(objective)
    print()
    print(format_strategic_goal(goal))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
