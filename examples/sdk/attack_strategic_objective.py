"""Plan and execute a verified strategic infrastructure attack."""

from __future__ import annotations

from pathlib import Path
import uuid

from example_support import load_example_theater, open_example_session, run_example

from moosebridge import (
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjectiveGenerationConfig,
    OperationalPlanStatus,
    StrategicVerificationRegistry,
    TheaterTransportInfrastructure,
    format_operational_plan_assessment,
    format_operational_plan_execution,
)
from moosebridge.control import DEFAULT_CONTROL_PORT


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT
COMMAND_TIMEOUT_SECONDS = 30.0
MISSION_TIMEOUT_SECONDS = 3_600.0

THEATER_PROFILE = (
    Path(__file__).resolve().parents[2]
    / "python"
    / "moosebridge"
    / "data"
    / "Caucasus_topography.json"
)
TARGET_SOURCE_ID = "BRIDGE:Caucasus:4d482fb330eb"
ATTACKING_COALITION = "red"
EXPECTED_TARGET_OWNER = "blue"
INTEL_ID = "INTEL:Red Intel"
REQUIRED_DAMAGE = 1.0
MAX_STRIKE_ROUNDS = 2
REQUIRE_WAR = True
DECLARE_WAR_IF_NEEDED = True
WAR_DECLARATION_REASON = "Attack a verified strategic infrastructure objective"

APPROVE_IF_FEASIBLE = True
# Keep the first run plan-only. Set True after inspecting the printed assignment.
EXECUTE_IF_APPROVED = True

CLIENT_ID = "strategic-objective-attack-example"
CLIENT_DISPLAY_NAME = "Strategic Objective Attack Example"


async def run() -> int:
    theater, theater_paths = load_example_theater(THEATER_PROFILE)
    verifications = StrategicVerificationRegistry.load(
        theater_paths.path("strategic_verifications")
    ).bind_theater(theater.theater_id)
    verification = verifications.get(TARGET_SOURCE_ID)
    if verification is None:
        raise ValueError(f"No DCS scenery verification exists for {TARGET_SOURCE_ID}")
    if not verification.admitted or not verification.target_components:
        raise ValueError(
            f"{TARGET_SOURCE_ID} is not attackable: verification={verification.state.value} "
            f"targets={len(verification.target_components)}"
        )

    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
        client_id=CLIENT_ID,
        display_name=CLIENT_DISPLAY_NAME,
    )
    bridge = session.bridge
    await bridge.refresh_global_picture()
    await bridge.refresh_diplomacy_state()

    generation = bridge.generate_strategic_objectives(
        transport=TheaterTransportInfrastructure.load(
            theater_paths.path("transport_infrastructure")
        ),
        verifications=verifications,
        config=StrategicObjectiveGenerationConfig(
            include_airbases=False,
            include_opszones=False,
            minimum_transport_importance=0.0,
            maximum_geographic_objectives_per_category_per_scope=None,
        ),
    )
    objective_id = f"OBJECTIVE:{TARGET_SOURCE_ID}"
    objective = bridge.strategic_objective(objective_id)
    if objective is None:
        exclusion = next(
            (item for item in generation.exclusions if item.object_id == TARGET_SOURCE_ID),
            None,
        )
        reason = exclusion.reason if exclusion is not None else "not generated"
        raise ValueError(f"Strategic objective unavailable for {TARGET_SOURCE_ID}: {reason}")
    if objective.owner != EXPECTED_TARGET_OWNER:
        raise ValueError(
            f"Target owner is {objective.owner or 'unknown'}, expected {EXPECTED_TARGET_OWNER}"
        )
    if objective.owner == ATTACKING_COALITION:
        raise ValueError("Attacking coalition owns the selected objective")
    declared_war = False
    if REQUIRE_WAR and bridge.relationship.state.value != "war":
        if not DECLARE_WAR_IF_NEEDED:
            raise ValueError(
                f"Coalition relationship is {bridge.relationship.state.value}; "
                "declare war before attacking or set DECLARE_WAR_IF_NEEDED=True"
            )
        bridge.declare_war(
            ATTACKING_COALITION,
            reason=WAR_DECLARATION_REASON,
        )
        await bridge.persist_diplomacy_state()
        declared_war = True

    mission_time = bridge.state.clock.mission_time if bridge.state.clock else None
    if mission_time is None:
        print("DCS mission time is unavailable.")
        return 1
    run_id = f"{mission_time:.3f}-{uuid.uuid4().hex[:8]}"
    goal = bridge.add_strategic_goal(
        StrategicGoal(
            goal_id=f"GOAL:{ATTACKING_COALITION}:destroy:{TARGET_SOURCE_ID}/RUN:{run_id}",
            name=f"Destroy {objective.name}",
            coalition=ATTACKING_COALITION,
            action=StrategicGoalAction.DESTROY,
            objective_id=objective.objective_id,
            priority=objective.priority,
            required_damage=REQUIRED_DAMAGE,
        ),
        activate=True,
    )

    print("Strategic infrastructure attack")
    print("=" * 88)
    print(f"Theater        : {theater.theater_id}")
    print(f"Source         : {TARGET_SOURCE_ID}")
    print(f"Objective      : {objective.objective_id}")
    print(f"Owner          : {objective.owner}")
    print(f"Attacker       : {ATTACKING_COALITION}")
    print(f"Relationship   : {bridge.relationship.state.value}")
    if declared_war:
        print(f"War declaration: {ATTACKING_COALITION} ({WAR_DECLARATION_REASON})")
    print(f"Required damage: {REQUIRED_DAMAGE:.0%}")
    print(f"Components     : {len(objective.components)}")
    for component in objective.components:
        print(f"  {component.object_id} weight={component.weight:.2f}")

    for strike_round in range(1, MAX_STRIKE_ROUNDS + 1):
        picture = await bridge.refresh_tactical_picture(ATTACKING_COALITION, INTEL_ID)
        eligible = [
            cohort
            for cohort in picture.cohorts
            if cohort.is_air
            and (cohort.available_asset_count or 0) > 0
            and "STRIKE" in cohort.mission_type_keys
            and cohort.has_payload_for("STRIKE") is True
        ]
        if not eligible:
            print(
                f"\nNo available {ATTACKING_COALITION} AIR cohort supports STRIKE with an available payload."
            )
            return 2

        plan = bridge.add_operational_plan(
            bridge.propose_destroy_plan(
                goal,
                picture,
                plan_id=(
                    f"PLAN:{ATTACKING_COALITION}:destroy:{TARGET_SOURCE_ID}"
                    f"/RUN:{run_id}/ROUND:{strike_round}"
                ),
            )
        )
        assessment = await bridge.refresh_and_validate_operational_plan(plan)
        if assessment.feasible and APPROVE_IF_FEASIBLE:
            bridge.approve_operational_plan(
                plan,
                reason=f"Strategic infrastructure strike round {strike_round} approved",
            )

        print()
        print(format_operational_plan_assessment(plan, assessment))
        if not assessment.feasible:
            return 2
        if not APPROVE_IF_FEASIBLE:
            print("\nPlan is feasible but remains unapproved.")
            return 0
        if not EXECUTE_IF_APPROVED:
            print("\nPlan is approved. Set EXECUTE_IF_APPROVED=True to launch the strike.")
            return 0

        print(f"\nExecuting strategic strike round {strike_round} ...")
        execution = await bridge.execute_plan(
            plan,
            mission_timeout_s=MISSION_TIMEOUT_SECONDS,
            on_event=print,
        )
        print()
        print(format_operational_plan_execution(execution))
        if execution.status is not OperationalPlanStatus.COMPLETED:
            print("\nStrike execution did not complete; no automatic follow-up round will be launched.")
            return 2
        if goal.status is StrategicGoalStatus.ACHIEVED:
            return 0
        if strike_round < MAX_STRIKE_ROUNDS:
            print("\nDamage threshold not reached. Replanning another strike round ...")

    print(f"\nDamage threshold was not reached after {MAX_STRIKE_ROUNDS} strike rounds.")
    return 2


def main() -> int:
    return run_example(run)


if __name__ == "__main__":
    raise SystemExit(main())
