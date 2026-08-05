"""Small Python-owned diplomacy and coalition-doctrine model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Iterable

from .strategic import StrategicGoalAction, StrategicObjective, normalize_coalition


DIPLOMACY_AUDIT_TYPE = "strategic.diplomacy_state"
DIPLOMACY_STATE_SCHEMA_VERSION = 3


class RelationshipState(str, Enum):
    """Shared political state between two coalitions."""

    PEACE = "peace"
    TENSE = "tense"
    LIMITED_CONFLICT = "limited_conflict"
    WAR = "war"
    CEASEFIRE = "ceasefire"


class EscalationIncidentType(str, Enum):
    """Small set of observable events that can raise tensions."""

    BORDER_VIOLATION = "border_violation"
    WEAPON_FIRED = "weapon_fired"
    UNIT_HIT = "unit_hit"
    UNIT_DESTROYED = "unit_destroyed"
    STRATEGIC_OBJECT_ATTACKED = "strategic_object_attacked"
    OBJECTIVE_CAPTURED = "objective_captured"
    OPSZONE_CAPTURED = "opszone_captured"
    CEASEFIRE_VIOLATION = "ceasefire_violation"


DEFAULT_INCIDENT_WEIGHTS: dict[EscalationIncidentType, float] = {
    EscalationIncidentType.BORDER_VIOLATION: 5.0,
    EscalationIncidentType.WEAPON_FIRED: 8.0,
    EscalationIncidentType.UNIT_HIT: 12.0,
    EscalationIncidentType.UNIT_DESTROYED: 20.0,
    EscalationIncidentType.STRATEGIC_OBJECT_ATTACKED: 30.0,
    EscalationIncidentType.OBJECTIVE_CAPTURED: 60.0,
    EscalationIncidentType.OPSZONE_CAPTURED: 20.0,
    EscalationIncidentType.CEASEFIRE_VIOLATION: 40.0,
}

OPSZONE_CAPTURE_CONTEXT_MULTIPLIERS = {
    ("enemy_owned", "opposing_territory"): 1.0,
    ("enemy_owned", "no_mans_land"): 2.0 / 3.0,
    ("enemy_owned", "own_territory"): 0.5,
    ("neutral", "opposing_territory"): 0.5,
    ("neutral", "no_mans_land"): 0.25,
    ("neutral", "own_territory"): 0.1,
}

AIRBASE_CAPTURE_ESCALATION_POINTS = {
    "airdrome": {
        ("enemy_owned", "opposing_territory"): 60.0,
        ("enemy_owned", "no_mans_land"): 40.0,
        ("enemy_owned", "own_territory"): 30.0,
        ("neutral", "opposing_territory"): 30.0,
        ("neutral", "no_mans_land"): 15.0,
        ("neutral", "own_territory"): 5.0,
    },
    "heliport": {
        ("enemy_owned", "opposing_territory"): 15.0,
        ("enemy_owned", "no_mans_land"): 10.0,
        ("enemy_owned", "own_territory"): 7.5,
        ("neutral", "opposing_territory"): 7.5,
        ("neutral", "no_mans_land"): 5.0,
        ("neutral", "own_territory"): 2.0,
    },
}


def airbase_capture_multiplier(
    *,
    previous_coalition: str | None,
    capturing_coalition: str,
    territory_coalition: str | None,
    category: str | None,
) -> tuple[float, dict[str, object]]:
    """Return an explainable escalation multiplier for an airbase capture."""

    actor = normalize_coalition(capturing_coalition)
    previous = normalize_coalition(previous_coalition)
    territory = normalize_coalition(territory_coalition)
    if actor not in {"blue", "red"}:
        raise ValueError("capturing coalition must be blue or red")
    opponent = "red" if actor == "blue" else "blue"
    ownership_context = "enemy_owned" if previous == opponent else "neutral"
    if territory == opponent:
        territory_context = "opposing_territory"
    elif territory == actor:
        territory_context = "own_territory"
    else:
        territory_context = "no_mans_land"
    normalized_category = str(category or "").strip().lower()
    category_context = "heliport" if normalized_category in {"heliport", "helipad", "farp"} else "airdrome"
    points = AIRBASE_CAPTURE_ESCALATION_POINTS[category_context][
        (ownership_context, territory_context)
    ]
    base_points = DEFAULT_INCIDENT_WEIGHTS[EscalationIncidentType.OBJECTIVE_CAPTURED]
    return points / base_points, {
        "ownership_context": ownership_context,
        "territory_context": territory_context,
        "category_context": category_context,
        "base_points": base_points,
        "escalation_points": points,
    }


def opszone_capture_multiplier(
    *,
    reference_points: float,
    previous_coalition: str | None,
    capturing_coalition: str,
    territory_coalition: str | None,
) -> tuple[float, dict[str, object]]:
    """Return an explainable multiplier for capture of one strategic OPSZONE."""

    points = _capture_points(reference_points, "OPSZONE capture reference points")
    actor = normalize_coalition(capturing_coalition)
    previous = normalize_coalition(previous_coalition)
    territory = normalize_coalition(territory_coalition)
    if actor not in {"blue", "red"}:
        raise ValueError("capturing coalition must be blue or red")
    opponent = "red" if actor == "blue" else "blue"
    ownership_context = "enemy_owned" if previous == opponent else "neutral"
    if territory == opponent:
        territory_context = "opposing_territory"
    elif territory == actor:
        territory_context = "own_territory"
    else:
        territory_context = "no_mans_land"
    context_multiplier = OPSZONE_CAPTURE_CONTEXT_MULTIPLIERS[
        (ownership_context, territory_context)
    ]
    escalation_points = points * context_multiplier
    base_points = DEFAULT_INCIDENT_WEIGHTS[EscalationIncidentType.OPSZONE_CAPTURED]
    return escalation_points / base_points, {
        "ownership_context": ownership_context,
        "territory_context": territory_context,
        "reference_points": points,
        "context_multiplier": context_multiplier,
        "base_points": base_points,
        "escalation_points": escalation_points,
    }


@dataclass(slots=True, frozen=True)
class EscalationIncident:
    """One attributed incident between the relationship participants."""

    incident_id: str
    incident_type: EscalationIncidentType
    actor_coalition: str
    target_coalition: str
    mission_time: float | None = None
    reference_id: str | None = None
    confidence: float = 1.0
    multiplier: float = 1.0
    details: dict[str, object] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        incident_id = self.incident_id.strip()
        actor = normalize_coalition(self.actor_coalition) or ""
        target = normalize_coalition(self.target_coalition) or ""
        if not incident_id:
            raise ValueError("incident_id must not be empty")
        if actor not in {"blue", "red"} or target not in {"blue", "red"} or actor == target:
            raise ValueError("incident requires different blue and red coalitions")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("incident confidence must be between zero and one")
        if not math.isfinite(self.multiplier) or self.multiplier < 0:
            raise ValueError("incident multiplier must be finite and non-negative")
        if self.mission_time is not None and (not math.isfinite(self.mission_time) or self.mission_time < 0):
            raise ValueError("incident mission_time must be finite and non-negative")
        object.__setattr__(self, "incident_id", incident_id)
        object.__setattr__(self, "incident_type", EscalationIncidentType(self.incident_type))
        object.__setattr__(self, "actor_coalition", actor)
        object.__setattr__(self, "target_coalition", target)
        object.__setattr__(self, "reference_id", self.reference_id.strip() if self.reference_id else None)


@dataclass(slots=True, frozen=True)
class RelationshipTransitionProposal:
    """Auditable request to change a shared relationship state."""

    proposal_id: str
    from_state: RelationshipState
    to_state: RelationshipState
    reason: str
    mission_time: float | None = None
    automatic: bool = False


@dataclass(slots=True)
class LimitedConflictAuthorization:
    """Explicit geographic/objective boundary for limited offensive action."""

    objective_ids: set[str] = field(default_factory=set)
    territory_ids: set[str] = field(default_factory=set)

    def authorize_objective(self, objective_id: str) -> None:
        objective_id = objective_id.strip()
        if not objective_id:
            raise ValueError("objective_id must not be empty")
        self.objective_ids.add(objective_id)

    def authorize_territory(self, territory_id: str) -> None:
        territory_id = territory_id.strip()
        if not territory_id:
            raise ValueError("territory_id must not be empty")
        self.territory_ids.add(territory_id)

    def allows(self, objective: StrategicObjective) -> bool:
        if objective.objective_id in self.objective_ids:
            return True
        territory_id = str(objective.metadata.get("territory_id") or "").strip()
        return bool(
            objective.control_object_id in self.territory_ids
            or territory_id in self.territory_ids
        )

    def clear(self) -> None:
        self.objective_ids.clear()
        self.territory_ids.clear()


@dataclass(slots=True)
class CoalitionRelationship:
    """Shared relationship with one simple escalation score."""

    coalition_a: str = "blue"
    coalition_b: str = "red"
    state: RelationshipState = RelationshipState.PEACE
    escalation_score: float = 0.0
    automatic_transitions: bool = True
    incidents: list[EscalationIncident] = field(default_factory=list)
    pending_transition: RelationshipTransitionProposal | None = None
    limited_conflict: LimitedConflictAuthorization = field(default_factory=LimitedConflictAuthorization)
    incident_weights: dict[EscalationIncidentType, float] = field(
        default_factory=lambda: dict(DEFAULT_INCIDENT_WEIGHTS),
        repr=False,
    )
    default_opszone_capture_points: float = 20.0
    opszone_capture_points: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.coalition_a = normalize_coalition(self.coalition_a) or ""
        self.coalition_b = normalize_coalition(self.coalition_b) or ""
        if {self.coalition_a, self.coalition_b} != {"blue", "red"}:
            raise ValueError("relationship currently requires blue and red coalitions")
        self.state = RelationshipState(self.state)
        self.escalation_score = _bounded_score(self.escalation_score)
        self.default_opszone_capture_points = _capture_points(
            self.default_opszone_capture_points,
            "default OPSZONE capture points",
        )
        self.opszone_capture_points = {
            _opszone_id(object_id): _capture_points(points, "OPSZONE capture points")
            for object_id, points in self.opszone_capture_points.items()
        }

    def set_opszone_capture_points(self, object_id: str, points: float) -> float:
        """Set the strategic capture value for one OPSZONE."""

        value = _capture_points(points, "OPSZONE capture points")
        self.opszone_capture_points[_opszone_id(object_id)] = value
        return value

    def get_opszone_capture_points(self, object_id: str) -> float:
        """Return a zone override or the relationship-wide default value."""

        return self.opszone_capture_points.get(
            _opszone_id(object_id),
            self.default_opszone_capture_points,
        )

    def record_incident(self, incident: EscalationIncident) -> RelationshipTransitionProposal | None:
        """Record an incident and propose or apply the resulting escalation."""

        if {incident.actor_coalition, incident.target_coalition} != {self.coalition_a, self.coalition_b}:
            raise ValueError("incident coalitions do not belong to this relationship")
        if any(item.incident_id == incident.incident_id for item in self.incidents):
            return None
        self.incidents.append(incident)
        weight = self.incident_weights.get(incident.incident_type, 0.0)
        self.escalation_score = _bounded_score(
            self.escalation_score + weight * incident.confidence * incident.multiplier
        )
        proposed_state = self._state_for_score()
        if proposed_state is None or proposed_state is self.state:
            return None
        proposal = self.propose_transition(
            proposed_state,
            reason=f"escalation score reached {self.escalation_score:.1f} after {incident.incident_type.value}",
            mission_time=incident.mission_time,
            automatic=self.automatic_transitions,
        )
        if proposal.automatic:
            self.approve_transition(proposal.proposal_id)
        return proposal

    def propose_transition(
        self,
        to_state: RelationshipState | str,
        *,
        reason: str,
        mission_time: float | None = None,
        automatic: bool = False,
    ) -> RelationshipTransitionProposal:
        """Create one transition proposal without changing state."""

        target = RelationshipState(to_state)
        reason = reason.strip()
        if target is self.state:
            raise ValueError("relationship is already in the requested state")
        if not reason:
            raise ValueError("relationship transition requires a reason")
        proposal = RelationshipTransitionProposal(
            proposal_id=f"RELATIONSHIP:{self.coalition_a}-{self.coalition_b}:{len(self.incidents)}:{target.value}",
            from_state=self.state,
            to_state=target,
            reason=reason,
            mission_time=mission_time,
            automatic=automatic,
        )
        self.pending_transition = proposal
        return proposal

    def approve_transition(self, proposal_id: str) -> RelationshipState:
        """Approve the current proposal and apply its shared state."""

        proposal = self.pending_transition
        if proposal is None or proposal.proposal_id != proposal_id:
            raise ValueError("unknown or stale relationship transition proposal")
        self.state = proposal.to_state
        self.pending_transition = None
        return self.state

    def reject_transition(self, proposal_id: str) -> None:
        """Reject the current proposal without changing the escalation score."""

        if self.pending_transition is None or self.pending_transition.proposal_id != proposal_id:
            raise ValueError("unknown or stale relationship transition proposal")
        self.pending_transition = None

    def reduce_tension(self, amount: float) -> float:
        """Explicitly reduce the score; de-escalation remains a political choice."""

        if not math.isfinite(amount) or amount < 0:
            raise ValueError("tension reduction must be finite and non-negative")
        self.escalation_score = _bounded_score(self.escalation_score - amount)
        return self.escalation_score

    def responsibility(self, coalition: str) -> float:
        """Return accumulated attributed escalation weight for one coalition."""

        coalition = normalize_coalition(coalition) or ""
        if coalition not in {self.coalition_a, self.coalition_b}:
            raise ValueError("coalition does not belong to this relationship")
        return sum(
            self.incident_weights.get(item.incident_type, 0.0) * item.confidence * item.multiplier
            for item in self.incidents
            if item.actor_coalition == coalition
        )

    def allows_goal(
        self,
        action: StrategicGoalAction | str,
        objective: StrategicObjective,
    ) -> tuple[bool, str]:
        """Apply the relationship as a hard boundary before goal ranking."""

        action = StrategicGoalAction(action)
        if action in {StrategicGoalAction.DEFEND, StrategicGoalAction.PROTECT}:
            return True, "defensive goal is permitted"
        if self.state in {RelationshipState.PEACE, RelationshipState.TENSE, RelationshipState.CEASEFIRE}:
            return False, f"offensive goal is not permitted during {self.state.value}"
        if self.state is RelationshipState.LIMITED_CONFLICT:
            if self.limited_conflict.allows(objective):
                return True, "objective is authorized for limited conflict"
            return False, "objective is outside the limited-conflict authorization"
        return True, "offensive goal is permitted during war"

    def clear(self) -> None:
        """Restore peace while preserving configuration for a new mission."""

        self.state = RelationshipState.PEACE
        self.escalation_score = 0.0
        self.incidents.clear()
        self.pending_transition = None
        self.limited_conflict.clear()

    def _state_for_score(self) -> RelationshipState | None:
        if self.state is RelationshipState.WAR:
            return None
        if self.state is RelationshipState.CEASEFIRE:
            return RelationshipState.WAR if self.escalation_score >= 80 else None
        candidate = RelationshipState.PEACE
        if self.escalation_score >= 80:
            candidate = RelationshipState.WAR
        elif self.escalation_score >= 50:
            candidate = RelationshipState.LIMITED_CONFLICT
        elif self.escalation_score >= 20:
            candidate = RelationshipState.TENSE
        rank = {
            RelationshipState.PEACE: 0,
            RelationshipState.TENSE: 1,
            RelationshipState.LIMITED_CONFLICT: 2,
            RelationshipState.WAR: 3,
        }
        return candidate if rank[candidate] > rank[self.state] else None


class CoalitionDoctrinePreset(str, Enum):
    """Convenient strategic-character presets."""

    PASSIVE = "passive"
    DEFENSIVE = "defensive"
    BALANCED = "balanced"
    OFFENSIVE = "offensive"
    AGGRESSIVE = "aggressive"


@dataclass(slots=True, frozen=True)
class CoalitionDoctrine:
    """Small set of independent strategic behavior biases."""

    preset: CoalitionDoctrinePreset
    defense_bias: float
    offense_bias: float
    escalation_tolerance: float
    risk_tolerance: float
    force_preservation: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "preset", CoalitionDoctrinePreset(self.preset))
        for name in (
            "defense_bias",
            "offense_bias",
            "escalation_tolerance",
            "risk_tolerance",
            "force_preservation",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")

    @classmethod
    def from_preset(cls, preset: CoalitionDoctrinePreset | str) -> "CoalitionDoctrine":
        preset = CoalitionDoctrinePreset(preset)
        values = {
            CoalitionDoctrinePreset.PASSIVE: (0.7, 0.1, 0.9, 0.1, 0.9),
            CoalitionDoctrinePreset.DEFENSIVE: (1.0, 0.3, 0.7, 0.3, 0.8),
            CoalitionDoctrinePreset.BALANCED: (0.7, 0.7, 0.5, 0.5, 0.6),
            CoalitionDoctrinePreset.OFFENSIVE: (0.4, 1.0, 0.3, 0.7, 0.4),
            CoalitionDoctrinePreset.AGGRESSIVE: (0.2, 1.0, 0.1, 1.0, 0.2),
        }
        return cls(preset, *values[preset])


class CoalitionDoctrineRegistry:
    """Mutable mission-scoped doctrine assignment for each coalition."""

    def __init__(self) -> None:
        self._doctrines = {
            "blue": CoalitionDoctrine.from_preset(CoalitionDoctrinePreset.BALANCED),
            "red": CoalitionDoctrine.from_preset(CoalitionDoctrinePreset.BALANCED),
        }

    def get(self, coalition: str) -> CoalitionDoctrine:
        coalition = normalize_coalition(coalition) or ""
        try:
            return self._doctrines[coalition]
        except KeyError as exc:
            raise ValueError("doctrine currently requires coalition blue or red") from exc

    def set(
        self,
        coalition: str,
        doctrine: CoalitionDoctrine | CoalitionDoctrinePreset | str,
    ) -> CoalitionDoctrine:
        coalition = normalize_coalition(coalition) or ""
        if coalition not in self._doctrines:
            raise ValueError("doctrine currently requires coalition blue or red")
        item = doctrine if isinstance(doctrine, CoalitionDoctrine) else CoalitionDoctrine.from_preset(doctrine)
        self._doctrines[coalition] = item
        return item

    def clear(self) -> None:
        """Restore neutral balanced defaults for a new DCS mission."""

        self.__init__()


def diplomacy_state_to_dict(
    relationship: CoalitionRelationship,
    doctrines: CoalitionDoctrineRegistry,
    *,
    mission_generation: int,
) -> dict[str, Any]:
    """Serialize the shared mission diplomacy state for daemon persistence."""

    proposal = relationship.pending_transition
    return {
        "diplomacy_schema_version": DIPLOMACY_STATE_SCHEMA_VERSION,
        "mission_generation": int(mission_generation),
        "relationship": {
            "state": relationship.state.value,
            "escalation_score": relationship.escalation_score,
            "automatic_transitions": relationship.automatic_transitions,
            "default_opszone_capture_points": relationship.default_opszone_capture_points,
            "opszone_capture_points": dict(sorted(relationship.opszone_capture_points.items())),
            "incidents": [
                {
                    "incident_id": item.incident_id,
                    "incident_type": item.incident_type.value,
                    "actor_coalition": item.actor_coalition,
                    "target_coalition": item.target_coalition,
                    "mission_time": item.mission_time,
                    "reference_id": item.reference_id,
                    "confidence": item.confidence,
                    "multiplier": item.multiplier,
                    "details": dict(item.details),
                }
                for item in relationship.incidents
            ],
            "pending_transition": None if proposal is None else {
                "proposal_id": proposal.proposal_id,
                "from_state": proposal.from_state.value,
                "to_state": proposal.to_state.value,
                "reason": proposal.reason,
                "mission_time": proposal.mission_time,
                "automatic": proposal.automatic,
            },
            "limited_conflict": {
                "objective_ids": sorted(relationship.limited_conflict.objective_ids),
                "territory_ids": sorted(relationship.limited_conflict.territory_ids),
            },
        },
        "doctrines": {
            coalition: _doctrine_to_dict(doctrines.get(coalition))
            for coalition in ("blue", "red")
        },
    }


def apply_diplomacy_state(
    payload: dict[str, Any],
    relationship: CoalitionRelationship,
    doctrines: CoalitionDoctrineRegistry,
) -> None:
    """Replace local diplomacy objects from a validated daemon snapshot."""

    relation = payload.get("relationship") if isinstance(payload.get("relationship"), dict) else {}
    relationship.state = RelationshipState(relation.get("state", RelationshipState.PEACE.value))
    relationship.escalation_score = _bounded_score(float(relation.get("escalation_score") or 0.0))
    if int(payload.get("diplomacy_schema_version") or 1) < 2:
        relationship.automatic_transitions = True
    else:
        relationship.automatic_transitions = bool(relation.get("automatic_transitions", True))
    relationship.default_opszone_capture_points = _capture_points(
        relation.get("default_opszone_capture_points", 20.0),
        "default OPSZONE capture points",
    )
    configured_opszones = relation.get("opszone_capture_points")
    relationship.opszone_capture_points = {
        _opszone_id(object_id): _capture_points(points, "OPSZONE capture points")
        for object_id, points in (
            configured_opszones.items() if isinstance(configured_opszones, dict) else ()
        )
    }
    relationship.incidents = [
        EscalationIncident(
            incident_id=str(item.get("incident_id") or ""),
            incident_type=EscalationIncidentType(item.get("incident_type")),
            actor_coalition=str(item.get("actor_coalition") or ""),
            target_coalition=str(item.get("target_coalition") or ""),
            mission_time=float(item["mission_time"]) if item.get("mission_time") is not None else None,
            reference_id=str(item.get("reference_id") or "") or None,
            confidence=float(item.get("confidence", 1.0)),
            multiplier=float(item.get("multiplier", 1.0)),
            details=dict(item.get("details") or {}),
        )
        for item in relation.get("incidents", [])
        if isinstance(item, dict)
    ]
    pending = relation.get("pending_transition")
    relationship.pending_transition = (
        RelationshipTransitionProposal(
            proposal_id=str(pending.get("proposal_id") or ""),
            from_state=RelationshipState(pending.get("from_state")),
            to_state=RelationshipState(pending.get("to_state")),
            reason=str(pending.get("reason") or ""),
            mission_time=float(pending["mission_time"]) if pending.get("mission_time") is not None else None,
            automatic=bool(pending.get("automatic", False)),
        )
        if isinstance(pending, dict)
        else None
    )
    if relationship.automatic_transitions and relationship.pending_transition is not None:
        relationship.approve_transition(relationship.pending_transition.proposal_id)
    authorization = relation.get("limited_conflict") if isinstance(relation.get("limited_conflict"), dict) else {}
    relationship.limited_conflict.objective_ids = {str(value) for value in authorization.get("objective_ids", [])}
    relationship.limited_conflict.territory_ids = {str(value) for value in authorization.get("territory_ids", [])}
    for coalition in ("blue", "red"):
        doctrine = payload.get("doctrines", {}).get(coalition) if isinstance(payload.get("doctrines"), dict) else None
        if isinstance(doctrine, dict):
            doctrines.set(
                coalition,
                CoalitionDoctrine(
                    preset=CoalitionDoctrinePreset(doctrine.get("preset")),
                    defense_bias=float(doctrine.get("defense_bias")),
                    offense_bias=float(doctrine.get("offense_bias")),
                    escalation_tolerance=float(doctrine.get("escalation_tolerance")),
                    risk_tolerance=float(doctrine.get("risk_tolerance")),
                    force_preservation=float(doctrine.get("force_preservation")),
                ),
            )


def _doctrine_to_dict(doctrine: CoalitionDoctrine) -> dict[str, Any]:
    return {
        "preset": doctrine.preset.value,
        "defense_bias": doctrine.defense_bias,
        "offense_bias": doctrine.offense_bias,
        "escalation_tolerance": doctrine.escalation_tolerance,
        "risk_tolerance": doctrine.risk_tolerance,
        "force_preservation": doctrine.force_preservation,
    }


@dataclass(slots=True)
class _BorderViolationState:
    group_id: str
    territory_id: str
    entered_mission_time: float
    reported: bool = False


class BorderViolationTracker:
    """Emit one incident after a ground group remains across a border."""

    def __init__(self, tolerance_s: float = 60.0) -> None:
        if not math.isfinite(tolerance_s) or tolerance_s < 0:
            raise ValueError("border violation tolerance must be finite and non-negative")
        self.tolerance_s = float(tolerance_s)
        self._active: dict[tuple[str, str], _BorderViolationState] = {}
        self._last_mission_time: float | None = None

    @property
    def active_violations(self) -> tuple[tuple[str, str, float, bool], ...]:
        return tuple(
            (item.group_id, item.territory_id, item.entered_mission_time, item.reported)
            for item in sorted(self._active.values(), key=lambda value: (value.group_id, value.territory_id))
        )

    def update(
        self,
        groups: Iterable[dict[str, Any]],
        territories: Iterable[Any],
        *,
        mission_time: float | None,
    ) -> tuple[EscalationIncident, ...]:
        """Update continuous incursions from mirrored state and DCS time."""

        if mission_time is None:
            return ()
        if self._last_mission_time is not None and mission_time < self._last_mission_time:
            self.clear()
        self._last_mission_time = mission_time
        regions = tuple(_territory_region(item) for item in territories)
        regions = tuple(item for item in regions if item is not None)
        present: set[tuple[str, str]] = set()
        incidents: list[EscalationIncident] = []
        for group in groups:
            group_id = str(group.get("object_id") or "").strip()
            coalition = normalize_coalition(group.get("coalition"))
            category = str(group.get("category") or "").strip().lower().replace("_", " ")
            if (
                not group_id
                or coalition not in {"blue", "red"}
                or group.get("alive") is not True
                or group.get("active") is not True
                or category not in {"ground", "ground unit", "ground units"}
            ):
                continue
            try:
                x = float(group["x"])
                z = float(group["z"])
            except (KeyError, TypeError, ValueError):
                continue
            region = next(
                (
                    item
                    for item in regions
                    if item[2] != coalition and _point_in_polygon(x, z, item[3])
                ),
                None,
            )
            if region is None:
                continue
            territory_id, territory_name, territory_coalition, _ = region
            key = (group_id, territory_id)
            present.add(key)
            state = self._active.get(key)
            if state is None:
                state = _BorderViolationState(group_id, territory_id, mission_time)
                self._active[key] = state
            elapsed = mission_time - state.entered_mission_time
            if state.reported or elapsed < self.tolerance_s:
                continue
            state.reported = True
            incidents.append(
                EscalationIncident(
                    incident_id=(
                        f"INCIDENT:BORDER:{group_id}:{territory_id}:"
                        f"{state.entered_mission_time:.3f}"
                    ),
                    incident_type=EscalationIncidentType.BORDER_VIOLATION,
                    actor_coalition=coalition,
                    target_coalition=territory_coalition,
                    mission_time=mission_time,
                    reference_id=group_id,
                    details={
                        "group_id": group_id,
                        "territory_id": territory_id,
                        "territory_name": territory_name,
                        "entered_mission_time": state.entered_mission_time,
                        "duration_s": elapsed,
                    },
                )
            )
        for key in set(self._active).difference(present):
            del self._active[key]
        return tuple(incidents)

    def clear(self) -> None:
        self._active.clear()
        self._last_mission_time = None


def _territory_region(territory: Any) -> tuple[str, str, str, tuple[tuple[float, float], ...]] | None:
    territory_id = str(getattr(territory, "object_id", "") or "").strip()
    coalition = normalize_coalition(getattr(territory, "coalition", None))
    vertices = tuple(
        (float(vertex.x), float(vertex.z))
        for vertex in getattr(territory, "vertices", ())
        if getattr(vertex, "x", None) is not None and getattr(vertex, "z", None) is not None
    )
    if not territory_id or coalition not in {"blue", "red"} or len(vertices) < 3:
        return None
    name = str(getattr(territory, "name", None) or getattr(territory, "dcs_name", None) or territory_id)
    return territory_id, name, coalition, vertices


def _point_in_polygon(x: float, z: float, vertices: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    previous_x, previous_z = vertices[-1]
    for current_x, current_z in vertices:
        crosses = (current_z > z) != (previous_z > z)
        if crosses:
            boundary_x = (previous_x - current_x) * (z - current_z) / (previous_z - current_z) + current_x
            if x < boundary_x:
                inside = not inside
        previous_x, previous_z = current_x, current_z
    return inside


def _bounded_score(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("escalation score must be finite")
    return min(100.0, max(0.0, float(value)))


def _capture_points(value: object, name: str) -> float:
    try:
        points = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite non-negative number") from exc
    if not math.isfinite(points) or points < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return points


def _opszone_id(object_id: object) -> str:
    value = str(object_id or "").strip()
    if not value.startswith("OPSZONE:") or not value.removeprefix("OPSZONE:").strip():
        raise ValueError("OPSZONE id must use OPSZONE:<name>")
    return value


__all__ = [
    "AIRBASE_CAPTURE_ESCALATION_POINTS",
    "OPSZONE_CAPTURE_CONTEXT_MULTIPLIERS",
    "CoalitionDoctrine",
    "CoalitionDoctrinePreset",
    "CoalitionDoctrineRegistry",
    "CoalitionRelationship",
    "BorderViolationTracker",
    "DEFAULT_INCIDENT_WEIGHTS",
    "DIPLOMACY_AUDIT_TYPE",
    "DIPLOMACY_STATE_SCHEMA_VERSION",
    "EscalationIncident",
    "EscalationIncidentType",
    "LimitedConflictAuthorization",
    "RelationshipState",
    "RelationshipTransitionProposal",
    "airbase_capture_multiplier",
    "opszone_capture_multiplier",
    "apply_diplomacy_state",
    "diplomacy_state_to_dict",
]
