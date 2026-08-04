"""Conservative rule-based operational plan proposals."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .intelligence import ContactInformationState, IntelContactMemory, assess_intel_contact
from .models import IntelContact, OpsZone
from .operational import (
    AssetRequirement,
    AssetRole,
    MissionIntent,
    OperationalPlan,
    OperationalPlanProvenance,
    OperationalPosture,
    PlanPhase,
    PlanProposalIssue,
    PlanSourceType,
)
from .pictures import TacticalPicture
from .recon import derive_recon_requirement
from .strategic import StrategicGoal, StrategicGoalAction, StrategicGoalStatus, StrategicObjective


@dataclass(slots=True, frozen=True)
class RuleBasedPlannerConfig:
    """Conservative constants used by the initial capture planner."""

    source_id: str = "moosebridge.rule_based_capture.v1"
    isolation_distance_from_zone_m: float = 30_000.0
    ground_assault_groups: int = 2
    contact_fresh_for_s: float = 120.0
    contact_stale_after_s: float = 600.0
    lost_contact_recon_window_s: float = 900.0
    lost_contact_recon_threat_min: float = 3.0

    def __post_init__(self) -> None:
        source_id = self.source_id.strip()
        if not source_id:
            raise ValueError("rule-based planner source_id must not be empty")
        object.__setattr__(self, "source_id", source_id)
        if not math.isfinite(self.isolation_distance_from_zone_m) or self.isolation_distance_from_zone_m < 0:
            raise ValueError("isolation distance must be finite and non-negative")
        if self.ground_assault_groups < 1:
            raise ValueError("ground assault groups must be at least one")
        if not math.isfinite(self.contact_fresh_for_s) or self.contact_fresh_for_s < 0:
            raise ValueError("contact fresh duration must be finite and non-negative")
        if not math.isfinite(self.contact_stale_after_s) or self.contact_stale_after_s <= self.contact_fresh_for_s:
            raise ValueError("contact stale threshold must be greater than the fresh duration")
        if (
            not math.isfinite(self.lost_contact_recon_window_s)
            or self.lost_contact_recon_window_s <= self.contact_fresh_for_s
        ):
            raise ValueError("lost-contact recon window must be greater than the contact fresh duration")
        if not math.isfinite(self.lost_contact_recon_threat_min) or self.lost_contact_recon_threat_min < 0:
            raise ValueError("lost-contact recon threat threshold must be finite and non-negative")


class RuleBasedOperationalPlanner:
    """Create reviewable CAPTURE drafts from coalition-visible tactical state."""

    def __init__(self, config: RuleBasedPlannerConfig | None = None) -> None:
        self.config = config or RuleBasedPlannerConfig()

    def propose_capture(
        self,
        goal: StrategicGoal,
        objective: StrategicObjective,
        picture: TacticalPicture,
        *,
        plan_id: str | None = None,
        name: str | None = None,
    ) -> OperationalPlan:
        """Return a draft capture plan without registering, validating, or approving it."""

        self._validate_inputs(goal, objective, picture)
        assert objective.control_object_id is not None
        zone = next((item for item in picture.opszones if item.object_id == objective.control_object_id), None)
        if zone is None:
            raise ValueError(f"tactical picture does not contain target OPSZONE: {objective.control_object_id}")

        defender = self._select_defender(zone, picture)
        lost_recon_contact = self._select_lost_recon_contact(zone, picture)
        proposal_issues = self._intel_issues(picture, defender, lost_recon_contact)
        recon_requirement = (
            derive_recon_requirement(
                goal,
                objective,
                picture,
                manual_target_ids=(lost_recon_contact.contact.target_object_id,)
                if lost_recon_contact and lost_recon_contact.contact.target_object_id
                else (),
                maximum_contact_age_s=self.config.lost_contact_recon_window_s,
                area_buffer_m=self.config.isolation_distance_from_zone_m,
            )
            if lost_recon_contact is not None
            else None
        )
        phases: list[PlanPhase] = []
        previous_phase: str | None = None
        if lost_recon_contact is not None:
            phases.append(
                PlanPhase(
                    phase_id="recon",
                    name="Reacquire important lost contacts",
                    metadata={
                        "requires_tactical_replanning": True,
                        "intel_id": picture.intel_id,
                        "reconnaissance_requirement": recon_requirement.to_dict() if recon_requirement else None,
                    },
                    intents=(
                        MissionIntent(
                            intent_id="recon-objective",
                            name="Reconnoitre the objective area",
                            auftrag_types=("RECON",),
                            target_object_id=objective.control_object_id,
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Reconnaissance",
                                    role=AssetRole.RECONNAISSANCE,
                                    mission_types=("RECON",),
                                    performer_categories=("AIR", "GROUND", "NAVAL"),
                                ),
                            ),
                            metadata={
                                "auftrag_params": {
                                    "zones": (objective.control_object_id,),
                                    "ad_infinitum": False,
                                    "randomly": False,
                                },
                                "lost_contact_id": lost_recon_contact.contact.object_id,
                                "reconnaissance_requirement": recon_requirement.to_dict() if recon_requirement else None,
                            },
                        ),
                    ),
                )
            )
            previous_phase = "recon"
        if defender is not None:
            target_id = defender.target_object_id
            assert target_id is not None
            phases.append(
                PlanPhase(
                    phase_id="isolate",
                    name="Isolate the objective",
                    depends_on=(previous_phase,) if previous_phase else (),
                    intents=(
                        MissionIntent(
                            intent_id="interdict-defenders",
                            name="Interdict detected defenders",
                            auftrag_types=("BAI",),
                            target_object_id=target_id,
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Strike",
                                    role=AssetRole.COMBAT,
                                    mission_types=("BAI",),
                                    performer_categories=("AIR",),
                                    require_payload=True,
                                ),
                            ),
                            metadata={"intel_contact_id": defender.object_id},
                        ),
                    ),
                )
            )
            previous_phase = "isolate"

        phases.append(
            PlanPhase(
                phase_id="seize",
                name="Seize the objective",
                depends_on=(previous_phase,) if previous_phase else (),
                intents=(
                    MissionIntent(
                        intent_id="capture-zone",
                        name="Capture the OPSZONE",
                        auftrag_types=("CAPTUREZONE",),
                        target_object_id=objective.control_object_id,
                        asset_requirements=(
                            AssetRequirement(
                                requirement_id="REQ:Ground assault",
                                role=AssetRole.COMBAT,
                                min_count=self.config.ground_assault_groups,
                                max_count=self.config.ground_assault_groups,
                                mission_types=("CAPTUREZONE",),
                                performer_categories=("GROUND",),
                            ),
                        ),
                    ),
                ),
            )
        )
        phases.append(
            PlanPhase(
                phase_id="consolidate",
                name="Consolidate control",
                depends_on=("seize",),
                intents=(
                    MissionIntent(
                        intent_id="establish-air-defense",
                        name="Establish local air defense",
                        auftrag_types=("AIRDEFENSE",),
                        target_object_id=objective.control_object_id,
                        required=False,
                        asset_requirements=(
                            AssetRequirement(
                                requirement_id="REQ:Air defense",
                                role=AssetRole.AIR_DEFENSE,
                                mission_types=("AIRDEFENSE",),
                                performer_categories=("GROUND",),
                            ),
                        ),
                    ),
                    MissionIntent(
                        intent_id="sustain-force",
                        name="Supply the occupying force",
                        auftrag_types=("AMMOSUPPLY",),
                        target_object_id=objective.control_object_id,
                        required=False,
                        asset_requirements=(
                            AssetRequirement(
                                requirement_id="REQ:Logistics",
                                role=AssetRole.LOGISTICS,
                                mission_types=("AMMOSUPPLY",),
                                performer_categories=("GROUND",),
                            ),
                        ),
                    ),
                ),
            )
        )

        defender_text = (
            f"Detected defender {defender.target_object_id} selected for isolation."
            if defender is not None
            else "No coalition-visible ground defender near the objective; no isolation strike was proposed."
        )
        recon_metadata = recon_requirement.to_dict() if recon_requirement else None
        if recon_metadata is not None:
            contact = lost_recon_contact.contact
            recon_metadata.update(
                {
                    "status": "required",
                    "reason": "important_lost_contact",
                    "contact_id": contact.object_id,
                    "target_object_id": contact.target_object_id,
                    "last_detected_time": contact.detected_time,
                    "lost_time": lost_recon_contact.lost_time,
                    "last_known_x": contact.x,
                    "last_known_z": contact.z,
                    "threat_level": contact.threat_level,
                }
            )
        proposal_id = plan_id or f"PLAN:{goal.goal_id.removeprefix('GOAL:')}"
        return OperationalPlan(
            plan_id=proposal_id,
            name=name or f"Capture {objective.name}",
            goal_id=goal.goal_id,
            coalition=goal.coalition,
            phases=tuple(phases),
            posture=OperationalPosture.BALANCED,
            provenance=OperationalPlanProvenance(
                source_type=PlanSourceType.RULE_ENGINE,
                source_id=self.config.source_id,
                picture_mission_time=picture.clock.mission_time if picture.clock else None,
                rationale=(
                    f"Conservative capture sequence for {objective.objective_id}. {defender_text} "
                    "Ground seizure is required; air defense and ammunition supply are optional consolidation tasks."
                ),
            ),
            proposal_issues=proposal_issues,
            metadata={
                "planner": self.config.source_id,
                "objective_control_id": objective.control_object_id,
                "selected_defender_contact_id": defender.object_id if defender else None,
                "reconnaissance_requirement": recon_metadata,
            },
        )

    def _intel_issues(
        self,
        picture: TacticalPicture,
        defender: IntelContact | None,
        lost_recon_contact: IntelContactMemory | None,
    ) -> tuple[PlanProposalIssue, ...]:
        issues: list[PlanProposalIssue] = []
        if picture.intel is None:
            issues.append(
                PlanProposalIssue(
                    "warning",
                    "intel_status_unknown",
                    "The tactical picture contains no INTEL status; detection coverage cannot be assessed.",
                    picture.intel_id,
                )
            )
        else:
            if not picture.intel.is_running:
                issues.append(
                    PlanProposalIssue(
                        "warning",
                        "intel_not_running",
                        "The INTEL source is not running; contacts may be incomplete or stale.",
                        picture.intel.object_id,
                    )
                )
            if picture.intel.alive_agent_count is None:
                issues.append(
                    PlanProposalIssue(
                        "warning",
                        "intel_agent_status_unknown",
                        "The number of living INTEL agents is unknown.",
                        picture.intel.object_id,
                    )
                )
            elif picture.intel.alive_agent_count == 0:
                issues.append(
                    PlanProposalIssue(
                        "warning",
                        "intel_no_alive_agents",
                        "The INTEL source has no living detection agents.",
                        picture.intel.object_id,
                    )
                )
        if defender is None:
            issues.append(
                PlanProposalIssue(
                    "warning",
                    "intel_no_visible_defenders",
                    (
                        "No coalition-visible ground defender was found near the objective. "
                        "This is not evidence that the objective is undefended."
                    ),
                    picture.intel_id,
                )
            )
        else:
            assessment = assess_intel_contact(
                defender,
                picture.clock.mission_time if picture.clock else None,
                fresh_for_s=self.config.contact_fresh_for_s,
                stale_after_s=self.config.contact_stale_after_s,
            )
            if assessment.state in {ContactInformationState.DEGRADED, ContactInformationState.UNKNOWN}:
                age = f"{assessment.age_s:.0f} seconds" if assessment.age_s is not None else "unknown"
                issues.append(
                    PlanProposalIssue(
                        "warning",
                        "intel_contact_quality_degraded",
                        f"The selected defender contact has {assessment.state.value} freshness (age {age}).",
                        defender.object_id,
                    )
                )
        if lost_recon_contact is not None:
            contact = lost_recon_contact.contact
            issues.append(
                PlanProposalIssue(
                    "warning",
                    "reconnaissance_required",
                    (
                        f"Important contact {contact.target_object_id or contact.object_id} was lost near the objective. "
                        "A RECON phase was proposed before relying on its last known position."
                    ),
                    contact.object_id,
                )
            )
        return tuple(issues)

    @staticmethod
    def _validate_inputs(
        goal: StrategicGoal,
        objective: StrategicObjective,
        picture: TacticalPicture,
    ) -> None:
        if goal.action is not StrategicGoalAction.CAPTURE:
            raise ValueError("rule-based operational planner currently supports CAPTURE goals only")
        if goal.status in {StrategicGoalStatus.ACHIEVED, StrategicGoalStatus.FAILED, StrategicGoalStatus.CANCELLED}:
            raise ValueError(f"cannot propose a plan for goal in state {goal.status.value}")
        if goal.objective_id != objective.objective_id:
            raise ValueError("goal and strategic objective do not match")
        if picture.coalition.lower() != goal.coalition:
            raise ValueError("tactical picture coalition does not match the strategic goal")
        if objective.owner == goal.coalition:
            raise ValueError("strategic objective is already controlled by the goal coalition")
        if not objective.control_object_id or not objective.control_object_id.startswith("OPSZONE:"):
            raise ValueError("initial rule-based CAPTURE planner requires an OPSZONE control object")

    def _select_defender(self, zone: OpsZone, picture: TacticalPicture) -> IntelContact | None:
        if zone.x is None or zone.z is None:
            return None
        radius = max(0.0, zone.zone_radius or 0.0) + self.config.isolation_distance_from_zone_m
        candidates: list[tuple[float, float, str, IntelContact]] = []
        mission_time = picture.clock.mission_time if picture.clock else None
        for contact in picture.contacts:
            target_id = contact.target_object_id or ""
            if not (contact.is_ground or contact.is_static) or not target_id.startswith(("GROUP:", "UNIT:", "STATIC:")):
                continue
            if contact.x is None or contact.z is None:
                continue
            distance = math.hypot(contact.x - zone.x, contact.z - zone.z)
            if distance > radius:
                continue
            assessment = assess_intel_contact(
                contact,
                mission_time,
                fresh_for_s=self.config.contact_fresh_for_s,
                stale_after_s=self.config.contact_stale_after_s,
            )
            if assessment.state is ContactInformationState.STALE:
                continue
            effective_threat = (contact.threat_level or 0.0) * assessment.confidence
            candidates.append((-effective_threat, distance, target_id, contact))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[:3])[-1]

    def _select_lost_recon_contact(
        self,
        zone: OpsZone,
        picture: TacticalPicture,
    ) -> IntelContactMemory | None:
        if zone.x is None or zone.z is None:
            return None
        current_targets = {contact.target_object_id for contact in picture.contacts if contact.target_object_id}
        mission_time = picture.clock.mission_time if picture.clock else None
        radius = max(0.0, zone.zone_radius or 0.0) + self.config.isolation_distance_from_zone_m
        candidates: list[tuple[float, float, str, IntelContactMemory]] = []
        for memory in picture.lost_contacts:
            contact = memory.contact
            target_id = contact.target_object_id or ""
            if target_id in current_targets:
                continue
            if not (contact.is_ground or contact.is_static) or not target_id.startswith(("GROUP:", "UNIT:", "STATIC:")):
                continue
            if contact.x is None or contact.z is None or (contact.threat_level or 0.0) < self.config.lost_contact_recon_threat_min:
                continue
            distance = math.hypot(contact.x - zone.x, contact.z - zone.z)
            if distance > radius:
                continue
            assessment = assess_intel_contact(
                contact,
                mission_time,
                fresh_for_s=self.config.contact_fresh_for_s,
                stale_after_s=self.config.lost_contact_recon_window_s,
                lost=True,
            )
            if assessment.age_s is not None and assessment.age_s > self.config.lost_contact_recon_window_s:
                continue
            candidates.append((-(contact.threat_level or 0.0), distance, target_id, memory))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[:3])[-1]


__all__ = ["RuleBasedOperationalPlanner", "RuleBasedPlannerConfig"]
