--- Minimal mission-side example.
-- Load this after the JSON helper and main bridge script.

-- Optional during development: avoid long DCS main-thread stalls while Python is
-- not listening yet.
dofile(lfs.writedir() .. "Scripts/MooseBridgeSocketTuningExtension.lua")

Bridge = MOOSE_BRIDGE:New("127.0.0.1", 51000)
Bridge:Start()
