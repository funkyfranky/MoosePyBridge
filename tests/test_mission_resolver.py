from __future__ import annotations

from moosebridge import (
    DcsWeaponFlag,
    StrategicGoalEffect,
    StrategicMissionResolver,
    StrategicTargetDomain,
    classify_strategic_target,
)
from moosebridge.ammunition import UnitAmmunition
from moosebridge.legions import Cohort, Legion


def _cohort(
    object_id: str,
    mission_type: str,
    category: str,
    *,
    payload: bool = False,
    unit_type: str | None = None,
    x: float | None = None,
    z: float | None = None,
    legion_id: str = "LEGION:Test",
    engage_range_m: float = 20_000,
) -> Cohort:
    category_key = category.lower()
    payloads = (
        {mission_type: {"available_count": 1, "total_available": 1}}
        if payload
        else {}
    )
    mission_ranges: dict[str, float] = {}
    weapon_ranges: dict[str, dict[str, float]] = {}
    if unit_type == "M-109":
        key = str(int(DcsWeaponFlag.CONVENTIONAL_SHELL))
        mission_ranges[key] = engage_range_m + 22_000
        weapon_ranges[key] = {"minimum_m": 30, "maximum_m": 22_000}
    elif unit_type == "MLRS":
        key = str(int(DcsWeaponFlag.ANY_ROCKET))
        mission_ranges[key] = engage_range_m + 32_000
        weapon_ranges[key] = {"minimum_m": 10_000, "maximum_m": 32_000}
    return Cohort.from_payload(
        {
            "object_id": object_id,
            "legion_id": legion_id,
            "unit_type": unit_type,
            "x": x,
            "z": z,
            "engage_range_m": engage_range_m,
            "mission_ranges_by_weapon_type": mission_ranges,
            "weapon_ranges_by_type": weapon_ranges,
            "available_asset_count": 2,
            "opsgroup_ids": ["OPSGROUP:M109-1"] if unit_type == "M-109" else [],
            "mission_types": [mission_type],
            "is_air": category_key == "air",
            "is_ground": category_key == "ground",
            "is_naval": category_key == "naval",
            "payloads_by_mission": payloads,
        }
    )


def _legion(*, x: float = 0.0, z: float = 0.0) -> Legion:
    return Legion.from_payload(
        {
            "object_id": "LEGION:Test",
            "coalition": "blue",
            "x": x,
            "z": z,
        }
    )


def _m109_ammunition(count: int) -> UnitAmmunition:
    return UnitAmmunition.from_payload(
        {
            "unit_id": "UNIT:M109-1",
            "group_id": "GROUP:M109-1",
            "dcs_type": "M-109",
            "category": "Ground Unit",
            "attributes": ["Artillery", "Indirect fire"],
            "life": 1,
            "life0": 1,
            "weapons": [
                {
                    "id": "weapons.shells.M107_155",
                    "display_name": "M107 155mm HE",
                    "count": count,
                    "initial_count": 28,
                    "category": 0,
                    "caliber": 155,
                }
            ],
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


def test_m109_arty_is_selected_within_range_and_bound_to_qualified_cohort() -> None:
    cohort = _cohort(
        "COHORT:M109",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "STATIC:Depot",
        target_data={"x": 10_000, "z": 0},
        cohorts=(item for item in (cohort,)),
        legions=(_legion(),),
    )

    assert resolution.selected.mission_type == "ARTY"
    assert resolution.selected_cohort_id == "COHORT:M109"
    assert resolution.fire_support is not None
    assert resolution.fire_support.weapon_flag is DcsWeaponFlag.CONVENTIONAL_SHELL
    assert (resolution.fire_support.minimum_m, resolution.fire_support.maximum_m) == (30, 22_000)
    assert resolution.fire_support.distance_m == 10_000
    assert resolution.fire_support.mission_range_m == 42_000
    assert resolution.fire_support.moose_weapon_range_m == 22_000
    assert resolution.fire_support.range_sync_required is False
    assert resolution.fire_support.required_relocation_m == 0
    assert resolution.fire_support.ammunition_source == "cohort_template_assumed_full"


def test_mlrs_inside_minimum_weapon_range_can_relocate() -> None:
    cohort = _cohort(
        "COHORT:MLRS",
        "ARTY",
        "ground",
        unit_type="MLRS",
        x=0,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "GROUP:Armor",
        target_data={"category": "Ground Unit", "x": 5_000, "z": 0, "speed_mps": 0},
        cohorts=(cohort,),
    )

    assert resolution.selected.mission_type == "ARTY"
    assert resolution.fire_support is not None
    assert resolution.fire_support.required_relocation_m == 5_000
    assert resolution.fire_support.mission_range_m == 52_000


def test_mlrs_beyond_cohort_mission_range_excludes_arty() -> None:
    cohort = _cohort(
        "COHORT:MLRS",
        "ARTY",
        "ground",
        unit_type="MLRS",
        x=0,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "GROUP:Armor",
        target_data={"category": "Ground Unit", "x": 53_000, "z": 0, "speed_mps": 0},
        cohorts=(cohort,),
    )

    assert "ARTY" not in [candidate.mission_type for candidate in resolution.candidates]


def test_relocation_uses_synchronized_datamine_range_when_moose_differs() -> None:
    cohort = _cohort(
        "COHORT:M109",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
        engage_range_m=20_000,
    )
    key = str(int(DcsWeaponFlag.CONVENTIONAL_SHELL))
    cohort.weapon_ranges_by_type[key] = (30, 20_000)
    cohort.mission_ranges_by_weapon_type[key] = 40_000

    resolution = StrategicMissionResolver().resolve(
        "STATIC:Depot",
        target_data={"x": 30_000, "z": 0},
        cohorts=(cohort,),
    )

    assert resolution.fire_support is not None
    assert resolution.fire_support.maximum_m == 22_000
    assert resolution.fire_support.moose_weapon_range_m == 20_000
    assert resolution.fire_support.configured_maximum_m == 20_000
    assert resolution.fire_support.range_sync_required is True
    assert resolution.fire_support.mission_range_m == 42_000
    assert resolution.fire_support.required_relocation_m == 8_000


def test_missing_moose_weapon_range_requires_synchronization() -> None:
    cohort = _cohort(
        "COHORT:M109",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
    )
    cohort.weapon_ranges_by_type.clear()

    resolution = StrategicMissionResolver().resolve(
        "STATIC:Depot",
        target_data={"x": 10_000, "z": 0},
        cohorts=(cohort,),
    )

    assert resolution.fire_support is not None
    assert resolution.fire_support.configured_minimum_m is None
    assert resolution.fire_support.configured_maximum_m is None
    assert resolution.fire_support.range_sync_required is True


def test_scientific_lua_weapon_keys_are_normalized() -> None:
    cohort = Cohort.from_payload(
        {
            "object_id": "COHORT:M109",
            "mission_ranges_by_weapon_type": {"2.06963736576e+11": 42_000},
            "weapon_ranges_by_type": {
                "2.06963736576e+11": {
                    "weapon_type": 206_963_736_576,
                    "minimum_m": 30,
                    "maximum_m": 22_000,
                }
            },
        }
    )

    assert cohort.mission_range_for_weapon_type(DcsWeaponFlag.CONVENTIONAL_SHELL) == 42_000
    assert cohort.weapon_range_for_weapon_type(DcsWeaponFlag.CONVENTIONAL_SHELL) == (30, 22_000)


def test_fire_support_prefers_cohort_that_can_fire_without_relocation() -> None:
    m109 = _cohort(
        "COHORT:M109",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
        engage_range_m=10_000,
    )
    mlrs = _cohort(
        "COHORT:MLRS",
        "ARTY",
        "ground",
        unit_type="MLRS",
        x=0,
        z=0,
        engage_range_m=10_000,
    )

    resolution = StrategicMissionResolver().resolve(
        "GROUP:Armor",
        target_data={"category": "Ground Unit", "x": 30_000, "z": 0, "speed_mps": 0},
        cohorts=(m109, mlrs),
    )

    assert resolution.selected.mission_type == "ARTY"
    assert resolution.selected_cohort_id == "COHORT:MLRS"
    assert resolution.fire_support is not None
    assert resolution.fire_support.required_relocation_m == 0
    assert [item.cohort_id for item in resolution.fire_support_candidates] == [
        "COHORT:MLRS",
        "COHORT:M109",
    ]


def test_fire_support_prefers_observed_ammunition_when_movement_is_equal() -> None:
    assumed = _cohort(
        "COHORT:Assumed",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
    )
    assumed.opsgroup_ids.clear()
    observed = _cohort(
        "COHORT:Observed",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "STATIC:Depot",
        target_data={"x": 10_000, "z": 0},
        cohorts=(assumed, observed),
        ammunition=(_m109_ammunition(12),),
    )

    assert resolution.selected_cohort_id == "COHORT:Observed"
    assert resolution.fire_support is not None
    assert resolution.fire_support.ammunition_source == "observed_current"
    assert resolution.fire_support.current_rounds == 12


def test_shortest_time_to_effect_selects_arty_over_distant_aircraft() -> None:
    mlrs = _cohort(
        "COHORT:MLRS",
        "ARTY",
        "ground",
        unit_type="MLRS",
        x=0,
        z=0,
        engage_range_m=10_000,
    )
    aircraft = _cohort(
        "COHORT:Aircraft",
        "BAI",
        "air",
        payload=True,
        x=-100_000,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "GROUP:Armor",
        target_data={"category": "Ground Unit", "x": 30_000, "z": 0, "speed_mps": 0},
        cohorts=(aircraft, mlrs),
    )

    assert resolution.selected.mission_type == "ARTY"
    assert resolution.selected_cohort_id == "COHORT:MLRS"
    assert resolution.assignments[0].estimated_time_to_effect_s == 120.0
    assert resolution.assignments[1].mission_type == "BAI"
    assert resolution.assignments[1].estimated_time_to_effect_s == 950.0


def test_shortest_time_to_effect_selects_near_aircraft_over_relocating_arty() -> None:
    m109 = _cohort(
        "COHORT:M109",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
        engage_range_m=10_000,
    )
    aircraft = _cohort(
        "COHORT:Aircraft",
        "BAI",
        "air",
        payload=True,
        x=20_000,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "GROUP:Armor",
        target_data={"category": "Ground Unit", "x": 30_000, "z": 0, "speed_mps": 0},
        cohorts=(m109, aircraft),
    )

    assert resolution.selected.mission_type == "BAI"
    assert resolution.selected_cohort_id == "COHORT:Aircraft"
    assert resolution.assignments[0].estimated_time_to_effect_s == 350.0
    assert resolution.assignments[1].mission_type == "ARTY"
    assert resolution.assignments[1].estimated_time_to_effect_s is not None
    assert resolution.assignments[1].estimated_time_to_effect_s > 1_000


def test_missing_positions_fall_back_to_doctrinal_candidate_order() -> None:
    ground = _cohort("COHORT:Ground", "GROUNDATTACK", "ground")
    aircraft = _cohort("COHORT:Aircraft", "BAI", "air", payload=True)

    resolution = StrategicMissionResolver().resolve(
        "GROUP:Armor",
        target_data={"category": "Ground Unit"},
        cohorts=(ground, aircraft),
    )

    assert resolution.selected.mission_type == "BAI"
    assert resolution.selected_cohort_id == "COHORT:Aircraft"
    assert all(item.estimated_time_to_effect_s is None for item in resolution.assignments)


def test_observed_empty_ammunition_excludes_arty() -> None:
    cohort = _cohort(
        "COHORT:M109",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "STATIC:Depot",
        target_data={"x": 10_000, "z": 0},
        cohorts=(cohort,),
        ammunition=(_m109_ammunition(0),),
    )

    assert "ARTY" not in [candidate.mission_type for candidate in resolution.candidates]


def test_observed_current_ammunition_qualifies_arty() -> None:
    cohort = _cohort(
        "COHORT:M109",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "STATIC:Depot",
        target_data={"x": 10_000, "z": 0},
        cohorts=(cohort,),
        ammunition=(_m109_ammunition(12),),
    )

    assert resolution.selected.mission_type == "ARTY"
    assert resolution.fire_support is not None
    assert resolution.fire_support.ammunition_source == "observed_current"
    assert resolution.fire_support.current_rounds == 12


def test_moving_ground_target_excludes_arty() -> None:
    cohort = _cohort(
        "COHORT:M109",
        "ARTY",
        "ground",
        unit_type="M-109",
        x=0,
        z=0,
    )

    resolution = StrategicMissionResolver().resolve(
        "GROUP:Armor",
        target_data={"category": "Ground Unit", "x": 10_000, "z": 0, "speed_mps": 2},
        cohorts=(cohort,),
    )

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
