"""Destroy one DCS unit by explosion and show its destruction event."""

from __future__ import annotations

import asyncio
from typing import Any

from example_support import open_example_session, run_example

from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 10.0
EVENT_TIMEOUT_SECONDS = 3600.0

UNIT_ID = "UNIT:Bradley Lost"
EXPLOSION_POWER_KG_TNT = 500.0
EXPLOSION_DELAY_SECONDS = 5.0


def print_unit(item: dict[str, Any] | None) -> None:
    if item is None:
        print("Unit is not present in the current state mirror.")
        return
    print(f"Object ID : {item.get('object_id', '-')}")
    print(f"Group     : {item.get('group_name', '-')}")
    print(f"DCS type  : {item.get('dcs_type', '-')}")
    print(f"Coalition : {item.get('coalition', '-')}")
    print(f"Alive     : {item.get('alive', '-')}")
    print(f"Active    : {item.get('active', '-')}")


async def run() -> int:
    session = await open_example_session(CONTROL_HOST, CONTROL_PORT, COMMAND_TIMEOUT_SECONDS)
    bridge = session.bridge
    await bridge.snapshot_groups()
    await bridge.snapshot_units()

    print("Initial state")
    print("=============")
    unit = bridge.state.units.get(UNIT_ID)
    print_unit(unit)
    if unit is None:
        print(f"\nConfigured unit was not found: {UNIT_ID}")
        return 1
    if not unit.get("alive", False):
        print(f"\nConfigured unit is already dead: {UNIT_ID}")
        return 1
    print()
    print(
        f"Destroying {UNIT_ID} with a {EXPLOSION_POWER_KG_TNT:g} kg TNT "
        f"explosion in {EXPLOSION_DELAY_SECONDS:g} second(s) ..."
    )

    event_waiter = asyncio.create_task(
        bridge.wait_for_object_destroyed(
            UNIT_ID,
            timeout=EVENT_TIMEOUT_SECONDS,
        )
    )
    await asyncio.sleep(0)

    try:
        ack = await bridge.explode_object(
            UNIT_ID,
            power=EXPLOSION_POWER_KG_TNT,
            delay=EXPLOSION_DELAY_SECONDS,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        print(
            f"Explosion scheduled at x={result.get('x', '-')} "
            f"y={result.get('y', '-')} z={result.get('z', '-')}"
        )
        print(f"Waiting for a DCS destruction event for {UNIT_ID} ...")
        event = await event_waiter
    except BaseException:
        event_waiter.cancel()
        await asyncio.gather(event_waiter, return_exceptions=True)
        raise

    print()
    print("Unit lost")
    print("=========")
    print(f"Source event : {event.dcs_event_name or '-'}")
    print(f"DCS time     : {event.dcs_event_time}")
    print_unit(bridge.state.units.get(UNIT_ID))
    if event.group is not None:
        print()
        print("Updated group")
        print("=============")
        print(f"Object ID   : {event.group.get('object_id', '-')}")
        print(f"Alive       : {event.group.get('alive', '-')}")
        print(f"Active      : {event.group.get('active', '-')}")
        print(f"Living units: {event.group.get('alive_unit_count', '-')}/{event.group.get('unit_count', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_example(run))
