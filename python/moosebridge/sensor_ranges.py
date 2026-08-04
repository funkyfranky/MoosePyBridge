"""Optimistic sensor detection bounds keyed by DCS unit type."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable

from .datamine_sensors import DEFAULT_DATAMINE_SENSOR_DATA, DatamineSensorData


class SensorDetectionType(str, Enum):
    """Organic DCS detection mechanisms represented by range profiles."""

    ORGANIC = "organic"
    VISUAL = "visual"
    OPTIC = "optic"
    RADAR = "radar"
    IRST = "irst"
    RWR = "rwr"


class SensorTargetDomain(str, Enum):
    """Target domain to which a sensor bound applies."""

    ANY = "any"
    AIR = "air"
    SURFACE = "surface"


class SensorPlatformCategory(str, Enum):
    """DCS platform category carrying the sensor."""

    GROUND = "ground"
    AIRPLANE = "airplane"
    HELICOPTER = "helicopter"


class SensorRangeScope(str, Enum):
    """Whether a bound covers one sensor or every organic sensor on a unit."""

    SENSOR = "sensor"
    UNIT = "unit"


class SensorRangeSource(str, Enum):
    """Origin of a sensor detection bound."""

    MANUAL = "manual"
    DCS_DATAMINE_UNIT = "dcs_datamine_unit"
    DCS_DATAMINE_SENSOR = "dcs_datamine_sensor"


@dataclass(slots=True, frozen=True)
class SensorRangeProfile:
    """Known range information for one organic sensor mechanism.

    A numeric, exclusion-safe value is an optimistic upper bound. A target
    beyond it is excluded for this scope; a target inside it is only
    potentially detectable. ``None`` preserves a sensor whose range is not
    published by DCS.
    """

    dcs_type: str
    platform_category: SensorPlatformCategory
    detection_type: SensorDetectionType
    target_domain: SensorTargetDomain
    maximum_m: float | None
    source: SensorRangeSource
    mode: str | None = None
    hard_limit_m: float | None = None
    reference_rcs_m2: float | None = None
    scan_period_s: float | None = None
    scan_azimuth_deg: tuple[float, float] | None = None
    scan_elevation_deg: tuple[float, float] | None = None
    range_scope: SensorRangeScope = SensorRangeScope.SENSOR
    exclusion_safe: bool = False
    emitter_only: bool = False
    sensor_names: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    basis: str | None = None

    def __post_init__(self) -> None:
        if not self.dcs_type.strip():
            raise ValueError("dcs_type must not be empty")
        for name, value in (("maximum_m", self.maximum_m), ("hard_limit_m", self.hard_limit_m)):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be a finite, positive number")

    def excludes(self, distance_m: float) -> bool | None:
        """Return whether this profile safely rules out detection at a distance."""

        if not self.exclusion_safe or self.maximum_m is None:
            return None
        return math.isfinite(distance_m) and distance_m > self.maximum_m


MANUAL_SENSOR_RANGE_PROFILES: tuple[SensorRangeProfile, ...] = ()


def _key(
    dcs_type: str,
    detection_type: SensorDetectionType | str,
    target_domain: SensorTargetDomain | str,
    mode: str | None,
) -> tuple[str, SensorDetectionType, SensorTargetDomain, str]:
    return (
        dcs_type.strip().casefold(),
        SensorDetectionType(detection_type),
        SensorTargetDomain(target_domain),
        (mode or "").strip().casefold(),
    )


class SensorRangeRegistry:
    """Resolve versioned and manually overridden sensor detection bounds."""

    def __init__(
        self,
        profiles: Iterable[SensorRangeProfile] = MANUAL_SENSOR_RANGE_PROFILES,
        datamine: DatamineSensorData | None = DEFAULT_DATAMINE_SENSOR_DATA,
    ) -> None:
        self._manual = {_key(item.dcs_type, item.detection_type, item.target_domain, item.mode): item for item in profiles}
        self._datamine: dict[tuple[str, SensorDetectionType, SensorTargetDomain, str], SensorRangeProfile] = {}
        if datamine is not None:
            for item in datamine.profiles:
                key = _key(item.dcs_type, item.detection_type, item.target_domain, item.mode)
                source = (
                    SensorRangeSource.DCS_DATAMINE_UNIT
                    if item.basis == "maxTargetDetectionRange"
                    else SensorRangeSource.DCS_DATAMINE_SENSOR
                )
                previous = self._datamine.get(key)
                candidate = SensorRangeProfile(
                    dcs_type=item.dcs_type,
                    platform_category=SensorPlatformCategory(item.platform_category),
                    detection_type=key[1],
                    target_domain=key[2],
                    maximum_m=item.maximum_m,
                    source=source,
                    mode=item.mode,
                    hard_limit_m=item.hard_limit_m,
                    reference_rcs_m2=item.reference_rcs_m2,
                    scan_period_s=item.scan_period_s,
                    scan_azimuth_deg=item.scan_azimuth_deg,
                    scan_elevation_deg=item.scan_elevation_deg,
                    range_scope=SensorRangeScope(item.range_scope),
                    exclusion_safe=item.exclusion_safe,
                    emitter_only=item.emitter_only,
                    sensor_names=tuple(sorted(set((previous.sensor_names if previous else ()) + item.sensor_names))),
                    source_paths=tuple(sorted(set((previous.source_paths if previous else ()) + item.source_paths))),
                    basis=item.basis,
                )
                self._datamine[key] = candidate
        self.datamine_metadata = datamine.metadata if datamine is not None else None
        resolved = {**self._datamine, **self._manual}
        self._profiles = tuple(
            sorted(
                resolved.values(),
                key=lambda item: (
                    item.dcs_type.casefold(),
                    item.detection_type.value,
                    item.target_domain.value,
                    item.mode or "",
                ),
            )
        )
        self._profiles_by_type: dict[str, tuple[SensorRangeProfile, ...]] = {}
        for dcs_type in {item.dcs_type.casefold() for item in self._profiles}:
            self._profiles_by_type[dcs_type] = tuple(
                item for item in self._profiles if item.dcs_type.casefold() == dcs_type
            )

    @property
    def profiles(self) -> tuple[SensorRangeProfile, ...]:
        """Return exact profiles in deterministic order, with manual overrides applied."""

        return self._profiles

    def profiles_for(
        self,
        dcs_type: str,
        *,
        target_domain: SensorTargetDomain | str | None = None,
    ) -> tuple[SensorRangeProfile, ...]:
        """Return profiles applicable to a unit type and optional target domain."""

        domain = SensorTargetDomain(target_domain) if target_domain is not None else None
        result = [
            item
            for item in self._profiles_by_type.get(dcs_type.strip().casefold(), ())
            if domain is None or item.target_domain in {SensorTargetDomain.ANY, domain}
        ]
        return tuple(result)

    def maximum_range_m(
        self,
        dcs_type: str,
        *,
        target_domain: SensorTargetDomain | str | None = None,
    ) -> float | None:
        """Return the largest applicable upper bound, or ``None`` when unknown."""

        profiles = self.profiles_for(dcs_type, target_domain=target_domain)
        return max((item.maximum_m for item in profiles if item.maximum_m is not None), default=None)

    def excludes(
        self,
        dcs_type: str,
        distance_m: float,
        *,
        target_domain: SensorTargetDomain | str | None = None,
    ) -> bool | None:
        """Return true when a complete unit envelope excludes detection.

        ``None`` means no applicable upper bound is known. ``False`` means only
        that detection remains possible, not that it will occur.
        """

        profiles = tuple(
            item
            for item in self.profiles_for(dcs_type, target_domain=target_domain)
            if item.range_scope is SensorRangeScope.UNIT
        )
        if not profiles or any(not item.exclusion_safe or item.maximum_m is None for item in profiles):
            return None
        maximum = max(item.maximum_m for item in profiles if item.maximum_m is not None)
        return math.isfinite(distance_m) and distance_m > maximum

    def sensor_excludes(
        self,
        dcs_type: str,
        detection_type: SensorDetectionType | str,
        distance_m: float,
        *,
        target_domain: SensorTargetDomain | str | None = None,
        mode: str | None = None,
    ) -> bool | None:
        """Return whether all matching bounded sensors exclude detection."""

        detection = SensorDetectionType(detection_type)
        candidates = tuple(
            item
            for item in self.profiles_for(dcs_type, target_domain=target_domain)
            if item.detection_type is detection
            and (mode is None or (item.mode or "").casefold() == mode.casefold())
        )
        if not candidates or any(not item.exclusion_safe or item.maximum_m is None for item in candidates):
            return None
        return math.isfinite(distance_m) and distance_m > max(
            item.maximum_m for item in candidates if item.maximum_m is not None
        )


DEFAULT_SENSOR_RANGE_REGISTRY = SensorRangeRegistry()


__all__ = [
    "DEFAULT_SENSOR_RANGE_REGISTRY",
    "MANUAL_SENSOR_RANGE_PROFILES",
    "SensorDetectionType",
    "SensorPlatformCategory",
    "SensorRangeProfile",
    "SensorRangeRegistry",
    "SensorRangeScope",
    "SensorRangeSource",
    "SensorTargetDomain",
]
