"""Periodically print one COMMANDER or all known COMMANDER objects."""

from __future__ import annotations

import asyncio

from example_support import open_example_session, run_example

from moosebridge import MooseBridgeClient, format_commander_status
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
INTERVAL_SECONDS = 10.0
COMMAND_TIMEOUT_SECONDS = 10.0
COMMANDER_ID: str | None = "COMMANDER:Blue Commander"  # Use None for all.


async def run() -> int:
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge: MooseBridgeClient = session.bridge
    while True:
        await bridge.refresh_legion_state()
        print()
        print(format_commander_status(bridge, COMMANDER_ID))
        await asyncio.sleep(INTERVAL_SECONDS)


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
