"""Inspect one strategic ground route between two DCS/MOOSE objects.

The daemon/control server and DCS mission are assumed to be running. Edit the
constants below; this example intentionally has no command-line parameters.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import (
    DebugMarkup,
    DebugMarkupPoint,
    GroundMobilityNetwork,
    MooseBridgeClient,
    RoadRoutingNetwork,
    TRACKED_ROAD_PROFILE,
    TRACKED_GROUND_PROFILE,
    format_ground_route,
    format_python_road_route,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0

NETWORK_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-ground-mobility.json"
ROAD_NETWORK_PATH = REPO_ROOT / "tmp" / "topography" / "GermanyCW-road-routing-mv.npz"
START_OBJECT_ID = "AIRBASE:Laage"
END_OBJECT_ID = "AIRBASE:Gross Mohrdorf"
PROFILE = TRACKED_GROUND_PROFILE
OVERLAY_ID = "ground-mobility-route"
ROUTE_COLOR = (1.0, 0.0, 0.85, 1.0)
PYTHON_ROUTE_COLOR = (0.0, 0.85, 1.0, 1.0)


def _sample_points(points: tuple[tuple[float, float], ...], maximum: int = 450) -> tuple[DebugMarkupPoint, ...]:
    if len(points) <= maximum:
        selected = points
    else:
        indexes = [round(index * (len(points) - 1) / (maximum - 1)) for index in range(maximum)]
        selected = tuple(points[index] for index in indexes)
    return tuple(DebugMarkupPoint(latitude, longitude) for latitude, longitude in selected)


async def run() -> int:
    if not NETWORK_PATH.is_file():
        print(f"Ground mobility graph not found: {NETWORK_PATH}")
        print("Run tools/build_ground_mobility.py first.")
        return 4

    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3
    bridge: MooseBridgeClient = sdk_from_control_client(
        control,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    start = await bridge.coords(START_OBJECT_ID, format="ll", timeout=COMMAND_TIMEOUT_SECONDS)
    end = await bridge.coords(END_OBJECT_ID, format="ll", timeout=COMMAND_TIMEOUT_SECONDS)
    if None in {start.latitude, start.longitude, end.latitude, end.longitude}:
        print("DCS did not return WGS84 coordinates for both route objects.")
        return 5

    network = GroundMobilityNetwork.load(NETWORK_PATH)
    route = network.route(
        start.latitude,
        start.longitude,
        end.latitude,
        end.longitude,
        profile=PROFILE,
    )
    print("Strategic ground mobility")
    print("=" * 80)
    print(f"From   : {START_OBJECT_ID}")
    print(f"To     : {END_OBJECT_ID}")
    print(f"Network: {len(network.nodes)} nodes, {len(network.edges)} edges")
    print(f"Strategic feasibility: {format_ground_route(route)}")
    if route is None:
        return 6

    python_route = None
    if ROAD_NETWORK_PATH.is_file():
        road_network = RoadRoutingNetwork.load(ROAD_NETWORK_PATH)
        python_route = road_network.route(
            start.latitude,
            start.longitude,
            end.latitude,
            end.longitude,
            profile=TRACKED_ROAD_PROFILE,
        )
        print(format_python_road_route(python_route))
    else:
        print(f"Python road graph not found: {ROAD_NETWORK_PATH}")

    dcs_route = await bridge.road_route(
        START_OBJECT_ID,
        END_OBJECT_ID,
        sample_spacing_m=100,
        max_points=500,
        timeout=60,
    )
    print(
        f"Native DCS road route: distance={dcs_route.distance_m / 1_000:.1f}km "
        f"points={len(dcs_route.points)}/{dcs_route.raw_point_count} "
        f"spacing={dcs_route.sample_spacing_m:.0f}m"
    )
    if dcs_route.pathfinding_cpu_ms is not None:
        print(
            f"Native DCS CPU: pathfinding={dcs_route.pathfinding_cpu_ms:.2f}ms "
            f"total={dcs_route.total_cpu_ms:.2f}ms"
        )
    drawn = False
    try:
        markups = [DebugMarkup("line", dcs_route.points, color=ROUTE_COLOR)]
        if python_route is not None:
            markups.append(DebugMarkup("line", _sample_points(python_route.points), color=PYTHON_ROUTE_COLOR))
        ack = await bridge.draw_debug_overlay(
            OVERLAY_ID,
            tuple(markups),
            replace=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        drawn = True
        print(f"DCS overlay: {ack.get('result') or ack}")
        print("Magenta=native DCS road route; cyan=local Python/OSM road route.")
        await asyncio.to_thread(input, "Inspect both routes, then press Enter to remove them ... ")
    finally:
        if drawn:
            ack = await bridge.clear_debug_overlay(
                OVERLAY_ID,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
            print(f"Overlay removed: {ack.get('result') or ack}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
