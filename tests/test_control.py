from __future__ import annotations

import asyncio
import io
import json
from contextlib import redirect_stdout
from typing import Any

from moosebridge.control import MooseBridgeControlClient, MooseBridgeControlServer, apply_state_payload, state_payload
from examples.control_server_client.interactive_control_client import (
    normalize_snapshot_actions,
    parse_message_argument,
    print_command_feedback,
    snapshot_actions_to_kinds,
)
from moosebridge.protocol import BridgeCommand
from moosebridge.state import MooseBridgeState


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


def test_interactive_snapshot_aliases_normalize_to_bridge_actions() -> None:
    actions = normalize_snapshot_actions(("groups", "units", "snapshot.cohorts", "all"))

    assert actions == ("snapshot.groups", "snapshot.units", "snapshot.cohorts", "snapshot.all")
    assert snapshot_actions_to_kinds(actions) is None


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
