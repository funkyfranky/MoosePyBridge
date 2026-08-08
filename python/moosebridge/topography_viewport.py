"""Spatially indexed viewport access to large theater topography caches."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .topography import TopographyLayer


VIEWPORT_SCHEMA = "moosebridge.topography_viewport"
VIEWPORT_SCHEMA_VERSION = 1
DEFAULT_VIEWPORT_FEATURE_LIMIT = 20_000
MAX_VIEWPORT_FEATURE_LIMIT = 50_000
MIN_VECTOR_TILE_ZOOM = 8
MAX_VECTOR_TILE_ZOOM = 14
VECTOR_TILE_PROPERTY_KEYS = frozenset({
    "object_id", "name", "layer", "category", "source", "source_id",
    "confidence", "dcs_verified", "detail_level", "valid_from", "valid_to",
})


@dataclass(slots=True, frozen=True)
class TopographyViewportShard:
    """One spatially indexed FlatGeobuf source and its coarse extent."""

    path: Path
    bounds: tuple[float, float, float, float]
    feature_count: int
    layers: frozenset[str]
    detail_levels: frozenset[str]

    def intersects(self, bounds: tuple[float, float, float, float]) -> bool:
        west, south, east, north = bounds
        own_west, own_south, own_east, own_north = self.bounds
        return not (own_east < west or own_west > east or own_north < south or own_south > north)


class TopographyViewportStore:
    """Query indexed topography shards by WGS84 viewport and zoom level."""

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if payload.get("schema") != VIEWPORT_SCHEMA:
            raise ValueError("not a MooseBridge topography viewport manifest")
        if int(payload.get("schema_version") or 0) != VIEWPORT_SCHEMA_VERSION:
            raise ValueError("unsupported topography viewport manifest version")
        self.theater_id = str(payload.get("theater_id") or "")
        if not self.theater_id:
            raise ValueError("topography viewport manifest requires theater_id")
        root = self.manifest_path.parent
        shards: list[TopographyViewportShard] = []
        for item in payload.get("shards") or []:
            raw_bounds = item.get("bounds")
            if not isinstance(raw_bounds, list) or len(raw_bounds) != 4:
                raise ValueError("topography viewport shard requires four bounds")
            path = root / str(item.get("path") or "")
            if not path.is_file():
                raise FileNotFoundError(path)
            shards.append(
                TopographyViewportShard(
                    path=path,
                    bounds=tuple(float(value) for value in raw_bounds),  # type: ignore[arg-type]
                    feature_count=int(item.get("feature_count") or 0),
                    layers=frozenset(str(value) for value in item.get("layers") or []),
                    detail_levels=frozenset(str(value) for value in item.get("detail_levels") or []),
                )
            )
        self.shards = tuple(shards)
        self.feature_count = sum(shard.feature_count for shard in self.shards)
        self.metadata = {
            key: value
            for key, value in payload.items()
            if key not in {"schema", "schema_version", "theater_id", "shards"}
        }

    def query(
        self,
        bounds: tuple[float, float, float, float],
        *,
        zoom: float,
        layers: Iterable[str] | None = None,
        limit: int = DEFAULT_VIEWPORT_FEATURE_LIMIT,
    ) -> dict[str, Any]:
        """Return a bounded GeoJSON feature collection for one browser viewport."""

        west, south, east, north = (float(value) for value in bounds)
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("invalid WGS84 viewport bounds")
        allowed_layers = {layer.value for layer in TopographyLayer}
        selected_layers = set(layers or allowed_layers)
        unknown_layers = selected_layers - allowed_layers
        if unknown_layers:
            raise ValueError(f"unsupported topography layer(s): {', '.join(sorted(unknown_layers))}")
        selected_limit = min(MAX_VIEWPORT_FEATURE_LIMIT, max(1, int(limit)))
        detail_levels = _detail_levels_for_zoom(zoom)
        selected_bounds = (west, south, east, north)
        candidates = [
            shard
            for shard in self.shards
            if shard.intersects(selected_bounds)
            and shard.layers.intersection(selected_layers)
            and shard.detail_levels.intersection(detail_levels)
        ]
        where = _where_clause(selected_layers, detail_levels)
        features: list[dict[str, Any]] = []
        object_ids: set[str] = set()
        queried_shards = 0
        truncated = False
        try:
            import pyogrio
        except ImportError as exc:
            raise RuntimeError('viewport topography requires: python -m pip install -e ".[map]"') from exc
        for index, shard in enumerate(candidates):
            remaining = selected_limit - len(features)
            if remaining <= 0:
                truncated = True
                break
            remaining_shards = len(candidates) - index
            shard_limit = max(1, (remaining + remaining_shards - 1) // remaining_shards)
            frame = pyogrio.read_dataframe(
                shard.path,
                bbox=selected_bounds,
                where=where,
                max_features=shard_limit + 1,
            )
            queried_shards += 1
            if len(frame) > shard_limit:
                frame = frame.iloc[:shard_limit]
                truncated = True
            if frame.empty:
                continue
            payload = json.loads(frame.to_json(drop_id=True, to_wgs84=True, default=str))
            for feature in payload.get("features") or []:
                object_id = str((feature.get("properties") or {}).get("object_id") or "")
                if object_id and object_id in object_ids:
                    continue
                if object_id:
                    object_ids.add(object_id)
                features.append(feature)
                if len(features) >= selected_limit:
                    truncated = True
                    break
        return {
            "type": "FeatureCollection",
            "features": features,
            "properties": {
                "schema": "moosebridge.topography_viewport_response",
                "theater_id": self.theater_id,
                "bounds": [west, south, east, north],
                "zoom": float(zoom),
                "detail_levels": sorted(detail_levels),
                "layers": sorted(selected_layers),
                "feature_count": len(features),
                "feature_limit": selected_limit,
                "candidate_shard_count": len(candidates),
                "queried_shard_count": queried_shards,
                "truncated": truncated,
            },
        }

    @lru_cache(maxsize=128)
    def vector_tile(self, layer: str, zoom: int, x: int, y: int) -> tuple[bytes, dict[str, Any]]:
        """Encode one cached Mapbox Vector Tile from the indexed source shards."""

        if not MIN_VECTOR_TILE_ZOOM <= zoom <= MAX_VECTOR_TILE_ZOOM:
            raise ValueError(f"vector tile zoom must be {MIN_VECTOR_TILE_ZOOM}..{MAX_VECTOR_TILE_ZOOM}")
        tile_count = 1 << zoom
        if not 0 <= x < tile_count or not 0 <= y < tile_count:
            raise ValueError("vector tile coordinates are outside the zoom grid")
        allowed_layers = {item.value for item in TopographyLayer}
        if layer not in allowed_layers:
            raise ValueError(f"unsupported topography layer: {layer}")
        bounds = _tile_bounds(zoom, x, y)
        payload = self.query(bounds, zoom=zoom, layers=[layer], limit=MAX_VIEWPORT_FEATURE_LIMIT)
        try:
            import mapbox_vector_tile
            import shapely
            from shapely.geometry import box, shape
        except ImportError as exc:
            raise RuntimeError('vector tiles require: python -m pip install -e ".[map]"') from exc
        west, south, east, north = bounds
        width = east - west
        height = north - south
        clipping_envelope = box(west - width * 0.02, south - height * 0.02, east + width * 0.02, north + height * 0.02)
        tolerance = width / 4096 * (4 if zoom <= 6 else 2 if zoom <= 8 else 1)
        layers: dict[str, list[dict[str, Any]]] = {}
        encoded_feature_count = 0
        for feature in payload["features"]:
            properties = dict(feature.get("properties") or {})
            layer_name = str(properties.get("layer") or "")
            if not layer_name:
                continue
            geometry = shape(feature.get("geometry") or {})
            if not geometry.is_valid:
                geometry = shapely.make_valid(geometry)
            geometry = geometry.intersection(clipping_envelope)
            if tolerance > 0 and not geometry.is_empty:
                geometry = geometry.simplify(tolerance, preserve_topology=True)
            safe_properties = {
                key: value
                for key, value in properties.items()
                if key in VECTOR_TILE_PROPERTY_KEYS and isinstance(value, (str, int, float, bool))
            }
            for part in _vector_tile_geometries(geometry):
                layers.setdefault(layer_name, []).append({"geometry": part, "properties": safe_properties})
                encoded_feature_count += 1
        encoded_layers = [
            {"name": name, "features": features}
            for name, features in sorted(layers.items())
            if features
        ]
        tile = mapbox_vector_tile.encode(
            encoded_layers,
            default_options={"quantize_bounds": bounds, "extents": 4096, "y_coord_down": False},
        ) if encoded_layers else b""
        return tile, {
            "feature_count": encoded_feature_count,
            "source_feature_count": len(payload["features"]),
            "truncated": payload["properties"]["truncated"],
            "detail_levels": payload["properties"]["detail_levels"],
        }


def _detail_levels_for_zoom(zoom: float) -> frozenset[str]:
    levels = {"all"}
    if zoom >= 6:
        levels.add("low")
    if zoom >= 10:
        levels.add("high")
    return frozenset(levels)


def _where_clause(layers: set[str], detail_levels: frozenset[str]) -> str:
    layer_values = ",".join(f"'{value}'" for value in sorted(layers))
    detail_values = ",".join(f"'{value}'" for value in sorted(detail_levels))
    return f"layer IN ({layer_values}) AND detail_level IN ({detail_values})"


def _tile_bounds(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    tile_count = 1 << zoom
    west = x / tile_count * 360.0 - 180.0
    east = (x + 1) / tile_count * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / tile_count))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / tile_count))))
    return west, south, east, north


def _vector_tile_geometries(geometry: Any) -> list[Any]:
    if geometry.is_empty:
        return []
    if geometry.geom_type in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [part for item in geometry.geoms for part in _vector_tile_geometries(item)]
    return []
