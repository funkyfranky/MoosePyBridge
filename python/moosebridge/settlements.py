"""Normalized settlements and bounded urban footprints for strategic planning."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .topography import TopographyFeature, TopographyLayer


SETTLEMENTS_SCHEMA = "moosebridge.settlements"
SETTLEMENTS_SCHEMA_VERSION = 1
URBAN_LANDUSE = frozenset({"residential", "commercial", "retail", "industrial"})


class SettlementKind(StrEnum):
    CITY = "city"
    TOWN = "town"


class SettlementSizeClass(StrEnum):
    METROPOLIS = "metropolis"
    LARGE_CITY = "large_city"
    MEDIUM_CITY = "medium_city"
    SMALL_CITY = "small_city"
    LAND_TOWN = "land_town"


class SettlementBoundaryKind(StrEnum):
    URBAN_FOOTPRINT = "urban_footprint"
    ADMINISTRATIVE = "administrative"
    POINT_ONLY = "point_only"


class SettlementImportanceTier(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOCAL = "local"


@dataclass(slots=True, frozen=True)
class Settlement:
    """One named city or town with a strategic size assessment."""

    settlement_id: str
    name: str
    kind: SettlementKind
    size_class: SettlementSizeClass
    geometry: dict[str, Any]
    latitude: float
    longitude: float
    source: str
    confidence: float
    population: int | None = None
    population_date: str | None = None
    urban_area_m2: float | None = None
    boundary_kind: SettlementBoundaryKind = SettlementBoundaryKind.POINT_ONLY
    size_class_source: str = "osm_place"
    importance_score: float = 0.0
    importance_tier: SettlementImportanceTier = SettlementImportanceTier.LOCAL
    source_ids: tuple[str, ...] = ()
    scenario_reference_year: int | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.settlement_id.strip() or not self.name.strip() or not self.source.strip():
            raise ValueError("settlement requires id, name, and source")
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ValueError("settlement coordinates are outside WGS84 bounds")
        if not 0 <= self.confidence <= 1:
            raise ValueError("settlement confidence must be between zero and one")
        if self.population is not None and self.population < 0:
            raise ValueError("settlement population must not be negative")
        if self.urban_area_m2 is not None and self.urban_area_m2 < 0:
            raise ValueError("settlement urban area must not be negative")
        if not 0 <= self.importance_score <= 100:
            raise ValueError("settlement importance score must be between zero and 100")

    def to_geojson_feature(self) -> dict[str, Any]:
        properties = {
            "layer": "settlements",
            "object_id": self.settlement_id,
            "name": self.name,
            "object_type": "SETTLEMENT",
            "category": self.kind.value,
            "settlement_kind": self.kind.value,
            "size_class": self.size_class.value,
            "size_class_source": self.size_class_source,
            "coordinate_system": "WGS84",
            "latitude": self.latitude,
            "longitude": self.longitude,
            "population": self.population,
            "population_date": self.population_date,
            "urban_area_m2": self.urban_area_m2,
            "boundary_kind": self.boundary_kind.value,
            "importance_score": round(self.importance_score, 3),
            "importance_tier": self.importance_tier.value,
            "source": self.source,
            "source_ids": list(self.source_ids),
            "confidence": self.confidence,
            "scenario_reference_year": self.scenario_reference_year,
            **self.properties,
        }
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {key: value for key, value in properties.items() if value is not None},
        }

    @classmethod
    def from_geojson_feature(cls, feature: Mapping[str, Any]) -> "Settlement":
        if feature.get("type") != "Feature":
            raise ValueError("settlement must be a GeoJSON Feature")
        properties = dict(feature.get("properties") or {})
        known = {
            "layer", "object_id", "name", "object_type", "category", "settlement_kind",
            "size_class", "size_class_source", "coordinate_system", "latitude", "longitude",
            "population", "population_date", "urban_area_m2", "boundary_kind",
            "importance_score", "importance_tier", "source", "source_ids", "confidence",
            "scenario_reference_year",
        }
        return cls(
            settlement_id=str(properties.get("object_id") or ""),
            name=str(properties.get("name") or ""),
            kind=SettlementKind(str(properties.get("settlement_kind") or properties.get("category") or "")),
            size_class=SettlementSizeClass(str(properties.get("size_class") or "")),
            geometry=dict(feature.get("geometry") or {}),
            latitude=float(properties.get("latitude") or 0),
            longitude=float(properties.get("longitude") or 0),
            source=str(properties.get("source") or ""),
            confidence=float(properties.get("confidence") or 0),
            population=_optional_int(properties.get("population")),
            population_date=_optional_string(properties.get("population_date")),
            urban_area_m2=_optional_float(properties.get("urban_area_m2")),
            boundary_kind=SettlementBoundaryKind(
                str(properties.get("boundary_kind") or SettlementBoundaryKind.POINT_ONLY.value)
            ),
            size_class_source=str(properties.get("size_class_source") or "osm_place"),
            importance_score=float(properties.get("importance_score") or 0),
            importance_tier=SettlementImportanceTier(
                str(properties.get("importance_tier") or SettlementImportanceTier.LOCAL.value)
            ),
            source_ids=tuple(str(value) for value in properties.get("source_ids") or ()),
            scenario_reference_year=_optional_int(properties.get("scenario_reference_year")),
            properties={key: value for key, value in properties.items() if key not in known},
        )


@dataclass(slots=True, frozen=True)
class TheaterSettlements:
    theater_id: str
    settlements: tuple[Settlement, ...] = ()
    schema_version: int = SETTLEMENTS_SCHEMA_VERSION
    scenario_reference_year: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.theater_id.strip():
            raise ValueError("settlements require theater_id")
        if self.schema_version != SETTLEMENTS_SCHEMA_VERSION:
            raise ValueError(f"unsupported settlements schema version: {self.schema_version}")
        ids = [settlement.settlement_id for settlement in self.settlements]
        if len(ids) != len(set(ids)):
            raise ValueError("settlement ids must be unique")

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [settlement.to_geojson_feature() for settlement in self.settlements],
            "properties": {
                "schema": SETTLEMENTS_SCHEMA,
                "schema_version": self.schema_version,
                "theater_id": self.theater_id,
                "scenario_reference_year": self.scenario_reference_year,
                "settlement_count": len(self.settlements),
                **self.metadata,
            },
        }

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.to_geojson(), stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
        temporary.replace(target)
        return target

    @classmethod
    def from_geojson(cls, payload: Mapping[str, Any]) -> "TheaterSettlements":
        if payload.get("type") != "FeatureCollection":
            raise ValueError("settlement artifact must be a GeoJSON FeatureCollection")
        properties = dict(payload.get("properties") or {})
        if properties.get("schema") != SETTLEMENTS_SCHEMA:
            raise ValueError("not a MooseBridge settlement artifact")
        known = {"schema", "schema_version", "theater_id", "scenario_reference_year", "settlement_count"}
        return cls(
            theater_id=str(properties.get("theater_id") or ""),
            schema_version=int(properties.get("schema_version") or SETTLEMENTS_SCHEMA_VERSION),
            scenario_reference_year=_optional_int(properties.get("scenario_reference_year")),
            settlements=tuple(Settlement.from_geojson_feature(item) for item in payload.get("features") or ()),
            metadata={key: value for key, value in properties.items() if key not in known},
        )

    @classmethod
    def load(cls, path: str | Path) -> "TheaterSettlements":
        with Path(path).open("r", encoding="utf-8") as stream:
            return cls.from_geojson(json.load(stream))


def build_settlements(
    features: Iterable[TopographyFeature],
    *,
    theater_id: str,
    urban_gap_m: float = 200.0,
    urban_simplify_m: float = 75.0,
) -> TheaterSettlements:
    """Build city and town objects using nearby connected urban land use."""

    try:
        from pyproj import Transformer
        from shapely.geometry import Point, mapping, shape
        from shapely.ops import transform, unary_union
        from shapely.strtree import STRtree
    except ImportError as exc:
        raise RuntimeError('settlement building requires: python -m pip install -e ".[topography]"') from exc

    materialized = tuple(features)
    anchors = [
        feature for feature in materialized
        if feature.layer is TopographyLayer.SETTLEMENTS
        and feature.category in {SettlementKind.CITY.value, SettlementKind.TOWN.value}
        and feature.name
    ]
    urban = [
        feature for feature in materialized
        if feature.layer is TopographyLayer.LANDUSE and feature.category in URBAN_LANDUSE
    ]
    to_metric = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    to_wgs84 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    projected_urban = []
    for feature in urban:
        geometry = shape(feature.geometry)
        if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        projected_urban.append(transform(to_metric.transform, geometry))
    tree = STRtree(projected_urban) if projected_urban else None

    settlements: list[Settlement] = []
    footprint_count = 0
    population_count = 0
    scenario_years = {feature.scenario_reference_year for feature in anchors if feature.scenario_reference_year}
    for anchor in anchors:
        longitude, latitude = _feature_center(anchor.geometry)
        point = transform(to_metric.transform, Point(longitude, latitude))
        radius_m = 12_000.0 if anchor.category == SettlementKind.CITY.value else 4_500.0
        footprint = None
        area_m2 = None
        if tree is not None:
            indices = tree.query(point.buffer(radius_m), predicate="intersects")
            candidates = [projected_urban[int(index)] for index in indices]
            if candidates:
                merged = unary_union([item.buffer(urban_gap_m) for item in candidates])
                components = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
                primary = min(components, key=point.distance)
                related = [item for item in components if item is primary or item.distance(primary) <= 350.0]
                footprint = unary_union(related).buffer(-urban_gap_m)
                if footprint.is_empty:
                    footprint = primary
                footprint = footprint.simplify(urban_simplify_m, preserve_topology=True)
                area_m2 = float(footprint.area)
        tags = _tags(anchor)
        population = _population(tags.get("population"))
        if population is not None:
            population_count += 1
        size_class, size_source = settlement_size_class(
            population=population,
            kind=SettlementKind(anchor.category),
        )
        boundary_kind = SettlementBoundaryKind.POINT_ONLY
        geometry = {"type": "Point", "coordinates": [longitude, latitude]}
        confidence = anchor.confidence
        if footprint is not None and area_m2 is not None and area_m2 >= 10_000:
            geometry = mapping(transform(to_wgs84.transform, footprint))
            boundary_kind = SettlementBoundaryKind.URBAN_FOOTPRINT
            confidence = min(0.9, confidence + 0.15)
            footprint_count += 1
        score = settlement_importance_score(population=population, urban_area_m2=area_m2, kind=SettlementKind(anchor.category))
        settlements.append(
            Settlement(
                settlement_id=_settlement_id(anchor),
                name=str(anchor.name),
                kind=SettlementKind(anchor.category),
                size_class=size_class,
                geometry=geometry,
                latitude=latitude,
                longitude=longitude,
                source=anchor.source,
                confidence=confidence,
                population=population,
                population_date=_optional_string(tags.get("population:date")),
                urban_area_m2=area_m2,
                boundary_kind=boundary_kind,
                size_class_source=size_source,
                importance_score=score,
                importance_tier=settlement_importance_tier(score),
                source_ids=tuple(value for value in (anchor.source_id,) if value),
                scenario_reference_year=anchor.scenario_reference_year,
                properties={"wikidata": tags.get("wikidata")} if tags.get("wikidata") else {},
            )
        )
    settlements.sort(key=lambda item: (-item.importance_score, item.name.casefold(), item.settlement_id))
    return TheaterSettlements(
        theater_id=theater_id,
        scenario_reference_year=max(scenario_years) if scenario_years else None,
        settlements=tuple(settlements),
        metadata={
            "boundary_policy": "connected urban land use near city/town anchor",
            "urban_landuse": sorted(URBAN_LANDUSE),
            "urban_gap_m": urban_gap_m,
            "urban_simplify_m": urban_simplify_m,
            "anchor_count": len(anchors),
            "urban_polygon_count": len(projected_urban),
            "urban_footprint_count": footprint_count,
            "population_count": population_count,
        },
    )


def apply_administrative_boundaries(
    artifact: TheaterSettlements,
    boundaries: Iterable[TopographyFeature],
) -> TheaterSettlements:
    """Replace urban footprints with matching OSM administrative boundaries."""

    try:
        from pyproj import Transformer
        from shapely.geometry import Point, shape
        from shapely.ops import transform
        from shapely.strtree import STRtree
    except ImportError as exc:
        raise RuntimeError('settlement building requires: python -m pip install -e ".[topography]"') from exc

    candidates = [
        feature for feature in boundaries
        if feature.layer is TopographyLayer.ADMINISTRATIVE_BOUNDARIES
        and feature.category in {"4", "6", "8"}
    ]
    if not candidates:
        return artifact
    to_metric = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    projected = [transform(to_metric.transform, shape(feature.geometry)) for feature in candidates]
    tree = STRtree(projected)
    updated: list[Settlement] = []
    matched = 0
    for settlement in artifact.settlements:
        point = transform(to_metric.transform, Point(settlement.longitude, settlement.latitude))
        containing = [
            int(index) for index in tree.query(point)
            if projected[int(index)].covers(point)
        ]
        ranked = sorted(
            (
                (_administrative_match_rank(settlement, candidates[index]), projected[index].area, index)
                for index in containing
            ),
            key=lambda item: (-item[0], item[1]),
        )
        if not ranked or ranked[0][0] <= 0:
            updated.append(settlement)
            continue
        _, area_m2, index = ranked[0]
        boundary = candidates[index]
        properties = dict(settlement.properties)
        properties.update({
            "administrative_boundary_id": boundary.source_id,
            "administrative_level": int(boundary.category),
            "administrative_area_m2": float(area_m2),
        })
        updated.append(replace(
            settlement,
            geometry=boundary.geometry,
            source="; ".join(dict.fromkeys((settlement.source, boundary.source))),
            confidence=max(settlement.confidence, boundary.confidence),
            boundary_kind=SettlementBoundaryKind.ADMINISTRATIVE,
            source_ids=tuple(dict.fromkeys((*settlement.source_ids, *(value for value in (boundary.source_id,) if value)))),
            properties=properties,
        ))
        matched += 1
    return replace(
        artifact,
        settlements=tuple(updated),
        metadata={
            **artifact.metadata,
            "boundary_policy": "OSM administrative boundary with urban-footprint fallback",
            "administrative_boundary_count": len(candidates),
            "administrative_match_count": matched,
            "administrative_levels": [4, 6, 8],
        },
    )


def _administrative_match_rank(settlement: Settlement, boundary: TopographyFeature) -> int:
    settlement_wikidata = str(settlement.properties.get("wikidata") or "").strip()
    boundary_wikidata = str(_tags(boundary).get("wikidata") or "").strip()
    if settlement_wikidata and settlement_wikidata == boundary_wikidata:
        return 3
    if _normalized_place_name(settlement.name) == _normalized_place_name(boundary.name or ""):
        return 2
    return 0


def _normalized_place_name(value: str) -> str:
    import re

    text = value.casefold().replace("&", " und ")
    for prefix in ("freie und hansestadt ", "kreisfreie stadt ", "landeshauptstadt ", "hansestadt "):
        text = text.removeprefix(prefix)
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    ignored = {
        "gemeinde", "stadt",
    }
    words = [word for word in text.split() if word not in ignored]
    return " ".join(words)


def settlement_size_class(*, population: int | None, kind: SettlementKind) -> tuple[SettlementSizeClass, str]:
    if population is not None:
        if population >= 1_000_000:
            return SettlementSizeClass.METROPOLIS, "population"
        if population >= 100_000:
            return SettlementSizeClass.LARGE_CITY, "population"
        if population >= 20_000:
            return SettlementSizeClass.MEDIUM_CITY, "population"
        if population >= 5_000:
            return SettlementSizeClass.SMALL_CITY, "population"
        return SettlementSizeClass.LAND_TOWN, "population"
    if kind is SettlementKind.CITY:
        return SettlementSizeClass.LARGE_CITY, "osm_place"
    return SettlementSizeClass.SMALL_CITY, "osm_place"


def settlement_importance_score(
    *, population: int | None, urban_area_m2: float | None, kind: SettlementKind
) -> float:
    if population is None:
        population_score = 55.0 if kind is SettlementKind.CITY else 25.0
    else:
        population_score = max(0.0, min(80.0, (math.log10(max(1, population)) - 3.0) / 3.0 * 80.0))
    area_score = 0.0
    if urban_area_m2 and urban_area_m2 > 0:
        area_score = max(0.0, min(20.0, (math.log10(urban_area_m2) - 5.0) / 2.5 * 20.0))
    return round(min(100.0, population_score + area_score), 3)


def settlement_importance_tier(score: float) -> SettlementImportanceTier:
    if score >= 80:
        return SettlementImportanceTier.CRITICAL
    if score >= 60:
        return SettlementImportanceTier.HIGH
    if score >= 35:
        return SettlementImportanceTier.MEDIUM
    return SettlementImportanceTier.LOCAL


def _settlement_id(feature: TopographyFeature) -> str:
    identity = feature.source_id or feature.object_id
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]
    return f"SETTLEMENT:{digest}"


def _feature_center(geometry: Mapping[str, Any]) -> tuple[float, float]:
    from shapely.geometry import shape

    item = shape(dict(geometry))
    point = item if item.geom_type == "Point" else item.representative_point()
    return float(point.x), float(point.y)


def _tags(feature: TopographyFeature) -> dict[str, Any]:
    tags = feature.properties.get("osm_tags")
    return dict(tags) if isinstance(tags, Mapping) else {}


def _population(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(" ", "").replace(",", "")
    try:
        parsed = int(float(text))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
