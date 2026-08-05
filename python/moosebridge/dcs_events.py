"""Typed normalized events originating from the DCS world event system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class DestroyedObjectEvent:
    """One DCS object reported destroyed by UnitLost or Dead."""

    object_id: str
    object_type: str
    dcs_name: str
    group_id: str | None = None
    coalition: str | None = None
    category: str | None = None
    dcs_type: str | None = None
    mission_time: float | None = None
    dcs_event_time: float | None = None
    dcs_event_name: str | None = None
    object: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    group: dict[str, Any] | None = field(default=None, repr=False, compare=False)
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_message(cls, message: dict[str, Any]) -> "DestroyedObjectEvent":
        """Build a typed event from a normalized bridge event message."""

        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        item = payload.get("object") if isinstance(payload.get("object"), dict) else {}
        object_id = str(payload.get("object_id") or item.get("object_id") or "")
        if not object_id:
            raise ValueError("object.destroyed event has no object_id")
        object_type = str(item.get("object_type") or object_id.partition(":")[0] or "OBJECT").upper()
        group = payload.get("group") if isinstance(payload.get("group"), dict) else None
        return cls(
            object_id=object_id,
            object_type=object_type,
            dcs_name=str(item.get("dcs_name") or object_id.partition(":")[2]),
            group_id=_optional_text(payload.get("group_id") or item.get("group_id")),
            coalition=_optional_text(item.get("coalition")),
            category=_optional_text(item.get("category")),
            dcs_type=_optional_text(item.get("dcs_type")),
            mission_time=_optional_float(message.get("mission_time")),
            dcs_event_time=_optional_float(payload.get("dcs_event_time")),
            dcs_event_name=_optional_text(payload.get("dcs_event_name")),
            object=item,
            group=group,
            raw=message,
        )


@dataclass(slots=True, frozen=True)
class KillEvent:
    """One DCS Kill event with explicit attacker and target attribution."""

    killer_object_id: str
    target_object_id: str
    killer_coalition: str | None = None
    target_coalition: str | None = None
    killer_group_id: str | None = None
    target_group_id: str | None = None
    killer_type: str | None = None
    target_type: str | None = None
    weapon_name: str | None = None
    mission_time: float | None = None
    dcs_event_time: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_message(cls, message: dict[str, Any]) -> "KillEvent":
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        killer_id = str(payload.get("killer_object_id") or "")
        target_id = str(payload.get("target_object_id") or "")
        if not killer_id or not target_id:
            raise ValueError("combat.kill event requires killer and target object ids")
        return cls(
            killer_object_id=killer_id,
            target_object_id=target_id,
            killer_coalition=_optional_text(payload.get("killer_coalition")),
            target_coalition=_optional_text(payload.get("target_coalition")),
            killer_group_id=_optional_text(payload.get("killer_group_id")),
            target_group_id=_optional_text(payload.get("target_group_id")),
            killer_type=_optional_text(payload.get("killer_type")),
            target_type=_optional_text(payload.get("target_type")),
            weapon_name=_optional_text(payload.get("weapon_name")),
            mission_time=_optional_float(message.get("mission_time")),
            dcs_event_time=_optional_float(payload.get("dcs_event_time")),
            raw=message,
        )


def _optional_text(value: Any) -> str | None:
    return str(value) if value is not None and value != "" else None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
