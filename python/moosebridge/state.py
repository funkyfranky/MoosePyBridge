"""State mirror for DCS/MOOSE objects observed by the Python bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from .auftrag_specs import canonical_mission_type, get_auftrag_type_spec, platform_categories_match
from .clock import DcsTime
from .legions import Cohort, Legion
from .models import Auftrag, Intel, IntelCluster, IntelContact, OpsGroup, OpsZone
from .outcomes import AuftragOutcome


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
    clock: DcsTime | None = None
    snapshot_clocks: dict[str, DcsTime] = field(default_factory=dict)
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    units: dict[str, dict[str, Any]] = field(default_factory=dict)
    statics: dict[str, dict[str, Any]] = field(default_factory=dict)
    airbases: dict[str, dict[str, Any]] = field(default_factory=dict)
    zones: dict[str, dict[str, Any]] = field(default_factory=dict)
    opszones: dict[str, dict[str, Any]] = field(default_factory=dict)
    opsgroups: dict[str, dict[str, Any]] = field(default_factory=dict)
    auftraege: dict[str, dict[str, Any]] = field(default_factory=dict)
    cohorts: dict[str, dict[str, Any]] = field(default_factory=dict)
    legions: dict[str, dict[str, Any]] = field(default_factory=dict)
    intels: dict[str, dict[str, Any]] = field(default_factory=dict)
    intel_contacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    intel_clusters: dict[str, dict[str, Any]] = field(default_factory=dict)
    opszone_objects: dict[str, OpsZone] = field(default_factory=dict)
    opsgroup_objects: dict[str, OpsGroup] = field(default_factory=dict)
    auftrag_objects: dict[str, Auftrag] = field(default_factory=dict)
    cohort_objects: dict[str, Cohort] = field(default_factory=dict)
    legion_objects: dict[str, Legion] = field(default_factory=dict)
    intel_objects: dict[str, Intel] = field(default_factory=dict)
    intel_contact_objects: dict[str, IntelContact] = field(default_factory=dict)
    intel_cluster_objects: dict[str, IntelCluster] = field(default_factory=dict)
    auftrag_outcomes: dict[str, AuftragOutcome] = field(default_factory=dict)
    auftrag_outcome_history: dict[str, list[AuftragOutcome]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def apply_message(self, message: dict[str, Any]) -> None:
        """Apply an incoming DCS message to the local state mirror.

        :param message: Decoded protocol message.
        """

        message_type = message.get("type")

        if message.get("source") == "dcs" or any(key in message for key in ("mission_time", "dcs_time")):
            self.clock = DcsTime.from_message(message)

        if message_type == "heartbeat":
            self.connected = True
            self.last_heartbeat = message
            return

        if message_type == "event":
            self.events.append(message)
            if len(self.events) > 10_000:
                del self.events[:1_000]
            self._apply_event(message)
            return

        if message_type == "snapshot":
            self._apply_snapshot(message)

    def opszone(self, object_id: str) -> OpsZone | None:
        """Return a typed OPSZONE by object id.

        :param object_id: Stable bridge object id such as ``OPSZONE:Town Fight``.
        :returns: Typed OPSZONE or ``None``.
        """

        return self.opszone_objects.get(object_id)

    def intel(self, object_id: str) -> Intel | None:
        """Return a typed INTEL object by object id.

        :param object_id: Stable bridge object id such as ``INTEL:BlueIntel``.
        :returns: Typed INTEL object or ``None``.
        """

        return self.intel_objects.get(object_id)

    def intel_contact(self, object_id: str) -> IntelContact | None:
        """Return a typed INTEL contact by object id."""

        return self.intel_contact_objects.get(object_id)

    def intel_cluster(self, object_id: str) -> IntelCluster | None:
        """Return a typed INTEL cluster by object id."""

        return self.intel_cluster_objects.get(object_id)

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

    def auftrag_outcome(self, object_id: str) -> AuftragOutcome | None:
        """Return the latest evaluated outcome for an AUFTRAG.

        :param object_id: Stable AUFTRAG object id such as ``AUFTRAG:1``.
        :returns: Latest outcome or ``None``.
        """

        return self.auftrag_outcomes.get(object_id)

    def auftrag_outcomes_for(self, object_id: str) -> list[AuftragOutcome]:
        """Return the recorded outcome history for an AUFTRAG.

        :param object_id: Stable AUFTRAG object id such as ``AUFTRAG:1``.
        :returns: Outcome history entries.
        """

        return list(self.auftrag_outcome_history.get(object_id, []))

    def cohort(self, object_id: str) -> Cohort | None:
        """Return a typed COHORT by object id.

        :param object_id: Stable bridge object id such as ``COHORT:F-18 Laage``.
        :returns: Typed COHORT or ``None``.
        """

        return self.cohort_objects.get(object_id)

    def legion(self, object_id: str) -> Legion | None:
        """Return a typed LEGION by object id.

        :param object_id: Stable bridge object id such as ``LEGION:US AW Batumi``.
        :returns: Typed LEGION or ``None``.
        """

        return self.legion_objects.get(object_id)

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

    def queued_auftraege_for_legion(self, legion_id: str) -> list[Auftrag]:
        """Return queued AUFTRAG objects for a LEGION.

        :param legion_id: Stable LEGION object id.
        :returns: Typed AUFTRAG objects present in the mirrored state.
        """

        legion = self.legion(legion_id)
        if not legion:
            return []
        return [auftrag for auftrag_id in legion.auftrag_queue_ids if (auftrag := self.auftrag(auftrag_id))]

    def cohorts_for_legion(self, legion_id: str) -> list[Cohort]:
        """Return typed COHORT objects belonging to a LEGION.

        :param legion_id: Stable LEGION object id.
        :returns: COHORT objects present in the mirrored state.
        """

        return [cohort for cohort in self.cohort_objects.values() if cohort.legion_id == legion_id]

    def contacts_for_intel(self, intel_id: str) -> list[IntelContact]:
        """Return typed contacts belonging to an INTEL object."""

        return [contact for contact in self.intel_contact_objects.values() if contact.intel_id == intel_id]

    def clusters_for_intel(self, intel_id: str) -> list[IntelCluster]:
        """Return typed clusters belonging to an INTEL object."""

        return [cluster for cluster in self.intel_cluster_objects.values() if cluster.intel_id == intel_id]

    def cohorts_matching_performer_categories(self, performer_categories: tuple[str, ...] | list[str]) -> list[Cohort]:
        """Return COHORTs matching required performer platform categories.

        :param performer_categories: Required platform categories such as ``AIR`` or ``GROUND``.
        :returns: COHORT objects with compatible platform categories.
        """

        return [
            cohort
            for cohort in self.cohort_objects.values()
            if platform_categories_match(cohort.performer_categories, performer_categories)
        ]

    def cohorts_capable_of(self, mission_type: str) -> list[Cohort]:
        """Return COHORTs that advertise support for a mission type and platform category.

        :param mission_type: Mission type such as ``BAI`` or ``Orbit``.
        :returns: COHORT objects with matching mission type and performer category.
        """

        key = canonical_mission_type(mission_type)
        spec = get_auftrag_type_spec(key)
        cohorts = [cohort for cohort in self.cohort_objects.values() if key in cohort.mission_type_keys]
        if spec is None:
            return cohorts
        return [
            cohort
            for cohort in cohorts
            if platform_categories_match(cohort.performer_categories, spec.performer_categories)
        ]

    def cohorts_with_stock_for_mission_type(self, mission_type: str) -> list[Cohort]:
        """Return mission-capable COHORTs with at least one stocked asset.

        :param mission_type: Mission type such as ``BAI`` or ``Orbit``.
        :returns: Mission-capable COHORT objects with ``stock_asset_count > 0``.
        """

        return [
            cohort
            for cohort in self.cohorts_capable_of(mission_type)
            if cohort.stock_asset_count is not None and cohort.stock_asset_count > 0
        ]

    def _apply_snapshot(self, message: dict[str, Any]) -> None:
        """Apply a snapshot message to the local state mirror.

        :param message: Decoded snapshot message.
        """

        kind = message.get("kind")
        payload = message.get("payload") or {}
        if isinstance(kind, str) and self.clock is not None:
            self.snapshot_clocks[kind] = self.clock

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
        elif kind == "objects":
            self.objects = self._index_objects(payload.get("objects", []))
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
            for item in items:
                self._record_auftrag_outcome(item)
        elif kind == "cohorts":
            items = payload.get("cohorts", [])
            self.cohorts = self._index_objects(items)
            self.cohort_objects = self._index_typed_objects(items, Cohort.from_payload)
        elif kind == "legions":
            items = payload.get("legions", [])
            self.legions = self._index_objects(items)
            self.legion_objects = self._index_typed_objects(items, Legion.from_payload)
        elif kind == "intels":
            items = payload.get("intels", [])
            self.intels = self._index_objects(items)
            self.intel_objects = self._index_typed_objects(items, Intel.from_payload)
        elif kind == "intel_contacts":
            items = payload.get("intel_contacts", [])
            self.intel_contacts = self._index_objects(items)
            self.intel_contact_objects = self._index_typed_objects(items, IntelContact.from_payload)
        elif kind == "intel_clusters":
            items = payload.get("intel_clusters", [])
            self.intel_clusters = self._index_objects(items)
            self.intel_cluster_objects = self._index_typed_objects(items, IntelCluster.from_payload)

    def _apply_event(self, message: dict[str, Any]) -> None:
        """Apply an incoming event to derived state indexes."""

        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        event_name = str(message.get("event") or payload.get("event") or "")
        if event_name.startswith("intel."):
            self._apply_intel_event(event_name, payload)
            return
        if event_name != "auftrag.evaluated":
            return

        auftrag_payload = payload.get("auftrag") if isinstance(payload.get("auftrag"), dict) else {}
        snapshot = dict(auftrag_payload)
        snapshot.setdefault("object_id", payload.get("auftrag_id"))
        snapshot.setdefault("type", payload.get("auftrag_type"))
        snapshot.setdefault("status", payload.get("status"))
        snapshot.setdefault("summary", payload.get("summary"))
        self._record_auftrag_outcome(snapshot)

    def _apply_intel_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Apply INTEL contact and cluster events to the local typed indexes."""

        contact_payload = payload.get("contact") if isinstance(payload.get("contact"), dict) else None
        cluster_payload = payload.get("cluster") if isinstance(payload.get("cluster"), dict) else None
        if contact_payload:
            object_id = str(contact_payload.get("object_id") or "")
            if object_id:
                if event_name == "intel.lost_contact":
                    self.intel_contacts.pop(object_id, None)
                    self.intel_contact_objects.pop(object_id, None)
                else:
                    self.intel_contacts[object_id] = contact_payload
                    self.intel_contact_objects[object_id] = IntelContact.from_payload(contact_payload)
        if cluster_payload:
            object_id = str(cluster_payload.get("object_id") or "")
            if object_id:
                if event_name == "intel.lost_cluster":
                    self.intel_clusters.pop(object_id, None)
                    self.intel_cluster_objects.pop(object_id, None)
                else:
                    self.intel_clusters[object_id] = cluster_payload
                    self.intel_cluster_objects[object_id] = IntelCluster.from_payload(cluster_payload)

    def _record_auftrag_outcome(self, snapshot: dict[str, Any]) -> None:
        """Record an evaluated AUFTRAG outcome if a summary is present.

        Duplicate consecutive outcomes are ignored so polling the same evaluated
        AUFTRAG does not grow history unboundedly.

        :param snapshot: Raw AUFTRAG snapshot.
        """

        if not isinstance(snapshot.get("summary"), dict):
            return
        try:
            outcome = AuftragOutcome.from_snapshot(snapshot)
        except ValueError:
            return
        if not outcome.auftrag_id:
            return

        self.auftrag_outcomes[outcome.auftrag_id] = outcome
        history = self.auftrag_outcome_history.setdefault(outcome.auftrag_id, [])
        if not history or history[-1] != outcome:
            history.append(outcome)

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
