#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1627 — 投資迷思驗證：「美股大跌、台股隔天必補跌」隔夜傳導的實際條件機率
======================================================================

動機
----
台股散戶最普遍的信念之一：「昨晚美股大跌，今天台股開盤/收盤『一定』補跌」。
本實驗用實證條件機率、2x2 列聯表檢定、與傳導幅度回歸，檢定「必」這個字站不站得住。

差異化（vs K1626）
------------------
K1626（TSM ADR vs 2330.TW 價格發現）研究的是「個股 ADR 的 intraday 價格發現 / lead-lag」。
本實驗（K1627）研究的是「指數層級的日頻條件機率」——大眾信念「補跌」是否成立、成立到什麼程度。
主題與資料頻率皆不同；K1626 為相關前作但不重疊。

資料
----
- 美股 proxy = SPY（本地 SQLite 快取，2016-01-04 → 2026-07-02）
- 台股大盤 proxy = 0050.TW（本地 SQLite 快取；本系統慣例以 0050.TW 作 TAIEX proxy，README 誠實標註）
- 來源：data/cache/price_cache.db，table price_data（ticker,date,open,high,low,close,volume,adj_close）
- 報酬用 adj_close 的 close-to-close 日報酬（本窗口 adj_close 無 null，已驗證無 split artifact：
  2016+ 兩序列 max|r|≈10-11%，2025-06-18 的 0050.TW 1:4 分割已正確反映在 adj_close，無 4x 跳空）。

方法論（最高優先：alignment 無 lookahead）
-----------------------------------------
1) 隔夜傳導 alignment（無 lookahead 的核心理由）：
   - 訊號 = SPY 在美股日 D 的 close-to-close 日報酬 r_us(D)。
     此訊號在美股收盤時（約台灣時間 D+1 清晨 04:00–05:00）已完全 realized，
     **早於**台股 D+1 開盤（約 09:00）。
   - 反應 = 0050.TW 在 D 之後的「下一個實際存在的 0050.TW 交易日」T 的日報酬 r_tw(T)
     （T = 資料中 strictly greater than D 的最小 0050.TW 交易日；遇台股假日自動跳到下一個存在的交易日）。
   - 因為 US close(D) 先於 TW open(T)，這是 legitimate timing、無 lookahead
     （等同 Paper 6 session-boundary 原則：用「已 realized 的隔夜資訊」預測「尚未開盤的下一 session」）。
   - **禁止** same-calendar-date 對齊 SPY 與 0050.TW（會製造 off-by-one lookahead）。
     本程式用兩邊各自實際存在的交易日曆做 map，不假設連續日。
   - 對齊採「US-forward 事件索引」：每個 US 交易日 D 都是一個迷思事件，指向其後第一個 TW 交易日 T。
     迷思本身是「US 事件 → 預測 TW」，故以 US 事件為分析單位。
     診斷：台股假日時可能多個 US 日對到同一 TW 日（many-to-one），會如實計數並在 caveat 報告；
     另附「每 TW 日僅保留最新 US 訊號」的去重 robustness 版本。

2) 迷思門檻（敏感度，不只單一門檻）：
   - 「美股大跌」US-down 門檻：r_us(D) < -1% / < -2% / < -3%（另附寬鬆 baseline r_us(D) < 0）。
   - 「台股補跌」定義：主用 r_tw(T) < 0（下跌）；另附較強版 r_tw(T) < -1%。

3) 核心統計（全做）：
   (a) 條件機率 vs base rate：每門檻算 P(TW down next | US big down)，
       並列無條件 base rate P(TW down) 與對照組 P(TW down | r_us >= 0)。
   (b) 2x2 列聯表：US big down(yes/no) x TW down next(yes/no)；chi-square（大樣本）/ Fisher exact（小樣本）
       + p-value；difference-in-proportions z 檢定 + 95% CI。
   (c) 傳導幅度回歸：r_tw(T) ~ alpha + beta*r_us(D)，OLS + Newey-West/HAC 穩健 SE（lag=5）。
   (d) 每門檻樣本數 n 必列。
   (e) 主門檻條件機率 block bootstrap 95% CI（block=5, n_boot=2000, seed=42）。

4) 固定 seed：所有隨機程序 seed=42。

5) 誠實原則：若「有顯著正向傳導但機率遠低於必然」則如實寫；某門檻 n<30 標 caveat 不過度宣稱。

執行：uv run python experiments/k1627/k1627.py
產出：k1627_results.json, fig_conditional_prob.png, fig_transmission_scatter.png（均寫入本目錄）
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
import statsmodels.api as sm

# CJK-capable font so Traditional Chinese labels render (not tofu boxes).
# macOS 上優先序：Arial Unicode MS -> Heiti TC -> STHeiti。
matplotlib.rcParams["font.sans-serif"] = [
    "Arial Unicode MS", "Heiti TC", "STHeiti", "Hiragino Sans GB", "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DB_PATH = REPO / "data" / "cache" / "price_cache.db"

US_TICKER = "SPY"
TW_TICKER = "0050.TW"
START_DATE = "2016-01-04"  # SPY 快取起點；兩邊重疊窗口

# 迷思門檻
US_DOWN_THRESHOLDS = [-0.01, -0.02, -0.03]   # 美股「大跌」（-1% / -2% / -3%）
TW_DOWN_MAIN = 0.0                            # 台股「補跌」主定義：下跌
TW_DOWN_STRONG = -0.01                        # 較強版：跌逾 1%

# bootstrap
BOOT_BLOCK = 5
BOOT_N = 2000
BOOT_MAIN_THRESHOLD = -0.02  # 主門檻用於 bootstrap CI

# HAC
HAC_LAG = 5


# ----------------------------------------------------------------------------
# Data load
# ----------------------------------------------------------------------------
def load_series(ticker: str, start: str | None = None) -> pd.DataFrame:
    con = sqlite3.connect(str(DB_PATH))
    try:
        df = pd.read_sql(
            "SELECT date, close, adj_close FROM price_data WHERE ticker=? ORDER BY date",
            con,
            params=(ticker,),
            parse_dates=["date"],
        )
    finally:
        con.close()
    # 用 adj_close 算報酬；若 adj_close 有 null 才 fallback close
    px = df["adj_close"].where(df["adj_close"].notna(), df["close"])
    df = df.assign(price=px.astype(float))
    df = df.dropna(subset=["price"]).drop_duplicates(subset=["date"]).sort_values("date")
    if start is not None:
        df = df[df["date"] >= pd.Timestamp(start)]
    df = df.reset_index(drop=True)
    df["ret"] = df["price"].pct_change()
    return df[["date", "price", "ret"]]


# ----------------------------------------------------------------------------
# Alignment: US day D -> next TW trading day T (strictly greater), no lookahead
# ----------------------------------------------------------------------------
def build_pairs(us: pd.DataFrame, tw: pd.DataFrame) -> pd.DataFrame:
    """對每個 US 日 D（有 r_us），找 T = 資料中 strictly > D 的最小 TW 交易日，map r_us(D)->r_tw(T)。

    US close(D) 發生於 TW open(T) 之前 → legitimate timing、無 lookahead。
    採 US-forward 事件索引；台股假日可能造成 many-to-one（診斷計數）。
    """
    tw_valid = tw.dropna(subset=["ret"]).sort_values("date").reset_index(drop=True)
    tw_dates = tw_valid["date"].to_numpy()  # sorted TW trading days with valid ret
    tw_ret = tw_valid["ret"].to_numpy()

    rows = []
    for _, r in us.dropna(subset=["ret"]).iterrows():
        d = r["date"]
        # T = 最小的 TW 交易日 strictly greater than D
        idx = np.searchsorted(tw_dates, np.datetime64(d), side="right")
        if idx >= len(tw_dates):
            continue  # D 之後沒有 TW 交易日
        rows.append(
            {
                "us_date": d,
                "r_us": float(r["ret"]),
                "tw_date": pd.Timestamp(tw_dates[idx]),
                "r_tw": float(tw_ret[idx]),
            }
        )
    pairs = pd.DataFrame(rows).sort_values("us_date").reset_index(drop=True)
    return pairs


# ----------------------------------------------------------------------------
# Stats helpers
# ----------------------------------------------------------------------------
def prop_ci_wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score 95% CI for a proportion."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / denom
    return (center - half, center + half)


def diff_in_prop_z(k1: int, n1: int, k2: int, n2: int) -> dict:
    """Two-proportion z-test (unpooled SE for CI, pooled SE for the test stat).

    group1 = US big down; group2 = US not big down (comparison / control).
    Returns diff (p1 - p2), z, two-sided p, 95% CI of diff.
    """
    if n1 == 0 or n2 == 0:
        return {"diff": float("nan"), "z": float("nan"), "p_value": float("nan"),
                "ci95": [float("nan"), float("nan")]}
    p1, p2 = k1 / n1, k2 / n2
    diff = p1 - p2
    # pooled SE for hypothesis test (H0: p1 = p2)
    p_pool = (k1 + k2) / (n1 + n2)
    se_pool = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    z = diff / se_pool if se_pool > 0 else float("nan")
    p_val = 2 * (1 - stats.norm.cdf(abs(z))) if np.isfinite(z) else float("nan")
    # unpooled SE for CI
    se_unpool = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    zc = 1.959963984540054
    ci = [diff - zc * se_unpool, diff + zc * se_unpool]
    return {"diff": diff, "z": z, "p_value": p_val, "ci95": ci}


def contingency_test(a: int, b: int, c: int, d: int) -> dict:
    """2x2: [[a,b],[c,d]] = [[US big down & TW down, US big down & TW up],
                              [US not big down & TW down, US not big down & TW up]].

    Uses Fisher exact when any expected cell < 5 (small sample), else chi-square.
    Reports both where computable.
    """
    table = np.array([[a, b], [c, d]], dtype=float)
    out = {"table": [[int(a), int(b)], [int(c), int(d)]]}
    n = table.sum()
    if n == 0:
        return out
    row = table.sum(axis=1, keepdims=True)
    col = table.sum(axis=0, keepdims=True)
    expected = row @ col / n
    min_expected = float(expected.min())
    out["min_expected_count"] = min_expected
    use_fisher = min_expected < 5
    out["test_used"] = "fisher_exact" if use_fisher else "chi2"
    # Fisher (always compute if 2x2 valid)
    try:
        odds, p_fisher = stats.fisher_exact([[int(a), int(b)], [int(c), int(d)]])
        out["fisher_odds_ratio"] = float(odds)
        out["fisher_p_value"] = float(p_fisher)
    except Exception:
        out["fisher_odds_ratio"] = float("nan")
        out["fisher_p_value"] = float("nan")
    # Chi-square with Yates correction off for reporting (report both stat + p)
    try:
        chi2, p_chi2, dof, _ = stats.chi2_contingency(
            [[int(a), int(b)], [int(c), int(d)]], correction=False
        )
        out["chi2_stat"] = float(chi2)
        out["chi2_p_value"] = float(p_chi2)
    except Exception:
        out["chi2_stat"] = float("nan")
        out["chi2_p_value"] = float("nan")
    out["primary_p_value"] = out["fisher_p_value"] if use_fisher else out["chi2_p_value"]
    return out


def block_bootstrap_prob(cond_mask: np.ndarray, tw_down: np.ndarray,
                         block: int, n_boot: int, seed: int) -> dict:
    """Block bootstrap 95% CI for P(TW down | condition).

    Resample contiguous blocks over the full (time-ordered) pair series, then
    recompute the conditional probability on each resample. Preserves short-run
    dependence (block length = 5).
    """
    rng = np.random.default_rng(seed)
    n = len(cond_mask)
    if n == 0:
        return {"point": float("nan"), "ci95": [float("nan"), float("nan")], "n_boot": n_boot}
    n_blocks = int(np.ceil(n / block))
    ests = []
    for _ in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) % n for s in starts])[:n]
        cm = cond_mask[idx]
        td = tw_down[idx]
        denom = cm.sum()
        if denom == 0:
            continue
        ests.append(td[cm].mean())
    ests = np.array(ests)
    point = float(tw_down[cond_mask].mean()) if cond_mask.sum() > 0 else float("nan")
    if len(ests) == 0:
        ci = [float("nan"), float("nan")]
    else:
        ci = [float(np.percentile(ests, 2.5)), float(np.percentile(ests, 97.5))]
    return {"point": point, "ci95": ci, "n_boot_effective": int(len(ests))}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    us_full = load_series(US_TICKER)              # 用於報 US 資料期間
    tw_full = load_series(TW_TICKER)
    us = load_series(US_TICKER, START_DATE)
    tw = load_series(TW_TICKER, START_DATE)

    pairs = build_pairs(us, tw)

    # ---- 診斷：many-to-one（台股假日）----
    dup_counts = pairs["tw_date"].value_counts()
    n_tw_shared = int((dup_counts > 1).sum())          # 有多個 US 訊號的 TW 日數
    n_pairs_in_shared = int(dup_counts[dup_counts > 1].sum())
    n_pairs = len(pairs)

    r_us = pairs["r_us"].to_numpy()
    r_tw = pairs["r_tw"].to_numpy()
    tw_down_main = (r_tw < TW_DOWN_MAIN)
    tw_down_strong = (r_tw < TW_DOWN_STRONG)

    # ---- base rate（去重 TW 日，反映真實無條件下跌頻率）----
    tw_target = pairs.drop_duplicates(subset=["tw_date"])
    base_down_main = float((tw_target["r_tw"] < TW_DOWN_MAIN).mean())
    base_down_strong = float((tw_target["r_tw"] < TW_DOWN_STRONG).mean())
    n_tw_unique = int(len(tw_target))

    # ---- base rate（event universe，每 US 日一票；與條件機率同分母口徑）----
    base_down_main_event = float(tw_down_main.mean())
    base_down_strong_event = float(tw_down_strong.mean())

    # ---- 對照組：US 沒大跌（r_us >= 0）----
    ctrl_mask = r_us >= 0.0
    n_ctrl = int(ctrl_mask.sum())
    ctrl_down_main = float(tw_down_main[ctrl_mask].mean()) if n_ctrl else float("nan")
    ctrl_down_strong = float(tw_down_strong[ctrl_mask].mean()) if n_ctrl else float("nan")

    # ---- 每門檻條件機率 + 2x2 + diff-in-prop ----
    threshold_results = {}
    seen = set()
    ordered = []
    for th in [0.0] + US_DOWN_THRESHOLDS:
        if th not in seen:
            ordered.append(th)
            seen.add(th)

    for th in ordered:
        down_mask = r_us < th            # US big down（含 th=0 的寬鬆版：US 收黑）
        not_mask = ~down_mask            # US 沒到此門檻
        n_ev = int(down_mask.sum())
        n_not = int(not_mask.sum())

        # 主定義 TW down (<0)
        k_down = int(tw_down_main[down_mask].sum())
        p_cond_main = float(k_down / n_ev) if n_ev else float("nan")
        ci_cond_main = list(prop_ci_wilson(k_down, n_ev))

        # 較強版 TW down (<-1%)
        k_down_s = int(tw_down_strong[down_mask].sum())
        p_cond_strong = float(k_down_s / n_ev) if n_ev else float("nan")
        ci_cond_strong = list(prop_ci_wilson(k_down_s, n_ev))

        # 對照組（US 沒到此門檻）主定義下跌率
        k_not_down = int(tw_down_main[not_mask].sum())
        p_not_down = float(k_not_down / n_not) if n_not else float("nan")

        # diff-in-prop（event vs not-event, 主定義）
        dip = diff_in_prop_z(k_down, n_ev, k_not_down, n_not)

        # 2x2 列聯表（主定義）
        a = k_down                       # US big down & TW down
        b = n_ev - k_down                # US big down & TW up
        c = k_not_down                   # US not big down & TW down
        d = n_not - k_not_down           # US not big down & TW up
        cont = contingency_test(a, b, c, d)

        small_sample = n_ev < 30
        threshold_results[f"us_below_{th:+.2f}"] = {
            "us_down_threshold": th,
            "n_event": n_ev,
            "small_sample_caveat": small_sample,
            "P_tw_down_given_event_main": p_cond_main,       # P(TW<0 | US<th)
            "P_tw_down_given_event_main_ci95": ci_cond_main,
            "P_tw_down_strong_given_event": p_cond_strong,   # P(TW<-1% | US<th)
            "P_tw_down_strong_given_event_ci95": ci_cond_strong,
            "P_tw_down_given_not_event_main": p_not_down,    # 對照：US 沒到門檻
            "n_not_event": n_not,
            "diff_in_prop_vs_not_event": dip,                # event - not_event
            "contingency_2x2": cont,
        }

    # ---- 傳導幅度回歸：r_tw ~ a + b*r_us, HAC(lag=5) ----
    X = sm.add_constant(r_us)
    ols = sm.OLS(r_tw, X).fit()
    hac = sm.OLS(r_tw, X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAG})
    reg = {
        "spec": "r_tw(T) ~ alpha + beta * r_us(D)",
        "n_obs": int(len(r_tw)),
        "alpha": float(hac.params[0]),
        "beta": float(hac.params[1]),
        "alpha_se_hac": float(hac.bse[0]),
        "beta_se_hac": float(hac.bse[1]),
        "alpha_t_hac": float(hac.tvalues[0]),
        "beta_t_hac": float(hac.tvalues[1]),
        "alpha_p_hac": float(hac.pvalues[0]),
        "beta_p_hac": float(hac.pvalues[1]),
        "r_squared": float(ols.rsquared),
        "hac_lag": HAC_LAG,
        "note": "beta>0 = 同向傳導強度：US 每跌 1%（r_us=-1）對應 TW 次日平均報酬 -beta%（beta=0.485 ⇒ 約 -0.485%）；斜率遠<1 代表非全額補跌；SE 用 Newey-West HAC lag=5",
    }

    # ---- 主門檻 block bootstrap CI ----
    main_mask = r_us < BOOT_MAIN_THRESHOLD
    boot = block_bootstrap_prob(main_mask, tw_down_main.astype(float),
                                block=BOOT_BLOCK, n_boot=BOOT_N, seed=SEED)
    boot["threshold"] = BOOT_MAIN_THRESHOLD
    boot["definition"] = "P(TW<0 | US<-2%), block bootstrap"

    # ---- Robustness：每 TW 日僅保留最新（freshest）US 訊號（去重 many-to-one）----
    # 對每個 TW 日，保留 us_date 最大的那筆（最接近 TW open 的隔夜訊號）
    dedup = pairs.sort_values(["tw_date", "us_date"]).drop_duplicates(subset=["tw_date"], keep="last")
    r_us_dd = dedup["r_us"].to_numpy()
    r_tw_dd = dedup["r_tw"].to_numpy()
    dd_tw_down = (r_tw_dd < TW_DOWN_MAIN)
    robustness = {"n_pairs_dedup": int(len(dedup)), "by_threshold": {}}
    for th in ordered:
        m = r_us_dd < th
        n_ev = int(m.sum())
        robustness["by_threshold"][f"us_below_{th:+.2f}"] = {
            "n_event": n_ev,
            "P_tw_down_given_event_main": float(dd_tw_down[m].mean()) if n_ev else float("nan"),
        }
    robustness["base_rate_tw_down_main"] = float(dd_tw_down.mean())

    # ---- Bucketed conditional prob（給圖用）----
    bucket_edges = [-np.inf, -0.02, -0.01, 0.0, 0.01, 0.02, np.inf]
    bucket_labels = ["US<-2%", "-2%~-1%", "-1%~0%", "0%~+1%", "+1%~+2%", "US>+2%"]
    bucket_idx = np.digitize(r_us, bucket_edges[1:-1], right=False)
    buckets = []
    for i, lab in enumerate(bucket_labels):
        m = bucket_idx == i
        n_b = int(m.sum())
        p_b = float(tw_down_main[m].mean()) if n_b else float("nan")
        ci_b = list(prop_ci_wilson(int(tw_down_main[m].sum()), n_b))
        buckets.append({"label": lab, "n": n_b, "P_tw_down_next": p_b, "ci95": ci_b})

    # ------------------------------------------------------------------
    # Assemble results
    # ------------------------------------------------------------------
    results = {
        "experiment_id": "k1627",
        "title": "美股大跌、台股隔天必補跌？隔夜傳導的實際條件機率",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "us_ticker": US_TICKER,
            "tw_ticker": TW_TICKER,
            "tw_proxy_note": "0050.TW 作為 TAIEX（台股大盤）proxy — 本系統慣例，非官方指數",
            "source": "data/cache/price_cache.db :: price_data (adj_close close-to-close returns)",
            "us_full_range": [us_full["date"].min().strftime("%Y-%m-%d"),
                              us_full["date"].max().strftime("%Y-%m-%d")],
            "tw_full_range": [tw_full["date"].min().strftime("%Y-%m-%d"),
                              tw_full["date"].max().strftime("%Y-%m-%d")],
            "analysis_start": START_DATE,
            "n_us_days_2016plus": int(us["ret"].notna().sum()),
            "n_tw_days_2016plus": int(tw["ret"].notna().sum()),
            "n_pairs": n_pairs,
            "n_tw_unique_targets": n_tw_unique,
        },
        "alignment": {
            "rule": "US-forward: r_us(D) -> r_tw(T), T=min TW trading day strictly > D",
            "no_lookahead_reason": "US close(D) 發生於 TW open(T) 之前（session-boundary timing）",
            "many_to_one_diagnostic": {
                "n_tw_days_shared_by_multiple_us_signals": n_tw_shared,
                "n_pairs_involved_in_sharing": n_pairs_in_shared,
                "pct_pairs_in_sharing": float(n_pairs_in_shared / n_pairs) if n_pairs else float("nan"),
                "note": "台股假日時多個 US 日對到同一 TW 日；robustness 版對每 TW 日只保留最新 US 訊號",
            },
        },
        "base_rate": {
            "definition_main": "P(TW next-day return < 0)  無條件",
            "P_tw_down_main_unique_twdays": base_down_main,
            "P_tw_down_strong_unique_twdays": base_down_strong,
            "n_unique_tw_days": n_tw_unique,
            "P_tw_down_main_event_universe": base_down_main_event,
            "P_tw_down_strong_event_universe": base_down_strong_event,
        },
        "control_us_nonneg": {
            "definition": "P(TW down next | r_us(D) >= 0)  美股沒下跌時",
            "n": n_ctrl,
            "P_tw_down_main": ctrl_down_main,
            "P_tw_down_strong": ctrl_down_strong,
        },
        "by_threshold": threshold_results,
        "regression": reg,
        "bootstrap_main_threshold": boot,
        "robustness_dedup_freshest_us_signal": robustness,
        "buckets_for_figure": buckets,
        "tw_down_definitions": {
            "main": "r_tw(T) < 0 (下跌)",
            "strong": "r_tw(T) < -1% (跌逾 1%)",
        },
    }

    out_json = HERE / "k1627_results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=float)
    print(f"[k1627] results -> {out_json}")

    # ------------------------------------------------------------------
    # Figures
    # ------------------------------------------------------------------
    _fig_conditional_prob(buckets, base_down_main_event, threshold_results)
    _fig_transmission_scatter(r_us, r_tw, reg)

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    print("\n===== K1627 SUMMARY =====")
    print(f"n_pairs={n_pairs}  n_tw_unique={n_tw_unique}  "
          f"many-to-one TW days={n_tw_shared} ({n_pairs_in_shared} pairs)")
    print(f"BASE RATE P(TW down)         = {base_down_main_event:.3f} (event universe) / "
          f"{base_down_main:.3f} (unique TW days)")
    print(f"CONTROL  P(TW down|US>=0)    = {ctrl_down_main:.3f}  (n={n_ctrl})")
    for key, tr in threshold_results.items():
        print(f"  {key}: n={tr['n_event']:4d}  P(TW<0|event)={tr['P_tw_down_given_event_main']:.3f}"
              f"  diff_vs_not={tr['diff_in_prop_vs_not_event']['diff']:+.3f}"
              f"  p={tr['contingency_2x2'].get('primary_p_value', float('nan')):.4g}"
              f"  {'[small n]' if tr['small_sample_caveat'] else ''}")
    print(f"REGRESSION beta={reg['beta']:.4f}  t={reg['beta_t_hac']:.2f}  "
          f"p={reg['beta_p_hac']:.4g}  R2={reg['r_squared']:.4f}")
    print(f"BOOTSTRAP P(TW<0|US<-2%)={boot['point']:.3f}  "
          f"95%CI=[{boot['ci95'][0]:.3f},{boot['ci95'][1]:.3f}]")


def _fig_conditional_prob(buckets, base_rate, threshold_results):
    labels = [b["label"] for b in buckets]
    probs = [b["P_tw_down_next"] for b in buckets]
    ns = [b["n"] for b in buckets]
    los = [max(0.0, b["P_tw_down_next"] - b["ci95"][0]) if np.isfinite(b["ci95"][0]) else 0 for b in buckets]
    his = [max(0.0, b["ci95"][1] - b["P_tw_down_next"]) if np.isfinite(b["ci95"][1]) else 0 for b in buckets]

    fig, ax = plt.subplots(figsize=(9.5, 5.6))
    colors = ["#8B0000", "#C0392B", "#E67E22", "#5DADE2", "#2E86C1", "#1B4F72"]
    x = np.arange(len(labels))
    bars = ax.bar(x, probs, color=colors, yerr=[los, his], capsize=4,
                  edgecolor="black", linewidth=0.6, alpha=0.9)
    ax.axhline(base_rate, color="black", linestyle="--", linewidth=1.4,
               label=f"無條件下跌率 base rate = {base_rate:.1%}")
    ax.axhline(1.0, color="grey", linestyle=":", linewidth=1.0,
               label="迷思宣稱『必』= 100%")
    for xi, p, n in zip(x, probs, ns):
        if np.isfinite(p):
            ax.text(xi, p + 0.02, f"{p:.0%}\n(n={n})", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("P( 台股次一交易日下跌 )", fontsize=11)
    ax.set_ylim(0, 1.12)
    ax.set_title("隔夜美股報酬 vs 台股次日下跌機率（SPY→0050.TW, 2016-2026）\n"
                 "單調上升，但即使美股跌逾 2% 也遠低於『必然』100%", fontsize=11)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    # 註明 x 軸左方向為美股大跌
    ax.annotate("← 美股大跌", xy=(0.02, -0.11), xycoords="axes fraction", fontsize=9, color="#8B0000")
    ax.annotate("美股大漲 →", xy=(0.80, -0.11), xycoords="axes fraction", fontsize=9, color="#1B4F72")
    fig.tight_layout()
    out = HERE / "fig_conditional_prob.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[k1627] figure -> {out}")


def _fig_transmission_scatter(r_us, r_tw, reg):
    fig, ax = plt.subplots(figsize=(8.5, 6.2))
    ax.scatter(r_us * 100, r_tw * 100, s=9, alpha=0.28, color="#2C3E50",
               edgecolors="none", label=f"每日配對 (n={len(r_us)})")
    xs = np.linspace(r_us.min(), r_us.max(), 100)
    ys = reg["alpha"] + reg["beta"] * xs
    ax.plot(xs * 100, ys * 100, color="#C0392B", linewidth=2.2,
            label=(f"OLS: r_tw = {reg['alpha']*100:.3f} + {reg['beta']:.3f}·r_us\n"
                   f"β t(HAC)={reg['beta_t_hac']:.1f}, R²={reg['r_squared']:.3f}"))
    ax.axhline(0, color="grey", linewidth=0.7)
    ax.axvline(0, color="grey", linewidth=0.7)
    # 標示 US 大跌區
    ax.axvspan(r_us.min() * 100, -2, color="#8B0000", alpha=0.06)
    ax.text(r_us.min() * 100 * 0.95, r_tw.max() * 100 * 0.9, "美股跌逾 2%",
            color="#8B0000", fontsize=9)
    ax.set_xlabel("隔夜美股 SPY 日報酬 r_us(D)  (%)", fontsize=11)
    ax.set_ylabel("台股 0050.TW 次日報酬 r_tw(T)  (%)", fontsize=11)
    ax.set_title("隔夜傳導散點圖：美股報酬 → 台股次日報酬（2016-2026）\n"
                 f"β={reg['beta']:.3f}（US 每跌 1% ⇒ TW 次日平均 {-reg['beta']:.3f}%），但散布極廣", fontsize=11)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    out = HERE / "fig_transmission_scatter.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[k1627] figure -> {out}")


if __name__ == "__main__":
    main()
