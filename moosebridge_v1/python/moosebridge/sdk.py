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
