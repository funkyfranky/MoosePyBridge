"""Streaming Geofabrik PBF conversion into normalized theater topography."""

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
    ],
    "railway": ["rail", "light_rail", "tram", "narrow_gauge"],
    "place": ["city", "town", "village", "hamlet"],
    "landuse": ["industrial", "commercial", "residential", "retail", "military", "port"],
}

OGR_LAYER_FILTERS: dict[str, str] = {
    "points": (
        "place IN ('city','town','village','hamlet') OR "
        "man_made IN ('works','water_works','wastewater_plant','storage_tank','silo') OR "
        "other_tags LIKE '%\"power\"=>\"plant\"%' OR other_tags LIKE '%\"harbour\"=>\"yes\"%'"
    ),
    "lines": (
        "highway IN ('motorway','trunk','primary','secondary','tertiary','unclassified') OR "
        "waterway IN ('river','canal') OR railway IN ('rail','light_rail','tram','narrow_gauge') OR "
        "other_tags LIKE '%\"natural\"=>\"coastline\"%' OR other_tags LIKE '%\"bridge\"%'"
    ),
    "multipolygons": (
        "natural = 'water' OR place IN ('city','town','village','hamlet') OR "
        "landuse IN ('industrial','commercial','residential','retail','military','port') OR "
        "man_made IN ('works','water_works','wastewater_plant','storage_tank','silo') OR "
        "military IS NOT NULL OR other_tags LIKE '%\"power\"=>\"plant\"%' OR "
        "other_tags LIKE '%\"harbour\"=>\"yes\"%'"
    ),
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
    """Read bounded Geofabrik extracts with GDAL/OGR through Pyogrio."""

    try:
        import pyogrio
    except ImportError as exc:
        raise RuntimeError('PBF import requires: python -m pip install -e ".[topography]"') from exc

    source_dates = source_snapshot_dates or {}
    west, south, east, north = bounds[1], bounds[0], bounds[3], bounds[2]
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
        import shapely
        for mask in coverage_masks.values():
            if mask is not None:
                shapely.prepare(mask)
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        sources.append(path.name)
        source_date = source_dates.get(path.name)
        if source_date:
            snapshots.append(source_date)
        layer_filters = dict(OGR_LAYER_FILTERS)
        if include_buildings:
            layer_filters["multipolygons"] += " OR building IS NOT NULL"
        for layer_name, where in layer_filters.items():
            frame = pyogrio.read_dataframe(
                path,
                layer=layer_name,
                bbox=(west, south, east, north),
                where=where,
                use_arrow=True,
            )
            if frame is None or frame.empty:
                continue
            if simplify_meters > 0:
                source_crs = frame.crs or "EPSG:4326"
                frame = frame.to_crs("EPSG:3035")
                frame.geometry = frame.geometry.simplify(simplify_meters, preserve_topology=True)
                frame = frame.to_crs(source_crs)
            for record in frame.iterfeatures():
                normalized = _normalize_ogr_record(record, layer_name)
                for feature in features_from_pyrosm_record(
                    normalized,
                    scenario_reference_year=scenario_reference_year,
                    source_snapshot_date=source_date,
                    include_buildings=include_buildings,
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


def _normalize_ogr_record(record: dict[str, Any], layer_name: str) -> dict[str, Any]:
    """Convert one OGR OSM layer record to the existing normalized converter input."""

    properties = dict(record.get("properties") or {})
    tags = _parse_ogr_other_tags(properties.pop("other_tags", None))
    for key, value in properties.items():
        if key not in {"osm_id", "osm_way_id", "z_order", "type"} and _has_value(value):
            tags[key] = value
    osm_way_id = properties.get("osm_way_id")
    osm_id = osm_way_id if _has_value(osm_way_id) else properties.get("osm_id")
    osm_type = "node" if layer_name == "points" else "way"
    if layer_name == "multipolygons" and not _has_value(osm_way_id):
        osm_type = "relation"
    return {
        "type": "Feature",
        "geometry": record.get("geometry"),
        "properties": {
            "id": osm_id,
            "osm_type": osm_type,
            "tags": json.dumps(tags, ensure_ascii=True),
        },
    }


def _parse_ogr_other_tags(value: Any) -> dict[str, str]:
    """Parse GDAL's escaped hstore-like representation of additional OSM tags."""

    if not isinstance(value, str) or not value:
        return {}
    import re

    output: dict[str, str] = {}
    for match in re.finditer(r'"((?:\\.|[^"\\])*)"=>"((?:\\.|[^"\\])*)"', value):
        key = bytes(match.group(1), "utf-8").decode("unicode_escape")
        item = bytes(match.group(2), "utf-8").decode("unicode_escape")
        output[key] = item
    return output


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
