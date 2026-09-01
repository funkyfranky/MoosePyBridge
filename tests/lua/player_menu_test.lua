-- Run with Lua 5.1+; DCS/MOOSE boundaries are deliberately mocked.
local source = assert(arg[1], "extension path required")
local events, messages, logs, scheduled = {}, {}, {}, {}
local created = 0
timer = {getTime=function() return 100 end}
env = {mission={theatre="Caucasus"}}
MOOSE_BRIDGE = {
  RegisterDefaultCommands=function() end,
  RegisterCommand=function(self, name, handler)
    self.commands = self.commands or {}
    self.commands[name] = handler
  end,
  _SafeCall=function(self, object, method)
    if object and object[method] then return object[method](object) end
  end,
  _CoalitionToName=function() return "blue" end,
  _BuildAirbaseSnapshotItem=function(self, name, airbase)
    return {object_id="AIRBASE:" .. name, dcs_name=name, name=name,
      x=airbase.x, y=0, z=airbase.z, latitude=airbase.latitude, longitude=airbase.longitude}
  end,
  _Log=function(self, text) logs[#logs + 1] = text end,
  SendEvent=function(self, name, payload) events[#events + 1] = {event=name, payload=payload} end,
  _FlushOutQueue=function() end,
}
local function group(name, id)
  return {name=name, id=id, alive=true,
    GetName=function(self) return self.name end,
    GetID=function(self) return self.id end,
    IsAlive=function(self) return self.alive end}
end
local hornet, other = group("Hornet", 10), group("Other", 20)
_DATABASE = {GROUPS={Hornet=hornet, Other=other}}
MENU_INDEX = {Group={}}
missionCommands = {removeItemForGroup=function() end}
MENU_GROUP = {}
function MENU_GROUP:New(g, text, parent)
  local path = (parent and parent.Path or "") .. "@" .. text
  MENU_INDEX.Group[g.name] = MENU_INDEX.Group[g.name] or {Menus={}}
  local menus = MENU_INDEX.Group[g.name].Menus
  if menus[path] then return menus[path] end
  created = created + 1
  local menu = {Group=g, GroupID=g.id, Menus={}, Path=path, MenuPath={text}}
  menus[path] = menu
  if parent then parent.Menus[text] = menu end
  function menu:RemoveSubMenus()
    local children = {}
    for _, child in pairs(self.Menus or {}) do children[#children + 1] = child end
    for _, child in ipairs(children) do child:Remove() end
    self.Menus = {}
  end
  function menu:Remove()
    if not self.Group.alive then return end -- Match MOOSE's alive gate.
    self:RemoveSubMenus()
    menus[self.Path] = nil
    if parent then parent.Menus[text] = nil end
  end
  return menu
end
MENU_GROUP_COMMAND = {}
function MENU_GROUP_COMMAND:New(g, text, parent, callback)
  local menu = MENU_GROUP:New(g, text, parent)
  menu.callback = callback
  return menu
end
MESSAGE = {New=function(self, text, duration, title)
  return {ToGroup=function(_, g)
    messages[#messages + 1] = {text=text, group=g, duration=duration}
  end}
end}
SCHEDULER = {New=function(_, bridge, callback, args, delay)
  assert(delay == 0.5)
  local entry = {run=function() callback(bridge) end}
  scheduled[#scheduled + 1] = entry
  return entry
end}
dofile(source)
local registered = MOOSE_BRIDGE.RegisterDefaultCommands
dofile(source)
assert(MOOSE_BRIDGE.RegisterDefaultCommands == registered, "duplicate loads must not wrap registration again")
local bridge = setmetatable({}, {__index=MOOSE_BRIDGE})
-- Leave the actual lifecycle and menu functions under test intact.
bridge._NotifyPlayerEnteredAircraft = function() end
bridge:RegisterDefaultCommands()
local configure = assert(bridge.commands["player.menu.test.configure"])
local function config(enabled, owner)
  return configure({params={enabled=enabled, owner_id=owner or "test"}})
end
local function event(player, g, time)
  return {IniPlayerName=player, IniUnitName=player .. "-unit",
    IniGroupName=g.name, IniGroup=g, time=time}
end
local function enter(player, g, time)
  bridge:_ForwardPlayerAircraftEvent(event(player, g, time), "player.aircraft.entered", "ENTER", true)
end
local function leave(player, g, time)
  bridge:OnEventPlayerLeaveUnit(event(player, g, time))
end
local function menu(g)
  return bridge.PlayerTestMenus and bridge.PlayerTestMenus[g.name]
end
local function click(entry, text) entry.menu.Menus[text].callback() end

local foreign = MENU_GROUP:New(hornet, "MissionTools")
enter("Pilot", hornet, 1)
assert(not menu(hornet), "menu must be opt-in")
assert(config(true).group_count == 1, "existing occupant must get menu")
local first = assert(menu(hornet))
local before = #events
click(first, "Show message")
assert(#messages == 1 and messages[1].group == hornet)
assert(messages[1].text == "Menu test successful! Group: Hornet")
assert(#events == before, "message command must stay local")
click(first, "Python console")
local payload = events[#events].payload
assert(events[#events].event == "player.menu.selected")
assert(payload.group_id == "GROUP:Hornet" and payload.scope == "group")
assert(payload.owner_id == "test" and payload.action == "python_console")
assert(payload.player_name == nil and payload.group_sessions[1].player_name == "Pilot")
local menu_count = created
enter("Wingman", hornet, 2)
assert(created == menu_count and menu(hornet) == first, "same group must share a menu")
click(first, "Python console")
assert(#events[#events].payload.group_sessions == 2)
leave("Pilot", hornet, 3)
assert(menu(hornet) == first, "other occupant still needs the menu")
before = #events
leave("Pilot", hornet, 3.001)
assert(#events == before, "duplicate leave must remain suppressed")
local stale_callback = first.menu.Menus["Python console"].callback
leave("Wingman", hornet, 4)
assert(not menu(hornet))
before = #events
stale_callback()
assert(#events == before, "removed callbacks must be inert")
assert(MENU_INDEX.Group.Hornet.Menus[foreign.Path] == foreign)

hornet.id = 11
enter("Pilot", hornet, 5)
local second = assert(menu(hornet))
assert(second ~= first and second.group_id == 11)
local old_callback = second.menu.Menus["Python console"].callback
config(true, "new-run")
assert(config(false, "test").enabled, "old script cannot remove new run's menu")
before = #events
old_callback()
assert(#events == before)
click(assert(menu(hornet)), "Python console")
assert(events[#events].payload.owner_id == "new-run")

-- Dead wrappers cause MOOSE Remove to return without clearing its index.
hornet.alive = false
leave("Pilot", hornet, 6)
assert(not menu(hornet))
assert(MENU_INDEX.Group.Hornet.Menus["@MoosePyBridge Test"] == nil)
assert(MENU_INDEX.Group.Hornet.Menus["@MoosePyBridge Test@Python console"] == nil)
assert(MENU_INDEX.Group.Hornet.Menus[foreign.Path] == foreign)
hornet.alive, hornet.id = true, 12
enter("Pilot", hornet, 7)
assert(menu(hornet).group_id == 12)
enter("OtherPilot", other, 8)
assert(menu(other).group_id == 20)
assert(not config(false, "new-run").enabled)
assert(not menu(hornet) and not menu(other))

config(true)
bridge:OnEventMissionEnd({time=9})
assert(not menu(hornet) and not menu(other) and not bridge.PlayerTestMenuConfig)
assert(next(bridge.PlayerAircraftSessions) == nil)
assert(events[#events].event == "mission.ended")

config(true)
bridge:OnEventPlayerEnterAircraft(event("QuickPilot", hornet, 10))
leave("QuickPilot", hornet, 10.1)
assert(not menu(hornet))
before = #events
scheduled[#scheduled].run()
assert(not menu(hornet) and #events == before, "deferred enter must not resurrect menu")
enter("Pilot", hornet, 11)
bridge:_StopDcsEventForwarding()
assert(not menu(hornet) and not bridge.PlayerTestMenuConfig)

assert(not pcall(config, "true"), "invalid enable must fail")
assert(not pcall(config, true, ""), "empty owner must fail")
enter("Pilot", hornet, 12)
local constructor = MENU_GROUP_COMMAND.New
MENU_GROUP_COMMAND.New = function() error("mock menu construction failure") end
assert(not pcall(config, true), "construction failure must reject enable")
assert(not menu(hornet) and not bridge.PlayerTestMenuConfig, "partial tree must be removed")
MENU_GROUP_COMMAND.New = constructor
assert(MENU_INDEX.Group.Hornet.Menus[foreign.Path] == foreign)
-- Navigation replaces the test profile and guards every asynchronous write.
local overlays, cleared = {}, {}
bridge.DebugOverlays = {}
bridge._DrawDebugOverlay = function(self, params)
  overlays[params.overlay_id] = params
  self.DebugOverlays[params.overlay_id] = {101}
  return {drawn=true}
end
bridge._ClearDebugOverlay = function(self, id)
  assert(id, "must never clear every overlay")
  overlays[id] = nil
  self.DebugOverlays[id] = nil
  cleared[#cleared + 1] = id
  return 1
end
bridge._CreateMapMarker = function() error("preflight must not create markers") end
_DATABASE.FLIGHTGROUPS = {Hornet={}}
config(true)
local navconfig = bridge.commands["player.menu.navigation.configure"]
navconfig({params={enabled=true, owner_id="nav-run"}})
assert(MENU_INDEX.Group.Hornet.Menus["@MoosePyBridge Test"] == nil)
local nav = assert(menu(hornet))
assert(events[#events].event == "player.menu.created", "existing occupant needs an initialization event")
assert(events[#events].payload.session_id == nav.session_id and events[#events].payload.owner_id == "nav-run")
before = #events
bridge:_SyncPlayerTestMenu(hornet.name, hornet)
assert(#events == before, "existing menu must not initialize again")
local runtime = bridge.commands["player.menu.navigation.status"]({params={}})
assert(runtime.api_version == 1 and runtime.ready and runtime.theater_id == "Caucasus")
assert(runtime.capabilities.navaid_overlay and runtime.owner_id == "nav-run")
assert(runtime.capabilities.navaids_initialize)
assert(runtime.capabilities.airfield_radios)
assert(not pcall(navconfig, {params={enabled=true, owner_id="wrong-instance", expected_instance_id="old-instance"}}))
assert(menu(hornet) == nav and bridge.PlayerTestMenuConfig.owner_id == "nav-run")
assert(bridge.commands["player.menu.navigation.status"]({params={}}).instance_id == runtime.instance_id)
local marker_method = bridge._CreateMapMarker
bridge._CreateMapMarker = false
assert(not bridge.commands["player.menu.navigation.status"]({params={}}).capabilities.navaid_overlay)
bridge._CreateMapMarker = marker_method
assert(nav.menu.Path == "@Navigation")
local expected = { ["Show route"]="route_show", ["Hide route"]="route_hide",
  ["Navigation status"]="status", ["Flight status"]="flight_status",
  ["Enable hints"]="hints_on", ["Disable hints"]="hints_off" }
local count = 0
for label, action in pairs(expected) do
  count = count + 1
  click(nav, label)
  assert(events[#events].payload.action == action, "each closure must bind its own action")
  assert(events[#events].payload.menu_id == "navigation")
  assert(events[#events].payload.session_id == nav.session_id)
end
local actual = 0
for _ in pairs(nav.menu.Menus) do actual = actual + 1 end
assert(count == 6 and actual == 8 and nav.menu.Menus.Navaids and nav.menu.Menus["Airfields / ATC"])
local function verify_menu_limit(root)
  local size = 0
  for _, child in pairs(root.Menus or {}) do
    size = size + 1
    verify_menu_limit(child)
  end
  assert(size <= 9, "reserve one of the ten positions for DCS back navigation")
end
verify_menu_limit(nav.menu)
assert(nav.menu.Menus.Navaids.Menus.TACAN)
assert(nav.menu.Menus.Navaids.Menus["More types"].Menus.RSBN)
local function navcall(operation, entry, extra)
  local params = extra or {}
  params.owner_id = params.owner_id or "nav-run"
  params.group_id = "GROUP:" .. entry.group.name
  params.session_id = entry.session_id
  return bridge.commands["player.menu.navigation." .. operation]({params=params})
end
local context = navcall("context", nav)
assert(context.opsgroup_id == "OPSGROUP:Hornet" and #context.group_sessions == 1)
assert(context.theater_id == "Caucasus")
navcall("message", nav, {text="NAV status"})
assert(messages[#messages].group == hornet)
assert(not pcall(navcall, "message", nav, {text="wrong owner", owner_id="old-run"}))
-- Flight telemetry is read from the occupied DCS unit, without a FLIGHTGROUP.
local position = {p={x=100, y=3048, z=200}, x={x=1, y=0, z=0}}
local velocity = {x=100, y=-5, z=20}
local exists, unit_group_id = true, hornet.id
local dcsunit = {
  isExist=function() return exists end,
  getGroup=function() return {getID=function() return unit_group_id end} end,
  getPosition=function() return position end,
  getVelocity=function() return velocity end,
}
_DATABASE.UNITS = {["Pilot-unit"]={GetDCSObject=function() return dcsunit end}}
_DATABASE.AIRBASES = {
  Batumi={x=1000, z=2000, latitude=41.6, longitude=41.6, GetID=function() return 22 end},
  Kutaisi={x=3000, z=4000, latitude=42.1, longitude=42.4, GetID=function() return 25 end},
}
local resolved = navcall("airfields.resolve", nav, {unit_id="UNIT:Pilot-unit", theater_id="Caucasus",
  airbase_ids={22, 25, 99}})
assert(#resolved.airbases == 2 and #resolved.unresolved_airbase_ids == 1
  and resolved.unresolved_airbase_ids[1] == 99)
local airfields = nav.airfields
local initial_airfields = navcall("airfields.initialize", nav, {unit_id="UNIT:Pilot-unit",
  theater_id="Caucasus", page=0, pages=1,
  items={{key="1", label="1. Batumi (1.0 NM)"}, {key="2", label="2. Kutaisi (2.0 NM)"}}})
assert(initial_airfields.initialized and initial_airfields.airfield_revision == 1)
airfields.menu.Menus["1. Batumi (1.0 NM)"].callback()
assert(events[#events].payload.action == "airfield_details" and events[#events].payload.station_key == "1")
navcall("message", nav, {text="Airfield communications: Batumi", unit_id="UNIT:Pilot-unit",
  theater_id="Caucasus", airfield_revision=1, station_key="1"})
airfields.menu.Menus["Refresh nearby"].callback()
assert(events[#events].payload.action == "airfields_refresh" and events[#events].payload.request_id == "1")
local changed = navcall("airfields.page", nav, {unit_id="UNIT:Pilot-unit", theater_id="Caucasus",
  airfield_revision=1, request_id="1", page=0, pages=1, items={}})
assert(changed.airfield_revision == 2 and airfields.menu.Menus["Refresh nearby"])
-- Dynamic navaid pages are bounded and stale callbacks/responses are inert.
local tacan = nav.navaids.TACAN
local initial_refresh = tacan.menu.Menus["Refresh nearby"].callback
initial_refresh()
assert(events[#events].payload.action == "navaids_refresh")
assert(events[#events].payload.navaid_type == "TACAN" and events[#events].payload.request_id == "1")
local function page_params(revision, request, page, pages, count)
  local items = {}
  for i=1,count do items[i] = {key=tostring(i), label="Station " .. tostring(i)} end
  return {navaid_type="TACAN", navaid_revision=revision, request_id=request,
    theater_id="Caucasus", unit_id="UNIT:Pilot-unit", page=page, pages=pages, items=items}
end
assert(not pcall(navcall, "navaids.page", nav, page_params(0, "1", 0, 3, 7)))
assert(tacan.revision == 0, "invalid page must not remove existing commands")
local updated = navcall("navaids.page", nav, page_params(0, "1", 0, 3, 6))
assert(updated.navaid_revision == 1)
verify_menu_limit(nav.menu)
local first_station = tacan.menu.Menus["Station 1"].callback
first_station()
assert(events[#events].payload.action == "navaid_details" and events[#events].payload.station_key == "1")
assert(events[#events].payload.navaid_revision == 1)
local selected_menu = nav.menu.Menus.Navaids.Menus["Selected station"]
assert(selected_menu.Menus["Show on F10"] and selected_menu.Menus["Show with bearing line"]
  and selected_menu.Menus["Hide from F10"])
selected_menu.Menus["Show on F10"].callback()
assert(events[#events].payload.action == "navaid_show" and not events[#events].payload.selection_id)
local selected = navcall("message", nav, {text="Station details", unit_id="UNIT:Pilot-unit",
  navaid_type="TACAN", navaid_revision=1, theater_id="Caucasus", station_key="1"})
assert(selected.selection_id == "1" and not overlays[nav.navaid_overlay_id], "inspection must not draw")
selected_menu.Menus["Show on F10"].callback()
assert(events[#events].payload.selection_id == "1")
local stale_show = selected_menu.Menus["Show on F10"].callback
local marker_params
bridge._CreateMapMarker = function(self, params)
  marker_params = params
  return {mark_id=102}
end
local function map_params(line)
  return {show=true, selection_id=nav.navaid_selection.id, unit_id="UNIT:Pilot-unit",
    theater_id="Caucasus", point={latitude=41, longitude=42, altitude=0},
    text="BTM | Batumi\nTACAN | Source data\nChannel: 16X", bearing_line=line,
    coalition="all", overlay_id="unrelated"}
end
navcall("overlay", nav, {show=true, features={{kind="line"}}})
navcall("navaids.overlay", nav, map_params(false))
assert(overlays[nav.overlay_id] and overlays[nav.navaid_overlay_id])
assert(#overlays[nav.navaid_overlay_id].features == 1 and marker_params.coalition == "blue")
assert(marker_params.read_only and bridge.DebugOverlays[nav.navaid_overlay_id][2] == 102)
navcall("navaids.overlay", nav, map_params(true))
assert(#overlays[nav.navaid_overlay_id].features == 2)
assert(overlays[nav.navaid_overlay_id].features[2].points[1].x == position.p.x)
assert(overlays[nav.navaid_overlay_id].coalition == "blue", "caller cannot widen visibility")
navcall("navaids.overlay", nav, {show=false})
assert(not overlays[nav.navaid_overlay_id] and overlays[nav.overlay_id], "hide must not clear route")
navcall("navaids.overlay", nav, {show=false}) -- Idempotent without selection parameters.
local invalid = map_params(true)
invalid.selection_id = "stale"
assert(not pcall(navcall, "navaids.overlay", nav, invalid))
invalid = map_params(true)
invalid.point.latitude = 91
assert(not pcall(navcall, "navaids.overlay", nav, invalid))
invalid = map_params(true)
invalid.unit_id = "UNIT:Other"
assert(not pcall(navcall, "navaids.overlay", nav, invalid))
invalid = map_params(true)
invalid.theater_id = "Nevada"
assert(not pcall(navcall, "navaids.overlay", nav, invalid))
invalid = map_params(true)
invalid.text = string.rep("a", 181)
assert(not pcall(navcall, "navaids.overlay", nav, invalid))
local original_marker = bridge._CreateMapMarker
bridge._CreateMapMarker = function() error("mock label failure") end
assert(not pcall(navcall, "navaids.overlay", nav, map_params(true)))
assert(not overlays[nav.navaid_overlay_id] and overlays[nav.overlay_id], "failed label rolls back only navaid geometry")
bridge._CreateMapMarker = original_marker
navcall("navaids.overlay", nav, map_params(true))
local previous_selection = nav.navaid_selection.id
navcall("message", nav, {text="Another station", unit_id="UNIT:Pilot-unit",
  navaid_type="TACAN", navaid_revision=1, theater_id="Caucasus", station_key="2"})
assert(nav.navaid_selection.id ~= previous_selection and marker_params.text:find("Batumi"))
invalid = map_params(true)
invalid.selection_id = previous_selection
assert(not pcall(navcall, "navaids.overlay", nav, invalid), "selection changes invalidate delayed show")
assert(not pcall(navcall, "message", nav, {text="stale shown message", selection_id=previous_selection,
  unit_id="UNIT:Pilot-unit", theater_id="Caucasus"}))
assert(not pcall(navcall, "message", nav, {text="off page", unit_id="UNIT:Pilot-unit",
  navaid_type="TACAN", navaid_revision=1, theater_id="Caucasus", station_key="999"}))
before = #events
initial_refresh()
assert(#events == before, "replaced refresh callback must be inert")
tacan.menu.Menus["Next page"].callback()
assert(events[#events].payload.page == 1 and events[#events].payload.request_id == "2")
navcall("navaids.page", nav, page_params(1, "2", 1, 3, 6))
verify_menu_limit(nav.menu) -- six stations + refresh + previous + next = nine.
assert(tacan.menu.Menus["Previous page"] and tacan.menu.Menus["Next page"])
before = #events
first_station()
assert(#events == before, "old station callback must not address a new page")
assert(not pcall(navcall, "message", nav, {text="stale station", unit_id="UNIT:Pilot-unit",
  navaid_type="TACAN", navaid_revision=1, theater_id="Caucasus"}))
assert(not pcall(navcall, "navaids.page", nav, page_params(1, "2", 2, 3, 6)))
tacan.menu.Menus["Next page"].callback()
tacan.menu.Menus["Refresh nearby"].callback() -- Supersedes the pending next page.
assert(not pcall(navcall, "navaids.page", nav, page_params(2, "3", 2, 3, 6)))
local wrong_terrain = page_params(2, "4", 0, 1, 0)
wrong_terrain.theater_id = "Nevada"
assert(not pcall(navcall, "navaids.page", nav, wrong_terrain))
local duplicate_labels = page_params(2, "4", 0, 1, 2)
duplicate_labels.items[2].label = duplicate_labels.items[1].label
assert(not pcall(navcall, "navaids.page", nav, duplicate_labels))
navcall("navaids.page", nav, page_params(2, "4", 0, 1, 0))
assert(tacan.menu.Menus["Refresh nearby"] and not tacan.menu.Menus["Next page"])
verify_menu_limit(nav.menu)
local stale_navaid_refresh = tacan.menu.Menus["Refresh nearby"].callback
assert(nav.navaids.VOR.revision == 0, "type pages must be independent")
navcall("navaids.overlay", nav, map_params(true)) -- Selection survives paging/refresh.
local terrain = 100
land = {getHeight=function(point)
  assert(point.x == 100 and point.y == 200, "terrain uses x/z, not altitude")
  return terrain
end}
coord = {
  LOtoLL=function(point) assert(point.y == 3048) return 42, 41 end,
  LLtoLO=function(lat, lon)
    assert(lon == 41)
    -- A rotated map, with an arbitrary round-trip position offset.
    return {x=lat * 100000 + 800, y=0, z=lat * 10000 + 900}
  end,
}
_DATABASE.FLIGHTGROUPS.Hornet = nil
local telemetry = navcall("flight_status", nav)
assert(telemetry.unit_id == "UNIT:Pilot-unit" and telemetry.group_id == "GROUP:Hornet")
assert(telemetry.owner_id == "nav-run" and telemetry.session_id == nav.session_id)
assert(telemetry.sample_time_s == 100 and telemetry.altitude_msl_m == 3048)
assert(telemetry.terrain_elevation_m == 100 and telemetry.velocity_mps.y == -5)
assert(math.abs(telemetry.true_north.x - 200) < 1e-6)
assert(math.abs(telemetry.true_north.z - 20) < 1e-6)
-- Optional POSITIONABLE speeds are isolated from missing methods and failures.
do
  local wrapper = _DATABASE.UNITS["Pilot-unit"]
  local flightgroup = {IsFlightgroup=function() return true end, GetState=function() return "Airborne" end}
  _DATABASE.FLIGHTGROUPS.Hornet = flightgroup
  local fields = {GetGroundSpeed="groundspeed_mps", GetAirspeedTrue="true_airspeed_mps",
    GetAirspeedIndicatedEstimated="estimated_ias_mps", GetMachNumber="mach_number"}
  local values = {GetGroundSpeed=150, GetAirspeedTrue=170, GetAirspeedIndicatedEstimated=140, GetMachNumber=0.52}
  local calls, wind_available = {}, true
  wrapper.GetCoord = function(self)
    assert(self == wrapper)
    return {y=3048, GetWindVec3=function(_, height, turbulence)
      assert(height == 3048 and turbulence == false)
      return wind_available and {x=5, y=0, z=10} or nil
    end, GetTemperature=function() return 15 end, GetPressure=function() return 1013.25 end,
      GetMagneticDeclination=function() return 6.25 end}
  end
  for method in pairs(fields) do
    local key = method
    wrapper[key] = function(self)
      assert(self == wrapper)
      calls[key] = (calls[key] or 0) + 1
      return values[key]
    end
  end
  wrapper.GetAirspeedIndicated = function() error("legacy IAS approximation must never be used") end
  telemetry = navcall("flight_status", nav)
  assert(telemetry.flightgroup_state == "Airborne")
  assert(telemetry.temperature_c == 15 and telemetry.pressure_hpa == 1013.25)
  assert(telemetry.magnetic_declination_deg == 6.25)
  for method, field in pairs(fields) do
    assert(telemetry[field] == values[method] and calls[method] == 1)
  end
  for method, field in pairs(fields) do
    local saved = wrapper[method]
    wrapper[method] = nil
    assert(navcall("flight_status", nav)[field] == nil)
    wrapper[method] = function() error("mock speed method failure") end
    assert(navcall("flight_status", nav)[field] == nil)
    wrapper[method] = saved
    local saved_value = values[method]
    for _, value in ipairs({-1, math.huge, 0/0, false, "invalid"}) do
      values[method] = value
      assert(navcall("flight_status", nav)[field] == nil)
    end
    values[method] = 0
    assert(navcall("flight_status", nav)[field] == 0, "valid zero must survive")
    values[method] = saved_value
  end
  wind_available = false
  telemetry = navcall("flight_status", nav)
  assert(telemetry.true_airspeed_mps == nil and telemetry.estimated_ias_mps == nil and telemetry.mach_number == nil)
  assert(telemetry.groundspeed_mps == 150 and telemetry.altitude_msl_m == 3048)
  wind_available = true
  flightgroup.GetState = function() error("mock FSM failure") end
  assert(navcall("flight_status", nav).flightgroup_state == nil)
  flightgroup.GetState = function() return "Air\nborne" end
  assert(navcall("flight_status", nav).flightgroup_state == nil)
  flightgroup.GetState = function() return "Cruising" end
  assert(navcall("flight_status", nav).flightgroup_state == "Cruising")
  flightgroup.IsFlightgroup = function() return false end
  assert(navcall("flight_status", nav).flightgroup_state == nil, "an OPSGROUP is not reported as FLIGHTGROUP")
  flightgroup.IsFlightgroup = function() return true end
  wrapper.GetCoord = function()
    return {y=3048, GetWindVec3=function() error("mock wind failure") end,
      GetTemperature=function() return 0/0 end, GetPressure=function() return -1 end,
      GetMagneticDeclination=function() return 181 end}
  end
  telemetry = navcall("flight_status", nav)
  assert(telemetry.temperature_c == nil and telemetry.pressure_hpa == nil)
  assert(telemetry.magnetic_declination_deg == nil)
  assert(telemetry.true_airspeed_mps == nil and telemetry.groundspeed_mps == 150)
  wrapper.GetCoord = function()
    return {y=3048, GetWindVec3=function() return {x=0,y=0,z=0} end,
      GetTemperature=function() error("mock temperature failure") end,
      GetPressure=function() error("mock pressure failure") end,
      GetMagneticDeclination=function() error("mock declination failure") end}
  end
  telemetry = navcall("flight_status", nav)
  assert(telemetry.temperature_c == nil and telemetry.pressure_hpa == nil
    and telemetry.magnetic_declination_deg == nil)
  local saved_velocity = velocity
  velocity = nil
  telemetry = navcall("flight_status", nav)
  for _, field in pairs(fields) do assert(telemetry[field] == nil, "no fallback zeros for missing velocity") end
  velocity = saved_velocity
  wrapper.GetMachNumber = function() exists = false; return 0.52 end
  assert(not pcall(navcall, "flight_status", nav), "despawn during sampling rejects the response")
  exists = true
  for method in pairs(fields) do wrapper[method] = nil end
  wrapper.GetCoord, wrapper.GetAirspeedIndicated = nil, nil
  _DATABASE.FLIGHTGROUPS.Hornet = nil
end
navcall("message", nav, {text="Flight status", unit_id="UNIT:Pilot-unit"})
assert(messages[#messages].duration == 10, "other messages keep the default duration")
navcall("message", nav, {text="Readable flight status", unit_id="UNIT:Pilot-unit", duration_s=15})
assert(messages[#messages].duration == 15)
for _, duration in ipairs({0, 31, 0/0, math.huge, true, "15"}) do
  assert(not pcall(navcall, "message", nav, {text="Invalid duration", duration_s=duration}))
end
assert(not pcall(navcall, "message", nav, {text="wrong aircraft", unit_id="UNIT:Other"}))
local saved_sessions = bridge._PlayerTestMenuSessions
bridge._PlayerTestMenuSessions = function()
  return {{unit_id="UNIT:Pilot-unit"}, {unit_id="UNIT:Pilot-unit"}}
end
assert(navcall("flight_status", nav).unit_id == "UNIT:Pilot-unit", "multicrew is unambiguous")
bridge._PlayerTestMenuSessions = function()
  return {{unit_id="UNIT:Pilot-unit"}, {unit_id="UNIT:Wingman-unit"}}
end
assert(not pcall(navcall, "flight_status", nav), "multiple aircraft cannot choose a reference")
assert(not pcall(navcall, "message", nav, {text="now ambiguous", unit_id="UNIT:Pilot-unit"}))
assert(not pcall(navcall, "navaids.overlay", nav, map_params(true)))
navcall("navaids.overlay", nav, {show=false}) -- Ambiguity cannot prevent hiding.
bridge._PlayerTestMenuSessions = saved_sessions
exists = false
assert(not pcall(navcall, "flight_status", nav), "dead DCS unit cannot supply telemetry")
exists, unit_group_id = true, -1
assert(not pcall(navcall, "flight_status", nav), "DCS group membership must match")
unit_group_id = hornet.id
local saved_position, saved_velocity, saved_coord = position, velocity, coord
position = {p={x=100, y=0, z=200}}
velocity, terrain, coord = nil, 0, nil
telemetry = navcall("flight_status", nav)
assert(telemetry.altitude_msl_m == 0 and telemetry.terrain_elevation_m == 0)
assert(telemetry.velocity_mps == nil and telemetry.forward == nil and telemetry.true_north == nil)
land.getHeight = function() error("terrain unavailable") end
assert(navcall("flight_status", nav).terrain_elevation_m == nil, "no sea-level fallback")
velocity = {x=0/0, y=0, z=0}
assert(navcall("flight_status", nav).velocity_mps == nil, "non-finite optional values are unavailable")
position.p.y = math.huge
assert(not pcall(navcall, "flight_status", nav), "invalid position must reject status")
position, velocity, coord = saved_position, saved_velocity, saved_coord
_DATABASE.FLIGHTGROUPS.Hornet = {}
navcall("overlay", nav, {show=true, features={{kind="line"}}, coalition="all"})
assert(overlays[nav.overlay_id].coalition == "blue", "coalition must come from group, not caller")
navcall("overlay", nav, {show=false})
assert(not overlays[nav.overlay_id])
navcall("overlay", nav, {show=true, features={{kind="line"}}})
navcall("navaids.overlay", nav, map_params(true))
enter("OtherPilot", other, 13)
local other_nav = assert(menu(other))
navcall("overlay", other_nav, {show=true, features={{kind="line"}}})
-- A different group's existing navaid marks must survive the first group leaving.
bridge:_DrawDebugOverlay({overlay_id=other_nav.navaid_overlay_id, features={{kind="point"}}})
assert(nav.overlay_id ~= other_nav.overlay_id)
leave("Pilot", hornet, 14)
assert(not overlays[nav.overlay_id] and overlays[other_nav.overlay_id])
assert(not overlays[nav.navaid_overlay_id] and overlays[other_nav.navaid_overlay_id])
assert(events[#events].event == "player.menu.closed")
assert(events[#events].payload.session_id == nav.session_id)
enter("Pilot", hornet, 15)
assert(menu(hornet).session_id ~= nav.session_id)
assert(events[#events].event == "player.menu.created", "later slot entry needs an initialization event")
assert(events[#events].payload.session_id == menu(hornet).session_id)
assert(not pcall(navcall, "message", nav, {text="stale reply"}))
assert(not pcall(navcall, "overlay", nav, {show=true, features={{kind="line"}}}))
assert(not pcall(navcall, "navaids.overlay", nav, {show=false}))
assert(not pcall(navcall, "navaids.overlay", nav, map_params(true)))
assert(not pcall(navcall, "context", nav))
assert(not pcall(navcall, "flight_status", nav), "old session cannot read a respawned unit")
before = #events
stale_navaid_refresh()
stale_show()
assert(#events == before, "old group-session callback must remain inert")
bridge:OnEventMissionEnd({time=16})
assert(next(overlays) == nil and not menu(hornet) and not menu(other))
assert(MENU_INDEX.Group.Hornet.Menus[foreign.Path] == foreign)
MOOSE_BRIDGE._NotifyPlayerEnteredAircraft(bridge, {
  player_name="Pilot", unit_name="Hornet-1", group_name="Hornet", aircraft_type="FA-18C_hornet",
}, hornet)
assert(messages[#messages].text == "Player Pilot entered aircraft slot Hornet-1 (FA-18C_hornet).")
-- Initial population uses the same validators and never supersedes user clicks.
navconfig({params={enabled=true, owner_id="nav-run"}})
enter("Pilot", hornet, 17)
local initial_nav = menu(hornet)
local initial = {unit_id="UNIT:Pilot-unit", theater_id="Caucasus", types={}}
for kind in pairs(initial_nav.navaids) do
  initial.types[kind] = {page=0, pages=3, items={{key="1", label="Initial station"}}}
end
initial.types.ICLS = {page=0, pages=1, items={}} -- Empty WWII/type data is valid.
initial.types.OTHER.items[2] = {key="2", label="Refresh nearby"}
assert(not pcall(navcall, "navaids.initialize", initial_nav, initial))
for _, state in pairs(initial_nav.navaids) do assert(state.revision == 0) end
initial.types.OTHER.items[2] = nil
initial.theater_id = "SinaiMap"
assert(not pcall(navcall, "navaids.initialize", initial_nav, initial))
initial.theater_id, initial.unit_id = "Caucasus", "UNIT:Other"
assert(not pcall(navcall, "navaids.initialize", initial_nav, initial))
initial.unit_id = "UNIT:Pilot-unit"
initial_nav.navaids.TACAN.menu.Menus["Refresh nearby"].callback()
local pending_refresh = events[#events].payload
local old_vor_refresh = initial_nav.navaids.VOR.menu.Menus["Refresh nearby"].callback
local message_count = #messages
local batch = navcall("navaids.initialize", initial_nav, initial)
assert(not batch.types.TACAN.initialized, "a pending manual request must win")
assert(batch.types.VOR.initialized and batch.types.VOR.navaid_revision == 1)
assert(batch.types.ICLS.initialized and initial_nav.navaids.ICLS.pages == 1)
assert(initial_nav.navaids.ICLS.menu.Menus["Refresh nearby"])
assert(#messages == message_count and next(overlays) == nil)
verify_menu_limit(initial_nav.menu)
before = #events
old_vor_refresh()
assert(#events == before, "initialization invalidates empty-page callbacks")
initial_nav.navaids.VOR.menu.Menus["Initial station"].callback()
assert(events[#events].payload.action == "navaid_details" and events[#events].payload.navaid_revision == 1)
navcall("navaids.page", initial_nav, page_params(0, pending_refresh.request_id, 0, 3, 6))
batch = navcall("navaids.initialize", initial_nav, initial)
for _, result in pairs(batch.types) do assert(not result.initialized, "batch replay must not overwrite lists") end
leave("Pilot", hornet, 18)
assert(not pcall(navcall, "navaids.initialize", initial_nav, initial), "closed sessions reject delayed batches")
enter("Pilot", hornet, 19)
initial_nav = menu(hornet)
local original_build = bridge._BuildNavaidMenuPage
bridge._BuildNavaidMenuPage = function(self, entry, kind, state, items)
  if kind == "VOR" and #items > 0 then error("mock initial page failure") end
  return original_build(self, entry, kind, state, items)
end
batch = navcall("navaids.initialize", initial_nav, initial)
assert(not batch.types.VOR.initialized and batch.types.VOR.error)
assert(batch.types.TACAN.initialized and initial_nav.navaids.VOR.revision == 2)
assert(initial_nav.navaids.VOR.menu.Menus["Refresh nearby"], "failed types retain manual recovery")
bridge._BuildNavaidMenuPage = original_build
verify_menu_limit(initial_nav.menu)
bridge:OnEventMissionEnd({time=20})
print("PLAYER MENU LUA TEST PASSED")
