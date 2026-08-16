"""Inspect and build one profile-driven DCS theater dataset."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge.theater_data import (  # noqa: E402
    DEFAULT_THEATER_PROFILE_PATH,
    MAP_ARTIFACT_KEYS,
    TheaterDataPaths,
    TheaterDataProfile,
    load_theater_profile,
)


@dataclass(slots=True, frozen=True)
class WorkflowStage:
    name: str
    description: str
    command: tuple[str, ...]


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile-driven DCS theater data workflow")
    parser.add_argument("--profile", type=Path, default=DEFAULT_THEATER_PROFILE_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Validate the profile and report available artifacts.")
    subparsers.add_parser("plan", help="Print the reproducible build order and commands.")
    build = subparsers.add_parser("build", help="Run one build stage or the complete workflow.")
    build.add_argument("--stage", action="append", help="Stage name; repeat as needed. Default: all.")
    build.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    args = parser.parse_args()

    profile, paths = load_theater_profile(args.profile, project_root=REPO_ROOT)
    stages = workflow_stages(profile, paths)
    if args.command == "status":
        return print_status(profile, paths)
    if args.command == "plan":
        print_plan(profile, stages)
        return 0

    selected = set(args.stage or (stage.name for stage in stages))
    unknown = sorted(selected.difference(stage.name for stage in stages))
    if unknown:
        raise SystemExit(f"Unknown stage(s): {', '.join(unknown)}")
    for stage in stages:
        if stage.name not in selected:
            continue
        print(f"\n[{stage.name}] {stage.description}", flush=True)
        print(_format_command(stage.command), flush=True)
        if args.dry_run:
            continue
        completed = subprocess.run(stage.command, cwd=REPO_ROOT, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


def workflow_stages(profile: TheaterDataProfile, paths: TheaterDataPaths) -> tuple[WorkflowStage, ...]:
    """Return the ordered, explicit commands for one theater build."""

    python = sys.executable
    config = str(profile.profile_path or DEFAULT_THEATER_PROFILE_PATH)
    p = lambda key: str(paths.path(key))
    return (
        WorkflowStage(
            "coverage",
            "Capture mission-editor Topography zones from a running DCS mission.",
            (python, "examples/sdk/capture_topography_coverage.py", "--profile", config),
        ),
        WorkflowStage(
            "import",
            "Download and normalize the configured Geofabrik sources into reusable shards.",
            (python, "tools/import_geofabrik_topography.py", "--config", config,
             "--download-dir", p("pbf_directory"), "--cache-dir", p("import_cache"),
             "--coverage", p("coverage")),
        ),
        WorkflowStage(
            "viewport",
            "Build the bounded browser-map viewport index.",
            (python, "tools/build_topography_viewport_cache.py", "--input", p("import_cache"),
             "--output", str(paths.path("viewport_manifest").parent), "--theater-id", profile.theater_id),
        ),
        WorkflowStage(
            "surfaces",
            "Build connected land and water regions.",
            (python, "tools/build_surface_regions.py", "--config", config,
             "--output", p("surface_regions"), "--import-cache", p("import_cache"),
             "--surface-source-output", p("surface_source"),
             "--osm-land", str(paths.path("osmcoastline_directory") / "land_polygons.shp"),
             "--osm-water", str(paths.path("osmcoastline_directory") / "water_polygons.shp")),
        ),
        WorkflowStage(
            "road-routing",
            "Build the unrestricted military road-routing graph.",
            (python, "tools/build_road_routing.py", "--config", config, "--coverage", p("coverage"),
             "--pbf-dir", p("pbf_directory"), "--cache-dir", p("road_routing_cache"),
             "--output", p("road_routing"), "--theater", profile.theater_id),
        ),
        WorkflowStage(
            "ground-mobility",
            "Build the strategic ground-mobility graph.",
            (python, "tools/build_ground_mobility.py", "--manifest", p("viewport_manifest"),
             "--surfaces", p("surface_regions"), "--output", p("ground_mobility")),
        ),
        WorkflowStage(
            "transport",
            "Aggregate bridges and strategic road junctions.",
            (python, "tools/build_transport_infrastructure.py", "--input", p("road_routing"),
             "--output", p("transport_infrastructure")),
        ),
        WorkflowStage(
            "settlements",
            "Normalize cities and towns with administrative boundaries.",
            (python, "tools/build_settlements.py", "--manifest", p("viewport_manifest"),
             "--output", p("settlements"), "--config", config, "--pbf-dir", p("pbf_directory"),
             "--admin-cache-dir", p("administrative_boundary_cache")),
        ),
        WorkflowStage(
            "railway",
            "Aggregate railway facilities and routing data.",
            (python, "tools/build_railway_infrastructure.py", "--manifest", p("viewport_manifest"),
             "--config", config, "--pbf-dir", p("pbf_directory"), "--coverage", p("coverage"),
             "--output", p("railway_infrastructure"), "--routing-output", p("railway_routing"),
             "--facility-cache", p("railway_facility_cache")),
        ),
        WorkflowStage(
            "infrastructure",
            "Normalize energy, fuel, military, industrial, and maritime candidates.",
            (python, "tools/build_infrastructure_sites.py", "--profile", config,
             "--manifest", p("viewport_manifest"), "--output", p("infrastructure_sites"),
             "--pbf-directory", p("pbf_directory")),
        ),
        WorkflowStage(
            "maritime",
            "Refresh maritime logistics while retaining other infrastructure sites.",
            (python, "tools/build_maritime_sites.py", "--manifest", p("viewport_manifest"),
             "--output", p("infrastructure_sites")),
        ),
    )


def print_status(profile: TheaterDataProfile, paths: TheaterDataPaths) -> int:
    print(f"Theater data: {profile.display_name or profile.theater_id}")
    print(f"ID          : {profile.theater_id}")
    print(f"Profile     : {profile.profile_path}")
    print(f"Data root   : {paths.root}")
    print(f"Scenario    : {profile.scenario_reference_year or '-'}")
    print(f"Sources     : {len(profile.geofabrik_sources)} Geofabrik extract(s)")
    print("\nMap artifacts")
    print("=" * 88)
    missing = 0
    for key in MAP_ARTIFACT_KEYS:
        path = paths.path(key)
        exists = path.is_file()
        missing += not exists
        size = f"{path.stat().st_size / (1024 * 1024):.1f} MiB" if exists else "missing"
        print(f"{key:28} {size:>12}  {path}")
    manifest = paths.path("viewport_manifest")
    if manifest.is_file():
        import json
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        actual = str(payload.get("theater_id") or "")
        if actual.casefold() != profile.theater_id.casefold():
            print(f"\nERROR: viewport manifest belongs to {actual or '<missing>'}")
            return 2
    print(f"\nStatus: {len(MAP_ARTIFACT_KEYS) - missing}/{len(MAP_ARTIFACT_KEYS)} map artifacts available")
    return 0


def print_plan(profile: TheaterDataProfile, stages: Iterable[WorkflowStage]) -> None:
    print(f"Theater build plan: {profile.theater_id}")
    print("Run individual stages with: python tools/theater_workflow.py build --stage <name>")
    for index, stage in enumerate(stages, start=1):
        print(f"\n{index:2}. {stage.name}: {stage.description}")
        print(f"    {_format_command(stage.command)}")


def _format_command(command: Iterable[str]) -> str:
    return subprocess.list2cmdline(list(command))


if __name__ == "__main__":
    raise SystemExit(main())
