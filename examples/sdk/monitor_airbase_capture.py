"""Wait for DCS to capture one airbase and show the strategic result."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import ObjectiveKind, OwnershipPolicy, StrategicObjective
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
EVENT_TIMEOUT_SECONDS = 3600.0

AIRBASE_ID = "AIRBASE:Tutow"
OBJECTIVE_ID = "OBJECTIVE:Tutow"
OBJECTIVE_NAME = f"{AIRBASE_ID.removeprefix('AIRBASE:')} Airbase"


def print_objective(objective: StrategicObjective) -> None:
    print(f"Objective : {objective.objective_id}")
    print(f"Name      : {objective.name}")
    print(f"Owner     : {objective.owner or 'unknown'}")
    print(f"Status    : {objective.status.value}")


async def main() -> int:
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the MooseBridge daemon.")
        return 1

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
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

    print("Initial state")
    print("=============")
    print_objective(objective)
    print()
    print(f"Waiting for DCS to change control of {AIRBASE_ID} ...")

    event = await bridge.wait_for_objective_event(
        "objective.control_changed",
        objective_id=OBJECTIVE_ID,
        timeout=EVENT_TIMEOUT_SECONDS,
    )

    print()
    print("Control changed")
    print("===============")
    print(f"Source    : {event.source}")
    print(f"Transition: {event.previous_owner or 'unknown'} -> {event.owner or 'unknown'}")
    print_objective(objective)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
