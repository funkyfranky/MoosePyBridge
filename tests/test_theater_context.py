"""Tests for validated, mission-independent theater data."""

from __future__ import annotations

import pytest

from moosebridge.infrastructure_sites import TheaterInfrastructureSites
from moosebridge.railway_infrastructure import TheaterRailwayInfrastructure
from moosebridge.sdk import MooseBridgeClient
from moosebridge.server import MooseBridgeServer
from moosebridge.settlements import TheaterSettlements
from moosebridge.strategic_verification import StrategicVerificationRegistry
from moosebridge.theater_context import TheaterContext
from moosebridge.transport_infrastructure import TheaterTransportInfrastructure


def test_theater_context_accepts_matching_artifacts_and_binds_verifications() -> None:
    registry = StrategicVerificationRegistry()
    context = TheaterContext.from_sources(
        settlements=TheaterSettlements("Caucasus"),
        transport=TheaterTransportInfrastructure("Caucasus", (), ()),
        railway=TheaterRailwayInfrastructure("Caucasus"),
        infrastructure=TheaterInfrastructureSites("Caucasus"),
        verifications=registry,
    )

    assert context.theater_id == "Caucasus"
    assert registry.theater_id == "Caucasus"


def test_theater_context_rejects_mixed_theater_artifacts() -> None:
    with pytest.raises(ValueError, match="theater data mismatch"):
        TheaterContext.from_sources(
            settlements=TheaterSettlements("GermanyCW"),
            railway=TheaterRailwayInfrastructure("Caucasus"),
        )


def test_sdk_preserves_theater_verifications_across_mission_reset() -> None:
    server = MooseBridgeServer()
    bridge = MooseBridgeClient(server)
    registry = StrategicVerificationRegistry()
    context = bridge.configure_theater(
        TheaterContext("Caucasus", verifications=registry)
    )

    bridge.reset_mission(reset_state=False)

    assert bridge.theater_context is context
    assert bridge._strategic_verifications is registry
    assert registry.theater_id == "Caucasus"
