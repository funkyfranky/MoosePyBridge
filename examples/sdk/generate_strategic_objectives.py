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
    ConflictControllerConfig,
    RuleBasedConflictController,
    StrategicObjectiveGenerationConfig,
    StrategicVerificationRegistry,
    TheaterInfrastructureSites,
    TheaterRailwayInfrastructure,
    TheaterSettlements,
    TheaterTransportInfrastructure,
    format_strategic_goal_generation,
    format_strategic_goal_portfolio,
    format_strategic_objective_generation,
    format_relationship,
    format_strategic_scope,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
COALITION = "blue"
INTEL_ID = "INTEL:Blue Intel"
MAX_CONCURRENT_GOALS = 3
# False keeps the current diplomacy state. Set True only when this preview is
# explicitly allowed to declare war through the conflict controller.
MANAGE_RELATIONSHIP = False
OBJECTIVE_PREVIEW_LIMIT = 30
MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE = 10

TOPOGRAPHY_DIR = REPO_ROOT / "tmp" / "topography"
SETTLEMENTS_PATH = TOPOGRAPHY_DIR / "GermanyCW-settlements.geojson"
TRANSPORT_PATH = TOPOGRAPHY_DIR / "GermanyCW-transport-infrastructure-mv.geojson"
RAILWAY_PATH = TOPOGRAPHY_DIR / "GermanyCW-railway-infrastructure-mv.geojson"
INFRASTRUCTURE_PATH = TOPOGRAPHY_DIR / "GermanyCW-infrastructure-sites.geojson"
VERIFICATIONS_PATH = TOPOGRAPHY_DIR / "GermanyCW-strategic-verifications.json"


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
        verifications=StrategicVerificationRegistry.load(VERIFICATIONS_PATH),
        config=StrategicObjectiveGenerationConfig(
            maximum_geographic_objectives_per_category_per_scope=(
                MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE
            ),
        ),
    )

    print(format_strategic_scope(scope))
    print()
    print(format_strategic_objective_generation(result))
    print("\nGenerated objectives")
    print("=" * 90)
    for objective in result.objectives[:OBJECTIVE_PREVIEW_LIMIT]:
        targetable = "yes" if objective.metadata.get("targetable") else "no"
        print(
            f"{objective.objective_id} owner={objective.owner or '-'} kind={objective.kind.value} "
            f"value={objective.strategic_value:.1f} targetable={targetable} name={objective.name}"
        )
    controller = RuleBasedConflictController(
        bridge,
        ConflictControllerConfig(
            coalition=COALITION,
            intel_id=INTEL_ID,
            controller_id=f"strategic-preview.{COALITION}",
            max_concurrent_goals=MAX_CONCURRENT_GOALS,
        ),
    )
    cycle = await controller.run_cycle(execute=False, manage_relationship=MANAGE_RELATIONSHIP)

    print()
    print(format_relationship(bridge.relationship))
    print()
    print(format_strategic_goal_generation(cycle.goal_generation))
    print()
    print(format_strategic_goal_portfolio(cycle.portfolio))
    if cycle.issues:
        print("\nPlanning issues")
        print("=" * 90)
        for issue in cycle.issues:
            print(f"{issue.objective_id} stage={issue.stage}: {issue.message}")
    if len(result.objectives) > OBJECTIVE_PREVIEW_LIMIT:
        print(f"\nObjective list shows {OBJECTIVE_PREVIEW_LIMIT}/{len(result.objectives)} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
