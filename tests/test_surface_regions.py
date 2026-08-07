from __future__ import annotations

import pytest

from moosebridge.surface_regions import (
    SurfaceClass,
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
