"""Situation-picture models and GeoJSON export helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from .clock import DcsTime
from .legions import Cohort, Legion
from .models import Auftrag, Intel, IntelCluster, IntelContact, OpsGroup, OpsZone


class HasGeographicPoint(Protocol):
    """Protocol for snapshot models with DCS and geographic coordinates."""

    object_id: str
    dcs_name: str
    object_type: str
    category: str | None
    x: float | None
    y: float | None
    z: float | None
    latitude: float | None
    longitude: float | None
    raw: dict[str, Any]


GeoJsonFeature = dict[str, Any]
GeoJsonFeatureCollection = dict[str, Any]


@dataclass(slots=True, frozen=True)
class PictureValidationIssue:
    """One consistency issue found in a situation picture."""

    severity: str
    code: str
    message: str
    object_id: str | None = None


def _clean_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-friendly properties without empty values."""

    return {key: value for key, value in properties.items() if value is not None}


def _point_geometry(longitude: float | None, latitude: float | None) -> dict[str, Any] | None:
    """Return a WGS84 GeoJSON point in longitude/latitude order."""

    if longitude is None or latitude is None:
        return None
    return {"type": "Point", "coordinates": [longitude, latitude]}


def _line_geometry(points: Iterable[tuple[float | None, float | None]]) -> dict[str, Any] | None:
    """Return a WGS84 GeoJSON line in longitude/latitude order."""

    coordinates = [[longitude, latitude] for longitude, latitude in points if longitude is not None and latitude is not None]
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
        "coordinate_system": "WGS84",
    }
    feature_properties.update(properties or {})
    return {"type": "Feature", "geometry": geometry, "properties": _clean_properties(feature_properties)}


def _point_feature(item: HasGeographicPoint, layer: str, properties: dict[str, Any] | None = None) -> GeoJsonFeature | None:
    """Build a point feature from a typed snapshot object."""

    feature_properties = {
        "x": _as_float(getattr(item, "x", None)),
        "y": _as_float(getattr(item, "y", None)),
        "z": _as_float(getattr(item, "z", None)),
    }
    feature_properties.update(properties or {})
    return _feature(
        geometry=_point_geometry(
            _as_float(getattr(item, "longitude", None)), _as_float(getattr(item, "latitude", None))
        ),
        layer=layer,
        object_id=str(getattr(item, "object_id", "")),
        name=str(getattr(item, "dcs_name", "") or "") or None,
        object_type=str(getattr(item, "object_type", "") or "") or None,
        category=getattr(item, "category", None),
        properties=feature_properties,
    )


def _raw_point_feature(item: dict[str, Any], layer: str, properties: dict[str, Any] | None = None) -> GeoJsonFeature | None:
    """Build a point feature from a raw snapshot dictionary."""

    feature_properties = dict(item)
    feature_properties.update(properties or {})
    return _feature(
        geometry=_point_geometry(_as_float(item.get("longitude")), _as_float(item.get("latitude"))),
        layer=layer,
        object_id=str(item.get("object_id") or ""),
        name=str(item.get("dcs_name") or item.get("name") or "") or None,
        object_type=str(item.get("object_type") or "") or None,
        category=str(item.get("category") or "") or None,
        properties=feature_properties,
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
        "properties": {"scope": scope, "coordinate_system": "WGS84", **metadata},
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
                    geometry=_point_geometry(target.longitude, target.latitude),
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
                        "x": target.x,
                        "y": target.y,
                        "z": target.z,
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

    def counts(self) -> dict[str, int]:
        """Return object counts by global-picture layer."""

        return {
            "groups": len(self.groups),
            "units": len(self.units),
            "statics": len(self.statics),
            "airbases": len(self.airbases),
            "zones": len(self.zones),
            "opszones": len(self.opszones),
            "opsgroups": len(self.opsgroups),
            "missions": len(self.missions),
            "legions": len(self.legions),
            "cohorts": len(self.cohorts),
            "intels": len(self.intels),
            "intel_contacts": len(self.intel_contacts),
            "intel_clusters": len(self.intel_clusters),
        }

    def validate(self) -> list[PictureValidationIssue]:
        """Validate global-truth identities, references and map geometry."""

        issues: list[PictureValidationIssue] = []
        raw_layers = {
            "groups": self.groups,
            "units": self.units,
            "statics": self.statics,
            "airbases": self.airbases,
            "zones": self.zones,
        }
        seen_ids: dict[str, str] = {}

        def record_id(layer: str, object_id: str) -> None:
            if not object_id:
                issues.append(PictureValidationIssue("error", "missing_object_id", f"{layer} item has no object_id"))
                return
            previous_layer = seen_ids.get(object_id)
            if previous_layer:
                issues.append(
                    PictureValidationIssue("error", "duplicate_object_id", f"also present in {previous_layer}", object_id)
                )
            else:
                seen_ids[object_id] = layer

        for layer, items in raw_layers.items():
            for item in items:
                object_id = str(item.get("object_id") or "")
                record_id(layer, object_id)
                if not object_id:
                    continue

                has_x = _as_float(item.get("x")) is not None
                has_z = _as_float(item.get("z")) is not None
                latitude = _as_float(item.get("latitude"))
                longitude = _as_float(item.get("longitude"))
                has_latitude = latitude is not None
                has_longitude = longitude is not None
                if has_x != has_z:
                    issues.append(PictureValidationIssue("error", "partial_position", "only x or z is present", object_id))
                if has_latitude != has_longitude:
                    issues.append(
                        PictureValidationIssue(
                            "error", "partial_geographic_position", "only latitude or longitude is present", object_id
                        )
                    )
                if has_x and has_z and not (has_latitude and has_longitude):
                    issues.append(
                        PictureValidationIssue(
                            "warning", "missing_geographic_position", "DCS position has no latitude/longitude", object_id
                        )
                    )
                if latitude is not None and not -90 <= latitude <= 90:
                    issues.append(PictureValidationIssue("error", "invalid_latitude", f"latitude={latitude}", object_id))
                if longitude is not None and not -180 <= longitude <= 180:
                    issues.append(PictureValidationIssue("error", "invalid_longitude", f"longitude={longitude}", object_id))
                if item.get("alive") is True and not (has_x and has_z):
                    issues.append(
                        PictureValidationIssue("warning", "alive_without_position", "alive object has no x/z position", object_id)
                    )
                if layer in {"airbases", "zones"} and not (has_x and has_z):
                    issues.append(
                        PictureValidationIssue("warning", "map_object_without_position", f"{layer} item has no x/z position", object_id)
                    )

        typed_layers = {
            "opszones": self.opszones,
            "opsgroups": self.opsgroups,
            "missions": self.missions,
            "legions": self.legions,
            "cohorts": self.cohorts,
            "intels": self.intels,
            "intel_contacts": self.intel_contacts,
            "intel_clusters": self.intel_clusters,
        }
        for layer, items in typed_layers.items():
            for item in items:
                record_id(layer, item.object_id)
                x = _as_float(getattr(item, "x", None))
                z = _as_float(getattr(item, "z", None))
                latitude = _as_float(getattr(item, "latitude", None))
                longitude = _as_float(getattr(item, "longitude", None))
                if x is not None and z is not None and (latitude is None or longitude is None):
                    issues.append(
                        PictureValidationIssue(
                            "warning", "missing_geographic_position", "DCS position has no latitude/longitude", item.object_id
                        )
                    )
                if latitude is not None and not -90 <= latitude <= 90:
                    issues.append(PictureValidationIssue("error", "invalid_latitude", f"latitude={latitude}", item.object_id))
                if longitude is not None and not -180 <= longitude <= 180:
                    issues.append(PictureValidationIssue("error", "invalid_longitude", f"longitude={longitude}", item.object_id))

        for zone in self.opszones:
            if zone.x is None or zone.z is None:
                issues.append(
                    PictureValidationIssue("warning", "map_object_without_position", "OPSZONE has no x/z position", zone.object_id)
                )

        group_ids = {str(item.get("object_id") or "") for item in self.groups}
        for unit in self.units:
            group_name = unit.get("group_name")
            if group_name and f"GROUP:{group_name}" not in group_ids:
                issues.append(
                    PictureValidationIssue(
                        "warning",
                        "unit_group_missing",
                        f"references missing GROUP:{group_name}",
                        str(unit.get("object_id") or "") or None,
                    )
                )

        for zone in self.zones:
            radius = _as_float(zone.get("radius"))
            if radius is not None and radius <= 0:
                issues.append(
                    PictureValidationIssue(
                        "error", "invalid_zone_radius", f"radius must be positive, got {radius}", str(zone.get("object_id") or "") or None
                    )
                )

        opsgroup_ids = {group.object_id for group in self.opsgroups}
        for group in self.opsgroups:
            if group.group_name and f"GROUP:{group.group_name}" not in group_ids:
                issues.append(
                    PictureValidationIssue(
                        "warning", "opsgroup_group_missing", f"references missing GROUP:{group.group_name}", group.object_id
                    )
                )
            if group.alive and (group.x is None or group.z is None):
                issues.append(
                    PictureValidationIssue("warning", "alive_without_position", "alive OPSGROUP has no x/z position", group.object_id)
                )

        for mission in self.missions:
            for group_id in mission.assigned_group_ids:
                if group_id not in opsgroup_ids:
                    issues.append(
                        PictureValidationIssue(
                            "warning", "mission_opsgroup_missing", f"references missing {group_id}", mission.object_id
                        )
                    )

        return issues

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
                    geometry=_point_geometry(target.longitude, target.latitude),
                    layer="missions",
                    object_id=mission.object_id,
                    name=mission.name,
                    object_type="AUFTRAG",
                    category=mission.type,
                    properties={
                        "mission_type": mission.type,
                        "status": mission.status,
                        "target_name": target.name,
                        "x": target.x,
                        "y": target.y,
                        "z": target.z,
                    },
                )
            )
            for group_id in mission.assigned_group_ids:
                group = groups_by_id.get(group_id)
                geometry = _line_geometry(
                    (
                        (group.longitude if group else None, group.latitude if group else None),
                        (target.longitude, target.latitude),
                    )
                )
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
