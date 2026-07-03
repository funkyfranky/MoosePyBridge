"""Adapter that lets the high-level SDK use a control API client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .control import MooseBridgeControlClient
from .protocol import BridgeCommand
from .state import MooseBridgeState

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


class ControlSdkAdapter:
    """Adapt :class:`MooseBridgeControlClient` to the SDK server interface."""

    def __init__(self, client: MooseBridgeControlClient, timeout: float = 10.0) -> None:
        self.client = client
        self.timeout = timeout

    @property
    def state(self) -> MooseBridgeState:
        """Return the shared control-client state mirror."""

        return self.client.state

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        """Forward one SDK command through the local control API."""

        return await self.client.send_dcs_command(command.action, command.params, timeout=timeout)

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait for one daemon event through the control API."""

        return await self.client.wait_for_event(event_name, filters=filters, timeout=timeout, after_id=after_id)

    async def _snapshot(self, kind: str) -> dict[str, Any]:
        action = f"snapshot.{kind}"
        result = await self.client.request("control.snapshots", params={"actions": [action]}, timeout=self.timeout)
        acks = result.get("acks") if isinstance(result.get("acks"), list) else []
        return acks[0] if acks else {"ok": True, "result": {"kind": kind, "count": 0}}

    async def snapshot_groups(self) -> dict[str, Any]:
        """Request a GROUP snapshot through the control API."""

        return await self._snapshot("groups")

    async def snapshot_units(self) -> dict[str, Any]:
        """Request a UNIT snapshot through the control API."""

        return await self._snapshot("units")

    async def snapshot_statics(self) -> dict[str, Any]:
        """Request a STATIC snapshot through the control API."""

        return await self._snapshot("statics")

    async def snapshot_airbases(self) -> dict[str, Any]:
        """Request an AIRBASE snapshot through the control API."""

        return await self._snapshot("airbases")

    async def snapshot_zones(self) -> dict[str, Any]:
        """Request a ZONE snapshot through the control API."""

        return await self._snapshot("zones")

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


def sdk_from_control_client(client: MooseBridgeControlClient, timeout: float = 10.0) -> "MooseBridgeClient":
    """Return a high-level SDK client backed by a control client."""

    from .sdk import MooseBridgeClient

    return MooseBridgeClient(ControlSdkAdapter(client, timeout=timeout))  # type: ignore[arg-type]
