from __future__ import annotations

from moosebridge import (
    RailwayLocationKind,
    TheaterRailwayInfrastructure,
    TopographyFeature,
    TopographyLayer,
    build_railway_infrastructure,
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
    assert kinds.count(RailwayLocationKind.MARSHALLING_YARD) == 1
    assert kinds.count(RailwayLocationKind.JUNCTION) == 1
    assert kinds.count(RailwayLocationKind.BRIDGE) == 1
    station = next(location for location in result.locations if location.kind is RailwayLocationKind.STATION)
    assert station.member_count == 2
    assert station.name == "Test Central"
    yard = next(location for location in result.locations if location.kind is RailwayLocationKind.MARSHALLING_YARD)
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
