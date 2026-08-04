"""Load generated sensor-range information from the DCS Lua datamine."""

from __future__ import annotations

from dataclasses import dataclass
import json
from importlib.resources import files
from typing import Any

from .datamine_ranges import DatamineMetadata


@dataclass(slots=True, frozen=True)
class DatamineSensorProfile:
    """One optimistic sensor detection bound exported from DCS descriptors."""

    dcs_type: str
    platform_category: str
    detection_type: str
    target_domain: str
    maximum_m: float | None
    mode: str | None = None
    hard_limit_m: float | None = None
    reference_rcs_m2: float | None = None
    scan_period_s: float | None = None
    scan_azimuth_deg: tuple[float, float] | None = None
    scan_elevation_deg: tuple[float, float] | None = None
    range_scope: str = "sensor"
    exclusion_safe: bool = False
    emitter_only: bool = False
    sensor_names: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    basis: str | None = None


@dataclass(slots=True, frozen=True)
class DatamineSensorData:
    """Validated generated sensor data."""

    metadata: DatamineMetadata
    profiles: tuple[DatamineSensorProfile, ...]
    unit_descriptor_count: int = 0
    sensor_descriptor_count: int = 0
    platform_descriptor_counts: tuple[tuple[str, int], ...] = ()


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _optional_positive_number(value: Any, name: str) -> float | None:
    return None if value is None else _positive_number(value, name)


def _optional_bounds(value: Any, name: str) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must contain two numbers")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ValueError(f"{name} must contain two numbers")
    return float(value[0]), float(value[1])


def load_datamine_sensor_data(path: str | None = None) -> DatamineSensorData:
    """Load the packaged sensor artifact or an explicitly supplied JSON file."""

    if path is None:
        resource = files("moosebridge").joinpath("data/dcs_sensor_ranges.json")
        if not resource.is_file():
            return DatamineSensorData(DatamineMetadata(), ())
        raw = json.loads(resource.read_text(encoding="utf-8"))
    else:
        with open(path, encoding="utf-8") as stream:
            raw = json.load(stream)

    if raw.get("schema_version") != 2:
        raise ValueError("Unsupported DCS datamine sensor schema")
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    metadata = DatamineMetadata(
        dcs_build=str(source["dcs_build"]) if source.get("dcs_build") else None,
        source_commit=str(source["commit"]) if source.get("commit") else None,
        source_url=str(source["url"]) if source.get("url") else None,
    )

    profiles = tuple(
        DatamineSensorProfile(
            dcs_type=str(item["dcs_type"]),
            platform_category=str(item["platform_category"]),
            detection_type=str(item["detection_type"]),
            target_domain=str(item["target_domain"]),
            maximum_m=_optional_positive_number(item.get("maximum_m"), "maximum_m"),
            mode=str(item["mode"]) if item.get("mode") else None,
            hard_limit_m=_optional_positive_number(item.get("hard_limit_m"), "hard_limit_m"),
            reference_rcs_m2=_optional_positive_number(item.get("reference_rcs_m2"), "reference_rcs_m2"),
            scan_period_s=_optional_positive_number(item.get("scan_period_s"), "scan_period_s"),
            scan_azimuth_deg=_optional_bounds(item.get("scan_azimuth_deg"), "scan_azimuth_deg"),
            scan_elevation_deg=_optional_bounds(item.get("scan_elevation_deg"), "scan_elevation_deg"),
            range_scope=str(item.get("range_scope", "sensor")),
            exclusion_safe=bool(item.get("exclusion_safe", False)),
            emitter_only=bool(item.get("emitter_only", False)),
            sensor_names=tuple(str(value) for value in item.get("sensor_names", [])),
            source_paths=tuple(str(value) for value in item.get("source_paths", [])),
            basis=str(item["basis"]) if item.get("basis") else None,
        )
        for item in raw.get("sensor_profiles", [])
    )
    return DatamineSensorData(
        metadata=metadata,
        profiles=profiles,
        unit_descriptor_count=int(raw.get("unit_descriptor_count", 0)),
        sensor_descriptor_count=int(raw.get("sensor_descriptor_count", 0)),
        platform_descriptor_counts=tuple(
            sorted(
                (str(key), int(value))
                for key, value in (
                    raw.get("platform_descriptor_counts")
                    if isinstance(raw.get("platform_descriptor_counts"), dict)
                    else {}
                ).items()
            )
        ),
    )


DEFAULT_DATAMINE_SENSOR_DATA = load_datamine_sensor_data()


__all__ = [
    "DEFAULT_DATAMINE_SENSOR_DATA",
    "DatamineSensorData",
    "DatamineSensorProfile",
    "load_datamine_sensor_data",
]
