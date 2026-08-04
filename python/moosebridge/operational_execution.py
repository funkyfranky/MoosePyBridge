"""Event-driven execution of approved operational plans through MOOSE COMMANDER."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
import inspect
from typing import TYPE_CHECKING, Any

from .auftraege import (
    Auftrag_AIRDEFENSE,
    Auftrag_AMMOSUPPLY,
    Auftrag_BAI,
    Auftrag_CAPTUREZONE,
    Auftrag_FUELSUPPLY,
    Auftrag_PATROLZONE,
    Auftrag_REARMING,
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
from .strategic import StrategicGoalAction, StrategicGoalStatus

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


class PlanMissionStatus(str, Enum):
    """Execution state of one concrete AUFTRAG created from a requirement."""

    PENDING = "pending"
    SKIPPED = "skipped"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


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

    def __str__(self) -> str:
        """Return a compact progress line suitable for example callbacks."""

        reference = self.auftrag_id or self.requirement_id or self.phase_id or self.plan_id
        parts = [reference, self.event]
        if self.status:
            parts.append(f"status={self.status}")
        if self.message:
            parts.append(self.message)
        return " ".join(parts)


@dataclass(slots=True)
class PlanMissionExecution:
    """Runtime record connecting one requirement to one MOOSE AUFTRAG."""

    phase_id: str
    intent_id: str
    requirement_id: str
    mission_type: str
    required: bool
    command: AuftragCommand | None = field(default=None, repr=False)
    status: PlanMissionStatus = PlanMissionStatus.PENDING
    auftrag_id: str | None = None
    outcome: AuftragOutcome | None = None
    error: str | None = None


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
    missions: list[PlanMissionExecution] = field(default_factory=list)
    events: list[PlanExecutionEvent] = field(default_factory=list)


PlanExecutionCallback = Callable[[PlanExecutionEvent], Any | Awaitable[Any]]


class OperationalPlanExecutor:
    """Execute approved capture plans phase by phase without status polling."""

    def __init__(self, client: MooseBridgeClient) -> None:
        self.client = client
        self._executions: dict[str, list[OperationalPlanExecution]] = {}

    def get(self, plan_id: str) -> OperationalPlanExecution | None:
        history = self._executions.get(plan_id, ())
        return history[-1] if history else None

    def history(self, plan_id: str) -> tuple[OperationalPlanExecution, ...]:
        """Return all execution attempts for a plan in chronological order."""

        return tuple(self._executions.get(plan_id, ()))

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
        """Execute an approved capture plan and return its runtime record."""

        if plan.status is not OperationalPlanStatus.APPROVED:
            raise ValueError("only an approved operational plan can be executed")
        goal = self.client.strategic_goal(plan.goal_id)
        if goal is None:
            raise ValueError(f"Unknown strategic goal: {plan.goal_id}")
        if goal.action is not StrategicGoalAction.CAPTURE:
            raise ValueError("the first operational executor supports CAPTURE goals only")
        assessment = self.client.plans.assessment(plan.plan_id)
        if assessment is None or not assessment.feasible:
            raise ValueError("operational plan requires a current feasible assessment")
        latest = self.get(plan.plan_id)
        if latest and latest.status is OperationalPlanStatus.EXECUTING:
            raise ValueError(f"operational plan is already executing: {plan.plan_id}")
        if goal.status in {StrategicGoalStatus.FAILED, StrategicGoalStatus.CANCELLED}:
            raise ValueError(f"strategic goal cannot be executed in state {goal.status.value}")

        commander = self.client.commander(commander_id) if commander_id else self.client.commander_for_coalition(plan.coalition)
        if commander is None:
            raise ValueError(f"Unknown COMMANDER: {commander_id}")
        if (commander.coalition or "").lower() != plan.coalition:
            raise ValueError("COMMANDER coalition must match the operational plan")

        assessments = {
            (item.phase_id, item.intent_id, item.requirement_id): item
            for item in assessment.requirements
        }
        prepared: dict[tuple[str, str, str], AuftragCommand] = {}
        commander_legions = set(commander.legion_ids)
        for phase in plan.phases:
            if phase.status is PlanPhaseStatus.COMPLETED:
                continue
            for intent in phase.intents:
                for requirement in intent.asset_requirements:
                    item = assessments[(phase.phase_id, intent.intent_id, requirement.requirement_id)]
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
                        if not (cohort := self.client.cohort(cohort_id)) or cohort.legion_id not in commander_legions
                    ]
                    if invalid_cohorts:
                        raise ValueError(
                            f"{requirement.requirement_id} constrains COHORTs outside {commander.object_id}: "
                            f"{sorted(invalid_cohorts)}"
                        )
                    prepared[(phase.phase_id, intent.intent_id, requirement.requirement_id)] = build_plan_auftrag(
                        plan,
                        intent,
                        requirement,
                    )

        await self._preflight_targets(prepared.values())

        history = self._executions.setdefault(plan.plan_id, [])
        attempt_number = len(history) + 1
        execution = OperationalPlanExecution(
            plan_id=plan.plan_id,
            commander_id=commander.object_id,
            attempt_id=f"{plan.plan_id}/ATTEMPT:{attempt_number}",
            attempt_number=attempt_number,
            resumed_from_phase_id=plan.metadata.pop("retry_resume_phase_id", None),
            status=OperationalPlanStatus.EXECUTING,
            started_mission_time=self.client._current_mission_time(),
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
            phase.status = PlanPhaseStatus.ACTIVE
            execution.current_phase_id = phase.phase_id
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
                        await self.client.add_auftrag(
                            command,
                            commander=commander.object_id,
                            allowed_legions=requirement.allowed_legion_ids,
                            allowed_cohorts=requirement.allowed_cohort_ids,
                        )
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

            failed = await self._wait_for_required_missions(
                execution,
                required_missions,
                mission_timeout_s=mission_timeout_s,
                on_event=on_event,
            )
            if failed is not None:
                return await self._block(
                    plan,
                    phase,
                    execution,
                    failed.error or f"{failed.auftrag_id} did not succeed",
                    on_event,
                )

            phase.status = PlanPhaseStatus.COMPLETED
            await self._emit(
                execution,
                PlanExecutionEvent("phase.completed", plan.plan_id, phase_id=phase.phase_id, status=phase.status.value),
                on_event,
            )

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

    async def _wait_for_required_missions(
        self,
        execution: OperationalPlanExecution,
        missions: list[PlanMissionExecution],
        *,
        mission_timeout_s: float,
        on_event: PlanExecutionCallback | None,
    ) -> PlanMissionExecution | None:
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
                        return mission
            return None
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

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
        after_id: str | None = None
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                mission.error = f"timed out waiting for {mission.auftrag_id}"
                return False
            message = await self.client.server.wait_for_event(
                "auftrag.*",
                filters={"auftrag_id": mission.auftrag_id},
                timeout=remaining,
                after_id=after_id,
            )
            after_id = str(message.get("id") or "") or after_id
            self.client.state.apply_message(message)
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
                await self._mission_event(execution, mission, f"mission.{mission.status.value}", on_event)
                return mission.status is PlanMissionStatus.SUCCEEDED
            if (event.fsm_event or "").lower() == "cancel":
                mission.status = PlanMissionStatus.CANCELLED
                mission.error = "AUFTRAG was cancelled"
                await self._mission_event(execution, mission, "mission.cancelled", on_event)
                return False
            mission.status = PlanMissionStatus.RUNNING
            await self._mission_event(execution, mission, "mission.status", on_event, message=str(event))

    async def _refresh_goal_control(self, objective_id: str) -> None:
        objective = self.client.strategic_objective(objective_id)
        if objective is None or not objective.control_object_id:
            return
        if objective.control_object_id.startswith("OPSZONE:"):
            await self.client.snapshot_opszones()
        elif objective.control_object_id.startswith("AIRBASE:"):
            await self.client.snapshot_airbases()
        elif objective.control_object_id.startswith("TERRITORY:"):
            await self.client.snapshot_territories()

    async def _preflight_targets(self, commands: Iterable[AuftragCommand]) -> None:
        """Refresh and verify every object id used by executable commands."""

        targets: set[str] = set()
        for command in commands:
            params = command.to_params()
            for key in ("target", "zone", "opszone", "coordinate"):
                value = params.get(key)
                if isinstance(value, str) and ":" in value:
                    targets.add(value)

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
                status=mission.status.value,
                message=message or mission.error,
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
            )
        execution.events.append(event)
        if callback is not None:
            result = callback(event)
            if inspect.isawaitable(result):
                await result

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
        for key in ("clock_start", "clock_stop", "duration_s"):
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
    elif mission_type == "PATROLZONE":
        if not target or not target.startswith(("ZONE:", "OPSZONE:")):
            raise ValueError(f"PATROLZONE intent {intent.intent_id} requires a ZONE or OPSZONE target")
        params.setdefault("zone", target)
        command = Auftrag_PATROLZONE(**params)
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
    if "clock_start" in lifecycle or "clock_stop" in lifecycle:
        command.set_time(lifecycle.get("clock_start"), lifecycle.get("clock_stop"))
    if "duration_s" in lifecycle:
        command.set_duration(lifecycle["duration_s"])
    return command


__all__ = [
    "OperationalPlanExecution",
    "OperationalPlanExecutor",
    "PlanExecutionCallback",
    "PlanExecutionEvent",
    "PlanMissionExecution",
    "PlanMissionStatus",
    "build_plan_auftrag",
]
