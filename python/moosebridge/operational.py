"""Operational planning between strategic goals and executable MOOSE AUFTRAGs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Iterable

from .auftrag_specs import canonical_mission_type, get_auftrag_type_spec, platform_categories_match
from .legions import Cohort, Legion
from .strategic import StrategicGoal, StrategicGoalRegistry, normalize_coalition


class OperationalPosture(str, Enum):
    """How aggressively a plan should commit available forces."""

    ECONOMY = "economy"
    BALANCED = "balanced"
    OVERWHELMING = "overwhelming"


class OperationalPlanStatus(str, Enum):
    """Lifecycle state of an operational plan."""

    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    EXECUTING = "executing"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanSourceType(str, Enum):
    """Origin of an operational plan proposal."""

    OPERATOR = "operator"
    RULE_ENGINE = "rule_engine"
    LLM = "llm"
    IMPORT = "import"


@dataclass(slots=True, frozen=True)
class OperationalPlanProvenance:
    """Optional origin and rationale for one operational plan proposal."""

    source_type: PlanSourceType
    source_id: str
    picture_mission_time: float | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", PlanSourceType(self.source_type))
        source_id = self.source_id.strip()
        if not source_id:
            raise ValueError("operational plan provenance requires source_id")
        object.__setattr__(self, "source_id", source_id)
        if self.picture_mission_time is not None and (
            not math.isfinite(self.picture_mission_time) or self.picture_mission_time < 0
        ):
            raise ValueError("picture_mission_time must be finite and non-negative")
        object.__setattr__(self, "rationale", self.rationale.strip() if self.rationale else None)


@dataclass(slots=True, frozen=True)
class PlanProposalIssue:
    """Structured uncertainty or limitation attached by a plan proposer."""

    severity: str
    code: str
    message: str
    reference_id: str | None = None

    def __post_init__(self) -> None:
        severity = self.severity.strip().lower()
        code = self.code.strip()
        message = self.message.strip()
        if severity not in {"warning", "error"}:
            raise ValueError("plan proposal issue severity must be warning or error")
        if not code or not message:
            raise ValueError("plan proposal issue requires code and message")
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "reference_id", self.reference_id.strip() if self.reference_id else None)


class PlanPhaseStatus(str, Enum):
    """Lifecycle state of one operational plan phase."""

    PENDING = "pending"
    READY = "ready"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class AssetRole(str, Enum):
    """Operational role fulfilled by one or more asset groups."""

    COMBAT = "combat"
    AIR_SUPERIORITY = "air_superiority"
    SEAD = "sead"
    FIRES = "fires"
    RECONNAISSANCE = "reconnaissance"
    SUPPORT = "support"
    LOGISTICS = "logistics"
    TRANSPORT = "transport"
    AIR_DEFENSE = "air_defense"
    COMMAND_CONTROL = "command_control"


@dataclass(slots=True, frozen=True)
class AssetRequirement:
    """Capability and quantity requested for one mission intent."""

    requirement_id: str
    role: AssetRole
    min_count: int = 1
    max_count: int | None = None
    mission_types: tuple[str, ...] = ()
    performer_categories: tuple[str, ...] = ()
    preferred_legion_ids: tuple[str, ...] = ()
    allowed_legion_ids: tuple[str, ...] = ()
    allowed_cohort_ids: tuple[str, ...] = ()
    require_payload: bool = False
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        requirement_id = self.requirement_id.strip()
        if not requirement_id:
            raise ValueError("requirement_id must not be empty")
        if self.min_count < 0:
            raise ValueError("asset min_count must be non-negative")
        maximum = self.min_count if self.max_count is None else self.max_count
        if maximum < self.min_count:
            raise ValueError("asset max_count must be greater than or equal to min_count")
        mission_types = tuple(dict.fromkeys(canonical_mission_type(item) for item in self.mission_types if item.strip()))
        categories = tuple(dict.fromkeys(item.strip().upper() for item in self.performer_categories if item.strip()))
        object.__setattr__(self, "requirement_id", requirement_id)
        object.__setattr__(self, "role", AssetRole(self.role))
        object.__setattr__(self, "max_count", maximum)
        object.__setattr__(self, "mission_types", mission_types)
        object.__setattr__(self, "performer_categories", categories)
        object.__setattr__(self, "preferred_legion_ids", tuple(dict.fromkeys(self.preferred_legion_ids)))
        object.__setattr__(self, "allowed_legion_ids", tuple(dict.fromkeys(self.allowed_legion_ids)))
        object.__setattr__(self, "allowed_cohort_ids", tuple(dict.fromkeys(self.allowed_cohort_ids)))


@dataclass(slots=True, frozen=True)
class MissionIntent:
    """Desired operational effect that can be implemented by an AUFTRAG type."""

    intent_id: str
    name: str
    auftrag_types: tuple[str, ...]
    asset_requirements: tuple[AssetRequirement, ...]
    target_object_id: str | None = None
    required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        intent_id = self.intent_id.strip()
        name = self.name.strip()
        if not intent_id or not name:
            raise ValueError("mission intent id and name must not be empty")
        auftrag_types = tuple(dict.fromkeys(canonical_mission_type(item) for item in self.auftrag_types if item.strip()))
        if not auftrag_types:
            raise ValueError("mission intent requires at least one AUFTRAG type")
        requirements = tuple(self.asset_requirements)
        if not requirements:
            raise ValueError("mission intent requires at least one asset requirement")
        requirement_ids = [item.requirement_id for item in requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("mission intent asset requirement ids must be unique")
        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "auftrag_types", auftrag_types)
        object.__setattr__(self, "asset_requirements", requirements)
        object.__setattr__(self, "target_object_id", self.target_object_id.strip() if self.target_object_id else None)


@dataclass(slots=True)
class PlanPhase:
    """Ordered collection of mission intents with explicit dependencies."""

    phase_id: str
    name: str
    intents: tuple[MissionIntent, ...]
    depends_on: tuple[str, ...] = ()
    status: PlanPhaseStatus = PlanPhaseStatus.PENDING
    optional: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.phase_id = self.phase_id.strip()
        self.name = self.name.strip()
        self.intents = tuple(self.intents)
        self.depends_on = tuple(dict.fromkeys(self.depends_on))
        self.status = PlanPhaseStatus(self.status)
        if not self.phase_id or not self.name:
            raise ValueError("plan phase id and name must not be empty")
        if not self.intents:
            raise ValueError("plan phase requires at least one mission intent")
        intent_ids = [intent.intent_id for intent in self.intents]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("mission intent ids must be unique within a phase")


@dataclass(slots=True)
class OperationalPlan:
    """Human-reviewable operational approach for one strategic goal."""

    plan_id: str
    name: str
    goal_id: str
    coalition: str
    phases: tuple[PlanPhase, ...]
    posture: OperationalPosture = OperationalPosture.BALANCED
    status: OperationalPlanStatus = OperationalPlanStatus.DRAFT
    created_mission_time: float | None = None
    validated_mission_time: float | None = None
    approved_mission_time: float | None = None
    approved_by: str | None = None
    approved_client_id: str | None = None
    approval_reason: str | None = None
    provenance: OperationalPlanProvenance | None = None
    proposal_issues: tuple[PlanProposalIssue, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.plan_id = self.plan_id.strip()
        self.name = self.name.strip()
        self.goal_id = self.goal_id.strip()
        self.coalition = normalize_coalition(self.coalition) or ""
        self.phases = tuple(self.phases)
        self.posture = OperationalPosture(self.posture)
        self.status = OperationalPlanStatus(self.status)
        self.proposal_issues = tuple(self.proposal_issues)
        if not self.plan_id or not self.name or not self.goal_id:
            raise ValueError("plan id, name and goal_id must not be empty")
        if self.coalition not in {"blue", "red"}:
            raise ValueError("operational plans require coalition blue or red")
        if not self.phases:
            raise ValueError("operational plan requires at least one phase")
        phase_ids = [phase.phase_id for phase in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("operational plan phase ids must be unique")
        known: set[str] = set()
        for phase in self.phases:
            unknown = set(phase.depends_on) - known
            if unknown:
                raise ValueError(f"phase {phase.phase_id} has unknown or forward dependencies: {sorted(unknown)}")
            known.add(phase.phase_id)
        for field_name in ("created_mission_time", "validated_mission_time", "approved_mission_time"):
            value = getattr(self, field_name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{field_name} must be finite and non-negative")
        self.approved_by = self.approved_by.strip() if self.approved_by else None
        self.approved_client_id = self.approved_client_id.strip() if self.approved_client_id else None
        self.approval_reason = self.approval_reason.strip() if self.approval_reason else None


@dataclass(slots=True, frozen=True)
class CohortAllocation:
    """Provisional minimum asset allocation used for feasibility analysis."""

    cohort_id: str
    legion_id: str
    count: int


@dataclass(slots=True, frozen=True)
class RequirementAssessment:
    """Feasibility result for one asset requirement."""

    phase_id: str
    intent_id: str
    requirement_id: str
    required_count: int
    available_count: int
    candidate_cohort_ids: tuple[str, ...]
    allocations: tuple[CohortAllocation, ...]
    feasible: bool
    shortfall: int


@dataclass(slots=True, frozen=True)
class PlanValidationIssue:
    """One human-readable plan validation finding."""

    severity: str
    code: str
    message: str
    reference_id: str | None = None


@dataclass(slots=True, frozen=True)
class OperationalPlanAssessment:
    """Structural and force-availability assessment for an operational plan."""

    plan_id: str
    feasible: bool
    requirements: tuple[RequirementAssessment, ...]
    issues: tuple[PlanValidationIssue, ...]

    @property
    def errors(self) -> tuple[PlanValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[PlanValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")


class OperationalPlanRegistry:
    """Runtime plans and conservative COHORT-based feasibility assessments."""

    def __init__(self, goals: StrategicGoalRegistry) -> None:
        self.goals = goals
        self._plans: dict[str, OperationalPlan] = {}
        self._assessments: dict[str, OperationalPlanAssessment] = {}

    def add(self, plan: OperationalPlan, *, replace: bool = False) -> OperationalPlan:
        goal = self.goals.get(plan.goal_id)
        if goal is None:
            raise ValueError(f"Unknown strategic goal: {plan.goal_id}")
        if goal.coalition != plan.coalition:
            raise ValueError("operational plan coalition must match its strategic goal")
        if plan.plan_id in self._plans and not replace:
            raise ValueError(f"Operational plan already exists: {plan.plan_id}")
        self._plans[plan.plan_id] = plan
        self._assessments.pop(plan.plan_id, None)
        return plan

    def get(self, plan_id: str) -> OperationalPlan | None:
        return self._plans.get(plan_id)

    def all(self) -> tuple[OperationalPlan, ...]:
        return tuple(self._plans[key] for key in sorted(self._plans))

    def clear(self) -> None:
        """Discard all mission-scoped plans and feasibility assessments."""

        self._plans.clear()
        self._assessments.clear()

    def assessment(self, plan_id: str) -> OperationalPlanAssessment | None:
        return self._assessments.get(plan_id)

    def invalidate(self, plan: OperationalPlan | str) -> None:
        """Discard a stale feasibility assessment after a plan was changed."""

        item = self._require(plan)
        self._assessments.pop(item.plan_id, None)

    def validate(
        self,
        plan: OperationalPlan | str,
        *,
        legions: Iterable[Legion],
        cohorts: Iterable[Cohort],
        mission_time: float | None = None,
        phase_ids: Iterable[str] | None = None,
        update_plan: bool = True,
    ) -> OperationalPlanAssessment:
        item = self._require(plan)
        selected_phases = set(phase_ids) if phase_ids is not None else None
        goal = self.goals.get(item.goal_id)
        issues: list[PlanValidationIssue] = []
        if goal is None:
            issues.append(PlanValidationIssue("error", "goal_missing", "Referenced strategic goal no longer exists", item.goal_id))
        elif goal.coalition != item.coalition:
            issues.append(PlanValidationIssue("error", "coalition_mismatch", "Plan and goal coalitions differ", item.goal_id))

        coalition_legions = {
            legion.object_id: legion
            for legion in legions
            if normalize_coalition(legion.coalition or legion.coalition_name) == item.coalition
        }
        coalition_cohorts = [cohort for cohort in cohorts if cohort.legion_id in coalition_legions]
        results: list[RequirementAssessment] = []

        for phase in item.phases:
            if phase.status is PlanPhaseStatus.COMPLETED or (
                selected_phases is not None and phase.phase_id not in selected_phases
            ):
                continue
            remaining = {cohort.object_id: max(0, cohort.available_asset_count or 0) for cohort in coalition_cohorts}
            for cohort in coalition_cohorts:
                if cohort.available_asset_count is None:
                    issues.append(
                        PlanValidationIssue(
                            "warning",
                            "unknown_availability",
                            "COHORT available_asset_count is unknown and was treated as zero",
                            cohort.object_id,
                        )
                    )
            for intent in phase.intents:
                valid_intent_types = tuple(mission for mission in intent.auftrag_types if get_auftrag_type_spec(mission) is not None)
                invalid_types = set(intent.auftrag_types) - set(valid_intent_types)
                for mission_type in sorted(invalid_types):
                    issues.append(
                        PlanValidationIssue("error", "unknown_auftrag_type", f"Unknown AUFTRAG type {mission_type}", intent.intent_id)
                    )
                for requirement in intent.asset_requirements:
                    mission_types = requirement.mission_types or valid_intent_types
                    candidates = [
                        cohort
                        for cohort in coalition_cohorts
                        if _cohort_matches_requirement(cohort, requirement, mission_types)
                    ]
                    preferred = set(requirement.preferred_legion_ids)
                    cohort_priority = {
                        cohort_id: index for index, cohort_id in enumerate(requirement.allowed_cohort_ids)
                    }
                    candidates.sort(
                        key=lambda cohort: (
                            cohort_priority.get(cohort.object_id, len(cohort_priority)),
                            0 if cohort.legion_id in preferred else 1,
                            -max((cohort.mission_performance_for(mission) or 0 for mission in mission_types), default=0),
                            cohort.object_id,
                        )
                    )
                    available = sum(remaining.get(cohort.object_id, 0) for cohort in candidates)
                    needed = requirement.min_count
                    allocations: list[CohortAllocation] = []
                    for cohort in candidates:
                        if needed <= 0:
                            break
                        capacity = remaining.get(cohort.object_id, 0)
                        assigned = min(capacity, needed)
                        if assigned <= 0:
                            continue
                        allocations.append(CohortAllocation(cohort.object_id, cohort.legion_id or "", assigned))
                        remaining[cohort.object_id] = capacity - assigned
                        needed -= assigned
                    feasible = needed == 0
                    results.append(
                        RequirementAssessment(
                            phase_id=phase.phase_id,
                            intent_id=intent.intent_id,
                            requirement_id=requirement.requirement_id,
                            required_count=requirement.min_count,
                            available_count=available,
                            candidate_cohort_ids=tuple(cohort.object_id for cohort in candidates),
                            allocations=tuple(allocations),
                            feasible=feasible,
                            shortfall=needed,
                        )
                    )
                    if not feasible and (intent.required and not phase.optional):
                        issues.append(
                            PlanValidationIssue(
                                "error",
                                "asset_shortfall",
                                f"Requires {requirement.min_count} asset group(s), shortfall {needed}",
                                requirement.requirement_id,
                            )
                        )
                    elif not feasible:
                        issues.append(
                            PlanValidationIssue(
                                "warning",
                                "optional_asset_shortfall",
                                f"Optional requirement shortfall {needed}",
                                requirement.requirement_id,
                            )
                        )

        feasible = not any(issue.severity == "error" for issue in issues)
        assessment = OperationalPlanAssessment(item.plan_id, feasible, tuple(results), tuple(issues))
        if update_plan:
            self._assessments[item.plan_id] = assessment
            item.status = OperationalPlanStatus.VALIDATED if feasible else OperationalPlanStatus.DRAFT
            item.validated_mission_time = mission_time if feasible else None
        return assessment

    def assess_phase(
        self,
        plan: OperationalPlan | str,
        phase_id: str,
        *,
        legions: Iterable[Legion],
        cohorts: Iterable[Cohort],
        mission_time: float | None = None,
    ) -> OperationalPlanAssessment:
        """Assess one immediate phase without changing plan approval state."""

        item = self._require(plan)
        if not any(phase.phase_id == phase_id for phase in item.phases):
            raise ValueError(f"Unknown operational plan phase: {phase_id}")
        return self.validate(
            item,
            legions=legions,
            cohorts=cohorts,
            mission_time=mission_time,
            phase_ids=(phase_id,),
            update_plan=False,
        )

    def approve(
        self,
        plan: OperationalPlan | str,
        *,
        mission_time: float | None = None,
        approved_by: str = "operator",
        approved_client_id: str | None = None,
        reason: str | None = None,
    ) -> OperationalPlan:
        """Approve a feasible plan without creating or assigning AUFTRAGs."""

        item = self._require(plan)
        assessment = self.assessment(item.plan_id)
        if item.status is not OperationalPlanStatus.VALIDATED or assessment is None or not assessment.feasible:
            raise ValueError("only a validated feasible operational plan can be approved")
        approved_by = approved_by.strip()
        if not approved_by:
            raise ValueError("approved_by must not be empty")
        item.status = OperationalPlanStatus.APPROVED
        item.approved_mission_time = mission_time
        item.approved_by = approved_by
        item.approved_client_id = approved_client_id.strip() if approved_client_id and approved_client_id.strip() else None
        item.approval_reason = reason.strip() if reason and reason.strip() else None
        return item

    def _require(self, plan: OperationalPlan | str) -> OperationalPlan:
        plan_id = plan.plan_id if isinstance(plan, OperationalPlan) else plan
        item = self.get(plan_id)
        if item is None:
            raise KeyError(f"Unknown operational plan: {plan_id}")
        return item


def _cohort_matches_requirement(
    cohort: Cohort,
    requirement: AssetRequirement,
    mission_types: tuple[str, ...],
) -> bool:
    if requirement.allowed_legion_ids and cohort.legion_id not in requirement.allowed_legion_ids:
        return False
    if requirement.allowed_cohort_ids and cohort.object_id not in requirement.allowed_cohort_ids:
        return False
    if requirement.performer_categories and not platform_categories_match(
        cohort.performer_categories,
        requirement.performer_categories,
    ):
        return False
    supported = tuple(mission for mission in mission_types if mission in cohort.mission_type_keys)
    if not supported:
        return False
    if requirement.require_payload and not any(cohort.has_payload_for(mission) is True for mission in supported):
        return False
    return True
