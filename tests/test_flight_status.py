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
        "true_airspeed_mps": 1852 / 3600 * 270,
        "estimated_ias_mps": 1852 / 3600 * 240,
        "mach_number": 0.42,
        "temperature_c": 15, "pressure_hpa": 1013.25,
        "magnetic_declination_deg": 6, "flightgroup_state": "Airborne",
    }


def test_live_quantities_and_english_units():
    status = FlightStatus.from_payload(payload())
    assert status.altitude_agl_m == pytest.approx(2743.2)
    assert status.groundspeed_mps == pytest.approx(1852 / 3600 * 250)
    assert status.vertical_speed_mps == 5.08
    assert status.true_airspeed_mps == pytest.approx(1852 / 3600 * 270)
    assert status.estimated_ias_mps == pytest.approx(1852 / 3600 * 240)
    assert status.mach_number == 0.42
    assert status.temperature_c == 15 and status.pressure_hpa == 1013.25
    assert status.magnetic_declination_deg == 6 and status.flightgroup_state == "Airborne"
    assert format_flight_status(status) == (
        "Flight status | Reference: Hornet-1\n"
        "FLIGHTGROUP FSM: Airborne\n"
        "Altitude: 10,000 ft MSL | 9,000 ft AGL\n"
        "Vertical speed: +1,000 ft/min (climb)\n"
        "Temperature: 15.0 C | Pressure: 1013.2 hPa / 29.92 inHg\n\n"
        "IAS: 240.0 kt | TAS: 270.0 kt\n"
        "GS: 250.0 kt | Mach: 0.420\n\n"
        "Heading: 084.0 deg MAG | 090.0 deg TRUE\n"
        "Track: 084.0 deg MAG | 090.0 deg TRUE"
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
        assert "000.0 deg TRUE" in format_flight_status(status)
        assert f"{(bearing - 6) % 360:05.1f} deg MAG" in format_flight_status(status)


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
    assert status.true_airspeed_mps is status.estimated_ias_mps is status.mach_number is None
    assert "0 ft MSL | N/A AGL" in format_flight_status(status)
    assert "IAS: N/A | TAS: N/A" in format_flight_status(status)
    assert "GS: N/A | Mach: N/A" in format_flight_status(status)
    assert "FLIGHTGROUP FSM: N/A" in format_flight_status(status)
    assert "Temperature: N/A | Pressure: N/A" in format_flight_status(status)
    assert "Heading: N/A MAG | N/A" in format_flight_status(status)
    assert format_flight_status(status).endswith("N/A = unavailable.")


def test_positionable_groundspeed_is_used_without_inventing_air_data_or_track():
    data = payload()
    data["groundspeed_mps"] = 200
    status = FlightStatus.from_payload(data)
    assert status.groundspeed_mps == 200 and status.track_true_deg == 90
    data.pop("velocity_mps")
    for field in ("true_airspeed_mps", "estimated_ias_mps", "mach_number"):
        data.pop(field)
    status = FlightStatus.from_payload(data)
    assert status.groundspeed_mps == 200 and status.track_true_deg is None
    assert status.true_airspeed_mps is status.estimated_ias_mps is status.mach_number is None


def test_zero_is_a_valid_speed_and_mach_not_missing_data():
    data = payload()
    data.update(groundspeed_mps=0, true_airspeed_mps=0, estimated_ias_mps=0, mach_number=0,
                velocity_mps={"x": 0, "y": 0, "z": 0})
    text = format_flight_status(FlightStatus.from_payload(data))
    assert "IAS: 0.0 kt | TAS: 0.0 kt" in text and "GS: 0.0 kt | Mach: 0.000" in text
    assert "Vertical speed: +0 ft/min (level)" in text
    assert "Track: N/A (GS below 1 m/s)" in text


@pytest.mark.parametrize("vertical,label", [(-5.08, "-1,000 ft/min (descent)"), (0, "+0 ft/min (level)")])
def test_vertical_motion_is_readable(vertical, label):
    data = payload()
    data["velocity_mps"]["y"] = vertical
    assert f"Vertical speed: {label}" in format_flight_status(FlightStatus.from_payload(data))


@pytest.mark.parametrize("declination", [-12, 0, 6, 179.9, -179.9])
def test_magnetic_directions_subtract_declination_and_wrap(declination):
    data = payload()
    data["magnetic_declination_deg"] = declination
    status = FlightStatus.from_payload(data)
    expected = (90 - declination) % 360
    text = format_flight_status(status)
    assert f"Heading: {expected:05.1f} deg MAG | 090.0 deg TRUE" in text
    assert f"Track: {expected:05.1f} deg MAG | 090.0 deg TRUE" in text


@pytest.mark.parametrize("field,value", [
    ("pressure_hpa", 0), ("pressure_hpa", -1), ("pressure_hpa", float("inf")),
    ("temperature_c", float("nan")), ("magnetic_declination_deg", 181),
    ("magnetic_declination_deg", -181), ("flightgroup_state", ""),
    ("flightgroup_state", "Air\nborne"), ("flightgroup_state", 42),
])
def test_environment_and_fsm_values_are_validated(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(ValueError, match=field):
        FlightStatus.from_payload(data)


@pytest.mark.parametrize("hpa,inhg", [(1013.25, "29.92"), (1000, "29.53"), (800, "23.62")])
def test_pressure_is_shown_in_hpa_and_inches_of_mercury(hpa, inhg):
    data = payload()
    data["pressure_hpa"] = hpa
    text = format_flight_status(FlightStatus.from_payload(data))
    assert f"Pressure: {hpa:.1f} hPa / {inhg} inHg" in text


@pytest.mark.parametrize("field", ["groundspeed_mps", "true_airspeed_mps", "estimated_ias_mps", "mach_number"])
@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), True, "200"])
def test_air_data_rejects_negative_nonfinite_or_non_numeric_values(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(ValueError, match=field):
        FlightStatus.from_payload(data)


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
