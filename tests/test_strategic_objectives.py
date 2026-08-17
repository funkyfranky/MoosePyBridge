"""Tests for scope-bounded automatic strategic-objective generation."""

from __future__ import annotations

from moosebridge.infrastructure_sites import (
    FuelStorageRole,
    FuelStorageSite,
    InfrastructureSiteKind,
    StoredCommodity,
    TheaterInfrastructureSites,
)
from moosebridge.models import Territory
from moosebridge.settlements import (
    Settlement,
    SettlementImportanceTier,
    SettlementKind,
    SettlementSizeClass,
    TheaterSettlements,
)
from moosebridge.state import MooseBridgeState
from moosebridge.strategic import ObjectiveKind, OwnershipPolicy
from moosebridge.strategic_objectives import (
    StrategicObjectiveGenerationConfig,
    generate_strategic_objectives,
)
from moosebridge.strategic_scope import StrategicScopeState, build_strategic_territory_scope
from moosebridge.strategic_verification import (
    ObservedDcsObject,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
    StrategicVerificationState,
    VerifiedDcsComponent,
)


def _verifications(*source_ids: str) -> StrategicVerificationRegistry:
    return StrategicVerificationRegistry.from_entries(
        StrategicSiteVerification(
            source_id=source_id,
            state=StrategicVerificationState.REPRESENTED,
            observed_objects=(ObservedDcsObject(f"SCENERY:Target-{index}"),),
            target_components=(VerifiedDcsComponent(f"SCENERY:Target-{index}"),),
        )
        for index, source_id in enumerate(source_ids)
    )


def _territory(object_id: str, coalition: str, bounds: tuple[float, float, float, float]) -> Territory:
    min_x, min_z, max_x, max_z = bounds
    return Territory.from_payload(
        {
            "object_id": object_id,
            "dcs_name": object_id.removeprefix("TERRITORY:"),
            "object_type": "TERRITORY",
            "coalition": coalition,
            "vertices": [
                {"x": min_x, "z": min_z, "longitude": min_x / 1000, "latitude": min_z / 1000},
                {"x": max_x, "z": min_z, "longitude": max_x / 1000, "latitude": min_z / 1000},
                {"x": max_x, "z": max_z, "longitude": max_x / 1000, "latitude": max_z / 1000},
                {"x": min_x, "z": max_z, "longitude": min_x / 1000, "latitude": max_z / 1000},
            ],
        }
    )


def _scope_and_state() -> tuple[object, MooseBridgeState]:
    territories = [
        _territory("TERRITORY:Neutral", "neutral", (0, 0, 100, 100)),
        _territory("TERRITORY:Blue", "blue", (0, 0, 40, 100)),
        _territory("TERRITORY:Red", "red", (60, 0, 100, 100)),
    ]
    state = MooseBridgeState()
    state.territory_objects = {item.object_id: item for item in territories}
    state.airbases = {
        "AIRBASE:Inside": {"object_id": "AIRBASE:Inside", "name": "Inside", "category": "Airdrome", "coalition": "blue", "x": 20, "z": 20},
        "AIRBASE:Outside": {"object_id": "AIRBASE:Outside", "name": "Outside", "category": "Airdrome", "coalition": "neutral", "x": 120, "z": 20},
    }
    state.opszones = {
        "OPSZONE:Center": {"object_id": "OPSZONE:Center", "name": "Center", "owner_current_name": "neutral", "x": 50, "z": 50},
    }
    return build_strategic_territory_scope(territories), state


def test_generator_admits_live_objects_only_inside_scope() -> None:
    scope, state = _scope_and_state()

    result = generate_strategic_objectives(state, scope)  # type: ignore[arg-type]
    by_id = {item.objective_id: item for item in result.objectives}

    airbase = by_id["OBJECTIVE:AIRBASE:Inside"]
    assert airbase.kind is ObjectiveKind.AIRBASE
    assert airbase.ownership_policy is OwnershipPolicy.DCS_MANAGED
    assert airbase.owner == "blue"
    assert by_id["OBJECTIVE:OPSZONE:Center"].owner == "neutral"
    assert "OBJECTIVE:AIRBASE:Outside" not in by_id
    assert result.out_of_scope_count == 1
    assert result.counts_by_scope[StrategicScopeState.BLUE.value] == 1


def test_generator_applies_importance_threshold_and_preserves_dcs_components() -> None:
    scope, state = _scope_and_state()
    settlements = TheaterSettlements(
        theater_id="Test",
        settlements=(
            Settlement(
                settlement_id="SETTLEMENT:Important",
                name="Important",
                kind=SettlementKind.CITY,
                size_class=SettlementSizeClass.LARGE_CITY,
                geometry={"type": "Point", "coordinates": [0.05, 0.05]},
                latitude=0.05,
                longitude=0.05,
                source="OpenStreetMap",
                confidence=0.8,
                importance_score=75,
                importance_tier=SettlementImportanceTier.HIGH,
            ),
            Settlement(
                settlement_id="SETTLEMENT:Local",
                name="Local",
                kind=SettlementKind.TOWN,
                size_class=SettlementSizeClass.LAND_TOWN,
                geometry={"type": "Point", "coordinates": [0.05, 0.06]},
                latitude=0.06,
                longitude=0.05,
                source="OpenStreetMap",
                confidence=0.8,
                importance_score=20,
                importance_tier=SettlementImportanceTier.LOCAL,
            ),
        ),
    )
    sites = TheaterInfrastructureSites(
        theater_id="Test",
        sites=(
            FuelStorageSite(
                site_id="FUEL_STORAGE_SITE:Depot",
                kind=InfrastructureSiteKind.FUEL_STORAGE,
                geometry={"type": "Point", "coordinates": [0.07, 0.05]},
                latitude=0.05,
                longitude=0.07,
                source="OpenStreetMap",
                confidence=0.8,
                component_ids=("SCENERY:123",),
                storage_roles=(FuelStorageRole.TANK_FARM,),
                commodities=(StoredCommodity.PETROLEUM,),
            ),
        ),
    )

    result = generate_strategic_objectives(
        state,
        scope,  # type: ignore[arg-type]
        settlements=settlements,
        infrastructure=sites,
        verifications=StrategicVerificationRegistry.from_entries((
            StrategicSiteVerification(
                source_id="SETTLEMENT:Important",
                state=StrategicVerificationState.REPRESENTED,
                observed_objects=(ObservedDcsObject("SCENERY:Important"),),
                target_components=(VerifiedDcsComponent("SCENERY:Important"),),
            ),
            StrategicSiteVerification(
                source_id="FUEL_STORAGE_SITE:Depot",
                state=StrategicVerificationState.REPRESENTED,
                observed_objects=(
                    ObservedDcsObject(
                        "SCENERY:123",
                        latitude=0.051,
                        longitude=0.071,
                    ),
                ),
                target_components=(VerifiedDcsComponent("SCENERY:123"),),
            ),
        )),
    )
    by_id = {item.objective_id: item for item in result.objectives}

    assert by_id["OBJECTIVE:SETTLEMENT:Important"].owner == "neutral"
    depot = by_id["OBJECTIVE:FUEL_STORAGE_SITE:Depot"]
    assert depot.kind is ObjectiveKind.DEPOT
    assert [component.object_id for component in depot.components] == ["SCENERY:123"]
    assert depot.components[0].metadata["latitude"] == 0.051
    assert depot.components[0].metadata["longitude"] == 0.071
    assert depot.metadata["targetable"] is True
    assert "OBJECTIVE:SETTLEMENT:Local" not in by_id
    assert result.below_threshold_count == 1


def test_generator_limits_ranked_geographic_categories_per_scope() -> None:
    scope, state = _scope_and_state()
    settlements = TheaterSettlements(
        theater_id="Test",
        settlements=tuple(
            Settlement(
                settlement_id=f"SETTLEMENT:Candidate-{index:02d}",
                name=f"Candidate {index:02d}",
                kind=SettlementKind.TOWN,
                size_class=SettlementSizeClass.LAND_TOWN,
                geometry={"type": "Point", "coordinates": [0.05, 0.05]},
                latitude=0.05,
                longitude=0.05,
                source="OpenStreetMap",
                confidence=0.8,
                importance_score=50 + index,
                importance_tier=SettlementImportanceTier.MEDIUM,
            )
            for index in range(13)
        ),
    )

    result = generate_strategic_objectives(
        state,
        scope,  # type: ignore[arg-type]
        settlements=settlements,
        verifications=_verifications(*(item.settlement_id for item in settlements.settlements)),
        config=StrategicObjectiveGenerationConfig(
            maximum_geographic_objectives_per_category_per_scope=3,
        ),
    )

    selected = [
        item
        for item in result.objectives
        if item.metadata.get("selection_category") == "settlement"
    ]
    assert [item.name for item in selected] == ["Candidate 12", "Candidate 11", "Candidate 10"]
    assert [item.metadata["selection_rank"] for item in selected] == [1, 2, 3]
    assert result.category_scope_limit_count == 10
    assert result.candidate_count == 16
    assert "OBJECTIVE:AIRBASE:Inside" in {item.objective_id for item in result.objectives}
    assert "OBJECTIVE:OPSZONE:Center" in {item.objective_id for item in result.objectives}


def test_generator_can_disable_geographic_category_limit() -> None:
    scope, state = _scope_and_state()
    settlements = TheaterSettlements(
        theater_id="Test",
        settlements=tuple(
            Settlement(
                settlement_id=f"SETTLEMENT:Candidate-{index:02d}",
                name=f"Candidate {index:02d}",
                kind=SettlementKind.TOWN,
                size_class=SettlementSizeClass.LAND_TOWN,
                geometry={"type": "Point", "coordinates": [0.05, 0.05]},
                latitude=0.05,
                longitude=0.05,
                source="OpenStreetMap",
                confidence=0.8,
                importance_score=60,
                importance_tier=SettlementImportanceTier.MEDIUM,
            )
            for index in range(12)
        ),
    )

    result = generate_strategic_objectives(
        state,
        scope,  # type: ignore[arg-type]
        settlements=settlements,
        verifications=_verifications(*(item.settlement_id for item in settlements.settlements)),
        config=StrategicObjectiveGenerationConfig(
            maximum_geographic_objectives_per_category_per_scope=None,
        ),
    )

    assert sum(item.kind is ObjectiveKind.TERRITORY for item in result.objectives) == 12
    assert result.category_scope_limit_count == 0


def test_generator_excludes_unverified_geographic_candidates() -> None:
    scope, state = _scope_and_state()
    settlements = TheaterSettlements(
        theater_id="Test",
        settlements=(
            Settlement(
                settlement_id="SETTLEMENT:Unverified",
                name="Unverified",
                kind=SettlementKind.CITY,
                size_class=SettlementSizeClass.LARGE_CITY,
                geometry={"type": "Point", "coordinates": [0.05, 0.05]},
                latitude=0.05,
                longitude=0.05,
                source="OpenStreetMap",
                confidence=0.8,
                importance_score=80,
                importance_tier=SettlementImportanceTier.HIGH,
            ),
        ),
    )

    result = generate_strategic_objectives(state, scope, settlements=settlements)  # type: ignore[arg-type]

    assert "OBJECTIVE:SETTLEMENT:Unverified" not in {item.objective_id for item in result.objectives}
    assert any(
        item.object_id == "SETTLEMENT:Unverified" and item.reason == "no_dcs_verification"
        for item in result.exclusions
    )


def test_generator_accepts_represented_mapping_with_target_component() -> None:
    scope, state = _scope_and_state()
    settlements = TheaterSettlements(
        theater_id="Test",
        settlements=(
            Settlement(
                settlement_id="SETTLEMENT:Approximate",
                name="Approximate",
                kind=SettlementKind.TOWN,
                size_class=SettlementSizeClass.SMALL_CITY,
                geometry={"type": "Point", "coordinates": [0.05, 0.05]},
                latitude=0.05,
                longitude=0.05,
                source="OpenStreetMap",
                confidence=0.7,
                importance_score=70,
                importance_tier=SettlementImportanceTier.HIGH,
            ),
        ),
    )
    registry = StrategicVerificationRegistry.from_entries((
        StrategicSiteVerification(
            source_id="SETTLEMENT:Approximate",
            state=StrategicVerificationState.REPRESENTED,
            observed_objects=(ObservedDcsObject("SCENERY:Town-Hall"),),
            target_components=(VerifiedDcsComponent("SCENERY:Town-Hall", role="administration", weight=2),),
        ),
    ))

    result = generate_strategic_objectives(
        state, scope, settlements=settlements, verifications=registry  # type: ignore[arg-type]
    )

    objective = next(item for item in result.objectives if item.objective_id.endswith("SETTLEMENT:Approximate"))
    assert objective.components[0].object_id == "SCENERY:Town-Hall"
    assert objective.components[0].role == "administration"
    assert objective.components[0].weight == 2
    assert objective.metadata["dcs_verification_state"] == "represented"
    assert "scenario_approved" not in objective.metadata
