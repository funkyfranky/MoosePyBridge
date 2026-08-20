from __future__ import annotations

import asyncio
from typing import Any

from moosebridge import Auftrag_PATROLZONE
from moosebridge.mission_execution_service import (
    MissionExecutionService,
    PlanMissionExecution,
    PlanMissionStatus,
)
from moosebridge.state import MooseBridgeState


class _MissionServer:
    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.events = list(events or ())

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        del event_name, filters, timeout, after_id
        return self.events.pop(0)


class _MissionClient:
    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        *,
        auftrag_snapshots: list[dict[str, Any]] | None = None,
    ) -> None:
        self.server = _MissionServer(events)
        self.state = MooseBridgeState(connected=True)
        self.submissions: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self.auftrag_snapshots = list(auftrag_snapshots or ())
        self.snapshot_calls = 0

    async def add_auftrag(
        self,
        command: Any,
        *,
        commander: str,
        allowed_legions: tuple[str, ...],
        allowed_cohorts: tuple[str, ...],
    ) -> dict[str, Any]:
        self.submissions.append(
            {
                "command": command,
                "commander": commander,
                "allowed_legions": allowed_legions,
                "allowed_cohorts": allowed_cohorts,
            }
        )
        return {
            "id": "ack-7",
            "correlation_id": "cmd-7",
            "sequence": 7,
            "result": {
                "action": "auftrag.create_patrolzone",
                "auftrag_id": "AUFTRAG:7",
                "auftrag_type": "Patrol Zone",
                "commander_id": commander,
            },
        }

    def mission_id(self, command: Any) -> str:
        assert self.submissions[-1]["command"] is command
        return "AUFTRAG:7"

    def _on_bridge_message(self, message: dict[str, Any]) -> None:
        del message

    async def cancel_mission(self, mission_id: str) -> dict[str, Any]:
        self.cancelled.append(mission_id)
        return {"ok": True}

    async def snapshot_auftraege(self) -> dict[str, Any]:
        self.snapshot_calls += 1
        self.state.apply_message(
            {
                "type": "snapshot",
                "kind": "auftraege",
                "payload": {"auftraege": self.auftrag_snapshots},
            }
        )
        return {
            "ok": True,
            "result": {"kind": "auftraege", "count": len(self.auftrag_snapshots)},
        }


def _mission() -> PlanMissionExecution:
    return PlanMissionExecution(
        phase_id="consolidate",
        intent_id="secure-zone",
        requirement_id="REQ:Ground security",
        mission_type="PATROLZONE",
        required=True,
        command=Auftrag_PATROLZONE(zone="ZONE:Town"),
    )


def test_service_submits_and_evaluates_one_auftrag() -> None:
    async def scenario() -> None:
        client = _MissionClient(
            [
                {
                    "type": "event",
                    "id": "event-1",
                    "event": "auftrag.status",
                    "payload": {
                        "auftrag_id": "AUFTRAG:7",
                        "auftrag_type": "PATROLZONE",
                        "status": "executing",
                        "fsm_event": "Executing",
                        "from": "started",
                        "to": "executing",
                    },
                },
                {
                    "type": "event",
                    "id": "event-2",
                    "event": "auftrag.evaluated",
                    "payload": {
                        "auftrag_id": "AUFTRAG:7",
                        "auftrag_type": "PATROLZONE",
                        "status": "done",
                        "summary": {
                            "evaluated": True,
                            "success": True,
                            "n_targets_initial": 1,
                            "n_targets_final": 0,
                        },
                    },
                },
            ]
        )
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        mission = _mission()
        observed: list[str] = []

        await service.submit(
            mission,
            commander_id="COMMANDER:Blue",
            allowed_legion_ids=("LEGION:Brigade",),
            allowed_cohort_ids=("COHORT:Infantry",),
            on_event=lambda _mission, event: observed.append(event.event),
        )
        succeeded = await service.wait_for_mission(
            mission,
            timeout_s=1,
            on_event=lambda _mission, event: observed.append(event.event),
        )

        assert succeeded is True
        assert mission.status is PlanMissionStatus.SUCCEEDED
        assert mission.auftrag_id == "AUFTRAG:7"
        assert mission.command_ack is not None
        assert mission.command_ack.ack_id == "ack-7"
        assert mission.outcome is not None
        assert mission.outcome.success is True
        assert client.submissions[0]["commander"] == "COMMANDER:Blue"
        assert client.submissions[0]["allowed_cohorts"] == ("COHORT:Infantry",)
        assert observed == ["mission.submitted", "mission.status", "mission.succeeded"]

    asyncio.run(scenario())


def test_service_cancels_only_active_missions() -> None:
    async def scenario() -> None:
        client = _MissionClient()
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        active = _mission()
        active.auftrag_id = "AUFTRAG:7"
        active.status = PlanMissionStatus.RUNNING
        completed = _mission()
        completed.auftrag_id = "AUFTRAG:8"
        completed.status = PlanMissionStatus.SUCCEEDED
        observed: list[str] = []

        await service.cancel_active(
            (active, completed),
            reason="strategic goal achieved",
            on_event=lambda _mission, event: observed.append(event.event),
        )

        assert client.cancelled == ["AUFTRAG:7"]
        assert active.status is PlanMissionStatus.CANCELLED
        assert active.error == "strategic goal achieved"
        assert completed.status is PlanMissionStatus.SUCCEEDED
        assert observed == ["mission.cancelled"]

    asyncio.run(scenario())


def test_service_reports_missing_command_as_submission_failure() -> None:
    async def scenario() -> None:
        client = _MissionClient()
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        mission = _mission()
        mission.command = None
        observed: list[str] = []

        try:
            await service.submit(
                mission,
                commander_id="COMMANDER:Blue",
                on_event=lambda _mission, event: observed.append(event.event),
            )
        except ValueError as exc:
            assert str(exc) == "plan mission submission requires an AUFTRAG command"
        else:
            raise AssertionError("missing AUFTRAG command was accepted")

        assert mission.status is PlanMissionStatus.FAILED
        assert mission.error == "plan mission submission requires an AUFTRAG command"
        assert observed == ["mission.failed"]

    asyncio.run(scenario())


def test_service_reconciles_running_auftrag_from_current_snapshot() -> None:
    async def scenario() -> None:
        client = _MissionClient(
            auftrag_snapshots=[
                {
                    "object_id": "AUFTRAG:7",
                    "type": "PATROLZONE",
                    "status": "Executing",
                }
            ]
        )
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        mission = _mission()
        mission.auftrag_id = "AUFTRAG:7"
        mission.status = PlanMissionStatus.SUBMITTED
        observed: list[str] = []

        reconciled = await service.reconcile(
            (mission,),
            on_event=lambda _mission, event: observed.append(event.event),
        )

        assert client.snapshot_calls == 1
        assert mission.status is PlanMissionStatus.RUNNING
        assert len(reconciled) == 1
        assert reconciled[0].snapshot_found is True
        assert reconciled[0].state_recognized is True
        assert reconciled[0].message is None
        assert observed == ["mission.reconciled"]

    asyncio.run(scenario())


def test_service_reconciles_evaluated_auftrag_failure() -> None:
    async def scenario() -> None:
        client = _MissionClient(
            auftrag_snapshots=[
                {
                    "object_id": "AUFTRAG:7",
                    "type": "PATROLZONE",
                    "status": "Done",
                    "summary": {
                        "evaluated": True,
                        "success": False,
                        "n_targets_initial": 1,
                        "n_targets_final": 1,
                    },
                }
            ]
        )
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        mission = _mission()
        mission.auftrag_id = "AUFTRAG:7"
        mission.status = PlanMissionStatus.RUNNING
        observed: list[str] = []

        reconciled = await service.reconcile(
            (mission,),
            on_event=lambda _mission, event: observed.append(event.event),
        )

        assert mission.status is PlanMissionStatus.FAILED
        assert mission.error == "AUFTRAG evaluated without success"
        assert mission.outcome is not None
        assert mission.outcome.success is False
        assert reconciled[0].state_recognized is True
        assert reconciled[0].message == "AUFTRAG evaluated without success"
        assert observed == ["mission.reconciled"]

    asyncio.run(scenario())


def test_service_keeps_unknown_auftrag_state_explicitly_unrecognized() -> None:
    async def scenario() -> None:
        client = _MissionClient(
            auftrag_snapshots=[
                {
                    "object_id": "AUFTRAG:7",
                    "type": "PATROLZONE",
                    "status": "Unexpected",
                }
            ]
        )
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        mission = _mission()
        mission.auftrag_id = "AUFTRAG:7"
        mission.status = PlanMissionStatus.RUNNING
        observed: list[str] = []

        reconciled = await service.reconcile(
            (mission,),
            on_event=lambda _mission, event: observed.append(event.event),
        )

        assert mission.status is PlanMissionStatus.RUNNING
        assert reconciled[0].snapshot_found is True
        assert reconciled[0].state_recognized is False
        assert reconciled[0].message == "AUFTRAG snapshot has no recognized lifecycle status"
        assert observed == []

    asyncio.run(scenario())
