"""Declarative AUFTRAG type specifications for advisory planning.

These specifications describe the stable MOOSE AUFTRAG constructor surface that the
Python advisory layer can reason about before autonomous command execution exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PLATFORM_CATEGORY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "AIR": ("AIR", "AIRPLANE", "HELICOPTER"),
    "AIRPLANE": ("AIRPLANE",),
    "HELICOPTER": ("HELICOPTER",),
    "GROUND": ("GROUND",),
    "NAVAL": ("NAVAL",),
}

AUFTRAG_TYPE_NAMES: dict[str, str] = {
    "ANTISHIP": "Anti Ship",
    "AWACS": "AWACS",
    "BAI": "BAI",
    "BOMBING": "Bombing",
    "BOMBRUNWAY": "Bomb Runway",
    "BOMBCARPET": "Carpet Bombing",
    "CAP": "CAP",
    "CAS": "CAS",
    "ESCORT": "Escort",
    "FAC": "FAC",
    "FACA": "FAC-A",
    "FERRY": "Ferry Flight",
    "GROUNDESCORT": "Ground Escort",
    "INTERCEPT": "Intercept",
    "ORBIT": "Orbit",
    "GCICAP": "Ground Controlled CAP",
    "RECON": "Recon",
    "RECOVERYTANKER": "Recovery Tanker",
    "RESCUEHELO": "Rescue Helo",
    "SEAD": "SEAD",
    "STRIKE": "Strike",
    "TANKER": "Tanker",
    "TROOPTRANSPORT": "Troop Transport",
    "ARTY": "Fire At Point",
    "PATROLZONE": "Patrol Zone",
    "OPSTRANSPORT": "Ops Transport",
    "AMMOSUPPLY": "Ammo Supply",
    "FUELSUPPLY": "Fuel Supply",
    "ALERT5": "Alert5",
    "ONGUARD": "On Guard",
    "ARMOREDGUARD": "Armored Guard",
    "BARRAGE": "Barrage",
    "ARMORATTACK": "Armor Attack",
    "CASENHANCED": "CAS Enhanced",
    "HOVER": "Hover",
    "LANDATCOORDINATE": "Land at Coordinate",
    "GROUNDATTACK": "Ground Attack",
    "NAVALENGAGEMENT": "Naval Engagement",
    "CARGOTRANSPORT": "Cargo Transport",
    "RELOCATECOHORT": "Relocate Cohort",
    "AIRDEFENSE": "Air Defence",
    "EWR": "Early Warning Radar",
    "REARMING": "Rearming",
    "CAPTUREZONE": "Capture Zone",
    "NOTHING": "Nothing",
    "PATROLRACETRACK": "Patrol Racetrack",
    "STRAFING": "Strafing",
    "FREIGHTTRANSPORT": "FREIGHTTRANSPORT",
}


def normalize_auftrag_type_token(value: str) -> str:
    """Normalize an AUFTRAG type key or display name for lookup.

    :param value: Raw AUFTRAG type key or MOOSE display name.
    :returns: Uppercase alphanumeric lookup token.
    """

    return "".join(character for character in value.strip().upper() if character.isalnum())


AUFTRAG_TYPE_KEYS_BY_TOKEN: dict[str, str] = {}
for _auftrag_type_key, _auftrag_type_name in AUFTRAG_TYPE_NAMES.items():
    AUFTRAG_TYPE_KEYS_BY_TOKEN[normalize_auftrag_type_token(_auftrag_type_key)] = _auftrag_type_key
    AUFTRAG_TYPE_KEYS_BY_TOKEN[normalize_auftrag_type_token(_auftrag_type_name)] = _auftrag_type_key


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
    :param performer_categories: Platform categories allowed to execute this AUFTRAG type.
    :param parameters: Ordered constructor parameters.
    :param description: Human-readable mission description.
    """

    mission_type: str
    constructor: str
    performer_categories: tuple[str, ...]
    parameters: tuple[AuftragParameterSpec, ...] = field(default_factory=tuple)
    description: str = ""

    @property
    def required_parameters(self) -> tuple[AuftragParameterSpec, ...]:
        """Return required parameters in constructor order.

        :returns: Required parameter specifications.
        """

        return tuple(parameter for parameter in self.parameters if not parameter.optional)

    @property
    def display_name(self) -> str:
        """Return the MOOSE display name for this AUFTRAG type.

        :returns: Display name from ``AUFTRAG.Type``.
        """

        return auftrag_type_name(self.mission_type)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        :returns: Dictionary representation of this AUFTRAG type specification.
        """

        return {
            "mission_type": self.mission_type,
            "display_name": self.display_name,
            "constructor": self.constructor,
            "performer_categories": list(self.performer_categories),
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "description": self.description,
        }


AIR_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=False,
    accepted_objects=("GROUP", "UNIT", "STATIC"),
    description="Target object. For coordinate-style constructors, DCS/MOOSE resolves the object's current coordinate.",
)

ALTITUDE_PARAMETER = AuftragParameterSpec(
    name="altitude_ft",
    optional=True,
    accepted_objects=("float",),
    description="Engage altitude in feet.",
)

AUFTRAG_TYPE_SPECS: dict[str, AuftragTypeSpec] = {
    "BAI": AuftragTypeSpec(
        mission_type="BAI",
        constructor="AUFTRAG:NewBAI",
        performer_categories=("AIR",),
        description="Battlefield air interdiction against a compatible target object.",
        parameters=(
            AIR_TARGET_PARAMETER,
            ALTITUDE_PARAMETER,
        ),
    ),
    "BOMBING": AuftragTypeSpec(
        mission_type="BOMBING",
        constructor="AUFTRAG:NewBOMBING",
        performer_categories=("AIR",),
        description="Bombing attack against a coordinate resolved from a GROUP, UNIT or STATIC object.",
        parameters=(
            AIR_TARGET_PARAMETER,
            ALTITUDE_PARAMETER,
            AuftragParameterSpec(
                name="engage_weapon_type",
                optional=True,
                accepted_objects=("int",),
                description="Optional numeric ENUMS.WeaponFlag value used as EngageWeaponType.",
            ),
            AuftragParameterSpec(
                name="divebomb",
                optional=True,
                accepted_objects=("bool",),
                description="Optional dive-bombing attack approach flag.",
            ),
        ),
    ),
}


def canonical_mission_type(mission_type: str) -> str:
    """Return the canonical Python key for a MOOSE AUFTRAG type string.

    Accepts both enum keys such as ``BOMBING`` and MOOSE display names such as
    ``Bombing`` or ``Ground Controlled CAP``.

    :param mission_type: MOOSE mission type string.
    :returns: Canonical ``AUFTRAG.Type`` key, or uppercase fallback for unknown types.
    """

    if mission_type is None:
        return ""
    text = str(mission_type).strip()
    if not text:
        return ""
    token = normalize_auftrag_type_token(text)
    return AUFTRAG_TYPE_KEYS_BY_TOKEN.get(token, text.upper())


def auftrag_type_name(mission_type: str) -> str:
    """Return the MOOSE display name for an AUFTRAG type.

    :param mission_type: AUFTRAG type key or display name.
    :returns: MOOSE display name if known, otherwise the original string.
    """

    key = canonical_mission_type(mission_type)
    return AUFTRAG_TYPE_NAMES.get(key, str(mission_type))


def auftrag_action_suffix(mission_type: str) -> str:
    """Return the stable Lua command suffix for an AUFTRAG type.

    :param mission_type: AUFTRAG type key or display name.
    :returns: Lowercase canonical key, for example ``bombing``.
    """

    return canonical_mission_type(mission_type).lower()


def canonical_platform_category(category: str) -> str:
    """Return the canonical platform category key.

    :param category: Platform category string.
    :returns: Uppercase canonical platform category key.
    """

    return category.strip().upper()


def expand_platform_categories(categories: tuple[str, ...] | list[str]) -> set[str]:
    """Expand hierarchical platform categories.

    ``AIR`` expands to ``AIR``, ``AIRPLANE`` and ``HELICOPTER``.

    :param categories: Platform categories.
    :returns: Expanded set of canonical platform categories.
    """

    expanded: set[str] = set()
    for category in categories:
        key = canonical_platform_category(category)
        expanded.update(PLATFORM_CATEGORY_EXPANSIONS.get(key, (key,)))
    return expanded


def platform_categories_match(candidate_categories: tuple[str, ...] | list[str], required_categories: tuple[str, ...] | list[str]) -> bool:
    """Return whether candidate platform categories can satisfy required categories.

    :param candidate_categories: Categories advertised by a COHORT.
    :param required_categories: Categories required by an AUFTRAG type.
    :returns: ``True`` if any expanded category overlaps.
    """

    return bool(expand_platform_categories(candidate_categories) & expand_platform_categories(required_categories))


def get_auftrag_type_spec(mission_type: str) -> AuftragTypeSpec | None:
    """Return an AUFTRAG type specification by mission type.

    :param mission_type: Mission type key or MOOSE display name.
    :returns: Matching AUFTRAG type specification or ``None``.
    """

    return AUFTRAG_TYPE_SPECS.get(canonical_mission_type(mission_type))
