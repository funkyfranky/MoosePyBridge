"""Typed Python models for MOOSE LEGION and COHORT snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .auftrag_specs import canonical_mission_type


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


def _dict_or_empty(value: Any) -> dict[str, Any]:
    """Convert a snapshot table to a dictionary.

    :param value: Raw snapshot value.
    :returns: Dictionary copy or empty dictionary.
    """

    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _float_map(value: Any) -> dict[str, float]:
    """Convert a snapshot table to a string-float dictionary.

    :param value: Raw snapshot value.
    :returns: Mapping with string keys and float values.
    """

    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, item in value.items():
        try:
            result[str(key)] = float(item)
        except (TypeError, ValueError):
            continue
    return result


def _mission_type_keys(mission_types: list[str]) -> list[str]:
    """Normalize MOOSE mission type names for robust Python-side lookup.

    :param mission_types: MOOSE mission type names as received from DCS.
    :returns: Canonical ``AUFTRAG.Type`` keys.
    """

    keys: list[str] = []
    seen: set[str] = set()
    for mission_type in mission_types:
        key = canonical_mission_type(mission_type)
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def _mission_performance_keys(mission_performance: dict[str, float]) -> dict[str, float]:
    """Normalize mission performance keys for robust Python-side lookup.

    :param mission_performance: Mission performance keyed by original MOOSE mission type names.
    :returns: Mission performance keyed by canonical ``AUFTRAG.Type`` keys.
    """

    return {canonical_mission_type(key): value for key, value in mission_performance.items() if canonical_mission_type(key)}


def _payloads_by_mission_keys(payloads_by_mission: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize payload availability keys for robust Python-side lookup.

    :param payloads_by_mission: Payload availability keyed by original MOOSE mission type names.
    :returns: Payload availability keyed by canonical ``AUFTRAG.Type`` keys.
    """

    result: dict[str, dict[str, Any]] = {}
    for key, value in payloads_by_mission.items():
        mission_key = canonical_mission_type(key)
        if not mission_key or not isinstance(value, dict):
            continue
        result[mission_key] = value
    return result


def _performer_categories(payload: dict[str, Any], is_air: bool, is_ground: bool, is_naval: bool) -> list[str]:
    """Infer canonical performer categories for a COHORT snapshot.

    :param payload: Raw COHORT payload.
    :param is_air: Whether the COHORT is an air COHORT.
    :param is_ground: Whether the COHORT is a ground COHORT.
    :param is_naval: Whether the COHORT is a naval COHORT.
    :returns: Canonical performer categories.
    """

    explicit = _string_list(payload.get("performer_categories"))
    if explicit:
        return [category.strip().upper() for category in explicit if category.strip()]

    if is_air:
        return ["AIR"]
    if is_ground:
        return ["GROUND"]
    if is_naval:
        return ["NAVAL"]
    return []


@dataclass(slots=True, frozen=True)
class CohortSummary:
    """Lightweight COHORT reference embedded in a LEGION snapshot."""

    object_id: str
    name: str
    category: str | None = None
    class_name: str | None = None
    is_air: bool = False
    is_ground: bool = False
    is_naval: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CohortSummary":
        """Create a cohort summary from a raw payload.

        :param payload: Raw cohort summary payload.
        :returns: Typed cohort summary.
        """

        return cls(
            object_id=str(payload.get("object_id", "")),
            name=str(payload.get("name", "")),
            category=_optional_str(payload.get("category")),
            class_name=_optional_str(payload.get("class_name")),
            is_air=_bool_or_false(payload.get("is_air")),
            is_ground=_bool_or_false(payload.get("is_ground")),
            is_naval=_bool_or_false(payload.get("is_naval")),
            raw=payload,
        )


@dataclass(slots=True, frozen=True)
class Cohort:
    """Typed COHORT snapshot for SQUADRON, PLATOON and FLOTILLA objects."""

    object_id: str
    dcs_name: str
    object_type: str
    category: str | None = None
    class_name: str | None = None
    source: str | None = None
    name: str | None = None
    legion_id: str | None = None
    legion_name: str | None = None
    unit_type: str | None = None
    is_air: bool = False
    is_ground: bool = False
    is_naval: bool = False
    performer_categories: list[str] = field(default_factory=list)
    mission_types: list[str] = field(default_factory=list)
    mission_type_keys: list[str] = field(default_factory=list)
    mission_performance: dict[str, float] = field(default_factory=dict)
    mission_performance_keys: dict[str, float] = field(default_factory=dict)
    payloads_by_mission: dict[str, Any] = field(default_factory=dict)
    payloads_by_mission_keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    asset_count: int | None = None
    stock_asset_count: int | None = None
    spawned_asset_count: int | None = None
    opsgroup_count: int | None = None
    opsgroup_ids: list[str] = field(default_factory=list)
    x: float | None = None
    y: float | None = None
    z: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def mission_performance_for(self, mission_type: str) -> float | None:
        """Return mission performance for a mission type.

        :param mission_type: Mission type such as ``BAI`` or ``Bombing``.
        :returns: Performance value, or ``None`` when not present.
        """

        return self.mission_performance_keys.get(canonical_mission_type(mission_type))

    def payload_info_for(self, mission_type: str) -> dict[str, Any] | None:
        """Return payload availability for a mission type.

        :param mission_type: Mission type such as ``BAI`` or ``Bombing``.
        :returns: Payload availability dictionary or ``None``.
        """

        return self.payloads_by_mission_keys.get(canonical_mission_type(mission_type))

    def payload_performance_for(self, mission_type: str) -> float | None:
        """Return best payload performance for a mission type.

        :param mission_type: Mission type such as ``BAI`` or ``Bombing``.
        :returns: Best payload performance or ``None``.
        """

        payload_info = self.payload_info_for(mission_type)
        if not payload_info:
            return None
        value = payload_info.get("best_performance")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def has_payload_for(self, mission_type: str) -> bool | None:
        """Return whether payload availability is positive for a mission type.

        :param mission_type: Mission type such as ``BAI`` or ``Bombing``.
        :returns: ``True`` or ``False`` when payload information is known, otherwise ``None``.
        """

        payload_info = self.payload_info_for(mission_type)
        if payload_info is None:
            return None
        available_count = _optional_int(payload_info.get("available_count")) or 0
        total_available = _optional_int(payload_info.get("total_available")) or 0
        unlimited_count = _optional_int(payload_info.get("unlimited_count")) or 0
        return available_count > 0 and (total_available > 0 or unlimited_count > 0)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Cohort":
        """Create a COHORT model from a raw payload.

        :param payload: Raw COHORT snapshot payload.
        :returns: Typed COHORT object.
        """

        mission_types = _string_list(payload.get("mission_types"))
        mission_performance = _float_map(payload.get("mission_performance"))
        payloads_by_mission = _dict_or_empty(payload.get("payloads_by_mission"))
        is_air = _bool_or_false(payload.get("is_air"))
        is_ground = _bool_or_false(payload.get("is_ground"))
        is_naval = _bool_or_false(payload.get("is_naval"))
        return cls(
            object_id=str(payload.get("object_id", "")),
            dcs_name=str(payload.get("dcs_name", "")),
            object_type=str(payload.get("object_type", "COHORT")),
            category=_optional_str(payload.get("category")),
            class_name=_optional_str(payload.get("class_name")),
            source=_optional_str(payload.get("source")),
            name=_optional_str(payload.get("name")),
            legion_id=_optional_str(payload.get("legion_id")),
            legion_name=_optional_str(payload.get("legion_name")),
            unit_type=_optional_str(payload.get("unit_type")),
            is_air=is_air,
            is_ground=is_ground,
            is_naval=is_naval,
            performer_categories=_performer_categories(payload, is_air, is_ground, is_naval),
            mission_types=mission_types,
            mission_type_keys=_mission_type_keys(mission_types),
            mission_performance=mission_performance,
            mission_performance_keys=_mission_performance_keys(mission_performance),
            payloads_by_mission=payloads_by_mission,
            payloads_by_mission_keys=_payloads_by_mission_keys(payloads_by_mission),
            asset_count=_optional_int(payload.get("asset_count")),
            stock_asset_count=_optional_int(payload.get("stock_asset_count")),
            spawned_asset_count=_optional_int(payload.get("spawned_asset_count")),
            opsgroup_count=_optional_int(payload.get("opsgroup_count")),
            opsgroup_ids=_string_list(payload.get("opsgroup_ids")),
            x=_optional_float(payload.get("x")),
            y=_optional_float(payload.get("y")),
            z=_optional_float(payload.get("z")),
            raw=payload,
        )


@dataclass(slots=True, frozen=True)
class Legion:
    """Typed LEGION snapshot for AIRWING, BRIGADE and FLEET objects."""

    object_id: str
    dcs_name: str
    object_type: str
    category: str | None = None
    class_name: str | None = None
    source: str | None = None
    name: str | None = None
    alias: str | None = None
    state: str | None = None
    coalition: str | None = None
    coalition_name: str | None = None
    airbase_name: str | None = None
    cohort_ids: list[str] = field(default_factory=list)
    cohorts: list[CohortSummary] = field(default_factory=list)
    n_cohorts: int | None = None
    auftrag_queue_ids: list[str] = field(default_factory=list)
    x: float | None = None
    y: float | None = None
    z: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Legion":
        """Create a LEGION model from a raw payload.

        :param payload: Raw LEGION snapshot payload.
        :returns: Typed LEGION object.
        """

        raw_cohorts = payload.get("cohorts")
        cohorts = [CohortSummary.from_payload(item) for item in raw_cohorts] if isinstance(raw_cohorts, list) else []
        return cls(
            object_id=str(payload.get("object_id", "")),
            dcs_name=str(payload.get("dcs_name", "")),
            object_type=str(payload.get("object_type", "LEGION")),
            category=_optional_str(payload.get("category")),
            class_name=_optional_str(payload.get("class_name")),
            source=_optional_str(payload.get("source")),
            name=_optional_str(payload.get("name")),
            alias=_optional_str(payload.get("alias")),
            state=_optional_str(payload.get("state")),
            coalition=_optional_str(payload.get("coalition")),
            coalition_name=_optional_str(payload.get("coalition_name")),
            airbase_name=_optional_str(payload.get("airbase_name")),
            cohort_ids=_string_list(payload.get("cohort_ids")),
            cohorts=cohorts,
            n_cohorts=_optional_int(payload.get("n_cohorts")),
            auftrag_queue_ids=_string_list(payload.get("auftrag_queue_ids")),
            x=_optional_float(payload.get("x")),
            y=_optional_float(payload.get("y")),
            z=_optional_float(payload.get("z")),
            raw=payload,
        )
