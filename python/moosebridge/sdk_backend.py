"""Backend contract used by the high-level MooseBridge SDK facade."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from .protocol import BridgeCommand
from .state import MooseBridgeState


MessageListener = Callable[[dict[str, Any]], None]


@runtime_checkable
class SdkBackend(Protocol):
    """Transport-neutral operations required by :class:`MooseBridgeClient`."""

    @property
    def state(self) -> MooseBridgeState: ...

    def add_message_listener(self, listener: MessageListener) -> None: ...

    def remove_message_listener(self, listener: MessageListener) -> None: ...

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]: ...

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def event_cursor(self) -> str | None: ...

    async def query_events(
        self,
        event_name: str = "*",
        filters: dict[str, Any] | None = None,
        after_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def append_audit_record(self, record_type: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def query_audit_records(
        self,
        *,
        record_type: str | None = None,
        plan_id: str | None = None,
        attempt_id: str | None = None,
        latest_attempts: bool = False,
    ) -> tuple[dict[str, Any], ...]: ...

    async def snapshot_groups(self) -> dict[str, Any]: ...

    async def snapshot_units(self) -> dict[str, Any]: ...

    async def snapshot_ammunition(self) -> dict[str, Any]: ...

    async def snapshot_statics(self) -> dict[str, Any]: ...

    async def snapshot_airbases(self) -> dict[str, Any]: ...

    async def snapshot_zones(self) -> dict[str, Any]: ...

    async def snapshot_territories(self) -> dict[str, Any]: ...

    async def snapshot_opszones(self) -> dict[str, Any]: ...

    async def snapshot_opsgroups(self) -> dict[str, Any]: ...

    async def snapshot_auftraege(self) -> dict[str, Any]: ...

    async def snapshot_cohorts(self) -> dict[str, Any]: ...

    async def snapshot_legions(self) -> dict[str, Any]: ...

    async def snapshot_commanders(self) -> dict[str, Any]: ...

    async def snapshot_intels(self) -> dict[str, Any]: ...

    async def snapshot_intel_contacts(self) -> dict[str, Any]: ...

    async def snapshot_intel_clusters(self) -> dict[str, Any]: ...
