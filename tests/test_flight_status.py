from copy import deepcopy
from dataclasses import replace
import math

import pytest

from moosebridge import FlightStatus, format_flight_status


def payload():
    return {
        "unit_id": "UNIT:Hornet-1", "group_id": "GROUP:Hornet", "sample_time_s": 100,
        "altitude_msl_m": 3048, "terrain_elevation_m": 304.8,
        "velocity_mps": {"x": 0, "y": 5.08, "z": 1852 / 3600 * 250},
        "forward": {"x": 0, "y": 0, "z": 1},
        "true_north": {"x": 222, "y": 0, "z": 0},
    }


def test_live_quantities_and_english_units():
    status = FlightStatus.from_payload(payload())
    assert status.altitude_agl_m == pytest.approx(2743.2)
    assert status.groundspeed_mps == pytest.approx(1852 / 3600 * 250)
    assert status.vertical_speed_mps == 5.08
    assert format_flight_status(status) == (
        "Flight status | Reference: Hornet-1\n"
        "Altitude: 10,000 ft MSL (geometric) | 9,000 ft AGL (terrain)\n"
        "Groundspeed: 250.0 kt GS (not IAS/TAS)\n"
        "Heading: 090.0 deg TRUE | Track: 090.0 deg TRUE\n"
        "Vertical speed: +1000 ft/min (+ climb / - descent)"
    )


@pytest.mark.parametrize("bearing", [0, 90, 180, 270, 359.99])
@pytest.mark.parametrize("convergence", [-17, 0, 23])
def test_true_directions_correct_for_grid_convergence(bearing, convergence):
    data = payload()
    angle, north = math.radians(bearing + convergence), math.radians(convergence)
    data["forward"] = {"x": math.cos(angle), "y": 0.2, "z": math.sin(angle)}
    data["velocity_mps"] = {"x": 100 * math.cos(angle), "y": -20, "z": 100 * math.sin(angle)}
    data["true_north"] = {"x": 222 * math.cos(north), "y": 0, "z": 222 * math.sin(north)}
    status = FlightStatus.from_payload(data)
    assert min(abs(status.heading_true_deg - bearing), abs(status.heading_true_deg - bearing - 360)) < 1e-9
    assert status.track_true_deg == pytest.approx(status.heading_true_deg)
    assert status.groundspeed_mps == pytest.approx(100)  # Excludes vertical motion.
    if bearing == 359.99:
        assert "Heading: 000.0 deg TRUE" in format_flight_status(status)


def test_heading_and_track_are_independent():
    data = payload()
    data["forward"] = {"x": 1, "y": 0, "z": 0}
    status = FlightStatus.from_payload(data)
    assert status.heading_true_deg == 0 and status.track_true_deg == 90


@pytest.mark.parametrize("speed,has_track", [(0, False), (0.99, False), (1, True)])
def test_track_is_unavailable_at_low_horizontal_speed(speed, has_track):
    data = payload()
    data["velocity_mps"] = {"x": speed, "y": 100, "z": 0}
    status = FlightStatus.from_payload(data)
    assert (status.track_true_deg is not None) == has_track
    assert ("GS below 1 m/s" in format_flight_status(status)) != has_track


def test_missing_optional_telemetry_is_not_invented():
    data = {"unit_id": "UNIT:Hornet-1", "group_id": "GROUP:Hornet", "altitude_msl_m": 0}
    status = FlightStatus.from_payload(data)
    assert status.altitude_msl_m == 0 and status.altitude_agl_m is None
    assert status.groundspeed_mps is None and status.vertical_speed_mps is None
    assert status.heading_true_deg is None and status.track_true_deg is None
    assert "0 ft MSL (geometric) | N/A AGL (terrain)" in format_flight_status(status)
    assert "Groundspeed: N/A" in format_flight_status(status)


def test_zero_terrain_negative_altitude_and_vertical_forward_vector():
    data = payload()
    data.update(altitude_msl_m=-10, terrain_elevation_m=0, forward={"x": 0, "y": 1, "z": 0})
    status = FlightStatus.from_payload(data)
    assert status.altitude_agl_m == -10 and status.heading_true_deg is None
    assert status.track_true_deg == 90
    data["true_north"] = {"x": 0, "y": 0, "z": 0}
    assert FlightStatus.from_payload(data).track_true_deg is None


@pytest.mark.parametrize("field,value", [
    ("altitude_msl_m", None), ("altitude_msl_m", float("nan")),
    ("terrain_elevation_m", float("inf")), ("sample_time_s", True),
    ("velocity_mps", {}), ("velocity_mps", {"x": 1, "y": 0, "z": float("nan")}),
    ("forward", []), ("true_north", {"x": 1, "y": 0}),
    ("unit_id", "UNIT:"), ("group_id", "OTHER:Hornet"),
])
def test_invalid_data_is_rejected(field, value):
    data = deepcopy(payload())
    data[field] = value
    with pytest.raises(ValueError):
        FlightStatus.from_payload(data)


def test_user_defined_names_are_preserved():
    status = replace(FlightStatus.from_payload(payload()), unit_id="UNIT:\u00dcberflug")
    assert "Reference: \u00dcberflug" in format_flight_status(status)
