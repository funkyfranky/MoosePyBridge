"""Deterministic Mission Editor route-conformance copilot.

The copilot reports sustained deviations; it does not grade the pilot. Waypoint
altitude is an arrival constraint, not an immediately commanded step or a rigid
linear profile. Route speed is compared with ground speed because DCS waypoint
speed is not Hornet cockpit IAS. Ambiguous route references produce no warning.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .flight_routes import FlightGroupRoute
from .flight_status import FlightStatus, METERS_PER_FOOT, MPS_PER_KNOT
from .navigation import NavigationSolution


METERS_PER_NM = 1852.0


@dataclass(frozen=True, slots=True)
class CopilotProfile:
    altitude_warning_ft: float = 300.0
    altitude_recovery_ft: float = 150.0
    speed_warning_kt: float = 20.0
    speed_recovery_kt: float = 10.0
    cross_track_warning_nm: float = 0.5
    cross_track_recovery_nm: float = 0.25
    sustain_s: float = 10.0
    reminder_cooldown_s: float = 60.0
    nominal_climb_fpm: float = 1000.0
    nominal_descent_fpm: float = 1500.0
    stabilization_distance_nm: float = 1.0
    vertical_speed_smoothing_s: float = 5.0
    vertical_notice_s: float = 60.0
    target_waypoint_max_agl_m: float = 10.0

    def __post_init__(self) -> None:
        pairs = (
            ("altitude", self.altitude_recovery_ft, self.altitude_warning_ft),
            ("speed", self.speed_recovery_kt, self.speed_warning_kt),
            ("cross_track", self.cross_track_recovery_nm, self.cross_track_warning_nm),
        )
        for name, recovery, warning in pairs:
            if (not math.isfinite(recovery) or not math.isfinite(warning)
                    or recovery < 0 or warning <= recovery):
                raise ValueError(f"Copilot {name} thresholds require 0 <= recovery < warning")
        for name, value in (("sustain_s", self.sustain_s),
                            ("reminder_cooldown_s", self.reminder_cooldown_s),
                            ("nominal_climb_fpm", self.nominal_climb_fpm),
                            ("nominal_descent_fpm", self.nominal_descent_fpm),
                            ("vertical_speed_smoothing_s", self.vertical_speed_smoothing_s)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Copilot {name} must be positive and finite")
        for name, value in (("stabilization_distance_nm", self.stabilization_distance_nm),
                            ("vertical_notice_s", self.vertical_notice_s),
                            ("target_waypoint_max_agl_m", self.target_waypoint_max_agl_m)):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Copilot {name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class CopilotSnapshot:
    unit_id: str
    from_waypoint_index: int
    target_waypoint_index: int
    target_name: str
    leg_excluded_reason: str | None
    altitude_excluded_reason: str | None
    altitude_reference: str | None
    departure_altitude_m: float | None
    planned_altitude_m: float | None
    actual_altitude_m: float | None
    remaining_distance_m: float
    nominal_start_distance_m: float | None
    time_to_guidance_start_s: float | None
    vertical_guidance_due: bool | None
    time_to_constraint_s: float | None
    required_vertical_speed_mps: float | None
    actual_vertical_speed_mps: float | None
    predicted_altitude_m: float | None
    planned_groundspeed_mps: float | None
    actual_groundspeed_mps: float | None
    cross_track_m: float | None
    reached_waypoint_indexes: tuple[int, ...]
    route_complete: bool

    @property
    def altitude_delta_ft(self) -> float | None:
        if self.planned_altitude_m is None or self.actual_altitude_m is None:
            return None
        return (self.actual_altitude_m - self.planned_altitude_m) / METERS_PER_FOOT

    def predicted_altitude_delta_ft(self, vertical_speed_mps: float | None = None) -> float | None:
        if self.planned_altitude_m is None or self.actual_altitude_m is None:
            return None
        if self.time_to_constraint_s is None:
            return self.altitude_delta_ft if self.departure_altitude_m == self.planned_altitude_m else None
        rate = self.actual_vertical_speed_mps if vertical_speed_mps is None else vertical_speed_mps
        if rate is None and self.time_to_constraint_s > 0:
            return None
        predicted = self.actual_altitude_m + (rate or 0.0) * self.time_to_constraint_s
        return (predicted - self.planned_altitude_m) / METERS_PER_FOOT

    @property
    def speed_delta_kt(self) -> float | None:
        if self.planned_groundspeed_mps is None or self.actual_groundspeed_mps is None:
            return None
        return (self.actual_groundspeed_mps - self.planned_groundspeed_mps) / MPS_PER_KNOT

    @property
    def cross_track_nm(self) -> float | None:
        return None if self.cross_track_m is None else self.cross_track_m / METERS_PER_NM


@dataclass(frozen=True, slots=True)
class CopilotAdvisory:
    kind: str
    text: str
    priority: int
    urgency: str
    ttl_s: float
    dedupe_key: str
    recovery: bool = False


@dataclass(slots=True)
class _Deviation:
    started_at: float
    active: bool = False
    last_advisory_at: float | None = None


def _normal_leg(route: FlightGroupRoute, solution: NavigationSolution) -> str | None:
    start = route.waypoints[solution.from_waypoint_index - 1]
    target = route.waypoints[solution.target_waypoint_index - 1]
    values = (start.waypoint_type, start.action, target.waypoint_type, target.action)
    normalized = " ".join(str(value or "").lower() for value in values)
    if "takeoff" in normalized:
        return "takeoff leg"
    if "land" in normalized:
        return "landing leg"
    return None


def _target_altitude_exclusion(target, profile: CopilotProfile) -> str | None:
    height = target.height_agl_m
    if (profile.target_waypoint_max_agl_m > 0 and height is not None
            and height < profile.target_waypoint_max_agl_m):
        return (f"probable target waypoint below "
                f"{profile.target_waypoint_max_agl_m:g} m AGL")
    return None


def build_copilot_snapshot(
    route: FlightGroupRoute,
    solution: NavigationSolution,
    status: FlightStatus,
    profile: CopilotProfile | None = None,
) -> CopilotSnapshot:
    """Build one read-only actual-versus-plan comparison for the active leg."""
    start = route.waypoints[solution.from_waypoint_index - 1]
    target = route.waypoints[solution.target_waypoint_index - 1]
    profile = profile or CopilotProfile()
    reason = _normal_leg(route, solution)
    altitude_reason = reason or _target_altitude_exclusion(target, profile)
    departure_altitude = planned_altitude = actual_altitude = None
    altitude_reference = None
    start_distance = time_to_start = time_to_constraint = None
    required_vertical_speed = predicted_altitude = None
    vertical_guidance_due = None
    planned_speed = None
    if reason is None:
        if altitude_reason is None:
            start_ref = (start.altitude_type or "").upper()
            target_ref = (target.altitude_type or "").upper()
            if (start.altitude_m is not None and target.altitude_m is not None
                    and start_ref == target_ref and start_ref in {"BARO", "RADIO"}):
                departure_altitude = start.altitude_m
                planned_altitude = target.altitude_m
                altitude_reference = "MSL" if start_ref == "BARO" else "AGL"
                actual_altitude = status.altitude_msl_m if start_ref == "BARO" else status.altitude_agl_m
                planned_change = target.altitude_m - start.altitude_m
                groundspeed = status.groundspeed_mps
                if groundspeed is not None and groundspeed >= 1.0:
                    stabilization_m = profile.stabilization_distance_nm * METERS_PER_NM
                    rate_fpm = (profile.nominal_climb_fpm if planned_change > 0
                                else profile.nominal_descent_fpm)
                    nominal_rate_mps = rate_fpm * METERS_PER_FOOT / 60
                    start_distance = stabilization_m + groundspeed * abs(planned_change) / nominal_rate_mps
                    time_to_start = max(0.0, solution.distance_m - start_distance) / groundspeed
                    vertical_guidance_due = (abs(planned_change) < 1.0
                                             or solution.distance_m <= start_distance + 1e-6)
                    time_to_constraint = max(0.0, solution.distance_m - stabilization_m) / groundspeed
                    if actual_altitude is not None:
                        if time_to_constraint > 0:
                            required_vertical_speed = (target.altitude_m - actual_altitude) / time_to_constraint
                        if status.vertical_speed_mps is not None:
                            predicted_altitude = (actual_altitude
                                                  + status.vertical_speed_mps * time_to_constraint)
                        elif time_to_constraint == 0:
                            predicted_altitude = actual_altitude
                elif abs(planned_change) < 1.0:
                    vertical_guidance_due = True
        planned_speed = (target.speed_mps
                         if target.speed_mps is not None and target.speed_mps > 0 else None)
    return CopilotSnapshot(
        unit_id=status.unit_id,
        from_waypoint_index=solution.from_waypoint_index,
        target_waypoint_index=solution.target_waypoint_index,
        target_name=solution.target_name,
        leg_excluded_reason=reason,
        altitude_excluded_reason=altitude_reason,
        altitude_reference=altitude_reference,
        departure_altitude_m=departure_altitude,
        planned_altitude_m=planned_altitude,
        actual_altitude_m=actual_altitude,
        remaining_distance_m=solution.distance_m,
        nominal_start_distance_m=start_distance,
        time_to_guidance_start_s=time_to_start,
        vertical_guidance_due=vertical_guidance_due,
        time_to_constraint_s=time_to_constraint,
        required_vertical_speed_mps=required_vertical_speed,
        actual_vertical_speed_mps=status.vertical_speed_mps,
        predicted_altitude_m=predicted_altitude,
        planned_groundspeed_mps=planned_speed,
        actual_groundspeed_mps=status.groundspeed_mps,
        cross_track_m=None if reason else solution.cross_track_m,
        reached_waypoint_indexes=solution.reached_waypoint_indexes,
        route_complete=solution.route_complete,
    )


class CopilotEvaluator:
    """Stateful hysteresis/cooldown evaluator for one player-group session."""

    def __init__(self, profile: CopilotProfile):
        self.profile = profile
        self._deviations: dict[str, _Deviation] = {}
        self._announced_waypoints: set[int] = set()
        self._route_complete_announced = False
        self._leg: tuple[int, int] | None = None
        self._vertical_guidance_latched = False
        self._vertical_notice_announced = False
        self._vertical_start_announced = False
        self._smoothed_vertical_speed_mps: float | None = None
        self._vertical_sample_at: float | None = None

    def reset(self) -> None:
        self._deviations.clear()
        self._announced_waypoints.clear()
        self._route_complete_announced = False
        self._leg = None
        self._vertical_guidance_latched = False
        self._vertical_notice_announced = False
        self._vertical_start_announced = False
        self._smoothed_vertical_speed_mps = None
        self._vertical_sample_at = None

    def _projected_altitude_delta(self, snapshot: CopilotSnapshot, now: float) -> float | None:
        leg = (snapshot.from_waypoint_index, snapshot.target_waypoint_index)
        if leg != self._leg:
            self._leg = leg
            self._vertical_guidance_latched = False
            self._vertical_notice_announced = False
            self._vertical_start_announced = False
            self._smoothed_vertical_speed_mps = None
            self._vertical_sample_at = None
            self._deviations.pop("altitude", None)
        raw = snapshot.actual_vertical_speed_mps
        if raw is not None:
            if self._smoothed_vertical_speed_mps is None or self._vertical_sample_at is None:
                self._smoothed_vertical_speed_mps = raw
            else:
                elapsed = max(0.0, now - self._vertical_sample_at)
                alpha = 1.0 - math.exp(-elapsed / self.profile.vertical_speed_smoothing_s)
                self._smoothed_vertical_speed_mps += alpha * (raw - self._smoothed_vertical_speed_mps)
            self._vertical_sample_at = now
        if snapshot.vertical_guidance_due:
            self._vertical_guidance_latched = True
        if not self._vertical_guidance_latched:
            return None
        return snapshot.predicted_altitude_delta_ft(self._smoothed_vertical_speed_mps)

    @staticmethod
    def _altitude_warning(snapshot: CopilotSnapshot, value: float) -> str:
        target_ft = snapshot.planned_altitude_m / METERS_PER_FOOT
        remaining_nm = snapshot.remaining_distance_m / METERS_PER_NM
        required = snapshot.required_vertical_speed_mps
        if required is None:
            instruction = "Adjust altitude"
            rate = "required vertical speed unavailable"
        else:
            required_fpm = required * 60 / METERS_PER_FOOT
            instruction = "Climb" if required_fpm > 50 else "Descend" if required_fpm < -50 else "Level"
            rate = f"required vertical speed {required_fpm:+,.0f} feet per minute"
        return (
            f"Altitude at {snapshot.target_name} is projected {abs(value):,.0f} feet "
            f"{'above' if value > 0 else 'below'} target. {instruction} toward "
            f"{target_ft:,.0f} feet {snapshot.altitude_reference}; "
            f"{remaining_nm:.1f} nautical miles remain, {rate}."
        )

    def _vertical_plan_advisories(self, snapshot: CopilotSnapshot) -> list[CopilotAdvisory]:
        start = snapshot.departure_altitude_m
        target = snapshot.planned_altitude_m
        actual = snapshot.actual_altitude_m
        if start is None or target is None or actual is None or abs(target - start) < 1.0:
            return []
        target_ft = target / METERS_PER_FOOT
        reference = snapshot.altitude_reference
        actual_error_ft = (actual - target) / METERS_PER_FOOT
        direction = "climb" if target > start else "descent"
        if not snapshot.vertical_guidance_due:
            remaining = snapshot.time_to_guidance_start_s
            if (self._vertical_notice_announced or remaining is None
                    or remaining > self.profile.vertical_notice_s
                    or abs(actual_error_ft) <= self.profile.altitude_recovery_ft):
                return []
            self._vertical_notice_announced = True
            if remaining >= 45:
                timing = ("about one minute" if remaining < 90
                          else f"about {round(remaining / 60):.0f} minutes")
            else:
                timing = f"about {max(5, round(remaining / 5) * 5):.0f} seconds"
            return [CopilotAdvisory(
                "vertical_notice",
                f"Expect {direction} to {target_ft:,.0f} feet {reference} in {timing} "
                f"for {snapshot.target_name}.",
                35, "routine", 15, "copilot:vertical-notice",
            )]
        if self._vertical_start_announced:
            return []
        self._vertical_start_announced = True
        if abs(actual_error_ft) <= self.profile.altitude_recovery_ft:
            return []
        required = snapshot.required_vertical_speed_mps
        if required is None:
            verb = "Begin climb" if target > actual else "Begin descent"
            rate = "Required vertical speed is unavailable."
        else:
            required_fpm = required * 60 / METERS_PER_FOOT
            climbing = required_fpm > 50
            descending = required_fpm < -50
            current_fpm = ((snapshot.actual_vertical_speed_mps or 0.0)
                           * 60 / METERS_PER_FOOT)
            if climbing:
                verb = "Continue climb" if current_fpm > 100 else "Begin climb"
                rate = f"Required climb rate is {abs(required_fpm):,.0f} feet per minute."
            elif descending:
                verb = "Continue descent" if current_fpm < -100 else "Begin descent"
                rate = f"Required descent rate is {abs(required_fpm):,.0f} feet per minute."
            else:
                verb = "Adjust altitude"
                rate = ""
        return [CopilotAdvisory(
            "vertical_start",
            f"{verb} to {target_ft:,.0f} feet {reference} for {snapshot.target_name}. "
            f"{rate}".rstrip(),
            55, "routine", 20, "copilot:vertical-start",
        )]

    def _metric(
        self,
        *,
        kind: str,
        value: float | None,
        warning: float,
        recovery: float,
        now: float,
        warning_text,
        recovery_text: str,
        priority: int,
    ) -> list[CopilotAdvisory]:
        state = self._deviations.get(kind)
        if value is None:
            self._deviations.pop(kind, None)
            return []
        magnitude = abs(value)
        if state is not None and state.active and magnitude <= recovery:
            self._deviations.pop(kind, None)
            return [CopilotAdvisory(
                kind, recovery_text, 30, "routine", 12, f"copilot:{kind}", recovery=True,
            )]
        if magnitude <= warning:
            if state is not None and not state.active:
                self._deviations.pop(kind, None)
            return []
        if state is None:
            state = _Deviation(started_at=now)
            self._deviations[kind] = state
            return []
        if not state.active:
            if now - state.started_at < self.profile.sustain_s:
                return []
            state.active = True
        elif (state.last_advisory_at is not None
              and now - state.last_advisory_at < self.profile.reminder_cooldown_s):
            return []
        state.last_advisory_at = now
        return [CopilotAdvisory(
            kind, warning_text(value), priority, "urgent", 20, f"copilot:{kind}",
        )]

    def update(self, snapshot: CopilotSnapshot, now: float) -> tuple[CopilotAdvisory, ...]:
        if not math.isfinite(now):
            raise ValueError("Copilot sample time must be finite")
        projected_altitude_delta = self._projected_altitude_delta(snapshot, now)
        advisories: list[CopilotAdvisory] = []
        for index in snapshot.reached_waypoint_indexes:
            if index not in self._announced_waypoints:
                self._announced_waypoints.add(index)
                suffix = "" if snapshot.route_complete else f" Continue to {snapshot.target_name}."
                advisories.append(CopilotAdvisory(
                    "waypoint", f"Waypoint {index} reached.{suffix}",
                    40, "routine", 15, "copilot:waypoint",
                ))
        if snapshot.route_complete and not self._route_complete_announced:
            self._route_complete_announced = True
            advisories.append(CopilotAdvisory(
                "route_complete", "The planned route is complete horizontally. Landing status is not evaluated.",
                45, "routine", 15, "copilot:route-complete",
            ))
        advisories.extend(self._vertical_plan_advisories(snapshot))
        p = self.profile
        advisories.extend(self._metric(
            kind="altitude", value=projected_altitude_delta,
            warning=p.altitude_warning_ft, recovery=p.altitude_recovery_ft, now=now,
            warning_text=lambda value: self._altitude_warning(snapshot, value),
            recovery_text=f"Vertical path is back on target for {snapshot.target_name}.", priority=70,
        ))
        advisories.extend(self._metric(
            kind="speed", value=snapshot.speed_delta_kt,
            warning=p.speed_warning_kt, recovery=p.speed_recovery_kt, now=now,
            warning_text=lambda value: (
                f"Ground speed is {abs(value):.0f} knots {'fast' if value > 0 else 'slow'} "
                f"compared with the planned route speed. "
                f"{'Reduce' if value > 0 else 'Increase'} speed to "
                f"{snapshot.planned_groundspeed_mps / MPS_PER_KNOT:.0f} knots ground speed."
            ),
            recovery_text="Ground speed is back within the planned route tolerance.", priority=60,
        ))
        advisories.extend(self._metric(
            kind="cross_track", value=snapshot.cross_track_nm,
            warning=p.cross_track_warning_nm, recovery=p.cross_track_recovery_nm, now=now,
            warning_text=lambda value: (
                f"You are {abs(value):.2f} nautical miles {'right' if value > 0 else 'left'} of course. "
                "Correct toward the planned route."
            ),
            recovery_text="Cross-track error is back within the planned route tolerance.", priority=65,
        ))
        return tuple(sorted(advisories, key=lambda item: item.priority, reverse=True))


def format_copilot_status(
    snapshot: CopilotSnapshot,
    *,
    monitoring: bool,
    text_enabled: bool,
    radio_enabled: bool,
) -> str:
    def altitude(value: float | None) -> str:
        return "N/A" if value is None else f"{value / METERS_PER_FOOT:,.0f} ft"

    def speed(value: float | None) -> str:
        return "N/A" if value is None else f"{value / MPS_PER_KNOT:.1f} kt"

    def vertical_speed(value: float | None) -> str:
        return "N/A" if value is None else f"{value * 60 / METERS_PER_FOOT:+,.0f} ft/min"

    speed_delta = snapshot.speed_delta_kt
    cross = snapshot.cross_track_nm
    cross_text = "N/A"
    if cross is not None:
        side = "right" if cross > 0 else "left" if cross < 0 else "on track"
        cross_text = f"{abs(cross):.2f} NM {side}"
    text = (
        f"Copilot monitoring: {'ACTIVE' if monitoring else 'STOPPED'}\n"
        f"Text output: {'ENABLED' if text_enabled else 'DISABLED'} | "
        f"Radio output: {'ENABLED' if radio_enabled else 'DISABLED'}\n\n"
        f"Leg: WP {snapshot.from_waypoint_index} -> WP {snapshot.target_waypoint_index} | "
        f"Target: {snapshot.target_name}\n"
    )
    if snapshot.leg_excluded_reason:
        text += f"Route-conformance evaluation: suspended ({snapshot.leg_excluded_reason})."
        return text
    if snapshot.altitude_excluded_reason:
        vertical = f"Vertical guidance: SUSPENDED ({snapshot.altitude_excluded_reason})\n\n"
    else:
        if snapshot.vertical_guidance_due is True:
            guidance = "ACTIVE"
        elif snapshot.vertical_guidance_due is False:
            start = snapshot.nominal_start_distance_m
            guidance = ("PENDING" if start is None
                        else f"PENDING until approximately {start / METERS_PER_NM:.1f} NM from target")
        else:
            guidance = "N/A"
        vertical = (
            f"Target altitude: {altitude(snapshot.planned_altitude_m)} {snapshot.altitude_reference or ''}\n"
            f"Actual altitude: {altitude(snapshot.actual_altitude_m)} {snapshot.altitude_reference or ''}\n"
            f"Vertical guidance: {guidance}\n"
            f"Time to vertical guidance: "
            f"{'N/A' if snapshot.time_to_guidance_start_s is None else f'{snapshot.time_to_guidance_start_s:.0f} s'}\n"
            f"Distance to target: {snapshot.remaining_distance_m / METERS_PER_NM:.2f} NM | "
            f"Time to stabilization point: {'N/A' if snapshot.time_to_constraint_s is None else f'{snapshot.time_to_constraint_s:.0f} s'}\n"
            f"Required vertical speed: {vertical_speed(snapshot.required_vertical_speed_mps)} | "
            f"Current vertical speed: {vertical_speed(snapshot.actual_vertical_speed_mps)}\n"
            f"Instantaneous projected altitude: {altitude(snapshot.predicted_altitude_m)} "
            f"{snapshot.altitude_reference or ''}\n\n"
        )
    text += vertical + (
        f"Planned GS: {speed(snapshot.planned_groundspeed_mps)} | "
        f"Actual GS: {speed(snapshot.actual_groundspeed_mps)}\n"
        f"Speed deviation: {'N/A' if speed_delta is None else f'{speed_delta:+.1f} kt'}\n"
        f"Cross-track error: {cross_text}"
    )
    return text
