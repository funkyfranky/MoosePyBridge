from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from moosebridge import (
    AssetRequirement,
    AssetRole,
    BilateralConflictCoordinator,
    BilateralStrategicRecommendation,
    MissionIntent,
    ObjectiveKind,
    OperationalPlan,
    OperationalPlanAssessment,
    OperationalPlanExecution,
    OperationalPlanStatus,
    OwnershipPolicy,
    PlanPhase,
    RelationshipState,
    StrategicAttemptStatus,
    StrategicCoordinatorConfig,
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

    async def append_audit_record(
        self,
        record_type: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.records.append((record_type, payload))
        return payload


class _Client:
    def __init__(
        self,
        recommendation: BilateralStrategicRecommendation,
        activations: dict[str, StrategicDecisionActivation],
    ) -> None:
        self.state = SimpleNamespace(
            mission_generation=0,
            clock=DcsTime(mission_time=100.0),
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
        assert client.server.records[0][1]["status"] == "blocked"
        assert client.server.records[1][1]["status"] == "no_selection"

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
