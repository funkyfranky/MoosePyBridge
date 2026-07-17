"""Inspect MOOSE Bridge OPS state from a running DCS mission.

Run this script while DCS has loaded the MOOSE Bridge mission-side Lua files.
The script starts a local Python bridge server, waits for the DCS Lua bridge to
connect, requests selected snapshots, and prints compact diagnostic state.

Examples:
    python examples/inspect_ops_state.py --host 127.0.0.1 --port 42000
    python examples/inspect_ops_state.py --snapshots legions cohorts --filter Parchim
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from moosebridge import MooseBridgeClient, MooseBridgeServer
from moosebridge.sdk import SNAPSHOT_KINDS
from moosebridge.server import DEFAULT_PORT

METERS_PER_NAUTICAL_MILE = 1852.0
DEFAULT_SNAPSHOTS = ("legions", "cohorts", "opsgroups", "auftraege")
VALID_SNAPSHOTS = SNAPSHOT_KINDS - {"objects"}


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


async def request_snapshot(client: MooseBridgeClient, snapshot: str, timeout_s: float) -> None:
    """Request one snapshot by short name.

    :param client: MOOSE Bridge SDK client.
    :param snapshot: Snapshot short name, e.g. ``legions``.
    :param timeout_s: ACK wait timeout in seconds.
    :raises ValueError: If the snapshot name is unknown.
    """

    if snapshot not in VALID_SNAPSHOTS:
        raise ValueError(f"Unsupported snapshot {snapshot!r}; expected one of {sorted(VALID_SNAPSHOTS)}")
    await client.snapshot_kind(snapshot)
    await asyncio.sleep(0.05)


async def request_snapshots(client: MooseBridgeClient, snapshots: Iterable[str], timeout_s: float) -> None:
    """Request multiple snapshots.

    :param client: MOOSE Bridge SDK client.
    :param snapshots: Snapshot names.
    :param timeout_s: ACK wait timeout in seconds.
    """

    for snapshot in snapshots:
        await request_snapshot(client, snapshot, timeout_s)
    await asyncio.sleep(0.1)


def meters_to_nm(value: float | None) -> float | None:
    """Convert meters to nautical miles.

    :param value: Distance in meters.
    :returns: Distance in nautical miles or ``None``.
    """

    return value / METERS_PER_NAUTICAL_MILE if value is not None else None


def fmt_float(value: float | None, digits: int = 1) -> str:
    """Format an optional float.

    :param value: Optional numeric value.
    :param digits: Number of fractional digits.
    :returns: Formatted value or ``n/a``.
    """

    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def matches_filter(*values: Any, text_filter: str | None) -> bool:
    """Return whether any value contains the text filter.

    :param values: Values to inspect.
    :param text_filter: Case-insensitive filter text.
    :returns: ``True`` if the item should be printed.
    """

    if not text_filter:
        return True
    needle = text_filter.lower()
    return any(needle in str(value).lower() for value in values if value is not None)


def list_text(values: Iterable[str] | None) -> str:
    """Return a compact comma-separated list string.

    :param values: Iterable of strings.
    :returns: Comma-separated list or ``none``.
    """

    items = [str(value) for value in values or [] if value]
    return ",".join(items) if items else "none"


def print_legions(client: MooseBridgeClient, text_filter: str | None) -> None:
    """Print LEGION diagnostics.

    :param client: MOOSE Bridge SDK client.
    :param text_filter: Optional case-insensitive filter.
    """

    legions = list(client.state.legion_objects.values())
    print(f"\nLEGION objects: {len(legions)}")
    for legion in legions:
        queue_text = list_text(legion.auftrag_queue_ids)
        if not matches_filter(legion.object_id, legion.name, legion.airbase_name, queue_text, text_filter=text_filter):
            continue
        print(
            f"  {legion.object_id} "
            f"category={legion.category} "
            f"state={legion.state or 'n/a'} "
            f"coalition={legion.coalition} "
            f"airbase={legion.airbase_name} "
            f"cohorts={len(legion.cohort_ids)} "
            f"queue=[{queue_text}] "
            f"x={fmt_float(legion.x)} y={fmt_float(legion.y)} z={fmt_float(legion.z)}"
        )


def print_cohorts(client: MooseBridgeClient, text_filter: str | None) -> None:
    """Print COHORT diagnostics including mission range.

    :param client: MOOSE Bridge SDK client.
    :param text_filter: Optional case-insensitive filter.
    """

    cohorts = list(client.state.cohort_objects.values())
    print(f"\nCOHORT objects: {len(cohorts)}")
    for cohort in cohorts:
        opsgroup_text = list_text(cohort.opsgroup_ids)
        if not matches_filter(cohort.object_id, cohort.name, cohort.legion_id, cohort.unit_type, opsgroup_text, text_filter=text_filter):
            continue
        mission_range_nm = meters_to_nm(cohort.mission_range_m)
        mission_types = ",".join(cohort.mission_type_keys) or "none"
        print(
            f"  {cohort.object_id} "
            f"legion={cohort.legion_id} "
            f"category={cohort.category} "
            f"unit_type={cohort.unit_type} "
            f"stock={cohort.stock_asset_count} "
            f"spawned={cohort.spawned_asset_count} "
            f"opsgroups=[{opsgroup_text}] "
            f"mission_range_m={fmt_float(cohort.mission_range_m, 0)} "
            f"mission_range_nm={fmt_float(mission_range_nm)} "
            f"missions=[{mission_types}] "
            f"x={fmt_float(cohort.x)} y={fmt_float(cohort.y)} z={fmt_float(cohort.z)}"
        )


def print_opsgroups(client: MooseBridgeClient, text_filter: str | None) -> None:
    """Print OPSGROUP diagnostics.

    :param client: MOOSE Bridge SDK client.
    :param text_filter: Optional case-insensitive filter.
    """

    groups = list(client.state.opsgroup_objects.values())
    print(f"\nOPSGROUP objects: {len(groups)}")
    for group in groups:
        queue_text = list_text(group.auftrag_queue_ids)
        if not matches_filter(group.object_id, group.name, group.auftrag_current_id, queue_text, text_filter=text_filter):
            continue
        print(
            f"  {group.object_id} "
            f"category={group.category} "
            f"coalition={group.coalition} "
            f"state={group.state} "
            f"alive={group.alive} "
            f"active={group.active} "
            f"auftrag_current={group.auftrag_current_id or 'none'} "
            f"queue=[{queue_text}] "
            f"x={fmt_float(group.x)} y={fmt_float(group.y)} z={fmt_float(group.z)}"
        )


def print_auftraege(client: MooseBridgeClient, text_filter: str | None) -> None:
    """Print AUFTRAG diagnostics.

    :param client: MOOSE Bridge SDK client.
    :param text_filter: Optional case-insensitive filter.
    """

    auftraege = list(client.state.auftrag_objects.values())
    print(f"\nAUFTRAG objects: {len(auftraege)}")
    for auftrag in auftraege:
        assigned = ",".join(auftrag.assigned_group_ids) or "none"
        if not matches_filter(auftrag.object_id, auftrag.name, auftrag.type, auftrag.status, assigned, text_filter=text_filter):
            continue
        print(
            f"  {auftrag.object_id} "
            f"type={auftrag.type} "
            f"status={auftrag.status} "
            f"summary_available={bool(auftrag.raw.get('summary'))} "
            f"assigned=[{assigned}]"
        )


def print_airbases(client: MooseBridgeClient, text_filter: str | None) -> None:
    """Print AIRBASE diagnostics.

    :param client: MOOSE Bridge SDK client.
    :param text_filter: Optional case-insensitive filter.
    """

    airbases = list(client.state.airbases.values())
    print(f"\nAIRBASE objects: {len(airbases)}")
    for airbase in airbases:
        if not matches_filter(airbase.get("object_id"), airbase.get("dcs_name"), airbase.get("display_name"), text_filter=text_filter):
            continue
        print(
            f"  {airbase.get('object_id')} "
            f"coalition={airbase.get('coalition')} "
            f"category={airbase.get('category')} "
            f"display={airbase.get('display_name')} "
            f"x={airbase.get('x')} y={airbase.get('y')} z={airbase.get('z')}"
        )


def print_selected_state(client: MooseBridgeClient, snapshots: Iterable[str], text_filter: str | None) -> None:
    """Print diagnostics for selected snapshots.

    :param client: MOOSE Bridge SDK client.
    :param snapshots: Requested snapshot names.
    :param text_filter: Optional case-insensitive filter.
    """

    selected = set(snapshots)
    if "legions" in selected:
        print_legions(client, text_filter)
    if "cohorts" in selected:
        print_cohorts(client, text_filter)
    if "opsgroups" in selected:
        print_opsgroups(client, text_filter)
    if "auftraege" in selected:
        print_auftraege(client, text_filter)
    if "airbases" in selected:
        print_airbases(client, text_filter)


async def async_main(args: argparse.Namespace) -> int:
    """Run the OPS state inspection example.

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

        print(f"DCS connected. Requesting snapshots: {', '.join(args.snapshots)} ...")
        await request_snapshots(client, args.snapshots, args.command_timeout)
        print_selected_state(client, args.snapshots, args.filter)
        return 0

    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(description="Inspect MOOSE Bridge OPS state.")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface for the Python bridge server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port for the Python bridge server.")
    parser.add_argument("--connect-timeout", type=float, default=60.0, help="Seconds to wait for DCS to connect.")
    parser.add_argument("--command-timeout", type=float, default=10.0, help="Seconds to wait for each DCS ACK.")
    parser.add_argument("--snapshots", nargs="+", default=list(DEFAULT_SNAPSHOTS), help="Snapshots to request.")
    parser.add_argument("--filter", default=None, help="Optional case-insensitive text filter for printed rows.")
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
