from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bridge_constructor_preserves_moose_base_inheritance() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert "BASE:Inherit(self, BASE:New())" in source
    assert "if not BASE then setmetatable(self, { __index = MOOSE_BRIDGE }) end" in source


def test_ops_snapshots_use_moose_available_asset_counts() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert source.count('available_asset_count=self:_NumberOrNil(self:_SafeCall(') == 3
    assert 'self:_SafeCall(legion, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(cohort, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(commander, "CountAvailableAssets")' in source


def test_commander_tasking_uses_moose_recruitment_and_constraints() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")

    assert "inputs.commander:AddMission(auftrag)" in source
    assert "auftrag:AssignLegion(legion)" in source
    assert "auftrag:AssignCohort(cohort)" in source


def test_recon_auftrag_builds_zone_set_and_moose_maintains_intel_agents() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeAuftragExecutionExtension.lua").read_text(encoding="utf-8")
    intel_source = (REPO_ROOT / "lua" / "MooseBridgeIntelExtension.lua").read_text(encoding="utf-8")

    assert 'self:RegisterCommand("auftrag.create_recon"' in source
    assert 'AUFTRAG:NewRECON(' in source
    assert 'self:_BuildZoneSet(inputs.zones, "RECON", true)' in source
    assert 'intel:SetAgentAuto()' in intel_source
    assert 'recce_unit_id=recce_name and "UNIT:" .. recce_name or nil' in intel_source
    assert 'recce_group_id=recce_group_name and "GROUP:" .. tostring(recce_group_name) or nil' in intel_source
    assert '_RegisterAuftragIntelAgents' not in source


def test_dcs_event_extension_uses_moose_dispatcher() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridgeDcsEventsExtension.lua").read_text(encoding="utf-8")

    assert "self:HandleEvent(EVENTS.BaseCaptured)" in source
    assert "self:HandleEvent(EVENTS.UnitLost)" in source
    assert "self:HandleEvent(EVENTS.Dead)" in source
    assert "function MOOSE_BRIDGE:OnEventBaseCaptured(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventUnitLost(EventData)" in source
    assert "function MOOSE_BRIDGE:OnEventDead(EventData)" in source
    assert 'self:SendEvent("airbase.coalition_changed"' in source
    assert 'self:SendEvent("object.destroyed"' in source
