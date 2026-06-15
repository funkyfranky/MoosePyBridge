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

function MOOSE_BRIDGE:New(host, port)
  local self = BASE and BASE:Inherit({}, BASE:New()) or {}
  setmetatable(self, { __index = MOOSE_BRIDGE })
  self.Host = host or "127.0.0.1"
  self.Port = port or 50100
  self.Socket = nil
  self.Scheduler = nil
  self.Connected = false
  self.Sequence = 0
  self.OutQueue = {}
  self.CommandHandlers = {}
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

function MOOSE_BRIDGE:_SafeCall(object, method_name)
  if not object or not method_name then return nil end
  local ok_method, method = pcall(function() return object[method_name] end)
  if not ok_method or not method then return nil end
  local ok, value = pcall(function() return method(object) end)
  if ok then return value end
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

function MOOSE_BRIDGE:_BoolOrFalse(value)
  if value == nil then return false end
  return value and true or false
end

function MOOSE_BRIDGE:_NumberOrZero(value)
  if type(value) == "number" then return value end
  return 0
end

function MOOSE_BRIDGE:_IsDcsUnitAlive(unit)
  if not unit then return false end

  local ok_exist, exists = pcall(function() return unit:isExist() end)
  if ok_exist and not exists then return false end

  local ok_life, life = pcall(function() return unit:getLife() end)
  if ok_life and type(life) == "number" then return life > 0 end

  return true
end

function MOOSE_BRIDGE:_IsMooseUnitAlive(unit)
  if not unit then return false end

  local alive = self:_SafeCall(unit, "IsAlive")
  if alive ~= nil then return alive and true or false end

  local dcs_unit = self:_SafeCall(unit, "GetDCSObject")
  if dcs_unit then return self:_IsDcsUnitAlive(dcs_unit) end

  return false
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

function MOOSE_BRIDGE:_CountDcsGroupUnits(group, alive_only)
  local dcs_group = self:_SafeCall(group, "GetDCSObject")
  if not dcs_group then return nil end

  local ok, units = pcall(function() return dcs_group:getUnits() end)
  if not ok or type(units) ~= "table" then return nil end

  local count = 0
  for _, unit in pairs(units) do
    if alive_only then
      if self:_IsDcsUnitAlive(unit) then count = count + 1 end
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

  if alive_only then
    count = self:_SafeCall(group, "CountAliveUnits")
  else
    count = self:_SafeCall(group, "CountUnits")
  end

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

  return {
    object_id = "GROUP:" .. safe_tostring(name),
    dcs_name = safe_tostring(name),
    object_type = "GROUP",
    category = category and safe_tostring(category) or nil,
    coalition = self:_CoalitionToName(coalition_value),
    alive = self:_BoolOrFalse(alive),
    active = self:_BoolOrFalse(active),
    unit_count = self:_NumberOrZero(unit_count),
    alive_unit_count = self:_NumberOrZero(alive_unit_count),
  }
end

function MOOSE_BRIDGE:BuildGroupSnapshot()
  local result = {}

  if not _DATABASE or not _DATABASE.GROUPS then
    return result
  end

  for group_name, group in pairs(_DATABASE.GROUPS) do
    local ok, item = pcall(function()
      return self:_BuildGroupSnapshotItem(group_name, group)
    end)
    if ok and item then
      result[#result + 1] = item
    else
      self:_Log("Failed to snapshot group " .. safe_tostring(group_name) .. ": " .. safe_tostring(item))
    end
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
  self:RegisterCommand("snapshot.groups", function(cmd)
    local groups = self:BuildGroupSnapshot()
    self:SendSnapshot("groups", {groups=groups})
    return {kind="groups", count=#groups}
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
