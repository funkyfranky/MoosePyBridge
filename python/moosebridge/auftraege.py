"""Python-side AUFTRAG descriptions used by the MooseBridge SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


def clean_auftrag_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return command parameters without null-valued fields."""

    return {key: value for key, value in params.items() if value is not None}


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


class AuftragCommand:
    """Python-side AUFTRAG description that can be sent through the bridge."""

    mission_type = ""

    def to_params(self) -> dict[str, Any]:
        """Return flat Lua command parameters for this AUFTRAG."""

        return {}


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


Auftrag_BAI = AuftragBAI
Auftrag_BOMBCARPET = AuftragBOMBCARPET
Auftrag_BOMBING = AuftragBOMBING
Auftrag_BOMBRUNWAY = AuftragBOMBRUNWAY
Auftrag_ARTY = AuftragARTY
Auftrag_ORBIT = AuftragORBIT
Auftrag_CAP = AuftragCAP
Auftrag_CAS = AuftragCAS
Auftrag_CASENHANCED = AuftragCASENHANCED
Auftrag_FAC = AuftragFAC
Auftrag_FACA = AuftragFACA
Auftrag_ESCORT = AuftragESCORT
Auftrag_GROUNDESCORT = AuftragGROUNDESCORT
Auftrag_SEAD = AuftragSEAD
Auftrag_STRIKE = AuftragSTRIKE


__all__ = [
    "AuftragARTY",
    "AuftragBAI",
    "AuftragBOMBCARPET",
    "AuftragBOMBING",
    "AuftragBOMBRUNWAY",
    "AuftragCAP",
    "AuftragCAS",
    "AuftragCASENHANCED",
    "AuftragCommand",
    "AuftragESCORT",
    "AuftragEvent",
    "AuftragFAC",
    "AuftragFACA",
    "AuftragGROUNDESCORT",
    "AuftragORBIT",
    "AuftragSEAD",
    "AuftragSTRIKE",
    "Auftrag_ARTY",
    "Auftrag_BAI",
    "Auftrag_BOMBCARPET",
    "Auftrag_BOMBING",
    "Auftrag_BOMBRUNWAY",
    "Auftrag_CAP",
    "Auftrag_CAS",
    "Auftrag_CASENHANCED",
    "Auftrag_ESCORT",
    "Auftrag_FAC",
    "Auftrag_FACA",
    "Auftrag_GROUNDESCORT",
    "Auftrag_ORBIT",
    "Auftrag_SEAD",
    "Auftrag_STRIKE",
]
