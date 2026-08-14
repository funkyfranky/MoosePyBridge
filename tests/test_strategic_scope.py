"""Tests for TERRITORY-derived strategic mission scope."""

from __future__ import annotations

import pytest

from moosebridge.diagnostics import format_strategic_scope
from moosebridge.models import Territory
from moosebridge.pictures import GlobalPicture
from moosebridge.strategic_scope import (
    OpposingTerritoryOverlapPolicy,
    StrategicScopeConfig,
    StrategicScopeState,
    StrategicScopeValidationError,
    build_strategic_territory_scope,
)


def _territory(object_id: str, coalition: str, bounds: tuple[float, float, float, float]) -> Territory:
    min_x, min_z, max_x, max_z = bounds
    return Territory.from_payload(
        {
            "object_id": object_id,
            "dcs_name": object_id.removeprefix("TERRITORY:"),
            "object_type": "TERRITORY",
            "coalition": coalition,
            "shape": "polygon",
            "x": (min_x + max_x) / 2,
            "z": (min_z + max_z) / 2,
            "longitude": (min_x + max_x) / 2000,
            "latitude": (min_z + max_z) / 2000,
            "vertices": [
                {"x": min_x, "z": min_z, "longitude": min_x / 1000, "latitude": min_z / 1000},
                {"x": max_x, "z": min_z, "longitude": max_x / 1000, "latitude": min_z / 1000},
                {"x": max_x, "z": max_z, "longitude": max_x / 1000, "latitude": max_z / 1000},
                {"x": min_x, "z": max_z, "longitude": min_x / 1000, "latitude": max_z / 1000},
            ],
        }
    )


def test_blue_and_red_override_neutral_and_outside_is_out_of_scope() -> None:
    scope = build_strategic_territory_scope(
        [
            _territory("TERRITORY:Neutral", "neutral", (0, 0, 100, 100)),
            _territory("TERRITORY:Blue", "blue", (10, 10, 40, 40)),
            _territory("TERRITORY:Red", "red", (60, 60, 90, 90)),
        ]
    )

    assert scope.classify_point(20, 20) is StrategicScopeState.BLUE
    assert scope.classify_point(70, 70) is StrategicScopeState.RED
    assert scope.classify_point(50, 50) is StrategicScopeState.NEUTRAL
    assert scope.classify_point(110, 50) is StrategicScopeState.OUT_OF_SCOPE
    assert scope.classify_geographic_point(0.02, 0.02) is StrategicScopeState.BLUE
    assert scope.classify_geographic_point(0.05, 0.05) is StrategicScopeState.NEUTRAL
    assert scope.neutral.area == pytest.approx(8200)
    assert scope.valid


def test_opposing_overlap_is_an_error_by_default() -> None:
    territories = [
        _territory("TERRITORY:Blue", "blue", (0, 0, 60, 60)),
        _territory("TERRITORY:Red", "red", (40, 40, 100, 100)),
    ]

    with pytest.raises(StrategicScopeValidationError) as exc_info:
        build_strategic_territory_scope(territories)

    assert exc_info.value.scope.overlap_area_m2 == pytest.approx(400)
    assert exc_info.value.scope.classify_point(50, 50) is StrategicScopeState.CONTESTED


def test_explicit_contested_policy_keeps_overlap_with_warning() -> None:
    scope = build_strategic_territory_scope(
        [
            _territory("TERRITORY:Blue", "blue", (0, 0, 60, 60)),
            _territory("TERRITORY:Red", "red", (40, 40, 100, 100)),
        ],
        config=StrategicScopeConfig(
            opposing_overlap_policy=OpposingTerritoryOverlapPolicy.CONTESTED,
        ),
    )

    assert scope.valid
    assert scope.classify_point(50, 50) is StrategicScopeState.CONTESTED
    assert scope.blue.area == pytest.approx(3200)
    assert scope.red.area == pytest.approx(3200)
    assert scope.to_geojson_features()[-1]["properties"]["scope_state"] == "contested"


def test_global_picture_exports_scope_geometry_and_diagnostics() -> None:
    territories = [
        _territory("TERRITORY:Neutral", "neutral", (0, 0, 100, 100)),
        _territory("TERRITORY:Blue", "blue", (0, 0, 40, 100)),
    ]
    scope = build_strategic_territory_scope(territories)
    picture = GlobalPicture(territories=territories, strategic_scope=scope)

    geojson = picture.to_geojson()
    scope_features = [
        feature for feature in geojson["features"] if feature["properties"]["layer"] == "strategic_scope"
    ]

    assert {feature["properties"]["scope_state"] for feature in scope_features} == {"blue", "neutral"}
    assert geojson["properties"]["strategic_scope"]["valid"] is True
    assert "area blue=" in format_strategic_scope(scope)
    assert picture.validate() == []
