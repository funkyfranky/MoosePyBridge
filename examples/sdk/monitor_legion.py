"""Periodically print one LEGION or all known LEGION objects."""

from __future__ import annotations

import asyncio

from example_support import open_example_session, run_example

from moosebridge import MooseBridgeClient
from moosebridge.control import DEFAULT_CONTROL_PORT
from moosebridge.diagnostics import format_legion_status


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
INTERVAL_SECONDS = 10.0
COMMAND_TIMEOUT_SECONDS = 10.0

LEGION_ID: str | None = "LEGION:Brigade Laage"  # Use None for all.


def print_legion_status(bridge: MooseBridgeClient, legion_id: str | None = None) -> None:
    print()
    print(format_legion_status(bridge, legion_id))


async def run() -> int:
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge

    while True:
        await bridge.refresh_legion_state()

        print_legion_status(bridge, LEGION_ID)

        await asyncio.sleep(INTERVAL_SECONDS)


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
