"""Structured AUFTRAG advisory recommendations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class AuftragRecommendation:
    """Structured recommendation for a future AUFTRAG command.

    :param legion_id: Recommended LEGION object id.
    :param cohort_id: Recommended COHORT object id.
    :param constructor: MOOSE AUFTRAG constructor name.
    :param mission_type: Canonical mission type.
    :param params: AUFTRAG constructor parameters.
    :param unit_type: Recommended COHORT unit type.
    :param mission_performance: COHORT mission performance for the mission type.
    :param payload_performance: Best compatible payload performance.
    :param distance_nm: Distance from LEGION coordinate to target in nautical miles.
    :param selected_payload_uid: Selected payload uid.
    :param selected_payload_unitname: Selected payload source/template unit name.
    :param selected_payload_aircrafttype: Selected payload aircraft type.
    :param selected_payload_available: Number of available payloads of this type.
    :param selected_payload_unlimited: Whether selected payload is unlimited.
    :param score_inputs: Raw score-relevant values.
    """

    legion_id: str
    cohort_id: str
    constructor: str
    mission_type: str
    params: dict[str, Any]
    unit_type: str | None = None
    mission_performance: float | None = None
    payload_performance: float | None = None
    distance_nm: float | None = None
    selected_payload_uid: int | float | str | None = None
    selected_payload_unitname: str | None = None
    selected_payload_aircrafttype: str | None = None
    selected_payload_available: int | float | None = None
    selected_payload_unlimited: bool | None = None
    score_inputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the recommendation as a plain dictionary.

        :returns: Serializable recommendation dictionary.
        """

        return asdict(self)


def payload_rejection_reason(candidate: Any, mission_type: str) -> str | None:
    """Return why an AIRWING candidate is not executable because of payload state.

    :param candidate: Advisory candidate.
    :param mission_type: Requested mission type.
    :returns: Rejection reason or ``None``.
    """

    if not candidate.cohort.is_air:
        return None
    payload_available = candidate.cohort.has_payload_for(mission_type)
    if payload_available is True:
        return None
    if payload_available is False:
        return "no compatible AIRWING payload available"
    return "payload availability unknown; load MooseBridgePayloadExtension.lua"


def candidate_sort_key(candidate: Any, mission_type: str) -> tuple[float, float, float, float]:
    """Return ranking key for executable advisory candidates.

    :param candidate: Advisory candidate.
    :param mission_type: Requested mission type.
    :returns: Sort key using mission performance, payload performance, distance and stock.
    """

    mission_performance = candidate.cohort.mission_performance_for(mission_type)
    payload_performance = candidate.cohort.payload_performance_for(mission_type)
    distance_m = candidate.distance_m if candidate.distance_m is not None else float("inf")
    stock = candidate.cohort.stock_asset_count or 0
    return (
        -(mission_performance if mission_performance is not None else -1.0),
        -(payload_performance if payload_performance is not None else -1.0),
        distance_m,
        -float(stock),
    )


def executable_candidates(result: Any) -> list[Any]:
    """Return executable candidates sorted by advisory ranking.

    :param result: AUFTRAG advisory result.
    :returns: Sorted executable candidates.
    """

    candidates = [candidate for candidate in result.candidates if payload_rejection_reason(candidate, result.mission_type) is None]
    candidates.sort(key=lambda candidate: candidate_sort_key(candidate, result.mission_type))
    return candidates


def rejected_candidates(result: Any) -> list[tuple[Any, str]]:
    """Return rejected candidates with rejection reasons.

    :param result: AUFTRAG advisory result.
    :returns: Candidate/reason pairs.
    """

    rejected: list[tuple[Any, str]] = []
    for candidate in result.candidates:
        reason = payload_rejection_reason(candidate, result.mission_type)
        if reason:
            rejected.append((candidate, reason))
    return rejected


def best_payload_for_candidate(candidate: Any, mission_type: str) -> dict[str, Any] | None:
    """Return the best compatible payload for a candidate and mission type.

    :param candidate: Advisory candidate.
    :param mission_type: Requested mission type.
    :returns: Payload summary dictionary or ``None``.
    """

    payload_info = candidate.cohort.payload_info_for(mission_type) or {}
    payloads = payload_info.get("payloads")
    if not isinstance(payloads, list):
        return None

    def payload_sort_key(payload: dict[str, Any]) -> tuple[float, float, float]:
        performance = payload.get("performance")
        navail = payload.get("navail")
        unlimited = 1.0 if payload.get("unlimited") else 0.0
        try:
            performance_value = float(performance) if performance is not None else -1.0
        except (TypeError, ValueError):
            performance_value = -1.0
        try:
            navail_value = float(navail) if navail is not None else 0.0
        except (TypeError, ValueError):
            navail_value = 0.0
        return (-performance_value, -unlimited, -navail_value)

    valid_payloads = [payload for payload in payloads if isinstance(payload, dict)]
    if not valid_payloads:
        return None
    return sorted(valid_payloads, key=payload_sort_key)[0]


def recommend_auftrag(result: Any) -> AuftragRecommendation | None:
    """Build a structured recommendation from an AUFTRAG advisory result.

    :param result: AUFTRAG advisory result.
    :returns: Recommendation for the best executable candidate or ``None``.
    """

    candidates = executable_candidates(result)
    if not candidates or not result.spec:
        return None

    candidate = candidates[0]
    payload = best_payload_for_candidate(candidate, result.mission_type)
    mission_performance = candidate.cohort.mission_performance_for(result.mission_type)
    payload_performance = candidate.cohort.payload_performance_for(result.mission_type)

    return AuftragRecommendation(
        legion_id=candidate.legion.object_id if candidate.legion else "",
        cohort_id=candidate.cohort.object_id,
        constructor=result.spec.constructor,
        mission_type=result.mission_type,
        params=dict(result.params),
        unit_type=candidate.cohort.unit_type,
        mission_performance=mission_performance,
        payload_performance=payload_performance,
        distance_nm=candidate.distance_nm,
        selected_payload_uid=payload.get("uid") if payload else None,
        selected_payload_unitname=payload.get("unitname") if payload else None,
        selected_payload_aircrafttype=payload.get("aircrafttype") if payload else None,
        selected_payload_available=payload.get("navail") if payload else None,
        selected_payload_unlimited=payload.get("unlimited") if payload else None,
        score_inputs={
            "mission_performance": mission_performance,
            "payload_performance": payload_performance,
            "distance_m": candidate.distance_m,
            "distance_nm": candidate.distance_nm,
            "stock_asset_count": candidate.cohort.stock_asset_count,
        },
    )
