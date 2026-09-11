"""Submit one neutral claim and interrupt its client for coordinator recovery."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

from example_support import open_example_session, run_example
import run_mission_conflict as conflict

from moosebridge import (
    ObjectiveKind,
    RelationshipState,
    StrategicGoalAction,
    StrategicObjectiveGenerationConfig,
    format_bilateral_strategic_recommendation,
    format_conflict_readiness,
)
from moosebridge.operational_execution import PLAN_EXECUTION_AUDIT_TYPE
from moosebridge.strategic_coordinator import STRATEGIC_COORDINATOR_APPROVER


# None lets the normal planner rank all currently neutral OPSZONEs.
# Set an exact OPSZONE id here to restrict the test to one zone.
OPSZONE_ID: str | None = None
CLAIMING_COALITION = "red"


class _ClaimSubmitted(asyncio.CancelledError):
    """Stop the client without marking its persisted execution as failed."""

    def __init__(self, event):
        super().__init__("Intentional client interruption after claim submission")
        self.event = event


def _interrupt_after_submission(event):
    print(f"[{CLAIMING_COALITION}] {event}", flush=True)
    # OperationalPlanExecutor persists the submission before this callback.
    # Cancellation leaves the actual DCS AUFTRAG running for the next client.
    if event.event == "mission.submitted" and event.mission_type == "PATROLZONE":
        raise _ClaimSubmitted(event)


def _neutral_objectives(readiness, state):
    generation = readiness.objective_generation
    if generation is None:
        return ()
    return tuple(
        objective
        for objective in generation.objectives
        if objective.kind is ObjectiveKind.OPSZONE
        and objective.owner == "neutral"
        and (OPSZONE_ID is None or objective.control_object_id == OPSZONE_ID)
        and (zone := state.opszone_objects.get(objective.control_object_id)) is not None
        and zone.owner_current_name == "neutral"
        and zone.is_contested is False
    )


def _require_recoverable_checkpoint(records, event, state):
    for record in records:
        payload = record.get("payload", {})
        if (
            payload.get("plan_id") == event.plan_id
            and payload.get("attempt_id") == event.attempt_id
            and payload.get("mission_generation") == state.mission_generation
            and payload.get("audit_session_id") == state.audit_session_id
            and payload.get("status") == "executing"
            and payload.get("plan", {}).get("approved_by") == STRATEGIC_COORDINATOR_APPROVER
            and payload.get("plan", {}).get("metadata", {}).get("candidate_id")
            and any(
                mission.get("auftrag_id") == event.auftrag_id
                and mission.get("mission_type") == "PATROLZONE"
                and mission.get("status") == "submitted"
                for mission in payload.get("missions", ())
            )
        ):
            return
    raise RuntimeError("The submitted claim has no recoverable current-session audit checkpoint")


async def run(profile_path=conflict.THEATER_PROFILE) -> int:
    session = await open_example_session(
        conflict.CONTROL_HOST,
        conflict.CONTROL_PORT,
        conflict.COMMAND_TIMEOUT_SECONDS,
        client_id="claim-recovery-preparation",
        display_name="Neutral Claim Recovery Preparation",
    )
    bridge = session.bridge
    records = await bridge.server.query_audit_records(
        record_type=PLAN_EXECUTION_AUDIT_TYPE, latest_attempts=True,
    )
    if any(
        (payload := record.get("payload", {})).get("status") == "executing"
        and payload.get("mission_generation") == bridge.state.mission_generation
        and payload.get("audit_session_id") == bridge.state.audit_session_id
        for record in records
    ):
        raise ValueError("An interrupted or active plan already exists; use the recovery runner or a fresh mission")

    readiness = await bridge.assess_conflict_readiness(
        theater=conflict._load_context(profile_path),
        intel_ids={"blue": conflict.BLUE_INTEL_ID, "red": conflict.RED_INTEL_ID},
        objective_config=StrategicObjectiveGenerationConfig(),
        register_objectives=False,
        timeout=conflict.COMMAND_TIMEOUT_SECONDS,
    )
    print(format_conflict_readiness(readiness), flush=True)
    readiness.require_ready()
    objectives = _neutral_objectives(readiness, bridge.state)
    if not objectives:
        raise ValueError("No verified neutral, uncontested OPSZONE is available; start a fresh test mission")

    await bridge.refresh_diplomacy_state()
    if bridge.relationship.state is not RelationshipState.WAR:
        bridge.declare_war(CLAIMING_COALITION, reason="Neutral claim recovery acceptance test")
        await bridge.persist_diplomacy_state()
        print(f"{CLAIMING_COALITION} declared war for the recovery test.", flush=True)

    # Restrict only this test recommendation. The production planner and all
    # activation, recruitment, execution, and recovery checks remain in use.
    scoped = replace(
        readiness,
        objective_generation=replace(readiness.objective_generation, objectives=objectives),
    )
    recommendation = await bridge.recommend_bilateral_strategy(scoped)
    print(format_bilateral_strategic_recommendation(recommendation), flush=True)
    selected = recommendation.coalition(CLAIMING_COALITION).selected
    if len(selected) != 1:
        raise ValueError("No single feasible neutral claim was selected; inspect the recommendation shortfalls")
    decision = selected[0]
    if (
        decision.action is not StrategicGoalAction.CAPTURE
        or decision.plan is None
        or decision.plan.metadata.get("capture_mode") != "neutral_claim"
        or not decision.plan.phases
        or decision.plan.phases[0].phase_id != "claim"
        or {kind for intent in decision.plan.phases[0].intents for kind in intent.auftrag_types}
        != {"PATROLZONE"}
    ):
        raise ValueError("The selected plan does not begin with a neutral-claim patrol; no mission was submitted")
    activation = await bridge.activate_strategic_decision(recommendation, decision)

    try:
        await bridge.execute_strategic_activation(
            activation,
            approved_by=STRATEGIC_COORDINATOR_APPROVER,
            approval_reason="Prepare an interrupted neutral claim for production coordinator recovery",
            mission_timeout_s=conflict.MISSION_TIMEOUT_SECONDS,
            on_event=_interrupt_after_submission,
        )
    except _ClaimSubmitted as interrupted:
        event = interrupted.event
        records = await bridge.server.query_audit_records(
            record_type=PLAN_EXECUTION_AUDIT_TYPE, plan_id=event.plan_id, latest_attempts=True,
        )
        _require_recoverable_checkpoint(records, event, bridge.state)
        await bridge.snapshot_opszones()
        if (
            activation.mission_generation != bridge.state.mission_generation
            or not any(
                objective.control_object_id == activation.objective.control_object_id
                for objective in _neutral_objectives(scoped, bridge.state)
            )
        ):
            raise ValueError("The claim was submitted, but its zone is no longer neutral or its mission ended; the test window was missed")
        print(
            f"\nCHECKPOINT READY: plan={event.plan_id} auftrag={event.auftrag_id} "
            f"zone={activation.objective.control_object_id} owner=neutral\n"
            "The client stopped intentionally; the DCS patrol remains active.\n"
            "Start run_mission_conflict.py now. Keep DCS and the daemon running.",
            flush=True,
        )
        return 0
    raise RuntimeError("Execution ended without reaching the neutral-claim restart checkpoint")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=conflict.THEATER_PROFILE)
    return run_example(lambda: run(parser.parse_args().profile))


if __name__ == "__main__":
    raise SystemExit(main())
