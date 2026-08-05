"""Local multi-client control API for a running MOOSE Bridge daemon.

The DCS Lua bridge connects to the authoritative ``MooseBridgeServer`` port. Local
Python tools connect to this separate control port and ask the daemon to forward
DCS commands or return the current mirrored state. This avoids multiple Python
processes trying to bind the DCS-facing port.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from .clock import DcsTime
from .protocol import BridgeCommand
from .server import DcsBridgeCommandTimeoutError, DcsBridgeConnectionError, DcsMissionEndedError, MooseBridgeServer
from .state import MooseBridgeState
from .streams import close_stream_writer

LOGGER = logging.getLogger(__name__)
DEFAULT_CONTROL_PORT = 42001
DEFAULT_CONTROL_READER_LIMIT = 16 * 1024 * 1024
STATE_KINDS = (
    "groups",
    "units",
    "ammunition",
    "statics",
    "airbases",
    "zones",
    "territories",
    "objects",
    "opszones",
    "opsgroups",
    "auftraege",
    "cohorts",
    "legions",
    "commanders",
    "intels",
    "intel_contacts",
    "lost_intel_contacts",
    "intel_clusters",
    "loss_reports",
)


@dataclass(slots=True)
class ControlClientIdentity:
    """Unauthenticated identity declared by one control client instance."""

    client_id: str
    display_name: str

    def __post_init__(self) -> None:
        self.client_id = self.client_id.strip()
        self.display_name = self.display_name.strip()
        if not self.client_id or not self.display_name:
            raise ValueError("control client identity requires client_id and display_name")
        if len(self.client_id) > 128 or len(self.display_name) > 128:
            raise ValueError("control client identity fields must not exceed 128 characters")

    def to_dict(self) -> dict[str, str]:
        return {"client_id": self.client_id, "display_name": self.display_name}

    @classmethod
    def from_dict(cls, data: Any) -> "ControlClientIdentity":
        if not isinstance(data, dict):
            return cls("legacy-control-client", "Legacy control client")
        return cls(
            str(data.get("client_id") or "legacy-control-client"),
            str(data.get("display_name") or "Legacy control client"),
        )


@dataclass(slots=True)
class ControlRequest:
    """Decoded control request.

    :param id: Request correlation id.
    :param action: Control or DCS action.
    :param params: Request parameters.
    :param timeout: DCS ACK timeout in seconds.
    """

    id: str
    action: str
    params: dict[str, Any]
    timeout: float
    client: ControlClientIdentity

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControlRequest":
        """Build a control request from a dictionary.

        :param data: Decoded JSON object.
        :returns: Parsed control request.
        :raises ValueError: If mandatory fields are invalid.
        """

        action = str(data.get("action") or "").strip()
        if not action:
            raise ValueError("Control request requires action")
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        return cls(
            id=str(data.get("id") or f"ctrl-{uuid.uuid4().hex[:12]}"),
            action=action,
            params=params,
            timeout=float(data.get("timeout") or params.get("timeout") or 10.0),
            client=ControlClientIdentity.from_dict(data.get("client")),
        )


def state_payload(state: MooseBridgeState, kinds: Iterable[str] | None = None) -> dict[str, Any]:
    """Build a JSON-serializable raw state payload.

    :param state: Local state mirror.
    :param kinds: Optional raw snapshot kinds to include.
    :returns: State payload with raw maps.
    """

    selected = tuple(STATE_KINDS if kinds is None else kinds)
    payload: dict[str, Any] = {
        "connected": state.connected,
        "mission_generation": state.mission_generation,
        "mission_ended": state.mission_ended,
        "last_heartbeat": state.last_heartbeat,
        "clock": state.clock.to_dict() if state.clock else None,
        "snapshot_clocks": {kind: clock.to_dict() for kind, clock in state.snapshot_clocks.items()},
        "counts": {kind: len(getattr(state, kind, {})) for kind in STATE_KINDS},
    }
    for kind in selected:
        if kind in STATE_KINDS:
            payload[kind] = list(getattr(state, kind, {}).values())
    return payload


def apply_state_payload(state: MooseBridgeState, payload: dict[str, Any]) -> MooseBridgeState:
    """Apply a control state payload to a local state mirror.

    :param state: State mirror to update.
    :param payload: Payload returned by ``control.state``.
    :returns: Updated state mirror.
    """

    state.connected = bool(payload.get("connected", False))
    state.mission_generation = int(payload.get("mission_generation") or 0)
    state.mission_ended = bool(payload.get("mission_ended", False))
    state.last_heartbeat = payload.get("last_heartbeat") if isinstance(payload.get("last_heartbeat"), dict) else None
    clock_payload = payload.get("clock") if isinstance(payload.get("clock"), dict) else None
    snapshot_clock_payloads = payload.get("snapshot_clocks") if isinstance(payload.get("snapshot_clocks"), dict) else {}
    if clock_payload is not None:
        previous_mission_time = state.clock.mission_time if state.clock else None
        next_clock = DcsTime.from_message(clock_payload)
        if (
            previous_mission_time is not None
            and next_clock.mission_time is not None
            and next_clock.mission_time < previous_mission_time
        ):
            state.ammunition_tracker.reset()
            state.ammunition.clear()
            state.ammunition_objects.clear()
            state.lost_intel_contacts.clear()
            state.lost_intel_contact_objects.clear()
        state.clock = next_clock
    for kind in STATE_KINDS:
        items = payload.get(kind)
        if isinstance(items, list):
            state.apply_message({"type": "snapshot", "kind": kind, "payload": {kind: items}})
    state.snapshot_clocks = {
        str(kind): DcsTime.from_message(value)
        for kind, value in snapshot_clock_payloads.items()
        if isinstance(value, dict)
    }
    return state


class MooseBridgeControlServer:
    """Local JSONL control server for one running MOOSE Bridge daemon.

    :param bridge_server: Authoritative DCS-facing bridge server.
    :param host: Control interface to bind.
    :param port: Control TCP port.
    :param reader_limit: Maximum incoming JSONL line size in bytes.
    """

    def __init__(
        self,
        bridge_server: MooseBridgeServer,
        host: str = "127.0.0.1",
        port: int = DEFAULT_CONTROL_PORT,
        reader_limit: int = DEFAULT_CONTROL_READER_LIMIT,
    ) -> None:
        self.bridge_server = bridge_server
        self.host = host
        self.port = port
        self.reader_limit = reader_limit
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        """Start the local control server."""

        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            limit=self.reader_limit,
        )
        sockets = ", ".join(str(sock.getsockname()) for sock in self._server.sockets or [])
        LOGGER.info("MOOSE Bridge control server listening on %s", sockets)

    async def stop(self) -> None:
        """Stop the local control server."""

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle one local control client connection.

        :param reader: Async stream reader.
        :param writer: Async stream writer.
        """

        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                response = await self._handle_line(line.decode("utf-8").strip())
                writer.write((json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                await writer.drain()
        except (ConnectionError, OSError):
            LOGGER.debug("Control client connection was reset", exc_info=True)
        finally:
            await close_stream_writer(writer, logger=LOGGER, context="control client connection")

    async def _handle_line(self, line: str) -> dict[str, Any]:
        """Handle one control JSONL request.

        :param line: Raw JSON request line.
        :returns: JSON-serializable response object.
        """

        data: Any = None
        request: ControlRequest | None = None
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("Control request must be a JSON object")
            request = ControlRequest.from_dict(data)
            result = await self._dispatch(request)
            return {"id": request.id, "ok": True, "result": result}
        except DcsBridgeConnectionError as exc:
            request_id = data.get("id") if isinstance(data, dict) else None
            LOGGER.info("Control request interrupted by DCS reconnect: %s", exc)
            return {"id": request_id, "ok": False, "error": str(exc)}
        except DcsBridgeCommandTimeoutError as exc:
            request_id = data.get("id") if isinstance(data, dict) else None
            LOGGER.warning("Control request timed out waiting for DCS ACK: %s", exc)
            return {"id": request_id, "ok": False, "error": str(exc)}
        except DcsMissionEndedError as exc:
            request_id = data.get("id") if isinstance(data, dict) else None
            LOGGER.info("Control request interrupted by mission end: %s", exc)
            return {"id": request_id, "ok": False, "error": str(exc)}
        except TimeoutError:
            request_id = data.get("id") if isinstance(data, dict) else None
            action = request.action if request is not None else "control request"
            timeout = request.timeout if request is not None else 10.0
            error = f"{action} timed out after {timeout:g} seconds"
            LOGGER.info("Control request timed out: %s", error)
            return {"id": request_id, "ok": False, "error": error}
        except Exception as exc:
            request_id = None
            try:
                if isinstance(data, dict):
                    request_id = data.get("id")
            except Exception:
                request_id = None
            LOGGER.exception("Control request failed")
            return {"id": request_id, "ok": False, "error": str(exc)}

    async def _dispatch(self, request: ControlRequest) -> dict[str, Any]:
        """Dispatch a parsed control request.

        :param request: Parsed control request.
        :returns: Response result payload.
        """

        action = request.action
        if action == "control.status":
            return {**state_payload(self.bridge_server.state, kinds=()), "client": request.client.to_dict()}
        if action == "control.state":
            kinds = request.params.get("kinds")
            if isinstance(kinds, str):
                kinds = [kinds]
            if not isinstance(kinds, list):
                kinds = list(STATE_KINDS)
            return state_payload(self.bridge_server.state, kinds=[str(kind) for kind in kinds])
        if action == "control.snapshots":
            actions = request.params.get("actions")
            if not isinstance(actions, list):
                raise ValueError("control.snapshots requires params.actions list")
            acks = []
            for snapshot_action in actions:
                ack = await self.bridge_server.send_command(BridgeCommand(action=str(snapshot_action), params={}), timeout=request.timeout)
                acks.append(ack)
                await asyncio.sleep(0.05)
            return {"acks": acks, "state": state_payload(self.bridge_server.state)}
        if action == "control.command":
            dcs_action = str(request.params.get("action") or "").strip()
            if not dcs_action:
                raise ValueError("control.command requires params.action")
            dcs_params = request.params.get("params") if isinstance(request.params.get("params"), dict) else {}
            ack = await self.bridge_server.send_command(BridgeCommand(action=dcs_action, params=dcs_params), timeout=request.timeout)
            return {"ack": ack, "state": state_payload(self.bridge_server.state)}
        if action == "control.event.wait":
            event_name = str(request.params.get("event") or "").strip()
            if not event_name:
                raise ValueError("control.event.wait requires params.event")
            filters = request.params.get("filters") if isinstance(request.params.get("filters"), dict) else {}
            after_id = str(request.params.get("after_id") or "") or None
            event = await self.bridge_server.wait_for_event(event_name, filters=filters, timeout=request.timeout, after_id=after_id)
            return {"event": event}
        if action == "control.event.cursor":
            return {"event_id": await self.bridge_server.event_cursor()}
        if action == "control.events.query":
            event_name = str(request.params.get("event") or "*").strip() or "*"
            filters = request.params.get("filters") if isinstance(request.params.get("filters"), dict) else {}
            after_id = str(request.params.get("after_id") or "") or None
            return await self.bridge_server.query_events(event_name, filters=filters, after_id=after_id)
        if action == "control.audit.append":
            record_type = str(request.params.get("record_type") or "").strip()
            payload = request.params.get("payload")
            if not record_type or not isinstance(payload, dict):
                raise ValueError("control.audit.append requires record_type and payload object")
            record = await self.bridge_server.append_audit_record(
                record_type,
                payload,
                client_identity=request.client.to_dict(),
            )
            return {"record": record}
        if action == "control.audit.query":
            records = await self.bridge_server.query_audit_records(
                record_type=str(request.params.get("record_type") or "") or None,
                plan_id=str(request.params.get("plan_id") or "") or None,
                attempt_id=str(request.params.get("attempt_id") or "") or None,
                latest_attempts=bool(request.params.get("latest_attempts", False)),
            )
            return {"records": list(records)}

        ack = await self.bridge_server.send_command(BridgeCommand(action=action, params=request.params), timeout=request.timeout)
        return {"ack": ack, "state": state_payload(self.bridge_server.state)}


class MooseBridgeControlClient:
    """JSONL client for the local MOOSE Bridge control server.

    :param host: Control server host.
    :param port: Control server TCP port.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_CONTROL_PORT,
        *,
        client_id: str | None = None,
        display_name: str = "MooseBridge Python client",
    ) -> None:
        self.host = host
        self.port = port
        self.state = MooseBridgeState()
        self.identity = ControlClientIdentity(
            client_id or f"client-{uuid.uuid4().hex[:12]}",
            display_name,
        )

    @staticmethod
    def _response_timeout(action: str, params: dict[str, Any], timeout: float) -> float:
        """Return a client-side response timeout for one control request."""

        if action == "control.snapshots":
            actions = params.get("actions")
            if isinstance(actions, list):
                action_count = max(1, len(actions))
                return action_count * timeout + max(0, action_count - 1) * 0.1 + 1.0
        return timeout + 1.0

    async def request(self, action: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
        """Send one control request and return its result.

        :param action: Control or DCS action.
        :param params: Request parameters.
        :param timeout: Request timeout in seconds.
        :returns: Result payload.
        :raises RuntimeError: If the control server rejects the request.
        """

        request_params = params or {}
        reader, writer = await asyncio.open_connection(self.host, self.port, limit=DEFAULT_CONTROL_READER_LIMIT)
        try:
            request = {
                "id": f"ctrl-{uuid.uuid4().hex[:12]}",
                "action": action,
                "params": request_params,
                "timeout": timeout,
                "client": self.identity.to_dict(),
            }
            writer.write((json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=self._response_timeout(action, request_params, timeout))
            if not line:
                raise RuntimeError("Control server closed the connection without response")
            response = json.loads(line.decode("utf-8"))
            if not response.get("ok"):
                raise RuntimeError(str(response.get("error") or response))
            result = response.get("result") if isinstance(response.get("result"), dict) else {}
            state_data = result.get("state") if isinstance(result.get("state"), dict) else None
            if state_data is not None:
                apply_state_payload(self.state, state_data)
            elif action == "control.state":
                apply_state_payload(self.state, result)
            return result
        finally:
            await close_stream_writer(writer, logger=LOGGER, context="control server connection")

    async def status(self, timeout: float = 5.0) -> dict[str, Any]:
        """Return daemon status.

        :param timeout: Request timeout in seconds.
        :returns: Status payload.
        """

        return await self.request("control.status", timeout=timeout)

    async def get_state(self, kinds: Iterable[str] | None = None, timeout: float = 10.0) -> MooseBridgeState:
        """Fetch current daemon state into the local state mirror.

        :param kinds: Optional state kinds to fetch.
        :param timeout: Request timeout in seconds.
        :returns: Updated local state mirror.
        """

        params: dict[str, Any] = {}
        if kinds is not None:
            params["kinds"] = list(kinds)
        result = await self.request("control.state", params=params, timeout=timeout)
        apply_state_payload(self.state, result)
        return self.state

    async def request_snapshots(self, actions: Iterable[str], timeout: float = 10.0) -> MooseBridgeState:
        """Request DCS snapshots via the daemon and update local state.

        :param actions: Snapshot command actions.
        :param timeout: Per-command DCS ACK timeout in seconds.
        :returns: Updated local state mirror.
        """

        await self.request("control.snapshots", params={"actions": list(actions)}, timeout=timeout)
        return self.state

    async def send_dcs_command(self, action: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
        """Forward a DCS command through the daemon.

        :param action: DCS bridge command action.
        :param params: DCS command parameters.
        :param timeout: DCS ACK timeout in seconds.
        :returns: DCS ACK payload.
        """

        result = await self.request("control.command", params={"action": action, "params": params or {}}, timeout=timeout)
        ack = result.get("ack") if isinstance(result.get("ack"), dict) else {}
        if not ack.get("ok", False):
            raise RuntimeError(str(ack.get("error") or ack))
        return ack

    async def append_audit_record(
        self,
        record_type: str,
        payload: dict[str, Any],
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Append one semantic record to the daemon audit store."""

        result = await self.request(
            "control.audit.append",
            params={"record_type": record_type, "payload": payload},
            timeout=timeout,
        )
        return result.get("record") if isinstance(result.get("record"), dict) else {}

    async def query_audit_records(
        self,
        *,
        record_type: str | None = None,
        plan_id: str | None = None,
        attempt_id: str | None = None,
        latest_attempts: bool = False,
        timeout: float = 10.0,
    ) -> tuple[dict[str, Any], ...]:
        """Query semantic audit records from the daemon store."""

        result = await self.request(
            "control.audit.query",
            params={
                "record_type": record_type,
                "plan_id": plan_id,
                "attempt_id": attempt_id,
                "latest_attempts": latest_attempts,
            },
            timeout=timeout,
        )
        records = result.get("records") if isinstance(result.get("records"), list) else []
        return tuple(record for record in records if isinstance(record, dict))

    async def wait_for_event(
        self,
        event_name: str,
        filters: dict[str, Any] | None = None,
        timeout: float = 600.0,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait for one daemon event matching name and filters."""

        result = await self.request("control.event.wait", params={"event": event_name, "filters": filters or {}, "after_id": after_id}, timeout=timeout)
        event = result.get("event") if isinstance(result.get("event"), dict) else {}
        if not event:
            raise RuntimeError("Control server returned no event")
        self.state.apply_message(event)
        return event

    async def event_cursor(self, timeout: float = 10.0) -> str | None:
        """Return the id of the latest event retained by the daemon."""

        result = await self.request("control.event.cursor", timeout=timeout)
        return str(result.get("event_id") or "") or None

    async def query_events(
        self,
        event_name: str = "*",
        filters: dict[str, Any] | None = None,
        after_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Query retained daemon events in chronological order."""

        result = await self.request(
            "control.events.query",
            params={"event": event_name, "filters": filters or {}, "after_id": after_id},
            timeout=timeout,
        )
        return result
