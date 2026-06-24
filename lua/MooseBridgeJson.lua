--- Minimal JSON helper for the MOOSE Bridge V1 prototype.
-- This is deliberately small and covers the V1 command/ack/heartbeat/snapshot payloads.

MOOSE_BRIDGE_JSON = MOOSE_BRIDGE_JSON or {}
local json = MOOSE_BRIDGE_JSON

local function escape(value)
  value = tostring(value or "")
  value = value:gsub('\\', '\\\\')
  value = value:gsub('"', '\\"')
  value = value:gsub('\n', '\\n')
  value = value:gsub('\r', '\\r')
  value = value:gsub('\t', '\\t')
  return value
end

local function is_array(value)
  if type(value) ~= "table" then
    return false
  end

  local max_index = 0
  local count = 0

  for key, _ in pairs(value) do
    if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then
      return false
    end
    if key > max_index then
      max_index = key
    end
    count = count + 1
  end

  return count == max_index
end

local function encode_value(value)
  local t = type(value)

  if value == nil then
    return "null"
  elseif t == "boolean" then
    return value and "true" or "false"
  elseif t == "number" then
    return tostring(value)
  elseif t == "string" then
    return '"' .. escape(value) .. '"'
  elseif t == "table" then
    local parts = {}

    if is_array(value) then
      for index = 1, #value do
        parts[#parts + 1] = encode_value(value[index])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    end

    for k, v in pairs(value) do
      parts[#parts + 1] = '"' .. escape(k) .. '":' .. encode_value(v)
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end

  return '"' .. escape(value) .. '"'
end

function json.encode(value)
  return encode_value(value)
end

local function unescape(value)
  value = value or ""
  value = value:gsub('\\n', '\n')
  value = value:gsub('\\r', '\r')
  value = value:gsub('\\t', '\t')
  value = value:gsub('\\"', '"')
  value = value:gsub('\\\\', '\\')
  return value
end

local function read_string_field(text, name)
  local pattern = '"' .. name .. '"%s*:%s*"(.-)"'
  local value = text:match(pattern)
  return unescape(value)
end

local function read_number_field(text, name)
  local pattern = '"' .. name .. '"%s*:%s*([%-%d%.]+)'
  local value = text:match(pattern)
  if value then
    return tonumber(value)
  end
  return nil
end

local function read_boolean_field(text, name)
  local true_pattern = '"' .. name .. '"%s*:%s*true'
  local false_pattern = '"' .. name .. '"%s*:%s*false'
  if text:match(true_pattern) then return true end
  if text:match(false_pattern) then return false end
  return nil
end

function json.decode(text)
  local result = {}
  result.version = read_number_field(text, "version")
  result.type = read_string_field(text, "type")
  result.id = read_string_field(text, "id")
  result.source = read_string_field(text, "source")
  result.mode = read_string_field(text, "mode")
  result.action = read_string_field(text, "action")
  result.params = {}

  local params_text = text:match('"params"%s*:%s*{(.-)}')
  if params_text then
    result.params.coalition = read_string_field(params_text, "coalition")
    result.params.text = read_string_field(params_text, "text")
    result.params.duration = read_number_field(params_text, "duration")
    result.params.object_id = read_string_field(params_text, "object_id")
    result.params.color = read_string_field(params_text, "color")
    result.params.x = read_number_field(params_text, "x")
    result.params.y = read_number_field(params_text, "y")
    result.params.z = read_number_field(params_text, "z")

    -- AUFTRAG advisory/application command fields.
    result.params.legion_id = read_string_field(params_text, "legion_id")
    result.params.cohort_id = read_string_field(params_text, "cohort_id")
    result.params.target = read_string_field(params_text, "target")
    result.params.altitude_ft = read_number_field(params_text, "altitude_ft")
    result.params.selected_payload_uid = read_number_field(params_text, "selected_payload_uid") or read_string_field(params_text, "selected_payload_uid")
    result.params.mission_type = read_string_field(params_text, "mission_type")
    result.params.constructor = read_string_field(params_text, "constructor")
    result.params.apply = read_boolean_field(params_text, "apply")

    -- AUFTRAG:BOMBING fields.
    result.params.engage_weapon_type = read_number_field(params_text, "engage_weapon_type")
    result.params.EngageWeaponType = read_number_field(params_text, "EngageWeaponType")
    result.params.divebomb = read_boolean_field(params_text, "divebomb")

    -- AUFTRAG:ARTY fields.
    result.params.nshots = read_number_field(params_text, "nshots")
    result.params.Nshots = read_number_field(params_text, "Nshots")
    result.params.radius_m = read_number_field(params_text, "radius_m")
    result.params.radius = read_number_field(params_text, "radius")
    result.params.Radius = read_number_field(params_text, "Radius")
  end

  return result
end

return json
