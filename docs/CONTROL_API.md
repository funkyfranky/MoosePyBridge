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
  `get_auftrag_summary`, `wait_for_auftrag_outcome`

For code that should read closer to the MOOSE AUFTRAG API, use the lightweight
Python AUFTRAG descriptions and let the SDK convert them to bridge commands:

```python
from moosebridge import Auftrag_ARTY, Auftrag_BAI

auftrag_bai = Auftrag_BAI(target="UNIT:Ground-1-1", altitude_ft=15000)
ack = await bridge.add_auftrag(auftrag=auftrag_bai, legion="LEGION:Wing Parchim")
summary = await bridge.get_auftrag_summary(auftrag_bai)
if summary.success is True:
    print("BAI succeeded")

auftrag_arty = Auftrag_ARTY(target="UNIT:Ground-1-1", nshots=6)
ack = await bridge.add_auftrag(auftrag=auftrag_arty, opsgroup="OPSGROUP:Group-1")
```

`get_auftrag_summary` and `wait_for_auftrag_outcome` wait for the Lua bridge's
`auftrag.evaluated` event, which is emitted from MOOSE's `OnAfterEvaluated`
FSM hook. They do not poll AUFTRAG snapshots.

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
