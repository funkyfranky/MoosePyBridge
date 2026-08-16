"""Build connected land and water regions from a theater topography cache."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
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
        help="Optional legacy merged topography input used only when no compact cache exists.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PYTHON_ROOT / "moosebridge" / "data" / "GermanyCW_topography.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "runtime" / "surface-regions.geojson",
    )
    parser.add_argument("--import-cache", type=Path, default=REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "cache" / "import")
    parser.add_argument(
        "--surface-source-output",
        type=Path,
        default=REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "cache" / "surface-source.geojson",
    )
    parser.add_argument(
        "--osm-land",
        type=Path,
        default=REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "sources" / "osmcoastline" / "land_polygons.shp",
    )
    parser.add_argument(
        "--osm-water",
        type=Path,
        default=REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "sources" / "osmcoastline" / "water_polygons.shp",
    )
    parser.add_argument("--refresh-surface-source", action="store_true", help="Rebuild the compact surface source from checkpoints.")
    parser.add_argument("--grid-spacing", type=float, default=500.0, help="Analysis grid spacing in meters.")
    parser.add_argument("--minimum-area-km2", type=float, default=0.25, help="Discard smaller components.")
    parser.add_argument("--simplify-meters", type=float, default=0.0, help="Optional output simplification; zero preserves shared boundaries.")
    parser.add_argument(
        "--bounds",
        type=float,
        nargs=4,
        metavar=("SOUTH", "WEST", "NORTH", "EAST"),
        help="Optional WGS84 comparison subset; defaults to the complete theater bounds.",
    )
    args = parser.parse_args()

    expected_source_count = None
    if args.config.is_file():
        config = json.loads(args.config.read_text(encoding="utf-8"))
        sources = config.get("geofabrik_sources")
        if isinstance(sources, list):
            expected_source_count = len(sources)

    if args.surface_source_output.is_file() and not args.refresh_surface_source:
        print(f"Loading compact surface source: {args.surface_source_output}", flush=True)
        topography = TheaterTopography.load(args.surface_source_output)
    elif args.import_cache.is_dir():
        print(f"Building compact surface source from import checkpoints: {args.import_cache}", flush=True)
        topography = _surface_topography_from_cache(args.import_cache)
        topography.save(args.surface_source_output)
        print(f"Wrote {len(topography.features)} coastline/water features to {args.surface_source_output}", flush=True)
    elif args.topography is not None and args.topography.is_file():
        print(f"Loading topography: {args.topography}", flush=True)
        topography = TheaterTopography.load(args.topography)
    else:
        raise FileNotFoundError(
            "surface build requires a compact surface source, import cache, or explicit --topography input"
        )
    if args.bounds:
        requested_bounds = tuple(args.bounds)
        if requested_bounds[0] >= requested_bounds[2] or requested_bounds[1] >= requested_bounds[3]:
            raise ValueError("bounds must be SOUTH WEST NORTH EAST")
        topography = replace(topography, bounds=requested_bounds)
    baseline_water = _load_polygon_baseline((args.osm_water,), topography.bounds, "OSM water")
    baseline_land = None
    baseline_land_source = f"{topography.theater_id} bounds minus OpenStreetMap prepared sea polygons"
    baseline_water_source = "OpenStreetMap prepared sea polygons"
    print(
        f"Building {topography.theater_id} surface regions at {args.grid_spacing:.0f} m resolution ...",
        flush=True,
    )
    regions = build_surface_regions(
        topography,
        baseline_land_geometry=baseline_land,
        baseline_land_source=baseline_land_source,
        baseline_water_geometry=baseline_water,
        baseline_water_source=baseline_water_source,
        refine_baseline_with_coastlines=False,
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


def _load_polygon_baseline(
    paths: tuple[Path, ...],
    bounds: tuple[float, float, float, float] | None,
    label: str,
) -> object:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        joined = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            f"{label} baseline missing: {joined}. "
            "Run the corresponding coastline-data downloader first."
        )
    if bounds is None:
        raise ValueError("topography bounds are required to load the land baseline")
    try:
        import pyogrio
        import shapely
        from pyproj import Transformer
    except ImportError as exc:
        raise RuntimeError('surface regions require: python -m pip install -e ".[topography]"') from exc

    south, west, north, east = bounds
    geometries = []
    for path in paths:
        info = pyogrio.read_info(path)
        source_crs = info.get("crs")
        if not source_crs:
            raise ValueError(f"{path} has no coordinate reference system")
        if str(source_crs).upper() == "EPSG:4326":
            source_bbox = (west, south, east, north)
        else:
            transformer = Transformer.from_crs("EPSG:4326", source_crs, always_xy=True)
            x_values, y_values = transformer.transform(
                [west, east, east, west],
                [south, south, north, north],
            )
            source_bbox = (min(x_values), min(y_values), max(x_values), max(y_values))
        frame = pyogrio.read_dataframe(path, bbox=source_bbox, columns=[])
        if str(frame.crs).upper() != "EPSG:4326":
            frame = frame.to_crs("EPSG:4326")
        geometries.extend(geometry for geometry in frame.geometry if geometry is not None and not geometry.is_empty)
    if not geometries:
        raise ValueError(f"{label} baseline does not intersect the topography bounds")
    return shapely.union_all(geometries)


def _land_complement(
    water_geometry: dict,
    bounds: tuple[float, float, float, float] | None,
) -> dict:
    if bounds is None:
        raise ValueError("topography bounds are required to derive the land complement")
    try:
        import shapely
        from shapely.geometry import box, mapping, shape
    except ImportError as exc:
        raise RuntimeError('surface regions require: python -m pip install -e ".[topography]"') from exc
    south, west, north, east = bounds
    land = shapely.make_valid(box(west, south, east, north).difference(shape(water_geometry)))
    if land.is_empty:
        raise ValueError("OSM sea polygons cover the complete topography bounds")
    return mapping(land)


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
