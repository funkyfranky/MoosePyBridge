--- Minimal mission-side example.
-- Load this after Moose.lua, MooseBridgeJson.lua, MooseBridge.lua and optional extensions such as MooseBridgeOps.lua.

Bridge = MOOSE_BRIDGE:New("127.0.0.1", 51000)
Bridge:Start()
