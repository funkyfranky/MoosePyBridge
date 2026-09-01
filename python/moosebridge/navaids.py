"""Read-only DCS navaid/airfield-radio import and conservative local snapshots.

This is an offline data audit, not a receiver simulation or navigation clearance.
Only generated cache/report files are written; DCS Lua is never executed.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
import unicodedata
from uuid import uuid4

from ._lua_data import Expression, LuaDataError, Reader, Symbol, json_value


SCHEMA_VERSION = 2
IMPORTER_VERSION = "3"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
KNOWN_FIELDS = {"display_name", "beaconId", "type", "callsign", "frequency", "channel",
                "channelMode", "position", "direction", "positionGeo", "sceneObjects", "chartOffsetX"}
KNOWN_RADIO_FIELDS = {"radioId", "role", "callsign", "frequency", "sceneObjects"}
RADIO_BANDS = ("HF", "VHF_LOW", "VHF_HI", "UHF")
RADIO_MODULATIONS = ("MODULATIONTYPE_AM", "MODULATIONTYPE_FM", "MODULATIONTYPE_AMFM",
                     "MODULATIONTYPE_DISCARD")
RADIO_DIRECTORY = Path("Scripts/World/Radio")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _issue(issues: list, severity: str, code: str, message: str, **context: Any) -> None:
    issues.append({"severity": severity, "code": code, "message": message, **context})


def _finite(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _literal_assignments(reader: Reader, prefix: str) -> dict[str, int]:
    names = {t.text for i, t in enumerate(reader.tokens[:-1]) if t.kind == "name"
             and t.text.startswith(prefix) and reader.tokens[i + 1].text == "="}
    result = {}
    for name in sorted(names):
        value = reader.assignment(name)
        if type(value) is not int:
            raise LuaDataError(f"Definition {name} is not an integer literal")
        result[name] = value
    return result


def read_definitions(types_source: str, sites_source: str) -> dict[str, Any]:
    """Read declarations only; legacy conversion functions are not executed."""
    types, sites = Reader(types_source), Reader(sites_source)
    type_codes = _literal_assignments(types, "BEACON_TYPE_")
    if not type_codes:
        raise LuaDataError("No beacon type definitions found")
    names = sites.assignment("SystemName")
    defaults = sites.assignment("default_systems")
    children = sites.assignment("default_child_systems")
    systems = sites.assignment("beacon_system")
    pairs = types.assignment("ILSchannelsPairs")
    if not all(isinstance(value, dict) for value in (names, defaults, children, systems, pairs)):
        raise LuaDataError("Radio definition tables are incomplete")
    if not names or not systems or not pairs:
        raise LuaDataError("Required radio definition tables are empty")
    for mapping in (defaults, children):
        if not all(isinstance(value, dict) and isinstance(value.get("system"), Symbol)
                   for value in mapping.values()):
            raise LuaDataError("Invalid default system mapping")
    if not all(isinstance(value, dict) and all(_finite(value.get(i)) for i in (1, 2)) for value in pairs.values()):
        raise LuaDataError("Invalid ILS channel-pair declaration")
    signals = {}
    for symbol, system in systems.items():
        if not isinstance(system, dict) or not isinstance(system.get("devices"), dict):
            raise LuaDataError(f"Invalid system declaration: {symbol}")
        declared = set()
        complete = True
        for device in system["devices"].values():
            value = device.get("signals") if isinstance(device, dict) else None
            if isinstance(value, (Symbol, Expression)) and re.fullmatch(
                r"SIGNAL_\w+(?:\s*\+\s*SIGNAL_\w+)*", value,
            ):
                declared.update(re.findall(r"SIGNAL_\w+", value))
            elif value != 0:
                complete = False
        signals[str(symbol)] = {"declared_signals": sorted(declared), "complete": complete}
    return {
        "type_codes": type_codes,
        "states": {key: value for key, value in _literal_assignments(types, "BEACON_").items()
                   if not key.startswith("BEACON_TYPE_")},
        "system_names": json_value(names), "default_systems": json_value(defaults),
        "default_child_systems": json_value(children), "systems": json_value(systems),
        "system_signals": signals, "ils_channel_pairs_mhz": json_value(pairs),
        "interpretation": "Static declarations only; no Lua functions executed and no live reception verified.",
    }


def read_radio_definitions(bands_source: str, modulations_source: str) -> dict[str, dict[str, int]]:
    """Read the symbolic band/modulation constants used by terrain radio tables."""
    bands, modulations = Reader(bands_source), Reader(modulations_source)
    result = {
        "bands": {name: bands.assignment(name) for name in RADIO_BANDS},
        "modulations": {name: modulations.assignment(name) for name in RADIO_MODULATIONS},
    }
    if any(type(value) is not int for values in result.values() for value in values.values()):
        raise LuaDataError("Radio band/modulation definitions must be integer literals")
    if any(len(set(values.values())) != len(values) for values in result.values()):
        raise LuaDataError("Radio band/modulation definitions contain duplicate numeric values")
    return result


def _radio_callsigns(value: Any, issues: list[dict]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if not isinstance(value, dict) or set(value) != set(range(1, len(value) + 1)):
        _issue(issues, "warning", "invalid_radio_callsigns", "Expected a contiguous radio callsign array.", field="callsign")
        return result
    for item in value.values():
        if not isinstance(item, dict):
            _issue(issues, "warning", "invalid_radio_callsigns", "A callsign variant is not a table.", field="callsign")
            continue
        for variant, pair in item.items():
            if (type(variant) is not str or not variant or not isinstance(pair, dict)
                    or set(pair) != {1, 2} or not all(type(pair.get(i)) is str and pair[i] for i in (1, 2))):
                _issue(issues, "warning", "invalid_radio_callsigns", "A callsign variant is malformed.", field="callsign")
                continue
            result.append({"variant": variant, "translation_key": pair[1], "name": pair[2]})
    if not result:
        _issue(issues, "warning", "missing_radio_callsign", "No usable ATC callsign is available.", field="callsign")
    return result


def _radio_record(raw: dict, index: int, reader: Reader, definitions: dict) -> dict:
    issues: list[dict] = []
    radio_id = raw.get("radioId")
    if type(radio_id) is not str or not radio_id:
        _issue(issues, "error", "missing_radio_id", "radioId is missing, empty or not a string.", field="radioId")
        radio_id = None
    match = re.fullmatch(r"airfield(\d+)_\d+", radio_id or "")
    airbase_uid = int(match.group(1)) if match else None
    if radio_id and airbase_uid is None:
        _issue(issues, "warning", "unresolvable_radio_id",
               "radioId does not contain an AIRBASE UID; no name-based match is attempted.", field="radioId")

    roles, raw_roles = [], raw.get("role")
    if isinstance(raw_roles, dict) and set(raw_roles) == set(range(1, len(raw_roles) + 1)):
        roles = [value for value in raw_roles.values() if type(value) is str and value]
    if not roles or not isinstance(raw_roles, dict) or len(roles) != len(raw_roles):
        _issue(issues, "warning", "invalid_radio_roles", "ATC roles are missing or malformed.", field="role")
    for role in roles:
        if role not in {"ground", "tower", "approach"}:
            _issue(issues, "info", "unknown_radio_role", f"Additional ATC role preserved: {role}", field="role")

    callsigns = _radio_callsigns(raw.get("callsign"), issues)
    frequencies, raw_frequencies = [], raw.get("frequency")
    if not isinstance(raw_frequencies, dict):
        _issue(issues, "warning", "invalid_radio_frequencies", "Expected a frequency table.", field="frequency")
    else:
        for raw_band, pair in raw_frequencies.items():
            band = str(raw_band) if isinstance(raw_band, Symbol) else raw_band if type(raw_band) is str else None
            if band not in definitions["bands"]:
                _issue(issues, "warning", "unknown_frequency_band", f"Unknown frequency band preserved: {band!s}", field="frequency")
                continue
            if not isinstance(pair, dict) or set(pair) != {1, 2}:
                _issue(issues, "warning", "invalid_radio_frequency", f"{band} does not contain modulation and frequency.", field="frequency")
                continue
            modulation = str(pair[1]) if isinstance(pair[1], Symbol) else None
            frequency = pair[2]
            if modulation not in definitions["modulations"] or not _finite(frequency) or frequency <= 0:
                _issue(issues, "warning", "invalid_radio_frequency", f"{band} has an unknown modulation or invalid frequency.", field="frequency")
                continue
            frequencies.append({"band_symbol": band, "band_code": definitions["bands"][band],
                                "modulation_symbol": modulation,
                                "modulation_code": definitions["modulations"][modulation],
                                "frequency_hz": frequency})
    if not frequencies:
        _issue(issues, "warning", "missing_radio_frequencies", "No usable ATC frequency is available.", field="frequency")

    for name in sorted(set(raw).difference(KNOWN_RADIO_FIELDS), key=str):
        _issue(issues, "info", "unknown_radio_field", f"Additional radio field preserved without interpretation: {name}")
    start, end = reader.table_spans[id(raw)]
    severities = {issue["severity"] for issue in issues}
    return {
        "source_index": index,
        "source_line": reader.source.count("\n", 0, start) + 1,
        "raw_fields": json_value(raw),
        "raw_lua": reader.source[start:end],
        "normalized": {"radio_id": radio_id, "airbase_uid": airbase_uid, "roles": roles,
                       "callsigns": callsigns, "frequencies": frequencies, "live_verified": False},
        "issues": issues,
        "validation_status": "invalid" if "error" in severities else "review" if severities else "no_issues",
    }


def read_airfield_radios(source: str, definitions: dict) -> dict:
    """Read a terrain radio.lua table without executing Lua."""
    reader = Reader(source)
    version = reader.assignment("radioTableFormat")
    if type(version) is not int or version != 3:
        raise LuaDataError(f"Unsupported radioTableFormat: {version}")
    data = reader.assignment("radio", terminal=True)
    if not isinstance(data, dict) or set(data) != set(range(1, len(data) + 1)):
        raise LuaDataError("Expected a contiguous array of airfield radio records")
    if not all(isinstance(raw, dict) for raw in data.values()):
        raise LuaDataError("Each airfield radio record must be a table")
    records = [_radio_record(raw, index, reader, definitions) for index, raw in sorted(data.items())]
    by_id, by_uid = defaultdict(list), defaultdict(list)
    for record in records:
        normal = record["normalized"]
        if normal["radio_id"]:
            by_id[normal["radio_id"]].append(record)
        if normal["airbase_uid"] is not None:
            by_uid[normal["airbase_uid"]].append(record)
    for name, group in by_id.items():
        if len(group) > 1:
            for record in group:
                _issue(record["issues"], "error", "duplicate_radio_id", f"radioId occurs {len(group)} times: {name}")
                record["validation_status"] = "invalid"
    for uid, group in by_uid.items():
        if len(group) > 1:
            for record in group:
                _issue(record["issues"], "warning", "duplicate_airbase_uid",
                       f"AIRBASE UID {uid} occurs in {len(group)} radio records; records were not merged.")
                if record["validation_status"] == "no_issues":
                    record["validation_status"] = "review"
    return {"format": version, "record_count": len(records), "records": records, "issues": []}


def _paired_channel(frequency: float) -> tuple[int, str] | None:
    # Explicit importer rule for VHF pairings; do not invoke DCS helper code.
    ranges = ((108000000, 112250000, 17), (112300000, 117950000, 70),
              (133300000, 134250000, 60), (134400000, 135950000, 1))
    for low, high, first in ranges:
        if low <= frequency <= high:
            steps = (frequency - low) / 50000
            if abs(steps - round(steps)) < 1e-6:
                return first + round(steps) // 2, "Y" if round(steps) % 2 else "X"
    return None


def _frequency_role(kind: str | None, frequency: float, definitions: dict) -> str:
    if kind and "HOMER" in kind and 10000 <= frequency <= 2000000:
        return "homing_tuning"
    if kind in {"BEACON_TYPE_ILS_LOCALIZER", "BEACON_TYPE_ILS_GLIDESLOPE"}:
        pairs = definitions["ils_channel_pairs_mhz"].values()
        if any(abs(frequency - pair["1"] * 1e6) < 1 for pair in pairs):
            return "ils_localizer_tuning"
        if kind.endswith("GLIDESLOPE") and any(
            abs(frequency - pair["2"] * 1e6) < 1 for pair in definitions["ils_channel_pairs_mhz"].values()
        ):
            return "ils_glideslope_carrier"
        return "unclassified"
    if kind in {"BEACON_TYPE_VOR", "BEACON_TYPE_VOR_DME", "BEACON_TYPE_VORTAC",
                "BEACON_TYPE_DME", "BEACON_TYPE_TACAN"}:
        if _paired_channel(frequency):
            return "vhf_paired_tuning"
        if kind in {"BEACON_TYPE_DME", "BEACON_TYPE_TACAN"} and 962000000 <= frequency <= 1213000000:
            return "uhf_dme_tacan"
        return "unclassified"
    return "unclassified"


def _record(raw: dict, index: int, reader: Reader, definitions: dict) -> dict:
    issues: list[dict] = []
    normalized: dict[str, Any] = {"live_verified": False}
    for source, dest in (("beaconId", "beacon_id"), ("display_name", "display_name"), ("callsign", "callsign")):
        value = raw.get(source)
        normalized[dest] = value if type(value) is str else None
        if type(value) is not str or not value.strip():
            _issue(issues, "error" if source == "beaconId" else "warning", "missing_" + dest,
                   f"{source} is missing, empty or not a string.", field=source)
    raw_type = raw.get("type")
    kind = str(raw_type) if isinstance(raw_type, Symbol) else next(
        (key for key, value in definitions["type_codes"].items() if type(raw_type) is int and value == raw_type), None,
    )
    normalized.update(type_symbol=kind, type_code=definitions["type_codes"].get(kind))
    if normalized["type_code"] is None:
        _issue(issues, "error", "unknown_type", f"Beacon type is not defined: {raw_type!s}", field="type")
    default = definitions["default_systems"].get(kind, {})
    system = default.get("system", {}).get("lua_symbol")
    signal_info = definitions["system_signals"].get(system, {})
    normalized["default_system"] = system
    normalized["declared_signals"] = signal_info.get("declared_signals", [])
    if not signal_info.get("complete"):
        _issue(issues, "info", "system_capabilities_unconfirmed", "No complete default signal declaration; do not infer receiver capabilities.")

    for name in ("frequency", "channel", "direction"):
        value = raw.get(name)
        normalized[{"frequency": "frequency_hz", "direction": "direction_raw_deg"}.get(name, name)] = value if _finite(value) else None
        if value is not None and not _finite(value):
            _issue(issues, "warning", "non_numeric_" + name, f"{name} is not a finite numeric literal.", field=name)
    frequency, channel = normalized["frequency_hz"], normalized["channel"]
    role = _frequency_role(kind, frequency, definitions) if frequency is not None and frequency > 0 else None
    normalized["frequency_role"] = role
    if frequency is not None and (frequency <= 0 or role == "unclassified"):
        _issue(issues, "warning", "unclassified_frequency", "Frequency cannot be safely interpreted for this type; retain raw value.", field="frequency")
    if frequency is None and channel is None:
        _issue(issues, "error", "missing_tuning", "Neither a numeric frequency nor a channel is available.")
    if channel is not None and (channel < 1 or channel != int(channel)):
        _issue(issues, "warning", "invalid_or_unused_channel", "Channel is non-positive or non-integral; it may be an unused placeholder.", field="channel")
    if kind in {"BEACON_TYPE_TACAN", "BEACON_TYPE_DME", "BEACON_TYPE_VORTAC", "BEACON_TYPE_VOR_DME"}:
        if channel is not None and channel > 126:
            _issue(issues, "warning", "channel_out_of_range", "DME/TACAN channel exceeds 126.", field="channel")
        paired = _paired_channel(frequency) if frequency is not None and role == "vhf_paired_tuning" else None
        if paired and channel is not None and channel > 0 and paired[0] != channel:
            _issue(issues, "warning", "frequency_channel_conflict",
                   f"VHF pairing suggests {paired[0]}{paired[1]}, but channel is {channel}; neither value was replaced.")
    mode = raw.get("channelMode")
    normalized["channel_mode"] = mode if type(mode) is str and mode in {"X", "Y"} else None
    normalized["channel_mode_source"] = "explicit" if normalized["channel_mode"] else None
    if mode is not None and normalized["channel_mode"] is None:
        _issue(issues, "warning", "unknown_channel_mode", "Channel mode is not X or Y.", field="channelMode")
    if channel and normalized["channel_mode"] is None:
        modes = [candidate for candidate in ("X", "Y") if "SIGNAL_TACAN_" + candidate in normalized["declared_signals"]]
        if len(modes) == 1 and signal_info.get("complete"):
            normalized["channel_mode"], normalized["channel_mode_source"] = modes[0], "default_system_declaration"
    if role == "vhf_paired_tuning" and normalized["channel_mode"]:
        paired = _paired_channel(frequency)
        if paired and paired[1] != normalized["channel_mode"]:
            _issue(issues, "warning", "frequency_mode_conflict", "Paired frequency and declared/default channel mode disagree; no correction applied.")
    if role == "uhf_dme_tacan" and channel is not None and 1 <= channel <= 126 and channel == int(channel):
        modes = [normalized["channel_mode"]] if normalized["channel_mode"] else ["X", "Y"]
        expected = [((961 if channel < 64 else 1087) if mode == "X" else
                     (1087 if channel < 64 else 961)) + channel for mode in modes]
        if not any(abs(frequency - value * 1e6) < 1 for value in expected):
            _issue(issues, "warning", "frequency_channel_conflict", "UHF frequency and channel/mode disagree; no correction applied.")

    position, geo = raw.get("position"), raw.get("positionGeo")
    normalized["position_m"] = None
    normalized["position_geo_deg"] = None
    if isinstance(position, dict) and all(_finite(position.get(i)) for i in (1, 2, 3)):
        normalized["position_m"] = dict(zip(("x", "y", "z"), (position[i] for i in (1, 2, 3))))
    else:
        _issue(issues, "error", "invalid_position", "Expected a finite DCS {x, y, z} position.")
    if (isinstance(geo, dict) and all(_finite(geo.get(key)) for key in ("latitude", "longitude"))
            and abs(geo["latitude"]) <= 90 and abs(geo["longitude"]) <= 180):
        normalized["position_geo_deg"] = {key: geo[key] for key in ("latitude", "longitude")}
    else:
        _issue(issues, "error", "invalid_geographic_position", "Latitude/longitude are missing or outside valid bounds.")
    # No grid-to-true/magnetic conversion, altitude fallback or chart offset is applied.
    for name in sorted(set(raw).difference(KNOWN_FIELDS), key=str):
        _issue(issues, "info", "unknown_field", f"Additional field preserved without interpretation: {name}")
    callsign = normalized["callsign"]
    if callsign and any(ord(char) > 127 for char in callsign):
        _issue(issues, "warning", "non_ascii_callsign", "Callsign contains non-ASCII characters; original spelling is preserved.")
    start, end = reader.table_spans[id(raw)]
    return {"source_index": index, "source_line": reader.source.count("\n", 0, start) + 1,
            "raw_fields": json_value(raw), "raw_lua": reader.source[start:end],
            "normalized": normalized, "issues": issues}


def read_beacons(source: str, definitions: dict) -> dict:
    reader = Reader(source)
    version = reader.assignment("beaconsTableFormat")
    if type(version) is not int or version != 2:
        raise LuaDataError(f"Unsupported beaconsTableFormat: {version}")
    data = reader.assignment("beacons", terminal=True)
    if not isinstance(data, dict) or set(data) != set(range(1, len(data) + 1)):
        raise LuaDataError("Expected a contiguous array of beacon records")
    if not all(isinstance(raw, dict) for raw in data.values()):
        raise LuaDataError("Each beacon record must be a table")
    records = [_record(raw, index, reader, definitions) for index, raw in sorted(data.items())]
    issues: list[dict] = []
    ids, sites, similar = defaultdict(list), defaultdict(list), defaultdict(list)
    # Only flag lookalikes; never use this skeleton to merge or rewrite identifiers.
    lookalikes = str.maketrans("АВСЕНІЈКМОРЅТХаеорсух", "ABCEHIJKMOPSTXaeopcyx")
    for record in records:
        value = record["normalized"]
        if value["beacon_id"]:
            ids[value["beacon_id"]].append(record)
        callsign = value["callsign"]
        if callsign:
            similar[unicodedata.normalize("NFKC", callsign).translate(lookalikes).casefold()].append(record)
        match = re.fullmatch(r"(airfield\d+)_\d+", value["beacon_id"] or "")
        if match and value["type_symbol"] in {"BEACON_TYPE_ILS_LOCALIZER", "BEACON_TYPE_ILS_GLIDESLOPE"}:
            sites[match[1]].append(record)
    for name, group in ids.items():
        if len(group) > 1:
            for record in group:
                _issue(record["issues"], "error", "duplicate_beacon_id", f"Beacon ID occurs {len(group)} times: {name}")
    for group in similar.values():
        names = sorted({record["normalized"]["callsign"] for record in group})
        if len(names) > 1 and any(any(ord(char) > 127 for char in name) for name in names):
            _issue(issues, "warning", "confusable_callsigns", "Visually similar callsigns are distinct: " + ", ".join(names))
    for site, group in sites.items():
        counts = Counter(record["normalized"]["type_symbol"] for record in group)
        loc, gs = counts["BEACON_TYPE_ILS_LOCALIZER"], counts["BEACON_TYPE_ILS_GLIDESLOPE"]
        if loc != gs:
            _issue(issues, "warning", "ils_component_imbalance",
                   f"{site}: {loc} localizer and {gs} glideslope entries; no automatic pairing or repair.")
    for record in records:
        severities = {issue["severity"] for issue in record["issues"]}
        record["validation_status"] = "invalid" if "error" in severities else "review" if severities else "no_issues"
    return {"format": version, "record_count": len(records), "records": records, "issues": issues}


def _discover(root: Path) -> tuple[list[dict], dict[str, bytes]]:
    terrain_root = root / "Mods/terrains"
    if not root.is_dir() or not terrain_root.is_dir():
        raise ValueError(f"DCS terrain directory not found: {terrain_root}")
    paths = [root / RADIO_DIRECTORY / "BeaconTypes.lua", root / RADIO_DIRECTORY / "BeaconSites.lua",
             root / RADIO_DIRECTORY / "FrequencyBands.lua", root / RADIO_DIRECTORY / "ModulationTypes.lua"]
    # Hash this imported dependency too, although no wsTypes code is executed.
    if (root / "Scripts/Database/wsTypes.lua").is_file():
        paths.append(root / "Scripts/Database/wsTypes.lua")
    maps = []
    for folder in sorted(terrain_root.iterdir(), key=lambda p: p.name.casefold()):
        if not folder.is_dir():
            continue
        beacons = [p for p in folder.iterdir() if p.name.casefold() == "beacons.lua" and p.is_file()]
        radios = [p for p in folder.iterdir() if p.name.casefold() == "radio.lua" and p.is_file()]
        if not beacons:
            continue
        if len(beacons) != 1:
            raise ValueError(f"Ambiguous beacon files in {folder}")
        if len(radios) != 1:
            raise ValueError(f"Expected exactly one terrain radio.lua in {folder}, found {len(radios)}")
        entry = next((p for p in folder.iterdir() if p.name.casefold() == "entry.lua" and p.is_file()), None)
        paths.extend(beacons + radios)
        if entry:
            paths.append(entry)
        maps.append({"folder": folder.name, "source": beacons[0].relative_to(root).as_posix(),
                     "radio_source": radios[0].relative_to(root).as_posix(),
                     "entry_source": entry.relative_to(root).as_posix() if entry else None})
    if not maps:
        raise ValueError("No terrain Beacon files found; refusing to publish an empty installation inventory")
    sources = {}
    for path in sorted(paths):
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Source resolves outside the selected DCS installation: {path}")
        with path.open("rb") as stream:
            content = stream.read(MAX_SOURCE_BYTES + 1)
        if len(content) > MAX_SOURCE_BYTES:
            raise ValueError(f"Source exceeds size limit: {path}")
        sources[path.relative_to(root).as_posix()] = content
    return maps, sources


def _text(sources: dict[str, bytes], path: str) -> str:
    return sources[path].decode("utf-8-sig", errors="strict")


def _terrain_radio_text(sources: dict[str, bytes], path: str) -> tuple[str, str]:
    """DCS includes legacy terrain radio tables encoded as Windows-1251."""
    try:
        return sources[path].decode("utf-8-sig", errors="strict"), "utf-8"
    except UnicodeDecodeError:
        return sources[path].decode("windows-1251", errors="strict"), "windows-1251"


def _all_issues(catalog: dict) -> list[dict]:
    return (catalog.get("issues", []) + catalog.get("radio_issues", [])
            + [issue for record in catalog.get("records", []) for issue in record["issues"]]
            + [issue for record in catalog.get("radio_records", []) for issue in record["issues"]])


def render_report(result: dict) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    lines = ["# DCS Navigation Data Import Report", "", f"Status: {result['status']}",
             f"Installation: {result['installation']}", f"Snapshot: {result['snapshot_id']}",
             f"Generated: {result['generated_at']}", "",
             "Offline static-data audit only. Not a live reception check or an aircraft-compatibility guarantee.",
             "Raw values are preserved. Warnings are not automatic corrections. Empty tables are valid.", "",
             "| Terrain folder | Terrain ID | Navaids | Airfield radios | Errors | Warnings | Import |",
             "|---|---|---:|---:|---:|---:|---|"]
    for catalog in result["maps"]:
        counts = Counter(issue["severity"] for issue in _all_issues(catalog))
        lines.append(f"| {cell(catalog['folder'])} | {cell(catalog.get('terrain_id') or 'unknown')} | "
                     f"{catalog.get('record_count', 0)} | {catalog.get('radio_record_count', 0)} | "
                     f"{counts['error']} | {counts['warning']} | {catalog['status']} |")
    for issue in result.get("issues", []):
        lines.extend(["", f"- {issue['severity'].upper()} [{issue['code']}]: {cell(issue['message'])}"])
    for catalog in result["maps"]:
        lines.extend(["", "## " + cell(catalog["folder"]), "", "Source: " + cell(catalog["source"])])
        kinds = Counter(record["normalized"]["type_symbol"] or "UNKNOWN" for record in catalog.get("records", []))
        lines.extend(["", "Types: " + (", ".join(f"{kind}={count}" for kind, count in sorted(kinds.items())) or "none"), ""])
        for issue in catalog.get("issues", []):
            lines.append(f"- {issue['severity'].upper()} [{issue['code']}]: {cell(issue['message'])}")
        for record in catalog.get("records", []):
            for issue in record["issues"]:
                lines.append(f"- {issue['severity'].upper()} [{issue['code']}] "
                             f"{cell(record['normalized']['beacon_id'] or record['source_index'])} "
                             f"(line {record['source_line']}): {cell(issue['message'])}")
        lines.extend(["", "Airfield radio source: " + cell(catalog.get("radio_source") or "missing"), ""])
        for issue in catalog.get("radio_issues", []):
            lines.append(f"- {issue['severity'].upper()} [{issue['code']}]: {cell(issue['message'])}")
        for record in catalog.get("radio_records", []):
            for issue in record["issues"]:
                lines.append(f"- {issue['severity'].upper()} [{issue['code']}] "
                             f"{cell(record['normalized']['radio_id'] or record['source_index'])} "
                             f"(line {record['source_line']}): {cell(issue['message'])}")
    lines.extend(["", "## Interpretation limits", "",
                  "- Frequency meaning depends on type: a VHF paired tuning frequency is not a UHF carrier.",
                  "- Channel modes derived from default systems are labeled; they are not live-verified.",
                  "- Raw direction is not a validated TRUE or magnetic course. Chart offsets are not applied.",
                  "- IDs are scoped to this terrain/source snapshot, not assumed stable across updates.",
                  "- Airfield frequencies are shared ATC alternatives; radio.lua does not assign one to each role.",
                  "- AIRBASE UIDs are resolved against live MOOSE AIRBASE:GetID() values after mission start.",
                  "- No Navigraph replacement, local override, cockpit write or mission-beacon discovery is performed.",
                  "- A completed import may contain record errors. Unsupported files do not replace the current snapshot.", ""])
    return "\n".join(lines)


def _atomic_json(path: Path, data: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".navaids-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(_json_bytes(data))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _cached(snapshot: Path, fingerprint: dict) -> dict | None:
    try:
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        if manifest["fingerprint"] != fingerprint or manifest["status"] != "completed":
            return None
        for name, expected in manifest["artifacts"].items():
            candidate = (snapshot / name).resolve()
            if not candidate.is_relative_to(snapshot.resolve()) or _digest(candidate.read_bytes()) != expected:
                return None
        required = {"report.md", "definitions.json", "radio_definitions.json"} | {
            item["file"] for item in manifest["maps"]
        }
        if not required.issubset(manifest["artifacts"]) or not manifest["maps"]:
            return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def import_installation(dcs_root: str | Path, output_root: str | Path) -> dict:
    """Audit installed terrain files and publish an immutable local snapshot.

    Reuse requires matching source and artifact hashes. Parse failure produces a
    report but never replaces current.json. No automatic stale fallback is used.
    """
    root, output = Path(dcs_root).resolve(), Path(output_root).resolve()
    if output == root or output.is_relative_to(root):
        raise ValueError("Output directory must be outside the DCS installation")
    maps, sources = _discover(root)
    fingerprint = {"schema_version": SCHEMA_VERSION, "importer_version": IMPORTER_VERSION,
                   "installation": str(root), "sources": {name: _digest(data) for name, data in sources.items()}}
    snapshot_id = _digest(_json_bytes(fingerprint))
    snapshots = output / "snapshots"
    snapshot = snapshots / snapshot_id
    try:
        pointer = json.loads((output / "current.json").read_text(encoding="utf-8"))
        candidate = pointer.get("snapshot_id", "")
        if isinstance(candidate, str) and re.fullmatch(re.escape(snapshot_id) + r"(?:-\d+T\d+)?", candidate):
            snapshot = snapshots / candidate
    except (OSError, ValueError, AttributeError):
        pass
    # Do not follow cache-directory symlinks into DCS or another output tree.
    if not snapshot.resolve().is_relative_to(output) or snapshot.resolve().is_relative_to(root):
        raise ValueError("Snapshot path escapes the output directory")
    cached = _cached(snapshot, fingerprint)
    if cached:
        _, checked_sources = _discover(root)
        if {name: _digest(data) for name, data in checked_sources.items()} != fingerprint["sources"]:
            raise ValueError("DCS sources changed during cache validation; retry after the update finishes.")
        _atomic_json(output / "current.json", {"snapshot_id": snapshot.name, "status": "completed"})
        return {**cached, "reused": True, "report_path": str(snapshot / "report.md"), "snapshot_path": str(snapshot)}

    result: dict[str, Any] = {**fingerprint, "fingerprint": fingerprint, "snapshot_id": snapshot_id,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "status": "completed", "maps": [], "issues": []}
    definitions = radio_definitions = None
    try:
        definitions = read_definitions(_text(sources, (RADIO_DIRECTORY / "BeaconTypes.lua").as_posix()),
                                       _text(sources, (RADIO_DIRECTORY / "BeaconSites.lua").as_posix()))
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        result["status"] = "failed"
        _issue(result["issues"], "error", "definitions_import_failed", str(exc))
    try:
        radio_definitions = read_radio_definitions(
            _text(sources, (RADIO_DIRECTORY / "FrequencyBands.lua").as_posix()),
            _text(sources, (RADIO_DIRECTORY / "ModulationTypes.lua").as_posix()),
        )
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        result["status"] = "failed"
        _issue(result["issues"], "error", "radio_definitions_import_failed", str(exc))
    for item in maps:
        catalog = {**item, "terrain_id": None, "status": "failed", "issues": []}
        if item["entry_source"]:
            try:
                theatre = Reader(_text(sources, item["entry_source"])).assignment("theatre")
                terrain_id = theatre.get("id") if isinstance(theatre, dict) else None
                if type(terrain_id) is str and terrain_id.strip():
                    catalog["terrain_id"] = terrain_id
            except (ValueError, TypeError, RecursionError) as exc:
                _issue(catalog["issues"], "warning", "terrain_metadata_unreadable", str(exc))
        if catalog["terrain_id"] is None:
            _issue(catalog["issues"], "warning", "terrain_id_unknown", "Terrain ID was not read; folder name is not assumed to be the mission terrain ID.")
        if definitions is not None:
            try:
                parsed = read_beacons(_text(sources, item["source"]), definitions)
                parsed["issues"] = catalog["issues"] + parsed["issues"]
                catalog.update(parsed, status="completed")
            except (ValueError, TypeError, KeyError, RecursionError) as exc:
                _issue(catalog["issues"], "error", "beacons_import_failed", str(exc))
        else:
            _issue(catalog["issues"], "error", "definitions_unavailable", "Beacon normalization requires readable common definitions.")
        catalog.update(radio_format=None, radio_record_count=0, radio_records=[], radio_issues=[],
                       radio_encoding=None)
        if radio_definitions is not None:
            try:
                radio_text, encoding = _terrain_radio_text(sources, item["radio_source"])
                parsed_radio = read_airfield_radios(radio_text, radio_definitions)
                radio_issues = list(parsed_radio["issues"])
                if encoding != "utf-8":
                    _issue(radio_issues, "warning", "legacy_radio_encoding",
                           f"Terrain radio source decoded as {encoding}; raw bytes are preserved in the snapshot.")
                catalog.update(radio_format=parsed_radio["format"],
                               radio_record_count=parsed_radio["record_count"],
                               radio_records=parsed_radio["records"], radio_issues=radio_issues,
                               radio_encoding=encoding)
            except (ValueError, TypeError, KeyError, RecursionError) as exc:
                _issue(catalog["radio_issues"], "error", "airfield_radios_import_failed", str(exc))
                catalog["status"] = "failed"
        else:
            _issue(catalog["radio_issues"], "error", "radio_definitions_unavailable",
                   "Airfield radio normalization requires readable common radio definitions.")
            catalog["status"] = "failed"
        if catalog["status"] != "completed":
            result["status"] = "failed"
        result["maps"].append(catalog)

    # Catch an update while importing, including added/removed map files.
    _, current_sources = _discover(root)
    if {name: _digest(data) for name, data in current_sources.items()} != fingerprint["sources"]:
        raise ValueError("DCS sources changed during import; no snapshot published. Retry after the update finishes.")
    snapshots.mkdir(parents=True, exist_ok=True)
    # Never overwrite a corrupt or failed historical snapshot at the same hash.
    if snapshot.exists():
        snapshot = snapshots / (snapshot_id + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
    # tempfile.TemporaryDirectory deliberately creates an owner-only directory
    # on Windows.  Renaming that directory into the shared project cache keeps
    # the restrictive ACL and makes the published snapshot unreadable to the
    # normal VS Code/DCS user when the importer ran in another security context.
    # A collision-resistant mkdir below inherits the cache directory ACL.
    staging = snapshots / (".import-" + uuid4().hex)
    staging.mkdir()
    published = False
    try:
        artifacts: dict[str, str] = {}

        def write(name: str, data: bytes) -> None:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            artifacts[name] = _digest(data)

        source_files = {}
        for i, (name, data) in enumerate(sources.items()):
            local = f"sources/{i:03d}.lua"
            write(local, data)
            source_files[name] = local
        if definitions is not None:
            write("definitions.json", _json_bytes(definitions))
        if radio_definitions is not None:
            write("radio_definitions.json", _json_bytes(radio_definitions))
        summaries = []
        for i, catalog in enumerate(result["maps"]):
            filename = f"maps/{i:03d}.json"
            write(filename, _json_bytes(catalog))
            summaries.append({key: value for key, value in catalog.items()
                              if key not in {"records", "issues", "radio_records", "radio_issues"}} |
                             {"file": filename, "issue_counts": dict(Counter(issue["severity"] for issue in _all_issues(catalog)))})
        write("report.md", render_report(result).encode("utf-8"))
        manifest = {key: value for key, value in result.items() if key != "maps"} | {
            "maps": summaries, "artifacts": artifacts, "source_files": source_files,
        }
        (staging / "manifest.json").write_bytes(_json_bytes(manifest))
        os.replace(staging, snapshot)
        published = True
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)
    if result["status"] == "completed":
        _atomic_json(output / "current.json", {"snapshot_id": snapshot.name, "status": "completed"})
    return {**manifest, "reused": False, "report_path": str(snapshot / "report.md"), "snapshot_path": str(snapshot)}


def print_summary(result: dict) -> None:
    print(f"DCS navigation-data import: {result['status']} ({'cached' if result['reused'] else 'new snapshot'})")
    print("Static data only; no live reception or aircraft compatibility verified.")
    for catalog in result["maps"]:
        counts = catalog.get("issue_counts", {})
        print(f"{catalog['folder']}: {catalog.get('record_count', 0)} navaids, "
              f"{catalog.get('radio_record_count', 0)} airfield radios, "
              f"{counts.get('error', 0)} errors, {counts.get('warning', 0)} warnings; {catalog['status']}")
    print(f"Report: {result['report_path']}")
    if result["status"] != "completed":
        print("Import failed; the previous current snapshot was not replaced or silently used.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dcs-root", required=True, type=Path, help="DCS installation directory (read-only)")
    parser.add_argument("--output", required=True, type=Path, help="Local cache/report directory outside DCS")
    args = parser.parse_args(argv)
    try:
        result = import_installation(args.dcs_root, args.output)
    except (OSError, ValueError) as exc:
        print(f"DCS navigation-data import failed: {exc}")
        return 2
    print_summary(result)
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
