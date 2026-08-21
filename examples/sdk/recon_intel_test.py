"""Run one RECON AUFTRAG and assess its contribution to MOOSE INTEL.

The MoosePyBridge daemon and DCS mission are expected to be running already.
Edit the constants below to match the mission; this example deliberately has
no command-line parameters.
"""

from __future__ import annotations

from example_support import open_example_session, run_example

from moosebridge import (
    Auftrag_RECON,
    ReconRequirement,
    ZoneSet,
    format_recon_outcome,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
MISSION_TIMEOUT_SECONDS = 600.0

INTEL_ID = "INTEL:Blue Intel"
COMMANDER_ID = "COMMANDER:Blue Commander"
RECON_ZONES = ZoneSet("ZONE:Red Camp Achigvara")

SPEED_KTS = 250
ALTITUDE_FT = 12_000

RECON_REQUIREMENT = ReconRequirement("ZONE:Red Camp Achigvara")


async def run() -> int:
    """Submit RECON through COMMANDER and print its tactical outcome."""

    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge
    await bridge.snapshot_groups()
    unavailable_targets = []
    for target_id in RECON_REQUIREMENT.relevant_target_ids:
        if not target_id.startswith("GROUP:"):
            continue
        target = bridge.state.groups.get(target_id)
        if target is None or target.get("alive") is not True or target.get("active") is not True:
            unavailable_targets.append(target_id)
    if unavailable_targets:
        print("RECON target groups are not active and alive:")
        for target_id in unavailable_targets:
            print(f"  {target_id}")
        print("Restart the mission or select a currently active target group.")
        return 4

    auftrag = Auftrag_RECON(
        zones=RECON_ZONES,
        speed_kts=SPEED_KTS,
        altitude_ft=ALTITUDE_FT,
        ad_infinitum=False,
        randomly=False,
    )
    auftrag.set_required_assets(min_count=1, max_count=1)

    outcome = await bridge.execute_recon(
        auftrag,
        intel=INTEL_ID,
        commander=COMMANDER_ID,
        requirement=RECON_REQUIREMENT,
        timeout_s=MISSION_TIMEOUT_SECONDS,
        command_timeout=COMMAND_TIMEOUT_SECONDS,
        on_status=print,
    )
    print()
    print(format_recon_outcome(outcome))
    return 0


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
