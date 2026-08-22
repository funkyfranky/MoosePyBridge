"""Tests for active DCS mission identity exposed by the SDK."""

from __future__ import annotations

import asyncio

from moosebridge.protocol import BridgeCommand
from moosebridge.sdk import MooseBridgeClient
from moosebridge.state import MooseBridgeState


class _MissionInfoServer:
    def __init__(self) -> None:
        self.state = MooseBridgeState(connected=True)
        self.command: BridgeCommand | None = None
        self.timeout: float | None = None

    async def send_command(self, command: BridgeCommand, timeout: float = 10.0) -> dict[str, object]:
        self.command = command
        self.timeout = timeout
        return {
            "ok": True,
            "mission_time": 42.5,
            "dcs_time": 32_442.5,
            "mission_date": "2008/06/21",
            "result": {
                "action": "mission.info",
                "theater_id": "Caucasus",
                "mission_name": "Conflict readiness test",
            },
        }


def test_sdk_returns_typed_active_mission_info() -> None:
    async def scenario() -> None:
        server = _MissionInfoServer()
        bridge = MooseBridgeClient(server)  # type: ignore[arg-type]

        result = await bridge.get_mission_info(timeout=7.0)

        assert result.theater_id == "Caucasus"
        assert result.mission_name == "Conflict readiness test"
        assert result.clock.mission_time == 42.5
        assert server.command is not None
        assert server.command.action == "mission.info"
        assert server.command.params == {}
        assert server.timeout == 7.0

    asyncio.run(scenario())
