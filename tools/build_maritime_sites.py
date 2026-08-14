"""Rebuild maritime sites from the indexed topography infrastructure cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from build_infrastructure_sites import _load_candidates  # noqa: E402
from moosebridge import (  # noqa: E402
    IndustrialRole,
    IndustrialSite,
    MaritimeSite,
    TheaterInfrastructureSites,
    build_maritime_sites,
)


DEFAULT_MANIFEST = REPO_ROOT / "tmp" / "topography" / "viewport" / "manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "topography" / "GermanyCW-infrastructure-sites.geojson"


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild normalized maritime sites from the viewport cache")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    theater_id = str(payload.get("theater_id") or "")
    features = _load_candidates(args.manifest.parent, payload.get("shards") or [])
    maritime = build_maritime_sites(features.values(), theater_id=theater_id)

    if args.output.is_file():
        existing = TheaterInfrastructureSites.load(args.output)
        retained = tuple(
            site for site in existing.sites
            if not isinstance(site, MaritimeSite)
            and not (isinstance(site, IndustrialSite) and IndustrialRole.SHIPYARD in site.roles)
        )
        metadata = {**existing.metadata, "maritime": maritime.metadata}
    else:
        retained = ()
        metadata = {"maritime": maritime.metadata}

    artifact = TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=maritime.scenario_reference_year,
        sites=(*retained, *maritime.sites),
        metadata=metadata,
    )
    output = artifact.save(args.output)
    strategic_count = sum(bool(site.properties.get("strategic_candidate")) for site in maritime.sites)
    print(f"Maritime sites written: {output}")
    print(f"  raw indexed candidates: {len(features)}")
    print(f"  admitted maritime sites: {len(maritime.sites)}")
    print(f"  strategic candidates: {strategic_count}")
    print(f"  retained non-maritime sites: {len(retained)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
