"""Internal static-theater context management for the SDK facade."""

from __future__ import annotations

from dataclasses import dataclass

from .infrastructure_sites import TheaterInfrastructureSites
from .railway_infrastructure import TheaterRailwayInfrastructure
from .settlements import TheaterSettlements
from .strategic_verification import StrategicVerificationRegistry
from .theater_context import TheaterContext
from .transport_infrastructure import TheaterTransportInfrastructure


@dataclass(frozen=True, slots=True)
class ResolvedTheaterSources:
    """Static theater inputs selected for one objective-generation call."""

    context: TheaterContext | None
    settlements: TheaterSettlements | None
    transport: TheaterTransportInfrastructure | None
    railway: TheaterRailwayInfrastructure | None
    infrastructure: TheaterInfrastructureSites | None
    verifications: StrategicVerificationRegistry | None


class TheaterDataService:
    """Own validated theater context independently from mission runtime state."""

    def __init__(self) -> None:
        self._context: TheaterContext | None = None

    @property
    def context(self) -> TheaterContext | None:
        return self._context

    @property
    def verifications(self) -> StrategicVerificationRegistry | None:
        return self._context.verifications if self._context is not None else None

    def configure(self, context: TheaterContext) -> TheaterContext:
        context.validate()
        self._context = context
        return context

    def clear(self) -> None:
        """Remove the configured context without touching mission runtime state."""

        self._context = None

    def resolve_sources(
        self,
        *,
        theater: TheaterContext | None,
        settlements: TheaterSettlements | None,
        transport: TheaterTransportInfrastructure | None,
        railway: TheaterRailwayInfrastructure | None,
        infrastructure: TheaterInfrastructureSites | None,
        verifications: StrategicVerificationRegistry | None,
    ) -> ResolvedTheaterSources:
        """Resolve explicit, legacy, or configured static theater sources."""

        separate_sources = any(
            item is not None
            for item in (settlements, transport, railway, infrastructure, verifications)
        )
        if theater is not None and separate_sources:
            raise ValueError("pass either theater context or individual theater artifacts, not both")

        resolved_context = theater
        scoped_sources = any(
            item is not None
            for item in (settlements, transport, railway, infrastructure)
        ) or bool(verifications is not None and verifications.theater_id.strip())
        if resolved_context is None and separate_sources and scoped_sources:
            resolved_context = TheaterContext.from_sources(
                settlements=settlements,
                transport=transport,
                railway=railway,
                infrastructure=infrastructure,
                verifications=verifications,
            )
        elif resolved_context is None and not separate_sources:
            resolved_context = self._context

        if resolved_context is not None:
            resolved_context.validate()
            settlements = resolved_context.settlements
            transport = resolved_context.transport
            railway = resolved_context.railway
            infrastructure = resolved_context.infrastructure
            verifications = resolved_context.verifications

        return ResolvedTheaterSources(
            context=resolved_context,
            settlements=settlements,
            transport=transport,
            railway=railway,
            infrastructure=infrastructure,
            verifications=verifications,
        )
