"""Build normalized infrastructure sites from a topography viewport index."""

from __future__ import annotations

import argparse
import ast
import json
import math
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import (  # noqa: E402
    EnergySource,
    EnergySite,
    FuelStorageSite,
    InfrastructureCandidatePolicy,
    IndustrialSite,
    MaritimeSite,
    MilitarySite,
    TopographyFeature,
    TopographyDetailLevel,
    TopographyLayer,
    build_infrastructure_sites,
)
from moosebridge.theater_data import DEFAULT_THEATER_PROFILE_PATH, TheaterDataProfile  # noqa: E402
from moosebridge.pbf_topography import (  # noqa: E402
    clip_topography_feature_to_mask,
    targeted_infrastructure_features_from_pbf,
    topography_detail_level,
)
from moosebridge.topography_coverage import TheaterTopographyCoverage  # noqa: E402


DEFAULT_MANIFEST = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "cache" / "viewport" / "manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "runtime" / "infrastructure-sites.geojson"
DEFAULT_PBF_DIRECTORY = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "sources" / "pbf"
DEFAULT_COVERAGE = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "verification" / "coverage.geojson"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build normalized strategic infrastructure-site candidates")
    parser.add_argument("--profile", type=Path, default=DEFAULT_THEATER_PROFILE_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument(
        "--pbf-directory",
        type=Path,
        default=DEFAULT_PBF_DIRECTORY,
        help="Directory containing Geofabrik PBF files for targeted energy and maritime extraction.",
    )
    parser.add_argument(
        "--include-modern-energy",
        action="store_true",
        help="Disable the theater profile's historical energy-source exclusions.",
    )
    args = parser.parse_args()
    profile = TheaterDataProfile.load(args.profile)
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    theater_id = str(payload.get("theater_id") or "")
    if theater_id.casefold() != profile.theater_id.casefold():
        raise ValueError(f"viewport theater {theater_id!r} does not match profile {profile.theater_id!r}")
    features = _load_candidates(args.manifest.parent, payload.get("shards") or [])
    coverage = TheaterTopographyCoverage.load(args.coverage)
    coverage_masks = {
        level: coverage.geometry_for_minimum_level(level)
        for level in TopographyDetailLevel
    }
    pbf_paths = sorted(args.pbf_directory.glob("*.osm.pbf")) if args.pbf_directory.is_dir() else []
    if pbf_paths:
        print(f"  reading targeted energy and maritime data from {len(pbf_paths)} PBF file(s)", flush=True)
        bounds = _manifest_bounds(payload.get("shards") or [])
        for feature in targeted_infrastructure_features_from_pbf(
            pbf_paths,
            bounds=bounds,
            scenario_reference_year=profile.infrastructure_reference_year,
            max_workers=8,
        ):
            required_level = topography_detail_level(feature)
            mask = coverage_masks[required_level]
            if mask is None:
                continue
            clipped_feature = clip_topography_feature_to_mask(feature, mask, required_level)
            if clipped_feature is None:
                continue
            features[feature.object_id] = clipped_feature
    excluded = () if args.include_modern_energy else profile.excluded_energy_sources
    policy = InfrastructureCandidatePolicy(
        theater_id=theater_id,
        scenario_reference_year=profile.infrastructure_reference_year,
        excluded_energy_sources=frozenset(EnergySource(value) for value in excluded),
    )
    artifact = build_infrastructure_sites(features.values(), theater_id=theater_id, policy=policy)
    output = artifact.save(args.output)
    energy_count = sum(isinstance(site, EnergySite) for site in artifact.sites)
    fuel_count = sum(isinstance(site, FuelStorageSite) for site in artifact.sites)
    military_count = sum(isinstance(site, MilitarySite) for site in artifact.sites)
    industrial_count = sum(isinstance(site, IndustrialSite) for site in artifact.sites)
    maritime_count = sum(isinstance(site, MaritimeSite) for site in artifact.sites)
    print(f"Infrastructure sites written: {output}")
    print(f"  theater: {theater_id}")
    print(f"  raw unique candidates: {len(features)}")
    print(f"  admitted energy sites: {energy_count}")
    print(f"  admitted fuel/storage sites: {fuel_count}")
    print(f"  admitted military sites: {military_count}")
    print(f"  admitted industrial sites: {industrial_count}")
    print(f"  admitted maritime sites: {maritime_count}")
    excluded = artifact.metadata.get("energy", {}).get("excluded_energy_source_counts") or {}
    print("  excluded: " + (", ".join(f"{key}={value}" for key, value in sorted(excluded.items())) or "none"))
    return 0


_CANDIDATE_CATEGORIES = (
    "power_plant", "power_substation", "power_converter", "storage_tank", "refinery", "oil", "oil_storage",
    "distillates_storage", "gas", "natural_gas", "gas_storage", "gas_cavern",
    "storage", "depot",
    "military",
    "industrial_area", "works", "factory", "sawmill", "brewery", "chemical",
    "shipyard", "mine", "metal_processing", "quarry", "cement", "glass",
    "machinery", "steelmaking", "automotive", "food", "electronics",
    "harbour", "port", "ferry_terminal", "pier", "quay", "dock", "berth", "harbour_basin",
)


def _load_candidates(directory: Path, shards: list[dict]) -> dict[str, TopographyFeature]:
    try:
        import pyogrio
        from shapely.geometry import mapping
    except ImportError as exc:
        raise RuntimeError('infrastructure import requires: python -m pip install -e ".[topography]"') from exc
    features: dict[str, TopographyFeature] = {}
    columns = [
        "layer", "object_id", "name", "category", "source", "source_id", "confidence",
        "scenario_reference_year", "valid_from", "dcs_verified", "osm_tags",
    ]
    for index, shard in enumerate(shards, start=1):
        path = directory / str(shard.get("path") or "")
        if not path.is_file() or "topography_infrastructure" not in (shard.get("layers") or []):
            continue
        categories = ",".join(repr(category) for category in _CANDIDATE_CATEGORIES)
        frame = pyogrio.read_dataframe(path, where=f"category IN ({categories})", columns=columns)
        for column in columns:
            if column not in frame.columns:
                frame[column] = None
        print(f"  shard {index}/{len(shards)}: {path.name} ({len(frame)} candidates)", flush=True)
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
                source_id=_text(getattr(row, "source_id", None)),
                confidence=float(row.confidence),
                name=_text(getattr(row, "name", None)),
                scenario_reference_year=_integer(getattr(row, "scenario_reference_year", None)),
                valid_from=_integer(getattr(row, "valid_from", None)),
                dcs_verified=bool(getattr(row, "dcs_verified", False)),
                properties={"osm_tags": _tags(getattr(row, "osm_tags", None))},
            )
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


def _manifest_bounds(shards: list[dict]) -> tuple[float, float, float, float] | None:
    boxes = [shard.get("bounds") for shard in shards]
    boxes = [box for box in boxes if isinstance(box, list) and len(box) == 4]
    if not boxes:
        return None
    return (
        min(float(box[1]) for box in boxes),
        min(float(box[0]) for box in boxes),
        max(float(box[3]) for box in boxes),
        max(float(box[2]) for box in boxes),
    )


if __name__ == "__main__":
    raise SystemExit(main())
