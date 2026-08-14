"""Generate scope-bounded strategic objectives for the running DCS mission."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import (
    TheaterInfrastructureSites,
    TheaterRailwayInfrastructure,
    TheaterSettlements,
    TheaterTransportInfrastructure,
    format_strategic_goal_generation,
    format_strategic_objective_generation,
    format_strategic_scope,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
COALITION = "blue"

TOPOGRAPHY_DIR = REPO_ROOT / "tmp" / "topography"
SETTLEMENTS_PATH = TOPOGRAPHY_DIR / "GermanyCW-settlements.geojson"
TRANSPORT_PATH = TOPOGRAPHY_DIR / "GermanyCW-transport-infrastructure-mv.geojson"
RAILWAY_PATH = TOPOGRAPHY_DIR / "GermanyCW-railway-infrastructure-mv.geojson"
INFRASTRUCTURE_PATH = TOPOGRAPHY_DIR / "GermanyCW-infrastructure-sites.geojson"


async def run() -> int:
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    await bridge.refresh_global_picture()
    await bridge.refresh_diplomacy_state()
    scope = bridge.build_strategic_scope()
    result = bridge.generate_strategic_objectives(
        settlements=TheaterSettlements.load(SETTLEMENTS_PATH),
        transport=TheaterTransportInfrastructure.load(TRANSPORT_PATH),
        railway=TheaterRailwayInfrastructure.load(RAILWAY_PATH),
        infrastructure=TheaterInfrastructureSites.load(INFRASTRUCTURE_PATH),
    )

    print(format_strategic_scope(scope))
    print()
    print(format_strategic_objective_generation(result))
    print("\nGenerated objectives")
    print("=" * 90)
    for objective in result.objectives:
        targetable = "yes" if objective.metadata.get("targetable") else "no"
        print(
            f"{objective.objective_id} owner={objective.owner or '-'} kind={objective.kind.value} "
            f"value={objective.strategic_value:.1f} targetable={targetable} name={objective.name}"
        )
    goals = bridge.generate_strategic_goals(COALITION, generation_id="OBJECTIVE-PREVIEW")
    print()
    print(format_strategic_goal_generation(goals))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
