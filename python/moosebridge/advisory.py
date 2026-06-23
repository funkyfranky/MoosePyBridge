"""Advisory-only AUFTRAG request validation.

This module evaluates whether an AUFTRAG request is structurally valid and which
LEGION/COHORT candidates are suitable. It never sends commands to DCS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any

from .auftrag_specs import (
    AuftragParameterSpec,
    AuftragType,
    AuftragTypeSpec,
    canonical_mission_type,
    get_auftrag_type_spec,
    platform_categories_match,
)
from .legions import Cohort, Legion
from .state import MooseBridgeState

COMBAT_TARGET_TYPES = {"GROUP", "UNIT", "STATIC"}
PRIMITIVE_PARAMETER_TYPES = {"float", "int", "str", "bool"}
METERS_PER_NAUTICAL_MILE = 1852.0


@dataclass(slots=True, frozen=True)
class AdvisoryIssue:
    """One advisory validation issue.

    :param severity: Issue severity such as ``error`` or ``warning``.
    :param code: Stable machine-readable issue code.
    :param message: Human-readable issue message.
    """

    severity: str
    code: str
    message: str


@dataclass(slots=True, frozen=True)
class AuftragCandidate:
    """Candidate LEGION/COHORT pairing for an AUFTRAG request.

    :param cohort: Candidate COHORT.
    :param legion: Parent LEGION of the candidate COHORT.
    :param distance_m: Distance from LEGION coordinate to target in meters, if known.
    :param distance_nm: Distance from LEGION coordinate to target in nautical miles, if known.
    """

    cohort: Cohort
    legion: Legion | None
    distance_m: float | None = None
    distance_nm: float | None = None


@dataclass(slots=True, frozen=True)
class AuftragAdvisoryResult:
    """Advisory result for one AUFTRAG request.

    :param mission_type: Requested mission type.
    :param params: Request parameters.
    :param coalition: Requested executing coalition, if provided.
    :param spec: Matched AUFTRAG type specification, if known.
    :param target_id: Requested target object id, if present.
    :param target: Resolved target payload, if found.
    :param target_type: Resolved target object type, if known.
    :param target_coalition: Resolved target coalition, if known.
    :param issues: Validation issues.
    :param candidates: Sorted advisory candidates.
    """

    mission_type: str
    params: dict[str, Any]
    coalition: str | None
    spec: AuftragTypeSpec | None
    target_id: str | None = None
    target: dict[str, Any] | None = None
    target_type: str | None = None
    target_coalition: str | None = None
    issues: list[AdvisoryIssue] = field(default_factory=list)
    candidates: list[AuftragCandidate] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return whether the request has no validation errors.

        :returns: ``True`` if no issue has severity ``error``.
        """

        return not any(issue.severity == "error" for issue in self.issues)


def normalize_coalition(value: Any) -> str | None:
    """Normalize a coalition value.

    :param value: Raw coalition value.
    :returns: Lowercase coalition string or ``None``.
    """

    if value is None or value == "":
        return None
    return str(value).strip().lower()


def object_type_from_id(object_id: str) -> str | None:
    """Infer an object type from a stable object id prefix.

    :param object_id: Stable bridge object id.
    :returns: Uppercase object type prefix or ``None``.
    """

    if ":" not in object_id:
        return None
    prefix, _ = object_id.split(":", 1)
    return prefix.strip().upper() or None


def payload_object_type(payload: dict[str, Any], fallback_id: str | None = None) -> str | None:
    """Return the object type of a payload.

    :param payload: Raw object payload.
    :param fallback_id: Optional object id used when payload lacks ``object_type``.
    :returns: Uppercase object type or ``None``.
    """

    value = payload.get("object_type")
    if value:
        return str(value).strip().upper()
    if fallback_id:
        return object_type_from_id(fallback_id)
    object_id = payload.get("object_id")
    if object_id:
        return object_type_from_id(str(object_id))
    return None


def payload_coalition(payload: dict[str, Any] | None) -> str | None:
    """Return a normalized coalition from an object payload.

    :param payload: Raw object payload.
    :returns: Normalized coalition or ``None``.
    """

    if not payload:
        return None
    return normalize_coalition(payload.get("coalition") or payload.get("coalition_name"))


def coordinates_from_payload(payload: dict[str, Any] | None) -> tuple[float, float] | None:
    """Return horizontal DCS coordinates from a payload.

    :param payload: Raw object payload.
    :returns: ``(x, z)`` in DCS meters or ``None``.
    """

    if not payload:
        return None
    try:
        x = payload.get("x")
        z = payload.get("z")
        if x is None or z is None:
            return None
        return float(x), float(z)
    except (TypeError, ValueError):
        return None


def coordinates_from_params(params: dict[str, Any]) -> tuple[float, float] | None:
    """Return direct horizontal DCS coordinates from request parameters.

    :param params: AUFTRAG request parameters.
    :returns: ``(x, z)`` in DCS meters or ``None``.
    """

    if params.get("x") in (None, "") or params.get("z") in (None, ""):
        return None
    try:
        return float(params["x"]), float(params["z"])
    except (TypeError, ValueError):
        return None


def group_coordinates_from_units(state: MooseBridgeState, group_payload: dict[str, Any] | None) -> tuple[float, float] | None:
    """Infer a GROUP coordinate from its UNIT snapshots.

    GROUP snapshots intentionally stay lightweight, so they may not carry ``x`` and ``z``.
    The advisory layer can still infer a useful group position from member UNIT snapshots.

    :param state: State mirror containing UNIT snapshots.
    :param group_payload: GROUP payload.
    :returns: Average UNIT position in DCS meters or ``None``.
    """

    if not group_payload:
        return None
    group_name = group_payload.get("dcs_name") or group_payload.get("name")
    if not group_name:
        object_id = group_payload.get("object_id")
        if isinstance(object_id, str) and ":" in object_id:
            _, group_name = object_id.split(":", 1)
    if not group_name:
        return None

    points: list[tuple[float, float]] = []
    for unit in state.units.values():
        if unit.get("group_name") != group_name:
            continue
        point = coordinates_from_payload(unit)
        if point is not None:
            points.append(point)

    if not points:
        return None
    x = sum(point[0] for point in points) / len(points)
    z = sum(point[1] for point in points) / len(points)
    return x, z


def coordinates_for_state_object(state: MooseBridgeState, object_id: str | None, payload: dict[str, Any] | None) -> tuple[float, float] | None:
    """Return coordinates for a state object, including GROUP fallback from UNIT snapshots.

    :param state: State mirror.
    :param object_id: Stable object id.
    :param payload: Raw object payload.
    :returns: Horizontal coordinate pair or ``None``.
    """

    point = coordinates_from_payload(payload)
    if point is not None:
        return point
    object_type = payload_object_type(payload or {}, object_id)
    if object_type == "GROUP":
        return group_coordinates_from_units(state, payload)
    return None


def distance_m_between(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float | None:
    """Calculate horizontal distance between two DCS coordinate pairs.

    :param a: First coordinate pair.
    :param b: Second coordinate pair.
    :returns: Distance in meters or ``None``.
    """

    if a is None or b is None:
        return None
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return sqrt(dx * dx + dz * dz)


def find_state_object(state: MooseBridgeState, object_id: str) -> dict[str, Any] | None:
    """Find an object payload in the state mirror by stable object id.

    :param state: State mirror.
    :param object_id: Stable bridge object id.
    :returns: Raw object payload or ``None``.
    """

    collections = (
        state.groups,
        state.units,
        state.statics,
        state.zones,
        state.opszones,
        state.opsgroups,
        state.airbases,
        state.auftraege,
        state.cohorts,
        state.legions,
    )
    for collection in collections:
        item = collection.get(object_id)
        if item is not None:
            return item
    return None


def validate_parameter_value(parameter: AuftragParameterSpec, value: Any, state: MooseBridgeState) -> AdvisoryIssue | None:
    """Validate one parameter value against its advisory specification.

    :param parameter: Parameter specification.
    :param value: Raw parameter value.
    :param state: State mirror.
    :returns: Validation issue or ``None``.
    """

    accepted = {item.upper() for item in parameter.accepted_objects}
    primitive_accepted = {item for item in parameter.accepted_objects if item in PRIMITIVE_PARAMETER_TYPES}

    if primitive_accepted:
        if "float" in primitive_accepted:
            try:
                float(value)
                return None
            except (TypeError, ValueError):
                return AdvisoryIssue("error", "INVALID_PARAMETER_TYPE", f"Parameter {parameter.name} must be a float.")
        if "int" in primitive_accepted:
            try:
                int(value)
                return None
            except (TypeError, ValueError):
                return AdvisoryIssue("error", "INVALID_PARAMETER_TYPE", f"Parameter {parameter.name} must be an int.")
        if "bool" in primitive_accepted and not isinstance(value, bool):
            return AdvisoryIssue("error", "INVALID_PARAMETER_TYPE", f"Parameter {parameter.name} must be a bool.")
        if "str" in primitive_accepted and not isinstance(value, str):
            return AdvisoryIssue("error", "INVALID_PARAMETER_TYPE", f"Parameter {parameter.name} must be a string.")
        return None

    if not isinstance(value, str):
        return AdvisoryIssue("error", "INVALID_PARAMETER_TYPE", f"Parameter {parameter.name} must be an object id string.")

    payload = find_state_object(state, value)
    if payload is None:
        return AdvisoryIssue("error", "OBJECT_NOT_FOUND", f"Parameter {parameter.name} object {value} was not found in the state mirror.")

    object_type = payload_object_type(payload, value)
    if object_type not in accepted:
        accepted_text = ", ".join(parameter.accepted_objects)
        return AdvisoryIssue(
            "error",
            "INCOMPATIBLE_OBJECT_TYPE",
            f"Parameter {parameter.name} object {value} has type {object_type}; expected one of {accepted_text}.",
        )

    return None


def evaluate_auftrag_request(
    state: MooseBridgeState,
    mission_type: str,
    params: dict[str, Any],
    coalition: str | None = None,
) -> AuftragAdvisoryResult:
    """Evaluate an AUFTRAG request without executing it in DCS.

    :param state: State mirror with target, LEGION and COHORT snapshots.
    :param mission_type: Requested AUFTRAG mission type.
    :param params: AUFTRAG constructor parameter values.
    :param coalition: Optional executing coalition filter.
    :returns: Advisory result with validation issues and sorted candidates.
    """

    mission_key = canonical_mission_type(mission_type)
    executing_coalition = normalize_coalition(coalition)
    spec = get_auftrag_type_spec(mission_key)
    issues: list[AdvisoryIssue] = []

    if spec is None:
        issues.append(AdvisoryIssue("error", "UNKNOWN_AUFTRAG_TYPE", f"No advisory spec exists for AUFTRAG type {mission_type}."))
        return AuftragAdvisoryResult(mission_key, params, executing_coalition, None, issues=issues)

    for parameter in spec.parameters:
        if parameter.name not in params or params.get(parameter.name) in (None, ""):
            if not parameter.optional:
                issues.append(AdvisoryIssue("error", "MISSING_PARAMETER", f"Required parameter {parameter.name} is missing."))
            continue
        issue = validate_parameter_value(parameter, params[parameter.name], state)
        if issue is not None:
            issues.append(issue)

    target_id = params.get("target") if isinstance(params.get("target"), str) else None
    direct_coords = coordinates_from_params(params)

    if mission_key == AuftragType.BOMBING.name:
        has_x = params.get("x") not in (None, "")
        has_z = params.get("z") not in (None, "")
        if not target_id and direct_coords is None:
            issues.append(
                AdvisoryIssue(
                    "error",
                    "MISSING_TARGET_COORDINATE",
                    "BOMBING requires either a target object or direct x/z coordinates.",
                )
            )
        elif not target_id and has_x != has_z:
            issues.append(AdvisoryIssue("error", "INCOMPLETE_COORDINATE", "BOMBING direct coordinate input requires both x and z."))
        elif target_id and direct_coords is not None:
            issues.append(
                AdvisoryIssue(
                    "warning",
                    "TARGET_OVERRIDES_COORDINATE",
                    "Both target and x/z were supplied; the target object's coordinate will be used.",
                )
            )

    target_payload = find_state_object(state, target_id) if target_id else None
    target_type = payload_object_type(target_payload or {}, target_id) if target_id else None
    target_coalition = payload_coalition(target_payload)
    target_coords = coordinates_for_state_object(state, target_id, target_payload) if target_id else direct_coords

    if target_type in COMBAT_TARGET_TYPES and executing_coalition and target_coalition == executing_coalition:
        issues.append(
            AdvisoryIssue(
                "error",
                "FRIENDLY_TARGET",
                f"Combat target {target_id} has same coalition as executor ({executing_coalition}).",
            )
        )

    if target_id and target_payload is not None and target_coords is None:
        issues.append(AdvisoryIssue("warning", "TARGET_COORDINATE_UNKNOWN", f"No coordinate could be resolved for target {target_id}."))

    cohorts = state.cohorts_with_stock_for_mission_type(mission_key)
    candidates: list[AuftragCandidate] = []
    for cohort in cohorts:
        legion = state.legion(cohort.legion_id) if cohort.legion_id else None
        legion_coalition = normalize_coalition(legion.coalition if legion else None)

        if executing_coalition and legion_coalition != executing_coalition:
            continue

        if target_type in COMBAT_TARGET_TYPES and target_coalition and legion_coalition == target_coalition:
            continue

        if spec.performer_categories and not platform_categories_match(cohort.performer_categories, spec.performer_categories):
            continue

        legion_coords = coordinates_from_payload(legion.raw if legion else None)
        distance_m = distance_m_between(legion_coords, target_coords)
        distance_nm = distance_m / METERS_PER_NAUTICAL_MILE if distance_m is not None else None
        candidates.append(AuftragCandidate(cohort=cohort, legion=legion, distance_m=distance_m, distance_nm=distance_nm))

    candidates.sort(key=lambda candidate: float("inf") if candidate.distance_m is None else candidate.distance_m)

    if not candidates and not any(issue.severity == "error" for issue in issues):
        issues.append(AdvisoryIssue("warning", "NO_CANDIDATES", "No matching COHORT candidates with stock were found."))

    return AuftragAdvisoryResult(
        mission_type=mission_key,
        params=params,
        coalition=executing_coalition,
        spec=spec,
        target_id=target_id,
        target=target_payload,
        target_type=target_type,
        target_coalition=target_coalition,
        issues=issues,
        candidates=candidates,
    )
