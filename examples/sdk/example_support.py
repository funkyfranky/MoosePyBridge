"""Shared runtime plumbing for the directly executable SDK examples."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import MooseBridgeClient, MooseBridgeCommandError  # noqa: E402
from moosebridge.control import MooseBridgeControlClient  # noqa: E402
from moosebridge.control_sdk import sdk_from_control_client  # noqa: E402


@dataclass(slots=True, frozen=True)
class ExampleSession:
    """Connected control and high-level SDK clients for one example."""

    control: MooseBridgeControlClient
    bridge: MooseBridgeClient
    status: dict[str, Any]


class DcsNotConnectedError(ConnectionError):
    """Raised when the daemon is reachable but has no live DCS connection."""


async def open_example_session(
    host: str,
    port: int,
    timeout: float,
    *,
    client_id: str | None = None,
    display_name: str | None = None,
) -> ExampleSession:
    """Connect to the daemon and require an active DCS bridge connection."""

    kwargs: dict[str, str] = {}
    if client_id is not None:
        kwargs["client_id"] = client_id
    if display_name is not None:
        kwargs["display_name"] = display_name
    control = MooseBridgeControlClient(host, port, **kwargs)
    status = await control.status(timeout=timeout)
    if not status.get("connected"):
        raise DcsNotConnectedError("DCS is not connected to the running MoosePyBridge daemon.")
    return ExampleSession(
        control=control,
        bridge=sdk_from_control_client(control, timeout=timeout),
        status=status,
    )


def run_example(
    entrypoint: Callable[[], Awaitable[int]],
    *,
    debug: bool = False,
) -> int:
    """Run an async example with consistent logging and readable failures."""

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    try:
        return asyncio.run(entrypoint())
    except KeyboardInterrupt:
        print()
        return 130
    except DcsNotConnectedError as exc:
        print(exc)
        return 3
    except MooseBridgeCommandError as exc:
        print(f"DCS rejected the command: {exc}")
        print(f"ACK: {exc.ack}")
        return 4
    except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
        print(f"Example failed: {exc}")
        return 2
