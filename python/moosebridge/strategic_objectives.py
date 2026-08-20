"""Automatic strategic-objective generation from mission and theater data."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import math
from typing import Any

from .infrastructure_sites import (
    FuelStorageSite,
    MaritimeSite,
    TheaterInfrastructureSites,
)
from .railway_infrastructure import TheaterRailwayInfrastructure
from .settlements import TheaterSettlements
from .state import MooseBridgeState
from .strategic import (
    ComponentHealthEstimate,
    ObjectiveComponent,
    ObjectiveKind,
    ObjectiveStatus,
    OwnershipPolicy,
    StrategicObjective,
)
from .strategic_scope import StrategicScopeState, StrategicTerritoryScope
from .strategic_verification import StrategicVerificationRegistry
from .theater_context import TheaterContext
from .transport_infrastructure import (
    TheaterTransportInfrastructure,
    TransportBridge,
    TransportJunction,
)


@dataclass(slots=True, frozen=True)
class StrategicObjectiveGenerationConfig:
    """Conservative admission thresholds for automatic objectives."""

    include_airbases: bool = True
    include_opszones: bool = True
    minimum_settlement_importance: float = 50.0
    minimum_transport_importance: float = 50.0
    minimum_railway_importance: float = 50.0
    minimum_site_importance: float = 50.0
    include_unscored_fuel_storage: bool = True
    include_contested: bool = True
    maximum_geographic_objectives_per_category_per_scope: int | None = 10

    def __post_init__(self) -> None:
        for value in (
            self.minimum_settlement_importance,
            self.minimum_transport_importance,
            self.minimum_railway_importance,
            self.minimum_site_importance,
        ):
            if not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError("objective importance thresholds must be between zero and 100")
        limit = self.maximum_geographic_objectives_per_category_per_scope
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise ValueError("geographic objective limit must be a positive integer or None")


@dataclass(slots=True, frozen=True)
class StrategicObjectiveExclusion:
    """One candidate deliberately excluded from automatic generation."""

    object_id: str
    reason: str
    scope_state: StrategicScopeState | None = None


@dataclass(slots=True, frozen=True)
class StrategicObjectiveGenerationResult:
    """Generated objectives plus auditable admission diagnostics."""

    objectives: tuple[StrategicObjective, ...]
    exclusions: tuple[StrategicObjectiveExclusion, ...] = ()
    candidate_count: int = 0
    counts_by_scope: dict[str, int] = field(default_factory=dict)

    @property
    def out_of_scope_count(self) -> int:
        return sum(item.reason == "out_of_scope" for item in self.exclusions)

    @property
    def below_threshold_count(self) -> int:
        return sum(item.reason == "below_importance_threshold" for item in self.exclusions)

    @property
    def category_scope_limit_count(self) -> int:
        return sum(item.reason == "category_scope_limit" for item in self.exclusions)

    @property
    def verification_exclusion_count(self) -> int:
        return sum(
            item.reason in {
                "no_dcs_verification",
                "no_concrete_dcs_components",
                "dcs_verification_not_approved",
            }
            for item in self.exclusions
        )


def generate_strategic_objectives(
    state: MooseBridgeState,
    scope: StrategicTerritoryScope,
    *,
    settlements: TheaterSettlements | None = None,
    transport: TheaterTransportInfrastructure | None = None,
    railway: TheaterRailwayInfrastructure | None = None,
    infrastructure: TheaterInfrastructureSites | None = None,
    verifications: StrategicVerificationRegistry | None = None,
    config: StrategicObjectiveGenerationConfig | None = None,
) -> StrategicObjectiveGenerationResult:
    """Generate mission objectives admitted by the TERRITORY-derived scope."""

    scope.require_valid()
    scoped_sources = any(
        item is not None for item in (settlements, transport, railway, infrastructure)
    ) or bool(verifications is not None and verifications.theater_id.strip())
    if scoped_sources:
        TheaterContext.from_sources(
            settlements=settlements,
            transport=transport,
            railway=railway,
            infrastructure=infrastructure,
            verifications=verifications,
        )
    resolved = config or StrategicObjectiveGenerationConfig()
    objectives: list[StrategicObjective] = []
    exclusions: list[StrategicObjectiveExclusion] = []
    counts: dict[str, int] = {state.value: 0 for state in StrategicScopeState}
    def admit(
        *,
        source_id: str,
        name: str,
        kind: ObjectiveKind,
        scope_state: StrategicScopeState,
        strategic_value: float,
        ownership_policy: OwnershipPolicy = OwnershipPolicy.FIXED,
        control_object_id: str | None = None,
        owner: str | None = None,
        contested: bool = False,
        components: tuple[ObjectiveComponent, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> None:
        counts[scope_state.value] += 1
        if scope_state is StrategicScopeState.OUT_OF_SCOPE:
            exclusions.append(StrategicObjectiveExclusion(source_id, "out_of_scope", scope_state))
            return
        if scope_state is StrategicScopeState.CONTESTED and not resolved.include_contested:
            exclusions.append(StrategicObjectiveExclusion(source_id, "contested_excluded", scope_state))
            return
        effective_owner = owner
        if ownership_policy is OwnershipPolicy.FIXED:
            effective_owner = _owner_from_scope(scope_state)
        initial_component_health = (
            {
                component.object_id: ComponentHealthEstimate(
                    1.0,
                    "verified_scenery_baseline",
                )
                for component in components
                if component.object_id.startswith("SCENERY:")
            }
            if (metadata or {}).get("dcs_verification_state") == "represented"
            else {}
        )
        objectives.append(
            StrategicObjective(
                objective_id=f"OBJECTIVE:{source_id}",
                name=name,
                kind=kind,
                control_object_id=control_object_id,
                ownership_policy=ownership_policy,
                components=components,
                strategic_value=max(0.0, min(100.0, strategic_value)),
                priority=max(0.0, min(100.0, strategic_value)),
                owner=effective_owner,
                status=(
                    ObjectiveStatus.CONTESTED
                    if scope_state is StrategicScopeState.CONTESTED
                    else ObjectiveStatus.OPERATIONAL
                ),
                contested=contested or scope_state is StrategicScopeState.CONTESTED,
                component_health_estimates=initial_component_health,
                metadata={
                    "generated": True,
                    "source_object_id": source_id,
                    "scope_state": scope_state.value,
                    "targetable": (
                        any(component.is_destroy_target for component in components)
                        or control_object_id is not None
                    ),
                    **(metadata or {}),
                },
            )
        )

    if resolved.include_airbases:
        for object_id, payload in sorted(state.airbases.items()):
            point_state = _classify_payload(scope, payload)
            category = str(payload.get("category") or "Airdrome")
            kind = ObjectiveKind.FARP if category.casefold() in {"helipad", "heliport"} else ObjectiveKind.AIRBASE
            admit(
                source_id=object_id,
                name=str(payload.get("name") or payload.get("dcs_name") or object_id.removeprefix("AIRBASE:")),
                kind=kind,
                scope_state=point_state,
                strategic_value=60.0 if kind is ObjectiveKind.FARP else 90.0,
                ownership_policy=OwnershipPolicy.DCS_MANAGED,
                control_object_id=object_id,
                owner=_coalition(payload.get("coalition")),
                metadata={"source_kind": "airbase", "airbase_category": category},
            )

    if resolved.include_opszones:
        for object_id, payload in sorted(state.opszones.items()):
            point_state = _classify_payload(scope, payload)
            admit(
                source_id=object_id,
                name=str(payload.get("name") or payload.get("dcs_name") or object_id.removeprefix("OPSZONE:")),
                kind=ObjectiveKind.OPSZONE,
                scope_state=point_state,
                strategic_value=float(payload.get("strategic_value") or 80.0),
                ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
                control_object_id=object_id,
                owner=_coalition(payload.get("owner_current_name")),
                contested=bool(payload.get("is_contested")),
                metadata={"source_kind": "opszone"},
            )

    for settlement in settlements.settlements if settlements else ():
        _admit_geographic_candidate(
            settlement,
            settlement.settlement_id,
            settlement.name,
            ObjectiveKind.TERRITORY,
            settlement.importance_score,
            resolved.minimum_settlement_importance,
            scope,
            admit,
            exclusions,
            metadata={"source_kind": "settlement", "settlement_kind": settlement.kind.value},
            selection_category="settlement",
            verifications=verifications,
        )

    if transport:
        for item in (*transport.bridges, *transport.junctions):
            source_id = item.bridge_id if isinstance(item, TransportBridge) else item.junction_id
            _admit_geographic_candidate(
                item,
                source_id,
                _candidate_name(item, source_id),
                ObjectiveKind.INFRASTRUCTURE,
                item.importance_score,
                resolved.minimum_transport_importance,
                scope,
                admit,
                exclusions,
                metadata={"source_kind": "transport", "infrastructure_kind": type(item).__name__},
                selection_category=(
                    "transport_bridge" if isinstance(item, TransportBridge) else "transport_junction"
                ),
                verifications=verifications,
            )

    for item in railway.locations if railway else ():
        _admit_geographic_candidate(
            item,
            item.location_id,
            _candidate_name(item, item.location_id),
            ObjectiveKind.INFRASTRUCTURE,
            item.importance_score,
            resolved.minimum_railway_importance,
            scope,
            admit,
            exclusions,
            metadata={"source_kind": "railway", "railway_kind": item.kind.value},
            selection_category="railway",
            verifications=verifications,
        )

    for site in infrastructure.sites if infrastructure else ():
        score = float(getattr(site, "importance_score", site.properties.get("importance_score", 0.0)) or 0.0)
        threshold = resolved.minimum_site_importance
        if isinstance(site, FuelStorageSite) and resolved.include_unscored_fuel_storage:
            score = score or 60.0
            threshold = 0.0
        kind = ObjectiveKind.PORT if isinstance(site, MaritimeSite) else (
            ObjectiveKind.DEPOT if isinstance(site, FuelStorageSite) else ObjectiveKind.INFRASTRUCTURE
        )
        _admit_geographic_candidate(
            site,
            site.site_id,
            _candidate_name(site, site.site_id),
            kind,
            score,
            threshold,
            scope,
            admit,
            exclusions,
            metadata={"source_kind": "infrastructure_site", "infrastructure_kind": site.kind.value},
            selection_category=f"infrastructure_{site.kind.value}",
            verifications=verifications,
        )

    objectives = _limit_geographic_objectives(
        objectives,
        exclusions,
        resolved.maximum_geographic_objectives_per_category_per_scope,
    )
    objectives.sort(key=lambda item: (-item.priority, item.objective_id))
    exclusions.sort(key=lambda item: (item.reason, item.object_id))
    return StrategicObjectiveGenerationResult(
        tuple(objectives), tuple(exclusions), len(objectives) + len(exclusions), counts
    )


def _admit_geographic_candidate(
    item: Any,
    source_id: str,
    name: str,
    kind: ObjectiveKind,
    score: float,
    threshold: float,
    scope: StrategicTerritoryScope,
    admit: Any,
    exclusions: list[StrategicObjectiveExclusion],
    *,
    metadata: dict[str, Any] | None = None,
    selection_category: str,
    verifications: StrategicVerificationRegistry | None,
) -> None:
    if score < threshold:
        exclusions.append(StrategicObjectiveExclusion(source_id, "below_importance_threshold"))
        return
    verification = verifications.get(source_id) if verifications is not None else None
    if verification is None:
        exclusions.append(StrategicObjectiveExclusion(source_id, "no_dcs_verification"))
        return
    if not verification.target_components:
        exclusions.append(StrategicObjectiveExclusion(source_id, "no_concrete_dcs_components"))
        return
    if not verification.admitted:
        exclusions.append(StrategicObjectiveExclusion(source_id, "dcs_site_not_represented"))
        return
    observed_by_id = {item.object_id: item for item in verification.observed_objects}
    components = tuple(
        ObjectiveComponent(
            component.object_id,
            role=component.role,
            weight=component.weight,
            metadata={
                key: value
                for key, value in {
                    "latitude": getattr(observed_by_id.get(component.object_id), "latitude", None),
                    "longitude": getattr(observed_by_id.get(component.object_id), "longitude", None),
                    "dcs_type": getattr(observed_by_id.get(component.object_id), "type_name", None),
                    "display_name": getattr(observed_by_id.get(component.object_id), "display_name", None),
                }.items()
                if value not in {None, ""}
            },
        )
        for component in verification.target_components
    )
    scope_state = scope.classify_geographic_point(item.latitude, item.longitude)
    admit(
        source_id=source_id,
        name=name,
        kind=kind,
        scope_state=scope_state,
        strategic_value=score,
        components=components,
        metadata={
            "latitude": item.latitude,
            "longitude": item.longitude,
            "source": getattr(item, "source", None),
            "selection_category": selection_category,
            "dcs_verification_state": verification.state.value,
            **(metadata or {}),
        },
    )


def _limit_geographic_objectives(
    objectives: list[StrategicObjective],
    exclusions: list[StrategicObjectiveExclusion],
    limit: int | None,
) -> list[StrategicObjective]:
    if limit is None:
        return objectives

    selected: list[StrategicObjective] = []
    grouped: dict[tuple[str, str], list[StrategicObjective]] = defaultdict(list)
    for objective in objectives:
        category = str(objective.metadata.get("selection_category") or "")
        scope_state = str(objective.metadata.get("scope_state") or "")
        if objective.control_object_id is not None or not category or not scope_state:
            selected.append(objective)
            continue
        grouped[(scope_state, category)].append(objective)

    for (scope_name, _category), candidates in sorted(grouped.items()):
        candidates.sort(key=lambda item: (-item.strategic_value, item.objective_id))
        scope_state = StrategicScopeState(scope_name)
        for rank, objective in enumerate(candidates, start=1):
            if rank <= limit:
                objective.metadata["selection_rank"] = rank
                objective.metadata["selection_limit"] = limit
                selected.append(objective)
            else:
                exclusions.append(
                    StrategicObjectiveExclusion(
                        str(objective.metadata.get("source_object_id") or objective.objective_id),
                        "category_scope_limit",
                        scope_state,
                    )
                )
    return selected


def _classify_payload(scope: StrategicTerritoryScope, payload: dict[str, Any]) -> StrategicScopeState:
    x, z = payload.get("x"), payload.get("z")
    if x is not None and z is not None:
        return scope.classify_point(float(x), float(z))
    latitude, longitude = payload.get("latitude"), payload.get("longitude")
    if latitude is not None and longitude is not None:
        return scope.classify_geographic_point(float(latitude), float(longitude))
    return StrategicScopeState.OUT_OF_SCOPE


def _owner_from_scope(state: StrategicScopeState) -> str | None:
    if state in {StrategicScopeState.BLUE, StrategicScopeState.RED, StrategicScopeState.NEUTRAL}:
        return state.value
    return None


def _coalition(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return {"0": "neutral", "1": "red", "2": "blue"}.get(normalized, normalized or None)


def _candidate_name(item: Any, fallback: str) -> str:
    return str(getattr(item, "name", None) or fallback.split(":")[-1].replace("_", " "))
