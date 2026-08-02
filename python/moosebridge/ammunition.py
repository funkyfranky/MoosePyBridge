"""Typed ammunition snapshots and observed-initial-count tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


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


@dataclass(slots=True, frozen=True)
class AmmunitionWeapon:
    """One current and initially observed weapon-ammunition entry."""

    id: str
    current_count: int
    initial_count: int
    fraction: float | None
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
    def from_payload(cls, payload: dict[str, Any]) -> "AmmunitionWeapon":
        current = max(0, _int(payload.get("count")) or 0)
        initial = max(0, _int(payload.get("initial_count")) or 0)
        fraction = current / initial if initial > 0 else None
        return cls(
            id=str(payload.get("id") or payload.get("type_name") or "unknown"),
            current_count=current,
            initial_count=initial,
            fraction=min(1.0, max(0.0, fraction)) if fraction is not None else None,
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
        return cls(
            unit_id=str(payload.get("unit_id") or payload.get("object_id") or ""),
            unit_name=str(payload.get("unit_name") or payload.get("dcs_name") or ""),
            group_id=_string(payload.get("group_id")),
            group_name=_string(payload.get("group_name")),
            dcs_type=_string(payload.get("dcs_type")),
            category=_string(payload.get("category")),
            attributes=tuple(sorted(str(value) for value in attributes)),
            life=_float(payload.get("life")),
            life0=_float(payload.get("life0")),
            weapons=tuple(AmmunitionWeapon.from_payload(item) for item in raw_weapons if isinstance(item, dict)),
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
