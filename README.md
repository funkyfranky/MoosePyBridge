# MoosePyBridge

MoosePyBridge is a semantic Python control plane for Digital Combat Simulator
(DCS) missions that use the MOOSE framework.

See [the roadmap](docs/ROADMAP.md) for the architectural direction and
[the backlog](docs/BACKLOG.md) for concrete pending work.

The bridge lets Python observe, analyze, and command a running DCS mission
through MOOSE and MOOSE OPS abstractions. It is intentionally not a raw Lua
remote execution tunnel. DCS remains the simulation runtime, MOOSE remains the
mission semantics layer, and Python becomes an external environment for state
mirroring, tactical reasoning, operator tooling, and future agentic control.

## Project direction

MoosePyBridge is intended to support both single-player and multiplayer or
dedicated-server missions.

The long-term goal is a server process connected to DCS/MOOSE, with one or more
Python clients or tools connected to that server. Those clients may provide:

- a live tactical picture of the battlefield
- recommendations for attacks, defense, patrols, and troop movements
- human approval workflows for proposed actions
- controlled autonomous execution within explicit policies
- experiment and agent frameworks that reason over MOOSE mission state

The agentic layer should command units only through semantic MOOSE/OPS concepts
such as `AUFTRAG`, `OPSGROUP`, `OPSZONE`, `LEGION`, and `COHORT`. This keeps the
Python side aligned with mission intent instead of micromanaging low-level DCS
objects directly.

## Current capabilities

Implemented baseline:

- TCP JSONL transport between DCS Lua and Python
- Lua-side `MOOSE_BRIDGE` class
- Python `asyncio` bridge daemon
- heartbeat, command, ACK, snapshot, and raw JSONL logging
- local multi-client control API for Python tools
- raw and typed Python state mirrors
- snapshot support for:
  - `GROUP`
  - `UNIT`
  - `STATIC`
  - `AIRBASE`
  - `ZONE`
  - `OPSZONE`
  - `OPSGROUP`
  - `AUFTRAG`
  - `COHORT`
  - `LEGION`
  - `INTEL`
  - `INTELCONTACT`
  - `INTELCLUSTER`
- command families including:
  - `message.*`
  - `mark.*`
  - `smoke.*`
  - `explosion.*`
  - `object.coords`
  - `object.distance`
  - `zone.draw`
  - `snapshot.*`
  - selected `auftrag.*` execution and trace commands
- advisory helpers for validating AUFTRAG requests and finding suitable
  LEGION/COHORT candidates
- SDK helpers for coordinate lookup, distance measurement, explosions, zone drawing,
  nearest-object queries, AUFTRAG tracing, snapshot refresh, and control-client
  adaptation
- SDK picture models for tactical INTEL-based and global truth-based GeoJSON
  exports

## Architecture

The DCS-facing bridge accepts one authoritative Lua connection from the mission.
Python tools should not each try to bind or own that DCS connection. Instead, a
single daemon can expose a local control port for multiple clients.

Default ports:

- DCS/MOOSE Lua bridge: `42000`
- local Python control API: `42001`

High-level layers:

- **Lua bridge**: runs inside DCS, calls MOOSE APIs, emits snapshots, executes
  whitelisted semantic commands
- **Python bridge daemon**: owns the DCS socket, maintains mirrored state, logs
  raw protocol traffic
- **Control API**: allows multiple local clients to query state or forward
  commands through the daemon
- **SDK and advisory layer**: provides typed state access, AUFTRAG validation,
  candidate selection, recommendations, and future policy checks
- **Agent/operator tools**: consume the same state and command surfaces in
  observe, recommend, approval, or autonomous modes

## Load order in DCS

Load the files in this order:

1. `Moose.lua`
2. optional MOOSE-side classes such as `lua/Territory.lua`
3. `lua/MooseBridgeJson.lua`
4. `lua/MooseBridge.lua`
5. optional extension files, for example:
   - `lua/MooseBridgeSocketTuningExtension.lua`
   - `lua/MooseBridgeDcsEventsExtension.lua`
   - `lua/MooseBridgePayloadExtension.lua`
   - `lua/MooseBridgeAuftragExecutionExtension.lua`
   - `lua/MooseBridgeAuftragTraceExtension.lua`
   - `lua/MooseBridgeIntelExtension.lua` (load after the execution extension for OPSGROUP agents)
6. mission-specific setup such as `lua/MooseBridgeMissionExample.lua`

The minimal example contains:

```lua
Bridge = MOOSE_BRIDGE:New("127.0.0.1", 42000)
Bridge:Start()
```

Register each MOOSE `COMMANDER` that Python should observe or task. This is a
one-time reference registration and does not add a polling loop:

```lua
BlueCommander = COMMANDER:New(coalition.side.BLUE, "Blue Command")
BlueCommander:AddLegion(WingParchim)
BlueCommander:AddLegion(BrigadeLaage)

Bridge:RegisterCommander(BlueCommander)
```

Passive strategic territories can be defined from Mission Editor zones:

```lua
local north = TERRITORY:New("Territory North", coalition.side.BLUE)
local south = TERRITORY:New(
  ZONE:FindByName("Territory South"),
  coalition.side.RED,
  "Southern Territory"
)

north:Draw()
```

`TERRITORY` registers objects in `_DATABASE.TERRITORIES` and exposes their
zone geometry and declared coalition without scanning DCS objects, scheduling
updates, or evaluating capture logic.

Python receives these objects as typed, passive SDK state:

```python
await bridge.refresh_territory_state()

north = bridge.territory("TERRITORY:Territory North")
blue_territories = bridge.territories(coalition="blue")
await bridge.set_territory_coalition("TERRITORY:Territory North", "red")
```

Coalition changes update the state mirror through
`territory.coalition_changed`. Global pictures export territory polygons as a
separate GeoJSON/map layer, and `FrontlineCalculationArea.from_territory()` adapts the
same geometry for Python's frontline engine. See `examples/sdk/territories.py`
for a parameterless client example.

### Strategic objectives

Python owns strategic objectives. An objective may be created or removed at
runtime and may contain multiple DCS/MOOSE components. Its ownership policy
selects the authoritative source instead of inferring control generically:

- `DCS_MANAGED` reads an `AIRBASE` or FARP owner from DCS state.
- `MOOSE_MANAGED` reads an `OPSZONE` owner and contested state from MOOSE.
- `TERRITORY_INHERITED` follows a passive `TERRITORY` declaration.
- `FIXED` retains the owner assigned by Python.

```python
from moosebridge import (
    CaptureBehavior,
    ObjectiveComponent,
    ObjectiveKind,
    OwnershipPolicy,
    StrategicObjective,
)

parchim = StrategicObjective(
    objective_id="OBJECTIVE:Parchim",
    name="Parchim Airbase",
    kind=ObjectiveKind.AIRBASE,
    control_object_id="AIRBASE:Parchim",
    ownership_policy=OwnershipPolicy.DCS_MANAGED,
    strategic_value=80,
    priority=60,
    components=(
        ObjectiveComponent(
            "STATIC:Parchim Depot",
            role="storage",
            weight=0.7,
            capture_behavior=CaptureBehavior.RESPAWN_FOR_NEW_OWNER,
        ),
        ObjectiveComponent("GROUP:Parchim Defense", role="defense", weight=0.3),
    ),
)

bridge.add_strategic_objective(parchim)
```

Strategic objectives are global facts. Coalition-private intent is represented
separately by `StrategicGoal`; only `blue` and `red` goals are accepted:

```python
from moosebridge import StrategicGoal, StrategicGoalAction

capture_parchim = bridge.add_strategic_goal(
    StrategicGoal(
        goal_id="GOAL:Blue capture Parchim",
        name="Capture Parchim",
        coalition="blue",
        action=StrategicGoalAction.CAPTURE,
        objective_id=parchim.objective_id,
        priority=90,
    ),
    activate=True,
)

mission_time = bridge.state.clock.mission_time if bridge.state.clock else 0
defend_parchim = bridge.add_strategic_goal(
    StrategicGoal(
        goal_id="GOAL:Blue defend Parchim",
        name="Defend Parchim for 30 minutes",
        coalition="blue",
        action=StrategicGoalAction.DEFEND,
        objective_id=parchim.objective_id,
        deadline_mission_time=mission_time + 1800,
    )
)
```

Supported actions are `CAPTURE`, `DEFEND`, `DESTROY`, `DISABLE`, `PROTECT`,
and `INTERDICT`. Goals move through `planned`, `active`, `achieved`, `failed`,
or `cancelled`. Capture and destruction complete when their typed conditions
match. An AIRBASE `DISABLE` goal defaults to the concrete `deny_runway` effect;
it is completed manually by the operational executor only after a successful
MOOSE `BOMBRUNWAY` AUFTRAG against an `Airdrome`. Defense and protection are evaluated at their
mission-time deadline; ownership changes and object losses can fail them
earlier. Completed goals remain historical facts if the objective later changes
again. A recapture therefore creates a new goal rather than reopening the old
one. Custom typed `GoalCondition` values and manual completion are also
available.
`await bridge.wait_for_strategic_goal_event(goal_id)` waits for completion
without periodically requesting objective snapshots.

The SDK can derive the currently executable `CAPTURE`, `DEFEND`, and `DESTROY`
goals for either coalition from the shared objective registry:

```python
result = bridge.generate_strategic_goals("blue")
print(format_strategic_goal_generation(result))
```

The derivation respects the TERRITORY scope and shared relationship as hard
boundaries. It proposes CAPTURE or DEFEND for MOOSE OPSZONEs and DESTROY only
for enemy objectives with addressable components. Neutral infrastructure is
not attacked automatically. Coalition doctrine is applied later by portfolio
selection, where it ranks otherwise permissible goals without overriding
diplomacy. Repeated generation keeps an existing planned or active goal rather
than creating a duplicate.

For a running mission, the parameterless preview example loads the generated
GermanyCW infrastructure datasets, resolves the TERRITORY-defined conflict
area, registers admitted objectives, derives coalition goals, creates
rule-based operational plan candidates, and performs capacity-aware portfolio
selection without executing a mission:

```powershell
& "C:\Program Files\Python313\python.exe" examples/sdk/generate_strategic_objectives.py
```

`MANAGE_RELATIONSHIP = False` is the safe default: current diplomacy is used
unchanged, so offensive goals are rejected during peace. Set it to `True` only
when the preview is deliberately allowed to invoke the controller's configured
war declaration. `MAX_CONCURRENT_GOALS` limits the selected portfolio; omitted
candidates remain visible as deferred or rejected decisions.

Automatic objective generation always retains mission-controlled airbases,
FARPs, and OPSZONEs. Geographic data is grouped by effective scope
(`blue`, `red`, `neutral`, or `contested`) and by category such as settlement,
bridge, railway, or energy site. Within each group the ten highest strategic
values are retained by default. The remainder is reported as
`category_scope_limit`, so reducing the working set does not hide why a
candidate was omitted. The limit can be adjusted or disabled explicitly:

```python
from moosebridge import StrategicObjectiveGenerationConfig

config = StrategicObjectiveGenerationConfig(
    maximum_geographic_objectives_per_category_per_scope=20,
)
# Use None instead of 20 to retain every candidate above its importance threshold.
result = bridge.generate_strategic_objectives(config=config)
```

The SDK also maintains passive strategic feedback. Relevant ownership and
loss events update objectives and goals immediately. COHORT, LEGION, and world
state snapshots revalidate every non-terminal plan from the existing mirror;
they do not trigger additional DCS polling. The monitor emits meaningful
changes such as `feedback.replanning_required`,
`feedback.plan_feasibility_restored`, `feedback.plan_allocation_changed`,
`feedback.goal_status_changed`, `feedback.intelligence_changed`, and
`feedback.mission_outcome`. A deterministic policy maps plan-specific feedback
to `keep`, `wait`, `replan`, or `abort`. Temporary shortages never cancel a
running mission, persistent shortages produce an advisory replan decision, and
replanning never happens without the normal validation and approval boundary.
Only terminal goals and unsafe friendly targets may automatically abort an
already active attempt through the existing plan executor.

```python
bridge.add_strategic_feedback_listener(
    lambda event: print(format_strategic_feedback(event))
)

# Explicitly establish or refresh the comparison baseline from mirrored state.
bridge.sync_strategic_feedback(source="operator")

for event in bridge.strategic_feedback_events(plan_id=plan.plan_id):
    for decision in bridge.strategic_feedback_decisions(event):
        print(format_strategic_feedback_decision(decision))
```

Use `bridge.strategic_feedback_events(plan_id=plan.plan_id)` to inspect retained
feedback. Required asset shortfalls are considered persistent after 300 seconds
of DCS mission time by default; configure this with
`MooseBridgeClient(..., strategic_shortfall_timeout_s=...)`. INTEL changes
remain context for planning until their relevance to a specific goal can be
established; they do not replace or cancel running AUFTRAGs globally.

Multiple strategic goals may be selected concurrently. The SDK builds a
capacity-aware portfolio from their candidate operational plans:

```python
portfolio = bridge.select_strategic_goal_portfolio("blue")
print(format_strategic_goal_portfolio(portfolio))
```

Candidates are ordered lexicographically by doctrine tier, explicit goal
priority, objective priority, strategic value, deadline, and stable goal id.
Each admitted plan reserves its largest simultaneous COHORT use in any phase.
Later candidates are validated against the remaining capacity, preventing the
same currently available asset group from being promised to multiple new plans.
Portfolio selection does not activate goals, approve plans, reserve assets in
MOOSE, or submit AUFTRAGs.

### Relationship and doctrine

Python owns one shared blue/red relationship with the states `peace`, `tense`,
`limited_conflict`, `war`, and `ceasefire`. A deliberately small set of
attributed incidents raises a bounded escalation score. Threshold crossings
apply their transition automatically by default:

```python
incident = EscalationIncident(
    incident_id="INCIDENT:1",
    incident_type=EscalationIncidentType.BORDER_VIOLATION,
    actor_coalition="red",
    target_coalition="blue",
)
proposal = bridge.record_escalation_incident(incident)
```

A coalition may also start a conflict explicitly without waiting for prior
incidents. The declaration is attributed, immediately establishes the shared
`war` state, and uses the normal diplomacy audit persistence:

```python
bridge.declare_war("blue", reason="Recover occupied territory")
await bridge.persist_diplomacy_state()
```

`examples/sdk/run_blue_conflict_controller.py` demonstrates one deliberately
bounded autonomous cycle. It restores or declares war, uses blue INTEL, derives
CAPTURE/DEFEND/DESTROY candidates from registered objectives,
admits at most one capacity-feasible plan, approves it, and executes it through
the blue COMMANDER. Red DCS forces can serve as targets for this first scenario;
red LEGIONs and COHORTs are required only when red should plan and execute its
own MOOSE missions.

Set `bridge.relationship.automatic_transitions = False` when a scenario should
require explicit approval through `approve_relationship_transition()`.
De-escalation remains explicit. Incident weights are
configurable through `bridge.relationship.incident_weights`; defaults range
from 5 points for a border violation to 60 for an objective capture. The
thresholds are 20 for tension, 50 for limited conflict, and 80 for war.

Each coalition has an independently mutable doctrine preset: `passive`,
`defensive`, `balanced`, `offensive`, or `aggressive`. Presets provide defense,
offense, escalation-tolerance, risk, and force-preservation biases and may be
replaced by a custom `CoalitionDoctrine`. Relationship and doctrine are
mission-scoped and reset when the DCS mission ends.

Relationship is a hard boundary for portfolio selection. Peace, tension, and a
ceasefire admit only DEFEND and PROTECT goals. Limited conflict admits offensive
goals only for explicitly authorized objectives or territories:

```python
bridge.relationship.limited_conflict.authorize_objective("OBJECTIVE:Border Town")
bridge.relationship.limited_conflict.authorize_territory("TERRITORY:Border")
```

War admits all currently implemented strategic actions. Doctrine never
overrides these restrictions; it only places otherwise valid goals into simple
preference tiers before their explicit priorities are compared.

Living, active ground groups inside an opposing `TERRITORY` are tracked as
potential border violations. A continuous stay of 60 DCS mission seconds emits
one `BORDER_VIOLATION` incident; leaving before the threshold discards the
candidate, and leaving after a report permits a later re-entry to become a new
incident. Configure the duration with
`MooseBridgeClient(..., border_violation_tolerance_s=...)`. Evaluation uses
existing group/territory mirrors on snapshots and heartbeats and does not issue
extra DCS queries. Aircraft do not create territorial border incidents.

MOOSE `EVENTS.Kill` is forwarded separately as `combat.kill` with killer,
target, coalition, type, and weapon attribution. An enemy unit kill creates one
deduplicated `UNIT_DESTROYED` escalation incident. `object.destroyed` remains
the authoritative UnitLost/Dead state update and is not used to guess the
attacker.

An `airbase.coalition_changed` event creates one attributed
`OBJECTIVE_CAPTURED` incident with an explicit contextual score. Enemy-owned
Airdromes are worth 60 points in opposing territory and 40 in no man's land;
neutral Airdromes are worth 30 and 15 respectively. A neutral FARP in no man's
land is worth 5 points. Remaining own-territory and FARP combinations are kept
in the public `AIRBASE_CAPTURE_ESCALATION_POINTS` matrix. Every incident retains
its ownership, territory, category, base score, and final score. Thus the
60-point reference capture proposes `limited_conflict` from peace and can
propose war when tension already exists.

The bridge composes the public MOOSE `OPSZONE:OnAfterCaptured(...)` callback
and forwards the completed transition as `opszone.owner_changed`. The internal
`onafterCaptured` implementation and generated `Captured` transition remain
untouched. An existing public callback is invoked first and errors remain
visible. Register an OPSZONE after defining its own `OnAfterCaptured` callback
when immediate forwarding is required. OPSZONEs discovered from
`_DATABASE.OPSZONES` are attached when monitoring starts; their current owner
forms the baseline, and earlier captures are intentionally not reconstructed as
events. A later forwarded event creates a separate `OPSZONE_CAPTURED` incident.
A strategic OPSZONE has a
20-point reference value by default. Set a more important zone explicitly:

```python
bridge.set_opszone_strategic_value("OPSZONE:Town Fight", 40)
```

The full configured value applies when an enemy-owned OPSZONE is captured in
the opponent's territory. The context multipliers are: enemy/opposing territory
`100%`, neutral/opposing territory `75%`, enemy/no man's land `50%`, and
neutral/no man's land `25%`. Capturing either a neutral or enemy-owned OPSZONE
inside the actor's own territory causes no escalation. The configured values
are part of the persisted mission diplomacy state. Processing is driven by the
MOOSE FSM event and adds no periodic scan.

Relationship state and both doctrines can be persisted as a mission-generation
scoped daemon audit snapshot with `await bridge.persist_diplomacy_state()` and
restored in another client with `await bridge.refresh_diplomacy_state()`. This
keeps planning tools, diagnostics, and the browser map on the same shared state.
Capture and Kill incidents use semantic identities based on involved objects,
coalitions, and DCS mission time, so replay with a new daemon event id cannot
score the same event twice. Active border crossings, including whether their
incident was already reported, are persisted on entry, report, and exit; a map
server restart therefore neither restarts the tolerance nor duplicates a
continuous violation.
`examples/sdk/monitor_relationship.py` provides a parameter-free monitor; its
output includes the latest incidents and their individual point contributions.
`examples/sdk/test_opszone_relationship.py` records current OPSZONE owners as a
non-escalating baseline, waits for a later capture, and replays that event to
verify deduplication without modifying the persisted map-server relationship.
For a focused DCS test, edit `GROUP_ID` and `TERRITORY_ID` in
`examples/sdk/test_border_violation.py`. The script uses only the global
GROUP/TERRITORY mirror, displays the 60-second DCS-time countdown, and waits for
the map server's persisted border incident; it never reads an INTEL contact.

### Operational planning

`OperationalPlan` translates one coalition-private `StrategicGoal` into ordered
phases, mission intents, and explicit asset requirements. Validation uses the
current LEGION/COHORT mirror and checks coalition, supported AUFTRAG types,
platform category, payload availability, and `available_asset_count`. MOOSE
calculates this value with `CountAvailableAssets()`, excluding assets already
requested or reserved for another mission.

An asset remains one MOOSE group even when `COHORT:SetGrouping()` changes the
number of units spawned in that group:

```lua
platoonAbrams:SetGrouping(4)
```

The typed Python `Cohort` then exposes `homogeneous`, `configured_grouping`,
`units_per_asset`, and the derived `available_unit_capacity`. The bridge derives
homogeneity automatically by comparing the DCS type of every unit in all asset
templates. Mixed templates such as SAM batteries are therefore never reduced
to an unsafe unit-count multiplier.

Assets are allocated conservatively: a COHORT's stock cannot satisfy two
requirements in the same phase, but can be reused in a later phase. The result
is a provisional feasibility assessment, not a reservation in MOOSE.

Ground assault and defense requirements distinguish minimum groups from minimum
unit capacity. With the default requirement of at least one group and two
combat units, two one-unit assets are requested while one homogeneous group of
four units is sufficient. Because the coalition `COMMANDER` chooses cohorts by
default, unconstrained plans use the smallest known group strength among all
currently available eligible cohorts. Explicit cohort restrictions allow the
planner to use that cohort's exact homogeneous group size. The resolved group
count is sent to MOOSE through `AUFTRAG:SetRequiredAssets()`.

```python
assessment = await bridge.refresh_and_validate_operational_plan(plan)
print(format_operational_plan_assessment(plan, assessment))

if assessment.feasible:
    bridge.approve_operational_plan(plan)
    execution = await bridge.execute_plan(plan, on_event=print)
    print(format_operational_plan_execution(execution))
```

Approval still records a command decision only. `execute_plan()` is the
separate, explicit execution step. The executor supports `CAPTURE`, weighted
`DESTROY`, deadline-based `DEFEND`, and `deny_runway` DISABLE goals and maps
`BAI`, `BOMBRUNWAY`, `PATROLZONE`, `RECON`, `CAPTUREZONE`, `AIRDEFENSE`,
`AMMOSUPPLY`, `FUELSUPPLY`, and `REARMING` requirements to concrete AUFTRAGs.
It submits all requirements in a phase before waiting for required outcomes,
then advances automatically when their `auftrag.evaluated` events report
success. Optional intents are submitted but do not gate phase completion.
A required cancellation, failure, timeout, or an unconfirmed strategic goal
sets the plan to `blocked`; no automatic retry is performed.

Blocked plans can be revised and resumed explicitly. Completed phases remain
completed and are excluded from the new feasibility assessment and execution.
Targets and recruitment constraints can be changed before the operator
revalidates and approves the plan again:

```python
bridge.prepare_plan_retry(
    plan,
    # Optional; defaults to the first incomplete phase. Naming a completed
    # phase explicitly reopens that phase and every phase after it.
    resume_from="seize",
    target_overrides={
        ("seize", "capture-zone"): "OPSZONE:Town Fight",
    },
    allowed_legion_overrides={
        ("seize", "capture-zone", "REQ:Ground assault"): ("LEGION:Brigade Laage",),
    },
    allowed_cohort_overrides={
        ("seize", "capture-zone", "REQ:Ground assault"): ("COHORT:Abrams Laage",),
    },
)
assessment = await bridge.refresh_and_validate_operational_plan(plan)
if assessment.feasible:
    bridge.approve_operational_plan(plan)
    execution = await bridge.execute_plan(
        plan,
        commander="COMMANDER:Blue Commander",
        on_event=print,
    )

for attempt in bridge.operational_plan_executions(plan):
    print(format_operational_plan_execution(attempt))
```

Every call to `execute_plan()` creates a numbered attempt record. The daemon
persists snapshots of the plan, feasibility assessment and provisional COHORT
allocations, generated AUFTRAGs, lifecycle events, outcomes, selected COMMANDER,
and resume phase in `moosebridge_audit.jsonl`. A new SDK process can load them
with `await bridge.refresh_operational_plan_executions(plan)`; `execute_plan()`
also refreshes them automatically before assigning the next attempt number.
Changing the COMMANDER is therefore an execution decision and does not require
modifying the plan itself. Audit write failures are logged but do not interrupt
a mission already being executed.

After an SDK process restart, the complete typed planning context can be
restored explicitly without issuing DCS commands:

```python
restored = await bridge.restore_operational_plan("PLAN:Blue capture Town Fight")
plan = restored.plan

if plan.status.value == "blocked":
    bridge.prepare_plan_retry(plan)
    assessment = await bridge.refresh_and_validate_operational_plan(plan)
    if assessment.feasible:
        bridge.approve_operational_plan(
            plan,
            approved_by="Frank",
            reason="Capture window confirmed",
        )
        execution = await bridge.execute_plan(plan, on_event=print)
```

The restore registers the audited `StrategicObjective`, `StrategicGoal`, and
`OperationalPlan` in dependency order and returns all execution attempts in a
`RestoredOperationalPlan`. Existing registry objects are protected by default;
pass `replace=True` only for an intentional replacement. An interrupted attempt
whose last state is `executing` remains `executing` after restore because its
MOOSE AUFTRAG may still be active. It must be reconciled before any retry:

```python
result = await bridge.reconcile_operational_plan(plan)
print(format_operational_plan_reconciliation(result))

if result.status.value == "running":
    result = await bridge.monitor_interrupted_operational_plan(plan, on_event=print)
elif result.status.value == "indeterminate":
    await bridge.block_interrupted_operational_plan(
        plan,
        reason="Operator confirmed that the AUFTRAG no longer exists",
    )
```

Reconciliation requests one current AUFTRAG snapshot. A MOOSE summary is the
authoritative terminal result; an existing non-terminal AUFTRAG remains
`running`, while a missing or unrecognized AUFTRAG is `indeterminate` and is
not guessed to have failed. Monitoring then uses AUFTRAG FSM events without
polling and never submits a replacement mission. After a reconciled phase, any
remaining phase is blocked for explicit revalidation and approval.

Plan approvals retain `approved_by`, `approved_client_id`, an optional reason,
and the DCS mission time. A control-backed SDK derives both identity fields
from its declared client identity; direct in-process SDK use defaults to
`"operator"`. Each
submitted plan mission also retains a compact `CommandAckReference` containing
the bridge `ack_id`, `correlation_id`, `sequence`, and selected scalar result
fields. Constructor inputs remain in the separate command snapshot, so the
full ACK payload is not duplicated in every audit record.

Plan origin is a separate optional concept from approval identity:

```python
provenance=OperationalPlanProvenance(
    source_type=PlanSourceType.RULE_ENGINE,
    source_id="capture-planner-v1",
    picture_mission_time=picture.clock.mission_time,
    rationale="Enemy control is weak and ground assets are available.",
)
```

Supported source types are `operator`, `rule_engine`, `llm`, and `import`.
Provenance remains optional for manually constructed legacy plans and survives
the same audit/restore roundtrip as phases and approvals.

The rule-based planner proposes conservative CAPTURE, DEFEND, DESTROY, and
AIRBASE runway-denial drafts from a coalition-visible tactical picture:

```python
picture = await bridge.refresh_tactical_picture("blue", "INTEL:Blue Intel")
draft = bridge.propose_capture_plan("GOAL:Blue capture Town", picture)
# A DEFEND goal must carry deadline_mission_time.
defense = bridge.propose_defend_plan("GOAL:Blue defend Town", picture)
destruction = bridge.propose_destroy_plan("GOAL:Blue damage Depot", picture)
runway_denial = bridge.propose_disable_plan("GOAL:Blue deny Parchim runway", picture)

bridge.add_operational_plan(draft)
assessment = await bridge.refresh_and_validate_operational_plan(draft)
```

`StrategicMissionResolver` is the single target/effect-to-AUFTRAG assignment
point used by CAPTURE isolation, DEFEND counterattacks, DESTROY component
strikes, and runway denial. It classifies mirrored `GROUP`, `UNIT`, `STATIC`,
`AIRBASE`, and known scenery ids, builds an ordered candidate list, and selects
the first candidate supported by a currently available COHORT. The selected
mission, target domain, candidate order, rationale, and matching COHORT are
stored in the mission intent metadata and shown in plan diagnostics.

The conservative mappings currently include:

- airborne `GROUP`/`UNIT` -> `INTERCEPT`
- ordinary ground `GROUP`/`UNIT` -> `BAI`, then `GROUNDATTACK`
- air-defense targets -> `SEAD`, then `BAI` or `GROUNDATTACK`
- naval `GROUP`/`UNIT` -> `ANTISHIP`, then `NAVALENGAGEMENT`
- `STATIC` infrastructure -> `BAI`, `BOMBING`, `GROUNDATTACK`, or `NAVALENGAGEMENT`
- stationary ground and `STATIC` targets -> `ARTY` when an available artillery
  COHORT has a known deployment position, a matching indirect-fire weapon
  profile, ammunition, and the target lies inside the COHORT mission range
- `AIRBASE` plus `deny_runway` -> `BOMBRUNWAY`
- scenery/map objects plus `attack_map_object` -> `STRIKE`

An `ARTY` resolution stores the selected DCS weapon flag, initial distance,
weapon range, COHORT engage range, total mission range, required relocation,
range source, ammunition source, and weapon ids in the intent metadata. The
Lua COHORT snapshot exposes both `COHORT:GetMissionRange({WeaponType})` and the
underlying `COHORT.weaponData` entry. Python compares that configuration with
its versioned Quaggles-derived profile. Immediately before an ARTY mission is
submitted, a missing or differing entry is synchronized once through
`COHORT:AddWeaponRange`; an already matching entry causes no command. The
COMMANDER therefore recruits against the same weapon flag and range used by
the Python resolver. The total mission range is `engageRange + weapon range`,
so mobile artillery may move into a valid firing position instead of being
rejected merely because its initial distance exceeds weapon range.
Because those checks depend on one COHORT, the
plan constrains execution to that qualified COHORT. Observed ammunition is
authoritative, including `count=0`. If no live ammunition observation exists
for a not-yet-spawned COHORT type, planning uses the versioned template weapon
profile and records `cohort_template_assumed_full`. Call
`await bridge.snapshot_ammunition()` before planning when current spawned-unit
ammunition should participate; it is deliberately not refreshed implicitly.
Moving ground contacts, unknown positions, missing COHORT deployment ranges,
and targets outside the synchronized total mission range do not receive an
ARTY candidate.

`examples/sdk/test_arty_weapon_selection.py` is a parameterless DCS integration
test for M109 and MLRS COHORTs. Configure its COHORT and target ids at the top;
it prints the complete feasibility decision, synchronizes stale MOOSE weapon
ranges, verifies the ACK weapon flag, and optionally waits for both AUFTRAG
outcomes. The same operation is available explicitly as
`await bridge.set_cohort_weapon_range(...)`.

The executor applies the selected flag through `AUFTRAG:SetWeaponType()` before
the mission is submitted to its COMMANDER, LEGION, or OPSGROUP. The same
resolver ranks multiple feasible artillery assignments deterministically by:

1. no relocation, then shortest required relocation;
2. observed current ammunition, then remaining rounds;
3. COHORT ARTY mission performance;
4. range-source quality, an already synchronized range, available assets, and
   stable ids as tie-breakers.

Observed ammunition is associated with the COHORT through its spawned
OPSGROUP ids, rather than being shared by every COHORT of the same DCS type.
Weapon lethality or cost is deliberately not guessed, so shell and rocket
flags receive no arbitrary intrinsic preference. The selected assignment and
all qualified alternatives are retained in mission-resolution metadata.

Mission selection has two distinct stages. First, the resolver walks the
doctrinally ordered AUFTRAG candidates and selects the first mission type with
an executable COHORT. A faster fallback such as ARTY therefore cannot displace
a preferred BAI mission merely because it has a shorter response time. Second,
COHORTs for that mission type are ranked by an auditable score: mission
performance contributes 50%, COHORT skill 30%, and response time 20%.
Response time combines distance, platform speed, and a preparation delay, so
distance is not counted twice. ARTY uses only required relocation. Air and
naval missions use straight-line distance from the COHORT or its parent LEGION.
When a preloaded `GroundMobilityNetwork` is supplied to the SDK or resolver,
ground missions instead use its connected route distance and travel time; a
disconnected target does not qualify that ground COHORT. Assignment metadata
records `transit_source`, the route profile, and bridge count. The native DCS
road solver is deliberately not called during ranking because it is reserved
for final tactical route validation. The
timing defaults are 300 s and 200 m/s for air, 60 s and 10 m/s for ground,
120 s and 12 m/s for naval forces, and 120 s plus 8.33 m/s relocation for
artillery. Timing can be replaced through `MissionTimingAssumptions`; scoring
weights and normalization defaults through `MissionScoringAssumptions`.
Missing performance, skill, or position data uses explicit neutral defaults.
Plans retain the total score, every score component, timing inputs, and all
qualified alternatives for diagnostics and audit.

The selected mission type is constrained to every qualified COHORT in score
order, rather than only the highest-scoring one. Phase validation consumes the
best COHORT's available assets first and continues with the next candidate when
capacity is exhausted. COMMANDER receives the same allowed COHORT pool, so
MOOSE can recruit and reserve across it. ARTY fallbacks additionally require the
selected weapon flag and an already synchronized MOOSE weapon range; the
selected ARTY COHORT itself may be synchronized immediately before submission.

`examples/sdk/select_arty_cohort.py` compares the configured Paladin and M270
COHORTs against one target, prints the ranked alternatives, synchronizes only
the selected range if necessary, and optionally submits that AUFTRAG.

The Pythonic setting is available for manually created missions as
`auftrag.set_weapon_type(DcsWeaponFlag.CONVENTIONAL_SHELL)`. A candidate with no
currently matching COHORT remains in the draft as the preferred type so normal
plan validation reports the asset shortfall rather than silently changing the
requested effect.

CAPTURE and DEFEND currently require an OPSZONE-controlled objective. CAPTURE can
add a BAI isolation phase before ground seizure. DEFEND requires current
friendly ownership, optionally interdicts the strongest visible nearby ground
attacker, and tasks ground forces to hold the zone until the goal deadline.
Local air defense and ammunition supply are optional support intents. The
DEFEND executor monitors objective and goal events alongside AUFTRAG events;
loss of control fails immediately, while holding the objective to the deadline
completes the plan and cancels its remaining active missions on a best-effort
basis. See `examples/sdk/plan_defend_goal.py` for a parameterless DCS example.

DESTROY objectives may contain multiple weighted components. A goal's
`required_damage` is a fraction from `0.0` to `1.0`; `1.0` requires complete
weighted destruction. The planner creates one intent for every currently alive,
known, and targetable component; the damage threshold controls strategic goal
completion, not which structures receive an AUFTRAG. Stationary `STATIC`
components are treated as known infrastructure. Moving `GROUP` and `UNIT`
components require a current, non-stale coalition INTEL contact. After each
strike phase, the executor refreshes the affected component snapshots once and
confirms the weighted objective health. All parallel strikes are allowed to
finish before that assessment. A negative individual MOOSE AUFTRAG summary does
not block a DESTROY plan when the required weighted damage was nevertheless
reached; otherwise the blocked reason reports achieved and required damage. See
`examples/sdk/plan_destroy_goal.py` for a parameterless DCS example.

Execution diagnostics keep both meanings explicit. `moose_auftrag_outcome`
reports the constructor-specific MOOSE result, while `strategic_damage` reports
evidence-derived weighted objective health, total damage, phase damage, the
required threshold, and component health. The same typed damage assessments and
`strategic.damage_assessed` events are retained in the operational audit.

For an AUFTRAG that targets exactly one objective component by object id, the
cumulative MOOSE `Summary.damage` percentage supplements the regular snapshot.
Python uses the lower confirmed component health from both sources and never
adds damage percentages from repeated attacks. Coordinate-targeted missions do
not contribute Summary damage because their MOOSE success semantics do not
identify one strategic component. Retained Summary evidence is cleared only by
an explicit repair, replacement, or respawn decision.

When a DESTROY plan ends below its threshold, a follow-up proposal uses this
retained effective health and prioritizes already damaged living components
before untouched alternatives. The executor itself still performs no hidden
retry: every follow-up is a distinct plan with its own validation, approval,
execution, and audit trail. `examples/sdk/plan_destroy_goal.py` demonstrates up
to three explicitly approved strike rounds through `MAX_STRIKE_ROUNDS`.

Runway denial deliberately has narrower semantics. The objective must be backed
by an `AIRBASE` snapshot whose MOOSE category is `Airdrome`; helipads and ships
are rejected. The planner creates one payload-aware `BOMBRUNWAY` requirement,
and the goal is achieved only when that exact MOOSE AUFTRAG reports success.
No `BOMBING` or `ARTY` fallback currently claims runway denial because those
constructors do not yet provide an agreed confirmation rule. See
`examples/sdk/plan_deny_runway_goal.py` for a parameterless DCS example.

The result stays `draft`: proposing never registers, validates, approves, or
executes a plan. Enemy selection uses only `TacticalPicture` INTEL contacts,
never global truth. CAPTURE without a visible defender carries
`intel_no_visible_defenders`; DEFEND without a visible attacker carries
`intel_no_visible_attackers`. Absence of a contact is never treated as proof
that the area is clear. Missing INTEL status, stopped INTEL, and absent living
detection agents produce their own proposal warnings. These remain distinct
from feasibility errors and survive audit persistence and restore.

Current INTEL contacts are assessed from MOOSE `Tdetected`, which represents
the last successful detection in absolute mission seconds. The default planner
quality bands are `fresh` through 120 seconds, `degraded` until 600 seconds,
and `stale` afterwards. Stale contacts remain owned by MOOSE and visible in the
tactical picture, but are not selected as attack targets by the rule-based
planner. The thresholds are configurable through `RuleBasedPlannerConfig`.

MOOSE `LostContact` events remove a contact from the active mirror and retain
its last known state in `TacticalPicture.lost_contacts`. A recent lost ground or
static contact near the objective requests reconnaissance only when its threat
level reaches the configurable importance threshold. The draft then contains a
`reconnaissance_required` proposal issue, structured last-known-position
metadata, and an executable RECON phase. INTEL agent membership is independent
of mission type. `RegisterIntel()` enables MOOSE `INTEL:SetAgentAuto()`, so
MOOSE periodically maintains all living groups of the INTEL coalition in its
detection set. The bridge does not duplicate this lifecycle logic.
When the route is complete and the recon group survived, MOOSE reports mission
success. The executor then refreshes INTEL and emits `plan.replanning_required`
instead of automatically starting the capture phases: successful survival does
not prove that the objective is clear.

Structured RECON requirements additionally assess spatial search coverage.
Assigned group positions are sampled every 10 seconds and combined with known
optimistic sensor bounds. The result reports potentially searchable area and
weighted coverage of known stationary objective components. Airfields, roads,
cities, static infrastructure, and other stationary map information are
treated as known; only their surrounding search coverage is assessed. Spatial
coverage does not prove that an area is free of enemy forces.

Normal plan execution also revalidates only the immediately upcoming phase.
Before any AUFTRAG for that phase is created, the executor refreshes COMMANDER,
LEGION, COHORT, and objective-control state, reassesses current asset
availability, validates COMMANDER constraints, and preflights that phase's
targets. The audit stream emits `phase.revalidating` followed by
`phase.revalidated`; a changed goal, missing target, unavailable COMMANDER, or
required asset shortfall blocks the plan without submitting a phase mission.
Completed earlier phases are not reassessed, and later phases wait until their
own execution boundary.

An executing or blocked attempt can be terminated explicitly. The default
scope cancels every live MOOSE AUFTRAG from the current attempt; use
`scope="current_phase"` only when earlier-phase AUFTRAGs should continue:

```python
abort = await bridge.abort_operational_plan(
    plan,
    reason="Objective priority changed",
)
print(format_operational_plan_abort(abort))
```

The abort performs one AUFTRAG snapshot so that timed-out but still-running
MOOSE missions are included. If any `auftrag.cancel` command fails, the plan is
left `blocked` and the failed mission ids are reported. A plan reaches
`cancelled` only after every selected live AUFTRAG accepted cancellation.

Before changing the plan to `executing`, a one-shot target preflight refreshes
each required object kind and verifies every executable GROUP, UNIT, STATIC,
ZONE, OPSZONE, AIRBASE, or TERRITORY id. A missing target leaves the plan
`approved` and prevents all AUFTRAG creation. This is reconciliation at the
execution boundary, not periodic polling.

The COMMANDER selects suitable LEGIONs by default. `allowed_legion_ids` and
`allowed_cohort_ids` on `AssetRequirement` constrain that MOOSE recruitment
when Python needs to make the selection. `OperationalPosture` currently records the planning intent
(`economy`, `balanced`, or `overwhelming`); it does not silently alter asset
counts.

The parameterless example defines a phased OPSZONE capture plan directly in
Python, refreshes LEGION/COHORT state, and prints all provisional allocations
and shortfalls. Set its approval and execution constants to run the plan:

```powershell
& "C:\Program Files\Python313\python.exe" examples/sdk/plan_capture_goal.py
```

The SDK registry synchronizes automatically after relevant bridge snapshots
and events. `bridge.sync_strategic_objectives()` is available for explicit
tests. A control change produces a normalized `objective.control_changed`
event. `capture_actions(event, objective)` identifies components that require
explicit handling; it does not respawn or destroy DCS objects by itself.

`MooseBridgeDcsEventsExtension.lua` subscribes to MOOSE's
`EVENTS.BaseCaptured` dispatcher and forwards a DCS airbase/FARP capture as
`airbase.coalition_changed`. It includes the previous owner cached at bridge
startup, the new authoritative DCS owner, the capturing unit/group, and a full
updated AIRBASE snapshot. Repeated events without an ownership change are
suppressed.

To test the event path, set `AIRBASE_ID` and `OBJECTIVE_ID` directly in the
parameterless example, start it before the capture, then let a hostile ground
unit capture that airbase or FARP in DCS:

```powershell
& "C:\Program Files\Python313\python.exe" examples/sdk/monitor_airbase_capture.py
```

The example waits without polling and prints the normalized
`objective.control_changed` transition.

The same DCS event extension subscribes to `EVENTS.UnitLost` and `EVENTS.Dead`
and forwards each loss as `object.destroyed`. DCS can use either event depending
on the object and destruction path; matching events for the same loss are
deduplicated in Lua. The payload contains a dead UNIT/STATIC tombstone
and, for units, a current MOOSE GROUP snapshot. Python merges the tombstone
with the last known object state, removes stale ammunition data, and updates
strategic component health without requesting another snapshot. This remains
fully event-driven and does not poll destroyed objects.

`EVENTS.MissionEnd` is forwarded as `mission.ended` and defines the hard
boundary of one Python mission session. The daemon clears its mirrored DCS and
MOOSE state, while every active SDK client clears mission-scoped information
requirements, strategic objectives, goals, plans, execution histories, and
AUFTRAG mappings. Persistent audit records are deliberately retained. The Lua
handler flushes this final event immediately because normal bridge scheduling
ends with the DCS mission.

Set `UNIT_ID` directly in the parameterless test example and destroy that unit
in DCS:

```powershell
& "C:\Program Files\Python313\python.exe" examples/sdk/monitor_unit_lost.py
```

The example waits specifically for that object and then prints the updated
unit and group state.

## Python setup

From the project root:

```bash
pip install -e .
python -m moosebridge --host 127.0.0.1 --port 42000 --control-port 42001 --log moosebridge_raw.jsonl --audit-log moosebridge_audit.jsonl
```

On Windows, the included helper scripts set `PYTHONPATH` for local development:

```powershell
.\run_server.ps1
.\run_interactive.ps1
```

The default console script starts the daemon with the local control API enabled:

```bash
moosebridge-server --host 127.0.0.1 --port 42000 --control-port 42001 --log moosebridge_raw.jsonl --audit-log moosebridge_audit.jsonl
```

Additional installed entry points:

- `moosebridge-daemon`: explicit daemon entry point
- `moosebridge-control`: local control client
- `moosebridge-standalone-server`: DCS-facing server without the local control API

See `docs/CONTROL_API.md` for the local multi-client control protocol.
See `docs/INTENTS.md` for the tactical intent and recommendation model.

## First manual test

1. Start the Python bridge daemon.
2. Start the DCS mission with the Lua bridge loaded.
3. Confirm that Python logs the DCS connection and heartbeat.
4. Use the interactive control client or a Python SDK client to request
   snapshots or send a simple semantic command.

Example:

```python
ack = await server.message_to_coalition(
    coalition="blue",
    text="MoosePyBridge connected",
    duration=10,
)
```

## Interactive control client

The local control client is the preferred manual test surface when a daemon is
already running:

```powershell
.\run_control_interactive.ps1
```

Useful commands:

```text
status
snapshots --list groups units zones
snapshots --list units --coalition red --alive --limit 20
coords "ZONE:Town Fight" --format mgrs
distance GROUP:Aerial-1 "ZONE:Town Fight"
nearest units "ZONE:Town Fight" --coalition red --alive --limit 5
drawzone "ZONE:Town Fight" --coalition blue --color red --line-type dashed
message blue Push now
mission BAI --target GROUP:Ground-1 --coalition blue
trace AUFTRAG:1
```

The interactive client uses the same SDK command path as Python tools for
coordinate lookup, distance, nearest-object queries, zone drawing, and AUFTRAG
trace.

## Python SDK examples

Server-backed SDK:

```python
from moosebridge import MooseBridgeClient, MooseBridgeServer

server = MooseBridgeServer(host="127.0.0.1", port=42000)
await server.start()
bridge = MooseBridgeClient(server)

coords = await bridge.coords("ZONE:Town Fight", format="mgrs")
distance = await bridge.distance("GROUP:Aerial-1", "ZONE:Town Fight")
await bridge.draw_zone("ZONE:Town Fight", coalition="blue", color="red", line_type="dashed")
nearest = await bridge.nearest("units", "ZONE:Town Fight", coalition="red", alive=True, limit=5)
trace = await bridge.trace_auftrag("AUFTRAG:1")
```

Control-client backed SDK:

```python
from moosebridge.control import MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client

control = MooseBridgeControlClient(
    "127.0.0.1",
    42001,
    client_id="planning-tool-1",
    display_name="Planning Tool",
)
bridge = sdk_from_control_client(control, timeout=10.0)

await bridge.snapshot_kind("units")
nearest = await bridge.nearest("units", "ZONE:Town Fight", coalition="red", alive=True)
```

Typed OPS state convenience helpers:

```python
from moosebridge import format_commander_status, format_legion_status

await bridge.refresh_legion_state()

legion = bridge.legion("LEGION:Wing Parchim")
commander = bridge.commander("COMMANDER:Blue Command")
command_legions = bridge.legions_of_commander("COMMANDER:Blue Command")
command_missions = bridge.missions_of_commander("COMMANDER:Blue Command")
cohorts = bridge.cohorts_of_legion("LEGION:Wing Parchim")
missions = bridge.missions_of_legion("LEGION:Wing Parchim")
ready = bridge.ready_cohorts_of_legion("LEGION:Wing Parchim", mission_type="BAI")

print(format_legion_status(bridge, "LEGION:Wing Parchim"))
print(format_commander_status(bridge, "COMMANDER:Blue Command"))
```

Situation pictures and GeoJSON export:

```python
tactical = await bridge.refresh_tactical_picture("blue", "INTEL:BlueIntel")
tactical_geojson = tactical.to_geojson()

for assessment in tactical.contact_assessments():
    print(assessment.contact.object_id, assessment.state.value, assessment.age_s, assessment.confidence)

for assessment in tactical.lost_contact_assessments():
    print("lost", assessment.contact.object_id, assessment.age_s, assessment.confidence)

await bridge.add_intel_agent("INTEL:BlueIntel", "GROUP:Blue EWR")

clock = await bridge.get_time()
print(clock.mission_time, clock.dcs_date, clock.time_of_day, clock.wall_time)

global_picture = await bridge.refresh_global_picture()
global_geojson = global_picture.to_geojson()
print(format_global_picture_status(global_picture))
```

`add_intel_agent` remains available for explicit mission setup. Normally MOOSE
maintains all living same-coalition groups through `INTEL:SetAgentAuto()`.

`TacticalPicture` uses INTEL contacts and clusters for enemy knowledge.
`GlobalPicture` uses global truth snapshots and is intended for admin/debug
views or neutral analysis tools.
Confirmed destruction events are stored separately as loss reports. They are
visible in both coalition tactical pictures: as a friendly loss for the owning
coalition and as an enemy loss for the opposing coalition. The global picture
shows the same report as confirmed truth. Loss reports preserve the last known
position and remain separate from MOOSE INTEL contacts.
Both picture types export standard WGS84 GeoJSON. DCS `x/y/z` coordinates stay
available as feature properties, while geometry coordinates use
`[longitude, latitude]` values produced by DCS `coord.LOtoLL`.
The zone snapshot omits MOOSE's automatically generated `_DATABASE.ZONES`
entries whose names match DCS airbases. Airbases remain available as
`AIRBASE` objects, while registered zones and mission trigger zones are kept.
INTEL diagnostics show agents as `alive/total`; both values come directly from
the MOOSE `INTEL.detectionset` (`SET_GROUP`).

Detailed ammunition is refreshed explicitly because DCS has no ammunition
change event and `Unit.getAmmo()` is more expensive than reading ordinary
object state:

```python
units = await bridge.refresh_ammunition()
stryker = bridge.unit_ammunition("UNIT:Stryker-1")
armor_group = bridge.group_ammunition("GROUP:Armor")

for weapon in stryker.weapons if stryker else ():
    print(
        weapon.display_name,
        weapon.family.value,
        weapon.role.value,
        [effect.value for effect in weapon.effects],
        weapon.current_count,
        weapon.initial_count,
        weapon.fraction,
    )
```

Only active, living ground and naval units are included. Weapon entries with
`count=0` are retained. On the first Python observation, the current count becomes the
observed initial count; a later higher value, for example after rearming,
raises that baseline. Different weapon types are never summed into one total.
The baseline resets when DCS mission time moves backwards. The ammunition
snapshot is intentionally separate from `snapshot.all`, so callers can choose
an appropriately slow update interval.

The SDK classifies ammunition in Python along independent dimensions:
`family` (`gun`, `cannon`, `rocket`, `missile`, ...), operational `role`
(`machine_gun`, `main_gun`, `artillery`, `atgm`, `sam`, ...), `delivery`,
launch and target domains, and broad tactical `effects`. Concrete ammunition
types such as `APFSDS`, `HEAT`, `HEI`, or `DPICM` remain available as
`ammunition_type`; they refine effects but do not create a second hierarchy of
weapon classes. Raw DCS descriptors remain available through `weapon.raw`.

DCS descriptor enums and task selectors are modeled separately as
`DcsWeaponCategory`, `DcsMissileCategory`, `DcsGuidanceType`,
`DcsWarheadType`, and `DcsWeaponFlag`. Each ammunition entry exposes all known
specific and parent task selectors through `weapon.weapon_flags`; every
association records its `confidence`, evidence `source`, and whether it is a
specific or broader selector. These associations do not claim that DCS can
select one concrete round from all ammunition matching the same flag.

```python
from moosebridge import DcsWeaponFlag, WeaponRole

selection = bridge.group_task_weapon("GROUP:SPH", role=WeaponRole.ARTILLERY)
if selection.weapon_flag is not None:
    assert isinstance(selection.weapon_flag, DcsWeaponFlag)
    print(selection.weapon_flag.name, int(selection.weapon_flag), selection.confidence.value)
```

If no defensible association exists, the selection contains `weapon_flag=None`.
Callers should then omit the DCS task `weaponType` and let DCS choose. Broad
selectors such as `ANY_ROCKET` permit a weapon category; they do not identify
one exact ammunition entry returned by `Unit.getAmmo()`.

Task weapon ranges use the same executable boundary as DCS: one profile is
keyed by `dcs_type + DcsWeaponFlag`. The packaged ground-unit data is generated
offline from the versioned
[dcs-lua-datamine](https://github.com/Quaggles/dcs-lua-datamine) descriptors;
the runtime SDK has no GitHub or network dependency. Resolution order is:
explicit manual profile, exact datamine weapon station, usable live DCS weapon
descriptor, unambiguous datamine unit threat envelope, conservative role
fallback, and optional generic flag fallback. Ambiguous unit envelopes are
retained for diagnostics but are not assigned to several weapons. For example,
the Bradley's unit-level range is not reused as both its cannon and TOW range.

```python
from moosebridge import DcsWeaponFlag, format_weapon_range

profile = bridge.unit_weapon_range("UNIT:MLRS", DcsWeaponFlag.ANY_ROCKET)
print(format_weapon_range(profile))

if profile is not None and profile.contains(25_000):
    print("Target is inside the task weapon envelope")
```

Scenario-specific profiles can be supplied without modifying the package:

```python
from moosebridge import (
    DcsWeaponFlag,
    MANUAL_WEAPON_RANGE_PROFILES,
    RangeSource,
    WeaponRangeProfile,
    WeaponRangeRegistry,
    sdk_from_control_client,
)

custom_profile = WeaponRangeProfile(
    dcs_type="My Artillery Mod",
    weapon_flag=DcsWeaponFlag.CONVENTIONAL_SHELL,
    minimum_m=500,
    maximum_m=40_000,
    source=RangeSource.MANUAL,
)
registry = WeaponRangeRegistry(profiles=(*MANUAL_WEAPON_RANGE_PROFILES, custom_profile))
bridge = sdk_from_control_client(control, weapon_ranges=registry)
```

Refresh the generated artifact from a local datamine checkout after a DCS
update:

```powershell
python tools/import_dcs_datamine.py C:\path\to\dcs-lua-datamine
```

The generated JSON records the source commit and DCS build. It contains every
ground-unit descriptor, including non-combat units and ambiguous descriptors,
while the registry activates only defensible task-selector mappings.

The same import also generates versioned sensor data for ground units,
airplanes, and helicopters from `maxTargetDetectionRange` and referenced DCS
sensor descriptors. Profiles retain the platform category, sensor type,
target domain, radar/IRST mode, published detection bound, hard measuring
limit, reference RCS, scan period, and whether the range is safe for exclusion.
Sensors such as optics and RWR are retained even when DCS publishes no numeric
range for them.

Numeric values are optimistic upper bounds, not promises that DCS will detect
a target. Inside a bound, terrain, line of sight, aspect, weather, target RCS,
radial velocity, sensor mode, and DCS sensor logic still determine the result.

```python
from moosebridge import SensorTargetDomain, format_sensor_range

profiles = bridge.group_sensor_ranges(
    "GROUP:Recon",
    target_domain=SensorTargetDomain.SURFACE,
)
for profile in profiles:
    print(format_sensor_range(profile))

excluded = bridge.unit_detection_excluded(
    "UNIT:Recon-1",
    distance_m=12_000,
    target_domain="surface",
)
if excluded is True:
    print("Organic detection is outside the known sensor envelope")
elif excluded is None:
    print("No complete unit-level sensor envelope is known")

radar_excluded = bridge.unit_sensor_detection_excluded(
    "UNIT:Hornet-1",
    "radar",
    distance_m=200_000,
    target_domain="surface",
    mode="rbm",
)
```

`unit_detection_excluded()` only uses a complete `unit`-scope envelope. The
datamine provides this for ground units through `maxTargetDetectionRange`, but
not for aircraft. Aircraft and helicopter callers can use
`unit_sensor_detection_excluded()` for a specific bounded sensor or mode.
That function returns `None` when any matching sensor has an unknown or unsafe
range. RWR profiles are marked `emitter_only` and are never treated as general
target detection.

`False` from either exclusion method means only that detection remains
possible. It must never be interpreted as a confirmed contact. Manual profiles
can be supplied through `SensorRangeRegistry` and passed to
`sdk_from_control_client(..., sensor_ranges=registry)`.

For a broad selector, the profile describes the envelope in which at least one
matching weapon can fire. `weapon_ids` records the observed or manually known
ammunition behind that envelope; it does not claim that DCS can select one
specific round when several entries share the same task flag.

The default role envelopes are deliberately conservative:

| Weapon role | Minimum | Maximum |
| --- | ---: | ---: |
| `machine_gun` | 0 m | 800 m |
| `autocannon` | 50 m | 1,500 m |
| `main_gun` | 50 m | 2,000 m |
| `atgm` | 100 m | 3,000 m |
| `mortar` | 100 m | 5,000 m |
| `artillery` | 500 m | 15,000 m |
| `rocket_artillery` | 5,000 m | 20,000 m |

When several roles share one DCS selector and no stronger data exists, their
possible fallback envelopes are combined. Versioned datamine profiles and live
DCS descriptor profiles take precedence over this `role_fallback` result.

Classified ammunition can be aggregated into traceable unit and group
readiness vectors:

```python
unit_profile = bridge.unit_capabilities("UNIT:Armor-1")
group_profile = bridge.group_capabilities("GROUP:Armor")
print(format_group_capabilities(group_profile))
```

Each capability keeps `base_power`, `ammo_readiness`, `health_readiness`, and
`effective_power` separate. Ammunition counts are combined only inside the
same weapon role and capability. Direct combat units receive normal presence,
indirect-fire and air-defense units receive reduced presence, and an unarmed
logistics unit retains a small default presence of `0.10`. Artillery and MLRS
produce `indirect_fire`; they do not currently add local direct-fire power.
The relative coefficients are centralized in `moosebridge.capabilities` for
scenario-based calibration.

Spatial influence is modeled separately from diagnostic presence:

```python
from moosebridge import format_group_influence

influence = bridge.group_influence("GROUP:Armor")
print(format_group_influence(influence))
```

The independent kinds are `control`, `direct_fire`, `indirect_fire`,
`air_defense`, and `logistics`. Only `control` contributes to the land
frontline. Unarmed supply and transport units contribute exclusively to
`logistics`; air-defense power does not move the ground frontline. Artillery
retains only a small local control contribution while its principal effect is
`indirect_fire`. Health and ammunition readiness affect each applicable value,
and weapon ranges come from the same versioned range registry.

### Global map viewer

Install the optional browser-map dependencies and start the viewer while the
MooseBridge daemon is running:

```powershell
python -m pip install -e ".[map]"
.\run_map.ps1
```

Open `http://127.0.0.1:8000`. The viewer connects to the daemon control API on
`127.0.0.1:42001`, refreshes the global picture every five seconds, and pushes
updates to the browser through a WebSocket. Alternatively, run
`python -m moosebridge.map_server`; append `--help` to change hosts, ports,
update interval, command timeout, or movement history limits. The viewer keeps
15 minutes and at most 180 samples per moving object by default. For example:

```powershell
python -m moosebridge.map_server --history-seconds 1800 --history-max-points 360
```

For deterministic browser QA without a running DCS mission, start the all-layer
fixture and open `http://127.0.0.1:8012`:

```powershell
python tools/run_map_fixture_server.py
```

The fixture includes representative forces, territorial control, zones, INTEL,
airbases, operations, events, movement history, and RECON coverage. Its
`/qa/mobile` page embeds the same viewer in a real 390-pixel viewport for
responsive layout checks.

`Layers > Map appearance` selects OpenStreetMap, CARTO Light, or CARTO Dark and
controls basemap, territory, and topography opacity independently. These
display-only preferences are stored locally by the browser and survive page
reloads; they do not change layer visibility, filters, or situation-picture
data.

The `GermanyCW` theater can use an offline OpenStreetMap baseline for water,
major roads, railways, cities, towns, land use, and infrastructure candidates.
The primary import downloads regional Geofabrik PBF extracts and filters them
locally, outside the running DCS mission:

```powershell
python -m pip install -e ".[topography]"
python examples/sdk/capture_topography_coverage.py
python tools/import_geofabrik_topography.py
python tools/build_topography_viewport_cache.py
```

Before the full import, create mission-editor zones using this naming scheme:

- `Topography All` encloses the complete usable DCS terrain. Multiple `All`
  zones with a suffix are allowed when the terrain cannot be represented by a
  single polygon.
- `Topography Low <name>` marks broad operational areas. It adds primary and
  secondary roads, towns, military/industrial land use, and bridges.
- `Topography High <name>` marks focused areas. It additionally includes
  tertiary and unclassified roads, villages, detailed land use, and minor
  railways. Generic residential/service roads and individual buildings remain
  excluded from the theater-wide browser cache; `--include-buildings` is
  reserved for deliberately small focused imports. Detailed land use remains
  limited to operationally useful residential, commercial, industrial,
  military, retail, and port areas; arbitrary OSM land-use polygons are not
  imported theater-wide.

The capture example requests the current zone snapshot and writes
`tmp/topography/GermanyCW-coverage.geojson`. Circle and polygon zones are both
supported. The heavy PBF conversion then runs offline. `all` is deliberately a
baseline coverage level rather than "all OSM objects": coastlines, water,
motorways, trunk roads, main railways, cities, harbours, and power plants remain
available across the complete terrain without making the browser cache
unmanageably large. Higher levels include every lower level automatically.

PBF files and the normalized cache are written below `tmp/topography/`.
Subsequent imports reuse the downloads unless `--refresh` is specified.
Use repeated `--source <id>` arguments for a smaller regional development
import; the source IDs are listed in `GermanyCW_topography.json`. Geometries are
topology-preservingly simplified by 20 meters by default; override this with
`--simplify-meters`, or use `--simplify-meters 0` for the original geometry.
Individual building polygons are deliberately excluded from the browser cache
by default; add `--include-buildings` when they are needed for a focused test.
The complete GermanyCW import currently contains more than 4.5 million features
and is an offline analysis source, not a single browser payload. The viewport
builder converts each non-empty import checkpoint to spatially indexed
FlatGeobuf and writes `tmp/topography/viewport/manifest.json`. It is incremental:
unchanged source shards are reused unless `--refresh` is specified.

The map server discovers that manifest by default. The browser consumes one
Mapbox Vector Tile source per enabled topography layer from
`/api/topography/tiles/{layer}/{z}/{x}/{y}.pbf`, so roads, water, land use, and
other layers can be loaded independently. Zoom levels below 6 use the `all`
baseline, zoom 6 adds `low`, and zoom 10 adds `high`. Interactive vector tiles
start at zoom 8, omit large raw OSM tag dictionaries, and are cached by the
server and browser. The bounded `/api/topography/viewport.geojson` endpoint
remains available for diagnostics and exports; it limits responses to 20,000
features by default and reports `properties.truncated=true` when necessary.
The server refuses to load a static GeoJSON larger than 256 MiB by default and
exposes the reason in `/api/health`; use `--max-topography-mb` to change the
guard. A deliberately bounded legacy cache can still be selected with
`--topography <path>`. Static data is independent of the five-second DCS picture
stream. The external layers are disabled initially and grouped under
`Topography` in the viewer.

The Overpass importer remains available for small experiments and targeted
updates:

```powershell
python tools/import_osm_topography.py
```

Imported features retain their source, confidence, scenario reference year,
source snapshot date, optional validity dates, and `dcs_verified` state.
Current OpenStreetMap data is only a
baseline for the historically oriented DCS terrain. It must not be treated as
DCS movement truth until targeted terrain and route verification has been
added.

For a bounded visual comparison on the native DCS F10 map, load the current
`MooseBridge.lua` into the mission and run:

```powershell
python examples/sdk/verify_topography_overlay.py
```

The example has no command-line parameters. Its constants select the cache,
center airbase, radius, layers, simplification, and safety limits. Python clips
the WGS84 features around the selected DCS object; Lua converts them through
`coord.LLtoLO` and draws native circles and line segments with
`trigger.action.circleToAll` and `trigger.action.lineToAll`. Press Enter after inspection to remove every mark
belonging to the named overlay. The SDK methods are `draw_debug_overlay()` and
`clear_debug_overlay()`; batches are limited to 200 geometry parts, 2,000
points, and 500 native DCS markups.

For a quantitative road comparison, load the current `MooseBridge.lua`, start
the mission, and run:

```powershell
python examples/sdk/verify_road_alignment.py
```

The script samples OSM road centerlines around the configured object and asks
DCS `land.getClosestPointOnRoads()` for the nearest native road. Green points
are within 50 m, yellow points within 200 m, and red points have no close DCS
road match. Yellow and red samples also draw a connector to the DCS result and
the console reports median, 90th-percentile, and maximum displacement.

Land/water agreement can be checked independently:

```powershell
python examples/sdk/verify_surface_alignment.py
```

The test builds balanced OSM land/water samples while excluding a configurable
shoreline margin and oversampling the usually smaller water area, then
classifies every point with DCS `land.getSurfaceType()`.
Green marks are matching land (`LAND`, `ROAD`, or `RUNWAY`), cyan marks are
matching water (`SHALLOW_WATER` or `WATER`), and red marks are disagreements.
The console prints the complete coarse confusion matrix and native DCS surface
type counts.

Connected physical land and water components use prepared OSMCoastline sea
polygons as the production baseline. Land is their exact complement inside the
GermanyCW bounds, while closed regional OSM water polygons add the detailed
inland-water network. Download the prepared polygons once, then build the
regions offline:

```powershell
python tools/download_osm_coastline_data.py
python tools/build_surface_regions.py
```

The default 500 m full-theater analysis grid uses four-neighbor connectivity so regions
that touch only at a corner remain separate. Output is written to
`tmp/topography/GermanyCW-surface-regions.geojson` and records mainland,
island, maritime, and inland-water components with area, source confidence,
grid resolution, and source-completeness metadata. The map server loads this
artifact by default; use `--surface-regions <path>` to select another file.
Enable `Connected land` and `Connected water` under `Topography` in the browser
map. These are physical components only: bridges and vessel-specific width or
depth constraints belong to the later mobility graph. Output simplification is
disabled by default because simplifying adjacent components independently can
create overlaps along their shared coastline. For a complete large import the
builder first creates and subsequently reuses
`GermanyCW-surface-source.geojson`, which contains only directed coastlines and
closed water polygons; use `--refresh-surface-source` after replacing import
checkpoints. The Natural Earth files are stored below
`tmp/topography/osmcoastline/` and are reused unless the download command is
called with `--refresh`. Natural Earth remains available through
`--baseline natural-earth` as an independent comparison reference.

The downloader defaults to the official simplified OSMCoastline Mercator
datasets, whose detail is appropriate for the 500 m strategic grid; the
full-resolution global archives remain optional because each is currently
close to 1 GB. Natural Earth and OSMCoastline can be compared on a bounded area
without replacing the production artifact:

```powershell
python tools/download_osm_coastline_data.py
python tools/build_surface_regions.py --baseline natural-earth --bounds 53 9 56 16 --grid-spacing 1000 --minimum-area-km2 25 --output tmp/topography/GermanyCW-surface-regions-naturalearth-test.geojson
python tools/build_surface_regions.py --baseline osm --bounds 53 9 56 16 --grid-spacing 1000 --minimum-area-km2 25 --output tmp/topography/GermanyCW-surface-regions-osm-test.geojson
python tools/compare_surface_regions.py --reference tmp/topography/GermanyCW-surface-regions-naturalearth-test.geojson --candidate tmp/topography/GermanyCW-surface-regions-osm-test.geojson
```

The OSM mode loads the spatially split sea polygons and derives land as their
exact complement inside the requested theater bounds. Detailed inland water
continues to come from the regional Geofabrik imports. The comparison writes
every sampled disagreement to
`tmp/topography/GermanyCW-surface-comparison.geojson` for inspection in a GIS.
The initial north-Germany and western-Baltic comparison agreed at 99.67% of
6,055 independent 5 km samples, with 20 changed classifications.

With the daemon and a GermanyCW mission running, validate exactly those changed
points against native DCS terrain data:

```powershell
python examples/sdk/verify_coastline_baselines.py
```

The script calls DCS `land.getSurfaceType()` for every disagreement, prints
which baseline matches DCS, and draws the points on the F10 map. Green means
the prepared OSMCoastline result matches DCS; orange means the current
Natural Earth/local-coastline reference matches DCS. The production surface
artifact is not changed by this diagnostic.

To inspect the prepared OSMCoastline geometry directly on the native DCS F10
map, run:

```powershell
python examples/sdk/draw_coastline_overlay.py
```

The example clips the coastline around the configured DCS object, removes
internal polygon joins, and increases simplification only as needed to stay
within the native DCS markup budget. The cyan line remains visible until Enter
is pressed.

Build the strategic ground-mobility graph after updating either the connected
surface artifact or the indexed OSM topography:

```powershell
python tools/build_ground_mobility.py
python tools/validate_ground_mobility_theater.py
```

The 5 km graph treats OSMCoastline land/water as a hard constraint, uses
motorway, trunk, primary, and secondary roads to estimate travel time, and
creates explicit links across OSM-tagged bridge heads. Wheeled and tracked
profiles apply different conservative road and off-road speeds. The graph is
validated against a bridge-connected mainland-to-Rugen route and a deliberately
disconnected mainland-to-Bornholm route. It is
used for fast strategic feasibility and cost estimates; it is not sufficiently
detailed to define tactical waypoints. A live DCS route diagnostic is available
through:

```powershell
python examples/sdk/inspect_ground_route.py
```

Edit the two object IDs and movement profile at the top of the example. After
the strategic graph confirms connectivity, the SDK requests one bounded native
`land.findPathOnRoads` route from DCS. The console reports both results and the
refined DCS road route is drawn in magenta on the F10 map. Native road routing
can now be compared with an additional compact Python/OSM graph. Build the
full GermanyCW graph once. The resumable builder clips and caches each configured
Geofabrik region in an isolated worker process before merging global OSM IDs:

```powershell
python -m pip install -e ".[routing]"
python tools/build_road_routing.py
python tools/validate_road_routing.py
python tools/validate_hierarchical_road_routing.py
python examples/sdk/inspect_ground_route.py
python examples/sdk/benchmark_road_routing.py
```

The Python graph deliberately treats every imported road as bidirectional and
ignores OSM access restrictions, matching permissive DCS military movement.
Road class affects estimated speed; bridges are retained as metadata without
weight or access restrictions. The F10 comparison draws native DCS in magenta
and Python/OSM in cyan. DCS returns both `findPathOnRoads` CPU time and total Lua
command CPU time when the current bridge version is loaded.

The complete graph is a 1.48-GiB reference artifact with about 32.0 million
nodes and 34.2 million edges. Cross-region validation connects Hamburg, Berlin,
Frankfurt, and Amsterdam. The SDK's `HierarchicalRoadRouter` first computes a
coarse strategic route, selects occupied 25-km cells in a configurable corridor,
and then assembles and caches only the required detailed OSM graph. The default
50-km corridor reproduces the full-graph validation distances. Laage to Gross
Mohrdorf uses about 348,000 nodes and takes roughly 2.7 seconds cold or 0.4
seconds warm on the development system. Continental warm routes currently take
about 2-27 seconds; prebuilt spatial graph tiles remain the next performance
step for interactive theater-wide routing.

Native road routing is intentionally used only for selected corridors because DCS calculates it
synchronously and can return many points.

The same detailed road graph can also be reduced to stable strategic
infrastructure objects:

```powershell
python tools/build_transport_infrastructure.py
```

This writes `tmp/topography/GermanyCW-transport-infrastructure.geojson`.

Normalized energy and fuel-storage candidates use a separate, theater-aware
site artifact:

```powershell
python tools/build_infrastructure_sites.py
```

When only the maritime taxonomy changes, the existing indexed topography cache
can update that category without repeating the expensive theater-wide PBF scan:

```powershell
python tools/build_maritime_sites.py
```

This preserves the other normalized categories, removes legacy industrial
shipyard duplicates, and replaces the maritime sites atomically in the same
artifact. A later full infrastructure build remains the authoritative route
when the source PBF snapshots themselves change.

For GermanyCW, modern wind, solar, biogas, and battery sites are excluded by
policy; other theaters allow them unless their own policy says otherwise. Power
plants are clustered by stable identity and proximity. Grid substations require
at least 110 kV; converter stations are retained separately, while transformers
and local distribution equipment are excluded. A
bounded DCS scenery check is available through
`await bridge.survey_scenery(latitude, longitude, radius_m=500)`.
The map server loads the normalized cache automatically and exposes it through
`/api/infrastructure-sites/global.geojson`. `Energy sites`, `Fuel and storage
sites`, `Military sites`, `Industrial sites`, and `Ports and maritime logistics` are separate, initially hidden
layers under `Infrastructure`. Energy sites can be filtered into power plants,
grid substations, and converter stations. The map uses importance-weighted
representative markers and normalized footprints while the SDK artifact retains
source identifiers and component membership. Maritime normalization groups
port anchors with nearby piers, quays, docks, basins, and berths. Generic local
harbours remain low-weight context; cargo, terminal, ferry, fishing, and shipyard
evidence determines operational roles and strategic importance.

The GermanyCW cache currently contains 3,718 energy sites, 440 fuel or bulk
storage sites, 1,100 military sites, 5,641 industrial sites, and 507 maritime
sites. Of the maritime sites, 301 currently have explicit strategic evidence;
generic local harbours remain low-weight context. Fuel admission
is deliberately conservative: a candidate needs
explicit fuel-storage, oil-storage, gas-storage, terminal, depot, tank, or
refinery evidence. A generic oil or gas industry tag is insufficient. Water,
slurry, and unspecified tanks are not promoted to operational sites. Related
terminal, refinery, and tank components are clustered into one location.
Energy sites record normalized role, source, electrical output, maximum grid
voltage, footprint, scale, importance score and tier. Of the current energy
sites, 2,733 are generation sites, 928 major substations, and 57 converter
stations; 452 are currently strategic candidates.
Military sites retain typed roles such as barracks, depot, ammunition storage,
radar, communications, naval base, training area, and firing range. Their source
components are combined into a hole-free footprint with a representative anchor,
area, scale, and role-led importance score. DCS
airfields remain represented by `AIRBASE` objects, and unnamed individual
bunkers are excluded. Training and firing areas provide geographic context but
are not automatically targetable strategic sites. The map uses weighted markers
at overview zoom and normalized footprints from zoom 8.
Industrial admission requires an explicit factory or industry role, product
evidence, or a recognized named works. Generic and unnamed industrial estates
are not promoted. The SDK records normalized roles, products, a hole-free
combined footprint, scale, importance score and tier, and a separate
`strategic_candidate` flag. Role is weighted most strongly; size, product,
operator, and multiple-role evidence refine the score. The map shows weighted
overview markers and switches to the normalized industrial footprint from zoom
9. The current GermanyCW cache classifies 2,037 of 5,641 industrial sites as
strategic candidates.

To inspect one admitted infrastructure site against nearby addressable DCS
scenery, start DCS, the bridge daemon, and a mission, then run the
parameter-free example:

```powershell
python examples/sdk/verify_infrastructure_site.py
```

By default it selects the admitted fuel-storage site nearest `AIRBASE:Laage`,
prints the bounded scenery survey, and draws a temporary F10 verification
overlay. Edit the typed constants at the top of the file to select energy,
another site, reference, or radius. `verify_energy_site.py` remains a compact
energy-specific entry point using the same implementation;
`verify_military_site.py` selects the military layer and
`verify_industrial_site.py` selects industry. Maritime sites normalize civilian
ports, cargo/container/bulk/RoRo and ferry terminals, fishing ports, passenger
terminals, and shipyards. Piers, quays, docks, harbour basins, and berths are
retained as components of their nearest port rather than promoted to independent
strategic locations. Naval bases remain military sites. The model records
explicit cargo types plus footprint, approximate quay length, berth count,
importance, and source membership; it does not infer throughput where OSM has
no capacity evidence.

Named cities and towns use a separate normalized artifact:

```powershell
python tools/build_settlements.py
```

The builder prefers matching OSM administrative boundaries and retains the
urban footprint as a fallback. German city states, independent cities, and
municipalities are matched across administrative levels 4, 6, and 8 by
Wikidata or normalized name. To compare Hamburg without reading every PBF:

```powershell
python tools/build_settlements.py --boundary-source hamburg --output tmp/topography/GermanyCW-settlements-administrative-test.geojson
./run_map.ps1 --settlements tmp/topography/GermanyCW-settlements-administrative-test.geojson
```

Use `--boundary-mode urban` to reproduce the previous footprint-only artifact.
Administrative boundaries are modern comparison evidence and are identified by
`boundary_kind=administrative`, `administrative_level`, and their OSM relation.
`administrative_area_m2` records the municipal area, while `urban_area_m2`
continues to describe the generalized built-up footprint used by the importance
score. For matched settlements, `urban_geometry` contains a connected, hole-free
urban core derived from the smoothed footprint. Detached minor components are
discarded; inland water, parks, and other internal gaps remain part of the strategic
city area. The core is clipped to the administrative boundary. The map renders it as the stronger fill
and keeps the administrative boundary as a restrained dashed outline.

By default this writes `tmp/topography/GermanyCW-settlements.geojson` and is loaded by the
map server through `/api/settlements/global.geojson`. The current cache contains
2,625 cities and towns, including 2,336 administrative boundaries, 2,274
clipped urban envelopes, 288 urban-footprint fallbacks, and 2,318 source
population values. `Cities and towns` is an initially hidden
Infrastructure layer. Population dates and OSM provenance are retained because
modern source values need not match the 1999 scenario. The importance class is
planning evidence only; settlements do not become strategic objectives
automatically.
Adjacent OSM road edges carrying a `bridge` tag are first connected and then
collapsed with nearby structures into abstract `TransportBridge` locations.
The default 150 m radius combines parallel carriageway decks and fragmented
OSM structures without transitive chaining. The point object retains its raw
bridge IDs, total length, road classes, endpoint OSM IDs, and approach count.
`TransportJunction` objects are created where at least three strategic road
arms meet. By default, the strategic network includes
motorway, trunk, primary, and secondary roads and their link roads; residential
and service-road intersections are deliberately excluded. Nearby same-kind OSM
nodes are then collapsed into operational junction complexes without transitive
chaining: 300 m for motorway/trunk interchanges and 100 m for other strategic
junctions. All member OSM IDs remain in the resulting object. The extraction
can be adjusted with repeated `--highway` arguments, `--minimum-arms`,
`--bridge-cluster-radius`, `--interchange-cluster-radius`, and
`--junction-cluster-radius`.

The map server loads this cache automatically. `Bridges` and `Transport
junctions` are separate, initially hidden layers under `Infrastructure`, and
the HTTP source is available at
`/api/transport-infrastructure/global.geojson`. These objects describe OSM
topology, not verified military load limits or DCS-destructible map objects.
They are intended as route dependencies and candidates for later strategic
objective and damage-state modelling.

Route criticality is an explicit offline refinement because it is substantially
more expensive than extracting locations. Run it against a regional detailed
graph when needed:

```powershell
python tools/build_transport_infrastructure.py `
  --input tmp/topography/GermanyCW-road-routing-mv.npz `
  --output tmp/topography/GermanyCW-transport-infrastructure-mv.geojson `
  --analyze-criticality
```

For each location, Python blocks a bounded area, identifies opposite strategic
road portals, and searches up to three alternatives within 50 km. The artifact
stores road-hierarchy importance, alternative distance, added detour, detour
ratio, a 0-100 score, and `low`, `medium`, `high`, or `critical`. A missing
alternative means none was found inside the configured analysis limit; it does
not prove that the continental road network is physically disconnected. The
map colors high locations orange and critical locations red. On the MV graph,
the complete analysis currently takes about 94 seconds, so it is not part of
the fast default extraction.

Display tiers are calibrated separately: bridge thresholds are 95/82/55 and
junction thresholds are 95/85/65 for critical/high/medium. At theater overview
zoom only high and critical locations are rendered; medium locations appear at
zoom 9 and low locations at zoom 11. The underlying features and numeric scores
remain available independently of this visual level of detail.

Operational railway locations use a separate aggregated cache:

```powershell
python tools/build_railway_infrastructure.py
```

Optional offline railway-network and failure analysis is enabled explicitly:

```powershell
python tools/build_railway_infrastructure.py --analyze-criticality
```

This additionally writes `GermanyCW-railway-routing.npz` and assesses only
high or critical rail junctions and bridges. A failed bridge blocks its rail
edges; a failed junction blocks its local graph nodes. The resulting
properties distinguish network disconnection from an available but longer
alternative route. The expensive analysis is not run by the map server.

This reads ordinary railway lines from the indexed topography shards and only
the relevant station, halt, freight, yard, and depot tags from the local
Geofabrik PBF files. Per-source facility reads are cached below
`tmp/topography/railway_facility_cache`, so an interrupted theater-wide build
can be resumed. Use `--refresh-facilities` only when the PBF inputs or railway
classification have changed. A bounded regional diagnostic can be generated
with `--source mecklenburg-vorpommern`.

The resulting `tmp/topography/GermanyCW-railway-infrastructure.geojson`
contains aggregated stations, freight terminals, rail yards, depots,
rail junctions, and rail bridges. Ordinary track remains in the Topography
layer and is not duplicated as infrastructure. Each operational location keeps
its source members and receives a transparent importance score and tier based
on facility role, topology, and extent. These values are planning evidence,
not proof that the modern OSM facility exists in the 1999 DCS theater.

The map server loads the cache automatically and exposes it through
`/api/railway-infrastructure/global.geojson`. `Rail infrastructure` is one
initially hidden Infrastructure group whose six location classes can be toggled
independently.

For a valid mission scope, the map server generates the bounded strategic
objective set once per mission and keeps its ownership and condition synchronized
from live state. `Operations > Strategic objectives` shows these selected targets
with owner-colored flag markers scaled by strategic value. The detail panel exposes
their rank, category, scope, value, control object, and component references. The
map filters can restrict objectives by owner, broad category, and selection rank.
From an objective's detail panel, an operator can derive one planned blue or red
goal through the same relationship-aware rules used by the Python SDK. This action
selects intent only; it does not activate a goal or execute an operational plan.

The header shows the shared relationship, escalation score, pending transition,
and blue/red doctrine. The map server is the default diplomacy incident
coordinator while it runs: it consumes retained `combat.kill` events, evaluates
tolerated ground-border violations from the existing snapshots, and persists
changes for other SDK clients. No additional Lua polling is introduced.

Movement history is derived from periodic DCS positions because DCS does not
emit position-change events. Tracks are removed when an object dies or
disappears and are reset when mission time restarts.

Completed structured RECON assessments from each plan's latest execution and
direct `execute_recon()` runs are loaded from the persistent audit and shown
under `RECON coverage`. The combined search
footprint is visible by default; individual asset footprints can be enabled
separately. Covered and uncovered known objective components use distinct map
markers. These polygons represent optimistic potential sensor access along the
sampled asset routes, clipped to the tasked area. They do not assert confirmed
detection or the absence of enemy units.

INTEL collection itself is independent of AUFTRAG lifecycle. Every group in
the coalition's automatic MOOSE INTEL agent set can create or update contacts
while executing any mission or no mission at all. A `ReconOutcome` therefore
uses observations from every coalition source to evaluate its information
requirement. It marks observations from explicitly assigned RECON assets only
for contribution diagnostics. `execute_recon()` and the operational executor
share the same route sampler and spatial coverage calculation.

Continuous target-knowledge needs are represented separately from RECON
tasking:

```python
from moosebridge import InformationRequirement, format_information_requirement

requirement = bridge.add_information_requirement(
    InformationRequirement(
        "ISR:Town defenders",
        "INTEL:Blue Intel",
        ("GROUP:Ground-1", "GROUP:Ground-7"),
    )
)

async def report(event):
    print(event.event, event.requirement_id, event.status.value)
    print(format_information_requirement(requirement))

await bridge.monitor_information_requirements(report)
```

The registry transitions through `open`, `partial`, `satisfied`, and `lost`
from general `intel.new_contact` and `intel.lost_contact` events. These states
never submit, cancel, or otherwise modify an AUFTRAG. A running RECON continues
to its normal MOOSE completion even when another coalition unit satisfies the
requirement.

The map server also calculates a live operational frontline every 15 mission
seconds by default:

- only active, living blue and red ground groups are considered;
- group control weight is aggregated from the current per-unit health,
  ammunition, weapon roles, and ranges;
- unarmed logistics groups are excluded from the land frontline;
- aircraft, helicopters, and ships do not influence the land frontline;
- group positions are smoothed before influence-field calculation;
- polygon territories form a combined calculation area that includes neutral
  gaps between them;
- distance to blue and red territory supplies the stable ownership field; its
  neutral zero line runs between non-overlapping territory boundaries;
- forces still inside their own territory add pressure and defensive strength
  but do not move the territorial frontline;
- forces in the neutral corridor or opposing territory deform the frontline
  locally; active forces also anchor their immediate surroundings, allowing
  bridgeheads and surrounded pockets;
- isolated hostile ground groups inside an opposing territory are published
  as `Incursions`; they may form a local territorial pocket but do not distort
  the main force-pressure calculation;
- all generated line vertices are converted through one batched DCS
  `coord.LOtoLL` call;
- the territorial result is published as `Frontlines`; the previous force
  balance contour remains available as the default-hidden `Pressure line`,
  alongside the `Incursions` layer.

Positions and the frontline are recalculated independently from ammunition.
The more expensive ammunition snapshot refreshes every 60 mission seconds by
default, and its influence weights are reused between refreshes. Group map
features expose the current separated values under `influence`.

The recalculation interval and smoothing factor can be changed when starting
the server:

```powershell
python -m moosebridge.map_server --frontline-interval 15 --ammunition-interval 60 --frontline-position-alpha 0.35
```

The local anchor defaults to a 5 km Gaussian scale and a 25 percent own-field
margin. Both are configurable with `--force-anchor-sigma` and
`--force-anchor-margin`.

Territorial ownership has a default strength of `1.0` relative to peak force
pressure and transitions over 20 km. These values are configurable with
`--territory-control-ratio` and `--territory-transition`. The pressure line
retains a weak independent territory prior controlled by
`--pressure-territory-ratio`.

### Operational frontline diagnostics

The frontline module derives territorial control from passive MOOSE territory
polygons and uses weighted blue/red ground forces for local deformation and a
separate pressure balance. It does not create or scan large MOOSE `OPSZONE`s.

Install the numerical/geospatial dependencies and run the isolated synthetic
example:

```powershell
python -m pip install -e ".[frontline]"
python examples/frontline/frontline_prototype.py
```

The script has no command-line parameters. Edit its constants and synthetic
forces directly. It writes `tmp/frontline_prototype.geojson` and a standalone
interactive diagnostic viewer to `tmp/frontline_prototype.html`.

The reusable API consists of `ForcePoint`, `TerritoryControlRegion`,
`FrontlineCalculationArea`, `FrontlineConfig`, `FrontlineForceTracker`,
`classify_frontline_forces()`, and `FrontlineEngine` in
`moosebridge.frontlines`. Python owns the influence model, incursion
classification, and frontline calculation. MOOSE/DCS remain the source of
object state and Mission Editor-aligned passive territory geometry.

To monitor and validate the global truth picture without command-line
parameters, edit the constants in and run:

```bash
python examples/sdk/monitor_global_picture.py
```

MOOSE-like AUFTRAG helper objects:

```python
from moosebridge import Auftrag_AIRDEFENSE, Auftrag_AMMOSUPPLY, Auftrag_ANTISHIP, Auftrag_ARTY, Auftrag_AWACS, Auftrag_BAI, Auftrag_BOMBCARPET, Auftrag_BOMBRUNWAY, Auftrag_CAP, Auftrag_CAPTUREZONE, Auftrag_CAS, Auftrag_CASENHANCED, Auftrag_ESCORT, Auftrag_EWR, Auftrag_FAC, Auftrag_FACA, Auftrag_FUELSUPPLY, Auftrag_GROUNDATTACK, Auftrag_GROUNDESCORT, Auftrag_INTERCEPT, Auftrag_NAVALENGAGEMENT, Auftrag_NOTHING, Auftrag_ONGUARD, Auftrag_ORBIT, Auftrag_PATROLZONE, Auftrag_REARMING, Auftrag_RECON, Auftrag_RESCUEHELO, Auftrag_SEAD, Auftrag_STRAFING, Auftrag_STRIKE, Auftrag_TANKER, Auftrag_TROOPTRANSPORT, GroupSet, ZoneSet, format_recon_outcome

auftrag_bai = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)
ack = await bridge.add_auftrag(auftrag=auftrag_bai, commander="COMMANDER:Blue Command")

# Optional Python constraints. Without them, COMMANDER selects suitable LEGIONs.
ack = await bridge.add_auftrag(
    auftrag=Auftrag_BAI(target="UNIT:Ground-1-1"),
    commander="COMMANDER:Blue Command",
    allowed_legions=["LEGION:Wing Parchim"],
    allowed_cohorts=["COHORT:F-4E Parchim Alpha"],
)

summary = await bridge.get_auftrag_summary(auftrag_bai, on_status=print)
if summary.success is True:
    print("BAI succeeded")

await bridge.pause_mission(auftrag_bai)
await bridge.resume_mission(auftrag_bai)
await bridge.cancel_mission(auftrag_bai)

auftrag_arty = Auftrag_ARTY(target="UNIT:Ground-1-1", nshots=6)
ack = await bridge.add_auftrag(auftrag=auftrag_arty, opsgroup="OPSGROUP:Group-1")
await bridge.assign_mission("AUFTRAG:1", legion="LEGION:Wing Parchim")

auftrag_bombrunway = Auftrag_BOMBRUNWAY(target="AIRBASE:Parchim", altitude_ft=25000)
ack = await bridge.add_auftrag(auftrag=auftrag_bombrunway, legion="LEGION:Wing Parchim")

auftrag_bombcarpet = Auftrag_BOMBCARPET(target="GROUP:Convoy", altitude_ft=25000, carpet_length_m=500)
ack = await bridge.add_auftrag(auftrag=auftrag_bombcarpet, legion="LEGION:Wing Parchim")

auftrag_groundescort = Auftrag_GROUNDESCORT(target="GROUP:Convoy", orbit_distance_nm=1.5)
ack = await bridge.add_auftrag(auftrag=auftrag_groundescort, legion="LEGION:Wing Parchim")

auftrag_groundattack = Auftrag_GROUNDATTACK(target="GROUP:Enemy Convoy", speed_kts=25, formation="Vee")
ack = await bridge.add_auftrag(auftrag=auftrag_groundattack, legion="LEGION:Ground Brigade")

auftrag_antiship = Auftrag_ANTISHIP(target="GROUP:Enemy Ships", altitude_ft=2000)
ack = await bridge.add_auftrag(auftrag=auftrag_antiship, legion="LEGION:Wing Parchim")

auftrag_navalengagement = Auftrag_NAVALENGAGEMENT(target="UNIT:Target Ship", speed_kts=18, depth_m=20)
ack = await bridge.add_auftrag(auftrag=auftrag_navalengagement, legion="LEGION:Naval Group")

auftrag_intercept = Auftrag_INTERCEPT(target="GROUP:Bandit-1")
ack = await bridge.add_auftrag(auftrag=auftrag_intercept, legion="LEGION:Wing Parchim")

auftrag_escort = Auftrag_ESCORT(target="GROUP:Package Lead", offset_x=-100, offset_y=0, offset_z=200)
ack = await bridge.add_auftrag(auftrag=auftrag_escort, legion="LEGION:Wing Parchim")

auftrag_rescuehelo = Auftrag_RESCUEHELO(target="UNIT:Carrier-1")
ack = await bridge.add_auftrag(auftrag=auftrag_rescuehelo, legion="LEGION:Rescue Detachment")

troops = GroupSet("GROUP:Infantry-1")
auftrag_trooptransport = Auftrag_TROOPTRANSPORT(transport_groups=troops, dropoff="ZONE:LZ Bravo")
ack = await bridge.add_auftrag(auftrag=auftrag_trooptransport, legion="LEGION:Helo Lift")

auftrag_orbit = Auftrag_ORBIT(target="ZONE:CAP Station", altitude_ft=15000, speed_kts=300)
ack = await bridge.add_auftrag(auftrag=auftrag_orbit, legion="LEGION:Wing Parchim")

auftrag_awacs = Auftrag_AWACS(target="ZONE:AWACS Track", altitude_ft=30000, speed_kts=350)
ack = await bridge.add_auftrag(auftrag=auftrag_awacs, legion="LEGION:Wing Parchim")

auftrag_tanker = Auftrag_TANKER(target="ZONE:Tanker Track", altitude_ft=20000, speed_kts=300, refuel_system=1)
ack = await bridge.add_auftrag(auftrag=auftrag_tanker, legion="LEGION:Wing Parchim")

auftrag_cap = Auftrag_CAP(zone="ZONE:Town Fight", altitude_ft=15000, speed_kts=300, target_types=["Air"])
ack = await bridge.add_auftrag(auftrag=auftrag_cap, legion="LEGION:Wing Parchim")

auftrag_cas = Auftrag_CAS(zone="ZONE:Town Fight", altitude_ft=12000, speed_kts=280)
ack = await bridge.add_auftrag(auftrag=auftrag_cas, legion="LEGION:Wing Parchim")

auftrag_casenhanced = Auftrag_CASENHANCED(zone="ZONE:Town Fight", range_max_nm=25)
ack = await bridge.add_auftrag(auftrag=auftrag_casenhanced, legion="LEGION:Wing Parchim")

auftrag_fac = Auftrag_FAC(zone="ZONE:Town Fight", frequency_mhz=133, modulation=0)
ack = await bridge.add_auftrag(auftrag=auftrag_fac, legion="LEGION:Ground Brigade")

auftrag_patrol = Auftrag_PATROLZONE(zone="ZONE:Patrol Area", speed_kts=20, altitude_ft=2000, formation="Off Road")
ack = await bridge.add_auftrag(auftrag=auftrag_patrol, legion="LEGION:Ground Brigade")

auftrag_recon = Auftrag_RECON(
    zones=ZoneSet("ZONE:Recon Alpha", "ZONE:Recon Bravo"),
    speed_kts=250,
    altitude_ft=12000,
    ad_infinitum=False,
    randomly=True,
)
ack = await bridge.add_auftrag(auftrag=auftrag_recon, commander="COMMANDER:Blue Commander")

# Event-based tactical assessment, separate from MOOSE mission success.
recon_outcome = await bridge.execute_recon(
    auftrag_recon,
    intel="INTEL:Blue Intel",
    commander="COMMANDER:Blue Commander",
    goal=goal,
    objective=objective,
    tactical_picture=tactical_picture,
    operational_plan=plan,
    on_status=print,
)
print(format_recon_outcome(recon_outcome))

auftrag_capture = Auftrag_CAPTUREZONE(opszone="OPSZONE:Town Fight", capture_coalition="blue", speed_kts=20)
ack = await bridge.add_auftrag(auftrag=auftrag_capture, legion="LEGION:Ground Brigade")

auftrag_ammo = Auftrag_AMMOSUPPLY(zone="ZONE:Forward Depot")
ack = await bridge.add_auftrag(auftrag=auftrag_ammo, legion="LEGION:Ground Logistics")

auftrag_fuel = Auftrag_FUELSUPPLY(zone="ZONE:Forward Depot")
ack = await bridge.add_auftrag(auftrag=auftrag_fuel, legion="LEGION:Ground Logistics")

auftrag_rearming = Auftrag_REARMING(zone="ZONE:Forward Depot")
ack = await bridge.add_auftrag(auftrag=auftrag_rearming, legion="LEGION:Ground Logistics")

auftrag_airdefense = Auftrag_AIRDEFENSE(zone="ZONE:Forward SAM")
ack = await bridge.add_auftrag(auftrag=auftrag_airdefense, legion="LEGION:Air Defense")

auftrag_onguard = Auftrag_ONGUARD(target="ZONE:Guard Point")
ack = await bridge.add_auftrag(auftrag=auftrag_onguard, legion="LEGION:Ground Brigade")

auftrag_nothing = Auftrag_NOTHING(zone="ZONE:Relax")
ack = await bridge.add_auftrag(auftrag=auftrag_nothing, legion="LEGION:Ground Brigade")

auftrag_ewr = Auftrag_EWR(zone="ZONE:EWR Site")
ack = await bridge.add_auftrag(auftrag=auftrag_ewr, legion="LEGION:Radar Net")

auftrag_faca = Auftrag_FACA(target="GROUP:Ground-1", designation="LASER", data_link=False)
ack = await bridge.add_auftrag(auftrag=auftrag_faca, legion="LEGION:Wing Parchim")

auftrag_sead = Auftrag_SEAD(target="UNIT:SA-11-1", altitude_ft=25000)
ack = await bridge.add_auftrag(auftrag=auftrag_sead, legion="LEGION:Wing Parchim")

auftrag_strike = Auftrag_STRIKE(target="ZONE:Factory", altitude_ft=2000, engage_weapon_type=1)
ack = await bridge.add_auftrag(auftrag=auftrag_strike, legion="LEGION:Wing Parchim")

auftrag_strafing = Auftrag_STRAFING(target="GROUP:Convoy", altitude_ft=1000, length_m=300)
ack = await bridge.add_auftrag(auftrag=auftrag_strafing, legion="LEGION:Wing Parchim")
```

All AUFTRAG helper objects support `set_time(start=..., stop=...)`,
`set_duration(duration=...)`, `set_required_assets(min_count=..., max_count=...)`,
and `set_weapon_type(weapon_type)`. For `set_time`, use a
string such as `"05:00"` for mission clock time or a number such as `600` for
seconds relative to the time the mission is assigned. `set_duration` sets how
many seconds the mission may run before MOOSE cancels it. `set_required_assets`
sets how many asset groups a LEGION-level Auftrag should request.
`set_weapon_type` forwards a numeric `DcsWeaponFlag` to MOOSE
`AUFTRAG:SetWeaponType()`.

```python
auftrag_bai = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)
auftrag_bai.set_time(start=600, stop="13:00")
auftrag_bai.set_duration(duration=1800)
auftrag_bai.set_required_assets(min_count=2, max_count=4)
auftrag_bai.set_weapon_type(DcsWeaponFlag.ANY_BOMB)
```

`get_auftrag_summary` waits for the MOOSE FSM `OnAfterEvaluated` event sent by
the Lua bridge. It does not poll AUFTRAG snapshots. The optional `on_status`
callback receives lightweight AUFTRAG status events while the final summary is
not available yet, including `Planned`, `Queued`, `Requested`, `Scheduled`,
`Started`, `Executing`, `Done`, and `Cancel` when MOOSE emits them.

Example script for SDK experimentation:

```bash
python examples/sdk/monitor_group_distance.py
```

The script is a pure client example. It assumes the MoosePyBridge daemon/control
server is already running and DCS is already connected to that daemon. Change
the group ids and timing options directly at the top of the script.

## Protocol example

Python command:

```json
{"version":1,"type":"command","id":"cmd-...","source":"python","mode":"execute","action":"message.to_coalition","params":{"coalition":"blue","text":"MoosePyBridge connected","duration":10}}
```

DCS ACK:

```json
{"version":1,"type":"ack","id":"ack-...","source":"dcs","correlation_id":"cmd-...","mission_time":3138.265,"dcs_time":46338.265,"mission_date":"2026/07/15","wall_time":"2026-07-15T10:00:00Z","ok":true,"result":{"message":"Message sent to coalition","coalition":"blue"}}
```

Every DCS message reports three clocks: `mission_time` from `timer.getTime()`,
`dcs_time` from `timer.getAbsTime()`, and UTC `wall_time`. Values of
`dcs_time` above 86400 retain their day offset. `mission_date` is read once
from `UTILS.GetDCSMissionDate()`, and the SDK derives the current DCS date from
it and the day offset. The SDK exposes these values as
`DcsTime` through `await bridge.get_time()` and stores the latest value in
`bridge.state.clock`.

## Design constraints

- DCS is the authoritative source of simulation state.
- MOOSE is the authoritative semantic layer for mission objects and OPS logic.
- Python consumes stable bridge objects, not raw MOOSE internals.
- Commands should remain whitelisted and MOOSE/OPS-semantic.
- Tactical agents should use the same validated command path as human tools.
- Multiplayer and dedicated-server use must stay first-class design targets.
- Autonomous behavior should be introduced through explicit modes, policies, and
  auditability rather than a separate uncontrolled command path.
