"""Typed Python models for semantic MOOSE Bridge snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar


T = TypeVar("T")


def _optional_str(value: Any) -> str | None:
    """Convert a snapshot value to an optional string.

    :param value: Raw snapshot value.
    :returns: ``None`` for absent values, otherwise ``str(value)``.
    """

    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    """Convert a snapshot value to an optional float.

    :param value: Raw snapshot value.
    :returns: Parsed float or ``None``.
    """

    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    """Convert a snapshot value to an optional integer.

    :param value: Raw snapshot value.
    :returns: Parsed integer or ``None``.
    """

    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_or_false(value: Any) -> bool:
    """Convert a snapshot value to a boolean.

    :param value: Raw snapshot value.
    :returns: Boolean interpretation.
    """

    return bool(value)


def _string_list(value: Any) -> list[str]:
    """Convert a snapshot list value to a list of strings.

    :param value: Raw snapshot value.
    :returns: String list.
    """

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


@dataclass(slots=True, frozen=True)
class MooseSnapshotObject:
    """Common identity fields shared by typed snapshot objects."""

    object_id: str
    dcs_name: str
    object_type: str
    category: str | None = None
    source: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls: type[T], payload: dict[str, Any]) -> T:
        """Create a typed object from a raw snapshot payload.

        :param payload: Raw snapshot payload.
        :returns: Typed snapshot object.
        """

        raise NotImplementedError


@dataclass(slots=True, frozen=True)
class OpsZone(MooseSnapshotObject):
    """Typed OPSZONE snapshot."""

    name: str | None = None
    state: str | None = None
    zone_name: str | None = None
    zone_type: str | None = None
    zone_radius: float | None = None
    owner_current_name: str | None = None
    owner_previous_name: str | None = None
    is_contested: bool = False
    n_red: int | None = None
    n_blue: int | None = None
    n_neutral: int | None = None
    threat_red: int | None = None
    threat_blue: int | None = None
    threat_neutral: int | None = None
    airbase_name: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "OpsZone":
        """Create an OPSZONE model from a raw payload.

        :param payload: Raw OPSZONE snapshot payload.
        :returns: Typed OPSZONE object.
        """

        return cls(
            object_id=str(payload.get("object_id", "")),
            dcs_name=str(payload.get("dcs_name", "")),
            object_type=str(payload.get("object_type", "OPSZONE")),
            category=_optional_str(payload.get("category")),
            source=_optional_str(payload.get("source")),
            raw=payload,
            name=_optional_str(payload.get("name")),
            state=_optional_str(payload.get("state")),
            zone_name=_optional_str(payload.get("zone_name")),
            zone_type=_optional_str(payload.get("zone_type")),
            zone_radius=_optional_float(payload.get("zone_radius")),
            owner_current_name=_optional_str(payload.get("owner_current_name")),
            owner_previous_name=_optional_str(payload.get("owner_previous_name")),
            is_contested=_bool_or_false(payload.get("is_contested")),
            n_red=_optional_int(payload.get("n_red")),
            n_blue=_optional_int(payload.get("n_blue")),
            n_neutral=_optional_int(payload.get("n_neutral")),
            threat_red=_optional_int(payload.get("threat_red")),
            threat_blue=_optional_int(payload.get("threat_blue")),
            threat_neutral=_optional_int(payload.get("threat_neutral")),
            airbase_name=_optional_str(payload.get("airbase_name")),
            x=_optional_float(payload.get("x")),
            y=_optional_float(payload.get("y")),
            z=_optional_float(payload.get("z")),
        )


@dataclass(slots=True, frozen=True)
class OpsGroup(MooseSnapshotObject):
    """Typed OPSGROUP snapshot."""

    name: str | None = None
    group_name: str | None = None
    class_name: str | None = None
    state: str | None = None
    coalition: str | None = None
    alive: bool = False
    active: bool = False
    is_ai: bool = False
    is_late_activated: bool = False
    is_uncontrolled: bool = False
    is_dead: bool = False
    is_destroyed: bool = False
    current_wp: int | None = None
    speed_cruise: float | None = None
    speed_wp: float | None = None
    heading: float | None = None
    travel_dist: float | None = None
    travel_time: float | None = None
    homebase_name: str | None = None
    destbase_name: str | None = None
    currbase_name: str | None = None
    auftrag_current_id: str | None = None
    auftrag_queue_ids: list[str] = field(default_factory=list)
    detected_group_ids: list[str] = field(default_factory=list)
    x: float | None = None
    y: float | None = None
    z: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "OpsGroup":
        """Create an OPSGROUP model from a raw payload.

        :param payload: Raw OPSGROUP snapshot payload.
        :returns: Typed OPSGROUP object.
        """

        return cls(
            object_id=str(payload.get("object_id", "")),
            dcs_name=str(payload.get("dcs_name", "")),
            object_type=str(payload.get("object_type", "OPSGROUP")),
            category=_optional_str(payload.get("category")),
            source=_optional_str(payload.get("source")),
            raw=payload,
            name=_optional_str(payload.get("name")),
            group_name=_optional_str(payload.get("group_name")),
            class_name=_optional_str(payload.get("class_name")),
            state=_optional_str(payload.get("state")),
            coalition=_optional_str(payload.get("coalition")),
            alive=_bool_or_false(payload.get("alive")),
            active=_bool_or_false(payload.get("active")),
            is_ai=_bool_or_false(payload.get("is_ai")),
            is_late_activated=_bool_or_false(payload.get("is_late_activated")),
            is_uncontrolled=_bool_or_false(payload.get("is_uncontrolled")),
            is_dead=_bool_or_false(payload.get("is_dead")),
            is_destroyed=_bool_or_false(payload.get("is_destroyed")),
            current_wp=_optional_int(payload.get("current_wp")),
            speed_cruise=_optional_float(payload.get("speed_cruise")),
            speed_wp=_optional_float(payload.get("speed_wp")),
            heading=_optional_float(payload.get("heading")),
            travel_dist=_optional_float(payload.get("travel_dist")),
            travel_time=_optional_float(payload.get("travel_time")),
            homebase_name=_optional_str(payload.get("homebase_name")),
            destbase_name=_optional_str(payload.get("destbase_name")),
            currbase_name=_optional_str(payload.get("currbase_name")),
            auftrag_current_id=_optional_str(payload.get("auftrag_current_id")),
            auftrag_queue_ids=_string_list(payload.get("auftrag_queue_ids")),
            detected_group_ids=_string_list(payload.get("detected_group_ids")),
            x=_optional_float(payload.get("x")),
            y=_optional_float(payload.get("y")),
            z=_optional_float(payload.get("z")),
        )


@dataclass(slots=True, frozen=True)
class Auftrag(MooseSnapshotObject):
    """Typed AUFTRAG snapshot."""

    auftragsnummer: int | None = None
    name: str | None = None
    type: str | None = None
    status: str | None = None
    prio: int | None = None
    urgent: bool = False
    importance: int | None = None
    t_start: float | None = None
    t_stop: float | None = None
    duration: float | None = None
    duration_exe: float | None = None
    t_started: float | None = None
    t_executing: float | None = None
    t_push: float | None = None
    t_over: float | None = None
    n_assigned: int | None = None
    n_elements: int | None = None
    n_dead: int | None = None
    n_kills: int | None = None
    n_casualties: int | None = None
    mission_task: str | None = None
    mission_altitude: float | None = None
    mission_speed: float | None = None
    mission_range: float | None = None
    chief_name: str | None = None
    commander_name: str | None = None
    operation_name: str | None = None
    assigned_group_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Auftrag":
        """Create an AUFTRAG model from a raw payload.

        :param payload: Raw AUFTRAG snapshot payload.
        :returns: Typed AUFTRAG object.
        """

        return cls(
            object_id=str(payload.get("object_id", "")),
            dcs_name=str(payload.get("dcs_name", "")),
            object_type=str(payload.get("object_type", "AUFTRAG")),
            category=_optional_str(payload.get("category")),
            source=_optional_str(payload.get("source")),
            raw=payload,
            auftragsnummer=_optional_int(payload.get("auftragsnummer")),
            name=_optional_str(payload.get("name")),
            type=_optional_str(payload.get("type")),
            status=_optional_str(payload.get("status")),
            prio=_optional_int(payload.get("prio")),
            urgent=_bool_or_false(payload.get("urgent")),
            importance=_optional_int(payload.get("importance")),
            t_start=_optional_float(payload.get("t_start")),
            t_stop=_optional_float(payload.get("t_stop")),
            duration=_optional_float(payload.get("duration")),
            duration_exe=_optional_float(payload.get("duration_exe")),
            t_started=_optional_float(payload.get("t_started")),
            t_executing=_optional_float(payload.get("t_executing")),
            t_push=_optional_float(payload.get("t_push")),
            t_over=_optional_float(payload.get("t_over")),
            n_assigned=_optional_int(payload.get("n_assigned")),
            n_elements=_optional_int(payload.get("n_elements")),
            n_dead=_optional_int(payload.get("n_dead")),
            n_kills=_optional_int(payload.get("n_kills")),
            n_casualties=_optional_int(payload.get("n_casualties")),
            mission_task=_optional_str(payload.get("mission_task")),
            mission_altitude=_optional_float(payload.get("mission_altitude")),
            mission_speed=_optional_float(payload.get("mission_speed")),
            mission_range=_optional_float(payload.get("mission_range")),
            chief_name=_optional_str(payload.get("chief_name")),
            commander_name=_optional_str(payload.get("commander_name")),
            operation_name=_optional_str(payload.get("operation_name")),
            assigned_group_ids=_string_list(payload.get("assigned_group_ids")),
        )
