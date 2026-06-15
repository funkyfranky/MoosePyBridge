--- Minimal JSON helper for the MOOSE Bridge V1 prototype.
-- This is deliberately small and covers the V1 command/ack/heartbeat payloads.

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
  end

  return result
end

return json
