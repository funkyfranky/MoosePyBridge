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
            "layer": "energy_sites" if self.kind is InfrastructureSiteKind.ENERGY else "military_sites",
            "object_id": self.site_id,
            "name": self.name,
            "object_type": "ENERGY_SITE" if self.kind is InfrastructureSiteKind.ENERGY else "MILITARY_SITE",
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
        return MilitarySite(**common, roles=tuple(str(value) for value in properties.get("roles") or ()))


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
class MilitarySite(InfrastructureSite):
    """Military installation kept separate from civilian infrastructure."""

    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        InfrastructureSite.__post_init__(self)
        if self.kind is not InfrastructureSiteKind.MILITARY:
            raise ValueError("MilitarySite kind must be military")

    def _specific_properties(self) -> dict[str, Any]:
        return {"category": "military_site", "roles": list(self.roles)}


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
