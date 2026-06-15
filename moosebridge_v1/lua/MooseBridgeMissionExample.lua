--- Minimal mission-side example.
-- Load this after Moose.lua, MooseBridgeJson.lua and MooseBridge.lua.

Bridge = MOOSE_BRIDGE:New("127.0.0.1", 50100)
Bridge:Start()
