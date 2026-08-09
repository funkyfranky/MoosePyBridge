"""Task-oriented weapon range profiles keyed by DCS type and weapon flag."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable

from .ammunition import AmmunitionWeapon, DcsWeaponCategory, DcsWeaponFlag, WeaponRole
from .datamine_ranges import DEFAULT_DATAMINE_RANGE_DATA, DatamineRangeData


class RangeSource(str, Enum):
    """Origin of a task weapon range profile."""

    MANUAL = "manual"
    DCS_DATAMINE_WEAPON = "dcs_datamine_weapon"
    DCS_DESCRIPTOR = "dcs_descriptor"
    DCS_DATAMINE_UNIT = "dcs_datamine_unit"
    ROLE_FALLBACK = "role_fallback"
    FLAG_FALLBACK = "flag_fallback"


@dataclass(slots=True, frozen=True)
class WeaponRangeProfile:
    """Range envelope for one DCS unit type and task weapon selector."""

    dcs_type: str
    weapon_flag: DcsWeaponFlag
    minimum_m: float
    maximum_m: float
    source: RangeSource
    weapon_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.dcs_type.strip():
            raise ValueError("dcs_type must not be empty")
        if not math.isfinite(self.minimum_m) or self.minimum_m < 0:
            raise ValueError("minimum_m must be a finite, non-negative number")
        if not math.isfinite(self.maximum_m) or self.maximum_m < self.minimum_m:
            raise ValueError("maximum_m must be finite and greater than or equal to minimum_m")

    def contains(self, distance_m: float) -> bool:
        """Return whether a distance lies inside the inclusive range envelope."""

        return math.isfinite(distance_m) and self.minimum_m <= distance_m <= self.maximum_m


@dataclass(slots=True, frozen=True)
class WeaponRangeFallback:
    """Conservative default range for one tactical role and DCS selector."""

    role: WeaponRole
    weapon_flag: DcsWeaponFlag
    minimum_m: float
    maximum_m: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.minimum_m) or self.minimum_m < 0:
            raise ValueError("minimum_m must be a finite, non-negative number")
        if not math.isfinite(self.maximum_m) or self.maximum_m < self.minimum_m:
            raise ValueError("maximum_m must be finite and greater than or equal to minimum_m")


MANUAL_WEAPON_RANGE_PROFILES: tuple[WeaponRangeProfile, ...] = ()


FLAG_RANGE_FALLBACKS: tuple[WeaponRangeProfile, ...] = ()


ROLE_RANGE_FALLBACKS: tuple[WeaponRangeFallback, ...] = (
    WeaponRangeFallback(
        role=WeaponRole.MACHINE_GUN,
        weapon_flag=DcsWeaponFlag.BUILT_IN_CANNON,
        minimum_m=0,
        maximum_m=800,
    ),
    WeaponRangeFallback(
        role=WeaponRole.AUTOCANNON,
        weapon_flag=DcsWeaponFlag.BUILT_IN_CANNON,
        minimum_m=50,
        maximum_m=1_500,
    ),
    WeaponRangeFallback(
        role=WeaponRole.MAIN_GUN,
        weapon_flag=DcsWeaponFlag.BUILT_IN_CANNON,
        minimum_m=50,
        maximum_m=2_000,
    ),
    WeaponRangeFallback(
        role=WeaponRole.ATGM,
        weapon_flag=DcsWeaponFlag.ANTI_TANK_MISSILE,
        minimum_m=100,
        maximum_m=3_000,
    ),
    WeaponRangeFallback(
        role=WeaponRole.MORTAR,
        weapon_flag=DcsWeaponFlag.CONVENTIONAL_SHELL,
        minimum_m=100,
        maximum_m=5_000,
    ),
    WeaponRangeFallback(
        role=WeaponRole.ARTILLERY,
        weapon_flag=DcsWeaponFlag.CONVENTIONAL_SHELL,
        minimum_m=500,
        maximum_m=15_000,
    ),
    WeaponRangeFallback(
        role=WeaponRole.ROCKET_ARTILLERY,
        weapon_flag=DcsWeaponFlag.ANY_ROCKET,
        minimum_m=5_000,
        maximum_m=20_000,
    ),
)


def _profile_key(dcs_type: str, weapon_flag: DcsWeaponFlag | int) -> tuple[str, DcsWeaponFlag]:
    return dcs_type.strip().casefold(), DcsWeaponFlag(weapon_flag)


def _descriptor_range(weapon: AmmunitionWeapon) -> tuple[float, float] | None:
    """Return a usable descriptor range without treating zero placeholders as data."""

    if weapon.category == DcsWeaponCategory.MISSILE:
        minimum = weapon.range_min_m
        maxima = (weapon.range_max_alt_min_m, weapon.range_max_alt_max_m)
    elif weapon.category == DcsWeaponCategory.ROCKET:
        minimum = weapon.distance_min_m
        maxima = (weapon.distance_max_m,)
    else:
        return None

    valid_maxima = [value for value in maxima if value is not None and math.isfinite(value) and value > 0]
    if not valid_maxima:
        return None
    normalized_minimum = minimum if minimum is not None and math.isfinite(minimum) and minimum >= 0 else 0.0
    maximum = max(valid_maxima)
    if maximum < normalized_minimum:
        return None
    return float(normalized_minimum), float(maximum)


class WeaponRangeRegistry:
    """Resolve manual, descriptor-derived, and fallback task range profiles."""

    def __init__(
        self,
        profiles: Iterable[WeaponRangeProfile] = MANUAL_WEAPON_RANGE_PROFILES,
        role_fallbacks: Iterable[WeaponRangeFallback] = ROLE_RANGE_FALLBACKS,
        fallbacks: Iterable[WeaponRangeProfile] = FLAG_RANGE_FALLBACKS,
        datamine: DatamineRangeData | None = DEFAULT_DATAMINE_RANGE_DATA,
    ) -> None:
        self._profiles = {_profile_key(item.dcs_type, item.weapon_flag): item for item in profiles}
        datamine_profiles: dict[tuple[str, DcsWeaponFlag], WeaponRangeProfile] = {}
        if datamine is not None:
            for item in datamine.ranges:
                key = _profile_key(item.dcs_type, item.weapon_flag)
                previous = datamine_profiles.get(key)
                datamine_profiles[key] = WeaponRangeProfile(
                    dcs_type=item.dcs_type,
                    weapon_flag=item.weapon_flag,
                    minimum_m=min(previous.minimum_m, item.minimum_m) if previous else item.minimum_m,
                    maximum_m=max(previous.maximum_m, item.maximum_m) if previous else item.maximum_m,
                    source=RangeSource.DCS_DATAMINE_WEAPON,
                    weapon_ids=tuple(sorted(set((previous.weapon_ids if previous else ()) + item.weapon_ids))),
                )
        self._datamine_profiles = datamine_profiles
        self._datamine_envelopes = {
            item.dcs_type.strip().casefold(): item
            for item in datamine.unit_envelopes
            if item.primary_weapon_flag is not None and item.maximum_m > 0
        } if datamine is not None else {}
        self._datamine_maximum_speeds_kph = {
            item.dcs_type.strip().casefold(): item.maximum_speed_kph
            for item in datamine.unit_envelopes
            if item.maximum_speed_kph is not None
        } if datamine is not None else {}
        self.datamine_metadata = datamine.metadata if datamine is not None else None
        self._role_fallbacks = {
            (WeaponRole(item.role), DcsWeaponFlag(item.weapon_flag)): item for item in role_fallbacks
        }
        self._fallbacks = {DcsWeaponFlag(item.weapon_flag): item for item in fallbacks}

    @property
    def profiles(self) -> tuple[WeaponRangeProfile, ...]:
        """Return configured exact profiles in deterministic order."""

        profiles = {**self._datamine_profiles, **self._profiles}
        return tuple(sorted(profiles.values(), key=lambda item: (item.dcs_type.casefold(), int(item.weapon_flag))))

    def profiles_for_type(self, dcs_type: str) -> tuple[WeaponRangeProfile, ...]:
        """Return known task envelopes for one DCS unit type."""

        normalized = dcs_type.strip().casefold()
        profiles = {
            (profile.weapon_flag, profile.minimum_m, profile.maximum_m, profile.source): profile
            for profile in self.profiles
            if profile.dcs_type.strip().casefold() == normalized
        }
        envelope = self._datamine_envelopes.get(normalized)
        if envelope is not None and envelope.primary_weapon_flag is not None:
            profile = WeaponRangeProfile(
                dcs_type=envelope.dcs_type,
                weapon_flag=envelope.primary_weapon_flag,
                minimum_m=envelope.minimum_m,
                maximum_m=envelope.maximum_m,
                source=RangeSource.DCS_DATAMINE_UNIT,
            )
            key = (profile.weapon_flag, profile.minimum_m, profile.maximum_m, profile.source)
            profiles.setdefault(key, profile)
        return tuple(
            sorted(
                profiles.values(),
                key=lambda item: (item.minimum_m, -item.maximum_m, int(item.weapon_flag), item.source.value),
            )
        )

    def maximum_speed_kph_for_type(self, dcs_type: str | None) -> float | None:
        """Return the DCS descriptor ``MaxSpeed`` for one ground unit type."""

        if not dcs_type:
            return None
        return self._datamine_maximum_speeds_kph.get(dcs_type.strip().casefold())

    def resolve(
        self,
        dcs_type: str,
        weapon_flag: DcsWeaponFlag | int,
        *,
        ammunition: Iterable[AmmunitionWeapon] = (),
    ) -> WeaponRangeProfile | None:
        """Resolve one task range, preferring exact manual information."""

        normalized_flag = DcsWeaponFlag(weapon_flag)
        exact = self._profiles.get(_profile_key(dcs_type, normalized_flag))
        if exact is not None:
            return exact

        datamine_exact = self._datamine_profiles.get(_profile_key(dcs_type, normalized_flag))
        if datamine_exact is not None:
            return datamine_exact

        ammunition_items = tuple(ammunition)
        ranges: list[tuple[float, float, str]] = []
        for weapon in ammunition_items:
            if normalized_flag not in {association.flag for association in weapon.weapon_flags}:
                continue
            descriptor_range = _descriptor_range(weapon)
            if descriptor_range is not None:
                ranges.append((*descriptor_range, weapon.id))
        if ranges:
            return WeaponRangeProfile(
                dcs_type=dcs_type,
                weapon_flag=normalized_flag,
                minimum_m=min(item[0] for item in ranges),
                maximum_m=max(item[1] for item in ranges),
                source=RangeSource.DCS_DESCRIPTOR,
                weapon_ids=tuple(sorted({item[2] for item in ranges})),
            )

        envelope = self._datamine_envelopes.get(dcs_type.strip().casefold())
        if envelope is not None and envelope.primary_weapon_flag == normalized_flag:
            matching_ids = tuple(
                sorted(
                    weapon.id
                    for weapon in ammunition_items
                    if normalized_flag in {association.flag for association in weapon.weapon_flags}
                )
            )
            return WeaponRangeProfile(
                dcs_type=dcs_type,
                weapon_flag=normalized_flag,
                minimum_m=envelope.minimum_m,
                maximum_m=envelope.maximum_m,
                source=RangeSource.DCS_DATAMINE_UNIT,
                weapon_ids=matching_ids,
            )

        role_ranges: list[tuple[float, float, str]] = []
        for weapon in ammunition_items:
            if normalized_flag not in {association.flag for association in weapon.weapon_flags}:
                continue
            fallback = self._role_fallbacks.get((weapon.role, normalized_flag))
            if fallback is not None:
                role_ranges.append((fallback.minimum_m, fallback.maximum_m, weapon.id))
        if role_ranges:
            return WeaponRangeProfile(
                dcs_type=dcs_type,
                weapon_flag=normalized_flag,
                minimum_m=min(item[0] for item in role_ranges),
                maximum_m=max(item[1] for item in role_ranges),
                source=RangeSource.ROLE_FALLBACK,
                weapon_ids=tuple(sorted({item[2] for item in role_ranges})),
            )

        fallback = self._fallbacks.get(normalized_flag)
        if fallback is None:
            return None
        return WeaponRangeProfile(
            dcs_type=dcs_type,
            weapon_flag=normalized_flag,
            minimum_m=fallback.minimum_m,
            maximum_m=fallback.maximum_m,
            source=RangeSource.FLAG_FALLBACK,
            weapon_ids=fallback.weapon_ids,
        )


DEFAULT_WEAPON_RANGE_REGISTRY = WeaponRangeRegistry()
