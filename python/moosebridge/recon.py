"""Event-based tactical assessment of MOOSE RECON missions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .models import IntelContact
from .outcomes import AuftragOutcome


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
    relevant_target_ids: tuple[str, ...] = ()
    observed_relevant_target_ids: tuple[str, ...] = ()
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

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "auftrag_id": self.auftrag_id,
            "intel_id": self.intel_id,
            "mission_outcome": self.mission_outcome.to_dict(),
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
    command_ack: dict[str, Any] | None = None,
    event_history_complete: bool = True,
) -> ReconOutcome:
    """Build a tactical RECON assessment from chronological bridge events."""

    assigned_ops = tuple(dict.fromkeys(str(value) for value in assigned_opsgroup_ids))
    assigned_groups = tuple(dict.fromkeys(str(value) for value in assigned_group_ids))
    assigned_group_set = set(assigned_groups)
    baseline = {str(value) for value in baseline_contact_ids}
    relevant = tuple(dict.fromkeys(str(value) for value in relevant_target_ids))
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

    for name, payload, event_time in contact_events:
        contact = IntelContact.from_payload(payload)
        contact_id = contact.object_id
        if not contact_id:
            continue
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
        detected_time = contact.detected_time if contact.detected_time is not None else event_time
        if state is None:
            state = {
                "contact_id": contact_id,
                "target_object_id": contact.target_object_id,
                "recce_unit_id": contact.recce_unit_id,
                "recce_group_id": contact.recce_group_id,
                "first_detected_time": detected_time,
                "last_detected_time": detected_time,
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
            state["threat_level"] = max(state["threat_level"], float(contact.threat_level or 0.0))
            state["detection_count"] += 1
            state["reacquired"] = state["reacquired"] or was_lost
            state["detected_during_executing"] = state["detected_during_executing"] or (
                executing_time is not None and event_time is not None and event_time >= executing_time
            )
            state["lost_at_end"] = False

    observations = tuple(ReconContactObservation(**state) for state in states.values())
    observed_relevant = tuple(sorted({item.target_object_id for item in observations if item.target_object_id in relevant_set}))
    lost_relevant = tuple(sorted({item.target_object_id for item in observations if item.lost_at_end and item.target_object_id in relevant_set}))
    unknown_relevant = tuple(sorted(relevant_set - set(observed_relevant)))
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
        relevant_target_ids=relevant,
        observed_relevant_target_ids=observed_relevant,
        lost_relevant_target_ids=lost_relevant,
        unknown_relevant_target_ids=unknown_relevant,
        event_history_complete=event_history_complete,
        command_ack=command_ack or {},
    )
