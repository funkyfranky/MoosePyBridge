"""Extract strategic bridges and road junctions from a road-routing artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import (  # noqa: E402
    DEFAULT_BRIDGE_CLUSTER_RADIUS_M,
    DEFAULT_INTERCHANGE_CLUSTER_RADIUS_M,
    DEFAULT_JUNCTION_CLUSTER_RADIUS_M,
    DEFAULT_STRATEGIC_HIGHWAYS,
    RoadRoutingNetwork,
    TransportCriticalityConfig,
    analyze_transport_criticality,
    build_transport_infrastructure,
)


DEFAULT_INPUT = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "runtime" / "road-routing.npz"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "runtime" / "transport-infrastructure.geojson"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build strategic bridge and road-junction GeoJSON")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--minimum-arms", type=int, default=3)
    parser.add_argument("--interchange-cluster-radius", type=float, default=DEFAULT_INTERCHANGE_CLUSTER_RADIUS_M)
    parser.add_argument("--junction-cluster-radius", type=float, default=DEFAULT_JUNCTION_CLUSTER_RADIUS_M)
    parser.add_argument("--bridge-cluster-radius", type=float, default=DEFAULT_BRIDGE_CLUSTER_RADIUS_M)
    parser.add_argument(
        "--analyze-criticality",
        action="store_true",
        help="Run bounded alternative-route analysis; intended for regional graphs or offline builds.",
    )
    parser.add_argument("--maximum-detour-km", type=float, default=50.0)
    parser.add_argument(
        "--highway",
        action="append",
        help="Included strategic OSM highway class; repeat as needed (defaults through secondary)",
    )
    args = parser.parse_args()
    started = perf_counter()
    network = RoadRoutingNetwork.load(args.input)
    loaded = perf_counter()
    infrastructure = build_transport_infrastructure(
        network,
        strategic_highways=tuple(args.highway or DEFAULT_STRATEGIC_HIGHWAYS),
        minimum_junction_arms=args.minimum_arms,
        interchange_cluster_radius_m=args.interchange_cluster_radius,
        junction_cluster_radius_m=args.junction_cluster_radius,
        bridge_cluster_radius_m=args.bridge_cluster_radius,
    )
    extracted = perf_counter()
    if args.analyze_criticality:
        infrastructure = analyze_transport_criticality(
            network,
            infrastructure,
            config=TransportCriticalityConfig(maximum_detour_m=args.maximum_detour_km * 1000),
        )
    built = perf_counter()
    output = infrastructure.save(args.output)
    saved = perf_counter()
    print(f"Transport infrastructure written: {output}")
    print(f"  bridges: {len(infrastructure.bridges)}")
    print(
        "  represented OSM bridge structures: "
        f"{sum(bridge.member_count for bridge in infrastructure.bridges)}"
    )
    print(f"  strategic junctions: {len(infrastructure.junctions)}")
    print(
        "  represented OSM junction nodes: "
        f"{sum(junction.member_count for junction in infrastructure.junctions)}"
    )
    print(f"  highway classes: {', '.join(infrastructure.strategic_highways)}")
    if args.analyze_criticality:
        tiers = {
            tier: sum(
                item.importance_tier.value == tier
                for item in (*infrastructure.bridges, *infrastructure.junctions)
            )
            for tier in ("critical", "high", "medium", "low")
        }
        print("  importance: " + ", ".join(f"{key}={value}" for key, value in tiers.items()))
    print(
        "  load/extract/analyze/save: "
        f"{loaded-started:.2f}s / {extracted-loaded:.2f}s / {built-extracted:.2f}s / {saved-built:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
