"""Run one RECON AUFTRAG and assess its contribution to MOOSE INTEL.

The MoosePyBridge daemon and DCS mission are expected to be running already.
Edit the constants below to match the mission; this example deliberately has
no command-line parameters.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import (
    Auftrag_RECON,
    MooseBridgeCommandError,
    ReconRequirement,
    ZoneSet,
    format_recon_outcome,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
MISSION_TIMEOUT_SECONDS = 600.0

INTEL_ID = "INTEL:Blue Intel"
COMMANDER_ID = "COMMANDER:Blue Commander"
RECON_ZONES = ZoneSet("ZONE:Town Fight")

SPEED_KTS = 250
ALTITUDE_FT = 12_000

RECON_REQUIREMENT = ReconRequirement.manual(
    "ZONE:Town Fight",
    "GROUP:Ground-3",
)


async def run() -> int:
    """Submit RECON through COMMANDER and print its tactical outcome."""

    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
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


async def async_main() -> int:
    try:
        return await run()
    except (MooseBridgeCommandError, ValueError) as exc:
        print(f"RECON failed: {exc}")
        if isinstance(exc, MooseBridgeCommandError):
            print(f"ACK: {exc.ack}")
        return 5


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
