from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from moosebridge import (
    AssetRequirement,
    AssetRole,
    MissionIntent,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveComponent,
    ObjectiveKind,
    OperationalPlan,
    OperationalPlanExecution,
    OperationalPlanProvenance,
    OperationalPlanStatus,
    OperationalPosture,
    OwnershipPolicy,
    PlanPhase,
    PlanPhaseStatus,
    PlanProposalIssue,
    PlanMissionExecution,
    PlanMissionStatus,
    PlanReconciliationStatus,
    PlanSourceType,
    ReconRequirement,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
    format_operational_plan_assessment,
    format_operational_plan_execution,
    format_operational_plan_reconciliation,
)
from moosebridge.audit import AuditStore, latest_attempt_records
from moosebridge.control import ControlClientIdentity
from moosebridge.protocol import BridgeCommand
from moosebridge.operational_execution import build_plan_auftrag
from moosebridge.operational_audit import execution_from_dict, execution_to_dict
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
    assert approved.approved_by == "operator"


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
            proposal_issues=(
                PlanProposalIssue(
                    "warning",
                    "intel_no_visible_defenders",
                    "No visible defender is not evidence that the objective is undefended.",
                    "INTEL:Blue",
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
    assert "proposal_issues=1" in rendered
    assert "PROPOSAL WARNING intel_no_visible_defenders INTEL:Blue" in rendered


def test_operational_execution_builds_recon_auftrag() -> None:
    requirement = AssetRequirement(
        "REQ:Reconnaissance",
        AssetRole.RECONNAISSANCE,
        mission_types=("RECON",),
        performer_categories=("AIR",),
    )
    intent = MissionIntent(
        "recon-objective",
        "Reconnoitre objective",
        ("RECON",),
        (requirement,),
        target_object_id="OPSZONE:Town",
        metadata={
            "auftrag_params": {
                "ad_infinitum": False,
                "randomly": False,
            }
        },
    )
    plan = OperationalPlan("PLAN:Recon", "Recon", "GOAL:Capture Town", "blue", (PlanPhase("recon", "Recon", (intent,)),))

    command = build_plan_auftrag(plan, intent, requirement)

    assert command.mission_type == "RECON"
    assert command.to_params() == {
        "zones": ["OPSZONE:Town"],
        "ad_infinitum": False,
        "randomly": False,
    }
    assert command.required_assets_min == 1


class _ExecutionServer:
    def __init__(
        self,
        *,
        success: bool | list[bool] = True,
        final_owner: str = "blue",
        group_ids: tuple[str, ...] = (),
        opszone_ids: tuple[str, ...] = ("OPSZONE:Town",),
        audit_path: Path | None = None,
        auftrag_snapshots: list[dict[str, Any]] | None = None,
        cancel_failures: tuple[str, ...] = (),
        cohort_available_on_refresh: int | None = None,
    ) -> None:
        self.state = MooseBridgeState(connected=True)
        self.success = success
        self.final_owner = final_owner
        self.group_ids = group_ids
        self.opszone_ids = opszone_ids
        self.audit_store = AuditStore(audit_path)
        self.auftrag_snapshots = auftrag_snapshots or []
        self.cancel_failures = set(cancel_failures)
        self.cohort_available_on_refresh = cohort_available_on_refresh
        self.cohort_snapshot_count = 0
        self._objective_updated = False
        self.commands: list[BridgeCommand] = []
        self._mission_number = 0
        self._mission_types: dict[int, str] = {}
        self._event_number = 0
        self.event_history: list[dict[str, Any]] = []

    async def append_audit_record(self, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.audit_store.append(record_type, payload)

    async def query_audit_records(
        self,
        *,
        record_type: str | None = None,
        plan_id: str | None = None,
        attempt_id: str | None = None,
        latest_attempts: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        records = self.audit_store.query(record_type=record_type, plan_id=plan_id, attempt_id=attempt_id)
        return latest_attempt_records(records) if latest_attempts else records

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        self.commands.append(command)
        if command.action == "auftrag.cancel" and command.params.get("object_id") in self.cancel_failures:
            raise RuntimeError(f"cancel rejected for {command.params['object_id']}")
        if command.action.startswith("auftrag.create_"):
            self._mission_number += 1
            self._mission_types[self._mission_number] = command.action.removeprefix("auftrag.create_").upper()
            return {
                "ok": True,
                "id": f"ack-{self._mission_number}",
                "correlation_id": command.id,
                "sequence": self._mission_number,
                "result": {
                    "action": command.action,
                    "auftrag_id": f"AUFTRAG:{self._mission_number}",
                    "auftrag_type": self._mission_types[self._mission_number],
                    "commander_id": command.params.get("commander_id"),
                    "target": command.params.get("opszone"),
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
        mission_type = self._mission_types.get(mission_number, "CAPTUREZONE")
        success = self.success[mission_number - 1] if isinstance(self.success, list) else self.success
        if success and mission_type == "CAPTUREZONE":
            self._objective_updated = True
        event = {
            "type": "event",
            "id": f"event-{self._event_number}",
            "event": "auftrag.evaluated",
            "payload": {
                "auftrag_id": auftrag_id,
                "auftrag_type": mission_type,
                "status": "Done",
                "summary": {"success": success, "Ntargets0": 1, "Ntargets": 0},
            },
        }
        self.event_history.append(event)
        return event

    async def event_cursor(self) -> str | None:
        return str(self.event_history[-1].get("id")) if self.event_history else None

    async def query_events(
        self,
        event_name: str = "*",
        filters: dict[str, Any] | None = None,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        events = self.event_history
        if after_id:
            events = next(
                (self.event_history[index + 1 :] for index, event in enumerate(self.event_history) if event.get("id") == after_id),
                self.event_history,
            )
        return {"events": events, "history_complete": True, "latest_event_id": self.event_history[-1]["id"] if self.event_history else None}

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
                            "owner_current_name": (
                                self.final_owner
                                if object_id == "OPSZONE:Town" and self._objective_updated
                                else "red"
                            ),
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

    async def snapshot_units(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "units", "count": len(self.state.units)}}

    async def snapshot_zones(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "zones", "count": len(self.state.zones)}}

    async def snapshot_statics(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "statics", "count": len(self.state.statics)}}

    async def snapshot_auftraege(self) -> dict[str, Any]:
        self.state.apply_message(
            {
                "type": "snapshot",
                "kind": "auftraege",
                "payload": {"auftraege": self.auftrag_snapshots},
            }
        )
        return {"ok": True, "result": {"kind": "auftraege", "count": len(self.auftrag_snapshots)}}

    async def snapshot_opsgroups(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "opsgroups", "count": len(self.state.opsgroup_objects)}}

    async def snapshot_commanders(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "commanders", "count": len(self.state.commander_objects)}}

    async def snapshot_legions(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "legions", "count": len(self.state.legion_objects)}}

    async def snapshot_cohorts(self) -> dict[str, Any]:
        self.cohort_snapshot_count += 1
        if self.cohort_available_on_refresh is not None:
            self.state.apply_message(
                {
                    "type": "snapshot",
                    "kind": "cohorts",
                    "payload": {
                        "cohorts": [
                            {**cohort, "available_asset_count": self.cohort_available_on_refresh}
                            for cohort in self.state.cohorts.values()
                        ]
                    },
                }
            )
        return {"ok": True, "result": {"kind": "cohorts", "count": len(self.state.cohort_objects)}}

    async def snapshot_airbases(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "airbases", "count": 0}}

    async def snapshot_territories(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "territories", "count": 0}}

    async def snapshot_intels(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "intels", "count": len(self.state.intel_objects)}}

    async def snapshot_intel_contacts(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "intel_contacts", "count": len(self.state.intel_contact_objects)}}

    async def snapshot_intel_clusters(self) -> dict[str, Any]:
        return {"ok": True, "result": {"kind": "intel_clusters", "count": len(self.state.intel_cluster_objects)}}


class _DefendExecutionServer(_ExecutionServer):
    """Execution server that advances DCS time to a DEFEND deadline."""

    def __init__(self, *, lose_control: bool = False) -> None:
        super().__init__(final_owner="blue")
        self.lose_control = lose_control

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        if filters:
            return await super().wait_for_event(event_name, filters, timeout, after_id)
        if self.lose_control:
            self.state.apply_message(
                {
                    "type": "snapshot",
                    "kind": "opszones",
                    "payload": {
                        "opszones": [{
                            "object_id": "OPSZONE:Town",
                            "object_type": "OPSZONE",
                            "owner_current_name": "red",
                            "is_contested": False,
                        }]
                    },
                }
            )
        self._event_number += 1
        event = {
            "type": "heartbeat",
            "source": "dcs",
            "id": f"event-{self._event_number}",
            "mission_time": 110.0 if self.lose_control else 120.0,
            "dcs_time": 43_310.0 if self.lose_control else 43_320.0,
        }
        self.event_history.append(event)
        return event


class _DestroyExecutionServer(_ExecutionServer):
    """Execution server that applies weighted component destruction after BAI."""

    def __init__(
        self,
        *,
        success: bool = True,
        destroy_main: bool = True,
        summary_damage: float | None = None,
    ) -> None:
        super().__init__(success=success)
        self.main_destroyed = False
        self.destroy_main = destroy_main
        self.summary_damage = summary_damage

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        event = await super().wait_for_event(event_name, filters, timeout, after_id)
        if self.summary_damage is not None:
            event["payload"]["summary"]["damage"] = self.summary_damage
        if self.destroy_main and event.get("payload", {}).get("auftrag_type") == "BAI":
            self.main_destroyed = True
        return event

    async def snapshot_statics(self) -> dict[str, Any]:
        self.state.apply_message(
            {
                "type": "snapshot",
                "kind": "statics",
                "payload": {
                    "statics": [
                        {"object_id": "STATIC:Main", "alive": not self.main_destroyed},
                        {"object_id": "STATIC:Reserve", "alive": True},
                    ]
                },
            }
        )
        return {"ok": True, "result": {"kind": "statics", "count": 2}}


def _executable_defend_plan(*, lose_control: bool = False) -> tuple[MooseBridgeClient, OperationalPlan]:
    server = _DefendExecutionServer(lose_control=lose_control)
    server._objective_updated = True
    bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
    bridge.state.apply_message(
        {"type": "heartbeat", "source": "dcs", "mission_time": 100.0, "dcs_time": 43_300.0}
    )
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Town",
            name="Town",
            kind=ObjectiveKind.OPSZONE,
            control_object_id="OPSZONE:Town",
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
            owner="blue",
        )
    )
    bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Defend Town",
            name="Defend Town",
            coalition="blue",
            action=StrategicGoalAction.DEFEND,
            objective_id="OBJECTIVE:Town",
            deadline_mission_time=120.0,
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "commanders",
            "payload": {
                "commanders": [{
                    "object_id": "COMMANDER:Blue Command",
                    "object_type": "COMMANDER",
                    "coalition": "blue",
                    "legion_ids": ["LEGION:Blue Brigade"],
                }]
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
                "cohorts": [{
                    "object_id": "COHORT:Blue Armor",
                    "legion_id": "LEGION:Blue Brigade",
                    "is_ground": True,
                    "available_asset_count": 3,
                    "mission_types": ["PATROLZONE"],
                }]
            },
        }
    )
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Defend Town",
            name="Defend Town",
            goal_id="GOAL:Defend Town",
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="defend",
                    name="Defend",
                    intents=(
                        MissionIntent(
                            intent_id="hold-zone",
                            name="Hold zone",
                            auftrag_types=("PATROLZONE",),
                            target_object_id="OPSZONE:Town",
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Ground defense",
                                    role=AssetRole.COMBAT,
                                    min_count=2,
                                    mission_types=("PATROLZONE",),
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


def _executable_destroy_plan(
    *,
    mission_success: bool = True,
    destroy_main: bool = True,
    summary_damage: float | None = None,
) -> tuple[MooseBridgeClient, OperationalPlan]:
    server = _DestroyExecutionServer(
        success=mission_success,
        destroy_main=destroy_main,
        summary_damage=summary_damage,
    )
    bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Depot",
            name="Depot",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(
                ObjectiveComponent("STATIC:Main", weight=0.6),
                ObjectiveComponent("STATIC:Reserve", weight=0.4),
            ),
        )
    )
    bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Damage Depot",
            name="Damage Depot",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id="OBJECTIVE:Depot",
            required_damage=0.6,
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "commanders",
            "payload": {
                "commanders": [{
                    "object_id": "COMMANDER:Blue Command",
                    "object_type": "COMMANDER",
                    "coalition": "blue",
                    "legion_ids": ["LEGION:Blue Wing"],
                }]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {"legions": [{"object_id": "LEGION:Blue Wing", "coalition": "blue"}]},
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [{
                    "object_id": "COHORT:Strike",
                    "legion_id": "LEGION:Blue Wing",
                    "is_air": True,
                    "stock_asset_count": 2,
                    "available_asset_count": 2,
                    "mission_types": ["BAI"],
                    "payloads_by_mission": {
                        "BAI": {"available_count": 1, "total_available": 2}
                    },
                }]
            },
        }
    )
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Damage Depot",
            name="Damage Depot",
            goal_id="GOAL:Damage Depot",
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="strike",
                    name="Strike",
                    intents=(
                        MissionIntent(
                            intent_id="destroy-main",
                            name="Destroy main depot",
                            auftrag_types=("BAI",),
                            target_object_id="STATIC:Main",
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Strike",
                                    role=AssetRole.COMBAT,
                                    mission_types=("BAI",),
                                    performer_categories=("AIR",),
                                    require_payload=True,
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


def _executable_capture_plan(
    *,
    success: bool = True,
    final_owner: str = "blue",
    audit_path: Path | None = None,
    approved_by: str | None = None,
    approval_reason: str | None = None,
    client_identity: ControlClientIdentity | None = None,
) -> tuple[MooseBridgeClient, OperationalPlan]:
    server = _ExecutionServer(success=success, final_owner=final_owner, audit_path=audit_path)
    if client_identity is not None:
        server.client_identity = client_identity  # type: ignore[attr-defined]
    bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
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
    bridge.approve_operational_plan(plan, approved_by=approved_by, reason=approval_reason)
    return bridge, plan


def test_execute_capture_plan_uses_commander_events_and_confirms_goal() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan()
        observed: list[str] = []

        execution = await bridge.execute_plan(plan, on_event=lambda event: observed.append(event.event))

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert plan.phases[0].status.value == "completed"
        assert execution.missions[0].status.value == "succeeded"
        assert execution.missions[0].command_ack is not None
        assert execution.missions[0].command_ack.ack_id == "ack-1"
        assert execution.missions[0].command_ack.sequence == 1
        assert execution.missions[0].command_ack.result == {
            "action": "auftrag.create_capturezone",
            "auftrag_id": "AUFTRAG:1",
            "auftrag_type": "CAPTUREZONE",
            "commander_id": "COMMANDER:Blue Command",
        }
        assert bridge.strategic_goal("GOAL:Capture Town").status.value == "achieved"  # type: ignore[union-attr]
        command = bridge.server.commands[0]  # type: ignore[attr-defined]
        assert command.params["commander_id"] == "COMMANDER:Blue Command"
        assert command.params["required_assets_min"] == 2
        assert command.params["required_assets_max"] == 3
        assert observed == [
            "plan.started",
            "phase.revalidating",
            "phase.revalidated",
            "phase.started",
            "mission.submitted",
            "mission.succeeded",
            "phase.completed",
            "plan.completed",
        ]
        rendered = format_operational_plan_execution(execution)
        assert "status=completed" in rendered
        assert "approved_by=operator" in rendered
        assert "ack=ack-1" in rendered
        assert f"correlation={command.id}" in rendered

    asyncio.run(scenario())


def test_execute_defend_plan_completes_from_deadline_goal_event() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_defend_plan()
        observed: list[str] = []

        execution = await bridge.execute_plan(
            plan,
            mission_timeout_s=2,
            on_event=lambda event: observed.append(event.event),
        )

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert plan.phases[0].status is PlanPhaseStatus.COMPLETED
        assert bridge.strategic_goal("GOAL:Defend Town").status is StrategicGoalStatus.ACHIEVED  # type: ignore[union-attr]
        assert execution.missions[0].status in {PlanMissionStatus.SUCCEEDED, PlanMissionStatus.CANCELLED}
        assert "plan.completed" in observed
        assert bridge.server.commands[0].action == "auftrag.create_patrolzone"  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_execute_defend_plan_blocks_when_control_is_lost_before_deadline() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_defend_plan(lose_control=True)

        execution = await bridge.execute_plan(plan, mission_timeout_s=2)

        assert execution.status is OperationalPlanStatus.BLOCKED
        assert plan.status is OperationalPlanStatus.BLOCKED
        assert bridge.strategic_goal("GOAL:Defend Town").status is StrategicGoalStatus.FAILED  # type: ignore[union-attr]
        assert "strategic DEFEND goal failed" in (execution.blocked_reason or "")

    asyncio.run(scenario())


def test_completed_plan_formats_expected_mission_cancellation_as_reason() -> None:
    execution = OperationalPlanExecution(
        plan_id="PLAN:Defend Town",
        commander_id="COMMANDER:Blue",
        status=OperationalPlanStatus.COMPLETED,
        missions=[
            PlanMissionExecution(
                phase_id="defend",
                intent_id="hold-zone",
                requirement_id="REQ:Ground defense",
                mission_type="PATROLZONE",
                required=True,
                status=PlanMissionStatus.CANCELLED,
                auftrag_id="AUFTRAG:1",
                error="strategic DEFEND goal achieved",
            )
        ],
    )

    rendered = format_operational_plan_execution(execution)

    assert "reason=strategic DEFEND goal achieved" in rendered
    assert "error=strategic DEFEND goal achieved" not in rendered


def test_execute_destroy_plan_refreshes_weighted_components_and_confirms_goal() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_destroy_plan()
        observed: list[str] = []

        execution = await bridge.execute_plan(plan, on_event=lambda event: observed.append(str(event)))

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert execution.missions[0].status is PlanMissionStatus.SUCCEEDED
        assert execution.damage_assessments[0].achieved_damage == 0.6
        assert execution.damage_assessments[0].required_damage == 0.6
        assert execution.damage_assessments[0].satisfied is True
        assert any("strategic.damage_assessed status=satisfied" in item for item in observed)
        assert any("MOOSE AUFTRAG outcome success=True" in item for item in observed)
        objective = bridge.strategic_objective("OBJECTIVE:Depot")
        goal = bridge.strategic_goal("GOAL:Damage Depot")
        assert objective is not None and abs((objective.health or 0) - 0.4) < 1e-12
        assert goal is not None and goal.status is StrategicGoalStatus.ACHIEVED

        rendered = format_operational_plan_execution(execution)
        assert "strategic_damage phase=strike" in rendered
        assert "damage=60.0%" in rendered
        assert "required=60.0% satisfied=True" in rendered
        assert "moose_auftrag_outcome evaluated=True success=True" in rendered

        restored = execution_from_dict(execution_to_dict(execution))
        assert restored.damage_assessments == execution.damage_assessments

    asyncio.run(scenario())


def test_execute_destroy_plan_uses_weighted_damage_over_auftrag_success() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_destroy_plan(mission_success=False, destroy_main=True)

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert execution.missions[0].status is PlanMissionStatus.FAILED
        assert bridge.strategic_goal("GOAL:Damage Depot").status is StrategicGoalStatus.ACHIEVED  # type: ignore[union-attr]
        rendered = format_operational_plan_execution(execution)
        assert "moose_auftrag_outcome evaluated=True success=False" in rendered
        assert "auftrag_reason=AUFTRAG evaluated without success" in rendered
        assert "required=60.0% satisfied=True" in rendered

    asyncio.run(scenario())


def test_execute_destroy_plan_uses_cumulative_object_damage_from_auftrag_summary() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_destroy_plan(
            mission_success=False,
            destroy_main=False,
            summary_damage=100.0,
        )

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.COMPLETED
        objective = bridge.strategic_objective("OBJECTIVE:Depot")
        assert objective is not None and objective.health == 0.4
        estimate = objective.component_health_estimates["STATIC:Main"]
        assert estimate.health == 0.0
        assert estimate.source == "auftrag_summary:AUFTRAG:1"
        assessment = execution.damage_assessments[0]
        assert assessment.component_health[0] == (
            "STATIC:Main",
            0.0,
            "auftrag_summary:AUFTRAG:1",
        )
        rendered = format_operational_plan_execution(execution)
        assert "STATIC:Main=0.0%(auftrag_summary:AUFTRAG:1)" in rendered

        restored = execution_from_dict(execution_to_dict(execution))
        assert restored.objective_snapshot["component_health_estimates"]["STATIC:Main"]["health"] == 0.0
        assert restored.damage_assessments == execution.damage_assessments

    asyncio.run(scenario())


def test_execute_destroy_plan_reports_weighted_damage_shortfall() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_destroy_plan(
            mission_success=False,
            destroy_main=False,
            summary_damage=50.0,
        )

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.BLOCKED
        assert execution.blocked_reason == "weighted destruction not achieved: damage=30.0% required=60.0%"
        assert bridge.strategic_goal("GOAL:Damage Depot").status is StrategicGoalStatus.ACTIVE  # type: ignore[union-attr]

    asyncio.run(scenario())


def test_successful_recon_requires_fresh_intel_replanning_before_capture() -> None:
    async def scenario() -> None:
        bridge, original = _executable_capture_plan()
        original.status = OperationalPlanStatus.CANCELLED
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
                            "mission_types": ["RECON", "CAPTUREZONE"],
                        }
                    ]
                },
            }
        )
        recon_requirement = AssetRequirement(
            requirement_id="REQ:Reconnaissance",
            role=AssetRole.RECONNAISSANCE,
            mission_types=("RECON",),
            performer_categories=("GROUND",),
        )
        capture_requirement = AssetRequirement(
            requirement_id="REQ:Ground assault",
            role=AssetRole.COMBAT,
            mission_types=("CAPTUREZONE",),
            performer_categories=("GROUND",),
        )
        plan = bridge.add_operational_plan(
            OperationalPlan(
                plan_id="PLAN:Recon Then Capture",
                name="Recon then capture",
                goal_id="GOAL:Capture Town",
                coalition="blue",
                phases=(
                    PlanPhase(
                        "recon",
                        "Reacquire objective contacts",
                        (
                            MissionIntent(
                                "recon-objective",
                                "Reconnoitre objective",
                                ("RECON",),
                                (recon_requirement,),
                                target_object_id="OPSZONE:Town",
                            ),
                        ),
                        metadata={
                            "requires_tactical_replanning": True,
                            "intel_id": "INTEL:Blue",
                            "reconnaissance_requirement": ReconRequirement.manual(
                                "OPSZONE:Town",
                                "GROUP:Lost armor",
                            ).to_dict(),
                        },
                    ),
                    PlanPhase(
                        "seize",
                        "Seize objective",
                        (
                            MissionIntent(
                                "capture-zone",
                                "Capture objective",
                                ("CAPTUREZONE",),
                                (capture_requirement,),
                                target_object_id="OPSZONE:Town",
                            ),
                        ),
                        depends_on=("recon",),
                    ),
                ),
            )
        )
        assert bridge.validate_operational_plan(plan).feasible is True
        bridge.approve_operational_plan(plan)
        observed: list[str] = []

        execution = await bridge.execute_plan(plan, on_event=lambda event: observed.append(event.event))

        assert execution.status is OperationalPlanStatus.BLOCKED
        assert plan.phases[0].status is PlanPhaseStatus.COMPLETED
        assert plan.phases[1].status is PlanPhaseStatus.BLOCKED
        assert [command.action for command in bridge.server.commands] == ["auftrag.create_recon"]  # type: ignore[attr-defined]
        assert execution.missions[0].status is PlanMissionStatus.SUCCEEDED
        assert execution.missions[0].recon_outcome is not None
        assert execution.missions[0].recon_outcome.requirement_satisfied is False
        restored = execution_from_dict(execution_to_dict(execution))
        assert restored.missions[0].recon_outcome is not None
        assert restored.missions[0].recon_outcome.requirement_satisfied is False
        assert "recon.assessed" in observed
        assert "plan.replanning_required" in observed
        assert "relevant targets remain unknown" in (execution.blocked_reason or "")

    asyncio.run(scenario())


def test_phase_revalidation_blocks_before_submission_when_assets_are_no_longer_available() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan()
        server = bridge.server
        server.cohort_available_on_refresh = 0  # type: ignore[attr-defined]
        observed: list[str] = []

        execution = await bridge.execute_plan(plan, on_event=lambda event: observed.append(event.event))

        assert execution.status is OperationalPlanStatus.BLOCKED
        assert plan.status is OperationalPlanStatus.BLOCKED
        assert plan.phases[0].status is PlanPhaseStatus.BLOCKED
        assert "asset_shortfall" in (execution.blocked_reason or "")
        assert "REQ:Ground assault" in (execution.blocked_reason or "")
        assert server.cohort_snapshot_count == 1  # type: ignore[attr-defined]
        assert not server.commands  # type: ignore[attr-defined]
        assert observed == ["plan.started", "phase.revalidating", "plan.blocked"]
        approved_assessment = bridge.plans.assessment(plan.plan_id)
        assert approved_assessment is not None and approved_assessment.feasible is True

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

    execution = asyncio.run(bridge.execute_plan(invalid))

    assert execution.status is OperationalPlanStatus.BLOCKED
    assert "requires a GROUP, UNIT or STATIC target" in (execution.blocked_reason or "")
    assert not bridge.server.commands  # type: ignore[attr-defined]


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

    execution = asyncio.run(bridge.execute_plan(plan))

    assert execution.status is OperationalPlanStatus.BLOCKED
    assert "operational target preflight could not find: GROUP:Missing" in (execution.blocked_reason or "")
    assert not bridge.server.commands  # type: ignore[attr-defined]

    assert plan.status is OperationalPlanStatus.BLOCKED
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
        assert len(bridge.server.commands) == 1  # type: ignore[attr-defined]
        assert plan.phases[0].status is PlanPhaseStatus.SKIPPED

    asyncio.run(scenario())


def test_execution_history_and_attempt_numbers_survive_sdk_restart(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "operational-audit.jsonl"
        first_bridge, first_plan = _executable_capture_plan(
            audit_path=path,
            approval_reason="Capture window confirmed",
            client_identity=ControlClientIdentity("planning-console-1", "Frank"),
        )
        first_plan.provenance = OperationalPlanProvenance(
            source_type=PlanSourceType.RULE_ENGINE,
            source_id="capture-planner-v1",
            picture_mission_time=42.5,
            rationale="Enemy control is weak and ground assets are available.",
        )
        first_plan.proposal_issues = (
            PlanProposalIssue(
                "warning",
                "intel_no_visible_defenders",
                "No visible defender is not proof that the objective is clear.",
                "INTEL:Blue",
            ),
        )
        first = await first_bridge.execute_plan(first_plan)
        first_bridge.server.audit_store.close()  # type: ignore[attr-defined]

        restore_server = _ExecutionServer(audit_path=path)
        restore_bridge = MooseBridgeClient(restore_server)  # type: ignore[arg-type]
        restored_context = await restore_bridge.restore_operational_plan("PLAN:Capture Town")

        assert restored_context.plan.status is OperationalPlanStatus.COMPLETED
        assert restored_context.plan.phases[0].status is PlanPhaseStatus.COMPLETED
        assert restored_context.plan.phases[0].intents[0].asset_requirements[0].min_count == 2
        assert restored_context.plan.approved_by == "Frank"
        assert restored_context.plan.approved_client_id == "planning-console-1"
        assert restored_context.plan.approval_reason == "Capture window confirmed"
        assert restored_context.plan.provenance is not None
        assert restored_context.plan.provenance.source_type is PlanSourceType.RULE_ENGINE
        assert restored_context.plan.provenance.source_id == "capture-planner-v1"
        assert restored_context.plan.provenance.picture_mission_time == 42.5
        assert restored_context.plan.provenance.rationale == (
            "Enemy control is weak and ground assets are available."
        )
        assert restored_context.plan.proposal_issues[0].code == "intel_no_visible_defenders"
        assert restored_context.plan.proposal_issues[0].reference_id == "INTEL:Blue"
        assert restored_context.goal.status.value == "achieved"
        assert restored_context.goal.objective_id == restored_context.objective.objective_id
        assert restored_context.objective.owner == "blue"
        assert restore_bridge.operational_plan("PLAN:Capture Town") is restored_context.plan
        assert restore_bridge.strategic_goal("GOAL:Capture Town") is restored_context.goal
        assert restore_bridge.strategic_objective("OBJECTIVE:Town") is restored_context.objective
        assert restored_context.executions[0].attempt_id == first.attempt_id

        try:
            await restore_bridge.restore_operational_plan("PLAN:Capture Town")
        except ValueError as exc:
            assert "would replace existing objects" in str(exc)
        else:
            raise AssertionError("Restore should reject registry conflicts by default")

        replaced_context = await restore_bridge.restore_operational_plan("PLAN:Capture Town", replace=True)
        assert replaced_context.plan.status is OperationalPlanStatus.COMPLETED
        restore_server.audit_store.close()

        second_bridge, second_plan = _executable_capture_plan(audit_path=path)
        restored = await second_bridge.refresh_operational_plan_executions(second_plan)

        assert len(restored) == 1
        assert restored[0].attempt_id == first.attempt_id
        assert restored[0].status is OperationalPlanStatus.COMPLETED
        assert restored[0].missions[0].outcome is not None
        assert restored[0].missions[0].outcome.success is True
        assert restored[0].missions[0].command_snapshot["mission_type"] == "CAPTUREZONE"
        assert restored[0].missions[0].command_snapshot["params"]["opszone"] == "OPSZONE:Town"
        assert restored[0].missions[0].command_ack is not None
        assert restored[0].missions[0].command_ack.ack_id == "ack-1"
        assert restored[0].missions[0].command_ack.sequence == 1
        assert restored[0].missions[0].command_ack.correlation_id
        assert restored[0].plan_snapshot["goal_id"] == "GOAL:Capture Town"
        assert restored[0].assessment_snapshot["requirements"][0]["allocations"][0]["cohort_id"] == "COHORT:Blue Armor"

        second = await second_bridge.execute_plan(second_plan)

        assert second.attempt_number == 2
        assert second.attempt_id == "PLAN:Capture Town/ATTEMPT:2"
        assert [item.attempt_number for item in second_bridge.operational_plan_executions(second_plan)] == [1, 2]
        second_bridge.server.audit_store.close()  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_restore_rejects_audit_records_without_strategic_snapshots(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "legacy-audit.jsonl"
        store = AuditStore(path)
        store.append(
            "operational_plan.execution",
            {
                "plan_id": "PLAN:Legacy",
                "commander_id": "COMMANDER:Blue",
                "attempt_id": "PLAN:Legacy/ATTEMPT:1",
                "attempt_number": 1,
                "status": "blocked",
                "plan": {"plan_id": "PLAN:Legacy"},
            },
        )
        store.close()
        server = _ExecutionServer(
            audit_path=path,
            auftrag_snapshots=[{"object_id": "AUFTRAG:1", "status": "Executing"}],
        )
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]

        try:
            await bridge.restore_operational_plan("PLAN:Legacy")
        except ValueError as exc:
            assert "predates restorable strategic snapshots" in str(exc)
        else:
            raise AssertionError("Legacy execution audit should not be partially restored")
        server.audit_store.close()

    asyncio.run(scenario())


def test_restored_blocked_plan_can_be_prepared_for_explicit_retry(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "blocked-audit.jsonl"
        first_bridge, first_plan = _executable_capture_plan(success=False, audit_path=path)
        first = await first_bridge.execute_plan(first_plan)
        assert first.status is OperationalPlanStatus.BLOCKED
        first_bridge.server.audit_store.close()  # type: ignore[attr-defined]

        server = _ExecutionServer(
            audit_path=path,
            auftrag_snapshots=[
                {"object_id": "AUFTRAG:1", "status": "Executing"},
                {"object_id": "AUFTRAG:99", "status": "Executing"},
            ],
        )
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        restored = await bridge.restore_operational_plan(first_plan.plan_id)

        assert restored.plan.status is OperationalPlanStatus.BLOCKED
        assert restored.plan.phases[0].status is PlanPhaseStatus.BLOCKED
        bridge.prepare_plan_retry(restored.plan)
        assert restored.plan.status is OperationalPlanStatus.DRAFT
        assert restored.plan.phases[0].status is PlanPhaseStatus.PENDING
        server.audit_store.close()

    asyncio.run(scenario())


async def _write_interrupted_capture_audit(path: Path) -> None:
    bridge, plan = _executable_capture_plan(audit_path=path)
    execution = await bridge.execute_plan(plan)
    mission = execution.missions[0]
    mission.status = PlanMissionStatus.RUNNING
    mission.outcome = None
    mission.error = None
    plan.status = OperationalPlanStatus.EXECUTING
    plan.phases[0].status = PlanPhaseStatus.ACTIVE
    execution.status = OperationalPlanStatus.EXECUTING
    execution.current_phase_id = "seize"
    execution.completed_mission_time = None
    goal = bridge.strategic_goal(plan.goal_id)
    objective = bridge.strategic_objective("OBJECTIVE:Town")
    assert goal is not None and objective is not None
    goal.status = StrategicGoalStatus.ACTIVE
    goal.completed_mission_time = None
    objective.owner = "red"
    await bridge.plan_executor._persist(execution)
    bridge.server.audit_store.close()  # type: ignore[attr-defined]


def test_reconcile_interrupted_plan_reports_running_and_missing_auftraege(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "interrupted-audit.jsonl"
        await _write_interrupted_capture_audit(path)

        running_server = _ExecutionServer(
            audit_path=path,
            auftrag_snapshots=[{"object_id": "AUFTRAG:1", "status": "Executing", "type": "CAPTUREZONE"}],
        )
        running_bridge = MooseBridgeClient(running_server)  # type: ignore[arg-type]
        running = await running_bridge.restore_operational_plan("PLAN:Capture Town")
        running_result = await running_bridge.reconcile_operational_plan(running.plan)
        assert running_result.status is PlanReconciliationStatus.RUNNING
        assert running.plan.status is OperationalPlanStatus.EXECUTING
        assert "reconciliation=running" in format_operational_plan_reconciliation(running_result)
        running_server.audit_store.close()

        missing_server = _ExecutionServer(audit_path=path)
        missing_bridge = MooseBridgeClient(missing_server)  # type: ignore[arg-type]
        missing = await missing_bridge.restore_operational_plan("PLAN:Capture Town")
        missing_result = await missing_bridge.reconcile_operational_plan(missing.plan)
        assert missing_result.status is PlanReconciliationStatus.INDETERMINATE
        assert missing_result.observations[0].snapshot_found is False
        assert missing.plan.status is OperationalPlanStatus.EXECUTING
        await missing_bridge.block_interrupted_operational_plan(
            missing.plan,
            reason="Operator confirmed that the AUFTRAG no longer exists",
        )
        assert missing.plan.status is OperationalPlanStatus.BLOCKED
        missing_bridge.prepare_plan_retry(missing.plan)
        assert missing.plan.status is OperationalPlanStatus.DRAFT
        missing_server.audit_store.close()

    asyncio.run(scenario())


def test_reconcile_interrupted_plan_blocks_on_failed_summary(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "failed-interrupted-audit.jsonl"
        await _write_interrupted_capture_audit(path)
        server = _ExecutionServer(
            audit_path=path,
            auftrag_snapshots=[
                {
                    "object_id": "AUFTRAG:1",
                    "status": "Done",
                    "type": "CAPTUREZONE",
                    "summary": {"success": False, "Ntargets0": 1, "Ntargets": 1},
                }
            ],
        )
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        restored = await bridge.restore_operational_plan("PLAN:Capture Town")

        result = await bridge.reconcile_operational_plan(restored.plan)

        assert result.status is PlanReconciliationStatus.BLOCKED
        assert restored.plan.status is OperationalPlanStatus.BLOCKED
        assert restored.executions[-1].missions[0].status.value == "failed"
        bridge.prepare_plan_retry(restored.plan)
        assert restored.plan.status is OperationalPlanStatus.DRAFT
        server.audit_store.close()

    asyncio.run(scenario())


def test_reconcile_interrupted_plan_leaves_unknown_auftrag_state_indeterminate(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "unknown-interrupted-audit.jsonl"
        await _write_interrupted_capture_audit(path)
        server = _ExecutionServer(
            audit_path=path,
            auftrag_snapshots=[{"object_id": "AUFTRAG:1", "status": "Unexpected", "type": "CAPTUREZONE"}],
        )
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        restored = await bridge.restore_operational_plan("PLAN:Capture Town")

        result = await bridge.reconcile_operational_plan(restored.plan)

        assert result.status is PlanReconciliationStatus.INDETERMINATE
        assert restored.plan.status is OperationalPlanStatus.EXECUTING
        assert result.observations[0].message == "AUFTRAG snapshot has no recognized lifecycle status"
        server.audit_store.close()

    asyncio.run(scenario())


def test_monitor_interrupted_plan_reattaches_to_events_without_new_auftrag(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "monitored-interrupted-audit.jsonl"
        await _write_interrupted_capture_audit(path)
        server = _ExecutionServer(
            audit_path=path,
            success=True,
            final_owner="blue",
            auftrag_snapshots=[{"object_id": "AUFTRAG:1", "status": "Executing", "type": "CAPTUREZONE"}],
        )
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        restored = await bridge.restore_operational_plan("PLAN:Capture Town")

        result = await bridge.monitor_interrupted_operational_plan(restored.plan, mission_timeout_s=1.0)

        assert result.status is PlanReconciliationStatus.COMPLETED
        assert restored.plan.status is OperationalPlanStatus.COMPLETED
        assert restored.executions[-1].missions[0].status.value == "succeeded"
        assert not [command for command in server.commands if command.action.startswith("auftrag.create_")]
        server.audit_store.close()

    asyncio.run(scenario())


def test_abort_operational_plan_cancels_all_live_auftraege_by_default(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "aborted-plan-audit.jsonl"
        await _write_interrupted_capture_audit(path)
        server = _ExecutionServer(
            audit_path=path,
            auftrag_snapshots=[{"object_id": "AUFTRAG:1", "status": "Executing"}],
        )
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        restored = await bridge.restore_operational_plan("PLAN:Capture Town")

        result = await bridge.abort_operational_plan(restored.plan, reason="Objective is no longer valid")

        assert result.status is OperationalPlanStatus.CANCELLED
        assert result.scope.value == "attempt"
        assert [mission.auftrag_id for mission in result.missions] == ["AUFTRAG:1"]
        assert result.missions[0].cancelled is True
        assert restored.plan.status is OperationalPlanStatus.CANCELLED
        assert restored.plan.phases[0].status is PlanPhaseStatus.CANCELLED
        assert restored.executions[-1].missions[0].status is PlanMissionStatus.CANCELLED
        assert [command.action for command in server.commands] == ["auftrag.cancel"]
        server.audit_store.close()

    asyncio.run(scenario())


def test_abort_operational_plan_can_limit_moose_cancellation_to_current_phase(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "current-phase-abort-audit.jsonl"
        await _write_interrupted_capture_audit(path)
        server = _ExecutionServer(
            audit_path=path,
            auftrag_snapshots=[
                {"object_id": "AUFTRAG:1", "status": "Executing"},
                {"object_id": "AUFTRAG:99", "status": "Executing"},
            ],
        )
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        restored = await bridge.restore_operational_plan("PLAN:Capture Town")
        execution = restored.executions[-1]
        execution.missions.insert(
            0,
            PlanMissionExecution(
                "isolate",
                "interdict",
                "REQ:Strike",
                "BAI",
                True,
                status=PlanMissionStatus.RUNNING,
                auftrag_id="AUFTRAG:99",
            ),
        )

        result = await bridge.abort_operational_plan(restored.plan, scope="current_phase")

        assert result.status is OperationalPlanStatus.CANCELLED
        assert [mission.auftrag_id for mission in result.missions] == ["AUFTRAG:1"]
        assert execution.missions[0].status is PlanMissionStatus.RUNNING
        assert [command.params["object_id"] for command in server.commands] == ["AUFTRAG:1"]
        server.audit_store.close()

    asyncio.run(scenario())


def test_abort_operational_plan_blocks_when_a_moose_cancel_fails(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "failed-abort-audit.jsonl"
        await _write_interrupted_capture_audit(path)
        server = _ExecutionServer(
            audit_path=path,
            auftrag_snapshots=[{"object_id": "AUFTRAG:1", "status": "Executing"}],
            cancel_failures=("AUFTRAG:1",),
        )
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        restored = await bridge.restore_operational_plan("PLAN:Capture Town")

        result = await bridge.abort_operational_plan(restored.plan)

        assert result.status is OperationalPlanStatus.BLOCKED
        assert result.missions[0].cancelled is False
        assert restored.plan.status is OperationalPlanStatus.BLOCKED
        assert restored.executions[-1].missions[0].status is PlanMissionStatus.RUNNING
        assert "AUFTRAG:1" in (result.message or "")
        server.audit_store.close()

    asyncio.run(scenario())
