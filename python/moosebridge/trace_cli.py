"""Trace-enabled command-line entry point for ``python -m moosebridge``."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from . import server as server_module
from .protocol import BridgeCommand


TRACE_HELP = """
  trace <auftrag_id> [--raw] Trace AUFTRAG assignment/execution path.
""".rstrip()


def _with_trace_help(text: str) -> str:
    """Insert trace help into the interactive help text.

    :param text: Original help text.
    :returns: Help text with trace command entry.
    """

    needle = "  auftraege               Request and print an AUFTRAG snapshot."
    if "trace <auftrag_id>" in text:
        return text
    if needle in text:
        return text.replace(needle, needle + "\n" + TRACE_HELP)
    return text + "\n" + TRACE_HELP


def _print_trace_result(trace: dict[str, Any]) -> None:
    """Print a compact AUFTRAG trace result.

    :param trace: Raw ``auftrag.trace`` result payload.
    """

    print(f"trace={trace.get('auftrag_id')} found={trace.get('found')} source={trace.get('source')} counts={trace.get('counts')}")

    auftrag = trace.get("auftrag") if isinstance(trace.get("auftrag"), dict) else {}
    if auftrag:
        print(
            f"  AUFTRAG type={auftrag.get('type')} status={auftrag.get('status')} "
            f"summary_available={auftrag.get('summary_available')} assigned={auftrag.get('assigned_group_ids')}"
        )
        target = auftrag.get("target")
        if target:
            print(f"  target={target}")

    matching_legions = trace.get("matching_legion_ids") or []
    matching_opsgroups = trace.get("matching_opsgroup_ids") or []
    print(f"  matching_legions={matching_legions}")
    print(f"  matching_opsgroups={matching_opsgroups}")

    legions = trace.get("legions") if isinstance(trace.get("legions"), list) else []
    if legions:
        print("  LEGIONs:")
        for legion in legions:
            if not isinstance(legion, dict):
                continue
            marker = "*" if legion.get("missionqueue_contains_auftrag") else " "
            print(
                f"   {marker} {legion.get('object_id')} state={legion.get('state')} "
                f"running={legion.get('is_running')} queue={legion.get('auftrag_queue_ids')}"
            )

    cohorts = trace.get("cohorts") if isinstance(trace.get("cohorts"), list) else []
    if cohorts:
        print("  COHORTs:")
        for cohort in cohorts:
            if not isinstance(cohort, dict):
                continue
            print(
                f"     {cohort.get('object_id')} legion={cohort.get('legion_id')} "
                f"stock={cohort.get('stock_asset_count')} spawned={cohort.get('spawned_asset_count')} "
                f"opsgroups={cohort.get('opsgroup_ids')}"
            )

    opsgroups = trace.get("opsgroups") if isinstance(trace.get("opsgroups"), list) else []
    if opsgroups:
        print("  OPSGROUPs:")
        for opsgroup in opsgroups:
            if not isinstance(opsgroup, dict):
                continue
            marker = "*" if opsgroup.get("current_contains_auftrag") or opsgroup.get("queue_contains_auftrag") else " "
            print(
                f"   {marker} {opsgroup.get('object_id')} state={opsgroup.get('state')} "
                f"alive={opsgroup.get('alive')} active={opsgroup.get('active')} "
                f"current={opsgroup.get('auftrag_current_id')} queue={opsgroup.get('auftrag_queue_ids')}"
            )


async def run_interactive_console(server: server_module.MooseBridgeServer) -> None:
    """Run the trace-enabled interactive command console.

    :param server: Running bridge server instance.
    """

    print(server_module.HELP_TEXT)

    while True:
        try:
            line = (await server_module._read_console_line()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not line:
            continue

        command, _, argument = line.partition(" ")
        command = command.lower()
        argument = argument.strip()

        if command in {"quit", "exit"}:
            return
        if command in {"help", "?"}:
            print(server_module.HELP_TEXT)
            continue
        if command == "status":
            print(f"connected={server.state.connected}")
            if server.state.last_heartbeat is not None:
                print(f"last_heartbeat={server.state.last_heartbeat}")
            continue
        if not server.state.connected:
            print("No DCS bridge connection is active.")
            continue

        try:
            if command == "groups":
                ack = await server.snapshot_groups()
                print(f"ACK: {ack}")
                server_module._print_group_snapshot(server.state.groups)
                continue
            if command == "units":
                ack = await server.snapshot_units()
                print(f"ACK: {ack}")
                server_module._print_unit_snapshot(server.state.units)
                continue
            if command == "statics":
                ack = await server.snapshot_statics()
                print(f"ACK: {ack}")
                server_module._print_static_snapshot(server.state.statics)
                continue
            if command == "airbases":
                ack = await server.snapshot_airbases()
                print(f"ACK: {ack}")
                server_module._print_airbase_snapshot(server.state.airbases)
                continue
            if command == "zones":
                ack = await server.snapshot_zones()
                print(f"ACK: {ack}")
                server_module._print_zone_snapshot(server.state.zones)
                continue
            if command == "opszones":
                ack = await server.snapshot_opszones()
                print(f"ACK: {ack}")
                server_module._print_opszone_snapshot(server.state.opszones)
                continue
            if command == "opsgroups":
                ack = await server.snapshot_opsgroups()
                print(f"ACK: {ack}")
                server_module._print_opsgroup_snapshot(server.state.opsgroups)
                continue
            if command == "auftraege":
                ack = await server.snapshot_auftraege()
                print(f"ACK: {ack}")
                server_module._print_auftrag_snapshot(server.state.auftraege)
                continue
            if command == "trace":
                parts = argument.split()
                if not parts:
                    print("Usage: trace <AUFTRAG:id> [--raw]")
                    continue
                auftrag_id = parts[0]
                raw = "--raw" in parts[1:]
                ack = await server.send_command(BridgeCommand(action="auftrag.trace", params={"object_id": auftrag_id}))
                print(f"ACK: {ack}")
                result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
                if raw:
                    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
                else:
                    _print_trace_result(result)
                continue
            if command == "smoke":
                object_id, _, color = argument.partition(" ")
                if not object_id:
                    print("Usage: smoke <object_id> [color]")
                    continue
                ack = await server.smoke_object(object_id, color.strip() or "white")
            elif command == "smokepoint":
                parts = argument.split(maxsplit=2)
                if len(parts) < 2:
                    print("Usage: smokepoint <x> <z> [color]")
                    continue
                color = parts[2] if len(parts) >= 3 else "white"
                ack = await server.smoke_at_point(server_module._parse_float(parts[0], "x"), server_module._parse_float(parts[1], "z"), color)
            elif command == "mark":
                object_id, _, text = argument.partition(" ")
                if not object_id or not text:
                    print("Usage: mark <object_id> <text>")
                    continue
                ack = await server.mark_object(object_id, text)
            elif command == "markpoint":
                parts = argument.split(maxsplit=2)
                if len(parts) < 3:
                    print("Usage: markpoint <x> <z> <text>")
                    continue
                ack = await server.mark_at_point(server_module._parse_float(parts[0], "x"), server_module._parse_float(parts[1], "z"), parts[2])
            elif command == "all":
                if not argument:
                    print("Usage: all <text>")
                    continue
                ack = await server.message_to_all(argument)
            elif command in {"blue", "red", "neutral"}:
                if not argument:
                    print(f"Usage: {command} <text>")
                    continue
                ack = await server.message_to_coalition(command, argument)
            else:
                print(f"Unknown command: {command}")
                print("Type 'help' for available commands.")
                continue
        except Exception as exc:
            print(f"ERROR: {exc}")
            continue

        print(f"ACK: {ack}")


def main() -> None:
    """Run the standard server CLI with a trace-enabled interactive console."""

    server_module.HELP_TEXT = _with_trace_help(server_module.HELP_TEXT)
    server_module.run_interactive_console = run_interactive_console
    server_module.main()
