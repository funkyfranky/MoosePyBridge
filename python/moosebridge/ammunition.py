"""Typed ammunition snapshots and observed-initial-count tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Iterable


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


def classify_ammunition_weapon(
    payload: dict[str, Any],
    *,
    unit_attributes: Iterable[str] = (),
    unit_category: str | None = None,
) -> WeaponClassification:
    """Classify one DCS ammunition descriptor without changing source data."""

    category = _int(payload.get("category"))
    missile_category = _int(payload.get("missile_category"))
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
        if missile_category == 4 or any(value in text for value in ("ANTI-SHIP", "ANTISHIP", "HARPOON", "EXOCET")):
            role = WeaponRole.ANTI_SHIP
        elif missile_category == 2:
            role = WeaponRole.SAM
        elif _contains_attribute(attributes, "atgm") or any(value in text for value in ("TOW", "KORNET", "MILAN", "JAVELIN")):
            role = WeaponRole.ATGM
        elif _contains_attribute(attributes, "sam", "air defence", "air defense"):
            role = WeaponRole.SAM
        else:
            role = WeaponRole.SURFACE_TO_SURFACE
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
    elif role == WeaponRole.TORPEDO:
        effects.update({WeaponEffect.ANTI_SHIP, WeaponEffect.ANTI_SUBMARINE})
    elif role == WeaponRole.BOMB:
        effects.update({WeaponEffect.ANTI_PERSONNEL, WeaponEffect.ANTI_STRUCTURE, WeaponEffect.AREA_EFFECT})

    return WeaponClassification(
        family=family,
        role=role,
        delivery=delivery,
        launch_domain=launch_domain,
        target_domains=tuple(sorted(target_domains, key=lambda value: value.value)),
        effects=tuple(sorted(effects, key=lambda value: value.value)),
        ammunition_type=ammunition_type,
    )


@dataclass(slots=True, frozen=True)
class AmmunitionWeapon:
    """One current and initially observed weapon-ammunition entry."""

    id: str
    current_count: int
    initial_count: int
    fraction: float | None
    classification: WeaponClassification
    category: int | None = None
    type_name: str | None = None
    display_name: str | None = None
    missile_category: int | None = None
    guidance: int | None = None
    range_min_m: float | None = None
    range_max_alt_min_m: float | None = None
    range_max_alt_max_m: float | None = None
    distance_min_m: float | None = None
    distance_max_m: float | None = None
    warhead_type: int | None = None
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
            category=_int(payload.get("category")),
            type_name=_string(payload.get("type_name")),
            display_name=_string(payload.get("display_name")),
            missile_category=_int(payload.get("missile_category")),
            guidance=_int(payload.get("guidance")),
            range_min_m=_float(payload.get("range_min_m")),
            range_max_alt_min_m=_float(payload.get("range_max_alt_min_m")),
            range_max_alt_max_m=_float(payload.get("range_max_alt_max_m")),
            distance_min_m=_float(payload.get("distance_min_m")),
            distance_max_m=_float(payload.get("distance_max_m")),
            warhead_type=_int(payload.get("warhead_type")),
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


@dataclass(slots=True, frozen=True)
class UnitAmmunition:
    """Detailed ammunition state for one active, living ground unit."""

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
