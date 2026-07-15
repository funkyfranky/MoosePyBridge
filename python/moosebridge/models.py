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
class TargetObjectSnapshot:
    """Typed TARGET object entry from an AUFTRAG target snapshot."""

    id: int | None = None
    type: str | None = None
    name: str | None = None
    object_id: str | None = None
    status: str | None = None
    n0: int | None = None
    n_dead: int | None = None
    n_destroyed: int | None = None
    life: float | None = None
    life0: float | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TargetObjectSnapshot":
        """Create a typed target object from a raw payload.

        :param payload: Raw target object payload.
        :returns: Typed target object.
        """

        return cls(
            id=_optional_int(payload.get("id")),
            type=_optional_str(payload.get("type")),
            name=_optional_str(payload.get("name")),
            object_id=_optional_str(payload.get("object_id")),
            status=_optional_str(payload.get("status")),
            n0=_optional_int(payload.get("n0")),
            n_dead=_optional_int(payload.get("n_dead")),
            n_destroyed=_optional_int(payload.get("n_destroyed")),
            life=_optional_float(payload.get("life")),
            life0=_optional_float(payload.get("life0")),
            x=_optional_float(payload.get("x")),
            y=_optional_float(payload.get("y")),
            z=_optional_float(payload.get("z")),
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
            raw=payload,
        )


@dataclass(slots=True, frozen=True)
class TargetSnapshot:
    """Typed TARGET snapshot embedded in an AUFTRAG snapshot."""

    object_id: str | None = None
    name: str | None = None
    state: str | None = None
    category: str | None = None
    heading: float | None = None
    life: float | None = None
    life0: float | None = None
    damage: float | None = None
    threat_level_max: float | None = None
    n0: int | None = None
    n_targets0: int | None = None
    n_destroyed: int | None = None
    n_dead: int | None = None
    is_destroyed: bool = False
    objects: list[TargetObjectSnapshot] = field(default_factory=list)
    x: float | None = None
    y: float | None = None
    z: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TargetSnapshot":
        """Create a typed target snapshot from a raw payload.

        :param payload: Raw target payload.
        :returns: Typed target snapshot.
        """

        raw_objects = payload.get("objects")
        objects = [TargetObjectSnapshot.from_payload(item) for item in raw_objects] if isinstance(raw_objects, list) else []
        return cls(
            object_id=_optional_str(payload.get("object_id")),
            name=_optional_str(payload.get("name")),
            state=_optional_str(payload.get("state")),
            category=_optional_str(payload.get("category")),
            heading=_optional_float(payload.get("heading")),
            life=_optional_float(payload.get("life")),
            life0=_optional_float(payload.get("life0")),
            damage=_optional_float(payload.get("damage")),
            threat_level_max=_optional_float(payload.get("threat_level_max")),
            n0=_optional_int(payload.get("n0")),
            n_targets0=_optional_int(payload.get("n_targets0")),
            n_destroyed=_optional_int(payload.get("n_destroyed")),
            n_dead=_optional_int(payload.get("n_dead")),
            is_destroyed=_bool_or_false(payload.get("is_destroyed")),
            objects=objects,
            x=_optional_float(payload.get("x")),
            y=_optional_float(payload.get("y")),
            z=_optional_float(payload.get("z")),
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
            raw=payload,
        )


@dataclass(slots=True, frozen=True)
class Intel(MooseSnapshotObject):
    """Typed INTEL snapshot."""

    alias: str | None = None
    coalition: str | None = None
    state: str | None = None
    is_running: bool = False
    cluster_analysis: bool = False
    cluster_markers: bool = False
    cluster_arrows: bool = False
    cluster_radius_m: float | None = None
    detect_statics: bool = False
    detect_accoustic: bool = False
    detect_accoustic_radius_m: float | None = None
    doppler_radar: bool = False
    contact_count: int | None = None
    cluster_count: int | None = None
    agent_count: int | None = None
    alive_agent_count: int | None = None
    agent_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Intel":
        """Create an INTEL model from a raw payload."""

        return cls(
            object_id=str(payload.get("object_id", "")),
            dcs_name=str(payload.get("dcs_name", "")),
            object_type=str(payload.get("object_type", "INTEL")),
            category=_optional_str(payload.get("category")),
            source=_optional_str(payload.get("source")),
            raw=payload,
            alias=_optional_str(payload.get("alias")),
            coalition=_optional_str(payload.get("coalition")),
            state=_optional_str(payload.get("state")),
            is_running=_bool_or_false(payload.get("is_running")),
            cluster_analysis=_bool_or_false(payload.get("cluster_analysis")),
            cluster_markers=_bool_or_false(payload.get("cluster_markers")),
            cluster_arrows=_bool_or_false(payload.get("cluster_arrows")),
            cluster_radius_m=_optional_float(payload.get("cluster_radius_m")),
            detect_statics=_bool_or_false(payload.get("detect_statics")),
            detect_accoustic=_bool_or_false(payload.get("detect_accoustic")),
            detect_accoustic_radius_m=_optional_float(payload.get("detect_accoustic_radius_m")),
            doppler_radar=_bool_or_false(payload.get("doppler_radar")),
            contact_count=_optional_int(payload.get("contact_count")),
            cluster_count=_optional_int(payload.get("cluster_count")),
            agent_count=_optional_int(payload.get("agent_count")),
            alive_agent_count=_optional_int(payload.get("alive_agent_count")),
            agent_ids=_string_list(payload.get("agent_ids")),
        )


@dataclass(slots=True, frozen=True)
class IntelContact(MooseSnapshotObject):
    """Typed INTEL contact snapshot."""

    intel_id: str | None = None
    target_object_id: str | None = None
    typename: str | None = None
    attribute: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    threat_level: float | None = None
    detected_time: float | None = None
    recce: str | None = None
    contact_type: str | None = None
    speed_mps: float | None = None
    velocity: dict[str, Any] | None = None
    is_ground: bool = False
    is_ship: bool = False
    is_static: bool = False
    platform: str | None = None
    heading: float | None = None
    maneuvering: bool = False
    altitude_m: float | None = None
    rcs: float | None = None
    mission_id: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    latitude: float | None = None
    longitude: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "IntelContact":
        """Create an INTEL contact model from a raw payload."""

        velocity = payload.get("velocity") if isinstance(payload.get("velocity"), dict) else None
        return cls(
            object_id=str(payload.get("object_id", "")),
            dcs_name=str(payload.get("dcs_name", "")),
            object_type=str(payload.get("object_type", "INTELCONTACT")),
            category=_optional_str(payload.get("category")),
            source=_optional_str(payload.get("source")),
            raw=payload,
            intel_id=_optional_str(payload.get("intel_id")),
            target_object_id=_optional_str(payload.get("target_object_id")),
            typename=_optional_str(payload.get("typename")),
            attribute=_optional_str(payload.get("attribute")),
            category_id=_optional_int(payload.get("category_id")),
            category_name=_optional_str(payload.get("category_name")),
            threat_level=_optional_float(payload.get("threat_level")),
            detected_time=_optional_float(payload.get("detected_time")),
            recce=_optional_str(payload.get("recce")),
            contact_type=_optional_str(payload.get("contact_type")),
            speed_mps=_optional_float(payload.get("speed_mps")),
            velocity=velocity,
            is_ground=_bool_or_false(payload.get("is_ground")),
            is_ship=_bool_or_false(payload.get("is_ship")),
            is_static=_bool_or_false(payload.get("is_static")),
            platform=_optional_str(payload.get("platform")),
            heading=_optional_float(payload.get("heading")),
            maneuvering=_bool_or_false(payload.get("maneuvering")),
            altitude_m=_optional_float(payload.get("altitude_m")),
            rcs=_optional_float(payload.get("rcs")),
            mission_id=_optional_str(payload.get("mission_id")),
            x=_optional_float(payload.get("x")),
            y=_optional_float(payload.get("y")),
            z=_optional_float(payload.get("z")),
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
        )


@dataclass(slots=True, frozen=True)
class IntelCluster(MooseSnapshotObject):
    """Typed INTEL cluster snapshot."""

    intel_id: str | None = None
    index: int | None = None
    size: int | None = None
    contact_ids: list[str] = field(default_factory=list)
    threat_level_max: float | None = None
    threat_level_sum: float | None = None
    threat_level_avg: float | None = None
    contact_type: str | None = None
    altitude_m: float | None = None
    mission_id: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    latitude: float | None = None
    longitude: float | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "IntelCluster":
        """Create an INTEL cluster model from a raw payload."""

        return cls(
            object_id=str(payload.get("object_id", "")),
            dcs_name=str(payload.get("dcs_name", "")),
            object_type=str(payload.get("object_type", "INTELCLUSTER")),
            category=_optional_str(payload.get("category")),
            source=_optional_str(payload.get("source")),
            raw=payload,
            intel_id=_optional_str(payload.get("intel_id")),
            index=_optional_int(payload.get("index")),
            size=_optional_int(payload.get("size")),
            contact_ids=_string_list(payload.get("contact_ids")),
            threat_level_max=_optional_float(payload.get("threat_level_max")),
            threat_level_sum=_optional_float(payload.get("threat_level_sum")),
            threat_level_avg=_optional_float(payload.get("threat_level_avg")),
            contact_type=_optional_str(payload.get("contact_type")),
            altitude_m=_optional_float(payload.get("altitude_m")),
            mission_id=_optional_str(payload.get("mission_id")),
            x=_optional_float(payload.get("x")),
            y=_optional_float(payload.get("y")),
            z=_optional_float(payload.get("z")),
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
        )


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
    latitude: float | None = None
    longitude: float | None = None

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
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
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
    latitude: float | None = None
    longitude: float | None = None

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
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
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
    legion_names: list[str] = field(default_factory=list)
    target: TargetSnapshot | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Auftrag":
        """Create an AUFTRAG model from a raw payload.

        :param payload: Raw AUFTRAG snapshot payload.
        :returns: Typed AUFTRAG object.
        """

        raw_target = payload.get("target")
        target = TargetSnapshot.from_payload(raw_target) if isinstance(raw_target, dict) else None
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
            legion_names=_string_list(payload.get("legion_names")),
            target=target,
        )
