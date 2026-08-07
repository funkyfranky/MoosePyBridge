"""Offline Geofabrik PBF conversion into normalized theater topography."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .osm_topography import features_from_overpass_element
from .topography import TheaterTopography, TopographyFeature, TopographyLayer


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


def topography_from_pbf(
    paths: Iterable[str | Path],
    *,
    theater_id: str,
    scenario_reference_year: int | None,
    bounds: tuple[float, float, float, float],
    source_snapshot_dates: Mapping[str, str] | None = None,
    include_buildings: bool = False,
    simplify_meters: float = 20.0,
) -> TheaterTopography:
    """Read bounded Geofabrik extracts with optional Pyrosm."""

    try:
        from pyrosm import OSM
    except ImportError as exc:
        raise RuntimeError('PBF import requires: python -m pip install -e ".[topography]"') from exc

    source_dates = source_snapshot_dates or {}
    west, south, east, north = bounds[1], bounds[0], bounds[3], bounds[2]
    custom_filter = dict(PBF_TAG_FILTER)
    if include_buildings:
        custom_filter["building"] = True
    features: dict[str, TopographyFeature] = {}
    snapshots: list[str] = []
    sources: list[str] = []
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
                include_buildings=include_buildings,
            ):
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
        },
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
