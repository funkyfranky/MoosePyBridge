"""Preview, apply, and optionally monitor a recommended AUFTRAG mission.

This generic example supports mission types backed by the advisory specs and Lua
execution extension, currently including BAI and BOMBING.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

from moosebridge import (
    MooseBridgeAuftragNotFoundError,
    MooseBridgeAuftragTimeoutError,
    MooseBridgeClient,
    MooseBridgeServer,
    evaluate_auftrag_request,
    recommend_auftrag,
)
from moosebridge.server import DEFAULT_PORT


def build_params(args: argparse.Namespace) -> dict[str, Any]:
    """Build AUFTRAG advisory parameters from command-line arguments.

    :param args: Parsed command-line arguments.
    :returns: Advisory parameter dictionary.
    """

    params: dict[str, Any] = {"target": args.target}
    if args.altitude_ft is not None:
        params["altitude_ft"] = args.altitude_ft
    if args.engage_weapon_type is not None:
        params["engage_weapon_type"] = args.engage_weapon_type
    if args.divebomb:
        params["divebomb"] = True
    return params


def print_mapping(title: str, values: dict[str, Any]) -> None:
    """Print a title and key/value mapping.

    :param title: Section title.
    :param values: Mapping to print.
    """

    print(f"\n{title}:")
    for key, value in values.items():
        print(f"  {key}: {value}")


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
    raise TimeoutError(f"No DCS bridge connection after {timeout_s:.1f} s.")


async def async_main(args: argparse.Namespace) -> int:
    """Run the approval-gated recommended AUFTRAG application example.

    :param args: Parsed command-line arguments.
    :returns: Process exit code.
    """

    mission_type = args.mission_type.strip().upper()
    log_path = Path(args.log) if args.log else None
    server = MooseBridgeServer(host=args.host, port=args.port, log_path=log_path)
    client = MooseBridgeClient(server)

    await server.start()
    try:
        print(f"Waiting for DCS bridge connection on {args.host}:{args.port} ...")
        await wait_for_dcs_connection(server, args.connect_timeout)

        print("DCS connected. Requesting advisory snapshots ...")
        await client.request_snapshots(
            ("snapshot.groups", "snapshot.units", "snapshot.statics", "snapshot.zones", "snapshot.cohorts", "snapshot.legions")
        )

        result = evaluate_auftrag_request(
            state=client.state,
            mission_type=mission_type,
            params=build_params(args),
            coalition=args.coalition,
        )
        recommendation = recommend_auftrag(result)
        if recommendation is None:
            print(f"No executable {mission_type} recommendation was found.")
            for issue in result.issues:
                print(f"  {issue.severity}: {issue.code}: {issue.message}")
            return 2

        print_mapping("Recommendation", recommendation.to_dict())

        if not args.apply:
            print("\nPreview only. Re-run with --apply to create and assign the AUFTRAG in DCS.")
            return 0

        print("\nApplying recommendation via SDK ...")
        ack = await client.apply_recommended_auftrag(recommendation, timeout=args.command_timeout)
        print("ACK:", ack)

        result_payload = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        auftrag_id = result_payload.get("auftrag_id")
        if not args.monitor:
            return 0

        if not auftrag_id:
            print("Cannot monitor AUFTRAG because ACK result did not include auftrag_id.")
            return 4

        print(f"\nWaiting for evaluated AUFTRAG outcome: {auftrag_id}")
        try:
            outcome = await client.wait_for_auftrag_outcome(
                str(auftrag_id),
                timeout_s=args.monitor_timeout,
                interval_s=args.monitor_interval,
            )
        except MooseBridgeAuftragNotFoundError as exc:
            print(f"AUFTRAG not found: {exc}")
            return 4
        except MooseBridgeAuftragTimeoutError as exc:
            print(f"AUFTRAG outcome timeout: {exc}")
            return 5

        print_mapping("Outcome", outcome.to_dict())
        print(f"\n{outcome.auftrag_id} evaluation complete: {'SUCCESS' if outcome.success else 'FAILURE'}")
        return 0 if outcome.success else 6

    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(description="Preview and optionally apply a recommended AUFTRAG.")
    parser.add_argument("--mission-type", required=True, help="Mission type, for example BAI or BOMBING.")
    parser.add_argument("--target", required=True, help="Target object id, for example GROUP:Ground-1.")
    parser.add_argument("--coalition", default="blue", help="Executing coalition filter, for example blue or red.")
    parser.add_argument("--altitude-ft", type=float, default=None, help="Optional engage altitude in feet.")
    parser.add_argument("--engage-weapon-type", type=int, default=None, help="Optional numeric ENUMS.WeaponFlag value.")
    parser.add_argument("--divebomb", action="store_true", help="Use dive bombing for BOMBING missions.")
    parser.add_argument("--apply", action="store_true", help="Create and assign the recommended AUFTRAG in DCS.")
    parser.add_argument("--monitor", action="store_true", help="Wait for the evaluated AUFTRAG outcome after applying.")
    parser.add_argument("--monitor-timeout", type=float, default=600.0, help="Maximum AUFTRAG monitoring time in seconds.")
    parser.add_argument("--monitor-interval", type=float, default=5.0, help="AUFTRAG monitoring poll interval in seconds.")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface for the Python bridge server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port for the Python bridge server.")
    parser.add_argument("--connect-timeout", type=float, default=60.0, help="Seconds to wait for DCS to connect.")
    parser.add_argument("--command-timeout", type=float, default=10.0, help="Seconds to wait for DCS command ACK.")
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
