"""Python-owned strategic objectives built from DCS and MOOSE objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Callable, Iterable, Mapping

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


class StrategicGoalAction(str, Enum):
    """Intent a coalition has toward a strategic objective."""

    CAPTURE = "capture"
    DEFEND = "defend"
    DESTROY = "destroy"
    DISABLE = "disable"
    PROTECT = "protect"
    INTERDICT = "interdict"


class StrategicGoalEffect(str, Enum):
    """Concrete effect requested from an operational plan."""

    DENY_RUNWAY = "deny_runway"
    DESTROY_OBJECT = "destroy_object"
    DESTROY_INFRASTRUCTURE = "destroy_infrastructure"
    SUPPRESS_AIR_DEFENSE = "suppress_air_defense"
    DESTROY_SHIP = "destroy_ship"
    DAMAGE_AREA = "damage_area"
    ATTACK_MAP_OBJECT = "attack_map_object"


class StrategicGoalStatus(str, Enum):
    """Lifecycle state of a coalition-owned strategic goal."""

    PLANNED = "planned"
    ACTIVE = "active"
    ACHIEVED = "achieved"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GoalEvaluationMode(str, Enum):
    """Point in time at which matching success conditions complete a goal."""

    IMMEDIATE = "immediate"
    AT_DEADLINE = "at_deadline"
    MANUAL = "manual"


class GoalConditionMatch(str, Enum):
    """How a set of goal conditions is combined."""

    ALL = "all"
    ANY = "any"


class GoalConditionKind(str, Enum):
    """Serializable strategic goal predicates."""

    OWNER_IS = "owner_is"
    OWNER_IS_NOT = "owner_is_not"
    STATUS_IS = "status_is"
    STATUS_IN = "status_in"
    HEALTH_AT_LEAST = "health_at_least"
    HEALTH_AT_MOST = "health_at_most"
    CONTESTED_IS = "contested_is"


@dataclass(slots=True, frozen=True)
class GoalCondition:
    """One typed condition evaluated against a strategic objective."""

    kind: GoalConditionKind
    value: Any

    def __post_init__(self) -> None:
        kind = GoalConditionKind(self.kind)
        value = self.value
        if kind in {GoalConditionKind.OWNER_IS, GoalConditionKind.OWNER_IS_NOT}:
            value = normalize_coalition(value)
            if value not in {"blue", "red"}:
                raise ValueError("owner goal conditions require coalition blue or red")
        elif kind is GoalConditionKind.STATUS_IS:
            value = ObjectiveStatus(value)
        elif kind is GoalConditionKind.STATUS_IN:
            value = tuple(ObjectiveStatus(item) for item in value)
            if not value:
                raise ValueError("status_in requires at least one objective status")
        elif kind in {GoalConditionKind.HEALTH_AT_LEAST, GoalConditionKind.HEALTH_AT_MOST}:
            value = float(value)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("health goal condition values must be between 0 and 1")
        elif kind is GoalConditionKind.CONTESTED_IS:
            if not isinstance(value, bool):
                raise ValueError("contested_is requires a boolean value")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", value)

    @classmethod
    def owner_is(cls, coalition: str) -> "GoalCondition":
        return cls(GoalConditionKind.OWNER_IS, coalition)

    @classmethod
    def owner_is_not(cls, coalition: str) -> "GoalCondition":
        return cls(GoalConditionKind.OWNER_IS_NOT, coalition)

    @classmethod
    def status_is(cls, status: ObjectiveStatus | str) -> "GoalCondition":
        return cls(GoalConditionKind.STATUS_IS, status)

    @classmethod
    def status_in(cls, *statuses: ObjectiveStatus | str) -> "GoalCondition":
        return cls(GoalConditionKind.STATUS_IN, statuses)

    @classmethod
    def health_at_least(cls, health: float) -> "GoalCondition":
        return cls(GoalConditionKind.HEALTH_AT_LEAST, health)

    @classmethod
    def health_at_most(cls, health: float) -> "GoalCondition":
        return cls(GoalConditionKind.HEALTH_AT_MOST, health)

    @classmethod
    def contested_is(cls, contested: bool) -> "GoalCondition":
        return cls(GoalConditionKind.CONTESTED_IS, contested)

    def matches(self, objective: "StrategicObjective") -> bool:
        """Return whether this condition currently matches an objective."""

        if self.kind is GoalConditionKind.OWNER_IS:
            return objective.owner == self.value
        if self.kind is GoalConditionKind.OWNER_IS_NOT:
            return objective.owner is not None and objective.owner != self.value
        if self.kind is GoalConditionKind.STATUS_IS:
            return objective.status is self.value
        if self.kind is GoalConditionKind.STATUS_IN:
            return objective.status in self.value
        if self.kind is GoalConditionKind.HEALTH_AT_LEAST:
            return objective.health is not None and objective.health >= self.value
        if self.kind is GoalConditionKind.HEALTH_AT_MOST:
            return objective.health is not None and objective.health <= self.value
        if self.kind is GoalConditionKind.CONTESTED_IS:
            return objective.contested is self.value
        return False


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

    @property
    def is_destroy_target(self) -> bool:
        """Return whether the operational planner can attack this component."""

        prefix = self.object_id.partition(":")[0].upper()
        if prefix in {"GROUP", "UNIT", "STATIC"}:
            return True
        if prefix not in {"SCENERY", "MAPOBJECT"}:
            return False
        return (
            self.metadata.get("latitude") is not None
            and self.metadata.get("longitude") is not None
        ) or (
            self.metadata.get("x") is not None
            and self.metadata.get("z") is not None
        )


@dataclass(slots=True, frozen=True)
class ComponentHealthEstimate:
    """Cumulative component-health evidence not available in regular snapshots."""

    health: float
    source: str
    mission_time: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.health) or not 0 <= self.health <= 1:
            raise ValueError("component health estimate must be between 0 and 1")
        if not self.source.strip():
            raise ValueError("component health estimate source must not be empty")
        if self.mission_time is not None and (not math.isfinite(self.mission_time) or self.mission_time < 0):
            raise ValueError("component health estimate mission_time must be finite and non-negative")


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
    component_health_estimates: dict[str, ComponentHealthEstimate] = field(default_factory=dict)

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
        unknown_estimates = set(self.component_health_estimates).difference(component_ids)
        if unknown_estimates:
            raise ValueError(f"component health estimates reference unknown components: {sorted(unknown_estimates)}")


@dataclass(slots=True)
class StrategicGoal:
    """A private coalition intent directed at one strategic objective."""

    goal_id: str
    name: str
    coalition: str
    action: StrategicGoalAction
    objective_id: str
    priority: float = 0.0
    status: StrategicGoalStatus = StrategicGoalStatus.PLANNED
    evaluation_mode: GoalEvaluationMode | None = None
    success_conditions: tuple[GoalCondition, ...] = ()
    failure_conditions: tuple[GoalCondition, ...] = ()
    success_match: GoalConditionMatch = GoalConditionMatch.ALL
    failure_match: GoalConditionMatch = GoalConditionMatch.ANY
    created_mission_time: float | None = None
    activated_mission_time: float | None = None
    deadline_mission_time: float | None = None
    completed_mission_time: float | None = None
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    required_damage: float | None = None
    effect: StrategicGoalEffect | None = None

    def __post_init__(self) -> None:
        self.goal_id = self.goal_id.strip()
        self.name = self.name.strip()
        self.objective_id = self.objective_id.strip()
        self.coalition = normalize_coalition(self.coalition) or ""
        self.action = StrategicGoalAction(self.action)
        self.effect = StrategicGoalEffect(self.effect) if self.effect is not None else None
        if self.effect is StrategicGoalEffect.DENY_RUNWAY and self.action is not StrategicGoalAction.DISABLE:
            raise ValueError("deny_runway effect requires a DISABLE goal")
        if self.action is StrategicGoalAction.DESTROY:
            self.required_damage = 1.0 if self.required_damage is None else float(self.required_damage)
            if not math.isfinite(self.required_damage) or not 0 <= self.required_damage <= 1:
                raise ValueError("DESTROY required_damage must be between 0 and 1")
        elif self.required_damage is not None:
            raise ValueError("required_damage is only valid for DESTROY goals")
        self.status = StrategicGoalStatus(self.status)
        if self.effect is StrategicGoalEffect.DENY_RUNWAY:
            if self.evaluation_mode not in {None, GoalEvaluationMode.MANUAL, GoalEvaluationMode.MANUAL.value}:
                raise ValueError("deny_runway effect requires manual evaluation")
            self.evaluation_mode = GoalEvaluationMode.MANUAL
        else:
            self.evaluation_mode = self.evaluation_mode or _default_goal_evaluation_mode(self.action)
        self.evaluation_mode = GoalEvaluationMode(self.evaluation_mode)
        self.success_match = GoalConditionMatch(self.success_match)
        self.failure_match = GoalConditionMatch(self.failure_match)
        self.success_conditions = (
            ()
            if self.effect is StrategicGoalEffect.DENY_RUNWAY
            else tuple(self.success_conditions) or _default_success_conditions(
                self.action,
                self.coalition,
                required_damage=self.required_damage,
            )
        )
        self.failure_conditions = tuple(self.failure_conditions) or _default_failure_conditions(self.action, self.coalition)
        if not self.goal_id:
            raise ValueError("goal_id must not be empty")
        if not self.name:
            raise ValueError("goal name must not be empty")
        if self.coalition not in {"blue", "red"}:
            raise ValueError("strategic goals require coalition blue or red")
        if not self.objective_id:
            raise ValueError("strategic goal requires objective_id")
        if not math.isfinite(self.priority) or self.priority < 0:
            raise ValueError("goal priority must be finite and non-negative")
        for field_name in (
            "created_mission_time",
            "activated_mission_time",
            "deadline_mission_time",
            "completed_mission_time",
        ):
            value = getattr(self, field_name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{field_name} must be finite and non-negative")
        if self.evaluation_mode is GoalEvaluationMode.AT_DEADLINE and self.deadline_mission_time is None:
            raise ValueError(f"{self.action.value} goals require deadline_mission_time")


@dataclass(slots=True, frozen=True)
class StrategicGoalEvent:
    """One normalized strategic goal lifecycle transition."""

    event: str
    goal_id: str
    objective_id: str
    coalition: str
    source: str
    mission_time: float | None = None
    previous_status: StrategicGoalStatus | None = None
    status: StrategicGoalStatus | None = None
    details: dict[str, Any] = field(default_factory=dict, compare=False)


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

    def clear(self) -> None:
        """Discard all mission-scoped objectives and their local event history."""

        self._objectives.clear()
        self._events.clear()

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
            health = _objective_health(
                objective.components,
                state,
                estimates=objective.component_health_estimates,
            )
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

    def record_component_health(
        self,
        objective: StrategicObjective | str,
        component_id: str,
        health: float,
        *,
        source: str,
        mission_time: float | None = None,
    ) -> ComponentHealthEstimate:
        """Retain the lowest cumulative health reported for one component."""

        item = objective if isinstance(objective, StrategicObjective) else self.get(objective)
        if item is None:
            raise KeyError(f"Unknown strategic objective: {objective}")
        if component_id not in {component.object_id for component in item.components}:
            raise KeyError(f"Unknown component for {item.objective_id}: {component_id}")
        estimate = ComponentHealthEstimate(float(health), source.strip(), mission_time)
        previous = item.component_health_estimates.get(component_id)
        if previous is None or estimate.health < previous.health:
            item.component_health_estimates[component_id] = estimate
            return estimate
        return previous

    def clear_component_health(
        self,
        objective: StrategicObjective | str,
        component_id: str | None = None,
    ) -> None:
        """Clear retained evidence after an explicit repair, replacement, or respawn."""

        item = objective if isinstance(objective, StrategicObjective) else self.get(objective)
        if item is None:
            raise KeyError(f"Unknown strategic objective: {objective}")
        if component_id is None:
            item.component_health_estimates.clear()
        else:
            item.component_health_estimates.pop(component_id, None)

    def _record(self, event: ObjectiveEvent) -> None:
        self._events.append(event)
        if len(self._events) > 10_000:
            del self._events[:1_000]


class StrategicGoalRegistry:
    """Coalition-private goals evaluated against a global objective registry."""

    def __init__(self, objectives: StrategicObjectiveRegistry) -> None:
        self.objectives = objectives
        self._goals: dict[str, StrategicGoal] = {}
        self._events: list[StrategicGoalEvent] = []
        self._listeners: list[Callable[[StrategicGoalEvent], None]] = []

    @property
    def events(self) -> tuple[StrategicGoalEvent, ...]:
        return tuple(self._events)

    def add_listener(self, listener: Callable[[StrategicGoalEvent], None]) -> None:
        """Subscribe to local strategic goal lifecycle events."""

        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[StrategicGoalEvent], None]) -> None:
        """Remove a previously registered goal listener."""

        if listener in self._listeners:
            self._listeners.remove(listener)

    def add(self, goal: StrategicGoal, *, replace: bool = False) -> StrategicGoal:
        """Add a goal after validating its referenced objective."""

        objective = self.objectives.get(goal.objective_id)
        if objective is None:
            raise ValueError(f"Unknown strategic objective: {goal.objective_id}")
        if goal.effect is None and goal.action is StrategicGoalAction.DISABLE and objective.kind is ObjectiveKind.AIRBASE:
            goal.effect = StrategicGoalEffect.DENY_RUNWAY
            goal.evaluation_mode = GoalEvaluationMode.MANUAL
            goal.success_conditions = ()
        if goal.goal_id in self._goals and not replace:
            raise ValueError(f"Strategic goal already exists: {goal.goal_id}")
        self._goals[goal.goal_id] = goal
        self._record(
            StrategicGoalEvent(
                event="goal.created" if not replace else "goal.replaced",
                goal_id=goal.goal_id,
                objective_id=goal.objective_id,
                coalition=goal.coalition,
                source="python",
                mission_time=goal.created_mission_time,
                status=goal.status,
            )
        )
        return goal

    def activate(
        self,
        goal: StrategicGoal | str,
        *,
        mission_time: float | None = None,
        source: str = "python",
    ) -> StrategicGoal:
        """Activate a planned goal."""

        item = self._require(goal)
        if item.status is not StrategicGoalStatus.PLANNED:
            raise ValueError(f"Only planned goals can be activated: {item.goal_id}")
        previous = item.status
        item.status = StrategicGoalStatus.ACTIVE
        item.activated_mission_time = mission_time
        self._record(
            StrategicGoalEvent(
                event="goal.activated",
                goal_id=item.goal_id,
                objective_id=item.objective_id,
                coalition=item.coalition,
                source=source,
                mission_time=mission_time,
                previous_status=previous,
                status=item.status,
            )
        )
        return item

    def cancel(
        self,
        goal: StrategicGoal | str,
        *,
        mission_time: float | None = None,
        source: str = "python",
        reason: str | None = None,
    ) -> StrategicGoal:
        """Cancel a planned or active goal."""

        item = self._require(goal)
        if item.status not in {StrategicGoalStatus.PLANNED, StrategicGoalStatus.ACTIVE}:
            raise ValueError(f"Completed goals cannot be cancelled: {item.goal_id}")
        self._transition(item, StrategicGoalStatus.CANCELLED, source, mission_time, reason=reason)
        return item

    def remove(self, goal: StrategicGoal | str) -> StrategicGoal:
        goal_id = goal.goal_id if isinstance(goal, StrategicGoal) else goal
        try:
            return self._goals.pop(goal_id)
        except KeyError as exc:
            raise KeyError(f"Unknown strategic goal: {goal_id}") from exc

    def get(self, goal_id: str) -> StrategicGoal | None:
        return self._goals.get(goal_id)

    def all(self) -> tuple[StrategicGoal, ...]:
        return tuple(self._goals[key] for key in sorted(self._goals))

    def clear(self) -> None:
        """Discard all mission-scoped goals and their local event history."""

        self._goals.clear()
        self._events.clear()

    def filter(
        self,
        *,
        coalition: str | None = None,
        action: StrategicGoalAction | str | None = None,
        status: StrategicGoalStatus | str | None = None,
        objective_id: str | None = None,
        minimum_priority: float | None = None,
    ) -> tuple[StrategicGoal, ...]:
        normalized_coalition = normalize_coalition(coalition) if coalition is not None else None
        normalized_action = StrategicGoalAction(action) if action is not None else None
        normalized_status = StrategicGoalStatus(status) if status is not None else None
        return tuple(
            goal
            for goal in self.all()
            if (normalized_coalition is None or goal.coalition == normalized_coalition)
            and (normalized_action is None or goal.action is normalized_action)
            and (normalized_status is None or goal.status is normalized_status)
            and (objective_id is None or goal.objective_id == objective_id)
            and (minimum_priority is None or goal.priority >= minimum_priority)
        )

    def sync(self, *, mission_time: float | None = None, source: str = "objective.sync") -> tuple[StrategicGoalEvent, ...]:
        """Evaluate active goals from current objective state."""

        emitted: list[StrategicGoalEvent] = []
        for goal in self.all():
            if goal.status is not StrategicGoalStatus.ACTIVE:
                continue
            objective = self.objectives.get(goal.objective_id)
            if objective is None:
                emitted.append(
                    self._transition(
                        goal,
                        StrategicGoalStatus.FAILED,
                        source,
                        mission_time,
                        reason="objective_removed",
                    )
                )
                continue

            if _conditions_match(goal.failure_conditions, goal.failure_match, objective):
                emitted.append(
                    self._transition(
                        goal,
                        StrategicGoalStatus.FAILED,
                        source,
                        mission_time,
                        reason="failure_conditions_met",
                    )
                )
                continue

            success = _conditions_match(goal.success_conditions, goal.success_match, objective)
            deadline_reached = (
                goal.deadline_mission_time is not None
                and mission_time is not None
                and mission_time >= goal.deadline_mission_time
            )
            if goal.evaluation_mode is GoalEvaluationMode.IMMEDIATE and success:
                emitted.append(self._transition(goal, StrategicGoalStatus.ACHIEVED, source, mission_time))
            elif goal.evaluation_mode is GoalEvaluationMode.AT_DEADLINE and deadline_reached:
                status = StrategicGoalStatus.ACHIEVED if success else StrategicGoalStatus.FAILED
                emitted.append(
                    self._transition(
                        goal,
                        status,
                        source,
                        mission_time,
                        reason=None if success else "deadline_conditions_not_met",
                    )
                )
            elif goal.evaluation_mode is not GoalEvaluationMode.AT_DEADLINE and deadline_reached:
                emitted.append(
                    self._transition(
                        goal,
                        StrategicGoalStatus.FAILED,
                        source,
                        mission_time,
                        reason="deadline_expired",
                    )
                )
        return tuple(emitted)

    def complete_manual(
        self,
        goal: StrategicGoal | str,
        *,
        achieved: bool,
        mission_time: float | None = None,
        source: str = "python",
        reason: str | None = None,
    ) -> StrategicGoal:
        """Complete one manual goal explicitly."""

        item = self._require(goal)
        if item.status is not StrategicGoalStatus.ACTIVE:
            raise ValueError(f"Only active goals can be completed: {item.goal_id}")
        status = StrategicGoalStatus.ACHIEVED if achieved else StrategicGoalStatus.FAILED
        self._transition(item, status, source, mission_time, reason=reason)
        return item

    def _require(self, goal: StrategicGoal | str) -> StrategicGoal:
        goal_id = goal.goal_id if isinstance(goal, StrategicGoal) else goal
        item = self.get(goal_id)
        if item is None:
            raise KeyError(f"Unknown strategic goal: {goal_id}")
        return item

    def _transition(
        self,
        goal: StrategicGoal,
        status: StrategicGoalStatus,
        source: str,
        mission_time: float | None,
        *,
        reason: str | None = None,
    ) -> StrategicGoalEvent:
        previous = goal.status
        goal.status = status
        goal.completed_mission_time = mission_time
        goal.failure_reason = reason if status is StrategicGoalStatus.FAILED else None
        event = StrategicGoalEvent(
            event=f"goal.{status.value}",
            goal_id=goal.goal_id,
            objective_id=goal.objective_id,
            coalition=goal.coalition,
            source=source,
            mission_time=mission_time,
            previous_status=previous,
            status=status,
            details={"reason": reason} if reason else {},
        )
        self._record(event)
        return event

    def _record(self, event: StrategicGoalEvent) -> None:
        self._events.append(event)
        if len(self._events) > 10_000:
            del self._events[:1_000]
        for listener in tuple(self._listeners):
            listener(event)


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


def _default_goal_evaluation_mode(action: StrategicGoalAction) -> GoalEvaluationMode:
    if action in {StrategicGoalAction.DEFEND, StrategicGoalAction.PROTECT}:
        return GoalEvaluationMode.AT_DEADLINE
    return GoalEvaluationMode.IMMEDIATE


def _default_success_conditions(
    action: StrategicGoalAction,
    coalition: str,
    *,
    required_damage: float | None = None,
) -> tuple[GoalCondition, ...]:
    if action is StrategicGoalAction.CAPTURE:
        return (GoalCondition.owner_is(coalition), GoalCondition.contested_is(False))
    if action is StrategicGoalAction.DEFEND:
        return (GoalCondition.owner_is(coalition),)
    if action is StrategicGoalAction.DESTROY:
        damage = 1.0 if required_damage is None else required_damage
        return (GoalCondition.health_at_most(round(1.0 - damage, 12)),)
    if action is StrategicGoalAction.DISABLE:
        return (GoalCondition.status_in(ObjectiveStatus.DISABLED, ObjectiveStatus.DESTROYED),)
    if action is StrategicGoalAction.PROTECT:
        return (GoalCondition.health_at_least(0.85),)
    if action is StrategicGoalAction.INTERDICT:
        return (GoalCondition.health_at_most(0.85),)
    return ()


def _default_failure_conditions(action: StrategicGoalAction, coalition: str) -> tuple[GoalCondition, ...]:
    if action is StrategicGoalAction.DEFEND:
        return (GoalCondition.owner_is_not(coalition),)
    if action is StrategicGoalAction.PROTECT:
        return (GoalCondition.status_is(ObjectiveStatus.DESTROYED),)
    return ()


def _conditions_match(
    conditions: tuple[GoalCondition, ...],
    match: GoalConditionMatch,
    objective: StrategicObjective,
) -> bool:
    if not conditions:
        return False
    matches = (condition.matches(objective) for condition in conditions)
    return all(matches) if match is GoalConditionMatch.ALL else any(matches)


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


def _objective_health(
    components: Iterable[ObjectiveComponent],
    state: MooseBridgeState,
    *,
    estimates: Mapping[str, ComponentHealthEstimate] | None = None,
) -> float | None:
    weighted_health = 0.0
    total_weight = 0.0
    for component in components:
        if not component.contributes_to_health or component.weight <= 0:
            continue
        health = component_health(component.object_id, state)
        estimate = (estimates or {}).get(component.object_id)
        if estimate is not None:
            health = estimate.health if health is None else min(health, estimate.health)
        if health is None:
            continue
        weighted_health += health * component.weight
        total_weight += component.weight
    if total_weight <= 0:
        return None
    return max(0.0, min(1.0, weighted_health / total_weight))


def component_health(object_id: str, state: MooseBridgeState) -> float | None:
    """Return normalized current health for one objective component."""

    if object_id in state.destroyed_object_ids:
        return 0.0
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
    if prefix == "GROUP":
        unit_count = _number(payload.get("unit_count"))
        alive_unit_count = _number(payload.get("alive_unit_count"))
        if unit_count is not None and alive_unit_count is not None and unit_count > 0:
            return max(0.0, min(1.0, alive_unit_count / unit_count))
    life = _number(payload.get("life"))
    life_initial = _number(payload.get("life_initial")) or _number(payload.get("life0"))
    if life is not None and life_initial is not None and life_initial > 0:
        return max(0.0, min(1.0, life / life_initial))
    if payload.get("alive") is not None:
        return 1.0 if bool(payload.get("alive")) else 0.0
    return None


def effective_component_health(
    objective: StrategicObjective,
    object_id: str,
    state: MooseBridgeState,
) -> float | None:
    """Combine current snapshot health with retained cumulative evidence."""

    health = component_health(object_id, state)
    estimate = objective.component_health_estimates.get(object_id)
    if estimate is None:
        return health
    return estimate.health if health is None else min(health, estimate.health)


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
