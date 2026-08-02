"""Print detailed ammunition for multiple groups.

The MoosePyBridge daemon/control server and the DCS mission are assumed to be
running already. All settings are constants below; no command-line arguments
are required.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PYTHON_DIR = REPO_ROOT / "python"
if LOCAL_PYTHON_DIR.exists():
    sys.path.insert(0, str(LOCAL_PYTHON_DIR))

from moosebridge import (
    MooseBridgeClient,
    MooseBridgeCommandError,
    UnitAmmunition,
    format_group_capabilities,
    format_weapon_range,
)
from moosebridge.control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client


GROUP_IDS = (
    "GROUP:MBT",
    #"GROUP:IFV",
    "GROUP:MLRS",
    #"GROUP:SPH",
    "GROUP:ATGM",
    #"GROUP:Truck",
)

CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 20.0
DEBUG = False


def format_percent(value: float | None) -> str:
    """Format an optional fraction as a percentage."""

    return f"{value * 100:6.1f}%" if value is not None else "   n/a"


def format_life(unit: UnitAmmunition) -> str:
    """Format unit life and its relative value."""

    if unit.life is None:
        return "n/a"
    if unit.life0 is None:
        return f"{unit.life:.1f}"
    return f"{unit.life:.1f}/{unit.life0:.1f} ({format_percent(unit.life_fraction).strip()})"


def print_unit_ammunition(bridge: MooseBridgeClient, unit: UnitAmmunition) -> None:
    """Print one typed unit-ammunition snapshot."""

    print(f"Unit       : {unit.unit_id}")
    print(f"Group      : {unit.group_id or 'n/a'}")
    print(f"DCS type   : {unit.dcs_type or 'n/a'}")
    print(f"Category   : {unit.category or 'n/a'}")
    print(f"Life       : {format_life(unit)}")
    print(f"Attributes : {', '.join(unit.attributes) if unit.attributes else 'none'}")

    if not unit.weapons:
        print("Ammunition : none reported by DCS")
        return

    print("Ammunition:")
    print(f"  {'Weapon':<32} {'Family':<8} {'Role':<18} {'Current':>8} {'Initial':>8} {'Remaining':>10}")
    print(f"  {'-' * 32} {'-' * 8} {'-' * 18} {'-' * 8} {'-' * 8} {'-' * 10}")
    task_flags = set()
    for weapon in unit.weapons:
        name = weapon.display_name or weapon.type_name or weapon.id
        print(
            f"  {name[:32]:<32} "
            f"{weapon.family.value:<8} "
            f"{weapon.role.value:<18} "
            f"{weapon.current_count:>8} "
            f"{weapon.initial_count:>8} "
            f"{format_percent(weapon.fraction):>10}"
        )
        effects = ", ".join(effect.value for effect in weapon.effects) or "none"
        domains = ", ".join(domain.value for domain in weapon.target_domains)
        print(
            f"    type={weapon.ammunition_type or 'n/a'} delivery={weapon.delivery.value} "
            f"targets={domains} effects={effects}"
        )
        if weapon.weapon_flags:
            print("    DCS task weapon flags:")
            for association in weapon.weapon_flags:
                marker = "preferred" if association.flag == weapon.preferred_weapon_flag else "compatible"
                breadth = "specific" if association.specific else "broad"
                print(
                    f"      {association.flag.name:<30} value={int(association.flag):>12} "
                    f"{marker}, {breadth}, {association.confidence.value}: {association.source}"
                )
        else:
            print("    DCS task weapon flags: none inferred")
        if weapon.preferred_weapon_flag is not None:
            task_flags.add(weapon.preferred_weapon_flag)

    if task_flags:
        print("Task weapon ranges:")
        for weapon_flag in sorted(task_flags, key=int):
            profile = bridge.unit_weapon_range(unit.unit_id, weapon_flag)
            if profile is None:
                print(f"  {unit.dcs_type or 'Unknown type'} {weapon_flag.name} range=unknown")
            else:
                print(f"  {format_weapon_range(profile)}")


def print_section(title: str) -> None:
    """Print a section heading."""

    print()
    print(title)
    print("=" * len(title))


def print_group_ammunition(bridge: MooseBridgeClient, group_id: str) -> None:
    """Print all unit-ammunition states belonging to one group."""

    print_section(f"Group ammunition: {group_id}")
    group_units = bridge.group_ammunition(group_id)
    if not group_units:
        print("No active, living ground units with ammunition data were found for this group.")
        return

    for index, unit in enumerate(group_units):
        if index:
            print("-" * 76)
        print_unit_ammunition(bridge, unit)

    print()
    print(format_group_capabilities(bridge.group_capabilities(group_id)))


async def run() -> int:
    """Request one ammunition snapshot and print the configured objects."""

    control = MooseBridgeControlClient(CONTROL_HOST, CONTROL_PORT)
    status = await control.status(timeout=COMMAND_TIMEOUT_SECONDS)
    if not status.get("connected"):
        print("DCS is not connected to the running MoosePyBridge daemon.")
        return 3

    bridge: MooseBridgeClient = sdk_from_control_client(control, timeout=COMMAND_TIMEOUT_SECONDS)
    all_units = await bridge.refresh_ammunition()

    for group_id in GROUP_IDS:
        print_group_ammunition(bridge, group_id)

    print()
    print(f"Snapshot contained {len(all_units)} active ground or naval unit(s) in total.")
    return 0


async def async_main() -> int:
    """Run the SDK example with readable error reporting."""

    try:
        return await run()
    except MooseBridgeCommandError as exc:
        print(f"DCS rejected the ammunition snapshot: {exc}")
        print(f"ACK: {exc.ack}")
        return 4
    except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
        print(f"Could not reach the MoosePyBridge daemon: {exc}")
        return 5


def main() -> int:
    """Run the script entry point."""

    logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
