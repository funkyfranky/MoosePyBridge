"""Small local SDK wrapper for embedding MOOSE Bridge commands in Python tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
import math
from typing import Any

from shapely.geometry import Point, shape

from .ammunition import DcsWeaponFlag, TaskWeaponSelection, UnitAmmunition, WeaponRole, select_task_weapon
from .auftraege import AuftragCommand, AuftragEvent
from .clock import DcsTime
from .dcs_events import DestroyedObjectEvent, KillEvent
from .debug_overlay import DcsRoadRoute, DcsSurfacePoint, DebugMarkup, DebugMarkupPoint, RoadPointMatch, validate_debug_overlay
from .infrastructure_sites import (
    GeographicSurveyPoint,
    InfrastructureSite,
    SceneryObjectResolution,
    SceneryObjectSnapshot,
    ScenerySurvey,
    TheaterInfrastructureSites,
)
from .scenery_verification import SceneryVerificationFeature
from .strategic_verification import (
    InfrastructureStateAssessment,
    ObservedDcsObject,
    StrategicSiteVerification,
    assess_infrastructure_state,
)
from .diplomacy import (
    BorderViolationTracker,
    CoalitionDoctrine,
    CoalitionDoctrinePreset,
    CoalitionDoctrineRegistry,
    CoalitionRelationship,
    DIPLOMACY_AUDIT_TYPE,
    DIPLOMACY_STATE_SCHEMA_VERSION,
    EscalationIncident,
    EscalationIncidentType,
    RelationshipState,
    RelationshipTransitionProposal,
    airbase_capture_multiplier,
    opszone_capture_multiplier,
    apply_diplomacy_state,
    diplomacy_state_to_dict,
)
from .auftrag_specs import auftrag_action_suffix
from .capabilities import (
    GroupCapabilities,
    GroupInfluence,
    UnitCapabilities,
    UnitInfluence,
    build_group_capabilities,
    build_group_influence,
    build_unit_capabilities,
    build_unit_influence,
)
from .intents import auftrag_command_params_from_recommendation
from .intelligence import (
    InformationRequirement,
    InformationRequirementEvent,
    InformationRequirementRegistry,
    InformationRequirementStatus,
)
from .ground_mobility import (
    GroundMobilityNetwork,
    GroundMobilityProfile,
    TRACKED_GROUND_PROFILE,
)
from .legions import Cohort, Commander, Legion
from .models import Auftrag, Intel, IntelCluster, IntelContact, OpsGroup, OpsZone, Territory
from .mission_resolver import StrategicMissionResolver
from .outcomes import AuftragOutcome
from .recon import (
    ReconArea,
    ReconOutcome,
    ReconRequirement,
    RECON_EXECUTION_AUDIT_TYPE,
    ReconSpatialCoverage,
    ReconTrackSample,
    ReconTrackingSession,
    assess_recon_spatial_coverage,
    build_recon_outcome,
    derive_recon_requirement,
)
from .operational import (
    OperationalPlan,
    OperationalPlanAssessment,
    OperationalPlanRegistry,
    OperationalPlanStatus,
)
from .operational_execution import (
    OperationalPlanAbortResult,
    OperationalPlanReconciliation,
    OperationalPlanExecution,
    OperationalPlanExecutor,
    PlanAbortScope,
    PlanExecutionCallback,
)
from .operational_planner import RuleBasedOperationalPlanner
from .operational_audit import RestoredOperationalPlan
from .pictures import GlobalPicture, TacticalPicture
from .protocol import BridgeCommand
from .server import DcsMissionEndedError, MooseBridgeServer
from .sensor_ranges import (
    DEFAULT_SENSOR_RANGE_REGISTRY,
    SensorDetectionType,
    SensorRangeProfile,
    SensorRangeRegistry,
    SensorTargetDomain,
)
from .state import MooseBridgeState
from .strategic_feedback import (
    StrategicFeedbackAction,
    StrategicFeedbackDecision,
    StrategicFeedbackEvent,
    StrategicFeedbackMonitor,
    StrategicFeedbackPolicy,
)
from .strategic_selection import StrategicGoalPortfolio, StrategicGoalPortfolioSelector
from .strategic_scope import (
    StrategicScopeConfig,
    StrategicTerritoryScope,
    build_strategic_territory_scope,
)
from .strategic_objectives import (
    StrategicObjectiveGenerationConfig,
    StrategicObjectiveGenerationResult,
    generate_strategic_objectives,
)
from .strategic_verification import StrategicVerificationRegistry
from .strategic_goals import (
    StrategicGoalGenerationConfig,
    StrategicGoalGenerationResult,
    generate_strategic_goals,
)
from .settlements import TheaterSettlements
from .railway_infrastructure import TheaterRailwayInfrastructure
from .transport_infrastructure import TheaterTransportInfrastructure
from .strategic import (
    ObjectiveEvent,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalEvent,
    StrategicGoalRegistry,
    StrategicObjective,
    StrategicObjectiveRegistry,
    component_health,
    effective_component_health,
    normalize_coalition,
)
from .weapon_ranges import DEFAULT_WEAPON_RANGE_REGISTRY, RangeSource, WeaponRangeProfile, WeaponRangeRegistry

SMOKE_COLORS = {"red", "green", "blue", "orange", "white"}
COORDINATE_FORMATS = {"xyz", "ll", "latlon", "latlong", "mgrs", "all"}
DRAW_ZONE_COLORS = {"red", "green", "blue", "yellow", "orange", "white", "black", "grey", "gray"}
DRAW_ZONE_COALITIONS = {"all", "neutral", "red", "blue", "-1", "0", "1", "2"}
DRAW_ZONE_LINE_TYPES = {
    "none": 0,
    "solid": 1,
    "dashed": 2,
    "dotted": 3,
    "dotdash": 4,
    "dot-dash": 4,
    "dot_dash": 4,
    "longdash": 5,
    "long-dash": 5,
    "long_dash": 5,
    "twodash": 6,
    "two-dash": 6,
    "two_dash": 6,
}
SNAPSHOT_KINDS = {
    "groups",
    "units",
    "ammunition",
    "statics",
    "airbases",
    "zones",
    "territories",
    "objects",
    "opszones",
    "opsgroups",
    "auftraege",
    "legions",
    "commanders",
    "cohorts",
    "intels",
    "intel_contacts",
    "intel_clusters",
}


@dataclass(slots=True, frozen=True)
class CoordinateResult:
    """Resolved object coordinates returned by ``object.coords``."""

    object_id: str
    format: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    mgrs: str | None = None
    raw: dict[str, Any] | None = None
    ack: dict[str, Any] | None = None

    @classmethod
    def from_ack(cls, ack: dict[str, Any]) -> "CoordinateResult":
        """Build a coordinate result from a successful ACK."""

        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        return cls(
            object_id=str(result.get("object_id") or ""),
            format=str(result.get("format") or "xyz"),
            x=_optional_float(result.get("x")),
            y=_optional_float(result.get("y")),
            z=_optional_float(result.get("z")),
            latitude=_optional_float(result.get("latitude")),
            longitude=_optional_float(result.get("longitude")),
            mgrs=str(result.get("mgrs")) if result.get("mgrs") is not None else None,
            raw=result,
            ack=ack,
        )


@dataclass(slots=True, frozen=True)
class GeographicPoint:
    """One DCS-local point converted to WGS84 by DCS."""

    x: float
    y: float
    z: float
    latitude: float
    longitude: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "GeographicPoint":
        """Build a converted point from a bridge result payload."""

        values = {
            "x": _optional_float(payload.get("x")),
            "y": _optional_float(payload.get("y")),
            "z": _optional_float(payload.get("z")),
            "latitude": _optional_float(payload.get("latitude")),
            "longitude": _optional_float(payload.get("longitude")),
        }
        if any(value is None for value in values.values()):
            raise ValueError("Converted point is missing x/y/z or latitude/longitude")
        return cls(**values)  # type: ignore[arg-type]


@dataclass(slots=True, frozen=True)
class DistanceResult:
    """Distance between two resolved DCS objects."""

    object_id_a: str
    object_id_b: str
    distance_m: float
    distance_km: float
    distance_nm: float
    raw: dict[str, Any] | None = None
    ack: dict[str, Any] | None = None

    @classmethod
    def from_ack(cls, ack: dict[str, Any]) -> "DistanceResult":
        """Build a distance result from a successful ACK."""

        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        return cls(
            object_id_a=str(result.get("object_id_a") or ""),
            object_id_b=str(result.get("object_id_b") or ""),
            distance_m=float(result.get("distance_m") or 0.0),
            distance_km=float(result.get("distance_km") or 0.0),
            distance_nm=float(result.get("distance_nm") or 0.0),
            raw=result,
            ack=ack,
        )


@dataclass(slots=True, frozen=True)
class NearestResult:
    """One snapshot item ranked by distance from a target object."""

    object_id: str
    distance_m: float
    distance_nm: float
    item: dict[str, Any]


def _ownership_bridge_event(objective: StrategicObjective) -> str:
    """Return the narrow bridge event stream authoritative for an objective."""

    if objective.ownership_policy is OwnershipPolicy.DCS_MANAGED:
        return "airbase.coalition_changed"
    if objective.ownership_policy is OwnershipPolicy.MOOSE_MANAGED:
        return "opszone.*"
    if objective.ownership_policy is OwnershipPolicy.TERRITORY_INHERITED:
        return "territory.coalition_changed"
    raise ValueError(f"Fixed objective has no external ownership event: {objective.objective_id}")


def _optional_float(value: Any) -> float | None:
    """Return a float or ``None`` for absent/non-numeric values."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _incident_mission_time(value: float | None) -> str:
    """Return stable DCS-time text for semantic incident identities."""

    return "unknown" if value is None else f"{value:.3f}"


def _territory_at_point(
    territories: Iterable[Territory],
    x: float | None,
    z: float | None,
) -> Territory | None:
    """Return the first declared territory containing a DCS-local point."""

    if x is None or z is None:
        return None
    for territory in territories:
        vertices = tuple((vertex.x, vertex.z) for vertex in territory.vertices)
        if len(vertices) >= 3:
            inside = False
            previous_x, previous_z = vertices[-1]
            for current_x, current_z in vertices:
                if (current_z > z) != (previous_z > z):
                    boundary_x = (
                        (previous_x - current_x) * (z - current_z)
                        / (previous_z - current_z)
                        + current_x
                    )
                    if x < boundary_x:
                        inside = not inside
                previous_x, previous_z = current_x, current_z
            if inside:
                return territory
        elif (
            territory.x is not None
            and territory.z is not None
            and territory.radius is not None
            and math.hypot(x - territory.x, z - territory.z) <= territory.radius
        ):
            return territory
    return None


class MooseBridgeCommandError(RuntimeError):
    """Raised when DCS rejects a bridge command.

    :param ack: ACK payload returned by DCS.
    """

    def __init__(self, ack: dict[str, Any]) -> None:
        self.ack = ack
        super().__init__(str(ack.get("error") or "DCS command failed"))


class MooseBridgeAuftragTimeoutError(TimeoutError):
    """Raised when an AUFTRAG does not produce an evaluation summary in time."""


class MooseBridgeAuftragNotFoundError(RuntimeError):
    """Raised when an AUFTRAG is never observed in snapshots."""


def require_ok(ack: dict[str, Any]) -> dict[str, Any]:
    """Validate that a DCS ACK accepted the command.

    :param ack: ACK payload returned by DCS.
    :returns: The original ACK payload if it is successful.
    :raises MooseBridgeCommandError: If DCS returned ``ok=false``.
    """

    if not ack.get("ok", False):
        raise MooseBridgeCommandError(ack)
    return ack


def validate_smoke_color(color: str) -> str:
    """Validate and normalize a smoke color.

    :param color: Requested smoke color.
    :returns: Lower-case smoke color.
    :raises ValueError: If the color is unsupported.
    """

    normalized = color.lower().strip()
    if normalized not in SMOKE_COLORS:
        raise ValueError(f"Unsupported smoke color: {color!r}. Expected one of {sorted(SMOKE_COLORS)}")
    return normalized


def validate_coordinate_format(format: str) -> str:
    """Validate and normalize a coordinate output format."""

    normalized = format.lower().strip()
    if normalized not in COORDINATE_FORMATS:
        raise ValueError(f"Unsupported coordinate format: {format!r}. Expected one of {sorted(COORDINATE_FORMATS)}")
    if normalized in {"latlon", "latlong"}:
        return "ll"
    return normalized


def validate_draw_zone_color(color: str | None) -> str | None:
    """Validate and normalize an optional DrawZone color name."""

    if color is None:
        return None
    normalized = color.lower().strip()
    if normalized not in DRAW_ZONE_COLORS:
        raise ValueError(f"Unsupported DrawZone color: {color!r}. Expected one of {sorted(DRAW_ZONE_COLORS)}")
    return normalized


def validate_draw_zone_coalition(coalition: str | int) -> str | int:
    """Validate a DrawZone coalition value."""

    if isinstance(coalition, int):
        if coalition in {-1, 0, 1, 2}:
            return coalition
        raise ValueError("DrawZone coalition integer must be one of -1, 0, 1, 2")
    normalized = coalition.lower().strip()
    if normalized not in DRAW_ZONE_COALITIONS:
        raise ValueError(f"Unsupported DrawZone coalition: {coalition!r}. Expected one of {sorted(DRAW_ZONE_COALITIONS)}")
    return normalized


def normalize_draw_zone_line_type(line_type: str | int | None) -> int | None:
    """Normalize an optional MOOSE DrawZone line type."""

    if line_type is None:
        return None
    if isinstance(line_type, int):
        value = line_type
    else:
        key = line_type.lower().strip()
        if key in DRAW_ZONE_LINE_TYPES:
            value = DRAW_ZONE_LINE_TYPES[key]
        else:
            try:
                value = int(key)
            except ValueError as exc:
                raise ValueError(f"Unsupported DrawZone line type: {line_type!r}") from exc
    if value < 0 or value > 6:
        raise ValueError("DrawZone line type must be in range 0..6")
    return value


def clean_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return params without ``None`` values."""

    return {key: value for key, value in params.items() if value is not None}


def point_from_item(item: dict[str, Any]) -> tuple[float, float] | None:
    """Return an x/z point from a snapshot item."""

    try:
        return float(item["x"]), float(item["z"])
    except (KeyError, TypeError, ValueError):
        return None


def item_matches(
    item: dict[str, Any],
    *,
    coalition: str | None = None,
    alive: bool | None = None,
    active: bool | None = None,
    contains: str | None = None,
) -> bool:
    """Return whether a snapshot item matches common SDK filters."""

    if coalition is not None:
        value = item.get("coalition") or item.get("coalition_name") or item.get("owner_current_name")
        if str(value or "").lower() != coalition.lower():
            return False
    if alive is not None and bool(item.get("alive", False)) is not alive:
        return False
    if active is not None and bool(item.get("active", False)) is not active:
        return False
    if contains is not None:
        fields = ("object_id", "dcs_name", "name", "group_name", "zone_name", "airbase_name", "unit_type", "dcs_type", "type", "category")
        text = " ".join(str(item.get(field) or "") for field in fields).lower()
        if contains.lower() not in text:
            return False
    return True


def auftrag_action_for_mission_type(mission_type: str) -> str:
    """Return the bridge command action for an AUFTRAG mission type.

    :param mission_type: MOOSE mission type such as ``BAI`` or ``Bombing``.
    :returns: Bridge command action string.
    """

    return f"auftrag.create_{auftrag_action_suffix(mission_type)}"


def build_recommended_auftrag_command_params(recommendation: Any) -> dict[str, Any]:
    """Build flat Lua command parameters from an AUFTRAG recommendation.

    :param recommendation: Recommendation object with ``to_dict``.
    :returns: Flat command parameter dictionary without null-valued fields.
    """

    return auftrag_command_params_from_recommendation(recommendation)


def auftrag_id_from_ack(ack: dict[str, Any]) -> str | None:
    """Return the created AUFTRAG id from an ACK payload."""

    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    value = result.get("auftrag_id")
    if value is None or value == "":
        return None
    return str(value)


def mission_id_from_snapshot(mission: Auftrag) -> str:
    """Return the stable id from a mirrored mission object."""

    return mission.object_id


def auftrag_outcome_from_event(event: dict[str, Any]) -> AuftragOutcome:
    """Build an AUFTRAG outcome from an ``auftrag.evaluated`` event."""

    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    auftrag_payload = payload.get("auftrag") if isinstance(payload.get("auftrag"), dict) else {}
    snapshot = dict(auftrag_payload)
    snapshot.setdefault("object_id", payload.get("auftrag_id"))
    snapshot.setdefault("type", payload.get("auftrag_type"))
    snapshot.setdefault("status", payload.get("status"))
    snapshot.setdefault("summary", payload.get("summary"))
    snapshot["_event_id"] = event.get("id")
    snapshot["_event_mission_time"] = event.get("mission_time")
    return AuftragOutcome.from_snapshot(snapshot)


def _same_coalition(value: str | None, coalition: str) -> bool:
    """Return whether a snapshot coalition value matches a requested coalition."""

    return str(value or "").lower() == coalition.lower()


def _unique_missions(missions: Iterable[Auftrag]) -> list[Auftrag]:
    """Return missions once, preserving insertion order."""

    result: list[Auftrag] = []
    seen: set[str] = set()
    for mission in missions:
        if mission.object_id in seen:
            continue
        seen.add(mission.object_id)
        result.append(mission)
    return result


async def maybe_call_auftrag_status_callback(
    callback: Callable[[AuftragEvent], Any | Awaitable[Any]] | None,
    event: AuftragEvent,
) -> None:
    """Call an optional sync or async AUFTRAG status callback."""

    if callback is None:
        return
    result = callback(event)
    if isinstance(result, Awaitable):
        await result


def is_evaluated_auftrag_snapshot(snapshot: dict[str, Any]) -> bool:
    """Return whether an AUFTRAG snapshot contains MOOSE's summary table.

    :param snapshot: Raw AUFTRAG snapshot.
    :returns: ``True`` when ``summary`` is present.
    """

    return isinstance(snapshot.get("summary"), dict)


class MooseBridgeClient:
    """High-level SDK facade backed by a local ``MooseBridgeServer`` instance.

    :param server: Running bridge server instance.
    :param strategic_shortfall_timeout_s: DCS-time duration before an asset
        shortfall produces a persistent replanning advisory.
    :param border_violation_tolerance_s: Continuous DCS-time duration inside
        hostile territory before an escalation incident is recorded.
    :param ground_mobility: Optional preloaded strategic ground network used for
        ground-asset feasibility, route distance, and ETA scoring.
    """

    def __init__(
        self,
        server: MooseBridgeServer,
        *,
        weapon_ranges: WeaponRangeRegistry | None = None,
        sensor_ranges: SensorRangeRegistry | None = None,
        ground_mobility: GroundMobilityNetwork | None = None,
        ground_mobility_profile: GroundMobilityProfile = TRACKED_GROUND_PROFILE,
        strategic_shortfall_timeout_s: float = 300.0,
        border_violation_tolerance_s: float = 60.0,
        strategic_scope_config: StrategicScopeConfig | None = None,
    ) -> None:
        self.server = server
        self.weapon_range_registry = weapon_ranges or DEFAULT_WEAPON_RANGE_REGISTRY
        self.sensor_range_registry = sensor_ranges or DEFAULT_SENSOR_RANGE_REGISTRY
        self.mission_resolver = StrategicMissionResolver(
            ground_mobility=ground_mobility,
            ground_mobility_profile=ground_mobility_profile,
        )
        self.objectives = StrategicObjectiveRegistry()
        self.goals = StrategicGoalRegistry(self.objectives)
        self.plans = OperationalPlanRegistry(self.goals)
        self.strategic_feedback = StrategicFeedbackMonitor(
            self.goals,
            self.plans,
            persistent_shortfall_s=strategic_shortfall_timeout_s,
        )
        self.strategic_feedback_policy = StrategicFeedbackPolicy(self.objectives, self.goals, self.plans)
        self.strategic_goal_selector = StrategicGoalPortfolioSelector(self.objectives, self.goals, self.plans)
        self.relationship = CoalitionRelationship()
        self.coalition_doctrines = CoalitionDoctrineRegistry()
        self.border_violations = BorderViolationTracker(border_violation_tolerance_s)
        self.strategic_scope_config = strategic_scope_config or StrategicScopeConfig()
        self.information_requirement_registry = InformationRequirementRegistry()
        self.plan_executor = OperationalPlanExecutor(self)
        self._auftrag_ids_by_object: dict[int, str] = {}
        self._strategic_feedback_message_ids: set[str] = set()
        self._strategic_feedback_tasks: set[asyncio.Task[Any]] = set()
        self._strategic_goal_generation_number = 0
        self._strategic_verifications: StrategicVerificationRegistry | None = None
        self._strategic_scenery_objectives: dict[str, set[str]] = {}
        self._strategic_scenery_baselines: dict[str, tuple[str, ...]] = {}
        self._strategic_scenery_baseline_complete: dict[str, bool] = {}
        self.strategic_feedback.add_listener(self._on_strategic_feedback_policy_event)
        add_listener = getattr(server, "add_message_listener", None)
        if callable(add_listener):
            add_listener(self._on_bridge_message)

    @property
    def state(self) -> MooseBridgeState:
        """Return the current typed and raw bridge state.

        :returns: Local state mirror maintained by the server.
        """

        return self.server.state

    def reset_mission(self, *, reset_state: bool = True) -> None:
        """Discard all Python runtime state owned by the completed DCS mission."""

        for task in tuple(self._strategic_feedback_tasks):
            task.cancel()
        self._strategic_feedback_tasks.clear()
        self.relationship.clear()
        self.coalition_doctrines.clear()
        self.border_violations.clear()
        self.plan_executor.clear()
        self.strategic_feedback.clear()
        self.plans.clear()
        self.goals.clear()
        self.objectives.clear()
        self.information_requirement_registry.clear()
        self._auftrag_ids_by_object.clear()
        self._strategic_feedback_message_ids.clear()
        self._strategic_goal_generation_number = 0
        self._strategic_verifications = None
        self._strategic_scenery_objectives.clear()
        self._strategic_scenery_baselines.clear()
        self._strategic_scenery_baseline_complete.clear()
        if reset_state:
            self.state.reset_mission()

    def opszone(self, object_id: str) -> OpsZone | None:
        """Return a typed OPSZONE by object id.

        :param object_id: Stable bridge object id such as ``OPSZONE:Town Fight``.
        :returns: Typed OPSZONE or ``None``.
        """

        return self.state.opszone(object_id)

    def territory(self, object_id: str) -> Territory | None:
        """Return a typed TERRITORY by object id."""

        return self.state.territory(object_id)

    def add_information_requirement(
        self,
        requirement: InformationRequirement,
        *,
        replace: bool = False,
    ) -> InformationRequirement:
        """Register a passive coalition-private information requirement."""

        return self.information_requirement_registry.add(
            requirement,
            replace=replace,
            state=self.state,
        )

    def remove_information_requirement(
        self,
        requirement: InformationRequirement | str,
    ) -> InformationRequirement:
        """Remove an information requirement without affecting any AUFTRAG."""

        return self.information_requirement_registry.remove(requirement)

    def information_requirement(self, requirement_id: str) -> InformationRequirement | None:
        """Return one registered information requirement."""

        return self.information_requirement_registry.get(requirement_id)

    def information_requirements(
        self,
        *,
        intel_id: str | None = None,
        status: InformationRequirementStatus | str | None = None,
    ) -> tuple[InformationRequirement, ...]:
        """Return registered requirements, optionally filtered by source and status."""

        return self.information_requirement_registry.filter(intel_id=intel_id, status=status)

    def sync_information_requirements(
        self,
        *,
        source: str = "manual",
    ) -> tuple[InformationRequirementEvent, ...]:
        """Evaluate requirements from the current general INTEL state."""

        return self.information_requirement_registry.sync(self.state, source=source)

    async def monitor_information_requirements(
        self,
        on_event: Callable[[InformationRequirementEvent], Any | Awaitable[Any]],
        *,
        after_id: str | None = None,
    ) -> None:
        """Continuously evaluate requirements from INTEL events without polling."""

        cursor = after_id if after_id is not None else await self.server.event_cursor()
        await self.refresh_intel_state()
        self.sync_information_requirements(source="snapshot.intel_contacts")
        history_index = len(self.information_requirement_registry.events)
        while True:
            try:
                message = await self.server.wait_for_event("intel.*", timeout=3600.0, after_id=cursor)
            except TimeoutError:
                continue
            cursor = str(message.get("id") or "") or cursor
            self.sync_information_requirements(source=str(message.get("event") or "intel.event"))
            events = self.information_requirement_registry.events
            for event in events[history_index:]:
                result = on_event(event)
                if isinstance(result, Awaitable):
                    await result
            history_index = len(events)

    async def wait_for_information_requirement_event(
        self,
        requirement_id: str,
        event: str = "information_requirement.satisfied",
        *,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> InformationRequirementEvent:
        """Wait for one knowledge-state transition without changing tasking."""

        if self.information_requirement_registry.get(requirement_id) is None:
            raise ValueError(f"Unknown information requirement: {requirement_id}")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        cursor = after_id if after_id is not None else await self.server.event_cursor()
        history_index = len(self.information_requirement_registry.events)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for {event}: {requirement_id}")
            message = await self.server.wait_for_event("intel.*", timeout=remaining, after_id=cursor)
            cursor = str(message.get("id") or "") or cursor
            self.sync_information_requirements(source=str(message.get("event") or "intel.event"))
            events = self.information_requirement_registry.events
            for requirement_event in events[history_index:]:
                if requirement_event.requirement_id == requirement_id and requirement_event.event == event:
                    return requirement_event
            history_index = len(events)

    def add_strategic_objective(
        self,
        objective: StrategicObjective,
        *,
        replace: bool = False,
        sync: bool = True,
    ) -> StrategicObjective:
        """Add a Python-owned strategic objective during the mission."""

        added = self.objectives.add(objective, replace=replace)
        self._rebuild_strategic_scenery_index()
        if sync:
            self.sync_strategic_objectives(source="current_state")
        return added

    def generate_strategic_objectives(
        self,
        *,
        settlements: TheaterSettlements | None = None,
        transport: TheaterTransportInfrastructure | None = None,
        railway: TheaterRailwayInfrastructure | None = None,
        infrastructure: TheaterInfrastructureSites | None = None,
        verifications: StrategicVerificationRegistry | None = None,
        config: StrategicObjectiveGenerationConfig | None = None,
        register: bool = True,
        replace: bool = False,
    ) -> StrategicObjectiveGenerationResult:
        """Generate scope-bounded objectives from live and static theater data.

        Existing manually registered objectives remain authoritative unless
        ``replace`` is explicitly enabled.
        """

        result = generate_strategic_objectives(
            self.state,
            self.build_strategic_scope(strict=True),
            settlements=settlements,
            transport=transport,
            railway=railway,
            infrastructure=infrastructure,
            verifications=verifications,
            config=config,
        )
        if register:
            if verifications is not None:
                self._strategic_verifications = verifications
            generated_ids = {objective.objective_id for objective in result.objectives}
            if replace:
                for existing in self.objectives.all():
                    if existing.metadata.get("generated") and existing.objective_id not in generated_ids:
                        self.objectives.remove(existing)
            for objective in result.objectives:
                existing = self.objectives.get(objective.objective_id)
                if existing is not None and not replace:
                    continue
                self.objectives.add(objective, replace=existing is not None)
            self._rebuild_strategic_scenery_index()
            self.sync_strategic_objectives(source="strategic_objective_generation")
        return result

    def remove_strategic_objective(self, objective: StrategicObjective | str) -> StrategicObjective:
        """Remove a strategic objective during the mission."""

        removed = self.objectives.remove(objective)
        self._rebuild_strategic_scenery_index()
        self.goals.sync(mission_time=self._current_mission_time(), source="objective.removed")
        return removed

    def strategic_objective(self, objective_id: str) -> StrategicObjective | None:
        """Return one strategic objective by id."""

        return self.objectives.get(objective_id)

    def strategic_objectives(self, **filters: Any) -> tuple[StrategicObjective, ...]:
        """Return strategic objectives, optionally filtered by registry fields."""

        return self.objectives.filter(**filters)

    def sync_strategic_objectives(self, *, source: str = "manual") -> tuple[ObjectiveEvent, ...]:
        """Synchronize all strategic objectives from the current state mirror."""

        events = self.objectives.sync(self.state, source=source)
        self._rebuild_strategic_scenery_index()
        self.goals.sync(mission_time=self._current_mission_time(), source=source)
        return events

    def add_strategic_goal(
        self,
        goal: StrategicGoal,
        *,
        replace: bool = False,
        activate: bool = False,
    ) -> StrategicGoal:
        """Add a coalition-private strategic goal, optionally activating it."""

        added = self.goals.add(goal, replace=replace)
        if activate:
            self.activate_strategic_goal(added)
        return added

    def generate_strategic_goals(
        self,
        coalition: str,
        *,
        config: StrategicGoalGenerationConfig | None = None,
        register: bool = True,
        generation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> StrategicGoalGenerationResult:
        """Derive executable coalition-private goals from current objectives.

        Relationship state is a hard boundary here. Coalition doctrine remains
        a portfolio-ranking preference and is applied by
        :meth:`select_strategic_goal_portfolio`.
        """

        self._strategic_goal_generation_number += 1
        resolved_generation_id = generation_id or f"AUTO:{self._strategic_goal_generation_number}"
        result = generate_strategic_goals(
            self.strategic_objectives(),
            coalition,
            relationship=self.relationship,
            existing_goals=self.strategic_goals(),
            mission_time=self._current_mission_time(),
            generation_id=resolved_generation_id,
            config=config,
            metadata=metadata,
        )
        if register:
            for goal in result.goals:
                self.goals.add(goal)
        return result

    def activate_strategic_goal(self, goal: StrategicGoal | str) -> StrategicGoal:
        """Activate a planned strategic goal and evaluate its current state."""

        mission_time = self._current_mission_time()
        activated = self.goals.activate(goal, mission_time=mission_time)
        self.goals.sync(mission_time=mission_time, source="current_state")
        return activated

    def cancel_strategic_goal(self, goal: StrategicGoal | str, *, reason: str | None = None) -> StrategicGoal:
        """Cancel a planned or active strategic goal."""

        return self.goals.cancel(goal, mission_time=self._current_mission_time(), reason=reason)

    def complete_strategic_goal(
        self,
        goal: StrategicGoal | str,
        *,
        achieved: bool,
        reason: str | None = None,
    ) -> StrategicGoal:
        """Explicitly complete an active manual strategic goal."""

        return self.goals.complete_manual(
            goal,
            achieved=achieved,
            mission_time=self._current_mission_time(),
            reason=reason,
        )

    def remove_strategic_goal(self, goal: StrategicGoal | str) -> StrategicGoal:
        """Remove a strategic goal from the runtime registry."""

        return self.goals.remove(goal)

    def strategic_goal(self, goal_id: str) -> StrategicGoal | None:
        """Return one strategic goal by id."""

        return self.goals.get(goal_id)

    def strategic_goals(self, **filters: Any) -> tuple[StrategicGoal, ...]:
        """Return strategic goals, optionally filtered by registry fields."""

        return self.goals.filter(**filters)

    def sync_strategic_goals(self, *, source: str = "manual") -> tuple[StrategicGoalEvent, ...]:
        """Evaluate active goals from current strategic objective state."""

        return self.goals.sync(mission_time=self._current_mission_time(), source=source)

    async def wait_for_strategic_goal_event(
        self,
        goal_id: str,
        event: str = "goal.achieved",
        *,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> StrategicGoalEvent:
        """Wait for a local goal transition while consuming bridge events without polling."""

        if self.goals.get(goal_id) is None:
            raise ValueError(f"Unknown strategic goal: {goal_id}")
        for existing in reversed(self.goals.events):
            if existing.goal_id == goal_id and (event == "*" or existing.event == event):
                return existing

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        future: asyncio.Future[StrategicGoalEvent] = loop.create_future()
        last_bridge_event_id = after_id

        def on_goal_event(goal_event: StrategicGoalEvent) -> None:
            if future.done() or goal_event.goal_id != goal_id:
                return
            if event == "*" or goal_event.event == event:
                future.set_result(goal_event)

        self.goals.add_listener(on_goal_event)
        bridge_waiter: asyncio.Task[dict[str, Any]] | None = None
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for {event} for {goal_id}")
                bridge_waiter = asyncio.create_task(
                    self.server.wait_for_event("*", timeout=remaining, after_id=last_bridge_event_id)
                )
                done, _ = await asyncio.wait(
                    {future, bridge_waiter},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if future in done:
                    bridge_waiter.cancel()
                    await asyncio.gather(bridge_waiter, return_exceptions=True)
                    return future.result()
                if bridge_waiter not in done:
                    bridge_waiter.cancel()
                    await asyncio.gather(bridge_waiter, return_exceptions=True)
                    raise TimeoutError(f"Timed out waiting for {event} for {goal_id}")
                message = bridge_waiter.result()
                last_bridge_event_id = str(message.get("id") or "") or last_bridge_event_id
                self._on_bridge_message(message)
                bridge_waiter = None
        finally:
            self.goals.remove_listener(on_goal_event)
            if bridge_waiter is not None and not bridge_waiter.done():
                bridge_waiter.cancel()
                await asyncio.gather(bridge_waiter, return_exceptions=True)

    def add_operational_plan(self, plan: OperationalPlan, *, replace: bool = False) -> OperationalPlan:
        """Add a draft operational plan for an existing strategic goal."""

        if plan.created_mission_time is None:
            plan.created_mission_time = self._current_mission_time()
        return self.plans.add(plan, replace=replace)

    def operational_plan(self, plan_id: str) -> OperationalPlan | None:
        """Return one operational plan by id."""

        return self.plans.get(plan_id)

    def operational_plans(self) -> tuple[OperationalPlan, ...]:
        """Return all operational plans in stable id order."""

        return self.plans.all()

    def strategic_feedback_events(
        self,
        *,
        event: str | None = None,
        coalition: str | None = None,
        goal_id: str | None = None,
        plan_id: str | None = None,
    ) -> tuple[StrategicFeedbackEvent, ...]:
        """Return event-driven strategic feedback, optionally filtered."""

        return self.strategic_feedback.filter(
            event=event,
            coalition=coalition,
            goal_id=goal_id,
            plan_id=plan_id,
        )

    def add_strategic_feedback_listener(
        self,
        listener: Callable[[StrategicFeedbackEvent], None],
    ) -> None:
        """Subscribe to strategic goal, feasibility, and allocation changes."""

        self.strategic_feedback.add_listener(listener)

    def remove_strategic_feedback_listener(
        self,
        listener: Callable[[StrategicFeedbackEvent], None],
    ) -> None:
        """Remove a strategic feedback listener."""

        self.strategic_feedback.remove_listener(listener)

    def sync_strategic_feedback(self, *, source: str = "manual") -> tuple[StrategicFeedbackEvent, ...]:
        """Reassess non-terminal plans from current mirrored asset state."""

        return self.strategic_feedback.reassess_plans(
            legions=self.state.legion_objects.values(),
            cohorts=self.state.cohort_objects.values(),
            mission_time=self._current_mission_time(),
            source=source,
        )

    def strategic_feedback_decisions(
        self,
        event: StrategicFeedbackEvent,
    ) -> tuple[StrategicFeedbackDecision, ...]:
        """Evaluate one feedback event without changing plans or DCS state."""

        executing = {
            plan.plan_id
            for plan in self.plans.all()
            if plan.status in {OperationalPlanStatus.EXECUTING, OperationalPlanStatus.BLOCKED}
        }
        return self.strategic_feedback_policy.decide(event, executing_plan_ids=executing)

    def record_escalation_incident(
        self,
        incident: EscalationIncident,
    ) -> RelationshipTransitionProposal | None:
        """Record an attributed incident and return any transition proposal."""

        return self.relationship.record_incident(incident)

    def sync_border_violations(self) -> tuple[EscalationIncident, ...]:
        """Update tolerated ground-border violations from mirrored state."""

        incidents = self.border_violations.update(
            self.state.groups.values(),
            self.state.territory_objects.values(),
            mission_time=self._current_mission_time(),
        )
        for incident in incidents:
            self.record_escalation_incident(incident)
        return incidents

    def approve_relationship_transition(self, proposal_id: str) -> RelationshipState:
        """Approve and apply the pending shared relationship transition."""

        return self.relationship.approve_transition(proposal_id)

    def declare_war(self, coalition: str, *, reason: str) -> EscalationIncident:
        """Let one coalition explicitly declare war without prior incidents."""

        return self.relationship.declare_war(
            coalition,
            reason=reason,
            mission_time=self._current_mission_time(),
        )

    def reject_relationship_transition(self, proposal_id: str) -> None:
        """Reject the pending relationship transition."""

        self.relationship.reject_transition(proposal_id)

    def set_coalition_doctrine(
        self,
        coalition: str,
        doctrine: CoalitionDoctrine | CoalitionDoctrinePreset | str,
    ) -> CoalitionDoctrine:
        """Change one coalition's doctrine independently of relationship state."""

        return self.coalition_doctrines.set(coalition, doctrine)

    def set_opszone_strategic_value(self, object_id: str, escalation_points: float) -> float:
        """Set reference escalation points for capture of one strategic OPSZONE."""

        return self.relationship.set_opszone_capture_points(object_id, escalation_points)

    def diplomacy_status(self) -> dict[str, Any]:
        """Return the compact shared relationship and doctrine state."""

        proposal = self.relationship.pending_transition
        return {
            "relationship": self.relationship.state.value,
            "escalation_score": self.relationship.escalation_score,
            "automatic_transitions": self.relationship.automatic_transitions,
            "incident_count": len(self.relationship.incidents),
            "pending_transition": None if proposal is None else {
                "proposal_id": proposal.proposal_id,
                "from_state": proposal.from_state.value,
                "to_state": proposal.to_state.value,
                "reason": proposal.reason,
                "mission_time": proposal.mission_time,
                "automatic": proposal.automatic,
            },
            "doctrines": {
                coalition: self.coalition_doctrines.get(coalition).preset.value
                for coalition in ("blue", "red")
            },
        }

    async def persist_diplomacy_state(self) -> dict[str, Any]:
        """Persist this mission's shared diplomacy state in the daemon audit store."""

        payload = diplomacy_state_to_dict(
            self.relationship,
            self.coalition_doctrines,
            mission_generation=self.state.mission_generation,
            audit_session_id=self.state.audit_session_id,
        )
        payload["border_violations"] = self.border_violations.to_dict()
        return await self.server.append_audit_record(DIPLOMACY_AUDIT_TYPE, payload)

    async def refresh_diplomacy_state(self) -> bool:
        """Load the latest daemon diplomacy snapshot for the current mission."""

        records = await self.server.query_audit_records(record_type=DIPLOMACY_AUDIT_TYPE)
        generation = self.state.mission_generation
        audit_session_id = self.state.audit_session_id
        payload = next(
            (
                record.get("payload")
                for record in reversed(records)
                if isinstance(record.get("payload"), dict)
                and int(record["payload"].get("mission_generation") or 0) == generation
                and str(record["payload"].get("audit_session_id") or "") == audit_session_id
            ),
            None,
        )
        if not isinstance(payload, dict):
            return False
        legacy_snapshot = (
            int(payload.get("diplomacy_schema_version") or 1)
            < DIPLOMACY_STATE_SCHEMA_VERSION
        )
        apply_diplomacy_state(payload, self.relationship, self.coalition_doctrines)
        self.border_violations.restore(payload.get("border_violations"))
        if legacy_snapshot:
            await self.persist_diplomacy_state()
        return True

    def apply_diplomacy_events(self, events: Iterable[dict[str, Any]]) -> int:
        """Apply retained bridge events and return the number of new incidents."""

        before = len(self.relationship.incidents)
        for event in events:
            if str(event.get("event") or "") in {
                "combat.kill",
                "airbase.coalition_changed",
                "opszone.owner_changed",
                "opszone.coalition_changed",
            }:
                self._on_bridge_message(event)
        return len(self.relationship.incidents) - before

    def select_strategic_goal_portfolio(
        self,
        coalition: str,
        *,
        plans: Iterable[OperationalPlan] | None = None,
        max_concurrent_goals: int | None = None,
    ) -> StrategicGoalPortfolio:
        """Select concurrently feasible goals without activating or approving them."""

        return self.strategic_goal_selector.select(
            coalition,
            legions=self.state.legion_objects.values(),
            cohorts=self.state.cohort_objects.values(),
            mission_time=self._current_mission_time(),
            plans=plans,
            max_concurrent_goals=max_concurrent_goals,
            relationship=self.relationship,
            doctrine=self.coalition_doctrines.get(coalition),
        )

    async def apply_strategic_feedback_policy(
        self,
        event: StrategicFeedbackEvent,
        *,
        automatic_only: bool = True,
    ) -> tuple[StrategicFeedbackDecision, ...]:
        """Apply safe policy actions; replanning decisions never mutate a plan."""

        decisions = self.strategic_feedback_decisions(event)
        for decision in decisions:
            if automatic_only and not decision.automatic:
                continue
            if decision.action is not StrategicFeedbackAction.ABORT or not decision.plan_id:
                continue
            plan = self.operational_plan(decision.plan_id)
            if plan is None or plan.status not in {
                OperationalPlanStatus.EXECUTING,
                OperationalPlanStatus.BLOCKED,
            }:
                continue
            try:
                await self.abort_operational_plan(plan, reason=decision.reason)
            except Exception as exc:
                self.strategic_feedback.record_context_change(
                    "feedback.policy_action_skipped",
                    source="strategic_feedback_policy",
                    mission_time=self._current_mission_time(),
                    coalition=plan.coalition,
                    goal_id=plan.goal_id,
                    plan_id=plan.plan_id,
                    details={"action": decision.action.value, "reason": str(exc)},
                )
            else:
                self.strategic_feedback.record_context_change(
                    "feedback.policy_action_applied",
                    source="strategic_feedback_policy",
                    mission_time=self._current_mission_time(),
                    coalition=plan.coalition,
                    goal_id=plan.goal_id,
                    plan_id=plan.plan_id,
                    details={"action": decision.action.value, "reason": decision.reason},
                )
        return decisions

    def _on_strategic_feedback_policy_event(self, event: StrategicFeedbackEvent) -> None:
        # The executor already consumes terminal goal events and owns their
        # phase/plan outcome. Scheduling a second abort here would race it.
        if event.event == "feedback.goal_status_changed":
            return
        if not any(decision.automatic for decision in self.strategic_feedback_decisions(event)):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.apply_strategic_feedback_policy(event))
        self._strategic_feedback_tasks.add(task)
        task.add_done_callback(self._strategic_feedback_tasks.discard)

    def propose_capture_plan(
        self,
        goal: StrategicGoal | str,
        picture: TacticalPicture,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        planner: RuleBasedOperationalPlanner | None = None,
        mission_resolver: StrategicMissionResolver | None = None,
    ) -> OperationalPlan:
        """Create an unregistered rule-based CAPTURE draft from tactical state."""

        item = goal if isinstance(goal, StrategicGoal) else self.strategic_goal(goal)
        if item is None:
            raise KeyError(f"Unknown strategic goal: {goal}")
        objective = self.strategic_objective(item.objective_id)
        if objective is None:
            raise KeyError(f"Unknown strategic objective: {item.objective_id}")
        resolver = mission_resolver or self.mission_resolver
        legions = self._strategic_legions(item.coalition)
        cohorts = self._strategic_cohorts(item.coalition)
        ammunition = self._strategic_ammunition(item.coalition)
        target_resolutions = {
            contact.target_object_id: resolver.resolve(
                contact.target_object_id,
                target_data=self._strategic_target_data(contact.target_object_id, picture=picture),
                cohorts=cohorts,
                legions=legions,
                ammunition=ammunition,
                weapon_ranges=self.weapon_range_registry,
            )
            for contact in picture.contacts
            if contact.target_object_id and (contact.is_ground or contact.is_static)
        }
        return (planner or RuleBasedOperationalPlanner()).propose_capture(
            item,
            objective,
            picture,
            target_resolutions=target_resolutions,
            plan_id=plan_id,
            name=name,
        )

    def propose_defend_plan(
        self,
        goal: StrategicGoal | str,
        picture: TacticalPicture,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        planner: RuleBasedOperationalPlanner | None = None,
        mission_resolver: StrategicMissionResolver | None = None,
    ) -> OperationalPlan:
        """Create an unregistered rule-based DEFEND draft from tactical state."""

        item = goal if isinstance(goal, StrategicGoal) else self.strategic_goal(goal)
        if item is None:
            raise KeyError(f"Unknown strategic goal: {goal}")
        objective = self.strategic_objective(item.objective_id)
        if objective is None:
            raise KeyError(f"Unknown strategic objective: {item.objective_id}")
        resolver = mission_resolver or self.mission_resolver
        legions = self._strategic_legions(item.coalition)
        cohorts = self._strategic_cohorts(item.coalition)
        ammunition = self._strategic_ammunition(item.coalition)
        target_resolutions = {
            contact.target_object_id: resolver.resolve(
                contact.target_object_id,
                target_data=self._strategic_target_data(contact.target_object_id, picture=picture),
                cohorts=cohorts,
                legions=legions,
                ammunition=ammunition,
                weapon_ranges=self.weapon_range_registry,
            )
            for contact in picture.contacts
            if contact.target_object_id and (contact.is_ground or contact.is_static)
        }
        return (planner or RuleBasedOperationalPlanner()).propose_defend(
            item,
            objective,
            picture,
            target_resolutions=target_resolutions,
            plan_id=plan_id,
            name=name,
        )

    def propose_destroy_plan(
        self,
        goal: StrategicGoal | str,
        picture: TacticalPicture,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        planner: RuleBasedOperationalPlanner | None = None,
        mission_resolver: StrategicMissionResolver | None = None,
    ) -> OperationalPlan:
        """Create an unregistered weighted DESTROY draft from tactical state."""

        item = goal if isinstance(goal, StrategicGoal) else self.strategic_goal(goal)
        if item is None:
            raise KeyError(f"Unknown strategic goal: {goal}")
        objective = self.strategic_objective(item.objective_id)
        if objective is None:
            raise KeyError(f"Unknown strategic objective: {item.objective_id}")
        health_by_id = {
            component.object_id: effective_component_health(objective, component.object_id, self.state)
            for component in objective.components
        }
        resolver = mission_resolver or self.mission_resolver
        legions = self._strategic_legions(item.coalition)
        cohorts = self._strategic_cohorts(item.coalition)
        ammunition = self._strategic_ammunition(item.coalition)
        resolutions = {
            component.object_id: resolver.resolve(
                component.object_id,
                effect=item.effect,
                target_data=self._strategic_target_data(component.object_id, picture=picture),
                cohorts=cohorts,
                legions=legions,
                ammunition=ammunition,
                weapon_ranges=self.weapon_range_registry,
            )
            for component in objective.components
            if component.contributes_to_health and health_by_id.get(component.object_id) not in {None, 0.0}
        }
        return (planner or RuleBasedOperationalPlanner()).propose_destroy(
            item,
            objective,
            picture,
            health_by_id,
            mission_resolutions=resolutions,
            plan_id=plan_id,
            name=name,
        )

    def propose_disable_plan(
        self,
        goal: StrategicGoal | str,
        picture: TacticalPicture,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        planner: RuleBasedOperationalPlanner | None = None,
        mission_resolver: StrategicMissionResolver | None = None,
    ) -> OperationalPlan:
        """Create an unregistered rule-based DISABLE draft from tactical state."""

        item = goal if isinstance(goal, StrategicGoal) else self.strategic_goal(goal)
        if item is None:
            raise KeyError(f"Unknown strategic goal: {goal}")
        objective = self.strategic_objective(item.objective_id)
        if objective is None:
            raise KeyError(f"Unknown strategic objective: {item.objective_id}")
        control_id = objective.control_object_id
        airbase = self.state.airbases.get(control_id or "")
        if airbase is None:
            raise ValueError(
                f"AIRBASE snapshot is unavailable for {control_id or objective.objective_id}; "
                "call snapshot_airbases() before proposing runway denial"
            )
        resolution = (mission_resolver or self.mission_resolver).resolve(
            control_id or "",
            effect=item.effect,
            target_data=airbase,
            cohorts=self._strategic_cohorts(item.coalition),
            legions=self._strategic_legions(item.coalition),
            ammunition=self._strategic_ammunition(item.coalition),
            weapon_ranges=self.weapon_range_registry,
        )
        return (planner or RuleBasedOperationalPlanner()).propose_disable(
            item,
            objective,
            picture,
            mission_resolution=resolution,
            plan_id=plan_id,
            name=name,
        )

    def _strategic_target_data(
        self,
        object_id: str,
        *,
        picture: TacticalPicture | None = None,
    ) -> Mapping[str, Any] | None:
        """Return raw mirrored data used for strategic target classification."""

        prefix = object_id.partition(":")[0].upper()
        collection_name = {
            "GROUP": "groups",
            "UNIT": "units",
            "STATIC": "statics",
            "AIRBASE": "airbases",
            "OPSZONE": "opszones",
        }.get(prefix)
        contact = next(
            (
                item
                for item in picture.contacts
                if item.target_object_id == object_id
            ),
            None,
        ) if picture is not None else None
        value = getattr(self.state, collection_name).get(object_id) if collection_name else None
        use_global_object_data = prefix not in {"GROUP", "UNIT"} or picture is None or contact is None
        data = dict(value) if use_global_object_data and isinstance(value, Mapping) else {}
        if prefix in {"SCENERY", "MAPOBJECT"}:
            component = next(
                (
                    component
                    for objective in self.objectives.all()
                    for component in objective.components
                    if component.object_id == object_id
                ),
                None,
            )
            if component is not None:
                data.update(component.metadata)
                data.setdefault("category", "Map Object")
        if contact is not None:
            data.update(
                {
                    "x": contact.x,
                    "y": contact.y,
                    "z": contact.z,
                    "speed_mps": contact.speed_mps,
                }
            )
            if not data.get("category"):
                if contact.is_ship:
                    data["category"] = "Ship"
                elif contact.is_ground:
                    data["category"] = "Ground Unit"
                elif contact.is_static:
                    data["category"] = "Static"
                elif contact.category_name:
                    data["category"] = contact.category_name
                elif contact.contact_type:
                    data["category"] = contact.contact_type
            if contact.attribute and not data.get("attributes"):
                data["attributes"] = [contact.attribute]
        return data or None

    def _strategic_cohorts(self, coalition: str) -> tuple[Cohort, ...]:
        """Return COHORTs belonging to LEGIONs of one coalition."""

        legion_ids = {legion.object_id for legion in self._strategic_legions(coalition)}
        return tuple(
            cohort
            for cohort in self.state.cohort_objects.values()
            if cohort.legion_id in legion_ids
        )

    def _strategic_legions(self, coalition: str) -> tuple[Legion, ...]:
        """Return LEGIONs belonging to one coalition."""

        normalized = normalize_coalition(coalition)
        return tuple(
            legion
            for legion in self.state.legion_objects.values()
            if normalize_coalition(legion.coalition or legion.coalition_name) == normalized
        )

    def _strategic_ammunition(self, coalition: str) -> tuple[UnitAmmunition, ...]:
        """Return observed ammunition for active units of one coalition."""

        normalized = normalize_coalition(coalition)
        result: list[UnitAmmunition] = []
        for ammunition in self.state.ammunition_objects.values():
            group = self.state.groups.get(ammunition.group_id or "")
            unit = self.state.units.get(ammunition.unit_id)
            payload = group if isinstance(group, Mapping) else unit
            if isinstance(payload, Mapping) and normalize_coalition(payload.get("coalition")) == normalized:
                result.append(ammunition)
        return tuple(sorted(result, key=lambda item: item.unit_id))

    def validate_operational_plan(self, plan: OperationalPlan | str) -> OperationalPlanAssessment:
        """Validate a plan against currently mirrored LEGION and COHORT stock."""

        item = plan if isinstance(plan, OperationalPlan) else self.plans.get(plan)
        if item is None:
            raise KeyError(f"Unknown operational plan: {plan}")
        legions = tuple(self.state.legion_objects.values())
        cohorts = tuple(self.state.cohort_objects.values())
        self._prepare_operational_assignment_metadata(item, legions=legions, cohorts=cohorts)
        return self.plans.validate(
            item,
            legions=legions,
            cohorts=cohorts,
            mission_time=self._current_mission_time(),
        )

    def _prepare_operational_assignment_metadata(
        self,
        plan: OperationalPlan,
        *,
        legions: tuple[Legion, ...],
        cohorts: tuple[Cohort, ...],
    ) -> None:
        """Attach route-aware COHORT rankings to target-bound requirements."""

        if self.mission_resolver.ground_mobility is None:
            return
        coalition_legion_ids = {
            legion.object_id
            for legion in legions
            if normalize_coalition(legion.coalition or legion.coalition_name) == plan.coalition
        }
        coalition_cohorts = tuple(
            cohort for cohort in cohorts if cohort.legion_id in coalition_legion_ids
        )
        for phase in plan.phases:
            for intent in phase.intents:
                if not intent.target_object_id:
                    continue
                target_data = self._strategic_target_data(intent.target_object_id)
                if not target_data or target_data.get("latitude") is None or target_data.get("longitude") is None:
                    continue
                for requirement in intent.asset_requirements:
                    mission_types = requirement.mission_types or intent.auftrag_types
                    assignments = []
                    for mission_type in mission_types:
                        assignments.extend(
                            self.mission_resolver.assignments_for_mission(
                                mission_type,
                                target_data=target_data,
                                cohorts=coalition_cohorts,
                                legions=legions,
                                performer_categories=requirement.performer_categories,
                                require_payload=requirement.require_payload,
                            )
                        )
                    best_by_cohort = {}
                    for assignment in assignments:
                        previous = best_by_cohort.get(assignment.cohort_id)
                        if previous is None or assignment.selection_score > previous.selection_score:
                            best_by_cohort[assignment.cohort_id] = assignment
                    ranked = sorted(
                        best_by_cohort.values(),
                        key=lambda assignment: (
                            -assignment.selection_score,
                            assignment.estimated_time_to_effect_s is None,
                            assignment.estimated_time_to_effect_s
                            if assignment.estimated_time_to_effect_s is not None
                            else math.inf,
                            assignment.cohort_id,
                        ),
                    )
                    ground_candidates_exist = any(
                        cohort.is_ground
                        and any(mission in cohort.mission_type_keys for mission in mission_types)
                        for cohort in coalition_cohorts
                    )
                    if not ground_candidates_exist:
                        continue
                    requirement.metadata["mission_assignments"] = [assignment.to_dict() for assignment in ranked]
                    requirement.metadata["ground_mobility_filter"] = True
                    if ranked:
                        requirement.metadata["estimated_time_to_effect_s"] = ranked[0].estimated_time_to_effect_s
                        requirement.metadata["selection_score"] = ranked[0].selection_score

    async def refresh_and_validate_operational_plan(self, plan: OperationalPlan | str) -> OperationalPlanAssessment:
        """Refresh LEGION/COHORT state and validate an operational plan."""

        await self.snapshot_legions()
        await self.snapshot_cohorts()
        return self.validate_operational_plan(plan)

    def approve_operational_plan(
        self,
        plan: OperationalPlan | str,
        *,
        approved_by: str | None = None,
        reason: str | None = None,
    ) -> OperationalPlan:
        """Approve a feasible plan and retain explicit operator attribution."""

        identity = getattr(self.server, "client_identity", None)
        identity_name = getattr(identity, "display_name", None)
        identity_id = getattr(identity, "client_id", None)
        return self.plans.approve(
            plan,
            mission_time=self._current_mission_time(),
            approved_by=approved_by or identity_name or "operator",
            approved_client_id=identity_id,
            reason=reason,
        )

    def operational_plan_execution(self, plan: OperationalPlan | str) -> OperationalPlanExecution | None:
        """Return the latest runtime execution record for an operational plan."""

        plan_id = plan.plan_id if isinstance(plan, OperationalPlan) else plan
        return self.plan_executor.get(plan_id)

    def operational_plan_executions(self, plan: OperationalPlan | str) -> tuple[OperationalPlanExecution, ...]:
        """Return every execution attempt for an operational plan."""

        plan_id = plan.plan_id if isinstance(plan, OperationalPlan) else plan
        return self.plan_executor.history(plan_id)

    async def refresh_operational_plan_executions(
        self,
        plan: OperationalPlan | str,
    ) -> tuple[OperationalPlanExecution, ...]:
        """Load persistent execution attempts from the daemon audit store."""

        plan_id = plan.plan_id if isinstance(plan, OperationalPlan) else plan
        return await self.plan_executor.refresh_history(plan_id)

    async def restore_operational_plan(
        self,
        plan_id: str,
        *,
        replace: bool = False,
    ) -> RestoredOperationalPlan:
        """Restore an objective, goal and plan from the daemon audit history."""

        executions = await self.plan_executor.refresh_history(plan_id)
        if not executions:
            raise KeyError(f"No operational audit history found: {plan_id}")
        latest = executions[-1]
        if not latest.plan_snapshot or not latest.goal_snapshot or not latest.objective_snapshot:
            raise ValueError(
                f"Operational audit for {plan_id} predates restorable strategic snapshots"
            )

        from .operational_audit import goal_from_snapshot, objective_from_snapshot, plan_from_snapshot

        objective = objective_from_snapshot(latest.objective_snapshot)
        goal = goal_from_snapshot(latest.goal_snapshot)
        plan = plan_from_snapshot(latest.plan_snapshot)
        if plan.plan_id != plan_id:
            raise ValueError(f"Operational audit plan id mismatch: {plan.plan_id}")
        if goal.objective_id != objective.objective_id or plan.goal_id != goal.goal_id:
            raise ValueError("Operational audit strategic references are inconsistent")
        if plan.coalition != goal.coalition:
            raise ValueError("Operational audit plan and goal coalitions are inconsistent")

        conflicts = [
            object_id
            for object_id, existing in (
                (objective.objective_id, self.objectives.get(objective.objective_id)),
                (goal.goal_id, self.goals.get(goal.goal_id)),
                (plan.plan_id, self.plans.get(plan.plan_id)),
            )
            if existing is not None
        ]
        if conflicts and not replace:
            raise ValueError(f"Restore would replace existing objects: {', '.join(conflicts)}")

        self.objectives.add(objective, replace=self.objectives.get(objective.objective_id) is not None)
        self.goals.add(goal, replace=self.goals.get(goal.goal_id) is not None)
        self.plans.add(plan, replace=self.plans.get(plan.plan_id) is not None)
        return RestoredOperationalPlan(objective, goal, plan, executions)

    async def reconcile_operational_plan(
        self,
        plan: OperationalPlan | str,
        *,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanReconciliation:
        """Reconcile one restored executing plan from a current AUFTRAG snapshot."""

        item = plan if isinstance(plan, OperationalPlan) else self.operational_plan(plan)
        if item is None:
            raise KeyError(f"Unknown operational plan: {plan}")
        return await self.plan_executor.reconcile(item, on_event=on_event)

    async def monitor_interrupted_operational_plan(
        self,
        plan: OperationalPlan | str,
        *,
        mission_timeout_s: float = 3600.0,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanReconciliation:
        """Reattach to current AUFTRAG events without submitting new missions."""

        item = plan if isinstance(plan, OperationalPlan) else self.operational_plan(plan)
        if item is None:
            raise KeyError(f"Unknown operational plan: {plan}")
        return await self.plan_executor.monitor_interrupted(
            item,
            mission_timeout_s=mission_timeout_s,
            on_event=on_event,
        )

    async def block_interrupted_operational_plan(
        self,
        plan: OperationalPlan | str,
        *,
        reason: str,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanExecution:
        """Explicitly block an unresolved interrupted plan so it can be replanned."""

        item = plan if isinstance(plan, OperationalPlan) else self.operational_plan(plan)
        if item is None:
            raise KeyError(f"Unknown operational plan: {plan}")
        return await self.plan_executor.block_interrupted(item, reason=reason, on_event=on_event)

    async def abort_operational_plan(
        self,
        plan: OperationalPlan | str,
        *,
        scope: PlanAbortScope | str = PlanAbortScope.ATTEMPT,
        reason: str = "Operational plan aborted by operator",
        timeout: float = 10.0,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanAbortResult:
        """Cancel live AUFTRAGs and terminate the current execution attempt."""

        item = plan if isinstance(plan, OperationalPlan) else self.operational_plan(plan)
        if item is None:
            raise KeyError(f"Unknown operational plan: {plan}")
        return await self.plan_executor.abort(
            item,
            scope=scope,
            reason=reason,
            timeout=timeout,
            on_event=on_event,
        )

    def prepare_plan_retry(
        self,
        plan: OperationalPlan | str,
        *,
        resume_from: str | None = None,
        target_overrides: Mapping[tuple[str, str], str] | None = None,
        allowed_legion_overrides: Mapping[tuple[str, str, str], Iterable[str]] | None = None,
        allowed_cohort_overrides: Mapping[tuple[str, str, str], Iterable[str]] | None = None,
    ) -> OperationalPlan:
        """Prepare a blocked plan for explicit revalidation and another execution attempt."""

        item = plan if isinstance(plan, OperationalPlan) else self.operational_plan(plan)
        if item is None:
            raise KeyError(f"Unknown operational plan: {plan}")
        return self.plan_executor.prepare_retry(
            item,
            resume_from=resume_from,
            target_overrides=target_overrides,
            allowed_legion_overrides=allowed_legion_overrides,
            allowed_cohort_overrides=allowed_cohort_overrides,
        )

    async def execute_plan(
        self,
        plan: OperationalPlan | str,
        *,
        commander: str | None = None,
        mission_timeout_s: float = 3600.0,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanExecution:
        """Execute an approved capture plan through a MOOSE COMMANDER."""

        item = plan if isinstance(plan, OperationalPlan) else self.operational_plan(plan)
        if item is None:
            raise KeyError(f"Unknown operational plan: {plan}")
        return await self.plan_executor.execute(
            item,
            commander_id=commander,
            mission_timeout_s=mission_timeout_s,
            on_event=on_event,
        )

    async def execute_operational_plan(
        self,
        plan: OperationalPlan | str,
        *,
        commander: str | None = None,
        mission_timeout_s: float = 3600.0,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanExecution:
        """Explicitly named alias for :meth:`execute_plan`."""

        return await self.execute_plan(
            plan,
            commander=commander,
            mission_timeout_s=mission_timeout_s,
            on_event=on_event,
        )

    async def wait_for_objective_event(
        self,
        event: str = "objective.control_changed",
        *,
        objective_id: str,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> ObjectiveEvent:
        """Wait for a normalized strategic event driven by bridge events."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        history_index = len(self.objectives.events)
        last_bridge_event_id = after_id
        objective = self.objectives.get(objective_id)
        if objective is None:
            raise ValueError(f"Unknown strategic objective: {objective_id}")
        bridge_event_name = _ownership_bridge_event(objective)
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for {event}")
            message = await self.server.wait_for_event(
                bridge_event_name,
                timeout=remaining,
                after_id=last_bridge_event_id,
            )
            last_bridge_event_id = str(message.get("id") or "") or last_bridge_event_id
            source = str(message.get("event") or "bridge.event")
            self.sync_strategic_objectives(source=source)
            current_events = self.objectives.events
            for objective_event in current_events[history_index:]:
                if objective_event.event != event:
                    continue
                if objective_event.objective_id != objective_id:
                    continue
                return objective_event
            history_index = len(current_events)

    async def wait_for_object_destroyed(
        self,
        object_id: str,
        *,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> DestroyedObjectEvent:
        """Wait for one UNIT, STATIC, or SCENERY destruction reported by DCS."""

        if not object_id.startswith(("UNIT:", "STATIC:", "SCENERY:")):
            raise ValueError("object_id must start with UNIT:, STATIC:, or SCENERY:")
        message = await self.server.wait_for_event(
            "object.destroyed",
            filters={"object_id": object_id},
            timeout=timeout,
            after_id=after_id,
        )
        return DestroyedObjectEvent.from_message(message)

    def _rebuild_strategic_scenery_index(self) -> None:
        """Index fixed scenery baselines belonging to current objectives."""

        by_scenery: dict[str, set[str]] = {}
        baselines: dict[str, tuple[str, ...]] = {}
        baseline_complete: dict[str, bool] = {}
        for objective in self.objectives.all():
            source_id = str(objective.metadata.get("source_object_id") or "")
            verification = (
                self._strategic_verifications.get(source_id)
                if self._strategic_verifications is not None and source_id
                else None
            )
            if verification is not None and verification.observed_objects:
                object_ids = tuple(item.object_id for item in verification.observed_objects)
                is_complete = verification.observation_complete
            else:
                object_ids = tuple(
                    component.object_id
                    for component in objective.components
                    if component.object_id.startswith("SCENERY:")
                )
                is_complete = bool(object_ids)
            if not object_ids:
                continue
            baselines[objective.objective_id] = object_ids
            baseline_complete[objective.objective_id] = is_complete
            for object_id in object_ids:
                by_scenery.setdefault(object_id, set()).add(objective.objective_id)

        self._strategic_scenery_objectives = by_scenery
        self._strategic_scenery_baselines = baselines
        self._strategic_scenery_baseline_complete = baseline_complete

        current_objective_ids = set(baselines)
        for report_id, report in tuple(self.state.loss_reports.items()):
            if (
                report.get("report_kind") == "strategic_damage"
                and report.get("target_object_id") not in current_objective_ids
            ):
                del self.state.loss_reports[report_id]
        for objective_id, object_ids in baselines.items():
            if self.state.destroyed_object_ids.intersection(object_ids):
                self._update_strategic_scenery_loss_report(objective_id)

    def _record_strategic_scenery_loss(self, event: DestroyedObjectEvent) -> None:
        """Update affected strategic-objective reports after one scenery loss."""

        if event.object_type != "SCENERY":
            return
        for objective_id in sorted(self._strategic_scenery_objectives.get(event.object_id, ())):
            self._update_strategic_scenery_loss_report(objective_id, event=event)

    def _update_strategic_scenery_loss_report(
        self,
        objective_id: str,
        *,
        event: DestroyedObjectEvent | None = None,
    ) -> None:
        """Create or refresh one stable aggregate report for an objective."""

        objective = self.objectives.get(objective_id)
        baseline = self._strategic_scenery_baselines.get(objective_id, ())
        if objective is None or not baseline:
            return
        observed_destroyed = tuple(
            object_id for object_id in baseline if object_id in self.state.destroyed_object_ids
        )
        if not observed_destroyed:
            return

        report_id = f"LOSS:STRATEGIC:{objective_id}"
        previous = self.state.loss_reports.get(report_id, {})
        observed_damage = len(observed_destroyed) / len(baseline)
        strategic_components = tuple(
            component
            for component in objective.components
            if component.contributes_to_health and component.weight > 0
        )
        strategic_weight = sum(component.weight for component in strategic_components)
        strategic_health_min = 0.0
        strategic_health_max = 0.0
        strategic_destroyed: list[str] = []
        if strategic_weight > 0:
            unknown_weight = 0.0
            for component in strategic_components:
                health = effective_component_health(objective, component.object_id, self.state)
                if health is None:
                    unknown_weight += component.weight
                    continue
                strategic_health_min += health * component.weight
                strategic_health_max += health * component.weight
                if health <= 0:
                    strategic_destroyed.append(component.object_id)
            strategic_health_min /= strategic_weight
            strategic_health_max = (strategic_health_max + unknown_weight) / strategic_weight
            strategic_damage_min = 1.0 - strategic_health_max
            strategic_damage_max = 1.0 - strategic_health_min
        else:
            strategic_damage_min = observed_damage
            strategic_damage_max = observed_damage

        damage_min = max(observed_damage, strategic_damage_min)
        damage_max = max(observed_damage, strategic_damage_max)
        status = (
            "destroyed"
            if strategic_weight > 0 and strategic_damage_min >= 1.0 - 1e-9
            else "damaged"
        )
        event_object = event.object if event is not None else {}
        latitude = _optional_float(objective.metadata.get("latitude"))
        longitude = _optional_float(objective.metadata.get("longitude"))
        if latitude is None:
            latitude = _optional_float(event_object.get("latitude"))
        if longitude is None:
            longitude = _optional_float(event_object.get("longitude"))
        x = _optional_float(objective.metadata.get("x"))
        y = _optional_float(objective.metadata.get("y"))
        z = _optional_float(objective.metadata.get("z"))
        if x is None:
            x = _optional_float(event_object.get("x"))
        if y is None:
            y = _optional_float(event_object.get("y"))
        if z is None:
            z = _optional_float(event_object.get("z"))
        owner = normalize_coalition(objective.owner)
        mission_time = event.mission_time if event is not None else self._current_mission_time()
        source_id = str(objective.metadata.get("source_object_id") or objective.objective_id)

        self.state.loss_reports[report_id] = {
            "object_id": report_id,
            "dcs_name": objective.name,
            "object_type": "LOSS_REPORT",
            "report_kind": "strategic_damage",
            "target_object_id": objective.objective_id,
            "target_object_type": "STRATEGIC_OBJECTIVE",
            "strategic_source_id": source_id,
            "objective_kind": objective.kind.value,
            "victim_coalition": owner,
            "coalition": owner,
            "visible_to": ["blue", "red"],
            "status": status,
            "alive": False,
            "confidence": "confirmed",
            "source": (
                event.dcs_event_name
                if event is not None and event.dcs_event_name
                else previous.get("source") or "DCS_DESTRUCTION_STATE"
            ),
            "mission_time": mission_time,
            "first_mission_time": previous.get("first_mission_time", mission_time),
            "dcs_event_time": (
                event.dcs_event_time if event is not None else previous.get("dcs_event_time")
            ),
            "category": "strategic_damage",
            "dcs_type": "Strategic infrastructure",
            "last_component_id": event.object_id if event is not None else observed_destroyed[-1],
            "destroyed_component_ids": list(observed_destroyed),
            "destroyed_component_count": len(observed_destroyed),
            "baseline_component_count": len(baseline),
            "baseline_complete": self._strategic_scenery_baseline_complete.get(objective_id, False),
            "strategic_component_count": len(strategic_components),
            "destroyed_strategic_component_ids": strategic_destroyed,
            "destroyed_strategic_component_count": len(strategic_destroyed),
            "damage_min": damage_min,
            "damage_max": damage_max,
            "damage_percent_min": damage_min * 100.0,
            "damage_percent_max": damage_max * 100.0,
            "strategic_damage_min": strategic_damage_min,
            "strategic_damage_max": strategic_damage_max,
            "observed_damage_min": observed_damage,
            "observed_damage_percent_min": observed_damage * 100.0,
            "x": x,
            "y": y,
            "z": z,
            "latitude": latitude,
            "longitude": longitude,
        }

    def _on_bridge_message(self, message: dict[str, Any]) -> None:
        """Update strategic objectives after relevant state messages arrive."""

        message_type = str(message.get("type") or "")
        kind = str(message.get("kind") or "")
        event_name = str(message.get("event") or "")
        message_id = str(message.get("id") or "")
        feedback_message_is_new = not message_id or message_id not in self._strategic_feedback_message_ids
        if message_id and feedback_message_is_new:
            self._strategic_feedback_message_ids.add(message_id)
            if len(self._strategic_feedback_message_ids) > 20_000:
                self._strategic_feedback_message_ids.clear()
                self._strategic_feedback_message_ids.add(message_id)
        if message_type == "event" and event_name == "mission.ended":
            self.reset_mission(reset_state=False)
            return
        if message_type == "event" and event_name == "object.destroyed" and feedback_message_is_new:
            self._record_strategic_scenery_loss(DestroyedObjectEvent.from_message(message))
        if message_type == "event" and event_name == "combat.kill" and feedback_message_is_new:
            kill = KillEvent.from_message(message)
            killer = normalize_coalition(kill.killer_coalition)
            target = normalize_coalition(kill.target_coalition)
            if (
                kill.target_object_id.startswith("UNIT:")
                and killer in {"blue", "red"}
                and target in {"blue", "red"}
                and killer != target
            ):
                self.record_escalation_incident(
                    EscalationIncident(
                        incident_id=(
                            f"INCIDENT:KILL:{kill.killer_object_id}:{kill.target_object_id}:"
                            f"{_incident_mission_time(kill.mission_time)}"
                        ),
                        incident_type=EscalationIncidentType.UNIT_DESTROYED,
                        actor_coalition=killer,
                        target_coalition=target,
                        mission_time=kill.mission_time,
                        reference_id=kill.target_object_id,
                        details={
                            "killer_object_id": kill.killer_object_id,
                            "killer_group_id": kill.killer_group_id,
                            "target_object_id": kill.target_object_id,
                            "target_group_id": kill.target_group_id,
                            "weapon_name": kill.weapon_name,
                            "source_event": "combat.kill",
                        },
                    )
                )
        if message_type == "event" and event_name == "airbase.coalition_changed" and feedback_message_is_new:
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            airbase = payload.get("airbase") if isinstance(payload.get("airbase"), dict) else {}
            previous = normalize_coalition(payload.get("previous_coalition"))
            current = normalize_coalition(payload.get("coalition") or airbase.get("coalition"))
            actor = normalize_coalition(payload.get("capturing_coalition")) or current
            airbase_id = str(payload.get("airbase_id") or airbase.get("object_id") or "")
            mission_time = _optional_float(message.get("mission_time"))
            opponent = "red" if actor == "blue" else "blue" if actor == "red" else None
            if (
                airbase_id.startswith("AIRBASE:")
                and current in {"blue", "red"}
                and actor == current
                and previous != current
                and opponent is not None
            ):
                x = _optional_float(airbase.get("x"))
                z = _optional_float(airbase.get("z"))
                territory = _territory_at_point(self.state.territory_objects.values(), x, z)
                multiplier, factors = airbase_capture_multiplier(
                    previous_coalition=previous,
                    capturing_coalition=actor,
                    territory_coalition=territory.coalition if territory else None,
                    category=str(airbase.get("category") or ""),
                )
                stable_source = (
                    f"{airbase_id}:{previous or 'unknown'}:{current}:"
                    f"{_incident_mission_time(mission_time)}"
                )
                self.record_escalation_incident(
                    EscalationIncident(
                        incident_id=f"INCIDENT:CAPTURE:{stable_source}",
                        incident_type=EscalationIncidentType.OBJECTIVE_CAPTURED,
                        actor_coalition=actor,
                        target_coalition=previous if previous in {"blue", "red"} else opponent,
                        mission_time=mission_time,
                        reference_id=airbase_id,
                        multiplier=multiplier,
                        details={
                            "airbase_id": airbase_id,
                            "airbase_name": airbase.get("name") or airbase.get("dcs_name"),
                            "previous_coalition": previous,
                            "coalition": current,
                            "capturing_unit_id": payload.get("capturing_unit_id"),
                            "capturing_group_id": payload.get("capturing_group_id"),
                            "territory_id": territory.object_id if territory else None,
                            "territory_coalition": territory.coalition if territory else None,
                            **factors,
                            "source_event": "airbase.coalition_changed",
                        },
                    )
                )
        if (
            message_type == "event"
            and event_name in {"opszone.owner_changed", "opszone.coalition_changed"}
            and feedback_message_is_new
        ):
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            opszone = payload.get("opszone") if isinstance(payload.get("opszone"), dict) else {}
            previous = normalize_coalition(
                payload.get("previous_coalition") or opszone.get("owner_previous_name")
            )
            current = normalize_coalition(
                payload.get("coalition") or opszone.get("owner_current_name")
            )
            actor = normalize_coalition(payload.get("capturing_coalition")) or current
            opszone_id = str(payload.get("opszone_id") or opszone.get("object_id") or "")
            mission_time = _optional_float(message.get("mission_time"))
            opponent = "red" if actor == "blue" else "blue" if actor == "red" else None
            if (
                opszone_id.startswith("OPSZONE:")
                and current in {"blue", "red"}
                and actor == current
                and previous != current
                and opponent is not None
            ):
                x = _optional_float(opszone.get("x"))
                z = _optional_float(opszone.get("z"))
                territory = _territory_at_point(self.state.territory_objects.values(), x, z)
                reference_points = self.relationship.get_opszone_capture_points(opszone_id)
                multiplier, factors = opszone_capture_multiplier(
                    reference_points=reference_points,
                    previous_coalition=previous,
                    capturing_coalition=actor,
                    territory_coalition=territory.coalition if territory else None,
                )
                stable_source = (
                    f"{opszone_id}:{previous or 'unknown'}:{current}:"
                    f"{_incident_mission_time(mission_time)}"
                )
                self.record_escalation_incident(
                    EscalationIncident(
                        incident_id=f"INCIDENT:OPSZONE_CAPTURE:{stable_source}",
                        incident_type=EscalationIncidentType.OPSZONE_CAPTURED,
                        actor_coalition=actor,
                        target_coalition=previous if previous in {"blue", "red"} else opponent,
                        mission_time=mission_time,
                        reference_id=opszone_id,
                        multiplier=multiplier,
                        details={
                            "opszone_id": opszone_id,
                            "opszone_name": opszone.get("name") or opszone.get("dcs_name"),
                            "previous_coalition": previous,
                            "coalition": current,
                            "territory_id": territory.object_id if territory else None,
                            "territory_coalition": territory.coalition if territory else None,
                            **factors,
                            "source_event": event_name,
                        },
                    )
                )
        if (
            message_type == "event" and event_name.startswith("intel.")
            or message_type == "snapshot" and kind == "intel_contacts"
        ):
            self.information_requirement_registry.sync(
                self.state,
                source=event_name or "snapshot.intel_contacts",
            )
            if message_type == "event" and feedback_message_is_new:
                payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
                contact = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
                self.strategic_feedback.record_context_change(
                    "feedback.intelligence_changed",
                    source=event_name,
                    mission_time=self._current_mission_time(),
                    coalition=normalize_coalition(contact.get("coalition")),
                    reference_id=str(
                        contact.get("target_object_id")
                        or contact.get("object_id")
                        or payload.get("contact_id")
                        or ""
                    ) or None,
                    details={"intel_event": event_name},
                )
        if message_type == "heartbeat":
            self.goals.sync(mission_time=self._current_mission_time(), source="heartbeat")
            self.sync_strategic_feedback(source="heartbeat")
            self.sync_border_violations()
            return
        relevant_event = message_type == "event" and event_name in {
            "object.destroyed",
            "airbase.coalition_changed",
            "opszone.owner_changed",
            "opszone.coalition_changed",
            "territory.coalition_changed",
        }
        if relevant_event or (message_type == "snapshot" and kind in {
            "airbases",
            "opszones",
            "territories",
            "groups",
            "units",
            "statics",
        }):
            source = event_name or f"snapshot.{kind}"
            objective_events = self.objectives.sync(self.state, source=source)
            self.goals.sync(mission_time=self._current_mission_time(), source=source)
            for objective_event in objective_events:
                self.strategic_feedback.record_context_change(
                    "feedback.objective_changed",
                    source=source,
                    mission_time=objective_event.mission_time,
                    reference_id=objective_event.objective_id,
                    details={"objective_event": objective_event.event},
                )
        should_reassess_plans = relevant_event or (
            message_type == "snapshot"
            and kind in {
                "airbases",
                "opszones",
                "territories",
                "groups",
                "units",
                "statics",
                "legions",
                "cohorts",
                "commanders",
            }
        )
        if should_reassess_plans:
            self.sync_strategic_feedback(source=event_name or f"snapshot.{kind}")
        if message_type == "snapshot" and kind in {"groups", "territories"}:
            self.sync_border_violations()
        if message_type == "event" and event_name == "auftrag.evaluated" and feedback_message_is_new:
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            self.strategic_feedback.record_context_change(
                "feedback.mission_outcome",
                source=event_name,
                mission_time=self._current_mission_time(),
                reference_id=str(payload.get("auftrag_id") or "") or None,
                details={
                    "auftrag_type": payload.get("auftrag_type"),
                    "success": (
                        payload.get("summary", {}).get("success")
                        if isinstance(payload.get("summary"), dict)
                        else None
                    ),
                },
            )

    def _current_mission_time(self) -> float | None:
        return self.state.clock.mission_time if self.state.clock else None

    def territories(self, coalition: str | None = None) -> list[Territory]:
        """Return known territories, optionally limited to one coalition."""

        territories = list(self.state.territory_objects.values())
        if coalition is None:
            return territories
        return [territory for territory in territories if _same_coalition(territory.coalition, coalition)]

    def build_strategic_scope(self, *, strict: bool = True) -> StrategicTerritoryScope:
        """Build mission scope from red, blue, and neutral territories."""

        return build_strategic_territory_scope(
            self.state.territory_objects.values(),
            config=self.strategic_scope_config,
            strict=strict,
        )

    def opsgroup(self, object_id: str) -> OpsGroup | None:
        """Return a typed OPSGROUP by object id.

        :param object_id: Stable bridge object id such as ``OPSGROUP:Aerial-1``.
        :returns: Typed OPSGROUP or ``None``.
        """

        return self.state.opsgroup(object_id)

    def unit_ammunition(self, unit_id: str) -> UnitAmmunition | None:
        """Return the latest detailed ammunition state for one unit."""

        normalized = unit_id if unit_id.startswith("UNIT:") else f"UNIT:{unit_id}"
        return self.state.ammunition_objects.get(normalized)

    def group_ammunition(self, group_id: str) -> list[UnitAmmunition]:
        """Return ammunition states for units belonging to one group."""

        normalized = group_id if group_id.startswith("GROUP:") else f"GROUP:{group_id}"
        return sorted(
            (item for item in self.state.ammunition_objects.values() if item.group_id == normalized),
            key=lambda item: item.unit_id,
        )

    def group_task_weapon(
        self,
        group_id: str,
        *,
        role: WeaponRole | str | None = None,
    ) -> TaskWeaponSelection:
        """Recommend a DCS task ``weaponType`` from available group ammunition."""

        weapons = (weapon for unit in self.group_ammunition(group_id) for weapon in unit.weapons)
        return select_task_weapon(weapons, role=role)

    def unit_weapon_range(
        self,
        unit_id: str,
        weapon_flag: DcsWeaponFlag | int,
    ) -> WeaponRangeProfile | None:
        """Resolve a task weapon range for one unit from current ammunition data."""

        ammunition = self.unit_ammunition(unit_id)
        if ammunition is None or not ammunition.dcs_type:
            return None
        return self.weapon_range_registry.resolve(
            ammunition.dcs_type,
            weapon_flag,
            ammunition=ammunition.weapons,
        )

    def group_weapon_ranges(
        self,
        group_id: str,
        weapon_flag: DcsWeaponFlag | int,
    ) -> tuple[WeaponRangeProfile, ...]:
        """Resolve task ranges for the distinct unit types present in a group."""

        profiles: dict[tuple[str, DcsWeaponFlag, float, float, RangeSource], WeaponRangeProfile] = {}
        for unit in self.group_ammunition(group_id):
            if not unit.dcs_type:
                continue
            profile = self.weapon_range_registry.resolve(unit.dcs_type, weapon_flag, ammunition=unit.weapons)
            if profile is not None:
                key = (profile.dcs_type, profile.weapon_flag, profile.minimum_m, profile.maximum_m, profile.source)
                profiles[key] = profile
        return tuple(sorted(profiles.values(), key=lambda item: (item.dcs_type.casefold(), item.minimum_m, item.maximum_m)))

    def sensor_ranges_for_type(
        self,
        dcs_type: str,
        *,
        target_domain: SensorTargetDomain | str | None = None,
    ) -> tuple[SensorRangeProfile, ...]:
        """Return known optimistic sensor bounds for one DCS unit type."""

        return self.sensor_range_registry.profiles_for(dcs_type, target_domain=target_domain)

    def unit_sensor_ranges(
        self,
        unit_id: str,
        *,
        target_domain: SensorTargetDomain | str | None = None,
    ) -> tuple[SensorRangeProfile, ...]:
        """Return known optimistic sensor bounds for one mirrored unit."""

        dcs_type = self._unit_dcs_type(unit_id)
        return self.sensor_ranges_for_type(str(dcs_type), target_domain=target_domain) if dcs_type else ()

    def _unit_dcs_type(self, unit_id: str) -> str | None:
        normalized = unit_id if unit_id.startswith("UNIT:") else f"UNIT:{unit_id}"
        payload = self.state.units.get(normalized)
        dcs_type = payload.get("dcs_type") if payload else None
        if not dcs_type:
            ammunition = self.unit_ammunition(normalized)
            dcs_type = ammunition.dcs_type if ammunition else None
        return str(dcs_type) if dcs_type else None

    def group_sensor_ranges(
        self,
        group_id: str,
        *,
        target_domain: SensorTargetDomain | str | None = None,
    ) -> tuple[SensorRangeProfile, ...]:
        """Return distinct sensor bounds for all currently mirrored units in a group."""

        normalized = group_id if group_id.startswith("GROUP:") else f"GROUP:{group_id}"
        group_name = normalized.removeprefix("GROUP:")
        unit_ids = {
            object_id
            for object_id, payload in self.state.units.items()
            if payload.get("group_id") == normalized or payload.get("group_name") == group_name
        }
        unit_ids.update(item.unit_id for item in self.group_ammunition(normalized))
        profiles = {
            profile
            for unit_id in unit_ids
            for profile in self.unit_sensor_ranges(unit_id, target_domain=target_domain)
        }
        return tuple(
            sorted(
                profiles,
                key=lambda item: (
                    item.dcs_type.casefold(),
                    item.detection_type.value,
                    item.target_domain.value,
                    item.mode or "",
                ),
            )
        )

    def unit_detection_excluded(
        self,
        unit_id: str,
        distance_m: float,
        *,
        target_domain: SensorTargetDomain | str | None = None,
    ) -> bool | None:
        """Return whether known organic bounds rule out detection by a unit.

        ``None`` means that no applicable bound is known. ``False`` only means
        that detection is possible; terrain, aspect and DCS sensor logic still
        decide whether it actually happens.
        """

        dcs_type = self._unit_dcs_type(unit_id)
        if dcs_type is None:
            return None
        return self.sensor_range_registry.excludes(dcs_type, distance_m, target_domain=target_domain)

    def unit_sensor_detection_excluded(
        self,
        unit_id: str,
        detection_type: SensorDetectionType | str,
        distance_m: float,
        *,
        target_domain: SensorTargetDomain | str | None = None,
        mode: str | None = None,
    ) -> bool | None:
        """Return whether one sensor mechanism safely excludes detection."""

        dcs_type = self._unit_dcs_type(unit_id)
        if dcs_type is None:
            return None
        return self.sensor_range_registry.sensor_excludes(
            dcs_type,
            detection_type,
            distance_m,
            target_domain=target_domain,
            mode=mode,
        )

    def unit_capabilities(self, unit_id: str) -> UnitCapabilities | None:
        """Build current combat capability readiness for one unit."""

        ammunition = self.unit_ammunition(unit_id)
        return build_unit_capabilities(ammunition) if ammunition else None

    def group_capabilities(self, group_id: str) -> GroupCapabilities:
        """Build aggregated combat capability readiness for one group."""

        normalized = group_id if group_id.startswith("GROUP:") else f"GROUP:{group_id}"
        return build_group_capabilities(self.group_ammunition(normalized), normalized)

    def unit_influence(self, unit_id: str) -> UnitInfluence | None:
        """Build separated tactical influences for one unit."""

        ammunition = self.unit_ammunition(unit_id)
        return (
            build_unit_influence(ammunition, weapon_ranges=self.weapon_range_registry)
            if ammunition else None
        )

    def group_influence(self, group_id: str) -> GroupInfluence:
        """Build aggregated tactical influences for one group."""

        normalized = group_id if group_id.startswith("GROUP:") else f"GROUP:{group_id}"
        return build_group_influence(
            self.group_ammunition(normalized),
            normalized,
            weapon_ranges=self.weapon_range_registry,
        )

    def auftrag(self, object_id: str) -> Auftrag | None:
        """Return a typed AUFTRAG by object id.

        :param object_id: Stable bridge object id such as ``AUFTRAG:1``.
        :returns: Typed AUFTRAG or ``None``.
        """

        return self.state.auftrag(object_id)

    def legion(self, object_id: str) -> Legion | None:
        """Return a typed LEGION by object id.

        :param object_id: Stable bridge object id such as ``LEGION:Wing Parchim``.
        :returns: Typed LEGION or ``None``.
        """

        return self.state.legion(object_id)

    def commander(self, object_id: str) -> Commander | None:
        """Return a typed COMMANDER by stable object id."""

        return self.state.commander(object_id)

    def commanders(self, coalition: str | None = None) -> list[Commander]:
        """Return mirrored COMMANDER objects, optionally for one coalition."""

        items = list(self.state.commander_objects.values())
        if coalition is not None:
            normalized = coalition.strip().lower()
            items = [item for item in items if (item.coalition or "").strip().lower() == normalized]
        return sorted(items, key=lambda item: item.object_id)

    def commander_for_coalition(self, coalition: str) -> Commander:
        """Return the unique COMMANDER for a coalition.

        :raises ValueError: If no COMMANDER or more than one COMMANDER matches.
        """

        matches = self.commanders(coalition)
        if not matches:
            raise ValueError(f"No COMMANDER snapshot is available for coalition {coalition!r}")
        if len(matches) > 1:
            ids = ", ".join(item.object_id for item in matches)
            raise ValueError(f"Multiple COMMANDER objects exist for coalition {coalition!r}: {ids}")
        return matches[0]

    def cohort(self, object_id: str) -> Cohort | None:
        """Return a typed COHORT by object id.

        :param object_id: Stable bridge object id such as ``COHORT:F-18 Parchim Alpha``.
        :returns: Typed COHORT or ``None``.
        """

        return self.state.cohort(object_id)

    async def set_cohort_weapon_range(
        self,
        cohort_id: str,
        weapon_type: DcsWeaponFlag | int,
        minimum_m: float,
        maximum_m: float,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Configure one MOOSE COHORT weapon range from Python range data."""

        normalized_type = int(weapon_type)
        minimum = float(minimum_m)
        maximum = float(maximum_m)
        if normalized_type < 0:
            raise ValueError("weapon_type must be non-negative")
        if not math.isfinite(minimum) or not math.isfinite(maximum) or minimum < 0 or maximum <= 0:
            raise ValueError("weapon range must be finite with minimum >= 0 and maximum > 0")
        if minimum > maximum:
            raise ValueError("weapon range minimum must not exceed maximum")
        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(
                    action="cohort.set_weapon_range",
                    params={
                        "cohort_id": cohort_id,
                        "weapon_type": normalized_type,
                        "minimum_m": minimum,
                        "maximum_m": maximum,
                    },
                ),
                timeout=timeout,
            )
        )
        cohort = self.cohort(cohort_id)
        result = ack.get("result") if isinstance(ack.get("result"), Mapping) else {}
        if cohort is not None:
            cohort.weapon_ranges_by_type[str(normalized_type)] = (minimum, maximum)
            mission_range = result.get("mission_range_m")
            if isinstance(mission_range, (int, float)):
                cohort.mission_ranges_by_weapon_type[str(normalized_type)] = float(mission_range)
        return ack

    def intel(self, object_id: str) -> Intel | None:
        """Return a typed INTEL object by object id.

        :param object_id: Stable INTEL object id such as ``INTEL:BlueIntel``.
        :returns: Typed INTEL object or ``None``.
        """

        return self.state.intel(object_id)

    def contacts_of_intel(self, intel_id: str) -> list[IntelContact]:
        """Return typed contacts belonging to an INTEL object."""

        return self.state.contacts_for_intel(intel_id)

    def clusters_of_intel(self, intel_id: str) -> list[IntelCluster]:
        """Return typed clusters belonging to an INTEL object."""

        return self.state.clusters_for_intel(intel_id)

    def cohorts_of_legion(self, legion_id: str) -> list[Cohort]:
        """Return typed COHORT objects belonging to a LEGION.

        :param legion_id: Stable LEGION object id.
        :returns: COHORT objects present in the local state mirror.
        """

        return self.state.cohorts_for_legion(legion_id)

    def missions_of_legion(self, legion_id: str) -> list[Auftrag]:
        """Return queued mission objects for a LEGION.

        The returned objects are the typed AUFTRAG models mirrored from DCS, but
        the SDK exposes them as missions for English-facing code.

        :param legion_id: Stable LEGION object id.
        :returns: Queued mission objects present in the local state mirror.
        """

        return self.state.queued_auftraege_for_legion(legion_id)

    def legions_of_commander(self, commander_id: str) -> list[Legion]:
        """Return mirrored LEGION objects assigned to a COMMANDER."""

        return self.state.legions_for_commander(commander_id)

    def missions_of_commander(self, commander_id: str) -> list[Auftrag]:
        """Return queued mission objects for a COMMANDER."""

        return self.state.queued_auftraege_for_commander(commander_id)

    def missions_of_group(self, opsgroup_id: str) -> list[Auftrag]:
        """Return queued mission objects for an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Queued mission objects present in the local state mirror.
        """

        return self.state.queued_auftraege_for_group(opsgroup_id)

    def ready_cohorts_of_legion(
        self,
        legion_id: str,
        mission_type: str | None = None,
        require_available: bool = True,
    ) -> list[Cohort]:
        """Return COHORTs of a LEGION that are ready for optional mission work.

        :param legion_id: Stable LEGION object id.
        :param mission_type: Optional AUFTRAG mission type filter such as ``BAI``.
        :param require_available: If ``True``, require at least one unrequested and unreserved asset.
        :returns: Matching COHORTs from the local state mirror.
        """

        cohorts = self.cohorts_of_legion(legion_id)
        if mission_type:
            mission_key = mission_type.strip().upper()
            cohorts = [cohort for cohort in cohorts if mission_key in {key.upper() for key in cohort.mission_type_keys}]
        if require_available:
            cohorts = [cohort for cohort in cohorts if (cohort.available_asset_count or 0) > 0]
        return cohorts

    def available_missions_of_cohort(self, cohort_id: str, require_payload: bool = False) -> list[str]:
        """Return mission type keys a COHORT can currently advertise.

        :param cohort_id: Stable COHORT object id.
        :param require_payload: If ``True``, keep only mission types with known positive payload availability.
        :returns: Mission type keys such as ``BAI`` or ``CAPTUREZONE``.
        """

        cohort = self.cohort(cohort_id)
        if not cohort:
            return []
        if not require_payload:
            return list(cohort.mission_type_keys)
        return [mission_type for mission_type in cohort.mission_type_keys if cohort.has_payload_for(mission_type) is True]

    def current_auftrag_for_group(self, opsgroup_id: str) -> Auftrag | None:
        """Return the current AUFTRAG assigned to an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Typed AUFTRAG or ``None``.
        """

        return self.state.current_auftrag_for_group(opsgroup_id)

    def queued_auftraege_for_group(self, opsgroup_id: str) -> list[Auftrag]:
        """Return queued AUFTRAG objects for an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Typed AUFTRAG objects present in the local state mirror.
        """

        return self.state.queued_auftraege_for_group(opsgroup_id)

    def build_tactical_picture(self, coalition: str, intel: str) -> TacticalPicture:
        """Build a coalition/INTEL based situation picture from local state.

        Enemy knowledge comes from INTEL contacts and clusters. Friendly assets
        come from the coalition's LEGION/COHORT/OPSGROUP snapshots.

        :param coalition: Friendly coalition, e.g. ``blue`` or ``red``.
        :param intel: INTEL object id such as ``INTEL:BlueIntel``.
        :returns: Tactical picture with GeoJSON export support.
        """

        legions = [
            legion
            for legion in self.state.legion_objects.values()
            if _same_coalition(legion.coalition or legion.coalition_name, coalition)
        ]
        legion_ids = {legion.object_id for legion in legions}
        opsgroups = [group for group in self.state.opsgroup_objects.values() if _same_coalition(group.coalition, coalition)]
        opsgroup_ids = {group.object_id for group in opsgroups}
        cohorts = [cohort for cohort in self.state.cohort_objects.values() if cohort.legion_id in legion_ids]
        contacts = self.contacts_of_intel(intel)
        lost_contacts = self.state.lost_contacts_for_intel(intel)
        clusters = self.clusters_of_intel(intel)

        mission_ids: set[str] = set()
        for legion in legions:
            mission_ids.update(legion.auftrag_queue_ids)
        for group in opsgroups:
            if group.auftrag_current_id:
                mission_ids.add(group.auftrag_current_id)
            mission_ids.update(group.auftrag_queue_ids)
        for contact in contacts:
            if contact.mission_id:
                mission_ids.add(contact.mission_id)
        for cluster in clusters:
            if cluster.mission_id:
                mission_ids.add(cluster.mission_id)

        missions = _unique_missions(
            mission
            for mission in self.state.auftrag_objects.values()
            if mission.object_id in mission_ids or any(group_id in opsgroup_ids for group_id in mission.assigned_group_ids)
        )
        coalition_name = coalition.lower().strip()
        loss_reports = [
            report
            for report in self.state.loss_reports.values()
            if coalition_name in {str(side).lower() for side in report.get("visible_to", [])}
        ]

        return TacticalPicture(
            coalition=coalition,
            intel_id=intel,
            clock=self.state.clock,
            intel=self.intel(intel),
            contacts=contacts,
            lost_contacts=lost_contacts,
            clusters=clusters,
            opszones=list(self.state.opszone_objects.values()),
            opsgroups=opsgroups,
            legions=legions,
            cohorts=cohorts,
            missions=missions,
            loss_reports=loss_reports,
        )

    def build_global_picture(self) -> GlobalPicture:
        """Build a global/admin situation picture from local truth snapshots."""

        return GlobalPicture(
            clock=self.state.clock,
            groups=list(self.state.groups.values()),
            units=list(self.state.units.values()),
            statics=list(self.state.statics.values()),
            airbases=list(self.state.airbases.values()),
            zones=list(self.state.zones.values()),
            territories=list(self.state.territory_objects.values()),
            opszones=list(self.state.opszone_objects.values()),
            opsgroups=list(self.state.opsgroup_objects.values()),
            missions=list(self.state.auftrag_objects.values()),
            legions=list(self.state.legion_objects.values()),
            cohorts=list(self.state.cohort_objects.values()),
            intels=list(self.state.intel_objects.values()),
            intel_contacts=list(self.state.intel_contact_objects.values()),
            intel_clusters=list(self.state.intel_cluster_objects.values()),
            loss_reports=list(self.state.loss_reports.values()),
            strategic_objectives=list(self.strategic_objectives()),
            strategic_scope=self.build_strategic_scope(strict=False),
        )

    async def request_snapshots(self, actions: tuple[str, ...]) -> None:
        """Request a sequence of bridge snapshots.

        :param actions: Snapshot command actions.
        :raises MooseBridgeCommandError: If any snapshot command is rejected.
        """

        for action in actions:
            require_ok(await self.server.send_command(BridgeCommand(action=action, params={})))
            await asyncio.sleep(0.05)

    async def refresh_legion_state(self) -> MooseBridgeState:
        """Refresh LEGION, COHORT and mission snapshots.

        :returns: Updated local state mirror.
        """

        await self.snapshot_commanders()
        await self.snapshot_legions()
        await self.snapshot_cohorts()
        await self.snapshot_auftraege()
        return self.state

    async def refresh_ops_state(self) -> MooseBridgeState:
        """Refresh the commonly used OPS state snapshots.

        :returns: Updated local state mirror.
        """

        await self.snapshot_opszones()
        await self.snapshot_opsgroups()
        await self.snapshot_auftraege()
        await self.snapshot_commanders()
        await self.snapshot_legions()
        await self.snapshot_cohorts()
        return self.state

    async def refresh_territory_state(self) -> MooseBridgeState:
        """Refresh passive strategic TERRITORY snapshots."""

        await self.snapshot_territories()
        return self.state

    async def refresh_intel_state(self) -> MooseBridgeState:
        """Refresh registered INTEL objects, contacts and clusters."""

        await self.snapshot_intels()
        await self.snapshot_intel_contacts()
        await self.snapshot_intel_clusters()
        return self.state

    async def refresh_tactical_picture(self, coalition: str, intel: str) -> TacticalPicture:
        """Refresh the snapshots needed for a tactical picture and build it."""

        await self.snapshot_intels()
        await self.snapshot_intel_contacts()
        await self.snapshot_intel_clusters()
        await self.snapshot_opszones()
        await self.snapshot_opsgroups()
        await self.snapshot_auftraege()
        await self.snapshot_legions()
        await self.snapshot_cohorts()
        return self.build_tactical_picture(coalition, intel)

    async def refresh_global_picture(self) -> GlobalPicture:
        """Refresh and build a global/admin picture."""

        await self.snapshot_all()
        return self.build_global_picture()

    async def snapshot_groups(self) -> dict[str, Any]:
        """Request a GROUP snapshot through the SDK."""

        return require_ok(await self.server.snapshot_groups())

    async def snapshot_units(self) -> dict[str, Any]:
        """Request a UNIT snapshot through the SDK."""

        return require_ok(await self.server.snapshot_units())

    async def snapshot_ammunition(self) -> dict[str, Any]:
        """Request detailed ammunition for active, living ground and naval units."""

        return require_ok(await self.server.snapshot_ammunition())

    async def refresh_ammunition(self) -> tuple[UnitAmmunition, ...]:
        """Refresh and return typed unit ammunition sorted by object id."""

        await self.snapshot_ammunition()
        return tuple(sorted(self.state.ammunition_objects.values(), key=lambda item: item.unit_id))

    async def snapshot_statics(self) -> dict[str, Any]:
        """Request a STATIC snapshot through the SDK."""

        return require_ok(await self.server.snapshot_statics())

    async def snapshot_airbases(self) -> dict[str, Any]:
        """Request an AIRBASE snapshot through the SDK."""

        return require_ok(await self.server.snapshot_airbases())

    async def snapshot_zones(self) -> dict[str, Any]:
        """Request a ZONE snapshot through the SDK."""

        return require_ok(await self.server.snapshot_zones())

    async def snapshot_territories(self) -> dict[str, Any]:
        """Request a TERRITORY snapshot through the SDK."""

        return require_ok(await self.server.snapshot_territories())

    async def snapshot_opszones(self) -> dict[str, Any]:
        """Request an OPSZONE snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_opszones())

    async def snapshot_opsgroups(self) -> dict[str, Any]:
        """Request an OPSGROUP snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_opsgroups())

    async def snapshot_auftraege(self) -> dict[str, Any]:
        """Request an AUFTRAG snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_auftraege())

    async def snapshot_cohorts(self) -> dict[str, Any]:
        """Request a COHORT snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_cohorts())

    async def snapshot_legions(self) -> dict[str, Any]:
        """Request a LEGION snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_legions())

    async def snapshot_commanders(self) -> dict[str, Any]:
        """Request a COMMANDER snapshot through the SDK."""

        return require_ok(await self.server.snapshot_commanders())

    async def snapshot_intels(self) -> dict[str, Any]:
        """Request an INTEL snapshot through the SDK."""

        return require_ok(await self.server.snapshot_intels())

    async def get_time(self, timeout: float = 10.0) -> DcsTime:
        """Read mission elapsed time, DCS world time and UTC wall time."""

        ack = require_ok(await self.server.send_command(BridgeCommand(action="time.get", params={}), timeout=timeout))
        return DcsTime.from_message(ack)

    async def snapshot_intel_contacts(self) -> dict[str, Any]:
        """Request an INTEL contact snapshot through the SDK."""

        return require_ok(await self.server.snapshot_intel_contacts())

    async def snapshot_intel_clusters(self) -> dict[str, Any]:
        """Request an INTEL cluster snapshot through the SDK."""

        return require_ok(await self.server.snapshot_intel_clusters())

    async def add_intel_agent(self, intel: Intel | str, agent: OpsGroup | str, timeout: float = 10.0) -> dict[str, Any]:
        """Add a GROUP or OPSGROUP to a registered MOOSE INTEL detection set.

        :param intel: Mirrored INTEL object or stable ``INTEL:<name>`` id.
        :param agent: Mirrored OPSGROUP object or ``GROUP:<name>``/``OPSGROUP:<name>`` id.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload including current agent counts.
        :raises ValueError: If an object id has an unsupported type.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        intel_id = intel.object_id if isinstance(intel, Intel) else intel
        agent_id = agent.object_id if isinstance(agent, OpsGroup) else agent
        if not intel_id.startswith("INTEL:"):
            raise ValueError("intel must be an INTEL:<name> object id")
        if not agent_id.startswith(("GROUP:", "OPSGROUP:")):
            raise ValueError("agent must be a GROUP:<name> or OPSGROUP:<name> object id")
        return require_ok(
            await self.server.send_command(
                BridgeCommand(action="intel.add_agent", params={"intel_id": intel_id, "agent_id": agent_id}),
                timeout=timeout,
            )
        )

    async def snapshot_objects(self) -> dict[str, Any]:
        """Request a combined object snapshot through the SDK."""

        return require_ok(await self.server.send_command(BridgeCommand(action="snapshot.objects", params={})))

    async def snapshot_all(self) -> dict[str, Any]:
        """Request all supported snapshots through the SDK."""

        return require_ok(await self.server.send_command(BridgeCommand(action="snapshot.all", params={})))

    async def snapshot_kind(self, kind: str) -> dict[str, Any]:
        """Request one snapshot by short kind name."""

        normalized = kind.removeprefix("snapshot.").lower().strip()
        if normalized not in SNAPSHOT_KINDS:
            raise ValueError(f"Unsupported snapshot kind: {kind!r}. Expected one of {sorted(SNAPSHOT_KINDS)}")
        method = getattr(self, f"snapshot_{normalized}", None)
        if method is not None:
            return await method()
        return require_ok(await self.server.send_command(BridgeCommand(action=f"snapshot.{normalized}", params={})))

    async def request_ops_state(self) -> MooseBridgeState:
        """Request OPS snapshots and return the updated local state mirror.

        :returns: Updated local state mirror.
        :raises MooseBridgeCommandError: If DCS rejects one of the snapshot commands.
        """

        await self.snapshot_opszones()
        await self.snapshot_opsgroups()
        await self.snapshot_auftraege()
        await asyncio.sleep(0.1)
        return self.state

    async def apply_auftrag(self, mission_type: str, params: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        """Apply an AUFTRAG command to DCS.

        :param mission_type: Mission type such as ``BAI`` or ``Bombing``.
        :param params: Flat command parameters accepted by the Lua extension.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        action = auftrag_action_for_mission_type(mission_type)
        clean_params = {key: value for key, value in params.items() if value is not None}
        return require_ok(await self.server.send_command(BridgeCommand(action=action, params=clean_params), timeout=timeout))

    def _auftrag_assignment_params(
        self,
        *,
        commander: str | None,
        legion: str | None,
        opsgroup: str | None,
        cohort: str | None,
        coalition: str | None,
        allowed_legions: Iterable[str] | None,
        allowed_cohorts: Iterable[str] | None,
    ) -> dict[str, Any]:
        """Validate and normalize one AUFTRAG assignment target."""

        if coalition is not None:
            if any(value is not None for value in (commander, legion, opsgroup)):
                raise ValueError("coalition cannot be combined with an explicit assignment target")
            commander = self.commander_for_coalition(coalition).object_id

        targets = [value for value in (commander, legion, opsgroup) if value is not None]
        if len(targets) != 1:
            raise ValueError("Specify exactly one of commander, legion or opsgroup")

        legion_constraints = list(dict.fromkeys(allowed_legions or ()))
        cohort_constraints = [item for item in dict.fromkeys(allowed_cohorts or ()) if item != cohort]
        if legion_constraints and commander is None:
            raise ValueError("allowed_legions requires commander tasking")
        if (cohort is not None or cohort_constraints) and opsgroup is not None:
            raise ValueError("COHORT constraints cannot be used with OPSGROUP tasking")

        return clean_params(
            {
                "commander_id": commander,
                "legion_id": legion,
                "opsgroup_id": opsgroup,
                "cohort_id": cohort,
                "allowed_legion_ids": legion_constraints or None,
                "allowed_cohort_ids": cohort_constraints or None,
            }
        )

    async def add_auftrag(
        self,
        auftrag: AuftragCommand,
        *,
        commander: str | None = None,
        legion: str | None = None,
        opsgroup: str | None = None,
        cohort: str | None = None,
        coalition: str | None = None,
        allowed_legions: Iterable[str] | None = None,
        allowed_cohorts: Iterable[str] | None = None,
        selected_payload_uid: int | str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Create an AUFTRAG and add it to a COMMANDER, LEGION or OPSGROUP.

        :param auftrag: Python-side AUFTRAG description, e.g. ``Auftrag_BAI``.
        :param commander: Target COMMANDER object id. It chooses suitable LEGIONs by default.
        :param legion: Target LEGION object id.
        :param opsgroup: Target OPSGROUP object id.
        :param cohort: Optional single COHORT constraint kept for concise tasking.
        :param coalition: Select the coalition's unique mirrored COMMANDER when no target is explicit.
        :param allowed_legions: Optional LEGION constraints for COMMANDER recruitment.
        :param allowed_cohorts: Optional COHORT constraints for COMMANDER or LEGION recruitment.
        :param selected_payload_uid: Optional selected payload UID.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises ValueError: If assignment targets or constraints are inconsistent.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        params = auftrag.to_params()
        params.update(auftrag.timing_params())
        params.update(
            self._auftrag_assignment_params(
                commander=commander,
                legion=legion,
                opsgroup=opsgroup,
                cohort=cohort,
                coalition=coalition,
                allowed_legions=allowed_legions,
                allowed_cohorts=allowed_cohorts,
            )
        )
        if selected_payload_uid is not None:
            params["selected_payload_uid"] = selected_payload_uid
        ack = await self.apply_auftrag(auftrag.mission_type, params, timeout=timeout)
        auftrag_id = auftrag_id_from_ack(ack)
        if auftrag_id:
            self._auftrag_ids_by_object[id(auftrag)] = auftrag_id
        return ack

    @staticmethod
    def _recon_requires_spatial_tracking(requirement: ReconRequirement | None) -> bool:
        return requirement is not None and (
            requirement.minimum_area_coverage > 0
            or requirement.minimum_component_coverage > 0 and bool(requirement.coverage_points)
        )

    async def sample_recon_tracking(self, session: ReconTrackingSession) -> None:
        """Sample groups assigned to a RECON without owning INTEL detection."""

        if not session.assigned_group_ids:
            await self.snapshot_auftraege()
            await self.snapshot_opsgroups()
            snapshot = self.auftrag(session.auftrag_id)
            if snapshot is not None:
                session.assigned_opsgroup_ids = tuple(snapshot.assigned_group_ids)
                group_ids: list[str] = []
                for opsgroup_id in session.assigned_opsgroup_ids:
                    opsgroup = self.opsgroup(opsgroup_id)
                    group_name = opsgroup.group_name if opsgroup and opsgroup.group_name else opsgroup_id.removeprefix("OPSGROUP:")
                    group_ids.append(f"GROUP:{group_name}")
                session.assigned_group_ids = tuple(group_ids)
        await self.snapshot_groups()
        mission_time = self.state.clock.mission_time if self.state.clock else None
        if mission_time is None:
            return
        for group_id in session.assigned_group_ids:
            payload = self.state.groups.get(group_id)
            if not payload or payload.get("alive") is False:
                continue
            try:
                sample = ReconTrackSample(group_id, mission_time, float(payload["x"]), float(payload["z"]))
            except (KeyError, TypeError, ValueError):
                continue
            samples = session.tracks.setdefault(group_id, [])
            if not samples or (samples[-1].mission_time, samples[-1].x, samples[-1].z) != (
                sample.mission_time,
                sample.x,
                sample.z,
            ):
                samples.append(sample)

    async def monitor_recon_tracking(
        self,
        session: ReconTrackingSession,
        stop: asyncio.Event,
        *,
        interval_s: float = 10.0,
    ) -> None:
        """Periodically sample a spatial RECON route until explicitly stopped."""

        while not stop.is_set():
            await self.sample_recon_tracking(session)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            except TimeoutError:
                pass

    async def assess_recon_tracking(
        self,
        requirement: ReconRequirement,
        session: ReconTrackingSession,
    ) -> ReconSpatialCoverage:
        """Assess one sampled route with the same logic for every RECON caller."""

        await self.snapshot_zones()
        await self.snapshot_opszones()
        await self.snapshot_statics()
        await self.snapshot_airbases()
        await self.snapshot_groups()
        await self.snapshot_units()
        sensor_ranges = {
            group_id: max(
                (
                    profile.maximum_m
                    for profile in self.group_sensor_ranges(group_id, target_domain="surface")
                    if profile.maximum_m is not None
                ),
                default=None,
            )
            for group_id in session.tracks
        }
        return assess_recon_spatial_coverage(
            requirement,
            self._resolve_recon_area(requirement.area_object_id),
            {group_id: tuple(samples) for group_id, samples in session.tracks.items()},
            sensor_ranges,
            self._resolve_recon_coverage_point_positions(requirement),
        )

    def _resolve_recon_area(self, object_id: str) -> ReconArea | None:
        payload: dict[str, Any] | None = None
        if object_id.startswith("ZONE:"):
            payload = self.state.zones.get(object_id)
        elif object_id.startswith("OPSZONE:"):
            zone = self.state.opszone_objects.get(object_id)
            if zone and zone.zone_name:
                payload = self.state.zones.get(f"ZONE:{zone.zone_name}")
            if payload is None and zone is not None:
                return ReconArea(object_id, zone.x, zone.z, zone.zone_radius)
        if payload is None:
            return None
        vertices = tuple(
            (float(item["x"]), float(item["z"]))
            for item in payload.get("vertices", ())
            if isinstance(item, dict) and item.get("x") is not None and item.get("z") is not None
        )
        return ReconArea(
            object_id,
            float(payload["x"]) if payload.get("x") is not None else None,
            float(payload["z"]) if payload.get("z") is not None else None,
            float(payload["radius"]) if payload.get("radius") is not None else None,
            vertices,
        )

    def _resolve_recon_coverage_point_positions(
        self,
        requirement: ReconRequirement,
    ) -> dict[str, tuple[float, float]]:
        collections = (
            self.state.airbases,
            self.state.statics,
            self.state.zones,
            self.state.groups,
            self.state.units,
            self.state.opszones,
            self.state.territories,
        )
        positions: dict[str, tuple[float, float]] = {}
        for point in requirement.coverage_points:
            payload = next((items.get(point.object_id) for items in collections if point.object_id in items), None)
            if not payload:
                continue
            try:
                positions[point.object_id] = (float(payload["x"]), float(payload["z"]))
            except (KeyError, TypeError, ValueError):
                continue
        return positions

    async def execute_recon(
        self,
        auftrag: AuftragCommand,
        *,
        intel: str,
        commander: str | None = None,
        legion: str | None = None,
        opsgroup: str | None = None,
        cohort: str | None = None,
        coalition: str | None = None,
        allowed_legions: Iterable[str] | None = None,
        allowed_cohorts: Iterable[str] | None = None,
        selected_payload_uid: int | str | None = None,
        relevant_target_ids: Iterable[str] = (),
        requirement: ReconRequirement | None = None,
        goal: StrategicGoal | None = None,
        objective: StrategicObjective | None = None,
        tactical_picture: TacticalPicture | None = None,
        operational_plan: OperationalPlan | None = None,
        timeout_s: float = 600.0,
        command_timeout: float = 10.0,
        on_status: Callable[[AuftragEvent], Any | Awaitable[Any]] | None = None,
    ) -> ReconOutcome:
        """Submit RECON and assess intelligence contributed by its assets.

        MOOSE ``summary.success`` remains authoritative for mission execution.
        The returned tactical assessment separately reports contacts observed by
        groups assigned to this RECON mission.
        """

        if str(auftrag.mission_type).upper() != "RECON":
            raise ValueError("execute_recon requires an Auftrag_RECON command")
        context_values = (goal, objective, tactical_picture)
        if requirement is not None and any(value is not None for value in context_values):
            raise ValueError("pass either requirement or goal/objective/tactical_picture context")
        if requirement is None and any(value is not None for value in context_values):
            if goal is None or objective is None or tactical_picture is None:
                raise ValueError("automatic RECON derivation requires goal, objective and tactical_picture")
            requirement = derive_recon_requirement(
                goal,
                objective,
                tactical_picture,
                plan=operational_plan,
                manual_target_ids=relevant_target_ids,
            )
            relevant_target_ids = ()
        cursor = await self.server.event_cursor()
        await self.refresh_intel_state()
        if self.intel(intel) is None:
            raise ValueError(f"INTEL is not registered: {intel}")
        baseline_contact_ids = tuple(contact.object_id for contact in self.contacts_of_intel(intel))
        ack = await self.add_auftrag(
            auftrag,
            commander=commander,
            legion=legion,
            opsgroup=opsgroup,
            cohort=cohort,
            coalition=coalition,
            allowed_legions=allowed_legions,
            allowed_cohorts=allowed_cohorts,
            selected_payload_uid=selected_payload_uid,
            timeout=command_timeout,
        )
        tracking = ReconTrackingSession(self.mission_id(auftrag))
        tracking_stop = asyncio.Event()
        tracking_task = (
            asyncio.create_task(self.monitor_recon_tracking(tracking, tracking_stop), name=f"recon-track-{tracking.auftrag_id}")
            if self._recon_requires_spatial_tracking(requirement)
            else None
        )
        try:
            outcome = await self.get_auftrag_summary(
                auftrag,
                timeout_s=timeout_s,
                on_status=on_status,
                after_event_id=cursor,
            )
        finally:
            if tracking_task is not None:
                tracking_stop.set()
                await tracking_task
        if tracking_task is not None:
            await self.sample_recon_tracking(tracking)
        await self.snapshot_auftraege()
        await self.snapshot_opsgroups()
        mission = self.auftrag(outcome.auftrag_id)
        assigned_opsgroup_ids = tracking.assigned_opsgroup_ids or (tuple(mission.assigned_group_ids) if mission else ())
        assigned_group_ids: list[str] = []
        if tracking.assigned_group_ids:
            assigned_group_ids.extend(tracking.assigned_group_ids)
        else:
            for opsgroup_id in assigned_opsgroup_ids:
                assigned = self.opsgroup(opsgroup_id)
                group_name = assigned.group_name if assigned and assigned.group_name else opsgroup_id.removeprefix("OPSGROUP:")
                assigned_group_ids.append(f"GROUP:{group_name}")
        spatial_coverage = (
            await self.assess_recon_tracking(requirement, tracking)
            if requirement is not None and tracking_task is not None
            else None
        )
        history = await self.server.query_events("*", after_id=cursor)
        events = history.get("events") if isinstance(history.get("events"), list) else []
        result = build_recon_outcome(
            auftrag_id=outcome.auftrag_id,
            intel_id=intel,
            mission_outcome=outcome,
            events=(event for event in events if isinstance(event, dict)),
            baseline_contact_ids=baseline_contact_ids,
            assigned_opsgroup_ids=assigned_opsgroup_ids,
            assigned_group_ids=assigned_group_ids,
            relevant_target_ids=relevant_target_ids,
            requirement=requirement,
            spatial_coverage=spatial_coverage,
            command_ack=ack,
            event_history_complete=bool(history.get("history_complete")),
        )
        completed_time = result.completed_time if result.completed_time is not None else self._current_mission_time()
        area_id = requirement.area_object_id if requirement is not None else result.auftrag_id
        plan_id = f"DIRECT_RECON:{intel}:{area_id}"
        attempt_id = f"{plan_id}:{completed_time if completed_time is not None else 'unknown'}"
        intel_snapshot = self.intel(intel)
        await self.server.append_audit_record(
            RECON_EXECUTION_AUDIT_TYPE,
            {
                "audit_session_id": self.state.audit_session_id,
                "mission_generation": self.state.mission_generation,
                "plan_id": plan_id,
                "commander_id": commander or "",
                "attempt_id": attempt_id,
                "attempt_number": 1,
                "status": "completed",
                "started_mission_time": result.started_time,
                "completed_mission_time": completed_time,
                "plan": {"coalition": intel_snapshot.coalition if intel_snapshot else None},
                "missions": [{
                    "phase_id": "direct_recon",
                    "intent_id": "direct_recon",
                    "requirement_id": requirement.area_object_id if requirement else "direct_recon",
                    "mission_type": "RECON",
                    "required": True,
                    "status": "succeeded" if result.mission_outcome.success is True else "failed",
                    "auftrag_id": result.auftrag_id,
                    "outcome": result.mission_outcome.to_dict(),
                    "recon_outcome": result.to_dict(),
                    "recon_intel_id": intel,
                    "recon_assigned_group_ids": list(tracking.assigned_group_ids),
                    "recon_tracks": {
                        group_id: [sample.to_dict() for sample in samples]
                        for group_id, samples in tracking.tracks.items()
                    },
                }],
                "events": [],
            },
        )
        return result

    def mission_id(self, mission: AuftragCommand | Auftrag | str) -> str:
        """Return the stable ``AUFTRAG:id`` for an SDK mission reference.

        :param mission: Python AUFTRAG description, mirrored mission object or direct id.
        :raises ValueError: If a Python AUFTRAG object has not been added through this client.
        """

        if isinstance(mission, str):
            return mission
        if isinstance(mission, Auftrag):
            return mission_id_from_snapshot(mission)
        mission_id = self._auftrag_ids_by_object.get(id(mission))
        if not mission_id:
            raise ValueError("No AUFTRAG id is known for this object. Call add_auftrag first or pass an AUFTRAG:id string.")
        return mission_id

    async def cancel_mission(self, mission: AuftragCommand | Auftrag | str, timeout: float = 10.0) -> dict[str, Any]:
        """Cancel an existing MOOSE AUFTRAG mission."""

        return require_ok(
            await self.server.send_command(
                BridgeCommand(action="auftrag.cancel", params={"object_id": self.mission_id(mission)}),
                timeout=timeout,
            )
        )

    async def pause_mission(self, mission: AuftragCommand | Auftrag | str, timeout: float = 10.0) -> dict[str, Any]:
        """Pause an existing MOOSE AUFTRAG mission."""

        return require_ok(
            await self.server.send_command(
                BridgeCommand(action="auftrag.pause", params={"object_id": self.mission_id(mission)}),
                timeout=timeout,
            )
        )

    async def resume_mission(self, mission: AuftragCommand | Auftrag | str, timeout: float = 10.0) -> dict[str, Any]:
        """Resume an existing MOOSE AUFTRAG mission."""

        return require_ok(
            await self.server.send_command(
                BridgeCommand(action="auftrag.resume", params={"object_id": self.mission_id(mission)}),
                timeout=timeout,
            )
        )

    async def assign_mission(
        self,
        mission: AuftragCommand | Auftrag | str,
        *,
        commander: str | None = None,
        legion: str | None = None,
        opsgroup: str | None = None,
        cohort: str | None = None,
        coalition: str | None = None,
        allowed_legions: Iterable[str] | None = None,
        allowed_cohorts: Iterable[str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Assign an existing mission to a COMMANDER, LEGION or OPSGROUP."""

        return require_ok(
            await self.server.send_command(
                BridgeCommand(
                    action="auftrag.assign",
                    params={
                        "object_id": self.mission_id(mission),
                        **self._auftrag_assignment_params(
                            commander=commander,
                            legion=legion,
                            opsgroup=opsgroup,
                            cohort=cohort,
                            coalition=coalition,
                            allowed_legions=allowed_legions,
                            allowed_cohorts=allowed_cohorts,
                        ),
                    },
                ),
                timeout=timeout,
            )
        )

    async def get_auftrag_summary(
        self,
        auftrag: AuftragCommand | str,
        *,
        timeout_s: float = 600.0,
        interval_s: float = 5.0,
        on_status: Callable[[AuftragEvent], Any | Awaitable[Any]] | None = None,
        after_event_id: str | None = None,
    ) -> AuftragOutcome:
        """Wait until an AUFTRAG evaluated event arrives and return its outcome.

        ``auftrag`` can be the same Python AUFTRAG object previously passed to
        :meth:`add_auftrag`, or a direct ``AUFTRAG:id`` string.

        :param auftrag: Python AUFTRAG description or stable ``AUFTRAG:id``.
        :param timeout_s: Maximum monitoring time in seconds.
        :param interval_s: Backward-compatible no-op; event waiting does not poll.
        :param on_status: Optional callback called for intermediate AUFTRAG events.
        :param after_event_id: Optional daemon cursor excluding older events.
        :returns: Stable evaluated AUFTRAG outcome.
        :raises ValueError: If the Python object was not created through this client.
        """

        auftrag_id = self.mission_id(auftrag)
        return await self.wait_for_auftrag_outcome(
            auftrag_id,
            timeout_s=timeout_s,
            interval_s=interval_s,
            on_status=on_status,
            after_event_id=after_event_id,
        )

    async def apply_recommended_auftrag(self, recommendation: Any, timeout: float = 10.0) -> dict[str, Any]:
        """Apply an AUFTRAG recommendation produced by the advisory layer.

        :param recommendation: Recommendation object with ``to_dict``.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        data = recommendation.to_dict()
        mission_type = str(data.get("mission_type") or "").strip()
        if not mission_type:
            raise ValueError("Recommendation does not include mission_type")
        return await self.apply_auftrag(mission_type, build_recommended_auftrag_command_params(recommendation), timeout=timeout)

    async def wait_for_auftrag_outcome(
        self,
        auftrag_id: str,
        timeout_s: float = 600.0,
        interval_s: float = 5.0,
        on_status: Callable[[AuftragEvent], Any | Awaitable[Any]] | None = None,
        after_event_id: str | None = None,
    ) -> AuftragOutcome:
        """Wait until an AUFTRAG evaluated event arrives and return its outcome.

        The method waits for the Lua bridge's ``auftrag.evaluated`` event and
        uses ``summary.success`` as the authoritative result. ``interval_s`` is
        accepted for backward-compatible call sites but is not used.

        :param auftrag_id: Stable AUFTRAG object id from the apply ACK.
        :param timeout_s: Maximum monitoring time in seconds.
        :param interval_s: Backward-compatible no-op; event waiting does not poll.
        :param on_status: Optional callback called for intermediate AUFTRAG events.
        :param after_event_id: Optional daemon cursor excluding older events.
        :returns: Stable AUFTRAG outcome model.
        :raises MooseBridgeAuftragNotFoundError: If the AUFTRAG is never observed.
        :raises MooseBridgeAuftragTimeoutError: If no summary appears before timeout.
        """

        deadline = asyncio.get_running_loop().time() + timeout_s
        seen = False
        last_event_id: str | None = after_event_id
        seen_status_keys: set[tuple[str, str | None, str | None, str | None, str | None]] = set()

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                if seen:
                    raise MooseBridgeAuftragTimeoutError(f"{auftrag_id} was not evaluated before timeout")
                raise MooseBridgeAuftragNotFoundError(f"{auftrag_id} produced no AUFTRAG events before timeout")

            try:
                event = await self.server.wait_for_event("auftrag.*", filters={"auftrag_id": auftrag_id}, timeout=remaining, after_id=last_event_id)
            except TimeoutError as exc:
                if seen:
                    raise MooseBridgeAuftragTimeoutError(f"{auftrag_id} was not evaluated before timeout") from exc
                raise MooseBridgeAuftragNotFoundError(f"{auftrag_id} produced no AUFTRAG events before timeout") from exc

            seen = True
            last_event_id = str(event.get("id") or "") or last_event_id
            self.state.apply_message(event)
            self._on_bridge_message(event)
            if str(event.get("event") or "") == "mission.ended":
                raise DcsMissionEndedError("DCS mission ended while waiting for AUFTRAG outcome")
            auftrag_event = AuftragEvent.from_message(event)
            if auftrag_event.event != "auftrag.evaluated":
                status_key = (
                    auftrag_event.auftrag_id,
                    auftrag_event.fsm_event,
                    auftrag_event.status,
                    auftrag_event.from_state,
                    auftrag_event.to_state,
                )
                if status_key not in seen_status_keys:
                    seen_status_keys.add(status_key)
                    await maybe_call_auftrag_status_callback(on_status, auftrag_event)
                continue

            try:
                outcome = auftrag_outcome_from_event(event)
            except ValueError as exc:
                raise MooseBridgeAuftragNotFoundError(f"{auftrag_id} evaluated event did not contain a usable summary") from exc
            return outcome

    async def message_coalition(self, coalition: str, text: str, duration: int = 10) -> dict[str, Any]:
        """Send a message to a coalition in DCS.

        :param coalition: Coalition name.
        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.message_to_coalition(coalition, text, duration))

    async def message_to_coalition(self, coalition: str, text: str, duration: int = 10) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`message_coalition`.

        :param coalition: Coalition name.
        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.message_coalition(coalition, text, duration)

    async def message_all(self, text: str, duration: int = 10) -> dict[str, Any]:
        """Send a message to all players in DCS.

        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.message_to_all(text, duration))

    async def message_to_all(self, text: str, duration: int = 10) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`message_all`.

        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.message_all(text, duration)

    async def smoke_point(self, x: float, z: float, color: str = "white", y: float = 0.0) -> dict[str, Any]:
        """Create smoke at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param color: Smoke color: red, green, blue, orange, or white.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.smoke_at_point(x, z, validate_smoke_color(color), y))

    async def smoke_at_point(self, x: float, z: float, color: str = "white", y: float = 0.0) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`smoke_point`.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param color: Smoke color: red, green, blue, orange, or white.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.smoke_point(x, z, color, y)

    async def smoke_object(self, object_id: str, color: str = "white") -> dict[str, Any]:
        """Create smoke at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``UNIT:Name``.
        :param color: Smoke color: red, green, blue, orange, or white.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.smoke_object(object_id, validate_smoke_color(color)))

    async def explode_point(
        self,
        x: float,
        z: float,
        power: float,
        y: float | None = None,
        delay: float = 0.0,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Create an explosion at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param power: Explosion intensity in kilograms of TNT.
        :param y: Optional DCS world y coordinate. DCS terrain height is used when omitted.
        :param delay: Delay before the explosion in seconds.
        :param timeout: Command timeout in seconds.
        :returns: ACK message received from DCS.
        :raises ValueError: If power or delay is invalid.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        if power <= 0:
            raise ValueError("Explosion power must be greater than zero")
        if delay < 0:
            raise ValueError("Explosion delay must be zero or greater")
        params: dict[str, Any] = {"x": x, "z": z, "power": power, "delay": delay}
        if y is not None:
            params["y"] = y
        return require_ok(
            await self.server.send_command(
                BridgeCommand(action="explosion.at_point", params=params),
                timeout=timeout,
            )
        )

    async def explode_object(
        self,
        object_id: str,
        power: float,
        delay: float = 0.0,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Create an explosion at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``UNIT:Name``.
        :param power: Explosion intensity in kilograms of TNT.
        :param delay: Delay before the explosion in seconds.
        :param timeout: Command timeout in seconds.
        :returns: ACK message received from DCS.
        :raises ValueError: If power or delay is invalid.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        if power <= 0:
            raise ValueError("Explosion power must be greater than zero")
        if delay < 0:
            raise ValueError("Explosion delay must be zero or greater")
        return require_ok(
            await self.server.send_command(
                BridgeCommand(
                    action="explosion.object",
                    params={"object_id": object_id, "power": power, "delay": delay},
                ),
                timeout=timeout,
            )
        )

    async def mark_point(self, x: float, z: float, text: str, y: float = 0.0) -> dict[str, Any]:
        """Create a map mark at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param text: Mark text.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.mark_at_point(x, z, text, y))

    async def mark_at_point(self, x: float, z: float, text: str, y: float = 0.0) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`mark_point`.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param text: Mark text.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.mark_point(x, z, text, y)

    async def mark_object(self, object_id: str, text: str) -> dict[str, Any]:
        """Create a map mark at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``GROUP:Name``.
        :param text: Mark text.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.mark_object(object_id, text))

    async def mark_map_position(
        self,
        text: str,
        *,
        x: float | None = None,
        z: float | None = None,
        y: float = 0.0,
        latitude: float | None = None,
        longitude: float | None = None,
        altitude: float = 0.0,
        coalition: str | int = "all",
        read_only: bool = False,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Create a compact native marker at a DCS or WGS84 map position.

        Supply either ``x`` and ``z`` or ``latitude`` and ``longitude``.
        WGS84 coordinates are converted inside DCS with ``coord.LLtoLO``.
        """

        marker_text = str(text).strip()
        if not marker_text:
            raise ValueError("marker text must not be empty")
        if len(marker_text) > 180:
            raise ValueError("marker text accepts at most 180 characters")
        local_position = x is not None or z is not None
        geographic_position = latitude is not None or longitude is not None
        if local_position == geographic_position:
            raise ValueError("supply either x/z or latitude/longitude")
        if local_position:
            values = (x, y, z)
            if x is None or z is None or not all(math.isfinite(float(value)) for value in values):
                raise ValueError("x, y and z must be finite numbers")
            point = {"x": float(x), "y": float(y), "z": float(z)}
        else:
            values = (latitude, longitude, altitude)
            if latitude is None or longitude is None or not all(math.isfinite(float(value)) for value in values):
                raise ValueError("latitude, longitude and altitude must be finite numbers")
            if not -90 <= float(latitude) <= 90 or not -180 <= float(longitude) <= 180:
                raise ValueError("latitude/longitude is outside WGS84 bounds")
            point = {
                "latitude": float(latitude),
                "longitude": float(longitude),
                "altitude": float(altitude),
            }
        return require_ok(
            await self.server.send_command(
                BridgeCommand(
                    action="map.marker.create",
                    params={
                        "point": point,
                        "text": marker_text,
                        "coalition": validate_draw_zone_coalition(coalition),
                        "read_only": bool(read_only),
                    },
                ),
                timeout=timeout,
            )
        )

    async def coords(self, object_id: str, format: str = "xyz", timeout: float = 10.0) -> CoordinateResult:
        """Resolve coordinates for a bridge object id.

        :param object_id: Stable bridge object id such as ``ZONE:Town Fight``.
        :param format: Coordinate format: ``xyz``, ``ll``, ``mgrs`` or ``all``.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Typed coordinate result.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(action="object.coords", params={"object_id": object_id, "format": validate_coordinate_format(format)}),
                timeout=timeout,
            )
        )
        return CoordinateResult.from_ack(ack)

    async def convert_points(
        self,
        points: Iterable[tuple[float, float] | tuple[float, float, float]],
        *,
        timeout: float = 10.0,
    ) -> list[GeographicPoint]:
        """Convert DCS-local points to WGS84 in one bridge roundtrip."""

        payload: list[dict[str, float]] = []
        for point in points:
            if len(point) == 2:
                x, z = point
                y = 0.0
            elif len(point) == 3:
                x, y, z = point
            else:
                raise ValueError("Each point must contain (x, z) or (x, y, z)")
            values = (float(x), float(y), float(z))
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Point coordinates must be finite")
            payload.append({"x": values[0], "y": values[1], "z": values[2]})
        if len(payload) > 5000:
            raise ValueError("convert_points accepts at most 5000 points")
        if not payload:
            return []
        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(action="coordinates.convert_points", params={"points": payload}),
                timeout=timeout,
            )
        )
        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        converted = result.get("points") if isinstance(result.get("points"), list) else []
        if len(converted) != len(payload):
            raise ValueError(f"DCS converted {len(converted)} of {len(payload)} points")
        return [GeographicPoint.from_payload(item) for item in converted if isinstance(item, dict)]

    async def survey_scenery(
        self,
        latitude: float,
        longitude: float,
        *,
        radius_m: float = 500.0,
        max_results: int = 250,
        timeout: float = 30.0,
    ) -> ScenerySurvey:
        """Inspect DCS scenery objects in one deliberately bounded sphere."""

        latitude = float(latitude)
        longitude = float(longitude)
        radius_m = float(radius_m)
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("latitude must be finite and in range -90..90")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("longitude must be finite and in range -180..180")
        if not math.isfinite(radius_m) or not 0 < radius_m <= 5000:
            raise ValueError("radius_m must be finite and in range 0..5000")
        if not 1 <= max_results <= 2000:
            raise ValueError("max_results must be in range 1..2000")
        ack = require_ok(await self.server.send_command(
            BridgeCommand(action="scenery.search", params={
                "latitude": latitude,
                "longitude": longitude,
                "radius_m": radius_m,
                "max_results": int(max_results),
            }),
            timeout=timeout,
        ))
        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        center = result.get("center") if isinstance(result.get("center"), dict) else {}
        center_values = {key: _optional_float(center.get(key)) for key in ("x", "y", "z", "latitude", "longitude")}
        if any(value is None for value in center_values.values()):
            raise ValueError("DCS scenery survey is missing its center coordinates")
        objects = result.get("objects") if isinstance(result.get("objects"), list) else []
        return ScenerySurvey(
            center=GeographicSurveyPoint(**center_values),  # type: ignore[arg-type]
            radius_m=float(result.get("radius_m") or radius_m),
            objects=tuple(SceneryObjectSnapshot.from_payload(item) for item in objects if isinstance(item, dict)),
            truncated=result.get("truncated") is True,
        )

    async def resolve_scenery_objects(
        self,
        object_ids: Iterable[str],
        *,
        positions: Mapping[str, tuple[float, float]] | None = None,
        zone_names: Mapping[str, str] | None = None,
        search_radius_m: float = 150.0,
        timeout: float = 30.0,
    ) -> SceneryObjectResolution:
        """Resolve known SCENERY IDs near saved positions or Assign-As zones."""

        search_radius_m = float(search_radius_m)
        if not math.isfinite(search_radius_m) or not 0 < search_radius_m <= 500:
            raise ValueError("search_radius_m must be finite and in range 0..500")
        position_by_id = positions or {}
        zone_by_id = zone_names or {}
        references: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in object_ids:
            object_id = str(value).strip()
            if not object_id or object_id in seen:
                continue
            if not object_id.startswith("SCENERY:"):
                raise ValueError(f"scenery object id must start with SCENERY: {object_id}")
            seen.add(object_id)
            reference: dict[str, Any] = {"object_id": object_id}
            zone_name = str(zone_by_id.get(object_id) or "").strip()
            if zone_name:
                reference["zone_name"] = zone_name
            else:
                position = position_by_id.get(object_id)
                if position is None or len(position) != 2:
                    raise ValueError(f"missing position or Assign-As zone for {object_id}")
                latitude, longitude = (float(position[0]), float(position[1]))
                if not math.isfinite(latitude) or not -90 <= latitude <= 90:
                    raise ValueError(f"invalid latitude for {object_id}")
                if not math.isfinite(longitude) or not -180 <= longitude <= 180:
                    raise ValueError(f"invalid longitude for {object_id}")
                reference.update(latitude=latitude, longitude=longitude)
            references.append(reference)
        if len(references) > 500:
            raise ValueError("resolve_scenery_objects accepts at most 500 object IDs")
        if not references:
            return SceneryObjectResolution(())
        ack = require_ok(await self.server.send_command(
            BridgeCommand(action="scenery.resolve", params={
                "references": references,
                "search_radius_m": search_radius_m,
            }),
            timeout=timeout,
        ))
        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        objects = result.get("objects") if isinstance(result.get("objects"), list) else []
        unresolved = result.get("unresolved") if isinstance(result.get("unresolved"), list) else []
        return SceneryObjectResolution(
            objects=tuple(
                SceneryObjectSnapshot.from_payload(item)
                for item in objects
                if isinstance(item, dict)
            ),
            unresolved_object_ids=tuple(
                str(item.get("object_id") or "")
                for item in unresolved
                if isinstance(item, dict) and item.get("object_id")
            ),
        )

    async def assess_infrastructure_site(
        self,
        site: InfrastructureSite,
        verification: StrategicSiteVerification,
        *,
        radius_m: float | None = None,
        max_results: int = 2000,
        timeout: float = 30.0,
    ) -> InfrastructureStateAssessment:
        """Compare a verified site's immutable object baseline with current DCS scenery."""

        feature = SceneryVerificationFeature.from_geojson_feature(
            site.to_geojson_feature(),
            artifact_key="infrastructure_sites",
        )
        return await self.assess_scenery_verification(
            feature,
            verification,
            radius_m=radius_m,
            max_results=max_results,
            timeout=timeout,
        )

    async def assess_scenery_verification(
        self,
        feature: SceneryVerificationFeature,
        verification: StrategicSiteVerification,
        *,
        radius_m: float | None = None,
        max_results: int = 2000,
        timeout: float = 30.0,
    ) -> InfrastructureStateAssessment:
        """Compare any normalized theater feature with its fixed SCENERY baseline."""

        if feature.object_id != verification.source_id:
            raise ValueError("scenery feature and verification source ids do not match")
        baseline_ids = tuple(item.object_id for item in verification.observed_objects)
        exact_positions = {
            item.object_id: (item.latitude, item.longitude)
            for item in verification.observed_objects
            if item.latitude is not None and item.longitude is not None
        }
        resolution = await self.resolve_scenery_objects(
            baseline_ids,
            positions=exact_positions,
            timeout=timeout,
        )
        current = tuple(
            ObservedDcsObject(
                object_id=item.object_id,
                type_name=item.type_name or "",
                display_name=item.display_name or item.name or "",
                latitude=item.latitude,
                longitude=item.longitude,
                life=item.life,
                exists=item.exists,
            )
            for item in resolution.objects
            if item.queryable
        )
        destroyed_ids = set(self.state.destroyed_object_ids)
        destroyed_ids.update({
            str(report.get("target_object_id"))
            for report in self.state.loss_reports.values()
            if report.get("target_object_id")
        })
        return assess_infrastructure_state(
            verification,
            current,
            destroyed_object_ids=destroyed_ids,
            current_observation_complete=not resolution.unresolved_object_ids,
        )

    async def distance(self, object_id_a: str, object_id_b: str, timeout: float = 10.0) -> DistanceResult:
        """Measure distance between two bridge object ids.

        :param object_id_a: First object id.
        :param object_id_b: Second object id.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Typed distance result.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(action="object.distance", params={"object_id_a": object_id_a, "object_id_b": object_id_b}),
                timeout=timeout,
            )
        )
        return DistanceResult.from_ack(ack)

    async def draw_zone(
        self,
        zone_id: str,
        *,
        coalition: str | int = "all",
        color: str | None = None,
        alpha: float | None = None,
        fill_color: str | None = None,
        fill_alpha: float | None = None,
        line_type: str | int | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Draw a MOOSE ZONE or OPSZONE on the F10 map.

        :param zone_id: ``ZONE:<name>`` or ``OPSZONE:<name>``.
        :param coalition: Visibility coalition: all, neutral, red, blue or -1/0/1/2.
        :param color: Optional line color name.
        :param alpha: Optional line alpha in range 0..1.
        :param fill_color: Optional fill color name.
        :param fill_alpha: Optional fill alpha in range 0..1.
        :param line_type: Optional MOOSE line type name or number 0..6.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        params = clean_params(
            {
                "object_id": zone_id,
                "coalition": validate_draw_zone_coalition(coalition),
                "color": validate_draw_zone_color(color),
                "alpha": alpha,
                "fill_color": validate_draw_zone_color(fill_color),
                "fill_alpha": fill_alpha,
                "line_type": normalize_draw_zone_line_type(line_type),
            }
        )
        return require_ok(await self.server.send_command(BridgeCommand(action="zone.draw", params=params), timeout=timeout))

    async def draw_debug_overlay(
        self,
        overlay_id: str,
        features: Iterable[DebugMarkup],
        *,
        coalition: str | int = "all",
        line_type: str | int = "solid",
        replace: bool = True,
        read_only: bool = True,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Draw a bounded diagnostic overlay with native DCS F10 markups.

        WGS84 points are converted by DCS using ``coord.LLtoLO``. Lines and
        polygon outlines are emitted as individual native line segments so
        complex OSM geometries remain predictable.
        """

        materialized = validate_debug_overlay(overlay_id, features)
        params = {
            "overlay_id": overlay_id,
            "features": [feature.to_payload() for feature in materialized],
            "coalition": validate_draw_zone_coalition(coalition),
            "line_type": normalize_draw_zone_line_type(line_type),
            "replace": bool(replace),
            "read_only": bool(read_only),
        }
        return require_ok(
            await self.server.send_command(BridgeCommand(action="map.overlay.draw", params=params), timeout=timeout)
        )

    async def clear_debug_overlay(self, overlay_id: str | None = None, *, timeout: float = 10.0) -> dict[str, Any]:
        """Remove one named diagnostic overlay, or all overlays when omitted."""

        if overlay_id is not None and (not overlay_id.strip() or len(overlay_id) > 96):
            raise ValueError("overlay_id must contain 1..96 non-whitespace characters")
        return require_ok(
            await self.server.send_command(
                BridgeCommand(action="map.overlay.clear", params=clean_params({"overlay_id": overlay_id})),
                timeout=timeout,
            )
        )

    async def closest_road_points(
        self,
        points: Iterable[DebugMarkupPoint],
        *,
        road_type: str = "roads",
        timeout: float = 30.0,
    ) -> tuple[RoadPointMatch, ...]:
        """Return the nearest native DCS road position for WGS84 points."""

        materialized = tuple(points)
        if not materialized:
            raise ValueError("closest-road lookup requires at least one point")
        if len(materialized) > 500:
            raise ValueError("closest-road lookup accepts at most 500 points")
        if not all(isinstance(point, DebugMarkupPoint) for point in materialized):
            raise TypeError("closest-road lookup points must be DebugMarkupPoint objects")
        normalized_type = road_type.strip().lower()
        if normalized_type not in {"roads", "railroads"}:
            raise ValueError("road_type must be roads or railroads")
        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(
                    action="terrain.closest_road_points",
                    params={
                        "road_type": normalized_type,
                        "points": [point.to_payload() for point in materialized],
                    },
                ),
                timeout=timeout,
            )
        )
        result = ack.get("result")
        samples = result.get("samples") if isinstance(result, Mapping) else None
        if (
            not isinstance(samples, list)
            or len(samples) != len(materialized)
            or not all(isinstance(sample, dict) for sample in samples)
        ):
            raise ValueError("DCS returned an invalid closest-road result")
        return tuple(RoadPointMatch.from_payload(sample) for sample in samples)

    async def road_route(
        self,
        start_object_id: str,
        end_object_id: str,
        *,
        road_type: str = "roads",
        sample_spacing_m: float = 100.0,
        max_points: int = 500,
        timeout: float = 60.0,
    ) -> DcsRoadRoute:
        """Resolve a bounded route through the native DCS road network.

        This is intended to refine a selected strategic corridor, not for
        periodic bulk routing. DCS performs the topology search synchronously.
        """

        if not start_object_id.strip() or not end_object_id.strip():
            raise ValueError("road route object ids must not be empty")
        normalized_type = road_type.strip().lower()
        if normalized_type not in {"roads", "rails"}:
            raise ValueError("road_type must be roads or rails")
        if not math.isfinite(sample_spacing_m) or not 0 <= sample_spacing_m <= 5000:
            raise ValueError("sample_spacing_m must be in range 0..5000")
        if type(max_points) is not int or not 2 <= max_points <= 2000:
            raise ValueError("max_points must be an integer in range 2..2000")
        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(
                    action="terrain.road_route",
                    params={
                        "start_object_id": start_object_id,
                        "end_object_id": end_object_id,
                        "road_type": normalized_type,
                        "sample_spacing_m": float(sample_spacing_m),
                        "max_points": max_points,
                    },
                ),
                timeout=timeout,
            )
        )
        result = ack.get("result")
        if not isinstance(result, dict):
            raise ValueError("DCS returned an invalid road route result")
        return DcsRoadRoute.from_payload(result)

    async def surface_types(
        self,
        points: Iterable[DebugMarkupPoint],
        *,
        timeout: float = 30.0,
    ) -> tuple[DcsSurfacePoint, ...]:
        """Return native DCS coarse terrain classifications for WGS84 points."""

        materialized = tuple(points)
        if not materialized:
            raise ValueError("surface-type lookup requires at least one point")
        if len(materialized) > 500:
            raise ValueError("surface-type lookup accepts at most 500 points")
        if not all(isinstance(point, DebugMarkupPoint) for point in materialized):
            raise TypeError("surface-type lookup points must be DebugMarkupPoint objects")
        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(
                    action="terrain.surface_types",
                    params={"points": [point.to_payload() for point in materialized]},
                ),
                timeout=timeout,
            )
        )
        result = ack.get("result")
        samples = result.get("samples") if isinstance(result, Mapping) else None
        if (
            not isinstance(samples, list)
            or len(samples) != len(materialized)
            or not all(isinstance(sample, dict) for sample in samples)
        ):
            raise ValueError("DCS returned an invalid surface-type result")
        return tuple(DcsSurfacePoint.from_payload(sample) for sample in samples)

    async def set_territory_coalition(
        self,
        territory_id: str,
        coalition: str,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Set declarative TERRITORY ownership in MOOSE.

        Strategic logic remains in Python; this command only updates the
        mission-side TERRITORY mirror and emits a coalition-changed event.
        """

        normalized = coalition.strip().lower()
        if normalized not in {"blue", "red", "neutral"}:
            raise ValueError("coalition must be blue, red, or neutral")
        if not territory_id.startswith("TERRITORY:") or not territory_id.removeprefix("TERRITORY:").strip():
            raise ValueError("territory_id must use TERRITORY:<name>")
        return require_ok(
            await self.server.send_command(
                BridgeCommand(
                    action="territory.set_coalition",
                    params={"territory_id": territory_id, "coalition": normalized},
                ),
                timeout=timeout,
            )
        )

    async def trace_auftrag(self, auftrag_id: str, timeout: float = 10.0) -> dict[str, Any]:
        """Trace AUFTRAG assignment and execution state.

        :param auftrag_id: Stable AUFTRAG object id.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Trace result payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        ack = require_ok(
            await self.server.send_command(BridgeCommand(action="auftrag.trace", params={"object_id": auftrag_id}), timeout=timeout)
        )
        result = ack.get("result")
        return result if isinstance(result, dict) else ack

    async def nearest(
        self,
        kind: str,
        target_id: str,
        *,
        coalition: str | None = None,
        alive: bool | None = None,
        active: bool | None = None,
        contains: str | None = None,
        limit: int = 5,
        refresh: bool = True,
        timeout: float = 10.0,
    ) -> list[NearestResult]:
        """Return nearest snapshot items to a target object.

        The target point is resolved live through DCS. Candidate items come
        from the selected local snapshot kind, optionally refreshed first.

        :param kind: Snapshot kind such as ``units``, ``groups`` or ``airbases``.
        :param target_id: Target object id.
        :param coalition: Optional coalition filter.
        :param alive: Optional alive/dead filter.
        :param active: Optional active/inactive filter.
        :param contains: Optional substring filter.
        :param limit: Maximum result count.
        :param refresh: Request the snapshot kind before ranking.
        :param timeout: Maximum ACK wait time in seconds for DCS commands.
        :returns: Ranked nearest results.
        :raises MooseBridgeCommandError: If DCS rejects a command.
        """

        normalized_kind = kind.removeprefix("snapshot.").lower().strip()
        if normalized_kind not in SNAPSHOT_KINDS:
            raise ValueError(f"Unsupported snapshot kind: {kind!r}. Expected one of {sorted(SNAPSHOT_KINDS)}")

        target = await self.coords(target_id, format="xyz", timeout=timeout)
        if target.x is None or target.z is None:
            raise ValueError(f"Target has no x/z coordinates: {target_id}")
        if refresh:
            await self.snapshot_kind(normalized_kind)

        values = getattr(self.state, normalized_kind)
        items = list(values.values()) if isinstance(values, dict) else []
        ranked: list[NearestResult] = []
        for item in items:
            object_id = str(item.get("object_id") or "")
            if object_id == target_id:
                continue
            if not item_matches(item, coalition=coalition, alive=alive, active=active, contains=contains):
                continue
            point = point_from_item(item)
            if point is None:
                continue
            distance_m = math.hypot(point[0] - target.x, point[1] - target.z)
            ranked.append(NearestResult(object_id=object_id, distance_m=distance_m, distance_nm=distance_m / 1852, item=item))

        ranked.sort(key=lambda value: value.distance_m)
        return ranked[: max(0, limit)]


def _footprint_within_survey(
    latitude: float,
    longitude: float,
    geometry: Mapping[str, Any],
    radius_m: float,
) -> bool:
    footprint = shape(geometry)
    if footprint.is_empty or footprint.geom_type not in {"Polygon", "MultiPolygon"}:
        return False
    min_lon, min_lat, max_lon, max_lat = footprint.bounds
    return all(
        _geographic_distance_m(latitude, longitude, corner_lat, corner_lon) <= radius_m
        for corner_lat, corner_lon in (
            (min_lat, min_lon),
            (min_lat, max_lon),
            (max_lat, min_lon),
            (max_lat, max_lon),
        )
    )


def _site_survey_radius_m(
    latitude: float,
    longitude: float,
    geometry: Mapping[str, Any],
) -> float:
    """Cover a site's footprint while keeping the DCS query explicitly bounded."""

    footprint = shape(geometry)
    if footprint.is_empty or footprint.geom_type not in {"Polygon", "MultiPolygon"}:
        return 750.0
    min_lon, min_lat, max_lon, max_lat = footprint.bounds
    required = max(
        _geographic_distance_m(latitude, longitude, corner_lat, corner_lon)
        for corner_lat, corner_lon in (
            (min_lat, min_lon),
            (min_lat, max_lon),
            (max_lat, min_lon),
            (max_lat, max_lon),
        )
    ) + 50.0
    return min(max(750.0, required), 5_000.0)


def _verification_survey_radius_m(
    feature: SceneryVerificationFeature,
    verification: StrategicSiteVerification,
) -> float:
    required = _site_survey_radius_m(feature.latitude, feature.longitude, feature.geometry)
    baseline_distances = [
        _geographic_distance_m(
            feature.latitude,
            feature.longitude,
            item.latitude,
            item.longitude,
        )
        for item in verification.observed_objects
        if item.latitude is not None and item.longitude is not None
    ]
    if baseline_distances:
        required = max(required, max(baseline_distances) + 50.0)
    return min(required, 5_000.0)


def _verification_within_survey(
    feature: SceneryVerificationFeature,
    verification: StrategicSiteVerification,
    radius_m: float,
) -> bool:
    footprint = shape(feature.geometry)
    footprint_covered = (
        True
        if footprint.is_empty or footprint.geom_type not in {"Polygon", "MultiPolygon"}
        else _footprint_within_survey(
            feature.latitude,
            feature.longitude,
            feature.geometry,
            radius_m,
        )
    )
    baseline_covered = all(
        item.latitude is None
        or item.longitude is None
        or _geographic_distance_m(
            feature.latitude,
            feature.longitude,
            item.latitude,
            item.longitude,
        ) <= radius_m
        for item in verification.observed_objects
    )
    return footprint_covered and baseline_covered


def _geographic_distance_m(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(value)))
