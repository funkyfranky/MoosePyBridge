"""Stable outcome models for evaluated MOOSE AUFTRAG objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class AuftragOutcome:
    """Stable Python representation of an evaluated MOOSE AUFTRAG.

    ``summary.success`` is the authoritative mission result for the first API
    version. Additional tactical classifications can be layered on later without
    changing this core contract.

    :param auftrag_id: Stable AUFTRAG object id, for example ``AUFTRAG:1``.
    :param mission_type: MOOSE AUFTRAG type, for example ``BAI``.
    :param status: Final lifecycle or result status reported by MOOSE.
    :param evaluated: Whether ``AUFTRAG.summary`` was present.
    :param success: Authoritative ``AUFTRAG.summary.success`` value.
    :param damage: Target damage in percent.
    :param n_targets_initial: Initial target count.
    :param n_targets_final: Final target count.
    :param n_destroyed: Number of destroyed targets.
    :param n_kills: Number of kills from assigned groups.
    :param n_elements: Number of assigned elements.
    :param n_casualties: Number of own casualties.
    :param target_life: Remaining target life points.
    :param category: Target category.
    :param raw_snapshot: Raw AUFTRAG snapshot used to build the outcome.
    :param raw_summary: Raw MOOSE ``AUFTRAG.summary`` table.
    """

    auftrag_id: str
    mission_type: str | None
    status: str | None
    evaluated: bool
    success: bool | None
    damage: float | None
    n_targets_initial: int | None
    n_targets_final: int | None
    n_destroyed: int | None
    n_kills: int | None
    n_elements: int | None
    n_casualties: int | None
    target_life: float | None
    category: str | None
    raw_snapshot: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    raw_summary: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "AuftragOutcome":
        """Create an outcome from an evaluated AUFTRAG snapshot.

        :param snapshot: Raw AUFTRAG snapshot containing ``summary``.
        :returns: Stable outcome model.
        :raises ValueError: If the snapshot has no summary.
        """

        summary = snapshot.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("AUFTRAG snapshot is not evaluated yet: missing summary")

        return cls(
            auftrag_id=str(snapshot.get("object_id", "")),
            mission_type=_optional_str(snapshot.get("type")),
            status=_optional_str(snapshot.get("status")),
            evaluated=True,
            success=_optional_bool(summary.get("success")),
            damage=_optional_float(summary.get("damage")),
            n_targets_initial=_optional_int(summary.get("Ntargets0")),
            n_targets_final=_optional_int(summary.get("Ntargets")),
            n_destroyed=_optional_int(summary.get("Ndestroyed")),
            n_kills=_optional_int(summary.get("Nkills")),
            n_elements=_optional_int(summary.get("Nelements")),
            n_casualties=_optional_int(summary.get("Ncasualties")),
            target_life=_optional_float(summary.get("targetLife")),
            category=_optional_str(summary.get("category")),
            raw_snapshot=snapshot,
            raw_summary=summary,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation.

        :returns: Outcome dictionary.
        """

        return {
            "auftrag_id": self.auftrag_id,
            "mission_type": self.mission_type,
            "status": self.status,
            "evaluated": self.evaluated,
            "success": self.success,
            "damage": self.damage,
            "n_targets_initial": self.n_targets_initial,
            "n_targets_final": self.n_targets_final,
            "n_destroyed": self.n_destroyed,
            "n_kills": self.n_kills,
            "n_elements": self.n_elements,
            "n_casualties": self.n_casualties,
            "target_life": self.target_life,
            "category": self.category,
        }


def _optional_str(value: Any) -> str | None:
    """Convert a value to an optional string."""

    if value is None:
        return None
    return str(value)


def _optional_bool(value: Any) -> bool | None:
    """Convert a value to an optional boolean."""

    if value is None:
        return None
    return bool(value)


def _optional_float(value: Any) -> float | None:
    """Convert a value to an optional float."""

    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    """Convert a value to an optional integer."""

    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
