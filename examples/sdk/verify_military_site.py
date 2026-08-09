"""Compatibility entry point for military-site scenery verification."""

from __future__ import annotations

import asyncio

import verify_infrastructure_site as verifier
from moosebridge import InfrastructureSiteKind


if __name__ == "__main__":
    verifier.SITE_KIND = InfrastructureSiteKind.MILITARY
    raise SystemExit(asyncio.run(verifier.run()))
