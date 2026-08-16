"""Build the compact GermanyCW Python road-routing artifact from Geofabrik PBF."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import build_road_routing_network, build_road_routing_shard_index, merge_road_routing_artifacts
from moosebridge.topography_coverage import TheaterTopographyCoverage, TopographyDetailLevel


DEFAULT_CONFIG = PYTHON_ROOT / "moosebridge" / "data" / "GermanyCW_topography.json"
DEFAULT_COVERAGE = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "verification" / "coverage.geojson"
DEFAULT_PBF_DIR = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "sources" / "pbf"
DEFAULT_CACHE_DIR = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "cache" / "road-routing"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "runtime" / "road-routing.npz"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact unrestricted military road graph")
    parser.add_argument("--pbf", type=Path, action="append")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--pbf-dir", type=Path, default=DEFAULT_PBF_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--theater", default="GermanyCW")
    parser.add_argument("--worker-pbf", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-empty", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_pbf is not None:
        if args.worker_output is None or args.worker_empty is None:
            raise ValueError("worker mode requires output and empty marker paths")
        return _build_partial(
            args.worker_pbf,
            args.worker_output,
            args.worker_empty,
            coverage_path=args.coverage,
            theater_id=args.theater,
        )
    paths = tuple(args.pbf or _configured_pbf_paths(args.config, args.pbf_dir))
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(str(path) for path in missing))
    coverage = TheaterTopographyCoverage.load(args.coverage)
    low_geometry = coverage.geometry_for_minimum_level(TopographyDetailLevel.LOW)
    high_geometry = coverage.geometry_for_minimum_level(TopographyDetailLevel.HIGH)
    if low_geometry is None:
        raise ValueError("road routing requires at least one Topography Low or High zone")
    digest = hashlib.sha256(b"detail-policy-v1")
    digest.update(low_geometry.wkb)
    if high_geometry is not None:
        digest.update(high_geometry.wkb)
    coverage_hash = digest.hexdigest()[:12]
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    partials: list[Path] = []
    for index, path in enumerate(paths, start=1):
        cache_path = args.cache_dir / f"{path.stem}-{coverage_hash}.npz"
        empty_path = args.cache_dir / f"{path.stem}-{coverage_hash}.empty"
        if cache_path.is_file() and not args.refresh_cache:
            print(f"Cache {index}/{len(paths)}: {cache_path.name}", flush=True)
            partials.append(cache_path)
            continue
        if empty_path.is_file() and not args.refresh_cache:
            print(f"Cache {index}/{len(paths)}: {empty_path.name} (no roads in coverage)", flush=True)
            continue
        print(f"Import {index}/{len(paths)}: {path.name}", flush=True)
        completed = subprocess.run(
            (
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker-pbf", str(path),
                "--worker-output", str(cache_path),
                "--worker-empty", str(empty_path),
                "--coverage", str(args.coverage),
                "--theater", args.theater,
            ),
            check=False,
        )
        if completed.returncode:
            return completed.returncode
        if cache_path.is_file():
            partials.append(cache_path)
    imported = perf_counter()
    index_path = args.cache_dir / "manifest.json"
    build_road_routing_shard_index(partials, index_path, theater_id=args.theater)
    network = merge_road_routing_artifacts(partials, theater_id=args.theater)
    compiled = perf_counter()
    output = network.save(args.output)
    saved = perf_counter()
    print(f"Wrote road-routing graph: {output}")
    print(f"  nodes: {network.node_count}")
    print(f"  edges: {network.edge_count} (undirected; oneway/access ignored)")
    print(f"  bridges: {int(network.edge_bridge.sum())} (metadata only)")
    print(f"  artifact: {output.stat().st_size / 1024 / 1024:.1f} MiB")
    print(f"  shard index: {index_path}")
    print(f"  import/compile/save: {imported-started:.1f}s / {compiled-imported:.1f}s / {saved-compiled:.1f}s")
    return 0


def _configured_pbf_paths(config_path: Path, pbf_dir: Path) -> tuple[Path, ...]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return tuple(
        pbf_dir / str(source["url"]).rsplit("/", 1)[-1]
        for source in config.get("geofabrik_sources") or ()
    )


def _build_partial(
    path: Path,
    output: Path,
    empty_marker: Path,
    *,
    coverage_path: Path,
    theater_id: str,
) -> int:
    try:
        import numpy as np
        from pyrosm import OSM
    except ImportError as exc:
        raise RuntimeError('road routing requires: python -m pip install -e ".[routing]"') from exc
    coverage = TheaterTopographyCoverage.load(coverage_path)
    low_geometry = coverage.geometry_for_minimum_level(TopographyDetailLevel.LOW)
    high_geometry = coverage.geometry_for_minimum_level(TopographyDetailLevel.HIGH)
    if low_geometry is None:
        raise ValueError("road routing requires at least one Topography Low or High zone")
    nodes, edges = OSM(str(path)).get_network(
        network_type="driving",
        nodes=True,
        extra_attributes=["bridge"],
    )
    if nodes is None or edges is None or nodes.empty or edges.empty:
        print("  no road features inside theater coverage", flush=True)
        empty_marker.touch()
        return 0
    sample_points = edges.geometry.interpolate(0.5, normalized=True)
    highway = edges["highway"].map(_road_classes)
    strategic = highway.map(lambda values: bool(values.intersection({"motorway", "trunk", "primary"})))
    selected = strategic & sample_points.intersects(low_geometry)
    if high_geometry is not None:
        selected |= sample_points.intersects(high_geometry)
    edges = edges[selected].copy()
    if edges.empty:
        print("  no road features inside theater coverage", flush=True)
        empty_marker.touch()
        return 0
    used_node_ids = np.unique(np.concatenate((
        edges["u"].astype("int64").to_numpy(),
        edges["v"].astype("int64").to_numpy(),
    )))
    nodes = nodes[nodes["id"].astype("int64").isin(used_node_ids)].copy()
    partial = build_road_routing_network(
        theater_id=theater_id,
        nodes=nodes,
        edges=edges,
        source_names=(path.name,),
    )
    partial.save(output)
    print(f"  cached {partial.node_count} nodes, {partial.edge_count} edges: {output.name}", flush=True)
    return 0


def _road_classes(value: object) -> frozenset[str]:
    """Normalize Pyrosm's scalar or collection-valued highway class."""

    if isinstance(value, str):
        return frozenset((value.removesuffix("_link"),))
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(str(item).removesuffix("_link") for item in value)
    return frozenset()


if __name__ == "__main__":
    raise SystemExit(main())
