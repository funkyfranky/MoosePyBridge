from __future__ import annotations

from moosebridge import (
    MooseBridgeClient,
    ObjectiveKind,
    OperationalPlanStatus,
    OwnershipPolicy,
    PlanSourceType,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
)
from moosebridge.clock import DcsTime
from moosebridge.models import IntelContact, OpsZone
from moosebridge.pictures import TacticalPicture
from moosebridge.server import MooseBridgeServer


def _capture_context() -> tuple[MooseBridgeClient, StrategicGoal, StrategicObjective]:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Town",
            name="Town",
            kind=ObjectiveKind.OPSZONE,
            control_object_id="OPSZONE:Town",
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
            owner="red",
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Blue capture Town",
            name="Blue capture Town",
            coalition="blue",
            action=StrategicGoalAction.CAPTURE,
            objective_id=objective.objective_id,
        )
    )
    return bridge, goal, objective


def _zone() -> OpsZone:
    return OpsZone.from_payload(
        {
            "object_id": "OPSZONE:Town",
            "dcs_name": "Town",
            "x": 100_000,
            "z": 200_000,
            "zone_radius": 5_000,
            "owner_current_name": "red",
        }
    )


def _contact(object_id: str, target_id: str, x: float, z: float, threat: float) -> IntelContact:
    return IntelContact.from_payload(
        {
            "object_id": object_id,
            "target_object_id": target_id,
            "is_ground": True,
            "x": x,
            "z": z,
            "threat_level": threat,
        }
    )


def test_rule_based_capture_proposal_uses_highest_threat_visible_nearby_defender() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        clock=DcsTime(mission_time=321.5),
        opszones=[_zone()],
        contacts=[
            _contact("INTELCONTACT:Low", "GROUP:Low threat", 101_000, 201_000, 2),
            _contact("INTELCONTACT:High", "GROUP:High threat", 110_000, 200_000, 8),
            _contact("INTELCONTACT:Far", "GROUP:Far away", 200_000, 200_000, 10),
        ],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert plan.status is OperationalPlanStatus.DRAFT
    assert bridge.operational_plan(plan.plan_id) is None
    assert [phase.phase_id for phase in plan.phases] == ["isolate", "seize", "consolidate"]
    assert plan.phases[0].intents[0].target_object_id == "GROUP:High threat"
    assert plan.phases[1].depends_on == ("isolate",)
    assert plan.phases[1].intents[0].target_object_id == "OPSZONE:Town"
    assert plan.phases[1].intents[0].asset_requirements[0].min_count == 2
    assert plan.provenance is not None
    assert plan.provenance.source_type is PlanSourceType.RULE_ENGINE
    assert plan.provenance.picture_mission_time == 321.5
    assert "GROUP:High threat" in (plan.provenance.rationale or "")


def test_rule_based_capture_proposal_omits_isolation_without_visible_defender() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        opszones=[_zone()],
        contacts=[_contact("INTELCONTACT:Far", "GROUP:Far away", 200_000, 200_000, 10)],
    )

    plan = bridge.propose_capture_plan(goal.goal_id, picture, plan_id="PLAN:Conservative Town")

    assert plan.plan_id == "PLAN:Conservative Town"
    assert [phase.phase_id for phase in plan.phases] == ["seize", "consolidate"]
    assert plan.phases[0].depends_on == ()
    assert "no isolation strike" in (plan.provenance.rationale or "").lower()  # type: ignore[union-attr]


def test_rule_based_capture_proposal_rejects_wrong_picture_coalition() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(coalition="red", intel_id="INTEL:Red", opszones=[_zone()])

    try:
        bridge.propose_capture_plan(goal, picture)
    except ValueError as exc:
        assert "coalition" in str(exc)
    else:
        raise AssertionError("Planner should reject an opposing coalition tactical picture")
