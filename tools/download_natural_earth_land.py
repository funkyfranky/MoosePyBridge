"""Download the pinned Natural Earth land baseline used by surface regions."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS = {
    "ne_10m_land": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip",
    "ne_10m_minor_islands": "https://naciscdn.org/naturalearth/10m/physical/ne_10m_minor_islands.zip",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Natural Earth 1:10m land polygons")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "tmp" / "topography" / "naturalearth",
    )
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    for dataset, url in DATASETS.items():
        target = args.output / f"{dataset}.shp"
        if target.is_file() and not args.refresh:
            print(f"Reusing {target}")
            continue
        print(f"Downloading {url}", flush=True)
        with tempfile.TemporaryDirectory(prefix="moosebridge-natural-earth-") as temporary:
            archive = Path(temporary) / f"{dataset}.zip"
            with urlopen(url, timeout=60) as response, archive.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            with ZipFile(archive) as zipped:
                members = [name for name in zipped.namelist() if Path(name).name.startswith(f"{dataset}.")]
                if not any(Path(name).suffix.lower() == ".shp" for name in members):
                    raise ValueError(f"downloaded archive contains no {dataset} shapefile")
                for name in members:
                    destination = args.output / Path(name).name
                    with zipped.open(name) as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
        print(f"Wrote {dataset} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
