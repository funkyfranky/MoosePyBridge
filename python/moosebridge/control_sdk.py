"""Adapter that lets the high-level SDK use a control API client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from .control import ControlClientIdentity, MooseBridgeControlClient
from .protocol import BridgeCommand
from .state import MooseBridgeState

if TYPE_CHECKING:
    from .sensor_ranges import SensorRangeRegistry
    from .sdk import MooseBridgeClient
    from .weapon_ranges import WeaponRangeRegistry


class ControlSdkAdapter:
    """Adapt :class:`MooseBridgeControlClient` to the SDK server interface."""

    def __init__(self, client: MooseBridgeControlClient, timeout: float = 10.0) -> None:
        self.client = client
        self.timeout = timeout
        self._message_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._mission_generation = client.state.mission_generation

    def add_message_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Register an SDK listener for control-observed mission boundaries."""

        if listener not in self._message_listeners:
            self._message_listeners.append(listener)

    def remove_message_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        if listener in self._message_listeners:
            self._message_listeners.remove(listener)

    def _notify_mission_boundary(self) -> None:
        generation = self.client.state.mission_generation
        if generation == self._mission_generation:
            return
        self._mission_generation = generation
        message = {
            "type": "event",
            "event": "mission.ended",
            "payload": {"reason": "mission_generation_changed", "mission_generation": generation},
        }
        for listener in tuple(self._message_listeners):
            listener(message)

    @property
    def state(self) -> MooseBridgeState:
        """Return the shared control-client state mirror."""

        return self.client.state

    @property
    def client_identity(self) -> ControlClientIdentity:
        """Return the declared identity propagated by control requests."""

        return self.client.identity

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        """Forward one SDK command through the local control API."""

        result = await self.client.send_dcs_command(command.action, command.params, timeout=timeout)
        self._notify_mission_boundary()
        return result

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait for one daemon event through the control API."""

        result = await self.client.wait_for_event(event_name, filters=filters, timeout=timeout, after_id=after_id)
        self._notify_mission_boundary()
        return result

    async def event_cursor(self) -> str | None:
        """Return the latest daemon event id."""

        return await self.client.event_cursor(timeout=self.timeout)

    async def query_events(
        self,
        event_name: str = "*",
        filters: dict[str, Any] | None = None,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        """Query retained daemon events through the control API."""

        return await self.client.query_events(
            event_name,
            filters=filters,
            after_id=after_id,
            timeout=self.timeout,
        )

    async def append_audit_record(self, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append one SDK audit record through the control API."""

        return await self.client.append_audit_record(record_type, payload, timeout=self.timeout)

    async def query_audit_records(
        self,
        *,
        record_type: str | None = None,
        plan_id: str | None = None,
        attempt_id: str | None = None,
        latest_attempts: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        """Query SDK audit records through the control API."""

        return await self.client.query_audit_records(
            record_type=record_type,
            plan_id=plan_id,
            attempt_id=attempt_id,
            latest_attempts=latest_attempts,
            timeout=self.timeout,
        )

    async def _snapshot(self, kind: str) -> dict[str, Any]:
        action = f"snapshot.{kind}"
        result = await self.client.request("control.snapshots", params={"actions": [action]}, timeout=self.timeout)
        self._notify_mission_boundary()
        acks = result.get("acks") if isinstance(result.get("acks"), list) else []
        return acks[0] if acks else {"ok": True, "result": {"kind": kind, "count": 0}}

    async def snapshot_groups(self) -> dict[str, Any]:
        """Request a GROUP snapshot through the control API."""

        return await self._snapshot("groups")

    async def snapshot_units(self) -> dict[str, Any]:
        """Request a UNIT snapshot through the control API."""

        return await self._snapshot("units")

    async def snapshot_ammunition(self) -> dict[str, Any]:
        """Request a detailed ground and naval ammunition snapshot."""

        return await self._snapshot("ammunition")

    async def snapshot_statics(self) -> dict[str, Any]:
        """Request a STATIC snapshot through the control API."""

        return await self._snapshot("statics")

    async def snapshot_airbases(self) -> dict[str, Any]:
        """Request an AIRBASE snapshot through the control API."""

        return await self._snapshot("airbases")

    async def snapshot_zones(self) -> dict[str, Any]:
        """Request a ZONE snapshot through the control API."""

        return await self._snapshot("zones")

    async def snapshot_territories(self) -> dict[str, Any]:
        """Request a TERRITORY snapshot through the control API."""

        return await self._snapshot("territories")

    async def snapshot_opszones(self) -> dict[str, Any]:
        """Request an OPSZONE snapshot through the control API."""

        return await self._snapshot("opszones")

    async def snapshot_opsgroups(self) -> dict[str, Any]:
        """Request an OPSGROUP snapshot through the control API."""

        return await self._snapshot("opsgroups")

    async def snapshot_auftraege(self) -> dict[str, Any]:
        """Request an AUFTRAG snapshot through the control API."""

        return await self._snapshot("auftraege")

    async def snapshot_cohorts(self) -> dict[str, Any]:
        """Request a COHORT snapshot through the control API."""

        return await self._snapshot("cohorts")

    async def snapshot_legions(self) -> dict[str, Any]:
        """Request a LEGION snapshot through the control API."""

        return await self._snapshot("legions")

    async def snapshot_commanders(self) -> dict[str, Any]:
        """Request a COMMANDER snapshot through the control API."""

        return await self._snapshot("commanders")

    async def snapshot_intels(self) -> dict[str, Any]:
        """Request an INTEL snapshot through the control API."""

        return await self._snapshot("intels")

    async def snapshot_intel_contacts(self) -> dict[str, Any]:
        """Request an INTEL contact snapshot through the control API."""

        return await self._snapshot("intel_contacts")

    async def snapshot_intel_clusters(self) -> dict[str, Any]:
        """Request an INTEL cluster snapshot through the control API."""

        return await self._snapshot("intel_clusters")


def sdk_from_control_client(
    client: MooseBridgeControlClient,
    timeout: float = 10.0,
    *,
    weapon_ranges: "WeaponRangeRegistry | None" = None,
    sensor_ranges: "SensorRangeRegistry | None" = None,
) -> "MooseBridgeClient":
    """Return a high-level SDK client backed by a control client."""

    from .sdk import MooseBridgeClient

    return MooseBridgeClient(  # type: ignore[arg-type]
        ControlSdkAdapter(client, timeout=timeout),
        weapon_ranges=weapon_ranges,
        sensor_ranges=sensor_ranges,
    )
