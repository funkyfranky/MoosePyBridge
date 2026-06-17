"""Validate an AUFTRAG request without executing it in DCS.

This example performs advisory-only validation:
    - AUFTRAG type specification lookup
    - required parameter validation
    - target object lookup and type compatibility
    - combat friendly-fire check
    - executing coalition filter
    - LEGION-to-target distance ranking
    - COHORT mission performance reporting
    - AIRWING payload availability and payload performance reporting
    - structured recommendation output for the best executable candidate

Example:
    PYTHONPATH=python python examples/advisory/validate_auftrag_request.py --mission-type BAI --target GROUP:Enemy-1 --coalition blue --altitude-ft 15000 --host 127.0.0.1 --port 51000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

from moosebridge import BridgeCommand, MooseBridgeClient, MooseBridgeServer, evaluate_auftrag_request
from moosebridge.server import DEFAULT_PORT


async def wait_for_dcs_connection(server: MooseBridgeServer, timeout_s: float) -> None:
    """Wait until the DCS Lua bridge is connected.

    :param server: Running MOOSE Bridge server.
    :param timeout_s: Maximum wait time in seconds.
    :raises TimeoutError: If no DCS connection appears before the timeout.
    """

    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if server.state.connected:
            return
        await asyncio.sleep(0.1)

    raise TimeoutError(
        f"No DCS bridge connection after {timeout_s:.1f} s. "
        "Make sure MooseBridge.lua is loaded and uses the same host/port."
    )


async def request_required_snapshots(client: MooseBridgeClient) -> None:
    """Request snapshots needed for AUFTRAG advisory validation.

    :param client: MOOSE Bridge SDK client.
    """

    for action in ("snapshot.groups", "snapshot.units", "snapshot.statics", "snapshot.zones", "snapshot.cohorts", "snapshot.legions"):
        await client.server.send_command(BridgeCommand(action=action, params={}))
        await asyncio.sleep(0.05)


def payload_rejection_reason(candidate: Any, mission_type: str) -> str | None:
    """Return why an AIRWING candidate is not executable because of payload state.

    :param candidate: Advisory candidate.
    :param mission_type: Requested mission type.
    :returns: Rejection reason or ``None``.
    """

    if not candidate.cohort.is_air:
        return None
    payload_available = candidate.cohort.has_payload_for(mission_type)
    if payload_available is True:
        return None
    if payload_available is False:
        return "no compatible AIRWING payload available"
    return "payload availability unknown; load MooseBridgePayloadExtension.lua"


def candidate_sort_key(candidate: Any, mission_type: str) -> tuple[float, float, float, float]:
    """Return ranking key for executable advisory candidates.

    :param candidate: Advisory candidate.
    :param mission_type: Requested mission type.
    :returns: Sort key using mission performance, payload performance, distance and stock.
    """

    mission_performance = candidate.cohort.mission_performance_for(mission_type)
    payload_performance = candidate.cohort.payload_performance_for(mission_type)
    distance_m = candidate.distance_m if candidate.distance_m is not None else float("inf")
    stock = candidate.cohort.stock_asset_count or 0
    return (
        -(mission_performance if mission_performance is not None else -1.0),
        -(payload_performance if payload_performance is not None else -1.0),
        distance_m,
        -float(stock),
    )


def best_payload_for_candidate(candidate: Any, mission_type: str) -> dict[str, Any] | None:
    """Return the best compatible payload for a candidate and mission type.

    :param candidate: Advisory candidate.
    :param mission_type: Requested mission type.
    :returns: Payload summary dictionary or ``None``.
    """

    payload_info = candidate.cohort.payload_info_for(mission_type) or {}
    payloads = payload_info.get("payloads")
    if not isinstance(payloads, list):
        return None

    def payload_sort_key(payload: dict[str, Any]) -> tuple[float, float, float]:
        performance = payload.get("performance")
        navail = payload.get("navail")
        unlimited = 1.0 if payload.get("unlimited") else 0.0
        try:
            performance_value = float(performance) if performance is not None else -1.0
        except (TypeError, ValueError):
            performance_value = -1.0
        try:
            navail_value = float(navail) if navail is not None else 0.0
        except (TypeError, ValueError):
            navail_value = 0.0
        return (-performance_value, -unlimited, -navail_value)

    valid_payloads = [payload for payload in payloads if isinstance(payload, dict)]
    if not valid_payloads:
        return None
    return sorted(valid_payloads, key=payload_sort_key)[0]


def print_candidate(candidate: Any, mission_type: str, prefix: str = "  ") -> None:
    """Print one advisory candidate.

    :param candidate: Advisory candidate.
    :param mission_type: Requested mission type.
    :param prefix: Line prefix.
    """

    legion_id = candidate.legion.object_id if candidate.legion else "none"
    distance = f"{candidate.distance_nm:.1f} NM" if candidate.distance_nm is not None else "unknown"
    mission_performance = candidate.cohort.mission_performance_for(mission_type)
    mission_performance_text = f"{mission_performance:.1f}" if mission_performance is not None else "unknown"
    payload_available = candidate.cohort.has_payload_for(mission_type)
    payload_status = "unknown" if payload_available is None else ("available" if payload_available else "not_available")
    payload_performance = candidate.cohort.payload_performance_for(mission_type)
    payload_performance_text = f"{payload_performance:.1f}" if payload_performance is not None else "unknown"
    payload_info = candidate.cohort.payload_info_for(mission_type) or {}
    payload_count = payload_info.get("available_count", "unknown")
    print(
        f"{prefix}{legion_id} / {candidate.cohort.object_id} "
        f"unit_type={candidate.cohort.unit_type or 'unknown'} "
        f"stock={candidate.cohort.stock_asset_count} "
        f"mission_performance={mission_performance_text} "
        f"payload={payload_status} "
        f"payload_count={payload_count} "
        f"payload_performance={payload_performance_text} "
        f"distance={distance}"
    )


def print_recommendation(result: Any, executable: list[Any]) -> None:
    """Print a structured recommendation for the best executable candidate.

    :param result: Advisory result.
    :param executable: Sorted executable candidates.
    """

    if not executable:
        print("\nRecommendation:")
        print("  none")
        return

    candidate = executable[0]
    payload = best_payload_for_candidate(candidate, result.mission_type)
    mission_performance = candidate.cohort.mission_performance_for(result.mission_type)
    payload_performance = candidate.cohort.payload_performance_for(result.mission_type)
    distance = f"{candidate.distance_nm:.1f} NM" if candidate.distance_nm is not None else "unknown"

    print("\nRecommendation:")
    print(f"  legion_id: {candidate.legion.object_id if candidate.legion else 'none'}")
    print(f"  cohort_id: {candidate.cohort.object_id}")
    print(f"  constructor: {result.spec.constructor if result.spec else 'unknown'}")
    print(f"  mission_type: {result.mission_type}")
    for key, value in result.params.items():
        print(f"  {key}: {value}")
    print(f"  unit_type: {candidate.cohort.unit_type or 'unknown'}")
    print(f"  mission_performance: {mission_performance if mission_performance is not None else 'unknown'}")
    print(f"  payload_performance: {payload_performance if payload_performance is not None else 'unknown'}")
    print(f"  distance: {distance}")
    if payload:
        print(f"  selected_payload_uid: {payload.get('uid', 'unknown')}")
        print(f"  selected_payload_unitname: {payload.get('unitname', 'unknown')}")
        print(f"  selected_payload_aircrafttype: {payload.get('aircrafttype', 'unknown')}")
        print(f"  selected_payload_available: {payload.get('navail', 'unknown')}")
        print(f"  selected_payload_unlimited: {payload.get('unlimited', 'unknown')}")
    else:
        print("  selected_payload_uid: none")


def print_result(result: Any) -> None:
    """Print an AUFTRAG advisory result.

    :param result: Advisory result returned by ``evaluate_auftrag_request``.
    """

    print("\nRequest:")
    print(f"  mission_type: {result.mission_type}")
    print(f"  coalition: {result.coalition or 'any'}")
    for key, value in result.params.items():
        print(f"  {key}: {value}")

    print("\nValidation:")
    print(f"  AUFTRAG type known: {'yes' if result.spec else 'no'}")
    print(f"  target: {result.target_id or 'none'}")
    print(f"  target_type: {result.target_type or 'unknown'}")
    print(f"  target_coalition: {result.target_coalition or 'unknown/none'}")
    print(f"  ok: {'yes' if result.ok else 'no'}")

    if result.issues:
        print("\nIssues:")
        for issue in result.issues:
            print(f"  [{issue.severity}] {issue.code}: {issue.message}")

    executable = []
    rejected = []
    for candidate in result.candidates:
        reason = payload_rejection_reason(candidate, result.mission_type)
        if reason:
            rejected.append((candidate, reason))
        else:
            executable.append(candidate)
    executable.sort(key=lambda candidate: candidate_sort_key(candidate, result.mission_type))

    print(f"\nExecutable candidates: {len(executable)}")
    for candidate in executable:
        print_candidate(candidate, result.mission_type)

    if rejected:
        print(f"\nRejected candidates: {len(rejected)}")
        for candidate, reason in rejected:
            print_candidate(candidate, result.mission_type)
            print(f"    reason={reason}")

    print_recommendation(result, executable)


def print_payload_load_hint(result: Any) -> None:
    """Print a hint when AIRWING payload data is not present.

    :param result: Advisory result.
    """

    if not any(candidate.cohort.is_air and candidate.cohort.payload_info_for(result.mission_type) is None for candidate in result.candidates):
        return
    print("\nNote:")
    print("  AIRWING payload information requires loading lua/MooseBridgePayloadExtension.lua after MooseBridge.lua.")


async def async_main(args: argparse.Namespace) -> int:
    """Run the AUFTRAG advisory validation example.

    :param args: Parsed command-line arguments.
    :returns: Process exit code.
    """

    log_path = Path(args.log) if args.log else None
    server = MooseBridgeServer(host=args.host, port=args.port, log_path=log_path)
    client = MooseBridgeClient(server)

    await server.start()

    try:
        print(f"Waiting for DCS bridge connection on {args.host}:{args.port} ...")
        await wait_for_dcs_connection(server, args.connect_timeout)

        print("DCS connected. Requesting advisory snapshots ...")
        await request_required_snapshots(client)

        params: dict[str, Any] = {}
        if args.target:
            params["target"] = args.target
        if args.altitude_ft is not None:
            params["altitude_ft"] = args.altitude_ft

        result = evaluate_auftrag_request(
            state=client.state,
            mission_type=args.mission_type,
            params=params,
            coalition=args.coalition,
        )
        print_result(result)
        print_payload_load_hint(result)
        return 0 if result.ok else 2

    finally:
        await server.stop()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    :returns: Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(description="Validate an AUFTRAG request without executing it in DCS.")
    parser.add_argument("--mission-type", required=True, help="AUFTRAG mission type, for example BAI.")
    parser.add_argument("--target", default=None, help="Target object id, for example GROUP:Enemy-1.")
    parser.add_argument("--coalition", default=None, help="Executing coalition filter, for example blue or red.")
    parser.add_argument("--altitude-ft", type=float, default=None, help="Optional engage altitude in feet for supported AUFTRAG types.")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface for the Python bridge server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port for the Python bridge server.")
    parser.add_argument("--connect-timeout", type=float, default=60.0, help="Seconds to wait for DCS to connect.")
    parser.add_argument("--log", default=None, help="Optional raw JSONL protocol log path.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> int:
    """Run the script entry point.

    :returns: Process exit code.
    """

    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
