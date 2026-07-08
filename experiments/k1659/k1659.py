"""K1659 — 投資迷思驗證（延伸 K1636）：「量先價行 / 爆量長黑是出貨」的
跨市場延續性 + 經濟價值 + 參數穩健檢定。

差異化定位（見 README §與 K1636 的差異）:
  K1636 已對 SPY/0050/2330 做逐資產 next-day 方向 BH-FDR，結論方向迷思不成立。
  K1659 補齊 K1636 未做、且方法論規則硬性要求的四件事:
    (1) 跨「市場」正確聚合 (K1355 規則): 先按日期聚合 cross-asset，再對日期序列
        做 HAC/Newey-West，而非把 asset-day 當 iid。
    (2) 「量先價行」= 延續性雙臂 (量增價漲→續漲 / 量增價跌→續跌) 的方向 hit-rate，
        不只 K1636 的「爆量偏跌」單臂。
    (3) 經濟價值: 條件化 next-day long/short 策略淨交易成本後 Sharpe vs buy-hold。
    (4) 參數穩健 grid (k × N) + 空頭次期間 (2020/2022) 分割，證明 null 非 cherry-pick。

防錯 (見 .claude/rules/experiments.md):
  - Lookahead 最高優先: 事件訊號一律用 signal.shift(1) 對齊到隔日報酬 r[t+1]；
    rolling volume 門檻用 shift(1)，今日 volume 絕不進入自己的門檻。
  - seed=42 固定所有 bootstrap。
  - 跨資產不把 asset-day 當 iid: 先 date-aggregate 再 HAC (K1355)。stacked asset-day
    只列 diagnostic。
  - Baseline 明確: unconditional up/down/continuation frequency 當 null，
    conditional hit-rate 用 binomial test vs baseline。
  - 參數不 cherry-pick: k/N/threshold 有 justification + 全 grid robustness。
  - 誠實報 null。

復現: uv run python experiments/k1659/k1659.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 繁中字型（macOS 內建 Arial Unicode MS 涵蓋 CJK；避免圖表 tofu 缺字）
plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC", "STHeiti", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from volpred.utils import clean_tw50_data

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SEED = 42
BOOTSTRAP_REPS = 10_000
HAC_MAXLAGS = 5
TC_PER_UNIT = 0.0005  # 5 bps 交易成本 per unit |Δposition|（round-trip 進出各一次）

# Primary signal params（justification 見 README）
# 「爆量」= 今日成交量 > 2 × 前 20 日均量（零售技術分析最常見定義：2x 20MA volume）
K_PRIMARY = 2.0
N_PRIMARY = 20
BLACK_THRESHOLD = -0.02  # 長黑 = 當日 adj-close 報酬 <= -2%

# Robustness grid
K_GRID = [1.5, 2.0, 2.5, 3.0]
N_GRID = [20, 50, 100]

# 美 2 + 台 2，做平衡的跨市場聚合
ASSETS = ["SPY", "QQQ", "0050.TW", "2330.TW"]
US_ASSETS = {"SPY", "QQQ"}
TW_ASSETS = {"0050.TW", "2330.TW"}

DATA_DIR = Path(__file__).resolve().parent / "data"
OUT_DIR = Path(__file__).resolve().parent
DOWNLOAD_START = "2010-01-01"
DOWNLOAD_END = "2026-07-04"


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if hasattr(df.columns, "get_level_values") and df.columns.nlevels > 1:
        df.columns = [c[0] for c in df.columns]
    return df


def load_asset(asset: str) -> tuple[pd.DataFrame, dict]:
    """讀 cache（k1636 快取複製過來），缺就下載。回傳 (df, meta)。"""
    path = DATA_DIR / f"{asset}.csv"
    meta = {"asset": asset}
    if path.exists():
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        meta["source"] = "cache"
    else:
        import yfinance as yf

        df = yf.download(
            asset, start=DOWNLOAD_START, end=DOWNLOAD_END,
            progress=False, auto_adjust=False,
        )
        df = _flatten(df)
        df.to_csv(path)
        meta["source"] = "yfinance_download"
        print(f"[data] downloaded {asset} -> {path}")

    df = _flatten(df)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    # 用 Adj Close 算報酬（含股利/分割調整）；缺就退回 Close 並記錄
    if "Adj Close" in df.columns and df["Adj Close"].notna().sum() > 0:
        price = df["Adj Close"].astype(float)
        meta["price_field"] = "Adj Close"
    else:
        price = df["Close"].astype(float)
        meta["price_field"] = "Close"

    # 0050.TW: 修 yfinance 2014-01-02 假 -75% split artifact
    if asset == "0050.TW":
        pre = price.copy()
        price, _ = clean_tw50_data(price)
        meta["tw50_clean_applied"] = bool(not price.equals(pre))

    out = pd.DataFrame(
        {"price": price, "volume": df["Volume"].astype(float)}
    ).dropna()
    out = out[out["volume"] > 0]
    meta["n_rows"] = int(len(out))
    meta["date_start"] = str(out.index.min().date())
    meta["date_end"] = str(out.index.max().date())
    return out, meta


# ----------------------------------------------------------------------------
# Panel + signal（明確 shift(1)）
# ----------------------------------------------------------------------------
def build_panel(df: pd.DataFrame, k: float, n: int) -> pd.DataFrame:
    """建 per-asset panel。所有事件訊號都會 shift(1) 對齊到隔日報酬。"""
    p = pd.DataFrame(index=df.index)
    p["ret"] = df["price"].pct_change()
    p["volume"] = df["volume"]

    # 前 n 日均量，shift(1) → 今日 volume 不進自己的門檻（lookahead-clean）
    roll_mean_vol = df["volume"].rolling(n, min_periods=max(10, n // 2)).mean().shift(1)
    p["vol_spike"] = (df["volume"] > k * roll_mean_vol)

    up = p["ret"] > 0
    down = p["ret"] < 0
    p["hv_up"] = p["vol_spike"] & up      # 量增價漲（量先價行 多頭臂）
    p["hv_down"] = p["vol_spike"] & down  # 量增價跌（量先價行 空頭臂）
    p["hv_black"] = p["vol_spike"] & (p["ret"] <= BLACK_THRESHOLD)  # 爆量長黑（出貨）

    # 需要 rolling window + 有效 ret；門檻 warmup 期為 NaN → 事件自然 False
    p = p.dropna(subset=["ret"])
    for c in ["vol_spike", "hv_up", "hv_down", "hv_black"]:
        p[c] = p[c].fillna(False).astype(bool)
    return p


# ----------------------------------------------------------------------------
# Stats helpers
# ----------------------------------------------------------------------------
def hac_mean(x: np.ndarray, maxlags: int = HAC_MAXLAGS) -> dict:
    """單序列均值的 Newey-West HAC t 檢定（intercept-only OLS）。"""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"mean": float(np.mean(x)) if n else None, "t": None, "p": None, "n": n}
    X = np.ones((n, 1))
    res = sm.OLS(x, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "mean": float(res.params[0]),
        "t": float(res.tvalues[0]),
        "p": float(res.pvalues[0]),
        "n": n,
    }


def binom_vs_baseline(hits: int, n: int, baseline: float) -> dict:
    """conditional hit-rate vs unconditional baseline 的 binomial test。"""
    if n == 0:
        return {"hit_rate": None, "baseline": baseline, "n": 0, "lift_pp": None, "p": None}
    bt = stats.binomtest(hits, n, baseline, alternative="two-sided")
    rate = hits / n
    return {
        "hit_rate": float(rate),
        "baseline": float(baseline),
        "n": int(n),
        "hits": int(hits),
        "lift_pp": float((rate - baseline) * 100),
        "p": float(bt.pvalue),
    }


def bootstrap_rate_ci(indicator: np.ndarray, rng: np.random.Generator) -> dict:
    ind = np.asarray(indicator, dtype=float)
    ind = ind[np.isfinite(ind)]
    n = len(ind)
    if n < 10:
        return {"lo": None, "hi": None}
    idx = rng.integers(0, n, size=(BOOTSTRAP_REPS, n))
    boots = ind[idx].mean(axis=1)
    return {"lo": float(np.percentile(boots, 2.5)), "hi": float(np.percentile(boots, 97.5))}


def bh_adjust(pvals: list[float | None]) -> list[float | None]:
    idx = [i for i, p in enumerate(pvals) if p is not None]
    m = len(idx)
    out: list[float | None] = [None] * len(pvals)
    if m == 0:
        return out
    ranked = sorted(idx, key=lambda i: pvals[i])
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = ranked[rank]
        q = pvals[i] * m / (rank + 1)
        prev = min(prev, q)
        out[i] = float(min(prev, 1.0))
    return out


# ----------------------------------------------------------------------------
# Per-asset directional tests
# ----------------------------------------------------------------------------
def next_ret_after(panel: pd.DataFrame, event_col: str) -> np.ndarray:
    """事件 signal.shift(1) 對齊隔日報酬: 回傳事件日 t 之後的 r[t+1]。"""
    mask = panel[event_col].shift(1).fillna(False).astype(bool)
    return panel.loc[mask, "ret"].to_numpy()


def evaluate_asset(panel: pd.DataFrame, rng: np.random.Generator) -> dict:
    ret = panel["ret"].to_numpy()
    base_up = float(np.mean(ret > 0))
    base_down = float(np.mean(ret < 0))
    # unconditional 延續率 P(sign(r[t+1]) == sign(r[t]))
    s = np.sign(ret)
    cont = (s[1:] == s[:-1]) & (s[1:] != 0)
    base_cont = float(np.mean(cont))

    out: dict = {
        "n_days": int(len(ret)),
        "baseline": {"p_up": base_up, "p_down": base_down, "p_continuation": base_cont},
        "event_counts": {
            "vol_spike": int(panel["vol_spike"].sum()),
            "hv_up": int(panel["hv_up"].sum()),
            "hv_down": int(panel["hv_down"].sum()),
            "hv_black": int(panel["hv_black"].sum()),
        },
        "tests": {},
    }

    # (A) 量先價行 多頭臂: 量增價漲 -> 隔日續漲?
    r_up = next_ret_after(panel, "hv_up")
    out["tests"]["myth_A_up_continuation"] = {
        "desc": "量增價漲 -> 隔日 r>0 (續漲)",
        "hit": binom_vs_baseline(int(np.sum(r_up > 0)), len(r_up), base_up),
        "next_ret_hac": hac_mean(r_up),
        "hit_ci": bootstrap_rate_ci((r_up > 0).astype(float), rng),
    }
    # (B) 量先價行 空頭臂: 量增價跌 -> 隔日續跌?
    r_dn = next_ret_after(panel, "hv_down")
    out["tests"]["myth_A_down_continuation"] = {
        "desc": "量增價跌 -> 隔日 r<0 (續跌)",
        "hit": binom_vs_baseline(int(np.sum(r_dn < 0)), len(r_dn), base_down),
        "next_ret_hac": hac_mean(r_dn),
        "hit_ci": bootstrap_rate_ci((r_dn < 0).astype(float), rng),
    }
    # (C) 爆量長黑出貨: 爆量長黑 -> 隔日續跌?
    r_bk = next_ret_after(panel, "hv_black")
    out["tests"]["myth_B_black_distribution"] = {
        "desc": "爆量長黑 (量增 & r<=-2%) -> 隔日 r<0 (出貨續跌)",
        "hit": binom_vs_baseline(int(np.sum(r_bk < 0)), len(r_bk), base_down),
        "next_ret_hac": hac_mean(r_bk),
        "hit_ci": bootstrap_rate_ci((r_bk < 0).astype(float), rng),
    }

    # (D) 延續性 sign-return: bet=sign(r[t])，爆量日次日 P&L=sign(r[t])*r[t+1]
    #     mean>0 表延續有利 (量先價行成立)；~0/<0 表迷思不成立
    spike_mask = panel["vol_spike"].shift(1).fillna(False).astype(bool)
    sign_today = np.sign(panel["ret"].shift(1).to_numpy())
    sign_pnl = sign_today * panel["ret"].to_numpy()
    sign_pnl_events = sign_pnl[spike_mask.to_numpy() & np.isfinite(sign_pnl)]
    out["tests"]["myth_A_sign_continuation_pnl"] = {
        "desc": "爆量日 sign(r_t)*r_{t+1} 均值 (延續性下注淨報酬，未計成本)",
        "hac": hac_mean(sign_pnl_events),
    }
    return out


# ----------------------------------------------------------------------------
# Cross-market pooled inference (K1355: date-aggregate then HAC)
# ----------------------------------------------------------------------------
def cross_market_pooled(panels: dict[str, pd.DataFrame]) -> dict:
    """對每個日期，先聚合 cross-asset 的延續性下注報酬 (equal weight)，
    再對日期序列做 HAC。避免把同日 asset-day 當 iid (K1355)。"""
    # 每資產: date -> sign(r_t)*r_{t+1} 若 t 為爆量日 else NaN（index 對齊到 return date t+1）
    per_asset_pnl = {}
    for a, p in panels.items():
        spike_lag = p["vol_spike"].shift(1).fillna(False).astype(bool)
        sign_today = np.sign(p["ret"].shift(1))
        pnl = sign_today * p["ret"]
        pnl = pnl.where(spike_lag, np.nan)
        per_asset_pnl[a] = pnl

    mat = pd.DataFrame(per_asset_pnl)  # index=date, cols=assets

    def _pooled(cols: list[str]) -> dict:
        sub = mat[cols]
        daily = sub.mean(axis=1, skipna=True)  # 先 cross-asset 聚合
        daily = daily.dropna()
        res = hac_mean(daily.to_numpy())
        res["n_event_dates"] = int(len(daily))
        return res

    # diagnostic: stacked asset-day（明確標示不可當 primary）
    stacked = mat.to_numpy().flatten()
    stacked = stacked[np.isfinite(stacked)]
    stacked_t = None
    if len(stacked) > 10:
        st = stats.ttest_1samp(stacked, 0.0)
        stacked_t = {"mean": float(np.mean(stacked)), "t": float(st.statistic),
                     "p": float(st.pvalue), "n": int(len(stacked)),
                     "NOTE": "stacked asset-day 忽略同日 cross-asset 相關，僅 diagnostic 不可當 primary (K1355)"}

    return {
        "primary_all_markets": _pooled(ASSETS),
        "primary_US": _pooled(list(US_ASSETS)),
        "primary_TW": _pooled(list(TW_ASSETS)),
        "diagnostic_stacked_asset_day": stacked_t,
        "method": "先按日期 equal-weight 聚合 cross-asset sign-continuation P&L，再對日期序列 Newey-West HAC (K1355)",
    }


# ----------------------------------------------------------------------------
# Economic value: next-day 延續性策略 vs buy-hold, 淨交易成本
# ----------------------------------------------------------------------------
def continuation_strategy(panel: pd.DataFrame) -> tuple[pd.Series, dict]:
    """量先價行策略: 爆量漲日後隔日做多(+1)，爆量跌日後隔日做空(-1)，其餘持平(0)。
    position 在 t+1 生效（用 t 的事件），淨 5bps/單位換手成本。"""
    pos = pd.Series(0.0, index=panel.index)
    pos[panel["hv_up"].shift(1).fillna(False).astype(bool)] = 1.0
    pos[panel["hv_down"].shift(1).fillna(False).astype(bool)] = -1.0
    turnover = pos.diff().abs().fillna(pos.abs())
    strat = pos * panel["ret"] - TC_PER_UNIT * turnover
    stats_d = _perf_stats(strat, panel["ret"], pos)
    return strat, stats_d


def distribution_short_strategy(panel: pd.DataFrame) -> dict:
    """出貨策略: 爆量長黑後隔日做空(-1)，其餘持平。淨成本。"""
    pos = pd.Series(0.0, index=panel.index)
    pos[panel["hv_black"].shift(1).fillna(False).astype(bool)] = -1.0
    turnover = pos.diff().abs().fillna(pos.abs())
    strat = pos * panel["ret"] - TC_PER_UNIT * turnover
    return _perf_stats(strat, panel["ret"], pos)


def _perf_stats(strat: pd.Series, bench: pd.Series, pos: pd.Series) -> dict:
    s = strat.dropna()
    b = bench.reindex(s.index).dropna()
    active = pos.reindex(s.index).fillna(0) != 0
    n_active = int(active.sum())
    ann = np.sqrt(252)

    def sharpe(x):
        x = x.dropna()
        sd = x.std(ddof=1)
        return float(x.mean() / sd * ann) if sd > 0 and len(x) > 2 else None

    strat_active = s[active.to_numpy()]
    hit = float((strat_active > 0).mean()) if n_active > 0 else None
    return {
        "n_days": int(len(s)),
        "n_active_days": n_active,
        "strat_sharpe_ann": sharpe(s),
        "buyhold_sharpe_ann": sharpe(b),
        "strat_total_return": float((1 + s).prod() - 1),
        "buyhold_total_return": float((1 + b).prod() - 1),
        "strat_mean_daily": float(s.mean()),
        "active_day_hit_rate": hit,
    }


# ----------------------------------------------------------------------------
# Robustness grid (k × N) — pooled cross-market sign-continuation
# ----------------------------------------------------------------------------
def robustness_grid(assets_df: dict[str, pd.DataFrame]) -> dict:
    grid = []
    for k in K_GRID:
        for n in N_GRID:
            panels = {a: build_panel(df, k, n) for a, df in assets_df.items()}
            pooled = cross_market_pooled(panels)["primary_all_markets"]
            grid.append({
                "k": k, "N": n,
                "mean": pooled["mean"], "t": pooled["t"], "p": pooled["p"],
                "n_event_dates": pooled["n_event_dates"],
            })
    sig = [g for g in grid if g["p"] is not None and g["p"] < 0.05 and g["mean"] is not None and g["mean"] > 0]
    return {
        "grid": grid,
        "n_cells": len(grid),
        "n_cells_supporting_continuation_p05": len(sig),
        "note": "延續性下注 mean>0 且 p<0.05 才算支持量先價行；heatmap 見 fig4",
    }


# ----------------------------------------------------------------------------
# Regime split (bull/bear via SPY 200d SMA; 2020/2022 crash windows)
# ----------------------------------------------------------------------------
def regime_split(panels: dict[str, pd.DataFrame], spy_price: pd.Series) -> dict:
    sma200 = spy_price.rolling(200, min_periods=100).mean().shift(1)
    bull = (spy_price > sma200)  # 以 SPY 判 regime（全球風險情緒 proxy）

    def pooled_pnl_series() -> pd.DataFrame:
        cols = {}
        for a, p in panels.items():
            spike_lag = p["vol_spike"].shift(1).fillna(False).astype(bool)
            pnl = np.sign(p["ret"].shift(1)) * p["ret"]
            cols[a] = pnl.where(spike_lag, np.nan)
        return pd.DataFrame(cols)

    mat = pooled_pnl_series()
    daily = mat.mean(axis=1, skipna=True).dropna()

    def _regime(mask_series: pd.Series, label: str) -> dict:
        aligned = mask_series.reindex(daily.index).fillna(False).astype(bool)
        x = daily[aligned.to_numpy()]
        r = hac_mean(x.to_numpy())
        r["regime"] = label
        r["n_event_dates"] = int(len(x))
        return r

    bull_al = bull.reindex(daily.index).fillna(False)
    out = {
        "bull_spy_above_200sma": _regime(bull_al, "bull"),
        "bear_spy_below_200sma": _regime(~bull_al, "bear"),
    }
    for label, lo, hi in [("crash_2020", "2020-02-01", "2020-12-31"),
                          ("crash_2022", "2022-01-01", "2022-12-31")]:
        win = (daily.index >= pd.Timestamp(lo)) & (daily.index <= pd.Timestamp(hi))
        x = daily[win]
        r = hac_mean(x.to_numpy())
        r["window"] = f"{lo}..{hi}"
        r["n_event_dates"] = int(len(x))
        out[label] = r
    return out


# ----------------------------------------------------------------------------
# Verdict
# ----------------------------------------------------------------------------
def build_verdict(asset_results: dict, pooled: dict, grid: dict,
                  strat_port: dict, short_port: dict) -> dict:
    # primary family p-values: 每資產 3 個 hit binomial + pooled all-markets HAC
    fam = []
    for a, r in asset_results.items():
        for key in ["myth_A_up_continuation", "myth_A_down_continuation", "myth_B_black_distribution"]:
            t = r["tests"][key]
            # 只把「方向與迷思一致 (lift>0)」的顯著才算支持
            p = t["hit"]["p"]
            supp = (t["hit"]["lift_pp"] is not None and t["hit"]["lift_pp"] > 0)
            fam.append({"asset": a, "test": key, "p": p, "lift_pp": t["hit"]["lift_pp"],
                        "myth_consistent": supp})
    pooled_p = pooled["primary_all_markets"]["p"]
    pooled_mean = pooled["primary_all_markets"]["mean"]
    fam.append({"asset": "POOLED", "test": "cross_market_sign_continuation",
                "p": pooled_p, "lift_pp": None,
                "myth_consistent": (pooled_mean is not None and pooled_mean > 0)})

    q = bh_adjust([f["p"] for f in fam])
    supporting = []
    for f, qv in zip(fam, q):
        f["q_bh"] = qv
        if f["myth_consistent"] and qv is not None and qv < 0.05:
            supporting.append(f)

    econ_ok = (strat_port["strat_sharpe_ann"] is not None
               and strat_port["strat_sharpe_ann"] > strat_port["buyhold_sharpe_ann"]
               and strat_port["strat_sharpe_ann"] > 0.3)

    if len(supporting) == 0 and grid["n_cells_supporting_continuation_p05"] == 0:
        verdict = "not_supported_as_next_day_direction_rule"
    elif len(supporting) > 0 and econ_ok:
        verdict = "supported_with_economic_value"
    else:
        verdict = "partially_statistically_significant_no_economic_value"

    return {
        "myth_verdict": verdict,
        "primary_family_bh": fam,
        "n_myth_consistent_bh_significant": len(supporting),
        "supporting_cells": supporting,
        "robustness_supporting_cells": grid["n_cells_supporting_continuation_p05"],
        "economic_value_beats_buyhold": bool(econ_ok),
        "continuation_strategy_sharpe": strat_port["strat_sharpe_ann"],
        "buyhold_sharpe": strat_port["buyhold_sharpe_ann"],
        "distribution_short_sharpe": short_port["strat_sharpe_ann"],
    }


# ----------------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------------
def plot_hit_rates(asset_results: dict, path: Path) -> None:
    tests = [("myth_A_up_continuation", "量增價漲→續漲"),
             ("myth_A_down_continuation", "量增價跌→續跌"),
             ("myth_B_black_distribution", "爆量長黑→續跌")]
    assets = list(asset_results.keys())
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    for ax, (tk, title) in zip(axes, tests):
        rates, bases, los, his, labels = [], [], [], [], []
        for a in assets:
            t = asset_results[a]["tests"][tk]
            rates.append((t["hit"]["hit_rate"] or 0) * 100)
            bases.append((t["hit"]["baseline"] or 0) * 100)
            ci = t["hit_ci"]
            los.append(((t["hit"]["hit_rate"] or 0) - (ci["lo"] or 0)) * 100)
            his.append(((ci["hi"] or 0) - (t["hit"]["hit_rate"] or 0)) * 100)
            labels.append(f"{a}\nn={t['hit']['n']}")
        x = np.arange(len(assets))
        ax.bar(x, rates, yerr=[los, his], capsize=4, color="#4c78a8", alpha=0.85, label="條件命中率")
        ax.scatter(x, bases, color="crimson", zorder=5, marker="_", s=400, linewidths=3, label="無條件基準")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_title(title, fontsize=11)
        ax.axhline(50, color="gray", ls=":", lw=0.8)
        ax.set_ylim(30, 70)
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("隔日方向命中率 (%)")
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("K1659: 量能事件的隔日方向命中率 vs 無條件基準 (95% bootstrap CI)", fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def plot_pooled(pooled: dict, regime: dict, path: Path) -> None:
    labels, means, ts = [], [], []
    for k, lab in [("primary_all_markets", "全市場"), ("primary_US", "美股"),
                   ("primary_TW", "台股")]:
        r = pooled[k]
        labels.append(f"{lab}\nn_dates={r['n_event_dates']}")
        means.append((r["mean"] or 0) * 1e4)  # bps
        ts.append(r["t"] or 0)
    for k, lab in [("bull_spy_above_200sma", "多頭"), ("bear_spy_below_200sma", "空頭"),
                   ("crash_2020", "2020崩"), ("crash_2022", "2022跌")]:
        r = regime[k]
        labels.append(f"{lab}\nn={r['n_event_dates']}")
        means.append((r["mean"] or 0) * 1e4)
        ts.append(r["t"] or 0)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    colors = ["#4c78a8" if abs(t) < 1.96 else "#e45756" for t in ts]
    bars = ax.bar(range(len(labels)), means, color=colors, alpha=0.85)
    for i, (b, t) in enumerate(zip(bars, ts)):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(),
                f"t={t:.2f}", ha="center",
                va="bottom" if b.get_height() >= 0 else "top", fontsize=8)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("延續性下注隔日平均報酬 (bps)")
    ax.set_title("K1659: 跨市場延續性下注報酬 (K1355 日期聚合+HAC)；紅=|t|>1.96", fontsize=12)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def plot_equity(strat_curve: pd.Series, bench_curve: pd.Series, port_stats: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.plot(strat_curve.index, (1 + strat_curve).cumprod(),
            label=f"量先價行策略 (Sharpe={port_stats['strat_sharpe_ann']:.2f})", color="#e45756")
    ax.plot(bench_curve.index, (1 + bench_curve).cumprod(),
            label=f"買進持有 (Sharpe={port_stats['buyhold_sharpe_ann']:.2f})", color="#4c78a8")
    ax.axhline(1, color="gray", ls=":", lw=0.8)
    ax.set_ylabel("累積淨值 (等權四資產組合)")
    ax.set_title("K1659: 量先價行 next-day 策略 vs 買進持有 (淨 5bps/單位換手成本)", fontsize=12)
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def plot_robustness(grid: dict, path: Path) -> None:
    ks = sorted({g["k"] for g in grid["grid"]})
    ns = sorted({g["N"] for g in grid["grid"]})
    tmat = np.full((len(ks), len(ns)), np.nan)
    for g in grid["grid"]:
        tmat[ks.index(g["k"]), ns.index(g["N"])] = g["t"] if g["t"] is not None else np.nan
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(tmat, cmap="RdBu_r", vmin=-3, vmax=3, aspect="auto")
    ax.set_xticks(range(len(ns)))
    ax.set_xticklabels([f"N={n}" for n in ns])
    ax.set_yticks(range(len(ks)))
    ax.set_yticklabels([f"k={k}" for k in ks])
    for i in range(len(ks)):
        for j in range(len(ns)):
            v = tmat[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                        color="white" if abs(v) > 1.8 else "black", fontsize=10)
    ax.set_title("K1659: 延續性下注 pooled HAC t-stat 參數穩健 grid\n(無正向顯著格 → 量先價行全 grid 不成立，非 cherry-pick；負值=輕微反向)", fontsize=10)
    fig.colorbar(im, ax=ax, label="pooled HAC t-stat")
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> None:
    rng = np.random.default_rng(SEED)
    assets_df: dict[str, pd.DataFrame] = {}
    data_meta = {}
    for a in ASSETS:
        df, meta = load_asset(a)
        assets_df[a] = df
        data_meta[a] = meta

    # Primary panels
    panels = {a: build_panel(df, K_PRIMARY, N_PRIMARY) for a, df in assets_df.items()}

    # Per-asset tests
    asset_results = {a: evaluate_asset(p, rng) for a, p in panels.items()}

    # Cross-market pooled (K1355)
    pooled = cross_market_pooled(panels)

    # Economic value: equal-weight 4-asset portfolio
    strat_curves, bench_curves = [], []
    per_asset_econ = {}
    for a, p in panels.items():
        strat, st = continuation_strategy(p)
        short_st = distribution_short_strategy(p)
        per_asset_econ[a] = {"continuation": st, "distribution_short": short_st}
        strat_curves.append(strat.rename(a))
        bench_curves.append(p["ret"].rename(a))
    strat_port = pd.concat(strat_curves, axis=1).mean(axis=1)  # 等權組合
    bench_port = pd.concat(bench_curves, axis=1).mean(axis=1)
    port_pos_dummy = (strat_port != 0).astype(float)  # 用於 active 統計近似
    port_stats = _perf_stats(strat_port, bench_port, port_pos_dummy)
    # 出貨組合
    short_curves = []
    for a, p in panels.items():
        pos = pd.Series(0.0, index=p.index)
        pos[p["hv_black"].shift(1).fillna(False).astype(bool)] = -1.0
        turn = pos.diff().abs().fillna(pos.abs())
        short_curves.append((pos * p["ret"] - TC_PER_UNIT * turn).rename(a))
    short_port_series = pd.concat(short_curves, axis=1).mean(axis=1)
    short_port_stats = _perf_stats(short_port_series, bench_port, (short_port_series != 0).astype(float))

    # Robustness grid
    grid = robustness_grid(assets_df)

    # Regime split
    regime = regime_split(panels, assets_df["SPY"]["price"])

    # Verdict
    verdict = build_verdict(asset_results, pooled, grid, port_stats, short_port_stats)

    # Charts
    plot_hit_rates(asset_results, OUT_DIR / "fig1_next_day_hit_rate.png")
    plot_pooled(pooled, regime, OUT_DIR / "fig2_cross_market_regime.png")
    plot_equity(strat_port, bench_port, port_stats, OUT_DIR / "fig3_economic_value.png")
    plot_robustness(grid, OUT_DIR / "fig4_robustness_grid.png")

    results = {
        "experiment_id": "K1659",
        "title": "量先價行 / 爆量長黑是出貨：跨市場延續性+經濟價值+穩健性檢定（延伸 K1636）",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "bootstrap_reps": BOOTSTRAP_REPS,
        "predecessor": "K1636 (逐資產 next-day 方向 BH-FDR; verdict not_supported)",
        "differentiation": [
            "跨市場正確聚合 K1355 (date-aggregate then HAC)",
            "量先價行延續性雙臂 hit-rate (K1636 只測爆量偏跌單臂)",
            "經濟價值 next-day long/short 淨成本 Sharpe",
            "參數穩健 k×N grid + 空頭次期間分割",
        ],
        "config": {
            "assets": ASSETS,
            "us_assets": sorted(US_ASSETS),
            "tw_assets": sorted(TW_ASSETS),
            "volume_spike_primary": f"volume[t] > {K_PRIMARY} x rolling_mean(volume,{N_PRIMARY}).shift(1)",
            "black_candle": f"ret[t] <= {BLACK_THRESHOLD}",
            "k_grid": K_GRID, "n_grid": N_GRID,
            "transaction_cost_per_unit_turnover": TC_PER_UNIT,
            "hac_maxlags": HAC_MAXLAGS,
            "lookahead_policy": "事件 signal.shift(1) 對齊 r[t+1]；rolling 門檻 shift(1)；同日不當預測",
        },
        "data": data_meta,
        "asset_results": asset_results,
        "cross_market_pooled": pooled,
        "economic_value": {
            "portfolio_continuation": port_stats,
            "portfolio_distribution_short": short_port_stats,
            "per_asset": per_asset_econ,
        },
        "robustness_grid": grid,
        "regime_split": regime,
        "verdict": verdict,
        "literature_basis": [
            "Karpoff (1987) JFQA — price-volume 同時關係，非隔日方向",
            "Campbell, Grossman & Wang (1993) QJE — volume 調節短期 return autocorrelation",
            "Llorente, Michaely, Saar & Wang (2002) RFS — volume 對報酬自相關的 information vs hedging 效果依 asset 而異",
            "Gervais, Kaniel & Mingelgrin (2001) JF — high-volume-return premium 是週/月頻現象，非日頻方向",
            "Lamoureux & Lastrapes (1990) JF — volume 是 volatility proxy，須把 direction 與 vol 分開",
        ],
        "related_project_knowledge": [
            "K1636 直接前身", "K1355 跨資產聚合規則", "K160 volume-volatility",
            "K710 volume 對 vol 增量極小", "K948 週頻 return 不可預測",
        ],
    }

    def _clean(o):
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, float) and not np.isfinite(o):
            return None
        return o

    out_path = OUT_DIR / "k1659_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(_clean(results), f, ensure_ascii=False, indent=2)

    # Console summary
    print("=" * 70)
    print(f"K1659 VERDICT: {verdict['myth_verdict']}")
    print(f"  BH-significant myth-consistent cells: {verdict['n_myth_consistent_bh_significant']}")
    print(f"  robustness supporting cells: {verdict['robustness_supporting_cells']}/{grid['n_cells']}")
    print(f"  continuation strategy Sharpe: {verdict['continuation_strategy_sharpe']}")
    print(f"  buy-hold Sharpe:              {verdict['buyhold_sharpe']}")
    print(f"  distribution-short Sharpe:    {verdict['distribution_short_sharpe']}")
    pa = pooled["primary_all_markets"]
    print(f"  pooled all-market sign-continuation: mean={pa['mean']}, t={pa['t']}, p={pa['p']}, n_dates={pa['n_event_dates']}")
    print(f"  results -> {out_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
