from __future__ import annotations

import asyncio
from datetime import datetime

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from moosebridge import MooseBridgeClient
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
INTERVAL_SECONDS = 10.0

LEGION_ID = "LEGION:Brigade Laage"  # oder None fuer alle LEGIONs


def text(value: object, default: str = "-") -> str:
    return str(value) if value not in (None, "") else default


def print_legion_status(bridge: MooseBridgeClient, legion_id: str | None = None) -> None:
    legions = [bridge.legion(legion_id)] if legion_id else list(bridge.state.legion_objects.values())
    legions = [legion for legion in legions if legion is not None]

    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] LEGION status")
    print("-" * 90)

    for legion in legions:
        missions = bridge.missions_of_legion(legion.object_id)
        cohorts = bridge.cohorts_of_legion(legion.object_id)

        stock_total = sum(cohort.stock_asset_count or 0 for cohort in cohorts)
        spawned_total = sum(cohort.spawned_asset_count or 0 for cohort in cohorts)
        asset_total = sum(cohort.asset_count or 0 for cohort in cohorts)

        print(
            f"{legion.object_id} "
            f"state={text(legion.state)} "
            f"coalition={text(legion.coalition or legion.coalition_name)} "
            f"airbase={text(legion.airbase_name)}"
        )
        print(
            f"  cohorts={len(cohorts)} "
            f"assets={asset_total} "
            f"stock={stock_total} "
            f"spawned={spawned_total} "
            f"missions={len(missions)}"
        )

        if missions:
            print("  missions:")
            for mission in missions:
                print(
                    f"    {mission.object_id} "
                    f"type={text(mission.type)} "
                    f"status={text(mission.status)}"
                )

        if cohorts:
            print("  cohorts:")
            for cohort in cohorts:
                missions = ", ".join(cohort.mission_type_keys[:6]) or "-"
                print(
                    f"    {cohort.object_id} "
                    f"cat={text(cohort.category)} "
                    f"type={text(cohort.unit_type)} "
                    f"stock={text(cohort.stock_asset_count)} "
                    f"spawned={text(cohort.spawned_asset_count)} "
                    f"missions=[{missions}]"
                )


async def main() -> None:
    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)

    status = await control.status()
    if not status.get("connected"):
        print("DCS ist nicht mit dem laufenden MoosePyBridge-Daemon verbunden.")
        return

    bridge = sdk_from_control_client(control, timeout=10.0)

    while True:
        await bridge.snapshot_legions()
        await bridge.snapshot_cohorts()
        await bridge.snapshot_auftraege()

        print_legion_status(bridge, LEGION_ID)

        await asyncio.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
