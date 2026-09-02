"""Navigation/import settings are shared, validated, and independent of cwd."""

from dataclasses import replace
import json
from pathlib import Path
import runpy

import pytest

from moosebridge.navigation_config import load_navigation_config


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "navigation.json"
    path.write_text((ROOT / "config/navigation.json").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_local_overrides_and_relative_paths_do_not_depend_on_cwd(config_file, tmp_path, monkeypatch):
    config_file.with_name("navigation.local.json").write_text(json.dumps({
        "control": {"port": 43001}, "navaids": {"dcs_directory": "DCS"},
    }), encoding="utf-8")
    monkeypatch.chdir(ROOT)
    config = load_navigation_config(config_file)
    assert config.control_port == 43001 and config.command_timeout == 10
    assert config.dcs_directory == tmp_path / "DCS"
    assert config.cache_directory == (tmp_path / "../tmp/navaids").resolve()
    assert config.speech_srs_port == 5002 and config.speech_frequency_mhz == 305
    assert config.speech_provider == "piper" and config.speech_voice == "en_US-lessac-low"
    assert config.copilot_auto_start and config.copilot_text_enabled and config.copilot_radio_enabled
    assert config.copilot_altitude_warning_ft == 300 and config.copilot_altitude_recovery_ft == 150
    assert config.copilot_nominal_climb_fpm == 1000 and config.copilot_nominal_descent_fpm == 1500
    assert config.copilot_stabilization_distance_nm == 1
    assert config.copilot_vertical_notice_seconds == 60
    assert config.copilot_target_waypoint_max_agl_m == 10


@pytest.mark.parametrize("override", [
    {"unknown": {}}, {"control": {"typo": 1}}, {"control": {"port": True}},
    {"control": {"port": 65536}}, {"control": {"command_timeout_seconds": 0}},
    {"control": {"reconnect_interval_seconds": float("nan")}}, {"control": {"host": ""}},
    {"navigation": {"initial_target_waypoint": 1}}, {"navigation": {"sample_interval_seconds": False}},
    {"copilot": {"auto_start": "yes"}}, {"copilot": {"sustain_seconds": 0}},
    {"copilot": {"speed_recovery_kt": 20}}, {"copilot": {"cross_track_warning_nm": float("nan")}},
    {"copilot": {"nominal_climb_fpm": 0}}, {"copilot": {"stabilization_distance_nm": -1}},
    {"copilot": {"vertical_notice_seconds": -1}},
    {"copilot": {"target_waypoint_max_agl_m": -1}},
    {"navaids": {"enabled": "yes"}}, {"navaids": {"cache_directory": ""}},
    {"navaids": {"dcs_directory": 3}}, {"navigation": []},
    {"speech": {"enabled": "yes"}}, {"speech": {"srs_port": 0}},
    {"speech": {"frequency_mhz": 0}}, {"speech": {"modulation": "SSB"}},
    {"speech": {"volume": 2}}, {"speech": {"voice": ""}}, {"speech": {"speed": 0}},
])
def test_invalid_overrides_fail_before_connecting(config_file, override):
    config_file.with_name("navigation.local.json").write_text(json.dumps(override), encoding="utf-8")
    with pytest.raises(ValueError):
        load_navigation_config(config_file)


def test_absent_local_configuration_keeps_missing_dcs_path_explicit(config_file):
    config = load_navigation_config(config_file)
    assert config.dcs_directory is None
    assert config.control_host == "127.0.0.1" and config.control_port == 42001


@pytest.mark.parametrize("text", ["{", "[]", "{}"])
def test_malformed_or_incomplete_configuration_fails(config_file, text):
    config_file.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_navigation_config(config_file)


def test_importer_uses_the_same_config_and_does_not_connect_to_dcs(config_file, monkeypatch):
    example = runpy.run_path(str(ROOT / "examples/navigation/import_dcs_beacons.py"))
    config = replace(load_navigation_config(config_file), dcs_directory=config_file.parent / "DCS")
    calls = []
    monkeypatch.setitem(example["run"].__globals__, "load_navigation_config", lambda path: config)
    monkeypatch.setitem(example["run"].__globals__, "main", lambda args: calls.append(args) or 0)
    assert example["run"]() == 0
    assert calls == [["--dcs-root", str(config.dcs_directory), "--output", str(config.cache_directory)]]


def test_importer_rejects_missing_local_dcs_path_without_writing(config_file, monkeypatch, capsys):
    example = runpy.run_path(str(ROOT / "examples/navigation/import_dcs_beacons.py"))
    monkeypatch.setitem(example["run"].__globals__, "CONFIG_FILE", config_file)
    monkeypatch.setitem(example["run"].__globals__, "main", lambda args: pytest.fail("Must not import"))
    assert example["run"]() == 2
    assert "navaids.dcs_directory" in capsys.readouterr().out
