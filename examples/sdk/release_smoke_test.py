"""Run the non-destructive MoosePyBridge 0.1.0 live release smoke test.

Start the bridge daemon, the map server, and the designated DCS release mission
before running this script. It refreshes snapshots and briefly draws one F10
overlay, but does not create missions, damage objects, or alter strategic state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from example_support import REPO_ROOT

import moosebridge  # noqa: E402
from moosebridge import DebugMarkup, DebugMarkupPoint, MooseBridgeClient  # noqa: E402
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient  # noqa: E402
from moosebridge.control_sdk import sdk_from_control_client  # noqa: E402


EXPECTED_VERSION = "0.1.0"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
MAP_HEALTH_URL = "http://127.0.0.1:8000/api/health"
COMMAND_TIMEOUT_SECONDS = 30.0
F10_OVERLAY_SECONDS = 2.0

REQUIRED_DAEMON_COUNTS = {
    "groups": 1,
    "units": 1,
    "airbases": 1,
    "territories": 1,
    "opszones": 1,
    "cohorts": 1,
    "legions": 1,
    "commanders": 1,
    "intels": 1,
}

REQUIRED_MAP_COUNTS = {
    "topography_viewport_feature_count": 1,
    "surface_region_count": 1,
    "transport_bridge_count": 1,
    "transport_junction_count": 1,
    "railway_infrastructure_count": 1,
    "infrastructure_site_count": 1,
    "settlement_count": 1,
}


@dataclass(slots=True, frozen=True)
class Check:
    name: str
    status: str
    detail: str


def check(name: str, passed: bool, detail: str) -> Check:
    return Check(name, "PASS" if passed else "FAIL", detail)


def warning(name: str, detail: str) -> Check:
    return Check(name, "WARN", detail)


def ack_result(ack: dict[str, Any]) -> dict[str, Any]:
    """Return the command-specific payload from a DCS ACK."""

    result = ack.get("result")
    return result if isinstance(result, dict) else ack


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed local release endpoint
        return json.loads(response.read().decode("utf-8"))


def count_checks(prefix: str, counts: Any, required: dict[str, int]) -> list[Check]:
    values = counts if isinstance(counts, dict) else {}
    return [
        check(
            f"{prefix}: {kind}",
            int(values.get(kind) or 0) >= minimum,
            f"{int(values.get(kind) or 0)} (required >= {minimum})",
        )
        for kind, minimum in required.items()
    ]


def first_geographic_airbase(picture: Any) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in picture.airbases
            if item.get("latitude") is not None and item.get("longitude") is not None
        ),
        None,
    )


async def verify_f10_overlay(bridge: MooseBridgeClient, picture: Any) -> Check:
    airbase = first_geographic_airbase(picture)
    if airbase is None:
        return Check("DCS F10 overlay", "FAIL", "no airbase with WGS84 coordinates")

    overlay_id = "release-smoke-test"
    markup = DebugMarkup(
        "point",
        (
            DebugMarkupPoint(
                latitude=float(airbase["latitude"]),
                longitude=float(airbase["longitude"]),
            ),
        ),
        color=(0.1, 0.8, 0.9, 1.0),
        fill_color=(0.1, 0.8, 0.9, 0.15),
        radius_m=300.0,
    )
    draw_ack: dict[str, Any] = {}
    clear_ack: dict[str, Any] = {}
    try:
        draw_ack = await bridge.draw_debug_overlay(
            overlay_id,
            [markup],
            replace=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        await asyncio.sleep(F10_OVERLAY_SECONDS)
    finally:
        clear_ack = await bridge.clear_debug_overlay(overlay_id, timeout=COMMAND_TIMEOUT_SECONDS)

    draw_result = ack_result(draw_ack)
    clear_result = ack_result(clear_ack)
    mark_count = int(draw_result.get("mark_count") or 0)
    removed_count = int(clear_result.get("removed") or 0)
    location = airbase.get("dcs_name") or airbase.get("object_id")
    return check(
        "DCS F10 overlay",
        mark_count >= 1 and removed_count >= 1,
        f"drawn={mark_count} removed={removed_count} near {location}",
    )


def print_report(checks: list[Check]) -> None:
    print("MoosePyBridge 0.1.0 live release smoke test")
    print("=" * 72)
    for item in checks:
        print(f"[{item.status:4}] {item.name:<36} {item.detail}")

    passed = sum(item.status == "PASS" for item in checks)
    warnings = sum(item.status == "WARN" for item in checks)
    failures = sum(item.status == "FAIL" for item in checks)
    print("-" * 72)
    print(f"Result: {passed} passed, {warnings} warning(s), {failures} failure(s)")


async def run() -> int:
    checks: list[Check] = [
        check("SDK version", moosebridge.__version__ == EXPECTED_VERSION, moosebridge.__version__),
    ]
    control = MooseBridgeControlClient(
        CONTROL_HOST,
        CONTROL_PORT,
        client_id="release-smoke-test",
        display_name="Release Smoke Test",
    )

    try:
        status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    except (ConnectionError, OSError, RuntimeError) as exc:
        checks.append(Check("Bridge control server", "FAIL", str(exc)))
        print_report(checks)
        return 1

    connected = bool(status.get("connected"))
    checks.append(check("DCS bridge connection", connected, "connected" if connected else "disconnected"))
    if not connected:
        print_report(checks)
        return 1

    clock = status.get("clock") if isinstance(status.get("clock"), dict) else {}
    checks.append(
        check(
            "DCS mission clock",
            clock.get("mission_time") is not None and clock.get("dcs_time") is not None,
            f"mission={clock.get('mission_elapsed') or clock.get('mission_time') or '-'} "
            f"dcs={clock.get('dcs_datetime') or clock.get('dcs_time') or '-'}",
        )
    )

    bridge: MooseBridgeClient = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    try:
        picture = await bridge.refresh_global_picture()
    except Exception as exc:  # The report must retain the failing live boundary.
        checks.append(Check("Global picture refresh", "FAIL", f"{type(exc).__name__}: {exc}"))
        print_report(checks)
        return 1

    counts = picture.counts()
    checks.append(check("Global picture refresh", bool(picture.groups or picture.units), str(counts)))
    issues = picture.validate()
    errors = tuple(issue for issue in issues if issue.severity == "error")
    warnings = tuple(issue for issue in issues if issue.severity == "warning")
    checks.append(check("Global picture validation", not errors, f"errors={len(errors)} warnings={len(warnings)}"))
    if warnings:
        checks.append(warning("Global picture warnings", ", ".join(item.code for item in warnings[:5])))

    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    checks.extend(count_checks("DCS/MOOSE snapshot", status.get("counts"), REQUIRED_DAEMON_COUNTS))

    try:
        cursor = await control.event_cursor(timeout=COMMAND_TIMEOUT_SECONDS)
        checks.append(Check("Event service", "PASS", f"cursor={cursor or 'initial'}"))
    except (ConnectionError, OSError, RuntimeError) as exc:
        checks.append(Check("Event service", "FAIL", str(exc)))

    try:
        map_health = await asyncio.to_thread(fetch_json, MAP_HEALTH_URL, COMMAND_TIMEOUT_SECONDS)
        checks.append(check("Browser map server", True, MAP_HEALTH_URL))
        checks.extend(count_checks("Map layer", map_health, REQUIRED_MAP_COUNTS))
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        checks.append(Check("Browser map server", "FAIL", str(exc)))

    try:
        checks.append(await verify_f10_overlay(bridge, picture))
    except Exception as exc:  # Preserve the DCS command error in the report.
        checks.append(Check("DCS F10 overlay", "FAIL", f"{type(exc).__name__}: {exc}"))

    print_report(checks)
    print()
    print("Remaining manual release checks:")
    print("  1. Run one representative AUFTRAG lifecycle test for the release mission.")
    print("  2. Run: python examples/sdk/test_mission_reset.py")
    return 1 if any(item.status == "FAIL" for item in checks) else 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
