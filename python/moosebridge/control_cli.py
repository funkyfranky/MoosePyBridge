"""Small CLI client for the local MOOSE Bridge control API."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from .control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient


def parse_params(text: str | None) -> dict[str, Any]:
    """Parse JSON parameters.

    :param text: JSON object text.
    :returns: Parameter dictionary.
    :raises ValueError: If the JSON value is not an object.
    """

    if not text:
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("--params-json must decode to an object")
    return value


async def async_main(args: argparse.Namespace) -> int:
    """Run the control CLI.

    :param args: Parsed command-line arguments.
    :returns: Process exit code.
    """

    client = MooseBridgeControlClient(args.control_host, args.control_port)

    if args.command == "status":
        result = await client.status(timeout=args.timeout)
    elif args.command == "state":
        kinds = args.kinds.split(",") if args.kinds else None
        await client.get_state(kinds=kinds, timeout=args.timeout)
        result = {"connected": client.state.connected, "counts": {kind: len(getattr(client.state, kind, {})) for kind in client.state.__dataclass_fields__ if isinstance(getattr(client.state, kind, None), dict)}}
    elif args.command == "send":
        result = await client.send_dcs_command(args.action, parse_params(args.params_json), timeout=args.timeout)
    elif args.command == "trace":
        result = await client.send_dcs_command("auftrag.trace", {"object_id": args.auftrag_id}, timeout=args.timeout)
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed arguments.
    """

    parser = argparse.ArgumentParser(description="MOOSE Bridge local control client")
    parser.add_argument("--control-host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--debug", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")

    state_parser = sub.add_parser("state")
    state_parser.add_argument("--kinds", default=None, help="Comma-separated raw state kinds")

    send_parser = sub.add_parser("send")
    send_parser.add_argument("action")
    send_parser.add_argument("--params-json", default=None)

    trace_parser = sub.add_parser("trace")
    trace_parser.add_argument("auftrag_id")

    return parser.parse_args()


def main() -> int:
    """Run the CLI entry point.

    :returns: Process exit code.
    """

    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
