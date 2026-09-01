-- Exercise the real bridge drawing/marker helpers against mocked DCS calls.
MOOSE_BRIDGE_JSON = {}
unpack = unpack or table.unpack
dofile(assert(arg[1], "base bridge path required"))
dofile(assert(arg[2], "event extension path required"))
env = {mission={theatre="Caucasus"}}
coalition = {side={BLUE=2, RED=1, NEUTRAL=0}}
local serial, marks, removed = 100, {}, {}
UTILS = {GetMarkID=function() serial = serial + 1 return serial end}
coord = {LLtoLO=function(lat, lon, alt) return {x=lat * 1000, z=lon * 1000, y=alt} end}
local fail_line, fail_label = false, false
trigger = {action={
  markToAll=function() error("must not create a public marker") end,
  circleToAll=function(side, id, point, radius, color, fill, line, readonly)
    assert(side == 2 and radius == 100 and readonly)
    marks[id] = {kind="circle", point=point}
  end,
  lineToAll=function(side, id, origin, destination, color, line, readonly)
    assert(side == 2 and readonly)
    if fail_line then error("DCS line unavailable") end
    marks[id] = {kind="line", origin=origin, destination=destination}
  end,
  markToCoalition=function(id, text, point, side, readonly)
    assert(side == 2 and readonly)
    if fail_label then error("DCS label unavailable") end
    marks[id] = {kind="label", text=text, point=point}
  end,
  removeMark=function(id) removed[#removed + 1] = id marks[id] = nil end,
}}
local unit = {getPosition=function() return {p={x=100, y=2000, z=300}} end}
local entry = {navaid_overlay_id="navaid-test", group={GetCoalition=function() return 2 end},
  navaid_selection={id="1", unit_id="UNIT:Hornet", theater_id="Caucasus"}}
local bridge = setmetatable({DebugOverlays={}}, {__index=MOOSE_BRIDGE})
bridge._NavigationMenuEntry = function() return entry end -- Guards have a separate lifecycle harness.
bridge._FlightStatusReferenceUnit = function() return "Hornet", unit end
local function show(line)
  return bridge:_UpdateNavaidOverlay({show=true, bearing_line=line, selection_id="1",
    unit_id="UNIT:Hornet", theater_id="Caucasus", point={latitude=41, longitude=42, altitude=0},
    text="BTM | Batumi\nTACAN | Source data\nChannel: 16X"})
end
marks[50] = {kind="unrelated-route"}
bridge.DebugOverlays.route = {50}
local result = show(true)
assert(result.shown and result.coalition == "blue" and result.bearing_line)
local ids = bridge.DebugOverlays[entry.navaid_overlay_id]
assert(#ids == 3 and marks[ids[1]].kind == "circle" and marks[ids[3]].kind == "label")
assert(marks[ids[2]].origin.x == 100 and marks[ids[2]].origin.y == 2000)
assert(marks[ids[2]].destination.x == 41000 and marks[ids[3]].point.z == 42000)
show(false)
for _, id in ipairs(ids) do assert(not marks[id], "replacement removes every old mark") end
assert(#bridge.DebugOverlays[entry.navaid_overlay_id] == 2 and marks[50])
bridge:_UpdateNavaidOverlay({show=false})
assert(not bridge.DebugOverlays[entry.navaid_overlay_id] and marks[50])
assert(bridge:_UpdateNavaidOverlay({show=false}).removed == 0)
for _, failure in ipairs({"line", "label"}) do
  fail_line, fail_label = failure == "line", failure == "label"
  assert(not pcall(show, true))
  assert(not bridge.DebugOverlays[entry.navaid_overlay_id])
  for id in pairs(marks) do assert(id == 50, "partial drawing must not leak marks") end
end
fail_line, fail_label = false, false
show(true)
bridge:_ClearDebugOverlay(entry.navaid_overlay_id)
assert(marks[50] and #bridge.DebugOverlays.route == 1)
print("NAVAID OVERLAY LUA TEST PASSED")
