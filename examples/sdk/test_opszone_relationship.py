"""Live-test a future OPSZONE capture and its escalation incident.

The MoosePyBridge daemon and the DCS mission are assumed to be running. This
script treats the current OPSZONE snapshot as its baseline, evaluates only new
``opszone.owner_changed`` events in an isolated SDK relationship, and never
persists or changes mission state.

Edit WATCHED_OPSZONES when using different OPSZONEs in another test mission.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import EscalationIncidentType, RelationshipState, format_relationship
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 15.0
TEST_TIMEOUT_SECONDS = 180.0
UPDATE_INTERVAL_SECONDS = 2.0


WATCHED_OPSZONES = (
    "OPSZONE:Town Fight",
    "OPSZONE:Capture Alpha",
    "OPSZONE:Blue Camp Alpha",
)
EVENTS_TO_TEST = 1


def event_capture_data(event: dict[str, object]) -> tuple[str, str, str]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    opszone = payload.get("opszone") if isinstance(payload.get("opszone"), dict) else {}
    return (
        str(payload.get("opszone_id") or opszone.get("object_id") or ""),
        str(payload.get("previous_coalition") or opszone.get("owner_previous_name") or "").lower(),
        str(payload.get("capturing_coalition") or payload.get("coalition") or "").lower(),
    )


def print_capture_result(
    opszone_id: str,
    event: dict[str, object],
    incident: object,
    *,
    state_before: RelationshipState,
    state_after: RelationshipState,
    deduplicated: bool,
) -> tuple[bool, list[str]]:
    _, previous, actor = event_capture_data(event)
    details = getattr(incident, "details", {})
    actual_points = float(details.get("escalation_points") or 0.0)
    actual_context = str(details.get("territory_context") or "")
    failures: list[str] = []
    if not previous or previous == actor:
        failures.append(f"invalid ownership transition {previous or '-'} -> {actor or '-'}")
    if actor not in {"blue", "red"}:
        failures.append(f"capturing coalition is not blue or red: {actor or '-'}")
    if not actual_context:
        failures.append("territory context is missing")
    if not deduplicated:
        failures.append("replayed event created a duplicate incident")

    status = "PASS" if not failures else "FAIL"
    mission_time = event.get("mission_time")
    print(f"[{status}] {opszone_id}")
    print(f"  DCS time     : {mission_time}")
    print(f"  transition   : {previous or '-'} -> {actor or '-'}")
    print(f"  territory    : {actual_context or '-'}")
    print(f"  points       : {actual_points:.1f}")
    print(f"  relationship : {state_before.value} -> {state_after.value}")
    print(f"  deduplicated : {deduplicated}")
    for failure in failures:
        print(f"  ERROR        : {failure}")
    print()
    return not failures, failures


async def run() -> int:
    control = MooseBridgeControlClient(
        CONTROL_HOST,
        CONTROL_PORT,
        client_id="opszone-relationship-test",
        display_name="OPSZONE Relationship Test",
    )
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    retained = await control.query_events("opszone.owner_changed", timeout=COMMAND_TIMEOUT_SECONDS)
    cursor = str(retained.get("latest_event_id") or "") or None
    await bridge.snapshot_opszones()
    await control.get_state(("territories",), timeout=COMMAND_TIMEOUT_SECONDS)

    watched = set(WATCHED_OPSZONES)
    missing_objects = sorted(watched.difference(bridge.state.opszone_objects))
    if missing_objects:
        print("Configured OPSZONEs are missing from the mirrored state:")
        for object_id in missing_objects:
            print(f"  {object_id}")
        print("Available OPSZONEs:")
        for object_id in sorted(bridge.state.opszone_objects):
            print(f"  {object_id}")
        return 4

    print("OPSZONE relationship live test")
    print("=" * 90)
    print("This client evaluates events locally and does not persist diplomacy state.")
    print("The current snapshot is the baseline and causes no escalation incidents.")
    print("Baseline owners:")
    unattached: list[str] = []
    for object_id in WATCHED_OPSZONES:
        zone = bridge.state.opszone_objects[object_id]
        raw = bridge.state.opszones.get(object_id, {})
        attached = raw.get("capture_event_forwarder_attached") is True
        callback_type = str(raw.get("capture_event_callback_type") or "unknown")
        print(
            f"  {object_id}: owner={zone.owner_current_name or 'unknown'} "
            f"forwarder={'attached' if attached else 'MISSING'} callback={callback_type}"
        )
        if not attached:
            unattached.append(object_id)
    if unattached:
        print()
        print("OPSZONE capture forwarding is not attached in the running DCS mission.")
        print("Load the current MooseBridgeAuftragExecutionExtension.lua and restart the mission.")
        print("Affected OPSZONEs:")
        for object_id in unattached:
            print(f"  {object_id}")
        return 5
    print(f"Waiting for {EVENTS_TO_TEST} future owner-change event(s).")
    print()

    processed: set[str] = set()
    failures: list[str] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TEST_TIMEOUT_SECONDS

    while loop.time() < deadline and len(processed) < EVENTS_TO_TEST:
        history = await control.query_events(
            "opszone.owner_changed",
            after_id=cursor,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        events = history.get("events") if isinstance(history.get("events"), list) else []
        cursor = str(history.get("latest_event_id") or "") or cursor

        for event in events:
            if not isinstance(event, dict):
                continue
            opszone_id, _, _ = event_capture_data(event)
            event_id = str(event.get("id") or "")
            if opszone_id not in watched or not event_id or event_id in processed:
                continue

            incident_count_before = len(bridge.relationship.incidents)
            state_before = bridge.relationship.state
            bridge.apply_diplomacy_events((event,))
            incident_count_after_first = len(bridge.relationship.incidents)
            bridge.apply_diplomacy_events((event,))
            incident_count_after_replay = len(bridge.relationship.incidents)
            deduplicated = (
                incident_count_after_first == incident_count_before + 1
                and incident_count_after_replay == incident_count_after_first
            )
            if incident_count_after_first != incident_count_before + 1:
                failures.append(f"{opszone_id}: event created no incident")
                print(f"[FAIL] {opszone_id}: event created no incident")
                processed.add(event_id)
                continue

            incident = bridge.relationship.incidents[-1]
            if incident.incident_type is not EscalationIncidentType.OPSZONE_CAPTURED:
                failures.append(f"{opszone_id}: unexpected incident type {incident.incident_type.value}")
            passed, capture_failures = print_capture_result(
                opszone_id,
                event,
                incident,
                state_before=state_before,
                state_after=bridge.relationship.state,
                deduplicated=deduplicated,
            )
            if not passed:
                failures.extend(f"{opszone_id}: {failure}" for failure in capture_failures)
            processed.add(event_id)

        if len(processed) < EVENTS_TO_TEST:
            print("Waiting for a future capture event in a watched OPSZONE ...", flush=True)
            await asyncio.sleep(UPDATE_INTERVAL_SECONDS)

    if len(processed) < EVENTS_TO_TEST:
        failures.append("no future OPSZONE owner-change event was received before timeout")

    print("Final local relationship")
    print("=" * 90)
    print(format_relationship(bridge.relationship))
    print()
    if failures:
        print("TEST FAILED")
        for failure in failures:
            print(f"  {failure}")
        return 6

    print("TEST PASSED: the future capture was forwarded, scored, and deduplicated correctly.")
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
