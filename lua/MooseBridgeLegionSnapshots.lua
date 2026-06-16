--- Optional LEGION snapshot extension for MoosePyBridge.
-- Load this after MooseBridge.lua if AIRWING/BRIGADE/FLEET snapshots are needed.

if not MOOSE_BRIDGE then error("Load MooseBridge.lua before MooseBridgeLegionSnapshots.lua") end

function MOOSE_BRIDGE:_LegionKind(legion)
  if self:_SafeCall(legion, "IsAirwing") then return "AIRWING" end
  if self:_SafeCall(legion, "IsBrigade") then return "BRIGADE" end
  if self:_SafeCall(legion, "IsFleet") then return "FLEET" end
  if type(legion) == "table" and legion.ClassName then return tostring(legion.ClassName) end
  return "LEGION"
end

function MOOSE_BRIDGE:_CollectCohortIds(legion)
  local result = {}
  local seen = {}
  local cohorts = legion and (legion.cohorts or legion.Cohorts)
  if type(cohorts) ~= "table" then return result end
  for key, cohort in pairs(cohorts) do
    local name = self:_ObjectName(cohort)
    if not name and type(key) == "string" then name = key end
    append_unique(result, seen, name and ("COHORT:" .. tostring(name)) or nil)
  end
  return result
end

function MOOSE_BRIDGE:_BuildLegionSnapshotItem(name, legion, source)
  local legion_name = self:_ObjectName(legion) or name
  local point = self:_PointFromMooseObject(legion)
  local item = {
    object_id="LEGION:" .. safe_tostring(legion_name),
    dcs_name=safe_tostring(legion_name),
    object_type="LEGION",
    category=self:_LegionKind(legion),
    class_name=type(legion) == "table" and legion.ClassName or nil,
    source=source,
    name=safe_tostring(legion_name),
    state=string_or_nil(self:_SafeCall(legion, "GetState") or self:_SafeCall(legion, "GetStateName") or legion.State or legion.state),
    coalition=self:_OpsCoalition(legion),
    operational=self:_BoolOrFalse(self:_SafeCall(legion, "IsOperational") or legion.isOperational or legion.operational),
    cohort_ids=self:_CollectCohortIds(legion),
    n_cohorts=self:_CountTable((legion and (legion.cohorts or legion.Cohorts)) or {}),
    n_assets=legion and legion.Nassets or nil,
    n_assigned=legion and legion.Nassigned or nil,
    n_available=legion and legion.Navailable or nil,
    n_alive=legion and legion.Nalive or nil,
  }
  if point then item.x = point.x; item.y = point.y; item.z = point.z end
  return item
end

function MOOSE_BRIDGE:BuildLegionSnapshot()
  local result = {}
  local seen = {}
  if _DATABASE and type(_DATABASE.LEGIONS) == "table" then
    for name, legion in pairs(_DATABASE.LEGIONS) do
      local ok, item = pcall(function() return self:_BuildLegionSnapshotItem(name, legion, "database.LEGIONS") end)
      if ok and item and item.object_id and not seen[item.object_id] then
        result[#result + 1] = item
        seen[item.object_id] = true
      end
    end
  end
  return result
end

local previous_register_default_commands = MOOSE_BRIDGE.RegisterDefaultCommands
function MOOSE_BRIDGE:RegisterDefaultCommands()
  previous_register_default_commands(self)
  self:RegisterCommand("snapshot.legions", function(cmd)
    local legions = self:BuildLegionSnapshot()
    self:SendSnapshot("legions", {legions=legions})
    return {kind="legions", count=#legions}
  end)
end

return MOOSE_BRIDGE
