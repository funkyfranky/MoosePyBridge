"""Preview, apply, trace, and optionally monitor a recommended AUFTRAG mission.

This generic example supports mission types backed by the advisory specs and Lua
execution extension, currently including BAI, BOMBING and ARTY.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable

from moosebridge import (
    MooseBridgeAuftragNotFoundError,
    MooseBridgeAuftragTimeoutError,
    MooseBridgeClient,
    MooseBridgeServer,
    canonical_mission_type,
    evaluate_auftrag_request,
    recommend_auftrag,
)
from moosebridge.outcomes import AuftragOutcome
from moosebridge.protocol import BridgeCommand
from moosebridge.sdk import build_recommended_auftrag_command_params, is_evaluated_auftrag_snapshot, require_ok
from moosebridge.server import DEFAULT_PORT


def build_params(args: argparse.Namespace) -> dict[str, Any]:
    """Build AUFTRAG advisory parameters from command-line arguments.

    :param args: Parsed command-line arguments.
    :returns: Advisory parameter dictionary.
    """

    params: dict[str, Any] = {}
    if args.target is not None:
        params["target"] = args.target
    if args.x is not None:
        params["x"] = args.x
    if args.y is not None:
        params["y"] = args.y
    if args.z is not None:
        params["z"] = args.z
    if args.altitude_ft is not None:
        params["altitude_ft"] = args.altitude_ft
    if args.engage_weapon_type is not None:
        params["engage_weapon_type"] = args.engage_weapon_type
    if args.divebomb:
        params["divebomb"] = True
    if args.nshots is not None:
        params["nshots"] = args.nshots
    if args.radius_m is not None:
        params["radius_m"] = args.radius_m
    return params


def print_mapping(title: str, values: dict[str, Any]) -> None:
    """Print a title and key/value mapping.

    :param title: Section title.
    :param values: Mapping to print.
    """

    print(f"\n{title}:")
    for key, value in values.items():
        print(f"  {key}: {value}")


def matching_items(items: Any, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    """Return dictionary items matching a predicate.

    :param items: Candidate item list.
    :param predicate: Match predicate.
    :returns: Matching dictionaries.
    """

    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and predicate(item)]


def object_ids(items: list[dict[str, Any]]) -> list[str]:
    """Return object ids from trace items.

    :param items: Trace item dictionaries.
    :returns: Non-empty object ids.
    """

    return [str(item.get("object_id")) for item in items if item.get("object_id")]


def print_compact_trace(title: str, trace: dict[str, Any]) -> None:
    """Print a compact one-block AUFTRAG trace.

    :param title: Section title.
    :param trace: Raw ``auftrag.trace`` result payload.
    """

    auftrag = trace.get("auftrag") if isinstance(trace.get("auftrag"), dict) else {}
    counts = trace.get("counts") if isinstance(trace.get("counts"), dict) else {}
    assigned = auftrag.get("assigned_group_ids") if isinstance(auftrag.get("assigned_group_ids"), list) else []
    target = auftrag.get("target") if isinstance(auftrag.get("target"), dict) else {}

    legions = matching_items(trace.get("legions"), lambda item: bool(item.get("missionqueue_contains_auftrag")))
    opsgroups = matching_items(
        trace.get("opsgroups"),
        lambda item: bool(item.get("current_contains_auftrag")) or bool(item.get("queue_contains_auftrag")),
    )
    active_cohorts = matching_items(
        trace.get("cohorts"),
        lambda item: bool(item.get("spawned_asset_count")) or bool(item.get("opsgroup_ids")),
    )

    print(
        f"\n{title}: {trace.get('auftrag_id')} "
        f"found={trace.get('found')} source={trace.get('source')} "
        f"type={auftrag.get('type')} status={auftrag.get('status')} "
        f"summary={auftrag.get('summary_available')} "
        f"assigned={len(assigned)} "
        f"matching_legions={counts.get('matching_legions')} "
        f"matching_opsgroups={counts.get('matching_opsgroups')}"
    )

    if target:
        print(
            f"  target={target.get('category')}:{target.get('name')} "
            f"x={target.get('x')} z={target.get('z')} damage={target.get('damage')} destroyed={target.get('n_destroyed')}"
        )
    if legions:
        print("  legions=" + ", ".join(f"{item.get('object_id')}[{item.get('state')}]" for item in legions))
    if active_cohorts:
        print(
            "  cohorts="
            + ", ".join(
                f"{item.get('object_id')}[stock={item.get('stock_asset_count')} spawned={item.get('spawned_asset_count')} opsgroups={len(item.get('opsgroup_ids') or [])}]"
                for item in active_cohorts
            )
        )
    if opsgroups:
        print(
            "  opsgroups="
            + ", ".join(
                f"{item.get('object_id')}[{item.get('state')} current={item.get('auftrag_current_id')} queue={len(item.get('auftrag_queue_ids') or [])}]"
                for item in opsgroups
            )
        )
    if assigned:
        print("  assigned=" + ", ".join(str(value) for value in assigned))


def print_verbose_trace(title: str, trace: dict[str, Any]) -> None:
    """Print the verbose human-readable AUFTRAG trace.

    :param title: Section title.
    :param trace: Raw ``auftrag.trace`` result payload.
    """

    print(f"\n{title}:")
    print(f"  auftrag_id: {trace.get('auftrag_id')}")
    print(f"  found: {trace.get('found')}")
    print(f"  source: {trace.get('source')}")
    print(f"  counts: {trace.get('counts')}")

    auftrag = trace.get("auftrag") if isinstance(trace.get("auftrag"), dict) else {}
    if auftrag:
        print("  AUFTRAG:")
        print(f"    type: {auftrag.get('type')}")
        print(f"    status: {auftrag.get('status')}")
        print(f"    summary_available: {auftrag.get('summary_available')}")
        print(f"    assigned_group_ids: {auftrag.get('assigned_group_ids')}")
        print(f"    target: {auftrag.get('target')}")

    print(f"  matching_legion_ids: {trace.get('matching_legion_ids') or []}")
    print(f"  matching_opsgroup_ids: {trace.get('matching_opsgroup_ids') or []}")

    legions = trace.get("legions") if isinstance(trace.get("legions"), list) else []
    if legions:
        print("  LEGIONs:")
        for legion in legions:
            if not isinstance(legion, dict):
                continue
            marker = "*" if legion.get("missionqueue_contains_auftrag") else " "
            print(
                f"   {marker} {legion.get('object_id')} "
                f"state={legion.get('state')} running={legion.get('is_running')} "
                f"queue={legion.get('auftrag_queue_ids')}"
            )

    cohorts = trace.get("cohorts") if isinstance(trace.get("cohorts"), list) else []
    if cohorts:
        print("  COHORTs:")
        for cohort in cohorts:
            if not isinstance(cohort, dict):
                continue
            print(
                f"     {cohort.get('object_id')} "
                f"legion={cohort.get('legion_id')} "
                f"stock={cohort.get('stock_asset_count')} "
                f"spawned={cohort.get('spawned_asset_count')} "
                f"opsgroups={cohort.get('opsgroup_ids')}"
            )

    opsgroups = trace.get("opsgroups") if isinstance(trace.get("opsgroups"), list) else []
    if opsgroups:
        print("  OPSGROUPs:")
        for opsgroup in opsgroups:
            if not isinstance(opsgroup, dict):
                continue
            marker = "*" if opsgroup.get("current_contains_auftrag") or opsgroup.get("queue_contains_auftrag") else " "
            print(
                f"   {marker} {opsgroup.get('object_id')} "
                f"state={opsgroup.get('state')} alive={opsgroup.get('alive')} active={opsgroup.get('active')} "
                f"current={opsgroup.get('auftrag_current_id')} queue={opsgroup.get('auftrag_queue_ids')}"
            )


def print_trace_result(title: str, trace: dict[str, Any], raw: bool = False, verbose: bool = False) -> None:
    """Print an AUFTRAG trace result.

    :param title: Section title.
    :param trace: Raw ``auftrag.trace`` result payload.
    :param raw: If true, print full JSON.
    :param verbose: If true, print detailed text output.
    """

    if raw:
        print(f"\n{title}:")
        print(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if verbose:
        print_verbose_trace(title, trace)
        return
    print_compact_trace(title, trace)


async def trace_auftrag(
    client: MooseBridgeClient,
    auftrag_id: str,
    raw: bool,
    verbose: bool,
    title: str = "Trace",
    command_timeout: float = 10.0,
) -> dict[str, Any]:
    """Request, print, and return an AUFTRAG trace through the active bridge server.

    :param client: High-level client bound to the active local server.
    :param auftrag_id: Stable AUFTRAG id.
    :param raw: If true, print full JSON.
    :param verbose: If true, print detailed text output.
    :param title: Printed section title.
    :param command_timeout: Maximum ACK wait time in seconds.
    :returns: Raw trace result payload.
    """

    ack = require_ok(
        await client.server.send_command(
            BridgeCommand(action="auftrag.trace", params={"object_id": auftrag_id}),
            timeout=command_timeout,
        )
    )
    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    print_trace_result(title, result, raw=raw, verbose=verbose)
    return result


async def wait_for_auftrag_outcome_with_trace(
    client: MooseBridgeClient,
    auftrag_id: str,
    timeout_s: float,
    interval_s: float,
    trace_raw: bool,
    trace_verbose: bool,
    command_timeout: float,
) -> AuftragOutcome:
    """Wait for an AUFTRAG outcome while printing periodic traces.

    :param client: High-level client bound to the active local server.
    :param auftrag_id: Stable AUFTRAG object id.
    :param timeout_s: Maximum monitoring time in seconds.
    :param interval_s: Poll interval in seconds.
    :param trace_raw: If true, print raw trace JSON.
    :param trace_verbose: If true, print detailed text trace output.
    :param command_timeout: Maximum trace command ACK wait time in seconds.
    :returns: Stable AUFTRAG outcome model.
    :raises MooseBridgeAuftragNotFoundError: If the AUFTRAG is never observed.
    :raises MooseBridgeAuftragTimeoutError: If no summary appears before timeout.
    """

    deadline = asyncio.get_running_loop().time() + timeout_s
    seen = False
    last_snapshot: dict[str, Any] | None = None
    poll_index = 0

    while asyncio.get_running_loop().time() < deadline:
        await client.request_snapshots(("snapshot.auftraege", "snapshot.legions", "snapshot.opsgroups"))
        snapshot = client.state.auftraege.get(auftrag_id)
        if snapshot is not None:
            seen = True
            last_snapshot = snapshot

        await trace_auftrag(
            client,
            auftrag_id,
            raw=trace_raw,
            verbose=trace_verbose,
            title=f"Trace poll {poll_index}",
            command_timeout=command_timeout,
        )

        if snapshot is not None and is_evaluated_auftrag_snapshot(snapshot):
            return AuftragOutcome.from_snapshot(snapshot)

        poll_index += 1
        await asyncio.sleep(interval_s)

    if not seen:
        raise MooseBridgeAuftragNotFoundError(f"{auftrag_id} was not visible before monitor timeout")
    raise MooseBridgeAuftragTimeoutError(f"{auftrag_id} was not evaluated before timeout; last_snapshot={last_snapshot!r}")


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

    mission_type = canonical_mission_type(args.mission_type)
    log_path = Path(args.log) if args.log else None
    server = MooseBridgeServer(host=args.host, port=args.port, log_path=log_path)
    client = MooseBridgeClient(server)

    await server.start()
    try:
        print(f"Waiting for DCS bridge connection on {args.host}:{args.port} ...")
        await wait_for_dcs_connection(server, args.connect_timeout)

        print("DCS connected. Requesting advisory snapshots ...")
        await client.request_snapshots(
            (
                "snapshot.groups",
                "snapshot.units",
                "snapshot.statics",
                "snapshot.airbases",
                "snapshot.zones",
                "snapshot.opszones",
                "snapshot.cohorts",
                "snapshot.legions",
            )
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

        command_params = build_recommended_auftrag_command_params(recommendation)
        print_mapping("Command parameters", command_params)

        print("\nApplying recommendation via SDK ...")
        ack = await client.apply_auftrag(mission_type, command_params, timeout=args.command_timeout)
        print("ACK:", ack)

        result_payload = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        auftrag_id = result_payload.get("auftrag_id")
        if not auftrag_id:
            if args.monitor or args.trace:
                print("Cannot monitor or trace AUFTRAG because ACK result did not include auftrag_id.")
                return 4
            return 0

        auftrag_id = str(auftrag_id)
        if args.trace and not args.monitor:
            await trace_auftrag(
                client,
                auftrag_id,
                raw=args.trace_raw,
                verbose=args.trace_verbose,
                title="Trace after apply",
                command_timeout=args.command_timeout,
            )
            return 0

        if not args.monitor:
            return 0

        print(f"\nWaiting for evaluated AUFTRAG outcome: {auftrag_id}")
        try:
            if args.trace:
                outcome = await wait_for_auftrag_outcome_with_trace(
                    client,
                    auftrag_id,
                    timeout_s=args.monitor_timeout,
                    interval_s=args.monitor_interval,
                    trace_raw=args.trace_raw,
                    trace_verbose=args.trace_verbose,
                    command_timeout=args.command_timeout,
                )
            else:
                outcome = await client.wait_for_auftrag_outcome(
                    auftrag_id,
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
    parser.add_argument("--mission-type", required=True, help="Mission type, for example BAI, BOMBING or ARTY.")
    parser.add_argument("--target", default=None, help="Optional target object id, for example GROUP:Ground-1, AIRBASE:Parchim, ZONE:Target, or OPSZONE:Alpha.")
    parser.add_argument("--x", type=float, default=None, help="Optional DCS world x coordinate in meters, used by coordinate-based missions.")
    parser.add_argument("--y", type=float, default=None, help="Optional DCS world y coordinate in meters. Defaults to 0 in Lua when omitted.")
    parser.add_argument("--z", type=float, default=None, help="Optional DCS world z coordinate in meters, used by coordinate-based missions.")
    parser.add_argument("--coalition", default="blue", help="Executing coalition filter, for example blue or red.")
    parser.add_argument("--altitude-ft", type=float, default=None, help="Optional engage altitude in feet for air missions.")
    parser.add_argument("--engage-weapon-type", type=int, default=None, help="Optional numeric ENUMS.WeaponFlag value for BOMBING.")
    parser.add_argument("--divebomb", action="store_true", help="Use dive bombing for BOMBING missions.")
    parser.add_argument("--nshots", type=float, default=None, help="Optional ARTY shot count. Values in (0, 1) are treated by MOOSE as ammo fraction.")
    parser.add_argument("--radius-m", type=float, default=None, help="Optional ARTY impact radius in meters. MOOSE defaults to 100 m when omitted.")
    parser.add_argument("--apply", action="store_true", help="Create and assign the recommended AUFTRAG in DCS.")
    parser.add_argument("--trace", action="store_true", help="Print compact AUFTRAG assignment/execution trace after applying and during monitoring.")
    parser.add_argument("--trace-verbose", action="store_true", help="Print detailed text AUFTRAG trace output.")
    parser.add_argument("--trace-raw", action="store_true", help="Print full raw AUFTRAG trace JSON instead of text output.")
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
