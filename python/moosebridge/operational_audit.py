"""Serialization schema for persistent operational-plan execution audits."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .operational import (
    AssetRequirement,
    AssetRole,
    MissionIntent,
    OperationalPlan,
    OperationalPlanAssessment,
    OperationalPlanProvenance,
    OperationalPlanStatus,
    OperationalPosture,
    PlanPhase,
    PlanPhaseStatus,
    PlanProposalIssue,
    PlanSourceType,
)
from .operational_execution import (
    CommandAckReference,
    OperationalPlanExecution,
    PlanExecutionEvent,
    PlanMissionExecution,
    PlanMissionStatus,
    StrategicDamageAssessment,
)
from .outcomes import AuftragOutcome
from .recon import ReconOutcome, ReconTrackSample
from .strategic import (
    CaptureBehavior,
    ComponentHealthEstimate,
    GoalCondition,
    GoalConditionKind,
    GoalConditionMatch,
    GoalEvaluationMode,
    ObjectiveComponent,
    ObjectiveKind,
    ObjectiveStatus,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalEffect,
    StrategicGoalStatus,
    StrategicObjective,
)


@dataclass(slots=True, frozen=True)
class RestoredOperationalPlan:
    """Typed strategic and operational context reconstructed from one audit."""

    objective: StrategicObjective
    goal: StrategicGoal
    plan: OperationalPlan
    executions: tuple[OperationalPlanExecution, ...]


def execution_to_dict(execution: OperationalPlanExecution) -> dict[str, Any]:
    return {
        "plan_id": execution.plan_id,
        "commander_id": execution.commander_id,
        "attempt_id": execution.attempt_id,
        "attempt_number": execution.attempt_number,
        "resumed_from_phase_id": execution.resumed_from_phase_id,
        "status": execution.status.value,
        "current_phase_id": execution.current_phase_id,
        "started_mission_time": execution.started_mission_time,
        "completed_mission_time": execution.completed_mission_time,
        "blocked_reason": execution.blocked_reason,
        "plan": execution.plan_snapshot,
        "goal": execution.goal_snapshot,
        "objective": execution.objective_snapshot,
        "assessment": execution.assessment_snapshot,
        "missions": [_mission_to_dict(mission) for mission in execution.missions],
        "damage_assessments": [_damage_assessment_to_dict(item) for item in execution.damage_assessments],
        "events": [_event_to_dict(event) for event in execution.events],
    }


def execution_from_dict(data: Mapping[str, Any]) -> OperationalPlanExecution:
    return OperationalPlanExecution(
        plan_id=str(data.get("plan_id") or ""),
        commander_id=str(data.get("commander_id") or ""),
        attempt_id=str(data.get("attempt_id") or ""),
        attempt_number=int(data.get("attempt_number") or 1),
        resumed_from_phase_id=_text(data.get("resumed_from_phase_id")),
        status=OperationalPlanStatus(data.get("status") or OperationalPlanStatus.APPROVED.value),
        current_phase_id=_text(data.get("current_phase_id")),
        started_mission_time=_float(data.get("started_mission_time")),
        completed_mission_time=_float(data.get("completed_mission_time")),
        blocked_reason=_text(data.get("blocked_reason")),
        plan_snapshot=dict(data.get("plan")) if isinstance(data.get("plan"), dict) else {},
        goal_snapshot=dict(data.get("goal")) if isinstance(data.get("goal"), dict) else {},
        objective_snapshot=dict(data.get("objective")) if isinstance(data.get("objective"), dict) else {},
        assessment_snapshot=dict(data.get("assessment")) if isinstance(data.get("assessment"), dict) else {},
        missions=[_mission_from_dict(item) for item in data.get("missions", ()) if isinstance(item, dict)],
        damage_assessments=[
            _damage_assessment_from_dict(item)
            for item in data.get("damage_assessments", ())
            if isinstance(item, dict)
        ],
        events=[_event_from_dict(item) for item in data.get("events", ()) if isinstance(item, dict)],
    )


def plan_snapshot(plan: OperationalPlan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "name": plan.name,
        "goal_id": plan.goal_id,
        "coalition": plan.coalition,
        "posture": plan.posture.value,
        "status": plan.status.value,
        "created_mission_time": plan.created_mission_time,
        "validated_mission_time": plan.validated_mission_time,
        "approved_mission_time": plan.approved_mission_time,
        "approved_by": plan.approved_by,
        "approved_client_id": plan.approved_client_id,
        "approval_reason": plan.approval_reason,
        "provenance": (
            {
                "source_type": plan.provenance.source_type.value,
                "source_id": plan.provenance.source_id,
                "picture_mission_time": plan.provenance.picture_mission_time,
                "rationale": plan.provenance.rationale,
            }
            if plan.provenance
            else None
        ),
        "proposal_issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "reference_id": issue.reference_id,
            }
            for issue in plan.proposal_issues
        ],
        "metadata": dict(plan.metadata),
        "phases": [_phase_to_dict(phase) for phase in plan.phases],
    }


def plan_from_snapshot(data: Mapping[str, Any]) -> OperationalPlan:
    provenance_data = data.get("provenance") if isinstance(data.get("provenance"), dict) else None
    phases = []
    for phase_data in data.get("phases", ()):
        if not isinstance(phase_data, dict):
            continue
        intents = []
        for intent_data in phase_data.get("intents", ()):
            if not isinstance(intent_data, dict):
                continue
            requirements = []
            for requirement_data in intent_data.get("asset_requirements", ()):
                if not isinstance(requirement_data, dict):
                    continue
                requirements.append(
                    AssetRequirement(
                        requirement_id=str(requirement_data.get("requirement_id") or ""),
                        role=AssetRole(requirement_data.get("role") or AssetRole.COMBAT.value),
                        min_count=int(requirement_data.get("min_count") or 0),
                        max_count=_int(requirement_data.get("max_count")),
                        mission_types=tuple(str(item) for item in requirement_data.get("mission_types", ())),
                        performer_categories=tuple(str(item) for item in requirement_data.get("performer_categories", ())),
                        preferred_legion_ids=tuple(str(item) for item in requirement_data.get("preferred_legion_ids", ())),
                        allowed_legion_ids=tuple(str(item) for item in requirement_data.get("allowed_legion_ids", ())),
                        allowed_cohort_ids=tuple(str(item) for item in requirement_data.get("allowed_cohort_ids", ())),
                        require_payload=bool(requirement_data.get("require_payload", False)),
                        metadata=dict(requirement_data.get("metadata")) if isinstance(requirement_data.get("metadata"), dict) else {},
                    )
                )
            intents.append(
                MissionIntent(
                    intent_id=str(intent_data.get("intent_id") or ""),
                    name=str(intent_data.get("name") or ""),
                    auftrag_types=tuple(str(item) for item in intent_data.get("auftrag_types", ())),
                    asset_requirements=tuple(requirements),
                    target_object_id=_text(intent_data.get("target_object_id")),
                    required=bool(intent_data.get("required", True)),
                    metadata=dict(intent_data.get("metadata")) if isinstance(intent_data.get("metadata"), dict) else {},
                )
            )
        phases.append(
            PlanPhase(
                phase_id=str(phase_data.get("phase_id") or ""),
                name=str(phase_data.get("name") or ""),
                intents=tuple(intents),
                depends_on=tuple(str(item) for item in phase_data.get("depends_on", ())),
                status=PlanPhaseStatus(phase_data.get("status") or PlanPhaseStatus.PENDING.value),
                optional=bool(phase_data.get("optional", False)),
                metadata=dict(phase_data.get("metadata")) if isinstance(phase_data.get("metadata"), dict) else {},
            )
        )
    return OperationalPlan(
        plan_id=str(data.get("plan_id") or ""),
        name=str(data.get("name") or ""),
        goal_id=str(data.get("goal_id") or ""),
        coalition=str(data.get("coalition") or ""),
        phases=tuple(phases),
        posture=OperationalPosture(data.get("posture") or OperationalPosture.BALANCED.value),
        status=OperationalPlanStatus(data.get("status") or OperationalPlanStatus.DRAFT.value),
        created_mission_time=_float(data.get("created_mission_time")),
        validated_mission_time=_float(data.get("validated_mission_time")),
        approved_mission_time=_float(data.get("approved_mission_time")),
        approved_by=_text(data.get("approved_by")),
        approved_client_id=_text(data.get("approved_client_id")),
        approval_reason=_text(data.get("approval_reason")),
        provenance=(
            OperationalPlanProvenance(
                source_type=PlanSourceType(provenance_data.get("source_type") or PlanSourceType.OPERATOR.value),
                source_id=str(provenance_data.get("source_id") or "legacy"),
                picture_mission_time=_float(provenance_data.get("picture_mission_time")),
                rationale=_text(provenance_data.get("rationale")),
            )
            if provenance_data
            else None
        ),
        proposal_issues=tuple(
            PlanProposalIssue(
                severity=str(issue.get("severity") or "warning"),
                code=str(issue.get("code") or "legacy_issue"),
                message=str(issue.get("message") or "Legacy proposal issue"),
                reference_id=_text(issue.get("reference_id")),
            )
            for issue in data.get("proposal_issues", ())
            if isinstance(issue, dict)
        ),
        metadata=dict(data.get("metadata")) if isinstance(data.get("metadata"), dict) else {},
    )


def objective_snapshot(objective: StrategicObjective) -> dict[str, Any]:
    return {
        "objective_id": objective.objective_id,
        "name": objective.name,
        "kind": objective.kind.value,
        "control_object_id": objective.control_object_id,
        "ownership_policy": objective.ownership_policy.value,
        "components": [
            {
                "object_id": component.object_id,
                "role": component.role,
                "weight": component.weight,
                "contributes_to_health": component.contributes_to_health,
                "capture_behavior": component.capture_behavior.value,
                "metadata": dict(component.metadata),
            }
            for component in objective.components
        ],
        "strategic_value": objective.strategic_value,
        "priority": objective.priority,
        "owner": objective.owner,
        "status": objective.status.value,
        "health": objective.health,
        "contested": objective.contested,
        "created_mission_time": objective.created_mission_time,
        "updated_mission_time": objective.updated_mission_time,
        "metadata": dict(objective.metadata),
        "component_health_estimates": {
            component_id: {
                "health": estimate.health,
                "source": estimate.source,
                "mission_time": estimate.mission_time,
            }
            for component_id, estimate in objective.component_health_estimates.items()
        },
    }


def objective_from_snapshot(data: Mapping[str, Any]) -> StrategicObjective:
    return StrategicObjective(
        objective_id=str(data.get("objective_id") or ""),
        name=str(data.get("name") or ""),
        kind=ObjectiveKind(data.get("kind") or ObjectiveKind.CUSTOM.value),
        control_object_id=_text(data.get("control_object_id")),
        ownership_policy=OwnershipPolicy(data.get("ownership_policy") or OwnershipPolicy.FIXED.value),
        components=tuple(
            ObjectiveComponent(
                object_id=str(component.get("object_id") or ""),
                role=str(component.get("role") or "component"),
                weight=float(component.get("weight") or 0.0),
                contributes_to_health=bool(component.get("contributes_to_health", True)),
                capture_behavior=CaptureBehavior(component.get("capture_behavior") or CaptureBehavior.KEEP.value),
                metadata=dict(component.get("metadata")) if isinstance(component.get("metadata"), dict) else {},
            )
            for component in data.get("components", ())
            if isinstance(component, dict)
        ),
        strategic_value=float(data.get("strategic_value") or 0.0),
        priority=float(data.get("priority") or 0.0),
        owner=_text(data.get("owner")),
        status=ObjectiveStatus(data.get("status") or ObjectiveStatus.UNKNOWN.value),
        health=_float(data.get("health")),
        contested=bool(data.get("contested", False)),
        created_mission_time=_float(data.get("created_mission_time")),
        updated_mission_time=_float(data.get("updated_mission_time")),
        metadata=dict(data.get("metadata")) if isinstance(data.get("metadata"), dict) else {},
        component_health_estimates={
            str(component_id): ComponentHealthEstimate(
                health=float(estimate.get("health")),
                source=str(estimate.get("source") or "audit"),
                mission_time=_float(estimate.get("mission_time")),
            )
            for component_id, estimate in (data.get("component_health_estimates") or {}).items()
            if isinstance(estimate, dict) and _float(estimate.get("health")) is not None
        },
    )


def goal_snapshot(goal: StrategicGoal) -> dict[str, Any]:
    return {
        "goal_id": goal.goal_id,
        "name": goal.name,
        "coalition": goal.coalition,
        "action": goal.action.value,
        "objective_id": goal.objective_id,
        "required_damage": goal.required_damage,
        "effect": goal.effect.value if goal.effect else None,
        "priority": goal.priority,
        "status": goal.status.value,
        "evaluation_mode": goal.evaluation_mode.value,
        "success_conditions": [_condition_to_dict(condition) for condition in goal.success_conditions],
        "failure_conditions": [_condition_to_dict(condition) for condition in goal.failure_conditions],
        "success_match": goal.success_match.value,
        "failure_match": goal.failure_match.value,
        "created_mission_time": goal.created_mission_time,
        "activated_mission_time": goal.activated_mission_time,
        "deadline_mission_time": goal.deadline_mission_time,
        "completed_mission_time": goal.completed_mission_time,
        "failure_reason": goal.failure_reason,
        "metadata": dict(goal.metadata),
    }


def goal_from_snapshot(data: Mapping[str, Any]) -> StrategicGoal:
    return StrategicGoal(
        goal_id=str(data.get("goal_id") or ""),
        name=str(data.get("name") or ""),
        coalition=str(data.get("coalition") or ""),
        action=StrategicGoalAction(data.get("action") or StrategicGoalAction.CAPTURE.value),
        objective_id=str(data.get("objective_id") or ""),
        required_damage=_float(data.get("required_damage")),
        effect=StrategicGoalEffect(data["effect"]) if data.get("effect") else None,
        priority=float(data.get("priority") or 0.0),
        status=StrategicGoalStatus(data.get("status") or StrategicGoalStatus.PLANNED.value),
        evaluation_mode=GoalEvaluationMode(data.get("evaluation_mode") or GoalEvaluationMode.IMMEDIATE.value),
        success_conditions=tuple(
            _condition_from_dict(item) for item in data.get("success_conditions", ()) if isinstance(item, dict)
        ),
        failure_conditions=tuple(
            _condition_from_dict(item) for item in data.get("failure_conditions", ()) if isinstance(item, dict)
        ),
        success_match=GoalConditionMatch(data.get("success_match") or GoalConditionMatch.ALL.value),
        failure_match=GoalConditionMatch(data.get("failure_match") or GoalConditionMatch.ANY.value),
        created_mission_time=_float(data.get("created_mission_time")),
        activated_mission_time=_float(data.get("activated_mission_time")),
        deadline_mission_time=_float(data.get("deadline_mission_time")),
        completed_mission_time=_float(data.get("completed_mission_time")),
        failure_reason=_text(data.get("failure_reason")),
        metadata=dict(data.get("metadata")) if isinstance(data.get("metadata"), dict) else {},
    )


def assessment_snapshot(assessment: OperationalPlanAssessment) -> dict[str, Any]:
    return {
        "plan_id": assessment.plan_id,
        "feasible": assessment.feasible,
        "requirements": [
            {
                "phase_id": item.phase_id,
                "intent_id": item.intent_id,
                "requirement_id": item.requirement_id,
                "required_count": item.required_count,
                "available_count": item.available_count,
                "candidate_cohort_ids": list(item.candidate_cohort_ids),
                "allocations": [
                    {"cohort_id": allocation.cohort_id, "legion_id": allocation.legion_id, "count": allocation.count}
                    for allocation in item.allocations
                ],
                "feasible": item.feasible,
                "shortfall": item.shortfall,
            }
            for item in assessment.requirements
        ],
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "reference_id": issue.reference_id,
            }
            for issue in assessment.issues
        ],
    }


def _phase_to_dict(phase: PlanPhase) -> dict[str, Any]:
    return {
        "phase_id": phase.phase_id,
        "name": phase.name,
        "depends_on": list(phase.depends_on),
        "status": phase.status.value,
        "optional": phase.optional,
        "metadata": dict(phase.metadata),
        "intents": [
            {
                "intent_id": intent.intent_id,
                "name": intent.name,
                "auftrag_types": list(intent.auftrag_types),
                "target_object_id": intent.target_object_id,
                "required": intent.required,
                "metadata": dict(intent.metadata),
                "asset_requirements": [
                    {
                        "requirement_id": requirement.requirement_id,
                        "role": requirement.role.value,
                        "min_count": requirement.min_count,
                        "max_count": requirement.max_count,
                        "mission_types": list(requirement.mission_types),
                        "performer_categories": list(requirement.performer_categories),
                        "preferred_legion_ids": list(requirement.preferred_legion_ids),
                        "allowed_legion_ids": list(requirement.allowed_legion_ids),
                        "allowed_cohort_ids": list(requirement.allowed_cohort_ids),
                        "require_payload": requirement.require_payload,
                        "metadata": dict(requirement.metadata),
                    }
                    for requirement in intent.asset_requirements
                ],
            }
            for intent in phase.intents
        ],
    }


def _mission_to_dict(mission: PlanMissionExecution) -> dict[str, Any]:
    command = mission.command_snapshot or None
    if mission.command is not None:
        command = {
            "mission_type": mission.command.mission_type,
            "params": {**mission.command.to_params(), **mission.command.timing_params()},
        }
    return {
        "phase_id": mission.phase_id,
        "intent_id": mission.intent_id,
        "requirement_id": mission.requirement_id,
        "mission_type": mission.mission_type,
        "required": mission.required,
        "command": command,
        "weapon_range_ack": _ack_to_dict(mission.weapon_range_ack),
        "command_ack": (
            {
                "ack_id": mission.command_ack.ack_id,
                "correlation_id": mission.command_ack.correlation_id,
                "sequence": mission.command_ack.sequence,
                "result": dict(mission.command_ack.result),
            }
            if mission.command_ack
            else None
        ),
        "status": mission.status.value,
        "auftrag_id": mission.auftrag_id,
        "outcome": mission.outcome.to_dict() if mission.outcome else None,
        "recon_outcome": mission.recon_outcome.to_dict() if mission.recon_outcome else None,
        "event_cursor": mission.event_cursor,
        "recon_intel_id": mission.recon_intel_id,
        "baseline_intel_contact_ids": list(mission.baseline_intel_contact_ids),
        "recon_assigned_group_ids": list(mission.recon_assigned_group_ids),
        "recon_tracks": {
            group_id: [sample.to_dict() for sample in samples]
            for group_id, samples in mission.recon_tracks.items()
        },
        "error": mission.error,
    }


def _mission_from_dict(data: Mapping[str, Any]) -> PlanMissionExecution:
    outcome_data = data.get("outcome") if isinstance(data.get("outcome"), dict) else None
    recon_outcome_data = data.get("recon_outcome") if isinstance(data.get("recon_outcome"), dict) else None
    ack_data = data.get("command_ack") if isinstance(data.get("command_ack"), dict) else None
    weapon_range_ack_data = (
        data.get("weapon_range_ack") if isinstance(data.get("weapon_range_ack"), dict) else None
    )
    return PlanMissionExecution(
        phase_id=str(data.get("phase_id") or ""),
        intent_id=str(data.get("intent_id") or ""),
        requirement_id=str(data.get("requirement_id") or ""),
        mission_type=str(data.get("mission_type") or ""),
        required=bool(data.get("required", False)),
        command_snapshot=dict(data.get("command")) if isinstance(data.get("command"), dict) else {},
        weapon_range_ack=_ack_from_dict(weapon_range_ack_data),
        command_ack=(
            CommandAckReference(
                ack_id=_text(ack_data.get("ack_id")),
                correlation_id=_text(ack_data.get("correlation_id")),
                sequence=_int(ack_data.get("sequence")),
                result=dict(ack_data.get("result")) if isinstance(ack_data.get("result"), dict) else {},
            )
            if ack_data
            else None
        ),
        status=PlanMissionStatus(data.get("status") or PlanMissionStatus.PENDING.value),
        auftrag_id=_text(data.get("auftrag_id")),
        outcome=_outcome_from_dict(outcome_data) if outcome_data else None,
        recon_outcome=ReconOutcome.from_dict(recon_outcome_data) if recon_outcome_data else None,
        event_cursor=_text(data.get("event_cursor")),
        recon_intel_id=_text(data.get("recon_intel_id")),
        baseline_intel_contact_ids=tuple(str(item) for item in data.get("baseline_intel_contact_ids", ())),
        recon_assigned_group_ids=tuple(str(item) for item in data.get("recon_assigned_group_ids", ())),
        recon_tracks={
            str(group_id): [ReconTrackSample.from_dict(item) for item in samples if isinstance(item, dict)]
            for group_id, samples in (data.get("recon_tracks") or {}).items()
            if isinstance(samples, list)
        } if isinstance(data.get("recon_tracks"), dict) else {},
        error=_text(data.get("error")),
    )


def _ack_to_dict(ack: CommandAckReference | None) -> dict[str, Any] | None:
    if ack is None:
        return None
    return {
        "ack_id": ack.ack_id,
        "correlation_id": ack.correlation_id,
        "sequence": ack.sequence,
        "result": dict(ack.result),
    }


def _ack_from_dict(data: Mapping[str, Any] | None) -> CommandAckReference | None:
    if data is None:
        return None
    return CommandAckReference(
        ack_id=_text(data.get("ack_id")),
        correlation_id=_text(data.get("correlation_id")),
        sequence=_int(data.get("sequence")),
        result=dict(data.get("result")) if isinstance(data.get("result"), dict) else {},
    )


def _damage_assessment_to_dict(assessment: StrategicDamageAssessment) -> dict[str, Any]:
    return {
        "phase_id": assessment.phase_id,
        "objective_id": assessment.objective_id,
        "required_damage": assessment.required_damage,
        "health_before": assessment.health_before,
        "health_after": assessment.health_after,
        "achieved_damage": assessment.achieved_damage,
        "phase_damage": assessment.phase_damage,
        "satisfied": assessment.satisfied,
        "component_health": [
            {"object_id": object_id, "health": health, "source": source}
            for object_id, health, source in assessment.component_health
        ],
        "mission_time": assessment.mission_time,
    }


def _damage_assessment_from_dict(data: Mapping[str, Any]) -> StrategicDamageAssessment:
    return StrategicDamageAssessment(
        phase_id=str(data.get("phase_id") or ""),
        objective_id=str(data.get("objective_id") or ""),
        required_damage=_float(data.get("required_damage")) or 0.0,
        health_before=_float(data.get("health_before")),
        health_after=_float(data.get("health_after")),
        achieved_damage=_float(data.get("achieved_damage")),
        phase_damage=_float(data.get("phase_damage")),
        satisfied=bool(data.get("satisfied", False)),
        component_health=tuple(
            (
                str(item.get("object_id") or ""),
                _float(item.get("health")),
                str(item.get("source") or "snapshot"),
            )
            for item in data.get("component_health", ())
            if isinstance(item, dict)
        ),
        mission_time=_float(data.get("mission_time")),
    )


def _event_to_dict(event: PlanExecutionEvent) -> dict[str, Any]:
    return {
        "event": event.event,
        "plan_id": event.plan_id,
        "phase_id": event.phase_id,
        "intent_id": event.intent_id,
        "requirement_id": event.requirement_id,
        "auftrag_id": event.auftrag_id,
        "status": event.status,
        "mission_time": event.mission_time,
        "message": event.message,
        "attempt_id": event.attempt_id,
    }


def _event_from_dict(data: Mapping[str, Any]) -> PlanExecutionEvent:
    return PlanExecutionEvent(
        event=str(data.get("event") or ""),
        plan_id=str(data.get("plan_id") or ""),
        phase_id=_text(data.get("phase_id")),
        intent_id=_text(data.get("intent_id")),
        requirement_id=_text(data.get("requirement_id")),
        auftrag_id=_text(data.get("auftrag_id")),
        status=_text(data.get("status")),
        mission_time=_float(data.get("mission_time")),
        message=_text(data.get("message")),
        attempt_id=_text(data.get("attempt_id")),
    )


def _condition_to_dict(condition: GoalCondition) -> dict[str, Any]:
    return {"kind": condition.kind.value, "value": _json_value(condition.value)}


def _condition_from_dict(data: Mapping[str, Any]) -> GoalCondition:
    return GoalCondition(GoalConditionKind(data.get("kind")), data.get("value"))


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _outcome_from_dict(data: Mapping[str, Any]) -> AuftragOutcome:
    return AuftragOutcome(
        auftrag_id=str(data.get("auftrag_id") or ""),
        mission_type=_text(data.get("mission_type")),
        status=_text(data.get("status")),
        evaluated=bool(data.get("evaluated", False)),
        success=data.get("success") if isinstance(data.get("success"), bool) else None,
        damage=_float(data.get("damage")),
        n_targets_initial=_int(data.get("n_targets_initial")),
        n_targets_final=_int(data.get("n_targets_final")),
        n_destroyed=_int(data.get("n_destroyed")),
        n_kills=_int(data.get("n_kills")),
        n_elements=_int(data.get("n_elements")),
        n_casualties=_int(data.get("n_casualties")),
        target_life=_float(data.get("target_life")),
        category=_text(data.get("category")),
    )


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "RestoredOperationalPlan",
    "assessment_snapshot",
    "execution_from_dict",
    "execution_to_dict",
    "goal_from_snapshot",
    "goal_snapshot",
    "objective_from_snapshot",
    "objective_snapshot",
    "plan_from_snapshot",
    "plan_snapshot",
]
