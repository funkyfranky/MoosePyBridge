from __future__ import annotations

import json

import pytest

pytest.importorskip("contourpy")
pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("shapely")

from moosebridge.frontline_diagnostics import write_frontline_diagnostic_html
from moosebridge.frontlines import ForcePoint, FrontlineArea, FrontlineConfig, FrontlineEngine
from moosebridge.models import Territory


def square() -> FrontlineArea:
    return FrontlineArea("Test", ((-50_000, -50_000), (50_000, -50_000), (50_000, 50_000), (-50_000, 50_000)))


def test_equal_opposing_forces_create_centered_frontline() -> None:
    result = FrontlineEngine(
        FrontlineConfig(
            grid_spacing_m=1_000,
            influence_sigma_m=12_000,
            simplify_tolerance_m=0,
            minimum_segment_length_m=0,
        )
    ).calculate(
        [ForcePoint("GROUP:Blue", "blue", -15_000, 0), ForcePoint("GROUP:Red", "red", 15_000, 0)],
        area=square(),
    )

    assert len(result.segments) == 1
    assert max(abs(x) for x, _ in result.segments[0].points) <= result.config.grid_spacing_m
    assert result.diagnostics["blue_force_count"] == 1
    assert result.diagnostics["red_force_count"] == 1


def test_single_coalition_has_no_frontline() -> None:
    result = FrontlineEngine().calculate([ForcePoint("GROUP:Blue", "blue", 0, 0)], area=square())

    assert result.segments == ()


def test_area_excludes_outside_forces() -> None:
    result = FrontlineEngine().calculate(
        [
            ForcePoint("GROUP:Inside", "blue", 0, 0),
            ForcePoint("GROUP:Outside", "red", 100_000, 0),
        ],
        area=square(),
    )

    assert [force.object_id for force in result.forces] == ["GROUP:Inside"]
    assert result.diagnostics["included_force_count"] == 1


def test_grid_uses_exact_spacing_and_enforces_cell_limit() -> None:
    config = FrontlineConfig(grid_spacing_m=3_000, maximum_grid_cells=2_000)
    result = FrontlineEngine(config).calculate([], area=FrontlineArea("Odd", ((0, 0), (10_001, 0), (10_001, 10_001), (0, 10_001))))

    assert result.x_coordinates[1] - result.x_coordinates[0] == 3_000

    with pytest.raises(ValueError, match="above maximum_grid_cells"):
        FrontlineEngine(FrontlineConfig(grid_spacing_m=100, maximum_grid_cells=100)).calculate([], area=square())


def test_frontline_area_from_typed_territory() -> None:
    territory = Territory.from_payload(
        {
            "object_id": "TERRITORY:North",
            "dcs_name": "North",
            "name": "North",
            "object_type": "TERRITORY",
            "vertices": [
                {"x": 0, "z": 0},
                {"x": 10_000, "z": 0},
                {"x": 10_000, "z": 10_000},
                {"x": 0, "z": 10_000},
            ],
        }
    )

    area = FrontlineArea.from_territory(territory)

    assert area.name == "North"
    assert area.vertices[2] == (10_000.0, 10_000.0)


def test_geojson_and_html_diagnostics(tmp_path) -> None:
    result = FrontlineEngine().calculate(
        [ForcePoint("GROUP:Blue", "blue", -10_000, 0), ForcePoint("GROUP:Red", "red", 10_000, 0)],
        area=square(),
    )
    geojson = result.to_geojson()
    html_path = write_frontline_diagnostic_html(result, tmp_path / "frontline.html")

    assert geojson["type"] == "FeatureCollection"
    assert any(feature["properties"]["layer"] == "frontlines" for feature in geojson["features"])
    assert json.loads(json.dumps(geojson)) == geojson
    assert "__FRONTLINE_DATA__" not in html_path.read_text(encoding="utf-8")
