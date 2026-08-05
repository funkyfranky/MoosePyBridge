from __future__ import annotations

from moosebridge import (
    Intel,
    MooseBridgeClient,
    ObjectiveComponent,
    ObjectiveKind,
    OperationalPlanStatus,
    OwnershipPolicy,
    PlanSourceType,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalEffect,
    StrategicObjective,
    format_operational_plan_assessment,
)
from moosebridge.clock import DcsTime
from moosebridge.intelligence import IntelContactMemory
from moosebridge.models import IntelContact, OpsZone
from moosebridge.pictures import TacticalPicture
from moosebridge.server import MooseBridgeServer


def _capture_context() -> tuple[MooseBridgeClient, StrategicGoal, StrategicObjective]:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Town",
            name="Town",
            kind=ObjectiveKind.OPSZONE,
            control_object_id="OPSZONE:Town",
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
            owner="red",
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Blue capture Town",
            name="Blue capture Town",
            coalition="blue",
            action=StrategicGoalAction.CAPTURE,
            objective_id=objective.objective_id,
        )
    )
    return bridge, goal, objective


def _zone() -> OpsZone:
    return OpsZone.from_payload(
        {
            "object_id": "OPSZONE:Town",
            "dcs_name": "Town",
            "x": 100_000,
            "z": 200_000,
            "zone_radius": 5_000,
            "owner_current_name": "red",
        }
    )


def _contact(
    object_id: str,
    target_id: str,
    x: float,
    z: float,
    threat: float,
    *,
    detected_time: float = 300.0,
    attribute: str | None = None,
) -> IntelContact:
    return IntelContact.from_payload(
        {
            "object_id": object_id,
            "target_object_id": target_id,
            "is_ground": True,
            "x": x,
            "z": z,
            "threat_level": threat,
            "detected_time": detected_time,
            "attribute": attribute,
        }
    )


def _intel(*, running: bool = True, alive_agents: int | None = 4) -> Intel:
    return Intel.from_payload(
        {
            "object_id": "INTEL:Blue",
            "coalition": "blue",
            "is_running": running,
            "agent_count": 4,
            "alive_agent_count": alive_agents,
        }
    )


def test_rule_based_capture_proposal_uses_highest_threat_visible_nearby_defender() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=321.5),
        opszones=[_zone()],
        contacts=[
            _contact("INTELCONTACT:Low", "GROUP:Low threat", 101_000, 201_000, 2),
            _contact("INTELCONTACT:High", "GROUP:High threat", 110_000, 200_000, 8),
            _contact("INTELCONTACT:Far", "GROUP:Far away", 200_000, 200_000, 10),
        ],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert plan.status is OperationalPlanStatus.DRAFT
    assert bridge.operational_plan(plan.plan_id) is None
    assert [phase.phase_id for phase in plan.phases] == ["isolate", "seize", "consolidate"]
    assert plan.phases[0].intents[0].target_object_id == "GROUP:High threat"
    assert plan.phases[1].depends_on == ("isolate",)
    assert plan.phases[1].intents[0].target_object_id == "OPSZONE:Town"
    assert plan.phases[1].intents[0].asset_requirements[0].min_count == 2
    assert plan.provenance is not None
    assert plan.provenance.source_type is PlanSourceType.RULE_ENGINE
    assert plan.provenance.picture_mission_time == 321.5
    assert "GROUP:High threat" in (plan.provenance.rationale or "")
    assert plan.proposal_issues == ()


def test_rule_based_capture_proposal_omits_isolation_without_visible_defender() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=321.5),
        opszones=[_zone()],
        contacts=[_contact("INTELCONTACT:Far", "GROUP:Far away", 200_000, 200_000, 10)],
    )

    plan = bridge.propose_capture_plan(goal.goal_id, picture, plan_id="PLAN:Conservative Town")

    assert plan.plan_id == "PLAN:Conservative Town"
    assert [phase.phase_id for phase in plan.phases] == ["seize", "consolidate"]
    assert plan.phases[0].depends_on == ()
    assert "no isolation strike" in (plan.provenance.rationale or "").lower()  # type: ignore[union-attr]
    assert [issue.code for issue in plan.proposal_issues] == ["intel_no_visible_defenders"]
    assert "not evidence" in plan.proposal_issues[0].message


def test_rule_based_capture_proposal_requests_recon_for_important_lost_contact() -> None:
    bridge, goal, _ = _capture_context()
    lost = _contact("INTELCONTACT:Lost", "GROUP:Lost armor", 102_000, 201_000, 7, detected_time=450.0)
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=500.0),
        opszones=[_zone()],
        lost_contacts=[IntelContactMemory(lost, lost_time=470.0, event_id="event-lost")],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert "reconnaissance_required" in {issue.code for issue in plan.proposal_issues}
    assert [phase.phase_id for phase in plan.phases] == ["recon", "seize", "consolidate"]
    recon_intent = plan.phases[0].intents[0]
    assert recon_intent.auftrag_types == ("RECON",)
    assert recon_intent.target_object_id == "OPSZONE:Town"
    assert "intel_id" not in recon_intent.metadata["auftrag_params"]
    assert plan.phases[0].metadata["requires_tactical_replanning"] is True
    assert plan.phases[1].depends_on == ("recon",)
    requirement = plan.metadata["reconnaissance_requirement"]
    assert requirement["target_object_id"] == "GROUP:Lost armor"
    assert requirement["last_known_x"] == 102_000
    assert requirement["threat_level"] == 7


def test_rule_based_capture_proposal_ignores_unimportant_lost_contact_for_recon() -> None:
    bridge, goal, _ = _capture_context()
    lost = _contact("INTELCONTACT:Lost", "GROUP:Lost truck", 102_000, 201_000, 1, detected_time=450.0)
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=500.0),
        opszones=[_zone()],
        lost_contacts=[IntelContactMemory(lost, lost_time=470.0)],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert "reconnaissance_required" not in {issue.code for issue in plan.proposal_issues}
    assert plan.metadata["reconnaissance_requirement"] is None


def test_rule_based_capture_proposal_does_not_target_stale_contact() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=1_000.0),
        opszones=[_zone()],
        contacts=[_contact("INTELCONTACT:Stale", "GROUP:Stale", 101_000, 201_000, 10, detected_time=100.0)],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert [phase.phase_id for phase in plan.phases] == ["seize", "consolidate"]
    assert "intel_no_visible_defenders" in {issue.code for issue in plan.proposal_issues}


def test_rule_based_capture_proposal_reports_unavailable_intel_coverage() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(running=False, alive_agents=0),
        opszones=[_zone()],
    )

    plan = bridge.propose_capture_plan(goal, picture)

    assert {issue.code for issue in plan.proposal_issues} == {
        "intel_not_running",
        "intel_no_alive_agents",
        "intel_no_visible_defenders",
    }


def test_rule_based_capture_proposal_rejects_wrong_picture_coalition() -> None:
    bridge, goal, _ = _capture_context()
    picture = TacticalPicture(coalition="red", intel_id="INTEL:Red", opszones=[_zone()])

    try:
        bridge.propose_capture_plan(goal, picture)
    except ValueError as exc:
        assert "coalition" in str(exc)
    else:
        raise AssertionError("Planner should reject an opposing coalition tactical picture")


def _defend_context() -> tuple[MooseBridgeClient, StrategicGoal, StrategicObjective]:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Town",
            name="Town",
            kind=ObjectiveKind.OPSZONE,
            control_object_id="OPSZONE:Town",
            ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
            owner="blue",
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Blue defend Town",
            name="Blue defend Town",
            coalition="blue",
            action=StrategicGoalAction.DEFEND,
            objective_id=objective.objective_id,
            deadline_mission_time=1_200,
        )
    )
    return bridge, goal, objective


def test_rule_based_defend_proposal_holds_zone_and_interdicts_visible_attacker() -> None:
    bridge, goal, _ = _defend_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=600),
        opszones=[_zone()],
        contacts=[
            _contact("INTELCONTACT:Low", "GROUP:Low", 101_000, 201_000, 2, detected_time=590),
            _contact("INTELCONTACT:High", "GROUP:High", 102_000, 200_000, 8, detected_time=590),
        ],
    )

    plan = bridge.propose_defend_plan(goal, picture)

    assert plan.status is OperationalPlanStatus.DRAFT
    assert bridge.operational_plan(plan.plan_id) is None
    assert [phase.phase_id for phase in plan.phases] == ["defend"]
    assert [intent.intent_id for intent in plan.phases[0].intents] == [
        "counterattack-visible-threat",
        "hold-zone",
        "establish-air-defense",
        "sustain-defenders",
    ]
    assert plan.phases[0].intents[0].target_object_id == "GROUP:High"
    hold = plan.phases[0].intents[1]
    assert hold.auftrag_types == ("PATROLZONE",)
    assert hold.asset_requirements[0].min_count == 2
    assert plan.metadata["defense_deadline_mission_time"] == 1_200
    assert plan.proposal_issues == ()


def test_rule_based_defend_proposal_warns_when_no_attacker_is_visible() -> None:
    bridge, goal, _ = _defend_context()
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        intel=_intel(),
        clock=DcsTime(mission_time=600),
        opszones=[_zone()],
    )

    plan = bridge.propose_defend_plan(goal.goal_id, picture)

    assert [intent.intent_id for intent in plan.phases[0].intents] == [
        "hold-zone",
        "establish-air-defense",
        "sustain-defenders",
    ]
    assert [issue.code for issue in plan.proposal_issues] == ["intel_no_visible_attackers"]
    assert "not evidence" in plan.proposal_issues[0].message


def test_rule_based_defend_proposal_requires_friendly_control() -> None:
    bridge, goal, objective = _defend_context()
    objective.owner = "red"
    picture = TacticalPicture(coalition="blue", intel_id="INTEL:Blue", opszones=[_zone()])

    try:
        bridge.propose_defend_plan(goal, picture)
    except ValueError as exc:
        assert "controlled" in str(exc)
    else:
        raise AssertionError("Planner should reject defense of an enemy-controlled objective")


def test_rule_based_destroy_proposal_selects_weighted_static_components() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Depot",
            name="Depot",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(
                ObjectiveComponent("STATIC:Main", weight=0.6),
                ObjectiveComponent("STATIC:Reserve", weight=0.3),
                ObjectiveComponent("STATIC:Shed", weight=0.1),
            ),
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "statics",
            "payload": {
                "statics": [
                    {"object_id": "STATIC:Main", "alive": True},
                    {"object_id": "STATIC:Reserve", "alive": True},
                    {"object_id": "STATIC:Shed", "alive": True},
                ]
            },
        }
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Damage Depot",
            name="Damage Depot",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
            required_damage=0.7,
        )
    )
    picture = TacticalPicture(coalition="blue", intel_id="INTEL:Blue", clock=DcsTime(mission_time=100))

    plan = bridge.propose_destroy_plan(goal, picture)

    assert [intent.target_object_id for intent in plan.phases[0].intents] == [
        "STATIC:Main",
        "STATIC:Reserve",
    ]
    assert plan.metadata["required_damage"] == 0.7
    assert plan.metadata["current_health"] == 1.0
    assert abs(plan.metadata["projected_health"] - 0.1) < 1e-12
    assert "at most 30.0%" in (plan.provenance.rationale or "")  # type: ignore[union-attr]


def test_rule_based_destroy_proposal_requires_intel_for_moving_components() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Armor",
            name="Armor",
            kind=ObjectiveKind.FORCE,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(ObjectiveComponent("GROUP:Armor", weight=1.0),),
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "groups",
            "payload": {"groups": [{"object_id": "GROUP:Armor", "alive": True}]},
        }
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Destroy Armor",
            name="Destroy Armor",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
        )
    )
    picture = TacticalPicture(coalition="blue", intel_id="INTEL:Blue")

    try:
        bridge.propose_destroy_plan(goal, picture)
    except ValueError as exc:
        assert "visible targetable components" in str(exc)
    else:
        raise AssertionError("Moving objective components must require coalition INTEL")


def test_destroy_planner_uses_resolver_and_current_cohort_capabilities() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:SAM",
            name="SAM Site",
            kind=ObjectiveKind.FORCE,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(ObjectiveComponent("GROUP:SAM", weight=1.0),),
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "groups",
            "payload": {
                "groups": [{
                    "object_id": "GROUP:SAM",
                    "alive": True,
                    "category": "Ground Unit",
                    "attributes": ["SAM SR", "Air Defence"],
                }]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [{
                    "object_id": "LEGION:Wing",
                    "coalition": "blue",
                }]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [{
                    "object_id": "COHORT:SEAD",
                    "legion_id": "LEGION:Wing",
                    "is_air": True,
                    "available_asset_count": 2,
                    "mission_types": ["SEAD"],
                    "payloads_by_mission": {
                        "SEAD": {"available_count": 1, "total_available": 2}
                    },
                }]
            },
        }
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Suppress SAM",
            name="Suppress SAM",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
            effect=StrategicGoalEffect.SUPPRESS_AIR_DEFENSE,
        )
    )
    picture = TacticalPicture(
        coalition="blue",
        intel_id="INTEL:Blue",
        clock=DcsTime(mission_time=350),
        contacts=[
            _contact(
                "INTELCONTACT:SAM",
                "GROUP:SAM",
                100_000,
                200_000,
                8,
                attribute="SAM SR",
            )
        ],
    )

    plan = bridge.propose_destroy_plan(goal, picture)

    intent = plan.phases[0].intents[0]
    assert intent.auftrag_types == ("SEAD",)
    assert intent.asset_requirements[0].role.value == "sead"
    assert intent.metadata["target_domain"] == "ground"
    assert intent.metadata["mission_candidates"] == ["SEAD", "BAI", "GROUNDATTACK"]
    assert intent.metadata["selected_cohort_id"] == "COHORT:SEAD"
    assert intent.asset_requirements[0].allowed_cohort_ids == ("COHORT:SEAD",)


def test_destroy_planner_binds_range_qualified_arty_cohort() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Artillery Target",
            name="Artillery Target",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(ObjectiveComponent("STATIC:Artillery Target"),),
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "statics",
            "payload": {
                "statics": [
                    {
                        "object_id": "STATIC:Artillery Target",
                        "alive": True,
                        "x": 10_000,
                        "z": 0,
                    }
                ]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [
                    {
                        "object_id": "LEGION:Blue Brigade",
                        "coalition": "blue",
                        "x": 0,
                        "z": 0,
                    }
                ]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:Blue M109",
                        "legion_id": "LEGION:Blue Brigade",
                        "unit_type": "M-109",
                        "is_ground": True,
                        "available_asset_count": 2,
                        "mission_types": ["ARTY"],
                        "engage_range_m": 20_000,
                        "mission_range_m": 42_000,
                            "mission_ranges_by_weapon_type": {
                                "206963736576": 42_000,
                            },
                            "weapon_ranges_by_type": {
                                "206963736576": {
                                    "minimum_m": 30,
                                    "maximum_m": 22_000,
                                },
                            },
                    }
                ]
            },
        }
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Shell Artillery Target",
            name="Shell Artillery Target",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
        )
    )

    plan = bridge.propose_destroy_plan(
        goal,
        TacticalPicture(coalition="blue", intel_id="INTEL:Blue"),
    )

    intent = plan.phases[0].intents[0]
    requirement = intent.asset_requirements[0]
    assert intent.auftrag_types == ("ARTY",)
    assert requirement.allowed_cohort_ids == ("COHORT:Blue M109",)
    assert intent.metadata["fire_support"]["weapon_flag"] == "CONVENTIONAL_SHELL"
    assert intent.metadata["fire_support"]["ammunition_source"] == "cohort_template_assumed_full"
    assert intent.metadata["selection_basis"] == "shortest_estimated_time_to_effect"
    assert intent.metadata["estimated_time_to_effect_s"] == 120.0
    bridge.add_operational_plan(plan)
    rendered = format_operational_plan_assessment(plan, bridge.validate_operational_plan(plan))
    assert "fire_support=COHORT:Blue M109 flag=CONVENTIONAL_SHELL" in rendered
    assert "distance=10.0km weapon_range=0.0-22.0km mission_range=42.0km" in rendered
    assert "moose_configured=0.0-22.0km sync=current relocation=0.0km" in rendered
    assert "estimated_time_to_effect=120s" in rendered
    assert "time_to_effect_options=ARTY:COHORT:Blue M109/CONVENTIONAL_SHELL=120s" in rendered
    assert "ammo=cohort_template_assumed_full" in rendered


def test_destroy_resolver_ignores_enemy_cohort_capabilities() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Depot Coalition Filter",
            name="Depot Coalition Filter",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(ObjectiveComponent("STATIC:Coalition Filter Depot"),),
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "statics",
            "payload": {"statics": [{"object_id": "STATIC:Coalition Filter Depot", "alive": True}]},
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [
                    {"object_id": "LEGION:Blue Wing", "coalition": "blue"},
                    {"object_id": "LEGION:Red Wing", "coalition": "red"},
                ]
            },
        }
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:Blue Bombers",
                        "legion_id": "LEGION:Blue Wing",
                        "is_air": True,
                        "available_asset_count": 1,
                        "mission_types": ["BOMBING"],
                        "payloads_by_mission": {"BOMBING": {"available_count": 1, "total_available": 1}},
                    },
                    {
                        "object_id": "COHORT:Red BAI",
                        "legion_id": "LEGION:Red Wing",
                        "is_air": True,
                        "available_asset_count": 1,
                        "mission_types": ["BAI"],
                        "payloads_by_mission": {"BAI": {"available_count": 1, "total_available": 1}},
                    },
                ]
            },
        }
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Destroy Coalition Filter Depot",
            name="Destroy Coalition Filter Depot",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
        )
    )

    plan = bridge.propose_destroy_plan(goal, TacticalPicture(coalition="blue", intel_id="INTEL:Blue"))

    intent = plan.phases[0].intents[0]
    assert intent.auftrag_types == ("BOMBING",)
    assert intent.metadata["selected_cohort_id"] == "COHORT:Blue Bombers"
    assert intent.asset_requirements[0].allowed_cohort_ids == ("COHORT:Blue Bombers",)


def test_destroy_replan_prefers_an_already_damaged_component() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Damaged Depot",
            name="Damaged Depot",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            components=(
                ObjectiveComponent("STATIC:Damaged", weight=0.2),
                ObjectiveComponent("STATIC:Untouched", weight=0.8),
            ),
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "statics",
            "payload": {
                "statics": [
                    {"object_id": "STATIC:Damaged", "alive": True},
                    {"object_id": "STATIC:Untouched", "alive": True},
                ]
            },
        }
    )
    bridge.objectives.record_component_health(
        objective,
        "STATIC:Damaged",
        0.5,
        source="auftrag_summary:AUFTRAG:1",
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Finish Damaged Depot",
            name="Finish Damaged Depot",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
            required_damage=0.5,
        )
    )

    plan = bridge.propose_destroy_plan(
        goal,
        TacticalPicture(coalition="blue", intel_id="INTEL:Blue", clock=DcsTime(mission_time=200)),
    )

    assert plan.metadata["current_health"] == 0.9
    assert [intent.target_object_id for intent in plan.phases[0].intents] == [
        "STATIC:Damaged",
        "STATIC:Untouched",
    ]
    assert plan.phases[0].intents[0].metadata["objective_component_health"] == 0.5


def test_rule_based_disable_proposal_uses_bombrunway_for_airdrome() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Tutow",
            name="Tutow Airbase",
            kind=ObjectiveKind.AIRBASE,
            control_object_id="AIRBASE:Tutow",
            ownership_policy=OwnershipPolicy.DCS_MANAGED,
            owner="red",
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Deny Tutow runway",
            name="Deny Tutow runway",
            coalition="blue",
            action=StrategicGoalAction.DISABLE,
            objective_id=objective.objective_id,
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "airbases",
            "payload": {
                "airbases": [{"object_id": "AIRBASE:Tutow", "category": "Airdrome", "coalition": "red"}]
            },
        }
    )

    plan = bridge.propose_disable_plan(goal, TacticalPicture(coalition="blue", intel_id="INTEL:Blue"))

    intent = plan.phases[0].intents[0]
    requirement = intent.asset_requirements[0]
    assert goal.effect is StrategicGoalEffect.DENY_RUNWAY
    assert intent.auftrag_types == ("BOMBRUNWAY",)
    assert intent.target_object_id == "AIRBASE:Tutow"
    assert requirement.performer_categories == ("AIR",)
    assert requirement.require_payload is True


def test_rule_based_disable_proposal_rejects_helipad() -> None:
    bridge = MooseBridgeClient(MooseBridgeServer())
    objective = bridge.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:FARP",
            name="FARP",
            kind=ObjectiveKind.AIRBASE,
            control_object_id="AIRBASE:FARP",
            ownership_policy=OwnershipPolicy.DCS_MANAGED,
            owner="red",
        )
    )
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Deny FARP",
            name="Deny FARP",
            coalition="blue",
            action=StrategicGoalAction.DISABLE,
            objective_id=objective.objective_id,
        )
    )
    bridge.state.apply_message(
        {
            "type": "snapshot",
            "kind": "airbases",
            "payload": {"airbases": [{"object_id": "AIRBASE:FARP", "category": "Helipad"}]},
        }
    )

    try:
        bridge.propose_disable_plan(goal, TacticalPicture(coalition="blue", intel_id="INTEL:Blue"))
    except ValueError as exc:
        assert "Airdrome" in str(exc)
    else:
        raise AssertionError("BOMBRUNWAY planning must reject helipads")
