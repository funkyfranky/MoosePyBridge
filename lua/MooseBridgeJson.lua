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
  if value == nil then return nil end
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

local function extract_object_text(text, name)
  local pattern = '"' .. name .. '"%s*:%s*{'
  local start_pos, end_pos = text:find(pattern)
  if not end_pos then return nil end

  local depth = 1
  local in_string = false
  local escaped = false
  local index = end_pos + 1

  while index <= #text do
    local char = text:sub(index, index)
    if in_string then
      if escaped then
        escaped = false
      elseif char == "\\" then
        escaped = true
      elseif char == '"' then
        in_string = false
      end
    else
      if char == '"' then
        in_string = true
      elseif char == "{" then
        depth = depth + 1
      elseif char == "}" then
        depth = depth - 1
        if depth == 0 then
          return text:sub(end_pos + 1, index - 1)
        end
      end
    end
    index = index + 1
  end

  return nil
end

local function decode_scalar_value(value)
  value = value:gsub("^%s+", ""):gsub("%s+$", "")
  if value == "true" then return true end
  if value == "false" then return false end
  if value == "null" then return nil end

  if value:sub(1, 1) == "[" and value:sub(-1) == "]" then
    local result = {}
    local inner = value:sub(2, -2)
    local index = 1
    local element_start = 1
    local in_string = false
    local escaped = false

    while index <= #inner + 1 do
      local char = inner:sub(index, index)
      local at_end = index > #inner
      if in_string then
        if escaped then
          escaped = false
        elseif char == "\\" then
          escaped = true
        elseif char == '"' then
          in_string = false
        end
      else
        if char == '"' then
          in_string = true
        elseif char == "," or at_end then
          local raw_element = inner:sub(element_start, index - 1)
          result[#result + 1] = decode_scalar_value(raw_element)
          element_start = index + 1
        end
      end
      index = index + 1
    end

    return result
  end

  local string_value = value:match('^"(.*)"$')
  if string_value ~= nil then return unescape(string_value) end

  local number_value = tonumber(value)
  if number_value ~= nil then return number_value end
  return nil
end

local function read_flat_object_fields(text)
  local result = {}
  local index = 1

  while index <= #text do
    local key_start, key_end, key = text:find('"%s*([^"]-)%s*"%s*:', index)
    if not key_start then break end

    local value_start = key_end + 1
    while value_start <= #text and text:sub(value_start, value_start):match("%s") do
      value_start = value_start + 1
    end

    local value_end = value_start
    local in_string = false
    local escaped = false
    local object_depth = 0
    local array_depth = 0
    while value_end <= #text do
      local char = text:sub(value_end, value_end)
      if in_string then
        if escaped then
          escaped = false
        elseif char == "\\" then
          escaped = true
        elseif char == '"' then
          in_string = false
        end
      else
        if char == '"' then
          in_string = true
        elseif char == "{" then
          object_depth = object_depth + 1
        elseif char == "}" then
          object_depth = object_depth - 1
        elseif char == "[" then
          array_depth = array_depth + 1
        elseif char == "]" then
          array_depth = array_depth - 1
        elseif char == "," and object_depth == 0 and array_depth == 0 then
          break
        end
      end
      value_end = value_end + 1
    end

    local raw_value = text:sub(value_start, value_end - 1)
    result[unescape(key)] = decode_scalar_value(raw_value)
    index = value_end + 1
  end

  return result
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

  local params_text = extract_object_text(text, "params")
  if params_text then
    result.params = read_flat_object_fields(params_text)

    result.params.coalition = read_string_field(params_text, "coalition")
    result.params.text = read_string_field(params_text, "text")
    result.params.duration = read_number_field(params_text, "duration")
    result.params.object_id = read_string_field(params_text, "object_id")
    result.params.object_id_a = read_string_field(params_text, "object_id_a")
    result.params.object_id_b = read_string_field(params_text, "object_id_b")
    result.params.zone_id = read_string_field(params_text, "zone_id")
    result.params.format = read_string_field(params_text, "format")
    result.params.color = read_string_field(params_text, "color")
    result.params.alpha = read_number_field(params_text, "alpha")
    result.params.fill_color = read_string_field(params_text, "fill_color")
    result.params.fill_alpha = read_number_field(params_text, "fill_alpha")
    result.params.line_type = read_number_field(params_text, "line_type") or read_string_field(params_text, "line_type")
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
    result.params.clock_start = read_number_field(params_text, "clock_start") or read_string_field(params_text, "clock_start")
    result.params.clock_stop = read_number_field(params_text, "clock_stop") or read_string_field(params_text, "clock_stop")
    result.params.ClockStart = read_number_field(params_text, "ClockStart") or read_string_field(params_text, "ClockStart")
    result.params.ClockStop = read_number_field(params_text, "ClockStop") or read_string_field(params_text, "ClockStop")

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

    -- AUFTRAG:ORBIT fields.
    result.params.speed_kts = read_number_field(params_text, "speed_kts")
    result.params.speed = read_number_field(params_text, "speed")
    result.params.Speed = read_number_field(params_text, "Speed")
    result.params.heading_deg = read_number_field(params_text, "heading_deg")
    result.params.heading = read_number_field(params_text, "heading")
    result.params.Heading = read_number_field(params_text, "Heading")
    result.params.leg_nm = read_number_field(params_text, "leg_nm")
    result.params.leg = read_number_field(params_text, "leg")
    result.params.Leg = read_number_field(params_text, "Leg")
  end

  return result
end

return json
