"""Read-only flight state from DCS world telemetry, not cockpit instruments."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


METERS_PER_FOOT = 0.3048
MPS_PER_KNOT = 1852 / 3600
MIN_TRACK_SPEED_MPS = 1.0


def _number(value: Any, name: str, *, required: bool = False) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"Flight status {name} must be finite")
    return float(value)


def _vector(value: Any, name: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"Flight status {name} must be a vector")
    return tuple(_number(value.get(axis), f"{name}.{axis}", required=True) for axis in ("x", "y", "z"))


def _direction(vector: tuple[float, float, float] | None,
               north: tuple[float, float, float] | None) -> float | None:
    if vector is None or north is None:
        return None
    if math.hypot(vector[0], vector[2]) < 1e-6 or math.hypot(north[0], north[2]) < 1e-6:
        return None
    # A vector aligned with local geographic north must give zero, regardless
    # of grid convergence. This is a direction, not a wind-corrected command.
    angle = math.degrees(math.atan2(vector[2], vector[0]) - math.atan2(north[2], north[0])) % 360
    return 0.0 if angle >= 360 else angle  # Tiny negative round-off can wrap to 360.


@dataclass(frozen=True, slots=True)
class FlightStatus:
    unit_id: str
    group_id: str
    sample_time_s: float | None
    altitude_msl_m: float
    altitude_agl_m: float | None
    groundspeed_mps: float | None
    vertical_speed_mps: float | None
    heading_true_deg: float | None
    track_true_deg: float | None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FlightStatus:
        unit_id, group_id = payload.get("unit_id"), payload.get("group_id")
        if not isinstance(unit_id, str) or not unit_id.startswith("UNIT:") or not unit_id[5:]:
            raise ValueError("Flight status requires a UNIT: id")
        if not isinstance(group_id, str) or not group_id.startswith("GROUP:") or not group_id[6:]:
            raise ValueError("Flight status requires a GROUP: id")
        altitude = _number(payload.get("altitude_msl_m"), "altitude_msl_m", required=True)
        terrain = _number(payload.get("terrain_elevation_m"), "terrain_elevation_m")
        velocity = _vector(payload.get("velocity_mps"), "velocity_mps")
        forward = _vector(payload.get("forward"), "forward")
        north = _vector(payload.get("true_north"), "true_north")
        speed = math.hypot(velocity[0], velocity[2]) if velocity is not None else None
        return cls(
            unit_id=unit_id, group_id=group_id,
            sample_time_s=_number(payload.get("sample_time_s"), "sample_time_s"),
            altitude_msl_m=altitude,
            # Do not invent a sea-level terrain fallback or clamp reported data.
            altitude_agl_m=altitude - terrain if terrain is not None else None,
            groundspeed_mps=speed,
            vertical_speed_mps=velocity[1] if velocity is not None else None,
            heading_true_deg=_direction(forward, north),
            track_true_deg=_direction(velocity, north) if speed is not None and speed >= MIN_TRACK_SPEED_MPS else None,
        )


def format_flight_status(status: FlightStatus) -> str:
    """English imperial-unit cockpit/console readout with explicit references."""
    def altitude(value: float | None) -> str:
        return "N/A" if value is None else f"{value / METERS_PER_FOOT:,.0f} ft"

    def direction(value: float | None) -> str:
        return "N/A" if value is None else f"{round(value, 1) % 360:05.1f} deg TRUE"

    speed = "N/A" if status.groundspeed_mps is None else f"{status.groundspeed_mps / MPS_PER_KNOT:.1f} kt GS"
    vertical = "N/A" if status.vertical_speed_mps is None else f"{status.vertical_speed_mps * 60 / METERS_PER_FOOT:+.0f} ft/min"
    track = direction(status.track_true_deg)
    if status.groundspeed_mps is not None and status.groundspeed_mps < MIN_TRACK_SPEED_MPS:
        track = "N/A (GS below 1 m/s)"
    return (
        f"Flight status | Reference: {status.unit_id.removeprefix('UNIT:')}\n"
        f"Altitude: {altitude(status.altitude_msl_m)} MSL (geometric) | {altitude(status.altitude_agl_m)} AGL (terrain)\n"
        f"Groundspeed: {speed} (not IAS/TAS)\n"
        f"Heading: {direction(status.heading_true_deg)} | Track: {track}\n"
        f"Vertical speed: {vertical} (+ climb / - descent)"
    )
