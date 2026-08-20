"""Lifecycle execution for one concrete MOOSE AUFTRAG."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
import inspect
from typing import TYPE_CHECKING, Any

from .auftraege import AuftragCommand, AuftragEvent
from .outcomes import AuftragOutcome
from .recon import ReconOutcome, ReconTrackSample, ReconTrackingSession
from .server import DcsMissionEndedError

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


RECON_POSITION_SAMPLE_INTERVAL_S = 10.0


class PlanMissionStatus(str, Enum):
    """Execution state of one concrete AUFTRAG created from a requirement."""

    PENDING = "pending"
    SKIPPED = "skipped"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True, frozen=True)
class CommandAckReference:
    """Compact reference from a submitted plan mission to its bridge ACK."""

    ack_id: str | None = None
    correlation_id: str | None = None
    sequence: int | None = None
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlanMissionExecution:
    """Runtime record connecting one requirement to one MOOSE AUFTRAG."""

    phase_id: str
    intent_id: str
    requirement_id: str
    mission_type: str
    required: bool
    command: AuftragCommand | None = field(default=None, repr=False)
    persistent: bool = False
    established_on: str | None = None
    command_snapshot: dict[str, Any] = field(default_factory=dict)
    weapon_range_ack: CommandAckReference | None = None
    command_ack: CommandAckReference | None = None
    status: PlanMissionStatus = PlanMissionStatus.PENDING
    auftrag_id: str | None = None
    outcome: AuftragOutcome | None = None
    recon_outcome: ReconOutcome | None = None
    event_cursor: str | None = field(default=None, repr=False)
    recon_intel_id: str | None = field(default=None, repr=False)
    baseline_intel_contact_ids: tuple[str, ...] = field(default=(), repr=False)
    recon_assigned_group_ids: tuple[str, ...] = field(default=(), repr=False)
    recon_tracks: dict[str, list[ReconTrackSample]] = field(default_factory=dict, repr=False)
    error: str | None = None


@dataclass(slots=True, frozen=True)
class PlanMissionReconciliation:
    """Observed MOOSE state for one previously submitted AUFTRAG."""

    auftrag_id: str | None
    phase_id: str
    requirement_id: str
    status: PlanMissionStatus
    snapshot_found: bool
    message: str | None = None
    state_recognized: bool = True


@dataclass(slots=True, frozen=True)
class PlanMissionAbort:
    """Result of cancelling one live MOOSE AUFTRAG."""

    auftrag_id: str
    phase_id: str
    requirement_id: str
    cancelled: bool
    message: str | None = None


@dataclass(slots=True, frozen=True)
class MissionLifecycleEvent:
    """Transport-neutral lifecycle event emitted for one plan mission."""

    event: str
    status: str | None = None
    message: str | None = None


MissionLifecycleCallback = Callable[
    [PlanMissionExecution, MissionLifecycleEvent],
    Any | Awaitable[Any],
]


class MissionExecutionService:
    """Submit, observe, evaluate, and cancel individual MOOSE AUFTRAGs."""

    def __init__(self, client: MooseBridgeClient) -> None:
        self.client = client

    async def submit(
        self,
        mission: PlanMissionExecution,
        *,
        commander_id: str,
        allowed_legion_ids: Iterable[str] = (),
        allowed_cohort_ids: Iterable[str] = (),
        fire_support: Mapping[str, Any] | None = None,
        structured_recon: bool = False,
        recon_intel_id: str | None = None,
        on_event: MissionLifecycleCallback | None = None,
    ) -> PlanMissionExecution:
        """Prepare and submit one concrete AUFTRAG to MOOSE."""

        legion_ids = tuple(allowed_legion_ids)
        cohort_ids = tuple(allowed_cohort_ids)
        try:
            command = mission.command
            if command is None:
                raise ValueError("plan mission submission requires an AUFTRAG command")
            if command.mission_type == "RECON" and structured_recon:
                mission.recon_intel_id = str(recon_intel_id or "").strip() or None
                if mission.recon_intel_id is None:
                    raise ValueError("structured RECON phase requires metadata.intel_id")
                mission.event_cursor = await self.client.server.event_cursor()
                await self.client.refresh_intel_state()
                mission.baseline_intel_contact_ids = tuple(
                    contact.object_id
                    for contact in self.client.contacts_of_intel(mission.recon_intel_id)
                )

            range_ack = await self.synchronize_arty_weapon_range(
                command,
                fire_support=fire_support,
                allowed_cohort_ids=cohort_ids,
            )
            if range_ack is not None:
                mission.weapon_range_ack = command_ack_reference(range_ack)
                result = range_ack.get("result") if isinstance(range_ack.get("result"), dict) else {}
                await self._emit(
                    mission,
                    MissionLifecycleEvent(
                        "mission.weapon_range_synchronized",
                        status="synchronized",
                        message=(
                            f"{result.get('cohort_id') or '-'} "
                            f"weapon_type={result.get('weapon_type')} "
                            f"range={float(result.get('minimum_m') or 0.0) / 1_000:.3f}-"
                            f"{float(result.get('maximum_m') or 0.0) / 1_000:.3f}km"
                        ),
                    ),
                    on_event,
                )

            ack = await self.client.add_auftrag(
                command,
                commander=commander_id,
                allowed_legions=legion_ids,
                allowed_cohorts=cohort_ids,
            )
            mission.command_ack = command_ack_reference(ack)
            mission.auftrag_id = self.client.mission_id(command)
            mission.status = PlanMissionStatus.SUBMITTED
            await self._emit(mission, MissionLifecycleEvent("mission.submitted"), on_event)
            return mission
        except Exception as exc:
            mission.status = PlanMissionStatus.FAILED
            mission.error = str(exc)
            await self._emit(mission, MissionLifecycleEvent("mission.failed"), on_event)
            raise

    async def synchronize_arty_weapon_range(
        self,
        command: AuftragCommand,
        *,
        fire_support: Mapping[str, Any] | None,
        allowed_cohort_ids: Iterable[str] = (),
    ) -> dict[str, Any] | None:
        """Apply the resolver's exact weapon envelope before MOOSE recruits assets."""

        if command.mission_type != "ARTY" or not fire_support or not fire_support.get("range_sync_required"):
            return None

        cohort_id = str(fire_support.get("cohort_id") or "").strip()
        if not cohort_id:
            raise ValueError("ARTY weapon range synchronization requires fire_support.cohort_id")
        cohort_ids = tuple(allowed_cohort_ids)
        if cohort_ids and cohort_id not in cohort_ids:
            raise ValueError(f"ARTY weapon range COHORT is not allowed by the requirement: {cohort_id}")

        weapon_type = int(fire_support.get("weapon_flag_value"))
        minimum_m = float(fire_support.get("minimum_m"))
        maximum_m = float(fire_support.get("maximum_m"))
        cohort = self.client.cohort(cohort_id)
        configured = cohort.weapon_range_for_weapon_type(weapon_type) if cohort is not None else None
        if configured is not None:
            configured_minimum, configured_maximum = configured
            if abs(configured_minimum - minimum_m) <= 1.0 and abs(configured_maximum - maximum_m) <= 1.0:
                return None
        return await self.client.set_cohort_weapon_range(
            cohort_id,
            weapon_type,
            minimum_m,
            maximum_m,
        )

    async def reconcile(
        self,
        missions: Iterable[PlanMissionExecution],
        *,
        on_event: MissionLifecycleCallback | None = None,
    ) -> tuple[PlanMissionReconciliation, ...]:
        """Refresh MOOSE AUFTRAG state and reconcile previously submitted missions."""

        await self.client.snapshot_auftraege()
        observations: list[PlanMissionReconciliation] = []
        for mission in missions:
            snapshot = self.client.state.auftraege.get(mission.auftrag_id or "")
            observations.append(
                await self.reconcile_snapshot(
                    mission,
                    snapshot,
                    on_event=on_event,
                )
            )
        return tuple(observations)

    async def reconcile_snapshot(
        self,
        mission: PlanMissionExecution,
        snapshot: dict[str, Any] | None,
        *,
        on_event: MissionLifecycleCallback | None = None,
    ) -> PlanMissionReconciliation:
        """Interpret one current MOOSE snapshot without making plan-level decisions."""

        previous = mission.status
        message: str | None = None
        state_recognized = True
        if mission.status in {
            PlanMissionStatus.SUCCEEDED,
            PlanMissionStatus.FAILED,
            PlanMissionStatus.CANCELLED,
        }:
            pass
        elif not mission.auftrag_id:
            message = "required mission has no AUFTRAG id"
            state_recognized = False
        elif snapshot is None:
            message = "AUFTRAG is absent from the current MOOSE snapshot"
            state_recognized = False
        elif isinstance(snapshot.get("summary"), dict):
            mission.outcome = AuftragOutcome.from_snapshot(snapshot)
            mission.status = (
                PlanMissionStatus.SUCCEEDED
                if mission.outcome.success is True
                else PlanMissionStatus.FAILED
            )
            mission.error = (
                None
                if mission.status is PlanMissionStatus.SUCCEEDED
                else "AUFTRAG evaluated without success"
            )
        else:
            status = str(snapshot.get("status") or "").strip().lower()
            if status in {"cancel", "cancelled", "canceled"}:
                mission.status = PlanMissionStatus.CANCELLED
                mission.error = "AUFTRAG was cancelled"
            elif status in {"failed", "failure"}:
                mission.status = PlanMissionStatus.FAILED
                mission.error = "AUFTRAG snapshot reports failure"
            elif status in {
                "planned",
                "queued",
                "requested",
                "scheduled",
                "started",
                "executing",
                "done",
            }:
                mission.status = PlanMissionStatus.RUNNING
            else:
                message = "AUFTRAG snapshot has no recognized lifecycle status"
                state_recognized = False

        if mission.status is not previous:
            await self._emit(
                mission,
                MissionLifecycleEvent("mission.reconciled", message=message),
                on_event,
            )
        return PlanMissionReconciliation(
            mission.auftrag_id,
            mission.phase_id,
            mission.requirement_id,
            mission.status,
            snapshot is not None,
            message or mission.error,
            state_recognized,
        )

    async def wait_for_required(
        self,
        missions: Iterable[PlanMissionExecution],
        *,
        timeout_s: float,
        on_event: MissionLifecycleCallback | None = None,
        stop_on_failure: bool = True,
    ) -> PlanMissionExecution | None:
        """Wait concurrently for required AUFTRAGs and return the first failure."""

        failed: PlanMissionExecution | None = None
        tasks = {
            asyncio.create_task(self.wait_for_mission(mission, timeout_s=timeout_s, on_event=on_event)): mission
            for mission in missions
        }
        try:
            while tasks:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    mission = tasks.pop(task)
                    try:
                        succeeded = task.result()
                    except Exception as exc:
                        mission.status = PlanMissionStatus.FAILED
                        mission.error = str(exc) or f"event wait failed for {mission.auftrag_id}"
                        await self._emit(mission, MissionLifecycleEvent("mission.failed"), on_event)
                        succeeded = False
                    if not succeeded:
                        if stop_on_failure:
                            return mission
                        failed = mission
            return failed
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def wait_for_mission(
        self,
        mission: PlanMissionExecution,
        *,
        timeout_s: float,
        on_event: MissionLifecycleCallback | None = None,
    ) -> bool:
        """Consume AUFTRAG events until one mission is evaluated or established."""

        if mission.auftrag_id is None:
            raise ValueError("cannot monitor a plan mission without an AUFTRAG id")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        after_id: str | None = mission.event_cursor
        seen_status_keys: set[tuple[str | None, str | None, str | None, str | None]] = set()
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                mission.status = PlanMissionStatus.FAILED
                mission.error = f"timed out waiting for {mission.auftrag_id}"
                await self._emit(mission, MissionLifecycleEvent("mission.failed"), on_event)
                return False
            wait_timeout = min(remaining, RECON_POSITION_SAMPLE_INTERVAL_S) if mission.recon_intel_id else remaining
            try:
                message = await self.client.server.wait_for_event(
                    "auftrag.*",
                    filters={"auftrag_id": mission.auftrag_id},
                    timeout=wait_timeout,
                    after_id=after_id,
                )
            except TimeoutError:
                if mission.recon_intel_id:
                    await self._sample_recon_positions(mission)
                    continue
                raise
            after_id = str(message.get("id") or "") or after_id
            self.client.state.apply_message(message)
            self.client._on_bridge_message(message)
            if str(message.get("event") or "") == "mission.ended":
                raise DcsMissionEndedError("DCS mission ended while executing operational plan")
            if mission.recon_intel_id:
                await self._sample_recon_positions(mission)
            event = AuftragEvent.from_message(message)
            if event.event == "auftrag.evaluated":
                payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
                snapshot = {
                    "object_id": mission.auftrag_id,
                    "type": payload.get("auftrag_type") or mission.mission_type,
                    "status": payload.get("status"),
                    "summary": payload.get("summary"),
                }
                mission.outcome = AuftragOutcome.from_snapshot(snapshot)
                mission.status = (
                    PlanMissionStatus.SUCCEEDED
                    if mission.outcome.success is True
                    else PlanMissionStatus.FAILED
                )
                if mission.status is PlanMissionStatus.FAILED:
                    mission.error = "AUFTRAG evaluated without success"
                await self._emit(
                    mission,
                    MissionLifecycleEvent(
                        f"mission.{mission.status.value}",
                        message=f"MOOSE AUFTRAG outcome success={mission.outcome.success}",
                    ),
                    on_event,
                )
                return mission.status is PlanMissionStatus.SUCCEEDED
            status_key = (event.fsm_event, event.status, event.from_state, event.to_state)
            if status_key in seen_status_keys:
                continue
            seen_status_keys.add(status_key)
            mission.status = PlanMissionStatus.RUNNING
            await self._emit(
                mission,
                MissionLifecycleEvent("mission.status", message=str(event)),
                on_event,
            )
            if (
                mission.persistent
                and mission.established_on
                and (event.fsm_event or "").lower() == mission.established_on.lower()
            ):
                await self._emit(
                    mission,
                    MissionLifecycleEvent(
                        "mission.established",
                        message=f"persistent AUFTRAG reached {event.fsm_event} and remains active",
                    ),
                    on_event,
                )
                return True

    async def cancel_active(
        self,
        missions: Iterable[PlanMissionExecution],
        *,
        reason: str,
        on_event: MissionLifecycleCallback | None = None,
    ) -> tuple[PlanMissionAbort, ...]:
        """Best-effort cancellation of submitted or running AUFTRAGs."""

        active = (
            mission
            for mission in missions
            if mission.auftrag_id
            and mission.status in {
                PlanMissionStatus.SUBMITTED,
                PlanMissionStatus.RUNNING,
            }
        )
        return await self._cancel_selected(active, reason=reason, timeout=10.0, on_event=on_event)

    async def cancel_live(
        self,
        missions: Iterable[PlanMissionExecution],
        *,
        reason: str,
        timeout: float = 10.0,
        on_event: MissionLifecycleCallback | None = None,
    ) -> tuple[PlanMissionAbort, ...]:
        """Discover and cancel AUFTRAGs that are live in the current MOOSE snapshot."""

        if timeout <= 0:
            raise ValueError("mission cancellation timeout must be greater than zero")
        await self.client.snapshot_auftraege()
        live_statuses = {
            "planned",
            "queued",
            "requested",
            "scheduled",
            "started",
            "executing",
            "paused",
        }
        active = (
            mission
            for mission in missions
            if mission.auftrag_id
            and str(
                self.client.state.auftraege.get(mission.auftrag_id, {}).get("status") or ""
            ).strip().lower() in live_statuses
        )
        return await self._cancel_selected(active, reason=reason, timeout=timeout, on_event=on_event)

    async def _cancel_selected(
        self,
        missions: Iterable[PlanMissionExecution],
        *,
        reason: str,
        timeout: float,
        on_event: MissionLifecycleCallback | None,
    ) -> tuple[PlanMissionAbort, ...]:
        results: list[PlanMissionAbort] = []
        for mission in missions:
            assert mission.auftrag_id is not None
            try:
                await self.client.cancel_mission(mission.auftrag_id, timeout=timeout)
            except Exception as exc:
                message = str(exc) or f"could not cancel {mission.auftrag_id}"
                mission.error = message
                await self._emit(
                    mission,
                    MissionLifecycleEvent("mission.cancel_failed", message=message),
                    on_event,
                )
                results.append(
                    PlanMissionAbort(
                        mission.auftrag_id,
                        mission.phase_id,
                        mission.requirement_id,
                        False,
                        message,
                    )
                )
                continue
            if mission.status is not PlanMissionStatus.CANCELLED:
                mission.status = PlanMissionStatus.CANCELLED
                mission.error = reason
                await self._emit(
                    mission,
                    MissionLifecycleEvent("mission.cancelled", message=reason),
                    on_event,
                )
            results.append(
                PlanMissionAbort(
                    mission.auftrag_id,
                    mission.phase_id,
                    mission.requirement_id,
                    True,
                    reason,
                )
            )
        return tuple(results)

    async def _sample_recon_positions(self, mission: PlanMissionExecution) -> None:
        session = ReconTrackingSession(
            mission.auftrag_id or "",
            assigned_group_ids=mission.recon_assigned_group_ids,
            tracks=mission.recon_tracks,
        )
        await self.client.sample_recon_tracking(session)
        mission.recon_assigned_group_ids = session.assigned_group_ids

    @staticmethod
    async def _emit(
        mission: PlanMissionExecution,
        event: MissionLifecycleEvent,
        callback: MissionLifecycleCallback | None,
    ) -> None:
        if callback is None:
            return
        result = callback(mission, event)
        if inspect.isawaitable(result):
            await result


def command_ack_reference(ack: Mapping[str, Any]) -> CommandAckReference:
    """Build the compact ACK persisted with a plan mission."""

    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    relevant_keys = {
        "action",
        "added",
        "auftrag_id",
        "auftragsnummer",
        "auftrag_type",
        "cohort_id",
        "commander_id",
        "legion_id",
        "target_resolution",
        "target_resolution_error",
    }
    compact_result = {
        str(key): value
        for key, value in result.items()
        if key in relevant_keys and isinstance(value, (str, int, float, bool))
    }
    sequence = ack.get("sequence")
    try:
        sequence_value = int(sequence) if sequence is not None else None
    except (TypeError, ValueError):
        sequence_value = None
    return CommandAckReference(
        ack_id=str(ack.get("id")) if ack.get("id") not in (None, "") else None,
        correlation_id=(
            str(ack.get("correlation_id"))
            if ack.get("correlation_id") not in (None, "")
            else None
        ),
        sequence=sequence_value,
        result=compact_result,
    )


__all__ = [
    "CommandAckReference",
    "MissionExecutionService",
    "MissionLifecycleCallback",
    "MissionLifecycleEvent",
    "PlanMissionExecution",
    "PlanMissionAbort",
    "PlanMissionReconciliation",
    "PlanMissionStatus",
    "command_ack_reference",
]
