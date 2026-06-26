from __future__ import annotations

from moosebridge.intents import (
    CommandPayload,
    TacticalIntent,
    TacticalRecommendation,
    command_action_for_auftrag_recommendation,
    intent_type_for_mission_type,
    tactical_recommendation_from_auftrag,
)
from moosebridge.recommendations import AuftragRecommendation


def test_tactical_intent_factories_serialize() -> None:
    attack = TacticalIntent.attack_target("GROUP:Enemy-1", coalition="blue", priority=80)
    defend = TacticalIntent.defend_zone("OPSZONE:Alpha", params={"radius_nm": 20})

    assert attack.to_dict()["intent_type"] == "attack_target"
    assert attack.target_id == "GROUP:Enemy-1"
    assert attack.coalition == "blue"
    assert attack.priority == 80
    assert defend.zone_id == "OPSZONE:Alpha"
    assert defend.params == {"radius_nm": 20}


def test_tactical_recommendation_serializes_executable_command() -> None:
    recommendation = TacticalRecommendation(
        intent=TacticalIntent.attack_target("GROUP:Enemy Armor"),
        command=CommandPayload(action="auftrag.create_bai", params={"target": "GROUP:Enemy Armor"}),
        rationale=["target is suitable for interdiction"],
        risks=["enemy air activity unknown"],
        confidence=0.7,
    )

    data = recommendation.to_dict()

    assert data["executable"] is True
    assert data["intent"]["intent_type"] == "attack_target"
    assert data["command"]["action"] == "auftrag.create_bai"
    assert data["approval_mode"] == "approval_required"


def test_intent_type_for_mission_type_maps_common_auftrag_types() -> None:
    assert intent_type_for_mission_type("BAI", {"target": "GROUP:Enemy"}) == "attack_target"
    assert intent_type_for_mission_type("CAP", {"target": "ZONE:Alpha"}) == "patrol_zone"
    assert intent_type_for_mission_type("Capture Zone", {"target": "OPSZONE:Alpha"}) == "defend_zone"
    assert intent_type_for_mission_type("Relocate Cohort", {"target": "ZONE:Rear"}) == "move_to_zone"


def test_auftrag_recommendation_converts_to_tactical_recommendation() -> None:
    auftrag = AuftragRecommendation(
        legion_id="LEGION:Blue Air Wing",
        cohort_id="COHORT:F-18",
        constructor="AUFTRAG:NewBAI",
        mission_type="BAI",
        params={"target": "GROUP:Enemy Armor", "altitude_ft": 12000},
        unit_type="FA-18C_hornet",
        distance_nm=42.0,
        mission_range_nm=180.0,
        range_margin_nm=138.0,
        selected_payload_uid=7,
        selected_payload_available=2,
        score_inputs={"mission_performance": 0.9},
    )

    recommendation = tactical_recommendation_from_auftrag(auftrag)
    data = recommendation.to_dict()

    assert command_action_for_auftrag_recommendation(auftrag) == "auftrag.create_bai"
    assert data["intent"]["intent_type"] == "attack_target"
    assert data["intent"]["target_id"] == "GROUP:Enemy Armor"
    assert data["command"]["action"] == "auftrag.create_bai"
    assert data["command"]["params"]["legion_id"] == "LEGION:Blue Air Wing"
    assert data["command"]["params"]["cohort_id"] == "COHORT:F-18"
    assert data["command"]["params"]["target"] == "GROUP:Enemy Armor"
    assert data["risks"] == []
    assert data["source"] == "auftrag_advisory"


def test_auftrag_recommendation_requires_mission_type_for_command_action() -> None:
    auftrag = AuftragRecommendation(
        legion_id="LEGION:Blue Air Wing",
        cohort_id="COHORT:F-18",
        constructor="AUFTRAG:NewBAI",
        mission_type="",
        params={"target": "GROUP:Enemy Armor"},
    )

    try:
        command_action_for_auftrag_recommendation(auftrag)
    except ValueError as exc:
        assert "mission_type" in str(exc)
    else:
        raise AssertionError("empty mission_type produced a command action")
