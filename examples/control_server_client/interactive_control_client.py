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
from dataclasses import dataclass, replace
import json
import math
import shlex
from typing import Any

from moosebridge import evaluate_auftrag_request, recommend_auftrag
from moosebridge.control import DEFAULT_CONTROL_PORT, STATE_KINDS, MooseBridgeControlClient
from moosebridge.intents import auftrag_command_params_from_recommendation, command_action_for_auftrag_recommendation


HELP_TEXT = """
Commands:
  help, ?                         Show this help.
  status                          Show daemon connection status and object counts.
  state [--list|--raw] [kind ...] [filters]
                                  Fetch mirrored state, optionally limited to kinds.
  snapshots [--list|--raw] <kind|action ...>
                                  Request DCS snapshots, e.g. groups units or snapshot.groups snapshot.units.
  send <action> [json-params]     Send a semantic DCS command through the daemon.
  mission <type> [options]        Validate, select assets, and create an AUFTRAG.
  trace [--raw|--verbose] <AUFTRAG:id>
                                  Trace an AUFTRAG assignment/execution path.
  coords <object_id> [--format xyz|ll|mgrs|all]
                                  Print object coordinates.
  distance <object_a> <object_b>  Measure distance between two objects.
  nearest <kind> <object_id> [filters]
                                  List nearest snapshot items to an object.
  mark <object_id> <text>         Create a map mark at an object position.
  drawzone <zone_id> [options]    Draw a MOOSE ZONE or OPSZONE on the F10 map.
  markpoint <x> <z> <text>        Create a map mark at a DCS world point.
  smoke <object_id> [color]       Create smoke at an object position.
  smokepoint <x> <z> [color]      Create smoke at a DCS world point.
  message [all|blue|red|neutral] <text>
                                  Send a message to all players or one coalition.
  quit, exit                      Close the client.

Examples:
  status
  snapshots --list groups units cohorts legions
  snapshots --list zones --contains Town
  state --list groups units --coalition blue --alive
  state --list groups units cohorts legions
  state --raw cohorts
  coords GROUP:Enemy-1
  coords AIRBASE:Gross Mohrdorf --format mgrs
  distance GROUP:Aerial-1 "ZONE:Town Fight"
  nearest units "ZONE:Town Fight" --coalition red --alive --limit 5
  mark GROUP:Enemy-1 Target area
  mark "ZONE:Town Fight" Target area
  drawzone "ZONE:Town Fight" --coalition blue --color red --alpha 0.8 --fill-alpha 0.15 --line-type dashed
  markpoint -33711 -510211 Fire mission
  send smoke.object {"object_id":"UNIT:Scout-1","color":"red"}
  message MoosePyBridge connected
  message blue Push now
  mission BAI --target GROUP:Ground-1 --coalition blue
  mission ARTY --target UNIT:Ground-1-1 --nshots 5 --radius 100 --legion BRIGADE:Laage
  trace AUFTRAG:1
  trace --raw AUFTRAG:1
""".strip()

OUTPUT_MODES = {"summary", "list", "raw"}
SMOKE_COLORS = {"red", "green", "blue", "orange", "white"}
DRAWZONE_COLORS = {"red", "green", "blue", "yellow", "orange", "white", "black", "grey", "gray"}
DRAWZONE_COALITIONS = {"all", "neutral", "red", "blue", "-1", "0", "1", "2"}
COORDINATE_FORMATS = {"xyz", "ll", "latlon", "latlong", "mgrs", "all"}
DRAWZONE_LINE_TYPES = {
    "none": 0,
    "solid": 1,
    "dashed": 2,
    "dotted": 3,
    "dotdash": 4,
    "dot-dash": 4,
    "dot_dash": 4,
    "longdash": 5,
    "long-dash": 5,
    "long_dash": 5,
    "twodash": 6,
    "two-dash": 6,
    "two_dash": 6,
}


@dataclass(slots=True, frozen=True)
class StateFilter:
    """Display filter for state output."""

    contains: str | None = None
    coalition: str | None = None
    alive: bool | None = None
    active: bool | None = None
    limit: int = 25


def print_json(value: Any) -> None:
    """Print a JSON-serializable value."""

    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def command_label(ack: dict[str, Any], fallback: str) -> str:
    """Return a compact command label for an ACK."""

    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    return str(result.get("action") or fallback)


def format_number(value: Any, decimals: int) -> str:
    """Format a numeric value with fixed decimal precision."""

    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def format_distance_m(value: Any) -> str:
    """Format meters for compact command output."""

    return format_number(value, 1)


def format_distance_nm(value: Any) -> str:
    """Format nautical miles for compact command output."""

    return format_number(value, 2)


def append_coordinate_feedback(details: list[str], result: dict[str, Any]) -> None:
    """Append coordinate details according to the requested output format."""

    coordinate_format = str(result.get("format") or "xyz").lower()
    show_xyz = coordinate_format in {"xyz", "all"}
    show_ll = coordinate_format in {"ll", "latlon", "latlong", "all"}
    show_mgrs = coordinate_format in {"mgrs", "all"}

    if show_xyz:
        if result.get("x") is not None and result.get("y") is not None and result.get("z") is not None:
            details.append(
                f"x={format_number(result.get('x'), 3)} "
                f"y={format_number(result.get('y'), 3)} "
                f"z={format_number(result.get('z'), 3)}"
            )
        elif result.get("x") is not None and result.get("z") is not None:
            details.append(f"x={format_number(result.get('x'), 3)} z={format_number(result.get('z'), 3)}")
    if show_ll and result.get("latitude") is not None and result.get("longitude") is not None:
        details.append(f"lat={format_number(result.get('latitude'), 5)} lon={format_number(result.get('longitude'), 5)}")
    if show_mgrs and result.get("mgrs") is not None:
        details.append(f"mgrs={result.get('mgrs')!r}")


def print_command_feedback(ack: dict[str, Any], fallback_action: str, debug: bool) -> None:
    """Print a command ACK in normal or debug form."""

    if debug:
        print_json(ack)
        return

    label = command_label(ack, fallback_action)
    if ack.get("ok", False):
        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        details: list[str] = []
        if result.get("object_id") is not None:
            details.append(f"object={result.get('object_id')}")
        if result.get("text") is not None:
            details.append(f"text={result.get('text')!r}")
        if result.get("coalition") is not None:
            details.append(f"coalition={result.get('coalition')}")
        if result.get("color") is not None:
            details.append(f"color={result.get('color')}")
        if result.get("alpha") is not None:
            details.append(f"alpha={result.get('alpha')}")
        if result.get("fill_color") is not None:
            details.append(f"fill_color={result.get('fill_color')}")
        if result.get("fill_alpha") is not None:
            details.append(f"fill_alpha={result.get('fill_alpha')}")
        if result.get("line_type") is not None:
            details.append(f"line_type={result.get('line_type')}")
        if label == "object.coords":
            append_coordinate_feedback(details, result)
        elif label == "object.distance":
            if result.get("object_id_a") is not None:
                details.append(f"from={result.get('object_id_a')}")
            if result.get("object_id_b") is not None:
                details.append(f"to={result.get('object_id_b')}")
            if result.get("distance_m") is not None:
                details.append(f"meters={format_distance_m(result.get('distance_m'))}")
            if result.get("distance_nm") is not None:
                details.append(f"nm={format_distance_nm(result.get('distance_nm'))}")
        elif result.get("x") is not None and result.get("y") is not None and result.get("z") is not None:
            details.append(f"x={result.get('x')} y={result.get('y')} z={result.get('z')}")
        elif result.get("x") is not None and result.get("z") is not None:
            details.append(f"x={result.get('x')} z={result.get('z')}")
        if result.get("auftrag_id") is not None:
            details.append(f"auftrag={result.get('auftrag_id')}")
        suffix = " " + " ".join(details) if details else ""
        print(f"OK {label}{suffix}")
        return

    print(f"ERROR {label}: {ack.get('error') or ack}")


def print_advisory_issues(result: Any) -> None:
    """Print advisory issues in compact form."""

    for issue in result.issues:
        print(f"{issue.severity.upper()} {issue.code}: {issue.message}")


def print_mission_feedback(recommendation: Any, ack: dict[str, Any] | None, preview: bool, debug: bool) -> None:
    """Print a compact mission recommendation or execution result."""

    data = recommendation.to_dict()
    prefix = "PREVIEW" if preview else "OK"
    parts = [
        prefix,
        str(data.get("mission_type")),
        f"legion={data.get('legion_id')}",
        f"cohort={data.get('cohort_id')}",
    ]
    if data.get("distance_nm") is not None:
        parts.append(f"distance={data['distance_nm']:.1f}NM")
    if data.get("selected_payload_uid") is not None:
        parts.append(f"payload_uid={data.get('selected_payload_uid')}")
    if data.get("selected_payload_aircrafttype") is not None:
        parts.append(f"aircraft={data.get('selected_payload_aircrafttype')}")
    if data.get("selected_payload_available") is not None:
        parts.append(f"payload_available={data.get('selected_payload_available')}")

    if ack is not None:
        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        if result.get("auftrag_id") is not None:
            parts.append(f"auftrag={result.get('auftrag_id')}")

    print(" ".join(parts))
    if debug:
        print_json({"recommendation": data, "ack": ack})


def format_count(value: Any) -> str:
    """Return a compact count string."""

    return str(value) if value is not None else "0"


def print_trace_compact(trace: dict[str, Any]) -> None:
    """Print a compact AUFTRAG trace summary."""

    auftrag = trace.get("auftrag") if isinstance(trace.get("auftrag"), dict) else {}
    counts = trace.get("counts") if isinstance(trace.get("counts"), dict) else {}
    target = auftrag.get("target") if isinstance(auftrag.get("target"), dict) else {}
    assigned = auftrag.get("assigned_group_ids") if isinstance(auftrag.get("assigned_group_ids"), list) else []

    parts = [
        f"TRACE {trace.get('auftrag_id')}",
        f"found={trace.get('found')}",
        f"source={trace.get('source')}",
    ]
    if auftrag:
        parts.extend(
            [
                f"type={auftrag.get('type')}",
                f"status={auftrag.get('status')}",
                f"summary={auftrag.get('summary_available')}",
                f"assigned={len(assigned)}",
            ]
        )
    parts.extend(
        [
            f"matching_legions={format_count(counts.get('matching_legions'))}",
            f"matching_opsgroups={format_count(counts.get('matching_opsgroups'))}",
        ]
    )
    print(" ".join(parts))

    if target:
        print(
            f"  target={target.get('category')}:{target.get('name')} "
            f"x={target.get('x')} z={target.get('z')} destroyed={target.get('n_destroyed')} damage={target.get('damage')}"
        )

    matching_legions = trace.get("matching_legion_ids") if isinstance(trace.get("matching_legion_ids"), list) else []
    matching_opsgroups = trace.get("matching_opsgroup_ids") if isinstance(trace.get("matching_opsgroup_ids"), list) else []
    if matching_legions:
        print("  legions=" + ", ".join(str(value) for value in matching_legions))
    if matching_opsgroups:
        print("  opsgroups=" + ", ".join(str(value) for value in matching_opsgroups))


def print_trace_verbose(trace: dict[str, Any]) -> None:
    """Print a medium-detail AUFTRAG trace summary."""

    print_trace_compact(trace)

    legions = trace.get("legions") if isinstance(trace.get("legions"), list) else []
    if legions:
        print("  LEGIONs:")
        for legion in legions:
            if not isinstance(legion, dict):
                continue
            marker = "*" if legion.get("missionqueue_contains_auftrag") else " "
            print(
                f"   {marker} {legion.get('object_id')} state={legion.get('state')} "
                f"queue={legion.get('auftrag_queue_ids')}"
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
                f"opsgroups={len(cohort.get('opsgroup_ids') or [])}"
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
                f"current={opsgroup.get('auftrag_current_id')} queue={opsgroup.get('auftrag_queue_ids')}"
            )


def print_trace(trace: dict[str, Any], mode: str) -> None:
    """Print a trace payload in the requested mode."""

    if mode == "raw":
        print_json(trace)
    elif mode == "verbose":
        print_trace_verbose(trace)
    else:
        print_trace_compact(trace)


def parse_trace_argument(argument: str) -> tuple[str, str]:
    """Parse ``trace [--raw|--verbose] <AUFTRAG:id>`` arguments."""

    parts = shlex.split(argument)
    if not parts:
        raise ValueError("trace requires an AUFTRAG:id")
    if parts[0] == "--raw":
        if len(parts) < 2:
            raise ValueError("trace --raw requires an AUFTRAG:id")
        return "raw", parts[1]
    if parts[0] == "--verbose":
        if len(parts) < 2:
            raise ValueError("trace --verbose requires an AUFTRAG:id")
        return "verbose", parts[1]
    return "summary", parts[0]


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


def normalize_drawzone_line_type(value: str) -> int:
    """Normalize a MOOSE DrawZone line type name or number."""

    key = value.strip().lower()
    if key in DRAWZONE_LINE_TYPES:
        return DRAWZONE_LINE_TYPES[key]
    try:
        line_type = int(key)
    except ValueError as exc:
        raise ValueError(f"Invalid line type: {value}") from exc
    if line_type < 0 or line_type > 6:
        raise ValueError(f"Invalid line type: {value}")
    return line_type


def parse_alpha(value: str, name: str) -> float:
    """Parse an alpha option in the inclusive [0, 1] range."""

    alpha = parse_float(value, name)
    if alpha < 0 or alpha > 1:
        raise ValueError(f"Invalid {name}: {value} (expected 0..1)")
    return alpha


def parse_drawzone_options(parts: list[str]) -> dict[str, Any]:
    """Parse DrawZone style options after the zone id."""

    params: dict[str, Any] = {}
    index = 0
    while index < len(parts):
        option = parts[index]
        key = option.lower()
        if key in {"--coalition", "-coalition"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            coalition = parts[index].lower()
            if coalition not in DRAWZONE_COALITIONS:
                raise ValueError(f"Invalid coalition: {parts[index]}")
            params["coalition"] = coalition
        elif key in {"--color", "-color"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            color = parts[index].lower()
            if color not in DRAWZONE_COLORS:
                raise ValueError(f"Invalid color: {parts[index]}")
            params["color"] = color
        elif key in {"--alpha", "-alpha"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params["alpha"] = parse_alpha(parts[index], "alpha")
        elif key in {"--fill-color", "--fill_color", "-fill-color", "-fill_color"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            color = parts[index].lower()
            if color not in DRAWZONE_COLORS:
                raise ValueError(f"Invalid fill color: {parts[index]}")
            params["fill_color"] = color
        elif key in {"--fill-alpha", "--fill_alpha", "-fill-alpha", "-fill_alpha"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params["fill_alpha"] = parse_alpha(parts[index], "fill_alpha")
        elif key in {"--line-type", "--line_type", "-line-type", "-line_type"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params["line_type"] = normalize_drawzone_line_type(parts[index])
        else:
            raise ValueError(f"Unknown drawzone option: {option}")
        index += 1

    return params


def normalize_drawzone_object_id(value: str) -> str:
    """Return a DrawZone object id, defaulting bare names to ZONE ids."""

    object_id = value.strip()
    if not object_id:
        raise ValueError("drawzone requires a zone id")
    if ":" in object_id:
        return object_id
    return f"ZONE:{object_id}"


def parse_drawzone_argument(argument: str) -> tuple[str, dict[str, Any]]:
    """Parse ``drawzone <zone_id> [options]`` arguments.

    Zone ids commonly contain spaces, so all tokens up to the first option are
    treated as the zone id. This allows ``drawzone ZONE:Town Fight --color red``
    without requiring quotes.
    """

    parts = shlex.split(argument)
    if not parts:
        raise ValueError("drawzone requires a zone id")

    option_start = len(parts)
    for index, part in enumerate(parts):
        if part.startswith("-"):
            option_start = index
            break

    zone_id = normalize_drawzone_object_id(" ".join(parts[:option_start]))
    return zone_id, parse_drawzone_options(parts[option_start:])


def parse_coords_argument(argument: str) -> tuple[str, dict[str, Any]]:
    """Parse ``coords <object_id> [--format xyz|ll|mgrs|all]`` arguments."""

    parts = shlex.split(argument)
    if not parts:
        raise ValueError("coords requires an object id")

    option_start = len(parts)
    for index, part in enumerate(parts):
        if part.startswith("-"):
            option_start = index
            break

    object_id = " ".join(parts[:option_start]).strip()
    if not object_id:
        raise ValueError("coords requires an object id")

    params: dict[str, Any] = {"object_id": object_id}
    index = option_start
    while index < len(parts):
        option = parts[index]
        key = option.lower()
        if key in {"--format", "-format"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            coordinate_format = parts[index].lower()
            if coordinate_format not in COORDINATE_FORMATS:
                raise ValueError(f"Invalid coordinate format: {parts[index]}")
            params["format"] = coordinate_format
        else:
            raise ValueError(f"Unknown coords option: {option}")
        index += 1

    return object_id, params


def split_two_object_arguments(argument: str, known_ids: set[str]) -> tuple[str, str]:
    """Split a command argument into two object ids."""

    first_id, rest = split_object_argument(argument, known_ids)
    if not first_id or not rest:
        raise ValueError("expected two object ids")
    second_text = " ".join(rest)
    second_id, second_rest = split_object_argument(second_text, known_ids)
    if not second_id:
        raise ValueError("expected second object id")
    if second_rest:
        second_id = " ".join([second_id, *second_rest]).strip()
    return first_id, second_id


def parse_nearest_argument(argument: str) -> tuple[str, str, StateFilter]:
    """Parse ``nearest <kind> <object_id> [filters]`` arguments."""

    parts = shlex.split(argument)
    if len(parts) < 2:
        raise ValueError("nearest requires a kind and target object id")

    kind = parts[0]
    if kind not in STATE_KINDS:
        raise ValueError(f"Invalid nearest kind: {kind}")

    option_start = len(parts)
    for index in range(1, len(parts)):
        if parts[index].startswith("-"):
            option_start = index
            break

    target_id = " ".join(parts[1:option_start]).strip()
    if not target_id:
        raise ValueError("nearest requires a target object id")

    option_text = " ".join(parts[option_start:])
    _, _, state_filter = parse_state_output_args(option_text)
    if state_filter.limit == 25:
        state_filter = replace(state_filter, limit=5)
    return kind, target_id, state_filter


def parse_mission_argument(argument: str) -> tuple[str, dict[str, Any], str | None, str | None, bool]:
    """Parse ``mission <type> [options]`` command arguments."""

    parts = shlex.split(argument)
    if not parts:
        raise ValueError("mission requires a mission type")

    mission_type = parts[0]
    params: dict[str, Any] = {}
    coalition: str | None = None
    legion_id: str | None = None
    preview = False

    index = 1
    while index < len(parts):
        option = parts[index]
        key = option.lower()
        if key in {"--preview", "-preview"}:
            preview = True
            index += 1
            continue
        if key in {"--target", "-target"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params["target"] = parts[index]
        elif key in {"--coalition", "-coalition"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            coalition = parts[index].lower()
        elif key in {"--legion", "-legion"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            legion_id = parts[index]
        elif key in {"--altitude-ft", "--altitude", "-altitude"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params["altitude_ft"] = float(parts[index])
        elif key in {"--nshots", "--n-shots", "-nshots", "-nshots"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params["nshots"] = float(parts[index])
        elif key in {"--radius", "--radius-m", "-radius"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params["radius_m"] = float(parts[index])
        elif key in {"--x", "-x", "--y", "-y", "--z", "-z"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params[key.lstrip("-")] = float(parts[index])
        elif key in {"--engage-weapon-type", "-engage-weapon-type"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{option} requires a value")
            params["engage_weapon_type"] = int(parts[index])
        elif key in {"--divebomb", "-divebomb"}:
            params["divebomb"] = True
        else:
            raise ValueError(f"Unknown mission option: {option}")
        index += 1

    return mission_type, params, coalition, legion_id, preview


def known_object_ids(client: MooseBridgeControlClient) -> set[str]:
    """Return object ids currently known in the local client state."""

    result: set[str] = set()
    for kind in STATE_KINDS:
        values = getattr(client.state, kind)
        if not isinstance(values, dict):
            continue
        result.update(str(object_id) for object_id in values if object_id)
    return result


def normalize_legion_id(client: MooseBridgeControlClient, value: str) -> str:
    """Normalize LEGION/AIRWING/BRIGADE/FLEET shortcuts to a LEGION object id."""

    if not value:
        raise ValueError("legion id is empty")
    if value in client.state.legions:
        return value

    prefix, _, name = value.partition(":")
    prefix = prefix.upper()
    if not name:
        raise ValueError(f"Invalid legion id: {value}")
    if prefix == "LEGION":
        return value

    for legion in client.state.legion_objects.values():
        names = {legion.object_id, legion.dcs_name, legion.name or "", legion.alias or ""}
        if prefix == (legion.category or "").upper() and name in names:
            return legion.object_id
        if prefix == (legion.category or "").upper() and name in {item.removeprefix("LEGION:") for item in names}:
            return legion.object_id

    return f"LEGION:{name}"


def filter_advisory_to_legion(result: Any, legion_id: str) -> Any:
    """Return an advisory result limited to one selected LEGION."""

    candidates = [candidate for candidate in result.candidates if candidate.legion and candidate.legion.object_id == legion_id]
    return replace(result, candidates=candidates)


async def refresh_mission_state(client: MooseBridgeControlClient, timeout: float) -> None:
    """Refresh state needed for AUFTRAG advisory and execution."""

    await client.request_snapshots(
        (
            "snapshot.groups",
            "snapshot.units",
            "snapshot.statics",
            "snapshot.airbases",
            "snapshot.zones",
            "snapshot.opszones",
            "snapshot.cohorts",
            "snapshot.legions",
        ),
        timeout=timeout,
    )


def split_object_argument(argument: str, known_ids: set[str]) -> tuple[str, list[str]]:
    """Split an object command into object id and remaining arguments.

    Quoted ids such as ``"ZONE:Town Fight"`` are supported directly. For
    unquoted ids with spaces, the longest known object id prefix is used when
    the local client state already contains that object.
    """

    parts = shlex.split(argument)
    if not parts:
        return "", []

    best_index = 0
    best_id = parts[0]
    for index in range(len(parts), 0, -1):
        candidate = " ".join(parts[:index])
        if candidate in known_ids:
            best_index = index - 1
            best_id = candidate
            break
    return best_id, parts[best_index + 1 :]


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


def parse_state_output_args(argument: str) -> tuple[str, tuple[str, ...] | None, StateFilter]:
    """Parse state/snapshot display arguments into mode, items and filters."""

    parts = shlex.split(argument)
    mode = "summary"
    items: list[str] = []
    contains: str | None = None
    coalition: str | None = None
    alive: bool | None = None
    active: bool | None = None
    limit = 25

    index = 0
    while index < len(parts):
        part = parts[index]
        key = part.lower()
        if key in {"--list", "-list"}:
            mode = "list"
        elif key in {"--raw", "-raw"}:
            mode = "raw"
        elif key in {"--summary", "-summary"}:
            mode = "summary"
        elif key in {"--contains", "--name", "-contains", "-name"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{part} requires a value")
            contains = parts[index]
        elif key in {"--coalition", "-coalition"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{part} requires a value")
            coalition = parts[index].lower()
        elif key in {"--alive", "-alive"}:
            alive = True
        elif key in {"--dead", "-dead"}:
            alive = False
        elif key in {"--active", "-active"}:
            active = True
        elif key in {"--inactive", "-inactive"}:
            active = False
        elif key in {"--limit", "-limit"}:
            index += 1
            if index >= len(parts):
                raise ValueError(f"{part} requires a value")
            limit = int(parts[index])
        else:
            items.append(part)
        index += 1

    return mode, tuple(items) if items else None, StateFilter(contains=contains, coalition=coalition, alive=alive, active=active, limit=limit)


def selected_kinds(kinds: tuple[str, ...] | None) -> tuple[str, ...]:
    """Return valid selected state kinds."""

    return tuple(kind for kind in (STATE_KINDS if kinds is None else kinds) if kind in STATE_KINDS)


def object_label(item: dict[str, Any]) -> str:
    """Return a stable display label for a state object."""

    return str(item.get("object_id") or item.get("dcs_name") or item.get("name") or "<unknown>")


def searchable_text(item: dict[str, Any]) -> str:
    """Return lower-case searchable text for a state item."""

    fields = (
        "object_id",
        "dcs_name",
        "name",
        "group_name",
        "zone_name",
        "airbase_name",
        "unit_type",
        "dcs_type",
        "type",
        "category",
    )
    return " ".join(str(item.get(field) or "") for field in fields).lower()


def normalized_coalition(item: dict[str, Any]) -> str | None:
    """Return a normalized coalition value from a state item."""

    value = item.get("coalition") or item.get("coalition_name") or item.get("owner_current_name")
    if value is None or value == "":
        return None
    return str(value).strip().lower()


def item_matches_filter(item: dict[str, Any], state_filter: StateFilter) -> bool:
    """Return whether an item matches a display filter."""

    if state_filter.contains and state_filter.contains.lower() not in searchable_text(item):
        return False
    if state_filter.coalition and normalized_coalition(item) != state_filter.coalition:
        return False
    if state_filter.alive is not None and bool(item.get("alive", False)) is not state_filter.alive:
        return False
    if state_filter.active is not None and bool(item.get("active", False)) is not state_filter.active:
        return False
    return True


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


def state_items(client: MooseBridgeControlClient, kind: str, state_filter: StateFilter | None = None) -> list[dict[str, Any]]:
    """Return state items for a kind."""

    values = getattr(client.state, kind)
    items = list(values.values()) if isinstance(values, dict) else []
    if state_filter is None:
        return items
    return [item for item in items if item_matches_filter(item, state_filter)]


def item_point(item: dict[str, Any]) -> tuple[float, float] | None:
    """Return an item's x/z point if present."""

    try:
        x = float(item["x"])
        z = float(item["z"])
    except (KeyError, TypeError, ValueError):
        return None
    return x, z


def distance_between_xz(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return flat DCS world distance in meters between two x/z points."""

    return math.hypot(b[0] - a[0], b[1] - a[1])


def print_nearest(kind: str, target_id: str, target_point: tuple[float, float], items: list[dict[str, Any]], state_filter: StateFilter) -> None:
    """Print nearest state items to a target point."""

    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        if object_label(item) == target_id:
            continue
        point = item_point(item)
        if point is None:
            continue
        ranked.append((distance_between_xz(target_point, point), item))

    ranked.sort(key=lambda value: value[0])
    print(f"\nnearest {kind} to {target_id}: {len(ranked)}")
    for distance_m, item in ranked[: state_filter.limit]:
        print(f"  {format_distance_m(distance_m)}m {format_distance_nm(distance_m / 1852)}NM  {compact_item(kind, item)}")
    if len(ranked) > state_filter.limit:
        print(f"  ... {len(ranked) - state_filter.limit} more")


def print_state_summary(client: MooseBridgeControlClient, kinds: tuple[str, ...] | None = None, state_filter: StateFilter | None = None) -> None:
    """Print local client state counts."""

    counts = {kind: len(state_items(client, kind, state_filter=state_filter)) for kind in selected_kinds(kinds)}
    print_json({"connected": client.state.connected, "counts": counts})


def print_state_list(client: MooseBridgeControlClient, kinds: tuple[str, ...] | None = None, state_filter: StateFilter | None = None) -> None:
    """Print compact object lists for selected state kinds."""

    state_filter = state_filter or StateFilter()
    for kind in selected_kinds(kinds):
        items = state_items(client, kind, state_filter=state_filter)
        print(f"\n{kind}: {len(items)}")
        for item in items[: state_filter.limit]:
            print(f"  {compact_item(kind, item)}")
        if len(items) > state_filter.limit:
            print(f"  ... {len(items) - state_filter.limit} more")


def print_state_raw(client: MooseBridgeControlClient, kinds: tuple[str, ...] | None = None, state_filter: StateFilter | None = None) -> None:
    """Print raw state payloads for selected kinds."""

    payload: dict[str, Any] = {"connected": client.state.connected}
    for kind in selected_kinds(kinds):
        payload[kind] = state_items(client, kind, state_filter=state_filter)
    print_json(payload)


def print_state(client: MooseBridgeControlClient, kinds: tuple[str, ...] | None, mode: str, state_filter: StateFilter | None = None) -> None:
    """Print state in the requested mode."""

    if mode == "raw":
        print_state_raw(client, kinds=kinds, state_filter=state_filter)
    elif mode == "list":
        print_state_list(client, kinds=kinds, state_filter=state_filter)
    else:
        print_state_summary(client, kinds=kinds, state_filter=state_filter)


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
        mode, kinds, state_filter = parse_state_output_args(argument)
        await client.get_state(kinds=kinds, timeout=timeout)
        print_state(client, kinds=kinds, mode=mode, state_filter=state_filter)
        return True
    if command == "snapshots":
        mode, action_inputs, state_filter = parse_state_output_args(argument)
        if not action_inputs:
            print("Usage: snapshots [--list|--raw] <kind|action ...>")
            return True
        actions = normalize_snapshot_actions(action_inputs)
        validate_snapshot_actions(actions)
        result = await client.request("control.snapshots", params={"actions": list(actions)}, timeout=timeout)
        if debug:
            print_json({"acks": result.get("acks", [])})
        print_state(client, kinds=snapshot_actions_to_kinds(actions), mode=mode, state_filter=state_filter)
        return True
    if command == "send":
        action, _, params_text = argument.partition(" ")
        if not action:
            print("Usage: send <action> [json-params]")
            return True
        ack = await client.send_dcs_command(action, parse_json_params(params_text), timeout=timeout)
        print_command_feedback(ack, action, debug)
        return True
    if command == "mission":
        mission_type, params, coalition, explicit_legion, preview = parse_mission_argument(argument)
        await refresh_mission_state(client, timeout=timeout)

        legion_id = normalize_legion_id(client, explicit_legion) if explicit_legion else None
        if legion_id and coalition is None:
            legion = client.state.legion(legion_id)
            coalition = legion.coalition if legion else None

        result = evaluate_auftrag_request(client.state, mission_type, params, coalition=coalition)
        if result.issues:
            print_advisory_issues(result)
        if not result.ok:
            return True

        selected_result = filter_advisory_to_legion(result, legion_id) if legion_id else result
        recommendation = recommend_auftrag(selected_result)
        if recommendation is None:
            if legion_id:
                print(f"ERROR no executable {result.mission_type} candidate for {legion_id}")
            else:
                print(f"ERROR no executable {result.mission_type} candidate")
            return True

        if preview:
            print_mission_feedback(recommendation, ack=None, preview=True, debug=debug)
            return True

        action = command_action_for_auftrag_recommendation(recommendation)
        command_params = auftrag_command_params_from_recommendation(recommendation)
        ack = await client.send_dcs_command(action, command_params, timeout=timeout)
        print_mission_feedback(recommendation, ack=ack, preview=False, debug=debug)
        return True
    if command == "trace":
        try:
            mode, auftrag_id = parse_trace_argument(argument)
        except ValueError as exc:
            print(f"Usage: trace [--raw|--verbose] <AUFTRAG:id> ({exc})")
            return True
        ack = await client.send_dcs_command("auftrag.trace", {"object_id": auftrag_id}, timeout=timeout)
        result = ack.get("result") if isinstance(ack.get("result"), dict) else ack
        print_trace(result, mode=mode)
        return True
    if command == "coords":
        try:
            _, params = parse_coords_argument(argument)
        except ValueError as exc:
            print("Usage: coords <object_id> [--format xyz|ll|mgrs|all]")
            if str(exc):
                print(f"ERROR: {exc}")
            return True
        ack = await client.send_dcs_command("object.coords", params, timeout=timeout)
        print_command_feedback(ack, "object.coords", debug)
        return True
    if command == "distance":
        try:
            object_id_a, object_id_b = split_two_object_arguments(argument, known_object_ids(client))
        except ValueError as exc:
            print("Usage: distance <object_a> <object_b>")
            if str(exc):
                print(f"ERROR: {exc}")
            return True
        ack = await client.send_dcs_command(
            "object.distance",
            {"object_id_a": object_id_a, "object_id_b": object_id_b},
            timeout=timeout,
        )
        print_command_feedback(ack, "object.distance", debug)
        return True
    if command == "nearest":
        try:
            kind, target_id, state_filter = parse_nearest_argument(argument)
        except ValueError as exc:
            print("Usage: nearest <kind> <object_id> [--coalition red|blue] [--alive|--dead] [--active|--inactive] [--contains text] [--limit n]")
            if str(exc):
                print(f"ERROR: {exc}")
            return True
        target_ack = await client.send_dcs_command("object.coords", {"object_id": target_id, "format": "xyz"}, timeout=timeout)
        if not target_ack.get("ok", False):
            print_command_feedback(target_ack, "object.coords", debug)
            return True
        target_result = target_ack.get("result") if isinstance(target_ack.get("result"), dict) else {}
        target_point = item_point(target_result)
        if target_point is None:
            print(f"ERROR nearest: target has no x/z coordinates: {target_id}")
            return True
        await client.request("control.snapshots", params={"actions": [f"snapshot.{kind}"]}, timeout=timeout)
        print_nearest(kind, target_id, target_point, state_items(client, kind, state_filter=state_filter), state_filter)
        return True
    if command == "mark":
        object_id, rest = split_object_argument(argument, known_object_ids(client))
        text = " ".join(rest)
        if not object_id or not text:
            print("Usage: mark <object_id> <text>")
            return True
        ack = await client.send_dcs_command("mark.object", {"object_id": object_id, "text": text}, timeout=timeout)
        print_command_feedback(ack, "mark.object", debug)
        return True
    if command == "drawzone":
        try:
            object_id, params = parse_drawzone_argument(argument)
        except ValueError as exc:
            print("Usage: drawzone <ZONE:name|OPSZONE:name> [--coalition all|blue|red|neutral] [--color red] [--alpha 1] [--fill-color red] [--fill-alpha 0.15] [--line-type solid|dashed|0..6]")
            if str(exc):
                print(f"ERROR: {exc}")
            return True
        params["object_id"] = object_id
        ack = await client.send_dcs_command("zone.draw", params, timeout=timeout)
        print_command_feedback(ack, "zone.draw", debug)
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
        object_id, rest = split_object_argument(argument, known_object_ids(client))
        color = rest[0] if rest else "white"
        if not object_id:
            print("Usage: smoke <object_id> [color]")
            return True
        if color not in SMOKE_COLORS:
            print(f"Unsupported smoke color: {color}. Expected one of {sorted(SMOKE_COLORS)}")
            return True
        ack = await client.send_dcs_command("smoke.object", {"object_id": object_id, "color": color}, timeout=timeout)
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
