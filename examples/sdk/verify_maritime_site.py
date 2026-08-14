"""Entry point for port and maritime-logistics scenery verification."""

from __future__ import annotations

import asyncio

import verify_infrastructure_site as verifier
from moosebridge import InfrastructureSiteKind


if __name__ == "__main__":
    verifier.SITE_KIND = InfrastructureSiteKind.MARITIME
    verifier.SURVEY_RADIUS_M = 1_500.0
    raise SystemExit(asyncio.run(verifier.run()))
