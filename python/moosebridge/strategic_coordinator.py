"""Recurring bilateral strategic conflict coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
import inspect
import math
from typing import TYPE_CHECKING, Any

from .conflict_readiness import ConflictReadinessReport
from .operational import OperationalPlanStatus
from .operational_execution import OperationalPlanExecution, PlanExecutionEvent
from .strategic import StrategicGoalStatus, normalize_coalition
from .strategic_decision import (
    BilateralStrategicRecommendation,
    StrategicDecision,
    StrategicDecisionActivation,
    StrategicDecisionConfig,
)

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


STRATEGIC_COORDINATOR_AUDIT_TYPE = "strategic_conflict_cycle"

ReadinessProvider = Callable[[], Awaitable[ConflictReadinessReport]]
CoordinatorEventCallback = Callable[[str, PlanExecutionEvent], Any | Awaitable[Any]]
CoordinatorCycleCallback = Callable[["StrategicCoalitionCycle"], Any | Awaitable[Any]]


class StrategicCycleStatus(StrEnum):
    """Terminal result of one coalition decision cycle."""

    NO_SELECTION = "no_selection"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    PARTIAL = "partial"
    MISSION_CHANGED = "mission_changed"


class StrategicAttemptStatus(StrEnum):
    """Terminal result of one selected strategic candidate."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    ERROR = "error"
    MISSION_CHANGED = "mission_changed"


@dataclass(slots=True, frozen=True)
class StrategicCoordinatorConfig:
    """Scheduling, cooldown, and execution policy for both coalitions."""

    blue_cadence_s: float = 60.0
    red_cadence_s: float = 60.0
    completed_cooldown_s: float = 900.0
    blocked_cooldown_s: float = 300.0
    failed_cooldown_s: float = 600.0
    poll_interval_s: float = 5.0
    mission_timeout_s: float = 3600.0
    retain_audit: bool = True
    decision: StrategicDecisionConfig = field(default_factory=StrategicDecisionConfig)

    def __post_init__(self) -> None:
        positive = {
            "blue_cadence_s": self.blue_cadence_s,
            "red_cadence_s": self.red_cadence_s,
            "poll_interval_s": self.poll_interval_s,
            "mission_timeout_s": self.mission_timeout_s,
        }
        non_negative = {
            "completed_cooldown_s": self.completed_cooldown_s,
            "blocked_cooldown_s": self.blocked_cooldown_s,
            "failed_cooldown_s": self.failed_cooldown_s,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name, value in non_negative.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")

    def cadence(self, coalition: str) -> float:
        normalized = normalize_coalition(coalition)
        if normalized == "blue":
            return self.blue_cadence_s
        if normalized == "red":
            return self.red_cadence_s
        raise ValueError("strategic coordinator coalition must be blue or red")


@dataclass(slots=True, frozen=True)
class StrategicCandidateCooldown:
    """One candidate suppressed until a later DCS mission time."""

    coalition: str
    candidate_id: str
    objective_id: str
    status: StrategicAttemptStatus
    started_mission_time: float | None
    available_mission_time: float | None
    reason: str

    def active(self, mission_time: float | None) -> bool:
        """Return whether this cooldown still suppresses its candidate."""

        if self.available_mission_time is None or mission_time is None:
            return True
        return mission_time < self.available_mission_time


@dataclass(slots=True, frozen=True)
class StrategicCoordinatorAttempt:
    """Activation and execution result for one selected candidate."""

    decision: StrategicDecision
    activation: StrategicDecisionActivation | None
    status: StrategicAttemptStatus
    execution: OperationalPlanExecution | None = None
    error: str | None = None
    cooldown: StrategicCandidateCooldown | None = None


@dataclass(slots=True, frozen=True)
class StrategicCoalitionCycle:
    """One auditable recommendation and execution cycle for one coalition."""

    coalition: str
    cycle_number: int
    mission_generation: int
    started_mission_time: float | None
    completed_mission_time: float | None
    status: StrategicCycleStatus
    recommendation: BilateralStrategicRecommendation
    attempts: tuple[StrategicCoordinatorAttempt, ...] = ()
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class BilateralConflictRun:
    """Bounded result returned after both independent workers finish."""

    mission_generation: int
    requested_cycles_per_coalition: int
    cycles: tuple[StrategicCoalitionCycle, ...]

    def coalition(self, coalition: str) -> tuple[StrategicCoalitionCycle, ...]:
        """Return all cycles for one coalition in execution order."""

        normalized = normalize_coalition(coalition)
        return tuple(item for item in self.cycles if item.coalition == normalized)


class BilateralConflictCoordinator:
    """Run independent blue and red strategic workers on shared policy rails."""

    def __init__(
        self,
        client: MooseBridgeClient,
        readiness_provider: ReadinessProvider,
        config: StrategicCoordinatorConfig | None = None,
    ) -> None:
        self.client = client
        self.readiness_provider = readiness_provider
        self.config = config or StrategicCoordinatorConfig()
        self.mission_generation = client.state.mission_generation
        self._decision_lock = asyncio.Lock()
        self._cycle_numbers = {"blue": 0, "red": 0}
        self._last_cycle_mission_time: dict[str, float | None] = {"blue": None, "red": None}
        self._cooldowns: dict[tuple[str, str], StrategicCandidateCooldown] = {}

    @property
    def cooldowns(self) -> tuple[StrategicCandidateCooldown, ...]:
        """Return all cooldown records, including ones that already elapsed."""

        return tuple(self._cooldowns[key] for key in sorted(self._cooldowns))

    async def run(
        self,
        *,
        cycles_per_coalition: int = 3,
        on_event: CoordinatorEventCallback | None = None,
        on_cycle: CoordinatorCycleCallback | None = None,
    ) -> BilateralConflictRun:
        """Run a bounded number of independently paced cycles per coalition."""

        if cycles_per_coalition < 1:
            raise ValueError("cycles_per_coalition must be at least one")

        async def worker(coalition: str) -> tuple[StrategicCoalitionCycle, ...]:
            cycles: list[StrategicCoalitionCycle] = []
            while len(cycles) < cycles_per_coalition:
                cycle = await self.run_cycle(coalition, on_event=on_event)
                if cycle is None:
                    await asyncio.sleep(self.config.poll_interval_s)
                    continue
                cycles.append(cycle)
                if on_cycle is not None:
                    value = on_cycle(cycle)
                    if inspect.isawaitable(value):
                        await value
                if cycle.status is StrategicCycleStatus.MISSION_CHANGED:
                    break
            return tuple(cycles)

        blue, red = await asyncio.gather(worker("blue"), worker("red"))
        cycles = tuple(sorted((*blue, *red), key=_cycle_sort_key))
        return BilateralConflictRun(
            mission_generation=self.mission_generation,
            requested_cycles_per_coalition=cycles_per_coalition,
            cycles=cycles,
        )

    async def run_cycle(
        self,
        coalition: str,
        *,
        on_event: CoordinatorEventCallback | None = None,
    ) -> StrategicCoalitionCycle | None:
        """Run one due cycle, or return ``None`` while its cadence is pending."""

        coalition = normalize_coalition(coalition) or ""
        if coalition not in {"blue", "red"}:
            raise ValueError("strategic coordinator coalition must be blue or red")

        async with self._decision_lock:
            if self.client.state.mission_generation != self.mission_generation:
                return self._mission_changed_cycle(coalition, None)
            readiness = await self.readiness_provider()
            readiness.require_ready()
            if (
                readiness.mission_generation != self.mission_generation
                or self.client.state.mission_generation != self.mission_generation
            ):
                return self._mission_changed_cycle(coalition, readiness.mission_time)
            mission_time = readiness.mission_time
            previous = self._last_cycle_mission_time[coalition]
            if (
                previous is not None
                and mission_time is not None
                and mission_time < previous + self.config.cadence(coalition)
            ):
                return None

            excluded = {
                candidate_id
                for (candidate_coalition, candidate_id), cooldown in self._cooldowns.items()
                if candidate_coalition == coalition and cooldown.active(mission_time)
            }
            recommendation = await self.client.recommend_bilateral_strategy(
                readiness,
                config=self.config.decision,
                excluded_candidate_ids={coalition: excluded},
                retain_audit=self.config.retain_audit,
            )
            decisions = recommendation.coalition(coalition).selected
            self._cycle_numbers[coalition] += 1
            cycle_number = self._cycle_numbers[coalition]
            self._last_cycle_mission_time[coalition] = mission_time

            activations: list[tuple[StrategicDecision, StrategicDecisionActivation]] = []
            activation_failures: list[StrategicCoordinatorAttempt] = []
            for decision in decisions:
                try:
                    activation = await self.client.activate_strategic_decision(
                        recommendation,
                        decision,
                        retain_audit=self.config.retain_audit,
                    )
                except Exception as exc:
                    activation_failures.append(
                        self._failed_attempt(decision, None, exc, mission_time)
                    )
                else:
                    activations.append((decision, activation))

        if not decisions:
            cycle = StrategicCoalitionCycle(
                coalition=coalition,
                cycle_number=cycle_number,
                mission_generation=self.mission_generation,
                started_mission_time=mission_time,
                completed_mission_time=self._current_mission_time(),
                status=StrategicCycleStatus.NO_SELECTION,
                recommendation=recommendation,
                reason="no eligible strategic candidate was selected",
            )
            await self._retain_cycle(cycle)
            return cycle

        async def execute_one(
            decision: StrategicDecision,
            activation: StrategicDecisionActivation,
        ) -> StrategicCoordinatorAttempt:
            async def forward(event: PlanExecutionEvent) -> None:
                if on_event is None:
                    return
                value = on_event(coalition, event)
                if inspect.isawaitable(value):
                    await value

            try:
                execution = await self.client.execute_strategic_activation(
                    activation,
                    approved_by="Bilateral Conflict Coordinator",
                    approval_reason=(
                        f"Approved by bilateral coordinator {coalition} cycle {cycle_number}"
                    ),
                    mission_timeout_s=self.config.mission_timeout_s,
                    on_event=forward,
                )
            except Exception as exc:
                return self._failed_attempt(decision, activation, exc, mission_time)
            return self._execution_attempt(decision, activation, execution, mission_time)

        executed = await asyncio.gather(
            *(execute_one(decision, activation) for decision, activation in activations)
        )
        attempts = tuple((*activation_failures, *executed))
        cycle = StrategicCoalitionCycle(
            coalition=coalition,
            cycle_number=cycle_number,
            mission_generation=self.mission_generation,
            started_mission_time=mission_time,
            completed_mission_time=self._current_mission_time(),
            status=_cycle_status(attempts),
            recommendation=recommendation,
            attempts=attempts,
            reason=_cycle_reason(attempts),
        )
        await self._retain_cycle(cycle)
        return cycle

    def _execution_attempt(
        self,
        decision: StrategicDecision,
        activation: StrategicDecisionActivation,
        execution: OperationalPlanExecution,
        started_mission_time: float | None,
    ) -> StrategicCoordinatorAttempt:
        if execution.status is OperationalPlanStatus.COMPLETED:
            status = StrategicAttemptStatus.COMPLETED
        elif execution.status is OperationalPlanStatus.BLOCKED:
            status = StrategicAttemptStatus.BLOCKED
        else:
            status = StrategicAttemptStatus.FAILED
        reason = execution.blocked_reason or f"operational plan ended {execution.status.value}"
        if status is not StrategicAttemptStatus.COMPLETED:
            self._terminalize_activation(activation, reason)
        cooldown = self._set_cooldown(decision, status, started_mission_time, reason)
        return StrategicCoordinatorAttempt(decision, activation, status, execution, None, cooldown)

    def _failed_attempt(
        self,
        decision: StrategicDecision,
        activation: StrategicDecisionActivation | None,
        error: Exception,
        started_mission_time: float | None,
    ) -> StrategicCoordinatorAttempt:
        if self.client.state.mission_generation != self.mission_generation:
            status = StrategicAttemptStatus.MISSION_CHANGED
        else:
            status = StrategicAttemptStatus.ERROR
            if activation is not None:
                self._terminalize_activation(activation, str(error))
        cooldown = self._set_cooldown(decision, status, started_mission_time, str(error))
        return StrategicCoordinatorAttempt(decision, activation, status, None, str(error), cooldown)

    def _terminalize_activation(self, activation: StrategicDecisionActivation, reason: str) -> None:
        goal = self.client.strategic_goal(activation.goal.goal_id)
        plan = self.client.operational_plan(activation.plan.plan_id)
        if goal is not None and goal.status is StrategicGoalStatus.ACTIVE:
            self.client.complete_strategic_goal(goal, achieved=False, reason=reason)
        if plan is not None and plan.status in {
            OperationalPlanStatus.VALIDATED,
            OperationalPlanStatus.APPROVED,
            OperationalPlanStatus.EXECUTING,
        }:
            plan.status = OperationalPlanStatus.FAILED

    def _set_cooldown(
        self,
        decision: StrategicDecision,
        status: StrategicAttemptStatus,
        started_mission_time: float | None,
        reason: str,
    ) -> StrategicCandidateCooldown | None:
        if status is StrategicAttemptStatus.MISSION_CHANGED:
            return None
        duration = (
            self.config.completed_cooldown_s
            if status is StrategicAttemptStatus.COMPLETED
            else self.config.blocked_cooldown_s
            if status is StrategicAttemptStatus.BLOCKED
            else self.config.failed_cooldown_s
        )
        now = self._current_mission_time()
        if now is None:
            now = started_mission_time
        available = now + duration if now is not None else None
        cooldown = StrategicCandidateCooldown(
            coalition=decision.coalition,
            candidate_id=decision.candidate_id,
            objective_id=decision.objective_id,
            status=status,
            started_mission_time=now,
            available_mission_time=available,
            reason=reason,
        )
        self._cooldowns[(decision.coalition, decision.candidate_id)] = cooldown
        return cooldown

    def _mission_changed_cycle(
        self,
        coalition: str,
        mission_time: float | None,
    ) -> StrategicCoalitionCycle:
        self._cycle_numbers[coalition] += 1
        empty = BilateralStrategicRecommendation(
            mission_generation=self.mission_generation,
            mission_time=mission_time,
            relationship_state=self.client.relationship.state.value,
            portfolios=(),
        )
        return StrategicCoalitionCycle(
            coalition=coalition,
            cycle_number=self._cycle_numbers[coalition],
            mission_generation=self.mission_generation,
            started_mission_time=mission_time,
            completed_mission_time=mission_time,
            status=StrategicCycleStatus.MISSION_CHANGED,
            recommendation=empty,
            reason="DCS mission generation changed; coordinator stopped",
        )

    async def _retain_cycle(self, cycle: StrategicCoalitionCycle) -> None:
        append = getattr(self.client.server, "append_audit_record", None)
        if self.config.retain_audit and callable(append):
            await append(
                STRATEGIC_COORDINATOR_AUDIT_TYPE,
                strategic_coordinator_cycle_to_dict(cycle),
            )

    def _current_mission_time(self) -> float | None:
        clock = self.client.state.clock
        return clock.mission_time if clock is not None else None


def strategic_coordinator_cycle_to_dict(cycle: StrategicCoalitionCycle) -> dict[str, object]:
    """Return the compact persistent audit payload for one coordinator cycle."""

    return {
        "schema_version": 1,
        "mission_generation": cycle.mission_generation,
        "coalition": cycle.coalition,
        "cycle_number": cycle.cycle_number,
        "started_mission_time": cycle.started_mission_time,
        "completed_mission_time": cycle.completed_mission_time,
        "status": cycle.status.value,
        "reason": cycle.reason,
        "attempts": [
            {
                "candidate_id": attempt.decision.candidate_id,
                "objective_id": attempt.decision.objective_id,
                "action": attempt.decision.action.value if attempt.decision.action else None,
                "effect": attempt.decision.effect.value if attempt.decision.effect else None,
                "activation_id": attempt.activation.activation_id if attempt.activation else None,
                "plan_id": attempt.activation.plan.plan_id if attempt.activation else None,
                "attempt_id": attempt.execution.attempt_id if attempt.execution else None,
                "status": attempt.status.value,
                "error": attempt.error,
                "cooldown_until": attempt.cooldown.available_mission_time if attempt.cooldown else None,
            }
            for attempt in cycle.attempts
        ],
    }


def format_bilateral_conflict_run(result: BilateralConflictRun) -> str:
    """Format a bounded coordinator result for examples and operators."""

    lines = [
        (
            f"Bilateral conflict run generation={result.mission_generation} "
            f"requested_cycles={result.requested_cycles_per_coalition}"
        )
    ]
    for cycle in result.cycles:
        lines.append(
            f"  {cycle.coalition} cycle={cycle.cycle_number} status={cycle.status.value} "
            f"mission_time={_time_text(cycle.started_mission_time)} attempts={len(cycle.attempts)}"
        )
        if cycle.reason:
            lines.append(f"    reason={cycle.reason}")
        for attempt in cycle.attempts:
            cooldown = (
                f" cooldown_until={_time_text(attempt.cooldown.available_mission_time)}"
                if attempt.cooldown is not None
                else ""
            )
            lines.append(
                f"    {attempt.decision.candidate_id} status={attempt.status.value}{cooldown}"
            )
    return "\n".join(lines)


def _cycle_status(attempts: tuple[StrategicCoordinatorAttempt, ...]) -> StrategicCycleStatus:
    statuses = {attempt.status for attempt in attempts}
    if not statuses:
        return StrategicCycleStatus.NO_SELECTION
    if statuses == {StrategicAttemptStatus.COMPLETED}:
        return StrategicCycleStatus.COMPLETED
    if statuses == {StrategicAttemptStatus.BLOCKED}:
        return StrategicCycleStatus.BLOCKED
    if StrategicAttemptStatus.MISSION_CHANGED in statuses:
        return StrategicCycleStatus.MISSION_CHANGED
    if len(statuses) == 1:
        return StrategicCycleStatus.FAILED
    return StrategicCycleStatus.PARTIAL


def _cycle_reason(attempts: tuple[StrategicCoordinatorAttempt, ...]) -> str | None:
    messages = [attempt.error for attempt in attempts if attempt.error]
    messages.extend(
        attempt.execution.blocked_reason
        for attempt in attempts
        if attempt.execution is not None and attempt.execution.blocked_reason
    )
    return "; ".join(dict.fromkeys(messages)) or None


def _cycle_sort_key(cycle: StrategicCoalitionCycle) -> tuple[float, str, int]:
    return (
        cycle.started_mission_time if cycle.started_mission_time is not None else math.inf,
        cycle.coalition,
        cycle.cycle_number,
    )


def _time_text(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


__all__ = [
    "STRATEGIC_COORDINATOR_AUDIT_TYPE",
    "BilateralConflictCoordinator",
    "BilateralConflictRun",
    "CoordinatorCycleCallback",
    "CoordinatorEventCallback",
    "StrategicAttemptStatus",
    "StrategicCandidateCooldown",
    "StrategicCoalitionCycle",
    "StrategicCoordinatorAttempt",
    "StrategicCoordinatorConfig",
    "StrategicCycleStatus",
    "format_bilateral_conflict_run",
    "strategic_coordinator_cycle_to_dict",
]
