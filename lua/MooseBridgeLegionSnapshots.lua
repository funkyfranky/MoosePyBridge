--- LEGION snapshot support for MoosePyBridge.
-- Load this after MooseBridge.lua.

if not MOOSE_BRIDGE then error("Load MooseBridge.lua before MooseBridgeLegionSnapshots.lua") end

function MOOSE_BRIDGE:_LegionKind(legion)
  if self:_SafeCall(legion, "IsAirwing") then return "AIRWING" end
  if self:_SafeCall(legion, "IsBrigade") then return "BRIGADE" end
  if self:_SafeCall(legion, "IsFleet") then return "FLEET" end
  if type(legion) == "table" and legion.ClassName then return safe_tostring(legion.ClassName) end
  return "LEGION"
end

function MOOSE_BRIDGE:_LegionName(legion, fallback)
  if not legion then return fallback end
  local name = self:_SafeCall(legion, "GetName") or legion.alias or fallback
  if name then return safe_tostring(name) end
  return nil
end

function MOOSE_BRIDGE:_CohortName(cohort, fallback)
  if not cohort then return fallback end
  local name = self:_SafeCall(cohort, "GetName") or cohort.name or fallback
  if name then return safe_tostring(name) end
  return nil
end

function MOOSE_BRIDGE:_CohortKind(cohort)
  if not cohort then return nil end
  if cohort.isAir then return "AIR" end
  if cohort.isGround then return "GROUND" end
  if cohort.isNaval then return "NAVAL" end
  if type(cohort) == "table" and cohort.ClassName then return safe_tostring(cohort.ClassName) end
  return nil
end

function MOOSE_BRIDGE:_CollectCohortIds(cohorts)
  local result = {}; local seen = {}
  if type(cohorts) ~= "table" then return result end
  for index, cohort in pairs(cohorts) do
    local name = self:_CohortName(cohort, type(index) == "string" and index or nil)
    append_unique(result, seen, name and ("COHORT:" .. name) or nil)
  end
  return result
end

function MOOSE_BRIDGE:_BuildCohortSummary(cohort, index)
  local name = self:_CohortName(cohort, type(index) == "string" and index or nil)
  if not name then return nil end
  return {
    object_id="COHORT:" .. name,
    name=name,
    category=self:_CohortKind(cohort),
    class_name=type(cohort) == "table" and cohort.ClassName or nil,
    is_air=self:_BoolOrFalse(cohort and cohort.isAir),
    is_ground=self:_BoolOrFalse(cohort and cohort.isGround),
    is_naval=self:_BoolOrFalse(cohort and cohort.isNaval),
  }
end

function MOOSE_BRIDGE:_BuildCohortSummaries(cohorts)
  local result = {}
  if type(cohorts) ~= "table" then return result end
  for index, cohort in pairs(cohorts) do
    local ok, item = pcall(function() return self:_BuildCohortSummary(cohort, index) end)
    if ok and item then result[#result + 1] = item end
  end
  return result
end

function MOOSE_BRIDGE:_CollectLegionAuftragIds(missionqueue)
  return self:_CollectAuftragIdsFromQueue(missionqueue)
end

function MOOSE_BRIDGE:_BuildLegionSnapshotItem(name, legion, source)
  local legion_name = self:_LegionName(legion, name)
  if not legion_name then return nil end
  local point = self:_PointFromMooseObject(legion)
  local airbase = self:_SafeCall(legion, "GetAirbase")
  local item = {
    object_id="LEGION:" .. legion_name,
    dcs_name=legion_name,
    object_type="LEGION",
    category=self:_LegionKind(legion),
    class_name=type(legion) == "table" and legion.ClassName or nil,
    source=source,
    name=legion_name,
    alias=string_or_nil(legion and legion.alias),
    state=string_or_nil(self:_SafeCall(legion, "GetState")),
    coalition=self:_CoalitionToName(self:_SafeCall(legion, "GetCoalition")),
    coalition_name=string_or_nil(self:_SafeCall(legion, "GetCoalitionName")),
    airbase_name=string_or_nil(self:_SafeCall(legion, "GetAirbaseName") or self:_ObjectName(airbase)),
    cohort_ids=self:_CollectCohortIds(legion and legion.cohorts),
    cohorts=self:_BuildCohortSummaries(legion and legion.cohorts),
    n_cohorts=self:_CountTable((legion and legion.cohorts) or {}),
    auftrag_queue_ids=self:_CollectLegionAuftragIds(legion and legion.missionqueue),
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
