from __future__ import annotations

from moosebridge.ammunition import (
    AmmunitionTracker,
    CombatDomain,
    UnitAmmunition,
    WeaponDelivery,
    WeaponEffect,
    WeaponFamily,
    WeaponRole,
    classify_ammunition_weapon,
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


def test_state_resets_observed_baseline_when_mission_time_moves_back() -> None:
    state = MooseBridgeState()
    state.apply_message({"type": "heartbeat", "source": "dcs", "mission_time": 100})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(14)]}})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(4)]}})
    assert state.ammunition_objects["UNIT:Stryker-1"].weapons[0].initial_count == 14

    state.apply_message({"type": "heartbeat", "source": "dcs", "mission_time": 1})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(4)]}})

    assert state.ammunition_objects["UNIT:Stryker-1"].weapons[0].initial_count == 4
