"""Conservative mapping from strategic target effects to executable AUFTRAG types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Iterable, Mapping

from .ammunition import DcsWeaponFlag, UnitAmmunition, WeaponRole
from .auftrag_specs import canonical_mission_type, platform_categories_match
from .legions import Cohort, Legion
from .operational import AssetRole
from .strategic import StrategicGoalEffect
from .weapon_ranges import DEFAULT_WEAPON_RANGE_REGISTRY, RangeSource, WeaponRangeProfile, WeaponRangeRegistry


class StrategicTargetDomain(str, Enum):
    """Target domain relevant to AUFTRAG selection."""

    AIR = "air"
    GROUND = "ground"
    NAVAL = "naval"
    STATIC = "static"
    AIRBASE = "airbase"
    SCENERY = "scenery"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class MissionCandidate:
    """One ordered AUFTRAG option for producing a strategic effect."""

    mission_type: str
    role: AssetRole
    performer_categories: tuple[str, ...]
    require_payload: bool
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_type", canonical_mission_type(self.mission_type))
        object.__setattr__(self, "role", AssetRole(self.role))
        object.__setattr__(
            self,
            "performer_categories",
            tuple(dict.fromkeys(category.strip().upper() for category in self.performer_categories)),
        )


@dataclass(slots=True, frozen=True)
class MissionResolution:
    """Resolved target domain, ordered alternatives, and selected AUFTRAG."""

    target_object_id: str
    target_domain: StrategicTargetDomain
    effect: StrategicGoalEffect
    candidates: tuple[MissionCandidate, ...]
    selected: MissionCandidate
    selected_cohort_id: str | None = None
    fire_support: "FireSupportAssignment | None" = None
    fire_support_candidates: tuple["FireSupportAssignment", ...] = ()
    assignments: tuple["MissionAssignment", ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        """Return an audit-safe explanation of the assignment."""

        metadata = {
            "target_domain": self.target_domain.value,
            "strategic_effect": self.effect.value,
            "selected_mission_type": self.selected.mission_type,
            "selected_cohort_id": self.selected_cohort_id,
            "mission_candidates": [candidate.mission_type for candidate in self.candidates],
            "selection_rationale": self.selected.rationale,
            "selection_basis": "doctrinal_mission_then_weighted_cohort_score",
        }
        if self.fire_support is not None:
            metadata["fire_support"] = self.fire_support.to_dict()
        if self.fire_support_candidates:
            metadata["fire_support_candidates"] = [item.to_dict() for item in self.fire_support_candidates]
        if self.assignments:
            metadata["mission_assignments"] = [item.to_dict() for item in self.assignments]
            selected_assignment = next(
                (
                    item
                    for item in self.assignments
                    if item.mission_type == self.selected.mission_type
                    and item.cohort_id == self.selected_cohort_id
                    and (
                        self.fire_support is None
                        or item.weapon_flag == self.fire_support.weapon_flag
                    )
                ),
                None,
            )
            metadata["estimated_time_to_effect_s"] = (
                selected_assignment.estimated_time_to_effect_s if selected_assignment else None
            )
            metadata["selection_score"] = selected_assignment.selection_score if selected_assignment else None
        return metadata


@dataclass(slots=True, frozen=True)
class FireSupportAssignment:
    """Range- and ammunition-qualified ARTY assignment for one COHORT."""

    cohort_id: str
    dcs_type: str
    weapon_flag: DcsWeaponFlag
    minimum_m: float
    maximum_m: float
    distance_m: float
    engage_range_m: float
    mission_range_m: float
    moose_weapon_range_m: float
    required_relocation_m: float
    configured_minimum_m: float | None
    configured_maximum_m: float | None
    range_sync_required: bool
    range_source: RangeSource
    ammunition_source: str
    available_assets: int
    mission_performance: float | None
    current_rounds: int | None = None
    weapon_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "dcs_type": self.dcs_type,
            "weapon_flag": self.weapon_flag.name,
            "weapon_flag_value": int(self.weapon_flag),
            "minimum_m": self.minimum_m,
            "maximum_m": self.maximum_m,
            "distance_m": self.distance_m,
            "engage_range_m": self.engage_range_m,
            "mission_range_m": self.mission_range_m,
            "moose_weapon_range_m": self.moose_weapon_range_m,
            "required_relocation_m": self.required_relocation_m,
            "requires_relocation": self.required_relocation_m > 0,
            "configured_minimum_m": self.configured_minimum_m,
            "configured_maximum_m": self.configured_maximum_m,
            "range_sync_required": self.range_sync_required,
            "range_source": self.range_source.value,
            "ammunition_source": self.ammunition_source,
            "available_assets": self.available_assets,
            "mission_performance": self.mission_performance,
            "current_rounds": self.current_rounds,
            "weapon_ids": list(self.weapon_ids),
        }


@dataclass(slots=True, frozen=True)
class MissionTimingAssumptions:
    """Fallback speeds and preparation delays for estimated time to effect."""

    air_speed_mps: float = 200.0
    ground_speed_mps: float = 10.0
    naval_speed_mps: float = 12.0
    artillery_relocation_speed_mps: float = 8.33
    air_preparation_s: float = 300.0
    ground_preparation_s: float = 60.0
    naval_preparation_s: float = 120.0
    artillery_preparation_s: float = 120.0

    def __post_init__(self) -> None:
        for name in (
            "air_speed_mps",
            "ground_speed_mps",
            "naval_speed_mps",
            "artillery_relocation_speed_mps",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in (
            "air_preparation_s",
            "ground_preparation_s",
            "naval_preparation_s",
            "artillery_preparation_s",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(slots=True, frozen=True)
class MissionScoringAssumptions:
    """Weights and stable normalization values for COHORT assignment scoring."""

    mission_performance_weight: float = 0.50
    skill_weight: float = 0.30
    response_weight: float = 0.20
    response_reference_time_s: float = 900.0
    unknown_performance_score: float = 50.0
    unknown_skill_score: float = 60.0
    unknown_response_score: float = 50.0

    def __post_init__(self) -> None:
        weights = (
            self.mission_performance_weight,
            self.skill_weight,
            self.response_weight,
        )
        if any(not math.isfinite(value) or value < 0 for value in weights):
            raise ValueError("mission scoring weights must be finite and non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError("mission scoring weights must sum to 1.0")
        if not math.isfinite(self.response_reference_time_s) or self.response_reference_time_s <= 0:
            raise ValueError("response_reference_time_s must be finite and positive")
        for name in (
            "unknown_performance_score",
            "unknown_skill_score",
            "unknown_response_score",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0 or value > 100:
                raise ValueError(f"{name} must be between 0 and 100")


@dataclass(slots=True, frozen=True)
class MissionAssignment:
    """One executable COHORT/AUFTRAG option with transparent selection scores."""

    mission_type: str
    cohort_id: str
    estimated_time_to_effect_s: float | None
    preparation_time_s: float | None
    transit_distance_m: float | None
    transit_speed_mps: float | None
    weapon_flag: DcsWeaponFlag | None = None
    mission_performance: float | None = None
    cohort_skill: str | float | None = None
    performance_score: float = 0.0
    skill_score: float = 0.0
    response_score: float = 0.0
    selection_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_type": self.mission_type,
            "cohort_id": self.cohort_id,
            "estimated_time_to_effect_s": self.estimated_time_to_effect_s,
            "preparation_time_s": self.preparation_time_s,
            "transit_distance_m": self.transit_distance_m,
            "transit_speed_mps": self.transit_speed_mps,
            "weapon_flag": self.weapon_flag.name if self.weapon_flag is not None else None,
            "weapon_flag_value": int(self.weapon_flag) if self.weapon_flag is not None else None,
            "mission_performance": self.mission_performance,
            "cohort_skill": self.cohort_skill,
            "performance_score": self.performance_score,
            "skill_score": self.skill_score,
            "response_score": self.response_score,
            "selection_score": self.selection_score,
        }


_AIR_DEFENSE_ATTRIBUTES = {
    "aaa",
    "air defence",
    "air defence vehicles",
    "ewr",
    "radar",
    "sam",
    "sam ll",
    "sam sr",
    "sam tr",
}

_INDIRECT_FIRE_FLAGS = {
    DcsWeaponFlag.CONVENTIONAL_SHELL,
    DcsWeaponFlag.GUIDED_SHELL,
    DcsWeaponFlag.SUBMUNITION_DISPENSER_SHELL,
    DcsWeaponFlag.ANY_SHELL,
    DcsWeaponFlag.ANY_ROCKET,
    DcsWeaponFlag.HEAVY_ROCKET,
}

_INDIRECT_FIRE_ROLES = {
    WeaponRole.ARTILLERY,
    WeaponRole.MORTAR,
    WeaponRole.ROCKET_ARTILLERY,
    WeaponRole.SURFACE_TO_SURFACE,
}

_RANGE_SOURCE_PRIORITY = {
    RangeSource.MANUAL: 0,
    RangeSource.DCS_DATAMINE_WEAPON: 1,
    RangeSource.DCS_DESCRIPTOR: 2,
    RangeSource.DCS_DATAMINE_UNIT: 3,
    RangeSource.ROLE_FALLBACK: 4,
    RangeSource.FLAG_FALLBACK: 5,
}


def _candidate(
    mission_type: str,
    role: AssetRole,
    categories: tuple[str, ...],
    require_payload: bool,
    rationale: str,
) -> MissionCandidate:
    return MissionCandidate(mission_type, role, categories, require_payload, rationale)


class StrategicMissionResolver:
    """Resolve a strategic effect and target object to one executable AUFTRAG type."""

    def __init__(
        self,
        timing: MissionTimingAssumptions | None = None,
        scoring: MissionScoringAssumptions | None = None,
    ) -> None:
        self.timing = timing or MissionTimingAssumptions()
        self.scoring = scoring or MissionScoringAssumptions()

    def resolve(
        self,
        target_object_id: str,
        *,
        effect: StrategicGoalEffect | str | None = None,
        target_data: Mapping[str, Any] | None = None,
        cohorts: Iterable[Cohort] = (),
        legions: Iterable[Legion] = (),
        ammunition: Iterable[UnitAmmunition] = (),
        weapon_ranges: WeaponRangeRegistry = DEFAULT_WEAPON_RANGE_REGISTRY,
    ) -> MissionResolution:
        """Return ordered candidates and select the first currently supported option."""

        target_object_id = target_object_id.strip()
        if not target_object_id or ":" not in target_object_id:
            raise ValueError("mission resolution requires a stable target object id")
        cohort_items = tuple(cohorts)
        legion_items = tuple(legions)
        ammunition_items = tuple(ammunition)
        domain = classify_strategic_target(target_object_id, target_data)
        resolved_effect = StrategicGoalEffect(effect) if effect is not None else self._default_effect(domain)
        candidates = self._candidates(domain, resolved_effect, target_data)
        fire_support = self._fire_support_assignments(
            domain,
            target_data,
            cohorts=cohort_items,
            legions=legion_items,
            ammunition=ammunition_items,
            weapon_ranges=weapon_ranges,
        )
        if fire_support:
            candidates = (
                *candidates,
                _candidate(
                    "ARTY",
                    AssetRole.FIRES,
                    ("GROUND", "NAVAL"),
                    False,
                    "ARTY is qualified by ammunition evidence and a valid task range.",
                ),
            )
        if not candidates:
            raise ValueError(
                f"no conservative AUFTRAG mapping for effect={resolved_effect.value} "
                f"target={target_object_id} domain={domain.value}"
            )
        assignments = self._mission_assignments(
            candidates,
            cohort_items,
            legion_items,
            target_data,
            fire_support=fire_support,
        )
        selected, cohort_id, selected_weapon_flag = self._select_available(candidates, assignments)
        selected_fire_support = next(
            (
                item
                for item in fire_support
                if selected.mission_type == "ARTY"
                and item.cohort_id == cohort_id
                and item.weapon_flag == selected_weapon_flag
            ),
            None,
        )
        return MissionResolution(
            target_object_id=target_object_id,
            target_domain=domain,
            effect=resolved_effect,
            candidates=candidates,
            selected=selected,
            selected_cohort_id=cohort_id,
            fire_support=selected_fire_support,
            fire_support_candidates=fire_support,
            assignments=assignments,
        )

    @staticmethod
    def _default_effect(domain: StrategicTargetDomain) -> StrategicGoalEffect:
        if domain is StrategicTargetDomain.NAVAL:
            return StrategicGoalEffect.DESTROY_SHIP
        if domain is StrategicTargetDomain.SCENERY:
            return StrategicGoalEffect.ATTACK_MAP_OBJECT
        if domain is StrategicTargetDomain.STATIC:
            return StrategicGoalEffect.DESTROY_INFRASTRUCTURE
        return StrategicGoalEffect.DESTROY_OBJECT

    def _candidates(
        self,
        domain: StrategicTargetDomain,
        effect: StrategicGoalEffect,
        target_data: Mapping[str, Any] | None,
    ) -> tuple[MissionCandidate, ...]:
        if effect is StrategicGoalEffect.DENY_RUNWAY:
            if domain is not StrategicTargetDomain.AIRBASE:
                raise ValueError("deny_runway requires an AIRBASE target")
            category = str((target_data or {}).get("category") or "").strip().lower()
            if category != "airdrome":
                raise ValueError("deny_runway requires an AIRBASE with category Airdrome")
            return (
                _candidate(
                    "BOMBRUNWAY",
                    AssetRole.COMBAT,
                    ("AIR",),
                    True,
                    "BOMBRUNWAY is the object-targeted MOOSE mission for denying an airdrome runway.",
                ),
            )

        if effect is StrategicGoalEffect.SUPPRESS_AIR_DEFENSE:
            if domain not in {StrategicTargetDomain.GROUND, StrategicTargetDomain.UNKNOWN}:
                raise ValueError("suppress_air_defense requires a ground GROUP or UNIT target")
            return (
                _candidate("SEAD", AssetRole.SEAD, ("AIR",), True, "SEAD is specialized for air-defense targets."),
                _candidate("BAI", AssetRole.COMBAT, ("AIR",), True, "BAI can destroy the exact ground object."),
                _candidate(
                    "GROUNDATTACK",
                    AssetRole.COMBAT,
                    ("GROUND",),
                    False,
                    "Ground forces can attack the exact positionable target.",
                ),
            )

        if effect is StrategicGoalEffect.DESTROY_SHIP:
            if domain is not StrategicTargetDomain.NAVAL:
                raise ValueError("destroy_ship requires a naval GROUP or UNIT target")
            return (
                _candidate("ANTISHIP", AssetRole.COMBAT, ("AIR",), True, "ANTISHIP is specialized for naval targets."),
                _candidate(
                    "NAVALENGAGEMENT",
                    AssetRole.COMBAT,
                    ("NAVAL",),
                    False,
                    "Naval forces can engage the exact positionable target.",
                ),
            )

        if effect is StrategicGoalEffect.ATTACK_MAP_OBJECT:
            if domain is not StrategicTargetDomain.SCENERY:
                raise ValueError("attack_map_object requires a SCENERY target")
            return (
                _candidate(
                    "STRIKE",
                    AssetRole.COMBAT,
                    ("AIR",),
                    True,
                    "STRIKE uses the DCS attackMapObject task for scenery objects.",
                ),
            )

        if effect is StrategicGoalEffect.DAMAGE_AREA:
            return (
                _candidate("BOMBING", AssetRole.COMBAT, ("AIR",), True, "BOMBING attacks a known target coordinate."),
                _candidate(
                    "BOMBCARPET",
                    AssetRole.COMBAT,
                    ("AIR",),
                    True,
                    "BOMBCARPET distributes effects over an area around the target.",
                ),
            )

        if domain is StrategicTargetDomain.AIR:
            return (
                _candidate("INTERCEPT", AssetRole.AIR_SUPERIORITY, ("AIR",), True, "INTERCEPT targets an airborne GROUP or UNIT."),
            )
        if domain is StrategicTargetDomain.NAVAL:
            return self._candidates(domain, StrategicGoalEffect.DESTROY_SHIP, target_data)
        if domain is StrategicTargetDomain.GROUND:
            attributes = _normalized_attributes(target_data)
            if attributes.intersection(_AIR_DEFENSE_ATTRIBUTES):
                return self._candidates(domain, StrategicGoalEffect.SUPPRESS_AIR_DEFENSE, target_data)
            return (
                _candidate("BAI", AssetRole.COMBAT, ("AIR",), True, "BAI attacks the exact ground GROUP or UNIT."),
                _candidate(
                    "GROUNDATTACK",
                    AssetRole.COMBAT,
                    ("GROUND",),
                    False,
                    "Ground forces can attack the exact positionable target.",
                ),
            )
        if domain is StrategicTargetDomain.STATIC:
            return (
                _candidate("BAI", AssetRole.COMBAT, ("AIR",), True, "BAI attacks the exact static object."),
                _candidate("BOMBING", AssetRole.COMBAT, ("AIR",), True, "BOMBING attacks known static infrastructure."),
                _candidate(
                    "GROUNDATTACK",
                    AssetRole.COMBAT,
                    ("GROUND",),
                    False,
                    "Ground forces can attack a reachable static object.",
                ),
                _candidate(
                    "NAVALENGAGEMENT",
                    AssetRole.COMBAT,
                    ("NAVAL",),
                    False,
                    "Naval forces can attack a reachable static object.",
                ),
            )
        if domain is StrategicTargetDomain.SCENERY:
            return self._candidates(domain, StrategicGoalEffect.ATTACK_MAP_OBJECT, target_data)
        if domain is StrategicTargetDomain.UNKNOWN:
            return (
                _candidate("BAI", AssetRole.COMBAT, ("AIR",), True, "BAI is the conservative positionable-object default."),
                _candidate("GROUNDATTACK", AssetRole.COMBAT, ("GROUND",), False, "Ground attack is available for positionable objects."),
            )
        return ()

    def _mission_assignments(
        self,
        candidates: tuple[MissionCandidate, ...],
        cohorts: tuple[Cohort, ...],
        legions: tuple[Legion, ...],
        target_data: Mapping[str, Any] | None,
        *,
        fire_support: tuple[FireSupportAssignment, ...] = (),
    ) -> tuple[MissionAssignment, ...]:
        target_x = _finite_coordinate((target_data or {}).get("x"))
        target_z = _finite_coordinate((target_data or {}).get("z"))
        legion_positions = {
            item.object_id: (item.x, item.z)
            for item in legions
            if item.x is not None and item.z is not None
        }
        candidate_priority = {item.mission_type: index for index, item in enumerate(candidates)}
        cohort_by_id = {item.object_id: item for item in cohorts}
        fire_priority = {
            (item.cohort_id, item.weapon_flag): index for index, item in enumerate(fire_support)
        }

        def build_assignment(
            candidate: MissionCandidate,
            cohort: Cohort,
            eta: float | None,
            preparation: float | None,
            distance: float | None,
            speed: float | None,
            weapon_flag: DcsWeaponFlag | None = None,
        ) -> MissionAssignment:
            performance = cohort.mission_performance_for(candidate.mission_type)
            performance_score = _bounded_score(
                performance,
                default=self.scoring.unknown_performance_score,
            )
            skill_score = _skill_score(cohort.skill, default=self.scoring.unknown_skill_score)
            response_score = (
                100.0 / (1.0 + eta / self.scoring.response_reference_time_s)
                if eta is not None
                else self.scoring.unknown_response_score
            )
            selection_score = (
                self.scoring.mission_performance_weight * performance_score
                + self.scoring.skill_weight * skill_score
                + self.scoring.response_weight * response_score
            )
            return MissionAssignment(
                mission_type=candidate.mission_type,
                cohort_id=cohort.object_id,
                estimated_time_to_effect_s=eta,
                preparation_time_s=preparation,
                transit_distance_m=distance,
                transit_speed_mps=speed,
                weapon_flag=weapon_flag,
                mission_performance=performance,
                cohort_skill=cohort.skill,
                performance_score=performance_score,
                skill_score=skill_score,
                response_score=response_score,
                selection_score=selection_score,
            )

        assignments: list[MissionAssignment] = []
        for candidate in candidates:
            if candidate.mission_type == "ARTY":
                for support in fire_support:
                    cohort = cohort_by_id.get(support.cohort_id)
                    if cohort is None:
                        continue
                    preparation = self.timing.artillery_preparation_s
                    speed = self.timing.artillery_relocation_speed_mps
                    assignments.append(
                        build_assignment(
                            candidate,
                            cohort,
                            preparation + support.required_relocation_m / speed,
                            preparation,
                            support.required_relocation_m,
                            speed,
                            support.weapon_flag,
                        )
                    )
                continue
            for cohort in cohorts:
                if not (
                    (cohort.available_asset_count or 0) > 0
                and candidate.mission_type in cohort.mission_type_keys
                and platform_categories_match(cohort.performer_categories, candidate.performer_categories)
                and (not candidate.require_payload or cohort.has_payload_for(candidate.mission_type) is True)
                ):
                    continue
                origin = (
                    (cohort.x, cohort.z)
                    if cohort.x is not None and cohort.z is not None
                    else legion_positions.get(cohort.legion_id or "")
                )
                if target_x is None or target_z is None or origin is None:
                    distance = None
                else:
                    distance = math.hypot(target_x - origin[0], target_z - origin[1])
                speed, preparation = self._platform_timing(cohort)
                eta = preparation + distance / speed if distance is not None else None
                assignments.append(
                    build_assignment(candidate, cohort, eta, preparation, distance, speed)
                )
        return tuple(
            sorted(
                assignments,
                key=lambda item: (
                    candidate_priority[item.mission_type],
                    -item.selection_score,
                    item.estimated_time_to_effect_s is None,
                    item.estimated_time_to_effect_s if item.estimated_time_to_effect_s is not None else math.inf,
                    fire_priority.get((item.cohort_id, item.weapon_flag), math.inf),
                    item.cohort_id,
                ),
            )
        )

    def _platform_timing(self, cohort: Cohort) -> tuple[float, float]:
        if cohort.is_air:
            return self.timing.air_speed_mps, self.timing.air_preparation_s
        if cohort.is_naval:
            return self.timing.naval_speed_mps, self.timing.naval_preparation_s
        return self.timing.ground_speed_mps, self.timing.ground_preparation_s

    @staticmethod
    def _select_available(
        candidates: tuple[MissionCandidate, ...],
        assignments: tuple[MissionAssignment, ...],
    ) -> tuple[MissionCandidate, str | None, DcsWeaponFlag | None]:
        for candidate in candidates:
            assignment = next(
                (item for item in assignments if item.mission_type == candidate.mission_type),
                None,
            )
            if assignment is not None:
                return candidate, assignment.cohort_id, assignment.weapon_flag
        return candidates[0], None, None

    @staticmethod
    def _fire_support_assignments(
        domain: StrategicTargetDomain,
        target_data: Mapping[str, Any] | None,
        *,
        cohorts: Iterable[Cohort],
        legions: Iterable[Legion],
        ammunition: Iterable[UnitAmmunition],
        weapon_ranges: WeaponRangeRegistry,
    ) -> tuple[FireSupportAssignment, ...]:
        if domain not in {StrategicTargetDomain.GROUND, StrategicTargetDomain.STATIC}:
            return ()
        target_x = _finite_coordinate((target_data or {}).get("x"))
        target_z = _finite_coordinate((target_data or {}).get("z"))
        speed_mps = _finite_coordinate((target_data or {}).get("speed_mps")) or 0.0
        if target_x is None or target_z is None or (domain is StrategicTargetDomain.GROUND and speed_mps > 1.0):
            return ()

        legion_positions = {
            legion.object_id: (legion.x, legion.z)
            for legion in legions
            if legion.x is not None and legion.z is not None
        }
        ammunition_by_type: dict[str, list[UnitAmmunition]] = {}
        for unit in ammunition:
            if unit.dcs_type:
                ammunition_by_type.setdefault(unit.dcs_type.casefold(), []).append(unit)

        assignments: list[FireSupportAssignment] = []
        for cohort in cohorts:
            if (
                (cohort.available_asset_count or 0) <= 0
                or "ARTY" not in cohort.mission_type_keys
                or not cohort.unit_type
            ):
                continue
            origin = (
                (cohort.x, cohort.z)
                if cohort.x is not None and cohort.z is not None
                else legion_positions.get(cohort.legion_id or "")
            )
            if origin is None or origin[0] is None or origin[1] is None:
                continue
            distance_m = math.hypot(target_x - origin[0], target_z - origin[1])
            spawned_group_names = {_object_name(item) for item in cohort.opsgroup_ids}
            observed = [
                unit
                for unit in ammunition_by_type.get(cohort.unit_type.casefold(), [])
                if unit.group_id is not None and _object_name(unit.group_id) in spawned_group_names
            ]
            profiles = list(weapon_ranges.profiles_for_type(cohort.unit_type))
            for unit in observed:
                for weapon in unit.weapons:
                    for association in weapon.weapon_flags:
                        if association.flag not in _INDIRECT_FIRE_FLAGS:
                            continue
                        profile = weapon_ranges.resolve(
                            cohort.unit_type,
                            association.flag,
                            ammunition=unit.weapons,
                        )
                        if profile is not None:
                            profiles.append(profile)
            unique_profiles: dict[tuple[DcsWeaponFlag, float, float], WeaponRangeProfile] = {}
            for profile in profiles:
                if profile.weapon_flag not in _INDIRECT_FIRE_FLAGS:
                    continue
                key = (profile.weapon_flag, profile.minimum_m, profile.maximum_m)
                previous = unique_profiles.get(key)
                if previous is None or _RANGE_SOURCE_PRIORITY[profile.source] < _RANGE_SOURCE_PRIORITY[previous.source]:
                    unique_profiles[key] = profile
            for profile in sorted(
                unique_profiles.values(),
                key=lambda item: (
                    _RANGE_SOURCE_PRIORITY[item.source],
                    item.maximum_m - item.minimum_m,
                    int(item.weapon_flag),
                ),
            ):
                engage_range_m = cohort.engage_range_m
                if engage_range_m is None:
                    continue
                configured_range = cohort.weapon_range_for_weapon_type(profile.weapon_flag)
                configured_minimum_m = configured_range[0] if configured_range is not None else None
                configured_maximum_m = configured_range[1] if configured_range is not None else None
                range_sync_required = configured_range is None or (
                    abs(configured_range[0] - profile.minimum_m) > 1.0
                    or abs(configured_range[1] - profile.maximum_m) > 1.0
                )
                mission_range_m = engage_range_m + profile.maximum_m
                if distance_m > mission_range_m:
                    continue
                moose_weapon_range_m = (
                    configured_maximum_m
                    if configured_maximum_m is not None
                    else profile.maximum_m
                )
                if distance_m < profile.minimum_m:
                    required_relocation_m = profile.minimum_m - distance_m
                elif distance_m > profile.maximum_m:
                    required_relocation_m = distance_m - profile.maximum_m
                else:
                    required_relocation_m = 0.0
                if required_relocation_m > engage_range_m:
                    continue
                current_weapons = tuple(
                    weapon
                    for unit in observed
                    for weapon in unit.weapons
                    if weapon.current_count > 0
                    and weapon.role in _INDIRECT_FIRE_ROLES
                    and profile.weapon_flag in {association.flag for association in weapon.weapon_flags}
                )
                if observed and not current_weapons:
                    continue
                assignments.append(
                    FireSupportAssignment(
                        cohort_id=cohort.object_id,
                        dcs_type=cohort.unit_type,
                        weapon_flag=profile.weapon_flag,
                        minimum_m=profile.minimum_m,
                        maximum_m=profile.maximum_m,
                        distance_m=distance_m,
                        engage_range_m=engage_range_m,
                        mission_range_m=mission_range_m,
                        moose_weapon_range_m=moose_weapon_range_m,
                        required_relocation_m=required_relocation_m,
                        configured_minimum_m=configured_minimum_m,
                        configured_maximum_m=configured_maximum_m,
                        range_sync_required=range_sync_required,
                        range_source=profile.source,
                        ammunition_source="observed_current" if observed else "cohort_template_assumed_full",
                        available_assets=cohort.available_asset_count or 0,
                        mission_performance=cohort.mission_performance_for("ARTY"),
                        current_rounds=(sum(weapon.current_count for weapon in current_weapons) if observed else None),
                        weapon_ids=(
                            tuple(sorted({weapon.id for weapon in current_weapons}))
                            if observed
                            else profile.weapon_ids
                        ),
                    )
                )
        return tuple(sorted(assignments, key=_fire_support_rank))


def _fire_support_rank(item: FireSupportAssignment) -> tuple[Any, ...]:
    """Rank feasible fire support without inventing weapon-effect preferences."""

    observed_ammunition = item.ammunition_source == "observed_current"
    rounds = item.current_rounds if item.current_rounds is not None else -1
    performance = item.mission_performance if item.mission_performance is not None else 0.0
    return (
        item.required_relocation_m > 1.0,
        item.required_relocation_m,
        not observed_ammunition,
        -rounds,
        -performance,
        _RANGE_SOURCE_PRIORITY[item.range_source],
        item.range_sync_required,
        -item.available_assets,
        item.cohort_id,
        int(item.weapon_flag),
    )


def _bounded_score(value: float | int | None, *, default: float) -> float:
    if value is None:
        return default
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(score):
        return default
    return min(100.0, max(0.0, score))


def _skill_score(value: str | float | None, *, default: float) -> float:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        named_scores = {
            "average": 40.0,
            "good": 60.0,
            "high": 80.0,
            "excellent": 100.0,
            "random": default,
            "client": 100.0,
            "player": 100.0,
        }
        if normalized in named_scores:
            return named_scores[normalized]
        try:
            value = float(normalized)
        except ValueError:
            return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            return default
        if 0.0 <= numeric <= 1.0:
            numeric *= 100.0
        return min(100.0, max(0.0, numeric))
    return default


def _object_name(object_id: str) -> str:
    return object_id.partition(":")[2].strip().casefold()


def classify_strategic_target(
    target_object_id: str,
    target_data: Mapping[str, Any] | None = None,
) -> StrategicTargetDomain:
    """Classify one stable bridge object id using its DCS/MOOSE category."""

    prefix = target_object_id.partition(":")[0].strip().upper()
    if prefix == "AIRBASE":
        return StrategicTargetDomain.AIRBASE
    if prefix in {"SCENERY", "MAPOBJECT"}:
        return StrategicTargetDomain.SCENERY
    if prefix == "STATIC":
        return StrategicTargetDomain.STATIC
    if prefix not in {"GROUP", "UNIT"}:
        return StrategicTargetDomain.UNKNOWN

    payload = target_data or {}
    category = str(payload.get("category") or payload.get("object_category") or "").strip().lower()
    if category in {"airplane", "helicopter", "air", "plane"}:
        return StrategicTargetDomain.AIR
    if category in {"ground unit", "ground", "vehicle"}:
        return StrategicTargetDomain.GROUND
    if category in {"ship", "naval"}:
        return StrategicTargetDomain.NAVAL
    attributes = _normalized_attributes(payload)
    if attributes.intersection({"planes", "helicopters"}):
        return StrategicTargetDomain.AIR
    if attributes.intersection({"ships", "heavy armed ships", "light armed ships"}):
        return StrategicTargetDomain.NAVAL
    if attributes.intersection({"ground units", "ground vehicles", "vehicles"}):
        return StrategicTargetDomain.GROUND
    return StrategicTargetDomain.UNKNOWN


def _normalized_attributes(target_data: Mapping[str, Any] | None) -> set[str]:
    raw = (target_data or {}).get("attributes")
    if isinstance(raw, Mapping):
        values = [key for key, enabled in raw.items() if enabled]
    elif isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = ()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _finite_coordinate(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "MissionCandidate",
    "MissionResolution",
    "FireSupportAssignment",
    "StrategicMissionResolver",
    "StrategicTargetDomain",
    "classify_strategic_target",
]
