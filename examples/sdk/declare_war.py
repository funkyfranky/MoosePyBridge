"""Explicitly start the current DCS mission in a state of war."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import RelationshipState, format_relationship
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
DECLARING_COALITION = "blue"
DECLARATION_REASON = "Start the autonomous conflict simulation"


async def main() -> int:
    control = MooseBridgeControlClient(
        CONTROL_HOST,
        CONTROL_PORT,
        client_id="war-declaration-example",
        display_name="War Declaration Example",
    )
    status = await control.status()
    if not status.get("connected"):
        print("DCS is not connected to the MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control)
    await bridge.refresh_diplomacy_state()
    if bridge.relationship.state is RelationshipState.WAR:
        print("The coalitions are already at war.")
    else:
        incident = bridge.declare_war(
            DECLARING_COALITION,
            reason=DECLARATION_REASON,
        )
        await bridge.persist_diplomacy_state()
        print(
            f"{incident.actor_coalition} declared war on "
            f"{incident.target_coalition}: {DECLARATION_REASON}"
        )
    print()
    print(format_relationship(bridge.relationship))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
