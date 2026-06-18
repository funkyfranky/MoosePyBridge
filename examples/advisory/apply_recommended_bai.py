"""Preview, apply, and optionally monitor the recommended BAI AUFTRAG.

By default this script only prints the recommendation. It creates and assigns the
AUFTRAG in DCS only when ``--apply`` is provided. Add ``--monitor`` to poll
AUFTRAG snapshots after application.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

from moosebridge import BridgeCommand, MooseBridgeClient, MooseBridgeServer, evaluate_auftrag_request, recommend_auftrag
from moosebridge.server import DEFAULT_PORT


TERMINAL_STATUS_KEYS = {
    "done",
    "failed",
    "failure",
    "finished",
    "success",
    "successful",
    "cancelled",
    "canceled",
    "stopped",
    "over",
}


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


async def request_snapshots(client: MooseBridgeClient, actions: tuple[str, ...]) -> None:
    """Request a sequence of snapshots.

    :param client: MOOSE Bridge SDK client.
    :param actions: Snapshot command actions.
    """

    for action in actions:
        await client.server.send_command(BridgeCommand(action=action, params={}))
        await asyncio.sleep(0.05)


def build_params(args: argparse.Namespace) -> dict[str, Any]:
    """Build AUFTRAG advisory parameters from command-line arguments.

    :param args: Parsed command-line arguments.
    :returns: Advisory parameter dictionary.
    """

    params: dict[str, Any] = {"target": args.target}
    if args.altitude_ft is not None:
        params["altitude_ft"] = args.altitude_ft
    return params


def build_apply_command_params(recommendation: Any) -> dict[str, Any]:
    """Build flat command parameters for the Lua AUFTRAG command.

    :param recommendation: Structured AUFTRAG recommendation.
    :returns: Flat command parameter dictionary.
    """

    params = recommendation.to_dict()
    nested = params.get("params") if isinstance(params.get("params"), dict) else {}
    return {
        "legion_id": params.get("legion_id"),
        "cohort_id": params.get("cohort_id"),
        "target": nested.get("target"),
        "altitude_ft": nested.get("altitude_ft"),
        "selected_payload_uid": params.get("selected_payload_uid"),
        "mission_type": params.get("mission_type"),
        "constructor": params.get("constructor"),
    }


def is_terminal_auftrag_snapshot(snapshot: dict[str, Any]) -> bool:
    """Return whether an AUFTRAG snapshot looks terminal.

    :param snapshot: Raw AUFTRAG snapshot dictionary.
    :returns: ``True`` if the AUFTRAG appears to have reached a terminal state.
    """

    status = str(snapshot.get("status") or "").strip().lower()
    if status in TERMINAL_STATUS_KEYS:
        return True
    return snapshot.get("t_over") is not None


def print_auftrag_snapshot(snapshot: dict[str, Any], prefix: str = "  ") -> None:
    """Print the most relevant AUFTRAG status fields.

    :param snapshot: Raw AUFTRAG snapshot dictionary.
    :param prefix: Prefix printed before each line.
    """

    fields = (
        "object_id",
        "type",
        "status",
        "n_assigned",
        "n_elements",
        "n_dead",
        "n_kills",
        "n_casualties",
        "t_started",
        "t_executing",
        "t_over",
        "assigned_group_ids",
        "legion_names",
    )
    for field in fields:
        print(f"{prefix}{field}: {snapshot.get(field)}")


async def monitor_auftrag(client: MooseBridgeClient, auftrag_id: str, timeout_s: float, interval_s: float) -> int:
    """Poll AUFTRAG snapshots until the AUFTRAG becomes terminal or times out.

    :param client: MOOSE Bridge SDK client.
    :param auftrag_id: Stable AUFTRAG object id from the ACK result.
    :param timeout_s: Maximum monitoring time in seconds.
    :param interval_s: Poll interval in seconds.
    :returns: Exit code contribution: ``0`` if terminal or visible at timeout, ``4`` if never seen.
    """

    print(f"\nMonitoring {auftrag_id} for up to {timeout_s:.1f} s ...")
    deadline = asyncio.get_running_loop().time() + timeout_s
    last_snapshot: dict[str, Any] | None = None
    seen = False

    while asyncio.get_running_loop().time() < deadline:
        await request_snapshots(client, ("snapshot.auftraege", "snapshot.legions", "snapshot.opsgroups"))
        snapshot = client.state.auftraege.get(auftrag_id)

        if snapshot is None:
            print(f"  {auftrag_id}: not visible in snapshot yet")
        else:
            seen = True
            if snapshot != last_snapshot:
                print("\nAUFTRAG snapshot:")
                print_auftrag_snapshot(snapshot)
                last_snapshot = dict(snapshot)
            if is_terminal_auftrag_snapshot(snapshot):
                print(f"\n{auftrag_id} appears terminal.")
                return 0

        await asyncio.sleep(interval_s)

    if not seen:
        print(f"\n{auftrag_id} was not visible before monitor timeout.")
        return 4

    print(f"\nMonitor timeout reached. Last known {auftrag_id} snapshot:")
    if last_snapshot is not None:
        print_auftrag_snapshot(last_snapshot)
    return 0


async def async_main(args: argparse.Namespace) -> int:
    """Run the approval-gated recommended BAI application example.

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
        await request_snapshots(
            client,
            ("snapshot.groups", "snapshot.units", "snapshot.statics", "snapshot.zones", "snapshot.cohorts", "snapshot.legions"),
        )

        result = evaluate_auftrag_request(
            state=client.state,
            mission_type="BAI",
            params=build_params(args),
            coalition=args.coalition,
        )
        recommendation = recommend_auftrag(result)
        if recommendation is None:
            print("No executable BAI recommendation was found.")
            return 2

        print("\nRecommendation:")
        for key, value in recommendation.to_dict().items():
            print(f"  {key}: {value}")

        command_params = build_apply_command_params(recommendation)
        print("\nCommand params:")
        for key, value in command_params.items():
            print(f"  {key}: {value}")

        if not args.apply:
            print("\nPreview only. Re-run with --apply to create and assign the AUFTRAG in DCS.")
            return 0

        print("\nApplying recommendation via action=auftrag.create_bai ...")
        ack = await server.send_command(
            BridgeCommand(
                action="auftrag.create_bai",
                params=command_params,
            ),
            timeout=args.command_timeout,
        )
        print("ACK:", ack)
        if not ack.get("ok"):
            return 3

        print("\nRequesting post-application snapshots ...")
        await request_snapshots(client, ("snapshot.auftraege", "snapshot.legions", "snapshot.opsgroups"))

        result_payload = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        auftrag_id = result_payload.get("auftrag_id")
        if args.monitor:
            if auftrag_id:
                return await monitor_auftrag(client, str(auftrag_id), args.monitor_timeout, args.monitor_interval)
            print("Cannot monitor AUFTRAG because ACK result did not include auftrag_id.")
            return 4

        return 0

    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(description="Preview and optionally apply the recommended BAI AUFTRAG.")
    parser.add_argument("--target", required=True, help="Target object id, for example GROUP:Ground-1.")
    parser.add_argument("--coalition", default="blue", help="Executing coalition filter, for example blue or red.")
    parser.add_argument("--altitude-ft", type=float, default=None, help="Optional engage altitude in feet.")
    parser.add_argument("--apply", action="store_true", help="Create and assign the recommended AUFTRAG in DCS.")
    parser.add_argument("--monitor", action="store_true", help="Poll AUFTRAG snapshots after applying the recommendation.")
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
