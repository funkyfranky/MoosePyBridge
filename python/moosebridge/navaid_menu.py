"""Mission-pinned navaid catalogs and conservative radio-menu presentation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from . import navaids
from .debug_overlay import DebugMarkupPoint
from .navigation import _bearing_true


PAGE_SIZE = 6  # + refresh + previous + next = 9; reserve the tenth for DCS back.
TYPE_LABELS = {"TACAN": "TACAN", "VOR": "VOR", "DME": "DME", "VOR_DME": "VOR/DME",
               "VORTAC": "VORTAC", "NDB": "NDB", "ILS": "ILS", "RSBN": "RSBN",
               "PRMG": "PRMG", "ICLS": "ICLS", "OTHER": "Other / unknown"}


def category(symbol: str | None) -> str:
    short = (symbol or "").removeprefix("BEACON_TYPE_")
    if short in {"TACAN", "VOR", "DME", "VOR_DME", "VORTAC", "RSBN"}:
        return short
    if short in {"HOMER", "AIRPORT_HOMER", "AIRPORT_HOMER_WITH_MARKER", "ILS_FAR_HOMER",
                 "ILS_NEAR_HOMER", "NAUTICAL_HOMER"}:
        return "NDB"
    for family in ("ILS", "PRMG", "ICLS"):
        if short in {family + "_LOCALIZER", family + "_GLIDESLOPE"}:
            return family
    return "OTHER"  # Do not turn undefined AIRPORT_TACAN into a known TACAN.


def _number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _coordinates(record: dict) -> tuple[float, float, float, float] | None:
    normal = record.get("normalized", {})
    local, geo = normal.get("position_m") or {}, normal.get("position_geo_deg") or {}
    values = local.get("x"), local.get("z"), geo.get("latitude"), geo.get("longitude")
    if all(_number(value) for value in values) and abs(values[2]) <= 90 and abs(values[3]) <= 180:
        return values
    return None


def _short(text: str, size: int = 110) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return text.encode("utf-8")[:size].decode("utf-8", errors="ignore")


@dataclass(frozen=True)
class NavaidCatalog:
    theater_id: str
    snapshot_id: str
    generated_at: str
    records: tuple[dict, ...]
    radio_records: tuple[dict, ...] = ()
    issues: tuple[dict, ...] = ()
    radio_issues: tuple[dict, ...] = ()

    def nearby(self, kind: str, position: Any) -> tuple[tuple[dict, ...], int]:
        validate_position(position)
        selected = [record for record in self.records if category(record["normalized"].get("type_symbol")) == kind]
        usable = [record for record in selected if _coordinates(record) is not None]
        usable.sort(key=lambda record: (metrics(record, position)[0], record["source_index"]))
        return tuple(usable), len(selected) - len(usable)


class NavaidCatalogProvider:
    """Verify the local snapshot and source hashes once, then pin it for this run.

    Active mission terrain is selected by exact theatre.id, not a folder-name
    guess. Local-source agreement is not proof of a remote server's map version.
    """

    def __init__(self, cache_directory: str | Path, dcs_directory: str | Path):
        self.cache_directory = Path(cache_directory).resolve()
        self.dcs_directory = Path(dcs_directory).resolve()
        self._catalogs: dict[str, NavaidCatalog] | None = None

    def get(self, theater_id: str) -> NavaidCatalog:
        if not isinstance(theater_id, str) or not theater_id:
            raise ValueError("DCS did not identify the active terrain.")
        if self._catalogs is None:
            try:
                self._load()
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError("Navaid cache unavailable or outdated. Run import_dcs_beacons.py, "
                                 f"then retry the menu refresh. Details: {exc}") from exc
        if theater_id not in self._catalogs:
            raise ValueError(f"No unambiguous navaid catalog for active terrain {theater_id}.")
        return self._catalogs[theater_id]

    def _load(self) -> None:
        pointer = json.loads((self.cache_directory / "current.json").read_text(encoding="utf-8"))
        name = pointer["snapshot_id"]
        if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{64}(?:-\d+T\d+)?", name):
            raise ValueError("Invalid snapshot reference")
        path = (self.cache_directory / "snapshots" / name).resolve()
        if not path.is_relative_to(self.cache_directory):
            raise ValueError("Snapshot path escapes the cache")
        _, sources = navaids._discover(self.dcs_directory)
        fingerprint = {"schema_version": navaids.SCHEMA_VERSION, "importer_version": navaids.IMPORTER_VERSION,
                       "installation": str(self.dcs_directory),
                       "sources": {key: hashlib.sha256(value).hexdigest() for key, value in sources.items()}}
        manifest = navaids._cached(path, fingerprint)
        if manifest is None:
            raise ValueError("Snapshot/source checksums do not match; " + self._mismatch_details(path, fingerprint))
        catalogs, duplicate = {}, set()
        for item in manifest["maps"]:
            data = json.loads((path / item["file"]).read_text(encoding="utf-8"))
            terrain = data.get("terrain_id")
            if not terrain or data.get("status") != "completed":
                continue
            records, radio_records = data["records"], data.get("radio_records", [])
            keys = [record["source_index"] for record in records]
            if any(type(key) is not int or key < 1 for key in keys) or len(set(keys)) != len(keys):
                raise ValueError("Invalid source record indexes")
            radio_keys = [record["source_index"] for record in radio_records]
            if (any(type(key) is not int or key < 1 for key in radio_keys)
                    or len(set(radio_keys)) != len(radio_keys)):
                raise ValueError("Invalid airfield radio source record indexes")
            if terrain in catalogs:
                duplicate.add(terrain)
            catalogs[terrain] = NavaidCatalog(
                terrain, manifest["snapshot_id"], manifest["generated_at"], tuple(records),
                radio_records=tuple(radio_records), issues=tuple(data.get("issues", [])),
                radio_issues=tuple(data.get("radio_issues", [])),
            )
        for terrain in duplicate:
            catalogs.pop(terrain)
        self._catalogs = catalogs

    def _mismatch_details(self, snapshot: Path, fingerprint: dict) -> str:
        """Describe a rejected snapshot without weakening validation."""
        try:
            manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            return f"manifest unreadable ({exc}); cache={self.cache_directory}; DCS={self.dcs_directory}"
        expected = manifest.get("fingerprint")
        reasons: list[str] = []
        if not isinstance(expected, dict):
            reasons.append("manifest fingerprint missing")
        else:
            for key in ("schema_version", "importer_version", "installation"):
                if expected.get(key) != fingerprint.get(key):
                    reasons.append(f"{key}={expected.get(key)!r}->{fingerprint.get(key)!r}")
            old_sources, new_sources = expected.get("sources"), fingerprint.get("sources")
            if not isinstance(old_sources, dict) or not isinstance(new_sources, dict):
                reasons.append("source fingerprint missing")
            else:
                missing = sorted(set(old_sources) - set(new_sources))
                added = sorted(set(new_sources) - set(old_sources))
                changed = sorted(key for key in set(old_sources) & set(new_sources)
                                 if old_sources[key] != new_sources[key])
                if missing:
                    reasons.append("missing sources=" + ",".join(missing[:3]))
                if added:
                    reasons.append("new sources=" + ",".join(added[:3]))
                if changed:
                    reasons.append("changed sources=" + ",".join(changed[:3]))
        artifacts = manifest.get("artifacts")
        if isinstance(artifacts, dict):
            invalid = []
            for name, digest in artifacts.items():
                try:
                    actual = hashlib.sha256((snapshot / name).read_bytes()).hexdigest()
                except OSError:
                    actual = None
                if actual != digest:
                    invalid.append(name)
            if invalid:
                reasons.append("invalid artifacts=" + ",".join(invalid[:3]))
        else:
            reasons.append("artifact index missing")
        if not reasons:
            reasons.append("manifest structure or required artifact set invalid")
        return ("; ".join(reasons) + f"; cache={self.cache_directory}; DCS={self.dcs_directory}; "
                f"module={Path(navaids.__file__).resolve()}")


@dataclass
class NavaidListing:
    catalog: NavaidCatalog
    unit_id: str
    records: tuple[dict, ...]
    position: Any
    excluded: int
    revision: int = 0
    page: int = 0

    @property
    def pages(self) -> int:
        return max(1, math.ceil(len(self.records) / PAGE_SIZE))

    def page_items(self, page: int) -> list[dict[str, str]]:
        if type(page) is not int or not 0 <= page < self.pages:
            raise ValueError("Navaid page is outside this list; use Refresh nearby.")
        items = []
        for rank, record in enumerate(self.records[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], page * PAGE_SIZE + 1):
            normal = record["normalized"]
            flag = "[!] " if record.get("validation_status") != "no_issues" or self.catalog.issues else ""
            kind = normal.get("type_symbol") or "UNKNOWN"
            component = " LOC" if kind.endswith("_LOCALIZER") else " GS" if kind.endswith("_GLIDESLOPE") else ""
            name = normal.get("display_name") or normal.get("beacon_id") or "Unnamed"
            ident = normal.get("callsign") or "---"
            distance, _ = metrics(record, self.position)
            label = f"{rank}. {flag}{ident}{component} - {name} ({distance / 1852:.1f} NM)"
            items.append({"key": str(record["source_index"]), "label": _short(label)})
        return items

    def selected(self, key: str) -> dict:
        for record in self.records[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]:
            if str(record["source_index"]) == key:
                return record
        raise ValueError("Station is not on this page; use Refresh nearby.")


@dataclass(frozen=True)
class NavaidSelection:
    """Last successfully inspected station, independent of paging and drawing."""

    catalog: NavaidCatalog
    record: dict
    unit_id: str
    selection_id: str

    def marker_point(self) -> dict[str, float]:
        coordinates = _coordinates(self.record)
        if coordinates is None:
            raise ValueError("Selected navaid coordinates are unavailable.")
        return DebugMarkupPoint(coordinates[2], coordinates[3]).to_payload()

    def marker_text(self, group_id: str) -> str:
        value = self.record["normalized"]
        flag = "[!] " if self.record.get("validation_status") != "no_issues" or self.catalog.issues else ""
        kind = (value.get("type_symbol") or "UNKNOWN").removeprefix("BEACON_TYPE_")
        ident = _short(value.get("callsign") or "---", 16)
        name = _short(value.get("display_name") or value.get("beacon_id") or "Unnamed", 40)
        lines = [f"{flag}{ident} | {name}", f"{kind} | Source data"]
        if value.get("channel") is not None:
            mode = value.get("channel_mode") or " (mode unknown)"
            suffix = " [default]" if value.get("channel_mode_source") == "default_system_declaration" else ""
            lines.append(f"Channel: {value['channel']:g}{mode}{suffix}")
        if value.get("frequency_hz") is not None:
            frequency = value["frequency_hz"]
            amount, unit = (frequency / 1000, "kHz") if frequency < 2000000 else (frequency / 1000000, "MHz")
            lines.append(f"Frequency: {amount:g} {unit}")
        lines.append(f"Group: {_short(group_id.removeprefix('GROUP:'), 28)}")
        return "\n".join(lines).encode("utf-8")[:180].decode("utf-8", errors="ignore")


def validate_position(position: Any) -> None:
    values = position.x, position.z, position.latitude, position.longitude
    if not all(_number(value) for value in values) or abs(values[2]) > 90 or abs(values[3]) > 180:
        raise ValueError("Live aircraft coordinates are unavailable.")


def metrics(record: dict, position: Any) -> tuple[float, float | None]:
    x, z, lat, lon = _coordinates(record)
    return math.hypot(position.x - x, position.z - z), _bearing_true(position.latitude, position.longitude, lat, lon)


def station_message(listing: NavaidListing, record: dict, position: Any) -> str:
    validate_position(position)
    value = record["normalized"]
    distance, bearing = metrics(record, position)
    bearing_text = "N/A" if bearing is None else f"{round(bearing, 1) % 360:05.1f} deg TRUE"
    kind = (value.get("type_symbol") or "UNKNOWN").removeprefix("BEACON_TYPE_")
    lines = [f"Navaid: {value.get('callsign') or '---'} | {value.get('display_name') or value.get('beacon_id')}",
             f"Type: {kind} | Reference: {listing.unit_id.removeprefix('UNIT:')}",
             f"Distance: {distance / 1852:.2f} NM horizontal | Bearing: {bearing_text}"]
    if value.get("channel") is not None:
        mode = value.get("channel_mode") or " (mode unknown)"
        origin = " [default system]" if value.get("channel_mode_source") == "default_system_declaration" else ""
        lines.append(f"Source channel: {value['channel']:g}{mode}{origin}")
    frequency = value.get("frequency_hz")
    if frequency is not None:
        amount, unit = (frequency / 1000, "kHz") if frequency < 2000000 else (frequency / 1000000, "MHz")
        lines.append(f"Source frequency: {amount:g} {unit} ({value.get('frequency_role') or 'unclassified'})")
    codes = sorted({issue["code"] for issue in record.get("issues", []) + list(listing.catalog.issues)})
    if codes:
        lines.append("DATA " + ("INVALID" if record.get("validation_status") == "invalid" else "REVIEW") +
                     ": " + ", ".join(codes) + ". Source values are not tuning recommendations.")
    lines.append(f"Catalog: {listing.catalog.theater_id}, {listing.catalog.snapshot_id[:12]} (pinned; local sources checked at load).")
    lines.append("Nearby does not mean receivable or aircraft-compatible. Cockpit unchanged.")
    return "\n".join(lines)
