"""Compact offline road routing derived from local OpenStreetMap PBF data."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np


ROAD_ROUTING_SCHEMA = "moosebridge.road_routing"
ROAD_ROUTING_SCHEMA_VERSION = 1


@dataclass(slots=True, frozen=True)
class RoadVehicleProfile:
    """Road speeds for one DCS-compatible military ground profile."""

    name: str
    speeds_kph: Mapping[str, float]
    default_speed_kph: float
    connector_speed_kph: float
    bridge_speed_kph: float | None = None

    def speed_kph(self, highway: str, *, bridge: bool) -> float:
        speed = float(self.speeds_kph.get(highway, self.default_speed_kph))
        if bridge and self.bridge_speed_kph is not None:
            speed = min(speed, self.bridge_speed_kph)
        return speed

    @property
    def maximum_speed_kph(self) -> float:
        values = (*self.speeds_kph.values(), self.default_speed_kph, self.connector_speed_kph)
        return max(float(value) for value in values)


WHEELED_ROAD_PROFILE = RoadVehicleProfile(
    name="wheeled",
    speeds_kph={
        "motorway": 70, "motorway_link": 50, "trunk": 60, "trunk_link": 45,
        "primary": 50, "primary_link": 40, "secondary": 40,
        "secondary_link": 35, "tertiary": 35, "tertiary_link": 30,
        "residential": 30, "unclassified": 30, "living_street": 20,
        "service": 20, "road": 25,
    },
    default_speed_kph=20,
    connector_speed_kph=12,
    bridge_speed_kph=None,
)

TRACKED_ROAD_PROFILE = RoadVehicleProfile(
    name="tracked",
    speeds_kph={
        "motorway": 45, "motorway_link": 38, "trunk": 42, "trunk_link": 36,
        "primary": 38, "primary_link": 34, "secondary": 34,
        "secondary_link": 30, "tertiary": 30, "tertiary_link": 28,
        "residential": 25, "unclassified": 25, "living_street": 18,
        "service": 18, "road": 22,
    },
    default_speed_kph=18,
    connector_speed_kph=20,
    bridge_speed_kph=None,
)

LOGISTICS_ROAD_PROFILE = RoadVehicleProfile(
    name="logistics",
    speeds_kph={
        "motorway": 65, "motorway_link": 45, "trunk": 55, "trunk_link": 42,
        "primary": 48, "primary_link": 38, "secondary": 38,
        "secondary_link": 32, "tertiary": 32, "tertiary_link": 28,
        "residential": 27, "unclassified": 27, "living_street": 18,
        "service": 18, "road": 23,
    },
    default_speed_kph=18,
    connector_speed_kph=10,
    bridge_speed_kph=None,
)


@dataclass(slots=True, frozen=True)
class PythonRoadRoute:
    """One route calculated entirely by the local Python road graph."""

    profile: str
    points: tuple[tuple[float, float], ...]
    distance_m: float
    travel_time_s: float
    road_distance_m: float
    connector_distance_m: float
    bridge_count: int
    edge_count: int
    start_node: int
    end_node: int


class RoadRoutingNetwork:
    """Compact undirected OSM road graph for DCS-compatible movement."""

    def __init__(
        self,
        *,
        theater_id: str,
        node_osm_ids: np.ndarray,
        node_longitudes: np.ndarray,
        node_latitudes: np.ndarray,
        node_x: np.ndarray,
        node_y: np.ndarray,
        edge_u: np.ndarray,
        edge_v: np.ndarray,
        edge_lengths_m: np.ndarray,
        edge_highway_codes: np.ndarray,
        edge_bridge: np.ndarray,
        geometry_offsets: np.ndarray,
        geometry_longitudes: np.ndarray,
        geometry_latitudes: np.ndarray,
        adjacency_offsets: np.ndarray,
        adjacency_edges: np.ndarray,
        highway_classes: tuple[str, ...],
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.theater_id = theater_id
        self.node_osm_ids = node_osm_ids
        self.node_longitudes = node_longitudes
        self.node_latitudes = node_latitudes
        self.node_x = node_x
        self.node_y = node_y
        self.edge_u = edge_u
        self.edge_v = edge_v
        self.edge_lengths_m = edge_lengths_m
        self.edge_highway_codes = edge_highway_codes
        self.edge_bridge = edge_bridge
        self.geometry_offsets = geometry_offsets
        self.geometry_longitudes = geometry_longitudes
        self.geometry_latitudes = geometry_latitudes
        self.adjacency_offsets = adjacency_offsets
        self.adjacency_edges = adjacency_edges
        self.highway_classes = highway_classes
        self.metadata = dict(metadata or {})
        self._spatial_index: Any = None
        self._validate()

    @property
    def node_count(self) -> int:
        return int(len(self.node_osm_ids))

    @property
    def edge_count(self) -> int:
        return int(len(self.edge_u))

    def _validate(self) -> None:
        node_count = self.node_count
        edge_count = self.edge_count
        if not self.theater_id or node_count == 0 or edge_count == 0:
            raise ValueError("road routing network requires theater, nodes, and edges")
        if not all(len(values) == node_count for values in (
            self.node_longitudes, self.node_latitudes, self.node_x, self.node_y,
        )):
            raise ValueError("road routing node arrays have inconsistent lengths")
        if not all(len(values) == edge_count for values in (
            self.edge_v, self.edge_lengths_m, self.edge_highway_codes, self.edge_bridge,
        )):
            raise ValueError("road routing edge arrays have inconsistent lengths")
        if len(self.geometry_offsets) != edge_count + 1:
            raise ValueError("road routing geometry offsets are inconsistent")
        if len(self.geometry_longitudes) != len(self.geometry_latitudes):
            raise ValueError("road routing geometry arrays are inconsistent")
        if len(self.adjacency_offsets) != node_count + 1:
            raise ValueError("road routing adjacency offsets are inconsistent")
        if np.any(self.edge_u < 0) or np.any(self.edge_v < 0):
            raise ValueError("road routing edge references a negative node")
        if np.any(self.edge_u >= node_count) or np.any(self.edge_v >= node_count):
            raise ValueError("road routing edge references an unknown node")

    def nearest_node(self, latitude: float, longitude: float) -> tuple[int, float]:
        """Return nearest graph node and projected distance in meters."""

        try:
            from pyproj import Transformer
            from scipy.spatial import cKDTree
        except ImportError as exc:
            raise RuntimeError('road routing requires: python -m pip install -e ".[routing]"') from exc
        if self._spatial_index is None:
            self._spatial_index = cKDTree(np.column_stack((self.node_x, self.node_y)))
        x, y = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform(longitude, latitude)
        distance, node = self._spatial_index.query((x, y), k=1)
        return int(node), float(distance)

    def route(
        self,
        start_latitude: float,
        start_longitude: float,
        end_latitude: float,
        end_longitude: float,
        *,
        profile: RoadVehicleProfile = TRACKED_ROAD_PROFILE,
    ) -> PythonRoadRoute | None:
        """Calculate a fastest road route with unrestricted military access."""

        start_node, start_connector = self.nearest_node(start_latitude, start_longitude)
        end_node, end_connector = self.nearest_node(end_latitude, end_longitude)
        maximum_speed_mps = profile.maximum_speed_kph / 3.6
        queue: list[tuple[float, float, int]] = [(0.0, 0.0, start_node)]
        costs = {start_node: 0.0}
        previous: dict[int, tuple[int, int]] = {}
        while queue:
            _, cost, node = heapq.heappop(queue)
            if cost != costs.get(node):
                continue
            if node == end_node:
                break
            begin = int(self.adjacency_offsets[node])
            finish = int(self.adjacency_offsets[node + 1])
            for edge_index in self.adjacency_edges[begin:finish]:
                edge = int(edge_index)
                u = int(self.edge_u[edge])
                v = int(self.edge_v[edge])
                neighbor = v if u == node else u
                highway = self.highway_classes[int(self.edge_highway_codes[edge])]
                speed_mps = profile.speed_kph(highway, bridge=bool(self.edge_bridge[edge])) / 3.6
                candidate = cost + float(self.edge_lengths_m[edge]) / speed_mps
                if candidate >= costs.get(neighbor, math.inf):
                    continue
                costs[neighbor] = candidate
                previous[neighbor] = (node, edge)
                heuristic = math.hypot(
                    float(self.node_x[neighbor] - self.node_x[end_node]),
                    float(self.node_y[neighbor] - self.node_y[end_node]),
                ) / maximum_speed_mps
                heapq.heappush(queue, (candidate + heuristic, candidate, neighbor))
        if end_node not in costs:
            return None

        edges: list[tuple[int, int]] = []
        cursor = end_node
        while cursor != start_node:
            prior, edge = previous[cursor]
            edges.append((edge, cursor))
            cursor = prior
        edges.reverse()
        points: list[tuple[float, float]] = [(start_latitude, start_longitude)]
        cursor = start_node
        for edge, destination in edges:
            start = int(self.geometry_offsets[edge])
            finish = int(self.geometry_offsets[edge + 1])
            coordinates = list(zip(
                self.geometry_latitudes[start:finish],
                self.geometry_longitudes[start:finish],
            ))
            if cursor != int(self.edge_u[edge]):
                coordinates.reverse()
            for latitude, longitude in coordinates:
                point = (float(latitude), float(longitude))
                if point != points[-1]:
                    points.append(point)
            cursor = destination
        end_point = (end_latitude, end_longitude)
        if end_point != points[-1]:
            points.append(end_point)
        connector_distance = start_connector + end_connector
        connector_time = connector_distance / (profile.connector_speed_kph / 3.6)
        road_distance = sum(float(self.edge_lengths_m[edge]) for edge, _ in edges)
        return PythonRoadRoute(
            profile=profile.name,
            points=tuple(points),
            distance_m=road_distance + connector_distance,
            travel_time_s=costs[end_node] + connector_time,
            road_distance_m=road_distance,
            connector_distance_m=connector_distance,
            bridge_count=sum(bool(self.edge_bridge[edge]) for edge, _ in edges),
            edge_count=len(edges),
            start_node=start_node,
            end_node=end_node,
        )

    def save(self, path: str | Path) -> Path:
        """Save the compact graph as a compressed, non-pickle NPZ artifact."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "schema": ROAD_ROUTING_SCHEMA,
            "schema_version": ROAD_ROUTING_SCHEMA_VERSION,
            "theater_id": self.theater_id,
            "highway_classes": list(self.highway_classes),
            "metadata": self.metadata,
        }
        np.savez_compressed(
            target,
            metadata=np.asarray(json.dumps(metadata, ensure_ascii=True)),
            node_osm_ids=self.node_osm_ids,
            node_longitudes=self.node_longitudes,
            node_latitudes=self.node_latitudes,
            node_x=self.node_x,
            node_y=self.node_y,
            edge_u=self.edge_u,
            edge_v=self.edge_v,
            edge_lengths_m=self.edge_lengths_m,
            edge_highway_codes=self.edge_highway_codes,
            edge_bridge=self.edge_bridge,
            geometry_offsets=self.geometry_offsets,
            geometry_longitudes=self.geometry_longitudes,
            geometry_latitudes=self.geometry_latitudes,
            adjacency_offsets=self.adjacency_offsets,
            adjacency_edges=self.adjacency_edges,
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> "RoadRoutingNetwork":
        """Load a compact road graph without allowing pickled values."""

        with np.load(Path(path), allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata"]))
            if metadata.get("schema") != ROAD_ROUTING_SCHEMA:
                raise ValueError("not a MooseBridge road-routing artifact")
            if int(metadata.get("schema_version") or 0) != ROAD_ROUTING_SCHEMA_VERSION:
                raise ValueError("unsupported road-routing schema version")
            return cls(
                theater_id=str(metadata.get("theater_id") or ""),
                node_osm_ids=payload["node_osm_ids"].copy(),
                node_longitudes=payload["node_longitudes"].copy(),
                node_latitudes=payload["node_latitudes"].copy(),
                node_x=payload["node_x"].copy(),
                node_y=payload["node_y"].copy(),
                edge_u=payload["edge_u"].copy(),
                edge_v=payload["edge_v"].copy(),
                edge_lengths_m=payload["edge_lengths_m"].copy(),
                edge_highway_codes=payload["edge_highway_codes"].copy(),
                edge_bridge=payload["edge_bridge"].copy(),
                geometry_offsets=payload["geometry_offsets"].copy(),
                geometry_longitudes=payload["geometry_longitudes"].copy(),
                geometry_latitudes=payload["geometry_latitudes"].copy(),
                adjacency_offsets=payload["adjacency_offsets"].copy(),
                adjacency_edges=payload["adjacency_edges"].copy(),
                highway_classes=tuple(str(value) for value in metadata.get("highway_classes") or []),
                metadata=metadata.get("metadata") or {},
            )


def build_road_routing_network(
    *,
    theater_id: str,
    nodes: Any,
    edges: Any,
    source_names: Iterable[str] = (),
) -> RoadRoutingNetwork:
    """Compile Pyrosm node/edge frames into a compact undirected graph."""

    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise RuntimeError('road routing requires: python -m pip install -e ".[routing]"') from exc
    if nodes.empty or edges.empty:
        raise ValueError("Pyrosm returned an empty driving network")
    node_ids = nodes["id"].astype("int64").to_numpy()
    order = np.argsort(node_ids)
    node_ids = node_ids[order]
    node_longitudes = nodes["lon"].astype("float64").to_numpy()[order]
    node_latitudes = nodes["lat"].astype("float64").to_numpy()[order]
    node_lookup = {int(osm_id): index for index, osm_id in enumerate(node_ids)}
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform(
        node_longitudes, node_latitudes,
    )
    highway_values = sorted({str(value) for value in edges["highway"].dropna().unique()})
    highway_classes = tuple(highway_values + (["unknown"] if "unknown" not in highway_values else []))
    highway_codes = {value: index for index, value in enumerate(highway_classes)}
    edge_u: list[int] = []
    edge_v: list[int] = []
    lengths: list[float] = []
    classes: list[int] = []
    bridges: list[bool] = []
    geometry_offsets = [0]
    geometry_longitudes: list[float] = []
    geometry_latitudes: list[float] = []
    seen: set[tuple[int, int, int]] = set()
    for record in edges.itertuples(index=False):
        u_osm, v_osm = int(record.u), int(record.v)
        u = node_lookup.get(u_osm)
        v = node_lookup.get(v_osm)
        if u is None or v is None or u == v:
            continue
        source_id = int(getattr(record, "id", 0) or 0)
        key = (min(u_osm, v_osm), max(u_osm, v_osm), source_id)
        if key in seen:
            continue
        seen.add(key)
        length = float(record.length or 0)
        geometry = record.geometry
        if length <= 0 or geometry is None or geometry.is_empty or geometry.geom_type != "LineString":
            continue
        coordinates = tuple(geometry.coords)
        if len(coordinates) < 2:
            continue
        edge_u.append(u)
        edge_v.append(v)
        lengths.append(length)
        classes.append(highway_codes.get(str(record.highway), highway_codes["unknown"]))
        bridge = getattr(record, "bridge", None)
        bridges.append(bridge is not None and str(bridge).lower() not in {"", "no", "none", "nan"})
        geometry_longitudes.extend(float(point[0]) for point in coordinates)
        geometry_latitudes.extend(float(point[1]) for point in coordinates)
        geometry_offsets.append(len(geometry_longitudes))
    if not edge_u:
        raise ValueError("Pyrosm driving network contains no usable line edges")

    edge_u_array = np.asarray(edge_u, dtype=np.int32)
    edge_v_array = np.asarray(edge_v, dtype=np.int32)
    counts = np.bincount(
        np.concatenate((edge_u_array, edge_v_array)), minlength=len(node_ids),
    )
    adjacency_offsets = np.zeros(len(node_ids) + 1, dtype=np.int64)
    np.cumsum(counts, out=adjacency_offsets[1:])
    adjacency_edges = np.empty(len(edge_u_array) * 2, dtype=np.int32)
    cursor = adjacency_offsets[:-1].copy()
    for edge_index, (u, v) in enumerate(zip(edge_u_array, edge_v_array)):
        adjacency_edges[cursor[u]] = edge_index
        cursor[u] += 1
        adjacency_edges[cursor[v]] = edge_index
        cursor[v] += 1
    return RoadRoutingNetwork(
        theater_id=theater_id,
        node_osm_ids=node_ids,
        node_longitudes=node_longitudes,
        node_latitudes=node_latitudes,
        node_x=np.asarray(x, dtype=np.float64),
        node_y=np.asarray(y, dtype=np.float64),
        edge_u=edge_u_array,
        edge_v=edge_v_array,
        edge_lengths_m=np.asarray(lengths, dtype=np.float32),
        edge_highway_codes=np.asarray(classes, dtype=np.uint16),
        edge_bridge=np.asarray(bridges, dtype=np.bool_),
        geometry_offsets=np.asarray(geometry_offsets, dtype=np.int64),
        geometry_longitudes=np.asarray(geometry_longitudes, dtype=np.float32),
        geometry_latitudes=np.asarray(geometry_latitudes, dtype=np.float32),
        adjacency_offsets=adjacency_offsets,
        adjacency_edges=adjacency_edges,
        highway_classes=highway_classes,
        metadata={
            "method": "pyrosm_compact_undirected",
            "source_names": list(source_names),
            "oneway_ignored": True,
            "access_ignored": True,
            "bridge_restrictions": False,
        },
    )


def merge_road_routing_artifacts(
    paths: Iterable[str | Path],
    *,
    theater_id: str,
    allowed_cells: Iterable[tuple[int, int]] | None = None,
    cell_size_m: float | None = None,
) -> RoadRoutingNetwork:
    """Merge compact regional graphs through their globally stable OSM node IDs."""

    sources = tuple(Path(path) for path in paths)
    if not sources:
        raise ValueError("at least one road-routing artifact is required")
    allowed_cell_values = tuple(allowed_cells) if allowed_cells is not None else None
    if allowed_cell_values is not None and (cell_size_m is None or cell_size_m <= 0):
        raise ValueError("filtered road merge requires a positive cell size")
    allowed_keys = (
        np.asarray(sorted(_routing_cell_key(column, row) for column, row in allowed_cell_values), dtype=np.int64)
        if allowed_cell_values is not None else None
    )
    node_chunks: list[np.ndarray] = []
    highway_values: set[str] = set()
    edge_count = 0
    geometry_count = 0
    source_names: list[str] = []
    for path in sources:
        with np.load(path, allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata"]))
            selected_edges = _selected_routing_edges(payload, allowed_keys, cell_size_m)
            local_u = payload["edge_u"][selected_edges]
            local_v = payload["edge_v"][selected_edges]
            selected_nodes = np.unique(np.concatenate((local_u, local_v)))
            node_chunks.append(payload["node_osm_ids"][selected_nodes])
            edge_count += len(selected_edges)
            offsets = payload["geometry_offsets"]
            geometry_count += int(np.sum(offsets[selected_edges + 1] - offsets[selected_edges]))
            highway_values.update(str(value) for value in metadata.get("highway_classes") or ())
            source_names.extend(str(value) for value in (metadata.get("metadata") or {}).get("source_names") or ())
    if edge_count == 0:
        raise ValueError("selected road-routing corridor contains no edges")
    node_ids = np.unique(np.concatenate(node_chunks))
    del node_chunks
    node_count = len(node_ids)
    node_longitudes = np.full(node_count, np.nan, dtype=np.float64)
    node_latitudes = np.full(node_count, np.nan, dtype=np.float64)
    node_x = np.full(node_count, np.nan, dtype=np.float64)
    node_y = np.full(node_count, np.nan, dtype=np.float64)
    edge_u = np.empty(edge_count, dtype=np.int32)
    edge_v = np.empty(edge_count, dtype=np.int32)
    edge_lengths = np.empty(edge_count, dtype=np.float32)
    edge_highways = np.empty(edge_count, dtype=np.uint16)
    edge_bridges = np.empty(edge_count, dtype=np.bool_)
    geometry_offsets = np.empty(edge_count + 1, dtype=np.int64)
    geometry_longitudes = np.empty(geometry_count, dtype=np.float32)
    geometry_latitudes = np.empty(geometry_count, dtype=np.float32)
    highway_classes = tuple(sorted(highway_values))
    highway_codes = {value: index for index, value in enumerate(highway_classes)}
    edge_cursor = 0
    geometry_cursor = 0
    for path in sources:
        with np.load(path, allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata"]))
            local_ids = payload["node_osm_ids"]
            selected_edges = _selected_routing_edges(payload, allowed_keys, cell_size_m)
            local_u = payload["edge_u"][selected_edges]
            local_v = payload["edge_v"][selected_edges]
            selected_local_nodes = np.unique(np.concatenate((local_u, local_v)))
            selected_global_nodes = np.searchsorted(node_ids, local_ids[selected_local_nodes])
            empty = np.isnan(node_longitudes[selected_global_nodes])
            local_to_fill = selected_local_nodes[empty]
            global_to_fill = selected_global_nodes[empty]
            node_longitudes[global_to_fill] = payload["node_longitudes"][local_to_fill]
            node_latitudes[global_to_fill] = payload["node_latitudes"][local_to_fill]
            node_x[global_to_fill] = payload["node_x"][local_to_fill]
            node_y[global_to_fill] = payload["node_y"][local_to_fill]
            count = len(local_u)
            finish = edge_cursor + count
            edge_u[edge_cursor:finish] = np.searchsorted(node_ids, local_ids[local_u])
            edge_v[edge_cursor:finish] = np.searchsorted(node_ids, local_ids[local_v])
            edge_lengths[edge_cursor:finish] = payload["edge_lengths_m"][selected_edges]
            local_classes = tuple(str(value) for value in metadata.get("highway_classes") or ())
            code_map = np.asarray([highway_codes[value] for value in local_classes], dtype=np.uint16)
            edge_highways[edge_cursor:finish] = code_map[payload["edge_highway_codes"][selected_edges]]
            edge_bridges[edge_cursor:finish] = payload["edge_bridge"][selected_edges]
            local_offsets = payload["geometry_offsets"]
            lengths = local_offsets[selected_edges + 1] - local_offsets[selected_edges]
            local_geometry_count = int(np.sum(lengths))
            geometry_finish = geometry_cursor + local_geometry_count
            selected_offsets = np.zeros(count + 1, dtype=np.int64)
            np.cumsum(lengths, out=selected_offsets[1:])
            geometry_offsets[edge_cursor:finish + 1] = selected_offsets + geometry_cursor
            if local_geometry_count:
                repeated_starts = np.repeat(local_offsets[selected_edges] - selected_offsets[:-1], lengths)
                geometry_indices = np.arange(local_geometry_count, dtype=np.int64) + repeated_starts
                geometry_longitudes[geometry_cursor:geometry_finish] = payload["geometry_longitudes"][geometry_indices]
                geometry_latitudes[geometry_cursor:geometry_finish] = payload["geometry_latitudes"][geometry_indices]
            edge_cursor = finish
            geometry_cursor = geometry_finish
    if np.isnan(node_longitudes).any():
        raise ValueError("merged road graph contains nodes without coordinates")
    counts = np.bincount(np.concatenate((edge_u, edge_v)), minlength=node_count)
    adjacency_offsets = np.zeros(node_count + 1, dtype=np.int64)
    np.cumsum(counts, out=adjacency_offsets[1:])
    adjacency_edges = np.empty(edge_count * 2, dtype=np.int32)
    cursor = adjacency_offsets[:-1].copy()
    for edge_index, (u, v) in enumerate(zip(edge_u, edge_v)):
        adjacency_edges[cursor[u]] = edge_index
        cursor[u] += 1
        adjacency_edges[cursor[v]] = edge_index
        cursor[v] += 1
    return RoadRoutingNetwork(
        theater_id=theater_id,
        node_osm_ids=node_ids,
        node_longitudes=node_longitudes,
        node_latitudes=node_latitudes,
        node_x=node_x,
        node_y=node_y,
        edge_u=edge_u,
        edge_v=edge_v,
        edge_lengths_m=edge_lengths,
        edge_highway_codes=edge_highways,
        edge_bridge=edge_bridges,
        geometry_offsets=geometry_offsets,
        geometry_longitudes=geometry_longitudes,
        geometry_latitudes=geometry_latitudes,
        adjacency_offsets=adjacency_offsets,
        adjacency_edges=adjacency_edges,
        highway_classes=highway_classes,
        metadata={
            "method": "pyrosm_compact_undirected_merged",
            "source_names": list(dict.fromkeys(source_names)),
            "partial_artifact_count": len(sources),
            "oneway_ignored": True,
            "access_ignored": True,
            "bridge_restrictions": False,
            "corridor_filtered": allowed_keys is not None,
        },
    )


def _routing_cell_key(column: int, row: int) -> int:
    return (int(column) << 32) ^ (int(row) & 0xFFFFFFFF)


def _selected_routing_edges(
    payload: Any,
    allowed_keys: np.ndarray | None,
    cell_size_m: float | None,
) -> np.ndarray:
    edge_count = len(payload["edge_u"])
    if allowed_keys is None:
        return np.arange(edge_count, dtype=np.int64)
    assert cell_size_m is not None
    columns = np.floor(payload["node_x"] / cell_size_m).astype(np.int64)
    rows = np.floor(payload["node_y"] / cell_size_m).astype(np.int64)
    node_keys = (columns << 32) ^ (rows & 0xFFFFFFFF)
    allowed_nodes = np.isin(node_keys, allowed_keys, assume_unique=False)
    mask = allowed_nodes[payload["edge_u"]] | allowed_nodes[payload["edge_v"]]
    return np.flatnonzero(mask)


def format_python_road_route(route: PythonRoadRoute | None) -> str:
    """Format a concise route diagnostic."""

    if route is None:
        return "No connected Python road route was found."
    return (
        f"Python road route profile={route.profile} distance={route.distance_m / 1000:.1f}km "
        f"eta={route.travel_time_s / 60:.0f}min roads={route.road_distance_m / 1000:.1f}km "
        f"connectors={route.connector_distance_m / 1000:.1f}km bridges={route.bridge_count} "
        f"edges={route.edge_count} points={len(route.points)}"
    )
