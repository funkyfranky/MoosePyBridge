"""Interactively verify fixed DCS scenery from F10 marker commands.

Start this example during a mission, then create or edit an F10 marker whose
first line is ``verify OBJECT_ID``. The marker position becomes the center of a
bounded SCENERY survey. The script draws the result, asks before persisting a
baseline, clears the overlay, and waits for the next marker.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from example_support import load_example_scenery_feature, open_example_session, run_example
from verify_scenery_representation import (
    COMMAND_TIMEOUT_SECONDS,
    MAX_SCENERY_OBJECTS,
    OVERLAY_ID,
    assess_current_survey,
    classify_survey_objects,
    format_assignments,
    format_feature,
    format_marker,
    format_survey,
    format_verification,
    include_assigned_objects,
    load_verification_registry,
    merge_survey_objects,
    overlay_markups,
    save_observed_baseline,
    survey_radius_m,
)

from moosebridge import (  # noqa: E402
    MooseBridgeClient,
    SceneryVerificationMarker,
    scenery_verification_marker_from_event,
    scenery_zone_assignments,
)
from moosebridge.control import DEFAULT_CONTROL_PORT  # noqa: E402


CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = DEFAULT_CONTROL_PORT

# None searches all bundled theater profiles for each marker object ID.
THEATER_PROFILE: str | Path | None = None

# None uses `radius` from the marker and then the feature-specific default.
# A value here deliberately overrides both for every marker handled by this run.
SURVEY_RADIUS_OVERRIDE_M: float | None = None

SAVE_OBSERVED_BASELINE = True
DRAW_F10_OVERLAY = True


def marker_signature(marker: SceneryVerificationMarker) -> tuple:
    """Identify duplicate add/change events for the same marker state."""

    return (
        marker.marker_id,
        marker.text,
        round(marker.latitude, 7),
        round(marker.longitude, 7),
    )


def selected_radius_m(marker: SceneryVerificationMarker, feature) -> float:
    if SURVEY_RADIUS_OVERRIDE_M is None:
        return survey_radius_m(feature, marker)
    if not 0 < SURVEY_RADIUS_OVERRIDE_M <= 5_000:
        raise ValueError("SURVEY_RADIUS_OVERRIDE_M must be in range 0..5000 or None")
    return SURVEY_RADIUS_OVERRIDE_M


async def confirmation(existing_baseline: bool) -> str:
    if existing_baseline:
        prompt = "[Enter] keep existing baseline, [r] replace, [s] skip, [q] quit: "
    else:
        prompt = "[Enter] save baseline, [s] skip, [q] quit: "
    return (await asyncio.to_thread(input, prompt)).strip().casefold()


async def process_marker(
    bridge: MooseBridgeClient,
    marker: SceneryVerificationMarker,
) -> bool:
    if marker.option_errors:
        print(
            f"\nMarker {marker.marker_id} rejected: "
            + "; ".join(marker.option_errors)
        )
        return True

    theater, theater_paths, feature = load_example_scenery_feature(
        marker.source_id,
        THEATER_PROFILE,
    )
    verifications_path = theater_paths.path("strategic_verifications")
    radius_m = selected_radius_m(marker, feature)

    await bridge.snapshot_zones()
    assignments = scenery_zone_assignments(feature.object_id, bridge.state.zones)
    survey = await bridge.survey_scenery(
        marker.latitude,
        marker.longitude,
        radius_m=radius_m,
        max_results=MAX_SCENERY_OBJECTS,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if assignments:
        resolution = await bridge.resolve_scenery_objects(
            (item.scenery_object_id for item in assignments),
            zone_names={item.scenery_object_id: item.zone_name for item in assignments},
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        survey = merge_survey_objects(survey, resolution.objects)
    included, nearby = classify_survey_objects(feature, survey)
    included, nearby = include_assigned_objects(
        feature,
        included,
        nearby,
        survey,
        assignments,
    )

    print()
    format_feature(feature, theater.theater_id)
    format_verification(feature, theater.theater_id, verifications_path)
    format_marker(feature, marker)
    format_survey(feature, survey, included, nearby, assignments)
    format_assignments(assignments, survey)

    drawn = False
    try:
        if DRAW_F10_OVERLAY:
            await bridge.draw_debug_overlay(
                OVERLAY_ID,
                overlay_markups(
                    feature,
                    radius_m,
                    marker.latitude,
                    marker.longitude,
                    included,
                    nearby,
                    {item.scenery_object_id for item in assignments},
                ),
                replace=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
            drawn = True
            print("\nInspect the feature and marked SCENERY objects in DCS F10.")

        registry = load_verification_registry(theater.theater_id, verifications_path)
        existing = registry.get(feature.object_id)
        existing_baseline = existing is not None and bool(existing.observed_objects)
        choice = await confirmation(existing_baseline)
        if choice == "q":
            return False
        should_save = (
            SAVE_OBSERVED_BASELINE
            and choice not in {"s", "skip"}
            and (not existing_baseline or choice in {"r", "replace"})
        )
        if should_save:
            verification = save_observed_baseline(
                feature,
                survey,
                included,
                assignments,
                theater.theater_id,
                verifications_path,
            )
            completeness = "complete" if verification.observation_complete else "partial"
            print(
                f"Saved {len(verification.observed_objects)} SCENERY object(s) as a "
                f"{completeness} baseline: {verifications_path}"
            )
        elif existing_baseline and choice not in {"s", "skip"}:
            print("Existing observation baseline preserved.")
        else:
            print("Observation baseline not changed.")

        assess_current_survey(
            bridge,
            feature,
            survey,
            included,
            assignments,
            theater.theater_id,
            verifications_path,
        )
    finally:
        if drawn:
            await bridge.clear_debug_overlay(OVERLAY_ID, timeout=COMMAND_TIMEOUT_SECONDS)
    return True


async def run() -> int:
    session = await open_example_session(
        CONTROL_HOST,
        CONTROL_PORT,
        COMMAND_TIMEOUT_SECONDS,
    )
    bridge: MooseBridgeClient = session.bridge
    cursor = await bridge.server.event_cursor()
    handled_signatures: set[tuple] = set()

    print("F10 scenery verification monitor")
    print("=" * 96)
    print("Create or edit a marker after this monitor starts. Example:")
    print("  verify BRIDGE:Caucasus:04b3c5b8894c")
    print("  radius 250m")
    print("  optional note")
    print("\nWaiting for F10 marker commands. Press Ctrl+C to stop.")

    while True:
        event = await bridge.server.wait_for_event(
            "map.marker.*",
            timeout=24 * 60 * 60,
            after_id=cursor,
        )
        cursor = str(event.get("id") or "") or cursor
        if str(event.get("event") or "") == "mission.ended":
            print("\nDCS mission ended; verification monitor stopped.")
            return 0
        marker = scenery_verification_marker_from_event(event)
        if marker is None:
            continue
        signature = marker_signature(marker)
        if signature in handled_signatures:
            continue
        handled_signatures.add(signature)
        try:
            if not await process_marker(bridge, marker):
                return 0
        except ValueError as exc:
            print(f"\nMarker {marker.marker_id} rejected: {exc}")


if __name__ == "__main__":
    raise SystemExit(run_example(run))
