"""Capture DCS mission zones that define offline topography detail coverage.

Create zones named `Topography All`, `Topography Low ...`, and
`Topography High ...` in the mission editor. Multiple zones per level are
allowed. The daemon and DCS mission are assumed to be running.
"""

from __future__ import annotations

import argparse

from example_support import REPO_ROOT, open_example_session, run_example

from moosebridge import DEFAULT_THEATER_PROFILE_PATH, TopographyDetailLevel, coverage_from_picture, load_theater_profile
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH


async def run(profile_path=THEATER_PROFILE) -> int:
    profile, paths = load_theater_profile(profile_path, project_root=REPO_ROOT)
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge
    picture = await bridge.refresh_global_picture()
    coverage = coverage_from_picture(picture.to_geojson(), theater_id=profile.theater_id)
    output_path = paths.path("coverage")
    coverage.save(output_path)

    print(f"Topography coverage written: {output_path}")
    print(f"Bounds: south={coverage.bounds[0]:.5f} west={coverage.bounds[1]:.5f} north={coverage.bounds[2]:.5f} east={coverage.bounds[3]:.5f}")
    for level in TopographyDetailLevel:
        areas = [area for area in coverage.areas if area.level is level]
        print(f"  {level.value}: {len(areas)} zone(s)")
        for area in areas:
            print(f"    {area.object_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=THEATER_PROFILE)
    args = parser.parse_args()
    return run_example(lambda: run(args.profile))


if __name__ == "__main__":
    raise SystemExit(main())
