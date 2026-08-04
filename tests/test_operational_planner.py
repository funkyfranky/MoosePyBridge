from __future__ import annotations

from moosebridge import (
    Intel,
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
from moosebridge.intelligence import IntelContactMemory
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


def _contact(
    object_id: str,
    target_id: str,
    x: float,
    z: float,
    threat: float,
    *,
    detected_time: float = 300.0,
) -> IntelContact:
    return IntelContact.from_payload(
        {
            "object_id": object_id,
            "target_object_id": target_id,
            "is_ground": True,
            "x": x,
            "z": z,
            "threat_level": threat,
            "detected_time": detected_time,
        }
    )


def _intel(*, running: bool = True, alive_agents: int | None = 4) -> Intel:
    return Intel.from_payload(
        {
            "object_id": "INTEL:Blue",
            "coalition": "blue",
            "is_running": running,
            "agent_count": 4,
            "alive_agent_count": alive_agents,
        }
    )


def test_rule_based_capture_proposal_uses_highest_threat_visible_nearby_defender() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
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
    assert plan.proposal_issues == ()


def test_rule_based_capture_proposal_omits_isolation_without_visible_defender() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=321.5),
        opszones=[_zone()],
        contacts=[_contact("INTELCONTACT:Far", "GROUP:Far away", 200_000, 200_000, 10)],
    )

    plan = bridge.propose_capture_plan(goal.goal_id, picture, plan_id="PLAN:Conservative Town")

    assert plan.plan_id == "PLAN:Conservative Town"
    assert [phase.phase_id for phase in plan.phases] == ["seize", "consolidate"]
    assert plan.phases[0].depends_on == ()
    assert "no isolation strike" in (plan.provenance.rationale or "").lower()  # type: ignore[union-attr]
    assert [issue.code for issue in plan.proposal_issues] == ["intel_no_visible_defenders"]
    assert "not evidence" in plan.proposal_issues[0].message


def test_rule_based_capture_proposal_requests_recon_for_important_lost_contact() -> None:
    bridge, goal, _ = _capture_context()
    lost = _contact("INTELCONTACT:Lost", "GROUP:Lost armor", 102_000, 201_000, 7, detected_time=450.0)
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=500.0),
        opszones=[_zone()],
        lost_contacts=[IntelContactMemory(lost, lost_time=470.0, event_id="event-lost")],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert "reconnaissance_required" in {issue.code for issue in plan.proposal_issues}
    assert [phase.phase_id for phase in plan.phases] == ["recon", "seize", "consolidate"]
    recon_intent = plan.phases[0].intents[0]
    assert recon_intent.auftrag_types == ("RECON",)
    assert recon_intent.target_object_id == "OPSZONE:Town"
    assert "intel_id" not in recon_intent.metadata["auftrag_params"]
    assert plan.phases[0].metadata["requires_tactical_replanning"] is True
    assert plan.phases[1].depends_on == ("recon",)
    requirement = plan.metadata["reconnaissance_requirement"]
    assert requirement["target_object_id"] == "GROUP:Lost armor"
    assert requirement["last_known_x"] == 102_000
    assert requirement["threat_level"] == 7


def test_rule_based_capture_proposal_ignores_unimportant_lost_contact_for_recon() -> None:
    bridge, goal, _ = _capture_context()
    lost = _contact("INTELCONTACT:Lost", "GROUP:Lost truck", 102_000, 201_000, 1, detected_time=450.0)
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=500.0),
        opszones=[_zone()],
        lost_contacts=[IntelContactMemory(lost, lost_time=470.0)],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert "reconnaissance_required" not in {issue.code for issue in plan.proposal_issues}
    assert plan.metadata["reconnaissance_requirement"] is None


def test_rule_based_capture_proposal_does_not_target_stale_contact() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=1_000.0),
        opszones=[_zone()],
        contacts=[_contact("INTELCONTACT:Stale", "GROUP:Stale", 101_000, 201_000, 10, detected_time=100.0)],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert [phase.phase_id for phase in plan.phases] == ["seize", "consolidate"]
    assert "intel_no_visible_defenders" in {issue.code for issue in plan.proposal_issues}


def test_rule_based_capture_proposal_reports_unavailable_intel_coverage() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(running=False, alive_agents=0),
        opszones=[_zone()],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert {issue.code for issue in plan.proposal_issues} == {
        "intel_not_running",
        "intel_no_alive_agents",
        "intel_no_visible_defenders",
    }


def test_rule_based_capture_proposal_rejects_wrong_picture_coalition() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(coalition="red", intel_id="INTEL:Red", opszones=[_zone()])

    try:
        bridge.propose_capture_plan(goal, picture)
    except ValueError as exc:
        assert "coalition" in str(exc)
    else:
        raise AssertionError("Planner should reject an opposing coalition tactical picture")
