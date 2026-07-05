"""Python-side AUFTRAG descriptions used by the MooseBridge SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


def clean_auftrag_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return command parameters without null-valued fields."""

    return {key: value for key, value in params.items() if value is not None}


@dataclass(slots=True, frozen=True)
class GeneralSet:
    """Serializable SDK value object for a MOOSE SET_* input."""

    object_ids: tuple[str, ...]
    object_type = ""

    def __init__(self, *object_ids: str):
        """Create a set from stable MooseBridge object ids."""

        normalized = tuple(str(object_id).strip() for object_id in object_ids)
        object.__setattr__(self, "object_ids", normalized)
        self._validate()

    def _validate(self) -> None:
        if not self.object_ids:
            raise ValueError(f"{type(self).__name__} requires at least one object id")
        if not self.object_type:
            return
        prefix = f"{self.object_type}:"
        invalid = [object_id for object_id in self.object_ids if not object_id.startswith(prefix)]
        if invalid:
            raise ValueError(f"{type(self).__name__} requires {prefix}<name> ids, got {invalid[0]!r}")

    def to_params_value(self) -> list[str]:
        """Return the flat JSON-friendly representation for bridge params."""

        return list(self.object_ids)


class GroupSet(GeneralSet):
    """Serializable SDK value object for a MOOSE SET_GROUP input."""

    object_type = "GROUP"


def set_param_value(value: str | Sequence[str] | GeneralSet) -> list[str]:
    """Return a flat bridge value for a set-like SDK field."""

    if isinstance(value, GeneralSet):
        return value.to_params_value()
    if isinstance(value, str):
        return [value]
    return list(value)


@dataclass(slots=True, frozen=True)
class AuftragEvent:
    """One AUFTRAG FSM event emitted by the Lua bridge."""

    event: str
    auftrag_id: str
    fsm_event: str | None = None
    status: str | None = None
    from_state: str | None = None
    to_state: str | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_message(cls, message: dict[str, Any]) -> "AuftragEvent":
        """Build an AUFTRAG event from a bridge event message."""

        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        return cls(
            event=str(message.get("event") or payload.get("event") or ""),
            auftrag_id=str(payload.get("auftrag_id") or ""),
            fsm_event=str(payload.get("fsm_event")) if payload.get("fsm_event") is not None else None,
            status=str(payload.get("status")) if payload.get("status") is not None else None,
            from_state=str(payload.get("from")) if payload.get("from") is not None else None,
            to_state=str(payload.get("to")) if payload.get("to") is not None else None,
            raw=message,
        )

    def __str__(self) -> str:
        """Return a compact status line."""

        parts = [self.auftrag_id or "<unknown>", self.fsm_event or self.event]
        if self.status:
            parts.append(f"status={self.status}")
        if self.from_state or self.to_state:
            parts.append(f"{self.from_state or '?'}->{self.to_state or '?'}")
        return " ".join(parts)


@dataclass(slots=True, frozen=True)
class AuftragCommand:
    """Python-side AUFTRAG description that can be sent through the bridge."""

    clock_start: str | float | int | None = field(default=None, init=False, repr=False)
    clock_stop: str | float | int | None = field(default=None, init=False, repr=False)
    duration: float | int | None = field(default=None, init=False, repr=False)
    required_assets_min: int | None = field(default=None, init=False, repr=False)
    required_assets_max: int | None = field(default=None, init=False, repr=False)
    mission_type = ""

    def set_time(
        self,
        start: str | float | int | None = None,
        stop: str | float | int | None = None,
    ) -> AuftragCommand:
        """Set optional MOOSE AUFTRAG start/stop timing and return this object."""

        object.__setattr__(self, "clock_start", start)
        object.__setattr__(self, "clock_stop", stop)
        return self

    def set_duration(self, duration: float | int | None) -> AuftragCommand:
        """Set optional MOOSE AUFTRAG execution duration in seconds and return this object."""

        object.__setattr__(self, "duration", duration)
        return self

    def set_required_assets(self, min_count: int | None = 1, max_count: int | None = None) -> AuftragCommand:
        """Set how many asset groups a LEGION-level AUFTRAG should request."""

        if max_count is None:
            max_count = min_count
        object.__setattr__(self, "required_assets_min", min_count)
        object.__setattr__(self, "required_assets_max", max_count)
        return self

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this AUFTRAG."""

        return {}

    def timing_params(self) -> dict[str, Any]:
        """Return optional AUFTRAG timing parameters."""

        return clean_auftrag_params(
            {
                "clock_start": self.clock_start,
                "clock_stop": self.clock_stop,
                "duration": self.duration,
                "required_assets_min": self.required_assets_min,
                "required_assets_max": self.required_assets_max,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragBAI(AuftragCommand):
    """Battlefield air interdiction AUFTRAG."""

    target: str
    altitude_ft: float | None = None
    mission_type = "BAI"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this BAI AUFTRAG."""

        return clean_auftrag_params({"target": self.target, "altitude_ft": self.altitude_ft})


@dataclass(slots=True, frozen=True)
class AuftragBOMBING(AuftragCommand):
    """Bombing AUFTRAG against a coordinate or object target."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    altitude_ft: float | None = None
    engage_weapon_type: int | None = None
    divebomb: bool | None = None
    mission_type = "BOMBING"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this BOMBING AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "altitude_ft": self.altitude_ft,
                "engage_weapon_type": self.engage_weapon_type,
                "divebomb": self.divebomb,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragARTY(AuftragCommand):
    """Artillery fire-at-point AUFTRAG."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    nshots: float | None = None
    radius_m: float | None = None
    mission_type = "ARTY"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this ARTY AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "nshots": self.nshots,
                "radius_m": self.radius_m,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragORBIT(AuftragCommand):
    """Aircraft/helicopter orbit AUFTRAG around a coordinate or object position."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    altitude_ft: float | None = None
    speed_kts: float | None = None
    heading_deg: float | None = None
    leg_nm: float | None = None
    mission_type = "ORBIT"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this ORBIT AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "altitude_ft": self.altitude_ft,
                "speed_kts": self.speed_kts,
                "heading_deg": self.heading_deg,
                "leg_nm": self.leg_nm,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragONGUARD(AuftragCommand):
    """On guard AUFTRAG for ground or naval units guarding a coordinate."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    mission_type = "ONGUARD"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this ONGUARD AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
            }
        )


@dataclass(slots=True, frozen=True)
class _AuftragOrbitRole(AuftragCommand):
    """Base description for air support roles orbiting around a point."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    altitude_ft: float | None = None
    speed_kts: float | None = None
    heading_deg: float | None = None
    leg_nm: float | None = None

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this orbit-role AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "altitude_ft": self.altitude_ft,
                "speed_kts": self.speed_kts,
                "heading_deg": self.heading_deg,
                "leg_nm": self.leg_nm,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragAWACS(_AuftragOrbitRole):
    """AWACS AUFTRAG orbiting around a coordinate or object position."""

    mission_type = "AWACS"


@dataclass(slots=True, frozen=True)
class AuftragTANKER(_AuftragOrbitRole):
    """Tanker AUFTRAG orbiting around a coordinate or object position."""

    refuel_system: int | None = None
    mission_type = "TANKER"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this TANKER AUFTRAG."""

        params = _AuftragOrbitRole.to_params(self)
        if self.refuel_system is not None:
            params["refuel_system"] = self.refuel_system
        return params


@dataclass(slots=True, frozen=True)
class _AuftragZonePatrol(AuftragCommand):
    """Base description for zone-based patrol AUFTRAGs."""

    zone: str
    altitude_ft: float | None = None
    speed_kts: float | None = None
    coordinate: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    heading_deg: float | None = None
    leg_nm: float | None = None
    target_types: Sequence[str] | None = None

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this zone-patrol AUFTRAG."""

        return clean_auftrag_params(
            {
                "zone": self.zone,
                "altitude_ft": self.altitude_ft,
                "speed_kts": self.speed_kts,
                "coordinate": self.coordinate,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "heading_deg": self.heading_deg,
                "leg_nm": self.leg_nm,
                "target_types": list(self.target_types) if self.target_types is not None else None,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragCAP(_AuftragZonePatrol):
    """Combat air patrol AUFTRAG inside a CAP zone."""

    mission_type = "CAP"


@dataclass(slots=True, frozen=True)
class AuftragCAS(_AuftragZonePatrol):
    """Close air support AUFTRAG inside a CAS zone."""

    mission_type = "CAS"


@dataclass(slots=True, frozen=True)
class AuftragCASENHANCED(AuftragCommand):
    """Enhanced close air support AUFTRAG inside a CAS zone."""

    zone: str
    altitude_ft: float | None = None
    speed_kts: float | None = None
    range_max_nm: float | None = None
    no_engage_zones: Sequence[str] | None = None
    target_types: Sequence[str] | None = None
    mission_type = "CASENHANCED"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this CASENHANCED AUFTRAG."""

        return clean_auftrag_params(
            {
                "zone": self.zone,
                "altitude_ft": self.altitude_ft,
                "speed_kts": self.speed_kts,
                "range_max_nm": self.range_max_nm,
                "no_engage_zones": list(self.no_engage_zones) if self.no_engage_zones is not None else None,
                "target_types": list(self.target_types) if self.target_types is not None else None,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragFAC(AuftragCommand):
    """Forward air controller AUFTRAG inside a FAC zone."""

    zone: str
    speed_kts: float | None = None
    altitude_ft: float | None = None
    frequency_mhz: float | None = None
    modulation: int | None = None
    mission_type = "FAC"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this FAC AUFTRAG."""

        return clean_auftrag_params(
            {
                "zone": self.zone,
                "speed_kts": self.speed_kts,
                "altitude_ft": self.altitude_ft,
                "frequency_mhz": self.frequency_mhz,
                "modulation": self.modulation,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragPATROLZONE(AuftragCommand):
    """Patrol zone AUFTRAG for air, ground or naval units."""

    zone: str
    speed_kts: float | None = None
    altitude_ft: float | None = None
    formation: str | None = None
    mission_type = "PATROLZONE"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this PATROLZONE AUFTRAG."""

        return clean_auftrag_params(
            {
                "zone": self.zone,
                "speed_kts": self.speed_kts,
                "altitude_ft": self.altitude_ft,
                "formation": self.formation,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragCAPTUREZONE(AuftragCommand):
    """Capture zone AUFTRAG for air, ground or naval units."""

    opszone: str
    capture_coalition: str | int
    speed_kts: float | None = None
    altitude_ft: float | None = None
    formation: str | None = None
    stay_in_zone_time_s: float | None = None
    mission_type = "CAPTUREZONE"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this CAPTUREZONE AUFTRAG."""

        return clean_auftrag_params(
            {
                "opszone": self.opszone,
                "capture_coalition": self.capture_coalition,
                "speed_kts": self.speed_kts,
                "altitude_ft": self.altitude_ft,
                "formation": self.formation,
                "stay_in_zone_time_s": self.stay_in_zone_time_s,
            }
        )


@dataclass(slots=True, frozen=True)
class _AuftragZoneOnly(AuftragCommand):
    """Base description for AUFTRAGs that only need a MOOSE ZONE."""

    zone: str

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this zone-only AUFTRAG."""

        return {"zone": self.zone}


@dataclass(slots=True, frozen=True)
class AuftragAMMOSUPPLY(_AuftragZoneOnly):
    """Ammo supply AUFTRAG for ground supply units going to a zone."""

    mission_type = "AMMOSUPPLY"


@dataclass(slots=True, frozen=True)
class AuftragFUELSUPPLY(_AuftragZoneOnly):
    """Fuel supply AUFTRAG for ground supply units going to a zone."""

    mission_type = "FUELSUPPLY"


@dataclass(slots=True, frozen=True)
class AuftragREARMING(_AuftragZoneOnly):
    """Rearming AUFTRAG for units going to a zone to find ammo supply."""

    mission_type = "REARMING"


@dataclass(slots=True, frozen=True)
class AuftragAIRDEFENSE(_AuftragZoneOnly):
    """Air defense AUFTRAG for ground or naval units stationed in a zone."""

    mission_type = "AIRDEFENSE"


@dataclass(slots=True, frozen=True)
class AuftragEWR(_AuftragZoneOnly):
    """Early warning radar AUFTRAG for ground units stationed in a zone."""

    mission_type = "EWR"


@dataclass(slots=True, frozen=True)
class AuftragNOTHING(_AuftragZoneOnly):
    """Nothing AUFTRAG for assets relaxing in a zone."""

    mission_type = "NOTHING"


@dataclass(slots=True, frozen=True)
class AuftragFACA(AuftragCommand):
    """Airborne forward air controller AUFTRAG against a target GROUP."""

    target: str
    designation: str | None = None
    data_link: bool | None = None
    frequency_mhz: float | None = None
    modulation: int | None = None
    mission_type = "FACA"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this FACA AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "designation": self.designation,
                "data_link": self.data_link,
                "frequency_mhz": self.frequency_mhz,
                "modulation": self.modulation,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragSEAD(AuftragCommand):
    """Suppression of enemy air defenses AUFTRAG against a GROUP or UNIT."""

    target: str
    altitude_ft: float | None = None
    mission_type = "SEAD"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this SEAD AUFTRAG."""

        return clean_auftrag_params({"target": self.target, "altitude_ft": self.altitude_ft})


@dataclass(slots=True, frozen=True)
class AuftragANTISHIP(AuftragCommand):
    """Anti-ship AUFTRAG against a GROUP or UNIT target."""

    target: str
    altitude_ft: float | None = None
    mission_type = "ANTISHIP"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this ANTISHIP AUFTRAG."""

        return clean_auftrag_params({"target": self.target, "altitude_ft": self.altitude_ft})


@dataclass(slots=True, frozen=True)
class AuftragINTERCEPT(AuftragCommand):
    """Intercept AUFTRAG against a GROUP or UNIT target."""

    target: str
    mission_type = "INTERCEPT"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this INTERCEPT AUFTRAG."""

        return {"target": self.target}


@dataclass(slots=True, frozen=True)
class AuftragSTRIKE(AuftragCommand):
    """Strike AUFTRAG against a coordinate or object position."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    altitude_ft: float | None = None
    engage_weapon_type: int | None = None
    mission_type = "STRIKE"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this STRIKE AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "altitude_ft": self.altitude_ft,
                "engage_weapon_type": self.engage_weapon_type,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragSTRAFING(AuftragCommand):
    """Strafing AUFTRAG against a coordinate or object position."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    altitude_ft: float | None = None
    length_m: float | None = None
    mission_type = "STRAFING"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this STRAFING AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "altitude_ft": self.altitude_ft,
                "length_m": self.length_m,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragBOMBRUNWAY(AuftragCommand):
    """Bomb runway AUFTRAG against an AIRBASE airdrome."""

    target: str
    altitude_ft: float | None = None
    mission_type = "BOMBRUNWAY"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this BOMBRUNWAY AUFTRAG."""

        return clean_auftrag_params({"target": self.target, "altitude_ft": self.altitude_ft})


@dataclass(slots=True, frozen=True)
class AuftragBOMBCARPET(AuftragCommand):
    """Carpet bombing AUFTRAG against a coordinate or object position."""

    target: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    altitude_ft: float | None = None
    carpet_length_m: float | None = None
    mission_type = "BOMBCARPET"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this BOMBCARPET AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "x": self.x,
                "y": self.y,
                "z": self.z,
                "altitude_ft": self.altitude_ft,
                "carpet_length_m": self.carpet_length_m,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragGROUNDESCORT(AuftragCommand):
    """Ground escort/follow AUFTRAG for escorting a ground GROUP."""

    target: str
    orbit_distance_nm: float | None = None
    target_types: Sequence[str] | None = None
    mission_type = "GROUNDESCORT"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this GROUNDESCORT AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "orbit_distance_nm": self.orbit_distance_nm,
                "target_types": list(self.target_types) if self.target_types is not None else None,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragGROUNDATTACK(AuftragCommand):
    """Ground attack AUFTRAG against a GROUP, UNIT or STATIC target."""

    target: str
    speed_kts: float | None = None
    formation: str | None = None
    mission_type = "GROUNDATTACK"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this GROUNDATTACK AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "speed_kts": self.speed_kts,
                "formation": self.formation,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragNAVALENGAGEMENT(AuftragCommand):
    """Naval engagement AUFTRAG against a GROUP, UNIT or STATIC target."""

    target: str
    speed_kts: float | None = None
    depth_m: float | None = None
    mission_type = "NAVALENGAGEMENT"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this NAVALENGAGEMENT AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "speed_kts": self.speed_kts,
                "depth_m": self.depth_m,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragESCORT(AuftragCommand):
    """Escort/follow AUFTRAG for escorting another GROUP."""

    target: str
    offset_x: float | None = None
    offset_y: float | None = None
    offset_z: float | None = None
    engage_max_distance_nm: float | None = None
    target_types: Sequence[str] | None = None
    mission_type = "ESCORT"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this ESCORT AUFTRAG."""

        return clean_auftrag_params(
            {
                "target": self.target,
                "offset_x": self.offset_x,
                "offset_y": self.offset_y,
                "offset_z": self.offset_z,
                "engage_max_distance_nm": self.engage_max_distance_nm,
                "target_types": list(self.target_types) if self.target_types is not None else None,
            }
        )


@dataclass(slots=True, frozen=True)
class AuftragRESCUEHELO(AuftragCommand):
    """Rescue helo AUFTRAG for a carrier UNIT."""

    target: str
    mission_type = "RESCUEHELO"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this RESCUEHELO AUFTRAG."""

        return clean_auftrag_params({"target": self.target})


@dataclass(slots=True, frozen=True)
class AuftragTROOPTRANSPORT(AuftragCommand):
    """Troop transport AUFTRAG for transporting GROUPs to a dropoff coordinate."""

    transport_groups: str | Sequence[str] | GroupSet
    dropoff: str | None = None
    dropoff_x: float | None = None
    dropoff_y: float | None = None
    dropoff_z: float | None = None
    pickup: str | None = None
    pickup_x: float | None = None
    pickup_y: float | None = None
    pickup_z: float | None = None
    pickup_radius_m: float | None = None
    mission_type = "TROOPTRANSPORT"

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this TROOPTRANSPORT AUFTRAG."""

        return clean_auftrag_params(
            {
                "transport_groups": set_param_value(self.transport_groups),
                "dropoff": self.dropoff,
                "dropoff_x": self.dropoff_x,
                "dropoff_y": self.dropoff_y,
                "dropoff_z": self.dropoff_z,
                "pickup": self.pickup,
                "pickup_x": self.pickup_x,
                "pickup_y": self.pickup_y,
                "pickup_z": self.pickup_z,
                "pickup_radius_m": self.pickup_radius_m,
            }
        )


Auftrag_BAI: type[AuftragBAI] = AuftragBAI
Auftrag_AIRDEFENSE: type[AuftragAIRDEFENSE] = AuftragAIRDEFENSE
Auftrag_AMMOSUPPLY: type[AuftragAMMOSUPPLY] = AuftragAMMOSUPPLY
Auftrag_ANTISHIP: type[AuftragANTISHIP] = AuftragANTISHIP
Auftrag_BOMBCARPET: type[AuftragBOMBCARPET] = AuftragBOMBCARPET
Auftrag_BOMBING: type[AuftragBOMBING] = AuftragBOMBING
Auftrag_BOMBRUNWAY: type[AuftragBOMBRUNWAY] = AuftragBOMBRUNWAY
Auftrag_ARTY: type[AuftragARTY] = AuftragARTY
Auftrag_AWACS: type[AuftragAWACS] = AuftragAWACS
Auftrag_ORBIT: type[AuftragORBIT] = AuftragORBIT
Auftrag_CAP: type[AuftragCAP] = AuftragCAP
Auftrag_CAPTUREZONE: type[AuftragCAPTUREZONE] = AuftragCAPTUREZONE
Auftrag_CAS: type[AuftragCAS] = AuftragCAS
Auftrag_CASENHANCED: type[AuftragCASENHANCED] = AuftragCASENHANCED
Auftrag_EWR: type[AuftragEWR] = AuftragEWR
Auftrag_FAC: type[AuftragFAC] = AuftragFAC
Auftrag_FACA: type[AuftragFACA] = AuftragFACA
Auftrag_FUELSUPPLY: type[AuftragFUELSUPPLY] = AuftragFUELSUPPLY
Auftrag_ESCORT: type[AuftragESCORT] = AuftragESCORT
Auftrag_GROUNDATTACK: type[AuftragGROUNDATTACK] = AuftragGROUNDATTACK
Auftrag_GROUNDESCORT: type[AuftragGROUNDESCORT] = AuftragGROUNDESCORT
Auftrag_INTERCEPT: type[AuftragINTERCEPT] = AuftragINTERCEPT
Auftrag_NAVALENGAGEMENT: type[AuftragNAVALENGAGEMENT] = AuftragNAVALENGAGEMENT
Auftrag_NOTHING: type[AuftragNOTHING] = AuftragNOTHING
Auftrag_ONGUARD: type[AuftragONGUARD] = AuftragONGUARD
Auftrag_PATROLZONE: type[AuftragPATROLZONE] = AuftragPATROLZONE
Auftrag_RESCUEHELO: type[AuftragRESCUEHELO] = AuftragRESCUEHELO
Auftrag_REARMING: type[AuftragREARMING] = AuftragREARMING
Auftrag_SEAD: type[AuftragSEAD] = AuftragSEAD
Auftrag_STRAFING: type[AuftragSTRAFING] = AuftragSTRAFING
Auftrag_STRIKE: type[AuftragSTRIKE] = AuftragSTRIKE
Auftrag_TANKER: type[AuftragTANKER] = AuftragTANKER
Auftrag_TROOPTRANSPORT: type[AuftragTROOPTRANSPORT] = AuftragTROOPTRANSPORT


__all__ = [
    "AuftragARTY",
    "AuftragAIRDEFENSE",
    "AuftragAMMOSUPPLY",
    "AuftragANTISHIP",
    "AuftragAWACS",
    "AuftragBAI",
    "AuftragBOMBCARPET",
    "AuftragBOMBING",
    "AuftragBOMBRUNWAY",
    "AuftragCAP",
    "AuftragCAPTUREZONE",
    "AuftragCAS",
    "AuftragCASENHANCED",
    "AuftragCommand",
    "AuftragESCORT",
    "AuftragEvent",
    "AuftragEWR",
    "AuftragFAC",
    "AuftragFACA",
    "AuftragFUELSUPPLY",
    "AuftragGROUNDATTACK",
    "AuftragGROUNDESCORT",
    "AuftragINTERCEPT",
    "AuftragNAVALENGAGEMENT",
    "AuftragNOTHING",
    "AuftragONGUARD",
    "AuftragORBIT",
    "AuftragPATROLZONE",
    "AuftragRESCUEHELO",
    "AuftragREARMING",
    "AuftragSEAD",
    "AuftragSTRAFING",
    "AuftragSTRIKE",
    "AuftragTANKER",
    "AuftragTROOPTRANSPORT",
    "Auftrag_ARTY",
    "Auftrag_AIRDEFENSE",
    "Auftrag_AMMOSUPPLY",
    "Auftrag_ANTISHIP",
    "Auftrag_AWACS",
    "Auftrag_BAI",
    "Auftrag_BOMBCARPET",
    "Auftrag_BOMBING",
    "Auftrag_BOMBRUNWAY",
    "Auftrag_CAP",
    "Auftrag_CAPTUREZONE",
    "Auftrag_CAS",
    "Auftrag_CASENHANCED",
    "Auftrag_ESCORT",
    "Auftrag_EWR",
    "Auftrag_FAC",
    "Auftrag_FACA",
    "Auftrag_FUELSUPPLY",
    "Auftrag_GROUNDATTACK",
    "Auftrag_GROUNDESCORT",
    "Auftrag_INTERCEPT",
    "Auftrag_NAVALENGAGEMENT",
    "Auftrag_NOTHING",
    "Auftrag_ONGUARD",
    "Auftrag_ORBIT",
    "Auftrag_PATROLZONE",
    "Auftrag_RESCUEHELO",
    "Auftrag_REARMING",
    "Auftrag_SEAD",
    "Auftrag_STRAFING",
    "Auftrag_STRIKE",
    "Auftrag_TANKER",
    "Auftrag_TROOPTRANSPORT",
    "GeneralSet",
    "GroupSet",
]
