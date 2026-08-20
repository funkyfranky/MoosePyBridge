from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from moosebridge import (
    Auftrag_ARTY,
    AssetRequirement,
    AssetRole,
    DcsWeaponFlag,
    GroundRoute,
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
    PlanExecutionEvent,
    PlanReconciliationStatus,
    PlanSourceType,
    ReconRequirement,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalEffect,
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
from moosebridge.operational_audit import execution_from_dict, execution_to_dict, plan_from_snapshot, plan_snapshot
from moosebridge.pictures import TacticalPicture
from moosebridge.state import MooseBridgeState


def _bridge_with_goal(
    server: Any | None = None,
    *,
    ground_mobility: Any | None = None,
) -> MooseBridgeClient:
    bridge = MooseBridgeClient(server or MooseBridgeServer(), ground_mobility=ground_mobility)
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


def test_plan_execution_event_formats_mission_type_without_duplicate_status() -> None:
    event = PlanExecutionEvent(
        event="mission.status",
        plan_id="PLAN:Strike",
        auftrag_id="AUFTRAG:1",
        status="running",
        message="AUFTRAG:1 Queued status=queued planned->queued",
        mission_type="BAI",
    )

    assert str(event) == "AUFTRAG:1 type=BAI Queued status=queued planned->queued"
    assert str(event).count("status=") == 1

    execution = OperationalPlanExecution(
        plan_id="PLAN:Strike",
        commander_id="COMMANDER:Blue",
        events=[event],
    )
    restored = execution_from_dict(execution_to_dict(execution))
    assert restored.events[0].mission_type == "BAI"


def test_persistent_mission_execution_round_trips_through_audit_schema() -> None:
    execution = OperationalPlanExecution(
        plan_id="PLAN:Secure Town",
        commander_id="COMMANDER:Blue",
        missions=[
            PlanMissionExecution(
                phase_id="consolidate",
                intent_id="secure-zone",
                requirement_id="REQ:Ground security",
                mission_type="PATROLZONE",
                required=True,
                persistent=True,
                established_on="Executing",
                status=PlanMissionStatus.RUNNING,
                auftrag_id="AUFTRAG:2",
            )
        ],
    )

    restored = execution_from_dict(execution_to_dict(execution))

    assert restored.missions[0].persistent is True
    assert restored.missions[0].established_on == "Executing"
    assert restored.missions[0].status is PlanMissionStatus.RUNNING


def _apply_force_state(
    bridge: MooseBridgeClient,
    *,
    air_stock: int = 2,
    ground_stock: int = 3,
    air_available: int | None = None,
    ground_available: int | None = None,
    ground_units_per_asset: int | None = None,
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
                        "homogeneous": ground_units_per_asset is not None,
                        "units_per_asset": ground_units_per_asset,
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


def test_plan_validation_uses_route_aware_assignment_order_and_filter() -> None:
    bridge = _bridge_with_goal()
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {"legions": [{"object_id": "LEGION:Blue", "coalition": "blue"}]},
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:Disconnected",
                        "legion_id": "LEGION:Blue",
                        "is_ground": True,
                        "available_asset_count": 2,
                        "mission_types": ["PATROLZONE"],
                        "mission_performance": {"PATROLZONE": 100},
                    },
                    {
                        "object_id": "COHORT:Reachable",
                        "legion_id": "LEGION:Blue",
                        "is_ground": True,
                        "available_asset_count": 2,
                        "mission_types": ["PATROLZONE"],
                        "mission_performance": {"PATROLZONE": 60},
                    },
                ]
            },
        }
    )
    requirement = AssetRequirement(
        "REQ:Secure",
        AssetRole.COMBAT,
        mission_types=("PATROLZONE",),
        performer_categories=("GROUND",),
        metadata={
            "ground_mobility_filter": True,
            "mission_assignments": [
                {"cohort_id": "COHORT:Reachable", "selection_score": 55.0},
            ],
        },
    )
    plan = bridge.add_operational_plan(
        OperationalPlan(
            "PLAN:Route aware",
            "Route aware",
            "GOAL:Capture Town",
            "blue",
            (
                PlanPhase(
                    "secure",
                    "Secure",
                    (
                        MissionIntent(
                            "patrol",
                            "Patrol",
                            ("PATROLZONE",),
                            (requirement,),
                            target_object_id="OPSZONE:Town",
                        ),
                    ),
                ),
            ),
        )
    )

    assessment = bridge.validate_operational_plan(plan)

    result = assessment.requirements[0]
    assert result.candidate_cohort_ids == ("COHORT:Reachable",)
    assert result.allocations[0].cohort_id == "COHORT:Reachable"


def test_sdk_prepares_ground_mobility_ranking_for_zone_requirement() -> None:
    class MobilityNetwork:
        def route(
            self,
            start_latitude: float,
            start_longitude: float,
            end_latitude: float,
            end_longitude: float,
            *,
            profile: Any,
        ) -> GroundRoute | None:
            if start_longitude < 12.05:
                return None
            return GroundRoute(profile.name, 0, 1, (0, 1), 10_000.0, 1_000.0, 1, 10_000.0)

    bridge = _bridge_with_goal(ground_mobility=MobilityNetwork())
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "opszones",
            "payload": {
                "opszones": [
                    {
                        "object_id": "OPSZONE:Town",
                        "x": 10_000.0,
                        "z": 0.0,
                        "latitude": 54.0,
                        "longitude": 12.2,
                    }
                ]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {"legions": [{"object_id": "LEGION:Blue", "coalition": "blue"}]},
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:Disconnected",
                        "legion_id": "LEGION:Blue",
                        "is_ground": True,
                        "available_asset_count": 1,
                        "mission_types": ["PATROLZONE"],
                        "mission_performance": {"PATROLZONE": 100},
                        "x": 0.0,
                        "z": 0.0,
                        "latitude": 54.0,
                        "longitude": 12.0,
                    },
                    {
                        "object_id": "COHORT:Reachable",
                        "legion_id": "LEGION:Blue",
                        "is_ground": True,
                        "available_asset_count": 1,
                        "mission_types": ["PATROLZONE"],
                        "mission_performance": {"PATROLZONE": 60},
                        "x": 1_000.0,
                        "z": 0.0,
                        "latitude": 54.0,
                        "longitude": 12.1,
                    },
                ]
            },
        }
    )
    requirement = AssetRequirement(
        "REQ:Secure",
        AssetRole.COMBAT,
        mission_types=("PATROLZONE",),
        performer_categories=("GROUND",),
    )
    plan = bridge.add_operational_plan(
        OperationalPlan(
            "PLAN:SDK route aware",
            "SDK route aware",
            "GOAL:Capture Town",
            "blue",
            (
                PlanPhase(
                    "secure",
                    "Secure",
                    (
                        MissionIntent(
                            "patrol",
                            "Patrol",
                            ("PATROLZONE",),
                            (requirement,),
                            target_object_id="OPSZONE:Town",
                        ),
                    ),
                ),
            ),
        )
    )

    assessment = bridge.validate_operational_plan(plan)

    assert assessment.requirements[0].allocations[0].cohort_id == "COHORT:Reachable"
    assignments = requirement.metadata["mission_assignments"]
    assert [item["cohort_id"] for item in assignments] == ["COHORT:Reachable"]
    assert assignments[0]["transit_source"] == "python_ground_mobility"
    assert assignments[0]["bridge_count"] == 1


def test_plan_validation_converts_homogeneous_unit_strength_to_asset_groups() -> None:
    def assess(units_per_asset: int | None) -> tuple[OperationalPlan, Any]:
        bridge = _bridge_with_goal()
        _apply_force_state(
            bridge,
            ground_stock=3,
            ground_available=3,
            ground_units_per_asset=units_per_asset,
        )
        requirement = AssetRequirement(
            requirement_id="REQ:Ground assault",
            role=AssetRole.COMBAT,
            min_count=1,
            max_count=2,
            min_unit_count=2,
            mission_types=("CAPTUREZONE",),
            performer_categories=("GROUND",),
        )
        intent = MissionIntent(
            "capture-zone",
            "Capture zone",
            ("CAPTUREZONE",),
            (requirement,),
            target_object_id="OPSZONE:Town",
        )
        plan = bridge.add_operational_plan(
            OperationalPlan(
                f"PLAN:Strength {units_per_asset}",
                "Unit-aware strength",
                "GOAL:Capture Town",
                "blue",
                (PlanPhase("seize", "Seize", (intent,)),),
            )
        )
        return plan, bridge.validate_operational_plan(plan)

    homogeneous_plan, homogeneous = assess(4)
    _, conservative = assess(None)

    strong = homogeneous.requirements[0]
    assert strong.required_count == 1
    assert strong.required_unit_count == 2
    assert strong.available_unit_count == 12
    assert strong.allocated_unit_count == 4
    assert strong.allocations[0].count == 1
    assert strong.allocations[0].units_per_asset == 4
    assert strong.allocations[0].unit_count == 4
    assert strong.feasible is True

    fallback = conservative.requirements[0]
    assert fallback.required_count == 2
    assert fallback.available_unit_count == 3
    assert fallback.allocated_unit_count == 2
    assert fallback.allocations[0].count == 2

    restored = plan_from_snapshot(plan_snapshot(homogeneous_plan))
    restored_requirement = restored.phases[0].intents[0].asset_requirements[0]
    assert restored_requirement.min_unit_count == 2


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
    assert "mission=BAI" in rendered
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


def test_operational_execution_uses_resolved_unit_aware_asset_count() -> None:
    requirement = AssetRequirement(
        "REQ:Ground security",
        AssetRole.COMBAT,
        min_count=1,
        max_count=4,
        min_unit_count=4,
        mission_types=("PATROLZONE",),
        performer_categories=("GROUND",),
    )
    intent = MissionIntent(
        "secure-zone",
        "Secure zone",
        ("PATROLZONE",),
        (requirement,),
        target_object_id="OPSZONE:Town",
    )
    plan = OperationalPlan(
        "PLAN:Secure",
        "Secure",
        "GOAL:Capture Town",
        "blue",
        (PlanPhase("consolidate", "Consolidate", (intent,)),),
    )

    command = build_plan_auftrag(plan, intent, requirement, required_asset_count=1)

    assert command.required_assets_min == 1
    assert command.required_assets_max == 1


def test_operational_execution_builds_resolved_object_attack_types() -> None:
    cases = (
        ("SEAD", "GROUP:SAM"),
        ("ANTISHIP", "GROUP:Ship"),
        ("INTERCEPT", "UNIT:Bandit"),
        ("GROUNDATTACK", "GROUP:Armor"),
        ("NAVALENGAGEMENT", "STATIC:Coastal Target"),
        ("BOMBING", "STATIC:Depot"),
        ("ARTY", "STATIC:Depot"),
    )
    for mission_type, target in cases:
        requirement = AssetRequirement(
            f"REQ:{mission_type}",
            AssetRole.COMBAT,
            mission_types=(mission_type,),
        )
        intent = MissionIntent(
            f"intent-{mission_type.lower()}",
            mission_type,
            (mission_type,),
            (requirement,),
            target_object_id=target,
        )
        plan = OperationalPlan(
            f"PLAN:{mission_type}",
            mission_type,
            "GOAL:Capture Town",
            "blue",
            (PlanPhase("strike", "Strike", (intent,)),),
        )

        command = build_plan_auftrag(plan, intent, requirement)

        assert command.mission_type == mission_type
        assert command.to_params()["target"] == target


def test_operational_execution_builds_scenery_strike_from_geographic_position() -> None:
    requirement = AssetRequirement(
        "REQ:STRIKE",
        AssetRole.COMBAT,
        mission_types=("STRIKE",),
        performer_categories=("AIR",),
    )
    intent = MissionIntent(
        "strike-bridge",
        "Strike bridge",
        ("STRIKE",),
        (requirement,),
        target_object_id="SCENERY:70254625",
        metadata={
            "auftrag_params": {
                "latitude": 41.664066994884,
                "longitude": 41.681539555042,
            }
        },
    )
    plan = OperationalPlan(
        "PLAN:Strike Bridge",
        "Strike Bridge",
        "GOAL:Destroy Bridge",
        "blue",
        (PlanPhase("strike", "Strike", (intent,)),),
    )

    command = build_plan_auftrag(plan, intent, requirement)

    assert command.mission_type == "STRIKE"
    assert command.to_params() == {
        "target": "SCENERY:70254625",
        "latitude": 41.664066994884,
        "longitude": 41.681539555042,
    }


def test_operational_execution_applies_resolved_arty_weapon_type() -> None:
    weapon_type = int(DcsWeaponFlag.CONVENTIONAL_SHELL)
    requirement = AssetRequirement(
        "REQ:ARTY",
        AssetRole.FIRES,
        mission_types=("ARTY",),
        performer_categories=("GROUND",),
    )
    intent = MissionIntent(
        "shell-depot",
        "Shell depot",
        ("ARTY",),
        (requirement,),
        target_object_id="STATIC:Depot",
        metadata={
            "fire_support": {
                "weapon_flag": "CONVENTIONAL_SHELL",
                "weapon_flag_value": weapon_type,
            }
        },
    )
    plan = OperationalPlan(
        "PLAN:ARTY Weapon",
        "ARTY Weapon",
        "GOAL:Destroy Depot",
        "blue",
        (PlanPhase("strike", "Strike", (intent,)),),
    )

    command = build_plan_auftrag(plan, intent, requirement)

    assert command.weapon_type == weapon_type
    assert command.timing_params()["weapon_type"] == weapon_type


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
        audit_session_id: str = "test-session",
    ) -> None:
        self.state = MooseBridgeState(connected=True, audit_session_id=audit_session_id)
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


class _SceneryDestroyExecutionServer(_ExecutionServer):
    """Execution server that retains a SCENERY loss beside AUFTRAG events."""

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        auftrag_id = str((filters or {}).get("auftrag_id") or "AUFTRAG:1")
        self._event_number += 1
        self.event_history.append(
            {
                "type": "event",
                "id": f"event-{self._event_number}",
                "event": "object.destroyed",
                "mission_time": 120.0,
                "payload": {
                    "object_id": "SCENERY:Bridge",
                    "object_type": "SCENERY",
                    "dcs_event_name": "S_EVENT_DEAD",
                    "object": {
                        "object_id": "SCENERY:Bridge",
                        "object_type": "SCENERY",
                        "dcs_type": "MOST(ROAD)BIG",
                        "alive": False,
                        "active": False,
                        "x": -349_070.875,
                        "y": 21.559,
                        "z": 623_555.0,
                    },
                },
            }
        )
        self._event_number += 1
        event = {
            "type": "event",
            "id": f"event-{self._event_number}",
            "event": "auftrag.evaluated",
            "payload": {
                "auftrag_id": auftrag_id,
                "auftrag_type": "STRIKE",
                "status": "Done",
                "summary": {"success": True, "Ntargets0": 1, "Ntargets": 0},
            },
        }
        self.event_history.append(event)
        return event


class _LiveSceneryDestroyExecutionServer(_SceneryDestroyExecutionServer):
    """Mirror direct-server delivery where the loss is already in state."""

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        event = await super().wait_for_event(event_name, filters, timeout, after_id)
        destroyed = next(
            item for item in reversed(self.event_history) if item.get("event") == "object.destroyed"
        )
        self.state.apply_message(destroyed)
        return event


class _IncompleteSceneryDestroyExecutionServer(_SceneryDestroyExecutionServer):
    """Simulate a destruction cursor evicted from bounded event history."""

    async def event_cursor(self) -> str | None:
        return "event-expired"

    async def query_events(
        self,
        event_name: str = "*",
        filters: dict[str, Any] | None = None,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        result = await super().query_events(event_name, filters, after_id)
        result["history_complete"] = False
        return result


class _DuplicateStatusExecutionServer(_ExecutionServer):
    """Execution server that repeats one status transition before evaluation."""

    def __init__(self) -> None:
        super().__init__()
        self._event_steps: dict[str, int] = {}

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        auftrag_id = str((filters or {}).get("auftrag_id") or "AUFTRAG:1")
        step = self._event_steps.get(auftrag_id, 0)
        self._event_steps[auftrag_id] = step + 1
        self._event_number += 1
        if step < 2:
            event = {
                "type": "event",
                "id": f"event-{self._event_number}",
                "event": "auftrag.status",
                "payload": {
                    "auftrag_id": auftrag_id,
                    "auftrag_type": "CAPTUREZONE",
                    "status": "queued",
                    "fsm_event": "Queued",
                    "from": "planned",
                    "to": "queued",
                },
            }
        else:
            self._objective_updated = True
            event = {
                "type": "event",
                "id": f"event-{self._event_number}",
                "event": "auftrag.evaluated",
                "payload": {
                    "auftrag_id": auftrag_id,
                    "auftrag_type": "CAPTUREZONE",
                    "status": "Done",
                    "summary": {"success": True, "Ntargets0": 1, "Ntargets": 0},
                },
            }
        self.event_history.append(event)
        return event


class _PersistentMissionExecutionServer(_ExecutionServer):
    """Execution server that establishes a persistent AUFTRAG without evaluating it."""

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        self._event_number += 1
        auftrag_id = str((filters or {}).get("auftrag_id") or "AUFTRAG:1")
        event = {
            "type": "event",
            "id": f"event-{self._event_number}",
            "event": "auftrag.status",
            "payload": {
                "auftrag_id": auftrag_id,
                "auftrag_type": "PATROLZONE",
                "status": "executing",
                "fsm_event": "Executing",
                "from": "started",
                "to": "executing",
            },
        }
        self.event_history.append(event)
        return event


class _CancelBeforeEvaluatedExecutionServer(_ExecutionServer):
    """Reproduce MOOSE's Done -> Cancel -> Evaluated terminal callback order."""

    def __init__(self, *, success: bool = True) -> None:
        super().__init__()
        self.evaluated_success = success
        self._event_steps: dict[str, int] = {}

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        auftrag_id = str((filters or {}).get("auftrag_id") or "AUFTRAG:1")
        step = self._event_steps.get(auftrag_id, 0)
        self._event_steps[auftrag_id] = step + 1
        self._event_number += 1
        if step == 0:
            event = {
                "type": "event",
                "id": f"event-{self._event_number}",
                "event": "auftrag.status",
                "payload": {
                    "auftrag_id": auftrag_id,
                    "auftrag_type": "CAPTUREZONE",
                    "status": "done",
                    "fsm_event": "Done",
                    "from": "cancelled",
                    "to": "done",
                },
            }
        elif step == 1:
            event = {
                "type": "event",
                "id": f"event-{self._event_number}",
                "event": "auftrag.status",
                "payload": {
                    "auftrag_id": auftrag_id,
                    "auftrag_type": "CAPTUREZONE",
                    "status": "done",
                    "fsm_event": "Cancel",
                    "from": "started",
                    "to": "cancelled",
                },
            }
        else:
            self._objective_updated = self.evaluated_success
            event = {
                "type": "event",
                "id": f"event-{self._event_number}",
                "event": "auftrag.evaluated",
                "payload": {
                    "auftrag_id": auftrag_id,
                    "auftrag_type": "CAPTUREZONE",
                    "status": "done",
                    "summary": {"success": self.evaluated_success, "Ntargets0": 1, "Ntargets": 0},
                },
            }
        self.event_history.append(event)
        return event


class _DisappearingStaticDestroyExecutionServer(_DestroyExecutionServer):
    """Execution server whose destroyed static vanishes from the complete snapshot."""

    async def snapshot_statics(self) -> dict[str, Any]:
        statics = [{"object_id": "STATIC:Reserve", "alive": True}]
        if not self.main_destroyed:
            statics.insert(0, {"object_id": "STATIC:Main", "alive": True})
        self.state.apply_message(
            {
                "type": "snapshot",
                "kind": "statics",
                "payload": {"statics": statics},
            }
        )
        return {"ok": True, "result": {"kind": "statics", "count": len(statics)}}


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


def _replace_destroy_server(
    bridge: MooseBridgeClient,
    server: _DestroyExecutionServer,
) -> None:
    state = bridge.state
    server.state = state
    bridge.server = server  # type: ignore[assignment]


def _executable_scenery_destroy_plan(
    server: _SceneryDestroyExecutionServer | None = None,
) -> tuple[MooseBridgeClient, OperationalPlan]:
    server = server or _SceneryDestroyExecutionServer()
    bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Bridge",
            name="Bridge",
            kind=ObjectiveKind.INFRASTRUCTURE,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="blue",
            components=(ObjectiveComponent("SCENERY:Bridge", role="bridge", weight=1.0),),
            metadata={"source_object_id": "BRIDGE:Caucasus:test"},
        )
    )
    bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Destroy Bridge",
            name="Destroy Bridge",
            coalition="red",
            action=StrategicGoalAction.DESTROY,
            objective_id="OBJECTIVE:Bridge",
            required_damage=1.0,
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "commanders",
            "payload": {
                "commanders": [{
                    "object_id": "COMMANDER:Red Command",
                    "object_type": "COMMANDER",
                    "coalition": "red",
                    "legion_ids": ["LEGION:Red Wing"],
                }]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {"legions": [{"object_id": "LEGION:Red Wing", "coalition": "red"}]},
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [{
                    "object_id": "COHORT:Red Strike",
                    "legion_id": "LEGION:Red Wing",
                    "is_air": True,
                    "stock_asset_count": 2,
                    "available_asset_count": 2,
                    "mission_types": ["STRIKE"],
                    "payloads_by_mission": {
                        "STRIKE": {"available_count": 1, "total_available": 2}
                    },
                }]
            },
        }
    )
    plan = bridge.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Destroy Bridge",
            name="Destroy Bridge",
            goal_id="GOAL:Destroy Bridge",
            coalition="red",
            phases=(
                PlanPhase(
                    phase_id="strike",
                    name="Strike",
                    intents=(
                        MissionIntent(
                            intent_id="destroy-bridge",
                            name="Destroy bridge",
                            auftrag_types=("STRIKE",),
                            target_object_id="SCENERY:Bridge",
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Strike",
                                    role=AssetRole.COMBAT,
                                    mission_types=("STRIKE",),
                                    performer_categories=("AIR",),
                                    require_payload=True,
                                ),
                            ),
                            metadata={
                                "auftrag_params": {
                                    "x": -349_070.875,
                                    "z": 623_555.0,
                                }
                            },
                        ),
                    ),
                ),
            ),
        )
    )
    bridge.validate_operational_plan(plan)
    bridge.approve_operational_plan(plan)
    return bridge, plan


def _executable_disable_plan(*, success: bool = True) -> tuple[MooseBridgeClient, OperationalPlan]:
    server = _ExecutionServer(success=success, opszone_ids=())
    bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Tutow",
            name="Tutow Airbase",
            kind=ObjectiveKind.AIRBASE,
            control_object_id="AIRBASE:Tutow",
            ownership_policy=OwnershipPolicy.DCS_MANAGED,
            owner="red",
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Deny Tutow runway",
            name="Deny Tutow runway",
            coalition="blue",
            action=StrategicGoalAction.DISABLE,
            objective_id=objective.objective_id,
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "airbases",
            "payload": {
                "airbases": [{"object_id": "AIRBASE:Tutow", "category": "Airdrome", "coalition": "red"}]
            },
        }
    )
    for kind, payload in (
        (
            "commanders",
            [{
                "object_id": "COMMANDER:Blue Command",
                "object_type": "COMMANDER",
                "coalition": "blue",
                "legion_ids": ["LEGION:Blue Wing"],
            }],
        ),
        ("legions", [{"object_id": "LEGION:Blue Wing", "coalition": "blue"}]),
        (
            "cohorts",
            [{
                "object_id": "COHORT:Runway Strike",
                "legion_id": "LEGION:Blue Wing",
                "is_air": True,
                "stock_asset_count": 2,
                "available_asset_count": 2,
                "mission_types": ["BOMBRUNWAY"],
                "payloads_by_mission": {"BOMBRUNWAY": {"available_count": 1, "total_available": 2}},
            }],
        ),
    ):
        bridge.state.apply_message(
            {"type": "snapshot", "kind": kind, "payload": {kind: payload}}
        )
    plan = bridge.propose_disable_plan(
        goal,
        TacticalPicture(coalition="blue", intel_id="INTEL:Blue"),
        plan_id="PLAN:Deny Tutow runway",
    )
    bridge.add_operational_plan(plan)
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
    units_per_asset: int | None = None,
    min_unit_count: int | None = None,
    audit_session_id: str = "test-session",
) -> tuple[MooseBridgeClient, OperationalPlan]:
    server = _ExecutionServer(
        success=success,
        final_owner=final_owner,
        audit_path=audit_path,
        audit_session_id=audit_session_id,
    )
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
                        "homogeneous": units_per_asset is not None,
                        "units_per_asset": units_per_asset,
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
                                    min_count=1 if min_unit_count is not None else 2,
                                    max_count=2 if min_unit_count is not None else 3,
                                    min_unit_count=min_unit_count,
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


def test_execute_disable_plan_confirms_runway_denial_from_successful_bombrunway() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_disable_plan()
        observed: list[str] = []

        execution = await bridge.execute_plan(plan, on_event=lambda event: observed.append(event.event))

        goal = bridge.strategic_goal("GOAL:Deny Tutow runway")
        assert execution.status is OperationalPlanStatus.COMPLETED
        assert goal is not None
        assert goal.effect is StrategicGoalEffect.DENY_RUNWAY
        assert goal.status is StrategicGoalStatus.ACHIEVED
        assert execution.missions[0].status is PlanMissionStatus.SUCCEEDED
        assert "strategic.effect_confirmed" in observed
        command = bridge.server.commands[0]  # type: ignore[attr-defined]
        assert command.action == "auftrag.create_bombrunway"
        assert command.params["target"] == "AIRBASE:Tutow"

    asyncio.run(scenario())


def test_execute_disable_plan_blocks_when_bombrunway_fails() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_disable_plan(success=False)

        execution = await bridge.execute_plan(plan)

        goal = bridge.strategic_goal("GOAL:Deny Tutow runway")
        assert execution.status is OperationalPlanStatus.BLOCKED
        assert goal is not None
        assert goal.status is StrategicGoalStatus.ACTIVE
        assert execution.missions[0].status is PlanMissionStatus.FAILED

    asyncio.run(scenario())


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


def test_execute_capture_plan_sends_unit_aware_group_count_to_moose() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan(units_per_asset=4, min_unit_count=2)
        assessment = bridge.plans.assessment(plan.plan_id)

        execution = await bridge.execute_plan(plan)

        assert assessment is not None
        assert assessment.requirements[0].required_count == 1
        assert execution.status is OperationalPlanStatus.COMPLETED
        command = bridge.server.commands[0]  # type: ignore[attr-defined]
        assert command.params["required_assets_min"] == 1
        assert command.params["required_assets_max"] == 1

    asyncio.run(scenario())


def test_persistent_mission_is_established_at_executing_and_remains_running() -> None:
    async def scenario() -> None:
        server = _PersistentMissionExecutionServer()
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        execution = OperationalPlanExecution(
            plan_id="PLAN:Secure Town",
            commander_id="COMMANDER:Blue",
        )
        mission = PlanMissionExecution(
            phase_id="consolidate",
            intent_id="secure-zone",
            requirement_id="REQ:Ground security",
            mission_type="PATROLZONE",
            required=True,
            persistent=True,
            established_on="Executing",
            status=PlanMissionStatus.SUBMITTED,
            auftrag_id="AUFTRAG:1",
        )
        observed: list[str] = []

        established = await bridge.plan_executor._wait_for_mission(  # noqa: SLF001
            execution,
            mission,
            timeout_s=1,
            on_event=lambda event: observed.append(event.event),
        )

        assert established is True
        assert mission.status is PlanMissionStatus.RUNNING
        assert mission.outcome is None
        assert mission.error is None
        assert observed == ["mission.status", "mission.established"]
        assert server.commands == []

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


def test_arty_execution_synchronizes_resolver_range_before_submission() -> None:
    async def scenario() -> None:
        server = _ExecutionServer()
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
        bridge.state.apply_message(
            {
                "type": "snapshot",
                "kind": "cohorts",
                "payload": {"cohorts": [{"object_id": "COHORT:Paladin"}]},
            }
        )
        intent = MissionIntent(
            intent_id="fire-support",
            name="Fire support",
            auftrag_types=("ARTY",),
            target_object_id="GROUP:Target",
            asset_requirements=(
                AssetRequirement(
                    requirement_id="REQ:Artillery",
                    role=AssetRole.FIRES,
                    mission_types=("ARTY",),
                    allowed_cohort_ids=("COHORT:Paladin",),
                ),
            ),
            metadata={
                "fire_support": {
                    "cohort_id": "COHORT:Paladin",
                    "weapon_flag_value": int(DcsWeaponFlag.CONVENTIONAL_SHELL),
                    "minimum_m": 30.0,
                    "maximum_m": 22_000.0,
                    "range_sync_required": True,
                }
            },
        )

        ack = await bridge.plan_executor._synchronize_arty_weapon_range(
            intent,
            intent.asset_requirements[0],
            Auftrag_ARTY(target="GROUP:Target"),
        )

        assert ack is not None
        assert [command.action for command in server.commands] == ["cohort.set_weapon_range"]
        assert server.commands[0].params["weapon_type"] == int(DcsWeaponFlag.CONVENTIONAL_SHELL)
        assert server.commands[0].params["maximum_m"] == 22_000.0

        second = await bridge.plan_executor._synchronize_arty_weapon_range(
            intent,
            intent.asset_requirements[0],
            Auftrag_ARTY(target="GROUP:Target"),
        )
        assert second is None
        assert len(server.commands) == 1

    asyncio.run(scenario())


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


def test_execute_destroy_plan_replays_retained_scenery_destruction_before_assessment() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_scenery_destroy_plan()

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert execution.missions[0].status is PlanMissionStatus.SUCCEEDED
        assert "SCENERY:Bridge" in bridge.state.destroyed_object_ids
        objective = bridge.strategic_objective("OBJECTIVE:Bridge")
        goal = bridge.strategic_goal("GOAL:Destroy Bridge")
        assert objective is not None and objective.health == 0.0
        assert goal is not None and goal.status is StrategicGoalStatus.ACHIEVED
        assert execution.damage_assessments[0].achieved_damage == 1.0
        assert execution.damage_assessments[0].satisfied is True
        report = bridge.state.loss_reports["LOSS:STRATEGIC:OBJECTIVE:Bridge"]
        assert report["status"] == "destroyed"
        assert report["destroyed_component_ids"] == ["SCENERY:Bridge"]
        assert sum(event.get("event") == "object.destroyed" for event in bridge.state.events) == 1

    asyncio.run(scenario())


def test_execute_destroy_plan_does_not_duplicate_live_scenery_destruction_event() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_scenery_destroy_plan(_LiveSceneryDestroyExecutionServer())

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert sum(event.get("event") == "object.destroyed" for event in bridge.state.events) == 1

    asyncio.run(scenario())


def test_execute_destroy_plan_blocks_when_destruction_history_is_incomplete() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_scenery_destroy_plan(_IncompleteSceneryDestroyExecutionServer())

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.BLOCKED
        assert execution.blocked_reason == (
            "strategic goal monitoring failed: DCS destruction event history is incomplete; "
            "strategic damage cannot be assessed reliably"
        )
        assert "SCENERY:Bridge" not in bridge.state.destroyed_object_ids

    asyncio.run(scenario())


def test_execute_destroy_plan_treats_known_static_missing_from_full_refresh_as_destroyed() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_destroy_plan(summary_damage=0.0)
        server = _DisappearingStaticDestroyExecutionServer(summary_damage=0.0)
        _replace_destroy_server(bridge, server)

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.COMPLETED
        objective = bridge.strategic_objective("OBJECTIVE:Depot")
        assert objective is not None and objective.health == 0.4
        estimate = objective.component_health_estimates["STATIC:Main"]
        assert estimate.health == 0.0
        assert estimate.source == "snapshot_absent_after_refresh"
        assert execution.damage_assessments[0].component_health[0] == (
            "STATIC:Main",
            0.0,
            "snapshot_absent_after_refresh",
        )

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


def test_execute_plan_deduplicates_repeated_auftrag_status_events() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan()
        state = bridge.state
        server = _DuplicateStatusExecutionServer()
        server.state = state
        bridge.server = server  # type: ignore[assignment]
        observed: list[str] = []

        execution = await bridge.execute_plan(plan, on_event=lambda event: observed.append(str(event)))

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert sum("Queued status=queued planned->queued" in item for item in observed) == 1

    asyncio.run(scenario())


def test_execute_plan_prefers_evaluated_outcome_after_nested_cancel_event() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan()
        server = _CancelBeforeEvaluatedExecutionServer()
        server.state = bridge.state
        bridge.server = server  # type: ignore[assignment]
        observed: list[str] = []

        execution = await bridge.execute_plan(plan, on_event=lambda event: observed.append(str(event)))

        assert execution.status is OperationalPlanStatus.COMPLETED
        assert execution.missions[0].status is PlanMissionStatus.SUCCEEDED
        assert execution.missions[0].outcome is not None
        assert execution.missions[0].outcome.success is True
        assert any("Done status=done cancelled->done" in item for item in observed)
        assert any("Cancel status=done started->cancelled" in item for item in observed)
        assert any("mission.succeeded" in item for item in observed)
        assert not any("mission.cancelled" in item for item in observed)

    asyncio.run(scenario())


def test_execute_plan_uses_failed_evaluation_after_cancel_event() -> None:
    async def scenario() -> None:
        bridge, plan = _executable_capture_plan()
        server = _CancelBeforeEvaluatedExecutionServer(success=False)
        server.state = bridge.state
        bridge.server = server  # type: ignore[assignment]

        execution = await bridge.execute_plan(plan)

        assert execution.status is OperationalPlanStatus.BLOCKED
        assert execution.missions[0].status is PlanMissionStatus.FAILED
        assert execution.missions[0].outcome is not None
        assert execution.missions[0].outcome.success is False

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


def test_execution_history_does_not_cross_dcs_mission_generations(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "operational-audit.jsonl"
        first_bridge, first_plan = _executable_capture_plan(audit_path=path)
        first = await first_bridge.execute_plan(first_plan)
        assert first.attempt_number == 1
        first_bridge.server.audit_store.close()  # type: ignore[attr-defined]

        second_bridge, second_plan = _executable_capture_plan(audit_path=path)
        second_bridge.server.state.mission_generation = 1  # type: ignore[attr-defined]

        assert await second_bridge.refresh_operational_plan_executions(second_plan) == ()
        second = await second_bridge.execute_plan(second_plan)
        assert second.attempt_number == 1
        assert second.attempt_id == "PLAN:Capture Town/ATTEMPT:1"
        second_bridge.server.audit_store.close()  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_execution_history_does_not_cross_server_audit_sessions(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "operational-audit.jsonl"
        first_bridge, first_plan = _executable_capture_plan(
            audit_path=path,
            audit_session_id="server-first",
        )
        first = await first_bridge.execute_plan(first_plan)
        assert first.attempt_number == 1
        first_bridge.server.audit_store.close()  # type: ignore[attr-defined]

        second_bridge, second_plan = _executable_capture_plan(
            audit_path=path,
            audit_session_id="server-second",
        )

        assert await second_bridge.refresh_operational_plan_executions(second_plan) == ()
        second = await second_bridge.execute_plan(second_plan)
        assert second.attempt_number == 1
        assert second.attempt_id == "PLAN:Capture Town/ATTEMPT:1"
        second_bridge.server.audit_store.close()  # type: ignore[attr-defined]

    asyncio.run(scenario())


def test_restore_rejects_audit_records_without_strategic_snapshots(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "legacy-audit.jsonl"
        store = AuditStore(path)
        store.append(
            "operational_plan.execution",
            {
                "audit_session_id": "test-session",
                "mission_generation": 0,
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
