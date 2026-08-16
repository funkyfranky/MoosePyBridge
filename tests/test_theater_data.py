from __future__ import annotations

from pathlib import Path

import pytest

from moosebridge.theater_data import (
    DEFAULT_ARTIFACTS,
    DEFAULT_THEATER_PROFILE_PATH,
    TheaterDataProfile,
    load_theater_profile,
)


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
    assert paths.path("viewport_manifest") == paths.root / "cache" / "viewport" / "manifest.json"
    assert paths.path("infrastructure_sites") == paths.root / "runtime" / "infrastructure-sites.geojson"
    assert profile.geofabrik_sources[0].source_id == "test"


def test_profile_rejects_artifacts_outside_data_root() -> None:
    artifacts = {**DEFAULT_ARTIFACTS, "surface_regions": "../other.geojson"}

    with pytest.raises(ValueError, match="must stay below data_root"):
        TheaterDataProfile(theater_id="TestMap", artifacts=artifacts)


def test_germany_profile_preserves_existing_artifact_layout() -> None:
    profile, paths = load_theater_profile(DEFAULT_THEATER_PROFILE_PATH, project_root=Path.cwd())

    assert profile.theater_id == "GermanyCW"
    assert profile.infrastructure_reference_year == 1989
    assert profile.excluded_energy_sources == ("solar", "wind", "biogas", "battery")
    assert paths.root.as_posix().endswith("tmp/theaters/GermanyCW")
    assert paths.path("transport_infrastructure").as_posix().endswith(
        "tmp/theaters/GermanyCW/runtime/transport-infrastructure.geojson"
    )


def test_caucasus_profile_uses_an_isolated_portable_layout() -> None:
    profile_path = DEFAULT_THEATER_PROFILE_PATH.with_name("Caucasus_topography.json")
    profile, paths = load_theater_profile(profile_path, project_root=Path.cwd())

    assert profile.theater_id == "Caucasus"
    assert profile.scenario_reference_year == 2008
    assert profile.infrastructure_reference_year == 2008
    assert profile.excluded_energy_sources == ()
    assert {source.source_id for source in profile.geofabrik_sources} == {
        "armenia",
        "azerbaijan",
        "bulgaria",
        "georgia",
        "iran",
        "kazakhstan",
        "moldova",
        "romania",
        "south-fed-district",
        "north-caucasus-fed-district",
        "turkey",
        "ukraine",
    }
    assert paths.root.as_posix().endswith("tmp/theaters/Caucasus")
    assert paths.path("coverage").as_posix().endswith(
        "tmp/theaters/Caucasus/verification/coverage.geojson"
    )
