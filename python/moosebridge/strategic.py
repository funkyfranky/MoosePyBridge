"""Python-owned strategic objectives built from DCS and MOOSE objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Iterable

from .state import MooseBridgeState


class ObjectiveKind(str, Enum):
    """Broad strategic objective categories."""

    AIRBASE = "airbase"
    FARP = "farp"
    DEPOT = "depot"
    PORT = "port"
    INFRASTRUCTURE = "infrastructure"
    FORCE = "force"
    OPSZONE = "opszone"
    TERRITORY = "territory"
    CUSTOM = "custom"


class ObjectiveStatus(str, Enum):
    """Current functional state of a strategic objective."""

    UNKNOWN = "unknown"
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    DESTROYED = "destroyed"
    CONTESTED = "contested"


class OwnershipPolicy(str, Enum):
    """Authority that determines an objective's current owner."""

    DCS_MANAGED = "dcs_managed"
    MOOSE_MANAGED = "moose_managed"
    TERRITORY_INHERITED = "territory_inherited"
    FIXED = "fixed"


class CaptureBehavior(str, Enum):
    """Requested treatment of a component after a control change."""

    KEEP = "keep"
    DESTROY = "destroy"
    RESPAWN_FOR_NEW_OWNER = "respawn_for_new_owner"
    DISABLE = "disable"


@dataclass(slots=True, frozen=True)
class ObjectiveComponent:
    """One DCS or MOOSE object participating in a strategic objective."""

    object_id: str
    role: str = "component"
    weight: float = 1.0
    contributes_to_health: bool = True
    capture_behavior: CaptureBehavior = CaptureBehavior.KEEP
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object_id = self.object_id.strip()
        role = self.role.strip()
        if not object_id or ":" not in object_id:
            raise ValueError("component object_id must be a stable bridge id such as STATIC:Depot-1")
        if not role:
            raise ValueError("component role must not be empty")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError("component weight must be finite and non-negative")
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "capture_behavior", CaptureBehavior(self.capture_behavior))


@dataclass(slots=True)
class StrategicObjective:
    """A Python-owned strategic objective composed of bridge objects."""

    objective_id: str
    name: str
    kind: ObjectiveKind
    control_object_id: str | None
    ownership_policy: OwnershipPolicy
    components: tuple[ObjectiveComponent, ...] = ()
    strategic_value: float = 0.0
    priority: float = 0.0
    owner: str | None = None
    status: ObjectiveStatus = ObjectiveStatus.UNKNOWN
    health: float | None = None
    contested: bool = False
    created_mission_time: float | None = None
    updated_mission_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.objective_id = self.objective_id.strip()
        self.name = self.name.strip()
        self.control_object_id = self.control_object_id.strip() if self.control_object_id else None
        self.kind = ObjectiveKind(self.kind)
        self.ownership_policy = OwnershipPolicy(self.ownership_policy)
        self.status = ObjectiveStatus(self.status)
        self.components = tuple(self.components)
        self.owner = normalize_coalition(self.owner)
        if not self.objective_id:
            raise ValueError("objective_id must not be empty")
        if not self.name:
            raise ValueError("objective name must not be empty")
        if self.ownership_policy is not OwnershipPolicy.FIXED and not self.control_object_id:
            raise ValueError("managed objectives require control_object_id")
        if not math.isfinite(self.strategic_value) or self.strategic_value < 0:
            raise ValueError("strategic_value must be finite and non-negative")
        if not math.isfinite(self.priority) or self.priority < 0:
            raise ValueError("priority must be finite and non-negative")
        if self.health is not None and not 0.0 <= self.health <= 1.0:
            raise ValueError("health must be between 0 and 1")
        component_ids = [component.object_id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("objective components must have unique object ids")


@dataclass(slots=True, frozen=True)
class ObjectiveEvent:
    """One normalized change emitted by the strategic objective registry."""

    event: str
    objective_id: str
    source: str
    mission_time: float | None = None
    previous_owner: str | None = None
    owner: str | None = None
    previous_status: ObjectiveStatus | None = None
    status: ObjectiveStatus | None = None
    details: dict[str, Any] = field(default_factory=dict, compare=False)


class StrategicObjectiveRegistry:
    """Dynamic registry and state synchronizer for strategic objectives."""

    def __init__(self) -> None:
        self._objectives: dict[str, StrategicObjective] = {}
        self._events: list[ObjectiveEvent] = []

    @property
    def events(self) -> tuple[ObjectiveEvent, ...]:
        """Return normalized events emitted during this registry's lifetime."""

        return tuple(self._events)

    def add(self, objective: StrategicObjective, *, replace: bool = False) -> StrategicObjective:
        """Add a runtime objective, optionally replacing an existing definition."""

        if objective.objective_id in self._objectives and not replace:
            raise ValueError(f"Strategic objective already exists: {objective.objective_id}")
        self._objectives[objective.objective_id] = objective
        self._record(
            ObjectiveEvent(
                event="objective.created" if not replace else "objective.replaced",
                objective_id=objective.objective_id,
                source="python",
                mission_time=objective.created_mission_time,
                owner=objective.owner,
                status=objective.status,
            )
        )
        return objective

    def remove(self, objective: StrategicObjective | str) -> StrategicObjective:
        """Remove and return a runtime objective."""

        objective_id = objective.objective_id if isinstance(objective, StrategicObjective) else objective
        try:
            removed = self._objectives.pop(objective_id)
        except KeyError as exc:
            raise KeyError(f"Unknown strategic objective: {objective_id}") from exc
        self._record(
            ObjectiveEvent(
                event="objective.removed",
                objective_id=removed.objective_id,
                source="python",
                mission_time=removed.updated_mission_time,
                previous_owner=removed.owner,
                previous_status=removed.status,
            )
        )
        return removed

    def get(self, objective_id: str) -> StrategicObjective | None:
        """Return an objective by id."""

        return self._objectives.get(objective_id)

    def all(self) -> tuple[StrategicObjective, ...]:
        """Return all objectives in stable id order."""

        return tuple(self._objectives[key] for key in sorted(self._objectives))

    def filter(
        self,
        *,
        owner: str | None = None,
        kind: ObjectiveKind | str | None = None,
        status: ObjectiveStatus | str | None = None,
        minimum_priority: float | None = None,
    ) -> tuple[StrategicObjective, ...]:
        """Return objectives matching common strategic selectors."""

        normalized_owner = normalize_coalition(owner) if owner is not None else None
        normalized_kind = ObjectiveKind(kind) if kind is not None else None
        normalized_status = ObjectiveStatus(status) if status is not None else None
        return tuple(
            objective
            for objective in self.all()
            if (normalized_owner is None or objective.owner == normalized_owner)
            and (normalized_kind is None or objective.kind is normalized_kind)
            and (normalized_status is None or objective.status is normalized_status)
            and (minimum_priority is None or objective.priority >= minimum_priority)
        )

    def sync(self, state: MooseBridgeState, *, source: str = "snapshot") -> tuple[ObjectiveEvent, ...]:
        """Synchronize objective ownership and health from current bridge state."""

        emitted: list[ObjectiveEvent] = []
        mission_time = state.clock.mission_time if state.clock else None
        for objective in self.all():
            previous_owner = objective.owner
            previous_status = objective.status
            previous_contested = objective.contested
            previous_health = objective.health

            resolved, owner, contested = _resolve_control(objective, state)
            health = _objective_health(objective.components, state)
            status = _objective_status(
                resolved=resolved,
                previous=previous_status,
                health=health,
                contested=contested,
            )

            if resolved:
                objective.owner = owner
                objective.contested = contested
            objective.health = health
            objective.status = status

            changed = (
                objective.owner != previous_owner
                or objective.status is not previous_status
                or objective.contested != previous_contested
                or objective.health != previous_health
            )
            if changed:
                objective.updated_mission_time = mission_time

            if objective.owner != previous_owner:
                emitted.append(
                    ObjectiveEvent(
                        event="objective.control_changed",
                        objective_id=objective.objective_id,
                        source=source,
                        mission_time=mission_time,
                        previous_owner=previous_owner,
                        owner=objective.owner,
                        previous_status=previous_status,
                        status=objective.status,
                        details={"control_object_id": objective.control_object_id},
                    )
                )
            if objective.contested != previous_contested:
                emitted.append(
                    ObjectiveEvent(
                        event="objective.contested" if objective.contested else "objective.secured",
                        objective_id=objective.objective_id,
                        source=source,
                        mission_time=mission_time,
                        owner=objective.owner,
                        previous_status=previous_status,
                        status=objective.status,
                    )
                )
            if objective.status is not previous_status and objective.owner == previous_owner:
                emitted.append(
                    ObjectiveEvent(
                        event=f"objective.{objective.status.value}",
                        objective_id=objective.objective_id,
                        source=source,
                        mission_time=mission_time,
                        owner=objective.owner,
                        previous_status=previous_status,
                        status=objective.status,
                        details={"health": objective.health},
                    )
                )

        for event in emitted:
            self._record(event)
        return tuple(emitted)

    def _record(self, event: ObjectiveEvent) -> None:
        self._events.append(event)
        if len(self._events) > 10_000:
            del self._events[:1_000]


def normalize_coalition(value: Any) -> str | None:
    """Normalize DCS coalition ids and names."""

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return {0: "neutral", 1: "red", 2: "blue"}.get(int(value))
    normalized = str(value).strip().lower()
    aliases = {"0": "neutral", "1": "red", "2": "blue", "neutrals": "neutral"}
    return aliases.get(normalized, normalized if normalized in {"neutral", "red", "blue"} else None)


def capture_actions(event: ObjectiveEvent, objective: StrategicObjective) -> tuple[ObjectiveComponent, ...]:
    """Return components requiring explicit work after a control change."""

    if event.event != "objective.control_changed" or event.owner is None:
        return ()
    return tuple(
        component
        for component in objective.components
        if component.capture_behavior is not CaptureBehavior.KEEP
    )


def _resolve_control(
    objective: StrategicObjective,
    state: MooseBridgeState,
) -> tuple[bool, str | None, bool]:
    if objective.ownership_policy is OwnershipPolicy.FIXED:
        return True, objective.owner, objective.contested
    object_id = objective.control_object_id
    if not object_id:
        return False, objective.owner, objective.contested

    if objective.ownership_policy is OwnershipPolicy.DCS_MANAGED:
        payload = state.airbases.get(object_id)
        if payload is None:
            return False, objective.owner, objective.contested
        owner = normalize_coalition(
            payload.get("coalition")
            if payload.get("coalition") is not None
            else payload.get("coalition_name")
        )
        return True, owner, False

    if objective.ownership_policy is OwnershipPolicy.MOOSE_MANAGED:
        opszone = state.opszone(object_id)
        if opszone is None:
            return False, objective.owner, objective.contested
        return True, normalize_coalition(opszone.owner_current_name), opszone.is_contested

    if objective.ownership_policy is OwnershipPolicy.TERRITORY_INHERITED:
        territory = state.territory(object_id)
        if territory is None:
            return False, objective.owner, objective.contested
        return True, normalize_coalition(territory.coalition), False

    return False, objective.owner, objective.contested


def _objective_health(components: Iterable[ObjectiveComponent], state: MooseBridgeState) -> float | None:
    weighted_health = 0.0
    total_weight = 0.0
    for component in components:
        if not component.contributes_to_health or component.weight <= 0:
            continue
        health = _component_health(component.object_id, state)
        if health is None:
            continue
        weighted_health += health * component.weight
        total_weight += component.weight
    if total_weight <= 0:
        return None
    return max(0.0, min(1.0, weighted_health / total_weight))


def _component_health(object_id: str, state: MooseBridgeState) -> float | None:
    prefix = object_id.partition(":")[0].upper()
    collections = {
        "GROUP": state.groups,
        "UNIT": state.units,
        "STATIC": state.statics,
        "AIRBASE": state.airbases,
        "OPSZONE": state.opszones,
        "TERRITORY": state.territories,
    }
    payload = collections.get(prefix, {}).get(object_id)
    if payload is None:
        return None
    life = _number(payload.get("life"))
    life_initial = _number(payload.get("life_initial")) or _number(payload.get("life0"))
    if life is not None and life_initial is not None and life_initial > 0:
        return max(0.0, min(1.0, life / life_initial))
    if payload.get("alive") is not None:
        return 1.0 if bool(payload.get("alive")) else 0.0
    return None


def _objective_status(
    *,
    resolved: bool,
    previous: ObjectiveStatus,
    health: float | None,
    contested: bool,
) -> ObjectiveStatus:
    if contested:
        return ObjectiveStatus.CONTESTED
    if health is not None:
        if health <= 0:
            return ObjectiveStatus.DESTROYED
        if health < 0.35:
            return ObjectiveStatus.DISABLED
        if health < 0.85:
            return ObjectiveStatus.DEGRADED
        return ObjectiveStatus.OPERATIONAL
    if resolved:
        return ObjectiveStatus.OPERATIONAL
    return previous


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
