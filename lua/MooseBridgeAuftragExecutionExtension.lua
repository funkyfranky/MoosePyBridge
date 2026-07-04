-- Optional approval-gated AUFTRAG execution extension for MOOSE Bridge.
--
-- Load after MooseBridge.lua and before creating the bridge instance. This file
-- exposes narrow, explicit AUFTRAG creation commands. Python should only call
-- them after an advisory recommendation has passed all hard filters and the user
-- explicitly requested execution.

if not MOOSE_BRIDGE then error("Load MooseBridge.lua before MooseBridgeAuftragExecutionExtension.lua") end

local bridge_unpack = table.unpack or unpack

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

function MOOSE_BRIDGE:_ResolveOpsGroupById(opsgroup_id)
  local prefix, name = bridge_split_object_id(opsgroup_id)
  if prefix ~= "OPSGROUP" or not name then return nil, "Invalid OPSGROUP id " .. bridge_safe_tostring(opsgroup_id) end

  if type(self.RegisteredOpsGroups) == "table" then
    for key, opsgroup in pairs(self.RegisteredOpsGroups) do
      local opsgroup_name = self:_OpsName(opsgroup, type(key) == "string" and key or nil)
      if opsgroup_name == name then return opsgroup, nil end
    end
  end

  if _DATABASE and type(_DATABASE.FLIGHTGROUPS) == "table" then
    for key, opsgroup in pairs(_DATABASE.FLIGHTGROUPS) do
      local opsgroup_name = self:_OpsName(opsgroup, type(key) == "string" and key or nil)
      if opsgroup_name == name then return opsgroup, nil end
    end
  end

  return nil, "OPSGROUP not found: " .. name
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

function MOOSE_BRIDGE:_BuildOpsZoneSnapshotItem(zone_name, opszone, source)
  local name = self:_OpsName(opszone, zone_name)
  if not name then return nil end
  local point = self:_PointFromMooseObject(opszone)
  local state = self:_OpsState(opszone)
  local item = {
    object_id="OPSZONE:"..bridge_safe_tostring(name),
    dcs_name=bridge_safe_tostring(name),
    object_type="OPSZONE",
    category=self:_OpsClassName(opszone, "OPSZONE"),
    source=source,
    name=bridge_safe_tostring(name),
    zone_name=opszone and opszone.zoneName and tostring(opszone.zoneName) or nil,
    zone_type=opszone and opszone.zoneType and tostring(opszone.zoneType) or nil,
    zone_radius=opszone and opszone.zoneRadius or nil,
    state=state and tostring(state) or nil,
    owner_current_name=self:_CoalitionToName(opszone and opszone.ownerCurrent),
    owner_previous_name=self:_CoalitionToName(opszone and opszone.ownerPrevious),
    is_contested=self:_BoolOrFalse(opszone and opszone.isContested),
    n_red=opszone and opszone.Nred or 0,
    n_blue=opszone and opszone.Nblu or 0,
    n_neutral=opszone and opszone.Nnut or 0,
    threat_red=opszone and opszone.Tred or 0,
    threat_blue=opszone and opszone.Tblu or 0,
    threat_neutral=opszone and opszone.Tnut or 0,
    airbase_name=opszone and opszone.airbaseName and tostring(opszone.airbaseName) or nil,
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
    opsgroup_id=bridge_optional_string_param(p.opsgroup_id) or bridge_optional_string_param(legacy_params.opsgroup_id),
    cohort_id=bridge_optional_string_param(p.cohort_id) or bridge_optional_string_param(legacy_params.cohort_id),
    target_id=bridge_optional_string_param(p.target) or bridge_optional_string_param(legacy_params.target),
    zone_id=bridge_optional_string_param(p.zone) or bridge_optional_string_param(p.zone_id) or bridge_optional_string_param(legacy_params.zone) or bridge_optional_string_param(legacy_params.zone_id),
    coordinate_id=bridge_optional_string_param(p.coordinate) or bridge_optional_string_param(p.coordinate_id) or bridge_optional_string_param(legacy_params.coordinate) or bridge_optional_string_param(legacy_params.coordinate_id),
    x=p.x or legacy_params.x,
    y=p.y or legacy_params.y,
    z=p.z or legacy_params.z,
    altitude_ft=p.altitude_ft or legacy_params.altitude_ft,
    selected_payload_uid=p.selected_payload_uid or legacy_params.selected_payload_uid,
    engage_weapon_type=p.engage_weapon_type or p.EngageWeaponType or legacy_params.engage_weapon_type or legacy_params.EngageWeaponType,
    divebomb=p.divebomb,
    nshots=p.nshots or p.Nshots or legacy_params.nshots or legacy_params.Nshots,
    radius_m=p.radius_m or p.radius or p.Radius or legacy_params.radius_m or legacy_params.radius or legacy_params.Radius,
    carpet_length_m=p.carpet_length_m or p.carpet_length or p.CarpetLength or legacy_params.carpet_length_m or legacy_params.carpet_length or legacy_params.CarpetLength,
    speed_kts=p.speed_kts or p.speed or p.Speed or legacy_params.speed_kts or legacy_params.speed or legacy_params.Speed,
    heading_deg=p.heading_deg or p.heading or p.Heading or legacy_params.heading_deg or legacy_params.heading or legacy_params.Heading,
    leg_nm=p.leg_nm or p.leg or p.Leg or legacy_params.leg_nm or legacy_params.leg or legacy_params.Leg,
    target_types=p.target_types or p.TargetTypes or legacy_params.target_types or legacy_params.TargetTypes,
    range_max_nm=p.range_max_nm or p.range_max or p.RangeMax or legacy_params.range_max_nm or legacy_params.range_max or legacy_params.RangeMax,
    no_engage_zones=p.no_engage_zones or p.no_engage_zone or p.NoEngageZones or legacy_params.no_engage_zones or legacy_params.no_engage_zone or legacy_params.NoEngageZones,
    frequency_mhz=p.frequency_mhz or p.frequency or p.Frequency or legacy_params.frequency_mhz or legacy_params.frequency or legacy_params.Frequency,
    modulation=p.modulation or p.Modulation or legacy_params.modulation or legacy_params.Modulation,
    designation=bridge_optional_string_param(p.designation) or bridge_optional_string_param(p.Designation) or bridge_optional_string_param(legacy_params.designation) or bridge_optional_string_param(legacy_params.Designation),
    data_link=p.data_link,
  }
  if inputs.divebomb == nil then inputs.divebomb = legacy_params.divebomb end
  if inputs.data_link == nil then inputs.data_link = p.datalink end
  if inputs.data_link == nil then inputs.data_link = p.DataLink end
  if inputs.data_link == nil then inputs.data_link = legacy_params.data_link end
  if inputs.data_link == nil then inputs.data_link = legacy_params.datalink end
  if inputs.data_link == nil then inputs.data_link = legacy_params.DataLink end

  if inputs.legion_id and inputs.opsgroup_id then error("Specify only one of legion_id or opsgroup_id; " .. bridge_param_debug(cmd, p)) end
  if not inputs.legion_id and not inputs.opsgroup_id then error("Missing legion_id or opsgroup_id; " .. bridge_param_debug(cmd, p)) end

  if inputs.legion_id then
    local legion, legion_err = self:_ResolveLegionById(inputs.legion_id)
    if not legion then error(legion_err) end
    inputs.legion = legion
  end

  if inputs.opsgroup_id then
    local opsgroup, opsgroup_err = self:_ResolveOpsGroupById(inputs.opsgroup_id)
    if not opsgroup then error(opsgroup_err) end
    inputs.opsgroup = opsgroup
  end

  return inputs
end

function MOOSE_BRIDGE:_ResolveObjectAuftragTarget(inputs)
  if not inputs.target_id then return nil, "Missing target" end
  return self:_ResolveAuftragTargetById(inputs.target_id)
end

function MOOSE_BRIDGE:_ResolveGroupAuftragTarget(inputs)
  if not inputs.target_id then return nil, "Missing target" end
  local prefix = bridge_split_object_id(inputs.target_id)
  if prefix ~= "GROUP" then return nil, "FACA target must be GROUP:<name>" end
  return self:_ResolveAuftragTargetById(inputs.target_id)
end

function MOOSE_BRIDGE:_ResolveGroupOrUnitAuftragTarget(inputs)
  if not inputs.target_id then return nil, "Missing target" end
  local prefix = bridge_split_object_id(inputs.target_id)
  if prefix ~= "GROUP" and prefix ~= "UNIT" then return nil, "Target must be GROUP:<name> or UNIT:<name>" end
  return self:_ResolveAuftragTargetById(inputs.target_id)
end

function MOOSE_BRIDGE:_ResolveAirbaseAuftragTarget(inputs)
  if not inputs.target_id then return nil, "Missing target" end
  local prefix, name = bridge_split_object_id(inputs.target_id)
  if prefix ~= "AIRBASE" then return nil, "BOMBRUNWAY target must be AIRBASE:<name>" end

  if AIRBASE and AIRBASE.FindByName then
    local ok, airbase = pcall(function() return AIRBASE:FindByName(name) end)
    if ok and airbase then return airbase, nil end
  end

  return nil, "AIRBASE target not found: " .. bridge_safe_tostring(name)
end

function MOOSE_BRIDGE:_ResolveBombingTarget(inputs)
  return self:_ResolveCoordinateAuftragTarget(inputs)
end

function MOOSE_BRIDGE:_ResolveBombCarpetTarget(inputs)
  if inputs.target_id then
    local prefix = bridge_split_object_id(inputs.target_id)
    if prefix ~= "GROUP" and prefix ~= "UNIT" and prefix ~= "STATIC" then
      return nil, "BOMBCARPET target must be GROUP:<name>, UNIT:<name>, STATIC:<name> or direct x/z coordinates"
    end
  end
  return self:_ResolveCoordinateAuftragTarget(inputs)
end

function MOOSE_BRIDGE:_ResolveArtyTarget(inputs)
  return self:_ResolveCoordinateAuftragTarget(inputs)
end

function MOOSE_BRIDGE:_ResolveStrikeTarget(inputs)
  return self:_ResolveCoordinateAuftragTarget(inputs)
end

function MOOSE_BRIDGE:_ResolveOrbitTarget(inputs)
  return self:_ResolveCoordinateAuftragTarget(inputs)
end

function MOOSE_BRIDGE:_ResolveZonePatrolZone(inputs)
  if not inputs.zone_id then return nil, "Missing zone" end
  local ok, zone = pcall(function() return self:_ZoneForDrawObjectId(inputs.zone_id) end)
  if ok and zone then return zone, nil end
  return nil, bridge_safe_tostring(zone)
end

function MOOSE_BRIDGE:_ResolveZonePatrolCoordinate(inputs)
  if inputs.coordinate_id then
    return self:_CoordinateTargetFromObjectId(inputs.coordinate_id)
  end
  if inputs.x ~= nil or inputs.z ~= nil then
    return self:_ResolveCoordinateFromInputs(inputs)
  end
  return nil, nil
end

function MOOSE_BRIDGE:_NormalizeTargetTypes(value)
  if type(value) == "table" then return value end
  if type(value) ~= "string" or value == "" then return nil end

  local result = {}
  for item in string.gmatch(value, "([^,]+)") do
    item = item:gsub("^%s+", ""):gsub("%s+$", "")
    if item ~= "" then result[#result + 1] = item end
  end
  if #result > 0 then return result end
  return nil
end

function MOOSE_BRIDGE:_NormalizeStringList(value)
  if type(value) == "table" then return value end
  if type(value) ~= "string" or value == "" then return nil end

  local result = {}
  for item in string.gmatch(value, "([^,]+)") do
    item = item:gsub("^%s+", ""):gsub("%s+$", "")
    if item ~= "" then result[#result + 1] = item end
  end
  if #result > 0 then return result end
  return nil
end

function MOOSE_BRIDGE:_BuildNoEngageZoneSet(value)
  local zone_ids = self:_NormalizeStringList(value)
  if not zone_ids then return nil end
  if not SET_ZONE or not SET_ZONE.New then error("SET_ZONE:New is not available") end

  local set_zone = SET_ZONE:New()
  for _, zone_id in ipairs(zone_ids) do
    local ok_zone, zone = pcall(function() return self:_ZoneForDrawObjectId(zone_id) end)
    if not ok_zone or not zone then error("NoEngage zone not found: " .. bridge_safe_tostring(zone_id)) end

    if type(set_zone.AddZone) == "function" then
      set_zone:AddZone(zone)
    elseif type(set_zone.Add) == "function" then
      set_zone:Add(zone)
    elseif type(set_zone.AddObject) == "function" then
      set_zone:AddObject(zone)
    else
      error("SET_ZONE add method is not available")
    end
  end

  return set_zone
end

function MOOSE_BRIDGE:_AddAuftragToLegion(auftrag, inputs)
  if not auftrag then error("AUFTRAG constructor returned nil") end
  self:_RegisterAuftragEvents(auftrag, inputs)
  self:_SendAuftragStatusEvent(auftrag, inputs, "Planned")
  local add_ok, add_result = pcall(function() return inputs.legion:AddMission(auftrag) end)
  if not add_ok then error("LEGION:AddMission failed: " .. bridge_safe_tostring(add_result)) end
  self:_TrackAuftragReference(auftrag)
  return auftrag
end

function MOOSE_BRIDGE:_AddAuftragToOpsGroup(auftrag, inputs)
  if not auftrag then error("AUFTRAG constructor returned nil") end
  if type(inputs.opsgroup.AddMission) ~= "function" then error("OPSGROUP:AddMission is not available") end
  self:_RegisterAuftragEvents(auftrag, inputs)
  self:_SendAuftragStatusEvent(auftrag, inputs, "Planned")
  local add_ok, add_result = pcall(function() return inputs.opsgroup:AddMission(auftrag) end)
  if not add_ok then error("OPSGROUP:AddMission failed: " .. bridge_safe_tostring(add_result)) end
  self:_TrackAuftragReference(auftrag)
  return auftrag
end

function MOOSE_BRIDGE:_SendAuftragStatusEvent(auftrag, inputs, fsm_event, From, Event, To)
  if type(auftrag) ~= "table" then return end
  local object_id = self:_AuftragObjectId(auftrag)
  local ok, err = pcall(function()
    self:SendEvent("auftrag.status", {
      auftrag_id=object_id,
      auftragsnummer=self:_AuftragNumber(auftrag),
      auftrag_type=self:_SafeCall(auftrag, "GetType") or auftrag.type,
      status=self:_SafeCall(auftrag, "GetState") or self:_SafeCall(auftrag, "GetStatus") or To,
      fsm_event=fsm_event,
      from=From,
      fsm_event_name=Event,
      to=To,
      legion_id=inputs and inputs.legion_id or nil,
      opsgroup_id=inputs and inputs.opsgroup_id or nil,
      cohort_id=inputs and inputs.cohort_id or nil,
      target=inputs and (inputs.target_id or inputs.zone_id) or nil,
    })
  end)
  if not ok and env and env.error then env.error("MooseBridge AUFTRAG status event failed: " .. bridge_safe_tostring(err)) end
end

function MOOSE_BRIDGE:_SendAuftragEvaluatedEvent(auftrag, inputs, From, Event, To, Summary)
  if type(auftrag) ~= "table" then return end
  local summary = bridge_auftrag_summary(Summary)
  local object_id = self:_AuftragObjectId(auftrag)
  local ok, err = pcall(function()
    self:SendEvent("auftrag.evaluated", {
      auftrag_id=object_id,
      auftragsnummer=self:_AuftragNumber(auftrag),
      auftrag_type=self:_SafeCall(auftrag, "GetType") or auftrag.type,
      status=self:_SafeCall(auftrag, "GetState") or self:_SafeCall(auftrag, "GetStatus") or To,
      fsm_event="Evaluated",
      from=From,
      fsm_event_name=Event,
      to=To,
      legion_id=inputs and inputs.legion_id or nil,
      opsgroup_id=inputs and inputs.opsgroup_id or nil,
      cohort_id=inputs and inputs.cohort_id or nil,
      target=inputs and (inputs.target_id or inputs.zone_id) or nil,
      summary=summary,
      auftrag={
        object_id=object_id,
        auftragsnummer=self:_AuftragNumber(auftrag),
        type=self:_SafeCall(auftrag, "GetType") or auftrag.type,
        status=self:_SafeCall(auftrag, "GetState") or self:_SafeCall(auftrag, "GetStatus") or To,
        summary_available=summary ~= nil,
        summary=summary,
      },
    })
  end)
  if not ok and env and env.error then env.error("MooseBridge OnAfterEvaluated send failed: " .. bridge_safe_tostring(err)) end
end

function MOOSE_BRIDGE:_RegisterAuftragEvents(auftrag, inputs)
  if type(auftrag) ~= "table" then return end
  if auftrag.MooseBridgeEvaluatedEventRegistered then return end

  local bridge = self
  auftrag.MooseBridgeEvaluatedEventRegistered = true
  local sent_status_events = {}

  local function register_after_event(method_event, output_event)
    output_event = output_event or method_event
    local method_name = "OnAfter" .. method_event
    local previous_handler = auftrag[method_name]
    auftrag[method_name] = function(auftrag_object, From, Event, To, ...)
      local extra = {...}
      if type(previous_handler) == "function" then
        pcall(function() previous_handler(auftrag_object, From, Event, To, bridge_unpack(extra)) end)
      end

      if output_event == "Evaluated" then
        bridge:_SendAuftragEvaluatedEvent(auftrag_object, inputs, From, Event, To, extra[1])
        return
      end

      if sent_status_events[output_event] then return end
      sent_status_events[output_event] = true
      bridge:_SendAuftragStatusEvent(auftrag_object, inputs, output_event, From, Event, To)
    end
  end

  register_after_event("Queued")
  register_after_event("Requested")
  register_after_event("Scheduled")
  register_after_event("Started")
  register_after_event("Executing")
  register_after_event("Done")
  register_after_event("Cancel")
  register_after_event("Evaluated")
end

function MOOSE_BRIDGE:_AddAuftragToTarget(auftrag, inputs)
  if inputs.opsgroup then return self:_AddAuftragToOpsGroup(auftrag, inputs) end
  return self:_AddAuftragToLegion(auftrag, inputs)
end

function MOOSE_BRIDGE:_BuildAuftragCommandResult(action, auftrag, inputs)
  return {
    action=action,
    legion_id=inputs.legion_id,
    opsgroup_id=inputs.opsgroup_id,
    cohort_id=inputs.cohort_id,
    target=inputs.target_id,
    zone=inputs.zone_id,
    coordinate=inputs.coordinate_id,
    x=inputs.x,
    y=inputs.y,
    z=inputs.z,
    altitude_ft=inputs.altitude_ft,
    engage_weapon_type=inputs.engage_weapon_type,
    divebomb=inputs.divebomb,
    nshots=inputs.nshots,
    radius_m=inputs.radius_m,
    carpet_length_m=inputs.carpet_length_m,
    speed_kts=inputs.speed_kts,
    heading_deg=inputs.heading_deg,
    leg_nm=inputs.leg_nm,
    range_max_nm=inputs.range_max_nm,
    no_engage_zones=inputs.no_engage_zones,
    frequency_mhz=inputs.frequency_mhz,
    modulation=inputs.modulation,
    designation=inputs.designation,
    data_link=inputs.data_link,
    target_types=inputs.target_types,
    selected_payload_uid=inputs.selected_payload_uid,
    auftrag_id=self:_AuftragObjectId(auftrag),
    auftragsnummer=self:_AuftragNumber(auftrag),
    auftrag_type=self:_SafeCall(auftrag, "GetType") or auftrag.type,
    added=true,
  }
end

function MOOSE_BRIDGE:_CreateZonePatrolAuftrag(cmd, action, constructor_name)
  local inputs = self:_CommonAuftragCommandInputs(cmd)
  local zone, zone_err = self:_ResolveZonePatrolZone(inputs)
  if not zone then error(zone_err) end

  local coordinate, coordinate_err = self:_ResolveZonePatrolCoordinate(inputs)
  if coordinate_err then error(coordinate_err) end

  if not AUFTRAG or type(AUFTRAG[constructor_name]) ~= "function" then error("AUFTRAG:" .. constructor_name .. " is not available") end

  local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
  local speed_kts = inputs.speed_kts and tonumber(inputs.speed_kts) or nil
  local heading_deg = inputs.heading_deg and tonumber(inputs.heading_deg) or nil
  local leg_nm = inputs.leg_nm and tonumber(inputs.leg_nm) or nil
  local target_types = self:_NormalizeTargetTypes(inputs.target_types)
  inputs.target_types = target_types

  local auftrag = AUFTRAG[constructor_name](AUFTRAG, zone, altitude_ft, speed_kts, coordinate, heading_deg, leg_nm, target_types)

  self:_AddAuftragToTarget(auftrag, inputs)
  return self:_BuildAuftragCommandResult(action, auftrag, inputs)
end

function MOOSE_BRIDGE:_CreateCasEnhancedAuftrag(cmd)
  local inputs = self:_CommonAuftragCommandInputs(cmd)
  local zone, zone_err = self:_ResolveZonePatrolZone(inputs)
  if not zone then error(zone_err) end

  if not AUFTRAG or not AUFTRAG.NewCASENHANCED then error("AUFTRAG:NewCASENHANCED is not available") end

  local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
  local speed_kts = inputs.speed_kts and tonumber(inputs.speed_kts) or nil
  local range_max_nm = inputs.range_max_nm and tonumber(inputs.range_max_nm) or nil
  local no_engage_zone_set = self:_BuildNoEngageZoneSet(inputs.no_engage_zones)
  local target_types = self:_NormalizeTargetTypes(inputs.target_types)
  inputs.no_engage_zones = self:_NormalizeStringList(inputs.no_engage_zones)
  inputs.target_types = target_types

  local auftrag = AUFTRAG:NewCASENHANCED(zone, altitude_ft, speed_kts, range_max_nm, no_engage_zone_set, target_types)

  self:_AddAuftragToTarget(auftrag, inputs)
  return self:_BuildAuftragCommandResult("auftrag.create_casenhanced", auftrag, inputs)
end

function MOOSE_BRIDGE:_CreateFacAuftrag(cmd)
  local inputs = self:_CommonAuftragCommandInputs(cmd)
  local zone, zone_err = self:_ResolveZonePatrolZone(inputs)
  if not zone then error(zone_err) end

  if not AUFTRAG or not AUFTRAG.NewFAC then error("AUFTRAG:NewFAC is not available") end

  local speed_kts = inputs.speed_kts and tonumber(inputs.speed_kts) or nil
  local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
  local frequency_mhz = inputs.frequency_mhz and tonumber(inputs.frequency_mhz) or nil
  local modulation = inputs.modulation and tonumber(inputs.modulation) or nil

  local auftrag = AUFTRAG:NewFAC(zone, speed_kts, altitude_ft, frequency_mhz, modulation)

  self:_AddAuftragToTarget(auftrag, inputs)
  return self:_BuildAuftragCommandResult("auftrag.create_fac", auftrag, inputs)
end

function MOOSE_BRIDGE:_CreateFacaAuftrag(cmd)
  local inputs = self:_CommonAuftragCommandInputs(cmd)
  local target, target_err = self:_ResolveGroupAuftragTarget(inputs)
  if not target then error(target_err) end

  if not AUFTRAG or not AUFTRAG.NewFACA then error("AUFTRAG:NewFACA is not available") end

  local data_link = bridge_bool_param(inputs.data_link)
  local frequency_mhz = inputs.frequency_mhz and tonumber(inputs.frequency_mhz) or nil
  local modulation = inputs.modulation and tonumber(inputs.modulation) or nil

  local auftrag = AUFTRAG:NewFACA(target, inputs.designation, data_link, frequency_mhz, modulation)

  self:_AddAuftragToTarget(auftrag, inputs)
  return self:_BuildAuftragCommandResult("auftrag.create_faca", auftrag, inputs)
end

function MOOSE_BRIDGE:_CreateSeadAuftrag(cmd)
  local inputs = self:_CommonAuftragCommandInputs(cmd)
  local target, target_err = self:_ResolveGroupOrUnitAuftragTarget(inputs)
  if not target then error(target_err) end

  if not AUFTRAG or not AUFTRAG.NewSEAD then error("AUFTRAG:NewSEAD is not available") end

  local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
  local auftrag = AUFTRAG:NewSEAD(target, altitude_ft)

  self:_AddAuftragToTarget(auftrag, inputs)
  return self:_BuildAuftragCommandResult("auftrag.create_sead", auftrag, inputs)
end

function MOOSE_BRIDGE:_CreateStrikeAuftrag(cmd)
  local inputs = self:_CommonAuftragCommandInputs(cmd)
  local target, target_err = self:_ResolveStrikeTarget(inputs)
  if not target then error(target_err) end

  if not AUFTRAG or not AUFTRAG.NewSTRIKE then error("AUFTRAG:NewSTRIKE is not available") end

  local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
  local engage_weapon_type = inputs.engage_weapon_type and tonumber(inputs.engage_weapon_type) or nil
  local auftrag = AUFTRAG:NewSTRIKE(target, altitude_ft, engage_weapon_type)

  self:_AddAuftragToTarget(auftrag, inputs)
  return self:_BuildAuftragCommandResult("auftrag.create_strike", auftrag, inputs)
end

function MOOSE_BRIDGE:_CreateBombRunwayAuftrag(cmd)
  local inputs = self:_CommonAuftragCommandInputs(cmd)
  local target, target_err = self:_ResolveAirbaseAuftragTarget(inputs)
  if not target then error(target_err) end

  if not AUFTRAG or not AUFTRAG.NewBOMBRUNWAY then error("AUFTRAG:NewBOMBRUNWAY is not available") end

  local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
  local auftrag = AUFTRAG:NewBOMBRUNWAY(target, altitude_ft)

  self:_AddAuftragToTarget(auftrag, inputs)
  return self:_BuildAuftragCommandResult("auftrag.create_bombrunway", auftrag, inputs)
end

function MOOSE_BRIDGE:_CreateBombCarpetAuftrag(cmd)
  local inputs = self:_CommonAuftragCommandInputs(cmd)
  local target, target_err = self:_ResolveBombCarpetTarget(inputs)
  if not target then error(target_err) end

  if not AUFTRAG or not AUFTRAG.NewBOMBCARPET then error("AUFTRAG:NewBOMBCARPET is not available") end

  local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
  local carpet_length_m = inputs.carpet_length_m and tonumber(inputs.carpet_length_m) or nil
  local auftrag = AUFTRAG:NewBOMBCARPET(target, altitude_ft, carpet_length_m)

  self:_AddAuftragToTarget(auftrag, inputs)
  return self:_BuildAuftragCommandResult("auftrag.create_bombcarpet", auftrag, inputs)
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

    self:_AddAuftragToTarget(auftrag, inputs)
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

    self:_AddAuftragToTarget(auftrag, inputs)
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

    self:_AddAuftragToTarget(auftrag, inputs)
    return self:_BuildAuftragCommandResult("auftrag.create_arty", auftrag, inputs)
  end)

  self:RegisterCommand("auftrag.create_orbit", function(cmd)
    local inputs = self:_CommonAuftragCommandInputs(cmd)
    local target, target_err = self:_ResolveOrbitTarget(inputs)
    if not target then error(target_err) end

    if not AUFTRAG or not AUFTRAG.NewORBIT then error("AUFTRAG:NewORBIT is not available") end

    local altitude_ft = inputs.altitude_ft and tonumber(inputs.altitude_ft) or nil
    local speed_kts = inputs.speed_kts and tonumber(inputs.speed_kts) or nil
    local heading_deg = inputs.heading_deg and tonumber(inputs.heading_deg) or nil
    local leg_nm = inputs.leg_nm and tonumber(inputs.leg_nm) or nil
    local auftrag = AUFTRAG:NewORBIT(target, altitude_ft, speed_kts, heading_deg, leg_nm)

    self:_AddAuftragToTarget(auftrag, inputs)
    return self:_BuildAuftragCommandResult("auftrag.create_orbit", auftrag, inputs)
  end)

  self:RegisterCommand("auftrag.create_cap", function(cmd)
    return self:_CreateZonePatrolAuftrag(cmd, "auftrag.create_cap", "NewCAP")
  end)

  self:RegisterCommand("auftrag.create_cas", function(cmd)
    return self:_CreateZonePatrolAuftrag(cmd, "auftrag.create_cas", "NewCAS")
  end)

  self:RegisterCommand("auftrag.create_casenhanced", function(cmd)
    return self:_CreateCasEnhancedAuftrag(cmd)
  end)

  self:RegisterCommand("auftrag.create_fac", function(cmd)
    return self:_CreateFacAuftrag(cmd)
  end)

  self:RegisterCommand("auftrag.create_faca", function(cmd)
    return self:_CreateFacaAuftrag(cmd)
  end)

  self:RegisterCommand("auftrag.create_sead", function(cmd)
    return self:_CreateSeadAuftrag(cmd)
  end)

  self:RegisterCommand("auftrag.create_strike", function(cmd)
    return self:_CreateStrikeAuftrag(cmd)
  end)

  self:RegisterCommand("auftrag.create_bombrunway", function(cmd)
    return self:_CreateBombRunwayAuftrag(cmd)
  end)

  self:RegisterCommand("auftrag.create_bombcarpet", function(cmd)
    return self:_CreateBombCarpetAuftrag(cmd)
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
