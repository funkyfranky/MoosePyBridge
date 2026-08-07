"""Import a bounded OpenStreetMap baseline into a MooseBridge theater cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge.osm_topography import build_overpass_query, topography_from_overpass
from moosebridge.topography import feature_counts

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import an OSM baseline for a DCS theater")
    parser.add_argument("--config", type=Path, default=PYTHON_ROOT / "moosebridge" / "data" / "GermanyCW_topography.json")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "tmp" / "topography" / "GermanyCW.geojson")
    parser.add_argument("--raw-cache", type=Path, default=REPO_ROOT / "tmp" / "topography" / "osm_raw" / "GermanyCW")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--tile-degrees", type=float, default=0.5)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--refresh", action="store_true", help="Download tiles even when a raw response is cached.")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    bounds_config = config["pilot_bounds"]
    bounds = (
        float(bounds_config["south"]), float(bounds_config["west"]),
        float(bounds_config["north"]), float(bounds_config["east"]),
    )
    tiles = list(_tiles(bounds, max(0.1, args.tile_degrees)))
    args.raw_cache.mkdir(parents=True, exist_ok=True)
    payloads = []
    for index, tile in enumerate(tiles, start=1):
        cache_file = args.raw_cache / _tile_name(tile)
        if cache_file.exists() and not args.refresh:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            origin = "cache"
        else:
            payload = _download(args.endpoint, build_overpass_query(tile), retries=max(1, args.retries))
            cache_file.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            origin = "download"
            if index < len(tiles):
                time.sleep(max(0.0, args.request_delay))
        payloads.append(payload)
        print(
            f"[{index:02d}/{len(tiles):02d}] {origin}: {cache_file.name} elements={len(payload.get('elements', []))}",
            flush=True,
        )

    topography = topography_from_overpass(
        payloads,
        theater_id=str(config["theater_id"]),
        reference_year=int(config["reference_year"]),
        bounds=bounds,
    )
    topography.save(args.output)
    print(f"Wrote {len(topography.features)} features to {args.output}")
    for layer, count in sorted(feature_counts(topography.features).items()):
        print(f"  {layer}: {count}")
    return 0


def _download(endpoint: str, query: str, *, retries: int) -> dict[str, object]:
    body = urlencode({"data": query}).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"User-Agent": "MoosePyBridge-topography-import/0.1", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=240) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in {429, 500, 502, 503, 504}
            if attempt >= retries or not retryable:
                raise
            delay = min(30.0, 2.0 ** attempt)
            print(f"  Overpass request failed ({exc}); retrying in {delay:.0f}s", flush=True)
            time.sleep(delay)
    raise RuntimeError("unreachable Overpass retry state")


def _tiles(
    bounds: tuple[float, float, float, float],
    size: float,
):
    south, west, north, east = bounds
    latitude = south
    while latitude < north:
        longitude = west
        tile_north = min(north, latitude + size)
        while longitude < east:
            tile_east = min(east, longitude + size)
            yield latitude, longitude, tile_north, tile_east
            longitude = tile_east
        latitude = tile_north


def _tile_name(bounds: tuple[float, float, float, float]) -> str:
    return "_".join(f"{value:.3f}".replace("-", "m").replace(".", "p") for value in bounds) + ".json"


if __name__ == "__main__":
    raise SystemExit(main())
