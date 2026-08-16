"""Validate strategic GermanyCW ground connectivity at theater boundaries."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge import GroundMobilityNetwork, TRACKED_GROUND_PROFILE, format_ground_route


DEFAULT_NETWORK = REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "runtime" / "ground-mobility.json"
MAINLAND = (54.3090, 13.0670)
RUGEN = (54.4180, 13.4330)
BORNHOLM = (55.1000, 14.7060)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the Rugen bridge connection and Bornholm isolation",
    )
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    args = parser.parse_args()

    network = GroundMobilityNetwork.load(args.network)
    rugen = network.route(*MAINLAND, *RUGEN, profile=TRACKED_GROUND_PROFILE)
    bornholm = network.route(*MAINLAND, *BORNHOLM, profile=TRACKED_GROUND_PROFILE)

    print("GermanyCW strategic ground connectivity")
    print("=" * 80)
    print(f"Network : {args.network.resolve()}")
    print(f"Rugen   : {format_ground_route(rugen)}")
    print(f"Bornholm: {format_ground_route(bornholm)}")

    failures: list[str] = []
    if rugen is None:
        failures.append("mainland -> Rugen is disconnected")
    elif rugen.bridge_count < 1:
        failures.append("mainland -> Rugen contains no detected bridge crossing")
    if bornholm is not None:
        failures.append("mainland -> Bornholm unexpectedly has a strategic ground route")

    if failures:
        print("\nFAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nPASSED: Rugen is bridge-connected and Bornholm remains disconnected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
