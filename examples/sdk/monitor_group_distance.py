"""Periodically print the distance between two DCS/MOOSE groups.

This example is intentionally small and SDK-first. Use it as a starting point
for experimenting with ``MooseBridgeClient.distance`` and for writing your own
SDK-level tests.

Run against an already running MoosePyBridge daemon/control server:

    PYTHONPATH=python python examples/sdk/monitor_group_distance.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import MooseBridgeClient, MooseBridgeCommandError
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


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

    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    await print_distance_loop(bridge, GROUP_A, GROUP_B, INTERVAL_SECONDS, RUN_ONCE, COMMAND_TIMEOUT_SECONDS)
    return 0


async def async_main() -> int:
    """Run the monitor client."""

    try:
        return await run()
    except MooseBridgeCommandError as exc:
        print(f"DCS rejected distance command: {exc}")
        print(f"ACK: {exc.ack}")
        return 4
    except KeyboardInterrupt:
        print()
        return 130


def main() -> int:
    """Run the script entry point."""

    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
