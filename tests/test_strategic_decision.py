from __future__ import annotations

from moosebridge import (
    AssetRequirement,
    AssetRole,
    BilateralStrategicRecommendation,
    Cohort,
    CohortAllocation,
    CoalitionDoctrine,
    CoalitionRelationship,
    MissionIntent,
    ObjectiveComponent,
    ObjectiveKind,
    OperationalPlan,
    OperationalPlanAssessment,
    OwnershipPolicy,
    PlanPhase,
    RequirementAssessment,
    StrategicActionSpec,
    StrategicDecisionConfig,
    StrategicDecisionDisposition,
    StrategicDecisionPortfolio,
    StrategicDecisionReasonCode,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
    derive_strategic_action_specs,
    format_bilateral_strategic_recommendation,
    score_strategic_candidate,
    strategic_recommendation_to_dict,
)
from moosebridge.clock import DcsTime
from moosebridge.models import IntelContact, OpsZone
from moosebridge.pictures import TacticalPicture
from moosebridge.sdk import MooseBridgeClient
from moosebridge.server import MooseBridgeServer


def _objective(
    suffix: str,
    kind: ObjectiveKind,
    owner: str | None,
    *,
    value: float = 60.0,
    targetable: bool = False,
) -> StrategicObjective:
    components = (
        (
            ObjectiveComponent(
                f"SCENERY:{suffix}",
                metadata={"x": 100_000.0, "z": 200_000.0},
            ),
        )
        if targetable
        else ()
    )
    control_id = f"OPSZONE:{suffix}" if kind is ObjectiveKind.OPSZONE else None
    return StrategicObjective(
        objective_id=f"OBJECTIVE:{suffix}",
        name=suffix,
        kind=kind,
        control_object_id=control_id,
        ownership_policy=(
            OwnershipPolicy.MOOSE_MANAGED
            if kind is ObjectiveKind.OPSZONE
            else OwnershipPolicy.FIXED
        ),
        components=components,
        strategic_value=value,
        priority=value,
        owner=owner,
        metadata={
            "targetable": targetable,
            "dcs_verification_state": "represented" if targetable else "unverified",
        },
    )


def _war() -> CoalitionRelationship:
    relationship = CoalitionRelationship()
    relationship.declare_war("blue", reason="test", mission_time=1.0)
    return relationship


def _zone(name: str) -> OpsZone:
    return OpsZone.from_payload(
        {
            "object_id": f"OPSZONE:{name}",
            "dcs_name": name,
            "x": 100_000,
            "z": 200_000,
            "zone_radius": 5_000,
            "owner_current_name": "red",
            "threat_red": 99,
            "n_red": 99,
        }
    )


def _apply_blue_capture_force(bridge: MooseBridgeClient, *, available: int = 2) -> None:
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [
                    {"object_id": "LEGION:Blue Brigade", "coalition": "blue"},
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
                        "object_id": "COHORT:Blue Infantry",
                        "legion_id": "LEGION:Blue Brigade",
                        "is_ground": True,
                        "stock_asset_count": available,
                        "available_asset_count": available,
                        "homogeneous": True,
                        "units_per_asset": 2,
                        "mission_types": ["CAPTUREZONE", "PATROLZONE", "ONGUARD"],
                        "mission_performance": {
                            "CAPTUREZONE": 85,
                            "PATROLZONE": 80,
                            "ONGUARD": 80,
                        },
                    }
                ]
            },
        }
    )


def test_candidate_matrix_applies_ownership_target_and_relationship_gates() -> None:
    objectives = (
        _objective("Own zone", ObjectiveKind.OPSZONE, "blue"),
        _objective("Enemy zone", ObjectiveKind.OPSZONE, "red"),
        _objective("Enemy airbase", ObjectiveKind.AIRBASE, "red"),
        _objective("Enemy bridge", ObjectiveKind.INFRASTRUCTURE, "red", targetable=True),
        _objective("Neutral depot", ObjectiveKind.DEPOT, None, targetable=True),
    )

    specs = derive_strategic_action_specs(
        objectives,
        "blue",
        relationship=_war(),
        config=StrategicDecisionConfig(),
    )
    decisions = {(item.objective.objective_id, item.action): item for item in specs}

    assert decisions[("OBJECTIVE:Own zone", StrategicGoalAction.DEFEND)].rejection_code is None
    assert decisions[("OBJECTIVE:Enemy zone", StrategicGoalAction.CAPTURE)].rejection_code is None
    assert decisions[("OBJECTIVE:Enemy bridge", StrategicGoalAction.DESTROY)].rejection_code is None
    assert decisions[("OBJECTIVE:Neutral depot", None)].rejection_code is StrategicDecisionReasonCode.NEUTRAL_PROTECTED
    assert decisions[("OBJECTIVE:Enemy airbase", StrategicGoalAction.CAPTURE)].rejection_code is StrategicDecisionReasonCode.ACTION_NOT_SUPPORTED
    assert decisions[("OBJECTIVE:Enemy airbase", StrategicGoalAction.DISABLE)].rejection_code is None


def test_offensive_candidate_is_rejected_during_peace() -> None:
    specs = derive_strategic_action_specs(
        (_objective("Enemy zone", ObjectiveKind.OPSZONE, "red"),),
        "blue",
        relationship=CoalitionRelationship(),
        config=StrategicDecisionConfig(),
    )

    assert specs[0].rejection_code is StrategicDecisionReasonCode.RELATIONSHIP_FORBIDS


def test_opszone_urgency_uses_private_intel_not_global_zone_counts() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    _apply_blue_capture_force(bridge)
    bridge.relationship = _war()
    objective = _objective("Enemy zone", ObjectiveKind.OPSZONE, "red", value=90)
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        clock=DcsTime(mission_time=100),
        opszones=[_zone("Enemy zone")],
    )
    portfolio = bridge.recommend_strategic_portfolio(
        "blue",
        picture,
        objectives=(objective,),
    )

    assert portfolio.selected[0].score is not None
    assert portfolio.selected[0].score.urgency == 55.0


def test_operational_score_uses_resolver_eta_from_mission_intent() -> None:
    objective = _objective("Enemy bridge", ObjectiveKind.INFRASTRUCTURE, "red", targetable=True)
    requirement = AssetRequirement(
        "REQ:Strike",
        AssetRole.COMBAT,
        mission_types=("STRIKE",),
        performer_categories=("AIR",),
    )
    intent = MissionIntent(
        "destroy",
        "Destroy bridge",
        ("STRIKE",),
        (requirement,),
        target_object_id="SCENERY:Enemy bridge",
        metadata={
            "mission_assignments": [
                {
                    "cohort_id": "COHORT:Strike",
                    "estimated_time_to_effect_s": 90.0,
                }
            ],
            "estimated_time_to_effect_s": 90.0,
        },
    )
    plan = OperationalPlan(
        "PLAN:Strike",
        "Strike",
        "GOAL:Strike",
        "blue",
        (PlanPhase("strike", "Strike", (intent,)),),
    )
    assessment = OperationalPlanAssessment(
        plan.plan_id,
        True,
        (
            RequirementAssessment(
                "strike",
                "destroy",
                "REQ:Strike",
                1,
                1,
                ("COHORT:Strike",),
                (CohortAllocation("COHORT:Strike", "LEGION:Blue", 1),),
                True,
                0,
            ),
        ),
        (),
    )
    cohort = Cohort.from_payload(
        {
            "object_id": "COHORT:Strike",
            "legion_id": "LEGION:Blue",
            "is_air": True,
            "mission_types": ["STRIKE"],
            "mission_performance": {"STRIKE": 90.0},
        }
    )

    score = score_strategic_candidate(
        StrategicActionSpec(
            "blue:destroy:Enemy bridge",
            "blue",
            objective,
            StrategicGoalAction.DESTROY,
        ),
        plan=plan,
        picture=TacticalPicture(coalition="blue", intel_id="INTEL:Blue"),
        doctrine=CoalitionDoctrine.from_preset("balanced"),
        assessment=assessment,
        cohorts={cohort.object_id: cohort},
        config=StrategicDecisionConfig(),
    )

    assert round(score.operational, 3) == 90.273


def test_recommendation_ranks_and_reserves_without_mutating_registries() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    _apply_blue_capture_force(bridge, available=1)
    bridge.relationship = _war()
    high = _objective("High", ObjectiveKind.OPSZONE, "red", value=90)
    low = _objective("Low", ObjectiveKind.OPSZONE, "red", value=30)
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        clock=DcsTime(mission_time=100),
        opszones=[_zone("High"), _zone("Low")],
    )
    before = (
        len(bridge.strategic_objectives()),
        len(bridge.strategic_goals()),
        len(bridge.operational_plans()),
    )

    first = bridge.recommend_strategic_portfolio(
        "blue",
        picture,
        objectives=(low, high),
        config=StrategicDecisionConfig(max_concurrent_goals=2),
    )
    second = bridge.recommend_strategic_portfolio(
        "blue",
        picture,
        objectives=(low, high),
        config=StrategicDecisionConfig(max_concurrent_goals=2),
    )

    assert [item.objective_id for item in first.selected] == [high.objective_id]
    assert first.deferred[0].reason_code is StrategicDecisionReasonCode.RESOURCE_CONFLICT
    assert first.selected[0].reserved_assets == (("COHORT:Blue Infantry", 1),)
    assert [item.candidate_id for item in first.decisions] == [
        item.candidate_id for item in second.decisions
    ]
    assert before == (
        len(bridge.strategic_objectives()),
        len(bridge.strategic_goals()),
        len(bridge.operational_plans()),
    )


def test_recommendation_refreshes_dynamic_control_on_a_private_objective_copy() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    _apply_blue_capture_force(bridge)
    bridge.relationship = _war()
    objective = _objective("Changed owner", ObjectiveKind.OPSZONE, "red")
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "opszones",
            "payload": {
                "opszones": [
                    {
                        "object_id": "OPSZONE:Changed owner",
                        "dcs_name": "Changed owner",
                        "owner_current_name": "blue",
                    }
                ]
            },
        }
    )
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        opszones=[_zone("Changed owner")],
    )

    portfolio = bridge.recommend_strategic_portfolio(
        "blue",
        picture,
        objectives=(objective,),
    )

    assert portfolio.selected[0].action is StrategicGoalAction.DEFEND
    assert objective.owner == "red"


def test_open_goal_consumes_concurrency_and_duplicate_objective_is_rejected() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    _apply_blue_capture_force(bridge)
    bridge.relationship = _war()
    busy = bridge.add_strategic_objective(_objective("Busy", ObjectiveKind.OPSZONE, "red"))
    bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Busy",
            name="Busy",
            coalition="blue",
            action=StrategicGoalAction.CAPTURE,
            objective_id=busy.objective_id,
            status=StrategicGoalStatus.ACTIVE,
        )
    )
    target = _objective("Target", ObjectiveKind.OPSZONE, "red")
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        opszones=[_zone("Busy"), _zone("Target")],
    )

    portfolio = bridge.recommend_strategic_portfolio(
        "blue",
        picture,
        objectives=(busy, target),
        config=StrategicDecisionConfig(max_concurrent_goals=1),
    )

    assert not portfolio.selected
    assert portfolio.existing_open_goal_count == 1
    assert next(item for item in portfolio.decisions if item.objective_id == busy.objective_id).reason_code is StrategicDecisionReasonCode.DUPLICATE_OPEN_GOAL
    assert next(item for item in portfolio.decisions if item.objective_id == target.objective_id).reason_code is StrategicDecisionReasonCode.CONCURRENCY_LIMIT


def test_recommendation_audit_and_formatter_keep_reason_codes() -> None:
    decision = StrategicDecisionPortfolio(
        coalition="blue",
        mission_time=20.0,
        decisions=(),
        max_concurrent_goals=2,
    )
    recommendation = BilateralStrategicRecommendation(3, 20.0, "war", (decision,))

    payload = strategic_recommendation_to_dict(recommendation)
    output = format_bilateral_strategic_recommendation(recommendation)

    assert payload["schema_version"] == 1
    assert payload["relationship_state"] == "war"
    assert "relationship=war" in output
