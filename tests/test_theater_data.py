from __future__ import annotations

from pathlib import Path

import pytest

from moosebridge.map_server import GlobalMapRuntime
from moosebridge.theater_data import (
    DEFAULT_ARTIFACTS,
    DEFAULT_THEATER_PROFILE_PATH,
    TheaterDataProfile,
    load_theater_profile,
)
from moosebridge.topography import TheaterTopography


def test_profile_resolves_portable_default_layout(tmp_path: Path) -> None:
    profile = TheaterDataProfile.from_dict(
        {
            "schema_version": 1,
            "theater_id": "TestMap",
            "scenario_reference_year": 1985,
            "pilot_bounds": {"south": 10, "west": 20, "north": 11, "east": 21},
            "geofabrik_sources": [
                {"id": "test", "url": "https://download.example/test-latest.osm.pbf"}
            ],
        }
    )

    paths = profile.paths(project_root=tmp_path)

    assert paths.root == (tmp_path / "tmp" / "theaters" / "TestMap").resolve()
    assert paths.path("topography") == paths.root / "TestMap.geojson"
    assert paths.path("viewport_manifest") == paths.root / "viewport" / "manifest.json"
    assert profile.geofabrik_sources[0].source_id == "test"


def test_profile_rejects_artifacts_outside_data_root() -> None:
    artifacts = {**DEFAULT_ARTIFACTS, "topography": "../other.geojson"}

    with pytest.raises(ValueError, match="must stay below data_root"):
        TheaterDataProfile(theater_id="TestMap", artifacts=artifacts)


def test_germany_profile_preserves_existing_artifact_layout() -> None:
    profile, paths = load_theater_profile(DEFAULT_THEATER_PROFILE_PATH, project_root=Path.cwd())

    assert profile.theater_id == "GermanyCW"
    assert profile.infrastructure_reference_year == 1989
    assert profile.excluded_energy_sources == ("solar", "wind", "biogas", "battery")
    assert paths.path("topography").as_posix().endswith("tmp/topography/GermanyCW.geojson")
    assert paths.path("transport_infrastructure").as_posix().endswith(
        "tmp/topography/GermanyCW-transport-infrastructure.geojson"
    )


def test_map_runtime_rejects_artifact_from_another_theater(tmp_path: Path) -> None:
    topography_path = TheaterTopography(theater_id="OtherMap").save(tmp_path / "other.geojson")

    with pytest.raises(ValueError, match="theater artifact mismatch"):
        GlobalMapRuntime(theater_id="ExpectedMap", topography_path=topography_path)


def test_map_runtime_accepts_matching_theater_artifact(tmp_path: Path) -> None:
    topography_path = TheaterTopography(theater_id="ExpectedMap").save(tmp_path / "expected.geojson")

    runtime = GlobalMapRuntime(theater_id="ExpectedMap", topography_path=topography_path)

    assert runtime.topography_geojson()["properties"]["theater_id"] == "ExpectedMap"
