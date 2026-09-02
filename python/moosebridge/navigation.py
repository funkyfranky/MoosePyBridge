"""Deterministic, read-only progress along a DCS-local flight route.

Distance and cross-track error use horizontal DCS x/z coordinates, matching the
straight F10 route segments. Bearing uses geographic coordinates and true north.
This tracker has no knowledge of the active cockpit waypoint or landing state.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .flight_routes import FlightGroupRoute


def _finite(value: float, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _bearing_true(latitude: float, longitude: float, target_lat: float, target_lon: float) -> float | None:
    lat1, lat2 = math.radians(latitude), math.radians(target_lat)
    delta_lon = math.radians(target_lon - longitude)
    east = math.sin(delta_lon) * math.cos(lat2)
    north = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    if math.hypot(east, north) < 1e-12:
        return None
    return math.degrees(math.atan2(east, north)) % 360.0


@dataclass(frozen=True, slots=True)
class NavigationSolution:
    from_waypoint_index: int
    target_waypoint_index: int
    target_name: str
    distance_m: float
    bearing_true_deg: float | None
    cross_track_m: float | None
    along_track_m: float | None
    leg_length_m: float
    reached_waypoint_indexes: tuple[int, ...]
    route_complete: bool

    @property
    def distance_nm(self) -> float:
        return self.distance_m / 1852.0

    @property
    def cross_track_side(self) -> str:
        if self.cross_track_m is None:
            return "undefined"
        if abs(self.cross_track_m) < 1.0:
            return "on track"
        return "right" if self.cross_track_m > 0 else "left"


class RouteNavigator:
    """Monotonically track ordered legs using proximity and bounded fly-by capture.

    WP 1 is the starting anchor by default, not an inferred cockpit selection.
    An end-plane crossing counts only within the capture radius laterally and
    between time-stamped samples at most max_sample_gap_s apart. Far-off-track
    positions and the first sample beyond a waypoint never trigger that rule.
    The final point is considered reached horizontally; this is not a landing
    or procedure-compliance check.
    """

    def __init__(
        self,
        route: FlightGroupRoute,
        *,
        initial_target_index: int = 2,
        capture_radius_m: float = 500.0,
        max_sample_gap_s: float = 10.0,
    ) -> None:
        if len(route.waypoints) < 2:
            raise ValueError("navigation requires at least two waypoints")
        if type(initial_target_index) is not int or not 2 <= initial_target_index <= len(route.waypoints):
            raise ValueError("initial_target_index must be in 2..waypoint_count")
        for name, value in (("capture_radius_m", capture_radius_m), ("max_sample_gap_s", max_sample_gap_s)):
            _finite(value, name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        for wp in route.waypoints:
            for name in ("x", "z", "latitude", "longitude"):
                _finite(getattr(wp, name), name)
            if not -90 <= wp.latitude <= 90 or not -180 <= wp.longitude <= 180:
                raise ValueError("route geographic coordinates outside bounds")
        self.route = route
        self.capture_radius_m = capture_radius_m
        self.max_sample_gap_s = max_sample_gap_s
        self._target = initial_target_index - 1
        self._complete = False
        self._previous: tuple[float, float, float | None] | None = None
        self._manual_capture_guard: int | None = None

    @property
    def target_waypoint_index(self) -> int:
        return self.route.waypoints[self._target].index

    def _select_target(self, target: int) -> bool:
        target = min(len(self.route.waypoints) - 1, max(1, target))
        if target == self._target:
            return False
        self._target = target
        self._complete = False
        self._previous = None
        # If Previous is selected while still inside that waypoint's capture
        # circle, do not immediately undo the manual selection. Automatic
        # capture is armed again after the aircraft leaves the circle once.
        self._manual_capture_guard = target
        return True

    def select_next_waypoint(self) -> bool:
        """Select the next route target without changing the route or cockpit."""
        return self._select_target(self._target + 1)

    def select_previous_waypoint(self) -> bool:
        """Select the previous route target; WP 1 remains the route anchor."""
        return self._select_target(self._target - 1)

    def _leg_metrics(self, x: float, z: float) -> tuple[float, float | None, float | None]:
        start, end = self.route.waypoints[self._target - 1:self._target + 1]
        dx, dz = end.x - start.x, end.z - start.z
        length = math.hypot(dx, dz)
        if length < 1e-6:
            return length, None, None
        px, pz = x - start.x, z - start.z
        along = (dx * px + dz * pz) / length
        # DCS grid x is northward and z eastward: positive is RIGHT of the leg.
        cross = (dx * pz - dz * px) / length
        return length, along, cross

    def update(
        self, *, x: float, z: float, latitude: float, longitude: float,
        mission_time: float | None = None,
    ) -> NavigationSolution:
        for name, value in (("x", x), ("z", z), ("latitude", latitude), ("longitude", longitude)):
            _finite(value, name)
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("position geographic coordinates outside bounds")
        if mission_time is not None:
            _finite(mission_time, "mission_time")
        reached: list[int] = []
        while not self._complete:
            target = self.route.waypoints[self._target]
            within_radius = math.hypot(x - target.x, z - target.z) <= self.capture_radius_m
            if self._manual_capture_guard == self._target:
                if within_radius:
                    break
                self._manual_capture_guard = None
            length, along, cross = self._leg_metrics(x, z)
            crossed = False
            if self._previous and along is not None and cross is not None and mission_time is not None:
                prev_x, prev_z, prev_time = self._previous
                if prev_time is not None and 0 < mission_time - prev_time <= self.max_sample_gap_s:
                    _, prev_along, prev_cross = self._leg_metrics(prev_x, prev_z)
                    if prev_along is not None and prev_cross is not None and prev_along < length <= along:
                        fraction = (length - prev_along) / (along - prev_along)
                        crossing_xte = prev_cross + fraction * (cross - prev_cross)
                        crossed = abs(crossing_xte) <= self.capture_radius_m
            if not within_radius and not crossed:
                break
            reached.append(target.index)
            self._previous = None  # Do not reuse one swept sample across several legs.
            if self._target == len(self.route.waypoints) - 1:
                self._complete = True
            else:
                self._target += 1
        target = self.route.waypoints[self._target]
        length, along, cross = self._leg_metrics(x, z)
        self._previous = (x, z, mission_time)
        return NavigationSolution(
            from_waypoint_index=self.route.waypoints[self._target - 1].index,
            target_waypoint_index=target.index,
            target_name=target.name,
            distance_m=math.hypot(x - target.x, z - target.z),
            bearing_true_deg=_bearing_true(latitude, longitude, target.latitude, target.longitude),
            cross_track_m=cross,
            along_track_m=along,
            leg_length_m=length,
            reached_waypoint_indexes=tuple(reached),
            route_complete=self._complete,
        )


def format_navigation_status(solution: NavigationSolution) -> str:
    bearing = "---" if solution.bearing_true_deg is None else f"{solution.bearing_true_deg:06.2f} deg true"
    cross = (
        "undefined (zero-length leg)" if solution.cross_track_m is None
        else f"{abs(solution.cross_track_m):.0f} m {solution.cross_track_side}"
    )
    return (
        f"NAV WP {solution.from_waypoint_index}->{solution.target_waypoint_index} "
        f"({solution.target_name}): distance={solution.distance_nm:.2f} NM | "
        f"bearing={bearing} | XTE={cross}"
    )
