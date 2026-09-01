from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from moosebridge.airfield_radio import (
    AirfieldRadioListing, airfield_radio_message, resolve_airfield_radios,
)
from moosebridge.navaid_menu import NavaidCatalog
from moosebridge.navigation_menu import NavigationMenuController
from test_navigation_menu import Bridge, event


def radio_record(index: int, uid: int | None, *, callsign="Tower", frequencies=True, warning=False):
    issues = ([{"severity": "warning", "code": "missing_radio_frequencies"}]
              if warning else [])
    return {
        "source_index": index,
        "validation_status": "review" if warning else "no_issues",
        "issues": issues,
        "normalized": {
            "radio_id": f"airfield{uid}_0" if uid is not None else "CustomTower",
            "airbase_uid": uid,
            "roles": ["ground", "tower", "approach"],
            "callsigns": [{"variant": "common", "translation_key": callsign, "name": callsign}],
            "frequencies": ([
                {"band_symbol": "UHF", "modulation_symbol": "MODULATIONTYPE_AM",
                 "frequency_hz": 250_500_000},
                {"band_symbol": "VHF_HI", "modulation_symbol": "MODULATIONTYPE_AM",
                 "frequency_hz": 118_450_000},
            ] if frequencies else []),
        },
    }


def airbase(uid: int, name: str, x: float):
    return {"airbase_id": uid, "name": name, "dcs_name": name, "object_id": f"AIRBASE:{name}",
            "x": x, "y": 0, "z": 0, "latitude": x / 100_000, "longitude": 0}


def catalog(*records):
    return NavaidCatalog("Caucasus", "b" * 64, "2026-09-01", (), radio_records=tuple(records))


def position(x=0):
    return SimpleNamespace(x=x, z=0, latitude=x / 100_000, longitude=0)


def provider(data):
    return SimpleNamespace(get=lambda theater: data if theater == data.theater_id else
                           (_ for _ in ()).throw(ValueError("Wrong terrain")))


def created_menu():
    result = event()
    result["event"] = "player.menu.created"
    result["payload"].pop("action")
    return result


def click(action, *, revision=1, page=0, station_key=None):
    result = event(action)
    result["payload"].update(airfield_revision=revision, page=page,
                             request_id=str(revision + 1), station_key=station_key)
    return result


def test_uid_join_never_falls_back_to_names_and_preserves_source_issues():
    data = catalog(radio_record(1, 42), radio_record(2, 77, warning=True), radio_record(3, None))
    stations, unresolved = resolve_airfield_radios(data, [airbase(42, "Different source name", 10_000)])
    assert [station.airbase_uid for station in stations] == [42]
    assert stations[0].name == "Different source name"
    assert unresolved == 2
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_airfield_radios(data, [airbase(42, "One", 0), airbase(42, "Two", 1)])


def test_listing_orders_live_airbases_and_formats_readable_atc_details():
    data = catalog(radio_record(1, 42, callsign="Batumi"), radio_record(2, 77, frequencies=False, warning=True))
    stations, unresolved = resolve_airfield_radios(data, [airbase(42, "Batumi", 1_000), airbase(77, "Kutaisi", 20_000)])
    listing = AirfieldRadioListing(data, "UNIT:Hornet-1", stations, position(), unresolved)
    assert listing.page_items(0)[0]["label"].startswith("1. Batumi")
    assert "[!] Kutaisi" in listing.page_items(0)[1]["label"]
    text = airfield_radio_message(listing, listing.selected("1"), position())
    assert "Airfield communications: Batumi" in text
    assert "Callsigns: Common Batumi" in text
    assert "ATC roles: Ground, Tower, Approach" in text
    assert "UHF: 250.5 MHz AM" in text and "VHF: 118.45 MHz AM" in text
    assert "shared ATC alternatives, not role-specific" in text and "Cockpit unchanged" in text


def test_controller_initializes_refreshes_pages_and_shows_airfield_details(capsys):
    async def scenario():
        data = catalog(*(radio_record(index, 40 + index) for index in range(1, 9)),
                       radio_record(9, None))
        bridge = Bridge()
        bridge.airbases = [airbase(40 + index, f"Airfield {index}", index * 1_000) for index in range(1, 9)]
        controller = NavigationMenuController(bridge, "run", navaid_catalogs=provider(data))
        await controller.handle(created_menu())
        state = controller.groups[("GROUP:Hornet", "1")]
        assert state.airfields is not None and state.airfields.revision == 1
        assert len(state.airfields.stations) == 8 and state.airfields.unresolved == 1
        initial = [call for call in bridge.calls if call.action.endswith("airfields.initialize")]
        assert len(initial) == 1 and len(initial[0].params["items"]) == 6
        await controller.handle(click("airfield_details", station_key="1"))
        assert "Airfield communications: Airfield 1" in bridge.messages()[-1]
        await controller.handle(click("airfields_page", page=1))
        assert state.airfields.revision == 2 and state.airfields.page == 1
        bridge.x = 50_000
        await controller.handle(click("airfields_refresh", revision=2))
        assert state.airfields.revision == 3 and state.airfields.page == 0
        assert "AIRBASE objects resolved live" in bridge.messages()[-1]
        await controller.close()
    asyncio.run(scenario())
    assert "Airfields / ATC initialized" in capsys.readouterr().out
