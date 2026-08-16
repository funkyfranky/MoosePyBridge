"""Human-readable diagnostics for MooseBridge SDK state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING

from .capabilities import (
    CapabilityReadiness,
    GroupCapabilities,
    GroupInfluence,
    InfluenceReadiness,
    UnitCapabilities,
    UnitInfluence,
)
from .diplomacy import CoalitionDoctrine, CoalitionRelationship
from .legions import Cohort, Commander, Legion
from .intelligence import InformationRequirement
from .models import Auftrag, Intel, IntelCluster, IntelContact
from .operational import OperationalPlan, OperationalPlanAssessment
from .operational_execution import (
    OperationalPlanAbortResult,
    OperationalPlanExecution,
    OperationalPlanReconciliation,
    PlanMissionStatus,
)
from .pictures import GlobalPicture, PictureValidationIssue
from .recon import ReconOutcome
from .sensor_ranges import SensorRangeProfile
from .strategic import GoalCondition, StrategicGoal
from .strategic_feedback import StrategicFeedbackDecision, StrategicFeedbackEvent
from .strategic_selection import StrategicGoalPortfolio
from .strategic_scope import StrategicTerritoryScope
from .strategic_objectives import StrategicObjectiveGenerationResult
from .strategic_goals import StrategicGoalGenerationResult
from .weapon_ranges import WeaponRangeProfile

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


def _text(value: object, default: str = "-") -> str:
    return str(value) if value not in (None, "") else default


def format_strategic_scope(scope: StrategicTerritoryScope) -> str:
    """Return concise mission-scope geometry and validation diagnostics."""

    counts = scope.counts()
    lines = [
        (
            f"Strategic scope territories={counts['territories']} valid={counts['valid']} "
            f"errors={counts['errors']} warnings={counts['warnings']} "
            f"red_blue_overlap={float(counts['overlap_area_m2']) / 1_000_000:.3f}km2"
        ),
        (
            f"  area blue={scope.blue.area / 1_000_000:.1f}km2 "
            f"red={scope.red.area / 1_000_000:.1f}km2 "
            f"neutral={scope.neutral.area / 1_000_000:.1f}km2 "
            f"contested={scope.contested.area / 1_000_000:.3f}km2"
        ),
    ]
    lines.extend(f"  {issue.severity.upper()} {issue.code}: {issue.message}" for issue in scope.issues)
    return "\n".join(lines)


def format_strategic_objective_generation(
    result: StrategicObjectiveGenerationResult,
    *,
    exclusion_limit: int = 20,
) -> str:
    """Return a compact audit of automatic objective admission."""

    contested = result.counts_by_scope.get("contested", 0)
    lines = [
        (
            f"Strategic objective generation candidates={result.candidate_count} "
            f"generated={len(result.objectives)} excluded={len(result.exclusions)}"
        ),
        (
            f"  out_of_scope={result.out_of_scope_count} "
            f"below_threshold={result.below_threshold_count} "
            f"dcs_verification={result.verification_exclusion_count} "
            f"category_scope_limit={result.category_scope_limit_count} contested={contested}"
        ),
    ]
    scope_counts = ", ".join(
        f"{scope}={count}" for scope, count in result.counts_by_scope.items() if count
    ) or "none"
    owner_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    for objective in result.objectives:
        owner = objective.owner or "unassigned"
        owner_counts[owner] = owner_counts.get(owner, 0) + 1
        kind = objective.kind.value
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    owners = ", ".join(f"{key}={value}" for key, value in sorted(owner_counts.items())) or "none"
    kinds = ", ".join(f"{key}={value}" for key, value in sorted(kind_counts.items())) or "none"
    lines.extend((f"  scope: {scope_counts}", f"  owners: {owners}", f"  kinds: {kinds}"))
    for item in result.exclusions[:max(0, exclusion_limit)]:
        scope = f" scope={item.scope_state.value}" if item.scope_state is not None else ""
        lines.append(f"  EXCLUDED {item.object_id}: {item.reason}{scope}")
    remaining = len(result.exclusions) - max(0, exclusion_limit)
    if remaining > 0:
        lines.append(f"  ... {remaining} more exclusion(s)")
    return "\n".join(lines)


def format_strategic_goal_generation(
    result: StrategicGoalGenerationResult,
    *,
    rejection_limit: int = 20,
) -> str:
    """Return a compact audit of coalition-specific goal derivation."""

    counts: dict[str, int] = {}
    for goal in result.goals:
        counts[goal.action.value] = counts.get(goal.action.value, 0) + 1
    actions = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
    lines = [
        (
            f"Strategic goal generation coalition={result.coalition} "
            f"evaluated={len(result.decisions)} generated={len(result.goals)} "
            f"rejected={len(result.rejected)}"
        ),
        f"  actions: {actions}",
    ]
    for goal in result.goals:
        lines.append(
            f"  GENERATED {goal.goal_id} objective={goal.objective_id} "
            f"action={goal.action.value} priority={goal.priority:g}"
        )
    for item in result.rejected[:max(0, rejection_limit)]:
        action = item.action.value if item.action is not None else "none"
        lines.append(f"  SKIPPED {item.objective_id} action={action}: {item.reason}")
    remaining = len(result.rejected) - max(0, rejection_limit)
    if remaining > 0:
        lines.append(f"  ... {remaining} more skipped decision(s)")
    return "\n".join(lines)


def format_strategic_feedback(event: StrategicFeedbackEvent) -> str:
    """Return one readable strategic feedback event."""

    lines = [
        f"{event.plan_id or event.goal_id or event.reference_id or 'STRATEGY'} {event.event}",
        (
            f"  source={event.source} mission_time={_text(event.mission_time)} "
            f"coalition={_text(event.coalition)} goal={_text(event.goal_id)}"
        ),
    ]
    if "feasible" in event.details:
        lines.append(f"  feasible={event.details['feasible']} reason={_text(event.details.get('reason'))}")
    allocations = event.details.get("allocations")
    if isinstance(allocations, list) and allocations:
        lines.append(
            "  allocations: "
            + ", ".join(
                f"{item.get('requirement_id')}={item.get('cohort_id')} x{item.get('count')}"
                for item in allocations
                if isinstance(item, Mapping)
            )
        )
    issues = event.details.get("issues")
    if isinstance(issues, list) and issues:
        lines.append(
            "  issues: "
            + ", ".join(
                f"{item.get('severity')}:{item.get('code')}"
                for item in issues
                if isinstance(item, Mapping)
            )
        )
    return "\n".join(lines)


def format_strategic_feedback_decision(decision: StrategicFeedbackDecision) -> str:
    """Return one concise policy decision."""

    reference = decision.plan_id or decision.goal_id or "STRATEGY"
    mode = "automatic" if decision.automatic else "advisory"
    return f"{reference} action={decision.action.value} mode={mode} reason={decision.reason}"


def format_strategic_goal_portfolio(portfolio: StrategicGoalPortfolio) -> str:
    """Return a readable concurrent strategic-goal selection."""

    lines = [
        f"Strategic portfolio coalition={portfolio.coalition} selected={len(portfolio.selected)} "
        f"deferred={len(portfolio.deferred)} mission_time={_text(portfolio.mission_time)}"
    ]
    for item in portfolio.decisions:
        status = "SELECTED" if item.selected else "DEFERRED"
        lines.append(
            f"  {status} {item.goal_id} plan={item.plan_id} priority={item.goal_priority:g} "
            f"objective_priority={item.objective_priority:g} value={item.strategic_value:g} "
            f"doctrine_tier={item.doctrine_tier}"
        )
        lines.append(f"    reason={item.reason}")
        if item.reserved_assets:
            lines.append(
                "    reserves="
                + ", ".join(f"{cohort_id} x{count}" for cohort_id, count in item.reserved_assets)
            )
    return "\n".join(lines)


def format_relationship(relationship: CoalitionRelationship, *, incident_limit: int = 10) -> str:
    """Return compact shared relationship and escalation diagnostics."""

    if incident_limit < 0:
        raise ValueError("incident_limit must be non-negative")

    pending = relationship.pending_transition
    lines = [
        f"Relationship {relationship.coalition_a}/{relationship.coalition_b} "
        f"state={relationship.state.value} escalation={relationship.escalation_score:.1f} "
        f"automatic={relationship.automatic_transitions} incidents={len(relationship.incidents)}",
        (
            f"  responsibility: blue={relationship.responsibility('blue'):.1f} "
            f"red={relationship.responsibility('red'):.1f}"
        ),
    ]
    if pending is not None:
        lines.append(
            f"  pending={pending.from_state.value}->{pending.to_state.value} "
            f"automatic={pending.automatic} reason={pending.reason}"
        )
    incidents = relationship.incidents[-incident_limit:] if incident_limit else []
    if incidents:
        hidden = len(relationship.incidents) - len(incidents)
        lines.append(f"  incidents (latest {len(incidents)}{f', {hidden} older' if hidden else ''}):")
        for incident in incidents:
            points = (
                relationship.incident_weights.get(incident.incident_type, 0.0)
                * incident.confidence
                * incident.multiplier
            )
            mission_time = f"{incident.mission_time:.1f}" if incident.mission_time is not None else "-"
            lines.append(
                f"    t={mission_time} {incident.incident_type.value} points={points:.1f} "
                f"actor={incident.actor_coalition} target={incident.target_coalition} "
                f"ref={incident.reference_id or '-'}"
            )
    return "\n".join(lines)


def format_coalition_doctrine(coalition: str, doctrine: CoalitionDoctrine) -> str:
    """Return compact coalition-doctrine diagnostics."""

    return (
        f"{coalition} doctrine={doctrine.preset.value} defense={doctrine.defense_bias:.2f} "
        f"offense={doctrine.offense_bias:.2f} escalation_tolerance={doctrine.escalation_tolerance:.2f} "
        f"risk={doctrine.risk_tolerance:.2f} preservation={doctrine.force_preservation:.2f}"
    )


def format_recon_outcome(outcome: ReconOutcome) -> str:
    """Return a compact readable RECON assessment."""

    first_delay = f"{outcome.first_intelligence_delay:.1f}s" if outcome.first_intelligence_delay is not None else "-"
    lines = [
        f"{outcome.auftrag_id} RECON outcome intel={outcome.intel_id}",
        (
            f"  MOOSE success={outcome.mission_outcome.success} contacts={len(outcome.observations)} "
            f"assigned_contacts={outcome.assigned_asset_contact_count} "
            f"new={outcome.new_contact_count} reacquired={outcome.reacquired_contact_count} "
            f"lost={outcome.lost_contact_count} first_delay={first_delay}"
        ),
        (
            f"  threat max={outcome.maximum_threat:.1f} total={outcome.total_threat:.1f} "
            f"assets={len(outcome.assigned_group_ids)} requirement_satisfied={outcome.requirement_satisfied} "
            f"history_complete={outcome.event_history_complete}"
        ),
    ]
    if outcome.assigned_group_ids:
        lines.append(f"  assigned: {', '.join(outcome.assigned_group_ids)}")
    if outcome.spatial_coverage:
        spatial = outcome.spatial_coverage
        area = f"{spatial.area_coverage_ratio:.1%}" if spatial.area_coverage_ratio is not None else "-"
        components = (
            f"{spatial.component_coverage_ratio:.1%}"
            if spatial.component_coverage_ratio is not None
            else "-"
        )
        lines.append(
            f"  spatial potential_area={area} components={components} "
            f"samples={spatial.sample_count} sufficient={spatial.sufficient}"
        )
    for item in outcome.observations:
        flags = []
        if item.new_contact:
            flags.append("new")
        if item.reacquired:
            flags.append("reacquired")
        if item.lost_at_end:
            flags.append("lost")
        if item.detected_during_executing:
            flags.append("executing")
        lines.append(
            f"  {item.contact_id} target={_text(item.target_object_id)} "
            f"recce={_text(item.recce_unit_id)} threat={item.threat_level:.1f} "
            f"detections={item.detection_count} source={'assigned' if item.assigned_asset else 'coalition'} "
            f"flags={','.join(flags) or '-'}"
        )
    if outcome.unknown_relevant_target_ids:
        lines.append(f"  relevant unknown: {', '.join(outcome.unknown_relevant_target_ids)}")
    if outcome.lost_relevant_target_ids:
        lines.append(f"  relevant lost: {', '.join(outcome.lost_relevant_target_ids)}")
    if not outcome.event_history_complete:
        lines.append("  WARNING: daemon event history was incomplete; assessment is partial")
    return "\n".join(lines)


def format_information_requirement(requirement: InformationRequirement) -> str:
    """Return a compact readable coalition information requirement."""

    lines = [
        (
            f"{requirement.requirement_id} intel={requirement.intel_id} "
            f"status={requirement.status.value} match={requirement.match.value} "
            f"priority={requirement.priority:g}"
        ),
        f"  targets: {', '.join(requirement.target_object_ids)}",
    ]
    if requirement.observed_target_ids:
        lines.append(f"  observed: {', '.join(requirement.observed_target_ids)}")
    if requirement.missing_target_ids:
        lines.append(f"  missing: {', '.join(requirement.missing_target_ids)}")
    if requirement.lost_target_ids:
        lines.append(f"  lost: {', '.join(requirement.lost_target_ids)}")
    return "\n".join(lines)


def format_capability_readiness(capability: CapabilityReadiness) -> str:
    """Return one readable capability readiness line."""

    roles = ",".join(role.value for role in capability.contributing_roles) or "-"
    return (
        f"{capability.kind.value:<18} "
        f"base={capability.base_power:5.2f} "
        f"ammo={capability.ammo_readiness:6.1%} "
        f"health={capability.health_readiness:6.1%} "
        f"effective={capability.effective_power:5.2f} "
        f"roles={roles}"
    )


def format_unit_capabilities(profile: UnitCapabilities) -> str:
    """Return a readable capability report for one unit."""

    lines = [f"{profile.unit_id} type={_text(profile.dcs_type)}"]
    lines.extend(f"  {format_capability_readiness(capability)}" for capability in profile.capabilities)
    return "\n".join(lines)


def format_group_capabilities(profile: GroupCapabilities) -> str:
    """Return a readable aggregated capability report for one group."""

    lines = [f"{profile.group_id} capabilities units={len(profile.units)}"]
    lines.extend(f"  {format_capability_readiness(capability)}" for capability in profile.capabilities)
    return "\n".join(lines)


def format_influence_readiness(influence: InfluenceReadiness) -> str:
    """Return one readable tactical influence line."""

    roles = ",".join(role.value for role in influence.contributing_roles) or "-"
    range_text = (
        f" range={influence.minimum_range_m / 1000:.3f}-{influence.maximum_range_m / 1000:.3f}km"
        if influence.maximum_range_m > 0 else ""
    )
    return (
        f"{influence.kind.value:<14} "
        f"base={influence.base_power:5.2f} "
        f"ammo={influence.ammo_readiness:6.1%} "
        f"health={influence.health_readiness:6.1%} "
        f"effective={influence.effective_power:5.2f}"
        f"{range_text} roles={roles}"
    )


def format_unit_influence(profile: UnitInfluence) -> str:
    """Return separated tactical influences for one unit."""

    lines = [f"{profile.unit_id} influence type={_text(profile.dcs_type)}"]
    lines.extend(f"  {format_influence_readiness(item)}" for item in profile.influences)
    return "\n".join(lines)


def format_group_influence(profile: GroupInfluence) -> str:
    """Return aggregated tactical influences for one group."""

    lines = [f"{profile.group_id} influence units={len(profile.units)}"]
    lines.extend(f"  {format_influence_readiness(item)}" for item in profile.influences)
    return "\n".join(lines)


def format_weapon_range(profile: WeaponRangeProfile | None) -> str:
    """Return a readable task weapon range profile."""

    if profile is None:
        return "Weapon range: unknown"
    weapon_ids = ", ".join(profile.weapon_ids) or "-"
    return (
        f"{profile.dcs_type} {profile.weapon_flag.name} "
        f"range={profile.minimum_m / 1000:.3f}-{profile.maximum_m / 1000:.3f}km "
        f"source={profile.source.value} weapons={weapon_ids}"
    )


def format_sensor_range(profile: SensorRangeProfile | None) -> str:
    """Return a readable optimistic sensor detection bound."""

    if profile is None:
        return "Sensor range: unknown"
    sensors = ", ".join(profile.sensor_names) or "organic"
    maximum = f"{profile.maximum_m / 1000:.3f}km" if profile.maximum_m is not None else "unknown"
    mode = f" mode={profile.mode}" if profile.mode else ""
    flags = []
    if profile.emitter_only:
        flags.append("emitter-only")
    if profile.exclusion_safe:
        flags.append(f"safe-{profile.range_scope.value}-bound")
    flag_text = f" flags={','.join(flags)}" if flags else ""
    details = []
    if profile.hard_limit_m is not None and profile.hard_limit_m != profile.maximum_m:
        details.append(f"hard-limit={profile.hard_limit_m / 1000:.3f}km")
    if profile.reference_rcs_m2 is not None:
        details.append(f"reference-rcs={profile.reference_rcs_m2:g}m2")
    if profile.scan_period_s is not None:
        details.append(f"scan-period={profile.scan_period_s:g}s")
    if profile.scan_azimuth_deg is not None:
        details.append(f"azimuth={profile.scan_azimuth_deg[0]:g}..{profile.scan_azimuth_deg[1]:g}deg")
    if profile.scan_elevation_deg is not None:
        details.append(f"elevation={profile.scan_elevation_deg[0]:g}..{profile.scan_elevation_deg[1]:g}deg")
    detail_text = f" {' '.join(details)}" if details else ""
    return (
        f"{profile.dcs_type} {profile.detection_type.value}/{profile.target_domain.value} "
        f"maximum={maximum}{mode} "
        f"source={profile.source.value} sensors={sensors}{flag_text}{detail_text}"
    )


def _format_goal_condition(condition: GoalCondition) -> str:
    value = condition.value
    if isinstance(value, tuple):
        rendered = ",".join(getattr(item, "value", str(item)) for item in value)
    else:
        rendered = getattr(value, "value", str(value))
    return f"{condition.kind.value}={rendered}"


def format_strategic_goal(goal: StrategicGoal) -> str:
    """Return a readable strategic goal lifecycle summary."""

    success = f" {goal.success_match.value} ".join(_format_goal_condition(item) for item in goal.success_conditions) or "manual"
    failure = f" {goal.failure_match.value} ".join(_format_goal_condition(item) for item in goal.failure_conditions) or "-"
    lines = [
            f"{goal.goal_id} action={goal.action.value} coalition={goal.coalition} "
            f"status={goal.status.value} priority={goal.priority:g}",
            f"  objective={goal.objective_id} evaluation={goal.evaluation_mode.value} "
            f"deadline={_text(goal.deadline_mission_time)}",
    ]
    if goal.required_damage is not None:
        lines.append(f"  required_damage={goal.required_damage:.1%}")
    if goal.effect is not None:
        lines.append(f"  effect={goal.effect.value}")
    lines.extend((f"  success: {success}", f"  failure: {failure}"))
    return "\n".join(lines)


def format_operational_plan_assessment(
    plan: OperationalPlan,
    assessment: OperationalPlanAssessment,
) -> str:
    """Return a readable operational plan and provisional allocation report."""

    lines = [
        (
            f"{plan.plan_id} goal={plan.goal_id} coalition={plan.coalition} "
            f"posture={plan.posture.value} status={plan.status.value}"
        ),
        (
            f"  feasible={assessment.feasible} requirements={len(assessment.requirements)} "
            f"errors={len(assessment.errors)} warnings={len(assessment.warnings)} "
            f"proposal_issues={len(plan.proposal_issues)}"
        ),
    ]
    phase_names = {phase.phase_id: phase.name for phase in plan.phases}
    mission_types = {
        (phase.phase_id, intent.intent_id, requirement.requirement_id): (
            str(intent.metadata.get("selected_mission_type") or "")
            or (requirement.mission_types[0] if requirement.mission_types else intent.auftrag_types[0])
        )
        for phase in plan.phases
        for intent in phase.intents
        for requirement in intent.asset_requirements
    }
    fire_support = {
        (phase.phase_id, intent.intent_id, requirement.requirement_id): intent.metadata.get("fire_support")
        for phase in plan.phases
        for intent in phase.intents
        for requirement in intent.asset_requirements
    }
    estimated_effect_times = {
        (phase.phase_id, intent.intent_id, requirement.requirement_id): intent.metadata.get(
            "estimated_time_to_effect_s"
        )
        or requirement.metadata.get("estimated_time_to_effect_s")
        for phase in plan.phases
        for intent in phase.intents
        for requirement in intent.asset_requirements
    }
    selection_scores = {
        (phase.phase_id, intent.intent_id, requirement.requirement_id): intent.metadata.get(
            "selection_score"
        )
        or requirement.metadata.get("selection_score")
        for phase in plan.phases
        for intent in phase.intents
        for requirement in intent.asset_requirements
    }
    mission_assignments = {
        (phase.phase_id, intent.intent_id, requirement.requirement_id): (
            requirement.metadata.get("mission_assignments")
            or intent.metadata.get("mission_assignments")
        )
        for phase in plan.phases
        for intent in phase.intents
        for requirement in intent.asset_requirements
    }
    current_phase: str | None = None
    for requirement in assessment.requirements:
        if requirement.phase_id != current_phase:
            current_phase = requirement.phase_id
            lines.append(f"  phase {current_phase}: {phase_names.get(current_phase, current_phase)}")
        allocations = ", ".join(
            (
                f"{item.cohort_id} x{item.count}/{item.unit_count}u ({item.legion_id})"
                if requirement.required_unit_count is not None
                else f"{item.cohort_id} x{item.count} ({item.legion_id})"
            )
            for item in requirement.allocations
        ) or "-"
        lines.append(
            f"    {requirement.intent_id}/{requirement.requirement_id}: "
            f"mission={mission_types.get((requirement.phase_id, requirement.intent_id, requirement.requirement_id), '-')} "
            f"required={requirement.required_count} available={requirement.available_count} "
            f"shortfall={requirement.shortfall} allocation=[{allocations}]"
        )
        if requirement.required_unit_count is not None:
            lines.append(
                f"      units required={requirement.required_unit_count} "
                f"available={requirement.available_unit_count} "
                f"allocated={requirement.allocated_unit_count} "
                f"shortfall={requirement.unit_shortfall}"
            )
        estimated_s = estimated_effect_times.get(
            (requirement.phase_id, requirement.intent_id, requirement.requirement_id)
        )
        if isinstance(estimated_s, (int, float)):
            lines.append(f"      estimated_time_to_effect={float(estimated_s):.0f}s")
        selected_score = selection_scores.get(
            (requirement.phase_id, requirement.intent_id, requirement.requirement_id)
        )
        if isinstance(selected_score, (int, float)):
            lines.append(f"      assignment_score={float(selected_score):.1f}")
        assignments = mission_assignments.get(
            (requirement.phase_id, requirement.intent_id, requirement.requirement_id)
        )
        if isinstance(assignments, list):
            options: list[str] = []
            for index, assignment in enumerate(assignments[:5], start=1):
                if not isinstance(assignment, Mapping):
                    continue
                eta = assignment.get("estimated_time_to_effect_s")
                eta_text = f"{float(eta):.0f}s" if isinstance(eta, (int, float)) else "unknown"
                weapon = assignment.get("weapon_flag")
                weapon_text = f"/{weapon}" if weapon else ""
                distance = assignment.get("transit_distance_m")
                distance_text = (
                    f" distance={float(distance) / 1_000.0:.1f}km"
                    if isinstance(distance, (int, float))
                    else ""
                )
                source = assignment.get("transit_source")
                route_text = f" route={source}" if source else ""
                max_speed = assignment.get("platform_max_speed_kph")
                speed_text = (
                    f" max_speed={float(max_speed):.1f}kph"
                    if isinstance(max_speed, (int, float))
                    else ""
                )
                bridges = assignment.get("bridge_count")
                bridge_text = (
                    f" bridges={int(bridges)}"
                    if isinstance(bridges, (int, float))
                    else ""
                )
                options.append(
                    f"      option {index}: {assignment.get('mission_type') or '-'}:"
                    f"{assignment.get('cohort_id') or '-'}{weapon_text} "
                    f"score={float(assignment.get('selection_score') or 0.0):.1f} "
                    f"performance={float(assignment.get('performance_score') or 0.0):.1f} "
                    f"skill={float(assignment.get('skill_score') or 0.0):.1f} "
                    f"response={float(assignment.get('response_score') or 0.0):.1f} "
                    f"eta={eta_text}{distance_text}{route_text}{speed_text}{bridge_text}"
                )
            if options:
                lines.append("      assignment_options:")
                lines.extend(options)
        support = fire_support.get((requirement.phase_id, requirement.intent_id, requirement.requirement_id))
        if isinstance(support, Mapping):
            distance = float(support.get("distance_m") or 0.0) / 1_000.0
            minimum = float(support.get("minimum_m") or 0.0) / 1_000.0
            maximum = float(support.get("maximum_m") or 0.0) / 1_000.0
            mission_range = float(support.get("mission_range_m") or 0.0) / 1_000.0
            configured_minimum = support.get("configured_minimum_m")
            configured_maximum = support.get("configured_maximum_m")
            configured_range = (
                "missing"
                if configured_maximum is None
                else (
                    f"{float(configured_minimum or 0.0) / 1_000.0:.1f}-"
                    f"{float(configured_maximum) / 1_000.0:.1f}km"
                )
            )
            sync = "required" if support.get("range_sync_required") else "current"
            relocation = float(support.get("required_relocation_m") or 0.0) / 1_000.0
            lines.append(
                f"      fire_support={support.get('cohort_id') or '-'} "
                f"flag={support.get('weapon_flag') or '-'} distance={distance:.1f}km "
                f"weapon_range={minimum:.1f}-{maximum:.1f}km mission_range={mission_range:.1f}km "
                f"moose_configured={configured_range} sync={sync} relocation={relocation:.1f}km "
                f"ammo={support.get('ammunition_source') or '-'}"
            )
    for issue in plan.proposal_issues:
        reference = f" {issue.reference_id}" if issue.reference_id else ""
        lines.append(f"  PROPOSAL {issue.severity.upper()} {issue.code}{reference}: {issue.message}")
    for issue in assessment.issues:
        reference = f" {issue.reference_id}" if issue.reference_id else ""
        lines.append(f"  {issue.severity.upper()} {issue.code}{reference}: {issue.message}")
    return "\n".join(lines)


def format_operational_plan_execution(execution: OperationalPlanExecution) -> str:
    """Return a readable operational plan execution report."""

    lines = [
        (
            f"{execution.plan_id} attempt={execution.attempt_number} "
            f"id={execution.attempt_id} commander={execution.commander_id} status={execution.status.value}"
        ),
        f"  current_phase={_text(execution.current_phase_id)} missions={len(execution.missions)} "
        f"resumed_from={_text(execution.resumed_from_phase_id)} blocked_reason={_text(execution.blocked_reason)}",
    ]
    approved_by = execution.plan_snapshot.get("approved_by")
    if approved_by:
        lines.append(
            f"  approved_by={approved_by} "
            f"client_id={_text(execution.plan_snapshot.get('approved_client_id'))} "
            f"approval_reason={_text(execution.plan_snapshot.get('approval_reason'))}"
        )
    provenance = execution.plan_snapshot.get("provenance")
    if isinstance(provenance, dict):
        lines.append(
            f"  source={_text(provenance.get('source_type'))}:{_text(provenance.get('source_id'))} "
            f"picture_mission_time={_text(provenance.get('picture_mission_time'))}"
        )
        if provenance.get("rationale"):
            lines.append(f"    rationale={provenance['rationale']}")
    proposal_issues = execution.plan_snapshot.get("proposal_issues")
    if isinstance(proposal_issues, list):
        for issue in proposal_issues:
            if not isinstance(issue, dict):
                continue
            reference = f" {issue.get('reference_id')}" if issue.get("reference_id") else ""
            lines.append(
                f"  PROPOSAL {str(issue.get('severity') or 'warning').upper()} "
                f"{issue.get('code') or 'unknown'}{reference}: "
                f"{issue.get('message') or '-'}"
            )
    for assessment in execution.damage_assessments:
        before = f"{assessment.health_before:.1%}" if assessment.health_before is not None else "-"
        after = f"{assessment.health_after:.1%}" if assessment.health_after is not None else "-"
        damage = f"{assessment.achieved_damage:.1%}" if assessment.achieved_damage is not None else "-"
        phase_damage = f"{assessment.phase_damage:.1%}" if assessment.phase_damage is not None else "-"
        lines.append(
            f"  strategic_damage phase={assessment.phase_id} objective={assessment.objective_id} "
            f"health={before}->{after} damage={damage} phase_damage={phase_damage} "
            f"required={assessment.required_damage:.1%} satisfied={assessment.satisfied}"
        )
        if assessment.component_health:
            components = ", ".join(
                f"{object_id}={'-' if health is None else f'{health:.1%}'}({source})"
                for object_id, health, source in assessment.component_health
            )
            lines.append(f"    components: {components}")
    for mission in execution.missions:
        requirement = f"{mission.phase_id}/{mission.intent_id}/{mission.requirement_id}"
        lines.append(
            f"  {requirement} type={mission.mission_type} required={mission.required} "
            f"persistent={mission.persistent} status={mission.status.value} "
            f"auftrag={_text(mission.auftrag_id)}"
        )
        if mission.command_ack:
            lines.append(
                f"    ack={_text(mission.command_ack.ack_id)} "
                f"correlation={_text(mission.command_ack.correlation_id)} "
                f"sequence={_text(mission.command_ack.sequence)}"
            )
        if mission.outcome:
            outcome = mission.outcome
            lines.append(
                f"    moose_auftrag_outcome evaluated={outcome.evaluated} success={outcome.success} "
                f"status={_text(outcome.status)} damage={_text(outcome.damage)} "
                f"targets={_text(outcome.n_targets_initial)}->{_text(outcome.n_targets_final)}"
            )
        if mission.recon_outcome:
            recon = mission.recon_outcome
            lines.append(
                f"    recon requirement_satisfied={recon.requirement_satisfied} "
                f"contacts={len(recon.observations)} new={recon.new_contact_count} "
                f"reacquired={recon.reacquired_contact_count} "
                f"unknown={len(recon.unknown_relevant_target_ids)} "
                f"lost={len(recon.lost_relevant_target_ids)}"
            )
            if recon.spatial_coverage:
                spatial = recon.spatial_coverage
                area = f"{spatial.area_coverage_ratio:.1%}" if spatial.area_coverage_ratio is not None else "-"
                components = f"{spatial.component_coverage_ratio:.1%}" if spatial.component_coverage_ratio is not None else "-"
                lines.append(
                    f"    spatial potential_area={area} components={components} "
                    f"samples={spatial.sample_count} sufficient={spatial.sufficient}"
                )
        if mission.error:
            label = (
                "auftrag_reason"
                if mission.outcome is not None
                else "reason"
                if execution.status.value == "completed" and mission.status is PlanMissionStatus.CANCELLED
                else "error"
            )
            lines.append(f"    {label}={mission.error}")
    return "\n".join(lines)


def format_operational_plan_reconciliation(reconciliation: OperationalPlanReconciliation) -> str:
    """Return a readable interrupted-plan reconciliation report."""

    lines = [
        (
            f"{reconciliation.plan_id} attempt={reconciliation.attempt_id} "
            f"reconciliation={reconciliation.status.value}"
        )
    ]
    if reconciliation.message:
        lines.append(f"  message={reconciliation.message}")
    for observation in reconciliation.observations:
        lines.append(
            f"  {observation.phase_id}/{observation.requirement_id} "
            f"auftrag={_text(observation.auftrag_id)} status={observation.status.value} "
            f"snapshot={observation.snapshot_found}"
        )
        if observation.message:
            lines.append(f"    message={observation.message}")
    return "\n".join(lines)


def format_operational_plan_abort(result: OperationalPlanAbortResult) -> str:
    """Return a readable operational-plan abort report."""

    lines = [
        (
            f"{result.plan_id} attempt={result.attempt_id} "
            f"abort_scope={result.scope.value} status={result.status.value}"
        )
    ]
    if result.message:
        lines.append(f"  message={result.message}")
    for mission in result.missions:
        lines.append(
            f"  {mission.phase_id}/{mission.requirement_id} auftrag={mission.auftrag_id} "
            f"cancelled={mission.cancelled}"
        )
        if mission.message:
            lines.append(f"    message={mission.message}")
    return "\n".join(lines)


def _clock_title(picture: GlobalPicture) -> str:
    clock = picture.clock
    if not clock:
        return datetime.now().strftime("%H:%M:%S")
    values = [f"wall={clock.wall_time or '-'}"]
    if clock.time_of_day is not None:
        dcs_date = clock.dcs_date or f"D+{clock.day_offset or 0}"
        values.append(f"dcs={dcs_date} {clock.time_of_day}")
    if clock.mission_elapsed is not None:
        values.append(f"mission={clock.mission_elapsed}")
    return " | ".join(values)


def format_picture_issue(issue: PictureValidationIssue) -> str:
    """Return one human-readable picture validation issue."""

    object_label = f" {issue.object_id}" if issue.object_id else ""
    return f"{issue.severity.upper()} {issue.code}{object_label}: {issue.message}"


def format_global_picture_status(picture: GlobalPicture, *, issue_limit: int = 20) -> str:
    """Return counts and consistency diagnostics for a global picture."""

    counts = picture.counts()
    alive_groups = sum(item.get("alive") is True for item in picture.groups)
    alive_units = sum(item.get("alive") is True for item in picture.units)
    alive_statics = sum(item.get("alive") is True for item in picture.statics)
    coalitions = {
        coalition: sum(item.get("coalition") == coalition for item in picture.groups)
        for coalition in ("blue", "red", "neutral")
    }
    issues = picture.validate()
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)

    lines = [
        f"[{_clock_title(picture)}] Global picture",
        "-" * 90,
        (
            f"truth: groups={counts['groups']} (alive={alive_groups}) "
            f"units={counts['units']} (alive={alive_units}) "
            f"statics={counts['statics']} (alive={alive_statics}) "
            f"airbases={counts['airbases']} zones={counts['zones']} "
            f"territories={counts['territories']}"
        ),
        (
            f"coalitions/groups: blue={coalitions['blue']} red={coalitions['red']} "
            f"neutral={coalitions['neutral']} unknown={counts['groups'] - sum(coalitions.values())}"
        ),
        (
            f"ops: opszones={counts['opszones']} opsgroups={counts['opsgroups']} "
            f"missions={counts['missions']} legions={counts['legions']} cohorts={counts['cohorts']}"
        ),
        (
            f"intel: objects={counts['intels']} contacts={counts['intel_contacts']} "
            f"clusters={counts['intel_clusters']}"
        ),
        f"validation: errors={errors} warnings={warnings}",
    ]
    for issue in issues[:issue_limit]:
        lines.append(f"  {format_picture_issue(issue)}")
    if len(issues) > issue_limit:
        lines.append(f"  ... {len(issues) - issue_limit} more")
    return "\n".join(lines)


def format_mission_summary(mission: Auftrag) -> str:
    """Return a compact one-line mission summary."""

    return (
        f"{mission.object_id} "
        f"type={_text(mission.type)} "
        f"status={_text(mission.status)} "
        f"assigned={_text(mission.n_assigned)} "
        f"elements={_text(mission.n_elements)}"
    )


def format_cohort_assets(cohort: Cohort, mission_limit: int = 6) -> str:
    """Return a compact one-line COHORT asset summary."""

    missions = ", ".join(cohort.mission_type_keys[:mission_limit]) or "-"
    return (
        f"{cohort.object_id} "
        f"cat={_text(cohort.category)} "
        f"type={_text(cohort.unit_type)} "
        f"assets={_text(cohort.asset_count)} "
        f"stock={_text(cohort.stock_asset_count)} "
        f"available={_text(cohort.available_asset_count)} "
        f"spawned={_text(cohort.spawned_asset_count)} "
        f"homogeneous={cohort.homogeneous} "
        f"units_per_asset={_text(cohort.units_per_asset)} "
        f"available_units={_text(cohort.available_unit_capacity)} "
        f"missions=[{missions}]"
    )


def format_legion_summary(legion: Legion, cohorts: list[Cohort], missions: list[Auftrag]) -> str:
    """Return a two-line LEGION summary."""

    stock_total = sum(cohort.stock_asset_count or 0 for cohort in cohorts)
    available_total = sum(cohort.available_asset_count or 0 for cohort in cohorts)
    spawned_total = sum(cohort.spawned_asset_count or 0 for cohort in cohorts)
    asset_total = sum(cohort.asset_count or 0 for cohort in cohorts)
    header = (
        f"{legion.object_id} "
        f"state={_text(legion.state)} "
        f"coalition={_text(legion.coalition or legion.coalition_name)} "
        f"airbase={_text(legion.airbase_name)}"
    )
    details = (
        f"  cohorts={len(cohorts)} "
        f"assets={asset_total} "
        f"stock={stock_total} "
        f"available={available_total} "
        f"spawned={spawned_total} "
        f"missions={len(missions)}"
    )
    return f"{header}\n{details}"


def format_legion_status(bridge: MooseBridgeClient, legion_id: str | None = None, timestamp: bool = True) -> str:
    """Return a readable LEGION status report from the SDK state mirror."""

    legions = [bridge.legion(legion_id)] if legion_id else list(bridge.state.legion_objects.values())
    resolved_legions = [legion for legion in legions if legion is not None]

    lines: list[str] = []
    title = "LEGION status"
    if timestamp:
        title = f"[{datetime.now().strftime('%H:%M:%S')}] {title}"
    lines.append(title)
    lines.append("-" * 90)

    if not resolved_legions:
        lines.append("No matching LEGION objects in the current state mirror.")
        return "\n".join(lines)

    for legion in resolved_legions:
        missions = bridge.missions_of_legion(legion.object_id)
        cohorts = bridge.cohorts_of_legion(legion.object_id)
        lines.append(format_legion_summary(legion, cohorts, missions))

        if missions:
            lines.append("  missions:")
            for mission in missions:
                lines.append(f"    {format_mission_summary(mission)}")

        if cohorts:
            lines.append("  cohorts:")
            for cohort in cohorts:
                lines.append(f"    {format_cohort_assets(cohort)}")

    return "\n".join(lines)


def format_commander_summary(commander: Commander, legions: list[Legion], missions: list[Auftrag]) -> str:
    """Return a compact COMMANDER summary."""

    return (
        f"{commander.object_id} state={_text(commander.state)} coalition={_text(commander.coalition)}\n"
        f"  legions={len(legions)} available={_text(commander.available_asset_count)} missions={len(missions)}"
    )


def format_commander_status(
    bridge: MooseBridgeClient,
    commander_id: str | None = None,
    timestamp: bool = True,
) -> str:
    """Return a readable COMMANDER status report from the SDK state mirror."""

    commanders = [bridge.commander(commander_id)] if commander_id else bridge.commanders()
    resolved = [commander for commander in commanders if commander is not None]
    title = "COMMANDER status"
    if timestamp:
        title = f"[{datetime.now().strftime('%H:%M:%S')}] {title}"
    lines = [title, "-" * 90]
    if not resolved:
        lines.append("No matching COMMANDER objects in the current state mirror.")
        return "\n".join(lines)
    for commander in resolved:
        legions = bridge.legions_of_commander(commander.object_id)
        missions = bridge.missions_of_commander(commander.object_id)
        lines.append(format_commander_summary(commander, legions, missions))
        for legion in legions:
            lines.append(
                f"    {legion.object_id} category={_text(legion.category)} "
                f"available={_text(legion.available_asset_count)}"
            )
        for mission in missions:
            lines.append(f"    {format_mission_summary(mission)}")
    return "\n".join(lines)


def format_intel_contact(contact: IntelContact) -> str:
    """Return a compact one-line INTEL contact summary."""

    position = "-"
    if contact.x is not None and contact.z is not None:
        position = f"x={contact.x:.0f} z={contact.z:.0f}"
    return (
        f"{contact.object_id} "
        f"target={_text(contact.target_object_id)} "
        f"type={_text(contact.contact_type)} "
        f"threat={_text(contact.threat_level)} "
        f"recce={_text(contact.recce)} "
        f"speed={_text(contact.speed_mps)} "
        f"{position}"
    )


def format_intel_cluster(cluster: IntelCluster) -> str:
    """Return a compact one-line INTEL cluster summary."""

    position = "-"
    if cluster.x is not None and cluster.z is not None:
        position = f"x={cluster.x:.0f} z={cluster.z:.0f}"
    return (
        f"{cluster.object_id} "
        f"type={_text(cluster.contact_type or cluster.category)} "
        f"size={_text(cluster.size)} "
        f"threat_max={_text(cluster.threat_level_max)} "
        f"threat_sum={_text(cluster.threat_level_sum)} "
        f"{position}"
    )


def format_intel_summary(intel: Intel, contacts: list[IntelContact], clusters: list[IntelCluster]) -> str:
    """Return a two-line INTEL summary."""

    header = (
        f"{intel.object_id} "
        f"state={_text(intel.state)} "
        f"running={intel.is_running} "
        f"coalition={_text(intel.coalition)} "
        f"alias={_text(intel.alias)}"
    )
    agent_count = intel.agent_count if intel.agent_count is not None else len(intel.agent_ids)
    agents = f"{intel.alive_agent_count}/{agent_count}" if intel.alive_agent_count is not None else str(agent_count)
    details = (
        f"  contacts={len(contacts)} "
        f"clusters={len(clusters)} "
        f"agents={agents} "
        f"cluster_analysis={intel.cluster_analysis} "
        f"radius_m={_text(intel.cluster_radius_m)}"
    )
    return f"{header}\n{details}"


def format_intel_status(
    bridge: MooseBridgeClient,
    intel_id: str | None = None,
    *,
    contact_limit: int = 12,
    cluster_limit: int = 8,
    timestamp: bool = True,
) -> str:
    """Return a readable INTEL status report from the SDK state mirror."""

    intels = [bridge.intel(intel_id)] if intel_id else list(bridge.state.intel_objects.values())
    resolved_intels = [intel for intel in intels if intel is not None]

    lines: list[str] = []
    title = "INTEL status"
    if timestamp:
        clock = bridge.state.clock
        if clock:
            values = [f"wall={clock.wall_time or '-'}"]
            if clock.time_of_day is not None:
                dcs_date = clock.dcs_date or f"D+{clock.day_offset or 0}"
                values.append(f"dcs={dcs_date} {clock.time_of_day}")
            if clock.mission_elapsed is not None:
                values.append(f"mission={clock.mission_elapsed}")
            title = f"[{' | '.join(values)}] {title}"
        else:
            title = f"[{datetime.now().strftime('%H:%M:%S')}] {title}"
    lines.append(title)
    lines.append("-" * 90)

    if not resolved_intels:
        lines.append("No matching INTEL objects in the current state mirror.")
        return "\n".join(lines)

    for intel in resolved_intels:
        contacts = bridge.contacts_of_intel(intel.object_id)
        clusters = bridge.clusters_of_intel(intel.object_id)
        contacts = sorted(contacts, key=lambda item: item.threat_level or 0, reverse=True)
        clusters = sorted(clusters, key=lambda item: item.threat_level_sum or 0, reverse=True)
        lines.append(format_intel_summary(intel, contacts, clusters))

        if contacts:
            lines.append("  contacts:")
            for contact in contacts[:contact_limit]:
                lines.append(f"    {format_intel_contact(contact)}")
            if len(contacts) > contact_limit:
                lines.append(f"    ... {len(contacts) - contact_limit} more")

        if clusters:
            lines.append("  clusters:")
            for cluster in clusters[:cluster_limit]:
                lines.append(f"    {format_intel_cluster(cluster)}")
            if len(clusters) > cluster_limit:
                lines.append(f"    ... {len(clusters) - cluster_limit} more")

    return "\n".join(lines)


__all__ = [
    "format_sensor_range",
    "format_cohort_assets",
    "format_global_picture_status",
    "format_intel_cluster",
    "format_intel_contact",
    "format_intel_status",
    "format_intel_summary",
    "format_legion_status",
    "format_legion_summary",
    "format_commander_status",
    "format_commander_summary",
    "format_mission_summary",
    "format_picture_issue",
    "format_operational_plan_assessment",
    "format_operational_plan_abort",
    "format_operational_plan_execution",
    "format_operational_plan_reconciliation",
    "format_strategic_goal",
    "format_strategic_goal_generation",
    "format_strategic_objective_generation",
    "format_strategic_scope",
    "format_strategic_feedback",
    "format_strategic_feedback_decision",
    "format_strategic_goal_portfolio",
    "format_relationship",
    "format_coalition_doctrine",
]
