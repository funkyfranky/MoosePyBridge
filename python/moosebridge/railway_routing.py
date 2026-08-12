"""Compact railway routing and bounded infrastructure failure analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace
import heapq
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from .railway_infrastructure import (
    RailwayLocation,
    RailwayLocationKind,
    TheaterRailwayInfrastructure,
)
from .topography import TopographyFeature, TopographyLayer


RAILWAY_ROUTING_SCHEMA = "moosebridge.railway_routing"
RAILWAY_ROUTING_SCHEMA_VERSION = 1


@dataclass(slots=True, frozen=True)
class RailwayRoute:
    start_node: int
    end_node: int
    node_ids: tuple[int, ...]
    distance_m: float
    edge_count: int


@dataclass(slots=True, frozen=True)
class RailwayCriticalityConfig:
    junction_block_radius_m: float = 180.0
    bridge_block_radius_m: float = 250.0
    maximum_route_m: float = 100_000.0
    maximum_portal_pairs: int = 3

    def __post_init__(self) -> None:
        if min(self.junction_block_radius_m, self.bridge_block_radius_m, self.maximum_route_m) <= 0:
            raise ValueError("railway criticality distances must be positive")
        if self.maximum_portal_pairs <= 0:
            raise ValueError("maximum_portal_pairs must be positive")


class RailwayRoutingNetwork:
    """Undirected OSM railway graph used only for strategic Python analysis."""

    def __init__(
        self,
        *,
        theater_id: str,
        node_longitudes: np.ndarray,
        node_latitudes: np.ndarray,
        node_x: np.ndarray,
        node_y: np.ndarray,
        edge_u: np.ndarray,
        edge_v: np.ndarray,
        edge_lengths_m: np.ndarray,
        edge_bridge: np.ndarray,
        adjacency_offsets: np.ndarray,
        adjacency_edges: np.ndarray,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.theater_id = theater_id
        self.node_longitudes = node_longitudes
        self.node_latitudes = node_latitudes
        self.node_x = node_x
        self.node_y = node_y
        self.edge_u = edge_u
        self.edge_v = edge_v
        self.edge_lengths_m = edge_lengths_m
        self.edge_bridge = edge_bridge
        self.adjacency_offsets = adjacency_offsets
        self.adjacency_edges = adjacency_edges
        self.metadata = dict(metadata or {})
        self._spatial_index: Any = None
        self._validate()

    @property
    def node_count(self) -> int:
        return len(self.node_longitudes)

    @property
    def edge_count(self) -> int:
        return len(self.edge_u)

    def _validate(self) -> None:
        if not self.theater_id or not self.node_count or not self.edge_count:
            raise ValueError("railway routing network requires theater, nodes, and edges")
        if not all(len(values) == self.node_count for values in (self.node_latitudes, self.node_x, self.node_y)):
            raise ValueError("railway routing node arrays have inconsistent lengths")
        if not all(len(values) == self.edge_count for values in (self.edge_v, self.edge_lengths_m, self.edge_bridge)):
            raise ValueError("railway routing edge arrays have inconsistent lengths")
        if len(self.adjacency_offsets) != self.node_count + 1:
            raise ValueError("railway routing adjacency offsets are inconsistent")

    def nearest_node(self, latitude: float, longitude: float) -> tuple[int, float]:
        try:
            from pyproj import Transformer
            from scipy.spatial import cKDTree
        except ImportError as exc:
            raise RuntimeError('railway routing requires: python -m pip install -e ".[routing]"') from exc
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
        blocked_nodes: frozenset[int] = frozenset(),
        maximum_distance_m: float = math.inf,
    ) -> RailwayRoute | None:
        start, _ = self.nearest_node(start_latitude, start_longitude)
        end, _ = self.nearest_node(end_latitude, end_longitude)
        result = self.shortest_path(start, end, blocked_nodes=blocked_nodes, maximum_distance_m=maximum_distance_m)
        if result is None:
            return None
        distance, nodes = result
        return RailwayRoute(start, end, nodes, distance, max(0, len(nodes) - 1))

    def shortest_path(
        self,
        start: int,
        end: int,
        *,
        blocked_nodes: frozenset[int] = frozenset(),
        blocked_edges: frozenset[int] = frozenset(),
        maximum_distance_m: float = math.inf,
    ) -> tuple[float, tuple[int, ...]] | None:
        if start in blocked_nodes or end in blocked_nodes:
            return None
        queue: list[tuple[float, float, int]] = [(0.0, 0.0, start)]
        costs = {start: 0.0}
        previous: dict[int, int] = {}
        while queue:
            _, cost, node = heapq.heappop(queue)
            if cost != costs.get(node):
                continue
            if node == end:
                break
            begin, finish = int(self.adjacency_offsets[node]), int(self.adjacency_offsets[node + 1])
            for edge_value in self.adjacency_edges[begin:finish]:
                edge = int(edge_value)
                if edge in blocked_edges:
                    continue
                u, v = int(self.edge_u[edge]), int(self.edge_v[edge])
                neighbor = v if u == node else u
                if neighbor in blocked_nodes:
                    continue
                candidate = cost + float(self.edge_lengths_m[edge])
                if candidate >= costs.get(neighbor, math.inf) or candidate > maximum_distance_m:
                    continue
                costs[neighbor] = candidate
                previous[neighbor] = node
                heuristic = math.hypot(
                    float(self.node_x[neighbor] - self.node_x[end]),
                    float(self.node_y[neighbor] - self.node_y[end]),
                )
                heapq.heappush(queue, (candidate + heuristic, candidate, neighbor))
        if end not in costs:
            return None
        nodes = [end]
        while nodes[-1] != start:
            nodes.append(previous[nodes[-1]])
        nodes.reverse()
        return costs[end], tuple(nodes)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "schema": RAILWAY_ROUTING_SCHEMA,
            "schema_version": RAILWAY_ROUTING_SCHEMA_VERSION,
            "theater_id": self.theater_id,
            "metadata": self.metadata,
        }
        np.savez_compressed(
            target,
            metadata=np.asarray(json.dumps(metadata, ensure_ascii=True)),
            node_longitudes=self.node_longitudes,
            node_latitudes=self.node_latitudes,
            node_x=self.node_x,
            node_y=self.node_y,
            edge_u=self.edge_u,
            edge_v=self.edge_v,
            edge_lengths_m=self.edge_lengths_m,
            edge_bridge=self.edge_bridge,
            adjacency_offsets=self.adjacency_offsets,
            adjacency_edges=self.adjacency_edges,
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> "RailwayRoutingNetwork":
        with np.load(Path(path), allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata"]))
            if metadata.get("schema") != RAILWAY_ROUTING_SCHEMA:
                raise ValueError("not a MooseBridge railway-routing artifact")
            if int(metadata.get("schema_version") or 0) != RAILWAY_ROUTING_SCHEMA_VERSION:
                raise ValueError("unsupported railway-routing schema version")
            return cls(
                theater_id=str(metadata.get("theater_id") or ""),
                node_longitudes=payload["node_longitudes"].copy(),
                node_latitudes=payload["node_latitudes"].copy(),
                node_x=payload["node_x"].copy(),
                node_y=payload["node_y"].copy(),
                edge_u=payload["edge_u"].copy(),
                edge_v=payload["edge_v"].copy(),
                edge_lengths_m=payload["edge_lengths_m"].copy(),
                edge_bridge=payload["edge_bridge"].copy(),
                adjacency_offsets=payload["adjacency_offsets"].copy(),
                adjacency_edges=payload["adjacency_edges"].copy(),
                metadata=metadata.get("metadata") or {},
            )


def build_railway_routing_network(
    features: Iterable[TopographyFeature],
    *,
    theater_id: str,
) -> RailwayRoutingNetwork:
    """Compile normalized OSM rail lines into a compact undirected graph."""

    from pyproj import Transformer

    node_lookup: dict[tuple[float, float], int] = {}
    longitudes: list[float] = []
    latitudes: list[float] = []
    edge_u: list[int] = []
    edge_v: list[int] = []
    lengths: list[float] = []
    bridges: list[bool] = []
    seen: set[tuple[int, int]] = set()
    source_count = 0
    for feature in features:
        if feature.layer is not TopographyLayer.RAILWAYS or feature.category != "rail":
            continue
        source_count += 1
        tags = feature.properties.get("osm_tags") or {}
        bridge = str(tags.get("bridge") or "").casefold() not in {"", "no", "false", "0", "none"}
        for line in _geometry_lines(feature.geometry):
            for first, second in zip(line, line[1:]):
                u = _node(node_lookup, longitudes, latitudes, first)
                v = _node(node_lookup, longitudes, latitudes, second)
                if u == v:
                    continue
                key = (min(u, v), max(u, v))
                if key in seen:
                    continue
                seen.add(key)
                edge_u.append(u)
                edge_v.append(v)
                lengths.append(_haversine_m(latitudes[u], longitudes[u], latitudes[v], longitudes[v]))
                bridges.append(bridge)
    if not edge_u:
        raise ValueError("railway features contain no usable line edges")
    lon_array = np.asarray(longitudes, dtype=np.float64)
    lat_array = np.asarray(latitudes, dtype=np.float64)
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform(lon_array, lat_array)
    u_array = np.asarray(edge_u, dtype=np.int32)
    v_array = np.asarray(edge_v, dtype=np.int32)
    counts = np.bincount(np.concatenate((u_array, v_array)), minlength=len(longitudes))
    offsets = np.zeros(len(longitudes) + 1, dtype=np.int64)
    np.cumsum(counts, out=offsets[1:])
    adjacency = np.empty(len(edge_u) * 2, dtype=np.int32)
    cursor = offsets[:-1].copy()
    for edge, (u, v) in enumerate(zip(u_array, v_array)):
        adjacency[cursor[u]] = edge
        cursor[u] += 1
        adjacency[cursor[v]] = edge
        cursor[v] += 1
    return RailwayRoutingNetwork(
        theater_id=theater_id,
        node_longitudes=lon_array,
        node_latitudes=lat_array,
        node_x=np.asarray(x, dtype=np.float64),
        node_y=np.asarray(y, dtype=np.float64),
        edge_u=u_array,
        edge_v=v_array,
        edge_lengths_m=np.asarray(lengths, dtype=np.float32),
        edge_bridge=np.asarray(bridges, dtype=np.bool_),
        adjacency_offsets=offsets,
        adjacency_edges=adjacency,
        metadata={"method": "normalized_osm_rail_lines", "source_feature_count": source_count},
    )


def analyze_railway_criticality(
    network: RailwayRoutingNetwork,
    infrastructure: TheaterRailwayInfrastructure,
    *,
    config: RailwayCriticalityConfig = RailwayCriticalityConfig(),
) -> TheaterRailwayInfrastructure:
    """Measure bounded route impact for high-value rail junctions and bridges."""

    from scipy.spatial import cKDTree

    tree = cKDTree(np.column_stack((network.node_x, network.node_y)))
    bridge_edges = np.flatnonzero(network.edge_bridge)
    edge_x = (network.node_x[network.edge_u[bridge_edges]] + network.node_x[network.edge_v[bridge_edges]]) / 2
    edge_y = (network.node_y[network.edge_u[bridge_edges]] + network.node_y[network.edge_v[bridge_edges]]) / 2
    bridge_tree = cKDTree(np.column_stack((edge_x, edge_y))) if len(bridge_edges) else None
    locations = []
    analyzed = 0
    for location in infrastructure.locations:
        if location.kind not in {RailwayLocationKind.JUNCTION, RailwayLocationKind.BRIDGE}:
            locations.append(location)
            continue
        if location.importance_tier.value not in {"high", "critical"}:
            locations.append(location)
            continue
        radius = config.bridge_block_radius_m if location.kind is RailwayLocationKind.BRIDGE else config.junction_block_radius_m
        properties = _location_impact(network, tree, bridge_tree, bridge_edges, location, radius, config)
        locations.append(replace(location, properties={**location.properties, **properties}))
        analyzed += 1
    return replace(
        infrastructure,
        locations=tuple(locations),
        metadata={
            **infrastructure.metadata,
            "railway_criticality_method": "bounded_node_block_and_alternative_route",
            "railway_criticality_location_count": analyzed,
            "railway_criticality_maximum_route_m": config.maximum_route_m,
        },
    )


def _location_impact(
    network: RailwayRoutingNetwork,
    tree: Any,
    bridge_tree: Any,
    bridge_edges: np.ndarray,
    location: RailwayLocation,
    radius_m: float,
    config: RailwayCriticalityConfig,
) -> dict[str, Any]:
    center, _ = network.nearest_node(location.latitude, location.longitude)
    blocked_nodes: frozenset[int] = frozenset()
    blocked_edges: frozenset[int] = frozenset()
    portals: set[int] = set()
    if location.kind is RailwayLocationKind.BRIDGE and bridge_tree is not None:
        local_edges = bridge_tree.query_ball_point((network.node_x[center], network.node_y[center]), radius_m)
        blocked_edges = frozenset(int(bridge_edges[index]) for index in local_edges)
        for edge in blocked_edges:
            portals.update((int(network.edge_u[edge]), int(network.edge_v[edge])))
    else:
        blocked_nodes = frozenset(int(value) for value in tree.query_ball_point((network.node_x[center], network.node_y[center]), radius_m))
        for node in blocked_nodes:
            begin, finish = int(network.adjacency_offsets[node]), int(network.adjacency_offsets[node + 1])
            for edge_value in network.adjacency_edges[begin:finish]:
                edge = int(edge_value)
                u, v = int(network.edge_u[edge]), int(network.edge_v[edge])
                neighbor = v if u == node else u
                if neighbor not in blocked_nodes:
                    portals.add(neighbor)
    pairs = _portal_pairs(network, portals, float(network.node_x[center]), float(network.node_y[center]))
    impacts: list[tuple[float, float, float]] = []
    disconnected = False
    tested = 0
    for start, end in pairs[:config.maximum_portal_pairs]:
        baseline = network.shortest_path(start, end, maximum_distance_m=config.maximum_route_m)
        if baseline is None:
            continue
        tested += 1
        alternative = network.shortest_path(
            start,
            end,
            blocked_nodes=blocked_nodes,
            blocked_edges=blocked_edges,
            maximum_distance_m=config.maximum_route_m,
        )
        if alternative is None:
            disconnected = True
            continue
        added = max(0.0, alternative[0] - baseline[0])
        impacts.append((alternative[0], added, alternative[0] / max(1.0, baseline[0])))
    worst = max(impacts, key=lambda item: item[1], default=None)
    score = 100.0 if disconnected else _detour_score(worst[1] if worst else 0.0)
    return {
        "network_analysis_complete": tested > 0,
        "network_portal_pair_count": tested,
        "network_disconnected_if_lost": disconnected,
        "network_alternative_route_found": False if disconnected else bool(worst),
        "network_detour_distance_m": worst[0] if worst else None,
        "network_detour_added_m": worst[1] if worst else None,
        "network_detour_ratio": worst[2] if worst else None,
        "network_criticality_score": score,
        "network_analysis_radius_m": radius_m,
        "network_analysis_limit_m": config.maximum_route_m,
    }


def _portal_pairs(
    network: RailwayRoutingNetwork,
    portals: set[int],
    center_x: float,
    center_y: float,
) -> list[tuple[int, int]]:
    values = sorted(portals)
    pairs: list[tuple[float, int, int]] = []
    for index, start in enumerate(values):
        start_angle = math.atan2(float(network.node_y[start]) - center_y, float(network.node_x[start]) - center_x)
        for end in values[index + 1:]:
            end_angle = math.atan2(float(network.node_y[end]) - center_y, float(network.node_x[end]) - center_x)
            separation = abs((start_angle - end_angle + math.pi) % (2 * math.pi) - math.pi)
            pairs.append((separation, start, end))
    pairs.sort(reverse=True)
    return [(start, end) for _, start, end in pairs]


def _node(
    lookup: dict[tuple[float, float], int],
    longitudes: list[float],
    latitudes: list[float],
    coordinate: Iterable[float],
) -> int:
    values = tuple(coordinate)
    key = round(float(values[0]), 7), round(float(values[1]), 7)
    node = lookup.get(key)
    if node is None:
        node = len(longitudes)
        lookup[key] = node
        longitudes.append(key[0])
        latitudes.append(key[1])
    return node


def _geometry_lines(geometry: Mapping[str, Any]) -> list[list[list[float]]]:
    if geometry.get("type") == "LineString":
        return [geometry.get("coordinates") or []]
    if geometry.get("type") == "MultiLineString":
        return list(geometry.get("coordinates") or [])
    return []


def _haversine_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(value)))


def _detour_score(added_m: float) -> float:
    anchors = ((0.0, 0.0), (2_000.0, 30.0), (10_000.0, 60.0), (30_000.0, 85.0), (60_000.0, 100.0))
    for (lower, lower_score), (upper, upper_score) in zip(anchors, anchors[1:]):
        if added_m <= upper:
            ratio = (added_m - lower) / (upper - lower)
            return lower_score + ratio * (upper_score - lower_score)
    return 100.0
