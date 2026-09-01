"""Persistent navigation lifecycle tests; no live daemon or DCS writes."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import moosebridge.navigation_app as app
from moosebridge.navigation_config import load_navigation_config
from moosebridge.navigation_menu import NavigationMenuController
from test_navigation_menu import Bridge, event


ROOT = Path(__file__).resolve().parents[1]


def config():
    return replace(load_navigation_config(ROOT / "config/navigation.json"), navaids_enabled=False,
                   reconnect_interval=.005, event_timeout=.005, command_timeout=.1, sample_interval=60)


class Backend:
    def __init__(self):
        self.state = Bridge().state
        self.state.connected = True
        self.state.audit_session_id = "server-a"
        self.online = True
        self.instance = "lua-a"
        self.owner = None
        self.speech_owner = None
        self.mode = None
        self.api_version = 1
        self.ready = True
        self.capabilities = dict.fromkeys(app.REQUIRED_CAPABILITIES, True)
        self.queue = asyncio.Queue()
        self.commands, self.controllers, self.bridges = [], [], []
        self.fail_enable = False
        self.missing_command = False
        self.occupied_on_enable = False

    def runtime(self):
        return {"api_version": self.api_version, "instance_id": self.instance, "ready": self.ready,
                "theater_id": "Caucasus", "capabilities": self.capabilities,
                "enabled": self.owner is not None, "owner_id": self.owner, "mode": self.mode}

    def install(self, monkeypatch):
        backend = self
        class Control:
            def __init__(self, host, port, **kwargs):
                assert host == "127.0.0.1" and port == 42001
                self.state = backend.state
            async def status(self, **kwargs):
                if not backend.online:
                    raise ConnectionError("Mock daemon offline")
                return {"connected": backend.state.connected, "mission_ended": backend.state.mission_ended,
                        "audit_session_id": backend.state.audit_session_id,
                        "mission_generation": backend.state.mission_generation}

        class Client(Bridge):
            def __init__(self):
                super().__init__()
                self.state = backend.state
                self.closed = False
                self.cursor_read = False
                backend.bridges.append(self)
            async def send_command(self, command, **kwargs):
                backend.commands.append(command)
                if not backend.online or not self.state.connected:
                    raise ConnectionError("Mock DCS offline")
                if command.action.endswith("navigation.status"):
                    if backend.missing_command:
                        return {"ok": False, "error": "Unknown command"}
                    return {"ok": True, "result": deepcopy(backend.runtime())}
                if command.action == "speech.configure":
                    if command.params["expected_instance_id"] != backend.instance:
                        return {"ok": False, "error": "Speech bridge instance changed"}
                    if command.params["enabled"]:
                        backend.speech_owner = command.params["owner_id"]
                    elif backend.speech_owner == command.params["owner_id"]:
                        backend.speech_owner = None
                    return {"ok": True, "result": {"available": True, "enabled": command.params["enabled"]}}
                if command.action == "player.menu.navigation.configure":
                    if command.params["expected_instance_id"] != backend.instance:
                        return {"ok": False, "error": "Navigation bridge instance changed"}
                    if command.params["enabled"]:
                        backend.owner, backend.mode = command.params["owner_id"], "navigation"
                        if backend.occupied_on_enable:
                            assert self.cursor_read, "capture the cursor before Lua emits menu creation events"
                            message = event(owner=backend.owner)
                            message.update(event="player.menu.created", id="created-on-enable")
                            await backend.queue.put(message)
                        if backend.fail_enable:
                            backend.fail_enable = False
                            raise TimeoutError("Lost enable ACK")
                    elif backend.owner == command.params["owner_id"]:
                        backend.owner = backend.mode = None
                    return {"ok": True, "result": {}}
                self.context["owner_id"] = backend.owner
                return await super().send_command(command, **kwargs)
            async def event_cursor(self):
                self.cursor_read = True
                return "baseline"
            async def wait_for_event(self, name, *, filters, timeout, after_id):
                assert name == "player.menu.*" and after_id
                while True:
                    message = await asyncio.wait_for(backend.queue.get(), timeout)
                    if isinstance(message, Exception):
                        raise message
                    if message.get("event") == "mission.ended" or message["payload"]["owner_id"] == filters["owner_id"]:
                        return message
            def close(self):
                self.closed = True

        def controller(*args, **kwargs):
            result = NavigationMenuController(*args, **kwargs)
            backend.controllers.append(result)
            return result
        monkeypatch.setattr(app, "MooseBridgeControlClient", Control)
        monkeypatch.setattr(app, "sdk_from_control_client", lambda *args, **kwargs: Client())
        monkeypatch.setattr(app, "NavigationMenuController", controller)

    def enables(self):
        return [c for c in self.commands
                if c.action == "player.menu.navigation.configure" and c.params["enabled"]]

    def navigation_configs(self):
        return [c for c in self.commands if c.action == "player.menu.navigation.configure"]


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(wait(), 3)


async def stop(task):
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_start_before_server_and_mission_then_cancel_cleans_only_owned_menu(monkeypatch, capsys):
    async def scenario():
        backend = Backend()
        backend.online = False
        backend.install(monkeypatch)
        task = asyncio.create_task(app.NavigationApplication(config()).run())
        try:
            await until(lambda: len(backend.bridges) >= 2)
            assert not backend.commands
            backend.online, backend.state.connected = True, False
            await asyncio.sleep(.025)
            assert not backend.enables()
            backend.state.connected = True
            await until(lambda: backend.owner is not None)
            assert len(backend.enables()) == 1
        finally:
            await stop(task)
        assert backend.owner is None and backend.speech_owner is None and all(b.closed for b in backend.bridges)
        configs = backend.navigation_configs()
        assert [c.params["enabled"] for c in configs] == [True, False]
        assert configs[0].params["owner_id"] == configs[1].params["owner_id"]
    asyncio.run(scenario())
    output = capsys.readouterr().out
    assert output.count("Mock daemon offline") == 1
    assert "Other navigation functions remain available" in output


@pytest.mark.parametrize("boundary", ["mission_event", "missed_end", "server_restart", "instance_change", "disconnect"])
def test_recovery_uses_fresh_controller_without_old_copilot_or_selection(monkeypatch, boundary):
    async def scenario():
        backend = Backend()
        backend.install(monkeypatch)
        task = asyncio.create_task(app.NavigationApplication(config()).run())
        try:
            await until(lambda: backend.owner is not None)
            old_owner, old = backend.owner, backend.controllers[0]
            message = event("copilot_start", owner=old_owner)
            message["id"] = "click-1"
            await backend.queue.put(message)
            await until(lambda: old.groups and next(iter(old.groups.values())).copilot_task is not None)
            state = next(iter(old.groups.values()))
            copilot_task = state.copilot_task
            state.selected_navaid = object()
            if boundary in {"mission_event", "missed_end"}:
                backend.state.reset_mission()
                if boundary == "mission_event":
                    await backend.queue.put({"id": "end", "event": "mission.ended"})
                await until(lambda: not old.groups)
                backend.state.connected, backend.state.mission_ended = True, False
                backend.instance, backend.owner, backend.mode = "lua-b", None, None
            elif boundary == "server_restart":
                backend.state.audit_session_id = "server-b"  # Generation may be unchanged.
            elif boundary == "instance_change":
                backend.instance, backend.owner, backend.mode = "lua-b", None, None
            else:
                backend.state.connected = False
                await until(lambda: not old.groups)
                backend.state.connected = True
            await until(lambda: len(backend.enables()) >= 2)
            assert backend.owner != old_owner and not old.groups and copilot_task.done()
            fresh = backend.controllers[-1]
            assert fresh is not old and not fresh.groups
            assert fresh.owner_id == backend.owner
        finally:
            await stop(task)
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["version", "missing_command", "capability", "not_ready"])
def test_lua_preflight_waits_without_creating_menus_and_recovers(monkeypatch, failure, capsys):
    async def scenario():
        backend = Backend()
        if failure == "version":
            backend.api_version = 99
        elif failure == "missing_command":
            backend.missing_command = True
        elif failure == "capability":
            backend.capabilities["navaid_overlay"] = False
        else:
            backend.ready = False
        backend.install(monkeypatch)
        task = asyncio.create_task(app.NavigationApplication(config()).run())
        try:
            await until(lambda: len(backend.bridges) > 1)
            assert not backend.enables()
            backend.api_version, backend.missing_command, backend.ready = 1, False, True
            backend.capabilities["navaid_overlay"] = True
            await until(lambda: backend.owner is not None)
        finally:
            await stop(task)
    asyncio.run(scenario())
    assert "Navigation active" in capsys.readouterr().out


def test_lost_enable_ack_is_cleaned_before_retrying(monkeypatch):
    async def scenario():
        backend = Backend()
        backend.fail_enable = True
        backend.install(monkeypatch)
        task = asyncio.create_task(app.NavigationApplication(config()).run())
        try:
            await until(lambda: len(backend.enables()) == 2)
            commands = backend.navigation_configs()
            assert [c.params["enabled"] for c in commands[:3]] == [True, False, True]
            assert commands[0].params["owner_id"] == commands[1].params["owner_id"]
            assert commands[2].params["owner_id"] != commands[0].params["owner_id"]
        finally:
            await stop(task)
    asyncio.run(scenario())


@pytest.mark.parametrize("when", ["active", "recovery"])
def test_another_menu_owner_stops_old_client_without_takeover_loop(monkeypatch, when):
    async def scenario():
        backend = Backend()
        backend.install(monkeypatch)
        task = asyncio.create_task(app.NavigationApplication(config()).run())
        await until(lambda: backend.owner is not None)
        if when == "recovery":
            backend.state.connected = False
            await until(lambda: backend.bridges[0].closed)
        backend.owner = "other-client"
        backend.state.connected = True
        assert await asyncio.wait_for(task, 3) == 0
        assert backend.owner == "other-client" and len(backend.enables()) == 1
    asyncio.run(scenario())


def test_missing_navaid_cache_does_not_disable_other_actions(monkeypatch, capsys):
    async def scenario():
        backend = Backend()
        backend.install(monkeypatch)
        class Missing:
            def __init__(self, *args):
                pass
            def get(self, theater):
                raise ValueError("Cache outdated; run import_dcs_beacons.py.")
        monkeypatch.setattr(app, "NavaidCatalogProvider", Missing)
        cfg = replace(config(), navaids_enabled=True, dcs_directory=ROOT)
        task = asyncio.create_task(app.NavigationApplication(cfg).run())
        try:
            await until(lambda: backend.owner is not None)
            controller = backend.controllers[0]
            # A failed preflight retains the provider so a menu refresh can
            # retry after the offline importer repairs the cache.
            assert isinstance(controller.navaid_catalogs, Missing)
            assert "Cache outdated" in controller.navaid_error
            message = event("flight_status", owner=backend.owner)
            message["id"] = "flight-status"
            # Supply the active owner in the existing telemetry test fixture.
            backend.bridges[-1].flight_status["owner_id"] = backend.owner
            await backend.queue.put(message)
            await until(lambda: any(c.action.endswith(".message") for c in backend.commands))
        finally:
            await stop(task)
    asyncio.run(scenario())
    assert "Other navigation functions remain available" in capsys.readouterr().out


def test_mission_change_during_preflight_does_not_enable_old_mission(monkeypatch):
    async def scenario():
        backend = Backend()
        backend.install(monkeypatch)
        application = app.NavigationApplication(config())
        calls = 0
        async def catalog(theater):
            nonlocal calls
            calls += 1
            if calls == 1:
                backend.state.mission_generation += 1
                backend.instance = "lua-b"
            return None, "Navaids disabled for test"
        monkeypatch.setattr(application, "_catalog", catalog)
        task = asyncio.create_task(application.run())
        try:
            await until(lambda: backend.owner is not None)
            assert calls == 2 and len(backend.enables()) == 1
            assert backend.enables()[0].params["expected_instance_id"] == "lua-b"
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_stalled_action_is_cancelled_by_independent_mission_watcher(monkeypatch):
    async def scenario():
        backend = Backend()
        backend.install(monkeypatch)
        task = asyncio.create_task(app.NavigationApplication(config()).run())
        started, cancelled = asyncio.Event(), asyncio.Event()
        try:
            await until(lambda: backend.owner is not None)
            async def blocked(message):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            backend.controllers[0].handle = blocked
            message = event(owner=backend.owner)
            message["id"] = "blocked"
            await backend.queue.put(message)
            await asyncio.wait_for(started.wait(), 1)
            backend.state.reset_mission()
            await asyncio.wait_for(cancelled.wait(), 1)
            assert not task.done()
        finally:
            await stop(task)
    asyncio.run(scenario())


def test_navaid_catalog_is_preflighted_again_for_each_activation(monkeypatch):
    async def scenario():
        backend = Backend()
        backend.install(monkeypatch)
        providers, checked = [], []
        class Catalog:
            def __init__(self, *args):
                providers.append(self)
            def get(self, theater):
                checked.append((self, theater))
                return SimpleNamespace(records=(), snapshot_id="a" * 64)
        monkeypatch.setattr(app, "NavaidCatalogProvider", Catalog)
        task = asyncio.create_task(app.NavigationApplication(
            replace(config(), navaids_enabled=True, dcs_directory=ROOT),
        ).run())
        try:
            await until(lambda: backend.owner is not None)
            first = backend.controllers[0].navaid_catalogs
            assert checked == [(first, "Caucasus")]
            backend.instance, backend.owner, backend.mode = "lua-b", None, None
            await until(lambda: len(backend.enables()) == 2)
            assert backend.controllers[-1].navaid_catalogs is not first
            assert len(checked) == 2 and len(providers) == 2
        finally:
            await stop(task)
    asyncio.run(scenario())


@pytest.mark.parametrize("occupied_on_enable", [True, False])
def test_application_initializes_menu_creation_before_enable_ack_or_on_later_entry(monkeypatch, occupied_on_enable):
    from test_navaid_menu import provider, created_menu
    async def scenario():
        backend = Backend()
        backend.occupied_on_enable = occupied_on_enable
        backend.install(monkeypatch)
        monkeypatch.setattr(app, "NavaidCatalogProvider", lambda *args: provider())
        task = asyncio.create_task(app.NavigationApplication(
            replace(config(), navaids_enabled=True, dcs_directory=ROOT),
        ).run())
        def batches():
            return [c for c in backend.commands if c.action.endswith("navaids.initialize")]
        try:
            await until(lambda: backend.owner is not None)
            if not occupied_on_enable:
                assert not batches()
                message = created_menu(owner=backend.owner)
                message["id"] = "created-after-entry"
                await backend.queue.put(message)
            await until(lambda: backend.controllers[0].groups
                        and len(next(iter(backend.controllers[0].groups.values())).navaids) == 11)
            assert len(batches()) == 1
            assert len(backend.bridges[-1].positions) == 1
            # A mission replacement creates a fresh owner, controller and snapshot.
            backend.instance, backend.owner, backend.mode = "lua-b", None, None
            backend.occupied_on_enable = True
            await until(lambda: len(batches()) == 2)
            assert len(backend.controllers) == 2 and not backend.controllers[0].groups
        finally:
            await stop(task)
    asyncio.run(scenario())
