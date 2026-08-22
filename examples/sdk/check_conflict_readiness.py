"""Validate the running mission before starting bilateral conflict control."""

from __future__ import annotations

import argparse

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    StrategicObjectiveGenerationConfig,
    StrategicVerificationRegistry,
    TheaterContext,
    TheaterInfrastructureSites,
    TheaterRailwayInfrastructure,
    TheaterSettlements,
    TheaterTransportInfrastructure,
    format_conflict_readiness,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


# Editable example configuration.
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH.with_name("Caucasus_topography.json")
BLUE_INTEL_ID = "INTEL:Blue Intel"
RED_INTEL_ID = "INTEL:Red Intel"
MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE = 10
REGISTER_OBJECTIVES = True
REPLACE_EXISTING_OBJECTIVES = False


def _load_context(profile_path) -> TheaterContext:
    theater, paths = load_example_theater(profile_path)
    return TheaterContext(
        theater_id=theater.theater_id,
        settlements=TheaterSettlements.load(paths.path("settlements")),
        transport=TheaterTransportInfrastructure.load(paths.path("transport_infrastructure")),
        railway=TheaterRailwayInfrastructure.load(paths.path("railway_infrastructure")),
        infrastructure=TheaterInfrastructureSites.load(paths.path("infrastructure_sites")),
        verifications=StrategicVerificationRegistry.load(
            paths.path("strategic_verifications")
        ).bind_theater(theater.theater_id),
    )


async def run(profile_path=THEATER_PROFILE) -> int:
    context = _load_context(profile_path)
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="conflict-readiness-example",
        display_name="Conflict Readiness Example",
    )
    report = await session.bridge.assess_conflict_readiness(
        theater=context,
        intel_ids={"blue": BLUE_INTEL_ID, "red": RED_INTEL_ID},
        objective_config=StrategicObjectiveGenerationConfig(
            maximum_geographic_objectives_per_category_per_scope=(
                MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE
            ),
        ),
        register_objectives=REGISTER_OBJECTIVES,
        replace_objectives=REPLACE_EXISTING_OBJECTIVES,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )

    print(format_conflict_readiness(report))
    if report.ready:
        print("\nPASS: the mission is ready for bilateral strategic conflict control.")
        return 0
    print("\nBLOCKED: correct the ERROR findings before starting either controller.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=THEATER_PROFILE)
    args = parser.parse_args()
    return run_example(lambda: run(args.profile))


if __name__ == "__main__":
    raise SystemExit(main())
