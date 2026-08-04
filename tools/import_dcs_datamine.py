#!/usr/bin/env python3
"""Generate compact ground-unit weapon and sensor ranges from the DCS datamine."""

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


def _field_values(value: Any, field_name: str) -> list[Any]:
    """Return recursively nested values for an exact Lua table field name."""

    if not isinstance(value, LuaTable):
        return []
    result = [value.fields[field_name]] if field_name in value.fields else []
    for child in (*value.values, *value.fields.values()):
        result.extend(_field_values(child, field_name))
    return result


def _numeric_values(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if not isinstance(value, LuaTable):
        return []
    result: list[float] = []
    for child in (*value.values, *value.fields.values()):
        result.extend(_numeric_values(child))
    return result


def _bounds(value: Any) -> list[float] | None:
    values = _numeric_values(value)
    return [min(values), max(values)] if values else None


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


_SENSOR_TYPES = {0: "optic", 1: "radar", 2: "irst", 3: "rwr"}


def _sensor_type(value: Any, fallback: str | None = None) -> str | None:
    numeric = int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if numeric in _SENSOR_TYPES:
        return _SENSOR_TYPES[numeric]
    if fallback:
        normalized = fallback.strip().casefold()
        if normalized in {"optic", "radar", "irst", "rwr", "visual"}:
            return normalized
    return None


def sensor_descriptor_profiles(sensor: LuaTable, source_path: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract optimistic air/surface bounds from one sensor descriptor."""

    name = sensor.fields.get("Name") or sensor.fields.get("DisplayName")
    if not isinstance(name, str) or not name:
        raise ValueError("Sensor descriptor has no name")
    detection_type = _sensor_type(sensor.fields.get("SensorType"))
    if detection_type is None:
        raise ValueError(f"Sensor descriptor has unsupported SensorType: {sensor.fields.get('SensorType')!r}")

    measuring_values = _numeric_values(sensor.fields.get("max_measuring_distance"))
    measuring_max = max((value for value in measuring_values if value > 0), default=None)
    scan_period = _float(sensor.fields.get("scan_period"))
    scan_volume = sensor.fields.get("scan_volume")
    scan_azimuth = _bounds(scan_volume.fields.get("azimuth")) if isinstance(scan_volume, LuaTable) else None
    scan_elevation = _bounds(scan_volume.fields.get("elevation")) if isinstance(scan_volume, LuaTable) else None
    profiles: list[dict[str, Any]] = []

    air_values = _numeric_values(sensor.fields.get("detection_distance"))
    air_search = sensor.fields.get("air_search")
    if isinstance(air_search, LuaTable):
        air_values.extend(_numeric_values(air_search.fields.get("detection_distance")))
    air_max = max((value for value in air_values if value > 0), default=None)
    if air_max is not None:
        profiles.append(
            {
                "detection_type": detection_type,
                "target_domain": "air",
                "maximum_m": min(air_max, measuring_max) if measuring_max else air_max,
                "hard_limit_m": measuring_max,
                "reference_rcs_m2": None,
                "scan_period_s": scan_period,
                "scan_azimuth_deg": scan_azimuth,
                "scan_elevation_deg": scan_elevation,
                "mode": "air_search",
                "exclusion_safe": True,
                "basis": "sensor.detection_distance",
                "source_path": source_path,
            }
        )

    surface_search = sensor.fields.get("surface_search")
    surface_fields = surface_search.fields if isinstance(surface_search, LuaTable) else sensor.fields
    surface_rcs = _float(surface_fields.get("RCS"))
    for key, value in surface_fields.items():
        normalized_key = str(key).casefold()
        if "detection_distance" not in normalized_key:
            continue
        if not isinstance(surface_search, LuaTable) and not normalized_key.startswith(("gmti_", "hrm_", "rbm_")):
            continue
        surface_values = _numeric_values(value)
        surface_max = max((item for item in surface_values if item > 0), default=None)
        if surface_max is None:
            continue
        mode = normalized_key.replace("_detection_distance", "")
        profiles.append(
            {
                "detection_type": detection_type,
                "target_domain": "surface",
                "maximum_m": min(surface_max, measuring_max) if measuring_max else surface_max,
                "hard_limit_m": measuring_max,
                "reference_rcs_m2": surface_rcs,
                "scan_period_s": scan_period,
                "scan_azimuth_deg": scan_azimuth,
                "scan_elevation_deg": scan_elevation,
                "mode": mode,
                "exclusion_safe": True,
                "basis": "sensor.surface_search",
                "source_path": source_path,
            }
        )

    if detection_type == "irst":
        irst_values: list[float] = []
        for key, value in sensor.fields.items():
            if "detectiondistance" in str(key).replace("_", "").casefold():
                irst_values.extend(_numeric_values(value))
        irst_max = max((value for value in irst_values if value > 0), default=None)
        if irst_max is not None and not profiles:
            profiles.append(
                {
                    "detection_type": detection_type,
                    "target_domain": "air",
                    "maximum_m": irst_max,
                    "hard_limit_m": measuring_max,
                    "reference_rcs_m2": None,
                    "scan_period_s": scan_period,
                    "scan_azimuth_deg": scan_azimuth,
                    "scan_elevation_deg": scan_elevation,
                    "mode": "tail_on",
                    "exclusion_safe": True,
                    "basis": "sensor.irst_detection_distance",
                    "source_path": source_path,
                }
            )
            head_coeff = _float(sensor.fields.get("head_on_distance_coeff"))
            if head_coeff is not None and head_coeff > 0:
                profiles.append(
                    {
                        "detection_type": detection_type,
                        "target_domain": "air",
                        "maximum_m": irst_max * head_coeff,
                        "hard_limit_m": measuring_max,
                        "reference_rcs_m2": None,
                        "scan_period_s": scan_period,
                        "scan_azimuth_deg": scan_azimuth,
                        "scan_elevation_deg": scan_elevation,
                        "mode": "head_on",
                        "exclusion_safe": True,
                        "basis": "sensor.irst_detection_distance",
                        "source_path": source_path,
                    }
                )

    if not profiles:
        profiles.append(
            {
                "detection_type": detection_type,
                "target_domain": "any",
                "maximum_m": None,
                "hard_limit_m": measuring_max,
                "reference_rcs_m2": None,
                "scan_period_s": scan_period,
                "scan_azimuth_deg": scan_azimuth,
                "scan_elevation_deg": scan_elevation,
                "mode": None,
                "exclusion_safe": False,
                "basis": "sensor_present_range_unknown",
                "source_path": source_path,
            }
        )

    return name, profiles


def unit_sensor_profiles(
    unit: LuaTable,
    source_path: str,
    sensors: dict[str, tuple[str, list[dict[str, Any]]]],
    platform_category: str = "ground",
) -> list[dict[str, Any]]:
    """Build organic and sensor-specific upper bounds for one ground unit."""

    dcs_type = unit.fields.get("type")
    if not isinstance(dcs_type, str) or not dcs_type:
        raise ValueError("Descriptor has no DCS type")
    overall_values = [
        number
        for value in _field_values(unit, "maxTargetDetectionRange")
        for number in _numeric_values(value)
        if number > 0
    ]
    overall_max = max(overall_values, default=None)
    result: list[dict[str, Any]] = []
    if overall_max is not None:
        result.append(
            {
                "dcs_type": dcs_type,
                "platform_category": platform_category,
                "detection_type": "organic",
                "target_domain": "any",
                "maximum_m": overall_max,
                "mode": None,
                "hard_limit_m": overall_max,
                "reference_rcs_m2": None,
                "scan_period_s": None,
                "scan_azimuth_deg": None,
                "scan_elevation_deg": None,
                "range_scope": "unit",
                "exclusion_safe": True,
                "emitter_only": False,
                "sensor_names": [],
                "source_paths": [source_path],
                "basis": "maxTargetDetectionRange",
            }
        )

    unit_sensors = unit.fields.get("Sensors")
    if not isinstance(unit_sensors, LuaTable):
        return result
    for category, value in unit_sensors.fields.items():
        detection_type = _sensor_type(None, str(category))
        if detection_type is None:
            continue
        for sensor_name in _strings(value):
            descriptor = sensors.get(sensor_name)
            descriptor_profiles = descriptor[1] if descriptor else []
            if descriptor_profiles:
                for profile in descriptor_profiles:
                    maximum = float(profile["maximum_m"]) if profile["maximum_m"] is not None else None
                    inherited_unit_bound = (
                        maximum is None
                        and overall_max is not None
                        and detection_type in {"optic", "visual", "radar", "irst"}
                    )
                    if inherited_unit_bound:
                        maximum = overall_max
                    elif maximum is not None and overall_max is not None:
                        maximum = min(maximum, overall_max)
                    result.append(
                        {
                            "dcs_type": dcs_type,
                            "platform_category": platform_category,
                            "detection_type": detection_type,
                            "target_domain": profile["target_domain"],
                            "maximum_m": maximum,
                            "mode": profile["mode"],
                            "hard_limit_m": overall_max if inherited_unit_bound else profile["hard_limit_m"],
                            "reference_rcs_m2": profile["reference_rcs_m2"],
                            "scan_period_s": profile["scan_period_s"],
                            "scan_azimuth_deg": profile["scan_azimuth_deg"],
                            "scan_elevation_deg": profile["scan_elevation_deg"],
                            "range_scope": "sensor",
                            "exclusion_safe": profile["exclusion_safe"] or inherited_unit_bound,
                            "emitter_only": detection_type == "rwr",
                            "sensor_names": [sensor_name],
                            "source_paths": [source_path, profile["source_path"]],
                            "basis": "maxTargetDetectionRange" if inherited_unit_bound else profile["basis"],
                        }
                    )
            elif overall_max is not None:
                result.append(
                    {
                        "dcs_type": dcs_type,
                        "platform_category": platform_category,
                        "detection_type": detection_type,
                        "target_domain": "any",
                        "maximum_m": overall_max,
                        "mode": None,
                        "hard_limit_m": overall_max,
                        "reference_rcs_m2": None,
                        "scan_period_s": None,
                        "scan_azimuth_deg": None,
                        "scan_elevation_deg": None,
                        "range_scope": "sensor",
                        "exclusion_safe": True,
                        "emitter_only": detection_type == "rwr",
                        "sensor_names": [sensor_name],
                        "source_paths": [source_path] + ([descriptor[0]] if descriptor else []),
                        "basis": "maxTargetDetectionRange",
                    }
                )
            else:
                result.append(
                    {
                        "dcs_type": dcs_type,
                        "platform_category": platform_category,
                        "detection_type": detection_type,
                        "target_domain": "any",
                        "maximum_m": None,
                        "mode": None,
                        "hard_limit_m": None,
                        "reference_rcs_m2": None,
                        "scan_period_s": None,
                        "scan_azimuth_deg": None,
                        "scan_elevation_deg": None,
                        "range_scope": "sensor",
                        "exclusion_safe": False,
                        "emitter_only": detection_type == "rwr",
                        "sensor_names": [sensor_name],
                        "source_paths": [source_path] + ([descriptor[0]] if descriptor else []),
                        "basis": "sensor_present_range_unknown",
                    }
                )
    return result


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


def build_sensor_artifact(source_root: Path, *, dcs_build: str | None = None) -> dict[str, Any]:
    """Build compact ground and airborne sensor data from DCS descriptors."""

    unit_directories = (
        ("ground", source_root / "_G" / "db" / "Units" / "Cars" / "Car"),
        ("airplane", source_root / "_G" / "db" / "Units" / "Planes" / "Plane"),
        ("helicopter", source_root / "_G" / "db" / "Units" / "Helicopters" / "Helicopter"),
    )
    sensor_directory = source_root / "_G" / "db" / "Sensors" / "Sensor"
    for _, unit_directory in unit_directories:
        if not unit_directory.is_dir():
            raise ValueError(f"Unit descriptor directory not found: {unit_directory}")
    if not sensor_directory.is_dir():
        raise ValueError(f"Sensor descriptor directory not found: {sensor_directory}")

    sensors: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    sensor_errors: list[str] = []
    for path in sorted(sensor_directory.glob("*.lua"), key=lambda item: item.name.casefold()):
        relative = path.relative_to(source_root).as_posix()
        try:
            table = LuaLiteralParser(path.read_text(encoding="utf-8-sig")).parse_assignment()
            name, profiles = sensor_descriptor_profiles(table, relative)
            sensors[name] = (relative, profiles)
        except (OSError, UnicodeError, ValueError) as exc:
            sensor_errors.append(f"{relative}: {exc}")

    profiles: list[dict[str, Any]] = []
    unit_errors: list[str] = []
    unit_count = 0
    platform_counts: dict[str, int] = {}
    for platform_category, unit_directory in unit_directories:
        platform_counts[platform_category] = 0
        for path in sorted(unit_directory.glob("*.lua"), key=lambda item: item.name.casefold()):
            relative = path.relative_to(source_root).as_posix()
            try:
                unit = LuaLiteralParser(path.read_text(encoding="utf-8-sig")).parse_assignment()
                profiles.extend(unit_sensor_profiles(unit, relative, sensors, platform_category))
                unit_count += 1
                platform_counts[platform_category] += 1
            except (OSError, UnicodeError, ValueError) as exc:
                unit_errors.append(f"{relative}: {exc}")
    if unit_errors:
        preview = "\n".join(unit_errors[:10])
        raise ValueError(f"Could not import {len(unit_errors)} unit descriptor(s):\n{preview}")

    combined: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for profile in profiles:
        key = (
            profile["dcs_type"].casefold(),
            profile["detection_type"],
            profile["target_domain"],
            profile["mode"] or "",
        )
        previous = combined.get(key)
        if previous is None:
            combined[key] = profile
            continue
        previous_max = previous["maximum_m"] or 0
        profile_max = profile["maximum_m"] or 0
        if profile_max > previous_max:
            sensor_names = previous["sensor_names"]
            source_paths = previous["source_paths"]
            combined[key] = profile
            previous = combined[key]
            previous["sensor_names"] = sensor_names
            previous["source_paths"] = source_paths
        previous["sensor_names"] = sorted(set(previous["sensor_names"] + profile["sensor_names"]))
        previous["source_paths"] = sorted(set(previous["source_paths"] + profile["source_paths"]))
        if previous["basis"] != profile["basis"]:
            previous["basis"] = "combined"

    commit = _git_value(source_root, "rev-parse", "HEAD")
    detected_build = dcs_build or _git_value(source_root, "describe", "--tags", "--exact-match")
    return {
        "schema_version": 2,
        "source": {"url": SOURCE_URL, "commit": commit, "dcs_build": detected_build},
        "unit_descriptor_count": unit_count,
        "platform_descriptor_counts": platform_counts,
        "sensor_descriptor_count": len(sensors),
        "sensor_parse_error_count": len(sensor_errors),
        "sensor_profiles": sorted(
            combined.values(),
            key=lambda item: (
                item["dcs_type"].casefold(),
                item["detection_type"],
                item["target_domain"],
                item["mode"] or "",
            ),
        ),
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
    parser.add_argument(
        "--sensor-output",
        type=Path,
        default=Path("python/moosebridge/data/dcs_sensor_ranges.json"),
        help="Generated sensor-range JSON artifact",
    )
    args = parser.parse_args()

    artifact = build_artifact(args.source.resolve(), dcs_build=args.dcs_build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    sensor_artifact = build_sensor_artifact(args.source.resolve(), dcs_build=args.dcs_build)
    args.sensor_output.parent.mkdir(parents=True, exist_ok=True)
    args.sensor_output.write_text(json.dumps(sensor_artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(
        f"Imported {artifact['descriptor_count']} descriptors and "
        f"{len(artifact['weapon_ranges'])} exact ranges into {args.output}"
    )
    print(
        f"Imported {len(sensor_artifact['sensor_profiles'])} sensor profiles into {args.sensor_output}"
    )


if __name__ == "__main__":
    main()
