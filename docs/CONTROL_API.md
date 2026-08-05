# MoosePyBridge Control API

The control API is a local JSONL protocol for Python tools that need to talk to a
running MoosePyBridge daemon.

DCS connects to the daemon on the DCS-facing bridge port, normally `42000`.
Operator tools, scripts, and future agents connect to the control port, normally
`42001`. This keeps one authoritative DCS/MOOSE connection while allowing
multiple clients to inspect state or request semantic commands.

## Transport

- TCP
- UTF-8
- one JSON object per line
- one response per request

Each client request opens a connection, sends one JSON line, reads one response
line, and closes the connection. Long-lived client sessions can be added later,
but the current protocol is intentionally simple.

## Request Shape

```json
{
  "id": "ctrl-optional-correlation-id",
  "action": "control.status",
  "params": {},
  "timeout": 10.0
}
```

Fields:

- `id`: optional request id. If omitted, the server creates one.
- `action`: required control action or DCS bridge action.
- `params`: optional object; defaults to `{}`.
- `timeout`: optional DCS command timeout in seconds.

## Response Shape

Successful response:

```json
{
  "id": "ctrl-optional-correlation-id",
  "ok": true,
  "result": {}
}
```

Error response:

```json
{
  "id": "ctrl-optional-correlation-id",
  "ok": false,
  "error": "human-readable error"
}
```

Errors are transport-level or control-level failures. DCS command rejection is
usually represented as a successful control response containing an ACK with
`ok=false`.

## Mission Session Boundary

Lua forwards DCS `S_EVENT_MISSION_END` as `mission.ended`. This event clears the
daemon's mission-scoped state and wakes outstanding event waits, including waits
for a different event type. SDK clients treat it as terminal for current
operations and clear their local information requirements, objectives, goals,
plans, execution histories, and AUFTRAG mappings. Audit records remain
persistent and are not part of the live mission session. State and status
responses expose a monotonic `mission_generation`; control-backed SDK clients
use it to detect a completed mission even when they were idle as the event was
emitted.

## Control Actions

### `control.status`

Returns daemon connectivity and object counts. It does not include full object
payload lists.

Example result:

```json
{
  "connected": true,
  "last_heartbeat": {},
  "counts": {
    "groups": 4,
    "units": 18,
    "objects": 0,
    "opsgroups": 2,
    "auftraege": 1,
    "cohorts": 3,
    "legions": 1
  }
}
```

### `control.state`

Returns raw mirrored state payloads.

Parameters:

```json
{
  "kinds": ["groups", "units", "zones"]
}
```

If `kinds` is omitted, all known state kinds are returned.

Known state kinds:

- `groups`
- `units`
- `ammunition`
- `statics`
- `airbases`
- `zones`
- `objects`
- `opszones`
- `opsgroups`
- `auftraege`
- `cohorts`
- `legions`

### `control.snapshots`

Requests one or more DCS/MOOSE snapshots through the daemon, then returns ACKs
and the updated mirrored state.

Parameters:

```json
{
  "actions": ["snapshot.groups", "snapshot.units", "snapshot.ammunition", "snapshot.cohorts"]
}
```

The server forwards each action as a DCS bridge command with empty params.
`snapshot.ammunition` is an explicit dynamic snapshot for active, living
ground units and is not part of `snapshot.all`. The Python state enriches each
weapon entry with `initial_count` and `fraction`, using the first observed
count as its per-mission baseline while preserving entries whose current
`count` is zero.

### `control.command`

Forwards a semantic DCS bridge command through the daemon.

Parameters:

```json
{
  "action": "message.to_all",
  "params": {
    "text": "MoosePyBridge connected",
    "duration": 10
  }
}
```

Example result:

```json
{
  "ack": {
    "type": "ack",
    "ok": true,
    "result": {}
  },
  "state": {}
}
```

### Direct DCS Actions

Any action that is not a `control.*` action is forwarded directly to DCS/MOOSE
as a bridge command.

For example, this request:

```json
{
  "action": "snapshot.groups",
  "params": {}
}
```

is equivalent to `control.command` with `params.action = "snapshot.groups"`.

## Client Helper

Python code can use `MooseBridgeControlClient` directly for low-level control
requests:

```python
from moosebridge.control import MooseBridgeControlClient

client = MooseBridgeControlClient(
    "127.0.0.1",
    42001,
    client_id="diagnostics-1",
    display_name="Diagnostics",
)
status = await client.status()
state = await client.get_state(kinds=("groups", "cohorts", "legions"))
ack = await client.send_dcs_command("message.to_all", {"text": "hello"})
```

The client maintains a local `MooseBridgeState` mirror and updates it whenever a
response contains a `state` payload. Every request also carries the same
declared `client_id` and `display_name` for the lifetime of that client object.
These fields are attribution metadata, not authentication credentials.

For application code, prefer adapting the control client into the high-level
SDK. This keeps daemon-backed tools on the same validated command path as the
interactive client and server-backed SDK users:

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

status = await control.status()
await bridge.snapshot_kind("units")

coords = await bridge.coords("ZONE:Town Fight", format="mgrs")
points = await bridge.convert_points([(1000, 2000), (3000, 4000)])
distance = await bridge.distance("GROUP:Aerial-1", "ZONE:Town Fight")
nearest = await bridge.nearest("units", "ZONE:Town Fight", coalition="red", alive=True, limit=5)
trace = await bridge.trace_auftrag("AUFTRAG:1")
```

Passive MOOSE territories are mirrored as typed SDK objects. Their geometry is
authored in the DCS Mission Editor and is not periodically scanned:

```python
await bridge.refresh_territory_state()

territory = bridge.territory("TERRITORY:Territory North")
blue_territories = bridge.territories(coalition="blue")

await bridge.set_territory_coalition(
    "TERRITORY:Territory North",
    "red",
)
```

`set_territory_coalition()` changes the declared owner in MOOSE. The
`territory.coalition_changed` event immediately updates the daemon and SDK
state mirrors; no polling loop is required for this change.

The SDK currently exposes helpers for:

- snapshots: `snapshot_kind`, `snapshot_all`, `request_snapshots`
- tactical effects and annotations: `mark_object`, `smoke_object`,
  `explode_object`, `explode_point`, `draw_zone`
- object utilities: `coords`, `convert_points`, `distance`, `nearest`
- messages: `message_all`, `message_coalition`
- AUFTRAG: `add_auftrag`, `apply_auftrag`, `apply_recommended_auftrag`, `trace_auftrag`,
  `get_auftrag_summary`, `wait_for_auftrag_outcome`, `pause_mission`,
  `resume_mission`, `cancel_mission`, `assign_mission`
- operational execution: `execute_plan`, `execute_operational_plan`,
  `prepare_plan_retry`, `operational_plan_execution`,
  `operational_plan_executions`, `refresh_operational_plan_executions`,
  `restore_operational_plan`, `reconcile_operational_plan`,
  `monitor_interrupted_operational_plan`, `block_interrupted_operational_plan`,
  `abort_operational_plan`

`execute_plan` refreshes and revalidates only the next immediate phase before
submitting its AUFTRAGs. Progress callbacks receive `phase.revalidating` and
`phase.revalidated`; a failed phase-boundary check produces `plan.blocked`
without creating a mission for that phase.

`approve_operational_plan(plan, approved_by=..., reason=...)` records explicit
operator attribution in the plan snapshot. A control-backed SDK uses its
declared display name automatically and stores the stable client id separately;
the caller may still override the display name. Executed plan missions expose
`command_ack`, a compact persisted reference with `ack_id`, `correlation_id`,
`sequence`, and relevant scalar ACK result fields. The execution formatter
shows both approval attribution and ACK references.

`OperationalPlan.provenance` optionally records where a proposal originated.
`OperationalPlanProvenance` contains a typed `source_type`, stable `source_id`,
optional tactical-picture mission time, and rationale. This is intentionally
separate from the client that later approves or executes the proposal.

`propose_capture_plan(goal, tactical_picture, ...)` returns an unregistered
rule-based draft for an OPSZONE CAPTURE goal. The initial conservative planner
selects at most one coalition-visible nearby ground defender for BAI isolation,
then proposes CAPTUREZONE seizure and optional AIRDEFENSE/AMMOSUPPLY
consolidation. Call `add_operational_plan`, validation, and approval explicitly.
The draft carries structured `proposal_issues` when INTEL coverage is unknown,
not running, has no living agents, or exposes no nearby defender. These warnings
are audit-persistent and informational; they are not feasibility errors.
Contact freshness is derived from MOOSE `Tdetected`. `TacticalPicture` exposes
`contact_assessments()` and `lost_contact_assessments()` with typed information
states, age, and confidence. `LostContact` events retain the last-known contact
in coalition-private memory. Important recent losses near a capture objective
produce a structured `reconnaissance_required` proposal issue and metadata;
the rule-based planner adds an executable RECON phase. `Auftrag_RECON` accepts a
`ZoneSet`, speed, altitude, route repetition/randomization, and formation.
INTEL agent membership is mission-independent. Registering an INTEL enables
MOOSE `INTEL:SetAgentAuto()`, which periodically maintains all living groups
of that coalition in the detection set. Successful route completion means the
recon asset survived; it does not assert that enemies were found or that the area is clear.
Execution therefore stops at a `plan.replanning_required` boundary after INTEL
has been refreshed.

`MooseBridgeClient.execute_recon()` captures a daemon event cursor before
submission and returns a typed `ReconOutcome` after MOOSE evaluation. It
correlates `intel.new_contact` and `intel.lost_contact` events with the DCS
groups assigned to that AUFTRAG. MOOSE success remains authoritative in
`outcome.mission_outcome`; contact gain, reacquisition, final losses, threat
totals, relevant unknown targets, and timing are separate tactical observations.
The control API exposes `control.event.cursor` and `control.events.query` for
the same chronological event-history mechanism.

`derive_recon_requirement(goal, objective, tactical_picture, plan=...)` uses
objective components, goal metadata, operational phase targets, and current or
recently lost coalition-private INTEL contacts near the objective. Every
`ReconRelevantTarget` retains its sources and information quality. Manual IDs
augment automatic targets; `derive_targets=False`, or the concise
`ReconRequirement.manual(area_id, *target_ids)` factory, creates a strictly
manual requirement for deterministic tests. Passing goal, objective, and
tactical picture directly to `execute_recon()` performs the derivation by
default. A target-based result is intentionally reported as unknown when no
relevant targets exist; proving complete spatial coverage is a separate future
capability.

The operational executor records this assessment on
`PlanMissionExecution.recon_outcome` and persists it with the execution audit.
It emits `recon.assessed` with status `satisfied`, `incomplete`, or
`indeterminate`. Every structured RECON phase still ends at
`plan.replanning_required`: satisfying the old information requirement does
not authorize later phases from a stale plan. The replanning reason now states
whether relevant targets remain unknown/lost or whether target coverage cannot
yet be determined.

Automatic requirements also define spatial search quality. The default
thresholds are 80% potentially searched objective area and 100% weighted
coverage of known objective components. Components are `ReconCoveragePoint`s,
not enemy contacts: airfields, static infrastructure, roads, cities, and other
stationary map features are assumed known. Additional known points can be
listed in `goal.metadata["recon_coverage_point_ids"]`; objective-component
weights determine their relative contribution.

While a structured RECON AUFTRAG is active, the executor samples only its
MOOSE-assigned DCS groups every 10 seconds because DCS has no movement event.
It buffers the actual route with the largest applicable surface-sensor bound
from `SensorRangeRegistry`, intersects that optimistic footprint with the
circle or polygon zone, and stores `ReconSpatialCoverage`. The reported area
means `potential_sensor_access_not_confirmed_detection`: coverage can show
where detection was possible and where it was impossible, but never proves an
apparently empty area is free of opponents. Unknown sensor ranges make spatial
completion indeterminate rather than silently assuming a fallback range.
- typed OPS state: `commander`, `commanders`, `commander_for_coalition`,
  `legions_of_commander`, `missions_of_commander`, `legion`, `cohort`, `cohorts_of_legion`,
  `missions_of_legion`, `missions_of_group`, `ready_cohorts_of_legion`,
  `available_missions_of_cohort`, `refresh_legion_state`, `refresh_ops_state`
- typed territory state: `territory`, `territories`,
  `refresh_territory_state`, `set_territory_coalition`
- diagnostics: `format_commander_status`, `format_legion_status`, `format_cohort_assets`,
  `format_mission_summary`, `format_operational_plan_execution`,
  `format_operational_plan_reconciliation`, `format_operational_plan_abort`

Typed OPS state can be read from the SDK state mirror after requesting the
relevant snapshots:

```python
from moosebridge import format_commander_status, format_legion_status

await bridge.refresh_legion_state()

legion = bridge.legion("LEGION:Wing Parchim")
commander = bridge.commander("COMMANDER:Blue Command")
cohorts = bridge.cohorts_of_legion("LEGION:Wing Parchim")
missions = bridge.missions_of_legion("LEGION:Wing Parchim")
ready = bridge.ready_cohorts_of_legion("LEGION:Wing Parchim", mission_type="BAI")

print(format_legion_status(bridge, "LEGION:Wing Parchim"))
print(format_commander_status(bridge, "COMMANDER:Blue Command"))
```

Weapon-specific COHORT ranges can be configured without mission-side Lua:

```python
from moosebridge import DcsWeaponFlag

await bridge.set_cohort_weapon_range(
    "COHORT:Paladin Laage",
    DcsWeaponFlag.CONVENTIONAL_SHELL,
    minimum_m=30,
    maximum_m=22_000,
)
```

The operational ARTY resolver performs this call automatically only when the
current MOOSE `weaponData` entry is missing or differs from its selected
versioned Python range profile.

For code that should read closer to the MOOSE AUFTRAG API, use the lightweight
Python AUFTRAG descriptions and let the SDK convert them to bridge commands:

```python
from moosebridge import Auftrag_AIRDEFENSE, Auftrag_AMMOSUPPLY, Auftrag_ANTISHIP, Auftrag_ARTY, Auftrag_AWACS, Auftrag_BAI, Auftrag_BOMBCARPET, Auftrag_BOMBRUNWAY, Auftrag_CAP, Auftrag_CAPTUREZONE, Auftrag_CAS, Auftrag_CASENHANCED, Auftrag_ESCORT, Auftrag_EWR, Auftrag_FAC, Auftrag_FACA, Auftrag_FUELSUPPLY, Auftrag_GROUNDATTACK, Auftrag_GROUNDESCORT, Auftrag_INTERCEPT, Auftrag_NAVALENGAGEMENT, Auftrag_NOTHING, Auftrag_ONGUARD, Auftrag_ORBIT, Auftrag_PATROLZONE, Auftrag_REARMING, Auftrag_RESCUEHELO, Auftrag_SEAD, Auftrag_STRAFING, Auftrag_STRIKE, Auftrag_TANKER, Auftrag_TROOPTRANSPORT, GroupSet

auftrag_bai = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)
ack = await bridge.add_auftrag(auftrag=auftrag_bai, commander="COMMANDER:Blue Command")
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

`get_auftrag_summary` and `wait_for_auftrag_outcome` wait for the Lua bridge's
`auftrag.evaluated` event, which is emitted from MOOSE's `OnAfterEvaluated`
FSM hook. They do not poll AUFTRAG snapshots. The optional `on_status` callback
receives lightweight AUFTRAG status events, including `Planned`, `Queued`,
`Requested`, `Scheduled`, `Started`, `Executing`, `Done`, and `Cancel` when
MOOSE emits them.

## Interactive Shell

The interactive control client is an operator-friendly wrapper around the same
control API and SDK path:

```powershell
.\run_control_interactive.ps1
```

Representative commands:

```text
status
snapshots --list groups units zones
snapshots --list units --coalition red --alive --limit 20
coords "ZONE:Town Fight" --format mgrs
distance GROUP:Aerial-1 "ZONE:Town Fight"
nearest units "ZONE:Town Fight" --coalition red --alive --limit 5
drawzone "ZONE:Town Fight" --coalition blue --color red --line-type dashed
message blue Push now
trace AUFTRAG:1
```

## Current Limits

- No authentication or roles yet.
- No persistent client sessions yet.
- The daemon has a versioned append-only semantic audit store for operational
  plan execution. Broader command, recommendation, and operator-session audit
  records still need schemas.
- Request timeout is currently also used as the DCS command timeout.
- Autonomous agents should still use higher-level validation and policy checks
  before calling `control.command`.
