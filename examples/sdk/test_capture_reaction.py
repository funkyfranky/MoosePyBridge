"""Capture one OPSZONE, establish its guard, and validate the opponent reaction."""

from __future__ import annotations

import argparse

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    OperationalPlanStatus,
    PlanMissionStatus,
    RelationshipState,
    StrategicDecisionConfig,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjectiveGenerationConfig,
    StrategicVerificationRegistry,
    TheaterContext,
    TheaterInfrastructureSites,
    TheaterRailwayInfrastructure,
    TheaterSettlements,
    TheaterTransportInfrastructure,
    format_conflict_readiness,
    format_operational_plan_assessment,
    format_operational_plan_execution,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


# Editable example configuration.
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
MISSION_TIMEOUT_SECONDS = 3_600.0
THEATER_PROFILE = DEFAULT_THEATER_PROFILE_PATH.with_name("Caucasus_topography.json")
BLUE_INTEL_ID = "INTEL:Blue Intel"
RED_INTEL_ID = "INTEL:Red Intel"
CAPTURING_COALITION = "blue"
OPSZONE_ID = "OPSZONE:Town Gali"
DECLARE_WAR_IF_NEEDED = True
MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE = 10
DEFENSE_DURATION_SECONDS = 1_800.0
DESTROY_REQUIRED_DAMAGE = 0.70


def _load_context(profile_path) -> TheaterContext:
    theater, paths = load_example_theater(profile_path)
    return TheaterContext(
        theater_id=theater.theater_id,
        settlements=TheaterSettlements.load(paths.path("settlements")),
        transport=TheaterTransportInfrastructure.load(paths.path("transport_infrastructure")),
        railway=TheaterRailwayInfrastructure.load(paths.path("railway_infrastructure")),
        infrastructure=TheaterInfrastructureSites.load(paths.path("infrastructure_sites")),
        verifications=StrategicVerificationRegistry.load(
            paths.path("strategic_verifications")
        ).bind_theater(theater.theater_id),
    )


def _mission_token(bridge) -> str:
    mission_time = bridge.state.clock.mission_time if bridge.state.clock is not None else 0.0
    return f"{mission_time:.3f}".replace(".", "-")


async def run(profile_path=THEATER_PROFILE) -> int:
    context = _load_context(profile_path)
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id="capture-reaction-acceptance-example",
        display_name="Capture Reaction Acceptance Example",
    )
    bridge = session.bridge
    readiness = await bridge.assess_conflict_readiness(
        theater=context,
        intel_ids={"blue": BLUE_INTEL_ID, "red": RED_INTEL_ID},
        objective_config=StrategicObjectiveGenerationConfig(
            maximum_geographic_objectives_per_category_per_scope=(
                MAX_GEOGRAPHIC_OBJECTIVES_PER_CATEGORY_PER_SCOPE
            ),
        ),
        register_objectives=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    print(format_conflict_readiness(readiness))
    readiness.require_ready()

    await bridge.refresh_diplomacy_state()
    if bridge.relationship.state is not RelationshipState.WAR:
        if not DECLARE_WAR_IF_NEEDED:
            raise ValueError(
                "relationship must be war; run examples/sdk/declare_war.py or enable "
                "DECLARE_WAR_IF_NEEDED"
            )
        bridge.declare_war(
            CAPTURING_COALITION,
            reason="Capture-reaction acceptance test",
        )
        await bridge.persist_diplomacy_state()
        print(f"\n{CAPTURING_COALITION.title()} declared war for this acceptance test.")

    objective_id = f"OBJECTIVE:{OPSZONE_ID}"
    objective = bridge.strategic_objective(objective_id)
    if objective is None:
        raise ValueError(f"strategic objective is unavailable: {objective_id}")
    if objective.owner == CAPTURING_COALITION:
        raise ValueError(
            f"{OPSZONE_ID} is already controlled by {CAPTURING_COALITION}; restart the mission"
        )

    token = _mission_token(bridge)
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=f"GOAL:{CAPTURING_COALITION}:capture:Town-Gali:ACCEPTANCE:{token}",
            name=f"{CAPTURING_COALITION.title()} capture Town Gali",
            coalition=CAPTURING_COALITION,
            action=StrategicGoalAction.CAPTURE,
            objective_id=objective.objective_id,
            priority=max(90.0, objective.priority),
        )
    )
    intel_id = BLUE_INTEL_ID if CAPTURING_COALITION == "blue" else RED_INTEL_ID
    picture = await bridge.refresh_tactical_picture(CAPTURING_COALITION, intel_id)
    plan = bridge.add_operational_plan(
        bridge.propose_capture_plan(
            goal,
            picture,
            plan_id=f"PLAN:{CAPTURING_COALITION}:capture:Town-Gali:ACCEPTANCE:{token}",
        )
    )
    assessment = await bridge.refresh_and_validate_operational_plan(plan)
    print("\nCapture plan")
    print("=" * 96)
    print(format_operational_plan_assessment(plan, assessment))
    if not assessment.feasible:
        raise RuntimeError("Town Gali capture plan is not feasible")
    bridge.approve_operational_plan(
        plan,
        reason="Milestone 4 capture, consolidation, and reaction acceptance test",
    )

    print("\nExecuting the bounded capture and consolidation plan ...")
    execution = await bridge.execute_plan(
        plan,
        mission_timeout_s=MISSION_TIMEOUT_SECONDS,
        on_event=print,
    )
    print()
    print(format_operational_plan_execution(execution))
    if execution.status is not OperationalPlanStatus.COMPLETED:
        raise RuntimeError(f"capture plan ended with {execution.status.value}")

    await bridge.snapshot_opszones()
    bridge.sync_strategic_objectives(source="capture_reaction.acceptance")
    bridge.sync_strategic_goals(source="capture_reaction.acceptance")
    if objective.owner != CAPTURING_COALITION:
        raise RuntimeError(
            f"capture was not confirmed by OPSZONE ownership: owner={objective.owner or 'unknown'}"
        )
    if goal.status is not StrategicGoalStatus.ACHIEVED:
        raise RuntimeError(f"capture goal ended with {goal.status.value}")

    guards = tuple(
        mission
        for mission in execution.missions
        if mission.mission_type == "PATROLZONE" and mission.persistent
    )
    if not guards or any(mission.status is not PlanMissionStatus.RUNNING for mission in guards):
        states = ", ".join(mission.status.value for mission in guards) or "missing"
        raise RuntimeError(f"persistent PATROLZONE guard was not established: {states}")

    opposing_coalition = "red" if CAPTURING_COALITION == "blue" else "blue"
    opposing_intel = RED_INTEL_ID if opposing_coalition == "red" else BLUE_INTEL_ID
    opposing_picture = await bridge.refresh_tactical_picture(opposing_coalition, opposing_intel)
    reaction = bridge.recommend_strategic_portfolio(
        opposing_coalition,
        opposing_picture,
        objectives=(objective,),
        config=StrategicDecisionConfig(
            max_concurrent_goals=1,
            defense_duration_s=DEFENSE_DURATION_SECONDS,
            destroy_required_damage=DESTROY_REQUIRED_DAMAGE,
        ),
    )
    recapture = next(
        (
            decision
            for decision in reaction.selected
            if decision.objective_id == objective.objective_id
            and decision.action is StrategicGoalAction.CAPTURE
        ),
        None,
    )
    if recapture is None:
        reasons = "; ".join(
            f"{item.disposition.value}/{item.reason_code.value}: {item.reason}"
            for item in reaction.decisions
        )
        raise RuntimeError(f"opponent did not select the recapture reaction: {reasons}")

    print("\nMilestone 4 acceptance")
    print("=" * 96)
    print(f"Captured objective : {objective.objective_id} owner={objective.owner}")
    print(
        "Persistent guard   : "
        + ", ".join(
            f"{item.auftrag_id} {item.mission_type} status={item.status.value}"
            for item in guards
        )
    )
    print(
        f"Opponent reaction  : {recapture.candidate_id} action={recapture.action.value} "
        f"status={recapture.disposition.value}"
    )
    print("\nPASS: capture, persistent defense, and opponent recapture selection are coherent.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=THEATER_PROFILE)
    args = parser.parse_args()
    return run_example(lambda: run(args.profile))


if __name__ == "__main__":
    raise SystemExit(main())
