"""Load generated weapon-range information from the DCS Lua datamine."""

from __future__ import annotations

from dataclasses import dataclass
import json
from importlib.resources import files
from typing import Any

from .ammunition import DcsWeaponFlag


@dataclass(slots=True, frozen=True)
class DatamineMetadata:
    """Version information attached to a generated datamine artifact."""

    dcs_build: str | None = None
    source_commit: str | None = None
    source_url: str | None = None


@dataclass(slots=True, frozen=True)
class DatamineRange:
    """One exact weapon-station range exported from a unit descriptor."""

    dcs_type: str
    weapon_flag: DcsWeaponFlag
    minimum_m: float
    maximum_m: float
    weapon_ids: tuple[str, ...] = ()
    source_path: str | None = None


@dataclass(slots=True, frozen=True)
class DatamineUnitEnvelope:
    """Unit-level descriptor data used for ranges and ground mobility."""

    dcs_type: str
    minimum_m: float
    maximum_m: float
    maximum_speed_kph: float | None = None
    primary_weapon_flag: DcsWeaponFlag | None = None
    source_path: str | None = None


@dataclass(slots=True, frozen=True)
class DatamineRangeData:
    """Validated generated range data."""

    metadata: DatamineMetadata
    ranges: tuple[DatamineRange, ...]
    unit_envelopes: tuple[DatamineUnitEnvelope, ...]
    descriptor_count: int = 0


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def _flag(value: Any) -> DcsWeaponFlag:
    if isinstance(value, str):
        try:
            return DcsWeaponFlag[value]
        except KeyError as exc:
            raise ValueError(f"Unknown DCS weapon flag: {value}") from exc
    return DcsWeaponFlag(int(value))


def load_datamine_range_data(path: str | None = None) -> DatamineRangeData:
    """Load the packaged artifact or an explicitly supplied JSON file."""

    if path is None:
        resource = files("moosebridge").joinpath("data/dcs_ground_weapon_ranges.json")
        if not resource.is_file():
            return DatamineRangeData(DatamineMetadata(), (), ())
        raw = json.loads(resource.read_text(encoding="utf-8"))
    else:
        with open(path, encoding="utf-8") as stream:
            raw = json.load(stream)

    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported DCS datamine range schema")
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    metadata = DatamineMetadata(
        dcs_build=str(source["dcs_build"]) if source.get("dcs_build") else None,
        source_commit=str(source["commit"]) if source.get("commit") else None,
        source_url=str(source["url"]) if source.get("url") else None,
    )

    ranges: list[DatamineRange] = []
    for item in raw.get("weapon_ranges", []):
        minimum = _number(item.get("minimum_m"), "minimum_m")
        maximum = _number(item.get("maximum_m"), "maximum_m")
        if minimum < 0 or maximum < minimum:
            raise ValueError("Invalid datamine weapon range")
        ranges.append(
            DatamineRange(
                dcs_type=str(item["dcs_type"]),
                weapon_flag=_flag(item["weapon_flag"]),
                minimum_m=minimum,
                maximum_m=maximum,
                weapon_ids=tuple(str(value) for value in item.get("weapon_ids", [])),
                source_path=str(item["source_path"]) if item.get("source_path") else None,
            )
        )

    envelopes: list[DatamineUnitEnvelope] = []
    for item in raw.get("unit_envelopes", []):
        minimum = _number(item.get("minimum_m", 0), "minimum_m")
        maximum = _number(item.get("maximum_m"), "maximum_m")
        maximum_speed = (
            _number(item.get("max_speed_kph"), "max_speed_kph")
            if item.get("max_speed_kph") is not None
            else None
        )
        if minimum < 0 or maximum < minimum:
            raise ValueError("Invalid datamine unit envelope")
        if maximum_speed is not None and maximum_speed < 0:
            raise ValueError("Invalid datamine unit maximum speed")
        primary = item.get("primary_weapon_flag")
        envelopes.append(
            DatamineUnitEnvelope(
                dcs_type=str(item["dcs_type"]),
                minimum_m=minimum,
                maximum_m=maximum,
                maximum_speed_kph=maximum_speed,
                primary_weapon_flag=_flag(primary) if primary is not None else None,
                source_path=str(item["source_path"]) if item.get("source_path") else None,
            )
        )

    return DatamineRangeData(
        metadata=metadata,
        ranges=tuple(ranges),
        unit_envelopes=tuple(envelopes),
        descriptor_count=int(raw.get("descriptor_count", 0)),
    )


DEFAULT_DATAMINE_RANGE_DATA = load_datamine_range_data()
