"""Tests for scenario-specific DCS component verification."""

from __future__ import annotations

import pytest

from moosebridge.strategic_verification import (
    InfrastructureOperationalState,
    ObservedDcsObject,
    StrategicSiteVerification,
    StrategicVerificationRegistry,
    StrategicVerificationState,
    VerifiedDcsComponent,
    assess_infrastructure_state,
)


def test_registry_round_trip_is_versioned_and_atomic(tmp_path) -> None:
    path = tmp_path / "scenario-verifications.json"
    registry = StrategicVerificationRegistry.from_entries(
        (
            StrategicSiteVerification(
                source_id="ENERGY_SITE:Alpha",
                state=StrategicVerificationState.REPRESENTED,
                observed_objects=(ObservedDcsObject("STATIC:Power-1", type_name="Generator"),),
                observation_complete=True,
                target_components=(VerifiedDcsComponent("STATIC:Power-1", role="generator", weight=2.5),),
                notes="Confirmed on the DCS F10 map",
            ),
        ),
        theater_id="GermanyCW",
        scenario_id="Example conflict",
    )

    registry.save(path)
    loaded = StrategicVerificationRegistry.load(path)

    assert loaded.to_dict() == registry.to_dict()
    assert not path.with_suffix(".json.tmp").exists()
    assert loaded.get("ENERGY_SITE:Alpha").admitted is True  # type: ignore[union-attr]


def test_concrete_component_rejects_coordinates_and_unknown_prefixes() -> None:
    with pytest.raises(ValueError, match="concrete bridge id"):
        VerifiedDcsComponent("COORDINATE:54.1,12.1")
    with pytest.raises(ValueError, match="concrete bridge id"):
        VerifiedDcsComponent("OSM:way/123")


def test_represented_mapping_requires_explicit_target_components() -> None:
    represented = StrategicSiteVerification(
        source_id="PORT_SITE:Rostock",
        state=StrategicVerificationState.REPRESENTED,
    )
    targetable = StrategicSiteVerification(
        source_id=represented.source_id,
        state=represented.state,
        target_components=(VerifiedDcsComponent("ZONE:Rostock Port"),),
    )

    assert represented.admitted is False
    assert targetable.admitted is True


def test_not_represented_mapping_cannot_be_admitted() -> None:
    verification = StrategicSiteVerification(
        source_id="ENERGY_SITE:Absent",
        state=StrategicVerificationState.NOT_REPRESENTED,
        target_components=(VerifiedDcsComponent("ZONE:Absent"),),
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
    assert verification.target_components[0].object_id == "STATIC:Legacy"
    assert verification.state is StrategicVerificationState.REPRESENTED


def test_registry_migrates_detailed_version_two_states() -> None:
    registry = StrategicVerificationRegistry.from_dict({
        "schema_version": 2,
        "verifications": [
            {"source_id": "ENERGY_SITE:Matched", "state": "dcs_scenery_matched"},
            {"source_id": "ENERGY_SITE:Approximate", "state": "approximate", "scenario_approved": True},
            {"source_id": "ENERGY_SITE:Historical", "state": "historically_uncertain"},
            {"source_id": "ENERGY_SITE:Absent", "state": "not_represented"},
        ],
    })

    assert registry.get("ENERGY_SITE:Matched").state is StrategicVerificationState.REPRESENTED  # type: ignore[union-attr]
    assert registry.get("ENERGY_SITE:Approximate").state is StrategicVerificationState.REPRESENTED  # type: ignore[union-attr]
    assert registry.get("ENERGY_SITE:Historical").state is StrategicVerificationState.UNVERIFIED  # type: ignore[union-attr]
    assert registry.get("ENERGY_SITE:Absent").state is StrategicVerificationState.NOT_REPRESENTED  # type: ignore[union-attr]
    assert "scenario_approved" not in registry.to_dict()["verifications"][0]


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
