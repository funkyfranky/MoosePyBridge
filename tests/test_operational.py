from __future__ import annotations

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
)


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
