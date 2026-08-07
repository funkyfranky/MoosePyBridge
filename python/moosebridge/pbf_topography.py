"""Offline Geofabrik PBF conversion into normalized theater topography."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .osm_topography import features_from_overpass_element
from .topography import TheaterTopography, TopographyFeature, TopographyLayer
from .topography_coverage import TheaterTopographyCoverage, TopographyDetailLevel


PBF_TAG_FILTER: dict[str, Any] = {
    "natural": ["water", "coastline"],
    "waterway": ["river", "canal"],
    "highway": ["motorway", "trunk", "primary", "secondary"],
    "railway": ["rail"],
    "place": ["city", "town"],
    "landuse": ["industrial", "commercial", "residential", "retail", "military", "port"],
    "power": ["plant"],
    "man_made": ["works", "water_works", "wastewater_plant", "storage_tank", "silo"],
    "harbour": ["yes"],
    "bridge": True,
    "industrial": True,
}
PBF_TAG_COLUMNS = tuple(PBF_TAG_FILTER) + (
    "name", "name:en", "start_date", "end_date", "building", "water", "area",
)

DETAILED_PBF_TAG_FILTER: dict[str, Any] = {
    **PBF_TAG_FILTER,
    "highway": [
        "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
        "residential", "service", "living_street", "track",
    ],
    "railway": ["rail", "light_rail", "tram", "narrow_gauge"],
    "place": ["city", "town", "village", "hamlet"],
    "landuse": True,
}


def topography_from_pbf(
    paths: Iterable[str | Path],
    *,
    theater_id: str,
    scenario_reference_year: int | None,
    bounds: tuple[float, float, float, float],
    source_snapshot_dates: Mapping[str, str] | None = None,
    include_buildings: bool = False,
    simplify_meters: float = 20.0,
    coverage: TheaterTopographyCoverage | None = None,
) -> TheaterTopography:
    """Read bounded Geofabrik extracts with optional Pyrosm."""

    try:
        from pyrosm import OSM
    except ImportError as exc:
        raise RuntimeError('PBF import requires: python -m pip install -e ".[topography]"') from exc

    source_dates = source_snapshot_dates or {}
    west, south, east, north = bounds[1], bounds[0], bounds[3], bounds[2]
    custom_filter = dict(DETAILED_PBF_TAG_FILTER if coverage is not None else PBF_TAG_FILTER)
    coverage_has_high = coverage is not None and any(area.level is TopographyDetailLevel.HIGH for area in coverage.areas)
    if include_buildings or coverage_has_high:
        custom_filter["building"] = True
    features: dict[str, TopographyFeature] = {}
    snapshots: list[str] = []
    sources: list[str] = []
    coverage_masks: dict[TopographyDetailLevel, Any] = {}
    shape_geometry = None
    if coverage is not None:
        try:
            from shapely.geometry import shape as shape_geometry
        except ImportError as exc:
            raise RuntimeError('PBF import requires: python -m pip install -e "[topography]"') from exc
        coverage_masks = {level: coverage.geometry_for_level(level) for level in TopographyDetailLevel}
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        sources.append(path.name)
        source_date = source_dates.get(path.name)
        if source_date:
            snapshots.append(source_date)
        reader = OSM(
            str(path),
            bounding_box=[west, south, east, north],
            keep_metadata=False,
            complete_relations=True,
        )
        frame = reader.get_data_by_custom_criteria(
            custom_filter=custom_filter,
            tags_as_columns=list(PBF_TAG_COLUMNS),
            keep_nodes=True,
            keep_ways=True,
            keep_relations=True,
        )
        if frame is None or frame.empty:
            continue
        if simplify_meters > 0:
            source_crs = frame.crs or "EPSG:4326"
            frame = frame.to_crs("EPSG:3035")
            frame.geometry = frame.geometry.simplify(simplify_meters, preserve_topology=True)
            frame = frame.to_crs(source_crs)
        for record in frame.iterfeatures():
            for feature in features_from_pyrosm_record(
                record,
                scenario_reference_year=scenario_reference_year,
                source_snapshot_date=source_date,
                include_buildings=include_buildings or coverage_has_high,
            ):
                if coverage is not None:
                    required_level = topography_detail_level(feature)
                    geometry = shape_geometry(feature.geometry)
                    eligible_levels = {
                        TopographyDetailLevel.ALL: TopographyDetailLevel,
                        TopographyDetailLevel.LOW: (TopographyDetailLevel.LOW, TopographyDetailLevel.HIGH),
                        TopographyDetailLevel.HIGH: (TopographyDetailLevel.HIGH,),
                    }[required_level]
                    if not any(
                        coverage_masks[level] is not None and coverage_masks[level].intersects(geometry)
                        for level in eligible_levels
                    ):
                        continue
                    feature = _with_detail_level(feature, required_level)
                features[feature.object_id] = feature
    source_snapshot_date = max(snapshots) if snapshots else None
    return TheaterTopography(
        theater_id=theater_id,
        scenario_reference_year=scenario_reference_year,
        source_snapshot_date=source_snapshot_date,
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        bounds=bounds,
        features=tuple(sorted(features.values(), key=lambda feature: feature.object_id)),
        metadata={
            "external_source": "OpenStreetMap Geofabrik PBF",
            "source_files": sources,
            "dcs_verification": "pending",
            "buildings_included": include_buildings,
            "geometry_simplification_m": simplify_meters,
            "coverage_levels": sorted({area.level.value for area in coverage.areas}) if coverage else None,
            "coverage_area_count": len(coverage.areas) if coverage else 0,
        },
    )


def topography_detail_level(feature: TopographyFeature) -> TopographyDetailLevel:
    """Return the minimum DCS-authored coverage level for one OSM feature."""

    category = feature.category.lower()
    if feature.layer is TopographyLayer.WATER:
        return TopographyDetailLevel.ALL
    if feature.layer is TopographyLayer.ROADS:
        if category in {"motorway", "trunk"}:
            return TopographyDetailLevel.ALL
        if category in {"primary", "secondary"}:
            return TopographyDetailLevel.LOW
        return TopographyDetailLevel.HIGH
    if feature.layer is TopographyLayer.RAILWAYS:
        return TopographyDetailLevel.ALL if category == "rail" else TopographyDetailLevel.HIGH
    if feature.layer is TopographyLayer.SETTLEMENTS:
        if category == "city":
            return TopographyDetailLevel.ALL
        return TopographyDetailLevel.LOW if category == "town" else TopographyDetailLevel.HIGH
    if feature.layer is TopographyLayer.BUILDINGS:
        return TopographyDetailLevel.HIGH
    if feature.layer is TopographyLayer.LANDUSE:
        return TopographyDetailLevel.LOW if category in {"industrial", "military", "port"} else TopographyDetailLevel.HIGH
    if feature.layer is TopographyLayer.INFRASTRUCTURE:
        return TopographyDetailLevel.ALL if category in {"power_plant", "harbour"} else TopographyDetailLevel.LOW
    return TopographyDetailLevel.HIGH


def _with_detail_level(feature: TopographyFeature, level: TopographyDetailLevel) -> TopographyFeature:
    return TopographyFeature(
        object_id=feature.object_id,
        layer=feature.layer,
        category=feature.category,
        geometry=feature.geometry,
        source=feature.source,
        confidence=feature.confidence,
        name=feature.name,
        source_id=feature.source_id,
        scenario_reference_year=feature.scenario_reference_year,
        source_snapshot_date=feature.source_snapshot_date,
        valid_from=feature.valid_from,
        valid_to=feature.valid_to,
        dcs_verified=feature.dcs_verified,
        properties={**feature.properties, "detail_level": level.value},
    )


def features_from_pyrosm_record(
    record: dict[str, Any],
    *,
    scenario_reference_year: int | None,
    source_snapshot_date: str | None,
    include_buildings: bool,
) -> tuple[TopographyFeature, ...]:
    """Convert one GeoDataFrame feature without depending on GeoPandas in tests."""

    properties = dict(record.get("properties") or {})
    nested_tags = properties.pop("tags", None)
    if isinstance(nested_tags, str):
        try:
            nested_tags = json.loads(nested_tags)
        except json.JSONDecodeError:
            nested_tags = None
    tags = dict(nested_tags) if isinstance(nested_tags, dict) else {}
    for key, value in properties.items():
        if _has_value(value) and key not in {"id", "osm_type", "version", "timestamp", "changeset"}:
            tags[key] = value
    osm_id = properties.get("id", record.get("id"))
    if osm_id is None:
        return ()
    osm_type = str(properties.get("osm_type") or "feature")
    element = {
        "type": osm_type,
        "id": osm_id,
        "tags": tags,
        "center": _geometry_center(record.get("geometry")),
    }
    features = list(
        features_from_overpass_element(
            element,
            scenario_reference_year=scenario_reference_year,
            source_snapshot_date=source_snapshot_date,
        )
    )
    geometry = record.get("geometry")
    if isinstance(geometry, dict) and geometry.get("type") in {
        "Point", "LineString", "Polygon", "MultiLineString", "MultiPolygon"
    }:
        features = [
            TopographyFeature(
                object_id=feature.object_id,
                layer=feature.layer,
                category=feature.category,
                geometry=dict(geometry),
                source=feature.source,
                confidence=feature.confidence,
                name=feature.name,
                source_id=feature.source_id,
                scenario_reference_year=feature.scenario_reference_year,
                source_snapshot_date=feature.source_snapshot_date,
                valid_from=feature.valid_from,
                valid_to=feature.valid_to,
                dcs_verified=feature.dcs_verified,
                properties=feature.properties,
            )
            for feature in features
        ]
    if not include_buildings:
        features = [feature for feature in features if feature.layer is not TopographyLayer.BUILDINGS]
    return tuple(features)


def _geometry_center(geometry: Any) -> dict[str, float] | None:
    if not isinstance(geometry, dict):
        return None
    coordinates: list[tuple[float, float]] = []

    def collect(value: Any) -> None:
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            coordinates.append((float(value[0]), float(value[1])))
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(geometry.get("coordinates"))
    if not coordinates:
        return None
    return {
        "lon": sum(point[0] for point in coordinates) / len(coordinates),
        "lat": sum(point[1] for point in coordinates) / len(coordinates),
    }


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    return not (isinstance(value, float) and value != value)
