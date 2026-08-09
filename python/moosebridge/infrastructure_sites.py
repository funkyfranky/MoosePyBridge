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


class InfrastructureVerificationState(StrEnum):
    UNVERIFIED = "unverified"
    DCS_SCENERY_MATCHED = "dcs_scenery_matched"
    DCS_MISSION_OBJECT_MATCHED = "dcs_mission_object_matched"
    DCS_VISUAL_ONLY = "dcs_visual_only"
    NOT_REPRESENTED_IN_DCS = "not_represented_in_dcs"


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
            "layer", "object_id", "name", "object_type", "site_kind", "category", "coordinate_system",
            "latitude", "longitude", "source", "source_ids", "confidence", "scenario_reference_year",
            "verification_state", "component_ids", "energy_sources", "output_mw", "roles",
            "storage_roles", "commodities", "capacity_m3",
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
                energy_sources=tuple(
                    EnergySource(str(value)) for value in properties.get("energy_sources") or (EnergySource.UNKNOWN.value,)
                ),
                output_mw=_optional_float(properties.get("output_mw")),
            )
        if kind is InfrastructureSiteKind.FUEL_STORAGE:
            return FuelStorageSite(
                **common,
                storage_roles=tuple(FuelStorageRole(str(value)) for value in properties.get("storage_roles") or ()),
                commodities=tuple(StoredCommodity(str(value)) for value in properties.get("commodities") or ()),
                capacity_m3=_optional_float(properties.get("capacity_m3")),
            )
        return MilitarySite(
            **common,
            roles=tuple(MilitaryRole(str(value)) for value in properties.get("roles") or ()),
        )


@dataclass(slots=True, frozen=True)
class EnergySite(InfrastructureSite):
    """Power-generation or storage site admitted by a theater policy."""

    energy_sources: tuple[EnergySource, ...] = (EnergySource.UNKNOWN,)
    output_mw: float | None = None

    def __post_init__(self) -> None:
        InfrastructureSite.__post_init__(self)
        if self.kind is not InfrastructureSiteKind.ENERGY:
            raise ValueError("EnergySite kind must be energy")
        if self.output_mw is not None and self.output_mw < 0:
            raise ValueError("energy output must not be negative")

    def _specific_properties(self) -> dict[str, Any]:
        return {
            "category": "energy_site",
            "energy_sources": [source.value for source in self.energy_sources],
            "output_mw": self.output_mw,
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

    def __post_init__(self) -> None:
        InfrastructureSite.__post_init__(self)
        if self.kind is not InfrastructureSiteKind.MILITARY:
            raise ValueError("MilitarySite kind must be military")
        if not self.roles:
            raise ValueError("military site requires at least one role")

    def _specific_properties(self) -> dict[str, Any]:
        return {"category": "military_site", "roles": [role.value for role in self.roles]}


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
) -> TheaterInfrastructureSites:
    """Normalize OSM power plants while applying only the selected theater policy."""

    selected_policy = policy or infrastructure_policy_for_theater(theater_id)
    sites: list[InfrastructureSite] = []
    excluded: dict[str, int] = {}
    for feature in features:
        if feature.layer is not TopographyLayer.INFRASTRUCTURE or feature.category != "power_plant":
            continue
        tags = _osm_tags(feature.properties.get("osm_tags"))
        sources = _energy_sources(tags)
        rejected = sources.intersection(selected_policy.excluded_energy_sources)
        if rejected:
            for source in rejected:
                excluded[source.value] = excluded.get(source.value, 0) + 1
            continue
        longitude, latitude = _representative_coordinate(feature.geometry)
        source_key = feature.source_id or feature.object_id
        digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:16]
        sites.append(EnergySite(
            site_id=f"ENERGY_SITE:{digest}",
            kind=InfrastructureSiteKind.ENERGY,
            geometry=feature.geometry,
            latitude=latitude,
            longitude=longitude,
            source=feature.source,
            confidence=feature.confidence,
            name=feature.name,
            source_ids=(source_key,),
            scenario_reference_year=selected_policy.scenario_reference_year or feature.scenario_reference_year,
            verification_state=(InfrastructureVerificationState.DCS_VISUAL_ONLY if feature.dcs_verified else InfrastructureVerificationState.UNVERIFIED),
            component_ids=(feature.object_id,),
            energy_sources=tuple(sorted(sources, key=lambda item: item.value)),
            output_mw=_parse_output_mw(tags),
            properties={"osm_tags": tags},
        ))
    return TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=selected_policy.scenario_reference_year,
        sites=tuple(sites),
        metadata={"excluded_energy_source_counts": excluded},
    )


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
    role: MilitaryRole
    role_source: str
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
        role = _MILITARY_TAG_ROLES.get(military_tag)
        role_source = "military_tag"
        inferred = _military_role_from_name(feature.name)
        if military_tag in _NON_SITE_MILITARY_TAGS:
            role = inferred
            role_source = "name" if role is not None else role_source
            if role is None:
                excluded["non_site_role"] += 1
                continue
        elif role is None:
            role = inferred
            role_source = "name" if role is not None else role_source
        if role is None:
            excluded["ambiguous"] += 1
            continue
        if role is MilitaryRole.BUNKER_COMPLEX and not feature.name:
            excluded["unnamed_bunker"] += 1
            continue
        longitude, latitude = _representative_coordinate(feature.geometry)
        candidates.append(_MilitaryCandidate(
            feature=feature,
            latitude=latitude,
            longitude=longitude,
            role=role,
            role_source=role_source,
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
    return TheaterInfrastructureSites(
        theater_id=theater_id,
        scenario_reference_year=energy.scenario_reference_year,
        sites=(*energy.sites, *fuel.sites, *military.sites),
        metadata={
            "energy": energy.metadata,
            "fuel_storage": fuel.metadata,
            "military": military.metadata,
        },
    )


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


def _candidate_distance_m(first: _FuelCandidate | _MilitaryCandidate, second: _FuelCandidate | _MilitaryCandidate) -> float:
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
    roles = tuple(sorted({item.role for item in cluster}, key=lambda role: role.value))
    names = [item.feature.name for item in ordered if item.feature.name]
    operators = tuple(sorted({item.operator for item in cluster if item.operator}))
    role_sources = tuple(sorted({item.role_source for item in cluster}))
    explicit_role = "military_tag" in role_sources
    confidence = min(
        0.95,
        max(item.feature.confidence for item in cluster)
        + (0.15 if explicit_role else 0.05)
        + (0.1 if names else 0.0),
    )
    return MilitarySite(
        site_id=f"MILITARY_SITE:{digest}",
        kind=InfrastructureSiteKind.MILITARY,
        geometry=primary.feature.geometry,
        latitude=sum(item.latitude for item in cluster) / len(cluster),
        longitude=sum(item.longitude for item in cluster) / len(cluster),
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
        properties={
            "member_count": len(cluster),
            "operators": list(operators),
            "role_sources": list(role_sources),
            "targetable_candidate": bool(set(roles).intersection(_TARGETABLE_MILITARY_ROLES)),
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


def _normalized_site_name(name: str | None) -> str:
    return " ".join((name or "").casefold().replace("-", " ").split())


def _military_role_from_name(name: str | None) -> MilitaryRole | None:
    value = _normalized_site_name(name)
    if not value:
        return None
    patterns: tuple[tuple[MilitaryRole, tuple[str, ...]], ...] = (
        (MilitaryRole.AMMUNITION_STORAGE, ("munition", "ammunition", "munitionsdepot")),
        (MilitaryRole.FUEL_STORAGE, ("tanklager", "fuel depot", "carburant")),
        (MilitaryRole.NAVAL_BASE, ("naval base", "marinebasis", "marinestützpunkt", "flådestation")),
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
    }[kind]


def _site_object_type(kind: InfrastructureSiteKind) -> str:
    return {
        InfrastructureSiteKind.ENERGY: "ENERGY_SITE",
        InfrastructureSiteKind.FUEL_STORAGE: "FUEL_STORAGE_SITE",
        InfrastructureSiteKind.MILITARY: "MILITARY_SITE",
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
