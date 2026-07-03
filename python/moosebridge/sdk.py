"""Small local SDK wrapper for embedding MOOSE Bridge commands in Python tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import math
from typing import Any

from .auftrag_specs import auftrag_action_suffix
from .intents import auftrag_command_params_from_recommendation
from .models import Auftrag, OpsGroup, OpsZone
from .outcomes import AuftragOutcome
from .protocol import BridgeCommand
from .server import MooseBridgeServer
from .state import MooseBridgeState

SMOKE_COLORS = {"red", "green", "blue", "orange", "white"}
COORDINATE_FORMATS = {"xyz", "ll", "latlon", "latlong", "mgrs", "all"}
DRAW_ZONE_COLORS = {"red", "green", "blue", "yellow", "orange", "white", "black", "grey", "gray"}
DRAW_ZONE_COALITIONS = {"all", "neutral", "red", "blue", "-1", "0", "1", "2"}
DRAW_ZONE_LINE_TYPES = {
    "none": 0,
    "solid": 1,
    "dashed": 2,
    "dotted": 3,
    "dotdash": 4,
    "dot-dash": 4,
    "dot_dash": 4,
    "longdash": 5,
    "long-dash": 5,
    "long_dash": 5,
    "twodash": 6,
    "two-dash": 6,
    "two_dash": 6,
}
SNAPSHOT_KINDS = {
    "groups",
    "units",
    "statics",
    "airbases",
    "zones",
    "objects",
    "opszones",
    "opsgroups",
    "auftraege",
    "legions",
    "cohorts",
}


@dataclass(slots=True, frozen=True)
class CoordinateResult:
    """Resolved object coordinates returned by ``object.coords``."""

    object_id: str
    format: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    mgrs: str | None = None
    raw: dict[str, Any] | None = None
    ack: dict[str, Any] | None = None

    @classmethod
    def from_ack(cls, ack: dict[str, Any]) -> "CoordinateResult":
        """Build a coordinate result from a successful ACK."""

        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        return cls(
            object_id=str(result.get("object_id") or ""),
            format=str(result.get("format") or "xyz"),
            x=_optional_float(result.get("x")),
            y=_optional_float(result.get("y")),
            z=_optional_float(result.get("z")),
            latitude=_optional_float(result.get("latitude")),
            longitude=_optional_float(result.get("longitude")),
            mgrs=str(result.get("mgrs")) if result.get("mgrs") is not None else None,
            raw=result,
            ack=ack,
        )


@dataclass(slots=True, frozen=True)
class DistanceResult:
    """Distance between two resolved DCS objects."""

    object_id_a: str
    object_id_b: str
    distance_m: float
    distance_km: float
    distance_nm: float
    raw: dict[str, Any] | None = None
    ack: dict[str, Any] | None = None

    @classmethod
    def from_ack(cls, ack: dict[str, Any]) -> "DistanceResult":
        """Build a distance result from a successful ACK."""

        result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
        return cls(
            object_id_a=str(result.get("object_id_a") or ""),
            object_id_b=str(result.get("object_id_b") or ""),
            distance_m=float(result.get("distance_m") or 0.0),
            distance_km=float(result.get("distance_km") or 0.0),
            distance_nm=float(result.get("distance_nm") or 0.0),
            raw=result,
            ack=ack,
        )


@dataclass(slots=True, frozen=True)
class NearestResult:
    """One snapshot item ranked by distance from a target object."""

    object_id: str
    distance_m: float
    distance_nm: float
    item: dict[str, Any]


@dataclass(slots=True, frozen=True)
class AuftragEvent:
    """One AUFTRAG FSM event emitted by the Lua bridge."""

    event: str
    auftrag_id: str
    status: str | None = None
    from_state: str | None = None
    to_state: str | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_message(cls, message: dict[str, Any]) -> "AuftragEvent":
        """Build an AUFTRAG event from a bridge event message."""

        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        return cls(
            event=str(message.get("event") or payload.get("event") or ""),
            auftrag_id=str(payload.get("auftrag_id") or ""),
            status=str(payload.get("status")) if payload.get("status") is not None else None,
            from_state=str(payload.get("from")) if payload.get("from") is not None else None,
            to_state=str(payload.get("to")) if payload.get("to") is not None else None,
            raw=message,
        )

    def __str__(self) -> str:
        """Return a compact status line."""

        parts = [self.auftrag_id or "<unknown>", self.event]
        if self.status:
            parts.append(f"status={self.status}")
        if self.from_state or self.to_state:
            parts.append(f"{self.from_state or '?'}->{self.to_state or '?'}")
        return " ".join(parts)


class AuftragCommand:
    """Python-side AUFTRAG description that can be sent through the bridge."""

    mission_type = ""

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this AUFTRAG."""

        return {}


@dataclass(slots=True, frozen=True)
class AuftragBAI(AuftragCommand):
    """Battlefield air interdiction AUFTRAG."""

    target: str
    altitude_ft: float | None = None
    mission_type = "BAI"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this BAI AUFTRAG."""

        return clean_params({"target": self.target, "altitude_ft": self.altitude_ft})


@dataclass(slots=True, frozen=True)
class AuftragBOMBING(AuftragCommand):
    """Bombing AUFTRAG against a coordinate or object target."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    altitude_ft: float | None = None
    engage_weapon_type: int | None = None
    divebomb: bool | None = None
    mission_type = "BOMBING"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this BOMBING AUFTRAG."""

        return clean_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "altitude_ft": self.altitude_ft,
                "engage_weapon_type": self.engage_weapon_type,
                "divebomb": self.divebomb,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragARTY(AuftragCommand):
    """Artillery fire-at-point AUFTRAG."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    nshots: float | None = None
    radius_m: float | None = None
    mission_type = "ARTY"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this ARTY AUFTRAG."""

        return clean_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "nshots": self.nshots,
                "radius_m": self.radius_m,
            }
        )


Auftrag_BAI = AuftragBAI
Auftrag_BOMBING = AuftragBOMBING
Auftrag_ARTY = AuftragARTY


def _optional_float(value: Any) -> float | None:
    """Return a float or ``None`` for absent/non-numeric values."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class MooseBridgeCommandError(RuntimeError):
    """Raised when DCS rejects a bridge command.

    :param ack: ACK payload returned by DCS.
    """

    def __init__(self, ack: dict[str, Any]) -> None:
        self.ack = ack
        super().__init__(str(ack.get("error") or "DCS command failed"))


class MooseBridgeAuftragTimeoutError(TimeoutError):
    """Raised when an AUFTRAG does not produce an evaluation summary in time."""


class MooseBridgeAuftragNotFoundError(RuntimeError):
    """Raised when an AUFTRAG is never observed in snapshots."""


def require_ok(ack: dict[str, Any]) -> dict[str, Any]:
    """Validate that a DCS ACK accepted the command.

    :param ack: ACK payload returned by DCS.
    :returns: The original ACK payload if it is successful.
    :raises MooseBridgeCommandError: If DCS returned ``ok=false``.
    """

    if not ack.get("ok", False):
        raise MooseBridgeCommandError(ack)
    return ack


def validate_smoke_color(color: str) -> str:
    """Validate and normalize a smoke color.

    :param color: Requested smoke color.
    :returns: Lower-case smoke color.
    :raises ValueError: If the color is unsupported.
    """

    normalized = color.lower().strip()
    if normalized not in SMOKE_COLORS:
        raise ValueError(f"Unsupported smoke color: {color!r}. Expected one of {sorted(SMOKE_COLORS)}")
    return normalized


def validate_coordinate_format(format: str) -> str:
    """Validate and normalize a coordinate output format."""

    normalized = format.lower().strip()
    if normalized not in COORDINATE_FORMATS:
        raise ValueError(f"Unsupported coordinate format: {format!r}. Expected one of {sorted(COORDINATE_FORMATS)}")
    if normalized in {"latlon", "latlong"}:
        return "ll"
    return normalized


def validate_draw_zone_color(color: str | None) -> str | None:
    """Validate and normalize an optional DrawZone color name."""

    if color is None:
        return None
    normalized = color.lower().strip()
    if normalized not in DRAW_ZONE_COLORS:
        raise ValueError(f"Unsupported DrawZone color: {color!r}. Expected one of {sorted(DRAW_ZONE_COLORS)}")
    return normalized


def validate_draw_zone_coalition(coalition: str | int) -> str | int:
    """Validate a DrawZone coalition value."""

    if isinstance(coalition, int):
        if coalition in {-1, 0, 1, 2}:
            return coalition
        raise ValueError("DrawZone coalition integer must be one of -1, 0, 1, 2")
    normalized = coalition.lower().strip()
    if normalized not in DRAW_ZONE_COALITIONS:
        raise ValueError(f"Unsupported DrawZone coalition: {coalition!r}. Expected one of {sorted(DRAW_ZONE_COALITIONS)}")
    return normalized


def normalize_draw_zone_line_type(line_type: str | int | None) -> int | None:
    """Normalize an optional MOOSE DrawZone line type."""

    if line_type is None:
        return None
    if isinstance(line_type, int):
        value = line_type
    else:
        key = line_type.lower().strip()
        if key in DRAW_ZONE_LINE_TYPES:
            value = DRAW_ZONE_LINE_TYPES[key]
        else:
            try:
                value = int(key)
            except ValueError as exc:
                raise ValueError(f"Unsupported DrawZone line type: {line_type!r}") from exc
    if value < 0 or value > 6:
        raise ValueError("DrawZone line type must be in range 0..6")
    return value


def clean_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return params without ``None`` values."""

    return {key: value for key, value in params.items() if value is not None}


def point_from_item(item: dict[str, Any]) -> tuple[float, float] | None:
    """Return an x/z point from a snapshot item."""

    try:
        return float(item["x"]), float(item["z"])
    except (KeyError, TypeError, ValueError):
        return None


def item_matches(
    item: dict[str, Any],
    *,
    coalition: str | None = None,
    alive: bool | None = None,
    active: bool | None = None,
    contains: str | None = None,
) -> bool:
    """Return whether a snapshot item matches common SDK filters."""

    if coalition is not None:
        value = item.get("coalition") or item.get("coalition_name") or item.get("owner_current_name")
        if str(value or "").lower() != coalition.lower():
            return False
    if alive is not None and bool(item.get("alive", False)) is not alive:
        return False
    if active is not None and bool(item.get("active", False)) is not active:
        return False
    if contains is not None:
        fields = ("object_id", "dcs_name", "name", "group_name", "zone_name", "airbase_name", "unit_type", "dcs_type", "type", "category")
        text = " ".join(str(item.get(field) or "") for field in fields).lower()
        if contains.lower() not in text:
            return False
    return True


def auftrag_action_for_mission_type(mission_type: str) -> str:
    """Return the bridge command action for an AUFTRAG mission type.

    :param mission_type: MOOSE mission type such as ``BAI`` or ``Bombing``.
    :returns: Bridge command action string.
    """

    return f"auftrag.create_{auftrag_action_suffix(mission_type)}"


def build_recommended_auftrag_command_params(recommendation: Any) -> dict[str, Any]:
    """Build flat Lua command parameters from an AUFTRAG recommendation.

    :param recommendation: Recommendation object with ``to_dict``.
    :returns: Flat command parameter dictionary without null-valued fields.
    """

    return auftrag_command_params_from_recommendation(recommendation)


def auftrag_id_from_ack(ack: dict[str, Any]) -> str | None:
    """Return the created AUFTRAG id from an ACK payload."""

    result = ack.get("result") if isinstance(ack.get("result"), dict) else {}
    value = result.get("auftrag_id")
    if value is None or value == "":
        return None
    return str(value)


def auftrag_outcome_from_event(event: dict[str, Any]) -> AuftragOutcome:
    """Build an AUFTRAG outcome from an ``auftrag.evaluated`` event."""

    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    auftrag_payload = payload.get("auftrag") if isinstance(payload.get("auftrag"), dict) else {}
    snapshot = dict(auftrag_payload)
    snapshot.setdefault("object_id", payload.get("auftrag_id"))
    snapshot.setdefault("type", payload.get("auftrag_type"))
    snapshot.setdefault("status", payload.get("status"))
    snapshot.setdefault("summary", payload.get("summary"))
    return AuftragOutcome.from_snapshot(snapshot)


async def maybe_call_auftrag_status_callback(
    callback: Callable[[AuftragEvent], Any | Awaitable[Any]] | None,
    event: AuftragEvent,
) -> None:
    """Call an optional sync or async AUFTRAG status callback."""

    if callback is None:
        return
    result = callback(event)
    if isinstance(result, Awaitable):
        await result


def is_evaluated_auftrag_snapshot(snapshot: dict[str, Any]) -> bool:
    """Return whether an AUFTRAG snapshot contains MOOSE's summary table.

    :param snapshot: Raw AUFTRAG snapshot.
    :returns: ``True`` when ``summary`` is present.
    """

    return isinstance(snapshot.get("summary"), dict)


class MooseBridgeClient:
    """High-level SDK facade backed by a local ``MooseBridgeServer`` instance.

    :param server: Running bridge server instance.
    """

    def __init__(self, server: MooseBridgeServer) -> None:
        self.server = server
        self._auftrag_ids_by_object: dict[int, str] = {}

    @property
    def state(self) -> MooseBridgeState:
        """Return the current typed and raw bridge state.

        :returns: Local state mirror maintained by the server.
        """

        return self.server.state

    def opszone(self, object_id: str) -> OpsZone | None:
        """Return a typed OPSZONE by object id.

        :param object_id: Stable bridge object id such as ``OPSZONE:Town Fight``.
        :returns: Typed OPSZONE or ``None``.
        """

        return self.state.opszone(object_id)

    def opsgroup(self, object_id: str) -> OpsGroup | None:
        """Return a typed OPSGROUP by object id.

        :param object_id: Stable bridge object id such as ``OPSGROUP:Aerial-1``.
        :returns: Typed OPSGROUP or ``None``.
        """

        return self.state.opsgroup(object_id)

    def auftrag(self, object_id: str) -> Auftrag | None:
        """Return a typed AUFTRAG by object id.

        :param object_id: Stable bridge object id such as ``AUFTRAG:1``.
        :returns: Typed AUFTRAG or ``None``.
        """

        return self.state.auftrag(object_id)

    def current_auftrag_for_group(self, opsgroup_id: str) -> Auftrag | None:
        """Return the current AUFTRAG assigned to an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Typed AUFTRAG or ``None``.
        """

        return self.state.current_auftrag_for_group(opsgroup_id)

    def queued_auftraege_for_group(self, opsgroup_id: str) -> list[Auftrag]:
        """Return queued AUFTRAG objects for an OPSGROUP.

        :param opsgroup_id: Stable OPSGROUP object id.
        :returns: Typed AUFTRAG objects present in the local state mirror.
        """

        return self.state.queued_auftraege_for_group(opsgroup_id)

    async def request_snapshots(self, actions: tuple[str, ...]) -> None:
        """Request a sequence of bridge snapshots.

        :param actions: Snapshot command actions.
        :raises MooseBridgeCommandError: If any snapshot command is rejected.
        """

        for action in actions:
            require_ok(await self.server.send_command(BridgeCommand(action=action, params={})))
            await asyncio.sleep(0.05)

    async def snapshot_groups(self) -> dict[str, Any]:
        """Request a GROUP snapshot through the SDK."""

        return require_ok(await self.server.snapshot_groups())

    async def snapshot_units(self) -> dict[str, Any]:
        """Request a UNIT snapshot through the SDK."""

        return require_ok(await self.server.snapshot_units())

    async def snapshot_statics(self) -> dict[str, Any]:
        """Request a STATIC snapshot through the SDK."""

        return require_ok(await self.server.snapshot_statics())

    async def snapshot_airbases(self) -> dict[str, Any]:
        """Request an AIRBASE snapshot through the SDK."""

        return require_ok(await self.server.snapshot_airbases())

    async def snapshot_zones(self) -> dict[str, Any]:
        """Request a ZONE snapshot through the SDK."""

        return require_ok(await self.server.snapshot_zones())

    async def snapshot_opszones(self) -> dict[str, Any]:
        """Request an OPSZONE snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_opszones())

    async def snapshot_opsgroups(self) -> dict[str, Any]:
        """Request an OPSGROUP snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_opsgroups())

    async def snapshot_auftraege(self) -> dict[str, Any]:
        """Request an AUFTRAG snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_auftraege())

    async def snapshot_cohorts(self) -> dict[str, Any]:
        """Request a COHORT snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_cohorts())

    async def snapshot_legions(self) -> dict[str, Any]:
        """Request a LEGION snapshot through the SDK.

        :returns: Successful ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.snapshot_legions())

    async def snapshot_objects(self) -> dict[str, Any]:
        """Request a combined object snapshot through the SDK."""

        return require_ok(await self.server.send_command(BridgeCommand(action="snapshot.objects", params={})))

    async def snapshot_all(self) -> dict[str, Any]:
        """Request all supported snapshots through the SDK."""

        return require_ok(await self.server.send_command(BridgeCommand(action="snapshot.all", params={})))

    async def snapshot_kind(self, kind: str) -> dict[str, Any]:
        """Request one snapshot by short kind name."""

        normalized = kind.removeprefix("snapshot.").lower().strip()
        if normalized not in SNAPSHOT_KINDS:
            raise ValueError(f"Unsupported snapshot kind: {kind!r}. Expected one of {sorted(SNAPSHOT_KINDS)}")
        method = getattr(self, f"snapshot_{normalized}", None)
        if method is not None:
            return await method()
        return require_ok(await self.server.send_command(BridgeCommand(action=f"snapshot.{normalized}", params={})))

    async def request_ops_state(self) -> MooseBridgeState:
        """Request OPS snapshots and return the updated local state mirror.

        :returns: Updated local state mirror.
        :raises MooseBridgeCommandError: If DCS rejects one of the snapshot commands.
        """

        await self.snapshot_opszones()
        await self.snapshot_opsgroups()
        await self.snapshot_auftraege()
        await asyncio.sleep(0.1)
        return self.state

    async def apply_auftrag(self, mission_type: str, params: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        """Apply an AUFTRAG command to DCS.

        :param mission_type: Mission type such as ``BAI`` or ``Bombing``.
        :param params: Flat command parameters accepted by the Lua extension.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        action = auftrag_action_for_mission_type(mission_type)
        clean_params = {key: value for key, value in params.items() if value is not None}
        return require_ok(await self.server.send_command(BridgeCommand(action=action, params=clean_params), timeout=timeout))

    async def add_auftrag(
        self,
        auftrag: AuftragCommand,
        *,
        legion: str | None = None,
        opsgroup: str | None = None,
        cohort: str | None = None,
        selected_payload_uid: int | str | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Create an AUFTRAG in DCS and add it to a LEGION or OPSGROUP.

        :param auftrag: Python-side AUFTRAG description, e.g. ``Auftrag_BAI``.
        :param legion: Target LEGION object id.
        :param opsgroup: Target OPSGROUP object id.
        :param cohort: Optional COHORT object id for LEGION-based tasking.
        :param selected_payload_uid: Optional selected payload UID.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises ValueError: If neither or both ``legion`` and ``opsgroup`` are set.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        if (legion is None) == (opsgroup is None):
            raise ValueError("Specify exactly one of legion or opsgroup")

        params = auftrag.to_params()
        params.update(
            clean_params(
                {
                    "legion_id": legion,
                    "opsgroup_id": opsgroup,
                    "cohort_id": cohort,
                    "selected_payload_uid": selected_payload_uid,
                }
            )
        )
        ack = await self.apply_auftrag(auftrag.mission_type, params, timeout=timeout)
        auftrag_id = auftrag_id_from_ack(ack)
        if auftrag_id:
            self._auftrag_ids_by_object[id(auftrag)] = auftrag_id
        return ack

    async def get_auftrag_summary(
        self,
        auftrag: AuftragCommand | str,
        *,
        timeout_s: float = 600.0,
        interval_s: float = 5.0,
        on_status: Callable[[AuftragEvent], Any | Awaitable[Any]] | None = None,
    ) -> AuftragOutcome:
        """Wait until an AUFTRAG evaluated event arrives and return its outcome.

        ``auftrag`` can be the same Python AUFTRAG object previously passed to
        :meth:`add_auftrag`, or a direct ``AUFTRAG:id`` string.

        :param auftrag: Python AUFTRAG description or stable ``AUFTRAG:id``.
        :param timeout_s: Maximum monitoring time in seconds.
        :param interval_s: Backward-compatible no-op; event waiting does not poll.
        :param on_status: Optional callback called for intermediate AUFTRAG events.
        :returns: Stable evaluated AUFTRAG outcome.
        :raises ValueError: If the Python object was not created through this client.
        """

        auftrag_id = auftrag if isinstance(auftrag, str) else self._auftrag_ids_by_object.get(id(auftrag))
        if not auftrag_id:
            raise ValueError("No AUFTRAG id is known for this object. Call add_auftrag first or pass an AUFTRAG:id string.")
        return await self.wait_for_auftrag_outcome(auftrag_id, timeout_s=timeout_s, interval_s=interval_s, on_status=on_status)

    async def apply_recommended_auftrag(self, recommendation: Any, timeout: float = 10.0) -> dict[str, Any]:
        """Apply an AUFTRAG recommendation produced by the advisory layer.

        :param recommendation: Recommendation object with ``to_dict``.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        data = recommendation.to_dict()
        mission_type = str(data.get("mission_type") or "").strip()
        if not mission_type:
            raise ValueError("Recommendation does not include mission_type")
        return await self.apply_auftrag(mission_type, build_recommended_auftrag_command_params(recommendation), timeout=timeout)

    async def wait_for_auftrag_outcome(
        self,
        auftrag_id: str,
        timeout_s: float = 600.0,
        interval_s: float = 5.0,
        on_status: Callable[[AuftragEvent], Any | Awaitable[Any]] | None = None,
    ) -> AuftragOutcome:
        """Wait until an AUFTRAG evaluated event arrives and return its outcome.

        The method waits for the Lua bridge's ``auftrag.evaluated`` event and
        uses ``summary.success`` as the authoritative result. ``interval_s`` is
        accepted for backward-compatible call sites but is not used.

        :param auftrag_id: Stable AUFTRAG object id from the apply ACK.
        :param timeout_s: Maximum monitoring time in seconds.
        :param interval_s: Backward-compatible no-op; event waiting does not poll.
        :param on_status: Optional callback called for intermediate AUFTRAG events.
        :returns: Stable AUFTRAG outcome model.
        :raises MooseBridgeAuftragNotFoundError: If the AUFTRAG is never observed.
        :raises MooseBridgeAuftragTimeoutError: If no summary appears before timeout.
        """

        deadline = asyncio.get_running_loop().time() + timeout_s
        seen = False
        last_event_id: str | None = None

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                if seen:
                    raise MooseBridgeAuftragTimeoutError(f"{auftrag_id} was not evaluated before timeout")
                raise MooseBridgeAuftragNotFoundError(f"{auftrag_id} produced no AUFTRAG events before timeout")

            try:
                event = await self.server.wait_for_event("auftrag.*", filters={"auftrag_id": auftrag_id}, timeout=remaining, after_id=last_event_id)
            except TimeoutError as exc:
                if seen:
                    raise MooseBridgeAuftragTimeoutError(f"{auftrag_id} was not evaluated before timeout") from exc
                raise MooseBridgeAuftragNotFoundError(f"{auftrag_id} produced no AUFTRAG events before timeout") from exc

            seen = True
            last_event_id = str(event.get("id") or "") or last_event_id
            self.state.apply_message(event)
            auftrag_event = AuftragEvent.from_message(event)
            if auftrag_event.event != "auftrag.evaluated":
                await maybe_call_auftrag_status_callback(on_status, auftrag_event)
                continue

            try:
                outcome = auftrag_outcome_from_event(event)
            except ValueError as exc:
                raise MooseBridgeAuftragNotFoundError(f"{auftrag_id} evaluated event did not contain a usable summary") from exc
            return outcome

    async def message_coalition(self, coalition: str, text: str, duration: int = 10) -> dict[str, Any]:
        """Send a message to a coalition in DCS.

        :param coalition: Coalition name.
        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.message_to_coalition(coalition, text, duration))

    async def message_to_coalition(self, coalition: str, text: str, duration: int = 10) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`message_coalition`.

        :param coalition: Coalition name.
        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.message_coalition(coalition, text, duration)

    async def message_all(self, text: str, duration: int = 10) -> dict[str, Any]:
        """Send a message to all players in DCS.

        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.message_to_all(text, duration))

    async def message_to_all(self, text: str, duration: int = 10) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`message_all`.

        :param text: Message text.
        :param duration: Message duration in seconds.
        :returns: ACK message received from DCS.
        """

        return await self.message_all(text, duration)

    async def smoke_point(self, x: float, z: float, color: str = "white", y: float = 0.0) -> dict[str, Any]:
        """Create smoke at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param color: Smoke color: red, green, blue, orange, or white.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.smoke_at_point(x, z, validate_smoke_color(color), y))

    async def smoke_at_point(self, x: float, z: float, color: str = "white", y: float = 0.0) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`smoke_point`.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param color: Smoke color: red, green, blue, orange, or white.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.smoke_point(x, z, color, y)

    async def smoke_object(self, object_id: str, color: str = "white") -> dict[str, Any]:
        """Create smoke at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``UNIT:Name``.
        :param color: Smoke color: red, green, blue, orange, or white.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.smoke_object(object_id, validate_smoke_color(color)))

    async def mark_point(self, x: float, z: float, text: str, y: float = 0.0) -> dict[str, Any]:
        """Create a map mark at a DCS world point.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param text: Mark text.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.mark_at_point(x, z, text, y))

    async def mark_at_point(self, x: float, z: float, text: str, y: float = 0.0) -> dict[str, Any]:
        """Backward-compatible alias for :meth:`mark_point`.

        :param x: DCS world x coordinate.
        :param z: DCS world z coordinate.
        :param text: Mark text.
        :param y: DCS world y coordinate, usually altitude.
        :returns: ACK message received from DCS.
        """

        return await self.mark_point(x, z, text, y)

    async def mark_object(self, object_id: str, text: str) -> dict[str, Any]:
        """Create a map mark at the resolved position of an object id.

        :param object_id: Stable bridge object id such as ``GROUP:Name``.
        :param text: Mark text.
        :returns: ACK message received from DCS.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        return require_ok(await self.server.mark_object(object_id, text))

    async def coords(self, object_id: str, format: str = "xyz", timeout: float = 10.0) -> CoordinateResult:
        """Resolve coordinates for a bridge object id.

        :param object_id: Stable bridge object id such as ``ZONE:Town Fight``.
        :param format: Coordinate format: ``xyz``, ``ll``, ``mgrs`` or ``all``.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Typed coordinate result.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(action="object.coords", params={"object_id": object_id, "format": validate_coordinate_format(format)}),
                timeout=timeout,
            )
        )
        return CoordinateResult.from_ack(ack)

    async def distance(self, object_id_a: str, object_id_b: str, timeout: float = 10.0) -> DistanceResult:
        """Measure distance between two bridge object ids.

        :param object_id_a: First object id.
        :param object_id_b: Second object id.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Typed distance result.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        ack = require_ok(
            await self.server.send_command(
                BridgeCommand(action="object.distance", params={"object_id_a": object_id_a, "object_id_b": object_id_b}),
                timeout=timeout,
            )
        )
        return DistanceResult.from_ack(ack)

    async def draw_zone(
        self,
        zone_id: str,
        *,
        coalition: str | int = "all",
        color: str | None = None,
        alpha: float | None = None,
        fill_color: str | None = None,
        fill_alpha: float | None = None,
        line_type: str | int | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Draw a MOOSE ZONE or OPSZONE on the F10 map.

        :param zone_id: ``ZONE:<name>`` or ``OPSZONE:<name>``.
        :param coalition: Visibility coalition: all, neutral, red, blue or -1/0/1/2.
        :param color: Optional line color name.
        :param alpha: Optional line alpha in range 0..1.
        :param fill_color: Optional fill color name.
        :param fill_alpha: Optional fill alpha in range 0..1.
        :param line_type: Optional MOOSE line type name or number 0..6.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Successful ACK payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        params = clean_params(
            {
                "object_id": zone_id,
                "coalition": validate_draw_zone_coalition(coalition),
                "color": validate_draw_zone_color(color),
                "alpha": alpha,
                "fill_color": validate_draw_zone_color(fill_color),
                "fill_alpha": fill_alpha,
                "line_type": normalize_draw_zone_line_type(line_type),
            }
        )
        return require_ok(await self.server.send_command(BridgeCommand(action="zone.draw", params=params), timeout=timeout))

    async def trace_auftrag(self, auftrag_id: str, timeout: float = 10.0) -> dict[str, Any]:
        """Trace AUFTRAG assignment and execution state.

        :param auftrag_id: Stable AUFTRAG object id.
        :param timeout: Maximum ACK wait time in seconds.
        :returns: Trace result payload.
        :raises MooseBridgeCommandError: If DCS rejects the command.
        """

        ack = require_ok(
            await self.server.send_command(BridgeCommand(action="auftrag.trace", params={"object_id": auftrag_id}), timeout=timeout)
        )
        result = ack.get("result")
        return result if isinstance(result, dict) else ack

    async def nearest(
        self,
        kind: str,
        target_id: str,
        *,
        coalition: str | None = None,
        alive: bool | None = None,
        active: bool | None = None,
        contains: str | None = None,
        limit: int = 5,
        refresh: bool = True,
        timeout: float = 10.0,
    ) -> list[NearestResult]:
        """Return nearest snapshot items to a target object.

        The target point is resolved live through DCS. Candidate items come
        from the selected local snapshot kind, optionally refreshed first.

        :param kind: Snapshot kind such as ``units``, ``groups`` or ``airbases``.
        :param target_id: Target object id.
        :param coalition: Optional coalition filter.
        :param alive: Optional alive/dead filter.
        :param active: Optional active/inactive filter.
        :param contains: Optional substring filter.
        :param limit: Maximum result count.
        :param refresh: Request the snapshot kind before ranking.
        :param timeout: Maximum ACK wait time in seconds for DCS commands.
        :returns: Ranked nearest results.
        :raises MooseBridgeCommandError: If DCS rejects a command.
        """

        normalized_kind = kind.removeprefix("snapshot.").lower().strip()
        if normalized_kind not in SNAPSHOT_KINDS:
            raise ValueError(f"Unsupported snapshot kind: {kind!r}. Expected one of {sorted(SNAPSHOT_KINDS)}")

        target = await self.coords(target_id, format="xyz", timeout=timeout)
        if target.x is None or target.z is None:
            raise ValueError(f"Target has no x/z coordinates: {target_id}")
        if refresh:
            await self.snapshot_kind(normalized_kind)

        values = getattr(self.state, normalized_kind)
        items = list(values.values()) if isinstance(values, dict) else []
        ranked: list[NearestResult] = []
        for item in items:
            object_id = str(item.get("object_id") or "")
            if object_id == target_id:
                continue
            if not item_matches(item, coalition=coalition, alive=alive, active=active, contains=contains):
                continue
            point = point_from_item(item)
            if point is None:
                continue
            distance_m = math.hypot(point[0] - target.x, point[1] - target.z)
            ranked.append(NearestResult(object_id=object_id, distance_m=distance_m, distance_nm=distance_m / 1852, item=item))

        ranked.sort(key=lambda value: value.distance_m)
        return ranked[: max(0, limit)]
