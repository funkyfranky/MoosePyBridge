"""Typed Python models for MOOSE LEGION snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
