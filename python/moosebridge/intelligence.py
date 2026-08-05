"""Coalition-private INTEL freshness and contact-memory models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import TYPE_CHECKING, Callable

from .models import IntelContact

if TYPE_CHECKING:
    from .state import MooseBridgeState


class ContactInformationState(str, Enum):
    """Operational quality of one INTEL contact observation."""

    FRESH = "fresh"
    DEGRADED = "degraded"
    STALE = "stale"
    UNKNOWN = "unknown"
    LOST = "lost"


@dataclass(slots=True, frozen=True)
class IntelContactMemory:
    """Last known state retained after MOOSE emits ``LostContact``."""

    contact: IntelContact
    lost_time: float | None = None
    event_id: str | None = None


@dataclass(slots=True, frozen=True)
class IntelContactAssessment:
    """Time-based information quality without changing MOOSE contact ownership."""

    contact: IntelContact
    state: ContactInformationState
    age_s: float | None
    confidence: float


class InformationRequirementMatch(str, Enum):
    """How target observations satisfy an information requirement."""

    ALL = "all"
    ANY = "any"


class InformationRequirementStatus(str, Enum):
    """Current coalition knowledge state without command side effects."""

    OPEN = "open"
    PARTIAL = "partial"
    SATISFIED = "satisfied"
    LOST = "lost"


@dataclass(slots=True)
class InformationRequirement:
    """Continuously evaluated need for coalition-private target knowledge."""

    requirement_id: str
    intel_id: str
    target_object_ids: tuple[str, ...]
    match: InformationRequirementMatch = InformationRequirementMatch.ALL
    priority: float = 0.0
    status: InformationRequirementStatus = InformationRequirementStatus.OPEN
    observed_target_ids: tuple[str, ...] = ()
    missing_target_ids: tuple[str, ...] = ()
    lost_target_ids: tuple[str, ...] = ()
    created_mission_time: float | None = None
    updated_mission_time: float | None = None
    satisfied_mission_time: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.requirement_id = self.requirement_id.strip()
        self.intel_id = self.intel_id.strip()
        self.target_object_ids = tuple(dict.fromkeys(item.strip() for item in self.target_object_ids if item.strip()))
        self.match = InformationRequirementMatch(self.match)
        self.status = InformationRequirementStatus(self.status)
        if not self.requirement_id:
            raise ValueError("information requirement id must not be empty")
        if not self.intel_id.startswith("INTEL:"):
            raise ValueError("information requirement intel_id must start with INTEL:")
        if not self.target_object_ids or any(":" not in item for item in self.target_object_ids):
            raise ValueError("information requirement needs stable target object ids")
        if not math.isfinite(self.priority) or self.priority < 0:
            raise ValueError("information requirement priority must be finite and non-negative")
        if not self.missing_target_ids:
            self.missing_target_ids = self.target_object_ids


@dataclass(slots=True, frozen=True)
class InformationRequirementEvent:
    """One event-driven knowledge-state transition."""

    event: str
    requirement_id: str
    intel_id: str
    source: str
    mission_time: float | None
    previous_status: InformationRequirementStatus | None
    status: InformationRequirementStatus
    observed_target_ids: tuple[str, ...]
    missing_target_ids: tuple[str, ...]
    lost_target_ids: tuple[str, ...]


class InformationRequirementRegistry:
    """Evaluate target knowledge from general INTEL contacts without tasking units."""

    def __init__(self) -> None:
        self._requirements: dict[str, InformationRequirement] = {}
        self._events: list[InformationRequirementEvent] = []
        self._listeners: list[Callable[[InformationRequirementEvent], None]] = []

    @property
    def events(self) -> tuple[InformationRequirementEvent, ...]:
        return tuple(self._events)

    def add_listener(self, listener: Callable[[InformationRequirementEvent], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[InformationRequirementEvent], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def add(
        self,
        requirement: InformationRequirement,
        *,
        replace: bool = False,
        state: MooseBridgeState | None = None,
        source: str = "python",
    ) -> InformationRequirement:
        if requirement.requirement_id in self._requirements and not replace:
            raise ValueError(f"Information requirement already exists: {requirement.requirement_id}")
        self._requirements[requirement.requirement_id] = requirement
        self._record(InformationRequirementEvent(
            "information_requirement.replaced" if replace else "information_requirement.created",
            requirement.requirement_id,
            requirement.intel_id,
            source,
            requirement.created_mission_time,
            None,
            requirement.status,
            requirement.observed_target_ids,
            requirement.missing_target_ids,
            requirement.lost_target_ids,
        ))
        if state is not None:
            self.sync(state, source="current_state")
        return requirement

    def remove(self, requirement: InformationRequirement | str) -> InformationRequirement:
        requirement_id = requirement.requirement_id if isinstance(requirement, InformationRequirement) else requirement
        try:
            return self._requirements.pop(requirement_id)
        except KeyError as exc:
            raise KeyError(f"Unknown information requirement: {requirement_id}") from exc

    def get(self, requirement_id: str) -> InformationRequirement | None:
        return self._requirements.get(requirement_id)

    def all(self) -> tuple[InformationRequirement, ...]:
        return tuple(self._requirements[key] for key in sorted(self._requirements))

    def clear(self) -> None:
        """Discard all mission-scoped requirements and their local event history."""

        self._requirements.clear()
        self._events.clear()

    def filter(
        self,
        *,
        intel_id: str | None = None,
        status: InformationRequirementStatus | str | None = None,
    ) -> tuple[InformationRequirement, ...]:
        normalized_status = InformationRequirementStatus(status) if status is not None else None
        return tuple(
            item for item in self.all()
            if (intel_id is None or item.intel_id == intel_id)
            and (normalized_status is None or item.status is normalized_status)
        )

    def sync(
        self,
        state: MooseBridgeState,
        *,
        source: str = "intel.sync",
    ) -> tuple[InformationRequirementEvent, ...]:
        mission_time = state.clock.mission_time if state.clock else None
        current_by_intel: dict[str, set[str]] = {}
        lost_by_intel: dict[str, set[str]] = {}
        for contact in state.intel_contact_objects.values():
            if contact.intel_id and contact.target_object_id:
                current_by_intel.setdefault(contact.intel_id, set()).add(contact.target_object_id)
        for memory in state.lost_intel_contact_objects.values():
            contact = memory.contact
            if contact.intel_id and contact.target_object_id:
                lost_by_intel.setdefault(contact.intel_id, set()).add(contact.target_object_id)

        emitted: list[InformationRequirementEvent] = []
        for requirement in self.all():
            targets = set(requirement.target_object_ids)
            observed = targets & current_by_intel.get(requirement.intel_id, set())
            lost = (targets - observed) & lost_by_intel.get(requirement.intel_id, set())
            missing = targets - observed - lost
            satisfied = bool(observed) if requirement.match is InformationRequirementMatch.ANY else observed == targets
            if satisfied:
                next_status = InformationRequirementStatus.SATISFIED
            elif lost:
                next_status = InformationRequirementStatus.LOST
            elif observed:
                next_status = InformationRequirementStatus.PARTIAL
            else:
                next_status = InformationRequirementStatus.OPEN
            previous = requirement.status
            requirement.observed_target_ids = tuple(sorted(observed))
            requirement.lost_target_ids = tuple(sorted(lost))
            requirement.missing_target_ids = tuple(sorted(missing))
            requirement.updated_mission_time = mission_time
            if next_status is InformationRequirementStatus.SATISFIED and previous is not next_status:
                requirement.satisfied_mission_time = mission_time
            requirement.status = next_status
            if previous is next_status:
                continue
            event = InformationRequirementEvent(
                f"information_requirement.{next_status.value}",
                requirement.requirement_id,
                requirement.intel_id,
                source,
                mission_time,
                previous,
                next_status,
                requirement.observed_target_ids,
                requirement.missing_target_ids,
                requirement.lost_target_ids,
            )
            self._record(event)
            emitted.append(event)
        return tuple(emitted)

    def _record(self, event: InformationRequirementEvent) -> None:
        self._events.append(event)
        if len(self._events) > 10_000:
            del self._events[:1_000]
        for listener in tuple(self._listeners):
            listener(event)


def assess_intel_contact(
    contact: IntelContact,
    mission_time: float | None,
    *,
    fresh_for_s: float = 120.0,
    stale_after_s: float = 600.0,
    lost: bool = False,
) -> IntelContactAssessment:
    """Assess one contact from its MOOSE ``Tdetected`` mission timestamp."""

    if not math.isfinite(fresh_for_s) or fresh_for_s < 0:
        raise ValueError("fresh_for_s must be finite and non-negative")
    if not math.isfinite(stale_after_s) or stale_after_s <= fresh_for_s:
        raise ValueError("stale_after_s must be finite and greater than fresh_for_s")
    if mission_time is None or contact.detected_time is None:
        state = ContactInformationState.LOST if lost else ContactInformationState.UNKNOWN
        return IntelContactAssessment(contact, state, None, 0.25 if lost else 0.5)

    age_s = max(0.0, mission_time - contact.detected_time)
    if lost:
        confidence = max(0.0, 0.5 * (1.0 - min(age_s / stale_after_s, 1.0)))
        return IntelContactAssessment(contact, ContactInformationState.LOST, age_s, confidence)
    if age_s <= fresh_for_s:
        return IntelContactAssessment(contact, ContactInformationState.FRESH, age_s, 1.0)
    if age_s < stale_after_s:
        fraction = (age_s - fresh_for_s) / (stale_after_s - fresh_for_s)
        return IntelContactAssessment(contact, ContactInformationState.DEGRADED, age_s, 1.0 - 0.75 * fraction)
    return IntelContactAssessment(contact, ContactInformationState.STALE, age_s, 0.1)


__all__ = [
    "ContactInformationState",
    "InformationRequirement",
    "InformationRequirementEvent",
    "InformationRequirementMatch",
    "InformationRequirementRegistry",
    "InformationRequirementStatus",
    "IntelContactAssessment",
    "IntelContactMemory",
    "assess_intel_contact",
]
