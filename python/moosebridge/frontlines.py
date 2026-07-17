"""DCS-local influence fields and operational frontline extraction."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from time import perf_counter
from typing import Any, Iterable, Literal

import contourpy
import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import gaussian_filter
import shapely
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

CoalitionName = Literal["blue", "red"]
FloatGrid = NDArray[np.float32]
BoolGrid = NDArray[np.bool_]
LAND_FRONTLINE_CATEGORIES = frozenset({"ground", "ground unit", "ground units"})


@dataclass(slots=True, frozen=True)
class ForcePoint:
    """One weighted ground-force position in DCS-local coordinates."""

    object_id: str
    coalition: CoalitionName
    x: float
    z: float
    weight: float = 1.0
    label: str | None = None

    def __post_init__(self) -> None:
        if self.coalition not in {"blue", "red"}:
            raise ValueError(f"Unsupported coalition: {self.coalition}")
        if not self.object_id:
            raise ValueError("ForcePoint requires object_id")
        if not math.isfinite(self.x) or not math.isfinite(self.z):
            raise ValueError("ForcePoint coordinates must be finite")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("ForcePoint weight must be positive")


@dataclass(slots=True, frozen=True)
class TerritoryControlRegion:
    """One declared blue/red territory used as a weak control prior."""

    object_id: str
    name: str
    coalition: CoalitionName
    vertices: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if self.coalition not in {"blue", "red"}:
            raise ValueError(f"Unsupported territory coalition: {self.coalition}")
        if len(self.vertices) < 3:
            raise ValueError("TerritoryControlRegion requires at least three vertices")
        geometry = Polygon(self.vertices)
        if geometry.is_empty or geometry.area <= 0 or not geometry.is_valid:
            raise ValueError("TerritoryControlRegion requires a valid non-empty polygon")

    @property
    def geometry(self) -> Polygon:
        return Polygon(self.vertices)

    @classmethod
    def from_territory(cls, territory: Any) -> "TerritoryControlRegion":
        """Create a control region from a typed TERRITORY snapshot."""

        coalition = str(getattr(territory, "coalition", "") or "").strip().lower()
        if coalition not in {"blue", "red"}:
            raise ValueError("TERRITORY requires a blue or red coalition")
        vertices = _territory_vertices(territory)
        object_id = str(getattr(territory, "object_id", "") or "")
        name = str(getattr(territory, "name", None) or getattr(territory, "dcs_name", None) or object_id or "Territory")
        return cls(object_id or f"TERRITORY:{name}", name, coalition, vertices)  # type: ignore[arg-type]


def territory_control_regions(territories: Iterable[Any]) -> tuple[TerritoryControlRegion, ...]:
    """Return valid blue/red polygon territories in stable order."""

    regions: list[TerritoryControlRegion] = []
    for territory in territories:
        try:
            regions.append(TerritoryControlRegion.from_territory(territory))
        except ValueError:
            continue
    return tuple(sorted(regions, key=lambda region: region.object_id))


@dataclass(slots=True, frozen=True)
class Incursion:
    """An isolated ground force operating inside hostile territory."""

    force: ForcePoint
    territory_id: str
    territory_name: str
    territory_coalition: CoalitionName
    connected_force_count: int
    nearest_external_support_m: float | None


@dataclass(slots=True, frozen=True)
class FrontlineForceClassification:
    """Ground forces separated into main-front and incursion roles."""

    main_forces: tuple[ForcePoint, ...]
    incursions: tuple[Incursion, ...]


def classify_frontline_forces(
    forces: Iterable[ForcePoint],
    control_regions: Iterable[TerritoryControlRegion],
    *,
    support_radius_m: float = 30_000.0,
    lodgement_min_forces: int = 3,
) -> FrontlineForceClassification:
    """Keep isolated hostile-territory forces from distorting the main front."""

    if support_radius_m <= 0:
        raise ValueError("support_radius_m must be positive")
    if lodgement_min_forces < 1:
        raise ValueError("lodgement_min_forces must be positive")

    force_points = tuple(forces)
    regions = tuple(control_regions)
    hostile_region: dict[str, TerritoryControlRegion] = {}
    for force in force_points:
        point = Point(force.x, force.z)
        region = next(
            (
                candidate
                for candidate in regions
                if candidate.coalition != force.coalition and candidate.geometry.contains(point)
            ),
            None,
        )
        if region is not None:
            hostile_region[force.object_id] = region

    unvisited = set(force.object_id for force in force_points)
    forces_by_id = {force.object_id: force for force in force_points}
    incursion_ids: set[str] = set()
    incursions: list[Incursion] = []
    for seed in force_points:
        if seed.object_id not in unvisited:
            continue
        component_ids: set[str] = set()
        pending = [seed]
        unvisited.remove(seed.object_id)
        while pending:
            current = pending.pop()
            component_ids.add(current.object_id)
            for candidate_id in tuple(unvisited):
                candidate = forces_by_id[candidate_id]
                if candidate.coalition != current.coalition:
                    continue
                if math.hypot(candidate.x - current.x, candidate.z - current.z) <= support_radius_m:
                    unvisited.remove(candidate_id)
                    pending.append(candidate)

        for region_id in {
            hostile_region[force_id].object_id
            for force_id in component_ids
            if force_id in hostile_region
        }:
            region = next(candidate for candidate in regions if candidate.object_id == region_id)
            members_inside = [
                forces_by_id[force_id]
                for force_id in component_ids
                if hostile_region.get(force_id) == region
            ]
            component_entirely_inside = len(members_inside) == len(component_ids)
            if not component_entirely_inside or len(members_inside) >= lodgement_min_forces:
                continue
            outside_support = [
                candidate
                for candidate in force_points
                if candidate.coalition == seed.coalition
                and candidate.object_id not in component_ids
                and not region.geometry.contains(Point(candidate.x, candidate.z))
            ]
            for member in members_inside:
                nearest = min(
                    (math.hypot(candidate.x - member.x, candidate.z - member.z) for candidate in outside_support),
                    default=None,
                )
                incursion_ids.add(member.object_id)
                incursions.append(
                    Incursion(
                        force=member,
                        territory_id=region.object_id,
                        territory_name=region.name,
                        territory_coalition=region.coalition,
                        connected_force_count=len(members_inside),
                        nearest_external_support_m=nearest,
                    )
                )

    return FrontlineForceClassification(
        main_forces=tuple(force for force in force_points if force.object_id not in incursion_ids),
        incursions=tuple(sorted(incursions, key=lambda incursion: incursion.force.object_id)),
    )


def _territory_vertices(territory: Any) -> tuple[tuple[float, float], ...]:
    return tuple(
        (float(vertex.x), float(vertex.z))
        for vertex in getattr(territory, "vertices", ())
        if getattr(vertex, "x", None) is not None and getattr(vertex, "z", None) is not None
    )


@dataclass(slots=True, frozen=True)
class FrontlineCalculationArea:
    """Passive polygon limiting influence and frontline calculations."""

    name: str
    vertices: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise ValueError("FrontlineCalculationArea requires at least three vertices")
        geometry = Polygon(self.vertices)
        if geometry.is_empty or geometry.area <= 0:
            raise ValueError("FrontlineCalculationArea requires a non-empty polygon")
        if not geometry.is_valid:
            raise ValueError(f"FrontlineCalculationArea polygon is invalid: {shapely.is_valid_reason(geometry)}")

    @property
    def geometry(self) -> Polygon:
        """Return the area as a Shapely polygon."""

        return Polygon(self.vertices)

    @classmethod
    def from_territory(cls, territory: Any) -> "FrontlineCalculationArea":
        """Create a calculation area from a typed TERRITORY snapshot."""

        vertices = _territory_vertices(territory)
        if len(vertices) < 3:
            raise ValueError("TERRITORY requires polygon vertices for frontline calculation")
        name = getattr(territory, "name", None) or getattr(territory, "dcs_name", None) or "Territory"
        return cls(str(name), vertices)

    @classmethod
    def from_territories(cls, territories: Iterable[Any]) -> "FrontlineCalculationArea":
        """Create one campaign calculation area spanning polygon territories."""

        polygons: list[Polygon] = []
        names: list[str] = []
        for territory in territories:
            vertices = _territory_vertices(territory)
            if len(vertices) < 3:
                continue
            polygon = Polygon(vertices)
            if not polygon.is_empty and polygon.is_valid and polygon.area > 0:
                polygons.append(polygon)
                names.append(str(getattr(territory, "name", None) or getattr(territory, "dcs_name", None) or "Territory"))
        if not polygons:
            raise ValueError("At least one polygon TERRITORY is required for a frontline calculation area")
        geometry = shapely.union_all(polygons).convex_hull
        if not isinstance(geometry, Polygon):
            raise ValueError("Territories do not define a polygon calculation area")
        return cls(
            names[0] if len(names) == 1 else "Combined territories",
            tuple((float(x), float(z)) for x, z in list(geometry.exterior.coords)[:-1]),
        )


def force_points_from_groups(groups: Iterable[dict[str, Any]]) -> tuple[ForcePoint, ...]:
    """Select alive blue/red ground groups from a global truth snapshot."""

    forces: list[ForcePoint] = []
    for group in groups:
        object_id = str(group.get("object_id") or "")
        category = str(group.get("category") or "").strip().lower().replace("_", " ")
        coalition = str(group.get("coalition") or "").strip().lower()
        x = group.get("x")
        z = group.get("z")
        if not object_id or group.get("alive") is not True or category not in LAND_FRONTLINE_CATEGORIES:
            continue
        if coalition not in {"blue", "red"} or not isinstance(x, (int, float)) or not isinstance(z, (int, float)):
            continue
        forces.append(
            ForcePoint(
                object_id=object_id,
                coalition=coalition,  # type: ignore[arg-type]
                x=float(x),
                z=float(z),
                label=str(group.get("dcs_name") or group.get("name") or group.get("object_id") or ""),
            )
        )
    return tuple(sorted(forces, key=lambda force: force.object_id))


@dataclass(slots=True)
class FrontlineForceTracker:
    """Smooth live force positions before recalculating a frontline."""

    position_alpha: float = 0.35
    _positions: dict[str, ForcePoint] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 < self.position_alpha <= 1:
            raise ValueError("position_alpha must be in (0, 1]")

    def update(self, forces: Iterable[ForcePoint]) -> tuple[ForcePoint, ...]:
        """Return exponentially smoothed positions for the current force set."""

        updated: dict[str, ForcePoint] = {}
        for force in forces:
            previous = self._positions.get(force.object_id)
            if previous is None or previous.coalition != force.coalition:
                smoothed = force
            else:
                alpha = self.position_alpha
                smoothed = ForcePoint(
                    object_id=force.object_id,
                    coalition=force.coalition,
                    x=previous.x + alpha * (force.x - previous.x),
                    z=previous.z + alpha * (force.z - previous.z),
                    weight=force.weight,
                    label=force.label,
                )
            updated[force.object_id] = smoothed
        self._positions = updated
        return tuple(updated[key] for key in sorted(updated))

    def reset(self) -> None:
        """Discard positions from a previous mission timeline."""

        self._positions.clear()


@dataclass(slots=True, frozen=True)
class FrontlineConfig:
    """Parameters controlling influence-field and contour generation."""

    grid_spacing_m: float = 2_500.0
    influence_sigma_m: float = 20_000.0
    influence_truncate: float = 3.0
    minimum_activity_ratio: float = 0.025
    minimum_opposition_ratio: float = 0.01
    simplify_tolerance_m: float = 750.0
    minimum_segment_length_m: float = 5_000.0
    bounds_padding_m: float = 30_000.0
    maximum_grid_cells: int = 1_000_000
    territory_control_ratio: float = 0.08
    incursion_support_radius_m: float = 30_000.0
    incursion_lodgement_min_forces: int = 3

    def __post_init__(self) -> None:
        positive = {
            "grid_spacing_m": self.grid_spacing_m,
            "influence_sigma_m": self.influence_sigma_m,
            "influence_truncate": self.influence_truncate,
            "maximum_grid_cells": self.maximum_grid_cells,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        ratios = {
            "minimum_activity_ratio": self.minimum_activity_ratio,
            "minimum_opposition_ratio": self.minimum_opposition_ratio,
            "territory_control_ratio": self.territory_control_ratio,
        }
        for name, value in ratios.items():
            if not 0 <= value < 1:
                raise ValueError(f"{name} must be in [0, 1)")
        if self.simplify_tolerance_m < 0 or self.minimum_segment_length_m < 0 or self.bounds_padding_m < 0:
            raise ValueError("Distance limits cannot be negative")
        if self.incursion_support_radius_m <= 0:
            raise ValueError("incursion_support_radius_m must be positive")
        if self.incursion_lodgement_min_forces < 1:
            raise ValueError("incursion_lodgement_min_forces must be positive")


@dataclass(slots=True, frozen=True)
class FrontlineSegment:
    """One disconnected operational frontline segment."""

    index: int
    points: tuple[tuple[float, float], ...]
    length_m: float

    def to_geojson_feature(self) -> dict[str, Any]:
        """Return this segment as DCS-local GeoJSON."""

        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [list(point) for point in self.points]},
            "properties": {
                "layer": "frontlines",
                "object_id": f"FRONTLINE:{self.index}",
                "name": f"Frontline {self.index}",
                "length_m": self.length_m,
                "coordinate_system": "DCS_LOCAL_XZ",
            },
        }


@dataclass(slots=True)
class FrontlineResult:
    """Influence grids, extracted segments and diagnostic metadata."""

    forces: tuple[ForcePoint, ...]
    config: FrontlineConfig
    area: FrontlineCalculationArea | None
    bounds: tuple[float, float, float, float]
    x_coordinates: NDArray[np.float64]
    z_coordinates: NDArray[np.float64]
    blue_influence: FloatGrid
    red_influence: FloatGrid
    active_mask: BoolGrid
    segments: tuple[FrontlineSegment, ...]
    elapsed_ms: float
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def balance(self) -> FloatGrid:
        """Return signed blue-minus-red influence."""

        return self.blue_influence - self.red_influence

    def to_geojson(self) -> dict[str, Any]:
        """Return forces, optional campaign area and frontline segments."""

        features: list[dict[str, Any]] = []
        if self.area is not None:
            ring = [list(vertex) for vertex in self.area.vertices]
            ring.append(ring[0])
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "layer": "frontline_area",
                        "object_id": f"FRONTLINE_AREA:{self.area.name}",
                        "name": self.area.name,
                        "coordinate_system": "DCS_LOCAL_XZ",
                    },
                }
            )
        features.extend(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [force.x, force.z]},
                "properties": {
                    "layer": "frontline_forces",
                    "object_id": force.object_id,
                    "name": force.label or force.object_id,
                    "coalition": force.coalition,
                    "weight": force.weight,
                    "coordinate_system": "DCS_LOCAL_XZ",
                },
            }
            for force in self.forces
        )
        features.extend(segment.to_geojson_feature() for segment in self.segments)
        return {
            "type": "FeatureCollection",
            "features": features,
            "properties": {
                "scope": "frontline_prototype",
                "coordinate_system": "DCS_LOCAL_XZ",
                "bounds": list(self.bounds),
                "config": asdict(self.config),
                "diagnostics": self.diagnostics,
                "elapsed_ms": self.elapsed_ms,
            },
        }


class FrontlineEngine:
    """Generate an operational frontline from weighted opposing force points."""

    def __init__(self, config: FrontlineConfig | None = None) -> None:
        self.config = config or FrontlineConfig()

    def calculate(
        self,
        forces: Iterable[ForcePoint],
        *,
        area: FrontlineCalculationArea | None = None,
        control_regions: Iterable[TerritoryControlRegion] = (),
    ) -> FrontlineResult:
        """Build influence fields and extract balanced opposing contours."""

        started = perf_counter()
        force_points = tuple(forces)
        bounds = self._bounds(force_points, area)
        x_coordinates, z_coordinates = self._grid_coordinates(bounds)
        blue_seed = np.zeros((len(z_coordinates), len(x_coordinates)), dtype=np.float32)
        red_seed = np.zeros_like(blue_seed)
        area_geometry = area.geometry if area is not None else None
        regions = tuple(control_regions)
        included_forces: list[ForcePoint] = []

        for force in force_points:
            if area_geometry is not None and not area_geometry.covers(Point(force.x, force.z)):
                continue
            x_index = int(np.clip(np.rint((force.x - x_coordinates[0]) / self.config.grid_spacing_m), 0, len(x_coordinates) - 1))
            z_index = int(np.clip(np.rint((force.z - z_coordinates[0]) / self.config.grid_spacing_m), 0, len(z_coordinates) - 1))
            target = blue_seed if force.coalition == "blue" else red_seed
            target[z_index, x_index] += force.weight
            included_forces.append(force)

        sigma_cells = self.config.influence_sigma_m / self.config.grid_spacing_m
        blue_influence = gaussian_filter(
            blue_seed,
            sigma=sigma_cells,
            mode="constant",
            truncate=self.config.influence_truncate,
        ).astype(np.float32, copy=False)
        red_influence = gaussian_filter(
            red_seed,
            sigma=sigma_cells,
            mode="constant",
            truncate=self.config.influence_truncate,
        ).astype(np.float32, copy=False)

        territory_prior = self._apply_territory_control_prior(
            blue_influence,
            red_influence,
            x_coordinates,
            z_coordinates,
            regions,
            {force.coalition for force in included_forces},
        )
        active_mask = self._active_mask(blue_influence, red_influence, x_coordinates, z_coordinates, area_geometry)
        segments = self._extract_segments(blue_influence - red_influence, active_mask, x_coordinates, z_coordinates, area_geometry)
        elapsed_ms = (perf_counter() - started) * 1_000
        diagnostics = {
            "input_force_count": len(force_points),
            "included_force_count": len(included_forces),
            "blue_force_count": sum(force.coalition == "blue" for force in included_forces),
            "red_force_count": sum(force.coalition == "red" for force in included_forces),
            "grid_columns": len(x_coordinates),
            "grid_rows": len(z_coordinates),
            "grid_cells": len(x_coordinates) * len(z_coordinates),
            "active_cells": int(np.count_nonzero(active_mask)),
            "segment_count": len(segments),
            "frontline_length_m": sum(segment.length_m for segment in segments),
            "territory_control_region_count": len(regions),
            "territory_control_prior": territory_prior,
        }
        return FrontlineResult(
            forces=tuple(included_forces),
            config=self.config,
            area=area,
            bounds=bounds,
            x_coordinates=x_coordinates,
            z_coordinates=z_coordinates,
            blue_influence=blue_influence,
            red_influence=red_influence,
            active_mask=active_mask,
            segments=segments,
            elapsed_ms=elapsed_ms,
            diagnostics=diagnostics,
        )

    def _apply_territory_control_prior(
        self,
        blue: FloatGrid,
        red: FloatGrid,
        x_coordinates: NDArray[np.float64],
        z_coordinates: NDArray[np.float64],
        regions: tuple[TerritoryControlRegion, ...],
        present_coalitions: set[CoalitionName],
    ) -> float:
        ratio = self.config.territory_control_ratio
        peak = float((blue + red).max(initial=0.0))
        prior = peak * ratio
        if prior <= 0 or not regions:
            return 0.0
        grid_x, grid_z = np.meshgrid(x_coordinates, z_coordinates)
        for region in regions:
            if region.coalition not in present_coalitions:
                continue
            mask = shapely.intersects_xy(region.geometry, grid_x, grid_z)
            target = blue if region.coalition == "blue" else red
            target[mask] += prior
        return prior

    def _bounds(
        self,
        forces: tuple[ForcePoint, ...],
        area: FrontlineCalculationArea | None,
    ) -> tuple[float, float, float, float]:
        if area is not None:
            return tuple(float(value) for value in area.geometry.bounds)  # type: ignore[return-value]
        if not forces:
            raise ValueError("Frontline calculation requires forces or a FrontlineCalculationArea")
        padding = self.config.bounds_padding_m
        return (
            min(force.x for force in forces) - padding,
            min(force.z for force in forces) - padding,
            max(force.x for force in forces) + padding,
            max(force.z for force in forces) + padding,
        )

    def _grid_coordinates(
        self,
        bounds: tuple[float, float, float, float],
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        min_x, min_z, max_x, max_z = bounds
        spacing = self.config.grid_spacing_m
        columns = max(2, math.ceil((max_x - min_x) / spacing) + 1)
        rows = max(2, math.ceil((max_z - min_z) / spacing) + 1)
        if columns * rows > self.config.maximum_grid_cells:
            raise ValueError(
                f"Frontline grid would contain {columns * rows:,} cells, "
                f"above maximum_grid_cells={self.config.maximum_grid_cells:,}"
            )
        return (
            min_x + np.arange(columns, dtype=np.float64) * spacing,
            min_z + np.arange(rows, dtype=np.float64) * spacing,
        )

    def _active_mask(
        self,
        blue: FloatGrid,
        red: FloatGrid,
        x_coordinates: NDArray[np.float64],
        z_coordinates: NDArray[np.float64],
        area: BaseGeometry | None,
    ) -> BoolGrid:
        activity = blue + red
        peak = float(activity.max(initial=0.0))
        if peak <= 0:
            return np.zeros_like(activity, dtype=np.bool_)
        mask = activity >= peak * self.config.minimum_activity_ratio
        if self.config.minimum_opposition_ratio > 0:
            mask &= np.minimum(blue, red) >= peak * self.config.minimum_opposition_ratio
        if area is not None:
            grid_x, grid_z = np.meshgrid(x_coordinates, z_coordinates)
            mask &= shapely.contains_xy(area, grid_x, grid_z)
        return mask

    def _extract_segments(
        self,
        balance: FloatGrid,
        active_mask: BoolGrid,
        x_coordinates: NDArray[np.float64],
        z_coordinates: NDArray[np.float64],
        area: BaseGeometry | None,
    ) -> tuple[FrontlineSegment, ...]:
        if not np.any(active_mask) or not (np.any(balance > 0) and np.any(balance < 0)):
            return ()
        masked_balance = np.ma.array(balance, mask=~active_mask)
        generator = contourpy.contour_generator(
            x=x_coordinates,
            y=z_coordinates,
            z=masked_balance,
            name="serial",
            line_type="Separate",
        )
        linework: list[LineString] = []
        for coordinates in generator.lines(0.0):
            if len(coordinates) < 2:
                continue
            geometry: BaseGeometry = LineString(coordinates)
            if area is not None:
                geometry = geometry.intersection(area)
            if self.config.simplify_tolerance_m > 0:
                geometry = geometry.simplify(self.config.simplify_tolerance_m, preserve_topology=True)
            linework.extend(self._lines(geometry))

        linework = [
            line
            for line in linework
            if not line.is_empty and len(line.coords) >= 2 and line.length >= self.config.minimum_segment_length_m
        ]
        linework.sort(key=lambda line: line.length, reverse=True)
        return tuple(
            FrontlineSegment(
                index=index,
                points=tuple((float(x), float(z)) for x, z in line.coords),
                length_m=float(line.length),
            )
            for index, line in enumerate(linework, start=1)
        )

    @staticmethod
    def _lines(geometry: BaseGeometry) -> list[LineString]:
        if isinstance(geometry, LineString):
            return [geometry]
        if isinstance(geometry, MultiLineString):
            return list(geometry.geoms)
        if hasattr(geometry, "geoms"):
            return [line for part in geometry.geoms for line in FrontlineEngine._lines(part)]
        return []
