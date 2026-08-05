from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from moosebridge import (
    AssetRequirement,
    AssetRole,
    MissionIntent,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveKind,
    OperationalPlan,
    OperationalPlanStatus,
    OwnershipPolicy,
    PlanPhase,
    StrategicGoal,
    StrategicGoalAction,
    StrategicFeedbackAction,
    StrategicFeedbackEvent,
    StrategicObjective,
    RelationshipState,
    format_strategic_feedback,
    format_strategic_goal_portfolio,
)


def _client_with_plan() -> tuple[MooseBridgeClient, OperationalPlan]:
    client = MooseBridgeClient(MooseBridgeServer())
    objective = client.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Feedback",
            name="Feedback Objective",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
        )
    )
    goal = client.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Feedback",
            name="Feedback Goal",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
        ),
        activate=True,
    )
    plan = client.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Feedback",
            name="Feedback Plan",
            goal_id=goal.goal_id,
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="strike",
                    name="Strike",
                    intents=(
                        MissionIntent(
                            intent_id="strike-target",
                            name="Strike target",
                            auftrag_types=("BAI",),
                            target_object_id="STATIC:Feedback",
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Strike",
                                    role=AssetRole.COMBAT,
                                    mission_types=("BAI",),
                                    performer_categories=("AIR",),
                                    allowed_cohort_ids=("COHORT:Feedback",),
                                    require_payload=True,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    client.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {"legions": [{"object_id": "LEGION:Feedback", "coalition": "blue"}]},
        }
    )
    _set_cohort_availability(client, 1)
    return client, plan


def _set_cohort_availability(client: MooseBridgeClient, available: int) -> None:
    client.state.apply_message(
        {
            "type": "snapshot",
            "kind": "cohorts",
            "payload": {
                "cohorts": [
                    {
                        "object_id": "COHORT:Feedback",
                        "legion_id": "LEGION:Feedback",
                        "is_air": True,
                        "available_asset_count": available,
                        "mission_types": ["BAI"],
                        "payloads_by_mission": {
                            "BAI": {"available_count": available, "total_available": available}
                        },
                    }
                ]
            },
        }
    )


def _add_second_plan(client: MooseBridgeClient) -> OperationalPlan:
    objective = client.add_strategic_objective(
        StrategicObjective(
            objective_id="OBJECTIVE:Feedback Two",
            name="Feedback Objective Two",
            kind=ObjectiveKind.DEPOT,
            control_object_id=None,
            ownership_policy=OwnershipPolicy.FIXED,
            owner="red",
            priority=20,
            strategic_value=80,
        )
    )
    goal = client.add_strategic_goal(
        StrategicGoal(
            goal_id="GOAL:Feedback Two",
            name="Feedback Goal Two",
            coalition="blue",
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
            priority=50,
        ),
        activate=True,
    )
    return client.add_operational_plan(
        OperationalPlan(
            plan_id="PLAN:Feedback Two",
            name="Feedback Plan Two",
            goal_id=goal.goal_id,
            coalition="blue",
            phases=(
                PlanPhase(
                    phase_id="strike",
                    name="Strike",
                    intents=(
                        MissionIntent(
                            intent_id="strike-target-two",
                            name="Strike second target",
                            auftrag_types=("BAI",),
                            target_object_id="STATIC:Feedback Two",
                            asset_requirements=(
                                AssetRequirement(
                                    requirement_id="REQ:Strike Two",
                                    role=AssetRole.COMBAT,
                                    mission_types=("BAI",),
                                    performer_categories=("AIR",),
                                    allowed_cohort_ids=("COHORT:Feedback",),
                                    require_payload=True,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )


def test_feedback_monitor_reports_shortfall_and_recovery_without_mutating_plan() -> None:
    client, plan = _client_with_plan()

    initial = client.sync_strategic_feedback(source="test.initial")
    assert [event.event for event in initial] == ["feedback.plan_assessed"]
    assert initial[0].details["feasible"] is True

    _set_cohort_availability(client, 0)
    lost = client.sync_strategic_feedback(source="snapshot.cohorts")
    assert [event.event for event in lost] == [
        "feedback.replanning_required",
        "feedback.plan_allocation_changed",
    ]
    assert lost[0].details["feasible"] is False
    assert "feedback.replanning_required" in format_strategic_feedback(lost[0])
    assert "error:asset_shortfall" in format_strategic_feedback(lost[0])
    assert plan.status.value == "draft"

    _set_cohort_availability(client, 1)
    restored = client.sync_strategic_feedback(source="snapshot.cohorts")
    assert [event.event for event in restored] == [
        "feedback.plan_feasibility_restored",
        "feedback.plan_allocation_changed",
    ]
    assert restored[0].details["feasible"] is True


def test_feedback_monitor_forwards_goal_transitions_and_listener_notifications() -> None:
    client, _ = _client_with_plan()
    observed: list[str] = []
    client.add_strategic_feedback_listener(lambda event: observed.append(event.event))

    client.complete_strategic_goal("GOAL:Feedback", achieved=True)

    events = client.strategic_feedback_events(goal_id="GOAL:Feedback")
    assert events[-1].event == "feedback.goal_status_changed"
    assert events[-1].details["previous_status"] == "active"
    assert events[-1].details["status"] == "achieved"
    assert observed == ["feedback.goal_status_changed"]


def test_bridge_intel_event_creates_feedback_without_plan_polling() -> None:
    client, _ = _client_with_plan()
    message = {
        "type": "event",
        "id": "event-intel-1",
        "event": "intel.new_contact",
        "mission_time": 42,
        "payload": {
            "contact": {
                "object_id": "INTELCONTACT:Blue:Armor",
                "target_object_id": "GROUP:Armor",
                "coalition": "red",
            }
        },
    }

    client.state.apply_message(message)
    client._on_bridge_message(message)
    client._on_bridge_message(message)

    events = client.strategic_feedback_events(event="feedback.intelligence_changed")
    assert len(events) == 1
    event = events[0]
    assert event.reference_id == "GROUP:Armor"
    assert event.details["intel_event"] == "intel.new_contact"


def test_reset_mission_clears_feedback_but_keeps_monitor_usable() -> None:
    client, _ = _client_with_plan()
    assert client.strategic_feedback_events()

    client.reset_mission()

    assert client.strategic_feedback_events() == ()


def test_policy_replans_before_execution_but_waits_for_executing_plan() -> None:
    client, plan = _client_with_plan()
    event = StrategicFeedbackEvent(
        event="feedback.replanning_required",
        source="snapshot.cohorts",
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        details={"feasible": False},
    )

    decision = client.strategic_feedback_decisions(event)[0]
    assert decision.action is StrategicFeedbackAction.REPLAN
    assert decision.automatic is False

    plan.status = OperationalPlanStatus.EXECUTING
    decision = client.strategic_feedback_decisions(event)[0]
    assert decision.action is StrategicFeedbackAction.WAIT
    assert decision.automatic is False


def test_policy_automatically_aborts_terminal_goal_and_friendly_target() -> None:
    client, plan = _client_with_plan()
    plan.status = OperationalPlanStatus.EXECUTING

    client.complete_strategic_goal(plan.goal_id, achieved=True)
    terminal = client.strategic_feedback_events(event="feedback.goal_status_changed")[-1]
    decision = client.strategic_feedback_decisions(terminal)[0]
    assert decision.action is StrategicFeedbackAction.ABORT
    assert decision.automatic is True

    objective = client.strategic_objective("OBJECTIVE:Feedback")
    assert objective is not None
    objective.owner = "blue"
    friendly = StrategicFeedbackEvent(
        event="feedback.objective_changed",
        source="test",
        reference_id=objective.objective_id,
    )
    decision = client.strategic_feedback_decisions(friendly)[0]
    assert decision.action is StrategicFeedbackAction.ABORT
    assert decision.automatic is True
    assert "friendly" in decision.reason


def test_persistent_asset_shortfall_uses_dcs_mission_time_once() -> None:
    client, plan = _client_with_plan()
    _set_cohort_availability(client, 0)

    client.strategic_feedback.reassess_plans(
        legions=client.state.legion_objects.values(),
        cohorts=client.state.cohort_objects.values(),
        mission_time=10.0,
        source="test",
    )
    before_threshold = client.strategic_feedback.reassess_plans(
        legions=client.state.legion_objects.values(),
        cohorts=client.state.cohort_objects.values(),
        mission_time=309.0,
        source="heartbeat",
    )
    at_threshold = client.strategic_feedback.reassess_plans(
        legions=client.state.legion_objects.values(),
        cohorts=client.state.cohort_objects.values(),
        mission_time=310.0,
        source="heartbeat",
    )
    repeated = client.strategic_feedback.reassess_plans(
        legions=client.state.legion_objects.values(),
        cohorts=client.state.cohort_objects.values(),
        mission_time=610.0,
        source="heartbeat",
    )

    assert before_threshold == ()
    assert [event.event for event in at_threshold] == ["feedback.asset_shortfall_persisted"]
    assert repeated == ()
    decision = client.strategic_feedback_decisions(at_threshold[0])[0]
    assert decision.plan_id == plan.plan_id
    assert decision.action is StrategicFeedbackAction.REPLAN
    assert decision.automatic is False


def test_apply_policy_executes_only_automatic_abort() -> None:
    client, plan = _client_with_plan()
    plan.status = OperationalPlanStatus.EXECUTING
    abort = AsyncMock()
    client.abort_operational_plan = abort
    terminal = StrategicFeedbackEvent(
        event="feedback.goal_status_changed",
        source="test",
        goal_id=plan.goal_id,
        details={"status": "cancelled"},
    )

    decisions = asyncio.run(client.apply_strategic_feedback_policy(terminal))

    assert decisions[0].action is StrategicFeedbackAction.ABORT
    abort.assert_awaited_once_with(plan, reason=decisions[0].reason)


def test_goal_portfolio_selects_multiple_goals_without_overbooking_assets() -> None:
    client, first_plan = _client_with_plan()
    first_goal = client.strategic_goal(first_plan.goal_id)
    first_objective = client.strategic_objective("OBJECTIVE:Feedback")
    assert first_goal is not None and first_objective is not None
    first_goal.priority = 100
    first_objective.priority = 50
    first_objective.strategic_value = 100
    second_plan = _add_second_plan(client)
    client.relationship.state = RelationshipState.WAR

    _set_cohort_availability(client, 1)
    constrained = client.select_strategic_goal_portfolio("blue")
    assert [item.goal_id for item in constrained.selected] == [first_goal.goal_id]
    assert [item.goal_id for item in constrained.deferred] == [second_plan.goal_id]
    assert constrained.reserved_assets == (("COHORT:Feedback", 1),)
    assert "insufficient remaining portfolio capacity" in constrained.deferred[0].reason

    _set_cohort_availability(client, 2)
    expanded = client.select_strategic_goal_portfolio("blue")
    assert [item.goal_id for item in expanded.selected] == [first_goal.goal_id, second_plan.goal_id]
    assert expanded.deferred == ()
    assert expanded.reserved_assets == (("COHORT:Feedback", 2),)
    assert first_plan.status is OperationalPlanStatus.DRAFT
    assert second_plan.status is OperationalPlanStatus.DRAFT
    assert "selected=2" in format_strategic_goal_portfolio(expanded)


def test_goal_portfolio_enforces_relationship_and_limited_conflict_scope() -> None:
    client, first_plan = _client_with_plan()
    second_plan = _add_second_plan(client)
    _set_cohort_availability(client, 2)

    peace = client.select_strategic_goal_portfolio("blue")
    assert peace.selected == ()
    assert all("not permitted during peace" in item.reason for item in peace.deferred)

    client.relationship.state = RelationshipState.LIMITED_CONFLICT
    client.relationship.limited_conflict.authorize_objective("OBJECTIVE:Feedback")
    limited = client.select_strategic_goal_portfolio("blue")
    assert [item.plan_id for item in limited.selected] == [first_plan.plan_id]
    assert [item.plan_id for item in limited.deferred] == [second_plan.plan_id]
    assert "outside the limited-conflict authorization" in limited.deferred[0].reason

    client.relationship.state = RelationshipState.WAR
    war = client.select_strategic_goal_portfolio("blue")
    assert len(war.selected) == 2


def test_defensive_doctrine_prioritizes_defend_when_capacity_is_limited() -> None:
    client, offensive_plan = _client_with_plan()
    defensive_plan = _add_second_plan(client)
    offensive_goal = client.strategic_goal(offensive_plan.goal_id)
    defensive_goal = client.strategic_goal(defensive_plan.goal_id)
    offensive_objective = client.strategic_objective("OBJECTIVE:Feedback")
    defensive_objective = client.strategic_objective("OBJECTIVE:Feedback Two")
    assert offensive_goal and defensive_goal and offensive_objective and defensive_objective
    offensive_goal.priority = defensive_goal.priority = 50
    offensive_objective.priority = defensive_objective.priority = 20
    offensive_objective.strategic_value = defensive_objective.strategic_value = 80
    defensive_goal.action = StrategicGoalAction.DEFEND
    client.relationship.state = RelationshipState.WAR
    client.set_coalition_doctrine("blue", "defensive")
    _set_cohort_availability(client, 1)

    portfolio = client.select_strategic_goal_portfolio("blue")

    assert [item.plan_id for item in portfolio.selected] == [defensive_plan.plan_id]
    assert portfolio.selected[0].doctrine_tier == 0
    assert portfolio.deferred[0].plan_id == offensive_plan.plan_id
    assert portfolio.deferred[0].doctrine_tier == 2
