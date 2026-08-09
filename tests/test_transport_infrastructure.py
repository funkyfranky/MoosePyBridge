from __future__ import annotations

from dataclasses import replace
import numpy as np
import moosebridge.transport_infrastructure as transport_infrastructure
import pytest

from moosebridge import (
    RoadRoutingNetwork,
    TheaterTransportInfrastructure,
    TransportCriticalityConfig,
    TransportJunctionKind,
    analyze_transport_criticality,
    build_transport_infrastructure,
    reclassify_transport_importance,
)


def _network() -> RoadRoutingNetwork:
    edge_u = np.asarray([0, 1, 3, 2, 3, 3, 4, 7, 7], dtype=np.int32)
    edge_v = np.asarray([1, 2, 0, 4, 5, 6, 7, 5, 6], dtype=np.int32)
    edge_count = len(edge_u)
    node_count = 8
    adjacency_counts = np.bincount(np.concatenate((edge_u, edge_v)), minlength=node_count)
    adjacency_offsets = np.zeros(node_count + 1, dtype=np.int64)
    np.cumsum(adjacency_counts, out=adjacency_offsets[1:])
    adjacency_edges = np.empty(edge_count * 2, dtype=np.int32)
    cursor = adjacency_offsets[:-1].copy()
    for edge_index, (u, v) in enumerate(zip(edge_u, edge_v)):
        adjacency_edges[cursor[u]] = edge_index
        cursor[u] += 1
        adjacency_edges[cursor[v]] = edge_index
        cursor[v] += 1
    longitudes = np.asarray([12.00, 12.01, 12.02, 11.99, 12.03, 11.98, 12.00, 12.04])
    latitudes = np.asarray([54.00, 54.00, 54.00, 54.00, 54.00, 54.01, 53.99, 54.01])
    geometry_longitudes = np.asarray(
        [value for u, v in zip(edge_u, edge_v) for value in (longitudes[u], longitudes[v])],
        dtype=np.float32,
    )
    geometry_latitudes = np.asarray(
        [value for u, v in zip(edge_u, edge_v) for value in (latitudes[u], latitudes[v])],
        dtype=np.float32,
    )
    return RoadRoutingNetwork(
        theater_id="TestTheater",
        node_osm_ids=np.arange(100, 108, dtype=np.int64),
        node_longitudes=longitudes,
        node_latitudes=latitudes,
        node_x=np.arange(node_count, dtype=np.float64) * 100,
        node_y=np.zeros(node_count, dtype=np.float64),
        edge_u=edge_u,
        edge_v=edge_v,
        edge_lengths_m=np.asarray([100, 110, 90, 90, 120, 130, 50, 50, 50], dtype=np.float32),
        edge_highway_codes=np.asarray([0, 0, 0, 0, 1, 2, 3, 3, 3], dtype=np.uint16),
        edge_bridge=np.asarray([True, True, False, False, False, False, False, False, False]),
        geometry_offsets=np.arange(0, edge_count * 2 + 1, 2, dtype=np.int64),
        geometry_longitudes=geometry_longitudes,
        geometry_latitudes=geometry_latitudes,
        adjacency_offsets=adjacency_offsets,
        adjacency_edges=adjacency_edges,
        highway_classes=("primary", "trunk", "secondary", "residential"),
        metadata={},
    )


def test_connected_bridge_edges_become_one_bridge() -> None:
    result = build_transport_infrastructure(_network())

    assert len(result.bridges) == 1
    bridge = result.bridges[0]
    assert bridge.bridge_id.startswith("BRIDGE:TestTheater:")
    assert bridge.edge_count == 2
    assert bridge.length_m == 210
    assert bridge.approach_count == 2
    assert bridge.endpoint_osm_ids == (100, 102)
    assert bridge.highway_classes == ("primary",)
    assert bridge.geometry["type"] == "Point"
    assert bridge.member_count == 1


def test_only_strategic_road_arms_create_junctions() -> None:
    result = build_transport_infrastructure(_network())

    assert [junction.osm_node_id for junction in result.junctions] == [103]
    junction = result.junctions[0]
    assert junction.arm_count == 3
    assert junction.kind is TransportJunctionKind.INTERCHANGE
    assert junction.highway_classes == ("primary", "secondary", "trunk")
    assert junction.bridge_adjacent is False


def test_transport_infrastructure_geojson_round_trip(tmp_path) -> None:
    original = build_transport_infrastructure(_network())
    path = original.save(tmp_path / "transport.geojson")

    restored = TheaterTransportInfrastructure.load(path)

    assert restored == original
    assert {feature["properties"]["layer"] for feature in restored.to_geojson()["features"]} == {
        "transport_bridges", "transport_junctions",
    }


def test_junction_minimum_arms_is_validated() -> None:
    try:
        build_transport_infrastructure(_network(), minimum_junction_arms=2)
    except ValueError as exc:
        assert "at least three" in str(exc)
    else:
        raise AssertionError("minimum_junction_arms=2 should fail")


def test_nearby_interchange_nodes_become_one_complex() -> None:
    network = _network()
    candidates = [
        (
            0,
            transport_infrastructure.TransportJunction(
                junction_id="JUNCTION:OSM:100",
                kind=TransportJunctionKind.INTERCHANGE,
                latitude=54.0,
                longitude=12.0,
                osm_node_id=100,
                arm_count=3,
                highway_classes=("motorway",),
                bridge_adjacent=True,
                member_osm_ids=(100,),
            ),
        ),
        (
            1,
            transport_infrastructure.TransportJunction(
                junction_id="JUNCTION:OSM:101",
                kind=TransportJunctionKind.INTERCHANGE,
                latitude=54.0,
                longitude=12.001,
                osm_node_id=101,
                arm_count=4,
                highway_classes=("motorway_link", "primary"),
                bridge_adjacent=False,
                member_osm_ids=(101,),
            ),
        ),
    ]

    result = transport_infrastructure._cluster_junctions(
        network,
        candidates,
        interchange_radius_m=300,
        junction_radius_m=100,
    )

    assert len(result) == 1
    assert result[0].junction_id.startswith("JUNCTION:OSM-COMPLEX:")
    assert result[0].member_osm_ids == (100, 101)
    assert result[0].member_count == 2
    assert result[0].arm_count == 4
    assert result[0].bridge_adjacent is True


def test_nearby_bridge_structures_become_one_location() -> None:
    candidates = [
        transport_infrastructure._BridgeCandidate(
            x=0,
            y=0,
            bridge=transport_infrastructure.TransportBridge(
                bridge_id="BRIDGE:TestTheater:a",
                geometry={"type": "Point", "coordinates": [12.0, 54.0]},
                latitude=54.0,
                longitude=12.0,
                length_m=50,
                highway_classes=("motorway",),
                edge_count=1,
                approach_count=2,
                endpoint_osm_ids=(1, 2),
                member_bridge_ids=("BRIDGE:TestTheater:a",),
            ),
        ),
        transport_infrastructure._BridgeCandidate(
            x=80,
            y=0,
            bridge=transport_infrastructure.TransportBridge(
                bridge_id="BRIDGE:TestTheater:b",
                geometry={"type": "Point", "coordinates": [12.001, 54.0]},
                latitude=54.0,
                longitude=12.001,
                length_m=60,
                highway_classes=("motorway",),
                edge_count=1,
                approach_count=2,
                endpoint_osm_ids=(3, 4),
                member_bridge_ids=("BRIDGE:TestTheater:b",),
            ),
        ),
    ]

    result = transport_infrastructure._cluster_bridges(candidates, radius_m=150)

    assert len(result) == 1
    assert result[0].bridge_id.startswith("BRIDGE:TestTheater:COMPLEX:")
    assert result[0].geometry["type"] == "Point"
    assert result[0].geometry["coordinates"] == pytest.approx([12.0005, 54.0])
    assert result[0].member_count == 2
    assert result[0].edge_count == 2
    assert result[0].endpoint_osm_ids == (1, 2, 3, 4)


def test_criticality_analysis_records_alternative_route_impact() -> None:
    network = _network()
    from pyproj import Transformer

    x, y = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform(
        network.node_longitudes,
        network.node_latitudes,
    )
    network.node_x = np.asarray(x, dtype=np.float64)
    network.node_y = np.asarray(y, dtype=np.float64)
    infrastructure = build_transport_infrastructure(network)

    analyzed = analyze_transport_criticality(
        network,
        infrastructure,
        config=TransportCriticalityConfig(
            bridge_block_radius_m=100,
            interchange_block_radius_m=100,
            junction_block_radius_m=100,
            maximum_detour_m=5_000,
        ),
    )

    bridge = analyzed.bridges[0]
    assert bridge.road_importance == 75
    assert bridge.alternative_route_found is True
    assert bridge.detour_distance_m is not None
    assert bridge.detour_added_m is not None
    assert bridge.importance_score > 0
    junction = analyzed.junctions[0]
    assert junction.road_importance == 90
    assert junction.analysis_limit_m == 5_000
    assert 0 <= junction.importance_score <= 100
    assert analyzed.metadata["criticality_method"] == "bounded_location_block_and_alternative_route"


def test_importance_tiers_are_calibrated_per_infrastructure_type() -> None:
    infrastructure = build_transport_infrastructure(_network())
    scored = replace(
        infrastructure,
        bridges=(replace(infrastructure.bridges[0], importance_score=94),),
        junctions=(replace(infrastructure.junctions[0], importance_score=94),),
    )

    result = reclassify_transport_importance(scored)

    assert result.bridges[0].importance_tier.value == "high"
    assert result.junctions[0].importance_tier.value == "high"
    assert result.metadata["bridge_tier_thresholds"] == [95.0, 82.0, 55.0]
    assert result.metadata["junction_tier_thresholds"] == [95.0, 85.0, 65.0]
