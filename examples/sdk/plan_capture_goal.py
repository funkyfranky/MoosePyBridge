"""Build and validate a phased operational plan for one CAPTURE goal."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import (
    AssetRequirement,
    AssetRole,
    MissionIntent,
    ObjectiveKind,
    OperationalPlan,
    OperationalPlanProvenance,
    OperationalPosture,
    OwnershipPolicy,
    PlanPhase,
    PlanSourceType,
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
CLIENT_ID = "capture-planner-example"
CLIENT_DISPLAY_NAME = "Capture Planner Example"

COALITION = "blue"
OPSZONE_ID = "OPSZONE:Town Fight"
ISOLATION_TARGET_ID = "GROUP:Ground-1"
OBJECTIVE_ID = "OBJECTIVE:Town Fight"
GOAL_ID = "GOAL:Blue capture Town Fight"
PLAN_ID = "PLAN:Blue capture Town Fight"

# Approval records a command decision only. It does not create DCS AUFTRAGs.
APPROVE_IF_FEASIBLE = True
EXECUTE_IF_APPROVED = True


def requirement(
    requirement_id: str,
    role: AssetRole,
    mission_type: str,
    category: str,
    *,
    count: int = 1,
    require_payload: bool = False,
) -> AssetRequirement:
    return AssetRequirement(
        requirement_id=requirement_id,
        role=role,
        min_count=count,
        mission_types=(mission_type,),
        performer_categories=(category,),
        require_payload=require_payload,
    )


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

    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id=OBJECTIVE_ID,
            name="Town Fight",
            kind=ObjectiveKind.OPSZONE,
            control_object_id=OPSZONE_ID,
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        )
    )
    bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=GOAL_ID,
            name="Capture Town Fight",
            coalition=COALITION,
            action=StrategicGoalAction.CAPTURE,
            objective_id=OBJECTIVE_ID,
            priority=90,
        )
    )

    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id=PLAN_ID,
            name="Capture Town Fight",
            goal_id=GOAL_ID,
            coalition=COALITION,
            posture=OperationalPosture.BALANCED,
            provenance=OperationalPlanProvenance(
                source_type=PlanSourceType.OPERATOR,
                source_id="examples.sdk.plan_capture_goal",
                picture_mission_time=bridge.state.clock.mission_time if bridge.state.clock else None,
                rationale="Demonstrate a phased capture plan through the Python SDK.",
            ),
            phases=(
                PlanPhase(
                    phase_id="isolate",
                    name="Isolate the objective",
                    intents=(
                        MissionIntent(
                            intent_id="interdict-defenders",
                            name="Interdict defending forces",
                            auftrag_types=("BAI",),
                            target_object_id=ISOLATION_TARGET_ID,
                            asset_requirements=(
                                requirement(
                                    "REQ:Strike",
                                    AssetRole.COMBAT,
                                    "BAI",
                                    "AIR",
                                    require_payload=True,
                                ),
                            ),
                        ),
                    ),
                ),
                PlanPhase(
                    phase_id="seize",
                    name="Seize the objective",
                    depends_on=("isolate",),
                    intents=(
                        MissionIntent(
                            intent_id="capture-zone",
                            name="Capture the OPSZONE",
                            auftrag_types=("CAPTUREZONE",),
                            target_object_id=OPSZONE_ID,
                            asset_requirements=(
                                requirement(
                                    "REQ:Ground assault",
                                    AssetRole.COMBAT,
                                    "CAPTUREZONE",
                                    "GROUND",
                                    count=2,
                                ),
                            ),
                        ),
                    ),
                ),
                PlanPhase(
                    phase_id="consolidate",
                    name="Consolidate control",
                    depends_on=("seize",),
                    intents=(
                        MissionIntent(
                            required=False,
                            intent_id="establish-air-defense",
                            name="Establish local air defense",
                            auftrag_types=("AIRDEFENSE",),
                            target_object_id=OPSZONE_ID,
                            asset_requirements=(
                                requirement(
                                    "REQ:Air defense",
                                    AssetRole.AIR_DEFENSE,
                                    "AIRDEFENSE",
                                    "GROUND",
                                ),
                            ),
                        ),
                        MissionIntent(
                            required=False,
                            intent_id="sustain-force",
                            name="Supply the occupying force",
                            auftrag_types=("AMMOSUPPLY",),
                            target_object_id=OPSZONE_ID,
                            asset_requirements=(
                                requirement(
                                    "REQ:Logistics",
                                    AssetRole.LOGISTICS,
                                    "AMMOSUPPLY",
                                    "GROUND",
                                ),                                                        
                            ),                            
                        ),
                    ),
                ),
            ),
        )
    )

    assessment = await bridge.refresh_and_validate_operational_plan(plan)
    if assessment.feasible and APPROVE_IF_FEASIBLE:
        bridge.approve_operational_plan(plan)

    print(format_operational_plan_assessment(plan, assessment))
    if assessment.feasible and not APPROVE_IF_FEASIBLE:
        print("\nPlan is feasible but remains unapproved. Set APPROVE_IF_FEASIBLE = True to approve it.")
    elif plan.status.value == "approved" and EXECUTE_IF_APPROVED:
        print("\nExecuting approved plan through the coalition COMMANDER ...")
        execution = await bridge.execute_plan(plan, on_event=print)
        print()
        print(format_operational_plan_execution(execution))
    elif plan.status.value == "approved":
        print("\nPlan is approved but not executed. Set EXECUTE_IF_APPROVED = True to execute it.")
    return 0 if assessment.feasible else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
