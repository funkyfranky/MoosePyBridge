"""Side-effect-free strategic candidate derivation and portfolio decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import Iterable, Mapping

from .diplomacy import CoalitionDoctrine, CoalitionRelationship
from .legions import Cohort
from .operational import OperationalPlan, OperationalPlanAssessment
from .pictures import TacticalPicture
from .strategic import (
    ObjectiveKind,
    ObjectiveStatus,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalEffect,
    StrategicGoalStatus,
    StrategicObjective,
    normalize_coalition,
)

STRATEGIC_DECISION_AUDIT_TYPE = "strategic_decision"


class StrategicDecisionDisposition(StrEnum):
    """Result of considering one coalition/action/objective tuple."""

    SELECTED = "selected"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class StrategicDecisionReasonCode(StrEnum):
    """Stable machine-readable explanations for strategic decisions."""

    SELECTED_FEASIBLE = "selected_feasible"
    CONCURRENCY_LIMIT = "concurrency_limit"
    RESOURCE_CONFLICT = "resource_conflict"
    ALTERNATIVE_ACTION_SELECTED = "alternative_action_selected"
    RELATIONSHIP_FORBIDS = "relationship_forbids"
    DUPLICATE_OPEN_GOAL = "duplicate_open_goal"
    FRIENDLY_OBJECTIVE = "friendly_objective"
    NEUTRAL_PROTECTED = "neutral_protected"
    OUT_OF_SCOPE = "out_of_scope"
    OBJECTIVE_DESTROYED = "objective_destroyed"
    ACTION_NOT_SUPPORTED = "action_not_supported"
    TARGET_COMPONENTS_MISSING = "target_components_missing"
    PLAN_INFEASIBLE = "plan_infeasible"
    PLANNING_FAILED = "planning_failed"


@dataclass(slots=True, frozen=True)
class StrategicDecisionWeights:
    """Transparent weights for ranking otherwise eligible candidates."""

    strategic_value: float = 0.30
    urgency: float = 0.25
    doctrine: float = 0.20
    operational: float = 0.15
    confidence: float = 0.10

    def __post_init__(self) -> None:
        values = (
            self.strategic_value,
            self.urgency,
            self.doctrine,
            self.operational,
            self.confidence,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("strategic decision weights must be finite and non-negative")
        if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("strategic decision weights must sum to one")


@dataclass(slots=True, frozen=True)
class StrategicDecisionConfig:
    """Conservative configuration for one recommendation cycle."""

    max_concurrent_goals: int = 1
    defense_duration_s: float = 1800.0
    destroy_required_damage: float = 0.70
    include_runway_denial: bool = True
    protect_neutral_infrastructure: bool = True
    weights: StrategicDecisionWeights = field(default_factory=StrategicDecisionWeights)

    def __post_init__(self) -> None:
        if self.max_concurrent_goals < 1:
            raise ValueError("max_concurrent_goals must be at least one")
        if not math.isfinite(self.defense_duration_s) or self.defense_duration_s <= 0:
            raise ValueError("defense_duration_s must be finite and positive")
        if not math.isfinite(self.destroy_required_damage) or not 0 <= self.destroy_required_damage <= 1:
            raise ValueError("destroy_required_damage must be between zero and one")


@dataclass(slots=True, frozen=True)
class StrategicActionSpec:
    """One action/objective tuple before operational planning."""

    candidate_id: str
    coalition: str
    objective: StrategicObjective
    action: StrategicGoalAction | None
    effect: StrategicGoalEffect | None = None
    rejection_code: StrategicDecisionReasonCode | None = None
    rejection_reason: str | None = None


@dataclass(slots=True, frozen=True)
class StrategicDecisionScore:
    """Explainable score components, each normalized to 0..100."""

    strategic_value: float
    urgency: float
    doctrine: float
    operational: float
    confidence: float
    total: float


@dataclass(slots=True, frozen=True)
class StrategicDecision:
    """Final consideration result for one strategic candidate."""

    candidate_id: str
    coalition: str
    objective_id: str
    objective_name: str
    action: StrategicGoalAction | None
    effect: StrategicGoalEffect | None
    disposition: StrategicDecisionDisposition
    reason_code: StrategicDecisionReasonCode
    reason: str
    score: StrategicDecisionScore | None = None
    goal: StrategicGoal | None = None
    plan: OperationalPlan | None = None
    assessment: OperationalPlanAssessment | None = None
    reserved_assets: tuple[tuple[str, int], ...] = ()


@dataclass(slots=True, frozen=True)
class StrategicDecisionPortfolio:
    """One coalition's selected, deferred, and rejected recommendations."""

    coalition: str
    mission_time: float | None
    decisions: tuple[StrategicDecision, ...]
    reserved_assets: tuple[tuple[str, int], ...] = ()
    max_concurrent_goals: int = 1
    existing_open_goal_count: int = 0

    @property
    def selected(self) -> tuple[StrategicDecision, ...]:
        return tuple(item for item in self.decisions if item.disposition is StrategicDecisionDisposition.SELECTED)

    @property
    def deferred(self) -> tuple[StrategicDecision, ...]:
        return tuple(item for item in self.decisions if item.disposition is StrategicDecisionDisposition.DEFERRED)

    @property
    def rejected(self) -> tuple[StrategicDecision, ...]:
        return tuple(item for item in self.decisions if item.disposition is StrategicDecisionDisposition.REJECTED)


@dataclass(slots=True, frozen=True)
class BilateralStrategicRecommendation:
    """Blue and red recommendations derived from one strategic state."""

    mission_generation: int
    mission_time: float | None
    relationship_state: str
    portfolios: tuple[StrategicDecisionPortfolio, ...]

    def coalition(self, coalition: str) -> StrategicDecisionPortfolio:
        normalized = normalize_coalition(coalition)
        for portfolio in self.portfolios:
            if portfolio.coalition == normalized:
                return portfolio
        raise ValueError(f"No strategic recommendation exists for coalition {coalition!r}")


def derive_strategic_action_specs(
    objectives: Iterable[StrategicObjective],
    coalition: str,
    *,
    relationship: CoalitionRelationship,
    config: StrategicDecisionConfig,
    open_goals: Iterable[StrategicGoal] = (),
) -> tuple[StrategicActionSpec, ...]:
    """Apply hard policy gates and return all auditable action candidates."""

    coalition = normalize_coalition(coalition) or ""
    if coalition not in {"blue", "red"}:
        raise ValueError("strategic decisions require coalition blue or red")
    opponent = "red" if coalition == "blue" else "blue"
    open_objectives = {
        goal.objective_id
        for goal in open_goals
        if goal.coalition == coalition
        and goal.status in {StrategicGoalStatus.PLANNED, StrategicGoalStatus.ACTIVE}
    }
    results: list[StrategicActionSpec] = []
    for objective in sorted(objectives, key=lambda item: item.objective_id):
        scope_state = str(objective.metadata.get("scope_state") or "")
        if scope_state == "out_of_scope":
            results.append(_rejected_spec(coalition, objective, None, StrategicDecisionReasonCode.OUT_OF_SCOPE,
                                          "objective is outside the configured strategic scope"))
            continue
        if objective.status is ObjectiveStatus.DESTROYED:
            results.append(_rejected_spec(coalition, objective, None, StrategicDecisionReasonCode.OBJECTIVE_DESTROYED,
                                          "objective is already destroyed"))
            continue
        if objective.objective_id in open_objectives:
            results.append(_rejected_spec(coalition, objective, None, StrategicDecisionReasonCode.DUPLICATE_OPEN_GOAL,
                                          "an open goal already exists for this coalition and objective"))
            continue

        owner = normalize_coalition(objective.owner)
        if owner == coalition:
            if objective.kind is ObjectiveKind.OPSZONE:
                results.append(_permitted_spec(coalition, objective, StrategicGoalAction.DEFEND, relationship))
            else:
                results.append(_rejected_spec(coalition, objective, None, StrategicDecisionReasonCode.FRIENDLY_OBJECTIVE,
                                              "friendly objective has no supported defensive plan type"))
            continue

        if owner not in {opponent, coalition}:
            if objective.kind is ObjectiveKind.OPSZONE:
                results.append(_permitted_spec(coalition, objective, StrategicGoalAction.CAPTURE, relationship))
            elif objective.kind in {ObjectiveKind.AIRBASE, ObjectiveKind.FARP}:
                results.append(_rejected_spec(
                    coalition,
                    objective,
                    StrategicGoalAction.CAPTURE,
                    StrategicDecisionReasonCode.ACTION_NOT_SUPPORTED,
                    "airbase capture requires an associated OPSZONE capture objective",
                ))
            else:
                code = (
                    StrategicDecisionReasonCode.NEUTRAL_PROTECTED
                    if config.protect_neutral_infrastructure
                    else StrategicDecisionReasonCode.TARGET_COMPONENTS_MISSING
                )
                reason = (
                    "neutral infrastructure is protected by strategic policy"
                    if config.protect_neutral_infrastructure
                    else "neutral objective has no supported control action"
                )
                results.append(_rejected_spec(coalition, objective, None, code, reason))
            continue

        if objective.kind is ObjectiveKind.OPSZONE:
            results.append(_permitted_spec(coalition, objective, StrategicGoalAction.CAPTURE, relationship))
            continue
        if objective.kind is ObjectiveKind.AIRBASE:
            results.append(_rejected_spec(
                coalition,
                objective,
                StrategicGoalAction.CAPTURE,
                StrategicDecisionReasonCode.ACTION_NOT_SUPPORTED,
                "airbase capture requires an associated OPSZONE capture objective",
            ))
            if config.include_runway_denial:
                results.append(_permitted_spec(
                    coalition,
                    objective,
                    StrategicGoalAction.DISABLE,
                    relationship,
                    effect=StrategicGoalEffect.DENY_RUNWAY,
                ))
            continue
        if objective.kind is ObjectiveKind.FARP:
            results.append(_rejected_spec(
                coalition,
                objective,
                StrategicGoalAction.CAPTURE,
                StrategicDecisionReasonCode.ACTION_NOT_SUPPORTED,
                "FARP capture requires an associated OPSZONE capture objective",
            ))
            continue

        targets = tuple(component for component in objective.components if component.is_destroy_target)
        if not targets or not bool(objective.metadata.get("targetable", True)):
            results.append(_rejected_spec(
                coalition,
                objective,
                StrategicGoalAction.DESTROY,
                StrategicDecisionReasonCode.TARGET_COMPONENTS_MISSING,
                "objective has no verified targetable DCS components",
            ))
            continue
        results.append(_permitted_spec(coalition, objective, StrategicGoalAction.DESTROY, relationship))
    return tuple(results)


def create_candidate_goal(
    spec: StrategicActionSpec,
    *,
    mission_time: float | None,
    config: StrategicDecisionConfig,
) -> StrategicGoal:
    """Create an unregistered deterministic goal draft for one permitted spec."""

    if spec.action is None or spec.rejection_code is not None:
        raise ValueError("cannot create a strategic goal for a rejected action spec")
    deadline = (
        (mission_time or 0.0) + config.defense_duration_s
        if spec.action is StrategicGoalAction.DEFEND
        else None
    )
    return StrategicGoal(
        goal_id=f"GOAL:RECOMMEND:{spec.candidate_id}",
        name=f"{spec.coalition.title()} {spec.action.value} {spec.objective.name}",
        coalition=spec.coalition,
        action=spec.action,
        objective_id=spec.objective.objective_id,
        priority=spec.objective.priority,
        created_mission_time=mission_time,
        deadline_mission_time=deadline,
        required_damage=(
            config.destroy_required_damage
            if spec.action is StrategicGoalAction.DESTROY
            else None
        ),
        effect=spec.effect,
        metadata={
            "decision_source": "rule_engine:moosebridge.strategic_decision.v1",
            "candidate_id": spec.candidate_id,
        },
    )


def score_strategic_candidate(
    spec: StrategicActionSpec,
    *,
    plan: OperationalPlan,
    picture: TacticalPicture,
    doctrine: CoalitionDoctrine,
    assessment: OperationalPlanAssessment,
    cohorts: Mapping[str, Cohort],
    config: StrategicDecisionConfig,
) -> StrategicDecisionScore:
    """Score an operationally assessed candidate without changing any registry."""

    value = _bounded(spec.objective.strategic_value)
    urgency = _urgency_score(spec, picture)
    doctrine_score = _doctrine_score(spec.action, doctrine)
    operational = _operational_score(plan, assessment, cohorts)
    confidence = _confidence_score(spec.objective)
    weights = config.weights
    total = (
        value * weights.strategic_value
        + urgency * weights.urgency
        + doctrine_score * weights.doctrine
        + operational * weights.operational
        + confidence * weights.confidence
    )
    return StrategicDecisionScore(value, urgency, doctrine_score, operational, confidence, round(total, 3))


def concurrent_plan_reservations(assessment: OperationalPlanAssessment) -> dict[str, int]:
    """Reserve each COHORT's largest simultaneous use in any one plan phase."""

    by_phase: dict[str, dict[str, int]] = {}
    for requirement in assessment.requirements:
        phase = by_phase.setdefault(requirement.phase_id, {})
        for allocation in requirement.allocations:
            phase[allocation.cohort_id] = phase.get(allocation.cohort_id, 0) + allocation.count
    result: dict[str, int] = {}
    for phase in by_phase.values():
        for cohort_id, count in phase.items():
            result[cohort_id] = max(result.get(cohort_id, 0), count)
    return result


def rejected_decision(spec: StrategicActionSpec) -> StrategicDecision:
    """Convert a policy-rejected action spec into a final decision."""

    if spec.rejection_code is None:
        raise ValueError("action spec is not rejected")
    return StrategicDecision(
        candidate_id=spec.candidate_id,
        coalition=spec.coalition,
        objective_id=spec.objective.objective_id,
        objective_name=spec.objective.name,
        action=spec.action,
        effect=spec.effect,
        disposition=StrategicDecisionDisposition.REJECTED,
        reason_code=spec.rejection_code,
        reason=spec.rejection_reason or spec.rejection_code.value,
    )


def strategic_recommendation_to_dict(
    recommendation: BilateralStrategicRecommendation,
) -> dict[str, object]:
    """Return the stable audit payload for one bilateral recommendation."""

    return {
        "schema_version": 1,
        "mission_generation": recommendation.mission_generation,
        "mission_time": recommendation.mission_time,
        "relationship_state": recommendation.relationship_state,
        "portfolios": [
            {
                "coalition": portfolio.coalition,
                "mission_time": portfolio.mission_time,
                "max_concurrent_goals": portfolio.max_concurrent_goals,
                "existing_open_goal_count": portfolio.existing_open_goal_count,
                "reserved_assets": [
                    {"cohort_id": cohort_id, "count": count}
                    for cohort_id, count in portfolio.reserved_assets
                ],
                "decisions": [
                    {
                        "candidate_id": decision.candidate_id,
                        "objective_id": decision.objective_id,
                        "objective_name": decision.objective_name,
                        "action": decision.action.value if decision.action is not None else None,
                        "effect": decision.effect.value if decision.effect is not None else None,
                        "disposition": decision.disposition.value,
                        "reason_code": decision.reason_code.value,
                        "reason": decision.reason,
                        "score": (
                            {
                                "total": decision.score.total,
                                "strategic_value": decision.score.strategic_value,
                                "urgency": decision.score.urgency,
                                "doctrine": decision.score.doctrine,
                                "operational": decision.score.operational,
                                "confidence": decision.score.confidence,
                            }
                            if decision.score is not None
                            else None
                        ),
                        "goal_id": decision.goal.goal_id if decision.goal is not None else None,
                        "plan_id": decision.plan.plan_id if decision.plan is not None else None,
                        "feasible": (
                            decision.assessment.feasible
                            if decision.assessment is not None
                            else None
                        ),
                        "reserved_assets": [
                            {"cohort_id": cohort_id, "count": count}
                            for cohort_id, count in decision.reserved_assets
                        ],
                    }
                    for decision in portfolio.decisions
                ],
            }
            for portfolio in recommendation.portfolios
        ],
    }


def _permitted_spec(
    coalition: str,
    objective: StrategicObjective,
    action: StrategicGoalAction,
    relationship: CoalitionRelationship,
    *,
    effect: StrategicGoalEffect | None = None,
) -> StrategicActionSpec:
    allowed, reason = relationship.allows_goal(action, objective)
    if not allowed:
        return _rejected_spec(
            coalition,
            objective,
            action,
            StrategicDecisionReasonCode.RELATIONSHIP_FORBIDS,
            reason,
            effect=effect,
        )
    return StrategicActionSpec(_candidate_id(coalition, objective, action, effect), coalition, objective, action, effect)


def _rejected_spec(
    coalition: str,
    objective: StrategicObjective,
    action: StrategicGoalAction | None,
    code: StrategicDecisionReasonCode,
    reason: str,
    *,
    effect: StrategicGoalEffect | None = None,
) -> StrategicActionSpec:
    return StrategicActionSpec(
        _candidate_id(coalition, objective, action, effect),
        coalition,
        objective,
        action,
        effect,
        code,
        reason,
    )


def _candidate_id(
    coalition: str,
    objective: StrategicObjective,
    action: StrategicGoalAction | None,
    effect: StrategicGoalEffect | None,
) -> str:
    action_name = action.value if action is not None else "none"
    effect_name = effect.value if effect is not None else "default"
    return f"{coalition}:{action_name}:{effect_name}:{objective.objective_id}"


def _urgency_score(spec: StrategicActionSpec, picture: TacticalPicture) -> float:
    objective = spec.objective
    if objective.contested or objective.status is ObjectiveStatus.CONTESTED:
        return 100.0
    if objective.status in {ObjectiveStatus.DEGRADED, ObjectiveStatus.DISABLED}:
        return 85.0
    if objective.kind is ObjectiveKind.OPSZONE and objective.control_object_id:
        zone = next((item for item in picture.opszones if item.object_id == objective.control_object_id), None)
        if zone is not None:
            radius = max(float(zone.zone_radius or 0.0), 5_000.0) + 20_000.0
            contacts = [
                contact
                for contact in picture.contacts
                if contact.x is not None
                and contact.z is not None
                and zone.x is not None
                and zone.z is not None
                and math.hypot(contact.x - zone.x, contact.z - zone.z) <= radius
            ]
            if contacts:
                maximum_threat = max(float(contact.threat_level or 0.0) for contact in contacts)
                return min(100.0, 50.0 + maximum_threat * 5.0 + len(contacts) * 3.0)
    if spec.action is StrategicGoalAction.DEFEND:
        return 35.0
    if normalize_coalition(objective.owner) in {"blue", "red"}:
        return 55.0
    return 30.0


def _doctrine_score(action: StrategicGoalAction | None, doctrine: CoalitionDoctrine) -> float:
    if action in {StrategicGoalAction.DEFEND, StrategicGoalAction.PROTECT}:
        return doctrine.defense_bias * 100.0
    return (doctrine.offense_bias * 0.70 + doctrine.risk_tolerance * 0.30) * 100.0


def _operational_score(
    plan: OperationalPlan,
    assessment: OperationalPlanAssessment,
    cohorts: Mapping[str, Cohort],
) -> float:
    requirements = {
        (phase.phase_id, intent.intent_id, requirement.requirement_id): (intent, requirement)
        for phase in plan.phases
        for intent in phase.intents
        for requirement in intent.asset_requirements
    }
    required = [item for item in assessment.requirements if item.required_count > 0]
    if not required:
        return 50.0
    requirement_scores: list[float] = []
    for item in required:
        performances: list[float] = []
        etas: list[float] = []
        intent, requirement = requirements.get(
            (item.phase_id, item.intent_id, item.requirement_id),
            (None, None),
        )
        mission_types = (
            (requirement.mission_types or intent.auftrag_types)
            if requirement is not None and intent is not None
            else ()
        )
        for allocation in item.allocations:
            cohort = cohorts.get(allocation.cohort_id)
            if cohort is None:
                continue
            performances.extend(
                value
                for mission_type in mission_types
                if (value := cohort.mission_performance_for(mission_type)) is not None
            )
        metadata_sources = (
            tuple(source for source in (intent.metadata, requirement.metadata) if source is not None)
            if intent is not None and requirement is not None
            else ()
        )
        allocated_ids = {allocation.cohort_id for allocation in item.allocations}
        for metadata in metadata_sources:
            assignments = metadata.get("mission_assignments")
            if isinstance(assignments, list):
                etas.extend(
                    float(assignment["estimated_time_to_effect_s"])
                    for assignment in assignments
                    if isinstance(assignment, Mapping)
                    and assignment.get("cohort_id") in allocated_ids
                    and isinstance(assignment.get("estimated_time_to_effect_s"), (int, float))
                )
            direct_eta = metadata.get("estimated_time_to_effect_s")
            if isinstance(direct_eta, (int, float)):
                etas.append(float(direct_eta))
        performance = max(performances, default=50.0)
        response = 50.0 if not etas else 100.0 / (1.0 + min(etas) / 900.0)
        requirement_scores.append(performance * 0.70 + response * 0.30)
    return _bounded(sum(requirement_scores) / len(requirement_scores))


def _confidence_score(objective: StrategicObjective) -> float:
    if objective.components and str(objective.metadata.get("dcs_verification_state") or "") == "represented":
        return 100.0
    if objective.kind is ObjectiveKind.OPSZONE:
        return 95.0
    if objective.kind in {ObjectiveKind.AIRBASE, ObjectiveKind.FARP}:
        return 90.0
    if objective.components:
        return 80.0
    return 55.0


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


__all__ = [
    "STRATEGIC_DECISION_AUDIT_TYPE",
    "BilateralStrategicRecommendation",
    "StrategicActionSpec",
    "StrategicDecision",
    "StrategicDecisionConfig",
    "StrategicDecisionDisposition",
    "StrategicDecisionPortfolio",
    "StrategicDecisionReasonCode",
    "StrategicDecisionScore",
    "StrategicDecisionWeights",
    "concurrent_plan_reservations",
    "create_candidate_goal",
    "derive_strategic_action_specs",
    "rejected_decision",
    "score_strategic_candidate",
    "strategic_recommendation_to_dict",
]
