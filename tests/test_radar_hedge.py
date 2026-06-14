"""Tests for VolPred Radar 支柱③ — 避險划不划算決策引擎 (scripts/radar_hedge.py).

驗證划算度計算邏輯的方向正確性（mock regime 輸入）：
  - regime 分類門檻（VIX / 年化波動備援）對齊前台 + K725 crisis 邊界
  - 高/中/低波動 regime 下的建議方向（timing 警示在 elevated/crisis）
  - 風險承受度（γ）× break-even 的划算度判讀（K738 decision guide）
  - 50/50 分散 fallback 的「順帶賺」負成本（K738 真實數字）
  - 資料不足時不臆造（regime=unknown → verdict=unknown，數字 None）
  - 所有保險成本數字鎖定真實 K 來源值（與 experiments/k738 / K667 一致）
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = REPO_ROOT / "scripts" / "radar_hedge.py"


def _load_engine():
    spec = importlib.util.spec_from_file_location("radar_hedge", ENGINE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__ in sys.modules.
    sys.modules["radar_hedge"] = module
    spec.loader.exec_module(module)
    return module


eng = _load_engine()


# ── regime 分類 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "vix,expected",
    [
        (10.0, "calm"),
        (14.9, "calm"),
        (15.0, "normal"),
        (17.9, "normal"),
        (18.0, "elevated"),
        (24.9, "elevated"),
        (25.0, "crisis"),
        (40.0, "crisis"),
    ],
)
def test_classify_regime_by_vix(vix, expected):
    assert eng.classify_regime(vix, None) == expected


@pytest.mark.parametrize(
    "sigma,expected",
    [
        (8.0, "calm"),
        (12.0, "normal"),
        (20.0, "elevated"),
        (30.0, "crisis"),
    ],
)
def test_classify_regime_vol_fallback_when_vix_missing(sigma, expected):
    assert eng.classify_regime(None, sigma) == expected


def test_classify_regime_unknown_when_both_missing():
    assert eng.classify_regime(None, None) == "unknown"


def test_classify_regime_prefers_vix_over_vol():
    # VIX says calm, σ says crisis → VIX wins (primary signal).
    assert eng.classify_regime(10.0, 50.0) == "calm"


# ── 高/中/低波動下的建議方向 ──────────────────────────────────────────────────

def test_crisis_regime_is_wrong_timing_for_continuous_vt():
    # K641/K725: 臨時上連續 VT 在 crisis 是最差時點。
    d = eng.decide_hedge(vix=35.0, risk_tolerance="low")
    assert d.regime == "crisis"
    assert d.verdict == "wrong_timing"
    # 不推薦連續 VT；fallback 到 50/50 分散，crisis 建議 0 加碼。
    assert d.instrument_key == "diversification_5050"
    assert d.suggested_hedge_ratio == 0.0
    assert any("K725" in n for n in d.notes)


def test_elevated_regime_is_wrong_timing_but_allows_small_defense():
    d = eng.decide_hedge(vix=20.0, risk_tolerance="very_low")
    assert d.regime == "elevated"
    assert d.verdict == "wrong_timing"
    assert d.suggested_hedge_ratio == 0.25
    assert any("K641" in n for n in d.notes)


def test_calm_regime_no_tolerance_recommends_5050_baseline():
    d = eng.decide_hedge(vix=12.0)
    assert d.regime == "calm"
    assert d.verdict == "worth_it"
    assert d.instrument_key == "diversification_5050"
    # 50/50 分散是負成本（順帶賺）— 真實 K738 數字。
    assert d.insurance_cost_pct == -0.51


# ── γ × break-even 划算度（K738 decision guide）────────────────────────────────

def test_high_tolerance_not_worth_it():
    # γ<2 → 不划算（K738 break-even γ≈4.4）。
    d = eng.decide_hedge(vix=12.0, risk_tolerance="high")
    assert d.verdict == "not_worth_it"
    assert d.suggested_hedge_ratio == 0.0


def test_moderate_tolerance_recommends_cheapest_insurance():
    # γ 2–5 → 50/50 分散（cheapest insurance），verdict worth_it（band 上界 5 > 4.4）。
    d = eng.decide_hedge(vix=12.0, risk_tolerance="moderate")
    assert d.instrument_key == "diversification_5050"
    assert d.verdict == "worth_it"


def test_low_tolerance_worth_it_active_vt():
    # γ 5–10 → 12/VIX 主動 VT，划算。
    d = eng.decide_hedge(vix=12.0, risk_tolerance="low")
    assert d.verdict == "worth_it"
    assert d.instrument_key == "twelve_over_vix"
    assert d.insurance_cost_pct == 3.49  # K738 真實
    assert d.breakeven_gamma == 4.5


def test_very_low_tolerance_max_protection_ewma():
    # γ>10 → EWMA VT（maximum protection, 最高成本效率）。
    d = eng.decide_hedge(vix=12.0, risk_tolerance="very_low")
    assert d.verdict == "worth_it"
    assert d.instrument_key == "ewma_vt"
    assert d.insurance_cost_pct == 2.12  # K738 真實
    assert d.breakeven_gamma == 4.4


def test_hedge_ratio_monotonic_in_risk_aversion_calm():
    # 風險越趨避 → 建議避險比例越高（calm regime，可正常布置保險）。
    ratios = [
        eng.decide_hedge(vix=12.0, risk_tolerance=t).suggested_hedge_ratio
        for t in ("high", "moderate", "low", "very_low")
    ]
    assert ratios == sorted(ratios)
    assert ratios[0] == 0.0 and ratios[-1] == 0.9


# ── 資料誠實 ──────────────────────────────────────────────────────────────────

def test_unknown_regime_does_not_fabricate():
    d = eng.decide_hedge(vix=None, annual_vol_pct=None)
    assert d.regime == "unknown"
    assert d.verdict == "unknown"
    assert d.insurance_cost_pct is None
    assert d.protection_mdd_pp is None
    assert d.instrument_key is None
    assert d.suggested_hedge_ratio is None


def test_real_k_numbers_locked():
    # 鎖定真實 K 數字，任何漂移即 fail（防臆造 / 防誤改）。
    instr = eng.HEDGE_INSTRUMENTS
    assert instr["diversification_5050"]["annual_cost_pct"] == -0.51  # K738
    assert instr["diversification_5050"]["cost_per_mdd_pp"] == -0.01  # K738
    assert instr["vt_5050"]["annual_cost_pct"] == 1.33  # K667
    assert instr["vt_5050"]["mdd_reduction_pp"] == 43.7  # K667
    assert instr["twelve_over_vix"]["annual_cost_pct"] == 3.49  # K738
    assert instr["twelve_over_vix"]["breakeven_gamma"] == 4.5  # K738
    assert instr["ewma_vt"]["annual_cost_pct"] == 2.12  # K738
    assert instr["ewma_vt"]["breakeven_gamma"] == 4.4  # K738
    assert instr["atm_put"]["annual_cost_pct"] == 26.1  # K667（對照組）
    assert eng.BREAKEVEN_GAMMA == 4.4  # K738 保守取較低 break-even


def test_data_honesty_string_present():
    d = eng.decide_hedge(vix=12.0, risk_tolerance="low")
    assert "K738" in d.data_honesty
    assert "非當下精確值" in d.data_honesty


def test_vol_fallback_drives_decision_when_vix_missing():
    # VIX 缺值但 σ=35% → crisis → wrong_timing。
    d = eng.decide_hedge(vix=None, annual_vol_pct=35.0, risk_tolerance="low")
    assert d.regime == "crisis"
    assert d.verdict == "wrong_timing"
