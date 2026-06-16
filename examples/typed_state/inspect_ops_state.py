"""Inspect typed MOOSE Bridge OPS state from a running DCS mission.

Run this script while DCS has loaded the MOOSE Bridge mission-side Lua files.
The script starts a local Python bridge server, waits for the DCS Lua bridge to
connect, requests OPS snapshots through the SDK, and prints the typed Python
state model.

Example:
    PYTHONPATH=python python examples/typed_state/inspect_ops_state.py --host 127.0.0.1 --port 51000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from moosebridge import MooseBridgeClient, MooseBridgeServer
from moosebridge.server import DEFAULT_PORT


async def wait_for_dcs_connection(server: MooseBridgeServer, timeout_s: float) -> None:
    """Wait until the DCS Lua bridge is connected.

    :param server: Running MOOSE Bridge server.
    :param timeout_s: Maximum wait time in seconds.
    :raises TimeoutError: If no DCS connection appears before the timeout.
    """

    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if server.state.connected:
            return
        await asyncio.sleep(0.1)

    raise TimeoutError(
        f"No DCS bridge connection after {timeout_s:.1f} s. "
        "Make sure MooseBridge.lua is loaded in the mission and uses the same host/port."
    )


def print_opszones(client: MooseBridgeClient) -> None:
    """Print typed OPSZONE objects.

    :param client: MOOSE Bridge SDK client.
    """

    zones = list(client.state.opszone_objects.values())
    print(f"\nOPSZONE objects: {len(zones)}")

    for zone in zones:
        print(
            f"  {zone.object_id} "
            f"state={zone.state} "
            f"owner={zone.owner_current_name} "
            f"zone_type={zone.zone_type} "
            f"radius={zone.zone_radius} "
            f"x={zone.x} z={zone.z}"
        )


def print_opsgroups(client: MooseBridgeClient) -> None:
    """Print typed OPSGROUP objects and their AUFTRAG relationships.

    :param client: MOOSE Bridge SDK client.
    """

    groups = list(client.state.opsgroup_objects.values())
    print(f"\nOPSGROUP objects: {len(groups)}")

    for group in groups:
        current_auftrag = client.current_auftrag_for_group(group.object_id)
        queued_auftraege = client.queued_auftraege_for_group(group.object_id)

        current_text = "none"
        if current_auftrag:
            current_text = f"{current_auftrag.object_id}({current_auftrag.type}/{current_auftrag.status})"

        queue_text = ", ".join(f"{auftrag.object_id}({auftrag.type})" for auftrag in queued_auftraege) or "none"

        print(
            f"  {group.object_id} "
            f"category={group.category} "
            f"coalition={group.coalition} "
            f"state={group.state} "
            f"alive={group.alive} "
            f"active={group.active} "
            f"current_auftrag={current_text} "
            f"queue=[{queue_text}] "
            f"detected_groups={len(group.detected_group_ids)} "
            f"x={group.x} z={group.z}"
        )


def print_auftraege(client: MooseBridgeClient) -> None:
    """Print typed AUFTRAG objects.

    :param client: MOOSE Bridge SDK client.
    """

    auftraege = list(client.state.auftrag_objects.values())
    print(f"\nAUFTRAG objects: {len(auftraege)}")

    for auftrag in auftraege:
        assigned = ", ".join(auftrag.assigned_group_ids) or "none"
        print(
            f"  {auftrag.object_id} "
            f"type={auftrag.type} "
            f"status={auftrag.status} "
            f"name={auftrag.name} "
            f"prio={auftrag.prio} "
            f"urgent={auftrag.urgent} "
            f"assigned_groups=[{assigned}]"
        )


async def async_main(args: argparse.Namespace) -> int:
    """Run the typed state inspection example.

    :param args: Parsed command-line arguments.
    :returns: Process exit code.
    """

    log_path = Path(args.log) if args.log else None
    server = MooseBridgeServer(host=args.host, port=args.port, log_path=log_path)
    client = MooseBridgeClient(server)

    await server.start()

    try:
        print(f"Waiting for DCS bridge connection on {args.host}:{args.port} ...")
        await wait_for_dcs_connection(server, args.connect_timeout)

        print("DCS connected. Requesting OPS state through SDK ...")
        await client.request_ops_state()

        print_opszones(client)
        print_opsgroups(client)
        print_auftraege(client)

        return 0

    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(description="Inspect typed MOOSE Bridge OPS state.")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface for the Python bridge server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port for the Python bridge server.")
    parser.add_argument("--connect-timeout", type=float, default=60.0, help="Seconds to wait for DCS to connect.")
    parser.add_argument("--log", default=None, help="Optional raw JSONL protocol log path.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> int:
    """Run the script entry point.

    :returns: Process exit code.
    """

    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
