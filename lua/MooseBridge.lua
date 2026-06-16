MOOSE_BRIDGE = MOOSE_BRIDGE or {}
MOOSE_BRIDGE.ClassName = "MOOSE_BRIDGE"

local json = MOOSE_BRIDGE_JSON
if not json then error("Load MooseBridgeJson.lua before MooseBridge.lua") end

local function mission_time()
  if timer and timer.getTime then return timer.getTime() end
  return nil
end

local function wall_time()
  if os and os.date then return os.date("!%Y-%m-%dT%H:%M:%SZ") end
  return nil
end

local function coalition_from_name(name)
  if name == "blue" then return coalition.side.BLUE end
  if name == "red" then return coalition.side.RED end
  if name == "neutral" then return coalition.side.NEUTRAL end
  return nil
end

local function safe_tostring(value)
  if value == nil then return "nil" end
  return tostring(value)
end

local function string_or_nil(value)
  if value == nil then return nil end
  return tostring(value)
end

local function append_unique(list, seen, value)
  if value == nil then return end
  local key = tostring(value)
  if seen[key] then return end
  list[#list + 1] = key
  seen[key] = true
end

function MOOSE_BRIDGE:New(host, port)
  local self = BASE and BASE:Inherit({}, BASE:New()) or {}
  setmetatable(self, { __index = MOOSE_BRIDGE })
  self.Host = host or "127.0.0.1"
  self.Port = port or 51000
  self.Socket = nil
  self.Scheduler = nil
  self.Connected = false
  self.Sequence = 0
  self.MarkId = 10000
  self.OutQueue = {}
  self.CommandHandlers = {}
  self.RegisteredZones = {}
  self.RegisteredOpsZones = {}
  self.RegisteredOpsGroups = {}
  self.ConnectRetryDelay = 5
  self.TickInterval = 0.2
  self.HeartbeatInterval = 5
  self.LastHeartbeat = 0
  self.LastConnectAttempt = -9999
  self:RegisterDefaultCommands()
  return self
end

function MOOSE_BRIDGE:_Log(message)
  local line = "[MOOSE_BRIDGE] " .. safe_tostring(message)
  if env and env.info then env.info(line) else print(line) end
end

function MOOSE_BRIDGE:Start()
  self:_Log("Starting bridge to " .. self.Host .. ":" .. tostring(self.Port))
  if not SCHEDULER then error("MOOSE_BRIDGE requires MOOSE SCHEDULER") end
  self.Scheduler = SCHEDULER:New(self, self._Tick, {}, 0, self.TickInterval)
  return self
end

function MOOSE_BRIDGE:Stop()
  if self.Scheduler then self.Scheduler:Stop(); self.Scheduler = nil end
  if self.Socket then self.Socket:close(); self.Socket = nil end
  self.Connected = false
  return self
end

function MOOSE_BRIDGE:_Connect()
  local now = mission_time() or 0
  if now - self.LastConnectAttempt < self.ConnectRetryDelay then return end
  self.LastConnectAttempt = now
  local socket_lib = require("socket")
  local sock = socket_lib.tcp()
  sock:settimeout(1)
  local ok, err = sock:connect(self.Host, self.Port)
  if not ok then self:_Log("Connect failed: " .. safe_tostring(err)); sock:close(); return end
  sock:settimeout(0)
  self.Socket = sock
  self.Connected = true
  self:_Log("Connected to Python bridge")
end

function MOOSE_BRIDGE:_Disconnect(reason)
  if reason then self:_Log("Disconnected: " .. safe_tostring(reason)) end
  if self.Socket then self.Socket:close(); self.Socket = nil end
  self.Connected = false
end

function MOOSE_BRIDGE:_NextId(prefix)
  self.Sequence = self.Sequence + 1
  return (prefix or "msg") .. "-" .. tostring(self.Sequence)
end

function MOOSE_BRIDGE:_NextMarkId()
  self.MarkId = self.MarkId + 1
  return self.MarkId
end

function MOOSE_BRIDGE:_BaseMessage(message_type)
  return {version=1,type=message_type,id=self:_NextId(message_type),source="dcs",sequence=self.Sequence,mission_time=mission_time(),wall_time=wall_time()}
end

function MOOSE_BRIDGE:Send(message)
  self.OutQueue[#self.OutQueue + 1] = json.encode(message)
  return self
end

function MOOSE_BRIDGE:SendHeartbeat()
  local msg = self:_BaseMessage("heartbeat")
  msg.status = "running"
  self:Send(msg)
end

function MOOSE_BRIDGE:SendSnapshot(kind, payload)
  local msg = self:_BaseMessage("snapshot")
  msg.kind = kind
  msg.payload = payload or {}
  self:Send(msg)
end

function MOOSE_BRIDGE:SendAck(command, ok, result, error_message)
  local msg = self:_BaseMessage("ack")
  msg.correlation_id = command and command.id or nil
  msg.ok = ok and true or false
  msg.result = result
  msg.error = error_message
  self:Send(msg)
end

function MOOSE_BRIDGE:RegisterCommand(action, handler)
  self.CommandHandlers[action] = handler
  return self
end

function MOOSE_BRIDGE:RegisterZone(zone, name)
  if not zone then return self end
  local zone_name = name or self:_SafeCall(zone, "GetName") or zone.ZoneName or zone.name
  if zone_name then self.RegisteredZones[safe_tostring(zone_name)] = zone end
  return self
end

function MOOSE_BRIDGE:RegisterZones(zones)
  if type(zones) ~= "table" then return self end
  for name, zone in pairs(zones) do self:RegisterZone(zone, name) end
  return self
end

function MOOSE_BRIDGE:RegisterOpsZone(opszone, name)
  if not opszone then return self end
  local zone_name = name or self:_SafeCall(opszone, "GetName") or opszone.Name or opszone.name
  if zone_name then self.RegisteredOpsZones[safe_tostring(zone_name)] = opszone end
  return self
end

function MOOSE_BRIDGE:RegisterOpsZones(opszones)
  if type(opszones) ~= "table" then return self end
  for name, opszone in pairs(opszones) do self:RegisterOpsZone(opszone, name) end
  return self
end

function MOOSE_BRIDGE:RegisterOpsGroup(opsgroup, name)
  if not opsgroup then return self end
  local group_name = name or self:_SafeCall(opsgroup, "GetName") or opsgroup.Name or opsgroup.name
  if group_name then self.RegisteredOpsGroups[safe_tostring(group_name)] = opsgroup end
  return self
end

function MOOSE_BRIDGE:RegisterOpsGroups(opsgroups)
  if type(opsgroups) ~= "table" then return self end
  for name, opsgroup in pairs(opsgroups) do self:RegisterOpsGroup(opsgroup, name) end
  return self
end

function MOOSE_BRIDGE:_SafeCall(object, method_name)
  if not object or not method_name then return nil end
  local ok_method, method = pcall(function() return object[method_name] end)
  if not ok_method or not method then return nil end
  local ok, value = pcall(function() return method(object) end)
  if ok then return value end
  return nil
end

function MOOSE_BRIDGE:_SafeCallArg(object, method_name, ...)
  if not object or not method_name then return nil end
  local ok_method, method = pcall(function() return object[method_name] end)
  if not ok_method or not method then return nil end
  local args = {...}
  local ok, value = pcall(function() return method(object, unpack(args)) end)
  if ok then return value end
  return nil
end

function MOOSE_BRIDGE:_DcsCall(object, method_name)
  if not object or not method_name then return nil end
  local ok, value = pcall(function() return object[method_name](object) end)
  if ok then return value end
  return nil
end

function MOOSE_BRIDGE:_ObjectName(object)
  if not object then return nil end
  local name = self:_SafeCall(object, "GetName")
  if name then return safe_tostring(name) end
  if object.alias then return safe_tostring(object.alias) end
  if object.name then return safe_tostring(object.name) end
  if object.Name then return safe_tostring(object.Name) end
  if object.groupname then return safe_tostring(object.groupname) end
  return nil
end

function MOOSE_BRIDGE:_CoalitionToName(value)
  if value == nil then return nil end
  if coalition and coalition.side then
    if value == coalition.side.BLUE then return "blue" end
    if value == coalition.side.RED then return "red" end
    if value == coalition.side.NEUTRAL then return "neutral" end
  end
  if value == 2 then return "blue" end
  if value == 1 then return "red" end
  if value == 0 then return "neutral" end
  return tostring(value)
end

function MOOSE_BRIDGE:_AirbaseCategoryToName(value)
  if value == nil then return nil end
  if Airbase and Airbase.Category then
    if value == Airbase.Category.AIRDROME then return "AIRDROME" end
    if value == Airbase.Category.HELIPAD then return "HELIPAD" end
    if value == Airbase.Category.SHIP then return "SHIP" end
  end
  if value == 0 then return "AIRDROME" end
  if value == 1 then return "HELIPAD" end
  if value == 2 then return "SHIP" end
  return "UNKNOWN_" .. tostring(value)
end

function MOOSE_BRIDGE:_ObjectCategoryToName(value)
  if value == nil then return nil end
  if Object and Object.Category then
    if value == Object.Category.UNIT then return "UNIT" end
    if value == Object.Category.WEAPON then return "WEAPON" end
    if value == Object.Category.STATIC then return "STATIC" end
    if value == Object.Category.BASE then return "BASE" end
    if value == Object.Category.SCENERY then return "SCENERY" end
    if value == Object.Category.CARGO then return "CARGO" end
  end
  if value == 4 then return "BASE" end
  return tostring(value)
end

function MOOSE_BRIDGE:_BoolOrFalse(value)
  if value == nil then return false end
  return value and true or false
end

function MOOSE_BRIDGE:_NumberOrZero(value)
  if type(value) == "number" then return value end
  return 0
end

function MOOSE_BRIDGE:_NumberOrNil(value)
  if type(value) == "number" then return value end
  if type(value) == "string" then return tonumber(value) end
  return nil
end

function MOOSE_BRIDGE:_IsDcsObjectAlive(object)
  if not object then return false end
  local ok_exist, exists = pcall(function() return object:isExist() end)
  if ok_exist and not exists then return false end
  local ok_life, life = pcall(function() return object:getLife() end)
  if ok_life and type(life) == "number" then return life > 0 end
  return true
end

function MOOSE_BRIDGE:_DcsTypeName(object)
  return self:_DcsCall(object, "getTypeName")
end

function MOOSE_BRIDGE:_DcsPoint(object)
  return self:_DcsCall(object, "getPoint")
end

function MOOSE_BRIDGE:_PointFromMooseObject(object)
  if not object then return nil end
  local coordinate = self:_SafeCall(object, "GetCoordinate")
  if coordinate then
    local vec3 = self:_SafeCall(coordinate, "GetVec3")
    if vec3 then return vec3 end
  end
  local vec3 = self:_SafeCall(object, "GetVec3") or self:_SafeCall(object, "GetPointVec3")
  if vec3 then return vec3 end
  if object.Coordinate then
    vec3 = self:_SafeCall(object.Coordinate, "GetVec3")
    if vec3 then return vec3 end
  end
  if object.position then return object.position end
  return nil
end

function MOOSE_BRIDGE:_PointFromParams(params)
  local x = self:_NumberOrNil(params and params.x)
  local y = self:_NumberOrNil(params and params.y) or 0
  local z = self:_NumberOrNil(params and params.z)
  if x == nil or z == nil then error("Point commands require numeric x and z parameters") end
  return {x=x, y=y, z=z}
end

function MOOSE_BRIDGE:_SplitObjectId(object_id)
  if type(object_id) ~= "string" then return nil, nil end
  local separator = string.find(object_id, ":")
  if not separator then return nil, nil end
  return string.sub(object_id, 1, separator - 1), string.sub(object_id, separator + 1)
end

function MOOSE_BRIDGE:_PointForGroupName(name)
  local group = _DATABASE and _DATABASE.GROUPS and _DATABASE.GROUPS[name]
  if not group then return nil end
  local point = self:_PointFromMooseObject(group)
  if point then return point end
  local dcs_group = self:_SafeCall(group, "GetDCSObject")
  local ok, units = pcall(function() return dcs_group and dcs_group:getUnits() end)
  if ok and type(units) == "table" and units[1] then return self:_DcsPoint(units[1]) end
  return nil
end

function MOOSE_BRIDGE:_PointForUnitName(name)
  local unit = _DATABASE and _DATABASE.UNITS and _DATABASE.UNITS[name]
  if not unit then return nil end
  local dcs_unit = self:_SafeCall(unit, "GetDCSObject")
  return self:_DcsPoint(dcs_unit) or self:_PointFromMooseObject(unit)
end

function MOOSE_BRIDGE:_PointForStaticName(name)
  local static = _DATABASE and _DATABASE.STATICS and _DATABASE.STATICS[name]
  if not static then return nil end
  local dcs_static = self:_SafeCall(static, "GetDCSObject")
  return self:_DcsPoint(dcs_static) or self:_PointFromMooseObject(static)
end

function MOOSE_BRIDGE:_PointForAirbaseName(name)
  if not world or not world.getAirbases then return nil end
  local ok, airbases = pcall(function() return world.getAirbases() end)
  if not ok or type(airbases) ~= "table" then return nil end
  for _, airbase in pairs(airbases) do
    if self:_DcsCall(airbase, "getName") == name then return self:_DcsPoint(airbase) end
  end
  return nil
end

function MOOSE_BRIDGE:_PointForZoneName(name)
  local zone = self.RegisteredZones and self.RegisteredZones[name]
  if not zone and _DATABASE and _DATABASE.ZONES then zone = _DATABASE.ZONES[name] end
  if zone then
    local point = self:_PointFromMooseObject(zone)
    if point then return point end
  end
  if env and env.mission and env.mission.triggers and type(env.mission.triggers.zones) == "table" then
    for _, trigger_zone in pairs(env.mission.triggers.zones) do
      if trigger_zone.name == name then return {x=trigger_zone.x, y=0, z=trigger_zone.y} end
    end
  end
  return nil
end

function MOOSE_BRIDGE:_PointForObjectId(object_id)
  local object_type, name = self:_SplitObjectId(object_id)
  if not object_type or not name then error("Invalid object_id: " .. safe_tostring(object_id)) end
  if object_type == "GROUP" then return self:_PointForGroupName(name) end
  if object_type == "UNIT" then return self:_PointForUnitName(name) end
  if object_type == "STATIC" then return self:_PointForStaticName(name) end
  if object_type == "AIRBASE" then return self:_PointForAirbaseName(name) end
  if object_type == "ZONE" then return self:_PointForZoneName(name) end
  error("Unsupported object_id type for point lookup: " .. safe_tostring(object_type))
end

function MOOSE_BRIDGE:_CoordinateFromPoint(point)
  if not COORDINATE or not COORDINATE.NewFromVec3 then error("MOOSE COORDINATE is not available") end
  if not point then error("Point is nil") end
  return COORDINATE:NewFromVec3({x=point.x, y=point.y or 0, z=point.z})
end

function MOOSE_BRIDGE:_SmokePoint(point, color)
  local coordinate = self:_CoordinateFromPoint(point)
  local smoke_color = string.lower(color or "white")
  local method_by_color = {red="SmokeRed", green="SmokeGreen", blue="SmokeBlue", orange="SmokeOrange", white="SmokeWhite"}
  local method_name = method_by_color[smoke_color]
  if not method_name then error("Unsupported smoke color: " .. safe_tostring(color)) end
  local method = coordinate[method_name]
  if not method then error("COORDINATE method unavailable: " .. method_name) end
  method(coordinate)
  return {x=point.x, y=point.y or 0, z=point.z, color=smoke_color}
end

function MOOSE_BRIDGE:_MarkPoint(point, text)
  local coordinate = self:_CoordinateFromPoint(point)
  local mark_text = text or "MOOSE Bridge mark"
  if coordinate.MarkToAll then
    coordinate:MarkToAll(mark_text)
  elseif trigger and trigger.action and trigger.action.markToAll then
    trigger.action.markToAll(self:_NextMarkId(), mark_text, {x=point.x, y=point.y or 0, z=point.z}, true)
  else
    error("No mark implementation available")
  end
  return {x=point.x, y=point.y or 0, z=point.z, text=mark_text}
end

function MOOSE_BRIDGE:_CountTable(value)
  if type(value) ~= "table" then return 0 end
  local count = 0
  for _, _ in pairs(value) do count = count + 1 end
  return count
end

function MOOSE_BRIDGE:_CountSet(set_object)
  if not set_object then return 0 end
  local count = self:_SafeCall(set_object, "Count") or self:_SafeCall(set_object, "CountAlive")
  if type(count) == "number" then return count end
  if type(set_object.Set) == "table" then return self:_CountTable(set_object.Set) end
  return 0
end

function MOOSE_BRIDGE:_CountUnitsInTable(units, alive_only)
  if type(units) ~= "table" then return nil end
  local count = 0
  for _, unit in pairs(units) do
    if alive_only then
      if self:_IsMooseUnitAlive(unit) then count = count + 1 end
    else
      count = count + 1
    end
  end
  return count
end

function MOOSE_BRIDGE:_IsMooseUnitAlive(unit)
  if not unit then return false end
  local alive = self:_SafeCall(unit, "IsAlive")
  if alive ~= nil then return alive and true or false end
  local dcs_unit = self:_SafeCall(unit, "GetDCSObject")
  if dcs_unit then return self:_IsDcsObjectAlive(dcs_unit) end
  return false
end

function MOOSE_BRIDGE:_CountDcsGroupUnits(group, alive_only)
  local dcs_group = self:_SafeCall(group, "GetDCSObject")
  if not dcs_group then return nil end
  local ok, units = pcall(function() return dcs_group:getUnits() end)
  if not ok or type(units) ~= "table" then return nil end
  local count = 0
  for _, unit in pairs(units) do
    if alive_only then
      if self:_IsDcsObjectAlive(unit) then count = count + 1 end
    else
      count = count + 1
    end
  end
  return count
end

function MOOSE_BRIDGE:_CountGroupUnits(group, alive_only)
  local units = self:_SafeCall(group, "GetUnits")
  local count = self:_CountUnitsInTable(units, alive_only)
  if count ~= nil then return count end
  count = self:_CountDcsGroupUnits(group, alive_only)
  if count ~= nil then return count end
  if alive_only then count = self:_SafeCall(group, "CountAliveUnits") else count = self:_SafeCall(group, "CountUnits") end
  return self:_NumberOrZero(count)
end

function MOOSE_BRIDGE:_BuildGroupSnapshotItem(group_name, group)
  local name = self:_SafeCall(group, "GetName") or group_name
  local coalition_value = self:_SafeCall(group, "GetCoalition")
  local category = self:_SafeCall(group, "GetCategoryName") or self:_SafeCall(group, "GetCategory")
  local alive = self:_SafeCall(group, "IsAlive")
  local active = self:_SafeCall(group, "IsActive")
  local unit_count = self:_CountGroupUnits(group, false)
  local alive_unit_count = self:_CountGroupUnits(group, true)
  return {object_id="GROUP:"..safe_tostring(name),dcs_name=safe_tostring(name),object_type="GROUP",category=category and safe_tostring(category) or nil,coalition=self:_CoalitionToName(coalition_value),alive=self:_BoolOrFalse(alive),active=self:_BoolOrFalse(active),unit_count=self:_NumberOrZero(unit_count),alive_unit_count=self:_NumberOrZero(alive_unit_count)}
end

function MOOSE_BRIDGE:BuildGroupSnapshot()
  local result = {}
  if not _DATABASE or not _DATABASE.GROUPS then return result end
  for group_name, group in pairs(_DATABASE.GROUPS) do
    local ok, item = pcall(function() return self:_BuildGroupSnapshotItem(group_name, group) end)
    if ok and item then result[#result + 1] = item else self:_Log("Failed to snapshot group " .. safe_tostring(group_name) .. ": " .. safe_tostring(item)) end
  end
  return result
end

function MOOSE_BRIDGE:_BuildUnitSnapshotItem(unit_name, unit)
  local name = self:_SafeCall(unit, "GetName") or unit_name
  local group_name = self:_SafeCall(unit, "GetGroupName")
  local group = self:_SafeCall(unit, "GetGroup")
  if not group_name and group then group_name = self:_SafeCall(group, "GetName") end
  local coalition_value = self:_SafeCall(unit, "GetCoalition")
  if coalition_value == nil and group then coalition_value = self:_SafeCall(group, "GetCoalition") end
  local category = self:_SafeCall(unit, "GetCategoryName") or self:_SafeCall(unit, "GetCategory")
  if not category and group then category = self:_SafeCall(group, "GetCategoryName") or self:_SafeCall(group, "GetCategory") end
  local dcs_unit = self:_SafeCall(unit, "GetDCSObject")
  local dcs_type = self:_SafeCall(unit, "GetTypeName") or self:_DcsTypeName(dcs_unit)
  local alive = self:_SafeCall(unit, "IsAlive")
  if alive == nil then alive = self:_IsDcsObjectAlive(dcs_unit) end
  local active = self:_SafeCall(unit, "IsActive")
  local point = self:_DcsPoint(dcs_unit)
  local item = {object_id="UNIT:"..safe_tostring(name),dcs_name=safe_tostring(name),object_type="UNIT",group_name=group_name and safe_tostring(group_name) or nil,category=category and safe_tostring(category) or nil,coalition=self:_CoalitionToName(coalition_value),dcs_type=dcs_type and safe_tostring(dcs_type) or nil,alive=self:_BoolOrFalse(alive),active=self:_BoolOrFalse(active)}
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:BuildUnitSnapshot()
  local result = {}
  if _DATABASE and _DATABASE.UNITS then
    for unit_name, unit in pairs(_DATABASE.UNITS) do
      local ok, item = pcall(function() return self:_BuildUnitSnapshotItem(unit_name, unit) end)
      if ok and item then result[#result + 1] = item else self:_Log("Failed to snapshot unit " .. safe_tostring(unit_name) .. ": " .. safe_tostring(item)) end
    end
    return result
  end
  if not _DATABASE or not _DATABASE.GROUPS then return result end
  for _, group in pairs(_DATABASE.GROUPS) do
    local units = self:_SafeCall(group, "GetUnits")
    if type(units) == "table" then
      for unit_name, unit in pairs(units) do
        local ok, item = pcall(function() return self:_BuildUnitSnapshotItem(unit_name, unit) end)
        if ok and item then result[#result + 1] = item else self:_Log("Failed to snapshot group unit " .. safe_tostring(unit_name) .. ": " .. safe_tostring(item)) end
      end
    end
  end
  return result
end

function MOOSE_BRIDGE:_BuildStaticSnapshotItem(static_name, static)
  local name = self:_SafeCall(static, "GetName") or static_name
  local coalition_value = self:_SafeCall(static, "GetCoalition")
  local category = self:_SafeCall(static, "GetCategoryName") or self:_SafeCall(static, "GetCategory")
  local dcs_static = self:_SafeCall(static, "GetDCSObject")
  local dcs_type = self:_SafeCall(static, "GetTypeName") or self:_DcsTypeName(dcs_static)
  local alive = self:_SafeCall(static, "IsAlive")
  if alive == nil then alive = self:_IsDcsObjectAlive(dcs_static) end
  local point = self:_DcsPoint(dcs_static) or self:_PointFromMooseObject(static)
  local item = {object_id="STATIC:"..safe_tostring(name),dcs_name=safe_tostring(name),object_type="STATIC",category=category and safe_tostring(category) or "STATIC",coalition=self:_CoalitionToName(coalition_value),dcs_type=dcs_type and safe_tostring(dcs_type) or nil,alive=self:_BoolOrFalse(alive)}
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:BuildStaticSnapshot()
  local result = {}
  if not _DATABASE or not _DATABASE.STATICS then return result end
  for static_name, static in pairs(_DATABASE.STATICS) do
    local ok, item = pcall(function() return self:_BuildStaticSnapshotItem(static_name, static) end)
    if ok and item then result[#result + 1] = item else self:_Log("Failed to snapshot static " .. safe_tostring(static_name) .. ": " .. safe_tostring(item)) end
  end
  return result
end

function MOOSE_BRIDGE:_BuildAirbaseSnapshotItem(airbase)
  local name = self:_DcsCall(airbase, "getName")
  local coalition_value = self:_DcsCall(airbase, "getCoalition")
  local object_category = self:_DcsCall(airbase, "getCategory")
  local point = self:_DcsCall(airbase, "getPoint")
  local desc = self:_DcsCall(airbase, "getDesc")
  local airbase_category = nil; local dcs_type = nil; local display_name = nil
  if type(desc) == "table" then airbase_category = desc.category; dcs_type = desc.typeName; display_name = desc.displayName end
  local item = {object_id="AIRBASE:"..safe_tostring(name),dcs_name=safe_tostring(name),object_type="AIRBASE",category=self:_AirbaseCategoryToName(airbase_category) or "AIRBASE",dcs_category=object_category,dcs_category_name=self:_ObjectCategoryToName(object_category),coalition=self:_CoalitionToName(coalition_value),dcs_type=dcs_type and safe_tostring(dcs_type) or nil,display_name=display_name and safe_tostring(display_name) or nil}
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:BuildAirbaseSnapshot()
  local result = {}
  if not world or not world.getAirbases then return result end
  local ok, airbases = pcall(function() return world.getAirbases() end)
  if not ok or type(airbases) ~= "table" then return result end
  for _, airbase in pairs(airbases) do
    local ok_item, item = pcall(function() return self:_BuildAirbaseSnapshotItem(airbase) end)
    if ok_item and item then result[#result + 1] = item else self:_Log("Failed to snapshot airbase: " .. safe_tostring(item)) end
  end
  return result
end

function MOOSE_BRIDGE:_BuildMooseZoneSnapshotItem(zone_name, zone, source)
  local name = self:_SafeCall(zone, "GetName") or zone.ZoneName or zone_name
  local radius = self:_SafeCall(zone, "GetRadius") or zone.Radius
  local point = self:_PointFromMooseObject(zone)
  local item = {object_id="ZONE:"..safe_tostring(name),dcs_name=safe_tostring(name),object_type="ZONE",category="MOOSE_ZONE",source=source or "moose",radius=radius}
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:_BuildMissionZoneSnapshotItem(zone)
  return {object_id="ZONE:"..safe_tostring(zone.name),dcs_name=safe_tostring(zone.name),object_type="ZONE",category="TRIGGER_ZONE",source="mission",radius=zone.radius,x=zone.x,y=0,z=zone.y}
end

function MOOSE_BRIDGE:BuildZoneSnapshot()
  local result = {}; local seen = {}
  for zone_name, zone in pairs(self.RegisteredZones or {}) do
    local ok, item = pcall(function() return self:_BuildMooseZoneSnapshotItem(zone_name, zone, "registered") end)
    if ok and item and item.object_id then result[#result + 1] = item; seen[item.object_id] = true end
  end
  if _DATABASE and _DATABASE.ZONES then
    for zone_name, zone in pairs(_DATABASE.ZONES) do
      local ok, item = pcall(function() return self:_BuildMooseZoneSnapshotItem(zone_name, zone, "database") end)
      if ok and item and item.object_id and not seen[item.object_id] then result[#result + 1] = item; seen[item.object_id] = true end
    end
  end
  if env and env.mission and env.mission.triggers and type(env.mission.triggers.zones) == "table" then
    for _, zone in pairs(env.mission.triggers.zones) do
      local ok, item = pcall(function() return self:_BuildMissionZoneSnapshotItem(zone) end)
      if ok and item and item.object_id and not seen[item.object_id] then result[#result + 1] = item; seen[item.object_id] = true end
    end
  end
  return result
end

function MOOSE_BRIDGE:_OpsClassName(object, fallback)
  if type(object) == "table" then
    if object.ClassName then return tostring(object.ClassName) end
    if object.classname then return tostring(object.classname) end
  end
  return fallback
end

function MOOSE_BRIDGE:_OpsGroupKind(opsgroup)
  if self:_SafeCall(opsgroup, "IsFlightgroup") then return "FLIGHTGROUP" end
  if self:_SafeCall(opsgroup, "IsArmygroup") then return "ARMYGROUP" end
  if self:_SafeCall(opsgroup, "IsNavygroup") then return "NAVYGROUP" end
  return self:_OpsClassName(opsgroup, "OPSGROUP")
end

function MOOSE_BRIDGE:_OpsName(object, fallback)
  if not object then return fallback end
  return self:_SafeCall(object, "GetName") or fallback or object.Name or object.name or object.groupname
end

function MOOSE_BRIDGE:_OpsState(object)
  if not object then return nil end
  return self:_SafeCall(object, "GetState") or self:_SafeCall(object, "GetStateName") or object.State or object.state
end

function MOOSE_BRIDGE:_OpsCoalition(object)
  if not object then return nil end
  local coalition_value = self:_SafeCall(object, "GetCoalition") or object.Coalition or object.coalition or object.ownerCurrent
  return self:_CoalitionToName(coalition_value)
end

function MOOSE_BRIDGE:_AuftragNumber(auftrag)
  if not auftrag then return nil end
  return self:_SafeCall(auftrag, "GetAuftragsnummer") or auftrag.auftragsnummer or auftrag.Auftragsnummer
end

function MOOSE_BRIDGE:_AuftragObjectId(auftrag)
  local number = self:_AuftragNumber(auftrag)
  if number == nil then return nil end
  return "AUFTRAG:" .. safe_tostring(number)
end

function MOOSE_BRIDGE:_CollectAuftragIdsFromQueue(missionqueue)
  local ids = {}; local seen = {}
  if type(missionqueue) ~= "table" then return ids end
  for key, auftrag in pairs(missionqueue) do
    local object_id = nil
    if type(auftrag) == "table" then object_id = self:_AuftragObjectId(auftrag) end
    if not object_id and type(key) == "number" then object_id = "AUFTRAG:" .. safe_tostring(key) end
    append_unique(ids, seen, object_id)
  end
  return ids
end

function MOOSE_BRIDGE:_CollectDetectedGroupIds(opsgroup)
  local result = {}; local seen = {}
  local set_group = self:_SafeCall(opsgroup, "GetDetectedGroups")
  if not set_group then return result end

  local for_each = set_group.ForEachGroup
  if for_each then
    pcall(function()
      for_each(set_group, function(group)
        local name = self:_SafeCall(group, "GetName") or group.GroupName or group.groupname or group.Name or group.name
        if name then append_unique(result, seen, "GROUP:" .. safe_tostring(name)) end
      end)
    end)
  end

  if #result == 0 and type(set_group.Set) == "table" then
    for name, group in pairs(set_group.Set) do
      local group_name = self:_SafeCall(group, "GetName") or name
      append_unique(result, seen, "GROUP:" .. safe_tostring(group_name))
    end
  end

  return result
end

function MOOSE_BRIDGE:_BuildOpsZoneSnapshotItem(zone_name, opszone, source)
  local name = self:_OpsName(opszone, zone_name)
  local point = self:_PointFromMooseObject(opszone)
  local state = self:_OpsState(opszone)
  local item = {
    object_id="OPSZONE:"..safe_tostring(name),
    dcs_name=safe_tostring(name),
    object_type="OPSZONE",
    category=self:_OpsClassName(opszone, "OPSZONE"),
    source=source,
    name=safe_tostring(name),
    zone_name=string_or_nil(opszone and opszone.zoneName),
    zone_type=string_or_nil(opszone and opszone.zoneType),
    zone_radius=opszone and opszone.zoneRadius or nil,
    state=string_or_nil(state),
    owner_current_name=self:_CoalitionToName(opszone and opszone.ownerCurrent),
    owner_previous_name=self:_CoalitionToName(opszone and opszone.ownerPrevious),
    is_contested=self:_BoolOrFalse(opszone and opszone.isContested),
    n_red=opszone and opszone.Nred or 0,
    n_blue=opszone and opszone.Nblu or 0,
    n_neutral=opszone and opszone.Nnut or 0,
    threat_red=opszone and opszone.Tred or 0,
    threat_blue=opszone and opszone.Tblu or 0,
    threat_neutral=opszone and opszone.Tnut or 0,
    airbase_name=string_or_nil(opszone and opszone.airbaseName),
  }
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:BuildOpsZoneSnapshot()
  local result = {}; local seen = {}
  for name, opszone in pairs(self.RegisteredOpsZones or {}) do
    local ok, item = pcall(function() return self:_BuildOpsZoneSnapshotItem(name, opszone, "registered") end)
    if ok and item and item.object_id then result[#result + 1] = item; seen[item.object_id] = true end
  end
  if _DATABASE and type(_DATABASE.OPSZONES) == "table" then
    for name, opszone in pairs(_DATABASE.OPSZONES) do
      local ok, item = pcall(function() return self:_BuildOpsZoneSnapshotItem(name, opszone, "database.OPSZONES") end)
      if ok and item and item.object_id and not seen[item.object_id] then result[#result + 1] = item; seen[item.object_id] = true end
    end
  end
  return result
end

function MOOSE_BRIDGE:_BuildOpsGroupSnapshotItem(group_name, opsgroup, source)
  local name = self:_OpsName(opsgroup, group_name)
  local group_kind = self:_OpsGroupKind(opsgroup)
  local point = self:_PointFromMooseObject(opsgroup)
  local state = self:_OpsState(opsgroup)
  local alive = self:_SafeCall(opsgroup, "IsAlive")
  local active = self:_SafeCall(opsgroup, "IsActive")
  local current_id = nil
  if opsgroup and opsgroup.currentmission then current_id = "AUFTRAG:" .. safe_tostring(opsgroup.currentmission) end
  local item = {
    object_id="OPSGROUP:"..safe_tostring(name),
    dcs_name=safe_tostring(name),
    object_type="OPSGROUP",
    category=group_kind,
    class_name=self:_OpsClassName(opsgroup, "OPSGROUP"),
    source=source,
    name=safe_tostring(name),
    group_name=safe_tostring(name),
    state=string_or_nil(state),
    coalition=self:_OpsCoalition(opsgroup),
    alive=self:_BoolOrFalse(alive),
    active=self:_BoolOrFalse(active),
    is_ai=self:_BoolOrFalse(opsgroup and opsgroup.isAI),
    is_late_activated=self:_BoolOrFalse(opsgroup and opsgroup.isLateActivated),
    is_uncontrolled=self:_BoolOrFalse(opsgroup and opsgroup.isUncontrolled),
    is_dead=self:_BoolOrFalse(opsgroup and opsgroup.isDead),
    is_destroyed=self:_BoolOrFalse(opsgroup and opsgroup.isDestroyed),
    current_wp=opsgroup and opsgroup.currentwp or nil,
    speed_cruise=opsgroup and opsgroup.speedCruise or nil,
    speed_wp=opsgroup and opsgroup.speedWp or nil,
    heading=opsgroup and opsgroup.heading or nil,
    travel_dist=opsgroup and opsgroup.traveldist or nil,
    travel_time=opsgroup and opsgroup.traveltime or nil,
    homebase_name=self:_ObjectName(opsgroup and opsgroup.homebase),
    destbase_name=self:_ObjectName(opsgroup and opsgroup.destbase),
    currbase_name=self:_ObjectName(opsgroup and opsgroup.currbase),
    auftrag_current_id=current_id,
    auftrag_queue_ids=self:_CollectAuftragIdsFromQueue(opsgroup and opsgroup.missionqueue),
    detected_group_ids=self:_CollectDetectedGroupIds(opsgroup),
  }
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:BuildOpsGroupSnapshot()
  local result = {}; local seen = {}
  for name, opsgroup in pairs(self.RegisteredOpsGroups or {}) do
    local ok, item = pcall(function() return self:_BuildOpsGroupSnapshotItem(name, opsgroup, "registered") end)
    if ok and item and item.object_id then result[#result + 1] = item; seen[item.object_id] = true end
  end
  if _DATABASE and type(_DATABASE.FLIGHTGROUPS) == "table" then
    for name, opsgroup in pairs(_DATABASE.FLIGHTGROUPS) do
      local ok, item = pcall(function() return self:_BuildOpsGroupSnapshotItem(name, opsgroup, "database.FLIGHTGROUPS") end)
      if ok and item and item.object_id and not seen[item.object_id] then result[#result + 1] = item; seen[item.object_id] = true end
    end
  end
  return result
end

function MOOSE_BRIDGE:_AddAuftragCandidate(result, seen, auftrag, source)
  if type(auftrag) ~= "table" then return end
  local object_id = self:_AuftragObjectId(auftrag)
  if not object_id or seen[object_id] then return end
  local ok, item = pcall(function() return self:_BuildAuftragSnapshotItem(auftrag, source) end)
  if ok and item and item.object_id then
    result[#result + 1] = item
    seen[item.object_id] = true
  end
end

function MOOSE_BRIDGE:_CollectAuftragCandidatesFromOpsGroup(result, seen, opsgroup)
  if type(opsgroup) ~= "table" then return end
  if type(opsgroup.missionqueue) == "table" then
    for _, auftrag in pairs(opsgroup.missionqueue) do self:_AddAuftragCandidate(result, seen, auftrag, "opsgroup.missionqueue") end
  end
end

function MOOSE_BRIDGE:_PointFromCoordinate(coordinate)
  if not coordinate then return nil end
  local vec3 = self:_SafeCall(coordinate, "GetVec3")
  if vec3 then return vec3 end
  if coordinate.x and coordinate.z then return {x=coordinate.x, y=coordinate.y or 0, z=coordinate.z} end
  return nil
end

function MOOSE_BRIDGE:_TargetObjectId(target_object)
  if not target_object then return nil end
  local target_type = target_object.Type
  local name = target_object.Name
  if not target_type or not name then return nil end
  local prefix_by_type = {
    Group="GROUP",
    Unit="UNIT",
    Static="STATIC",
    Scenery="SCENERY",
    Airbase="AIRBASE",
    Zone="ZONE",
    OpsZone="OPSZONE",
  }
  local prefix = prefix_by_type[target_type]
  if not prefix then return nil end
  return prefix .. ":" .. safe_tostring(name)
end

function MOOSE_BRIDGE:_BuildTargetObjectSnapshot(target, target_object)
  if type(target_object) ~= "table" then return nil end
  local coordinate = self:_SafeCallArg(target, "GetTargetCoordinate", target_object) or target_object.Coordinate
  local point = self:_PointFromCoordinate(coordinate)
  local item = {
    id=target_object.ID,
    type=string_or_nil(target_object.Type),
    name=string_or_nil(target_object.Name),
    object_id=self:_TargetObjectId(target_object),
    status=string_or_nil(target_object.Status),
    n0=target_object.N0,
    n_dead=target_object.Ndead,
    n_destroyed=target_object.Ndestroyed,
    life=target_object.Life,
    life0=target_object.Life0,
  }
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:_BuildTargetSnapshot(target)
  if type(target) ~= "table" then return nil end
  local target_objects = {}
  if type(target.targets) == "table" then
    for _, target_object in pairs(target.targets) do
      local ok, item = pcall(function() return self:_BuildTargetObjectSnapshot(target, target_object) end)
      if ok and item then target_objects[#target_objects + 1] = item end
    end
  end

  local point = self:_SafeCall(target, "GetVec3")
  if not point then point = self:_PointFromCoordinate(self:_SafeCall(target, "GetCoordinate")) end

  local item = {
    object_id=target.uid and ("TARGET:" .. safe_tostring(target.uid)) or nil,
    name=string_or_nil(self:_SafeCall(target, "GetName") or target.name),
    state=string_or_nil(self:_SafeCall(target, "GetState")),
    category=string_or_nil(self:_SafeCall(target, "GetCategory") or target.category),
    heading=self:_SafeCall(target, "GetHeading"),
    life=self:_SafeCall(target, "GetLife") or target.life,
    life0=self:_SafeCall(target, "GetLife0") or target.life0,
    damage=self:_SafeCall(target, "GetDamage"),
    threat_level_max=self:_SafeCall(target, "GetThreatLevelMax") or target.threatlevel0,
    n0=target.N0,
    n_targets0=target.Ntargets0,
    n_destroyed=target.Ndestroyed,
    n_dead=target.Ndead,
    is_destroyed=self:_BoolOrFalse(target.isDestroyed),
    objects=target_objects,
  }
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:_CollectLegionNames(legions)
  local result = {}; local seen = {}
  if type(legions) ~= "table" then return result end
  for key, legion in pairs(legions) do
    local name = self:_ObjectName(legion)
    if not name and type(key) == "string" then name = key end
    append_unique(result, seen, name)
  end
  return result
end

function MOOSE_BRIDGE:_BuildAuftragSnapshotItem(auftrag, source)
  local object_id = self:_AuftragObjectId(auftrag)
  local auftrag_type = self:_SafeCall(auftrag, "GetType") or auftrag.type
  local assigned_group_ids = {}
  local group_seen = {}
  local opsgroups = self:_SafeCall(auftrag, "GetOpsGroups")
  if type(opsgroups) == "table" then
    for _, opsgroup in pairs(opsgroups) do
      local name = self:_OpsName(opsgroup, nil)
      if name then append_unique(assigned_group_ids, group_seen, "OPSGROUP:" .. safe_tostring(name)) end
    end
  end
  return {
    object_id=object_id,
    dcs_name=safe_tostring(auftrag.name or object_id),
    object_type="AUFTRAG",
    category=string_or_nil(auftrag_type),
    source=source,
    auftragsnummer=self:_AuftragNumber(auftrag),
    name=string_or_nil(auftrag.name),
    type=string_or_nil(auftrag_type),
    status=string_or_nil(self:_SafeCall(auftrag, "GetState") or auftrag.status),
    prio=auftrag.prio,
    urgent=self:_BoolOrFalse(auftrag.urgent),
    importance=auftrag.importance,
    t_start=auftrag.Tstart,
    t_stop=auftrag.Tstop,
    duration=auftrag.duration,
    duration_exe=auftrag.durationExe,
    t_started=auftrag.Tstarted,
    t_executing=auftrag.Texecuting,
    t_push=auftrag.Tpush,
    t_over=auftrag.Tover,
    n_assigned=auftrag.Nassigned,
    n_elements=auftrag.Nelements,
    n_dead=auftrag.Ndead,
    n_kills=auftrag.Nkills,
    n_casualties=auftrag.Ncasualties,
    mission_task=string_or_nil(auftrag.missionTask),
    mission_altitude=auftrag.missionAltitude,
    mission_speed=auftrag.missionSpeed,
    mission_range=auftrag.missionRange,
    chief_name=self:_ObjectName(auftrag.chief),
    commander_name=self:_ObjectName(auftrag.commander),
    operation_name=self:_ObjectName(auftrag.operation),
    assigned_group_ids=assigned_group_ids,
    legion_names=self:_CollectLegionNames(auftrag.legions),
    target=self:_BuildTargetSnapshot(auftrag.engageTarget),
  }
end

function MOOSE_BRIDGE:BuildAuftragSnapshot()
  local result = {}; local seen = {}
  for _, opsgroup in pairs(self.RegisteredOpsGroups or {}) do self:_CollectAuftragCandidatesFromOpsGroup(result, seen, opsgroup) end
  if _DATABASE and type(_DATABASE.FLIGHTGROUPS) == "table" then
    for _, opsgroup in pairs(_DATABASE.FLIGHTGROUPS) do self:_CollectAuftragCandidatesFromOpsGroup(result, seen, opsgroup) end
  end
  return result
end

function MOOSE_BRIDGE:RegisterDefaultCommands()
  self:RegisterCommand("message.to_all", function(cmd)
    local p = cmd.params or {}
    MESSAGE:New(p.text or "", p.duration or 10):ToAll()
    return {message="Message sent to all"}
  end)
  self:RegisterCommand("message.to_coalition", function(cmd)
    local p = cmd.params or {}
    local side = coalition_from_name(p.coalition)
    if not side then error("Invalid coalition: " .. safe_tostring(p.coalition)) end
    MESSAGE:New(p.text or "", p.duration or 10):ToCoalition(side)
    return {message="Message sent to coalition", coalition=p.coalition}
  end)
  self:RegisterCommand("smoke.at_point", function(cmd)
    local p = cmd.params or {}; return self:_SmokePoint(self:_PointFromParams(p), p.color)
  end)
  self:RegisterCommand("smoke.object", function(cmd)
    local p = cmd.params or {}; local point = self:_PointForObjectId(p.object_id)
    if not point then error("Could not resolve point for object_id: " .. safe_tostring(p.object_id)) end
    local result = self:_SmokePoint(point, p.color); result.object_id = p.object_id; return result
  end)
  self:RegisterCommand("mark.at_point", function(cmd)
    local p = cmd.params or {}; return self:_MarkPoint(self:_PointFromParams(p), p.text)
  end)
  self:RegisterCommand("mark.object", function(cmd)
    local p = cmd.params or {}; local point = self:_PointForObjectId(p.object_id)
    if not point then error("Could not resolve point for object_id: " .. safe_tostring(p.object_id)) end
    local result = self:_MarkPoint(point, p.text); result.object_id = p.object_id; return result
  end)
  self:RegisterCommand("snapshot.groups", function(cmd)
    local groups = self:BuildGroupSnapshot(); self:SendSnapshot("groups", {groups=groups}); return {kind="groups", count=#groups}
  end)
  self:RegisterCommand("snapshot.units", function(cmd)
    local units = self:BuildUnitSnapshot(); self:SendSnapshot("units", {units=units}); return {kind="units", count=#units}
  end)
  self:RegisterCommand("snapshot.statics", function(cmd)
    local statics = self:BuildStaticSnapshot(); self:SendSnapshot("statics", {statics=statics}); return {kind="statics", count=#statics}
  end)
  self:RegisterCommand("snapshot.airbases", function(cmd)
    local airbases = self:BuildAirbaseSnapshot(); self:SendSnapshot("airbases", {airbases=airbases}); return {kind="airbases", count=#airbases}
  end)
  self:RegisterCommand("snapshot.zones", function(cmd)
    local zones = self:BuildZoneSnapshot(); self:SendSnapshot("zones", {zones=zones}); return {kind="zones", count=#zones}
  end)
  self:RegisterCommand("snapshot.opszones", function(cmd)
    local opszones = self:BuildOpsZoneSnapshot(); self:SendSnapshot("opszones", {opszones=opszones}); return {kind="opszones", count=#opszones}
  end)
  self:RegisterCommand("snapshot.opsgroups", function(cmd)
    local opsgroups = self:BuildOpsGroupSnapshot(); self:SendSnapshot("opsgroups", {opsgroups=opsgroups}); return {kind="opsgroups", count=#opsgroups}
  end)
  self:RegisterCommand("snapshot.auftraege", function(cmd)
    local auftraege = self:BuildAuftragSnapshot(); self:SendSnapshot("auftraege", {auftraege=auftraege}); return {kind="auftraege", count=#auftraege}
  end)
end

function MOOSE_BRIDGE:_DispatchCommand(command)
  local handler = self.CommandHandlers[command.action]
  if not handler then self:SendAck(command, false, nil, "Unsupported action: " .. safe_tostring(command.action)); return end
  local ok, result = pcall(handler, command)
  if ok then self:SendAck(command, true, result or {}, nil) else self:SendAck(command, false, nil, safe_tostring(result)) end
end

function MOOSE_BRIDGE:_HandleLine(line)
  local ok, message = pcall(json.decode, line)
  if not ok then self:_Log("Invalid JSON from Python: " .. safe_tostring(message)); return end
  if message.type == "command" then self:_DispatchCommand(message) else self:_Log("Unsupported inbound message type: " .. safe_tostring(message.type)) end
end

function MOOSE_BRIDGE:_FlushOutgoing()
  while self.Socket and #self.OutQueue > 0 do
    local line = table.remove(self.OutQueue, 1)
    local ok, err = self.Socket:send(line .. "\n")
    if not ok then table.insert(self.OutQueue, 1, line); self:_Disconnect(err); return end
  end
end

function MOOSE_BRIDGE:_ReadIncoming()
  if not self.Socket then return end
  while true do
    local line, err = self.Socket:receive("*l")
    if line then self:_HandleLine(line) elseif err == "timeout" then return else self:_Disconnect(err); return end
  end
end

function MOOSE_BRIDGE:_Tick()
  if not self.Connected then self:_Connect(); return end
  local now = mission_time() or 0
  if now - self.LastHeartbeat >= self.HeartbeatInterval then self.LastHeartbeat = now; self:SendHeartbeat() end
  self:_ReadIncoming()
  self:_FlushOutgoing()
end

return MOOSE_BRIDGE
