"""Request a compact AUFTRAG trace from a running DCS mission.

The script starts a local Python bridge server, waits for the DCS Lua bridge to
connect, calls the read-only ``auftrag.trace`` command, and prints the returned
trace in a compact form.

Examples:
    python examples/trace_auftrag.py AUFTRAG:1 --host 127.0.0.1 --port 51000
    python examples/trace_auftrag.py AUFTRAG:1 --raw
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from moosebridge import MooseBridgeServer
from moosebridge.protocol import BridgeCommand
from moosebridge.sdk import require_ok
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
    raise TimeoutError(f"No DCS bridge connection after {timeout_s:.1f} s.")


def print_list(title: str, items: list[Any], limit: int | None = None) -> None:
    """Print a list with optional truncation.

    :param title: Section title.
    :param items: Items to print.
    :param limit: Optional maximum number of rows.
    """

    print(f"\n{title}: {len(items)}")
    shown = items if limit is None else items[:limit]
    for item in shown:
        print(f"  {item}")
    if limit is not None and len(items) > limit:
        print(f"  ... {len(items) - limit} more")


def print_trace(trace: dict[str, Any]) -> None:
    """Print a compact trace response.

    :param trace: ``auftrag.trace`` ACK result payload.
    """

    print(f"\nAUFTRAG trace: {trace.get('auftrag_id')}")
    print(f"  found: {trace.get('found')}")
    print(f"  source: {trace.get('source')}")
    print(f"  counts: {trace.get('counts')}")

    auftrag = trace.get("auftrag") if isinstance(trace.get("auftrag"), dict) else {}
    if auftrag:
        print("\nAUFTRAG:")
        print(f"  type={auftrag.get('type')} status={auftrag.get('status')} summary_available={auftrag.get('summary_available')}")
        print(f"  assigned={auftrag.get('assigned_group_ids')}")
        print(f"  target={auftrag.get('target')}")

    print_list("Matching LEGION ids", trace.get("matching_legion_ids") or [])
    print_list("Matching OPSGROUP ids", trace.get("matching_opsgroup_ids") or [])

    legions = trace.get("legions") if isinstance(trace.get("legions"), list) else []
    print("\nLEGIONs:")
    for legion in legions:
        if not isinstance(legion, dict):
            continue
        marker = "*" if legion.get("missionqueue_contains_auftrag") else " "
        print(
            f" {marker} {legion.get('object_id')} "
            f"state={legion.get('state')} "
            f"running={legion.get('is_running')} "
            f"queue={legion.get('auftrag_queue_ids')}"
        )

    cohorts = trace.get("cohorts") if isinstance(trace.get("cohorts"), list) else []
    print("\nCOHORTs:")
    for cohort in cohorts:
        if not isinstance(cohort, dict):
            continue
        print(
            f"   {cohort.get('object_id')} "
            f"legion={cohort.get('legion_id')} "
            f"stock={cohort.get('stock_asset_count')} "
            f"spawned={cohort.get('spawned_asset_count')} "
            f"opsgroups={cohort.get('opsgroup_ids')}"
        )

    opsgroups = trace.get("opsgroups") if isinstance(trace.get("opsgroups"), list) else []
    print("\nOPSGROUPs:")
    for opsgroup in opsgroups:
        if not isinstance(opsgroup, dict):
            continue
        marker = "*" if opsgroup.get("current_contains_auftrag") or opsgroup.get("queue_contains_auftrag") else " "
        print(
            f" {marker} {opsgroup.get('object_id')} "
            f"state={opsgroup.get('state')} "
            f"alive={opsgroup.get('alive')} "
            f"active={opsgroup.get('active')} "
            f"current={opsgroup.get('auftrag_current_id')} "
            f"queue={opsgroup.get('auftrag_queue_ids')}"
        )


async def async_main(args: argparse.Namespace) -> int:
    """Run the trace command.

    :param args: Parsed command-line arguments.
    :returns: Process exit code.
    """

    log_path = Path(args.log) if args.log else None
    server = MooseBridgeServer(host=args.host, port=args.port, log_path=log_path)
    await server.start()
    try:
        print(f"Waiting for DCS bridge connection on {args.host}:{args.port} ...")
        await wait_for_dcs_connection(server, args.connect_timeout)
        ack = await server.send_command(
            BridgeCommand(action="auftrag.trace", params={"object_id": args.auftrag_id}),
            timeout=args.command_timeout,
        )
        require_ok(ack)
        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        if args.raw:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print_trace(result)
        return 0
    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed arguments.
    """

    parser = argparse.ArgumentParser(description="Trace one AUFTRAG in the running MOOSE Bridge mission state.")
    parser.add_argument("auftrag_id", help="Stable AUFTRAG id, for example AUFTRAG:1.")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface for the Python bridge server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port for the Python bridge server.")
    parser.add_argument("--connect-timeout", type=float, default=60.0, help="Seconds to wait for DCS to connect.")
    parser.add_argument("--command-timeout", type=float, default=10.0, help="Seconds to wait for DCS command ACK.")
    parser.add_argument("--raw", action="store_true", help="Print the raw trace JSON instead of compact text.")
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
