"""Async stream helpers shared by the bridge servers and clients."""

from __future__ import annotations

import asyncio
import logging


async def close_stream_writer(
    writer: asyncio.StreamWriter,
    *,
    logger: logging.Logger | None = None,
    context: str = "stream connection",
) -> None:
    """Close a stream while tolerating an already reset peer connection."""

    try:
        writer.close()
        await writer.wait_closed()
    except (ConnectionError, OSError):
        if logger is not None:
            logger.debug("Socket error while closing %s", context, exc_info=True)
