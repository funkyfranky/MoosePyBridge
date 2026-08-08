from __future__ import annotations

import json
import math

import pytest

from moosebridge.topography_viewport import TopographyViewportStore


def test_viewport_store_filters_bbox_layer_and_zoom(tmp_path) -> None:
    geopandas = pytest.importorskip("geopandas")
    pyogrio = pytest.importorskip("pyogrio")
    geometry = pytest.importorskip("shapely.geometry")
    frame = geopandas.GeoDataFrame(
        {
            "layer": ["topography_roads", "topography_roads", "topography_water", "topography_roads"],
            "object_id": ["ROAD:all", "ROAD:low", "WATER:high", "ROAD:outside"],
            "category": ["motorway", "primary", "lake", "primary"],
            "detail_level": ["all", "low", "high", "all"],
        },
        geometry=[
            geometry.Point(12.0, 54.0),
            geometry.Point(12.1, 54.0),
            geometry.Point(12.2, 54.0),
            geometry.Point(14.0, 55.0),
        ],
        crs="EPSG:4326",
    )
    shard = tmp_path / "test.fgb"
    pyogrio.write_dataframe(frame, shard, driver="FlatGeobuf", spatial_index=True)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "moosebridge.topography_viewport",
                "schema_version": 1,
                "theater_id": "GermanyCW",
                "shards": [{
                    "path": shard.name,
                    "bounds": [12.0, 54.0, 14.0, 55.0],
                    "feature_count": 4,
                    "layers": ["topography_roads", "topography_water"],
                    "detail_levels": ["all", "low", "high"],
                }],
            }
        ),
        encoding="utf-8",
    )
    store = TopographyViewportStore(manifest)

    broad = store.query((11.9, 53.9, 12.3, 54.1), zoom=5, layers=["topography_roads"])
    detailed = store.query((11.9, 53.9, 12.3, 54.1), zoom=10)

    assert [feature["properties"]["object_id"] for feature in broad["features"]] == ["ROAD:all"]
    assert {feature["properties"]["object_id"] for feature in detailed["features"]} == {
        "ROAD:all", "ROAD:low", "WATER:high",
    }
    assert detailed["properties"]["detail_levels"] == ["all", "high", "low"]
    assert detailed["properties"]["truncated"] is False

    mapbox_vector_tile = pytest.importorskip("mapbox_vector_tile")
    zoom = 9
    tile_count = 1 << zoom
    x = int((12.0 + 180) / 360 * tile_count)
    latitude_radians = math.radians(54.0)
    y = int((1 - math.asinh(math.tan(latitude_radians)) / math.pi) / 2 * tile_count)
    tile, diagnostics = store.vector_tile("topography_roads", zoom, x, y)
    decoded = mapbox_vector_tile.decode(tile)

    assert "topography_roads" in decoded
    assert diagnostics["feature_count"] >= 1
    assert decoded["topography_roads"]["features"][0]["properties"]["object_id"].startswith("ROAD:")


def test_viewport_store_rejects_unknown_layer(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "schema": "moosebridge.topography_viewport",
            "schema_version": 1,
            "theater_id": "GermanyCW",
            "shards": [],
        }),
        encoding="utf-8",
    )
    store = TopographyViewportStore(manifest)

    with pytest.raises(ValueError, match="unsupported topography layer"):
        store.query((11.9, 53.9, 12.3, 54.1), zoom=8, layers=["groups"])


def test_viewport_limit_is_distributed_across_shards(tmp_path) -> None:
    geopandas = pytest.importorskip("geopandas")
    pyogrio = pytest.importorskip("pyogrio")
    geometry = pytest.importorskip("shapely.geometry")
    shards = []
    for name, longitude in (("west", 11.0), ("east", 13.0)):
        frame = geopandas.GeoDataFrame(
            {
                "layer": ["topography_roads"] * 3,
                "object_id": [f"{name}:{index}" for index in range(3)],
                "category": ["motorway"] * 3,
                "detail_level": ["all"] * 3,
            },
            geometry=[geometry.Point(longitude, 54.0 + index / 100) for index in range(3)],
            crs="EPSG:4326",
        )
        path = tmp_path / f"{name}.fgb"
        pyogrio.write_dataframe(frame, path, driver="FlatGeobuf", spatial_index=True)
        shards.append({
            "path": path.name,
            "bounds": [longitude, 54.0, longitude, 54.02],
            "feature_count": 3,
            "layers": ["topography_roads"],
            "detail_levels": ["all"],
        })
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "moosebridge.topography_viewport",
        "schema_version": 1,
        "theater_id": "GermanyCW",
        "shards": shards,
    }), encoding="utf-8")

    result = TopographyViewportStore(manifest).query(
        (10.0, 53.0, 14.0, 55.0),
        zoom=5,
        layers=["topography_roads"],
        limit=2,
    )

    assert {feature["properties"]["object_id"].split(":")[0] for feature in result["features"]} == {"west", "east"}
    assert result["properties"]["truncated"] is True
