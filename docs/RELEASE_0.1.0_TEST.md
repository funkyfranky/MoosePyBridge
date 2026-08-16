# MoosePyBridge 0.1.0 Live Test

Use the designated GermanyCW release mission. Start the components in this
order:

1. `run_server.ps1`
2. `run_map.ps1`
3. Start the DCS mission and wait until the bridge reports a connection.

Run the non-destructive automated smoke test:

```powershell
python examples/sdk/release_smoke_test.py
```

It refreshes the global picture, checks the required DCS/MOOSE snapshots,
validates the local event service, checks all configured static map datasets,
and briefly draws and removes a cyan F10 overlay near an airbase. It does not
submit an AUFTRAG or damage mission objects.

After it passes, complete two manual checks:

1. Run `python examples/sdk/run_auftrag_lifecycle.py` (or another representative
   AUFTRAG example suitable for the release mission) and
   confirm `Planned -> Queued -> Requested -> Scheduled -> Started` followed by
   a valid terminal result.
2. Run `python examples/sdk/test_mission_reset.py`, end and restart the mission
   twice as prompted, and confirm that every generation and local reset check
   passes.

Record any skipped or failed check in the `v0.1.0` release description. A
scenario-specific AUFTRAG failure is acceptable only when the bridge lifecycle,
outcome, and reason were transmitted correctly and the skipped success case is
documented.

## Validated Reference Run

The live release checks passed on 2026-08-16 with the GermanyCW release
mission:

- Automated smoke test: 24 passed, 0 warnings, 0 failures.
- F10 overlay: one native markup drawn and removed successfully.
- Mission reset: two mission-end and restart cycles passed; both local SDK and
  daemon mission-scoped data were empty after each reset.
- AUFTRAG lifecycle: a 60-second `ONGUARD` mission progressed through queueing,
  recruitment, scheduling, start, and execution before the duration limit
  produced MOOSE's valid `Done -> Cancel -> Evaluated` terminal sequence.
  Evaluation reported `success=True`, seven elements, and no casualties.

MOOSE may emit `Done` before `Cancel` for duration-limited missions. The SDK
waits for the subsequent evaluated summary and uses that summary as the
authoritative outcome.
