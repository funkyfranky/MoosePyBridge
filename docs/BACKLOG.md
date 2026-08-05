# MoosePyBridge Backlog

This file tracks concrete work that is not yet complete. `ROADMAP.md` describes
the architectural direction and completed foundations; this backlog is the
shorter working list for upcoming implementation.

Priorities:

- **P1**: Important for the next usable conflict-simulation increment.
- **P2**: Valuable after the current decision and execution loop is stable.
- **P3**: Longer-term hardening or extension.

## P1 - Decision and execution

- [ ] **Connect incidents to DCS and strategic events.** Convert attributed
  border incursions, weapon fire, hits, unit losses, strategic-object attacks,
  captures, and ceasefire violations into the compact relationship model.
  Deduplicate source events and retain confidence where the attacker is not
  known. Do not add periodic DCS polling solely for diplomacy. Continuous
  ground-border violations with a configurable 60-second tolerance are
  complete, MOOSE `EVENTS.Kill` provides primary destruction attribution
  through `combat.kill`, and hostile airbase captures create strongly weighted
  attributed incidents. MOOSE `OPSZONE:OnAfterCaptured` now supplies
  configurable, context-weighted OPSZONE capture incidents. Weapon-fire, other
  strategic-object attacks, and ceasefire sources remain open.
- [ ] **Validate Kill-event reliability in live DCS missions.** Confirm that
  `EVENTS.Kill` consistently supplies killer and target coalition/object data
  for relevant air, ground, and naval kills. Only if live evidence shows gaps,
  add a bounded last-Hit cache and correlate it with UnitLost/Dead; keep that
  fallback explicitly lower-confidence and avoid forwarding every Hit to
  Python.
- [x] **Apply relationship constraints and doctrine to goal selection.** Block
  offensive goals that are politically invalid in peace or a ceasefire, bound
  limited-conflict goals to their authorized area/effects, and use doctrine
  biases when ranking otherwise valid concurrent goals. Relationship remains a
  hard policy boundary; doctrine is only a preference.
- [ ] **Broaden operational planning beyond CAPTURE, DEFEND, DESTROY, and runway denial.** Generate
  and execute plans for remaining DISABLE effects, PROTECT, and INTERDICT while
  preserving the existing validation, approval, audit, and replanning path.
- [ ] **Add strategic goal selection and prioritization.** Let Python compare
  possible goals using strategic value, current control, visible threats,
  available capabilities, expected cost, and uncertainty. Start with a
  deterministic rule engine before adding an LLM decision layer. The first
  capacity-aware portfolio selector is complete: it permits multiple concurrent
  goals, applies explicit priority ordering, and prevents provisional COHORT
  overbooking across candidate plans. Threat, cost, uncertainty, and objective
  relationship scoring remain to be added.
- [x] **Close the deterministic strategic feedback loop.** Reassess active goals and plans
  after objective ownership changes, losses, INTEL changes, mission outcomes,
  and asset availability changes without duplicating MOOSE tactical behavior.
  The event monitor and policy now produce explicit keep, wait, replan, and
  abort decisions. Temporary shortages preserve active MOOSE missions;
  persistent shortages use DCS mission time and request an approved replan.
  Only terminal goals and unsafe friendly targets trigger automatic aborts.
- [ ] **Relate INTEL changes to goals before proposing replans.** New, lost, or
  reacquired contacts currently remain planning context because a global INTEL
  event does not prove relevance to every active plan. Add spatial, target, and
  information-requirement matching before emitting plan-specific follow-up or
  replan proposals; never replace running AUFTRAGs directly.

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

- [ ] **Extend ammunition/range-aware ranking beyond artillery.** ARTY now uses
  weapon classification, DCS weapon flags, current ammunition, firing position,
  and min/max task ranges for feasibility. Apply current losses, readiness, and
  ammunition evidence to other combat missions where it changes a real
  operational decision.
- [ ] **Expand logistics planning.** Model ammunition supply, rearming, force
  sustainment, and transport as operational dependencies rather than only
  optional support missions. Fuel remains irrelevant for DCS ground and naval
  units unless a later simulation layer adds it deliberately.
- [ ] **Improve force-effectiveness estimates.** Combine unit role, DCS
  attributes, life, active state, ammunition availability, weapon reach, and a
  small logistics contribution for territorial control and planning.

## P2 - Deferred COHORT ranking

- [ ] **Calibrate COHORT score assumptions with live DCS scenarios.** Validate
  the current 50% mission-performance, 30% skill, and 20% response weighting,
  the neutral values for unknown inputs, and the 900-second response reference.
  Introduce mission- or domain-specific values only when observed behavior
  demonstrates a real need.
- [ ] **Replace timing fallbacks with measured capability where available.** Use
  reliable COHORT, template, or spawned OPSGROUP preparation and movement data
  instead of fixed air, ground, naval, and artillery speeds without adding
  periodic polling solely for ranking.
- [ ] **Decide whether force size belongs in the score.** Asset availability is
  currently a hard capacity constraint and unit/group count is deliberately not
  a score component. Revisit combat mass, losses, and remaining unit count only
  with a model that does not reward oversized formations indiscriminately.
- [ ] **Make ranking diagnostics reflect the two-stage decision.** Show only
  COHORT alternatives for the selected AUFTRAG type under `cohort_options`, and
  list lower-priority mission types separately as doctrinal fallbacks. Retain
  the complete raw assignment metadata for audit and debugging.
- [ ] **Verify and expose actual MOOSE recruitment.** Compare Python's predicted
  capacity allocation with the COHORTs and assets recruited by COMMANDER, then
  retain the actual selection in events, execution diagnostics, and audit data.
  Do not assume that repeated `AssignCohort` calls imply score-order preference.
- [ ] **Broaden safe ARTY fallback recruitment.** Synchronize the selected
  weapon range for every otherwise qualified fallback COHORT before submission.
  Until then, only the selected ARTY COHORT and already synchronized alternatives
  with the same weapon flag may enter the COMMANDER recruitment pool.
- [ ] **Validate COHORT skill semantics.** Confirm all values used by the MOOSE
  branch and DCS templates, including `Random` and numeric forms, then replace
  neutral mappings only where the runtime meaning is unambiguous.

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

- [x] A passive event-driven strategic feedback monitor reports goal status,
  plan feasibility, predicted allocation, INTEL context, objective changes, and
  mission outcomes. It emits `replanning_required` on real asset shortfalls and
  reports recovery without mutating plans or issuing DCS commands.
- [x] Cross-domain mission selection first fixes the first executable type in
  the doctrinal AUFTRAG order, then ranks only its COHORTs. Mission performance,
  skill, and response time produce auditable COHORT score components for air,
  ground, naval, and ARTY assignments. Distance and platform speed are combined
  in response time and unknown inputs receive explicit neutral defaults.
- [x] Generated mission requirements retain all qualified COHORTs in score
  order. Phase validation distributes capacity across that order and passes the
  same recruitment pool to MOOSE COMMANDER. ARTY alternatives remain constrained
  by weapon flag and synchronized weapon range.
- [x] Multiple feasible ARTY COHORTs are ranked by required relocation,
  COHORT-specific observed ammunition, remaining rounds, mission performance,
  range-source quality, synchronization state, and available assets. Qualified
  alternatives remain in resolution metadata for diagnostics. No unsupported
  shell-versus-rocket lethality or cost preference is inferred.
- [x] Automatic `ARTY` assignment is restricted to stationary ground or static
  targets and a concrete available COHORT with known deployment position,
  matching indirect-fire weapon flag, ammunition evidence, and a known COHORT
  `engageRange`. Mobile artillery may relocate within that range before firing.
  Missing or stale MOOSE `weaponData` is synchronized from the versioned Python
  datamine profile through `COHORT:AddWeaponRange` before COMMANDER submission.
  The complete decision and synchronization ACK are retained in plan metadata
  and audit diagnostics; execution applies the same flag through
  `AUFTRAG:SetWeaponType()`.
- [x] A central `StrategicMissionResolver` maps strategic effects and DCS/MOOSE
  target domains to prioritized AUFTRAG candidates. CAPTURE isolation, DEFEND
  counterattacks, DESTROY strikes, and runway denial use the same assignment
  path, with current COHORT support selecting the concrete mission type.
- [x] AIRBASE `DISABLE` goals default to `deny_runway`; planning accepts only
  MOOSE `Airdrome` objects and completion requires a successful object-targeted
  `BOMBRUNWAY` AUFTRAG. Unverified BOMBING/ARTY fallbacks are intentionally absent.
- [x] Weighted DESTROY goals create one task per alive, known, targetable
  component while retaining the damage threshold solely as the strategic
  completion condition. COMMANDER execution, component-state refresh,
  confirmation, audit, diagnostics, and the DCS example use the established path.
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
