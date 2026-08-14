from __future__ import annotations

import asyncio

from moosebridge import (
    ConflictControllerConfig,
    MooseBridgeClient,
    MooseBridgeServer,
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    RelationshipState,
    RuleBasedConflictController,
    StrategicGoalAction,
    StrategicObjective,
    TacticalPicture,
)


def _objective(
    objective_id: str,
    kind: ObjectiveKind,
    *,
    owner: str | None,
    contested: bool = False,
    components: tuple[ObjectiveComponent, ...] = (),
) -> StrategicObjective:
    return StrategicObjective(
        objective_id=objective_id,
        name=objective_id.removeprefix("OBJECTIVE:"),
        kind=kind,
        control_object_id=(
            f"OPSZONE:{objective_id.removeprefix('OBJECTIVE:')}"
            if kind is ObjectiveKind.OPSZONE
            else None
        ),
        ownership_policy=(
            OwnershipPolicy.MOOSE_MANAGED
            if kind is ObjectiveKind.OPSZONE
            else OwnershipPolicy.FIXED
        ),
        owner=owner,
        contested=contested,
        components=components,
        health=1.0 if components else None,
    )


def test_controller_selects_only_supported_minimal_actions() -> None:
    client = MooseBridgeClient(MooseBridgeServer())
    controller = RuleBasedConflictController(client)

    capture = _objective("OBJECTIVE:Town", ObjectiveKind.OPSZONE, owner="red")
    defend = _objective("OBJECTIVE:Camp", ObjectiveKind.OPSZONE, owner="blue", contested=True)
    quiet = _objective("OBJECTIVE:Rear", ObjectiveKind.OPSZONE, owner="blue")
    destroy = _objective(
        "OBJECTIVE:Depot",
        ObjectiveKind.DEPOT,
        owner="red",
        components=(ObjectiveComponent("STATIC:Depot"),),
    )

    assert controller._desired_action(capture) is StrategicGoalAction.CAPTURE
    assert controller._desired_action(defend) is StrategicGoalAction.DEFEND
    assert controller._desired_action(quiet) is None
    assert controller._desired_action(destroy) is StrategicGoalAction.DESTROY


def test_controller_declares_and_persists_war_when_required() -> None:
    async def scenario() -> None:
        server = MooseBridgeServer()
        server.state.mission_generation = 3
        client = MooseBridgeClient(server)
        controller = RuleBasedConflictController(client)

        assert await controller.ensure_war() is True
        assert client.relationship.state is RelationshipState.WAR

        restored = MooseBridgeClient(server)
        assert await restored.refresh_diplomacy_state() is True
        assert restored.relationship.state is RelationshipState.WAR
        assert restored.relationship.incidents[-1].incident_type.value == "war_declared"

        assert await controller.ensure_war() is False
        assert len(client.relationship.incidents) == 1

    asyncio.run(scenario())


def test_controller_can_require_preexisting_war() -> None:
    async def scenario() -> None:
        controller = RuleBasedConflictController(
            MooseBridgeClient(MooseBridgeServer()),
            ConflictControllerConfig(declare_war_if_needed=False),
        )
        try:
            await controller.ensure_war()
        except ValueError as exc:
            assert "requires relationship state war" in str(exc)
        else:
            raise AssertionError("controller should reject a non-war relationship")

    asyncio.run(scenario())


def test_first_snapshot_preserves_configured_objectives_and_declares_war_after_reset() -> None:
    async def scenario() -> None:
        client = MooseBridgeClient(MooseBridgeServer())
        objective = _objective("OBJECTIVE:Rear", ObjectiveKind.OPSZONE, owner="blue")
        client.add_strategic_objective(objective, sync=False)

        async def snapshot_statics() -> dict[str, object]:
            client.reset_mission(reset_state=False)
            return {"ok": True}

        async def refresh_tactical_picture(coalition: str, intel_id: str) -> TacticalPicture:
            return TacticalPicture(coalition=coalition, intel_id=intel_id)

        legion_refreshes = 0

        async def refresh_legion_state() -> object:
            nonlocal legion_refreshes
            legion_refreshes += 1
            return client.state

        client.snapshot_statics = snapshot_statics  # type: ignore[method-assign]
        client.refresh_tactical_picture = refresh_tactical_picture  # type: ignore[method-assign]
        client.refresh_legion_state = refresh_legion_state  # type: ignore[method-assign]
        controller = RuleBasedConflictController(client)

        cycle = await controller.run_cycle(execute=False)

        assert client.strategic_objective(objective.objective_id) is objective
        assert client.relationship.state is RelationshipState.WAR
        assert client.relationship.incidents[-1].incident_type.value == "war_declared"
        assert legion_refreshes == 1
        assert cycle.portfolio.selected == ()

    asyncio.run(scenario())


def test_preview_cycle_preserves_current_relationship() -> None:
    async def scenario() -> None:
        client = MooseBridgeClient(MooseBridgeServer())
        client.add_strategic_objective(
            _objective("OBJECTIVE:Enemy Zone", ObjectiveKind.OPSZONE, owner="red"),
            sync=False,
        )

        async def snapshot_statics() -> dict[str, object]:
            return {"ok": True}

        async def refresh_tactical_picture(coalition: str, intel_id: str) -> TacticalPicture:
            return TacticalPicture(coalition=coalition, intel_id=intel_id)

        async def refresh_legion_state() -> object:
            return client.state

        client.snapshot_statics = snapshot_statics  # type: ignore[method-assign]
        client.refresh_tactical_picture = refresh_tactical_picture  # type: ignore[method-assign]
        client.refresh_legion_state = refresh_legion_state  # type: ignore[method-assign]

        cycle = await RuleBasedConflictController(client).run_cycle(
            execute=False,
            manage_relationship=False,
        )

        assert client.relationship.state is RelationshipState.PEACE
        assert client.relationship.incidents == []
        assert cycle.generated_goal_ids == ()
        assert cycle.goal_generation.goals == ()
        assert "peace" in cycle.goal_generation.rejected[0].reason

    asyncio.run(scenario())
