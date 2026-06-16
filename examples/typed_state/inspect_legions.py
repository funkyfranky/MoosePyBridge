"""Inspect typed MOOSE Bridge LEGION state from a running DCS mission.

Load order in DCS:
    1. Moose.lua
    2. MooseBridgeJson.lua
    3. MooseBridge.lua
    4. MooseBridgeLegionSnapshots.lua
    5. MooseBridgeMissionExample.lua

Example:
    PYTHONPATH=python python examples/typed_state/inspect_legions.py --host 127.0.0.1 --port 51000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from moosebridge import BridgeCommand, MooseBridgeClient, MooseBridgeServer
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
        "Make sure MooseBridge.lua and MooseBridgeLegionSnapshots.lua are loaded and use the same host/port."
    )


async def request_legion_snapshot(client: MooseBridgeClient) -> None:
    """Request a LEGION snapshot.

    :param client: MOOSE Bridge SDK client.
    """

    await client.server.send_command(BridgeCommand(action="snapshot.legions", params={}))
    await asyncio.sleep(0.1)


def print_legions(client: MooseBridgeClient) -> None:
    """Print typed LEGION objects.

    :param client: MOOSE Bridge SDK client.
    """

    legions = list(client.state.legion_objects.values())
    print(f"\nLEGION objects: {len(legions)}")

    for legion in legions:
        queue = ", ".join(legion.auftrag_queue_ids) or "none"
        cohorts = ", ".join(legion.cohort_ids) or "none"
        print(
            f"  {legion.object_id} "
            f"category={legion.category} "
            f"state={legion.state} "
            f"coalition={legion.coalition or legion.coalition_name} "
            f"airbase={legion.airbase_name} "
            f"n_cohorts={legion.n_cohorts} "
            f"cohorts=[{cohorts}] "
            f"queue=[{queue}]"
        )

        for cohort in legion.cohorts:
            print(
                f"    {cohort.object_id} "
                f"category={cohort.category} "
                f"is_air={cohort.is_air} "
                f"is_ground={cohort.is_ground} "
                f"is_naval={cohort.is_naval}"
            )


async def async_main(args: argparse.Namespace) -> int:
    """Run the LEGION state inspection example.

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

        print("DCS connected. Requesting LEGION snapshot ...")
        await request_legion_snapshot(client)

        print_legions(client)
        return 0

    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(description="Inspect typed MOOSE Bridge LEGION state.")
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
