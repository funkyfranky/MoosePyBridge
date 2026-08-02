"""Combat capability and readiness aggregation for DCS ground units."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable

from .ammunition import AmmunitionWeapon, DcsWeaponFlag, UnitAmmunition, WeaponEffect, WeaponRole
from .weapon_ranges import DEFAULT_WEAPON_RANGE_REGISTRY, WeaponRangeRegistry


class CapabilityKind(str, Enum):
    """Broad capabilities used by tactical and territorial reasoning."""

    PRESENCE = "presence"
    ANTI_PERSONNEL = "anti_personnel"
    ANTI_LIGHT_ARMOR = "anti_light_armor"
    ANTI_ARMOR = "anti_armor"
    INDIRECT_FIRE = "indirect_fire"
    AIR_DEFENSE = "air_defense"
    ANTI_SHIP = "anti_ship"


class InfluenceKind(str, Enum):
    """Independent spatial effects used by tactical reasoning."""

    CONTROL = "control"
    DIRECT_FIRE = "direct_fire"
    INDIRECT_FIRE = "indirect_fire"
    AIR_DEFENSE = "air_defense"
    LOGISTICS = "logistics"


@dataclass(slots=True, frozen=True)
class CapabilityReadiness:
    """One capability with traceable base, ammunition, health, and result."""

    kind: CapabilityKind
    base_power: float
    ammo_readiness: float
    health_readiness: float
    effective_power: float
    contributing_roles: tuple[WeaponRole, ...] = ()


@dataclass(slots=True, frozen=True)
class UnitCapabilities:
    """Capability readiness vector for one unit."""

    unit_id: str
    group_id: str | None
    dcs_type: str | None
    capabilities: tuple[CapabilityReadiness, ...]

    def get(self, kind: CapabilityKind | str) -> CapabilityReadiness | None:
        """Return one capability by enum or string value."""

        normalized = CapabilityKind(kind)
        return next((item for item in self.capabilities if item.kind == normalized), None)


@dataclass(slots=True, frozen=True)
class GroupCapabilities:
    """Aggregated capability readiness for a DCS/MOOSE group."""

    group_id: str
    units: tuple[UnitCapabilities, ...]
    capabilities: tuple[CapabilityReadiness, ...]

    def get(self, kind: CapabilityKind | str) -> CapabilityReadiness | None:
        """Return one aggregated capability by enum or string value."""

        normalized = CapabilityKind(kind)
        return next((item for item in self.capabilities if item.kind == normalized), None)


@dataclass(slots=True, frozen=True)
class InfluenceReadiness:
    """One traceable tactical influence contribution."""

    kind: InfluenceKind
    base_power: float
    ammo_readiness: float
    health_readiness: float
    effective_power: float
    minimum_range_m: float = 0.0
    maximum_range_m: float = 0.0
    contributing_roles: tuple[WeaponRole, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("base_power", self.base_power),
            ("ammo_readiness", self.ammo_readiness),
            ("health_readiness", self.health_readiness),
            ("effective_power", self.effective_power),
            ("minimum_range_m", self.minimum_range_m),
            ("maximum_range_m", self.maximum_range_m),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.maximum_range_m < self.minimum_range_m:
            raise ValueError("maximum_range_m must not be smaller than minimum_range_m")


@dataclass(slots=True, frozen=True)
class UnitInfluence:
    """Separated tactical influences for one active ground unit."""

    unit_id: str
    group_id: str | None
    dcs_type: str | None
    influences: tuple[InfluenceReadiness, ...]

    def get(self, kind: InfluenceKind | str) -> InfluenceReadiness | None:
        normalized = InfluenceKind(kind)
        return next((item for item in self.influences if item.kind == normalized), None)


@dataclass(slots=True, frozen=True)
class GroupInfluence:
    """Aggregated tactical influences for one DCS group."""

    group_id: str
    units: tuple[UnitInfluence, ...]
    influences: tuple[InfluenceReadiness, ...]

    def get(self, kind: InfluenceKind | str) -> InfluenceReadiness | None:
        normalized = InfluenceKind(kind)
        return next((item for item in self.influences if item.kind == normalized), None)


# These coefficients are relative defaults for diagnostics and later scenario
# calibration. They are deliberately centralized and do not claim to be DCS
# weapon-performance values.
ROLE_CAPABILITY_POWER: dict[tuple[WeaponRole, CapabilityKind], float] = {
    (WeaponRole.MACHINE_GUN, CapabilityKind.ANTI_PERSONNEL): 0.25,
    (WeaponRole.MACHINE_GUN, CapabilityKind.ANTI_LIGHT_ARMOR): 0.15,
    (WeaponRole.AUTOCANNON, CapabilityKind.ANTI_PERSONNEL): 0.60,
    (WeaponRole.AUTOCANNON, CapabilityKind.ANTI_LIGHT_ARMOR): 1.00,
    (WeaponRole.MAIN_GUN, CapabilityKind.ANTI_PERSONNEL): 0.60,
    (WeaponRole.MAIN_GUN, CapabilityKind.ANTI_ARMOR): 1.50,
    (WeaponRole.ATGM, CapabilityKind.ANTI_ARMOR): 1.25,
    (WeaponRole.ARTILLERY, CapabilityKind.INDIRECT_FIRE): 1.00,
    (WeaponRole.MORTAR, CapabilityKind.INDIRECT_FIRE): 0.70,
    (WeaponRole.ROCKET_ARTILLERY, CapabilityKind.INDIRECT_FIRE): 1.20,
    (WeaponRole.SAM, CapabilityKind.AIR_DEFENSE): 1.00,
    (WeaponRole.ANTI_SHIP, CapabilityKind.ANTI_SHIP): 1.00,
}

CAPABILITY_EFFECT: dict[CapabilityKind, WeaponEffect] = {
    CapabilityKind.ANTI_PERSONNEL: WeaponEffect.ANTI_PERSONNEL,
    CapabilityKind.ANTI_LIGHT_ARMOR: WeaponEffect.ANTI_LIGHT_ARMOR,
    CapabilityKind.ANTI_ARMOR: WeaponEffect.ANTI_ARMOR,
    CapabilityKind.AIR_DEFENSE: WeaponEffect.ANTI_AIR,
    CapabilityKind.ANTI_SHIP: WeaponEffect.ANTI_SHIP,
}

INDIRECT_ROLES = frozenset({WeaponRole.ARTILLERY, WeaponRole.MORTAR, WeaponRole.ROCKET_ARTILLERY})
DIRECT_COMBAT_ROLES = frozenset(
    {WeaponRole.MACHINE_GUN, WeaponRole.AUTOCANNON, WeaponRole.MAIN_GUN, WeaponRole.ATGM}
)

ROLE_INFLUENCE_POWER: dict[tuple[WeaponRole, InfluenceKind], float] = {
    (WeaponRole.MACHINE_GUN, InfluenceKind.CONTROL): 0.25,
    (WeaponRole.AUTOCANNON, InfluenceKind.CONTROL): 1.00,
    (WeaponRole.MAIN_GUN, InfluenceKind.CONTROL): 1.50,
    (WeaponRole.ATGM, InfluenceKind.CONTROL): 1.25,
    (WeaponRole.ARTILLERY, InfluenceKind.CONTROL): 0.15,
    (WeaponRole.MORTAR, InfluenceKind.CONTROL): 0.15,
    (WeaponRole.ROCKET_ARTILLERY, InfluenceKind.CONTROL): 0.10,
    (WeaponRole.MACHINE_GUN, InfluenceKind.DIRECT_FIRE): 0.25,
    (WeaponRole.AUTOCANNON, InfluenceKind.DIRECT_FIRE): 1.00,
    (WeaponRole.MAIN_GUN, InfluenceKind.DIRECT_FIRE): 1.50,
    (WeaponRole.ATGM, InfluenceKind.DIRECT_FIRE): 1.25,
    (WeaponRole.ARTILLERY, InfluenceKind.INDIRECT_FIRE): 1.00,
    (WeaponRole.MORTAR, InfluenceKind.INDIRECT_FIRE): 0.70,
    (WeaponRole.ROCKET_ARTILLERY, InfluenceKind.INDIRECT_FIRE): 1.20,
    (WeaponRole.SAM, InfluenceKind.AIR_DEFENSE): 1.00,
}

ROLE_WEAPON_FLAG: dict[WeaponRole, DcsWeaponFlag] = {
    WeaponRole.MACHINE_GUN: DcsWeaponFlag.BUILT_IN_CANNON,
    WeaponRole.AUTOCANNON: DcsWeaponFlag.BUILT_IN_CANNON,
    WeaponRole.MAIN_GUN: DcsWeaponFlag.BUILT_IN_CANNON,
    WeaponRole.ATGM: DcsWeaponFlag.ANTI_TANK_MISSILE,
    WeaponRole.ARTILLERY: DcsWeaponFlag.CONVENTIONAL_SHELL,
    WeaponRole.MORTAR: DcsWeaponFlag.CONVENTIONAL_SHELL,
    WeaponRole.ROCKET_ARTILLERY: DcsWeaponFlag.ANY_ROCKET,
    WeaponRole.SAM: DcsWeaponFlag.ANY_MISSILE,
}

LOGISTICS_ATTRIBUTE_TERMS = (
    "logistic",
    "supply",
    "truck",
    "transport",
    "unarmed",
    "refuel",
    "fuel",
)
LOGISTICS_POWER = 0.10


def _health_readiness(unit: UnitAmmunition) -> float:
    return unit.life_fraction if unit.life_fraction is not None else 1.0


def _role_ammunition_readiness(weapons: Iterable[AmmunitionWeapon]) -> float:
    values = tuple(weapons)
    initial = sum(weapon.initial_count for weapon in values)
    if initial <= 0:
        return 0.0
    current = sum(min(weapon.current_count, weapon.initial_count) for weapon in values)
    return min(1.0, max(0.0, current / initial))


def _matching_weapons(
    unit: UnitAmmunition,
    role: WeaponRole,
    capability: CapabilityKind,
) -> tuple[AmmunitionWeapon, ...]:
    effect = CAPABILITY_EFFECT.get(capability)
    return tuple(
        weapon
        for weapon in unit.weapons
        if weapon.role == role and (capability == CapabilityKind.INDIRECT_FIRE or effect in weapon.effects)
    )


def _presence_power(unit: UnitAmmunition) -> float:
    roles = {weapon.role for weapon in unit.weapons}
    if roles & DIRECT_COMBAT_ROLES:
        return 1.0
    if roles & INDIRECT_ROLES:
        return 0.35
    if WeaponRole.SAM in roles or WeaponRole.ANTI_SHIP in roles:
        return 0.25
    return 0.10


def build_unit_capabilities(unit: UnitAmmunition) -> UnitCapabilities:
    """Build a traceable readiness vector without mixing ammunition roles."""

    health = _health_readiness(unit)
    values: list[CapabilityReadiness] = []
    presence = _presence_power(unit)
    values.append(
        CapabilityReadiness(
            kind=CapabilityKind.PRESENCE,
            base_power=presence,
            ammo_readiness=1.0,
            health_readiness=health,
            effective_power=presence * health,
        )
    )

    for capability in CapabilityKind:
        if capability == CapabilityKind.PRESENCE:
            continue
        contributions: list[tuple[WeaponRole, float, float]] = []
        for (role, candidate), base_power in ROLE_CAPABILITY_POWER.items():
            if candidate != capability:
                continue
            weapons = _matching_weapons(unit, role, capability)
            if weapons:
                contributions.append((role, base_power, _role_ammunition_readiness(weapons)))
        if not contributions:
            continue
        base_power = sum(value[1] for value in contributions)
        ammo_weighted_power = sum(value[1] * value[2] for value in contributions)
        ammo_readiness = ammo_weighted_power / base_power if base_power > 0 else 0.0
        values.append(
            CapabilityReadiness(
                kind=capability,
                base_power=base_power,
                ammo_readiness=ammo_readiness,
                health_readiness=health,
                effective_power=ammo_weighted_power * health,
                contributing_roles=tuple(sorted((value[0] for value in contributions), key=lambda role: role.value)),
            )
        )

    return UnitCapabilities(
        unit_id=unit.unit_id,
        group_id=unit.group_id,
        dcs_type=unit.dcs_type,
        capabilities=tuple(values),
    )


def build_group_capabilities(
    units: Iterable[UnitAmmunition],
    group_id: str,
) -> GroupCapabilities:
    """Aggregate unit readiness while retaining role-relative weighting."""

    unit_profiles = tuple(sorted((build_unit_capabilities(unit) for unit in units), key=lambda item: item.unit_id))
    values: list[CapabilityReadiness] = []
    for capability in CapabilityKind:
        entries = tuple(
            entry
            for unit in unit_profiles
            if (entry := unit.get(capability)) is not None
        )
        if not entries:
            continue
        base_power = sum(entry.base_power for entry in entries)
        ammo_readiness = (
            sum(entry.base_power * entry.ammo_readiness for entry in entries) / base_power if base_power > 0 else 0.0
        )
        health_readiness = (
            sum(entry.base_power * entry.health_readiness for entry in entries) / base_power if base_power > 0 else 0.0
        )
        roles = {role for entry in entries for role in entry.contributing_roles}
        values.append(
            CapabilityReadiness(
                kind=capability,
                base_power=base_power,
                ammo_readiness=ammo_readiness,
                health_readiness=health_readiness,
                effective_power=sum(entry.effective_power for entry in entries),
                contributing_roles=tuple(sorted(roles, key=lambda role: role.value)),
            )
        )
    return GroupCapabilities(group_id=group_id, units=unit_profiles, capabilities=tuple(values))


def _is_logistics_unit(unit: UnitAmmunition) -> bool:
    attributes = " ".join(unit.attributes).casefold()
    armed_roles = {weapon.role for weapon in unit.weapons if weapon.role != WeaponRole.UNKNOWN}
    if armed_roles:
        return False
    if "unarmed" in attributes:
        return True
    return not unit.weapons and any(term in attributes for term in LOGISTICS_ATTRIBUTE_TERMS)


def _role_range(
    unit: UnitAmmunition,
    role: WeaponRole,
    weapons: tuple[AmmunitionWeapon, ...],
    registry: WeaponRangeRegistry,
) -> tuple[float, float]:
    flag = ROLE_WEAPON_FLAG.get(role)
    if flag is None or not unit.dcs_type:
        return 0.0, 0.0
    profile = registry.resolve(unit.dcs_type, flag, ammunition=weapons)
    return (profile.minimum_m, profile.maximum_m) if profile is not None else (0.0, 0.0)


def build_unit_influence(
    unit: UnitAmmunition,
    *,
    weapon_ranges: WeaponRangeRegistry = DEFAULT_WEAPON_RANGE_REGISTRY,
) -> UnitInfluence:
    """Build independent control, fire, air-defense, and logistics effects."""

    health = _health_readiness(unit)
    values: list[InfluenceReadiness] = []
    for kind in (
        InfluenceKind.CONTROL,
        InfluenceKind.DIRECT_FIRE,
        InfluenceKind.INDIRECT_FIRE,
        InfluenceKind.AIR_DEFENSE,
    ):
        contributions: list[tuple[WeaponRole, float, float, float, float]] = []
        for (role, candidate), base_power in ROLE_INFLUENCE_POWER.items():
            if candidate != kind:
                continue
            weapons = tuple(weapon for weapon in unit.weapons if weapon.role == role)
            if not weapons:
                continue
            ammo = _role_ammunition_readiness(weapons)
            minimum, maximum = (
                (0.0, 0.0)
                if kind == InfluenceKind.CONTROL
                else _role_range(unit, role, weapons, weapon_ranges)
            )
            contributions.append((role, base_power, ammo, minimum, maximum))
        if not contributions:
            continue
        base_power = sum(item[1] for item in contributions)
        ready_power = sum(item[1] * item[2] for item in contributions)
        values.append(
            InfluenceReadiness(
                kind=kind,
                base_power=base_power,
                ammo_readiness=ready_power / base_power if base_power else 0.0,
                health_readiness=health,
                effective_power=ready_power * health,
                minimum_range_m=min(item[3] for item in contributions),
                maximum_range_m=max(item[4] for item in contributions),
                contributing_roles=tuple(sorted((item[0] for item in contributions), key=lambda role: role.value)),
            )
        )

    if _is_logistics_unit(unit):
        values.append(
            InfluenceReadiness(
                kind=InfluenceKind.LOGISTICS,
                base_power=LOGISTICS_POWER,
                ammo_readiness=1.0,
                health_readiness=health,
                effective_power=LOGISTICS_POWER * health,
                maximum_range_m=5_000.0,
            )
        )

    return UnitInfluence(unit.unit_id, unit.group_id, unit.dcs_type, tuple(values))


def build_group_influence(
    units: Iterable[UnitAmmunition],
    group_id: str,
    *,
    weapon_ranges: WeaponRangeRegistry = DEFAULT_WEAPON_RANGE_REGISTRY,
) -> GroupInfluence:
    """Aggregate separated tactical influences for one group."""

    unit_profiles = tuple(
        sorted(
            (build_unit_influence(unit, weapon_ranges=weapon_ranges) for unit in units),
            key=lambda item: item.unit_id,
        )
    )
    values: list[InfluenceReadiness] = []
    for kind in InfluenceKind:
        entries = tuple(entry for unit in unit_profiles if (entry := unit.get(kind)) is not None)
        if not entries:
            continue
        base_power = sum(entry.base_power for entry in entries)
        roles = {role for entry in entries for role in entry.contributing_roles}
        values.append(
            InfluenceReadiness(
                kind=kind,
                base_power=base_power,
                ammo_readiness=(
                    sum(entry.base_power * entry.ammo_readiness for entry in entries) / base_power
                    if base_power else 0.0
                ),
                health_readiness=(
                    sum(entry.base_power * entry.health_readiness for entry in entries) / base_power
                    if base_power else 0.0
                ),
                effective_power=sum(entry.effective_power for entry in entries),
                minimum_range_m=min(entry.minimum_range_m for entry in entries),
                maximum_range_m=max(entry.maximum_range_m for entry in entries),
                contributing_roles=tuple(sorted(roles, key=lambda role: role.value)),
            )
        )
    return GroupInfluence(group_id, unit_profiles, tuple(values))
