"""Browser map service for the global MooseBridge situation picture."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from .control_sdk import sdk_from_control_client

LOGGER = logging.getLogger(__name__)
DEFAULT_MAP_HOST = "127.0.0.1"
DEFAULT_MAP_PORT = 8000
DEFAULT_UPDATE_INTERVAL = 5.0
DEFAULT_COMMAND_TIMEOUT = 15.0
MAP_UI_DIR = Path(__file__).with_name("map_ui")


def empty_picture() -> dict[str, Any]:
    """Return an empty WGS84 feature collection."""

    return {
        "type": "FeatureCollection",
        "features": [],
        "properties": {"scope": "global", "coordinate_system": "WGS84"},
    }


@dataclass(slots=True)
class GlobalMapRuntime:
    """Refresh global state and fan it out to connected browsers."""

    control_host: str = "127.0.0.1"
    control_port: int = DEFAULT_CONTROL_PORT
    interval: float = DEFAULT_UPDATE_INTERVAL
    timeout: float = DEFAULT_COMMAND_TIMEOUT
    picture: dict[str, Any] = field(default_factory=empty_picture)
    connected: bool = False
    error: str | None = None
    clients: set[WebSocket] = field(default_factory=set)
    _task: asyncio.Task[None] | None = None

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
        }

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
                self.picture = picture.to_geojson()
                self.connected = True
                self.error = None
                await self._broadcast({"type": "picture", "data": self.picture, "status": self.status_payload()})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.error = str(exc)
                LOGGER.warning("Global map refresh failed: %s", exc)
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
) -> FastAPI:
    """Create the FastAPI map application."""

    runtime = GlobalMapRuntime(control_host, control_port, interval, timeout)

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
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
