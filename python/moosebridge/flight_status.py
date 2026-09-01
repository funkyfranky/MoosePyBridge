"""Read-only DCS flight state and MOOSE air data, not cockpit instruments."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


METERS_PER_FOOT = 0.3048
MPS_PER_KNOT = 1852 / 3600
MIN_TRACK_SPEED_MPS = 1.0
INHG_PER_HPA = 0.0295299830714


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


def _nonnegative(value: Any, name: str) -> float | None:
    result = _number(value, name)
    if result is not None and result < 0:
        raise ValueError(f"Flight status {name} must be non-negative")
    return result


def _text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 120
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise ValueError(f"Flight status {name} must be a printable string")
    return value


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
    true_airspeed_mps: float | None = None
    estimated_ias_mps: float | None = None
    mach_number: float | None = None
    temperature_c: float | None = None
    pressure_hpa: float | None = None
    magnetic_declination_deg: float | None = None
    flightgroup_state: str | None = None

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
        horizontal_speed = math.hypot(velocity[0], velocity[2]) if velocity is not None else None
        speed = _nonnegative(payload.get("groundspeed_mps"), "groundspeed_mps")
        if speed is None:
            speed = horizontal_speed  # Older MOOSE versions can still supply GS.
        pressure = _number(payload.get("pressure_hpa"), "pressure_hpa")
        if pressure is not None and pressure <= 0:
            raise ValueError("Flight status pressure_hpa must be positive")
        declination = _number(payload.get("magnetic_declination_deg"), "magnetic_declination_deg")
        if declination is not None and abs(declination) > 180:
            raise ValueError("Flight status magnetic_declination_deg must be within -180..180")
        return cls(
            unit_id=unit_id, group_id=group_id,
            sample_time_s=_number(payload.get("sample_time_s"), "sample_time_s"),
            altitude_msl_m=altitude,
            # Do not invent a sea-level terrain fallback or clamp reported data.
            altitude_agl_m=altitude - terrain if terrain is not None else None,
            groundspeed_mps=speed,
            vertical_speed_mps=velocity[1] if velocity is not None else None,
            heading_true_deg=_direction(forward, north),
            track_true_deg=(_direction(velocity, north)
                            if horizontal_speed is not None and horizontal_speed >= MIN_TRACK_SPEED_MPS else None),
            true_airspeed_mps=_nonnegative(payload.get("true_airspeed_mps"), "true_airspeed_mps"),
            estimated_ias_mps=_nonnegative(payload.get("estimated_ias_mps"), "estimated_ias_mps"),
            mach_number=_nonnegative(payload.get("mach_number"), "mach_number"),
            temperature_c=_number(payload.get("temperature_c"), "temperature_c"),
            pressure_hpa=pressure,
            magnetic_declination_deg=declination,
            flightgroup_state=_text(payload.get("flightgroup_state"), "flightgroup_state"),
        )


def format_flight_status(status: FlightStatus) -> str:
    """English imperial-unit cockpit/console readout with explicit references."""
    def altitude(value: float | None) -> str:
        return "N/A" if value is None else f"{value / METERS_PER_FOOT:,.0f} ft"

    def direction(value: float | None) -> str:
        return "N/A" if value is None else f"{round(value, 1) % 360:05.1f} deg TRUE"

    def direction_pair(value: float | None) -> str:
        true = direction(value)
        if value is None or status.magnetic_declination_deg is None:
            return f"N/A MAG | {true}"
        magnetic = round(value - status.magnetic_declination_deg, 1) % 360
        return f"{magnetic:05.1f} deg MAG | {true}"

    def speed(value: float | None) -> str:
        return "N/A" if value is None else f"{value / MPS_PER_KNOT:.1f} kt"

    vertical = "N/A"
    if status.vertical_speed_mps is not None:
        fpm = round(status.vertical_speed_mps * 60 / METERS_PER_FOOT)
        motion = "climb" if fpm > 0 else "descent" if fpm < 0 else "level"
        vertical = f"{fpm:+,d} ft/min ({motion})"
    mach = "N/A" if status.mach_number is None else f"{status.mach_number:.3f}"
    track = direction_pair(status.track_true_deg)
    if status.groundspeed_mps is not None and status.groundspeed_mps < MIN_TRACK_SPEED_MPS:
        track = "N/A (GS below 1 m/s)"
    text = (
        f"Flight status | Reference: {status.unit_id.removeprefix('UNIT:')}\n"
        f"FLIGHTGROUP FSM: {status.flightgroup_state or 'N/A'}\n"
        f"Altitude: {altitude(status.altitude_msl_m)} MSL | {altitude(status.altitude_agl_m)} AGL\n"
        f"Vertical speed: {vertical}\n"
        f"Temperature: {'N/A' if status.temperature_c is None else f'{status.temperature_c:.1f} C'} | "
        f"Pressure: {'N/A' if status.pressure_hpa is None else f'{status.pressure_hpa:.1f} hPa / {status.pressure_hpa * INHG_PER_HPA:.2f} inHg'}\n\n"
        f"IAS: {speed(status.estimated_ias_mps)} | TAS: {speed(status.true_airspeed_mps)}\n"
        f"GS: {speed(status.groundspeed_mps)} | Mach: {mach}\n\n"
        f"Heading: {direction_pair(status.heading_true_deg)}\n"
        f"Track: {track}"
    )
    if "N/A" in text:
        text += "\nN/A = unavailable."
    return text
