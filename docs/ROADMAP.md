# MoosePyBridge Roadmap

## Final goal

MoosePyBridge is intended to become a semantic Python control plane for DCS/MOOSE missions.

The bridge should mirror MOOSE mission state, expose MOOSE and OPS abstractions as typed Python objects, and enable tactical analysis plus controlled execution of MOOSE commands from Python.

The bridge is not meant to be a generic raw DCS scripting tunnel. DCS remains the simulation runtime, MOOSE remains the mission semantics layer, and Python becomes the external analysis, decision, and control layer.

## Guiding principles

- DCS is the authoritative source of simulation state.
- MOOSE is the authoritative semantic model for mission objects.
- Python consumes stable protocol objects, not raw MOOSE internals.
- The external protocol should remain stable even if MOOSE internals evolve.
- Commands should be MOOSE/OPS-semantic, not low-level DCS scripting snippets.
- Autonomous execution and human-approval workflows must both be supported.
- Dedicated server and multiplayer operation are first-class requirements.

## Architecture layers

### 1. Mission state mirror

The first layer mirrors mission state from DCS/MOOSE into Python.

Current baseline object types:

- GROUP
- UNIT
- STATIC
- AIRBASE
- ZONE
- OPSZONE
- OPSGROUP
- AUFTRAG

Planned object types:

- AIRWING
- BRIGADE
- FLEET
- COMMANDER
- CHIEF
- LEGION
- COHORT
- DETECTION
- EVENT

The Python mirror should preserve stable object identity, including:

- object_id
- dcs_name
- object_type
- category
- coalition
- birth_time where available

### 2. Tactical reasoning layer

The second layer interprets the mirrored state.

It should be able to answer operational questions such as:

- Which OPSZONE is threatened, empty, guarded, captured, or contested?
- Which OPSGROUPs are available, assigned, moving, executing, or destroyed?
- Which AUFTRAG objects are scheduled, started, executing, successful, failed, or cancelled?
- Which groups are detected by which OPSGROUPs?
- Which assets are suitable for a requested mission?
- Which actions are tactically useful and safe?

### 3. Controlled action layer

The third layer sends controlled commands back into MOOSE.

Initial command families:

- message.*
- mark.*
- smoke.*
- snapshot.*

Planned command families:

- auftrag.*
- opsgroup.*
- opszone.*
- commander.*
- chief.*
- airwing.*
- brigade.*
- fleet.*

Execution modes:

- read_only
- suggest_only
- approval_required
- autonomous

## Protocol direction

The protocol should remain line-oriented JSON for now.

Core message types:

- heartbeat
- snapshot
- event
- command
- ack
- error

Snapshot kinds should be object-family oriented:

- groups
- units
- statics
- airbases
- zones
- opszones
- opsgroups
- auftraege

The protocol should prefer references over nested objects. For example, an OPSGROUP references its current AUFTRAG with `auftrag_current_id`, while the AUFTRAG exists as a separate snapshot object.

## Phase 1: Stabilize state snapshots

Goal: Python knows the mission world.

### Current work

- GROUP snapshot
- UNIT snapshot
- STATIC snapshot
- AIRBASE snapshot
- ZONE snapshot
- OPSZONE snapshot
- OPSGROUP snapshot
- AUFTRAG snapshot

### Next work items

1. Expand AUFTRAG snapshots with mission target information.
2. Add AUFTRAG timing details in a stable form.
3. Add AUFTRAG target/zone/coordinate references.
4. Expand OPSGROUP snapshots with useful FLIGHTGROUP, ARMYGROUP, and NAVYGROUP-specific fields.
5. Add AIRWING/BRIGADE/FLEET snapshots.
6. Add COMMANDER/CHIEF snapshots.
7. Add LEGION/COHORT snapshots.

## Phase 2: Typed Python state model

Goal: Replace raw dict consumption with typed Python objects.

Initial Python model candidates:

- MooseObject
- Group
- Unit
- StaticObject
- Airbase
- Zone
- OpsZone
- OpsGroup
- Auftrag

Example target API:

```python
auftrag = bridge.state.auftraege["AUFTRAG:1"]
print(auftrag.type)
print(auftrag.status)
print(auftrag.assigned_group_ids)
```

## Phase 3: Event stream

Goal: Python understands what happened, not only what exists now.

Initial event families:

- object birth/death
- unit hit/kill/shot
- OPSGROUP state changed
- OPSZONE state/owner changed
- AUFTRAG scheduled/started/executing/success/failed/cancelled
- detection updates

Events should be logged and replayable.

## Phase 4: Command SDK

Goal: Python can command MOOSE semantically.

Initial command targets:

- AUFTRAG cancellation
- AUFTRAG assignment to OPSGROUP
- OPSGROUP mission control
- MOOSE MESSAGE/MARK/SMOKE support

Later command targets:

- AUFTRAG creation
- AIRWING/BRIGADE/FLEET tasking
- COMMANDER/CHIEF tasking
- policy and approval workflows

## Phase 5: Tactical agent

Goal: Build an agent that can analyze the mission and propose or execute actions.

The agent should be able to produce structured recommendations:

- situation summary
- threat assessment
- available assets
- recommended action
- required command
- confidence
- risks
- approval requirement

Initial mode should be suggest_only or approval_required. Autonomous operation should be a later capability.

## Immediate next milestone

The next concrete milestone is Phase 1 completion for OPS objects:

1. Expand AUFTRAG snapshot details.
2. Add AIRWING/BRIGADE/FLEET snapshots.
3. Add COMMANDER/CHIEF snapshots.
4. Start a typed Python state model for OPSZONE, OPSGROUP, and AUFTRAG.
