"""Validated static theater data consumed by strategic planning."""

from __future__ import annotations

from dataclasses import dataclass

from .infrastructure_sites import TheaterInfrastructureSites
from .railway_infrastructure import TheaterRailwayInfrastructure
from .settlements import TheaterSettlements
from .strategic_verification import StrategicVerificationRegistry
from .transport_infrastructure import TheaterTransportInfrastructure


@dataclass(slots=True)
class TheaterContext:
    """Static artifacts that must all belong to one DCS theater."""

    theater_id: str
    settlements: TheaterSettlements | None = None
    transport: TheaterTransportInfrastructure | None = None
    railway: TheaterRailwayInfrastructure | None = None
    infrastructure: TheaterInfrastructureSites | None = None
    verifications: StrategicVerificationRegistry | None = None

    def __post_init__(self) -> None:
        self.theater_id = self.theater_id.strip()
        if not self.theater_id:
            raise ValueError("theater context requires a non-empty theater_id")
        self.validate()

    @classmethod
    def from_sources(
        cls,
        *,
        theater_id: str | None = None,
        settlements: TheaterSettlements | None = None,
        transport: TheaterTransportInfrastructure | None = None,
        railway: TheaterRailwayInfrastructure | None = None,
        infrastructure: TheaterInfrastructureSites | None = None,
        verifications: StrategicVerificationRegistry | None = None,
    ) -> "TheaterContext":
        """Infer one theater identity from supplied static artifacts."""

        identities = [
            value.strip()
            for value in (
                theater_id,
                getattr(settlements, "theater_id", None),
                getattr(transport, "theater_id", None),
                getattr(railway, "theater_id", None),
                getattr(infrastructure, "theater_id", None),
                getattr(verifications, "theater_id", None),
            )
            if isinstance(value, str) and value.strip()
        ]
        folded = {value.casefold() for value in identities}
        if not identities:
            raise ValueError("cannot infer theater_id from unscoped theater artifacts")
        if len(folded) != 1:
            raise ValueError(f"theater data mismatch: found {', '.join(sorted(identities))}")
        resolved_id = identities[0]
        return cls(
            theater_id=resolved_id,
            settlements=settlements,
            transport=transport,
            railway=railway,
            infrastructure=infrastructure,
            verifications=verifications,
        )

    def validate(self) -> None:
        """Reject artifacts belonging to another theater and bind verification data."""

        expected = self.theater_id.casefold()
        for label, artifact in (
            ("settlements", self.settlements),
            ("transport", self.transport),
            ("railway", self.railway),
            ("infrastructure", self.infrastructure),
        ):
            if artifact is None:
                continue
            actual = str(artifact.theater_id or "").strip()
            if not actual:
                raise ValueError(f"{label} theater data has no theater_id")
            if actual.casefold() != expected:
                raise ValueError(
                    f"{label} theater mismatch: expected {self.theater_id}, found {actual}"
                )
        if self.verifications is not None:
            self.verifications.bind_theater(self.theater_id)
