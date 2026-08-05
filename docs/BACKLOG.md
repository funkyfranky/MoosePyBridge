# MoosePyBridge Backlog

This file tracks concrete work that is not yet complete. `ROADMAP.md` describes
the architectural direction and completed foundations; this backlog is the
shorter working list for upcoming implementation.

Priorities:

- **P1**: Important for the next usable conflict-simulation increment.
- **P2**: Valuable after the current decision and execution loop is stable.
- **P3**: Longer-term hardening or extension.

## P1 - Decision and execution

- [ ] **Broaden operational planning beyond CAPTURE, DEFEND, DESTROY, and runway denial.** Generate
  and execute plans for remaining DISABLE effects, PROTECT, and INTERDICT while
  preserving the existing validation, approval, audit, and replanning path.
- [ ] **Add strategic goal selection and prioritization.** Let Python compare
  possible goals using strategic value, current control, visible threats,
  available capabilities, expected cost, and uncertainty. Start with a
  deterministic rule engine before adding an LLM decision layer.
- [ ] **Close the strategic feedback loop.** Reassess active goals and plans
  after objective ownership changes, losses, INTEL changes, mission outcomes,
  and asset availability changes without duplicating MOOSE tactical behavior.

## P1 - Intelligence and RECON

- [ ] **Optional satellite picture.** Provide an explicit omniscient INTEL
  source that can add all relevant groups as known contacts independently of
  normal DCS detection. The Lua integration should use
  `INTEL:KnowObject(Positionable, RecceName, Tdetected)` and clearly identify
  the synthetic recce source, for example `Satellite`. This mode must remain
  opt-in and separate from the normal coalition-private, sensor-derived
  tactical picture.
- [ ] **Define satellite refresh semantics.** Decide whether satellite data is
  a one-time pass, a periodic pass, or operator-triggered; define coalition
  scope, refresh interval, and how `Tdetected` and stale/lost contacts behave.

## P2 - Forces and sustainment

- [ ] **Use ammunition and task-range profiles in operational decisions.** Move
  the existing weapon classification, DCS weapon flags, and min/max task ranges
  from diagnostics into mission feasibility and asset ranking. This is also
  required before `ARTY` can participate in automatic mission assignment.
- [ ] **Expand logistics planning.** Model ammunition supply, rearming, force
  sustainment, and transport as operational dependencies rather than only
  optional support missions. Fuel remains irrelevant for DCS ground and naval
  units unless a later simulation layer adds it deliberately.
- [ ] **Improve force-effectiveness estimates.** Combine unit role, DCS
  attributes, life, active state, ammunition availability, weapon reach, and a
  small logistics contribution for territorial control and planning.

## P2 - Tactical picture

- [ ] **Expose goals and operational plans on the browser map.** Show objective
  status, coalition intent, active plan phase, assigned missions, warnings, and
  blocked reasons with coalition-appropriate visibility.
- [ ] **Add historical analysis controls.** Allow inspection of losses, INTEL
  changes, frontline movement, objective ownership, and mission activity over
  a selected DCS-time window.

## P3 - Platform hardening

- [ ] **Add authenticated remote clients.** Build authentication and
  authorization on top of the existing declared client identity and audit
  envelope before exposing the control service beyond trusted networks.
- [ ] **Continue protocol and snapshot hardening.** Expand typed snapshots and
  schemas only where required by operational features, with replay and
  compatibility tests for state-changing events.
- [ ] **Add long-running DCS integration scenarios.** Exercise reconnects,
  mission restarts, multiple clients, audit restore, event ordering, and map
  updates over extended missions.

## Recently completed

- [x] A central `StrategicMissionResolver` maps strategic effects and DCS/MOOSE
  target domains to prioritized AUFTRAG candidates. CAPTURE isolation, DEFEND
  counterattacks, DESTROY strikes, and runway denial use the same assignment
  path, with current COHORT support selecting the concrete mission type.
- [x] AIRBASE `DISABLE` goals default to `deny_runway`; planning accepts only
  MOOSE `Airdrome` objects and completion requires a successful object-targeted
  `BOMBRUNWAY` AUFTRAG. Unverified BOMBING/ARTY fallbacks are intentionally absent.
- [x] Weighted DESTROY goals, rule-based component selection, COMMANDER
  execution, component-state refresh, strategic confirmation, audit roundtrip,
  diagnostics, and a parameterless DCS example use the established plan path.
- [x] DESTROY events, pretty-print diagnostics, and audits distinguish MOOSE
  AUFTRAG outcomes from evidence-derived weighted strategic damage assessments.
- [x] Object-targeted AUFTRAG `Summary.damage` supplements snapshot component
  health cumulatively without double counting; source attribution survives audit.
- [x] DESTROY shortfalls can be replanned against already damaged components;
  the DCS example demonstrates bounded, separately approved strike rounds.
- [x] Rule-based DEFEND proposals and deadline-aware execution use the existing
  COMMANDER, validation, event, cleanup, audit, and replanning path.
- [x] Deadline-based DEFEND execution was validated in a live DCS mission with
  required ground defense and optional logistics tasking.
- [x] Browser-map layers are grouped into compact force, territorial-control,
  zone, intelligence, infrastructure, operations, and event sections.
- [x] Direct and operational RECON share route sampling and spatial coverage.
- [x] Direct `execute_recon()` results are persisted and displayed by the map.
- [x] INTEL contact acquisition is independent of AUFTRAG lifecycle and accepts
  observations from every coalition INTEL agent.
- [x] Information requirements track open, partial, satisfied, and lost states
  without cancelling a running RECON mission.
