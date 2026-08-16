"""Periodically print the distance between two DCS/MOOSE groups.

This example is intentionally small and SDK-first. Use it as a starting point
for experimenting with ``MooseBridgeClient.distance`` and for writing your own
SDK-level tests.

Run against an already running MoosePyBridge daemon/control server:

    PYTHONPATH=python python examples/sdk/monitor_group_distance.py
"""

from __future__ import annotations

import asyncio

from example_support import open_example_session, run_example

from moosebridge import MooseBridgeClient
from moosebridge.control import DEFAULT_CONTROL_PORT


GROUP_A = "GROUP:Aerial-1"
GROUP_B = "GROUP:Aerial-2"

CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT

INTERVAL_SECONDS = 2.0
COMMAND_TIMEOUT_SECONDS = 10.0
RUN_ONCE = False
DEBUG = False


async def print_distance_loop(bridge: MooseBridgeClient, group_a: str, group_b: str, interval_s: float, once: bool, timeout_s: float) -> None:
    """Print the distance between two object ids until interrupted."""

    while True:
        result = await bridge.distance(group_a, group_b, timeout=timeout_s)
        print(
            f"{result.object_id_a} -> {result.object_id_b}: "
            f"{result.distance_m:.1f} m / {result.distance_nm:.2f} NM",
            flush=True,
        )
        if once:
            return
        await asyncio.sleep(interval_s)


async def run() -> int:
    """Use an already running daemon/control server and monitor distances."""

    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    await print_distance_loop(
        session.bridge,
        GROUP_A,
        GROUP_B,
        INTERVAL_SECONDS,
        RUN_ONCE,
        COMMAND_TIMEOUT_SECONDS,
    )
    return 0


def main() -> int:
    """Run the script entry point."""

    return run_example(run, debug=DEBUG)


if __name__ == "__main__":
    raise SystemExit(main())
