from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from moosebridge.clock import DcsTime
from moosebridge.ammunition import UnitAmmunition
from moosebridge.map_server import GlobalMapRuntime, compact_dcs_marker_text, create_app, empty_picture
from moosebridge.models import Territory
from moosebridge.pictures import GlobalPicture
from moosebridge.sdk import GeographicPoint
from moosebridge.state import MooseBridgeState
from moosebridge.strategic import ObjectiveKind, OwnershipPolicy, StrategicObjective
from moosebridge.surface_regions import (
    SurfaceClass,
    SurfaceRegion,
    SurfaceRegionKind,
    TheaterSurfaceRegions,
)
from moosebridge.transport_infrastructure import (
    TheaterTransportInfrastructure,
    TransportBridge,
    TransportImportanceTier,
    TransportJunction,
    TransportJunctionKind,
)
from moosebridge.infrastructure_sites import (
    EnergySite,
    EnergySource,
    FuelStorageRole,
    FuelStorageSite,
    InfrastructureSiteKind,
    InfrastructureSite,
    IndustrialRole,
    IndustrialSite,
    MaritimeRole,
    MaritimeSite,
    MilitaryRole,
    MilitarySite,
    StoredCommodity,
    TheaterInfrastructureSites,
)
from moosebridge.strategic_verification import (
    InfrastructureOperationalState,
    InfrastructureStateAssessment,
    ObservedDcsObject,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
)
from moosebridge.settlements import (
    Settlement,
    SettlementImportanceTier,
    SettlementKind,
    SettlementSizeClass,
    TheaterSettlements,
)
from moosebridge.weapon_ranges import DEFAULT_WEAPON_RANGE_REGISTRY


def _armed_unit(group_id: str) -> UnitAmmunition:
    name = group_id.removeprefix("GROUP:")
    return UnitAmmunition.from_payload(
        {
            "object_id": f"UNIT:{name}",
            "unit_id": f"UNIT:{name}",
            "unit_name": name,
            "group_id": group_id,
            "group_name": name,
            "dcs_type": "Leopard-2",
            "category": "Ground Unit",
            "attributes": ["Tanks"],
            "life": 10,
            "life0": 10,
            "weapons": [
                {
                    "id": "weapons.shells.DM53_120_AP",
                    "display_name": "DM53 (120mm APFSDS-T)",
                    "category": 0,
                    "caliber": 120,
                    "count": 10,
                    "initial_count": 10,
                }
            ],
        }
    )


def test_empty_picture_is_wgs84_geojson() -> None:
    picture = empty_picture()

    assert picture == {
        "type": "FeatureCollection",
        "features": [],
        "properties": {"scope": "global", "coordinate_system": "WGS84"},
    }


def test_map_runtime_status_uses_picture_metadata() -> None:
    runtime = GlobalMapRuntime()
    runtime.connected = True
    runtime.picture = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature"}],
        "properties": {"sequence": 12, "dcs_date": "1999/06/01", "dcs_time_of_day": "09:00:42"},
    }

    assert runtime.status_payload() == {
        "connected": True,
        "mission_generation": 0,
        "error": None,
        "feature_count": 1,
        "sequence": 12,
        "mission_time": None,
        "dcs_date": "1999/06/01",
        "dcs_time_of_day": "09:00:42",
        "wall_time": None,
        "trajectory_count": 0,
        "history_seconds": 900.0,
        "frontline_count": 0,
        "pressure_line_count": 0,
        "incursion_count": 0,
        "frontline_updated_mission_time": None,
        "influence_updated_mission_time": None,
        "frontline_error": None,
        "recon_coverage_count": 0,
        "recon_coverage_error": None,
        "strategic_objective_count": 0,
        "strategic_objective_error": None,
        "topography_viewport_available": False,
        "topography_viewport_feature_count": 0,
        "topography_viewport_error": None,
        "surface_region_count": 0,
        "surface_regions_source_complete": None,
        "transport_bridge_count": 0,
            "transport_junction_count": 0,
            "railway_infrastructure_count": 0,
            "infrastructure_site_count": 0,
            "settlement_count": 0,
            "strategic_verification_count": 0,
            "diplomacy": None,
    }


def test_map_runtime_serves_surface_regions_separately_from_mission_state() -> None:
    runtime = GlobalMapRuntime()
    runtime._surface_regions = TheaterSurfaceRegions(
        theater_id="GermanyCW",
        bounds=(53.0, 10.0, 55.0, 14.0),
        grid_spacing_m=250,
        regions=(
            SurfaceRegion(
                region_id="SURFACE:GermanyCW:LAND:1",
                surface_class=SurfaceClass.LAND,
                kind=SurfaceRegionKind.MAINLAND,
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[12.0, 54.0], [12.1, 54.0], [12.1, 54.1], [12.0, 54.0]]],
                },
                area_m2=1_000_000,
                cell_count=16,
                confidence=0.75,
                source="test",
            ),
        ),
        metadata={"source_complete": False},
    )

    payload = runtime.surface_regions_geojson()
    status = runtime.status_payload()

    assert runtime.picture == empty_picture()
    assert payload["features"][0]["properties"]["layer"] == "surface_land_regions"
    assert status["surface_region_count"] == 1
    assert status["surface_regions_source_complete"] is False


def test_map_runtime_serves_transport_infrastructure_separately_from_mission_state() -> None:
    runtime = GlobalMapRuntime()
    runtime._transport_infrastructure = TheaterTransportInfrastructure(
        theater_id="GermanyCW",
        bridges=(),
        junctions=(
            TransportJunction(
                junction_id="JUNCTION:OSM:123",
                kind=TransportJunctionKind.MAJOR_JUNCTION,
                latitude=54.0,
                longitude=12.0,
                osm_node_id=123,
                arm_count=3,
                highway_classes=("primary", "secondary"),
                bridge_adjacent=False,
            ),
        ),
    )

    payload = runtime.transport_infrastructure_geojson()
    status = runtime.status_payload()

    assert runtime.picture == empty_picture()
    assert payload["features"][0]["properties"]["layer"] == "transport_junctions"
    assert status["transport_bridge_count"] == 0
    assert status["transport_junction_count"] == 1


def test_map_runtime_serves_normalized_infrastructure_sites() -> None:
    runtime = GlobalMapRuntime()
    runtime._infrastructure_sites = TheaterInfrastructureSites(
        theater_id="GermanyCW",
        sites=(EnergySite(
            site_id="ENERGY_SITE:test",
            kind=InfrastructureSiteKind.ENERGY,
            geometry={
                "type": "Polygon",
                "coordinates": [[[11.9, 53.9], [12.1, 53.9], [12.1, 54.1], [11.9, 53.9]]],
            },
            latitude=54.0,
            longitude=12.0,
            source="test",
            confidence=0.8,
            energy_sources=(EnergySource.COAL,),
        ), FuelStorageSite(
            site_id="FUEL_STORAGE_SITE:test",
            kind=InfrastructureSiteKind.FUEL_STORAGE,
            geometry={"type": "Point", "coordinates": [12.2, 54.1]},
            latitude=54.1,
            longitude=12.2,
            source="test",
            confidence=0.8,
            storage_roles=(FuelStorageRole.TANK_FARM,),
            commodities=(StoredCommodity.PETROLEUM,),
        ), IndustrialSite(
            site_id="INDUSTRIAL_SITE:test",
            kind=InfrastructureSiteKind.INDUSTRIAL,
            geometry={
                "type": "Polygon",
                "coordinates": [[[12.3, 54.1], [12.5, 54.1], [12.5, 54.3], [12.3, 54.1]]],
            },
            latitude=54.2,
            longitude=12.4,
            source="test",
            confidence=0.8,
            roles=(IndustrialRole.MACHINERY,),
            products=("machinery",),
            footprint_area_m2=25_000,
        ), MilitarySite(
            site_id="MILITARY_SITE:test",
            kind=InfrastructureSiteKind.MILITARY,
            geometry={
                "type": "Polygon",
                "coordinates": [[[12.5, 54.2], [12.7, 54.2], [12.7, 54.4], [12.5, 54.2]]],
            },
            latitude=54.3,
            longitude=12.6,
            source="test",
            confidence=0.8,
            roles=(MilitaryRole.BASE,),
            footprint_area_m2=50_000,
        ), MaritimeSite(
            site_id="MARITIME_SITE:test",
            kind=InfrastructureSiteKind.MARITIME,
            geometry={
                "type": "Polygon",
                "coordinates": [[[12.7, 54.2], [12.9, 54.2], [12.9, 54.4], [12.7, 54.2]]],
            },
            latitude=54.3,
            longitude=12.8,
            source="test",
            confidence=0.8,
            roles=(MaritimeRole.COMMERCIAL_PORT,),
            footprint_area_m2=80_000,
        )),
    )

    payload = runtime.infrastructure_sites_geojson()

    assert payload["features"][0]["properties"]["layer"] == "energy_sites"
    assert payload["features"][0]["properties"]["source_geometry_type"] == "Polygon"
    assert payload["features"][0]["geometry"]["type"] == "Polygon"
    assert payload["features"][1]["properties"]["layer"] == "fuel_storage_sites"
    assert payload["features"][2]["properties"]["layer"] == "industrial_sites"
    assert payload["features"][2]["properties"]["source_geometry_type"] == "Polygon"
    assert payload["features"][2]["geometry"]["type"] == "Polygon"
    assert payload["features"][3]["properties"]["layer"] == "military_sites"
    assert payload["features"][3]["properties"]["source_geometry_type"] == "Polygon"
    assert payload["features"][3]["geometry"]["type"] == "Polygon"
    assert payload["features"][4]["properties"]["layer"] == "maritime_sites"
    assert payload["features"][4]["properties"]["source_geometry_type"] == "Polygon"
    assert payload["features"][4]["geometry"]["type"] == "Polygon"
    assert runtime.status_payload()["infrastructure_site_count"] == 5


def test_map_runtime_serves_normalized_settlements() -> None:
    runtime = GlobalMapRuntime()
    runtime._settlements = TheaterSettlements(
        theater_id="GermanyCW",
        settlements=(Settlement(
            settlement_id="SETTLEMENT:test",
            name="Test City",
            kind=SettlementKind.CITY,
            size_class=SettlementSizeClass.MEDIUM_CITY,
            geometry={"type": "Point", "coordinates": [12.0, 54.0]},
            latitude=54.0,
            longitude=12.0,
            source="test",
            confidence=0.8,
            importance_score=55,
            importance_tier=SettlementImportanceTier.MEDIUM,
        ),),
    )

    payload = runtime.settlements_geojson()
    status = runtime.status_payload()

    assert payload["features"][0]["properties"]["layer"] == "settlements"
    assert payload["features"][0]["properties"]["size_class"] == "medium_city"
    assert status["settlement_count"] == 1


def test_map_runtime_clears_all_mission_caches_at_session_boundary() -> None:
    runtime = GlobalMapRuntime()
    runtime.update_picture(_moving_picture(10.0))
    runtime._frontline_features.append({"type": "Feature"})
    runtime._pressure_frontline_features.append({"type": "Feature"})
    runtime._incursion_features.append({"type": "Feature"})
    runtime._recon_features.append({"type": "Feature"})
    runtime._diplomacy_event_cursor = "event-12"
    runtime._border_violation_signature = (("GROUP:Blue", "TERRITORY:Red", 10.0, True),)

    runtime.reset_mission(1)

    assert runtime._mission_generation == 1
    assert runtime.picture == empty_picture()
    assert not runtime.tracks
    assert not runtime._frontline_features
    assert not runtime._pressure_frontline_features
    assert not runtime._incursion_features
    assert not runtime._recon_features
    assert runtime._diplomacy_event_cursor is None
    assert runtime._border_violation_signature == ()


def _moving_picture(mission_time: float, *, x: float = 0, z: float = 0, alive: bool = True) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [12.0 + x / 100_000, 54.0 + z / 100_000]},
                "properties": {
                    "layer": "groups",
                    "object_id": "GROUP:Moving",
                    "name": "Moving",
                    "category": "Ground Unit",
                    "coalition": "blue",
                    "alive": alive,
                    "x": x,
                    "z": z,
                },
            }
        ],
        "properties": {"mission_time": mission_time},
    }


def test_map_runtime_builds_trajectory_and_derived_movement() -> None:
    runtime = GlobalMapRuntime(history_seconds=60, history_max_points=10)

    runtime.update_picture(_moving_picture(100, x=0, z=0))  # type: ignore[arg-type]
    picture = runtime.update_picture(_moving_picture(110, x=100, z=0))  # type: ignore[arg-type]

    group = next(feature for feature in picture["features"] if feature["properties"]["layer"] == "groups")
    trajectory = next(feature for feature in picture["features"] if feature["properties"]["layer"] == "trajectories")
    assert group["properties"]["derived_speed_mps"] == 10
    assert group["properties"]["derived_heading_deg"] == 90
    assert group["properties"]["track_distance_m"] == 100
    assert trajectory["properties"]["tracked_object_id"] == "GROUP:Moving"
    assert trajectory["properties"]["sample_count"] == 2
    assert picture["properties"]["trajectory_count"] == 1


def test_map_runtime_removes_dead_or_missing_tracks() -> None:
    runtime = GlobalMapRuntime()
    runtime.update_picture(_moving_picture(100))  # type: ignore[arg-type]

    runtime.update_picture(_moving_picture(105, alive=False))  # type: ignore[arg-type]
    assert runtime.tracks == {}

    runtime.update_picture(_moving_picture(110))  # type: ignore[arg-type]
    runtime.update_picture({"type": "FeatureCollection", "features": [], "properties": {"mission_time": 115}})
    assert runtime.tracks == {}


def test_map_runtime_resets_tracks_when_mission_time_restarts() -> None:
    runtime = GlobalMapRuntime()
    runtime.update_picture(_moving_picture(100, x=0))  # type: ignore[arg-type]
    runtime.update_picture(_moving_picture(110, x=100))  # type: ignore[arg-type]

    picture = runtime.update_picture(_moving_picture(5, x=200))  # type: ignore[arg-type]

    assert len(runtime.tracks["GROUP:Moving"]) == 1
    assert not any(feature["properties"]["layer"] == "trajectories" for feature in picture["features"])


def test_map_runtime_builds_and_reuses_live_frontline() -> None:
    class Bridge:
        calls = 0
        ammo_calls = 0
        weapon_range_registry = DEFAULT_WEAPON_RANGE_REGISTRY

        async def refresh_ammunition(self) -> tuple[UnitAmmunition, ...]:
            self.ammo_calls += 1
            return (_armed_unit("GROUP:Blue"), _armed_unit("GROUP:Red"))

        async def convert_points(self, points: list[tuple[float, float]]) -> list[GeographicPoint]:
            self.calls += 1
            return [
                GeographicPoint(x=x, y=0, z=z, latitude=54 + z / 100_000, longitude=12 + x / 100_000)
                for x, z in points
            ]

    async def scenario() -> None:
        runtime = GlobalMapRuntime(frontline_interval=15)
        bridge = Bridge()
        groups = [
            {"object_id": "GROUP:Blue", "dcs_name": "Blue", "category": "Ground Unit", "coalition": "blue", "alive": True, "active": True, "x": -15_000, "z": 0, "latitude": 54.0, "longitude": 11.85},
            {"object_id": "GROUP:Red", "dcs_name": "Red", "category": "Ground Unit", "coalition": "red", "alive": True, "active": True, "x": 15_000, "z": 0, "latitude": 54.0, "longitude": 12.15},
        ]
        first = GlobalPicture(clock=DcsTime(mission_time=100), groups=groups)
        first_geojson = await runtime.update_frontline(first, first.to_geojson(), bridge)
        second = GlobalPicture(clock=DcsTime(mission_time=105), groups=groups)
        second_geojson = await runtime.update_frontline(second, second.to_geojson(), bridge)
        third = GlobalPicture(clock=DcsTime(mission_time=120), groups=groups)
        await runtime.update_frontline(third, third.to_geojson(), bridge)
        fourth = GlobalPicture(clock=DcsTime(mission_time=165), groups=groups)
        await runtime.update_frontline(fourth, fourth.to_geojson(), bridge)

        frontlines = [feature for feature in first_geojson["features"] if feature["properties"]["layer"] == "frontlines"]
        pressure_lines = [feature for feature in first_geojson["features"] if feature["properties"]["layer"] == "pressure_frontlines"]
        assert frontlines
        assert pressure_lines
        assert frontlines[0]["geometry"]["type"] == "LineString"
        assert first_geojson["properties"]["frontline_count"] == len(frontlines)
        assert first_geojson["properties"]["pressure_line_count"] == len(pressure_lines)
        assert second_geojson["properties"]["frontline_count"] == len(frontlines)
        assert bridge.calls == 3
        assert bridge.ammo_calls == 2
        blue = next(
            feature for feature in first_geojson["features"]
            if feature["properties"].get("object_id") == "GROUP:Blue"
        )
        assert blue["properties"]["control_power"] == 1.5
        assert blue["properties"]["influence"]["direct_fire"]["maximum_range_m"] == 3_500

    asyncio.run(scenario())


def test_map_runtime_publishes_incursion_without_bending_main_front() -> None:
    class Bridge:
        weapon_range_registry = DEFAULT_WEAPON_RANGE_REGISTRY

        async def refresh_ammunition(self) -> tuple[UnitAmmunition, ...]:
            return (
                _armed_unit("GROUP:Blue"),
                _armed_unit("GROUP:RedRear"),
                _armed_unit("GROUP:RedIncursion"),
            )

        async def convert_points(self, points: list[tuple[float, float]]) -> list[GeographicPoint]:
            return [
                GeographicPoint(x=x, y=0, z=z, latitude=54 + z / 100_000, longitude=12 + x / 100_000)
                for x, z in points
            ]

    async def scenario() -> None:
        territory = Territory.from_payload(
            {
                "object_id": "TERRITORY:Blue",
                "dcs_name": "Blue",
                "name": "Blue",
                "object_type": "TERRITORY",
                "coalition": "blue",
                "vertices": [
                    {"x": -50_000, "z": -50_000, "latitude": 53.5, "longitude": 11.5},
                    {"x": 0, "z": -50_000, "latitude": 53.5, "longitude": 12.0},
                    {"x": 0, "z": 50_000, "latitude": 54.5, "longitude": 12.0},
                    {"x": -50_000, "z": 50_000, "latitude": 54.5, "longitude": 11.5},
                ],
            }
        )
        red_territory = Territory.from_payload(
            {
                "object_id": "TERRITORY:Red",
                "dcs_name": "Red",
                "name": "Red",
                "object_type": "TERRITORY",
                "coalition": "red",
                "vertices": [
                    {"x": 0, "z": -50_000, "latitude": 53.5, "longitude": 12.0},
                    {"x": 50_000, "z": -50_000, "latitude": 53.5, "longitude": 12.5},
                    {"x": 50_000, "z": 50_000, "latitude": 54.5, "longitude": 12.5},
                    {"x": 0, "z": 50_000, "latitude": 54.5, "longitude": 12.0},
                ],
            }
        )
        groups = [
            {"object_id": "GROUP:Blue", "dcs_name": "Blue", "category": "Ground Unit", "coalition": "blue", "alive": True, "active": True, "x": -30_000, "y": 0, "z": 0, "latitude": 54, "longitude": 11.7},
            {"object_id": "GROUP:RedRear", "dcs_name": "Red Rear", "category": "Ground Unit", "coalition": "red", "alive": True, "active": True, "x": 30_000, "y": 0, "z": 0, "latitude": 54, "longitude": 12.3},
            {"object_id": "GROUP:RedIncursion", "dcs_name": "Red Incursion", "category": "Ground Unit", "coalition": "red", "alive": True, "active": True, "x": -20_000, "y": 0, "z": 20_000, "latitude": 54.2, "longitude": 11.8},
        ]
        picture = GlobalPicture(clock=DcsTime(mission_time=100), groups=groups, territories=[territory, red_territory])
        runtime = GlobalMapRuntime()
        geojson = await runtime.update_frontline(picture, picture.to_geojson(), Bridge())

        incursions = [feature for feature in geojson["features"] if feature["properties"]["layer"] == "incursions"]
        assert len(incursions) == 1
        assert incursions[0]["properties"]["source_group_id"] == "GROUP:RedIncursion"
        assert geojson["properties"]["incursion_count"] == 1
        assert geojson["properties"]["frontline_diagnostics"]["main_force_count"] == 2
        assert geojson["properties"]["frontline_diagnostics"]["main_control_power_red"] == 1.5
        assert geojson["properties"]["frontline_diagnostics"]["incursion_control_power_red"] == 1.5

    asyncio.run(scenario())


def test_map_runtime_publishes_persisted_recon_coverage() -> None:
    pytest.importorskip("shapely")

    class Server:
        async def query_audit_records(self, **kwargs: object) -> tuple[dict[str, object], ...]:
            if kwargs["record_type"] == "operational_plan.execution":
                return ()
            assert kwargs == {"record_type": "recon.execution", "latest_attempts": True}
            return ({
                "recorded_at": "2026-08-04T20:00:00Z",
                "payload": {
                    "audit_session_id": "test-session",
                    "mission_generation": 0,
                    "plan_id": "PLAN:Recon",
                    "commander_id": "COMMANDER:Blue",
                    "attempt_id": "ATTEMPT:Recon:1",
                    "attempt_number": 1,
                    "status": "blocked",
                    "plan": {"coalition": "blue"},
                    "missions": [{
                        "phase_id": "recon",
                        "intent_id": "search",
                        "requirement_id": "REQ:Recon",
                        "mission_type": "RECON",
                        "required": True,
                        "status": "succeeded",
                        "auftrag_id": "AUFTRAG:1",
                        "recon_tracks": {
                            "GROUP:Reaper": [
                                {"group_id": "GROUP:Reaper", "mission_time": 10, "x": -4_000, "z": 0},
                                {"group_id": "GROUP:Reaper", "mission_time": 20, "x": 4_000, "z": 0},
                            ],
                        },
                        "recon_outcome": {
                            "auftrag_id": "AUFTRAG:1",
                            "intel_id": "INTEL:Blue",
                            "mission_outcome": {"auftrag_id": "AUFTRAG:1", "status": "done", "evaluated": True, "success": True},
                            "requirement": {
                                "area_object_id": "ZONE:Search",
                                "derive_targets": True,
                                "coverage_points": [{"object_id": "STATIC:Depot", "weight": 1, "source": "objective_component"}],
                            },
                            "spatial_coverage": {
                                "available": True,
                                "area_object_id": "ZONE:Search",
                                "area_m2": 314_000_000,
                                "searched_area_m2": 100_000_000,
                                "area_coverage_ratio": 0.32,
                                "component_coverage_ratio": 1,
                                "covered_component_ids": ["STATIC:Depot"],
                                "uncovered_component_ids": [],
                                "tracked_group_ids": ["GROUP:Reaper"],
                                "unknown_sensor_group_ids": [],
                                "sample_count": 2,
                                "sufficient": False,
                                "sensor_ranges_m": {"GROUP:Reaper": 5_000},
                            },
                            "observations": [],
                        },
                    }],
                },
            },)

    class Bridge:
        server = Server()
        state = MooseBridgeState(audit_session_id="test-session")

        async def convert_points(self, points: list[tuple[float, float]]) -> list[GeographicPoint]:
            return [
                GeographicPoint(x=x, y=0, z=z, latitude=54 + z / 100_000, longitude=12 + x / 100_000)
                for x, z in points
            ]

    async def scenario() -> None:
        runtime = GlobalMapRuntime()
        picture = GlobalPicture(
            clock=DcsTime(mission_time=30),
            zones=[{
                "object_id": "ZONE:Search", "dcs_name": "Search", "x": 0, "z": 0, "radius": 10_000,
                "latitude": 54, "longitude": 12,
            }],
            statics=[{
                "object_id": "STATIC:Depot", "dcs_name": "Depot", "x": 0, "y": 0, "z": 0,
                "latitude": 54, "longitude": 12, "alive": True,
            }],
        )
        geojson = await runtime.update_recon_coverage(picture, picture.to_geojson(), Bridge())
        coverage = [feature for feature in geojson["features"] if feature["properties"].get("layer") == "recon_coverage"]

        assert {feature["properties"]["map_category"] for feature in coverage} == {"aggregate", "assets", "covered"}
        assert sum(feature["geometry"]["type"] == "Polygon" for feature in coverage) == 2
        assert next(feature for feature in coverage if feature["properties"]["map_category"] == "assets")["properties"]["sensor_range_m"] == 5_000
        assert geojson["properties"]["recon_coverage_count"] == len(coverage)

    asyncio.run(scenario())


def test_map_runtime_task_stops_cleanly() -> None:
    async def scenario() -> None:
        runtime = GlobalMapRuntime(interval=60)
        await runtime.start()
        assert runtime._task is not None
        await runtime.stop()
        assert runtime._task is None

    asyncio.run(scenario())


def test_map_app_exposes_runtime() -> None:
    app = create_app(control_host="localhost", control_port=52001, interval=2.5, timeout=7)

    runtime = app.state.runtime
    assert runtime.control_host == "localhost"
    assert runtime.control_port == 52001
    assert runtime.interval == 2.5
    assert runtime.timeout == 7
    assert app.state.topography_tile_concurrency == 1


def test_map_runtime_creates_one_selected_strategic_goal_and_annotates_picture() -> None:
    objective = StrategicObjective(
        objective_id="OBJECTIVE:Town Fight",
        name="Town Fight",
        kind=ObjectiveKind.OPSZONE,
        control_object_id="OPSZONE:Town Fight",
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        owner="red",
        strategic_value=90,
        priority=80,
    )

    class Bridge:
        relationship = None

        def __init__(self) -> None:
            self.goals = []

        def strategic_objective(self, objective_id: str):
            return objective if objective_id == objective.objective_id else None

        def strategic_goals(self):
            return tuple(self.goals)

        def add_strategic_goal(self, goal):
            self.goals.append(goal)
            return goal

    bridge = Bridge()
    runtime = GlobalMapRuntime()
    runtime.connected = True
    runtime._mission_generation = 3
    runtime._bridge = bridge
    runtime.picture = {
        "type": "FeatureCollection",
        "properties": {"mission_time": 120.0},
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12.0, 54.0]},
            "properties": {"layer": "strategic_objectives", "object_id": objective.objective_id},
        }],
    }

    created = runtime.create_strategic_goal(objective.objective_id, "blue")

    assert created["action"] == "capture"
    assert created["status"] == "planned"
    assert created["objective_id"] == objective.objective_id
    properties = runtime.picture["features"][0]["properties"]
    assert properties["goal_count"] == 1
    assert properties["blue_goal_id"] == created["goal_id"]
    assert properties["blue_goal_action"] == "capture"
    assert properties["blue_goal_status"] == "planned"
    with pytest.raises(ValueError, match="open goal already exists"):
        runtime.create_strategic_goal(objective.objective_id, "blue")


def test_map_app_exposes_strategic_goal_creation_endpoint() -> None:
    app = create_app()
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/strategic-goals")

    assert "POST" in route.methods


def test_map_runtime_creates_compact_dcs_marker_at_wgs84_position() -> None:
    class Bridge:
        def __init__(self) -> None:
            self.calls = []

        async def mark_map_position(self, text: str, **params):
            self.calls.append((text, params))
            return {"ok": True, "result": {"mark_id": 42, "coalition": -1, "read_only": False}}

    async def scenario() -> None:
        bridge = Bridge()
        runtime = GlobalMapRuntime()
        runtime.connected = True
        runtime._bridge = bridge

        marker = await runtime.create_dcs_marker({
            "point": {"latitude": 53.92, "longitude": 12.28},
            "properties": {
                "object_id": "AIRBASE:Laage",
                "name": "Laage",
                "category": "airdrome",
                "coalition": "blue",
                "status": "operational",
            },
        })

        assert marker["mark_id"] == 42
        assert marker["text"] == "Laage\nairdrome | Blue | operational\nAIRBASE:Laage"
        assert bridge.calls[0][1]["latitude"] == 53.92
        assert bridge.calls[0][1]["longitude"] == 12.28
        assert bridge.calls[0][1]["coalition"] == "all"
        assert bridge.calls[0][1]["read_only"] is False

    asyncio.run(scenario())


def test_compact_dcs_marker_text_is_single_value_per_line_and_bounded() -> None:
    text = compact_dcs_marker_text({
        "object_id": "STATIC:" + "X" * 200,
        "name": "  Red   Supply\nDepot  ",
        "dcs_type": "fuel_storage",
        "coalition": "red",
        "alive": True,
    })

    assert text.startswith("Red Supply Depot\nfuel storage | Red | alive\nSTATIC:")
    assert len(text) <= 180


def test_map_app_exposes_dcs_marker_creation_endpoint() -> None:
    app = create_app()
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/dcs-markers")

    assert "POST" in route.methods


def test_map_runtime_persists_strategic_verification(tmp_path) -> None:
    path = tmp_path / "verifications.json"
    runtime = GlobalMapRuntime(theater_id="GermanyCW", strategic_verifications_path=path)

    verification = runtime.save_strategic_verification({
        "source_id": "ENERGY_SITE:Alpha",
        "state": "represented",
        "observed_objects": [{
            "object_id": "SCENERY:Generator-1",
            "type_name": "Generator",
            "latitude": 54.0,
            "longitude": 12.0,
        }],
        "observation_complete": True,
        "target_components": [{"object_id": "SCENERY:Generator-1", "role": "generator", "weight": 2}],
        "notes": "Matched on F10",
    })

    assert verification.admitted is True
    assert verification.observation_complete is True
    assert path.is_file()
    assert runtime.strategic_verifications_payload()["theater_id"] == "GermanyCW"
    assert runtime.strategic_verifications_payload()["verifications"][0]["source_id"] == "ENERGY_SITE:Alpha"
    assert runtime._strategic_objective_signature == ()


def test_map_runtime_rejects_verifications_from_another_theater(tmp_path) -> None:
    path = tmp_path / "verifications.json"
    StrategicVerificationRegistry(theater_id="Caucasus").save(path)

    with pytest.raises(ValueError, match="theater mismatch"):
        GlobalMapRuntime(theater_id="GermanyCW", strategic_verifications_path=path)


def test_map_app_exposes_strategic_verification_endpoints() -> None:
    app = create_app()
    routes = {getattr(route, "path", None): route for route in app.routes}

    assert "GET" in routes["/api/strategic-verifications"].methods
    assert "PUT" in routes["/api/strategic-verifications/{source_id:path}"].methods
    assert "POST" in routes["/api/strategic-verifications/{source_id:path}/assess"].methods


def test_map_runtime_assesses_verified_infrastructure_on_demand(tmp_path) -> None:
    async def run() -> None:
        path = tmp_path / "verifications.json"
        site = InfrastructureSite(
            site_id="MILITARY_SITE:Barracks",
            kind=InfrastructureSiteKind.MILITARY,
            geometry={"type": "Point", "coordinates": [12.0, 54.0]},
            latitude=54.0,
            longitude=12.0,
            source="OpenStreetMap",
            confidence=0.75,
        )
        verification = StrategicSiteVerification(
            source_id=site.site_id,
            observed_objects=(ObservedDcsObject("SCENERY:1"),),
            observation_complete=True,
        )
        runtime = GlobalMapRuntime(strategic_verifications_path=path)
        runtime._strategic_verifications.upsert(verification)
        runtime._strategic_verifications.save(path)
        runtime._infrastructure_sites = TheaterInfrastructureSites("GermanyCW", (site,))

        class FakeBridge:
            async def assess_scenery_verification(self, candidate, baseline, *, timeout):
                assert candidate.object_id == site.site_id
                assert candidate.artifact_key == "infrastructure_sites"
                assert baseline.source_id == site.site_id
                assert timeout == runtime.timeout
                return InfrastructureStateAssessment(
                    source_id=site.site_id,
                    state=InfrastructureOperationalState.OPERATIONAL,
                    baseline_count=1,
                    intact_count=1,
                    damaged_count=0,
                    destroyed_count=0,
                    unknown_count=0,
                    health_min=1.0,
                    health_max=1.0,
                    complete=True,
                )

        runtime._bridge = FakeBridge()
        runtime.connected = True

        result = await runtime.assess_strategic_verification(site.site_id)

        assert result["state"] == "operational"
        assert result["complete"] is True

    asyncio.run(run())


def test_map_runtime_assesses_verified_transport_bridge_on_demand(tmp_path) -> None:
    async def run() -> None:
        path = tmp_path / "verifications.json"
        bridge_feature = TransportBridge(
            bridge_id="BRIDGE:Caucasus:4d482fb330eb",
            geometry={"type": "Point", "coordinates": [41.68362, 41.66473]},
            latitude=41.66473,
            longitude=41.68362,
            length_m=120.0,
            highway_classes=("primary",),
            edge_count=1,
            approach_count=2,
            endpoint_osm_ids=(1, 2),
            importance_score=66.0,
            importance_tier=TransportImportanceTier.MEDIUM,
        )
        verification = StrategicSiteVerification(
            source_id=bridge_feature.bridge_id,
            observed_objects=(ObservedDcsObject("SCENERY:70254625"),),
            observation_complete=True,
        )
        runtime = GlobalMapRuntime(theater_id="Caucasus", strategic_verifications_path=path)
        runtime._strategic_verifications.upsert(verification)
        runtime._strategic_verifications.save(path)
        runtime._transport_infrastructure = TheaterTransportInfrastructure(
            "Caucasus",
            (bridge_feature,),
            (),
        )

        class FakeBridge:
            async def assess_scenery_verification(self, candidate, baseline, *, timeout):
                assert candidate.object_id == bridge_feature.bridge_id
                assert candidate.artifact_key == "transport_infrastructure"
                assert candidate.category == "bridge"
                assert baseline == verification
                assert timeout == runtime.timeout
                return InfrastructureStateAssessment(
                    source_id=bridge_feature.bridge_id,
                    state=InfrastructureOperationalState.OPERATIONAL,
                    baseline_count=1,
                    intact_count=1,
                    damaged_count=0,
                    destroyed_count=0,
                    unknown_count=0,
                    health_min=1.0,
                    health_max=1.0,
                    complete=True,
                )

        runtime._bridge = FakeBridge()
        runtime.connected = True

        result = await runtime.assess_strategic_verification(bridge_feature.bridge_id)

        assert result["state"] == "operational"
        assert result["baseline_count"] == 1

    asyncio.run(run())


def test_map_ui_does_not_apply_tactical_filters_to_topography() -> None:
    map_script = (
        Path(__file__).parents[1] / "python" / "moosebridge" / "map_ui" / "map.js"
    ).read_text(encoding="utf-8")

    assert "const tacticalFilters = isTopographyLayer(checkbox.dataset.layer)" in map_script
    assert "[mapLayerBaseFilters.get(id), ...tacticalFilters]" in map_script


def test_map_ui_exposes_objective_filters_and_goal_selection() -> None:
    map_script = (
        Path(__file__).parents[1] / "python" / "moosebridge" / "map_ui" / "map.js"
    ).read_text(encoding="utf-8")

    assert 'key: "objective_owner"' in map_script
    assert 'key: "objective_category"' in map_script
    assert 'key: "objective_rank"' in map_script
    assert 'spec.layer === layer' in map_script
    assert 'fetch("/api/strategic-goals"' in map_script
    assert 'addStrategicGoalControls(properties)' in map_script


def test_map_ui_exposes_selected_object_f10_marker_action() -> None:
    root = Path(__file__).parents[1] / "python" / "moosebridge" / "map_ui"
    map_script = (root / "map.js").read_text(encoding="utf-8")
    index = (root / "index.html").read_text(encoding="utf-8")

    assert 'id="detail-f10-marker"' in index
    assert 'fetch("/api/dcs-markers"' in map_script
    assert "function markerPointForFeature(feature)" in map_script
    assert 'elements.detailF10Marker.addEventListener("click", createF10Marker)' in map_script


def test_map_ui_exposes_strategic_dcs_verification_controls() -> None:
    map_script = (
        Path(__file__).parents[1] / "python" / "moosebridge" / "map_ui" / "map.js"
    ).read_text(encoding="utf-8")

    assert 'function addStrategicVerificationControls(properties)' in map_script
    assert 'fetch("/api/strategic-verifications")' in map_script
    assert '/api/strategic-verifications/${encodeURIComponent(sourceId)}' in map_script
    assert '/api/strategic-verifications/${encodeURIComponent(sourceId)}/assess' in map_script
    assert "Assess current state" in map_script
    assert "const strategicVerificationAssessments = new Map();" in map_script
    assert "strategicVerificationAssessments.set(sourceId, assessment);" in map_script
    assert "strategicVerificationAssessments.delete(sourceId);" in map_script
    assert "strategicVerificationAssessments.clear();" in map_script
    assert 'addStrategicVerificationControls(properties)' in map_script
    assert "function withCurrentStrategicVerification(properties)" in map_script
    assert "strategicVerificationDetailProperties(saved)" in map_script
    assert '["unverified", "Unverified"], ["represented", "Represented"]' in map_script
    assert 'not_represented: "Not represented"' in map_script
    assert "Scenario approved" not in map_script


def test_map_ui_exposes_grouped_railway_infrastructure() -> None:
    map_script = (
        Path(__file__).parents[1] / "python" / "moosebridge" / "map_ui" / "map.js"
    ).read_text(encoding="utf-8")

    assert 'key: "railway_infrastructure", label: "Rail infrastructure"' in map_script
    assert 'fetch("/api/railway-infrastructure/global.geojson")' in map_script
    assert 'source: "railway-infrastructure"' in map_script
    assert 'addDetailSection("Rail network impact", "network"' in map_script
    assert '"Network disconnected"' in map_script
