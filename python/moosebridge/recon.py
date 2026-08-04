"""Event-based tactical assessment of MOOSE RECON missions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import TYPE_CHECKING, Any, Iterable

from .models import IntelContact
from .outcomes import AuftragOutcome

if TYPE_CHECKING:
    from .operational import OperationalPlan
    from .pictures import TacticalPicture
    from .strategic import StrategicGoal, StrategicObjective


class ReconTargetSource(str, Enum):
    """Why one object is relevant to a reconnaissance requirement."""

    MANUAL = "manual"
    GOAL = "goal"
    OBJECTIVE_COMPONENT = "objective_component"
    PHASE_TARGET = "phase_target"
    INTEL_CONTACT = "intel_contact"
    LOST_CONTACT = "lost_contact"


@dataclass(slots=True, frozen=True)
class ReconRelevantTarget:
    """One target and the reasons it matters to a RECON mission."""

    object_id: str
    sources: tuple[ReconTargetSource, ...]
    contact_id: str | None = None
    confidence: float | None = None
    information_age_s: float | None = None
    threat_level: float = 0.0

    def __post_init__(self) -> None:
        object_id = self.object_id.strip()
        if not object_id or ":" not in object_id:
            raise ValueError("recon target requires a stable bridge object id")
        sources = tuple(dict.fromkeys(ReconTargetSource(item) for item in self.sources))
        if not sources:
            raise ValueError("recon target requires at least one source")
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(self, "sources", sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "sources": [item.value for item in self.sources],
            "contact_id": self.contact_id,
            "confidence": self.confidence,
            "information_age_s": self.information_age_s,
            "threat_level": self.threat_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReconRelevantTarget":
        """Restore one relevant target from serialized plan metadata."""

        return cls(
            object_id=str(data.get("object_id") or ""),
            sources=tuple(ReconTargetSource(item) for item in data.get("sources", ())),
            contact_id=str(data.get("contact_id")) if data.get("contact_id") else None,
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            information_age_s=float(data["information_age_s"]) if data.get("information_age_s") is not None else None,
            threat_level=float(data.get("threat_level") or 0.0),
        )


@dataclass(slots=True, frozen=True)
class ReconRequirement:
    """Desired information state for one reconnaissance area."""

    area_object_id: str
    relevant_targets: tuple[ReconRelevantTarget, ...] = ()
    derive_targets: bool = True
    minimum_confidence: float = 0.7
    maximum_contact_age_s: float = 300.0
    area_buffer_m: float = 30_000.0

    def __post_init__(self) -> None:
        area = self.area_object_id.strip()
        if not area or ":" not in area:
            raise ValueError("recon requirement requires a stable area object id")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between zero and one")
        if not math.isfinite(self.maximum_contact_age_s) or self.maximum_contact_age_s <= 0:
            raise ValueError("maximum_contact_age_s must be finite and positive")
        if not math.isfinite(self.area_buffer_m) or self.area_buffer_m < 0:
            raise ValueError("area_buffer_m must be finite and non-negative")
        targets = _merge_recon_targets(self.relevant_targets)
        object.__setattr__(self, "area_object_id", area)
        object.__setattr__(self, "relevant_targets", targets)

    @property
    def relevant_target_ids(self) -> tuple[str, ...]:
        return tuple(item.object_id for item in self.relevant_targets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "area_object_id": self.area_object_id,
            "derive_targets": self.derive_targets,
            "minimum_confidence": self.minimum_confidence,
            "maximum_contact_age_s": self.maximum_contact_age_s,
            "area_buffer_m": self.area_buffer_m,
            "relevant_targets": [item.to_dict() for item in self.relevant_targets],
        }

    @classmethod
    def manual(cls, area_object_id: str, *target_ids: str, **kwargs: Any) -> "ReconRequirement":
        """Create a strictly manual requirement for tests or operator tasking."""

        return cls(
            area_object_id=area_object_id,
            relevant_targets=tuple(
                ReconRelevantTarget(object_id, (ReconTargetSource.MANUAL,)) for object_id in target_ids
            ),
            derive_targets=False,
            **kwargs,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReconRequirement":
        """Restore a requirement from operational-plan metadata."""

        raw_targets = data.get("relevant_targets") if isinstance(data.get("relevant_targets"), list) else []
        return cls(
            area_object_id=str(data.get("area_object_id") or ""),
            relevant_targets=tuple(
                ReconRelevantTarget.from_dict(item) for item in raw_targets if isinstance(item, dict)
            ),
            derive_targets=bool(data.get("derive_targets", True)),
            minimum_confidence=float(data.get("minimum_confidence", 0.7)),
            maximum_contact_age_s=float(data.get("maximum_contact_age_s", 300.0)),
            area_buffer_m=float(data.get("area_buffer_m", 30_000.0)),
        )


def _merge_recon_targets(targets: Iterable[ReconRelevantTarget]) -> tuple[ReconRelevantTarget, ...]:
    merged: dict[str, ReconRelevantTarget] = {}
    for target in targets:
        previous = merged.get(target.object_id)
        if previous is None:
            merged[target.object_id] = target
            continue
        merged[target.object_id] = ReconRelevantTarget(
            object_id=target.object_id,
            sources=tuple(dict.fromkeys((*previous.sources, *target.sources))),
            contact_id=target.contact_id or previous.contact_id,
            confidence=target.confidence if target.confidence is not None else previous.confidence,
            information_age_s=target.information_age_s if target.information_age_s is not None else previous.information_age_s,
            threat_level=max(previous.threat_level, target.threat_level),
        )
    return tuple(merged.values())


def _object_id_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return ()


def derive_recon_requirement(
    goal: "StrategicGoal",
    objective: "StrategicObjective",
    picture: "TacticalPicture",
    *,
    plan: "OperationalPlan | None" = None,
    manual_target_ids: Iterable[str] = (),
    derive_targets: bool = True,
    minimum_confidence: float = 0.7,
    maximum_contact_age_s: float = 300.0,
    area_buffer_m: float = 30_000.0,
) -> ReconRequirement:
    """Derive coalition-private reconnaissance targets from planning context."""

    if goal.objective_id != objective.objective_id:
        raise ValueError("goal and objective do not refer to the same objective")
    if goal.coalition != picture.coalition:
        raise ValueError("goal and tactical picture coalitions do not match")
    area_id = objective.control_object_id or str(goal.metadata.get("area_object_id") or "")
    if not area_id:
        raise ValueError("objective has no control area for reconnaissance")
    targets = [
        ReconRelevantTarget(str(object_id), (ReconTargetSource.MANUAL,))
        for object_id in manual_target_ids
    ]
    if derive_targets:
        for object_id in _object_id_values(goal.metadata.get("relevant_target_ids", ())):
            targets.append(ReconRelevantTarget(str(object_id), (ReconTargetSource.GOAL,)))
        targets.extend(
            ReconRelevantTarget(component.object_id, (ReconTargetSource.OBJECTIVE_COMPONENT,))
            for component in objective.components
        )
        if plan is not None:
            for phase in plan.phases:
                for intent in phase.intents:
                    if intent.target_object_id and intent.target_object_id != area_id:
                        targets.append(ReconRelevantTarget(intent.target_object_id, (ReconTargetSource.PHASE_TARGET,)))

        zone = next((item for item in picture.opszones if item.object_id == area_id), None)
        zone_radius = max(0.0, zone.zone_radius or 0.0) if zone else 0.0
        max_distance = zone_radius + area_buffer_m
        fresh_for_s = min(120.0, maximum_contact_age_s / 2.0)
        for assessment in (
            *picture.contact_assessments(fresh_for_s=fresh_for_s, stale_after_s=maximum_contact_age_s),
            *picture.lost_contact_assessments(fresh_for_s=fresh_for_s, stale_after_s=maximum_contact_age_s),
        ):
            contact = assessment.contact
            target_id = contact.target_object_id
            if not target_id or assessment.age_s is not None and assessment.age_s > maximum_contact_age_s:
                continue
            if str(goal.action.value) == "capture" and not (contact.is_ground or contact.is_static or contact.is_ship):
                continue
            if zone and zone.x is not None and zone.z is not None:
                if contact.x is None or contact.z is None or math.hypot(contact.x - zone.x, contact.z - zone.z) > max_distance:
                    continue
            source = ReconTargetSource.LOST_CONTACT if assessment.state.value == "lost" else ReconTargetSource.INTEL_CONTACT
            targets.append(
                ReconRelevantTarget(
                    target_id,
                    (source,),
                    contact_id=contact.object_id,
                    confidence=assessment.confidence,
                    information_age_s=assessment.age_s,
                    threat_level=float(contact.threat_level or 0.0),
                )
            )
    return ReconRequirement(
        area_object_id=area_id,
        relevant_targets=tuple(targets),
        derive_targets=derive_targets,
        minimum_confidence=minimum_confidence,
        maximum_contact_age_s=maximum_contact_age_s,
        area_buffer_m=area_buffer_m,
    )


def _event_time(event: dict[str, Any]) -> float | None:
    value = event.get("mission_time")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(slots=True, frozen=True)
class ReconContactObservation:
    """One contact observed by an asset assigned to a RECON mission."""

    contact_id: str
    target_object_id: str | None
    recce_unit_id: str | None
    recce_group_id: str | None
    first_detected_time: float | None
    last_detected_time: float | None
    reported_detected_time: float | None
    threat_level: float
    detection_count: int
    new_contact: bool
    reacquired: bool
    detected_during_executing: bool
    lost_at_end: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "contact_id": self.contact_id,
            "target_object_id": self.target_object_id,
            "recce_unit_id": self.recce_unit_id,
            "recce_group_id": self.recce_group_id,
            "first_detected_time": self.first_detected_time,
            "last_detected_time": self.last_detected_time,
            "reported_detected_time": self.reported_detected_time,
            "threat_level": self.threat_level,
            "detection_count": self.detection_count,
            "new_contact": self.new_contact,
            "reacquired": self.reacquired,
            "detected_during_executing": self.detected_during_executing,
            "lost_at_end": self.lost_at_end,
        }


@dataclass(slots=True, frozen=True)
class ReconOutcome:
    """Tactical RECON result layered on the authoritative MOOSE outcome."""

    auftrag_id: str
    intel_id: str
    mission_outcome: AuftragOutcome
    assigned_opsgroup_ids: tuple[str, ...]
    assigned_group_ids: tuple[str, ...]
    started_time: float | None
    executing_time: float | None
    completed_time: float | None
    observations: tuple[ReconContactObservation, ...]
    requirement: ReconRequirement | None = None
    relevant_target_ids: tuple[str, ...] = ()
    observed_relevant_target_ids: tuple[str, ...] = ()
    satisfied_relevant_target_ids: tuple[str, ...] = ()
    lost_relevant_target_ids: tuple[str, ...] = ()
    unknown_relevant_target_ids: tuple[str, ...] = ()
    event_history_complete: bool = True
    command_ack: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def new_contact_count(self) -> int:
        return sum(item.new_contact for item in self.observations)

    @property
    def reacquired_contact_count(self) -> int:
        return sum(item.reacquired for item in self.observations)

    @property
    def lost_contact_count(self) -> int:
        return sum(item.lost_at_end for item in self.observations)

    @property
    def maximum_threat(self) -> float:
        return max((item.threat_level for item in self.observations), default=0.0)

    @property
    def total_threat(self) -> float:
        return sum(item.threat_level for item in self.observations)

    @property
    def first_intelligence_time(self) -> float | None:
        values = [item.first_detected_time for item in self.observations if item.first_detected_time is not None]
        return min(values) if values else None

    @property
    def first_intelligence_delay(self) -> float | None:
        first = self.first_intelligence_time
        origin = self.executing_time if self.executing_time is not None else self.started_time
        return first - origin if first is not None and origin is not None else None

    @property
    def requirement_satisfied(self) -> bool | None:
        """Return target-based completion, or unknown without relevant targets."""

        if not self.relevant_target_ids:
            return None
        return not self.unknown_relevant_target_ids and not self.lost_relevant_target_ids and self.event_history_complete

    @property
    def reconnaissance_required(self) -> bool:
        """Return whether important target information still needs collection."""

        return self.requirement_satisfied is not True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "auftrag_id": self.auftrag_id,
            "intel_id": self.intel_id,
            "mission_outcome": self.mission_outcome.to_dict(),
            "requirement": self.requirement.to_dict() if self.requirement else None,
            "requirement_satisfied": self.requirement_satisfied,
            "reconnaissance_required": self.reconnaissance_required,
            "assigned_opsgroup_ids": list(self.assigned_opsgroup_ids),
            "assigned_group_ids": list(self.assigned_group_ids),
            "started_time": self.started_time,
            "executing_time": self.executing_time,
            "completed_time": self.completed_time,
            "new_contact_count": self.new_contact_count,
            "reacquired_contact_count": self.reacquired_contact_count,
            "lost_contact_count": self.lost_contact_count,
            "maximum_threat": self.maximum_threat,
            "total_threat": self.total_threat,
            "first_intelligence_time": self.first_intelligence_time,
            "first_intelligence_delay": self.first_intelligence_delay,
            "observations": [item.to_dict() for item in self.observations],
            "relevant_target_ids": list(self.relevant_target_ids),
            "observed_relevant_target_ids": list(self.observed_relevant_target_ids),
            "satisfied_relevant_target_ids": list(self.satisfied_relevant_target_ids),
            "lost_relevant_target_ids": list(self.lost_relevant_target_ids),
            "unknown_relevant_target_ids": list(self.unknown_relevant_target_ids),
            "event_history_complete": self.event_history_complete,
        }


def build_recon_outcome(
    *,
    auftrag_id: str,
    intel_id: str,
    mission_outcome: AuftragOutcome,
    events: Iterable[dict[str, Any]],
    baseline_contact_ids: Iterable[str],
    assigned_opsgroup_ids: Iterable[str],
    assigned_group_ids: Iterable[str],
    relevant_target_ids: Iterable[str] = (),
    requirement: ReconRequirement | None = None,
    command_ack: dict[str, Any] | None = None,
    event_history_complete: bool = True,
) -> ReconOutcome:
    """Build a tactical RECON assessment from chronological bridge events."""

    assigned_ops = tuple(dict.fromkeys(str(value) for value in assigned_opsgroup_ids))
    assigned_groups = tuple(dict.fromkeys(str(value) for value in assigned_group_ids))
    assigned_group_set = set(assigned_groups)
    baseline = {str(value) for value in baseline_contact_ids}
    requirement_ids = requirement.relevant_target_ids if requirement else ()
    relevant = tuple(dict.fromkeys((*requirement_ids, *(str(value) for value in relevant_target_ids))))
    relevant_set = set(relevant)
    lifecycle: dict[str, float] = {}
    contact_events: list[tuple[str, dict[str, Any], float | None]] = []

    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        name = str(event.get("event") or payload.get("event") or "")
        event_time = _event_time(event)
        if name.startswith("auftrag.") and str(payload.get("auftrag_id") or "") == auftrag_id:
            fsm = str(payload.get("fsm_event") or "").lower()
            if fsm in {"started", "executing", "done", "cancel"} and event_time is not None:
                lifecycle.setdefault(fsm, event_time)
        if name in {"intel.new_contact", "intel.lost_contact"} and str(payload.get("intel_id") or "") == intel_id:
            contact_payload = payload.get("contact") if isinstance(payload.get("contact"), dict) else payload
            contact_events.append((name, contact_payload, event_time))

    executing_time = lifecycle.get("executing")
    completed_time = lifecycle.get("done", lifecycle.get("cancel"))
    states: dict[str, dict[str, Any]] = {}
    known_ids = set(baseline)
    lost_ids: set[str] = set()
    contact_targets: dict[str, str] = {}

    for name, payload, event_time in contact_events:
        contact = IntelContact.from_payload(payload)
        contact_id = contact.object_id
        if not contact_id:
            continue
        if contact.target_object_id:
            contact_targets[contact_id] = contact.target_object_id
        if name == "intel.lost_contact":
            lost_ids.add(contact_id)
            if contact_id in states:
                states[contact_id]["lost_at_end"] = True
            continue

        was_known = contact_id in known_ids
        was_lost = contact_id in lost_ids
        known_ids.add(contact_id)
        lost_ids.discard(contact_id)
        if contact.recce_group_id not in assigned_group_set:
            continue
        state = states.get(contact_id)
        detected_time = event_time if event_time is not None else contact.detected_time
        if state is None:
            state = {
                "contact_id": contact_id,
                "target_object_id": contact.target_object_id,
                "recce_unit_id": contact.recce_unit_id,
                "recce_group_id": contact.recce_group_id,
                "first_detected_time": detected_time,
                "last_detected_time": detected_time,
                "reported_detected_time": contact.detected_time,
                "threat_level": float(contact.threat_level or 0.0),
                "detection_count": 1,
                "new_contact": not was_known,
                "reacquired": was_lost,
                "detected_during_executing": executing_time is not None and event_time is not None and event_time >= executing_time,
                "lost_at_end": False,
            }
            states[contact_id] = state
        else:
            state["last_detected_time"] = detected_time
            state["reported_detected_time"] = contact.detected_time
            state["threat_level"] = max(state["threat_level"], float(contact.threat_level or 0.0))
            state["detection_count"] += 1
            state["reacquired"] = state["reacquired"] or was_lost
            state["detected_during_executing"] = state["detected_during_executing"] or (
                executing_time is not None and event_time is not None and event_time >= executing_time
            )
            state["lost_at_end"] = False

    observations = tuple(ReconContactObservation(**state) for state in states.values())
    observed_relevant = tuple(sorted({item.target_object_id for item in observations if item.target_object_id in relevant_set}))
    requirement_targets = requirement.relevant_targets if requirement is not None else ()
    minimum_confidence = requirement.minimum_confidence if requirement is not None else 1.0
    maximum_contact_age_s = requirement.maximum_contact_age_s if requirement is not None else 0.0
    baseline_satisfied = {
        target.object_id
        for target in requirement_targets
        if ReconTargetSource.LOST_CONTACT not in target.sources
        and target.confidence is not None
        and target.confidence >= minimum_confidence
        and (target.information_age_s is None or target.information_age_s <= maximum_contact_age_s)
    }
    lost_relevant_set = {contact_targets[contact_id] for contact_id in lost_ids if contact_targets.get(contact_id) in relevant_set}
    lost_relevant_set.update(
        item.target_object_id for item in observations if item.lost_at_end and item.target_object_id in relevant_set
    )
    satisfied_relevant_set = (baseline_satisfied | set(observed_relevant)) - lost_relevant_set
    lost_relevant = tuple(sorted(lost_relevant_set))
    satisfied_relevant = tuple(sorted(satisfied_relevant_set))
    unknown_relevant = tuple(sorted(relevant_set - satisfied_relevant_set - lost_relevant_set))
    return ReconOutcome(
        auftrag_id=auftrag_id,
        intel_id=intel_id,
        mission_outcome=mission_outcome,
        assigned_opsgroup_ids=assigned_ops,
        assigned_group_ids=assigned_groups,
        started_time=lifecycle.get("started"),
        executing_time=executing_time,
        completed_time=completed_time,
        observations=observations,
        requirement=requirement,
        relevant_target_ids=relevant,
        observed_relevant_target_ids=observed_relevant,
        satisfied_relevant_target_ids=satisfied_relevant,
        lost_relevant_target_ids=lost_relevant,
        unknown_relevant_target_ids=unknown_relevant,
        event_history_complete=event_history_complete,
        command_ack=command_ack or {},
    )


__all__ = [
    "ReconContactObservation",
    "ReconOutcome",
    "ReconRelevantTarget",
    "ReconRequirement",
    "ReconTargetSource",
    "build_recon_outcome",
    "derive_recon_requirement",
]
