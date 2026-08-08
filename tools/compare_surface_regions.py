"""Compare the current and candidate GermanyCW surface-region artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge.surface_comparison import compare_surface_regions
from moosebridge.surface_regions import TheaterSurfaceRegions


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two theater surface-region artifacts")
    parser.add_argument(
        "--reference",
        type=Path,
        default=REPO_ROOT / "tmp" / "topography" / "GermanyCW-surface-regions.geojson",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=REPO_ROOT / "tmp" / "topography" / "GermanyCW-surface-regions-osm.geojson",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "tmp" / "topography" / "GermanyCW-surface-comparison.geojson",
    )
    parser.add_argument("--sample-spacing", type=float, default=5_000.0)
    args = parser.parse_args()

    reference = TheaterSurfaceRegions.load(args.reference)
    candidate = TheaterSurfaceRegions.load(args.candidate)
    summary, geojson = compare_surface_regions(
        reference,
        candidate,
        sample_spacing_m=args.sample_spacing,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(geojson, separators=(",", ":")) + "\n", encoding="utf-8")

    print("Surface-region comparison")
    print("=" * 80)
    print(f"Reference : {args.reference}")
    print(f"Candidate : {args.candidate}")
    print(f"Samples   : {summary['sample_count']} at {summary['sample_spacing_m'] / 1000:.1f} km spacing")
    print(f"Agreement : {summary['agreement_percent']:.2f}%")
    print(f"Land -> water: {summary['reference_land_candidate_water']}")
    print(f"Water -> land: {summary['reference_water_candidate_land']}")
    print(f"Differences written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
