"""Start a MoosePyBridge daemon and drive ARTY through the control client.

This example is a small integration smoke test for the server/client shape:

1. Start one DCS-facing bridge server.
2. Start one local control server.
3. Connect a client to the control port.
4. Request state snapshots.
5. Build an ARTY advisory recommendation.
6. Optionally apply it and trace the AUFTRAG over time.

Load these Lua files in DCS before running the script:

    Moose.lua
    lua/MooseBridgeJson.lua
    lua/MooseBridge.lua
    lua/MooseBridgeAuftragExecutionExtension.lua
    lua/MooseBridgeAuftragTraceExtension.lua
    lua/MooseBridgeMissionExample.lua

Example preview:

    PYTHONPATH=python python examples/control_server_client/apply_arty_with_control_client.py --x 1000 --z 2000 --coalition blue

Example execution with trace:

    PYTHONPATH=python python examples/control_server_client/apply_arty_with_control_client.py --x 1000 --z 2000 --coalition blue --apply --trace
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from moosebridge import evaluate_auftrag_request, recommend_auftrag
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient, MooseBridgeControlServer
from moosebridge.control_sdk import sdk_from_control_client
from moosebridge.sdk import build_recommended_auftrag_command_params
from moosebridge.server import DEFAULT_PORT, MooseBridgeServer


ADVISORY_SNAPSHOTS = (
    "snapshot.groups",
    "snapshot.units",
    "snapshot.statics",
    "snapshot.airbases",
    "snapshot.zones",
    "snapshot.opszones",
    "snapshot.cohorts",
    "snapshot.legions",
)

TRACE_SNAPSHOTS = (
    "snapshot.auftraege",
    "snapshot.legions",
    "snapshot.cohorts",
    "snapshot.opsgroups",
)


async def wait_for_dcs_connection(server: MooseBridgeServer, timeout_s: float) -> None:
    """Wait until the Lua bridge has connected to the DCS-facing server."""

    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if server.state.connected:
            return
        await asyncio.sleep(0.1)
    raise TimeoutError(f"No DCS bridge connection after {timeout_s:.1f} s.")


def build_arty_params(args: argparse.Namespace) -> dict[str, Any]:
    """Build ARTY advisory parameters from command line arguments."""

    params: dict[str, Any] = {}
    if args.target:
        params["target"] = args.target
    if args.x is not None:
        params["x"] = args.x
    if args.y is not None:
        params["y"] = args.y
    if args.z is not None:
        params["z"] = args.z
    if args.nshots is not None:
        params["nshots"] = args.nshots
    if args.radius_m is not None:
        params["radius_m"] = args.radius_m
    return params


def print_json(title: str, value: Any) -> None:
    """Print a compact titled JSON block."""

    print(f"\n{title}:")
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def print_trace(trace: dict[str, Any]) -> None:
    """Print a compact AUFTRAG trace result."""

    auftrag = trace.get("auftrag") if isinstance(trace.get("auftrag"), dict) else {}
    counts = trace.get("counts") if isinstance(trace.get("counts"), dict) else {}
    print(
        f"trace {trace.get('auftrag_id')} "
        f"found={trace.get('found')} source={trace.get('source')} "
        f"type={auftrag.get('type')} status={auftrag.get('status')} "
        f"summary={auftrag.get('summary_available')} counts={counts}"
    )

    target = auftrag.get("target") if isinstance(auftrag.get("target"), dict) else {}
    if target:
        print(
            f"  target={target.get('category')}:{target.get('name')} "
            f"x={target.get('x')} z={target.get('z')} "
            f"damage={target.get('damage')} destroyed={target.get('n_destroyed')}"
        )

    for item in trace.get("legions") or []:
        if isinstance(item, dict) and item.get("missionqueue_contains_auftrag"):
            print(f"  legion={item.get('object_id')} state={item.get('state')} queue={item.get('auftrag_queue_ids')}")

    for item in trace.get("opsgroups") or []:
        if isinstance(item, dict) and (item.get("current_contains_auftrag") or item.get("queue_contains_auftrag")):
            print(
                f"  opsgroup={item.get('object_id')} state={item.get('state')} "
                f"current={item.get('auftrag_current_id')} queue={item.get('auftrag_queue_ids')}"
            )


async def trace_auftrag(client: MooseBridgeControlClient, auftrag_id: str, timeout: float) -> dict[str, Any]:
    """Request fresh trace-related snapshots and then call ``auftrag.trace``."""

    sdk = sdk_from_control_client(client, timeout=timeout)
    await sdk.request_snapshots(TRACE_SNAPSHOTS)
    return await sdk.trace_auftrag(auftrag_id, timeout=timeout)


async def trace_loop(client: MooseBridgeControlClient, auftrag_id: str, args: argparse.Namespace) -> None:
    """Trace an AUFTRAG until summary data appears or the trace timeout expires."""

    deadline = asyncio.get_running_loop().time() + args.trace_timeout
    poll = 0
    while asyncio.get_running_loop().time() < deadline:
        trace = await trace_auftrag(client, auftrag_id, timeout=args.command_timeout)
        print_trace(trace)

        auftrag = trace.get("auftrag") if isinstance(trace.get("auftrag"), dict) else {}
        if auftrag.get("summary_available"):
            print("\nAUFTRAG summary is available; trace complete.")
            print_json("Final trace", trace)
            return

        poll += 1
        if not args.trace:
            return
        await asyncio.sleep(args.trace_interval)

    print(f"\nTrace timeout after {args.trace_timeout:.1f} s for {auftrag_id}.")


async def async_main(args: argparse.Namespace) -> int:
    """Run the daemon and control-client ARTY example."""

    bridge_server = MooseBridgeServer(
        host=args.host,
        port=args.port,
        log_path=Path(args.log) if args.log else None,
    )
    control_server = MooseBridgeControlServer(
        bridge_server,
        host=args.control_host,
        port=args.control_port,
    )
    client = MooseBridgeControlClient(args.control_host, args.control_port)

    await bridge_server.start()
    await control_server.start()
    try:
        print(f"DCS bridge server listening on {args.host}:{args.port}")
        print(f"Control server listening on {args.control_host}:{args.control_port}")
        print("Waiting for DCS/MOOSE Lua bridge ...")
        await wait_for_dcs_connection(bridge_server, args.connect_timeout)

        status = await client.status(timeout=args.command_timeout)
        print_json("Control status", status)

        print("\nRequesting advisory snapshots through the control client ...")
        sdk = sdk_from_control_client(client, timeout=args.command_timeout)
        await sdk.request_snapshots(ADVISORY_SNAPSHOTS)

        advisory = evaluate_auftrag_request(
            client.state,
            "ARTY",
            build_arty_params(args),
            coalition=args.coalition,
        )
        recommendation = recommend_auftrag(advisory)

        print_json(
            "Advisory",
            {
                "ok": advisory.ok,
                "issues": [asdict(issue) for issue in advisory.issues],
                "candidate_count": len(advisory.candidates),
            },
        )

        if recommendation is None:
            print("\nNo executable ARTY recommendation was found.")
            return 2

        print_json("Recommendation", recommendation.to_dict())

        command_params = build_recommended_auftrag_command_params(recommendation)
        print_json("Command parameters", command_params)

        if not args.apply:
            print("\nPreview only. Re-run with --apply to create and assign the ARTY AUFTRAG.")
            return 0

        print("\nApplying ARTY AUFTRAG through the control client ...")
        ack = await client.send_dcs_command("auftrag.create_arty", command_params, timeout=args.command_timeout)
        print_json("Apply ACK", ack)

        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        auftrag_id = result.get("auftrag_id")
        if not auftrag_id:
            print("\nDCS ACK did not include an auftrag_id; cannot trace the mission.")
            return 3

        await trace_loop(client, str(auftrag_id), args)
        return 0
    finally:
        await control_server.stop()
        await bridge_server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Start MoosePyBridge server/client and apply an ARTY AUFTRAG.")
    parser.add_argument("--host", default="127.0.0.1", help="DCS-facing host/interface.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="DCS-facing TCP port.")
    parser.add_argument("--control-host", default="127.0.0.1", help="Control API host/interface.")
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT, help="Control API TCP port.")
    parser.add_argument("--connect-timeout", type=float, default=60.0, help="Seconds to wait for DCS to connect.")
    parser.add_argument("--command-timeout", type=float, default=10.0, help="Seconds to wait for command ACKs.")
    parser.add_argument("--log", default=None, help="Optional raw JSONL protocol log path.")
    parser.add_argument("--target", default=None, help="Optional target object id, for example GROUP:Enemy-1 or ZONE:FireMission.")
    parser.add_argument("--x", type=float, default=None, help="Optional DCS world x coordinate in meters.")
    parser.add_argument("--y", type=float, default=None, help="Optional DCS world y coordinate in meters.")
    parser.add_argument("--z", type=float, default=None, help="Optional DCS world z coordinate in meters.")
    parser.add_argument("--nshots", type=float, default=None, help="Optional ARTY shot count.")
    parser.add_argument("--radius-m", type=float, default=None, help="Optional ARTY impact radius in meters.")
    parser.add_argument("--coalition", default="blue", help="Executing coalition filter.")
    parser.add_argument("--apply", action="store_true", help="Actually create and assign the AUFTRAG.")
    parser.add_argument("--trace", action="store_true", help="Keep tracing until summary data appears or timeout expires.")
    parser.add_argument("--trace-timeout", type=float, default=300.0, help="Maximum trace duration in seconds.")
    parser.add_argument("--trace-interval", type=float, default=5.0, help="Seconds between trace polls.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> int:
    """Run the script entry point."""

    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
