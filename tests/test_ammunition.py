from __future__ import annotations

from moosebridge.ammunition import AmmunitionTracker, UnitAmmunition
from moosebridge.state import MooseBridgeState


def _unit(count: int, *, initial_count: int | None = None) -> dict[str, object]:
    weapon: dict[str, object] = {
        "id": "weapons.missiles.BGM_71D",
        "type_name": "weapons.missiles.BGM_71D",
        "display_name": "BGM-71D TOW2",
        "count": count,
        "category": 1,
        "missile_category": 6,
    }
    if initial_count is not None:
        weapon["initial_count"] = initial_count
    return {
        "object_id": "UNIT:Stryker-1",
        "unit_id": "UNIT:Stryker-1",
        "unit_name": "Stryker-1",
        "group_id": "GROUP:Stryker",
        "group_name": "Stryker",
        "dcs_type": "M1134 Stryker ATGM",
        "category": "Ground Unit",
        "attributes": ["ATGM", "Ground Units"],
        "life": 12,
        "life0": 16,
        "weapons": [weapon],
    }


def test_tracker_uses_first_observation_and_preserves_zero_counts() -> None:
    tracker = AmmunitionTracker()

    first = tracker.update([_unit(7)])[0]["weapons"][0]
    second = tracker.update([_unit(0)])[0]["weapons"][0]

    assert first["initial_count"] == 7
    assert first["fraction"] == 1.0
    assert second["count"] == 0
    assert second["initial_count"] == 7
    assert second["fraction"] == 0.0


def test_tracker_increases_observed_baseline_after_rearming() -> None:
    tracker = AmmunitionTracker()
    tracker.update([_unit(7)])
    tracker.update([_unit(3)])

    rearmed = tracker.update([_unit(14)])[0]["weapons"][0]

    assert rearmed["initial_count"] == 14
    assert rearmed["fraction"] == 1.0


def test_typed_ammunition_preserves_weapon_identity_and_life() -> None:
    item = AmmunitionTracker().update([_unit(7)])[0]

    ammunition = UnitAmmunition.from_payload(item)

    assert ammunition.unit_id == "UNIT:Stryker-1"
    assert ammunition.group_id == "GROUP:Stryker"
    assert ammunition.life_fraction == 0.75
    assert ammunition.weapons[0].type_name == "weapons.missiles.BGM_71D"
    assert ammunition.weapons[0].missile_category == 6


def test_state_resets_observed_baseline_when_mission_time_moves_back() -> None:
    state = MooseBridgeState()
    state.apply_message({"type": "heartbeat", "source": "dcs", "mission_time": 100})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(14)]}})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(4)]}})
    assert state.ammunition_objects["UNIT:Stryker-1"].weapons[0].initial_count == 14

    state.apply_message({"type": "heartbeat", "source": "dcs", "mission_time": 1})
    state.apply_message({"type": "snapshot", "kind": "ammunition", "payload": {"ammunition": [_unit(4)]}})

    assert state.ammunition_objects["UNIT:Stryker-1"].weapons[0].initial_count == 4

