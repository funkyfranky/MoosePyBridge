"""Draw an OSMCoastline shoreline on the native DCS F10 map.

The daemon/control server and DCS mission are assumed to be running. Edit the
constants below; this example intentionally has no command-line parameters.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

from example_support import REPO_ROOT, open_example_session, run_example

from moosebridge import DebugMarkup, DebugMarkupPoint, MooseBridgeClient
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

LAND_POLYGONS_PATH = (
    REPO_ROOT / "tmp" / "theaters" / "GermanyCW" / "sources" / "osmcoastline" / "land_polygons.shp"
)
CENTER_OBJECT_ID = "AIRBASE:Laage"
RADIUS_KM = 100.0
INITIAL_SIMPLIFY_METERS = 150.0
MAX_GEOMETRY_PARTS = 80
MAX_DCS_MARKUPS = 450
OVERLAY_ID = "osmcoastline-verification"
COALITION = "all"
COASTLINE_COLOR = (0.0, 0.9, 1.0, 1.0)


def build_coastline_markups(
    path: Path,
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
) -> tuple[tuple[DebugMarkup, ...], float, float]:
    """Load, clip, and simplify a bounded OSMCoastline shoreline."""

    try:
        import pyogrio
        import shapely
        from pyproj import CRS, Transformer
        from shapely.geometry import Point, box
        from shapely.ops import transform
    except ImportError as exc:
        raise RuntimeError(
            'coastline overlays require: python -m pip install -e ".[topography]"'
        ) from exc

    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} "
        "+datum=WGS84 +units=m +no_defs"
    )
    source_crs = pyogrio.read_info(path).get("crs")
    if not source_crs:
        raise ValueError(f"Coastline source has no coordinate reference system: {path}")

    to_source = Transformer.from_crs("EPSG:4326", source_crs, always_xy=True)
    to_local = Transformer.from_crs(source_crs, local_crs, always_xy=True).transform
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True).transform

    # A generous envelope limits disk I/O. The exact circular clip is applied
    # later in the local metric projection.
    latitude_margin = radius_m / 110_574.0
    longitude_margin = radius_m / max(
        1.0,
        111_320.0 * abs(math.cos(math.radians(latitude))),
    )
    west = longitude - longitude_margin
    east = longitude + longitude_margin
    south = latitude - latitude_margin
    north = latitude + latitude_margin
    source_x, source_y = to_source.transform(
        [west, east, east, west],
        [south, south, north, north],
    )
    source_bounds = (
        min(source_x),
        min(source_y),
        max(source_x),
        max(source_y),
    )
    frame = pyogrio.read_dataframe(path, bbox=source_bounds, columns=[])
    geometries = [
        geometry
        for geometry in frame.geometry
        if geometry is not None and not geometry.is_empty
    ]
    if not geometries:
        return (), INITIAL_SIMPLIFY_METERS, 0.0

    # Union polygons before taking their boundary. This removes internal
    # polygon joins while retaining only the actual land/sea boundary.
    land = shapely.union_all(geometries)
    shoreline = land.boundary.intersection(box(*source_bounds))
    shoreline = transform(to_local, shoreline).intersection(Point(0, 0).buffer(radius_m))
    if shoreline.is_empty:
        return (), INITIAL_SIMPLIFY_METERS, 0.0

    original_length_m = float(shoreline.length)
    tolerance = INITIAL_SIMPLIFY_METERS
    selected_parts: list[Any] = []
    for _ in range(16):
        simplified = shoreline.simplify(tolerance, preserve_topology=True)
        parts = sorted(_line_parts(simplified), key=lambda line: line.length, reverse=True)
        selected_parts = parts[:MAX_GEOMETRY_PARTS]
        mark_count = sum(max(0, len(line.coords) - 1) for line in selected_parts)
        if mark_count <= MAX_DCS_MARKUPS:
            break
        tolerance *= 1.5
    else:
        raise ValueError("Coastline cannot be reduced to the configured DCS markup budget")

    markups = []
    for line in selected_parts:
        coordinates = tuple(to_wgs84(x, y) for x, y in line.coords)
        points = tuple(
            DebugMarkupPoint(latitude=lat, longitude=lon)
            for lon, lat in coordinates
        )
        if len(points) >= 2:
            markups.append(DebugMarkup("line", points, color=COASTLINE_COLOR))
    return tuple(markups), tolerance, original_length_m


def _line_parts(geometry: Any) -> tuple[Any, ...]:
    if geometry.geom_type == "LineString":
        return (geometry,)
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return tuple(line for part in geometry.geoms for line in _line_parts(part))
    return ()


async def run() -> int:
    if not LAND_POLYGONS_PATH.is_file():
        print(f"OSMCoastline land polygons not found: {LAND_POLYGONS_PATH}")
        print("Run tools/download_osm_coastline_data.py first.")
        return 4

    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge: MooseBridgeClient = session.bridge
    center = await bridge.coords(
        CENTER_OBJECT_ID,
        format="ll",
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if center.latitude is None or center.longitude is None:
        print(f"DCS did not return WGS84 coordinates for {CENTER_OBJECT_ID}.")
        return 5

    print(f"Loading coastline: {LAND_POLYGONS_PATH}", flush=True)
    markups, tolerance, length_m = build_coastline_markups(
        LAND_POLYGONS_PATH,
        latitude=center.latitude,
        longitude=center.longitude,
        radius_m=RADIUS_KM * 1_000.0,
    )
    if not markups:
        print(f"No coastline found within {RADIUS_KM:.1f} km of {CENTER_OBJECT_ID}.")
        return 6

    mark_count = sum(markup.mark_count for markup in markups)
    print(
        f"Drawing {len(markups)} coastline part(s), {mark_count} native markups, "
        f"within {RADIUS_KM:.1f} km of {CENTER_OBJECT_ID} ...",
        flush=True,
    )
    print(f"Visible coastline length: {length_m / 1_000.0:.1f} km", flush=True)
    print(f"Applied simplification : {tolerance:.0f} m", flush=True)

    drawn = False
    try:
        ack = await bridge.draw_debug_overlay(
            OVERLAY_ID,
            markups,
            coalition=COALITION,
            replace=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        drawn = True
        print(f"DCS overlay: {ack.get('result') or ack}", flush=True)
        await asyncio.to_thread(
            input,
            "Inspect the cyan coastline on the DCS F10 map, then press Enter to remove it ... ",
        )
    finally:
        if drawn:
            ack = await bridge.clear_debug_overlay(
                OVERLAY_ID,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
            print(f"Overlay removed: {ack.get('result') or ack}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
