"""MOOSE Bridge Python package."""

from .auftrag_specs import (
    AuftragParameterSpec,
    AuftragTypeSpec,
    expand_platform_categories,
    get_auftrag_type_spec,
    platform_categories_match,
)
from .legions import Cohort, CohortSummary, Legion
from .models import Auftrag, MooseSnapshotObject, OpsGroup, OpsZone, TargetObjectSnapshot, TargetSnapshot
from .protocol import BridgeCommand, BridgeMessage
from .server import MooseBridgeServer
from .sdk import MooseBridgeClient
from .state import MooseBridgeState, MooseObjectIdentity

__all__ = [
    "Auftrag",
    "AuftragParameterSpec",
    "AuftragTypeSpec",
    "BridgeCommand",
    "BridgeMessage",
    "Cohort",
    "CohortSummary",
    "Legion",
    "MooseBridgeClient",
    "MooseBridgeServer",
    "MooseBridgeState",
    "MooseSnapshotObject",
    "MooseObjectIdentity",
    "OpsGroup",
    "OpsZone",
    "TargetObjectSnapshot",
    "TargetSnapshot",
    "expand_platform_categories",
    "get_auftrag_type_spec",
    "platform_categories_match",
]
