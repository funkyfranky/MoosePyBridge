"""Run one RECON AUFTRAG and observe the resulting MOOSE INTEL picture.

The MoosePyBridge daemon and DCS mission are expected to be running already.
Edit the constants below to match the mission; this example deliberately has
no command-line parameters.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import Auftrag_RECON, MooseBridgeClient, MooseBridgeCommandError, ZoneSet
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0

INTEL_ID = "INTEL:Blue Intel"
COMMANDER_ID = "COMMANDER:Blue Commander"
RECON_ZONES = ZoneSet("ZONE:Town Fight")

SPEED_KTS = 250
ALTITUDE_FT = 12_000
OBSERVATION_INTERVAL_SECONDS = 5.0


def contact_description(contact: object) -> str:
    """Return one compact line for a mirrored INTEL contact."""

    object_id = getattr(contact, "object_id", "?")
    target = getattr(contact, "target_object_id", None) or "?"
    threat = getattr(contact, "threat_level", None)
    recce = getattr(contact, "recce", None) or "?"
    x = getattr(contact, "x", None)
    z = getattr(contact, "z", None)
    position = f"x={x:.0f} z={z:.0f}" if isinstance(x, (int, float)) and isinstance(z, (int, float)) else "position=?"
    return f"{object_id} target={target} threat={threat} recce={recce} {position}"


def assigned_agent_description(bridge: MooseBridgeClient, opsgroup_id: str, agent_ids: set[str]) -> str:
    """Describe whether one assigned OPSGROUP is represented in INTEL."""

    opsgroup = bridge.opsgroup(opsgroup_id)
    group_name = opsgroup.group_name if opsgroup and opsgroup.group_name else opsgroup_id.removeprefix("OPSGROUP:")
    group_id = f"GROUP:{group_name}"
    state = opsgroup.state if opsgroup and opsgroup.state else "unknown"
    alive = opsgroup.alive if opsgroup else False
    return (
        f"RECON ASSET: {opsgroup_id} group={group_id} state={state} "
        f"alive={alive} intel_agent={group_id in agent_ids}"
    )


async def observe_intel(bridge: MooseBridgeClient, auftrag_id: str, known_contacts: set[str]) -> None:
    """Print changing agents, assigned assets, contacts, and lost contacts."""

    previous_counts: tuple[int | None, int | None, int] | None = None
    previous_agent_ids: set[str] | None = None
    previous_assigned_status: tuple[str, ...] = ()
    previous_contact_ids: set[str] = set(known_contacts)
    while True:
        await bridge.refresh_intel_state()
        await bridge.snapshot_auftraege()
        await bridge.snapshot_opsgroups()
        intel = bridge.intel(INTEL_ID)
        if intel is None:
            raise RuntimeError(f"INTEL is not available: {INTEL_ID}")

        contacts = bridge.contacts_of_intel(INTEL_ID)
        counts = (intel.alive_agent_count, intel.agent_count, len(contacts))
        if counts != previous_counts:
            print(
                f"INTEL agents={intel.alive_agent_count}/{intel.agent_count} "
                f"contacts={len(contacts)}",
                flush=True,
            )
            previous_counts = counts

        agent_ids = set(intel.agent_ids)
        if previous_agent_ids is not None:
            for agent_id in sorted(agent_ids - previous_agent_ids):
                print(f"INTEL AGENT ADDED: {agent_id}", flush=True)
            for agent_id in sorted(previous_agent_ids - agent_ids):
                print(f"INTEL AGENT REMOVED: {agent_id}", flush=True)
        previous_agent_ids = agent_ids

        mission = bridge.auftrag(auftrag_id)
        assigned_ids = tuple(sorted(mission.assigned_group_ids)) if mission else ()
        assigned_status = tuple(assigned_agent_description(bridge, opsgroup_id, agent_ids) for opsgroup_id in assigned_ids)
        if assigned_status != previous_assigned_status:
            for description in assigned_status:
                print(description, flush=True)
            previous_assigned_status = assigned_status

        contact_ids = {contact.object_id for contact in contacts}
        for contact_id in sorted(previous_contact_ids - contact_ids):
            print(f"CONTACT LOST: {contact_id}", flush=True)
        for contact in contacts:
            if contact.object_id not in known_contacts:
                known_contacts.add(contact.object_id)
                print(f"NEW CONTACT: {contact_description(contact)}", flush=True)
            elif contact.object_id not in previous_contact_ids:
                print(f"CONTACT REACQUIRED: {contact_description(contact)}", flush=True)
        previous_contact_ids = contact_ids

        await asyncio.sleep(OBSERVATION_INTERVAL_SECONDS)


async def run() -> int:
    """Submit RECON through the COMMANDER and monitor INTEL until evaluation."""

    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    await bridge.refresh_intel_state()
    intel = bridge.intel(INTEL_ID)
    if intel is None:
        print(f"INTEL is not registered: {INTEL_ID}")
        return 4

    initial_contacts = bridge.contacts_of_intel(INTEL_ID)
    known_contacts = {contact.object_id for contact in initial_contacts}
    print(
        f"Initial INTEL: agents={intel.alive_agent_count}/{intel.agent_count} "
        f"contacts={len(initial_contacts)}"
    )

    auftrag = Auftrag_RECON(
        zones=RECON_ZONES,
        speed_kts=SPEED_KTS,
        altitude_ft=ALTITUDE_FT,
        ad_infinitum=False,
        randomly=False,
    )
    auftrag.set_required_assets(min_count=1, max_count=1)

    ack = await bridge.add_auftrag(auftrag=auftrag, commander=COMMANDER_ID)
    result = ack.get("result", {})
    auftrag_id = str(result.get("auftrag_id") or "")
    print(f"RECON created: {auftrag_id} commander={result.get('commander_id')}")

    observer = asyncio.create_task(observe_intel(bridge, auftrag_id, known_contacts))
    try:
        summary = await bridge.get_auftrag_summary(auftrag, on_status=print)
    finally:
        observer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await observer

    print(f"RECON completed: success={summary.success}")
    print(summary.to_dict())
    return 0


async def async_main() -> int:
    try:
        return await run()
    except MooseBridgeCommandError as exc:
        print(f"DCS rejected the command: {exc}")
        print(f"ACK: {exc.ack}")
        return 5


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
