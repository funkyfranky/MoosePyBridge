from __future__ import annotations

from types import SimpleNamespace

import pytest

from moosebridge.ammunition import DcsWeaponFlag, UnitAmmunition
from moosebridge.diagnostics import format_weapon_range
from moosebridge.datamine_ranges import DEFAULT_DATAMINE_RANGE_DATA
from moosebridge.sdk import MooseBridgeClient
from moosebridge.state import MooseBridgeState
from moosebridge.weapon_ranges import RangeSource, WeaponRangeProfile, WeaponRangeRegistry


def _ammunition_item(
    *,
    unit_id: str,
    group_id: str,
    dcs_type: str,
    category: str,
    attributes: list[str],
    weapons: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "object_id": unit_id,
        "unit_id": unit_id,
        "unit_name": unit_id.removeprefix("UNIT:"),
        "group_id": group_id,
        "group_name": group_id.removeprefix("GROUP:"),
        "dcs_type": dcs_type,
        "category": category,
        "attributes": attributes,
        "life": 1,
        "life0": 1,
        "weapons": weapons,
    }


def test_datamine_profiles_define_mlrs_and_m109_task_ranges() -> None:
    registry = WeaponRangeRegistry()

    mlrs = registry.resolve("MLRS", DcsWeaponFlag.ANY_ROCKET)
    m109 = registry.resolve("M-109", DcsWeaponFlag.CONVENTIONAL_SHELL)

    assert mlrs is not None
    assert mlrs.source == RangeSource.DCS_DATAMINE_WEAPON
    assert (mlrs.minimum_m, mlrs.maximum_m) == (10_000, 32_000)
    assert mlrs.weapon_ids == ("weapons.nurs.M26",)
    assert m109 is not None
    assert m109.source == RangeSource.DCS_DATAMINE_UNIT
    assert m109.minimum_m == 30
    assert m109.maximum_m == 22_000
    assert m109.contains(22_000)
    assert not m109.contains(22_001)


def test_profiles_for_type_exposes_all_task_eligible_datamine_ranges() -> None:
    registry = WeaponRangeRegistry()

    mlrs = registry.profiles_for_type("MLRS")
    m109 = registry.profiles_for_type("M-109")

    assert any(
        profile.weapon_flag is DcsWeaponFlag.ANY_ROCKET
        and (profile.minimum_m, profile.maximum_m) == (10_000, 32_000)
        for profile in mlrs
    )
    assert any(
        profile.weapon_flag is DcsWeaponFlag.CONVENTIONAL_SHELL
        and (profile.minimum_m, profile.maximum_m) == (30, 22_000)
        for profile in m109
    )


def test_datamine_profile_takes_priority_over_descriptor_placeholders() -> None:
    state = MooseBridgeState()
    state.apply_message(
        {
            "type": "snapshot",
            "kind": "ammunition",
            "payload": {
                "ammunition": [
                    _ammunition_item(
                        unit_id="UNIT:MLRS",
                        group_id="GROUP:MLRS",
                        dcs_type="MLRS",
                        category="Ground Unit",
                        attributes=["Artillery", "MLRS"],
                        weapons=[
                            {
                                "id": "weapons.nurs.M26",
                                "display_name": "M26 (270mm DPICM)",
                                "count": 12,
                                "category": 2,
                                "distance_min_m": 0,
                                "distance_max_m": 0,
                            }
                        ],
                    )
                ]
            },
        }
    )
    client = MooseBridgeClient(SimpleNamespace(state=state))  # type: ignore[arg-type]

    profile = client.unit_weapon_range("MLRS", DcsWeaponFlag.ANY_ROCKET)

    assert profile is not None
    assert profile.source == RangeSource.DCS_DATAMINE_WEAPON
    assert (profile.minimum_m, profile.maximum_m) == (10_000, 32_000)
    assert client.group_weapon_ranges("GROUP:MLRS", DcsWeaponFlag.ANY_ROCKET) == (profile,)
    assert "range=10.000-32.000km" in format_weapon_range(profile)


def test_explicit_manual_profile_takes_priority_over_datamine() -> None:
    manual = WeaponRangeProfile(
        dcs_type="MLRS",
        weapon_flag=DcsWeaponFlag.ANY_ROCKET,
        minimum_m=11_000,
        maximum_m=31_000,
        source=RangeSource.MANUAL,
    )

    profile = WeaponRangeRegistry(profiles=(manual,)).resolve("MLRS", DcsWeaponFlag.ANY_ROCKET)

    assert profile == manual


def test_cruise_missile_range_is_derived_from_dcs_descriptor() -> None:
    state = MooseBridgeState()
    state.apply_message(
        {
            "type": "snapshot",
            "kind": "ammunition",
            "payload": {
                "ammunition": [
                    _ammunition_item(
                        unit_id="UNIT:Burke",
                        group_id="GROUP:Burke",
                        dcs_type="USS_Arleigh_Burke_IIa",
                        category="Ship",
                        attributes=["Armed Air Defence", "Armed Ship"],
                        weapons=[
                            {
                                "id": "weapons.missiles.BGM_109B",
                                "display_name": "BGM-109C Tomahawk",
                                "count": 22,
                                "category": 1,
                                "missile_category": 5,
                                "guidance": 1,
                                "range_min_m": 3_000,
                                "range_max_alt_min_m": 1_700_000,
                                "range_max_alt_max_m": 1_700_000,
                            }
                        ],
                    )
                ]
            },
        }
    )
    client = MooseBridgeClient(SimpleNamespace(state=state))  # type: ignore[arg-type]

    profile = client.unit_weapon_range("UNIT:Burke", DcsWeaponFlag.CRUISE_MISSILE)

    assert profile is not None
    assert profile.source == RangeSource.DCS_DESCRIPTOR
    assert profile.minimum_m == 3_000
    assert profile.maximum_m == 1_700_000
    assert profile.weapon_ids == ("weapons.missiles.BGM_109B",)


def test_role_fallback_aggregates_machine_gun_and_main_gun_envelopes() -> None:
    unit = UnitAmmunition.from_payload(
        _ammunition_item(
            unit_id="UNIT:MBT",
            group_id="GROUP:MBT",
            dcs_type="Leopard-2",
            category="Ground Unit",
            attributes=["Modern Tanks", "Tanks"],
            weapons=[
                {
                    "id": "weapons.shells.7_62x51",
                    "display_name": "7.62mm",
                    "count": 3_218,
                    "category": 0,
                    "caliber": 7.62,
                },
                {
                    "id": "weapons.shells.DM53_120_AP",
                    "display_name": "DM53 (120mm APFSDS-T)",
                    "count": 26,
                    "category": 0,
                    "caliber": 120,
                },
            ],
        )
    )

    profile = WeaponRangeRegistry(datamine=None).resolve(
        "Leopard-2",
        DcsWeaponFlag.BUILT_IN_CANNON,
        ammunition=unit.weapons,
    )

    assert profile is not None
    assert profile.source == RangeSource.ROLE_FALLBACK
    assert (profile.minimum_m, profile.maximum_m) == (0, 2_000)
    assert profile.weapon_ids == (
        "weapons.shells.7_62x51",
        "weapons.shells.DM53_120_AP",
    )


def test_packaged_datamine_contains_versioned_ground_unit_descriptors() -> None:
    data = DEFAULT_DATAMINE_RANGE_DATA

    assert data.descriptor_count == 351
    assert data.metadata.dcs_build == "2.9.28.26283"
    assert data.metadata.source_commit == "d75d7ac540ab5683b07d6a7c0f59b48528e8ff1a"
    assert any(item.dcs_type == "M-2 Bradley" for item in data.unit_envelopes)


def test_unambiguous_datamine_unit_envelope_precedes_role_fallback() -> None:
    unit = UnitAmmunition.from_payload(
        _ammunition_item(
            unit_id="UNIT:Mortar",
            group_id="GROUP:Mortar",
            dcs_type="2B11 mortar",
            category="Ground Unit",
            attributes=["Artillery", "Indirect fire"],
            weapons=[
                {
                    "id": "weapons.shells.2B11_120mm",
                    "display_name": "120mm mortar shell",
                    "count": 20,
                    "category": 0,
                    "caliber": 120,
                }
            ],
        )
    )

    profile = WeaponRangeRegistry().resolve(
        "2B11 mortar",
        DcsWeaponFlag.CONVENTIONAL_SHELL,
        ammunition=unit.weapons,
    )

    assert profile is not None
    assert profile.source == RangeSource.DCS_DATAMINE_UNIT
    assert (profile.minimum_m, profile.maximum_m) == (30, 7_000)


def test_ambiguous_multi_weapon_unit_does_not_reuse_unit_threat_range() -> None:
    unit = UnitAmmunition.from_payload(
        _ammunition_item(
            unit_id="UNIT:Bradley",
            group_id="GROUP:Bradley",
            dcs_type="M-2 Bradley",
            category="Ground Unit",
            attributes=["IFV", "ATGM"],
            weapons=[
                {
                    "id": "weapons.shells.M242_25_AP_M791",
                    "display_name": "M791 (25mm APDS-T)",
                    "count": 300,
                    "category": 0,
                    "caliber": 25,
                }
            ],
        )
    )

    profile = WeaponRangeRegistry().resolve(
        "M-2 Bradley",
        DcsWeaponFlag.BUILT_IN_CANNON,
        ammunition=unit.weapons,
    )

    assert profile is not None
    assert profile.source == RangeSource.ROLE_FALLBACK
    assert profile.maximum_m == 1_500


def test_descriptor_range_has_priority_over_atgm_role_fallback() -> None:
    unit = UnitAmmunition.from_payload(
        _ammunition_item(
            unit_id="UNIT:ATGM",
            group_id="GROUP:ATGM",
            dcs_type="M1134 Stryker ATGM",
            category="Ground Unit",
            attributes=["ATGM", "IFV"],
            weapons=[
                {
                    "id": "weapons.missiles.TOW2",
                    "display_name": "BGM-71 TOW",
                    "count": 14,
                    "category": 1,
                    "missile_category": 6,
                    "range_min_m": 65,
                    "range_max_alt_min_m": 3_800,
                    "range_max_alt_max_m": 3_800,
                }
            ],
        )
    )

    profile = WeaponRangeRegistry().resolve(
        "M1134 Stryker ATGM",
        DcsWeaponFlag.ANTI_TANK_MISSILE,
        ammunition=unit.weapons,
    )

    assert profile is not None
    assert profile.source == RangeSource.DCS_DESCRIPTOR
    assert (profile.minimum_m, profile.maximum_m) == (65, 3_800)


def test_registry_uses_explicit_flag_fallback_only_after_descriptor_lookup() -> None:
    fallback = WeaponRangeProfile(
        dcs_type="*",
        weapon_flag=DcsWeaponFlag.ANY_ROCKET,
        minimum_m=1_000,
        maximum_m=20_000,
        source=RangeSource.FLAG_FALLBACK,
    )
    registry = WeaponRangeRegistry(profiles=(), fallbacks=(fallback,))

    result = registry.resolve("Unknown MLRS", DcsWeaponFlag.ANY_ROCKET)

    assert result is not None
    assert result.dcs_type == "Unknown MLRS"
    assert result.source == RangeSource.FLAG_FALLBACK
    assert (result.minimum_m, result.maximum_m) == (1_000, 20_000)


def test_invalid_range_profile_is_rejected() -> None:
    with pytest.raises(ValueError):
        WeaponRangeProfile(
            dcs_type="M-109",
            weapon_flag=DcsWeaponFlag.CONVENTIONAL_SHELL,
            minimum_m=22_000,
            maximum_m=30,
            source=RangeSource.MANUAL,
        )
