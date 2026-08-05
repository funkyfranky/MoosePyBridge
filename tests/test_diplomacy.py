from __future__ import annotations

import asyncio

from moosebridge import (
    BorderViolationTracker,
    CoalitionDoctrine,
    CoalitionDoctrinePreset,
    CoalitionRelationship,
    EscalationIncident,
    EscalationIncidentType,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveKind,
    OwnershipPolicy,
    RelationshipState,
    StrategicGoalAction,
    StrategicObjective,
    Territory,
    format_coalition_doctrine,
    format_relationship,
)
from moosebridge.diplomacy import apply_diplomacy_state, diplomacy_state_to_dict


def _incident(
    number: int,
    incident_type: EscalationIncidentType,
    *,
    actor: str = "red",
    target: str = "blue",
) -> EscalationIncident:
    return EscalationIncident(
        incident_id=f"INCIDENT:{number}",
        incident_type=incident_type,
        actor_coalition=actor,
        target_coalition=target,
        mission_time=float(number),
    )


def test_relationship_supports_explicit_manual_transition_approval() -> None:
    relationship = CoalitionRelationship(
        state=RelationshipState.PEACE,
        automatic_transitions=False,
    )

    proposal = relationship.record_incident(_incident(1, EscalationIncidentType.UNIT_DESTROYED))

    assert proposal is not None
    assert proposal.from_state is RelationshipState.PEACE
    assert proposal.to_state is RelationshipState.TENSE
    assert proposal.automatic is False
    assert relationship.state is RelationshipState.PEACE
    assert relationship.escalation_score == 20.0
    assert relationship.responsibility("red") == 20.0
    assert relationship.responsibility("blue") == 0.0

    relationship.approve_transition(proposal.proposal_id)
    assert relationship.state is RelationshipState.TENSE
    assert relationship.pending_transition is None


def test_relationship_deduplicates_incidents_by_stable_id() -> None:
    relationship = CoalitionRelationship()
    incident = _incident(1, EscalationIncidentType.UNIT_DESTROYED)

    relationship.record_incident(incident)
    assert relationship.record_incident(incident) is None

    assert len(relationship.incidents) == 1
    assert relationship.escalation_score == 20.0


def test_diplomacy_state_round_trip_preserves_relationship_and_doctrines() -> None:
    source = MooseBridgeClient(MooseBridgeServer())
    source.relationship.automatic_transitions = False
    source.set_opszone_strategic_value("OPSZONE:Capital", 45)
    source.record_escalation_incident(_incident(1, EscalationIncidentType.UNIT_DESTROYED))
    source.set_coalition_doctrine("blue", CoalitionDoctrinePreset.DEFENSIVE)
    payload = diplomacy_state_to_dict(
        source.relationship,
        source.coalition_doctrines,
        mission_generation=7,
    )
    target = MooseBridgeClient(MooseBridgeServer())

    apply_diplomacy_state(payload, target.relationship, target.coalition_doctrines)

    assert target.relationship.state is RelationshipState.PEACE
    assert target.relationship.escalation_score == 20.0
    assert target.relationship.pending_transition is not None
    assert target.relationship.pending_transition.to_state is RelationshipState.TENSE
    assert target.relationship.get_opszone_capture_points("OPSZONE:Capital") == 45
    assert target.relationship.get_opszone_capture_points("OPSZONE:Other") == 20
    assert target.coalition_doctrines.get("blue").preset is CoalitionDoctrinePreset.DEFENSIVE


def test_opszone_strategic_value_rejects_invalid_ids_and_values() -> None:
    client = MooseBridgeClient(MooseBridgeServer())

    for object_id, points in (("ZONE:Town", 20), ("OPSZONE:", 20), ("OPSZONE:Town", -1)):
        try:
            client.set_opszone_strategic_value(object_id, points)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid OPSZONE strategic value: {object_id}, {points}")


def test_legacy_diplomacy_snapshot_migrates_to_automatic_transitions() -> None:
    source = MooseBridgeClient(MooseBridgeServer())
    source.relationship.automatic_transitions = False
    source.record_escalation_incident(_incident(1, EscalationIncidentType.UNIT_DESTROYED))
    payload = diplomacy_state_to_dict(
        source.relationship,
        source.coalition_doctrines,
        mission_generation=1,
    )
    del payload["diplomacy_schema_version"]
    target = MooseBridgeClient(MooseBridgeServer())

    apply_diplomacy_state(payload, target.relationship, target.coalition_doctrines)

    assert target.relationship.automatic_transitions is True
    assert target.relationship.state is RelationshipState.TENSE
    assert target.relationship.pending_transition is None


def test_sdk_persists_and_restores_diplomacy_for_current_mission_generation() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        server.state.mission_generation = 4
        writer = MooseBridgeClient(server)
        writer.record_escalation_incident(_incident(1, EscalationIncidentType.UNIT_DESTROYED))
        writer.set_coalition_doctrine("red", CoalitionDoctrinePreset.AGGRESSIVE)
        await writer.persist_diplomacy_state()

        reader = MooseBridgeClient(server)
        assert await reader.refresh_diplomacy_state() is True
        assert reader.relationship.escalation_score == 20.0
        assert reader.coalition_doctrines.get("red").preset is CoalitionDoctrinePreset.AGGRESSIVE

        server.state.mission_generation = 5
        reader.reset_mission(reset_state=False)
        assert await reader.refresh_diplomacy_state() is False
        assert reader.relationship.escalation_score == 0.0

    asyncio.run(scenario())


def test_relationship_can_apply_automatic_escalation_but_not_deescalation() -> None:
    relationship = CoalitionRelationship()

    first = relationship.record_incident(_incident(1, EscalationIncidentType.UNIT_DESTROYED))
    assert first is not None and first.automatic is True
    assert relationship.state is RelationshipState.TENSE

    relationship.record_incident(_incident(2, EscalationIncidentType.UNIT_DESTROYED))
    limited = relationship.record_incident(_incident(3, EscalationIncidentType.UNIT_HIT))
    assert limited is not None and limited.to_state is RelationshipState.LIMITED_CONFLICT
    assert relationship.state is RelationshipState.LIMITED_CONFLICT

    relationship.reduce_tension(50)
    relationship.record_incident(_incident(4, EscalationIncidentType.BORDER_VIOLATION))
    assert relationship.state is RelationshipState.LIMITED_CONFLICT


def test_doctrine_is_mutable_and_independent_from_relationship() -> None:
    client = MooseBridgeClient(MooseBridgeServer())
    client.relationship.state = RelationshipState.TENSE

    doctrine = client.set_coalition_doctrine("blue", CoalitionDoctrinePreset.DEFENSIVE)

    assert doctrine.preset is CoalitionDoctrinePreset.DEFENSIVE
    assert doctrine.defense_bias > doctrine.offense_bias
    assert client.relationship.state is RelationshipState.TENSE
    assert "doctrine=defensive" in format_coalition_doctrine("blue", doctrine)

    custom = CoalitionDoctrine(
        CoalitionDoctrinePreset.BALANCED,
        defense_bias=0.9,
        offense_bias=0.5,
        escalation_tolerance=0.8,
        risk_tolerance=0.2,
        force_preservation=0.9,
    )
    assert client.set_coalition_doctrine("blue", custom) is custom


def test_relationship_diagnostics_list_incident_points_and_references() -> None:
    relationship = CoalitionRelationship()
    relationship.record_incident(_incident(1, EscalationIncidentType.BORDER_VIOLATION))

    text = format_relationship(relationship)

    assert "border_violation points=5.0" in text
    assert "actor=red target=blue ref=-" in text


def test_mission_reset_clears_relationship_and_doctrines() -> None:
    client = MooseBridgeClient(MooseBridgeServer())
    client.relationship.automatic_transitions = True
    client.record_escalation_incident(_incident(1, EscalationIncidentType.UNIT_DESTROYED))
    client.set_coalition_doctrine("red", "aggressive")
    assert "state=tense" in format_relationship(client.relationship)

    client.reset_mission()

    assert client.relationship.state is RelationshipState.PEACE
    assert client.relationship.escalation_score == 0
    assert client.relationship.incidents == []
    assert client.relationship.automatic_transitions is True
    assert client.coalition_doctrines.get("red").preset is CoalitionDoctrinePreset.BALANCED


def test_limited_conflict_requires_explicit_objective_or_territory_authorization() -> None:
    relationship = CoalitionRelationship(state=RelationshipState.LIMITED_CONFLICT)
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Border Town",
        name="Border Town",
        kind=ObjectiveKind.CUSTOM,
        control_object_id=None,
        ownership_policy=OwnershipPolicy.FIXED,
        owner="red",
        metadata={"territory_id": "TERRITORY:Border"},
    )

    allowed, _ = relationship.allows_goal(StrategicGoalAction.DESTROY, objective)
    assert allowed is False

    relationship.limited_conflict.authorize_territory("TERRITORY:Border")
    allowed, reason = relationship.allows_goal(StrategicGoalAction.DESTROY, objective)
    assert allowed is True
    assert "authorized" in reason

    relationship.clear()
    assert relationship.limited_conflict.territory_ids == set()


def test_border_violation_requires_continuous_default_tolerance_and_emits_once() -> None:
    tracker = BorderViolationTracker()
    territory = Territory.from_payload(
        {
            "object_id": "TERRITORY:Red",
            "dcs_name": "Red",
            "name": "Red Territory",
            "coalition": "red",
            "shape": "polygon",
            "vertices": [
                {"x": 0, "z": 0},
                {"x": 1000, "z": 0},
                {"x": 1000, "z": 1000},
                {"x": 0, "z": 1000},
            ],
        }
    )
    inside = {
        "object_id": "GROUP:Blue Patrol",
        "coalition": "blue",
        "category": "Ground Unit",
        "alive": True,
        "active": True,
        "x": 500,
        "z": 500,
    }

    assert tracker.tolerance_s == 60
    assert tracker.update((inside,), (territory,), mission_time=10) == ()
    assert tracker.update((inside,), (territory,), mission_time=69.9) == ()
    incidents = tracker.update((inside,), (territory,), mission_time=70)
    assert len(incidents) == 1
    assert incidents[0].incident_type is EscalationIncidentType.BORDER_VIOLATION
    assert incidents[0].actor_coalition == "blue"
    assert incidents[0].target_coalition == "red"
    assert incidents[0].details["duration_s"] == 60
    assert tracker.update((inside,), (territory,), mission_time=100) == ()

    outside = {**inside, "x": 1500}
    assert tracker.update((outside,), (territory,), mission_time=110) == ()
    assert tracker.active_violations == ()
    assert tracker.update((inside,), (territory,), mission_time=120) == ()
    second = tracker.update((inside,), (territory,), mission_time=180)
    assert len(second) == 1
    assert second[0].incident_id != incidents[0].incident_id


def test_border_violation_ignores_aircraft_dead_and_inactive_groups() -> None:
    tracker = BorderViolationTracker(tolerance_s=0)
    territory = Territory.from_payload(
        {
            "object_id": "TERRITORY:Red",
            "dcs_name": "Red",
            "coalition": "red",
            "vertices": [{"x": 0, "z": 0}, {"x": 100, "z": 0}, {"x": 0, "z": 100}],
        }
    )
    base = {"coalition": "blue", "alive": True, "active": True, "x": 10, "z": 10}
    groups = (
        {**base, "object_id": "GROUP:Aircraft", "category": "Airplane"},
        {**base, "object_id": "GROUP:Dead", "category": "Ground Unit", "alive": False},
        {**base, "object_id": "GROUP:Inactive", "category": "Ground Unit", "active": False},
    )

    assert tracker.update(groups, (territory,), mission_time=1) == ()
