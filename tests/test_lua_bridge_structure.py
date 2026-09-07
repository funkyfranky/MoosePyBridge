import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_lua_bridge_transport_lifecycle() -> None:
    runtime = os.environ.get("MOOSEBRIDGE_TEST_LUA") or shutil.which("lua")
    if not runtime:
        pytest.skip("Set MOOSEBRIDGE_TEST_LUA or install Lua to run the bridge transport harness")
    result = subprocess.run(
        [runtime, str(REPO_ROOT / "tests/lua/bridge_transport_test.lua"),
         str(REPO_ROOT / "lua/MooseBridge.lua")],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BRIDGE TRANSPORT LUA TEST PASSED" in result.stdout


def test_bridge_constructor_preserves_moose_base_inheritance() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert "BASE:Inherit(self, BASE:New())" in source
    assert "if not BASE then setmetatable(self, { __index = MOOSE_BRIDGE }) end" in source


def test_bridge_transport_resumes_partial_nonblocking_io() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert 'self.ReadBuffer = ""' in source
    assert 'line = (self.ReadBuffer or "") .. line' in source
    assert 'self.ReadBuffer = (self.ReadBuffer or "") .. partial' in source
    assert "self.OutQueueOffset = 1" in source
    assert "local entry = self.OutQueue[self.OutQueueHead]" in source
    assert "local payload = entry.payload" in source
    assert "self.Socket:send(payload, offset)" in source
    assert 'elseif err == "timeout" then' in source
    assert "self.OutQueueOffset = final_byte + 1" in source
    assert "self:_RemoveOutQueueEntry(self.OutQueueHead)" in source


def test_bridge_start_is_idempotent_and_transport_work_is_bounded() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert "if self.Started then return self end" in source
    assert "self.Started = true" in source
    assert "self.Started = false" in source
    assert "while handled < self.MaxCommandsPerTick do" in source
    assert 'self:_Disconnect("receive failed: " .. safe_tostring(err))' in source
    assert "self:_FlushOutQueue(self.MaxOutMessagesPerTick)" in source
    assert "self.MaxOutQueueBytes = 32 * 1024 * 1024" in source


def test_bridge_replays_terminal_events_and_cached_command_results() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert '["auftrag.evaluated"]=true' in source
    assert '["object.destroyed"]=true' in source
    assert "self:_RetainReliableOutput()" in source
    assert "self:_ReplayReliableEvents()" in source
    assert "local cached = command_id and self.CommandResultCache[command_id] or nil" in source
    assert "self:Send(cached.message, true)" in source
    assert "self:_RememberCommandResult(command, msg)" in source


def test_group_snapshot_avoids_position_lookup_for_absent_dcs_groups() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")
    point_lookup = source.split("function MOOSE_BRIDGE:_PointForGroupName(name)", 1)[1]
    point_lookup = point_lookup.split("function MOOSE_BRIDGE:_PointForUnitName(name)", 1)[0]

    assert point_lookup.index('self:_SafeCall(group, "GetDCSObject")') < point_lookup.index(
        "self:_PointFromMooseObject(group)"
    )
    assert 'if self:_SafeCall(group, "IsAlive") ~= true then return nil end' in point_lookup


def test_bridge_exposes_bounded_native_dcs_road_routing() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert 'self:RegisterCommand("terrain.road_route"' in source
    assert "land.findPathOnRoads(" in source
    assert "max_points must be in range 2..2000" in source
    assert "sample_spacing_m=effective_spacing" in source
    assert "pathfinding_cpu_ms=pathfinding_cpu_ms" in source
    assert "total_cpu_ms=total_cpu_ms" in source


def test_zone_snapshot_exposes_scalar_moose_properties() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert "function MOOSE_BRIDGE:_ZoneProperties(zone)" in source
    assert "local source = zone and zone.Properties" in source
    assert 'value_type == "string" or value_type == "number" or value_type == "boolean"' in source
    assert "properties=self:_ZoneProperties(zone)" in source


def test_bridge_exposes_active_dcs_theater_identity() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert 'self:RegisterCommand("mission.info"' in source
    assert "theater_id=mission and mission.theatre or nil" in source


def test_ops_snapshots_use_moose_available_asset_counts() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert source.count('available_asset_count=self:_NumberOrNil(self:_SafeCall(') == 3
    assert 'self:_SafeCall(legion, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(cohort, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(commander, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(cohort, "GetMissionRange")' in source
    assert 'self:_SafeCallArg(cohort, "GetMissionRange", {weapon_type})' in source
    assert "skill=cohort and cohort.skill or nil" in source


def test_legion_snapshot_exposes_general_home_base_identity() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert 'home_base_id=home_base_name and "AIRBASE:"..safe_tostring(home_base_name) or nil' in source
    assert "home_base_name=string_or_nil(home_base_name)" in source


def test_cohort_snapshot_derives_homogeneous_grouping_from_asset_templates() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert "SetHomogeneous" not in source
    assert "function MOOSE_BRIDGE:_AnalyzeCohortComposition(cohort)" in source
    assert "local unit_type = unit and (unit.type or unit.typeName)" in source
    assert "unit_type ~= expected_type" in source
    assert "return true, uniform_count and expected_count or nil" in source
    assert "local homogeneous, units_per_asset = self:_AnalyzeCohortComposition(cohort)" in source
    assert "homogeneous=homogeneous" in source
    assert "configured_grouping=self:_NumberOrNil(cohort and cohort.ngrouping)" in source
    assert "units_per_asset=units_per_asset" in source


def test_commander_tasking_uses_moose_recruitment_and_constraints() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")

    assert "inputs.commander:AddMission(auftrag)" in source
    assert "auftrag:AssignLegion(legion)" in source
    assert "auftrag:AssignCohort(cohort)" in source


def test_auftrag_extension_applies_weapon_type_before_assignment() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")

    assert "weapon_type=bridge_number_param(p.weapon_type)" in source
    assert "auftrag:SetWeaponType(inputs.weapon_type)" in source


def test_auftrag_extension_converts_wgs84_coordinates_with_dcs_signature() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")

    assert "coord.LLtoLO(latitude, longitude, 0)" in source
    assert "coord.LLtoLO({lat=latitude, lon=longitude, alt=0})" not in source


def test_strike_prefers_live_scenery_object_and_retains_coordinate_fallback() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")

    assert "function MOOSE_BRIDGE:_ResolveSceneryAuftragTarget(inputs)" in source
    assert "SCENERY:FindByID(scenery_id)" in source
    assert "world.searchObjects(Object.Category.SCENERY" in source
    assert "SCENERY:Register(name, found)" in source
    assert 'inputs.target_resolution = "scenery_object"' in source
    assert 'inputs.target_resolution = "coordinate_fallback"' in source
    assert "target_resolution=inputs.target_resolution" in source


def test_recon_auftrag_builds_zone_set_and_moose_maintains_intel_agents() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")
    intel_source = (REPO_ROOT / "lua" / "MooseBridgeIntelExtension.lua").read_text(encoding="utf-8")

    assert 'self:RegisterCommand("auftrag.create_recon"' in source
    assert 'AUFTRAG:NewRECON(' in source
    assert 'self:_BuildZoneSet(inputs.zones, "RECON", true)' in source
    assert 'intel:SetAgentAuto()' in intel_source
    assert 'recce_unit_id=recce_name and "UNIT:" .. recce_name or nil' in intel_source
    assert 'self:_SafeCall(recce_unit, "GetGroup")' in intel_source
    assert 'self:_SafeCall(recce_group, "GetName")' in intel_source
    assert 'recce_group_id=recce_group_name and "GROUP:" .. tostring(recce_group_name) or nil' in intel_source
    assert '_RegisterAuftragIntelAgents' not in source


def test_dcs_event_extension_uses_moose_dispatcher() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeDcsEventsExtension.lua").read_text(encoding="utf-8")

    assert "self:HandleEvent(EVENTS.BaseCaptured)" in source
    assert "self:HandleEvent(EVENTS.UnitLost)" in source
    assert "self:HandleEvent(EVENTS.Dead)" in source
    assert "self:HandleEvent(EVENTS.Kill)" in source
    assert "self:HandleEvent(EVENTS.PlayerEnterAircraft)" in source
    assert "self:HandleEvent(EVENTS.PlayerLeaveUnit)" in source
    assert "self:HandleEvent(EVENTS.MarkAdded)" in source
    assert "self:HandleEvent(EVENTS.MarkChange)" in source
    assert "self:HandleEvent(EVENTS.MarkRemoved)" in source
    assert "self:HandleEvent(EVENTS.MissionEnd)" in source
    assert "function MOOSE_BRIDGE:OnEventBaseCaptured(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventUnitLost(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventDead(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventKill(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventPlayerEnterAircraft(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventPlayerLeaveUnit(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventMarkAdded(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventMarkChange(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventMarkRemoved(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventMissionEnd(EventData)" in source
    assert 'self:SendEvent("airbase.coalition_changed"' in source
    assert 'self:SendEvent("object.destroyed"' in source
    assert 'self:SendEvent("combat.kill"' in source
    assert '"player.aircraft.entered"' in source
    assert '"player.aircraft.left"' in source
    assert "self.PlayerAircraftSessions" in source
    assert "function MOOSE_BRIDGE:_NotifyPlayerEnteredAircraft(session, group)" in source
    assert 'self:_Log(string.format(' in source
    assert 'MESSAGE:New(text, 10, "MoosePyBridge"):ToGroup(group)' in source
    assert "function MOOSE_BRIDGE:_LogPlayerLeftAircraft(session)" in source
    assert '"Player/client left aircraft: player=' in source
    assert "self.PlayerAircraftLeaveTimes" in source
    assert "Suppressed duplicate PlayerLeaveUnit" in source
    assert "math.abs(lifecycle_time - previous_leave) <= 1" in source
    assert 'self:SendEvent(event_name' in source
    assert '"map.marker.changed"' in source
    assert 'self:SendEvent("mission.ended"' in source
    assert "self:_FlushOutQueue()" in source
    assert "function MOOSE_BRIDGE:_BuildObjectDestroyedPayload(EventData)" in source
    assert "EventData.IniObjectCategory == Object.Category.SCENERY" in source
    assert 'local object_type = is_scenery and "SCENERY"' in source
    assert 'return self:_ScenerySnapshot(' in source
    assert '"destruction_event"' in source


def test_flightgroup_route_command_reads_me_and_current_without_changing_route() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeNavigationExtension.lua").read_text(encoding="utf-8")
    route_code = source.split("function MOOSE_BRIDGE:_GetFlightGroupRoute(params)", 1)[1]
    route_code = route_code.split("--- Find cached enter data", 1)[0]
    assert "waypoints = opsgroup.waypoints0" in route_code
    assert 'self:_SafeCall(opsgroup, "GetWaypoints")' in route_code
    assert 'self:_SafeCall(opsgroup, "IsFlightgroup")' in route_code
    assert "local z = tonumber(waypoint.y)" in route_code
    assert "altitude_m=altitude" in route_code
    assert "altitude_type=waypoint.alt_type" in route_code
    assert '#waypoints > 501' in route_code
    assert 'self:RegisterCommand("flightgroup.route.get"' in route_code
    assert "_player_route_register_default_commands(self)" in route_code
    assert "UpdateRoute" not in route_code
    assert "AddWaypoint" not in route_code


def test_navigation_and_speech_are_separate_default_extensions() -> None:
    navigation = (REPO_ROOT / "lua" / "MooseBridgeNavigationExtension.lua").read_text(encoding="utf-8")
    speech = (REPO_ROOT / "lua" / "MooseBridgeSpeechExtension.lua").read_text(encoding="utf-8")

    assert "MOOSE_BRIDGE._NavigationExtensionLoaded" in navigation
    assert "MOOSE_BRIDGE._SpeechExtensionLoaded" in speech
    assert 'self:RegisterCommand("player.menu.navigation.status"' in navigation
    assert 'self:RegisterCommand("speech.enqueue"' not in navigation
    assert 'self:RegisterCommand("speech.enqueue"' in speech
    assert "local _speech_bridge_tick = MOOSE_BRIDGE._Tick" in speech


def test_player_enter_waits_for_flightgroup_and_preserves_lifecycle_order() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeDcsEventsExtension.lua").read_text(encoding="utf-8")
    enter = source.split("function MOOSE_BRIDGE:OnEventPlayerEnterAircraft(EventData)", 1)[1]
    enter = enter.split("function MOOSE_BRIDGE:OnEventPlayerLeaveUnit(EventData)", 1)[0]
    assert "for key, value in pairs(EventData) do pending[key] = value end" in enter
    assert "SCHEDULER:New(self, function(bridge)" in enter
    assert "end, {}, 0.5)" in enter
    assert "bridge:_FlushPendingPlayerAircraftEnter(pending)" in enter
    assert "self:ScheduleOnce(" not in enter
    assert "self.Scheduler =" not in enter
    leave = source.split("function MOOSE_BRIDGE:OnEventPlayerLeaveUnit(EventData)", 1)[1]
    leave = leave.split("--- Forward one DCS F10", 1)[0]
    assert leave.index("self:_FlushPendingPlayerAircraftEnter(pending)") < leave.index(
        "self:_ForwardPlayerAircraftEvent("
    )
    stop = source.split("function MOOSE_BRIDGE:_StopDcsEventForwarding()", 1)[1].split(
        "--- Forward DCS S_EVENT_BASE_CAPTURED", 1
    )[0]
    assert "self.PendingPlayerAircraftEnters = {}" in stop
    mission_end = source.split("function MOOSE_BRIDGE:OnEventMissionEnd(EventData)", 1)[1]
    assert "self.PendingPlayerAircraftEnters = {}" in mission_end


def test_opszone_capture_fsm_event_composes_public_callback_without_touching_internal_fsm() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")

    assert "local user_callback = opszone.OnAfterCaptured" in source
    assert "user_callback(opszone_self, From, Event, To, Coalition)" in source
    assert "opszone.OnAfterCaptured = forwarder" in source
    assert "opszone.onafterCaptured" not in source
    assert "opszone.Captured =" not in source
    assert "pcall(user_callback" not in source
    assert "capture_event_callback_type=" in source
    assert "capture_event_forwarder_attached=" in source
    assert 'bridge:SendEvent("opszone.owner_changed"' in source
    assert "previous_coalition=item.owner_previous_name" in source
    assert "capturing_coalition=bridge:_CoalitionToName(Coalition)" in source


def test_opszone_snapshot_derives_contested_from_current_scan_counts() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")

    assert "local n_red = opszone and tonumber(opszone.Nred) or 0" in source
    assert "local n_blue = opszone and tonumber(opszone.Nblu) or 0" in source
    assert "is_contested=n_red > 0 and n_blue > 0" in source
    assert "is_contested=self:_BoolOrFalse(opszone and opszone.isContested)" not in source
