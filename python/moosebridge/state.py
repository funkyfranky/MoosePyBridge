"""State mirror for DCS/MOOSE objects observed by the Python bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from .models import Auftrag, OpsGroup, OpsZone


T = TypeVar("T")


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
    opszones: dict[str, dict[str, Any]] = field(default_factory=dict)
    opsgroups: dict[str, dict[str, Any]] = field(default_factory=dict)
    auftraege: dict[str, dict[str, Any]] = field(default_factory=dict)
    opszone_objects: dict[str, OpsZone] = field(default_factory=dict)
    opsgroup_objects: dict[str, OpsGroup] = field(default_factory=dict)
    auftrag_objects: dict[str, Auftrag] = field(default_factory=dict)
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

    def opszone(self, object_id: str) -> OpsZone | None:
        """Return a typed OPSZONE by object id.

        :param object_id: Stable bridge object id such as ``OPSZONE:Town Fight``.
        :returns: Typed OPSZONE or ``None``.
        """

        return self.opszone_objects.get(object_id)

    def opsgroup(self, object_id: str) -> OpsGroup | None:
        """Return a typed OPSGROUP by object id.

        :param object_id: Stable bridge object id such as ``OPSGROUP:Aerial-1``.
        :returns: Typed OPSGROUP or ``None``.
        """

        return self.opsgroup_objects.get(object_id)

    def auftrag(self, object_id: str) -> Auftrag | None:
        """Return a typed AUFTRAG by object id.

        :param object_id: Stable bridge object id such as ``AUFTRAG:1``.
        :returns: Typed AUFTRAG or ``None``.
        """

        return self.auftrag_objects.get(object_id)

    def current_auftrag_for_group(self, opsgroup_id: str) -> Auftrag | None:
        """Return the current AUFTRAG assigned to an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Current typed AUFTRAG or ``None``.
        """

        group = self.opsgroup(opsgroup_id)
        if not group or not group.auftrag_current_id:
            return None
        return self.auftrag(group.auftrag_current_id)

    def queued_auftraege_for_group(self, opsgroup_id: str) -> list[Auftrag]:
        """Return queued AUFTRAG objects for an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Typed AUFTRAG objects present in the mirrored state.
        """

        group = self.opsgroup(opsgroup_id)
        if not group:
            return []
        return [auftrag for auftrag_id in group.auftrag_queue_ids if (auftrag := self.auftrag(auftrag_id))]

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
        elif kind == "opszones":
            items = payload.get("opszones", [])
            self.opszones = self._index_objects(items)
            self.opszone_objects = self._index_typed_objects(items, OpsZone.from_payload)
        elif kind == "opsgroups":
            items = payload.get("opsgroups", [])
            self.opsgroups = self._index_objects(items)
            self.opsgroup_objects = self._index_typed_objects(items, OpsGroup.from_payload)
        elif kind == "auftraege":
            items = payload.get("auftraege", [])
            self.auftraege = self._index_objects(items)
            self.auftrag_objects = self._index_typed_objects(items, Auftrag.from_payload)

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

    @staticmethod
    def _index_typed_objects(items: list[dict[str, Any]], factory: Callable[[dict[str, Any]], T]) -> dict[str, T]:
        """Index a list of protocol objects as typed models.

        :param items: Objects received from DCS.
        :param factory: Function converting one payload into a typed model.
        :returns: Mapping from object id to typed model.
        """

        indexed: dict[str, T] = {}
        for item in items:
            object_id = item.get("object_id")
            if object_id:
                indexed[str(object_id)] = factory(item)
        return indexed
