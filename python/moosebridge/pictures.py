"""Situation-picture models and GeoJSON export helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from .clock import DcsTime
from .legions import Cohort, Legion
from .models import Auftrag, Intel, IntelCluster, IntelContact, OpsGroup, OpsZone


class HasDcsPoint(Protocol):
    """Protocol for snapshot models with DCS x/y/z coordinates."""

    object_id: str
    dcs_name: str
    object_type: str
    category: str | None
    x: float | None
    y: float | None
    z: float | None
    raw: dict[str, Any]


GeoJsonFeature = dict[str, Any]
GeoJsonFeatureCollection = dict[str, Any]


def _clean_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-friendly properties without empty values."""

    return {key: value for key, value in properties.items() if value is not None}


def _point_geometry(x: float | None, z: float | None) -> dict[str, Any] | None:
    """Return GeoJSON point geometry using DCS x/z as planar coordinates."""

    if x is None or z is None:
        return None
    return {"type": "Point", "coordinates": [x, z]}


def _line_geometry(points: Iterable[tuple[float | None, float | None]]) -> dict[str, Any] | None:
    """Return GeoJSON line geometry using DCS x/z as planar coordinates."""

    coordinates = [[x, z] for x, z in points if x is not None and z is not None]
    if len(coordinates) < 2:
        return None
    return {"type": "LineString", "coordinates": coordinates}


def _feature(
    *,
    geometry: dict[str, Any] | None,
    layer: str,
    object_id: str,
    name: str | None = None,
    object_type: str | None = None,
    category: str | None = None,
    properties: dict[str, Any] | None = None,
) -> GeoJsonFeature | None:
    """Build one GeoJSON feature or ``None`` when no geometry is available."""

    if geometry is None:
        return None
    feature_properties = {
        "layer": layer,
        "object_id": object_id,
        "name": name,
        "object_type": object_type,
        "category": category,
        "coordinate_system": "dcs",
    }
    feature_properties.update(properties or {})
    return {"type": "Feature", "geometry": geometry, "properties": _clean_properties(feature_properties)}


def _point_feature(item: HasDcsPoint, layer: str, properties: dict[str, Any] | None = None) -> GeoJsonFeature | None:
    """Build a point feature from a typed snapshot object."""

    return _feature(
        geometry=_point_geometry(_as_float(getattr(item, "x", None)), _as_float(getattr(item, "z", None))),
        layer=layer,
        object_id=str(getattr(item, "object_id", "")),
        name=str(getattr(item, "dcs_name", "") or "") or None,
        object_type=str(getattr(item, "object_type", "") or "") or None,
        category=getattr(item, "category", None),
        properties=properties,
    )


def _raw_point_feature(item: dict[str, Any], layer: str, properties: dict[str, Any] | None = None) -> GeoJsonFeature | None:
    """Build a point feature from a raw snapshot dictionary."""

    return _feature(
        geometry=_point_geometry(_as_float(item.get("x")), _as_float(item.get("z"))),
        layer=layer,
        object_id=str(item.get("object_id") or ""),
        name=str(item.get("dcs_name") or item.get("name") or "") or None,
        object_type=str(item.get("object_type") or "") or None,
        category=str(item.get("category") or "") or None,
        properties=properties or item,
    )


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _feature_collection(features: Iterable[GeoJsonFeature | None], *, scope: str, metadata: dict[str, Any]) -> GeoJsonFeatureCollection:
    """Build a GeoJSON feature collection with MooseBridge metadata."""

    return {
        "type": "FeatureCollection",
        "features": [feature for feature in features if feature is not None],
        "properties": {"scope": scope, "coordinate_system": "dcs", **metadata},
    }


@dataclass(slots=True, frozen=True)
class TacticalPicture:
    """Coalition/INTEL based situation picture.

    Enemy knowledge in this model comes from INTEL contacts and clusters, not
    from global GROUP/UNIT truth snapshots.
    """

    coalition: str
    intel_id: str
    clock: DcsTime | None = None
    intel: Intel | None = None
    contacts: list[IntelContact] = field(default_factory=list)
    clusters: list[IntelCluster] = field(default_factory=list)
    opszones: list[OpsZone] = field(default_factory=list)
    opsgroups: list[OpsGroup] = field(default_factory=list)
    legions: list[Legion] = field(default_factory=list)
    cohorts: list[Cohort] = field(default_factory=list)
    missions: list[Auftrag] = field(default_factory=list)

    def to_geojson(self) -> GeoJsonFeatureCollection:
        """Return a GeoJSON FeatureCollection suitable for a tactical map."""

        features: list[GeoJsonFeature | None] = []
        features.extend(self._zone_features())
        features.extend(self._asset_features())
        features.extend(self._contact_features())
        features.extend(self._cluster_features())
        features.extend(self._mission_features())
        return _feature_collection(
            features,
            scope="tactical",
            metadata={"coalition": self.coalition, "intel_id": self.intel_id, **(self.clock.to_dict() if self.clock else {})},
        )

    def _zone_features(self) -> list[GeoJsonFeature | None]:
        return [
            _point_feature(
                zone,
                "opszones",
                {
                    "state": zone.state,
                    "owner": zone.owner_current_name,
                    "contested": zone.is_contested,
                    "radius_m": zone.zone_radius,
                    "n_red": zone.n_red,
                    "n_blue": zone.n_blue,
                    "threat_red": zone.threat_red,
                    "threat_blue": zone.threat_blue,
                },
            )
            for zone in self.opszones
        ]

    def _asset_features(self) -> list[GeoJsonFeature | None]:
        features: list[GeoJsonFeature | None] = []
        for group in self.opsgroups:
            features.append(
                _point_feature(
                    group,
                    "friendly_opsgroups",
                    {
                        "coalition": group.coalition,
                        "state": group.state,
                        "alive": group.alive,
                        "active": group.active,
                        "auftrag_current_id": group.auftrag_current_id,
                        "auftrag_queue_ids": group.auftrag_queue_ids,
                    },
                )
            )
        for legion in self.legions:
            features.append(
                _point_feature(
                    legion,  # type: ignore[arg-type]
                    "friendly_legions",
                    {
                        "coalition": legion.coalition or legion.coalition_name,
                        "state": legion.state,
                        "airbase_name": legion.airbase_name,
                        "cohort_ids": legion.cohort_ids,
                        "auftrag_queue_ids": legion.auftrag_queue_ids,
                    },
                )
            )
        return features

    def _contact_features(self) -> list[GeoJsonFeature | None]:
        return [
            _point_feature(
                contact,
                "known_enemy_contacts",
                {
                    "intel_id": contact.intel_id,
                    "target_object_id": contact.target_object_id,
                    "contact_type": contact.contact_type,
                    "threat_level": contact.threat_level,
                    "detected_time": contact.detected_time,
                    "recce": contact.recce,
                    "speed_mps": contact.speed_mps,
                    "heading": contact.heading,
                    "altitude_m": contact.altitude_m,
                    "mission_id": contact.mission_id,
                },
            )
            for contact in self.contacts
        ]

    def _cluster_features(self) -> list[GeoJsonFeature | None]:
        return [
            _point_feature(
                cluster,
                "intel_clusters",
                {
                    "intel_id": cluster.intel_id,
                    "index": cluster.index,
                    "size": cluster.size,
                    "contact_ids": cluster.contact_ids,
                    "contact_type": cluster.contact_type,
                    "threat_level_max": cluster.threat_level_max,
                    "threat_level_sum": cluster.threat_level_sum,
                    "threat_level_avg": cluster.threat_level_avg,
                    "altitude_m": cluster.altitude_m,
                    "mission_id": cluster.mission_id,
                },
            )
            for cluster in self.clusters
        ]

    def _mission_features(self) -> list[GeoJsonFeature | None]:
        features: list[GeoJsonFeature | None] = []
        for mission in self.missions:
            target = mission.target
            if target is None:
                continue
            features.append(
                _feature(
                    geometry=_point_geometry(target.x, target.z),
                    layer="missions",
                    object_id=mission.object_id,
                    name=mission.name,
                    object_type="AUFTRAG",
                    category=mission.type,
                    properties={
                        "mission_type": mission.type,
                        "status": mission.status,
                        "assigned_group_ids": mission.assigned_group_ids,
                        "target_name": target.name,
                        "target_object_id": target.object_id,
                    },
                )
            )
        return features


@dataclass(slots=True, frozen=True)
class GlobalPicture:
    """Admin/debug picture based on global truth snapshots."""

    clock: DcsTime | None = None
    groups: list[dict[str, Any]] = field(default_factory=list)
    units: list[dict[str, Any]] = field(default_factory=list)
    statics: list[dict[str, Any]] = field(default_factory=list)
    airbases: list[dict[str, Any]] = field(default_factory=list)
    zones: list[dict[str, Any]] = field(default_factory=list)
    opszones: list[OpsZone] = field(default_factory=list)
    opsgroups: list[OpsGroup] = field(default_factory=list)
    missions: list[Auftrag] = field(default_factory=list)
    legions: list[Legion] = field(default_factory=list)
    cohorts: list[Cohort] = field(default_factory=list)
    intels: list[Intel] = field(default_factory=list)
    intel_contacts: list[IntelContact] = field(default_factory=list)
    intel_clusters: list[IntelCluster] = field(default_factory=list)

    def to_geojson(self) -> GeoJsonFeatureCollection:
        """Return a GeoJSON FeatureCollection suitable for an admin/global map."""

        features: list[GeoJsonFeature | None] = []
        features.extend(_raw_point_feature(item, "groups") for item in self.groups)
        features.extend(_raw_point_feature(item, "units") for item in self.units)
        features.extend(_raw_point_feature(item, "statics") for item in self.statics)
        features.extend(_raw_point_feature(item, "airbases") for item in self.airbases)
        features.extend(_raw_point_feature(item, "zones", {"radius_m": item.get("radius")}) for item in self.zones)
        features.extend(_point_feature(item, "opszones", {"state": item.state, "owner": item.owner_current_name}) for item in self.opszones)
        features.extend(_point_feature(item, "opsgroups", {"coalition": item.coalition, "state": item.state}) for item in self.opsgroups)
        features.extend(_point_feature(item, "legions", {"coalition": item.coalition or item.coalition_name, "state": item.state}) for item in self.legions)  # type: ignore[arg-type]
        features.extend(_point_feature(item, "intel_contacts", {"intel_id": item.intel_id, "threat_level": item.threat_level}) for item in self.intel_contacts)
        features.extend(_point_feature(item, "intel_clusters", {"intel_id": item.intel_id, "size": item.size}) for item in self.intel_clusters)
        features.extend(self._mission_features())
        return _feature_collection(features, scope="global", metadata=self.clock.to_dict() if self.clock else {})

    def _mission_features(self) -> list[GeoJsonFeature | None]:
        features: list[GeoJsonFeature | None] = []
        groups_by_id = {item.object_id: item for item in self.opsgroups}
        for mission in self.missions:
            target = mission.target
            if target is None:
                continue
            features.append(
                _feature(
                    geometry=_point_geometry(target.x, target.z),
                    layer="missions",
                    object_id=mission.object_id,
                    name=mission.name,
                    object_type="AUFTRAG",
                    category=mission.type,
                    properties={"mission_type": mission.type, "status": mission.status, "target_name": target.name},
                )
            )
            for group_id in mission.assigned_group_ids:
                group = groups_by_id.get(group_id)
                geometry = _line_geometry(((group.x if group else None, group.z if group else None), (target.x, target.z)))
                features.append(
                    _feature(
                        geometry=geometry,
                        layer="mission_links",
                        object_id=f"{mission.object_id}->{group_id}",
                        name=mission.name,
                        object_type="MISSION_LINK",
                        category=mission.type,
                        properties={"mission_id": mission.object_id, "opsgroup_id": group_id, "status": mission.status},
                    )
                )
        return features
