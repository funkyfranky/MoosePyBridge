from __future__ import annotations

import asyncio
import json

from moosebridge import (
    AssetRequirement,
    AssetRole,
    DestroyedObjectEvent,
    InformationRequirement,
    KillEvent,
    MissionIntent,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveComponent,
    ObjectiveKind,
    ObjectiveStatus,
    OperationalPlan,
    OwnershipPolicy,
    PlanPhase,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
    EscalationIncidentType,
    RelationshipState,
    ObservedDcsObject,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
    Territory,
    VerifiedDcsComponent,
)
from moosebridge.state import MooseBridgeState


def destroyed_message() -> dict[str, object]:
    return {
        "type": "event",
        "id": "event-unit-lost-1",
        "event": "object.destroyed",
        "mission_time": 125.5,
        "payload": {
            "object_id": "UNIT:Armor-1-1",
            "object_type": "UNIT",
            "group_id": "GROUP:Armor-1",
            "dcs_event_time": 125.25,
            "dcs_event_name": "S_EVENT_UNIT_LOST",
            "object": {
                "object_id": "UNIT:Armor-1-1",
                "dcs_name": "Armor-1-1",
                "object_type": "UNIT",
                "group_name": "Armor-1",
                "coalition": "red",
                "alive": False,
                "active": False,
                "x": 100,
                "y": 20,
                "z": 200,
                "latitude": 54.1,
                "longitude": 12.2,
            },
            "group": {
                "object_id": "GROUP:Armor-1",
                "alive": True,
                "active": True,
                "unit_count": 2,
                "alive_unit_count": 1,
            },
        },
    }


def destroyed_scenery_message(object_id: str, event_id: str) -> dict[str, object]:
    return {
        "type": "event",
        "id": event_id,
        "event": "object.destroyed",
        "mission_time": 150.0,
        "payload": {
            "object_id": object_id,
            "object_type": "SCENERY",
            "dcs_event_time": 149.8,
            "dcs_event_name": "S_EVENT_DEAD",
            "object": {
                "object_id": object_id,
                "dcs_name": object_id.partition(":")[2],
                "object_type": "SCENERY",
                "category": "Scenery",
                "dcs_type": "MOST(ROAD)BIG",
                "alive": False,
                "active": False,
                "x": -349070.875,
                "y": 21.559,
                "z": 623555.0,
                "latitude": 41.66473,
                "longitude": 41.68362,
            },
        },
    }


def mission_ended_message() -> dict[str, object]:
    return {
        "type": "event",
        "id": "event-mission-ended-1",
        "event": "mission.ended",
        "mission_time": 900.0,
        "payload": {
            "dcs_event_name": "S_EVENT_MISSION_END",
            "dcs_event_time": 900.0,
            "reason": "dcs_mission_end",
        },
    }


def kill_message() -> dict[str, object]:
    return {
        "type": "event",
        "id": "event-kill-1",
        "event": "combat.kill",
        "mission_time": 130.0,
        "payload": {
            "dcs_event_name": "S_EVENT_KILL",
            "dcs_event_time": 129.8,
            "killer_object_id": "UNIT:Blue Tank-1",
            "killer_group_id": "GROUP:Blue Tank",
            "killer_coalition": "blue",
            "killer_type": "M-1 Abrams",
            "target_object_id": "UNIT:Red Tank-1",
            "target_group_id": "GROUP:Red Tank",
            "target_coalition": "red",
            "target_type": "T-72B",
            "weapon_name": "M256",
        },
    }


def airbase_captured_message() -> dict[str, object]:
    return {
        "type": "event",
        "id": "event-base-captured-1",
        "event": "airbase.coalition_changed",
        "mission_time": 240.0,
        "payload": {
            "airbase_id": "AIRBASE:Tutow",
            "previous_coalition": "red",
            "coalition": "blue",
            "capturing_coalition": "blue",
            "capturing_unit_id": "UNIT:Blue Armor-1",
            "capturing_group_id": "GROUP:Blue Armor",
            "airbase": {
                "object_id": "AIRBASE:Tutow",
                "dcs_name": "Tutow",
                "category": "Airdrome",
                "coalition": "blue",
                "x": 500,
                "z": 500,
            },
        },
    }


def opszone_captured_message() -> dict[str, object]:
    return {
        "type": "event",
        "id": "event-opszone-captured-1",
        "event": "opszone.owner_changed",
        "mission_time": 260.0,
        "payload": {
            "opszone_id": "OPSZONE:Town Fight",
            "previous_coalition": "red",
            "coalition": "blue",
            "capturing_coalition": "blue",
            "fsm_event": "Captured",
            "opszone": {
                "object_id": "OPSZONE:Town Fight",
                "name": "Town Fight",
                "owner_previous_name": "red",
                "owner_current_name": "blue",
                "x": 500,
                "z": 500,
            },
        },
    }


def add_red_territory(bridge: MooseBridgeClient) -> None:
    territory = Territory.from_payload(
        {
            "object_id": "TERRITORY:Red",
            "dcs_name": "Red",
            "coalition": "red",
            "vertices": [
                {"x": 0, "z": 0},
                {"x": 1000, "z": 0},
                {"x": 1000, "z": 1000},
                {"x": 0, "z": 1000},
            ],
        }
    )
    bridge.state.territory_objects[territory.object_id] = territory


def test_destroyed_object_event_model() -> None:
    event = DestroyedObjectEvent.from_message(destroyed_message())

    assert event.object_id == "UNIT:Armor-1-1"
    assert event.group_id == "GROUP:Armor-1"
    assert event.coalition == "red"
    assert event.mission_time == 125.5
    assert event.dcs_event_time == 125.25
    assert event.dcs_event_name == "S_EVENT_UNIT_LOST"


def test_kill_event_model_and_diplomatic_incident_are_attributed_once() -> None:
    event = KillEvent.from_message(kill_message())
    assert event.killer_object_id == "UNIT:Blue Tank-1"
    assert event.target_object_id == "UNIT:Red Tank-1"
    assert event.killer_coalition == "blue"
    assert event.target_coalition == "red"
    assert event.weapon_name == "M256"

    bridge = MooseBridgeClient(MooseBridgeServer())
    bridge._on_bridge_message(kill_message())
    replay = kill_message()
    replay["id"] = "event-kill-replayed"
    bridge._on_bridge_message(replay)

    assert len(bridge.relationship.incidents) == 1
    incident = bridge.relationship.incidents[0]
    assert incident.actor_coalition == "blue"
    assert incident.target_coalition == "red"
    assert incident.reference_id == "UNIT:Red Tank-1"
    assert bridge.relationship.escalation_score == 20
    assert bridge.relationship.state is RelationshipState.TENSE
    assert bridge.relationship.pending_transition is None


def test_enemy_airbase_capture_is_one_strong_attributed_escalation() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    add_red_territory(bridge)

    bridge._on_bridge_message(airbase_captured_message())
    replay = airbase_captured_message()
    replay["id"] = "event-base-captured-replayed"
    bridge._on_bridge_message(replay)

    assert len(bridge.relationship.incidents) == 1
    incident = bridge.relationship.incidents[0]
    assert incident.incident_type is EscalationIncidentType.OBJECTIVE_CAPTURED
    assert incident.actor_coalition == "blue"
    assert incident.target_coalition == "red"
    assert incident.reference_id == "AIRBASE:Tutow"
    assert bridge.relationship.escalation_score == 60
    assert bridge.relationship.state is RelationshipState.LIMITED_CONFLICT
    assert bridge.relationship.pending_transition is None


def test_airbase_capture_can_escalate_existing_tension_to_war() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    add_red_territory(bridge)
    bridge._on_bridge_message(kill_message())
    assert bridge.relationship.state is RelationshipState.TENSE

    bridge._on_bridge_message(airbase_captured_message())

    assert bridge.relationship.escalation_score == 80
    assert bridge.relationship.state is RelationshipState.WAR
    assert bridge.relationship.pending_transition is None


def test_neutral_airbase_capture_in_no_mans_land_is_weak_escalation() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    message = airbase_captured_message()
    message["payload"]["previous_coalition"] = "neutral"  # type: ignore[index]
    message["payload"]["airbase"]["x"] = 5000  # type: ignore[index]

    bridge._on_bridge_message(message)

    assert len(bridge.relationship.incidents) == 1
    assert bridge.relationship.escalation_score == 15
    assert bridge.relationship.pending_transition is None
    assert bridge.relationship.incidents[0].details["territory_context"] == "no_mans_land"
    assert bridge.relationship.incidents[0].details["escalation_points"] == 15


def test_enemy_farp_capture_is_quarter_of_equivalent_airdrome() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    add_red_territory(bridge)
    message = airbase_captured_message()
    message["payload"]["airbase"]["category"] = "Heliport"  # type: ignore[index]

    bridge._on_bridge_message(message)

    assert bridge.relationship.escalation_score == 15
    assert bridge.relationship.pending_transition is None
    assert bridge.relationship.incidents[0].details["escalation_points"] == 15


def test_enemy_airdrome_capture_in_no_mans_land_scores_forty() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    message = airbase_captured_message()
    message["payload"]["airbase"]["x"] = 5000  # type: ignore[index]

    bridge._on_bridge_message(message)

    assert bridge.relationship.escalation_score == 40
    assert bridge.relationship.incidents[0].details["escalation_points"] == 40


def test_neutral_airdrome_capture_in_opposing_territory_scores_thirty() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    add_red_territory(bridge)
    message = airbase_captured_message()
    message["payload"]["previous_coalition"] = "neutral"  # type: ignore[index]

    bridge._on_bridge_message(message)

    assert bridge.relationship.escalation_score == 30
    assert bridge.relationship.incidents[0].details["escalation_points"] == 30


def test_enemy_opszone_capture_uses_configurable_strategic_value_once() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    add_red_territory(bridge)
    assert bridge.set_opszone_strategic_value("OPSZONE:Town Fight", 35) == 35

    message = opszone_captured_message()
    bridge._on_bridge_message(message)
    replay = opszone_captured_message()
    replay["id"] = "event-opszone-captured-replayed"
    bridge._on_bridge_message(replay)

    assert len(bridge.relationship.incidents) == 1
    incident = bridge.relationship.incidents[0]
    assert incident.incident_type is EscalationIncidentType.OPSZONE_CAPTURED
    assert incident.actor_coalition == "blue"
    assert incident.target_coalition == "red"
    assert incident.reference_id == "OPSZONE:Town Fight"
    assert incident.details["reference_points"] == 35
    assert incident.details["escalation_points"] == 35
    assert bridge.relationship.escalation_score == 35
    assert bridge.relationship.state is RelationshipState.TENSE


def test_neutral_opszone_capture_in_no_mans_land_uses_quarter_default_value() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    message = opszone_captured_message()
    message["payload"]["previous_coalition"] = "neutral"  # type: ignore[index]
    message["payload"]["opszone"]["owner_previous_name"] = "neutral"  # type: ignore[index]
    message["payload"]["opszone"]["x"] = 5000  # type: ignore[index]

    bridge._on_bridge_message(message)

    assert bridge.relationship.escalation_score == 5
    assert bridge.relationship.state is RelationshipState.PEACE
    assert bridge.relationship.incidents[0].details["territory_context"] == "no_mans_land"
    assert bridge.relationship.incidents[0].details["escalation_points"] == 5


def test_opszone_capture_at_mission_start_is_still_an_incident() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    add_red_territory(bridge)
    message = opszone_captured_message()
    message["mission_time"] = 1.0

    bridge._on_bridge_message(message)

    assert len(bridge.relationship.incidents) == 1
    assert bridge.relationship.incidents[0].incident_type is EscalationIncidentType.OPSZONE_CAPTURED
    assert bridge.relationship.escalation_score == 20
    assert bridge.relationship.state is RelationshipState.TENSE


def test_neutral_farp_capture_in_no_mans_land_scores_five() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    message = airbase_captured_message()
    message["payload"]["previous_coalition"] = "neutral"  # type: ignore[index]
    message["payload"]["airbase"]["category"] = "Heliport"  # type: ignore[index]
    message["payload"]["airbase"]["x"] = 5000  # type: ignore[index]

    bridge._on_bridge_message(message)

    assert bridge.relationship.escalation_score == 5
    assert bridge.relationship.incidents[0].details["escalation_points"] == 5


def test_object_destroyed_event_updates_state_without_snapshot() -> None:
    state = MooseBridgeState()
    state.units["UNIT:Armor-1-1"] = {
        "object_id": "UNIT:Armor-1-1",
        "dcs_type": "T-72B",
        "alive": True,
        "active": True,
        "x": 100,
        "z": 200,
    }
    state.groups["GROUP:Armor-1"] = {
        "object_id": "GROUP:Armor-1",
        "alive": True,
        "unit_count": 2,
        "alive_unit_count": 2,
    }
    state.ammunition["UNIT:Armor-1-1"] = {"object_id": "UNIT:Armor-1-1"}
    state.ammunition_objects["UNIT:Armor-1-1"] = object()  # type: ignore[assignment]

    state.apply_message(destroyed_message())

    unit = state.units["UNIT:Armor-1-1"]
    assert unit["alive"] is False
    assert unit["active"] is False
    assert unit["dcs_type"] == "T-72B"
    assert unit["x"] == 100
    assert state.groups["GROUP:Armor-1"]["alive_unit_count"] == 1
    assert "UNIT:Armor-1-1" not in state.ammunition
    assert "UNIT:Armor-1-1" not in state.ammunition_objects
    assert "UNIT:Armor-1-1" in state.destroyed_object_ids
    report = state.loss_reports["LOSS:event-unit-lost-1"]
    assert report["target_object_id"] == "UNIT:Armor-1-1"
    assert report["victim_coalition"] == "red"
    assert report["visible_to"] == ["blue", "red"]
    assert report["confidence"] == "confirmed"
    assert report["longitude"] == 12.2


def test_destroyed_scenery_object_is_retained_for_infrastructure_assessment() -> None:
    state = MooseBridgeState()
    message = destroyed_message()
    message["payload"]["object_id"] = "SCENERY:42"  # type: ignore[index]
    message["payload"]["object_type"] = "SCENERY"  # type: ignore[index]
    message["payload"]["object"] = {"object_id": "SCENERY:42", "category": "Scenery"}  # type: ignore[index]

    state.apply_message(message)

    assert "SCENERY:42" in state.destroyed_object_ids
    assert not state.loss_reports


def test_strategic_scenery_destruction_updates_one_aggregate_loss_report() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        source_id = "BRIDGE:Caucasus:test"
        verification = StrategicSiteVerification(
            source_id=source_id,
            state="represented",
            observed_objects=(
                ObservedDcsObject("SCENERY:42", type_name="MOST(ROAD)BIG", life=500.0),
                ObservedDcsObject("SCENERY:43", type_name="MOST(ROAD)BIG_END", life=100.0),
            ),
            observation_complete=True,
            target_components=(VerifiedDcsComponent("SCENERY:42", role="bridge span"),),
        )
        bridge._strategic_verifications = StrategicVerificationRegistry(
            theater_id="Caucasus",
            entries={source_id: verification},
        )
        bridge.add_strategic_objective(
            StrategicObjective(
                objective_id=f"OBJECTIVE:{source_id}",
                name="Batumi bridge",
                kind=ObjectiveKind.INFRASTRUCTURE,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
                owner="red",
                components=(ObjectiveComponent("SCENERY:42"),),
                metadata={
                    "generated": True,
                    "source_object_id": source_id,
                    "latitude": 41.66473,
                    "longitude": 41.68362,
                },
            )
        )

        await server._handle_line(json.dumps(destroyed_scenery_message("SCENERY:42", "event-scenery-42")))

        report_id = f"LOSS:STRATEGIC:OBJECTIVE:{source_id}"
        report = bridge.state.loss_reports[report_id]
        assert report["report_kind"] == "strategic_damage"
        assert report["status"] == "damaged"
        assert report["destroyed_component_ids"] == ["SCENERY:42"]
        assert report["destroyed_component_count"] == 1
        assert report["baseline_component_count"] == 2
        assert report["baseline_complete"] is True
        assert report["damage_min"] == 0.5
        assert report["target_object_id"] == f"OBJECTIVE:{source_id}"
        assert report["victim_coalition"] == "red"

        blue_picture = bridge.build_tactical_picture("blue", "INTEL:Blue").to_geojson()
        loss_feature = next(
            feature
            for feature in blue_picture["features"]
            if feature["properties"]["layer"] == "loss_reports"
        )
        assert loss_feature["properties"]["perspective"] == "strategic_damage"

        await server._handle_line(json.dumps(destroyed_scenery_message("SCENERY:43", "event-scenery-43")))

        assert list(bridge.state.loss_reports) == [report_id]
        report = bridge.state.loss_reports[report_id]
        assert report["status"] == "destroyed"
        assert report["destroyed_component_ids"] == ["SCENERY:42", "SCENERY:43"]
        assert report["damage_min"] == 1.0
        assert report["first_mission_time"] == 150.0

        await server._handle_line(json.dumps(destroyed_scenery_message("SCENERY:99", "event-scenery-99")))
        assert list(bridge.state.loss_reports) == [report_id]

    asyncio.run(scenario())


def test_loss_report_is_visible_in_both_tactical_pictures_and_global_truth() -> None:
    server = MooseBridgeServer()
    bridge = MooseBridgeClient(server)
    server.state.apply_message(destroyed_message())

    blue = bridge.build_tactical_picture("blue", "INTEL:Blue")
    red = bridge.build_tactical_picture("red", "INTEL:Red")
    global_picture = bridge.build_global_picture()

    assert len(blue.loss_reports) == 1
    assert len(red.loss_reports) == 1
    assert blue.to_geojson()["features"][0]["properties"]["perspective"] == "enemy_loss"
    assert red.to_geojson()["features"][0]["properties"]["perspective"] == "friendly_loss"
    global_feature = next(
        feature
        for feature in global_picture.to_geojson()["features"]
        if feature["properties"]["layer"] == "loss_reports"
    )
    assert global_feature["properties"]["perspective"] == "global_truth"


def test_strategic_scenery_loss_is_rebuilt_from_destroyed_state() -> None:
    server = MooseBridgeServer()
    bridge = MooseBridgeClient(server)
    source_id = "BRIDGE:Caucasus:test"
    bridge._strategic_verifications = StrategicVerificationRegistry(
        theater_id="Caucasus",
        entries={
            source_id: StrategicSiteVerification(
                source_id=source_id,
                state="represented",
                observed_objects=(ObservedDcsObject("SCENERY:42", type_name="MOST(ROAD)BIG"),),
                observation_complete=True,
                target_components=(VerifiedDcsComponent("SCENERY:42", role="bridge span"),),
            )
        },
    )
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id=f"OBJECTIVE:{source_id}",
            name="Batumi bridge",
            kind=ObjectiveKind.INFRASTRUCTURE,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(ObjectiveComponent("SCENERY:42"),),
            metadata={
                "generated": True,
                "source_object_id": source_id,
                "latitude": 41.66473,
                "longitude": 41.68362,
            },
        )
    )
    bridge.state.loss_reports.clear()
    bridge.state.destroyed_object_ids.add("SCENERY:42")

    bridge.sync_strategic_objectives(source="control.snapshot")

    assert objective.status.value == "destroyed"
    report = bridge.state.loss_reports[f"LOSS:STRATEGIC:{objective.objective_id}"]
    assert report["status"] == "destroyed"
    assert report["destroyed_component_ids"] == ["SCENERY:42"]


def test_unit_lost_updates_strategic_component_health() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        await server._handle_line(
            json.dumps(
                {
                    "type": "snapshot",
                    "kind": "units",
                    "payload": {
                        "units": [
                            {
                                "object_id": "UNIT:Armor-1-1",
                                "alive": True,
                                "active": True,
                            }
                        ]
                    },
                }
            )
        )
        objective = bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Armor-1-1",
                name="Armor component",
                kind=ObjectiveKind.FORCE,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
                owner="red",
                components=(ObjectiveComponent("UNIT:Armor-1-1"),),
            )
        )
        assert objective.status is ObjectiveStatus.OPERATIONAL

        await server._handle_line(json.dumps(destroyed_message()))

        assert objective.health == 0.0
        assert objective.status is ObjectiveStatus.DESTROYED
        assert bridge.objectives.events[-1].event == "objective.destroyed"
        assert bridge.objectives.events[-1].source == "object.destroyed"

    asyncio.run(scenario())


def test_sdk_waits_for_one_unit_lost_event() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        waiter = asyncio.create_task(
            bridge.wait_for_object_destroyed("UNIT:Armor-1-1", timeout=1.0)
        )
        await asyncio.sleep(0)
        assert server._event_waiters[0][0] == "object.destroyed"
        assert server._event_waiters[0][1] == {"object_id": "UNIT:Armor-1-1"}

        await server._handle_line(json.dumps(destroyed_message()))
        event = await waiter

        assert event.object_id == "UNIT:Armor-1-1"
        assert bridge.state.units[event.object_id]["alive"] is False

    asyncio.run(scenario())


def test_sdk_waits_for_one_scenery_destroyed_event() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        waiter = asyncio.create_task(
            bridge.wait_for_object_destroyed("SCENERY:42", timeout=1.0)
        )
        await asyncio.sleep(0)

        await server._handle_line(json.dumps(destroyed_scenery_message("SCENERY:42", "event-scenery-42")))
        event = await waiter

        assert event.object_id == "SCENERY:42"
        assert event.object_type == "SCENERY"
        assert "SCENERY:42" in bridge.state.destroyed_object_ids

    asyncio.run(scenario())


def test_mission_end_clears_world_and_python_mission_registries() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        server.state.groups["GROUP:Old"] = {"object_id": "GROUP:Old", "alive": True}
        objective = bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Old",
                name="Old objective",
                kind=ObjectiveKind.FORCE,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
                components=(ObjectiveComponent("GROUP:Old"),),
            )
        )
        goal = bridge.add_strategic_goal(
            StrategicGoal(
                goal_id="GOAL:Old",
                name="Old goal",
                coalition="blue",
                action=StrategicGoalAction.DESTROY,
                objective_id=objective.objective_id,
            )
        )
        requirement = AssetRequirement(
            "REQ:Old",
            AssetRole.COMBAT,
            mission_types=("BAI",),
            performer_categories=("AIR",),
        )
        bridge.add_operational_plan(
            OperationalPlan(
                "PLAN:Old",
                "Old plan",
                goal.goal_id,
                "blue",
                (
                    PlanPhase(
                        "strike",
                        "Strike",
                        (MissionIntent("strike", "Strike", ("BAI",), (requirement,), "GROUP:Old"),),
                    ),
                ),
            )
        )
        bridge.add_information_requirement(
            InformationRequirement("INFO:Old", "INTEL:Blue", ("GROUP:Old",))
        )
        bridge.plan_executor._executions["PLAN:Old"] = []
        bridge.plan_executor._loaded_plan_ids.add("PLAN:Old")
        bridge._auftrag_ids_by_object[123] = "AUFTRAG:1"
        bridge._strategic_scenery_objectives["SCENERY:Old"] = {"OBJECTIVE:Old"}
        bridge._strategic_scenery_baselines["OBJECTIVE:Old"] = ("SCENERY:Old",)

        await server._handle_line(json.dumps(mission_ended_message()))

        assert bridge.state.connected is False
        assert not bridge.state.groups
        assert bridge.strategic_objectives() == ()
        assert bridge.strategic_goals() == ()
        assert bridge.operational_plans() == ()
        assert bridge.information_requirements() == ()
        assert not bridge.plan_executor._executions
        assert not bridge.plan_executor._loaded_plan_ids
        assert not bridge._auftrag_ids_by_object
        assert not bridge._strategic_scenery_objectives
        assert not bridge._strategic_scenery_baselines
        assert [event["event"] for event in server._event_history] == ["mission.ended"]

    asyncio.run(scenario())


def test_mission_end_wakes_unrelated_event_waiters() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        waiter = asyncio.create_task(
            server.wait_for_event("auftrag.*", filters={"auftrag_id": "AUFTRAG:1"}, timeout=1.0)
        )
        await asyncio.sleep(0)

        await server._handle_line(json.dumps(mission_ended_message()))

        event = await waiter
        assert event["event"] == "mission.ended"
        assert not server._event_waiters

    asyncio.run(scenario())


def test_mission_clock_rollback_uses_the_mission_end_reset_path() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        bridge = MooseBridgeClient(server)
        bridge.add_strategic_objective(
            StrategicObjective(
                objective_id="OBJECTIVE:Old",
                name="Old objective",
                kind=ObjectiveKind.FORCE,
                control_object_id=None,
                ownership_policy=OwnershipPolicy.FIXED,
            )
        )

        await server._handle_line(json.dumps({
            "type": "heartbeat",
            "source": "dcs",
            "mission_time": 900.0,
        }))
        await server._handle_line(json.dumps({
            "type": "heartbeat",
            "source": "dcs",
            "mission_time": 3.0,
        }))

        assert server.state.mission_generation == 1
        assert server.state.connected is True
        assert server.state.mission_ended is False
        assert server.state.clock is not None
        assert server.state.clock.mission_time == 3.0
        assert bridge.strategic_objectives() == ()
        assert [event["event"] for event in server._event_history] == ["mission.ended"]
        assert server._event_history[0]["payload"]["reason"] == "mission_clock_reset"

    asyncio.run(scenario())
