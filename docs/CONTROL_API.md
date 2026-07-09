# MoosePyBridge Control API

The control API is a local JSONL protocol for Python tools that need to talk to a
running MoosePyBridge daemon.

DCS connects to the daemon on the DCS-facing bridge port, normally `51000`.
Operator tools, scripts, and future agents connect to the control port, normally
`51001`. This keeps one authoritative DCS/MOOSE connection while allowing
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
  "actions": ["snapshot.groups", "snapshot.units", "snapshot.cohorts"]
}
```

The server forwards each action as a DCS bridge command with empty params.

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

client = MooseBridgeControlClient("127.0.0.1", 51001)
status = await client.status()
state = await client.get_state(kinds=("groups", "cohorts", "legions"))
ack = await client.send_dcs_command("message.to_all", {"text": "hello"})
```

The client maintains a local `MooseBridgeState` mirror and updates it whenever a
response contains a `state` payload.

For application code, prefer adapting the control client into the high-level
SDK. This keeps daemon-backed tools on the same validated command path as the
interactive client and server-backed SDK users:

```python
from moosebridge.control import MooseBridgeControlClient
from moosebridge.control_sdk import sdk_from_control_client

control = MooseBridgeControlClient("127.0.0.1", 51001)
bridge = sdk_from_control_client(control, timeout=10.0)

status = await control.status()
await bridge.snapshot_kind("units")

coords = await bridge.coords("ZONE:Town Fight", format="mgrs")
distance = await bridge.distance("GROUP:Aerial-1", "ZONE:Town Fight")
nearest = await bridge.nearest("units", "ZONE:Town Fight", coalition="red", alive=True, limit=5)
trace = await bridge.trace_auftrag("AUFTRAG:1")
```

The SDK currently exposes helpers for:

- snapshots: `snapshot_kind`, `snapshot_all`, `request_snapshots`
- tactical annotations: `mark_object`, `smoke_object`, `draw_zone`
- object utilities: `coords`, `distance`, `nearest`
- messages: `message_all`, `message_coalition`
- AUFTRAG: `add_auftrag`, `apply_auftrag`, `apply_recommended_auftrag`, `trace_auftrag`,
  `get_auftrag_summary`, `wait_for_auftrag_outcome`, `pause_mission`,
  `resume_mission`, `cancel_mission`, `assign_mission`
- typed OPS state: `legion`, `cohort`, `cohorts_of_legion`,
  `missions_of_legion`, `missions_of_group`, `ready_cohorts_of_legion`,
  `available_missions_of_cohort`, `refresh_legion_state`, `refresh_ops_state`
- diagnostics: `format_legion_status`, `format_cohort_assets`,
  `format_mission_summary`

Typed OPS state can be read from the SDK state mirror after requesting the
relevant snapshots:

```python
from moosebridge import format_legion_status

await bridge.refresh_legion_state()

legion = bridge.legion("LEGION:Wing Parchim")
cohorts = bridge.cohorts_of_legion("LEGION:Wing Parchim")
missions = bridge.missions_of_legion("LEGION:Wing Parchim")
ready = bridge.ready_cohorts_of_legion("LEGION:Wing Parchim", mission_type="BAI")

print(format_legion_status(bridge, "LEGION:Wing Parchim"))
```

For code that should read closer to the MOOSE AUFTRAG API, use the lightweight
Python AUFTRAG descriptions and let the SDK convert them to bridge commands:

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
- No audit log schema yet.
- Request timeout is currently also used as the DCS command timeout.
- Autonomous agents should still use higher-level validation and policy checks
  before calling `control.command`.
