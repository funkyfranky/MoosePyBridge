from __future__ import annotations

from moosebridge.infrastructure_sites import (
    EnergySite,
    EnergySource,
    InfrastructureSiteKind,
    MilitarySite,
    TheaterInfrastructureSites,
    build_energy_sites,
    infrastructure_policy_for_theater,
)
from moosebridge.topography import TopographyFeature, TopographyLayer


def _plant(name: str, source: str) -> TopographyFeature:
    return TopographyFeature(
        object_id=f"TOPOGRAPHY:plant:{name}",
        layer=TopographyLayer.INFRASTRUCTURE,
        category="power_plant",
        geometry={"type": "Point", "coordinates": [12.0, 54.0]},
        source="OpenStreetMap",
        source_id=f"way/{name}",
        confidence=0.8,
        name=name,
        properties={
            "osm_tags": {
                "plant:source": source,
                "plant:output:electricity": "250 MW",
            }
        },
    )


def test_germany_cw_policy_excludes_modern_energy_sources_only() -> None:
    artifact = build_energy_sites(
        [_plant("coal", "coal"), _plant("wind", "wind"), _plant("solar", "solar")],
        theater_id="GermanyCW",
    )

    assert [site.name for site in artifact.sites] == ["coal"]
    assert artifact.metadata["excluded_energy_source_counts"] == {"solar": 1, "wind": 1}
    site = artifact.sites[0]
    assert isinstance(site, EnergySite)
    assert site.energy_sources == (EnergySource.COAL,)
    assert site.output_mw == 250


def test_other_theaters_can_include_wind_power() -> None:
    artifact = build_energy_sites([_plant("wind", "wind")], theater_id="Kola")

    assert len(artifact.sites) == 1
    assert artifact.sites[0].scenario_reference_year is None
    assert not infrastructure_policy_for_theater("Kola").excluded_energy_sources


def test_military_site_is_a_distinct_site_type() -> None:
    site = MilitarySite(
        site_id="MILITARY_SITE:test",
        kind=InfrastructureSiteKind.MILITARY,
        geometry={"type": "Point", "coordinates": [12.0, 54.0]},
        latitude=54.0,
        longitude=12.0,
        source="mission author",
        confidence=1.0,
        roles=("barracks", "depot"),
    )

    properties = site.to_geojson_feature()["properties"]
    assert properties["object_type"] == "MILITARY_SITE"
    assert properties["roles"] == ["barracks", "depot"]


def test_infrastructure_artifact_round_trips_typed_sites(tmp_path) -> None:
    artifact = build_energy_sites([_plant("coal", "coal")], theater_id="GermanyCW")
    path = artifact.save(tmp_path / "sites.geojson")

    loaded = TheaterInfrastructureSites.load(path)

    assert loaded == artifact
    assert isinstance(loaded.sites[0], EnergySite)
    assert loaded.sites[0].to_geojson_feature()["properties"]["layer"] == "energy_sites"
