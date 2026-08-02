from __future__ import annotations

import json

import pytest

pytest.importorskip("contourpy")
pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("shapely")

from shapely.geometry import Point

from moosebridge.capabilities import GroupInfluence, InfluenceKind, InfluenceReadiness
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


def test_force_anchor_keeps_living_defender_inside_own_local_field() -> None:
    result = FrontlineEngine(
        FrontlineConfig(
            grid_spacing_m=1_000,
            influence_sigma_m=20_000,
            force_anchor_sigma_m=5_000,
            simplify_tolerance_m=0,
            minimum_segment_length_m=0,
        )
    ).calculate(
        [
            ForcePoint("GROUP:Blue", "blue", -10_000, 0, weight=20),
            ForcePoint("GROUP:Red", "red", 10_000, 0, weight=1),
        ],
        area=square(),
    )
    x_index = int(abs(result.x_coordinates - 10_000).argmin())
    z_index = int(abs(result.z_coordinates).argmin())

    assert result.red_influence[z_index, x_index] > result.blue_influence[z_index, x_index]
    assert result.diagnostics["force_anchor_count"] == 1
    assert result.diagnostics["red_frontline_distance_min_m"] > 0


def test_territorial_front_stays_between_territories_while_pressure_line_moves() -> None:
    regions = [
        TerritoryControlRegion(
            "TERRITORY:Blue",
            "Blue",
            "blue",
            ((-50_000, -50_000), (-5_000, -50_000), (-5_000, 50_000), (-50_000, 50_000)),
        ),
        TerritoryControlRegion(
            "TERRITORY:Red",
            "Red",
            "red",
            ((5_000, -50_000), (50_000, -50_000), (50_000, 50_000), (5_000, 50_000)),
        ),
    ]
    result = FrontlineEngine(
        FrontlineConfig(grid_spacing_m=1_000, simplify_tolerance_m=0, minimum_segment_length_m=0)
    ).calculate(
        [
            ForcePoint("GROUP:Blue", "blue", -10_000, 0, weight=20),
            ForcePoint("GROUP:Red", "red", 10_000, 0, weight=1),
        ],
        area=square(),
        control_regions=regions,
    )

    assert result.segments
    assert result.pressure_segments
    assert max(abs(x) for segment in result.segments for x, _ in segment.points) <= 1_000
    assert min(x for segment in result.pressure_segments for x, _ in segment.points) > 5_000
    assert result.diagnostics["forward_force_count"] == 0


def test_force_outside_own_territory_can_deform_territorial_control() -> None:
    regions = [
        TerritoryControlRegion(
            "TERRITORY:Blue",
            "Blue",
            "blue",
            ((-50_000, -50_000), (-5_000, -50_000), (-5_000, 50_000), (-50_000, 50_000)),
        ),
        TerritoryControlRegion(
            "TERRITORY:Red",
            "Red",
            "red",
            ((5_000, -50_000), (50_000, -50_000), (50_000, 50_000), (5_000, 50_000)),
        ),
    ]
    result = FrontlineEngine(
        FrontlineConfig(grid_spacing_m=1_000, simplify_tolerance_m=0, minimum_segment_length_m=0)
    ).calculate(
        [
            ForcePoint("GROUP:BlueForward", "blue", 12_000, 0, weight=5),
            ForcePoint("GROUP:Red", "red", 25_000, 0, weight=1),
        ],
        area=square(),
        control_regions=regions,
    )
    x_index = int(abs(result.x_coordinates - 12_000).argmin())
    z_index = int(abs(result.z_coordinates).argmin())

    assert result.blue_influence[z_index, x_index] > result.red_influence[z_index, x_index]
    assert result.diagnostics["forward_force_count"] == 1


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
        {"object_id": "GROUP:Blue", "dcs_name": "Blue", "category": "Ground Unit", "coalition": "blue", "alive": True, "active": True, "x": 0, "z": 10},
        {"object_id": "GROUP:Red", "category": "Ground Unit", "coalition": "red", "alive": True, "active": True, "x": 100, "z": 10},
        {"object_id": "GROUP:Air", "category": "Airplane", "coalition": "blue", "alive": True, "active": True, "x": 0, "z": 0},
        {"object_id": "GROUP:Helo", "category": "Helicopter", "coalition": "blue", "alive": True, "active": True, "x": 0, "z": 0},
        {"object_id": "GROUP:Ship", "category": "Ship", "coalition": "blue", "alive": True, "active": True, "x": 0, "z": 0},
        {"object_id": "GROUP:Dead", "category": "Ground Unit", "coalition": "red", "alive": False, "active": True, "x": 0, "z": 0},
        {"object_id": "GROUP:Inactive", "category": "Ground Unit", "coalition": "blue", "alive": True, "active": False, "x": 0, "z": 0},
    ]
    tracker = FrontlineForceTracker(position_alpha=0.25)

    first = tracker.update(force_points_from_groups(groups))
    groups[0]["x"] = 100
    second = tracker.update(force_points_from_groups(groups))

    assert [force.object_id for force in first] == ["GROUP:Blue", "GROUP:Red"]
    assert second[0].x == 25


def test_weighted_group_adapter_excludes_logistics_and_inactive_groups() -> None:
    groups = [
        {"object_id": "GROUP:Armor", "category": "Ground Unit", "coalition": "blue", "alive": True, "active": True, "x": 0, "z": 0},
        {"object_id": "GROUP:Supply", "category": "Ground Unit", "coalition": "blue", "alive": True, "active": True, "x": 10, "z": 0},
        {"object_id": "GROUP:Inactive", "category": "Ground Unit", "coalition": "red", "alive": True, "active": False, "x": 20, "z": 0},
    ]
    influences = {
        "GROUP:Armor": GroupInfluence(
            "GROUP:Armor",
            (),
            (InfluenceReadiness(InfluenceKind.CONTROL, 2, 1, 1, 2),),
        ),
        "GROUP:Supply": GroupInfluence(
            "GROUP:Supply",
            (),
            (InfluenceReadiness(InfluenceKind.LOGISTICS, 0.1, 1, 1, 0.1, maximum_range_m=5_000),),
        ),
        "GROUP:Inactive": GroupInfluence(
            "GROUP:Inactive",
            (),
            (InfluenceReadiness(InfluenceKind.CONTROL, 5, 1, 1, 5),),
        ),
    }

    forces = force_points_from_groups(groups, influences=influences)

    assert [force.object_id for force in forces] == ["GROUP:Armor"]
    assert forces[0].weight == 2


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
