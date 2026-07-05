"""Declarative AUFTRAG type specifications for advisory planning.

These specifications describe the stable MOOSE AUFTRAG constructor surface that the
Python advisory layer can reason about before autonomous command execution exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

PLATFORM_CATEGORY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "AIR": ("AIR", "AIRPLANE", "HELICOPTER"),
    "AIRPLANE": ("AIRPLANE",),
    "HELICOPTER": ("HELICOPTER",),
    "GROUND": ("GROUND",),
    "NAVAL": ("NAVAL",),
}

PRIMITIVE_PARAMETER_TYPES = {"float", "int", "str", "bool", "list"}


class AuftragType(str, Enum):
    """MOOSE ``AUFTRAG.Type`` values.

    The enum member name is the stable Python/protocol key and the enum value is
    the original MOOSE display string.
    """

    ANTISHIP = "Anti Ship"
    AWACS = "AWACS"
    BAI = "BAI"
    BOMBING = "Bombing"
    BOMBRUNWAY = "Bomb Runway"
    BOMBCARPET = "Carpet Bombing"
    CAP = "CAP"
    CAS = "CAS"
    ESCORT = "Escort"
    FAC = "FAC"
    FACA = "FAC-A"
    FERRY = "Ferry Flight"
    GROUNDESCORT = "Ground Escort"
    INTERCEPT = "Intercept"
    ORBIT = "Orbit"
    GCICAP = "Ground Controlled CAP"
    RECON = "Recon"
    RECOVERYTANKER = "Recovery Tanker"
    RESCUEHELO = "Rescue Helo"
    SEAD = "SEAD"
    STRIKE = "Strike"
    TANKER = "Tanker"
    TROOPTRANSPORT = "Troop Transport"
    ARTY = "Fire At Point"
    PATROLZONE = "Patrol Zone"
    OPSTRANSPORT = "Ops Transport"
    AMMOSUPPLY = "Ammo Supply"
    FUELSUPPLY = "Fuel Supply"
    ALERT5 = "Alert5"
    ONGUARD = "On Guard"
    ARMOREDGUARD = "Armored Guard"
    BARRAGE = "Barrage"
    ARMORATTACK = "Armor Attack"
    CASENHANCED = "CAS Enhanced"
    HOVER = "Hover"
    LANDATCOORDINATE = "Land at Coordinate"
    GROUNDATTACK = "Ground Attack"
    NAVALENGAGEMENT = "Naval Engagement"
    CARGOTRANSPORT = "Cargo Transport"
    RELOCATECOHORT = "Relocate Cohort"
    AIRDEFENSE = "Air Defence"
    EWR = "Early Warning Radar"
    REARMING = "Rearming"
    CAPTUREZONE = "Capture Zone"
    NOTHING = "Nothing"
    PATROLRACETRACK = "Patrol Racetrack"
    STRAFING = "Strafing"
    FREIGHTTRANSPORT = "FREIGHTTRANSPORT"


class AuftragTargetType(str, Enum):
    """Stable target classes accepted by AUFTRAG advisory specs.

    ``COORDINATE`` is represented over the wire by DCS world ``x/y/z`` meters.
    The object-valued target types use stable bridge object ids such as
    ``GROUP:Armor-1`` or ``OPSZONE:Frontline``.
    """

    UNIT = "UNIT"
    GROUP = "GROUP"
    STATIC = "STATIC"
    SCENERY = "SCENERY"
    AIRBASE = "AIRBASE"
    COORDINATE = "COORDINATE"
    ZONE = "ZONE"
    OPSZONE = "OPSZONE"


AUFTRAG_TYPE_NAMES: dict[str, str] = {auftrag_type.name: auftrag_type.value for auftrag_type in AuftragType}


def normalize_auftrag_type_token(value: str) -> str:
    """Normalize an AUFTRAG type key or display name for lookup.

    :param value: Raw AUFTRAG type key or MOOSE display name.
    :returns: Uppercase alphanumeric lookup token.
    """

    return "".join(character for character in value.strip().upper() if character.isalnum())


AUFTRAG_TYPES_BY_TOKEN: dict[str, AuftragType] = {}
for _auftrag_type in AuftragType:
    AUFTRAG_TYPES_BY_TOKEN[normalize_auftrag_type_token(_auftrag_type.name)] = _auftrag_type
    AUFTRAG_TYPES_BY_TOKEN[normalize_auftrag_type_token(_auftrag_type.value)] = _auftrag_type

# Backward-compatible string mapping retained for external callers that used it.
AUFTRAG_TYPE_KEYS_BY_TOKEN: dict[str, str] = {token: auftrag_type.name for token, auftrag_type in AUFTRAG_TYPES_BY_TOKEN.items()}


@dataclass(slots=True, frozen=True)
class AuftragParameterSpec:
    """Specification for one AUFTRAG constructor parameter.

    :param name: Stable parameter name used by Python-side planners.
    :param optional: Whether the parameter may be omitted.
    :param accepted_objects: Accepted bridge target types or primitive parameter types.
    :param description: Human-readable parameter description.
    """

    name: str
    optional: bool
    accepted_objects: tuple[str | AuftragTargetType, ...]
    description: str

    @property
    def accepted_object_values(self) -> tuple[str, ...]:
        """Return accepted target/primitive types as string values.

        :returns: Accepted type values.
        """

        return tuple(item.value if isinstance(item, AuftragTargetType) else str(item) for item in self.accepted_objects)

    def accepts_coordinate(self) -> bool:
        """Return whether this parameter allows coordinate input.

        :returns: ``True`` if ``COORDINATE`` is accepted.
        """

        return AuftragTargetType.COORDINATE.value in self.accepted_object_values

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        :returns: Dictionary representation of this parameter specification.
        """

        return {
            "name": self.name,
            "optional": self.optional,
            "accepted_objects": list(self.accepted_object_values),
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
    def auftrag_type(self) -> AuftragType | None:
        """Return the typed AUFTRAG enum value for this spec.

        :returns: Matching enum value or ``None``.
        """

        return canonical_auftrag_type(self.mission_type)

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

    @property
    def target_parameter(self) -> AuftragParameterSpec | None:
        """Return the semantic target parameter, if present.

        :returns: Target parameter or ``None``.
        """

        for parameter in self.parameters:
            if parameter.name == "target":
                return parameter
        return None

    @property
    def coordinate_parameter(self) -> AuftragParameterSpec | None:
        """Return the optional coordinate parameter, if present."""

        for parameter in self.parameters:
            if parameter.name == "coordinate":
                return parameter
        return None

    @property
    def accepts_coordinate_target(self) -> bool:
        """Return whether this AUFTRAG can use direct coordinate targets.

        :returns: ``True`` if coordinate targets are supported.
        """

        target = self.target_parameter
        return bool(target and target.accepts_coordinate())

    @property
    def accepts_optional_coordinate(self) -> bool:
        """Return whether this AUFTRAG accepts an optional direct coordinate."""

        coordinate = self.coordinate_parameter
        return bool(coordinate and coordinate.accepts_coordinate())

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


OBJECT_TARGET_TYPES = (
    AuftragTargetType.UNIT,
    AuftragTargetType.GROUP,
    AuftragTargetType.STATIC,
    AuftragTargetType.SCENERY,
    AuftragTargetType.AIRBASE,
    AuftragTargetType.ZONE,
    AuftragTargetType.OPSZONE,
)
COMBAT_OBJECT_TARGET_TYPES = (
    AuftragTargetType.GROUP,
    AuftragTargetType.UNIT,
    AuftragTargetType.STATIC,
)
COORDINATE_OR_OBJECT_TARGET_TYPES = (AuftragTargetType.COORDINATE, *OBJECT_TARGET_TYPES)

AIR_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=False,
    accepted_objects=COMBAT_OBJECT_TARGET_TYPES,
    description="Target object used by object-based AUFTRAG constructors.",
)

GROUP_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=False,
    accepted_objects=(AuftragTargetType.GROUP,),
    description="Target GROUP object used by group-based AUFTRAG constructors.",
)

GROUP_OR_UNIT_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=False,
    accepted_objects=(AuftragTargetType.GROUP, AuftragTargetType.UNIT),
    description="Target GROUP or UNIT object.",
)

POSITIONABLE_ATTACK_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=False,
    accepted_objects=(AuftragTargetType.GROUP, AuftragTargetType.UNIT, AuftragTargetType.STATIC),
    description="Target GROUP, UNIT or STATIC object.",
)

UNIT_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=False,
    accepted_objects=(AuftragTargetType.UNIT,),
    description="Target UNIT object.",
)

AIRBASE_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=False,
    accepted_objects=(AuftragTargetType.AIRBASE,),
    description="Target AIRBASE airdrome whose runway should be bombed.",
)

OPTIONAL_COORDINATE_OR_OBJECT_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=True,
    accepted_objects=COORDINATE_OR_OBJECT_TARGET_TYPES,
    description="Optional object shortcut whose current coordinate is used as the mission target point; direct x/z coordinates are also accepted.",
)

OPTIONAL_CARPET_COORDINATE_OR_OBJECT_TARGET_PARAMETER = AuftragParameterSpec(
    name="target",
    optional=True,
    accepted_objects=(AuftragTargetType.COORDINATE, AuftragTargetType.GROUP, AuftragTargetType.UNIT, AuftragTargetType.STATIC),
    description="Optional GROUP, UNIT or STATIC shortcut whose current coordinate is used as the carpet bombing target point; direct x/z coordinates are also accepted.",
)

CAP_ZONE_PARAMETER = AuftragParameterSpec(
    name="zone",
    optional=False,
    accepted_objects=(AuftragTargetType.ZONE,),
    description="ZONE_RADIUS object used as the circular CAP zone.",
)

OPTIONAL_COORDINATE_OBJECT_PARAMETER = AuftragParameterSpec(
    name="coordinate",
    optional=True,
    accepted_objects=COORDINATE_OR_OBJECT_TARGET_TYPES,
    description="Optional object shortcut whose current coordinate is used as the orbit point; direct x/z coordinates are also accepted.",
)

ALTITUDE_PARAMETER = AuftragParameterSpec(
    name="altitude_ft",
    optional=True,
    accepted_objects=("float",),
    description="Engage altitude in feet.",
)

X_COORDINATE_PARAMETER = AuftragParameterSpec(
    name="x",
    optional=True,
    accepted_objects=("float",),
    description="DCS world x coordinate in meters. Required with z when no target object is supplied.",
)

Y_COORDINATE_PARAMETER = AuftragParameterSpec(
    name="y",
    optional=True,
    accepted_objects=("float",),
    description="DCS world y coordinate in meters. Optional; defaults to 0 for 2D coordinate input.",
)

Z_COORDINATE_PARAMETER = AuftragParameterSpec(
    name="z",
    optional=True,
    accepted_objects=("float",),
    description="DCS world z coordinate in meters. Required with x when no target object is supplied.",
)

NSHOTS_PARAMETER = AuftragParameterSpec(
    name="nshots",
    optional=True,
    accepted_objects=("float",),
    description="Optional number of artillery shots. Values in (0, 1) are interpreted by MOOSE as a fraction of available ammunition.",
)

RADIUS_M_PARAMETER = AuftragParameterSpec(
    name="radius_m",
    optional=True,
    accepted_objects=("float",),
    description="Optional artillery impact radius in meters. MOOSE defaults to 100 m when omitted.",
)

SPEED_KTS_PARAMETER = AuftragParameterSpec(
    name="speed_kts",
    optional=True,
    accepted_objects=("float",),
    description="Optional orbit indicated airspeed in knots at altitude. MOOSE defaults to 350 KIAS when omitted.",
)

ATTACK_SPEED_KTS_PARAMETER = AuftragParameterSpec(
    name="speed_kts",
    optional=True,
    accepted_objects=("float",),
    description="Optional attack speed in knots. MOOSE defaults to max speed when omitted.",
)

FORMATION_PARAMETER = AuftragParameterSpec(
    name="formation",
    optional=True,
    accepted_objects=("str",),
    description="Optional ground attack formation string such as Wedge or Vee.",
)

DEPTH_M_PARAMETER = AuftragParameterSpec(
    name="depth_m",
    optional=True,
    accepted_objects=("float",),
    description="Optional naval attack depth in meters. Only relevant for submarines; MOOSE defaults to 0 m.",
)

HEADING_DEG_PARAMETER = AuftragParameterSpec(
    name="heading_deg",
    optional=True,
    accepted_objects=("float",),
    description="Optional race-track orbit heading in degrees. Omit for a circular orbit.",
)

LEG_NM_PARAMETER = AuftragParameterSpec(
    name="leg_nm",
    optional=True,
    accepted_objects=("float",),
    description="Optional race-track leg length in nautical miles. Omit for a circular orbit.",
)

REFUEL_SYSTEM_PARAMETER = AuftragParameterSpec(
    name="refuel_system",
    optional=True,
    accepted_objects=("int",),
    description="Optional tanker refueling system for AIRWING tanker selection: 0=boom, 1=probe.",
)

TARGET_TYPES_PARAMETER = AuftragParameterSpec(
    name="target_types",
    optional=True,
    accepted_objects=("list", "str"),
    description="Optional list of MOOSE target type strings.",
)

RANGE_MAX_NM_PARAMETER = AuftragParameterSpec(
    name="range_max_nm",
    optional=True,
    accepted_objects=("float",),
    description="Optional max engagement range in nautical miles. MOOSE defaults to 25 NM when omitted.",
)

NO_ENGAGE_ZONES_PARAMETER = AuftragParameterSpec(
    name="no_engage_zones",
    optional=True,
    accepted_objects=("list", "str"),
    description="Optional ZONE object id or list of ZONE object ids used to build the NoEngageZoneSet.",
)

FREQUENCY_MHZ_PARAMETER = AuftragParameterSpec(
    name="frequency_mhz",
    optional=True,
    accepted_objects=("float",),
    description="Optional radio frequency in MHz. MOOSE defaults to 133 MHz when omitted.",
)

MODULATION_PARAMETER = AuftragParameterSpec(
    name="modulation",
    optional=True,
    accepted_objects=("int",),
    description="Optional radio modulation. MOOSE defaults to AM when omitted; use 1 for FM.",
)

CARPET_LENGTH_M_PARAMETER = AuftragParameterSpec(
    name="carpet_length_m",
    optional=True,
    accepted_objects=("float",),
    description="Optional carpet bombing length in meters. MOOSE defaults to 500 m when omitted.",
)

STRAFING_LENGTH_M_PARAMETER = AuftragParameterSpec(
    name="length_m",
    optional=True,
    accepted_objects=("float",),
    description="Optional strafing target length in meters.",
)

ORBIT_DISTANCE_NM_PARAMETER = AuftragParameterSpec(
    name="orbit_distance_nm",
    optional=True,
    accepted_objects=("float",),
    description="Optional orbit distance from the escorted lead unit in nautical miles. MOOSE defaults to 1.5 NM.",
)

OFFSET_X_PARAMETER = AuftragParameterSpec(
    name="offset_x",
    optional=True,
    accepted_objects=("float",),
    description="Optional escort offset x component in meters. MOOSE defaults to -100 m when omitted.",
)

OFFSET_Y_PARAMETER = AuftragParameterSpec(
    name="offset_y",
    optional=True,
    accepted_objects=("float",),
    description="Optional escort offset y component in meters. MOOSE defaults to 0 m when omitted.",
)

OFFSET_Z_PARAMETER = AuftragParameterSpec(
    name="offset_z",
    optional=True,
    accepted_objects=("float",),
    description="Optional escort offset z component in meters. MOOSE defaults to 200 m when omitted.",
)

ENGAGE_MAX_DISTANCE_NM_PARAMETER = AuftragParameterSpec(
    name="engage_max_distance_nm",
    optional=True,
    accepted_objects=("float",),
    description="Optional max escort engagement distance in nautical miles. MOOSE defaults to auto 32 NM.",
)

TRANSPORT_GROUPS_PARAMETER = AuftragParameterSpec(
    name="transport_groups",
    optional=False,
    accepted_objects=("list", "str"),
    description="GROUP object id or list of GROUP object ids to transport.",
)

DROPOFF_PARAMETER = AuftragParameterSpec(
    name="dropoff",
    optional=True,
    accepted_objects=COORDINATE_OR_OBJECT_TARGET_TYPES,
    description="Optional object shortcut whose current coordinate is used as the troop dropoff point; direct dropoff_x/dropoff_z coordinates are also accepted.",
)

PICKUP_PARAMETER = AuftragParameterSpec(
    name="pickup",
    optional=True,
    accepted_objects=COORDINATE_OR_OBJECT_TARGET_TYPES,
    description="Optional object shortcut whose current coordinate is used as the troop pickup point; direct pickup_x/pickup_z coordinates are also accepted.",
)

PICKUP_RADIUS_M_PARAMETER = AuftragParameterSpec(
    name="pickup_radius_m",
    optional=True,
    accepted_objects=("float",),
    description="Optional pickup radius in meters. MOOSE defaults to 100 m when omitted.",
)

DESIGNATION_PARAMETER = AuftragParameterSpec(
    name="designation",
    optional=True,
    accepted_objects=("str",),
    description="Optional AI.Task.Designation value. MOOSE defaults to AUTO when omitted.",
)

DATA_LINK_PARAMETER = AuftragParameterSpec(
    name="data_link",
    optional=True,
    accepted_objects=("bool",),
    description="Optional FACA data link flag. MOOSE defaults to true when omitted.",
)

AUFTRAG_TYPE_SPECS: dict[str, AuftragTypeSpec] = {
    AuftragType.BAI.name: AuftragTypeSpec(
        mission_type=AuftragType.BAI.name,
        constructor="AUFTRAG:NewBAI",
        performer_categories=("AIR",),
        description="Battlefield air interdiction against a compatible target object.",
        parameters=(
            AIR_TARGET_PARAMETER,
            ALTITUDE_PARAMETER,
        ),
    ),
    AuftragType.BOMBING.name: AuftragTypeSpec(
        mission_type=AuftragType.BOMBING.name,
        constructor="AUFTRAG:NewBOMBING",
        performer_categories=("AIR",),
        description="Bombing attack against a coordinate, optionally resolved from an object target.",
        parameters=(
            OPTIONAL_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
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
    AuftragType.BOMBRUNWAY.name: AuftragTypeSpec(
        mission_type=AuftragType.BOMBRUNWAY.name,
        constructor="AUFTRAG:NewBOMBRUNWAY",
        performer_categories=("AIR",),
        description="Bomb runway mission against an AIRBASE airdrome.",
        parameters=(
            AIRBASE_TARGET_PARAMETER,
            ALTITUDE_PARAMETER,
        ),
    ),
    AuftragType.BOMBCARPET.name: AuftragTypeSpec(
        mission_type=AuftragType.BOMBCARPET.name,
        constructor="AUFTRAG:NewBOMBCARPET",
        performer_categories=("AIR",),
        description="Carpet bombing mission against a coordinate, optionally resolved from GROUP, UNIT or STATIC.",
        parameters=(
            OPTIONAL_CARPET_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            ALTITUDE_PARAMETER,
            CARPET_LENGTH_M_PARAMETER,
        ),
    ),
    AuftragType.ARTY.name: AuftragTypeSpec(
        mission_type=AuftragType.ARTY.name,
        constructor="AUFTRAG:NewARTY",
        performer_categories=("GROUND", "NAVAL"),
        description="Artillery fire-at-point mission against a coordinate, optionally resolved from an object target.",
        parameters=(
            OPTIONAL_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            NSHOTS_PARAMETER,
            RADIUS_M_PARAMETER,
        ),
    ),
    AuftragType.ORBIT.name: AuftragTypeSpec(
        mission_type=AuftragType.ORBIT.name,
        constructor="AUFTRAG:NewORBIT",
        performer_categories=("AIR",),
        description="Aircraft/helicopter orbit at a coordinate, optionally resolved from an object target.",
        parameters=(
            OPTIONAL_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            ALTITUDE_PARAMETER,
            SPEED_KTS_PARAMETER,
            HEADING_DEG_PARAMETER,
            LEG_NM_PARAMETER,
        ),
    ),
    AuftragType.AWACS.name: AuftragTypeSpec(
        mission_type=AuftragType.AWACS.name,
        constructor="AUFTRAG:NewAWACS",
        performer_categories=("AIR",),
        description="AWACS orbit at a coordinate, optionally resolved from an object target.",
        parameters=(
            OPTIONAL_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            ALTITUDE_PARAMETER,
            SPEED_KTS_PARAMETER,
            HEADING_DEG_PARAMETER,
            LEG_NM_PARAMETER,
        ),
    ),
    AuftragType.TANKER.name: AuftragTypeSpec(
        mission_type=AuftragType.TANKER.name,
        constructor="AUFTRAG:NewTANKER",
        performer_categories=("AIR",),
        description="Tanker orbit at a coordinate, optionally resolved from an object target.",
        parameters=(
            OPTIONAL_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            ALTITUDE_PARAMETER,
            SPEED_KTS_PARAMETER,
            HEADING_DEG_PARAMETER,
            LEG_NM_PARAMETER,
            REFUEL_SYSTEM_PARAMETER,
        ),
    ),
    AuftragType.CAP.name: AuftragTypeSpec(
        mission_type=AuftragType.CAP.name,
        constructor="AUFTRAG:NewCAP",
        performer_categories=("AIR",),
        description="Combat air patrol inside a ZONE_RADIUS, with optional explicit orbit point.",
        parameters=(
            CAP_ZONE_PARAMETER,
            ALTITUDE_PARAMETER,
            SPEED_KTS_PARAMETER,
            OPTIONAL_COORDINATE_OBJECT_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            HEADING_DEG_PARAMETER,
            LEG_NM_PARAMETER,
            TARGET_TYPES_PARAMETER,
        ),
    ),
    AuftragType.CAS.name: AuftragTypeSpec(
        mission_type=AuftragType.CAS.name,
        constructor="AUFTRAG:NewCAS",
        performer_categories=("AIR",),
        description="Close air support inside a ZONE_RADIUS, with optional explicit orbit point.",
        parameters=(
            CAP_ZONE_PARAMETER,
            ALTITUDE_PARAMETER,
            SPEED_KTS_PARAMETER,
            OPTIONAL_COORDINATE_OBJECT_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            HEADING_DEG_PARAMETER,
            LEG_NM_PARAMETER,
            TARGET_TYPES_PARAMETER,
        ),
    ),
    AuftragType.CASENHANCED.name: AuftragTypeSpec(
        mission_type=AuftragType.CASENHANCED.name,
        constructor="AUFTRAG:NewCASENHANCED",
        performer_categories=("AIR",),
        description="Enhanced close air support inside a ZONE with random patrol and optional engagement range limits.",
        parameters=(
            CAP_ZONE_PARAMETER,
            ALTITUDE_PARAMETER,
            SPEED_KTS_PARAMETER,
            RANGE_MAX_NM_PARAMETER,
            NO_ENGAGE_ZONES_PARAMETER,
            TARGET_TYPES_PARAMETER,
        ),
    ),
    AuftragType.FAC.name: AuftragTypeSpec(
        mission_type=AuftragType.FAC.name,
        constructor="AUFTRAG:NewFAC",
        performer_categories=("AIR", "GROUND"),
        description="Forward air controller patrol inside a ZONE.",
        parameters=(
            CAP_ZONE_PARAMETER,
            SPEED_KTS_PARAMETER,
            ALTITUDE_PARAMETER,
            FREQUENCY_MHZ_PARAMETER,
            MODULATION_PARAMETER,
        ),
    ),
    AuftragType.PATROLZONE.name: AuftragTypeSpec(
        mission_type=AuftragType.PATROLZONE.name,
        constructor="AUFTRAG:NewPATROLZONE",
        performer_categories=("AIR", "GROUND", "NAVAL"),
        description="Patrol mission inside a ZONE with optional air altitude and ground formation.",
        parameters=(
            CAP_ZONE_PARAMETER,
            ATTACK_SPEED_KTS_PARAMETER,
            ALTITUDE_PARAMETER,
            FORMATION_PARAMETER,
        ),
    ),
    AuftragType.AMMOSUPPLY.name: AuftragTypeSpec(
        mission_type=AuftragType.AMMOSUPPLY.name,
        constructor="AUFTRAG:NewAMMOSUPPLY",
        performer_categories=("GROUND",),
        description="Ammo supply mission for ground supply units moving to a ZONE.",
        parameters=(
            CAP_ZONE_PARAMETER,
        ),
    ),
    AuftragType.FUELSUPPLY.name: AuftragTypeSpec(
        mission_type=AuftragType.FUELSUPPLY.name,
        constructor="AUFTRAG:NewFUELSUPPLY",
        performer_categories=("GROUND",),
        description="Fuel supply mission for ground supply units moving to a ZONE.",
        parameters=(
            CAP_ZONE_PARAMETER,
        ),
    ),
    AuftragType.REARMING.name: AuftragTypeSpec(
        mission_type=AuftragType.REARMING.name,
        constructor="AUFTRAG:NewREARMING",
        performer_categories=("GROUND",),
        description="Rearming mission for units moving to a ZONE to find ammo supply.",
        parameters=(
            CAP_ZONE_PARAMETER,
        ),
    ),
    AuftragType.AIRDEFENSE.name: AuftragTypeSpec(
        mission_type=AuftragType.AIRDEFENSE.name,
        constructor="AUFTRAG:NewAIRDEFENSE",
        performer_categories=("GROUND", "NAVAL"),
        description="Air defense mission for ground or naval units stationed in a ZONE.",
        parameters=(
            CAP_ZONE_PARAMETER,
        ),
    ),
    AuftragType.EWR.name: AuftragTypeSpec(
        mission_type=AuftragType.EWR.name,
        constructor="AUFTRAG:NewEWR",
        performer_categories=("GROUND",),
        description="Early warning radar mission for ground units stationed in a ZONE.",
        parameters=(
            CAP_ZONE_PARAMETER,
        ),
    ),
    AuftragType.ONGUARD.name: AuftragTypeSpec(
        mission_type=AuftragType.ONGUARD.name,
        constructor="AUFTRAG:NewONGUARD",
        performer_categories=("GROUND", "NAVAL"),
        description="On guard mission for ground or naval units guarding a coordinate.",
        parameters=(
            OPTIONAL_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
        ),
    ),
    AuftragType.NOTHING.name: AuftragTypeSpec(
        mission_type=AuftragType.NOTHING.name,
        constructor="AUFTRAG:NewNOTHING",
        performer_categories=("GROUND", "NAVAL"),
        description="Do nothing mission for assets relaxing in a ZONE.",
        parameters=(
            CAP_ZONE_PARAMETER,
        ),
    ),
    AuftragType.FACA.name: AuftragTypeSpec(
        mission_type=AuftragType.FACA.name,
        constructor="AUFTRAG:NewFACA",
        performer_categories=("AIR",),
        description="Airborne forward air controller mission against a target GROUP.",
        parameters=(
            GROUP_TARGET_PARAMETER,
            DESIGNATION_PARAMETER,
            DATA_LINK_PARAMETER,
            FREQUENCY_MHZ_PARAMETER,
            MODULATION_PARAMETER,
        ),
    ),
    AuftragType.INTERCEPT.name: AuftragTypeSpec(
        mission_type=AuftragType.INTERCEPT.name,
        constructor="AUFTRAG:NewINTERCEPT",
        performer_categories=("AIR",),
        description="Intercept mission against a GROUP or UNIT target.",
        parameters=(
            GROUP_OR_UNIT_TARGET_PARAMETER,
        ),
    ),
    AuftragType.GROUNDESCORT.name: AuftragTypeSpec(
        mission_type=AuftragType.GROUNDESCORT.name,
        constructor="AUFTRAG:NewGROUNDESCORT",
        performer_categories=("AIR",),
        description="Ground escort/follow mission for escorting a ground GROUP.",
        parameters=(
            GROUP_TARGET_PARAMETER,
            ORBIT_DISTANCE_NM_PARAMETER,
            TARGET_TYPES_PARAMETER,
        ),
    ),
    AuftragType.GROUNDATTACK.name: AuftragTypeSpec(
        mission_type=AuftragType.GROUNDATTACK.name,
        constructor="AUFTRAG:NewGROUNDATTACK",
        performer_categories=("GROUND",),
        description="Ground group attack mission against a GROUP, UNIT or STATIC target.",
        parameters=(
            POSITIONABLE_ATTACK_TARGET_PARAMETER,
            ATTACK_SPEED_KTS_PARAMETER,
            FORMATION_PARAMETER,
        ),
    ),
    AuftragType.NAVALENGAGEMENT.name: AuftragTypeSpec(
        mission_type=AuftragType.NAVALENGAGEMENT.name,
        constructor="AUFTRAG:NewNAVALENGAGEMENT",
        performer_categories=("NAVAL",),
        description="Naval group engagement mission against a GROUP, UNIT or STATIC target.",
        parameters=(
            POSITIONABLE_ATTACK_TARGET_PARAMETER,
            ATTACK_SPEED_KTS_PARAMETER,
            DEPTH_M_PARAMETER,
        ),
    ),
    AuftragType.ESCORT.name: AuftragTypeSpec(
        mission_type=AuftragType.ESCORT.name,
        constructor="AUFTRAG:NewESCORT",
        performer_categories=("AIR",),
        description="Escort/follow mission for escorting another GROUP.",
        parameters=(
            GROUP_TARGET_PARAMETER,
            OFFSET_X_PARAMETER,
            OFFSET_Y_PARAMETER,
            OFFSET_Z_PARAMETER,
            ENGAGE_MAX_DISTANCE_NM_PARAMETER,
            TARGET_TYPES_PARAMETER,
        ),
    ),
    AuftragType.RESCUEHELO.name: AuftragTypeSpec(
        mission_type=AuftragType.RESCUEHELO.name,
        constructor="AUFTRAG:NewRESCUEHELO",
        performer_categories=("AIR", "HELICOPTER"),
        description="Rescue helo mission for a carrier UNIT.",
        parameters=(
            UNIT_TARGET_PARAMETER,
        ),
    ),
    AuftragType.TROOPTRANSPORT.name: AuftragTypeSpec(
        mission_type=AuftragType.TROOPTRANSPORT.name,
        constructor="AUFTRAG:NewTROOPTRANSPORT",
        performer_categories=("AIR", "HELICOPTER", "GROUND"),
        description="Troop transport mission moving GROUPs to a dropoff coordinate with optional pickup coordinate.",
        parameters=(
            TRANSPORT_GROUPS_PARAMETER,
            DROPOFF_PARAMETER,
            PICKUP_PARAMETER,
            PICKUP_RADIUS_M_PARAMETER,
        ),
    ),
    AuftragType.SEAD.name: AuftragTypeSpec(
        mission_type=AuftragType.SEAD.name,
        constructor="AUFTRAG:NewSEAD",
        performer_categories=("AIR",),
        description="Suppression of enemy air defenses against a GROUP or UNIT target.",
        parameters=(
            GROUP_OR_UNIT_TARGET_PARAMETER,
            ALTITUDE_PARAMETER,
        ),
    ),
    AuftragType.ANTISHIP.name: AuftragTypeSpec(
        mission_type=AuftragType.ANTISHIP.name,
        constructor="AUFTRAG:NewANTISHIP",
        performer_categories=("AIR",),
        description="Anti-ship mission against a GROUP or UNIT target.",
        parameters=(
            GROUP_OR_UNIT_TARGET_PARAMETER,
            ALTITUDE_PARAMETER,
        ),
    ),
    AuftragType.STRIKE.name: AuftragTypeSpec(
        mission_type=AuftragType.STRIKE.name,
        constructor="AUFTRAG:NewSTRIKE",
        performer_categories=("AIR",),
        description="Strike mission against the closest map object to a coordinate or object position.",
        parameters=(
            OPTIONAL_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            ALTITUDE_PARAMETER,
            AuftragParameterSpec(
                name="engage_weapon_type",
                optional=True,
                accepted_objects=("int",),
                description="Optional numeric ENUMS.WeaponFlag value used as EngageWeaponType.",
            ),
        ),
    ),
    AuftragType.STRAFING.name: AuftragTypeSpec(
        mission_type=AuftragType.STRAFING.name,
        constructor="AUFTRAG:NewSTRAFING",
        performer_categories=("AIR",),
        description="Strafing mission against a coordinate, optionally resolved from GROUP, UNIT or STATIC.",
        parameters=(
            OPTIONAL_CARPET_COORDINATE_OR_OBJECT_TARGET_PARAMETER,
            X_COORDINATE_PARAMETER,
            Y_COORDINATE_PARAMETER,
            Z_COORDINATE_PARAMETER,
            ALTITUDE_PARAMETER,
            STRAFING_LENGTH_M_PARAMETER,
        ),
    ),
}


def canonical_auftrag_type(mission_type: str | AuftragType | None) -> AuftragType | None:
    """Return the canonical AUFTRAG enum member for a key or display name.

    :param mission_type: AUFTRAG type key, display name or enum member.
    :returns: Canonical enum member or ``None`` for unknown/empty input.
    """

    if mission_type is None:
        return None
    if isinstance(mission_type, AuftragType):
        return mission_type
    text = str(mission_type).strip()
    if not text:
        return None
    token = normalize_auftrag_type_token(text)
    return AUFTRAG_TYPES_BY_TOKEN.get(token)


def canonical_mission_type(mission_type: str | AuftragType | None) -> str:
    """Return the canonical Python key for a MOOSE AUFTRAG type string.

    Accepts both enum keys such as ``BOMBING`` and MOOSE display names such as
    ``Bombing`` or ``Ground Controlled CAP``.

    :param mission_type: MOOSE mission type string or enum member.
    :returns: Canonical ``AUFTRAG.Type`` key, or uppercase fallback for unknown types.
    """

    auftrag_type = canonical_auftrag_type(mission_type)
    if auftrag_type is not None:
        return auftrag_type.name
    if mission_type is None:
        return ""
    return str(mission_type).strip().upper()


def auftrag_type_name(mission_type: str | AuftragType | None) -> str:
    """Return the MOOSE display name for an AUFTRAG type.

    :param mission_type: AUFTRAG type key, display name or enum member.
    :returns: MOOSE display name if known, otherwise the original string.
    """

    auftrag_type = canonical_auftrag_type(mission_type)
    if auftrag_type is not None:
        return auftrag_type.value
    if mission_type is None:
        return ""
    return str(mission_type)


def auftrag_action_suffix(mission_type: str | AuftragType | None) -> str:
    """Return the stable Lua command suffix for an AUFTRAG type.

    :param mission_type: AUFTRAG type key, display name or enum member.
    :returns: Lowercase canonical key, for example ``bombing``.
    """

    return canonical_mission_type(mission_type).lower()


def target_type_values(target_types: tuple[str | AuftragTargetType, ...] | list[str | AuftragTargetType]) -> tuple[str, ...]:
    """Return target type values as strings.

    :param target_types: Target type enum values or strings.
    :returns: String target type values.
    """

    return tuple(item.value if isinstance(item, AuftragTargetType) else str(item) for item in target_types)


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


def get_auftrag_type_spec(mission_type: str | AuftragType) -> AuftragTypeSpec | None:
    """Return an AUFTRAG type specification by mission type.

    :param mission_type: Mission type key, enum member or MOOSE display name.
    :returns: Matching AUFTRAG type specification or ``None``.
    """

    return AUFTRAG_TYPE_SPECS.get(canonical_mission_type(mission_type))
