"""Protocol primitives for the MOOSE Bridge JSONL transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


MessageType = Literal["heartbeat", "event", "snapshot", "command", "ack", "error"]
CommandMode = Literal["execute", "propose"]


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    :returns: UTC timestamp with timezone suffix.
    """

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_message_id(prefix: str = "msg") -> str:
    """Create a compact message identifier.

    :param prefix: Prefix used to identify the message family.
    :returns: Identifier in the form ``prefix-shortuuid``.
    """

    return f"{prefix}-{uuid4().hex[:12]}"


@dataclass(slots=True)
class BridgeMessage:
    """Base message envelope used by the bridge protocol."""

    type: MessageType
    source: str
    id: str = field(default_factory=new_message_id)
    version: int = 1
    sequence: int | None = None
    mission_time: float | None = None
    dcs_time: float | None = None
    mission_date: str | None = None
    wall_time: str = field(default_factory=utc_now_iso)
    correlation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the message into a JSON-serializable dictionary.

        :returns: Dictionary representation without ``None`` values.
        """

        data: dict[str, Any] = {
            "version": self.version,
            "type": self.type,
            "id": self.id,
            "source": self.source,
            "wall_time": self.wall_time,
        }

        if self.sequence is not None:
            data["sequence"] = self.sequence
        if self.mission_time is not None:
            data["mission_time"] = self.mission_time
        if self.dcs_time is not None:
            data["dcs_time"] = self.dcs_time
        if self.mission_date is not None:
            data["mission_date"] = self.mission_date
        if self.correlation_id is not None:
            data["correlation_id"] = self.correlation_id
        if self.payload:
            data["payload"] = self.payload

        return data


@dataclass(slots=True)
class BridgeCommand:
    """Command message sent from Python to DCS/MOOSE."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    mode: CommandMode = "execute"
    id: str = field(default_factory=lambda: new_message_id("cmd"))

    def to_dict(self, sequence: int | None = None) -> dict[str, Any]:
        """Convert the command into the bridge JSON message format.

        :param sequence: Optional sender-local sequence number.
        :returns: JSON-serializable command dictionary.
        """

        data: dict[str, Any] = {
            "version": 1,
            "type": "command",
            "id": self.id,
            "source": "python",
            "mode": self.mode,
            "action": self.action,
            "params": self.params,
            "wall_time": utc_now_iso(),
        }
        if sequence is not None:
            data["sequence"] = sequence
        return data


@dataclass(slots=True)
class PendingCommand:
    """Tracks a command waiting for a DCS acknowledgement."""

    command: BridgeCommand
    future: Any
