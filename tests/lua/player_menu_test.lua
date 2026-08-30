-- Run with Lua 5.1+; DCS/MOOSE boundaries are deliberately mocked.
local source = assert(arg[1], "extension path required")
local events, messages, logs, scheduled = {}, {}, {}, {}
local created = 0
timer = {getTime=function() return 100 end}
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
  function menu:Remove()
    if not self.Group.alive then return end -- Match MOOSE's alive gate.
    for _, child in pairs(self.Menus) do child:Remove() end
    self.Menus = {}
    menus[self.Path] = nil
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
click(first, "Nachricht anzeigen")
assert(#messages == 1 and messages[1].group == hornet)
assert(#events == before, "message command must stay local")
click(first, "Python-Konsole")
local payload = events[#events].payload
assert(events[#events].event == "player.menu.selected")
assert(payload.group_id == "GROUP:Hornet" and payload.scope == "group")
assert(payload.owner_id == "test" and payload.action == "python_console")
assert(payload.player_name == nil and payload.group_sessions[1].player_name == "Pilot")
local menu_count = created
enter("Wingman", hornet, 2)
assert(created == menu_count and menu(hornet) == first, "same group must share a menu")
click(first, "Python-Konsole")
assert(#events[#events].payload.group_sessions == 2)
leave("Pilot", hornet, 3)
assert(menu(hornet) == first, "other occupant still needs the menu")
before = #events
leave("Pilot", hornet, 3.001)
assert(#events == before, "duplicate leave must remain suppressed")
local stale_callback = first.menu.Menus["Python-Konsole"].callback
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
local old_callback = second.menu.Menus["Python-Konsole"].callback
config(true, "new-run")
assert(config(false, "test").enabled, "old script cannot remove new run's menu")
before = #events
old_callback()
assert(#events == before)
click(assert(menu(hornet)), "Python-Konsole")
assert(events[#events].payload.owner_id == "new-run")

-- Dead wrappers cause MOOSE Remove to return without clearing its index.
hornet.alive = false
leave("Pilot", hornet, 6)
assert(not menu(hornet))
assert(MENU_INDEX.Group.Hornet.Menus["@MoosePyBridge Test"] == nil)
assert(MENU_INDEX.Group.Hornet.Menus["@MoosePyBridge Test@Python-Konsole"] == nil)
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
bridge._DrawDebugOverlay = function(self, params)
  overlays[params.overlay_id] = params
  return {drawn=true}
end
bridge._ClearDebugOverlay = function(self, id)
  assert(id, "must never clear every overlay")
  overlays[id] = nil
  cleared[#cleared + 1] = id
  return 1
end
_DATABASE.FLIGHTGROUPS = {Hornet={}}
config(true)
local navconfig = bridge.commands["player.menu.navigation.configure"]
navconfig({params={enabled=true, owner_id="nav-run"}})
assert(MENU_INDEX.Group.Hornet.Menus["@MoosePyBridge Test"] == nil)
local nav = assert(menu(hornet))
assert(nav.menu.Path == "@Navigation")
local expected = { ["Route anzeigen"]="route_show", ["Route ausblenden"]="route_hide",
  ["Navigationsstatus"]="status", ["Hinweise ein"]="hints_on", ["Hinweise aus"]="hints_off" }
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
assert(count == actual and count == 5)
local function navcall(operation, entry, extra)
  local params = extra or {}
  params.owner_id = params.owner_id or "nav-run"
  params.group_id = "GROUP:" .. entry.group.name
  params.session_id = entry.session_id
  return bridge.commands["player.menu.navigation." .. operation]({params=params})
end
local context = navcall("context", nav)
assert(context.opsgroup_id == "OPSGROUP:Hornet" and #context.group_sessions == 1)
navcall("message", nav, {text="NAV status"})
assert(messages[#messages].group == hornet)
assert(not pcall(navcall, "message", nav, {text="wrong owner", owner_id="old-run"}))
navcall("overlay", nav, {show=true, features={{kind="line"}}, coalition="all"})
assert(overlays[nav.overlay_id].coalition == "blue", "coalition must come from group, not caller")
navcall("overlay", nav, {show=false})
assert(not overlays[nav.overlay_id])
navcall("overlay", nav, {show=true, features={{kind="line"}}})
enter("OtherPilot", other, 13)
local other_nav = assert(menu(other))
navcall("overlay", other_nav, {show=true, features={{kind="line"}}})
assert(nav.overlay_id ~= other_nav.overlay_id)
leave("Pilot", hornet, 14)
assert(not overlays[nav.overlay_id] and overlays[other_nav.overlay_id])
assert(events[#events].event == "player.menu.closed")
assert(events[#events].payload.session_id == nav.session_id)
enter("Pilot", hornet, 15)
assert(menu(hornet).session_id ~= nav.session_id)
assert(not pcall(navcall, "message", nav, {text="stale reply"}))
assert(not pcall(navcall, "overlay", nav, {show=true, features={{kind="line"}}}))
assert(not pcall(navcall, "context", nav))
bridge:OnEventMissionEnd({time=16})
assert(next(overlays) == nil and not menu(hornet) and not menu(other))
assert(MENU_INDEX.Group.Hornet.Menus[foreign.Path] == foreign)
print("PLAYER MENU LUA TEST PASSED")
