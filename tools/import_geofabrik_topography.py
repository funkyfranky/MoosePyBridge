"""Download and locally filter Geofabrik PBF extracts for one DCS theater."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge.pbf_topography import topography_from_pbf
from moosebridge.topography import feature_counts
from moosebridge.topography_coverage import TheaterTopographyCoverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a Geofabrik PBF baseline for a DCS theater")
    parser.add_argument("--config", type=Path, default=PYTHON_ROOT / "moosebridge" / "data" / "GermanyCW_topography.json")
    parser.add_argument("--download-dir", type=Path, default=REPO_ROOT / "tmp" / "topography" / "pbf")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "tmp" / "topography" / "GermanyCW.geojson")
    parser.add_argument("--coverage", type=Path, default=REPO_ROOT / "tmp" / "topography" / "GermanyCW-coverage.geojson")
    parser.add_argument("--source", action="append", dest="sources", help="Import only the named source; repeat as needed.")
    parser.add_argument("--refresh", action="store_true", help="Redownload existing PBF files.")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--include-buildings", action="store_true", help="Include individual buildings in the browser cache.")
    parser.add_argument("--simplify-meters", type=float, default=20.0, help="Topology-preserving output simplification; use 0 to disable.")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    configured_sources = config.get("geofabrik_sources")
    if not isinstance(configured_sources, list) or not configured_sources:
        raise ValueError("topography config has no geofabrik_sources")
    selected = set(args.sources or ())
    sources = [source for source in configured_sources if not selected or source.get("id") in selected]
    missing = selected - {str(source.get("id")) for source in sources}
    if missing:
        raise ValueError(f"unknown Geofabrik source(s): {', '.join(sorted(missing))}")

    args.download_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    source_dates: dict[str, str] = {}
    for source in sources:
        path, snapshot_date = _ensure_source(source, args.download_dir, refresh=args.refresh)
        paths.append(path)
        if snapshot_date:
            source_dates[path.name] = snapshot_date
    if args.download_only:
        print(f"Downloaded {len(paths)} PBF source file(s).")
        return 0

    coverage = TheaterTopographyCoverage.load(args.coverage) if args.coverage.is_file() else None
    if coverage is not None:
        bounds = coverage.bounds
        print(f"Using {len(coverage.areas)} DCS coverage zone(s): {args.coverage}")
    else:
        bounds_config = config["pilot_bounds"]
        bounds = (
            float(bounds_config["south"]), float(bounds_config["west"]),
            float(bounds_config["north"]), float(bounds_config["east"]),
        )
        print(f"WARNING: coverage file not found; using legacy pilot bounds: {args.coverage}")
    topography = topography_from_pbf(
        paths,
        theater_id=str(config["theater_id"]),
        scenario_reference_year=int(config["scenario_reference_year"]),
        bounds=bounds,
        source_snapshot_dates=source_dates,
        include_buildings=args.include_buildings,
        simplify_meters=args.simplify_meters,
        coverage=coverage,
    )
    topography.save(args.output)
    print(f"Wrote {len(topography.features)} features to {args.output}")
    for layer, count in sorted(feature_counts(topography.features).items()):
        print(f"  {layer}: {count}")
    return 0


def _ensure_source(source: dict[str, object], directory: Path, *, refresh: bool) -> tuple[Path, str | None]:
    source_id = str(source.get("id") or "")
    url = str(source.get("url") or "")
    if not source_id or not url:
        raise ValueError("Geofabrik source requires id and url")
    filename = url.rsplit("/", 1)[-1]
    target = directory / filename
    metadata_path = target.with_suffix(f"{target.suffix}.metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    if refresh or not target.is_file():
        headers = _download(url, target)
        expected_md5 = _download_md5(f"{url}.md5")
        actual_md5 = _file_md5(target)
        if actual_md5.lower() != expected_md5.lower():
            raise ValueError(f"MD5 mismatch for {target.name}: expected {expected_md5}, got {actual_md5}")
        metadata = {
            "source_id": source_id,
            "url": url,
            "downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_last_modified": headers.get("Last-Modified"),
            "md5": actual_md5,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"PBF {source_id}: {target} ({target.stat().st_size / 1024 / 1024:.1f} MiB)", flush=True)
    return target, _http_date_to_iso(metadata.get("source_last_modified"))


def _download(url: str, target: Path) -> dict[str, str]:
    partial = target.with_suffix(f"{target.suffix}.part")
    offset = partial.stat().st_size if partial.is_file() else 0
    headers = {"User-Agent": "MoosePyBridge-topography-import/0.1"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=120) as response:
        append = offset > 0 and getattr(response, "status", None) == 206
        mode = "ab" if append else "wb"
        if not append:
            offset = 0
        total = response.headers.get("Content-Length")
        expected = offset + int(total) if total else None
        written = offset
        with partial.open(mode) as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                written += len(chunk)
                if written % (25 * 1024 * 1024) < len(chunk):
                    suffix = f"/{expected / 1024 / 1024:.0f}" if expected else ""
                    print(f"  {target.name}: {written / 1024 / 1024:.0f}{suffix} MiB", flush=True)
        response_headers = dict(response.headers.items())
    partial.replace(target)
    return response_headers


def _download_md5(url: str) -> str:
    request = Request(url, headers={"User-Agent": "MoosePyBridge-topography-import/0.1"})
    with urlopen(request, timeout=60) as response:
        value = response.read().decode("ascii", errors="strict").strip().split()[0]
    if len(value) != 32:
        raise ValueError(f"invalid MD5 response from {url}")
    return value


def _file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _http_date_to_iso(value: object) -> str | None:
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    return parsedate_to_datetime(str(value)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
