"""Benchmark representative routes through strategic corridor shard selection."""

from __future__ import annotations

from pathlib import Path
import sys
from time import perf_counter


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import (
    GroundMobilityNetwork,
    HierarchicalRoadRouter,
    RoadRoutingShardIndex,
    format_hierarchical_road_route,
)


STRATEGIC_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-ground-mobility.json"
SHARD_INDEX_PATH = REPO_ROOT / "tmp" / "topography" / "road_routing_cache" / "manifest.json"
CORRIDOR_BUFFER_M = 50_000.0
ROUTES = (
    ("Laage - Gross Mohrdorf", (53.9182, 12.2783), (54.3600, 12.9000)),
    ("Hamburg - Berlin", (53.5511, 9.9937), (52.5200, 13.4050)),
    ("Frankfurt - Berlin", (50.1109, 8.6821), (52.5200, 13.4050)),
    ("Amsterdam - Berlin", (52.3676, 4.9041), (52.5200, 13.4050)),
)


def main() -> int:
    for path in (STRATEGIC_PATH, SHARD_INDEX_PATH):
        if not path.is_file():
            print(f"Required routing artifact not found: {path}")
            return 4
    strategic = GroundMobilityNetwork.load(STRATEGIC_PATH)
    shards = RoadRoutingShardIndex.load(SHARD_INDEX_PATH)
    router = HierarchicalRoadRouter(
        strategic,
        shards,
        corridor_buffer_m=CORRIDOR_BUFFER_M,
        graph_cache_size=1,
    )
    print("Hierarchical road routing")
    print("=" * 100)
    print(f"Strategic graph: {len(strategic.nodes)} nodes, {len(strategic.edges)} edges")
    print(f"Detailed shards: {len(shards.shards)}, corridor buffer: {CORRIDOR_BUFFER_M / 1000:.0f}km")
    failures = 0
    for name, start, end in ROUTES:
        started = perf_counter()
        cold = router.route(*start, *end)
        cold_elapsed = perf_counter() - started
        started = perf_counter()
        warm = router.route(*start, *end)
        warm_elapsed = perf_counter() - started
        print(f"{name}: cold={cold_elapsed:.2f}s warm={warm_elapsed:.2f}s")
        print(f"  {format_hierarchical_road_route(cold)}")
        failures += cold is None or warm is None
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
