"""Read-only FLIGHTGROUP routes and their F10 polyline representation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .debug_overlay import DebugMarkup, DebugMarkupPoint


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


@dataclass(frozen=True, slots=True)
class FlightRouteWaypoint:
    """One ordered waypoint; altitude reference and speed remain as supplied by DCS."""

    index: int
    name: str
    latitude: float
    longitude: float
    x: float
    z: float
    altitude_m: float | None
    altitude_type: str | None
    terrain_elevation_m: float | None
    speed_mps: float | None
    waypoint_type: str | None
    action: str | None

    @property
    def height_agl_m(self) -> float | None:
        """Best available planned height above terrain, without guessing."""
        if self.altitude_m is None:
            return None
        if (self.altitude_type or "").upper() == "RADIO":
            return self.altitude_m
        if self.terrain_elevation_m is not None:
            return self.altitude_m - self.terrain_elevation_m
        return None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FlightRouteWaypoint":
        index = payload.get("index")
        if type(index) is not int or index < 1:
            raise ValueError("waypoint index must be a positive integer")
        latitude = _number(payload.get("latitude"), "latitude")
        longitude = _number(payload.get("longitude"), "longitude")
        DebugMarkupPoint(latitude, longitude)  # Validate geographic bounds.
        speed = payload.get("speed_mps")
        speed_mps = _number(speed, "speed_mps") if speed is not None else None
        if speed_mps is not None and speed_mps < 0:
            raise ValueError("speed_mps must not be negative")
        altitude = payload.get("altitude_m")
        terrain = payload.get("terrain_elevation_m")
        return cls(
            index=index,
            name=str(payload.get("name") or f"WP {index}"),
            latitude=latitude,
            longitude=longitude,
            x=_number(payload.get("x"), "x"),
            z=_number(payload.get("z"), "z"),
            altitude_m=_number(altitude, "altitude_m") if altitude is not None else None,
            altitude_type=str(payload["altitude_type"]) if payload.get("altitude_type") else None,
            terrain_elevation_m=(_number(terrain, "terrain_elevation_m")
                                 if terrain is not None else None),
            speed_mps=speed_mps,
            waypoint_type=str(payload["type"]) if payload.get("type") else None,
            action=str(payload["action"]) if payload.get("action") else None,
        )


@dataclass(frozen=True, slots=True)
class FlightGroupRoute:
    """An original Mission Editor or current operational FLIGHTGROUP route."""

    opsgroup_id: str
    group_id: str
    coalition: str | None
    route_source: str
    waypoints: tuple[FlightRouteWaypoint, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FlightGroupRoute":
        object_id = str(payload.get("opsgroup_id") or "")
        if not object_id.startswith("OPSGROUP:") or not object_id[9:].strip():
            raise ValueError("route requires a nonempty OPSGROUP: id")
        source = str(payload.get("route_source") or "")
        if source not in {"mission_editor", "current"}:
            raise ValueError("route_source must be mission_editor or current")
        raw = payload.get("waypoints")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 501:
            raise ValueError("route must contain 1..501 waypoints")
        if not all(isinstance(item, dict) for item in raw):
            raise ValueError("route waypoints must be objects")
        waypoints = tuple(FlightRouteWaypoint.from_payload(item) for item in raw)
        if tuple(point.index for point in waypoints) != tuple(range(1, len(waypoints) + 1)):
            raise ValueError("route waypoint indexes must be ordered and contiguous")
        return cls(
            opsgroup_id=object_id,
            group_id=str(payload.get("group_id") or "GROUP:" + object_id[9:]),
            coalition=str(payload["coalition"]) if payload.get("coalition") else None,
            route_source=source,
            waypoints=waypoints,
        )

    def to_map_line(self) -> DebugMarkup:
        """Connect consecutive points in cyan, without closing the route.

        This is a plan-view polyline, not a flyable procedure or altitude profile.
        BARO/RADIO altitude constraints are preserved in the data, not used as
        absolute markup heights.
        """

        return DebugMarkup(
            "line",
            tuple(DebugMarkupPoint(wp.latitude, wp.longitude) for wp in self.waypoints),
            color=(0.0, 1.0, 1.0, 1.0),
        )
