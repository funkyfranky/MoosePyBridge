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
resolver-provided response estimates, reserves capacity within each proposed
portfolio, and records stable selection or rejection reasons. Recommendation
mode does not mutate the production Objective, Goal, or Plan registries.

Required work:

1. Run the same bounded decision cycle for either coalition.
2. Derive CAPTURE, DEFEND, and DESTROY candidates from strategic state and each
   coalition's permitted information picture.
3. Rank candidates using relationship policy, doctrine, strategic value,
   current control, visible threat, feasibility, expected response, and
   uncertainty.
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
