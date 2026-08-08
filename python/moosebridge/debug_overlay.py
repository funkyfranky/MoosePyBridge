"""Bounded native DCS F10 markup models for diagnostic overlays."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Literal, Sequence


MarkupKind = Literal["point", "line", "polygon"]
MarkupColor = tuple[float, float, float, float]


@dataclass(slots=True, frozen=True)
class DebugMarkupPoint:
    """One WGS84 point sent to DCS for conversion with ``coord.LLtoLO``."""

    latitude: float
    longitude: float
    altitude: float = 0.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.latitude, self.longitude, self.altitude)):
            raise ValueError("debug markup coordinates must be finite")
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ValueError("debug markup latitude/longitude is outside WGS84 bounds")

    def to_payload(self) -> dict[str, float]:
        return {"latitude": self.latitude, "longitude": self.longitude, "altitude": self.altitude}


@dataclass(slots=True, frozen=True)
class DebugMarkup:
    """One point, polyline, or polygon outline in a named DCS overlay."""

    kind: MarkupKind
    points: tuple[DebugMarkupPoint, ...]
    color: MarkupColor = (0.0, 1.0, 0.0, 1.0)
    fill_color: MarkupColor = (0.0, 1.0, 0.0, 0.12)
    radius_m: float = 100.0
    line_type: int = 1

    def __post_init__(self) -> None:
        minimum = {"point": 1, "line": 2, "polygon": 3}.get(self.kind)
        if minimum is None:
            raise ValueError(f"unsupported debug markup kind: {self.kind}")
        if len(self.points) < minimum:
            raise ValueError(f"{self.kind} debug markup requires at least {minimum} point(s)")
        if self.kind == "point" and len(self.points) != 1:
            raise ValueError("point debug markup requires exactly one point")
        if not math.isfinite(self.radius_m) or self.radius_m <= 0:
            raise ValueError("debug markup radius_m must be positive")
        if self.line_type not in range(7):
            raise ValueError("debug markup line_type must be in range 0..6")
        _validate_color(self.color)
        _validate_color(self.fill_color)

    @property
    def mark_count(self) -> int:
        """Return the number of native DCS markup objects this feature needs."""

        if self.kind == "point":
            return 1
        count = len(self.points) - 1
        if self.kind == "polygon" and self.points[0] != self.points[-1]:
            count += 1
        return count

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "points": [point.to_payload() for point in self.points],
            "color": list(self.color),
            "fill_color": list(self.fill_color),
            "radius_m": self.radius_m,
            "line_type": self.line_type,
        }


@dataclass(slots=True, frozen=True)
class RoadPointMatch:
    """One OSM sample point and the nearest DCS road position."""

    input_point: DebugMarkupPoint
    road_point: DebugMarkupPoint
    input_x: float
    input_z: float
    road_x: float
    road_z: float
    distance_m: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RoadPointMatch":
        fields = (
            "input_latitude", "input_longitude", "road_latitude", "road_longitude",
            "input_x", "input_z", "road_x", "road_z", "distance_m",
        )
        try:
            values = {field: float(payload[field]) for field in fields}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("closest-road result is incomplete") from exc
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("closest-road result contains non-finite values")
        return cls(
            input_point=DebugMarkupPoint(values["input_latitude"], values["input_longitude"]),
            road_point=DebugMarkupPoint(values["road_latitude"], values["road_longitude"]),
            input_x=values["input_x"],
            input_z=values["input_z"],
            road_x=values["road_x"],
            road_z=values["road_z"],
            distance_m=values["distance_m"],
        )


@dataclass(slots=True, frozen=True)
class DcsRoadRoute:
    """One bounded route returned by native DCS road topology."""

    start_object_id: str
    end_object_id: str
    road_type: str
    points: tuple[DebugMarkupPoint, ...]
    distance_m: float
    raw_point_count: int
    sample_spacing_m: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DcsRoadRoute":
        """Build and validate a native road route result."""

        raw_points = payload.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 2:
            raise ValueError("DCS road route requires at least two points")
        try:
            points = tuple(
                DebugMarkupPoint(float(point["latitude"]), float(point["longitude"]))
                for point in raw_points
                if isinstance(point, dict)
            )
            distance_m = float(payload["distance_m"])
            raw_point_count = int(payload["raw_point_count"])
            sample_spacing_m = float(payload["sample_spacing_m"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("DCS road route result is incomplete") from exc
        if len(points) != len(raw_points):
            raise ValueError("DCS road route contains an invalid point")
        if not all(math.isfinite(value) for value in (distance_m, sample_spacing_m)):
            raise ValueError("DCS road route contains non-finite values")
        if distance_m < 0 or raw_point_count < len(points) or sample_spacing_m < 0:
            raise ValueError("DCS road route contains invalid metrics")
        return cls(
            start_object_id=str(payload.get("start_object_id") or ""),
            end_object_id=str(payload.get("end_object_id") or ""),
            road_type=str(payload.get("road_type") or "roads"),
            points=points,
            distance_m=distance_m,
            raw_point_count=raw_point_count,
            sample_spacing_m=sample_spacing_m,
        )


@dataclass(slots=True, frozen=True)
class DcsSurfacePoint:
    """Native DCS terrain classification for one WGS84 point."""

    input_point: DebugMarkupPoint
    input_x: float
    input_z: float
    surface_type: int
    surface_name: str
    is_water: bool

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DcsSurfacePoint":
        try:
            latitude = float(payload["input_latitude"])
            longitude = float(payload["input_longitude"])
            input_x = float(payload["input_x"])
            input_z = float(payload["input_z"])
            surface_type = int(payload["surface_type"])
            surface_name = str(payload["surface_name"])
            is_water = payload["is_water"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("surface-type result is incomplete") from exc
        if not all(math.isfinite(value) for value in (latitude, longitude, input_x, input_z)):
            raise ValueError("surface-type result contains non-finite values")
        if not surface_name or type(is_water) is not bool:
            raise ValueError("surface-type result has invalid classification data")
        return cls(
            input_point=DebugMarkupPoint(latitude, longitude),
            input_x=input_x,
            input_z=input_z,
            surface_type=surface_type,
            surface_name=surface_name,
            is_water=is_water,
        )


def validate_debug_overlay(
    overlay_id: str,
    features: Iterable[DebugMarkup],
    *,
    max_features: int = 200,
    max_points: int = 2_000,
    max_marks: int = 500,
) -> tuple[DebugMarkup, ...]:
    """Materialize and validate one overlay against the Lua safety limits."""

    if not overlay_id.strip() or len(overlay_id) > 96:
        raise ValueError("overlay_id must contain 1..96 non-whitespace characters")
    materialized = tuple(features)
    if not materialized:
        raise ValueError("debug overlay requires at least one feature")
    if len(materialized) > max_features:
        raise ValueError(f"debug overlay accepts at most {max_features} features")
    point_count = sum(len(feature.points) for feature in materialized)
    mark_count = sum(feature.mark_count for feature in materialized)
    if point_count > max_points:
        raise ValueError(f"debug overlay accepts at most {max_points} points")
    if mark_count > max_marks:
        raise ValueError(f"debug overlay accepts at most {max_marks} native DCS markups")
    return materialized


def rgba(red: float, green: float, blue: float, alpha: float = 1.0) -> MarkupColor:
    """Create and validate an immutable DCS RGBA color."""

    color = (float(red), float(green), float(blue), float(alpha))
    _validate_color(color)
    return color


def points_from_lon_lat(coordinates: Sequence[Sequence[float]]) -> tuple[DebugMarkupPoint, ...]:
    """Convert GeoJSON longitude/latitude pairs to typed markup points."""

    return tuple(DebugMarkupPoint(latitude=float(point[1]), longitude=float(point[0])) for point in coordinates)


def _validate_color(color: Sequence[float]) -> None:
    if len(color) != 4 or not all(math.isfinite(float(value)) and 0 <= float(value) <= 1 for value in color):
        raise ValueError("debug markup colors must contain four RGBA values in range 0..1")
