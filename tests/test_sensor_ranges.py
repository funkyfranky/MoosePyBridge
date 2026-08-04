from __future__ import annotations

from moosebridge.datamine_ranges import DatamineMetadata
from moosebridge.datamine_sensors import DatamineSensorData, DatamineSensorProfile
from moosebridge.diagnostics import format_sensor_range
from moosebridge.sensor_ranges import (
    DEFAULT_SENSOR_RANGE_REGISTRY,
    SensorDetectionType,
    SensorPlatformCategory,
    SensorRangeProfile,
    SensorRangeRegistry,
    SensorRangeSource,
    SensorTargetDomain,
)


def _datamine() -> DatamineSensorData:
    return DatamineSensorData(
        metadata=DatamineMetadata(dcs_build="test"),
        profiles=(
            DatamineSensorProfile(
                "Scout", "ground", "organic", "any", 8_000,
                range_scope="unit", exclusion_safe=True, basis="maxTargetDetectionRange",
            ),
            DatamineSensorProfile(
                "Scout", "ground", "radar", "air", 20_000,
                exclusion_safe=True, sensor_names=("Search Radar",),
            ),
            DatamineSensorProfile(
                "Scout", "ground", "radar", "surface", 12_000,
                exclusion_safe=True, sensor_names=("Search Radar",),
            ),
        ),
    )


def test_registry_resolves_domain_specific_upper_bounds() -> None:
    registry = SensorRangeRegistry(datamine=_datamine())

    assert registry.maximum_range_m("Scout") == 20_000
    assert registry.maximum_range_m("Scout", target_domain="air") == 20_000
    assert registry.maximum_range_m("Scout", target_domain="surface") == 12_000
    assert registry.excludes("Scout", 8_001, target_domain="surface") is True
    assert registry.excludes("Scout", 8_000, target_domain="surface") is False
    assert registry.sensor_excludes("Scout", "radar", 12_001, target_domain="surface") is True
    assert registry.excludes("Unknown", 1_000) is None


def test_manual_profile_overrides_same_datamine_profile() -> None:
    manual = SensorRangeProfile(
        dcs_type="Scout",
        platform_category=SensorPlatformCategory.GROUND,
        detection_type=SensorDetectionType.RADAR,
        target_domain=SensorTargetDomain.AIR,
        maximum_m=25_000,
        source=SensorRangeSource.MANUAL,
        exclusion_safe=True,
    )
    registry = SensorRangeRegistry((manual,), datamine=_datamine())

    profiles = registry.profiles_for("Scout", target_domain="air")
    assert any(item is manual for item in profiles)
    assert registry.maximum_range_m("Scout", target_domain="air") == 25_000


def test_sensor_exclusion_requires_every_matching_sensor_profile_to_be_bounded() -> None:
    datamine = DatamineSensorData(
        DatamineMetadata(dcs_build="test"),
        (
            DatamineSensorProfile(
                "Aircraft", "airplane", "radar", "air", 50_000,
                mode="search", exclusion_safe=True,
            ),
            DatamineSensorProfile(
                "Aircraft", "airplane", "radar", "air", None,
                mode="special", exclusion_safe=False,
            ),
        ),
    )
    registry = SensorRangeRegistry(datamine=datamine)

    assert registry.sensor_excludes("Aircraft", "radar", 60_000, target_domain="air") is None
    assert registry.sensor_excludes("Aircraft", "radar", 60_000, target_domain="air", mode="search") is True


def test_packaged_datamine_contains_known_ground_unit_bounds() -> None:
    profiles = DEFAULT_SENSOR_RANGE_REGISTRY.profiles_for("Leopard-2", target_domain="surface")

    assert profiles
    assert DEFAULT_SENSOR_RANGE_REGISTRY.maximum_range_m("Leopard-2", target_domain="surface") == 6_000
    assert DEFAULT_SENSOR_RANGE_REGISTRY.datamine_metadata.dcs_build == "2.9.28.26283"


def test_packaged_aircraft_profiles_preserve_modes_without_claiming_unit_exclusion() -> None:
    profiles = DEFAULT_SENSOR_RANGE_REGISTRY.profiles_for("FA-18C_hornet")

    assert {(item.detection_type.value, item.target_domain.value, item.mode) for item in profiles} >= {
        ("radar", "air", "air_search"),
        ("radar", "surface", "gmti"),
        ("radar", "surface", "hrm"),
        ("radar", "surface", "rbm"),
        ("rwr", "any", None),
    }
    assert DEFAULT_SENSOR_RANGE_REGISTRY.excludes("FA-18C_hornet", 1_000_000, target_domain="air") is None
    assert (
        DEFAULT_SENSOR_RANGE_REGISTRY.sensor_excludes(
            "FA-18C_hornet", "radar", 181_000, target_domain="surface", mode="rbm"
        )
        is True
    )


def test_packaged_helicopter_retains_unbounded_optic_and_bounded_radar() -> None:
    profiles = DEFAULT_SENSOR_RANGE_REGISTRY.profiles_for("AH-64D_BLK_II", target_domain="surface")

    assert any(item.detection_type.value == "optic" and item.maximum_m is None for item in profiles)
    assert any(item.detection_type.value == "radar" and item.mode == "gmti" and item.maximum_m == 40_000 for item in profiles)
    radar = next(item for item in profiles if item.detection_type.value == "radar" and item.mode == "gmti")
    rendered = format_sensor_range(radar)
    assert "maximum=40.000km" in rendered
    assert "mode=gmti" in rendered
    assert "azimuth=-45..45deg" in rendered
