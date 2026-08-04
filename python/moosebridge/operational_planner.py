"""Conservative rule-based operational plan proposals."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .models import IntelContact, OpsZone
from .operational import (
    AssetRequirement,
    AssetRole,
    MissionIntent,
    OperationalPlan,
    OperationalPlanProvenance,
    OperationalPosture,
    PlanPhase,
    PlanSourceType,
)
from .pictures import TacticalPicture
from .strategic import StrategicGoal, StrategicGoalAction, StrategicGoalStatus, StrategicObjective


@dataclass(slots=True, frozen=True)
class RuleBasedPlannerConfig:
    """Conservative constants used by the initial capture planner."""

    source_id: str = "moosebridge.rule_based_capture.v1"
    isolation_distance_from_zone_m: float = 30_000.0
    ground_assault_groups: int = 2

    def __post_init__(self) -> None:
        source_id = self.source_id.strip()
        if not source_id:
            raise ValueError("rule-based planner source_id must not be empty")
        object.__setattr__(self, "source_id", source_id)
        if not math.isfinite(self.isolation_distance_from_zone_m) or self.isolation_distance_from_zone_m < 0:
            raise ValueError("isolation distance must be finite and non-negative")
        if self.ground_assault_groups < 1:
            raise ValueError("ground assault groups must be at least one")


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

        defender = self._select_defender(zone, picture.contacts)
        phases: list[PlanPhase] = []
        previous_phase: str | None = None
        if defender is not None:
            target_id = defender.target_object_id
            assert target_id is not None
            phases.append(
                PlanPhase(
                    phase_id="isolate",
                    name="Isolate the objective",
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
            metadata={
                "planner": self.config.source_id,
                "objective_control_id": objective.control_object_id,
                "selected_defender_contact_id": defender.object_id if defender else None,
            },
        )

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

    def _select_defender(self, zone: OpsZone, contacts: list[IntelContact]) -> IntelContact | None:
        if zone.x is None or zone.z is None:
            return None
        radius = max(0.0, zone.zone_radius or 0.0) + self.config.isolation_distance_from_zone_m
        candidates: list[tuple[float, float, str, IntelContact]] = []
        for contact in contacts:
            target_id = contact.target_object_id or ""
            if not (contact.is_ground or contact.is_static) or not target_id.startswith(("GROUP:", "UNIT:", "STATIC:")):
                continue
            if contact.x is None or contact.z is None:
                continue
            distance = math.hypot(contact.x - zone.x, contact.z - zone.z)
            if distance > radius:
                continue
            candidates.append((-(contact.threat_level or 0.0), distance, target_id, contact))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[:3])[-1]


__all__ = ["RuleBasedOperationalPlanner", "RuleBasedPlannerConfig"]
