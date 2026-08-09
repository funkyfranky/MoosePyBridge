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
    EnergySite,
    FuelStorageSite,
    InfrastructureCandidatePolicy,
    IndustrialSite,
    MilitarySite,
    TopographyFeature,
    TopographyLayer,
    build_infrastructure_sites,
)


DEFAULT_MANIFEST = REPO_ROOT / "tmp" / "topography" / "viewport" / "manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "topography" / "GermanyCW-infrastructure-sites.geojson"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build normalized strategic infrastructure-site candidates")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--include-modern-energy",
        action="store_true",
        help="Disable GermanyCW's wind, solar, biogas, and battery exclusions.",
    )
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    theater_id = str(payload.get("theater_id") or "")
    features = _load_candidates(args.manifest.parent, payload.get("shards") or [])
    policy = None
    if args.include_modern_energy:
        policy = InfrastructureCandidatePolicy(theater_id=theater_id)
    artifact = build_infrastructure_sites(features.values(), theater_id=theater_id, policy=policy)
    output = artifact.save(args.output)
    energy_count = sum(isinstance(site, EnergySite) for site in artifact.sites)
    fuel_count = sum(isinstance(site, FuelStorageSite) for site in artifact.sites)
    military_count = sum(isinstance(site, MilitarySite) for site in artifact.sites)
    industrial_count = sum(isinstance(site, IndustrialSite) for site in artifact.sites)
    print(f"Infrastructure sites written: {output}")
    print(f"  theater: {theater_id}")
    print(f"  raw unique candidates: {len(features)}")
    print(f"  admitted energy sites: {energy_count}")
    print(f"  admitted fuel/storage sites: {fuel_count}")
    print(f"  admitted military sites: {military_count}")
    print(f"  admitted industrial sites: {industrial_count}")
    excluded = artifact.metadata.get("energy", {}).get("excluded_energy_source_counts") or {}
    print("  excluded: " + (", ".join(f"{key}={value}" for key, value in sorted(excluded.items())) or "none"))
    return 0


_CANDIDATE_CATEGORIES = (
    "power_plant", "storage_tank", "refinery", "oil", "oil_storage",
    "distillates_storage", "gas", "natural_gas", "gas_storage", "gas_cavern",
    "storage", "depot",
    "military",
    "industrial_area", "works", "factory", "sawmill", "brewery", "chemical",
    "shipyard", "mine", "metal_processing", "quarry", "cement", "glass",
    "machinery", "steelmaking", "automotive", "food", "electronics",
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
                source_id=_text(row.source_id),
                confidence=float(row.confidence),
                name=_text(row.name),
                scenario_reference_year=_integer(row.scenario_reference_year),
                valid_from=_integer(row.valid_from),
                dcs_verified=bool(row.dcs_verified),
                properties={"osm_tags": _tags(row.osm_tags)},
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


if __name__ == "__main__":
    raise SystemExit(main())
