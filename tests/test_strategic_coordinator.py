from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from moosebridge import (
    AssetRequirement,
    AssetRole,
    BilateralConflictCoordinator,
    BilateralConflictRun,
    BilateralStrategicRecommendation,
    MissionIntent,
    ObjectiveKind,
    OperationalPlan,
    OperationalPlanAssessment,
    OperationalPlanExecution,
    OperationalPlanReconciliation,
    OperationalPlanStatus,
    OwnershipPolicy,
    PlanPhase,
    RelationshipState,
    StrategicAttemptStatus,
    StrategicCoalitionCycle,
    StrategicCoordinatorConfig,
    StrategicRecoveryStatus,
    StrategicCycleStatus,
    StrategicDecision,
    StrategicDecisionDisposition,
    StrategicDecisionPortfolio,
    StrategicDecisionReasonCode,
    StrategicDecisionActivation,
    StrategicGoal,
    StrategicGoalAction,
    StrategicGoalStatus,
    StrategicObjective,
    PlanReconciliationStatus,
    format_bilateral_conflict_run,
    format_strategic_coalition_cycle,
)
from moosebridge.clock import DcsTime


class _Readiness:
    def __init__(self, client: _Client) -> None:
        self._client = client

    @property
    def mission_generation(self) -> int:
        return self._client.state.mission_generation

    @property
    def mission_time(self) -> float | None:
        return self._client.state.clock.mission_time

    def require_ready(self) -> _Readiness:
        return self


class _AuditServer:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, object]]] = []
        self.query_records: list[dict[str, object]] = []

    async def append_audit_record(
        self,
        record_type: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.records.append((record_type, payload))
        return payload

    async def query_audit_records(
        self,
        *,
        record_type: str | None = None,
        plan_id: str | None = None,
        attempt_id: str | None = None,
        latest_attempts: bool = False,
    ) -> tuple[dict[str, object], ...]:
        del latest_attempts
        result = []
        for record in self.query_records:
            payload = record.get("payload")
            if record_type is not None and record.get("record_type") != record_type:
                continue
            if plan_id is not None and isinstance(payload, dict) and payload.get("plan_id") != plan_id:
                continue
            if attempt_id is not None and isinstance(payload, dict) and payload.get("attempt_id") != attempt_id:
                continue
            result.append(record)
        return tuple(result)


class _Client:
    def __init__(
        self,
        recommendation: BilateralStrategicRecommendation,
        activations: dict[str, StrategicDecisionActivation],
    ) -> None:
        self.state = SimpleNamespace(
            mission_generation=0,
            clock=DcsTime(mission_time=100.0),
            audit_session_id="test-session",
        )
        self.relationship = SimpleNamespace(state=RelationshipState.WAR)
        self.server = _AuditServer()
        self.recommendation = recommendation
        self.activations = activations
        self.goals = {
            activation.goal.goal_id: activation.goal for activation in activations.values()
        }
        self.plans = {
            activation.plan.plan_id: activation.plan for activation in activations.values()
        }
        self.excluded_calls: list[dict[str, set[str]]] = []
        self.execute_probe = None
        self.activation_calls: list[str] = []
        self.restore_calls: list[str] = []
        self.monitor_calls: list[str] = []
        self.resume_execute_calls: list[str] = []
        self.recovery_context = None
        self.reconciliation_status = PlanReconciliationStatus.COMPLETED

    async def recommend_bilateral_strategy(self, readiness, **kwargs):
        excluded = {
            coalition: set(candidate_ids)
            for coalition, candidate_ids in kwargs.get("excluded_candidate_ids", {}).items()
        }
        self.excluded_calls.append(excluded)
        portfolios = []
        for portfolio in self.recommendation.portfolios:
            decisions = tuple(
                replace(
                    decision,
                    disposition=StrategicDecisionDisposition.DEFERRED,
                    reason_code=StrategicDecisionReasonCode.COOLDOWN,
                    reason="candidate is in a coordinator cooldown period",
                    goal=None,
                    plan=None,
                    assessment=None,
                )
                if decision.candidate_id in excluded.get(portfolio.coalition, set())
                else decision
                for decision in portfolio.decisions
            )
            portfolios.append(replace(portfolio, decisions=decisions))
        return replace(
            self.recommendation,
            mission_time=readiness.mission_time,
            portfolios=tuple(portfolios),
        )

    async def activate_strategic_decision(self, recommendation, decision, **kwargs):
        self.activation_calls.append(decision.candidate_id)
        return self.activations[decision.candidate_id]

    async def execute_strategic_activation(self, activation, **kwargs):
        if self.execute_probe is not None:
            await self.execute_probe(activation.coalition)
        execution = OperationalPlanExecution(
            plan_id=activation.plan.plan_id,
            commander_id=f"COMMANDER:{activation.coalition}",
            attempt_id=f"{activation.plan.plan_id}/ATTEMPT:1",
            status=activation.plan.metadata.get(
                "test_execution_status", OperationalPlanStatus.COMPLETED
            ),
            blocked_reason=activation.plan.metadata.get("test_blocked_reason"),
        )
        return execution

    def strategic_goal(self, goal_id: str) -> StrategicGoal | None:
        return self.goals.get(goal_id)

    def operational_plan(self, plan_id: str) -> OperationalPlan | None:
        return self.plans.get(plan_id)

    async def restore_operational_plan(self, plan_id: str, *, replace: bool = False):
        assert replace is True
        self.restore_calls.append(plan_id)
        if self.recovery_context is None:
            raise KeyError(plan_id)
        return self.recovery_context

    async def monitor_interrupted_operational_plan(self, plan, **kwargs):
        self.monitor_calls.append(plan.plan_id)
        context = self.recovery_context
        assert context is not None
        if self.reconciliation_status is PlanReconciliationStatus.COMPLETED:
            plan.status = OperationalPlanStatus.COMPLETED
            context.goal.status = StrategicGoalStatus.ACHIEVED
        elif self.reconciliation_status is PlanReconciliationStatus.REVALIDATION_REQUIRED:
            plan.status = OperationalPlanStatus.BLOCKED
        return OperationalPlanReconciliation(
            plan.plan_id,
            f"{plan.plan_id}/ATTEMPT:1",
            self.reconciliation_status,
            (),
        )

    def prepare_plan_retry(self, plan):
        plan.status = OperationalPlanStatus.DRAFT
        return plan

    async def refresh_and_validate_operational_plan(self, plan):
        plan.status = OperationalPlanStatus.VALIDATED
        return OperationalPlanAssessment(plan.plan_id, True, (), ())

    def approve_operational_plan(self, plan, **kwargs):
        plan.status = OperationalPlanStatus.APPROVED
        return plan

    async def execute_plan(self, plan, **kwargs):
        self.resume_execute_calls.append(plan.plan_id)
        plan.status = OperationalPlanStatus.COMPLETED
        context = self.recovery_context
        assert context is not None
        context.goal.status = StrategicGoalStatus.ACHIEVED
        return OperationalPlanExecution(
            plan_id=plan.plan_id,
            commander_id="COMMANDER:blue",
            attempt_id=f"{plan.plan_id}/ATTEMPT:2",
            attempt_number=2,
            status=OperationalPlanStatus.COMPLETED,
        )

    def complete_strategic_goal(
        self,
        goal: StrategicGoal,
        *,
        achieved: bool,
        reason: str | None = None,
    ) -> StrategicGoal:
        goal.status = StrategicGoalStatus.ACHIEVED if achieved else StrategicGoalStatus.FAILED
        goal.failure_reason = None if achieved else reason
        return goal


def _decision(coalition: str, suffix: str) -> tuple[StrategicDecision, StrategicDecisionActivation]:
    objective = StrategicObjective(
        objective_id=f"OBJECTIVE:{suffix}",
        name=suffix,
        kind=ObjectiveKind.OPSZONE,
        ownership_policy=OwnershipPolicy.MOOSE_MANAGED,
        owner="red" if coalition == "blue" else "blue",
        control_object_id=f"OPSZONE:{suffix}",
        strategic_value=80.0,
        priority=80.0,
    )
    goal = StrategicGoal(
        goal_id=f"GOAL:{coalition}:{suffix}",
        name=f"Capture {suffix}",
        coalition=coalition,
        action=StrategicGoalAction.CAPTURE,
        objective_id=objective.objective_id,
        status=StrategicGoalStatus.ACTIVE,
    )
    requirement = AssetRequirement(
        requirement_id=f"REQ:{suffix}",
        role=AssetRole.COMBAT,
        mission_types=("CAPTUREZONE",),
    )
    intent = MissionIntent(
        intent_id=f"INTENT:{suffix}",
        name=f"Capture {suffix}",
        auftrag_types=("CAPTUREZONE",),
        asset_requirements=(requirement,),
        target_object_id=objective.control_object_id,
    )
    plan = OperationalPlan(
        plan_id=f"PLAN:{coalition}:{suffix}",
        name=f"Capture {suffix}",
        goal_id=goal.goal_id,
        coalition=coalition,
        phases=(PlanPhase("seize", "Seize", (intent,)),),
        status=OperationalPlanStatus.VALIDATED,
    )
    assessment = OperationalPlanAssessment(plan.plan_id, True, (), ())
    candidate_id = f"CANDIDATE:{coalition}:{suffix}"
    decision = StrategicDecision(
        candidate_id=candidate_id,
        coalition=coalition,
        objective_id=objective.objective_id,
        objective_name=objective.name,
        action=StrategicGoalAction.CAPTURE,
        effect=None,
        disposition=StrategicDecisionDisposition.SELECTED,
        reason_code=StrategicDecisionReasonCode.SELECTED_FEASIBLE,
        reason="selected for coordinator test",
        objective=objective,
        goal=goal,
        plan=plan,
        assessment=assessment,
    )
    activation = StrategicDecisionActivation(
        activation_id=f"ACTIVATION:{coalition}:{suffix}",
        mission_generation=0,
        recommendation_mission_time=100.0,
        activated_mission_time=100.0,
        candidate_id=candidate_id,
        coalition=coalition,
        relationship_state="war",
        objective=objective,
        goal=goal,
        plan=plan,
        assessment=assessment,
    )
    return decision, activation


def _recommendation(
    *pairs: tuple[StrategicDecision, StrategicDecisionActivation],
) -> tuple[BilateralStrategicRecommendation, dict[str, StrategicDecisionActivation]]:
    decisions = {decision.coalition: decision for decision, _ in pairs}
    portfolios = tuple(
        StrategicDecisionPortfolio(
            coalition=coalition,
            mission_time=100.0,
            decisions=(decisions[coalition],),
        )
        for coalition in ("blue", "red")
        if coalition in decisions
    )
    recommendation = BilateralStrategicRecommendation(0, 100.0, "war", portfolios)
    return recommendation, {
        activation.candidate_id: activation for _, activation in pairs
    }


def _interrupted_record(
    decision: StrategicDecision,
    activation: StrategicDecisionActivation,
) -> dict[str, object]:
    return {
        "record_type": "operational_plan.execution",
        "payload": {
            "audit_session_id": "test-session",
            "mission_generation": 0,
            "plan_id": activation.plan.plan_id,
            "attempt_id": f"{activation.plan.plan_id}/ATTEMPT:1",
            "attempt_number": 1,
            "status": "executing",
            "started_mission_time": 90.0,
            "commander_id": "COMMANDER:blue",
            "plan": {
                "coalition": "blue",
                "approved_by": "Bilateral Conflict Coordinator",
                "metadata": {"candidate_id": decision.candidate_id},
            },
            "goal": {"objective_id": decision.objective_id},
            "objective": {"objective_id": decision.objective_id},
            "missions": [{"auftrag_id": "AUFTRAG:13"}],
        },
    }


def test_blocked_cycle_terminalizes_goal_and_suppresses_candidate_until_cooldown() -> None:
    async def scenario() -> None:
        pair = _decision("blue", "Blocked target")
        recommendation, activations = _recommendation(pair)
        activation = pair[1]
        activation.plan.metadata.update(
            test_execution_status=OperationalPlanStatus.BLOCKED,
            test_blocked_reason="insufficient surviving force",
        )
        client = _Client(recommendation, activations)
        readiness = _Readiness(client)
        coordinator = BilateralConflictCoordinator(
            client,
            lambda: asyncio.sleep(0, result=readiness),
            StrategicCoordinatorConfig(
                blue_cadence_s=10.0,
                red_cadence_s=10.0,
                blocked_cooldown_s=300.0,
                retain_audit=True,
            ),
        )

        first = await coordinator.run_cycle("blue")
        assert first is not None
        assert first.status is StrategicCycleStatus.BLOCKED
        assert first.attempts[0].status is StrategicAttemptStatus.BLOCKED
        assert activation.goal.status is StrategicGoalStatus.FAILED
        assert activation.goal.failure_reason == "insufficient surviving force"
        assert activation.plan.status is OperationalPlanStatus.FAILED

        client.state.clock = DcsTime(mission_time=111.0)
        second = await coordinator.run_cycle("blue")
        assert second is not None
        assert second.status is StrategicCycleStatus.NO_SELECTION
        assert client.excluded_calls[-1]["blue"] == {pair[0].candidate_id}
        assert coordinator.cooldowns[0].available_mission_time == 400.0
        assert [record_type for record_type, _ in client.server.records] == [
            "strategic_conflict_cycle",
            "strategic_conflict_cycle",
        ]
        assert client.server.records[0][1]["audit_session_id"] == "test-session"
        assert client.server.records[0][1]["status"] == "blocked"
        assert client.server.records[1][1]["status"] == "no_selection"

    asyncio.run(scenario())


def test_no_selection_uses_mission_time_backoff_before_recommending_again() -> None:
    async def scenario() -> None:
        recommendation = BilateralStrategicRecommendation(
            0,
            100.0,
            "war",
            (
                StrategicDecisionPortfolio("blue", 100.0, ()),
                StrategicDecisionPortfolio("red", 100.0, ()),
            ),
        )
        client = _Client(recommendation, {})
        readiness = _Readiness(client)
        coordinator = BilateralConflictCoordinator(
            client,
            lambda: asyncio.sleep(0, result=readiness),
            StrategicCoordinatorConfig(
                blue_cadence_s=10.0,
                red_cadence_s=10.0,
                no_selection_backoff_s=300.0,
                retain_audit=False,
            ),
        )

        first = await coordinator.run_cycle("blue")
        assert first is not None
        assert first.status is StrategicCycleStatus.NO_SELECTION

        client.state.clock = DcsTime(mission_time=399.0)
        assert await coordinator.run_cycle("blue") is None
        assert len(client.excluded_calls) == 1

        client.state.clock = DcsTime(mission_time=400.0)
        second = await coordinator.run_cycle("blue")
        assert second is not None
        assert second.status is StrategicCycleStatus.NO_SELECTION
        assert second.cycle_number == 2
        assert len(client.excluded_calls) == 2

    asyncio.run(scenario())


def test_coordinator_restores_no_selection_backoff_from_current_session() -> None:
    async def scenario() -> None:
        recommendation = BilateralStrategicRecommendation(
            0,
            100.0,
            "war",
            (
                StrategicDecisionPortfolio("blue", 100.0, ()),
                StrategicDecisionPortfolio("red", 100.0, ()),
            ),
        )
        client = _Client(recommendation, {})
        client.server.query_records.append(
            {
                "record_type": "strategic_conflict_cycle",
                "payload": {
                    "audit_session_id": "test-session",
                    "mission_generation": 0,
                    "coalition": "blue",
                    "cycle_number": 7,
                    "started_mission_time": 95.0,
                    "status": "no_selection",
                    "attempts": [],
                },
            }
        )
        readiness = _Readiness(client)
        coordinator = BilateralConflictCoordinator(
            client,
            lambda: asyncio.sleep(0, result=readiness),
            StrategicCoordinatorConfig(
                blue_cadence_s=1.0,
                red_cadence_s=1.0,
                no_selection_backoff_s=20.0,
                retain_audit=False,
            ),
        )

        await coordinator._load_audit_state()
        assert await coordinator.run_cycle("blue") is None
        assert client.excluded_calls == []

        client.state.clock = DcsTime(mission_time=115.0)
        cycle = await coordinator.run_cycle("blue")
        assert cycle is not None
        assert cycle.cycle_number == 8
        assert cycle.status is StrategicCycleStatus.NO_SELECTION

    asyncio.run(scenario())


def test_coordinator_restores_current_session_cycle_numbers_and_cooldowns() -> None:
    async def scenario() -> None:
        blue = _decision("blue", "Blue audited target")
        red = _decision("red", "Red audited target")
        recommendation, activations = _recommendation(blue, red)
        client = _Client(recommendation, activations)
        for cycle_number, pair in ((3, blue), (7, red)):
            decision = pair[0]
            client.server.query_records.append(
                {
                    "record_type": "strategic_conflict_cycle",
                    "payload": {
                        "audit_session_id": "test-session",
                        "mission_generation": 0,
                        "coalition": decision.coalition,
                        "cycle_number": cycle_number,
                        "started_mission_time": 95.0,
                        "status": "completed",
                        "attempts": [
                            {
                                "candidate_id": decision.candidate_id,
                                "objective_id": decision.objective_id,
                                "status": "completed",
                                "cooldown_until": 500.0,
                            }
                        ],
                    },
                }
            )
        readiness = _Readiness(client)
        coordinator = BilateralConflictCoordinator(
            client,
            lambda: asyncio.sleep(0, result=readiness),
            StrategicCoordinatorConfig(
                blue_cadence_s=1.0,
                red_cadence_s=1.0,
                retain_audit=False,
            ),
        )

        result = await coordinator.run(cycles_per_coalition=1)

        assert result.coalition("blue")[0].cycle_number == 4
        assert result.coalition("red")[0].cycle_number == 8
        assert all(cycle.status is StrategicCycleStatus.NO_SELECTION for cycle in result.cycles)
        assert client.activation_calls == []
        assert client.excluded_calls[0]["blue"] == {blue[0].candidate_id}
        assert client.excluded_calls[1]["red"] == {red[0].candidate_id}

    asyncio.run(scenario())


def test_coordinator_recovers_interrupted_plan_before_selecting_new_work() -> None:
    async def scenario() -> None:
        blue = _decision("blue", "Interrupted target")
        decision, activation = blue
        activation.plan.status = OperationalPlanStatus.EXECUTING
        recommendation = BilateralStrategicRecommendation(
            0,
            100.0,
            "war",
            (
                StrategicDecisionPortfolio("blue", 100.0, (decision,)),
                StrategicDecisionPortfolio("red", 100.0, ()),
            ),
        )
        client = _Client(recommendation, {decision.candidate_id: activation})
        client.recovery_context = SimpleNamespace(
            objective=activation.objective,
            goal=activation.goal,
            plan=activation.plan,
        )
        client.server.query_records.append(_interrupted_record(decision, activation))
        readiness = _Readiness(client)
        coordinator = BilateralConflictCoordinator(
            client,
            lambda: asyncio.sleep(0, result=readiness),
            StrategicCoordinatorConfig(
                blue_cadence_s=1.0,
                red_cadence_s=1.0,
                completed_cooldown_s=300.0,
                retain_audit=False,
            ),
        )

        result = await coordinator.run(cycles_per_coalition=1)

        assert client.restore_calls == [activation.plan.plan_id]
        assert client.monitor_calls == [activation.plan.plan_id]
        assert client.activation_calls == []
        assert result.recoveries[0].status is StrategicRecoveryStatus.COMPLETED
        assert result.recoveries[0].auftrag_ids == ("AUFTRAG:13",)
        assert result.coalition("blue")[0].status is StrategicCycleStatus.NO_SELECTION
        assert client.excluded_calls[0]["blue"] == {decision.candidate_id}

    asyncio.run(scenario())


def test_coordinator_revalidates_remaining_phases_after_recovered_phase() -> None:
    async def scenario() -> None:
        decision, activation = _decision("blue", "Multi-phase target")
        activation.plan.status = OperationalPlanStatus.EXECUTING
        recommendation = BilateralStrategicRecommendation(
            0,
            100.0,
            "war",
            (
                StrategicDecisionPortfolio("blue", 100.0, (decision,)),
                StrategicDecisionPortfolio("red", 100.0, ()),
            ),
        )
        client = _Client(recommendation, {decision.candidate_id: activation})
        client.recovery_context = SimpleNamespace(
            objective=activation.objective,
            goal=activation.goal,
            plan=activation.plan,
        )
        client.reconciliation_status = PlanReconciliationStatus.REVALIDATION_REQUIRED
        client.server.query_records.append(_interrupted_record(decision, activation))
        readiness = _Readiness(client)
        coordinator = BilateralConflictCoordinator(
            client,
            lambda: asyncio.sleep(0, result=readiness),
            StrategicCoordinatorConfig(
                blue_cadence_s=1.0,
                red_cadence_s=1.0,
                retain_audit=False,
            ),
        )

        result = await coordinator.run(cycles_per_coalition=1)

        assert client.restore_calls == [activation.plan.plan_id]
        assert client.monitor_calls == [activation.plan.plan_id]
        assert client.resume_execute_calls == [activation.plan.plan_id]
        assert client.activation_calls == []
        assert result.recoveries[0].status is StrategicRecoveryStatus.COMPLETED
        assert result.recoveries[0].resumed_attempt_id == f"{activation.plan.plan_id}/ATTEMPT:2"

    asyncio.run(scenario())


def test_bilateral_workers_execute_coalitions_concurrently() -> None:
    async def scenario() -> None:
        blue = _decision("blue", "Contested target")
        red = _decision("red", "Contested target")
        recommendation, activations = _recommendation(blue, red)
        client = _Client(recommendation, activations)
        readiness = _Readiness(client)
        started: set[str] = set()
        both_started = asyncio.Event()

        async def probe(coalition: str) -> None:
            started.add(coalition)
            if started == {"blue", "red"}:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1.0)

        client.execute_probe = probe
        coordinator = BilateralConflictCoordinator(
            client,
            lambda: asyncio.sleep(0, result=readiness),
            StrategicCoordinatorConfig(
                blue_cadence_s=1.0,
                red_cadence_s=1.0,
                poll_interval_s=0.01,
                retain_audit=False,
            ),
        )

        result = await coordinator.run(cycles_per_coalition=1)

        assert started == {"blue", "red"}
        assert result.coalition("blue")[0].status is StrategicCycleStatus.COMPLETED
        assert result.coalition("red")[0].status is StrategicCycleStatus.COMPLETED

    asyncio.run(scenario())


def test_mission_bound_run_stops_both_workers_without_following_next_generation() -> None:
    async def scenario() -> None:
        blue = _decision("blue", "Blue target")
        red = _decision("red", "Red target")
        recommendation, activations = _recommendation(blue, red)
        client = _Client(recommendation, activations)
        readiness = _Readiness(client)
        started: set[str] = set()
        both_started = asyncio.Event()

        async def probe(coalition: str) -> None:
            started.add(coalition)
            if started == {"blue", "red"}:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1.0)

        async def advance_generation(cycle) -> None:
            if cycle.status is StrategicCycleStatus.COMPLETED:
                client.state.mission_generation = 1

        client.execute_probe = probe
        coordinator = BilateralConflictCoordinator(
            client,
            lambda: asyncio.sleep(0, result=readiness),
            StrategicCoordinatorConfig(
                blue_cadence_s=1.0,
                red_cadence_s=1.0,
                poll_interval_s=0.01,
                retain_audit=False,
            ),
        )

        result = await asyncio.wait_for(
            coordinator.run_until_mission_end(on_cycle=advance_generation),
            timeout=1.0,
        )

        assert result.requested_cycles_per_coalition is None
        assert started == {"blue", "red"}
        assert result.coalition("blue")[-1].status is StrategicCycleStatus.MISSION_CHANGED
        assert result.coalition("red")[-1].status is StrategicCycleStatus.MISSION_CHANGED
        assert all(cycle.mission_generation == 0 for cycle in result.cycles)

    asyncio.run(scenario())


def test_coordinator_formatters_distinguish_bounded_and_mission_runs() -> None:
    pair = _decision("blue", "Formatting target")
    recommendation, _ = _recommendation(pair)
    cycle = StrategicCoalitionCycle(
        coalition="blue",
        cycle_number=2,
        mission_generation=4,
        started_mission_time=125.0,
        completed_mission_time=130.0,
        status=StrategicCycleStatus.NO_SELECTION,
        recommendation=recommendation,
        reason="all candidates are cooling down",
    )
    result = BilateralConflictRun(
        mission_generation=4,
        requested_cycles_per_coalition=None,
        cycles=(cycle,),
    )

    cycle_text = format_strategic_coalition_cycle(cycle)
    run_text = format_bilateral_conflict_run(result)

    assert "decisions=1/0/0 (selected/deferred/rejected)" in cycle_text
    assert "reason=all candidates are cooling down" in cycle_text
    assert "requested_cycles=until_mission_end" in run_text
    assert "no_selection=1" in run_text
