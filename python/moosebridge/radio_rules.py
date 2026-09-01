"""Deterministic first-pass radio phrasing for simulation events.

These helpers turn trusted event facts into bounded :class:`RadioIntent`
objects. A future LLM phraser can replace only the text-building step while the
profile, sender, priority, urgency, TTL, and deduplication policy remain under
application control.
"""

from __future__ import annotations

from .speech import RadioIntent, RadioSender


def _fact(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} must be non-empty printable text")
    return value.strip().rstrip(".")


def status_report(
    profile_id: str,
    sender: RadioSender,
    *,
    callsign: str,
    status: str,
    location: str | None = None,
) -> RadioIntent:
    """Create a routine, replaceable unit status transmission."""
    parts = [_fact(callsign, "callsign"), _fact(status, "status")]
    if location is not None:
        parts.append(f"Position {_fact(location, 'location')}")
    return RadioIntent(
        profile_id=profile_id, sender=sender, text=". ".join(parts) + ".",
        priority=35, urgency="routine", ttl_s=20,
        dedupe_key=f"status:{sender.sender_id}",
    )


def support_request(
    profile_id: str,
    sender: RadioSender,
    *,
    callsign: str,
    addressee: str,
    request: str,
    location: str,
    emergency: bool = False,
) -> RadioIntent:
    """Create a time-sensitive support or assistance request."""
    origin = _fact(callsign, "callsign")
    text = (f"{_fact(addressee, 'addressee')}, this is {origin}. "
            f"Request {_fact(request, 'request')} at {_fact(location, 'location')}.")
    return RadioIntent(
        profile_id=profile_id, sender=sender, text=text,
        priority=100 if emergency else 80,
        urgency="emergency" if emergency else "urgent",
        ttl_s=12 if emergency else 25,
        dedupe_key=f"support:{sender.sender_id}",
    )


def threat_warning(
    profile_id: str,
    sender: RadioSender,
    *,
    callsign: str,
    threat: str,
    location: str,
) -> RadioIntent:
    """Create a short warning that becomes useless quickly."""
    text = (f"{_fact(callsign, 'callsign')}, warning. {_fact(threat, 'threat')} "
            f"at {_fact(location, 'location')}.")
    return RadioIntent(
        profile_id=profile_id, sender=sender, text=text,
        priority=90, urgency="urgent", ttl_s=8,
        dedupe_key=f"warning:{sender.sender_id}:{_fact(threat, 'threat').lower()}",
    )
