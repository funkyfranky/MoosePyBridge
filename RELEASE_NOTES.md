# MoosePyBridge 0.1.0

Released: 2026-08-16

MoosePyBridge 0.1.0 is the first named development baseline. It establishes a
stable semantic interface between a running DCS/MOOSE mission and Python while
keeping DCS as the simulation runtime, MOOSE as the high-level execution layer,
and Python as the owner of tactical and strategic reasoning.

## Highlights

- TCP JSONL bridge with reconnect handling, acknowledgements, snapshots, events,
  local multi-client control, audit logging, and mission-scoped reset behavior.
- Python SDK models for core DCS objects and MOOSE OPS concepts including
  `AUFTRAG`, `COHORT`, `LEGION`, `COMMANDER`, `OPSZONE`, `INTEL`, and sets.
- Typed, Pythonic AUFTRAG constructors and lifecycle controls for the currently
  integrated air, ground, naval, logistics, support, and reconnaissance mission
  families.
- Global truth picture and coalition-specific INTEL pictures with GeoJSON,
  movement history, loss reports, reconnaissance coverage, and diagnostics.
- Browser map with grouped layers, filtering, details, strategic verification,
  DCS F10 markers, territories, frontlines, incursions, and infrastructure.
- Rule-based strategic goals and operational planning for capture, defense,
  destruction, runway denial, asset qualification, phased execution, and
  feedback-based replanning.
- Coalition relationships, doctrine, escalation incidents, border violations,
  captures, and war declaration.
- Ammunition classification, DCS weapon flags, datamine-derived weapon and sensor
  profiles, artillery ranges, and COHORT range synchronization.
- GermanyCW topography workflow with connected land and water, coastline,
  strategic road routing, bridges, junctions, railways, settlements, military,
  industrial, energy, fuel, and maritime infrastructure.
- Scenario-specific DCS infrastructure verification using immutable observed
  baselines, selected target components, and damage assessment.

## Compatibility

- Python 3.10 or newer.
- MOOSE `FF/Ops` is the actively tested branch for the current project.
- DCS and MOOSE remain authoritative for simulation state and AUFTRAG execution.
- Python snapshots and events are mission-scoped and reset on DCS mission end.

## Known Limitations

- The control interfaces currently assume trusted local clients and do not yet
  provide authentication or authorization for remote use.
- GermanyCW is the only theater with the complete topography and infrastructure
  preparation workflow validated so far.
- OSM-derived geography can differ from the historical DCS theater and therefore
  remains an approximation unless verified against DCS.
- Infrastructure verification is intentionally scenario-specific; unverified or
  unrepresented sites are not automatically admitted as targetable objectives.
- Several live-DCS behaviors remain covered by manual integration scripts rather
  than an automated end-to-end test environment.
- Public SDK and protocol compatibility will be preserved deliberately from this
  baseline, but pre-1.0 additions may still require documented migrations.

## Release Validation

The release procedure is documented in
[`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).
