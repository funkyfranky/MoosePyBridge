from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bridge_constructor_preserves_moose_base_inheritance() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert "BASE:Inherit(self, BASE:New())" in source
    assert "if not BASE then setmetatable(self, { __index = MOOSE_BRIDGE }) end" in source


def test_ops_snapshots_use_moose_available_asset_counts() -> None:
    source = (REPO_ROOT / "lua" / "MooseBridge.lua").read_text(encoding="utf-8")

    assert source.count('available_asset_count=self:_NumberOrNil(self:_SafeCall(') == 2
    assert 'self:_SafeCall(legion, "CountAvailableAssets")' in source
    assert 'self:_SafeCall(cohort, "CountAvailableAssets")' in source


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
