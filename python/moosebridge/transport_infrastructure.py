"""Strategic bridges and transport junctions derived from the OSM road graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .road_routing import RoadRoutingNetwork


TRANSPORT_INFRASTRUCTURE_SCHEMA = "moosebridge.transport_infrastructure"
TRANSPORT_INFRASTRUCTURE_SCHEMA_VERSION = 1

DEFAULT_STRATEGIC_HIGHWAYS = (
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link",
)
DEFAULT_INTERCHANGE_CLUSTER_RADIUS_M = 300.0
DEFAULT_JUNCTION_CLUSTER_RADIUS_M = 100.0
DEFAULT_BRIDGE_CLUSTER_RADIUS_M = 150.0


class TransportJunctionKind(StrEnum):
    """Operationally useful classification of a road junction."""

    INTERCHANGE = "interchange"
    MAJOR_JUNCTION = "major_junction"
    JUNCTION = "junction"


class TransportImportanceTier(StrEnum):
    """Coarse strategic importance derived from road hierarchy and route impact."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True, frozen=True)
class TransportBridge:
    """One abstract bridge location containing one or more OSM bridge structures."""

    bridge_id: str
    geometry: dict[str, Any]
    latitude: float
    longitude: float
    length_m: float
    highway_classes: tuple[str, ...]
    edge_count: int
    approach_count: int
    endpoint_osm_ids: tuple[int, ...]
    member_bridge_ids: tuple[str, ...] = ()
    road_importance: float = 0.0
    detour_distance_m: float | None = None
    detour_added_m: float | None = None
    detour_ratio: float | None = None
    alternative_route_found: bool | None = None
    analysis_limit_m: float | None = None
    importance_score: float = 0.0
    importance_tier: TransportImportanceTier = TransportImportanceTier.LOW
    source: str = "OpenStreetMap bridge tags"

    def __post_init__(self) -> None:
        if not self.bridge_id.strip() or not self.source.strip():
            raise ValueError("transport bridge requires bridge_id and source")
        if self.geometry.get("type") != "Point":
            raise ValueError("transport bridge geometry must be Point")
        if self.length_m <= 0 or self.edge_count <= 0:
            raise ValueError("transport bridge length and edge_count must be positive")
        if not 0 <= self.road_importance <= 100 or not 0 <= self.importance_score <= 100:
            raise ValueError("transport bridge importance values must be between zero and 100")

    @property
    def member_count(self) -> int:
        return len(self.member_bridge_ids) or 1

    def to_geojson_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {
                "layer": "transport_bridges",
                "object_id": self.bridge_id,
                "name": self.bridge_id,
                "object_type": "TRANSPORT_BRIDGE",
                "category": "bridge",
                "latitude": self.latitude,
                "longitude": self.longitude,
                "length_m": self.length_m,
                "highway_classes": list(self.highway_classes),
                "edge_count": self.edge_count,
                "approach_count": self.approach_count,
                "endpoint_osm_ids": list(self.endpoint_osm_ids),
                "member_count": self.member_count,
                "member_bridge_ids": list(self.member_bridge_ids or (self.bridge_id,)),
                "road_importance": self.road_importance,
                "detour_distance_m": self.detour_distance_m,
                "detour_added_m": self.detour_added_m,
                "detour_ratio": self.detour_ratio,
                "alternative_route_found": self.alternative_route_found,
                "analysis_limit_m": self.analysis_limit_m,
                "importance_score": self.importance_score,
                "importance_tier": self.importance_tier.value,
                "source": self.source,
                "coordinate_system": "WGS84",
            },
        }

    @classmethod
    def from_geojson_feature(cls, feature: dict[str, Any]) -> "TransportBridge":
        properties = dict(feature.get("properties") or {})
        return cls(
            bridge_id=str(properties.get("object_id") or ""),
            geometry=dict(feature.get("geometry") or {}),
            latitude=float(properties.get("latitude") or 0),
            longitude=float(properties.get("longitude") or 0),
            length_m=float(properties.get("length_m") or 0),
            highway_classes=tuple(str(value) for value in properties.get("highway_classes") or ()),
            edge_count=int(properties.get("edge_count") or 0),
            approach_count=int(properties.get("approach_count") or 0),
            endpoint_osm_ids=tuple(int(value) for value in properties.get("endpoint_osm_ids") or ()),
            member_bridge_ids=tuple(str(value) for value in properties.get("member_bridge_ids") or ()),
            road_importance=float(properties.get("road_importance") or 0),
            detour_distance_m=_optional_float(properties.get("detour_distance_m")),
            detour_added_m=_optional_float(properties.get("detour_added_m")),
            detour_ratio=_optional_float(properties.get("detour_ratio")),
            alternative_route_found=_optional_bool(properties.get("alternative_route_found")),
            analysis_limit_m=_optional_float(properties.get("analysis_limit_m")),
            importance_score=float(properties.get("importance_score") or 0),
            importance_tier=TransportImportanceTier(str(properties.get("importance_tier") or "low")),
            source=str(properties.get("source") or ""),
        )


@dataclass(slots=True, frozen=True)
class TransportJunction:
    """One strategic road-network node with three or more relevant arms."""

    junction_id: str
    kind: TransportJunctionKind
    latitude: float
    longitude: float
    osm_node_id: int
    arm_count: int
    highway_classes: tuple[str, ...]
    bridge_adjacent: bool
    member_osm_ids: tuple[int, ...] = ()
    road_importance: float = 0.0
    detour_distance_m: float | None = None
    detour_added_m: float | None = None
    detour_ratio: float | None = None
    alternative_route_found: bool | None = None
    analysis_limit_m: float | None = None
    importance_score: float = 0.0
    importance_tier: TransportImportanceTier = TransportImportanceTier.LOW
    source: str = "OpenStreetMap road topology"

    def __post_init__(self) -> None:
        if not self.junction_id.strip() or not self.source.strip():
            raise ValueError("transport junction requires junction_id and source")
        if self.arm_count < 3:
            raise ValueError("transport junction requires at least three road arms")
        if self.member_osm_ids and self.osm_node_id not in self.member_osm_ids:
            raise ValueError("representative OSM node must be a junction member")
        if not 0 <= self.road_importance <= 100 or not 0 <= self.importance_score <= 100:
            raise ValueError("transport junction importance values must be between zero and 100")

    @property
    def member_count(self) -> int:
        return len(self.member_osm_ids) or 1

    def to_geojson_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
            "properties": {
                "layer": "transport_junctions",
                "object_id": self.junction_id,
                "name": self.junction_id,
                "object_type": "TRANSPORT_JUNCTION",
                "category": self.kind.value,
                "junction_kind": self.kind.value,
                "osm_node_id": self.osm_node_id,
                "arm_count": self.arm_count,
                "highway_classes": list(self.highway_classes),
                "bridge_adjacent": self.bridge_adjacent,
                "member_count": self.member_count,
                "member_osm_ids": list(self.member_osm_ids or (self.osm_node_id,)),
                "road_importance": self.road_importance,
                "detour_distance_m": self.detour_distance_m,
                "detour_added_m": self.detour_added_m,
                "detour_ratio": self.detour_ratio,
                "alternative_route_found": self.alternative_route_found,
                "analysis_limit_m": self.analysis_limit_m,
                "importance_score": self.importance_score,
                "importance_tier": self.importance_tier.value,
                "source": self.source,
                "coordinate_system": "WGS84",
            },
        }

    @classmethod
    def from_geojson_feature(cls, feature: dict[str, Any]) -> "TransportJunction":
        properties = dict(feature.get("properties") or {})
        coordinates = (feature.get("geometry") or {}).get("coordinates") or (0, 0)
        return cls(
            junction_id=str(properties.get("object_id") or ""),
            kind=TransportJunctionKind(str(properties.get("junction_kind") or "")),
            latitude=float(coordinates[1]),
            longitude=float(coordinates[0]),
            osm_node_id=int(properties.get("osm_node_id") or 0),
            arm_count=int(properties.get("arm_count") or 0),
            highway_classes=tuple(str(value) for value in properties.get("highway_classes") or ()),
            bridge_adjacent=bool(properties.get("bridge_adjacent")),
            member_osm_ids=tuple(
                int(value) for value in properties.get("member_osm_ids") or (properties.get("osm_node_id"),)
            ),
            road_importance=float(properties.get("road_importance") or 0),
            detour_distance_m=_optional_float(properties.get("detour_distance_m")),
            detour_added_m=_optional_float(properties.get("detour_added_m")),
            detour_ratio=_optional_float(properties.get("detour_ratio")),
            alternative_route_found=_optional_bool(properties.get("alternative_route_found")),
            analysis_limit_m=_optional_float(properties.get("analysis_limit_m")),
            importance_score=float(properties.get("importance_score") or 0),
            importance_tier=TransportImportanceTier(str(properties.get("importance_tier") or "low")),
            source=str(properties.get("source") or ""),
        )


@dataclass(slots=True, frozen=True)
class TheaterTransportInfrastructure:
    """Versioned strategic transport infrastructure for one DCS theater."""

    theater_id: str
    bridges: tuple[TransportBridge, ...]
    junctions: tuple[TransportJunction, ...]
    strategic_highways: tuple[str, ...] = DEFAULT_STRATEGIC_HIGHWAYS
    minimum_junction_arms: int = 3
    schema_version: int = TRANSPORT_INFRASTRUCTURE_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.theater_id.strip() or self.schema_version != TRANSPORT_INFRASTRUCTURE_SCHEMA_VERSION:
            raise ValueError("invalid theater transport-infrastructure collection")
        if self.minimum_junction_arms < 3:
            raise ValueError("minimum_junction_arms must be at least three")
        ids = [item.bridge_id for item in self.bridges] + [item.junction_id for item in self.junctions]
        if len(ids) != len(set(ids)):
            raise ValueError("transport infrastructure IDs must be unique")

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [
                *(bridge.to_geojson_feature() for bridge in self.bridges),
                *(junction.to_geojson_feature() for junction in self.junctions),
            ],
            "properties": {
                "schema": TRANSPORT_INFRASTRUCTURE_SCHEMA,
                "schema_version": self.schema_version,
                "theater_id": self.theater_id,
                "bridge_count": len(self.bridges),
                "junction_count": len(self.junctions),
                "strategic_highways": list(self.strategic_highways),
                "minimum_junction_arms": self.minimum_junction_arms,
                **self.metadata,
            },
        }

    @classmethod
    def from_geojson(cls, payload: dict[str, Any]) -> "TheaterTransportInfrastructure":
        properties = dict(payload.get("properties") or {})
        if payload.get("type") != "FeatureCollection" or properties.get("schema") != TRANSPORT_INFRASTRUCTURE_SCHEMA:
            raise ValueError("not a MooseBridge transport-infrastructure cache")
        bridges: list[TransportBridge] = []
        junctions: list[TransportJunction] = []
        for feature in payload.get("features") or ():
            object_type = str((feature.get("properties") or {}).get("object_type") or "")
            if object_type == "TRANSPORT_BRIDGE":
                bridges.append(TransportBridge.from_geojson_feature(feature))
            elif object_type == "TRANSPORT_JUNCTION":
                junctions.append(TransportJunction.from_geojson_feature(feature))
        known = {
            "schema", "schema_version", "theater_id", "bridge_count", "junction_count",
            "strategic_highways", "minimum_junction_arms",
        }
        return cls(
            theater_id=str(properties.get("theater_id") or ""),
            bridges=tuple(bridges),
            junctions=tuple(junctions),
            strategic_highways=tuple(str(value) for value in properties.get("strategic_highways") or ()),
            minimum_junction_arms=int(properties.get("minimum_junction_arms") or 3),
            schema_version=int(properties.get("schema_version") or 1),
            metadata={key: value for key, value in properties.items() if key not in known},
        )

    @classmethod
    def load(cls, path: str | Path) -> "TheaterTransportInfrastructure":
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


def build_transport_infrastructure(
    network: RoadRoutingNetwork,
    *,
    strategic_highways: Iterable[str] = DEFAULT_STRATEGIC_HIGHWAYS,
    minimum_junction_arms: int = 3,
    interchange_cluster_radius_m: float = DEFAULT_INTERCHANGE_CLUSTER_RADIUS_M,
    junction_cluster_radius_m: float = DEFAULT_JUNCTION_CLUSTER_RADIUS_M,
    bridge_cluster_radius_m: float = DEFAULT_BRIDGE_CLUSTER_RADIUS_M,
) -> TheaterTransportInfrastructure:
    """Extract connected bridges and relevant junctions from a road graph."""

    highway_filter = tuple(dict.fromkeys(str(value) for value in strategic_highways))
    if minimum_junction_arms < 3:
        raise ValueError("minimum_junction_arms must be at least three")
    if interchange_cluster_radius_m < 0 or junction_cluster_radius_m < 0 or bridge_cluster_radius_m < 0:
        raise ValueError("infrastructure cluster radii must not be negative")
    bridges = _extract_bridges(network, cluster_radius_m=bridge_cluster_radius_m)
    junctions = _extract_junctions(
        network,
        strategic_highways=frozenset(highway_filter),
        minimum_arms=minimum_junction_arms,
        interchange_cluster_radius_m=interchange_cluster_radius_m,
        junction_cluster_radius_m=junction_cluster_radius_m,
    )
    return TheaterTransportInfrastructure(
        theater_id=network.theater_id,
        bridges=bridges,
        junctions=junctions,
        strategic_highways=highway_filter,
        minimum_junction_arms=minimum_junction_arms,
        metadata={
            "method": "connected_osm_bridges_and_strategic_node_degree",
            "road_network_nodes": network.node_count,
            "road_network_edges": network.edge_count,
            "interchange_cluster_radius_m": interchange_cluster_radius_m,
            "junction_cluster_radius_m": junction_cluster_radius_m,
            "bridge_cluster_radius_m": bridge_cluster_radius_m,
        },
    )


@dataclass(slots=True, frozen=True)
class _BridgeCandidate:
    x: float
    y: float
    bridge: TransportBridge


def _extract_bridges(
    network: RoadRoutingNetwork,
    *,
    cluster_radius_m: float,
) -> tuple[TransportBridge, ...]:
    bridge_edges = np.flatnonzero(network.edge_bridge)
    if not len(bridge_edges):
        return ()
    node_to_edges: dict[int, list[int]] = {}
    for edge_index in bridge_edges:
        for node in (int(network.edge_u[edge_index]), int(network.edge_v[edge_index])):
            node_to_edges.setdefault(node, []).append(int(edge_index))
    unseen = set(int(value) for value in bridge_edges)
    components: list[tuple[int, ...]] = []
    while unseen:
        seed = unseen.pop()
        component = {seed}
        stack = [seed]
        while stack:
            edge_index = stack.pop()
            for node in (int(network.edge_u[edge_index]), int(network.edge_v[edge_index])):
                for neighbor in node_to_edges[node]:
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        component.add(neighbor)
                        stack.append(neighbor)
        components.append(tuple(sorted(component)))
    candidates = [_bridge_from_component(network, component) for component in components]
    return _cluster_bridges(candidates, radius_m=cluster_radius_m)


def _bridge_from_component(network: RoadRoutingNetwork, edges: tuple[int, ...]) -> _BridgeCandidate:
    local_degree: dict[int, int] = {}
    lines: list[list[list[float]]] = []
    highway_classes: set[str] = set()
    for edge_index in edges:
        u, v = int(network.edge_u[edge_index]), int(network.edge_v[edge_index])
        local_degree[u] = local_degree.get(u, 0) + 1
        local_degree[v] = local_degree.get(v, 0) + 1
        highway_classes.add(network.highway_classes[int(network.edge_highway_codes[edge_index])])
        start, finish = int(network.geometry_offsets[edge_index]), int(network.geometry_offsets[edge_index + 1])
        lines.append([
            [float(lon), float(lat)]
            for lon, lat in zip(
                network.geometry_longitudes[start:finish], network.geometry_latitudes[start:finish],
            )
        ])
    component_nodes = set(local_degree)
    endpoints = {
        node for node, degree in local_degree.items()
        if degree != 2 or _has_non_bridge_approach(network, node, set(edges))
    }
    if not endpoints:
        endpoints = component_nodes
    endpoint_ids = tuple(sorted(int(network.node_osm_ids[node]) for node in endpoints))
    identity_ids = endpoint_ids or tuple(sorted(int(network.node_osm_ids[node]) for node in component_nodes))
    digest = hashlib.sha1(",".join(str(value) for value in identity_ids).encode("ascii")).hexdigest()[:12]
    coordinates = [point for line in lines for point in line]
    approach_edges = {
        edge_index
        for node in component_nodes
        for edge_index in _incident_edges(network, node)
        if edge_index not in edges and not bool(network.edge_bridge[edge_index])
    }
    bridge_id = f"BRIDGE:{network.theater_id}:{digest}"
    bridge = TransportBridge(
        bridge_id=bridge_id,
        geometry={
            "type": "Point",
            "coordinates": [
                sum(point[0] for point in coordinates) / len(coordinates),
                sum(point[1] for point in coordinates) / len(coordinates),
            ],
        },
        latitude=sum(point[1] for point in coordinates) / len(coordinates),
        longitude=sum(point[0] for point in coordinates) / len(coordinates),
        length_m=sum(float(network.edge_lengths_m[index]) for index in edges),
        highway_classes=tuple(sorted(highway_classes)),
        edge_count=len(edges),
        approach_count=len(approach_edges),
        endpoint_osm_ids=endpoint_ids,
        member_bridge_ids=(bridge_id,),
    )
    return _BridgeCandidate(
        x=sum(float(network.node_x[node]) for node in component_nodes) / len(component_nodes),
        y=sum(float(network.node_y[node]) for node in component_nodes) / len(component_nodes),
        bridge=bridge,
    )


def _cluster_bridges(
    candidates: list[_BridgeCandidate],
    *,
    radius_m: float,
) -> tuple[TransportBridge, ...]:
    """Collapse nearby bridge structures into non-chained operational locations."""

    remaining = sorted(candidates, key=lambda item: (-item.bridge.edge_count, item.bridge.bridge_id))
    radius_squared = radius_m * radius_m
    result: list[TransportBridge] = []
    while remaining:
        seed = remaining.pop(0)
        members = [seed]
        keep: list[_BridgeCandidate] = []
        for candidate in remaining:
            distance_squared = (candidate.x - seed.x) ** 2 + (candidate.y - seed.y) ** 2
            if distance_squared <= radius_squared:
                members.append(candidate)
            else:
                keep.append(candidate)
        remaining = keep
        result.append(_bridge_from_members(members))
    return tuple(sorted(result, key=lambda item: item.bridge_id))


def _bridge_from_members(members: list[_BridgeCandidate]) -> TransportBridge:
    bridges = [member.bridge for member in members]
    raw_ids = tuple(sorted(bridge.bridge_id for bridge in bridges))
    if len(raw_ids) == 1:
        bridge_id = raw_ids[0]
    else:
        theater_id = raw_ids[0].split(":", 2)[1]
        digest = hashlib.sha1(",".join(raw_ids).encode("ascii")).hexdigest()[:12]
        bridge_id = f"BRIDGE:{theater_id}:COMPLEX:{digest}"
    latitude = sum(bridge.latitude for bridge in bridges) / len(bridges)
    longitude = sum(bridge.longitude for bridge in bridges) / len(bridges)
    return TransportBridge(
        bridge_id=bridge_id,
        geometry={"type": "Point", "coordinates": [longitude, latitude]},
        latitude=latitude,
        longitude=longitude,
        length_m=sum(bridge.length_m for bridge in bridges),
        highway_classes=tuple(sorted({
            highway for bridge in bridges for highway in bridge.highway_classes
        })),
        edge_count=sum(bridge.edge_count for bridge in bridges),
        approach_count=sum(bridge.approach_count for bridge in bridges),
        endpoint_osm_ids=tuple(sorted({
            osm_id for bridge in bridges for osm_id in bridge.endpoint_osm_ids
        })),
        member_bridge_ids=raw_ids,
    )


def _extract_junctions(
    network: RoadRoutingNetwork,
    *,
    strategic_highways: frozenset[str],
    minimum_arms: int,
    interchange_cluster_radius_m: float,
    junction_cluster_radius_m: float,
) -> tuple[TransportJunction, ...]:
    strategic_codes = np.asarray([
        index for index, name in enumerate(network.highway_classes) if name in strategic_highways
    ], dtype=np.int64)
    if not len(strategic_codes):
        return ()
    selected = np.isin(network.edge_highway_codes, strategic_codes)
    selected_indices = np.flatnonzero(selected)
    degree = np.bincount(
        np.concatenate((network.edge_u[selected_indices], network.edge_v[selected_indices])),
        minlength=network.node_count,
    )
    candidate_nodes = np.flatnonzero(degree >= minimum_arms)
    candidates: list[tuple[int, TransportJunction]] = []
    for node in candidate_nodes:
        incident = tuple(index for index in _incident_edges(network, int(node)) if selected[index])
        classes = tuple(sorted({
            network.highway_classes[int(network.edge_highway_codes[index])] for index in incident
        }))
        kind = _junction_kind(classes)
        osm_id = int(network.node_osm_ids[node])
        candidates.append((int(node), TransportJunction(
            junction_id=f"JUNCTION:OSM:{osm_id}",
            kind=kind,
            latitude=float(network.node_latitudes[node]),
            longitude=float(network.node_longitudes[node]),
            osm_node_id=osm_id,
            arm_count=len(incident),
            highway_classes=classes,
            bridge_adjacent=any(bool(network.edge_bridge[index]) for index in incident),
            member_osm_ids=(osm_id,),
        )))
    return _cluster_junctions(
        network,
        candidates,
        interchange_radius_m=interchange_cluster_radius_m,
        junction_radius_m=junction_cluster_radius_m,
    )


def _cluster_junctions(
    network: RoadRoutingNetwork,
    candidates: list[tuple[int, TransportJunction]],
    *,
    interchange_radius_m: float,
    junction_radius_m: float,
) -> tuple[TransportJunction, ...]:
    """Collapse nearby same-kind OSM nodes without transitive corridor chaining."""

    unassigned = {
        kind: sorted(
            ((node, junction) for node, junction in candidates if junction.kind is kind),
            key=lambda item: (-item[1].arm_count, item[1].osm_node_id),
        )
        for kind in TransportJunctionKind
    }
    result: list[TransportJunction] = []
    for kind, remaining in unassigned.items():
        radius = interchange_radius_m if kind is TransportJunctionKind.INTERCHANGE else junction_radius_m
        radius_squared = radius * radius
        while remaining:
            seed_node, seed = remaining.pop(0)
            seed_x, seed_y = float(network.node_x[seed_node]), float(network.node_y[seed_node])
            members = [(seed_node, seed)]
            keep: list[tuple[int, TransportJunction]] = []
            for node, junction in remaining:
                distance_squared = (
                    (float(network.node_x[node]) - seed_x) ** 2
                    + (float(network.node_y[node]) - seed_y) ** 2
                )
                if distance_squared <= radius_squared:
                    members.append((node, junction))
                else:
                    keep.append((node, junction))
            remaining = keep
            result.append(_junction_from_members(kind, members))
    return tuple(sorted(result, key=lambda item: item.junction_id))


def _junction_from_members(
    kind: TransportJunctionKind,
    members: list[tuple[int, TransportJunction]],
) -> TransportJunction:
    osm_ids = tuple(sorted(junction.osm_node_id for _, junction in members))
    if len(osm_ids) == 1:
        junction_id = f"JUNCTION:OSM:{osm_ids[0]}"
    else:
        digest = hashlib.sha1(",".join(str(value) for value in osm_ids).encode("ascii")).hexdigest()[:12]
        junction_id = f"JUNCTION:OSM-COMPLEX:{digest}"
    return TransportJunction(
        junction_id=junction_id,
        kind=kind,
        latitude=sum(junction.latitude for _, junction in members) / len(members),
        longitude=sum(junction.longitude for _, junction in members) / len(members),
        osm_node_id=osm_ids[0],
        arm_count=max(junction.arm_count for _, junction in members),
        highway_classes=tuple(sorted({
            highway for _, junction in members for highway in junction.highway_classes
        })),
        bridge_adjacent=any(junction.bridge_adjacent for _, junction in members),
        member_osm_ids=osm_ids,
    )


def _junction_kind(highway_classes: tuple[str, ...]) -> TransportJunctionKind:
    base_classes = {value.removesuffix("_link") for value in highway_classes}
    if base_classes & {"motorway", "trunk"}:
        return TransportJunctionKind.INTERCHANGE
    if "primary" in base_classes:
        return TransportJunctionKind.MAJOR_JUNCTION
    return TransportJunctionKind.JUNCTION


def _incident_edges(network: RoadRoutingNetwork, node: int) -> tuple[int, ...]:
    start, finish = int(network.adjacency_offsets[node]), int(network.adjacency_offsets[node + 1])
    return tuple(int(value) for value in network.adjacency_edges[start:finish])


def _has_non_bridge_approach(network: RoadRoutingNetwork, node: int, component: set[int]) -> bool:
    return any(
        edge_index not in component and not bool(network.edge_bridge[edge_index])
        for edge_index in _incident_edges(network, node)
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)
