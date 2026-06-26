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
DEFAULT_PORT = 51000
DEFAULT_READER_LIMIT = 16 * 1024 * 1024


class MooseBridgeServer:
    """Single-DCS, multi-client bridge server.

    :param host: Interface to bind.
    :param port: TCP port to listen on.
    :param log_path: Optional raw JSONL log file path.
    :param reader_limit: Maximum incoming JSONL line size in bytes.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        log_path: Path | None = None,
        reader_limit: int = DEFAULT_READER_LIMIT,
    ) -> None:
        self.host = host
        self.port = port
        self.log_path = log_path
        self.reader_limit = reader_limit
        self.state = MooseBridgeState()
        self._server: asyncio.AbstractServer | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._sequence = 0
        self._pending: dict[str, PendingCommand] = {}
        self._raw_log_file = None

    def _fail_pending(self, exc: BaseException) -> None:
        """Fail all commands currently waiting for a DCS ACK."""

        pending = list(self._pending.values())
        self._pending.clear()
        for item in pending:
            if not item.future.done():
                item.future.set_exception(exc)

    async def start(self) -> None:
        """Start listening for the DCS Lua bridge connection."""

        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._raw_log_file = self.log_path.open("a", encoding="utf-8")

        self._server = await asyncio.start_server(
            self._handle_dcs_client,
            self.host,
            self.port,
            limit=self.reader_limit,
        )
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

        self._fail_pending(RuntimeError("MOOSE Bridge server stopped"))

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
            self._fail_pending(RuntimeError("DCS bridge connection was replaced"))
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
                self._fail_pending(RuntimeError("DCS bridge connection disconnected"))
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
        try:
            self._writer.write((line + "\n").encode("utf-8"))
            await self._writer.drain()
        except Exception:
            self._pending.pop(command.id, None)
            raise

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

        return await self.send_command(BridgeCommand(action="message.to_all", params={"text": text, "duration": duration}))

    async def smoke_at_point(self, x: float, z: float, color: str = "white", y: float = 0.0) -> dict[str, Any]:
        """Create smoke at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param color: Smoke color: red, green, blue, orange, or white.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.send_command(BridgeCommand(action="smoke.at_point", params={"x": x, "y": y, "z": z, "color": color}))

    async def smoke_object(self, object_id: str, color: str = "white") -> dict[str, Any]:
        """Create smoke at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``UNIT:Name``.
        :param color: Smoke color: red, green, blue, orange, or white.
        :returns: ACK message received from DCS.
        """

        return await self.send_command(BridgeCommand(action="smoke.object", params={"object_id": object_id, "color": color}))

    async def mark_at_point(self, x: float, z: float, text: str, y: float = 0.0) -> dict[str, Any]:
        """Create a map mark at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param text: Mark text.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.send_command(BridgeCommand(action="mark.at_point", params={"x": x, "y": y, "z": z, "text": text}))

    async def mark_object(self, object_id: str, text: str) -> dict[str, Any]:
        """Create a map mark at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``GROUP:Name``.
        :param text: Mark text.
        :returns: ACK message received from DCS.
        """

        return await self.send_command(BridgeCommand(action="mark.object", params={"object_id": object_id, "text": text}))

    async def snapshot_groups(self) -> dict[str, Any]:
        """Request a GROUP snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.groups", params={}))

    async def snapshot_units(self) -> dict[str, Any]:
        """Request a UNIT snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.units", params={}))

    async def snapshot_statics(self) -> dict[str, Any]:
        """Request a STATIC snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.statics", params={}))

    async def snapshot_airbases(self) -> dict[str, Any]:
        """Request an AIRBASE snapshot from DCS.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.airbases", params={}))

    async def snapshot_zones(self) -> dict[str, Any]:
        """Request a ZONE snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.zones", params={}))

    async def snapshot_opszones(self) -> dict[str, Any]:
        """Request an OPSZONE snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.opszones", params={}))

    async def snapshot_opsgroups(self) -> dict[str, Any]:
        """Request an OPSGROUP snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.opsgroups", params={}))

    async def snapshot_auftraege(self) -> dict[str, Any]:
        """Request an AUFTRAG snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.auftraege", params={}))

    async def snapshot_cohorts(self) -> dict[str, Any]:
        """Request a COHORT snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.cohorts", params={}))

    async def snapshot_legions(self) -> dict[str, Any]:
        """Request a LEGION snapshot from DCS/MOOSE.

        :returns: ACK message received from DCS after the snapshot was queued.
        """

        return await self.send_command(BridgeCommand(action="snapshot.legions", params={}))

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
  units                   Request and print a UNIT snapshot.
  statics                 Request and print a STATIC snapshot.
  airbases                Request and print an AIRBASE snapshot.
  zones                   Request and print a ZONE snapshot.
  opszones                Request and print an OPSZONE snapshot.
  opsgroups               Request and print an OPSGROUP snapshot.
  auftraege               Request and print an AUFTRAG snapshot.
  cohorts                 Request and print a COHORT snapshot.
  legions                 Request and print a LEGION snapshot.
  smoke <object_id> [color]       Smoke an object position.
  smokepoint <x> <z> [color]      Smoke a DCS world point.
  mark <object_id> <text>         Mark an object position.
  markpoint <x> <z> <text>        Mark a DCS world point.
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


def _parse_float(value: str, name: str) -> float:
    """Parse a CLI float argument.

    :param value: Raw argument value.
    :param name: User-facing argument name for errors.
    :returns: Parsed floating point value.
    """

    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {name}: {value}") from exc


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


def _print_unit_snapshot(units: dict[str, dict[str, Any]], limit: int = 40) -> None:
    """Print a compact UNIT snapshot summary.

    :param units: Mapping from object id to unit payload.
    :param limit: Maximum number of units to print.
    """

    items = list(units.values())
    print(f"units={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        group_name = item.get("group_name", "")
        coalition = item.get("coalition", "")
        category = item.get("category", "")
        dcs_type = item.get("dcs_type", "")
        alive = item.get("alive", "")
        active = item.get("active", "")
        print(
            f"  {object_id} group={group_name} coalition={coalition} "
            f"category={category} dcs_type={dcs_type} alive={alive} active={active}"
        )

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more units not shown")


def _print_static_snapshot(statics: dict[str, dict[str, Any]], limit: int = 40) -> None:
    """Print a compact STATIC snapshot summary.

    :param statics: Mapping from object id to static payload.
    :param limit: Maximum number of statics to print.
    """

    items = list(statics.values())
    print(f"statics={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        coalition = item.get("coalition", "")
        category = item.get("category", "")
        dcs_type = item.get("dcs_type", "")
        alive = item.get("alive", "")
        x = item.get("x", "")
        z = item.get("z", "")
        print(f"  {object_id} coalition={coalition} category={category} dcs_type={dcs_type} alive={alive} x={x} z={z}")

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more statics not shown")


def _print_airbase_snapshot(airbases: dict[str, dict[str, Any]], limit: int = 60) -> None:
    """Print a compact AIRBASE snapshot summary.

    :param airbases: Mapping from object id to airbase payload.
    :param limit: Maximum number of airbases to print.
    """

    items = list(airbases.values())
    print(f"airbases={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        coalition = item.get("coalition", "")
        category = item.get("category", "")
        x = item.get("x", "")
        z = item.get("z", "")
        print(f"  {object_id} coalition={coalition} category={category} x={x} z={z}")

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more airbases not shown")


def _print_zone_snapshot(zones: dict[str, dict[str, Any]], limit: int = 60) -> None:
    """Print a compact ZONE snapshot summary.

    :param zones: Mapping from object id to zone payload.
    :param limit: Maximum number of zones to print.
    """

    items = list(zones.values())
    print(f"zones={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        category = item.get("category", "")
        source = item.get("source", "")
        radius = item.get("radius", "")
        x = item.get("x", "")
        z = item.get("z", "")
        print(f"  {object_id} category={category} source={source} radius={radius} x={x} z={z}")

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more zones not shown")


def _print_opszone_snapshot(opszones: dict[str, dict[str, Any]], limit: int = 60) -> None:
    """Print a compact OPSZONE snapshot summary.

    :param opszones: Mapping from object id to OPSZONE payload.
    :param limit: Maximum number of OPSZONEs to print.
    """

    items = list(opszones.values())
    print(f"opszones={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        category = item.get("category", "")
        source = item.get("source", "")
        state = item.get("state", "")
        owner = item.get("owner_current_name", "")
        zone_type = item.get("zone_type", "")
        radius = item.get("zone_radius", "")
        x = item.get("x", "")
        z = item.get("z", "")
        print(f"  {object_id} category={category} source={source} state={state} owner={owner} zone_type={zone_type} radius={radius} x={x} z={z}")

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more OPSZONEs not shown")


def _print_opsgroup_snapshot(opsgroups: dict[str, dict[str, Any]], limit: int = 60) -> None:
    """Print a compact OPSGROUP snapshot summary.

    :param opsgroups: Mapping from object id to OPSGROUP payload.
    :param limit: Maximum number of OPSGROUPs to print.
    """

    items = list(opsgroups.values())
    print(f"opsgroups={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        category = item.get("category", "")
        source = item.get("source", "")
        coalition = item.get("coalition", "")
        state = item.get("state", "")
        alive = item.get("alive", "")
        active = item.get("active", "")
        current_auftrag = item.get("auftrag_current_id", "")
        queue = item.get("auftrag_queue_ids", [])
        detected = item.get("detected_group_ids", [])
        x = item.get("x", "")
        z = item.get("z", "")
        print(
            f"  {object_id} category={category} source={source} coalition={coalition} "
            f"state={state} alive={alive} active={active} auftrag={current_auftrag} "
            f"queue={len(queue)} detected_groups={len(detected)} x={x} z={z}"
        )

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more OPSGROUPs not shown")


def _print_auftrag_snapshot(auftraege: dict[str, dict[str, Any]], limit: int = 60) -> None:
    """Print a compact AUFTRAG snapshot summary.

    :param auftraege: Mapping from object id to AUFTRAG payload.
    :param limit: Maximum number of AUFTRAG objects to print.
    """

    items = list(auftraege.values())
    print(f"auftraege={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        auftrag_type = item.get("type", "")
        status = item.get("status", "")
        name = item.get("name", "")
        prio = item.get("prio", "")
        urgent = item.get("urgent", "")
        assigned = item.get("assigned_group_ids", [])
        print(f"  {object_id} type={auftrag_type} status={status} name={name} prio={prio} urgent={urgent} assigned_groups={len(assigned)}")

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more AUFTRAG objects not shown")


def _print_cohort_snapshot(cohorts: dict[str, dict[str, Any]], limit: int = 60) -> None:
    """Print a compact COHORT snapshot summary.

    :param cohorts: Mapping from object id to COHORT payload.
    :param limit: Maximum number of COHORT objects to print.
    """

    items = list(cohorts.values())
    print(f"cohorts={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        legion_id = item.get("legion_id", "")
        category = item.get("category", "")
        unit_type = item.get("unit_type", "")
        stock = item.get("stock_asset_count", "")
        spawned = item.get("spawned_asset_count", "")
        mission_types = item.get("mission_type_keys", [])
        print(
            f"  {object_id} legion={legion_id} category={category} unit_type={unit_type} "
            f"stock={stock} spawned={spawned} missions={len(mission_types)}"
        )

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more COHORT objects not shown")


def _print_legion_snapshot(legions: dict[str, dict[str, Any]], limit: int = 60) -> None:
    """Print a compact LEGION snapshot summary.

    :param legions: Mapping from object id to LEGION payload.
    :param limit: Maximum number of LEGION objects to print.
    """

    items = list(legions.values())
    print(f"legions={len(items)}")

    for item in items[:limit]:
        object_id = item.get("object_id", "")
        category = item.get("category", "")
        coalition = item.get("coalition", "")
        state = item.get("state", "")
        airbase = item.get("airbase_name", "")
        cohorts = item.get("cohort_ids", [])
        queue = item.get("auftrag_queue_ids", [])
        print(
            f"  {object_id} category={category} coalition={coalition} state={state} "
            f"airbase={airbase} cohorts={len(cohorts)} queue={len(queue)}"
        )

    if len(items) > limit:
        print(f"  ... {len(items) - limit} more LEGION objects not shown")


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
            if command == "units":
                ack = await server.snapshot_units()
                print(f"ACK: {ack}")
                _print_unit_snapshot(server.state.units)
                continue
            if command == "statics":
                ack = await server.snapshot_statics()
                print(f"ACK: {ack}")
                _print_static_snapshot(server.state.statics)
                continue
            if command == "airbases":
                ack = await server.snapshot_airbases()
                print(f"ACK: {ack}")
                _print_airbase_snapshot(server.state.airbases)
                continue
            if command == "zones":
                ack = await server.snapshot_zones()
                print(f"ACK: {ack}")
                _print_zone_snapshot(server.state.zones)
                continue
            if command == "opszones":
                ack = await server.snapshot_opszones()
                print(f"ACK: {ack}")
                _print_opszone_snapshot(server.state.opszones)
                continue
            if command == "opsgroups":
                ack = await server.snapshot_opsgroups()
                print(f"ACK: {ack}")
                _print_opsgroup_snapshot(server.state.opsgroups)
                continue
            if command == "auftraege":
                ack = await server.snapshot_auftraege()
                print(f"ACK: {ack}")
                _print_auftrag_snapshot(server.state.auftraege)
                continue
            if command == "cohorts":
                ack = await server.snapshot_cohorts()
                print(f"ACK: {ack}")
                _print_cohort_snapshot(server.state.cohorts)
                continue
            if command == "legions":
                ack = await server.snapshot_legions()
                print(f"ACK: {ack}")
                _print_legion_snapshot(server.state.legions)
                continue
            if command == "smoke":
                object_id, _, color = argument.partition(" ")
                if not object_id:
                    print("Usage: smoke <object_id> [color]")
                    continue
                ack = await server.smoke_object(object_id, color.strip() or "white")
            elif command == "smokepoint":
                parts = argument.split(maxsplit=2)
                if len(parts) < 2:
                    print("Usage: smokepoint <x> <z> [color]")
                    continue
                color = parts[2] if len(parts) >= 3 else "white"
                ack = await server.smoke_at_point(_parse_float(parts[0], "x"), _parse_float(parts[1], "z"), color)
            elif command == "mark":
                object_id, _, text = argument.partition(" ")
                if not object_id or not text:
                    print("Usage: mark <object_id> <text>")
                    continue
                ack = await server.mark_object(object_id, text)
            elif command == "markpoint":
                parts = argument.split(maxsplit=2)
                if len(parts) < 3:
                    print("Usage: markpoint <x> <z> <text>")
                    continue
                ack = await server.mark_at_point(_parse_float(parts[0], "x"), _parse_float(parts[1], "z"), parts[2])
            elif command == "all":
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
    server = MooseBridgeServer(
        args.host,
        args.port,
        Path(args.log) if args.log else None,
        reader_limit=args.reader_limit,
    )

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
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--log", default="moosebridge_raw.jsonl")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--reader-limit", type=int, default=DEFAULT_READER_LIMIT, help="Maximum incoming JSONL line size in bytes")
    parser.add_argument("--interactive", action="store_true", help="Run an interactive command console after starting the server")
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user")


if __name__ == "__main__":
    main()
