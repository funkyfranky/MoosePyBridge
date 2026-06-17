"""Find COHORTs capable of a requested AUFTRAG mission type.

This is an advisory-only example. It does not create or assign AUFTRAGs in DCS.

Load order in DCS:
    1. Moose.lua
    2. MooseBridgeJson.lua
    3. MooseBridge.lua
    4. MooseBridgeMissionExample.lua

Example:
    PYTHONPATH=python python examples/advisory/find_capable_cohorts.py --mission-type BAI --host 127.0.0.1 --port 51000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from moosebridge import BridgeCommand, MooseBridgeClient, MooseBridgeServer, get_auftrag_type_spec
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
        "Make sure MooseBridge.lua is loaded and uses the same host/port."
    )


async def request_required_snapshots(client: MooseBridgeClient) -> None:
    """Request snapshots needed for COHORT capability advisory.

    :param client: MOOSE Bridge SDK client.
    """

    await client.server.send_command(BridgeCommand(action="snapshot.cohorts", params={}))
    await asyncio.sleep(0.1)


def print_auftrag_spec(mission_type: str) -> None:
    """Print the known advisory AUFTRAG specification.

    :param mission_type: AUFTRAG mission type key.
    """

    spec = get_auftrag_type_spec(mission_type)
    if spec is None:
        print(f"Mission type: {mission_type}")
        print("Known advisory spec: no")
        return

    print(f"Mission type: {spec.mission_type}")
    print(f"Constructor: {spec.constructor}")
    print(f"Performer categories: {', '.join(spec.performer_categories)}")
    print("Parameters:")
    for parameter in spec.parameters:
        required = "optional" if parameter.optional else "required"
        accepted = ", ".join(parameter.accepted_objects)
        print(f"  - {parameter.name}: {required}, accepted={accepted}, {parameter.description}")


def print_capable_cohorts(client: MooseBridgeClient, mission_type: str) -> None:
    """Print COHORTs capable of the requested mission type.

    :param client: MOOSE Bridge SDK client.
    :param mission_type: AUFTRAG mission type key.
    """

    capable = client.state.cohorts_capable_of(mission_type)
    capable_with_stock = client.state.cohorts_with_stock_for_mission_type(mission_type)

    print(f"\nCapable cohorts: {len(capable)}")
    for cohort in capable:
        performers = ", ".join(cohort.performer_categories) or "none"
        mission_types = ", ".join(cohort.mission_types) or "none"
        print(
            f"  {cohort.object_id} "
            f"legion={cohort.legion_id} "
            f"performers=[{performers}] "
            f"mission_types=[{mission_types}] "
            f"stock={cohort.stock_asset_count}"
        )

    print(f"\nCapable cohorts with stock: {len(capable_with_stock)}")
    for cohort in capable_with_stock:
        print(f"  {cohort.object_id} stock={cohort.stock_asset_count}")


async def async_main(args: argparse.Namespace) -> int:
    """Run the advisory example.

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

        print("DCS connected. Requesting COHORT snapshot ...")
        await request_required_snapshots(client)

        print_auftrag_spec(args.mission_type)
        print_capable_cohorts(client, args.mission_type)
        return 0

    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(description="Find COHORTs capable of a requested AUFTRAG mission type.")
    parser.add_argument("--mission-type", required=True, help="AUFTRAG mission type, for example BAI or Orbit.")
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
