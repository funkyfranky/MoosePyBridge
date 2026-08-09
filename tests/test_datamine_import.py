from __future__ import annotations

from pathlib import Path

from tools.import_dcs_datamine import (
    LuaLiteralParser,
    build_artifact,
    build_sensor_artifact,
    descriptor_record,
    sensor_descriptor_profiles,
    unit_sensor_profiles,
)


def test_literal_parser_handles_datamine_table_markers_and_references() -> None:
    table = LuaLiteralParser(
        '_G["db"]["unit"] = <1>{ type = "Test", values = { <2>{ 1, 2 }, <table 2> } }'
    ).parse_assignment()

    assert table.fields["type"] == "Test"
    values = table.fields["values"].values
    assert values[0].values == [1, 2]
    assert values[1].values == []


def test_descriptor_import_separates_exact_range_from_unit_envelope() -> None:
    table = LuaLiteralParser(
        """
        _G["db"]["unit"] = {
            type = "Test MLRS",
            DisplayName = "Test launcher",
            MaxSpeed = 64.00008,
            ThreatRangeMin = 10000,
            ThreatRange = 32000,
            attribute = { "MLRS", "Artillery", "Indirect fire" },
            WS = {{ LN = {{
                distanceMin = 10000,
                distanceMax = 32000,
                PL = {{ type_ammunition = "weapons.nurs.TEST", ammo_capacity = 12 }}
            }} }}
        }
        """
    ).parse_assignment()

    envelope, ranges = descriptor_record(table, "unit.lua")

    assert envelope["primary_weapon_flag"] == "ANY_ROCKET"
    assert envelope["max_speed_kph"] == 64.00008
    assert envelope["minimum_m"] == 10_000
    assert ranges == [
        {
            "dcs_type": "Test MLRS",
            "weapon_flag": "ANY_ROCKET",
            "minimum_m": 10_000.0,
            "maximum_m": 32_000.0,
            "weapon_ids": ["weapons.nurs.TEST"],
            "source_path": "unit.lua",
        }
    ]


def test_build_artifact_imports_local_descriptor_directory(tmp_path: Path) -> None:
    directory = tmp_path / "_G" / "db" / "Units" / "Cars" / "Car"
    directory.mkdir(parents=True)
    (directory / "unit.lua").write_text(
        '_G["db"]["unit"] = { type = "Tank", MaxSpeed = 72, ThreatRange = 2500, '
        'attribute = { "Tanks", "Armed ground units" } }',
        encoding="utf-8",
    )

    artifact = build_artifact(tmp_path, dcs_build="test-build")

    assert artifact["descriptor_count"] == 1
    assert artifact["source"]["dcs_build"] == "test-build"
    assert artifact["unit_envelopes"][0]["primary_weapon_flag"] == "BUILT_IN_CANNON"
    assert artifact["unit_envelopes"][0]["max_speed_kph"] == 72


def test_sensor_import_extracts_and_clamps_detection_bounds() -> None:
    radar = LuaLiteralParser(
        """
        _G["db"]["sensor"] = {
            Name = "Test Radar",
            SensorType = 1,
            max_measuring_distance = 100000,
            air_search = { detection_distance = { [0] = 90000, 80000 } },
            surface_search = { RBM_detection_distance = 60000 }
        }
        """
    ).parse_assignment()
    radar_name, radar_profiles = sensor_descriptor_profiles(radar, "radar.lua")
    assert radar_name == "Test Radar"
    assert {(item["target_domain"], item["maximum_m"]) for item in radar_profiles} == {
        ("air", 90_000.0),
        ("surface", 60_000.0),
    }

    unit = LuaLiteralParser(
        """
        _G["db"]["unit"] = {
            type = "Recon Tank",
            Sensors = { OPTIC = { "Day Sight" }, RADAR = { "Test Radar" } },
            WS = { { maxTargetDetectionRange = 5000 } }
        }
        """
    ).parse_assignment()
    profiles = unit_sensor_profiles(unit, "unit.lua", {radar_name: ("radar.lua", radar_profiles)})

    assert {(item["detection_type"], item["target_domain"], item["maximum_m"]) for item in profiles} == {
        ("organic", "any", 5_000.0),
        ("optic", "any", 5_000.0),
        ("radar", "air", 5_000.0),
        ("radar", "surface", 5_000.0),
    }


def test_sensor_import_handles_airborne_surface_modes_and_unknown_optics() -> None:
    radar = LuaLiteralParser(
        """
        _G["db"]["sensor"] = {
            Name = "Mast Radar", SensorType = 1,
            max_measuring_distance = 50000,
            GMTI_detection_distance = 40000,
            HRM_detection_distance = 15000,
            RBM_detection_distance = 10000
        }
        """
    ).parse_assignment()
    radar_name, radar_profiles = sensor_descriptor_profiles(radar, "mast-radar.lua")
    optic = LuaLiteralParser(
        '_G["db"]["sensor"] = { Name = "Target Sight", SensorType = 0, magnifications = { 2, 20 } }'
    ).parse_assignment()
    optic_name, optic_profiles = sensor_descriptor_profiles(optic, "sight.lua")
    helicopter = LuaLiteralParser(
        """
        _G["db"]["unit"] = {
            type = "Attack Helo",
            Sensors = { RADAR = "Mast Radar", OPTIC = "Target Sight", RWR = "Abstract RWR" }
        }
        """
    ).parse_assignment()
    profiles = unit_sensor_profiles(
        helicopter,
        "helo.lua",
        {
            radar_name: ("mast-radar.lua", radar_profiles),
            optic_name: ("sight.lua", optic_profiles),
        },
        "helicopter",
    )

    radar_modes = {
        (item["mode"], item["maximum_m"])
        for item in profiles
        if item["detection_type"] == "radar"
    }
    assert radar_modes == {("gmti", 40_000.0), ("hrm", 15_000.0), ("rbm", 10_000.0)}
    assert any(
        item["detection_type"] == "optic"
        and item["maximum_m"] is None
        and item["exclusion_safe"] is False
        for item in profiles
    )
    assert any(item["detection_type"] == "rwr" and item["emitter_only"] for item in profiles)


def test_build_sensor_artifact_imports_local_descriptors(tmp_path: Path) -> None:
    unit_directory = tmp_path / "_G" / "db" / "Units" / "Cars" / "Car"
    plane_directory = tmp_path / "_G" / "db" / "Units" / "Planes" / "Plane"
    helicopter_directory = tmp_path / "_G" / "db" / "Units" / "Helicopters" / "Helicopter"
    sensor_directory = tmp_path / "_G" / "db" / "Sensors" / "Sensor"
    unit_directory.mkdir(parents=True)
    plane_directory.mkdir(parents=True)
    helicopter_directory.mkdir(parents=True)
    sensor_directory.mkdir(parents=True)
    (unit_directory / "unit.lua").write_text(
        '_G["db"]["unit"] = { type = "Scout", maxTargetDetectionRange = 7500, '
        'Sensors = { OPTIC = { "Scout Sight" } } }',
        encoding="utf-8",
    )
    (sensor_directory / "optic.lua").write_text(
        '_G["db"]["sensor"] = { Name = "Scout Sight", SensorType = 0 }',
        encoding="utf-8",
    )

    artifact = build_sensor_artifact(tmp_path, dcs_build="test-build")

    assert artifact["unit_descriptor_count"] == 1
    assert artifact["sensor_descriptor_count"] == 1
    assert artifact["platform_descriptor_counts"] == {"ground": 1, "airplane": 0, "helicopter": 0}
    assert artifact["source"]["dcs_build"] == "test-build"
    assert len(artifact["sensor_profiles"]) == 2
