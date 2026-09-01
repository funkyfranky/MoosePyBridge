from __future__ import annotations

import pytest

from moosebridge.copilot import (
    CopilotEvaluator,
    CopilotProfile,
    build_copilot_snapshot,
    format_copilot_status,
)
from moosebridge.flight_routes import FlightGroupRoute
from moosebridge.flight_status import FlightStatus
from moosebridge.navigation import NavigationSolution


def route(*, first_type="Turning Point", altitude_type="BARO"):
    return FlightGroupRoute.from_payload({
        "opsgroup_id": "OPSGROUP:Hornet", "group_id": "GROUP:Hornet",
        "route_source": "mission_editor", "coalition": "blue",
        "waypoints": [
            {"index": 1, "name": "WP 1", "x": 0, "z": 0, "latitude": 0, "longitude": 0,
             "altitude_m": 1000, "altitude_type": altitude_type, "speed_mps": 100,
             "type": first_type},
            {"index": 2, "name": "WP 2", "x": 10000, "z": 0, "latitude": 0.1, "longitude": 0,
             "altitude_m": 2000, "altitude_type": altitude_type, "speed_mps": 120,
             "type": "Turning Point"},
            {"index": 3, "name": "WP 3", "x": 20000, "z": 0, "latitude": 0.2, "longitude": 0,
             "altitude_m": 3000, "altitude_type": altitude_type, "speed_mps": 130,
             "type": "Turning Point"},
        ],
    })


def solution(*, along=5000, cross=0, reached=(), complete=False):
    return NavigationSolution(
        from_waypoint_index=1, target_waypoint_index=2, target_name="WP 2",
        distance_m=5000, bearing_true_deg=90, cross_track_m=cross,
        along_track_m=along, leg_length_m=10000,
        reached_waypoint_indexes=reached, route_complete=complete,
    )


def status(*, altitude=1500, agl=1400, gs=120):
    return FlightStatus(
        unit_id="UNIT:Hornet-1", group_id="GROUP:Hornet", sample_time_s=10,
        altitude_msl_m=altitude, altitude_agl_m=agl, groundspeed_mps=gs,
        vertical_speed_mps=0, heading_true_deg=90, track_true_deg=90,
    )


def test_snapshot_interpolates_baro_altitude_and_uses_target_waypoint_speed_as_gs():
    snapshot = build_copilot_snapshot(route(), solution(), status(altitude=1600, gs=130))
    assert snapshot.planned_altitude_m == 1500 and snapshot.altitude_reference == "MSL"
    assert snapshot.actual_altitude_m == 1600
    assert snapshot.altitude_delta_ft == pytest.approx(328.084)
    assert snapshot.planned_groundspeed_mps == 120
    assert snapshot.speed_delta_kt == pytest.approx(19.438445)


def test_radio_altitude_uses_agl_and_ambiguous_or_takeoff_legs_are_silent():
    radio = build_copilot_snapshot(route(altitude_type="RADIO"), solution(), status(agl=1600))
    assert radio.altitude_reference == "AGL" and radio.actual_altitude_m == 1600
    takeoff = build_copilot_snapshot(route(first_type="TakeOffParkingHot"), solution(cross=2000), status())
    assert takeoff.leg_excluded_reason == "takeoff leg"
    assert takeoff.planned_altitude_m is None and takeoff.planned_groundspeed_mps is None
    assert takeoff.cross_track_m is None


def test_sustained_warning_hysteresis_recovery_and_cooldown():
    profile = CopilotProfile(sustain_s=10, reminder_cooldown_s=60)
    evaluator = CopilotEvaluator(profile)
    high = build_copilot_snapshot(route(), solution(), status(altitude=1700))
    assert evaluator.update(high, 0) == ()
    assert evaluator.update(high, 9.9) == ()
    warning = evaluator.update(high, 10)
    assert [item.kind for item in warning] == ["altitude"]
    assert "above" in warning[0].text and warning[0].priority == 70
    assert evaluator.update(high, 69.9) == ()
    assert evaluator.update(high, 70)[0].kind == "altitude"
    recovered = build_copilot_snapshot(route(), solution(), status(altitude=1530))
    result = evaluator.update(recovered, 71)
    assert len(result) == 1 and result[0].recovery and "back within" in result[0].text
    assert evaluator.update(recovered, 72) == ()


def test_speed_cross_track_and_waypoint_announcements_are_independent_and_prioritized():
    evaluator = CopilotEvaluator(CopilotProfile(sustain_s=1))
    snapshot = build_copilot_snapshot(
        route(), solution(cross=1852, reached=(2,)), status(gs=140),
    )
    first = evaluator.update(snapshot, 0)
    assert [item.kind for item in first] == ["waypoint"]
    second = evaluator.update(snapshot, 1)
    assert [item.kind for item in second] == ["cross_track", "speed"]
    assert "right of course" in second[0].text and "fast" in second[1].text
    assert evaluator.update(snapshot, 2) == ()  # Waypoint is never announced twice.

    complete = build_copilot_snapshot(
        route(), solution(reached=(3,), complete=True), status(),
    )
    final = evaluator.update(complete, 3)
    assert [item.kind for item in final[:2]] == ["route_complete", "waypoint"]
    assert all(item.recovery for item in final[2:])
    assert final[1].text == "Waypoint 3 reached."


def test_status_output_explains_settings_plan_actual_and_excluded_legs():
    snapshot = build_copilot_snapshot(route(), solution(cross=-926), status(altitude=1600, gs=130))
    text = format_copilot_status(snapshot, monitoring=True, text_enabled=True, radio_enabled=False)
    assert "Copilot monitoring: ACTIVE" in text
    assert "Text output: ENABLED | Radio output: DISABLED" in text
    assert "Planned altitude: 4,921 ft MSL" in text
    assert "Cross-track error: 0.50 NM left" in text
    excluded = build_copilot_snapshot(route(first_type="TakeOffParkingHot"), solution(), status())
    assert "suspended (takeoff leg)" in format_copilot_status(
        excluded, monitoring=False, text_enabled=True, radio_enabled=True,
    )
