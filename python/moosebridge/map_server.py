"""Browser map service for the global MooseBridge situation picture."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
import math
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from .control_sdk import sdk_from_control_client
from .frontlines import (
    FrontlineCalculationArea,
    FrontlineConfig,
    FrontlineEngine,
    FrontlineForceTracker,
    FrontlineResult,
    force_points_from_groups,
)
from .pictures import GlobalPicture

LOGGER = logging.getLogger(__name__)
DEFAULT_MAP_HOST = "127.0.0.1"
DEFAULT_MAP_PORT = 8000
DEFAULT_UPDATE_INTERVAL = 5.0
DEFAULT_COMMAND_TIMEOUT = 15.0
DEFAULT_HISTORY_SECONDS = 15 * 60.0
DEFAULT_HISTORY_MAX_POINTS = 180
DEFAULT_FRONTLINE_INTERVAL = 15.0
DEFAULT_FRONTLINE_POSITION_ALPHA = 0.35
MAP_UI_DIR = Path(__file__).with_name("map_ui")
TRACKED_LAYERS = frozenset({"groups", "units", "opsgroups", "friendly_opsgroups", "intel_contacts", "known_enemy_contacts"})


def empty_picture() -> dict[str, Any]:
    """Return an empty WGS84 feature collection."""

    return {
        "type": "FeatureCollection",
        "features": [],
        "properties": {"scope": "global", "coordinate_system": "WGS84"},
    }


@dataclass(slots=True, frozen=True)
class TrackPoint:
    """One observed object position in mission time."""

    mission_time: float
    longitude: float
    latitude: float
    x: float | None = None
    z: float | None = None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _distance_m(first: TrackPoint, second: TrackPoint) -> float:
    """Return planar DCS distance when available, otherwise great-circle distance."""

    if first.x is not None and first.z is not None and second.x is not None and second.z is not None:
        return math.hypot(second.x - first.x, second.z - first.z)
    latitude_1 = math.radians(first.latitude)
    latitude_2 = math.radians(second.latitude)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = math.radians(second.longitude - first.longitude)
    haversine = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(haversine)))


def _heading_deg(first: TrackPoint, second: TrackPoint) -> float | None:
    """Return movement heading in degrees clockwise from north."""

    if first.x is not None and first.z is not None and second.x is not None and second.z is not None:
        delta_x = second.x - first.x
        delta_z = second.z - first.z
        if delta_x == 0 and delta_z == 0:
            return None
        return (math.degrees(math.atan2(delta_x, delta_z)) + 360) % 360
    if first.longitude == second.longitude and first.latitude == second.latitude:
        return None
    longitude_delta = math.radians(second.longitude - first.longitude)
    latitude_1 = math.radians(first.latitude)
    latitude_2 = math.radians(second.latitude)
    y = math.sin(longitude_delta) * math.cos(latitude_2)
    x = math.cos(latitude_1) * math.sin(latitude_2) - math.sin(latitude_1) * math.cos(latitude_2) * math.cos(longitude_delta)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


@dataclass(slots=True)
class GlobalMapRuntime:
    """Refresh global state and fan it out to connected browsers."""

    control_host: str = "127.0.0.1"
    control_port: int = DEFAULT_CONTROL_PORT
    interval: float = DEFAULT_UPDATE_INTERVAL
    timeout: float = DEFAULT_COMMAND_TIMEOUT
    history_seconds: float = DEFAULT_HISTORY_SECONDS
    history_max_points: int = DEFAULT_HISTORY_MAX_POINTS
    frontline_interval: float = DEFAULT_FRONTLINE_INTERVAL
    frontline_position_alpha: float = DEFAULT_FRONTLINE_POSITION_ALPHA
    picture: dict[str, Any] = field(default_factory=empty_picture)
    connected: bool = False
    error: str | None = None
    clients: set[WebSocket] = field(default_factory=set)
    tracks: dict[str, deque[TrackPoint]] = field(default_factory=dict)
    _task: asyncio.Task[None] | None = None
    _last_mission_time: float | None = None
    _frontline_mission_time: float | None = None
    _frontline_features: list[dict[str, Any]] = field(default_factory=list)
    _frontline_diagnostics: dict[str, Any] = field(default_factory=dict)
    _frontline_error: str | None = None
    _frontline_tracker: FrontlineForceTracker = field(init=False)
    _frontline_engine: FrontlineEngine = field(init=False)

    def __post_init__(self) -> None:
        if self.frontline_interval <= 0:
            raise ValueError("frontline_interval must be positive")
        self._frontline_tracker = FrontlineForceTracker(self.frontline_position_alpha)
        self._frontline_engine = FrontlineEngine(FrontlineConfig())

    def status_payload(self) -> dict[str, Any]:
        """Return the current browser-facing service status."""

        properties = self.picture.get("properties") if isinstance(self.picture.get("properties"), dict) else {}
        return {
            "connected": self.connected,
            "error": self.error,
            "feature_count": len(self.picture.get("features", [])),
            "sequence": properties.get("sequence"),
            "mission_time": properties.get("mission_time"),
            "dcs_date": properties.get("dcs_date"),
            "dcs_time_of_day": properties.get("dcs_time_of_day"),
            "wall_time": properties.get("wall_time"),
            "trajectory_count": sum(1 for feature in self.picture.get("features", []) if feature.get("properties", {}).get("layer") == "trajectories"),
            "history_seconds": self.history_seconds,
            "frontline_count": len(self._frontline_features),
            "frontline_updated_mission_time": self._frontline_mission_time,
            "frontline_error": self._frontline_error,
        }

    def update_picture(self, picture: dict[str, Any]) -> dict[str, Any]:
        """Record movement observations and append trajectory features."""

        properties = dict(picture.get("properties") or {})
        mission_time = _number(properties.get("mission_time"))
        source_features = picture.get("features") if isinstance(picture.get("features"), list) else []
        if mission_time is None:
            self.picture = {**picture, "features": list(source_features)}
            return self.picture

        if self._last_mission_time is not None and mission_time < self._last_mission_time:
            self.tracks.clear()
        self._last_mission_time = mission_time

        current_ids: set[str] = set()
        decorated_features: list[dict[str, Any]] = []
        for source_feature in source_features:
            feature = {**source_feature, "properties": dict(source_feature.get("properties") or {})}
            feature_properties = feature["properties"]
            object_id = str(feature_properties.get("object_id") or "")
            layer = str(feature_properties.get("layer") or "")
            geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
            coordinates = geometry.get("coordinates") if geometry.get("type") == "Point" else None
            trackable = (
                object_id
                and layer in TRACKED_LAYERS
                and feature_properties.get("alive") is not False
                and isinstance(coordinates, list)
                and len(coordinates) >= 2
            )
            if trackable:
                longitude = _number(coordinates[0])
                latitude = _number(coordinates[1])
                if longitude is not None and latitude is not None:
                    current_ids.add(object_id)
                    point = TrackPoint(
                        mission_time,
                        longitude,
                        latitude,
                        _number(feature_properties.get("x")),
                        _number(feature_properties.get("z")),
                    )
                    history = self.tracks.setdefault(object_id, deque(maxlen=max(2, self.history_max_points)))
                    history.append(point)
                    cutoff = mission_time - max(0.0, self.history_seconds)
                    while len(history) > 1 and history[0].mission_time < cutoff:
                        history.popleft()
                    self._add_movement_properties(feature_properties, history, mission_time)
            decorated_features.append(feature)

        for object_id in tuple(self.tracks):
            if object_id not in current_ids:
                del self.tracks[object_id]

        trajectories = self._trajectory_features(decorated_features)
        properties["trajectory_count"] = len(trajectories)
        properties["history_seconds"] = self.history_seconds
        self.picture = {**picture, "features": [*decorated_features, *trajectories], "properties": properties}
        return self.picture

    async def update_frontline(
        self,
        picture: GlobalPicture,
        geojson: dict[str, Any],
        bridge: Any,
    ) -> dict[str, Any]:
        """Append a periodically recalculated operational frontline."""

        mission_time = picture.clock.mission_time if picture.clock else None
        if (
            mission_time is not None
            and self._frontline_mission_time is not None
            and mission_time < self._frontline_mission_time
        ):
            self._frontline_tracker.reset()
            self._frontline_features.clear()
            self._frontline_diagnostics.clear()
            self._frontline_error = None
            self._frontline_mission_time = None

        due = (
            self._frontline_mission_time is None
            or mission_time is None
            or mission_time - self._frontline_mission_time >= self.frontline_interval
        )
        if due:
            forces = self._frontline_tracker.update(force_points_from_groups(picture.groups))
            if {force.coalition for force in forces} == {"blue", "red"}:
                area = None
                try:
                    area = FrontlineCalculationArea.from_territories(picture.territories)
                except ValueError:
                    pass
                result = self._frontline_engine.calculate(forces, area=area)
                self._frontline_features = await self._frontline_geojson_features(result, bridge)
                self._frontline_diagnostics = dict(result.diagnostics)
            else:
                self._frontline_features = []
                self._frontline_diagnostics = {
                    "input_force_count": len(forces),
                    "segment_count": 0,
                    "reason": "both blue and red ground forces are required",
                }
            self._frontline_mission_time = mission_time
            self._frontline_error = None

        features = geojson.get("features")
        if isinstance(features, list):
            features.extend(self._frontline_features)
        properties = geojson.setdefault("properties", {})
        properties["frontline_count"] = len(self._frontline_features)
        properties["frontline_updated_mission_time"] = self._frontline_mission_time
        properties["frontline_diagnostics"] = self._frontline_diagnostics
        return geojson

    @staticmethod
    async def _frontline_geojson_features(result: FrontlineResult, bridge: Any) -> list[dict[str, Any]]:
        points = [point for segment in result.segments for point in segment.points]
        converted = await bridge.convert_points(points) if points else []
        features: list[dict[str, Any]] = []
        cursor = 0
        for segment in result.segments:
            segment_points = converted[cursor : cursor + len(segment.points)]
            cursor += len(segment.points)
            coordinates = [[point.longitude, point.latitude] for point in segment_points]
            if len(coordinates) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "properties": {
                        "layer": "frontlines",
                        "object_id": f"FRONTLINE:{segment.index}",
                        "name": f"Frontline {segment.index}",
                        "object_type": "FRONTLINE",
                        "category": "Operational frontline",
                        "length_m": segment.length_m,
                        "force_count": result.diagnostics.get("included_force_count", 0),
                        "blue_force_count": result.diagnostics.get("blue_force_count", 0),
                        "red_force_count": result.diagnostics.get("red_force_count", 0),
                        "calculation_ms": result.elapsed_ms,
                        "coordinate_system": "WGS84",
                    },
                }
            )
        return features

    @staticmethod
    def _add_movement_properties(properties: dict[str, Any], history: deque[TrackPoint], mission_time: float) -> None:
        properties["last_update_mission_time"] = mission_time
        properties["track_sample_count"] = len(history)
        if len(history) < 2:
            return
        previous, current = history[-2], history[-1]
        elapsed = current.mission_time - previous.mission_time
        distance = _distance_m(previous, current)
        speed_mps = distance / elapsed if elapsed > 0 else 0.0
        properties["derived_speed_mps"] = speed_mps
        properties["derived_speed_kts"] = speed_mps * 1.9438444924406
        heading = _heading_deg(previous, current)
        if heading is not None:
            properties["derived_heading_deg"] = heading
        properties["track_distance_m"] = sum(_distance_m(first, second) for first, second in zip(history, list(history)[1:]))
        properties["track_duration_s"] = max(0.0, history[-1].mission_time - history[0].mission_time)

    def _trajectory_features(self, object_features: list[dict[str, Any]]) -> list[dict[str, Any]]:
        features_by_id = {str(feature.get("properties", {}).get("object_id") or ""): feature for feature in object_features}
        trajectories: list[dict[str, Any]] = []
        for object_id, history in self.tracks.items():
            if len(history) < 2:
                continue
            coordinates: list[list[float]] = []
            for point in history:
                coordinate = [point.longitude, point.latitude]
                if not coordinates or coordinate != coordinates[-1]:
                    coordinates.append(coordinate)
            if len(coordinates) < 2:
                continue
            source = features_by_id.get(object_id)
            if source is None:
                continue
            source_properties = source.get("properties", {})
            trajectories.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "properties": {
                        "layer": "trajectories",
                        "object_id": f"TRAJECTORY:{object_id}",
                        "tracked_object_id": object_id,
                        "name": source_properties.get("name") or object_id,
                        "object_type": "TRAJECTORY",
                        "category": source_properties.get("category"),
                        "coalition": source_properties.get("coalition"),
                        "alive": source_properties.get("alive"),
                        "source_layer": source_properties.get("layer"),
                        "sample_count": len(history),
                        "distance_m": source_properties.get("track_distance_m", 0.0),
                        "duration_s": source_properties.get("track_duration_s", 0.0),
                        "average_speed_mps": (
                            source_properties.get("track_distance_m", 0.0) / source_properties.get("track_duration_s", 1.0)
                            if source_properties.get("track_duration_s", 0.0) > 0
                            else 0.0
                        ),
                    },
                }
            )
        return trajectories

    async def start(self) -> None:
        """Start the periodic refresh task."""

        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="moosebridge-global-map")

    async def stop(self) -> None:
        """Stop the periodic refresh task."""

        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        control = MooseBridgeControlClient(self.control_host, self.control_port)
        bridge = sdk_from_control_client(control, timeout=self.timeout)
        while True:
            try:
                status = await control.status(timeout=self.timeout)
                if not status.get("connected"):
                    raise ConnectionError("DCS is not connected to the MooseBridge daemon")
                picture = await bridge.refresh_global_picture()
                geojson = picture.to_geojson()
                try:
                    geojson = await self.update_frontline(picture, geojson, bridge)
                except Exception as exc:
                    frontline_error = str(exc)
                    if frontline_error != self._frontline_error:
                        LOGGER.warning("Frontline update failed: %s", exc)
                    else:
                        LOGGER.debug("Frontline update still unavailable: %s", exc)
                    self._frontline_error = frontline_error
                    self._frontline_features = []
                    geojson["properties"]["frontline_count"] = 0
                    geojson["properties"]["frontline_error"] = self._frontline_error
                self.update_picture(geojson)
                if not self.connected:
                    LOGGER.info("Global map connected to DCS")
                self.connected = True
                self.error = None
                await self._broadcast({"type": "picture", "data": self.picture, "status": self.status_payload()})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = str(exc)
                if error != self.error:
                    LOGGER.warning("Global map refresh failed: %s", error)
                else:
                    LOGGER.debug("Global map refresh still unavailable: %s", error)
                self.connected = False
                self.error = error
                await self._broadcast({"type": "status", "status": self.status_payload()})
            await asyncio.sleep(self.interval)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in tuple(self.clients):
            try:
                await client.send_json(message)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


def create_app(
    *,
    control_host: str = "127.0.0.1",
    control_port: int = DEFAULT_CONTROL_PORT,
    interval: float = DEFAULT_UPDATE_INTERVAL,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
    history_seconds: float = DEFAULT_HISTORY_SECONDS,
    history_max_points: int = DEFAULT_HISTORY_MAX_POINTS,
    frontline_interval: float = DEFAULT_FRONTLINE_INTERVAL,
    frontline_position_alpha: float = DEFAULT_FRONTLINE_POSITION_ALPHA,
) -> FastAPI:
    """Create the FastAPI map application."""

    runtime = GlobalMapRuntime(
        control_host,
        control_port,
        interval,
        timeout,
        history_seconds,
        history_max_points,
        frontline_interval,
        frontline_position_alpha,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="MooseBridge Global Map", lifespan=lifespan)
    app.state.runtime = runtime
    app.mount("/assets", StaticFiles(directory=MAP_UI_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(MAP_UI_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return runtime.status_payload()

    @app.get("/api/picture/global.geojson")
    async def global_picture() -> dict[str, Any]:
        return runtime.picture

    @app.websocket("/ws/global")
    async def global_updates(websocket: WebSocket) -> None:
        await websocket.accept()
        runtime.clients.add(websocket)
        await websocket.send_json({"type": "picture", "data": runtime.picture, "status": runtime.status_payload()})
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            runtime.clients.discard(websocket)

    return app


def main() -> None:
    """Run the global map service."""

    parser = argparse.ArgumentParser(description="Live browser map for the MooseBridge global picture")
    parser.add_argument("--host", default=DEFAULT_MAP_HOST, help="HTTP interface to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_MAP_PORT, help="HTTP port.")
    parser.add_argument("--control-host", default="127.0.0.1", help="MooseBridge control API host.")
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT, help="MooseBridge control API port.")
    parser.add_argument("--interval", type=float, default=DEFAULT_UPDATE_INTERVAL, help="Picture refresh interval in seconds.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_COMMAND_TIMEOUT, help="DCS command timeout in seconds.")
    parser.add_argument("--history-seconds", type=float, default=DEFAULT_HISTORY_SECONDS, help="Trajectory history duration in mission seconds.")
    parser.add_argument("--history-max-points", type=int, default=DEFAULT_HISTORY_MAX_POINTS, help="Maximum trajectory samples per object.")
    parser.add_argument("--frontline-interval", type=float, default=DEFAULT_FRONTLINE_INTERVAL, help="Frontline recalculation interval in mission seconds.")
    parser.add_argument("--frontline-position-alpha", type=float, default=DEFAULT_FRONTLINE_POSITION_ALPHA, help="Frontline force-position smoothing factor.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Map dependencies are missing. Run: python -m pip install -e ".[map]"') from exc

    app = create_app(
        control_host=args.control_host,
        control_port=args.control_port,
        interval=max(0.5, args.interval),
        timeout=max(1.0, args.timeout),
        history_seconds=max(0.0, args.history_seconds),
        history_max_points=max(2, args.history_max_points),
        frontline_interval=max(1.0, args.frontline_interval),
        frontline_position_alpha=min(1.0, max(0.01, args.frontline_position_alpha)),
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
