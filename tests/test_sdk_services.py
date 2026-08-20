"""Focused tests for internal services behind the public SDK facade."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from moosebridge.protocol import BridgeCommand
from moosebridge.sdk_presentation import DcsPresentationService
from moosebridge.settlements import TheaterSettlements
from moosebridge.strategic_verification import StrategicVerificationRegistry
from moosebridge.theater_context import TheaterContext
from moosebridge.theater_service import TheaterDataService


class CapturingBackend:
    def __init__(self) -> None:
        self.commands: list[tuple[BridgeCommand, float]] = []

    async def send_command(
        self,
        command: BridgeCommand,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        self.commands.append((command, timeout))
        return {"ok": True, "result": {"action": command.action}}


def test_presentation_service_builds_transport_neutral_commands() -> None:
    async def scenario() -> None:
        backend = CapturingBackend()
        service = DcsPresentationService(backend)  # type: ignore[arg-type]

        await service.message_coalition("blue", "Ready", 8)
        await service.smoke_point(10.0, 20.0, " Green ", 3.0)
        await service.explode_object("SCENERY:42", 500.0, delay=2.0, timeout=12.0)
        await service.mark_map_position(
            "Bridge",
            x=None,
            z=None,
            y=0.0,
            latitude=41.66,
            longitude=41.68,
            altitude=0.0,
            coalition="red",
            read_only=True,
            timeout=4.0,
        )

        assert [command.action for command, _ in backend.commands] == [
            "message.to_coalition",
            "smoke.at_point",
            "explosion.object",
            "map.marker.create",
        ]
        assert backend.commands[1][0].params["color"] == "green"
        assert backend.commands[2][1] == 12.0
        marker, marker_timeout = backend.commands[3]
        assert marker.params == {
            "point": {"latitude": 41.66, "longitude": 41.68, "altitude": 0.0},
            "text": "Bridge",
            "coalition": "red",
            "read_only": True,
        }
        assert marker_timeout == 4.0

    asyncio.run(scenario())


def test_presentation_service_owns_effect_validation() -> None:
    async def scenario() -> None:
        service = DcsPresentationService(CapturingBackend())  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="greater than zero"):
            await service.explode_point(0.0, 0.0, 0.0, y=None, delay=0.0, timeout=10.0)
        with pytest.raises(ValueError, match="Unsupported smoke color"):
            await service.smoke_object("UNIT:Target", "purple")
        with pytest.raises(ValueError, match="either x/z or latitude/longitude"):
            await service.mark_map_position(
                "Invalid",
                x=1.0,
                z=2.0,
                y=0.0,
                latitude=41.0,
                longitude=42.0,
                altitude=0.0,
                coalition="all",
                read_only=False,
                timeout=10.0,
            )

    asyncio.run(scenario())


def test_theater_service_resolves_configured_and_explicit_sources() -> None:
    service = TheaterDataService()
    configured = service.configure(
        TheaterContext("Caucasus", settlements=TheaterSettlements("Caucasus"))
    )

    resolved = service.resolve_sources(
        theater=None,
        settlements=None,
        transport=None,
        railway=None,
        infrastructure=None,
        verifications=None,
    )
    assert resolved.context is configured
    assert resolved.settlements is configured.settlements

    explicit = service.resolve_sources(
        theater=None,
        settlements=TheaterSettlements("GermanyCW"),
        transport=None,
        railway=None,
        infrastructure=None,
        verifications=None,
    )
    assert explicit.context is not None
    assert explicit.context.theater_id == "GermanyCW"
    assert service.context is configured


def test_theater_service_preserves_unbound_verification_compatibility() -> None:
    service = TheaterDataService()
    registry = StrategicVerificationRegistry()

    resolved = service.resolve_sources(
        theater=None,
        settlements=None,
        transport=None,
        railway=None,
        infrastructure=None,
        verifications=registry,
    )

    assert resolved.context is None
    assert resolved.verifications is registry
    assert registry.theater_id == ""
