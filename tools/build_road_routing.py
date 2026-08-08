"""Build the compact GermanyCW Python road-routing artifact from Geofabrik PBF."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import build_road_routing_network


DEFAULT_PBF = REPO_ROOT / "tmp" / "topography" / "pbf" / "mecklenburg-vorpommern-latest.osm.pbf"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "topography" / "GermanyCW-road-routing-mv.npz"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact unrestricted military road graph")
    parser.add_argument("--pbf", type=Path, action="append")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--theater", default="GermanyCW")
    args = parser.parse_args()
    paths = tuple(args.pbf or (DEFAULT_PBF,))
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(str(path) for path in missing))
    try:
        import pandas as pd
        from pyrosm import OSM
    except ImportError as exc:
        raise RuntimeError('road routing requires: python -m pip install -e ".[routing]"') from exc

    frames = []
    node_frames = []
    started = perf_counter()
    for path in paths:
        print(f"Reading driving network: {path}", flush=True)
        nodes, edges = OSM(str(path)).get_network(
            network_type="driving",
            nodes=True,
            extra_attributes=["bridge"],
        )
        node_frames.append(nodes)
        frames.append(edges)
    nodes = pd.concat(node_frames, ignore_index=True).drop_duplicates(subset="id")
    edges = pd.concat(frames, ignore_index=True)
    imported = perf_counter()
    network = build_road_routing_network(
        theater_id=args.theater,
        nodes=nodes,
        edges=edges,
        source_names=(path.name for path in paths),
    )
    compiled = perf_counter()
    output = network.save(args.output)
    saved = perf_counter()
    print(f"Wrote road-routing graph: {output}")
    print(f"  nodes: {network.node_count}")
    print(f"  edges: {network.edge_count} (undirected; oneway/access ignored)")
    print(f"  bridges: {int(network.edge_bridge.sum())} (metadata only)")
    print(f"  artifact: {output.stat().st_size / 1024 / 1024:.1f} MiB")
    print(f"  import/compile/save: {imported-started:.1f}s / {compiled-imported:.1f}s / {saved-compiled:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
