"""Event-driven execution of approved operational plans through MOOSE COMMANDER."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
import inspect
import logging
from typing import TYPE_CHECKING, Any

from .auftraege import (
    Auftrag_AIRDEFENSE,
    Auftrag_AMMOSUPPLY,
    Auftrag_ANTISHIP,
    Auftrag_ARTY,
    Auftrag_BAI,
    Auftrag_BOMBING,
    Auftrag_BOMBRUNWAY,
    Auftrag_CAPTUREZONE,
    Auftrag_FUELSUPPLY,
    Auftrag_GROUNDATTACK,
    Auftrag_INTERCEPT,
    Auftrag_NAVALENGAGEMENT,
    Auftrag_PATROLZONE,
    Auftrag_RECON,
    Auftrag_REARMING,
    Auftrag_SEAD,
    AuftragCommand,
    AuftragEvent,
)
from .operational import (
    AssetRequirement,
    MissionIntent,
    OperationalPlan,
    OperationalPlanStatus,
    PlanPhase,
    PlanPhaseStatus,
    RequirementAssessment,
)
from .outcomes import AuftragOutcome
from .recon import (
    ReconOutcome,
    ReconRequirement,
    ReconTrackSample,
    ReconTrackingSession,
    build_recon_outcome,
)
from .server import DcsMissionEndedError
from .strategic import (
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalEffect,
    StrategicGoalStatus,
    StrategicObjective,
    component_health,
)

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient

LOGGER = logging.getLogger(__name__)
PLAN_EXECUTION_AUDIT_TYPE = "operational_plan.execution"
RECON_POSITION_SAMPLE_INTERVAL_S = 10.0
AUFTRAG_CANCEL_EVALUATION_GRACE_S = 2.0


class PlanMissionStatus(str, Enum):
    """Execution state of one concrete AUFTRAG created from a requirement."""

    PENDING = "pending"
    SKIPPED = "skipped"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanReconciliationStatus(str, Enum):
    """Result of comparing one interrupted attempt with current MOOSE state."""

    RUNNING = "running"
    INDETERMINATE = "indeterminate"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class PlanAbortScope(str, Enum):
    """Which live AUFTRAGs are cancelled when aborting an attempt."""

    ATTEMPT = "attempt"
    CURRENT_PHASE = "current_phase"


@dataclass(slots=True, frozen=True)
class PlanMissionAbort:
    """Result of cancelling one live MOOSE AUFTRAG."""

    auftrag_id: str
    phase_id: str
    requirement_id: str
    cancelled: bool
    message: str | None = None


@dataclass(slots=True, frozen=True)
class OperationalPlanAbortResult:
    """Result of an explicit operational-plan abort request."""

    plan_id: str
    attempt_id: str
    scope: PlanAbortScope
    status: OperationalPlanStatus
    missions: tuple[PlanMissionAbort, ...]
    message: str | None = None


@dataclass(slots=True, frozen=True)
class PlanMissionReconciliation:
    """Observed MOOSE state for one previously submitted AUFTRAG."""

    auftrag_id: str | None
    phase_id: str
    requirement_id: str
    status: PlanMissionStatus
    snapshot_found: bool
    message: str | None = None


@dataclass(slots=True, frozen=True)
class OperationalPlanReconciliation:
    """One-shot reconciliation result without automatic retasking."""

    plan_id: str
    attempt_id: str
    status: PlanReconciliationStatus
    observations: tuple[PlanMissionReconciliation, ...]
    message: str | None = None


@dataclass(slots=True, frozen=True)
class PlanExecutionEvent:
    """One local operational-plan lifecycle event."""

    event: str
    plan_id: str
    phase_id: str | None = None
    intent_id: str | None = None
    requirement_id: str | None = None
    auftrag_id: str | None = None
    status: str | None = None
    mission_time: float | None = None
    message: str | None = None
    attempt_id: str | None = None
    mission_type: str | None = None

    def __str__(self) -> str:
        """Return a compact progress line suitable for example callbacks."""

        reference = self.auftrag_id or self.requirement_id or self.phase_id or self.plan_id
        parts = [reference]
        if self.mission_type:
            parts.append(f"type={self.mission_type}")
        if self.event == "mission.status" and self.message:
            message = self.message
            prefix = f"{reference} "
            if message.startswith(prefix):
                message = message[len(prefix):]
            parts.append(message)
            return " ".join(parts)
        parts.append(self.event)
        if self.status:
            parts.append(f"status={self.status}")
        if self.message:
            parts.append(self.message)
        return " ".join(parts)


@dataclass(slots=True, frozen=True)
class CommandAckReference:
    """Compact reference from a submitted plan mission to its bridge ACK."""

    ack_id: str | None = None
    correlation_id: str | None = None
    sequence: int | None = None
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlanMissionExecution:
    """Runtime record connecting one requirement to one MOOSE AUFTRAG."""

    phase_id: str
    intent_id: str
    requirement_id: str
    mission_type: str
    required: bool
    command: AuftragCommand | None = field(default=None, repr=False)
    command_snapshot: dict[str, Any] = field(default_factory=dict)
    weapon_range_ack: CommandAckReference | None = None
    command_ack: CommandAckReference | None = None
    status: PlanMissionStatus = PlanMissionStatus.PENDING
    auftrag_id: str | None = None
    outcome: AuftragOutcome | None = None
    recon_outcome: ReconOutcome | None = None
    event_cursor: str | None = field(default=None, repr=False)
    recon_intel_id: str | None = field(default=None, repr=False)
    baseline_intel_contact_ids: tuple[str, ...] = field(default=(), repr=False)
    recon_assigned_group_ids: tuple[str, ...] = field(default=(), repr=False)
    recon_tracks: dict[str, list[ReconTrackSample]] = field(default_factory=dict, repr=False)
    error: str | None = None


@dataclass(slots=True, frozen=True)
class StrategicDamageAssessment:
    """Snapshot-derived strategic damage, independent of MOOSE AUFTRAG success."""

    phase_id: str
    objective_id: str
    required_damage: float
    health_before: float | None
    health_after: float | None
    achieved_damage: float | None
    phase_damage: float | None
    satisfied: bool
    component_health: tuple[tuple[str, float | None, str], ...] = ()
    mission_time: float | None = None


@dataclass(slots=True)
class OperationalPlanExecution:
    """Runtime state and audit trail for one execution attempt."""

    plan_id: str
    commander_id: str
    attempt_id: str = ""
    attempt_number: int = 1
    resumed_from_phase_id: str | None = None
    status: OperationalPlanStatus = OperationalPlanStatus.APPROVED
    current_phase_id: str | None = None
    started_mission_time: float | None = None
    completed_mission_time: float | None = None
    blocked_reason: str | None = None
    plan_snapshot: dict[str, Any] = field(default_factory=dict)
    goal_snapshot: dict[str, Any] = field(default_factory=dict)
    objective_snapshot: dict[str, Any] = field(default_factory=dict)
    assessment_snapshot: dict[str, Any] = field(default_factory=dict)
    missions: list[PlanMissionExecution] = field(default_factory=list)
    damage_assessments: list[StrategicDamageAssessment] = field(default_factory=list)
    events: list[PlanExecutionEvent] = field(default_factory=list)
    plan_ref: OperationalPlan | None = field(default=None, repr=False, compare=False)

PlanExecutionCallback = Callable[[PlanExecutionEvent], Any | Awaitable[Any]]


class OperationalPlanExecutor:
    """Execute approved capture plans phase by phase without status polling."""

    def __init__(self, client: MooseBridgeClient) -> None:
        self.client = client
        self._executions: dict[str, list[OperationalPlanExecution]] = {}
        self._loaded_plan_ids: set[str] = set()

    def get(self, plan_id: str) -> OperationalPlanExecution | None:
        history = self._executions.get(plan_id, ())
        return history[-1] if history else None

    def history(self, plan_id: str) -> tuple[OperationalPlanExecution, ...]:
        """Return all execution attempts for a plan in chronological order."""

        return tuple(self._executions.get(plan_id, ()))

    def clear(self) -> None:
        """Discard mission-scoped in-memory executions without touching the audit."""

        self._executions.clear()
        self._loaded_plan_ids.clear()

    async def refresh_history(self, plan_id: str) -> tuple[OperationalPlanExecution, ...]:
        """Load the latest persistent snapshot of every attempt from the daemon."""

        query = getattr(self.client.server, "query_audit_records", None)
        if query is None:
            self._loaded_plan_ids.add(plan_id)
            return self.history(plan_id)
        records = await query(
            record_type=PLAN_EXECUTION_AUDIT_TYPE,
            plan_id=plan_id,
            latest_attempts=True,
        )
        restored: list[OperationalPlanExecution] = []
        from .operational_audit import execution_from_dict

        for record in records:
            payload = record.get("payload") if isinstance(record, dict) else None
            if isinstance(payload, dict):
                try:
                    restored.append(execution_from_dict(payload))
                except (TypeError, ValueError) as exc:
                    LOGGER.warning("Ignoring invalid operational audit payload for %s: %s", plan_id, exc)
        local = {execution.attempt_id: execution for execution in self._executions.get(plan_id, ())}
        merged = {execution.attempt_id: execution for execution in restored}
        merged.update(local)
        self._executions[plan_id] = sorted(merged.values(), key=lambda execution: execution.attempt_number)
        self._loaded_plan_ids.add(plan_id)
        return self.history(plan_id)

    async def reconcile(
        self,
        plan: OperationalPlan,
        *,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanReconciliation:
        """Reconcile an interrupted execution from one current AUFTRAG snapshot."""

        if plan.plan_id not in self._loaded_plan_ids:
            await self.refresh_history(plan.plan_id)
        execution = self.get(plan.plan_id)
        if plan.status is not OperationalPlanStatus.EXECUTING or execution is None:
            raise ValueError("only a restored executing operational plan can be reconciled")
        if execution.status is not OperationalPlanStatus.EXECUTING:
            raise ValueError("latest operational plan attempt is not executing")

        await self.client.snapshot_auftraege()
        observations: list[PlanMissionReconciliation] = []
        required = [mission for mission in execution.missions if mission.required]
        for mission in required:
            previous = mission.status
            snapshot = self.client.state.auftraege.get(mission.auftrag_id or "")
            message: str | None = None
            if mission.status in {
                PlanMissionStatus.SUCCEEDED,
                PlanMissionStatus.FAILED,
                PlanMissionStatus.CANCELLED,
            }:
                pass
            elif not mission.auftrag_id:
                message = "required mission has no AUFTRAG id"
            elif snapshot is None:
                message = "AUFTRAG is absent from the current MOOSE snapshot"
            elif isinstance(snapshot.get("summary"), dict):
                mission.outcome = AuftragOutcome.from_snapshot(snapshot)
                mission.status = (
                    PlanMissionStatus.SUCCEEDED if mission.outcome.success is True else PlanMissionStatus.FAILED
                )
                mission.error = None if mission.status is PlanMissionStatus.SUCCEEDED else "AUFTRAG evaluated without success"
            else:
                status = str(snapshot.get("status") or "").strip().lower()
                if status in {"cancel", "cancelled", "canceled"}:
                    mission.status = PlanMissionStatus.CANCELLED
                    mission.error = "AUFTRAG was cancelled"
                elif status in {"failed", "failure"}:
                    mission.status = PlanMissionStatus.FAILED
                    mission.error = "AUFTRAG snapshot reports failure"
                elif status in {"planned", "queued", "requested", "scheduled", "started", "executing", "done"}:
                    mission.status = PlanMissionStatus.RUNNING
                else:
                    message = "AUFTRAG snapshot has no recognized lifecycle status"

            if mission.status is not previous:
                await self._mission_event(execution, mission, "mission.reconciled", on_event, message=message)
            observations.append(
                PlanMissionReconciliation(
                    mission.auftrag_id,
                    mission.phase_id,
                    mission.requirement_id,
                    mission.status,
                    snapshot is not None,
                    message or mission.error,
                )
            )

        if not required:
            return OperationalPlanReconciliation(
                plan.plan_id,
                execution.attempt_id,
                PlanReconciliationStatus.INDETERMINATE,
                tuple(observations),
                "interrupted attempt has no required submitted missions",
            )
        failed = next(
            (mission for mission in required if mission.status in {PlanMissionStatus.FAILED, PlanMissionStatus.CANCELLED}),
            None,
        )
        if failed is not None:
            phase = self._phase(plan, failed.phase_id)
            await self._block(plan, phase, execution, failed.error or f"{failed.auftrag_id} did not succeed", on_event)
            return OperationalPlanReconciliation(
                plan.plan_id,
                execution.attempt_id,
                PlanReconciliationStatus.BLOCKED,
                tuple(observations),
                execution.blocked_reason,
            )
        if any(
            (not observation.snapshot_found or observation.auftrag_id is None)
            and observation.status not in {
                PlanMissionStatus.SUCCEEDED,
                PlanMissionStatus.FAILED,
                PlanMissionStatus.CANCELLED,
            }
            for observation in observations
        ) or any(
            observation.message == "AUFTRAG snapshot has no recognized lifecycle status"
            for observation in observations
        ):
            await self._persist(execution)
            return OperationalPlanReconciliation(
                plan.plan_id,
                execution.attempt_id,
                PlanReconciliationStatus.INDETERMINATE,
                tuple(observations),
                "one or more required AUFTRAGs could not be identified",
            )
        if any(mission.status is not PlanMissionStatus.SUCCEEDED for mission in required):
            await self._persist(execution)
            return OperationalPlanReconciliation(
                plan.plan_id,
                execution.attempt_id,
                PlanReconciliationStatus.RUNNING,
                tuple(observations),
                "one or more required AUFTRAGs are still running",
            )
        status, message = await self._finish_reconciled_phase(plan, execution, on_event)
        return OperationalPlanReconciliation(plan.plan_id, execution.attempt_id, status, tuple(observations), message)

    async def monitor_interrupted(
        self,
        plan: OperationalPlan,
        *,
        mission_timeout_s: float = 3600.0,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanReconciliation:
        """Reattach to live AUFTRAG events and stop at the next plan boundary."""

        reconciled = await self.reconcile(plan, on_event=on_event)
        if reconciled.status is not PlanReconciliationStatus.RUNNING:
            return reconciled
        execution = self.get(plan.plan_id)
        assert execution is not None
        current = self._current_execution_phase(plan, execution)
        missions = [
            mission
            for mission in execution.missions
            if mission.required
            and mission.phase_id == current.phase_id
            and mission.status in {PlanMissionStatus.SUBMITTED, PlanMissionStatus.RUNNING}
        ]
        failed = await self._wait_for_required_missions(
            execution,
            missions,
            mission_timeout_s=mission_timeout_s,
            on_event=on_event,
        )
        if failed is not None:
            await self._block(plan, current, execution, failed.error or f"{failed.auftrag_id} did not succeed", on_event)
            return OperationalPlanReconciliation(
                plan.plan_id,
                execution.attempt_id,
                PlanReconciliationStatus.BLOCKED,
                reconciled.observations,
                execution.blocked_reason,
            )
        status, message = await self._finish_reconciled_phase(plan, execution, on_event)
        return OperationalPlanReconciliation(
            plan.plan_id,
            execution.attempt_id,
            status,
            reconciled.observations,
            message,
        )

    async def block_interrupted(
        self,
        plan: OperationalPlan,
        *,
        reason: str,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanExecution:
        """Explicitly block an indeterminate interrupted attempt for replanning."""

        reason = reason.strip()
        if not reason:
            raise ValueError("blocking an interrupted plan requires a reason")
        if plan.plan_id not in self._loaded_plan_ids:
            await self.refresh_history(plan.plan_id)
        execution = self.get(plan.plan_id)
        if plan.status is not OperationalPlanStatus.EXECUTING or execution is None:
            raise ValueError("only an executing interrupted plan can be blocked")
        if execution.status is not OperationalPlanStatus.EXECUTING:
            raise ValueError("latest operational plan attempt is not executing")
        try:
            phase = self._current_execution_phase(plan, execution)
        except ValueError:
            phase = None
        return await self._block(plan, phase, execution, reason, on_event)

    async def abort(
        self,
        plan: OperationalPlan,
        *,
        scope: PlanAbortScope | str = PlanAbortScope.ATTEMPT,
        reason: str = "Operational plan aborted by operator",
        timeout: float = 10.0,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanAbortResult:
        """Cancel live MOOSE AUFTRAGs and terminate the current plan attempt."""

        scope = PlanAbortScope(scope)
        reason = reason.strip()
        if not reason:
            raise ValueError("aborting an operational plan requires a reason")
        if timeout <= 0:
            raise ValueError("abort timeout must be greater than zero")
        if plan.plan_id not in self._loaded_plan_ids:
            await self.refresh_history(plan.plan_id)
        execution = self.get(plan.plan_id)
        if execution is None or plan.status not in {
            OperationalPlanStatus.EXECUTING,
            OperationalPlanStatus.BLOCKED,
        }:
            raise ValueError("only an executing or blocked operational plan can be aborted")
        if execution.status not in {OperationalPlanStatus.EXECUTING, OperationalPlanStatus.BLOCKED}:
            raise ValueError("latest operational plan attempt cannot be aborted")

        await self.client.snapshot_auftraege()
        current_phase: PlanPhase | None = None
        if scope is PlanAbortScope.CURRENT_PHASE:
            current_phase = self._current_execution_phase(plan, execution)
        live_statuses = {"planned", "queued", "requested", "scheduled", "started", "executing", "paused"}
        active = [
            mission
            for mission in execution.missions
            if mission.auftrag_id
            and str(
                self.client.state.auftraege.get(mission.auftrag_id, {}).get("status") or ""
            ).strip().lower() in live_statuses
            and (current_phase is None or mission.phase_id == current_phase.phase_id)
        ]
        results: list[PlanMissionAbort] = []
        for mission in active:
            assert mission.auftrag_id is not None
            try:
                await self.client.cancel_mission(mission.auftrag_id, timeout=timeout)
            except Exception as exc:
                message = str(exc) or f"could not cancel {mission.auftrag_id}"
                mission.error = message
                await self._mission_event(execution, mission, "mission.cancel_failed", on_event, message=message)
                results.append(
                    PlanMissionAbort(
                        mission.auftrag_id,
                        mission.phase_id,
                        mission.requirement_id,
                        False,
                        message,
                    )
                )
            else:
                if mission.status is not PlanMissionStatus.CANCELLED:
                    mission.status = PlanMissionStatus.CANCELLED
                    mission.error = reason
                    await self._mission_event(execution, mission, "mission.cancelled", on_event, message=reason)
                results.append(
                    PlanMissionAbort(
                        mission.auftrag_id,
                        mission.phase_id,
                        mission.requirement_id,
                        True,
                        reason,
                    )
                )

        failures = [result for result in results if not result.cancelled]
        if failures:
            message = "operational plan abort incomplete: " + ", ".join(result.auftrag_id for result in failures)
            phase = current_phase
            if phase is None:
                try:
                    phase = self._current_execution_phase(plan, execution)
                except ValueError:
                    phase = None
            await self._block(plan, phase, execution, message, on_event)
            return OperationalPlanAbortResult(
                plan.plan_id,
                execution.attempt_id,
                scope,
                execution.status,
                tuple(results),
                message,
            )

        for phase in plan.phases:
            if phase.status is PlanPhaseStatus.COMPLETED:
                continue
            phase.status = (
                PlanPhaseStatus.CANCELLED
                if phase.status in {PlanPhaseStatus.ACTIVE, PlanPhaseStatus.BLOCKED}
                else PlanPhaseStatus.SKIPPED
            )
        plan.status = OperationalPlanStatus.CANCELLED
        execution.status = plan.status
        execution.current_phase_id = None
        execution.blocked_reason = None
        execution.completed_mission_time = self.client._current_mission_time()
        await self._emit(
            execution,
            PlanExecutionEvent("plan.cancelled", plan.plan_id, status=plan.status.value, message=reason),
            on_event,
        )
        return OperationalPlanAbortResult(
            plan.plan_id,
            execution.attempt_id,
            scope,
            execution.status,
            tuple(results),
            reason,
        )

    def prepare_retry(
        self,
        plan: OperationalPlan,
        *,
        resume_from: str | None = None,
        target_overrides: Mapping[tuple[str, str], str] | None = None,
        allowed_legion_overrides: Mapping[tuple[str, str, str], Iterable[str]] | None = None,
        allowed_cohort_overrides: Mapping[tuple[str, str, str], Iterable[str]] | None = None,
    ) -> OperationalPlan:
        """Return a blocked plan to draft state while preserving completed phases."""

        latest = self.get(plan.plan_id)
        if plan.status is not OperationalPlanStatus.BLOCKED or latest is None:
            raise ValueError("only a blocked plan with an execution attempt can be prepared for retry")
        if latest.status is not OperationalPlanStatus.BLOCKED:
            raise ValueError("latest operational plan execution is not blocked")

        incomplete = [index for index, phase in enumerate(plan.phases) if phase.status is not PlanPhaseStatus.COMPLETED]
        if resume_from is None:
            resume_index = incomplete[0] if incomplete else len(plan.phases)
        else:
            try:
                resume_index = next(index for index, phase in enumerate(plan.phases) if phase.phase_id == resume_from)
            except StopIteration as exc:
                raise ValueError(f"Unknown operational plan phase: {resume_from}") from exc
        unfinished_before = [phase.phase_id for phase in plan.phases[:resume_index] if phase.status is not PlanPhaseStatus.COMPLETED]
        if unfinished_before:
            raise ValueError(f"retry cannot skip incomplete phases: {unfinished_before}")

        retryable_phases = plan.phases[resume_index:]
        targets = dict(target_overrides or {})
        legion_limits = dict(allowed_legion_overrides or {})
        cohort_limits = dict(allowed_cohort_overrides or {})
        known_targets = {
            (phase.phase_id, intent.intent_id)
            for phase in retryable_phases
            for intent in phase.intents
        }
        known_requirements = {
            (phase.phase_id, intent.intent_id, requirement.requirement_id)
            for phase in retryable_phases
            for intent in phase.intents
            for requirement in intent.asset_requirements
        }
        unknown_targets = sorted(set(targets) - known_targets)
        unknown_legion_limits = sorted(set(legion_limits) - known_requirements)
        unknown_cohort_limits = sorted(set(cohort_limits) - known_requirements)
        if unknown_targets or unknown_legion_limits or unknown_cohort_limits:
            raise ValueError(
                "retry overrides reference unknown or completed plan elements: "
                f"targets={unknown_targets}, legions={unknown_legion_limits}, cohorts={unknown_cohort_limits}"
            )

        for phase in retryable_phases:
            updated_intents: list[MissionIntent] = []
            for intent in phase.intents:
                intent_key = (phase.phase_id, intent.intent_id)
                updated_requirements: list[AssetRequirement] = []
                for requirement in intent.asset_requirements:
                    requirement_key = (phase.phase_id, intent.intent_id, requirement.requirement_id)
                    changes: dict[str, Any] = {}
                    if requirement_key in legion_limits:
                        changes["allowed_legion_ids"] = _object_ids(legion_limits[requirement_key])
                    if requirement_key in cohort_limits:
                        changes["allowed_cohort_ids"] = _object_ids(cohort_limits[requirement_key])
                    updated_requirements.append(replace(requirement, **changes) if changes else requirement)
                changes = {"asset_requirements": tuple(updated_requirements)}
                if intent_key in targets:
                    changes["target_object_id"] = targets[intent_key]
                updated_intents.append(replace(intent, **changes))
            phase.intents = tuple(updated_intents)
            phase.status = PlanPhaseStatus.PENDING

        plan.status = OperationalPlanStatus.DRAFT
        plan.validated_mission_time = None
        plan.approved_mission_time = None
        plan.approved_by = None
        plan.approved_client_id = None
        plan.approval_reason = None
        plan.metadata["retry_resume_phase_id"] = (
            plan.phases[resume_index].phase_id if resume_index < len(plan.phases) else None
        )
        self.client.plans.invalidate(plan)
        latest.events.append(
            PlanExecutionEvent(
                "plan.retry_prepared",
                plan.plan_id,
                phase_id=plan.metadata["retry_resume_phase_id"],
                status=plan.status.value,
                mission_time=self.client._current_mission_time(),
                attempt_id=latest.attempt_id,
            )
        )
        return plan

    async def execute(
        self,
        plan: OperationalPlan,
        *,
        commander_id: str | None = None,
        mission_timeout_s: float = 3600.0,
        on_event: PlanExecutionCallback | None = None,
    ) -> OperationalPlanExecution:
        """Execute an approved operational plan and return its runtime record."""

        if plan.status is not OperationalPlanStatus.APPROVED:
            raise ValueError("only an approved operational plan can be executed")
        goal = self.client.strategic_goal(plan.goal_id)
        if goal is None:
            raise ValueError(f"Unknown strategic goal: {plan.goal_id}")
        if goal.action not in {
            StrategicGoalAction.CAPTURE,
            StrategicGoalAction.DEFEND,
            StrategicGoalAction.DESTROY,
            StrategicGoalAction.DISABLE,
        }:
            raise ValueError("operational execution currently supports CAPTURE, DEFEND, DESTROY, and DISABLE goals")
        if goal.action is StrategicGoalAction.DISABLE and goal.effect is not StrategicGoalEffect.DENY_RUNWAY:
            raise ValueError("operational execution currently supports only deny_runway DISABLE goals")
        assessment = self.client.plans.assessment(plan.plan_id)
        if assessment is None or not assessment.feasible:
            raise ValueError("operational plan requires a current feasible assessment")
        if plan.plan_id not in self._loaded_plan_ids:
            await self.refresh_history(plan.plan_id)
        latest = self.get(plan.plan_id)
        if latest and latest.status is OperationalPlanStatus.EXECUTING:
            raise ValueError(
                f"operational plan has an interrupted executing attempt: {plan.plan_id}; "
                "reconcile or explicitly block/abort that attempt before reuse, or create a new plan id"
            )
        if goal.status in {StrategicGoalStatus.FAILED, StrategicGoalStatus.CANCELLED}:
            raise ValueError(f"strategic goal cannot be executed in state {goal.status.value}")

        commander = self.client.commander(commander_id) if commander_id else self.client.commander_for_coalition(plan.coalition)
        if commander is None:
            raise ValueError(f"Unknown COMMANDER: {commander_id}")
        if (commander.coalition or "").lower() != plan.coalition:
            raise ValueError("COMMANDER coalition must match the operational plan")

        history = self._executions.setdefault(plan.plan_id, [])
        if latest is not None:
            await self._persist(latest)
        attempt_number = len(history) + 1
        from .operational_audit import assessment_snapshot, plan_snapshot

        execution = OperationalPlanExecution(
            plan_id=plan.plan_id,
            commander_id=commander.object_id,
            attempt_id=f"{plan.plan_id}/ATTEMPT:{attempt_number}",
            attempt_number=attempt_number,
            resumed_from_phase_id=plan.metadata.pop("retry_resume_phase_id", None),
            status=OperationalPlanStatus.EXECUTING,
            started_mission_time=self.client._current_mission_time(),
            plan_snapshot=plan_snapshot(plan),
            assessment_snapshot=assessment_snapshot(assessment),
            plan_ref=plan,
        )
        history.append(execution)
        plan.status = OperationalPlanStatus.EXECUTING
        if goal.status is StrategicGoalStatus.PLANNED:
            self.client.activate_strategic_goal(goal)
        await self._emit(execution, PlanExecutionEvent("plan.started", plan.plan_id, status=plan.status.value), on_event)

        for phase in plan.phases:
            if phase.status is PlanPhaseStatus.COMPLETED:
                continue
            if any(self._phase(plan, dependency).status is not PlanPhaseStatus.COMPLETED for dependency in phase.depends_on):
                return await self._block(plan, phase, execution, "phase dependency is not completed", on_event)
            execution.current_phase_id = phase.phase_id
            await self._emit(
                execution,
                PlanExecutionEvent("phase.revalidating", plan.plan_id, phase_id=phase.phase_id, status=phase.status.value),
                on_event,
            )
            try:
                await self.client.snapshot_commanders()
                await self.client.snapshot_legions()
                await self.client.snapshot_cohorts()
                await self._refresh_goal_control(goal.objective_id)
                self.client.sync_strategic_objectives(source="plan.phase_revalidation")
                self.client.sync_strategic_goals(source="plan.phase_revalidation")

                if goal.status is StrategicGoalStatus.ACHIEVED and not any(
                    item.status is PlanPhaseStatus.COMPLETED for item in plan.phases
                ):
                    for remaining_phase in plan.phases:
                        if remaining_phase.status is PlanPhaseStatus.COMPLETED:
                            continue
                        remaining_phase.status = PlanPhaseStatus.SKIPPED
                        await self._emit(
                            execution,
                            PlanExecutionEvent(
                                "phase.skipped",
                                plan.plan_id,
                                phase_id=remaining_phase.phase_id,
                                status=remaining_phase.status.value,
                                message="strategic goal already achieved",
                            ),
                            on_event,
                        )
                    plan.status = OperationalPlanStatus.COMPLETED
                    execution.status = plan.status
                    execution.current_phase_id = None
                    execution.completed_mission_time = self.client._current_mission_time()
                    await self._emit(
                        execution,
                        PlanExecutionEvent(
                            "plan.completed",
                            plan.plan_id,
                            status=plan.status.value,
                            message="strategic goal already achieved during phase revalidation",
                        ),
                        on_event,
                    )
                    return execution
                if goal.status in {StrategicGoalStatus.FAILED, StrategicGoalStatus.CANCELLED}:
                    raise ValueError(f"strategic goal changed to {goal.status.value}")

                refreshed_commander = self.client.commander(commander.object_id)
                if refreshed_commander is None:
                    raise ValueError(f"COMMANDER is no longer available: {commander.object_id}")
                commander = refreshed_commander
                if (commander.coalition or "").lower() != plan.coalition:
                    raise ValueError("COMMANDER coalition no longer matches the operational plan")

                phase_assessment = self.client.plans.assess_phase(
                    plan,
                    phase.phase_id,
                    legions=self.client.state.legion_objects.values(),
                    cohorts=self.client.state.cohort_objects.values(),
                    mission_time=self.client._current_mission_time(),
                )
                execution.assessment_snapshot = assessment_snapshot(phase_assessment)
                if not phase_assessment.feasible:
                    details = "; ".join(
                        f"{issue.code} {issue.reference_id or '-'}: {issue.message}"
                        for issue in phase_assessment.errors
                    )
                    raise ValueError(details or "phase is no longer feasible")

                assessments = {
                    (item.phase_id, item.intent_id, item.requirement_id): item
                    for item in phase_assessment.requirements
                }
                prepared: dict[tuple[str, str, str], AuftragCommand] = {}
                commander_legions = set(commander.legion_ids)
                for intent in phase.intents:
                    for requirement in intent.asset_requirements:
                        key = (phase.phase_id, intent.intent_id, requirement.requirement_id)
                        item = assessments[key]
                        if not item.feasible and not (intent.required and not phase.optional):
                            continue
                        invalid_legions = set(requirement.allowed_legion_ids) - commander_legions
                        if invalid_legions:
                            raise ValueError(
                                f"{requirement.requirement_id} constrains LEGIONs outside {commander.object_id}: "
                                f"{sorted(invalid_legions)}"
                            )
                        invalid_cohorts = [
                            cohort_id
                            for cohort_id in requirement.allowed_cohort_ids
                            if not (cohort := self.client.cohort(cohort_id))
                            or cohort.legion_id not in commander_legions
                        ]
                        if invalid_cohorts:
                            raise ValueError(
                                f"{requirement.requirement_id} constrains COHORTs outside {commander.object_id}: "
                                f"{sorted(invalid_cohorts)}"
                            )
                        prepared[key] = build_plan_auftrag(plan, intent, requirement)
                await self._preflight_targets(prepared.values())
            except Exception as exc:
                return await self._block(plan, phase, execution, f"phase revalidation failed: {exc}", on_event)

            await self._emit(
                execution,
                PlanExecutionEvent(
                    "phase.revalidated",
                    plan.plan_id,
                    phase_id=phase.phase_id,
                    status="feasible",
                ),
                on_event,
            )
            phase.status = PlanPhaseStatus.ACTIVE
            destroy_health_before = None
            if goal.action is StrategicGoalAction.DESTROY:
                objective = self.client.strategic_objective(goal.objective_id)
                destroy_health_before = objective.health if objective is not None else None
            await self._emit(
                execution,
                PlanExecutionEvent("phase.started", plan.plan_id, phase_id=phase.phase_id, status=phase.status.value),
                on_event,
            )

            required_missions: list[PlanMissionExecution] = []
            for intent in phase.intents:
                for requirement in intent.asset_requirements:
                    key = (phase.phase_id, intent.intent_id, requirement.requirement_id)
                    requirement_assessment = assessments[key]
                    required = intent.required and not phase.optional
                    command = prepared.get(key)
                    if command is None:
                        skipped = PlanMissionExecution(
                            phase.phase_id,
                            intent.intent_id,
                            requirement.requirement_id,
                            _mission_type(intent, requirement),
                            required,
                            None,
                            status=PlanMissionStatus.SKIPPED,
                            error=f"optional asset shortfall {requirement_assessment.shortfall}",
                        )
                        execution.missions.append(skipped)
                        await self._mission_event(execution, skipped, "mission.skipped", on_event)
                        continue

                    mission = PlanMissionExecution(
                        phase.phase_id,
                        intent.intent_id,
                        requirement.requirement_id,
                        command.mission_type,
                        required,
                        command,
                    )
                    execution.missions.append(mission)
                    try:
                        recon_requirement_data = self._recon_requirement_data(phase, intent)
                        if command.mission_type == "RECON" and recon_requirement_data is not None:
                            mission.recon_intel_id = str(phase.metadata.get("intel_id") or "") or None
                            if mission.recon_intel_id is None:
                                raise ValueError("structured RECON phase requires metadata.intel_id")
                            mission.event_cursor = await self.client.server.event_cursor()
                            await self.client.refresh_intel_state()
                            mission.baseline_intel_contact_ids = tuple(
                                contact.object_id
                                for contact in self.client.contacts_of_intel(mission.recon_intel_id)
                            )
                        range_ack = await self._synchronize_arty_weapon_range(intent, requirement, command)
                        if range_ack is not None:
                            mission.weapon_range_ack = _command_ack_reference(range_ack)
                            result = range_ack.get("result") if isinstance(range_ack.get("result"), dict) else {}
                            await self._emit(
                                execution,
                                PlanExecutionEvent(
                                    "mission.weapon_range_synchronized",
                                    plan.plan_id,
                                    phase_id=phase.phase_id,
                                    intent_id=intent.intent_id,
                                    requirement_id=requirement.requirement_id,
                                    status="synchronized",
                                    message=(
                                        f"{result.get('cohort_id') or '-'} "
                                        f"weapon_type={result.get('weapon_type')} "
                                        f"range={float(result.get('minimum_m') or 0.0) / 1_000:.3f}-"
                                        f"{float(result.get('maximum_m') or 0.0) / 1_000:.3f}km"
                                    ),
                                ),
                                on_event,
                            )
                        ack = await self.client.add_auftrag(
                            command,
                            commander=commander.object_id,
                            allowed_legions=requirement.allowed_legion_ids,
                            allowed_cohorts=requirement.allowed_cohort_ids,
                        )
                        mission.command_ack = _command_ack_reference(ack)
                        mission.auftrag_id = self.client.mission_id(command)
                        mission.status = PlanMissionStatus.SUBMITTED
                        await self._mission_event(execution, mission, "mission.submitted", on_event)
                    except Exception as exc:
                        mission.status = PlanMissionStatus.FAILED
                        mission.error = str(exc)
                        await self._mission_event(execution, mission, "mission.failed", on_event)
                        if required:
                            return await self._block(plan, phase, execution, mission.error, on_event)
                        continue
                    if required:
                        required_missions.append(mission)

            defend_status: StrategicGoalStatus | None = None
            try:
                if goal.action is StrategicGoalAction.DEFEND:
                    defend_status, failed = await self._wait_for_defend_phase(
                        goal,
                        execution,
                        required_missions,
                        mission_timeout_s=mission_timeout_s,
                        on_event=on_event,
                    )
                else:
                    failed = await self._wait_for_required_missions(
                        execution,
                        required_missions,
                        mission_timeout_s=mission_timeout_s,
                        on_event=on_event,
                        stop_on_failure=goal.action is not StrategicGoalAction.DESTROY,
                    )
            except Exception as exc:
                return await self._block(
                    plan,
                    phase,
                    execution,
                    f"strategic goal monitoring failed: {exc}",
                    on_event,
                )
            if goal.action is StrategicGoalAction.DESTROY:
                self._record_destroy_auftrag_damage(goal, required_missions)
                await self._refresh_goal_control(goal.objective_id)
                self.client.sync_strategic_objectives(source="plan.destroy_phase")
                self.client.sync_strategic_goals(source="plan.destroy_phase")
                await self._record_destroy_assessment(
                    execution,
                    phase.phase_id,
                    goal,
                    health_before=destroy_health_before,
                    callback=on_event,
                )
            if failed is not None and goal.status is not StrategicGoalStatus.ACHIEVED:
                reason = (
                    self._destroy_shortfall_reason(goal)
                    if goal.action is StrategicGoalAction.DESTROY
                    else failed.error or f"{failed.auftrag_id} did not succeed"
                )
                return await self._block(
                    plan,
                    phase,
                    execution,
                    reason,
                    on_event,
                )

            if goal.action is StrategicGoalAction.DISABLE:
                effect_error = await self._confirm_disable_effect(
                    goal,
                    plan,
                    phase.phase_id,
                    required_missions,
                    execution,
                    on_event,
                )
                if effect_error is not None:
                    return await self._block(
                        plan,
                        phase,
                    execution,
                    effect_error,
                    on_event,
                    )

            if defend_status in {StrategicGoalStatus.ACHIEVED, StrategicGoalStatus.FAILED, StrategicGoalStatus.CANCELLED}:
                cleanup_reason = (
                    "strategic DEFEND goal achieved"
                    if defend_status is StrategicGoalStatus.ACHIEVED
                    else f"strategic DEFEND goal {defend_status.value}"
                )
                await self._cancel_plan_missions(execution, cleanup_reason, on_event)
                if defend_status is not StrategicGoalStatus.ACHIEVED:
                    return await self._block(plan, phase, execution, cleanup_reason, on_event)

                phase.status = PlanPhaseStatus.COMPLETED
                await self._emit(
                    execution,
                    PlanExecutionEvent(
                        "phase.completed",
                        plan.plan_id,
                        phase_id=phase.phase_id,
                        status=phase.status.value,
                        message="defense objective held until its deadline",
                    ),
                    on_event,
                )
                for remaining_phase in plan.phases:
                    if remaining_phase.status is PlanPhaseStatus.PENDING:
                        remaining_phase.status = PlanPhaseStatus.SKIPPED
                        await self._emit(
                            execution,
                            PlanExecutionEvent(
                                "phase.skipped",
                                plan.plan_id,
                                phase_id=remaining_phase.phase_id,
                                status=remaining_phase.status.value,
                                message="strategic DEFEND goal already achieved",
                            ),
                            on_event,
                        )
                plan.status = OperationalPlanStatus.COMPLETED
                execution.status = plan.status
                execution.current_phase_id = None
                execution.completed_mission_time = self.client._current_mission_time()
                await self._emit(
                    execution,
                    PlanExecutionEvent("plan.completed", plan.plan_id, status=plan.status.value),
                    on_event,
                )
                return execution

            phase.status = PlanPhaseStatus.COMPLETED
            await self._emit(
                execution,
                PlanExecutionEvent("phase.completed", plan.plan_id, phase_id=phase.phase_id, status=phase.status.value),
                on_event,
            )
            try:
                recon_outcomes = await self._assess_recon_phase(plan, phase, execution, on_event)
            except Exception as exc:
                reason = f"RECON assessment failed: {exc}"
                await self._emit(
                    execution,
                    PlanExecutionEvent(
                        "recon.assessment_failed",
                        plan.plan_id,
                        phase_id=phase.phase_id,
                        status="failed",
                        message=reason,
                    ),
                    on_event,
                )
                next_phase = next(
                    (item for item in plan.phases if item.status is not PlanPhaseStatus.COMPLETED),
                    None,
                )
                return await self._block(plan, next_phase, execution, reason, on_event)
            if phase.metadata.get("requires_tactical_replanning"):
                await self.client.refresh_intel_state()
                next_phase = next(
                    (item for item in plan.phases if item.status is not PlanPhaseStatus.COMPLETED),
                    None,
                )
                reason = self._replanning_reason(recon_outcomes)
                await self._emit(
                    execution,
                    PlanExecutionEvent(
                        "plan.replanning_required",
                        plan.plan_id,
                        phase_id=phase.phase_id,
                        status="review_required",
                        message=reason,
                    ),
                    on_event,
                )
                return await self._block(plan, next_phase, execution, reason, on_event)

        await self._refresh_goal_control(goal.objective_id)
        self.client.sync_strategic_objectives(source="plan.execution")
        self.client.sync_strategic_goals(source="plan.execution")
        if goal.status is not StrategicGoalStatus.ACHIEVED:
            return await self._block(plan, None, execution, "missions completed but the strategic goal is not achieved", on_event)

        plan.status = OperationalPlanStatus.COMPLETED
        execution.status = plan.status
        execution.current_phase_id = None
        execution.completed_mission_time = self.client._current_mission_time()
        await self._emit(execution, PlanExecutionEvent("plan.completed", plan.plan_id, status=plan.status.value), on_event)
        return execution

    async def _synchronize_arty_weapon_range(
        self,
        intent: MissionIntent,
        requirement: AssetRequirement,
        command: AuftragCommand,
    ) -> dict[str, Any] | None:
        """Apply the resolver's exact weapon envelope before MOOSE recruits assets."""

        if command.mission_type != "ARTY":
            return None
        support = intent.metadata.get("fire_support")
        if not isinstance(support, dict) or not support.get("range_sync_required"):
            return None

        cohort_id = str(support.get("cohort_id") or "").strip()
        if not cohort_id:
            raise ValueError("ARTY weapon range synchronization requires fire_support.cohort_id")
        if requirement.allowed_cohort_ids and cohort_id not in requirement.allowed_cohort_ids:
            raise ValueError(f"ARTY weapon range COHORT is not allowed by the requirement: {cohort_id}")

        weapon_type = int(support.get("weapon_flag_value"))
        minimum_m = float(support.get("minimum_m"))
        maximum_m = float(support.get("maximum_m"))
        cohort = self.client.cohort(cohort_id)
        configured = cohort.weapon_range_for_weapon_type(weapon_type) if cohort is not None else None
        if configured is not None:
            configured_minimum, configured_maximum = configured
            if abs(configured_minimum - minimum_m) <= 1.0 and abs(configured_maximum - maximum_m) <= 1.0:
                return None
        return await self.client.set_cohort_weapon_range(
            cohort_id,
            weapon_type,
            minimum_m,
            maximum_m,
        )

    @staticmethod
    def _recon_requirement_data(phase: PlanPhase, intent: MissionIntent) -> dict[str, Any] | None:
        value = intent.metadata.get("reconnaissance_requirement")
        if not isinstance(value, dict):
            value = phase.metadata.get("reconnaissance_requirement")
        return value if isinstance(value, dict) else None

    async def _assess_recon_phase(
        self,
        plan: OperationalPlan,
        phase: PlanPhase,
        execution: OperationalPlanExecution,
        on_event: PlanExecutionCallback | None,
    ) -> tuple[ReconOutcome, ...]:
        """Build and persist tactical outcomes for structured RECON missions."""

        results: list[ReconOutcome] = []
        phase_missions = [
            mission
            for mission in execution.missions
            if mission.phase_id == phase.phase_id
            and mission.mission_type == "RECON"
            and mission.status is PlanMissionStatus.SUCCEEDED
        ]
        for mission in phase_missions:
            intent = next((item for item in phase.intents if item.intent_id == mission.intent_id), None)
            requirement_data = self._recon_requirement_data(phase, intent) if intent else None
            if requirement_data is None or mission.recon_intel_id is None:
                continue
            requirement = ReconRequirement.from_dict(requirement_data)
            history = await self.client.server.query_events("*", after_id=mission.event_cursor)
            events = history.get("events") if isinstance(history.get("events"), list) else []
            await self.client.snapshot_auftraege()
            await self.client.snapshot_opsgroups()
            await self.client.snapshot_zones()
            await self.client.snapshot_opszones()
            await self.client.snapshot_statics()
            await self.client.snapshot_airbases()
            snapshot = self.client.auftrag(mission.auftrag_id or "")
            assigned_opsgroup_ids = tuple(snapshot.assigned_group_ids) if snapshot else ()
            assigned_group_ids: list[str] = []
            for opsgroup_id in assigned_opsgroup_ids:
                opsgroup = self.client.opsgroup(opsgroup_id)
                group_name = opsgroup.group_name if opsgroup and opsgroup.group_name else opsgroup_id.removeprefix("OPSGROUP:")
                assigned_group_ids.append(f"GROUP:{group_name}")
            assert mission.outcome is not None
            tracking = ReconTrackingSession(
                mission.auftrag_id or "",
                assigned_opsgroup_ids,
                tuple(assigned_group_ids),
                mission.recon_tracks,
            )
            spatial_coverage = await self.client.assess_recon_tracking(requirement, tracking)
            mission.recon_outcome = build_recon_outcome(
                auftrag_id=mission.auftrag_id or "",
                intel_id=mission.recon_intel_id,
                mission_outcome=mission.outcome,
                events=(event for event in events if isinstance(event, dict)),
                baseline_contact_ids=mission.baseline_intel_contact_ids,
                assigned_opsgroup_ids=assigned_opsgroup_ids,
                assigned_group_ids=assigned_group_ids,
                requirement=requirement,
                spatial_coverage=spatial_coverage,
                event_history_complete=bool(history.get("history_complete")),
            )
            results.append(mission.recon_outcome)
            status = (
                "satisfied"
                if mission.recon_outcome.requirement_satisfied is True
                else "incomplete"
                if mission.recon_outcome.requirement_satisfied is False
                else "indeterminate"
            )
            message = (
                f"contacts={len(mission.recon_outcome.observations)} "
                f"unknown={len(mission.recon_outcome.unknown_relevant_target_ids)} "
                f"lost={len(mission.recon_outcome.lost_relevant_target_ids)}"
            )
            await self._mission_event(execution, mission, "recon.assessed", on_event, message=message, status=status)
        return tuple(results)

    @staticmethod
    def _replanning_reason(outcomes: tuple[ReconOutcome, ...]) -> str:
        if not outcomes:
            return "reconnaissance completed; refresh the tactical picture and replan from current INTEL contacts"
        if any(outcome.requirement_satisfied is False for outcome in outcomes):
            return "reconnaissance incomplete; relevant targets remain unknown or lost, refresh INTEL and replan"
        if any(outcome.requirement_satisfied is None for outcome in outcomes):
            return "reconnaissance completed but target coverage is indeterminate; refresh INTEL and replan"
        return "reconnaissance requirement satisfied; refresh INTEL and replan before continuing"

    async def _sample_recon_positions(self, mission: PlanMissionExecution) -> None:
        """Sample assigned RECON groups when no movement event exists in DCS."""

        session = ReconTrackingSession(
            mission.auftrag_id or "",
            assigned_group_ids=mission.recon_assigned_group_ids,
            tracks=mission.recon_tracks,
        )
        await self.client.sample_recon_tracking(session)
        mission.recon_assigned_group_ids = session.assigned_group_ids

    async def _wait_for_required_missions(
        self,
        execution: OperationalPlanExecution,
        missions: list[PlanMissionExecution],
        *,
        mission_timeout_s: float,
        on_event: PlanExecutionCallback | None,
        stop_on_failure: bool = True,
    ) -> PlanMissionExecution | None:
        failed: PlanMissionExecution | None = None
        tasks = {
            asyncio.create_task(self._wait_for_mission(execution, mission, mission_timeout_s, on_event)): mission
            for mission in missions
        }
        try:
            while tasks:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    mission = tasks.pop(task)
                    try:
                        succeeded = task.result()
                    except Exception as exc:
                        mission.status = PlanMissionStatus.FAILED
                        mission.error = str(exc) or f"event wait failed for {mission.auftrag_id}"
                        await self._mission_event(execution, mission, "mission.failed", on_event)
                        succeeded = False
                    if not succeeded:
                        if stop_on_failure:
                            return mission
                        failed = mission
            return failed
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def _destroy_shortfall_reason(self, goal: StrategicGoal) -> str:
        objective = self.client.strategic_objective(goal.objective_id)
        health = objective.health if objective is not None else None
        required = goal.required_damage
        if health is None or required is None:
            return "weighted destruction goal is not achieved after all strike missions completed"
        achieved = max(0.0, min(1.0, 1.0 - health))
        return f"weighted destruction not achieved: damage={achieved:.1%} required={required:.1%}"

    async def _record_destroy_assessment(
        self,
        execution: OperationalPlanExecution,
        phase_id: str,
        goal: StrategicGoal,
        *,
        health_before: float | None,
        callback: PlanExecutionCallback | None,
    ) -> StrategicDamageAssessment:
        objective = self.client.strategic_objective(goal.objective_id)
        health_after = objective.health if objective is not None else None
        achieved_damage = None if health_after is None else max(0.0, min(1.0, 1.0 - health_after))
        phase_damage = (
            None
            if health_before is None or health_after is None
            else max(0.0, min(1.0, health_before - health_after))
        )
        required_damage = goal.required_damage or 0.0
        assessment = StrategicDamageAssessment(
            phase_id=phase_id,
            objective_id=goal.objective_id,
            required_damage=required_damage,
            health_before=health_before,
            health_after=health_after,
            achieved_damage=achieved_damage,
            phase_damage=phase_damage,
            satisfied=goal.status is StrategicGoalStatus.ACHIEVED,
            component_health=tuple(
                self._component_health_evidence(objective, component.object_id)
                for component in (objective.components if objective is not None else ())
                if component.contributes_to_health and component.weight > 0
            ),
            mission_time=self.client._current_mission_time(),
        )
        execution.damage_assessments.append(assessment)
        damage = f"{achieved_damage:.1%}" if achieved_damage is not None else "unknown"
        phase_damage_text = f"{phase_damage:.1%}" if phase_damage is not None else "unknown"
        await self._emit(
            execution,
            PlanExecutionEvent(
                "strategic.damage_assessed",
                execution.plan_id,
                phase_id=phase_id,
                status="satisfied" if assessment.satisfied else "shortfall",
                message=(
                    f"objective={goal.objective_id} damage={damage} "
                    f"required={required_damage:.1%} phase_damage={phase_damage_text}"
                ),
            ),
            callback,
        )
        return assessment

    def _record_destroy_auftrag_damage(
        self,
        goal: StrategicGoal,
        missions: Iterable[PlanMissionExecution],
    ) -> None:
        objective = self.client.strategic_objective(goal.objective_id)
        if objective is None:
            return
        component_ids = {component.object_id for component in objective.components}
        for mission in missions:
            if mission.mission_type in {"ARTY", "BOMBING", "BOMBCARPET", "STRIKE"}:
                continue
            if mission.outcome is None or mission.outcome.damage is None:
                continue
            params = mission.command.to_params() if mission.command is not None else {}
            target = params.get("target")
            if not isinstance(target, str) or target not in component_ids:
                continue
            damage = max(0.0, min(100.0, mission.outcome.damage))
            self.client.objectives.record_component_health(
                objective,
                target,
                1.0 - damage / 100.0,
                source=f"auftrag_summary:{mission.auftrag_id or 'unknown'}",
                mission_time=self.client._current_mission_time(),
            )

    def _component_health_evidence(
        self,
        objective: StrategicObjective,
        component_id: str,
    ) -> tuple[str, float | None, str]:
        snapshot_health = component_health(component_id, self.client.state)
        estimate = objective.component_health_estimates.get(component_id)
        if estimate is None:
            return component_id, snapshot_health, "snapshot"
        if snapshot_health is None or estimate.health < snapshot_health:
            return component_id, estimate.health, estimate.source
        if estimate.health == snapshot_health:
            return component_id, snapshot_health, f"snapshot+{estimate.source}"
        return component_id, snapshot_health, "snapshot"

    async def _wait_for_defend_phase(
        self,
        goal: StrategicGoal,
        execution: OperationalPlanExecution,
        missions: list[PlanMissionExecution],
        *,
        mission_timeout_s: float,
        on_event: PlanExecutionCallback | None,
    ) -> tuple[StrategicGoalStatus, PlanMissionExecution | None]:
        """Wait for required missions or a terminal deadline-based DEFEND goal."""

        goal_task = asyncio.create_task(self._wait_for_defend_goal(goal, mission_timeout_s))
        mission_task = asyncio.create_task(
            self._wait_for_required_missions(
                execution,
                missions,
                mission_timeout_s=mission_timeout_s,
                on_event=on_event,
            )
        )
        try:
            done, _ = await asyncio.wait({goal_task, mission_task}, return_when=asyncio.FIRST_COMPLETED)
            if goal_task in done:
                return goal_task.result(), None
            failed = mission_task.result()
            if failed is not None:
                return goal.status, failed
            return await goal_task, None
        finally:
            for task in (goal_task, mission_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(goal_task, mission_task, return_exceptions=True)

    async def _wait_for_defend_goal(self, goal: StrategicGoal, timeout_s: float) -> StrategicGoalStatus:
        """Consume bridge events until a DEFEND goal reaches its deadline or fails."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        after_id = await self.client.server.event_cursor()
        deadline_refreshed = False
        while goal.status is StrategicGoalStatus.ACTIVE:
            mission_time = self.client._current_mission_time()
            if (
                not deadline_refreshed
                and goal.deadline_mission_time is not None
                and mission_time is not None
                and mission_time >= goal.deadline_mission_time
            ):
                await self._refresh_goal_control(goal.objective_id)
                deadline_refreshed = True
            self.client.sync_strategic_objectives(source="plan.defend")
            self.client.sync_strategic_goals(source="plan.defend")
            if goal.status is not StrategicGoalStatus.ACTIVE:
                break

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for strategic DEFEND goal {goal.goal_id}")
            message = await self.client.server.wait_for_event("*", timeout=remaining, after_id=after_id)
            after_id = str(message.get("id") or "") or after_id
            self.client.state.apply_message(message)
            self.client._on_bridge_message(message)
            if str(message.get("event") or "") == "mission.ended":
                raise DcsMissionEndedError("DCS mission ended while monitoring DEFEND goal")
        return goal.status

    async def _cancel_plan_missions(
        self,
        execution: OperationalPlanExecution,
        reason: str,
        on_event: PlanExecutionCallback | None,
    ) -> None:
        """Best-effort cleanup for missions still active when a DEFEND goal ends."""

        for mission in execution.missions:
            if not mission.auftrag_id or mission.status not in {
                PlanMissionStatus.SUBMITTED,
                PlanMissionStatus.RUNNING,
            }:
                continue
            try:
                await self.client.cancel_mission(mission.auftrag_id)
            except Exception as exc:
                message = str(exc) or f"could not cancel {mission.auftrag_id}"
                mission.error = message
                await self._mission_event(execution, mission, "mission.cancel_failed", on_event, message=message)
                continue
            mission.status = PlanMissionStatus.CANCELLED
            mission.error = reason
            await self._mission_event(execution, mission, "mission.cancelled", on_event, message=reason)

    async def _wait_for_mission(
        self,
        execution: OperationalPlanExecution,
        mission: PlanMissionExecution,
        timeout_s: float,
        on_event: PlanExecutionCallback | None,
    ) -> bool:
        assert mission.auftrag_id is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        after_id: str | None = mission.event_cursor
        cancel_evaluation_deadline: float | None = None
        seen_status_keys: set[tuple[str | None, str | None, str | None, str | None]] = set()
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                mission.status = PlanMissionStatus.FAILED
                mission.error = f"timed out waiting for {mission.auftrag_id}"
                await self._mission_event(execution, mission, "mission.failed", on_event)
                return False
            wait_timeout = min(remaining, RECON_POSITION_SAMPLE_INTERVAL_S) if mission.recon_intel_id else remaining
            if cancel_evaluation_deadline is not None:
                wait_timeout = min(wait_timeout, max(0.0, cancel_evaluation_deadline - loop.time()))
            try:
                message = await self.client.server.wait_for_event(
                    "auftrag.*",
                    filters={"auftrag_id": mission.auftrag_id},
                    timeout=wait_timeout,
                    after_id=after_id,
                )
            except TimeoutError:
                if cancel_evaluation_deadline is not None:
                    mission.status = PlanMissionStatus.CANCELLED
                    mission.error = "AUFTRAG was cancelled"
                    await self._mission_event(execution, mission, "mission.cancelled", on_event)
                    return False
                if mission.recon_intel_id:
                    await self._sample_recon_positions(mission)
                    continue
                raise
            after_id = str(message.get("id") or "") or after_id
            self.client.state.apply_message(message)
            self.client._on_bridge_message(message)
            if str(message.get("event") or "") == "mission.ended":
                raise DcsMissionEndedError("DCS mission ended while executing operational plan")
            if mission.recon_intel_id:
                await self._sample_recon_positions(mission)
            event = AuftragEvent.from_message(message)
            if event.event == "auftrag.evaluated":
                payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
                snapshot = {
                    "object_id": mission.auftrag_id,
                    "type": payload.get("auftrag_type") or mission.mission_type,
                    "status": payload.get("status"),
                    "summary": payload.get("summary"),
                }
                mission.outcome = AuftragOutcome.from_snapshot(snapshot)
                mission.status = (
                    PlanMissionStatus.SUCCEEDED if mission.outcome.success is True else PlanMissionStatus.FAILED
                )
                if mission.status is PlanMissionStatus.FAILED:
                    mission.error = "AUFTRAG evaluated without success"
                await self._mission_event(
                    execution,
                    mission,
                    f"mission.{mission.status.value}",
                    on_event,
                    message=f"MOOSE AUFTRAG outcome success={mission.outcome.success}",
                )
                return mission.status is PlanMissionStatus.SUCCEEDED
            if (event.fsm_event or "").lower() == "cancel":
                # Some MOOSE mission types enter Cancel while evaluating their
                # terminal state, then emit the authoritative Evaluated event.
                cancel_evaluation_deadline = loop.time() + AUFTRAG_CANCEL_EVALUATION_GRACE_S
                continue
            status_key = (event.fsm_event, event.status, event.from_state, event.to_state)
            if status_key in seen_status_keys:
                continue
            seen_status_keys.add(status_key)
            mission.status = PlanMissionStatus.RUNNING
            await self._mission_event(execution, mission, "mission.status", on_event, message=str(event))

    async def _refresh_goal_control(self, objective_id: str) -> None:
        objective = self.client.strategic_objective(objective_id)
        if objective is None:
            return
        component_prefixes = {component.object_id.partition(":")[0].upper() for component in objective.components}
        if "GROUP" in component_prefixes:
            await self.client.snapshot_groups()
        if "UNIT" in component_prefixes:
            await self.client.snapshot_units()
        if "STATIC" in component_prefixes:
            known_static_ids = set(self.client.state.statics)
            await self.client.snapshot_statics()
            refreshed_static_ids = set(self.client.state.statics)
            for component in objective.components:
                component_id = component.object_id
                if not component_id.startswith("STATIC:") or component_id in refreshed_static_ids:
                    continue
                if component_id not in known_static_ids and component_id not in objective.component_health_estimates:
                    continue
                self.client.objectives.record_component_health(
                    objective,
                    component_id,
                    0.0,
                    source="snapshot_absent_after_refresh",
                    mission_time=self.client._current_mission_time(),
                )
        if not objective.control_object_id:
            return
        if objective.control_object_id.startswith("OPSZONE:"):
            await self.client.snapshot_opszones()
        elif objective.control_object_id.startswith("AIRBASE:"):
            await self.client.snapshot_airbases()
        elif objective.control_object_id.startswith("TERRITORY:"):
            await self.client.snapshot_territories()

    async def _finish_reconciled_phase(
        self,
        plan: OperationalPlan,
        execution: OperationalPlanExecution,
        callback: PlanExecutionCallback | None,
    ) -> tuple[PlanReconciliationStatus, str | None]:
        current = self._current_execution_phase(plan, execution)
        goal = self.client.strategic_goal(plan.goal_id)
        if goal is None:
            reason = f"strategic goal is unavailable after reconciliation: {plan.goal_id}"
            await self._block(plan, current, execution, reason, callback)
            return PlanReconciliationStatus.BLOCKED, reason
        if goal.action is StrategicGoalAction.DISABLE:
            effect_error = await self._confirm_disable_effect(
                goal,
                plan,
                current.phase_id,
                tuple(
                    mission
                    for mission in execution.missions
                    if mission.phase_id == current.phase_id and mission.required
                ),
                execution,
                callback,
            )
            if effect_error is not None:
                await self._block(plan, current, execution, effect_error, callback)
                return PlanReconciliationStatus.BLOCKED, effect_error
        current.status = PlanPhaseStatus.COMPLETED
        await self._emit(
            execution,
            PlanExecutionEvent(
                "phase.reconciled",
                plan.plan_id,
                phase_id=current.phase_id,
                status=current.status.value,
            ),
            callback,
        )
        next_phase = next(
            (phase for phase in plan.phases if phase.status is not PlanPhaseStatus.COMPLETED),
            None,
        )
        if next_phase is not None:
            reason = "interrupted phase completed; remaining phases require explicit revalidation and approval"
            await self._block(plan, next_phase, execution, reason, callback)
            return PlanReconciliationStatus.BLOCKED, reason

        await self._refresh_goal_control(goal.objective_id)
        self.client.sync_strategic_objectives(source="plan.reconciliation")
        self.client.sync_strategic_goals(source="plan.reconciliation")
        if goal.status is not StrategicGoalStatus.ACHIEVED:
            reason = "missions completed but the strategic goal is not achieved"
            await self._block(plan, None, execution, reason, callback)
            return PlanReconciliationStatus.BLOCKED, reason

        plan.status = OperationalPlanStatus.COMPLETED
        execution.status = plan.status
        execution.current_phase_id = None
        execution.completed_mission_time = self.client._current_mission_time()
        await self._emit(
            execution,
            PlanExecutionEvent("plan.reconciled", plan.plan_id, status=plan.status.value),
            callback,
        )
        return PlanReconciliationStatus.COMPLETED, None

    async def _confirm_disable_effect(
        self,
        goal: StrategicGoal,
        plan: OperationalPlan,
        phase_id: str,
        required_missions: Iterable[PlanMissionExecution],
        execution: OperationalPlanExecution,
        callback: PlanExecutionCallback | None,
    ) -> str | None:
        """Confirm a supported manual DISABLE effect from authoritative mission outcomes."""

        missions = tuple(required_missions)
        if goal.effect is not StrategicGoalEffect.DENY_RUNWAY:
            return "operational execution currently supports only deny_runway DISABLE goals"
        if not missions or any(
            mission.mission_type != "BOMBRUNWAY" or mission.status is not PlanMissionStatus.SUCCEEDED
            for mission in missions
        ):
            return "deny_runway requires a successful BOMBRUNWAY AUFTRAG against an AIRBASE airdrome"
        self.client.complete_strategic_goal(
            goal,
            achieved=True,
            reason="successful BOMBRUNWAY AUFTRAG against AIRBASE airdrome",
        )
        await self._emit(
            execution,
            PlanExecutionEvent(
                "strategic.effect_confirmed",
                plan.plan_id,
                phase_id=phase_id,
                status=goal.status.value,
                message="effect=deny_runway confirmed by successful BOMBRUNWAY AUFTRAG",
            ),
            callback,
        )
        return None

    @staticmethod
    def _current_execution_phase(plan: OperationalPlan, execution: OperationalPlanExecution) -> PlanPhase:
        if execution.current_phase_id:
            return OperationalPlanExecutor._phase(plan, execution.current_phase_id)
        active = next((phase for phase in plan.phases if phase.status is PlanPhaseStatus.ACTIVE), None)
        if active is not None:
            return active
        mission_phase_id = next(
            (mission.phase_id for mission in reversed(execution.missions) if mission.required),
            None,
        )
        if mission_phase_id:
            return OperationalPlanExecutor._phase(plan, mission_phase_id)
        raise ValueError("interrupted execution has no identifiable active phase")

    async def _preflight_targets(self, commands: Iterable[AuftragCommand]) -> None:
        """Refresh and verify every object id used by executable commands."""

        targets: set[str] = set()
        for command in commands:
            params = command.to_params()
            for key in ("target", "zone", "opszone", "coordinate"):
                value = params.get(key)
                if isinstance(value, str) and ":" in value:
                    targets.add(value)
            zone_values = params.get("zones")
            if isinstance(zone_values, (list, tuple)):
                targets.update(str(value) for value in zone_values if isinstance(value, str) and ":" in value)

        snapshot_methods = {
            "GROUP": "snapshot_groups",
            "UNIT": "snapshot_units",
            "STATIC": "snapshot_statics",
            "ZONE": "snapshot_zones",
            "OPSZONE": "snapshot_opszones",
            "AIRBASE": "snapshot_airbases",
            "TERRITORY": "snapshot_territories",
        }
        state_collections = {
            "GROUP": "groups",
            "UNIT": "units",
            "STATIC": "statics",
            "ZONE": "zones",
            "OPSZONE": "opszones",
            "AIRBASE": "airbases",
            "TERRITORY": "territories",
        }
        prefixes = {target.partition(":")[0].upper() for target in targets}
        unsupported = sorted(prefix for prefix in prefixes if prefix not in snapshot_methods)
        if unsupported:
            raise ValueError(f"operational target preflight does not support object types: {unsupported}")
        for prefix in sorted(prefixes):
            await getattr(self.client, snapshot_methods[prefix])()

        missing = sorted(
            target
            for target in targets
            if target not in getattr(self.client.state, state_collections[target.partition(":")[0].upper()])
        )
        if missing:
            raise ValueError(f"operational target preflight could not find: {', '.join(missing)}")

    async def _block(
        self,
        plan: OperationalPlan,
        phase: PlanPhase | None,
        execution: OperationalPlanExecution,
        reason: str,
        callback: PlanExecutionCallback | None,
    ) -> OperationalPlanExecution:
        if plan.status is OperationalPlanStatus.CANCELLED or execution.status is OperationalPlanStatus.CANCELLED:
            return execution
        if phase is not None:
            phase.status = PlanPhaseStatus.BLOCKED
        plan.status = OperationalPlanStatus.BLOCKED
        execution.status = plan.status
        execution.current_phase_id = phase.phase_id if phase else None
        execution.blocked_reason = reason
        execution.completed_mission_time = self.client._current_mission_time()
        await self._emit(
            execution,
            PlanExecutionEvent(
                "plan.blocked",
                plan.plan_id,
                phase_id=phase.phase_id if phase else None,
                status=plan.status.value,
                message=reason,
            ),
            callback,
        )
        return execution

    async def _mission_event(
        self,
        execution: OperationalPlanExecution,
        mission: PlanMissionExecution,
        event: str,
        callback: PlanExecutionCallback | None,
        *,
        message: str | None = None,
        status: str | None = None,
    ) -> None:
        await self._emit(
            execution,
            PlanExecutionEvent(
                event,
                execution.plan_id,
                phase_id=mission.phase_id,
                intent_id=mission.intent_id,
                requirement_id=mission.requirement_id,
                auftrag_id=mission.auftrag_id,
                status=status or mission.status.value,
                message=message or mission.error,
                mission_type=mission.mission_type,
            ),
            callback,
        )

    async def _emit(
        self,
        execution: OperationalPlanExecution,
        event: PlanExecutionEvent,
        callback: PlanExecutionCallback | None,
    ) -> None:
        if event.mission_time is None:
            event = PlanExecutionEvent(
                event.event,
                event.plan_id,
                event.phase_id,
                event.intent_id,
                event.requirement_id,
                event.auftrag_id,
                event.status,
                self.client._current_mission_time(),
                event.message,
                execution.attempt_id,
                event.mission_type,
            )
        execution.events.append(event)
        await self._persist(execution)
        if callback is not None:
            result = callback(event)
            if inspect.isawaitable(result):
                await result

    async def _persist(self, execution: OperationalPlanExecution) -> None:
        append = getattr(self.client.server, "append_audit_record", None)
        if append is None:
            return
        try:
            from .operational_audit import execution_to_dict, goal_snapshot, objective_snapshot, plan_snapshot

            if execution.plan_ref is not None:
                execution.plan_snapshot = plan_snapshot(execution.plan_ref)
                goal = self.client.strategic_goal(execution.plan_ref.goal_id)
                if goal is not None:
                    execution.goal_snapshot = goal_snapshot(goal)
                    objective = self.client.strategic_objective(goal.objective_id)
                    if objective is not None:
                        execution.objective_snapshot = objective_snapshot(objective)

            await append(PLAN_EXECUTION_AUDIT_TYPE, execution_to_dict(execution))
        except Exception:
            LOGGER.warning("Could not persist operational execution %s", execution.attempt_id, exc_info=True)

    @staticmethod
    def _phase(plan: OperationalPlan, phase_id: str) -> PlanPhase:
        return next(phase for phase in plan.phases if phase.phase_id == phase_id)


def _mission_type(intent: MissionIntent, requirement: AssetRequirement) -> str:
    candidates = requirement.mission_types or intent.auftrag_types
    allowed = set(intent.auftrag_types)
    for mission_type in candidates:
        if mission_type in allowed:
            return mission_type
    raise ValueError(f"{intent.intent_id}/{requirement.requirement_id} has no common AUFTRAG type")


def _command_ack_reference(ack: Mapping[str, Any]) -> CommandAckReference:
    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    relevant_keys = {
        "action",
        "added",
        "auftrag_id",
        "auftragsnummer",
        "auftrag_type",
        "cohort_id",
        "commander_id",
        "legion_id",
    }
    compact_result = {
        str(key): value
        for key, value in result.items()
        if key in relevant_keys and isinstance(value, (str, int, float, bool))
    }
    sequence = ack.get("sequence")
    try:
        sequence_value = int(sequence) if sequence is not None else None
    except (TypeError, ValueError):
        sequence_value = None
    return CommandAckReference(
        ack_id=str(ack.get("id")) if ack.get("id") not in (None, "") else None,
        correlation_id=(
            str(ack.get("correlation_id")) if ack.get("correlation_id") not in (None, "") else None
        ),
        sequence=sequence_value,
        result=compact_result,
    )


def _object_ids(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _auftrag_metadata(intent: MissionIntent, requirement: AssetRequirement) -> tuple[dict[str, Any], dict[str, Any]]:
    constructor: dict[str, Any] = {}
    lifecycle: dict[str, Any] = {}
    for metadata in (intent.metadata, requirement.metadata):
        params = metadata.get("auftrag_params")
        if isinstance(params, dict):
            constructor.update(params)
        for key in ("clock_start", "clock_stop", "duration_s", "weapon_type"):
            if key in metadata:
                lifecycle[key] = metadata[key]
    return constructor, lifecycle


def build_plan_auftrag(
    plan: OperationalPlan,
    intent: MissionIntent,
    requirement: AssetRequirement,
) -> AuftragCommand:
    """Build one supported AUFTRAG command from an operational requirement."""

    mission_type = _mission_type(intent, requirement)
    params, lifecycle = _auftrag_metadata(intent, requirement)
    target = intent.target_object_id
    if mission_type == "BAI":
        if not target or not target.startswith(("GROUP:", "UNIT:", "STATIC:")):
            raise ValueError(f"BAI intent {intent.intent_id} requires a GROUP, UNIT or STATIC target")
        params.setdefault("target", target)
        command = Auftrag_BAI(**params)
    elif mission_type == "ARTY":
        if not target or not target.startswith(("GROUP:", "UNIT:", "STATIC:")):
            raise ValueError(f"ARTY intent {intent.intent_id} requires a GROUP, UNIT or STATIC target")
        params.setdefault("target", target)
        command = Auftrag_ARTY(**params)
    elif mission_type == "BOMBRUNWAY":
        if not target or not target.startswith("AIRBASE:"):
            raise ValueError(f"BOMBRUNWAY intent {intent.intent_id} requires an AIRBASE target")
        params.setdefault("target", target)
        command = Auftrag_BOMBRUNWAY(**params)
    elif mission_type in {"SEAD", "ANTISHIP", "INTERCEPT"}:
        if not target or not target.startswith(("GROUP:", "UNIT:")):
            raise ValueError(f"{mission_type} intent {intent.intent_id} requires a GROUP or UNIT target")
        params.setdefault("target", target)
        factories = {
            "SEAD": Auftrag_SEAD,
            "ANTISHIP": Auftrag_ANTISHIP,
            "INTERCEPT": Auftrag_INTERCEPT,
        }
        command = factories[mission_type](**params)
    elif mission_type in {"GROUNDATTACK", "NAVALENGAGEMENT"}:
        if not target or not target.startswith(("GROUP:", "UNIT:", "STATIC:")):
            raise ValueError(
                f"{mission_type} intent {intent.intent_id} requires a GROUP, UNIT or STATIC target"
            )
        params.setdefault("target", target)
        factories = {
            "GROUNDATTACK": Auftrag_GROUNDATTACK,
            "NAVALENGAGEMENT": Auftrag_NAVALENGAGEMENT,
        }
        command = factories[mission_type](**params)
    elif mission_type == "BOMBING":
        if not target or not target.startswith(("GROUP:", "UNIT:", "STATIC:")):
            raise ValueError(f"BOMBING intent {intent.intent_id} requires a GROUP, UNIT or STATIC target")
        params.setdefault("target", target)
        command = Auftrag_BOMBING(**params)
    elif mission_type == "PATROLZONE":
        if not target or not target.startswith(("ZONE:", "OPSZONE:")):
            raise ValueError(f"PATROLZONE intent {intent.intent_id} requires a ZONE or OPSZONE target")
        params.setdefault("zone", target)
        command = Auftrag_PATROLZONE(**params)
    elif mission_type == "RECON":
        if not target or not target.startswith(("ZONE:", "OPSZONE:")):
            raise ValueError(f"RECON intent {intent.intent_id} requires a ZONE or OPSZONE target")
        params.setdefault("zones", (target,))
        command = Auftrag_RECON(**params)
    elif mission_type == "CAPTUREZONE":
        if not target or not target.startswith("OPSZONE:"):
            raise ValueError(f"CAPTUREZONE intent {intent.intent_id} requires an OPSZONE target")
        params.setdefault("opszone", target)
        params.setdefault("capture_coalition", plan.coalition)
        command = Auftrag_CAPTUREZONE(**params)
    elif mission_type in {"AIRDEFENSE", "AMMOSUPPLY", "FUELSUPPLY", "REARMING"}:
        if not target or not target.startswith(("ZONE:", "OPSZONE:")):
            raise ValueError(f"{mission_type} intent {intent.intent_id} requires a ZONE or OPSZONE target")
        params.setdefault("zone", target)
        factories = {
            "AIRDEFENSE": Auftrag_AIRDEFENSE,
            "AMMOSUPPLY": Auftrag_AMMOSUPPLY,
            "FUELSUPPLY": Auftrag_FUELSUPPLY,
            "REARMING": Auftrag_REARMING,
        }
        command = factories[mission_type](**params)
    else:
        raise ValueError(f"Operational execution does not yet map AUFTRAG type {mission_type}")

    command.set_required_assets(requirement.min_count, requirement.max_count)
    weapon_type = lifecycle.get("weapon_type")
    if weapon_type is None and mission_type == "ARTY":
        fire_support = intent.metadata.get("fire_support")
        if isinstance(fire_support, Mapping):
            weapon_type = fire_support.get("weapon_flag_value")
    if weapon_type is not None:
        command.set_weapon_type(weapon_type)
    if "clock_start" in lifecycle or "clock_stop" in lifecycle:
        command.set_time(lifecycle.get("clock_start"), lifecycle.get("clock_stop"))
    if "duration_s" in lifecycle:
        command.set_duration(lifecycle["duration_s"])
    return command


__all__ = [
    "CommandAckReference",
    "OperationalPlanExecution",
    "OperationalPlanExecutor",
    "OperationalPlanReconciliation",
    "OperationalPlanAbortResult",
    "PlanAbortScope",
    "PlanExecutionCallback",
    "PlanExecutionEvent",
    "PlanMissionExecution",
    "PlanMissionReconciliation",
    "PlanMissionAbort",
    "PlanMissionStatus",
    "PlanReconciliationStatus",
    "build_plan_auftrag",
]
