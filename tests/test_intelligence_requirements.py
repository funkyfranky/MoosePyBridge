from __future__ import annotations

from moosebridge.clock import DcsTime
from moosebridge.intelligence import (
    InformationRequirement,
    InformationRequirementMatch,
    InformationRequirementRegistry,
    InformationRequirementStatus,
)
from moosebridge.sdk import MooseBridgeClient
from moosebridge.state import MooseBridgeState


def _contact_event(event: str, contact_id: str, target_id: str, mission_time: float) -> dict[str, object]:
    return {
        "type": "event",
        "id": f"event-{event}-{contact_id}-{mission_time}",
        "event": event,
        "mission_time": mission_time,
        "payload": {
            "intel_id": "INTEL:Blue",
            "contact": {
                "object_id": contact_id,
                "object_type": "INTELCONTACT",
                "intel_id": "INTEL:Blue",
                "target_object_id": target_id,
                "detected_time": mission_time,
            },
        },
    }


def test_information_requirement_tracks_all_targets_without_task_side_effects() -> None:
    state = MooseBridgeState(clock=DcsTime(mission_time=10))
    registry = InformationRequirementRegistry()
    observed_events = []
    registry.add_listener(observed_events.append)
    requirement = registry.add(
        InformationRequirement(
            "ISR:Defenders",
            "INTEL:Blue",
            ("GROUP:Red-1", "GROUP:Red-2"),
        ),
        state=state,
    )

    state.apply_message(_contact_event("intel.new_contact", "CONTACT:1", "GROUP:Red-1", 20))
    registry.sync(state, source="intel.new_contact")
    assert requirement.status is InformationRequirementStatus.PARTIAL
    assert requirement.observed_target_ids == ("GROUP:Red-1",)
    assert requirement.missing_target_ids == ("GROUP:Red-2",)

    state.apply_message(_contact_event("intel.new_contact", "CONTACT:2", "GROUP:Red-2", 30))
    registry.sync(state, source="intel.new_contact")
    assert requirement.status is InformationRequirementStatus.SATISFIED
    assert requirement.satisfied_mission_time == 30

    state.apply_message(_contact_event("intel.lost_contact", "CONTACT:1", "GROUP:Red-1", 40))
    registry.sync(state, source="intel.lost_contact")
    assert requirement.status is InformationRequirementStatus.LOST
    assert requirement.lost_target_ids == ("GROUP:Red-1",)

    state.apply_message(_contact_event("intel.new_contact", "CONTACT:1", "GROUP:Red-1", 50))
    registry.sync(state, source="intel.new_contact")
    assert requirement.status is InformationRequirementStatus.SATISFIED
    assert requirement.satisfied_mission_time == 50
    assert [event.event for event in observed_events] == [
        "information_requirement.created",
        "information_requirement.partial",
        "information_requirement.satisfied",
        "information_requirement.lost",
        "information_requirement.satisfied",
    ]


def test_information_requirement_any_match_is_satisfied_by_one_coalition_contact() -> None:
    state = MooseBridgeState(clock=DcsTime(mission_time=10))
    registry = InformationRequirementRegistry()
    requirement = registry.add(
        InformationRequirement(
            "ISR:Any SAM",
            "INTEL:Blue",
            ("GROUP:SAM-1", "GROUP:SAM-2"),
            match=InformationRequirementMatch.ANY,
        ),
        state=state,
    )

    state.apply_message(_contact_event("intel.new_contact", "CONTACT:SAM", "GROUP:SAM-2", 20))
    events = registry.sync(state, source="intel.new_contact")

    assert requirement.status is InformationRequirementStatus.SATISFIED
    assert requirement.observed_target_ids == ("GROUP:SAM-2",)
    assert events[0].event == "information_requirement.satisfied"


def test_information_requirements_are_isolated_by_intel_source() -> None:
    state = MooseBridgeState(clock=DcsTime(mission_time=10))
    registry = InformationRequirementRegistry()
    blue = registry.add(InformationRequirement("ISR:Blue", "INTEL:Blue", ("GROUP:Target",)), state=state)
    red = registry.add(InformationRequirement("ISR:Red", "INTEL:Red", ("GROUP:Target",)), state=state)

    state.apply_message(_contact_event("intel.new_contact", "CONTACT:Target", "GROUP:Target", 20))
    registry.sync(state, source="intel.new_contact")

    assert blue.status is InformationRequirementStatus.SATISFIED
    assert red.status is InformationRequirementStatus.OPEN


def test_sdk_listener_updates_requirement_without_sending_a_command() -> None:
    class Server:
        def __init__(self) -> None:
            self.state = MooseBridgeState(clock=DcsTime(mission_time=10))
            self.listeners = []
            self.commands = []

        def add_message_listener(self, listener: object) -> None:
            self.listeners.append(listener)

        def emit(self, message: dict[str, object]) -> None:
            self.state.apply_message(message)
            for listener in tuple(self.listeners):
                listener(message)

    server = Server()
    bridge = MooseBridgeClient(server)  # type: ignore[arg-type]
    requirement = bridge.add_information_requirement(
        InformationRequirement("ISR:Passive", "INTEL:Blue", ("GROUP:Target",))
    )

    server.emit(_contact_event("intel.new_contact", "CONTACT:Target", "GROUP:Target", 20))

    assert requirement.status is InformationRequirementStatus.SATISFIED
    assert server.commands == []
