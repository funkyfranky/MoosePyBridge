"""Asyncio TCP JSONL server for the MOOSE Bridge V1 prototype."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from .protocol import BridgeCommand, PendingCommand
from .state import MooseBridgeState

LOGGER = logging.getLogger(__name__)


class MooseBridgeServer:
    """Single-DCS, multi-client bridge server.

    :param host: Interface to bind.
    :param port: TCP port to listen on.
    :param log_path: Optional raw JSONL log file path.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 50100, log_path: Path | None = None) -> None:
        self.host = host
        self.port = port
        self.log_path = log_path
        self.state = MooseBridgeState()
        self._server: asyncio.AbstractServer | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._sequence = 0
        self._pending: dict[str, PendingCommand] = {}
        self._raw_log_file = None

    async def start(self) -> None:
        """Start listening for the DCS Lua bridge connection."""

        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._raw_log_file = self.log_path.open("a", encoding="utf-8")

        self._server = await asyncio.start_server(self._handle_dcs_client, self.host, self.port)
        sockets = ", ".join(str(sock.getsockname()) for sock in self._server.sockets or [])
        LOGGER.info("MOOSE Bridge server listening on %s", sockets)

    async def serve_forever(self) -> None:
        """Start the server and run until cancelled."""

        await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the server and close active resources."""

        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if self._raw_log_file is not None:
            self._raw_log_file.close()
            self._raw_log_file = None

    async def _handle_dcs_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle the single authoritative DCS connection.

        :param reader: Async stream reader.
        :param writer: Async stream writer.
        """

        peer = writer.get_extra_info("peername")
        LOGGER.info("DCS connected from %s", peer)

        if self._writer is not None:
            LOGGER.warning("Replacing previous DCS connection")
            self._writer.close()

        self._writer = writer
        self.state.connected = True

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                await self._handle_line(line.decode("utf-8").strip())
        finally:
            LOGGER.warning("DCS disconnected from %s", peer)
            if self._writer is writer:
                self._writer = None
            self.state.connected = False
            writer.close()
            await writer.wait_closed()

    async def _handle_line(self, line: str) -> None:
        """Parse and process a single JSONL message from DCS.

        :param line: Raw line without newline.
        """

        if not line:
            return

        self._write_raw("dcs", line)

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            LOGGER.exception("Invalid JSON from DCS: %s", line)
            return

        LOGGER.debug("DCS -> Python: %s", message)
        self.state.apply_message(message)

        if message.get("type") == "ack":
            self._resolve_ack(message)

    def _resolve_ack(self, message: dict[str, Any]) -> None:
        """Resolve a pending command future from an ACK message.

        :param message: Decoded ACK message.
        """

        command_id = message.get("correlation_id")
        if not command_id:
            return

        pending = self._pending.pop(str(command_id), None)
        if pending is None:
            return

        if not pending.future.done():
            pending.future.set_result(message)

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        """Send a command to DCS and wait for its ACK.

        :param command: Command to send.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: ACK message received from DCS.
        :raises RuntimeError: If no DCS connection is active.
        :raises TimeoutError: If DCS does not ACK the command in time.
        """

        if self._writer is None:
            raise RuntimeError("No DCS bridge connection is active")

        self._sequence += 1
        data = command.to_dict(sequence=self._sequence)
        line = json.dumps(data, separators=(",", ":"), ensure_ascii=False)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[command.id] = PendingCommand(command=command, future=future)

        LOGGER.debug("Python -> DCS: %s", data)
        self._write_raw("python", line)
        self._writer.write((line + "\n").encode("utf-8"))
        await self._writer.drain()

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._pending.pop(command.id, None)
            raise

    async def message_to_coalition(self, coalition: str, text: str, duration: int = 10) -> dict[str, Any]:
        """Send a MOOSE message to one coalition.

        :param coalition: Coalition name: ``blue``, ``red`` or ``neutral``.
        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.send_command(
            BridgeCommand(
                action="message.to_coalition",
                params={"coalition": coalition, "text": text, "duration": duration},
            )
        )

    async def message_to_all(self, text: str, duration: int = 10) -> dict[str, Any]:
        """Send a MOOSE message to all players.

        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.send_command(
            BridgeCommand(
                action="message.to_all",
                params={"text": text, "duration": duration},
            )
        )

    def _write_raw(self, direction: str, line: str) -> None:
        """Write one raw protocol line to the JSONL log.

        :param direction: Direction label, either ``dcs`` or ``python``.
        :param line: Raw JSON line.
        """

        if self._raw_log_file is None:
            return
        self._raw_log_file.write(json.dumps({"direction": direction, "line": line}, ensure_ascii=False) + "\n")
        self._raw_log_file.flush()


async def _run(args: argparse.Namespace) -> None:
    """Run the command-line server entry point.

    :param args: Parsed CLI arguments.
    """

    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server = MooseBridgeServer(args.host, args.port, Path(args.log) if args.log else None)
    await server.serve_forever()


def main() -> None:
    """Console script entry point."""

    parser = argparse.ArgumentParser(description="MOOSE Bridge TCP JSONL server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50100)
    parser.add_argument("--log", default="moosebridge_raw.jsonl")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user")


if __name__ == "__main__":
    main()
