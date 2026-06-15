--- Minimal mission-side example.
-- Load this after the JSON helper and main bridge script.

Bridge = MOOSE_BRIDGE:New("127.0.0.1", 51000)
Bridge:Start()
