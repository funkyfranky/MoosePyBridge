# MOOSE Bridge V1 Prototype

This is a minimal TCP JSONL bridge between DCS/MOOSE Lua 5.1 and Python.

## Scope

Implemented in this prototype:

- TCP JSONL transport
- Lua-side `MOOSE_BRIDGE` class
- Python `asyncio` bridge server
- Heartbeat from DCS to Python
- Command from Python to DCS
- ACK from DCS to Python
- Raw JSONL logging on Python side
- Initial MOOSE commands:
  - `message.to_all`
  - `message.to_coalition`

## Load order in DCS

Load the files in this order:

1. `Moose.lua`
2. `lua/MooseBridgeJson.lua`
3. `lua/MooseBridge.lua`
4. `lua/MooseBridgeMissionExample.lua`

The example contains:

```lua
Bridge = MOOSE_BRIDGE:New("127.0.0.1", 50100)
Bridge:Start()
```

## Python setup

From the project root:

```bash
pip install -e .
moosebridge-server --host 127.0.0.1 --port 50100 --log moosebridge_raw.jsonl
```

Alternatively:

```bash
python -m moosebridge --host 127.0.0.1 --port 50100
```

## First manual test

1. Start the Python bridge server.
2. Start the DCS mission with the Lua bridge loaded.
3. Confirm that the Python server logs the DCS connection and heartbeat.
4. Use the Python API from an embedded tool or script:

```python
ack = await server.message_to_coalition(
    coalition="blue",
    text="MOOSE Bridge connected",
    duration=10,
)
```

## Protocol example

Python command:

```json
{"version":1,"type":"command","id":"cmd-...","source":"python","mode":"execute","action":"message.to_coalition","params":{"coalition":"blue","text":"MOOSE Bridge connected","duration":10}}
```

DCS ACK:

```json
{"version":1,"type":"ack","id":"ack-...","source":"dcs","correlation_id":"cmd-...","ok":true,"result":{"message":"Message sent to coalition","coalition":"blue"}}
```

## Notes

- This prototype assumes a de-sanitized DCS mission scripting environment with `require("socket")` available.
- DCS/MOOSE remains the authoritative source.
- Python holds a state mirror and coordinates future clients.
- The Lua side intentionally executes only whitelisted semantic commands, not arbitrary Lua strings.
