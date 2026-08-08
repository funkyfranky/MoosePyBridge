"""Run the browser map with a deterministic all-layer development picture."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moosebridge.map_server import create_app


MOBILE_QA_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MooseBridge mobile map QA</title>
  <style>
    html, body { margin: 0; min-height: 100%; background: #d9dfdc; }
    iframe { display: block; width: 390px; height: 844px; border: 0; background: white; }
  </style>
</head>
<body><iframe id="mobile-map" title="MooseBridge mobile map" src="/"></iframe></body>
</html>"""


def _feature(
    layer: str,
    object_id: str,
    geometry: dict[str, Any],
    **properties: Any,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "layer": layer,
            "object_id": object_id,
            "name": properties.pop("name", object_id.split(":", 1)[-1]),
            "object_type": object_id.split(":", 1)[0],
            "coordinate_system": "WGS84",
            **properties,
        },
    }


def _point(longitude: float, latitude: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [longitude, latitude]}


def _line(*coordinates: tuple[float, float]) -> dict[str, Any]:
    return {"type": "LineString", "coordinates": [list(point) for point in coordinates]}


def _polygon(*coordinates: tuple[float, float]) -> dict[str, Any]:
    ring = [list(point) for point in coordinates]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def build_fixture_picture() -> dict[str, Any]:
    """Return representative data for every dynamic browser-map layer."""

    features = [
        _feature(
            "territories", "TERRITORY:Blue North", _polygon((11.60, 53.55), (12.25, 53.55), (12.25, 54.25), (11.60, 54.25)),
            name="Blue Territory", coalition="blue", owner="blue", category="territory",
        ),
        _feature(
            "territories", "TERRITORY:Red East", _polygon((12.25, 53.55), (12.95, 53.55), (12.95, 54.25), (12.25, 54.25)),
            name="Red Territory", coalition="red", owner="red", category="territory",
        ),
        _feature(
            "zones", "ZONE:Training Alpha", _point(11.92, 53.83),
            name="Training Alpha", radius_m=8_000, category="circle", coalition="neutral",
        ),
        _feature(
            "opszones", "OPSZONE:Town Fight", _polygon((12.20, 53.82), (12.38, 53.82), (12.39, 53.98), (12.19, 53.98)),
            name="Town Fight", owner="red", coalition="red", contested=True, category="opszone",
        ),
        _feature(
            "frontlines", "FRONTLINE:Blue Red", _line((12.24, 53.58), (12.28, 53.77), (12.27, 53.98), (12.31, 54.20)),
            name="Blue/Red frontline", category="frontline",
        ),
        _feature(
            "pressure_frontlines", "PRESSURELINE:Blue Red", _line((12.18, 53.58), (12.22, 53.78), (12.21, 54.00), (12.25, 54.20)),
            name="Blue/Red pressure line", category="pressure",
        ),
        _feature(
            "incursions", "INCURSION:Red Recon", _point(12.04, 53.91),
            name="Red incursion", coalition="red", category="Ground Unit", alive=True, active=True,
            source_group_id="GROUP:Red Recon", territory_id="TERRITORY:Blue North",
        ),
        _feature(
            "groups", "GROUP:Blue Armor", _point(11.98, 53.88),
            name="Blue Armor", coalition="blue", category="Ground Unit", alive=True, active=True,
            unit_count=4, alive_unit_count=3, dcs_type="Leopard-2", x=-50_000, y=42, z=-540_000,
        ),
        _feature(
            "groups", "GROUP:Red Armor", _point(12.47, 53.91),
            name="Red Armor", coalition="red", category="Ground Unit", alive=True, active=True,
            unit_count=3, alive_unit_count=3, dcs_type="T-72B", x=-23_000, y=34, z=-535_000,
        ),
        _feature(
            "groups", "GROUP:Destroyed Convoy", _point(12.08, 53.72),
            name="Destroyed Convoy", coalition="red", category="Ground Unit", alive=False, active=False,
            unit_count=5, alive_unit_count=0, dcs_type="Ural-375",
        ),
        _feature(
            "units", "UNIT:Blue Armor-1", _point(11.985, 53.882),
            name="Blue Armor-1", group_name="Blue Armor", coalition="blue", category="Ground Unit",
            alive=True, active=True, dcs_type="Leopard-2", derived_speed_kts=18.4, derived_heading_deg=72.0,
            latitude=53.882, longitude=11.985, x=-49_700, y=42, z=-539_900,
        ),
        _feature(
            "units", "UNIT:Red Armor-1", _point(12.465, 53.912),
            name="Red Armor-1", group_name="Red Armor", coalition="red", category="Ground Unit",
            alive=True, active=True, dcs_type="T-72B",
        ),
        _feature(
            "statics", "STATIC:Fuel Depot", _point(12.58, 53.78),
            name="Fuel Depot", coalition="red", category="Warehouse", alive=True, active=True, dcs_type="Tank 2",
        ),
        _feature(
            "airbases", "AIRBASE:Laage", _point(12.28, 53.92),
            name="Laage", coalition="blue", category="airdrome", type="BASE", airbase_id=84, alive=True,
            latitude=53.92, longitude=12.28, source="database.AIRBASES",
        ),
        _feature(
            "airbases", "AIRBASE:Field FARP", _point(11.82, 53.72),
            name="Field FARP", coalition="blue", category="heliport", type="STATIC", airbase_id=401, alive=True,
        ),
        _feature(
            "airbases", "AIRBASE:Carrier", _point(12.12, 54.17),
            name="Carrier", coalition="blue", category="ship", type="UNIT", airbase_id=501, alive=True,
        ),
        _feature(
            "opsgroups", "OPSGROUP:Blue Armor", _point(11.98, 53.88),
            name="Blue Armor OPS", coalition="blue", category="Ground Unit", alive=True, active=True,
            group_name="Blue Armor", state="Cruising", legion_id="LEGION:Blue Brigade",
        ),
        _feature(
            "legions", "LEGION:Blue Brigade", _point(11.78, 53.94),
            name="Blue Brigade", coalition="blue", category="BRIGADE", state="OnDuty", alive=True,
            available_assets=8, cohort_count=3,
        ),
        _feature(
            "legions", "LEGION:Red Wing", _point(12.78, 54.05),
            name="Red Wing", coalition="red", category="AIRWING", state="OnDuty", alive=True,
            available_assets=6, cohort_count=2,
        ),
        _feature(
            "intel_contacts", "INTELCONTACT:Blue:Red Armor", _point(12.47, 53.91),
            name="Red Armor contact", coalition="blue", category="Ground", alive=True, target_id="GROUP:Red Armor",
            intel_id="INTEL:Blue", recce_name="MQ-9 Reaper", threat_level=6, speed=12.0,
        ),
        _feature(
            "intel_clusters", "INTELCLUSTER:Blue:1", _point(12.52, 53.94),
            name="Red ground cluster", coalition="blue", category="Ground", alive=True,
            intel_id="INTEL:Blue", size=3, threat_level_max=8, threat_level_sum=17,
        ),
        _feature(
            "loss_reports", "LOSS:Blue Armor-2", _point(12.10, 53.86),
            name="Blue Armor-2 lost", coalition="blue", category="Ground Unit", alive=False,
            tracked_object_id="UNIT:Blue Armor-2", source_layer="units", event="S_EVENT_UNIT_LOST",
        ),
        _feature(
            "missions", "AUFTRAG:7", _point(12.33, 53.90),
            name="Capture Town Fight", coalition="blue", category="Ground", alive=True,
            mission_type="CAPTUREZONE", status="executing", target_id="OPSZONE:Town Fight", legion_id="LEGION:Blue Brigade",
        ),
        _feature(
            "mission_links", "MISSIONLINK:AUFTRAG:7", _line((11.78, 53.94), (12.33, 53.90)),
            name="Mission assignment", coalition="blue", category="assignment", alive=True,
        ),
        _feature(
            "trajectories", "TRACK:GROUP:Blue Armor", _line((11.82, 53.82), (11.90, 53.85), (11.98, 53.88)),
            name="Blue Armor movement", coalition="blue", category="Ground Unit", alive=True,
            tracked_object_id="GROUP:Blue Armor", sample_count=8, track_distance_m=18_200, track_duration_s=940,
        ),
        _feature(
            "recon_coverage", "RECONCOVERAGE:AUFTRAG:8:aggregate", _polygon((12.37, 53.76), (12.67, 53.76), (12.67, 54.05), (12.37, 54.05)),
            name="RECON search coverage", coalition="blue", map_category="aggregate", category="aggregate", alive=True,
            auftrag_id="AUFTRAG:8", area_coverage_ratio=0.82,
        ),
        _feature(
            "recon_coverage", "RECONCOVERAGE:AUFTRAG:8:asset", _polygon((12.43, 53.82), (12.61, 53.82), (12.61, 53.99), (12.43, 53.99)),
            name="MQ-9 sensor footprint", coalition="blue", map_category="assets", category="assets", alive=True,
            auftrag_id="AUFTRAG:8", sensor_range_m=25_000,
        ),
        _feature(
            "recon_coverage", "RECONPOINT:Fuel Depot", _point(12.58, 53.78),
            name="Fuel Depot covered", coalition="blue", map_category="covered", category="covered", alive=True,
        ),
        _feature(
            "recon_coverage", "RECONPOINT:Rail Junction", _point(12.64, 54.02),
            name="Rail junction uncovered", coalition="blue", map_category="uncovered", category="uncovered", alive=True,
        ),
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "scope": "global",
            "coordinate_system": "WGS84",
            "sequence": 42,
            "mission_time": 3_725.0,
            "mission_elapsed": "01:02:05",
            "dcs_date": "1989/10/03",
            "dcs_time_of_day": "14:32:05",
            "wall_time": "2026-08-08T12:00:00Z",
            "diplomacy": {
                "relationship": "war",
                "escalation_score": 100,
                "doctrines": {"blue": "offensive", "red": "defensive"},
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the all-layer MooseBridge map fixture")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()

    app = create_app()
    runtime = app.state.runtime
    runtime.picture = build_fixture_picture()
    runtime.connected = True
    runtime.error = None

    from fastapi.responses import HTMLResponse

    @app.get("/qa/mobile", response_class=HTMLResponse)
    async def mobile_qa() -> str:
        return MOBILE_QA_PAGE

    @asynccontextmanager
    async def fixture_lifespan(_: Any):
        yield

    app.router.lifespan_context = fixture_lifespan
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Map dependencies are missing. Run: python -m pip install -e ".[map]"') from exc
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
