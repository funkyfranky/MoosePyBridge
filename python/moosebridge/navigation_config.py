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
    initial_target: int
    capture_radius_m: float
    max_sample_gap: float
    copilot_auto_start: bool
    copilot_text_enabled: bool
    copilot_radio_enabled: bool
    copilot_altitude_warning_ft: float
    copilot_altitude_recovery_ft: float
    copilot_speed_warning_kt: float
    copilot_speed_recovery_kt: float
    copilot_cross_track_warning_nm: float
    copilot_cross_track_recovery_nm: float
    copilot_sustain_seconds: float
    copilot_reminder_cooldown_seconds: float
    copilot_nominal_climb_fpm: float
    copilot_nominal_descent_fpm: float
    copilot_stabilization_distance_nm: float
    copilot_vertical_speed_smoothing_seconds: float
    copilot_vertical_notice_seconds: float
    copilot_target_waypoint_max_agl_m: float
    navaids_enabled: bool
    dcs_directory: Path | None
    cache_directory: Path
    speech_enabled: bool
    speech_profile_id: str
    speech_network_id: str
    speech_srs_path: Path
    speech_srs_host: str
    speech_srs_port: int
    speech_frequency_mhz: float
    speech_modulation: str
    speech_provider: str
    speech_voice: str
    speech_label: str
    speech_volume: float
    speech_speed: float
    speech_interval: float
    speech_arbitration: str
    speech_backoff_min: float
    speech_backoff_max: float
    speech_collision_probability: float
    speech_emergency_break_in: bool


_SECTIONS = {
    "control": {"host", "port", "command_timeout_seconds", "reconnect_interval_seconds", "event_timeout_seconds"},
    "navigation": {"sample_interval_seconds", "initial_target_waypoint",
                   "capture_radius_m", "max_sample_gap_seconds"},
    "copilot": {"auto_start", "text_enabled", "radio_enabled", "altitude_warning_ft",
                "altitude_recovery_ft", "speed_warning_kt", "speed_recovery_kt",
                "cross_track_warning_nm", "cross_track_recovery_nm", "sustain_seconds",
                "reminder_cooldown_seconds", "nominal_climb_fpm", "nominal_descent_fpm",
                "stabilization_distance_nm", "vertical_speed_smoothing_seconds",
                "vertical_notice_seconds", "target_waypoint_max_agl_m"},
    "navaids": {"enabled", "dcs_directory", "cache_directory"},
    "speech": {"enabled", "profile_id", "network_id", "srs_path", "srs_host", "srs_port",
               "frequency_mhz", "modulation", "provider", "voice", "label", "volume", "speed",
               "interval_seconds", "arbitration", "backoff_min_seconds", "backoff_max_seconds",
               "collision_probability", "emergency_break_in"},
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

    def nonnegative(section: str, key: str) -> float:
        value = data[section][key]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{section}.{key} must be finite and non-negative")
        return float(value)

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
    speech_enabled = data["speech"]["enabled"]
    if type(speech_enabled) is not bool:
        raise ValueError("speech.enabled must be boolean")
    for key in ("auto_start", "text_enabled", "radio_enabled"):
        if type(data["copilot"][key]) is not bool:
            raise ValueError(f"copilot.{key} must be boolean")
    copilot_values = {
        key: positive("copilot", key)
        for key in ("altitude_warning_ft", "altitude_recovery_ft", "speed_warning_kt",
                    "speed_recovery_kt", "cross_track_warning_nm", "cross_track_recovery_nm",
                    "sustain_seconds", "reminder_cooldown_seconds", "nominal_climb_fpm",
                    "nominal_descent_fpm", "vertical_speed_smoothing_seconds")
    }
    copilot_values["stabilization_distance_nm"] = nonnegative(
        "copilot", "stabilization_distance_nm")
    copilot_values["vertical_notice_seconds"] = nonnegative(
        "copilot", "vertical_notice_seconds")
    copilot_values["target_waypoint_max_agl_m"] = nonnegative(
        "copilot", "target_waypoint_max_agl_m")
    threshold_pairs = {
        "altitude": ("altitude_recovery_ft", "altitude_warning_ft"),
        "speed": ("speed_recovery_kt", "speed_warning_kt"),
        "cross_track": ("cross_track_recovery_nm", "cross_track_warning_nm"),
    }
    for name, (recovery_key, warning_key) in threshold_pairs.items():
        if copilot_values[recovery_key] >= copilot_values[warning_key]:
            raise ValueError(f"copilot.{name} recovery threshold must be below its warning threshold")
    for key in ("profile_id", "network_id", "srs_host", "provider", "voice", "label"):
        value = data["speech"][key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"speech.{key} must be a non-empty string")
    modulation = data["speech"]["modulation"]
    if modulation not in {"AM", "FM"}:
        raise ValueError("speech.modulation must be AM or FM")
    volume = data["speech"]["volume"]
    if type(volume) not in (int, float) or not math.isfinite(volume) or not 0 <= volume <= 1:
        raise ValueError("speech.volume must be finite and between 0 and 1")
    arbitration = data["speech"]["arbitration"]
    if arbitration not in {"strict", "disciplined", "congested", "uncontrolled"}:
        raise ValueError("speech.arbitration must be strict, disciplined, congested, or uncontrolled")
    collision_probability = data["speech"]["collision_probability"]
    if (type(collision_probability) not in (int, float) or not math.isfinite(collision_probability)
            or not 0 <= collision_probability <= 1):
        raise ValueError("speech.collision_probability must be finite and between 0 and 1")
    emergency_break_in = data["speech"]["emergency_break_in"]
    if type(emergency_break_in) is not bool:
        raise ValueError("speech.emergency_break_in must be boolean")
    backoff_min = data["speech"]["backoff_min_seconds"]
    backoff_max = data["speech"]["backoff_max_seconds"]
    if (type(backoff_min) not in (int, float) or not math.isfinite(backoff_min) or backoff_min < 0
            or type(backoff_max) not in (int, float) or not math.isfinite(backoff_max) or backoff_max < 0):
        raise ValueError("speech backoff values must be finite and non-negative")
    backoff_min, backoff_max = float(backoff_min), float(backoff_max)
    if backoff_max < backoff_min:
        raise ValueError("speech.backoff_max_seconds must not be less than backoff_min_seconds")
    frequency = positive("speech", "frequency_mhz")
    if frequency > 1000:
        raise ValueError("speech.frequency_mhz must not exceed 1000")
    srs_path = data["speech"]["srs_path"]
    if not isinstance(srs_path, str) or not srs_path.strip():
        raise ValueError("speech.srs_path must be a non-empty path")
    resolved_srs_path = Path(srs_path).expanduser()
    if not resolved_srs_path.is_absolute():
        resolved_srs_path = path.parent / resolved_srs_path
    return NavigationConfig(
        control_host=host.strip(), control_port=integer("control", "port", 1, 65535),
        command_timeout=positive("control", "command_timeout_seconds"),
        reconnect_interval=positive("control", "reconnect_interval_seconds"),
        event_timeout=positive("control", "event_timeout_seconds"),
        sample_interval=positive("navigation", "sample_interval_seconds"),
        initial_target=integer("navigation", "initial_target_waypoint", 2, 501),
        capture_radius_m=positive("navigation", "capture_radius_m"),
        max_sample_gap=positive("navigation", "max_sample_gap_seconds"),
        copilot_auto_start=data["copilot"]["auto_start"],
        copilot_text_enabled=data["copilot"]["text_enabled"],
        copilot_radio_enabled=data["copilot"]["radio_enabled"],
        copilot_altitude_warning_ft=copilot_values["altitude_warning_ft"],
        copilot_altitude_recovery_ft=copilot_values["altitude_recovery_ft"],
        copilot_speed_warning_kt=copilot_values["speed_warning_kt"],
        copilot_speed_recovery_kt=copilot_values["speed_recovery_kt"],
        copilot_cross_track_warning_nm=copilot_values["cross_track_warning_nm"],
        copilot_cross_track_recovery_nm=copilot_values["cross_track_recovery_nm"],
        copilot_sustain_seconds=copilot_values["sustain_seconds"],
        copilot_reminder_cooldown_seconds=copilot_values["reminder_cooldown_seconds"],
        copilot_nominal_climb_fpm=copilot_values["nominal_climb_fpm"],
        copilot_nominal_descent_fpm=copilot_values["nominal_descent_fpm"],
        copilot_stabilization_distance_nm=copilot_values["stabilization_distance_nm"],
        copilot_vertical_speed_smoothing_seconds=copilot_values["vertical_speed_smoothing_seconds"],
        copilot_vertical_notice_seconds=copilot_values["vertical_notice_seconds"],
        copilot_target_waypoint_max_agl_m=copilot_values["target_waypoint_max_agl_m"],
        navaids_enabled=enabled, dcs_directory=directory("dcs_directory", optional=True),
        cache_directory=directory("cache_directory"),
        speech_enabled=speech_enabled,
        speech_profile_id=data["speech"]["profile_id"].strip(),
        speech_network_id=data["speech"]["network_id"].strip(),
        speech_srs_path=resolved_srs_path.resolve(),
        speech_srs_host=data["speech"]["srs_host"].strip(),
        speech_srs_port=integer("speech", "srs_port", 1, 65535),
        speech_frequency_mhz=frequency, speech_modulation=modulation,
        speech_provider=data["speech"]["provider"].strip(),
        speech_voice=data["speech"]["voice"].strip(), speech_label=data["speech"]["label"].strip(),
        speech_volume=float(volume), speech_speed=positive("speech", "speed"),
        speech_interval=positive("speech", "interval_seconds"),
        speech_arbitration=arbitration,
        speech_backoff_min=backoff_min, speech_backoff_max=backoff_max,
        speech_collision_probability=float(collision_probability),
        speech_emergency_break_in=emergency_break_in,
    )
