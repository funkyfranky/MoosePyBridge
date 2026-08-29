"""Tests for the bilateral conflict scenario contract."""

from __future__ import annotations

import asyncio

import pytest

from moosebridge.clock import DcsTime
from moosebridge.conflict_readiness import (
    ConflictCapability,
    ConflictReadinessError,
    evaluate_conflict_readiness,
)
from moosebridge.legions import Cohort, Commander, Legion
from moosebridge.models import Intel, Territory
from moosebridge.protocol import BridgeCommand
from moosebridge.sdk import MooseBridgeClient
from moosebridge.state import MooseBridgeState
from moosebridge.strategic import (
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    StrategicObjective,
)
from moosebridge.strategic_objectives import StrategicObjectiveGenerationResult
from moosebridge.strategic_scope import build_strategic_territory_scope
from moosebridge.theater_context import TheaterContext


def _territory(object_id: str, coalition: str, x0: float, x1: float) -> Territory:
    return Territory.from_payload(
        {
            "object_id": object_id,
            "dcs_name": object_id,
            "coalition": coalition,
            "vertices": [
                {"x": x0, "z": 0, "latitude": 0, "longitude": x0 / 1000},
                {"x": x1, "z": 0, "latitude": 0, "longitude": x1 / 1000},
                {"x": x1, "z": 100, "latitude": 0.001, "longitude": x1 / 1000},
                {"x": x0, "z": 100, "latitude": 0.001, "longitude": x0 / 1000},
            ],
        }
    )


def _objective(owner: str, index: int) -> StrategicObjective:
    return StrategicObjective(
        objective_id=f"OBJECTIVE:{owner}:{index}",
        name=f"{owner} objective {index}",
        kind=ObjectiveKind.OPSZONE,
        control_object_id=f"OPSZONE:{owner}:{index}",
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        owner=owner,
        components=(ObjectiveComponent(f"STATIC:{owner}:{index}"),),
        metadata={"targetable": True},
    )


def _ready_inputs() -> tuple[MooseBridgeState, object, StrategicObjectiveGenerationResult]:
    state = MooseBridgeState(mission_generation=3, clock=DcsTime(mission_time=125.0))
    territories = (
        _territory("TERRITORY:Blue", "blue", 0, 100),
        _territory("TERRITORY:Neutral", "neutral", 100, 200),
        _territory("TERRITORY:Red", "red", 200, 300),
    )
    state.territory_objects = {item.object_id: item for item in territories}
    for coalition in ("blue", "red"):
        commander = Commander.from_payload(
            {
                "object_id": f"COMMANDER:{coalition}",
                "dcs_name": coalition,
                "coalition": coalition,
                "legion_ids": [f"LEGION:{coalition}"],
            }
        )
        legion = Legion.from_payload(
            {
                "object_id": f"LEGION:{coalition}",
                "dcs_name": coalition,
                "coalition": coalition,
            }
        )
        cohort = Cohort.from_payload(
            {
                "object_id": f"COHORT:{coalition}",
                "dcs_name": coalition,
                "legion_id": legion.object_id,
                "available_asset_count": 4,
                "mission_types": ["CAPTUREZONE", "ONGUARD", "RECON", "STRIKE"],
            }
        )
        intel = Intel.from_payload(
            {
                "object_id": f"INTEL:{coalition}",
                "dcs_name": coalition,
                "coalition": coalition,
                "is_running": True,
            }
        )
        state.commander_objects[commander.object_id] = commander
        state.legion_objects[legion.object_id] = legion
        state.cohort_objects[cohort.object_id] = cohort
        state.intel_objects[intel.object_id] = intel
    objectives = StrategicObjectiveGenerationResult(
        objectives=(_objective("blue", 1), _objective("red", 1)),
        candidate_count=2,
        counts_by_scope={"blue": 1, "red": 1},
    )
    return state, build_strategic_territory_scope(territories), objectives


def test_complete_bilateral_scenario_is_ready() -> None:
    state, scope, objectives = _ready_inputs()

    report = evaluate_conflict_readiness(
        state,
        scope,  # type: ignore[arg-type]
        objectives,
        configured_theater_id="Caucasus",
        active_theater_id="Caucasus",
        intel_ids={"blue": "INTEL:blue", "red": "INTEL:red"},
    )

    assert report.ready is True
    assert report.errors == ()
    assert report.objective_count == 2
    assert report.mission_generation == 3
    assert report.coalition("blue").supports(ConflictCapability.CAPTURE)
    assert report.coalition("red").supports(ConflictCapability.DEFEND)
    assert report.coalition("red").supports(ConflictCapability.DESTROY)
    assert report.coalition("red").recon_cohort_ids == ("COHORT:red",)
    assert not any(issue.code == "recon_capability_missing" for issue in report.warnings)


def test_missing_recon_capability_is_an_actionable_non_blocking_warning() -> None:
    state, scope, objectives = _ready_inputs()
    red = state.cohort_objects["COHORT:red"]
    state.cohort_objects[red.object_id] = Cohort.from_payload(
        {
            "object_id": red.object_id,
            "dcs_name": red.dcs_name,
            "legion_id": red.legion_id,
            "available_asset_count": red.available_asset_count,
            "mission_types": ["CAPTUREZONE", "ONGUARD", "STRIKE"],
        }
    )

    report = evaluate_conflict_readiness(
        state,
        scope,  # type: ignore[arg-type]
        objectives,
        configured_theater_id="Caucasus",
        active_theater_id="Caucasus",
    )

    assert report.ready is True
    assert report.coalition("red").recon_cohort_ids == ()
    issue = next(issue for issue in report.warnings if issue.code == "recon_capability_missing")
    assert issue.coalition == "red"
    assert "lost contacts" in issue.message


def test_theater_mismatch_blocks_controller_startup() -> None:
    state, scope, objectives = _ready_inputs()

    report = evaluate_conflict_readiness(
        state,
        scope,  # type: ignore[arg-type]
        objectives,
        configured_theater_id="GermanyCW",
        active_theater_id="Caucasus",
    )

    assert report.ready is False
    assert any(issue.code == "theater_mismatch" for issue in report.errors)
    with pytest.raises(ConflictReadinessError, match="does not match active DCS theater"):
        report.require_ready()


def test_missing_red_destroy_capability_is_actionable_error() -> None:
    state, scope, objectives = _ready_inputs()
    state.cohort_objects["COHORT:red"] = Cohort.from_payload(
        {
            "object_id": "COHORT:red",
            "dcs_name": "red",
            "legion_id": "LEGION:red",
            "available_asset_count": 2,
            "mission_types": ["CAPTUREZONE", "PATROLZONE"],
        }
    )

    report = evaluate_conflict_readiness(
        state,
        scope,  # type: ignore[arg-type]
        objectives,
        configured_theater_id="Caucasus",
        active_theater_id="Caucasus",
    )

    assert report.ready is False
    issue = next(issue for issue in report.errors if issue.code == "destroy_capability_missing")
    assert issue.coalition == "red"
    assert "DESTROY" in issue.message


def test_sdk_builds_bilateral_readiness_report_from_live_state() -> None:
    class _ReadinessServer:
        def __init__(self, state: MooseBridgeState) -> None:
            self.state = state
            self.commands: list[BridgeCommand] = []

        async def send_command(
            self,
            command: BridgeCommand,
            timeout: float = 10.0,
        ) -> dict[str, object]:
            self.commands.append(command)
            assert timeout == 12.0
            assert command.action == "mission.info"
            return {
                "ok": True,
                "mission_time": 125.0,
                "dcs_time": 32_525.0,
                "mission_date": "2008/06/21",
                "result": {
                    "action": "mission.info",
                    "theater_id": "Caucasus",
                    "mission_name": "Bilateral readiness test",
                },
            }

    async def scenario() -> None:
        state, _scope, _objectives = _ready_inputs()
        state.opszones = {
            "OPSZONE:Blue": {
                "object_id": "OPSZONE:Blue",
                "name": "Blue objective",
                "owner_current_name": "blue",
                "x": 50,
                "z": 50,
            },
            "OPSZONE:Red": {
                "object_id": "OPSZONE:Red",
                "name": "Red objective",
                "owner_current_name": "red",
                "x": 250,
                "z": 50,
            },
        }
        server = _ReadinessServer(state)
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]

        report = await bridge.assess_conflict_readiness(
            theater=TheaterContext("Caucasus"),
            intel_ids={"blue": "INTEL:blue", "red": "INTEL:red"},
            refresh=False,
            timeout=12.0,
        )

        assert report.ready is True
        assert report.configured_theater_id == "Caucasus"
        assert report.active_theater_id == "Caucasus"
        assert report.objective_count == 2
        assert report.objective_generation is not None
        assert {item.owner for item in report.objective_generation.objectives} == {"blue", "red"}
        assert [command.action for command in server.commands] == ["mission.info"]

    asyncio.run(scenario())
