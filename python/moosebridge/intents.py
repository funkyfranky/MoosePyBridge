"""Intent and recommendation models for tactical and strategic planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .auftrag_specs import auftrag_action_suffix, canonical_mission_type


IntentType = Literal["attack_target", "defend_zone", "patrol_zone", "move_to_zone", "observe"]
ApprovalMode = Literal["observe", "recommend", "approval_required", "autonomous"]
CommandMode = Literal["execute", "propose"]


@dataclass(slots=True, frozen=True)
class CommandPayload:
    """Executable semantic bridge command payload.

    :param action: Bridge command action such as ``auftrag.create_bai``.
    :param params: Command parameters.
    :param mode: Command mode sent to DCS/MOOSE.
    """

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    mode: CommandMode = "execute"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable command payload."""

        return asdict(self)


@dataclass(slots=True, frozen=True)
class TacticalIntent:
    """Structured tactical or strategic intent.

    :param intent_type: Stable intent type such as ``attack_target``.
    :param objective: Human-readable objective.
    :param target_id: Optional target object id.
    :param zone_id: Optional zone object id.
    :param coalition: Optional executing coalition.
    :param priority: Relative priority. Higher means more important.
    :param params: Intent-specific parameters.
    """

    intent_type: IntentType
    objective: str
    target_id: str | None = None
    zone_id: str | None = None
    coalition: str | None = None
    priority: int = 50
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def attack_target(
        cls,
        target_id: str,
        objective: str | None = None,
        coalition: str | None = None,
        priority: int = 50,
        params: dict[str, Any] | None = None,
    ) -> "TacticalIntent":
        """Create an attack intent for a target object."""

        return cls(
            intent_type="attack_target",
            objective=objective or f"Attack {target_id}",
            target_id=target_id,
            coalition=coalition,
            priority=priority,
            params=params or {},
        )

    @classmethod
    def defend_zone(
        cls,
        zone_id: str,
        objective: str | None = None,
        coalition: str | None = None,
        priority: int = 50,
        params: dict[str, Any] | None = None,
    ) -> "TacticalIntent":
        """Create a defense intent for a zone object."""

        return cls(
            intent_type="defend_zone",
            objective=objective or f"Defend {zone_id}",
            zone_id=zone_id,
            coalition=coalition,
            priority=priority,
            params=params or {},
        )

    @classmethod
    def patrol_zone(
        cls,
        zone_id: str,
        objective: str | None = None,
        coalition: str | None = None,
        priority: int = 50,
        params: dict[str, Any] | None = None,
    ) -> "TacticalIntent":
        """Create a patrol intent for a zone object."""

        return cls(
            intent_type="patrol_zone",
            objective=objective or f"Patrol {zone_id}",
            zone_id=zone_id,
            coalition=coalition,
            priority=priority,
            params=params or {},
        )

    @classmethod
    def move_to_zone(
        cls,
        zone_id: str,
        objective: str | None = None,
        coalition: str | None = None,
        priority: int = 50,
        params: dict[str, Any] | None = None,
    ) -> "TacticalIntent":
        """Create a movement intent toward a zone object."""

        return cls(
            intent_type="move_to_zone",
            objective=objective or f"Move to {zone_id}",
            zone_id=zone_id,
            coalition=coalition,
            priority=priority,
            params=params or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable intent."""

        return asdict(self)


@dataclass(slots=True, frozen=True)
class TacticalRecommendation:
    """Structured recommendation that can be approved or executed later.

    :param intent: Tactical or strategic intent.
    :param command: Executable bridge command payload.
    :param rationale: Reasons supporting the recommendation.
    :param risks: Known risks or assumptions.
    :param confidence: Recommendation confidence in the range 0..1.
    :param approval_mode: Required operating mode before execution.
    :param source: Recommendation source such as ``auftrag_advisory``.
    :param evidence: Score inputs and other machine-readable support data.
    """

    intent: TacticalIntent
    command: CommandPayload
    rationale: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.5
    approval_mode: ApprovalMode = "approval_required"
    source: str = "manual"
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        """Return whether this recommendation carries a command action."""

        return bool(self.command.action)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable recommendation."""

        return {
            "intent": self.intent.to_dict(),
            "command": self.command.to_dict(),
            "rationale": list(self.rationale),
            "risks": list(self.risks),
            "confidence": self.confidence,
            "approval_mode": self.approval_mode,
            "source": self.source,
            "evidence": dict(self.evidence),
            "executable": self.executable,
        }


def auftrag_command_params_from_recommendation(recommendation: Any) -> dict[str, Any]:
    """Build flat AUFTRAG Lua command params from an AUFTRAG recommendation."""

    params = recommendation.to_dict()
    nested = params.get("params") if isinstance(params.get("params"), dict) else {}
    command_params = {
        "legion_id": params.get("legion_id"),
        "cohort_id": params.get("cohort_id"),
        "selected_payload_uid": params.get("selected_payload_uid"),
        "mission_type": params.get("mission_type"),
        "constructor": params.get("constructor"),
    }
    for key, value in nested.items():
        command_params[key] = value
    return {key: value for key, value in command_params.items() if value is not None}


def command_action_for_auftrag_recommendation(recommendation: Any) -> str:
    """Return the bridge command action for an AUFTRAG recommendation."""

    data = recommendation.to_dict()
    mission_type = str(data.get("mission_type") or "").strip()
    if not mission_type:
        raise ValueError("AUFTRAG recommendation does not include mission_type")
    return f"auftrag.create_{auftrag_action_suffix(mission_type)}"


def intent_type_for_mission_type(mission_type: str, params: dict[str, Any]) -> IntentType:
    """Infer a broad tactical intent type from an AUFTRAG mission type."""

    mission_key = canonical_mission_type(mission_type)
    if mission_key in {"BAI", "BOMBING", "ARTY", "CAS", "STRIKE", "SEAD", "GROUNDATTACK", "ARMORATTACK"}:
        return "attack_target"
    if mission_key in {"PATROLZONE", "CAP", "GCICAP"}:
        return "patrol_zone"
    if mission_key in {"CAPTUREZONE", "ONGUARD", "ARMOREDGUARD", "AIRDEFENSE"}:
        return "defend_zone"
    if mission_key in {"RELOCATECOHORT", "TROOPTRANSPORT", "OPSTRANSPORT", "CARGOTRANSPORT"}:
        return "move_to_zone"
    if params.get("target"):
        return "attack_target"
    return "observe"


def tactical_recommendation_from_auftrag(
    recommendation: Any,
    approval_mode: ApprovalMode = "approval_required",
    confidence: float | None = None,
) -> TacticalRecommendation:
    """Convert an AUFTRAG-specific recommendation into a generic recommendation."""

    data = recommendation.to_dict()
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    mission_type = str(data.get("mission_type") or "")
    target_id = params.get("target") if isinstance(params.get("target"), str) else None
    zone_id = target_id if target_id and (target_id.startswith("ZONE:") or target_id.startswith("OPSZONE:")) else None
    intent_type = intent_type_for_mission_type(mission_type, params)
    objective_target = target_id or zone_id or "mission target"
    intent = TacticalIntent(
        intent_type=intent_type,
        objective=f"{mission_type} using {data.get('cohort_id') or 'selected asset'} against {objective_target}",
        target_id=target_id,
        zone_id=zone_id,
        priority=50,
        params={"mission_type": mission_type, "constructor": data.get("constructor")},
    )
    command = CommandPayload(
        action=command_action_for_auftrag_recommendation(recommendation),
        params=auftrag_command_params_from_recommendation(recommendation),
    )
    rationale = [
        f"Selected cohort {data.get('cohort_id')}",
        f"Selected legion {data.get('legion_id')}",
    ]
    if data.get("distance_nm") is not None:
        rationale.append(f"Distance to target is {data['distance_nm']:.1f} NM")
    if data.get("range_margin_nm") is not None:
        rationale.append(f"Range margin is {data['range_margin_nm']:.1f} NM")

    risks: list[str] = []
    if data.get("selected_payload_uid") is None and data.get("selected_payload_available") is None:
        risks.append("Payload selection is not confirmed by payload snapshot data")

    score_inputs = data.get("score_inputs") if isinstance(data.get("score_inputs"), dict) else {}
    if confidence is None:
        confidence = 0.75 if not risks else 0.6

    return TacticalRecommendation(
        intent=intent,
        command=command,
        rationale=rationale,
        risks=risks,
        confidence=confidence,
        approval_mode=approval_mode,
        source="auftrag_advisory",
        evidence={
            "auftrag_recommendation": data,
            "score_inputs": score_inputs,
        },
    )
