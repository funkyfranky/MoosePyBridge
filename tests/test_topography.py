from __future__ import annotations

import pytest

from moosebridge.osm_topography import build_overpass_query, features_from_overpass_element, topography_from_overpass
from moosebridge.pbf_topography import (
    _normalize_ogr_record,
    clip_topography_feature_to_mask,
    features_from_pyrosm_record,
    topography_detail_level,
)
from moosebridge.topography import TheaterTopography, TopographyFeature, TopographyLayer, merge_topography_features


def _water() -> TopographyFeature:
    return TopographyFeature(
        object_id="TOPOGRAPHY:OSM:way/1:water",
        layer=TopographyLayer.WATER,
        category="lake",
        name="Test Lake",
        geometry={
            "type": "Polygon",
            "coordinates": [[[12.0, 54.0], [12.1, 54.0], [12.1, 54.1], [12.0, 54.0]]],
        },
        source="OpenStreetMap",
        source_id="OSM:way/1",
        confidence=0.75,
        scenario_reference_year=1999,
        properties={"ground_passable": False},
    )


def test_theater_topography_round_trip(tmp_path) -> None:
    original = TheaterTopography(
        theater_id="GermanyCW",
        scenario_reference_year=1999,
        bounds=(53.0, 10.0, 55.25, 14.75),
        features=(_water(),),
    )

    path = original.save(tmp_path / "GermanyCW.geojson")
    restored = TheaterTopography.load(path)

    assert restored == original
    assert restored.to_geojson()["features"][0]["properties"]["layer"] == "topography_water"


def test_merge_topography_replaces_previous_static_features() -> None:
    topography = TheaterTopography(theater_id="GermanyCW", features=(_water(),))
    picture = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": {"layer": "groups", "object_id": "GROUP:One"}},
            _water().to_geojson_feature(),
        ],
        "properties": {},
    }

    merge_topography_features(picture, topography)
    merge_topography_features(picture, topography)

    assert len(picture["features"]) == 2
    assert picture["properties"]["topography_feature_count"] == 1
    assert picture["properties"]["topography_theater_id"] == "GermanyCW"


def test_overpass_element_can_supply_transport_and_bridge_layers() -> None:
    features = features_from_overpass_element(
        {
            "type": "way",
            "id": 42,
            "tags": {"name": "Old Bridge", "highway": "primary", "bridge": "yes", "start_date": "1938"},
            "geometry": [{"lon": 12.0, "lat": 54.0}, {"lon": 12.01, "lat": 54.01}],
        },
        scenario_reference_year=1999,
    )

    assert {feature.layer for feature in features} == {TopographyLayer.ROADS, TopographyLayer.INFRASTRUCTURE}
    assert {feature.category for feature in features} == {"primary", "bridge"}
    assert all(feature.valid_from == 1938 for feature in features)


def test_overpass_element_prefers_english_then_international_name() -> None:
    english = features_from_overpass_element(
        {
            "type": "node",
            "id": 420,
            "lat": 45.0,
            "lon": 42.0,
            "tags": {
                "place": "city",
                "name": "Ставрополь",
                "int_name": "Stavropol International",
                "name:en": "Stavropol",
            },
        },
        scenario_reference_year=2008,
    )
    international = features_from_overpass_element(
        {
            "type": "node",
            "id": 421,
            "lat": 45.1,
            "lon": 42.1,
            "tags": {"place": "town", "name": "Локальное имя", "int_name": "International Name"},
        },
        scenario_reference_year=2008,
    )

    assert english[0].name == "Stavropol"
    assert international[0].name == "International Name"


def test_overpass_element_classifies_railway_facilities() -> None:
    station = features_from_overpass_element({
        "type": "node",
        "id": 44,
        "lat": 54.1,
        "lon": 12.2,
        "tags": {"railway": "station", "name": "Test Central", "train": "yes"},
    }, scenario_reference_year=1999)
    halt = features_from_overpass_element({
        "type": "node",
        "id": 45,
        "lat": 54.2,
        "lon": 12.3,
        "tags": {"railway": "halt", "name": "Test Halt"},
    }, scenario_reference_year=1999)

    assert station[0].layer is TopographyLayer.INFRASTRUCTURE
    assert station[0].category == "railway_station"
    assert halt[0].category == "railway_halt"


def test_overpass_element_classifies_maritime_facilities_and_components() -> None:
    port = features_from_overpass_element({
        "type": "way",
        "id": 46,
        "tags": {"name": "Cargo Alpha", "landuse": "port", "port": "cargo", "cargo": "containers"},
        "geometry": [{"lon": 12.0, "lat": 54.0}, {"lon": 12.01, "lat": 54.0}, {"lon": 12.0, "lat": 54.0}],
    }, scenario_reference_year=1999)
    berth = features_from_overpass_element({
        "type": "node", "id": 47, "lat": 54.0, "lon": 12.02,
        "tags": {"seamark:type": "berth", "seamark:berth:category": "loading"},
    }, scenario_reference_year=1999)

    assert next(feature for feature in port if feature.layer is TopographyLayer.INFRASTRUCTURE).category == "port"
    assert berth[0].category == "berth"


def test_inconsistent_osm_validity_dates_do_not_abort_theater_import() -> None:
    features = features_from_overpass_element(
        {
            "type": "way",
            "id": 43,
            "tags": {"railway": "rail", "start_date": "2020", "end_date": "1980"},
            "geometry": [{"lon": 12.0, "lat": 54.0}, {"lon": 12.01, "lat": 54.01}],
        },
        scenario_reference_year=1999,
    )

    assert len(features) == 1
    assert features[0].valid_from is None
    assert features[0].valid_to is None


def test_tiled_overpass_payloads_are_deduplicated() -> None:
    element = {
        "type": "node",
        "id": 7,
        "lat": 54.1,
        "lon": 12.6,
        "tags": {"place": "town", "name": "Example"},
    }

    topography = topography_from_overpass(
        [{"elements": [element]}, {"elements": [element]}],
        theater_id="GermanyCW",
        scenario_reference_year=1999,
        bounds=(53.0, 10.0, 55.25, 14.75),
    )

    assert len(topography.features) == 1
    assert topography.features[0].layer is TopographyLayer.SETTLEMENTS


def test_overpass_query_is_bounded_and_restricted() -> None:
    query = build_overpass_query((53.0, 10.0, 54.0, 11.0))

    assert "53.0000000,10.0000000,54.0000000,11.0000000" in query
    assert 'way["highway"' in query
    assert 'nwr["landuse"="industrial"]' in query


def test_pyrosm_record_preserves_geometry_and_source_time() -> None:
    features = features_from_pyrosm_record(
        {
            "id": "row-1",
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[12.0, 54.0], [12.1, 54.1]]},
            "properties": {
                "id": 99,
                "osm_type": "way",
                "name": "Bridge Road",
                "highway": "primary",
                "bridge": "yes",
            },
        },
        scenario_reference_year=1999,
        source_snapshot_date="2026-08-07T03:00:00Z",
        include_buildings=False,
    )

    assert {feature.layer for feature in features} == {TopographyLayer.ROADS, TopographyLayer.INFRASTRUCTURE}
    assert all(feature.geometry["type"] == "LineString" for feature in features)
    assert all(feature.scenario_reference_year == 1999 for feature in features)
    assert all(feature.source_snapshot_date == "2026-08-07T03:00:00Z" for feature in features)


def test_pyrosm_buildings_are_explicitly_optional() -> None:
    record = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[12.0, 54.0], [12.01, 54.0], [12.01, 54.01], [12.0, 54.0]]],
        },
        "properties": {"id": 100, "osm_type": "way", "building": "industrial"},
    }

    excluded = features_from_pyrosm_record(
        record,
        scenario_reference_year=1999,
        source_snapshot_date=None,
        include_buildings=False,
    )
    included = features_from_pyrosm_record(
        record,
        scenario_reference_year=1999,
        source_snapshot_date=None,
        include_buildings=True,
    )

    assert excluded == ()
    assert len(included) == 1
    assert included[0].layer is TopographyLayer.BUILDINGS


def test_osm_administrative_boundary_is_preserved() -> None:
    features = features_from_pyrosm_record(
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[9.8, 53.4], [10.2, 53.4], [10.2, 53.7], [9.8, 53.7], [9.8, 53.4]]],
            },
            "properties": {
                "id": 62782,
                "osm_type": "relation",
                "name": "Hamburg",
                "boundary": "administrative",
                "admin_level": "4",
            },
        },
        scenario_reference_year=1999,
        source_snapshot_date=None,
        include_buildings=False,
    )

    assert len(features) == 1
    assert features[0].layer is TopographyLayer.ADMINISTRATIVE_BOUNDARIES
    assert features[0].category == "4"
    assert features[0].geometry["type"] == "Polygon"


def test_topography_detail_levels_keep_baseline_small_and_local_detail_rich() -> None:
    def feature(layer: TopographyLayer, category: str) -> TopographyFeature:
        return TopographyFeature(
            object_id=f"TOPOGRAPHY:test:{layer.value}:{category}",
            layer=layer,
            category=category,
            geometry={"type": "Point", "coordinates": [12.0, 54.0]},
            source="test",
            confidence=1.0,
        )

    assert topography_detail_level(feature(TopographyLayer.WATER, "lake")).value == "all"
    assert topography_detail_level(feature(TopographyLayer.ROADS, "motorway")).value == "low"
    assert topography_detail_level(feature(TopographyLayer.ROADS, "primary")).value == "low"
    assert topography_detail_level(feature(TopographyLayer.ROADS, "secondary")).value == "high"
    assert topography_detail_level(feature(TopographyLayer.RAILWAYS, "rail")).value == "low"
    assert topography_detail_level(feature(TopographyLayer.SETTLEMENTS, "city")).value == "low"
    assert topography_detail_level(feature(TopographyLayer.SETTLEMENTS, "town")).value == "high"
    assert topography_detail_level(feature(TopographyLayer.ROADS, "residential")).value == "high"
    assert topography_detail_level(feature(TopographyLayer.BUILDINGS, "industrial")).value == "high"
    assert topography_detail_level(feature(TopographyLayer.INFRASTRUCTURE, "power_plant")).value == "low"
    assert topography_detail_level(feature(TopographyLayer.INFRASTRUCTURE, "storage_tank")).value == "high"


def test_topography_feature_is_clipped_to_its_detail_mask() -> None:
    pytest.importorskip("shapely")
    from shapely.geometry import box
    from moosebridge import TopographyDetailLevel

    road = TopographyFeature(
        object_id="TOPOGRAPHY:test:road",
        layer=TopographyLayer.ROADS,
        category="primary",
        geometry={"type": "LineString", "coordinates": [[0, 5], [10, 5]]},
        source="test",
        confidence=1.0,
    )

    clipped = clip_topography_feature_to_mask(road, box(2, 2, 8, 8), TopographyDetailLevel.LOW)

    assert clipped is not None
    assert clipped.geometry == {"type": "LineString", "coordinates": ((2.0, 5.0), (8.0, 5.0))}
    assert clipped.properties["detail_level"] == "low"


def test_topography_line_touching_mask_at_one_point_is_discarded() -> None:
    pytest.importorskip("shapely")
    from shapely.geometry import box
    from moosebridge import TopographyDetailLevel

    road = TopographyFeature(
        object_id="TOPOGRAPHY:test:touching-road",
        layer=TopographyLayer.ROADS,
        category="primary",
        geometry={"type": "LineString", "coordinates": [[0, 0], [2, 2]]},
        source="test",
        confidence=1.0,
    )

    assert clip_topography_feature_to_mask(
        road,
        box(2, 2, 4, 4),
        TopographyDetailLevel.LOW,
    ) is None


def test_topography_invalid_polygon_is_repaired_before_clipping() -> None:
    pytest.importorskip("shapely")
    from shapely.geometry import box, shape
    from moosebridge import TopographyDetailLevel

    feature = TopographyFeature(
        object_id="TOPOGRAPHY:test:invalid-polygon",
        layer=TopographyLayer.LANDUSE,
        category="industrial",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0, 0], [4, 4], [0, 4], [4, 0], [0, 0]]],
        },
        source="test",
        confidence=1.0,
    )

    clipped = clip_topography_feature_to_mask(
        feature,
        box(-1, -1, 5, 5),
        TopographyDetailLevel.LOW,
    )

    assert clipped is not None
    assert shape(clipped.geometry).is_valid


def test_ogr_record_normalization_preserves_coastline_tags_and_way_identity() -> None:
    normalized = _normalize_ogr_record(
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[12.0, 54.0], [12.1, 54.1]]},
            "properties": {
                "osm_id": "42",
                "name": "Coast",
                "highway": None,
                "other_tags": '"natural"=>"coastline","source"=>"survey"',
            },
        },
        "lines",
    )
    features = features_from_pyrosm_record(
        normalized,
        scenario_reference_year=1999,
        source_snapshot_date=None,
        include_buildings=False,
    )

    assert len(features) == 1
    assert features[0].category == "coastline"
    assert features[0].source_id == "OSM:way/42"
