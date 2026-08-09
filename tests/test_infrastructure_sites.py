from __future__ import annotations

from moosebridge.infrastructure_sites import (
    EnergySite,
    EnergySource,
    FuelStorageRole,
    FuelStorageSite,
    InfrastructureSiteKind,
    MilitaryRole,
    MilitarySite,
    StoredCommodity,
    TheaterInfrastructureSites,
    build_energy_sites,
    build_fuel_storage_sites,
    build_infrastructure_sites,
    build_military_sites,
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


def _fuel_feature(
    name: str,
    category: str,
    longitude: float,
    latitude: float,
    **tags: str,
) -> TopographyFeature:
    return TopographyFeature(
        object_id=f"TOPOGRAPHY:fuel:{name}",
        layer=TopographyLayer.INFRASTRUCTURE,
        category=category,
        geometry={"type": "Point", "coordinates": [longitude, latitude]},
        source="OpenStreetMap",
        source_id=f"way/{name}",
        confidence=0.75,
        name=name,
        properties={"osm_tags": tags},
    )


def _military_feature(
    name: str | None,
    longitude: float,
    latitude: float,
    *,
    military: str | None = None,
    valid_from: int | None = None,
    source_suffix: str | None = None,
    **tags: str,
) -> TopographyFeature:
    source = source_suffix or name or f"{longitude}-{latitude}"
    osm_tags = {"landuse": "military", **tags}
    if military is not None:
        osm_tags["military"] = military
    return TopographyFeature(
        object_id=f"TOPOGRAPHY:military:{source}",
        layer=TopographyLayer.LANDUSE,
        category="military",
        geometry={"type": "Point", "coordinates": [longitude, latitude]},
        source="OpenStreetMap",
        source_id=f"way/{source}",
        confidence=0.5,
        name=name,
        valid_from=valid_from,
        properties={"osm_tags": osm_tags},
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
        roles=(MilitaryRole.BARRACKS, MilitaryRole.DEPOT),
    )

    properties = site.to_geojson_feature()["properties"]
    assert properties["object_type"] == "MILITARY_SITE"
    assert properties["roles"] == ["barracks", "depot"]


def test_military_builder_keeps_operational_sites_but_not_airfields_or_minor_areas() -> None:
    artifact = build_military_sites(
        [
            _military_feature("Alpha Barracks", 12.0, 54.0, military="barracks"),
            _military_feature("DCS Airbase", 12.1, 54.0, military="airfield", aeroway="aerodrome"),
            _military_feature("Danger Area", 12.2, 54.0, military="danger_area"),
            _military_feature(None, 12.3, 54.0, military="bunker"),
        ],
        theater_id="GermanyCW",
    )

    assert len(artifact.sites) == 1
    site = artifact.sites[0]
    assert isinstance(site, MilitarySite)
    assert site.roles == (MilitaryRole.BARRACKS,)
    assert site.properties["targetable_candidate"] is True
    assert artifact.metadata["excluded_military_counts"] == {
        "airfield": 1,
        "non_site_role": 1,
        "ambiguous": 0,
        "outside_scenario_date": 0,
        "unnamed_bunker": 1,
    }


def test_military_builder_infers_named_sites_and_excludes_post_scenario_construction() -> None:
    artifact = build_military_sites(
        [
            _military_feature("Munitionsdepot Alpha", 12.0, 54.0),
            _military_feature("Radarstellung Bravo", 12.1, 54.0),
            _military_feature("Neue Kaserne", 12.2, 54.0, military="barracks", valid_from=2005),
            _military_feature("Unknown fenced area", 12.3, 54.0),
        ],
        theater_id="GermanyCW",
    )

    assert [(site.name, site.roles) for site in artifact.sites] == [
        ("Munitionsdepot Alpha", (MilitaryRole.AMMUNITION_STORAGE,)),
        ("Radarstellung Bravo", (MilitaryRole.RADAR_SITE,)),
    ]
    assert artifact.metadata["excluded_military_counts"]["outside_scenario_date"] == 1
    assert artifact.metadata["excluded_military_counts"]["ambiguous"] == 1


def test_military_builder_clusters_split_named_installations_without_transitive_chaining() -> None:
    artifact = build_military_sites(
        [
            _military_feature("Camp Alpha", 12.0, 54.0, military="base", source_suffix="a"),
            _military_feature("Camp Alpha", 12.005, 54.0, military="depot", source_suffix="b"),
            _military_feature("Camp Alpha", 12.020, 54.0, military="barracks", source_suffix="c"),
        ],
        theater_id="GermanyCW",
        named_cluster_radius_m=1_000,
    )

    assert len(artifact.sites) == 2
    assert artifact.sites[0].roles == (MilitaryRole.BASE, MilitaryRole.DEPOT)
    assert artifact.sites[0].properties["member_count"] == 2


def test_fuel_storage_requires_explicit_commodity_evidence() -> None:
    artifact = build_fuel_storage_sites(
        [
            _fuel_feature("unknown", "storage_tank", 12.0, 54.0, man_made="storage_tank"),
            _fuel_feature("water", "storage_tank", 12.01, 54.0, man_made="storage_tank", content="water"),
            _fuel_feature(
                "diesel", "storage_tank", 12.02, 54.0,
                man_made="storage_tank", content="diesel", capacity="1000 m3",
            ),
        ],
        theater_id="GermanyCW",
    )

    assert len(artifact.sites) == 1
    site = artifact.sites[0]
    assert isinstance(site, FuelStorageSite)
    assert site.commodities == (StoredCommodity.DIESEL,)
    assert site.storage_roles == (FuelStorageRole.TANK_FARM,)
    assert artifact.metadata["excluded_unknown_tank_count"] == 2


def test_generic_oil_or_gas_industry_is_not_assumed_to_be_storage() -> None:
    artifact = build_fuel_storage_sites(
        [
            _fuel_feature("oil works", "oil", 11.8, 54.0, industrial="oil"),
            _fuel_feature("distribution", "gas", 12.0, 54.0, industrial="gas"),
            _fuel_feature("cavern", "gas_storage", 12.2, 54.0, industrial="gas_storage"),
        ],
        theater_id="GermanyCW",
    )

    assert [site.name for site in artifact.sites] == ["cavern"]
    assert artifact.metadata["excluded_ambiguous_facility_count"] == 2


def test_fuel_tanks_are_components_of_nearby_explicit_terminal() -> None:
    artifact = build_fuel_storage_sites(
        [
            _fuel_feature(
                "terminal", "oil", 12.0, 54.0,
                industrial="oil", storage="terminal", operator="Example Fuel",
            ),
            _fuel_feature("tank-a", "storage_tank", 12.002, 54.0, content="fuel", capacity="1000 m3"),
            _fuel_feature("tank-b", "storage_tank", 12.003, 54.0, content="diesel", capacity="500000 l"),
        ],
        theater_id="GermanyCW",
    )

    assert len(artifact.sites) == 1
    site = artifact.sites[0]
    assert isinstance(site, FuelStorageSite)
    assert site.name == "terminal"
    assert site.capacity_m3 == 1500
    assert site.properties["member_count"] == 3
    assert site.storage_roles == (FuelStorageRole.TANK_FARM, FuelStorageRole.TERMINAL)
    assert site.commodities == (StoredCommodity.DIESEL, StoredCommodity.PETROLEUM)


def test_infrastructure_artifact_round_trips_typed_sites(tmp_path) -> None:
    artifact = build_infrastructure_sites(
        [_plant("coal", "coal"), _fuel_feature("depot", "oil_storage", 12.2, 54.1, industrial="oil_storage")],
        theater_id="GermanyCW",
    )
    path = artifact.save(tmp_path / "sites.geojson")

    loaded = TheaterInfrastructureSites.load(path)

    assert loaded == artifact
    assert isinstance(loaded.sites[0], EnergySite)
    assert isinstance(loaded.sites[1], FuelStorageSite)
    assert loaded.sites[0].to_geojson_feature()["properties"]["layer"] == "energy_sites"
    assert loaded.sites[1].to_geojson_feature()["properties"]["layer"] == "fuel_storage_sites"
