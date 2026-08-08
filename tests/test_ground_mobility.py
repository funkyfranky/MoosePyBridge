from __future__ import annotations

import pytest

from moosebridge.ground_mobility import (
    GroundMobilityNetwork,
    GroundTransportFeature,
    RoadClass,
    TRACKED_GROUND_PROFILE,
    build_ground_mobility_network,
    format_ground_route,
)
from moosebridge.surface_regions import (
    SurfaceClass,
    SurfaceRegion,
    SurfaceRegionKind,
    TheaterSurfaceRegions,
)


def _split_land() -> TheaterSurfaceRegions:
    def region(region_id: str, west: float, east: float) -> SurfaceRegion:
        return SurfaceRegion(
            region_id=region_id,
            surface_class=SurfaceClass.LAND,
            kind=SurfaceRegionKind.MAINLAND if west < 12 else SurfaceRegionKind.ISLAND,
            geometry={
                "type": "Polygon",
                "coordinates": [[
                    [west, 53.9], [east, 53.9], [east, 54.1],
                    [west, 54.1], [west, 53.9],
                ]],
            },
            area_m2=1,
            cell_count=1,
            confidence=0.75,
            source="test",
        )

    return TheaterSurfaceRegions(
        theater_id="MobilityTest",
        bounds=(53.9, 11.8, 54.1, 12.2),
        grid_spacing_m=500,
        regions=(
            region("SURFACE:MobilityTest:LAND:1", 11.8, 11.98),
            region("SURFACE:MobilityTest:LAND:2", 12.02, 12.2),
        ),
    )


def _road(*, bridge: bool) -> GroundTransportFeature:
    return GroundTransportFeature(
        source_id="OSM:way/1",
        road_class=RoadClass.PRIMARY,
        bridge=bridge,
        geometry={
            "type": "LineString",
            "coordinates": (
                [[11.97, 54.0], [12.03, 54.0]]
                if bridge
                else [[11.85, 54.0], [12.15, 54.0]]
            ),
        },
    )


def test_ground_mobility_bridge_connects_split_land() -> None:
    pytest.importorskip("shapely")
    pytest.importorskip("pyproj")

    disconnected = build_ground_mobility_network(
        _split_land(),
        (_road(bridge=False),),
        grid_spacing_m=5_000,
    )
    connected = build_ground_mobility_network(
        _split_land(),
        (_road(bridge=True),),
        grid_spacing_m=5_000,
    )

    assert disconnected.route(54.0, 11.85, 54.0, 12.15) is None
    route = connected.route(
        54.0,
        11.85,
        54.0,
        12.15,
        profile=TRACKED_GROUND_PROFILE,
    )
    assert route is not None
    assert route.bridge_count >= 1
    assert route.road_distance_m > 0
    assert "profile=tracked" in format_ground_route(route)


def test_ground_mobility_artifact_round_trip(tmp_path) -> None:
    pytest.importorskip("shapely")
    pytest.importorskip("pyproj")
    network = build_ground_mobility_network(
        _split_land(),
        (_road(bridge=True),),
        grid_spacing_m=5_000,
    )

    restored = GroundMobilityNetwork.load(network.save(tmp_path / "mobility.json"))

    assert restored.theater_id == network.theater_id
    assert restored.nodes == network.nodes
    assert restored.edges == network.edges
    assert restored.component_count == network.component_count
