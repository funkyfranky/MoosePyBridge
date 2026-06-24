"""Minimal recommended AUFTRAG apply example using the daemon control API."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from moosebridge import canonical_mission_type, evaluate_auftrag_request, recommend_auftrag
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.outcomes import AuftragOutcome
from moosebridge.sdk import auftrag_action_for_mission_type, build_recommended_auftrag_command_params, is_evaluated_auftrag_snapshot

SNAPSHOTS = ("snapshot.groups", "snapshot.units", "snapshot.statics", "snapshot.airbases", "snapshot.zones", "snapshot.opszones", "snapshot.cohorts", "snapshot.legions")


def parse_json_object(text: str | None) -> dict[str, Any]:
    """Parse an optional JSON object.

    :param text: JSON object text.
    :returns: Parsed dictionary.
    """

    if not text:
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


async def print_trace(client: MooseBridgeControlClient, auftrag_id: str, timeout: float) -> None:
    """Print one compact trace line.

    :param client: Control client.
    :param auftrag_id: Stable AUFTRAG id.
    :param timeout: Command timeout.
    """

    ack = await client.send_dcs_command("auftrag.trace", {"object_id": auftrag_id}, timeout=timeout)
    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    auftrag = result.get("auftrag") if isinstance(result.get("auftrag"), dict) else {}
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    print(
        f"trace {auftrag_id}: status={auftrag.get('status')} summary={auftrag.get('summary_available')} "
        f"assigned={len(auftrag.get('assigned_group_ids') or [])} "
        f"matching_legions={counts.get('matching_legions')} matching_opsgroups={counts.get('matching_opsgroups')}"
    )


async def wait_for_outcome(client: MooseBridgeControlClient, auftrag_id: str, timeout_s: float, interval_s: float, command_timeout: float, trace: bool) -> AuftragOutcome:
    """Wait until the AUFTRAG has an evaluated summary.

    :param client: Control client.
    :param auftrag_id: Stable AUFTRAG id.
    :param timeout_s: Monitor timeout.
    :param interval_s: Poll interval.
    :param command_timeout: Command timeout.
    :param trace: Print trace on each poll.
    :returns: Evaluated outcome.
    """

    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        await client.request_snapshots(("snapshot.auftraege", "snapshot.legions", "snapshot.opsgroups"), timeout=command_timeout)
        snapshot = client.state.auftraege.get(auftrag_id)
        if trace:
            await print_trace(client, auftrag_id, command_timeout)
        if snapshot is not None and is_evaluated_auftrag_snapshot(snapshot):
            return AuftragOutcome.from_snapshot(snapshot)
        await asyncio.sleep(interval_s)
    raise TimeoutError(f"{auftrag_id} was not evaluated before timeout")


async def async_main(args: argparse.Namespace) -> int:
    """Run the control-based example.

    :param args: Parsed arguments.
    :returns: Process exit code.
    """

    client = MooseBridgeControlClient(args.control_host, args.control_port)
    status = await client.status(timeout=args.command_timeout)
    if not status.get("connected"):
        print("DCS is not connected to the running daemon.")
        return 3

    mission_type = canonical_mission_type(args.mission_type)
    params = parse_json_object(args.params_json)
    await client.request_snapshots(SNAPSHOTS, timeout=args.command_timeout)
    result = evaluate_auftrag_request(client.state, mission_type, params, coalition=args.coalition)
    recommendation = recommend_auftrag(result)
    if recommendation is None:
        print(f"No executable {mission_type} recommendation was found.")
        for issue in result.issues:
            print(f"  {issue.severity}: {issue.code}: {issue.message}")
        return 2

    print("Recommendation:", recommendation.to_dict())
    if not args.apply:
        return 0

    command_params = build_recommended_auftrag_command_params(recommendation)
    ack = await client.send_dcs_command(auftrag_action_for_mission_type(mission_type), command_params, timeout=args.command_timeout)
    print("ACK:", ack)
    payload = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    auftrag_id = str(payload.get("auftrag_id") or "")
    if not auftrag_id:
        return 4
    if args.trace and not args.monitor:
        await print_trace(client, auftrag_id, args.command_timeout)
    if args.monitor:
        outcome = await wait_for_outcome(client, auftrag_id, args.monitor_timeout, args.monitor_interval, args.command_timeout, args.trace)
        print("Outcome:", outcome.to_dict())
        return 0 if outcome.success else 6
    return 0


def parse_args() -> argparse.Namespace:
    """Parse arguments.

    :returns: Parsed arguments.
    """

    parser = argparse.ArgumentParser(description="Apply a recommended AUFTRAG through a running daemon.")
    parser.add_argument("--mission-type", required=True)
    parser.add_argument("--params-json", required=True, help="Advisory parameters as JSON object")
    parser.add_argument("--coalition", default="blue")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--monitor-timeout", type=float, default=600.0)
    parser.add_argument("--monitor-interval", type=float, default=5.0)
    parser.add_argument("--control-host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--command-timeout", type=float, default=10.0)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Run the CLI.

    :returns: Process exit code.
    """

    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
