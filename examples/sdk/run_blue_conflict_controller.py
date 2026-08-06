"""Run one conservative autonomous strategic cycle for blue."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import (
    ConflictControllerConfig,
    MooseBridgeClient,
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    RuleBasedConflictController,
    StrategicObjective,
    format_operational_plan_execution,
    format_relationship,
    format_strategic_goal_portfolio,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 15.0
EXECUTE_SELECTED_PLAN = True

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


async def main() -> int:
    control = MooseBridgeControlClient(
        CONTROL_HOST,
        CONTROL_PORT,
        client_id="blue-conflict-controller",
        display_name="Blue Conflict Controller",
    )
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
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


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
