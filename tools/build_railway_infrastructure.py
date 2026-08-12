"""Build aggregated railway infrastructure from the viewport cache and local PBFs."""

from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import sys
from time import perf_counter


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import (  # noqa: E402
    RailwayCriticalityConfig,
    TopographyFeature,
    TopographyLayer,
    analyze_railway_criticality,
    build_railway_infrastructure,
    build_railway_routing_network,
)
from moosebridge.pbf_topography import _normalize_ogr_record, features_from_pyrosm_record  # noqa: E402
from moosebridge.topography_coverage import TheaterTopographyCoverage  # noqa: E402


DEFAULT_MANIFEST = REPO_ROOT / "tmp" / "topography" / "viewport" / "manifest.json"
DEFAULT_CONFIG = PYTHON_ROOT / "moosebridge" / "data" / "GermanyCW_topography.json"
DEFAULT_PBF_DIR = REPO_ROOT / "tmp" / "topography" / "pbf"
DEFAULT_COVERAGE = REPO_ROOT / "tmp" / "topography" / "GermanyCW-coverage.geojson"
DEFAULT_FACILITY_CACHE = REPO_ROOT / "tmp" / "topography" / "railway_facility_cache"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "topography" / "GermanyCW-railway-infrastructure.geojson"
DEFAULT_ROUTING_OUTPUT = REPO_ROOT / "tmp" / "topography" / "GermanyCW-railway-routing.npz"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build aggregated railway infrastructure GeoJSON")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--pbf-dir", type=Path, default=DEFAULT_PBF_DIR)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--routing-output", type=Path, default=DEFAULT_ROUTING_OUTPUT)
    parser.add_argument("--analyze-criticality", action="store_true")
    parser.add_argument("--maximum-route-km", type=float, default=100.0)
    parser.add_argument("--facility-cache", type=Path, default=DEFAULT_FACILITY_CACHE)
    parser.add_argument("--refresh-facilities", action="store_true")
    parser.add_argument("--cluster-radius", type=float, default=350.0)
    parser.add_argument("--workers", type=int, default=4, help="Parallel PBF facility readers.")
    parser.add_argument("--source", action="append", help="Limit facility import to configured source id(s).")
    args = parser.parse_args()

    started = perf_counter()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected_sources = set(args.source or ())
    tracks = _load_tracks(
        args.manifest.parent,
        manifest.get("shards") or [],
        selected_sources=selected_sources,
    )
    tracks_loaded = perf_counter()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    coverage = TheaterTopographyCoverage.load(args.coverage)
    facilities = _load_facilities(
        config,
        args.pbf_dir,
        bounds=coverage.bounds,
        selected_sources=selected_sources,
        workers=max(1, args.workers),
        cache_dir=args.facility_cache,
        refresh=args.refresh_facilities,
        allowed_pbf_names={
            str(shard.get("path") or "").split("-latest.osm-", 1)[0] + "-latest.osm.pbf"
            for shard in manifest.get("shards") or []
        },
    )
    facilities_loaded = perf_counter()
    artifact = build_railway_infrastructure(
        tracks.values(),
        facilities.values(),
        theater_id=str(manifest.get("theater_id") or config.get("theater_id") or ""),
        cluster_radius_m=args.cluster_radius,
    )
    built = perf_counter()
    routing = None
    if args.analyze_criticality:
        routing = build_railway_routing_network(
            tracks.values(),
            theater_id=str(manifest.get("theater_id") or config.get("theater_id") or ""),
        )
        routing.save(args.routing_output)
        artifact = analyze_railway_criticality(
            routing,
            artifact,
            config=RailwayCriticalityConfig(maximum_route_m=args.maximum_route_km * 1_000),
        )
    analyzed = perf_counter()
    output = artifact.save(args.output)
    saved = perf_counter()
    counts = artifact.to_geojson()["properties"]["counts"]
    tiers = {
        tier: sum(location.importance_tier.value == tier for location in artifact.locations)
        for tier in ("critical", "high", "medium", "local")
    }
    print(f"Railway infrastructure written: {output}")
    print(f"  railway track features: {len(tracks)}")
    print(f"  raw facility features: {len(facilities)}")
    print("  locations: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    print("  importance: " + ", ".join(f"{key}={value}" for key, value in tiers.items()))
    if routing is not None:
        print(f"  routing graph: {routing.node_count} nodes, {routing.edge_count} edges -> {args.routing_output}")
        print(f"  criticality locations: {artifact.metadata.get('railway_criticality_location_count', 0)}")
    print(
        "  tracks/facilities/build/analysis/save: "
        f"{tracks_loaded-started:.2f}s / {facilities_loaded-tracks_loaded:.2f}s / "
        f"{built-facilities_loaded:.2f}s / {analyzed-built:.2f}s / {saved-analyzed:.2f}s"
    )
    return 0


def _load_tracks(
    directory: Path,
    shards: list[dict],
    *,
    selected_sources: set[str],
) -> dict[str, TopographyFeature]:
    try:
        import pyogrio
        from shapely.geometry import mapping
    except ImportError as exc:
        raise RuntimeError('railway import requires: python -m pip install -e ".[topography]"') from exc
    columns = [
        "layer", "object_id", "name", "category", "source", "source_id", "confidence",
        "scenario_reference_year", "valid_from", "dcs_verified", "osm_tags",
    ]
    features: dict[str, TopographyFeature] = {}
    for index, shard in enumerate(shards, start=1):
        path = directory / str(shard.get("path") or "")
        if selected_sources and not any(path.name.startswith(f"{source}-latest.osm-") for source in selected_sources):
            continue
        if not path.is_file() or TopographyLayer.RAILWAYS.value not in (shard.get("layers") or []):
            continue
        frame = pyogrio.read_dataframe(
            path,
            where=f"layer = '{TopographyLayer.RAILWAYS.value}' AND category = 'rail'",
            columns=columns,
            use_arrow=True,
        )
        print(f"  track shard {index}/{len(shards)}: {path.name} ({len(frame)} tracks)", flush=True)
        for row in frame.itertuples(index=False):
            if row.geometry is None or row.geometry.is_empty:
                continue
            object_id = str(row.object_id)
            features[object_id] = TopographyFeature(
                object_id=object_id,
                layer=TopographyLayer.RAILWAYS,
                category="rail",
                geometry=mapping(row.geometry),
                source=str(getattr(row, "source", "OpenStreetMap")),
                source_id=_text(getattr(row, "source_id", None)),
                confidence=float(getattr(row, "confidence", 0.6)),
                name=_text(getattr(row, "name", None)),
                scenario_reference_year=_integer(getattr(row, "scenario_reference_year", None)),
                valid_from=_integer(getattr(row, "valid_from", None)),
                dcs_verified=bool(getattr(row, "dcs_verified", False)),
                properties={"osm_tags": _tags(getattr(row, "osm_tags", None))},
            )
    return features


_FACILITY_WHERE = (
    "other_tags LIKE '%\"railway\"=>\"station\"%' OR "
    "other_tags LIKE '%\"railway\"=>\"halt\"%' OR "
    "other_tags LIKE '%\"railway\"=>\"depot\"%' OR "
    "other_tags LIKE '%\"railway\"=>\"yard\"%' OR "
    "other_tags LIKE '%\"railway\"=>\"freight_terminal\"%' OR "
    "other_tags LIKE '%\"railway\"=>\"container_terminal\"%' OR "
    "other_tags LIKE '%\"public_transport\"=>\"station\"%' OR "
    "other_tags LIKE '%\"freight\"=>\"yes\"%'"
)


def _load_facilities(
    config: dict,
    pbf_dir: Path,
    *,
    bounds: tuple[float, float, float, float],
    selected_sources: set[str],
    workers: int,
    cache_dir: Path,
    refresh: bool,
    allowed_pbf_names: set[str],
) -> dict[str, TopographyFeature]:
    try:
        import pyogrio
    except ImportError as exc:
        raise RuntimeError('railway import requires: python -m pip install -e ".[topography]"') from exc
    south, west, north, east = bounds
    bbox = (west, south, east, north)
    configured = config.get("geofabrik_sources") or []
    sources = [
        source for source in configured
        if (not selected_sources or source.get("id") in selected_sources)
        and str(source.get("url") or "").rsplit("/", 1)[-1] in allowed_pbf_names
    ]
    missing = selected_sources - {str(source.get("id")) for source in sources}
    if missing:
        raise ValueError(f"unknown Geofabrik source(s): {', '.join(sorted(missing))}")
    cache_dir.mkdir(parents=True, exist_ok=True)

    def read_source(index: int, source: dict) -> tuple[int, Path, dict[str, TopographyFeature], bool]:
        filename = str(source.get("url") or "").rsplit("/", 1)[-1]
        path = pbf_dir / filename
        cache_path = cache_dir / f"{Path(filename).stem}-v1.geojson"
        if cache_path.is_file() and not refresh:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            local = {
                feature.object_id: feature
                for item in payload.get("features") or ()
                for feature in (TopographyFeature.from_geojson_feature(item),)
            }
            return index, path, local, True
        if not path.is_file():
            return index, path, {}, False
        local: dict[str, TopographyFeature] = {}
        for layer in ("points", "multipolygons"):
            frame = pyogrio.read_dataframe(
                path,
                layer=layer,
                bbox=bbox,
                where=_FACILITY_WHERE,
                use_arrow=True,
            )
            for record in frame.iterfeatures():
                normalized = _normalize_ogr_record(record, layer)
                converted = features_from_pyrosm_record(
                    normalized,
                    scenario_reference_year=int(config.get("scenario_reference_year") or 0) or None,
                    source_snapshot_date=None,
                    include_buildings=False,
                )
                for feature in converted:
                    if feature.layer is TopographyLayer.INFRASTRUCTURE and feature.category.startswith("railway_"):
                        local[feature.object_id] = feature
        temporary = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
        temporary.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [feature.to_geojson_feature() for feature in local.values()],
        }, ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(cache_path)
        return index, path, local, False

    features: dict[str, TopographyFeature] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(read_source, index, source) for index, source in enumerate(sources, start=1)]
        for future in as_completed(futures):
            index, path, local, cached = future.result()
            features.update(local)
            status = f"+{len(local)}" if path.is_file() else "missing"
            suffix = ", cache" if cached else ""
            print(f"  facility source {index}/{len(sources)}: {path.name} ({status}{suffix})", flush=True)
    return features


def _tags(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(value)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return str(value)


def _integer(value: object) -> int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return int(value)


if __name__ == "__main__":
    raise SystemExit(main())
