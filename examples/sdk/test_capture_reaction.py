"""Capture one OPSZONE, establish its guard, and validate the opponent reaction."""

from __future__ import annotations

import argparse
import asyncio
import time

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    DEFAULT_THEATER_PROFILE_PATH,
    Auftrag_PATROLZONE,
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
# Set to "blue" or "red" to force one side. None attacks the current owner.
CAPTURING_COALITION: str | None = None
OPSZONE_ID = "OPSZONE:Town Gali"
DECLARE_WAR_IF_NEEDED = True
REQUIRE_DEFENDED_TARGET = True
STAGE_DEFENDER_IF_NEEDED = True
DEFENDER_STAGING_TIMEOUT_SECONDS = 1_800.0
DEFENDER_POLL_INTERVAL_SECONDS = 10.0
DEFENDER_DURATION_SECONDS = 3_600.0
DEFENDER_REQUIRED_ASSETS = 1
OWNER_INITIALIZATION_TIMEOUT_SECONDS = 15.0
OWNER_INITIALIZATION_POLL_SECONDS = 2.0
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


def _reaction_failure_reason(decision) -> str:
    text = f"{decision.disposition.value}/{decision.reason_code.value}: {decision.reason}"
    assessment = decision.assessment
    if assessment is None:
        return text
    shortfalls = [
        (
            f"{item.phase_id}/{item.intent_id}/{item.requirement_id} "
            f"required={item.required_count} available={item.available_count} "
            f"shortfall={item.shortfall} candidates="
            f"{','.join(item.candidate_cohort_ids) or '-'}"
        )
        for item in assessment.requirements
        if not item.feasible
    ]
    return text + (f" [{'; '.join(shortfalls)}]" if shortfalls else "")


def _ground_mission_cohort_ids(
    bridge,
    coalition: str,
    mission_type: str,
) -> tuple[str, ...]:
    legion_ids = {
        item.object_id
        for item in bridge.state.legion_objects.values()
        if (item.coalition or "").lower() == coalition
    }
    eligible = [
        item
        for item in bridge.state.cohort_objects.values()
        if item.legion_id in legion_ids
        and item.is_ground
        and mission_type in item.mission_type_keys
        and (item.available_asset_count or 0) > 0
    ]
    eligible.sort(
        key=lambda item: (
            -(item.mission_performance_for(mission_type) or 0.0),
            item.units_per_asset or 1,
            -(item.available_asset_count or 0),
            item.object_id,
        )
    )
    # Keep the acceptance defense real but bounded; production planning remains
    # responsible for sizing defenders from value, threat, and doctrine.
    return tuple(item.object_id for item in eligible[:1])


async def _stage_defender(
    bridge,
    opszone,
    coalition: str,
    *,
    claim_neutral_zone: bool = False,
) -> tuple[str, object]:
    cohort_ids = _ground_mission_cohort_ids(bridge, coalition, "PATROLZONE")
    if not cohort_ids:
        raise RuntimeError(f"{coalition} has no available ground PATROLZONE cohort")

    zone_name = opszone.zone_name or OPSZONE_ID.removeprefix("OPSZONE:")
    zone_id = zone_name if zone_name.startswith("ZONE:") else f"ZONE:{zone_name}"
    mission = Auftrag_PATROLZONE(zone=zone_id)
    mission.set_duration(DEFENDER_DURATION_SECONDS)
    mission.set_required_assets(
        min_count=DEFENDER_REQUIRED_ASSETS,
        max_count=DEFENDER_REQUIRED_ASSETS,
    )
    ack = await bridge.add_auftrag(
        mission,
        coalition=coalition,
        allowed_cohorts=cohort_ids,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    auftrag_id = str(result.get("auftrag_id") or "")
    if not auftrag_id:
        raise RuntimeError("defender staging did not return an AUFTRAG id")

    print("\nClaiming neutral OPSZONE" if claim_neutral_zone else "\nStaging active defense")
    print("=" * 96)
    print(f"AUFTRAG           : {auftrag_id} PATROLZONE")
    print(f"Coalition         : {coalition}")
    print(f"Zone              : {zone_id}")
    print(f"Allowed COHORTs   : {', '.join(cohort_ids)}")
    print("Waiting for the defending ground group to enter the OPSZONE ...")

    deadline = time.monotonic() + DEFENDER_STAGING_TIMEOUT_SECONDS
    last_status = None
    while time.monotonic() < deadline:
        await bridge.snapshot_opszones()
        await bridge.snapshot_auftraege()
        live_zone = bridge.state.opszone_objects.get(OPSZONE_ID)
        snapshot = bridge.auftrag(auftrag_id)
        status = snapshot.status if snapshot is not None else None
        if status != last_status:
            print(f"{auftrag_id} status={status or 'unknown'}")
            last_status = status
        if live_zone is not None:
            count = live_zone.n_red if coalition == "red" else live_zone.n_blue
            threat = live_zone.threat_red if coalition == "red" else live_zone.threat_blue
            owner = (live_zone.owner_current_name or "neutral").lower()
            if (
                (count or 0) > 0
                and (threat or 0) > 0
                and (not claim_neutral_zone or owner == coalition)
            ):
                print(
                    f"Occupation confirmed: owner={owner} red={live_zone.n_red or 0} "
                    f"blue={live_zone.n_blue or 0} threat_{coalition}={threat or 0} "
                    f"contested={live_zone.is_contested}"
                )
                return auftrag_id, live_zone
        if (status or "").lower() in {
            "success",
            "succeeded",
            "done",
            "cancelled",
            "failed",
        }:
            raise RuntimeError(
                f"defender staging {auftrag_id} ended with {status} before reaching {OPSZONE_ID}"
            )
        await asyncio.sleep(DEFENDER_POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"defender staging {auftrag_id} did not reach {OPSZONE_ID} within "
        f"{DEFENDER_STAGING_TIMEOUT_SECONDS:.0f} seconds"
    )


async def _wait_for_initial_owner(bridge):
    deadline = time.monotonic() + OWNER_INITIALIZATION_TIMEOUT_SECONDS
    last_owner = None
    opszone = None
    while time.monotonic() < deadline:
        await bridge.snapshot_opszones()
        opszone = bridge.state.opszone_objects.get(OPSZONE_ID)
        if opszone is None:
            raise ValueError(f"OPSZONE snapshot is unavailable: {OPSZONE_ID}")
        owner = (opszone.owner_current_name or "neutral").lower()
        if owner in {"blue", "red"}:
            return opszone, owner
        if owner != last_owner:
            print(
                f"Waiting for {OPSZONE_ID} initial owner: "
                f"owner={owner} red={opszone.n_red or 0} blue={opszone.n_blue or 0}"
            )
            last_owner = owner
        await asyncio.sleep(OWNER_INITIALIZATION_POLL_SECONDS)
    if opszone is None:
        raise ValueError(f"OPSZONE snapshot is unavailable: {OPSZONE_ID}")
    return opszone, "neutral"


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

    if CAPTURING_COALITION not in {None, "blue", "red"}:
        raise ValueError("CAPTURING_COALITION must be 'blue', 'red', or None")

    objective_id = f"OBJECTIVE:{OPSZONE_ID}"
    live_opszone, live_owner = await _wait_for_initial_owner(bridge)
    staged_defender_id = None
    if live_owner == "neutral":
        capturing_coalition = CAPTURING_COALITION or "blue"
        defending_coalition = "red" if capturing_coalition == "blue" else "blue"
        staged_defender_id, live_opszone = await _stage_defender(
            bridge,
            live_opszone,
            defending_coalition,
            claim_neutral_zone=True,
        )
    else:
        defending_coalition = live_owner
        capturing_coalition = CAPTURING_COALITION
        if capturing_coalition is None:
            capturing_coalition = "red" if defending_coalition == "blue" else "blue"

    # OPSZONE ownership is authoritative. Refresh the generated objective before
    # deriving either role so a stale strategic snapshot cannot invert them.
    bridge.sync_strategic_objectives(source="capture_reaction.live_owner")
    objective = bridge.strategic_objective(objective_id)
    if objective is None:
        raise ValueError(f"strategic objective is unavailable: {objective_id}")
    objective_owner = (objective.owner or "neutral").lower()
    if objective_owner != defending_coalition:
        raise RuntimeError(
            f"OPSZONE/objective ownership mismatch for {OPSZONE_ID}: "
            f"live={defending_coalition} objective={objective_owner}"
        )
    if defending_coalition == capturing_coalition:
        raise ValueError(
            f"{OPSZONE_ID} is already controlled by {capturing_coalition}; "
            "choose the opposing coalition or use automatic selection"
        )

    intel_id = BLUE_INTEL_ID if capturing_coalition == "blue" else RED_INTEL_ID
    picture = await bridge.refresh_tactical_picture(capturing_coalition, intel_id)
    opszone = next((item for item in picture.opszones if item.object_id == OPSZONE_ID), None)
    if opszone is None:
        raise ValueError(f"OPSZONE snapshot is unavailable: {OPSZONE_ID}")
    picture_owner = (opszone.owner_current_name or "neutral").lower()
    if picture_owner != defending_coalition:
        raise RuntimeError(
            f"{OPSZONE_ID} changed owner while preparing the test: "
            f"{defending_coalition}->{picture_owner}"
        )
    defending_units = opszone.n_red if defending_coalition == "red" else opszone.n_blue
    defending_threat = (
        opszone.threat_red if defending_coalition == "red" else opszone.threat_blue
    )
    defended = bool(
        opszone.is_contested
        or (defending_units or 0) > 0
        or (defending_threat or 0) > 0
    )
    print("\nInitial OPSZONE state")
    print("=" * 96)
    print(
        f"{OPSZONE_ID} owner={opszone.owner_current_name or 'unknown'} "
        f"contested={opszone.is_contested} red={opszone.n_red or 0} "
        f"blue={opszone.n_blue or 0} threat_red={opszone.threat_red or 0} "
        f"threat_blue={opszone.threat_blue or 0}"
    )
    if REQUIRE_DEFENDED_TARGET and not defended:
        if not STAGE_DEFENDER_IF_NEEDED:
            raise ValueError(
                f"{OPSZONE_ID} is not actively defended by {defending_coalition}; "
                f"place at least one alive {defending_coalition} ground group inside the OPSZONE "
                "and restart the mission"
            )
        staged_defender_id, opszone = await _stage_defender(
            bridge,
            opszone,
            defending_coalition,
        )

    await bridge.refresh_diplomacy_state()
    if bridge.relationship.state is not RelationshipState.WAR:
        if not DECLARE_WAR_IF_NEEDED:
            raise ValueError(
                "relationship must be war; run examples/sdk/declare_war.py or enable "
                "DECLARE_WAR_IF_NEEDED"
            )
        bridge.declare_war(
            capturing_coalition,
            reason="Capture-reaction acceptance test",
        )
        await bridge.persist_diplomacy_state()
        print(f"\n{capturing_coalition.title()} declared war for this acceptance test.")

    token = _mission_token(bridge)
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=f"GOAL:{capturing_coalition}:capture:Town-Gali:ACCEPTANCE:{token}",
            name=f"{capturing_coalition.title()} capture Town Gali",
            coalition=capturing_coalition,
            action=StrategicGoalAction.CAPTURE,
            objective_id=objective.objective_id,
            priority=max(90.0, objective.priority),
        )
    )
    plan = bridge.add_operational_plan(
        bridge.propose_capture_plan(
            goal,
            picture,
            plan_id=f"PLAN:{capturing_coalition}:capture:Town-Gali:ACCEPTANCE:{token}",
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
    if objective.owner != capturing_coalition:
        raise RuntimeError(
            f"capture was not confirmed by OPSZONE ownership: owner={objective.owner or 'unknown'}"
        )
    if goal.status is not StrategicGoalStatus.ACHIEVED:
        raise RuntimeError(f"capture goal ended with {goal.status.value}")

    secured_zone = bridge.state.opszone_objects.get(OPSZONE_ID)
    secured_count = (
        secured_zone.n_blue if capturing_coalition == "blue" else secured_zone.n_red
    ) if secured_zone is not None else 0
    secured_threat = (
        secured_zone.threat_blue if capturing_coalition == "blue" else secured_zone.threat_red
    ) if secured_zone is not None else 0
    if (
        secured_zone is None
        or secured_zone.is_contested
        or (secured_count or 0) <= 0
        or (secured_threat or 0) <= 0
    ):
        raise RuntimeError(
            f"captured OPSZONE has no combat-capable occupation: "
            f"units={secured_count or 0} threat={secured_threat or 0}"
        )

    guards = tuple(
        mission
        for mission in execution.missions
        if mission.mission_type == "PATROLZONE" and mission.persistent
    )
    if not guards or any(mission.status is not PlanMissionStatus.RUNNING for mission in guards):
        states = ", ".join(mission.status.value for mission in guards) or "missing"
        raise RuntimeError(f"persistent PATROLZONE guard was not established: {states}")

    opposing_intel = RED_INTEL_ID if defending_coalition == "red" else BLUE_INTEL_ID
    opposing_picture = await bridge.refresh_tactical_picture(defending_coalition, opposing_intel)
    reaction = bridge.recommend_strategic_portfolio(
        defending_coalition,
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
        reasons = "; ".join(_reaction_failure_reason(item) for item in reaction.decisions)
        raise RuntimeError(f"opponent did not select the recapture reaction: {reasons}")

    print("\nMilestone 4 acceptance")
    print("=" * 96)
    print(f"Captured objective : {objective.objective_id} owner={objective.owner}")
    if staged_defender_id:
        print(f"Initial defender   : {staged_defender_id} coalition={defending_coalition}")
    print(
        "Persistent guard   : "
        + ", ".join(
            f"{item.auftrag_id} {item.mission_type} status={item.status.value}"
            for item in guards
        )
    )
    print(
        f"Combat presence   : units={secured_count or 0} "
        f"threat={secured_threat or 0} contested={secured_zone.is_contested}"
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
