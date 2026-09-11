"""Recurring bilateral strategic conflict coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import inspect
import math
from typing import TYPE_CHECKING, Any

from .conflict_readiness import ConflictReadinessReport
from .server import DcsMissionEndedError
from .operational import OperationalPlanStatus
from .operational_execution import (
    PLAN_EXECUTION_AUDIT_TYPE,
    OperationalPlanExecution,
    PlanExecutionEvent,
    PlanReconciliationStatus,
)
from .strategic import StrategicGoal, StrategicGoalStatus, normalize_coalition
from .strategic_decision import (
    BilateralStrategicRecommendation,
    StrategicDecision,
    StrategicDecisionActivation,
    StrategicDecisionConfig,
)

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


STRATEGIC_COORDINATOR_AUDIT_TYPE = "strategic_conflict_cycle"
STRATEGIC_COORDINATOR_APPROVER = "Bilateral Conflict Coordinator"

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


class StrategicRecoveryStatus(StrEnum):
    """Outcome of recovering one coordinator-owned interrupted plan."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    MISSION_CHANGED = "mission_changed"


@dataclass(slots=True, frozen=True)
class StrategicCoordinatorConfig:
    """Scheduling, cooldown, and execution policy for both coalitions."""

    blue_cadence_s: float = 60.0
    red_cadence_s: float = 60.0
    no_selection_backoff_s: float = 300.0
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
            "no_selection_backoff_s": self.no_selection_backoff_s,
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
class StrategicCoordinatorRecovery:
    """Result of reconciling one plan left active by a previous SDK client."""

    coalition: str
    candidate_id: str
    objective_id: str
    plan_id: str
    interrupted_attempt_id: str
    status: StrategicRecoveryStatus
    auftrag_ids: tuple[str, ...] = ()
    resumed_attempt_id: str | None = None
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class BilateralConflictRun:
    """Result returned after both independent coalition workers finish."""

    mission_generation: int
    requested_cycles_per_coalition: int | None
    cycles: tuple[StrategicCoalitionCycle, ...]
    cooldowns: tuple[StrategicCandidateCooldown, ...] = ()
    recoveries: tuple[StrategicCoordinatorRecovery, ...] = ()

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
        self._not_before_mission_time: dict[str, float | None] = {"blue": None, "red": None}
        self._cooldowns: dict[tuple[str, str], StrategicCandidateCooldown] = {}
        self._audit_state_loaded = False
        self._mission_ended = False
        self._interrupted_plans: tuple[dict[str, Any], ...] = ()

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
        return await self._run(
            cycles_per_coalition=cycles_per_coalition,
            on_event=on_event,
            on_cycle=on_cycle,
        )

    async def run_until_mission_end(
        self,
        *,
        on_event: CoordinatorEventCallback | None = None,
        on_cycle: CoordinatorCycleCallback | None = None,
    ) -> BilateralConflictRun:
        """Run both workers until the current DCS mission generation changes.

        This method never follows the next mission. The caller must construct a
        fresh coordinator for every new mission generation.
        """

        watcher = await self._start_mission_boundary_watcher()
        try:
            return await self._run(
                cycles_per_coalition=None,
                on_event=on_event,
                on_cycle=on_cycle,
            )
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)

    async def _run(
        self,
        *,
        cycles_per_coalition: int | None,
        on_event: CoordinatorEventCallback | None,
        on_cycle: CoordinatorCycleCallback | None,
    ) -> BilateralConflictRun:
        """Run bounded or mission-bound coalition workers."""

        await self._load_audit_state()

        async def worker(
            coalition: str,
        ) -> tuple[tuple[StrategicCoalitionCycle, ...], tuple[StrategicCoordinatorRecovery, ...]]:
            cycles: list[StrategicCoalitionCycle] = []
            recoveries: list[StrategicCoordinatorRecovery] = []
            for payload in self._interrupted_plans:
                if self._interrupted_plan_coalition(payload) != coalition:
                    continue
                recovery = await self._recover_interrupted_plan(payload, on_event=on_event)
                recoveries.append(recovery)
                if recovery.status is StrategicRecoveryStatus.MISSION_CHANGED:
                    cycle = self._mission_changed_cycle(coalition, self._current_mission_time())
                    cycles.append(cycle)
                    if on_cycle is not None:
                        value = on_cycle(cycle)
                        if inspect.isawaitable(value):
                            await value
                    return tuple(cycles), tuple(recoveries)
            while cycles_per_coalition is None or len(cycles) < cycles_per_coalition:
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
            return tuple(cycles), tuple(recoveries)

        blue, red = await asyncio.gather(worker("blue"), worker("red"))
        cycles = tuple(sorted((*blue[0], *red[0]), key=_cycle_sort_key))
        recoveries = tuple(sorted((*blue[1], *red[1]), key=_recovery_sort_key))
        return BilateralConflictRun(
            mission_generation=self.mission_generation,
            requested_cycles_per_coalition=cycles_per_coalition,
            cycles=cycles,
            cooldowns=self.cooldowns,
            recoveries=recoveries,
        )

    async def _load_audit_state(self) -> None:
        """Restore current-generation cooldowns and find interrupted coordinator plans."""

        if self._audit_state_loaded:
            return
        query = getattr(self.client.server, "query_audit_records", None)
        if not callable(query):
            self._audit_state_loaded = True
            return

        cycle_records = await query(record_type=STRATEGIC_COORDINATOR_AUDIT_TYPE)
        execution_records = await query(
            record_type=PLAN_EXECUTION_AUDIT_TYPE,
            latest_attempts=True,
        )
        audit_session_id = str(getattr(self.client.state, "audit_session_id", "") or "")
        for record in cycle_records:
            payload = _audit_payload(record)
            if not self._is_current_audit_payload(payload, audit_session_id=audit_session_id):
                continue
            self._restore_cycle_audit(payload)

        interrupted: list[dict[str, Any]] = []
        for record in execution_records:
            payload = _audit_payload(record)
            if not self._is_current_audit_payload(payload, audit_session_id=audit_session_id):
                continue
            if not self._is_coordinator_execution(payload):
                continue
            if str(payload.get("status") or "").casefold() == OperationalPlanStatus.EXECUTING.value:
                interrupted.append(dict(payload))
            else:
                self._restore_execution_cooldown(payload)

        self._interrupted_plans = tuple(
            sorted(
                interrupted,
                key=_execution_sort_key,
            )
        )
        self._audit_state_loaded = True

    def _is_current_audit_payload(
        self,
        payload: Mapping[str, Any],
        *,
        audit_session_id: str,
    ) -> bool:
        try:
            generation = int(payload.get("mission_generation"))
        except (TypeError, ValueError):
            return False
        return (
            generation == self.mission_generation
            and bool(audit_session_id)
            and str(payload.get("audit_session_id") or "") == audit_session_id
        )

    def _restore_cycle_audit(self, payload: Mapping[str, Any]) -> None:
        coalition = normalize_coalition(payload.get("coalition")) or ""
        if coalition not in {"blue", "red"}:
            return
        try:
            cycle_number = int(payload.get("cycle_number") or 0)
        except (TypeError, ValueError):
            cycle_number = 0
        previous_cycle_number = self._cycle_numbers[coalition]
        self._cycle_numbers[coalition] = max(previous_cycle_number, cycle_number)
        started = _optional_number(payload.get("started_mission_time"))
        previous = self._last_cycle_mission_time[coalition]
        is_latest = started is not None and (
            previous is None
            or started > previous
            or (started == previous and cycle_number > previous_cycle_number)
        )
        if is_latest:
            self._last_cycle_mission_time[coalition] = started
            self._not_before_mission_time[coalition] = (
                started + self.config.no_selection_backoff_s
                if str(payload.get("status") or "") == StrategicCycleStatus.NO_SELECTION.value
                else None
            )

        attempts = payload.get("attempts")
        if not isinstance(attempts, list):
            return
        for attempt in attempts:
            if not isinstance(attempt, Mapping):
                continue
            candidate_id = str(attempt.get("candidate_id") or "")
            objective_id = str(attempt.get("objective_id") or "")
            if not candidate_id or not objective_id:
                continue
            try:
                status = StrategicAttemptStatus(str(attempt.get("status") or ""))
            except ValueError:
                continue
            if status is StrategicAttemptStatus.MISSION_CHANGED:
                continue
            cooldown = StrategicCandidateCooldown(
                coalition=coalition,
                candidate_id=candidate_id,
                objective_id=objective_id,
                status=status,
                started_mission_time=started,
                available_mission_time=_optional_number(attempt.get("cooldown_until")),
                reason=str(attempt.get("error") or payload.get("reason") or "restored coordinator cooldown"),
            )
            self._merge_cooldown(cooldown)

    def _restore_execution_cooldown(self, payload: Mapping[str, Any]) -> None:
        plan = payload.get("plan")
        goal = payload.get("goal")
        objective = payload.get("objective")
        if not isinstance(plan, Mapping):
            return
        metadata = plan.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        candidate_id = str(metadata.get("candidate_id") or "")
        coalition = normalize_coalition(plan.get("coalition")) or ""
        objective_id = ""
        if isinstance(objective, Mapping):
            objective_id = str(objective.get("objective_id") or "")
        elif isinstance(goal, Mapping):
            objective_id = str(goal.get("objective_id") or "")
        if not candidate_id or coalition not in {"blue", "red"} or not objective_id:
            return
        execution_status = str(payload.get("status") or "").casefold()
        status = (
            StrategicAttemptStatus.COMPLETED
            if execution_status == OperationalPlanStatus.COMPLETED.value
            else StrategicAttemptStatus.BLOCKED
            if execution_status == OperationalPlanStatus.BLOCKED.value
            else StrategicAttemptStatus.FAILED
        )
        completed = _optional_number(payload.get("completed_mission_time"))
        started = _optional_number(payload.get("started_mission_time"))
        base_time = completed if completed is not None else started
        cooldown = self._make_cooldown(
            coalition=coalition,
            candidate_id=candidate_id,
            objective_id=objective_id,
            status=status,
            started_mission_time=base_time,
            reason=str(payload.get("blocked_reason") or f"restored {execution_status} execution"),
            base_time=base_time,
        )
        self._merge_cooldown(cooldown)

    async def _recover_interrupted_plan(
        self,
        payload: Mapping[str, Any],
        *,
        on_event: CoordinatorEventCallback | None,
    ) -> StrategicCoordinatorRecovery:
        plan_id = str(payload.get("plan_id") or "")
        interrupted_attempt_id = str(payload.get("attempt_id") or "")
        coalition = self._interrupted_plan_coalition(payload)
        plan_snapshot = payload.get("plan")
        plan_metadata = (
            plan_snapshot.get("metadata")
            if isinstance(plan_snapshot, Mapping) and isinstance(plan_snapshot.get("metadata"), Mapping)
            else {}
        )
        objective_snapshot = payload.get("objective")
        candidate_id = str(plan_metadata.get("candidate_id") or "")
        objective_id = str(
            objective_snapshot.get("objective_id")
            if isinstance(objective_snapshot, Mapping)
            else ""
        )
        auftrag_ids = tuple(
            dict.fromkeys(
                str(mission.get("auftrag_id"))
                for mission in payload.get("missions", ())
                if isinstance(mission, Mapping) and mission.get("auftrag_id")
            )
        )

        async def forward(event: PlanExecutionEvent) -> None:
            if on_event is None:
                return
            value = on_event(coalition, event)
            if inspect.isawaitable(value):
                await value

        await forward(
            PlanExecutionEvent(
                "plan.recovery_started",
                plan_id,
                status="recovering",
                message=(
                    f"reattaching to {', '.join(auftrag_ids)}"
                    if auftrag_ids
                    else "reconciling interrupted coordinator plan"
                ),
                attempt_id=interrupted_attempt_id,
            )
        )

        resumed_attempt_id: str | None = None
        reason: str | None = None
        recovery_status = StrategicRecoveryStatus.FAILED
        restored = None
        try:
            restored = await self.client.restore_operational_plan(plan_id, replace=True)
            reconciliation = await self.client.monitor_interrupted_operational_plan(
                restored.plan,
                mission_timeout_s=self.config.mission_timeout_s,
                on_event=forward,
            )
            if self.client.state.mission_generation != self.mission_generation:
                recovery_status = StrategicRecoveryStatus.MISSION_CHANGED
                reason = "DCS mission generation changed during coordinator recovery"
            elif reconciliation.status is PlanReconciliationStatus.REVALIDATION_REQUIRED:
                await forward(
                    PlanExecutionEvent(
                        "plan.recovery_revalidating",
                        plan_id,
                        status="pending",
                        message="revalidating the first unfinished phase at a safe recovery boundary",
                        attempt_id=interrupted_attempt_id,
                    )
                )
                self.client.prepare_plan_retry(restored.plan)
                assessment = await self.client.refresh_and_validate_operational_plan(restored.plan)
                if not assessment.feasible:
                    reason = "remaining phases are no longer feasible after coordinator recovery"
                    restored.plan.status = OperationalPlanStatus.FAILED
                    self._fail_restored_goal(restored.goal, reason)
                    recovery_status = StrategicRecoveryStatus.BLOCKED
                else:
                    self.client.approve_operational_plan(
                        restored.plan,
                        approved_by=STRATEGIC_COORDINATOR_APPROVER,
                        reason="Resume unfinished phases after SDK client restart",
                    )
                    resumed = await self.client.execute_plan(
                        restored.plan,
                        commander=payload.get("commander_id") or None,
                        mission_timeout_s=self.config.mission_timeout_s,
                        on_event=forward,
                    )
                    resumed_attempt_id = resumed.attempt_id
                    recovery_status = (
                        StrategicRecoveryStatus.COMPLETED
                        if resumed.status is OperationalPlanStatus.COMPLETED
                        else StrategicRecoveryStatus.BLOCKED
                        if resumed.status is OperationalPlanStatus.BLOCKED
                        else StrategicRecoveryStatus.FAILED
                    )
                    reason = resumed.blocked_reason
                    if recovery_status is not StrategicRecoveryStatus.COMPLETED:
                        self._fail_restored_goal(
                            restored.goal,
                            reason or f"operational plan ended {resumed.status.value}",
                        )
            elif reconciliation.status is PlanReconciliationStatus.COMPLETED:
                recovery_status = StrategicRecoveryStatus.COMPLETED
                reason = reconciliation.message
            elif reconciliation.status is PlanReconciliationStatus.BLOCKED:
                recovery_status = StrategicRecoveryStatus.BLOCKED
                reason = reconciliation.message or "interrupted operational plan could not be resumed"
                self._fail_restored_goal(restored.goal, reason)
            else:
                raise RuntimeError(
                    reconciliation.message
                    or f"interrupted operational plan reconciliation ended {reconciliation.status.value}"
                )
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            if self.client.state.mission_generation != self.mission_generation:
                recovery_status = StrategicRecoveryStatus.MISSION_CHANGED
            else:
                await forward(
                    PlanExecutionEvent(
                        "plan.recovery_failed",
                        plan_id,
                        status="failed",
                        message=reason,
                        attempt_id=interrupted_attempt_id,
                    )
                )
                raise RuntimeError(f"coordinator recovery failed for {plan_id}: {reason}") from exc

        if recovery_status is not StrategicRecoveryStatus.MISSION_CHANGED:
            cooldown_status = (
                StrategicAttemptStatus.COMPLETED
                if recovery_status is StrategicRecoveryStatus.COMPLETED
                else StrategicAttemptStatus.BLOCKED
                if recovery_status is StrategicRecoveryStatus.BLOCKED
                else StrategicAttemptStatus.FAILED
            )
            cooldown = self._make_cooldown(
                coalition=coalition,
                candidate_id=candidate_id,
                objective_id=objective_id,
                status=cooldown_status,
                started_mission_time=_optional_number(payload.get("started_mission_time")),
                reason=reason or "recovered operational plan completed",
            )
            self._merge_cooldown(cooldown)

        await forward(
            PlanExecutionEvent(
                "plan.recovered",
                plan_id,
                status=recovery_status.value,
                message=reason,
                attempt_id=resumed_attempt_id or interrupted_attempt_id,
            )
        )
        return StrategicCoordinatorRecovery(
            coalition=coalition,
            candidate_id=candidate_id,
            objective_id=objective_id,
            plan_id=plan_id,
            interrupted_attempt_id=interrupted_attempt_id,
            status=recovery_status,
            auftrag_ids=auftrag_ids,
            resumed_attempt_id=resumed_attempt_id,
            reason=reason,
        )

    def _interrupted_plan_coalition(self, payload: Mapping[str, Any]) -> str:
        plan = payload.get("plan")
        coalition = normalize_coalition(plan.get("coalition")) if isinstance(plan, Mapping) else None
        return coalition or ""

    def _is_coordinator_execution(self, payload: Mapping[str, Any]) -> bool:
        plan = payload.get("plan")
        if not isinstance(plan, Mapping):
            return False
        metadata = plan.get("metadata")
        return (
            isinstance(metadata, Mapping)
            and bool(metadata.get("candidate_id"))
            and str(plan.get("approved_by") or "") == STRATEGIC_COORDINATOR_APPROVER
        )

    def _fail_restored_goal(self, goal: StrategicGoal, reason: str) -> None:
        current = self.client.strategic_goal(goal.goal_id)
        if current is not None and current.status is StrategicGoalStatus.ACTIVE:
            self.client.complete_strategic_goal(current, achieved=False, reason=reason)

    def _make_cooldown(
        self,
        *,
        coalition: str,
        candidate_id: str,
        objective_id: str,
        status: StrategicAttemptStatus,
        started_mission_time: float | None,
        reason: str,
        base_time: float | None = None,
    ) -> StrategicCandidateCooldown:
        duration = (
            self.config.completed_cooldown_s
            if status is StrategicAttemptStatus.COMPLETED
            else self.config.blocked_cooldown_s
            if status is StrategicAttemptStatus.BLOCKED
            else self.config.failed_cooldown_s
        )
        if base_time is None:
            base_time = self._current_mission_time()
        if base_time is None:
            base_time = started_mission_time
        return StrategicCandidateCooldown(
            coalition=coalition,
            candidate_id=candidate_id,
            objective_id=objective_id,
            status=status,
            started_mission_time=started_mission_time,
            available_mission_time=base_time + duration if base_time is not None else None,
            reason=reason,
        )

    def _merge_cooldown(self, cooldown: StrategicCandidateCooldown) -> None:
        if not cooldown.candidate_id or cooldown.coalition not in {"blue", "red"}:
            return
        key = (cooldown.coalition, cooldown.candidate_id)
        previous = self._cooldowns.get(key)
        if previous is None or _cooldown_sort_value(cooldown) >= _cooldown_sort_value(previous):
            self._cooldowns[key] = cooldown

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

        try:
            return await self._run_cycle(coalition, on_event=on_event)
        except Exception as exc:
            if not self._has_mission_ended(exc):
                raise
            return self._mission_changed_cycle(coalition, self._current_mission_time())

    def _has_mission_ended(self, error: Exception | None = None) -> bool:
        # A command response can report mission end before the passive event
        # watcher updates the local generation. Retain that terminal boundary.
        if isinstance(error, DcsMissionEndedError):
            self._mission_ended = True
        return self._mission_ended or self.client.state.mission_generation != self.mission_generation

    async def _run_cycle(
        self,
        coalition: str,
        *,
        on_event: CoordinatorEventCallback | None,
    ) -> StrategicCoalitionCycle | None:
        async with self._decision_lock:
            if self._has_mission_ended():
                return self._mission_changed_cycle(coalition, None)
            readiness = await self.readiness_provider()
            if (
                readiness.mission_generation != self.mission_generation
                or self._has_mission_ended()
            ):
                return self._mission_changed_cycle(coalition, readiness.mission_time)
            readiness.require_ready()
            mission_time = readiness.mission_time
            previous = self._last_cycle_mission_time[coalition]
            if mission_time is not None:
                next_due = self._not_before_mission_time[coalition]
                if previous is not None:
                    cadence_due = previous + self.config.cadence(coalition)
                    next_due = cadence_due if next_due is None else max(next_due, cadence_due)
                if next_due is not None and mission_time < next_due:
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
            self._not_before_mission_time[coalition] = (
                mission_time + self.config.no_selection_backoff_s
                if not decisions and mission_time is not None
                else None
            )

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
                    approved_by=STRATEGIC_COORDINATOR_APPROVER,
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
        if self._has_mission_ended(error):
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
        now = self._current_mission_time()
        if now is None:
            now = started_mission_time
        cooldown = self._make_cooldown(
            coalition=decision.coalition,
            candidate_id=decision.candidate_id,
            objective_id=decision.objective_id,
            status=status,
            started_mission_time=now,
            reason=reason,
            base_time=now,
        )
        self._merge_cooldown(cooldown)
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
            payload = strategic_coordinator_cycle_to_dict(cycle)
            payload["audit_session_id"] = str(
                getattr(self.client.state, "audit_session_id", "") or ""
            )
            await append(
                STRATEGIC_COORDINATOR_AUDIT_TYPE,
                payload,
            )

    def _current_mission_time(self) -> float | None:
        clock = self.client.state.clock
        return clock.mission_time if clock is not None else None

    async def _start_mission_boundary_watcher(self) -> asyncio.Task[object] | None:
        """Start a passive event wait so control-backed state sees mission end promptly."""

        cursor_method = getattr(self.client.server, "event_cursor", None)
        wait_method = getattr(self.client.server, "wait_for_event", None)
        if not callable(cursor_method) or not callable(wait_method):
            return None
        cursor = await cursor_method()
        return asyncio.create_task(
            wait_method(
                "mission.ended",
                timeout=31_536_000.0,
                after_id=cursor,
            )
        )


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
    """Format a completed coordinator run for examples and operators."""

    requested = (
        str(result.requested_cycles_per_coalition)
        if result.requested_cycles_per_coalition is not None
        else "until_mission_end"
    )
    lines = [
        (
            f"Bilateral conflict run generation={result.mission_generation} "
            f"requested_cycles={requested} cooldowns={len(result.cooldowns)} "
            f"recoveries={len(result.recoveries)}"
        )
    ]
    if result.recoveries:
        recovery_counts = ", ".join(
            f"{status.value}={sum(item.status is status for item in result.recoveries)}"
            for status in StrategicRecoveryStatus
            if any(item.status is status for item in result.recoveries)
        )
        lines.append(f"  recovered interrupted plans: {recovery_counts}")
    for coalition in ("blue", "red"):
        cycles = result.coalition(coalition)
        status_counts = ", ".join(
            f"{status.value}={sum(cycle.status is status for cycle in cycles)}"
            for status in StrategicCycleStatus
            if any(cycle.status is status for cycle in cycles)
        ) or "none"
        lines.append(
            f"  {coalition}: cycles={len(cycles)} attempts="
            f"{sum(len(cycle.attempts) for cycle in cycles)} statuses=[{status_counts}]"
        )
        if cycles and cycles[-1].reason:
            lines.append(f"    latest_reason={cycles[-1].reason}")
    return "\n".join(lines)


def format_strategic_coalition_cycle(cycle: StrategicCoalitionCycle) -> str:
    """Format one concise live coordinator-cycle status line."""

    try:
        portfolio = cycle.recommendation.coalition(cycle.coalition)
    except ValueError:
        selected = deferred = rejected = 0
    else:
        selected = len(portfolio.selected)
        deferred = len(portfolio.deferred)
        rejected = len(portfolio.rejected)
    attempts = ",".join(attempt.status.value for attempt in cycle.attempts) or "none"
    text = (
        f"[{cycle.coalition}] cycle={cycle.cycle_number} status={cycle.status.value} "
        f"mission_time={_time_text(cycle.started_mission_time)} "
        f"decisions={selected}/{deferred}/{rejected} "
        f"(selected/deferred/rejected) attempts={attempts}"
    )
    return f"{text} reason={cycle.reason}" if cycle.reason else text


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


def _audit_payload(record: object) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        return {}
    payload = record.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _cooldown_sort_value(cooldown: StrategicCandidateCooldown) -> tuple[float, float]:
    return (
        cooldown.started_mission_time
        if cooldown.started_mission_time is not None
        else -math.inf,
        cooldown.available_mission_time
        if cooldown.available_mission_time is not None
        else math.inf,
    )


def _recovery_sort_key(recovery: StrategicCoordinatorRecovery) -> tuple[str, str, str]:
    return recovery.coalition, recovery.plan_id, recovery.interrupted_attempt_id


def _execution_sort_key(payload: Mapping[str, Any]) -> tuple[float, str]:
    started = _optional_number(payload.get("started_mission_time"))
    return started if started is not None else math.inf, str(payload.get("plan_id") or "")


__all__ = [
    "STRATEGIC_COORDINATOR_AUDIT_TYPE",
    "STRATEGIC_COORDINATOR_APPROVER",
    "BilateralConflictCoordinator",
    "BilateralConflictRun",
    "CoordinatorCycleCallback",
    "CoordinatorEventCallback",
    "StrategicAttemptStatus",
    "StrategicCandidateCooldown",
    "StrategicCoalitionCycle",
    "StrategicCoordinatorAttempt",
    "StrategicCoordinatorRecovery",
    "StrategicCoordinatorConfig",
    "StrategicCycleStatus",
    "StrategicRecoveryStatus",
    "format_bilateral_conflict_run",
    "format_strategic_coalition_cycle",
    "strategic_coordinator_cycle_to_dict",
]
