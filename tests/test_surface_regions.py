from __future__ import annotations

import pytest

from moosebridge.surface_regions import (
    SurfaceClass,
    SurfaceRegion,
    SurfaceRegionKind,
    TheaterSurfaceRegions,
    build_surface_regions,
)
from moosebridge.topography import TheaterTopography, TopographyFeature, TopographyLayer


def test_surface_region_builder_separates_mainland_maritime_and_inland_water() -> None:
    pytest.importorskip("contourpy")
    pytest.importorskip("scipy")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="TestTheater",
        bounds=(53.9, 11.9, 54.1, 12.1),
        features=(
            TopographyFeature(
                object_id="TOPOGRAPHY:coast",
                layer=TopographyLayer.WATER,
                category="coastline",
                geometry={"type": "LineString", "coordinates": [[12.0, 53.9], [12.0, 54.1]]},
                source="OpenStreetMap",
                confidence=0.75,
            ),
            TopographyFeature(
                object_id="TOPOGRAPHY:lake",
                layer=TopographyLayer.WATER,
                category="lake",
                geometry={
                    "type": "Polygon",
                    "coordinates": [[
                        [11.94, 53.97], [11.97, 53.97], [11.97, 54.00], [11.94, 54.00], [11.94, 53.97],
                    ]],
                },
                source="OpenStreetMap",
                confidence=0.75,
            ),
        ),
        metadata={"source_files": ["test.osm.pbf"]},
    )

    result = build_surface_regions(
        topography,
        grid_spacing_m=1_000,
        coastline_sample_spacing_m=500,
        minimum_region_area_m2=100_000,
        simplify_meters=0,
        expected_source_count=1,
    )

    kinds = {region.kind for region in result.regions}
    assert SurfaceRegionKind.MAINLAND in kinds
    assert SurfaceRegionKind.MARITIME in kinds
    assert SurfaceRegionKind.INLAND_WATER in kinds
    assert result.metadata["source_complete"] is True
    assert all(region.surface_class is SurfaceClass.LAND for region in result.regions if region.kind is SurfaceRegionKind.MAINLAND)


def test_surface_region_geojson_round_trip(tmp_path) -> None:
    pytest.importorskip("contourpy")
    pytest.importorskip("scipy")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="TestTheater",
        bounds=(53.9, 11.9, 54.1, 12.1),
        features=(
            TopographyFeature(
                object_id="TOPOGRAPHY:coast",
                layer=TopographyLayer.WATER,
                category="coastline",
                geometry={"type": "LineString", "coordinates": [[12.0, 53.9], [12.0, 54.1]]},
                source="OpenStreetMap",
                confidence=0.75,
            ),
        ),
    )
    original = build_surface_regions(topography, grid_spacing_m=1_000, minimum_region_area_m2=100_000)
    path = original.save(tmp_path / "surface.geojson")

    restored = TheaterSurfaceRegions.load(path)

    assert restored.theater_id == original.theater_id
    assert restored.grid_spacing_m == original.grid_spacing_m
    assert len(restored.regions) == len(original.regions)
    assert restored.to_geojson()["properties"]["schema"] == "moosebridge.theater_surface_regions"


def test_surface_region_builder_repairs_invalid_water_polygon() -> None:
    pytest.importorskip("contourpy")
    pytest.importorskip("scipy")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="TestTheater",
        bounds=(53.9, 11.9, 54.1, 12.1),
        features=(
            TopographyFeature(
                object_id="TOPOGRAPHY:coast",
                layer=TopographyLayer.WATER,
                category="coastline",
                geometry={"type": "LineString", "coordinates": [[12.0, 53.9], [12.0, 54.1]]},
                source="OpenStreetMap",
                confidence=0.75,
            ),
            TopographyFeature(
                object_id="TOPOGRAPHY:invalid-water",
                layer=TopographyLayer.WATER,
                category="lake",
                geometry={
                    "type": "Polygon",
                    "coordinates": [[
                        [11.92, 53.94], [11.98, 54.00], [11.92, 54.00],
                        [11.98, 53.94], [11.92, 53.94],
                    ]],
                },
                source="OpenStreetMap",
                confidence=0.75,
            ),
        ),
    )

    result = build_surface_regions(
        topography,
        grid_spacing_m=1_000,
        minimum_region_area_m2=100_000,
    )

    assert result.metadata["repaired_water_polygon_count"] == 1
    assert any(region.kind is SurfaceRegionKind.INLAND_WATER for region in result.regions)


def test_surface_region_builder_does_not_extrapolate_island_coasts_across_open_water() -> None:
    pytest.importorskip("contourpy")
    pytest.importorskip("scipy")
    pytest.importorskip("shapely")

    def island(object_id: str, west: float, south: float) -> TopographyFeature:
        east = west + 0.05
        north = south + 0.05
        return TopographyFeature(
            object_id=object_id,
            layer=TopographyLayer.WATER,
            category="coastline",
            geometry={
                "type": "LineString",
                "coordinates": [
                    [west, south], [east, south], [east, north],
                    [west, north], [west, south],
                ],
            },
            source="OpenStreetMap",
            confidence=0.75,
        )

    topography = TheaterTopography(
        theater_id="IslandTheater",
        bounds=(53.8, 11.6, 54.2, 12.4),
        features=(
            island("TOPOGRAPHY:island-west", 11.75, 53.95),
            island("TOPOGRAPHY:island-east", 12.20, 54.05),
        ),
    )

    result = build_surface_regions(
        topography,
        grid_spacing_m=1_000,
        coastline_sample_spacing_m=500,
        minimum_region_area_m2=100_000,
    )

    land = [region for region in result.regions if region.surface_class is SurfaceClass.LAND]
    maritime = [region for region in result.regions if region.kind is SurfaceRegionKind.MARITIME]
    assert len(land) == 2
    assert len(maritime) == 1
    assert sum(region.area_m2 for region in land) < 100_000_000
    assert result.metadata["method"] == "coastline_barrier_raster_components"


def test_surface_region_builder_uses_global_land_baseline_away_from_osm_coast() -> None:
    pytest.importorskip("contourpy")
    pytest.importorskip("scipy")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="BaselineTheater",
        bounds=(53.9, 11.8, 54.1, 12.2),
        features=(
            TopographyFeature(
                object_id="TOPOGRAPHY:short-coast",
                layer=TopographyLayer.WATER,
                category="coastline",
                geometry={"type": "LineString", "coordinates": [[12.0, 53.98], [12.0, 54.02]]},
                source="OpenStreetMap",
                confidence=0.75,
            ),
        ),
    )
    baseline_land = {
        "type": "Polygon",
        "coordinates": [[[11.8, 53.9], [12.0, 53.9], [12.0, 54.1], [11.8, 54.1], [11.8, 53.9]]],
    }

    result = build_surface_regions(
        topography,
        baseline_land_geometry=baseline_land,
        baseline_land_source="test baseline",
        grid_spacing_m=1_000,
        minimum_region_area_m2=100_000,
    )

    land_area = sum(region.area_m2 for region in result.regions if region.surface_class is SurfaceClass.LAND)
    water_area = sum(region.area_m2 for region in result.regions if region.surface_class is SurfaceClass.WATER)
    assert land_area > 250_000_000
    assert water_area > 250_000_000
    assert result.metadata["method"] == "baseline_land_with_local_osm_coastline"
    assert result.metadata["baseline_land_source"] == "test baseline"


def test_surface_region_builder_uses_prepared_land_and_water_without_local_refinement() -> None:
    pytest.importorskip("contourpy")
    pytest.importorskip("scipy")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="PreparedBaseline",
        bounds=(53.9, 11.8, 54.1, 12.2),
        features=(TopographyFeature(
            object_id="TOPOGRAPHY:coast",
            layer=TopographyLayer.WATER,
            category="coastline",
            geometry={"type": "LineString", "coordinates": [[12.0, 53.9], [12.0, 54.1]]},
            source="OpenStreetMap",
            confidence=0.75,
        ),),
    )
    baseline_land = {
        "type": "Polygon",
        "coordinates": [[[11.8, 53.9], [12.0, 53.9], [12.0, 54.1], [11.8, 54.1], [11.8, 53.9]]],
    }
    baseline_water = {
        "type": "Polygon",
        "coordinates": [[[12.0, 53.9], [12.2, 53.9], [12.2, 54.1], [12.0, 54.1], [12.0, 53.9]]],
    }

    result = build_surface_regions(
        topography,
        baseline_land_geometry=baseline_land,
        baseline_land_source="prepared OSM land",
        baseline_water_geometry=baseline_water,
        baseline_water_source="prepared OSM sea",
        refine_baseline_with_coastlines=False,
        grid_spacing_m=1_000,
        minimum_region_area_m2=100_000,
    )

    assert result.metadata["method"] == "external_land_water_polygons"
    assert result.metadata["baseline_water_source"] == "prepared OSM sea"
    assert result.metadata["baseline_coastline_refinement"] is False
    assert {region.surface_class for region in result.regions} == {SurfaceClass.LAND, SurfaceClass.WATER}

def test_surface_region_builder_uses_prepared_water_as_complete_baseline() -> None:
    pytest.importorskip("contourpy")
    pytest.importorskip("scipy")
    pytest.importorskip("shapely")
    topography = TheaterTopography(
        theater_id="PreparedWaterBaseline",
        bounds=(53.9, 11.8, 54.1, 12.2),
        features=(),
    )
    baseline_water = {
        "type": "Polygon",
        "coordinates": [[[12.0, 53.9], [12.2, 53.9], [12.2, 54.1], [12.0, 54.1], [12.0, 53.9]]],
    }

    result = build_surface_regions(
        topography,
        baseline_water_geometry=baseline_water,
        baseline_water_source="prepared OSM sea",
        refine_baseline_with_coastlines=False,
        grid_spacing_m=1_000,
        minimum_region_area_m2=100_000,
    )

    assert result.metadata["method"] == "external_water_polygons"
    assert result.metadata["coastline_sample_count"] == 0
    assert result.metadata["maximum_coastline_distance_m"] is None
    assert {region.surface_class for region in result.regions} == {SurfaceClass.LAND, SurfaceClass.WATER}
