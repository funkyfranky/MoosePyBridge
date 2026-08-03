from __future__ import annotations

import asyncio
from typing import Any

from moosebridge import (
    AssetRequirement,
    AssetRole,
    MissionIntent,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveKind,
    OperationalPlan,
    OperationalPlanStatus,
    OperationalPosture,
    OwnershipPolicy,
    PlanPhase,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
    format_operational_plan_assessment,
    format_operational_plan_execution,
)
from moosebridge.protocol import BridgeCommand
from moosebridge.state import MooseBridgeState


def _bridge_with_goal() -> MooseBridgeClient:
    bridge = MooseBridgeClient(MooseBridgeServer())
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Town",
            name="Town",
            kind=ObjectiveKind.OPSZONE,
            control_object_id="OPSZONE:Town",
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        )
    )
    bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Capture Town",
            name="Capture Town",
            coalition="blue",
            action=StrategicGoalAction.CAPTURE,
            objective_id="OBJECTIVE:Town",
        )
    )
    return bridge


def _apply_force_state(
    bridge: MooseBridgeClient,
    *,
    air_stock: int = 2,
    ground_stock: int = 3,
    air_available: int | None = None,
    ground_available: int | None = None,
) -> None:
    air_available = air_stock if air_available is None else air_available
    ground_available = ground_stock if ground_available is None else ground_available
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [
                    {"object_id": "LEGION:Blue Wing", "coalition": "blue"},
                    {"object_id": "LEGION:Blue Brigade", "coalition": "blue"},
                    {"object_id": "LEGION:Red Wing", "coalition": "red"},
                ]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:Blue Strike",
                        "legion_id": "LEGION:Blue Wing",
                        "is_air": True,
                        "stock_asset_count": air_stock,
                        "available_asset_count": air_available,
                        "mission_types": ["BAI", "SEAD"],
                        "mission_performance": {"BAI": 80, "SEAD": 70},
                        "payloads_by_mission": {
                            "BAI": {"available_count": 1, "total_available": 2},
                            "SEAD": {"available_count": 1, "total_available": 2},
                        },
                    },
                    {
                        "object_id": "COHORT:Blue Armor",
                        "legion_id": "LEGION:Blue Brigade",
                        "is_ground": True,
                        "stock_asset_count": ground_stock,
                        "available_asset_count": ground_available,
                        "mission_types": ["CAPTUREZONE", "AIRDEFENSE", "AMMOSUPPLY"],
                    },
                    {
                        "object_id": "COHORT:Red Strike",
                        "legion_id": "LEGION:Red Wing",
                        "is_air": True,
                        "stock_asset_count": 20,
                        "available_asset_count": 20,
                        "mission_types": ["BAI", "SEAD"],
                    },
                ]
            },
        }
    )


def _intent(
    intent_id: str,
    mission_type: str,
    role: AssetRole,
    *,
    count: int = 1,
    category: str,
    require_payload: bool = False,
) -> MissionIntent:
    return MissionIntent(
        intent_id=intent_id,
        name=intent_id,
        auftrag_types=(mission_type,),
        target_object_id="OPSZONE:Town",
        asset_requirements=(
            AssetRequirement(
                requirement_id=f"REQ:{intent_id}",
                role=role,
                min_count=count,
                performer_categories=(category,),
                require_payload=require_payload,
            ),
        ),
    )


def test_plan_validation_allocates_cohort_stock_without_same_phase_double_counting() -> None:
    bridge = _bridge_with_goal()
    _apply_force_state(bridge, air_stock=2)
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Capture Town",
            name="Capture Town",
            goal_id="GOAL:Capture Town",
            coalition="blue",
            posture=OperationalPosture.BALANCED,
            phases=(
                PlanPhase(
                    phase_id="shape",
                    name="Shape",
                    intents=(
                        _intent("isolate", "BAI", AssetRole.COMBAT, count=2, category="AIR", require_payload=True),
                        _intent("suppress", "SEAD", AssetRole.SEAD, count=1, category="AIR", require_payload=True),
                    ),
                ),
            ),
        )
    )

    assessment = bridge.validate_operational_plan(plan)

    assert assessment.feasible is False
    assert assessment.requirements[0].allocations[0].count == 2
    assert assessment.requirements[1].available_count == 0
    assert assessment.requirements[1].shortfall == 1
    assert {issue.code for issue in assessment.errors} == {"asset_shortfall"}
    assert plan.status is OperationalPlanStatus.DRAFT


def test_plan_validation_does_not_allocate_requested_or_reserved_stock() -> None:
    bridge = _bridge_with_goal()
    _apply_force_state(bridge, air_stock=10, air_available=0)
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Reserved",
            name="Reserved assets",
            goal_id="GOAL:Capture Town",
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="shape",
                    name="Shape",
                    intents=(_intent("bai", "BAI", AssetRole.COMBAT, category="AIR", require_payload=True),),
                ),
            ),
        )
    )

    assessment = bridge.validate_operational_plan(plan)

    assert bridge.cohort("COHORT:Blue Strike").stock_asset_count == 10  # type: ignore[union-attr]
    assert assessment.requirements[0].available_count == 0
    assert assessment.requirements[0].shortfall == 1
    assert assessment.feasible is False


def test_plan_validation_reuses_assets_in_later_phases_and_can_be_approved() -> None:
    bridge = _bridge_with_goal()
    _apply_force_state(bridge, air_stock=1, ground_stock=2)
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Sequential",
            name="Sequential capture",
            goal_id="GOAL:Capture Town",
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="isolate",
                    name="Isolate",
                    intents=(_intent("bai", "BAI", AssetRole.COMBAT, category="AIR", require_payload=True),),
                ),
                PlanPhase(
                    phase_id="suppress",
                    name="Suppress",
                    depends_on=("isolate",),
                    intents=(_intent("sead", "SEAD", AssetRole.SEAD, category="AIR", require_payload=True),),
                ),
                PlanPhase(
                    phase_id="capture",
                    name="Capture",
                    depends_on=("suppress",),
                    intents=(_intent("capture-zone", "CAPTUREZONE", AssetRole.COMBAT, category="GROUND"),),
                ),
            ),
        )
    )

    assessment = bridge.validate_operational_plan(plan)
    approved = bridge.approve_operational_plan(plan)

    assert assessment.feasible is True
    assert [item.allocations[0].cohort_id for item in assessment.requirements] == [
        "COHORT:Blue Strike",
        "COHORT:Blue Strike",
        "COHORT:Blue Armor",
    ]
    assert approved.status is OperationalPlanStatus.APPROVED


def test_plan_registry_rejects_goal_coalition_mismatch() -> None:
    bridge = _bridge_with_goal()
    plan = OperationalPlan(
        plan_id="PLAN:Red",
        name="Wrong coalition",
        goal_id="GOAL:Capture Town",
        coalition="red",
        phases=(
            PlanPhase(
                phase_id="capture",
                name="Capture",
                intents=(_intent("capture", "CAPTUREZONE", AssetRole.COMBAT, category="GROUND"),),
            ),
        ),
    )

    try:
        bridge.add_operational_plan(plan)
    except ValueError as exc:
        assert "coalition" in str(exc)
    else:
        raise AssertionError("Mismatched plan coalition should be rejected")


def test_phase_dependencies_must_reference_preceding_phases() -> None:
    phase = PlanPhase(
        phase_id="first",
        name="First",
        depends_on=("later",),
        intents=(_intent("capture", "CAPTUREZONE", AssetRole.COMBAT, category="GROUND"),),
    )
    try:
        OperationalPlan(
            plan_id="PLAN:Invalid",
            name="Invalid",
            goal_id="GOAL:Capture Town",
            coalition="blue",
            phases=(phase,),
        )
    except ValueError as exc:
        assert "forward dependencies" in str(exc)
    else:
        raise AssertionError("Forward phase dependency should be rejected")


def test_operational_diagnostics_show_phase_allocations_and_shortfalls() -> None:
    bridge = _bridge_with_goal()
    _apply_force_state(bridge, air_stock=0)
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Diagnostic",
            name="Diagnostic",
            goal_id="GOAL:Capture Town",
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="shape",
                    name="Shape the battlespace",
                    intents=(_intent("isolate", "BAI", AssetRole.COMBAT, category="AIR"),),
                ),
            ),
        )
    )

    assessment = bridge.validate_operational_plan(plan)
    rendered = format_operational_plan_assessment(plan, assessment)

    assert "PLAN:Diagnostic goal=GOAL:Capture Town" in rendered
    assert "phase shape: Shape the battlespace" in rendered
    assert "required=1 available=0 shortfall=1" in rendered
    assert "ERROR asset_shortfall REQ:isolate" in rendered


class _ExecutionServer:
    def __init__(self, *, success: bool = True, final_owner: str = "blue") -> None:
        self.state = MooseBridgeState(connected=True)
        self.success = success
        self.final_owner = final_owner
        self.commands: list[BridgeCommand] = []
        self._mission_number = 0
        self._event_number = 0

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        self.commands.append(command)
        if command.action.startswith("auftrag.create_"):
            self._mission_number += 1
            return {
                "ok": True,
                "result": {
                    "action": command.action,
                    "auftrag_id": f"AUFTRAG:{self._mission_number}",
                },
            }
        return {"ok": True, "result": {"action": command.action}}

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        self._event_number += 1
        auftrag_id = str((filters or {}).get("auftrag_id") or "AUFTRAG:1")
        return {
            "type": "event",
            "id": f"event-{self._event_number}",
            "event": "auftrag.evaluated",
            "payload": {
                "auftrag_id": auftrag_id,
                "auftrag_type": "CAPTUREZONE",
                "status": "Done",
                "summary": {"success": self.success, "Ntargets0": 1, "Ntargets": 0},
            },
        }

    async def snapshot_opszones(self) -> dict[str, Any]:
        self.state.apply_message(
            {
                "type": "snapshot",
                "kind": "opszones",
                "payload": {
                    "opszones": [
                        {
                            "object_id": "OPSZONE:Town",
                            "object_type": "OPSZONE",
                            "owner_current_name": self.final_owner,
                            "is_contested": False,
                        }
                    ]
                },
            }
        )
        return {"ok": True, "result": {"kind": "opszones", "count": 1}}

    async def snapshot_airbases(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "airbases", "count": 0}}

    async def snapshot_territories(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "territories", "count": 0}}


def _executable_capture_plan(*, success: bool = True, final_owner: str = "blue") -> tuple[MooseBridgeClient, OperationalPlan]:
    bridge = MooseBridgeClient(_ExecutionServer(success=success, final_owner=final_owner))  # type: ignore[arg-type]
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Town",
            name="Town",
            kind=ObjectiveKind.OPSZONE,
            control_object_id="OPSZONE:Town",
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        )
    )
    bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Capture Town",
            name="Capture Town",
            coalition="blue",
            action=StrategicGoalAction.CAPTURE,
            objective_id="OBJECTIVE:Town",
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "commanders",
            "payload": {
                "commanders": [
                    {
                        "object_id": "COMMANDER:Blue Command",
                        "object_type": "COMMANDER",
                        "coalition": "blue",
                        "legion_ids": ["LEGION:Blue Brigade"],
                    }
                ]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {"legions": [{"object_id": "LEGION:Blue Brigade", "coalition": "blue"}]},
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:Blue Armor",
                        "legion_id": "LEGION:Blue Brigade",
                        "is_ground": True,
                        "available_asset_count": 3,
                        "mission_types": ["CAPTUREZONE"],
                    }
                ]
            },
        }
    )
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Capture Town",
            name="Capture Town",
            goal_id="GOAL:Capture Town",
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="seize",
                    name="Seize",
                    intents=(
                        MissionIntent(
                            intent_id="capture-zone",
                            name="Capture zone",
                            auftrag_types=("CAPTUREZONE",),
                            target_object_id="OPSZONE:Town",
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Ground assault",
                                    role=AssetRole.COMBAT,
                                    min_count=2,
                                    max_count=3,
                                    mission_types=("CAPTUREZONE",),
                                    performer_categories=("GROUND",),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    bridge.validate_operational_plan(plan)
    bridge.approve_operational_plan(plan)
    return bridge, plan


def test_execute_capture_plan_uses_commander_events_and_confirms_goal() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan()
        observed: list[str] = []

        execution = await bridge.execute_plan(plan, on_event=lambda event: observed.append(event.event))

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert plan.phases[0].status.value == "completed"
        assert execution.missions[0].status.value == "succeeded"
        assert bridge.strategic_goal("GOAL:Capture Town").status.value == "achieved"  # type: ignore[union-attr]
        command = bridge.server.commands[0]  # type: ignore[attr-defined]
        assert command.params["commander_id"] == "COMMANDER:Blue Command"
        assert command.params["required_assets_min"] == 2
        assert command.params["required_assets_max"] == 3
        assert observed == [
            "plan.started",
            "phase.started",
            "mission.submitted",
            "mission.succeeded",
            "phase.completed",
            "plan.completed",
        ]
        assert "status=completed" in format_operational_plan_execution(execution)

    asyncio.run(scenario())


def test_execute_capture_plan_blocks_after_required_auftrag_failure() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan(success=False)

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.BLOCKED
        assert plan.phases[0].status.value == "blocked"
        assert execution.missions[0].status.value == "failed"
        assert "without success" in (execution.blocked_reason or "")

    asyncio.run(scenario())


def test_optional_support_shortfall_is_skipped_without_blocking_capture() -> None:
    async def scenario() -> None:
        bridge, original = _executable_capture_plan()
        original.status = OperationalPlanStatus.CANCELLED
        capture_intent = original.phases[0].intents[0]
        plan = bridge.add_operational_plan(
            OperationalPlan(
                plan_id="PLAN:Capture With Optional Support",
                name="Capture with optional support",
                goal_id="GOAL:Capture Town",
                coalition="blue",
                phases=(
                    PlanPhase("seize", "Seize", (capture_intent,)),
                    PlanPhase(
                        "consolidate",
                        "Consolidate",
                        (
                            MissionIntent(
                                intent_id="air-defense",
                                name="Establish air defense",
                                auftrag_types=("AIRDEFENSE",),
                                target_object_id="OPSZONE:Town",
                                required=False,
                                asset_requirements=(
                                    AssetRequirement(
                                        requirement_id="REQ:Air defense",
                                        role=AssetRole.AIR_DEFENSE,
                                        mission_types=("AIRDEFENSE",),
                                        performer_categories=("GROUND",),
                                    ),
                                ),
                            ),
                        ),
                        depends_on=("seize",),
                    ),
                ),
            )
        )
        assessment = bridge.validate_operational_plan(plan)
        assert assessment.feasible is True
        bridge.approve_operational_plan(plan)

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert [mission.status.value for mission in execution.missions] == ["succeeded", "skipped"]
        assert len(bridge.server.commands) == 1  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_plan_auftrag_rejects_abstract_bai_opszone_target_before_execution() -> None:
    bridge, _ = _executable_capture_plan()
    invalid = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Invalid BAI",
            name="Invalid BAI",
            goal_id="GOAL:Capture Town",
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="isolate",
                    name="Isolate",
                    intents=(_intent("bai", "BAI", AssetRole.COMBAT, category="AIR"),),
                ),
            ),
        )
    )
    _apply_force_state(bridge)
    bridge.validate_operational_plan(invalid)
    bridge.approve_operational_plan(invalid)

    try:
        asyncio.run(bridge.execute_plan(invalid))
    except ValueError as exc:
        assert "requires a GROUP, UNIT or STATIC target" in str(exc)
    else:
        raise AssertionError("Abstract BAI OPSZONE target should be rejected")
