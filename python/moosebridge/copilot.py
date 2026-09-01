"""Deterministic Mission Editor route-conformance copilot.

The copilot reports sustained deviations; it does not grade the pilot. Route
speed is compared with ground speed because DCS waypoint speed is not Hornet
cockpit IAS. Unsupported or ambiguous route references produce no warning.
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
                            ("reminder_cooldown_s", self.reminder_cooldown_s)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Copilot {name} must be positive and finite")


@dataclass(frozen=True, slots=True)
class CopilotSnapshot:
    unit_id: str
    from_waypoint_index: int
    target_waypoint_index: int
    target_name: str
    leg_excluded_reason: str | None
    altitude_reference: str | None
    planned_altitude_m: float | None
    actual_altitude_m: float | None
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


def build_copilot_snapshot(
    route: FlightGroupRoute,
    solution: NavigationSolution,
    status: FlightStatus,
) -> CopilotSnapshot:
    """Build one read-only actual-versus-plan comparison for the active leg."""
    reason = _normal_leg(route, solution)
    start = route.waypoints[solution.from_waypoint_index - 1]
    target = route.waypoints[solution.target_waypoint_index - 1]
    planned_altitude = actual_altitude = None
    altitude_reference = None
    planned_speed = None
    if reason is None:
        start_ref = (start.altitude_type or "").upper()
        target_ref = (target.altitude_type or "").upper()
        if (start.altitude_m is not None and target.altitude_m is not None
                and start_ref == target_ref and start_ref in {"BARO", "RADIO"}
                and solution.along_track_m is not None and solution.leg_length_m > 0):
            progress = min(1.0, max(0.0, solution.along_track_m / solution.leg_length_m))
            planned_altitude = start.altitude_m + progress * (target.altitude_m - start.altitude_m)
            altitude_reference = "MSL" if start_ref == "BARO" else "AGL"
            actual_altitude = status.altitude_msl_m if start_ref == "BARO" else status.altitude_agl_m
        planned_speed = (target.speed_mps
                         if target.speed_mps is not None and target.speed_mps > 0 else None)
    return CopilotSnapshot(
        unit_id=status.unit_id,
        from_waypoint_index=solution.from_waypoint_index,
        target_waypoint_index=solution.target_waypoint_index,
        target_name=solution.target_name,
        leg_excluded_reason=reason,
        altitude_reference=altitude_reference,
        planned_altitude_m=planned_altitude,
        actual_altitude_m=actual_altitude,
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

    def reset(self) -> None:
        self._deviations.clear()
        self._announced_waypoints.clear()
        self._route_complete_announced = False

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
        p = self.profile
        reference = snapshot.altitude_reference or ""
        planned_ft = (None if snapshot.planned_altitude_m is None
                      else snapshot.planned_altitude_m / METERS_PER_FOOT)
        advisories.extend(self._metric(
            kind="altitude", value=snapshot.altitude_delta_ft,
            warning=p.altitude_warning_ft, recovery=p.altitude_recovery_ft, now=now,
            warning_text=lambda value: (
                f"You are {abs(value):,.0f} feet {'above' if value > 0 else 'below'} the planned vertical profile. "
                f"{'Descend' if value > 0 else 'Climb'} to rejoin "
                f"{planned_ft:,.0f} feet {reference}."
            ),
            recovery_text="Altitude is back within the planned vertical profile.", priority=70,
        ))
        advisories.extend(self._metric(
            kind="speed", value=snapshot.speed_delta_kt,
            warning=p.speed_warning_kt, recovery=p.speed_recovery_kt, now=now,
            warning_text=lambda value: (
                f"Ground speed is {abs(value):.0f} knots {'fast' if value > 0 else 'slow'} "
                f"compared with the planned route speed. {'Reduce' if value > 0 else 'Increase'} speed."
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

    altitude_delta = snapshot.altitude_delta_ft
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
    text += (
        f"Planned altitude: {altitude(snapshot.planned_altitude_m)} {snapshot.altitude_reference or ''}\n"
        f"Actual altitude: {altitude(snapshot.actual_altitude_m)} {snapshot.altitude_reference or ''}\n"
        f"Altitude deviation: {'N/A' if altitude_delta is None else f'{altitude_delta:+,.0f} ft'}\n\n"
        f"Planned GS: {speed(snapshot.planned_groundspeed_mps)} | "
        f"Actual GS: {speed(snapshot.actual_groundspeed_mps)}\n"
        f"Speed deviation: {'N/A' if speed_delta is None else f'{speed_delta:+.1f} kt'}\n"
        f"Cross-track error: {cross_text}"
    )
    return text
