"""Convert checkpointed topography GeoJSON shards to indexed FlatGeobuf."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "cache" / "import"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "cache" / "viewport"
KEY_PATTERN = re.compile(r"-([0-9a-f]{12})\.geojson$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an indexed topography viewport cache")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--theater-id", default="GermanyCW")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    try:
        import pyogrio
    except ImportError as exc:
        raise SystemExit('Topography dependencies are missing. Run: python -m pip install -e ".[topography]"') from exc

    sources = list(args.input.glob("*.geojson"))
    keys = Counter(match.group(1) for path in sources if (match := KEY_PATTERN.search(path.name)))
    if not keys:
        raise FileNotFoundError(f"no versioned topography checkpoints found in {args.input}")
    cache_key, _ = keys.most_common(1)[0]
    sources = sorted(path for path in sources if path.name.endswith(f"-{cache_key}.geojson"))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.json"
    previous = _load_manifest(manifest_path)
    previous_by_source = {item.get("source_path"): item for item in previous.get("shards") or []}
    shards: list[dict[str, object]] = []
    theater_id = args.theater_id
    for index, source in enumerate(sources, start=1):
        relative_source = source.relative_to(REPO_ROOT).as_posix()
        stat = source.stat()
        output_name = f"{source.name.removesuffix('.geojson')}.fgb"
        output_path = args.output / output_name
        cached = previous_by_source.get(relative_source)
        if (
            not args.refresh
            and output_path.is_file()
            and cached
            and cached.get("source_size") == stat.st_size
            and cached.get("source_mtime_ns") == stat.st_mtime_ns
        ):
            print(f"[{index}/{len(sources)}] reuse {output_name}", flush=True)
            shards.append(cached)
            continue
        print(f"[{index}/{len(sources)}] convert {source.name}", flush=True)
        frame = pyogrio.read_dataframe(source)
        if frame.empty:
            continue
        if output_path.exists():
            output_path.unlink()
        pyogrio.write_dataframe(frame, output_path, driver="FlatGeobuf", spatial_index=True)
        bounds = [float(value) for value in frame.total_bounds]
        shards.append(
            {
                "path": output_name,
                "source_path": relative_source,
                "source_size": stat.st_size,
                "source_mtime_ns": stat.st_mtime_ns,
                "bounds": bounds,
                "feature_count": len(frame),
                "layers": sorted(str(value) for value in frame["layer"].dropna().unique()),
                "detail_levels": sorted(str(value) for value in frame["detail_level"].dropna().unique()),
            }
        )
    payload = {
        "schema": "moosebridge.topography_viewport",
        "schema_version": 1,
        "theater_id": theater_id,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "conversion_cache_key": cache_key,
        "source_count": len(sources),
        "shard_count": len(shards),
        "feature_count": sum(int(item["feature_count"]) for item in shards),
        "shards": shards,
    }
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    print(f"Wrote {payload['feature_count']} indexed features in {len(shards)} shard(s) to {manifest_path}")
    return 0


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    raise SystemExit(main())
