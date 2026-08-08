"""Hierarchical road routing through strategic corridors and detailed OSM shards."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Iterable

import numpy as np

from .ground_mobility import GroundMobilityNetwork, GroundMobilityProfile, GroundRoute, TRACKED_GROUND_PROFILE
from .road_routing import PythonRoadRoute, RoadRoutingNetwork, RoadVehicleProfile, TRACKED_ROAD_PROFILE, merge_road_routing_artifacts


ROAD_ROUTING_SHARD_SCHEMA = "moosebridge.road_routing_shards"
ROAD_ROUTING_SHARD_SCHEMA_VERSION = 2


@dataclass(slots=True, frozen=True)
class RoadRoutingShard:
    """One independently loadable detailed road graph."""

    path: Path
    source_names: tuple[str, ...]
    bounds_xy: tuple[float, float, float, float]
    bounds_wgs84: tuple[float, float, float, float]
    node_count: int
    edge_count: int
    coverage_cells: frozenset[tuple[int, int]]


@dataclass(slots=True, frozen=True)
class RoadRoutingShardIndex:
    """Spatial catalog of detailed road-routing artifacts."""

    theater_id: str
    shards: tuple[RoadRoutingShard, ...]
    cell_size_m: float

    @classmethod
    def load(cls, path: str | Path) -> "RoadRoutingShardIndex":
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload.get("schema") != ROAD_ROUTING_SHARD_SCHEMA:
            raise ValueError("not a MooseBridge road-routing shard index")
        if int(payload.get("schema_version") or 0) != ROAD_ROUTING_SHARD_SCHEMA_VERSION:
            raise ValueError("unsupported road-routing shard-index version")
        shards = tuple(
            RoadRoutingShard(
                path=(source.parent / str(item["path"])).resolve(),
                source_names=tuple(str(value) for value in item.get("source_names") or ()),
                bounds_xy=tuple(float(value) for value in item["bounds_xy"]),  # type: ignore[arg-type]
                bounds_wgs84=tuple(float(value) for value in item["bounds_wgs84"]),  # type: ignore[arg-type]
                node_count=int(item["node_count"]),
                edge_count=int(item["edge_count"]),
                coverage_cells=frozenset(
                    (int(cell[0]), int(cell[1])) for cell in item.get("coverage_cells") or ()
                ),
            )
            for item in payload.get("shards") or ()
        )
        return cls(
            theater_id=str(payload.get("theater_id") or ""),
            shards=shards,
            cell_size_m=float(payload.get("cell_size_m") or 0),
        )

    def select(self, strategic: GroundRoute, network: GroundMobilityNetwork, *, buffer_m: float) -> tuple[RoadRoutingShard, ...]:
        """Select every shard intersecting the buffered strategic route."""

        cells = self.corridor_cells(strategic, network, buffer_m=buffer_m)
        return tuple(
            shard for shard in self.shards
            if not shard.coverage_cells.isdisjoint(cells)
        )

    def corridor_cells(
        self,
        strategic: GroundRoute,
        network: GroundMobilityNetwork,
        *,
        buffer_m: float,
    ) -> frozenset[tuple[int, int]]:
        """Rasterize one buffered strategic route into index cells."""

        if buffer_m <= 0:
            raise ValueError("corridor buffer must be positive")
        if self.cell_size_m <= 0:
            raise ValueError("road-routing shard index has no valid cell size")
        try:
            from shapely.geometry import LineString, Point, box
        except ImportError as exc:
            raise RuntimeError('hierarchical routing requires: python -m pip install -e ".[routing]"') from exc
        coordinates = [(network.nodes[node].x, network.nodes[node].y) for node in strategic.node_ids]
        axis = LineString(coordinates) if len(coordinates) > 1 else Point(coordinates[0])
        corridor = axis.buffer(buffer_m)
        min_x, min_y, max_x, max_y = corridor.bounds
        first_x = int(np.floor(min_x / self.cell_size_m))
        last_x = int(np.floor(max_x / self.cell_size_m))
        first_y = int(np.floor(min_y / self.cell_size_m))
        last_y = int(np.floor(max_y / self.cell_size_m))
        corridor_cells = frozenset({
            (column, row)
            for column in range(first_x, last_x + 1)
            for row in range(first_y, last_y + 1)
            if box(
                column * self.cell_size_m,
                row * self.cell_size_m,
                (column + 1) * self.cell_size_m,
                (row + 1) * self.cell_size_m,
            ).intersects(corridor)
        })
        return corridor_cells


@dataclass(slots=True, frozen=True)
class HierarchicalRoadRoute:
    """Strategic corridor and its exact detailed route."""

    strategic_route: GroundRoute
    detailed_route: PythonRoadRoute
    shard_sources: tuple[str, ...]
    detailed_node_count: int
    detailed_edge_count: int
    corridor_buffer_m: float
    strategic_time_ms: float
    graph_time_ms: float
    detailed_time_ms: float
    graph_cache_hit: bool


class HierarchicalRoadRouter:
    """Route through a bounded union of regional detailed road graphs."""

    def __init__(
        self,
        strategic_network: GroundMobilityNetwork,
        shard_index: RoadRoutingShardIndex,
        *,
        corridor_buffer_m: float = 75_000.0,
        graph_cache_size: int = 1,
    ) -> None:
        if strategic_network.theater_id != shard_index.theater_id:
            raise ValueError("strategic network and road shards belong to different theaters")
        if corridor_buffer_m <= 0 or graph_cache_size < 0:
            raise ValueError("invalid hierarchical routing configuration")
        self.strategic_network = strategic_network
        self.shard_index = shard_index
        self.corridor_buffer_m = float(corridor_buffer_m)
        self.graph_cache_size = graph_cache_size
        self._graphs: OrderedDict[tuple[str, ...], RoadRoutingNetwork] = OrderedDict()

    def route(
        self,
        start_latitude: float,
        start_longitude: float,
        end_latitude: float,
        end_longitude: float,
        *,
        strategic_profile: GroundMobilityProfile = TRACKED_GROUND_PROFILE,
        road_profile: RoadVehicleProfile = TRACKED_ROAD_PROFILE,
    ) -> HierarchicalRoadRoute | None:
        strategic_started = perf_counter()
        strategic = self.strategic_network.route(
            start_latitude, start_longitude, end_latitude, end_longitude,
            profile=strategic_profile,
        )
        strategic_ms = (perf_counter() - strategic_started) * 1_000
        if strategic is None:
            return None
        corridor_cells = self.shard_index.corridor_cells(
            strategic, self.strategic_network, buffer_m=self.corridor_buffer_m,
        )
        shards = tuple(
            shard for shard in self.shard_index.shards
            if not shard.coverage_cells.isdisjoint(corridor_cells)
        )
        if not shards:
            return None
        artifact_paths = tuple(sorted(str(shard.path) for shard in shards))
        cell_signature = hash(tuple(sorted(corridor_cells)))
        key = (*artifact_paths, f"#cells:{cell_signature}")
        graph_started = perf_counter()
        graph = self._graphs.pop(key, None)
        cache_hit = graph is not None
        if graph is None:
            graph = merge_road_routing_artifacts(
                artifact_paths,
                theater_id=self.strategic_network.theater_id,
                allowed_cells=corridor_cells,
                cell_size_m=self.shard_index.cell_size_m,
            )
        if self.graph_cache_size:
            self._graphs[key] = graph
            while len(self._graphs) > self.graph_cache_size:
                self._graphs.popitem(last=False)
        graph_ms = (perf_counter() - graph_started) * 1_000
        detailed_started = perf_counter()
        detailed = graph.route(
            start_latitude, start_longitude, end_latitude, end_longitude,
            profile=road_profile,
        )
        detailed_ms = (perf_counter() - detailed_started) * 1_000
        if detailed is None:
            return None
        return HierarchicalRoadRoute(
            strategic_route=strategic,
            detailed_route=detailed,
            shard_sources=tuple(
                source for shard in shards for source in shard.source_names
            ),
            detailed_node_count=graph.node_count,
            detailed_edge_count=graph.edge_count,
            corridor_buffer_m=self.corridor_buffer_m,
            strategic_time_ms=strategic_ms,
            graph_time_ms=graph_ms,
            detailed_time_ms=detailed_ms,
            graph_cache_hit=cache_hit,
        )


def build_road_routing_shard_index(
    artifacts: Iterable[str | Path],
    output: str | Path,
    *,
    theater_id: str,
    cell_size_m: float = 25_000.0,
) -> Path:
    """Build a small spatial index without loading full shard graphs."""

    if cell_size_m <= 0:
        raise ValueError("road-routing shard cell size must be positive")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for artifact in sorted(Path(path) for path in artifacts):
        with np.load(artifact, allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata"]))
            x = payload["node_x"]
            y = payload["node_y"]
            longitude = payload["node_longitudes"]
            latitude = payload["node_latitudes"]
            cells = np.unique(np.column_stack((
                np.floor(x / cell_size_m).astype(np.int32),
                np.floor(y / cell_size_m).astype(np.int32),
            )), axis=0)
            items.append({
                "path": os.path.relpath(artifact.resolve(), target.parent.resolve()),
                "source_names": list((metadata.get("metadata") or {}).get("source_names") or ()),
                "bounds_xy": [float(x.min()), float(y.min()), float(x.max()), float(y.max())],
                "bounds_wgs84": [
                    float(longitude.min()), float(latitude.min()),
                    float(longitude.max()), float(latitude.max()),
                ],
                "node_count": len(payload["node_osm_ids"]),
                "edge_count": len(payload["edge_u"]),
                "coverage_cells": cells.tolist(),
            })
    payload = {
        "schema": ROAD_ROUTING_SHARD_SCHEMA,
        "schema_version": ROAD_ROUTING_SHARD_SCHEMA_VERSION,
        "theater_id": theater_id,
        "cell_size_m": cell_size_m,
        "shards": items,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return target


def format_hierarchical_road_route(route: HierarchicalRoadRoute | None) -> str:
    if route is None:
        return "No hierarchical road route was found in the selected corridor."
    detailed = route.detailed_route
    return (
        f"Hierarchical road route distance={detailed.distance_m / 1000:.1f}km "
        f"eta={detailed.travel_time_s / 60:.0f}min shards={len(route.shard_sources)} "
        f"graph={route.detailed_node_count} nodes/{route.detailed_edge_count} edges "
        f"timing={route.strategic_time_ms:.0f}+{route.graph_time_ms:.0f}+{route.detailed_time_ms:.0f}ms "
        f"cache={'hit' if route.graph_cache_hit else 'miss'}"
    )
