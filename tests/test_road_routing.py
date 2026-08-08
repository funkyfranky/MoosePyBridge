from __future__ import annotations

import pandas as pd
from shapely.geometry import LineString

from moosebridge import (
    RoadRoutingNetwork,
    WHEELED_ROAD_PROFILE,
    build_road_routing_network,
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
