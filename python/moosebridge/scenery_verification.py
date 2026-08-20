"""Normalized geographic features eligible for DCS scenery verification."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from shapely.geometry import shape


SCENERY_VERIFICATION_ARTIFACT_KEYS = (
    "infrastructure_sites",
    "railway_infrastructure",
    "settlements",
    "transport_infrastructure",
)

_PREFIX_ARTIFACTS = {
    "ENERGY_SITE": "infrastructure_sites",
    "FUEL_STORAGE_SITE": "infrastructure_sites",
    "INDUSTRIAL_SITE": "infrastructure_sites",
    "MARITIME_SITE": "infrastructure_sites",
    "MILITARY_SITE": "infrastructure_sites",
    "RAILWAY_STATION": "railway_infrastructure",
    "RAILWAY_FREIGHT_TERMINAL": "railway_infrastructure",
    "RAILWAY_RAIL_YARD": "railway_infrastructure",
    "RAILWAY_DEPOT": "railway_infrastructure",
    "RAILWAY_JUNCTION": "railway_infrastructure",
    "RAILWAY_BRIDGE": "railway_infrastructure",
    "SETTLEMENT": "settlements",
    "BRIDGE": "transport_infrastructure",
    "JUNCTION": "transport_infrastructure",
}


@dataclass(slots=True, frozen=True)
class SceneryVerificationFeature:
    """One normalized theater feature that may map to fixed DCS scenery."""

    object_id: str
    name: str
    layer: str
    category: str
    geometry: dict[str, Any]
    latitude: float
    longitude: float
    source: str
    artifact_key: str
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.object_id.strip() or ":" not in self.object_id:
            raise ValueError("scenery verification feature requires a stable object id")
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ValueError("scenery verification feature coordinates are outside WGS84 bounds")
        if not self.artifact_key.strip():
            raise ValueError("scenery verification feature requires an artifact key")

    @classmethod
    def from_geojson_feature(
        cls,
        feature: Mapping[str, Any],
        *,
        artifact_key: str,
    ) -> "SceneryVerificationFeature":
        if feature.get("type") != "Feature":
            raise ValueError(f"{artifact_key} contains a non-Feature GeoJSON item")
        geometry = dict(feature.get("geometry") or {})
        properties = dict(feature.get("properties") or {})
        latitude, longitude = _feature_position(geometry, properties)
        object_id = str(properties.get("object_id") or "").strip()
        return cls(
            object_id=object_id,
            name=str(properties.get("name") or object_id),
            layer=str(properties.get("layer") or artifact_key),
            category=str(
                properties.get("site_kind")
                or properties.get("settlement_kind")
                or properties.get("railway_kind")
                or properties.get("category")
                or "unknown"
            ),
            geometry=geometry,
            latitude=latitude,
            longitude=longitude,
            source=str(properties.get("source") or "unknown"),
            artifact_key=artifact_key,
            properties=properties,
        )


@dataclass(slots=True, frozen=True)
class SceneryZoneAssignment:
    """One Mission Editor Assign As zone mapped to a fixed DCS scenery object."""

    feature_id: str
    zone_name: str
    zone_object_id: str
    scenery_object_id: str


@dataclass(slots=True, frozen=True)
class SceneryVerificationMarker:
    """One active F10 marker that positions a scenery verification survey."""

    source_id: str
    marker_id: str
    text: str
    note: str
    latitude: float
    longitude: float
    radius_m: float | None = None
    option_errors: tuple[str, ...] = ()
    x: float | None = None
    y: float | None = None
    z: float | None = None
    player_name: str | None = None
    coalition: str | None = None
    event_id: str | None = None
    mission_time: float | None = None


_VERIFICATION_MARKER_COMMAND = re.compile(
    r"^\s*(?:verify|verified)\s+([^\s]+)\s*$",
    re.IGNORECASE,
)
_VERIFICATION_MARKER_RADIUS = re.compile(
    r"^\s*radius\s*(?:=|:)?\s*(\d+(?:[.,]\d+)?)\s*(m|km)?\s*$",
    re.IGNORECASE,
)
_MAXIMUM_MARKER_RADIUS_M = 5_000.0


def scenery_verification_marker_from_event(
    event: Mapping[str, Any],
) -> SceneryVerificationMarker | None:
    """Parse a ``verify OBJECT_ID`` command from one normalized marker event."""

    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    event_name = str(event.get("event") or payload.get("event") or "")
    if event_name not in {"map.marker.added", "map.marker.changed"}:
        return None
    text = str(payload.get("text") or event.get("text") or "").strip()
    lines = text.splitlines()
    if not lines:
        return None
    match = _VERIFICATION_MARKER_COMMAND.fullmatch(lines[0])
    if match is None:
        return None
    latitude = _optional_float(payload.get("latitude", event.get("latitude")))
    longitude = _optional_float(payload.get("longitude", event.get("longitude")))
    marker_id = payload.get("marker_id", event.get("marker_id"))
    if latitude is None or longitude is None or marker_id is None:
        return None
    radius_m: float | None = None
    option_errors: list[str] = []
    note_lines: list[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.casefold().startswith("radius"):
            note_lines.append(stripped)
            continue
        radius_match = _VERIFICATION_MARKER_RADIUS.fullmatch(stripped)
        if radius_match is None:
            option_errors.append(f"invalid radius option: {stripped}")
            continue
        value = float(radius_match.group(1).replace(",", "."))
        if (radius_match.group(2) or "m").casefold() == "km":
            value *= 1_000
        if not 0 < value <= _MAXIMUM_MARKER_RADIUS_M:
            option_errors.append(
                f"radius must be greater than 0 and at most {_MAXIMUM_MARKER_RADIUS_M:g} m"
            )
            continue
        if radius_m is not None:
            option_errors.append("radius may only be specified once")
            continue
        radius_m = value
    return SceneryVerificationMarker(
        source_id=match.group(1),
        marker_id=str(marker_id),
        text=text,
        note="\n".join(note_lines),
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        option_errors=tuple(option_errors),
        x=_optional_float(payload.get("x", event.get("x"))),
        y=_optional_float(payload.get("y", event.get("y"))),
        z=_optional_float(payload.get("z", event.get("z"))),
        player_name=_optional_string(payload.get("player_name", event.get("player_name"))),
        coalition=_optional_string(payload.get("coalition", event.get("coalition"))),
        event_id=_optional_string(event.get("id")),
        mission_time=_optional_float(event.get("mission_time", payload.get("mission_time"))),
    )


def active_scenery_verification_markers(
    events: Iterable[Mapping[str, Any]],
) -> tuple[SceneryVerificationMarker, ...]:
    """Reconstruct active verification markers from retained marker events."""

    active: dict[str, SceneryVerificationMarker] = {}
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        event_name = str(event.get("event") or payload.get("event") or "")
        raw_marker_id = payload.get("marker_id", event.get("marker_id"))
        if raw_marker_id is None:
            continue
        marker_id = str(raw_marker_id)
        if event_name == "map.marker.removed":
            active.pop(marker_id, None)
            continue
        if event_name not in {"map.marker.added", "map.marker.changed"}:
            continue
        marker = scenery_verification_marker_from_event(event)
        if marker is None:
            active.pop(marker_id, None)
        else:
            active[marker_id] = marker
    return tuple(active.values())


def latest_scenery_verification_marker(
    events: Iterable[Mapping[str, Any]],
    source_id: str,
) -> SceneryVerificationMarker | None:
    """Return the newest active marker for one normalized theater feature."""

    normalized_source_id = source_id.strip().casefold()
    matching = [
        marker
        for marker in active_scenery_verification_markers(events)
        if marker.source_id.casefold() == normalized_source_id
    ]
    return matching[-1] if matching else None


def scenery_zone_assignments(
    feature_id: str,
    zones: Mapping[str, Mapping[str, Any]],
) -> tuple[SceneryZoneAssignment, ...]:
    """Read exact and DCS-numbered Assign As zones for one normalized feature."""

    normalized_feature_id = feature_id.strip()
    if not normalized_feature_id:
        raise ValueError("scenery assignment requires a normalized feature id")
    zone_name_pattern = re.compile(rf"^{re.escape(normalized_feature_id)}(?:-(\d+))?$")
    assignments: list[SceneryZoneAssignment] = []
    seen_scenery_ids: set[str] = set()
    for key, zone in zones.items():
        zone_name = str(zone.get("dcs_name") or zone.get("name") or key).strip()
        if zone_name.startswith("ZONE:"):
            zone_name = zone_name.removeprefix("ZONE:")
        match = zone_name_pattern.fullmatch(zone_name)
        if match is None:
            continue
        properties = zone.get("properties")
        if not isinstance(properties, Mapping):
            continue
        raw_object_id = next(
            (
                value
                for property_name, value in properties.items()
                if str(property_name).strip().casefold() == "object id"
            ),
            None,
        )
        scenery_object_id = _normalize_scenery_object_id(raw_object_id)
        if scenery_object_id is None or scenery_object_id in seen_scenery_ids:
            continue
        seen_scenery_ids.add(scenery_object_id)
        assignments.append(
            SceneryZoneAssignment(
                feature_id=normalized_feature_id,
                zone_name=zone_name,
                zone_object_id=str(zone.get("object_id") or key),
                scenery_object_id=scenery_object_id,
            )
        )
    return tuple(
        sorted(
            assignments,
            key=lambda item: _assignment_zone_sort_key(normalized_feature_id, item.zone_name),
        )
    )


def resolve_scenery_verification_feature(
    theater_id: str,
    object_id: str,
    artifact_paths: Mapping[str, str | Path],
) -> SceneryVerificationFeature | None:
    """Load one feature from its prefix-specific artifact without scanning all theater data."""

    normalized_id = object_id.strip()
    prefix = normalized_id.partition(":")[0]
    artifact_key = _PREFIX_ARTIFACTS.get(prefix)
    if artifact_key is None:
        supported = ", ".join(sorted(_PREFIX_ARTIFACTS))
        raise ValueError(
            f"object type {prefix or '<missing>'} cannot be verified against DCS scenery; "
            f"supported prefixes: {supported}"
        )
    path_value = artifact_paths.get(artifact_key)
    if path_value is None:
        raise ValueError(f"missing theater artifact path: {artifact_key}")
    path = Path(path_value)
    if not path.is_file():
        raise ValueError(f"theater artifact not found: {path}")
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")
    properties = dict(payload.get("properties") or {})
    artifact_theater = str(properties.get("theater_id") or "").strip()
    if artifact_theater and artifact_theater.casefold() != theater_id.casefold():
        raise ValueError(
            f"{artifact_key} belongs to theater {artifact_theater}, expected {theater_id}"
        )
    matches = [
        item
        for item in payload.get("features") or ()
        if isinstance(item, Mapping)
        and str((item.get("properties") or {}).get("object_id") or "").strip() == normalized_id
    ]
    if len(matches) > 1:
        raise ValueError(f"duplicate normalized theater feature id: {normalized_id}")
    if not matches:
        return None
    return SceneryVerificationFeature.from_geojson_feature(matches[0], artifact_key=artifact_key)


def _feature_position(
    geometry: Mapping[str, Any],
    properties: Mapping[str, Any],
) -> tuple[float, float]:
    latitude = _optional_float(properties.get("latitude"))
    longitude = _optional_float(properties.get("longitude"))
    if latitude is not None and longitude is not None:
        return latitude, longitude
    candidate = shape(geometry)
    if candidate.is_empty:
        raise ValueError("scenery verification feature has neither coordinates nor usable geometry")
    point = candidate.representative_point()
    return float(point.y), float(point.x)


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_scenery_object_id(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        normalized = str(int(value))
    else:
        normalized = str(value).strip()
    if not normalized:
        return None
    if normalized.upper().startswith("SCENERY:"):
        _, _, name = normalized.partition(":")
        return f"SCENERY:{name.strip()}" if name.strip() else None
    return f"SCENERY:{normalized}"


def _assignment_zone_sort_key(feature_id: str, zone_name: str) -> tuple[int, int]:
    if zone_name == feature_id:
        return 0, 0
    try:
        return 1, int(zone_name.removeprefix(f"{feature_id}-"))
    except ValueError:
        return 2, 0
