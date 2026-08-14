"""Coalition-specific strategic-goal derivation from shared objectives."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .diplomacy import CoalitionRelationship
from .strategic import (
    ObjectiveKind,
    ObjectiveStatus,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
    normalize_coalition,
)


@dataclass(slots=True, frozen=True)
class StrategicGoalGenerationConfig:
    """Policy values used when materializing derived strategic goals."""

    defense_duration_s: float = 1800.0
    destroy_required_damage: float = 0.7

    def __post_init__(self) -> None:
        if not math.isfinite(self.defense_duration_s) or self.defense_duration_s <= 0:
            raise ValueError("defense_duration_s must be finite and positive")
        if not math.isfinite(self.destroy_required_damage) or not 0 <= self.destroy_required_damage <= 1:
            raise ValueError("destroy_required_damage must be between zero and one")


@dataclass(slots=True, frozen=True)
class StrategicGoalDerivation:
    """Auditable coalition-specific decision for one shared objective."""

    objective_id: str
    coalition: str
    action: StrategicGoalAction | None
    permitted: bool
    reason: str
    priority: float
    goal_id: str | None = None


@dataclass(slots=True, frozen=True)
class StrategicGoalGenerationResult:
    """Generated goals and the complete objective-by-objective decision audit."""

    coalition: str
    goals: tuple[StrategicGoal, ...]
    decisions: tuple[StrategicGoalDerivation, ...]

    @property
    def rejected(self) -> tuple[StrategicGoalDerivation, ...]:
        return tuple(item for item in self.decisions if item.goal_id is None)


def evaluate_strategic_objective(
    objective: StrategicObjective,
    coalition: str,
    *,
    relationship: CoalitionRelationship | None = None,
) -> StrategicGoalDerivation:
    """Choose the currently supported strategic action for one coalition."""

    normalized = normalize_coalition(coalition) or ""
    if normalized not in {"blue", "red"}:
        raise ValueError("strategic goal generation requires coalition blue or red")
    priority = max(objective.priority, objective.strategic_value)
    scope_state = str(objective.metadata.get("scope_state") or "").strip().lower()
    if scope_state == "out_of_scope":
        return StrategicGoalDerivation(
            objective.objective_id, normalized, None, False, "objective is outside strategic scope", priority
        )
    if objective.status is ObjectiveStatus.DESTROYED or objective.health == 0.0:
        return StrategicGoalDerivation(
            objective.objective_id, normalized, None, False, "objective is already destroyed", priority
        )

    action: StrategicGoalAction | None = None
    reason: str
    if objective.kind is ObjectiveKind.OPSZONE and (
        objective.control_object_id or ""
    ).startswith("OPSZONE:"):
        if objective.owner == normalized:
            if objective.contested:
                action = StrategicGoalAction.DEFEND
                reason = "friendly OPSZONE is contested"
            else:
                reason = "friendly OPSZONE is secure"
        else:
            action = StrategicGoalAction.CAPTURE
            reason = "OPSZONE is not controlled by the coalition"
    elif objective.components:
        if objective.owner == normalized:
            reason = "friendly component objective is not an attack target"
        elif objective.owner in {"blue", "red"}:
            action = StrategicGoalAction.DESTROY
            reason = "enemy objective has addressable components"
        else:
            reason = "neutral component objective is not attacked automatically"
    else:
        reason = "no supported CAPTURE, DEFEND, or DESTROY plan is available"

    if action is None:
        return StrategicGoalDerivation(objective.objective_id, normalized, None, False, reason, priority)
    if relationship is not None:
        permitted, policy_reason = relationship.allows_goal(action, objective)
        if not permitted:
            return StrategicGoalDerivation(
                objective.objective_id,
                normalized,
                action,
                False,
                policy_reason,
                priority,
            )
        reason = f"{reason}; {policy_reason}"
    return StrategicGoalDerivation(objective.objective_id, normalized, action, True, reason, priority)


def generate_strategic_goals(
    objectives: Iterable[StrategicObjective],
    coalition: str,
    *,
    relationship: CoalitionRelationship | None = None,
    existing_goals: Iterable[StrategicGoal] = (),
    mission_time: float | None = None,
    generation_id: str = "AUTO",
    config: StrategicGoalGenerationConfig | None = None,
    metadata: dict[str, object] | None = None,
) -> StrategicGoalGenerationResult:
    """Derive executable coalition-private goals from shared objectives."""

    normalized = normalize_coalition(coalition) or ""
    if normalized not in {"blue", "red"}:
        raise ValueError("strategic goal generation requires coalition blue or red")
    if mission_time is not None and (not math.isfinite(mission_time) or mission_time < 0):
        raise ValueError("mission_time must be finite and non-negative")
    resolved = config or StrategicGoalGenerationConfig()
    suffix = _identifier_token(generation_id)
    open_by_objective = {
        item.objective_id: item
        for item in existing_goals
        if item.coalition == normalized
        and item.status in {StrategicGoalStatus.PLANNED, StrategicGoalStatus.ACTIVE}
    }
    goals: list[StrategicGoal] = []
    decisions: list[StrategicGoalDerivation] = []
    ordered_objectives = sorted(
        objectives,
        key=lambda item: (-max(item.priority, item.strategic_value), item.objective_id),
    )
    for objective in ordered_objectives:
        decision = evaluate_strategic_objective(objective, normalized, relationship=relationship)
        existing = open_by_objective.get(objective.objective_id)
        if existing is not None:
            decisions.append(
                StrategicGoalDerivation(
                    decision.objective_id,
                    normalized,
                    decision.action,
                    False,
                    f"open goal already exists: {existing.goal_id}",
                    decision.priority,
                )
            )
            continue
        if decision.action is None or not decision.permitted:
            decisions.append(decision)
            continue
        if decision.action is StrategicGoalAction.DEFEND and mission_time is None:
            decisions.append(
                StrategicGoalDerivation(
                    decision.objective_id,
                    normalized,
                    decision.action,
                    False,
                    "DEFEND goal requires current DCS mission time",
                    decision.priority,
                )
            )
            continue
        token = _identifier_token(objective.objective_id.removeprefix("OBJECTIVE:"))
        goal_id = f"GOAL:{normalized}:{decision.action.value}:{token}:{suffix}"
        goal = StrategicGoal(
            goal_id=goal_id,
            name=f"{normalized.title()} {decision.action.value} {objective.name}",
            coalition=normalized,
            action=decision.action,
            objective_id=objective.objective_id,
            priority=decision.priority,
            created_mission_time=mission_time,
            deadline_mission_time=(
                mission_time + resolved.defense_duration_s
                if decision.action is StrategicGoalAction.DEFEND and mission_time is not None
                else None
            ),
            required_damage=(
                resolved.destroy_required_damage
                if decision.action is StrategicGoalAction.DESTROY
                else None
            ),
            metadata={
                "generated": True,
                "generation_id": generation_id,
                "derivation_reason": decision.reason,
                **(metadata or {}),
            },
        )
        goals.append(goal)
        decisions.append(
            StrategicGoalDerivation(
                decision.objective_id,
                normalized,
                decision.action,
                True,
                decision.reason,
                decision.priority,
                goal.goal_id,
            )
        )
    return StrategicGoalGenerationResult(normalized, tuple(goals), tuple(decisions))


def _identifier_token(value: str) -> str:
    token = "-".join(str(value).strip().split())
    return token.replace("/", "-").replace("\\", "-").replace(":", "-") or "AUTO"


__all__ = [
    "StrategicGoalDerivation",
    "StrategicGoalGenerationConfig",
    "StrategicGoalGenerationResult",
    "evaluate_strategic_objective",
    "generate_strategic_goals",
]
