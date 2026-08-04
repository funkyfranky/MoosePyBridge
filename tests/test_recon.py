from __future__ import annotations

from moosebridge.diagnostics import format_recon_outcome
from moosebridge.models import IntelContact, OpsZone
from moosebridge.outcomes import AuftragOutcome
from moosebridge.pictures import TacticalPicture
from moosebridge.recon import (
    ReconRelevantTarget,
    ReconRequirement,
    ReconTargetSource,
    build_recon_outcome,
    derive_recon_requirement,
)
from moosebridge.strategic import (
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
)


def _outcome() -> AuftragOutcome:
    return AuftragOutcome.from_snapshot(
        {
            "object_id": "AUFTRAG:1",
            "type": "Recon",
            "status": "done",
            "summary": {"success": True},
        }
    )


def _event(name: str, time: float, payload: dict[str, object]) -> dict[str, object]:
    return {"type": "event", "event": name, "mission_time": time, "payload": payload}


def _contact(contact_id: str, target: str, recce_group: str, threat: float) -> dict[str, object]:
    return {
        "object_id": contact_id,
        "object_type": "INTELCONTACT",
        "intel_id": "INTEL:Blue Intel",
        "target_object_id": target,
        "recce": "MQ-9-1",
        "recce_unit_id": "UNIT:MQ-9-1",
        "recce_group_id": recce_group,
        "threat_level": threat,
    }


def test_build_recon_outcome_correlates_assigned_assets_and_contact_lifecycle() -> None:
    events = [
        _event("auftrag.status", 20, {"auftrag_id": "AUFTRAG:1", "fsm_event": "Started"}),
        _event("intel.lost_contact", 21, {"intel_id": "INTEL:Blue Intel", "contact": _contact("CONTACT:Old", "GROUP:Old", "GROUP:Other", 2)}),
        _event("auftrag.status", 25, {"auftrag_id": "AUFTRAG:1", "fsm_event": "Executing"}),
        _event("intel.new_contact", 30, {"intel_id": "INTEL:Blue Intel", "contact": _contact("CONTACT:Old", "GROUP:Old", "GROUP:MQ-9", 4)}),
        _event("intel.new_contact", 31, {"intel_id": "INTEL:Blue Intel", "contact": _contact("CONTACT:New", "GROUP:New", "GROUP:MQ-9", 6)}),
        _event("intel.new_contact", 32, {"intel_id": "INTEL:Blue Intel", "contact": _contact("CONTACT:Ignored", "GROUP:Ignored", "GROUP:Other", 10)}),
        _event("intel.lost_contact", 35, {"intel_id": "INTEL:Blue Intel", "contact": _contact("CONTACT:New", "GROUP:New", "GROUP:MQ-9", 6)}),
        _event("auftrag.status", 40, {"auftrag_id": "AUFTRAG:1", "fsm_event": "Done"}),
    ]
    outcome = build_recon_outcome(
        auftrag_id="AUFTRAG:1",
        intel_id="INTEL:Blue Intel",
        mission_outcome=_outcome(),
        events=events,
        baseline_contact_ids=("CONTACT:Old",),
        assigned_opsgroup_ids=("OPSGROUP:MQ-9",),
        assigned_group_ids=("GROUP:MQ-9",),
        relevant_target_ids=("GROUP:Old", "GROUP:New", "GROUP:Unknown"),
    )

    assert outcome.mission_outcome.success is True
    assert outcome.started_time == 20
    assert outcome.executing_time == 25
    assert outcome.completed_time == 40
    assert outcome.new_contact_count == 1
    assert outcome.reacquired_contact_count == 1
    assert outcome.lost_contact_count == 1
    assert outcome.maximum_threat == 6
    assert outcome.total_threat == 10
    assert outcome.first_intelligence_delay == 5
    assert outcome.observed_relevant_target_ids == ("GROUP:New", "GROUP:Old")
    assert outcome.lost_relevant_target_ids == ("GROUP:New",)
    assert outcome.unknown_relevant_target_ids == ("GROUP:Unknown",)
    assert {item.contact_id for item in outcome.observations} == {"CONTACT:Old", "CONTACT:New"}

    text = format_recon_outcome(outcome)
    assert "MOOSE success=True contacts=2 new=1 reacquired=1 lost=1" in text
    assert "relevant unknown: GROUP:Unknown" in text


def test_recon_outcome_reports_partial_event_history() -> None:
    outcome = build_recon_outcome(
        auftrag_id="AUFTRAG:1",
        intel_id="INTEL:Blue Intel",
        mission_outcome=_outcome(),
        events=(),
        baseline_contact_ids=(),
        assigned_opsgroup_ids=(),
        assigned_group_ids=(),
        event_history_complete=False,
    )
    assert outcome.to_dict()["event_history_complete"] is False
    assert "assessment is partial" in format_recon_outcome(outcome)


def test_recon_requirement_derives_targets_with_provenance_from_private_picture() -> None:
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Town",
        name="Town",
        kind=ObjectiveKind.OPSZONE,
        control_object_id="OPSZONE:Town",
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        components=(ObjectiveComponent("STATIC:Depot", role="logistics"),),
    )
    goal = StrategicGoal(
        goal_id="GOAL:Town",
        name="Capture Town",
        coalition="blue",
        action=StrategicGoalAction.CAPTURE,
        objective_id=objective.objective_id,
        metadata={"relevant_target_ids": ("GROUP:Goal Target",)},
    )
    nearby = IntelContact.from_payload(
        {
            "object_id": "CONTACT:Nearby",
            "target_object_id": "GROUP:Nearby",
            "x": 12_000,
            "z": 0,
            "threat_level": 4,
            "is_ground": True,
        }
    )
    far = IntelContact.from_payload(
        {"object_id": "CONTACT:Far", "target_object_id": "GROUP:Far", "x": 100_000, "z": 0, "is_ground": True}
    )
    aircraft = IntelContact.from_payload(
        {"object_id": "CONTACT:Air", "target_object_id": "GROUP:Fighter", "x": 1_000, "z": 0}
    )
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        contacts=[nearby, far, aircraft],
        opszones=[OpsZone.from_payload({"object_id": "OPSZONE:Town", "x": 0, "z": 0, "zone_radius": 5_000})],
    )

    requirement = derive_recon_requirement(
        goal,
        objective,
        picture,
        manual_target_ids=("GROUP:Nearby", "GROUP:Manual"),
        area_buffer_m=20_000,
    )

    assert requirement.relevant_target_ids == (
        "GROUP:Nearby",
        "GROUP:Manual",
        "GROUP:Goal Target",
        "STATIC:Depot",
    )
    nearby_target = next(item for item in requirement.relevant_targets if item.object_id == "GROUP:Nearby")
    assert nearby_target.sources == (ReconTargetSource.MANUAL, ReconTargetSource.INTEL_CONTACT)
    assert "GROUP:Far" not in requirement.relevant_target_ids
    assert "GROUP:Fighter" not in requirement.relevant_target_ids
    assert ReconRequirement.from_dict(requirement.to_dict()) == requirement


def test_recon_requirement_can_be_strictly_manual() -> None:
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Town",
        name="Town",
        kind=ObjectiveKind.OPSZONE,
        control_object_id="OPSZONE:Town",
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        components=(ObjectiveComponent("STATIC:Depot"),),
    )
    goal = StrategicGoal(
        goal_id="GOAL:Town",
        name="Capture Town",
        coalition="blue",
        action=StrategicGoalAction.CAPTURE,
        objective_id=objective.objective_id,
        metadata={"relevant_target_ids": ("GROUP:Automatic",)},
    )
    requirement = derive_recon_requirement(
        goal,
        objective,
        TacticalPicture(coalition="blue", intel_id="INTEL:Blue"),
        manual_target_ids=("GROUP:Manual",),
        derive_targets=False,
    )
    assert requirement.relevant_target_ids == ("GROUP:Manual",)


def test_recon_requirement_accepts_fresh_baseline_contact_without_claiming_mission_detection() -> None:
    requirement = ReconRequirement(
        area_object_id="ZONE:Recon",
        relevant_targets=(
            ReconRelevantTarget(
                "GROUP:Known",
                (ReconTargetSource.INTEL_CONTACT,),
                confidence=0.9,
                information_age_s=30,
            ),
        ),
    )
    outcome = build_recon_outcome(
        auftrag_id="AUFTRAG:1",
        intel_id="INTEL:Blue",
        mission_outcome=_outcome(),
        events=(),
        baseline_contact_ids=("CONTACT:Known",),
        assigned_opsgroup_ids=(),
        assigned_group_ids=(),
        requirement=requirement,
    )
    assert outcome.observed_relevant_target_ids == ()
    assert outcome.satisfied_relevant_target_ids == ("GROUP:Known",)
    assert outcome.requirement_satisfied is True
