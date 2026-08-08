"""Compare local Python routing with native DCS road pathfinding latency."""

from __future__ import annotations

import asyncio
from pathlib import Path
import statistics
import sys
from time import perf_counter


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import RoadRoutingNetwork, TRACKED_ROAD_PROFILE
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
NETWORK_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-road-routing-mv.npz"
START_OBJECT_ID = "AIRBASE:Laage"
END_OBJECT_ID = "AIRBASE:Gross Mohrdorf"
RUNS = 5


def _metrics(values: list[float]) -> str:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return f"median={statistics.median(values):.2f}ms p95={p95:.2f}ms min={min(values):.2f}ms max={max(values):.2f}ms"


async def run() -> int:
    if not NETWORK_PATH.is_file():
        print(f"Python road graph not found: {NETWORK_PATH}")
        print("Run: python tools/build_road_routing.py")
        return 4
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=10)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3
    bridge = sdk_from_control_client(control, timeout=60)
    start = await bridge.coords(START_OBJECT_ID, format="ll")
    end = await bridge.coords(END_OBJECT_ID, format="ll")
    coordinates = (start.latitude, start.longitude, end.latitude, end.longitude)
    if any(value is None for value in coordinates):
        print("DCS did not return both route coordinates.")
        return 5

    load_started = perf_counter()
    network = RoadRoutingNetwork.load(NETWORK_PATH)
    load_ms = (perf_counter() - load_started) * 1_000
    cold_started = perf_counter()
    python_route = network.route(*coordinates, profile=TRACKED_ROAD_PROFILE)  # type: ignore[arg-type]
    cold_ms = (perf_counter() - cold_started) * 1_000
    if python_route is None:
        print("Python found no connected road route.")
        return 6
    python_ms: list[float] = []
    for _ in range(RUNS):
        started = perf_counter()
        python_route = network.route(*coordinates, profile=TRACKED_ROAD_PROFILE)  # type: ignore[arg-type]
        python_ms.append((perf_counter() - started) * 1_000)

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
    print(f"Graph load   : {load_ms:.2f}ms ({network.node_count} nodes, {network.edge_count} edges)")
    print(f"Python cold  : {cold_ms:.2f}ms (includes spatial-index construction)")
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
    raise SystemExit(asyncio.run(run()))
