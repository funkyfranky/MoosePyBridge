"""Download prepared OSMCoastline land, sea, and coastline shapefiles."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS = {
    "land": (
        "https://osmdata.openstreetmap.de/download/simplified-land-polygons-complete-3857.zip",
        "land_polygons",
    ),
    "water": (
        "https://osmdata.openstreetmap.de/download/simplified-water-polygons-split-3857.zip",
        "water_polygons",
    ),
    "coastlines": (
        "https://osmdata.openstreetmap.de/download/coastlines-split-4326.zip",
        "coastlines",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download prepared OpenStreetMap coastline datasets")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "tmp" / "topography" / "osmcoastline",
    )
    parser.add_argument("--dataset", choices=tuple(DATASETS), action="append")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    selected = args.dataset or ["land", "water"]
    manifest: dict[str, object] = {
        "source": "osmdata.openstreetmap.de prepared OSMCoastline datasets",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "datasets": {},
    }
    for dataset in selected:
        url, target_stem = DATASETS[dataset]
        target = args.output / f"{target_stem}.shp"
        if target.is_file() and not args.refresh:
            print(f"Reusing {target}")
        else:
            print(f"Downloading {url}", flush=True)
            with tempfile.TemporaryDirectory(prefix="moosebridge-osmcoastline-") as temporary:
                archive = Path(temporary) / f"{dataset}.zip"
                with urlopen(url, timeout=180) as response, archive.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
                _extract_shapefile(archive, args.output, target_stem)
            print(f"Wrote {dataset} dataset to {args.output}")
        manifest["datasets"][dataset] = {  # type: ignore[index]
            "url": url,
            "path": target.name,
            "size_bytes": target.stat().st_size,
        }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _extract_shapefile(archive: Path, output: Path, target_stem: str) -> None:
    with ZipFile(archive) as zipped:
        shapefiles = [name for name in zipped.namelist() if Path(name).suffix.lower() == ".shp"]
        if len(shapefiles) != 1:
            raise ValueError(f"expected one shapefile in {archive}, found {len(shapefiles)}")
        source_stem = Path(shapefiles[0]).stem
        members = [name for name in zipped.namelist() if Path(name).stem == source_stem]
        for name in members:
            suffix = Path(name).suffix.lower()
            if not suffix:
                continue
            destination = output / f"{target_stem}{suffix}"
            with zipped.open(name) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)


if __name__ == "__main__":
    raise SystemExit(main())
