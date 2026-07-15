"""Human-readable diagnostics for MooseBridge SDK state."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .legions import Cohort, Legion
from .models import Auftrag, Intel, IntelCluster, IntelContact
from .pictures import GlobalPicture, PictureValidationIssue

if TYPE_CHECKING:
    from .sdk import MooseBridgeClient


def _text(value: object, default: str = "-") -> str:
    return str(value) if value not in (None, "") else default


def _clock_title(picture: GlobalPicture) -> str:
    clock = picture.clock
    if not clock:
        return datetime.now().strftime("%H:%M:%S")
    values = [f"wall={clock.wall_time or '-'}"]
    if clock.time_of_day is not None:
        dcs_date = clock.dcs_date or f"D+{clock.day_offset or 0}"
        values.append(f"dcs={dcs_date} {clock.time_of_day}")
    if clock.mission_elapsed is not None:
        values.append(f"mission={clock.mission_elapsed}")
    return " | ".join(values)


def format_picture_issue(issue: PictureValidationIssue) -> str:
    """Return one human-readable picture validation issue."""

    object_label = f" {issue.object_id}" if issue.object_id else ""
    return f"{issue.severity.upper()} {issue.code}{object_label}: {issue.message}"


def format_global_picture_status(picture: GlobalPicture, *, issue_limit: int = 20) -> str:
    """Return counts and consistency diagnostics for a global picture."""

    counts = picture.counts()
    alive_groups = sum(item.get("alive") is True for item in picture.groups)
    alive_units = sum(item.get("alive") is True for item in picture.units)
    alive_statics = sum(item.get("alive") is True for item in picture.statics)
    coalitions = {
        coalition: sum(item.get("coalition") == coalition for item in picture.groups)
        for coalition in ("blue", "red", "neutral")
    }
    issues = picture.validate()
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)

    lines = [
        f"[{_clock_title(picture)}] Global picture",
        "-" * 90,
        (
            f"truth: groups={counts['groups']} (alive={alive_groups}) "
            f"units={counts['units']} (alive={alive_units}) "
            f"statics={counts['statics']} (alive={alive_statics}) "
            f"airbases={counts['airbases']} zones={counts['zones']}"
        ),
        (
            f"coalitions/groups: blue={coalitions['blue']} red={coalitions['red']} "
            f"neutral={coalitions['neutral']} unknown={counts['groups'] - sum(coalitions.values())}"
        ),
        (
            f"ops: opszones={counts['opszones']} opsgroups={counts['opsgroups']} "
            f"missions={counts['missions']} legions={counts['legions']} cohorts={counts['cohorts']}"
        ),
        (
            f"intel: objects={counts['intels']} contacts={counts['intel_contacts']} "
            f"clusters={counts['intel_clusters']}"
        ),
        f"validation: errors={errors} warnings={warnings}",
    ]
    for issue in issues[:issue_limit]:
        lines.append(f"  {format_picture_issue(issue)}")
    if len(issues) > issue_limit:
        lines.append(f"  ... {len(issues) - issue_limit} more")
    return "\n".join(lines)


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


def format_intel_contact(contact: IntelContact) -> str:
    """Return a compact one-line INTEL contact summary."""

    position = "-"
    if contact.x is not None and contact.z is not None:
        position = f"x={contact.x:.0f} z={contact.z:.0f}"
    return (
        f"{contact.object_id} "
        f"target={_text(contact.target_object_id)} "
        f"type={_text(contact.contact_type)} "
        f"threat={_text(contact.threat_level)} "
        f"recce={_text(contact.recce)} "
        f"speed={_text(contact.speed_mps)} "
        f"{position}"
    )


def format_intel_cluster(cluster: IntelCluster) -> str:
    """Return a compact one-line INTEL cluster summary."""

    position = "-"
    if cluster.x is not None and cluster.z is not None:
        position = f"x={cluster.x:.0f} z={cluster.z:.0f}"
    return (
        f"{cluster.object_id} "
        f"type={_text(cluster.contact_type or cluster.category)} "
        f"size={_text(cluster.size)} "
        f"threat_max={_text(cluster.threat_level_max)} "
        f"threat_sum={_text(cluster.threat_level_sum)} "
        f"{position}"
    )


def format_intel_summary(intel: Intel, contacts: list[IntelContact], clusters: list[IntelCluster]) -> str:
    """Return a two-line INTEL summary."""

    header = (
        f"{intel.object_id} "
        f"state={_text(intel.state)} "
        f"running={intel.is_running} "
        f"coalition={_text(intel.coalition)} "
        f"alias={_text(intel.alias)}"
    )
    agent_count = intel.agent_count if intel.agent_count is not None else len(intel.agent_ids)
    agents = f"{intel.alive_agent_count}/{agent_count}" if intel.alive_agent_count is not None else str(agent_count)
    details = (
        f"  contacts={len(contacts)} "
        f"clusters={len(clusters)} "
        f"agents={agents} "
        f"cluster_analysis={intel.cluster_analysis} "
        f"radius_m={_text(intel.cluster_radius_m)}"
    )
    return f"{header}\n{details}"


def format_intel_status(
    bridge: MooseBridgeClient,
    intel_id: str | None = None,
    *,
    contact_limit: int = 12,
    cluster_limit: int = 8,
    timestamp: bool = True,
) -> str:
    """Return a readable INTEL status report from the SDK state mirror."""

    intels = [bridge.intel(intel_id)] if intel_id else list(bridge.state.intel_objects.values())
    resolved_intels = [intel for intel in intels if intel is not None]

    lines: list[str] = []
    title = "INTEL status"
    if timestamp:
        clock = bridge.state.clock
        if clock:
            values = [f"wall={clock.wall_time or '-'}"]
            if clock.time_of_day is not None:
                dcs_date = clock.dcs_date or f"D+{clock.day_offset or 0}"
                values.append(f"dcs={dcs_date} {clock.time_of_day}")
            if clock.mission_elapsed is not None:
                values.append(f"mission={clock.mission_elapsed}")
            title = f"[{' | '.join(values)}] {title}"
        else:
            title = f"[{datetime.now().strftime('%H:%M:%S')}] {title}"
    lines.append(title)
    lines.append("-" * 90)

    if not resolved_intels:
        lines.append("No matching INTEL objects in the current state mirror.")
        return "\n".join(lines)

    for intel in resolved_intels:
        contacts = bridge.contacts_of_intel(intel.object_id)
        clusters = bridge.clusters_of_intel(intel.object_id)
        contacts = sorted(contacts, key=lambda item: item.threat_level or 0, reverse=True)
        clusters = sorted(clusters, key=lambda item: item.threat_level_sum or 0, reverse=True)
        lines.append(format_intel_summary(intel, contacts, clusters))

        if contacts:
            lines.append("  contacts:")
            for contact in contacts[:contact_limit]:
                lines.append(f"    {format_intel_contact(contact)}")
            if len(contacts) > contact_limit:
                lines.append(f"    ... {len(contacts) - contact_limit} more")

        if clusters:
            lines.append("  clusters:")
            for cluster in clusters[:cluster_limit]:
                lines.append(f"    {format_intel_cluster(cluster)}")
            if len(clusters) > cluster_limit:
                lines.append(f"    ... {len(clusters) - cluster_limit} more")

    return "\n".join(lines)


__all__ = [
    "format_cohort_assets",
    "format_global_picture_status",
    "format_intel_cluster",
    "format_intel_contact",
    "format_intel_status",
    "format_intel_summary",
    "format_legion_status",
    "format_legion_summary",
    "format_mission_summary",
    "format_picture_issue",
]
