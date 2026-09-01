"""Live AIRBASE resolution and read-only presentation of imported ATC radio data."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

from .navaid_menu import NavaidCatalog, PAGE_SIZE, _short, validate_position
from .navigation import _bearing_true


BAND_LABELS = {"UHF": "UHF", "VHF_HI": "VHF", "VHF_LOW": "VHF Low", "HF": "HF"}
BAND_ORDER = {name: index for index, name in enumerate(BAND_LABELS)}
RUNWAY_WIND_STATUSES = {"available", "calm", "unavailable", "no_runways"}


def _number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _airbase_coordinates(airbase: dict) -> tuple[float, float, float, float] | None:
    values = airbase.get("x"), airbase.get("z"), airbase.get("latitude"), airbase.get("longitude")
    if all(_number(value) for value in values) and abs(values[2]) <= 90 and abs(values[3]) <= 180:
        return values
    return None


def _validate_runways(airbase: dict) -> None:
    runways = airbase.get("runways")
    status, suggestion = airbase.get("runway_wind_status"), airbase.get("suggested_runway")
    if not isinstance(runways, list) or status not in RUNWAY_WIND_STATUSES:
        raise ValueError(f"Live AIRBASE {airbase.get('airbase_id')} has invalid runway data")
    names, directions = set(), set()
    for runway in runways:
        if not isinstance(runway, dict):
            raise ValueError("Invalid live AIRBASE runway entry")
        name = runway.get("name")
        numbers = {key: runway.get(key) for key in (
            "heading_true_deg", "heading_magnetic_deg", "length_m", "width_m", "center_x", "center_z",
        )}
        if (not isinstance(name, str) or not name or len(name) > 8
                or not all(_number(value) for value in numbers.values())
                or not 0 <= numbers["heading_true_deg"] <= 360
                or not 0 <= numbers["heading_magnetic_deg"] <= 360
                or not 1 <= numbers["length_m"] <= 20_000
                or not 1 <= numbers["width_m"] <= 1_000
                or abs(numbers["center_x"]) > 100_000_000 or abs(numbers["center_z"]) > 100_000_000
                or ("is_left" in runway and type(runway["is_left"]) is not bool)):
            raise ValueError(f"Live AIRBASE {airbase.get('airbase_id')} has invalid runway fields")
        key = (name, numbers["center_x"], numbers["center_z"])
        if key in directions:
            raise ValueError(f"Live AIRBASE {airbase.get('airbase_id')} has duplicate runway directions")
        directions.add(key)
        names.add(name)
    if status == "available":
        if not isinstance(suggestion, str) or suggestion not in names:
            raise ValueError(f"Live AIRBASE {airbase.get('airbase_id')} has an invalid runway suggestion")
    elif suggestion is not None or (status == "no_runways") != (not runways):
        raise ValueError(f"Live AIRBASE {airbase.get('airbase_id')} has inconsistent runway status")


@dataclass(frozen=True)
class ResolvedAirfieldRadio:
    record: dict
    airbase: dict

    @property
    def airbase_uid(self) -> int:
        return self.record["normalized"]["airbase_uid"]

    @property
    def name(self) -> str:
        return self.airbase.get("name") or self.airbase.get("dcs_name") or f"AIRBASE {self.airbase_uid}"


def resolve_airfield_radios(catalog: NavaidCatalog, airbases: Any) -> tuple[tuple[ResolvedAirfieldRadio, ...], int]:
    """Join imported radioId UIDs to live AIRBASE snapshots; never match names."""
    if not isinstance(airbases, list):
        raise ValueError("Invalid live AIRBASE response")
    live: dict[int, dict] = {}
    for item in airbases:
        if not isinstance(item, dict) or type(item.get("airbase_id")) is not int:
            raise ValueError("Invalid live AIRBASE entry")
        uid = item["airbase_id"]
        if uid in live:
            raise ValueError(f"Live AIRBASE ID is ambiguous: {uid}")
        if _airbase_coordinates(item) is None or type(item.get("name")) is not str or not item["name"]:
            raise ValueError(f"Live AIRBASE {uid} has no usable name or coordinates")
        _validate_runways(item)
        live[uid] = item
    result, unresolved = [], 0
    for record in catalog.radio_records:
        uid = record.get("normalized", {}).get("airbase_uid")
        if type(uid) is not int or uid not in live:
            unresolved += 1
            continue
        result.append(ResolvedAirfieldRadio(record, live[uid]))
    return tuple(result), unresolved


def metrics(station: ResolvedAirfieldRadio, position: Any) -> tuple[float, float | None]:
    validate_position(position)
    x, z, latitude, longitude = _airbase_coordinates(station.airbase)
    return (math.hypot(position.x - x, position.z - z),
            _bearing_true(position.latitude, position.longitude, latitude, longitude))


@dataclass
class AirfieldRadioListing:
    catalog: NavaidCatalog
    unit_id: str
    stations: tuple[ResolvedAirfieldRadio, ...]
    position: Any
    unresolved: int
    revision: int = 0
    page: int = 0

    def __post_init__(self) -> None:
        validate_position(self.position)
        self.stations = tuple(sorted(self.stations,
                                     key=lambda item: (metrics(item, self.position)[0],
                                                       item.record["source_index"])))

    @property
    def pages(self) -> int:
        return max(1, math.ceil(len(self.stations) / PAGE_SIZE))

    def page_items(self, page: int) -> list[dict[str, str]]:
        if type(page) is not int or not 0 <= page < self.pages:
            raise ValueError("Airfield page is outside this list; use Refresh nearby.")
        result = []
        selected = self.stations[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        for rank, station in enumerate(selected, page * PAGE_SIZE + 1):
            record = station.record
            flagged = record.get("validation_status") != "no_issues" or self.catalog.radio_issues
            flag = "[!] " if flagged else ""
            distance, _ = metrics(station, self.position)
            label = f"{rank}. {flag}{station.name} ({distance / 1852:.1f} NM)"
            result.append({"key": str(record["source_index"]), "label": _short(label)})
        return result

    def selected(self, key: str) -> ResolvedAirfieldRadio:
        if type(key) is not str:
            raise ValueError("Invalid airfield selection")
        for station in self.stations[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]:
            if str(station.record["source_index"]) == key:
                return station
        raise ValueError("Airfield is not on this page; use Refresh nearby.")


def _frequency_text(item: dict) -> str:
    frequency = item["frequency_hz"] / 1_000_000
    modulation = re.sub(r"^MODULATIONTYPE_", "", item["modulation_symbol"])
    return f"{BAND_LABELS[item['band_symbol']]}: {frequency:g} MHz {modulation}"


def _runway_lines(airbase: dict) -> list[str]:
    physical: dict[tuple[float, float, float, float], list[dict]] = {}
    for runway in airbase["runways"]:
        key = (round(runway["center_x"], 1), round(runway["center_z"], 1),
               round(runway["length_m"], 1), round(runway["width_m"], 1))
        physical.setdefault(key, []).append(runway)
    lines = ["Runways:"]
    if not physical:
        lines.append("  N/A from live MOOSE AIRBASE")
    for (_, _, length, width), directions in sorted(
            physical.items(), key=lambda item: min(runway["name"] for runway in item[1])):
        names = sorted({runway["name"] for runway in directions},
                       key=lambda value: (int(value[:2]) if value[:2].isdigit() else 99, value))
        lines.append(f"  {'/'.join(names)} - {length:,.0f} x {width:,.0f} m")
    status, suggestion = airbase["runway_wind_status"], airbase.get("suggested_runway")
    if status == "available":
        lines.append(f"Suggested into-wind runway: {suggestion} (MOOSE wind calculation)")
    elif status == "calm":
        lines.append("Suggested into-wind runway: N/A (calm wind)")
    elif status == "no_runways":
        lines.append("Suggested into-wind runway: N/A (no runway data)")
    else:
        lines.append("Suggested into-wind runway: N/A (wind unavailable)")
    lines.append("Runway suggestion is advisory, not a DCS ATC clearance.")
    return lines


def airfield_radio_message(listing: AirfieldRadioListing, station: ResolvedAirfieldRadio,
                           position: Any) -> str:
    value = station.record["normalized"]
    distance, bearing = metrics(station, position)
    bearing_text = "N/A" if bearing is None else f"{round(bearing, 1) % 360:05.1f} deg TRUE"
    lines = [f"Airfield communications: {station.name}",
             f"Reference: {listing.unit_id.removeprefix('UNIT:')} | AIRBASE ID: {station.airbase_uid}",
             f"Distance: {distance / 1852:.2f} NM horizontal | Bearing: {bearing_text}"]
    lines.extend(_runway_lines(station.airbase))
    callsigns = [f"{item['variant'].title()} {item['name']}" for item in value.get("callsigns", [])]
    lines.append("Callsigns: " + (" | ".join(callsigns) if callsigns else "N/A"))
    roles = [role.title() for role in value.get("roles", [])]
    lines.append("ATC roles: " + (", ".join(roles) if roles else "N/A"))
    frequencies = sorted(value.get("frequencies", []),
                         key=lambda item: BAND_ORDER.get(item.get("band_symbol"), 99))
    lines.extend(_frequency_text(item) for item in frequencies)
    if not frequencies:
        lines.append("ATC frequencies: N/A in the terrain source")
    codes = sorted({issue["code"] for issue in station.record.get("issues", [])
                    + list(listing.catalog.radio_issues)})
    if codes:
        lines.append("DATA " + ("INVALID" if station.record.get("validation_status") == "invalid" else "REVIEW")
                     + ": " + ", ".join(codes) + ".")
    lines.append(f"Catalog: {listing.catalog.theater_id}, {listing.catalog.snapshot_id[:12]} "
                 "(pinned; AIRBASE resolved live by ID).")
    lines.append("Frequencies are shared ATC alternatives, not role-specific assignments. Cockpit unchanged.")
    return "\n".join(lines)
