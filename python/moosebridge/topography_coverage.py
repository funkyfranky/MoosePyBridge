"""Spatial detail coverage for offline theater-topography imports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Iterable


class TopographyDetailLevel(StrEnum):
    """Increasing topography detail inside a DCS-defined coverage area."""

    ALL = "all"
    LOW = "low"
    HIGH = "high"


_LEVEL_RANK = {
    TopographyDetailLevel.ALL: 0,
    TopographyDetailLevel.LOW: 1,
    TopographyDetailLevel.HIGH: 2,
}


@dataclass(slots=True, frozen=True)
class TopographyCoverageArea:
    """One circular or polygonal DCS zone used as an offline import mask."""

    object_id: str
    level: TopographyDetailLevel
    geometry: dict[str, Any]
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.object_id.strip():
            raise ValueError("topography coverage area requires an object_id")
        if self.geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("topography coverage geometry must be Polygon or MultiPolygon")

    def to_geojson_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {
                "object_id": self.object_id,
                "name": self.name,
                "detail_level": self.level.value,
                "source": "DCS mission zone",
            },
        }


@dataclass(slots=True, frozen=True)
class TheaterTopographyCoverage:
    """Versioned DCS-authored coverage masks for one terrain."""

    theater_id: str
    areas: tuple[TopographyCoverageArea, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.theater_id.strip() or self.schema_version != 1:
            raise ValueError("invalid theater topography coverage")
        if not any(area.level is TopographyDetailLevel.ALL for area in self.areas):
            raise ValueError("topography coverage requires at least one 'all' area")
        ids = [area.object_id for area in self.areas]
        if len(ids) != len(set(ids)):
            raise ValueError("topography coverage object IDs must be unique")

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Return south, west, north, east bounds of all baseline areas."""

        points = list(_geometry_points(area.geometry for area in self.areas if area.level is TopographyDetailLevel.ALL))
        if not points:
            raise ValueError("topography coverage has no baseline coordinates")
        longitudes = [point[0] for point in points]
        latitudes = [point[1] for point in points]
        return min(latitudes), min(longitudes), max(latitudes), max(longitudes)

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [area.to_geojson_feature() for area in self.areas],
            "properties": {
                "schema": "moosebridge.theater_topography_coverage",
                "schema_version": self.schema_version,
                "theater_id": self.theater_id,
                "bounds": list(self.bounds),
                "levels": {
                    level.value: sum(area.level is level for area in self.areas)
                    for level in TopographyDetailLevel
                },
            },
        }

    @classmethod
    def from_geojson(cls, payload: dict[str, Any]) -> TheaterTopographyCoverage:
        properties = dict(payload.get("properties") or {})
        if payload.get("type") != "FeatureCollection" or properties.get("schema") != "moosebridge.theater_topography_coverage":
            raise ValueError("not a MooseBridge theater topography coverage cache")
        areas = []
        for feature in payload.get("features") or []:
            feature_properties = dict(feature.get("properties") or {})
            areas.append(TopographyCoverageArea(
                object_id=str(feature_properties.get("object_id") or ""),
                name=str(feature_properties["name"]) if feature_properties.get("name") else None,
                level=TopographyDetailLevel(str(feature_properties.get("detail_level") or "")),
                geometry=dict(feature.get("geometry") or {}),
            ))
        return cls(
            theater_id=str(properties.get("theater_id") or ""),
            schema_version=int(properties.get("schema_version") or 1),
            areas=tuple(areas),
        )

    @classmethod
    def load(cls, path: str | Path) -> TheaterTopographyCoverage:
        with Path(path).open("r", encoding="utf-8") as stream:
            return cls.from_geojson(json.load(stream))

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        temporary.write_text(json.dumps(self.to_geojson(), ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(target)
        return target

    def geometry_for_level(self, level: TopographyDetailLevel) -> Any:
        """Return the unioned Shapely geometry for one exact level."""

        try:
            import shapely
            from shapely.geometry import shape
        except ImportError as exc:
            raise RuntimeError('topography coverage requires: python -m pip install -e ".[topography]"') from exc
        geometries = [shape(area.geometry) for area in self.areas if area.level is level]
        return shapely.union_all(geometries) if geometries else None

    def geometry_for_minimum_level(self, required_level: TopographyDetailLevel) -> Any:
        """Return coverage whose configured detail is at least ``required_level``."""

        try:
            import shapely
        except ImportError as exc:
            raise RuntimeError('topography coverage requires: python -m pip install -e ".[topography]"') from exc
        required_rank = _LEVEL_RANK[required_level]
        geometries = [
            geometry
            for level in TopographyDetailLevel
            if _LEVEL_RANK[level] >= required_rank
            if (geometry := self.geometry_for_level(level)) is not None
        ]
        return shapely.union_all(geometries) if geometries else None

    def geometry_exclusive_to_level(self, level: TopographyDetailLevel) -> Any:
        """Return the part of a level not covered by a more detailed area."""

        try:
            import shapely
        except ImportError as exc:
            raise RuntimeError('topography coverage requires: python -m pip install -e ".[topography]"') from exc
        geometry = self.geometry_for_level(level)
        if geometry is None:
            return None
        more_detailed = [
            candidate
            for other_level in TopographyDetailLevel
            if _LEVEL_RANK[other_level] > _LEVEL_RANK[level]
            if (candidate := self.geometry_for_level(other_level)) is not None
        ]
        if not more_detailed:
            return geometry
        return shapely.make_valid(geometry.difference(shapely.union_all(more_detailed)))

    def accepts(self, geometry: Any, required_level: TopographyDetailLevel) -> bool:
        """Return whether geometry intersects an area with sufficient detail."""

        mask = self.geometry_for_minimum_level(required_level)
        return mask is not None and mask.intersects(geometry)


def coverage_from_picture(
    picture: dict[str, Any],
    *,
    theater_id: str,
    zone_prefix: str = "Topography ",
) -> TheaterTopographyCoverage:
    """Extract `Topography All/Low/High ...` zones from global-picture GeoJSON."""

    try:
        from pyproj import Transformer
        from shapely.geometry import Point, mapping, shape
        from shapely.ops import transform
    except ImportError as exc:
        raise RuntimeError('topography coverage requires: python -m pip install -e ".[topography]"') from exc

    to_metric = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    to_wgs84 = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True).transform
    areas: list[TopographyCoverageArea] = []
    for feature in picture.get("features") or []:
        properties = dict(feature.get("properties") or {})
        if properties.get("layer") != "zones":
            continue
        name = str(properties.get("name") or "")
        suffix = name.removeprefix(zone_prefix) if name.startswith(zone_prefix) else ""
        level_name = suffix.split(None, 1)[0].lower() if suffix else ""
        if level_name not in {level.value for level in TopographyDetailLevel}:
            continue
        geometry = shape(feature.get("geometry") or {})
        if geometry.geom_type == "Point":
            radius_m = float(properties.get("radius_m") or properties.get("radius") or 0)
            if radius_m <= 0:
                raise ValueError(f"coverage zone {name!r} has no positive radius")
            geometry = transform(to_wgs84, transform(to_metric, Point(geometry.x, geometry.y)).buffer(radius_m, quad_segs=24))
        if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty:
            raise ValueError(f"coverage zone {name!r} has unsupported geometry {geometry.geom_type}")
        areas.append(TopographyCoverageArea(
            object_id=str(properties.get("object_id") or f"ZONE:{name}"),
            name=name,
            level=TopographyDetailLevel(level_name),
            geometry=mapping(geometry),
        ))
    return TheaterTopographyCoverage(theater_id=theater_id, areas=tuple(areas))


def _geometry_points(geometries: Iterable[dict[str, Any]]) -> Iterable[tuple[float, float]]:
    def visit(value: Any) -> Iterable[tuple[float, float]]:
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            yield float(value[0]), float(value[1])
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from visit(item)

    for geometry in geometries:
        yield from visit(geometry.get("coordinates"))
