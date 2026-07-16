from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from moosebridge.map_server import GlobalMapRuntime, create_app, empty_picture


def test_empty_picture_is_wgs84_geojson() -> None:
    picture = empty_picture()

    assert picture == {
        "type": "FeatureCollection",
        "features": [],
        "properties": {"scope": "global", "coordinate_system": "WGS84"},
    }


def test_map_runtime_status_uses_picture_metadata() -> None:
    runtime = GlobalMapRuntime()
    runtime.connected = True
    runtime.picture = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature"}],
        "properties": {"sequence": 12, "dcs_date": "1999/06/01", "dcs_time_of_day": "09:00:42"},
    }

    assert runtime.status_payload() == {
        "connected": True,
        "error": None,
        "feature_count": 1,
        "sequence": 12,
        "mission_time": None,
        "dcs_date": "1999/06/01",
        "dcs_time_of_day": "09:00:42",
        "wall_time": None,
        "trajectory_count": 0,
        "history_seconds": 900.0,
    }


def _moving_picture(mission_time: float, *, x: float = 0, z: float = 0, alive: bool = True) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [12.0 + x / 100_000, 54.0 + z / 100_000]},
                "properties": {
                    "layer": "groups",
                    "object_id": "GROUP:Moving",
                    "name": "Moving",
                    "category": "Ground Unit",
                    "coalition": "blue",
                    "alive": alive,
                    "x": x,
                    "z": z,
                },
            }
        ],
        "properties": {"mission_time": mission_time},
    }


def test_map_runtime_builds_trajectory_and_derived_movement() -> None:
    runtime = GlobalMapRuntime(history_seconds=60, history_max_points=10)

    runtime.update_picture(_moving_picture(100, x=0, z=0))  # type: ignore[arg-type]
    picture = runtime.update_picture(_moving_picture(110, x=100, z=0))  # type: ignore[arg-type]

    group = next(feature for feature in picture["features"] if feature["properties"]["layer"] == "groups")
    trajectory = next(feature for feature in picture["features"] if feature["properties"]["layer"] == "trajectories")
    assert group["properties"]["derived_speed_mps"] == 10
    assert group["properties"]["derived_heading_deg"] == 90
    assert group["properties"]["track_distance_m"] == 100
    assert trajectory["properties"]["tracked_object_id"] == "GROUP:Moving"
    assert trajectory["properties"]["sample_count"] == 2
    assert picture["properties"]["trajectory_count"] == 1


def test_map_runtime_removes_dead_or_missing_tracks() -> None:
    runtime = GlobalMapRuntime()
    runtime.update_picture(_moving_picture(100))  # type: ignore[arg-type]

    runtime.update_picture(_moving_picture(105, alive=False))  # type: ignore[arg-type]
    assert runtime.tracks == {}

    runtime.update_picture(_moving_picture(110))  # type: ignore[arg-type]
    runtime.update_picture({"type": "FeatureCollection", "features": [], "properties": {"mission_time": 115}})
    assert runtime.tracks == {}


def test_map_runtime_resets_tracks_when_mission_time_restarts() -> None:
    runtime = GlobalMapRuntime()
    runtime.update_picture(_moving_picture(100, x=0))  # type: ignore[arg-type]
    runtime.update_picture(_moving_picture(110, x=100))  # type: ignore[arg-type]

    picture = runtime.update_picture(_moving_picture(5, x=200))  # type: ignore[arg-type]

    assert len(runtime.tracks["GROUP:Moving"]) == 1
    assert not any(feature["properties"]["layer"] == "trajectories" for feature in picture["features"])


def test_map_runtime_task_stops_cleanly() -> None:
    async def scenario() -> None:
        runtime = GlobalMapRuntime(interval=60)
        await runtime.start()
        assert runtime._task is not None
        await runtime.stop()
        assert runtime._task is None

    asyncio.run(scenario())


def test_map_app_exposes_runtime() -> None:
    app = create_app(control_host="localhost", control_port=52001, interval=2.5, timeout=7)

    runtime = app.state.runtime
    assert runtime.control_host == "localhost"
    assert runtime.control_port == 52001
    assert runtime.interval == 2.5
    assert runtime.timeout == 7
