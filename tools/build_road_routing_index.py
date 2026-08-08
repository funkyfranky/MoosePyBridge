"""Build the spatial index for cached GermanyCW road-routing shards."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import build_road_routing_shard_index


CACHE_DIR = REPO_ROOT / "tmp" / "topography" / "road_routing_cache"
OUTPUT = CACHE_DIR / "manifest.json"


def main() -> int:
    artifacts = tuple(CACHE_DIR.glob("*.npz"))
    if not artifacts:
        print(f"No cached road-routing shards found: {CACHE_DIR}")
        return 4
    build_road_routing_shard_index(artifacts, OUTPUT, theater_id="GermanyCW")
    print(f"Road-routing shard index written: {OUTPUT}")
    print(f"Shards: {len(artifacts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
