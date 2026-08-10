"""Build normalized city and town objects from the topography viewport index."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import (  # noqa: E402
    SettlementBoundaryKind,
    SettlementImportanceTier,
    SettlementKind,
    SettlementSizeClass,
    TheaterSettlements,
    TopographyFeature,
    TopographyLayer,
    apply_administrative_boundaries,
    build_settlements,
)
from moosebridge.pbf_topography import administrative_boundaries_from_pbf  # noqa: E402


DEFAULT_MANIFEST = REPO_ROOT / "tmp" / "topography" / "viewport" / "manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "topography" / "GermanyCW-settlements.geojson"
DEFAULT_CONFIG = PYTHON_ROOT / "moosebridge" / "data" / "GermanyCW_topography.json"
DEFAULT_PBF_DIR = REPO_ROOT / "tmp" / "topography" / "pbf"
DEFAULT_ADMIN_CACHE = REPO_ROOT / "tmp" / "topography" / "administrative_boundary_cache"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build normalized strategic settlements")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--urban-gap-m", type=float, default=200.0)
    parser.add_argument("--urban-simplify-m", type=float, default=75.0)
    parser.add_argument("--boundary-mode", choices=("administrative", "urban"), default="administrative")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--pbf-dir", type=Path, default=DEFAULT_PBF_DIR)
    parser.add_argument("--boundary-source", action="append", dest="boundary_sources")
    parser.add_argument("--admin-simplify-m", type=float, default=75.0)
    parser.add_argument("--admin-cache-dir", type=Path, default=DEFAULT_ADMIN_CACHE)
    parser.add_argument("--refresh-admin-cache", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    theater_id = str(payload.get("theater_id") or "")
    settlements = {}
    raw_feature_count = 0
    shard_count = 0
    for index, shard, features in _load_shards(args.manifest.parent, payload.get("shards") or []):
        shard_count += 1
        raw_feature_count += len(features)
        print(f"  shard {index}/{len(payload.get('shards') or [])}: {shard['path']} ({len(features)} features)", flush=True)
        partial = build_settlements(
            features.values(),
            theater_id=theater_id,
            urban_gap_m=args.urban_gap_m,
            urban_simplify_m=args.urban_simplify_m,
        )
        for settlement in partial.settlements:
            previous = settlements.get(settlement.settlement_id)
            if previous is None or _settlement_quality(settlement) > _settlement_quality(previous):
                settlements[settlement.settlement_id] = settlement
    deduplicated = _deduplicate_nearby_names(settlements.values())
    ordered = tuple(sorted(
        deduplicated,
        key=lambda item: (-item.importance_score, item.name.casefold(), item.settlement_id),
    ))
    scenario_year = next((item.scenario_reference_year for item in ordered if item.scenario_reference_year), None)
    artifact = TheaterSettlements(
        theater_id=theater_id,
        scenario_reference_year=scenario_year,
        settlements=ordered,
        metadata={
            "boundary_policy": "connected urban land use in source shard near city/town anchor",
            "urban_gap_m": args.urban_gap_m,
            "urban_simplify_m": args.urban_simplify_m,
            "source_shard_count": shard_count,
            "raw_feature_count": raw_feature_count,
            "cross_shard_boundary_complete": False,
            "nearby_duplicate_count": len(settlements) - len(deduplicated),
        },
    )
    if args.boundary_mode == "administrative":
        pbf_paths = _administrative_pbf_paths(
            args.config,
            args.pbf_dir,
            selected=set(args.boundary_sources or ()),
        )
        print(f"Reading administrative boundaries from {len(pbf_paths)} PBF source(s) ...", flush=True)
        boundaries = _load_administrative_boundaries(
            pbf_paths,
            cache_dir=args.admin_cache_dir,
            simplify_meters=args.admin_simplify_m,
            refresh=args.refresh_admin_cache,
        )
        artifact = apply_administrative_boundaries(artifact, boundaries)
        print(
            f"  administrative boundaries: {len(boundaries)}, "
            f"matched settlements: {artifact.metadata.get('administrative_match_count', 0)}",
            flush=True,
        )
    output = artifact.save(args.output)
    print(f"Settlements written: {output}")
    print(f"  theater: {theater_id}")
    print(f"  raw shard features: {raw_feature_count}")
    print(f"  settlements: {len(artifact.settlements)}")
    for kind in SettlementKind:
        count = sum(item.kind is kind for item in artifact.settlements)
        print(f"  {kind.value}: {count}")
    for size_class in SettlementSizeClass:
        count = sum(item.size_class is size_class for item in artifact.settlements)
        print(f"  {size_class.value}: {count}")
    footprints = sum(
        item.boundary_kind is SettlementBoundaryKind.URBAN_FOOTPRINT
        for item in artifact.settlements
    )
    administrative = sum(
        item.boundary_kind is SettlementBoundaryKind.ADMINISTRATIVE
        for item in artifact.settlements
    )
    populated = sum(item.population is not None for item in artifact.settlements)
    print(f"  urban footprints: {footprints}")
    print(f"  administrative boundaries: {administrative}")
    print(f"  population values: {populated}")
    tiers = ", ".join(
        f"{tier.value}={sum(item.importance_tier is tier for item in artifact.settlements)}"
        for tier in SettlementImportanceTier
    )
    print(f"  importance tiers: {tiers}")
    return 0


def _administrative_pbf_paths(config_path: Path, directory: Path, *, selected: set[str]) -> list[Path]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    sources = config.get("geofabrik_sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("topography config has no geofabrik_sources")
    known = {str(source.get("id")) for source in sources}
    missing = selected - known
    if missing:
        raise ValueError(f"unknown boundary source(s): {', '.join(sorted(missing))}")
    paths = [
        directory / str(source.get("url") or "").rsplit("/", 1)[-1]
        for source in sources
        if not selected or str(source.get("id")) in selected
    ]
    missing_paths = [path for path in paths if not path.is_file()]
    if missing_paths:
        raise FileNotFoundError(f"PBF source is not downloaded: {missing_paths[0]}")
    return paths


def _load_administrative_boundaries(
    paths: list[Path],
    *,
    cache_dir: Path,
    simplify_meters: float,
    refresh: bool,
) -> tuple[TopographyFeature, ...]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    boundaries: dict[str, TopographyFeature] = {}
    for index, path in enumerate(paths, start=1):
        stat = path.stat()
        fingerprint = hashlib.sha256(
            f"v1|{path.name}|{stat.st_size}|{stat.st_mtime_ns}|{simplify_meters:g}".encode("utf-8")
        ).hexdigest()[:12]
        cache_path = cache_dir / f"{path.stem}-{fingerprint}.geojson"
        if cache_path.is_file() and not refresh:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            source_boundaries = tuple(
                TopographyFeature.from_geojson_feature(feature)
                for feature in payload.get("features") or ()
            )
            state = "cache"
        else:
            source_boundaries = administrative_boundaries_from_pbf(
                [path],
                simplify_meters=simplify_meters,
            )
            payload = {
                "type": "FeatureCollection",
                "features": [feature.to_geojson_feature() for feature in source_boundaries],
                "properties": {
                    "source_file": path.name,
                    "simplify_meters": simplify_meters,
                    "feature_count": len(source_boundaries),
                },
            }
            temporary = cache_path.with_suffix(".geojson.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")
            temporary.replace(cache_path)
            state = "read"
        print(
            f"  boundary {index}/{len(paths)}: {path.name} "
            f"({len(source_boundaries)} features, {state})",
            flush=True,
        )
        for boundary in source_boundaries:
            boundaries[boundary.object_id] = boundary
    return tuple(sorted(boundaries.values(), key=lambda feature: feature.object_id))


def _load_shards(directory: Path, shards: list[dict]):
    try:
        import pyogrio
        from shapely.geometry import mapping
    except ImportError as exc:
        raise RuntimeError('settlement import requires: python -m pip install -e ".[topography]"') from exc
    columns = [
        "layer", "object_id", "name", "category", "source", "source_id", "confidence",
        "scenario_reference_year", "valid_from", "dcs_verified", "osm_tags",
    ]
    where = (
        "(layer = 'topography_settlements' AND category IN ('city','town')) OR "
        "(layer = 'topography_landuse' AND category IN "
        "('residential','commercial','retail','industrial'))"
    )
    for index, shard in enumerate(shards, start=1):
        layers = set(shard.get("layers") or [])
        if not layers.intersection({"topography_settlements", "topography_landuse"}):
            continue
        path = directory / str(shard.get("path") or "")
        if not path.is_file():
            continue
        frame = pyogrio.read_dataframe(path, where=where, columns=columns)
        features: dict[str, TopographyFeature] = {}
        for row in frame.itertuples(index=False):
            if row.geometry is None or row.geometry.is_empty:
                continue
            object_id = str(row.object_id)
            features[object_id] = TopographyFeature(
                object_id=object_id,
                layer=TopographyLayer(str(row.layer)),
                category=str(row.category),
                geometry=mapping(row.geometry),
                source=str(row.source),
                source_id=_text(row.source_id),
                confidence=float(row.confidence),
                name=_text(row.name),
                scenario_reference_year=_integer(row.scenario_reference_year),
                valid_from=_integer(row.valid_from),
                dcs_verified=bool(row.dcs_verified),
                properties={"osm_tags": _tags(row.osm_tags)},
            )
        yield index, shard, features


def _settlement_quality(settlement) -> tuple[int, int, float]:
    return (
        int(settlement.boundary_kind is not SettlementBoundaryKind.POINT_ONLY),
        int(settlement.population is not None),
        float(settlement.urban_area_m2 or 0),
    )


def _deduplicate_nearby_names(settlements) -> list:
    retained = []
    for settlement in sorted(settlements, key=_settlement_quality, reverse=True):
        duplicate = next(
            (
                item for item in retained
                if item.name.casefold() == settlement.name.casefold()
                and _distance_m(item.latitude, item.longitude, settlement.latitude, settlement.longitude) <= 20_000
            ),
            None,
        )
        if duplicate is None:
            retained.append(settlement)
    return retained


def _distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius_m = 6_371_008.8
    lat1 = math.radians(lat_a)
    lat2 = math.radians(lat_b)
    dlat = lat2 - lat1
    dlon = math.radians(lon_b - lon_a)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius_m * 2 * math.asin(min(1.0, math.sqrt(value)))


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
