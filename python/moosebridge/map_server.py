"""Browser map service for the global MooseBridge situation picture."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
import math
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware

from .control import DEFAULT_CONTROL_PORT, MooseBridgeControlClient
from .control_sdk import sdk_from_control_client
from .capabilities import GroupInfluence, build_group_influence
from .frontlines import (
    FrontlineForceClassification,
    FrontlineCalculationArea,
    FrontlineConfig,
    FrontlineEngine,
    FrontlineForceTracker,
    FrontlineResult,
    classify_frontline_forces,
    force_points_from_groups,
    territory_control_regions,
)
from .pictures import GlobalPicture
from .operational_audit import execution_from_dict
from .recon import ReconArea, build_recon_coverage_footprints
from .recon import RECON_EXECUTION_AUDIT_TYPE
from .topography import TheaterTopography
from .theater_data import DEFAULT_THEATER_PROFILE_PATH, load_theater_profile
from .topography_viewport import DEFAULT_VIEWPORT_FEATURE_LIMIT, TopographyViewportStore
from .transport_infrastructure import TheaterTransportInfrastructure, TransportImportanceTier
from .railway_infrastructure import TheaterRailwayInfrastructure
from .infrastructure_sites import TheaterInfrastructureSites
from .settlements import TheaterSettlements
from .strategic_goals import generate_strategic_goals
from .strategic_verification import (
    ObservedDcsObject,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
    StrategicVerificationState,
    VerifiedDcsComponent,
)
from .surface_regions import TheaterSurfaceRegions

LOGGER = logging.getLogger(__name__)
DEFAULT_MAP_HOST = "127.0.0.1"
DEFAULT_MAP_PORT = 8000
DEFAULT_UPDATE_INTERVAL = 5.0
DEFAULT_COMMAND_TIMEOUT = 15.0
DEFAULT_HISTORY_SECONDS = 15 * 60.0
DEFAULT_HISTORY_MAX_POINTS = 180
DEFAULT_FRONTLINE_INTERVAL = 15.0
DEFAULT_AMMUNITION_INTERVAL = 60.0
DEFAULT_FRONTLINE_POSITION_ALPHA = 0.35
DEFAULT_FORCE_ANCHOR_SIGMA_M = 5_000.0
DEFAULT_FORCE_ANCHOR_MARGIN_RATIO = 0.25
DEFAULT_TERRITORY_CONTROL_RATIO = 1.0
DEFAULT_TERRITORY_TRANSITION_M = 20_000.0
DEFAULT_PRESSURE_TERRITORY_RATIO = 0.08
DEFAULT_INCURSION_SUPPORT_RADIUS_M = 30_000.0
DEFAULT_LODGEMENT_MIN_FORCES = 3
DEFAULT_MAX_TOPOGRAPHY_BYTES = 256 * 1024 * 1024
DEFAULT_TOPOGRAPHY_PATH = Path("tmp/topography/GermanyCW.geojson")
DEFAULT_TOPOGRAPHY_VIEWPORT_PATH = Path("tmp/topography/viewport/manifest.json")
DEFAULT_SURFACE_REGIONS_PATH = Path("tmp/topography/GermanyCW-surface-regions.geojson")
DEFAULT_TRANSPORT_INFRASTRUCTURE_PATH = Path("tmp/topography/GermanyCW-transport-infrastructure.geojson")
DEFAULT_RAILWAY_INFRASTRUCTURE_PATH = Path("tmp/topography/GermanyCW-railway-infrastructure.geojson")
DEFAULT_INFRASTRUCTURE_SITES_PATH = Path("tmp/topography/GermanyCW-infrastructure-sites.geojson")
DEFAULT_SETTLEMENTS_PATH = Path("tmp/topography/GermanyCW-settlements.geojson")
DEFAULT_STRATEGIC_VERIFICATIONS_PATH = Path("tmp/topography/GermanyCW-strategic-verifications.json")
MAP_UI_DIR = Path(__file__).with_name("map_ui")
TRACKED_LAYERS = frozenset({"groups", "units", "opsgroups", "friendly_opsgroups", "intel_contacts", "known_enemy_contacts"})


def empty_picture() -> dict[str, Any]:
    """Return an empty WGS84 feature collection."""

    return {
        "type": "FeatureCollection",
        "features": [],
        "properties": {"scope": "global", "coordinate_system": "WGS84"},
    }


@dataclass(slots=True, frozen=True)
class TrackPoint:
    """One observed object position in mission time."""

    mission_time: float
    longitude: float
    latitude: float
    x: float | None = None
    z: float | None = None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _marker_value(value: Any) -> str:
    """Return one compact, single-line marker value."""

    return " ".join(str(value or "").replace("_", " ").split())


def compact_dcs_marker_text(properties: dict[str, Any], *, max_length: int = 180) -> str:
    """Build concise F10 marker text from browser-map feature properties."""

    object_id = _marker_value(properties.get("object_id"))
    name = _marker_value(properties.get("name") or properties.get("display_name") or object_id or "Map object")
    category = _marker_value(
        properties.get("dcs_type")
        or properties.get("category")
        or properties.get("selection_category")
        or properties.get("object_type")
        or properties.get("layer")
    )
    side = _marker_value(properties.get("coalition") or properties.get("owner"))
    status = _marker_value(properties.get("status") or properties.get("state"))
    if not status and isinstance(properties.get("alive"), bool):
        status = "alive" if properties["alive"] else "destroyed"
    details = " | ".join(value for value in (category, side.title(), status) if value)
    lines = [name[:72]]
    if details:
        lines.append(details[:72])
    if object_id and object_id != name:
        lines.append(object_id[:72])
    text = "\n".join(lines)
    if len(text) > max_length:
        text = text[: max(1, max_length - 3)].rstrip() + "..."
    return text


def _distance_m(first: TrackPoint, second: TrackPoint) -> float:
    """Return planar DCS distance when available, otherwise great-circle distance."""

    if first.x is not None and first.z is not None and second.x is not None and second.z is not None:
        return math.hypot(second.x - first.x, second.z - first.z)
    latitude_1 = math.radians(first.latitude)
    latitude_2 = math.radians(second.latitude)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = math.radians(second.longitude - first.longitude)
    haversine = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(haversine)))


def _heading_deg(first: TrackPoint, second: TrackPoint) -> float | None:
    """Return movement heading in degrees clockwise from north."""

    if first.x is not None and first.z is not None and second.x is not None and second.z is not None:
        delta_x = second.x - first.x
        delta_z = second.z - first.z
        if delta_x == 0 and delta_z == 0:
            return None
        return (math.degrees(math.atan2(delta_x, delta_z)) + 360) % 360
    if first.longitude == second.longitude and first.latitude == second.latitude:
        return None
    longitude_delta = math.radians(second.longitude - first.longitude)
    latitude_1 = math.radians(first.latitude)
    latitude_2 = math.radians(second.latitude)
    y = math.sin(longitude_delta) * math.cos(latitude_2)
    x = math.cos(latitude_1) * math.sin(latitude_2) - math.sin(latitude_1) * math.cos(latitude_2) * math.cos(longitude_delta)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


@dataclass(slots=True)
class GlobalMapRuntime:
    """Refresh global state and fan it out to connected browsers."""

    control_host: str = "127.0.0.1"
    control_port: int = DEFAULT_CONTROL_PORT
    interval: float = DEFAULT_UPDATE_INTERVAL
    timeout: float = DEFAULT_COMMAND_TIMEOUT
    history_seconds: float = DEFAULT_HISTORY_SECONDS
    history_max_points: int = DEFAULT_HISTORY_MAX_POINTS
    frontline_interval: float = DEFAULT_FRONTLINE_INTERVAL
    ammunition_interval: float = DEFAULT_AMMUNITION_INTERVAL
    frontline_position_alpha: float = DEFAULT_FRONTLINE_POSITION_ALPHA
    force_anchor_sigma_m: float = DEFAULT_FORCE_ANCHOR_SIGMA_M
    force_anchor_margin_ratio: float = DEFAULT_FORCE_ANCHOR_MARGIN_RATIO
    territory_control_ratio: float = DEFAULT_TERRITORY_CONTROL_RATIO
    territory_transition_m: float = DEFAULT_TERRITORY_TRANSITION_M
    pressure_territory_ratio: float = DEFAULT_PRESSURE_TERRITORY_RATIO
    incursion_support_radius_m: float = DEFAULT_INCURSION_SUPPORT_RADIUS_M
    lodgement_min_forces: int = DEFAULT_LODGEMENT_MIN_FORCES
    theater_id: str | None = None
    topography_path: Path | None = None
    max_topography_bytes: int = DEFAULT_MAX_TOPOGRAPHY_BYTES
    topography_viewport_path: Path | None = None
    surface_regions_path: Path | None = None
    transport_infrastructure_path: Path | None = None
    railway_infrastructure_path: Path | None = None
    infrastructure_sites_path: Path | None = None
    settlements_path: Path | None = None
    strategic_verifications_path: Path | None = None
    picture: dict[str, Any] = field(default_factory=empty_picture)
    connected: bool = False
    error: str | None = None
    clients: set[WebSocket] = field(default_factory=set)
    tracks: dict[str, deque[TrackPoint]] = field(default_factory=dict)
    _task: asyncio.Task[None] | None = None
    _mission_generation: int = 0
    _last_mission_time: float | None = None
    _frontline_mission_time: float | None = None
    _influence_mission_time: float | None = None
    _group_influences: dict[str, GroupInfluence] = field(default_factory=dict)
    _frontline_features: list[dict[str, Any]] = field(default_factory=list)
    _pressure_frontline_features: list[dict[str, Any]] = field(default_factory=list)
    _incursion_features: list[dict[str, Any]] = field(default_factory=list)
    _frontline_diagnostics: dict[str, Any] = field(default_factory=dict)
    _frontline_error: str | None = None
    _recon_features: list[dict[str, Any]] = field(default_factory=list)
    _recon_audit_signature: tuple[tuple[str, str], ...] = ()
    _recon_error: str | None = None
    _strategic_objective_signature: tuple[Any, ...] = ()
    _strategic_objective_error: str | None = None
    _strategic_goal_generation_number: int = 0
    _bridge: Any = field(init=False, default=None, repr=False)
    _diplomacy_event_cursor: str | None = None
    _border_violation_signature: tuple[tuple[str, str, float, bool], ...] = ()
    _topography: TheaterTopography | None = field(init=False, default=None)
    _topography_load_warning: str | None = field(init=False, default=None)
    _topography_viewport: TopographyViewportStore | None = field(init=False, default=None)
    _topography_viewport_error: str | None = field(init=False, default=None)
    _surface_regions: TheaterSurfaceRegions | None = field(init=False, default=None)
    _transport_infrastructure: TheaterTransportInfrastructure | None = field(init=False, default=None)
    _railway_infrastructure: TheaterRailwayInfrastructure | None = field(init=False, default=None)
    _infrastructure_sites: TheaterInfrastructureSites | None = field(init=False, default=None)
    _settlements: TheaterSettlements | None = field(init=False, default=None)
    _strategic_verifications: StrategicVerificationRegistry = field(init=False)
    _frontline_tracker: FrontlineForceTracker = field(init=False)
    _frontline_engine: FrontlineEngine = field(init=False)

    def __post_init__(self) -> None:
        if self.frontline_interval <= 0:
            raise ValueError("frontline_interval must be positive")
        if self.ammunition_interval <= 0:
            raise ValueError("ammunition_interval must be positive")
        self._frontline_tracker = FrontlineForceTracker(self.frontline_position_alpha)
        self._frontline_engine = FrontlineEngine(
            FrontlineConfig(
                territory_control_ratio=self.territory_control_ratio,
                territory_transition_m=self.territory_transition_m,
                pressure_territory_ratio=self.pressure_territory_ratio,
                force_anchor_sigma_m=self.force_anchor_sigma_m,
                force_anchor_margin_ratio=self.force_anchor_margin_ratio,
                incursion_support_radius_m=self.incursion_support_radius_m,
                incursion_lodgement_min_forces=self.lodgement_min_forces,
            )
        )
        self.load_topography()
        self.load_topography_viewport()
        self.load_surface_regions()
        self.load_transport_infrastructure()
        self.load_railway_infrastructure()
        self.load_infrastructure_sites()
        self.load_settlements()
        self.load_strategic_verifications()

    def load_strategic_verifications(self) -> StrategicVerificationRegistry:
        """Load scenario-specific DCS component mappings."""

        self._strategic_verifications = (
            StrategicVerificationRegistry.load(self.strategic_verifications_path)
            if self.strategic_verifications_path is not None
            else StrategicVerificationRegistry()
        )
        LOGGER.info(
            "Loaded %d strategic DCS verifications from %s",
            len(self._strategic_verifications.entries),
            self.strategic_verifications_path or "memory",
        )
        return self._strategic_verifications

    def strategic_verifications_payload(self) -> dict[str, Any]:
        """Return all verification mappings used by the map and generator."""

        if self.strategic_verifications_path is not None:
            self._strategic_verifications = StrategicVerificationRegistry.load(self.strategic_verifications_path)
        return self._strategic_verifications.to_dict()

    def save_strategic_verification(self, payload: dict[str, Any]) -> StrategicSiteVerification:
        """Validate and persist one source-site mapping."""

        if self.strategic_verifications_path is not None:
            self._strategic_verifications = StrategicVerificationRegistry.load(self.strategic_verifications_path)
        verification = StrategicSiteVerification(
            source_id=str(payload.get("source_id") or ""),
            state=StrategicVerificationState(str(payload.get("state") or "unverified")),
            observed_objects=tuple(
                ObservedDcsObject.from_dict(item)
                for item in payload.get("observed_objects") or ()
                if isinstance(item, dict)
            ),
            observation_complete=payload.get("observation_complete") is True,
            target_components=tuple(
                VerifiedDcsComponent.from_dict(item)
                for item in payload.get("target_components") or ()
                if isinstance(item, dict)
            ),
            notes=str(payload.get("notes") or ""),
        )
        self._strategic_verifications.upsert(verification)
        if self.strategic_verifications_path is not None:
            self._strategic_verifications.save(self.strategic_verifications_path)
        self._strategic_objective_signature = ()
        return verification

    async def assess_strategic_verification(self, source_id: str) -> dict[str, object]:
        """Run one bounded DCS survey against an immutable infrastructure baseline."""

        bridge = self._bridge
        if bridge is None or not self.connected:
            raise RuntimeError("DCS bridge is not connected")
        if self.strategic_verifications_path is not None:
            self._strategic_verifications = StrategicVerificationRegistry.load(self.strategic_verifications_path)
        verification = self._strategic_verifications.get(source_id)
        if verification is None:
            raise KeyError(f"No strategic verification exists for {source_id}")
        if not verification.observed_objects:
            raise ValueError(f"Strategic verification has no DCS observation baseline: {source_id}")
        if self._infrastructure_sites is None:
            raise ValueError("Normalized infrastructure sites are not loaded")
        site = next((item for item in self._infrastructure_sites.sites if item.site_id == source_id), None)
        if site is None:
            raise ValueError(f"Current state assessment is not supported for this feature type: {source_id}")
        assessment = await bridge.assess_infrastructure_site(
            site,
            verification,
            timeout=self.timeout,
        )
        return assessment.to_dict()

    def load_topography(self) -> TheaterTopography | None:
        """Load the optional static theater cache without touching DCS."""

        self._topography = None
        self._topography_load_warning = None
        if self.topography_path is None or not self.topography_path.is_file():
            return None
        size_bytes = self.topography_path.stat().st_size
        if self.max_topography_bytes > 0 and size_bytes > self.max_topography_bytes:
            self._topography_load_warning = (
                f"Static topography cache is {size_bytes / (1024 * 1024):.1f} MiB; "
                f"the configured in-memory limit is {self.max_topography_bytes / (1024 * 1024):.1f} MiB. "
                "Use a bounded cache or viewport/tile delivery."
            )
            LOGGER.warning("Skipping %s: %s", self.topography_path, self._topography_load_warning)
            return None
        self._topography = TheaterTopography.load(self.topography_path)
        self._validate_theater_id(self._topography.theater_id, self.topography_path)
        LOGGER.info(
            "Loaded %d %s topography features from %s",
            len(self._topography.features),
            self._topography.theater_id,
            self.topography_path,
        )
        return self._topography

    def topography_geojson(self) -> dict[str, Any]:
        """Return the static theater data independently of mission updates."""

        return self._topography.to_geojson() if self._topography is not None else empty_picture()

    def load_topography_viewport(self) -> TopographyViewportStore | None:
        """Load the optional indexed topography manifest without reading its shards."""

        self._topography_viewport = None
        self._topography_viewport_error = None
        if self.topography_viewport_path is None or not self.topography_viewport_path.is_file():
            return None
        try:
            self._topography_viewport = TopographyViewportStore(self.topography_viewport_path)
        except (OSError, ValueError) as exc:
            self._topography_viewport_error = str(exc)
            LOGGER.warning("Could not load topography viewport manifest %s: %s", self.topography_viewport_path, exc)
            return None
        self._validate_theater_id(self._topography_viewport.theater_id, self.topography_viewport_path)
        LOGGER.info(
            "Loaded %d-feature %s topography viewport index from %s",
            self._topography_viewport.feature_count,
            self._topography_viewport.theater_id,
            self.topography_viewport_path,
        )
        return self._topography_viewport

    def topography_viewport_geojson(
        self,
        bounds: tuple[float, float, float, float],
        *,
        zoom: float,
        layers: list[str] | None = None,
        limit: int = DEFAULT_VIEWPORT_FEATURE_LIMIT,
    ) -> dict[str, Any]:
        """Return indexed topography for one visible browser extent."""

        if self._topography_viewport is None:
            return empty_picture()
        return self._topography_viewport.query(bounds, zoom=zoom, layers=layers, limit=limit)

    def topography_vector_tile(self, layer: str, zoom: int, x: int, y: int) -> tuple[bytes, dict[str, Any]]:
        """Return one cached MVT tile and its diagnostics."""

        if self._topography_viewport is None:
            return b"", {"feature_count": 0, "truncated": False}
        return self._topography_viewport.vector_tile(layer, zoom, x, y)

    def load_surface_regions(self) -> TheaterSurfaceRegions | None:
        """Load optional static connected surface components."""

        self._surface_regions = None
        if self.surface_regions_path is None or not self.surface_regions_path.is_file():
            return None
        self._surface_regions = TheaterSurfaceRegions.load(self.surface_regions_path)
        self._validate_theater_id(self._surface_regions.theater_id, self.surface_regions_path)
        LOGGER.info(
            "Loaded %d %s surface regions from %s",
            len(self._surface_regions.regions),
            self._surface_regions.theater_id,
            self.surface_regions_path,
        )
        if not self._surface_regions.metadata.get("source_complete", True):
            LOGGER.warning("Surface-region source coverage is incomplete: %s", self.surface_regions_path)
        return self._surface_regions

    def surface_regions_geojson(self) -> dict[str, Any]:
        """Return connected static land/water components."""

        return self._surface_regions.to_geojson() if self._surface_regions is not None else empty_picture()

    def load_transport_infrastructure(self) -> TheaterTransportInfrastructure | None:
        """Load optional static bridges and strategic road junctions."""

        self._transport_infrastructure = None
        if self.transport_infrastructure_path is None or not self.transport_infrastructure_path.is_file():
            return None
        self._transport_infrastructure = TheaterTransportInfrastructure.load(self.transport_infrastructure_path)
        self._validate_theater_id(
            self._transport_infrastructure.theater_id,
            self.transport_infrastructure_path,
        )
        LOGGER.info(
            "Loaded %d bridges and %d strategic junctions for %s from %s",
            len(self._transport_infrastructure.bridges),
            len(self._transport_infrastructure.junctions),
            self._transport_infrastructure.theater_id,
            self.transport_infrastructure_path,
        )
        return self._transport_infrastructure

    def transport_infrastructure_geojson(
        self,
        *,
        bounds: tuple[float, float, float, float] | None = None,
        minimum_importance_tier: str | None = None,
    ) -> dict[str, Any]:
        """Return static bridge and junction features."""

        tier = None
        if minimum_importance_tier is not None:
            try:
                tier = TransportImportanceTier(minimum_importance_tier)
            except ValueError as exc:
                raise ValueError(f"invalid transport importance tier: {minimum_importance_tier}") from exc
        return (
            self._transport_infrastructure.to_geojson(
                bounds=bounds,
                minimum_importance_tier=tier,
            )
            if self._transport_infrastructure is not None else empty_picture()
        )

    def load_railway_infrastructure(self) -> TheaterRailwayInfrastructure | None:
        """Load optional aggregated railway facilities and network locations."""

        self._railway_infrastructure = None
        if self.railway_infrastructure_path is None or not self.railway_infrastructure_path.is_file():
            return None
        self._railway_infrastructure = TheaterRailwayInfrastructure.load(self.railway_infrastructure_path)
        self._validate_theater_id(
            self._railway_infrastructure.theater_id,
            self.railway_infrastructure_path,
        )
        LOGGER.info(
            "Loaded %d railway infrastructure locations for %s from %s",
            len(self._railway_infrastructure.locations),
            self._railway_infrastructure.theater_id,
            self.railway_infrastructure_path,
        )
        return self._railway_infrastructure

    def railway_infrastructure_geojson(self) -> dict[str, Any]:
        """Return aggregated static railway infrastructure locations."""

        return self._railway_infrastructure.to_geojson() if self._railway_infrastructure else empty_picture()

    def load_infrastructure_sites(self) -> TheaterInfrastructureSites | None:
        """Load optional normalized infrastructure sites."""

        self._infrastructure_sites = None
        if self.infrastructure_sites_path is None or not self.infrastructure_sites_path.is_file():
            return None
        self._infrastructure_sites = TheaterInfrastructureSites.load(self.infrastructure_sites_path)
        self._validate_theater_id(self._infrastructure_sites.theater_id, self.infrastructure_sites_path)
        LOGGER.info(
            "Loaded %d normalized infrastructure sites for %s from %s",
            len(self._infrastructure_sites.sites),
            self._infrastructure_sites.theater_id,
            self.infrastructure_sites_path,
        )
        return self._infrastructure_sites

    def infrastructure_sites_geojson(self) -> dict[str, Any]:
        """Return map-ready sites, preserving normalized strategic footprints."""

        if not self._infrastructure_sites:
            return empty_picture()
        payload = self._infrastructure_sites.to_geojson()
        for site, feature in zip(self._infrastructure_sites.sites, payload["features"], strict=True):
            source_geometry = feature.get("geometry") or {}
            feature.setdefault("properties", {})["source_geometry_type"] = source_geometry.get("type")
            if site.kind.value in {"energy", "military", "industrial", "maritime"} and source_geometry.get("type") in {"Polygon", "MultiPolygon"}:
                continue
            feature["geometry"] = {
                "type": "Point",
                "coordinates": [site.longitude, site.latitude],
            }
        return payload

    def load_settlements(self) -> TheaterSettlements | None:
        """Load optional normalized cities and towns."""

        self._settlements = None
        if self.settlements_path is None or not self.settlements_path.is_file():
            return None
        self._settlements = TheaterSettlements.load(self.settlements_path)
        self._validate_theater_id(self._settlements.theater_id, self.settlements_path)
        LOGGER.info(
            "Loaded %d normalized settlements for %s from %s",
            len(self._settlements.settlements),
            self._settlements.theater_id,
            self.settlements_path,
        )
        return self._settlements

    def _validate_theater_id(self, actual: str, path: Path) -> None:
        """Reject accidental mixtures of artifacts from different theaters."""

        if self.theater_id and actual.casefold() != self.theater_id.casefold():
            raise ValueError(
                f"theater artifact mismatch: expected {self.theater_id}, "
                f"found {actual or '<missing>'} in {path}"
            )

    def settlements_geojson(self) -> dict[str, Any]:
        """Return normalized city and town objects with their urban footprints."""

        return self._settlements.to_geojson() if self._settlements is not None else empty_picture()

    def status_payload(self) -> dict[str, Any]:
        """Return the current browser-facing service status."""

        properties = self.picture.get("properties") if isinstance(self.picture.get("properties"), dict) else {}
        return {
            "connected": self.connected,
            "mission_generation": self._mission_generation,
            "error": self.error,
            "feature_count": len(self.picture.get("features", [])),
            "sequence": properties.get("sequence"),
            "mission_time": properties.get("mission_time"),
            "dcs_date": properties.get("dcs_date"),
            "dcs_time_of_day": properties.get("dcs_time_of_day"),
            "wall_time": properties.get("wall_time"),
            "trajectory_count": sum(1 for feature in self.picture.get("features", []) if feature.get("properties", {}).get("layer") == "trajectories"),
            "history_seconds": self.history_seconds,
            "frontline_count": len(self._frontline_features),
            "pressure_line_count": len(self._pressure_frontline_features),
            "incursion_count": len(self._incursion_features),
            "frontline_updated_mission_time": self._frontline_mission_time,
            "influence_updated_mission_time": self._influence_mission_time,
            "frontline_error": self._frontline_error,
            "recon_coverage_count": len(self._recon_features),
            "recon_coverage_error": self._recon_error,
            "strategic_objective_count": sum(
                1
                for feature in self.picture.get("features", [])
                if feature.get("properties", {}).get("layer") == "strategic_objectives"
            ),
            "strategic_objective_error": self._strategic_objective_error,
            "topography_theater_id": self._topography.theater_id if self._topography else None,
            "topography_feature_count": len(self._topography.features) if self._topography else 0,
            "topography_load_warning": self._topography_load_warning,
            "topography_viewport_available": self._topography_viewport is not None,
            "topography_viewport_feature_count": self._topography_viewport.feature_count if self._topography_viewport else 0,
            "topography_viewport_error": self._topography_viewport_error,
            "surface_region_count": len(self._surface_regions.regions) if self._surface_regions else 0,
            "surface_regions_source_complete": (
                self._surface_regions.metadata.get("source_complete") if self._surface_regions else None
            ),
            "transport_bridge_count": (
                len(self._transport_infrastructure.bridges) if self._transport_infrastructure else 0
            ),
            "transport_junction_count": (
                len(self._transport_infrastructure.junctions) if self._transport_infrastructure else 0
            ),
            "railway_infrastructure_count": (
                len(self._railway_infrastructure.locations) if self._railway_infrastructure else 0
            ),
            "infrastructure_site_count": len(self._infrastructure_sites.sites) if self._infrastructure_sites else 0,
            "settlement_count": len(self._settlements.settlements) if self._settlements else 0,
            "strategic_verification_count": len(self._strategic_verifications.entries),
            "diplomacy": properties.get("diplomacy"),
        }

    def reset_mission(self, generation: int) -> None:
        """Clear all browser-facing caches owned by the completed mission."""

        self._mission_generation = generation
        self.picture = empty_picture()
        self.tracks.clear()
        self._last_mission_time = None
        self._frontline_mission_time = None
        self._influence_mission_time = None
        self._group_influences.clear()
        self._frontline_features.clear()
        self._pressure_frontline_features.clear()
        self._incursion_features.clear()
        self._frontline_diagnostics.clear()
        self._frontline_error = None
        self._recon_features.clear()
        self._recon_audit_signature = ()
        self._recon_error = None
        self._strategic_objective_signature = ()
        self._strategic_objective_error = None
        self._strategic_goal_generation_number = 0
        self._diplomacy_event_cursor = None
        self._border_violation_signature = ()
        self._frontline_tracker.reset()

    def update_picture(self, picture: dict[str, Any]) -> dict[str, Any]:
        """Record movement observations and append trajectory features."""

        properties = dict(picture.get("properties") or {})
        mission_time = _number(properties.get("mission_time"))
        source_features = picture.get("features") if isinstance(picture.get("features"), list) else []
        if mission_time is None:
            self.picture = {**picture, "features": list(source_features)}
            return self.picture

        if self._last_mission_time is not None and mission_time < self._last_mission_time:
            self.tracks.clear()
        self._last_mission_time = mission_time

        current_ids: set[str] = set()
        decorated_features: list[dict[str, Any]] = []
        for source_feature in source_features:
            feature = {**source_feature, "properties": dict(source_feature.get("properties") or {})}
            feature_properties = feature["properties"]
            object_id = str(feature_properties.get("object_id") or "")
            layer = str(feature_properties.get("layer") or "")
            geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
            coordinates = geometry.get("coordinates") if geometry.get("type") == "Point" else None
            trackable = (
                object_id
                and layer in TRACKED_LAYERS
                and feature_properties.get("alive") is not False
                and isinstance(coordinates, list)
                and len(coordinates) >= 2
            )
            if trackable:
                longitude = _number(coordinates[0])
                latitude = _number(coordinates[1])
                if longitude is not None and latitude is not None:
                    current_ids.add(object_id)
                    point = TrackPoint(
                        mission_time,
                        longitude,
                        latitude,
                        _number(feature_properties.get("x")),
                        _number(feature_properties.get("z")),
                    )
                    history = self.tracks.setdefault(object_id, deque(maxlen=max(2, self.history_max_points)))
                    history.append(point)
                    cutoff = mission_time - max(0.0, self.history_seconds)
                    while len(history) > 1 and history[0].mission_time < cutoff:
                        history.popleft()
                    self._add_movement_properties(feature_properties, history, mission_time)
            decorated_features.append(feature)

        for object_id in tuple(self.tracks):
            if object_id not in current_ids:
                del self.tracks[object_id]

        trajectories = self._trajectory_features(decorated_features)
        properties["trajectory_count"] = len(trajectories)
        properties["history_seconds"] = self.history_seconds
        self.picture = {**picture, "features": [*decorated_features, *trajectories], "properties": properties}
        return self.picture

    def update_strategic_objectives(self, picture: GlobalPicture, bridge: Any) -> None:
        """Generate and synchronize the map server's mission-scoped objective view."""

        verification_signature: tuple[int, int] | tuple[()] = ()
        if self.strategic_verifications_path is not None and self.strategic_verifications_path.is_file():
            verification_stat = self.strategic_verifications_path.stat()
            verification_signature = (verification_stat.st_mtime_ns, verification_stat.st_size)
            self._strategic_verifications = StrategicVerificationRegistry.load(self.strategic_verifications_path)
        signature = (
            int(bridge.state.mission_generation),
            tuple(
                sorted(
                    (territory.object_id, territory.coalition, territory.shape, len(territory.vertices))
                    for territory in picture.territories
                )
            ),
            bool(self._settlements),
            bool(self._transport_infrastructure),
            bool(self._railway_infrastructure),
            bool(self._infrastructure_sites),
            verification_signature,
        )
        try:
            if signature != self._strategic_objective_signature:
                bridge.generate_strategic_objectives(
                    settlements=self._settlements,
                    transport=self._transport_infrastructure,
                    railway=self._railway_infrastructure,
                    infrastructure=self._infrastructure_sites,
                    verifications=self._strategic_verifications,
                    register=True,
                    replace=True,
                )
                self._strategic_objective_signature = signature
            else:
                bridge.sync_strategic_objectives(source="map.refresh")
            picture.strategic_objectives.clear()
            picture.strategic_objectives.extend(bridge.strategic_objectives())
            self._strategic_objective_error = None
        except ValueError as exc:
            error = str(exc)
            if error != self._strategic_objective_error:
                LOGGER.warning("Strategic objective update unavailable: %s", error)
            else:
                LOGGER.debug("Strategic objective update still unavailable: %s", error)
            self._strategic_objective_error = error

    def create_strategic_goal(self, objective_id: str, coalition: str) -> dict[str, Any]:
        """Derive and register one planned coalition goal selected on the map."""

        bridge = self._bridge
        if bridge is None or not self.connected:
            raise RuntimeError("DCS bridge is not connected")
        objective = bridge.strategic_objective(str(objective_id).strip())
        if objective is None:
            raise KeyError(f"Unknown strategic objective: {objective_id}")
        self._strategic_goal_generation_number += 1
        generation_id = f"MAP:{self._mission_generation}:{self._strategic_goal_generation_number}"
        properties = self.picture.get("properties") if isinstance(self.picture.get("properties"), dict) else {}
        result = generate_strategic_goals(
            (objective,),
            coalition,
            relationship=bridge.relationship,
            existing_goals=bridge.strategic_goals(),
            mission_time=_number(properties.get("mission_time")),
            generation_id=generation_id,
            metadata={"selected_from": "global_map"},
        )
        if not result.goals:
            reason = result.decisions[0].reason if result.decisions else "No strategic goal could be derived"
            raise ValueError(reason)
        goal = bridge.add_strategic_goal(result.goals[0])
        self.annotate_strategic_goals(self.picture, bridge)
        return {
            "goal_id": goal.goal_id,
            "name": goal.name,
            "coalition": goal.coalition,
            "action": goal.action.value,
            "objective_id": goal.objective_id,
            "priority": goal.priority,
            "status": goal.status.value,
            "reason": result.decisions[0].reason,
        }

    async def create_dcs_marker(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create an all-visible F10 marker for one selected map feature."""

        bridge = self._bridge
        if bridge is None or not self.connected:
            raise RuntimeError("DCS bridge is not connected")
        properties = payload.get("properties")
        point = payload.get("point")
        if not isinstance(properties, dict) or not isinstance(point, dict):
            raise ValueError("properties and point are required")
        text = compact_dcs_marker_text(properties)
        x, z = _number(point.get("x")), _number(point.get("z"))
        latitude, longitude = _number(point.get("latitude")), _number(point.get("longitude"))
        if x is not None and z is not None:
            ack = await bridge.mark_map_position(
                text,
                x=x,
                y=_number(point.get("y")) or 0.0,
                z=z,
                coalition="all",
                read_only=False,
                timeout=self.timeout,
            )
        elif latitude is not None and longitude is not None:
            ack = await bridge.mark_map_position(
                text,
                latitude=latitude,
                longitude=longitude,
                altitude=_number(point.get("altitude")) or 0.0,
                coalition="all",
                read_only=False,
                timeout=self.timeout,
            )
        else:
            raise ValueError("point requires x/z or latitude/longitude")
        result = ack.get("result") if isinstance(ack.get("result"), dict) else ack
        return {
            "mark_id": result.get("mark_id"),
            "text": text,
            "coalition": result.get("coalition", -1),
            "read_only": result.get("read_only", False),
        }

    @staticmethod
    def annotate_strategic_goals(geojson: dict[str, Any], bridge: Any) -> dict[str, Any]:
        """Attach coalition-private goal state to its shared objective feature."""

        goals_by_objective: dict[str, list[Any]] = {}
        for goal in bridge.strategic_goals():
            goals_by_objective.setdefault(goal.objective_id, []).append(goal)
        for feature in geojson.get("features") or ():
            properties = feature.get("properties") if isinstance(feature, dict) else None
            if not isinstance(properties, dict) or properties.get("layer") != "strategic_objectives":
                continue
            goals = goals_by_objective.get(str(properties.get("object_id") or ""), [])
            properties["goal_count"] = len(goals)
            for coalition in ("blue", "red"):
                matching = [goal for goal in goals if goal.coalition == coalition]
                if not matching:
                    continue
                goal = matching[-1]
                properties[f"{coalition}_goal_id"] = goal.goal_id
                properties[f"{coalition}_goal_action"] = goal.action.value
                properties[f"{coalition}_goal_status"] = goal.status.value
        return geojson

    async def update_frontline(
        self,
        picture: GlobalPicture,
        geojson: dict[str, Any],
        bridge: Any,
    ) -> dict[str, Any]:
        """Append a periodically recalculated operational frontline."""

        mission_time = picture.clock.mission_time if picture.clock else None
        if (
            mission_time is not None
            and self._frontline_mission_time is not None
            and mission_time < self._frontline_mission_time
        ):
            self._frontline_tracker.reset()
            self._frontline_features.clear()
            self._pressure_frontline_features.clear()
            self._incursion_features.clear()
            self._frontline_diagnostics.clear()
            self._frontline_error = None
            self._frontline_mission_time = None
            self._influence_mission_time = None
            self._group_influences.clear()

        due = (
            self._frontline_mission_time is None
            or mission_time is None
            or mission_time - self._frontline_mission_time >= self.frontline_interval
        )
        if due:
            influence_due = (
                self._influence_mission_time is None
                or mission_time is None
                or mission_time - self._influence_mission_time >= self.ammunition_interval
            )
            if influence_due:
                ammunition = await bridge.refresh_ammunition()
                ammunition_by_group: dict[str, list[Any]] = {}
                for unit in ammunition:
                    if unit.group_id:
                        ammunition_by_group.setdefault(unit.group_id, []).append(unit)
                self._group_influences = {
                    group_id: build_group_influence(units, group_id, weapon_ranges=bridge.weapon_range_registry)
                    for group_id, units in ammunition_by_group.items()
                }
                self._influence_mission_time = mission_time
            forces = self._frontline_tracker.update(
                force_points_from_groups(picture.groups, influences=self._group_influences)
            )
            regions = territory_control_regions(picture.territories)
            classification = classify_frontline_forces(
                forces,
                regions,
                support_radius_m=self._frontline_engine.config.incursion_support_radius_m,
                lodgement_min_forces=self._frontline_engine.config.incursion_lodgement_min_forces,
            )
            self._incursion_features = self._incursion_geojson_features(classification, geojson)
            if {force.coalition for force in classification.main_forces} == {"blue", "red"}:
                area = None
                try:
                    area = FrontlineCalculationArea.from_territories(picture.territories)
                except ValueError:
                    pass
                result = self._frontline_engine.calculate(
                    forces,
                    area=area,
                    control_regions=regions,
                    pressure_forces=classification.main_forces,
                )
                (
                    self._frontline_features,
                    self._pressure_frontline_features,
                ) = await self._frontline_geojson_features(result, bridge)
                self._frontline_diagnostics = {
                    **result.diagnostics,
                    "ground_force_count": len(forces),
                    "control_power_blue": sum(force.weight for force in forces if force.coalition == "blue"),
                    "control_power_red": sum(force.weight for force in forces if force.coalition == "red"),
                    "main_control_power_blue": sum(
                        force.weight for force in classification.main_forces if force.coalition == "blue"
                    ),
                    "main_control_power_red": sum(
                        force.weight for force in classification.main_forces if force.coalition == "red"
                    ),
                    "incursion_control_power_blue": sum(
                        incursion.force.weight
                        for incursion in classification.incursions
                        if incursion.force.coalition == "blue"
                    ),
                    "incursion_control_power_red": sum(
                        incursion.force.weight
                        for incursion in classification.incursions
                        if incursion.force.coalition == "red"
                    ),
                    "logistics_group_count": sum(
                        1 for influence in self._group_influences.values() if influence.get("logistics") is not None
                    ),
                    "main_force_count": len(classification.main_forces),
                    "incursion_count": len(classification.incursions),
                }
            else:
                self._frontline_features = []
                self._pressure_frontline_features = []
                self._frontline_diagnostics = {
                    "input_force_count": len(forces),
                    "main_force_count": len(classification.main_forces),
                    "incursion_count": len(classification.incursions),
                    "segment_count": 0,
                    "reason": "both blue and red main-front ground forces are required",
                }
            self._frontline_mission_time = mission_time
            self._frontline_error = None

        self._add_influence_properties(geojson, self._group_influences)

        features = geojson.get("features")
        if isinstance(features, list):
            features.extend(self._frontline_features)
            features.extend(self._pressure_frontline_features)
            features.extend(self._incursion_features)
        properties = geojson.setdefault("properties", {})
        properties["frontline_count"] = len(self._frontline_features)
        properties["pressure_line_count"] = len(self._pressure_frontline_features)
        properties["incursion_count"] = len(self._incursion_features)
        properties["frontline_updated_mission_time"] = self._frontline_mission_time
        properties["frontline_diagnostics"] = self._frontline_diagnostics
        return geojson

    async def update_recon_coverage(
        self,
        picture: GlobalPicture,
        geojson: dict[str, Any],
        bridge: Any,
    ) -> dict[str, Any]:
        """Append persisted potential RECON sensor coverage to the map."""

        operational_records = await bridge.server.query_audit_records(
            record_type="operational_plan.execution",
            latest_attempts=True,
        )
        direct_records = await bridge.server.query_audit_records(
            record_type=RECON_EXECUTION_AUDIT_TYPE,
            latest_attempts=True,
        )
        queried_records = (*operational_records, *direct_records)
        mission_generation = int(bridge.state.mission_generation)
        audit_session_id = str(bridge.state.audit_session_id or "")
        latest_by_plan: dict[str, dict[str, Any]] = {}
        for record in queried_records:
            payload = record.get("payload") if isinstance(record, dict) else None
            if not isinstance(payload, dict):
                continue
            if int(payload.get("mission_generation") or 0) != mission_generation:
                continue
            if str(payload.get("audit_session_id") or "") != audit_session_id:
                continue
            plan_id = str(payload.get("plan_id") or "")
            previous = latest_by_plan.get(plan_id)
            previous_payload = previous.get("payload", {}) if previous else {}
            if previous is None or (
                int(payload.get("attempt_number") or 0),
                str(record.get("recorded_at") or ""),
            ) >= (
                int(previous_payload.get("attempt_number") or 0),
                str(previous.get("recorded_at") or ""),
            ):
                latest_by_plan[plan_id] = record
        records = tuple(latest_by_plan.values())
        signature = tuple(
            (str(record.get("recorded_at") or ""), str((record.get("payload") or {}).get("attempt_id") or ""))
            for record in records
            if isinstance(record, dict) and isinstance(record.get("payload"), dict)
        )
        if signature != self._recon_audit_signature:
            features: list[dict[str, Any]] = []
            source_by_id = {
                str(feature.get("properties", {}).get("object_id") or ""): feature
                for feature in geojson.get("features", [])
                if isinstance(feature, dict)
            }
            for record in records:
                payload = record.get("payload") if isinstance(record, dict) else None
                if not isinstance(payload, dict):
                    continue
                execution = execution_from_dict(payload)
                coalition = str(execution.plan_snapshot.get("coalition") or "unknown").lower()
                for mission in execution.missions:
                    outcome = mission.recon_outcome
                    spatial = outcome.spatial_coverage if outcome else None
                    if outcome is None or spatial is None or not spatial.available or not mission.recon_tracks:
                        continue
                    area = self._recon_area(picture, spatial.area_object_id)
                    if area is None or not spatial.sensor_ranges_m:
                        continue
                    footprints = build_recon_coverage_footprints(
                        area,
                        {group_id: tuple(samples) for group_id, samples in mission.recon_tracks.items()},
                        spatial.sensor_ranges_m,
                    )
                    common = {
                        "layer": "recon_coverage",
                        "plan_id": execution.plan_id,
                        "attempt_id": execution.attempt_id,
                        "auftrag_id": outcome.auftrag_id,
                        "coalition": coalition,
                        "area_object_id": spatial.area_object_id,
                        "area_coverage_ratio": spatial.area_coverage_ratio,
                        "component_coverage_ratio": spatial.component_coverage_ratio,
                        "sufficient": spatial.sufficient,
                        "interpretation": "Potential sensor access, not confirmed detection",
                    }
                    aggregate = await self._coverage_polygon_features(
                        bridge,
                        footprints.aggregate,
                        {
                            **common,
                            "map_category": "aggregate",
                            "object_id": f"RECON_COVERAGE:{execution.attempt_id}:{outcome.auftrag_id}",
                            "name": f"{outcome.auftrag_id} search coverage",
                            "object_type": "RECON_COVERAGE",
                            "category": "Aggregate search footprint",
                            "sample_count": spatial.sample_count,
                        },
                    )
                    features.extend(aggregate)
                    for group_id, polygons in footprints.by_group.items():
                        features.extend(await self._coverage_polygon_features(
                            bridge,
                            polygons,
                            {
                                **common,
                                "map_category": "assets",
                                "object_id": f"RECON_ASSET_COVERAGE:{execution.attempt_id}:{outcome.auftrag_id}:{group_id}",
                                "name": f"{group_id} sensor access",
                                "object_type": "RECON_ASSET_COVERAGE",
                                "category": "Asset search footprint",
                                "group_id": group_id,
                                "sensor_range_m": spatial.sensor_ranges_m.get(group_id),
                                "track_sample_count": len(mission.recon_tracks.get(group_id, ())),
                            },
                        ))
                    for covered, object_ids in (
                        (True, spatial.covered_component_ids),
                        (False, spatial.uncovered_component_ids),
                    ):
                        for object_id in object_ids:
                            source = source_by_id.get(object_id)
                            if not source or source.get("geometry", {}).get("type") != "Point":
                                continue
                            features.append({
                                "type": "Feature",
                                "geometry": source["geometry"],
                                "properties": {
                                    **common,
                                    "map_category": "covered" if covered else "uncovered",
                                    "object_id": f"RECON_COMPONENT:{execution.attempt_id}:{outcome.auftrag_id}:{object_id}",
                                    "name": str(source.get("properties", {}).get("name") or object_id),
                                    "object_type": "RECON_COVERAGE_POINT",
                                    "category": "Covered objective component" if covered else "Uncovered objective component",
                                    "component_object_id": object_id,
                                    "covered": covered,
                                },
                            })
            self._recon_features = features
            self._recon_audit_signature = signature
            self._recon_error = None
        geojson.setdefault("features", []).extend(self._recon_features)
        geojson.setdefault("properties", {})["recon_coverage_count"] = len(self._recon_features)
        return geojson

    @staticmethod
    def _recon_area(picture: GlobalPicture, object_id: str) -> ReconArea | None:
        zone_payload: dict[str, Any] | None = None
        if object_id.startswith("ZONE:"):
            zone_payload = next((zone for zone in picture.zones if zone.get("object_id") == object_id), None)
        elif object_id.startswith("OPSZONE:"):
            opszone = next((zone for zone in picture.opszones if zone.object_id == object_id), None)
            if opszone and opszone.zone_name:
                zone_payload = next(
                    (zone for zone in picture.zones if zone.get("object_id") == f"ZONE:{opszone.zone_name}"),
                    None,
                )
            if zone_payload is None and opszone is not None:
                return ReconArea(object_id, opszone.x, opszone.z, opszone.zone_radius)
        if zone_payload is None:
            return None
        vertices = tuple(
            (float(vertex["x"]), float(vertex["z"]))
            for vertex in zone_payload.get("vertices", ())
            if isinstance(vertex, dict) and vertex.get("x") is not None and vertex.get("z") is not None
        )
        return ReconArea(
            object_id,
            _number(zone_payload.get("x")),
            _number(zone_payload.get("z")),
            _number(zone_payload.get("radius")),
            vertices,
        )

    @staticmethod
    async def _coverage_polygon_features(
        bridge: Any,
        polygons: tuple[tuple[tuple[float, float], ...], ...],
        properties: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not polygons:
            return []
        flat = [point for polygon in polygons for point in polygon]
        converted = []
        for offset in range(0, len(flat), 5000):
            converted.extend(await bridge.convert_points(flat[offset:offset + 5000]))
        result: list[dict[str, Any]] = []
        cursor = 0
        for index, polygon in enumerate(polygons, start=1):
            count = len(polygon)
            ring = [[point.longitude, point.latitude] for point in converted[cursor:cursor + count]]
            cursor += count
            if len(ring) < 4:
                continue
            feature_properties = dict(properties)
            if len(polygons) > 1:
                feature_properties["object_id"] = f"{properties['object_id']}:{index}"
                feature_properties["polygon_part"] = index
            result.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": feature_properties,
            })
        return result

    @staticmethod
    def _add_influence_properties(
        geojson: dict[str, Any],
        group_influences: dict[str, GroupInfluence],
    ) -> None:
        """Expose separated group influence values in map feature details."""

        for feature in geojson.get("features", []):
            properties = feature.get("properties") if isinstance(feature, dict) else None
            if not isinstance(properties, dict) or properties.get("layer") != "groups":
                continue
            profile = group_influences.get(str(properties.get("object_id") or ""))
            if profile is None:
                continue
            values = {
                influence.kind.value: {
                    "effective_power": round(influence.effective_power, 4),
                    "ammo_readiness": round(influence.ammo_readiness, 4),
                    "health_readiness": round(influence.health_readiness, 4),
                    "minimum_range_m": round(influence.minimum_range_m, 3),
                    "maximum_range_m": round(influence.maximum_range_m, 3),
                    "roles": [role.value for role in influence.contributing_roles],
                }
                for influence in profile.influences
            }
            properties["influence"] = values
            properties["control_power"] = values.get("control", {}).get("effective_power", 0.0)

    @staticmethod
    def _incursion_geojson_features(
        classification: FrontlineForceClassification,
        geojson: dict[str, Any],
    ) -> list[dict[str, Any]]:
        source_by_id = {
            str(feature.get("properties", {}).get("object_id") or ""): feature
            for feature in geojson.get("features", [])
            if isinstance(feature, dict)
        }
        features: list[dict[str, Any]] = []
        for incursion in classification.incursions:
            source = source_by_id.get(incursion.force.object_id)
            geometry = source.get("geometry") if isinstance(source, dict) else None
            if not isinstance(geometry, dict) or geometry.get("type") != "Point":
                continue
            source_properties = source.get("properties") if isinstance(source.get("properties"), dict) else {}
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "layer": "incursions",
                        "object_id": f"INCURSION:{incursion.force.object_id}",
                        "name": f"Incursion: {incursion.force.label or incursion.force.object_id}",
                        "object_type": "INCURSION",
                        "category": "Ground incursion",
                        "coalition": incursion.force.coalition,
                        "alive": True,
                        "source_group_id": incursion.force.object_id,
                        "territory_id": incursion.territory_id,
                        "territory_name": incursion.territory_name,
                        "territory_coalition": incursion.territory_coalition,
                        "connected_force_count": incursion.connected_force_count,
                        "nearest_external_support_m": incursion.nearest_external_support_m,
                        "x": incursion.force.x,
                        "z": incursion.force.z,
                        "latitude": source_properties.get("latitude"),
                        "longitude": source_properties.get("longitude"),
                        "coordinate_system": "WGS84",
                    },
                }
            )
        return features

    @staticmethod
    async def _frontline_geojson_features(
        result: FrontlineResult,
        bridge: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tagged_segments = [
            *((segment, "frontlines", "Frontline") for segment in result.segments),
            *((segment, "pressure_frontlines", "Pressure line") for segment in result.pressure_segments),
        ]
        points = [point for segment, _, _ in tagged_segments for point in segment.points]
        converted = await bridge.convert_points(points) if points else []
        frontline_features: list[dict[str, Any]] = []
        pressure_features: list[dict[str, Any]] = []
        cursor = 0
        for segment, layer, label in tagged_segments:
            segment_points = converted[cursor : cursor + len(segment.points)]
            cursor += len(segment.points)
            coordinates = [[point.longitude, point.latitude] for point in segment_points]
            if len(coordinates) < 2:
                continue
            target = frontline_features if layer == "frontlines" else pressure_features
            target.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "properties": {
                        "layer": layer,
                        "object_id": f"{'FRONTLINE' if layer == 'frontlines' else 'PRESSURE_FRONTLINE'}:{segment.index}",
                        "name": f"{label} {segment.index}",
                        "object_type": "FRONTLINE" if layer == "frontlines" else "PRESSURE_FRONTLINE",
                        "category": "Territorial frontline" if layer == "frontlines" else "Force pressure balance",
                        "length_m": segment.length_m,
                        "force_count": result.diagnostics.get("included_force_count", 0),
                        "blue_force_count": result.diagnostics.get("blue_force_count", 0),
                        "red_force_count": result.diagnostics.get("red_force_count", 0),
                        "calculation_ms": result.elapsed_ms,
                        "coordinate_system": "WGS84",
                    },
                }
            )
        return frontline_features, pressure_features

    @staticmethod
    def _add_movement_properties(properties: dict[str, Any], history: deque[TrackPoint], mission_time: float) -> None:
        properties["last_update_mission_time"] = mission_time
        properties["track_sample_count"] = len(history)
        if len(history) < 2:
            return
        previous, current = history[-2], history[-1]
        elapsed = current.mission_time - previous.mission_time
        distance = _distance_m(previous, current)
        speed_mps = distance / elapsed if elapsed > 0 else 0.0
        properties["derived_speed_mps"] = speed_mps
        properties["derived_speed_kts"] = speed_mps * 1.9438444924406
        heading = _heading_deg(previous, current)
        if heading is not None:
            properties["derived_heading_deg"] = heading
        properties["track_distance_m"] = sum(_distance_m(first, second) for first, second in zip(history, list(history)[1:]))
        properties["track_duration_s"] = max(0.0, history[-1].mission_time - history[0].mission_time)

    def _trajectory_features(self, object_features: list[dict[str, Any]]) -> list[dict[str, Any]]:
        features_by_id = {str(feature.get("properties", {}).get("object_id") or ""): feature for feature in object_features}
        trajectories: list[dict[str, Any]] = []
        for object_id, history in self.tracks.items():
            if len(history) < 2:
                continue
            coordinates: list[list[float]] = []
            for point in history:
                coordinate = [point.longitude, point.latitude]
                if not coordinates or coordinate != coordinates[-1]:
                    coordinates.append(coordinate)
            if len(coordinates) < 2:
                continue
            source = features_by_id.get(object_id)
            if source is None:
                continue
            source_properties = source.get("properties", {})
            trajectories.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "properties": {
                        "layer": "trajectories",
                        "object_id": f"TRAJECTORY:{object_id}",
                        "tracked_object_id": object_id,
                        "name": source_properties.get("name") or object_id,
                        "object_type": "TRAJECTORY",
                        "category": source_properties.get("category"),
                        "coalition": source_properties.get("coalition"),
                        "alive": source_properties.get("alive"),
                        "source_layer": source_properties.get("layer"),
                        "sample_count": len(history),
                        "distance_m": source_properties.get("track_distance_m", 0.0),
                        "duration_s": source_properties.get("track_duration_s", 0.0),
                        "average_speed_mps": (
                            source_properties.get("track_distance_m", 0.0) / source_properties.get("track_duration_s", 1.0)
                            if source_properties.get("track_duration_s", 0.0) > 0
                            else 0.0
                        ),
                    },
                }
            )
        return trajectories

    async def start(self) -> None:
        """Start the periodic refresh task."""

        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="moosebridge-global-map")

    async def stop(self) -> None:
        """Stop the periodic refresh task."""

        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._bridge = None

    async def _run(self) -> None:
        control = MooseBridgeControlClient(
            self.control_host,
            self.control_port,
            client_id="moosebridge-map-server",
            display_name="MooseBridge Map Server",
        )
        bridge = sdk_from_control_client(control, timeout=self.timeout)
        self._bridge = bridge
        while True:
            try:
                status = await control.status(timeout=self.timeout)
                generation = int(status.get("mission_generation") or 0)
                if generation != self._mission_generation:
                    self.reset_mission(generation)
                if not status.get("connected"):
                    raise ConnectionError("DCS is not connected to the MooseBridge daemon")
                picture = await bridge.refresh_global_picture()
                self.update_strategic_objectives(picture, bridge)
                geojson = picture.to_geojson()
                self.annotate_strategic_goals(geojson, bridge)
                geojson.setdefault("properties", {})["strategic_objective_error"] = self._strategic_objective_error
                await bridge.refresh_diplomacy_state()
                event_history = await control.query_events(
                    "*",
                    after_id=self._diplomacy_event_cursor,
                    timeout=self.timeout,
                )
                events = event_history.get("events") if isinstance(event_history.get("events"), list) else []
                incident_count = bridge.apply_diplomacy_events(
                    event for event in events if isinstance(event, dict)
                )
                self._diplomacy_event_cursor = (
                    str(event_history.get("latest_event_id") or "") or self._diplomacy_event_cursor
                )
                border_incidents = bridge.sync_border_violations()
                border_signature = bridge.border_violations.active_violations
                border_state_changed = border_signature != self._border_violation_signature
                self._border_violation_signature = border_signature
                if incident_count or border_incidents or border_state_changed:
                    await bridge.persist_diplomacy_state()
                geojson.setdefault("properties", {})["diplomacy"] = bridge.diplomacy_status()
                try:
                    geojson = await self.update_frontline(picture, geojson, bridge)
                except Exception as exc:
                    frontline_error = str(exc)
                    if frontline_error != self._frontline_error:
                        LOGGER.warning("Frontline update failed: %s", exc)
                    else:
                        LOGGER.debug("Frontline update still unavailable: %s", exc)
                    self._frontline_error = frontline_error
                    self._frontline_features = []
                    self._pressure_frontline_features = []
                    self._incursion_features = []
                    geojson["properties"]["frontline_count"] = 0
                    geojson["properties"]["pressure_line_count"] = 0
                    geojson["properties"]["incursion_count"] = 0
                    geojson["properties"]["frontline_error"] = self._frontline_error
                try:
                    geojson = await self.update_recon_coverage(picture, geojson, bridge)
                except Exception as exc:
                    recon_error = str(exc)
                    if recon_error != self._recon_error:
                        LOGGER.warning("RECON coverage update failed: %s", exc)
                    else:
                        LOGGER.debug("RECON coverage still unavailable: %s", exc)
                    self._recon_error = recon_error
                    geojson["properties"]["recon_coverage_count"] = 0
                    geojson["properties"]["recon_coverage_error"] = recon_error
                self.update_picture(geojson)
                if not self.connected:
                    LOGGER.info("Global map connected to DCS")
                self.connected = True
                self.error = None
                await self._broadcast({"type": "picture", "data": self.picture, "status": self.status_payload()})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = str(exc)
                if error != self.error:
                    LOGGER.warning("Global map refresh failed: %s", error)
                else:
                    LOGGER.debug("Global map refresh still unavailable: %s", error)
                self.connected = False
                self.error = error
                await self._broadcast({"type": "status", "status": self.status_payload()})
            await asyncio.sleep(self.interval)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in tuple(self.clients):
            try:
                await client.send_json(message)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


def create_app(
    *,
    control_host: str = "127.0.0.1",
    control_port: int = DEFAULT_CONTROL_PORT,
    interval: float = DEFAULT_UPDATE_INTERVAL,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
    history_seconds: float = DEFAULT_HISTORY_SECONDS,
    history_max_points: int = DEFAULT_HISTORY_MAX_POINTS,
    frontline_interval: float = DEFAULT_FRONTLINE_INTERVAL,
    ammunition_interval: float = DEFAULT_AMMUNITION_INTERVAL,
    frontline_position_alpha: float = DEFAULT_FRONTLINE_POSITION_ALPHA,
    force_anchor_sigma_m: float = DEFAULT_FORCE_ANCHOR_SIGMA_M,
    force_anchor_margin_ratio: float = DEFAULT_FORCE_ANCHOR_MARGIN_RATIO,
    territory_control_ratio: float = DEFAULT_TERRITORY_CONTROL_RATIO,
    territory_transition_m: float = DEFAULT_TERRITORY_TRANSITION_M,
    pressure_territory_ratio: float = DEFAULT_PRESSURE_TERRITORY_RATIO,
    incursion_support_radius_m: float = DEFAULT_INCURSION_SUPPORT_RADIUS_M,
    lodgement_min_forces: int = DEFAULT_LODGEMENT_MIN_FORCES,
    theater_id: str | None = None,
    topography_path: Path | None = DEFAULT_TOPOGRAPHY_PATH,
    max_topography_bytes: int = DEFAULT_MAX_TOPOGRAPHY_BYTES,
    topography_viewport_path: Path | None = DEFAULT_TOPOGRAPHY_VIEWPORT_PATH,
    surface_regions_path: Path | None = DEFAULT_SURFACE_REGIONS_PATH,
    transport_infrastructure_path: Path | None = DEFAULT_TRANSPORT_INFRASTRUCTURE_PATH,
    railway_infrastructure_path: Path | None = DEFAULT_RAILWAY_INFRASTRUCTURE_PATH,
    infrastructure_sites_path: Path | None = DEFAULT_INFRASTRUCTURE_SITES_PATH,
    settlements_path: Path | None = DEFAULT_SETTLEMENTS_PATH,
    strategic_verifications_path: Path | None = DEFAULT_STRATEGIC_VERIFICATIONS_PATH,
) -> FastAPI:
    """Create the FastAPI map application."""

    runtime = GlobalMapRuntime(
        control_host=control_host,
        control_port=control_port,
        interval=interval,
        timeout=timeout,
        history_seconds=history_seconds,
        history_max_points=history_max_points,
        frontline_interval=frontline_interval,
        ammunition_interval=ammunition_interval,
        frontline_position_alpha=frontline_position_alpha,
        force_anchor_sigma_m=force_anchor_sigma_m,
        force_anchor_margin_ratio=force_anchor_margin_ratio,
        territory_control_ratio=territory_control_ratio,
        territory_transition_m=territory_transition_m,
        pressure_territory_ratio=pressure_territory_ratio,
        incursion_support_radius_m=incursion_support_radius_m,
        lodgement_min_forces=lodgement_min_forces,
        theater_id=theater_id,
        topography_path=topography_path,
        max_topography_bytes=max_topography_bytes,
        topography_viewport_path=topography_viewport_path,
        surface_regions_path=surface_regions_path,
        transport_infrastructure_path=transport_infrastructure_path,
        railway_infrastructure_path=railway_infrastructure_path,
        infrastructure_sites_path=infrastructure_sites_path,
        settlements_path=settlements_path,
        strategic_verifications_path=strategic_verifications_path,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="MooseBridge Global Map", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.state.runtime = runtime
    # GDAL/FlatGeobuf reads become dramatically slower when many MapLibre tile
    # requests hit the same large shards concurrently. A single worker keeps
    # generation predictable; completed tiles remain covered by both caches.
    topography_tile_semaphore = asyncio.Semaphore(1)
    app.state.topography_tile_concurrency = 1

    @app.middleware("http")
    async def revalidate_map_ui(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/assets", StaticFiles(directory=MAP_UI_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(MAP_UI_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return runtime.status_payload()

    @app.get("/api/picture/global.geojson")
    async def global_picture() -> dict[str, Any]:
        return runtime.picture

    @app.post("/api/strategic-goals")
    async def create_strategic_goal(payload: dict[str, Any]) -> dict[str, Any]:
        objective_id = str(payload.get("objective_id") or "").strip()
        coalition = str(payload.get("coalition") or "").strip().lower()
        if not objective_id:
            raise HTTPException(status_code=400, detail="objective_id is required")
        if coalition not in {"blue", "red"}:
            raise HTTPException(status_code=400, detail="coalition must be blue or red")
        try:
            goal = runtime.create_strategic_goal(objective_id, coalition)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        await runtime._broadcast({"type": "picture", "data": runtime.picture, "status": runtime.status_payload()})
        return {"ok": True, "goal": goal}

    @app.post("/api/dcs-markers")
    async def create_dcs_marker(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            marker = await runtime.create_dcs_marker(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True, "marker": marker}

    @app.get("/api/strategic-verifications")
    async def strategic_verifications() -> dict[str, Any]:
        return runtime.strategic_verifications_payload()

    @app.put("/api/strategic-verifications/{source_id:path}")
    async def save_strategic_verification(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            verification = runtime.save_strategic_verification({**payload, "source_id": source_id})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "verification": verification.to_dict(),
            "admitted": verification.admitted,
        }

    @app.post("/api/strategic-verifications/{source_id:path}/assess")
    async def assess_strategic_verification(source_id: str) -> dict[str, Any]:
        try:
            assessment = await runtime.assess_strategic_verification(source_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True, "assessment": assessment}

    @app.get("/api/topography/global.geojson")
    async def global_topography() -> dict[str, Any]:
        return runtime.topography_geojson()

    @app.get("/api/topography/viewport.geojson")
    async def viewport_topography(
        west: float,
        south: float,
        east: float,
        north: float,
        zoom: float,
        layers: str = "",
        limit: int = DEFAULT_VIEWPORT_FEATURE_LIMIT,
    ) -> dict[str, Any]:
        selected_layers = [value for value in layers.split(",") if value] or None
        try:
            return await run_in_threadpool(
                runtime.topography_viewport_geojson,
                (west, south, east, north),
                zoom=zoom,
                layers=selected_layers,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/topography/tiles/{layer}/{zoom}/{x}/{y}.pbf")
    async def topography_vector_tile(layer: str, zoom: int, x: int, y: int) -> Response:
        try:
            async with topography_tile_semaphore:
                payload, diagnostics = await run_in_threadpool(runtime.topography_vector_tile, layer, zoom, x, y)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=payload,
            media_type="application/vnd.mapbox-vector-tile",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Feature-Count": str(diagnostics.get("feature_count", 0)),
                "X-Source-Truncated": str(bool(diagnostics.get("truncated"))).lower(),
            },
        )

    @app.get("/api/surface-regions/global.geojson")
    async def global_surface_regions() -> dict[str, Any]:
        return runtime.surface_regions_geojson()

    @app.get("/api/transport-infrastructure/global.geojson")
    async def global_transport_infrastructure(
        west: float | None = None,
        south: float | None = None,
        east: float | None = None,
        north: float | None = None,
        minimum_tier: str | None = None,
    ) -> dict[str, Any]:
        coordinates = (west, south, east, north)
        if any(value is not None for value in coordinates) and not all(value is not None for value in coordinates):
            raise HTTPException(status_code=400, detail="transport bounds require west, south, east, and north")
        bounds = None if west is None else (west, south, east, north)
        assert bounds is None or all(value is not None for value in bounds)
        try:
            return runtime.transport_infrastructure_geojson(
                bounds=bounds,  # type: ignore[arg-type]
                minimum_importance_tier=minimum_tier,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/railway-infrastructure/global.geojson")
    async def global_railway_infrastructure() -> dict[str, Any]:
        return runtime.railway_infrastructure_geojson()

    @app.get("/api/infrastructure-sites/global.geojson")
    async def global_infrastructure_sites() -> dict[str, Any]:
        return runtime.infrastructure_sites_geojson()

    @app.get("/api/settlements/global.geojson")
    async def settlements() -> dict[str, Any]:
        return runtime.settlements_geojson()

    @app.websocket("/ws/global")
    async def global_updates(websocket: WebSocket) -> None:
        await websocket.accept()
        runtime.clients.add(websocket)
        await websocket.send_json({"type": "picture", "data": runtime.picture, "status": runtime.status_payload()})
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            runtime.clients.discard(websocket)

    return app


def main() -> None:
    """Run the global map service."""

    parser = argparse.ArgumentParser(description="Live browser map for the MooseBridge global picture")
    parser.add_argument("--host", default=DEFAULT_MAP_HOST, help="HTTP interface to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_MAP_PORT, help="HTTP port.")
    parser.add_argument("--control-host", default="127.0.0.1", help="MooseBridge control API host.")
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT, help="MooseBridge control API port.")
    parser.add_argument("--interval", type=float, default=DEFAULT_UPDATE_INTERVAL, help="Picture refresh interval in seconds.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_COMMAND_TIMEOUT, help="DCS command timeout in seconds.")
    parser.add_argument("--history-seconds", type=float, default=DEFAULT_HISTORY_SECONDS, help="Trajectory history duration in mission seconds.")
    parser.add_argument("--history-max-points", type=int, default=DEFAULT_HISTORY_MAX_POINTS, help="Maximum trajectory samples per object.")
    parser.add_argument("--frontline-interval", type=float, default=DEFAULT_FRONTLINE_INTERVAL, help="Frontline recalculation interval in mission seconds.")
    parser.add_argument("--ammunition-interval", type=float, default=DEFAULT_AMMUNITION_INTERVAL, help="Ammunition and influence refresh interval in mission seconds.")
    parser.add_argument("--frontline-position-alpha", type=float, default=DEFAULT_FRONTLINE_POSITION_ALPHA, help="Frontline force-position smoothing factor.")
    parser.add_argument("--force-anchor-sigma", type=float, default=DEFAULT_FORCE_ANCHOR_SIGMA_M, help="Local force-anchor radius scale in meters.")
    parser.add_argument("--force-anchor-margin", type=float, default=DEFAULT_FORCE_ANCHOR_MARGIN_RATIO, help="Required own-coalition advantage at a force position.")
    parser.add_argument("--territory-control-ratio", type=float, default=DEFAULT_TERRITORY_CONTROL_RATIO, help="Territorial ownership strength relative to peak force pressure.")
    parser.add_argument("--territory-transition", type=float, default=DEFAULT_TERRITORY_TRANSITION_M, help="Distance scale for territorial control transition in meters.")
    parser.add_argument("--pressure-territory-ratio", type=float, default=DEFAULT_PRESSURE_TERRITORY_RATIO, help="Weak territory prior used by the force pressure line.")
    parser.add_argument("--incursion-support-radius", type=float, default=DEFAULT_INCURSION_SUPPORT_RADIUS_M, help="Ground-force connection radius in meters.")
    parser.add_argument("--lodgement-min-forces", type=int, default=DEFAULT_LODGEMENT_MIN_FORCES, help="Connected hostile groups required to establish a lodgement.")
    parser.add_argument(
        "--theater-profile",
        type=Path,
        default=DEFAULT_THEATER_PROFILE_PATH,
        help="Theater profile defining source policy and default artifact paths.",
    )
    parser.add_argument("--topography", type=Path, default=None, help="Override the profile's static topography cache.")
    parser.add_argument(
        "--max-topography-mb",
        type=float,
        default=DEFAULT_MAX_TOPOGRAPHY_BYTES / (1024 * 1024),
        help="Maximum static GeoJSON size loaded into memory; zero disables the guard.",
    )
    parser.add_argument(
        "--topography-viewport",
        type=Path,
        default=None,
        help="Indexed topography viewport manifest.",
    )
    parser.add_argument(
        "--surface-regions",
        type=Path,
        default=None,
        help="Connected static land/water surface-region GeoJSON cache.",
    )
    parser.add_argument(
        "--transport-infrastructure",
        type=Path,
        default=None,
        help="Static strategic bridge and road-junction GeoJSON cache.",
    )
    parser.add_argument(
        "--railway-infrastructure",
        type=Path,
        default=None,
        help="Aggregated static railway-infrastructure GeoJSON cache.",
    )
    parser.add_argument(
        "--infrastructure-sites",
        type=Path,
        default=None,
        help="Normalized static infrastructure-site GeoJSON cache.",
    )
    parser.add_argument(
        "--settlements",
        type=Path,
        default=None,
        help="Normalized city and town GeoJSON cache.",
    )
    parser.add_argument(
        "--strategic-verifications",
        type=Path,
        default=None,
        help="Scenario-specific DCS component verification JSON file.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    profile, theater_paths = load_theater_profile(args.theater_profile, project_root=Path.cwd())

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Map dependencies are missing. Run: python -m pip install -e ".[map]"') from exc

    app = create_app(
        control_host=args.control_host,
        control_port=args.control_port,
        interval=max(0.5, args.interval),
        timeout=max(1.0, args.timeout),
        history_seconds=max(0.0, args.history_seconds),
        history_max_points=max(2, args.history_max_points),
        frontline_interval=max(1.0, args.frontline_interval),
        ammunition_interval=max(1.0, args.ammunition_interval),
        frontline_position_alpha=min(1.0, max(0.01, args.frontline_position_alpha)),
        force_anchor_sigma_m=max(0.0, args.force_anchor_sigma),
        force_anchor_margin_ratio=min(0.99, max(0.0, args.force_anchor_margin)),
        territory_control_ratio=max(0.0, args.territory_control_ratio),
        territory_transition_m=max(1.0, args.territory_transition),
        pressure_territory_ratio=max(0.0, args.pressure_territory_ratio),
        incursion_support_radius_m=max(1.0, args.incursion_support_radius),
        lodgement_min_forces=max(1, args.lodgement_min_forces),
        theater_id=profile.theater_id,
        topography_path=args.topography or theater_paths.path("topography"),
        max_topography_bytes=max(0, int(args.max_topography_mb * 1024 * 1024)),
        topography_viewport_path=args.topography_viewport or theater_paths.path("viewport_manifest"),
        surface_regions_path=args.surface_regions or theater_paths.path("surface_regions"),
        transport_infrastructure_path=args.transport_infrastructure or theater_paths.path("transport_infrastructure"),
        railway_infrastructure_path=args.railway_infrastructure or theater_paths.path("railway_infrastructure"),
        infrastructure_sites_path=args.infrastructure_sites or theater_paths.path("infrastructure_sites"),
        settlements_path=args.settlements or theater_paths.path("settlements"),
        strategic_verifications_path=args.strategic_verifications or theater_paths.path("strategic_verifications"),
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
