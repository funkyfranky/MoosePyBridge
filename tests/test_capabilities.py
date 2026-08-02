from __future__ import annotations

import pytest

from moosebridge.ammunition import UnitAmmunition
from moosebridge.capabilities import (
    CapabilityKind,
    InfluenceKind,
    build_group_capabilities,
    build_group_influence,
    build_unit_capabilities,
    build_unit_influence,
)


def _unit(
    unit_id: str,
    *,
    dcs_type: str,
    attributes: list[str],
    weapons: list[dict[str, object]],
    life: float = 10,
    life0: float = 10,
) -> UnitAmmunition:
    group_name = "Test Group"
    return UnitAmmunition.from_payload(
        {
            "object_id": unit_id,
            "unit_id": unit_id,
            "unit_name": unit_id.removeprefix("UNIT:"),
            "group_id": f"GROUP:{group_name}",
            "group_name": group_name,
            "dcs_type": dcs_type,
            "category": "Ground Unit",
            "attributes": attributes,
            "life": life,
            "life0": life0,
            "weapons": weapons,
        }
    )


def _dm53(count: int, initial: int = 26) -> dict[str, object]:
    return {
        "id": "weapons.shells.DM53_120_AP",
        "type_name": "weapons.shells.DM53_120_AP",
        "display_name": "DM53 (120mm APFSDS-T)",
        "category": 0,
        "caliber": 120,
        "count": count,
        "initial_count": initial,
    }


def test_tank_capabilities_keep_presence_and_ammunition_readiness_separate() -> None:
    unit = _unit(
        "UNIT:MBT",
        dcs_type="Leopard-2",
        attributes=["Tanks", "Modern Tanks"],
        weapons=[_dm53(13)],
    )

    profile = build_unit_capabilities(unit)

    assert profile.get(CapabilityKind.PRESENCE).effective_power == 1.0  # type: ignore[union-attr]
    anti_armor = profile.get(CapabilityKind.ANTI_ARMOR)
    assert anti_armor is not None
    assert anti_armor.base_power == 1.5
    assert anti_armor.ammo_readiness == 0.5
    assert anti_armor.health_readiness == 1.0
    assert anti_armor.effective_power == 0.75


def test_unarmed_logistics_retains_only_small_presence() -> None:
    truck = _unit("UNIT:Truck", dcs_type="Bedford_MWD", attributes=["Trucks", "Unarmed vehicles"], weapons=[])

    profile = build_unit_capabilities(truck)

    assert len(profile.capabilities) == 1
    presence = profile.get(CapabilityKind.PRESENCE)
    assert presence is not None
    assert presence.base_power == 0.10
    assert presence.ammo_readiness == 1.0

    influence = build_unit_influence(truck)
    assert influence.get(InfluenceKind.CONTROL) is None
    logistics = influence.get(InfluenceKind.LOGISTICS)
    assert logistics is not None
    assert logistics.base_power == 0.10
    assert logistics.effective_power == 0.10


def test_artillery_is_support_capability_with_reduced_presence() -> None:
    artillery = _unit(
        "UNIT:SPH",
        dcs_type="M-109",
        attributes=["Artillery", "Indirect fire"],
        weapons=[
            {
                "id": "weapons.shells.M185_155",
                "display_name": "M795 (155mm HE)",
                "category": 0,
                "caliber": 155,
                "count": 20,
                "initial_count": 40,
            }
        ],
    )

    profile = build_unit_capabilities(artillery)

    assert profile.get(CapabilityKind.PRESENCE).base_power == 0.35  # type: ignore[union-attr]
    assert profile.get(CapabilityKind.ANTI_PERSONNEL) is None
    indirect = profile.get(CapabilityKind.INDIRECT_FIRE)
    assert indirect is not None
    assert indirect.ammo_readiness == 0.5
    assert indirect.effective_power == 0.5

    influence = build_unit_influence(artillery)
    control = influence.get(InfluenceKind.CONTROL)
    indirect_influence = influence.get(InfluenceKind.INDIRECT_FIRE)
    assert control is not None
    assert control.effective_power == 0.075
    assert indirect_influence is not None
    assert indirect_influence.effective_power == 0.5
    assert (indirect_influence.minimum_range_m, indirect_influence.maximum_range_m) == (30, 22_000)


def test_group_aggregation_preserves_per_unit_ammo_and_health_effects() -> None:
    ready = _unit(
        "UNIT:MBT-1",
        dcs_type="Leopard-2",
        attributes=["Tanks"],
        weapons=[_dm53(26)],
    )
    depleted_and_damaged = _unit(
        "UNIT:MBT-2",
        dcs_type="Leopard-2",
        attributes=["Tanks"],
        weapons=[_dm53(0)],
        life=5,
        life0=10,
    )

    profile = build_group_capabilities([ready, depleted_and_damaged], "GROUP:Test Group")
    anti_armor = profile.get(CapabilityKind.ANTI_ARMOR)

    assert anti_armor is not None
    assert anti_armor.base_power == 3.0
    assert anti_armor.ammo_readiness == 0.5
    assert anti_armor.health_readiness == 0.75
    assert anti_armor.effective_power == pytest.approx(1.5)

    influence = build_group_influence([ready, depleted_and_damaged], "GROUP:Test Group")
    control = influence.get(InfluenceKind.CONTROL)
    assert control is not None
    assert control.base_power == 3.0
    assert control.effective_power == 1.5


def test_air_defense_does_not_create_ground_control() -> None:
    sam = _unit(
        "UNIT:SAM",
        dcs_type="SAM",
        attributes=["SAM", "Air Defence"],
        weapons=[
            {
                "id": "weapons.missiles.SAM",
                "display_name": "SAM",
                "category": 1,
                "missile_category": 2,
                "count": 4,
                "initial_count": 4,
            }
        ],
    )

    influence = build_unit_influence(sam)

    assert influence.get(InfluenceKind.CONTROL) is None
    assert influence.get(InfluenceKind.AIR_DEFENSE).effective_power == 1.0  # type: ignore[union-attr]
