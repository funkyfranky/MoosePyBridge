"""Declarative AUFTRAG type specifications for advisory planning.

These specifications describe the stable MOOSE AUFTRAG constructor surface that the
Python advisory layer can reason about before autonomous command execution exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class AuftragParameterSpec:
    """Specification for one AUFTRAG constructor parameter.

    :param name: Stable parameter name used by Python-side planners.
    :param optional: Whether the parameter may be omitted.
    :param accepted_objects: Accepted bridge object types or primitive types.
    :param description: Human-readable parameter description.
    """

    name: str
    optional: bool
    accepted_objects: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        :returns: Dictionary representation of this parameter specification.
        """

        return {
            "name": self.name,
            "optional": self.optional,
            "accepted_objects": list(self.accepted_objects),
            "description": self.description,
        }


@dataclass(slots=True, frozen=True)
class AuftragTypeSpec:
    """Specification for one AUFTRAG constructor.

    :param mission_type: Canonical AUFTRAG mission type key.
    :param constructor: MOOSE constructor name.
    :param parameters: Ordered constructor parameters.
    :param description: Human-readable mission description.
    """

    mission_type: str
    constructor: str
    parameters: tuple[AuftragParameterSpec, ...] = field(default_factory=tuple)
    description: str = ""

    @property
    def required_parameters(self) -> tuple[AuftragParameterSpec, ...]:
        """Return required parameters in constructor order.

        :returns: Required parameter specifications.
        """

        return tuple(parameter for parameter in self.parameters if not parameter.optional)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        :returns: Dictionary representation of this AUFTRAG type specification.
        """

        return {
            "mission_type": self.mission_type,
            "constructor": self.constructor,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "description": self.description,
        }


AUFTRAG_TYPE_SPECS: dict[str, AuftragTypeSpec] = {
    "BAI": AuftragTypeSpec(
        mission_type="BAI",
        constructor="AUFTRAG:NewBAI",
        description="Battlefield air interdiction against a compatible target object.",
        parameters=(
            AuftragParameterSpec(
                name="target",
                optional=False,
                accepted_objects=("GROUP", "UNIT", "STATIC"),
                description="Target object used to create the MOOSE TARGET for the BAI mission.",
            ),
            AuftragParameterSpec(
                name="altitude_ft",
                optional=True,
                accepted_objects=("float",),
                description="Engage altitude in feet.",
            ),
        ),
    ),
}


def canonical_mission_type(mission_type: str) -> str:
    """Return the canonical Python key for a MOOSE mission type string.

    :param mission_type: MOOSE mission type string such as ``BAI`` or ``Orbit``.
    :returns: Uppercase canonical mission type key.
    """

    return mission_type.strip().upper()


def get_auftrag_type_spec(mission_type: str) -> AuftragTypeSpec | None:
    """Return an AUFTRAG type specification by mission type.

    :param mission_type: Mission type key.
    :returns: Matching AUFTRAG type specification or ``None``.
    """

    return AUFTRAG_TYPE_SPECS.get(canonical_mission_type(mission_type))
