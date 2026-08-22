"""Preflight validation for a bilateral strategic conflict scenario."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .state import MooseBridgeState
from .strategic import ObjectiveKind, StrategicObjective, normalize_coalition
from .strategic_objectives import StrategicObjectiveGenerationResult
from .strategic_scope import StrategicTerritoryScope


class ConflictCapability(StrEnum):
    """Strategic action families required by the conflict controller."""

    CAPTURE = "capture"
    DEFEND = "defend"
    DESTROY = "destroy"


class ConflictReadinessSeverity(StrEnum):
    """Severity of one conflict-readiness finding."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(slots=True, frozen=True)
class ConflictReadinessIssue:
    """One actionable scenario-contract finding."""

    severity: ConflictReadinessSeverity
    code: str
    message: str
    coalition: str | None = None
    object_ids: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class CoalitionConflictReadiness:
    """Forces, intelligence, objectives, and capabilities of one coalition."""

    coalition: str
    commander_ids: tuple[str, ...]
    intel_ids: tuple[str, ...]
    legion_ids: tuple[str, ...]
    cohort_ids: tuple[str, ...]
    available_asset_count: int
    capability_cohort_ids: Mapping[ConflictCapability, tuple[str, ...]]
    owned_objective_count: int
    opposing_objective_count: int
    neutral_objective_count: int
    capturable_objective_count: int
    destroyable_objective_count: int

    def supports(self, capability: ConflictCapability | str) -> bool:
        """Return whether an available COHORT supports an action family."""

        return bool(self.capability_cohort_ids.get(ConflictCapability(capability), ()))


@dataclass(slots=True, frozen=True)
class ConflictReadinessReport:
    """Typed result of validating a live mission for bilateral conflict."""

    configured_theater_id: str | None
    active_theater_id: str | None
    mission_generation: int
    mission_time: float | None
    scope: StrategicTerritoryScope
    objective_generation: StrategicObjectiveGenerationResult | None
    coalitions: tuple[CoalitionConflictReadiness, ...]
    issues: tuple[ConflictReadinessIssue, ...]

    @property
    def ready(self) -> bool:
        """Return whether autonomous strategic decisions may start."""

        return not any(issue.severity is ConflictReadinessSeverity.ERROR for issue in self.issues)

    @property
    def errors(self) -> tuple[ConflictReadinessIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is ConflictReadinessSeverity.ERROR)

    @property
    def warnings(self) -> tuple[ConflictReadinessIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is ConflictReadinessSeverity.WARNING)

    @property
    def objective_count(self) -> int:
        return len(self.objective_generation.objectives) if self.objective_generation is not None else 0

    def coalition(self, coalition: str) -> CoalitionConflictReadiness:
        """Return one coalition report or raise for an unsupported coalition."""

        normalized = normalize_coalition(coalition)
        for item in self.coalitions:
            if item.coalition == normalized:
                return item
        raise ValueError(f"No conflict-readiness result exists for coalition {coalition!r}")

    def require_ready(self) -> "ConflictReadinessReport":
        """Reject controller startup when the scenario contract is incomplete."""

        if self.errors:
            raise ConflictReadinessError("; ".join(issue.message for issue in self.errors), self)
        return self


class ConflictReadinessError(ValueError):
    """Raised when a mission must not enter autonomous conflict control."""

    def __init__(self, message: str, report: ConflictReadinessReport) -> None:
        super().__init__(message)
        self.report = report


_CAPABILITY_MISSION_TYPES: Mapping[ConflictCapability, frozenset[str]] = {
    ConflictCapability.CAPTURE: frozenset({"CAPTUREZONE"}),
    ConflictCapability.DEFEND: frozenset({"ONGUARD", "PATROLZONE"}),
    ConflictCapability.DESTROY: frozenset(
        {
            "ANTISHIP",
            "ARTY",
            "BAI",
            "BOMBCARPET",
            "BOMBING",
            "BOMBRUNWAY",
            "GROUNDATTACK",
            "NAVALENGAGEMENT",
            "STRIKE",
        }
    ),
}

_CAPTURABLE_KINDS = {ObjectiveKind.AIRBASE, ObjectiveKind.FARP, ObjectiveKind.OPSZONE}


def evaluate_conflict_readiness(
    state: MooseBridgeState,
    scope: StrategicTerritoryScope,
    objective_generation: StrategicObjectiveGenerationResult | None,
    *,
    configured_theater_id: str | None,
    active_theater_id: str | None,
    intel_ids: Mapping[str, str] | None = None,
) -> ConflictReadinessReport:
    """Evaluate the live mission against the bilateral conflict contract."""

    issues: list[ConflictReadinessIssue] = []
    expected_intels = {
        normalized: object_id.strip()
        for coalition, object_id in (intel_ids or {}).items()
        if (normalized := normalize_coalition(coalition)) in {"blue", "red"} and object_id.strip()
    }

    configured = _clean(configured_theater_id)
    active = _clean(active_theater_id)
    if configured is None:
        issues.append(_error("theater_not_configured", "No static theater context is configured"))
    if active is None:
        issues.append(_error("active_theater_unknown", "DCS did not report the active theater"))
    if configured is not None and active is not None and configured.casefold() != active.casefold():
        issues.append(
            _error(
                "theater_mismatch",
                f"Configured theater {configured!r} does not match active DCS theater {active!r}",
            )
        )

    for item in scope.issues:
        issues.append(
            ConflictReadinessIssue(
                severity=(
                    ConflictReadinessSeverity.ERROR
                    if item.severity == "error"
                    else ConflictReadinessSeverity.WARNING
                ),
                code=f"scope_{item.code}",
                message=item.message,
                object_ids=item.territory_ids,
            )
        )
    if not scope.territory_ids or scope.included.is_empty:
        issues.append(_error("strategic_scope_empty", "No red, blue, or neutral strategic territory is available"))
    if scope.blue.is_empty:
        issues.append(_error("blue_scope_missing", "The strategic scope has no blue territory"))
    if scope.red.is_empty:
        issues.append(_error("red_scope_missing", "The strategic scope has no red territory"))

    objectives = objective_generation.objectives if objective_generation is not None else ()
    if objective_generation is None:
        issues.append(_error("objective_generation_unavailable", "Strategic objectives were not generated"))
    elif not objectives:
        issues.append(_error("objective_set_empty", "No strategic objective was admitted inside the scope"))

    coalition_reports = tuple(
        _evaluate_coalition(
            state,
            objectives,
            coalition,
            expected_intel_id=expected_intels.get(coalition),
            issues=issues,
        )
        for coalition in ("blue", "red")
    )
    return ConflictReadinessReport(
        configured_theater_id=configured,
        active_theater_id=active,
        mission_generation=state.mission_generation,
        mission_time=state.clock.mission_time if state.clock is not None else None,
        scope=scope,
        objective_generation=objective_generation,
        coalitions=coalition_reports,
        issues=tuple(issues),
    )


def _evaluate_coalition(
    state: MooseBridgeState,
    objectives: tuple[StrategicObjective, ...],
    coalition: str,
    *,
    expected_intel_id: str | None,
    issues: list[ConflictReadinessIssue],
) -> CoalitionConflictReadiness:
    opponent = "red" if coalition == "blue" else "blue"
    commanders = sorted(
        (
            item
            for item in state.commander_objects.values()
            if normalize_coalition(item.coalition) == coalition
        ),
        key=lambda item: item.object_id,
    )
    if not commanders:
        issues.append(_error("commander_missing", f"{coalition} has no COMMANDER", coalition))
    elif len(commanders) > 1:
        issues.append(
            _error(
                "commander_ambiguous",
                f"{coalition} has multiple COMMANDER objects: {', '.join(item.object_id for item in commanders)}",
                coalition,
                tuple(item.object_id for item in commanders),
            )
        )

    coalition_intels = sorted(
        (
            item
            for item in state.intel_objects.values()
            if normalize_coalition(item.coalition) == coalition
        ),
        key=lambda item: item.object_id,
    )
    if expected_intel_id is not None:
        selected_intels = [item for item in coalition_intels if item.object_id == expected_intel_id]
        if not selected_intels:
            issues.append(
                _error(
                    "intel_missing",
                    f"{coalition} requires {expected_intel_id}, but it is not available",
                    coalition,
                    (expected_intel_id,),
                )
            )
    else:
        selected_intels = coalition_intels
        if not selected_intels:
            issues.append(_error("intel_missing", f"{coalition} has no INTEL object", coalition))
        elif len(selected_intels) > 1:
            issues.append(
                _error(
                    "intel_ambiguous",
                    f"{coalition} has multiple INTEL objects; configure the controller's INTEL id explicitly",
                    coalition,
                    tuple(item.object_id for item in selected_intels),
                )
            )
    for intel in selected_intels:
        if not intel.is_running:
            issues.append(
                _warning(
                    "intel_not_running",
                    f"{intel.object_id} is present but not reported as running",
                    coalition,
                    (intel.object_id,),
                )
            )

    commander_legion_ids = {legion_id for commander in commanders for legion_id in commander.legion_ids}
    legions = sorted(
        (
            item
            for object_id, item in state.legion_objects.items()
            if object_id in commander_legion_ids and normalize_coalition(item.coalition) == coalition
        ),
        key=lambda item: item.object_id,
    )
    if not legions:
        issues.append(_error("legion_missing", f"{coalition} COMMANDER has no assigned LEGION", coalition))

    legion_ids = {item.object_id for item in legions}
    cohorts = sorted(
        (item for item in state.cohort_objects.values() if item.legion_id in legion_ids),
        key=lambda item: item.object_id,
    )
    available_cohorts = [item for item in cohorts if (item.available_asset_count or 0) > 0]
    if not cohorts:
        issues.append(_error("cohort_missing", f"{coalition} has no COHORT under its COMMANDER", coalition))
    elif not available_cohorts:
        issues.append(_error("assets_unavailable", f"{coalition} has no currently available COHORT assets", coalition))

    capability_cohorts: dict[ConflictCapability, tuple[str, ...]] = {}
    for capability, mission_types in _CAPABILITY_MISSION_TYPES.items():
        ids = tuple(
            item.object_id
            for item in available_cohorts
            if mission_types.intersection(item.mission_type_keys)
        )
        capability_cohorts[capability] = ids
        if not ids:
            issues.append(
                _error(
                    f"{capability.value}_capability_missing",
                    f"{coalition} has no available COHORT for {capability.value.upper()} missions",
                    coalition,
                )
            )

    owned = tuple(item for item in objectives if item.owner == coalition)
    opposing = tuple(item for item in objectives if item.owner == opponent)
    neutral = tuple(item for item in objectives if item.owner not in {coalition, opponent})
    capturable = tuple(
        item
        for item in objectives
        if item.owner != coalition and item.kind in _CAPTURABLE_KINDS and item.control_object_id is not None
    )
    destroyable = tuple(
        item
        for item in opposing
        if bool(item.metadata.get("targetable")) and bool(item.components)
    )
    if objectives and not owned:
        issues.append(_error("owned_objective_missing", f"{coalition} has no objective to defend", coalition))
    if objectives and not opposing:
        issues.append(_error("opposing_objective_missing", f"{coalition} has no opposing objective", coalition))
    if objectives and not capturable:
        issues.append(_warning("capture_target_missing", f"{coalition} has no capturable objective", coalition))
    if objectives and not destroyable:
        issues.append(_warning("destroy_target_missing", f"{coalition} has no verified destroyable objective", coalition))

    return CoalitionConflictReadiness(
        coalition=coalition,
        commander_ids=tuple(item.object_id for item in commanders),
        intel_ids=tuple(item.object_id for item in selected_intels),
        legion_ids=tuple(item.object_id for item in legions),
        cohort_ids=tuple(item.object_id for item in cohorts),
        available_asset_count=sum(item.available_asset_count or 0 for item in available_cohorts),
        capability_cohort_ids=capability_cohorts,
        owned_objective_count=len(owned),
        opposing_objective_count=len(opposing),
        neutral_objective_count=len(neutral),
        capturable_objective_count=len(capturable),
        destroyable_objective_count=len(destroyable),
    )


def _clean(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _error(
    code: str,
    message: str,
    coalition: str | None = None,
    object_ids: tuple[str, ...] = (),
) -> ConflictReadinessIssue:
    return ConflictReadinessIssue(ConflictReadinessSeverity.ERROR, code, message, coalition, object_ids)


def _warning(
    code: str,
    message: str,
    coalition: str | None = None,
    object_ids: tuple[str, ...] = (),
) -> ConflictReadinessIssue:
    return ConflictReadinessIssue(ConflictReadinessSeverity.WARNING, code, message, coalition, object_ids)
