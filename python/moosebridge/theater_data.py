"""Configuration and artifact paths for one DCS theater dataset."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping


THEATER_PROFILE_SCHEMA_VERSION = 1
DEFAULT_THEATER_PROFILE_PATH = Path(__file__).with_name("data") / "GermanyCW_topography.json"


DEFAULT_ARTIFACTS: dict[str, str] = {
    "topography": "{theater_id}.geojson",
    "topography_preview": "{theater_id}-simplified.geojson",
    "coverage": "{theater_id}-coverage.geojson",
    "viewport_manifest": "viewport/manifest.json",
    "surface_source": "{theater_id}-surface-source.geojson",
    "surface_regions": "{theater_id}-surface-regions.geojson",
    "surface_comparison": "{theater_id}-surface-comparison.geojson",
    "road_routing": "{theater_id}-road-routing.npz",
    "road_routing_cache": "road_routing_cache",
    "ground_mobility": "{theater_id}-ground-mobility.json",
    "transport_infrastructure": "{theater_id}-transport-infrastructure.geojson",
    "railway_infrastructure": "{theater_id}-railway-infrastructure.geojson",
    "railway_routing": "{theater_id}-railway-routing.npz",
    "railway_facility_cache": "railway_facility_cache",
    "settlements": "{theater_id}-settlements.geojson",
    "administrative_boundary_cache": "administrative_boundary_cache",
    "infrastructure_sites": "{theater_id}-infrastructure-sites.geojson",
    "strategic_verifications": "{theater_id}-strategic-verifications.json",
    "pbf_directory": "pbf",
    "import_cache": "import_cache",
    "osmcoastline_directory": "osmcoastline",
    "natural_earth_directory": "naturalearth",
}

MAP_ARTIFACT_KEYS = (
    "topography",
    "viewport_manifest",
    "surface_regions",
    "transport_infrastructure",
    "railway_infrastructure",
    "infrastructure_sites",
    "settlements",
    "strategic_verifications",
)


@dataclass(slots=True, frozen=True)
class TheaterSource:
    """One external source used to construct a theater dataset."""

    source_id: str
    url: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TheaterSource":
        source_id = str(payload.get("id") or "").strip()
        url = str(payload.get("url") or "").strip()
        if not source_id or not url:
            raise ValueError("theater source requires id and url")
        return cls(source_id=source_id, url=url)


@dataclass(slots=True, frozen=True)
class TheaterDataPaths:
    """Resolved artifact paths belonging to one theater profile."""

    theater_id: str
    root: Path
    artifacts: Mapping[str, str]

    def path(self, key: str) -> Path:
        try:
            relative = self.artifacts[key]
        except KeyError as exc:
            raise KeyError(f"unknown theater artifact: {key}") from exc
        return self.root / relative.format(theater_id=self.theater_id)

    def as_dict(self) -> dict[str, Path]:
        return {key: self.path(key) for key in self.artifacts}


@dataclass(slots=True, frozen=True)
class TheaterDataProfile:
    """Portable definition of source policy and generated theater artifacts."""

    theater_id: str
    scenario_reference_year: int | None = None
    infrastructure_reference_year: int | None = None
    display_name: str | None = None
    pilot_bounds: tuple[float, float, float, float] | None = None
    data_root: str = "tmp/theaters/{theater_id}"
    source_policy: Mapping[str, Any] = field(default_factory=dict)
    excluded_energy_sources: tuple[str, ...] = ()
    geofabrik_sources: tuple[TheaterSource, ...] = ()
    artifacts: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_ARTIFACTS))
    schema_version: int = THEATER_PROFILE_SCHEMA_VERSION
    profile_path: Path | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not self.theater_id.strip():
            raise ValueError("theater profile requires theater_id")
        if self.schema_version != THEATER_PROFILE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported theater profile schema {self.schema_version}; "
                f"expected {THEATER_PROFILE_SCHEMA_VERSION}"
            )
        if self.pilot_bounds is not None:
            south, west, north, east = self.pilot_bounds
            if south >= north or west >= east:
                raise ValueError("pilot_bounds must be SOUTH WEST NORTH EAST")
        missing = sorted(set(DEFAULT_ARTIFACTS).difference(self.artifacts))
        if missing:
            raise ValueError(f"theater profile is missing artifact paths: {', '.join(missing)}")
        for key, value in self.artifacts.items():
            candidate = Path(str(value).format(theater_id=self.theater_id))
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError(f"artifact path must stay below data_root: {key}={value}")

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        profile_path: Path | None = None,
    ) -> "TheaterDataProfile":
        bounds_payload = payload.get("pilot_bounds")
        bounds = None
        if isinstance(bounds_payload, Mapping):
            bounds = tuple(
                float(bounds_payload[key]) for key in ("south", "west", "north", "east")
            )
        artifacts = dict(DEFAULT_ARTIFACTS)
        artifacts.update({str(key): str(value) for key, value in (payload.get("artifacts") or {}).items()})
        return cls(
            theater_id=str(payload.get("theater_id") or ""),
            scenario_reference_year=_optional_int(payload.get("scenario_reference_year")),
            infrastructure_reference_year=_optional_int(
                payload.get("infrastructure_reference_year", payload.get("scenario_reference_year"))
            ),
            display_name=str(payload.get("display_name") or "") or None,
            pilot_bounds=bounds,  # type: ignore[arg-type]
            data_root=str(payload.get("data_root") or "tmp/theaters/{theater_id}"),
            source_policy=dict(payload.get("source_policy") or {}),
            excluded_energy_sources=tuple(str(item) for item in payload.get("excluded_energy_sources") or ()),
            geofabrik_sources=tuple(
                TheaterSource.from_dict(item) for item in payload.get("geofabrik_sources") or ()
            ),
            artifacts=artifacts,
            schema_version=int(payload.get("schema_version") or THEATER_PROFILE_SCHEMA_VERSION),
            profile_path=profile_path,
        )

    @classmethod
    def load(cls, path: str | Path = DEFAULT_THEATER_PROFILE_PATH) -> "TheaterDataProfile":
        profile_path = Path(path).resolve()
        with profile_path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("theater profile must be a JSON object")
        return cls.from_dict(payload, profile_path=profile_path)

    def paths(self, *, project_root: str | Path | None = None) -> TheaterDataPaths:
        root = Path(self.data_root.format(theater_id=self.theater_id))
        if not root.is_absolute():
            root = Path(project_root or Path.cwd()) / root
        return TheaterDataPaths(
            theater_id=self.theater_id,
            root=root.resolve(),
            artifacts=self.artifacts,
        )


def load_theater_profile(
    path: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> tuple[TheaterDataProfile, TheaterDataPaths]:
    """Load one profile and resolve all paths against the project root."""

    profile = TheaterDataProfile.load(path or DEFAULT_THEATER_PROFILE_PATH)
    return profile, profile.paths(project_root=project_root)


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
