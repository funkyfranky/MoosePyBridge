"""Live-test a tolerated border violation without using MOOSE INTEL.

Start the daemon and map server first. Place the configured active, living
ground group inside the opposing territory, then run this file. The map server
owns incident creation; this test only diagnoses the global GROUP/TERRITORY
mirror and waits for the persisted relationship update.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import BorderViolationTracker, EscalationIncidentType, format_relationship
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 15.0
UPDATE_INTERVAL_SECONDS = 5.0
TEST_TIMEOUT_SECONDS = 180.0

# Change these constants to objects in the running mission. The group must
# belong to the coalition opposing the territory owner.
GROUP_ID = "GROUP:Blue Border Test"
TERRITORY_ID = "TERRITORY:Red Territory Alpha"


async def run() -> int:
    control = MooseBridgeControlClient(
        CONTROL_HOST,
        CONTROL_PORT,
        client_id="border-violation-test",
        display_name="Border Violation Test",
    )
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    tracker = BorderViolationTracker(tolerance_s=60.0)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TEST_TIMEOUT_SECONDS

    await control.get_state(("groups", "territories"), timeout=COMMAND_TIMEOUT_SECONDS)
    group = bridge.state.groups.get(GROUP_ID)
    territory = bridge.territory(TERRITORY_ID)
    if group is None:
        print(f"Group not found in the global mirror: {GROUP_ID}")
        print("Available groups:")
        for object_id in sorted(bridge.state.groups):
            print(f"  {object_id}")
        return 4
    if territory is None:
        print(f"Territory not found in the global mirror: {TERRITORY_ID}")
        print("Available territories:")
        for object_id in sorted(bridge.state.territory_objects):
            print(f"  {object_id}")
        return 5
    if str(group.get("coalition") or "").lower() == str(territory.coalition or "").lower():
        print("The configured group and territory belong to the same coalition.")
        print("Choose a living, active ground group of the opposing coalition.")
        return 5

    print("Border violation live test")
    print("=" * 90)
    print(f"Group     : {GROUP_ID} coalition={group.get('coalition')}")
    print(f"Territory : {TERRITORY_ID} coalition={territory.coalition}")
    print("Source    : global GROUP/TERRITORY mirror (no INTEL contacts)")
    print("Tolerance : 60 DCS mission seconds")
    print("Move or keep the group inside the opposing territory.")
    print()

    while loop.time() < deadline:
        await control.get_state(("groups", "territories"), timeout=COMMAND_TIMEOUT_SECONDS)
        await bridge.refresh_diplomacy_state()
        clock = bridge.state.clock
        mission_time = clock.mission_time if clock is not None else None
        tracker.update(
            bridge.state.groups.values(),
            bridge.state.territory_objects.values(),
            mission_time=mission_time,
        )

        crossing = next(
            (
                item for item in tracker.active_violations
                if item[0] == GROUP_ID and item[1] == TERRITORY_ID
            ),
            None,
        )
        if crossing is None:
            print(f"mission={mission_time!s:>8} waiting for {GROUP_ID} to enter {TERRITORY_ID}", flush=True)
        else:
            _, _, entered_time, _ = crossing
            elapsed = max(0.0, (mission_time or entered_time) - entered_time)
            remaining = max(0.0, tracker.tolerance_s - elapsed)
            print(
                f"mission={mission_time:8.1f} crossing active "
                f"elapsed={elapsed:5.1f}s remaining={remaining:5.1f}s",
                flush=True,
            )

        incident = next(
            (
                item for item in reversed(bridge.relationship.incidents)
                if item.incident_type is EscalationIncidentType.BORDER_VIOLATION
                and item.details.get("group_id") == GROUP_ID
                and item.details.get("territory_id") == TERRITORY_ID
            ),
            None,
        )
        if incident is not None:
            print()
            print("Border violation recorded")
            print("=" * 90)
            print(f"Incident  : {incident.incident_id}")
            print(f"Actor     : {incident.actor_coalition}")
            print(f"Target    : {incident.target_coalition}")
            print(f"DCS time  : {incident.mission_time}")
            print(format_relationship(bridge.relationship))
            return 0

        await asyncio.sleep(UPDATE_INTERVAL_SECONDS)

    print()
    print("TIMEOUT: No persisted border-violation incident was observed.")
    print("Verify that the map server is running and refreshing the global picture.")
    return 6


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
