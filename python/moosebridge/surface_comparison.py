"""Offline comparison helpers for theater surface-region artifacts."""

from __future__ import annotations

from typing import Any

from .surface_regions import SurfaceClass, TheaterSurfaceRegions


def compare_surface_regions(
    reference: TheaterSurfaceRegions,
    candidate: TheaterSurfaceRegions,
    *,
    sample_spacing_m: float = 5_000.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compare two region sets on a common equal-area point grid."""

    if reference.bounds != candidate.bounds:
        raise ValueError("surface-region bounds must match")
    if sample_spacing_m <= 0:
        raise ValueError("sample spacing must be positive")
    try:
        import numpy as np
        import shapely
        from pyproj import Transformer
        from shapely.geometry import shape
    except ImportError as exc:
        raise RuntimeError('surface comparison requires: python -m pip install -e ".[topography]"') from exc

    south, west, north, east = reference.bounds
    to_local = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    to_wgs84 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    corners_x, corners_y = to_local.transform(
        [west, east, east, west],
        [south, south, north, north],
    )
    x_values = np.arange(min(corners_x), max(corners_x) + sample_spacing_m, sample_spacing_m)
    y_values = np.arange(min(corners_y), max(corners_y) + sample_spacing_m, sample_spacing_m)
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    longitude, latitude = to_wgs84.transform(grid_x.ravel(), grid_y.ravel())
    inside = (longitude >= west) & (longitude <= east) & (latitude >= south) & (latitude <= north)
    longitude = np.asarray(longitude)[inside]
    latitude = np.asarray(latitude)[inside]

    reference_land = _land_geometry(reference, shapely, shape)
    candidate_land = _land_geometry(candidate, shapely, shape)
    reference_is_land = shapely.intersects_xy(reference_land, longitude, latitude)
    candidate_is_land = shapely.intersects_xy(candidate_land, longitude, latitude)

    same = reference_is_land == candidate_is_land
    reference_land_candidate_water = reference_is_land & ~candidate_is_land
    reference_water_candidate_land = ~reference_is_land & candidate_is_land
    total = int(len(longitude))
    summary = {
        "sample_spacing_m": sample_spacing_m,
        "sample_count": total,
        "agreement_count": int(np.count_nonzero(same)),
        "agreement_percent": 100.0 * float(np.count_nonzero(same)) / total if total else 0.0,
        "reference_land_candidate_water": int(np.count_nonzero(reference_land_candidate_water)),
        "reference_water_candidate_land": int(np.count_nonzero(reference_water_candidate_land)),
        "reference_method": reference.metadata.get("method"),
        "candidate_method": candidate.metadata.get("method"),
    }
    disagreements = []
    for index in np.flatnonzero(~same):
        reference_class = "land" if reference_is_land[index] else "water"
        candidate_class = "land" if candidate_is_land[index] else "water"
        disagreements.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(longitude[index]), float(latitude[index])]},
            "properties": {
                "layer": "surface_comparison",
                "reference": reference_class,
                "candidate": candidate_class,
                "change": f"{reference_class}_to_{candidate_class}",
            },
        })
    geojson = {
        "type": "FeatureCollection",
        "features": disagreements,
        "properties": {"schema": "moosebridge.surface_comparison", **summary},
    }
    return summary, geojson


def _land_geometry(regions: TheaterSurfaceRegions, shapely_module: Any, shape_function: Any) -> Any:
    geometries = [
        shape_function(region.geometry)
        for region in regions.regions
        if region.surface_class is SurfaceClass.LAND
    ]
    if not geometries:
        raise ValueError(f"surface regions for {regions.theater_id} contain no land")
    return shapely_module.union_all(geometries)
