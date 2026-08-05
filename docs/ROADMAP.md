# MoosePyBridge Roadmap

Concrete pending work is maintained in [BACKLOG.md](BACKLOG.md).

## Vision

MoosePyBridge is a semantic Python environment for DCS missions built on MOOSE.
It should make DCS/MOOSE mission state available to Python, expose MOOSE and OPS
objects as stable typed models, and provide controlled ways to command the
mission through MOOSE semantics.

The long-term target is an agent-capable command environment:

- Python mirrors the battlefield state.
- Tactical and strategic reasoning layers interpret that state.
- Operator tools and agents propose useful actions.
- Approved or autonomous actions are executed only through semantic MOOSE/OPS
  commands such as AUFTRAG and OPS tasking.

The bridge is not meant to be a generic raw DCS scripting tunnel. DCS remains the
simulation runtime, MOOSE remains the mission semantics layer, and Python becomes
the external analysis, decision, and control layer.

## Operating model

MoosePyBridge should work in both single-player and multiplayer or dedicated
server scenarios.

The preferred runtime shape is:

1. One DCS mission loads the Lua bridge.
2. One Python bridge daemon owns the DCS-facing TCP connection.
3. Multiple Python clients, tools, or agents connect to the daemon through a
   local or network-facing control API.
4. All command execution goes through validation, policy, and audit-friendly
   semantic actions.

Initial local defaults:

- DCS-facing bridge port: `42000`
- Python control port: `42001`

## Guiding principles

- DCS is the authoritative source of simulation state.
- MOOSE is the authoritative semantic model for mission objects.
- Python consumes stable protocol objects, not raw MOOSE internals.
- The external protocol should remain stable even if MOOSE internals evolve.
- Commands should be MOOSE/OPS-semantic, not low-level DCS scripting snippets.
- Agents command through AUFTRAG/OPS and do not micromanage units directly.
- Human approval and autonomous execution should use the same validated command
  path.
- Dedicated server and multiplayer operation are first-class requirements.
- Auditability matters: recommendations, approvals, commands, ACKs, and outcomes
  should be traceable.

## Architecture layers

### 1. Mission state mirror

The first layer mirrors mission state from DCS/MOOSE into Python.

Current object families:

- GROUP
- UNIT
- STATIC
- AIRBASE
- ZONE
- OPSZONE
- OPSGROUP
- AUFTRAG
- COHORT
- LEGION

Planned object families:

- AIRWING
- BRIGADE
- FLEET
- COMMANDER
- CHIEF
- DETECTION
- EVENT

The Python mirror should preserve stable object identity:

- `object_id`
- `dcs_name`
- `object_type`
- `category`
- `coalition`
- `birth_time` where available

Raw snapshots remain useful for debugging and forward compatibility. Typed
models should be added where the bridge has enough stable semantics.

### 2. Tactical reasoning and advisory layer

The second layer interprets the mirrored state and produces structured
recommendations.

It should answer operational questions such as:

- Which OPSZONEs are threatened, empty, guarded, captured, or contested?
- Which OPSGROUPs are available, assigned, moving, executing, or destroyed?
- Which AUFTRAG objects are scheduled, started, executing, successful, failed, or
  cancelled?
- Which LEGION/COHORT assets are available, stocked, in range, and suitable for
  a requested mission?
- Which friendly or neutral targets must be rejected?
- Which attacks, defenses, patrols, or troop movements are tactically useful?
- What confidence, risks, assumptions, and required approvals apply?

Recommendations should be structured objects, not prose only. They should carry
the intended action, rationale, risk, candidate assets, required command payload,
and approval/autonomy requirements.

### 3. Controlled action layer

The third layer sends controlled commands back into MOOSE.

Current command families:

- `message.*`
- `mark.*`
- `smoke.*`
- `explosion.*`
- `object.coords`
- `object.distance`
- `zone.draw`
- `snapshot.*`
- selected `auftrag.*`
- AUFTRAG trace helpers

Planned command families:

- broader `auftrag.*` creation, cancellation, assignment, and monitoring
- `opsgroup.*`
- `opszone.*`
- `commander.*`
- `chief.*`
- `airwing.*`
- `brigade.*`
- `fleet.*`

Commands should remain whitelisted, parameterized, and semantic. The controlled
action layer should never become an arbitrary Lua execution API.

### 4. Server and client layer

The bridge daemon should be the central owner of the DCS connection. Client
tools should connect to the daemon instead of each starting their own bridge.

Near-term server needs:

- stable multi-client state queries (baseline implemented)
- command forwarding through the daemon (baseline implemented)
- snapshot orchestration (baseline implemented)
- SDK adapter for daemon-backed control clients (baseline implemented)
- raw protocol logging
- error reporting suitable for tools and agents

Later server needs:

- remote client access
- authentication and role-based permissions
- session tracking
- audit log for recommendations, approvals, commands, ACKs, and outcomes
- replayable state and event history

### 5. Agent layer

The agent layer should support both strategic and tactical behavior.

Strategic mode thinks like a commander:

- maintain a situation picture
- identify priorities and threats
- decide where to attack, defend, patrol, or reinforce
- allocate LEGION/COHORT resources through OPS semantics

Tactical mode reasons closer to the current fight:

- choose suitable targets
- select available assets
- validate range, coalition, payload, and mission type
- create or recommend AUFTRAG actions
- monitor outcomes and adapt

Execution modes:

- `observe`: no recommendations or commands
- `recommend`: produce proposals only
- `approval_required`: prepare executable commands but wait for approval
- `autonomous`: execute within explicit policy constraints

Autonomy should be a mode on top of the same advisory, validation, and command
path used by human-operated tools.

## Protocol direction

The protocol should remain line-oriented JSON for now.

Core message types:

- `heartbeat`
- `snapshot`
- `event`
- `command`
- `ack`
- `error`

Snapshot kinds should be object-family oriented:

- `groups`
- `units`
- `statics`
- `airbases`
- `zones`
- `objects`
- `opszones`
- `opsgroups`
- `auftraege`
- `cohorts`
- `legions`

The protocol should prefer references over deeply nested objects. For example,
an OPSGROUP references its current AUFTRAG with `auftrag_current_id`, while the
AUFTRAG exists as a separate snapshot object.

## Phase 1: Stabilize state snapshots

Goal: Python knows the mission world.

Current baseline:

- GROUP snapshot
- UNIT snapshot
- STATIC snapshot
- AIRBASE snapshot
- ZONE snapshot
- OPSZONE snapshot
- OPSGROUP snapshot
- AUFTRAG snapshot
- COHORT snapshot
- LEGION snapshot
- typed Python models for OPSZONE, OPSGROUP, AUFTRAG, target snapshots, COHORT,
  LEGION, and AUFTRAG outcomes

Next work items:

1. Expand and harden AUFTRAG snapshot details, especially timing, target, summary,
   and outcome fields.
2. Add AIRWING/BRIGADE/FLEET snapshots.
3. Add CHIEF snapshots after COMMANDER tasking has been validated in DCS.
4. Add replayable event snapshots or event streams for state changes.
5. Add tests for additional AUFTRAG advisory edge
   cases.

## Phase 2: Typed Python state model

Goal: Prefer typed access while preserving raw snapshot payloads.

Typed model priorities:

- Group
- Unit
- StaticObject
- Airbase
- Zone
- OpsZone
- OpsGroup
- Auftrag
- TargetSnapshot
- Cohort
- Legion
- Commander
- AuftragOutcome
- later Airwing, Brigade, Fleet, Chief

Example target API:

```python
auftrag = bridge.state.auftrag("AUFTRAG:1")
print(auftrag.type)
print(auftrag.status)
print(auftrag.assigned_group_ids)
```

## Phase 3: Advisory and recommendation model

Goal: Convert state analysis into executable, explainable proposals.

The advisory layer should produce structured recommendations for:

- attacking known targets
- defending threatened OPSZONEs
- patrolling or screening areas
- reinforcing or moving ground/naval forces
- selecting suitable LEGION/COHORT assets
- rejecting unsafe or impossible missions

Each recommendation should include:

- intent
- target or defended area
- candidate asset
- selected command family
- command payload
- rationale
- risk and assumptions
- confidence
- required approval mode

Current operational-planning baseline:

- `StrategicGoal` is translated into a human-reviewable `OperationalPlan`.
- Ordered `PlanPhase` objects contain `MissionIntent` and `AssetRequirement`
  objects rather than executable commands.
- Validation uses coalition-owned LEGION/COHORT stock, supported AUFTRAG types,
  platform categories, payload readiness, and explicit preferred/allowed
  LEGION constraints.
- Same-phase requirements compete for finite COHORT stock; later phases may
  reuse surviving assets.
- Feasible plans can be approved and explicitly executed through a coalition
  COMMANDER. The event-driven executor covers CAPTURE, weighted DESTROY, and deadline-based DEFEND
  plans, automatic phase progression, parallel required AUFTRAG monitoring, optional support
  missions, one-shot target existence preflight, and blocked-state handoff
  without automatic retries.
- Blocked plans can be returned explicitly to draft state. Completed phases
  are preserved, remaining targets and allowed LEGION/COHORT constraints can
  be revised, and a fresh validation plus approval is required before resume.
  An explicit resume phase may reopen that phase and all following phases when
  strategic goal confirmation failed after their AUFTRAGs completed.
- Each execution has a stable attempt id and remains available in chronological
  runtime history; changing the COMMANDER for a later attempt is supported.
- Operational execution snapshots are persisted in the daemon's versioned,
  append-only JSONL audit store and can be restored by a new SDK process.
- The SDK can reconstruct and register the audited strategic objective, goal,
  operational plan, phase states, and execution history without issuing DCS
  commands. Blocked plans re-enter the normal explicit retry workflow.
- Interrupted `executing` attempts can be reconciled through one AUFTRAG
  snapshot and optionally reattached to existing FSM events. Missing missions
  remain indeterminate until an operator explicitly blocks them; reconciliation
  never creates a replacement AUFTRAG.
- Operational attempts can be explicitly aborted. One current AUFTRAG snapshot
  identifies live MOOSE missions, the default scope cancels the complete
  attempt, and partial cancellation failures leave the plan blocked and
  auditable instead of reporting a false successful abort.
- Every immediate phase now has an execution-boundary revalidation. Current
  COMMANDER, LEGION, COHORT, strategic-control, allocation, constraint, and
  target state is refreshed before any phase AUFTRAG is submitted; completed
  and later phases are not unnecessarily reassessed.
- Plan snapshots retain explicit operator attribution and approval reasons.
  Submitted missions retain compact ACK ids, correlation ids, sequence numbers,
  and relevant results across daemon audit persistence and SDK restore.
- Operational plans can carry optional typed recommendation provenance for an
  operator, rule engine, LLM, or imported source, including source id, tactical
  picture mission time, and rationale. Provenance is preserved through audit
  persistence and restore independently of the approving client.
- A conservative rule-based planner creates unregistered CAPTURE, DEFEND, and
  weighted DESTROY drafts from coalition-specific tactical pictures. It
  uses visible INTEL contacts for optional isolation or counterattack and never
  reads global truth; registration, validation, approval, and execution remain
  explicit SDK steps.
- Weighted DESTROY goals select enough objective components to meet a configurable
  damage fraction. Static infrastructure is known by position; moving targets
  require current coalition INTEL. Execution refreshes component state at phase
  boundaries and confirms weighted objective health without status polling.
  Parallel strikes settle before assessment, so strategic damage rather than an
  individual AUFTRAG success flag determines DESTROY completion.
- DESTROY diagnostics and audits explicitly separate constructor-specific MOOSE
  AUFTRAG outcomes from snapshot-derived strategic damage assessments, including
  weighted component health and threshold satisfaction.
- Cumulative MOOSE `Summary.damage` supplements snapshot health only when an
  AUFTRAG targets one exact strategic object component. Repeated reports retain
  the strongest confirmed damage instead of adding percentages; coordinate
  missions cannot provide component damage evidence.
- DESTROY follow-up proposals retain cumulative component health and prioritize
  damaged living targets. Each strike round remains a separately validated,
  approved, executed, and audited plan rather than an implicit executor retry.
- Rule-based proposals retain structured INTEL coverage warnings separately
  from technical feasibility findings, including the important distinction that
  no visible defender does not prove an objective is undefended.
- Tactical contacts have configurable `fresh`, `degraded`, `stale`, `unknown`,
  and `lost` information states derived from MOOSE `Tdetected`. LostContact
  events feed a coalition-private last-known-contact memory. Important recent
  losses near an objective create an executable RECON phase. MOOSE
  `INTEL:SetAgentAuto()` maintains all living coalition groups as agents,
  independent of mission type. Successful recon survival
  triggers an INTEL refresh and mandatory tactical replanning before later
  combat or capture phases may proceed.
- RECON tasking can carry a typed, audit-safe `ReconRequirement`. Automatic
  derivation combines goal metadata, objective components, phase targets, and
  coalition-private current/lost INTEL contacts while retaining provenance.
  `ReconOutcome` keeps authoritative MOOSE mission success separate from
  contact contribution and target-based information completion. Strict manual
  requirements remain available for deterministic mission tests.
- The operational executor captures RECON event cursors and INTEL baselines,
  persists each mission's `ReconOutcome`, emits a structured `recon.assessed`
  boundary, and gives replanning an explicit satisfied/incomplete/indeterminate
  reason. Later phases are never resumed from the stale pre-recon plan.
- Spatial RECON coverage from operational plans and direct `execute_recon()`
  runs uses sampled assigned-group trajectories and bounded
  sensor profiles. It reports optimistic potential access over circular or
  polygonal objective areas plus weighted known infrastructure points. Unknown
  sensor bounds remain indeterminate, and coverage never asserts enemy absence.
- The browser map reads completed RECON assessments from operational-plan and
  direct-RECON audit records.
  It renders the combined search footprint by default, optional per-asset
  footprints, and separate covered/uncovered objective-component markers.
- INTEL acquisition is mission-independent: all coalition agents contribute
  contacts regardless of AUFTRAG or lifecycle state. Information requirements
  accept every coalition source, while assigned RECON contribution remains a
  diagnostic dimension. Direct and operational RECON now share route sampling
  and spatial assessment code.
- `InformationRequirementRegistry` continuously tracks coalition-private target
  knowledge as open, partial, satisfied, or lost from INTEL events. It is a
  passive observer: satisfying or losing a requirement never cancels or
  retasks a running AUFTRAG.

## Phase 4: Command SDK and policies

Goal: Python can command MOOSE semantically and safely.

Work items:

- broaden AUFTRAG creation helpers beyond the current BAI, BOMBING, BOMBRUNWAY,
  BOMBCARPET, ARTY, ORBIT, AWACS, TANKER, CAP, CAS, CASENHANCED, FAC, FACA,
  SEAD, ANTISHIP, STRIKE, INTERCEPT, STRAFING, PATROLZONE, RECON, CAPTUREZONE,
  GROUNDESCORT, GROUNDATTACK, NAVALENGAGEMENT, AMMOSUPPLY, FUELSUPPLY,
  REARMING, AIRDEFENSE, EWR, ONGUARD, NOTHING, ESCORT, RESCUEHELO, and
  TROOPTRANSPORT baseline
- add cancellation and reassignment helpers (baseline implemented via mission
  lifecycle SDK methods)
- add OPSGROUP and OPSZONE control helpers
- map recommendations to command payloads (baseline implemented for AUFTRAG
  recommendations)
- validate coalition, range, mission type, target type, and asset availability
  (baseline implemented in the advisory layer)
- keep human tools and agents on the same SDK/control command path
- define policy checks for autonomous execution
- record command ACKs and outcomes

## Phase 5: Multi-client server hardening

Goal: Make the daemon a robust service for tools and agents.

Work items:

- stabilize the control protocol beyond the current local JSONL baseline
- define client-facing request and response schemas beyond the current
  `control.status`, `control.state`, `control.snapshots`, and
  `control.command` baseline
- add structured errors
- carry declared control `client_id` and `display_name` through every request
  and daemon audit envelope (implemented; authentication remains future work)
- add audit log records
- add remote access and authentication options
- keep dedicated-server performance and blocking behavior under control

## Phase 6: Agentic command layer

Goal: Build agents that can analyze the mission and propose or execute actions.

Initial behavior:

- summarize the tactical situation
- identify threatened zones and valuable targets
- find available assets
- produce recommendations with command payloads
- wait for approval before execution
- monitor AUFTRAG outcomes

Later behavior:

- strategic prioritization across multiple fronts
- autonomous defensive responses
- autonomous tasking inside policy limits
- adaptive replanning based on outcomes and events

## Immediate next milestone

The next milestone is controlled plan execution:

1. Convert approved `MissionIntent` objects into concrete typed AUFTRAG
   commands without duplicating constructor logic.
2. Treat Python allocations as planning commitments, let MOOSE recruit and
   reserve concrete warehouse assets, and reconcile the result through
   AUFTRAG/LEGION state and events.
3. Drive phase transitions from AUFTRAG FSM events and strategic objective
   events rather than status polling.
4. Automatic immediate-phase revalidation and explicit abort are implemented.
   Explicit replan, operator reapproval, target changes, recruitment changes,
   and resume from the first incomplete phase are implemented.
5. Explicit operator approvals, compact command ACK references, declared
   control-client identities, and recommendation provenance are now in the
   operational audit. Authenticated client identities remain future work.
6. Explicit cancellation of still-running MOOSE AUFTRAGs is implemented for
   complete attempts and, optionally, only the current phase.

The frontline, ammunition, capability, strategic objective, and strategic goal
layers are established inputs to this planner. They remain Python-owned
reasoning state; MOOSE remains the semantic execution interface to DCS.

## Frontline architecture baseline

MOOSE owns the Mission Editor-aligned passive territory definitions. Python
owns their strategic interpretation, force influence, incursion
classification, and operational-front calculation. MOOSE also supplies DCS
and OPS object state. Small tactical `OPSZONE`s may exist inside territories,
but they are not used as large-area territory scanners.

The passive MOOSE-side `TERRITORY` class is implemented in
`lua/Territory.lua`. It wraps a `ZONE_BASE`, stores its declared coalition, and
registers itself in `_DATABASE.TERRITORIES`. It intentionally has no FSM,
scheduler, object scan, capture evaluation, or strategic decision logic.
Territory snapshots, typed Python state, event-based coalition changes,
GeoJSON export, and the dedicated map layer are implemented. The same typed
geometry can be passed to the frontline engine with
`FrontlineCalculationArea.from_territory()`.

The calculation engine and live adapters are implemented in
`moosebridge.frontlines`:

- NumPy rasterizes weighted force positions.
- SciPy smooths their influence fields.
- ContourPy extracts equal-influence contours.
- Shapely validates, clips, simplifies, and measures the resulting lines.
- The map server selects only living ground groups, smooths their positions,
  separates isolated incursions, applies the combined territory boundary and
  weak ownership prior, converts line vertices through DCS, and publishes the
  results as GeoJSON.
- `examples/frontline/frontline_prototype.py` generates GeoJSON and an
  interactive diagnostic HTML viewer without requiring a running DCS server.
