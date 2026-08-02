--- DCS world event forwarding for MOOSE_BRIDGE.
--
-- Load after MooseBridge.lua and before constructing/starting the bridge.
-- DCS events are normalized here; Python never needs to understand the raw
-- world event table or MOOSE EVENTDATA implementation details.

if not MOOSE_BRIDGE then error("Load MooseBridge.lua before MooseBridgeDcsEventsExtension.lua") end

--- Cache current DCS ownership for all known MOOSE AIRBASE objects.
-- The DCS BaseCaptured event already exposes the new owner, so the cache is
-- needed to include the previous owner in the normalized bridge event.
function MOOSE_BRIDGE:_CacheAirbaseCoalitions()
  self.AirbaseCoalitions = self.AirbaseCoalitions or {}
  if not _DATABASE or type(_DATABASE.AIRBASES) ~= "table" then return self end
  for airbase_name, airbase in pairs(_DATABASE.AIRBASES) do
    local ok, result = pcall(function()
      local name = self:_SafeCall(airbase, "GetName") or airbase.AirbaseName or airbase_name
      local owner = self:_CoalitionToName(self:_SafeCall(airbase, "GetCoalition"))
      return name and {object_id="AIRBASE:" .. tostring(name), coalition=owner} or nil
    end)
    if ok and result and result.object_id then
      self.AirbaseCoalitions[result.object_id] = result.coalition
    elseif not ok then
      self:_Log("Failed to cache airbase " .. tostring(airbase_name) .. ": " .. tostring(result))
    end
  end
  return self
end

--- Resolve the authoritative MOOSE AIRBASE wrapper from an EVENTDATA object.
function MOOSE_BRIDGE:_AirbaseFromCapturedEvent(EventData)
  if type(EventData) ~= "table" then return nil, nil end
  local place = EventData.Place
  local name = EventData.PlaceName
  if not name and place then
    name = self:_SafeCall(place, "GetName")
  end
  if not name and EventData.place then
    local ok, value = pcall(function() return EventData.place:getName() end)
    if ok then name = value end
  end
  if not name then return nil, nil end

  local airbase = type(place) == "table" and place or nil
  if _DATABASE and type(_DATABASE.AIRBASES) == "table" then
    airbase = _DATABASE.AIRBASES[name] or airbase
  end
  if not airbase and AIRBASE and AIRBASE.FindByName then
    local ok, value = pcall(function() return AIRBASE:FindByName(name) end)
    if ok then airbase = value end
  end
  return airbase, tostring(name)
end

--- Subscribe to selected low-frequency DCS events through MOOSE.
function MOOSE_BRIDGE:_StartDcsEventForwarding()
  if self.DcsEventForwardingStarted then return self end
  if not EVENTS or not EVENTS.BaseCaptured or not self.HandleEvent then
    self:_Log("DCS BaseCaptured event forwarding unavailable")
    return self
  end
  self:_CacheAirbaseCoalitions()
  self:HandleEvent(EVENTS.BaseCaptured)
  self.DcsEventForwardingStarted = true
  self:_Log("DCS BaseCaptured event forwarding enabled")
  return self
end

--- Unsubscribe from DCS events owned by this bridge instance.
function MOOSE_BRIDGE:_StopDcsEventForwarding()
  if self.DcsEventForwardingStarted and EVENTS and EVENTS.BaseCaptured and self.UnHandleEvent then
    self:UnHandleEvent(EVENTS.BaseCaptured)
  end
  self.DcsEventForwardingStarted = false
  return self
end

--- Forward DCS S_EVENT_BASE_CAPTURED as airbase.coalition_changed.
-- @param Core.Event#EVENTDATA EventData MOOSE-normalized DCS event data.
function MOOSE_BRIDGE:OnEventBaseCaptured(EventData)
  local ok, err = pcall(function()
    local airbase, airbase_name = self:_AirbaseFromCapturedEvent(EventData)
    if not airbase or not airbase_name then
      error("BaseCaptured event has no resolvable AIRBASE")
    end

    local item = self:_BuildAirbaseSnapshotItem(airbase_name, airbase)
    if not item or not item.object_id then
      error("Could not build AIRBASE snapshot for " .. tostring(airbase_name))
    end

    self.AirbaseCoalitions = self.AirbaseCoalitions or {}
    local previous = self.AirbaseCoalitions[item.object_id]
    local current = item.coalition
    self.AirbaseCoalitions[item.object_id] = current

    if previous ~= current then
      self:SendEvent("airbase.coalition_changed", {
        dcs_event_id=EventData.id,
        dcs_event_name="S_EVENT_BASE_CAPTURED",
        dcs_event_time=EventData.time,
        airbase_id=item.object_id,
        previous_coalition=previous,
        coalition=current,
        capturing_unit_id=EventData.IniUnitName and ("UNIT:" .. tostring(EventData.IniUnitName)) or nil,
        capturing_group_id=EventData.IniGroupName and ("GROUP:" .. tostring(EventData.IniGroupName)) or nil,
        capturing_coalition=self:_CoalitionToName(EventData.IniCoalition),
        capturing_unit_type=EventData.IniTypeName and tostring(EventData.IniTypeName) or nil,
        airbase=item,
      })
    end
  end)
  if not ok then
    self:_Log("Failed to forward BaseCaptured event: " .. tostring(err))
  end
end
