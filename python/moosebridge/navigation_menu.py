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

from .flight_routes import FlightGroupRoute
from .navigation import NavigationSolution, RouteNavigator, format_navigation_status
from .protocol import BridgeCommand
from .sdk import require_ok

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


ERRORS = (ConnectionError, OSError, RuntimeError, TimeoutError, ValueError)


async def configure_navigation_menu(
    bridge: MooseBridgeClient, owner_id: str, *, enabled: bool, timeout: float = 10,
) -> dict[str, Any]:
    return require_ok(await bridge.server.send_command(BridgeCommand(
        action="player.menu.navigation.configure", params={"owner_id": owner_id, "enabled": enabled},
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


def reference_unit(context: dict[str, Any]) -> str:
    """Multicrew in one aircraft is unambiguous; multiple aircraft are not."""
    units = {item["unit_id"] for item in context.get("group_sessions", []) if item.get("unit_id")}
    if len(units) != 1:
        raise ValueError("Navigation benoetigt genau ein Spielerflugzeug pro Gruppe.")
    return next(iter(units))


def cockpit_status(unit_id: str, solution: NavigationSolution) -> str:
    bearing = "---" if solution.bearing_true_deg is None else f"{solution.bearing_true_deg:.1f} Grad TRUE"
    side = {"left": "links", "right": "rechts", "on track": "auf Kurs", "undefined": "undefiniert"}
    xte = "undefiniert" if solution.cross_track_m is None else (
        f"{abs(solution.cross_track_m):.0f} m {side[solution.cross_track_side]}"
    )
    text = (f"Referenz: {unit_id.removeprefix('UNIT:')}\n"
            f"WP {solution.from_waypoint_index} -> {solution.target_waypoint_index} ({solution.target_name})\n"
            f"Entfernung: {solution.distance_nm:.2f} NM | Peilung: {bearing}\nXTE: {xte}")
    if solution.route_complete:
        text += "\nLetzter Wegpunkt horizontal erreicht; Landung NICHT geprueft."
    return text


class NavigationMenuController:
    """One route tracker per occupied group-menu session, opt-in periodic hints."""

    def __init__(
        self, bridge: MooseBridgeClient, owner_id: str, *, sample_interval: float = 2,
        hint_interval: float = 10, timeout: float = 10, initial_target: int = 2,
        capture_radius_m: float = 500, max_sample_gap_s: float = 10,
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

    async def _call(self, state: GroupNavigation, operation: str, **params: Any) -> dict[str, Any]:
        if self.bridge.state.mission_ended:
            raise ConnectionError("DCS-Mission beendet.")
        ack = require_ok(await self.bridge.server.send_command(BridgeCommand(
            action=f"player.menu.navigation.{operation}",
            params={**params, "owner_id": self.owner_id,
                    "group_id": state.group_id, "session_id": state.session_id},
        ), timeout=self.timeout))
        result = ack.get("result")
        if not isinstance(result, dict):
            raise ValueError("Invalid navigation menu response")
        return result

    async def _reply(self, state: GroupNavigation, text: str) -> None:
        # Lua bounds bytes, not Unicode characters (player/waypoint names vary).
        bounded = text.encode("utf-8")[:1900].decode("utf-8", errors="ignore")
        await self._call(state, "message", text=bounded)

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
            raise ValueError("Keine FLIGHTGROUP vorhanden. Bitte in der Mission erzeugen.")
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
            raise ValueError("Spielerflugzeug gewechselt; bitte Status erneut abrufen.")
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
            await self._report_error(state, exc, prefix="Hinweise gestoppt")

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
        action = payload.get("action")
        if message.get("event") != "player.menu.selected" or action not in {
            "route_show", "route_hide", "status", "hints_on", "hints_off",
        }:
            return
        state = self.groups.setdefault(key, GroupNavigation(group_id, session_id))
        print(f"NAV MENU: {group_id} action={action}", flush=True)
        try:
            if action == "hints_off":
                await self._stop_hints(state)
                await self._reply(state, "Navigationshinweise aus.")
                return
            async with state.lock:
                if action == "route_hide":
                    await self._call(state, "overlay", show=False)
                    await self._reply(state, "Route auf der F10-Karte ausgeblendet.")
                elif action == "route_show":
                    route = await self._route(state, await self._context(state))
                    await self._call(state, "overlay", show=True, features=[route.to_map_line().to_payload()])
                    await self._reply(state, f"F10-Route angezeigt: {len(route.waypoints)} Wegpunkte (eigene Koalition).")
                elif action == "hints_on" and state.hints is not None and not state.hints.done():
                    await self._reply(state, "Navigationshinweise sind bereits eingeschaltet.")
                else:
                    solution = await self._sample(state)
                    text = cockpit_status(state.unit_id or "", solution)
                    if action == "hints_on" and not solution.route_complete:
                        text = f"Hinweise ein (ca. alle {self.hint_interval:g} s).\n" + text
                    await self._reply(state, text)
                    if action == "hints_on" and not solution.route_complete:
                        state.hints = asyncio.create_task(self._hints(state))
        except ERRORS as exc:
            await self._report_error(state, exc)

    async def close(self) -> None:
        for state in list(self.groups.values()):
            await self._stop_hints(state)
        self.groups.clear()
