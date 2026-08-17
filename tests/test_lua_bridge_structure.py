from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


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
    assert "local payload = self.OutQueue[1]" in source
    assert "self.Socket:send(payload, offset)" in source
    assert 'elseif err == "timeout" then' in source
    assert "self.OutQueueOffset = final_byte + 1" in source
    assert "table.remove(self.OutQueue, 1)" in source


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


def test_ops_snapshots_use_moose_available_asset_counts() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert source.count('available_asset_count=self:_NumberOrNil(self:_SafeCall(') == 3
    assert 'self:_SafeCall(legion, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(cohort, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(commander, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(cohort, "GetMissionRange")' in source
    assert 'self:_SafeCallArg(cohort, "GetMissionRange", {weapon_type})' in source
    assert "skill=cohort and cohort.skill or nil" in source


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
    assert "self:HandleEvent(EVENTS.MissionEnd)" in source
    assert "function MOOSE_BRIDGE:OnEventBaseCaptured(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventUnitLost(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventDead(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventKill(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventMissionEnd(EventData)" in source
    assert 'self:SendEvent("airbase.coalition_changed"' in source
    assert 'self:SendEvent("object.destroyed"' in source
    assert 'self:SendEvent("combat.kill"' in source
    assert 'self:SendEvent("mission.ended"' in source
    assert "self:_FlushOutQueue()" in source


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
