"""Small local SDK wrapper for embedding MOOSE Bridge commands in Python tools."""

from __future__ import annotations

import asyncio
from typing import Any

from .models import Auftrag, OpsGroup, OpsZone
from .outcomes import AuftragOutcome
from .protocol import BridgeCommand
from .server import MooseBridgeServer
from .state import MooseBridgeState

SMOKE_COLORS = {"red", "green", "blue", "orange", "white"}


class MooseBridgeCommandError(RuntimeError):
    """Raised when DCS rejects a bridge command.

    :param ack: ACK payload returned by DCS.
    """

    def __init__(self, ack: dict[str, Any]) -> None:
        self.ack = ack
        super().__init__(str(ack.get("error") or "DCS command failed"))


class MooseBridgeAuftragTimeoutError(TimeoutError):
    """Raised when an AUFTRAG does not produce an evaluation summary in time."""


class MooseBridgeAuftragNotFoundError(RuntimeError):
    """Raised when an AUFTRAG is never observed in snapshots."""


def require_ok(ack: dict[str, Any]) -> dict[str, Any]:
    """Validate that a DCS ACK accepted the command.

    :param ack: ACK payload returned by DCS.
    :returns: The original ACK payload if it is successful.
    :raises MooseBridgeCommandError: If DCS returned ``ok=false``.
    """

    if not ack.get("ok", False):
        raise MooseBridgeCommandError(ack)
    return ack


def validate_smoke_color(color: str) -> str:
    """Validate and normalize a smoke color.

    :param color: Requested smoke color.
    :returns: Lower-case smoke color.
    :raises ValueError: If the color is unsupported.
    """

    normalized = color.lower().strip()
    if normalized not in SMOKE_COLORS:
        raise ValueError(f"Unsupported smoke color: {color!r}. Expected one of {sorted(SMOKE_COLORS)}")
    return normalized


def auftrag_action_for_mission_type(mission_type: str) -> str:
    """Return the bridge command action for an AUFTRAG mission type.

    :param mission_type: MOOSE mission type such as ``BAI`` or ``BOMBING``.
    :returns: Bridge command action string.
    """

    return f"auftrag.create_{mission_type.strip().lower()}"


def build_recommended_auftrag_command_params(recommendation: Any) -> dict[str, Any]:
    """Build flat Lua command parameters from an AUFTRAG recommendation.

    :param recommendation: Recommendation object with ``to_dict``.
    :returns: Flat command parameter dictionary.
    """

    params = recommendation.to_dict()
    nested = params.get("params") if isinstance(params.get("params"), dict) else {}
    return {
        "legion_id": params.get("legion_id"),
        "cohort_id": params.get("cohort_id"),
        "target": nested.get("target"),
        "altitude_ft": nested.get("altitude_ft"),
        "selected_payload_uid": params.get("selected_payload_uid"),
        "mission_type": params.get("mission_type"),
        "constructor": params.get("constructor"),
    }


def is_evaluated_auftrag_snapshot(snapshot: dict[str, Any]) -> bool:
    """Return whether an AUFTRAG snapshot contains MOOSE's summary table.

    :param snapshot: Raw AUFTRAG snapshot.
    :returns: ``True`` when ``summary`` is present.
    """

    return isinstance(snapshot.get("summary"), dict)


class MooseBridgeClient:
    """High-level SDK facade backed by a local ``MooseBridgeServer`` instance.

    :param server: Running bridge server instance.
    """

    def __init__(self, server: MooseBridgeServer) -> None:
        self.server = server

    @property
    def state(self) -> MooseBridgeState:
        """Return the current typed and raw bridge state.

        :returns: Local state mirror maintained by the server.
        """

        return self.server.state

    def opszone(self, object_id: str) -> OpsZone | None:
        """Return a typed OPSZONE by object id.

        :param object_id: Stable bridge object id such as ``OPSZONE:Town Fight``.
        :returns: Typed OPSZONE or ``None``.
        """

        return self.state.opszone(object_id)

    def opsgroup(self, object_id: str) -> OpsGroup | None:
        """Return a typed OPSGROUP by object id.

        :param object_id: Stable bridge object id such as ``OPSGROUP:Aerial-1``.
        :returns: Typed OPSGROUP or ``None``.
        """

        return self.state.opsgroup(object_id)

    def auftrag(self, object_id: str) -> Auftrag | None:
        """Return a typed AUFTRAG by object id.

        :param object_id: Stable bridge object id such as ``AUFTRAG:1``.
        :returns: Typed AUFTRAG or ``None``.
        """

        return self.state.auftrag(object_id)

    def current_auftrag_for_group(self, opsgroup_id: str) -> Auftrag | None:
        """Return the current AUFTRAG assigned to an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Typed AUFTRAG or ``None``.
        """

        return self.state.current_auftrag_for_group(opsgroup_id)

    def queued_auftraege_for_group(self, opsgroup_id: str) -> list[Auftrag]:
        """Return queued AUFTRAG objects for an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Typed AUFTRAG objects present in the local state mirror.
        """

        return self.state.queued_auftraege_for_group(opsgroup_id)

    async def request_snapshots(self, actions: tuple[str, ...]) -> None:
        """Request a sequence of bridge snapshots.

        :param actions: Snapshot command actions.
        :raises MooseBridgeCommandError: If any snapshot command is rejected.
        """

        for action in actions:
            require_ok(await self.server.send_command(BridgeCommand(action=action, params={})))
            await asyncio.sleep(0.05)

    async def snapshot_opszones(self) -> dict[str, Any]:
        """Request an OPSZONE snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_opszones())

    async def snapshot_opsgroups(self) -> dict[str, Any]:
        """Request an OPSGROUP snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_opsgroups())

    async def snapshot_auftraege(self) -> dict[str, Any]:
        """Request an AUFTRAG snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_auftraege())

    async def request_ops_state(self) -> MooseBridgeState:
        """Request OPS snapshots and return the updated local state mirror.

        :returns: Updated local state mirror.
        :raises MooseBridgeCommandError: If DCS rejects one of the snapshot commands.
        """

        await self.snapshot_opszones()
        await self.snapshot_opsgroups()
        await self.snapshot_auftraege()
        await asyncio.sleep(0.1)
        return self.state

    async def apply_auftrag(self, mission_type: str, params: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        """Apply an AUFTRAG command to DCS.

        :param mission_type: Mission type such as ``BAI`` or ``BOMBING``.
        :param params: Flat command parameters accepted by the Lua extension.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        action = auftrag_action_for_mission_type(mission_type)
        return require_ok(await self.server.send_command(BridgeCommand(action=action, params=params), timeout=timeout))

    async def apply_recommended_auftrag(self, recommendation: Any, timeout: float = 10.0) -> dict[str, Any]:
        """Apply an AUFTRAG recommendation produced by the advisory layer.

        :param recommendation: Recommendation object with ``to_dict``.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        data = recommendation.to_dict()
        mission_type = str(data.get("mission_type") or "").strip()
        if not mission_type:
            raise ValueError("Recommendation does not include mission_type")
        return await self.apply_auftrag(mission_type, build_recommended_auftrag_command_params(recommendation), timeout=timeout)

    async def wait_for_auftrag_outcome(
        self,
        auftrag_id: str,
        timeout_s: float = 600.0,
        interval_s: float = 5.0,
    ) -> AuftragOutcome:
        """Wait until an AUFTRAG has been evaluated and return its outcome.

        The method waits for MOOSE to create ``AUFTRAG.summary`` and uses
        ``summary.success`` as the authoritative result.

        :param auftrag_id: Stable AUFTRAG object id from the apply ACK.
        :param timeout_s: Maximum monitoring time in seconds.
        :param interval_s: Poll interval in seconds.
        :returns: Stable AUFTRAG outcome model.
        :raises MooseBridgeAuftragNotFoundError: If the AUFTRAG is never observed.
        :raises MooseBridgeAuftragTimeoutError: If no summary appears before timeout.
        """

        deadline = asyncio.get_running_loop().time() + timeout_s
        seen = False
        last_snapshot: dict[str, Any] | None = None

        while asyncio.get_running_loop().time() < deadline:
            await self.request_snapshots(("snapshot.auftraege", "snapshot.legions", "snapshot.opsgroups"))
            snapshot = self.state.auftraege.get(auftrag_id)
            if snapshot is not None:
                seen = True
                last_snapshot = snapshot
                if is_evaluated_auftrag_snapshot(snapshot):
                    return AuftragOutcome.from_snapshot(snapshot)
            await asyncio.sleep(interval_s)

        if not seen:
            raise MooseBridgeAuftragNotFoundError(f"{auftrag_id} was not visible before monitor timeout")
        raise MooseBridgeAuftragTimeoutError(f"{auftrag_id} was not evaluated before timeout; last_snapshot={last_snapshot!r}")

    async def message_coalition(self, coalition: str, text: str, duration: int = 10) -> dict[str, Any]:
        """Send a message to a coalition in DCS.

        :param coalition: Coalition name.
        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.message_to_coalition(coalition, text, duration))

    async def message_to_coalition(self, coalition: str, text: str, duration: int = 10) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`message_coalition`.

        :param coalition: Coalition name.
        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.message_coalition(coalition, text, duration)

    async def message_all(self, text: str, duration: int = 10) -> dict[str, Any]:
        """Send a message to all players in DCS.

        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.message_to_all(text, duration))

    async def message_to_all(self, text: str, duration: int = 10) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`message_all`.

        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.message_all(text, duration)

    async def smoke_point(self, x: float, z: float, color: str = "white", y: float = 0.0) -> dict[str, Any]:
        """Create smoke at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param color: Smoke color: red, green, blue, orange, or white.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.smoke_at_point(x, z, validate_smoke_color(color), y))

    async def smoke_at_point(self, x: float, z: float, color: str = "white", y: float = 0.0) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`smoke_point`.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param color: Smoke color: red, green, blue, orange, or white.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.smoke_point(x, z, color, y)

    async def smoke_object(self, object_id: str, color: str = "white") -> dict[str, Any]:
        """Create smoke at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``UNIT:Name``.
        :param color: Smoke color: red, green, blue, orange, or white.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.smoke_object(object_id, validate_smoke_color(color)))

    async def mark_point(self, x: float, z: float, text: str, y: float = 0.0) -> dict[str, Any]:
        """Create a map mark at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param text: Mark text.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.mark_at_point(x, z, text, y))

    async def mark_at_point(self, x: float, z: float, text: str, y: float = 0.0) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`mark_point`.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param text: Mark text.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.mark_point(x, z, text, y)

    async def mark_object(self, object_id: str, text: str) -> dict[str, Any]:
        """Create a map mark at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``GROUP:Name``.
        :param text: Mark text.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.mark_object(object_id, text))
