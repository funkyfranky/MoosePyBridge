"""Connected coarse land and water regions derived from theater topography."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Iterable

from .topography import TheaterTopography, TopographyLayer


class SurfaceClass(StrEnum):
    """Coarse physical surface class used for strategic mobility."""

    LAND = "land"
    WATER = "water"


class SurfaceRegionKind(StrEnum):
    """Semantic connected-component kind."""

    MAINLAND = "mainland"
    ISLAND = "island"
    MARITIME = "maritime"
    INLAND_WATER = "inland_water"


@dataclass(slots=True, frozen=True)
class SurfaceRegion:
    """One four-neighbor-connected land or water component in WGS84."""

    region_id: str
    surface_class: SurfaceClass
    kind: SurfaceRegionKind
    geometry: dict[str, Any]
    area_m2: float
    cell_count: int
    confidence: float
    source: str
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.region_id.strip() or not self.source.strip():
            raise ValueError("surface region requires region_id and source")
        if self.geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("surface region geometry must be Polygon or MultiPolygon")
        if self.area_m2 <= 0 or self.cell_count <= 0:
            raise ValueError("surface region area and cell_count must be positive")
        if not 0 <= self.confidence <= 1:
            raise ValueError("surface region confidence must be between zero and one")
        expected = {
            SurfaceClass.LAND: {SurfaceRegionKind.MAINLAND, SurfaceRegionKind.ISLAND},
            SurfaceClass.WATER: {SurfaceRegionKind.MARITIME, SurfaceRegionKind.INLAND_WATER},
        }
        if self.kind not in expected[self.surface_class]:
            raise ValueError("surface region kind does not match its surface class")

    def to_geojson_feature(self) -> dict[str, Any]:
        layer = "surface_land_regions" if self.surface_class is SurfaceClass.LAND else "surface_water_regions"
        properties = {
            "layer": layer,
            "object_id": self.region_id,
            "name": self.region_id,
            "object_type": "SURFACE_REGION",
            "surface_class": self.surface_class.value,
            "region_kind": self.kind.value,
            "category": self.kind.value,
            "area_m2": self.area_m2,
            "area_km2": self.area_m2 / 1_000_000,
            "cell_count": self.cell_count,
            "confidence": self.confidence,
            "source": self.source,
            "coordinate_system": "WGS84",
            **self.properties,
        }
        return {"type": "Feature", "geometry": self.geometry, "properties": properties}

    @classmethod
    def from_geojson_feature(cls, feature: dict[str, Any]) -> "SurfaceRegion":
        if feature.get("type") != "Feature":
            raise ValueError("surface region entry must be a GeoJSON Feature")
        properties = dict(feature.get("properties") or {})
        known = {
            "layer", "object_id", "name", "object_type", "surface_class", "region_kind", "category",
            "area_m2", "area_km2", "cell_count", "confidence", "source", "coordinate_system",
        }
        return cls(
            region_id=str(properties.get("object_id") or ""),
            surface_class=SurfaceClass(str(properties.get("surface_class") or "")),
            kind=SurfaceRegionKind(str(properties.get("region_kind") or "")),
            geometry=dict(feature.get("geometry") or {}),
            area_m2=float(properties.get("area_m2") or 0),
            cell_count=int(properties.get("cell_count") or 0),
            confidence=float(properties.get("confidence") or 0),
            source=str(properties.get("source") or ""),
            properties={key: value for key, value in properties.items() if key not in known},
        )


@dataclass(slots=True, frozen=True)
class TheaterSurfaceRegions:
    """Versioned offline surface-region artifact for one DCS theater."""

    theater_id: str
    regions: tuple[SurfaceRegion, ...]
    bounds: tuple[float, float, float, float]
    grid_spacing_m: float
    schema_version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.theater_id.strip() or self.schema_version != 1:
            raise ValueError("invalid theater surface-region collection")
        if self.grid_spacing_m <= 0:
            raise ValueError("surface-region grid spacing must be positive")
        if len(self.bounds) != 4:
            raise ValueError("surface-region bounds must contain south, west, north, east")
        ids = [region.region_id for region in self.regions]
        if len(ids) != len(set(ids)):
            raise ValueError("surface region IDs must be unique")

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [region.to_geojson_feature() for region in self.regions],
            "properties": {
                "schema": "moosebridge.theater_surface_regions",
                "schema_version": self.schema_version,
                "theater_id": self.theater_id,
                "bounds": list(self.bounds),
                "grid_spacing_m": self.grid_spacing_m,
                "region_count": len(self.regions),
                "land_region_count": sum(region.surface_class is SurfaceClass.LAND for region in self.regions),
                "water_region_count": sum(region.surface_class is SurfaceClass.WATER for region in self.regions),
                **self.metadata,
            },
        }

    @classmethod
    def from_geojson(cls, payload: dict[str, Any]) -> "TheaterSurfaceRegions":
        properties = dict(payload.get("properties") or {})
        if payload.get("type") != "FeatureCollection" or properties.get("schema") != "moosebridge.theater_surface_regions":
            raise ValueError("not a MooseBridge theater surface-region cache")
        bounds = properties.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise ValueError("surface-region cache requires bounds")
        features = payload.get("features")
        if not isinstance(features, list):
            raise ValueError("surface-region cache features must be a list")
        known = {
            "schema", "schema_version", "theater_id", "bounds", "grid_spacing_m", "region_count",
            "land_region_count", "water_region_count",
        }
        return cls(
            theater_id=str(properties.get("theater_id") or ""),
            regions=tuple(SurfaceRegion.from_geojson_feature(feature) for feature in features),
            bounds=tuple(float(value) for value in bounds),  # type: ignore[arg-type]
            grid_spacing_m=float(properties.get("grid_spacing_m") or 0),
            schema_version=int(properties.get("schema_version") or 1),
            metadata={key: value for key, value in properties.items() if key not in known},
        )

    @classmethod
    def load(cls, path: str | Path) -> "TheaterSurfaceRegions":
        with Path(path).open("r", encoding="utf-8") as stream:
            return cls.from_geojson(json.load(stream))

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.to_geojson(), stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
        temporary.replace(target)
        return target


def build_surface_regions(
    topography: TheaterTopography,
    *,
    baseline_land_geometry: dict[str, Any] | None = None,
    baseline_land_source: str | None = None,
    baseline_water_geometry: dict[str, Any] | None = None,
    baseline_water_source: str | None = None,
    refine_baseline_with_coastlines: bool = True,
    grid_spacing_m: float = 250.0,
    coastline_sample_spacing_m: float | None = None,
    minimum_region_area_m2: float = 250_000.0,
    simplify_meters: float = 0.0,
    expected_source_count: int | None = None,
) -> TheaterSurfaceRegions:
    """Derive connected land/water components from directed OSM coastlines."""

    if topography.bounds is None:
        raise ValueError("topography bounds are required to build surface regions")
    if grid_spacing_m <= 0 or minimum_region_area_m2 < 0 or simplify_meters < 0:
        raise ValueError("surface-region dimensions must not be negative and grid spacing must be positive")
    try:
        import contourpy
        import numpy as np
        import shapely
        from pyproj import Transformer
        from scipy.ndimage import find_objects, generate_binary_structure, label
        from scipy.spatial import cKDTree
        from shapely.geometry import LineString, Polygon, box, mapping, shape
        from shapely.ops import transform
    except ImportError as exc:
        raise RuntimeError('surface regions require: python -m pip install -e ".[topography]"') from exc

    south, west, north, east = topography.bounds
    to_local_transformer = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    to_wgs84_transformer = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    envelope = transform(to_local_transformer.transform, box(west, south, east, north))
    sample_spacing = coastline_sample_spacing_m or grid_spacing_m
    min_x, min_y, max_x, max_y = envelope.bounds
    x_coordinates = np.arange(min_x, max_x + grid_spacing_m, grid_spacing_m, dtype=np.float64)
    y_coordinates = np.arange(min_y, max_y + grid_spacing_m, grid_spacing_m, dtype=np.float64)
    grid_x = x_coordinates[np.newaxis, :]
    grid_y = y_coordinates[:, np.newaxis]
    inside = shapely.contains_xy(envelope, grid_x, grid_y)
    inland_water = np.zeros_like(inside)

    need_directed_coastline = baseline_water_geometry is None and (
        baseline_land_geometry is None or refine_baseline_with_coastlines
    )
    coastline_samples: list[tuple[float, float, float, float]] = []
    coastline_feature_count = 0
    water_polygon_count = 0
    repaired_water_polygon_count = 0

    for feature in topography.features:
        if feature.layer is not TopographyLayer.WATER:
            continue
        if feature.category == "coastline":
            coastline_feature_count += 1
            if not need_directed_coastline:
                continue
            geometry = transform(to_local_transformer.transform, shape(feature.geometry))
            for line in _surface_lines(geometry):
                coordinates = np.asarray(line.coords, dtype=np.float64)
                for first, second in zip(coordinates[:-1], coordinates[1:]):
                    delta = second - first
                    length = float(np.linalg.norm(delta))
                    if length <= 0:
                        continue
                    count = max(1, int(np.ceil(length / sample_spacing)))
                    direction = delta / length
                    for index in range(count):
                        midpoint = first + delta * ((index + 0.5) / count)
                        coastline_samples.append((midpoint[0], midpoint[1], direction[0], direction[1]))
        else:
            geometry = transform(to_local_transformer.transform, shape(feature.geometry))
        if feature.category != "coastline" and geometry.geom_type in {"Polygon", "MultiPolygon"}:
            if not geometry.is_valid:
                geometry = shapely.make_valid(geometry)
                repaired_water_polygon_count += 1
            polygon_parts = _surface_polygons(geometry)
            if not polygon_parts:
                continue
            clipped = shapely.union_all(polygon_parts).intersection(envelope)
            if not clipped.is_empty:
                _rasterize_geometry(
                    inland_water,
                    clipped,
                    x_coordinates,
                    y_coordinates,
                    shapely_module=shapely,
                )
                water_polygon_count += 1

    if need_directed_coastline and not coastline_samples:
        raise ValueError("topography contains no directed coastline geometry")

    distances = None
    distance_grid = None
    directed_maritime = None
    if need_directed_coastline:
        coastline_array = np.asarray(coastline_samples, dtype=np.float64)
        tree = cKDTree(coastline_array[:, :2])
        point_count = len(x_coordinates) * len(y_coordinates)
        nearest = np.empty(point_count, dtype=np.int64)
        distances = np.empty(point_count, dtype=np.float64)
        chunk_size = 250_000
        for start in range(0, point_count, chunk_size):
            stop = min(point_count, start + chunk_size)
            indices = np.arange(start, stop)
            rows, columns = np.divmod(indices, len(x_coordinates))
            points = np.column_stack((x_coordinates[columns], y_coordinates[rows]))
            chunk_distances, chunk_nearest = tree.query(points, workers=-1)
            distances[start:stop] = chunk_distances
            nearest[start:stop] = chunk_nearest
        closest = coastline_array[nearest]
        rows, columns = np.divmod(np.arange(point_count), len(x_coordinates))
        cross = (
            closest[:, 2] * (y_coordinates[rows] - closest[:, 1])
            - closest[:, 3] * (x_coordinates[columns] - closest[:, 0])
        )
        distance_grid = distances.reshape(inside.shape)
        directed_maritime = (cross.reshape(inside.shape) < 0) & inside

    if baseline_water_geometry is not None:
        baseline_water = transform(
            to_local_transformer.transform,
            _as_shapely_geometry(baseline_water_geometry, shape),
        )
        baseline_water_mask = shapely.intersects_xy(baseline_water, grid_x, grid_y) & inside
        if baseline_land_geometry is not None:
            baseline_land = transform(
                to_local_transformer.transform,
                _as_shapely_geometry(baseline_land_geometry, shape),
            )
            baseline_land_mask = shapely.intersects_xy(baseline_land, grid_x, grid_y) & inside
            unclassified = inside & ~baseline_land_mask & ~baseline_water_mask
            maritime = baseline_water_mask | unclassified
            classification_method = "external_land_water_polygons"
        else:
            maritime = baseline_water_mask
            classification_method = "external_water_polygons"
        coastline_refinement_distance = None
        coastline_partition_count = 0
        ambiguous_partition_count = 0
        coastline_barrier_cells = 0
    elif baseline_land_geometry is not None:
        baseline_land = transform(
            to_local_transformer.transform,
            _as_shapely_geometry(baseline_land_geometry, shape),
        )
        baseline_land_mask = shapely.intersects_xy(baseline_land, grid_x, grid_y) & inside
        maritime = inside & ~baseline_land_mask
        classification_method = "baseline_land_with_local_osm_coastline"
        if refine_baseline_with_coastlines and distance_grid is not None and directed_maritime is not None:
            coastline_refinement_distance = max(2.0 * grid_spacing_m, sample_spacing)
            coastline_refinement = inside & (distance_grid <= coastline_refinement_distance)
            maritime[coastline_refinement] = directed_maritime[coastline_refinement]
        else:
            coastline_refinement_distance = None
        coastline_partition_count = 0
        ambiguous_partition_count = 0
        coastline_barrier_cells = 0
    else:
        maritime, coastline_partition_count, ambiguous_partition_count, coastline_barrier_cells = (
            _classify_coastline_partitions(
                directed_maritime,
                distance_grid,
                inside,
                grid_spacing_m=grid_spacing_m,
                coastline_sample_spacing_m=sample_spacing,
                label_function=label,
                structure=generate_binary_structure(2, 1),
            )
        )
        coastline_refinement_distance = None
        classification_method = "coastline_barrier_raster_components"

    inland_water &= inside
    water_mask = maritime | inland_water
    land_mask = inside & ~water_mask

    structure = generate_binary_structure(2, 1)
    land_labels, land_count = label(land_mask, structure=structure)
    water_labels, water_count = label(water_mask, structure=structure)
    cell_area = grid_spacing_m * grid_spacing_m
    land_regions = _regions_from_labels(
        land_labels,
        land_count,
        x_coordinates,
        y_coordinates,
        surface_class=SurfaceClass.LAND,
        subtype_mask=None,
        minimum_cells=max(1, int(np.ceil(minimum_region_area_m2 / cell_area))),
        simplify_meters=simplify_meters,
        envelope=envelope,
        contourpy_module=contourpy,
        find_objects_function=find_objects,
        polygon_class=Polygon,
        transform_function=transform,
        to_wgs84=to_wgs84_transformer.transform,
        mapping_function=mapping,
    )
    water_regions = _regions_from_labels(
        water_labels,
        water_count,
        x_coordinates,
        y_coordinates,
        surface_class=SurfaceClass.WATER,
        subtype_mask=maritime,
        minimum_cells=max(1, int(np.ceil(minimum_region_area_m2 / cell_area))),
        simplify_meters=simplify_meters,
        envelope=envelope,
        contourpy_module=contourpy,
        find_objects_function=find_objects,
        polygon_class=Polygon,
        transform_function=transform,
        to_wgs84=to_wgs84_transformer.transform,
        mapping_function=mapping,
    )
    if land_regions:
        largest_land_id = max(land_regions, key=lambda region: region["cell_count"])["label"]
    else:
        largest_land_id = None

    regions: list[SurfaceRegion] = []
    for item in land_regions:
        kind = SurfaceRegionKind.MAINLAND if item["label"] == largest_land_id else SurfaceRegionKind.ISLAND
        regions.append(_surface_region_from_component(topography.theater_id, item, SurfaceClass.LAND, kind, grid_spacing_m))
    for item in water_regions:
        kind = SurfaceRegionKind.MARITIME if item["subtype_cells"] > 0 else SurfaceRegionKind.INLAND_WATER
        regions.append(_surface_region_from_component(topography.theater_id, item, SurfaceClass.WATER, kind, grid_spacing_m))
    regions.sort(key=lambda region: (region.surface_class.value, -region.area_m2, region.region_id))

    source_files = list(topography.metadata.get("source_files") or [])
    source_complete = expected_source_count is None or len(source_files) >= expected_source_count
    return TheaterSurfaceRegions(
        theater_id=topography.theater_id,
        regions=tuple(regions),
        bounds=topography.bounds,
        grid_spacing_m=grid_spacing_m,
        metadata={
            "method": classification_method,
            "baseline_land_source": baseline_land_source,
            "baseline_water_source": baseline_water_source,
            "baseline_coastline_refinement": refine_baseline_with_coastlines,
            "coastline_refinement_distance_m": coastline_refinement_distance,
            "connectivity": 4,
            "minimum_region_area_m2": minimum_region_area_m2,
            "simplify_meters": simplify_meters,
            "coastline_feature_count": coastline_feature_count,
            "coastline_sample_count": len(coastline_samples),
            "coastline_partition_count": coastline_partition_count,
            "ambiguous_coastline_partition_count": ambiguous_partition_count,
            "coastline_barrier_cell_count": coastline_barrier_cells,
            "water_polygon_count": water_polygon_count,
            "repaired_water_polygon_count": repaired_water_polygon_count,
            "source_files": source_files,
            "source_complete": source_complete,
            "expected_source_count": expected_source_count,
            "maximum_coastline_distance_m": (
                float(distances[inside.ravel()].max(initial=0))
                if distances is not None
                else None
            ),
            "dcs_verification": "pending",
        },
    )


def _classify_coastline_partitions(
    directed_maritime: Any,
    coastline_distance: Any,
    inside: Any,
    *,
    grid_spacing_m: float,
    coastline_sample_spacing_m: float,
    label_function: Any,
    structure: Any,
) -> tuple[Any, int, int, int]:
    """Propagate directed coastline evidence only within coast-bounded areas."""

    import numpy as np

    barrier_distance = max(grid_spacing_m, coastline_sample_spacing_m) * 0.9
    coastline_barrier = inside & (coastline_distance <= barrier_distance)
    open_cells = inside & ~coastline_barrier
    partitions, partition_count = label_function(open_cells, structure=structure)
    if partition_count == 0:
        return directed_maritime.copy(), 0, 0, int(np.count_nonzero(coastline_barrier))

    evidence_distance = barrier_distance + 2.0 * grid_spacing_m
    evidence = open_cells & (coastline_distance <= evidence_distance)
    water_votes = np.bincount(
        partitions[evidence & directed_maritime],
        minlength=partition_count + 1,
    )
    land_votes = np.bincount(
        partitions[evidence & ~directed_maritime],
        minlength=partition_count + 1,
    )

    # A complete coastline barrier normally gives each partition evidence from
    # only one side. Fall back to the local directed classification solely for
    # partitions that do not reach the evidence band or receive equal votes.
    fallback_water = np.bincount(
        partitions[open_cells & directed_maritime],
        minlength=partition_count + 1,
    )
    fallback_land = np.bincount(
        partitions[open_cells & ~directed_maritime],
        minlength=partition_count + 1,
    )
    partition_is_water = water_votes > land_votes
    unresolved = (water_votes + land_votes == 0) | (water_votes == land_votes)
    partition_is_water[unresolved] = fallback_water[unresolved] > fallback_land[unresolved]
    partition_is_water[0] = False

    maritime = np.zeros_like(inside, dtype=bool)
    maritime[open_cells] = partition_is_water[partitions[open_cells]]
    maritime[coastline_barrier] = directed_maritime[coastline_barrier]
    ambiguous = int(np.count_nonzero((water_votes[1:] > 0) & (land_votes[1:] > 0)))
    return maritime, int(partition_count), ambiguous, int(np.count_nonzero(coastline_barrier))


def _surface_lines(geometry: Any) -> list[Any]:
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "Polygon":
        return [geometry.exterior, *geometry.interiors]
    if hasattr(geometry, "geoms"):
        return [line for part in geometry.geoms for line in _surface_lines(part)]
    return []


def _as_shapely_geometry(geometry: Any, shape_function: Any) -> Any:
    """Accept either a GeoJSON mapping or an already materialized geometry."""

    return geometry if hasattr(geometry, "geom_type") else shape_function(geometry)


def _rasterize_geometry(
    target: Any,
    geometry: Any,
    x_coordinates: Any,
    y_coordinates: Any,
    *,
    shapely_module: Any,
) -> None:
    """Burn one geometry into the smallest intersecting grid window."""

    import numpy as np

    min_x, min_y, max_x, max_y = geometry.bounds
    column_start = max(0, int(np.searchsorted(x_coordinates, min_x, side="left")))
    column_stop = min(len(x_coordinates), int(np.searchsorted(x_coordinates, max_x, side="right")))
    row_start = max(0, int(np.searchsorted(y_coordinates, min_y, side="left")))
    row_stop = min(len(y_coordinates), int(np.searchsorted(y_coordinates, max_y, side="right")))
    if column_start >= column_stop or row_start >= row_stop:
        return
    window = shapely_module.intersects_xy(
        geometry,
        x_coordinates[np.newaxis, column_start:column_stop],
        y_coordinates[row_start:row_stop, np.newaxis],
    )
    target[row_start:row_stop, column_start:column_stop] |= window


def _regions_from_labels(
    labels: Any,
    label_count: int,
    x_coordinates: Any,
    y_coordinates: Any,
    *,
    surface_class: SurfaceClass,
    subtype_mask: Any | None,
    minimum_cells: int,
    simplify_meters: float,
    envelope: Any,
    contourpy_module: Any,
    find_objects_function: Any,
    polygon_class: Any,
    transform_function: Any,
    to_wgs84: Any,
    mapping_function: Any,
) -> list[dict[str, Any]]:
    import numpy as np
    import shapely

    output: list[dict[str, Any]] = []
    slices = find_objects_function(labels, max_label=label_count)
    for label_value, component_slice in enumerate(slices, start=1):
        if component_slice is None:
            continue
        component = labels[component_slice] == label_value
        cell_count = int(np.count_nonzero(component))
        if cell_count < minimum_cells:
            continue
        row_slice, column_slice = component_slice
        padded = np.pad(component.astype(np.float32), 1)
        spacing_x = float(x_coordinates[1] - x_coordinates[0])
        spacing_y = float(y_coordinates[1] - y_coordinates[0])
        local_x = x_coordinates[column_slice.start:column_slice.stop]
        local_y = y_coordinates[row_slice.start:row_slice.stop]
        contour_x = np.concatenate(([local_x[0] - spacing_x], local_x, [local_x[-1] + spacing_x]))
        contour_y = np.concatenate(([local_y[0] - spacing_y], local_y, [local_y[-1] + spacing_y]))
        generator = contourpy_module.contour_generator(
            x=contour_x,
            y=contour_y,
            z=padded,
            name="serial",
            fill_type="OuterOffset",
        )
        points_collection, offsets_collection = generator.filled(0.5, 1.5)
        polygons = []
        for points, offsets in zip(points_collection, offsets_collection):
            rings = [points[offsets[index]:offsets[index + 1]] for index in range(len(offsets) - 1)]
            if rings and len(rings[0]) >= 4:
                polygons.append(polygon_class(rings[0], [ring for ring in rings[1:] if len(ring) >= 4]))
        if not polygons:
            continue
        geometry = shapely.union_all(polygons).intersection(envelope)
        if simplify_meters:
            geometry = geometry.simplify(simplify_meters, preserve_topology=True)
        geometry = shapely.make_valid(geometry)
        polygon_parts = [part for part in _surface_polygons(geometry) if not part.is_empty]
        if not polygon_parts:
            continue
        geometry = shapely.union_all(polygon_parts)
        wgs84_geometry = transform_function(to_wgs84, geometry)
        subtype_cells = 0
        if subtype_mask is not None:
            subtype_cells = int(np.count_nonzero(subtype_mask[component_slice] & component))
        output.append(
            {
                "label": label_value,
                "surface_class": surface_class,
                "geometry": mapping_function(wgs84_geometry),
                "cell_count": cell_count,
                "area_m2": float(geometry.area),
                "subtype_cells": subtype_cells,
            }
        )
    return output


def _surface_polygons(geometry: Any) -> list[Any]:
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [polygon for part in geometry.geoms for polygon in _surface_polygons(part)]
    return []


def _surface_region_from_component(
    theater_id: str,
    component: dict[str, Any],
    surface_class: SurfaceClass,
    kind: SurfaceRegionKind,
    grid_spacing_m: float,
) -> SurfaceRegion:
    prefix = "LAND" if surface_class is SurfaceClass.LAND else "WATER"
    return SurfaceRegion(
        region_id=f"SURFACE:{theater_id}:{prefix}:{component['label']}",
        surface_class=surface_class,
        kind=kind,
        geometry=dict(component["geometry"]),
        area_m2=float(component["area_m2"]),
        cell_count=int(component["cell_count"]),
        confidence=0.75,
        source="OpenStreetMap coastline and water polygons",
        properties={
            "grid_spacing_m": grid_spacing_m,
            "connectivity": 4,
            "maritime_cell_count": int(component["subtype_cells"]),
        },
    )


def surface_region_counts(regions: Iterable[SurfaceRegion]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for region in regions:
        counts[region.kind.value] = counts.get(region.kind.value, 0) + 1
    return counts
