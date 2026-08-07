"""Select a bounded subset of theater topography for native DCS diagnostics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math
from typing import Any, Literal

from .debug_overlay import DebugMarkup, DebugMarkupPoint, MarkupColor, points_from_lon_lat
from .topography import TheaterTopography, TopographyFeature, TopographyLayer


DEFAULT_LAYER_COLORS: dict[TopographyLayer, MarkupColor] = {
    TopographyLayer.WATER: (0.00, 0.65, 1.00, 1.00),
    TopographyLayer.ROADS: (1.00, 0.90, 0.00, 1.00),
    TopographyLayer.RAILWAYS: (0.12, 0.12, 0.12, 0.95),
    TopographyLayer.SETTLEMENTS: (0.85, 0.20, 0.20, 0.95),
    TopographyLayer.INFRASTRUCTURE: (0.65, 0.20, 0.85, 0.95),
    TopographyLayer.BUILDINGS: (0.45, 0.45, 0.45, 0.95),
    TopographyLayer.LANDUSE: (0.20, 0.65, 0.25, 0.95),
}


@dataclass(slots=True, frozen=True)
class SurfaceVerificationPoint:
    """One OSM-derived point with its expected coarse surface class."""

    point: DebugMarkupPoint
    expected_surface: Literal["land", "water"]


def build_topography_debug_overlay(
    topography: TheaterTopography,
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
    layers: Iterable[TopographyLayer],
    max_features: int = 100,
    max_marks: int = 300,
    simplify_meters: float = 75.0,
    minimum_polygon_area_m2: float = 0.0,
    minimum_line_length_m: float = 0.0,
) -> tuple[DebugMarkup, ...]:
    """Clip nearby WGS84 features and convert them to a bounded markup batch."""

    if (
        radius_m <= 0
        or max_features <= 0
        or max_marks <= 0
        or simplify_meters < 0
        or minimum_polygon_area_m2 < 0
        or minimum_line_length_m < 0
    ):
        raise ValueError("overlay radius and limits must be positive; simplification must not be negative")
    try:
        from pyproj import CRS, Transformer
        from shapely.geometry import Point, shape
        from shapely.ops import transform
    except ImportError as exc:
        raise RuntimeError('topography overlays require: python -m pip install -e ".[topography]"') from exc

    selected_layers = frozenset(layers)
    if not selected_layers:
        raise ValueError("at least one topography layer must be selected")
    local_crs = CRS.from_proj4(f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} +datum=WGS84 +units=m +no_defs")
    to_local = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True).transform
    area = Point(0, 0).buffer(radius_m)
    candidates: list[tuple[float, TopographyFeature, Any]] = []
    for feature in topography.features:
        if feature.layer not in selected_layers:
            continue
        geometry = transform(to_local, shape(feature.geometry))
        if geometry.is_empty or not geometry.intersects(area):
            continue
        clipped = geometry.intersection(area)
        if simplify_meters:
            clipped = clipped.simplify(simplify_meters, preserve_topology=True)
        if clipped.is_empty:
            continue
        polygon_area = _polygon_area(clipped)
        line_length = _line_length(clipped)
        if polygon_area > 0 and polygon_area < minimum_polygon_area_m2:
            continue
        if line_length > 0 and polygon_area == 0 and line_length < minimum_line_length_m:
            continue
        candidates.append((clipped.distance(Point(0, 0)), feature, clipped))
    candidates.sort(key=lambda item: (item[0], item[1].object_id))

    result: list[DebugMarkup] = []
    marks = 0
    for _, feature, geometry in candidates:
        additions = _markups_from_geometry(transform(to_wgs84, geometry), DEFAULT_LAYER_COLORS[feature.layer])
        addition_marks = sum(markup.mark_count for markup in additions)
        if not additions or len(result) + len(additions) > max_features or marks + addition_marks > max_marks:
            continue
        result.extend(additions)
        marks += addition_marks
        if len(result) >= max_features:
            break
    return tuple(result)


def build_road_verification_points(
    topography: TheaterTopography,
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
    spacing_m: float = 500.0,
    max_points: int = 200,
) -> tuple[DebugMarkupPoint, ...]:
    """Sample OSM road centerlines inside a circular local test area."""

    if radius_m <= 0 or spacing_m <= 0 or max_points <= 0 or max_points > 500:
        raise ValueError("road sample radius, spacing, and max_points must be positive; max_points cannot exceed 500")
    try:
        from pyproj import CRS, Transformer
        from shapely.geometry import Point, shape
        from shapely.ops import transform
    except ImportError as exc:
        raise RuntimeError('road verification requires: python -m pip install -e ".[topography]"') from exc

    local_crs = CRS.from_proj4(f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} +datum=WGS84 +units=m +no_defs")
    to_local = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True).transform
    area = Point(0, 0).buffer(radius_m)
    samples: dict[tuple[int, int], tuple[float, float]] = {}
    for feature in topography.features:
        if feature.layer is not TopographyLayer.ROADS:
            continue
        clipped = transform(to_local, shape(feature.geometry)).intersection(area)
        for line in _line_parts(clipped):
            if line.length <= 0:
                continue
            distance = 0.0
            while distance <= line.length:
                point = line.interpolate(distance)
                samples.setdefault((round(point.x / 50), round(point.y / 50)), (point.x, point.y))
                distance += spacing_m
            endpoint = line.interpolate(line.length)
            samples.setdefault((round(endpoint.x / 50), round(endpoint.y / 50)), (endpoint.x, endpoint.y))

    ordered = sorted(samples.values(), key=lambda point: (math.atan2(point[1], point[0]), math.hypot(*point)))
    if len(ordered) > max_points:
        if max_points == 1:
            ordered = [ordered[len(ordered) // 2]]
        else:
            ordered = [ordered[round(index * (len(ordered) - 1) / (max_points - 1))] for index in range(max_points)]
    result = []
    for x, y in ordered:
        lon, lat = to_wgs84(x, y)
        result.append(DebugMarkupPoint(latitude=lat, longitude=lon))
    return tuple(result)


def build_surface_verification_points(
    topography: TheaterTopography,
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
    spacing_m: float = 500.0,
    boundary_clearance_m: float = 50.0,
    max_points: int = 180,
) -> tuple[SurfaceVerificationPoint, ...]:
    """Build balanced OSM land/water samples away from ambiguous shorelines."""

    if (
        radius_m <= 0
        or spacing_m <= 0
        or boundary_clearance_m < 0
        or max_points <= 0
        or max_points > 500
    ):
        raise ValueError("surface sample dimensions must be valid and max_points cannot exceed 500")
    try:
        from pyproj import CRS, Transformer
        from shapely.geometry import Point, shape
        from shapely.ops import transform, unary_union
    except ImportError as exc:
        raise RuntimeError('surface verification requires: python -m pip install -e ".[topography]"') from exc

    local_crs = CRS.from_proj4(f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} +datum=WGS84 +units=m +no_defs")
    to_local = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True).transform
    area = Point(0, 0).buffer(radius_m)
    water_parts: list[Any] = []
    for feature in topography.features:
        if feature.layer is not TopographyLayer.WATER:
            continue
        geometry_type = str(feature.geometry.get("type") or "")
        if geometry_type not in {"Polygon", "MultiPolygon"}:
            continue
        geometry = transform(to_local, shape(feature.geometry))
        if geometry.intersects(area):
            clipped = geometry.intersection(area)
            if not clipped.is_empty:
                water_parts.append(clipped)
    water = unary_union(water_parts) if water_parts else None
    shoreline = water.boundary if water is not None and not water.is_empty else None

    land_samples: list[tuple[float, float]] = []
    water_samples: list[tuple[float, float]] = []
    coordinate = -radius_m
    while coordinate <= radius_m:
        other = -radius_m
        while other <= radius_m:
            point = Point(coordinate, other)
            if area.covers(point):
                near_boundary = shoreline is not None and point.distance(shoreline) < boundary_clearance_m
                if not near_boundary and water is not None and water.covers(point):
                    water_samples.append((coordinate, other))
                elif not near_boundary:
                    land_samples.append((coordinate, other))
            other += spacing_m
        coordinate += spacing_m

    # Water usually occupies much less area than land. Add a denser water-only
    # grid so the bounded verification batch can still compare both classes.
    if water is not None and not water.is_empty:
        water_spacing = max(boundary_clearance_m * 2, min(spacing_m, spacing_m / 4), 25.0)
        existing_water = {(round(x / 10), round(y / 10)) for x, y in water_samples}
        min_x, min_y, max_x, max_y = water.bounds
        x = max(-radius_m, min_x)
        while x <= min(radius_m, max_x):
            y = max(-radius_m, min_y)
            while y <= min(radius_m, max_y):
                point = Point(x, y)
                if (
                    area.covers(point)
                    and water.covers(point)
                    and (shoreline is None or point.distance(shoreline) >= boundary_clearance_m)
                ):
                    key = (round(x / 10), round(y / 10))
                    if key not in existing_water:
                        water_samples.append((x, y))
                        existing_water.add(key)
                y += water_spacing
            x += water_spacing

    selected = _balanced_surface_samples(land_samples, water_samples, max_points)
    result: list[SurfaceVerificationPoint] = []
    for expected_surface, x, y in selected:
        lon, lat = to_wgs84(x, y)
        result.append(
            SurfaceVerificationPoint(
                point=DebugMarkupPoint(latitude=lat, longitude=lon),
                expected_surface=expected_surface,
            )
        )
    return tuple(result)


def _markups_from_geometry(geometry: Any, color: MarkupColor) -> tuple[DebugMarkup, ...]:
    geometry_type = geometry.geom_type
    if geometry_type == "Point":
        return (DebugMarkup("point", points_from_lon_lat(((geometry.x, geometry.y),)), color=color, fill_color=(*color[:3], 0.25)),)
    if geometry_type == "LineString":
        points = points_from_lon_lat(tuple(geometry.coords))
        return (DebugMarkup("line", points, color=color),) if len(points) >= 2 else ()
    if geometry_type == "Polygon":
        points = points_from_lon_lat(tuple(geometry.exterior.coords))
        return (DebugMarkup("polygon", points, color=color),) if len(points) >= 3 else ()
    if geometry_type.startswith("Multi") or geometry_type == "GeometryCollection":
        return tuple(markup for part in geometry.geoms for markup in _markups_from_geometry(part, color))
    return ()


def _polygon_area(geometry: Any) -> float:
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return float(geometry.area)
    if geometry.geom_type == "GeometryCollection":
        return sum(_polygon_area(part) for part in geometry.geoms)
    return 0.0


def _line_length(geometry: Any) -> float:
    if geometry.geom_type in {"LineString", "MultiLineString"}:
        return float(geometry.length)
    if geometry.geom_type == "GeometryCollection":
        return sum(_line_length(part) for part in geometry.geoms)
    return 0.0


def _line_parts(geometry: Any) -> tuple[Any, ...]:
    if geometry.geom_type == "LineString":
        return (geometry,)
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return tuple(line for part in geometry.geoms for line in _line_parts(part))
    return ()


def _balanced_surface_samples(
    land_samples: list[tuple[float, float]],
    water_samples: list[tuple[float, float]],
    max_points: int,
) -> list[tuple[Literal["land", "water"], float, float]]:
    target_water = min(len(water_samples), max_points // 2)
    target_land = min(len(land_samples), max_points - target_water)
    remaining = max_points - target_water - target_land
    if remaining:
        extra_water = min(len(water_samples) - target_water, remaining)
        target_water += extra_water
        remaining -= extra_water
        target_land += min(len(land_samples) - target_land, remaining)
    selected_land = _evenly_select_points(land_samples, target_land)
    selected_water = _evenly_select_points(water_samples, target_water)
    return [
        *(("land", x, y) for x, y in selected_land),
        *(("water", x, y) for x, y in selected_water),
    ]


def _evenly_select_points(points: list[tuple[float, float]], count: int) -> list[tuple[float, float]]:
    if count <= 0:
        return []
    ordered = sorted(points, key=lambda point: (math.atan2(point[1], point[0]), math.hypot(*point)))
    if len(ordered) <= count:
        return ordered
    if count == 1:
        return [ordered[len(ordered) // 2]]
    return [ordered[round(index * (len(ordered) - 1) / (count - 1))] for index in range(count)]
