"""General Hound/MSRS radio speech models and bridge commands.

Radio profiles are trusted application configuration. A rule system or LLM
may propose text and urgency through :class:`RadioIntent`, but cannot select an
arbitrary frequency, SRS installation, provider, or voice.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Literal, TYPE_CHECKING
from uuid import uuid4

from .protocol import BridgeCommand
from .sdk import require_ok

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


ArbitrationMode = Literal["strict", "disciplined", "congested", "uncontrolled"]
SenderKind = Literal["player", "unit", "group", "airbase", "coordinate"]
Urgency = Literal["routine", "urgent", "emergency"]


def _clean_string(value: str, name: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} must contain 1..{maximum} printable characters")
    return value


def _finite(value: float, name: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return float(value)


@dataclass(frozen=True)
class SpeechProfile:
    """One controlled radio voice and its synthetic network policy."""

    srs_path: str
    srs_host: str
    srs_port: int
    frequency_mhz: float
    modulation: str
    provider: str
    voice: str
    label: str
    volume: float
    speed: float
    interval_s: float
    profile_id: str = "default"
    network_id: str = "default"
    arbitration: ArbitrationMode = "disciplined"
    backoff_min_s: float = 0.25
    backoff_max_s: float = 0.75
    collision_probability: float = 0.10
    emergency_break_in: bool = True

    def __post_init__(self) -> None:
        for name in ("profile_id", "network_id", "srs_host", "provider", "voice", "label"):
            _clean_string(getattr(self, name), name)
        _clean_string(self.srs_path, "srs_path", 512)
        if type(self.srs_port) is not int or not 1 <= self.srs_port <= 65535:
            raise ValueError("srs_port must be an integer from 1 to 65535")
        _finite(self.frequency_mhz, "frequency_mhz", 1, 1000)
        if self.modulation not in {"AM", "FM"}:
            raise ValueError("modulation must be AM or FM")
        _finite(self.volume, "volume", 0, 1)
        _finite(self.speed, "speed", 0.1, 4)
        _finite(self.interval_s, "interval_s", 0, 30)
        if self.arbitration not in {"strict", "disciplined", "congested", "uncontrolled"}:
            raise ValueError("Invalid speech arbitration mode")
        minimum = _finite(self.backoff_min_s, "backoff_min_s", 0, 30)
        maximum = _finite(self.backoff_max_s, "backoff_max_s", 0, 30)
        if maximum < minimum:
            raise ValueError("backoff_max_s must not be less than backoff_min_s")
        _finite(self.collision_probability, "collision_probability", 0, 1)
        if type(self.emergency_break_in) is not bool:
            raise ValueError("emergency_break_in must be boolean")

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "network_id": self.network_id,
            "srs_path": self.srs_path,
            "srs_host": self.srs_host,
            "srs_port": self.srs_port,
            "frequency_mhz": self.frequency_mhz,
            "modulation": self.modulation,
            "provider": self.provider,
            "voice": self.voice,
            "label": self.label,
            "volume": self.volume,
            "speed": self.speed,
            "interval_s": self.interval_s,
            "arbitration": self.arbitration,
            "backoff_min_s": self.backoff_min_s,
            "backoff_max_s": self.backoff_max_s,
            "collision_probability": self.collision_probability,
            "emergency_break_in": self.emergency_break_in,
        }


@dataclass(frozen=True)
class RadioSender:
    """A logical transmitter and the DCS object used as its radio origin."""

    sender_id: str
    kind: SenderKind
    radio_id: str = "primary"
    object_id: str | None = None
    group_id: str | None = None
    session_id: str | None = None
    coalition: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None

    def __post_init__(self) -> None:
        _clean_string(self.sender_id, "sender_id")
        _clean_string(self.radio_id, "radio_id")
        if self.kind not in {"player", "unit", "group", "airbase", "coordinate"}:
            raise ValueError("Invalid radio sender kind")
        if self.kind == "player":
            _clean_string(self.group_id or "", "group_id", 256)
            _clean_string(self.session_id or "", "session_id")
        elif self.kind == "coordinate":
            _finite(self.x, "x", -20_000_000, 20_000_000)
            _finite(self.y, "y", -100_000, 1_000_000)
            _finite(self.z, "z", -20_000_000, 20_000_000)
            if self.coalition not in {"neutral", "red", "blue"}:
                raise ValueError("coordinate sender coalition must be neutral, red, or blue")
        else:
            expected = {"unit": "UNIT:", "group": "GROUP:", "airbase": "AIRBASE:"}[self.kind]
            _clean_string(self.object_id or "", "object_id", 256)
            if not self.object_id.startswith(expected):
                raise ValueError(f"{self.kind} sender object_id must start with {expected}")

    @classmethod
    def player(cls, group_id: str, session_id: str, *, radio_id: str = "primary") -> RadioSender:
        return cls(sender_id=f"player:{group_id}", kind="player", radio_id=radio_id,
                   group_id=group_id, session_id=session_id)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "sender_id": self.sender_id, "kind": self.kind, "radio_id": self.radio_id,
        }
        for key in ("object_id", "group_id", "session_id", "coalition", "x", "y", "z"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class RadioIntent:
    """One bounded request to transmit through a configured radio profile."""

    profile_id: str
    sender: RadioSender
    text: str
    priority: int = 50
    urgency: Urgency = "routine"
    ttl_s: float = 30.0
    dedupe_key: str | None = None
    intent_id: str = ""

    def __post_init__(self) -> None:
        if not self.intent_id:
            object.__setattr__(self, "intent_id", str(uuid4()))
        if not isinstance(self.sender, RadioSender):
            raise ValueError("sender must be a RadioSender")
        _clean_string(self.intent_id, "intent_id")
        _clean_string(self.profile_id, "profile_id")
        _clean_string(self.text, "text", 1000)
        if type(self.priority) is not int or not 1 <= self.priority <= 100:
            raise ValueError("priority must be an integer from 1 to 100")
        if self.urgency not in {"routine", "urgent", "emergency"}:
            raise ValueError("urgency must be routine, urgent, or emergency")
        _finite(self.ttl_s, "ttl_s", 0.1, 3600)
        if self.dedupe_key is not None:
            _clean_string(self.dedupe_key, "dedupe_key")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "intent_id": self.intent_id,
            "profile_id": self.profile_id,
            "sender": self.sender.to_payload(),
            "text": self.text,
            "priority": self.priority,
            "urgency": self.urgency,
            "ttl_s": self.ttl_s,
        }
        if self.dedupe_key is not None:
            payload["dedupe_key"] = self.dedupe_key
        return payload


async def _speech_request(
    bridge: MooseBridgeClient,
    operation: str,
    params: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    ack = require_ok(await bridge.server.send_command(
        BridgeCommand(action=f"speech.{operation}", params=params), timeout=timeout,
    ))
    result = ack.get("result")
    if not isinstance(result, dict):
        raise ValueError("Invalid speech response")
    return result


async def configure_speech(
    bridge: MooseBridgeClient,
    owner_id: str,
    profile: SpeechProfile | Iterable[SpeechProfile] | None,
    *,
    enabled: bool,
    timeout: float = 10,
    expected_instance_id: str | None = None,
) -> dict[str, Any]:
    """Configure one or more mission-scoped profiles or release this owner."""
    params: dict[str, Any] = {"owner_id": owner_id, "enabled": enabled}
    if enabled:
        if profile is None:
            raise ValueError("An enabled speech service requires at least one profile")
        profiles = [profile] if isinstance(profile, SpeechProfile) else list(profile)
        if not profiles or any(not isinstance(item, SpeechProfile) for item in profiles):
            raise ValueError("Speech profiles must be a non-empty collection of SpeechProfile values")
        params["profiles"] = [item.to_payload() for item in profiles]
    if expected_instance_id is not None:
        params["expected_instance_id"] = expected_instance_id
    return await _speech_request(bridge, "configure", params, timeout=timeout)


async def enqueue_speech(
    bridge: MooseBridgeClient,
    owner_id: str,
    intent: RadioIntent,
    *,
    timeout: float = 10,
) -> dict[str, Any]:
    """Submit an intent to its sender queue and configured radio network."""
    return await _speech_request(
        bridge, "enqueue", {"owner_id": owner_id, **intent.to_payload()}, timeout=timeout,
    )


async def test_tone(
    bridge: MooseBridgeClient,
    owner_id: str,
    profile_id: str,
    sender: RadioSender,
    *,
    timeout: float = 10,
) -> dict[str, Any]:
    """Request Hound's test tone on a configured profile."""
    return await _speech_request(bridge, "test_tone", {
        "owner_id": owner_id, "profile_id": profile_id, "sender": sender.to_payload(),
    }, timeout=timeout)


async def clear_speech(
    bridge: MooseBridgeClient,
    owner_id: str,
    *,
    sender: RadioSender | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    """Clear all pending intents, or only those for one logical sender/radio."""
    params: dict[str, Any] = {"owner_id": owner_id}
    if sender is not None:
        params["sender"] = sender.to_payload()
    return await _speech_request(bridge, "clear", params, timeout=timeout)


async def speech_command(
    bridge: MooseBridgeClient,
    owner_id: str,
    group_id: str,
    session_id: str,
    operation: str,
    *,
    timeout: float = 10,
    **params: Any,
) -> dict[str, Any]:
    """Compatibility wrapper for the original player-menu speech API."""
    sender = RadioSender.player(group_id, session_id, radio_id=str(params.pop("radio_id", "primary")))
    profile_id = str(params.pop("profile_id", "default"))
    if operation == "test_tone":
        return await test_tone(bridge, owner_id, profile_id, sender, timeout=timeout)
    if operation == "enqueue":
        intent = RadioIntent(
            profile_id=profile_id, sender=sender, text=params.pop("text"),
            priority=params.pop("priority", 50), urgency=params.pop("urgency", "routine"),
            ttl_s=params.pop("ttl_s", 30.0), dedupe_key=params.pop("dedupe_key", None),
            intent_id=params.pop("intent_id", ""),
        )
        if params:
            raise ValueError(f"Unsupported speech parameters: {', '.join(sorted(params))}")
        return await enqueue_speech(bridge, owner_id, intent, timeout=timeout)
    if operation == "clear":
        return await clear_speech(bridge, owner_id, sender=sender, timeout=timeout)
    raise ValueError(f"Unsupported speech operation: {operation}")
