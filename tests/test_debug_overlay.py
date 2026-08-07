from __future__ import annotations

import pytest

from moosebridge.debug_overlay import DebugMarkup, DebugMarkupPoint, RoadPointMatch, validate_debug_overlay
from moosebridge.topography import TheaterTopography, TopographyFeature, TopographyLayer
from moosebridge.topography_overlay import build_road_verification_points, build_topography_debug_overlay


def test_polygon_markup_reports_native_segment_count() -> None:
    feature = DebugMarkup(
        "polygon",
        (
            DebugMarkupPoint(54.0, 12.0),
            DebugMarkupPoint(54.0, 12.1),
            DebugMarkupPoint(54.1, 12.1),
        ),
    )

    assert feature.mark_count == 3
    assert validate_debug_overlay("test", [feature]) == (feature,)


def test_overlay_validation_rejects_excessive_native_marks() -> None:
    points = tuple(DebugMarkupPoint(54.0, 12.0 + index / 10_000) for index in range(502))

    with pytest.raises(ValueError, match="500 native DCS markups"):
        validate_debug_overlay("too-large", [DebugMarkup("line", points)])


def test_topography_overlay_clips_nearby_features_and_respects_mark_budget() -> None:
    pytest.importorskip("pyproj")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="GermanyCW",
        features=(
            TopographyFeature(
                object_id="TOPOGRAPHY:road/near",
                layer=TopographyLayer.ROADS,
                category="primary",
                geometry={"type": "LineString", "coordinates": [[11.9, 54.0], [12.1, 54.0]]},
                source="OpenStreetMap",
                confidence=0.75,
            ),
            TopographyFeature(
                object_id="TOPOGRAPHY:road/far",
                layer=TopographyLayer.ROADS,
                category="primary",
                geometry={"type": "LineString", "coordinates": [[14.0, 54.0], [14.1, 54.0]]},
                source="OpenStreetMap",
                confidence=0.75,
            ),
        ),
    )

    features = build_topography_debug_overlay(
        topography,
        latitude=54.0,
        longitude=12.0,
        radius_m=5_000,
        layers=(TopographyLayer.ROADS,),
        max_marks=10,
    )

    assert len(features) == 1
    assert features[0].kind == "line"
    assert features[0].mark_count <= 10


def test_topography_overlay_can_exclude_small_water_polygons() -> None:
    pytest.importorskip("pyproj")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="GermanyCW",
        features=(
            TopographyFeature(
                object_id="TOPOGRAPHY:water/small",
                layer=TopographyLayer.WATER,
                category="water",
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[12.0, 54.0], [12.001, 54.0], [12.001, 54.001], [12.0, 54.0]]],
                },
                source="OpenStreetMap",
                confidence=0.75,
            ),
            TopographyFeature(
                object_id="TOPOGRAPHY:water/large",
                layer=TopographyLayer.WATER,
                category="water",
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[12.01, 54.0], [12.03, 54.0], [12.03, 54.02], [12.01, 54.0]]],
                },
                source="OpenStreetMap",
                confidence=0.75,
            ),
        ),
    )

    features = build_topography_debug_overlay(
        topography,
        latitude=54.0,
        longitude=12.0,
        radius_m=10_000,
        layers=(TopographyLayer.WATER,),
        minimum_polygon_area_m2=20_000,
    )

    assert len(features) == 1
    assert features[0].kind == "polygon"


def test_road_point_match_parses_dcs_result() -> None:
    match = RoadPointMatch.from_payload(
        {
            "input_latitude": 54.0,
            "input_longitude": 12.0,
            "road_latitude": 54.0001,
            "road_longitude": 12.0002,
            "input_x": 100,
            "input_z": 200,
            "road_x": 110,
            "road_z": 220,
            "distance_m": 22.36,
        }
    )

    assert match.input_point == DebugMarkupPoint(54.0, 12.0)
    assert match.road_point == DebugMarkupPoint(54.0001, 12.0002)
    assert match.distance_m == pytest.approx(22.36)


def test_road_verification_samples_only_nearby_roads_and_honors_limit() -> None:
    pytest.importorskip("pyproj")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="GermanyCW",
        features=(
            TopographyFeature(
                object_id="TOPOGRAPHY:road/near",
                layer=TopographyLayer.ROADS,
                category="primary",
                geometry={"type": "LineString", "coordinates": [[11.95, 54.0], [12.05, 54.0]]},
                source="OpenStreetMap",
                confidence=0.75,
            ),
            TopographyFeature(
                object_id="TOPOGRAPHY:road/far",
                layer=TopographyLayer.ROADS,
                category="primary",
                geometry={"type": "LineString", "coordinates": [[14.0, 54.0], [14.1, 54.0]]},
                source="OpenStreetMap",
                confidence=0.75,
            ),
        ),
    )

    points = build_road_verification_points(
        topography,
        latitude=54.0,
        longitude=12.0,
        radius_m=5_000,
        spacing_m=250,
        max_points=7,
    )

    assert len(points) == 7
    assert all(abs(point.longitude - 12.0) < 0.1 for point in points)
