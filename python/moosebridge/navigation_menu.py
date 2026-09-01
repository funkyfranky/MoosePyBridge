"""Group-scoped navigation radio actions over the normal bridge control API.

Lua owns menu/overlay lifetimes and validates an entry token before every write.
Python owns route calculations. No cockpit waypoints or aircraft tasks change.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import math
from typing import Any, TYPE_CHECKING

from .airfield_radio import AirfieldRadioListing, airfield_radio_message, resolve_airfield_radios
from .flight_routes import FlightGroupRoute
from .flight_status import FlightStatus, format_flight_status
from .navaid_menu import NavaidCatalogProvider, NavaidListing, NavaidSelection, TYPE_LABELS, station_message, validate_position
from .navigation import NavigationSolution, RouteNavigator, format_navigation_status
from .protocol import BridgeCommand
from .sdk import require_ok

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


ERRORS = (ConnectionError, OSError, RuntimeError, TimeoutError, ValueError)


async def configure_navigation_menu(
    bridge: MooseBridgeClient, owner_id: str, *, enabled: bool, timeout: float = 10,
    expected_instance_id: str | None = None,
) -> dict[str, Any]:
    params = {"owner_id": owner_id, "enabled": enabled}
    if expected_instance_id is not None:
        params["expected_instance_id"] = expected_instance_id
    return require_ok(await bridge.server.send_command(BridgeCommand(
        action="player.menu.navigation.configure", params=params,
    ), timeout=timeout))


@dataclass
class GroupNavigation:
    group_id: str
    session_id: str
    route: FlightGroupRoute | None = None
    navigator: RouteNavigator | None = None
    unit_id: str | None = None
    hints: asyncio.Task[None] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    navaids: dict[str, NavaidListing] = field(default_factory=dict)
    selected_navaid: NavaidSelection | None = None
    navaids_initialization_attempted: bool = False
    airfields: AirfieldRadioListing | None = None
    airfields_initialization_attempted: bool = False


def reference_unit(context: dict[str, Any]) -> str:
    """Multicrew in one aircraft is unambiguous; multiple aircraft are not."""
    units = {item["unit_id"] for item in context.get("group_sessions", []) if item.get("unit_id")}
    if len(units) != 1:
        raise ValueError("Navigation requires exactly one player aircraft per group.")
    return next(iter(units))


def cockpit_status(unit_id: str, solution: NavigationSolution) -> str:
    bearing = "N/A" if solution.bearing_true_deg is None else f"{solution.bearing_true_deg:.1f} deg TRUE"
    cross_track = "N/A" if solution.cross_track_m is None else (
        f"{abs(solution.cross_track_m):.0f} m {solution.cross_track_side}"
    )
    text = (
        f"Navigation status | Reference: {unit_id.removeprefix('UNIT:')}\n"
        f"Leg: WP {solution.from_waypoint_index} -> WP {solution.target_waypoint_index} | "
        f"Target: {solution.target_name}\n"
        f"Distance: {solution.distance_nm:.2f} NM | Bearing: {bearing}\n"
        f"Cross-track error: {cross_track}"
    )
    if solution.route_complete:
        text += "\nRoute complete horizontally; landing status not checked."
    return text


class NavigationMenuController:
    """One route tracker per occupied group-menu session, opt-in periodic hints."""

    def __init__(
        self, bridge: MooseBridgeClient, owner_id: str, *, sample_interval: float = 2,
        hint_interval: float = 10, timeout: float = 10, initial_target: int = 2,
        capture_radius_m: float = 500, max_sample_gap_s: float = 10,
        navaid_catalogs: NavaidCatalogProvider | None = None,
        navaid_error: str | None = None,
    ) -> None:
        for name, value in (("sample_interval", sample_interval), ("hint_interval", hint_interval),
                            ("timeout", timeout), ("capture_radius_m", capture_radius_m),
                            ("max_sample_gap_s", max_sample_gap_s)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if type(initial_target) is not int or initial_target < 2:
            raise ValueError("initial_target must be an integer >= 2")
        self.bridge, self.owner_id = bridge, owner_id
        self.sample_interval, self.hint_interval, self.timeout = sample_interval, hint_interval, timeout
        self.initial_target, self.capture_radius_m = initial_target, capture_radius_m
        self.max_sample_gap_s = max_sample_gap_s
        self.groups: dict[tuple[str, str], GroupNavigation] = {}
        self.navaid_catalogs = navaid_catalogs
        self.navaid_error = navaid_error

    async def _call(self, state: GroupNavigation, operation: str, **params: Any) -> dict[str, Any]:
        if self.bridge.state.mission_ended:
            raise ConnectionError("DCS mission ended.")
        ack = require_ok(await self.bridge.server.send_command(BridgeCommand(
            action=f"player.menu.navigation.{operation}",
            params={**params, "owner_id": self.owner_id,
                    "group_id": state.group_id, "session_id": state.session_id},
        ), timeout=self.timeout))
        if self.bridge.state.mission_ended:
            raise ConnectionError("DCS mission ended.")
        result = ack.get("result")
        if not isinstance(result, dict):
            raise ValueError("Invalid navigation menu response")
        return result

    async def _reply(self, state: GroupNavigation, text: str, *, unit_id: str | None = None,
                     duration_s: float | None = None) -> None:
        # Lua bounds bytes, not Unicode characters (player/waypoint names vary).
        bounded = text.encode("utf-8")[:1900].decode("utf-8", errors="ignore")
        params = {"text": bounded}
        if unit_id is not None:
            params["unit_id"] = unit_id
        if duration_s is not None:
            params["duration_s"] = duration_s
        await self._call(state, "message", **params)

    async def _context(self, state: GroupNavigation) -> dict[str, Any]:
        result = await self._call(state, "context")
        if (result.get("group_id"), result.get("session_id"), result.get("owner_id")) != (
            state.group_id, state.session_id, self.owner_id,
        ):
            raise ValueError("Navigation context belongs to another menu session")
        return result

    async def _route(self, state: GroupNavigation, context: dict[str, Any]) -> FlightGroupRoute:
        opsgroup_id = context.get("opsgroup_id")
        if not opsgroup_id:
            raise ValueError("No FLIGHTGROUP available. Please create it in the mission.")
        if state.route is None or state.route.opsgroup_id != opsgroup_id:
            state.route = await self.bridge.get_flightgroup_route(
                opsgroup_id, route_source="mission_editor", timeout=self.timeout,
            )
            state.navigator = None
        return state.route

    async def _sample(self, state: GroupNavigation) -> NavigationSolution:
        context = await self._context(state)
        unit_id = reference_unit(context)
        route = await self._route(state, context)
        position = await self.bridge.coords(unit_id, format="ll", timeout=self.timeout)
        if position.object_id != unit_id:
            raise ValueError("Received coordinates for a different aircraft")
        # A leave/respawn during an awaited query must not advance the old track.
        current = await self._context(state)
        if reference_unit(current) != unit_id or current.get("opsgroup_id") != context.get("opsgroup_id"):
            state.navigator = None
            raise ValueError("Player aircraft changed; please request status again.")
        if state.navigator is None or state.unit_id != unit_id:
            state.navigator = RouteNavigator(
                route, initial_target_index=self.initial_target,
                capture_radius_m=self.capture_radius_m, max_sample_gap_s=self.max_sample_gap_s,
            )
        state.unit_id = unit_id
        solution = state.navigator.update(
            x=position.x, z=position.z, latitude=position.latitude, longitude=position.longitude,
            mission_time=(position.ack or {}).get("mission_time"),
        )
        print(f"{state.group_id}: {format_navigation_status(solution)}", flush=True)
        return solution

    async def _stop_hints(self, state: GroupNavigation) -> None:
        task, state.hints = state.hints, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _catalog_position(self, state: GroupNavigation, subject: str):
        context = await self._context(state)
        unit_id = reference_unit(context)
        theater = context.get("theater_id")
        if not isinstance(theater, str) or not theater:
            raise ValueError("DCS did not identify the active terrain.")
        position = await self.bridge.coords(unit_id, format="ll", timeout=self.timeout)
        current = await self._context(state)
        if (position.object_id != unit_id or reference_unit(current) != unit_id
                or current.get("theater_id") != theater):
            raise ValueError(f"{subject} reference aircraft or terrain changed; use Refresh nearby.")
        validate_position(position)
        return unit_id, theater, position

    async def _initialize_navaids(self, state: GroupNavigation) -> None:
        if state.navaids_initialization_attempted:
            return
        state.navaids_initialization_attempted = True
        if self.navaid_catalogs is None:
            return  # The application already reports unavailable catalogs at startup.
        unit_id, theater, position = await self._catalog_position(state, "Navaid")
        catalog = self.navaid_catalogs.get(theater)
        listings, pages = {}, {}
        for kind in TYPE_LABELS:
            records, excluded = catalog.nearby(kind, position)
            listing = NavaidListing(catalog, unit_id, records, position, excluded)
            listings[kind] = listing
            pages[kind] = {"page": 0, "pages": listing.pages, "items": listing.page_items(0)}
        response = await self._call(state, "navaids.initialize", unit_id=unit_id, theater_id=theater, types=pages)
        results = response.get("types")
        if not isinstance(results, dict) or results.keys() != listings.keys():
            raise ValueError("Invalid navaid initialization acknowledgement; use Refresh nearby.")
        # Validate all acknowledgements before publishing local listings.
        for result in results.values():
            if (not isinstance(result, dict) or type(result.get("initialized")) is not bool
                    or (result["initialized"] and (result.get("navaid_revision") != 1 or result.get("page") != 0))):
                raise ValueError("Invalid navaid initialization acknowledgement; use Refresh nearby.")
        initialized = 0
        for kind, result in results.items():
            if result["initialized"]:
                listings[kind].revision = 1
                state.navaids[kind] = listings[kind]
                initialized += 1
            elif result.get("error"):
                logging.warning("%s: %s initialization failed: %s; use Refresh nearby.",
                                state.group_id, TYPE_LABELS[kind], result["error"])
        print(f"{state.group_id}: Navaids initialized for {unit_id.removeprefix('UNIT:')} "
              f"on {theater}: {initialized}/{len(listings)} type lists populated "
              "from one position snapshot. Use Refresh nearby to update a type.", flush=True)

    async def _navaid_action(self, state: GroupNavigation, payload: dict) -> None:
        kind, revision = payload.get("navaid_type"), payload.get("navaid_revision")
        if not isinstance(kind, str) or kind not in TYPE_LABELS or type(revision) is not int or revision < 0:
            raise ValueError("Invalid navaid menu event")
        if self.navaid_catalogs is None:
            raise ValueError(self.navaid_error or "Navaid catalog is not configured for this navigation script.")
        unit_id, theater, position = await self._catalog_position(state, "Navaid")
        action = payload["action"]
        if action == "navaids_refresh":
            catalog = self.navaid_catalogs.get(theater)
            records, excluded = catalog.nearby(kind, position)
            listing = NavaidListing(catalog, unit_id, records, position, excluded)
            page = 0
        else:
            listing = state.navaids.get(kind)
            if (listing is None or listing.revision != revision or listing.unit_id != unit_id
                    or listing.catalog.theater_id != theater):
                raise ValueError("Navaid list is stale; use Refresh nearby.")
            page = payload.get("page")
        if action == "navaid_details":
            record = listing.selected(payload.get("station_key"))
            text = station_message(listing, record, position)
            text += "\nMap unchanged. Use Navaids > Selected station to show this station on F10."
        else:
            response = await self._call(state, "navaids.page", navaid_type=kind, navaid_revision=revision,
                                        request_id=payload.get("request_id"), unit_id=unit_id, theater_id=theater,
                                        page=page, pages=listing.pages, items=listing.page_items(page))
            if response.get("navaid_revision") != revision + 1:
                raise ValueError("Invalid navaid page acknowledgement; use Refresh nearby.")
            listing.revision, listing.page = revision + 1, page
            state.navaids[kind] = listing
            text = (f"{TYPE_LABELS[kind]}: page {page + 1}/{listing.pages}, {len(listing.records)} entries.\n"
                    "Reopen this type submenu to select a station. Order/distances are from initialization or the last refresh.\n"
                    f"[!] = source data needs review. {listing.excluded} entries omitted for missing coordinates.\n"
                    f"Catalog: {theater}, {listing.catalog.snapshot_id[:12]} (pinned; local sources checked at load).\n"
                    "Nearby does not mean receivable or aircraft-compatible.")
        bounded = text.encode("utf-8")[:1900].decode("utf-8", errors="ignore")
        extra = {"station_key": payload.get("station_key")} if action == "navaid_details" else {}
        response = await self._call(state, "message", text=bounded, unit_id=unit_id, theater_id=theater,
                                    navaid_type=kind, navaid_revision=listing.revision, **extra)
        if action == "navaid_details":
            token = response.get("selection_id")
            if not isinstance(token, str) or not token:
                state.selected_navaid = None
                raise ValueError("Navaid selection was not acknowledged; select the station again.")
            state.selected_navaid = NavaidSelection(listing.catalog, record, unit_id, token)
        print(f"{state.group_id}: {bounded}", flush=True)

    async def _navaid_map_action(self, state: GroupNavigation, payload: dict) -> None:
        if payload["action"] == "navaid_hide":
            # Hiding must work even if no station or single aircraft is selected.
            await self._call(state, "navaids.overlay", show=False)
            await self._reply(state, "Navaid marker and bearing line hidden. Route display unchanged.")
            return
        selected = state.selected_navaid
        if selected is None or payload.get("selection_id") != selected.selection_id:
            raise ValueError("Select a station first, then use Navaids > Selected station.")
        unit_id, theater, _ = await self._catalog_position(state, "Navaid")
        if unit_id != selected.unit_id or theater != selected.catalog.theater_id:
            raise ValueError("Navaid reference aircraft or terrain changed; select a station again.")
        guard = {"unit_id": unit_id, "theater_id": theater, "selection_id": selected.selection_id}
        line = payload["action"] == "navaid_show_line"
        await self._call(state, "navaids.overlay", show=True, bearing_line=line,
                         point=selected.marker_point(), text=selected.marker_text(state.group_id), **guard)
        value = selected.record["normalized"]
        name = value.get("display_name") or value.get("beacon_id") or "Unnamed"
        text = (f"F10 navaid displayed: {value.get('callsign') or '---'} | {name} (own coalition).\n"
                "Amber symbol marks the source position, not reception range.\n")
        if line:
            text += "Bearing line uses aircraft position at display time; it does not track movement.\n"
        text += "Route and cockpit unchanged. Source data does not prove reception or compatibility."
        bounded = text.encode("utf-8")[:1900].decode("utf-8", errors="ignore")
        await self._call(state, "message", text=bounded, **guard)
        print(f"{state.group_id}: {bounded}", flush=True)

    async def _airfield_listing(self, state: GroupNavigation, unit_id: str, theater: str,
                                position: Any) -> AirfieldRadioListing:
        if self.navaid_catalogs is None:
            raise ValueError(self.navaid_error or "Airfield radio catalog is not configured for this navigation script.")
        catalog = self.navaid_catalogs.get(theater)
        airbase_ids = sorted({record.get("normalized", {}).get("airbase_uid")
                              for record in catalog.radio_records
                              if type(record.get("normalized", {}).get("airbase_uid")) is int})
        response = await self._call(state, "airfields.resolve", unit_id=unit_id, theater_id=theater,
                                    airbase_ids=airbase_ids)
        if response.get("theater_id") != theater or not isinstance(response.get("unresolved_airbase_ids"), list):
            raise ValueError("Invalid live AIRBASE resolution response")
        stations, unresolved = resolve_airfield_radios(catalog, response.get("airbases"))
        expected_unresolved = sorted(set(airbase_ids).difference(station.airbase_uid for station in stations))
        if response["unresolved_airbase_ids"] != expected_unresolved:
            raise ValueError("Live AIRBASE resolution acknowledgement is inconsistent")
        return AirfieldRadioListing(catalog, unit_id, stations, position, unresolved)

    async def _initialize_airfields(self, state: GroupNavigation,
                                    reference: tuple[str, str, Any] | None = None) -> None:
        if state.airfields_initialization_attempted:
            return
        state.airfields_initialization_attempted = True
        if self.navaid_catalogs is None:
            return
        unit_id, theater, position = reference or await self._catalog_position(state, "Airfield")
        listing = await self._airfield_listing(state, unit_id, theater, position)
        response = await self._call(state, "airfields.initialize", unit_id=unit_id, theater_id=theater,
                                    page=0, pages=listing.pages, items=listing.page_items(0))
        if response.get("initialized") is not True:
            return  # A manual request made during initialization wins.
        if response.get("airfield_revision") != 1 or response.get("page") != 0:
            raise ValueError("Invalid airfield initialization acknowledgement; use Refresh nearby.")
        listing.revision = 1
        state.airfields = listing
        print(f"{state.group_id}: Airfields / ATC initialized for {unit_id.removeprefix('UNIT:')} "
              f"on {theater}: {len(listing.stations)} live AIRBASE matches, {listing.unresolved} unresolved radio records. "
              "Use Refresh nearby to update the order.", flush=True)

    async def _airfield_action(self, state: GroupNavigation, payload: dict) -> None:
        revision = payload.get("airfield_revision")
        if type(revision) is not int or revision < 0:
            raise ValueError("Invalid airfield menu event")
        unit_id, theater, position = await self._catalog_position(state, "Airfield")
        action = payload["action"]
        if action == "airfields_refresh":
            listing = await self._airfield_listing(state, unit_id, theater, position)
            page = 0
        else:
            listing = state.airfields
            if (listing is None or listing.revision != revision or listing.unit_id != unit_id
                    or listing.catalog.theater_id != theater):
                raise ValueError("Airfield list is stale; use Refresh nearby.")
            page = payload.get("page")
        if action == "airfield_details":
            station = listing.selected(payload.get("station_key"))
            text = airfield_radio_message(listing, station, position)
        else:
            response = await self._call(
                state, "airfields.page", airfield_revision=revision,
                request_id=payload.get("request_id"), unit_id=unit_id, theater_id=theater,
                page=page, pages=listing.pages, items=listing.page_items(page),
            )
            if response.get("airfield_revision") != revision + 1:
                raise ValueError("Invalid airfield page acknowledgement; use Refresh nearby.")
            listing.revision, listing.page = revision + 1, page
            state.airfields = listing
            text = (f"Airfields / ATC: page {page + 1}/{listing.pages}, {len(listing.stations)} live AIRBASE matches.\n"
                    "Reopen this submenu to select an airfield. Order/distances are from initialization or the last refresh.\n"
                    f"[!] = source data needs review. {listing.unresolved} radio records unresolved by AIRBASE ID.\n"
                    f"Catalog: {theater}, {listing.catalog.snapshot_id[:12]} (pinned; AIRBASE objects resolved live).")
        bounded = text.encode("utf-8")[:1900].decode("utf-8", errors="ignore")
        extra = ({"station_key": payload.get("station_key"), "airfield_revision": listing.revision,
                  "theater_id": theater} if action == "airfield_details" else {})
        await self._call(state, "message", text=bounded, unit_id=unit_id, **extra)
        print(f"{state.group_id}: {bounded}", flush=True)

    async def _hints(self, state: GroupNavigation) -> None:
        last_message = asyncio.get_running_loop().time()
        try:
            while not self.bridge.state.mission_ended:
                await asyncio.sleep(self.sample_interval)
                async with state.lock:
                    solution = await self._sample(state)
                    now = asyncio.get_running_loop().time()
                    if (now - last_message >= self.hint_interval
                            or solution.reached_waypoint_indexes or solution.route_complete):
                        await self._reply(state, cockpit_status(state.unit_id or "", solution))
                        last_message = now
                    if solution.route_complete:
                        return
        except ERRORS as exc:
            await self._report_error(state, exc, prefix="Navigation hints stopped")

    async def _report_error(self, state: GroupNavigation, exc: Exception, *, prefix: str = "Navigation") -> None:
        logging.warning("%s: %s: %s", state.group_id, prefix, exc)
        try:
            await self._reply(state, f"{prefix}: {exc}")
        except ERRORS:
            pass  # Stale session/disconnected mission: never fall back to a public message.

    async def handle(self, message: dict[str, Any]) -> None:
        payload = message.get("payload") or {}
        if payload.get("owner_id") != self.owner_id or payload.get("menu_id") != "navigation":
            return
        group_id, session_id = payload.get("group_id"), payload.get("session_id")
        if not isinstance(group_id, str) or not group_id.startswith("GROUP:") or not isinstance(session_id, str):
            return
        key = (group_id, session_id)
        if message.get("event") == "player.menu.closed":
            state = self.groups.pop(key, None)
            if state is not None:
                await self._stop_hints(state)
            return  # Lua already removed this session's overlay, even after disconnect.
        if message.get("event") == "player.menu.created":
            state = self.groups.setdefault(key, GroupNavigation(group_id, session_id))
            async with state.lock:
                try:
                    await self._initialize_navaids(state)
                except ERRORS as exc:
                    logging.warning("%s: Automatic navaid initialization unavailable: %s; use Refresh nearby.",
                                    group_id, exc)
                reference = None
                if state.navaids:
                    first = next(iter(state.navaids.values()))
                    reference = (first.unit_id, first.catalog.theater_id, first.position)
                try:
                    await self._initialize_airfields(state, reference)
                except ERRORS as exc:
                    logging.warning("%s: Automatic airfield radio initialization unavailable: %s; use Refresh nearby.",
                                    group_id, exc)
            return
        action = payload.get("action")
        if message.get("event") != "player.menu.selected" or action not in {
            "route_show", "route_hide", "status", "flight_status", "hints_on", "hints_off",
            "navaids_refresh", "navaids_page", "navaid_details",
            "navaid_show", "navaid_show_line", "navaid_hide",
            "airfields_refresh", "airfields_page", "airfield_details",
        }:
            return
        state = self.groups.setdefault(key, GroupNavigation(group_id, session_id))
        print(f"NAV MENU: {group_id} action={action}", flush=True)
        try:
            if action == "hints_off":
                await self._stop_hints(state)
                await self._reply(state, "Navigation hints disabled.")
                return
            async with state.lock:
                if action in {"navaids_refresh", "navaids_page", "navaid_details"}:
                    await self._navaid_action(state, payload)
                elif action in {"airfields_refresh", "airfields_page", "airfield_details"}:
                    await self._airfield_action(state, payload)
                elif action in {"navaid_show", "navaid_show_line", "navaid_hide"}:
                    await self._navaid_map_action(state, payload)
                elif action == "flight_status":
                    payload = await self._call(state, "flight_status")
                    if (payload.get("owner_id"), payload.get("group_id"), payload.get("session_id")) != (
                        self.owner_id, state.group_id, state.session_id,
                    ):
                        raise ValueError("Flight status belongs to another menu session")
                    status = FlightStatus.from_payload(payload)
                    text = format_flight_status(status)
                    await self._reply(state, text, unit_id=status.unit_id, duration_s=15)
                    print(f"{state.group_id}: {text}", flush=True)
                elif action == "route_hide":
                    await self._call(state, "overlay", show=False)
                    await self._reply(state, "Route hidden on the F10 map.")
                elif action == "route_show":
                    route = await self._route(state, await self._context(state))
                    await self._call(state, "overlay", show=True, features=[route.to_map_line().to_payload()])
                    await self._reply(state, f"F10 route displayed: {len(route.waypoints)} waypoints (own coalition).")
                elif action == "hints_on" and state.hints is not None and not state.hints.done():
                    await self._reply(state, "Navigation hints are already enabled.")
                else:
                    solution = await self._sample(state)
                    text = cockpit_status(state.unit_id or "", solution)
                    if action == "hints_on" and not solution.route_complete:
                        text = f"Navigation hints enabled (approximately every {self.hint_interval:g} s).\n" + text
                    await self._reply(state, text)
                    if action == "hints_on" and not solution.route_complete:
                        state.hints = asyncio.create_task(self._hints(state))
        except ERRORS as exc:
            await self._report_error(state, exc)

    async def close(self) -> None:
        for state in list(self.groups.values()):
            await self._stop_hints(state)
        self.groups.clear()
