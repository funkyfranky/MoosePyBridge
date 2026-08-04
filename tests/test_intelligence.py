from __future__ import annotations

from moosebridge import ContactInformationState, IntelContact, IntelContactMemory, TacticalPicture, assess_intel_contact
from moosebridge.clock import DcsTime


def _contact(detected_time: float | None) -> IntelContact:
    payload = {
        "object_id": "INTELCONTACT:Blue:Target",
        "detected_time": detected_time,
        "x": 10.0,
        "z": 20.0,
        "latitude": 54.0,
        "longitude": 12.0,
    }
    return IntelContact.from_payload(payload)


def test_contact_information_quality_uses_last_detected_mission_time() -> None:
    assert assess_intel_contact(_contact(950), 1_000).state is ContactInformationState.FRESH

    degraded = assess_intel_contact(_contact(700), 1_000)
    assert degraded.state is ContactInformationState.DEGRADED
    assert 0.25 < degraded.confidence < 1.0

    stale = assess_intel_contact(_contact(100), 1_000)
    assert stale.state is ContactInformationState.STALE
    assert stale.confidence == 0.1


def test_contact_information_quality_preserves_unknown_and_lost_states() -> None:
    assert assess_intel_contact(_contact(None), 1_000).state is ContactInformationState.UNKNOWN
    assert assess_intel_contact(_contact(900), 1_000, lost=True).state is ContactInformationState.LOST


def test_tactical_picture_exposes_current_and_lost_contact_assessments() -> None:
    current = _contact(950)
    lost = _contact(800)
    picture = TacticalPicture(
        "blue",
        "INTEL:Blue",
        clock=DcsTime(mission_time=1_000),
        contacts=[current],
        lost_contacts=[IntelContactMemory(lost, lost_time=900)],
    )

    assert picture.contact_assessments()[0].state is ContactInformationState.FRESH
    assert picture.lost_contact_assessments()[0].state is ContactInformationState.LOST
    features = picture.to_geojson()["features"]
    assert features[0]["properties"]["information_state"] == "fresh"
    assert features[1]["properties"]["layer"] == "lost_enemy_contacts"
    assert features[1]["properties"]["information_state"] == "lost"
