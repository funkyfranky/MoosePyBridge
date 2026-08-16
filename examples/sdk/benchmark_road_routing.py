"""Compare local Python routing with native DCS road pathfinding latency."""

from __future__ import annotations

import asyncio
import statistics
from time import perf_counter

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    GroundMobilityNetwork,
    HierarchicalRoadRouter,
    RoadRoutingShardIndex,
    TRACKED_ROAD_PROFILE,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH
_, THEATER_PATHS = load_example_theater(THEATER_PROFILE)
STRATEGIC_NETWORK_PATH = THEATER_PATHS.path("ground_mobility")
ROAD_SHARD_INDEX_PATH = THEATER_PATHS.path("road_routing_cache") / "manifest.json"
ROAD_CORRIDOR_BUFFER_M = 50_000.0
START_OBJECT_ID = "AIRBASE:Laage"
END_OBJECT_ID = "AIRBASE:Gross Mohrdorf"
RUNS = 5


def _metrics(values: list[float]) -> str:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return f"median={statistics.median(values):.2f}ms p95={p95:.2f}ms min={min(values):.2f}ms max={max(values):.2f}ms"


async def run() -> int:
    missing = tuple(path for path in (STRATEGIC_NETWORK_PATH, ROAD_SHARD_INDEX_PATH) if not path.is_file())
    if missing:
        print(f"Python routing artifact not found: {missing[0]}")
        print("Run: python tools/build_road_routing.py")
        return 4
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, 60.0)
    bridge = session.bridge
    start = await bridge.coords(START_OBJECT_ID, format="ll")
    end = await bridge.coords(END_OBJECT_ID, format="ll")
    coordinates = (start.latitude, start.longitude, end.latitude, end.longitude)
    if any(value is None for value in coordinates):
        print("DCS did not return both route coordinates.")
        return 5

    load_started = perf_counter()
    strategic_network = GroundMobilityNetwork.load(STRATEGIC_NETWORK_PATH)
    router = HierarchicalRoadRouter(
        strategic_network,
        RoadRoutingShardIndex.load(ROAD_SHARD_INDEX_PATH),
        corridor_buffer_m=ROAD_CORRIDOR_BUFFER_M,
    )
    load_ms = (perf_counter() - load_started) * 1_000
    cold_started = perf_counter()
    hierarchical_route = router.route(*coordinates, road_profile=TRACKED_ROAD_PROFILE)  # type: ignore[arg-type]
    cold_ms = (perf_counter() - cold_started) * 1_000
    if hierarchical_route is None:
        print("Python found no connected road route.")
        return 6
    python_route = hierarchical_route.detailed_route
    python_ms: list[float] = []
    for _ in range(RUNS):
        started = perf_counter()
        hierarchical_route = router.route(*coordinates, road_profile=TRACKED_ROAD_PROFILE)  # type: ignore[arg-type]
        python_ms.append((perf_counter() - started) * 1_000)
    assert hierarchical_route is not None
    python_route = hierarchical_route.detailed_route

    roundtrip_ms: list[float] = []
    dcs_path_ms: list[float] = []
    dcs_total_ms: list[float] = []
    dcs_route = None
    for _ in range(RUNS):
        started = perf_counter()
        dcs_route = await bridge.road_route(
            START_OBJECT_ID, END_OBJECT_ID, sample_spacing_m=5_000, max_points=20, timeout=60,
        )
        roundtrip_ms.append((perf_counter() - started) * 1_000)
        if dcs_route.pathfinding_cpu_ms is not None:
            dcs_path_ms.append(dcs_route.pathfinding_cpu_ms)
        if dcs_route.total_cpu_ms is not None:
            dcs_total_ms.append(dcs_route.total_cpu_ms)

    print("Road-routing benchmark")
    print("=" * 88)
    print(f"Route        : {START_OBJECT_ID} -> {END_OBJECT_ID}")
    print(f"Runs         : {RUNS}")
    print(f"Index load   : {load_ms:.2f}ms")
    print(
        f"Corridor graph: {hierarchical_route.detailed_node_count} nodes, "
        f"{hierarchical_route.detailed_edge_count} edges, buffer={ROAD_CORRIDOR_BUFFER_M / 1000:.0f}km"
    )
    print(f"Python cold  : {cold_ms:.2f}ms (includes corridor graph assembly)")
    print(f"Python warm  : {_metrics(python_ms)}")
    print(f"Python route : {python_route.distance_m / 1000:.1f}km, {python_route.edge_count} edges")
    print(f"DCS roundtrip: {_metrics(roundtrip_ms)}")
    if dcs_path_ms:
        print(f"DCS path CPU : {_metrics(dcs_path_ms)}")
        print(f"DCS total CPU: {_metrics(dcs_total_ms)}")
    else:
        print("DCS CPU      : unavailable; reload the current MooseBridge.lua and restart the mission")
    if dcs_route is not None:
        print(f"DCS route    : {dcs_route.distance_m / 1000:.1f}km, {dcs_route.raw_point_count} raw points")
        difference = python_route.distance_m - dcs_route.distance_m
        percentage = abs(difference) / dcs_route.distance_m * 100 if dcs_route.distance_m else 0.0
        speedup = statistics.median(dcs_path_ms) / statistics.median(python_ms) if dcs_path_ms else None
        print(f"Distance diff: {difference / 1000:+.1f}km ({percentage:.1f}%)")
        if speedup is not None:
            print(f"CPU speedup  : Python warm is about {speedup:.1f}x faster than native DCS pathfinding")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
