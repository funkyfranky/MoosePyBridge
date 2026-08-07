from __future__ import annotations

from moosebridge.osm_topography import build_overpass_query, features_from_overpass_element, topography_from_overpass
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
        reference_year=1999,
        properties={"ground_passable": False},
    )


def test_theater_topography_round_trip(tmp_path) -> None:
    original = TheaterTopography(
        theater_id="GermanyCW",
        reference_year=1999,
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
        reference_year=1999,
    )

    assert {feature.layer for feature in features} == {TopographyLayer.ROADS, TopographyLayer.INFRASTRUCTURE}
    assert {feature.category for feature in features} == {"primary", "bridge"}
    assert all(feature.valid_from == 1938 for feature in features)


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
        reference_year=1999,
        bounds=(53.0, 10.0, 55.25, 14.75),
    )

    assert len(topography.features) == 1
    assert topography.features[0].layer is TopographyLayer.SETTLEMENTS


def test_overpass_query_is_bounded_and_restricted() -> None:
    query = build_overpass_query((53.0, 10.0, 54.0, 11.0))

    assert "53.0000000,10.0000000,54.0000000,11.0000000" in query
    assert 'way["highway"' in query
    assert 'nwr["landuse"="industrial"]' in query
