"""MOOSE Bridge Python package."""

from .advisory import AdvisoryIssue, AuftragAdvisoryResult, AuftragCandidate, evaluate_auftrag_request
from .auftrag_specs import (
    AUFTRAG_TYPE_NAMES,
    AuftragParameterSpec,
    AuftragTargetType,
    AuftragType,
    AuftragTypeSpec,
    auftrag_action_suffix,
    auftrag_type_name,
    canonical_auftrag_type,
    canonical_mission_type,
    expand_platform_categories,
    get_auftrag_type_spec,
    platform_categories_match,
    target_type_values,
)
from .intents import (
    CommandPayload,
    TacticalIntent,
    TacticalRecommendation,
    auftrag_command_params_from_recommendation,
    command_action_for_auftrag_recommendation,
    tactical_recommendation_from_auftrag,
)
from .legions import Cohort, CohortSummary, Legion
from .models import Auftrag, MooseSnapshotObject, OpsGroup, OpsZone, TargetObjectSnapshot, TargetSnapshot
from .outcomes import AuftragOutcome
from .protocol import BridgeCommand, BridgeMessage
from .recommendations import AuftragRecommendation, executable_candidates, recommend_auftrag, rejected_candidates
from .server import MooseBridgeServer
from .sdk import MooseBridgeAuftragNotFoundError, MooseBridgeAuftragTimeoutError, MooseBridgeClient, MooseBridgeCommandError
from .state import MooseBridgeState, MooseObjectIdentity

__all__ = [
    "AUFTRAG_TYPE_NAMES",
    "AdvisoryIssue",
    "Auftrag",
    "AuftragAdvisoryResult",
    "AuftragCandidate",
    "AuftragOutcome",
    "AuftragParameterSpec",
    "AuftragRecommendation",
    "AuftragTargetType",
    "AuftragType",
    "AuftragTypeSpec",
    "BridgeCommand",
    "BridgeMessage",
    "Cohort",
    "CohortSummary",
    "CommandPayload",
    "Legion",
    "MooseBridgeAuftragNotFoundError",
    "MooseBridgeAuftragTimeoutError",
    "MooseBridgeClient",
    "MooseBridgeCommandError",
    "MooseBridgeServer",
    "MooseBridgeState",
    "MooseSnapshotObject",
    "MooseObjectIdentity",
    "OpsGroup",
    "OpsZone",
    "TargetObjectSnapshot",
    "TargetSnapshot",
    "TacticalIntent",
    "TacticalRecommendation",
    "auftrag_action_suffix",
    "auftrag_command_params_from_recommendation",
    "auftrag_type_name",
    "canonical_auftrag_type",
    "canonical_mission_type",
    "command_action_for_auftrag_recommendation",
    "evaluate_auftrag_request",
    "executable_candidates",
    "expand_platform_categories",
    "get_auftrag_type_spec",
    "platform_categories_match",
    "recommend_auftrag",
    "rejected_candidates",
    "tactical_recommendation_from_auftrag",
    "target_type_values",
]
