"""State mirror for DCS/MOOSE objects observed by the Python bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MooseObjectIdentity:
    """Stable object identity shared between DCS/MOOSE and Python."""

    object_id: str
    dcs_name: str
    object_type: str
    category: str | None = None
    coalition: str | None = None
    birth_time: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MooseObjectIdentity":
        """Create an identity from a protocol dictionary.

        :param data: Dictionary received from DCS.
        :returns: Parsed identity.
        """

        return cls(
            object_id=str(data.get("object_id", "")),
            dcs_name=str(data.get("dcs_name", "")),
            object_type=str(data.get("object_type", "")),
            category=data.get("category"),
            coalition=data.get("coalition"),
            birth_time=data.get("birth_time"),
        )


@dataclass(slots=True)
class MooseBridgeState:
    """Stateful Python mirror of the DCS/MOOSE world."""

    connected: bool = False
    last_heartbeat: dict[str, Any] | None = None
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    units: dict[str, dict[str, Any]] = field(default_factory=dict)
    statics: dict[str, dict[str, Any]] = field(default_factory=dict)
    airbases: dict[str, dict[str, Any]] = field(default_factory=dict)
    zones: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def apply_message(self, message: dict[str, Any]) -> None:
        """Apply an incoming DCS message to the local state mirror.

        :param message: Decoded protocol message.
        """

        message_type = message.get("type")

        if message_type == "heartbeat":
            self.connected = True
            self.last_heartbeat = message
            return

        if message_type == "event":
            self.events.append(message)
            if len(self.events) > 10_000:
                del self.events[:1_000]
            return

        if message_type == "snapshot":
            self._apply_snapshot(message)

    def _apply_snapshot(self, message: dict[str, Any]) -> None:
        """Apply a snapshot message to the local state mirror.

        :param message: Decoded snapshot message.
        """

        kind = message.get("kind")
        payload = message.get("payload") or {}

        if kind == "groups":
            self.groups = self._index_objects(payload.get("groups", []))
        elif kind == "units":
            self.units = self._index_objects(payload.get("units", []))
        elif kind == "statics":
            self.statics = self._index_objects(payload.get("statics", []))
        elif kind == "airbases":
            self.airbases = self._index_objects(payload.get("airbases", []))
        elif kind == "zones":
            self.zones = self._index_objects(payload.get("zones", []))

    @staticmethod
    def _index_objects(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Index a list of protocol objects by ``object_id``.

        :param items: Objects received from DCS.
        :returns: Mapping from object id to object payload.
        """

        indexed: dict[str, dict[str, Any]] = {}
        for item in items:
            object_id = item.get("object_id")
            if object_id:
                indexed[str(object_id)] = item
        return indexed
