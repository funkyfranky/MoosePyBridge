"""Conservative mapping from strategic target effects to executable AUFTRAG types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .auftrag_specs import canonical_mission_type, platform_categories_match
from .legions import Cohort
from .operational import AssetRole
from .strategic import StrategicGoalEffect


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

    def to_metadata(self) -> dict[str, Any]:
        """Return an audit-safe explanation of the assignment."""

        return {
            "target_domain": self.target_domain.value,
            "strategic_effect": self.effect.value,
            "selected_mission_type": self.selected.mission_type,
            "selected_cohort_id": self.selected_cohort_id,
            "mission_candidates": [candidate.mission_type for candidate in self.candidates],
            "selection_rationale": self.selected.rationale,
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

    def resolve(
        self,
        target_object_id: str,
        *,
        effect: StrategicGoalEffect | str | None = None,
        target_data: Mapping[str, Any] | None = None,
        cohorts: Iterable[Cohort] = (),
    ) -> MissionResolution:
        """Return ordered candidates and select the first currently supported option."""

        target_object_id = target_object_id.strip()
        if not target_object_id or ":" not in target_object_id:
            raise ValueError("mission resolution requires a stable target object id")
        domain = classify_strategic_target(target_object_id, target_data)
        resolved_effect = StrategicGoalEffect(effect) if effect is not None else self._default_effect(domain)
        candidates = self._candidates(domain, resolved_effect, target_data)
        if not candidates:
            raise ValueError(
                f"no conservative AUFTRAG mapping for effect={resolved_effect.value} "
                f"target={target_object_id} domain={domain.value}"
            )
        selected, cohort_id = self._select_available(candidates, cohorts)
        return MissionResolution(
            target_object_id=target_object_id,
            target_domain=domain,
            effect=resolved_effect,
            candidates=candidates,
            selected=selected,
            selected_cohort_id=cohort_id,
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

    @staticmethod
    def _select_available(
        candidates: tuple[MissionCandidate, ...],
        cohorts: Iterable[Cohort],
    ) -> tuple[MissionCandidate, str | None]:
        cohort_items = tuple(cohorts)
        for candidate in candidates:
            matches = [
                cohort
                for cohort in cohort_items
                if (cohort.available_asset_count or 0) > 0
                and candidate.mission_type in cohort.mission_type_keys
                and platform_categories_match(cohort.performer_categories, candidate.performer_categories)
                and (not candidate.require_payload or cohort.has_payload_for(candidate.mission_type) is True)
            ]
            if matches:
                matches.sort(
                    key=lambda cohort: (
                        -(cohort.mission_performance_for(candidate.mission_type) or 0.0),
                        cohort.object_id,
                    )
                )
                return candidate, matches[0].object_id
        return candidates[0], None


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


__all__ = [
    "MissionCandidate",
    "MissionResolution",
    "StrategicMissionResolver",
    "StrategicTargetDomain",
    "classify_strategic_target",
]
