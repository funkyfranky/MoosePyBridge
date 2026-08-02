#!/usr/bin/env python3
"""Generate compact ground-unit weapon ranges from Quaggles' DCS datamine."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterator


SOURCE_URL = "https://github.com/Quaggles/dcs-lua-datamine"


@dataclass(slots=True)
class LuaTable:
    values: list[Any] = field(default_factory=list)
    fields: dict[Any, Any] = field(default_factory=dict)


_TOKEN = re.compile(
    r"\s+|--\[(=*)\[(?:.|\n)*?\]\1\]|--[^\r\n]*|"
    r"(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')|"
    r"(?P<number>(?:0[xX][0-9a-fA-F]+)|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<identifier>[A-Za-z_][A-Za-z0-9_]*)|(?P<symbol>[{}\[\]=,;.+\-<>])",
    re.MULTILINE,
)


def _tokens(text: str) -> Iterator[tuple[str, str]]:
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise ValueError(f"Unsupported Lua syntax near offset {position}: {text[position:position + 40]!r}")
        position = match.end()
        if match.group(0).isspace() or match.group(0).startswith("--"):
            continue
        kind = match.lastgroup
        if kind is None:
            continue
        yield kind, match.group(kind)


class LuaLiteralParser:
    """Parse literal Lua tables without executing downloaded code."""

    def __init__(self, text: str) -> None:
        self.tokens = list(_tokens(text))
        self.index = 0

    def peek(self, value: str | None = None) -> tuple[str, str] | bool | None:
        if self.index >= len(self.tokens):
            return None if value is None else False
        token = self.tokens[self.index]
        return token if value is None else token[1] == value

    def take(self, value: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if not isinstance(token, tuple) or (value is not None and token[1] != value):
            raise ValueError(f"Expected {value!r}, got {token!r}")
        self.index += 1
        return token

    def parse_assignment(self) -> LuaTable:
        while not self.peek("="):
            if self.peek() is None:
                raise ValueError("Lua assignment was not found")
            self.index += 1
        self.take("=")
        result = self.parse_value()
        if not isinstance(result, LuaTable):
            raise ValueError("Top-level Lua value is not a table")
        return result

    def parse_value(self) -> Any:
        token = self.peek()
        if not isinstance(token, tuple):
            raise ValueError("Unexpected end of Lua input")
        kind, value = token
        if value == "<":
            self.take("<")
            while not self.peek(">"):
                if self.peek() is None:
                    raise ValueError("Unterminated datamine table marker")
                self.take()
            self.take(">")
            return self.parse_value() if self.peek("{") else LuaTable()
        if value == "-":
            self.take("-")
            return -self.parse_value()
        if value == "{":
            return self.parse_table()
        self.take()
        if kind == "string":
            return ast.literal_eval(value)
        if kind == "number":
            if value.lower().startswith("0x"):
                return int(value, 16)
            number = float(value)
            return int(number) if number.is_integer() and "." not in value and "e" not in value.lower() else number
        if kind == "identifier":
            return {"true": True, "false": False, "nil": None}.get(value, value)
        raise ValueError(f"Unsupported Lua value: {token!r}")

    def parse_table(self) -> LuaTable:
        result = LuaTable()
        self.take("{")
        while not self.peek("}"):
            token = self.peek()
            if token is None:
                raise ValueError("Unterminated Lua table")
            if self.peek("["):
                self.take("[")
                key = self.parse_value()
                self.take("]")
                self.take("=")
                result.fields[key] = self.parse_value()
            elif isinstance(token, tuple) and token[0] == "identifier" and self.index + 1 < len(self.tokens) and self.tokens[self.index + 1][1] == "=":
                key = self.take()[1]
                self.take("=")
                result.fields[key] = self.parse_value()
            else:
                result.values.append(self.parse_value())
            if self.peek(",") or self.peek(";"):
                self.take()
            elif not self.peek("}"):
                raise ValueError(f"Expected table separator, got {self.peek()!r}")
        self.take("}")
        return result


def _tables(value: Any) -> list[LuaTable]:
    return [item for item in value.values if isinstance(item, LuaTable)] if isinstance(value, LuaTable) else []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, LuaTable):
        return []
    result: list[str] = []
    for item in (*value.values, *value.fields.values()):
        result.extend(_strings(item))
    return result


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _attributes(unit: LuaTable) -> set[str]:
    return {value.casefold() for value in _strings(unit.fields.get("attribute")) + _strings(unit.fields.get("tags"))}


def _flag_from_weapon_id(weapon_id: str, attributes: set[str]) -> str | None:
    lowered = weapon_id.casefold()
    if "weapons.nurs" in lowered or "rocket" in lowered:
        return "ANY_ROCKET"
    if "weapons.missiles" in lowered or "missile" in lowered:
        if "atgm" in attributes or any(value in lowered for value in ("tow", "hellfire", "vikhr", "kornet")):
            return "ANTI_TANK_MISSILE"
        if "anti-ship" in lowered or "antiship" in lowered:
            return "ANTI_SHIP_MISSILE"
        if "cruise" in lowered or "tomahawk" in lowered:
            return "CRUISE_MISSILE"
        return "ANY_MISSILE"
    if "weapons.shells" in lowered or "shell" in lowered:
        return "CONVENTIONAL_SHELL" if _is_indirect(attributes) else "BUILT_IN_CANNON"
    return None


def _is_indirect(attributes: set[str]) -> bool:
    return bool(attributes & {"artillery", "indirect fire", "mortar", "mrl", "mlrs"})


def _primary_flag(attributes: set[str], discovered: set[str]) -> str | None:
    if attributes & {"mlrs", "mrl"}:
        return "ANY_ROCKET"
    if _is_indirect(attributes):
        return "CONVENTIONAL_SHELL"
    if "sam" in attributes and discovered <= {"ANY_MISSILE"}:
        return "ANY_MISSILE"
    if discovered == {"BUILT_IN_CANNON"}:
        return "BUILT_IN_CANNON"
    if discovered == {"ANTI_TANK_MISSILE"}:
        return "ANTI_TANK_MISSILE"
    if not discovered and attributes & {"tanks", "modern tanks", "old tanks"}:
        return "BUILT_IN_CANNON"
    return None


def _weapon_ids(launcher: LuaTable) -> tuple[str, ...]:
    result: set[str] = set()
    for payload in _tables(launcher.fields.get("PL")):
        for key in ("type_ammunition", "shell_name", "ammo_type"):
            for value in _strings(payload.fields.get(key)):
                if value and value not in {"Redacted", "none"}:
                    result.add(value)
    return tuple(sorted(result))


def descriptor_record(unit: LuaTable, source_path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dcs_type = unit.fields.get("type")
    if not isinstance(dcs_type, str) or not dcs_type:
        raise ValueError("Descriptor has no DCS type")
    attributes = _attributes(unit)
    discovered: set[str] = set()
    ranges: list[dict[str, Any]] = []
    for station in _tables(unit.fields.get("WS")):
        for launcher in _tables(station.fields.get("LN")):
            weapon_ids = _weapon_ids(launcher)
            flags = {flag for weapon_id in weapon_ids if (flag := _flag_from_weapon_id(weapon_id, attributes))}
            discovered.update(flags)
            minimum = _float(launcher.fields.get("distanceMin"))
            maximum = _float(launcher.fields.get("distanceMax"))
            if maximum is None or maximum <= 0 or len(flags) != 1:
                continue
            minimum = minimum if minimum is not None and minimum >= 0 else 0.0
            if maximum < minimum:
                continue
            ranges.append(
                {
                    "dcs_type": dcs_type,
                    "weapon_flag": next(iter(flags)),
                    "minimum_m": minimum,
                    "maximum_m": maximum,
                    "weapon_ids": list(weapon_ids),
                    "source_path": source_path,
                }
            )

    threat_max = _float(unit.fields.get("ThreatRange")) or 0.0
    threat_min = _float(unit.fields.get("ThreatRangeMin")) or 0.0
    envelope = {
        "dcs_type": dcs_type,
        "display_name": unit.fields.get("DisplayName"),
        "category": unit.fields.get("category"),
        "attributes": sorted(attributes),
        "minimum_m": max(0.0, threat_min),
        "maximum_m": max(0.0, threat_max),
        "primary_weapon_flag": _primary_flag(attributes, discovered),
        "source_path": source_path,
    }
    return envelope, ranges


def _git_value(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def build_artifact(source_root: Path, *, dcs_build: str | None = None) -> dict[str, Any]:
    directory = source_root / "_G" / "db" / "Units" / "Cars" / "Car"
    if not directory.is_dir():
        raise ValueError(f"Ground-unit descriptor directory not found: {directory}")

    envelopes: list[dict[str, Any]] = []
    ranges: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(directory.glob("*.lua"), key=lambda item: item.name.casefold()):
        relative = path.relative_to(source_root).as_posix()
        try:
            unit = LuaLiteralParser(path.read_text(encoding="utf-8-sig")).parse_assignment()
            envelope, unit_ranges = descriptor_record(unit, relative)
            envelopes.append(envelope)
            ranges.extend(unit_ranges)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{relative}: {exc}")

    if errors:
        preview = "\n".join(errors[:10])
        raise ValueError(f"Could not import {len(errors)} descriptor(s):\n{preview}")

    commit = _git_value(source_root, "rev-parse", "HEAD")
    detected_build = dcs_build or _git_value(source_root, "describe", "--tags", "--exact-match")
    return {
        "schema_version": 1,
        "source": {"url": SOURCE_URL, "commit": commit, "dcs_build": detected_build},
        "descriptor_count": len(envelopes),
        "weapon_ranges": sorted(ranges, key=lambda item: (item["dcs_type"].casefold(), item["weapon_flag"], item["minimum_m"])),
        "unit_envelopes": sorted(envelopes, key=lambda item: item["dcs_type"].casefold()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Local dcs-lua-datamine checkout")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("python/moosebridge/data/dcs_ground_weapon_ranges.json"),
        help="Generated JSON artifact",
    )
    parser.add_argument("--dcs-build", help="Override the DCS build metadata")
    args = parser.parse_args()

    artifact = build_artifact(args.source.resolve(), dcs_build=args.dcs_build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(
        f"Imported {artifact['descriptor_count']} descriptors and "
        f"{len(artifact['weapon_ranges'])} exact ranges into {args.output}"
    )


if __name__ == "__main__":
    main()
