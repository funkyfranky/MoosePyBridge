-- Optional approval-gated AUFTRAG execution extension for MOOSE Bridge.
--
-- Load after MooseBridge.lua and before creating the bridge instance. This file
-- exposes narrow, explicit AUFTRAG creation commands. Python should only call
-- them after an advisory recommendation has passed all hard filters and the user
-- explicitly requested execution.

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

local function bridge_optional_string_param(value)
  if type(value) ~= "string" then return nil end
  local trimmed = string.match(value, "^%s*(.-)%s*$")
  if trimmed == "" or string.lower(trimmed) == "null" then return nil end
  return trimmed
end

local function bridge_optional_bool(value)
  if value == nil then return nil end
  return value and true or false
end

local function bridge_bool_param(value)
  if value == nil then return nil end
  if type(value) == "boolean" then return value end
  local text = string.lower(tostring(value))
  if text == "true" or text == "1" or text == "yes" or text == "y" then return true end
  if text == "false" or text == "0" or text == "no" or text == "n" then return false end
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

  return nil, "Unsupported AUFTRAG target type: " .. prefix
end

function MOOSE_BRIDGE:_ResolveCoordinateFromInputs(inputs)
  local x = inputs.x ~= nil and tonumber(inputs.x) or nil
  local z = inputs.z ~= nil and tonumber(inputs.z) or nil
  local y = inputs.y ~= nil and tonumber(inputs.y) or 0

  if not x or not z then return nil, "Coordinate target requires numeric x and z" end
  if not COORDINATE or not COORDINATE.New then return nil, "COORDINATE:New is not available" end

  return COORDINATE:New(x, y, z), nil
end

function MOOSE_BRIDGE:_PointForOpsZoneName(name)
  local opszone = self.RegisteredOpsZones and self.RegisteredOpsZones[name] or nil
  if not opszone and _DATABASE and type(_DATABASE.OPSZONES) == "table" then opszone = _DATABASE.OPSZONES[name] end
  if not opszone then return nil end
  return self:_PointFromMooseObject(opszone)
end

function MOOSE_BRIDGE:_CoordinateTargetFromObjectId(target_id)
  local prefix, name = bridge_split_object_id(target_id)
  if not prefix or not name then return nil, "Invalid coordinate target id " .. bridge_safe_tostring(target_id) end

  local point = nil
  if prefix == "OPSZONE" then
    point = self:_PointForOpsZoneName(name)
  elseif prefix == "SCENERY" then
    return nil, "SCENERY coordinate target resolution is not available yet"
  else
    local ok, value = pcall(function() return self:_PointForObjectId(target_id) end)
    if ok then point = value else return nil, bridge_safe_tostring(value) end
  end

  if not point then return nil, "Coordinate target point not found for " .. bridge_safe_tostring(target_id) end

  local ok_coordinate, coordinate = pcall(function() return self:_CoordinateFromPoint(point) end)
  if ok_coordinate then return coordinate, nil end
  return nil, bridge_safe_tostring(coordinate)
end

function MOOSE_BRIDGE:_ResolveCoordinateAuftragTarget(inputs)
  if inputs.target_id then
    return self:_CoordinateTargetFromObjectId(inputs.target_id)
  end
  return self:_ResolveCoordinateFromInputs(inputs)
end

function MOOSE_BRIDGE:_CommonAuftragCommandInputs(cmd)
  local p = self:_CommandParams(cmd)
  local legacy_params = type(p.params) == "table" and p.params or {}
  local inputs = {
    params=p,
    legion_id=bridge_optional_string_param(p.legion_id) or bridge_optional_string_param(legacy_params.legion_id),
    cohort_id=bridge_optional_string_param(p.cohort_id) or bridge_optional_string_param(legacy_params.cohort_id),
    target_id=bridge_optional_string_param(p.target) or bridge_optional_string_param(legacy_params.target),
    x=p.x or legacy_params.x,
    y=p.y or legacy_params.y,
    z=p.z or legacy_params.z,
    altitude_ft=p.altitude_ft or legacy_params.altitude_ft,
    selected_payload_uid=p.selected_payload_uid or legacy_params.selected_payload_uid,
    engage_weapon_type=p.engage_weapon_type or p.EngageWeaponType or legacy_params.engage_weapon_type or legacy_params.EngageWeaponType,
    divebomb=p.divebomb,
    nshots=p.nshots or p.Nshots or legacy_params.nshots or legacy_params.Nshots,
    radius_m=p.radius_m or p.radius or p.Radius or legacy_params.radius_m or legacy_params.radius or legacy_params.Radius,
  }
  if inputs.divebomb == nil then inputs.divebomb = legacy_params.divebomb end

  if not inputs.legion_id then error("Missing legion_id; " .. bridge_param_debug(cmd, p)) end

  local legion, legion_err = self:_ResolveLegionById(inputs.legion_id)
  if not legion then error(legion_err) end
  inputs.legion = legion

  return inputs
end

function MOOSE_BRIDGE:_ResolveObjectAuftragTarget(inputs)
  if not inputs.target_id then return nil, "Missing target" end
  return self:_ResolveAuftragTargetById(inputs.target_id)
end

function MOOSE_BRIDGE:_ResolveBombingTarget(inputs)
  return self:_ResolveCoordinateAuftragTarget(inputs)
end

function MOOSE_BRIDGE:_ResolveArtyTarget(inputs)
  return self:_ResolveCoordinateAuftragTarget(inputs)
end

function MOOSE_BRIDGE:_AddAuftragToLegion(auftrag, inputs)
  if not auftrag then error("AUFTRAG constructor returned nil") end
  local add_ok, add_result = pcall(function() return inputs.legion:AddMission(auftrag) end)
  if not add_ok then error("LEGION:AddMission failed: " .. bridge_safe_tostring(add_result)) end
  self:_TrackAuftragReference(auftrag)
  return auftrag
end

function MOOSE_BRIDGE:_BuildAuftragCommandResult(action, auftrag, inputs)
  return {
    action=action,
    legion_id=inputs.legion_id,
    cohort_id=inputs.cohort_id,
    target=inputs.target_id,
    x=inputs.x,
    y=inputs.y,
    z=inputs.z,
    altitude_ft=inputs.altitude_ft,
    engage_weapon_type=inputs.engage_weapon_type,
    divebomb=inputs.divebomb,
    nshots=inputs.nshots,
    radius_m=inputs.radius_m,
    selected_payload_uid=inputs.selected_payload_uid,
    auftrag_id=self:_AuftragObjectId(auftrag),
    auftragsnummer=self:_AuftragNumber(auftrag),
    auftrag_type=self:_SafeCall(auftrag, "GetType") or auftrag.type,
    added=true,
  }
end

function MOOSE_BRIDGE:RegisterAuftragExecutionCommands()
  self:RegisterCommand("auftrag.create_bai", function(cmd)
    local inputs = self:_CommonAuftragCommandInputs(cmd)
    local target, target_err = self:_ResolveObjectAuftragTarget(inputs)
    if not target then error(target_err) end

    if not AUFTRAG or not AUFTRAG.NewBAI then error("AUFTRAG:NewBAI is not available") end

    local auftrag = nil
    if inputs.altitude_ft ~= nil then
      auftrag = AUFTRAG:NewBAI(target, tonumber(inputs.altitude_ft))
    else
      auftrag = AUFTRAG:NewBAI(target)
    end

    self:_AddAuftragToLegion(auftrag, inputs)
    return self:_BuildAuftragCommandResult("auftrag.create_bai", auftrag, inputs)
  end)

  self:RegisterCommand("auftrag.create_bombing", function(cmd)
    local inputs = self:_CommonAuftragCommandInputs(cmd)
    local target, target_err = self:_ResolveBombingTarget(inputs)
    if not target then error(target_err) end

    if not AUFTRAG or not AUFTRAG.NewBOMBING then error("AUFTRAG:NewBOMBING is not available") end

    local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
    local engage_weapon_type = inputs.engage_weapon_type and tonumber(inputs.engage_weapon_type) or nil
    local divebomb = bridge_bool_param(inputs.divebomb)

    local auftrag = AUFTRAG:NewBOMBING(target, altitude_ft, engage_weapon_type, divebomb)

    self:_AddAuftragToLegion(auftrag, inputs)
    return self:_BuildAuftragCommandResult("auftrag.create_bombing", auftrag, inputs)
  end)

  self:RegisterCommand("auftrag.create_arty", function(cmd)
    local inputs = self:_CommonAuftragCommandInputs(cmd)
    local target, target_err = self:_ResolveArtyTarget(inputs)
    if not target then error(target_err) end

    if not AUFTRAG or not AUFTRAG.NewARTY then error("AUFTRAG:NewARTY is not available") end

    local nshots = inputs.nshots and tonumber(inputs.nshots) or nil
    local radius_m = inputs.radius_m and tonumber(inputs.radius_m) or nil
    local auftrag = AUFTRAG:NewARTY(target, nshots, radius_m)

    self:_AddAuftragToLegion(auftrag, inputs)
    return self:_BuildAuftragCommandResult("auftrag.create_arty", auftrag, inputs)
  end)
end

local _moose_bridge_base_add_auftrag_candidate = MOOSE_BRIDGE._AddAuftragCandidate

function MOOSE_BRIDGE:_AddAuftragCandidate(result, seen, auftrag, source)
  self:_TrackAuftragReference(auftrag)
  return _moose_bridge_base_add_auftrag_candidate(self, result, seen, auftrag, source)
end

local _moose_bridge_base_build_cohort_snapshot_item = MOOSE_BRIDGE._BuildCohortSnapshotItem

function MOOSE_BRIDGE:_BuildCohortSnapshotItem(cohort_name, cohort, source)
  local item = _moose_bridge_base_build_cohort_snapshot_item(self, cohort_name, cohort, source)
  if type(item) ~= "table" or type(cohort) ~= "table" then return item end

  local mission_range = self:_SafeCall(cohort, "GetMissionRange") or cohort.missionRange or cohort.MissionRange
  item.mission_range_m = mission_range

  return item
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
