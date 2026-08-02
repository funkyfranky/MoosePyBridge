from __future__ import annotations

from pathlib import Path

from tools.import_dcs_datamine import LuaLiteralParser, build_artifact, descriptor_record


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
        '_G["db"]["unit"] = { type = "Tank", ThreatRange = 2500, '
        'attribute = { "Tanks", "Armed ground units" } }',
        encoding="utf-8",
    )

    artifact = build_artifact(tmp_path, dcs_build="test-build")

    assert artifact["descriptor_count"] == 1
    assert artifact["source"]["dcs_build"] == "test-build"
    assert artifact["unit_envelopes"][0]["primary_weapon_flag"] == "BUILT_IN_CANNON"
