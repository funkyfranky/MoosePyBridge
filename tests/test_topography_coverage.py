from __future__ import annotations

import pytest

from moosebridge import (
    TheaterTopographyCoverage,
    TopographyCoverageArea,
    TopographyDetailLevel,
    coverage_from_picture,
)


def test_coverage_extracts_polygon_and_circle_zones_and_round_trips(tmp_path) -> None:
    pytest.importorskip("shapely")
    picture = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[10, 53], [14, 53], [14, 55], [10, 55], [10, 53]]]},
                "properties": {"layer": "zones", "object_id": "ZONE:Topography All", "name": "Topography All"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [12, 54]},
                "properties": {"layer": "zones", "object_id": "ZONE:Topography High Laage", "name": "Topography High Laage", "radius_m": 10_000},
            },
        ],
    }

    coverage = coverage_from_picture(picture, theater_id="GermanyCW")
    path = coverage.save(tmp_path / "coverage.geojson")
    restored = TheaterTopographyCoverage.load(path)

    assert restored.bounds == (53.0, 10.0, 55.0, 14.0)
    assert [area.level for area in restored.areas] == [TopographyDetailLevel.ALL, TopographyDetailLevel.HIGH]
    assert restored.areas[1].geometry["type"] == "Polygon"


def test_coverage_requires_an_all_zone() -> None:
    pytest.importorskip("shapely")
    picture = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12, 54]},
            "properties": {"layer": "zones", "object_id": "ZONE:Topography High", "name": "Topography High", "radius_m": 1000},
        }],
    }

    with pytest.raises(ValueError, match="at least one 'all'"):
        coverage_from_picture(picture, theater_id="GermanyCW")


def test_coverage_levels_are_inherited_and_can_be_made_exclusive() -> None:
    pytest.importorskip("shapely")
    from shapely.geometry import box

    coverage = TheaterTopographyCoverage(
        theater_id="Test",
        areas=(
            TopographyCoverageArea(
                object_id="ZONE:All",
                level=TopographyDetailLevel.ALL,
                geometry={"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
            ),
            TopographyCoverageArea(
                object_id="ZONE:Low",
                level=TopographyDetailLevel.LOW,
                geometry={"type": "Polygon", "coordinates": [[[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]]},
            ),
            TopographyCoverageArea(
                object_id="ZONE:High",
                level=TopographyDetailLevel.HIGH,
                geometry={"type": "Polygon", "coordinates": [[[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]},
            ),
        ),
    )

    assert coverage.geometry_for_minimum_level(TopographyDetailLevel.ALL).area == pytest.approx(100)
    assert coverage.geometry_for_minimum_level(TopographyDetailLevel.LOW).area == pytest.approx(36)
    assert coverage.geometry_for_minimum_level(TopographyDetailLevel.HIGH).area == pytest.approx(4)
    assert coverage.geometry_exclusive_to_level(TopographyDetailLevel.ALL).area == pytest.approx(64)
    assert coverage.geometry_exclusive_to_level(TopographyDetailLevel.LOW).area == pytest.approx(32)
    assert coverage.accepts(box(4.5, 4.5, 5.5, 5.5), TopographyDetailLevel.LOW)
    assert not coverage.accepts(box(0.5, 0.5, 1.5, 1.5), TopographyDetailLevel.LOW)
