"""Verify DCS mission-end forwarding and mission-scoped state cleanup.

Start the MooseBridge daemon, run this script, then end and restart the DCS
mission as requested by the prompts. No command-line arguments are required.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from example_support import REPO_ROOT

from moosebridge import (
    ObjectiveKind,
    OwnershipPolicy,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 15.0
MISSION_END_TIMEOUT_SECONDS = 7200.0
STATUS_INTERVAL_SECONDS = 1.0
MISSION_END_EVENTS_TO_TEST = 2


def heading(text: str) -> None:
    print()
    print(text)
    print("=" * len(text))


def nonzero_counts(counts: Any) -> dict[str, int]:
    if not isinstance(counts, dict):
        return {}
    return {
        str(kind): int(value)
        for kind, value in counts.items()
        if isinstance(value, (int, float)) and int(value) != 0
    }


def local_world_counts(control: MooseBridgeControlClient) -> dict[str, int]:
    state = control.state
    names = (
        "groups",
        "units",
        "ammunition",
        "statics",
        "airbases",
        "zones",
        "territories",
        "objects",
        "opszones",
        "opsgroups",
        "auftraege",
        "cohorts",
        "legions",
        "commanders",
        "intels",
        "intel_contacts",
        "lost_intel_contacts",
        "intel_clusters",
        "loss_reports",
    )
    return {name: len(getattr(state, name)) for name in names}


def event_reason(event: dict[str, Any]) -> tuple[str, str]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return (
        str(payload.get("reason") or "unknown"),
        str(payload.get("dcs_event_name") or "-")
    )


async def wait_for_active_mission(control: MooseBridgeControlClient) -> dict[str, Any]:
    announced = False
    while True:
        status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
        clock = status.get("clock") if isinstance(status.get("clock"), dict) else {}
        if (
            status.get("connected")
            and not status.get("mission_ended")
            and clock.get("mission_time") is not None
        ):
            return status
        if not announced:
            print("Waiting for an active DCS mission ...", flush=True)
            announced = True
        await asyncio.sleep(STATUS_INTERVAL_SECONDS)


def add_sdk_reset_markers(bridge: Any, cycle: int) -> None:
    objective_id = f"OBJECTIVE:Mission reset marker {cycle}"
    bridge.add_strategic_objective(
        StrategicObjective(
            objective_id=objective_id,
            name=f"Mission reset marker {cycle}",
            kind=ObjectiveKind.FORCE,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
        )
    )
    bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=f"GOAL:Mission reset marker {cycle}",
            name=f"Mission reset marker {cycle}",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective_id,
        )
    )


async def run() -> int:
    control = MooseBridgeControlClient(
        CONTROL_HOST,
        CONTROL_PORT,
        client_id="mission-reset-test",
        display_name="Mission Reset Test",
    )
    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)

    heading("DCS mission reset live test")
    print(f"Mission-end events to test: {MISSION_END_EVENTS_TO_TEST}")
    print("End and restart the DCS mission when prompted. Press Ctrl+C to stop.")

    cursor = await control.event_cursor(timeout=COMMAND_TIMEOUT_SECONDS)
    failures: list[str] = []

    for cycle in range(1, MISSION_END_EVENTS_TO_TEST + 1):
        status_before = await wait_for_active_mission(control)
        generation_before = int(status_before.get("mission_generation") or 0)
        await control.get_state(timeout=COMMAND_TIMEOUT_SECONDS)
        status_before = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
        add_sdk_reset_markers(bridge, cycle)

        heading(f"Cycle {cycle}: active mission")
        print(f"Generation       : {generation_before}")
        print(f"Mission time     : {(status_before.get('clock') or {}).get('mission_elapsed', '-')}")
        print(f"Daemon objects   : {sum(nonzero_counts(status_before.get('counts')).values())}")
        print(f"SDK objectives   : {len(bridge.strategic_objectives())}")
        print(f"SDK goals        : {len(bridge.strategic_goals())}")
        print("Now end the DCS mission.", flush=True)

        event = await bridge.server.wait_for_event(
            "mission.ended",
            timeout=MISSION_END_TIMEOUT_SECONDS,
            after_id=cursor,
        )
        cursor = str(event.get("id") or "") or cursor
        reason, dcs_event_name = event_reason(event)

        local_counts = nonzero_counts(local_world_counts(control))
        local_objectives = len(bridge.strategic_objectives())
        local_goals = len(bridge.strategic_goals())
        local_reset_ok = not local_counts and local_objectives == 0 and local_goals == 0

        status_after = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
        generation_after = int(status_after.get("mission_generation") or 0)
        daemon_counts = nonzero_counts(status_after.get("counts"))
        generation_ok = generation_after == generation_before + 1

        heading(f"Cycle {cycle}: mission end received")
        print(f"Wall time        : {datetime.now().strftime('%H:%M:%S')}")
        print(f"Event ID         : {event.get('id') or '-'}")
        print(f"Source           : {event.get('source') or 'dcs'}")
        print(f"Reason           : {reason}")
        print(f"DCS event        : {dcs_event_name}")
        print(f"Generation       : {generation_before} -> {generation_after}")
        print(f"Generation check : {'PASS' if generation_ok else 'FAIL'}")
        print(f"Local reset      : {'PASS' if local_reset_ok else 'FAIL'}")
        print(f"SDK objectives   : {local_objectives}")
        print(f"SDK goals        : {local_goals}")
        print(f"Local data       : {local_counts or 'empty'}")
        if daemon_counts:
            print(f"Daemon data      : {daemon_counts}")
            print("Daemon data may already belong to a newly started mission.")
        else:
            print("Daemon data      : empty")

        if not generation_ok:
            failures.append(f"cycle {cycle}: mission generation did not increase exactly once")
        if not local_reset_ok:
            failures.append(f"cycle {cycle}: local SDK or world state was not cleared")

        if cycle < MISSION_END_EVENTS_TO_TEST:
            print()
            print("Start the DCS mission again for the next cycle.", flush=True)

    heading("Test result")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: every mission end was forwarded and mission-scoped data was reset.")
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print()
        return 130
    except (ConnectionError, OSError) as exc:
        print(f"Cannot connect to the MooseBridge control server: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
