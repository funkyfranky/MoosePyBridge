"""Interactive control client for a running MoosePyBridge daemon.

Use this example to test the two-terminal server/client workflow.

Terminal 1:

    PYTHONPATH=python python -m moosebridge.daemon

Terminal 2:

    PYTHONPATH=python python examples/control_server_client/interactive_control_client.py

The client talks only to the local control API, normally port 51001. DCS/MOOSE
still connects to the daemon's DCS-facing port, normally 51000.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shlex
from typing import Any

from moosebridge.control import DEFAULT_CONTROL_PORT, STATE_KINDS, MooseBridgeControlClient


HELP_TEXT = """
Commands:
  help, ?                         Show this help.
  status                          Show daemon connection status and object counts.
  state [--list|--raw] [kind ...] Fetch mirrored state, optionally limited to kinds.
  snapshots [--list|--raw] <kind|action ...>
                                  Request DCS snapshots, e.g. groups units or snapshot.groups snapshot.units.
  send <action> [json-params]     Send a semantic DCS command through the daemon.
  trace <AUFTRAG:id>              Trace an AUFTRAG.
  mark <object_id> <text>         Create a map mark at an object position.
  markpoint <x> <z> <text>        Create a map mark at a DCS world point.
  smoke <object_id> [color]       Create smoke at an object position.
  smokepoint <x> <z> [color]      Create smoke at a DCS world point.
  message [all|blue|red|neutral] <text>
                                  Send a message to all players or one coalition.
  quit, exit                      Close the client.

Examples:
  status
  snapshots --list groups units cohorts legions
  state --list groups units cohorts legions
  state --raw cohorts
  mark GROUP:Enemy-1 Target area
  markpoint -33711 -510211 Fire mission
  send smoke.object {"object_id":"UNIT:Scout-1","color":"red"}
  message MoosePyBridge connected
  message blue Push now
  trace AUFTRAG:1
""".strip()

OUTPUT_MODES = {"summary", "list", "raw"}


def print_json(value: Any) -> None:
    """Print a JSON-serializable value."""

    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def command_label(ack: dict[str, Any], fallback: str) -> str:
    """Return a compact command label for an ACK."""

    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    return str(result.get("action") or fallback)


def print_command_feedback(ack: dict[str, Any], fallback_action: str, debug: bool) -> None:
    """Print a command ACK in normal or debug form."""

    if debug:
        print_json(ack)
        return

    label = command_label(ack, fallback_action)
    if ack.get("ok", False):
        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        details: list[str] = []
        if result.get("text") is not None:
            details.append(f"text={result.get('text')!r}")
        if result.get("coalition") is not None:
            details.append(f"coalition={result.get('coalition')}")
        if result.get("x") is not None and result.get("z") is not None:
            details.append(f"x={result.get('x')} z={result.get('z')}")
        if result.get("auftrag_id") is not None:
            details.append(f"auftrag={result.get('auftrag_id')}")
        suffix = " " + " ".join(details) if details else ""
        print(f"OK {label}{suffix}")
        return

    print(f"ERROR {label}: {ack.get('error') or ack}")


def parse_json_params(text: str) -> dict[str, Any]:
    """Parse optional command parameter JSON."""

    if not text:
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Parameters must be a JSON object")
    return value


def parse_float(value: str, name: str) -> float:
    """Parse a command-line float value."""

    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {name}: {value}") from exc


def parse_message_argument(argument: str) -> tuple[str, str]:
    """Parse ``message [recipient] <text>`` into recipient and text."""

    recipient, _, remainder = argument.partition(" ")
    recipient = recipient.lower().strip()
    if recipient in {"all", "blue", "red", "neutral"}:
        text = remainder.strip()
        if not text:
            raise ValueError("message requires text")
        return recipient, text

    text = argument.strip()
    if not text:
        raise ValueError("message requires text")
    return "all", text


def normalize_snapshot_actions(values: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize snapshot kind aliases to bridge command actions."""

    actions: list[str] = []
    for value in values:
        if value == "snapshot.all":
            actions.append(value)
        elif value == "all":
            actions.append("snapshot.all")
        elif value in STATE_KINDS:
            actions.append(f"snapshot.{value}")
        else:
            actions.append(value)
    return tuple(actions)


def snapshot_actions_to_kinds(actions: tuple[str, ...]) -> tuple[str, ...] | None:
    """Return state kinds implied by snapshot actions."""

    if any(action == "snapshot.all" for action in actions):
        return None
    kinds: list[str] = []
    for action in actions:
        prefix = "snapshot."
        if action.startswith(prefix):
            kind = action[len(prefix) :]
            if kind in STATE_KINDS and kind not in kinds:
                kinds.append(kind)
    return tuple(kinds)


def validate_snapshot_actions(actions: tuple[str, ...]) -> None:
    """Validate snapshot command actions before forwarding them to DCS."""

    invalid: list[str] = []
    suggestions: list[str] = []
    for action in actions:
        if action == "snapshot.all":
            continue
        if action.startswith("snapshots."):
            invalid.append(action)
            suggestions.append("snapshot." + action[len("snapshots.") :])
            continue
        if not action.startswith("snapshot."):
            invalid.append(action)
            continue
        kind = action[len("snapshot.") :]
        if kind not in STATE_KINDS:
            invalid.append(action)

    if not invalid:
        return

    message = "Invalid snapshot action(s): " + ", ".join(invalid)
    if suggestions:
        message += ". Did you mean: " + ", ".join(suggestions)
    raise ValueError(message)


def parse_output_mode(argument: str) -> tuple[str, str]:
    """Parse an optional output mode flag from a command argument."""

    parts = argument.split(maxsplit=1)
    if not parts:
        return "summary", ""
    if parts[0] == "--list":
        return "list", parts[1] if len(parts) > 1 else ""
    if parts[0] == "--raw":
        return "raw", parts[1] if len(parts) > 1 else ""
    if parts[0] == "--summary":
        return "summary", parts[1] if len(parts) > 1 else ""
    return "summary", argument


def selected_kinds(kinds: tuple[str, ...] | None) -> tuple[str, ...]:
    """Return valid selected state kinds."""

    return tuple(kind for kind in (STATE_KINDS if kinds is None else kinds) if kind in STATE_KINDS)


def object_label(item: dict[str, Any]) -> str:
    """Return a stable display label for a state object."""

    return str(item.get("object_id") or item.get("dcs_name") or item.get("name") or "<unknown>")


def compact_item(kind: str, item: dict[str, Any]) -> str:
    """Return one compact human-readable state object line."""

    label = object_label(item)
    if kind == "groups":
        return (
            f"{label} coalition={item.get('coalition')} category={item.get('category')} "
            f"alive={item.get('alive')} active={item.get('active')} "
            f"units={item.get('alive_unit_count')}/{item.get('unit_count')}"
        )
    if kind == "units":
        return (
            f"{label} group={item.get('group_name')} coalition={item.get('coalition')} "
            f"type={item.get('dcs_type')} alive={item.get('alive')} x={item.get('x')} z={item.get('z')}"
        )
    if kind == "zones":
        return f"{label} category={item.get('category')} source={item.get('source')} radius={item.get('radius')} x={item.get('x')} z={item.get('z')}"
    if kind == "opszones":
        return (
            f"{label} state={item.get('state')} owner={item.get('owner_current_name')} "
            f"contested={item.get('is_contested')} red={item.get('n_red')} blue={item.get('n_blue')}"
        )
    if kind == "opsgroups":
        return (
            f"{label} coalition={item.get('coalition')} state={item.get('state')} "
            f"alive={item.get('alive')} active={item.get('active')} current={item.get('auftrag_current_id')}"
        )
    if kind == "auftraege":
        return (
            f"{label} type={item.get('type')} status={item.get('status')} "
            f"assigned={len(item.get('assigned_group_ids') or [])} summary={item.get('summary_available')}"
        )
    if kind == "cohorts":
        return (
            f"{label} legion={item.get('legion_id')} category={item.get('category')} "
            f"unit_type={item.get('unit_type')} stock={item.get('stock_asset_count')} "
            f"missions={len(item.get('mission_type_keys') or item.get('mission_types') or [])}"
        )
    if kind == "legions":
        return (
            f"{label} category={item.get('category')} coalition={item.get('coalition')} "
            f"state={item.get('state')} airbase={item.get('airbase_name')} "
            f"cohorts={len(item.get('cohort_ids') or [])} queue={len(item.get('auftrag_queue_ids') or [])}"
        )
    if kind == "airbases":
        return f"{label} coalition={item.get('coalition')} category={item.get('category')} x={item.get('x')} z={item.get('z')}"
    if kind == "statics":
        return f"{label} coalition={item.get('coalition')} type={item.get('dcs_type')} alive={item.get('alive')} x={item.get('x')} z={item.get('z')}"
    return f"{label} type={item.get('object_type')} name={item.get('dcs_name')}"


def state_items(client: MooseBridgeControlClient, kind: str) -> list[dict[str, Any]]:
    """Return state items for a kind."""

    values = getattr(client.state, kind)
    return list(values.values()) if isinstance(values, dict) else []


def print_state_summary(client: MooseBridgeControlClient, kinds: tuple[str, ...] | None = None) -> None:
    """Print local client state counts."""

    counts = {kind: len(getattr(client.state, kind)) for kind in selected_kinds(kinds)}
    print_json({"connected": client.state.connected, "counts": counts})


def print_state_list(client: MooseBridgeControlClient, kinds: tuple[str, ...] | None = None, limit: int = 25) -> None:
    """Print compact object lists for selected state kinds."""

    print_state_summary(client, kinds=kinds)
    for kind in selected_kinds(kinds):
        items = state_items(client, kind)
        print(f"\n{kind}: {len(items)}")
        for item in items[:limit]:
            print(f"  {compact_item(kind, item)}")
        if len(items) > limit:
            print(f"  ... {len(items) - limit} more")


def print_state_raw(client: MooseBridgeControlClient, kinds: tuple[str, ...] | None = None) -> None:
    """Print raw state payloads for selected kinds."""

    payload: dict[str, Any] = {"connected": client.state.connected}
    for kind in selected_kinds(kinds):
        payload[kind] = state_items(client, kind)
    print_json(payload)


def print_state(client: MooseBridgeControlClient, kinds: tuple[str, ...] | None, mode: str) -> None:
    """Print state in the requested mode."""

    if mode == "raw":
        print_state_raw(client, kinds=kinds)
    elif mode == "list":
        print_state_list(client, kinds=kinds)
    else:
        print_state_summary(client, kinds=kinds)


async def read_input(prompt: str) -> str:
    """Read one console line without blocking the event loop."""

    return await asyncio.to_thread(input, prompt)


async def handle_line(client: MooseBridgeControlClient, line: str, timeout: float, debug: bool = False) -> bool:
    """Handle one interactive command.

    Returns ``False`` when the shell should exit.
    """

    command, _, argument = line.partition(" ")
    command = command.lower().strip()
    argument = argument.strip()

    if command in {"quit", "exit"}:
        return False
    if command in {"help", "?"}:
        print(HELP_TEXT)
        return True
    if command == "status":
        print_json(await client.status(timeout=timeout))
        return True
    if command == "state":
        mode, rest = parse_output_mode(argument)
        kinds = tuple(rest.split()) if rest else None
        await client.get_state(kinds=kinds, timeout=timeout)
        print_state(client, kinds=kinds, mode=mode)
        return True
    if command == "snapshots":
        mode, rest = parse_output_mode(argument)
        action_inputs = tuple(rest.split())
        if not action_inputs:
            print("Usage: snapshots [--list|--raw] <kind|action ...>")
            return True
        actions = normalize_snapshot_actions(action_inputs)
        validate_snapshot_actions(actions)
        result = await client.request("control.snapshots", params={"actions": list(actions)}, timeout=timeout)
        if debug:
            print_json({"acks": result.get("acks", [])})
        print_state(client, kinds=snapshot_actions_to_kinds(actions), mode=mode)
        return True
    if command == "send":
        action, _, params_text = argument.partition(" ")
        if not action:
            print("Usage: send <action> [json-params]")
            return True
        ack = await client.send_dcs_command(action, parse_json_params(params_text), timeout=timeout)
        print_command_feedback(ack, action, debug)
        return True
    if command == "trace":
        if not argument:
            print("Usage: trace <AUFTRAG:id>")
            return True
        ack = await client.send_dcs_command("auftrag.trace", {"object_id": argument}, timeout=timeout)
        print_json(ack.get("result") if isinstance(ack.get("result"), dict) else ack)
        return True
    if command == "mark":
        object_id, _, text = argument.partition(" ")
        if not object_id or not text:
            print("Usage: mark <object_id> <text>")
            return True
        ack = await client.send_dcs_command("mark.object", {"object_id": object_id, "text": text}, timeout=timeout)
        print_command_feedback(ack, "mark.object", debug)
        return True
    if command == "markpoint":
        parts = argument.split(maxsplit=2)
        if len(parts) < 3:
            print("Usage: markpoint <x> <z> <text>")
            return True
        ack = await client.send_dcs_command(
            "mark.at_point",
            {"x": parse_float(parts[0], "x"), "z": parse_float(parts[1], "z"), "text": parts[2]},
            timeout=timeout,
        )
        print_command_feedback(ack, "mark.at_point", debug)
        return True
    if command == "smoke":
        object_id, _, color = argument.partition(" ")
        if not object_id:
            print("Usage: smoke <object_id> [color]")
            return True
        ack = await client.send_dcs_command("smoke.object", {"object_id": object_id, "color": color.strip() or "white"}, timeout=timeout)
        print_command_feedback(ack, "smoke.object", debug)
        return True
    if command == "smokepoint":
        parts = argument.split(maxsplit=2)
        if len(parts) < 2:
            print("Usage: smokepoint <x> <z> [color]")
            return True
        color = parts[2] if len(parts) >= 3 else "white"
        ack = await client.send_dcs_command(
            "smoke.at_point",
            {"x": parse_float(parts[0], "x"), "z": parse_float(parts[1], "z"), "color": color},
            timeout=timeout,
        )
        print_command_feedback(ack, "smoke.at_point", debug)
        return True
    if command == "message":
        recipient, text = parse_message_argument(argument)
        if recipient == "all":
            action = "message.to_all"
            params = {"text": text, "duration": 10}
        else:
            action = "message.to_coalition"
            params = {"coalition": recipient, "text": text, "duration": 10}
        ack = await client.send_dcs_command(action, params, timeout=timeout)
        print_command_feedback(ack, action, debug)
        return True
    if command == "all":
        ack = await client.send_dcs_command("message.to_all", {"text": argument, "duration": 10}, timeout=timeout)
        print_command_feedback(ack, "message.to_all", debug)
        return True
    if command in {"blue", "red", "neutral"}:
        ack = await client.send_dcs_command(
            "message.to_coalition",
            {"coalition": command, "text": argument, "duration": 10},
            timeout=timeout,
        )
        print_command_feedback(ack, "message.to_coalition", debug)
        return True

    print(f"Unknown command: {command}")
    print("Type 'help' for available commands.")
    return True


async def interactive_main(args: argparse.Namespace) -> int:
    """Run the interactive control shell."""

    client = MooseBridgeControlClient(args.control_host, args.control_port)
    print(f"Connected client target: {args.control_host}:{args.control_port}")
    print("Type 'help' for commands.")

    while True:
        try:
            line = (await read_input("moosebridge-control> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue

        try:
            # shlex catches accidental unclosed quotes early while preserving the
            # original line for JSON parsing after the command action.
            shlex.split(line)
            if not await handle_line(client, line, args.timeout, debug=args.debug):
                return 0
        except Exception as exc:
            print(f"ERROR: {exc}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Interactive MoosePyBridge control client")
    parser.add_argument("--control-host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--debug", action="store_true", help="Print raw ACK/control payloads for command diagnostics.")
    return parser.parse_args()


def main() -> int:
    """Run the script entry point."""

    return asyncio.run(interactive_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
