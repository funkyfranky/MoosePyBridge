"""Small local SDK wrapper for embedding MOOSE Bridge commands in Python tools."""

from __future__ import annotations

import asyncio
from typing import Any

from .models import Auftrag, OpsGroup, OpsZone
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
