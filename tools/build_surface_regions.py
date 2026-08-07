"""Build connected land and water regions from a theater topography cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import TheaterTopography, build_surface_regions, surface_region_counts


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
    parser.add_argument("--grid-spacing", type=float, default=250.0, help="Analysis grid spacing in meters.")
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


if __name__ == "__main__":
    raise SystemExit(main())
