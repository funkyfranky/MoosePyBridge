"""Combat capability and readiness aggregation for DCS ground units."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .ammunition import AmmunitionWeapon, UnitAmmunition, WeaponEffect, WeaponRole


class CapabilityKind(str, Enum):
    """Broad capabilities used by tactical and territorial reasoning."""

    PRESENCE = "presence"
    ANTI_PERSONNEL = "anti_personnel"
    ANTI_LIGHT_ARMOR = "anti_light_armor"
    ANTI_ARMOR = "anti_armor"
    INDIRECT_FIRE = "indirect_fire"
    AIR_DEFENSE = "air_defense"
    ANTI_SHIP = "anti_ship"


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
