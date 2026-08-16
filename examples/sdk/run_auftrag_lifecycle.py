"""Run one representative AUFTRAG lifecycle against a live DCS mission.

This example changes the running mission: it assigns an ONGUARD mission to a
LEGION, recruits assets, and keeps them at the target for a bounded duration.
Adjust the constants below to match the release mission before running it.
"""

from __future__ import annotations

from example_support import open_example_session, run_example

from moosebridge import Auftrag_ONGUARD  # noqa: E402
from moosebridge.control import DEFAULT_CONTROL_PORT  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0

TARGET_ZONE = "ZONE:Test Alpha"
LEGION_ID = "LEGION:Brigade Laage"
DURATION_SECONDS = 60
REQUIRED_ASSETS_MIN = 3
REQUIRED_ASSETS_MAX = 4


async def run() -> int:
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="auftrag-lifecycle-example",
        display_name="AUFTRAG Lifecycle Example",
    )
    bridge = session.bridge
    mission = Auftrag_ONGUARD(target=TARGET_ZONE)
    mission.set_duration(duration=DURATION_SECONDS)
    mission.set_required_assets(
        min_count=REQUIRED_ASSETS_MIN,
        max_count=REQUIRED_ASSETS_MAX,
    )

    ack = await bridge.add_auftrag(auftrag=mission, legion=LEGION_ID)
    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    auftrag_id = str(result.get("auftrag_id") or "unknown")
    mission_type = str(result.get("auftrag_type") or "On Guard")

    print("AUFTRAG lifecycle")
    print("=" * 80)
    print(f"AUFTRAG : {auftrag_id}")
    print(f"Type    : {mission_type}")
    print(f"Target  : {TARGET_ZONE}")
    print(f"LEGION  : {result.get('legion_id') or LEGION_ID}")
    print(f"Assets  : {REQUIRED_ASSETS_MIN}-{REQUIRED_ASSETS_MAX}")
    print(f"Duration: {DURATION_SECONDS}s")
    print(f"{auftrag_id} Planned status=planned")

    summary = await bridge.get_auftrag_summary(mission, on_status=print)

    print("\nTerminal summary")
    print("=" * 80)
    print(summary.to_dict())
    if summary.success is True:
        print(f"\nPASS: {summary.mission_type} completed successfully.")
        return 0

    print(f"\nFAIL: {summary.mission_type} did not complete successfully.")
    return 1


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
