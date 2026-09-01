from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from moosebridge.navaid_menu import (
    NavaidCatalog, NavaidCatalogProvider, NavaidListing, NavaidSelection, PAGE_SIZE, TYPE_LABELS,
    category, station_message,
)
from moosebridge.navigation_menu import NavigationMenuController
from moosebridge.navaids import import_installation
from test_navaids import installation
from test_navigation_menu import Bridge, event


def record(index=1, kind="TACAN", *, warning=False, invalid=False):
    return {"source_index": index, "validation_status": "invalid" if invalid else "review" if warning else "no_issues",
            "issues": [{"code": "unknown_type", "severity": "error"}] if invalid else
                      [{"code": "frequency_channel_conflict", "severity": "warning"}] if warning else [],
            "normalized": {"beacon_id": f"world_{index}", "type_symbol": f"BEACON_TYPE_{kind}",
                           "display_name": f"Station {index}", "callsign": f"T{index}",
                           "position_m": {"x": index * 1000, "y": 0, "z": 0},
                           "position_geo_deg": {"latitude": index / 100, "longitude": 0},
                           "channel": 16, "channel_mode": "X", "channel_mode_source": "default_system_declaration",
                           "frequency_hz": 977000000, "frequency_role": "uhf_dme_tacan"}}


def catalog(count=13):
    return NavaidCatalog("Caucasus", "a" * 64, "2026-08-31", tuple(record(i) for i in range(1, count + 1)))


def position(x=0):
    return SimpleNamespace(x=x, z=0, latitude=x / 100000, longitude=0)


def click(action="navaids_refresh", *, kind="TACAN", revision=0, page=0, station_key=None, **kwargs):
    result = event(action, **kwargs)
    result["payload"].update(navaid_type=kind, navaid_revision=revision, page=page,
                             request_id=str(revision + 1), station_key=station_key)
    return result


def provider(data=None):
    data = data or catalog()
    return SimpleNamespace(get=lambda theater: data if theater == data.theater_id else (_ for _ in ()).throw(ValueError("Wrong terrain")))


def created_menu(**kwargs):
    result = event(**kwargs)
    result["event"] = "player.menu.created"
    result["payload"].pop("action")
    return result


@pytest.mark.parametrize("count", [0, 13, 413])
def test_menu_creation_initializes_all_types_once_from_one_position(count, capsys):
    async def scenario():
        bridge = Bridge()
        bridge.context["opsgroup_id"] = None
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider(catalog(count)))
        await controller.handle(created_menu(owner="foreign"))
        assert not bridge.calls
        await controller.handle(created_menu())
        state = controller.groups[("GROUP:Hornet", "1")]
        assert set(state.navaids) == set(TYPE_LABELS)
        assert len(bridge.positions) == 1
        assert all(listing.position is state.navaids["TACAN"].position for listing in state.navaids.values())
        assert all(listing.revision == 1 and listing.page == 0 for listing in state.navaids.values())
        assert len(state.navaids["TACAN"].records) == count
        assert state.copilot_task is not None
        assert state.route is state.navigator is state.selected_navaid is None
        assert not bridge.routes and not bridge.messages()
        assert not any(command.action.endswith("overlay") for command in bridge.calls)
        batches = [command for command in bridge.calls if command.action.endswith("navaids.initialize")]
        assert len(batches) == 1 and batches[0].params["theater_id"] == "Caucasus"
        assert all(len(page["items"]) <= 6 for page in batches[0].params["types"].values())
        before = len(bridge.calls)
        bridge.x = 50000
        await controller.handle(created_menu())
        assert len(bridge.calls) == before  # Duplicate delivery does not resample.
        if count:
            await controller.handle(click("navaid_details", revision=1, station_key="1"))
            assert "Navaid:" in bridge.messages()[-1]
        await controller.handle(click(revision=1))
        assert state.navaids["TACAN"].position.x == 50000
        await controller.handle(event(closed=True))
        bridge.context["session_id"] = "2"
        await controller.handle(created_menu(session="2"))
        assert len(controller.groups) == 1
        assert controller.groups[("GROUP:Hornet", "2")].navaids["TACAN"].position.x == 50000
        await controller.close()
    asyncio.run(scenario())
    assert "11/11 type lists populated from one position snapshot" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["no_catalog", "wrong_terrain", "multi_aircraft", "position_unavailable",
                                     "mission_end", "changed_unit", "rejected_batch", "bad_ack"])
def test_initialization_failure_is_quiet_and_manual_refresh_remains_available(failure, caplog):
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        original_coords, original_send = bridge.coords, bridge.send_command
        if failure == "no_catalog":
            controller.navaid_catalogs = None
        elif failure == "wrong_terrain":
            bridge.context["theater_id"] = "SinaiMap"
        elif failure == "multi_aircraft":
            bridge.context["group_sessions"].append({"unit_id": "UNIT:Wingman"})
        async def coords(*args, **kwargs):
            if failure == "position_unavailable":
                raise ValueError("Position not ready")
            if failure == "mission_end":
                bridge.state.mission_ended = True
            if failure == "changed_unit":
                bridge.context["group_sessions"] = [{"unit_id": "UNIT:Other"}]
            return await original_coords(*args, **kwargs)
        async def send(command, **kwargs):
            if command.action.endswith("navaids.initialize"):
                if failure == "rejected_batch":
                    raise RuntimeError("Menu session inactive")
                if failure == "bad_ack":
                    return {"ok": True, "result": {"types": {}}}
            return await original_send(command, **kwargs)
        bridge.coords, bridge.send_command = coords, send
        await controller.handle(created_menu())
        state = controller.groups[("GROUP:Hornet", "1")]
        assert state.navaids_initialization_attempted and not state.navaids
        assert not bridge.messages()  # No unsolicited cockpit error spam.
        bridge.coords, bridge.send_command = original_coords, original_send
        bridge.state.mission_ended = False
        bridge.context.update(theater_id="Caucasus", group_sessions=[{"unit_id": "UNIT:Hornet-1"}])
        controller.navaid_catalogs = provider()
        await controller.handle(click())
        assert state.navaids["TACAN"].revision == 1
        await controller.close()
    asyncio.run(scenario())
    if failure != "no_catalog":
        assert "use Refresh nearby" in caplog.text


def test_initialization_only_publishes_acknowledged_types_and_preserves_manual_work():
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        await controller.handle(click())
        await controller.handle(click("navaid_details", revision=1, station_key="1"))
        state = controller.groups[("GROUP:Hornet", "1")]
        listing, selected = state.navaids["TACAN"], state.selected_navaid
        original = bridge.send_command
        async def send(command, **kwargs):
            ack = await original(command, **kwargs)
            if command.action.endswith("navaids.initialize"):
                ack["result"]["types"]["TACAN"] = {"initialized": False}
                ack["result"]["types"]["VOR"] = {"initialized": False, "error": "Mock construction error"}
            return ack
        bridge.send_command = send
        await controller.handle(created_menu())
        assert state.navaids["TACAN"] is listing and state.selected_navaid is selected
        assert "VOR" not in state.navaids and len(state.navaids) == 10
        await controller.handle(click(kind="VOR", revision=2))
        assert state.navaids["VOR"].revision == 3
        await controller.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("symbol,expected", [
    ("TACAN", "TACAN"), ("VOR_DME", "VOR_DME"), ("VORTAC", "VORTAC"), ("DME", "DME"),
    ("ILS_LOCALIZER", "ILS"), ("ILS_GLIDESLOPE", "ILS"), ("ILS_FAR_HOMER", "NDB"),
    ("PRMG_LOCALIZER", "PRMG"), ("ICLS_GLIDESLOPE", "ICLS"), ("RSBN", "RSBN"),
    ("AIRPORT_TACAN", "OTHER"), ("BROADCAST_STATION", "OTHER"),
])
def test_type_families_do_not_guess_unknown_tacan(symbol, expected):
    assert category("BEACON_TYPE_" + symbol) == expected
    assert expected in TYPE_LABELS


@pytest.mark.parametrize("count", [0, 1, 6, 7, 12, 13, 164, 413])
def test_all_stations_are_accessible_within_page_budget(count):
    data = catalog(count)
    rows, excluded = data.nearby("TACAN", position())
    listing = NavaidListing(data, "UNIT:A", rows, position(), excluded)
    keys = []
    for page in range(listing.pages):
        items = listing.page_items(page)
        # Stations + refresh + prev/next + reserved DCS back slot.
        assert len(items) + 1 + (page > 0) + (page + 1 < listing.pages) + 1 <= 10
        assert len(items) <= PAGE_SIZE
        keys.extend(item["key"] for item in items)
    assert keys == [str(i) for i in range(1, count + 1)]


def test_coordinate_failures_are_omitted_but_data_issues_remain_marked():
    first, second, third = record(1, warning=True), record(2), record(3, kind="AIRPORT_TACAN", invalid=True)
    second["normalized"]["position_geo_deg"] = None
    data = NavaidCatalog("Caucasus", "a" * 64, "now", (first, second, third))
    rows, excluded = data.nearby("TACAN", position())
    listing = NavaidListing(data, "UNIT:A", rows, position(), excluded)
    assert len(rows) == 1 and excluded == 1 and "[!]" in listing.page_items(0)[0]["label"]
    other, _ = data.nearby("OTHER", position())
    message = station_message(listing, other[0], position())
    assert "DATA INVALID" in message and "not tuning recommendations" in message
    assert "receivable or aircraft-compatible" in message


def test_long_unicode_names_and_ils_components_are_preserved_in_details():
    data = record(kind="ILS_GLIDESLOPE")
    data["normalized"]["display_name"] = "Küstenpunkt" * 30
    original = deepcopy(data)
    listing = NavaidListing(catalog(), "UNIT:Überflug", (data,), position(), 0)
    label = listing.page_items(0)[0]["label"]
    assert "GS" in label and len(label.encode("utf-8")) <= 110
    text = station_message(listing, data, position())
    assert "Reference: Überflug" in text and data["normalized"]["display_name"] in text
    assert data == original


def test_provider_checks_hashes_selects_exact_terrain_and_pins(installation, tmp_path):
    output = tmp_path / "cache"
    first = import_installation(installation, output)
    store = NavaidCatalogProvider(output, installation)
    loaded = store.get("ExampleTerrain")
    assert len(loaded.records) == 1 and loaded.snapshot_id == first["snapshot_id"]
    assert not store.get("Empty").records
    with pytest.raises(ValueError, match="active terrain"):
        store.get("ExampleFolder")  # Folder names are not mission terrain IDs.
    path = installation / "Mods/terrains/ExampleFolder/Beacons.lua"
    path.write_text(path.read_text(encoding="utf-8") + "\n-- new source\n", encoding="utf-8")
    assert store.get("ExampleTerrain") is loaded  # No hot replacement during this run.
    with pytest.raises(ValueError, match="outdated"):
        NavaidCatalogProvider(output, installation).get("ExampleTerrain")


@pytest.mark.parametrize("failure", ["missing", "corrupt", "traversal"])
def test_provider_rejects_unusable_cache(installation, tmp_path, failure):
    output = tmp_path / "cache"
    if failure != "missing":
        imported = import_installation(installation, output)
        if failure == "corrupt":
            Path(imported["report_path"]).write_text("bad", encoding="utf-8")
        else:
            (output / "current.json").write_text(json.dumps({"snapshot_id": "../../escape"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Run import_dcs_beacons.py"):
        NavaidCatalogProvider(output, installation).get("ExampleTerrain")


def test_refresh_page_details_use_normal_group_commands_without_flightgroup(capsys):
    async def scenario():
        bridge = Bridge()
        bridge.context["opsgroup_id"] = None
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        await controller.handle(click())
        state = controller.groups[("GROUP:Hornet", "1")]
        listing = state.navaids["TACAN"]
        assert listing.revision == 1 and listing.page == 0
        assert state.route is None and state.navigator is None and state.copilot_task is None
        bridge.x = 50000
        await controller.handle(click("navaids_page", revision=1, page=1))
        pages = [command for command in bridge.calls if command.action.endswith("navaids.page")]
        assert pages[-1].params["items"][0]["key"] == "7"  # Retain order until refresh.
        assert pages[-1].params["theater_id"] == "Caucasus"
        await controller.handle(click("navaid_details", revision=2, page=1, station_key="7"))
        assert "23.22 NM" in bridge.messages()[-1]  # Fresh 43 km distance, not old list distance.
        assert "180.0 deg TRUE" in bridge.messages()[-1]
        assert "Source channel: 16X" in bridge.messages()[-1]
        message = bridge.calls[-1]
        assert message.params["unit_id"] == "UNIT:Hornet-1" and message.params["navaid_revision"] == 2
        assert bridge.messages()[-1] in capsys.readouterr().out
        assert not bridge.routes
        await controller.handle(click(revision=2))
        assert state.navaids["TACAN"].records[0]["source_index"] == 13  # Fresh nearest order.
        await controller.handle(event(closed=True))
        assert not controller.groups
        await controller.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["wrong_terrain", "missing_theater", "multi_aircraft", "changed_unit", "mission_end", "wrong_position"])
def test_invalid_live_reference_never_builds_a_station_page(failure):
    async def scenario():
        bridge = Bridge()
        original = bridge.coords
        if failure == "wrong_terrain":
            bridge.context["theater_id"] = "Nevada"
        elif failure == "missing_theater":
            bridge.context.pop("theater_id")
        elif failure == "multi_aircraft":
            bridge.context["group_sessions"].append({"unit_id": "UNIT:Wingman"})

        async def coords(*args, **kwargs):
            if failure == "changed_unit":
                bridge.context["group_sessions"] = [{"unit_id": "UNIT:Other"}]
            if failure == "mission_end":
                bridge.state.reset_mission()
            return await original("UNIT:Other" if failure == "wrong_position" else args[0], **kwargs)
        bridge.coords = coords
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        await controller.handle(click())
        assert not any(command.action.endswith("navaids.page") for command in bridge.calls)
        assert not controller.groups[("GROUP:Hornet", "1")].navaids
        await controller.close()
    asyncio.run(scenario())


def test_stale_details_off_page_keys_and_foreign_owner_do_not_emit_station_data(capsys):
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        await controller.handle(click(owner="foreign"))
        assert not bridge.calls
        await controller.handle(click())
        await controller.handle(click("navaid_details", revision=0, station_key="1"))
        await controller.handle(click("navaid_details", revision=1, station_key="12"))
        assert not any(text.startswith("Navaid:") for text in bridge.messages())
        assert "Navaid:" not in capsys.readouterr().out
        await controller.close()
    asyncio.run(scenario())


def test_empty_type_retains_refresh_and_gives_clear_feedback():
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        await controller.handle(click(kind="DME"))
        command = next(command for command in bridge.calls if command.action.endswith("navaids.page"))
        assert command.params["items"] == [] and command.params["pages"] == 1
        assert "DME: page 1/1, 0 entries" in bridge.messages()[-1]
        await controller.close()
    asyncio.run(scenario())


def map_click(action="navaid_show", token="1", **kwargs):
    result = event(action, **kwargs)
    result["payload"]["selection_id"] = token
    return result


def test_map_actions_are_explicit_and_independent_of_route_paging_and_hints():
    async def scenario():
        bridge = Bridge()
        bridge.context["opsgroup_id"] = None
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        await controller.handle(click())
        await controller.handle(click("navaid_details", revision=1, station_key="1"))
        state = controller.groups[("GROUP:Hornet", "1")]
        selected = state.selected_navaid
        assert selected.record["source_index"] == 1
        assert "Map unchanged" in bridge.messages()[-1]
        assert not any(c.action.endswith(".overlay") for c in bridge.calls)
        await controller.handle(map_click())
        await controller.handle(map_click("navaid_show_line"))
        overlays = [c for c in bridge.calls if c.action.endswith("navaids.overlay")]
        assert [c.params["bearing_line"] for c in overlays] == [False, True]
        for c in overlays:
            assert c.params["show"] is True and c.params["selection_id"] == "1"
            assert c.params["unit_id"] == "UNIT:Hornet-1" and c.params["theater_id"] == "Caucasus"
            assert c.params["point"] == {"latitude": .01, "longitude": 0, "altitude": 0}
            assert "TACAN" in c.params["text"] and "16X" in c.params["text"]
            assert "coalition" not in c.params and "overlay_id" not in c.params
        assert "does not track movement" in bridge.messages()[-1]
        assert "own coalition" in bridge.messages()[-1]
        await controller.handle(click("navaids_page", revision=1, page=1))
        assert state.selected_navaid is selected
        await controller.handle(map_click())
        await controller.handle(click(revision=2))
        assert state.selected_navaid is selected
        await controller.handle(click("navaid_details", revision=3, station_key="2"))
        assert state.selected_navaid.record["source_index"] == 2
        # Browsing another station does not replace the currently drawn station.
        overlays = [c for c in bridge.calls if c.action.endswith("navaids.overlay")]
        assert len(overlays) == 3 and overlays[-1].params["point"]["latitude"] == .01
        await controller.handle(map_click(token="2"))
        assert next(c for c in reversed(bridge.calls) if c.action.endswith("navaids.overlay")).params["point"]["latitude"] == .02
        await controller.handle(map_click("navaid_hide"))
        assert state.selected_navaid.record["source_index"] == 2
        assert not bridge.routes and state.route is None and state.copilot_task is None and state.navigator is None
        await controller.handle(event(closed=True))
        assert not controller.groups
        await controller.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["no_selection", "stale_token", "wrong_terrain", "changed_unit",
                                     "ambiguous", "dead_session", "mission_end", "draw_failure"])
def test_invalid_map_actions_do_not_draw_or_report_success(failure, capsys):
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        if failure != "no_selection":
            await controller.handle(click())
            await controller.handle(click("navaid_details", revision=1, station_key="1"))
        if failure == "wrong_terrain":
            bridge.context["theater_id"] = "Nevada"
        elif failure == "changed_unit":
            bridge.context["group_sessions"] = [{"unit_id": "UNIT:Other"}]
        elif failure == "ambiguous":
            bridge.context["group_sessions"].append({"unit_id": "UNIT:Wingman"})
        elif failure == "mission_end":
            bridge.state.reset_mission()
        original = bridge.send_command
        async def send(command, **kwargs):
            if failure == "dead_session" or (failure == "draw_failure" and command.action.endswith("navaids.overlay")):
                raise RuntimeError("Draw rejected")
            return await original(command, **kwargs)
        bridge.send_command = send
        await controller.handle(map_click(token="old" if failure == "stale_token" else "1"))
        assert not any(c.action.endswith("navaids.overlay") for c in bridge.calls)
        assert not any(text.startswith("F10 navaid displayed:") for text in bridge.messages())
        assert "F10 navaid displayed:" not in capsys.readouterr().out
        await controller.close()
    asyncio.run(scenario())


def test_hiding_requires_neither_selection_catalog_nor_single_aircraft():
    async def scenario():
        bridge = Bridge()
        bridge.context["group_sessions"] = []
        controller = NavigationMenuController(bridge, "run")
        await controller.handle(map_click("navaid_hide", token=None))
        await controller.handle(map_click("navaid_hide", token=None))
        overlays = [c for c in bridge.calls if c.action.endswith("navaids.overlay")]
        assert len(overlays) == 2 and all(c.params["show"] is False for c in overlays)
        assert not bridge.positions
        await controller.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["rejected", "missing_token", "lost_ack"])
def test_failed_details_do_not_select_a_new_station(failure):
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        await controller.handle(click())
        original = bridge.send_command
        async def send(command, **kwargs):
            if command.params.get("station_key"):
                if failure == "lost_ack":
                    raise TimeoutError("Lost selection ACK")
                if failure == "rejected":
                    raise RuntimeError("Stale selection")
                return {"ok": True, "result": {}}
            return await original(command, **kwargs)
        bridge.send_command = send
        await controller.handle(click("navaid_details", revision=1, station_key="1"))
        assert controller.groups[("GROUP:Hornet", "1")].selected_navaid is None
        await controller.close()
    asyncio.run(scenario())


def test_map_selections_are_isolated_between_group_sessions():
    async def scenario():
        bridge = Bridge()
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider())
        await controller.handle(click())
        await controller.handle(click("navaid_details", revision=1, station_key="1"))
        first = controller.groups[("GROUP:Hornet", "1")].selected_navaid
        bridge.context.update(group_id="GROUP:Other", session_id="2", group_sessions=[{"unit_id": "UNIT:Other-1"}])
        await controller.handle(click(group="Other", session="2"))
        await controller.handle(click("navaid_details", revision=1, station_key="2", group="Other", session="2"))
        second = controller.groups[("GROUP:Other", "2")].selected_navaid
        assert first.record["source_index"] == 1 and second.record["source_index"] == 2
        await controller.handle(map_click(token=second.selection_id, group="Other", session="2"))
        command = next(c for c in reversed(bridge.calls) if c.action.endswith("navaids.overlay"))
        assert command.params["group_id"] == "GROUP:Other" and command.params["unit_id"] == "UNIT:Other-1"
        await controller.handle(event(closed=True))
        assert controller.groups[("GROUP:Other", "2")].selected_navaid is second
        await controller.close()
    asyncio.run(scenario())


def test_marker_labels_preserve_warnings_and_utf8_bounds_without_mutating_sources():
    row = record(warning=True)
    row["normalized"]["display_name"] = "Ü" * 200 + "\x00\t"
    original = deepcopy(row)
    selected = NavaidSelection(catalog(), row, "UNIT:A", "1")
    label = selected.marker_text("GROUP:" + "長" * 80)
    assert len(label.encode("utf-8")) <= 180 and label.startswith("[!]")
    assert "16X [default]" in label and "977 MHz" in label
    assert "\x00" not in label and "\t" not in label
    assert row == original
