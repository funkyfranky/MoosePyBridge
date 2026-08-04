"""Coalition-private INTEL freshness and contact-memory models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from .models import IntelContact


class ContactInformationState(str, Enum):
    """Operational quality of one INTEL contact observation."""

    FRESH = "fresh"
    DEGRADED = "degraded"
    STALE = "stale"
    UNKNOWN = "unknown"
    LOST = "lost"


@dataclass(slots=True, frozen=True)
class IntelContactMemory:
    """Last known state retained after MOOSE emits ``LostContact``."""

    contact: IntelContact
    lost_time: float | None = None
    event_id: str | None = None


@dataclass(slots=True, frozen=True)
class IntelContactAssessment:
    """Time-based information quality without changing MOOSE contact ownership."""

    contact: IntelContact
    state: ContactInformationState
    age_s: float | None
    confidence: float


def assess_intel_contact(
    contact: IntelContact,
    mission_time: float | None,
    *,
    fresh_for_s: float = 120.0,
    stale_after_s: float = 600.0,
    lost: bool = False,
) -> IntelContactAssessment:
    """Assess one contact from its MOOSE ``Tdetected`` mission timestamp."""

    if not math.isfinite(fresh_for_s) or fresh_for_s < 0:
        raise ValueError("fresh_for_s must be finite and non-negative")
    if not math.isfinite(stale_after_s) or stale_after_s <= fresh_for_s:
        raise ValueError("stale_after_s must be finite and greater than fresh_for_s")
    if mission_time is None or contact.detected_time is None:
        state = ContactInformationState.LOST if lost else ContactInformationState.UNKNOWN
        return IntelContactAssessment(contact, state, None, 0.25 if lost else 0.5)

    age_s = max(0.0, mission_time - contact.detected_time)
    if lost:
        confidence = max(0.0, 0.5 * (1.0 - min(age_s / stale_after_s, 1.0)))
        return IntelContactAssessment(contact, ContactInformationState.LOST, age_s, confidence)
    if age_s <= fresh_for_s:
        return IntelContactAssessment(contact, ContactInformationState.FRESH, age_s, 1.0)
    if age_s < stale_after_s:
        fraction = (age_s - fresh_for_s) / (stale_after_s - fresh_for_s)
        return IntelContactAssessment(contact, ContactInformationState.DEGRADED, age_s, 1.0 - 0.75 * fraction)
    return IntelContactAssessment(contact, ContactInformationState.STALE, age_s, 0.1)


__all__ = [
    "ContactInformationState",
    "IntelContactAssessment",
    "IntelContactMemory",
    "assess_intel_contact",
]
