from __future__ import annotations

import asyncio
import io
import json
import logging
from contextlib import redirect_stdout
from typing import Any

from moosebridge.control import MooseBridgeControlClient, MooseBridgeControlServer, apply_state_payload, state_payload
from examples.control_server_client.interactive_control_client import (
    normalize_snapshot_actions,
    normalize_legion_id,
    normalize_drawzone_line_type,
    normalize_drawzone_object_id,
    parse_coords_argument,
    parse_drawzone_argument,
    parse_drawzone_options,
    parse_mission_assign_argument,
    parse_mission_argument,
    parse_message_argument,
    parse_nearest_argument,
    parse_state_output_args,
    parse_trace_argument,
    print_nearest,
    print_state,
    print_trace,
    print_mission_feedback,
    print_command_feedback,
    snapshot_actions_to_kinds,
    split_object_argument,
    split_two_object_arguments,
)
from moosebridge.recommendations import AuftragRecommendation
from moosebridge.protocol import BridgeCommand
from moosebridge.sdk import NearestResult
from moosebridge.state import MooseBridgeState
from moosebridge.server import DcsBridgeConnectionError, MooseBridgeServer


class FakeBridgeServer:
    def __init__(self) -> None:
        self.state = MooseBridgeState(connected=True)
        self.commands: list[tuple[BridgeCommand, float]] = []

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        self.commands.append((command, timeout))
        if command.action == "snapshot.groups":
            self.state.apply_message(
                {
                    "type": "snapshot",
                    "kind": "groups",
                    "payload": {
                        "groups": [
                            {
                                "object_id": "GROUP:Blue Armor",
                                "dcs_name": "Blue Armor",
                                "object_type": "GROUP",
                                "coalition": "blue",
                            }
                        ]
                    },
                }
            )
        return {
            "type": "ack",
            "ok": True,
            "correlation_id": command.id,
            "result": {"action": command.action, "params": command.params},
        }


class SlowFakeBridgeServer(FakeBridgeServer):
    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
        await asyncio.sleep(0.38)
        return await super().send_command(command, timeout=timeout)


def _control_port(server: MooseBridgeControlServer) -> int:
    assert server._server is not None
    sockets = server._server.sockets
    assert sockets
    return int(sockets[0].getsockname()[1])


async def _with_control_server() -> tuple[FakeBridgeServer, MooseBridgeControlServer, MooseBridgeControlClient]:
    bridge = FakeBridgeServer()
    server = MooseBridgeControlServer(bridge, host="127.0.0.1", port=0)
    await server.start()
    client = MooseBridgeControlClient("127.0.0.1", _control_port(server))
    return bridge, server, client


def test_state_payload_roundtrip_applies_requested_kinds() -> None:
    source = MooseBridgeState(connected=True)
    source.apply_message(
        {
            "type": "snapshot",
            "source": "dcs",
            "sequence": 12,
            "mission_time": 125.5,
            "dcs_time": 43_325.5,
            "mission_date": "2026/07/15",
            "wall_time": "2026-07-15T12:00:00Z",
            "kind": "objects",
            "payload": {
                "objects": [
                    {
                        "object_id": "UNIT:Scout-1",
                        "dcs_name": "Scout-1",
                        "object_type": "UNIT",
                    }
                ]
            },
        }
    )

    target = MooseBridgeState()
    payload = state_payload(source, kinds=("objects",))
    apply_state_payload(target, payload)

    assert payload["counts"]["objects"] == 1
    assert target.connected is True
    assert target.objects["UNIT:Scout-1"]["object_type"] == "UNIT"
    assert payload["clock"]["dcs_time"] == 43_325.5
    assert target.clock is not None
    assert target.clock.mission_time == 125.5
    assert target.clock.time_of_day == "12:02:05"
    assert target.clock.dcs_date == "2026/07/15"
    assert target.snapshot_clocks["objects"].sequence == 12


def test_interactive_snapshot_aliases_normalize_to_bridge_actions() -> None:
    actions = normalize_snapshot_actions(("groups", "units", "snapshot.cohorts", "all"))

    assert actions == ("snapshot.groups", "snapshot.units", "snapshot.cohorts", "snapshot.all")
    assert snapshot_actions_to_kinds(actions) is None


def test_interactive_state_output_args_parse_filters() -> None:
    mode, kinds, state_filter = parse_state_output_args('--list zones --contains "Town Fight" --coalition blue --alive --limit 5')

    assert mode == "list"
    assert kinds == ("zones",)
    assert state_filter.contains == "Town Fight"
    assert state_filter.coalition == "blue"
    assert state_filter.alive is True
    assert state_filter.limit == 5


def test_interactive_state_output_filters_list_items() -> None:
    client = MooseBridgeControlClient()
    client.state.apply_message(
        {
            "type": "snapshot",
            "kind": "groups",
            "payload": {
                "groups": [
                    {
                        "object_id": "GROUP:Blue Armor",
                        "dcs_name": "Blue Armor",
                        "object_type": "GROUP",
                        "coalition": "blue",
                        "category": "Ground Unit",
                        "alive": True,
                    },
                    {
                        "object_id": "GROUP:Red Armor",
                        "dcs_name": "Red Armor",
                        "object_type": "GROUP",
                        "coalition": "red",
                        "category": "Ground Unit",
                        "alive": True,
                    },
                    {
                        "object_id": "GROUP:Blue Dead",
                        "dcs_name": "Blue Dead",
                        "object_type": "GROUP",
                        "coalition": "blue",
                        "category": "Ground Unit",
                        "alive": False,
                    },
                ]
            },
        }
    )
    _, _, state_filter = parse_state_output_args("--coalition blue --alive")
    output = io.StringIO()

    with redirect_stdout(output):
        print_state(client, kinds=("groups",), mode="list", state_filter=state_filter)

    text = output.getvalue()
    assert "GROUP:Blue Armor" in text
    assert "GROUP:Red Armor" not in text
    assert "GROUP:Blue Dead" not in text
    assert '"connected"' not in text
    assert '"counts"' not in text


def test_interactive_state_output_filters_contains() -> None:
    client = MooseBridgeControlClient()
    client.state.apply_message(
        {
            "type": "snapshot",
            "kind": "zones",
            "payload": {
                "zones": [
                    {"object_id": "ZONE:Town Fight", "dcs_name": "Town Fight", "object_type": "ZONE"},
                    {"object_id": "ZONE:Rear Area", "dcs_name": "Rear Area", "object_type": "ZONE"},
                ]
            },
        }
    )
    _, _, state_filter = parse_state_output_args('--contains "Town"')
    output = io.StringIO()

    with redirect_stdout(output):
        print_state(client, kinds=("zones",), mode="list", state_filter=state_filter)

    text = output.getvalue()
    assert "ZONE:Town Fight" in text
    assert "ZONE:Rear Area" not in text


def test_interactive_command_feedback_is_concise_by_default() -> None:
    output = io.StringIO()
    ack = {
        "ok": True,
        "result": {
            "text": "Hello Mate",
            "x": -57639.609375,
            "z": -475128.375,
        },
    }

    with redirect_stdout(output):
        print_command_feedback(ack, "mark.object", debug=False)

    assert output.getvalue().strip() == "OK mark.object text='Hello Mate' x=-57639.609375 z=-475128.375"


def test_interactive_command_feedback_debug_prints_raw_ack() -> None:
    output = io.StringIO()
    ack = {"ok": True, "id": "ack-1", "result": {"text": "Hello Mate"}}

    with redirect_stdout(output):
        print_command_feedback(ack, "mark.object", debug=True)

    assert '"id": "ack-1"' in output.getvalue()
    assert '"result"' in output.getvalue()


def test_interactive_command_feedback_prints_coordinate_fields() -> None:
    output = io.StringIO()
    ack = {
        "ok": True,
        "result": {
            "action": "object.coords",
            "format": "all",
            "object_id": "GROUP:Enemy-1",
            "x": -1.5,
            "y": 12,
            "z": -2.5,
            "latitude": 54.1,
            "longitude": 13.2,
            "mgrs": "33U UV 46038 98158",
        },
    }

    with redirect_stdout(output):
        print_command_feedback(ack, "object.coords", debug=False)

    text = output.getvalue().strip()
    assert "OK object.coords" in text
    assert "object=GROUP:Enemy-1" in text
    assert "x=-1.500 y=12.000 z=-2.500" in text
    assert "lat=54.10000 lon=13.20000" in text
    assert "mgrs='33U UV 46038 98158'" in text


def test_interactive_command_feedback_respects_mgrs_coordinate_format() -> None:
    output = io.StringIO()
    ack = {
        "ok": True,
        "result": {
            "action": "object.coords",
            "format": "mgrs",
            "object_id": "ZONE:Town Fight",
            "x": -33711.171875,
            "y": 9.5332527160645,
            "z": -510211,
            "latitude": 54.108514182505,
            "longitude": 12.644885348283,
            "mgrs": "33U UV 46038 98158",
        },
    }

    with redirect_stdout(output):
        print_command_feedback(ack, "object.coords", debug=False)

    text = output.getvalue().strip()
    assert text == "OK object.coords object=ZONE:Town Fight mgrs='33U UV 46038 98158'"


def test_interactive_command_feedback_prints_distance_fields() -> None:
    output = io.StringIO()
    ack = {
        "ok": True,
        "result": {
            "action": "object.distance",
            "object_id_a": "GROUP:Aerial-1",
            "object_id_b": "ZONE:Town Fight",
            "distance_m": 1852,
            "distance_nm": 1,
        },
    }

    with redirect_stdout(output):
        print_command_feedback(ack, "object.distance", debug=False)

    assert output.getvalue().strip() == "OK object.distance from=GROUP:Aerial-1 to=ZONE:Town Fight meters=1852.0 nm=1.00"


def test_interactive_message_argument_defaults_to_all() -> None:
    assert parse_message_argument("Hello Mate") == ("all", "Hello Mate")
    assert parse_message_argument("blue Push now") == ("blue", "Push now")
    assert parse_message_argument("all Broadcast") == ("all", "Broadcast")


def test_interactive_message_argument_requires_text() -> None:
    try:
        parse_message_argument("blue")
    except ValueError as exc:
        assert "requires text" in str(exc)
    else:
        raise AssertionError("message recipient without text was accepted")


def test_interactive_drawzone_options_parse_style_fields() -> None:
    params = parse_drawzone_options(
        ["--coalition", "blue", "--color", "red", "--alpha", "0.8", "--fill-color", "yellow", "--fill-alpha", "0.15", "--line-type", "dashed"]
    )

    assert params == {
        "coalition": "blue",
        "color": "red",
        "alpha": 0.8,
        "fill_color": "yellow",
        "fill_alpha": 0.15,
        "line_type": 2,
    }


def test_interactive_drawzone_line_type_accepts_names_and_numbers() -> None:
    assert normalize_drawzone_line_type("solid") == 1
    assert normalize_drawzone_line_type("dot-dash") == 4
    assert normalize_drawzone_line_type("6") == 6


def test_interactive_drawzone_object_id_defaults_bare_names_to_zone() -> None:
    assert normalize_drawzone_object_id("Town Fight") == "ZONE:Town Fight"
    assert normalize_drawzone_object_id("OPSZONE:Alpha") == "OPSZONE:Alpha"


def test_interactive_drawzone_argument_accepts_unquoted_zone_id_with_spaces() -> None:
    object_id, params = parse_drawzone_argument("ZONE:Town Fight")

    assert object_id == "ZONE:Town Fight"
    assert params == {}


def test_interactive_drawzone_argument_splits_options_after_zone_id() -> None:
    object_id, params = parse_drawzone_argument("ZONE:Town Fight --coalition blue --line-type dashed")

    assert object_id == "ZONE:Town Fight"
    assert params == {"coalition": "blue", "line_type": 2}


def test_interactive_coords_argument_defaults_to_xyz() -> None:
    object_id, params = parse_coords_argument("GROUP:Aerial-1")

    assert object_id == "GROUP:Aerial-1"
    assert params == {"object_id": "GROUP:Aerial-1"}


def test_interactive_coords_argument_accepts_unquoted_id_with_spaces_and_format() -> None:
    object_id, params = parse_coords_argument("AIRBASE:Gross Mohrdorf --format mgrs")

    assert object_id == "AIRBASE:Gross Mohrdorf"
    assert params == {"object_id": "AIRBASE:Gross Mohrdorf", "format": "mgrs"}


def test_interactive_distance_argument_splits_two_object_ids() -> None:
    object_id_a, object_id_b = split_two_object_arguments(
        '"ZONE:Town Fight" AIRBASE:Gross Mohrdorf',
        known_ids=set(),
    )

    assert object_id_a == "ZONE:Town Fight"
    assert object_id_b == "AIRBASE:Gross Mohrdorf"


def test_interactive_nearest_argument_parses_target_and_filters() -> None:
    kind, target_id, state_filter = parse_nearest_argument('units "ZONE:Town Fight" --coalition red --alive --limit 3')

    assert kind == "units"
    assert target_id == "ZONE:Town Fight"
    assert state_filter.coalition == "red"
    assert state_filter.alive is True
    assert state_filter.limit == 3


def test_interactive_print_nearest_displays_sdk_results() -> None:
    results = [
        NearestResult(
            object_id="UNIT:Near",
            distance_m=100,
            distance_nm=100 / 1852,
            item={"object_id": "UNIT:Near", "dcs_name": "Near", "object_type": "UNIT", "x": 100, "z": 0, "alive": True},
        ),
        NearestResult(
            object_id="UNIT:Far",
            distance_m=1000,
            distance_nm=1000 / 1852,
            item={"object_id": "UNIT:Far", "dcs_name": "Far", "object_type": "UNIT", "x": 1000, "z": 0, "alive": True},
        ),
    ]
    output = io.StringIO()

    with redirect_stdout(output):
        print_nearest("units", "ZONE:Target", results)

    text = output.getvalue()
    assert text.index("UNIT:Near") < text.index("UNIT:Far")
    assert "100.0m 0.05NM" in text


def test_interactive_object_argument_accepts_quoted_ids_with_spaces() -> None:
    object_id, rest = split_object_argument('"ZONE:Town Fight" Hello Mate', known_ids=set())

    assert object_id == "ZONE:Town Fight"
    assert rest == ["Hello", "Mate"]


def test_interactive_object_argument_uses_longest_known_unquoted_id() -> None:
    object_id, rest = split_object_argument(
        "AIRBASE:Gross Mohrdorf Hello Mate",
        known_ids={"AIRBASE:Gross Mohrdorf"},
    )

    assert object_id == "AIRBASE:Gross Mohrdorf"
    assert rest == ["Hello", "Mate"]


def test_interactive_mission_argument_parses_auftrag_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'ARTY --target UNIT:Ground-1-1 --Nshots 5 --radius 100 -legion "BRIGADE:Laage" --preview'
    )

    assert mission_type == "ARTY"
    assert params == {"target": "UNIT:Ground-1-1", "nshots": 5.0, "radius_m": 100.0}
    assert coalition is None
    assert legion_id == "BRIGADE:Laage"
    assert preview is True


def test_interactive_mission_argument_parses_coalition() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument("BAI --target GROUP:Ground-1 -coalition blue")

    assert mission_type == "BAI"
    assert params == {"target": "GROUP:Ground-1"}
    assert coalition == "blue"
    assert legion_id is None
    assert preview is False


def test_interactive_mission_argument_parses_timing_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'BAI --target GROUP:Ground-1 --clock-start 600 --clock-stop "13:00" --duration 1800 --assets-min 2 --assets-max 4 -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "BAI"
    assert params == {
        "target": "GROUP:Ground-1",
        "clock_start": 600.0,
        "clock_stop": "13:00",
        "duration": 1800.0,
        "required_assets_min": 2,
        "required_assets_max": 4,
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_assign_argument_parses_target() -> None:
    mission_id, legion_id, opsgroup_id = parse_mission_assign_argument('AUFTRAG:1 --legion "LEGION:Wing Parchim"')

    assert mission_id == "AUFTRAG:1"
    assert legion_id == "LEGION:Wing Parchim"
    assert opsgroup_id is None


def test_interactive_mission_argument_parses_orbit_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'ORBIT --target "ZONE:CAP Station" --altitude 15000 --speed 300 --heading 90 --leg 20 -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "ORBIT"
    assert params == {
        "target": "ZONE:CAP Station",
        "altitude_ft": 15000.0,
        "speed_kts": 300.0,
        "heading_deg": 90.0,
        "leg_nm": 20.0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_awacs_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'AWACS --target "ZONE:AWACS Track" --altitude 30000 --speed 350 --heading 270 --leg 10 -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "AWACS"
    assert params == {
        "target": "ZONE:AWACS Track",
        "altitude_ft": 30000.0,
        "speed_kts": 350.0,
        "heading_deg": 270.0,
        "leg_nm": 10.0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_tanker_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'TANKER --target "ZONE:Tanker Track" --altitude 20000 --speed 300 --heading 270 --leg 10 '
        '--refuel-system 1 -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "TANKER"
    assert params == {
        "target": "ZONE:Tanker Track",
        "altitude_ft": 20000.0,
        "speed_kts": 300.0,
        "heading_deg": 270.0,
        "leg_nm": 10.0,
        "refuel_system": 1,
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_bombcarpet_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'BOMBCARPET --target GROUP:Convoy --altitude 25000 --carpet-length 500 -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "BOMBCARPET"
    assert params == {
        "target": "GROUP:Convoy",
        "altitude_ft": 25000.0,
        "carpet_length_m": 500.0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_intercept_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'INTERCEPT --target "GROUP:Bandit-1" -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "INTERCEPT"
    assert params == {
        "target": "GROUP:Bandit-1",
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_strafing_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'STRAFING --target GROUP:Convoy --altitude 1000 --length 300 -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "STRAFING"
    assert params == {
        "target": "GROUP:Convoy",
        "altitude_ft": 1000.0,
        "length_m": 300.0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_groundescort_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'GROUNDESCORT --target GROUP:Convoy --orbit-distance 1.5 --target-types "Ground vehicles" -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "GROUNDESCORT"
    assert params == {
        "target": "GROUP:Convoy",
        "orbit_distance_nm": 1.5,
        "target_types": ["Ground vehicles"],
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_groundattack_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'GROUNDATTACK --target "GROUP:Enemy Convoy" --speed 25 --formation Vee -legion "LEGION:Ground Brigade"'
    )

    assert mission_type == "GROUNDATTACK"
    assert params == {
        "target": "GROUP:Enemy Convoy",
        "speed_kts": 25.0,
        "formation": "Vee",
    }
    assert coalition is None
    assert legion_id == "LEGION:Ground Brigade"
    assert preview is False


def test_interactive_mission_argument_parses_antiship_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'ANTISHIP --target "GROUP:Enemy Ships" --altitude 2000 -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "ANTISHIP"
    assert params == {
        "target": "GROUP:Enemy Ships",
        "altitude_ft": 2000.0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_navalengagement_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'NAVALENGAGEMENT --target "UNIT:Target Ship" --speed 18 --depth 20 -legion "LEGION:Naval Group"'
    )

    assert mission_type == "NAVALENGAGEMENT"
    assert params == {
        "target": "UNIT:Target Ship",
        "speed_kts": 18.0,
        "depth_m": 20.0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Naval Group"
    assert preview is False


def test_interactive_mission_argument_parses_escort_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'ESCORT --target "GROUP:Package Lead" --offset-x -100 --offset-y 0 --offset-z 200 '
        '--engage-max-distance 32 --target-types Air -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "ESCORT"
    assert params == {
        "target": "GROUP:Package Lead",
        "offset_x": -100.0,
        "offset_y": 0.0,
        "offset_z": 200.0,
        "engage_max_distance_nm": 32.0,
        "target_types": ["Air"],
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_trooptransport_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'TROOPTRANSPORT --groups "GROUP:Infantry-1,GROUP:Infantry-2" --dropoff "ZONE:LZ Bravo" '
        '--pickup "ZONE:LZ Alpha" --pickup-radius 100 -legion "LEGION:Helo Lift"'
    )

    assert mission_type == "TROOPTRANSPORT"
    assert params == {
        "transport_groups": ["GROUP:Infantry-1", "GROUP:Infantry-2"],
        "dropoff": "ZONE:LZ Bravo",
        "pickup": "ZONE:LZ Alpha",
        "pickup_radius_m": 100.0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Helo Lift"
    assert preview is False


def test_interactive_mission_argument_parses_cap_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'CAP --target "ZONE:Town Fight" --coordinate "ZONE:CAP Station" --altitude 15000 --speed 300 '
        '--heading 90 --leg 20 --target-types Air -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "CAP"
    assert params == {
        "zone": "ZONE:Town Fight",
        "coordinate": "ZONE:CAP Station",
        "altitude_ft": 15000.0,
        "speed_kts": 300.0,
        "heading_deg": 90.0,
        "leg_nm": 20.0,
        "target_types": ["Air"],
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_cas_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'CAS --target "ZONE:Town Fight" --altitude 12000 --speed 280 --heading 45 --leg 12 '
        '--target-types "Ground Units,Light armed ships" -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "CAS"
    assert params == {
        "zone": "ZONE:Town Fight",
        "altitude_ft": 12000.0,
        "speed_kts": 280.0,
        "heading_deg": 45.0,
        "leg_nm": 12.0,
        "target_types": ["Ground Units", "Light armed ships"],
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_casenhanced_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'CASENHANCED --target "ZONE:Town Fight" --altitude 2000 --speed 250 --range-max 25 '
        '--no-engage-zones "ZONE:Friendly Area,ZONE:Blue FARP" '
        '--target-types "Ground Units,Light armed ships" -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "CASENHANCED"
    assert params == {
        "zone": "ZONE:Town Fight",
        "altitude_ft": 2000.0,
        "speed_kts": 250.0,
        "range_max_nm": 25.0,
        "no_engage_zones": ["ZONE:Friendly Area", "ZONE:Blue FARP"],
        "target_types": ["Ground Units", "Light armed ships"],
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_mission_argument_parses_fac_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'FAC --target "ZONE:Town Fight" --speed 80 --altitude 2000 --frequency 133 --modulation 0 -legion "LEGION:Ground Brigade"'
    )

    assert mission_type == "FAC"
    assert params == {
        "zone": "ZONE:Town Fight",
        "speed_kts": 80.0,
        "altitude_ft": 2000.0,
        "frequency_mhz": 133.0,
        "modulation": 0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Ground Brigade"
    assert preview is False


def test_interactive_mission_argument_parses_patrolzone_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'PATROLZONE --target "ZONE:Patrol Area" --speed 20 --altitude 2000 --formation "Off Road" '
        '-legion "LEGION:Ground Brigade"'
    )

    assert mission_type == "PATROLZONE"
    assert params == {
        "zone": "ZONE:Patrol Area",
        "speed_kts": 20.0,
        "altitude_ft": 2000.0,
        "formation": "Off Road",
    }
    assert coalition is None
    assert legion_id == "LEGION:Ground Brigade"
    assert preview is False


def test_interactive_mission_argument_parses_capturezone_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'CAPTUREZONE --target "OPSZONE:Town Fight" --capture-coalition blue --speed 20 '
        '--altitude 2000 --formation "Off Road" --stay 300 -legion "LEGION:Ground Brigade"'
    )

    assert mission_type == "CAPTUREZONE"
    assert params == {
        "opszone": "OPSZONE:Town Fight",
        "capture_coalition": "blue",
        "speed_kts": 20.0,
        "altitude_ft": 2000.0,
        "formation": "Off Road",
        "stay_in_zone_time_s": 300.0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Ground Brigade"
    assert preview is False


def test_interactive_mission_argument_parses_supply_zone_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'AMMOSUPPLY --target "ZONE:Forward Depot" -legion "LEGION:Ground Logistics"'
    )

    assert mission_type == "AMMOSUPPLY"
    assert params == {
        "zone": "ZONE:Forward Depot",
    }
    assert coalition is None
    assert legion_id == "LEGION:Ground Logistics"
    assert preview is False


def test_interactive_mission_argument_parses_airdefense_and_ewr_zone_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'AIRDEFENSE --target "ZONE:Forward SAM" -legion "LEGION:Air Defense"'
    )

    assert mission_type == "AIRDEFENSE"
    assert params == {"zone": "ZONE:Forward SAM"}
    assert coalition is None
    assert legion_id == "LEGION:Air Defense"
    assert preview is False

    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'EWR --target "ZONE:EWR Site" -legion "LEGION:Radar Net"'
    )

    assert mission_type == "EWR"
    assert params == {"zone": "ZONE:EWR Site"}
    assert coalition is None
    assert legion_id == "LEGION:Radar Net"
    assert preview is False


def test_interactive_mission_argument_parses_onguard_and_nothing_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'ONGUARD --target "ZONE:Guard Point" -legion "LEGION:Ground Brigade"'
    )

    assert mission_type == "ONGUARD"
    assert params == {"target": "ZONE:Guard Point"}
    assert coalition is None
    assert legion_id == "LEGION:Ground Brigade"
    assert preview is False

    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'NOTHING --target "ZONE:Relax" -legion "LEGION:Ground Brigade"'
    )

    assert mission_type == "NOTHING"
    assert params == {"zone": "ZONE:Relax"}
    assert coalition is None
    assert legion_id == "LEGION:Ground Brigade"
    assert preview is False


def test_interactive_mission_argument_parses_faca_options() -> None:
    mission_type, params, coalition, legion_id, preview = parse_mission_argument(
        'FACA --target GROUP:Ground-1 --designation LASER --no-data-link --frequency 133 --modulation 0 -legion "LEGION:Wing Parchim"'
    )

    assert mission_type == "FACA"
    assert params == {
        "target": "GROUP:Ground-1",
        "designation": "LASER",
        "data_link": False,
        "frequency_mhz": 133.0,
        "modulation": 0,
    }
    assert coalition is None
    assert legion_id == "LEGION:Wing Parchim"
    assert preview is False


def test_interactive_legion_alias_normalizes_to_legion_object_id() -> None:
    client = MooseBridgeControlClient()
    client.state.apply_message(
        {
            "type": "snapshot",
            "kind": "legions",
            "payload": {
                "legions": [
                    {
                        "object_id": "LEGION:Laage",
                        "dcs_name": "Laage",
                        "object_type": "LEGION",
                        "category": "BRIGADE",
                        "coalition": "blue",
                    }
                ]
            },
        }
    )

    assert normalize_legion_id(client, "BRIGADE:Laage") == "LEGION:Laage"
    assert normalize_legion_id(client, "LEGION:Laage") == "LEGION:Laage"


def test_interactive_mission_feedback_labels_payload_uid_zero() -> None:
    output = io.StringIO()
    recommendation = AuftragRecommendation(
        legion_id="LEGION:Wing Parchim",
        cohort_id="COHORT:F-4E Parchim Alpha",
        constructor="AUFTRAG:NewBAI",
        mission_type="BAI",
        params={"target": "GROUP:Ground-1"},
        distance_nm=63.6,
        selected_payload_uid=0,
        selected_payload_aircrafttype="F-4E-45MC",
        selected_payload_available=1,
    )

    with redirect_stdout(output):
        print_mission_feedback(
            recommendation,
            ack={"ok": True, "result": {"auftrag_id": "AUFTRAG:1"}},
            preview=False,
            debug=False,
        )

    text = output.getvalue().strip()
    assert "payload_uid=0" in text
    assert "payload=0" not in text
    assert "aircraft=F-4E-45MC" in text
    assert "payload_available=1" in text


def test_interactive_trace_argument_parses_modes() -> None:
    assert parse_trace_argument("AUFTRAG:2") == ("summary", "AUFTRAG:2")
    assert parse_trace_argument("--raw AUFTRAG:2") == ("raw", "AUFTRAG:2")
    assert parse_trace_argument("--verbose AUFTRAG:2") == ("verbose", "AUFTRAG:2")


def test_interactive_trace_summary_is_compact() -> None:
    output = io.StringIO()
    trace = {
        "auftrag_id": "AUFTRAG:2",
        "found": True,
        "source": "bridge.tracked",
        "auftrag": {
            "type": "Bombing",
            "status": "requested",
            "summary_available": False,
            "assigned_group_ids": [],
            "target": {
                "category": "Coordinate",
                "name": "MGRS 33U UV 46038 98158",
                "x": -33711.171875,
                "z": -510211,
                "n_destroyed": 0,
                "damage": 0,
            },
        },
        "counts": {"matching_legions": 1, "matching_opsgroups": 0},
        "matching_legion_ids": ["LEGION:Wing Parchim"],
    }

    with redirect_stdout(output):
        print_trace(trace, mode="summary")

    text = output.getvalue()
    assert "TRACE AUFTRAG:2" in text
    assert "type=Bombing" in text
    assert "matching_legions=1" in text
    assert "LEGION:Wing Parchim" in text
    assert '"auftrag"' not in text


def test_control_status_and_state_roundtrip() -> None:
    async def scenario() -> None:
        bridge, server, client = await _with_control_server()
        try:
            bridge.state.apply_message(
                {
                    "type": "snapshot",
                    "kind": "zones",
                    "payload": {
                        "zones": [
                            {
                                "object_id": "ZONE:Alpha",
                                "dcs_name": "Alpha",
                                "object_type": "ZONE",
                            }
                        ]
                    },
                }
            )

            status = await client.status()
            assert status["connected"] is True
            assert status["counts"]["zones"] == 1
            assert "zones" not in status

            state = await client.get_state(kinds=("zones",))
            assert state.zones["ZONE:Alpha"]["dcs_name"] == "Alpha"
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_control_dcs_disconnect_is_not_logged_as_server_error(caplog: Any) -> None:
    class DisconnectingBridge(FakeBridgeServer):
        async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, Any]:
            raise DcsBridgeConnectionError("DCS bridge connection disconnected")

    async def scenario() -> dict[str, Any]:
        control = MooseBridgeControlServer(DisconnectingBridge())  # type: ignore[arg-type]
        return await control._handle_line(
            json.dumps({"id": "ctrl-reconnect", "action": "control.command", "params": {"action": "snapshot.all"}})
        )

    with caplog.at_level(logging.INFO, logger="moosebridge.control"):
        response = asyncio.run(scenario())

    assert response == {
        "id": "ctrl-reconnect",
        "ok": False,
        "error": "DCS bridge connection disconnected",
    }
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert "interrupted by DCS reconnect" in caplog.text


def test_control_snapshots_forwards_actions_and_updates_client_state() -> None:
    async def scenario() -> None:
        bridge, server, client = await _with_control_server()
        try:
            await client.request_snapshots(("snapshot.groups",), timeout=3.0)

            assert [command.action for command, _ in bridge.commands] == ["snapshot.groups"]
            assert bridge.commands[0][1] == 3.0
            assert client.state.groups["GROUP:Blue Armor"]["coalition"] == "blue"
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_control_snapshot_client_timeout_scales_with_action_count() -> None:
    async def scenario() -> None:
        bridge = SlowFakeBridgeServer()
        server = MooseBridgeControlServer(bridge, host="127.0.0.1", port=0)
        await server.start()
        client = MooseBridgeControlClient("127.0.0.1", _control_port(server))
        try:
            await client.request_snapshots(("snapshot.groups", "snapshot.units", "snapshot.zones"), timeout=0.1)

            assert [command.action for command, _ in bridge.commands] == [
                "snapshot.groups",
                "snapshot.units",
                "snapshot.zones",
            ]
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_control_command_forwards_action_params_and_returns_ack() -> None:
    async def scenario() -> None:
        bridge, server, client = await _with_control_server()
        try:
            ack = await client.send_dcs_command("message.to_all", {"text": "hello"}, timeout=4.0)

            command, timeout = bridge.commands[0]
            assert command.action == "message.to_all"
            assert command.params == {"text": "hello"}
            assert timeout == 4.0
            assert ack["result"]["params"] == {"text": "hello"}
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_control_client_wait_for_event_roundtrip() -> None:
    async def scenario() -> None:
        bridge = MooseBridgeServer()
        server = MooseBridgeControlServer(bridge, host="127.0.0.1", port=0)
        await server.start()
        client = MooseBridgeControlClient("127.0.0.1", _control_port(server))
        try:
            task = asyncio.create_task(client.wait_for_event("auftrag.evaluated", filters={"auftrag_id": "AUFTRAG:1"}, timeout=1.0))
            await asyncio.sleep(0)
            await bridge._handle_line(
                '{"type":"event","event":"auftrag.evaluated","payload":{"auftrag_id":"AUFTRAG:1","summary":{"success":true}}}'
            )
            event = await task
            assert event["event"] == "auftrag.evaluated"
            assert client.state.events[-1]["payload"]["auftrag_id"] == "AUFTRAG:1"
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_control_rejects_invalid_snapshot_request() -> None:
    async def scenario() -> None:
        _, server, client = await _with_control_server()
        try:
            try:
                await client.request("control.snapshots", params={"actions": "snapshot.groups"})
            except RuntimeError as exc:
                assert "control.snapshots requires params.actions list" in str(exc)
            else:
                raise AssertionError("control.snapshots accepted a non-list actions value")
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_control_returns_error_for_invalid_json() -> None:
    async def scenario() -> None:
        _, server, client = await _with_control_server()
        try:
            reader, writer = await asyncio.open_connection(client.host, client.port)
            try:
                writer.write(b"not-json\n")
                await writer.drain()
                line = await reader.readline()
                response = json.loads(line.decode("utf-8"))
            finally:
                writer.close()
                await writer.wait_closed()

            assert response["ok"] is False
            assert "Expecting value" in response["error"]
        finally:
            await server.stop()

    asyncio.run(scenario())
