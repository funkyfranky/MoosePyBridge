"""Normalized infrastructure sites and bounded DCS scenery surveys."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .topography import TopographyFeature, TopographyLayer


INFRASTRUCTURE_SITES_SCHEMA = "moosebridge.infrastructure_sites"
INFRASTRUCTURE_SITES_SCHEMA_VERSION = 1


class InfrastructureSiteKind(StrEnum):
    ENERGY = "energy"
    FUEL_STORAGE = "fuel_storage"
    MILITARY = "military"
    INDUSTRIAL = "industrial"
    MARITIME = "maritime"


class InfrastructureVerificationState(StrEnum):
    UNVERIFIED = "unverified"
    DCS_SCENERY_MATCHED = "dcs_scenery_matched"
    DCS_MISSION_OBJECT_MATCHED = "dcs_mission_object_matched"
    DCS_VISUAL_ONLY = "dcs_visual_only"
    NOT_REPRESENTED_IN_DCS = "not_represented_in_dcs"


class InfrastructureImportanceTier(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOCAL = "local"


class EnergySource(StrEnum):
    COAL = "coal"
    GAS = "gas"
    OIL = "oil"
    NUCLEAR = "nuclear"
    HYDRO = "hydro"
    BIOMASS = "biomass"
    WASTE = "waste"
    SOLAR = "solar"
    WIND = "wind"
    BIOGAS = "biogas"
    BATTERY = "battery"
    OTHER = "other"
    UNKNOWN = "unknown"


class EnergyRole(StrEnum):
    GENERATION = "generation"
    GRID_SUBSTATION = "grid_substation"
    CONVERTER_STATION = "converter_station"


class FuelStorageRole(StrEnum):
    REFINERY = "refinery"
    TERMINAL = "terminal"
    TANK_FARM = "tank_farm"
    GAS_STORAGE = "gas_storage"
    BULK_STORAGE = "bulk_storage"


class StoredCommodity(StrEnum):
    CRUDE_OIL = "crude_oil"
    PETROLEUM = "petroleum"
    DIESEL = "diesel"
    GASOLINE = "gasoline"
    JET_FUEL = "jet_fuel"
    LPG = "lpg"
    LNG = "lng"
    NATURAL_GAS = "natural_gas"
    OTHER_FUEL = "other_fuel"


class MilitaryRole(StrEnum):
    BASE = "base"
    BARRACKS = "barracks"
    NAVAL_BASE = "naval_base"
    DEPOT = "depot"
    AMMUNITION_STORAGE = "ammunition_storage"
    FUEL_STORAGE = "fuel_storage"
    TRAINING_AREA = "training_area"
    FIRING_RANGE = "firing_range"
    RADAR_SITE = "radar_site"
    COMMUNICATIONS_SITE = "communications_site"
    BUNKER_COMPLEX = "bunker_complex"
    MISSILE_SITE = "missile_site"


class IndustrialRole(StrEnum):
    GENERAL_MANUFACTURING = "general_manufacturing"
    HEAVY_INDUSTRY = "heavy_industry"
    METALWORKS = "metalworks"
    CHEMICAL = "chemical"
    MACHINERY = "machinery"
    AUTOMOTIVE = "automotive"
    ELECTRONICS = "electronics"
    CONSTRUCTION_MATERIALS = "construction_materials"
    FOOD_PROCESSING = "food_processing"
    TIMBER_PAPER = "timber_paper"
    SHIPYARD = "shipyard"
    EXTRACTION = "extraction"


class MaritimeRole(StrEnum):
    HARBOUR = "harbour"
    COMMERCIAL_PORT = "commercial_port"
    CARGO_TERMINAL = "cargo_terminal"
    CONTAINER_TERMINAL = "container_terminal"
    BULK_TERMINAL = "bulk_terminal"
    RORO_TERMINAL = "roro_terminal"
    FERRY_TERMINAL = "ferry_terminal"
    FISHING_PORT = "fishing_port"
    PASSENGER_TERMINAL = "passenger_terminal"
    SHIPYARD = "shipyard"


class MaritimeCargo(StrEnum):
    GENERAL_CARGO = "general_cargo"
    CONTAINERS = "containers"
    DRY_BULK = "dry_bulk"
    LIQUID_BULK = "liquid_bulk"
    PETROLEUM = "petroleum"
    GAS = "gas"
    COAL = "coal"
    ORE = "ore"
    GRAIN = "grain"
    TIMBER = "timber"
    VEHICLES = "vehicles"
    PASSENGERS = "passengers"
    FISH = "fish"


@dataclass(slots=True, frozen=True)
class InfrastructureCandidatePolicy:
    """Theater-specific admission policy for external infrastructure data."""

    theater_id: str
    scenario_reference_year: int | None = None
    excluded_energy_sources: frozenset[EnergySource] = frozenset()

    def admits_energy_sources(self, sources: Iterable[EnergySource]) -> bool:
        materialized = frozenset(sources)
        return not materialized.intersection(self.excluded_energy_sources)


GERMANY_CW_INFRASTRUCTURE_POLICY = InfrastructureCandidatePolicy(
    theater_id="GermanyCW",
    scenario_reference_year=1989,
    excluded_energy_sources=frozenset(
        {EnergySource.SOLAR, EnergySource.WIND, EnergySource.BIOGAS, EnergySource.BATTERY}
    ),
)


def infrastructure_policy_for_theater(theater_id: str) -> InfrastructureCandidatePolicy:
    """Return the built-in candidate policy, defaulting to no exclusions."""

    if theater_id.strip().casefold() == "germanycw":
        return GERMANY_CW_INFRASTRUCTURE_POLICY
    return InfrastructureCandidatePolicy(theater_id=theater_id)


@dataclass(slots=True, frozen=True)
class InfrastructureSite:
    """Shared stable identity and geometry for one infrastructure location."""

    site_id: str
    kind: InfrastructureSiteKind
    geometry: dict[str, Any]
    latitude: float
    longitude: float
    source: str
    confidence: float
    name: str | None = None
    source_ids: tuple[str, ...] = ()
    scenario_reference_year: int | None = None
    verification_state: InfrastructureVerificationState = InfrastructureVerificationState.UNVERIFIED
    component_ids: tuple[str, ...] = ()
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.site_id.strip() or not self.source.strip():
            raise ValueError("infrastructure site requires site_id and source")
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ValueError("infrastructure site coordinates are outside WGS84 bounds")
        if not 0 <= self.confidence <= 1:
            raise ValueError("infrastructure confidence must be between zero and one")

    def _specific_properties(self) -> dict[str, Any]:
        return {}

    def to_geojson_feature(self) -> dict[str, Any]:
        properties = {
            "layer": _site_layer(self.kind),
            "object_id": self.site_id,
            "name": self.name,
            "object_type": _site_object_type(self.kind),
            "site_kind": self.kind.value,
            "coordinate_system": "WGS84",
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source": self.source,
            "source_ids": list(self.source_ids),
            "confidence": self.confidence,
            "scenario_reference_year": self.scenario_reference_year,
            "verification_state": self.verification_state.value,
            "component_ids": list(self.component_ids),
            **self._specific_properties(),
            **self.properties,
        }
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {key: value for key, value in properties.items() if value is not None},
        }

    @classmethod
    def from_geojson_feature(cls, feature: Mapping[str, Any]) -> "InfrastructureSite":
        if feature.get("type") != "Feature":
            raise ValueError("infrastructure site must be a GeoJSON Feature")
        properties = dict(feature.get("properties") or {})
        kind = InfrastructureSiteKind(str(properties.get("site_kind") or ""))
        known = {
            "layer", "object_id", "name", "object_type", "site_kind", "category", "map_category", "coordinate_system",
            "latitude", "longitude", "source", "source_ids", "confidence", "scenario_reference_year",
            "verification_state", "component_ids", "energy_sources", "output_mw", "roles",
            "storage_roles", "commodities", "capacity_m3", "products", "footprint_area_m2",
            "importance_score", "importance_tier", "energy_roles", "voltage_kv",
            "maritime_roles", "cargo_types", "quay_length_m", "berth_count",
        }
        common = dict(
            site_id=str(properties.get("object_id") or ""),
            kind=kind,
            geometry=dict(feature.get("geometry") or {}),
            latitude=float(properties.get("latitude") or 0),
            longitude=float(properties.get("longitude") or 0),
            source=str(properties.get("source") or ""),
            confidence=float(properties.get("confidence") or 0),
            name=_optional_string(properties.get("name")),
            source_ids=tuple(str(value) for value in properties.get("source_ids") or ()),
            scenario_reference_year=_optional_int(properties.get("scenario_reference_year")),
            verification_state=InfrastructureVerificationState(
                str(properties.get("verification_state") or InfrastructureVerificationState.UNVERIFIED.value)
            ),
            component_ids=tuple(str(value) for value in properties.get("component_ids") or ()),
            properties={key: value for key, value in properties.items() if key not in known},
        )
        if kind is InfrastructureSiteKind.ENERGY:
            return EnergySite(
                **common,
                roles=tuple(
                    EnergyRole(str(value)) for value in properties.get("energy_roles") or (EnergyRole.GENERATION.value,)
                ),
                energy_sources=tuple(
                    EnergySource(str(value)) for value in properties.get("energy_sources") or (EnergySource.UNKNOWN.value,)
                ),
                output_mw=_optional_float(properties.get("output_mw")),
                voltage_kv=_optional_float(properties.get("voltage_kv")),
                footprint_area_m2=_optional_float(properties.get("footprint_area_m2")),
                importance_score=float(properties.get("importance_score") or 0),
                importance_tier=InfrastructureImportanceTier(
                    str(properties.get("importance_tier") or InfrastructureImportanceTier.LOCAL.value)
                ),
            )
        if kind is InfrastructureSiteKind.FUEL_STORAGE:
            return FuelStorageSite(
                **common,
                storage_roles=tuple(FuelStorageRole(str(value)) for value in properties.get("storage_roles") or ()),
                commodities=tuple(StoredCommodity(str(value)) for value in properties.get("commodities") or ()),
                capacity_m3=_optional_float(properties.get("capacity_m3")),
            )
        if kind is InfrastructureSiteKind.MILITARY:
            return MilitarySite(
                **common,
                roles=tuple(MilitaryRole(str(value)) for value in properties.get("roles") or ()),
                footprint_area_m2=_optional_float(properties.get("footprint_area_m2")),
                importance_score=float(properties.get("importance_score") or 0),
                importance_tier=InfrastructureImportanceTier(
                    str(properties.get("importance_tier") or InfrastructureImportanceTier.LOCAL.value)
                ),
            )
        if kind is InfrastructureSiteKind.INDUSTRIAL:
            return IndustrialSite(
                **common,
                roles=tuple(IndustrialRole(str(value)) for value in properties.get("roles") or ()),
                products=tuple(str(value) for value in properties.get("products") or ()),
                footprint_area_m2=_optional_float(properties.get("footprint_area_m2")),
                importance_score=float(properties.get("importance_score") or 0),
                importance_tier=InfrastructureImportanceTier(
                    str(properties.get("importance_tier") or InfrastructureImportanceTier.LOCAL.value)
                ),
            )
        if kind is InfrastructureSiteKind.MARITIME:
            return MaritimeSite(
                **common,
                roles=tuple(MaritimeRole(str(value)) for value in properties.get("maritime_roles") or ()),
                cargo_types=tuple(MaritimeCargo(str(value)) for value in properties.get("cargo_types") or ()),
                footprint_area_m2=_optional_float(properties.get("footprint_area_m2")),
                quay_length_m=_optional_float(properties.get("quay_length_m")),
                berth_count=int(properties.get("berth_count") or 0),
                importance_score=float(properties.get("importance_score") or 0),
                importance_tier=InfrastructureImportanceTier(
                    str(properties.get("importance_tier") or InfrastructureImportanceTier.LOCAL.value)
                ),
            )
        raise ValueError(f"unsupported infrastructure site kind: {kind}")


@dataclass(slots=True, frozen=True)
class EnergySite(InfrastructureSite):
    """Normalized generation site or strategically relevant grid node."""

    roles: tuple[EnergyRole, ...] = (EnergyRole.GENERATION,)
    energy_sources: tuple[EnergySource, ...] = (EnergySource.UNKNOWN,)
    output_mw: float | None = None
    voltage_kv: float | None = None
    footprint_area_m2: float | None = None
    importance_score: float = 0.0
    importance_tier: InfrastructureImportanceTier = InfrastructureImportanceTier.LOCAL

    def __post_init__(self) -> None:
        InfrastructureSite.__post_init__(self)
        if self.kind is not InfrastructureSiteKind.ENERGY:
            raise ValueError("EnergySite kind must be energy")
        if not self.roles:
            raise ValueError("energy site requires at least one role")
        if self.output_mw is not None and self.output_mw < 0:
            raise ValueError("energy output must not be negative")
        if self.voltage_kv is not None and self.voltage_kv < 0:
            raise ValueError("energy voltage must not be negative")
        if self.footprint_area_m2 is not None and self.footprint_area_m2 < 0:
            raise ValueError("energy footprint must not be negative")
        if not 0 <= self.importance_score <= 100:
            raise ValueError("energy importance score must be between zero and 100")

    def _specific_properties(self) -> dict[str, Any]:
        return {
            "category": "energy_site",
            "energy_roles": [role.value for role in self.roles],
            "map_category": self.roles[0].value,
            "energy_sources": [source.value for source in self.energy_sources],
            "output_mw": self.output_mw,
            "voltage_kv": self.voltage_kv,
            "footprint_area_m2": self.footprint_area_m2,
            "importance_score": self.importance_score,
            "importance_tier": self.importance_tier.value,
        }


@dataclass(slots=True, frozen=True)
class FuelStorageSite(InfrastructureSite):
    """A refinery, terminal, tank farm, or other explicit bulk-fuel site."""

    storage_roles: tuple[FuelStorageRole, ...] = ()
    commodities: tuple[StoredCommodity, ...] = ()
    capacity_m3: float | None = None

    def __post_init__(self) -> None:
        InfrastructureSite.__post_init__(self)
        if self.kind is not InfrastructureSiteKind.FUEL_STORAGE:
            raise ValueError("FuelStorageSite kind must be fuel_storage")
        if not self.storage_roles or not self.commodities:
            raise ValueError("fuel-storage site requires a role and commodity")
        if self.capacity_m3 is not None and self.capacity_m3 < 0:
            raise ValueError("fuel-storage capacity must not be negative")

    def _specific_properties(self) -> dict[str, Any]:
        return {
            "category": "fuel_storage_site",
            "storage_roles": [role.value for role in self.storage_roles],
            "commodities": [commodity.value for commodity in self.commodities],
            "capacity_m3": self.capacity_m3,
        }


@dataclass(slots=True, frozen=True)
class MilitarySite(InfrastructureSite):
    """Military installation kept separate from civilian infrastructure."""

    roles: tuple[MilitaryRole, ...] = ()
    footprint_area_m2: float | None = None
    importance_score: float = 0.0
    importance_tier: InfrastructureImportanceTier = InfrastructureImportanceTier.LOCAL

    def __post_init__(self) -> None:
        InfrastructureSite.__post_init__(self)
        if self.kind is not InfrastructureSiteKind.MILITARY:
            raise ValueError("MilitarySite kind must be military")
        if not self.roles:
            raise ValueError("military site requires at least one role")
        if self.footprint_area_m2 is not None and self.footprint_area_m2 < 0:
            raise ValueError("military footprint must not be negative")
        if not 0 <= self.importance_score <= 100:
            raise ValueError("military importance score must be between zero and 100")

    def _specific_properties(self) -> dict[str, Any]:
        return {
            "category": "military_site",
            "roles": [role.value for role in self.roles],
            "footprint_area_m2": self.footprint_area_m2,
            "importance_score": self.importance_score,
            "importance_tier": self.importance_tier.value,
        }


@dataclass(slots=True, frozen=True)
class IndustrialSite(InfrastructureSite):
    """A conservatively admitted industrial plant or works complex."""

    roles: tuple[IndustrialRole, ...] = ()
    products: tuple[str, ...] = ()
    footprint_area_m2: float | None = None
    importance_score: float = 0.0
    importance_tier: InfrastructureImportanceTier = InfrastructureImportanceTier.LOCAL

    def __post_init__(self) -> None:
        InfrastructureSite.__post_init__(self)
        if self.kind is not InfrastructureSiteKind.INDUSTRIAL:
            raise ValueError("IndustrialSite kind must be industrial")
        if not self.roles:
            raise ValueError("industrial site requires at least one role")
        if self.footprint_area_m2 is not None and self.footprint_area_m2 < 0:
            raise ValueError("industrial footprint must not be negative")
        if not 0 <= self.importance_score <= 100:
            raise ValueError("industrial importance score must be between zero and 100")

    def _specific_properties(self) -> dict[str, Any]:
        return {
            "category": "industrial_site",
            "roles": [role.value for role in self.roles],
            "products": list(self.products),
            "footprint_area_m2": self.footprint_area_m2,
            "importance_score": self.importance_score,
            "importance_tier": self.importance_tier.value,
        }


@dataclass(slots=True, frozen=True)
class MaritimeSite(InfrastructureSite):
    """A normalized civilian port, terminal, or shipyard complex."""

    roles: tuple[MaritimeRole, ...] = ()
    cargo_types: tuple[MaritimeCargo, ...] = ()
    footprint_area_m2: float | None = None
    quay_length_m: float | None = None
    berth_count: int = 0
    importance_score: float = 0.0
    importance_tier: InfrastructureImportanceTier = InfrastructureImportanceTier.LOCAL

    def __post_init__(self) -> None:
        InfrastructureSite.__post_init__(self)
        if self.kind is not InfrastructureSiteKind.MARITIME:
            raise ValueError("MaritimeSite kind must be maritime")
        if not self.roles:
            raise ValueError("maritime site requires at least one role")
        if self.footprint_area_m2 is not None and self.footprint_area_m2 < 0:
            raise ValueError("maritime footprint must not be negative")
        if self.quay_length_m is not None and self.quay_length_m < 0:
            raise ValueError("maritime quay length must not be negative")
        if self.berth_count < 0:
            raise ValueError("maritime berth count must not be negative")
        if not 0 <= self.importance_score <= 100:
            raise ValueError("maritime importance score must be between zero and 100")

    def _specific_properties(self) -> dict[str, Any]:
        return {
            "category": "maritime_site",
            "maritime_roles": [role.value for role in self.roles],
            "map_category": self.roles[0].value,
            "cargo_types": [cargo.value for cargo in self.cargo_types],
            "footprint_area_m2": self.footprint_area_m2,
            "quay_length_m": self.quay_length_m,
            "berth_count": self.berth_count,
            "importance_score": self.importance_score,
            "importance_tier": self.importance_tier.value,
        }


@dataclass(slots=True, frozen=True)
class TheaterInfrastructureSites:
    theater_id: str
    sites: tuple[InfrastructureSite, ...] = ()
    schema_version: int = INFRASTRUCTURE_SITES_SCHEMA_VERSION
    scenario_reference_year: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.theater_id.strip():
            raise ValueError("infrastructure sites require theater_id")
        if self.schema_version != INFRASTRUCTURE_SITES_SCHEMA_VERSION:
            raise ValueError(f"unsupported infrastructure schema version: {self.schema_version}")
        ids = [site.site_id for site in self.sites]
        if len(ids) != len(set(ids)):
            raise ValueError("infrastructure site_id values must be unique")

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [site.to_geojson_feature() for site in self.sites],
            "properties": {
                "schema": INFRASTRUCTURE_SITES_SCHEMA,
                "schema_version": self.schema_version,
                "theater_id": self.theater_id,
                "scenario_reference_year": self.scenario_reference_year,
                "site_count": len(self.sites),
                **self.metadata,
            },
        }

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.to_geojson(), stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
        temporary.replace(target)
        return target

    @classmethod
    def from_geojson(cls, payload: Mapping[str, Any]) -> "TheaterInfrastructureSites":
        if payload.get("type") != "FeatureCollection":
            raise ValueError("infrastructure artifact must be a GeoJSON FeatureCollection")
        properties = dict(payload.get("properties") or {})
        if properties.get("schema") != INFRASTRUCTURE_SITES_SCHEMA:
            raise ValueError("not a MooseBridge infrastructure-site artifact")
        raw_features = payload.get("features")
        if not isinstance(raw_features, list):
            raise ValueError("infrastructure artifact features must be a list")
        known = {"schema", "schema_version", "theater_id", "scenario_reference_year", "site_count"}
        return cls(
            theater_id=str(properties.get("theater_id") or ""),
            schema_version=int(properties.get("schema_version") or INFRASTRUCTURE_SITES_SCHEMA_VERSION),
            scenario_reference_year=_optional_int(properties.get("scenario_reference_year")),
            sites=tuple(InfrastructureSite.from_geojson_feature(feature) for feature in raw_features),
            metadata={key: value for key, value in properties.items() if key not in known},
        )

    @classmethod
    def load(cls, path: str | Path) -> "TheaterInfrastructureSites":
        with Path(path).open("r", encoding="utf-8") as stream:
            return cls.from_geojson(json.load(stream))


@dataclass(slots=True, frozen=True)
class SceneryObjectSnapshot:
    object_id: str
    name: str | None
    type_name: str | None
    display_name: str | None
    x: float
    y: float
    z: float
    latitude: float
    longitude: float
    life: float | None = None
    exists: bool | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SceneryObjectSnapshot":
        required = ("x", "y", "z", "latitude", "longitude")
        if any(_optional_float(payload.get(key)) is None for key in required):
            raise ValueError("scenery object is missing coordinates")
        return cls(
            object_id=str(payload.get("object_id") or ""),
            name=_optional_string(payload.get("name")),
            type_name=_optional_string(payload.get("type_name")),
            display_name=_optional_string(payload.get("display_name")),
            x=float(payload["x"]), y=float(payload["y"]), z=float(payload["z"]),
            latitude=float(payload["latitude"]), longitude=float(payload["longitude"]),
            life=_optional_float(payload.get("life")),
            exists=payload.get("exists") if isinstance(payload.get("exists"), bool) else None,
        )


@dataclass(slots=True, frozen=True)
class ScenerySurvey:
    center: GeographicSurveyPoint
    radius_m: float
    objects: tuple[SceneryObjectSnapshot, ...]
    truncated: bool = False


@dataclass(slots=True, frozen=True)
class GeographicSurveyPoint:
    x: float
    y: float
    z: float
    latitude: float
    longitude: float


def build_energy_sites(
    features: Iterable[TopographyFeature],
    *,
    theater_id: str,
    policy: InfrastructureCandidatePolicy | None = None,
    named_cluster_radius_m: float = 1_000.0,
    major_grid_voltage_kv: float = 110.0,
) -> TheaterInfrastructureSites:
    """Normalize generation facilities and strategically relevant grid nodes."""

    selected_policy = policy or infrastructure_policy_for_theater(theater_id)
    candidates: list[_EnergyCandidate] = []
    excluded: dict[str, int] = {}
    for feature in features:
        if feature.layer is not TopographyLayer.INFRASTRUCTURE or feature.category not in {
            "power_plant", "power_substation", "power_converter",
        }:
            continue
        if not _feature_exists_in_scenario(feature, selected_policy.scenario_reference_year):
            excluded["outside_scenario_period"] = excluded.get("outside_scenario_period", 0) + 1
            continue
        tags = _osm_tags(feature.properties.get("osm_tags"))
        roles = _energy_roles(feature.category, tags)
        sources = _energy_sources(tags) if EnergyRole.GENERATION in roles else frozenset()
        rejected = sources.intersection(selected_policy.excluded_energy_sources)
        if rejected:
            for source in rejected:
                excluded[source.value] = excluded.get(source.value, 0) + 1
            continue
        voltage_kv = _parse_voltage_kv(tags)
        if (
            EnergyRole.GRID_SUBSTATION in roles
            and EnergyRole.CONVERTER_STATION not in roles
            and (voltage_kv is None or voltage_kv < major_grid_voltage_kv)
        ):
            excluded["minor_grid_node"] = excluded.get("minor_grid_node", 0) + 1
            continue
        longitude, latitude = _representative_coordinate(feature.geometry)
        candidates.append(_EnergyCandidate(
            feature=feature,
            latitude=latitude,
            longitude=longitude,
            roles=roles,
            sources=sources,
            output_mw=_parse_output_mw(tags),
            voltage_kv=voltage_kv,
            operator=_optional_string(tags.get("operator")),
            area_m2=_geometry_area_m2(feature.geometry),
        ))
    clusters = _cluster_energy_candidates(candidates, named_cluster_radius_m)
    sites = tuple(_energy_site_from_cluster(cluster, selected_policy) for cluster in clusters)
    return TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=selected_policy.scenario_reference_year,
        sites=sites,
        metadata={
            "raw_energy_candidate_count": len(candidates),
            "excluded_energy_source_counts": {
                key: value for key, value in excluded.items() if key in {source.value for source in EnergySource}
            },
            "excluded_energy_counts": excluded,
            "named_cluster_radius_m": named_cluster_radius_m,
            "major_grid_voltage_kv": major_grid_voltage_kv,
        },
    )


@dataclass(slots=True, frozen=True)
class _EnergyCandidate:
    feature: TopographyFeature
    latitude: float
    longitude: float
    roles: frozenset[EnergyRole]
    sources: frozenset[EnergySource]
    output_mw: float | None
    voltage_kv: float | None
    operator: str | None
    area_m2: float


@dataclass(slots=True, frozen=True)
class _FuelCandidate:
    feature: TopographyFeature
    latitude: float
    longitude: float
    roles: frozenset[FuelStorageRole]
    commodities: frozenset[StoredCommodity]
    anchor: bool
    capacity_m3: float | None
    operator: str | None


_FUEL_ANCHOR_ROLES: dict[str, FuelStorageRole] = {
    "refinery": FuelStorageRole.REFINERY,
    "oil": FuelStorageRole.TERMINAL,
    "oil_storage": FuelStorageRole.TANK_FARM,
    "distillates_storage": FuelStorageRole.TANK_FARM,
    "gas": FuelStorageRole.TERMINAL,
    "natural_gas": FuelStorageRole.GAS_STORAGE,
    "gas_storage": FuelStorageRole.GAS_STORAGE,
    "gas_cavern": FuelStorageRole.GAS_STORAGE,
    "storage": FuelStorageRole.BULK_STORAGE,
    "depot": FuelStorageRole.TERMINAL,
}

_FUEL_ALIASES: dict[str, StoredCommodity] = {
    "crude": StoredCommodity.CRUDE_OIL,
    "crude_oil": StoredCommodity.CRUDE_OIL,
    "oil": StoredCommodity.PETROLEUM,
    "petroleum": StoredCommodity.PETROLEUM,
    "fuel": StoredCommodity.PETROLEUM,
    "distillates": StoredCommodity.PETROLEUM,
    "diesel": StoredCommodity.DIESEL,
    "gasoline": StoredCommodity.GASOLINE,
    "petrol": StoredCommodity.GASOLINE,
    "kerosene": StoredCommodity.JET_FUEL,
    "jet_fuel": StoredCommodity.JET_FUEL,
    "aviation_fuel": StoredCommodity.JET_FUEL,
    "lpg": StoredCommodity.LPG,
    "liquefied_petroleum_gas": StoredCommodity.LPG,
    "lng": StoredCommodity.LNG,
    "liquefied_natural_gas": StoredCommodity.LNG,
    "gas": StoredCommodity.NATURAL_GAS,
    "natural_gas": StoredCommodity.NATURAL_GAS,
    "hydrocarbons": StoredCommodity.OTHER_FUEL,
}


def build_fuel_storage_sites(
    features: Iterable[TopographyFeature],
    *,
    theater_id: str,
    policy: InfrastructureCandidatePolicy | None = None,
    anchor_cluster_radius_m: float = 400.0,
    component_radius_m: float = 750.0,
    standalone_cluster_radius_m: float = 250.0,
) -> TheaterInfrastructureSites:
    """Build conservative bulk-fuel sites from explicit OSM evidence."""

    if min(anchor_cluster_radius_m, component_radius_m, standalone_cluster_radius_m) < 0:
        raise ValueError("fuel-storage cluster radii must not be negative")
    selected_policy = policy or infrastructure_policy_for_theater(theater_id)
    candidates: list[_FuelCandidate] = []
    excluded_unknown_tanks = 0
    excluded_military = 0
    excluded_ambiguous_facilities = 0
    for feature in features:
        if feature.layer is not TopographyLayer.INFRASTRUCTURE:
            continue
        tags = _osm_tags(feature.properties.get("osm_tags"))
        if tags.get("military") or tags.get("landuse") == "military":
            excluded_military += 1
            continue
        commodities = _fuel_commodities(tags, feature.category)
        role = _fuel_anchor_role(feature.category, tags, feature.name)
        is_tank = feature.category == "storage_tank"
        if is_tank and not commodities:
            excluded_unknown_tanks += 1
            continue
        if role is None and not is_tank:
            if feature.category in _FUEL_ANCHOR_ROLES:
                excluded_ambiguous_facilities += 1
            continue
        if role in {FuelStorageRole.BULK_STORAGE, FuelStorageRole.TERMINAL} and not commodities:
            continue
        if not commodities:
            commodities = _category_commodities(feature.category)
        if not commodities:
            continue
        longitude, latitude = _representative_coordinate(feature.geometry)
        roles = frozenset({role}) if role is not None else frozenset({FuelStorageRole.TANK_FARM})
        candidates.append(_FuelCandidate(
            feature=feature,
            latitude=latitude,
            longitude=longitude,
            roles=roles,
            commodities=commodities,
            anchor=not is_tank,
            capacity_m3=_parse_capacity_m3(tags),
            operator=_optional_string(tags.get("operator")),
        ))

    clusters = _cluster_fuel_candidates(
        candidates,
        anchor_cluster_radius_m=anchor_cluster_radius_m,
        component_radius_m=component_radius_m,
        standalone_cluster_radius_m=standalone_cluster_radius_m,
    )
    admitted_clusters = [cluster for cluster in clusters if _admit_fuel_cluster(cluster)]
    sites = tuple(
        _fuel_site_from_cluster(cluster, selected_policy)
        for cluster in admitted_clusters
    )
    return TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=selected_policy.scenario_reference_year,
        sites=sites,
        metadata={
            "raw_fuel_candidate_count": len(candidates),
            "excluded_unknown_tank_count": excluded_unknown_tanks,
            "excluded_military_candidate_count": excluded_military,
            "excluded_ambiguous_facility_count": excluded_ambiguous_facilities,
            "excluded_small_standalone_tank_count": len(clusters) - len(admitted_clusters),
            "fuel_storage_cluster_radii_m": {
                "anchors": anchor_cluster_radius_m,
                "components": component_radius_m,
                "standalone_tanks": standalone_cluster_radius_m,
            },
        },
    )


@dataclass(slots=True, frozen=True)
class _MilitaryCandidate:
    feature: TopographyFeature
    latitude: float
    longitude: float
    roles: frozenset[MilitaryRole]
    role_sources: frozenset[str]
    operator: str | None


_MILITARY_TAG_ROLES: dict[str, MilitaryRole] = {
    "base": MilitaryRole.BASE,
    "yes": MilitaryRole.BASE,
    "barracks": MilitaryRole.BARRACKS,
    "naval_base": MilitaryRole.NAVAL_BASE,
    "depot": MilitaryRole.DEPOT,
    "storage": MilitaryRole.DEPOT,
    "ammunition": MilitaryRole.AMMUNITION_STORAGE,
    "amunition": MilitaryRole.AMMUNITION_STORAGE,
    "ammunition;bunker": MilitaryRole.AMMUNITION_STORAGE,
    "fuel": MilitaryRole.FUEL_STORAGE,
    "training_area": MilitaryRole.TRAINING_AREA,
    "traning_area": MilitaryRole.TRAINING_AREA,
    "range": MilitaryRole.FIRING_RANGE,
    "shooting_range": MilitaryRole.FIRING_RANGE,
    "radar": MilitaryRole.RADAR_SITE,
    "radar_facility": MilitaryRole.RADAR_SITE,
    "communications": MilitaryRole.COMMUNICATIONS_SITE,
    "airfield radio": MilitaryRole.COMMUNICATIONS_SITE,
    "bunker": MilitaryRole.BUNKER_COMPLEX,
    "missile_base": MilitaryRole.MISSILE_SITE,
}

_NON_SITE_MILITARY_TAGS = {
    "airfield", "danger_area", "exclusion_zone", "obstacle_course", "office",
    "apartments", "checkpoint", "hospital", "prison", "shelter", "support", "trench",
}

_TARGETABLE_MILITARY_ROLES = {
    MilitaryRole.BASE,
    MilitaryRole.BARRACKS,
    MilitaryRole.NAVAL_BASE,
    MilitaryRole.DEPOT,
    MilitaryRole.AMMUNITION_STORAGE,
    MilitaryRole.FUEL_STORAGE,
    MilitaryRole.RADAR_SITE,
    MilitaryRole.COMMUNICATIONS_SITE,
    MilitaryRole.BUNKER_COMPLEX,
    MilitaryRole.MISSILE_SITE,
}

_MILITARY_ROLE_IMPORTANCE = {
    MilitaryRole.MISSILE_SITE: 85.0,
    MilitaryRole.AMMUNITION_STORAGE: 80.0,
    MilitaryRole.RADAR_SITE: 75.0,
    MilitaryRole.FUEL_STORAGE: 75.0,
    MilitaryRole.NAVAL_BASE: 75.0,
    MilitaryRole.COMMUNICATIONS_SITE: 70.0,
    MilitaryRole.DEPOT: 65.0,
    MilitaryRole.BASE: 60.0,
    MilitaryRole.BUNKER_COMPLEX: 60.0,
    MilitaryRole.BARRACKS: 50.0,
    MilitaryRole.TRAINING_AREA: 25.0,
    MilitaryRole.FIRING_RANGE: 20.0,
}


def build_military_sites(
    features: Iterable[TopographyFeature],
    *,
    theater_id: str,
    policy: InfrastructureCandidatePolicy | None = None,
    named_cluster_radius_m: float = 1_000.0,
) -> TheaterInfrastructureSites:
    """Build conservative military installations from explicit OSM areas."""

    if named_cluster_radius_m < 0:
        raise ValueError("military-site cluster radius must not be negative")
    selected_policy = policy or infrastructure_policy_for_theater(theater_id)
    candidates: list[_MilitaryCandidate] = []
    excluded = {
        "airfield": 0,
        "non_site_role": 0,
        "ambiguous": 0,
        "outside_scenario_date": 0,
        "unnamed_bunker": 0,
    }
    for feature in features:
        tags = _osm_tags(feature.properties.get("osm_tags"))
        military_tag = str(tags.get("military") or "").strip().casefold()
        if feature.category != "military" and tags.get("landuse") != "military" and not military_tag:
            continue
        if _is_military_airfield(tags, military_tag):
            excluded["airfield"] += 1
            continue
        if not _feature_exists_in_scenario(feature, selected_policy.scenario_reference_year):
            excluded["outside_scenario_date"] += 1
            continue
        tagged_role = _MILITARY_TAG_ROLES.get(military_tag)
        inferred = _military_role_from_name(feature.name)
        roles: set[MilitaryRole] = set()
        role_sources: set[str] = set()
        if tagged_role is not None:
            roles.add(tagged_role)
            role_sources.add("military_tag")
        if inferred is not None:
            roles.add(inferred)
            role_sources.add("name")
        if military_tag in _NON_SITE_MILITARY_TAGS:
            roles = {inferred} if inferred is not None else set()
            role_sources = {"name"} if inferred is not None else set()
            if not roles:
                excluded["non_site_role"] += 1
                continue
        if not roles:
            excluded["ambiguous"] += 1
            continue
        if roles == {MilitaryRole.BUNKER_COMPLEX} and _is_generic_bunker_name(feature.name):
            excluded["unnamed_bunker"] += 1
            continue
        longitude, latitude = _representative_coordinate(feature.geometry)
        candidates.append(_MilitaryCandidate(
            feature=feature,
            latitude=latitude,
            longitude=longitude,
            roles=frozenset(roles),
            role_sources=frozenset(role_sources),
            operator=_optional_string(tags.get("operator")),
        ))

    clusters = _cluster_military_candidates(candidates, named_cluster_radius_m)
    sites = tuple(_military_site_from_cluster(cluster, selected_policy) for cluster in clusters)
    return TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=selected_policy.scenario_reference_year,
        sites=sites,
        metadata={
            "raw_military_candidate_count": len(candidates),
            "excluded_military_counts": excluded,
            "named_cluster_radius_m": named_cluster_radius_m,
        },
    )


@dataclass(slots=True, frozen=True)
class _IndustrialCandidate:
    feature: TopographyFeature
    latitude: float
    longitude: float
    roles: frozenset[IndustrialRole]
    role_sources: frozenset[str]
    products: frozenset[str]
    operator: str | None
    area_m2: float


_INDUSTRIAL_CATEGORY_ROLES: dict[str, IndustrialRole] = {
    "factory": IndustrialRole.GENERAL_MANUFACTURING,
    "sawmill": IndustrialRole.TIMBER_PAPER,
    "brewery": IndustrialRole.FOOD_PROCESSING,
    "food": IndustrialRole.FOOD_PROCESSING,
    "chemical": IndustrialRole.CHEMICAL,
    "shipyard": IndustrialRole.SHIPYARD,
    "mine": IndustrialRole.EXTRACTION,
    "quarry": IndustrialRole.EXTRACTION,
    "metal_processing": IndustrialRole.METALWORKS,
    "steelmaking": IndustrialRole.METALWORKS,
    "cement": IndustrialRole.CONSTRUCTION_MATERIALS,
    "glass": IndustrialRole.CONSTRUCTION_MATERIALS,
    "machinery": IndustrialRole.MACHINERY,
    "automotive": IndustrialRole.AUTOMOTIVE,
    "electronics": IndustrialRole.ELECTRONICS,
}

_NON_INDUSTRIAL_SITE_NAME_TOKENS = {
    "gewerbegebiet", "industriegebiet", "industrial park", "business park",
    "zone industrielle", "zone d'activités", "zone d’activités", "stadtwerke",
    "straßenmeisterei", "strassenmeisterei", "autobahnmeisterei", "bauhof",
    "recyclinghof", "kläranlage", "klaeranlage", "kraftwerk", "heizwerk",
    "umspannwerk", "windpark", "solarpark", "biogasanlage", "tanklager",
}

_INDUSTRIAL_ROLE_IMPORTANCE: dict[IndustrialRole, float] = {
    IndustrialRole.HEAVY_INDUSTRY: 78.0,
    IndustrialRole.CHEMICAL: 72.0,
    IndustrialRole.SHIPYARD: 72.0,
    IndustrialRole.METALWORKS: 68.0,
    IndustrialRole.MACHINERY: 62.0,
    IndustrialRole.AUTOMOTIVE: 62.0,
    IndustrialRole.ELECTRONICS: 60.0,
    IndustrialRole.EXTRACTION: 52.0,
    IndustrialRole.CONSTRUCTION_MATERIALS: 48.0,
    IndustrialRole.TIMBER_PAPER: 38.0,
    IndustrialRole.FOOD_PROCESSING: 33.0,
    IndustrialRole.GENERAL_MANUFACTURING: 28.0,
}


def build_industrial_sites(
    features: Iterable[TopographyFeature],
    *,
    theater_id: str,
    policy: InfrastructureCandidatePolicy | None = None,
    named_cluster_radius_m: float = 750.0,
    unnamed_minimum_area_m2: float = 2_500.0,
    industrial_area_minimum_m2: float = 5_000.0,
) -> TheaterInfrastructureSites:
    """Build conservative industrial plants without promoting generic estates."""

    if min(named_cluster_radius_m, unnamed_minimum_area_m2, industrial_area_minimum_m2) < 0:
        raise ValueError("industrial-site distances and areas must not be negative")
    selected_policy = policy or infrastructure_policy_for_theater(theater_id)
    candidates: list[_IndustrialCandidate] = []
    excluded = {
        "generic_industrial_area": 0,
        "weak_works": 0,
        "small_unnamed_site": 0,
        "other_infrastructure_category": 0,
        "outside_scenario_date": 0,
    }
    supported_categories = {"industrial_area", "works", *_INDUSTRIAL_CATEGORY_ROLES} - {"shipyard"}
    for feature in features:
        if feature.layer is not TopographyLayer.INFRASTRUCTURE or feature.category not in supported_categories:
            continue
        if not _feature_exists_in_scenario(feature, selected_policy.scenario_reference_year):
            excluded["outside_scenario_date"] += 1
            continue
        tags = _osm_tags(feature.properties.get("osm_tags"))
        if _industrial_name_is_non_site(feature.name):
            excluded["other_infrastructure_category"] += 1
            continue
        roles, role_sources = _industrial_roles(feature.category, tags, feature.name)
        if IndustrialRole.SHIPYARD in roles:
            excluded["other_infrastructure_category"] += 1
            continue
        products = _industrial_products(tags)
        operator = _optional_string(tags.get("operator"))
        area_m2 = _geometry_area_m2(feature.geometry)
        named = bool(feature.name or operator)
        if feature.category == "industrial_area":
            if "name" not in role_sources or area_m2 < industrial_area_minimum_m2:
                excluded["generic_industrial_area"] += 1
                continue
        elif feature.category == "works":
            has_evidence = bool(products or tags.get("industrial") or tags.get("craft") or "name" in role_sources)
            if not named or not has_evidence:
                excluded["weak_works"] += 1
                continue
        elif not named and area_m2 < unnamed_minimum_area_m2:
            excluded["small_unnamed_site"] += 1
            continue
        if not roles:
            roles = {IndustrialRole.GENERAL_MANUFACTURING}
            role_sources.add("explicit_industrial_feature")
        longitude, latitude = _representative_coordinate(feature.geometry)
        candidates.append(_IndustrialCandidate(
            feature=feature,
            latitude=latitude,
            longitude=longitude,
            roles=frozenset(roles),
            role_sources=frozenset(role_sources),
            products=products,
            operator=operator,
            area_m2=area_m2,
        ))

    clusters = _cluster_industrial_candidates(candidates, named_cluster_radius_m)
    sites = tuple(_industrial_site_from_cluster(cluster, selected_policy) for cluster in clusters)
    return TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=selected_policy.scenario_reference_year,
        sites=sites,
        metadata={
            "raw_industrial_candidate_count": len(candidates),
            "excluded_industrial_counts": excluded,
            "named_cluster_radius_m": named_cluster_radius_m,
            "unnamed_minimum_area_m2": unnamed_minimum_area_m2,
            "industrial_area_minimum_m2": industrial_area_minimum_m2,
        },
    )


@dataclass(slots=True, frozen=True)
class _MaritimeCandidate:
    feature: TopographyFeature
    latitude: float
    longitude: float
    roles: frozenset[MaritimeRole]
    cargo_types: frozenset[MaritimeCargo]
    anchor: bool
    operator: str | None
    length_m: float


_MARITIME_ANCHOR_CATEGORIES = {"harbour", "port", "ferry_terminal", "shipyard"}
_MARITIME_COMPONENT_CATEGORIES = {"pier", "quay", "dock", "berth", "harbour_basin"}
_MARITIME_ROLE_IMPORTANCE = {
    MaritimeRole.CONTAINER_TERMINAL: 78.0,
    MaritimeRole.BULK_TERMINAL: 72.0,
    MaritimeRole.CARGO_TERMINAL: 68.0,
    MaritimeRole.RORO_TERMINAL: 62.0,
    MaritimeRole.SHIPYARD: 60.0,
    MaritimeRole.COMMERCIAL_PORT: 55.0,
    MaritimeRole.FERRY_TERMINAL: 48.0,
    MaritimeRole.PASSENGER_TERMINAL: 42.0,
    MaritimeRole.FISHING_PORT: 30.0,
    MaritimeRole.HARBOUR: 20.0,
}
_MARITIME_CARGO_ALIASES = {
    "cargo": MaritimeCargo.GENERAL_CARGO,
    "general": MaritimeCargo.GENERAL_CARGO,
    "general_cargo": MaritimeCargo.GENERAL_CARGO,
    "container": MaritimeCargo.CONTAINERS,
    "containers": MaritimeCargo.CONTAINERS,
    "bulk": MaritimeCargo.DRY_BULK,
    "dry_bulk": MaritimeCargo.DRY_BULK,
    "liquid_bulk": MaritimeCargo.LIQUID_BULK,
    "oil": MaritimeCargo.PETROLEUM,
    "petroleum": MaritimeCargo.PETROLEUM,
    "gas": MaritimeCargo.GAS,
    "lng": MaritimeCargo.GAS,
    "coal": MaritimeCargo.COAL,
    "ore": MaritimeCargo.ORE,
    "grain": MaritimeCargo.GRAIN,
    "timber": MaritimeCargo.TIMBER,
    "wood": MaritimeCargo.TIMBER,
    "vehicle": MaritimeCargo.VEHICLES,
    "vehicles": MaritimeCargo.VEHICLES,
    "ro_ro": MaritimeCargo.VEHICLES,
    "roro": MaritimeCargo.VEHICLES,
    "passenger": MaritimeCargo.PASSENGERS,
    "passengers": MaritimeCargo.PASSENGERS,
    "ferry": MaritimeCargo.PASSENGERS,
    "fish": MaritimeCargo.FISH,
}


def build_maritime_sites(
    features: Iterable[TopographyFeature],
    *,
    theater_id: str,
    policy: InfrastructureCandidatePolicy | None = None,
    anchor_cluster_radius_m: float = 2_000.0,
    anonymous_anchor_cluster_radius_m: float = 500.0,
    component_radius_m: float = 2_500.0,
) -> TheaterInfrastructureSites:
    """Normalize civilian ports and their logistics components."""

    if min(anchor_cluster_radius_m, anonymous_anchor_cluster_radius_m, component_radius_m) < 0:
        raise ValueError("maritime-site cluster radii must not be negative")
    selected_policy = policy or infrastructure_policy_for_theater(theater_id)
    candidates: list[_MaritimeCandidate] = []
    excluded = {"recreational": 0, "military": 0, "unanchored_component": 0, "outside_scenario_date": 0}
    for feature in features:
        if feature.layer is not TopographyLayer.INFRASTRUCTURE:
            continue
        tags = _osm_tags(feature.properties.get("osm_tags"))
        if feature.category not in _MARITIME_ANCHOR_CATEGORIES | _MARITIME_COMPONENT_CATEGORIES:
            continue
        if not _feature_exists_in_scenario(feature, selected_policy.scenario_reference_year):
            excluded["outside_scenario_date"] += 1
            continue
        if _is_recreational_maritime_feature(feature, tags):
            excluded["recreational"] += 1
            continue
        if tags.get("military") or tags.get("landuse") == "military":
            excluded["military"] += 1
            continue
        anchor = feature.category in _MARITIME_ANCHOR_CATEGORIES or _is_maritime_anchor(tags)
        roles = _maritime_roles(feature.category, tags)
        if anchor and not roles:
            roles = {MaritimeRole.HARBOUR}
        longitude, latitude = _representative_coordinate(feature.geometry)
        candidates.append(_MaritimeCandidate(
            feature=feature,
            latitude=latitude,
            longitude=longitude,
            roles=frozenset(roles),
            cargo_types=_maritime_cargo_types(tags),
            anchor=anchor,
            operator=_optional_string(tags.get("operator")),
            length_m=_geometry_length_m(feature.geometry),
        ))

    anchors = sorted((candidate for candidate in candidates if candidate.anchor), key=_maritime_candidate_key)
    components = sorted((candidate for candidate in candidates if not candidate.anchor), key=_maritime_candidate_key)
    clusters: list[list[_MaritimeCandidate]] = []
    for candidate in anchors:
        identity = _maritime_identity(candidate)
        eligible = []
        for cluster in clusters:
            cluster_identity = next((_maritime_identity(item) for item in cluster if _maritime_identity(item)), "")
            distance = _candidate_distance_m(candidate, cluster[0])
            if identity and cluster_identity:
                matches = identity == cluster_identity and distance <= anchor_cluster_radius_m
            else:
                matches = distance <= anonymous_anchor_cluster_radius_m
            if matches:
                eligible.append((distance, cluster))
        matching = min(eligible, key=lambda item: item[0], default=(math.inf, None))[1]
        if matching is None:
            clusters.append([candidate])
        else:
            matching.append(candidate)
    for component in components:
        nearest = min(
            clusters,
            key=lambda cluster: _candidate_distance_m(component, cluster[0]),
            default=None,
        )
        if nearest is None or _candidate_distance_m(component, nearest[0]) > component_radius_m:
            excluded["unanchored_component"] += 1
            continue
        nearest.append(component)

    sites = tuple(_maritime_site_from_cluster(cluster, selected_policy) for cluster in clusters)
    return TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=selected_policy.scenario_reference_year,
        sites=sites,
        metadata={
            "raw_maritime_candidate_count": len(candidates),
            "excluded_maritime_counts": excluded,
            "maritime_cluster_radii_m": {
                "named_anchors": anchor_cluster_radius_m,
                "anonymous_anchors": anonymous_anchor_cluster_radius_m,
                "components": component_radius_m,
            },
        },
    )


def build_infrastructure_sites(
    features: Iterable[TopographyFeature],
    *,
    theater_id: str,
    policy: InfrastructureCandidatePolicy | None = None,
) -> TheaterInfrastructureSites:
    """Build the currently supported normalized infrastructure categories."""

    materialized = tuple(features)
    energy = build_energy_sites(materialized, theater_id=theater_id, policy=policy)
    fuel = build_fuel_storage_sites(materialized, theater_id=theater_id, policy=policy)
    military = build_military_sites(materialized, theater_id=theater_id, policy=policy)
    industrial = build_industrial_sites(materialized, theater_id=theater_id, policy=policy)
    maritime = build_maritime_sites(materialized, theater_id=theater_id, policy=policy)
    return TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=energy.scenario_reference_year,
        sites=(*energy.sites, *fuel.sites, *military.sites, *industrial.sites, *maritime.sites),
        metadata={
            "energy": energy.metadata,
            "fuel_storage": fuel.metadata,
            "military": military.metadata,
            "industrial": industrial.metadata,
            "maritime": maritime.metadata,
        },
    )


def _is_maritime_anchor(tags: Mapping[str, Any]) -> bool:
    seamark_type = str(tags.get("seamark:type") or "").strip().casefold()
    return (
        str(tags.get("harbour") or "").casefold() == "yes"
        or str(tags.get("landuse") or "").casefold() == "port"
        or str(tags.get("industrial") or "").casefold() in {"port", "shipyard"}
        or bool(str(tags.get("port") or "").strip())
        or str(tags.get("amenity") or "").casefold() == "ferry_terminal"
        or seamark_type == "harbour"
    )


def _is_recreational_maritime_feature(feature: TopographyFeature, tags: Mapping[str, Any]) -> bool:
    operational_values: set[str] = set()
    for key in ("port", "cargo", "industrial", "seamark:harbour:category", "seamark:berth:category"):
        if tags.get(key) is not None:
            operational_values.update(_split_tag_values(tags[key]))
    if (
        feature.category in {"ferry_terminal", "shipyard"}
        or str(tags.get("amenity") or "").casefold() == "ferry_terminal"
        or operational_values.intersection({
            "port", "shipyard", "cargo", "general_cargo", "freight", "container", "containers",
            "bulk", "dry_bulk", "liquid_bulk", "coal", "ore", "grain", "oil", "gas", "lng",
            "ro_ro", "roro", "vehicle", "vehicles", "passenger", "passengers", "ferry", "fishing",
        })
    ):
        return False
    recreational_values = {
        str(tags.get("leisure") or "").casefold(),
        str(tags.get("harbour") or "").casefold(),
        str(tags.get("sport") or "").casefold(),
        str(tags.get("club") or "").casefold(),
        str(tags.get("seamark:harbour:category") or "").casefold(),
    }
    if recreational_values.intersection({"marina", "sailing", "yachting", "yacht_club"}):
        return True
    normalized_name = (feature.name or "").casefold()
    return any(marker in normalized_name for marker in (
        "marina", "yachtclub", "yacht club", "yachthafen", "sportboothafen", "segelhafen",
    ))


def _maritime_roles(category: str, tags: Mapping[str, Any]) -> set[MaritimeRole]:
    values = set()
    for key in ("port", "cargo", "harbour", "seamark:harbour:category", "seamark:berth:category"):
        if tags.get(key) is not None:
            values.update(_split_tag_values(tags[key]))
    roles: set[MaritimeRole] = set()
    if category == "shipyard" or str(tags.get("industrial") or "").casefold() == "shipyard":
        roles.add(MaritimeRole.SHIPYARD)
    if category == "ferry_terminal" or str(tags.get("amenity") or "").casefold() == "ferry_terminal" or "ferry" in values:
        roles.add(MaritimeRole.FERRY_TERMINAL)
    if values.intersection({"container", "containers", "container_terminal"}):
        roles.add(MaritimeRole.CONTAINER_TERMINAL)
    if values.intersection({"bulk", "dry_bulk", "liquid_bulk", "coal", "ore", "grain", "oil", "gas", "lng"}):
        roles.add(MaritimeRole.BULK_TERMINAL)
    if values.intersection({"ro_ro", "roro", "vehicle", "vehicles"}):
        roles.add(MaritimeRole.RORO_TERMINAL)
    if values.intersection({"cargo", "general_cargo", "freight"}):
        roles.add(MaritimeRole.CARGO_TERMINAL)
    if values.intersection({"passenger", "passengers", "cruise"}):
        roles.add(MaritimeRole.PASSENGER_TERMINAL)
    if values.intersection({"fishing", "fishery"}):
        roles.add(MaritimeRole.FISHING_PORT)
    if (
        category == "port"
        or str(tags.get("landuse") or "").casefold() == "port"
        or str(tags.get("industrial") or "").casefold() == "port"
        or bool(str(tags.get("port") or "").strip())
    ):
        roles.add(MaritimeRole.COMMERCIAL_PORT)
    if not roles and (
        category == "harbour"
        or str(tags.get("harbour") or "").casefold() == "yes"
        or str(tags.get("seamark:type") or "").casefold() == "harbour"
    ):
        roles.add(MaritimeRole.HARBOUR)
    return roles


def _maritime_cargo_types(tags: Mapping[str, Any]) -> frozenset[MaritimeCargo]:
    values: set[str] = set()
    for key in ("cargo", "port", "product", "seamark:harbour:category", "seamark:berth:category"):
        if tags.get(key) is not None:
            values.update(_split_tag_values(tags[key]))
    return frozenset(_MARITIME_CARGO_ALIASES[value] for value in values if value in _MARITIME_CARGO_ALIASES)


def _maritime_site_from_cluster(
    cluster: list[_MaritimeCandidate],
    policy: InfrastructureCandidatePolicy,
) -> MaritimeSite:
    ordered = sorted(cluster, key=lambda item: (not item.anchor, _maritime_candidate_key(item)))
    primary = max(ordered, key=lambda item: (_geometry_area_m2(item.feature.geometry), item.anchor, bool(item.feature.name)))
    source_keys = tuple(sorted({item.feature.source_id or item.feature.object_id for item in cluster}))
    digest = hashlib.sha1("|".join(source_keys).encode("utf-8")).hexdigest()[:16]
    roles = tuple(sorted({role for item in cluster for role in item.roles}, key=lambda role: role.value))
    cargo_types = tuple(sorted({cargo for item in cluster for cargo in item.cargo_types}, key=lambda cargo: cargo.value))
    operators = tuple(sorted({item.operator for item in cluster if item.operator}))
    names = [item.feature.name for item in ordered if item.feature.name]
    geometry, longitude, latitude = _normalized_feature_footprint(item.feature for item in cluster)
    footprint_area_m2 = _geometry_area_m2(geometry) or None
    quay_components = [item for item in cluster if item.feature.category in {"pier", "quay"}]
    quay_length_m = sum(item.length_m for item in quay_components) or None
    berth_count = sum(item.feature.category == "berth" for item in cluster)
    importance_score = _maritime_importance_score(
        roles,
        cargo_types,
        footprint_area_m2=footprint_area_m2,
        quay_length_m=quay_length_m,
        berth_count=berth_count,
        component_count=len(cluster),
    )
    return MaritimeSite(
        site_id=f"MARITIME_SITE:{digest}",
        kind=InfrastructureSiteKind.MARITIME,
        geometry=geometry,
        latitude=latitude,
        longitude=longitude,
        source=primary.feature.source,
        confidence=min(0.95, max(item.feature.confidence for item in cluster) + (0.1 if names or operators else 0.0)),
        name=names[0] if names else (f"{operators[0]} port" if operators else None),
        source_ids=source_keys,
        scenario_reference_year=policy.scenario_reference_year or primary.feature.scenario_reference_year,
        verification_state=(InfrastructureVerificationState.DCS_VISUAL_ONLY if any(item.feature.dcs_verified for item in cluster) else InfrastructureVerificationState.UNVERIFIED),
        component_ids=tuple(sorted({item.feature.object_id for item in cluster})),
        roles=roles,
        cargo_types=cargo_types,
        footprint_area_m2=footprint_area_m2,
        quay_length_m=quay_length_m,
        berth_count=berth_count,
        importance_score=importance_score,
        importance_tier=_infrastructure_importance_tier(importance_score),
        properties={
            "member_count": len(cluster),
            "operators": list(operators),
            "strategic_candidate": importance_score >= 50,
            "scale": _industrial_scale(footprint_area_m2),
            "geometry_method": "hole_free_union_of_source_components",
            "evidence_categories": sorted({item.feature.category for item in cluster}),
        },
    )


def _maritime_importance_score(
    roles: Iterable[MaritimeRole],
    cargo_types: Iterable[MaritimeCargo],
    *,
    footprint_area_m2: float | None,
    quay_length_m: float | None,
    berth_count: int,
    component_count: int,
) -> float:
    role_score = max((_MARITIME_ROLE_IMPORTANCE[role] for role in roles), default=0.0)
    area_bonus = 0.0 if not footprint_area_m2 else min(10.0, max(0.0, math.log10(max(1.0, footprint_area_m2) / 10_000.0) * 4.0))
    quay_bonus = 0.0 if not quay_length_m else min(10.0, quay_length_m / 500.0 * 2.0)
    evidence_bonus = min(8.0, berth_count * 1.5 + max(0, component_count - 1) * 0.5)
    cargo_bonus = min(6.0, len(tuple(cargo_types)) * 2.0)
    return round(min(100.0, role_score + area_bonus + quay_bonus + evidence_bonus + cargo_bonus), 3)


def _maritime_candidate_key(candidate: _MaritimeCandidate) -> tuple[str, str]:
    return candidate.feature.source_id or "", candidate.feature.object_id


def _maritime_identity(candidate: _MaritimeCandidate) -> str:
    return _normalized_site_name(candidate.feature.name) or _normalized_site_name(candidate.operator)


def _cluster_fuel_candidates(
    candidates: Iterable[_FuelCandidate],
    *,
    anchor_cluster_radius_m: float,
    component_radius_m: float,
    standalone_cluster_radius_m: float,
) -> list[list[_FuelCandidate]]:
    anchors = sorted((candidate for candidate in candidates if candidate.anchor), key=_fuel_candidate_key)
    components = sorted((candidate for candidate in candidates if not candidate.anchor), key=_fuel_candidate_key)
    clusters: list[list[_FuelCandidate]] = []
    for candidate in anchors:
        cluster = _nearest_cluster(candidate, clusters, anchor_cluster_radius_m, anchors_only=True)
        if cluster is None:
            clusters.append([candidate])
        else:
            cluster.append(candidate)
    unassigned: list[_FuelCandidate] = []
    for component in components:
        cluster = _nearest_cluster(component, clusters, component_radius_m, anchors_only=True)
        if cluster is None:
            unassigned.append(component)
        else:
            cluster.append(component)
    while unassigned:
        seed = unassigned.pop(0)
        cluster = [seed]
        remaining: list[_FuelCandidate] = []
        for candidate in unassigned:
            if _candidate_distance_m(seed, candidate) <= standalone_cluster_radius_m:
                cluster.append(candidate)
            else:
                remaining.append(candidate)
        clusters.append(cluster)
        unassigned = remaining
    return clusters


def _nearest_cluster(
    candidate: _FuelCandidate,
    clusters: list[list[_FuelCandidate]],
    radius_m: float,
    *,
    anchors_only: bool,
) -> list[_FuelCandidate] | None:
    nearest: list[_FuelCandidate] | None = None
    nearest_distance = math.inf
    for cluster in clusters:
        reference = next((item for item in cluster if item.anchor), cluster[0])
        if anchors_only and not reference.anchor:
            continue
        distance = _candidate_distance_m(candidate, reference)
        if distance <= radius_m and distance < nearest_distance:
            nearest = cluster
            nearest_distance = distance
    return nearest


def _fuel_site_from_cluster(
    cluster: list[_FuelCandidate],
    policy: InfrastructureCandidatePolicy,
) -> FuelStorageSite:
    ordered = sorted(cluster, key=lambda item: (not item.anchor, _fuel_candidate_key(item)))
    primary = ordered[0]
    source_keys = tuple(sorted({item.feature.source_id or item.feature.object_id for item in cluster}))
    digest = hashlib.sha1("|".join(source_keys).encode("utf-8")).hexdigest()[:16]
    operators = tuple(sorted({item.operator for item in cluster if item.operator}))
    names = [item.feature.name for item in ordered if item.feature.name]
    name = names[0] if names else (f"{operators[0]} fuel storage" if operators else None)
    capacities = [item.capacity_m3 for item in cluster if item.capacity_m3 is not None]
    return FuelStorageSite(
        site_id=f"FUEL_STORAGE_SITE:{digest}",
        kind=InfrastructureSiteKind.FUEL_STORAGE,
        geometry=primary.feature.geometry,
        latitude=sum(item.latitude for item in cluster) / len(cluster),
        longitude=sum(item.longitude for item in cluster) / len(cluster),
        source=primary.feature.source,
        confidence=max(item.feature.confidence for item in cluster),
        name=name,
        source_ids=source_keys,
        scenario_reference_year=policy.scenario_reference_year or primary.feature.scenario_reference_year,
        verification_state=(
            InfrastructureVerificationState.DCS_VISUAL_ONLY
            if any(item.feature.dcs_verified for item in cluster)
            else InfrastructureVerificationState.UNVERIFIED
        ),
        component_ids=tuple(sorted({item.feature.object_id for item in cluster})),
        storage_roles=tuple(sorted({role for item in cluster for role in item.roles}, key=lambda role: role.value)),
        commodities=tuple(sorted({value for item in cluster for value in item.commodities}, key=lambda value: value.value)),
        capacity_m3=sum(capacities) if capacities else None,
        properties={
            "member_count": len(cluster),
            "operators": list(operators),
            "evidence_categories": sorted({item.feature.category for item in cluster}),
        },
    )


def _fuel_candidate_key(candidate: _FuelCandidate) -> tuple[str, str]:
    return candidate.feature.source_id or "", candidate.feature.object_id


def _candidate_distance_m(
    first: _EnergyCandidate | _FuelCandidate | _MilitaryCandidate | _IndustrialCandidate | _MaritimeCandidate,
    second: _EnergyCandidate | _FuelCandidate | _MilitaryCandidate | _IndustrialCandidate | _MaritimeCandidate,
) -> float:
    latitude = math.radians((first.latitude + second.latitude) / 2)
    dx = math.radians(first.longitude - second.longitude) * math.cos(latitude)
    dy = math.radians(first.latitude - second.latitude)
    return math.hypot(dx, dy) * 6_371_008.8


def _fuel_commodities(tags: Mapping[str, Any], category: str) -> frozenset[StoredCommodity]:
    values: set[str] = set()
    for key in ("content", "substance", "storage", "product", "depot"):
        raw = tags.get(key)
        if raw is not None:
            values.update(_split_tag_values(raw))
    industrial = str(tags.get("industrial") or category).casefold()
    if industrial in _FUEL_ANCHOR_ROLES:
        values.add(industrial)
    return frozenset(_FUEL_ALIASES[value] for value in values if value in _FUEL_ALIASES)


def _fuel_anchor_role(
    category: str,
    tags: Mapping[str, Any],
    name: str | None,
) -> FuelStorageRole | None:
    role = _FUEL_ANCHOR_ROLES.get(category)
    if role is None:
        return None
    if category in {"oil", "gas", "natural_gas"} and not _has_storage_evidence(tags, name):
        return None
    return role


def _has_storage_evidence(tags: Mapping[str, Any], name: str | None) -> bool:
    evidence = " ".join(
        str(value).casefold()
        for value in (tags.get("storage"), tags.get("industrial"), tags.get("depot"), name)
        if value is not None
    )
    return any(token in evidence for token in ("storage", "terminal", "tank", "depot", "cavern", "speicher", "lager"))


def _admit_fuel_cluster(cluster: list[_FuelCandidate]) -> bool:
    if any(candidate.anchor for candidate in cluster) or len(cluster) >= 2:
        return True
    candidate = cluster[0]
    return candidate.capacity_m3 is not None and candidate.capacity_m3 >= 500


def _category_commodities(category: str) -> frozenset[StoredCommodity]:
    if category in {"oil", "oil_storage", "distillates_storage", "refinery"}:
        return frozenset({StoredCommodity.PETROLEUM})
    if category in {"gas", "natural_gas", "gas_storage", "gas_cavern"}:
        return frozenset({StoredCommodity.NATURAL_GAS})
    return frozenset()


def _split_tag_values(value: Any) -> set[str]:
    text = str(value).casefold().replace(",", ";")
    return {item.strip().replace(" ", "_") for item in text.split(";") if item.strip()}


def _parse_capacity_m3(tags: Mapping[str, Any]) -> float | None:
    raw = tags.get("capacity") or tags.get("volume")
    if raw is None:
        return None
    text = str(raw).strip().casefold().replace(" ", "").replace(",", ".")
    units = (("m³", 1.0), ("m3", 1.0), ("litres", 0.001), ("liters", 0.001), ("litre", 0.001), ("liter", 0.001), ("l", 0.001))
    for suffix, multiplier in units:
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            try:
                return float(text) * multiplier
            except ValueError:
                return None
    try:
        return float(text)
    except ValueError:
        return None


def _cluster_military_candidates(
    candidates: Iterable[_MilitaryCandidate],
    radius_m: float,
) -> list[list[_MilitaryCandidate]]:
    clusters: list[list[_MilitaryCandidate]] = []
    for candidate in sorted(candidates, key=_military_candidate_key):
        name_key = _normalized_site_name(candidate.feature.name)
        matching = next(
            (
                cluster for cluster in clusters
                if name_key
                and _normalized_site_name(cluster[0].feature.name) == name_key
                and _candidate_distance_m(candidate, cluster[0]) <= radius_m
            ),
            None,
        )
        if matching is None:
            clusters.append([candidate])
        else:
            matching.append(candidate)
    return clusters


def _military_site_from_cluster(
    cluster: list[_MilitaryCandidate],
    policy: InfrastructureCandidatePolicy,
) -> MilitarySite:
    ordered = sorted(cluster, key=_military_candidate_key)
    primary = next((candidate for candidate in ordered if candidate.feature.name), ordered[0])
    source_keys = tuple(sorted({item.feature.source_id or item.feature.object_id for item in cluster}))
    digest = hashlib.sha1("|".join(source_keys).encode("utf-8")).hexdigest()[:16]
    roles = tuple(sorted({role for item in cluster for role in item.roles}, key=lambda role: role.value))
    names = [item.feature.name for item in ordered if item.feature.name]
    operators = tuple(sorted({item.operator for item in cluster if item.operator}))
    role_sources = tuple(sorted({source for item in cluster for source in item.role_sources}))
    explicit_role = "military_tag" in role_sources
    confidence = min(
        0.95,
        max(item.feature.confidence for item in cluster)
        + (0.15 if explicit_role else 0.05)
        + (0.1 if names else 0.0),
    )
    geometry, longitude, latitude = _normalized_feature_footprint(item.feature for item in cluster)
    footprint_area_m2 = _geometry_area_m2(geometry) or None
    targetable_candidate = bool(set(roles).intersection(_TARGETABLE_MILITARY_ROLES))
    importance_score = _military_importance_score(
        roles,
        footprint_area_m2=footprint_area_m2,
        explicit_role=explicit_role,
        targetable=targetable_candidate,
    )
    return MilitarySite(
        site_id=f"MILITARY_SITE:{digest}",
        kind=InfrastructureSiteKind.MILITARY,
        geometry=geometry,
        latitude=latitude,
        longitude=longitude,
        source=primary.feature.source,
        confidence=confidence,
        name=names[0] if names else (f"{operators[0]} military site" if operators else None),
        source_ids=source_keys,
        scenario_reference_year=policy.scenario_reference_year or primary.feature.scenario_reference_year,
        verification_state=(
            InfrastructureVerificationState.DCS_VISUAL_ONLY
            if any(item.feature.dcs_verified for item in cluster)
            else InfrastructureVerificationState.UNVERIFIED
        ),
        component_ids=tuple(sorted({item.feature.object_id for item in cluster})),
        roles=roles,
        footprint_area_m2=footprint_area_m2,
        importance_score=importance_score,
        importance_tier=_infrastructure_importance_tier(importance_score),
        properties={
            "member_count": len(cluster),
            "operators": list(operators),
            "role_sources": list(role_sources),
            "targetable_candidate": targetable_candidate,
            "scale": _industrial_scale(footprint_area_m2),
            "geometry_method": "hole_free_union_of_source_components",
            "historical_fit": (
                "date_supported"
                if any(item.feature.valid_from is not None or item.feature.valid_to is not None for item in cluster)
                else "unverified"
            ),
            "evidence_military_tags": sorted({
                str(_osm_tags(item.feature.properties.get("osm_tags")).get("military") or "unspecified")
                for item in cluster
            }),
        },
    )


def _military_candidate_key(candidate: _MilitaryCandidate) -> tuple[str, str]:
    return candidate.feature.source_id or "", candidate.feature.object_id


def _normalized_feature_footprint(
    features: Iterable[TopographyFeature],
) -> tuple[dict[str, Any], float, float]:
    try:
        from shapely import make_valid
        from shapely.geometry import Polygon, mapping, shape
        from shapely.ops import unary_union
    except ImportError as exc:
        raise RuntimeError('infrastructure-site normalization requires: python -m pip install -e ".[topography]"') from exc

    materialized = tuple(features)
    if not materialized:
        raise ValueError("infrastructure footprint requires at least one source feature")
    polygons = []
    for feature in materialized:
        geometry = make_valid(shape(feature.geometry))
        for polygon in _shapely_polygon_components(geometry):
            polygons.append(Polygon(polygon.exterior))
    if not polygons:
        primary = materialized[0]
        longitude, latitude = _representative_coordinate(primary.geometry)
        return primary.geometry, longitude, latitude
    geometry = make_valid(unary_union(polygons))
    polygon_components = _shapely_polygon_components(geometry)
    if not polygon_components:
        primary = materialized[0]
        longitude, latitude = _representative_coordinate(primary.geometry)
        return primary.geometry, longitude, latitude
    geometry = make_valid(unary_union(polygon_components))
    anchor = geometry.representative_point()
    return mapping(geometry), float(anchor.x), float(anchor.y)


def _shapely_polygon_components(geometry: Any) -> list[Any]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return [
            polygon
            for part in geometry.geoms
            for polygon in _shapely_polygon_components(part)
        ]
    return []


def _military_importance_score(
    roles: Iterable[MilitaryRole],
    *,
    footprint_area_m2: float | None,
    explicit_role: bool,
    targetable: bool,
) -> float:
    materialized = tuple(roles)
    role_score = max((_MILITARY_ROLE_IMPORTANCE[role] for role in materialized), default=0.0)
    area_bonus = 0.0
    if footprint_area_m2 and footprint_area_m2 > 10_000:
        area_bonus = min(12.0, math.log10(footprint_area_m2 / 10_000.0) * 4.0)
    evidence_bonus = 4.0 if explicit_role else 0.0
    multi_role_bonus = min(6.0, max(0, len(materialized) - 1) * 3.0)
    score = role_score + area_bonus + evidence_bonus + multi_role_bonus
    if not targetable:
        score = min(score, 39.0)
    return round(min(100.0, max(0.0, score)), 3)


def _infrastructure_importance_tier(score: float) -> InfrastructureImportanceTier:
    if score >= 80:
        return InfrastructureImportanceTier.CRITICAL
    if score >= 60:
        return InfrastructureImportanceTier.HIGH
    if score >= 40:
        return InfrastructureImportanceTier.MEDIUM
    return InfrastructureImportanceTier.LOCAL


def _cluster_energy_candidates(
    candidates: Iterable[_EnergyCandidate],
    radius_m: float,
) -> list[list[_EnergyCandidate]]:
    """Group same-site OSM components without transitive distance chaining."""

    clusters: list[list[_EnergyCandidate]] = []
    for candidate in sorted(candidates, key=_energy_candidate_key):
        identity = _energy_identity(candidate)
        matching = next(
            (
                cluster for cluster in clusters
                if identity
                and _energy_identity(cluster[0]) == identity
                and not candidate.roles.isdisjoint(cluster[0].roles)
                and _candidate_distance_m(candidate, cluster[0]) <= radius_m
            ),
            None,
        )
        if matching is None:
            clusters.append([candidate])
        else:
            matching.append(candidate)
    return clusters


def _energy_site_from_cluster(
    cluster: list[_EnergyCandidate],
    policy: InfrastructureCandidatePolicy,
) -> EnergySite:
    ordered = sorted(cluster, key=_energy_candidate_key)
    primary = max(ordered, key=lambda item: (item.area_m2, bool(item.feature.name)))
    source_keys = tuple(sorted({item.feature.source_id or item.feature.object_id for item in cluster}))
    digest = hashlib.sha1("|".join(source_keys).encode("utf-8")).hexdigest()[:16]
    roles = tuple(sorted({role for item in cluster for role in item.roles}, key=lambda role: role.value))
    sources = tuple(sorted({source for item in cluster for source in item.sources}, key=lambda source: source.value))
    if not sources:
        sources = (EnergySource.UNKNOWN,)
    operators = tuple(sorted({item.operator for item in cluster if item.operator}))
    names = [item.feature.name for item in ordered if item.feature.name]
    outputs = [item.output_mw for item in cluster if item.output_mw is not None]
    voltages = [item.voltage_kv for item in cluster if item.voltage_kv is not None]
    geometry, longitude, latitude = _normalized_feature_footprint(item.feature for item in cluster)
    footprint_area_m2 = _geometry_area_m2(geometry) or None
    output_mw = max(outputs) if outputs else None
    voltage_kv = max(voltages) if voltages else None
    importance_score = _energy_importance_score(
        roles,
        sources,
        output_mw=output_mw,
        voltage_kv=voltage_kv,
        footprint_area_m2=footprint_area_m2,
        has_operator=bool(operators),
    )
    return EnergySite(
        site_id=f"ENERGY_SITE:{digest}",
        kind=InfrastructureSiteKind.ENERGY,
        geometry=geometry,
        latitude=latitude,
        longitude=longitude,
        source=primary.feature.source,
        confidence=min(
            0.95,
            max(item.feature.confidence for item in cluster)
            + (0.1 if names or operators else 0.0)
            + (0.1 if output_mw is not None or voltage_kv is not None else 0.0),
        ),
        name=names[0] if names else (f"{operators[0]} energy site" if operators else None),
        source_ids=source_keys,
        scenario_reference_year=policy.scenario_reference_year or primary.feature.scenario_reference_year,
        verification_state=(
            InfrastructureVerificationState.DCS_VISUAL_ONLY
            if any(item.feature.dcs_verified for item in cluster)
            else InfrastructureVerificationState.UNVERIFIED
        ),
        component_ids=tuple(sorted({item.feature.object_id for item in cluster})),
        roles=roles,
        energy_sources=sources,
        output_mw=output_mw,
        voltage_kv=voltage_kv,
        footprint_area_m2=footprint_area_m2,
        importance_score=importance_score,
        importance_tier=_infrastructure_importance_tier(importance_score),
        properties={
            "member_count": len(cluster),
            "operators": list(operators),
            "strategic_candidate": importance_score >= 50,
            "scale": _energy_scale(output_mw, voltage_kv, footprint_area_m2),
            "geometry_method": "hole_free_union_of_source_components",
            "evidence_categories": sorted({item.feature.category for item in cluster}),
        },
    )


_ENERGY_SOURCE_IMPORTANCE: dict[EnergySource, float] = {
    EnergySource.NUCLEAR: 65.0,
    EnergySource.COAL: 42.0,
    EnergySource.OIL: 40.0,
    EnergySource.GAS: 40.0,
    EnergySource.HYDRO: 35.0,
    EnergySource.WASTE: 28.0,
    EnergySource.BIOMASS: 24.0,
    EnergySource.WIND: 24.0,
    EnergySource.SOLAR: 20.0,
    EnergySource.BIOGAS: 22.0,
    EnergySource.BATTERY: 30.0,
    EnergySource.OTHER: 24.0,
    EnergySource.UNKNOWN: 20.0,
}


def _energy_importance_score(
    roles: Iterable[EnergyRole],
    sources: Iterable[EnergySource],
    *,
    output_mw: float | None,
    voltage_kv: float | None,
    footprint_area_m2: float | None,
    has_operator: bool,
) -> float:
    role_set = frozenset(roles)
    source_score = max((_ENERGY_SOURCE_IMPORTANCE[source] for source in sources), default=20.0)
    role_score = 0.0
    if EnergyRole.CONVERTER_STATION in role_set:
        role_score = 65.0
    elif EnergyRole.GRID_SUBSTATION in role_set:
        role_score = 44.0
    if EnergyRole.GENERATION not in role_set:
        source_score = role_score
    output_bonus = 0.0 if output_mw is None else min(30.0, math.log10(max(1.0, output_mw)) * 10.0)
    voltage_bonus = 0.0 if voltage_kv is None else min(24.0, max(0.0, voltage_kv - 100.0) / 25.0)
    area_bonus = 0.0
    if footprint_area_m2 and footprint_area_m2 > 10_000:
        area_bonus = min(10.0, math.log10(footprint_area_m2 / 10_000.0) * 4.0)
    evidence_bonus = 2.0 if has_operator else 0.0
    return round(min(100.0, max(0.0, source_score + output_bonus + voltage_bonus + area_bonus + evidence_bonus)), 3)


def _energy_candidate_key(candidate: _EnergyCandidate) -> tuple[str, str]:
    return candidate.feature.source_id or "", candidate.feature.object_id


def _energy_identity(candidate: _EnergyCandidate) -> str:
    return _normalized_site_name(candidate.feature.name) or _normalized_site_name(candidate.operator)


def _energy_scale(
    output_mw: float | None,
    voltage_kv: float | None,
    footprint_area_m2: float | None,
) -> str:
    if (output_mw or 0) >= 500 or (voltage_kv or 0) >= 380 or (footprint_area_m2 or 0) >= 1_000_000:
        return "very_large"
    if (output_mw or 0) >= 100 or (voltage_kv or 0) >= 220 or (footprint_area_m2 or 0) >= 200_000:
        return "large"
    if (output_mw or 0) >= 10 or (voltage_kv or 0) >= 110 or (footprint_area_m2 or 0) >= 20_000:
        return "medium"
    return "small"


def _cluster_industrial_candidates(
    candidates: Iterable[_IndustrialCandidate],
    radius_m: float,
) -> list[list[_IndustrialCandidate]]:
    clusters: list[list[_IndustrialCandidate]] = []
    for candidate in sorted(candidates, key=_industrial_candidate_key):
        identity = _industrial_identity(candidate)
        matching = next(
            (
                cluster for cluster in clusters
                if identity
                and _industrial_identity(cluster[0]) == identity
                and _candidate_distance_m(candidate, cluster[0]) <= radius_m
            ),
            None,
        )
        if matching is None:
            clusters.append([candidate])
        else:
            matching.append(candidate)
    return clusters


def _industrial_site_from_cluster(
    cluster: list[_IndustrialCandidate],
    policy: InfrastructureCandidatePolicy,
) -> IndustrialSite:
    ordered = sorted(cluster, key=_industrial_candidate_key)
    primary = max(ordered, key=lambda item: (item.area_m2, bool(item.feature.name)))
    source_keys = tuple(sorted({item.feature.source_id or item.feature.object_id for item in cluster}))
    digest = hashlib.sha1("|".join(source_keys).encode("utf-8")).hexdigest()[:16]
    roles = tuple(sorted({role for item in cluster for role in item.roles}, key=lambda role: role.value))
    products = tuple(sorted({product for item in cluster for product in item.products}))
    operators = tuple(sorted({item.operator for item in cluster if item.operator}))
    names = [item.feature.name for item in ordered if item.feature.name]
    role_sources = tuple(sorted({source for item in cluster for source in item.role_sources}))
    geometry, longitude, latitude = _normalized_feature_footprint(item.feature for item in cluster)
    footprint_area_m2 = _geometry_area_m2(geometry) or None
    confidence = min(
        0.95,
        max(item.feature.confidence for item in cluster)
        + (0.1 if any(source in role_sources for source in ("industrial_tag", "category", "product")) else 0.0)
        + (0.1 if names or operators else 0.0),
    )
    importance_score = _industrial_importance_score(
        roles,
        footprint_area_m2=footprint_area_m2,
        has_products=bool(products),
        has_operator=bool(operators),
        explicit_role=any(source in role_sources for source in ("industrial_tag", "category", "product")),
    )
    strategic_candidate = importance_score >= 50
    return IndustrialSite(
        site_id=f"INDUSTRIAL_SITE:{digest}",
        kind=InfrastructureSiteKind.INDUSTRIAL,
        geometry=geometry,
        latitude=latitude,
        longitude=longitude,
        source=primary.feature.source,
        confidence=confidence,
        name=names[0] if names else (f"{operators[0]} industrial site" if operators else None),
        source_ids=source_keys,
        scenario_reference_year=policy.scenario_reference_year or primary.feature.scenario_reference_year,
        verification_state=(
            InfrastructureVerificationState.DCS_VISUAL_ONLY
            if any(item.feature.dcs_verified for item in cluster)
            else InfrastructureVerificationState.UNVERIFIED
        ),
        component_ids=tuple(sorted({item.feature.object_id for item in cluster})),
        roles=roles,
        products=products,
        footprint_area_m2=footprint_area_m2,
        importance_score=importance_score,
        importance_tier=_infrastructure_importance_tier(importance_score),
        properties={
            "member_count": len(cluster),
            "operators": list(operators),
            "role_sources": list(role_sources),
            "strategic_candidate": strategic_candidate,
            "scale": _industrial_scale(footprint_area_m2),
            "geometry_method": "hole_free_union_of_source_components",
            "evidence_categories": sorted({item.feature.category for item in cluster}),
        },
    )


def _industrial_importance_score(
    roles: Iterable[IndustrialRole],
    *,
    footprint_area_m2: float | None,
    has_products: bool,
    has_operator: bool,
    explicit_role: bool,
) -> float:
    materialized = tuple(roles)
    role_score = max((_INDUSTRIAL_ROLE_IMPORTANCE[role] for role in materialized), default=0.0)
    area_bonus = 0.0
    if footprint_area_m2 and footprint_area_m2 > 10_000:
        area_bonus = min(15.0, math.log10(footprint_area_m2 / 10_000.0) * 5.0)
    evidence_bonus = (3.0 if explicit_role else 0.0) + (3.0 if has_products else 0.0) + (2.0 if has_operator else 0.0)
    multi_role_bonus = min(4.0, max(0, len(materialized) - 1) * 2.0)
    return round(min(100.0, max(0.0, role_score + area_bonus + evidence_bonus + multi_role_bonus)), 3)


def _industrial_candidate_key(candidate: _IndustrialCandidate) -> tuple[str, str]:
    return candidate.feature.source_id or "", candidate.feature.object_id


def _industrial_identity(candidate: _IndustrialCandidate) -> str:
    return _normalized_site_name(candidate.feature.name) or _normalized_site_name(candidate.operator)


def _industrial_roles(
    category: str,
    tags: Mapping[str, Any],
    name: str | None,
) -> tuple[set[IndustrialRole], set[str]]:
    roles: set[IndustrialRole] = set()
    sources: set[str] = set()
    category_role = _INDUSTRIAL_CATEGORY_ROLES.get(category)
    if category_role is not None:
        roles.add(category_role)
        sources.add("category")
    industrial_value = str(tags.get("industrial") or "").strip().casefold()
    industrial_role = _industrial_role_from_value(industrial_value)
    if industrial_role is not None:
        roles.add(industrial_role)
        sources.add("industrial_tag")
    for product in _industrial_products(tags):
        role = _industrial_role_from_value(product)
        if role is not None:
            roles.add(role)
            sources.add("product")
    inferred = _industrial_role_from_name(name)
    if inferred is not None:
        roles.add(inferred)
        sources.add("name")
    return roles, sources


def _industrial_role_from_value(value: str) -> IndustrialRole | None:
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    groups: tuple[tuple[IndustrialRole, tuple[str, ...]], ...] = (
        (IndustrialRole.SHIPYARD, ("shipyard", "boatbuilding", "boatbuilder")),
        (IndustrialRole.HEAVY_INDUSTRY, ("heavy_industry",)),
        (IndustrialRole.METALWORKS, ("steel", "steelmaking", "metal", "metal_processing", "foundry", "aluminium")),
        (IndustrialRole.CHEMICAL, ("chemical", "chemicals", "fertilizer", "pharmaceutical")),
        (IndustrialRole.AUTOMOTIVE, ("automotive", "automotive_parts", "car_parts", "vehicles", "vehicle")),
        (IndustrialRole.MACHINERY, ("machinery", "machine_shop", "tools", "agricultural_engines")),
        (IndustrialRole.ELECTRONICS, ("electronics", "electrical", "communication")),
        (IndustrialRole.CONSTRUCTION_MATERIALS, ("cement", "concrete", "asphalt", "brick", "bricks", "glass", "precast_concrete")),
        (IndustrialRole.FOOD_PROCESSING, ("food", "food_industry", "brewery", "beer", "dairy", "meat", "slaughterhouse", "bakery", "sugar_refinery", "cheese", "milk", "seafood", "flour", "beverages", "juice")),
        (IndustrialRole.TIMBER_PAPER, ("sawmill", "timber", "wood", "paper", "cardboard", "pulp", "furniture")),
        (IndustrialRole.EXTRACTION, ("mine", "quarry", "mining", "gravel", "sand", "salt")),
        (IndustrialRole.GENERAL_MANUFACTURING, ("factory", "manufacturing", "works", "industrial")),
    )
    parts = set(normalized.split("_"))
    return next(
        (role for role, values in groups if any(token == normalized or token in parts for token in values)),
        None,
    )


def _industrial_role_from_name(name: str | None) -> IndustrialRole | None:
    value = _normalized_site_name(name)
    if not value:
        return None
    patterns: tuple[tuple[IndustrialRole, tuple[str, ...]], ...] = (
        (IndustrialRole.SHIPYARD, ("werft", "shipyard", "dockyard", "chantier naval")),
        (IndustrialRole.METALWORKS, ("stahl", "metall", "hüttenwerk", "huettenwerk", "gießerei", "giesserei", "foundry", "smelter")),
        (IndustrialRole.CHEMICAL, ("chemie", "chemical plant", "pharma", "düngemittel", "duengemittel")),
        (IndustrialRole.AUTOMOTIVE, ("fahrzeugwerk", "automobil", "automotive", "car factory", "motorenwerk")),
        (IndustrialRole.MACHINERY, ("maschinenbau", "maschinenfabrik", "machine works")),
        (IndustrialRole.ELECTRONICS, ("elektronikwerk", "electronic factory")),
        (IndustrialRole.CONSTRUCTION_MATERIALS, ("zement", "beton", "asphalt", "ziegel", "glaswerk", "cement works", "brickworks")),
        (IndustrialRole.FOOD_PROCESSING, ("brauerei", "brewery", "molkerei", "schlachthof", "zuckerfabrik", "mühle", "muehle")),
        (IndustrialRole.TIMBER_PAPER, ("sägewerk", "saegewerk", "papierfabrik", "zellstoffwerk", "paper mill")),
        (IndustrialRole.EXTRACTION, ("bergwerk", "tagebau", "kieswerk", "steinbruch", "mine", "quarry")),
        (IndustrialRole.GENERAL_MANUFACTURING, ("fabrik", "factory", " werk", "werke", "works", "manufacturing")),
    )
    return next((role for role, tokens in patterns if any(token in value for token in tokens)), None)


def _industrial_products(tags: Mapping[str, Any]) -> frozenset[str]:
    products: set[str] = set()
    for key in ("product", "produce"):
        if tags.get(key) is not None:
            products.update(_split_tag_values(tags[key]))
    return frozenset(products)


def _industrial_name_is_non_site(name: str | None) -> bool:
    value = _normalized_site_name(name)
    return bool(value and any(token in value for token in _NON_INDUSTRIAL_SITE_NAME_TOKENS))


def _industrial_scale(area_m2: float | None) -> str:
    if area_m2 is None or area_m2 < 10_000:
        return "small"
    if area_m2 < 100_000:
        return "medium"
    if area_m2 < 1_000_000:
        return "large"
    return "very_large"


def _normalized_site_name(name: str | None) -> str:
    return " ".join((name or "").casefold().replace("-", " ").split())


def _military_role_from_name(name: str | None) -> MilitaryRole | None:
    value = _normalized_site_name(name)
    if not value:
        return None
    patterns: tuple[tuple[MilitaryRole, tuple[str, ...]], ...] = (
        (MilitaryRole.AMMUNITION_STORAGE, ("munition", "ammunition", "munitionsdepot")),
        (MilitaryRole.FUEL_STORAGE, ("tanklager", "fuel depot", "carburant")),
        (MilitaryRole.NAVAL_BASE, ("naval base", "marinebasis", "marinestützpunkt", "marinearsenal", "flådestation")),
        (MilitaryRole.BARRACKS, ("kaserne", "caserne", "barracks", "kazerne", "koszary")),
        (MilitaryRole.RADAR_SITE, ("radar",)),
        (MilitaryRole.COMMUNICATIONS_SITE, ("funk", "fernmelde", "radio site", "communications")),
        (MilitaryRole.MISSILE_SITE, ("missile", "raketen", "missil")),
        (MilitaryRole.DEPOT, ("depot", "dépôt", "materiallager", "materialelager", "militärlager")),
        (MilitaryRole.FIRING_RANGE, ("schieß", "schiess", "firing range", "shooting range", "champ de tir")),
        (MilitaryRole.TRAINING_AREA, ("übungsplatz", "training area", "truppenübungsplatz", "øvelsesplads")),
        (MilitaryRole.BUNKER_COMPLEX, ("bunker", "ouvrage", "fort ", "fort de", "feste ")),
        (MilitaryRole.BASE, ("military base", "militärbasis", "stützpunkt", "military site")),
    )
    return next((role for role, tokens in patterns if any(token in value for token in tokens)), None)


def _is_generic_bunker_name(name: str | None) -> bool:
    return _normalized_site_name(name) in {"", "bunker", "bunkier"}


def _is_military_airfield(tags: Mapping[str, Any], military_tag: str) -> bool:
    return military_tag == "airfield" or str(tags.get("aeroway") or "").casefold() in {
        "aerodrome", "airfield", "heliport",
    }


def _feature_exists_in_scenario(feature: TopographyFeature, scenario_year: int | None) -> bool:
    if scenario_year is None:
        return True
    if feature.valid_from is not None and feature.valid_from > scenario_year:
        return False
    return feature.valid_to is None or feature.valid_to >= scenario_year


def _site_layer(kind: InfrastructureSiteKind) -> str:
    return {
        InfrastructureSiteKind.ENERGY: "energy_sites",
        InfrastructureSiteKind.FUEL_STORAGE: "fuel_storage_sites",
        InfrastructureSiteKind.MILITARY: "military_sites",
        InfrastructureSiteKind.INDUSTRIAL: "industrial_sites",
        InfrastructureSiteKind.MARITIME: "maritime_sites",
    }[kind]


def _site_object_type(kind: InfrastructureSiteKind) -> str:
    return {
        InfrastructureSiteKind.ENERGY: "ENERGY_SITE",
        InfrastructureSiteKind.FUEL_STORAGE: "FUEL_STORAGE_SITE",
        InfrastructureSiteKind.MILITARY: "MILITARY_SITE",
        InfrastructureSiteKind.INDUSTRIAL: "INDUSTRIAL_SITE",
        InfrastructureSiteKind.MARITIME: "MARITIME_SITE",
    }[kind]


def _osm_tags(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _energy_sources(tags: Mapping[str, Any]) -> frozenset[EnergySource]:
    raw = str(tags.get("plant:source") or tags.get("generator:source") or "unknown")
    values = {part.strip().casefold() for part in raw.replace(",", ";").split(";") if part.strip()}
    aliases = {"photovoltaic": "solar", "water": "hydro", "natural_gas": "gas", "biofuel": "biomass"}
    resolved: set[EnergySource] = set()
    for value in values or {"unknown"}:
        normalized = aliases.get(value, value)
        try:
            resolved.add(EnergySource(normalized))
        except ValueError:
            resolved.add(EnergySource.OTHER)
    return frozenset(resolved)


def _energy_roles(category: str, tags: Mapping[str, Any]) -> frozenset[EnergyRole]:
    if category == "power_plant":
        return frozenset({EnergyRole.GENERATION})
    substation = str(tags.get("substation") or "").strip().casefold()
    if category == "power_converter" or substation == "converter":
        return frozenset({EnergyRole.CONVERTER_STATION})
    return frozenset({EnergyRole.GRID_SUBSTATION})


def _parse_voltage_kv(tags: Mapping[str, Any]) -> float | None:
    values: list[float] = []
    for item in _split_tag_values(tags.get("voltage")):
        text = item.strip().casefold().replace(" ", "")
        multiplier = 0.001
        if text.endswith("kv"):
            text = text[:-2]
            multiplier = 1.0
        elif text.endswith("v"):
            text = text[:-1]
        try:
            values.append(float(text.replace(",", ".")) * multiplier)
        except ValueError:
            continue
    return max(values) if values else None


def _parse_output_mw(tags: Mapping[str, Any]) -> float | None:
    raw = tags.get("plant:output:electricity") or tags.get("output:electricity")
    if raw is None:
        return None
    text = str(raw).strip().casefold().replace(" ", "")
    multipliers = {"gw": 1000.0, "mw": 1.0, "kw": 0.001, "w": 0.000001}
    for suffix, multiplier in multipliers.items():
        if text.endswith(suffix):
            try:
                return float(text[:-len(suffix)].replace(",", ".")) * multiplier
            except ValueError:
                return None
    try:
        return float(text)
    except ValueError:
        return None


def _representative_coordinate(geometry: Mapping[str, Any]) -> tuple[float, float]:
    points: list[tuple[float, float]] = []

    def collect(value: Any) -> None:
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            points.append((float(value[0]), float(value[1])))
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(geometry.get("coordinates"))
    if not points:
        raise ValueError("infrastructure geometry contains no coordinates")
    return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)


def _geometry_area_m2(geometry: Mapping[str, Any]) -> float:
    geometry_type = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon" and isinstance(coordinates, (list, tuple)):
        return _polygon_area_m2(coordinates)
    if geometry_type == "MultiPolygon" and isinstance(coordinates, (list, tuple)):
        return sum(_polygon_area_m2(polygon) for polygon in coordinates if isinstance(polygon, (list, tuple)))
    return 0.0


def _geometry_length_m(geometry: Mapping[str, Any]) -> float:
    geometry_type = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates")
    lines: list[Any] = []
    if geometry_type == "LineString":
        lines = [coordinates]
    elif geometry_type == "MultiLineString" and isinstance(coordinates, (list, tuple)):
        lines = list(coordinates)
    elif geometry_type == "Polygon" and isinstance(coordinates, (list, tuple)) and coordinates:
        lines = [coordinates[0]]
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, (list, tuple)):
        lines = [polygon[0] for polygon in coordinates if isinstance(polygon, (list, tuple)) and polygon]
    total = 0.0
    for line in lines:
        points = [point for point in line or () if isinstance(point, (list, tuple)) and len(point) >= 2]
        for first, second in zip(points, points[1:]):
            latitude = math.radians((float(first[1]) + float(second[1])) / 2)
            dx = math.radians(float(first[0]) - float(second[0])) * math.cos(latitude)
            dy = math.radians(float(first[1]) - float(second[1]))
            total += math.hypot(dx, dy) * 6_371_008.8
    return total


def _polygon_area_m2(rings: Any) -> float:
    if not isinstance(rings, (list, tuple)) or not rings:
        return 0.0
    areas = [_ring_area_m2(ring) for ring in rings if isinstance(ring, (list, tuple))]
    return max(0.0, areas[0] - sum(areas[1:])) if areas else 0.0


def _ring_area_m2(ring: Any) -> float:
    points = [
        (float(point[0]), float(point[1]))
        for point in ring
        if isinstance(point, (list, tuple))
        and len(point) >= 2
        and isinstance(point[0], (int, float))
        and isinstance(point[1], (int, float))
    ]
    if len(points) < 3:
        return 0.0
    latitude = math.radians(sum(point[1] for point in points) / len(points))
    scale_x = 6_371_008.8 * math.cos(latitude) * math.pi / 180
    scale_y = 6_371_008.8 * math.pi / 180
    projected = [(longitude * scale_x, latitude_value * scale_y) for longitude, latitude_value in points]
    return abs(sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(projected, projected[1:] + projected[:1])
    )) / 2


def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
