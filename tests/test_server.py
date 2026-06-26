from __future__ import annotations

import asyncio

from moosebridge.protocol import BridgeCommand
from moosebridge.server import MooseBridgeServer


def test_point_commands_use_at_point_actions() -> None:
    server = MooseBridgeServer()
    sent: list[BridgeCommand] = []

    async def fake_send_command(command: BridgeCommand, timeout: float = 10.0) -> dict[str, object]:
        sent.append(command)
        return {"ok": True}

    server.send_command = fake_send_command  # type: ignore[method-assign]

    asyncio.run(server.smoke_at_point(1, 2, "red", y=3))
    asyncio.run(server.mark_at_point(4, 5, "mark", y=6))

    assert [command.action for command in sent] == ["smoke.at_point", "mark.at_point"]
    assert sent[0].params == {"x": 1, "y": 3, "z": 2, "color": "red"}
    assert sent[1].params == {"x": 4, "y": 6, "z": 5, "text": "mark"}


def test_new_snapshot_helpers_use_registered_lua_actions() -> None:
    server = MooseBridgeServer()
    sent: list[BridgeCommand] = []

    async def fake_send_command(command: BridgeCommand, timeout: float = 10.0) -> dict[str, object]:
        sent.append(command)
        return {"ok": True}

    server.send_command = fake_send_command  # type: ignore[method-assign]

    asyncio.run(server.snapshot_cohorts())
    asyncio.run(server.snapshot_legions())

    assert [command.action for command in sent] == ["snapshot.cohorts", "snapshot.legions"]
