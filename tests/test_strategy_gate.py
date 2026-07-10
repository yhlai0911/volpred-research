"""Tests for the mechanical strategy-activation gate.

Covers the gate module itself and its wiring into every activation write path:
the two supabase_sync choke points, the volpred.ops.strategies wrappers used by
the CLI and ops jobs, scripts/add_strategy.py, and scripts/list_new_strategy.py's
independent Supabase writer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from volpred.ops import strategy_gate  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def receipts(tmp_path, monkeypatch):
    """Redirect the gate's receipt directory to an isolated tmp dir."""
    monkeypatch.setattr(strategy_gate, "receipts_dir", lambda: tmp_path)
    return tmp_path


def _valid_gates() -> dict:
    return {k: True for k in strategy_gate.GATE_KEYS}


def _write_receipt(directory: Path, key: str, gates: dict, **extra) -> Path:
    payload = {"strategy_key": key, "gates": gates, **extra}
    path = directory / f"{key}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _mod_of(func):
    """Return the actual module object a bound function lives in.

    add_strategy imports supabase_sync as a top-level module, which can be a
    distinct object from scripts.supabase_sync. Resolving via __module__ keeps
    monkeypatches on the correct copy.
    """
    return sys.modules[func.__module__]


# ---------------------------------------------------------------------------
# Gate module: validate_receipt / load_receipt / assert_activation_allowed
# ---------------------------------------------------------------------------

def test_validate_receipt_all_true_ok():
    ok, reasons = strategy_gate.validate_receipt({"gates": _valid_gates()})
    assert ok and reasons == []


def test_validate_receipt_grandfathered_ok():
    gates = {k: "grandfathered" for k in strategy_gate.GATE_KEYS}
    ok, reasons = strategy_gate.validate_receipt({"gates": gates})
    assert ok and reasons == []


def test_validate_receipt_missing_one_gate():
    gates = _valid_gates()
    gates.pop("sensitivity")
    ok, reasons = strategy_gate.validate_receipt({"gates": gates})
    assert not ok
    assert any("sensitivity" in r for r in reasons)


def test_validate_receipt_false_value_rejected():
    gates = _valid_gates()
    gates["cross_oos"] = False
    ok, reasons = strategy_gate.validate_receipt({"gates": gates})
    assert not ok
    assert any("cross_oos" in r for r in reasons)


def test_validate_receipt_int_one_not_treated_as_true():
    # JSON true -> Python True; a stray 1 must NOT sneak through as a pass.
    gates = _valid_gates()
    gates["mdd_acceptable"] = 1
    ok, _ = strategy_gate.validate_receipt({"gates": gates})
    assert not ok


def test_validate_receipt_non_dict():
    ok, reasons = strategy_gate.validate_receipt(["not", "a", "dict"])
    assert not ok and reasons


def test_load_receipt_missing_returns_none(receipts):
    assert strategy_gate.load_receipt("nope") is None


def test_load_receipt_valid(receipts):
    _write_receipt(receipts, "demo", _valid_gates())
    got = strategy_gate.load_receipt("demo")
    assert got["strategy_key"] == "demo"


def test_load_receipt_corrupt_raises(receipts):
    (receipts / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(strategy_gate.StrategyGateError, match="unreadable/invalid"):
        strategy_gate.load_receipt("broken")


def test_assert_no_receipt_raises(receipts):
    with pytest.raises(strategy_gate.StrategyGateError) as ei:
        strategy_gate.assert_activation_allowed("ghost", "Ghost Strategy")
    # Error must be actionable: mentions the tool, the five gates, the path.
    msg = str(ei.value)
    assert "evaluate_new_strategy.py" in msg
    assert "same_period_comparison" in msg
    assert "ghost.json" in msg


def test_assert_grandfathered_receipt_passes(receipts):
    _write_receipt(
        receipts, "legacy", {k: "grandfathered" for k in strategy_gate.GATE_KEYS}
    )
    strategy_gate.assert_activation_allowed("legacy", "Legacy")  # no raise


def test_assert_incomplete_receipt_raises(receipts):
    gates = _valid_gates()
    gates.pop("codex_review")
    _write_receipt(receipts, "partial", gates)
    with pytest.raises(strategy_gate.StrategyGateError, match="incomplete/invalid"):
        strategy_gate.assert_activation_allowed("partial", "Partial")


# ---------------------------------------------------------------------------
# Choke point 1: supabase_sync.sync_strategy_signal
# ---------------------------------------------------------------------------

@pytest.fixture
def sb():
    import scripts.supabase_sync as s
    return s


def test_sync_noop_active_resync_passes_without_receipt(sb, receipts, monkeypatch):
    """daily_update-style full sync of an already-active strategy: no receipt."""
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 7, "strategy_key": "slow_vt", "is_active": True},
    )
    patched = {}
    monkeypatch.setattr(sb, "_patch_where", lambda *a, **k: patched.setdefault("hit", True) or True)
    spy = _install_gate_spy(monkeypatch)

    ok = sb.sync_strategy_signal("GARCH VT (SPY)", {"SPY": 1.0}, is_active=True, strategy_key="slow_vt")
    assert ok is True
    assert patched.get("hit") is True
    spy.assert_not_called()  # no-op transition never touches the gate


def test_sync_new_strategy_no_receipt_raises(sb, receipts, monkeypatch):
    monkeypatch.setattr(sb, "_find_strategy_signal", lambda k, n: None)
    monkeypatch.setattr(sb, "_post", lambda *a, **k: True)
    with pytest.raises(strategy_gate.StrategyGateError):
        sb.sync_strategy_signal("Brand New", {"SPY": 1.0}, is_active=True, strategy_key="brand_new")


def test_sync_new_strategy_with_grandfathered_receipt_passes(sb, receipts, monkeypatch):
    _write_receipt(receipts, "brand_new", {k: "grandfathered" for k in strategy_gate.GATE_KEYS})
    monkeypatch.setattr(sb, "_find_strategy_signal", lambda k, n: None)
    posted = {}
    monkeypatch.setattr(sb, "_post", lambda *a, **k: posted.setdefault("hit", True) or True)
    ok = sb.sync_strategy_signal("Brand New", {"SPY": 1.0}, is_active=True, strategy_key="brand_new")
    assert ok is True and posted.get("hit") is True


def test_sync_reactivation_of_disabled_no_receipt_raises(sb, receipts, monkeypatch):
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 3, "strategy_key": "tz_tw_jp_5050", "is_active": False},
    )
    with pytest.raises(strategy_gate.StrategyGateError):
        sb.sync_strategy_signal("TW+JP", {"TW": 0.5}, is_active=True, strategy_key="tz_tw_jp_5050")


def test_sync_deactivation_always_passes(sb, receipts, monkeypatch):
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 3, "strategy_key": "x", "is_active": True},
    )
    monkeypatch.setattr(sb, "_patch_where", lambda *a, **k: True)
    spy = _install_gate_spy(monkeypatch)
    ok = sb.sync_strategy_signal("X", {"A": 1.0}, is_active=False, strategy_key="x")
    assert ok is True
    spy.assert_not_called()


def test_sync_supabase_lookup_failure_on_activation_fails_closed(sb, receipts, monkeypatch):
    """Indeterminate current state on activation -> raise (no backdoor), with a
    message distinguishable from a missing receipt."""
    def _boom(k, n):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(sb, "_find_strategy_signal", _boom)
    with pytest.raises(strategy_gate.StrategyGateError, match="indeterminate"):
        sb.sync_strategy_signal("New", {"SPY": 1.0}, is_active=True, strategy_key="new_x")


def test_sync_supabase_lookup_failure_on_deactivation_propagates_original(sb, receipts, monkeypatch):
    def _boom(k, n):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(sb, "_find_strategy_signal", _boom)
    # Deactivation must not be reinterpreted as a gate error; original raises.
    with pytest.raises(RuntimeError, match="connection refused"):
        sb.sync_strategy_signal("X", {"A": 1.0}, is_active=False, strategy_key="x")


# ---------------------------------------------------------------------------
# Choke point 2: supabase_sync.set_strategy_active
# ---------------------------------------------------------------------------

def test_set_active_disabled_to_active_no_receipt_raises(sb, receipts, monkeypatch):
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 5, "strategy_key": "disabled_one", "strategy_name": "Disabled", "is_active": False},
    )
    with pytest.raises(strategy_gate.StrategyGateError):
        sb.set_strategy_active("disabled_one", True)


def test_set_active_already_active_passes(sb, receipts, monkeypatch):
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 5, "strategy_key": "x", "strategy_name": "X", "is_active": True},
    )
    monkeypatch.setattr(sb, "_patch_where", lambda *a, **k: True)
    spy = _install_gate_spy(monkeypatch)
    assert sb.set_strategy_active("x", True) is True
    spy.assert_not_called()


def test_set_inactive_always_passes(sb, receipts, monkeypatch):
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 5, "strategy_key": "x", "strategy_name": "X", "is_active": True},
    )
    monkeypatch.setattr(sb, "_patch_where", lambda *a, **k: True)
    spy = _install_gate_spy(monkeypatch)
    assert sb.set_strategy_active("x", False) is True
    spy.assert_not_called()


def test_set_active_with_valid_receipt_passes(sb, receipts, monkeypatch):
    _write_receipt(receipts, "disabled_one", _valid_gates())
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 5, "strategy_key": "disabled_one", "strategy_name": "Disabled", "is_active": False},
    )
    monkeypatch.setattr(sb, "_patch_where", lambda *a, **k: True)
    assert sb.set_strategy_active("disabled_one", True) is True


def test_set_active_lookup_failure_fails_closed(sb, receipts, monkeypatch):
    def _boom(k, n):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(sb, "_find_strategy_signal", _boom)
    with pytest.raises(strategy_gate.StrategyGateError, match="indeterminate"):
        sb.set_strategy_active("whatever", True)


# ---------------------------------------------------------------------------
# Bypass wiring: each upstream caller reaches the gate
# ---------------------------------------------------------------------------

def _install_gate_spy(monkeypatch):
    """Replace the gate with a spy that records without raising."""
    from unittest.mock import MagicMock
    spy = MagicMock(name="assert_activation_allowed")
    monkeypatch.setattr(strategy_gate, "assert_activation_allowed", spy)
    return spy


def test_bypass_ops_strategies_upsert_reaches_gate(receipts, monkeypatch):
    """CLI `strategy-upsert` and ops-jobs `strategy_upsert` both route here."""
    from volpred.ops import strategies
    sb = _mod_of(strategies.sync_strategy_signal)
    monkeypatch.setattr(sb, "_find_strategy_signal", lambda k, n: None)
    monkeypatch.setattr(sb, "_post", lambda *a, **k: True)
    spy = _install_gate_spy(monkeypatch)
    strategies.upsert_strategy_metadata(
        strategy_key="new_upsert", strategy_name="New Upsert",
        weights={"SPY": 1.0}, is_active=True,
    )
    spy.assert_called_once_with("new_upsert", "New Upsert")


def test_bypass_ops_strategies_activate_reaches_gate(receipts, monkeypatch):
    """CLI `strategy-set-active --active` and ops-jobs `strategy_set_active`."""
    from volpred.ops import strategies
    sb = _mod_of(strategies.set_strategy_active)
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 9, "strategy_key": "reenable", "strategy_name": "Reenable", "is_active": False},
    )
    monkeypatch.setattr(sb, "_patch_where", lambda *a, **k: True)
    spy = _install_gate_spy(monkeypatch)
    strategies.activate_strategy("reenable")
    spy.assert_called_once_with("reenable", "Reenable")


def test_bypass_add_strategy_reaches_gate(receipts, monkeypatch):
    import add_strategy  # via scripts on sys.path
    sb = _mod_of(add_strategy.sync_strategy_signal)
    monkeypatch.setattr(sb, "_find_strategy_signal", lambda k, n: None)
    monkeypatch.setattr(sb, "_post", lambda *a, **k: True)
    spy = _install_gate_spy(monkeypatch)
    add_strategy.sync_strategy_signal(
        "Added Strategy", {"SPY": 1.0}, is_active=True, strategy_key="added_x",
    )
    spy.assert_called_once_with("added_x", "Added Strategy")


def test_bypass_add_strategy_set_active_reaches_gate(receipts, monkeypatch):
    import add_strategy
    sb = _mod_of(add_strategy.set_strategy_active)
    monkeypatch.setattr(
        sb, "_find_strategy_signal",
        lambda k, n: {"id": 2, "strategy_key": "added_x", "strategy_name": "Added", "is_active": False},
    )
    monkeypatch.setattr(sb, "_patch_where", lambda *a, **k: True)
    spy = _install_gate_spy(monkeypatch)
    add_strategy.set_strategy_active("added_x", True)
    spy.assert_called_once_with("added_x", "Added")


def test_bypass_list_new_strategy_step_b_reaches_gate(receipts, monkeypatch):
    import list_new_strategy as lns
    monkeypatch.setattr(lns, "_sb_select", lambda *a, **k: [])  # new strategy
    monkeypatch.setattr(lns, "_sb_upsert", lambda *a, **k: True)
    monkeypatch.setattr(lns, "_sb_patch", lambda *a, **k: True)
    spy = _install_gate_spy(monkeypatch)

    obj = lns.StrategyLister.__new__(lns.StrategyLister)
    obj.key = "listed_x"
    obj.name = "Listed Strategy"
    obj.assets = {"SPY": 1.0}
    obj.order = 20
    obj.howto = ""
    obj.description = ""
    obj.color = "#111111"
    obj.articles = []
    obj.rebalance_freq = ""
    obj.strategy_type = ""
    obj.strategy_type_color = ""
    obj.results = {}

    assert obj.step_b_strategy_signal() is True
    spy.assert_called_once_with("listed_x", "Listed Strategy")


def test_list_new_strategy_step_b_no_receipt_blocks(receipts, monkeypatch, capsys):
    """End-to-end (real gate) block: no receipt -> step_b returns False, prints help."""
    import list_new_strategy as lns
    monkeypatch.setattr(lns, "_sb_select", lambda *a, **k: [])
    monkeypatch.setattr(lns, "_sb_upsert", lambda *a, **k: True)

    obj = lns.StrategyLister.__new__(lns.StrategyLister)
    obj.key = "unreceipted"
    obj.name = "Unreceipted"
    obj.assets = {"SPY": 1.0}
    obj.order = 21
    obj.howto = obj.description = ""
    obj.color = "#111111"
    obj.articles = []
    obj.rebalance_freq = obj.strategy_type = obj.strategy_type_color = ""
    obj.results = {}

    assert obj.step_b_strategy_signal() is False
    assert "evaluate_new_strategy.py" in capsys.readouterr().out
