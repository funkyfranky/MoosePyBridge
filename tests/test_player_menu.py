"""Player radio test: Lua lifecycle harness and normal-daemon Python consumer."""

import asyncio
import os
from pathlib import Path
import runpy
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from moosebridge import MooseBridgeCommandError, MooseBridgeState


ROOT = Path(__file__).resolve().parents[1]


def test_lua_player_menu_lifecycle() -> None:
    runtime = os.environ.get("MOOSEBRIDGE_TEST_LUA") or shutil.which("lua")
    if not runtime:
        pytest.skip("Set MOOSEBRIDGE_TEST_LUA or install Lua to run the Lua lifecycle harness")
    result = subprocess.run(
        [runtime, str(ROOT / "tests/lua/player_menu_test.lua"),
         str(ROOT / "lua/MooseBridgeDcsEventsExtension.lua")],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PLAYER MENU LUA TEST PASSED" in result.stdout


def test_lua_navaid_overlay_uses_real_drawing_helpers() -> None:
    runtime = os.environ.get("MOOSEBRIDGE_TEST_LUA") or shutil.which("lua")
    if not runtime:
        pytest.skip("Set MOOSEBRIDGE_TEST_LUA or install Lua to run the drawing harness")
    result = subprocess.run(
        [runtime, str(ROOT / "tests/lua/navaid_overlay_test.lua"),
         str(ROOT / "lua/MooseBridge.lua"), str(ROOT / "lua/MooseBridgeDcsEventsExtension.lua")],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NAVAID OVERLAY LUA TEST PASSED" in result.stdout


@pytest.fixture
def example(monkeypatch):
    examples = ROOT / "examples/sdk"
    monkeypatch.syspath_prepend(str(examples))
    return runpy.run_path(str(examples / "monitor_player_menu.py"))


def test_configure_uses_normal_bridge_command_and_checks_ack(example) -> None:
    async def scenario():
        send = AsyncMock(return_value={"ok": True})
        bridge = SimpleNamespace(server=SimpleNamespace(send_command=send))
        await example["configure_menu"](bridge, "run-id", enabled=True)
        command = send.call_args.args[0]
        assert command.action == "player.menu.test.configure"
        assert command.params == {"enabled": True, "owner_id": "run-id"}
        send.return_value = {"ok": False, "error": "rejected"}
        with pytest.raises(MooseBridgeCommandError):
            await example["configure_menu"](bridge, "run-id", enabled=False)
    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["mission", "cancel", "connection", "lost_ack"])
def test_monitor_prints_click_and_cleans_up_its_own_run(example, monkeypatch, capsys, boundary) -> None:
    async def scenario():
        state = MooseBridgeState()
        sends, waits = [], []

        async def send(command, **kwargs):
            sends.append(command)
            if boundary == "lost_ack" and len(sends) == 1:
                raise TimeoutError("lost enable ACK")
            return {"ok": True}

        async def wait(name, **kwargs):
            waits.append((name, kwargs))
            if len(waits) == 1:
                return {"id": "click-1", "event": "player.menu.selected", "payload": {
                    "action": "python_console", "group_id": "GROUP:Hornet",
                    "group_sessions": [{"player_name": "Pilot"}, {"player_name": "Wingman"}],
                }}
            assert kwargs["after_id"] == "click-1"
            if boundary == "mission":
                state.reset_mission()
                return {"id": "end", "event": "mission.ended"}
            if boundary == "cancel":
                raise asyncio.CancelledError
            raise ConnectionError("test disconnect")

        bridge = SimpleNamespace(
            state=state,
            server=SimpleNamespace(
                send_command=send, wait_for_event=wait,
                event_cursor=AsyncMock(return_value="baseline"),
            ),
            closed=False,
        )
        bridge.close = lambda: setattr(bridge, "closed", True)
        monkeypatch.setitem(example["run"].__globals__, "open_example_session",
                            AsyncMock(return_value=SimpleNamespace(bridge=bridge)))
        if boundary == "mission":
            assert await example["run"]() == 0
            assert len(sends) == 1
        else:
            error = {"cancel": asyncio.CancelledError, "connection": ConnectionError,
                     "lost_ack": TimeoutError}[boundary]
            with pytest.raises(error):
                await example["run"]()
            assert len(sends) == 2
            assert sends[1].params == {"enabled": False, "owner_id": sends[0].params["owner_id"]}
        assert bridge.closed
        if waits:
            assert waits[0][0] == "player.menu.selected"
            assert waits[0][1]["after_id"] == "baseline"
            assert waits[0][1]["filters"] == {
                "owner_id": sends[0].params["owner_id"], "action": "python_console",
            }
    asyncio.run(scenario())
    if boundary != "lost_ack":
        output = capsys.readouterr().out
        assert "MENU CLICK 1: group=GROUP:Hornet action=python_console" in output
        assert "group occupants: Pilot, Wingman" in output


def test_lua_menu_hooks_preserve_lifecycle_and_use_moose_classes() -> None:
    source = (ROOT / "lua/MooseBridgeDcsEventsExtension.lua").read_text(encoding="utf-8")
    assert 'MENU_GROUP:New(group, "MoosePyBridge Test")' in source
    assert 'MENU_GROUP_COMMAND:New(group, "Show message"' in source
    assert 'MENU_GROUP_COMMAND:New(group, "Python console"' in source
    assert ':ToGroup(entry.group)' in source
    assert 'self:SendEvent("player.menu.selected"' in source
    assert 'self:_SyncPlayerTestMenu(session.group_name, group)' in source
    assert 'scope="group"' in source
    assert 'self.PlayerTestMenus[group_name] ~= entry' in source
