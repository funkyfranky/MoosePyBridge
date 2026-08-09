"""Offline route-impact analysis for strategic transport infrastructure."""

from __future__ import annotations

from dataclasses import dataclass, replace
import heapq
import math
from typing import Any, Iterable

import numpy as np

from .road_routing import RoadRoutingNetwork
from .transport_infrastructure import (
    TheaterTransportInfrastructure,
    TransportBridge,
    TransportImportanceTier,
    TransportJunction,
    TransportJunctionKind,
)


ROAD_IMPORTANCE = {
    "motorway": 100.0,
    "trunk": 90.0,
    "primary": 75.0,
    "secondary": 55.0,
    "tertiary": 40.0,
}


@dataclass(slots=True, frozen=True)
class TransportCriticalityConfig:
    """Bounds for deterministic local route-impact analysis."""

    bridge_block_radius_m: float = 225.0
    interchange_block_radius_m: float = 350.0
    junction_block_radius_m: float = 150.0
    maximum_detour_m: float = 50_000.0
    maximum_portal_pairs: int = 3
    bridge_tier_thresholds: tuple[float, float, float] = (95.0, 82.0, 55.0)
    junction_tier_thresholds: tuple[float, float, float] = (95.0, 85.0, 65.0)

    def __post_init__(self) -> None:
        if min(
            self.bridge_block_radius_m,
            self.interchange_block_radius_m,
            self.junction_block_radius_m,
            self.maximum_detour_m,
        ) <= 0:
            raise ValueError("transport criticality distances must be positive")
        if self.maximum_portal_pairs <= 0:
            raise ValueError("maximum_portal_pairs must be positive")
        for thresholds in (self.bridge_tier_thresholds, self.junction_tier_thresholds):
            if len(thresholds) != 3 or not (100 >= thresholds[0] > thresholds[1] > thresholds[2] >= 0):
                raise ValueError("importance thresholds must be descending critical/high/medium values")


@dataclass(slots=True, frozen=True)
class _RouteImpact:
    road_importance: float
    detour_distance_m: float | None
    detour_added_m: float | None
    detour_ratio: float | None
    alternative_route_found: bool | None
    importance_score: float
    importance_tier: TransportImportanceTier


def analyze_transport_criticality(
    network: RoadRoutingNetwork,
    infrastructure: TheaterTransportInfrastructure,
    *,
    config: TransportCriticalityConfig = TransportCriticalityConfig(),
) -> TheaterTransportInfrastructure:
    """Assess route impact when each abstract bridge or junction is blocked."""

    try:
        from scipy.spatial import cKDTree
    except ImportError as exc:
        raise RuntimeError('transport criticality requires: python -m pip install -e ".[routing]"') from exc
    tree = cKDTree(np.column_stack((network.node_x, network.node_y)))
    strategic_codes = frozenset(
        index
        for index, highway in enumerate(network.highway_classes)
        if _road_importance((highway,)) >= ROAD_IMPORTANCE["secondary"]
    )
    bridges = tuple(
        _analyze_bridge(network, tree, strategic_codes, bridge, config)
        for bridge in infrastructure.bridges
    )
    junctions = tuple(
        _analyze_junction(network, tree, strategic_codes, junction, config)
        for junction in infrastructure.junctions
    )
    return replace(
        infrastructure,
        bridges=bridges,
        junctions=junctions,
        metadata={
            **infrastructure.metadata,
            "criticality_method": "bounded_location_block_and_alternative_route",
            "criticality_maximum_detour_m": config.maximum_detour_m,
            "criticality_maximum_portal_pairs": config.maximum_portal_pairs,
            "bridge_tier_thresholds": list(config.bridge_tier_thresholds),
            "junction_tier_thresholds": list(config.junction_tier_thresholds),
        },
    )


def reclassify_transport_importance(
    infrastructure: TheaterTransportInfrastructure,
    *,
    config: TransportCriticalityConfig = TransportCriticalityConfig(),
) -> TheaterTransportInfrastructure:
    """Apply type-specific display tiers to already calculated scores without rerouting."""

    return replace(
        infrastructure,
        bridges=tuple(
            replace(bridge, importance_tier=_tier(bridge.importance_score, config.bridge_tier_thresholds))
            for bridge in infrastructure.bridges
        ),
        junctions=tuple(
            replace(junction, importance_tier=_tier(junction.importance_score, config.junction_tier_thresholds))
            for junction in infrastructure.junctions
        ),
        metadata={
            **infrastructure.metadata,
            "bridge_tier_thresholds": list(config.bridge_tier_thresholds),
            "junction_tier_thresholds": list(config.junction_tier_thresholds),
        },
    )


def _analyze_bridge(
    network: RoadRoutingNetwork,
    tree: Any,
    strategic_codes: frozenset[int],
    bridge: TransportBridge,
    config: TransportCriticalityConfig,
) -> TransportBridge:
    impact = _analyze_location(
        network,
        tree,
        strategic_codes,
        longitude=bridge.longitude,
        latitude=bridge.latitude,
        road_classes=bridge.highway_classes,
        block_radius_m=config.bridge_block_radius_m,
        maximum_detour_m=config.maximum_detour_m,
        maximum_portal_pairs=config.maximum_portal_pairs,
        connectivity_score=min(100.0, bridge.approach_count * 15.0),
        detour_weight=0.45,
        road_weight=0.45,
        tier_thresholds=config.bridge_tier_thresholds,
    )
    return replace(
        bridge,
        road_importance=impact.road_importance,
        detour_distance_m=impact.detour_distance_m,
        detour_added_m=impact.detour_added_m,
        detour_ratio=impact.detour_ratio,
        alternative_route_found=impact.alternative_route_found,
        analysis_limit_m=config.maximum_detour_m,
        importance_score=impact.importance_score,
        importance_tier=impact.importance_tier,
    )


def _analyze_junction(
    network: RoadRoutingNetwork,
    tree: Any,
    strategic_codes: frozenset[int],
    junction: TransportJunction,
    config: TransportCriticalityConfig,
) -> TransportJunction:
    radius = (
        config.interchange_block_radius_m
        if junction.kind is TransportJunctionKind.INTERCHANGE else config.junction_block_radius_m
    )
    impact = _analyze_location(
        network,
        tree,
        strategic_codes,
        longitude=junction.longitude,
        latitude=junction.latitude,
        road_classes=junction.highway_classes,
        block_radius_m=radius,
        maximum_detour_m=config.maximum_detour_m,
        maximum_portal_pairs=config.maximum_portal_pairs,
        connectivity_score=min(100.0, junction.arm_count * 20.0),
        detour_weight=0.35,
        road_weight=0.45,
        tier_thresholds=config.junction_tier_thresholds,
    )
    return replace(
        junction,
        road_importance=impact.road_importance,
        detour_distance_m=impact.detour_distance_m,
        detour_added_m=impact.detour_added_m,
        detour_ratio=impact.detour_ratio,
        alternative_route_found=impact.alternative_route_found,
        analysis_limit_m=config.maximum_detour_m,
        importance_score=impact.importance_score,
        importance_tier=impact.importance_tier,
    )


def _analyze_location(
    network: RoadRoutingNetwork,
    tree: Any,
    strategic_codes: frozenset[int],
    *,
    longitude: float,
    latitude: float,
    road_classes: Iterable[str],
    block_radius_m: float,
    maximum_detour_m: float,
    maximum_portal_pairs: int,
    connectivity_score: float,
    detour_weight: float,
    road_weight: float,
    tier_thresholds: tuple[float, float, float],
) -> _RouteImpact:
    center_node, _ = network.nearest_node(latitude, longitude)
    center_x, center_y = float(network.node_x[center_node]), float(network.node_y[center_node])
    blocked_nodes = frozenset(int(value) for value in tree.query_ball_point((center_x, center_y), block_radius_m))
    portals: dict[int, float] = {}
    for node in blocked_nodes:
        begin, finish = int(network.adjacency_offsets[node]), int(network.adjacency_offsets[node + 1])
        for edge_value in network.adjacency_edges[begin:finish]:
            edge = int(edge_value)
            if int(network.edge_highway_codes[edge]) not in strategic_codes:
                continue
            u, v = int(network.edge_u[edge]), int(network.edge_v[edge])
            neighbor = v if u == node else u
            if neighbor in blocked_nodes:
                continue
            highway = network.highway_classes[int(network.edge_highway_codes[edge])]
            portals[neighbor] = max(portals.get(neighbor, 0.0), _road_importance((highway,)))
    selected_portals = _directional_portals(network, portals, center_x, center_y)
    pairs = _portal_pairs(network, selected_portals, center_x, center_y)[:maximum_portal_pairs]
    road_score = _road_importance(road_classes)
    if not pairs:
        score = road_weight * road_score + (1.0 - road_weight - detour_weight) * connectivity_score
        return _RouteImpact(road_score, None, None, None, None, score, _tier(score, tier_thresholds))

    impacts: list[tuple[float, float, float]] = []
    missing_alternative = False
    for start, end, baseline in pairs:
        alternative = _shortest_distance(
            network,
            start,
            end,
            blocked_nodes=blocked_nodes,
            maximum_distance_m=maximum_detour_m,
        )
        if alternative is None:
            missing_alternative = True
            continue
        added = max(0.0, alternative - baseline)
        impacts.append((alternative, added, alternative / max(1.0, baseline)))
    if missing_alternative:
        detour_score = 100.0
        alternative_found = False
        detour_distance = detour_added = detour_ratio = None
    elif impacts:
        detour_distance, detour_added, detour_ratio = max(impacts, key=lambda value: value[1])
        detour_score = _detour_score(detour_added)
        alternative_found = True
    else:
        detour_score = 0.0
        alternative_found = None
        detour_distance = detour_added = detour_ratio = None
    connectivity_weight = 1.0 - road_weight - detour_weight
    score = min(100.0, road_weight * road_score + detour_weight * detour_score + connectivity_weight * connectivity_score)
    return _RouteImpact(
        road_score,
        detour_distance,
        detour_added,
        detour_ratio,
        alternative_found,
        score,
        _tier(score, tier_thresholds),
    )


def _directional_portals(
    network: RoadRoutingNetwork,
    portals: dict[int, float],
    center_x: float,
    center_y: float,
) -> tuple[int, ...]:
    sectors: dict[int, tuple[float, float, int]] = {}
    for node, road_score in portals.items():
        dx = float(network.node_x[node]) - center_x
        dy = float(network.node_y[node]) - center_y
        angle = (math.atan2(dy, dx) + 2 * math.pi) % (2 * math.pi)
        sector = int(angle / (math.pi / 4)) % 8
        distance = math.hypot(dx, dy)
        candidate = (-road_score, distance, node)
        if sector not in sectors or candidate < sectors[sector]:
            sectors[sector] = candidate
    return tuple(value[2] for _, value in sorted(sectors.items()))


def _portal_pairs(
    network: RoadRoutingNetwork,
    portals: tuple[int, ...],
    center_x: float,
    center_y: float,
) -> list[tuple[int, int, float]]:
    pairs: list[tuple[float, int, int, float]] = []
    for index, start in enumerate(portals):
        start_angle = math.atan2(float(network.node_y[start]) - center_y, float(network.node_x[start]) - center_x)
        for end in portals[index + 1:]:
            end_angle = math.atan2(float(network.node_y[end]) - center_y, float(network.node_x[end]) - center_x)
            separation = abs((start_angle - end_angle + math.pi) % (2 * math.pi) - math.pi)
            if separation < 2 * math.pi / 3:
                continue
            baseline = math.hypot(
                float(network.node_x[start] - network.node_x[end]),
                float(network.node_y[start] - network.node_y[end]),
            )
            pairs.append((separation, start, end, baseline))
    pairs.sort(reverse=True)
    return [(start, end, baseline) for _, start, end, baseline in pairs]


def _shortest_distance(
    network: RoadRoutingNetwork,
    start: int,
    end: int,
    *,
    blocked_nodes: frozenset[int],
    maximum_distance_m: float,
) -> float | None:
    queue: list[tuple[float, float, int]] = [(0.0, 0.0, start)]
    costs = {start: 0.0}
    while queue:
        _, cost, node = heapq.heappop(queue)
        if cost != costs.get(node):
            continue
        if node == end:
            return cost
        if cost >= maximum_distance_m:
            continue
        begin, finish = int(network.adjacency_offsets[node]), int(network.adjacency_offsets[node + 1])
        for edge_value in network.adjacency_edges[begin:finish]:
            edge = int(edge_value)
            u, v = int(network.edge_u[edge]), int(network.edge_v[edge])
            neighbor = v if u == node else u
            if neighbor in blocked_nodes:
                continue
            candidate = cost + float(network.edge_lengths_m[edge])
            if candidate >= costs.get(neighbor, math.inf) or candidate > maximum_distance_m:
                continue
            costs[neighbor] = candidate
            heuristic = math.hypot(
                float(network.node_x[neighbor] - network.node_x[end]),
                float(network.node_y[neighbor] - network.node_y[end]),
            )
            heapq.heappush(queue, (candidate + heuristic, candidate, neighbor))
    return None


def _road_importance(highway_classes: Iterable[str]) -> float:
    return max(
        (ROAD_IMPORTANCE.get(str(value).removesuffix("_link"), 25.0) for value in highway_classes),
        default=25.0,
    )


def _detour_score(added_distance_m: float) -> float:
    anchors = ((0.0, 0.0), (1_000.0, 30.0), (5_000.0, 60.0), (15_000.0, 85.0), (30_000.0, 100.0))
    for (lower_distance, lower_score), (upper_distance, upper_score) in zip(anchors, anchors[1:]):
        if added_distance_m <= upper_distance:
            ratio = (added_distance_m - lower_distance) / (upper_distance - lower_distance)
            return lower_score + ratio * (upper_score - lower_score)
    return 100.0


def _tier(score: float, thresholds: tuple[float, float, float]) -> TransportImportanceTier:
    critical, high, medium = thresholds
    if score >= critical:
        return TransportImportanceTier.CRITICAL
    if score >= high:
        return TransportImportanceTier.HIGH
    if score >= medium:
        return TransportImportanceTier.MEDIUM
    return TransportImportanceTier.LOW
