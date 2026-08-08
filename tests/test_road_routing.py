from __future__ import annotations

import pandas as pd
import pytest
from shapely.geometry import LineString

from moosebridge import (
    GroundMobilityEdge,
    GroundMobilityNetwork,
    GroundMobilityNode,
    HierarchicalRoadRouter,
    RoadRoutingNetwork,
    RoadRoutingShardIndex,
    WHEELED_ROAD_PROFILE,
    build_road_routing_network,
    build_road_routing_shard_index,
    merge_road_routing_artifacts,
)


def _network() -> RoadRoutingNetwork:
    nodes = pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "lon": [12.000, 12.010, 12.020, 12.010],
            "lat": [54.000, 54.000, 54.000, 54.010],
        }
    )
    edges = pd.DataFrame(
        {
            "id": [10, 11, 12, 13],
            "u": [1, 2, 1, 4],
            "v": [2, 3, 4, 3],
            "length": [1_000.0, 1_000.0, 1_200.0, 1_200.0],
            "highway": ["residential", "residential", "motorway", "motorway"],
            "bridge": [None, None, "yes", None],
            "oneway": ["yes", "yes", "yes", "yes"],
            "access": ["private", "private", "private", "private"],
            "geometry": [
                LineString([(12.000, 54.000), (12.010, 54.000)]),
                LineString([(12.010, 54.000), (12.020, 54.000)]),
                LineString([(12.000, 54.000), (12.010, 54.010)]),
                LineString([(12.010, 54.010), (12.020, 54.000)]),
            ],
        }
    )
    return build_road_routing_network(theater_id="Test", nodes=nodes, edges=edges)


def test_router_ignores_oneway_and_access_and_prefers_fastest_route() -> None:
    network = _network()

    route = network.route(54.0, 12.02, 54.0, 12.0, profile=WHEELED_ROAD_PROFILE)

    assert route is not None
    assert route.edge_count == 2
    assert route.road_distance_m == 2_400
    assert route.bridge_count == 1
    assert route.travel_time_s < 2_000 / (30 / 3.6)


def test_router_round_trips_without_pickle(tmp_path) -> None:
    path = _network().save(tmp_path / "roads.npz")

    loaded = RoadRoutingNetwork.load(path)
    route = loaded.route(54.0, 12.0, 54.0, 12.02)

    assert loaded.metadata["oneway_ignored"] is True
    assert loaded.metadata["access_ignored"] is True
    assert route is not None
    assert route.edge_count == 2


def test_regional_artifacts_merge_through_shared_osm_node(tmp_path) -> None:
    nodes_a = pd.DataFrame({"id": [1, 2], "lon": [12.0, 12.01], "lat": [54.0, 54.0]})
    nodes_b = pd.DataFrame({"id": [2, 3], "lon": [12.01, 12.02], "lat": [54.0, 54.0]})
    edge_a = pd.DataFrame({
        "id": [10], "u": [1], "v": [2], "length": [1_000.0],
        "highway": ["primary"], "bridge": [None],
        "geometry": [LineString([(12.0, 54.0), (12.01, 54.0)])],
    })
    edge_b = pd.DataFrame({
        "id": [11], "u": [2], "v": [3], "length": [1_000.0],
        "highway": ["secondary"], "bridge": ["yes"],
        "geometry": [LineString([(12.01, 54.0), (12.02, 54.0)])],
    })
    first = build_road_routing_network(
        theater_id="Test", nodes=nodes_a, edges=edge_a, source_names=("a.pbf",),
    ).save(tmp_path / "a.npz")
    second = build_road_routing_network(
        theater_id="Test", nodes=nodes_b, edges=edge_b, source_names=("b.pbf",),
    ).save(tmp_path / "b.npz")

    merged = merge_road_routing_artifacts((first, second), theater_id="Test")
    route = merged.route(54.0, 12.0, 54.0, 12.02)

    assert merged.node_count == 3
    assert merged.edge_count == 2
    assert merged.metadata["partial_artifact_count"] == 2
    assert route is not None
    assert route.edge_count == 2
    assert route.bridge_count == 1


def test_filtered_merge_keeps_only_edges_touching_corridor_cells(tmp_path) -> None:
    source_network = _network()
    artifact = source_network.save(tmp_path / "roads.npz")
    cell_size_m = 100.0
    allowed_cell = (
        int(source_network.node_x[0] // cell_size_m),
        int(source_network.node_y[0] // cell_size_m),
    )

    filtered = merge_road_routing_artifacts(
        (artifact,),
        theater_id="Test",
        allowed_cells=(allowed_cell,),
        cell_size_m=cell_size_m,
    )

    assert filtered.edge_count == 2
    assert filtered.node_count == 3
    assert filtered.metadata["corridor_filtered"] is True


def test_filtered_merge_rejects_corridor_without_roads(tmp_path) -> None:
    artifact = _network().save(tmp_path / "roads.npz")

    with pytest.raises(ValueError, match="contains no edges"):
        merge_road_routing_artifacts(
            (artifact,),
            theater_id="Test",
            allowed_cells=((0, 0),),
            cell_size_m=100.0,
        )


def test_hierarchical_router_selects_and_caches_corridor_shards(tmp_path) -> None:
    from pyproj import Transformer

    nodes_a = pd.DataFrame({"id": [1, 2], "lon": [12.0, 12.01], "lat": [54.0, 54.0]})
    nodes_b = pd.DataFrame({"id": [2, 3], "lon": [12.01, 12.02], "lat": [54.0, 54.0]})
    edge_a = pd.DataFrame({
        "id": [10], "u": [1], "v": [2], "length": [1_000.0], "highway": ["primary"],
        "bridge": [None], "geometry": [LineString([(12.0, 54.0), (12.01, 54.0)])],
    })
    edge_b = pd.DataFrame({
        "id": [11], "u": [2], "v": [3], "length": [1_000.0], "highway": ["primary"],
        "bridge": [None], "geometry": [LineString([(12.01, 54.0), (12.02, 54.0)])],
    })
    first = build_road_routing_network(
        theater_id="Test", nodes=nodes_a, edges=edge_a, source_names=("a.pbf",),
    ).save(tmp_path / "a.npz")
    second = build_road_routing_network(
        theater_id="Test", nodes=nodes_b, edges=edge_b, source_names=("b.pbf",),
    ).save(tmp_path / "b.npz")
    manifest = build_road_routing_shard_index((first, second), tmp_path / "manifest.json", theater_id="Test")
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform(
        [12.0, 12.01, 12.02], [54.0, 54.0, 54.0],
    )
    strategic = GroundMobilityNetwork(
        theater_id="Test",
        grid_spacing_m=1_000,
        land_region_ids=("land",),
        nodes=tuple(
            GroundMobilityNode(index, x[index], y[index], 54.0, 12.0 + index * 0.01, 0, 0)
            for index in range(3)
        ),
        edges=(
            GroundMobilityEdge(0, 1, 1_000),
            GroundMobilityEdge(1, 2, 1_000),
        ),
        bounds=(53.9, 11.9, 54.1, 12.1),
    )
    router = HierarchicalRoadRouter(
        strategic, RoadRoutingShardIndex.load(manifest), corridor_buffer_m=5_000,
    )

    first_route = router.route(54.0, 12.0, 54.0, 12.02)
    second_route = router.route(54.0, 12.0, 54.0, 12.02)

    assert first_route is not None
    assert first_route.detailed_route.edge_count == 2
    assert first_route.graph_cache_hit is False
    assert second_route is not None
    assert second_route.graph_cache_hit is True
