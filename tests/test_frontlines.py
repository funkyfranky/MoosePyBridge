from __future__ import annotations

import json

import pytest

pytest.importorskip("contourpy")
pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("shapely")

from shapely.geometry import Point

from moosebridge.frontline_diagnostics import write_frontline_diagnostic_html
from moosebridge.frontlines import (
    ForcePoint,
    FrontlineCalculationArea,
    FrontlineConfig,
    FrontlineEngine,
    FrontlineForceTracker,
    TerritoryControlRegion,
    classify_frontline_forces,
    force_points_from_groups,
)
from moosebridge.models import Territory


def square() -> FrontlineCalculationArea:
    return FrontlineCalculationArea(
        "Test",
        ((-50_000, -50_000), (50_000, -50_000), (50_000, 50_000), (-50_000, 50_000)),
    )


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
    result = FrontlineEngine(config).calculate(
        [],
        area=FrontlineCalculationArea("Odd", ((0, 0), (10_001, 0), (10_001, 10_001), (0, 10_001))),
    )

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

    area = FrontlineCalculationArea.from_territory(territory)

    assert area.name == "North"
    assert area.vertices[2] == (10_000.0, 10_000.0)


def test_combined_territories_span_neutral_gap() -> None:
    left = Territory.from_payload(
        {
            "object_id": "TERRITORY:Blue",
            "dcs_name": "Blue",
            "object_type": "TERRITORY",
            "vertices": [{"x": 0, "z": 0}, {"x": 10, "z": 0}, {"x": 10, "z": 10}, {"x": 0, "z": 10}],
        }
    )
    right = Territory.from_payload(
        {
            "object_id": "TERRITORY:Red",
            "dcs_name": "Red",
            "object_type": "TERRITORY",
            "vertices": [{"x": 20, "z": 0}, {"x": 30, "z": 0}, {"x": 30, "z": 10}, {"x": 20, "z": 10}],
        }
    )

    area = FrontlineCalculationArea.from_territories([left, right])

    assert area.geometry.covers(Point(15, 5))


def test_live_group_adapter_and_position_smoothing() -> None:
    groups = [
        {"object_id": "GROUP:Blue", "dcs_name": "Blue", "category": "Ground Unit", "coalition": "blue", "alive": True, "x": 0, "z": 10},
        {"object_id": "GROUP:Red", "category": "Ground Unit", "coalition": "red", "alive": True, "x": 100, "z": 10},
        {"object_id": "GROUP:Air", "category": "Airplane", "coalition": "blue", "alive": True, "x": 0, "z": 0},
        {"object_id": "GROUP:Helo", "category": "Helicopter", "coalition": "blue", "alive": True, "x": 0, "z": 0},
        {"object_id": "GROUP:Ship", "category": "Ship", "coalition": "blue", "alive": True, "x": 0, "z": 0},
        {"object_id": "GROUP:Dead", "category": "Ground Unit", "coalition": "red", "alive": False, "x": 0, "z": 0},
    ]
    tracker = FrontlineForceTracker(position_alpha=0.25)

    first = tracker.update(force_points_from_groups(groups))
    groups[0]["x"] = 100
    second = tracker.update(force_points_from_groups(groups))

    assert [force.object_id for force in first] == ["GROUP:Blue", "GROUP:Red"]
    assert second[0].x == 25


def test_isolated_hostile_territory_force_becomes_incursion() -> None:
    blue_region = TerritoryControlRegion(
        "TERRITORY:Blue",
        "Blue",
        "blue",
        ((-50_000, -50_000), (0, -50_000), (0, 50_000), (-50_000, 50_000)),
    )
    forces = [
        ForcePoint("GROUP:Blue", "blue", -30_000, 0),
        ForcePoint("GROUP:RedRear", "red", 30_000, 0),
        ForcePoint("GROUP:RedIncursion", "red", -20_000, 0),
    ]

    classified = classify_frontline_forces(forces, [blue_region], support_radius_m=30_000)

    assert [force.object_id for force in classified.main_forces] == ["GROUP:Blue", "GROUP:RedRear"]
    assert [incursion.force.object_id for incursion in classified.incursions] == ["GROUP:RedIncursion"]
    assert classified.incursions[0].nearest_external_support_m == 50_000


def test_supported_or_established_hostile_forces_remain_on_main_front() -> None:
    blue_region = TerritoryControlRegion(
        "TERRITORY:Blue",
        "Blue",
        "blue",
        ((-50_000, -50_000), (0, -50_000), (0, 50_000), (-50_000, 50_000)),
    )
    supported = classify_frontline_forces(
        [
            ForcePoint("GROUP:Inside", "red", -10_000, 0),
            ForcePoint("GROUP:Outside", "red", 10_000, 0),
        ],
        [blue_region],
    )
    lodgement = classify_frontline_forces(
        [
            ForcePoint("GROUP:One", "red", -20_000, 0),
            ForcePoint("GROUP:Two", "red", -18_000, 0),
            ForcePoint("GROUP:Three", "red", -16_000, 0),
        ],
        [blue_region],
    )

    assert supported.incursions == ()
    assert lodgement.incursions == ()


def test_territory_control_is_a_weak_owner_prior() -> None:
    region = TerritoryControlRegion(
        "TERRITORY:Blue",
        "Blue",
        "blue",
        ((-50_000, -50_000), (0, -50_000), (0, 50_000), (-50_000, 50_000)),
    )
    forces = [ForcePoint("GROUP:Blue", "blue", -20_000, 0), ForcePoint("GROUP:Red", "red", 20_000, 0)]
    without_prior = FrontlineEngine(FrontlineConfig(territory_control_ratio=0)).calculate(forces, area=square())
    with_prior = FrontlineEngine(FrontlineConfig(territory_control_ratio=0.08)).calculate(
        forces,
        area=square(),
        control_regions=[region],
    )
    x_index = int(abs(with_prior.x_coordinates + 10_000).argmin())
    z_index = int(abs(with_prior.z_coordinates).argmin())

    assert with_prior.blue_influence[z_index, x_index] > without_prior.blue_influence[z_index, x_index]
    assert with_prior.red_influence[z_index, x_index] == without_prior.red_influence[z_index, x_index]
    assert with_prior.diagnostics["territory_control_region_count"] == 1


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
