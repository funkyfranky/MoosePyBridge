-- Optional approval-gated AUFTRAG execution extension for MOOSE Bridge.
--
-- Load after MooseBridge.lua and before creating the bridge instance. This file
-- intentionally starts with one narrow, explicit command: auftrag.create_bai.
-- Python should only call it after an advisory recommendation has passed all hard
-- filters and the user explicitly requested execution.

if not MOOSE_BRIDGE then error("Load MooseBridge.lua before MooseBridgeAuftragExecutionExtension.lua") end

local function bridge_split_object_id(object_id)
  if type(object_id) ~= "string" then return nil, nil end
  local prefix, name = string.match(object_id, "^([^:]+):(.+)$")
  if not prefix or not name then return nil, nil end
  return string.upper(prefix), name
end

local function bridge_safe_tostring(value)
  if value == nil then return "nil" end
  return tostring(value)
end

local function bridge_table_keys(value)
  if type(value) ~= "table" then return "<" .. type(value) .. ">" end
  local keys = {}
  for key, _ in pairs(value) do keys[#keys + 1] = tostring(key) end
  table.sort(keys)
  return table.concat(keys, ",")
end

local function bridge_param_debug(command, params)
  return "command_keys=[" .. bridge_table_keys(command) .. "] " ..
         "params_keys=[" .. bridge_table_keys(command and command.params) .. "] " ..
         "payload_keys=[" .. bridge_table_keys(command and command.payload) .. "] " ..
         "resolved_keys=[" .. bridge_table_keys(params) .. "]"
end

local function bridge_optional_bool(value)
  if value == nil then return nil end
  return value and true or false
end

local function bridge_auftrag_now()
  if timer and timer.getAbsTime then return timer.getAbsTime() end
  if timer and timer.getTime then return timer.getTime() end
  return nil
end

local function bridge_auftrag_summary(summary)
  if type(summary) ~= "table" then return nil end
  return {
    success=bridge_optional_bool(summary.success),
    Ntargets0=summary.Ntargets0,
    Ntargets=summary.Ntargets,
    damage=summary.damage,
    Ndestroyed=summary.Ndestroyed,
    Nkills=summary.Nkills,
    Nelements=summary.Nelements,
    targetLife=summary.targetLife,
    category=summary.category,
    Ncasualties=summary.Ncasualties,
  }
end

local function bridge_auftrag_ready_to_evaluate(auftrag)
  local tover = auftrag and auftrag.Tover or nil
  local dtevaluate = auftrag and auftrag.dTevaluate or nil
  local now = bridge_auftrag_now()
  if tover and dtevaluate and now then return now - tover >= dtevaluate end
  return false
end

function MOOSE_BRIDGE:_CommandParams(command)
  if type(command) ~= "table" then return {} end
  if type(command.params) == "table" then return command.params end
  if type(command.payload) == "table" then
    if type(command.payload.params) == "table" then return command.payload.params end
    return command.payload
  end
  return {}
end

function MOOSE_BRIDGE:_TrackAuftragReference(auftrag)
  if type(auftrag) ~= "table" then return self end
  local object_id = self:_AuftragObjectId(auftrag)
  if not object_id then return self end
  self.TrackedAuftraege = self.TrackedAuftraege or {}
  self.TrackedAuftraege[object_id] = auftrag
  return self
end

function MOOSE_BRIDGE:_ResolveLegionById(legion_id)
  local prefix, name = bridge_split_object_id(legion_id)
  if prefix ~= "LEGION" or not name then return nil, "Invalid LEGION id " .. bridge_safe_tostring(legion_id) end

  if _DATABASE then
    local found = self:_SafeCallArg(_DATABASE, "FindLegion", name)
    if found then return found, nil end

    if type(_DATABASE.LEGIONS) == "table" then
      for key, legion in pairs(_DATABASE.LEGIONS) do
        local legion_name = self:_ObjectName(legion) or (type(key) == "string" and key or nil)
        if legion_name == name then return legion, nil end
      end
    end
  end

  return nil, "LEGION not found: " .. name
end

function MOOSE_BRIDGE:_ResolveAuftragTargetById(target_id)
  local prefix, name = bridge_split_object_id(target_id)
  if not prefix or not name then return nil, "Invalid target id " .. bridge_safe_tostring(target_id) end

  if prefix == "GROUP" then
    if GROUP and GROUP.FindByName then
      local target = GROUP:FindByName(name)
      if target then return target, nil end
    end
    if Group and Group.getByName then
      local dcs_group = Group.getByName(name)
      if dcs_group then return dcs_group, nil end
    end
    return nil, "GROUP target not found: " .. name
  end

  if prefix == "UNIT" then
    if UNIT and UNIT.FindByName then
      local target = UNIT:FindByName(name)
      if target then return target, nil end
    end
    if Unit and Unit.getByName then
      local dcs_unit = Unit.getByName(name)
      if dcs_unit then return dcs_unit, nil end
    end
    return nil, "UNIT target not found: " .. name
  end

  if prefix == "STATIC" then
    if STATIC and STATIC.FindByName then
      local target = STATIC:FindByName(name)
      if target then return target, nil end
    end
    if StaticObject and StaticObject.getByName then
      local dcs_static = StaticObject.getByName(name)
      if dcs_static then return dcs_static, nil end
    end
    return nil, "STATIC target not found: " .. name
  end

  return nil, "Unsupported BAI target type: " .. prefix
end

function MOOSE_BRIDGE:RegisterAuftragExecutionCommands()
  self:RegisterCommand("auftrag.create_bai", function(cmd)
    local p = self:_CommandParams(cmd)
    local legacy_params = type(p.params) == "table" and p.params or {}
    local legion_id = p.legion_id or legacy_params.legion_id
    local cohort_id = p.cohort_id or legacy_params.cohort_id
    local target_id = p.target or legacy_params.target
    local altitude_ft = p.altitude_ft or legacy_params.altitude_ft
    local selected_payload_uid = p.selected_payload_uid or legacy_params.selected_payload_uid

    if not legion_id then error("Missing legion_id; " .. bridge_param_debug(cmd, p)) end
    if not target_id then error("Missing target; " .. bridge_param_debug(cmd, p)) end

    local legion, legion_err = self:_ResolveLegionById(legion_id)
    if not legion then error(legion_err) end

    local target, target_err = self:_ResolveAuftragTargetById(target_id)
    if not target then error(target_err) end

    if not AUFTRAG or not AUFTRAG.NewBAI then error("AUFTRAG:NewBAI is not available") end

    local auftrag = nil
    if altitude_ft ~= nil then
      auftrag = AUFTRAG:NewBAI(target, tonumber(altitude_ft))
    else
      auftrag = AUFTRAG:NewBAI(target)
    end
    if not auftrag then error("AUFTRAG:NewBAI returned nil") end

    local add_ok, add_result = pcall(function() return legion:AddMission(auftrag) end)
    if not add_ok then error("LEGION:AddMission failed: " .. bridge_safe_tostring(add_result)) end

    self:_TrackAuftragReference(auftrag)

    local auftrag_id = self:_AuftragObjectId(auftrag)
    return {
      action="auftrag.create_bai",
      legion_id=legion_id,
      cohort_id=cohort_id,
      target=target_id,
      altitude_ft=altitude_ft,
      selected_payload_uid=selected_payload_uid,
      auftrag_id=auftrag_id,
      auftragsnummer=self:_AuftragNumber(auftrag),
      auftrag_type=self:_SafeCall(auftrag, "GetType") or auftrag.type,
      added=true,
    }
  end)
end

local _moose_bridge_base_add_auftrag_candidate = MOOSE_BRIDGE._AddAuftragCandidate

function MOOSE_BRIDGE:_AddAuftragCandidate(result, seen, auftrag, source)
  self:_TrackAuftragReference(auftrag)
  return _moose_bridge_base_add_auftrag_candidate(self, result, seen, auftrag, source)
end

local _moose_bridge_base_build_auftrag_snapshot_item = MOOSE_BRIDGE._BuildAuftragSnapshotItem

function MOOSE_BRIDGE:_BuildAuftragSnapshotItem(auftrag, source)
  local item = _moose_bridge_base_build_auftrag_snapshot_item(self, auftrag, source)
  if type(item) ~= "table" or type(auftrag) ~= "table" then return item end

  local summary = bridge_auftrag_summary(auftrag.summary)
  item.d_tevaluate = auftrag.dTevaluate
  item.ready_to_evaluate = bridge_auftrag_ready_to_evaluate(auftrag)
  item.summary_available = summary ~= nil
  item.summary = summary

  return item
end

function MOOSE_BRIDGE:_CollectAuftragCandidatesFromLegion(result, seen, legion)
  if type(legion) ~= "table" then return end
  local queues = {
    legion.missionqueue,
    legion.missions,
    legion.auftraege,
    legion.missionQueue,
  }
  for _, queue in ipairs(queues) do
    if type(queue) == "table" then
      for _, auftrag in pairs(queue) do self:_AddAuftragCandidate(result, seen, auftrag, "legion.missionqueue") end
    end
  end
end

function MOOSE_BRIDGE:_CollectAuftragCandidatesFromTracked(result, seen)
  if type(self.TrackedAuftraege) ~= "table" then return end
  for object_id, auftrag in pairs(self.TrackedAuftraege) do
    if type(auftrag) == "table" then
      self:_AddAuftragCandidate(result, seen, auftrag, "bridge.tracked")
    else
      self.TrackedAuftraege[object_id] = nil
    end
  end
end

local _moose_bridge_base_build_auftrag_snapshot = MOOSE_BRIDGE.BuildAuftragSnapshot

function MOOSE_BRIDGE:BuildAuftragSnapshot()
  local result = _moose_bridge_base_build_auftrag_snapshot(self) or {}
  local seen = {}
  for _, item in ipairs(result) do
    if item.object_id then seen[item.object_id] = true end
  end

  if _DATABASE and type(_DATABASE.LEGIONS) == "table" then
    for _, legion in pairs(_DATABASE.LEGIONS) do
      self:_CollectAuftragCandidatesFromLegion(result, seen, legion)
    end
  end

  self:_CollectAuftragCandidatesFromTracked(result, seen)

  return result
end

local _moose_bridge_base_register_default_commands = MOOSE_BRIDGE.RegisterDefaultCommands

function MOOSE_BRIDGE:RegisterDefaultCommands()
  _moose_bridge_base_register_default_commands(self)
  self:RegisterAuftragExecutionCommands()
end
