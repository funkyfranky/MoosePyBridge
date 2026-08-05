from __future__ import annotations

from moosebridge import (
    AssetRequirement,
    AssetRole,
    MissionIntent,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveKind,
    OperationalPlan,
    OwnershipPolicy,
    PlanPhase,
    StrategicGoal,
    StrategicGoalAction,
    StrategicObjective,
    format_strategic_feedback,
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
