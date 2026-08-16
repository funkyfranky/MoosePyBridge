"""Validate representative local and cross-region routes on the full theater graph."""

from __future__ import annotations

from pathlib import Path
import sys
from time import perf_counter


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import RoadRoutingNetwork, TRACKED_ROAD_PROFILE, format_python_road_route


NETWORK_PATH = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "runtime" / "road-routing.npz"
ROUTES = (
    ("Laage - Gross Mohrdorf", (53.9182, 12.2783), (54.3600, 12.9000)),
    ("Hamburg - Berlin", (53.5511, 9.9937), (52.5200, 13.4050)),
    ("Frankfurt - Berlin", (50.1109, 8.6821), (52.5200, 13.4050)),
    ("Amsterdam - Berlin", (52.3676, 4.9041), (52.5200, 13.4050)),
)


def main() -> int:
    if not NETWORK_PATH.is_file():
        print(f"Full road graph not found: {NETWORK_PATH}")
        print("Run: python tools/build_road_routing.py")
        return 4
    started = perf_counter()
    network = RoadRoutingNetwork.load(NETWORK_PATH)
    print("Full-theater road routing")
    print("=" * 100)
    print(
        f"Graph: {network.node_count} nodes, {network.edge_count} edges, "
        f"loaded in {(perf_counter() - started):.2f}s"
    )
    failures = 0
    for name, start, end in ROUTES:
        route_started = perf_counter()
        route = network.route(*start, *end, profile=TRACKED_ROAD_PROFILE)
        elapsed = perf_counter() - route_started
        print(f"{name}: {elapsed:.2f}s")
        print(f"  {format_python_road_route(route)}")
        failures += route is None
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
