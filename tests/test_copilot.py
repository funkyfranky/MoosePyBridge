from __future__ import annotations

from dataclasses import replace
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


def route(*, first_type="Turning Point", altitude_type="BARO",
          start_altitude_m=1000, target_altitude_m=2000, final_altitude_m=3000):
    return FlightGroupRoute.from_payload({
        "opsgroup_id": "OPSGROUP:Hornet", "group_id": "GROUP:Hornet",
        "route_source": "mission_editor", "coalition": "blue",
        "waypoints": [
            {"index": 1, "name": "WP 1", "x": 0, "z": 0, "latitude": 0, "longitude": 0,
             "altitude_m": start_altitude_m, "altitude_type": altitude_type, "speed_mps": 100,
             "type": first_type},
            {"index": 2, "name": "WP 2", "x": 10000, "z": 0, "latitude": 0.1, "longitude": 0,
             "altitude_m": target_altitude_m, "altitude_type": altitude_type, "speed_mps": 120,
             "type": "Turning Point"},
            {"index": 3, "name": "WP 3", "x": 20000, "z": 0, "latitude": 0.2, "longitude": 0,
             "altitude_m": final_altitude_m, "altitude_type": altitude_type, "speed_mps": 130,
             "type": "Turning Point"},
        ],
    })


def solution(*, along=5000, distance=5000, cross=0, reached=(), complete=False):
    return NavigationSolution(
        from_waypoint_index=1, target_waypoint_index=2, target_name="WP 2",
        distance_m=distance, bearing_true_deg=90, cross_track_m=cross,
        along_track_m=along, leg_length_m=10000,
        reached_waypoint_indexes=reached, route_complete=complete,
    )


def status(*, altitude=2000, agl=1900, gs=120, vs=0):
    return FlightStatus(
        unit_id="UNIT:Hornet-1", group_id="GROUP:Hornet", sample_time_s=10,
        altitude_msl_m=altitude, altitude_agl_m=agl, groundspeed_mps=gs,
        vertical_speed_mps=vs, heading_true_deg=90, track_true_deg=90,
    )


def test_snapshot_treats_baro_waypoint_altitude_as_target_and_uses_route_speed_as_gs():
    snapshot = build_copilot_snapshot(route(), solution(), status(altitude=1600, gs=130))
    assert snapshot.departure_altitude_m == 1000
    assert snapshot.planned_altitude_m == 2000 and snapshot.altitude_reference == "MSL"
    assert snapshot.actual_altitude_m == 1600
    assert snapshot.altitude_delta_ft == pytest.approx(-1312.336)
    assert snapshot.vertical_guidance_due
    assert snapshot.required_vertical_speed_mps == pytest.approx(16.517, rel=1e-3)
    assert snapshot.predicted_altitude_m == 1600
    assert snapshot.planned_groundspeed_mps == 120
    assert snapshot.speed_delta_kt == pytest.approx(19.438445)


def test_radio_altitude_uses_agl_and_ambiguous_or_takeoff_legs_are_silent():
    radio = build_copilot_snapshot(route(altitude_type="RADIO"), solution(), status(agl=1600))
    assert radio.altitude_reference == "AGL" and radio.actual_altitude_m == 1600
    takeoff = build_copilot_snapshot(route(first_type="TakeOffParkingHot"), solution(cross=2000), status())
    assert takeoff.leg_excluded_reason == "takeoff leg"
    assert takeoff.planned_altitude_m is None and takeoff.planned_groundspeed_mps is None
    assert takeoff.cross_track_m is None


@pytest.mark.parametrize("reference", ["RADIO", "BARO"])
def test_probable_ground_target_suppresses_only_vertical_guidance(reference):
    original = route(altitude_type=reference)
    terrain = 1000 if reference == "BARO" else None
    altitude = 1009 if reference == "BARO" else 9
    target = replace(original.waypoints[1], altitude_m=altitude,
                     terrain_elevation_m=terrain)
    target_route = replace(original, waypoints=(original.waypoints[0], target,
                                                original.waypoints[2]))
    snapshot = build_copilot_snapshot(
        target_route, solution(cross=926), status(gs=140), CopilotProfile(),
    )
    assert snapshot.altitude_excluded_reason == "probable target waypoint below 10 m AGL"
    assert snapshot.planned_altitude_m is None and snapshot.vertical_guidance_due is None
    assert snapshot.planned_groundspeed_mps == 120
    assert snapshot.cross_track_m == 926
    text = format_copilot_status(snapshot, monitoring=True, text_enabled=True, radio_enabled=True)
    assert "Vertical guidance: SUSPENDED (probable target waypoint below 10 m AGL)" in text
    assert "Planned GS:" in text and "Cross-track error:" in text


def test_target_height_threshold_is_configurable_and_exclusive():
    original = route(altitude_type="RADIO")
    target = replace(original.waypoints[1], altitude_m=10)
    exact = replace(original, waypoints=(original.waypoints[0], target, original.waypoints[2]))
    snapshot = build_copilot_snapshot(exact, solution(), status(), CopilotProfile())
    assert snapshot.altitude_excluded_reason is None  # Less than 10 m, not 10 m.
    disabled = build_copilot_snapshot(
        replace(original, waypoints=(original.waypoints[0], replace(target, altitude_m=0),
                                     original.waypoints[2])),
        solution(), status(), CopilotProfile(target_waypoint_max_agl_m=0),
    )
    assert disabled.altitude_excluded_reason is None


def test_altitude_constraint_waits_until_nominal_start_then_projects_arrival():
    profile = CopilotProfile(sustain_s=1, nominal_climb_fpm=1000,
                             stabilization_distance_nm=1)
    evaluator = CopilotEvaluator(profile)
    early = build_copilot_snapshot(
        route(), solution(distance=40000), status(altitude=1000, gs=120), profile,
    )
    assert early.vertical_guidance_due is False
    assert early.nominal_start_distance_m == pytest.approx(25474.8, rel=1e-3)
    assert evaluator.update(early, 0) == ()
    assert evaluator.update(early, 10) == ()  # Holding the departure altitude is valid here.

    notice = build_copilot_snapshot(
        route(), solution(distance=30000), status(altitude=1000, gs=120), profile,
    )
    advance = evaluator.update(notice, 10.5)
    assert [item.kind for item in advance] == ["vertical_notice"]
    assert "Expect climb" in advance[0].text
    assert evaluator.update(notice, 10.75) == ()

    due = build_copilot_snapshot(
        route(), solution(distance=25000), status(altitude=1000, gs=120), profile,
    )
    assert due.vertical_guidance_due is True
    start = evaluator.update(due, 11)
    assert [item.kind for item in start] == ["vertical_start"]
    assert "Begin climb" in start[0].text and "Required climb rate" in start[0].text
    warning = evaluator.update(due, 12)
    assert [item.kind for item in warning] == ["altitude"]
    assert "projected" in warning[0].text and "Climb toward" in warning[0].text

    required = due.required_vertical_speed_mps
    on_trajectory = build_copilot_snapshot(
        route(), solution(distance=24000), status(altitude=1000, gs=120, vs=required), profile,
    )
    # The evaluator smooths the rate, so the first correcting sample need not
    # instantly clear an active warning; sustained samples converge to recovery.
    recovered = ()
    for now in range(17, 47, 5):
        recovered = evaluator.update(on_trajectory, now)
        if recovered:
            break
    assert recovered and recovered[0].recovery


def test_6000_to_7000_feet_example_starts_at_six_nm_with_300_knot_groundspeed():
    feet = 0.3048
    groundspeed = 300 * 1852 / 3600
    profile = CopilotProfile(nominal_climb_fpm=1000, stabilization_distance_nm=1)
    flight_route = route(
        start_altitude_m=6000 * feet,
        target_altitude_m=7000 * feet,
        final_altitude_m=7000 * feet,
    )
    before = build_copilot_snapshot(
        flight_route, solution(distance=6.1 * 1852),
        status(altitude=6000 * feet, gs=groundspeed), profile,
    )
    assert before.nominal_start_distance_m / 1852 == pytest.approx(6.0)
    assert before.vertical_guidance_due is False
    at_start = build_copilot_snapshot(
        flight_route, solution(distance=6.0 * 1852),
        status(altitude=6000 * feet, gs=groundspeed), profile,
    )
    assert at_start.vertical_guidance_due is True
    assert at_start.required_vertical_speed_mps * 60 / feet == pytest.approx(1000)


def test_reaching_target_early_suppresses_the_start_instruction():
    profile = CopilotProfile(vertical_notice_s=60)
    evaluator = CopilotEvaluator(profile)
    notice = build_copilot_snapshot(
        route(), solution(distance=30000), status(altitude=1000, gs=120), profile,
    )
    assert [item.kind for item in evaluator.update(notice, 0)] == ["vertical_notice"]
    already_there = build_copilot_snapshot(
        route(), solution(distance=25000), status(altitude=2000, gs=120), profile,
    )
    assert evaluator.update(already_there, 1) == ()


def test_sustained_warning_hysteresis_recovery_and_cooldown():
    profile = CopilotProfile(sustain_s=10, reminder_cooldown_s=60)
    evaluator = CopilotEvaluator(profile)
    high = build_copilot_snapshot(route(), solution(), status(altitude=2100))
    start = evaluator.update(high, 0)
    assert [item.kind for item in start] == ["vertical_start"]
    assert "Begin descent" in start[0].text
    assert evaluator.update(high, 9.9) == ()
    warning = evaluator.update(high, 10)
    assert [item.kind for item in warning] == ["altitude"]
    assert "above" in warning[0].text and warning[0].priority == 70
    assert evaluator.update(high, 69.9) == ()
    assert evaluator.update(high, 70)[0].kind == "altitude"
    recovered = build_copilot_snapshot(route(), solution(), status(altitude=2030))
    result = evaluator.update(recovered, 71)
    assert len(result) == 1 and result[0].recovery and "back on target" in result[0].text
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
    assert "Reduce speed to 233 knots ground speed." in second[1].text
    assert evaluator.update(snapshot, 2) == ()  # Waypoint is never announced twice.

    complete = build_copilot_snapshot(
        route(), solution(reached=(3,), complete=True), status(),
    )
    final = evaluator.update(complete, 3)
    assert [item.kind for item in final[:2]] == ["route_complete", "waypoint"]
    assert all(item.recovery for item in final[2:])
    assert final[1].text == "Waypoint 3 reached."

    slow_evaluator = CopilotEvaluator(CopilotProfile(sustain_s=1))
    slow = build_copilot_snapshot(route(), solution(), status(gs=100))
    assert slow_evaluator.update(slow, 0) == ()
    slow_warning = slow_evaluator.update(slow, 1)
    assert any("Increase speed to 233 knots ground speed." in item.text
               for item in slow_warning)


def test_status_output_explains_settings_plan_actual_and_excluded_legs():
    snapshot = build_copilot_snapshot(route(), solution(cross=-926), status(altitude=1600, gs=130))
    text = format_copilot_status(snapshot, monitoring=True, text_enabled=True, radio_enabled=False)
    assert "Copilot monitoring: ACTIVE" in text
    assert "Text output: ENABLED | Radio output: DISABLED" in text
    assert "Target altitude: 6,562 ft MSL" in text
    assert "Vertical guidance: ACTIVE" in text
    assert "Required vertical speed:" in text
    assert "Cross-track error: 0.50 NM left" in text
    excluded = build_copilot_snapshot(route(first_type="TakeOffParkingHot"), solution(), status())
    assert "suspended (takeoff leg)" in format_copilot_status(
        excluded, monitoring=False, text_enabled=True, radio_enabled=True,
    )
