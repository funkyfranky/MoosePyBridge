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

from moosebridge import (  # noqa: E402
    DEFAULT_THEATER_PROFILE_PATH,
    MooseBridgeClient,
    MooseBridgeCommandError,
    SceneryVerificationFeature,
    TheaterDataPaths,
    TheaterDataProfile,
    load_theater_profile,
    resolve_scenery_verification_feature,
)
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


def load_example_theater(
    profile_path: str | Path = DEFAULT_THEATER_PROFILE_PATH,
) -> tuple[TheaterDataProfile, TheaterDataPaths]:
    """Resolve an editable example theater profile against the repository."""

    return load_theater_profile(profile_path, project_root=REPO_ROOT)


def load_example_scenery_feature(
    object_id: str,
    profile_path: str | Path | None = None,
) -> tuple[TheaterDataProfile, TheaterDataPaths, SceneryVerificationFeature]:
    """Find one normalized scenery-verifiable feature across theater profiles."""

    profile_paths = (
        (Path(profile_path),)
        if profile_path is not None
        else tuple(sorted(DEFAULT_THEATER_PROFILE_PATH.parent.glob("*_topography.json")))
    )
    if not profile_paths:
        raise ValueError("No theater profiles are available for automatic object lookup")

    loaded_profiles = [load_example_theater(path) for path in profile_paths]
    id_parts = object_id.split(":")
    theater_hint = id_parts[1].casefold() if len(id_parts) >= 3 else None
    hinted_profiles = [
        item
        for item in loaded_profiles
        if theater_hint is not None and item[0].theater_id.casefold() == theater_hint
    ]
    candidates = hinted_profiles or loaded_profiles
    matches: list[tuple[TheaterDataProfile, TheaterDataPaths, SceneryVerificationFeature]] = []
    failures: list[str] = []
    for theater, theater_paths in candidates:
        try:
            feature = resolve_scenery_verification_feature(
                theater.theater_id,
                object_id,
                {
                    key: theater_paths.path(key)
                    for key in (
                        "infrastructure_sites",
                        "railway_infrastructure",
                        "settlements",
                        "transport_infrastructure",
                    )
                },
            )
        except ValueError as exc:
            failures.append(f"{theater.theater_id}: {exc}")
            continue
        if feature is not None:
            matches.append((theater, theater_paths, feature))

    if len(matches) > 1:
        theaters = ", ".join(item[0].theater_id for item in matches)
        raise ValueError(
            f"Normalized theater feature is ambiguous across {theaters}: {object_id}. "
            "Set THEATER_PROFILE explicitly."
        )
    if not matches:
        searched = ", ".join(item[0].theater_id for item in candidates)
        detail = f" ({'; '.join(failures)})" if failures else ""
        raise ValueError(
            f"Normalized theater feature not found in {searched}: {object_id}{detail}"
        )
    return matches[0]


async def open_example_session(
    host: str,
    port: int,
    timeout: float,
    *,
    client_id: str | None = None,
    display_name: str | None = None,
    sdk_options: dict[str, Any] | None = None,
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
        bridge=sdk_from_control_client(control, timeout=timeout, **(sdk_options or {})),
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
    except ValueError as exc:
        print(f"Example configuration is invalid: {exc}")
        return 1
    except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
        print(f"Example failed: {exc}")
        return 2
