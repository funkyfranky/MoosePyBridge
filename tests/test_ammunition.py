from __future__ import annotations

from moosebridge.ammunition import (
    AmmunitionTracker,
    CombatDomain,
    DcsWeaponFlag,
    MappingConfidence,
    UnitAmmunition,
    WeaponDelivery,
    WeaponEffect,
    WeaponFamily,
    WeaponRole,
    classify_ammunition_weapon,
    select_task_weapon,
)
from moosebridge.state import MooseBridgeState


def _unit(count: int, *, initial_count: int | None = None) -> dict[str, object]:
    weapon: dict[str, object] = {
        "id": "weapons.missiles.BGM_71D",
        "type_name": "weapons.missiles.BGM_71D",
        "display_name": "BGM-71D TOW2",
        "count": count,
        "category": 1,
        "missile_category": 6,
    }
    if initial_count is not None:
        weapon["initial_count"] = initial_count
    return {
        "object_id": "UNIT:Stryker-1",
        "unit_id": "UNIT:Stryker-1",
        "unit_name": "Stryker-1",
        "group_id": "GROUP:Stryker",
        "group_name": "Stryker",
        "dcs_type": "M1134 Stryker ATGM",
        "category": "Ground Unit",
        "attributes": ["ATGM", "Ground Units"],
        "life": 12,
        "life0": 16,
        "weapons": [weapon],
    }


def test_tracker_uses_first_observation_and_preserves_zero_counts() -> None:
    tracker = AmmunitionTracker()

    first = tracker.update([_unit(7)])[0]["weapons"][0]
    second = tracker.update([_unit(0)])[0]["weapons"][0]

    assert first["initial_count"] == 7
    assert first["fraction"] == 1.0
    assert second["count"] == 0
    assert second["initial_count"] == 7
    assert second["fraction"] == 0.0


def test_tracker_increases_observed_baseline_after_rearming() -> None:
    tracker = AmmunitionTracker()
    tracker.update([_unit(7)])
    tracker.update([_unit(3)])

    rearmed = tracker.update([_unit(14)])[0]["weapons"][0]

    assert rearmed["initial_count"] == 14
    assert rearmed["fraction"] == 1.0


def test_typed_ammunition_preserves_weapon_identity_and_life() -> None:
    item = AmmunitionTracker().update([_unit(7)])[0]

    ammunition = UnitAmmunition.from_payload(item)

    assert ammunition.unit_id == "UNIT:Stryker-1"
    assert ammunition.group_id == "GROUP:Stryker"
    assert ammunition.life_fraction == 0.75
    assert ammunition.weapons[0].type_name == "weapons.missiles.BGM_71D"
    assert ammunition.weapons[0].missile_category == 6
    assert ammunition.weapons[0].family == WeaponFamily.MISSILE
    assert ammunition.weapons[0].role == WeaponRole.ATGM
    assert ammunition.weapons[0].effects == (WeaponEffect.ANTI_ARMOR,)
    assert ammunition.weapons[0].launch_domain == CombatDomain.SURFACE
    assert ammunition.weapons[0].target_domains == (CombatDomain.SURFACE,)


def test_classifies_leopard_main_gun_ammunition_by_effect() -> None:
    apfsds = classify_ammunition_weapon(
        {"category": 0, "caliber": 120, "type_name": "weapons.shells.DM53_120_AP", "display_name": "DM53 (120mm APFSDS-T)"},
        unit_attributes=("Modern Tanks", "Tanks"),
        unit_category="Ground Unit",
    )
    heat = classify_ammunition_weapon(
        {
            "category": 0,
            "caliber": 120,
            "type_name": "weapons.shells.DM12_L55_120mm_HEAT_MP_T",
            "display_name": "DM12 (120mm HEAT-MP-T)",
            "explosive_mass": 14.3,
        },
        unit_attributes=("Modern Tanks", "Tanks"),
        unit_category="Ground Unit",
    )

    assert apfsds.family == WeaponFamily.CANNON
    assert apfsds.role == WeaponRole.MAIN_GUN
    assert apfsds.ammunition_type == "APFSDS"
    assert apfsds.effects == (WeaponEffect.ANTI_ARMOR,)
    assert heat.effects == (
        WeaponEffect.ANTI_ARMOR,
        WeaponEffect.ANTI_PERSONNEL,
        WeaponEffect.AREA_EFFECT,
    )


def test_classifies_bradley_autocannon_and_machine_gun() -> None:
    autocannon = classify_ammunition_weapon(
        {"category": 0, "caliber": 25, "display_name": "M791 (25mm APDS-T)"},
        unit_attributes=("IFV", "ATGM"),
        unit_category="Ground Unit",
    )
    machine_gun = classify_ammunition_weapon(
        {"category": 0, "caliber": 7.62, "display_name": "7.62mm"},
        unit_attributes=("IFV",),
        unit_category="Ground Unit",
    )

    assert autocannon.role == WeaponRole.AUTOCANNON
    assert autocannon.effects == (WeaponEffect.ANTI_LIGHT_ARMOR,)
    assert machine_gun.family == WeaponFamily.GUN
    assert machine_gun.role == WeaponRole.MACHINE_GUN
    assert machine_gun.effects == (WeaponEffect.ANTI_PERSONNEL,)


def test_classifies_indirect_cannon_and_rocket_artillery() -> None:
    cannon = classify_ammunition_weapon(
        {"category": 0, "caliber": 155, "display_name": "155mm HE"},
        unit_attributes=("Artillery",),
        unit_category="Ground Unit",
    )
    rocket = classify_ammunition_weapon(
        {"category": 2, "caliber": 0, "display_name": "M26 (270mm DPICM)"},
        unit_attributes=("Artillery", "MLRS"),
        unit_category="Ground Unit",
    )

    assert cannon.role == WeaponRole.ARTILLERY
    assert cannon.delivery == WeaponDelivery.INDIRECT
    assert rocket.family == WeaponFamily.ROCKET
    assert rocket.role == WeaponRole.ROCKET_ARTILLERY
    assert rocket.delivery == WeaponDelivery.INDIRECT
    assert WeaponEffect.AREA_EFFECT in rocket.effects
    assert WeaponEffect.ANTI_LIGHT_ARMOR in rocket.effects
    assert cannon.weapon_flags[0].flag == DcsWeaponFlag.CONVENTIONAL_SHELL
    assert DcsWeaponFlag.ANY_SHELL in {association.flag for association in cannon.weapon_flags}
    assert rocket.weapon_flags[0].flag == DcsWeaponFlag.ANY_ROCKET
    assert rocket.weapon_flags[0].confidence == MappingConfidence.DERIVED


def test_direct_fire_shells_and_atgm_have_traceable_task_flags() -> None:
    main_gun = classify_ammunition_weapon(
        {"category": 0, "caliber": 120, "display_name": "DM53 (120mm APFSDS-T)"},
        unit_attributes=("Tanks",),
        unit_category="Ground Unit",
    )
    atgm_payload = _unit(7)
    atgm = UnitAmmunition.from_payload(atgm_payload).weapons[0]

    assert main_gun.weapon_flags[0].flag == DcsWeaponFlag.BUILT_IN_CANNON
    assert main_gun.weapon_flags[0].confidence == MappingConfidence.HEURISTIC
    assert atgm.preferred_weapon_flag == DcsWeaponFlag.ANTI_TANK_MISSILE
    assert DcsWeaponFlag.ANY_ASM in {association.flag for association in atgm.weapon_flags}


def test_group_task_selection_uses_available_ammunition_and_role() -> None:
    artillery_payload = {
        "id": "weapons.shells.M185_155",
        "display_name": "M795 (155mm HE)",
        "count": 39,
        "initial_count": 39,
        "category": 0,
        "warhead_type": 1,
        "caliber": 155,
    }
    artillery = UnitAmmunition.from_payload(
        {
            "unit_id": "UNIT:SPH",
            "unit_name": "SPH",
            "group_id": "GROUP:SPH",
            "group_name": "SPH",
            "dcs_type": "M-109",
            "category": "Ground Unit",
            "attributes": ["Artillery", "Indirect fire"],
            "weapons": [artillery_payload],
        }
    )

    selection = select_task_weapon(artillery.weapons, role=WeaponRole.ARTILLERY)

    assert selection.weapon_flag == DcsWeaponFlag.CONVENTIONAL_SHELL
    assert selection.matching_weapon_ids == ("weapons.shells.M185_155",)
    assert selection.confidence == MappingConfidence.HEURISTIC


def test_unknown_missile_does_not_claim_surface_to_surface_role_or_flag() -> None:
    classification = classify_ammunition_weapon(
        {"category": 1, "missile_category": 6, "display_name": "Unknown missile"},
        unit_category="Ground Unit",
    )

    assert classification.role == WeaponRole.UNKNOWN
    assert classification.weapon_flags == ()


def test_task_selection_requires_a_role_when_group_weapon_flags_are_ambiguous() -> None:
    unit = UnitAmmunition.from_payload(_unit(7))
    machine_gun = UnitAmmunition.from_payload(
        {
            **_unit(7),
            "weapons": [
                _unit(7)["weapons"][0],
                {
                    "id": "weapons.shells.7_62x51",
                    "display_name": "7.62mm",
                    "count": 800,
                    "initial_count": 800,
                    "category": 0,
                    "caliber": 7.62,
                },
            ],
        }
    )

    ambiguous = select_task_weapon(machine_gun.weapons)
    anti_armor = select_task_weapon(machine_gun.weapons, role=WeaponRole.ATGM)

    assert ambiguous.weapon_flag is None
    assert "ANTI_TANK_MISSILE" in ambiguous.reason
    assert "BUILT_IN_CANNON" in ambiguous.reason
    assert anti_armor.weapon_flag == DcsWeaponFlag.ANTI_TANK_MISSILE
    assert unit.weapons[0].preferred_weapon_flag == DcsWeaponFlag.ANTI_TANK_MISSILE


def test_dcs_missile_category_distinguishes_sam_and_anti_ship_roles() -> None:
    sam = classify_ammunition_weapon(
        {"category": 1, "missile_category": 2, "display_name": "Generic missile"},
        unit_category="Ground Unit",
    )
    anti_ship = classify_ammunition_weapon(
        {"category": 1, "missile_category": 4, "display_name": "Generic missile"},
        unit_category="Ship",
    )

    assert sam.role == WeaponRole.SAM
    assert sam.target_domains == (CombatDomain.AIR,)
    assert sam.effects == (WeaponEffect.ANTI_AIR,)
    assert anti_ship.role == WeaponRole.ANTI_SHIP
    assert anti_ship.launch_domain == CombatDomain.SEA
    assert anti_ship.target_domains == (CombatDomain.SEA,)


def test_ship_cruise_missile_is_not_reclassified_by_air_defence_attributes() -> None:
    payload = {
        "id": "weapons.missiles.BGM_109B",
        "type_name": "weapons.missiles.BGM_109B",
        "display_name": "BGM-109C Tomahawk",
        "count": 22,
        "initial_count": 22,
        "category": 1,
        "missile_category": 5,
        "guidance": 1,
        "range_min_m": 3000,
        "range_max_alt_min_m": 1_700_000,
        "range_max_alt_max_m": 1_700_000,
        "altitude_min_m": -1,
        "altitude_max_m": 12_000,
    }
    unit = UnitAmmunition.from_payload(
        {
            "unit_id": "UNIT:Burke",
            "unit_name": "Burke",
            "group_id": "GROUP:Burke",
            "group_name": "Burke",
            "dcs_type": "USS_Arleigh_Burke_IIa",
            "category": "Ship",
            "attributes": ["Armed Air Defence", "Armed Ship", "Ships"],
            "weapons": [payload],
        }
    )
    tomahawk = unit.weapons[0]

    assert tomahawk.role == WeaponRole.SURFACE_TO_SURFACE
    assert tomahawk.launch_domain == CombatDomain.SEA
    assert tomahawk.target_domains == (CombatDomain.SURFACE,)
    assert tomahawk.preferred_weapon_flag == DcsWeaponFlag.CRUISE_MISSILE
    assert tomahawk.range_min_m == 3000
    assert tomahawk.range_max_alt_min_m == 1_700_000
    assert tomahawk.altitude_min_m == -1
    assert tomahawk.altitude_max_m == 12_000
    assert WeaponEffect.ANTI_STRUCTURE in tomahawk.effects


def test_state_resets_observed_baseline_when_mission_time_moves_back() -> None:
    state = MooseBridgeState()
    state.apply_message({"type": "heartbeat", "source": "dcs", "mission_time": 100})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(14)]}})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(4)]}})
    assert state.ammunition_objects["UNIT:Stryker-1"].weapons[0].initial_count == 14

    state.apply_message({"type": "heartbeat", "source": "dcs", "mission_time": 1})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(4)]}})

    assert state.ammunition_objects["UNIT:Stryker-1"].weapons[0].initial_count == 4
