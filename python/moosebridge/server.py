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

    async def snapshot_groups(self) -> dict[str, Any]:
        """Request a GROUP snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.groups", params={}))

    def _write_raw(self, direction: str, line: str) -> None:
        """Write one raw protocol line to the JSONL log.

        :param direction: Direction label, either ``dcs`` or ``python``.
        :param line: Raw JSON line.
        """

        if self._raw_log_file is None:
            return
        self._raw_log_file.write(json.dumps({"direction": direction, "line": line}, ensure_ascii=False) + "\n")
        self._raw_log_file.flush()


HELP_TEXT = """
Interactive commands:
  help, ?                 Show this help.
  status                  Show current bridge connection status.
  groups                  Request and print a GROUP snapshot.
  all <text>              Send a MOOSE MESSAGE to all players.
  blue <text>             Send a MOOSE MESSAGE to blue coalition.
  red <text>              Send a MOOSE MESSAGE to red coalition.
  neutral <text>          Send a MOOSE MESSAGE to neutral coalition.
  quit, exit              Stop the bridge server.
""".strip()


async def _read_console_line(prompt: str = "moosebridge> ") -> str:
    """Read one console line without blocking the asyncio event loop.

    :param prompt: Prompt text displayed to the user.
    :returns: Console input line.
    """

    return await asyncio.to_thread(input, prompt)


def _print_group_snapshot(groups: dict[str, dict[str, Any]], limit: int = 25) -> None:
    """Print a compact GROUP snapshot summary.

    :param groups: Mapping from object id to group payload.
    :param limit: Maximum number of groups to print.
    """

    items = list(groups.values())
    print(f"groups={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        coalition = item.get("coalition", "")
        category = item.get("category", "")
        alive = item.get("alive", "")
        active = item.get("active", "")
        alive_units = item.get("alive_unit_count", "")
        units = item.get("unit_count", "")
        print(f"  {object_id} coalition={coalition} category={category} alive={alive} active={active} units={alive_units}/{units}")

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more groups not shown")


async def run_interactive_console(server: MooseBridgeServer) -> None:
    """Run an interactive command console backed by a bridge server.

    :param server: Running bridge server instance.
    """

    print(HELP_TEXT)

    while True:
        try:
            line = (await _read_console_line()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not line:
            continue

        command, _, argument = line.partition(" ")
        command = command.lower()
        argument = argument.strip()

        if command in {"quit", "exit"}:
            return

        if command in {"help", "?"}:
            print(HELP_TEXT)
            continue

        if command == "status":
            print(f"connected={server.state.connected}")
            if server.state.last_heartbeat is not None:
                print(f"last_heartbeat={server.state.last_heartbeat}")
            continue

        if not server.state.connected:
            print("No DCS bridge connection is active.")
            continue

        try:
            if command == "groups":
                ack = await server.snapshot_groups()
                print(f"ACK: {ack}")
                _print_group_snapshot(server.state.groups)
                continue
            if command == "all":
                if not argument:
                    print("Usage: all <text>")
                    continue
                ack = await server.message_to_all(argument)
            elif command in {"blue", "red", "neutral"}:
                if not argument:
                    print(f"Usage: {command} <text>")
                    continue
                ack = await server.message_to_coalition(command, argument)
            else:
                print(f"Unknown command: {command}")
                print("Type 'help' for available commands.")
                continue
        except Exception as exc:
            print(f"ERROR: {exc}")
            continue

        print(f"ACK: {ack}")


async def _run(args: argparse.Namespace) -> None:
    """Run the command-line server entry point.

    :param args: Parsed CLI arguments.
    """

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = MooseBridgeServer(args.host, args.port, Path(args.log) if args.log else None)

    if args.interactive:
        await server.start()
        try:
            await run_interactive_console(server)
        finally:
            await server.stop()
        return

    await server.serve_forever()


def main() -> None:
    """Console script entry point."""

    parser = argparse.ArgumentParser(description="MOOSE Bridge TCP JSONL server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50100)
    parser.add_argument("--log", default="moosebridge_raw.jsonl")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--interactive", action="store_true", help="Run an interactive command console after starting the server")
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user")


if __name__ == "__main__":
    main()
