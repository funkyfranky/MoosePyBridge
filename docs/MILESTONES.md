# Conflict Simulation Milestones

This document defines the shortest path from the current MoosePyBridge
foundation to a persistent conflict in which both coalitions select, attack,
capture, and defend strategic objectives. The deterministic rule engine comes
first. An LLM may later choose among the same validated proposals, but it must
not gain a separate execution path.

Detailed deferred work remains in [BACKLOG.md](BACKLOG.md). The milestones only
contain work required for the end-to-end conflict loop.

## Established foundation

The following capabilities are treated as the starting point rather than new
milestones:

- typed DCS/MOOSE snapshots and mission-scoped reset
- red, blue, and neutral strategic mission scope
- normalized theater data and verified strategic objectives
- coalition-private INTEL and mission-independent detection
- CAPTURE, DEFEND, weighted DESTROY, and runway-denial planning
- diplomacy, doctrine, strategic goal portfolios, and approval policy
- COMMANDER submission, AUFTRAG lifecycle monitoring, strategic assessment,
  audit, and explicit replanning
- one bounded rule-based conflict-controller cycle for one coalition

## Milestone 1: Conflict-ready scenario contract

**Outcome:** A running mission can be declared ready or rejected before either
coalition makes a strategic decision.

**Status:** Completed and accepted against the live Caucasus mission. The
preflight reported the correct theater, three scoped territories, both
coalition force structures, 24 admitted objectives, and no blocking errors.
Blue's lack of a verified opposing SCENERY target remains a non-blocking data
coverage warning.

Required work:

1. Expose the active DCS theater ID and reject a mismatched theater profile.
2. Validate red, blue, and neutral strategic scope, including red/blue overlap.
3. Validate that both coalitions have a COMMANDER, an INTEL picture, and enough
   LEGION/COHORT capability for at least CAPTURE, DEFEND, and DESTROY.
4. Generate the admitted objective set with explicit owner, scope, strategic
   value, targetability, and DCS component evidence.
5. Produce one compact readiness report with blocking errors and non-blocking
   warnings.

Acceptance test:

- Start the Caucasus test mission and run one readiness script.
- It reports the active theater, scope, both force structures, and objective
  counts by coalition and kind.
- A deliberately missing COMMANDER, invalid territory overlap, or wrong theater
  profile blocks the conflict controller before any AUFTRAG is created.

Implementation entry points:

- `MooseBridgeClient.assess_conflict_readiness()` is the controller-independent
  preflight used by rule-based and future LLM decision sources.
- `ConflictReadinessReport.require_ready()` is the hard startup gate.
- `examples/sdk/check_conflict_readiness.py` is the editable live acceptance
  script.

## Milestone 2: Bilateral rule-based decisions

**Outcome:** Blue and red independently produce sensible, explainable goal
portfolios without executing them.

**Status:** Completed and accepted against the live Caucasus mission. Blue and
red independently selected feasible recommendations in two consecutive runs;
the second run created no duplicate goal, plan, or AUFTRAG. The SDK derives
policy-permitted actions, asks the operational planners to prove mission and
asset feasibility, ranks feasible candidates using independent urgency and
resolver-provided response estimates, and adds strategically known force
presence: an AIRWING raises the value of its exact home airbase, a BRIGADE of a
nearby verified military site, and a FLEET of a nearby verified maritime site.
This signal deliberately excludes current asset counts, readiness, and mission
assignments. The SDK reserves capacity within each proposed portfolio and
records stable selection or rejection reasons. Recommendation mode does not
mutate the production Objective, Goal, or Plan registries.

Required work:

1. Run the same bounded decision cycle for either coalition.
2. Derive CAPTURE, DEFEND, and DESTROY candidates from strategic state and each
   coalition's permitted information picture.
3. Rank candidates using relationship policy, doctrine, strategic value,
   current control, visible threat, feasibility, expected response, force
   presence, and uncertainty.
4. Suppress duplicate open goals and respect per-coalition concurrency and
   resource reservations.
5. Explain selected and deferred goals with stable reason codes and retain the
   decision in the audit.

Acceptance test:

- Start in `war` or declare war explicitly.
- Run one blue and one red cycle in recommendation mode.
- Each coalition selects at least one feasible goal when a valid candidate and
  suitable assets exist; friendly, neutral-protected, out-of-scope, unknown,
  and infeasible targets are rejected with explicit reasons.
- Repeating the cycle does not create duplicate goals.

Implementation entry points:

- `MooseBridgeClient.recommend_strategic_portfolio()` evaluates one coalition
  against its own tactical picture.
- `MooseBridgeClient.recommend_bilateral_strategy()` refreshes coalition-private
  INTEL and returns both bounded portfolios from one mission generation.
- `StrategicDecisionConfig` owns concurrency, damage, defense-duration, and
  scoring policy.
- `examples/sdk/recommend_bilateral_strategy.py` is the editable live acceptance
  script.

Current deliberate policy limits:

- AIRBASE objectives may produce runway-denial recommendations, but AIRBASE and
  FARP capture require an associated OPSZONE control mechanism.
- Neutral infrastructure is protected.
- Friendly non-OPSZONE objectives do not yet produce defensive plans.
- Recommendation and execution remain separate until Milestone 3.

## Milestone 3: Autonomous two-sided conflict MVP

**Outcome:** Both coalition controllers can execute bounded strategic decisions
through MOOSE at the same time.

Required work:

1. Add a coordinator that schedules independent blue and red decision cycles
   with configurable cadence and concurrency limits.
2. Submit every approved mission through `MissionExecutionService` and the
   coalition COMMANDER; no controller may issue raw DCS tasking.
3. Keep coalition resource reservations independent and reconcile planned with
   actual MOOSE recruitment.
4. Define collision policy for opposing goals on the same objective. Competing
   CAPTURE/DEFEND goals are valid; duplicate same-coalition work is not.
5. Apply cooldowns after completion, failure, or blocking so an impossible goal
   cannot be resubmitted every cycle.

Implemented foundation:

- `MooseBridgeClient.activate_strategic_decision()` is the sole controlled
  transition from a selected recommendation to mission-scoped Objective, Goal,
  and Plan state. It refreshes current policy and force availability, rejects
  stale recommendations, reserves assets already held by active plans, and is
  idempotent within one recommendation cycle.
- A successful activation leaves the Goal active and the Plan validated. It
  deliberately creates no AUFTRAG.
- `examples/sdk/activate_bilateral_strategy.py` exercises this boundary for
  both coalitions and verifies that no AUFTRAG is submitted.
- `MooseBridgeClient.execute_strategic_activation()` is the sole controlled
  transition from an activation to plan approval and execution. Immediately
  before submission it checks mission generation, relationship state,
  registered Objective/Goal/Plan identity, objective state, duplicate
  execution history, and current phase feasibility. It then delegates to the
  existing `execute_plan()` and `MissionExecutionService` COMMANDER path.
- A failure before an execution attempt is created restores the Plan to
  validated state. Once an attempt exists, its persisted execution record is
  authoritative and the activation cannot be executed again.
- `examples/sdk/execute_bilateral_strategy.py` activates one selected decision
  for each coalition and executes both concurrently as one bounded live test.
- `BilateralConflictCoordinator` schedules blue and red independently using DCS
  mission time. Recommendation and activation are serialized only while shared
  snapshots and reservations are established; COMMANDER execution remains
  concurrent.
- Per-coalition candidate cooldowns distinguish completed, blocked, and failed
  work. Cooldown candidates are deferred before planning, allowing the next
  eligible objective to be selected without creating duplicate Goals or Plans.
- Blocked and failed plans explicitly fail any still-active strategic Goal, so
  duplicate-open-goal protection cannot deadlock later cycles.
- `strategic_conflict_cycle` audit records retain each decision-cycle outcome.
- `examples/sdk/run_bilateral_conflict.py` is the bounded three-cycle live
  acceptance script with editable cadence and cooldown constants.

Milestone 3 acceptance is complete.

Live acceptance status:

- One bounded bilateral cycle has been verified on Caucasus. Blue and red were
  activated concurrently and each completed a full AUFTRAG lifecycle through
  its coalition COMMANDER. The red STRIKE destroyed its verified bridge and
  completed its plan; the blue BOMBRUNWAY failed to damage its runway and
  correctly left its plan blocked. This validates both successful and failed
  terminal execution paths without treating tactical failure as a coordinator
  error.
- A bounded three-cycle-per-coalition Caucasus run completed successfully. Both
  coalitions submitted full AUFTRAG lifecycles through their COMMANDERs while
  executions overlapped. Red completed one verified bridge strike and then
  attempted a verified port; blue attempted runway denial against Sochi-Adler
  and Nalchik. Completed and blocked candidates received cooldowns, later cycles
  selected alternatives while those cooldowns were active, and repeated targets
  were admitted only after their cooldown elapsed. No duplicate open strategic
  requirement remained.
- The same live run exercised mixed terminal outcomes: completed, tactically
  failed, weighted-damage shortfall, and mission-success-with-strategic-shortfall.
  These remained coalition-local and did not stop the opposing controller.
- Recurring coordination remains covered by deterministic SDK tests, including
  next-candidate selection during cooldown, terminalization after blocking, and
  overlapping blue/red execution.

Acceptance test:

- Run both controllers autonomously for at least three decision cycles.
- Blue and red each submit and complete or fail at least one AUFTRAG lifecycle.
- All commands, assignments, outcomes, and strategic assessments are audited.
- No coalition overbooks its own COHORT capacity and no duplicate AUFTRAG is
  created for the same open requirement.

This milestone is the first playable automated-war release.

## Milestone 4: Hold, defend, and react

**Outcome:** Capturing or damaging an objective changes later behavior instead
of ending at the first successful AUFTRAG.

**Status:** Core implementation is complete and the first live Caucasus
acceptance passed. Blue captured `OPSZONE:Town Gali`; completion was confirmed
from the changed OPSZONE owner rather than AUFTRAG success alone; a required
persistent combat `PATROLZONE` remained running; and the red rule engine then
selected CAPTURE of the same objective as its response. The target had no
coalition-visible defender, so one deliberately defended or contested live
capture remains before closing the complete milestone acceptance.

Required work:

1. Confirm CAPTURE from objective ownership, not only from MOOSE mission
   success.
2. After capture, keep useful logistics in the area and assign combat forces to
   persistent ONGUARD and/or PATROLZONE defense according to threat and value.
3. Feed verified SCENERY baseline health and destruction events into objective
   health before and after attacks.
4. Reassess active goals after ownership changes, strategic damage, relevant
   INTEL changes, or meaningful force losses.
5. Replan or reinforce when the strategic condition remains unmet; do not abort
   otherwise valid running missions merely because information changes.

Acceptance test:

- One coalition captures a defended OPSZONE and establishes a combat-capable
  guard rather than leaving only a supply vehicle.
- The opponent subsequently creates a recapture or attack goal.
- Destroying a verified bridge or infrastructure component updates objective
  health, its aggregate strategic loss report, and future goal selection.

Implementation entry points:

- The rule-based CAPTURE planner always follows seizure with a required,
  persistent combat `PATROLZONE`; optional air defense and logistics remain
  independently feasible support tasks.
- Plan execution confirms CAPTURE from refreshed OPSZONE ownership and leaves
  the established patrol in `running` state instead of waiting for it to end.
- `examples/sdk/test_capture_reaction.py` is the bounded live acceptance script
  for capture, ownership confirmation, persistent security, and opponent
  recapture selection.
- `tests/test_operational.py` covers the complete deterministic transition from
  capture through guard establishment to changed opponent goal derivation.

## Milestone 5: Stable mission-length conflict

**Outcome:** The conflict loop survives normal runtime failures and can run for
an entire DCS mission without accumulating contradictory state.

Required work:

1. Exercise reconnects, daemon/client restarts, delayed and reordered events,
   and interrupted AUFTRAG reconciliation.
2. Verify that mission end clears all mission-scoped goals, plans, reservations,
   diplomacy, destruction state, and controller scheduling state.
3. Bound event retention, audit growth, decision frequency, and DCS command
   load.
4. Add deterministic scenario seeds or fixtures where Python controls a choice;
   retain normal DCS combat variability as an observed outcome.
5. Provide one concise campaign status report for operators and tests.

Acceptance test:

- Run a 60-minute two-sided conflict soak test with at least one map-server or
  SDK-client restart.
- End and restart the DCS mission twice.
- No stale goal, reservation, loss, diplomacy incident, or execution attempt
  leaks into the new mission generation.

## Milestone 6: LLM commander on the same rails

**Outcome:** An LLM may prioritize and explain strategic choices without being
able to bypass deterministic safety and execution policy.

Required work:

1. Define a provider-neutral decision request containing the coalition-private
   picture, admissible candidates, doctrine, relationship, constraints, and
   uncertainty.
2. Require a typed response that selects or defers existing candidates and
   provides rationale; the LLM does not invent raw commands or object IDs.
3. Re-run all deterministic policy, feasibility, capacity, and target checks
   after the LLM response.
4. Support `observe`, `recommend`, `approval_required`, and `autonomous` modes
   through the same approval and audit path as the rule engine.
5. Fall back to the deterministic rule engine on timeout, malformed output, or
   rejected choices.

Acceptance test:

- Feed the same recorded tactical picture to the rule engine and an LLM
  adapter.
- Both produce auditable portfolios using only admitted candidates.
- An intentionally invalid LLM choice is rejected before AUFTRAG submission.
- Switching decision sources requires no change to planning or execution code.

## Scope discipline

The following work is deliberately outside the first playable conflict release
unless a milestone acceptance test proves it necessary:

- new strategic goal families beyond CAPTURE, DEFEND, and DESTROY
- a detailed economy or production simulation
- complete logistics and fuel consumption
- perfect historical topography or verification of every infrastructure site
- satellite INTEL
- remote authentication and multi-user administration
- additional infrastructure categories

These remain valid backlog items, but they must not delay Milestones 1-3.
