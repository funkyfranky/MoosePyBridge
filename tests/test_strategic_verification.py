"""Tests for theater-level DCS scenery verification."""

from __future__ import annotations

import json

import pytest

from moosebridge.scenery_verification import (
    active_scenery_verification_markers,
    latest_scenery_verification_marker,
    resolve_scenery_verification_feature,
    scenery_verification_marker_from_event,
    scenery_zone_assignments,
)
from moosebridge.strategic_verification import (
    InfrastructureOperationalState,
    ObservedDcsObject,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
    StrategicVerificationState,
    VerifiedDcsComponent,
    assess_infrastructure_state,
)


def test_common_scenery_resolver_loads_all_supported_artifacts(tmp_path) -> None:
    artifact_paths = {}
    expected_ids = set()
    for index, artifact_key in enumerate((
        "infrastructure_sites",
        "railway_infrastructure",
        "settlements",
        "transport_infrastructure",
    )):
        prefix = (
            "MILITARY_SITE",
            "RAILWAY_STATION",
            "SETTLEMENT",
            "BRIDGE",
        )[index]
        object_id = f"{prefix}:{index}"
        expected_ids.add(object_id)
        path = tmp_path / f"{artifact_key}.geojson"
        path.write_text(json.dumps({
            "type": "FeatureCollection",
            "properties": {"theater_id": "TestTheater"},
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [12.0 + index, 54.0]},
                "properties": {
                    "object_id": object_id,
                    "name": f"Feature {index}",
                    "layer": artifact_key,
                    "category": "test",
                    "source": "test",
                },
            }],
        }), encoding="utf-8")
        artifact_paths[artifact_key] = path

    resolved = {
        object_id: resolve_scenery_verification_feature("TestTheater", object_id, artifact_paths)
        for object_id in expected_ids
    }

    assert set(resolved) == expected_ids
    assert resolved["SETTLEMENT:2"].artifact_key == "settlements"  # type: ignore[union-attr]


def test_scenery_verification_marker_parses_f10_command_and_note() -> None:
    event = {
        "type": "event",
        "event": "map.marker.changed",
        "id": "event-12",
        "mission_time": 42.5,
        "payload": {
            "marker_id": 2516,
            "text": "verified BRIDGE:Caucasus:04b3c5b8894c\nradius 1.5km\nbridge",
            "latitude": 41.75,
            "longitude": 42.125,
            "x": -123.0,
            "y": 45.0,
            "z": 678.0,
            "player_name": "Pilot",
            "coalition": "blue",
        },
    }

    marker = scenery_verification_marker_from_event(event)

    assert marker is not None
    assert marker.source_id == "BRIDGE:Caucasus:04b3c5b8894c"
    assert marker.marker_id == "2516"
    assert marker.note == "bridge"
    assert marker.radius_m == 1500.0
    assert marker.option_errors == ()
    assert marker.latitude == 41.75
    assert marker.longitude == 42.125
    assert marker.player_name == "Pilot"
    assert marker.event_id == "event-12"


def test_active_scenery_verification_markers_follow_change_and_remove_events() -> None:
    source_id = "BRIDGE:Caucasus:04b3c5b8894c"
    events = [
        {
            "type": "event",
            "event": "map.marker.added",
            "payload": {
                "marker_id": 7,
                "text": "",
                "latitude": 41.0,
                "longitude": 42.0,
            },
        },
        {
            "type": "event",
            "event": "map.marker.changed",
            "payload": {
                "marker_id": 7,
                "text": f"verify {source_id}",
                "latitude": 41.1,
                "longitude": 42.1,
            },
        },
        {
            "type": "event",
            "event": "map.marker.changed",
            "payload": {
                "marker_id": 8,
                "text": f"VERIFY {source_id}",
                "latitude": 41.2,
                "longitude": 42.2,
            },
        },
        {
            "type": "event",
            "event": "map.marker.removed",
            "payload": {"marker_id": 7},
        },
    ]

    active = active_scenery_verification_markers(events)
    latest = latest_scenery_verification_marker(events, source_id.lower())

    assert [marker.marker_id for marker in active] == ["8"]
    assert latest is not None
    assert latest.marker_id == "8"
    assert latest.latitude == 41.2


def test_scenery_verification_marker_ignores_unrelated_or_positionless_marks() -> None:
    assert scenery_verification_marker_from_event({
        "type": "event",
        "event": "map.marker.changed",
        "payload": {
            "marker_id": 1,
            "text": "ordinary mission note",
            "latitude": 41.0,
            "longitude": 42.0,
        },
    }) is None
    assert scenery_verification_marker_from_event({
        "type": "event",
        "event": "map.marker.changed",
        "payload": {"marker_id": 1, "text": "verify BRIDGE:Caucasus:test"},
    }) is None


def test_scenery_verification_marker_reports_invalid_radius_options() -> None:
    marker = scenery_verification_marker_from_event({
        "type": "event",
        "event": "map.marker.changed",
        "payload": {
            "marker_id": 9,
            "text": "verify BRIDGE:Caucasus:test\nradius 8km",
            "latitude": 41.0,
            "longitude": 42.0,
        },
    })

    assert marker is not None
    assert marker.radius_m is None
    assert marker.option_errors == ("radius must be greater than 0 and at most 5000 m",)


def test_common_scenery_resolver_rejects_theater_mismatch(tmp_path) -> None:
    path = tmp_path / "settlements.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "properties": {"theater_id": "OtherTheater"},
        "features": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="belongs to theater"):
        resolve_scenery_verification_feature("TestTheater", "SETTLEMENT:1", {"settlements": path})


def test_common_scenery_resolver_rejects_mission_defined_objects() -> None:
    with pytest.raises(ValueError, match="cannot be verified"):
        resolve_scenery_verification_feature("TestTheater", "STATIC:Depot", {})


def test_scenery_zone_assignments_accept_dcs_numeric_suffixes() -> None:
    feature_id = "BRIDGE:Caucasus:4d482fb330eb"
    assignments = scenery_zone_assignments(feature_id, {
        f"ZONE:{feature_id}": {
            "object_id": f"ZONE:{feature_id}",
            "dcs_name": feature_id,
            "properties": {"OBJECT ID": 70254625},
        },
        f"ZONE:{feature_id}-2": {
            "object_id": f"ZONE:{feature_id}-2",
            "dcs_name": f"{feature_id}-2",
            "properties": {"object id": "SCENERY:270213120"},
        },
        f"ZONE:{feature_id}-1": {
            "object_id": f"ZONE:{feature_id}-1",
            "dcs_name": f"{feature_id}-1",
            "properties": {"OBJECT ID": 270213121.0},
        },
    })

    assert [item.zone_name for item in assignments] == [
        feature_id,
        f"{feature_id}-1",
        f"{feature_id}-2",
    ]
    assert [item.scenery_object_id for item in assignments] == [
        "SCENERY:70254625",
        "SCENERY:270213121",
        "SCENERY:270213120",
    ]


def test_scenery_zone_assignments_reject_non_dcs_suffixes_and_missing_properties() -> None:
    feature_id = "BRIDGE:Caucasus:4d482fb330eb"
    assignments = scenery_zone_assignments(feature_id, {
        f"ZONE:{feature_id}-rail": {
            "dcs_name": f"{feature_id}-rail",
            "properties": {"OBJECT ID": 1},
        },
        f"ZONE:prefix-{feature_id}": {
            "dcs_name": f"prefix-{feature_id}",
            "properties": {"OBJECT ID": 2},
        },
        f"ZONE:{feature_id}": {
            "dcs_name": feature_id,
            "properties": {},
        },
    })

    assert assignments == ()


def test_registry_round_trip_is_versioned_and_atomic(tmp_path) -> None:
    path = tmp_path / "scenario-verifications.json"
    registry = StrategicVerificationRegistry.from_entries(
        (
            StrategicSiteVerification(
                source_id="ENERGY_SITE:Alpha",
                state=StrategicVerificationState.REPRESENTED,
                observed_objects=(ObservedDcsObject("SCENERY:Power-1", type_name="Generator"),),
                observation_complete=True,
                target_components=(VerifiedDcsComponent("SCENERY:Power-1", role="generator", weight=2.5),),
                notes="Confirmed on the DCS F10 map",
            ),
        ),
        theater_id="GermanyCW",
    )

    registry.save(path)
    loaded = StrategicVerificationRegistry.load(path)

    assert loaded.to_dict() == registry.to_dict()
    assert not path.with_suffix(".json.tmp").exists()
    assert loaded.get("ENERGY_SITE:Alpha").admitted is True  # type: ignore[union-attr]


def test_components_and_observations_accept_only_scenery_ids() -> None:
    with pytest.raises(ValueError, match="SCENERY"):
        VerifiedDcsComponent("COORDINATE:54.1,12.1")
    with pytest.raises(ValueError, match="SCENERY"):
        VerifiedDcsComponent("STATIC:Power-1")
    with pytest.raises(ValueError, match="SCENERY"):
        ObservedDcsObject("UNIT:Truck-1")


def test_represented_mapping_requires_explicit_target_components() -> None:
    represented = StrategicSiteVerification(
        source_id="PORT_SITE:Rostock",
        state=StrategicVerificationState.REPRESENTED,
        observed_objects=(ObservedDcsObject("SCENERY:Port-1"),),
    )
    targetable = StrategicSiteVerification(
        source_id=represented.source_id,
        state=represented.state,
        observed_objects=represented.observed_objects,
        target_components=(VerifiedDcsComponent("SCENERY:Port-1"),),
    )

    assert represented.admitted is False
    assert targetable.admitted is True


def test_not_represented_mapping_cannot_have_targets() -> None:
    with pytest.raises(ValueError, match="cannot contain target components"):
        StrategicSiteVerification(
            source_id="ENERGY_SITE:Absent",
            state=StrategicVerificationState.NOT_REPRESENTED,
            observed_objects=(ObservedDcsObject("SCENERY:Unrelated"),),
            target_components=(VerifiedDcsComponent("SCENERY:Unrelated"),),
        )

    verification = StrategicSiteVerification(
        source_id="ENERGY_SITE:Absent",
        state=StrategicVerificationState.NOT_REPRESENTED,
    )

    assert verification.admitted is False


def test_observed_objects_do_not_admit_a_site_without_explicit_targets() -> None:
    verification = StrategicSiteVerification(
        source_id="MILITARY_SITE:Barracks",
        state=StrategicVerificationState.REPRESENTED,
        observed_objects=(ObservedDcsObject("SCENERY:1", type_name="BARRACK_SMALL"),),
        observation_complete=True,
    )

    assert verification.admitted is False
    assert verification.to_dict()["observed_objects"][0]["type_name"] == "BARRACK_SMALL"


def test_registry_migrates_version_one_components_to_targets() -> None:
    registry = StrategicVerificationRegistry.from_dict({
        "schema_version": 1,
        "verifications": [{
            "source_id": "ENERGY_SITE:Legacy",
            "state": "confirmed",
            "components": [{"object_id": "STATIC:Legacy"}],
        }],
    })

    verification = registry.get("ENERGY_SITE:Legacy")
    assert verification is not None
    assert verification.observed_objects == ()
    assert verification.target_components == ()
    assert verification.state is StrategicVerificationState.UNVERIFIED


def test_registry_migrates_detailed_version_two_states() -> None:
    registry = StrategicVerificationRegistry.from_dict({
        "schema_version": 2,
        "verifications": [
            {"source_id": "ENERGY_SITE:Matched", "state": "dcs_scenery_matched", "observed_objects": [{"object_id": "SCENERY:1"}]},
            {"source_id": "ENERGY_SITE:Approximate", "state": "approximate", "scenario_approved": True, "observed_objects": [{"object_id": "SCENERY:2"}]},
            {"source_id": "ENERGY_SITE:Historical", "state": "historically_uncertain"},
            {"source_id": "ENERGY_SITE:Absent", "state": "not_represented"},
        ],
    })

    assert registry.get("ENERGY_SITE:Matched").state is StrategicVerificationState.REPRESENTED  # type: ignore[union-attr]
    assert registry.get("ENERGY_SITE:Approximate").state is StrategicVerificationState.REPRESENTED  # type: ignore[union-attr]
    assert registry.get("ENERGY_SITE:Historical").state is StrategicVerificationState.UNVERIFIED  # type: ignore[union-attr]
    assert registry.get("ENERGY_SITE:Absent").state is StrategicVerificationState.NOT_REPRESENTED  # type: ignore[union-attr]
    assert "scenario_approved" not in registry.to_dict()["verifications"][0]


def test_registry_migrates_version_three_to_theater_scenery_only() -> None:
    registry = StrategicVerificationRegistry.from_dict({
        "schema_version": 3,
        "theater_id": "GermanyCW",
        "scenario_id": "Old mission",
        "verifications": [{
            "source_id": "MILITARY_SITE:Alpha",
            "state": "represented",
            "observed_objects": [
                {"object_id": "SCENERY:1"},
                {"object_id": "STATIC:Mission object"},
            ],
            "target_components": [
                {"object_id": "SCENERY:1"},
                {"object_id": "STATIC:Mission object"},
            ],
        }],
    })

    verification = registry.get("MILITARY_SITE:Alpha")
    assert verification is not None
    assert [item.object_id for item in verification.observed_objects] == ["SCENERY:1"]
    assert [item.object_id for item in verification.target_components] == ["SCENERY:1"]
    assert "scenario_id" not in registry.to_dict()


def test_target_components_must_come_from_observed_baseline() -> None:
    with pytest.raises(ValueError, match="observed scenery baseline"):
        StrategicSiteVerification(
            source_id="MILITARY_SITE:Alpha",
            observed_objects=(ObservedDcsObject("SCENERY:1"),),
            target_components=(VerifiedDcsComponent("SCENERY:2"),),
        )


def test_complete_matching_baseline_is_operational() -> None:
    verification = StrategicSiteVerification(
        source_id="MILITARY_SITE:Barracks",
        observed_objects=(
            ObservedDcsObject("SCENERY:1", life=100),
            ObservedDcsObject("SCENERY:2", life=100),
        ),
        observation_complete=True,
    )

    assessment = assess_infrastructure_state(
        verification,
        (ObservedDcsObject("SCENERY:1", life=100), ObservedDcsObject("SCENERY:2", life=100)),
        current_observation_complete=True,
    )

    assert assessment.state is InfrastructureOperationalState.OPERATIONAL
    assert assessment.complete is True
    assert assessment.health_min == assessment.health_max == 1.0


def test_damage_events_drive_damaged_disabled_and_destroyed_states() -> None:
    verification = StrategicSiteVerification(
        source_id="MILITARY_SITE:Barracks",
        observed_objects=tuple(ObservedDcsObject(f"SCENERY:{index}", life=100) for index in range(4)),
        observation_complete=True,
    )
    current = tuple(ObservedDcsObject(f"SCENERY:{index}", life=100) for index in range(4))

    damaged = assess_infrastructure_state(
        verification,
        (*current[:1], ObservedDcsObject("SCENERY:1", life=50), *current[2:]),
        current_observation_complete=True,
    )
    disabled = assess_infrastructure_state(
        verification,
        current,
        destroyed_object_ids={"SCENERY:0", "SCENERY:1", "SCENERY:2"},
        current_observation_complete=False,
    )
    destroyed = assess_infrastructure_state(
        verification,
        current,
        destroyed_object_ids={item.object_id for item in current},
        current_observation_complete=False,
    )

    assert damaged.state is InfrastructureOperationalState.DAMAGED
    assert damaged.damage_min == damaged.damage_max == pytest.approx(0.125)
    assert disabled.state is InfrastructureOperationalState.DISABLED
    assert destroyed.state is InfrastructureOperationalState.DESTROYED


def test_incomplete_survey_preserves_health_uncertainty() -> None:
    verification = StrategicSiteVerification(
        source_id="MILITARY_SITE:Barracks",
        observed_objects=tuple(ObservedDcsObject(f"SCENERY:{index}") for index in range(4)),
        observation_complete=True,
    )

    assessment = assess_infrastructure_state(
        verification,
        (ObservedDcsObject("SCENERY:0"), ObservedDcsObject("SCENERY:1")),
        current_observation_complete=False,
    )

    assert assessment.state is InfrastructureOperationalState.UNKNOWN
    assert assessment.unknown_count == 2
    assert assessment.health_min == pytest.approx(0.5)
    assert assessment.health_max == pytest.approx(1.0)


def test_partial_baseline_never_claims_disabled_or_destroyed_site() -> None:
    verification = StrategicSiteVerification(
        source_id="MILITARY_SITE:Barracks",
        observed_objects=(ObservedDcsObject("SCENERY:1"),),
        observation_complete=False,
    )

    assessment = assess_infrastructure_state(
        verification,
        (),
        destroyed_object_ids={"SCENERY:1"},
        current_observation_complete=True,
    )

    assert assessment.state is InfrastructureOperationalState.DAMAGED
    assert assessment.complete is False
