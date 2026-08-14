from __future__ import annotations

from moosebridge import (
    RailwayCriticalityConfig,
    RailwayImportanceTier,
    RailwayLocation,
    RailwayLocationKind,
    TheaterRailwayInfrastructure,
    TopographyFeature,
    TopographyLayer,
    analyze_railway_criticality,
    build_railway_infrastructure,
    build_railway_routing_network,
)


def _track(object_id: str, coordinates: list[list[float]], **tags: str) -> TopographyFeature:
    return TopographyFeature(
        object_id=object_id,
        layer=TopographyLayer.RAILWAYS,
        category="rail",
        geometry={"type": "LineString", "coordinates": coordinates},
        source="OpenStreetMap",
        confidence=0.6,
        properties={"osm_tags": {"railway": "rail", **tags}},
    )


def _facility(object_id: str, category: str, lon: float, lat: float, name: str) -> TopographyFeature:
    return TopographyFeature(
        object_id=object_id,
        layer=TopographyLayer.INFRASTRUCTURE,
        category=category,
        geometry={"type": "Point", "coordinates": [lon, lat]},
        source="OpenStreetMap",
        confidence=0.65,
        name=name,
        properties={"osm_tags": {"railway": category.removeprefix("railway_")}},
    )


def test_builds_aggregated_operational_railway_locations() -> None:
    tracks = [
        _track("RAIL:1", [[12.0, 54.0], [12.01, 54.0]], bridge="yes"),
        _track("RAIL:2", [[12.01, 54.0], [12.02, 54.0]]),
        _track("RAIL:3", [[12.01, 54.0], [12.01, 54.01]]),
        _track("RAIL:Y1", [[12.03, 54.0], [12.031, 54.0]], service="yard"),
        _track("RAIL:Y2", [[12.031, 54.0], [12.032, 54.0]], service="yard"),
    ]
    facilities = [
        _facility("INFRA:station:1", "railway_station", 12.02, 54.0, "Test Central"),
        _facility("INFRA:station:2", "railway_station", 12.0202, 54.0, "Test Central"),
    ]

    result = build_railway_infrastructure(tracks, facilities, theater_id="Test", cluster_radius_m=250)

    kinds = [location.kind for location in result.locations]
    assert kinds.count(RailwayLocationKind.STATION) == 1
    assert kinds.count(RailwayLocationKind.RAIL_YARD) == 1
    assert kinds.count(RailwayLocationKind.JUNCTION) == 1
    assert kinds.count(RailwayLocationKind.BRIDGE) == 1
    station = next(location for location in result.locations if location.kind is RailwayLocationKind.STATION)
    assert station.member_count == 2
    assert station.name == "Test Central"
    yard = next(location for location in result.locations if location.kind is RailwayLocationKind.RAIL_YARD)
    assert yard.member_count == 2
    assert yard.track_length_m > 0


def test_railway_geojson_round_trip(tmp_path) -> None:
    result = build_railway_infrastructure(
        [_track("RAIL:1", [[12.0, 54.0], [12.01, 54.0]], bridge="yes")],
        [_facility("INFRA:station:1", "railway_station", 12.01, 54.0, "Station")],
        theater_id="Test",
    )
    path = result.save(tmp_path / "railway.geojson")

    restored = TheaterRailwayInfrastructure.load(path)

    assert restored == result
    assert all(feature["geometry"]["type"] == "Point" for feature in restored.to_geojson()["features"])


def test_railway_geojson_loads_legacy_marshalling_yard_kind() -> None:
    result = build_railway_infrastructure(
        [_track("RAIL:Y1", [[12.03, 54.0], [12.032, 54.0]], service="yard")],
        theater_id="Test",
    )
    payload = result.to_geojson()
    payload["features"][0]["properties"]["railway_kind"] = "marshalling_yard"
    payload["features"][0]["properties"]["category"] = "marshalling_yard"

    restored = TheaterRailwayInfrastructure.from_geojson(payload)

    assert restored.locations[0].kind is RailwayLocationKind.RAIL_YARD
    assert restored.to_geojson()["features"][0]["properties"]["railway_kind"] == "rail_yard"


def test_bridge_clustering_does_not_chain_distant_structures() -> None:
    tracks = [
        _track("RAIL:B1", [[12.0000, 54.0], [12.0001, 54.0]], bridge="yes"),
        _track("RAIL:B2", [[12.0037, 54.0], [12.0038, 54.0]], bridge="yes"),
        _track("RAIL:B3", [[12.0074, 54.0], [12.0075, 54.0]], bridge="yes"),
    ]

    result = build_railway_infrastructure(
        tracks,
        theater_id="Test",
        cluster_radius_m=300,
    )

    bridges = [location for location in result.locations if location.kind is RailwayLocationKind.BRIDGE]
    assert len(bridges) == 2
    assert sorted(location.member_count for location in bridges) == [1, 2]


def test_railway_routing_round_trip_and_route(tmp_path) -> None:
    network = build_railway_routing_network(
        [
            _track("RAIL:1", [[12.0, 54.0], [12.01, 54.0]]),
            _track("RAIL:2", [[12.01, 54.0], [12.02, 54.0]], bridge="yes"),
        ],
        theater_id="Test",
    )

    route = network.route(54.0, 12.0, 54.0, 12.02)
    restored = type(network).load(network.save(tmp_path / "railway-routing.npz"))

    assert route is not None
    assert route.edge_count == 2
    assert route.distance_m > 1_000
    assert restored.node_count == network.node_count
    assert restored.edge_count == network.edge_count


def test_railway_criticality_detects_disconnection() -> None:
    tracks = [
        _track("RAIL:1", [[12.0, 54.0], [12.01, 54.0]]),
        _track("RAIL:2", [[12.01, 54.0], [12.02, 54.0]], bridge="yes"),
        _track("RAIL:3", [[12.02, 54.0], [12.03, 54.0]]),
    ]
    network = build_railway_routing_network(tracks, theater_id="Test")
    location = RailwayLocation(
        location_id="RAILWAY_BRIDGE:Test:1",
        kind=RailwayLocationKind.BRIDGE,
        latitude=54.0,
        longitude=12.015,
        importance_score=75,
        importance_tier=RailwayImportanceTier.HIGH,
    )
    infrastructure = TheaterRailwayInfrastructure(theater_id="Test", locations=(location,))

    analyzed = analyze_railway_criticality(
        network,
        infrastructure,
        config=RailwayCriticalityConfig(bridge_block_radius_m=400, maximum_route_m=20_000),
    )

    properties = analyzed.locations[0].properties
    assert properties["network_analysis_complete"] is True
    assert properties["network_disconnected_if_lost"] is True
    assert properties["network_criticality_score"] == 100


def test_railway_criticality_records_alternative_route() -> None:
    tracks = [
        _track("RAIL:1", [[12.0, 54.0], [12.01, 54.0]]),
        _track("RAIL:2", [[12.01, 54.0], [12.02, 54.0]], bridge="yes"),
        _track("RAIL:3", [[12.02, 54.0], [12.03, 54.0]]),
        _track("RAIL:4", [[12.01, 54.0], [12.01, 54.01], [12.02, 54.01], [12.02, 54.0]]),
    ]
    network = build_railway_routing_network(tracks, theater_id="Test")
    location = RailwayLocation(
        location_id="RAILWAY_BRIDGE:Test:2",
        kind=RailwayLocationKind.BRIDGE,
        latitude=54.0,
        longitude=12.015,
        importance_score=75,
        importance_tier=RailwayImportanceTier.HIGH,
    )

    analyzed = analyze_railway_criticality(
        network,
        TheaterRailwayInfrastructure(theater_id="Test", locations=(location,)),
        config=RailwayCriticalityConfig(bridge_block_radius_m=400, maximum_route_m=20_000),
    )

    properties = analyzed.locations[0].properties
    assert properties["network_disconnected_if_lost"] is False
    assert properties["network_alternative_route_found"] is True
    assert properties["network_detour_added_m"] > 0
    assert properties["network_detour_ratio"] > 1
