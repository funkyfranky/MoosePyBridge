"""Typed ammunition snapshots and observed-initial-count tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum, IntFlag
import re
from typing import Any, Iterable, TypeVar


_IntEnumT = TypeVar("_IntEnumT", bound=IntEnum)


class WeaponFamily(str, Enum):
    """Basic physical weapon family."""

    UNKNOWN = "unknown"
    GUN = "gun"
    CANNON = "cannon"
    ROCKET = "rocket"
    MISSILE = "missile"
    BOMB = "bomb"
    TORPEDO = "torpedo"
    MINE = "mine"


class DcsWeaponCategory(IntEnum):
    """Categories exposed by ``Weapon.Desc.category`` and ``Unit.getAmmo``."""

    SHELL = 0
    MISSILE = 1
    ROCKET = 2
    BOMB = 3


class DcsMissileCategory(IntEnum):
    """Missile categories exposed by DCS weapon descriptors."""

    AAM = 1
    SAM = 2
    BALLISTIC = 3
    ANTI_SHIP = 4
    CRUISE = 5
    OTHER = 6


class DcsGuidanceType(IntEnum):
    """Guidance types exposed by DCS weapon descriptors."""

    INS = 1
    IR = 2
    RADAR_ACTIVE = 3
    RADAR_SEMI_ACTIVE = 4
    RADAR_PASSIVE = 5
    TV = 6
    LASER = 7
    TELE = 8


class DcsWarheadType(IntEnum):
    """Warhead types exposed by DCS weapon descriptors."""

    AP = 0
    HE = 1
    SHAPED_EXPLOSIVE = 2


class DcsWeaponFlag(IntFlag):
    """DCS ``Weapon.flag`` values used by task ``weaponType`` parameters."""

    NO_WEAPON = 0

    LGB = 2
    TV_GUIDED_BOMB = 4
    SATELLITE_GUIDED_BOMB = 8
    HE_BOMB = 16
    PENETRATOR = 32
    NAPALM_BOMB = 64
    FAE_BOMB = 128
    CLUSTER_BOMB = 256
    DISPENSER = 512
    CANDLE_BOMB = 1024
    PARACHUTE_BOMB = 2147483648
    GUIDED_BOMB = 14
    ANY_UNGUIDED_BOMB = 2147485680
    ANY_BOMB = 2147485694

    LIGHT_ROCKET = 2048
    MARKER_ROCKET = 4096
    CANDLE_ROCKET = 8192
    HEAVY_ROCKET = 16384
    ANY_ROCKET = 30720

    ANTI_RADAR_MISSILE = 32768
    ANTI_SHIP_MISSILE = 65536
    ANTI_TANK_MISSILE = 131072
    FIRE_AND_FORGET_ASM = 262144
    LASER_ASM = 524288
    TV_ASM = 1048576
    CRUISE_MISSILE = 2097152
    ANTI_RADAR_MISSILE_2 = 1073741824
    DECOYS = 8589934592
    GUIDED_ASM = 1572864
    TACTICAL_ASM = 1835008
    ANY_ASM = 4161536

    SRAAM = 4194304
    MRAAM = 8388608
    LRAAM = 16777216
    IR_AAM = 33554432
    SAR_AAM = 67108864
    AR_AAM = 134217728
    ANY_AAM = 264241152
    ANY_MISSILE = 268402688
    ANY_AUTONOMOUS_MISSILE = 36012032

    GUN_POD = 268435456
    BUILT_IN_CANNON = 536870912
    CANNONS = 805306368

    SMOKE_SHELL = 17179869184
    ILLUMINATION_SHELL = 34359738368
    MARKER_SHELL = 51539607552
    SUBMUNITION_DISPENSER_SHELL = 68719476736
    GUIDED_SHELL = 137438953472
    CONVENTIONAL_SHELL = 206963736576
    ANY_SHELL = 258503344128

    TORPEDO = 4294967296

    ANY_AG_WEAPON = 2956984318
    ANY_AA_WEAPON = 264241152
    UNGUIDED_WEAPON = 2952822768
    GUIDED_WEAPON = 268402702
    ANY_WEAPON = 3221225470
    MARKER_WEAPON = 13312
    ARM_WEAPON = 209379642366


class MappingConfidence(str, Enum):
    """Confidence that descriptor evidence maps to a DCS task selector."""

    EXACT = "exact"
    DERIVED = "derived"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class WeaponFlagAssociation:
    """Traceable association between observed ammunition and a task selector."""

    flag: DcsWeaponFlag
    confidence: MappingConfidence
    source: str
    specific: bool = True


@dataclass(slots=True, frozen=True)
class TaskWeaponSelection:
    """Best available group-level ``weaponType`` recommendation."""

    weapon_flag: DcsWeaponFlag | None = None
    matching_weapon_ids: tuple[str, ...] = ()
    confidence: MappingConfidence = MappingConfidence.UNKNOWN
    reason: str = "No compatible DCS weapon flag is known."


class WeaponRole(str, Enum):
    """Operational role of a weapon system."""

    UNKNOWN = "unknown"
    MACHINE_GUN = "machine_gun"
    AUTOCANNON = "autocannon"
    MAIN_GUN = "main_gun"
    ARTILLERY = "artillery"
    MORTAR = "mortar"
    ROCKET_ARTILLERY = "rocket_artillery"
    UNGUIDED_ROCKET = "unguided_rocket"
    ATGM = "atgm"
    SAM = "sam"
    SURFACE_TO_SURFACE = "surface_to_surface"
    ANTI_SHIP = "anti_ship"
    BOMB = "bomb"
    TORPEDO = "torpedo"
    MINE = "mine"


class WeaponDelivery(str, Enum):
    """How the weapon is normally delivered to its target."""

    UNKNOWN = "unknown"
    DIRECT = "direct"
    INDIRECT = "indirect"
    AIR_DELIVERED = "air_delivered"
    PASSIVE = "passive"


class CombatDomain(str, Enum):
    """Launch or target domain."""

    SURFACE = "surface"
    AIR = "air"
    SEA = "sea"
    SUBSURFACE = "subsurface"


class WeaponEffect(str, Enum):
    """Broad target effect relevant to tactical reasoning."""

    ANTI_PERSONNEL = "anti_personnel"
    ANTI_LIGHT_ARMOR = "anti_light_armor"
    ANTI_ARMOR = "anti_armor"
    ANTI_AIR = "anti_air"
    ANTI_SHIP = "anti_ship"
    ANTI_SUBMARINE = "anti_submarine"
    ANTI_STRUCTURE = "anti_structure"
    AREA_EFFECT = "area_effect"
    SUPPRESSION = "suppression"


@dataclass(slots=True, frozen=True)
class WeaponClassification:
    """Orthogonal tactical classification derived from DCS metadata."""

    family: WeaponFamily
    role: WeaponRole
    delivery: WeaponDelivery
    launch_domain: CombatDomain
    target_domains: tuple[CombatDomain, ...]
    effects: tuple[WeaponEffect, ...]
    ammunition_type: str | None = None
    weapon_flags: tuple[WeaponFlagAssociation, ...] = ()


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _enum(enum_type: type[_IntEnumT], value: Any) -> _IntEnumT | None:
    numeric = _int(value)
    if numeric is None:
        return None
    try:
        return enum_type(numeric)
    except ValueError:
        return None


def _string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _contains_attribute(attributes: set[str], *needles: str) -> bool:
    return any(needle in attribute for attribute in attributes for needle in needles)


def _ammunition_type(text: str) -> str | None:
    for value in ("APFSDS", "APDS", "HEAT", "HEI", "DPICM", "HESH"):
        if value in text:
            return value
    for value in ("HE", "AP"):
        if re.search(rf"(?:^|[^A-Z]){value}(?:$|[^A-Z])", text):
            return value
    return None


_CONFIDENCE_RANK = {
    MappingConfidence.UNKNOWN: 0,
    MappingConfidence.HEURISTIC: 1,
    MappingConfidence.DERIVED: 2,
    MappingConfidence.EXACT: 3,
}


def _parent_weapon_flags(flag: DcsWeaponFlag) -> tuple[DcsWeaponFlag, ...]:
    """Return useful broader selectors without relying on bitwise inference."""

    bomb_flags = {
        DcsWeaponFlag.LGB,
        DcsWeaponFlag.TV_GUIDED_BOMB,
        DcsWeaponFlag.SATELLITE_GUIDED_BOMB,
        DcsWeaponFlag.GUIDED_BOMB,
    }
    unguided_bomb_flags = {
        DcsWeaponFlag.HE_BOMB,
        DcsWeaponFlag.PENETRATOR,
        DcsWeaponFlag.NAPALM_BOMB,
        DcsWeaponFlag.FAE_BOMB,
        DcsWeaponFlag.CLUSTER_BOMB,
        DcsWeaponFlag.DISPENSER,
        DcsWeaponFlag.CANDLE_BOMB,
        DcsWeaponFlag.PARACHUTE_BOMB,
        DcsWeaponFlag.ANY_UNGUIDED_BOMB,
    }
    rocket_flags = {
        DcsWeaponFlag.LIGHT_ROCKET,
        DcsWeaponFlag.MARKER_ROCKET,
        DcsWeaponFlag.CANDLE_ROCKET,
        DcsWeaponFlag.HEAVY_ROCKET,
        DcsWeaponFlag.ANY_ROCKET,
    }
    asm_flags = {
        DcsWeaponFlag.ANTI_RADAR_MISSILE,
        DcsWeaponFlag.ANTI_SHIP_MISSILE,
        DcsWeaponFlag.ANTI_TANK_MISSILE,
        DcsWeaponFlag.FIRE_AND_FORGET_ASM,
        DcsWeaponFlag.LASER_ASM,
        DcsWeaponFlag.TV_ASM,
        DcsWeaponFlag.CRUISE_MISSILE,
        DcsWeaponFlag.ANTI_RADAR_MISSILE_2,
        DcsWeaponFlag.GUIDED_ASM,
        DcsWeaponFlag.TACTICAL_ASM,
        DcsWeaponFlag.ANY_ASM,
    }
    aam_flags = {
        DcsWeaponFlag.SRAAM,
        DcsWeaponFlag.MRAAM,
        DcsWeaponFlag.LRAAM,
        DcsWeaponFlag.IR_AAM,
        DcsWeaponFlag.SAR_AAM,
        DcsWeaponFlag.AR_AAM,
        DcsWeaponFlag.ANY_AAM,
    }
    shell_flags = {
        DcsWeaponFlag.SMOKE_SHELL,
        DcsWeaponFlag.ILLUMINATION_SHELL,
        DcsWeaponFlag.MARKER_SHELL,
        DcsWeaponFlag.SUBMUNITION_DISPENSER_SHELL,
        DcsWeaponFlag.GUIDED_SHELL,
        DcsWeaponFlag.CONVENTIONAL_SHELL,
        DcsWeaponFlag.ANY_SHELL,
    }

    parents: list[DcsWeaponFlag] = []
    if flag == DcsWeaponFlag.ANY_BOMB:
        parents.extend((DcsWeaponFlag.ANY_AG_WEAPON, DcsWeaponFlag.ANY_WEAPON))
    elif flag in bomb_flags:
        if flag != DcsWeaponFlag.GUIDED_BOMB:
            parents.append(DcsWeaponFlag.GUIDED_BOMB)
        parents.extend((DcsWeaponFlag.ANY_BOMB, DcsWeaponFlag.GUIDED_WEAPON, DcsWeaponFlag.ANY_AG_WEAPON, DcsWeaponFlag.ANY_WEAPON))
    elif flag in unguided_bomb_flags:
        if flag != DcsWeaponFlag.ANY_UNGUIDED_BOMB:
            parents.append(DcsWeaponFlag.ANY_UNGUIDED_BOMB)
        parents.extend((DcsWeaponFlag.ANY_BOMB, DcsWeaponFlag.UNGUIDED_WEAPON, DcsWeaponFlag.ANY_AG_WEAPON, DcsWeaponFlag.ANY_WEAPON))
    elif flag in rocket_flags:
        if flag != DcsWeaponFlag.ANY_ROCKET:
            parents.append(DcsWeaponFlag.ANY_ROCKET)
        parents.extend((DcsWeaponFlag.UNGUIDED_WEAPON, DcsWeaponFlag.ANY_AG_WEAPON, DcsWeaponFlag.ANY_WEAPON))
        if flag in {DcsWeaponFlag.MARKER_ROCKET, DcsWeaponFlag.CANDLE_ROCKET}:
            parents.append(DcsWeaponFlag.MARKER_WEAPON)
    elif flag in asm_flags:
        if flag != DcsWeaponFlag.ANY_ASM:
            parents.append(DcsWeaponFlag.ANY_ASM)
        parents.extend((DcsWeaponFlag.ANY_MISSILE, DcsWeaponFlag.GUIDED_WEAPON, DcsWeaponFlag.ANY_AG_WEAPON, DcsWeaponFlag.ANY_WEAPON))
    elif flag in aam_flags:
        if flag != DcsWeaponFlag.ANY_AAM:
            parents.append(DcsWeaponFlag.ANY_AAM)
        parents.extend((DcsWeaponFlag.ANY_MISSILE, DcsWeaponFlag.GUIDED_WEAPON, DcsWeaponFlag.ANY_WEAPON))
    elif flag in {DcsWeaponFlag.GUN_POD, DcsWeaponFlag.BUILT_IN_CANNON, DcsWeaponFlag.CANNONS}:
        if flag != DcsWeaponFlag.CANNONS:
            parents.append(DcsWeaponFlag.CANNONS)
        parents.extend((DcsWeaponFlag.UNGUIDED_WEAPON, DcsWeaponFlag.ANY_AG_WEAPON, DcsWeaponFlag.ANY_WEAPON))
    elif flag in shell_flags and flag != DcsWeaponFlag.ANY_SHELL:
        parents.append(DcsWeaponFlag.ANY_SHELL)

    return tuple(dict.fromkeys(parent for parent in parents if parent != flag))


def _weapon_flag_associations(
    *,
    category: int | None,
    missile_category: int | None,
    guidance: int | None,
    warhead_type: int | None,
    role: WeaponRole,
    text: str,
) -> tuple[WeaponFlagAssociation, ...]:
    """Infer task selectors while preserving uncertainty and evidence."""

    direct: list[WeaponFlagAssociation] = []

    def add(flag: DcsWeaponFlag, confidence: MappingConfidence, source: str, *, specific: bool = True) -> None:
        direct.append(WeaponFlagAssociation(flag, confidence, source, specific))

    if role == WeaponRole.TORPEDO:
        add(DcsWeaponFlag.TORPEDO, MappingConfidence.HEURISTIC, "weapon name identifies a torpedo")
    elif category == DcsWeaponCategory.SHELL:
        if role in {WeaponRole.ARTILLERY, WeaponRole.MORTAR}:
            if "SMOKE" in text:
                add(DcsWeaponFlag.SMOKE_SHELL, MappingConfidence.HEURISTIC, "indirect-fire shell name contains SMOKE")
            elif any(value in text for value in ("ILLUM", "CANDLE")):
                add(DcsWeaponFlag.ILLUMINATION_SHELL, MappingConfidence.HEURISTIC, "indirect-fire shell name indicates illumination")
            elif any(value in text for value in ("DPICM", "SUBMUNITION")):
                add(DcsWeaponFlag.SUBMUNITION_DISPENSER_SHELL, MappingConfidence.HEURISTIC, "indirect-fire shell name indicates submunitions")
            elif "GUIDED" in text:
                add(DcsWeaponFlag.GUIDED_SHELL, MappingConfidence.HEURISTIC, "indirect-fire shell name indicates guidance")
            else:
                add(DcsWeaponFlag.CONVENTIONAL_SHELL, MappingConfidence.HEURISTIC, "ordinary ammunition on an indirect-fire unit")
        else:
            add(DcsWeaponFlag.BUILT_IN_CANNON, MappingConfidence.HEURISTIC, "shell belongs to an integral direct-fire weapon")
    elif category == DcsWeaponCategory.ROCKET:
        if "MARKER" in text:
            add(DcsWeaponFlag.MARKER_ROCKET, MappingConfidence.HEURISTIC, "rocket name contains MARKER")
        elif any(value in text for value in ("CANDLE", "ILLUM")):
            add(DcsWeaponFlag.CANDLE_ROCKET, MappingConfidence.HEURISTIC, "rocket name indicates illumination")
        else:
            add(DcsWeaponFlag.ANY_ROCKET, MappingConfidence.DERIVED, "DCS descriptor category is ROCKET", specific=False)
    elif category == DcsWeaponCategory.MISSILE:
        if missile_category == DcsMissileCategory.ANTI_SHIP:
            add(DcsWeaponFlag.ANTI_SHIP_MISSILE, MappingConfidence.DERIVED, "DCS missile category is ANTI_SHIP")
        elif missile_category == DcsMissileCategory.CRUISE:
            add(DcsWeaponFlag.CRUISE_MISSILE, MappingConfidence.DERIVED, "DCS missile category is CRUISE")
        elif missile_category == DcsMissileCategory.AAM:
            if guidance == DcsGuidanceType.IR:
                add(DcsWeaponFlag.IR_AAM, MappingConfidence.DERIVED, "DCS missile category is AAM and guidance is IR")
            elif guidance == DcsGuidanceType.RADAR_ACTIVE:
                add(DcsWeaponFlag.AR_AAM, MappingConfidence.DERIVED, "DCS missile category is AAM and guidance is active radar")
            elif guidance == DcsGuidanceType.RADAR_SEMI_ACTIVE:
                add(DcsWeaponFlag.SAR_AAM, MappingConfidence.DERIVED, "DCS missile category is AAM and guidance is semi-active radar")
            else:
                add(DcsWeaponFlag.ANY_AAM, MappingConfidence.DERIVED, "DCS missile category is AAM", specific=False)
        elif role == WeaponRole.ATGM:
            add(DcsWeaponFlag.ANTI_TANK_MISSILE, MappingConfidence.HEURISTIC, "unit attributes or weapon name identify an ATGM")
        elif role == WeaponRole.ANTI_SHIP:
            add(DcsWeaponFlag.ANTI_SHIP_MISSILE, MappingConfidence.HEURISTIC, "unit attributes or weapon name indicate anti-ship use")
    elif category == DcsWeaponCategory.BOMB:
        if guidance == DcsGuidanceType.LASER:
            add(DcsWeaponFlag.LGB, MappingConfidence.DERIVED, "DCS bomb guidance is LASER")
        elif guidance in {DcsGuidanceType.TV, DcsGuidanceType.TELE}:
            add(DcsWeaponFlag.TV_GUIDED_BOMB, MappingConfidence.DERIVED, "DCS bomb guidance is TV or TELE")
        elif guidance == DcsGuidanceType.INS:
            add(DcsWeaponFlag.SATELLITE_GUIDED_BOMB, MappingConfidence.HEURISTIC, "DCS bomb guidance is INS")
        elif warhead_type == DcsWarheadType.HE:
            add(DcsWeaponFlag.HE_BOMB, MappingConfidence.HEURISTIC, "unguided bomb has an HE warhead")
        elif warhead_type == DcsWarheadType.AP:
            add(DcsWeaponFlag.PENETRATOR, MappingConfidence.HEURISTIC, "unguided bomb has an AP warhead")
        else:
            add(DcsWeaponFlag.ANY_BOMB, MappingConfidence.DERIVED, "DCS descriptor category is BOMB", specific=False)

    associations = list(direct)
    for association in direct:
        associations.extend(
            WeaponFlagAssociation(
                flag=parent,
                confidence=association.confidence,
                source=f"parent selector of {association.flag.name}",
                specific=False,
            )
            for parent in _parent_weapon_flags(association.flag)
        )

    deduplicated: dict[DcsWeaponFlag, WeaponFlagAssociation] = {}
    for association in associations:
        previous = deduplicated.get(association.flag)
        if previous is None or (_CONFIDENCE_RANK[association.confidence], association.specific) > (
            _CONFIDENCE_RANK[previous.confidence],
            previous.specific,
        ):
            deduplicated[association.flag] = association
    return tuple(deduplicated.values())


def classify_ammunition_weapon(
    payload: dict[str, Any],
    *,
    unit_attributes: Iterable[str] = (),
    unit_category: str | None = None,
) -> WeaponClassification:
    """Classify one DCS ammunition descriptor without changing source data."""

    category = _int(payload.get("category"))
    missile_category = _int(payload.get("missile_category"))
    guidance = _int(payload.get("guidance"))
    warhead_type = _int(payload.get("warhead_type"))
    caliber = _float(payload.get("caliber"))
    text = " ".join(
        str(value or "") for value in (payload.get("type_name"), payload.get("display_name"), payload.get("id"))
    ).upper()
    attributes = {str(value).strip().lower() for value in unit_attributes}
    ammunition_type = _ammunition_type(text)

    if "TORPEDO" in text:
        family = WeaponFamily.TORPEDO
    elif "MINE" in text:
        family = WeaponFamily.MINE
    elif category == 0:
        family = WeaponFamily.CANNON if caliber is not None and caliber >= 20 else WeaponFamily.GUN
    elif category == 1:
        family = WeaponFamily.MISSILE
    elif category == 2:
        family = WeaponFamily.ROCKET
    elif category == 3:
        family = WeaponFamily.BOMB
    else:
        family = WeaponFamily.UNKNOWN

    if family == WeaponFamily.GUN:
        role = WeaponRole.MACHINE_GUN
    elif family == WeaponFamily.CANNON:
        if "MORTAR" in text:
            role = WeaponRole.MORTAR
        elif _contains_attribute(attributes, "artillery"):
            role = WeaponRole.ARTILLERY
        elif _contains_attribute(attributes, "tank") and caliber is not None and caliber >= 60:
            role = WeaponRole.MAIN_GUN
        elif _contains_attribute(attributes, "ifv") or (caliber is not None and 20 <= caliber < 60):
            role = WeaponRole.AUTOCANNON
        elif caliber is not None and caliber >= 60:
            role = WeaponRole.MAIN_GUN
        else:
            role = WeaponRole.UNKNOWN
    elif family == WeaponFamily.ROCKET:
        role = WeaponRole.ROCKET_ARTILLERY if _contains_attribute(attributes, "artillery", "mlrs") else WeaponRole.UNGUIDED_ROCKET
    elif family == WeaponFamily.MISSILE:
        if missile_category == DcsMissileCategory.ANTI_SHIP or any(
            value in text for value in ("ANTI-SHIP", "ANTISHIP", "HARPOON", "EXOCET")
        ):
            role = WeaponRole.ANTI_SHIP
        elif missile_category == DcsMissileCategory.SAM:
            role = WeaponRole.SAM
        elif missile_category in {DcsMissileCategory.BALLISTIC, DcsMissileCategory.CRUISE}:
            role = WeaponRole.SURFACE_TO_SURFACE
        elif _contains_attribute(attributes, "atgm") or any(value in text for value in ("TOW", "KORNET", "MILAN", "JAVELIN")):
            role = WeaponRole.ATGM
        elif _contains_attribute(attributes, "sam", "air defence", "air defense"):
            role = WeaponRole.SAM
        else:
            role = WeaponRole.UNKNOWN
    elif family == WeaponFamily.BOMB:
        role = WeaponRole.BOMB
    elif family == WeaponFamily.TORPEDO:
        role = WeaponRole.TORPEDO
    elif family == WeaponFamily.MINE:
        role = WeaponRole.MINE
    else:
        role = WeaponRole.UNKNOWN

    if role in {WeaponRole.ARTILLERY, WeaponRole.MORTAR, WeaponRole.ROCKET_ARTILLERY}:
        delivery = WeaponDelivery.INDIRECT
    elif role == WeaponRole.BOMB:
        delivery = WeaponDelivery.AIR_DELIVERED
    elif role == WeaponRole.MINE:
        delivery = WeaponDelivery.PASSIVE
    elif role == WeaponRole.UNKNOWN:
        delivery = WeaponDelivery.UNKNOWN
    else:
        delivery = WeaponDelivery.DIRECT

    normalized_category = str(unit_category or "").lower()
    if "ship" in normalized_category:
        launch_domain = CombatDomain.SEA
    elif "air" in normalized_category or "helicopter" in normalized_category:
        launch_domain = CombatDomain.AIR
    else:
        launch_domain = CombatDomain.SURFACE

    if role == WeaponRole.SAM:
        target_domains = {CombatDomain.AIR}
    elif role == WeaponRole.ANTI_SHIP:
        target_domains = {CombatDomain.SEA}
    elif role == WeaponRole.TORPEDO:
        target_domains = {CombatDomain.SEA, CombatDomain.SUBSURFACE}
    else:
        target_domains = {CombatDomain.SURFACE}

    effects: set[WeaponEffect] = set()
    explosive_mass = _float(payload.get("explosive_mass")) or 0.0
    shaped_penetration = _float(payload.get("shaped_explosive_armor_thickness")) or 0.0
    if role == WeaponRole.MACHINE_GUN:
        effects.add(WeaponEffect.ANTI_PERSONNEL)
        if caliber is not None and caliber >= 12.7:
            effects.add(WeaponEffect.ANTI_LIGHT_ARMOR)
    elif role in {WeaponRole.AUTOCANNON, WeaponRole.MAIN_GUN}:
        if ammunition_type in {"AP", "APDS", "APFSDS", "HEAT", "HESH"} or shaped_penetration > 0:
            effects.add(WeaponEffect.ANTI_ARMOR if role == WeaponRole.MAIN_GUN else WeaponEffect.ANTI_LIGHT_ARMOR)
        if ammunition_type in {"HE", "HEI", "HEAT", "HESH"} or explosive_mass > 0:
            effects.update({WeaponEffect.ANTI_PERSONNEL, WeaponEffect.AREA_EFFECT})
    elif role in {WeaponRole.ARTILLERY, WeaponRole.MORTAR, WeaponRole.ROCKET_ARTILLERY, WeaponRole.UNGUIDED_ROCKET}:
        effects.update(
            {WeaponEffect.ANTI_PERSONNEL, WeaponEffect.ANTI_STRUCTURE, WeaponEffect.AREA_EFFECT, WeaponEffect.SUPPRESSION}
        )
        if ammunition_type == "DPICM":
            effects.add(WeaponEffect.ANTI_LIGHT_ARMOR)
    elif role == WeaponRole.ATGM:
        effects.add(WeaponEffect.ANTI_ARMOR)
    elif role == WeaponRole.SAM:
        effects.add(WeaponEffect.ANTI_AIR)
    elif role == WeaponRole.ANTI_SHIP:
        effects.add(WeaponEffect.ANTI_SHIP)
    elif role == WeaponRole.SURFACE_TO_SURFACE:
        effects.update({WeaponEffect.ANTI_PERSONNEL, WeaponEffect.ANTI_STRUCTURE, WeaponEffect.AREA_EFFECT})
    elif role == WeaponRole.TORPEDO:
        effects.update({WeaponEffect.ANTI_SHIP, WeaponEffect.ANTI_SUBMARINE})
    elif role == WeaponRole.BOMB:
        effects.update({WeaponEffect.ANTI_PERSONNEL, WeaponEffect.ANTI_STRUCTURE, WeaponEffect.AREA_EFFECT})

    weapon_flags = _weapon_flag_associations(
        category=category,
        missile_category=missile_category,
        guidance=guidance,
        warhead_type=warhead_type,
        role=role,
        text=text,
    )

    return WeaponClassification(
        family=family,
        role=role,
        delivery=delivery,
        launch_domain=launch_domain,
        target_domains=tuple(sorted(target_domains, key=lambda value: value.value)),
        effects=tuple(sorted(effects, key=lambda value: value.value)),
        ammunition_type=ammunition_type,
        weapon_flags=weapon_flags,
    )


@dataclass(slots=True, frozen=True)
class AmmunitionWeapon:
    """One current and initially observed weapon-ammunition entry."""

    id: str
    current_count: int
    initial_count: int
    fraction: float | None
    classification: WeaponClassification
    category: DcsWeaponCategory | None = None
    type_name: str | None = None
    display_name: str | None = None
    missile_category: DcsMissileCategory | None = None
    guidance: DcsGuidanceType | None = None
    range_min_m: float | None = None
    range_max_alt_min_m: float | None = None
    range_max_alt_max_m: float | None = None
    distance_min_m: float | None = None
    distance_max_m: float | None = None
    altitude_min_m: float | None = None
    altitude_max_m: float | None = None
    warhead_type: DcsWarheadType | None = None
    caliber: float | None = None
    warhead_mass: float | None = None
    explosive_mass: float | None = None
    shaped_explosive_mass: float | None = None
    shaped_explosive_armor_thickness: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        unit_attributes: Iterable[str] = (),
        unit_category: str | None = None,
    ) -> "AmmunitionWeapon":
        current = max(0, _int(payload.get("count")) or 0)
        initial = max(0, _int(payload.get("initial_count")) or 0)
        fraction = current / initial if initial > 0 else None
        return cls(
            id=str(payload.get("id") or payload.get("type_name") or "unknown"),
            current_count=current,
            initial_count=initial,
            fraction=min(1.0, max(0.0, fraction)) if fraction is not None else None,
            classification=classify_ammunition_weapon(
                payload,
                unit_attributes=unit_attributes,
                unit_category=unit_category,
            ),
            category=_enum(DcsWeaponCategory, payload.get("category")),
            type_name=_string(payload.get("type_name")),
            display_name=_string(payload.get("display_name")),
            missile_category=_enum(DcsMissileCategory, payload.get("missile_category")),
            guidance=_enum(DcsGuidanceType, payload.get("guidance")),
            range_min_m=_float(payload.get("range_min_m")),
            range_max_alt_min_m=_float(payload.get("range_max_alt_min_m")),
            range_max_alt_max_m=_float(payload.get("range_max_alt_max_m")),
            distance_min_m=_float(payload.get("distance_min_m")),
            distance_max_m=_float(payload.get("distance_max_m")),
            altitude_min_m=_float(payload.get("altitude_min_m")),
            altitude_max_m=_float(payload.get("altitude_max_m")),
            warhead_type=_enum(DcsWarheadType, payload.get("warhead_type")),
            caliber=_float(payload.get("caliber")),
            warhead_mass=_float(payload.get("warhead_mass")),
            explosive_mass=_float(payload.get("explosive_mass")),
            shaped_explosive_mass=_float(payload.get("shaped_explosive_mass")),
            shaped_explosive_armor_thickness=_float(payload.get("shaped_explosive_armor_thickness")),
            raw=payload,
        )

    @property
    def family(self) -> WeaponFamily:
        return self.classification.family

    @property
    def role(self) -> WeaponRole:
        return self.classification.role

    @property
    def delivery(self) -> WeaponDelivery:
        return self.classification.delivery

    @property
    def effects(self) -> tuple[WeaponEffect, ...]:
        return self.classification.effects

    @property
    def launch_domain(self) -> CombatDomain:
        return self.classification.launch_domain

    @property
    def target_domains(self) -> tuple[CombatDomain, ...]:
        return self.classification.target_domains

    @property
    def ammunition_type(self) -> str | None:
        return self.classification.ammunition_type

    @property
    def weapon_flags(self) -> tuple[WeaponFlagAssociation, ...]:
        """Return all known specific and parent DCS task selectors."""

        return self.classification.weapon_flags

    @property
    def specific_weapon_flags(self) -> tuple[WeaponFlagAssociation, ...]:
        """Return the narrowest selectors inferred directly for this ammunition."""

        return tuple(association for association in self.weapon_flags if association.specific)

    @property
    def preferred_weapon_flag(self) -> DcsWeaponFlag | None:
        """Return the narrowest task selector, or a broad selector when necessary."""

        return self.weapon_flags[0].flag if self.weapon_flags else None


@dataclass(slots=True, frozen=True)
class UnitAmmunition:
    """Detailed ammunition state for one active, living ground or naval unit."""

    unit_id: str
    unit_name: str
    group_id: str | None
    group_name: str | None
    dcs_type: str | None
    category: str | None
    attributes: tuple[str, ...]
    life: float | None
    life0: float | None
    weapons: tuple[AmmunitionWeapon, ...]
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "UnitAmmunition":
        raw_weapons = payload.get("weapons") if isinstance(payload.get("weapons"), list) else []
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), list) else []
        normalized_attributes = tuple(sorted(str(value) for value in attributes))
        category = _string(payload.get("category"))
        return cls(
            unit_id=str(payload.get("unit_id") or payload.get("object_id") or ""),
            unit_name=str(payload.get("unit_name") or payload.get("dcs_name") or ""),
            group_id=_string(payload.get("group_id")),
            group_name=_string(payload.get("group_name")),
            dcs_type=_string(payload.get("dcs_type")),
            category=category,
            attributes=normalized_attributes,
            life=_float(payload.get("life")),
            life0=_float(payload.get("life0")),
            weapons=tuple(
                AmmunitionWeapon.from_payload(
                    item,
                    unit_attributes=normalized_attributes,
                    unit_category=category,
                )
                for item in raw_weapons
                if isinstance(item, dict)
            ),
            raw=payload,
        )

    @property
    def life_fraction(self) -> float | None:
        """Return remaining relative life when DCS supplied a valid baseline."""

        if self.life is None or self.life0 is None or self.life0 <= 0:
            return None
        return min(1.0, max(0.0, self.life / self.life0))


def select_task_weapon(
    weapons: Iterable[AmmunitionWeapon],
    *,
    role: WeaponRole | str | None = None,
) -> TaskWeaponSelection:
    """Select the best supported DCS task flag from currently available ammo."""

    normalized_role = WeaponRole(role) if role is not None else None
    candidates: dict[DcsWeaponFlag, tuple[WeaponFlagAssociation, list[str]]] = {}
    for weapon in weapons:
        if weapon.current_count <= 0 or (normalized_role is not None and weapon.role != normalized_role):
            continue
        if not weapon.weapon_flags:
            continue
        association = weapon.weapon_flags[0]
        existing = candidates.get(association.flag)
        if existing is None:
            candidates[association.flag] = (association, [weapon.id])
        else:
            existing[1].append(weapon.id)
            if _CONFIDENCE_RANK[association.confidence] > _CONFIDENCE_RANK[existing[0].confidence]:
                candidates[association.flag] = (association, existing[1])

    if not candidates:
        role_text = f" for role {normalized_role.value}" if normalized_role is not None else ""
        return TaskWeaponSelection(reason=f"No available ammunition has a compatible DCS weapon flag{role_text}.")

    if len(candidates) > 1:
        names = ", ".join(sorted(flag.name for flag in candidates))
        role_text = f" for role {normalized_role.value}" if normalized_role is not None else ""
        return TaskWeaponSelection(
            reason=f"Multiple DCS weapon flags are available{role_text}: {names}. Specify a narrower role or selector."
        )

    association, weapon_ids = next(iter(candidates.values()))
    return TaskWeaponSelection(
        weapon_flag=association.flag,
        matching_weapon_ids=tuple(sorted(set(weapon_ids))),
        confidence=association.confidence,
        reason=association.source,
    )


@dataclass(slots=True)
class AmmunitionTracker:
    """Track the maximum observed count per mission, unit, and weapon id."""

    _initial_counts: dict[tuple[str, str, str], int] = field(default_factory=dict)

    def update(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return copied payloads enriched with observed initial counts."""

        enriched_items: list[dict[str, Any]] = []
        for source_item in items:
            item = dict(source_item)
            unit_id = str(item.get("unit_id") or item.get("object_id") or "")
            dcs_type = str(item.get("dcs_type") or "")
            raw_weapons = item.get("weapons") if isinstance(item.get("weapons"), list) else []
            weapons: list[dict[str, Any]] = []
            for source_weapon in raw_weapons:
                if not isinstance(source_weapon, dict):
                    continue
                weapon = dict(source_weapon)
                weapon_id = str(weapon.get("id") or weapon.get("type_name") or "unknown")
                current = max(0, _int(weapon.get("count")) or 0)
                supplied_initial = max(0, _int(weapon.get("initial_count")) or 0)
                key = (unit_id, dcs_type, weapon_id)
                initial = max(self._initial_counts.get(key, 0), supplied_initial, current)
                self._initial_counts[key] = initial
                weapon["id"] = weapon_id
                weapon["count"] = current
                weapon["initial_count"] = initial
                weapon["fraction"] = min(1.0, max(0.0, current / initial)) if initial > 0 else None
                weapons.append(weapon)
            item["weapons"] = sorted(weapons, key=lambda value: str(value.get("id") or ""))
            enriched_items.append(item)
        return enriched_items

    def reset(self) -> None:
        """Discard observations from a previous mission timeline."""

        self._initial_counts.clear()
