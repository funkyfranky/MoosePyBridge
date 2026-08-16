"""Persistent DCS-component verification for geographic strategic sites."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 4
SCENERY_OBJECT_PREFIX = "SCENERY"


class StrategicVerificationState(str, Enum):
    """How well one geographic candidate is represented in DCS."""

    UNVERIFIED = "unverified"
    REPRESENTED = "represented"
    NOT_REPRESENTED = "not_represented"


class InfrastructureOperationalState(str, Enum):
    """Derived physical state of a verified infrastructure site."""

    UNKNOWN = "unknown"
    OPERATIONAL = "operational"
    DAMAGED = "damaged"
    DISABLED = "disabled"
    DESTROYED = "destroyed"


@dataclass(slots=True, frozen=True)
class VerifiedDcsComponent:
    """One fixed DCS scenery object selected as a target component."""

    object_id: str
    role: str = "infrastructure component"
    weight: float = 1.0

    def __post_init__(self) -> None:
        object_id = self.object_id.strip()
        role = self.role.strip()
        if not _is_scenery_object_id(object_id):
            raise ValueError("target component must use a fixed SCENERY:<id> object id")
        if not role:
            raise ValueError("component role must not be empty")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("component weight must be finite and positive")
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "role", role)

    def to_dict(self) -> dict[str, Any]:
        return {"object_id": self.object_id, "role": self.role, "weight": self.weight}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VerifiedDcsComponent":
        return cls(
            object_id=str(payload.get("object_id") or ""),
            role=str(payload.get("role") or "infrastructure component"),
            weight=float(payload.get("weight") or 1.0),
        )


@dataclass(slots=True, frozen=True)
class ObservedDcsObject:
    """One fixed DCS scenery object retained in a theater baseline."""

    object_id: str
    type_name: str = ""
    display_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    life: float | None = None
    exists: bool | None = None

    def __post_init__(self) -> None:
        object_id = self.object_id.strip()
        if not _is_scenery_object_id(object_id):
            raise ValueError("observed object must use a fixed SCENERY:<id> object id")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("observed object coordinates must contain both latitude and longitude")
        for label, value in (("latitude", self.latitude), ("longitude", self.longitude), ("life", self.life)):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"observed object {label} must be finite")
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "type_name", self.type_name.strip())
        object.__setattr__(self, "display_name", self.display_name.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "type_name": self.type_name,
            "display_name": self.display_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "life": self.life,
            "exists": self.exists,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObservedDcsObject":
        return cls(
            object_id=str(payload.get("object_id") or ""),
            type_name=str(payload.get("type_name") or ""),
            display_name=str(payload.get("display_name") or ""),
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
            life=_optional_float(payload.get("life")),
            exists=payload.get("exists") if isinstance(payload.get("exists"), bool) else None,
        )


@dataclass(slots=True, frozen=True)
class StrategicSiteVerification:
    """Theater-level scenery verification and target mapping for one source site."""

    source_id: str
    state: StrategicVerificationState = StrategicVerificationState.UNVERIFIED
    observed_objects: tuple[ObservedDcsObject, ...] = ()
    observation_complete: bool = False
    target_components: tuple[VerifiedDcsComponent, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        source_id = self.source_id.strip()
        if not source_id or ":" not in source_id:
            raise ValueError("source_id must be a stable normalized object id")
        state = _coerce_verification_state(self.state)
        observed_objects = tuple(self.observed_objects)
        observed_ids = [item.object_id for item in observed_objects]
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError("observed objects must have unique object ids")
        target_components = tuple(self.target_components)
        target_ids = [item.object_id for item in target_components]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("target components must have unique object ids")
        unknown_targets = sorted(set(target_ids).difference(observed_ids))
        if unknown_targets:
            raise ValueError(
                "target components must be selected from the observed scenery baseline: "
                + ", ".join(unknown_targets)
            )
        if state is StrategicVerificationState.REPRESENTED and not observed_objects:
            raise ValueError("represented verification requires observed scenery objects")
        if state is StrategicVerificationState.NOT_REPRESENTED and target_components:
            raise ValueError("not-represented verification cannot contain target components")
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "observed_objects", observed_objects)
        object.__setattr__(self, "target_components", target_components)
        object.__setattr__(self, "notes", self.notes.strip())

    @property
    def admitted(self) -> bool:
        """Return whether this mapping may create an automatic objective."""

        return bool(self.target_components) and self.state is StrategicVerificationState.REPRESENTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "state": self.state.value,
            "observed_objects": [item.to_dict() for item in self.observed_objects],
            "observation_complete": self.observation_complete,
            "target_components": [item.to_dict() for item in self.target_components],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategicSiteVerification":
        return cls(
            source_id=str(payload.get("source_id") or ""),
            state=_coerce_verification_state(payload.get("state")),
            observed_objects=tuple(
                ObservedDcsObject.from_dict(item)
                for item in payload.get("observed_objects") or ()
                if isinstance(item, Mapping)
            ),
            observation_complete=payload.get("observation_complete") is True,
            target_components=tuple(
                VerifiedDcsComponent.from_dict(item)
                for item in payload.get("target_components") or ()
                if isinstance(item, Mapping)
            ),
            notes=str(payload.get("notes") or ""),
        )


@dataclass(slots=True, frozen=True)
class InfrastructureObjectAssessment:
    """Current condition of one object retained in an observation baseline."""

    object_id: str
    health: float | None
    condition: str
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "health": self.health,
            "condition": self.condition,
            "source": self.source,
        }


@dataclass(slots=True, frozen=True)
class InfrastructureStateAssessment:
    """Bounded comparison of a site's observed baseline with current DCS state."""

    source_id: str
    state: InfrastructureOperationalState
    baseline_count: int
    intact_count: int
    damaged_count: int
    destroyed_count: int
    unknown_count: int
    health_min: float | None
    health_max: float | None
    complete: bool
    objects: tuple[InfrastructureObjectAssessment, ...] = ()

    @property
    def damage_min(self) -> float | None:
        return None if self.health_max is None else 1.0 - self.health_max

    @property
    def damage_max(self) -> float | None:
        return None if self.health_min is None else 1.0 - self.health_min

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "state": self.state.value,
            "baseline_count": self.baseline_count,
            "intact_count": self.intact_count,
            "damaged_count": self.damaged_count,
            "destroyed_count": self.destroyed_count,
            "unknown_count": self.unknown_count,
            "health_min": self.health_min,
            "health_max": self.health_max,
            "damage_min": self.damage_min,
            "damage_max": self.damage_max,
            "complete": self.complete,
            "objects": [item.to_dict() for item in self.objects],
        }


def assess_infrastructure_state(
    verification: StrategicSiteVerification,
    current_objects: Iterable[ObservedDcsObject],
    *,
    destroyed_object_ids: Iterable[str] = (),
    current_observation_complete: bool = False,
    disabled_health_threshold: float = 0.4,
    destroyed_health_threshold: float = 0.05,
) -> InfrastructureStateAssessment:
    """Compare current object evidence with an immutable site baseline."""

    if not 0 <= destroyed_health_threshold < disabled_health_threshold <= 1:
        raise ValueError("infrastructure health thresholds are invalid")
    current_by_id = {item.object_id: item for item in current_objects}
    destroyed_ids = {str(item) for item in destroyed_object_ids}
    assessed: list[InfrastructureObjectAssessment] = []
    known_health_total = 0.0
    unknown_count = 0
    for baseline in verification.observed_objects:
        current = current_by_id.get(baseline.object_id)
        if baseline.object_id in destroyed_ids:
            result = InfrastructureObjectAssessment(baseline.object_id, 0.0, "destroyed", "dcs_event")
        elif current is not None and (current.exists is False or current.life is not None and current.life <= 0):
            result = InfrastructureObjectAssessment(baseline.object_id, 0.0, "destroyed", "current_snapshot")
        elif current is not None:
            health = _relative_object_health(baseline, current)
            condition = "damaged" if health < 0.999 else "intact"
            result = InfrastructureObjectAssessment(baseline.object_id, health, condition, "current_snapshot")
        elif current_observation_complete:
            result = InfrastructureObjectAssessment(baseline.object_id, 0.0, "destroyed", "missing_from_complete_survey")
        else:
            result = InfrastructureObjectAssessment(baseline.object_id, None, "unknown", "incomplete_survey")
        assessed.append(result)
        if result.health is None:
            unknown_count += 1
        else:
            known_health_total += result.health

    count = len(assessed)
    complete = verification.observation_complete and current_observation_complete and unknown_count == 0
    if count == 0:
        health_min = health_max = None
        state = InfrastructureOperationalState.UNKNOWN
    else:
        health_min = known_health_total / count
        health_max = (known_health_total + unknown_count) / count
        confirmed_damage = any(item.health is not None and item.health < 0.999 for item in assessed)
        if verification.observation_complete and health_max <= destroyed_health_threshold:
            state = InfrastructureOperationalState.DESTROYED
        elif verification.observation_complete and health_max <= disabled_health_threshold:
            state = InfrastructureOperationalState.DISABLED
        elif confirmed_damage:
            state = InfrastructureOperationalState.DAMAGED
        elif complete:
            state = InfrastructureOperationalState.OPERATIONAL
        else:
            state = InfrastructureOperationalState.UNKNOWN

    return InfrastructureStateAssessment(
        source_id=verification.source_id,
        state=state,
        baseline_count=count,
        intact_count=sum(item.condition == "intact" for item in assessed),
        damaged_count=sum(item.condition == "damaged" for item in assessed),
        destroyed_count=sum(item.condition == "destroyed" for item in assessed),
        unknown_count=unknown_count,
        health_min=health_min,
        health_max=health_max,
        complete=complete,
        objects=tuple(assessed),
    )


def _relative_object_health(baseline: ObservedDcsObject, current: ObservedDcsObject) -> float:
    if current.life is None or baseline.life is None or baseline.life <= 0:
        return 1.0
    return max(0.0, min(1.0, current.life / baseline.life))


@dataclass(slots=True)
class StrategicVerificationRegistry:
    """Versioned collection of fixed scenery mappings for one DCS theater."""

    theater_id: str = ""
    entries: dict[str, StrategicSiteVerification] = field(default_factory=dict)

    def bind_theater(self, theater_id: str) -> "StrategicVerificationRegistry":
        """Bind an unscoped registry or reject data from another theater."""

        expected = theater_id.strip()
        if not expected:
            return self
        if self.theater_id and self.theater_id.casefold() != expected.casefold():
            raise ValueError(
                f"strategic verification theater mismatch: expected {expected}, "
                f"found {self.theater_id}"
            )
        self.theater_id = expected
        return self

    def get(self, source_id: str) -> StrategicSiteVerification | None:
        return self.entries.get(source_id)

    def upsert(self, verification: StrategicSiteVerification) -> StrategicSiteVerification:
        self.entries[verification.source_id] = verification
        return verification

    def remove(self, source_id: str) -> StrategicSiteVerification | None:
        return self.entries.pop(source_id, None)

    def all(self) -> tuple[StrategicSiteVerification, ...]:
        return tuple(self.entries[key] for key in sorted(self.entries))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "theater_id": self.theater_id,
            "verifications": [item.to_dict() for item in self.all()],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategicVerificationRegistry":
        version = int(payload.get("schema_version") or 0)
        if version == 1:
            payload = _migrate_v1_payload(payload)
            version = 2
        if version == 2:
            payload = _migrate_v2_payload(payload)
            version = 3
        if version == 3:
            payload = _migrate_v3_payload(payload)
            version = SCHEMA_VERSION
        if version != SCHEMA_VERSION:
            raise ValueError(f"unsupported strategic verification schema version: {version}")
        registry = cls(
            theater_id=str(payload.get("theater_id") or ""),
        )
        for item in payload.get("verifications") or ():
            if isinstance(item, Mapping):
                registry.upsert(StrategicSiteVerification.from_dict(item))
        return registry

    @classmethod
    def load(cls, path: str | Path) -> "StrategicVerificationRegistry":
        target = Path(path)
        if not target.is_file():
            return cls()
        with target.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, Mapping):
            raise ValueError("strategic verification file must contain a JSON object")
        return cls.from_dict(payload)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    @classmethod
    def from_entries(
        cls,
        entries: Iterable[StrategicSiteVerification],
        *,
        theater_id: str = "",
    ) -> "StrategicVerificationRegistry":
        registry = cls(theater_id=theater_id)
        for entry in entries:
            registry.upsert(entry)
        return registry


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _is_scenery_object_id(object_id: str) -> bool:
    prefix, separator, name = object_id.partition(":")
    return bool(separator and name.strip() and prefix.upper() == SCENERY_OBJECT_PREFIX)


def _coerce_verification_state(value: Any) -> StrategicVerificationState:
    """Read current and legacy verification labels using the simplified model."""

    if isinstance(value, StrategicVerificationState):
        return value
    raw = str(value or StrategicVerificationState.UNVERIFIED.value)
    if raw in {
        "confirmed",
        "dcs_scenery_matched",
        "dcs_mission_object_matched",
        "dcs_visual_only",
        "approximate",
        StrategicVerificationState.REPRESENTED.value,
    }:
        return StrategicVerificationState.REPRESENTED
    if raw in {"not_represented_in_dcs", StrategicVerificationState.NOT_REPRESENTED.value}:
        return StrategicVerificationState.NOT_REPRESENTED
    return StrategicVerificationState.UNVERIFIED


def _migrate_v1_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Rename the former ambiguous components field during the v1 -> v2 load."""

    migrated = dict(payload)
    migrated["schema_version"] = 2
    migrated["verifications"] = [
        {
            **dict(item),
            "observed_objects": [],
            "observation_complete": False,
            "target_components": list(item.get("components") or ()),
        }
        for item in payload.get("verifications") or ()
        if isinstance(item, Mapping)
    ]
    return migrated


def _migrate_v2_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Collapse detailed v2 evidence labels into the three-state v3 model."""

    migrated = dict(payload)
    migrated["schema_version"] = 3
    migrated["verifications"] = [
        {
            **{key: value for key, value in dict(item).items() if key != "scenario_approved"},
            "state": _coerce_verification_state(item.get("state")).value,
        }
        for item in payload.get("verifications") or ()
        if isinstance(item, Mapping)
    ]
    return migrated


def _migrate_v3_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convert scenario mappings into theater-level, scenery-only evidence."""

    migrated_verifications: list[dict[str, Any]] = []
    for item in payload.get("verifications") or ():
        if not isinstance(item, Mapping):
            continue
        observed = [
            dict(candidate)
            for candidate in item.get("observed_objects") or ()
            if isinstance(candidate, Mapping)
            and _is_scenery_object_id(str(candidate.get("object_id") or ""))
        ]
        observed_ids = {str(candidate.get("object_id") or "") for candidate in observed}
        targets = [
            dict(candidate)
            for candidate in item.get("target_components") or ()
            if isinstance(candidate, Mapping)
            and _is_scenery_object_id(str(candidate.get("object_id") or ""))
            and str(candidate.get("object_id") or "") in observed_ids
        ]
        state = _coerce_verification_state(item.get("state"))
        if state is StrategicVerificationState.REPRESENTED and not observed:
            state = StrategicVerificationState.UNVERIFIED
        if state is StrategicVerificationState.NOT_REPRESENTED:
            targets = []
        migrated_verifications.append({
            **dict(item),
            "state": state.value,
            "observed_objects": observed,
            "target_components": targets,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "theater_id": str(payload.get("theater_id") or ""),
        "verifications": migrated_verifications,
    }
