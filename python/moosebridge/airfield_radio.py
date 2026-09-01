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


def _number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _airbase_coordinates(airbase: dict) -> tuple[float, float, float, float] | None:
    values = airbase.get("x"), airbase.get("z"), airbase.get("latitude"), airbase.get("longitude")
    if all(_number(value) for value in values) and abs(values[2]) <= 90 and abs(values[3]) <= 180:
        return values
    return None


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


def airfield_radio_message(listing: AirfieldRadioListing, station: ResolvedAirfieldRadio,
                           position: Any) -> str:
    value = station.record["normalized"]
    distance, bearing = metrics(station, position)
    bearing_text = "N/A" if bearing is None else f"{round(bearing, 1) % 360:05.1f} deg TRUE"
    lines = [f"Airfield communications: {station.name}",
             f"Reference: {listing.unit_id.removeprefix('UNIT:')} | AIRBASE ID: {station.airbase_uid}",
             f"Distance: {distance / 1852:.2f} NM horizontal | Bearing: {bearing_text}"]
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
