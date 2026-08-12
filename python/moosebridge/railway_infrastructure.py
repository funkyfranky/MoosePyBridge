"""Operational railway locations derived from OSM facilities and track geometry."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .topography import TopographyFeature, TopographyLayer


RAILWAY_INFRASTRUCTURE_SCHEMA = "moosebridge.railway_infrastructure"
RAILWAY_INFRASTRUCTURE_SCHEMA_VERSION = 1
DEFAULT_RAILWAY_CLUSTER_RADIUS_M = 350.0


class RailwayLocationKind(StrEnum):
    STATION = "station"
    FREIGHT_TERMINAL = "freight_terminal"
    RAIL_YARD = "rail_yard"
    DEPOT = "depot"
    JUNCTION = "junction"
    BRIDGE = "bridge"


class RailwayImportanceTier(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOCAL = "local"


@dataclass(slots=True, frozen=True)
class RailwayLocation:
    location_id: str
    kind: RailwayLocationKind
    latitude: float
    longitude: float
    name: str | None = None
    source_ids: tuple[str, ...] = ()
    member_count: int = 1
    track_length_m: float = 0.0
    branch_count: int = 0
    importance_score: float = 0.0
    importance_tier: RailwayImportanceTier = RailwayImportanceTier.LOCAL
    source: str = "OpenStreetMap"
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.location_id.strip() or not self.source.strip():
            raise ValueError("railway location requires location_id and source")
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ValueError("railway location coordinates are outside WGS84 bounds")
        if self.member_count < 1 or self.track_length_m < 0 or self.branch_count < 0:
            raise ValueError("railway location counts and lengths must not be negative")
        if not 0 <= self.importance_score <= 100:
            raise ValueError("railway importance score must be between zero and 100")

    @property
    def strategic_candidate(self) -> bool:
        return self.importance_tier is not RailwayImportanceTier.LOCAL

    def to_geojson_feature(self) -> dict[str, Any]:
        properties = {
            "layer": "railway_infrastructure",
            "object_id": self.location_id,
            "name": self.name,
            "object_type": "RAILWAY_LOCATION",
            "category": self.kind.value,
            "map_category": self.kind.value,
            "railway_kind": self.kind.value,
            "coordinate_system": "WGS84",
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source": self.source,
            "source_ids": list(self.source_ids),
            "member_count": self.member_count,
            "track_length_m": self.track_length_m,
            "branch_count": self.branch_count,
            "importance_score": self.importance_score,
            "importance_tier": self.importance_tier.value,
            "strategic_candidate": self.strategic_candidate,
            **self.properties,
        }
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
            "properties": {key: value for key, value in properties.items() if value is not None},
        }

    @classmethod
    def from_geojson_feature(cls, feature: Mapping[str, Any]) -> "RailwayLocation":
        properties = dict(feature.get("properties") or {})
        geometry = dict(feature.get("geometry") or {})
        coordinates = geometry.get("coordinates") or (0, 0)
        known = {
            "layer", "object_id", "name", "object_type", "category", "map_category", "railway_kind",
            "coordinate_system", "latitude", "longitude", "source", "source_ids", "member_count",
            "track_length_m", "branch_count", "importance_score", "importance_tier", "strategic_candidate",
        }
        return cls(
            location_id=str(properties.get("object_id") or ""),
            kind=RailwayLocationKind(str(properties.get("railway_kind") or properties.get("category") or "")),
            latitude=float(properties.get("latitude", coordinates[1])),
            longitude=float(properties.get("longitude", coordinates[0])),
            name=_optional_text(properties.get("name")),
            source_ids=tuple(str(value) for value in properties.get("source_ids") or ()),
            member_count=int(properties.get("member_count") or 1),
            track_length_m=float(properties.get("track_length_m") or 0),
            branch_count=int(properties.get("branch_count") or 0),
            importance_score=float(properties.get("importance_score") or 0),
            importance_tier=RailwayImportanceTier(
                str(properties.get("importance_tier") or RailwayImportanceTier.LOCAL.value)
            ),
            source=str(properties.get("source") or "OpenStreetMap"),
            properties={key: value for key, value in properties.items() if key not in known},
        )


@dataclass(slots=True, frozen=True)
class TheaterRailwayInfrastructure:
    theater_id: str
    locations: tuple[RailwayLocation, ...] = ()
    schema_version: int = RAILWAY_INFRASTRUCTURE_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.theater_id.strip():
            raise ValueError("railway infrastructure requires theater_id")
        if self.schema_version != RAILWAY_INFRASTRUCTURE_SCHEMA_VERSION:
            raise ValueError(f"unsupported railway infrastructure schema version: {self.schema_version}")
        ids = [location.location_id for location in self.locations]
        if len(ids) != len(set(ids)):
            raise ValueError("railway location IDs must be unique")

    def to_geojson(self) -> dict[str, Any]:
        counts = {
            kind.value: sum(location.kind is kind for location in self.locations)
            for kind in RailwayLocationKind
        }
        return {
            "type": "FeatureCollection",
            "features": [location.to_geojson_feature() for location in self.locations],
            "properties": {
                "schema": RAILWAY_INFRASTRUCTURE_SCHEMA,
                "schema_version": self.schema_version,
                "theater_id": self.theater_id,
                "location_count": len(self.locations),
                "counts": counts,
                **self.metadata,
            },
        }

    @classmethod
    def from_geojson(cls, payload: Mapping[str, Any]) -> "TheaterRailwayInfrastructure":
        properties = dict(payload.get("properties") or {})
        if payload.get("type") != "FeatureCollection" or properties.get("schema") != RAILWAY_INFRASTRUCTURE_SCHEMA:
            raise ValueError("not a MooseBridge railway-infrastructure artifact")
        known = {"schema", "schema_version", "theater_id", "location_count", "counts"}
        return cls(
            theater_id=str(properties.get("theater_id") or ""),
            schema_version=int(properties.get("schema_version") or 1),
            locations=tuple(
                RailwayLocation.from_geojson_feature(feature)
                for feature in payload.get("features") or ()
            ),
            metadata={key: value for key, value in properties.items() if key not in known},
        )

    @classmethod
    def load(cls, path: str | Path) -> "TheaterRailwayInfrastructure":
        with Path(path).open("r", encoding="utf-8") as stream:
            return cls.from_geojson(json.load(stream))

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        temporary.write_text(json.dumps(self.to_geojson(), ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(target)
        return target


@dataclass(slots=True)
class _Candidate:
    kind: RailwayLocationKind
    latitude: float
    longitude: float
    source_ids: set[str]
    names: set[str] = field(default_factory=set)
    preferred_name: str | None = None
    member_count: int = 1
    track_length_m: float = 0.0
    branch_count: int = 0
    base_score: float = 0.0
    properties: dict[str, Any] = field(default_factory=dict)


def build_railway_infrastructure(
    track_features: Iterable[TopographyFeature],
    facility_features: Iterable[TopographyFeature] = (),
    *,
    theater_id: str,
    cluster_radius_m: float = DEFAULT_RAILWAY_CLUSTER_RADIUS_M,
) -> TheaterRailwayInfrastructure:
    """Build aggregated operational railway locations from OSM source data."""

    if cluster_radius_m < 0:
        raise ValueError("railway cluster radius must not be negative")
    tracks = [
        feature for feature in track_features
        if feature.layer is TopographyLayer.RAILWAYS and feature.category == "rail"
    ]
    candidates = _facility_candidates(facility_features)
    candidates.extend(_track_site_candidates(tracks))
    candidates.extend(_junction_candidates(tracks))
    candidates.extend(_bridge_candidates(tracks))
    clustered: list[_Candidate] = []
    for kind in RailwayLocationKind:
        radius = 180.0 if kind is RailwayLocationKind.STATION else cluster_radius_m
        clustered.extend(_cluster_candidates(
            [candidate for candidate in candidates if candidate.kind is kind],
            radius,
            allow_chaining=kind is not RailwayLocationKind.BRIDGE,
        ))
    locations = tuple(sorted((_location(theater_id, candidate) for candidate in clustered), key=lambda item: item.location_id))
    return TheaterRailwayInfrastructure(
        theater_id=theater_id,
        locations=locations,
        metadata={
            "method": "aggregated_osm_facilities_track_topology_and_bridges",
            "track_feature_count": len(tracks),
            "cluster_radius_m": cluster_radius_m,
            "ordinary_tracks_are_topography_only": True,
        },
    )


def _facility_candidates(features: Iterable[TopographyFeature]) -> list[_Candidate]:
    output: list[_Candidate] = []
    category_kinds = {
        "railway_station": RailwayLocationKind.STATION,
        "railway_halt": RailwayLocationKind.STATION,
        "railway_freight_terminal": RailwayLocationKind.FREIGHT_TERMINAL,
        "railway_yard": RailwayLocationKind.RAIL_YARD,
        "railway_depot": RailwayLocationKind.DEPOT,
    }
    scores = {
        "railway_station": 35.0,
        "railway_halt": 12.0,
        "railway_freight_terminal": 72.0,
        "railway_yard": 58.0,
        "railway_depot": 55.0,
    }
    for feature in features:
        kind = category_kinds.get(feature.category)
        if kind is None:
            continue
        tags = _tags(feature)
        if kind is RailwayLocationKind.STATION and (
            tags.get("subway") == "yes" or tags.get("station") in {"subway", "light_rail"}
        ):
            continue
        lon, lat = _representative_coordinate(feature.geometry)
        score = scores[feature.category]
        if feature.name:
            score += 5
        if tags.get("uic_ref") or tags.get("railway:ref"):
            score += 8
        if tags.get("train") == "yes":
            score += 5
        output.append(_Candidate(
            kind=kind,
            latitude=lat,
            longitude=lon,
            source_ids={feature.object_id},
            names={feature.name} if feature.name else set(),
            preferred_name=feature.name,
            base_score=score,
            properties={
                "facility_source": feature.category,
                "operator": tags.get("operator"),
                "uic_ref": tags.get("uic_ref"),
            },
        ))
    return output


def _track_site_candidates(tracks: Iterable[TopographyFeature]) -> list[_Candidate]:
    output: list[_Candidate] = []
    for feature in tracks:
        tags = _tags(feature)
        service = str(tags.get("service") or "").casefold()
        railway = str(tags.get("railway") or "").casefold()
        freight = str(tags.get("freight") or "").casefold()
        if service == "yard" or railway == "yard":
            kind, score = RailwayLocationKind.RAIL_YARD, 32.0
        elif railway in {"depot", "engine_shed", "roundhouse", "workshop"}:
            kind, score = RailwayLocationKind.DEPOT, 48.0
        elif railway in {"freight_terminal", "container_terminal"} or freight in {"yes", "only"}:
            kind, score = RailwayLocationKind.FREIGHT_TERMINAL, 65.0
        else:
            continue
        lon, lat = _representative_coordinate(feature.geometry)
        length = _geometry_length_m(feature.geometry)
        output.append(_Candidate(
            kind=kind,
            latitude=lat,
            longitude=lon,
            source_ids={feature.object_id},
            names={feature.name} if feature.name else set(),
            preferred_name=feature.name,
            track_length_m=length,
            base_score=score,
            properties={"service": service or None},
        ))
    return output


def _junction_candidates(tracks: Iterable[TopographyFeature]) -> list[_Candidate]:
    neighbours: dict[tuple[float, float], set[tuple[float, float]]] = {}
    source_ids: dict[tuple[float, float], set[str]] = {}
    for feature in tracks:
        tags = _tags(feature)
        if str(tags.get("service") or "").casefold() in {"yard", "spur", "siding", "crossover"}:
            continue
        for line in _geometry_lines(feature.geometry):
            for first, second in zip(line, line[1:]):
                a = _coordinate_key(first)
                b = _coordinate_key(second)
                if a == b:
                    continue
                neighbours.setdefault(a, set()).add(b)
                neighbours.setdefault(b, set()).add(a)
                source_ids.setdefault(a, set()).add(feature.object_id)
                source_ids.setdefault(b, set()).add(feature.object_id)
    output = []
    for (lon, lat), connected in neighbours.items():
        branches = len(connected)
        if branches < 3:
            continue
        output.append(_Candidate(
            kind=RailwayLocationKind.JUNCTION,
            latitude=lat,
            longitude=lon,
            source_ids=source_ids.get((lon, lat), set()),
            branch_count=branches,
            base_score=min(88.0, 25.0 + branches * 10.0),
        ))
    return output


def _bridge_candidates(tracks: Iterable[TopographyFeature]) -> list[_Candidate]:
    output = []
    for feature in tracks:
        tags = _tags(feature)
        if str(tags.get("bridge") or "").casefold() in {"", "no", "false", "0"}:
            continue
        lon, lat = _representative_coordinate(feature.geometry)
        length = _geometry_length_m(feature.geometry)
        output.append(_Candidate(
            kind=RailwayLocationKind.BRIDGE,
            latitude=lat,
            longitude=lon,
            source_ids={feature.object_id},
            names={feature.name} if feature.name else set(),
            preferred_name=feature.name,
            track_length_m=length,
            base_score=min(75.0, 24.0 + math.log1p(max(length, 1.0)) * 3.0),
            properties={"bridge": tags.get("bridge")},
        ))
    return output


def _cluster_candidates(
    candidates: list[_Candidate],
    radius_m: float,
    *,
    allow_chaining: bool = True,
) -> list[_Candidate]:
    if not candidates:
        return []
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    projected = [transformer.transform(candidate.longitude, candidate.latitude) for candidate in candidates]
    cell_size = max(radius_m, 1.0)
    buckets: dict[tuple[int, int], set[int]] = {}
    for index, (x, y) in enumerate(projected):
        buckets.setdefault((math.floor(x / cell_size), math.floor(y / cell_size)), set()).add(index)
    unseen = set(range(len(candidates)))
    result = []
    while unseen:
        seed = min(unseen)
        unseen.remove(seed)
        seed_x, seed_y = projected[seed]
        buckets[(math.floor(seed_x / cell_size), math.floor(seed_y / cell_size))].discard(seed)
        members = [seed]
        queue = [seed]
        while queue:
            current = queue.pop()
            x, y = projected[current]
            cell = (math.floor(x / cell_size), math.floor(y / cell_size))
            nearby = {
                index
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                for index in buckets.get((cell[0] + dx, cell[1] + dy), ())
            }
            for index in nearby:
                px, py = projected[index]
                if math.hypot(px - x, py - y) <= radius_m:
                    unseen.remove(index)
                    buckets[(math.floor(px / cell_size), math.floor(py / cell_size))].discard(index)
                    members.append(index)
                    if allow_chaining:
                        queue.append(index)
        result.append(_merge_candidates([candidates[index] for index in members]))
    return result


def _merge_candidates(members: list[_Candidate]) -> _Candidate:
    best = max(members, key=lambda item: (item.base_score, bool(item.names), item.member_count))
    source_ids = {value for member in members for value in member.source_ids}
    names = {value for member in members for value in member.names if value}
    name_counts = Counter(
        member.preferred_name
        for member in members
        if member.preferred_name
    )
    preferred_name = max(
        name_counts,
        key=lambda value: (name_counts[value], len(value), value),
        default=None,
    )
    track_length = sum(member.track_length_m for member in members)
    branch_count = max((member.branch_count for member in members), default=0)
    score = max(member.base_score for member in members)
    score += min(18.0, math.log1p(len(source_ids)) * 4.0)
    score += min(12.0, math.log1p(track_length / 500.0) * 4.0) if track_length else 0.0
    return _Candidate(
        kind=best.kind,
        latitude=sum(member.latitude for member in members) / len(members),
        longitude=sum(member.longitude for member in members) / len(members),
        source_ids=source_ids,
        names=names,
        preferred_name=preferred_name,
        member_count=sum(member.member_count for member in members),
        track_length_m=track_length,
        branch_count=branch_count,
        base_score=min(100.0, score),
        properties={key: value for member in members for key, value in member.properties.items() if value is not None},
    )


def _location(theater_id: str, candidate: _Candidate) -> RailwayLocation:
    digest = hashlib.sha1(
        "|".join(sorted(candidate.source_ids) or [f"{candidate.longitude:.6f},{candidate.latitude:.6f}"]).encode("utf-8")
    ).hexdigest()[:16]
    prefix = candidate.kind.value.upper()
    return RailwayLocation(
        location_id=f"RAILWAY_{prefix}:{theater_id}:{digest}",
        kind=candidate.kind,
        latitude=candidate.latitude,
        longitude=candidate.longitude,
        name=candidate.preferred_name or (
            max(candidate.names, key=lambda value: (len(value), value)) if candidate.names else None
        ),
        source_ids=tuple(sorted(candidate.source_ids)),
        member_count=candidate.member_count,
        track_length_m=candidate.track_length_m,
        branch_count=candidate.branch_count,
        importance_score=candidate.base_score,
        importance_tier=_importance_tier(candidate.base_score),
        properties=candidate.properties,
    )


def _importance_tier(score: float) -> RailwayImportanceTier:
    if score >= 85:
        return RailwayImportanceTier.CRITICAL
    if score >= 68:
        return RailwayImportanceTier.HIGH
    if score >= 45:
        return RailwayImportanceTier.MEDIUM
    return RailwayImportanceTier.LOCAL


def _tags(feature: TopographyFeature) -> dict[str, Any]:
    value = feature.properties.get("osm_tags")
    return dict(value) if isinstance(value, Mapping) else {}


def _coordinate_key(coordinate: Iterable[float]) -> tuple[float, float]:
    values = tuple(coordinate)
    return round(float(values[0]), 6), round(float(values[1]), 6)


def _geometry_lines(geometry: Mapping[str, Any]) -> list[list[list[float]]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "LineString":
        return [coordinates]
    if kind == "MultiLineString":
        return list(coordinates)
    return []


def _representative_coordinate(geometry: Mapping[str, Any]) -> tuple[float, float]:
    from shapely.geometry import shape

    point = shape(dict(geometry)).representative_point()
    return float(point.x), float(point.y)


def _geometry_length_m(geometry: Mapping[str, Any]) -> float:
    from shapely.geometry import shape
    from shapely.ops import transform

    transformer = _metric_transformer()
    return float(transform(transformer.transform, shape(dict(geometry))).length)


@lru_cache(maxsize=1)
def _metric_transformer():
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
