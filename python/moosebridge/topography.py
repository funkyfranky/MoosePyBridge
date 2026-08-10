"""Static theater topography imported from external geographic sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Iterable


TOPOGRAPHY_LAYER_PREFIX = "topography_"
SUPPORTED_GEOMETRIES = frozenset({"Point", "LineString", "Polygon", "MultiLineString", "MultiPolygon"})


class TopographyLayer(StrEnum):
    """Map layers represented by the first theater-topography increment."""

    WATER = "topography_water"
    ROADS = "topography_roads"
    RAILWAYS = "topography_railways"
    SETTLEMENTS = "topography_settlements"
    INFRASTRUCTURE = "topography_infrastructure"
    BUILDINGS = "topography_buildings"
    LANDUSE = "topography_landuse"
    ADMINISTRATIVE_BOUNDARIES = "topography_administrative_boundaries"


@dataclass(slots=True, frozen=True)
class TopographyFeature:
    """One external or DCS-verified theater feature in WGS84 coordinates."""

    object_id: str
    layer: TopographyLayer
    category: str
    geometry: dict[str, Any]
    source: str
    confidence: float
    name: str | None = None
    source_id: str | None = None
    scenario_reference_year: int | None = None
    source_snapshot_date: str | None = None
    valid_from: int | None = None
    valid_to: int | None = None
    dcs_verified: bool = False
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.object_id.strip() or not self.category.strip() or not self.source.strip():
            raise ValueError("topography feature requires object_id, category, and source")
        if not 0 <= self.confidence <= 1:
            raise ValueError("topography confidence must be between zero and one")
        geometry_type = str(self.geometry.get("type") or "")
        if geometry_type not in SUPPORTED_GEOMETRIES:
            raise ValueError(f"unsupported topography geometry: {geometry_type or 'missing'}")
        if "coordinates" not in self.geometry:
            raise ValueError("topography geometry requires coordinates")
        if self.valid_from is not None and self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError("topography valid_from must not be after valid_to")

    def to_geojson_feature(self) -> dict[str, Any]:
        """Return this feature in the map server's GeoJSON convention."""

        properties = {
            "layer": self.layer.value,
            "object_id": self.object_id,
            "name": self.name,
            "object_type": "TOPOGRAPHY",
            "category": self.category,
            "coordinate_system": "WGS84",
            "source": self.source,
            "source_id": self.source_id,
            "confidence": self.confidence,
            "scenario_reference_year": self.scenario_reference_year,
            "source_snapshot_date": self.source_snapshot_date,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "dcs_verified": self.dcs_verified,
            **self.properties,
        }
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {key: value for key, value in properties.items() if value is not None},
        }

    @classmethod
    def from_geojson_feature(cls, feature: dict[str, Any]) -> TopographyFeature:
        """Parse one normalized topography GeoJSON feature."""

        if feature.get("type") != "Feature":
            raise ValueError("topography entry must be a GeoJSON Feature")
        properties = dict(feature.get("properties") or {})
        known = {
            "layer", "object_id", "name", "object_type", "category", "coordinate_system",
            "source", "source_id", "confidence", "scenario_reference_year", "source_snapshot_date", "valid_from", "valid_to",
            "dcs_verified",
        }
        return cls(
            object_id=str(properties.get("object_id") or ""),
            layer=TopographyLayer(str(properties.get("layer") or "")),
            category=str(properties.get("category") or ""),
            geometry=dict(feature.get("geometry") or {}),
            source=str(properties.get("source") or ""),
            confidence=float(properties.get("confidence", 0)),
            name=str(properties["name"]) if properties.get("name") is not None else None,
            source_id=str(properties["source_id"]) if properties.get("source_id") is not None else None,
            scenario_reference_year=_optional_int(properties.get("scenario_reference_year")),
            source_snapshot_date=str(properties["source_snapshot_date"]) if properties.get("source_snapshot_date") else None,
            valid_from=_optional_int(properties.get("valid_from")),
            valid_to=_optional_int(properties.get("valid_to")),
            dcs_verified=properties.get("dcs_verified") is True,
            properties={key: value for key, value in properties.items() if key not in known},
        )


@dataclass(slots=True, frozen=True)
class TheaterTopography:
    """Versioned static topography cache for one DCS terrain."""

    theater_id: str
    schema_version: int = 1
    scenario_reference_year: int | None = None
    source_snapshot_date: str | None = None
    generated_at: str | None = None
    bounds: tuple[float, float, float, float] | None = None
    features: tuple[TopographyFeature, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.theater_id.strip():
            raise ValueError("theater topography requires theater_id")
        if self.schema_version != 1:
            raise ValueError(f"unsupported topography schema version: {self.schema_version}")
        object_ids = [feature.object_id for feature in self.features]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("topography object_id values must be unique")

    def to_geojson(self) -> dict[str, Any]:
        """Serialize the complete theater cache as GeoJSON."""

        properties = {
            "schema": "moosebridge.theater_topography",
            "schema_version": self.schema_version,
            "theater_id": self.theater_id,
            "scenario_reference_year": self.scenario_reference_year,
            "source_snapshot_date": self.source_snapshot_date,
            "generated_at": self.generated_at,
            "bounds": list(self.bounds) if self.bounds else None,
            "feature_count": len(self.features),
            **self.metadata,
        }
        return {
            "type": "FeatureCollection",
            "features": [feature.to_geojson_feature() for feature in self.features],
            "properties": {key: value for key, value in properties.items() if value is not None},
        }

    @classmethod
    def from_geojson(cls, payload: dict[str, Any]) -> TheaterTopography:
        """Parse a normalized MooseBridge theater cache."""

        if payload.get("type") != "FeatureCollection":
            raise ValueError("topography cache must be a GeoJSON FeatureCollection")
        properties = dict(payload.get("properties") or {})
        if properties.get("schema") != "moosebridge.theater_topography":
            raise ValueError("not a MooseBridge theater-topography cache")
        raw_features = payload.get("features")
        if not isinstance(raw_features, list):
            raise ValueError("topography cache features must be a list")
        known = {"schema", "schema_version", "theater_id", "scenario_reference_year", "source_snapshot_date", "generated_at", "bounds", "feature_count"}
        bounds = properties.get("bounds")
        parsed_bounds = tuple(float(value) for value in bounds) if isinstance(bounds, list) and len(bounds) == 4 else None
        return cls(
            theater_id=str(properties.get("theater_id") or ""),
            schema_version=int(properties.get("schema_version") or 1),
            scenario_reference_year=_optional_int(properties.get("scenario_reference_year")),
            source_snapshot_date=str(properties["source_snapshot_date"]) if properties.get("source_snapshot_date") else None,
            generated_at=str(properties["generated_at"]) if properties.get("generated_at") else None,
            bounds=parsed_bounds,  # type: ignore[arg-type]
            features=tuple(TopographyFeature.from_geojson_feature(feature) for feature in raw_features),
            metadata={key: value for key, value in properties.items() if key not in known},
        )

    @classmethod
    def load(cls, path: str | Path) -> TheaterTopography:
        """Load a theater cache from disk."""

        with Path(path).open("r", encoding="utf-8") as stream:
            return cls.from_geojson(json.load(stream))

    def save(self, path: str | Path) -> Path:
        """Write the theater cache atomically enough for an offline import."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.to_geojson(), stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
        temporary.replace(target)
        return target

    def features_for_map(self) -> list[dict[str, Any]]:
        """Return detached GeoJSON features suitable for merging into a live picture."""

        return [feature.to_geojson_feature() for feature in self.features]


def merge_topography_features(
    picture: dict[str, Any],
    topography: TheaterTopography | None,
) -> dict[str, Any]:
    """Replace static topography features in a live picture without duplication."""

    features = picture.setdefault("features", [])
    if not isinstance(features, list):
        raise ValueError("picture features must be a list")
    features[:] = [
        feature for feature in features
        if not str((feature.get("properties") or {}).get("layer") or "").startswith(TOPOGRAPHY_LAYER_PREFIX)
    ]
    properties = picture.setdefault("properties", {})
    if topography is None:
        properties["topography_feature_count"] = 0
        properties.pop("topography_theater_id", None)
        properties.pop("topography_scenario_reference_year", None)
        properties.pop("topography_source_snapshot_date", None)
        return picture
    features.extend(topography.features_for_map())
    properties["topography_feature_count"] = len(topography.features)
    properties["topography_theater_id"] = topography.theater_id
    properties["topography_scenario_reference_year"] = topography.scenario_reference_year
    properties["topography_source_snapshot_date"] = topography.source_snapshot_date
    return picture


def feature_counts(features: Iterable[TopographyFeature]) -> dict[str, int]:
    """Return counts by normalized map layer."""

    counts: dict[str, int] = {}
    for feature in features:
        counts[feature.layer.value] = counts.get(feature.layer.value, 0) + 1
    return counts


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
