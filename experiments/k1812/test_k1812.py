"""K1812 不變式測試 —— lag 正確、組合市場中性、regime 對齊、檢定可重現。

這些測試證明「程式照設計跑」；方法論是否違反 repo 硬規則另由 experiment_gates 驗。
純合成資料 + 讀 results.json 的不變式，不觸網路。

除了程式不變式，這裡還守兩條**審查用**的機械 gate：
  * `test_results_primary_test_preserves_time_dependence` —— 主顯著性檢定必須是保留 regime
    持續性的那一個（i.i.d. 版只能掛 COMPARISON ONLY），退回去就紅。
  * `test_readme_numbers_match_results` —— README 的每個關鍵數字都要對得上現行 results.json，
    避免 README 漂成一份無法查證的敘事。
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "k1812_results.json"
README = HERE / "README.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("k1812_mod", HERE / "k1812.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


k = _load_module()


# --------------------------------------------------------------------------------------
# 1) FP rank weights：兩腿權重各自加總為 1；低腿只壓低 beta、高腿只壓高 beta
# --------------------------------------------------------------------------------------
def test_fp_rank_weights_sum_to_one():
    betas = pd.Series({"a": 0.4, "b": 0.7, "c": 1.0, "d": 1.3, "e": 1.6})
    w_low, w_high = k.fp_rank_weights(betas)
    assert w_low.sum() == pytest.approx(1.0, abs=1e-10)
    assert w_high.sum() == pytest.approx(1.0, abs=1e-10)


def test_fp_rank_weights_leg_assignment():
    betas = pd.Series({"a": 0.4, "b": 0.7, "c": 1.0, "d": 1.3, "e": 1.6})
    w_low, w_high = k.fp_rank_weights(betas)
    # 低腿權重集中在低 beta，高腿集中在高 beta
    assert w_low["a"] > w_low["b"] > 0
    assert w_low["e"] == pytest.approx(0.0)
    assert w_high["e"] > w_high["d"] > 0
    assert w_high["a"] == pytest.approx(0.0)


# --------------------------------------------------------------------------------------
# 2) 市場中性不變式：(1/βL)·βL - (1/βH)·βH == 0，恆等於 0（建構層面）
# --------------------------------------------------------------------------------------
def test_market_neutral_construction():
    for beta_L, beta_H in [(0.6, 1.3), (0.4, 1.5), (0.8, 1.1)]:
        exante = (1.0 / beta_L) * beta_L - (1.0 / beta_H) * beta_H
        assert exante == pytest.approx(0.0, abs=1e-12)


# --------------------------------------------------------------------------------------
# 3) beta 收縮：affine 保序、且腿 beta 被拉離 0
# --------------------------------------------------------------------------------------
def test_shrinkage_keeps_order_and_bounds():
    raw = pd.Series({"a": -0.2, "b": 0.3, "c": 1.0, "d": 1.8})
    shr = k.SHRINKAGE_W * raw + (1.0 - k.SHRINKAGE_W) * 1.0
    # 保序
    assert list(shr.sort_values().index) == list(raw.sort_values().index)
    # 最低值被拉離 0（raw=-0.2 → 0.6*-0.2+0.4 = 0.28 > raw）
    assert shr.min() > raw.min()
    assert shr.min() == pytest.approx(0.6 * (-0.2) + 0.4)


# --------------------------------------------------------------------------------------
# 4) bootstrap 可重現（seed=42 兩次相同）
# --------------------------------------------------------------------------------------
def test_bootstrap_deterministic():
    rng = np.random.default_rng(0)
    y_low = rng.normal(0.01, 0.05, 120)
    y_high = rng.normal(-0.005, 0.05, 130)
    a = k.sharpe_diff_bootstrap(y_low, y_high, reps=500, seed=42)
    b = k.sharpe_diff_bootstrap(y_low, y_high, reps=500, seed=42)
    assert a["diff_observed"] == pytest.approx(b["diff_observed"])
    assert a["p_value_ci_based"] == pytest.approx(b["p_value_ci_based"])
    assert a["ci95_low"] == pytest.approx(b["ci95_low"])


def test_permutation_deterministic_and_null_centered():
    rng = np.random.default_rng(0)
    y_low = rng.normal(0.01, 0.05, 120)
    y_high = rng.normal(-0.005, 0.05, 130)
    a = k.sharpe_diff_permutation(y_low, y_high, reps=800, seed=42)
    b = k.sharpe_diff_permutation(y_low, y_high, reps=800, seed=42)
    assert a["p_value_two_sided"] == pytest.approx(b["p_value_two_sided"])
    assert a["diff_observed"] == pytest.approx(b["diff_observed"])
    # permutation null 應以 0 為中心
    assert abs(a["null_mean"]) < 0.15
    assert 0.0 <= a["p_value_two_sided"] <= 1.0
    # i.i.d. 版只能是對照組，不得被當主判準
    assert a["preserves_time_dependence"] is False
    assert "COMPARISON ONLY" in a["role"]


# --------------------------------------------------------------------------------------
# 4b) 主檢定 = circular block permutation：保留時間相依、有 power、且校準正常
# --------------------------------------------------------------------------------------
def _persistent_labels(n: int, p_stay: float, rng: np.random.Generator) -> np.ndarray:
    """兩態 Markov chain 產生**會持續**的 regime label（模擬 vol regime clustering）。"""
    lab = np.empty(n, dtype=int)
    lab[0] = 1
    for i in range(1, n):
        lab[i] = lab[i - 1] if rng.random() < p_stay else 1 - lab[i - 1]
    return lab


def test_circular_block_permutation_preserves_labels_and_persistence():
    """區塊重排必須保持：長度、低/高月數、以及大部分的 regime 持續性（i.i.d. 版則不會）。"""
    rng = np.random.default_rng(7)
    lab = _persistent_labels(240, 0.85, rng)
    obs_acf1 = k.acf_profile(lab, 1)[0]
    obs_run = k.regime_run_lengths(lab).mean()
    assert obs_acf1 > 0.5, "合成 label 應該有明顯持續性，否則這個測試沒在測東西"

    perms = [k._circular_block_permute(lab, 8, rng) for _ in range(300)]
    assert all(len(p) == len(lab) for p in perms), "區塊重排不得改變序列長度"
    assert all(p.sum() == lab.sum() for p in perms), "區塊重排不得改變低/高月數（multiset 不變）"

    block_acf1 = float(np.mean([k.acf_profile(p, 1)[0] for p in perms]))
    block_run = float(np.mean([k.regime_run_lengths(p).mean() for p in perms]))
    iid = [rng.permutation(lab) for _ in range(300)]
    iid_acf1 = float(np.mean([k.acf_profile(p, 1)[0] for p in iid]))

    # 區塊重排留住大部分持續性；i.i.d. 重排把它歸零 —— 這正是主檢定被換掉的理由
    assert block_acf1 > 0.6 * obs_acf1, f"block null 沒保住持續性: {block_acf1} vs {obs_acf1}"
    assert block_run > 0.7 * obs_run
    assert abs(iid_acf1) < 0.05, f"i.i.d. null 竟保留了持續性: {iid_acf1}"


def test_block_permutation_deterministic():
    rng = np.random.default_rng(3)
    lab = _persistent_labels(200, 0.85, rng)
    r = rng.normal(0.0, 0.04, 200)
    a = k.sharpe_diff_block_permutation(r, lab, reps=500, seed=42)
    b = k.sharpe_diff_block_permutation(r, lab, reps=500, seed=42)
    assert a["p_value_two_sided"] == pytest.approx(b["p_value_two_sided"])
    assert a["diff_observed"] == pytest.approx(b["diff_observed"])
    assert a["preserves_time_dependence"] is True
    assert a["n_low"] + a["n_high"] == len(r)


def test_block_permutation_has_power_against_a_real_regime_effect():
    """真的有 regime 效應時，主檢定必須抓得到 —— 否則「p 不顯著」只是檢定沒力氣。"""
    rng = np.random.default_rng(11)
    lab = _persistent_labels(240, 0.85, rng)
    r = np.where(lab == 1, rng.normal(0.020, 0.04, 240), rng.normal(-0.020, 0.04, 240))
    res = k.sharpe_diff_block_permutation(r, lab, reps=1000, seed=42)
    assert res["diff_observed"] > 0.5
    assert res["p_value_two_sided"] < 0.01, f"對真效應無 power: p={res['p_value_two_sided']}"


def test_block_permutation_calibrated_under_the_null():
    """label 持續但與報酬獨立時，p 不得系統性偏小（否則主檢定會製造假顯著）。"""
    small = 0
    for trial in range(20):
        rng = np.random.default_rng(1000 + trial)
        lab = _persistent_labels(240, 0.85, rng)
        r = rng.normal(0.0, 0.04, 240)  # 與 label 完全獨立
        if k.sharpe_diff_block_permutation(r, lab, reps=300, seed=42)["p_value_two_sided"] < 0.05:
            small += 1
    assert small <= 5, f"20 個純 null 樣本有 {small} 個 p<0.05 —— 檢定校準有問題"


def test_circular_shift_enumerates_every_nontrivial_shift():
    rng = np.random.default_rng(5)
    lab = _persistent_labels(120, 0.85, rng)
    r = rng.normal(0.0, 0.04, 120)
    res = k.sharpe_diff_circular_shift(r, lab)
    assert res["n_shifts"] == len(r) - 1, "窮舉 shift 必須跑遍 k=1..n-1"
    assert res["p_resolution_floor"] == pytest.approx(1.0 / len(r))
    assert res["p_value_two_sided"] >= res["p_resolution_floor"]
    assert res["preserves_time_dependence"] is True


def test_stationary_bootstrap_deterministic_and_covers_observed_effect():
    rng = np.random.default_rng(9)
    lab = _persistent_labels(200, 0.85, rng)
    r = np.where(lab == 1, rng.normal(0.01, 0.04, 200), rng.normal(-0.01, 0.04, 200))
    a = k.sharpe_diff_stationary_bootstrap(r, lab, reps=400, seed=42)
    b = k.sharpe_diff_stationary_bootstrap(r, lab, reps=400, seed=42)
    assert a["ci95_low"] == pytest.approx(b["ci95_low"])
    assert a["ci95_high"] == pytest.approx(b["ci95_high"])
    # 效應量 bootstrap：分佈以觀察效應為中心 → CI 必須涵蓋它
    assert a["ci95_low"] <= a["diff_observed"] <= a["ci95_high"]
    assert a["preserves_time_dependence"] is True


def test_regime_block_length_rule():
    """block 長度是規則算出來的（非依 p 值挑選）：max(ceil(n^(1/3)), ceil(平均段長))。"""
    lab = np.array([1, 1, 0, 0, 1, 1, 0, 0] * 10)  # n=80，段長恆為 2
    rule = k.regime_block_length(lab)
    assert rule["mean_run_length"] == pytest.approx(2.0)
    assert rule["block_len_months"] == max(int(np.ceil(80 ** (1 / 3))), 2)
    assert rule["n_runs"] == 40


def test_contiguous_month_guard_fails_loud_on_a_gap():
    """block/circular 重排假設逐月連續；跳月必須 fail-loud，不得默默算出一個 p。"""
    ok = pd.period_range("2020-01", "2020-12", freq="M").to_timestamp("M")
    assert k.assert_contiguous_months(ok, "ok") == 12
    gapped = ok.delete(5)
    with pytest.raises(AssertionError, match="not contiguous"):
        k.assert_contiguous_months(gapped, "gapped")


# --------------------------------------------------------------------------------------
# 5) NW 落後期公式
# --------------------------------------------------------------------------------------
def test_nw_maxlags():
    assert k.nw_maxlags(261) == int(np.floor(4.0 * (261 / 100.0) ** (2.0 / 9.0)))
    assert k.nw_maxlags(100) == 4


# --------------------------------------------------------------------------------------
# 5b) 完成月 gate：資料只到月中 → 該月被判為未完成、回上一個完整月
# --------------------------------------------------------------------------------------
def test_last_complete_month_drops_incomplete():
    # 資料到 2026-07-24（July 未結束）→ 最後完整月應為 2026-06
    idx = pd.bdate_range("2026-01-02", "2026-07-24")
    assert k.last_complete_month_period(idx) == pd.Period("2026-06", "M")
    # 資料到某月最後 business day → 該月即完整
    idx2 = pd.bdate_range("2026-01-02", "2026-06-30")
    assert k.last_complete_month_period(idx2) == pd.Period("2026-06", "M")


# --------------------------------------------------------------------------------------
# 6) results.json 不變式：市場中性 + lookahead 0 mismatch
# --------------------------------------------------------------------------------------
@pytest.mark.skipif(not RESULTS.exists(), reason="results not yet generated")
def test_results_invariants():
    r = json.loads(RESULTS.read_text())
    inv = r["invariants"]
    # ex-ante BAB beta ≈ 0
    assert abs(inv["exante_bab_beta_max_abs"]) < 1e-8
    # regime alignment：每一個檢查月 shift(1) 訊號 == 形成月 regime，0 mismatch
    assert inv["regime_alignment_mismatches"] == 0
    assert inv["regime_alignment_check_months"] > 0


# --------------------------------------------------------------------------------------
# 7) lag 正確性：panel 每列 hold_month period == form_month period + 1（無 same-month）
# --------------------------------------------------------------------------------------
@pytest.mark.skipif(
    not (HERE / "data" / "bab_panel.json").exists(), reason="panel not yet generated"
)
def test_no_same_month_lag():
    panel = pd.read_json(HERE / "data" / "bab_panel.json")
    hold_p = pd.to_datetime(panel["hold_month"]).dt.to_period("M")
    form_p = pd.to_datetime(panel["form_month"]).dt.to_period("M")
    # 形成月嚴格早於持有月，且恰好差 1 個月
    diff = (hold_p.astype("int64") - form_p.astype("int64"))
    assert (diff == 1).all(), "hold month must be exactly one month after formation month"


# --------------------------------------------------------------------------------------
# 8) regime 對齊：持有月 m 的低 vol 訊號 = 形成月 (m-1) 的 regime（合成驗證 shift 語意）
# --------------------------------------------------------------------------------------
def test_regime_shift_alignment_semantics():
    idx = pd.period_range("2020-01", "2020-06", freq="M").to_timestamp("M")
    rv = pd.Series([0.05, 0.02, 0.08, 0.03, 0.09, 0.01], index=idx)  # 月市場 RV
    med = rv.median()
    regime_low = (rv < med).astype(float)  # 1 = low-vol 月
    # 對齊到「下一月報酬」：shift(1)
    signal = regime_low.shift(1)
    # 2020-02 的訊號 = 2020-01 的 regime
    assert signal.loc[idx[1]] == regime_low.loc[idx[0]]
    assert signal.loc[idx[3]] == regime_low.loc[idx[2]]
    # 第一個月無前月訊號
    assert pd.isna(signal.loc[idx[0]])


# --------------------------------------------------------------------------------------
# 9) 審查 gate：results 宣告的主檢定必須是保留時間相依的那一個
# --------------------------------------------------------------------------------------
@pytest.mark.skipif(not RESULTS.exists(), reason="results not yet generated")
def test_results_primary_test_preserves_time_dependence():
    r = json.loads(RESULTS.read_text())
    cond = r["conditional_median_split"]

    assert cond["primary_significance_test"] == "sharpe_difference_block_permutation"
    assert cond["primary_effect_size_ci"] == "sharpe_difference_stationary_bootstrap"

    for key in ("sharpe_difference_block_permutation",
                "sharpe_difference_circular_shift_exact",
                "sharpe_difference_stationary_bootstrap"):
        assert cond[key]["preserves_time_dependence"] is True, key
    for key in ("sharpe_difference_iid_permutation", "sharpe_difference_iid_bootstrap"):
        assert cond[key]["preserves_time_dependence"] is False, key
        assert "COMPARISON ONLY" in cond[key]["role"], key

    primary = cond["sharpe_difference_block_permutation"]
    assert primary["reps"] >= 10000 and primary["seed"] == 42
    assert primary["n_low"] + primary["n_high"] == cond["n_months"]

    # 主檢定的 null 確實保留了 regime 持續性，i.i.d. 的 null 確實沒有
    dep = cond["serial_dependence_check"]
    obs_acf1 = dep["observed"]["label_acf1"]
    assert obs_acf1 > 0.2, "本樣本 regime 應該有持續性，否則這條 gate 沒在守東西"
    assert dep["under_block_permutation_null"]["label_acf1"] > 0.6 * obs_acf1
    assert dep["under_circular_shift_null"]["label_acf1"] > 0.8 * obs_acf1
    assert abs(dep["under_iid_permutation_null"]["label_acf1"]) < 0.05

    # block 長度是規則產物，且 p 對 block 長度不敏感（沒有靠調 b 換結論）
    rule = cond["regime_block_length_rule"]
    assert primary["block_len_months"] == rule["block_len_months"]
    grid_p = [g["p_value_two_sided"] for g in cond["sharpe_difference_block_length_sensitivity"]]
    assert max(grid_p) - min(grid_p) < 0.05, f"p 對 block 長度敏感: {grid_p}"

    # robustness spec 走同一套主檢定
    assert r["robustness_expanding_median"]["primary_significance_test"] == (
        "sharpe_difference_block_permutation"
    )


# --------------------------------------------------------------------------------------
# 10) 審查 gate：README 的關鍵數字必須逐一對上現行 results.json
#     （防的是「README 寫了一組沒有 artifact 可核對的數字」這個 bug class）
# --------------------------------------------------------------------------------------
def _has_number(text: str, token: str) -> bool:
    """token 必須以完整數字出現：前後不可再接數字，避免 -0.37 誤配到 -0.375。"""
    return re.search(rf"(?<![\d.]){re.escape(token)}(?!\d)", text) is not None


@pytest.mark.skipif(
    not (RESULTS.exists() and README.exists()), reason="results/README not present"
)
def test_readme_numbers_match_results():
    r = json.loads(RESULTS.read_text())
    # README 用 U+2212 排版負號；比對前正規化成 ASCII
    text = README.read_text().replace("−", "-")

    cond = r["conditional_median_split"]
    rt = r["robustness_expanding_median"]
    dep = cond["serial_dependence_check"]
    lev = r["leverage_diagnostics"]
    unc = r["baseline_unconditional_bab"]
    grid = {g["block_len_months"]: g["p_value_two_sided"]
            for g in cond["sharpe_difference_block_length_sensitivity"]}

    checks: list[tuple[str, str]] = [
        # 樣本
        ("n_bab_months", f"{r['sample']['n_bab_months']:d}"),
        ("universe requested", f"{r['universe']['n_tickers_requested']:d}"),
        ("universe included", f"{r['universe']['n_tickers_included']:d}"),
        # baseline
        ("uncond mean %/mo", f"{unc['mean'] * 100:.2f}%"),
        ("uncond sharpe", f"{unc['sharpe_annual']:.3f}"),
        ("uncond HAC t", f"{unc['t_stat']:.2f}"),
        ("uncond HAC p", f"{unc['p_value']:.3f}"),
        # 條件 Sharpe
        ("sharpe after low", f"{cond['after_low_vol']['sharpe_annual']:.3f}"),
        ("sharpe after high", f"{cond['after_high_vol']['sharpe_annual']:.3f}"),
        ("n low", f"{cond['after_low_vol']['n']:d}"),
        ("n high", f"{cond['after_high_vol']['n']:d}"),
        ("sharpe diff", f"{cond['sharpe_difference_block_permutation']['diff_observed']:.3f}"),
        # 主檢定與對照
        ("PRIMARY block-perm p",
         f"{cond['sharpe_difference_block_permutation']['p_value_two_sided']:.3f}"),
        ("exact circular-shift p",
         f"{cond['sharpe_difference_circular_shift_exact']['p_value_two_sided']:.3f}"),
        ("iid perm p (comparison)",
         f"{cond['sharpe_difference_iid_permutation']['p_value_two_sided']:.3f}"),
        ("stationary boot CI low",
         f"{cond['sharpe_difference_stationary_bootstrap']['ci95_low']:.3f}"),
        ("stationary boot CI high",
         f"{cond['sharpe_difference_stationary_bootstrap']['ci95_high']:.3f}"),
        ("block null sd", f"{cond['sharpe_difference_block_permutation']['null_sd']:.3f}"),
        ("iid null sd", f"{cond['sharpe_difference_iid_permutation']['null_sd']:.3f}"),
        ("block len", f"{cond['sharpe_difference_block_permutation']['block_len_months']:d}"),
        ("n blocks", f"{cond['sharpe_difference_block_permutation']['n_blocks']:d}"),
        *[(f"grid p b={b}", f"{p:.3f}") for b, p in grid.items()],
        # 持續性量測（§3.1 的表）
        ("observed label acf1", f"{dep['observed']['label_acf1']:.3f}"),
        ("block null acf1", f"{dep['under_block_permutation_null']['label_acf1']:.3f}"),
        ("shift null acf1", f"{dep['under_circular_shift_null']['label_acf1']:.3f}"),
        ("iid null acf1", f"{dep['under_iid_permutation_null']['label_acf1']:.3f}"),
        ("observed mean run", f"{dep['observed']['mean_run_length']:.2f}"),
        ("block null mean run", f"{dep['under_block_permutation_null']['mean_run_length']:.2f}"),
        ("shift null mean run", f"{dep['under_circular_shift_null']['mean_run_length']:.2f}"),
        ("iid null mean run", f"{dep['under_iid_permutation_null']['mean_run_length']:.2f}"),
        ("bab return acf1", f"{dep['observed']['bab_return_acf'][0]:.3f}"),
        ("max regime run", f"{cond['regime_block_length_rule']['max_run_length']:d}"),
        # regime 迴歸
        ("regime reg beta", f"{cond['regime_regression']['beta_low_vol']:.4f}"),
        ("regime reg t", f"{cond['regime_regression']['beta_low_vol_t']:.2f}"),
        ("regime reg p", f"{cond['regime_regression']['beta_low_vol_p']:.3f}"),
        # robustness
        ("tercile low", f"{r['robustness_tercile']['low']['sharpe_annual']:.3f}"),
        ("tercile mid", f"{r['robustness_tercile']['mid']['sharpe_annual']:.3f}"),
        ("tercile high", f"{r['robustness_tercile']['high']['sharpe_annual']:.3f}"),
        ("rt diff", f"{rt['sharpe_difference_block_permutation']['diff_observed']:.3f}"),
        ("rt block p", f"{rt['sharpe_difference_block_permutation']['p_value_two_sided']:.3f}"),
        ("rt shift p",
         f"{rt['sharpe_difference_circular_shift_exact']['p_value_two_sided']:.3f}"),
        ("rt iid p", f"{rt['sharpe_difference_iid_permutation']['p_value_two_sided']:.3f}"),
        # 槓桿診斷（§6A 每個數字都必須來自 results）
        ("beta_L_raw min", f"{lev['beta_L_raw_min']:.4f}"),
        ("n months beta_L_raw<=0", f"{lev['n_months_beta_L_raw_nonpositive']:d}"),
        ("leverage without shrinkage",
         f"{lev['implied_leverage_without_shrinkage_max']:,.0f}"),
        ("beta_L shrunk min", f"{lev['beta_L_shrunk_min']:.3f}"),
        ("beta_L shrunk max", f"{lev['beta_L_shrunk_max']:.3f}"),
        ("leverage with shrinkage", f"{lev['leverage_with_shrinkage_max']:.2f}"),
        ("max |BAB| monthly", f"{lev['bab_abs_max_monthly'] * 100:.2f}%"),
        # 不變式
        ("exante beta max abs", f"{r['invariants']['exante_bab_beta_max_abs']:.1e}"),
        ("alignment months", f"{r['invariants']['regime_alignment_check_months']:d}"),
    ]

    missing = [(label, token) for label, token in checks if not _has_number(text, token)]
    assert not missing, (
        "README 有數字對不上現行 k1812_results.json（改了結果就要同步改 README）:\n"
        + "\n".join(f"  - {label}: 期望在 README 找到 {token!r}" for label, token in missing)
    )


# --------------------------------------------------------------------------------------
# 11) 審查 gate：README 不得宣稱未發生的審查輪次
# --------------------------------------------------------------------------------------
@pytest.mark.skipif(not README.exists(), reason="README not present")
def test_readme_does_not_claim_unrecorded_review_rounds():
    """review 敘事必須可由 review_verdict.json 核對；『多輪 review』這類無憑據宣稱不得再出現。"""
    text = README.read_text()
    assert "Codex review（多輪）" not in text
    assert "Codex primary-path review（多輪）" not in text
    verdict = HERE / "review_verdict.json"
    for claim in re.findall(r"round-(\d+)", text):
        assert verdict.exists(), (
            f"README 提到 round-{claim}，但 review_verdict.json 不存在 —— 審查敘事無憑據"
        )
