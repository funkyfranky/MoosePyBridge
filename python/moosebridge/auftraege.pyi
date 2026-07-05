from __future__ import annotations

from typing import Any, Sequence


class GeneralSet:
    object_ids: tuple[str, ...]
    object_type: str
    def __init__(self, *object_ids: str) -> None: ...
    def to_params_value(self) -> list[str]: ...


class GroupSet(GeneralSet): ...


class AuftragEvent:
    event: str
    auftrag_id: str
    fsm_event: str | None
    status: str | None
    from_state: str | None
    to_state: str | None
    raw: dict[str, Any] | None
    def __init__(
        self,
        event: str,
        auftrag_id: str,
        fsm_event: str | None = None,
        status: str | None = None,
        from_state: str | None = None,
        to_state: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None: ...
    @classmethod
    def from_message(cls, message: dict[str, Any]) -> AuftragEvent: ...
    def short_text(self) -> str: ...


class AuftragCommand:
    mission_type: str
    clock_start: str | float | int | None
    clock_stop: str | float | int | None
    duration: float | int | None
    def set_time(self, start: str | float | int | None = None, stop: str | float | int | None = None) -> AuftragCommand: ...
    def set_duration(self, duration: float | int | None) -> AuftragCommand: ...
    def to_params(self) -> dict[str, Any]: ...
    def timing_params(self) -> dict[str, Any]: ...


class AuftragBAI(AuftragCommand):
    def __init__(self, target: str, altitude_ft: float | None = None) -> None: ...


class AuftragBOMBING(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        altitude_ft: float | None = None,
        engage_weapon_type: int | None = None,
        divebomb: bool | None = None,
    ) -> None: ...


class AuftragARTY(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        nshots: float | None = None,
        radius_m: float | None = None,
    ) -> None: ...


class AuftragORBIT(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        altitude_ft: float | None = None,
        speed_kts: float | None = None,
        heading_deg: float | None = None,
        leg_nm: float | None = None,
    ) -> None: ...


class AuftragONGUARD(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
    ) -> None: ...


class AuftragAWACS(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        altitude_ft: float | None = None,
        speed_kts: float | None = None,
        heading_deg: float | None = None,
        leg_nm: float | None = None,
    ) -> None: ...


class AuftragTANKER(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        altitude_ft: float | None = None,
        speed_kts: float | None = None,
        heading_deg: float | None = None,
        leg_nm: float | None = None,
        refuel_system: int | None = None,
    ) -> None: ...


class AuftragCAP(AuftragCommand):
    def __init__(
        self,
        zone: str,
        altitude_ft: float | None = None,
        speed_kts: float | None = None,
        coordinate: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        heading_deg: float | None = None,
        leg_nm: float | None = None,
        target_types: Sequence[str] | None = None,
    ) -> None: ...


class AuftragCAS(AuftragCommand):
    def __init__(
        self,
        zone: str,
        altitude_ft: float | None = None,
        speed_kts: float | None = None,
        coordinate: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        heading_deg: float | None = None,
        leg_nm: float | None = None,
        target_types: Sequence[str] | None = None,
    ) -> None: ...


class AuftragCASENHANCED(AuftragCommand):
    def __init__(
        self,
        zone: str,
        altitude_ft: float | None = None,
        speed_kts: float | None = None,
        range_max_nm: float | None = None,
        no_engage_zones: Sequence[str] | None = None,
        target_types: Sequence[str] | None = None,
    ) -> None: ...


class AuftragFAC(AuftragCommand):
    def __init__(
        self,
        zone: str,
        speed_kts: float | None = None,
        altitude_ft: float | None = None,
        frequency_mhz: float | None = None,
        modulation: int | None = None,
    ) -> None: ...


class AuftragPATROLZONE(AuftragCommand):
    def __init__(
        self,
        zone: str,
        speed_kts: float | None = None,
        altitude_ft: float | None = None,
        formation: str | None = None,
    ) -> None: ...


class AuftragAMMOSUPPLY(AuftragCommand):
    def __init__(self, zone: str) -> None: ...


class AuftragFUELSUPPLY(AuftragCommand):
    def __init__(self, zone: str) -> None: ...


class AuftragREARMING(AuftragCommand):
    def __init__(self, zone: str) -> None: ...


class AuftragAIRDEFENSE(AuftragCommand):
    def __init__(self, zone: str) -> None: ...


class AuftragEWR(AuftragCommand):
    def __init__(self, zone: str) -> None: ...


class AuftragNOTHING(AuftragCommand):
    def __init__(self, zone: str) -> None: ...


class AuftragFACA(AuftragCommand):
    def __init__(
        self,
        target: str,
        designation: str | None = None,
        data_link: bool | None = None,
        frequency_mhz: float | None = None,
        modulation: int | None = None,
    ) -> None: ...


class AuftragSEAD(AuftragCommand):
    def __init__(self, target: str, altitude_ft: float | None = None) -> None: ...


class AuftragANTISHIP(AuftragCommand):
    def __init__(self, target: str, altitude_ft: float | None = None) -> None: ...


class AuftragINTERCEPT(AuftragCommand):
    def __init__(self, target: str) -> None: ...


class AuftragSTRIKE(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        altitude_ft: float | None = None,
        engage_weapon_type: int | None = None,
    ) -> None: ...


class AuftragSTRAFING(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        altitude_ft: float | None = None,
        length_m: float | None = None,
    ) -> None: ...


class AuftragBOMBRUNWAY(AuftragCommand):
    def __init__(self, target: str, altitude_ft: float | None = None) -> None: ...


class AuftragBOMBCARPET(AuftragCommand):
    def __init__(
        self,
        target: str | None = None,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        altitude_ft: float | None = None,
        carpet_length_m: float | None = None,
    ) -> None: ...


class AuftragGROUNDESCORT(AuftragCommand):
    def __init__(
        self,
        target: str,
        orbit_distance_nm: float | None = None,
        target_types: Sequence[str] | None = None,
    ) -> None: ...


class AuftragGROUNDATTACK(AuftragCommand):
    def __init__(self, target: str, speed_kts: float | None = None, formation: str | None = None) -> None: ...


class AuftragNAVALENGAGEMENT(AuftragCommand):
    def __init__(self, target: str, speed_kts: float | None = None, depth_m: float | None = None) -> None: ...


class AuftragESCORT(AuftragCommand):
    def __init__(
        self,
        target: str,
        offset_x: float | None = None,
        offset_y: float | None = None,
        offset_z: float | None = None,
        engage_max_distance_nm: float | None = None,
        target_types: Sequence[str] | None = None,
    ) -> None: ...


class AuftragRESCUEHELO(AuftragCommand):
    def __init__(self, target: str) -> None: ...


class AuftragTROOPTRANSPORT(AuftragCommand):
    def __init__(
        self,
        transport_groups: str | Sequence[str] | GroupSet,
        dropoff: str | None = None,
        dropoff_x: float | None = None,
        dropoff_y: float | None = None,
        dropoff_z: float | None = None,
        pickup: str | None = None,
        pickup_x: float | None = None,
        pickup_y: float | None = None,
        pickup_z: float | None = None,
        pickup_radius_m: float | None = None,
    ) -> None: ...


Auftrag_ARTY: type[AuftragARTY]
Auftrag_AIRDEFENSE: type[AuftragAIRDEFENSE]
Auftrag_AMMOSUPPLY: type[AuftragAMMOSUPPLY]
Auftrag_ANTISHIP: type[AuftragANTISHIP]
Auftrag_AWACS: type[AuftragAWACS]
Auftrag_BAI: type[AuftragBAI]
Auftrag_BOMBCARPET: type[AuftragBOMBCARPET]
Auftrag_BOMBING: type[AuftragBOMBING]
Auftrag_BOMBRUNWAY: type[AuftragBOMBRUNWAY]
Auftrag_CAP: type[AuftragCAP]
Auftrag_CAS: type[AuftragCAS]
Auftrag_CASENHANCED: type[AuftragCASENHANCED]
Auftrag_ESCORT: type[AuftragESCORT]
Auftrag_EWR: type[AuftragEWR]
Auftrag_FAC: type[AuftragFAC]
Auftrag_FACA: type[AuftragFACA]
Auftrag_FUELSUPPLY: type[AuftragFUELSUPPLY]
Auftrag_GROUNDATTACK: type[AuftragGROUNDATTACK]
Auftrag_GROUNDESCORT: type[AuftragGROUNDESCORT]
Auftrag_INTERCEPT: type[AuftragINTERCEPT]
Auftrag_NAVALENGAGEMENT: type[AuftragNAVALENGAGEMENT]
Auftrag_NOTHING: type[AuftragNOTHING]
Auftrag_ONGUARD: type[AuftragONGUARD]
Auftrag_ORBIT: type[AuftragORBIT]
Auftrag_PATROLZONE: type[AuftragPATROLZONE]
Auftrag_RESCUEHELO: type[AuftragRESCUEHELO]
Auftrag_REARMING: type[AuftragREARMING]
Auftrag_SEAD: type[AuftragSEAD]
Auftrag_STRAFING: type[AuftragSTRAFING]
Auftrag_STRIKE: type[AuftragSTRIKE]
Auftrag_TANKER: type[AuftragTANKER]
Auftrag_TROOPTRANSPORT: type[AuftragTROOPTRANSPORT]

__all__: list[str]
