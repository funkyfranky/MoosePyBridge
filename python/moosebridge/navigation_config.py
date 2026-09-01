"""Shared configuration for the navigation client and offline navaid importer."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class NavigationConfig:
    control_host: str
    control_port: int
    command_timeout: float
    reconnect_interval: float
    event_timeout: float
    sample_interval: float
    hint_interval: float
    initial_target: int
    capture_radius_m: float
    max_sample_gap: float
    navaids_enabled: bool
    dcs_directory: Path | None
    cache_directory: Path


_SECTIONS = {
    "control": {"host", "port", "command_timeout_seconds", "reconnect_interval_seconds", "event_timeout_seconds"},
    "navigation": {"sample_interval_seconds", "hint_interval_seconds", "initial_target_waypoint",
                   "capture_radius_m", "max_sample_gap_seconds"},
    "navaids": {"enabled", "dcs_directory", "cache_directory"},
}


def load_navigation_config(path: str | Path) -> NavigationConfig:
    """Read defaults plus optional sibling *.local.json; paths use this directory.

    No files are created and no import/deployment is performed. Unknown keys
    fail early so misspelled settings cannot silently change runtime behavior.
    """
    path = Path(path).resolve()
    local = path.with_name(path.stem + ".local.json")
    data = {section: {} for section in _SECTIONS}
    for source in (path, local):
        if source == local and not source.exists():
            continue
        try:
            values = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read navigation configuration {source}: {exc}") from exc
        if not isinstance(values, dict) or set(values) - set(_SECTIONS):
            raise ValueError(f"Unknown navigation configuration section in {source}")
        for section, settings in values.items():
            if not isinstance(settings, dict) or set(settings) - _SECTIONS[section]:
                raise ValueError(f"Unknown or invalid {section} settings in {source}")
            data[section].update(settings)
    for section, keys in _SECTIONS.items():
        if set(data[section]) != keys:
            raise ValueError(f"Missing {section} settings: {', '.join(sorted(keys - set(data[section])))}")

    def positive(section: str, key: str) -> float:
        value = data[section][key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{section}.{key} must be positive and finite")
        return float(value)

    def integer(section: str, key: str, low: int, high: int) -> int:
        value = data[section][key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{section}.{key} must be an integer in {low}..{high}")
        return value

    def directory(key: str, optional: bool = False) -> Path | None:
        value = data["navaids"][key]
        if optional and value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"navaids.{key} must be a non-empty path")
        return (path.parent / value).resolve()

    host = data["control"]["host"]
    if not isinstance(host, str) or not host.strip():
        raise ValueError("control.host must be a non-empty string")
    enabled = data["navaids"]["enabled"]
    if type(enabled) is not bool:
        raise ValueError("navaids.enabled must be boolean")
    return NavigationConfig(
        control_host=host.strip(), control_port=integer("control", "port", 1, 65535),
        command_timeout=positive("control", "command_timeout_seconds"),
        reconnect_interval=positive("control", "reconnect_interval_seconds"),
        event_timeout=positive("control", "event_timeout_seconds"),
        sample_interval=positive("navigation", "sample_interval_seconds"),
        hint_interval=positive("navigation", "hint_interval_seconds"),
        initial_target=integer("navigation", "initial_target_waypoint", 2, 501),
        capture_radius_m=positive("navigation", "capture_radius_m"),
        max_sample_gap=positive("navigation", "max_sample_gap_seconds"),
        navaids_enabled=enabled, dcs_directory=directory("dcs_directory", optional=True),
        cache_directory=directory("cache_directory"),
    )
