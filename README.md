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
- command families including:
  - `message.*`
  - `mark.*`
  - `smoke.*`
  - `snapshot.*`
  - selected `auftrag.*` execution and trace commands
- advisory helpers for validating AUFTRAG requests and finding suitable
  LEGION/COHORT candidates

## Architecture

The DCS-facing bridge accepts one authoritative Lua connection from the mission.
Python tools should not each try to bind or own that DCS connection. Instead, a
single daemon can expose a local control port for multiple clients.

Default ports:

- DCS/MOOSE Lua bridge: `51000`
- local Python control API: `51001`

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
2. `lua/MooseBridgeJson.lua`
3. `lua/MooseBridge.lua`
4. optional extension files, for example:
   - `lua/MooseBridgeSocketTuningExtension.lua`
   - `lua/MooseBridgePayloadExtension.lua`
   - `lua/MooseBridgeAuftragExecutionExtension.lua`
   - `lua/MooseBridgeAuftragTraceExtension.lua`
5. mission-specific setup such as `lua/MooseBridgeMissionExample.lua`

The minimal example contains:

```lua
Bridge = MOOSE_BRIDGE:New("127.0.0.1", 51000)
Bridge:Start()
```

## Python setup

From the project root:

```bash
pip install -e .
python -m moosebridge --host 127.0.0.1 --port 51000 --log moosebridge_raw.jsonl
```

On Windows, the included helper scripts set `PYTHONPATH` for local development:

```powershell
.\run_server.ps1
.\run_interactive.ps1
```

The default console script starts the daemon with the local control API enabled:

```bash
moosebridge-server --host 127.0.0.1 --port 51000 --log moosebridge_raw.jsonl
```

Additional installed entry points:

- `moosebridge-daemon`: explicit daemon entry point
- `moosebridge-control`: local control client
- `moosebridge-standalone-server`: DCS-facing server without the local control API

## First manual test

1. Start the Python bridge daemon.
2. Start the DCS mission with the Lua bridge loaded.
3. Confirm that Python logs the DCS connection and heartbeat.
4. Use the interactive console or a Python client to request snapshots or send a
   simple message command.

Example:

```python
ack = await server.message_to_coalition(
    coalition="blue",
    text="MoosePyBridge connected",
    duration=10,
)
```

## Protocol example

Python command:

```json
{"version":1,"type":"command","id":"cmd-...","source":"python","mode":"execute","action":"message.to_coalition","params":{"coalition":"blue","text":"MoosePyBridge connected","duration":10}}
```

DCS ACK:

```json
{"version":1,"type":"ack","id":"ack-...","source":"dcs","correlation_id":"cmd-...","ok":true,"result":{"message":"Message sent to coalition","coalition":"blue"}}
```

## Design constraints

- DCS is the authoritative source of simulation state.
- MOOSE is the authoritative semantic layer for mission objects and OPS logic.
- Python consumes stable bridge objects, not raw MOOSE internals.
- Commands should remain whitelisted and MOOSE/OPS-semantic.
- Tactical agents should use the same validated command path as human tools.
- Multiplayer and dedicated-server use must stay first-class design targets.
- Autonomous behavior should be introduced through explicit modes, policies, and
  auditability rather than a separate uncontrolled command path.
