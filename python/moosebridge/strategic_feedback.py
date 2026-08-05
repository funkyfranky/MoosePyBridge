"""Event-driven strategic feedback for goals and operational plans."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .legions import Cohort, Legion
from .operational import (
    OperationalPlan,
    OperationalPlanAssessment,
    OperationalPlanRegistry,
    OperationalPlanStatus,
)
from .strategic import (
    StrategicGoalAction,
    StrategicGoalEvent,
    StrategicGoalRegistry,
    StrategicGoalStatus,
    StrategicObjectiveRegistry,
)


class StrategicFeedbackAction(str, Enum):
    """Deterministic response to one strategic feedback event."""

    KEEP = "keep"
    WAIT = "wait"
    REPLAN = "replan"
    ABORT = "abort"


@dataclass(slots=True, frozen=True)
class StrategicFeedbackDecision:
    """Policy decision for one operational plan.

    ``automatic`` is deliberately true only for terminal goals and unsafe
    friendly-target situations. Replanning always remains an explicit action.
    """

    action: StrategicFeedbackAction
    reason: str
    plan_id: str | None = None
    goal_id: str | None = None
    automatic: bool = False


@dataclass(slots=True, frozen=True)
class StrategicFeedbackEvent:
    """One actionable strategic state change observed by Python."""

    event: str
    source: str
    mission_time: float | None = None
    coalition: str | None = None
    goal_id: str | None = None
    plan_id: str | None = None
    reference_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict, compare=False)

    def __str__(self) -> str:
        reference = self.plan_id or self.goal_id or self.reference_id or "STRATEGY"
        parts = [reference, self.event]
        if "feasible" in self.details:
            parts.append(f"feasible={self.details['feasible']}")
        reason = self.details.get("reason")
        if reason:
            parts.append(str(reason))
        return " ".join(parts)


@dataclass(slots=True, frozen=True)
class _PlanFeedbackState:
    feasible: bool
    allocations: tuple[tuple[str, str, int], ...]
    issues: tuple[tuple[str, str, str | None], ...]


class StrategicFeedbackMonitor:
    """Compare event-driven strategic state without creating missions."""

    _TERMINAL_PLAN_STATUSES = {
        OperationalPlanStatus.COMPLETED,
        OperationalPlanStatus.FAILED,
        OperationalPlanStatus.CANCELLED,
    }

    def __init__(
        self,
        goals: StrategicGoalRegistry,
        plans: OperationalPlanRegistry,
        *,
        persistent_shortfall_s: float = 300.0,
    ) -> None:
        if persistent_shortfall_s <= 0:
            raise ValueError("persistent_shortfall_s must be greater than zero")
        self.goals = goals
        self.plans = plans
        self.persistent_shortfall_s = float(persistent_shortfall_s)
        self._events: list[StrategicFeedbackEvent] = []
        self._listeners: list[Callable[[StrategicFeedbackEvent], None]] = []
        self._plan_states: dict[str, _PlanFeedbackState] = {}
        self._shortfall_since: dict[str, float] = {}
        self._persistent_shortfalls_reported: set[str] = set()
        goals.add_listener(self._on_goal_event)

    @property
    def events(self) -> tuple[StrategicFeedbackEvent, ...]:
        return tuple(self._events)

    def add_listener(self, listener: Callable[[StrategicFeedbackEvent], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[StrategicFeedbackEvent], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def clear(self) -> None:
        self._events.clear()
        self._plan_states.clear()
        self._shortfall_since.clear()
        self._persistent_shortfalls_reported.clear()

    def filter(
        self,
        *,
        event: str | None = None,
        coalition: str | None = None,
        goal_id: str | None = None,
        plan_id: str | None = None,
    ) -> tuple[StrategicFeedbackEvent, ...]:
        return tuple(
            item
            for item in self._events
            if (event is None or item.event == event)
            and (coalition is None or item.coalition == coalition)
            and (goal_id is None or item.goal_id == goal_id)
            and (plan_id is None or item.plan_id == plan_id)
        )

    def reassess_plans(
        self,
        *,
        legions: Iterable[Legion],
        cohorts: Iterable[Cohort],
        mission_time: float | None,
        source: str,
    ) -> tuple[StrategicFeedbackEvent, ...]:
        """Revalidate non-terminal plans and emit only meaningful changes."""

        legion_items = tuple(legions)
        cohort_items = tuple(cohorts)
        emitted: list[StrategicFeedbackEvent] = []
        active_ids: set[str] = set()
        for plan in self.plans.all():
            if plan.status in self._TERMINAL_PLAN_STATUSES:
                continue
            active_ids.add(plan.plan_id)
            assessment = self.plans.validate(
                plan,
                legions=legion_items,
                cohorts=cohort_items,
                mission_time=mission_time,
                update_plan=False,
            )
            current = _assessment_state(assessment)
            previous = self._plan_states.get(plan.plan_id)
            self._plan_states[plan.plan_id] = current
            if current.feasible:
                self._shortfall_since.pop(plan.plan_id, None)
                self._persistent_shortfalls_reported.discard(plan.plan_id)
            elif mission_time is not None:
                since = self._shortfall_since.setdefault(plan.plan_id, mission_time)
                if (
                    plan.plan_id not in self._persistent_shortfalls_reported
                    and mission_time - since >= self.persistent_shortfall_s
                ):
                    emitted.append(
                        self._plan_event(
                            "feedback.asset_shortfall_persisted",
                            plan,
                            source,
                            mission_time,
                            current,
                            reason=f"required asset shortfall persisted for {mission_time - since:.0f}s",
                        )
                    )
                    self._persistent_shortfalls_reported.add(plan.plan_id)
            if previous is None:
                emitted.append(self._plan_event("feedback.plan_assessed", plan, source, mission_time, current))
                continue
            if previous.feasible != current.feasible:
                event_name = (
                    "feedback.plan_feasibility_restored"
                    if current.feasible
                    else "feedback.replanning_required"
                )
                emitted.append(
                    self._plan_event(
                        event_name,
                        plan,
                        source,
                        mission_time,
                        current,
                        reason=None if current.feasible else "required asset shortfall or invalid plan constraint",
                    )
                )
            if previous.allocations != current.allocations:
                emitted.append(
                    self._plan_event("feedback.plan_allocation_changed", plan, source, mission_time, current)
                )
            elif previous.issues != current.issues and previous.feasible == current.feasible:
                emitted.append(self._plan_event("feedback.plan_issues_changed", plan, source, mission_time, current))
        for stale_plan_id in set(self._plan_states).difference(active_ids):
            del self._plan_states[stale_plan_id]
            self._shortfall_since.pop(stale_plan_id, None)
            self._persistent_shortfalls_reported.discard(stale_plan_id)
        for event in emitted:
            self._record(event)
        return tuple(emitted)

    def record_context_change(
        self,
        event: str,
        *,
        source: str,
        mission_time: float | None,
        coalition: str | None = None,
        goal_id: str | None = None,
        plan_id: str | None = None,
        reference_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> StrategicFeedbackEvent:
        item = StrategicFeedbackEvent(
            event=event,
            source=source,
            mission_time=mission_time,
            coalition=coalition,
            goal_id=goal_id,
            plan_id=plan_id,
            reference_id=reference_id,
            details=dict(details or {}),
        )
        self._record(item)
        return item

    def _on_goal_event(self, event: StrategicGoalEvent) -> None:
        if event.previous_status == event.status:
            return
        self._record(
            StrategicFeedbackEvent(
                event="feedback.goal_status_changed",
                source=event.source,
                mission_time=event.mission_time,
                coalition=event.coalition,
                goal_id=event.goal_id,
                reference_id=event.objective_id,
                details={
                    "previous_status": event.previous_status.value if event.previous_status else None,
                    "status": event.status.value if event.status else None,
                    **event.details,
                },
            )
        )

    @staticmethod
    def _plan_event(
        event: str,
        plan: OperationalPlan,
        source: str,
        mission_time: float | None,
        state: _PlanFeedbackState,
        *,
        reason: str | None = None,
    ) -> StrategicFeedbackEvent:
        return StrategicFeedbackEvent(
            event=event,
            source=source,
            mission_time=mission_time,
            coalition=plan.coalition,
            goal_id=plan.goal_id,
            plan_id=plan.plan_id,
            details={
                "feasible": state.feasible,
                "allocations": [
                    {"requirement_id": requirement_id, "cohort_id": cohort_id, "count": count}
                    for requirement_id, cohort_id, count in state.allocations
                ],
                "issues": [
                    {"severity": severity, "code": code, "reference_id": reference_id}
                    for severity, code, reference_id in state.issues
                ],
                **({"reason": reason} if reason else {}),
            },
        )

    def _record(self, event: StrategicFeedbackEvent) -> None:
        self._events.append(event)
        if len(self._events) > 10_000:
            del self._events[:1_000]
        for listener in tuple(self._listeners):
            listener(event)


class StrategicFeedbackPolicy:
    """Translate feedback into conservative operational actions."""

    _TERMINAL_GOAL_STATUSES = {
        StrategicGoalStatus.ACHIEVED.value,
        StrategicGoalStatus.FAILED.value,
        StrategicGoalStatus.CANCELLED.value,
    }
    _FRIENDLY_TARGET_ACTIONS = {
        StrategicGoalAction.DESTROY,
        StrategicGoalAction.DISABLE,
        StrategicGoalAction.INTERDICT,
    }

    def __init__(
        self,
        objectives: StrategicObjectiveRegistry,
        goals: StrategicGoalRegistry,
        plans: OperationalPlanRegistry,
    ) -> None:
        self.objectives = objectives
        self.goals = goals
        self.plans = plans

    def decide(
        self,
        event: StrategicFeedbackEvent,
        *,
        executing_plan_ids: Iterable[str] = (),
    ) -> tuple[StrategicFeedbackDecision, ...]:
        """Return deterministic decisions without mutating plans or DCS."""

        executing = set(executing_plan_ids)
        candidates = self._candidate_plans(event)
        decisions: list[StrategicFeedbackDecision] = []
        for plan in candidates:
            goal = self.goals.get(plan.goal_id)
            if goal is None:
                continue
            status = str(event.details.get("status") or "").lower()
            if event.event == "feedback.goal_status_changed" and status in self._TERMINAL_GOAL_STATUSES:
                decisions.append(
                    StrategicFeedbackDecision(
                        StrategicFeedbackAction.ABORT,
                        f"strategic goal {status}; remaining missions are no longer required",
                        plan.plan_id,
                        goal.goal_id,
                        automatic=True,
                    )
                )
                continue
            if event.event == "feedback.objective_changed":
                objective = self.objectives.get(goal.objective_id)
                if (
                    objective is not None
                    and objective.owner == plan.coalition
                    and goal.action in self._FRIENDLY_TARGET_ACTIONS
                ):
                    decisions.append(
                        StrategicFeedbackDecision(
                            StrategicFeedbackAction.ABORT,
                            "target objective is now friendly; continuing would be unsafe",
                            plan.plan_id,
                            goal.goal_id,
                            automatic=True,
                        )
                    )
                    continue
            if event.event == "feedback.replanning_required":
                action = StrategicFeedbackAction.WAIT if plan.plan_id in executing else StrategicFeedbackAction.REPLAN
                reason = (
                    "active MOOSE missions continue; the shortfall applies to later recruitment"
                    if action is StrategicFeedbackAction.WAIT
                    else "plan is infeasible before execution and requires revalidation"
                )
                decisions.append(StrategicFeedbackDecision(action, reason, plan.plan_id, goal.goal_id))
                continue
            if event.event == "feedback.asset_shortfall_persisted":
                decisions.append(
                    StrategicFeedbackDecision(
                        StrategicFeedbackAction.REPLAN,
                        "asset shortfall persisted beyond the configured DCS-time threshold",
                        plan.plan_id,
                        goal.goal_id,
                    )
                )
                continue
            if event.event == "feedback.plan_allocation_changed":
                action = StrategicFeedbackAction.KEEP if plan.plan_id in executing else StrategicFeedbackAction.REPLAN
                reason = (
                    "retain running missions and use the new allocation on a later phase or plan"
                    if action is StrategicFeedbackAction.KEEP
                    else "allocation changed before execution; revalidate before approval or launch"
                )
                decisions.append(StrategicFeedbackDecision(action, reason, plan.plan_id, goal.goal_id))
                continue
            decisions.append(
                StrategicFeedbackDecision(
                    StrategicFeedbackAction.KEEP,
                    "no destructive operational response is required",
                    plan.plan_id,
                    goal.goal_id,
                )
            )
        return tuple(decisions)

    def _candidate_plans(self, event: StrategicFeedbackEvent) -> tuple[OperationalPlan, ...]:
        if event.plan_id:
            plan = self.plans.get(event.plan_id)
            return (plan,) if plan is not None else ()
        if event.goal_id:
            return tuple(plan for plan in self.plans.all() if plan.goal_id == event.goal_id)
        if event.event == "feedback.objective_changed" and event.reference_id:
            goal_ids = {
                goal.goal_id
                for goal in self.goals.filter(objective_id=event.reference_id)
            }
            return tuple(plan for plan in self.plans.all() if plan.goal_id in goal_ids)
        return ()


def _assessment_state(assessment: OperationalPlanAssessment) -> _PlanFeedbackState:
    allocations = tuple(
        (
            requirement.requirement_id,
            allocation.cohort_id,
            allocation.count,
        )
        for requirement in assessment.requirements
        for allocation in requirement.allocations
    )
    issues = tuple(
        (issue.severity, issue.code, issue.reference_id)
        for issue in assessment.issues
    )
    return _PlanFeedbackState(assessment.feasible, allocations, issues)


__all__ = [
    "StrategicFeedbackAction",
    "StrategicFeedbackDecision",
    "StrategicFeedbackEvent",
    "StrategicFeedbackMonitor",
    "StrategicFeedbackPolicy",
]
