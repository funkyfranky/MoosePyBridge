from __future__ import annotations

from moosebridge.settlements import (
    Settlement,
    SettlementBoundaryKind,
    SettlementImportanceTier,
    SettlementKind,
    SettlementSizeClass,
    TheaterSettlements,
    apply_administrative_boundaries,
    build_settlements,
    settlement_importance_tier,
    settlement_size_class,
)
from moosebridge.topography import TopographyFeature, TopographyLayer


def _feature(
    object_id: str,
    layer: TopographyLayer,
    category: str,
    geometry: dict,
    *,
    name: str | None = None,
    tags: dict | None = None,
) -> TopographyFeature:
    return TopographyFeature(
        object_id=object_id,
        layer=layer,
        category=category,
        geometry=geometry,
        source="OpenStreetMap",
        source_id=object_id,
        confidence=0.7,
        name=name,
        scenario_reference_year=1999,
        properties={"osm_tags": tags or {}},
    )


def test_population_size_classes_and_place_fallbacks() -> None:
    assert settlement_size_class(population=1_200_000, kind=SettlementKind.CITY) == (
        SettlementSizeClass.METROPOLIS,
        "population",
    )
    assert settlement_size_class(population=120_000, kind=SettlementKind.CITY)[0] is SettlementSizeClass.LARGE_CITY
    assert settlement_size_class(population=25_000, kind=SettlementKind.TOWN)[0] is SettlementSizeClass.MEDIUM_CITY
    assert settlement_size_class(population=7_500, kind=SettlementKind.TOWN)[0] is SettlementSizeClass.SMALL_CITY
    assert settlement_size_class(population=2_000, kind=SettlementKind.TOWN)[0] is SettlementSizeClass.LAND_TOWN
    assert settlement_size_class(population=None, kind=SettlementKind.CITY) == (
        SettlementSizeClass.LARGE_CITY,
        "osm_place",
    )


def test_importance_tiers_are_stable() -> None:
    assert settlement_importance_tier(85) is SettlementImportanceTier.CRITICAL
    assert settlement_importance_tier(65) is SettlementImportanceTier.HIGH
    assert settlement_importance_tier(40) is SettlementImportanceTier.MEDIUM
    assert settlement_importance_tier(20) is SettlementImportanceTier.LOCAL


def test_build_settlements_derives_bounded_urban_footprint() -> None:
    city = _feature(
        "TOPOGRAPHY:city/1",
        TopographyLayer.SETTLEMENTS,
        "city",
        {"type": "Point", "coordinates": [12.0, 54.0]},
        name="Test City",
        tags={"population": "120000", "population:date": "2021", "wikidata": "Q1"},
    )
    urban = _feature(
        "TOPOGRAPHY:landuse/1",
        TopographyLayer.LANDUSE,
        "residential",
        {
            "type": "Polygon",
            "coordinates": [[[11.99, 53.99], [12.01, 53.99], [12.01, 54.01], [11.99, 54.01], [11.99, 53.99]]],
        },
    )

    artifact = build_settlements((city, urban), theater_id="GermanyCW")
    settlement = artifact.settlements[0]

    assert settlement.name == "Test City"
    assert settlement.population == 120_000
    assert settlement.population_date == "2021"
    assert settlement.size_class is SettlementSizeClass.LARGE_CITY
    assert settlement.boundary_kind is SettlementBoundaryKind.URBAN_FOOTPRINT
    assert settlement.geometry["type"] == "Polygon"
    assert settlement.urban_area_m2 and settlement.urban_area_m2 > 1_000_000
    assert settlement.properties["wikidata"] == "Q1"


def test_town_without_urban_landuse_remains_point() -> None:
    town = _feature(
        "TOPOGRAPHY:town/1",
        TopographyLayer.SETTLEMENTS,
        "town",
        {"type": "Point", "coordinates": [12.2, 54.1]},
        name="Test Town",
    )

    settlement = build_settlements((town,), theater_id="GermanyCW").settlements[0]

    assert settlement.boundary_kind is SettlementBoundaryKind.POINT_ONLY
    assert settlement.geometry["type"] == "Point"
    assert settlement.size_class is SettlementSizeClass.SMALL_CITY


def test_matching_administrative_boundary_replaces_urban_footprint() -> None:
    city = _feature(
        "TOPOGRAPHY:city/hamburg",
        TopographyLayer.SETTLEMENTS,
        "city",
        {"type": "Point", "coordinates": [10.0, 53.55]},
        name="Hamburg",
        tags={"wikidata": "Q1055", "population": "1800000"},
    )
    boundary = _feature(
        "TOPOGRAPHY:boundary/hamburg",
        TopographyLayer.ADMINISTRATIVE_BOUNDARIES,
        "4",
        {
            "type": "Polygon",
            "coordinates": [[[9.8, 53.4], [10.2, 53.4], [10.2, 53.7], [9.8, 53.7], [9.8, 53.4]]],
        },
        name="Freie und Hansestadt Hamburg",
        tags={"wikidata": "Q1055", "boundary": "administrative", "admin_level": "4"},
    )

    result = apply_administrative_boundaries(
        build_settlements((city,), theater_id="GermanyCW"),
        (boundary,),
    )
    settlement = result.settlements[0]

    assert settlement.boundary_kind is SettlementBoundaryKind.ADMINISTRATIVE
    assert settlement.geometry == boundary.geometry
    assert settlement.urban_area_m2 is None
    assert settlement.properties["administrative_area_m2"] > 800_000_000
    assert settlement.properties["administrative_level"] == 4
    assert settlement.properties["administrative_boundary_id"] == boundary.source_id
    assert result.metadata["administrative_match_count"] == 1


def test_containing_boundary_with_different_name_is_not_assigned() -> None:
    city = _feature(
        "TOPOGRAPHY:city/rostock",
        TopographyLayer.SETTLEMENTS,
        "city",
        {"type": "Point", "coordinates": [12.1, 54.1]},
        name="Rostock",
    )
    boundary = _feature(
        "TOPOGRAPHY:boundary/county",
        TopographyLayer.ADMINISTRATIVE_BOUNDARIES,
        "6",
        {
            "type": "Polygon",
            "coordinates": [[[11.8, 53.9], [12.4, 53.9], [12.4, 54.3], [11.8, 54.3], [11.8, 53.9]]],
        },
        name="Landkreis Rostock",
    )

    settlement = apply_administrative_boundaries(
        build_settlements((city,), theater_id="GermanyCW"),
        (boundary,),
    ).settlements[0]

    assert settlement.boundary_kind is SettlementBoundaryKind.POINT_ONLY


def test_settlement_artifact_round_trip(tmp_path) -> None:
    settlement = Settlement(
        settlement_id="SETTLEMENT:test",
        name="Test",
        kind=SettlementKind.TOWN,
        size_class=SettlementSizeClass.SMALL_CITY,
        geometry={"type": "Point", "coordinates": [12.0, 54.0]},
        latitude=54.0,
        longitude=12.0,
        source="test",
        confidence=0.8,
        importance_score=30,
        importance_tier=SettlementImportanceTier.LOCAL,
    )
    artifact = TheaterSettlements(theater_id="GermanyCW", settlements=(settlement,))
    path = artifact.save(tmp_path / "settlements.geojson")

    loaded = TheaterSettlements.load(path)

    assert loaded == artifact
