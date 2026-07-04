#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
K1635 — 投資迷思驗證：「台積電打噴嚏、台股重感冒」

把民間俗諺拆成四個可量化命題（2330.TW vs ^TWII 加權指數，2010-2026 日資料）：

  M1 集中度   : 2330.TW 佔台股大盤的市值權重隨時間演變（近似法，非官方 TWSE 指數權重）
  M2 傳導強度 : 2330 單日大跌（-3% / -5% 兩門檻）當日 & 隔日（T+1）對 ^TWII 的傳導
  M3 beta     : TWII_ret ~ a + b*TSMC_ret 全期 β + rolling β；大跌/下跌日 β 是否 asymmetry
  M4 波動傳導 : 2330 大跌後 ^TWII 之 T+1..T+5 forward realized vol 是否顯著升高 vs 基準

方法論硬規則（研究誠實原則）：
  * yfinance auto_adjust=False 明確指定（error_log 2026-05-01 教訓）；報酬用 Adj Close，
    市值用 raw Close × 股數（避免除息假跌訊號污染 drop 事件）。
  * 報酬一律 simple pct-change（讀者對 -3%/-5% 的直覺是 simple return），全程一致。
  * Lookahead 最高風險：T+1 傳導用「t 日已知的 2330 大跌」對「t+1 日的 TWII 報酬」，
    以 twii_ret.shift(-1) 對齊到事件日 t（等價把 signal lag 到隔日），當日/隔日分開報告不混。
  * 所有 bootstrap 固定 np.random.seed(SEED)。
  * 檢定：two-proportion z-test / Welch t / Mann-Whitney / HAC(Newey-West) OLS / bootstrap CI。
  * 大跌樣本小 → 誠實報告 N 與 power 限制。
  * Mechanical vs empirical 區分：2330 是 ^TWII 的成分股（權重 ~30-36%），當日傳導含
    「指數算術」機械成分（≈ weight × r_2330）；beta 若 >> weight 才是「感冒擴散到全市場」
    的真實共同波動。T+1 傳導無機械成分（不同交易日），是純預測性命題。

輸出：k1635_results.json + 4 張 PNG 圖 + README.md（另寫）
"""

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 註冊中文字型（macOS）避免 CJK glyph 缺失變方框
for _fp in [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]:
    if os.path.exists(_fp):
        try:
            font_manager.fontManager.addfont(_fp)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=_fp).get_name()
            break
        except Exception:
            continue
plt.rcParams["axes.unicode_minus"] = False

from scipy import stats
import statsmodels.api as sm
from statsmodels.stats.proportion import proportions_ztest

# ----------------------------------------------------------------------------
# 全域設定
# ----------------------------------------------------------------------------
SEED = 42
N_BOOT = 10000
START = "2010-01-01"
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(HERE, "k1635_results.json")
SNAPSHOT_PATH = os.path.join(HERE, "k1635_data_snapshot.csv")

# 2330 股數（yfinance sharesOutstanding 2026-07；股本近年大致穩定，用常數並在 README 註明）
TSMC_SHARES = 25_932_370_067
# M1 anchored-proxy：以文獻/公開資訊之 TSMC TAIEX 權重錨定 series 末端。
# 公開資訊（TWSE / 指數編製商）近年 TSMC 佔 TAIEX 約 30-38%；取中性 0.36 為中心，另做 0.30 敏感度。
W_ANCHOR_CENTRAL = 0.36
W_ANCHOR_LOW = 0.30

DROP_THRESHOLDS = [-0.03, -0.05]  # -3%, -5%

np.random.seed(SEED)


# ----------------------------------------------------------------------------
# 資料
# ----------------------------------------------------------------------------
def _flatten(df):
    """yfinance 單 ticker 下載回 MultiIndex columns；攤平成單層。"""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def load_data():
    import yfinance as yf

    if os.path.exists(SNAPSHOT_PATH):
        # 復現優先讀本地 snapshot（yfinance 非 time-travel，error_log 2026-05-06 教訓）
        snap = pd.read_csv(SNAPSHOT_PATH, index_col=0, parse_dates=True)
        used_snapshot = True
    else:
        tsmc = _flatten(yf.download("2330.TW", start=START, auto_adjust=False, progress=False))
        twii = _flatten(yf.download("^TWII", start=START, auto_adjust=False, progress=False))
        proxy_used = False
        if twii is None or len(twii) == 0:
            twii = _flatten(yf.download("0050.TW", start=START, auto_adjust=False, progress=False))
            proxy_used = True
        snap = pd.DataFrame(
            {
                "tsmc_adjclose": tsmc["Adj Close"],
                "tsmc_close": tsmc["Close"],
                "twii_adjclose": twii["Adj Close"],
                "twii_close": twii["Close"],
            }
        ).dropna()
        snap.attrs["proxy_used"] = proxy_used
        snap.to_csv(SNAPSHOT_PATH)
        used_snapshot = False

    # inner-join 已由共同 index + dropna 保證
    snap = snap.dropna()
    snap.attrs.setdefault("used_snapshot", used_snapshot)
    return snap


# ----------------------------------------------------------------------------
# 統計工具
# ----------------------------------------------------------------------------
def bootstrap_mean_ci(x, n_boot=N_BOOT, alpha=0.05, seed=SEED):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    boot_means = x[idx].mean(axis=1)
    lo = np.percentile(boot_means, 100 * alpha / 2)
    hi = np.percentile(boot_means, 100 * (1 - alpha / 2))
    return (float(np.mean(x)), float(lo), float(hi))


def two_sample_prop_ztest(k_event, n_event, k_comp, n_comp):
    """事件組 vs 補集組（非事件日）的兩樣本 down-prob 檢定（獨立兩群，乾淨對照）。"""
    if n_event == 0 or n_comp == 0:
        return (np.nan, np.nan)
    stat, pval = proportions_ztest(count=[k_event, k_comp], nobs=[n_event, n_comp])
    return (float(stat), float(pval))


def welch_t(a, b):
    a = np.asarray(a, float)
    a = a[~np.isnan(a)]
    b = np.asarray(b, float)
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return (np.nan, np.nan)
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return (float(t), float(p))


# ----------------------------------------------------------------------------
# M1 集中度
# ----------------------------------------------------------------------------
def run_M1(df):
    # 市值（NT$）= raw Close × 股數（不用 adjusted，adjusted 非真實股價）
    mktcap = df["tsmc_close"] * TSMC_SHARES  # NT$
    mktcap_last = float(mktcap.iloc[-1])

    # anchored weight proxy: w(t) = mktcap_2330(t)/TAIEX(t)，正規化使末端 = W_ANCHOR
    # 假設：total_mktcap(t) ∝ TAIEX(t)（除數常數）。這是近似；除數其實隨新上市成長，
    # 常數除數會誇大權重上升幅度 → 在 README 誠實標註偏誤方向。
    ratio = mktcap / df["twii_close"]
    k_central = ratio.iloc[-1] / W_ANCHOR_CENTRAL
    k_low = ratio.iloc[-1] / W_ANCHOR_LOW
    w_central = ratio / k_central
    w_low = ratio / k_low

    # 年度平均權重（proxy, central anchor）
    yearly = w_central.groupby(w_central.index.year).mean()

    out = {
        "method": "approximate (NOT official TWSE index weight); mktcap=rawClose*shares, "
        "anchored to documented TSMC TAIEX weight at series end",
        "shares_outstanding_used": TSMC_SHARES,
        "tsmc_mktcap_last_NTD_trillion": round(mktcap_last / 1e12, 3),
        "tsmc_mktcap_first_NTD_trillion": round(float(mktcap.iloc[0]) / 1e12, 3),
        "mktcap_growth_multiple": round(float(mktcap.iloc[-1] / mktcap.iloc[0]), 2),
        "anchor_central": W_ANCHOR_CENTRAL,
        "anchor_low": W_ANCHOR_LOW,
        "weight_proxy_first_central": round(float(w_central.iloc[0]), 4),
        "weight_proxy_last_central": round(float(w_central.iloc[-1]), 4),
        "weight_proxy_yearly_central": {str(int(y)): round(float(v), 4) for y, v in yearly.items()},
        "bias_note": "constant-divisor assumption exaggerates the RISE (true divisor grows with "
        "new listings); absolute mktcap trend is assumption-free, weight trajectory corroborated "
        "by public sources (~16-18% in 2015, ~28% in 2020, ~30-38% in 2024-2025).",
    }
    # 供繪圖
    aux = {
        "mktcap_trillion": mktcap / 1e12,
        "w_central": w_central,
        "w_low": w_low,
    }
    return out, aux


# ----------------------------------------------------------------------------
# M2 傳導強度
# ----------------------------------------------------------------------------
def run_M2(df):
    r_tsmc = df["tsmc_adjclose"].pct_change()
    r_twii = df["twii_adjclose"].pct_change()
    # T+1 的 TWII 報酬對齊到「事件日 t」：twii_next[t] = r_twii[t+1]
    r_twii_next = r_twii.shift(-1)

    base = pd.DataFrame(
        {"r_tsmc": r_tsmc, "r_twii": r_twii, "r_twii_next": r_twii_next}
    ).dropna(subset=["r_tsmc", "r_twii"])

    # 無條件基準（同日）
    uncond_p_down = float((base["r_twii"] < 0).mean())
    uncond_mean = float(base["r_twii"].mean())
    # 無條件 T+1 基準
    base_next = base.dropna(subset=["r_twii_next"])
    uncond_p_down_next = float((base_next["r_twii_next"] < 0).mean())
    uncond_mean_next = float(base_next["r_twii_next"].mean())

    res = {
        "n_total_days": int(len(base)),
        "unconditional_same_day": {
            "p_twii_down": round(uncond_p_down, 4),
            "mean_twii_ret": round(uncond_mean, 6),
        },
        "unconditional_next_day": {
            "p_twii_down": round(uncond_p_down_next, 4),
            "mean_twii_ret": round(uncond_mean_next, 6),
        },
        "thresholds": {},
    }

    for thr in DROP_THRESHOLDS:
        key = f"{int(thr*100)}pct"
        drop = base["r_tsmc"] <= thr
        comp = ~drop  # 補集：非大跌日（乾淨對照組，避免子集混入母體）
        n_drop = int(drop.sum())

        # ---- 同日（contemporaneous；含機械成分）；對照 = 非大跌日 ----
        twii_same = base.loc[drop, "r_twii"]
        twii_same_comp = base.loc[comp, "r_twii"]
        k_down_same = int((twii_same < 0).sum())
        k_down_same_comp = int((twii_same_comp < 0).sum())
        p_down_same = k_down_same / n_drop if n_drop else np.nan
        mean_same, lo_same, hi_same = bootstrap_mean_ci(twii_same.values)
        z_same, pz_same = two_sample_prop_ztest(
            k_down_same, n_drop, k_down_same_comp, int(comp.sum())
        )
        t_same, pt_same = welch_t(twii_same.values, twii_same_comp.values)

        # ---- 隔日 T+1（純預測；無機械成分；lookahead-safe: signal@t, target@t+1）；對照 = 非大跌日隔日 ----
        base_n = base.dropna(subset=["r_twii_next"])
        drop_n = base_n["r_tsmc"] <= thr
        comp_n = ~drop_n
        twii_next = base_n.loc[drop_n, "r_twii_next"]
        twii_next_comp = base_n.loc[comp_n, "r_twii_next"]
        n_drop_next = int(len(twii_next))
        k_down_next = int((twii_next < 0).sum())
        k_down_next_comp = int((twii_next_comp < 0).sum())
        p_down_next = k_down_next / n_drop_next if n_drop_next else np.nan
        mean_next, lo_next, hi_next = bootstrap_mean_ci(twii_next.values)
        z_next, pz_next = two_sample_prop_ztest(
            k_down_next, n_drop_next, k_down_next_comp, int(comp_n.sum())
        )
        t_next, pt_next = welch_t(twii_next.values, twii_next_comp.values)

        res["thresholds"][key] = {
            "threshold": thr,
            "n_drop_days": n_drop,
            "same_day": {
                "p_twii_down": round(p_down_same, 4) if n_drop else None,
                "mean_twii_ret": round(mean_same, 6),
                "boot_ci95": [round(lo_same, 6), round(hi_same, 6)],
                "vs_nonevent_p_down_z": round(z_same, 3) if not np.isnan(z_same) else None,
                "vs_nonevent_p_down_pval": round(pz_same, 5) if not np.isnan(pz_same) else None,
                "vs_nonevent_mean_welch_t": round(t_same, 3) if not np.isnan(t_same) else None,
                "vs_nonevent_mean_welch_p": round(pt_same, 6) if not np.isnan(pt_same) else None,
            },
            "next_day_T1": {
                "n": n_drop_next,
                "p_twii_down": round(p_down_next, 4) if n_drop_next else None,
                "mean_twii_ret": round(mean_next, 6),
                "boot_ci95": [round(lo_next, 6), round(hi_next, 6)],
                "vs_nonevent_p_down_z": round(z_next, 3) if not np.isnan(z_next) else None,
                "vs_nonevent_p_down_pval": round(pz_next, 5) if not np.isnan(pz_next) else None,
                "vs_nonevent_mean_welch_t": round(t_next, 3) if not np.isnan(t_next) else None,
                "vs_nonevent_mean_welch_p": round(pt_next, 6) if not np.isnan(pt_next) else None,
            },
        }
    aux = {"r_tsmc": r_tsmc, "r_twii": r_twii, "r_twii_next": r_twii_next, "base": base}
    return res, aux


# ----------------------------------------------------------------------------
# M3 beta / 迴歸
# ----------------------------------------------------------------------------
def run_M3(df):
    r_tsmc = df["tsmc_adjclose"].pct_change()
    r_twii = df["twii_adjclose"].pct_change()
    d = pd.DataFrame({"r_tsmc": r_tsmc, "r_twii": r_twii}).dropna()

    # 全期 OLS + HAC(Newey-West)
    X = sm.add_constant(d["r_tsmc"].values)
    y = d["r_twii"].values
    ols = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    beta_full = float(ols.params[1])
    beta_full_se = float(ols.bse[1])
    beta_full_t = float(ols.tvalues[1])
    r2_full = float(ols.rsquared)
    alpha_full = float(ols.params[0])

    # rolling 252d beta
    win = 252
    roll_beta = pd.Series(index=d.index, dtype=float)
    xa = d["r_tsmc"].values
    ya = d["r_twii"].values
    for i in range(win, len(d) + 1):
        xx = xa[i - win : i]
        yy = ya[i - win : i]
        cov = np.cov(xx, yy)[0, 1]
        var = np.var(xx)
        roll_beta.iloc[i - 1] = cov / var if var > 0 else np.nan
    roll_beta = roll_beta.dropna()

    # ---- Asymmetry #1: downside vs upside beta（依 r_tsmc 正負分組）----
    down = d[d["r_tsmc"] < 0]
    up = d[d["r_tsmc"] >= 0]

    def _beta(sub):
        Xs = sm.add_constant(sub["r_tsmc"].values)
        m = sm.OLS(sub["r_twii"].values, Xs).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        return float(m.params[1]), float(m.bse[1]), int(len(sub))

    b_down, se_down, n_down = _beta(down)
    b_up, se_up, n_up = _beta(up)
    # 差異檢定（獨立近似）
    z_asym = (b_down - b_up) / np.sqrt(se_down**2 + se_up**2)
    p_asym = 2 * (1 - stats.norm.cdf(abs(z_asym)))

    # ---- Asymmetry #2: 交互項（大跌 -3% dummy）----
    drop_dummy = (d["r_tsmc"] <= -0.03).astype(float).values
    Xi = np.column_stack(
        [np.ones(len(d)), d["r_tsmc"].values, d["r_tsmc"].values * drop_dummy, drop_dummy]
    )
    oi = sm.OLS(d["r_twii"].values, Xi).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    inter_coef = float(oi.params[2])  # r_tsmc × drop
    inter_t = float(oi.tvalues[2])
    inter_p = float(oi.pvalues[2])

    out = {
        "n": int(len(d)),
        "beta_full": round(beta_full, 4),
        "beta_full_HAC_se": round(beta_full_se, 4),
        "beta_full_HAC_t": round(beta_full_t, 2),
        "alpha_full": round(alpha_full, 6),
        "r2_full": round(r2_full, 4),
        "rolling_beta_min": round(float(roll_beta.min()), 3),
        "rolling_beta_max": round(float(roll_beta.max()), 3),
        "rolling_beta_last": round(float(roll_beta.iloc[-1]), 3),
        "rolling_beta_mean": round(float(roll_beta.mean()), 3),
        "downside_beta": round(b_down, 4),
        "downside_beta_se": round(se_down, 4),
        "downside_n": n_down,
        "upside_beta": round(b_up, 4),
        "upside_beta_se": round(se_up, 4),
        "upside_n": n_up,
        "asymmetry_z": round(float(z_asym), 3),
        "asymmetry_pval": round(float(p_asym), 5),
        "tail_interaction_coef": round(inter_coef, 4),
        "tail_interaction_t": round(inter_t, 2),
        "tail_interaction_pval": round(inter_p, 5),
        "note": "beta_full >> approx weight(~0.30-0.36) => co-movement extends beyond TSMC's own "
        "mechanical index share (broad-market 'cold'). Same-day beta mixes mechanical inclusion + "
        "genuine sector co-movement.",
    }
    aux = {"roll_beta": roll_beta}
    return out, aux


# ----------------------------------------------------------------------------
# M4 波動傳導
# ----------------------------------------------------------------------------
def run_M4(df):
    r_twii = df["twii_adjclose"].pct_change()
    r_tsmc = df["tsmc_adjclose"].pct_change()
    d = pd.DataFrame({"r_tsmc": r_tsmc, "r_twii": r_twii}).dropna()

    ann = np.sqrt(252)
    H = 5
    # forward 5d realized vol of TWII，對齊到事件日 t：用 [t+1..t+5] 的報酬 std（strictly forward）
    rt = d["r_twii"].values
    n = len(d)
    fwd_rv = np.full(n, np.nan)
    for i in range(n - H):
        window = rt[i + 1 : i + 1 + H]  # t+1..t+5, strictly after t
        if len(window) == H:
            fwd_rv[i] = np.std(window, ddof=1) * ann
    d = d.assign(fwd_rv=fwd_rv)

    valid = d.dropna(subset=["fwd_rv"])
    uncond_rv = float(valid["fwd_rv"].mean())

    res = {
        "horizon_days": H,
        "annualized": True,
        "unconditional_fwd5d_rv_mean": round(uncond_rv, 4),
        "thresholds": {},
    }
    for thr in DROP_THRESHOLDS:
        key = f"{int(thr*100)}pct"
        ev = valid[valid["r_tsmc"] <= thr]["fwd_rv"]
        comp = valid[valid["r_tsmc"] > thr]["fwd_rv"]  # 補集：非大跌日（乾淨對照）
        n_ev = int(len(ev))
        mean_ev, lo_ev, hi_ev = bootstrap_mean_ci(ev.values)
        mean_comp = float(comp.mean())
        # Welch on log-RV（波動右偏，log 較穩健）；對照 = 非大跌日
        t_log, p_log = welch_t(np.log(ev.values), np.log(comp.values))
        # Mann-Whitney（單尾：事件組 > 對照組）
        if n_ev >= 2:
            u, p_u = stats.mannwhitneyu(ev.values, comp.values, alternative="greater")
        else:
            u, p_u = (np.nan, np.nan)
        res["thresholds"][key] = {
            "threshold": thr,
            "n_events": n_ev,
            "event_fwd5d_rv_mean": round(mean_ev, 4),
            "event_boot_ci95": [round(lo_ev, 4), round(hi_ev, 4)],
            "nonevent_fwd5d_rv_mean": round(mean_comp, 4),
            "ratio_event_vs_nonevent": round(mean_ev / mean_comp, 3),
            "welch_logrv_t": round(t_log, 3) if not np.isnan(t_log) else None,
            "welch_logrv_p": round(p_log, 6) if not np.isnan(p_log) else None,
            "mannwhitney_u": float(u) if not np.isnan(u) else None,
            "mannwhitney_p_greater": round(float(p_u), 6) if not np.isnan(p_u) else None,
        }
    aux = {"valid": valid}
    return res, aux


# ----------------------------------------------------------------------------
# 圖表
# ----------------------------------------------------------------------------
def plot_M1(aux, path):
    fig, ax1 = plt.subplots(figsize=(10, 5.5))
    mktcap = aux["mktcap_trillion"]
    ax1.plot(mktcap.index, mktcap.values, color="#1f4e79", lw=1.6, label="2330 市值 (兆 NT$)")
    ax1.set_ylabel("2330 市值 (兆 NT$, raw Close × 股數)", color="#1f4e79")
    ax1.tick_params(axis="y", labelcolor="#1f4e79")
    ax2 = ax1.twinx()
    ax2.plot(aux["w_central"].index, aux["w_central"].values * 100, color="#c00000", lw=1.4,
             label="權重近似 (anchor 36%)")
    ax2.plot(aux["w_low"].index, aux["w_low"].values * 100, color="#e69138", lw=1.0, ls="--",
             label="權重近似 (anchor 30%)")
    ax2.set_ylabel("2330 佔大盤權重近似 (%)", color="#c00000")
    ax2.tick_params(axis="y", labelcolor="#c00000")
    ax1.set_title("M1 集中度：2330 市值成長與佔台股大盤權重近似 (2010-2026)")
    ax1.set_xlabel("年份")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)
    ax1.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_M2(m2_aux, path):
    base = m2_aux["base"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    # 同日
    drop3 = base["r_tsmc"] <= -0.03
    axes[0].hist(base["r_twii"] * 100, bins=80, color="#bdd7ee", density=True,
                 alpha=0.8, label="全部交易日")
    axes[0].hist(base.loc[drop3, "r_twii"] * 100, bins=30, color="#c00000", density=True,
                 alpha=0.55, label="2330 當日跌 ≤ -3%")
    axes[0].axvline(0, color="k", lw=0.8)
    axes[0].set_title("M2 當日：TWII 報酬分布（含機械成分）")
    axes[0].set_xlabel("^TWII 當日報酬 (%)")
    axes[0].set_ylabel("density")
    axes[0].set_xlim(-8, 8)
    axes[0].legend(fontsize=8)
    # 隔日 T+1
    nb = base.dropna(subset=["r_twii_next"])
    d3n = nb["r_tsmc"] <= -0.03
    axes[1].hist(nb["r_twii_next"] * 100, bins=80, color="#c9e2c9", density=True,
                 alpha=0.8, label="全部交易日 (T+1)")
    axes[1].hist(nb.loc[d3n, "r_twii_next"] * 100, bins=30, color="#c00000", density=True,
                 alpha=0.55, label="2330 跌 ≤ -3% 之隔日")
    axes[1].axvline(0, color="k", lw=0.8)
    axes[1].set_title("M2 隔日 T+1：TWII 報酬分布（純預測）")
    axes[1].set_xlabel("^TWII 隔日報酬 (%)")
    axes[1].set_xlim(-8, 8)
    axes[1].legend(fontsize=8)
    fig.suptitle("M2 傳導：2330 大跌日 vs 全部交易日的 ^TWII 報酬分布", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_M3(m3_aux, path):
    rb = m3_aux["roll_beta"]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(rb.index, rb.values, color="#1f4e79", lw=1.3)
    ax.axhline(rb.mean(), color="#c00000", ls="--", lw=1.0, label=f"平均 β={rb.mean():.2f}")
    ax.axhline(0.35, color="#7f7f7f", ls=":", lw=1.0, label="近似權重 ~0.35（機械下限）")
    ax.set_title("M3 rolling 252 日 β：^TWII 對 2330 的敏感度 (2011-2026)")
    ax.set_xlabel("年份")
    ax.set_ylabel("β (TWII_ret on TSMC_ret)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_M4(m4_aux, path):
    valid = m4_aux["valid"]
    base = valid["fwd_rv"].values * 100
    ev3 = valid[valid["r_tsmc"] <= -0.03]["fwd_rv"].values * 100
    ev5 = valid[valid["r_tsmc"] <= -0.05]["fwd_rv"].values * 100
    fig, ax = plt.subplots(figsize=(9, 5.5))
    data = [base, ev3, ev5]
    labels = [f"全部\n(n={len(base)})", f"2330 跌≤-3%\n(n={len(ev3)})",
              f"2330 跌≤-5%\n(n={len(ev5)})"]
    bp = ax.boxplot(data, labels=labels, showfliers=False, patch_artist=True, widths=0.55)
    for patch, c in zip(bp["boxes"], ["#bdd7ee", "#f4b183", "#c00000"]):
        patch.set_facecolor(c)
        patch.set_alpha(0.75)
    means = [np.mean(x) for x in data]
    ax.plot(range(1, 4), means, "D", color="black", ms=6, label="平均")
    for i, m in enumerate(means, 1):
        ax.text(i, m, f" {m:.1f}%", va="center", fontsize=9)
    ax.set_title("M4 波動傳導：2330 大跌後 ^TWII 之 T+1..T+5 forward RV（年化）")
    ax.set_ylabel("forward 5 日 realized vol（年化 %）")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def main():
    df = load_data()
    proxy_used = bool(df.attrs.get("proxy_used", False))
    period = (str(df.index[0].date()), str(df.index[-1].date()))
    n_obs = int(len(df))

    m1, m1_aux = run_M1(df)
    m2, m2_aux = run_M2(df)
    m3, m3_aux = run_M3(df)
    m4, m4_aux = run_M4(df)

    # 圖
    plot_M1(m1_aux, os.path.join(HERE, "k1635_fig1_concentration.png"))
    plot_M2(m2_aux, os.path.join(HERE, "k1635_fig2_transmission.png"))
    plot_M3(m3_aux, os.path.join(HERE, "k1635_fig3_rolling_beta.png"))
    plot_M4(m4_aux, os.path.join(HERE, "k1635_fig4_vol_transmission.png"))

    results = {
        "experiment_id": "k1635",
        "title": "投資迷思驗證：台積電打噴嚏、台股重感冒（2330 → ^TWII 傳導 event study）",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "index_ticker": "0050.TW (proxy)" if proxy_used else "^TWII",
            "stock_ticker": "2330.TW",
            "proxy_used": proxy_used,
            "period": period,
            "n_obs": n_obs,
            "return_type": "simple pct_change on Adj Close (auto_adjust=False)",
            "seed": SEED,
            "n_bootstrap": N_BOOT,
        },
        "M1_concentration": m1,
        "M2_transmission": m2,
        "M3_beta": m3,
        "M4_vol_transmission": m4,
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # console 摘要
    print(f"[K1635] {period[0]}..{period[1]}  N={n_obs}  proxy={proxy_used}")
    print(f"  M1 last mktcap={m1['tsmc_mktcap_last_NTD_trillion']}兆  "
          f"weight_proxy last={m1['weight_proxy_last_central']} first={m1['weight_proxy_first_central']}")
    for thr in ["-3pct", "-5pct"]:
        t = m2["thresholds"][thr]
        print(f"  M2 {thr}: N={t['n_drop_days']} | sameday P(down)={t['same_day']['p_twii_down']} "
              f"mean={t['same_day']['mean_twii_ret']} | T+1 P(down)={t['next_day_T1']['p_twii_down']} "
              f"mean={t['next_day_T1']['mean_twii_ret']} (p={t['next_day_T1']['vs_nonevent_mean_welch_p']})")
    print(f"  M3 beta_full={m3['beta_full']} (t={m3['beta_full_HAC_t']}) R2={m3['r2_full']} "
          f"| downside β={m3['downside_beta']} upside β={m3['upside_beta']} asym_p={m3['asymmetry_pval']} "
          f"| tail_interaction p={m3['tail_interaction_pval']}")
    for thr in ["-3pct", "-5pct"]:
        t = m4["thresholds"][thr]
        print(f"  M4 {thr}: n={t['n_events']} fwdRV={t['event_fwd5d_rv_mean']} vs nonevent "
              f"{t['nonevent_fwd5d_rv_mean']} ratio={t['ratio_event_vs_nonevent']} MW_p={t['mannwhitney_p_greater']}")
    print(f"  wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
