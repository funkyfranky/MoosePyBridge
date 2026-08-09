"""Strategic ground-mobility graph derived from immutable theater geography."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import heapq
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .surface_regions import SurfaceClass, TheaterSurfaceRegions


GROUND_MOBILITY_SCHEMA = "moosebridge.ground_mobility"
GROUND_MOBILITY_SCHEMA_VERSION = 1


class RoadClass(StrEnum):
    MOTORWAY = "motorway"
    TRUNK = "trunk"
    PRIMARY = "primary"
    SECONDARY = "secondary"


ROAD_CLASS_RANK = {
    RoadClass.MOTORWAY: 1,
    RoadClass.TRUNK: 2,
    RoadClass.PRIMARY: 3,
    RoadClass.SECONDARY: 4,
}
ROAD_CLASS_BY_RANK = {rank: road_class for road_class, rank in ROAD_CLASS_RANK.items()}


@dataclass(slots=True, frozen=True)
class GroundMobilityProfile:
    """Travel-speed assumptions for one broad ground-platform family."""

    name: str
    offroad_speed_kph: float
    road_speeds_kph: Mapping[RoadClass, float]
    bridge_speed_kph: float

    def speed_kph(self, edge: GroundMobilityEdge) -> float:
        if edge.bridge:
            return self.bridge_speed_kph
        if edge.road_class is not None:
            return float(self.road_speeds_kph.get(edge.road_class, self.offroad_speed_kph))
        return self.offroad_speed_kph

    def calibrated_to_max_speed(
        self,
        maximum_speed_kph: float,
        *,
        dcs_type: str | None = None,
    ) -> GroundMobilityProfile:
        """Scale this profile so its fastest edge equals a DCS ``MaxSpeed`` value."""

        maximum_speed_kph = float(maximum_speed_kph)
        if not math.isfinite(maximum_speed_kph) or maximum_speed_kph <= 0:
            raise ValueError("maximum_speed_kph must be finite and positive")
        baseline_maximum = max(
            self.offroad_speed_kph,
            self.bridge_speed_kph,
            *self.road_speeds_kph.values(),
        )
        scale = maximum_speed_kph / baseline_maximum
        profile_name = f"dcs_max_speed:{dcs_type or 'ground'}:{maximum_speed_kph:g}kph"
        return GroundMobilityProfile(
            name=profile_name,
            offroad_speed_kph=self.offroad_speed_kph * scale,
            road_speeds_kph={road_class: speed * scale for road_class, speed in self.road_speeds_kph.items()},
            bridge_speed_kph=self.bridge_speed_kph * scale,
        )


WHEELED_GROUND_PROFILE = GroundMobilityProfile(
    name="wheeled",
    offroad_speed_kph=12.0,
    road_speeds_kph={
        RoadClass.MOTORWAY: 70.0,
        RoadClass.TRUNK: 60.0,
        RoadClass.PRIMARY: 50.0,
        RoadClass.SECONDARY: 40.0,
    },
    bridge_speed_kph=30.0,
)
TRACKED_GROUND_PROFILE = GroundMobilityProfile(
    name="tracked",
    offroad_speed_kph=20.0,
    road_speeds_kph={
        RoadClass.MOTORWAY: 45.0,
        RoadClass.TRUNK: 42.0,
        RoadClass.PRIMARY: 38.0,
        RoadClass.SECONDARY: 34.0,
    },
    bridge_speed_kph=25.0,
)


@dataclass(slots=True, frozen=True)
class GroundTransportFeature:
    """One normalized WGS84 road geometry consumed by the graph builder."""

    source_id: str
    road_class: RoadClass
    geometry: dict[str, Any]
    bridge: bool = False
    coordinate_system: str = "EPSG:4326"


@dataclass(slots=True, frozen=True)
class GroundMobilityNode:
    node_id: int
    x: float
    y: float
    latitude: float
    longitude: float
    land_region_index: int
    component_id: int
    road_class: RoadClass | None = None


@dataclass(slots=True, frozen=True)
class GroundMobilityEdge:
    start: int
    end: int
    distance_m: float
    road_class: RoadClass | None = None
    bridge: bool = False


@dataclass(slots=True, frozen=True)
class GroundRoute:
    profile: str
    start_node: int
    end_node: int
    node_ids: tuple[int, ...]
    distance_m: float
    travel_time_s: float
    bridge_count: int
    road_distance_m: float

    def to_geojson(self, network: GroundMobilityNetwork) -> dict[str, Any]:
        coordinates = [
            [network.nodes[node_id].longitude, network.nodes[node_id].latitude]
            for node_id in self.node_ids
        ]
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coordinates},
            "properties": {
                "layer": "ground_mobility_route",
                "profile": self.profile,
                "distance_m": self.distance_m,
                "travel_time_s": self.travel_time_s,
                "bridge_count": self.bridge_count,
                "road_distance_m": self.road_distance_m,
            },
        }


@dataclass(slots=True)
class GroundMobilityNetwork:
    """A compact strategic graph; MOOSE remains owner of tactical routing."""

    theater_id: str
    grid_spacing_m: float
    land_region_ids: tuple[str, ...]
    nodes: tuple[GroundMobilityNode, ...]
    edges: tuple[GroundMobilityEdge, ...]
    bounds: tuple[float, float, float, float]
    metadata: dict[str, Any] = field(default_factory=dict)
    _adjacency: tuple[tuple[tuple[int, GroundMobilityEdge], ...], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.theater_id or self.grid_spacing_m <= 0:
            raise ValueError("ground mobility network requires theater_id and positive grid spacing")
        if any(node.node_id != index for index, node in enumerate(self.nodes)):
            raise ValueError("ground mobility node IDs must be dense and ordered")
        adjacency: list[list[tuple[int, GroundMobilityEdge]]] = [[] for _ in self.nodes]
        for edge in self.edges:
            if edge.start < 0 or edge.end < 0 or edge.start >= len(self.nodes) or edge.end >= len(self.nodes):
                raise ValueError("ground mobility edge references an unknown node")
            adjacency[edge.start].append((edge.end, edge))
            adjacency[edge.end].append((edge.start, edge))
        self._adjacency = tuple(tuple(items) for items in adjacency)

    @property
    def component_count(self) -> int:
        return len({node.component_id for node in self.nodes})

    def nearest_node(self, latitude: float, longitude: float) -> GroundMobilityNode:
        if not self.nodes:
            raise ValueError("ground mobility network contains no nodes")
        try:
            from pyproj import Transformer
        except ImportError as exc:
            raise RuntimeError('ground mobility requires: python -m pip install -e ".[topography]"') from exc
        x, y = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform(longitude, latitude)
        return min(self.nodes, key=lambda node: (node.x - x) ** 2 + (node.y - y) ** 2)

    def route(
        self,
        start_latitude: float,
        start_longitude: float,
        end_latitude: float,
        end_longitude: float,
        *,
        profile: GroundMobilityProfile = TRACKED_GROUND_PROFILE,
    ) -> GroundRoute | None:
        start = self.nearest_node(start_latitude, start_longitude)
        end = self.nearest_node(end_latitude, end_longitude)
        if start.component_id != end.component_id:
            return None

        maximum_speed_mps = max(
            profile.offroad_speed_kph,
            profile.bridge_speed_kph,
            *profile.road_speeds_kph.values(),
        ) / 3.6
        queue = [(0.0, 0.0, start.node_id)]
        costs = {start.node_id: 0.0}
        previous: dict[int, tuple[int, GroundMobilityEdge]] = {}
        while queue:
            _, cost, node_id = heapq.heappop(queue)
            if cost != costs.get(node_id):
                continue
            if node_id == end.node_id:
                break
            for neighbor_id, edge in self._adjacency[node_id]:
                speed_mps = profile.speed_kph(edge) / 3.6
                candidate = cost + edge.distance_m / speed_mps
                if candidate >= costs.get(neighbor_id, math.inf):
                    continue
                costs[neighbor_id] = candidate
                previous[neighbor_id] = (node_id, edge)
                neighbor = self.nodes[neighbor_id]
                heuristic = math.hypot(neighbor.x - end.x, neighbor.y - end.y) / maximum_speed_mps
                heapq.heappush(queue, (candidate + heuristic, candidate, neighbor_id))
        if end.node_id not in costs:
            return None

        node_ids = [end.node_id]
        route_edges = []
        cursor = end.node_id
        while cursor != start.node_id:
            prior, edge = previous[cursor]
            route_edges.append(edge)
            node_ids.append(prior)
            cursor = prior
        node_ids.reverse()
        return GroundRoute(
            profile=profile.name,
            start_node=start.node_id,
            end_node=end.node_id,
            node_ids=tuple(node_ids),
            distance_m=sum(edge.distance_m for edge in route_edges),
            travel_time_s=costs[end.node_id],
            bridge_count=sum(edge.bridge for edge in route_edges),
            road_distance_m=sum(edge.distance_m for edge in route_edges if edge.road_class is not None),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GROUND_MOBILITY_SCHEMA,
            "schema_version": GROUND_MOBILITY_SCHEMA_VERSION,
            "theater_id": self.theater_id,
            "grid_spacing_m": self.grid_spacing_m,
            "bounds": list(self.bounds),
            "land_region_ids": list(self.land_region_ids),
            "nodes": [
                [
                    node.node_id, node.x, node.y, node.latitude, node.longitude,
                    node.land_region_index, node.component_id,
                    node.road_class.value if node.road_class else None,
                ]
                for node in self.nodes
            ],
            "edges": [
                [
                    edge.start, edge.end, edge.distance_m,
                    edge.road_class.value if edge.road_class else None,
                    edge.bridge,
                ]
                for edge in self.edges
            ],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GroundMobilityNetwork:
        if payload.get("schema") != GROUND_MOBILITY_SCHEMA:
            raise ValueError("not a MooseBridge ground-mobility artifact")
        if int(payload.get("schema_version") or 0) != GROUND_MOBILITY_SCHEMA_VERSION:
            raise ValueError("unsupported ground-mobility schema version")
        nodes = tuple(
            GroundMobilityNode(
                node_id=int(item[0]), x=float(item[1]), y=float(item[2]),
                latitude=float(item[3]), longitude=float(item[4]),
                land_region_index=int(item[5]), component_id=int(item[6]),
                road_class=RoadClass(item[7]) if item[7] else None,
            )
            for item in payload.get("nodes") or []
        )
        edges = tuple(
            GroundMobilityEdge(
                start=int(item[0]), end=int(item[1]), distance_m=float(item[2]),
                road_class=RoadClass(item[3]) if item[3] else None,
                bridge=bool(item[4]),
            )
            for item in payload.get("edges") or []
        )
        return cls(
            theater_id=str(payload.get("theater_id") or ""),
            grid_spacing_m=float(payload.get("grid_spacing_m") or 0),
            land_region_ids=tuple(str(value) for value in payload.get("land_region_ids") or []),
            nodes=nodes,
            edges=edges,
            bounds=tuple(float(value) for value in payload.get("bounds") or ()),  # type: ignore[arg-type]
            metadata=dict(payload.get("metadata") or {}),
        )

    @classmethod
    def load(cls, path: str | Path) -> GroundMobilityNetwork:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return target


def build_ground_mobility_network(
    surfaces: TheaterSurfaceRegions,
    transport_features: Iterable[GroundTransportFeature],
    *,
    grid_spacing_m: float = 5_000.0,
) -> GroundMobilityNetwork:
    """Build a bounded strategic graph from land regions and major roads."""

    if grid_spacing_m <= 0:
        raise ValueError("ground mobility grid spacing must be positive")
    try:
        import numpy as np
        import shapely
        from pyproj import Transformer
        from shapely.geometry import box, shape
        from shapely.ops import transform
    except ImportError as exc:
        raise RuntimeError('ground mobility requires: python -m pip install -e ".[topography]"') from exc

    south, west, north, east = surfaces.bounds
    to_local = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    to_wgs84 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    envelope = transform(to_local.transform, box(west, south, east, north))
    min_x, min_y, max_x, max_y = envelope.bounds
    xs = np.arange(min_x, max_x + grid_spacing_m, grid_spacing_m)
    ys = np.arange(min_y, max_y + grid_spacing_m, grid_spacing_m)
    region_grid = np.full((len(ys), len(xs)), -1, dtype=np.int32)
    land_region_ids = []
    land_geometries = []
    for region in surfaces.regions:
        if region.surface_class is not SurfaceClass.LAND:
            continue
        geometry = transform(to_local.transform, shape(region.geometry))
        if geometry.is_empty:
            continue
        region_index = len(land_region_ids)
        land_region_ids.append(region.region_id)
        land_geometries.append(geometry)
        _burn_region(region_grid, geometry, xs, ys, region_index, shapely)
    if not land_geometries:
        raise ValueError("surface artifact contains no land regions")
    land_union = shapely.union_all(land_geometries)

    road_grid = np.zeros_like(region_grid, dtype=np.uint8)
    bridge_geometries: list[tuple[Any, RoadClass]] = []
    source_count = 0
    bridge_source_count = 0
    for feature in transport_features:
        source_count += 1
        geometry = shape(feature.geometry)
        if feature.coordinate_system.upper() != "EPSG:3035":
            geometry = transform(to_local.transform, geometry)
        if geometry.is_empty:
            continue
        rank = ROAD_CLASS_RANK[feature.road_class]
        segmented = shapely.segmentize(geometry, max_segment_length=grid_spacing_m * 0.45)
        for line in _line_parts(segmented):
            coordinates = np.asarray(line.coords)
            columns = np.rint((coordinates[:, 0] - min_x) / grid_spacing_m).astype(int)
            rows = np.rint((coordinates[:, 1] - min_y) / grid_spacing_m).astype(int)
            valid = (rows >= 0) & (rows < len(ys)) & (columns >= 0) & (columns < len(xs))
            for row, column in zip(rows[valid], columns[valid]):
                current = int(road_grid[row, column])
                road_grid[row, column] = rank if current == 0 else min(current, rank)
        if feature.bridge:
            bridge_source_count += 1
            bridge_geometries.extend((line, feature.road_class) for line in _line_parts(geometry))

    node_grid = np.full_like(region_grid, -1, dtype=np.int32)
    rows, columns = np.nonzero(region_grid >= 0)
    node_grid[rows, columns] = np.arange(len(rows), dtype=np.int32)
    lon, lat = to_wgs84.transform(xs[columns], ys[rows])

    candidate_data: list[tuple[int, int, int, int, float]] = []
    for row_delta, column_delta in ((0, 1), (1, 0), (1, 1), (1, -1)):
        row_start = max(0, -row_delta)
        row_stop = min(len(ys), len(ys) - row_delta)
        column_start = max(0, -column_delta)
        column_stop = min(len(xs), len(xs) - column_delta)
        starts = node_grid[row_start:row_stop, column_start:column_stop]
        ends = node_grid[
            row_start + row_delta:row_stop + row_delta,
            column_start + column_delta:column_stop + column_delta,
        ]
        valid_rows, valid_columns = np.nonzero((starts >= 0) & (ends >= 0))
        distance = grid_spacing_m * math.hypot(row_delta, column_delta)
        for local_row, local_column in zip(valid_rows, valid_columns):
            candidate_data.append((
                int(starts[local_row, local_column]),
                int(ends[local_row, local_column]),
                row_start + int(local_row),
                column_start + int(local_column),
                distance,
            ))

    edges = []
    union_find = _UnionFind(len(rows))
    fractions = np.linspace(0.1, 0.9, 9)
    edge_keys: set[tuple[int, int]] = set()
    for start_id, end_id, start_row, start_column, distance in candidate_data:
        start_node_row = int(rows[start_id])
        start_node_column = int(columns[start_id])
        end_node_row = int(rows[end_id])
        end_node_column = int(columns[end_id])
        start_x, start_y = xs[start_node_column], ys[start_node_row]
        end_x, end_y = xs[end_node_column], ys[end_node_row]
        sample_x = start_x + (end_x - start_x) * fractions
        sample_y = start_y + (end_y - start_y) * fractions
        passable = bool(np.all(shapely.intersects_xy(land_union, sample_x, sample_y)))
        if not passable:
            continue
        start_rank = int(road_grid[start_node_row, start_node_column])
        end_rank = int(road_grid[end_node_row, end_node_column])
        edge_rank = max(start_rank, end_rank) if start_rank and end_rank else 0
        edge = GroundMobilityEdge(
            start=start_id,
            end=end_id,
            distance_m=distance,
            road_class=ROAD_CLASS_BY_RANK.get(edge_rank),
            bridge=False,
        )
        edges.append(edge)
        edge_keys.add((min(start_id, end_id), max(start_id, end_id)))
        union_find.union(start_id, end_id)

    # A strategic grid may contain no node in a narrow strait. Model each OSM
    # bridge as an explicit connection between land nodes beyond its two heads.
    node_x = xs[columns]
    node_y = ys[rows]
    for bridge_geometry, road_class in bridge_geometries:
        coordinates = np.asarray(bridge_geometry.coords)
        if len(coordinates) < 2:
            continue
        first = coordinates[0]
        last = coordinates[-1]
        direction = last - first
        length = float(np.linalg.norm(direction))
        if length <= 0:
            continue
        direction /= length
        extension = grid_spacing_m * 0.75
        first_probe = first - direction * extension
        last_probe = last + direction * extension
        start_id = int(np.argmin((node_x - first_probe[0]) ** 2 + (node_y - first_probe[1]) ** 2))
        end_id = int(np.argmin((node_x - last_probe[0]) ** 2 + (node_y - last_probe[1]) ** 2))
        if start_id == end_id:
            continue
        key = (min(start_id, end_id), max(start_id, end_id))
        if key in edge_keys:
            continue
        distance = float(math.hypot(node_x[end_id] - node_x[start_id], node_y[end_id] - node_y[start_id]))
        if distance > grid_spacing_m * 3.0:
            continue
        sample_x = node_x[start_id] + (node_x[end_id] - node_x[start_id]) * fractions
        sample_y = node_y[start_id] + (node_y[end_id] - node_y[start_id]) * fractions
        if bool(np.all(shapely.intersects_xy(land_union, sample_x, sample_y))):
            continue
        edge = GroundMobilityEdge(
            start=start_id,
            end=end_id,
            distance_m=distance,
            road_class=road_class,
            bridge=True,
        )
        edges.append(edge)
        edge_keys.add(key)
        union_find.union(start_id, end_id)

    component_roots: dict[int, int] = {}
    component_ids = []
    for node_id in range(len(rows)):
        root = union_find.find(node_id)
        component_ids.append(component_roots.setdefault(root, len(component_roots)))
    nodes = tuple(
        GroundMobilityNode(
            node_id=node_id,
            x=float(xs[column]),
            y=float(ys[row]),
            latitude=float(lat[node_id]),
            longitude=float(lon[node_id]),
            land_region_index=int(region_grid[row, column]),
            component_id=component_ids[node_id],
            road_class=ROAD_CLASS_BY_RANK.get(int(road_grid[row, column])),
        )
        for node_id, (row, column) in enumerate(zip(rows, columns))
    )
    return GroundMobilityNetwork(
        theater_id=surfaces.theater_id,
        grid_spacing_m=grid_spacing_m,
        land_region_ids=tuple(land_region_ids),
        nodes=nodes,
        edges=tuple(edges),
        bounds=surfaces.bounds,
        metadata={
            "method": "surface_constrained_strategic_grid",
            "crs": "EPSG:3035",
            "source_surface_method": surfaces.metadata.get("method"),
            "transport_feature_count": source_count,
            "bridge_feature_count": bridge_source_count,
            "road_node_count": int(np.count_nonzero(road_grid[rows, columns])),
            "bridge_edge_count": sum(edge.bridge for edge in edges),
            "component_count": len(component_roots),
            "road_classes": [road_class.value for road_class in RoadClass],
            "dcs_verification": "pending",
        },
    )


def format_ground_route(route: GroundRoute | None) -> str:
    if route is None:
        return "No connected strategic ground route was found."
    return (
        f"Ground route profile={route.profile} distance={route.distance_m / 1_000:.1f}km "
        f"eta={route.travel_time_s / 60:.0f}min road={route.road_distance_m / 1_000:.1f}km "
        f"bridges={route.bridge_count} nodes={len(route.node_ids)}"
    )


def _burn_region(target: Any, geometry: Any, xs: Any, ys: Any, value: int, shapely_module: Any) -> None:
    import numpy as np

    min_x, min_y, max_x, max_y = geometry.bounds
    column_start = max(0, int(np.searchsorted(xs, min_x, side="left")))
    column_stop = min(len(xs), int(np.searchsorted(xs, max_x, side="right")))
    row_start = max(0, int(np.searchsorted(ys, min_y, side="left")))
    row_stop = min(len(ys), int(np.searchsorted(ys, max_y, side="right")))
    if row_start >= row_stop or column_start >= column_stop:
        return
    mask = shapely_module.intersects_xy(
        geometry,
        xs[np.newaxis, column_start:column_stop],
        ys[row_start:row_stop, np.newaxis],
    )
    window = target[row_start:row_stop, column_start:column_stop]
    window[mask] = value


def _line_parts(geometry: Any) -> tuple[Any, ...]:
    if geometry.geom_type == "LineString":
        return (geometry,)
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return tuple(line for part in geometry.geoms for line in _line_parts(part))
    return ()


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, first: int, second: int) -> None:
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root == second_root:
            return
        if self.rank[first_root] < self.rank[second_root]:
            first_root, second_root = second_root, first_root
        self.parent[second_root] = first_root
        if self.rank[first_root] == self.rank[second_root]:
            self.rank[first_root] += 1
