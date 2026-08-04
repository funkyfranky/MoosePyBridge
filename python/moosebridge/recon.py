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
class ReconCoveragePoint:
    """Known stationary point whose surroundings should be searched."""

    object_id: str
    weight: float = 1.0
    source: ReconTargetSource = ReconTargetSource.OBJECTIVE_COMPONENT

    def __post_init__(self) -> None:
        if not self.object_id.strip() or ":" not in self.object_id:
            raise ValueError("coverage point requires a stable bridge object id")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError("coverage point weight must be finite and non-negative")
        object.__setattr__(self, "object_id", self.object_id.strip())
        object.__setattr__(self, "source", ReconTargetSource(self.source))

    def to_dict(self) -> dict[str, Any]:
        return {"object_id": self.object_id, "weight": self.weight, "source": self.source.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReconCoveragePoint":
        return cls(
            object_id=str(data.get("object_id") or ""),
            weight=float(data.get("weight", 1.0)),
            source=ReconTargetSource(data.get("source") or ReconTargetSource.OBJECTIVE_COMPONENT.value),
        )


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
    coverage_points: tuple[ReconCoveragePoint, ...] = ()
    derive_targets: bool = True
    minimum_confidence: float = 0.7
    maximum_contact_age_s: float = 300.0
    area_buffer_m: float = 30_000.0
    minimum_area_coverage: float = 0.8
    minimum_component_coverage: float = 1.0

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
        if not 0.0 <= self.minimum_area_coverage <= 1.0:
            raise ValueError("minimum_area_coverage must be between zero and one")
        if not 0.0 <= self.minimum_component_coverage <= 1.0:
            raise ValueError("minimum_component_coverage must be between zero and one")
        targets = _merge_recon_targets(self.relevant_targets)
        point_index: dict[str, ReconCoveragePoint] = {}
        for item in self.coverage_points:
            previous = point_index.get(item.object_id)
            point_index[item.object_id] = (
                ReconCoveragePoint(item.object_id, max(previous.weight, item.weight), previous.source)
                if previous is not None
                else item
            )
        points = tuple(point_index.values())
        object.__setattr__(self, "area_object_id", area)
        object.__setattr__(self, "relevant_targets", targets)
        object.__setattr__(self, "coverage_points", points)

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
            "coverage_points": [item.to_dict() for item in self.coverage_points],
            "minimum_area_coverage": self.minimum_area_coverage,
            "minimum_component_coverage": self.minimum_component_coverage,
        }

    @classmethod
    def manual(cls, area_object_id: str, *target_ids: str, **kwargs: Any) -> "ReconRequirement":
        """Create a strictly manual requirement for tests or operator tasking."""

        kwargs.setdefault("minimum_area_coverage", 0.0)
        kwargs.setdefault("minimum_component_coverage", 0.0)
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
        raw_points = data.get("coverage_points") if isinstance(data.get("coverage_points"), list) else []
        return cls(
            area_object_id=str(data.get("area_object_id") or ""),
            relevant_targets=tuple(
                ReconRelevantTarget.from_dict(item) for item in raw_targets if isinstance(item, dict)
            ),
            coverage_points=tuple(
                ReconCoveragePoint.from_dict(item) for item in raw_points if isinstance(item, dict)
            ),
            derive_targets=bool(data.get("derive_targets", True)),
            minimum_confidence=float(data.get("minimum_confidence", 0.7)),
            maximum_contact_age_s=float(data.get("maximum_contact_age_s", 300.0)),
            area_buffer_m=float(data.get("area_buffer_m", 30_000.0)),
            minimum_area_coverage=float(data.get("minimum_area_coverage", 0.8)),
            minimum_component_coverage=float(data.get("minimum_component_coverage", 1.0)),
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
    coverage_points: list[ReconCoveragePoint] = []
    if derive_targets:
        for object_id in _object_id_values(goal.metadata.get("relevant_target_ids", ())):
            targets.append(ReconRelevantTarget(str(object_id), (ReconTargetSource.GOAL,)))
        coverage_points.extend(
            ReconCoveragePoint(component.object_id, component.weight, ReconTargetSource.OBJECTIVE_COMPONENT)
            for component in objective.components
        )
        coverage_points.extend(
            ReconCoveragePoint(object_id, 1.0, ReconTargetSource.GOAL)
            for object_id in _object_id_values(goal.metadata.get("recon_coverage_point_ids", ()))
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
        coverage_points=tuple(coverage_points),
        derive_targets=derive_targets,
        minimum_confidence=minimum_confidence,
        maximum_contact_age_s=maximum_contact_age_s,
        area_buffer_m=area_buffer_m,
    )


@dataclass(slots=True, frozen=True)
class ReconTrackSample:
    """One sampled DCS-local position of a RECON asset group."""

    group_id: str
    mission_time: float
    x: float
    z: float

    def to_dict(self) -> dict[str, Any]:
        return {"group_id": self.group_id, "mission_time": self.mission_time, "x": self.x, "z": self.z}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReconTrackSample":
        return cls(str(data.get("group_id") or ""), float(data.get("mission_time") or 0.0), float(data["x"]), float(data["z"]))


@dataclass(slots=True, frozen=True)
class ReconArea:
    """DCS-local circular or polygonal area used for coverage calculation."""

    object_id: str
    center_x: float | None = None
    center_z: float | None = None
    radius_m: float | None = None
    vertices: tuple[tuple[float, float], ...] = ()


@dataclass(slots=True, frozen=True)
class ReconSpatialCoverage:
    """Potentially searched area from optimistic sensor upper bounds."""

    available: bool
    area_object_id: str
    area_m2: float | None
    searched_area_m2: float | None
    area_coverage_ratio: float | None
    component_coverage_ratio: float | None
    covered_component_ids: tuple[str, ...]
    uncovered_component_ids: tuple[str, ...]
    tracked_group_ids: tuple[str, ...]
    unknown_sensor_group_ids: tuple[str, ...]
    sample_count: int
    sufficient: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "area_object_id": self.area_object_id,
            "area_m2": self.area_m2,
            "searched_area_m2": self.searched_area_m2,
            "area_coverage_ratio": self.area_coverage_ratio,
            "component_coverage_ratio": self.component_coverage_ratio,
            "covered_component_ids": list(self.covered_component_ids),
            "uncovered_component_ids": list(self.uncovered_component_ids),
            "tracked_group_ids": list(self.tracked_group_ids),
            "unknown_sensor_group_ids": list(self.unknown_sensor_group_ids),
            "sample_count": self.sample_count,
            "sufficient": self.sufficient,
            "interpretation": "potential_sensor_access_not_confirmed_detection",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReconSpatialCoverage":
        return cls(
            available=bool(data.get("available", False)),
            area_object_id=str(data.get("area_object_id") or ""),
            area_m2=float(data["area_m2"]) if data.get("area_m2") is not None else None,
            searched_area_m2=float(data["searched_area_m2"]) if data.get("searched_area_m2") is not None else None,
            area_coverage_ratio=float(data["area_coverage_ratio"]) if data.get("area_coverage_ratio") is not None else None,
            component_coverage_ratio=float(data["component_coverage_ratio"]) if data.get("component_coverage_ratio") is not None else None,
            covered_component_ids=tuple(str(item) for item in data.get("covered_component_ids", ())),
            uncovered_component_ids=tuple(str(item) for item in data.get("uncovered_component_ids", ())),
            tracked_group_ids=tuple(str(item) for item in data.get("tracked_group_ids", ())),
            unknown_sensor_group_ids=tuple(str(item) for item in data.get("unknown_sensor_group_ids", ())),
            sample_count=int(data.get("sample_count") or 0),
            sufficient=data.get("sufficient") if isinstance(data.get("sufficient"), bool) else None,
        )


def assess_recon_spatial_coverage(
    requirement: ReconRequirement,
    area: ReconArea | None,
    tracks: dict[str, tuple[ReconTrackSample, ...]],
    sensor_ranges_m: dict[str, float | None],
    component_positions: dict[str, tuple[float, float]],
) -> ReconSpatialCoverage:
    """Calculate optimistic sensor access over an area and known key points."""

    sample_count = sum(len(items) for items in tracks.values())
    unknown_groups = tuple(sorted(group_id for group_id in tracks if not sensor_ranges_m.get(group_id)))
    uncovered_points = tuple(item.object_id for item in requirement.coverage_points)

    def unavailable(area_id: str, area_m2: float | None = None, searched_m2: float | None = None) -> ReconSpatialCoverage:
        return ReconSpatialCoverage(
            False,
            area_id,
            area_m2,
            searched_m2,
            None,
            None,
            (),
            uncovered_points,
            (),
            unknown_groups,
            sample_count,
            None,
        )

    if area is None:
        return unavailable(requirement.area_object_id)
    try:
        from shapely.geometry import LineString, Point, Polygon
        from shapely.ops import unary_union
    except ImportError:
        return unavailable(area.object_id)

    if len(area.vertices) >= 3:
        area_geometry = Polygon(area.vertices)
    elif area.center_x is not None and area.center_z is not None and area.radius_m and area.radius_m > 0:
        area_geometry = Point(area.center_x, area.center_z).buffer(area.radius_m)
    else:
        return unavailable(area.object_id)
    if area_geometry.is_empty or not area_geometry.is_valid or area_geometry.area <= 0:
        return unavailable(area.object_id)

    footprints = []
    tracked: list[str] = []
    unknown: list[str] = []
    for group_id, samples in tracks.items():
        sensor_range = sensor_ranges_m.get(group_id)
        if sensor_range is None or sensor_range <= 0:
            unknown.append(group_id)
            continue
        coordinates = list(dict.fromkeys((sample.x, sample.z) for sample in samples))
        if not coordinates:
            continue
        route = Point(coordinates[0]) if len(coordinates) == 1 else LineString(coordinates)
        footprints.append(route.buffer(sensor_range))
        tracked.append(group_id)
    if not footprints:
        return unavailable(area.object_id, area_geometry.area, 0.0)

    footprint = unary_union(footprints)
    searched_area = area_geometry.intersection(footprint).area
    area_ratio = min(1.0, max(0.0, searched_area / area_geometry.area))
    point_weights = {item.object_id: item.weight for item in requirement.coverage_points}
    covered = tuple(sorted(object_id for object_id, position in component_positions.items() if object_id in point_weights and footprint.covers(Point(position))))
    uncovered = tuple(sorted(set(point_weights) - set(covered)))
    total_weight = sum(point_weights.values())
    covered_weight = sum(point_weights[object_id] for object_id in covered)
    component_ratio = covered_weight / total_weight if total_weight > 0 else None
    components_sufficient = component_ratio is None or component_ratio >= requirement.minimum_component_coverage
    sufficient = area_ratio >= requirement.minimum_area_coverage and components_sufficient
    return ReconSpatialCoverage(
        True,
        area.object_id,
        area_geometry.area,
        searched_area,
        area_ratio,
        component_ratio,
        covered,
        uncovered,
        tuple(sorted(tracked)),
        tuple(sorted(unknown)),
        sample_count,
        sufficient,
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReconContactObservation":
        return cls(
            contact_id=str(data.get("contact_id") or ""),
            target_object_id=str(data.get("target_object_id")) if data.get("target_object_id") else None,
            recce_unit_id=str(data.get("recce_unit_id")) if data.get("recce_unit_id") else None,
            recce_group_id=str(data.get("recce_group_id")) if data.get("recce_group_id") else None,
            first_detected_time=float(data["first_detected_time"]) if data.get("first_detected_time") is not None else None,
            last_detected_time=float(data["last_detected_time"]) if data.get("last_detected_time") is not None else None,
            reported_detected_time=float(data["reported_detected_time"]) if data.get("reported_detected_time") is not None else None,
            threat_level=float(data.get("threat_level") or 0.0),
            detection_count=int(data.get("detection_count") or 0),
            new_contact=bool(data.get("new_contact", False)),
            reacquired=bool(data.get("reacquired", False)),
            detected_during_executing=bool(data.get("detected_during_executing", False)),
            lost_at_end=bool(data.get("lost_at_end", False)),
        )


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
    spatial_coverage: ReconSpatialCoverage | None = None
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

        targets_satisfied = not self.unknown_relevant_target_ids and not self.lost_relevant_target_ids
        spatial_required = self.requirement is not None and (
            self.requirement.minimum_area_coverage > 0
            or bool(self.requirement.coverage_points) and self.requirement.minimum_component_coverage > 0
        )
        if self.spatial_coverage is not None and self.spatial_coverage.available:
            return targets_satisfied and self.spatial_coverage.sufficient is True and self.event_history_complete
        if spatial_required:
            return None
        if not self.relevant_target_ids:
            return None
        return targets_satisfied and self.event_history_complete

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
            "spatial_coverage": self.spatial_coverage.to_dict() if self.spatial_coverage else None,
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReconOutcome":
        """Restore a persisted tactical RECON assessment."""

        mission = data.get("mission_outcome") if isinstance(data.get("mission_outcome"), dict) else {}
        mission_outcome = AuftragOutcome(
            auftrag_id=str(mission.get("auftrag_id") or data.get("auftrag_id") or ""),
            mission_type=str(mission.get("mission_type")) if mission.get("mission_type") else None,
            status=str(mission.get("status")) if mission.get("status") else None,
            evaluated=bool(mission.get("evaluated", False)),
            success=mission.get("success") if isinstance(mission.get("success"), bool) else None,
            damage=float(mission["damage"]) if mission.get("damage") is not None else None,
            n_targets_initial=int(mission["n_targets_initial"]) if mission.get("n_targets_initial") is not None else None,
            n_targets_final=int(mission["n_targets_final"]) if mission.get("n_targets_final") is not None else None,
            n_destroyed=int(mission["n_destroyed"]) if mission.get("n_destroyed") is not None else None,
            n_kills=int(mission["n_kills"]) if mission.get("n_kills") is not None else None,
            n_elements=int(mission["n_elements"]) if mission.get("n_elements") is not None else None,
            n_casualties=int(mission["n_casualties"]) if mission.get("n_casualties") is not None else None,
            target_life=float(mission["target_life"]) if mission.get("target_life") is not None else None,
            category=str(mission.get("category")) if mission.get("category") else None,
        )
        raw_requirement = data.get("requirement") if isinstance(data.get("requirement"), dict) else None
        raw_spatial = data.get("spatial_coverage") if isinstance(data.get("spatial_coverage"), dict) else None
        return cls(
            auftrag_id=str(data.get("auftrag_id") or ""),
            intel_id=str(data.get("intel_id") or ""),
            mission_outcome=mission_outcome,
            assigned_opsgroup_ids=tuple(str(item) for item in data.get("assigned_opsgroup_ids", ())),
            assigned_group_ids=tuple(str(item) for item in data.get("assigned_group_ids", ())),
            started_time=float(data["started_time"]) if data.get("started_time") is not None else None,
            executing_time=float(data["executing_time"]) if data.get("executing_time") is not None else None,
            completed_time=float(data["completed_time"]) if data.get("completed_time") is not None else None,
            observations=tuple(
                ReconContactObservation.from_dict(item)
                for item in data.get("observations", ())
                if isinstance(item, dict)
            ),
            requirement=ReconRequirement.from_dict(raw_requirement) if raw_requirement else None,
            spatial_coverage=ReconSpatialCoverage.from_dict(raw_spatial) if raw_spatial else None,
            relevant_target_ids=tuple(str(item) for item in data.get("relevant_target_ids", ())),
            observed_relevant_target_ids=tuple(str(item) for item in data.get("observed_relevant_target_ids", ())),
            satisfied_relevant_target_ids=tuple(str(item) for item in data.get("satisfied_relevant_target_ids", ())),
            lost_relevant_target_ids=tuple(str(item) for item in data.get("lost_relevant_target_ids", ())),
            unknown_relevant_target_ids=tuple(str(item) for item in data.get("unknown_relevant_target_ids", ())),
            event_history_complete=bool(data.get("event_history_complete", False)),
        )


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
    spatial_coverage: ReconSpatialCoverage | None = None,
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
        spatial_coverage=spatial_coverage,
        relevant_target_ids=relevant,
        observed_relevant_target_ids=observed_relevant,
        satisfied_relevant_target_ids=satisfied_relevant,
        lost_relevant_target_ids=lost_relevant,
        unknown_relevant_target_ids=unknown_relevant,
        event_history_complete=event_history_complete,
        command_ack=command_ack or {},
    )


__all__ = [
    "ReconArea",
    "ReconContactObservation",
    "ReconCoveragePoint",
    "ReconOutcome",
    "ReconRelevantTarget",
    "ReconRequirement",
    "ReconTargetSource",
    "ReconTrackSample",
    "ReconSpatialCoverage",
    "assess_recon_spatial_coverage",
    "build_recon_outcome",
    "derive_recon_requirement",
]
