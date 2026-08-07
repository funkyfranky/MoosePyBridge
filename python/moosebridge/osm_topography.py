"""OpenStreetMap/Overpass conversion for offline theater-topography imports."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable

from .topography import TheaterTopography, TopographyFeature, TopographyLayer


ROAD_CLASSES = frozenset({"motorway", "trunk", "primary", "secondary"})
RAIL_CLASSES = frozenset({"rail"})
SETTLEMENT_CLASSES = frozenset({"city", "town"})
_YEAR_PATTERN = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")


def build_overpass_query(bounds: tuple[float, float, float, float]) -> str:
    """Build a bounded query for the deliberately small first import scope.

    Bounds use ``south, west, north, east`` order.
    """

    south, west, north, east = bounds
    bbox = f"{south:.7f},{west:.7f},{north:.7f},{east:.7f}"
    return f"""[out:json][timeout:180];
(
  way[\"natural\"~\"^(water|coastline)$\"]({bbox});
  way[\"waterway\"~\"^(river|canal)$\"]({bbox});
  way[\"highway\"~\"^(motorway|trunk|primary|secondary)$\"]({bbox});
  way[\"railway\"=\"rail\"]({bbox});
  nwr[\"place\"~\"^(city|town)$\"]({bbox});
  nwr[\"landuse\"=\"industrial\"]({bbox});
  nwr[\"power\"=\"plant\"]({bbox});
  nwr[\"man_made\"~\"^(works|water_works|wastewater_plant|storage_tank|silo)$\"]({bbox});
  nwr[\"harbour\"=\"yes\"]({bbox});
  nwr[\"industrial\"]({bbox});
  way[\"bridge\"][\"highway\"]({bbox});
);
out tags center geom;"""


def topography_from_overpass(
    payloads: Iterable[dict[str, Any]],
    *,
    theater_id: str,
    scenario_reference_year: int | None,
    bounds: tuple[float, float, float, float],
) -> TheaterTopography:
    """Convert and deduplicate one or more tiled Overpass responses."""

    payload_list = tuple(payloads)
    features: dict[str, TopographyFeature] = {}
    for payload in payload_list:
        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise ValueError("Overpass payload does not contain an elements list")
        for element in elements:
            if not isinstance(element, dict):
                continue
            for feature in features_from_overpass_element(
                element,
                scenario_reference_year=scenario_reference_year,
                source_snapshot_date=_overpass_snapshot_date(payload),
            ):
                features[feature.object_id] = feature
    return TheaterTopography(
        theater_id=theater_id,
        scenario_reference_year=scenario_reference_year,
        source_snapshot_date=next((_overpass_snapshot_date(payload) for payload in payload_list if _overpass_snapshot_date(payload)), None),
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        bounds=bounds,
        features=tuple(sorted(features.values(), key=lambda feature: feature.object_id)),
        metadata={"external_source": "OpenStreetMap via Overpass", "dcs_verification": "pending"},
    )


def features_from_overpass_element(
    element: dict[str, Any],
    *,
    scenario_reference_year: int | None,
    source_snapshot_date: str | None = None,
) -> tuple[TopographyFeature, ...]:
    """Map one OSM element to one or more semantic topography features."""

    tags = element.get("tags")
    if not isinstance(tags, dict):
        return ()
    geometry = _geometry(element, tags)
    if geometry is None:
        return ()
    osm_type = str(element.get("type") or "object")
    osm_id = str(element.get("id") or "")
    if not osm_id:
        return ()
    source_id = f"OSM:{osm_type}/{osm_id}"
    name = str(tags.get("name") or tags.get("name:en") or "") or None
    valid_from = _tag_year(tags.get("start_date"))
    valid_to = _tag_year(tags.get("end_date"))
    common = {
        "source": "OpenStreetMap",
        "source_id": source_id,
        "scenario_reference_year": scenario_reference_year,
        "source_snapshot_date": source_snapshot_date,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "dcs_verified": False,
        "name": name,
    }
    output: list[TopographyFeature] = []
    natural = str(tags.get("natural") or "")
    waterway = str(tags.get("waterway") or "")
    if natural in {"water", "coastline"} or waterway in {"river", "canal"}:
        category = "coastline" if natural == "coastline" else waterway or str(tags.get("water") or "water")
        output.append(_feature(source_id, TopographyLayer.WATER, category, geometry, 0.75, tags, common))
    highway = str(tags.get("highway") or "")
    if highway in ROAD_CLASSES:
        output.append(_feature(source_id, TopographyLayer.ROADS, highway, geometry, 0.55, tags, common))
    railway = str(tags.get("railway") or "")
    if railway in RAIL_CLASSES:
        output.append(_feature(source_id, TopographyLayer.RAILWAYS, railway, geometry, 0.6, tags, common))
    place = str(tags.get("place") or "")
    if place in SETTLEMENT_CLASSES:
        output.append(_feature(source_id, TopographyLayer.SETTLEMENTS, place, geometry, 0.65, tags, common))
    infrastructure_category = _infrastructure_category(tags)
    if infrastructure_category is not None:
        output.append(
            _feature(source_id, TopographyLayer.INFRASTRUCTURE, infrastructure_category, geometry, 0.45, tags, common)
        )
    building = tags.get("building")
    if building not in {None, "no"}:
        output.append(_feature(source_id, TopographyLayer.BUILDINGS, str(building), geometry, 0.4, tags, common))
    landuse = tags.get("landuse")
    if landuse:
        output.append(_feature(source_id, TopographyLayer.LANDUSE, str(landuse), geometry, 0.5, tags, common))
    return tuple(output)


def _feature(
    source_id: str,
    layer: TopographyLayer,
    category: str,
    geometry: dict[str, Any],
    confidence: float,
    tags: dict[str, Any],
    common: dict[str, Any],
) -> TopographyFeature:
    properties: dict[str, Any] = {"osm_tags": dict(tags)}
    if layer is TopographyLayer.WATER:
        properties.update({"ground_passable": False, "naval_candidate": True})
    elif layer in {TopographyLayer.ROADS, TopographyLayer.RAILWAYS}:
        properties["transport_network"] = True
    return TopographyFeature(
        object_id=f"TOPOGRAPHY:{source_id}:{layer.value.removeprefix('topography_')}",
        layer=layer,
        category=category,
        geometry=geometry,
        confidence=confidence,
        properties=properties,
        **common,
    )


def _geometry(element: dict[str, Any], tags: dict[str, Any]) -> dict[str, Any] | None:
    points = element.get("geometry")
    if isinstance(points, list):
        coordinates = [
            [float(point["lon"]), float(point["lat"])]
            for point in points
            if isinstance(point, dict) and point.get("lon") is not None and point.get("lat") is not None
        ]
        if len(coordinates) >= 2:
            is_area = len(coordinates) >= 4 and coordinates[0] == coordinates[-1] and _is_area(tags)
            return {"type": "Polygon", "coordinates": [coordinates]} if is_area else {
                "type": "LineString", "coordinates": coordinates
            }
    if element.get("lon") is not None and element.get("lat") is not None:
        return {"type": "Point", "coordinates": [float(element["lon"]), float(element["lat"])]}
    center = element.get("center")
    if isinstance(center, dict) and center.get("lon") is not None and center.get("lat") is not None:
        return {"type": "Point", "coordinates": [float(center["lon"]), float(center["lat"])]}
    return None


def _is_area(tags: dict[str, Any]) -> bool:
    return (
        tags.get("natural") == "water"
        or tags.get("landuse") == "industrial"
        or tags.get("power") == "plant"
        or tags.get("man_made") in {"works", "water_works", "wastewater_plant", "storage_tank", "silo"}
        or tags.get("area") == "yes"
    )


def _infrastructure_category(tags: dict[str, Any]) -> str | None:
    if tags.get("bridge") not in {None, "no"} and tags.get("highway"):
        return "bridge"
    if tags.get("power") == "plant":
        return "power_plant"
    if tags.get("harbour") == "yes" or tags.get("landuse") == "port":
        return "harbour"
    if tags.get("man_made"):
        return str(tags["man_made"])
    if tags.get("industrial"):
        return str(tags["industrial"])
    if tags.get("landuse") == "industrial":
        return "industrial_area"
    return None


def _tag_year(value: Any) -> int | None:
    if value is None:
        return None
    match = _YEAR_PATTERN.search(str(value))
    return int(match.group(1)) if match else None


def _overpass_snapshot_date(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("osm3s")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("timestamp_osm_base")
    return str(value) if value else None
