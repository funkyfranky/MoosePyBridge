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
    PlanPhaseStatus,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
    format_operational_plan_assessment,
    format_operational_plan_execution,
)
from moosebridge.protocol import BridgeCommand
from moosebridge.state import MooseBridgeState


def _bridge_with_goal(server: Any | None = None) -> MooseBridgeClient:
    bridge = MooseBridgeClient(server or MooseBridgeServer())
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
    def __init__(
        self,
        *,
        success: bool | list[bool] = True,
        final_owner: str = "blue",
        group_ids: tuple[str, ...] = (),
        opszone_ids: tuple[str, ...] = ("OPSZONE:Town",),
    ) -> None:
        self.state = MooseBridgeState(connected=True)
        self.success = success
        self.final_owner = final_owner
        self.group_ids = group_ids
        self.opszone_ids = opszone_ids
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
        mission_number = int(auftrag_id.partition(":")[2])
        success = self.success[mission_number - 1] if isinstance(self.success, list) else self.success
        return {
            "type": "event",
            "id": f"event-{self._event_number}",
            "event": "auftrag.evaluated",
            "payload": {
                "auftrag_id": auftrag_id,
                "auftrag_type": "CAPTUREZONE",
                "status": "Done",
                "summary": {"success": success, "Ntargets0": 1, "Ntargets": 0},
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
                            "object_id": object_id,
                            "object_type": "OPSZONE",
                            "owner_current_name": self.final_owner if object_id == "OPSZONE:Town" else "red",
                            "is_contested": False,
                        }
                        for object_id in self.opszone_ids
                    ]
                },
            }
        )
        return {"ok": True, "result": {"kind": "opszones", "count": 1}}

    async def snapshot_groups(self) -> dict[str, Any]:
        self.state.apply_message(
            {
                "type": "snapshot",
                "kind": "groups",
                "payload": {
                    "groups": [
                        {"object_id": object_id, "alive": True, "active": True}
                        for object_id in self.group_ids
                    ]
                },
            }
        )
        return {"ok": True, "result": {"kind": "groups", "count": len(self.group_ids)}}

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


def test_target_preflight_blocks_before_first_auftrag_when_object_is_missing() -> None:
    bridge, original = _executable_capture_plan()
    original.status = OperationalPlanStatus.CANCELLED
    _apply_force_state(bridge)
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Missing target",
            name="Missing target",
            goal_id="GOAL:Capture Town",
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="isolate",
                    name="Isolate",
                    intents=(
                        MissionIntent(
                            intent_id="bai",
                            name="BAI",
                            auftrag_types=("BAI",),
                            target_object_id="GROUP:Missing",
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Strike",
                                    role=AssetRole.COMBAT,
                                    mission_types=("BAI",),
                                    performer_categories=("AIR",),
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

    try:
        asyncio.run(bridge.execute_plan(plan))
    except ValueError as exc:
        assert str(exc) == "operational target preflight could not find: GROUP:Missing"
    else:
        raise AssertionError("Missing target should fail preflight")

    assert plan.status is OperationalPlanStatus.APPROVED
    assert not [command for command in bridge.server.commands if command.action.startswith("auftrag.create_")]  # type: ignore[attr-defined]


def test_blocked_plan_retry_preserves_completed_phases_and_attempt_history() -> None:
    async def scenario() -> None:
        server = _ExecutionServer(
            success=[True, False, True],
            group_ids=("GROUP:Defenders",),
            opszone_ids=("OPSZONE:Town", "OPSZONE:Town East"),
        )
        bridge = _bridge_with_goal(server)
        _apply_force_state(bridge)
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
                            "legion_ids": ["LEGION:Blue Wing", "LEGION:Blue Brigade"],
                        }
                    ]
                },
            }
        )
        plan = bridge.add_operational_plan(
            OperationalPlan(
                plan_id="PLAN:Retry Capture",
                name="Retry capture",
                goal_id="GOAL:Capture Town",
                coalition="blue",
                phases=(
                    PlanPhase(
                        "isolate",
                        "Isolate",
                        (
                            MissionIntent(
                                "bai",
                                "BAI",
                                ("BAI",),
                                (
                                    AssetRequirement(
                                        "REQ:Strike",
                                        AssetRole.COMBAT,
                                        mission_types=("BAI",),
                                        performer_categories=("AIR",),
                                    ),
                                ),
                                target_object_id="GROUP:Defenders",
                            ),
                        ),
                    ),
                    PlanPhase(
                        "seize",
                        "Seize",
                        (
                            MissionIntent(
                                "capture-zone",
                                "Capture zone",
                                ("CAPTUREZONE",),
                                (
                                    AssetRequirement(
                                        "REQ:Ground assault",
                                        AssetRole.COMBAT,
                                        mission_types=("CAPTUREZONE",),
                                        performer_categories=("GROUND",),
                                    ),
                                ),
                                target_object_id="OPSZONE:Town",
                            ),
                        ),
                        depends_on=("isolate",),
                    ),
                ),
            )
        )
        bridge.validate_operational_plan(plan)
        bridge.approve_operational_plan(plan)

        first = await bridge.execute_plan(plan)

        assert first.status is OperationalPlanStatus.BLOCKED
        assert [phase.status for phase in plan.phases] == [PlanPhaseStatus.COMPLETED, PlanPhaseStatus.BLOCKED]

        bridge.prepare_plan_retry(
            plan,
            target_overrides={("seize", "capture-zone"): "OPSZONE:Town East"},
            allowed_legion_overrides={
                ("seize", "capture-zone", "REQ:Ground assault"): ("LEGION:Blue Brigade",)
            },
            allowed_cohort_overrides={
                ("seize", "capture-zone", "REQ:Ground assault"): ("COHORT:Blue Armor",)
            },
        )

        assert plan.status is OperationalPlanStatus.DRAFT
        assert [phase.status for phase in plan.phases] == [PlanPhaseStatus.COMPLETED, PlanPhaseStatus.PENDING]
        assert bridge.plans.assessment(plan.plan_id) is None
        retried_intent = plan.phases[1].intents[0]
        retried_requirement = retried_intent.asset_requirements[0]
        assert retried_intent.target_object_id == "OPSZONE:Town East"
        assert retried_requirement.allowed_legion_ids == ("LEGION:Blue Brigade",)
        assert retried_requirement.allowed_cohort_ids == ("COHORT:Blue Armor",)

        assessment = bridge.validate_operational_plan(plan)
        assert [(item.phase_id, item.requirement_id) for item in assessment.requirements] == [
            ("seize", "REQ:Ground assault")
        ]
        bridge.approve_operational_plan(plan)
        second = await bridge.execute_plan(plan, commander="COMMANDER:Blue Command")

        assert second.status is OperationalPlanStatus.COMPLETED
        assert second.attempt_number == 2
        assert second.attempt_id == "PLAN:Retry Capture/ATTEMPT:2"
        assert second.resumed_from_phase_id == "seize"
        assert [mission.phase_id for mission in second.missions] == ["seize"]
        history = bridge.operational_plan_executions(plan)
        assert history == (first, second)
        assert [item.attempt_number for item in history] == [1, 2]
        actions = [command.action for command in server.commands if command.action.startswith("auftrag.create_")]
        assert actions == ["auftrag.create_bai", "auftrag.create_capturezone", "auftrag.create_capturezone"]

    asyncio.run(scenario())


def test_explicit_retry_can_reopen_completed_phase_after_goal_confirmation_failure() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan(final_owner="red")

        first = await bridge.execute_plan(plan)

        assert first.status is OperationalPlanStatus.BLOCKED
        assert first.current_phase_id is None
        assert plan.phases[0].status is PlanPhaseStatus.COMPLETED
        assert "strategic goal" in (first.blocked_reason or "")

        bridge.prepare_plan_retry(plan, resume_from="seize")
        assert plan.phases[0].status is PlanPhaseStatus.PENDING
        bridge.server.final_owner = "blue"  # type: ignore[attr-defined]
        bridge.validate_operational_plan(plan)
        bridge.approve_operational_plan(plan)

        second = await bridge.execute_plan(plan)

        assert second.status is OperationalPlanStatus.COMPLETED
        assert second.resumed_from_phase_id == "seize"
        assert len(bridge.operational_plan_executions(plan)) == 2
        assert len(bridge.server.commands) == 2  # type: ignore[attr-defined]

    asyncio.run(scenario())
