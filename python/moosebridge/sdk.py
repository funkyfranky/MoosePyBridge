"""Small local SDK wrapper for embedding MOOSE Bridge commands in Python tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
import math
from typing import Any

from .ammunition import DcsWeaponFlag, TaskWeaponSelection, UnitAmmunition, WeaponRole, select_task_weapon
from .auftraege import AuftragCommand, AuftragEvent
from .clock import DcsTime
from .dcs_events import DestroyedObjectEvent
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
from .legions import Cohort, Commander, Legion
from .models import Auftrag, Intel, IntelCluster, IntelContact, OpsGroup, OpsZone, Territory
from .outcomes import AuftragOutcome
from .recon import ReconOutcome, build_recon_outcome
from .operational import OperationalPlan, OperationalPlanAssessment, OperationalPlanRegistry
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
from .server import MooseBridgeServer
from .sensor_ranges import (
    DEFAULT_SENSOR_RANGE_REGISTRY,
    SensorDetectionType,
    SensorRangeProfile,
    SensorRangeRegistry,
    SensorTargetDomain,
)
from .state import MooseBridgeState
from .strategic import (
    ObjectiveEvent,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalEvent,
    StrategicGoalRegistry,
    StrategicObjective,
    StrategicObjectiveRegistry,
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
    """

    def __init__(
        self,
        server: MooseBridgeServer,
        *,
        weapon_ranges: WeaponRangeRegistry | None = None,
        sensor_ranges: SensorRangeRegistry | None = None,
    ) -> None:
        self.server = server
        self.weapon_range_registry = weapon_ranges or DEFAULT_WEAPON_RANGE_REGISTRY
        self.sensor_range_registry = sensor_ranges or DEFAULT_SENSOR_RANGE_REGISTRY
        self.objectives = StrategicObjectiveRegistry()
        self.goals = StrategicGoalRegistry(self.objectives)
        self.plans = OperationalPlanRegistry(self.goals)
        self.plan_executor = OperationalPlanExecutor(self)
        self._auftrag_ids_by_object: dict[int, str] = {}
        add_listener = getattr(server, "add_message_listener", None)
        if callable(add_listener):
            add_listener(self._on_bridge_message)

    @property
    def state(self) -> MooseBridgeState:
        """Return the current typed and raw bridge state.

        :returns: Local state mirror maintained by the server.
        """

        return self.server.state

    def opszone(self, object_id: str) -> OpsZone | None:
        """Return a typed OPSZONE by object id.

        :param object_id: Stable bridge object id such as ``OPSZONE:Town Fight``.
        :returns: Typed OPSZONE or ``None``.
        """

        return self.state.opszone(object_id)

    def territory(self, object_id: str) -> Territory | None:
        """Return a typed TERRITORY by object id."""

        return self.state.territory(object_id)

    def add_strategic_objective(
        self,
        objective: StrategicObjective,
        *,
        replace: bool = False,
        sync: bool = True,
    ) -> StrategicObjective:
        """Add a Python-owned strategic objective during the mission."""

        added = self.objectives.add(objective, replace=replace)
        if sync:
            self.sync_strategic_objectives(source="current_state")
        return added

    def remove_strategic_objective(self, objective: StrategicObjective | str) -> StrategicObjective:
        """Remove a strategic objective during the mission."""

        removed = self.objectives.remove(objective)
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

    def propose_capture_plan(
        self,
        goal: StrategicGoal | str,
        picture: TacticalPicture,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        planner: RuleBasedOperationalPlanner | None = None,
    ) -> OperationalPlan:
        """Create an unregistered rule-based CAPTURE draft from tactical state."""

        item = goal if isinstance(goal, StrategicGoal) else self.strategic_goal(goal)
        if item is None:
            raise KeyError(f"Unknown strategic goal: {goal}")
        objective = self.strategic_objective(item.objective_id)
        if objective is None:
            raise KeyError(f"Unknown strategic objective: {item.objective_id}")
        return (planner or RuleBasedOperationalPlanner()).propose_capture(
            item,
            objective,
            picture,
            plan_id=plan_id,
            name=name,
        )

    def validate_operational_plan(self, plan: OperationalPlan | str) -> OperationalPlanAssessment:
        """Validate a plan against currently mirrored LEGION and COHORT stock."""

        return self.plans.validate(
            plan,
            legions=self.state.legion_objects.values(),
            cohorts=self.state.cohort_objects.values(),
            mission_time=self._current_mission_time(),
        )

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
        """Wait for one UNIT or STATIC destruction reported by DCS."""

        if not object_id.startswith(("UNIT:", "STATIC:")):
            raise ValueError("object_id must start with UNIT: or STATIC:")
        message = await self.server.wait_for_event(
            "object.destroyed",
            filters={"object_id": object_id},
            timeout=timeout,
            after_id=after_id,
        )
        return DestroyedObjectEvent.from_message(message)

    def _on_bridge_message(self, message: dict[str, Any]) -> None:
        """Update strategic objectives after relevant state messages arrive."""

        message_type = str(message.get("type") or "")
        kind = str(message.get("kind") or "")
        event_name = str(message.get("event") or "")
        if message_type == "heartbeat":
            self.goals.sync(mission_time=self._current_mission_time(), source="heartbeat")
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
            self.objectives.sync(self.state, source=source)
            self.goals.sync(mission_time=self._current_mission_time(), source=source)

    def _current_mission_time(self) -> float | None:
        return self.state.clock.mission_time if self.state.clock else None

    def territories(self, coalition: str | None = None) -> list[Territory]:
        """Return known territories, optionally limited to one coalition."""

        territories = list(self.state.territory_objects.values())
        if coalition is None:
            return territories
        return [territory for territory in territories if _same_coalition(territory.coalition, coalition)]

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
        await self.refresh_intel_state()
        if self.intel(intel) is None:
            raise ValueError(f"INTEL is not registered: {intel}")
        baseline_contact_ids = tuple(contact.object_id for contact in self.contacts_of_intel(intel))
        cursor = await self.server.event_cursor()
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
        outcome = await self.get_auftrag_summary(auftrag, timeout_s=timeout_s, on_status=on_status)
        await self.snapshot_auftraege()
        await self.snapshot_opsgroups()
        mission = self.auftrag(outcome.auftrag_id)
        assigned_opsgroup_ids = tuple(mission.assigned_group_ids) if mission else ()
        assigned_group_ids: list[str] = []
        for opsgroup_id in assigned_opsgroup_ids:
            assigned = self.opsgroup(opsgroup_id)
            group_name = assigned.group_name if assigned and assigned.group_name else opsgroup_id.removeprefix("OPSGROUP:")
            assigned_group_ids.append(f"GROUP:{group_name}")
        history = await self.server.query_events("*", after_id=cursor)
        events = history.get("events") if isinstance(history.get("events"), list) else []
        return build_recon_outcome(
            auftrag_id=outcome.auftrag_id,
            intel_id=intel,
            mission_outcome=outcome,
            events=(event for event in events if isinstance(event, dict)),
            baseline_contact_ids=baseline_contact_ids,
            assigned_opsgroup_ids=assigned_opsgroup_ids,
            assigned_group_ids=assigned_group_ids,
            relevant_target_ids=relevant_target_ids,
            command_ack=ack,
            event_history_complete=bool(history.get("history_complete")),
        )

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
    ) -> AuftragOutcome:
        """Wait until an AUFTRAG evaluated event arrives and return its outcome.

        ``auftrag`` can be the same Python AUFTRAG object previously passed to
        :meth:`add_auftrag`, or a direct ``AUFTRAG:id`` string.

        :param auftrag: Python AUFTRAG description or stable ``AUFTRAG:id``.
        :param timeout_s: Maximum monitoring time in seconds.
        :param interval_s: Backward-compatible no-op; event waiting does not poll.
        :param on_status: Optional callback called for intermediate AUFTRAG events.
        :returns: Stable evaluated AUFTRAG outcome.
        :raises ValueError: If the Python object was not created through this client.
        """

        auftrag_id = self.mission_id(auftrag)
        return await self.wait_for_auftrag_outcome(auftrag_id, timeout_s=timeout_s, interval_s=interval_s, on_status=on_status)

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
    ) -> AuftragOutcome:
        """Wait until an AUFTRAG evaluated event arrives and return its outcome.

        The method waits for the Lua bridge's ``auftrag.evaluated`` event and
        uses ``summary.success`` as the authoritative result. ``interval_s`` is
        accepted for backward-compatible call sites but is not used.

        :param auftrag_id: Stable AUFTRAG object id from the apply ACK.
        :param timeout_s: Maximum monitoring time in seconds.
        :param interval_s: Backward-compatible no-op; event waiting does not poll.
        :param on_status: Optional callback called for intermediate AUFTRAG events.
        :returns: Stable AUFTRAG outcome model.
        :raises MooseBridgeAuftragNotFoundError: If the AUFTRAG is never observed.
        :raises MooseBridgeAuftragTimeoutError: If no summary appears before timeout.
        """

        deadline = asyncio.get_running_loop().time() + timeout_s
        seen = False
        last_event_id: str | None = None
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
