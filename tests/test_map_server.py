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
    }


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
