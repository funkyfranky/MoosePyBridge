-- Exercise bridge lifecycle and reconnect reliability with mocked DCS boundaries.
local bridge_path = assert(arg[1], "base bridge path required")
local decoded_command = nil
MOOSE_BRIDGE_JSON = {
  encode=function(message) return tostring(message.id) .. "|" .. tostring(message.type) end,
  decode=function() return decoded_command end,
}
timer = {getTime=function() return 10 end, getAbsTime=function() return 20 end}
local scheduler_count = 0
SCHEDULER = {}
function SCHEDULER:New(owner, callback, args, delay, interval)
  scheduler_count = scheduler_count + 1
  return {Stop=function(self) self.stopped = true end}
end
dofile(bridge_path)

local bridge = MOOSE_BRIDGE:New("127.0.0.1", 42000)
bridge:Start()
bridge:Start()
assert(scheduler_count == 1, "Start must be idempotent")

bridge:SendEvent("auftrag.evaluated", {auftrag_id="AUFTRAG:1"})
assert(bridge.OutQueueCount == 1 and #bridge.ReliableEventJournal == 1,
  "terminal event must be retained while disconnected")

local function socket_sink()
  local sent = {}
  return {
    sent=sent,
    send=function(self, payload, offset)
      self.sent[#self.sent + 1] = payload:sub(offset)
      return #payload
    end,
    close=function() end,
  }
end

bridge.Socket = socket_sink()
bridge:_OnConnected()
assert(bridge.OutQueueCount == 1, "journal replay must not duplicate an already queued event")
bridge:_FlushOutQueue()
assert(#bridge.Socket.sent == 1 and bridge.OutQueueCount == 0, "retained event must be delivered")

bridge.Socket = socket_sink()
bridge:_OnConnected()
bridge:_FlushOutQueue()
assert(#bridge.Socket.sent == 1, "terminal journal must replay on every reconnect")

local side_effects = 0
bridge:RegisterCommand("test.side_effect", function(command)
  side_effects = side_effects + 1
  return {value=side_effects}
end)
decoded_command = {id="cmd-stable", action="test.side_effect", params={}}
bridge:_HandleCommand("ignored")
bridge:_FlushOutQueue()
bridge:_HandleCommand("ignored")
bridge:_FlushOutQueue()
assert(side_effects == 1, "replayed command must return its cached ACK without repeating side effects")
assert(bridge.CommandResultCache["cmd-stable"].message.result.value == 1,
  "cached ACK must preserve the original command result")

bridge:Stop()
assert(not bridge.Started and bridge.Scheduler == nil, "Stop must reset lifecycle state")
print("BRIDGE TRANSPORT LUA TEST PASSED")
