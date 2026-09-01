from __future__ import annotations

import json
from pathlib import Path
import runpy

import pytest

from moosebridge._lua_data import Expression, LuaDataError, Reader, Symbol, json_value
from moosebridge import navaids


TYPES = """
BEACON_TYPE_TACAN = 4
BEACON_TYPE_VOR_DME = 3
BEACON_TYPE_DME = 2
BEACON_TYPE_HOMER = 8
BEACON_TYPE_ILS_LOCALIZER = 16640
BEACON_TYPE_ILS_GLIDESLOPE = 16896
BEACON_DISABLED = 0
BEACON_ACTIVE = 1
local ILSchannelsPairs = {['18X']={108.10,334.70}, ['18Y']={108.15,334.55}, ['26X']={108.90,329.30}}
function must_not_run() error('not executed') end
"""
SITES = """
SystemName = {TACAN=3, VORDME=15}
default_systems = {
 [BEACON_TYPE_TACAN]={system=SystemName.TACAN},
 [BEACON_TYPE_VOR_DME]={system=SystemName.VORDME},
}
default_child_systems = {[BEACON_TYPE_TACAN]={system=SystemName.TACAN}}
beacon_system = {
 [SystemName.TACAN]={devices={
  [1]={signals=SIGNAL_TACAN_X + SIGNAL_TACAN_BEARING + SIGNAL_DME, height=14*0.3048},
 }},
 [SystemName.VORDME]={devices={
  [1]={signals=SIGNAL_TACAN_X + SIGNAL_DME}, [2]={signals=SIGNAL_VOR},
 }},
}
"""
BANDS = """HF = 0
VHF_LOW = 1
VHF_HI = 2
UHF = 3
"""
MODULATIONS = """MODULATIONTYPE_AM = 0
MODULATIONTYPE_FM = 1
MODULATIONTYPE_AMFM = 2
MODULATIONTYPE_DISCARD = -1
"""


def record(*, ident="world_0", kind="BEACON_TYPE_TACAN", name="Example", callsign="EX",
           frequency="977000000", channel="16", extra=""):
    return "{" + f"""
 display_name=_('{name}'); beaconId='{ident}'; type={kind}; callsign='{callsign}';
 {f'frequency={frequency};' if frequency else ''}
 {f'channel={channel};' if channel else ''}
 position={{100, 12, -200}}; positionGeo={{latitude=41, longitude=42}};
 direction=-90; sceneObjects={{'t:123'}}; {extra}
""" + "}"


def source(*records):
    return "dofile('not-executed.lua')\nlocal gettext=require('i_18n')\nbeaconsTableFormat=2\nbeacons={\n" + ",\n".join(records) + "\n}\n"


def radio_record(*, radio_id="airfield42_0", callsign="Example Tower", frequency="250500000",
                 band="UHF", modulation="MODULATIONTYPE_AM", extra=""):
    frequencies = (f"[{band}]={{{modulation},{frequency}}}" if frequency else "")
    return "{" + f"""
 radioId='{radio_id}'; role={{'ground','tower','approach'}};
 callsign={{{{['common']={{_('{callsign}'),'{callsign}'}}}}}};
 frequency={{{frequencies}}}; sceneObjects={{'t:456'}}; {extra}
""" + "}"


def radio_source(*records, version=3):
    return "dofile('not-executed.lua')\nradioTableFormat=" + str(version) + "\nradio={\n" + ",\n".join(records) + "\n}\n"


@pytest.fixture
def definitions():
    return navaids.read_definitions(TYPES, SITES)


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "DCS"
    radio = root / "Scripts/World/Radio"
    radio.mkdir(parents=True)
    (radio / "BeaconTypes.lua").write_text(TYPES, encoding="utf-8")
    (radio / "BeaconSites.lua").write_text(SITES, encoding="utf-8")
    (radio / "FrequencyBands.lua").write_text(BANDS, encoding="utf-8")
    (radio / "ModulationTypes.lua").write_text(MODULATIONS, encoding="utf-8")
    for folder, terrain_id, body, radios in (
        ("ExampleFolder", "ExampleTerrain", source(record()), radio_source(radio_record())),
        ("EmptyMap", "Empty", source(), radio_source()),
    ):
        directory = root / "Mods/terrains" / folder
        directory.mkdir(parents=True)
        (directory / "Beacons.lua").write_text(body, encoding="utf-8")
        (directory / "Radio.lua").write_text(radios, encoding="utf-8")
        (directory / "entry.lua").write_text("theatre={['id']='" + terrain_id + "', ['version']='EA'}", encoding="utf-8")
    return root


def catalog(result, folder="ExampleFolder"):
    item = next(item for item in result["maps"] if item["folder"] == folder)
    return json.loads((Path(result["snapshot_path"]) / item["file"]).read_text(encoding="utf-8"))


def codes(record):
    return {issue["code"] for issue in record["issues"]}


def test_reader_preserves_unicode_symbols_arithmetic_and_comments():
    reader = Reader("""-- bogus data={}
--[=[ data={danger()} ]=]
local ignored='data = {}'
data={name=_('Küstenpunkt'), ['x']=-1.25e2, symbol=UNKNOWN, height=14*0.3048,
      note='it\\'s safe', values={0, false, nil}, text=[=[hello]=]}
""")
    data = reader.assignment("data", terminal=True)
    assert data["name"] == "Küstenpunkt" and data["x"] == -125
    assert data["note"] == "it's safe" and data["text"] == "hello"
    assert isinstance(data["symbol"], Symbol) and isinstance(data["height"], Expression)
    assert data["values"] == {1: 0, 2: False, 3: None}
    assert json_value(data)["symbol"] == {"lua_symbol": "UNKNOWN"}


@pytest.mark.parametrize("text", [
    "data={x=os.execute('bad')}", "data={x=1,x=2}", "data={1;[1]=2}",
    "data={x=1e999}", "data={x=" + "9" * 400 + "}", "data={x='unterminated}",
    "data={x=1} data.x=2", "data={} data={}", "data={x=function() end}",
    "data={x=_('x', 'y')}", "data=" + "{" * 45 + "1" + "}" * 45,
])
def test_unsupported_or_ambiguous_lua_is_not_executed(text):
    with pytest.raises(LuaDataError):
        Reader(text).assignment("data", terminal=True)


def test_definitions_keep_system_capabilities_distinct(definitions):
    assert definitions["type_codes"]["BEACON_TYPE_TACAN"] == 4
    assert "SIGNAL_TACAN_BEARING" in definitions["system_signals"]["SystemName.TACAN"]["declared_signals"]
    assert "SIGNAL_TACAN_BEARING" not in definitions["system_signals"]["SystemName.VORDME"]["declared_signals"]
    assert definitions["systems"]["SystemName.TACAN"]["devices"]["1"]["height"] == {"lua_expression": "14*0.3048"}


def test_normalization_is_read_only_and_keeps_references(definitions):
    data = navaids.read_beacons(source(record(extra="chartOffsetX=500; futureField='keep me';")), definitions)
    value = data["records"][0]
    normalized = value["normalized"]
    assert normalized["frequency_hz"] == 977000000 and normalized["frequency_role"] == "uhf_dme_tacan"
    assert normalized["channel_mode"] == "X" and normalized["channel_mode_source"] == "default_system_declaration"
    assert normalized["position_m"] == {"x": 100, "y": 12, "z": -200}
    assert normalized["direction_raw_deg"] == -90 and normalized["live_verified"] is False
    assert value["raw_fields"]["futureField"] == "keep me" and "futureField" in value["raw_lua"]
    assert "unknown_field" in codes(value)


def test_unknown_type_is_not_dropped_or_guessed(definitions):
    data = navaids.read_beacons(source(record(kind="BEACON_TYPE_AIRPORT_TACAN")), definitions)
    value = data["records"][0]
    assert data["record_count"] == 1 and value["validation_status"] == "invalid"
    assert value["normalized"]["type_symbol"] == "BEACON_TYPE_AIRPORT_TACAN"
    assert value["normalized"]["type_code"] is None
    assert value["raw_fields"]["type"] == {"lua_symbol": "BEACON_TYPE_AIRPORT_TACAN"}


@pytest.mark.parametrize("kind,frequency,channel,expected", [
    ("BEACON_TYPE_TACAN", "", "16", None),
    ("BEACON_TYPE_TACAN", "1000000", "31", "unclassified_frequency"),
    ("BEACON_TYPE_TACAN", "977000000", "17", "frequency_channel_conflict"),
    ("BEACON_TYPE_DME", "108900000", "99", "frequency_channel_conflict"),
    ("BEACON_TYPE_VOR_DME", "108150000", "18", "frequency_mode_conflict"),
    ("BEACON_TYPE_HOMER", "430000", "0", "invalid_or_unused_channel"),
    ("BEACON_TYPE_TACAN", "", "", "missing_tuning"),
    ("BEACON_TYPE_TACAN", "nil", "nil", "missing_tuning"),
    ("BEACON_TYPE_TACAN", "977000000", "130", "channel_out_of_range"),
])
def test_tuning_variants_are_preserved_and_flagged(definitions, kind, frequency, channel, expected):
    value = navaids.read_beacons(source(record(kind=kind, frequency=frequency, channel=channel)), definitions)["records"][0]
    if expected:
        assert expected in codes(value)
    else:
        assert not value["issues"]
        assert value["normalized"]["frequency_hz"] is None


@pytest.mark.parametrize("frequency,role", [("108100000", "ils_localizer_tuning"), ("334700000", "ils_glideslope_carrier")])
def test_ils_frequency_roles_are_explicit(definitions, frequency, role):
    value = navaids.read_beacons(source(record(kind="BEACON_TYPE_ILS_GLIDESLOPE", frequency=frequency, channel="")), definitions)["records"][0]
    assert value["normalized"]["frequency_role"] == role


def test_duplicate_ids_confusables_and_ils_imbalance(definitions):
    data = navaids.read_beacons(source(
        record(ident="airfield1_0", kind="BEACON_TYPE_ILS_LOCALIZER", callsign="RC", frequency="108100000"),
        record(ident="airfield1_1", kind="BEACON_TYPE_ILS_GLIDESLOPE", callsign="R\u0421", frequency="108100000"),
        record(ident="airfield1_1", kind="BEACON_TYPE_ILS_GLIDESLOPE", callsign="RC", frequency="108100000"),
    ), definitions)
    assert data["record_count"] == 3
    assert {issue["code"] for issue in data["issues"]} == {"confusable_callsigns", "ils_component_imbalance"}
    assert all("duplicate_beacon_id" in codes(value) for value in data["records"][1:])
    assert data["records"][1]["normalized"]["callsign"] == "R\u0421"


def test_invalid_coordinates_are_not_filled_in(definitions):
    text = source(record()).replace("latitude=41", "latitude=141").replace("position={100, 12, -200}", "position={100, nil, -200}")
    value = navaids.read_beacons(text, definitions)["records"][0]
    assert {"invalid_position", "invalid_geographic_position"}.issubset(codes(value))
    assert value["normalized"]["position_m"] is None


def test_empty_is_valid_but_unknown_format_and_missing_table_are_not(definitions):
    assert navaids.read_beacons(source(), definitions)["record_count"] == 0
    for text in (source().replace("Format=2", "Format=3"), "beaconsTableFormat=2", "beaconsTableFormat=2\nbeacons={[2]={}}"):
        with pytest.raises(LuaDataError):
            navaids.read_beacons(text, definitions)


def test_airfield_radio_normalization_preserves_roles_callsigns_and_frequency():
    definitions = navaids.read_radio_definitions(BANDS, MODULATIONS)
    data = navaids.read_airfield_radios(radio_source(radio_record()), definitions)
    item = data["records"][0]
    assert data["format"] == 3 and data["record_count"] == 1
    assert item["normalized"] == {
        "radio_id": "airfield42_0", "airbase_uid": 42,
        "roles": ["ground", "tower", "approach"],
        "callsigns": [{"variant": "common", "translation_key": "Example Tower", "name": "Example Tower"}],
        "frequencies": [{"band_symbol": "UHF", "band_code": 3,
                         "modulation_symbol": "MODULATIONTYPE_AM", "modulation_code": 0,
                         "frequency_hz": 250500000}],
        "live_verified": False,
    }
    assert item["validation_status"] == "no_issues" and not item["issues"]


def test_airfield_radio_nonstandard_ids_empty_frequencies_and_duplicates_are_visible():
    definitions = navaids.read_radio_definitions(BANDS, MODULATIONS)
    data = navaids.read_airfield_radios(radio_source(
        radio_record(radio_id="As_Suwayda1", frequency=""),
        radio_record(radio_id="airfield5_0"),
        radio_record(radio_id="airfield5_1"),
    ), definitions)
    assert {"unresolvable_radio_id", "missing_radio_frequencies"}.issubset(codes(data["records"][0]))
    assert data["records"][0]["normalized"]["airbase_uid"] is None
    assert all("duplicate_airbase_uid" in codes(item) for item in data["records"][1:])
    assert all(item["validation_status"] == "review" for item in data["records"])


@pytest.mark.parametrize("text", [radio_source(version=2), "radioTableFormat=3", "radioTableFormat=3\nradio={[2]={}}"])
def test_airfield_radio_unknown_format_or_malformed_table_fails(text):
    with pytest.raises(LuaDataError):
        navaids.read_airfield_radios(text, navaids.read_radio_definitions(BANDS, MODULATIONS))


def test_legacy_windows_1251_radio_source_is_explicitly_identified():
    raw = radio_source(radio_record(callsign="Boulderсity")).encode("windows-1251")
    text, encoding = navaids._terrain_radio_text({"radio.lua": raw}, "radio.lua")
    assert encoding == "windows-1251" and "Boulderсity" in text


def test_snapshot_reuse_and_input_integrity(installation, tmp_path, monkeypatch):
    before = {str(path): path.read_bytes() for path in installation.rglob("*.lua")}
    output = tmp_path / "cache"
    first = navaids.import_installation(installation, output)
    assert first["status"] == "completed" and not first["reused"]
    assert catalog(first)["terrain_id"] == "ExampleTerrain"
    assert catalog(first, "EmptyMap")["record_count"] == 0
    assert catalog(first)["radio_record_count"] == 1
    assert catalog(first, "EmptyMap")["radio_record_count"] == 0
    monkeypatch.setattr(navaids, "read_beacons", lambda *args: pytest.fail("Cached tables must not be reparsed"))
    second = navaids.import_installation(installation, output)
    assert second["reused"] and first["snapshot_id"] == second["snapshot_id"]
    assert before == {str(path): path.read_bytes() for path in installation.rglob("*.lua")}
    assert "Offline static-data audit" in Path(second["report_path"]).read_text(encoding="utf-8")


def test_snapshot_publication_does_not_use_owner_only_temporary_directory(installation, tmp_path, monkeypatch):
    """Published Windows cache directories must inherit the project cache ACL."""
    monkeypatch.setattr(
        navaids.tempfile, "TemporaryDirectory",
        lambda *args, **kwargs: pytest.fail("Do not publish an owner-only temporary directory"),
    )
    result = navaids.import_installation(installation, tmp_path / "cache")
    assert result["status"] == "completed" and Path(result["snapshot_path"]).is_dir()


@pytest.mark.parametrize("change", ["beacons", "radio", "definitions", "sites", "bands", "modulations",
                                     "entry", "importer", "remove_map"])
def test_cache_refreshes_on_every_relevant_change(installation, tmp_path, monkeypatch, change):
    output = tmp_path / "cache"
    first = navaids.import_installation(installation, output)
    paths = {"beacons": "Mods/terrains/ExampleFolder/Beacons.lua", "definitions": "Scripts/World/Radio/BeaconTypes.lua",
             "radio": "Mods/terrains/ExampleFolder/Radio.lua",
             "sites": "Scripts/World/Radio/BeaconSites.lua", "bands": "Scripts/World/Radio/FrequencyBands.lua",
             "modulations": "Scripts/World/Radio/ModulationTypes.lua",
             "entry": "Mods/terrains/ExampleFolder/entry.lua"}
    if change in paths:
        path = installation / paths[change]
        path.write_text(path.read_text(encoding="utf-8") + "\n-- Updated source\n", encoding="utf-8")
    elif change == "importer":
        monkeypatch.setattr(navaids, "IMPORTER_VERSION", "next")
    else:
        (installation / "Mods/terrains/EmptyMap/Beacons.lua").unlink()
    second = navaids.import_installation(installation, output)
    assert not second["reused"] and second["snapshot_id"] != first["snapshot_id"]
    assert Path(first["report_path"]).is_file()


@pytest.mark.parametrize("path,bad", [
    ("Mods/terrains/ExampleFolder/Beacons.lua", "beaconsTableFormat=2\nbeacons={"),
    ("Mods/terrains/ExampleFolder/Radio.lua", "radioTableFormat=3\nradio={"),
    ("Scripts/World/Radio/BeaconTypes.lua", "not valid definitions"),
    ("Scripts/World/Radio/BeaconSites.lua", SITES.replace("system=SystemName.TACAN", "system=12")),
    ("Scripts/World/Radio/FrequencyBands.lua", BANDS.replace("HF = 0", "HF = 'bad'")),
])
def test_bad_import_reports_error_and_preserves_current(installation, tmp_path, path, bad):
    output = tmp_path / "cache"
    first = navaids.import_installation(installation, output)
    pointer = (output / "current.json").read_bytes()
    (installation / path).write_text(bad, encoding="utf-8")
    failed = navaids.import_installation(installation, output)
    assert failed["status"] == "failed"
    assert (output / "current.json").read_bytes() == pointer
    assert Path(first["report_path"]).is_file() and Path(failed["report_path"]).is_file()


def test_record_errors_do_not_discard_other_records(installation, tmp_path):
    (installation / "Mods/terrains/ExampleFolder/Beacons.lua").write_text(source(record(), record(ident="world_1", kind="UNKNOWN_TYPE")), encoding="utf-8")
    result = navaids.import_installation(installation, tmp_path / "cache")
    assert result["status"] == "completed"
    assert catalog(result)["record_count"] == 2
    assert catalog(result)["records"][1]["validation_status"] == "invalid"


def test_corrupt_cache_is_rebuilt_and_then_reused(installation, tmp_path):
    output = tmp_path / "cache"
    first = navaids.import_installation(installation, output)
    Path(first["report_path"]).write_text("corrupt", encoding="utf-8")
    second = navaids.import_installation(installation, output)
    assert not second["reused"] and second["snapshot_path"] != first["snapshot_path"]
    third = navaids.import_installation(installation, output)
    assert third["reused"] and third["snapshot_path"] == second["snapshot_path"]


@pytest.mark.parametrize("bad_artifacts", [None, [], {"../outside.json": "wrong"}])
def test_malformed_cache_manifest_is_not_trusted(installation, tmp_path, bad_artifacts):
    output = tmp_path / "cache"
    first = navaids.import_installation(installation, output)
    path = Path(first["snapshot_path"]) / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifacts"] = bad_artifacts
    path.write_text(json.dumps(manifest), encoding="utf-8")
    rebuilt = navaids.import_installation(installation, output)
    assert not rebuilt["reused"] and rebuilt["status"] == "completed"


def test_missing_metadata_does_not_invent_terrain_id(installation, tmp_path):
    (installation / "Mods/terrains/ExampleFolder/entry.lua").unlink()
    result = navaids.import_installation(installation, tmp_path / "cache")
    data = catalog(result)
    assert data["terrain_id"] is None and "terrain_id_unknown" in codes(data)


def test_explicit_channel_mode_remains_explicit(definitions):
    value = navaids.read_beacons(source(record(frequency="", extra="channelMode='Y';")), definitions)["records"][0]
    assert value["normalized"]["channel_mode"] == "Y"
    assert value["normalized"]["channel_mode_source"] == "explicit"


def test_sources_changing_during_import_do_not_publish(installation, tmp_path, monkeypatch):
    output = tmp_path / "cache"
    navaids.import_installation(installation, output)
    pointer = (output / "current.json").read_bytes()
    original = navaids._discover
    calls = 0

    def discover(root):
        nonlocal calls
        calls += 1
        if calls == 2:
            path = root / "Mods/terrains/ExampleFolder/Beacons.lua"
            path.write_text(source(record(channel="17")), encoding="utf-8")
        return original(root)
    monkeypatch.setattr(navaids, "_discover", discover)
    with pytest.raises(ValueError, match="sources changed"):
        navaids.import_installation(installation, output)
    assert (output / "current.json").read_bytes() == pointer


def test_no_writes_inside_dcs_and_missing_installation_is_not_empty_success(installation, tmp_path):
    with pytest.raises(ValueError, match="outside"):
        navaids.import_installation(installation, installation / "cache")
    assert not (installation / "cache").exists()
    with pytest.raises(ValueError, match="not found"):
        navaids.import_installation(tmp_path / "missing", tmp_path / "cache")


def test_cli_and_vscode_entrypoint_use_no_server(installation, tmp_path, capsys):
    assert navaids.main(["--dcs-root", str(installation), "--output", str(tmp_path / "cache")]) == 0
    assert "Static data only" in capsys.readouterr().out
    assert navaids.main(["--dcs-root", str(tmp_path / "missing"), "--output", str(tmp_path / "cache")]) == 2
    script = Path(__file__).resolve().parents[1] / "examples/navigation/import_dcs_beacons.py"
    example = runpy.run_path(str(script))
    assert example["main"] is navaids.main
