"""Build connected land and water regions from a theater topography cache."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import TheaterTopography, TopographyFeature, TopographyLayer, build_surface_regions, surface_region_counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Build connected theater land/water regions")
    parser.add_argument(
        "--topography",
        type=Path,
        default=REPO_ROOT / "tmp" / "topography" / "GermanyCW.geojson",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PYTHON_ROOT / "moosebridge" / "data" / "GermanyCW_topography.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "tmp" / "topography" / "GermanyCW-surface-regions.geojson",
    )
    parser.add_argument("--import-cache", type=Path, default=REPO_ROOT / "tmp" / "topography" / "import_cache")
    parser.add_argument(
        "--surface-source-output",
        type=Path,
        default=REPO_ROOT / "tmp" / "topography" / "GermanyCW-surface-source.geojson",
    )
    parser.add_argument("--refresh-surface-source", action="store_true", help="Rebuild the compact surface source from checkpoints.")
    parser.add_argument("--grid-spacing", type=float, default=500.0, help="Analysis grid spacing in meters.")
    parser.add_argument("--minimum-area-km2", type=float, default=0.25, help="Discard smaller components.")
    parser.add_argument("--simplify-meters", type=float, default=0.0, help="Optional output simplification; zero preserves shared boundaries.")
    args = parser.parse_args()

    if not args.topography.is_file():
        raise FileNotFoundError(args.topography)
    expected_source_count = None
    if args.config.is_file():
        config = json.loads(args.config.read_text(encoding="utf-8"))
        sources = config.get("geofabrik_sources")
        if isinstance(sources, list):
            expected_source_count = len(sources)

    if (
        args.topography.stat().st_size > 512 * 1024 * 1024
        and args.surface_source_output.is_file()
        and not args.refresh_surface_source
    ):
        print(f"Loading compact surface source: {args.surface_source_output}", flush=True)
        topography = TheaterTopography.load(args.surface_source_output)
    elif args.topography.stat().st_size > 512 * 1024 * 1024 and args.import_cache.is_dir():
        print(f"Building compact surface source from import checkpoints: {args.import_cache}", flush=True)
        topography = _surface_topography_from_cache(args.import_cache)
        topography.save(args.surface_source_output)
        print(f"Wrote {len(topography.features)} coastline/water features to {args.surface_source_output}", flush=True)
    else:
        print(f"Loading topography: {args.topography}", flush=True)
        topography = TheaterTopography.load(args.topography)
    print(
        f"Building {topography.theater_id} surface regions at {args.grid_spacing:.0f} m resolution ...",
        flush=True,
    )
    regions = build_surface_regions(
        topography,
        grid_spacing_m=args.grid_spacing,
        minimum_region_area_m2=args.minimum_area_km2 * 1_000_000,
        simplify_meters=args.simplify_meters,
        expected_source_count=expected_source_count,
    )
    regions.save(args.output)
    print(f"Wrote {len(regions.regions)} regions to {args.output}")
    for kind, count in sorted(surface_region_counts(regions.regions).items()):
        area = sum(region.area_m2 for region in regions.regions if region.kind.value == kind) / 1_000_000
        print(f"  {kind}: {count} region(s), {area:.1f} km2")
    if not regions.metadata.get("source_complete", True):
        print(
            "WARNING: The input cache contains only "
            f"{len(regions.metadata.get('source_files') or [])}/{expected_source_count} configured PBF sources."
        )
    return 0


def _surface_topography_from_cache(cache_dir: Path) -> TheaterTopography:
    cache_paths = list(cache_dir.glob("*.geojson"))
    key_pattern = re.compile(r"-([0-9a-f]{12})\.geojson$")
    keys = Counter(match.group(1) for path in cache_paths if (match := key_pattern.search(path.name)))
    if not keys:
        raise ValueError(f"no versioned import checkpoints found in {cache_dir}")
    cache_key, _ = keys.most_common(1)[0]
    selected = sorted(path for path in cache_paths if path.name.endswith(f"-{cache_key}.geojson"))
    features: dict[str, TopographyFeature] = {}
    sources: list[str] = []
    bounds = None
    theater_id = ""
    reference_year = None
    snapshot_dates: list[str] = []
    for index, path in enumerate(selected, start=1):
        shard = TheaterTopography.load(path)
        print(f"  surface checkpoint {index}/{len(selected)}: {path.name}", flush=True)
        theater_id = theater_id or shard.theater_id
        reference_year = reference_year if reference_year is not None else shard.scenario_reference_year
        bounds = bounds or shard.bounds
        sources.extend(str(item) for item in shard.metadata.get("source_files") or [])
        if shard.source_snapshot_date:
            snapshot_dates.append(shard.source_snapshot_date)
        for feature in shard.features:
            if feature.layer is not TopographyLayer.WATER:
                continue
            geometry_type = str(feature.geometry.get("type") or "")
            if feature.category != "coastline" and geometry_type not in {"Polygon", "MultiPolygon"}:
                continue
            features[feature.object_id] = TopographyFeature(
                object_id=feature.object_id,
                layer=feature.layer,
                category=feature.category,
                geometry=feature.geometry,
                source=feature.source,
                confidence=feature.confidence,
                name=feature.name,
                source_id=feature.source_id,
                scenario_reference_year=feature.scenario_reference_year,
                source_snapshot_date=feature.source_snapshot_date,
                valid_from=feature.valid_from,
                valid_to=feature.valid_to,
                dcs_verified=feature.dcs_verified,
                properties={"ground_passable": False, "naval_candidate": True},
            )
    return TheaterTopography(
        theater_id=theater_id,
        scenario_reference_year=reference_year,
        source_snapshot_date=max(snapshot_dates) if snapshot_dates else None,
        bounds=bounds,
        features=tuple(sorted(features.values(), key=lambda feature: feature.object_id)),
        metadata={
            "external_source": "OpenStreetMap Geofabrik PBF surface subset",
            "source_files": sorted(set(sources)),
            "dcs_verification": "pending",
            "conversion_cache_key": cache_key,
            "surface_source": True,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
