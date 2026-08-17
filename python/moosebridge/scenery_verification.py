"""Normalized geographic features eligible for DCS scenery verification."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping

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
