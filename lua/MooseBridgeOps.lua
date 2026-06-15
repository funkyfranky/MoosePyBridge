--- OPS extension for MooseBridge.
-- Load this after MooseBridge.lua and before creating the bridge instance.

if not MOOSE_BRIDGE then error("Load MooseBridge.lua before MooseBridgeOps.lua") end

function MOOSE_BRIDGE:_EnsureOpsRegistries()
  self.RegisteredOpsZones = self.RegisteredOpsZones or {}
  self.RegisteredOpsGroups = self.RegisteredOpsGroups or {}
end

function MOOSE_BRIDGE:RegisterOpsZone(opszone, name)
  self:_EnsureOpsRegistries()
  if not opszone then return self end
  local zone_name = name or self:_SafeCall(opszone, "GetName") or opszone.name or opszone.Name
  if zone_name then self.RegisteredOpsZones[tostring(zone_name)] = opszone end
  return self
end

function MOOSE_BRIDGE:RegisterOpsZones(opszones)
  if type(opszones) ~= "table" then return self end
  for name, opszone in pairs(opszones) do self:RegisterOpsZone(opszone, name) end
  return self
end

function MOOSE_BRIDGE:RegisterOpsGroup(opsgroup, name)
  self:_EnsureOpsRegistries()
  if not opsgroup then return self end
  local group_name = name or self:_SafeCall(opsgroup, "GetName") or self:_SafeCall(opsgroup, "GetGroupName") or opsgroup.name or opsgroup.Name
  if group_name then self.RegisteredOpsGroups[tostring(group_name)] = opsgroup end
  return self
end

function MOOSE_BRIDGE:RegisterOpsGroups(opsgroups)
  if type(opsgroups) ~= "table" then return self end
  for name, opsgroup in pairs(opsgroups) do self:RegisterOpsGroup(opsgroup, name) end
  return self
end

function MOOSE_BRIDGE:_OpsClassName(object, fallback)
  if type(object) == "table" then
    if object.ClassName then return tostring(object.ClassName) end
    if object.classname then return tostring(object.classname) end
  end
  return fallback
end

function MOOSE_BRIDGE:_OpsName(object, fallback)
  return self:_SafeCall(object, "GetName") or self:_SafeCall(object, "GetGroupName") or fallback or object.Name or object.name
end

function MOOSE_BRIDGE:_OpsStatus(object)
  return self:_SafeCall(object, "GetStatus") or self:_SafeCall(object, "GetState") or self:_SafeCall(object, "GetStateName") or object.Status or object.status or object.State or object.state
end

function MOOSE_BRIDGE:_OpsCoalition(object)
  local coalition_value = self:_SafeCall(object, "GetCoalition") or object.Coalition or object.coalition
  return self:_CoalitionToName(coalition_value)
end

function MOOSE_BRIDGE:_AddOpsDatabaseCandidates(result, seen, table_name, builder, source)
  if not _DATABASE or type(_DATABASE[table_name]) ~= "table" then return end
  for name, object in pairs(_DATABASE[table_name]) do
    local ok, item = pcall(function() return builder(self, name, object, source or table_name) end)
    if ok and item and item.object_id and not seen[item.object_id] then
      result[#result + 1] = item
      seen[item.object_id] = true
    end
  end
end

function MOOSE_BRIDGE:_BuildOpsZoneSnapshotItem(zone_name, opszone, source)
  local name = self:_OpsName(opszone, zone_name)
  local class_name = self:_OpsClassName(opszone, "OPSZONE")
  local point = self:_PointFromMooseObject(opszone)
  local radius = self:_SafeCall(opszone, "GetRadius") or opszone.Radius or opszone.radius
  local status = self:_OpsStatus(opszone)

  local item = {
    object_id = "OPSZONE:" .. safe_tostring(name),
    dcs_name = safe_tostring(name),
    object_type = "OPSZONE",
    category = class_name,
    source = source,
    radius = radius,
    status = status and safe_tostring(status) or nil,
    coalition = self:_OpsCoalition(opszone),
  }

  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:_BuildOpsGroupSnapshotItem(group_name, opsgroup, source)
  local name = self:_OpsName(opsgroup, group_name)
  local class_name = self:_OpsClassName(opsgroup, "OPSGROUP")
  local point = self:_PointFromMooseObject(opsgroup)
  local status = self:_OpsStatus(opsgroup)
  local alive = self:_SafeCall(opsgroup, "IsAlive")
  local active = self:_SafeCall(opsgroup, "IsActive")
  local dcs_group_name = self:_SafeCall(opsgroup, "GetGroupName") or opsgroup.GroupName or opsgroup.groupname

  local item = {
    object_id = "OPSGROUP:" .. safe_tostring(name),
    dcs_name = safe_tostring(name),
    object_type = "OPSGROUP",
    category = class_name,
    source = source,
    group_name = dcs_group_name and safe_tostring(dcs_group_name) or nil,
    status = status and safe_tostring(status) or nil,
    coalition = self:_OpsCoalition(opsgroup),
    alive = self:_BoolOrFalse(alive),
    active = self:_BoolOrFalse(active),
  }

  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:BuildOpsZoneSnapshot()
  self:_EnsureOpsRegistries()
  local result = {}
  local seen = {}

  for name, opszone in pairs(self.RegisteredOpsZones) do
    local ok, item = pcall(function() return self:_BuildOpsZoneSnapshotItem(name, opszone, "registered") end)
    if ok and item and item.object_id then result[#result + 1] = item; seen[item.object_id] = true end
  end

  self:_AddOpsDatabaseCandidates(result, seen, "OPSZONES", MOOSE_BRIDGE._BuildOpsZoneSnapshotItem, "database.OPSZONES")
  self:_AddOpsDatabaseCandidates(result, seen, "OPS_ZONE", MOOSE_BRIDGE._BuildOpsZoneSnapshotItem, "database.OPS_ZONE")
  self:_AddOpsDatabaseCandidates(result, seen, "OPERATIONALZONES", MOOSE_BRIDGE._BuildOpsZoneSnapshotItem, "database.OPERATIONALZONES")

  return result
end

function MOOSE_BRIDGE:BuildOpsGroupSnapshot()
  self:_EnsureOpsRegistries()
  local result = {}
  local seen = {}

  for name, opsgroup in pairs(self.RegisteredOpsGroups) do
    local ok, item = pcall(function() return self:_BuildOpsGroupSnapshotItem(name, opsgroup, "registered") end)
    if ok and item and item.object_id then result[#result + 1] = item; seen[item.object_id] = true end
  end

  self:_AddOpsDatabaseCandidates(result, seen, "OPSGROUPS", MOOSE_BRIDGE._BuildOpsGroupSnapshotItem, "database.OPSGROUPS")
  self:_AddOpsDatabaseCandidates(result, seen, "FLIGHTGROUPS", MOOSE_BRIDGE._BuildOpsGroupSnapshotItem, "database.FLIGHTGROUPS")
  self:_AddOpsDatabaseCandidates(result, seen, "ARMYGROUPS", MOOSE_BRIDGE._BuildOpsGroupSnapshotItem, "database.ARMYGROUPS")
  self:_AddOpsDatabaseCandidates(result, seen, "NAVYGROUPS", MOOSE_BRIDGE._BuildOpsGroupSnapshotItem, "database.NAVYGROUPS")

  return result
end

function MOOSE_BRIDGE:RegisterOpsBridgeCommands()
  self:RegisterCommand("snapshot.opszones", function(cmd)
    local opszones = self:BuildOpsZoneSnapshot()
    self:SendSnapshot("opszones", {opszones=opszones})
    return {kind="opszones", count=#opszones}
  end)
  self:RegisterCommand("snapshot.opsgroups", function(cmd)
    local opsgroups = self:BuildOpsGroupSnapshot()
    self:SendSnapshot("opsgroups", {opsgroups=opsgroups})
    return {kind="opsgroups", count=#opsgroups}
  end)
  return self
end

local original_new = MOOSE_BRIDGE.New
function MOOSE_BRIDGE:New(...)
  local bridge = original_new(self, ...)
  bridge:_EnsureOpsRegistries()
  bridge:RegisterOpsBridgeCommands()
  return bridge
end

return MOOSE_BRIDGE
