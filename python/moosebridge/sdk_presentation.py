"""Internal DCS presentation and effect commands used by the SDK facade."""

from __future__ import annotations

import math
from typing import Any

from .protocol import BridgeCommand
from .sdk_backend import SdkBackend


SMOKE_COLORS = {"red", "green", "blue", "orange", "white"}


def validate_smoke_color(color: str) -> str:
    """Validate and normalize a smoke color."""

    normalized = color.lower().strip()
    if normalized not in SMOKE_COLORS:
        raise ValueError(f"Unsupported smoke color: {color!r}. Expected one of {sorted(SMOKE_COLORS)}")
    return normalized


class DcsPresentationService:
    """Build and send user-visible DCS commands through an SDK backend."""

    def __init__(self, backend: SdkBackend) -> None:
        self._backend = backend

    async def message_coalition(self, coalition: str, text: str, duration: int) -> dict[str, Any]:
        return await self._backend.send_command(
            BridgeCommand(
                action="message.to_coalition",
                params={"coalition": coalition, "text": text, "duration": duration},
            )
        )

    async def message_all(self, text: str, duration: int) -> dict[str, Any]:
        return await self._backend.send_command(
            BridgeCommand(action="message.to_all", params={"text": text, "duration": duration})
        )

    async def smoke_point(
        self,
        x: float,
        z: float,
        color: str,
        y: float,
    ) -> dict[str, Any]:
        return await self._backend.send_command(
            BridgeCommand(
                action="smoke.at_point",
                params={"x": x, "y": y, "z": z, "color": validate_smoke_color(color)},
            )
        )

    async def smoke_object(self, object_id: str, color: str) -> dict[str, Any]:
        return await self._backend.send_command(
            BridgeCommand(
                action="smoke.object",
                params={"object_id": object_id, "color": validate_smoke_color(color)},
            )
        )

    async def explode_point(
        self,
        x: float,
        z: float,
        power: float,
        *,
        y: float | None,
        delay: float,
        timeout: float,
    ) -> dict[str, Any]:
        if power <= 0:
            raise ValueError("Explosion power must be greater than zero")
        if delay < 0:
            raise ValueError("Explosion delay must be zero or greater")
        params: dict[str, Any] = {"x": x, "z": z, "power": power, "delay": delay}
        if y is not None:
            params["y"] = y
        return await self._backend.send_command(
            BridgeCommand(action="explosion.at_point", params=params),
            timeout=timeout,
        )

    async def explode_object(
        self,
        object_id: str,
        power: float,
        *,
        delay: float,
        timeout: float,
    ) -> dict[str, Any]:
        if power <= 0:
            raise ValueError("Explosion power must be greater than zero")
        if delay < 0:
            raise ValueError("Explosion delay must be zero or greater")
        return await self._backend.send_command(
            BridgeCommand(
                action="explosion.object",
                params={"object_id": object_id, "power": power, "delay": delay},
            ),
            timeout=timeout,
        )

    async def mark_point(self, x: float, z: float, text: str, y: float) -> dict[str, Any]:
        return await self._backend.send_command(
            BridgeCommand(action="mark.at_point", params={"x": x, "y": y, "z": z, "text": text})
        )

    async def mark_object(self, object_id: str, text: str) -> dict[str, Any]:
        return await self._backend.send_command(
            BridgeCommand(action="mark.object", params={"object_id": object_id, "text": text})
        )

    async def mark_map_position(
        self,
        text: str,
        *,
        x: float | None,
        z: float | None,
        y: float,
        latitude: float | None,
        longitude: float | None,
        altitude: float,
        coalition: str | int,
        read_only: bool,
        timeout: float,
    ) -> dict[str, Any]:
        marker_text = str(text).strip()
        if not marker_text:
            raise ValueError("marker text must not be empty")
        if len(marker_text) > 180:
            raise ValueError("marker text accepts at most 180 characters")
        local_position = x is not None or z is not None
        geographic_position = latitude is not None or longitude is not None
        if local_position == geographic_position:
            raise ValueError("supply either x/z or latitude/longitude")
        if local_position:
            values = (x, y, z)
            if x is None or z is None or not all(math.isfinite(float(value)) for value in values):
                raise ValueError("x, y and z must be finite numbers")
            point = {"x": float(x), "y": float(y), "z": float(z)}
        else:
            values = (latitude, longitude, altitude)
            if latitude is None or longitude is None or not all(
                math.isfinite(float(value)) for value in values
            ):
                raise ValueError("latitude, longitude and altitude must be finite numbers")
            if not -90 <= float(latitude) <= 90 or not -180 <= float(longitude) <= 180:
                raise ValueError("latitude/longitude is outside WGS84 bounds")
            point = {
                "latitude": float(latitude),
                "longitude": float(longitude),
                "altitude": float(altitude),
            }
        return await self._backend.send_command(
            BridgeCommand(
                action="map.marker.create",
                params={
                    "point": point,
                    "text": marker_text,
                    "coalition": coalition,
                    "read_only": bool(read_only),
                },
            ),
            timeout=timeout,
        )
