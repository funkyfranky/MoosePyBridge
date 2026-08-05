from __future__ import annotations

from moosebridge import (
    StrategicGoalEffect,
    StrategicMissionResolver,
    StrategicTargetDomain,
    classify_strategic_target,
)
from moosebridge.legions import Cohort


def _cohort(
    object_id: str,
    mission_type: str,
    category: str,
    *,
    payload: bool = False,
) -> Cohort:
    category_key = category.lower()
    payloads = (
        {mission_type: {"available_count": 1, "total_available": 1}}
        if payload
        else {}
    )
    return Cohort.from_payload(
        {
            "object_id": object_id,
            "legion_id": "LEGION:Test",
            "available_asset_count": 2,
            "mission_types": [mission_type],
            "is_air": category_key == "air",
            "is_ground": category_key == "ground",
            "is_naval": category_key == "naval",
            "payloads_by_mission": payloads,
        }
    )


def test_target_domain_uses_object_type_and_dcs_category() -> None:
    assert classify_strategic_target("STATIC:Depot") is StrategicTargetDomain.STATIC
    assert classify_strategic_target("AIRBASE:Tutow", {"category": "Airdrome"}) is StrategicTargetDomain.AIRBASE
    assert classify_strategic_target("GROUP:Armor", {"category": "Ground Unit"}) is StrategicTargetDomain.GROUND
    assert classify_strategic_target("UNIT:MiG", {"category": "Airplane"}) is StrategicTargetDomain.AIR
    assert classify_strategic_target("GROUP:Burke", {"category": "Ship"}) is StrategicTargetDomain.NAVAL
    assert classify_strategic_target("SCENERY:Bridge") is StrategicTargetDomain.SCENERY


def test_ground_target_prefers_bai_but_selects_available_groundattack() -> None:
    resolution = StrategicMissionResolver().resolve(
        "GROUP:Armor",
        target_data={"category": "Ground Unit"},
        cohorts=(_cohort("COHORT:Armor", "GROUNDATTACK", "ground"),),
    )

    assert [candidate.mission_type for candidate in resolution.candidates] == ["BAI", "GROUNDATTACK"]
    assert resolution.selected.mission_type == "GROUNDATTACK"
    assert resolution.selected_cohort_id == "COHORT:Armor"


def test_air_defense_target_prefers_sead() -> None:
    resolution = StrategicMissionResolver().resolve(
        "GROUP:SAM",
        target_data={"category": "Ground Unit", "attributes": ["SAM SR", "Air Defence"]},
        cohorts=(_cohort("COHORT:SEAD", "SEAD", "air", payload=True),),
    )

    assert resolution.effect is StrategicGoalEffect.DESTROY_OBJECT
    assert resolution.selected.mission_type == "SEAD"
    assert resolution.selected.role.value == "sead"


def test_naval_and_air_targets_use_domain_specific_missions() -> None:
    resolver = StrategicMissionResolver()
    ship = resolver.resolve(
        "GROUP:Burke",
        target_data={"category": "Ship"},
        cohorts=(_cohort("COHORT:Fleet", "NAVALENGAGEMENT", "naval"),),
    )
    aircraft = resolver.resolve(
        "GROUP:Bandit",
        target_data={"category": "Airplane"},
        cohorts=(_cohort("COHORT:CAP", "INTERCEPT", "air", payload=True),),
    )

    assert ship.effect is StrategicGoalEffect.DESTROY_SHIP
    assert ship.selected.mission_type == "NAVALENGAGEMENT"
    assert aircraft.selected.mission_type == "INTERCEPT"


def test_static_target_can_select_bombing_when_bai_is_unavailable() -> None:
    resolution = StrategicMissionResolver().resolve(
        "STATIC:Depot",
        cohorts=(_cohort("COHORT:Bombers", "BOMBING", "air", payload=True),),
    )

    assert resolution.effect is StrategicGoalEffect.DESTROY_INFRASTRUCTURE
    assert resolution.selected.mission_type == "BOMBING"
    assert "ARTY" not in [candidate.mission_type for candidate in resolution.candidates]


def test_runway_denial_requires_an_airdrome() -> None:
    resolver = StrategicMissionResolver()
    resolution = resolver.resolve(
        "AIRBASE:Tutow",
        effect=StrategicGoalEffect.DENY_RUNWAY,
        target_data={"category": "Airdrome"},
    )
    assert resolution.selected.mission_type == "BOMBRUNWAY"

    try:
        resolver.resolve(
            "AIRBASE:FARP",
            effect=StrategicGoalEffect.DENY_RUNWAY,
            target_data={"category": "Helipad"},
        )
    except ValueError as exc:
        assert "Airdrome" in str(exc)
    else:
        raise AssertionError("runway denial must reject helipads")
