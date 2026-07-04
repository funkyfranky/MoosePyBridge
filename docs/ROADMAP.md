# MoosePyBridge Roadmap

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

- DCS-facing bridge port: `51000`
- Python control port: `51001`

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
3. Add COMMANDER/CHIEF snapshots.
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
- AuftragOutcome
- later Airwing, Brigade, Fleet, Commander, Chief

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

## Phase 4: Command SDK and policies

Goal: Python can command MOOSE semantically and safely.

Work items:

- broaden AUFTRAG creation helpers beyond the current BAI, BOMBING, ARTY, ORBIT,
  CAP, CAS, CASENHANCED, FAC, FACA, SEAD, and STRIKE baseline
- add cancellation and reassignment helpers
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
- add session and client identity fields
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

The next concrete milestone is to deepen the current daemon, SDK, and advisory
baseline:

1. Add AIRWING/BRIGADE/FLEET snapshots and typed models.
2. Expand AUFTRAG lifecycle support with cancellation, reassignment, and richer
   outcome/trace details.
3. Add OPSGROUP and OPSZONE command helpers.
4. Add structured audit records for recommendations, approvals, commands, ACKs,
   and outcomes.
5. Start policy checks for approval-required and autonomous modes on top of the
   existing SDK/control command path.
