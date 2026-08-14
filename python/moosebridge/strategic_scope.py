"""Territory-derived geographic scope for strategic decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Any, Iterable

from shapely.geometry import Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .models import Territory


class StrategicScopeState(StrEnum):
    """Effective strategic ownership of a location."""

    BLUE = "blue"
    RED = "red"
    NEUTRAL = "neutral"
    CONTESTED = "contested"
    OUT_OF_SCOPE = "out_of_scope"


class OpposingTerritoryOverlapPolicy(StrEnum):
    """How intentional red/blue TERRITORY overlap is handled."""

    ERROR = "error"
    CONTESTED = "contested"


@dataclass(slots=True, frozen=True)
class StrategicScopeConfig:
    """Configuration for deriving mission scope from TERRITORY objects."""

    territory_ids: frozenset[str] | None = None
    opposing_overlap_policy: OpposingTerritoryOverlapPolicy = OpposingTerritoryOverlapPolicy.ERROR
    overlap_tolerance_m2: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.overlap_tolerance_m2) or self.overlap_tolerance_m2 < 0:
            raise ValueError("overlap_tolerance_m2 must be finite and non-negative")


@dataclass(slots=True, frozen=True)
class StrategicScopeIssue:
    """One actionable scope validation or data-quality finding."""

    severity: str
    code: str
    message: str
    territory_ids: tuple[str, ...] = ()
    overlap_area_m2: float | None = None


@dataclass(slots=True, frozen=True)
class StrategicTerritoryScope:
    """Resolved, non-overlapping strategic areas in DCS-local coordinates."""

    config: StrategicScopeConfig
    territory_ids: tuple[str, ...]
    blue: BaseGeometry
    red: BaseGeometry
    neutral: BaseGeometry
    contested: BaseGeometry
    included: BaseGeometry
    geographic_blue: BaseGeometry
    geographic_red: BaseGeometry
    geographic_neutral: BaseGeometry
    geographic_contested: BaseGeometry
    issues: tuple[StrategicScopeIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def overlap_area_m2(self) -> float:
        return float(self.contested.area)

    def require_valid(self) -> "StrategicTerritoryScope":
        """Raise when this scope must not be used for strategic decisions."""

        errors = [issue.message for issue in self.issues if issue.severity == "error"]
        if errors:
            raise StrategicScopeValidationError("; ".join(errors), self)
        return self

    def classify_point(self, x: float, z: float) -> StrategicScopeState:
        """Return effective scope ownership at a DCS-local point."""

        point = Point(float(x), float(z))
        if self.contested.covers(point):
            return StrategicScopeState.CONTESTED
        if self.blue.covers(point):
            return StrategicScopeState.BLUE
        if self.red.covers(point):
            return StrategicScopeState.RED
        if self.neutral.covers(point):
            return StrategicScopeState.NEUTRAL
        return StrategicScopeState.OUT_OF_SCOPE

    def classify_geographic_point(self, latitude: float, longitude: float) -> StrategicScopeState:
        """Return effective scope ownership at a WGS84 point."""

        point = Point(float(longitude), float(latitude))
        if self.geographic_contested.covers(point):
            return StrategicScopeState.CONTESTED
        if self.geographic_blue.covers(point):
            return StrategicScopeState.BLUE
        if self.geographic_red.covers(point):
            return StrategicScopeState.RED
        if self.geographic_neutral.covers(point):
            return StrategicScopeState.NEUTRAL
        return StrategicScopeState.OUT_OF_SCOPE

    def contains(self, x: float, z: float) -> bool:
        """Return whether a point belongs to the configured conflict area."""

        return self.included.covers(Point(float(x), float(z)))

    def counts(self) -> dict[str, int | float | bool]:
        """Return concise diagnostics suitable for logs and map metadata."""

        return {
            "territories": len(self.territory_ids),
            "valid": self.valid,
            "errors": sum(issue.severity == "error" for issue in self.issues),
            "warnings": sum(issue.severity == "warning" for issue in self.issues),
            "overlap_area_m2": round(self.overlap_area_m2, 3),
        }

    def to_geojson_features(self) -> list[dict[str, Any]]:
        """Return resolved WGS84 areas for the browser map."""

        features: list[dict[str, Any]] = []
        for state, geometry in (
            (StrategicScopeState.NEUTRAL, self.geographic_neutral),
            (StrategicScopeState.BLUE, self.geographic_blue),
            (StrategicScopeState.RED, self.geographic_red),
            (StrategicScopeState.CONTESTED, self.geographic_contested),
        ):
            if geometry.is_empty:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geometry),
                    "properties": {
                        "layer": "strategic_scope",
                        "object_id": f"STRATEGIC_SCOPE:{state.value}",
                        "name": _scope_label(state),
                        "object_type": "STRATEGIC_SCOPE",
                        "category": state.value,
                        "scope_state": state.value,
                        "coalition": (
                            state.value if state in {StrategicScopeState.BLUE, StrategicScopeState.RED} else None
                        ),
                        "valid": self.valid,
                        "overlap_area_m2": self.overlap_area_m2 if state is StrategicScopeState.CONTESTED else None,
                    },
                }
            )
        return features


class StrategicScopeValidationError(ValueError):
    """Raised when TERRITORY geometry is unsafe for strategic decisions."""

    def __init__(self, message: str, scope: StrategicTerritoryScope) -> None:
        super().__init__(message)
        self.scope = scope


def build_strategic_territory_scope(
    territories: Iterable[Territory],
    *,
    config: StrategicScopeConfig | None = None,
    strict: bool = True,
) -> StrategicTerritoryScope:
    """Resolve red/blue/neutral TERRITORY objects into one strategic scope.

    Red and blue always override neutral. Red/blue overlap is retained as a
    separate contested area, but is an error by default so accidental overlap
    cannot silently influence planning.
    """

    resolved_config = config or StrategicScopeConfig()
    selected = [
        territory
        for territory in territories
        if resolved_config.territory_ids is None or territory.object_id in resolved_config.territory_ids
    ]
    local_by_state: dict[str, list[BaseGeometry]] = {"blue": [], "red": [], "neutral": []}
    geographic_by_state: dict[str, list[BaseGeometry]] = {"blue": [], "red": [], "neutral": []}
    issues: list[StrategicScopeIssue] = []

    for territory in selected:
        coalition = _coalition_name(territory.coalition)
        if coalition is None:
            issues.append(
                StrategicScopeIssue(
                    "warning",
                    "territory_coalition_unsupported",
                    f"{territory.object_id} has unsupported coalition {territory.coalition!r} and is out of scope",
                    (territory.object_id,),
                )
            )
            continue
        local = _territory_geometry(territory, geographic=False)
        if local is None:
            issues.append(
                StrategicScopeIssue(
                    "error",
                    "territory_geometry_invalid",
                    f"{territory.object_id} has no valid local polygon or circle geometry",
                    (territory.object_id,),
                )
            )
            continue
        local_by_state[coalition].append(local)
        geographic = _territory_geometry(territory, geographic=True)
        if geographic is not None:
            geographic_by_state[coalition].append(geographic)
        else:
            issues.append(
                StrategicScopeIssue(
                    "warning",
                    "territory_wgs84_geometry_missing",
                    f"{territory.object_id} cannot be displayed as a resolved WGS84 scope area",
                    (territory.object_id,),
                )
            )

    blue_raw = _union(local_by_state["blue"])
    red_raw = _union(local_by_state["red"])
    neutral_raw = _union(local_by_state["neutral"])
    contested = blue_raw.intersection(red_raw)
    overlap_area = float(contested.area)
    if overlap_area > resolved_config.overlap_tolerance_m2:
        severity = (
            "error"
            if resolved_config.opposing_overlap_policy is OpposingTerritoryOverlapPolicy.ERROR
            else "warning"
        )
        issues.append(
            StrategicScopeIssue(
                severity,
                "opposing_territories_overlap",
                f"red and blue territories overlap by {overlap_area:.1f} m2",
                tuple(sorted(t.object_id for t in selected if _coalition_name(t.coalition) in {"blue", "red"})),
                overlap_area,
            )
        )
    elif overlap_area > 0:
        issues.append(
            StrategicScopeIssue(
                "warning",
                "opposing_territory_sliver",
                f"red and blue territories have a tolerated {overlap_area:.1f} m2 overlap sliver",
                overlap_area_m2=overlap_area,
            )
        )

    occupied = blue_raw.union(red_raw)
    included = occupied.union(neutral_raw)
    geographic_blue_raw = _union(geographic_by_state["blue"])
    geographic_red_raw = _union(geographic_by_state["red"])
    geographic_neutral_raw = _union(geographic_by_state["neutral"])
    geographic_contested = geographic_blue_raw.intersection(geographic_red_raw)
    geographic_occupied = geographic_blue_raw.union(geographic_red_raw)

    scope = StrategicTerritoryScope(
        config=resolved_config,
        territory_ids=tuple(sorted(t.object_id for t in selected)),
        blue=blue_raw.difference(contested),
        red=red_raw.difference(contested),
        neutral=neutral_raw.difference(occupied),
        contested=contested,
        included=included,
        geographic_blue=geographic_blue_raw.difference(geographic_contested),
        geographic_red=geographic_red_raw.difference(geographic_contested),
        geographic_neutral=geographic_neutral_raw.difference(geographic_occupied),
        geographic_contested=geographic_contested,
        issues=tuple(issues),
    )
    return scope.require_valid() if strict else scope


def _coalition_name(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    aliases = {"0": "neutral", "1": "red", "2": "blue", "neutrals": "neutral"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"blue", "red", "neutral"} else None


def _union(geometries: list[BaseGeometry]) -> BaseGeometry:
    return unary_union(geometries) if geometries else Polygon()


def _territory_geometry(territory: Territory, *, geographic: bool) -> BaseGeometry | None:
    if geographic:
        vertices = [
            (float(vertex.longitude), float(vertex.latitude))
            for vertex in territory.vertices
            if vertex.longitude is not None and vertex.latitude is not None
        ]
    else:
        vertices = [(float(vertex.x), float(vertex.z)) for vertex in territory.vertices]
    if len(vertices) >= 3:
        geometry: BaseGeometry = Polygon(vertices)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        return geometry if not geometry.is_empty and geometry.area > 0 else None

    if territory.radius is None or territory.radius <= 0:
        return None
    if geographic:
        if territory.latitude is None or territory.longitude is None:
            return None
        latitude_radius = territory.radius / 111_320.0
        longitude_scale = max(0.1, math.cos(math.radians(territory.latitude)))
        longitude_radius = latitude_radius / longitude_scale
        center = Point(territory.longitude, territory.latitude)
        circle = center.buffer(1.0, quad_segs=32)
        from shapely import affinity

        return affinity.scale(circle, xfact=longitude_radius, yfact=latitude_radius, origin=center)
    if territory.x is None or territory.z is None:
        return None
    return Point(territory.x, territory.z).buffer(territory.radius, quad_segs=32)


def _scope_label(state: StrategicScopeState) -> str:
    return {
        StrategicScopeState.BLUE: "Blue strategic area",
        StrategicScopeState.RED: "Red strategic area",
        StrategicScopeState.NEUTRAL: "Neutral strategic area",
        StrategicScopeState.CONTESTED: "Invalid red/blue overlap",
        StrategicScopeState.OUT_OF_SCOPE: "Out of scope",
    }[state]
