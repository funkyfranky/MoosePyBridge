"""Daemon entry point for MOOSE Bridge with a local multi-client control API."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .control import DEFAULT_CONTROL_PORT, MooseBridgeControlServer
from .server import DEFAULT_PORT, DEFAULT_READER_LIMIT, MooseBridgeServer
from .trace_cli import run_interactive_console

LOGGER = logging.getLogger(__name__)


async def _run(args: argparse.Namespace) -> None:
    """Run the daemon.

    :param args: Parsed command-line arguments.
    """

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bridge_server = MooseBridgeServer(
        args.host,
        args.port,
        Path(args.log) if args.log else None,
        reader_limit=args.reader_limit,
    )
    control_server = None
    if not args.no_control:
        control_server = MooseBridgeControlServer(
            bridge_server,
            host=args.control_host,
            port=args.control_port,
            reader_limit=args.control_reader_limit,
        )

    await bridge_server.start()
    if control_server is not None:
        await control_server.start()

    try:
        if args.interactive:
            await run_interactive_console(bridge_server)
        else:
            await asyncio.Event().wait()
    finally:
        if control_server is not None:
            await control_server.stop()
        await bridge_server.stop()


def main() -> None:
    """Console script entry point."""

    parser = argparse.ArgumentParser(description="MOOSE Bridge daemon with DCS and local control ports")
    parser.add_argument("--host", default="127.0.0.1", help="DCS-facing host/interface to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="DCS-facing bridge TCP port.")
    parser.add_argument("--control-host", default="127.0.0.1", help="Local control host/interface to bind.")
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT, help="Local control TCP port for Python tools.")
    parser.add_argument("--no-control", action="store_true", help="Disable the local control server.")
    parser.add_argument("--log", default="moosebridge_raw.jsonl", help="Optional raw JSONL DCS protocol log path.")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--reader-limit", type=int, default=DEFAULT_READER_LIMIT, help="Maximum incoming DCS JSONL line size in bytes.")
    parser.add_argument("--control-reader-limit", type=int, default=DEFAULT_READER_LIMIT, help="Maximum incoming control JSONL line size in bytes.")
    parser.add_argument("--interactive", action="store_true", help="Run an interactive console after starting the daemon.")
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user")


if __name__ == "__main__":
    main()
