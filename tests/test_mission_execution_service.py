from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from moosebridge import Auftrag_PATROLZONE
from moosebridge.mission_execution_service import (
    AuftragAssignment,
    MissionExecutionService,
    PlanMissionExecution,
    PlanMissionStatus,
)
from moosebridge.outcomes import AuftragOutcome
from moosebridge.recon import ReconRequirement, ReconSpatialCoverage, ReconTrackingSession
from moosebridge.state import MooseBridgeState


class _MissionServer:
    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.events = list(events or ())
        self.history_events: list[dict[str, Any]] = []

    async def event_cursor(self) -> str:
        return "event-before"

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        del event_name, filters, timeout, after_id
        return self.events.pop(0)

    async def query_events(
        self,
        event_name: str = "*",
        filters: dict[str, Any] | None = None,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        del event_name, filters, after_id
        return {"events": list(self.history_events), "history_complete": True}


class _MissionClient:
    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        *,
        auftrag_snapshots: list[dict[str, Any]] | None = None,
        cancel_failures: tuple[str, ...] = (),
    ) -> None:
        self.server = _MissionServer(events)
        self.state = MooseBridgeState(connected=True)
        self.submissions: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self.cancel_timeouts: list[float] = []
        self.cancel_failures = set(cancel_failures)
        self.auftrag_snapshots = list(auftrag_snapshots or ())
        self.snapshot_calls = 0
        self.opsgroup_snapshot_calls = 0
        self.opsgroup_names: dict[str, str] = {}
        self.assessed_recon: tuple[ReconRequirement, Any] | None = None

    async def add_auftrag(
        self,
        command: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.submissions.append(
            {
                "command": command,
                **kwargs,
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
                "commander_id": kwargs.get("commander"),
            },
        }

    def mission_id(self, command: Any) -> str:
        assert self.submissions[-1]["command"] is command
        return "AUFTRAG:7"

    def _on_bridge_message(self, message: dict[str, Any]) -> None:
        del message

    async def cancel_mission(self, mission_id: str, timeout: float = 10.0) -> dict[str, Any]:
        if mission_id in self.cancel_failures:
            raise RuntimeError(f"cancel failed for {mission_id}")
        self.cancelled.append(mission_id)
        self.cancel_timeouts.append(timeout)
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

    async def snapshot_opsgroups(self) -> dict[str, Any]:
        self.opsgroup_snapshot_calls += 1
        return {"ok": True, "result": {"kind": "opsgroups", "count": len(self.opsgroup_names)}}

    def auftrag(self, object_id: str) -> Any | None:
        snapshot = next(
            (item for item in self.auftrag_snapshots if item.get("object_id") == object_id),
            None,
        )
        if snapshot is None:
            return None
        return SimpleNamespace(assigned_group_ids=tuple(snapshot.get("assigned_group_ids") or ()))

    def opsgroup(self, object_id: str) -> Any | None:
        name = self.opsgroup_names.get(object_id)
        return SimpleNamespace(group_name=name) if name is not None else None

    async def assess_recon_tracking(
        self,
        requirement: ReconRequirement,
        session: Any,
    ) -> ReconSpatialCoverage:
        self.assessed_recon = (requirement, session)
        return ReconSpatialCoverage(
            available=False,
            area_object_id=requirement.area_object_id,
            area_m2=None,
            searched_area_m2=None,
            area_coverage_ratio=None,
            component_coverage_ratio=None,
            covered_component_ids=(),
            uncovered_component_ids=(),
            tracked_group_ids=tuple(session.assigned_group_ids),
            unknown_sensor_group_ids=(),
            sample_count=0,
            sufficient=None,
        )


def _mission() -> PlanMissionExecution:
    return PlanMissionExecution(
        phase_id="consolidate",
        intent_id="secure-zone",
        requirement_id="REQ:Ground security",
        mission_type="PATROLZONE",
        required=True,
        command=Auftrag_PATROLZONE(zone="ZONE:Town"),
    )


def test_auftrag_assignment_normalizes_recruitment_constraints() -> None:
    assignment = AuftragAssignment.commander(
        "COMMANDER:Blue",
        cohort_id="COHORT:MQ-9",
        allowed_legion_ids=("LEGION:Wing", "LEGION:Wing"),
        allowed_cohort_ids=("COHORT:MQ-9", "COHORT:F-16", "COHORT:F-16"),
        selected_payload_uid=17,
    )

    assert assignment.allowed_legion_ids == ("LEGION:Wing",)
    assert assignment.allowed_cohort_ids == ("COHORT:F-16",)
    assert assignment.cohort_scope_ids == ("COHORT:MQ-9", "COHORT:F-16")
    assert assignment.add_auftrag_kwargs() == {
        "commander": "COMMANDER:Blue",
        "cohort": "COHORT:MQ-9",
        "allowed_legions": ("LEGION:Wing",),
        "allowed_cohorts": ("COHORT:F-16",),
        "selected_payload_uid": 17,
    }


@pytest.mark.parametrize(
    ("assignment", "target_key", "target_id"),
    (
        (AuftragAssignment.commander("COMMANDER:Blue"), "commander", "COMMANDER:Blue"),
        (AuftragAssignment.legion("LEGION:Wing"), "legion", "LEGION:Wing"),
        (AuftragAssignment.opsgroup("OPSGROUP:Flight"), "opsgroup", "OPSGROUP:Flight"),
        (AuftragAssignment.coalition("blue"), "coalition", "blue"),
    ),
)
def test_auftrag_assignment_supports_every_moose_tasking_target(
    assignment: AuftragAssignment,
    target_key: str,
    target_id: str,
) -> None:
    assert assignment.add_auftrag_kwargs()[target_key] == target_id


def test_auftrag_assignment_rejects_incompatible_constraints() -> None:
    with pytest.raises(ValueError, match="COHORT constraints"):
        AuftragAssignment.opsgroup("OPSGROUP:Flight", cohort_id="COHORT:MQ-9")
    with pytest.raises(ValueError, match="allowed LEGIONs"):
        AuftragAssignment.legion(
            "LEGION:Wing",
            allowed_legion_ids=("LEGION:Other",),
        )
    with pytest.raises(ValueError, match="COMMANDER:"):
        AuftragAssignment.commander("Blue Commander")


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
            assignment=AuftragAssignment.commander(
                "COMMANDER:Blue",
                allowed_legion_ids=("LEGION:Brigade",),
                allowed_cohort_ids=("COHORT:Infantry",),
            ),
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
        assert mission.raw_command_ack["id"] == "ack-7"
        assert mission.event_cursor == "event-before"
        assert mission.outcome is not None
        assert mission.outcome.success is True
        assert client.submissions[0]["commander"] == "COMMANDER:Blue"
        assert client.submissions[0]["allowed_cohorts"] == ("COHORT:Infantry",)
        assert client.submissions[0]["timeout"] == 10.0
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


def test_service_discovers_and_cancels_only_live_snapshot_auftraege() -> None:
    async def scenario() -> None:
        client = _MissionClient(
            auftrag_snapshots=[
                {"object_id": "AUFTRAG:7", "status": "Started"},
                {"object_id": "AUFTRAG:8", "status": "Done"},
            ]
        )
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        live = _mission()
        live.auftrag_id = "AUFTRAG:7"
        live.status = PlanMissionStatus.RUNNING
        finished = _mission()
        finished.auftrag_id = "AUFTRAG:8"
        finished.status = PlanMissionStatus.RUNNING
        observed: list[str] = []

        results = await service.cancel_live(
            (live, finished),
            reason="operator abort",
            timeout=3.5,
            on_event=lambda _mission, event: observed.append(event.event),
        )

        assert client.snapshot_calls == 1
        assert client.cancelled == ["AUFTRAG:7"]
        assert client.cancel_timeouts == [3.5]
        assert live.status is PlanMissionStatus.CANCELLED
        assert finished.status is PlanMissionStatus.RUNNING
        assert len(results) == 1
        assert results[0].auftrag_id == "AUFTRAG:7"
        assert results[0].cancelled is True
        assert results[0].message == "operator abort"
        assert observed == ["mission.cancelled"]

    asyncio.run(scenario())


def test_service_returns_failed_live_auftrag_cancellation() -> None:
    async def scenario() -> None:
        client = _MissionClient(
            auftrag_snapshots=[{"object_id": "AUFTRAG:7", "status": "Executing"}],
            cancel_failures=("AUFTRAG:7",),
        )
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        mission = _mission()
        mission.auftrag_id = "AUFTRAG:7"
        mission.status = PlanMissionStatus.RUNNING
        observed: list[str] = []

        results = await service.cancel_live(
            (mission,),
            reason="operator abort",
            on_event=lambda _mission, event: observed.append(event.event),
        )

        assert mission.status is PlanMissionStatus.RUNNING
        assert mission.error == "cancel failed for AUFTRAG:7"
        assert len(results) == 1
        assert results[0].cancelled is False
        assert results[0].message == "cancel failed for AUFTRAG:7"
        assert observed == ["mission.cancel_failed"]

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
                assignment=AuftragAssignment.commander("COMMANDER:Blue"),
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


def test_service_builds_recon_assessment_for_one_completed_auftrag() -> None:
    async def scenario() -> None:
        client = _MissionClient(
            auftrag_snapshots=[
                {
                    "object_id": "AUFTRAG:7",
                    "status": "Done",
                    "assigned_group_ids": ["OPSGROUP:MQ-9 Flight"],
                }
            ]
        )
        client.opsgroup_names["OPSGROUP:MQ-9 Flight"] = "MQ-9 Flight-1"
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        mission = _mission()
        mission.mission_type = "RECON"
        mission.auftrag_id = "AUFTRAG:7"
        mission.status = PlanMissionStatus.SUCCEEDED
        mission.recon_intel_id = "INTEL:Blue"
        mission.outcome = AuftragOutcome.from_snapshot(
            {
                "object_id": "AUFTRAG:7",
                "type": "RECON",
                "status": "Done",
                "summary": {
                    "evaluated": True,
                    "success": True,
                    "n_targets_initial": 1,
                    "n_targets_final": 0,
                },
            }
        )
        requirement = ReconRequirement.manual("ZONE:Recon", "GROUP:Missing target")
        observed: list[tuple[str, str | None, str | None]] = []

        outcome = await service.assess_recon(
            mission,
            requirement,
            on_event=lambda _mission, event: observed.append(
                (event.event, event.status, event.message)
            ),
        )

        assert client.snapshot_calls == 1
        assert client.opsgroup_snapshot_calls == 1
        assert client.assessed_recon is not None
        assert mission.recon_assigned_group_ids == ("GROUP:MQ-9 Flight-1",)
        assert outcome is mission.recon_outcome
        assert outcome.assigned_opsgroup_ids == ("OPSGROUP:MQ-9 Flight",)
        assert outcome.assigned_group_ids == ("GROUP:MQ-9 Flight-1",)
        assert outcome.requirement_satisfied is False
        assert observed == [
            (
                "recon.assessed",
                "incomplete",
                "contacts=0 unknown=1 lost=0",
            )
        ]

    asyncio.run(scenario())


def test_service_reuses_direct_recon_tracking_and_ack() -> None:
    async def scenario() -> None:
        client = _MissionClient(
            auftrag_snapshots=[
                {
                    "object_id": "AUFTRAG:7",
                    "status": "Done",
                    "assigned_group_ids": ["OPSGROUP:Snapshot Flight"],
                }
            ]
        )
        service = MissionExecutionService(client)  # type: ignore[arg-type]
        mission = _mission()
        mission.mission_type = "RECON"
        mission.auftrag_id = "AUFTRAG:7"
        mission.status = PlanMissionStatus.SUCCEEDED
        mission.recon_intel_id = "INTEL:Blue"
        mission.outcome = AuftragOutcome.from_snapshot(
            {
                "object_id": "AUFTRAG:7",
                "type": "RECON",
                "status": "Done",
                "summary": {"evaluated": True, "success": True},
            }
        )
        tracking = ReconTrackingSession(
            "AUFTRAG:7",
            ("OPSGROUP:Direct Flight",),
            ("GROUP:Direct Flight-1",),
            {},
        )

        outcome = await service.assess_recon(
            mission,
            None,
            tracking=tracking,
            relevant_target_ids=("GROUP:Ground-1",),
            command_ack={"id": "ack-7", "result": {"auftrag_id": "AUFTRAG:7"}},
            assess_spatial_coverage=False,
        )

        assert client.assessed_recon is None
        assert mission.recon_assigned_group_ids == ("GROUP:Direct Flight-1",)
        assert outcome.assigned_opsgroup_ids == ("OPSGROUP:Direct Flight",)
        assert outcome.relevant_target_ids == ("GROUP:Ground-1",)
        assert outcome.command_ack["id"] == "ack-7"
        assert outcome.spatial_coverage is None

    asyncio.run(scenario())
