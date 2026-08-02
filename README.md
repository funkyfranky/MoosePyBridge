# MoosePyBridge

MoosePyBridge is a semantic Python control plane for Digital Combat Simulator
(DCS) missions that use the MOOSE framework.

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
  - `object.coords`
  - `object.distance`
  - `zone.draw`
  - `snapshot.*`
  - selected `auftrag.*` execution and trace commands
- advisory helpers for validating AUFTRAG requests and finding suitable
  LEGION/COHORT candidates
- SDK helpers for coordinate lookup, distance measurement, zone drawing,
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

The SDK registry synchronizes automatically after relevant bridge snapshots
and events. `bridge.sync_strategic_objectives()` is available for explicit
tests. A control change produces a normalized `objective.control_changed`
event. `capture_actions(event, objective)` identifies components that require
explicit handling; it does not respawn or destroy DCS objects by itself.

## Python setup

From the project root:

```bash
pip install -e .
python -m moosebridge --host 127.0.0.1 --port 42000 --control-port 42001 --log moosebridge_raw.jsonl
```

On Windows, the included helper scripts set `PYTHONPATH` for local development:

```powershell
.\run_server.ps1
.\run_interactive.ps1
```

The default console script starts the daemon with the local control API enabled:

```bash
moosebridge-server --host 127.0.0.1 --port 42000 --control-port 42001 --log moosebridge_raw.jsonl
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

control = MooseBridgeControlClient("127.0.0.1", 42001)
bridge = sdk_from_control_client(control, timeout=10.0)

await bridge.snapshot_kind("units")
nearest = await bridge.nearest("units", "ZONE:Town Fight", coalition="red", alive=True)
```

Typed OPS state convenience helpers:

```python
from moosebridge import format_legion_status

await bridge.refresh_legion_state()

legion = bridge.legion("LEGION:Wing Parchim")
cohorts = bridge.cohorts_of_legion("LEGION:Wing Parchim")
missions = bridge.missions_of_legion("LEGION:Wing Parchim")
ready = bridge.ready_cohorts_of_legion("LEGION:Wing Parchim", mission_type="BAI")

print(format_legion_status(bridge, "LEGION:Wing Parchim"))
```

Situation pictures and GeoJSON export:

```python
tactical = await bridge.refresh_tactical_picture("blue", "INTEL:BlueIntel")
tactical_geojson = tactical.to_geojson()

await bridge.add_intel_agent("INTEL:BlueIntel", "GROUP:Blue EWR")

clock = await bridge.get_time()
print(clock.mission_time, clock.dcs_date, clock.time_of_day, clock.wall_time)

global_picture = await bridge.refresh_global_picture()
global_geojson = global_picture.to_geojson()
print(format_global_picture_status(global_picture))
```

`TacticalPicture` uses INTEL contacts and clusters for enemy knowledge.
`GlobalPicture` uses global truth snapshots and is intended for admin/debug
views or neutral analysis tools.
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

Movement history is derived from periodic DCS positions because DCS does not
emit position-change events. Tracks are removed when an object dies or
disappears and are reset when mission time restarts.

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
from moosebridge import Auftrag_AIRDEFENSE, Auftrag_AMMOSUPPLY, Auftrag_ANTISHIP, Auftrag_ARTY, Auftrag_AWACS, Auftrag_BAI, Auftrag_BOMBCARPET, Auftrag_BOMBRUNWAY, Auftrag_CAP, Auftrag_CAPTUREZONE, Auftrag_CAS, Auftrag_CASENHANCED, Auftrag_ESCORT, Auftrag_EWR, Auftrag_FAC, Auftrag_FACA, Auftrag_FUELSUPPLY, Auftrag_GROUNDATTACK, Auftrag_GROUNDESCORT, Auftrag_INTERCEPT, Auftrag_NAVALENGAGEMENT, Auftrag_NOTHING, Auftrag_ONGUARD, Auftrag_ORBIT, Auftrag_PATROLZONE, Auftrag_REARMING, Auftrag_RESCUEHELO, Auftrag_SEAD, Auftrag_STRAFING, Auftrag_STRIKE, Auftrag_TANKER, Auftrag_TROOPTRANSPORT, GroupSet

auftrag_bai = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)
ack = await bridge.add_auftrag(auftrag=auftrag_bai, legion="LEGION:Wing Parchim")

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
`set_duration(duration=...)`, and
`set_required_assets(min_count=..., max_count=...)`. For `set_time`, use a
string such as `"05:00"` for mission clock time or a number such as `600` for
seconds relative to the time the mission is assigned. `set_duration` sets how
many seconds the mission may run before MOOSE cancels it. `set_required_assets`
sets how many asset groups a LEGION-level Auftrag should request.

```python
auftrag_bai = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)
auftrag_bai.set_time(start=600, stop="13:00")
auftrag_bai.set_duration(duration=1800)
auftrag_bai.set_required_assets(min_count=2, max_count=4)
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
