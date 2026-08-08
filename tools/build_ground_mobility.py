"""Build the strategic GermanyCW ground-mobility graph."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
from typing import Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import (
    GroundTransportFeature,
    RoadClass,
    TheaterSurfaceRegions,
    build_ground_mobility_network,
)


DEFAULT_MANIFEST = REPO_ROOT / "tmp" / "topography" / "viewport" / "manifest.json"
DEFAULT_SURFACES = REPO_ROOT / "tmp" / "topography" / "GermanyCW-surface-regions.geojson"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "topography" / "GermanyCW-ground-mobility.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a strategic ground-mobility graph")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--surfaces", type=Path, default=DEFAULT_SURFACES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--grid-spacing", type=float, default=5_000.0)
    args = parser.parse_args()

    if not args.manifest.is_file():
        raise FileNotFoundError(args.manifest)
    if not args.surfaces.is_file():
        raise FileNotFoundError(args.surfaces)

    surfaces = TheaterSurfaceRegions.load(args.surfaces)
    print(f"Loading transport features from {args.manifest} ...", flush=True)
    network = build_ground_mobility_network(
        surfaces,
        _transport_features(args.manifest),
        grid_spacing_m=args.grid_spacing,
    )
    network.save(args.output)
    road_nodes = sum(node.road_class is not None for node in network.nodes)
    bridge_edges = sum(edge.bridge for edge in network.edges)
    print(f"Wrote ground mobility graph: {args.output}")
    print(f"  nodes: {len(network.nodes)} ({road_nodes} road-influenced)")
    print(f"  edges: {len(network.edges)} ({bridge_edges} bridge crossings)")
    print(f"  components: {network.component_count}")
    print(f"  grid spacing: {network.grid_spacing_m:.0f} m")
    return 0


def _transport_features(manifest_path: Path) -> Iterator[GroundTransportFeature]:
    try:
        import pyogrio
    except ImportError as exc:
        raise RuntimeError(
            'ground mobility requires: python -m pip install -e ".[topography]"'
        ) from exc

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    classes = tuple(road_class.value for road_class in RoadClass)
    class_sql = ",".join(f"'{value}'" for value in classes)
    where = f"layer = 'topography_roads' AND category IN ({class_sql})"
    seen: set[str] = set()
    shards = [
        item for item in manifest.get("shards") or []
        if "topography_roads" in (item.get("layers") or [])
    ]
    for index, item in enumerate(shards, start=1):
        path = root / str(item["path"])
        print(f"  [{index}/{len(shards)}] {path.name}", flush=True)
        frame = pyogrio.read_dataframe(
            path,
            where=where,
            columns=["layer", "source_id", "category", "osm_tags", "valid_from", "valid_to"],
        )
        if frame.empty:
            continue
        frame = frame[~frame["source_id"].astype(str).isin(seen)].copy()
        if frame.empty:
            continue
        if "valid_from" in frame:
            frame = frame[frame["valid_from"].isna() | (frame["valid_from"] <= 1999)].copy()
        if "valid_to" in frame:
            frame = frame[frame["valid_to"].isna() | (frame["valid_to"] >= 1999)].copy()
        if frame.empty:
            continue
        frame = frame.to_crs("EPSG:3035")
        for record in frame.itertuples(index=False):
            source_id = str(record.source_id or "")
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            tags = _parse_osm_tags(record.osm_tags)
            geometry = record.geometry
            if geometry is None or geometry.is_empty:
                continue
            yield GroundTransportFeature(
                source_id=source_id,
                road_class=RoadClass(str(record.category)),
                geometry=geometry.__geo_interface__,
                bridge=tags.get("bridge") not in {None, "no"},
                coordinate_system="EPSG:3035",
            )


def _parse_osm_tags(value: object) -> dict[str, object]:
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
