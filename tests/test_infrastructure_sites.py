from __future__ import annotations

from moosebridge.infrastructure_sites import (
    EnergySite,
    EnergySource,
    FuelStorageRole,
    FuelStorageSite,
    InfrastructureSiteKind,
    IndustrialRole,
    IndustrialSite,
    MilitaryRole,
    MilitarySite,
    StoredCommodity,
    TheaterInfrastructureSites,
    build_energy_sites,
    build_fuel_storage_sites,
    build_infrastructure_sites,
    build_industrial_sites,
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
    size_degrees: float = 0.001,
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
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [longitude - size_degrees, latitude - size_degrees],
                [longitude + size_degrees, latitude - size_degrees],
                [longitude + size_degrees, latitude + size_degrees],
                [longitude - size_degrees, latitude + size_degrees],
                [longitude - size_degrees, latitude - size_degrees],
            ]],
        },
        source="OpenStreetMap",
        source_id=f"way/{source}",
        confidence=0.5,
        name=name,
        valid_from=valid_from,
        properties={"osm_tags": osm_tags},
    )


def _industrial_feature(
    name: str | None,
    category: str,
    longitude: float,
    latitude: float,
    *,
    size_degrees: float = 0.001,
    valid_from: int | None = None,
    source_suffix: str | None = None,
    **tags: str,
) -> TopographyFeature:
    source = source_suffix or name or f"{longitude}-{latitude}"
    return TopographyFeature(
        object_id=f"TOPOGRAPHY:industrial:{source}",
        layer=TopographyLayer.INFRASTRUCTURE,
        category=category,
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [longitude, latitude],
                [longitude + size_degrees, latitude],
                [longitude + size_degrees, latitude + size_degrees],
                [longitude, latitude + size_degrees],
                [longitude, latitude],
            ]],
        },
        source="OpenStreetMap",
        source_id=f"way/{source}",
        confidence=0.55,
        name=name,
        valid_from=valid_from,
        properties={"osm_tags": tags},
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
    assert properties["importance_score"] == 0
    assert properties["importance_tier"] == "local"


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
    assert artifact.sites[0].geometry["type"] == "MultiPolygon"
    assert artifact.sites[0].footprint_area_m2 > 0
    assert artifact.sites[0].importance_score >= 60
    assert artifact.sites[0].importance_tier.value == "high"


def test_military_builder_fills_internal_footprint_holes() -> None:
    feature = _military_feature("Core Base", 12.0, 54.0, military="base")
    feature = TopographyFeature(
        object_id=feature.object_id,
        layer=feature.layer,
        category=feature.category,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [[11.99, 53.99], [12.01, 53.99], [12.01, 54.01], [11.99, 54.01], [11.99, 53.99]],
                [[11.999, 53.999], [12.001, 53.999], [12.001, 54.001], [11.999, 54.001], [11.999, 53.999]],
            ],
        },
        source=feature.source,
        source_id=feature.source_id,
        confidence=feature.confidence,
        name=feature.name,
        properties=feature.properties,
    )

    site = build_military_sites((feature,), theater_id="GermanyCW").sites[0]

    from shapely.geometry import shape

    footprint = shape(site.geometry)
    assert footprint.geom_type == "Polygon"
    assert len(footprint.interiors) == 0
    assert site.properties["geometry_method"] == "hole_free_union_of_source_components"


def test_large_training_area_remains_context_in_importance_ranking() -> None:
    site = build_military_sites(
        [_military_feature("Training Alpha", 12.0, 54.0, military="training_area", size_degrees=0.2)],
        theater_id="GermanyCW",
    ).sites[0]

    assert site.properties["targetable_candidate"] is False
    assert site.importance_score <= 39
    assert site.importance_tier.value == "local"


def test_military_builder_preserves_tagged_and_name_inferred_roles() -> None:
    artifact = build_military_sites(
        [_military_feature("Graf Example Kaserne", 12.0, 54.0, military="range")],
        theater_id="GermanyCW",
    )

    assert artifact.sites[0].roles == (MilitaryRole.BARRACKS, MilitaryRole.FIRING_RANGE)
    assert artifact.sites[0].properties["role_sources"] == ["military_tag", "name"]


def test_industrial_builder_admits_supported_works_but_not_generic_estates() -> None:
    artifact = build_industrial_sites(
        [
            _industrial_feature("Alpha Steel", "works", 12.0, 54.0, industrial="steelmaking"),
            _industrial_feature("Gewerbegebiet Beta", "industrial_area", 12.1, 54.0, size_degrees=0.01),
            _industrial_feature(None, "works", 12.2, 54.0),
            _industrial_feature("Future Factory", "factory", 12.3, 54.0, valid_from=2005),
        ],
        theater_id="GermanyCW",
    )

    assert len(artifact.sites) == 1
    site = artifact.sites[0]
    assert isinstance(site, IndustrialSite)
    assert site.roles == (IndustrialRole.METALWORKS,)
    assert site.properties["strategic_candidate"] is True
    assert site.importance_score >= 60
    assert site.importance_tier.value == "high"
    assert artifact.metadata["excluded_industrial_counts"] == {
        "generic_industrial_area": 0,
        "weak_works": 1,
        "small_unnamed_site": 0,
        "other_infrastructure_category": 1,
        "outside_scenario_date": 1,
    }


def test_industrial_builder_clusters_same_site_without_merging_neighbors() -> None:
    artifact = build_industrial_sites(
        [
            _industrial_feature("Werft Alpha", "shipyard", 12.0, 54.0, source_suffix="a"),
            _industrial_feature("Werft Alpha", "works", 12.004, 54.0, source_suffix="b", product="steel"),
            _industrial_feature("Factory Beta", "factory", 12.005, 54.0, source_suffix="c"),
        ],
        theater_id="GermanyCW",
    )

    assert len(artifact.sites) == 2
    site = next(item for item in artifact.sites if item.name == "Werft Alpha")
    assert isinstance(site, IndustrialSite)
    assert site.roles == (IndustrialRole.METALWORKS, IndustrialRole.SHIPYARD)
    assert site.products == ("steel",)
    assert site.properties["member_count"] == 2
    assert site.geometry["type"] == "MultiPolygon"
    assert site.footprint_area_m2 > 0
    assert site.importance_tier.value == "critical"


def test_industrial_builder_fills_internal_footprint_holes() -> None:
    feature = _industrial_feature("Chemical Alpha", "chemical", 12.0, 54.0)
    feature = TopographyFeature(
        object_id=feature.object_id,
        layer=feature.layer,
        category=feature.category,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [[11.99, 53.99], [12.01, 53.99], [12.01, 54.01], [11.99, 54.01], [11.99, 53.99]],
                [[11.999, 53.999], [12.001, 53.999], [12.001, 54.001], [11.999, 54.001], [11.999, 53.999]],
            ],
        },
        source=feature.source,
        source_id=feature.source_id,
        confidence=feature.confidence,
        name=feature.name,
        properties=feature.properties,
    )

    site = build_industrial_sites((feature,), theater_id="GermanyCW").sites[0]

    from shapely.geometry import shape

    footprint = shape(site.geometry)
    assert footprint.geom_type == "Polygon"
    assert len(footprint.interiors) == 0
    assert site.properties["geometry_method"] == "hole_free_union_of_source_components"


def test_small_general_factory_is_not_automatically_strategic() -> None:
    site = build_industrial_sites(
        [_industrial_feature("Factory Alpha", "factory", 12.0, 54.0)],
        theater_id="GermanyCW",
    ).sites[0]

    assert site.importance_score < 50
    assert site.importance_tier.value == "local"
    assert site.properties["strategic_candidate"] is False


def test_industrial_site_round_trips_typed_properties() -> None:
    artifact = build_industrial_sites(
        [_industrial_feature("Machine Works", "machinery", 12.0, 54.0, product="machinery")],
        theater_id="GermanyCW",
    )

    loaded = TheaterInfrastructureSites.from_geojson(artifact.to_geojson())

    assert loaded == artifact
    assert isinstance(loaded.sites[0], IndustrialSite)
    assert loaded.sites[0].roles == (IndustrialRole.MACHINERY,)


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
