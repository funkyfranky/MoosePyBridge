"""MOOSE Bridge Python package."""

from .auftrag_specs import AuftragParameterSpec, AuftragTypeSpec, get_auftrag_type_spec
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
    "get_auftrag_type_spec",
]
