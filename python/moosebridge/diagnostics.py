"""Human-readable diagnostics for MooseBridge SDK state."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .legions import Cohort, Legion
from .models import Auftrag

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


def _text(value: object, default: str = "-") -> str:
    return str(value) if value not in (None, "") else default


def format_mission_summary(mission: Auftrag) -> str:
    """Return a compact one-line mission summary."""

    return (
        f"{mission.object_id} "
        f"type={_text(mission.type)} "
        f"status={_text(mission.status)} "
        f"assigned={_text(mission.n_assigned)} "
        f"elements={_text(mission.n_elements)}"
    )


def format_cohort_assets(cohort: Cohort, mission_limit: int = 6) -> str:
    """Return a compact one-line COHORT asset summary."""

    missions = ", ".join(cohort.mission_type_keys[:mission_limit]) or "-"
    return (
        f"{cohort.object_id} "
        f"cat={_text(cohort.category)} "
        f"type={_text(cohort.unit_type)} "
        f"assets={_text(cohort.asset_count)} "
        f"stock={_text(cohort.stock_asset_count)} "
        f"spawned={_text(cohort.spawned_asset_count)} "
        f"missions=[{missions}]"
    )


def format_legion_summary(legion: Legion, cohorts: list[Cohort], missions: list[Auftrag]) -> str:
    """Return a two-line LEGION summary."""

    stock_total = sum(cohort.stock_asset_count or 0 for cohort in cohorts)
    spawned_total = sum(cohort.spawned_asset_count or 0 for cohort in cohorts)
    asset_total = sum(cohort.asset_count or 0 for cohort in cohorts)
    header = (
        f"{legion.object_id} "
        f"state={_text(legion.state)} "
        f"coalition={_text(legion.coalition or legion.coalition_name)} "
        f"airbase={_text(legion.airbase_name)}"
    )
    details = (
        f"  cohorts={len(cohorts)} "
        f"assets={asset_total} "
        f"stock={stock_total} "
        f"spawned={spawned_total} "
        f"missions={len(missions)}"
    )
    return f"{header}\n{details}"


def format_legion_status(bridge: MooseBridgeClient, legion_id: str | None = None, timestamp: bool = True) -> str:
    """Return a readable LEGION status report from the SDK state mirror."""

    legions = [bridge.legion(legion_id)] if legion_id else list(bridge.state.legion_objects.values())
    resolved_legions = [legion for legion in legions if legion is not None]

    lines: list[str] = []
    title = "LEGION status"
    if timestamp:
        title = f"[{datetime.now().strftime('%H:%M:%S')}] {title}"
    lines.append(title)
    lines.append("-" * 90)

    if not resolved_legions:
        lines.append("No matching LEGION objects in the current state mirror.")
        return "\n".join(lines)

    for legion in resolved_legions:
        missions = bridge.missions_of_legion(legion.object_id)
        cohorts = bridge.cohorts_of_legion(legion.object_id)
        lines.append(format_legion_summary(legion, cohorts, missions))

        if missions:
            lines.append("  missions:")
            for mission in missions:
                lines.append(f"    {format_mission_summary(mission)}")

        if cohorts:
            lines.append("  cohorts:")
            for cohort in cohorts:
                lines.append(f"    {format_cohort_assets(cohort)}")

    return "\n".join(lines)


__all__ = [
    "format_cohort_assets",
    "format_legion_status",
    "format_legion_summary",
    "format_mission_summary",
]
