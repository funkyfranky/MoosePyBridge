"""Small local SDK wrapper for embedding MOOSE Bridge commands in Python tools."""

from __future__ import annotations

from .server import MooseBridgeServer


class MooseBridgeClient:
    """High-level SDK facade backed by a local ``MooseBridgeServer`` instance.

    :param server: Running bridge server instance.
    """

    def __init__(self, server: MooseBridgeServer) -> None:
        self.server = server

    async def message_to_coalition(self, coalition: str, text: str, duration: int = 10):
        """Send a message to a coalition in DCS.

        :param coalition: Coalition name.
        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.server.message_to_coalition(coalition, text, duration)

    async def message_to_all(self, text: str, duration: int = 10):
        """Send a message to all players in DCS.

        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.server.message_to_all(text, duration)

    async def smoke_at_point(self, x: float, z: float, color: str = "white", y: float = 0.0):
        """Create smoke at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param color: Smoke color: red, green, blue, orange, or white.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.server.smoke_at_point(x, z, color, y)

    async def smoke_object(self, object_id: str, color: str = "white"):
        """Create smoke at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``UNIT:Name``.
        :param color: Smoke color: red, green, blue, orange, or white.
        :returns: ACK message received from DCS.
        """

        return await self.server.smoke_object(object_id, color)

    async def mark_at_point(self, x: float, z: float, text: str, y: float = 0.0):
        """Create a map mark at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param text: Mark text.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.server.mark_at_point(x, z, text, y)

    async def mark_object(self, object_id: str, text: str):
        """Create a map mark at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``GROUP:Name``.
        :param text: Mark text.
        :returns: ACK message received from DCS.
        """

        return await self.server.mark_object(object_id, text)
