#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1669 — 動能因子崩盤：動態 vs 常數波動率縮放（MDD / 尾部聚焦）

動機
----
動能（momentum）因子有著名的「動能崩盤（momentum crash）」：在市場由熊轉牛的劇烈
反轉期（2009-03、2020-03 等），過去輸家暴漲、贏家暴跌，動能組合承受巨大回撤。文獻兩處方：
  - Barroso & Santa-Clara (2015, JFE)「Momentum has its moments」：常數目標波動率縮放
    （constant vol targeting，用過去已實現波動率把曝險 scale 到固定 vol 目標）。
  - Daniel & Moskowitz (2016, JFE)「Momentum crashes」：崩盤可預測（熊市 + 反彈），
    提出動態縮放（依波動率/熊市狀態動態調整曝險）。

本實驗差異化：在**同一組動能組合、同一 OOS 期間、同一縮放慣例**下公平比較
  (a) 無縮放 baseline
  (b) 常數波動率目標縮放（Barroso 式，inverse-vol，σ_ref = expanding median 使平均槓桿≈1）
  (c) 波動率狀態動態縮放（Daniel-Moskowitz 精神的簡化：高 vol 分位 regime 額外 haircut）
指標聚焦 MDD 與左尾（CVaR(5%) / 最差月）而非只看 Sharpe。

研究誠實原則落地
----------------
* Lookahead 最高優先：所有 scaling 因子用 **t-1 之前**已實現波動率預測 t 期曝險。
  日頻縮放槓桿一律 .shift(1)（見 build_leverage）。月頻橫截面動能訊號用 t-1 月底可得資訊、
  t 月報酬（見 build_sector_momentum，明確 shift）。baseline 與縮放策略同 lag 慣例。
* 槓桿 cap = 2.0（避免無限槓桿製造假 Sharpe）。
* expanding median / expanding quantile 皆只用歷史（lookahead-safe）。
* 固定 seed = 42（block bootstrap）。
* 公平比較：三策略同期間、同 universe、同 rebalance 慣例、同交易成本假設（同一 bps）。
* Panel A（primary）= 完全 ex-ante，無任何 ex-post 資訊。
  Panel B（robustness）= risk-matched（單一 ex-post scalar 均勻縮放到 baseline 全期 vol，
  僅做 level 對齊、不含 timing 資訊；文獻標準的等風險比較，用來隔離分佈「形狀」）。

輸出：experiments/k1669/{k1669_results.json, figs/*.png}
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 繁中字型（避免 CJK 缺字方框）；不可用時 fall back 不致命
for _f in ("Heiti TC", "Arial Unicode MS", "Hiragino Sans GB", "STHeiti"):
    try:
        import matplotlib.font_manager as _fm
        if any(_ff.name == _f for _ff in _fm.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [_f]
            break
    except Exception:
        pass
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
FIG_DIR = os.path.join(HERE, "figs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

SEED = 42
TRADING_DAYS = 252
LEV_CAP = 2.0            # 槓桿上限（避免假 Sharpe）
VOL_WINDOW = 126        # 主要已實現波動率窗（Barroso 6 個月 ≈ 126 交易日）
ROBUST_WINDOWS = [21, 63]  # robustness 波動率窗
DYN_Q_THRESH = 0.80     # 動態縮放：波動率 expanding 分位門檻（top-quintile 進 crash-defense）
DYN_HAIRCUT = 0.50      # 高 vol regime 額外曝險 haircut（腰斬）
COST_BPS = 10.0         # robustness 交易成本（bps of turnover），三策略同一 bps

SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE"]
ALL_TICKERS = ["MTUM"] + SECTORS

CRASH_WINDOWS = {
    # name: (start, end)  — 明確崩盤 / 熊市窗口，用於 crash-window 報酬對比
    "gfc_rebound_2009": ("2009-03-01", "2009-06-30"),   # 動能經典崩盤（僅自建組合可及）
    "covid_2020_03": ("2020-02-20", "2020-04-30"),      # COVID 崩盤 + 反彈
    "bear_2022": ("2022-01-01", "2022-12-31"),          # 2022 升息熊市
}


# ---------------------------------------------------------------------------
# 資料
# ---------------------------------------------------------------------------
def load_prices() -> pd.DataFrame:
    """抓取（或讀快取）調整後收盤價。快取於 experiments/k1669/data/ 供復現。"""
    cache = os.path.join(DATA_DIR, "prices.csv")
    if os.path.exists(cache):
        px = pd.read_csv(cache, index_col=0, parse_dates=True)
        # 只在快取涵蓋足夠近期才用；否則重抓
        if px.index.max() >= pd.Timestamp("2026-06-01"):
            print(f"[data] 使用快取 {cache}  shape={px.shape}")
            return px
    import yfinance as yf

    print("[data] 從 yfinance 下載 ...")
    raw = yf.download(
        ALL_TICKERS, start="2004-01-01", end="2026-07-10",
        auto_adjust=True, progress=False,
    )
    px = raw["Close"][ALL_TICKERS].copy()
    px.index = pd.to_datetime(px.index)
    px.to_csv(cache)
    print(f"[data] 已下載並快取  shape={px.shape}  {px.index.min().date()}->{px.index.max().date()}")
    return px


# ---------------------------------------------------------------------------
# 動能組合建構
# ---------------------------------------------------------------------------
def build_sector_momentum(px: pd.DataFrame):
    """自建橫截面類股動能（月頻，12-1 月訊號，long-short 前後 tertile + long-only top tertile）。

    Lag 慣例（明確）：
      - 訊號用「t-1 月底」可得的 12-1 月報酬（過去 12 個月報酬、跳過最近 1 個月）。
      - 權重 .shift(1) 後套到「t 月」的日報酬 —— 即 t 月只用 t-1 月底資訊。
      - long-short：做多 top tertile、做空 bottom tertile；long-only：只做多 top tertile。
      - universe 每月動態：只納入當月有效（非 NaN 且已上市）的 ETF；XLRE 2015 後才進。
    回傳 (ls_daily_ret, longonly_daily_ret, monthly_turnover_ls, monthly_turnover_lo)
    """
    sec_px = px[SECTORS].copy()
    daily_ret = sec_px.pct_change()

    # 月末價格（用於算月報酬與 12-1 訊號）
    m_px = sec_px.resample("ME").last()
    m_ret = m_px.pct_change()

    # 12-1 動能訊號：過去 12 個月累積報酬、跳過最近 1 個月 = prod(1+r) over months [t-12, t-2]
    log_m = np.log1p(m_ret)
    mom_12_1 = log_m.rolling(12).sum() - log_m  # sum 過去12月 log ret 減掉當月 => 過去12月跳最近1月
    # 注意：mom_12_1.loc[m] 用到 m 當月報酬（減掉了），成分是 [m-11 .. m-1] 的 log ret，
    # 全部在「m 月底」已實現 => 用來決定「m+1 月」持倉。

    ls_w = pd.DataFrame(0.0, index=m_px.index, columns=SECTORS)
    lo_w = pd.DataFrame(0.0, index=m_px.index, columns=SECTORS)

    for m in mom_12_1.index:
        row = mom_12_1.loc[m].dropna()
        # 需至少 6 檔有效才做橫截面排序（早期 XLRE 缺，其餘 9 檔 2004 起）
        if row.shape[0] < 6:
            continue
        ranked = row.sort_values()
        n = row.shape[0]
        k = max(1, n // 3)  # tertile 大小
        losers = ranked.index[:k]
        winners = ranked.index[-k:]
        # long-short：等權多空、各腿權重和 = 1（多 +1 / 空 -1）
        ls_w.loc[m, winners] = 1.0 / k
        ls_w.loc[m, losers] = -1.0 / k
        # long-only top tertile：等權
        lo_w.loc[m, winners] = 1.0 / k

    # 關鍵 lag：t 月持倉 = t-1 月底訊號 => 權重 shift(1)（月頻）
    ls_w_lag = ls_w.shift(1)
    lo_w_lag = lo_w.shift(1)

    # 把月權重 forward-fill 到日頻（當月每一交易日持有相同權重），再乘當日 ETF 報酬
    daily_idx = daily_ret.index
    # 對每個交易日找出其所屬月份的（已 lag 的）權重
    ls_w_daily = ls_w_lag.reindex(daily_idx, method="ffill")
    lo_w_daily = lo_w_lag.reindex(daily_idx, method="ffill")

    ls_daily = (ls_w_daily * daily_ret).sum(axis=1, min_count=1)
    lo_daily = (lo_w_daily * daily_ret).sum(axis=1, min_count=1)

    # 月頻換手率（turnover）：|w_t - w_{t-1}| 在每個 rebalance 月的 L1 變動之半（買賣）
    ls_turn = ls_w_lag.diff().abs().sum(axis=1) / 2.0
    lo_turn = lo_w_lag.diff().abs().sum(axis=1) / 2.0

    # 只保留 momentum 訊號有效後的期間
    ls_daily = ls_daily.dropna()
    lo_daily = lo_daily.dropna()
    return ls_daily, lo_daily, ls_turn, lo_turn


def mtum_returns(px: pd.DataFrame) -> pd.Series:
    r = px["MTUM"].pct_change().dropna()
    return r


# ---------------------------------------------------------------------------
# 波動率縮放引擎（lookahead-safe）
# ---------------------------------------------------------------------------
def realized_vol(daily_ret: pd.Series, window: int) -> pd.Series:
    """滾動已實現年化波動率（用過去 window 日日報酬標準差 * sqrt(252)）。"""
    return daily_ret.rolling(window).std() * np.sqrt(TRADING_DAYS)


def build_leverage(daily_ret: pd.Series, window: int):
    """建三種槓桿序列（全部 lookahead-safe，t 期槓桿只用 <= t-1 資訊）。

    baseline: 常數 1.0
    const   : inverse-vol，σ_ref = expanding median(σ̂) 使平均槓桿≈1，cap 2x
    dynamic : const × haircut，高 vol expanding 分位(>0.80) 時曝險腰斬（DM 精神）

    回傳 (lev_base, lev_const, lev_dyn, sigma_hat, active_start)
    """
    sigma = realized_vol(daily_ret, window)     # σ̂_t 用「到 t 為止」window 日
    sigma_lag = sigma.shift(1)                    # ← 關鍵：t 期槓桿用 σ̂_{t-1}（不含當日）

    # σ_ref = expanding median of σ̂（只用歷史；同樣用 lag 版避免看到當日）
    sigma_ref = sigma_lag.expanding(min_periods=window).median()

    # expanding 分位排名 q_{t-1}：σ̂_{t-1} 在 {σ̂_s: s<=t-1} 的分位（lookahead-safe）
    q = sigma_lag.expanding(min_periods=window).apply(
        lambda a: (a[-1] >= a).mean(), raw=True
    )

    lev_const_raw = (sigma_ref / sigma_lag).clip(upper=LEV_CAP, lower=0.0)
    haircut = pd.Series(np.where(q >= DYN_Q_THRESH, DYN_HAIRCUT, 1.0), index=q.index)
    lev_dyn_raw = (sigma_ref / sigma_lag * haircut).clip(upper=LEV_CAP, lower=0.0)

    # burn-in：σ̂/σ_ref/q 尚未有效前，三策略槓桿皆 = 1（期間完全一致，公平）
    active = sigma_ref.notna() & sigma_lag.notna() & q.notna()
    active_start = active.idxmax() if active.any() else daily_ret.index[-1]

    lev_base = pd.Series(1.0, index=daily_ret.index)
    lev_const = lev_base.copy()
    lev_dyn = lev_base.copy()
    lev_const[active] = lev_const_raw[active]
    lev_dyn[active] = lev_dyn_raw[active]
    return lev_base, lev_const, lev_dyn, sigma_lag, active_start


# ---------------------------------------------------------------------------
# 績效指標
# ---------------------------------------------------------------------------
def equity_curve(ret: pd.Series) -> pd.Series:
    return (1.0 + ret).cumprod()


def max_drawdown(ret: pd.Series) -> float:
    eq = equity_curve(ret)
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min())


def drawdown_series(ret: pd.Series) -> pd.Series:
    eq = equity_curve(ret)
    return eq / eq.cummax() - 1.0


def cvar(ret: pd.Series, alpha: float = 0.05) -> float:
    """左尾 CVaR：最差 alpha 分位日報酬的平均（負值）。"""
    q = ret.quantile(alpha)
    tail = ret[ret <= q]
    return float(tail.mean()) if len(tail) else float("nan")


def worst_month(ret: pd.Series) -> float:
    m = (1.0 + ret).resample("ME").prod() - 1.0
    return float(m.min())


def perf_metrics(ret: pd.Series) -> dict:
    ret = ret.dropna()
    n = len(ret)
    mu_d = ret.mean()
    sd_d = ret.std(ddof=1)
    ann_ret_arith = float(mu_d * TRADING_DAYS)
    cagr = float((1.0 + ret).prod() ** (TRADING_DAYS / n) - 1.0) if n > 0 else float("nan")
    ann_vol = float(sd_d * np.sqrt(TRADING_DAYS))
    sharpe = float(mu_d / sd_d * np.sqrt(TRADING_DAYS)) if sd_d > 0 else float("nan")
    return {
        "n_days": int(n),
        "ann_return_arith": ann_ret_arith,
        "cagr": cagr,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(ret),
        "worst_month": worst_month(ret),
        "cvar_5pct_daily": cvar(ret, 0.05),
        "cvar_1pct_daily": cvar(ret, 0.01),
        "skew": float(ret.skew()),
        "kurtosis_excess": float(ret.kurtosis()),
    }


def crash_window_returns(ret: pd.Series) -> dict:
    out = {}
    for name, (s, e) in CRASH_WINDOWS.items():
        seg = ret.loc[(ret.index >= s) & (ret.index <= e)]
        if len(seg) == 0:
            out[name] = None
            continue
        cum = float((1.0 + seg).prod() - 1.0)
        out[name] = {
            "cum_return": cum,
            "max_drawdown": max_drawdown(seg),
            "worst_day": float(seg.min()),
            "n_days": int(len(seg)),
            "start": str(seg.index.min().date()),
            "end": str(seg.index.max().date()),
        }
    return out


# ---------------------------------------------------------------------------
# Block bootstrap Sharpe 差異檢定（circular block bootstrap，seed 固定）
# ---------------------------------------------------------------------------
def block_bootstrap_sharpe_diff(ret_a: pd.Series, ret_b: pd.Series,
                                block: int = 21, reps: int = 5000, seed: int = SEED):
    """檢定 Sharpe(a) - Sharpe(b) 是否顯著 != 0（paired，circular block bootstrap）。
    a = 縮放策略、b = baseline。回傳 point diff / 95% CI / 雙尾 p。"""
    df = pd.concat([ret_a, ret_b], axis=1, join="inner").dropna()
    x = df.iloc[:, 0].values
    y = df.iloc[:, 1].values
    n = len(x)

    def sharpe(v):
        sd = v.std(ddof=1)
        return v.mean() / sd * np.sqrt(TRADING_DAYS) if sd > 0 else 0.0

    point = sharpe(x) - sharpe(y)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    diffs = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % n
        idx = idx[:n]
        diffs[r] = sharpe(x[idx]) - sharpe(y[idx])
    ci = np.percentile(diffs, [2.5, 97.5])
    # 雙尾 p：以 bootstrap 分佈相對 0 的位置（居中於 point 的 null 版本）
    centered = diffs - point
    p_two = float(2.0 * min((centered >= point).mean(), (centered <= point).mean()))
    p_two = min(p_two, 1.0)
    return {
        "sharpe_diff_point": float(point),
        "ci95_low": float(ci[0]),
        "ci95_high": float(ci[1]),
        "p_value_two_sided": p_two,
        "block": block,
        "reps": reps,
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# 交易成本（同一 bps 套三策略）
# ---------------------------------------------------------------------------
def apply_costs(daily_ret: pd.Series, lev: pd.Series, base_turnover_daily: pd.Series,
                bps: float) -> pd.Series:
    """成本 = bps × turnover。turnover = |Δ(曝險)|（縮放槓桿變動）+ 底層組合 rebalance 換手。
    曝險 = lev（對 baseline lev≡1 → Δ=0）；底層換手（自建組合月頻 rebalance）以 lev 加權。"""
    d_lev = lev.diff().abs().fillna(0.0)
    base_turn = base_turnover_daily.reindex(daily_ret.index).fillna(0.0) * lev.abs()
    turnover = d_lev + base_turn
    cost = turnover * (bps / 1e4)
    return daily_ret * lev - cost


# ---------------------------------------------------------------------------
# 單一動能組合的完整分析
# ---------------------------------------------------------------------------
def analyze_portfolio(name: str, daily_ret: pd.Series, base_turnover: pd.Series | None,
                      window: int = VOL_WINDOW) -> dict:
    daily_ret = daily_ret.dropna()
    lev_base, lev_const, lev_dyn, sigma_lag, active_start = build_leverage(daily_ret, window)

    if base_turnover is None:
        base_turnover = pd.Series(0.0, index=daily_ret.index)

    # 三策略「無成本」報酬（Panel A：完全 ex-ante）
    r_base = daily_ret * lev_base
    r_const = daily_ret * lev_const
    r_dyn = daily_ret * lev_dyn

    strategies = {"baseline": r_base, "const_vol": r_const, "dynamic_vol": r_dyn}
    levs = {"baseline": lev_base, "const_vol": lev_const, "dynamic_vol": lev_dyn}

    panelA = {k: perf_metrics(v) for k, v in strategies.items()}
    crash = {k: crash_window_returns(v) for k, v in strategies.items()}

    # Panel B：risk-matched（單一 ex-post scalar 均勻縮放到 baseline 全期 vol）
    vol_base = r_base.std(ddof=1)
    panelB = {}
    strategies_rm = {}
    for k, v in strategies.items():
        vk = v.std(ddof=1)
        scalar = float(vol_base / vk) if vk > 0 else 1.0
        v_rm = v * scalar
        strategies_rm[k] = v_rm
        m = perf_metrics(v_rm)
        m["level_match_scalar"] = scalar
        panelB[k] = m

    # 槓桿統計（診斷是否合理、cap 是否常 binding）
    lev_stats = {}
    for k, lv in levs.items():
        lv_active = lv.loc[daily_ret.index >= active_start]
        lev_stats[k] = {
            "mean": float(lv_active.mean()),
            "median": float(lv_active.median()),
            "max": float(lv_active.max()),
            "p95": float(lv_active.quantile(0.95)),
            "frac_at_cap": float((lv_active >= LEV_CAP - 1e-9).mean()),
            "frac_below_0p5": float((lv_active < 0.5).mean()),
        }

    # 交易成本 robustness（10 bps，同套三策略）
    panel_cost = {}
    for k in strategies:
        r_c = apply_costs(daily_ret, levs[k], base_turnover, COST_BPS)
        panel_cost[k] = perf_metrics(r_c)

    # bootstrap Sharpe 差異：const vs baseline、dynamic vs baseline、dynamic vs const（Panel A）
    boot = {
        "const_vs_baseline": block_bootstrap_sharpe_diff(r_const, r_base),
        "dynamic_vs_baseline": block_bootstrap_sharpe_diff(r_dyn, r_base),
        "dynamic_vs_const": block_bootstrap_sharpe_diff(r_dyn, r_const),
    }

    # robustness：其他 vol 窗（只報 Panel A MDD/CVaR/Sharpe 精簡）
    robust_windows = {}
    for w in ROBUST_WINDOWS:
        lb, lc, ld, _, _ = build_leverage(daily_ret, w)
        rw = {
            "baseline": perf_metrics(daily_ret * lb),
            "const_vol": perf_metrics(daily_ret * lc),
            "dynamic_vol": perf_metrics(daily_ret * ld),
        }
        robust_windows[f"vol_window_{w}"] = {
            kk: {"sharpe": vv["sharpe"], "max_drawdown": vv["max_drawdown"],
                 "cvar_5pct_daily": vv["cvar_5pct_daily"], "worst_month": vv["worst_month"]}
            for kk, vv in rw.items()
        }

    return {
        "name": name,
        "period": {"start": str(daily_ret.index.min().date()),
                   "end": str(daily_ret.index.max().date()),
                   "n_days": int(len(daily_ret)),
                   "scaling_active_from": str(pd.Timestamp(active_start).date())},
        "vol_window_primary": window,
        "panelA_ex_ante": panelA,
        "panelB_risk_matched": panelB,
        "panel_cost_10bps": panel_cost,
        "crash_windows": crash,
        "leverage_stats": lev_stats,
        "bootstrap_sharpe_diff": boot,
        "robustness_vol_windows": robust_windows,
        "_series_for_plot": {  # 內部用，不寫入 JSON
            "strategies": strategies,
            "strategies_rm": strategies_rm,
        },
    }


# ---------------------------------------------------------------------------
# 繪圖
# ---------------------------------------------------------------------------
def shade_crashes(ax):
    for name, (s, e) in CRASH_WINDOWS.items():
        ax.axvspan(pd.Timestamp(s), pd.Timestamp(e), color="red", alpha=0.08)


COLORS = {"baseline": "#444444", "const_vol": "#1f77b4", "dynamic_vol": "#d62728"}
LABELS = {"baseline": "無縮放 baseline", "const_vol": "常數 vol 目標",
          "dynamic_vol": "動態 vol 縮放"}


def plot_cum_and_dd(res: dict, tag: str, use_rm: bool = True):
    key = "strategies_rm" if use_rm else "strategies"
    strats = res["_series_for_plot"][key]
    fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1]})
    ax0, ax1 = axes
    for k, r in strats.items():
        eq = equity_curve(r)
        ax0.plot(eq.index, eq.values, label=LABELS[k], color=COLORS[k], lw=1.4)
        dd = drawdown_series(r)
        ax1.plot(dd.index, dd.values, color=COLORS[k], lw=1.1)
    ax0.set_yscale("log")
    ax0.set_ylabel("累積淨值（log，起始=1）")
    matched = "risk-matched（等全期 vol）" if use_rm else "ex-ante"
    ax0.set_title(f"K1669 {res['name']} — 三策略累積淨值（{matched}），紅區=崩盤窗口")
    ax0.legend(loc="upper left", fontsize=9)
    shade_crashes(ax0)
    ax1.set_ylabel("回撤")
    ax1.set_xlabel("日期")
    shade_crashes(ax1)
    ax1.axhline(0, color="k", lw=0.5)
    for ax in axes:
        ax.grid(True, alpha=0.25)
    ax1.xaxis.set_major_locator(mdates.YearLocator(2))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    path = os.path.join(FIG_DIR, f"k1669_{tag}_cum_dd.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"[fig] {path}")
    return path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def strip_plot_series(res: dict) -> dict:
    r = {k: v for k, v in res.items() if k != "_series_for_plot"}
    return r


def atomic_write_json(obj: dict, path: str):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    # 驗證可解析
    with open(tmp, "r", encoding="utf-8") as f:
        json.load(f)
    os.replace(tmp, path)


def main():
    np.random.seed(SEED)
    px = load_prices()

    r_mtum = mtum_returns(px)
    ls_daily, lo_daily, ls_turn, lo_turn = build_sector_momentum(px)

    print(f"[info] MTUM {r_mtum.index.min().date()}->{r_mtum.index.max().date()} n={len(r_mtum)}")
    print(f"[info] Sector L-S {ls_daily.index.min().date()}->{ls_daily.index.max().date()} n={len(ls_daily)}")
    print(f"[info] Sector L-only {lo_daily.index.min().date()}->{lo_daily.index.max().date()} n={len(lo_daily)}")

    # 月頻換手率轉成「每個交易日對應其 rebalance 當日」的 series（月初第一個交易日承擔換手成本）
    def month_turn_to_daily(turn_m: pd.Series, daily_idx: pd.DatetimeIndex) -> pd.Series:
        # 將月末換手歸到「下個月第一個交易日」（rebalance 執行日）
        s = pd.Series(0.0, index=daily_idx)
        for m, t in turn_m.dropna().items():
            future = daily_idx[daily_idx > m]
            if len(future):
                s.loc[future[0]] += float(t)
        return s

    ls_turn_daily = month_turn_to_daily(ls_turn, ls_daily.index)
    lo_turn_daily = month_turn_to_daily(lo_turn, lo_daily.index)

    portfolios = {
        "MTUM_etf": analyze_portfolio("MTUM ETF", r_mtum, None),
        "sector_long_short": analyze_portfolio("自建類股動能 L-S", ls_daily, ls_turn_daily),
        "sector_long_only": analyze_portfolio("自建類股動能 long-only top-tertile", lo_daily, lo_turn_daily),
    }

    # 繪圖：MTUM + 自建 L-S（涵蓋 2008-09）
    figs = []
    figs.append(plot_cum_and_dd(portfolios["MTUM_etf"], "mtum", use_rm=True))
    figs.append(plot_cum_and_dd(portfolios["sector_long_short"], "sector_ls", use_rm=True))

    results = {
        "experiment_id": "k1669",
        "title": "動能因子崩盤：動態 vs 常數波動率縮放（MDD/尾部聚焦）",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "config": {
            "leverage_cap": LEV_CAP,
            "vol_window_primary": VOL_WINDOW,
            "robust_vol_windows": ROBUST_WINDOWS,
            "dyn_quantile_threshold": DYN_Q_THRESH,
            "dyn_haircut": DYN_HAIRCUT,
            "cost_bps_robustness": COST_BPS,
            "trading_days": TRADING_DAYS,
            "rf_rate": 0.0,
            "sector_universe": SECTORS,
            "crash_windows": CRASH_WINDOWS,
        },
        "lag_conventions": {
            "daily_scaling": "t 期槓桿 = f(σ̂_{t-1})，realized_vol().shift(1)；三策略同 lag",
            "monthly_momentum": "t 月持倉權重 = t-1 月底 12-1 動能訊號（權重 .shift(1)）",
            "expanding_stats": "σ_ref=expanding median、q=expanding quantile 皆只用歷史",
            "level_match_note": "Panel B 的 risk-match scalar 為單一 ex-post 常數（均勻縮放，"
                                "無 timing 資訊），僅用於等風險比較 MDD/尾部；Panel A 完全 ex-ante",
        },
        "data_source": "yfinance auto_adjust Close；快取 experiments/k1669/data/prices.csv",
        "portfolios": {k: strip_plot_series(v) for k, v in portfolios.items()},
        "figures": [os.path.relpath(f, HERE) for f in figs],
    }

    out = os.path.join(HERE, "k1669_results.json")
    atomic_write_json(results, out)
    print(f"[done] 寫入 {out}")

    # 簡要 stdout 摘要（給主線程 review）
    print("\n===== 摘要（Panel A ex-ante / Panel B risk-matched）=====")
    for pk, pv in portfolios.items():
        print(f"\n--- {pv['name']} ({pv['period']['start']}~{pv['period']['end']}, "
              f"n={pv['period']['n_days']}) ---")
        A = pv["panelA_ex_ante"]; B = pv["panelB_risk_matched"]
        hdr = f"{'strategy':<14}{'Sharpe':>8}{'MDD':>9}{'CVaR5%':>9}{'worstM':>9}{'annVol':>8}"
        print("[Panel A ex-ante] " + hdr)
        for s in ["baseline", "const_vol", "dynamic_vol"]:
            a = A[s]
            print(f"  {s:<14}{a['sharpe']:>8.3f}{a['max_drawdown']:>9.3f}"
                  f"{a['cvar_5pct_daily']:>9.4f}{a['worst_month']:>9.3f}{a['ann_vol']:>8.3f}")
        print("[Panel B risk-matched] " + hdr)
        for s in ["baseline", "const_vol", "dynamic_vol"]:
            b = B[s]
            print(f"  {s:<14}{b['sharpe']:>8.3f}{b['max_drawdown']:>9.3f}"
                  f"{b['cvar_5pct_daily']:>9.4f}{b['worst_month']:>9.3f}{b['ann_vol']:>8.3f}")
        boot = pv["bootstrap_sharpe_diff"]
        print(f"  bootstrap ΔSharpe const-base={boot['const_vs_baseline']['sharpe_diff_point']:.3f} "
              f"(p={boot['const_vs_baseline']['p_value_two_sided']:.3f}), "
              f"dyn-base={boot['dynamic_vs_baseline']['sharpe_diff_point']:.3f} "
              f"(p={boot['dynamic_vs_baseline']['p_value_two_sided']:.3f})")


if __name__ == "__main__":
    main()
