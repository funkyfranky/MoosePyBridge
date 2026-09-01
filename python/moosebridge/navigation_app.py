"""Persistent navigation client: wait, preflight, activate, release, reconnect.

Never starts a server, imports data or deploys Lua. Each activation owns a fresh
controller; route progress, selection and hints never survive connection recovery.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from .control import MooseBridgeControlClient
from .control_sdk import sdk_from_control_client
from .navaid_menu import NavaidCatalogProvider
from .navigation_config import NavigationConfig
from .navigation_menu import NavigationMenuController, configure_navigation_menu, ERRORS
from .protocol import BridgeCommand
from .sdk import MooseBridgeCommandError, require_ok


REQUIRED_CAPABILITIES = ("player_lifecycle", "route", "flight_status", "navaids", "navaid_overlay",
                         "navaids_initialize", "airfield_radios")


class NavigationWaiting(Exception):
    """A recoverable boundary or missing prerequisite, without a traceback."""


class NavigationSuperseded(Exception):
    """Another menu owner took over; stop instead of taking it back."""


def session_key(status: dict) -> tuple[str, int]:
    if not status.get("connected") or status.get("mission_ended"):
        raise NavigationWaiting("Waiting for an active DCS mission.")
    server_id, generation = status.get("audit_session_id"), status.get("mission_generation")
    if not isinstance(server_id, str) or not server_id or type(generation) is not int:
        raise NavigationWaiting("Daemon session identity unavailable; update/restart the bridge server.")
    return server_id, generation


async def runtime_status(bridge, timeout: float) -> dict:
    try:
        ack = require_ok(await bridge.server.send_command(
            BridgeCommand(action="player.menu.navigation.status", params={}), timeout=timeout,
        ))
    except MooseBridgeCommandError as exc:
        raise NavigationWaiting("Navigation Lua preflight failed. Deploy current Lua files and restart the mission. "
                                f"Details: {exc}") from exc
    result = ack.get("result")
    if (not isinstance(result, dict) or type(result.get("api_version")) is not int or result["api_version"] != 1
            or not isinstance(result.get("instance_id"), str) or not result["instance_id"]):
        raise NavigationWaiting("Incompatible navigation Lua API; deploy current Lua files and restart the mission.")
    caps = result.get("capabilities")
    if not isinstance(caps, dict) or any(caps.get(key) is not True for key in REQUIRED_CAPABILITIES):
        raise NavigationWaiting("Required navigation Lua capabilities are missing; restart with the current Lua files.")
    if result.get("ready") is not True or not isinstance(result.get("theater_id"), str) or not result["theater_id"]:
        raise NavigationWaiting("Waiting for MOOSE menus and the active mission terrain.")
    return result


class NavigationApplication:
    """A foreground VS Code client with bounded retries and explicit ownership."""

    def __init__(self, config: NavigationConfig):
        self.config = config
        self._notice = None
        self._owned_runs: set[str] = set()

    def notice(self, message: str) -> None:
        if message != self._notice:
            print(message, flush=True)
            self._notice = message

    def _check_takeover(self, runtime: dict) -> None:
        # A newly started process intentionally replaces an earlier run. Recovery
        # must never steal menus back from another process or diagnostic tool.
        if self._owned_runs and runtime.get("enabled") and runtime.get("owner_id") not in self._owned_runs:
            raise NavigationSuperseded("Another client owns the player menus; this navigation client is stopping.")

    async def _catalog(self, theater: str):
        config = self.config
        if not config.navaids_enabled:
            return None, "Navaids are disabled in the navigation configuration."
        if config.dcs_directory is None:
            return None, "Navaids unavailable: set navaids.dcs_directory in navigation.local.json, then restart this script."
        print(f"Navigation-data paths: DCS={config.dcs_directory} | cache={config.cache_directory}", flush=True)
        provider = NavaidCatalogProvider(config.cache_directory, config.dcs_directory)
        try:
            catalog = await asyncio.to_thread(provider.get, theater)
        except ValueError as exc:
            # Keep the provider so a later manual menu refresh can validate the
            # cache again after the offline importer has repaired it.  The
            # provider pins only a successfully loaded snapshot.
            return provider, str(exc)
        print(f"Navigation-data preflight OK: {theater}, {len(catalog.records)} navaids, "
              f"{len(getattr(catalog, 'radio_records', ()))} airfield radio records, snapshot {catalog.snapshot_id[:12]}. "
              "Pinned for this activation; local-source validation does not verify a remote server.", flush=True)
        return provider, None

    async def _watch(self, control, bridge, owner, instance, key) -> None:
        while True:
            await asyncio.sleep(self.config.reconnect_interval)
            if session_key(await control.status(timeout=self.config.command_timeout)) != key:
                raise NavigationWaiting("Mission or bridge server changed; resetting navigation.")
            runtime = await runtime_status(bridge, self.config.command_timeout)
            if runtime["instance_id"] != instance:
                raise NavigationWaiting("Mission Lua instance changed; resetting navigation.")
            if runtime.get("owner_id") != owner or runtime.get("mode") != "navigation":
                raise NavigationSuperseded("Player menus were released or replaced by another client; navigation is stopping.")

    async def _events(self, control, bridge, controller, owner, key, cursor) -> None:
        while True:
            try:
                message = await bridge.server.wait_for_event(
                    "player.menu.*", filters={"owner_id": owner}, after_id=cursor,
                    timeout=self.config.event_timeout,
                )
            except (TimeoutError, RuntimeError) as exc:
                if isinstance(exc, TimeoutError) or str(exc).startswith("control.event.wait timed out after "):
                    continue  # An independent watcher checks health during idle periods.
                raise
            if message.get("event") == "mission.ended":
                raise NavigationWaiting("Mission ended; waiting for the next mission.")
            if session_key(await control.status(timeout=self.config.command_timeout)) != key:
                raise NavigationWaiting("Mission or bridge server changed; discarding the old menu event.")
            cursor = str(message.get("id") or "") or cursor
            await controller.handle(message)

    async def _serve(self, control, bridge, controller, owner, instance, key, cursor) -> None:
        tasks = [asyncio.create_task(self._events(control, bridge, controller, owner, key, cursor)),
                 asyncio.create_task(self._watch(control, bridge, owner, instance, key))]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.cancelled() and isinstance(task.exception(), NavigationSuperseded):
                    raise task.exception()
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _release(self, control, bridge, owner, instance, key) -> None:
        timeout = min(self.config.command_timeout, 2.0)
        try:
            if session_key(await control.status(timeout=timeout)) == key:
                await configure_navigation_menu(bridge, owner, enabled=False, timeout=timeout,
                                                expected_instance_id=instance)
        except (NavigationWaiting, *ERRORS) as exc:
            logging.info("Navigation cleanup deferred to Lua lifecycle/new activation: %s", exc)

    async def run(self) -> int:
        config = self.config
        print(f"Navigation client: {config.control_host}:{config.control_port}. "
              "Waiting/reconnect enabled; Ctrl+C to stop. The bridge server is started separately.", flush=True)
        while True:
            control = MooseBridgeControlClient(config.control_host, config.control_port,
                                               client_id="navigation-menu", display_name="Navigation Menu")
            bridge = sdk_from_control_client(control, timeout=config.command_timeout)
            owner, controller, instance, key, attempted = str(uuid4()), None, None, None, False
            try:
                key = session_key(await control.status(timeout=config.command_timeout))
                runtime = await runtime_status(bridge, config.command_timeout)
                instance = runtime["instance_id"]
                self._check_takeover(runtime)
                provider, unavailable = await self._catalog(runtime["theater_id"])
                # Hashing can take time: recheck the mission before any writes.
                if session_key(await control.status(timeout=config.command_timeout)) != key:
                    raise NavigationWaiting("Mission changed during preflight; retrying.")
                current = await runtime_status(bridge, config.command_timeout)
                if current["instance_id"] != instance or current["theater_id"] != runtime["theater_id"]:
                    raise NavigationWaiting("Mission Lua changed during preflight; retrying.")
                self._check_takeover(current)
                controller = NavigationMenuController(
                    bridge, owner, sample_interval=config.sample_interval, hint_interval=config.hint_interval,
                    timeout=config.command_timeout, initial_target=config.initial_target,
                    capture_radius_m=config.capture_radius_m, max_sample_gap_s=config.max_sample_gap,
                    navaid_catalogs=provider, navaid_error=unavailable,
                )
                cursor = await bridge.server.event_cursor()
                attempted = True  # A lost enable ACK can still leave menus in Lua.
                self._owned_runs.add(owner)
                await configure_navigation_menu(bridge, owner, enabled=True, timeout=config.command_timeout,
                                                expected_instance_id=instance)
                self.notice(f"Navigation active on {runtime['theater_id']}: Radio menu > F10 Other > Navigation. "
                            "Route, hints and navaid map display start OFF.")
                if unavailable:
                    print(f"Navaid preflight WARNING: {unavailable}\nOther navigation functions remain available.", flush=True)
                print("Show/Hide route | Navigation status | Flight status | Enable/Disable hints | Navaids | Airfields / ATC", flush=True)
                print("Navaids: all types initialize once at menu creation; Refresh nearby updates a type (six stations per page).", flush=True)
                print("Airfields / ATC: imported radio.lua data joined to live MOOSE AIRBASE:GetID(); six airfields per page.", flush=True)
                print("Selected station > Show on F10 / Show with bearing line / Hide from F10.", flush=True)
                print("Flight status: FLIGHTGROUP FSM, altitude/weather, IAS/TAS/GS/Mach, "
                      "MAG/TRUE directions; on demand for 15 seconds. Missing values are N/A.", flush=True)
                print("One player aircraft per group; route navigation also needs its FLIGHTGROUP. "
                      "Bearings are TRUE, navaid bearing lines are static, F10 drawings are coalition-visible. Cockpit unchanged.", flush=True)
                await self._serve(control, bridge, controller, owner, instance, key, cursor)
            except NavigationSuperseded as exc:
                self.notice(str(exc))
                return 0
            except NavigationWaiting as exc:
                self.notice(str(exc))
            except ERRORS as exc:
                self.notice(f"Waiting for bridge/DCS recovery: {exc}")
            finally:
                if controller is not None:
                    await controller.close()
                if attempted:
                    await self._release(control, bridge, owner, instance, key)
                bridge.close()
            await asyncio.sleep(config.reconnect_interval)
