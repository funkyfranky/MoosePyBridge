"""Validate an AUFTRAG request without executing it in DCS.

This example performs advisory-only validation:
    - AUFTRAG type specification lookup
    - required parameter validation
    - target object lookup and type compatibility
    - combat friendly-fire check
    - executing coalition filter
    - LEGION-to-target distance ranking
    - COHORT mission performance reporting

Example:
    PYTHONPATH=python python examples/advisory/validate_auftrag_request.py --mission-type BAI --target GROUP:Enemy-1 --coalition blue --altitude-ft 15000 --host 127.0.0.1 --port 51000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

from moosebridge import BridgeCommand, MooseBridgeClient, MooseBridgeServer, evaluate_auftrag_request
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
    """Request snapshots needed for AUFTRAG advisory validation.

    :param client: MOOSE Bridge SDK client.
    """

    for action in ("snapshot.groups", "snapshot.units", "snapshot.statics", "snapshot.zones", "snapshot.cohorts", "snapshot.legions"):
        await client.server.send_command(BridgeCommand(action=action, params={}))
        await asyncio.sleep(0.05)


def print_result(result: Any) -> None:
    """Print an AUFTRAG advisory result.

    :param result: Advisory result returned by ``evaluate_auftrag_request``.
    """

    print("\nRequest:")
    print(f"  mission_type: {result.mission_type}")
    print(f"  coalition: {result.coalition or 'any'}")
    for key, value in result.params.items():
        print(f"  {key}: {value}")

    print("\nValidation:")
    print(f"  AUFTRAG type known: {'yes' if result.spec else 'no'}")
    print(f"  target: {result.target_id or 'none'}")
    print(f"  target_type: {result.target_type or 'unknown'}")
    print(f"  target_coalition: {result.target_coalition or 'unknown/none'}")
    print(f"  ok: {'yes' if result.ok else 'no'}")

    if result.issues:
        print("\nIssues:")
        for issue in result.issues:
            print(f"  [{issue.severity}] {issue.code}: {issue.message}")

    print(f"\nCandidates: {len(result.candidates)}")
    for candidate in result.candidates:
        legion_id = candidate.legion.object_id if candidate.legion else "none"
        distance = f"{candidate.distance_nm:.1f} NM" if candidate.distance_nm is not None else "unknown"
        performance = candidate.cohort.mission_performance_for(result.mission_type)
        performance_text = f"{performance:.1f}" if performance is not None else "unknown"
        print(
            f"  {legion_id} / {candidate.cohort.object_id} "
            f"stock={candidate.cohort.stock_asset_count} "
            f"performance={performance_text} "
            f"distance={distance}"
        )


async def async_main(args: argparse.Namespace) -> int:
    """Run the AUFTRAG advisory validation example.

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

        print("DCS connected. Requesting advisory snapshots ...")
        await request_required_snapshots(client)

        params: dict[str, Any] = {}
        if args.target:
            params["target"] = args.target
        if args.altitude_ft is not None:
            params["altitude_ft"] = args.altitude_ft

        result = evaluate_auftrag_request(
            state=client.state,
            mission_type=args.mission_type,
            params=params,
            coalition=args.coalition,
        )
        print_result(result)
        return 0 if result.ok else 2

    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(description="Validate an AUFTRAG request without executing it in DCS.")
    parser.add_argument("--mission-type", required=True, help="AUFTRAG mission type, for example BAI.")
    parser.add_argument("--target", default=None, help="Target object id, for example GROUP:Enemy-1.")
    parser.add_argument("--coalition", default=None, help="Executing coalition filter, for example blue or red.")
    parser.add_argument("--altitude-ft", type=float, default=None, help="Optional engage altitude in feet for supported AUFTRAG types.")
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
