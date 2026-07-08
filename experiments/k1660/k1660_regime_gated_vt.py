"""
K1660 — Conditional (regime-gated) Volatility Targeting vs Always-VT: net-of-cost performance.

研究問題
--------
Volatility Targeting (VT) 永遠按預測波動率縮放曝險，即使在平靜期 (低波動 regime)
仍持續小幅換手 → 累積交易成本卻沒實質風險改善。本題檢定：**只在偵測到高波動
regime 時才啟動 VT (regime-gated)，平靜期維持 buy-and-hold (曝險=1，不換手)**，
能否透過省下平靜期無謂換手，改善淨成本後的 Sharpe / Calmar。

與庫內既有 K 的差異化
--------------------
- regime_adaptive_overlay (K, Sharpe 0.61→0.53 harmful): 連續 cap 60%/floor 120%
  overlay，**且不計交易成本**。本題是二元 on/off gate，成本為核心。
- adaptive_vt_regime_target (Sharpe 0.697→0.705): 調 target vol (10%/12%)，非 on/off。
- CED (research_program.md line 623, NULL): backward-looking 連續 tail scaler。
本題新機制 = **二元 regime 開關 + per-turnover 淨成本比較**。

方法論 / 防錯 (研究誠實原則)
--------------------------
- Lag 慣例: 所有 signal (vol forecast + regime label) 在日 t 收盤用 up-to-t 資訊算，
  以 `exposure.shift(1)` 進入 t+1 的持倉 (賺 ret_{t+1})。turnover 同步對齊。
  → 無 lookahead: pos_t = exposure_{t-1}, gross_ret_t = pos_t * ret_t。
- Baseline 與 gated 用**同一** vol forecast、同一 cap/floor、同一成本模型、同一 lag。
  gated 唯一差別 = 低波動 regime 時 exposure 強制設為 1.0。
- 淨報酬 = pos * ret - cost_rate * |pos.diff()|  (per-turnover 單邊成本)。
- 隨機程序 (block bootstrap) 固定 seed=42。
- Sharpe 異常高先疑 bug (參 K562 lookahead 教訓)。

資料來源: yfinance (SPY 主, 0050.TW robustness)，日收盤 adjusted close。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SEED = 42
TRADING_DAYS = 252
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FIG_DIR = os.path.join(os.path.dirname(__file__), "figures")
RESULTS_PATH = os.path.join(os.path.dirname(__file__), "k1660_results.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_prices(ticker: str, start: str, end: str) -> pd.Series:
    """下載或讀快取的 adjusted close。快取到 data/ 供復現。"""
    safe = ticker.replace(".", "_").replace("^", "")
    cache = os.path.join(DATA_DIR, f"{safe}_{start}_{end}.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        return df["close"].dropna()
    import yfinance as yf

    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        raise RuntimeError(f"no data for {ticker}")
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close.name = "close"
    close.to_frame().to_csv(cache)
    return close.dropna()


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #
def clean_returns(ret: pd.Series, daily_limit: float | None) -> tuple[pd.Series, list]:
    """
    移除明顯的資料錯誤 (yfinance adjustment glitch)。
    daily_limit 有經濟依據時 (台股 ±7%/±10% 漲跌幅限制 → 用 0.11 buffer) 才啟用；
    SPY 等無漲跌幅限制市場傳 None (不清洗)。回傳 (cleaned_ret, removed_records)。
    """
    if daily_limit is None:
        return ret, []
    bad = ret.abs() > daily_limit
    removed = [{"date": str(d.date()), "ret": float(ret[d])} for d in ret.index[bad]]
    return ret[~bad], removed


def realized_vol(ret: pd.Series, window: int = 20) -> pd.Series:
    """rolling realized vol (annualized). 用 up-to-t 報酬，非 lookahead。"""
    return ret.rolling(window).std() * np.sqrt(TRADING_DAYS)


def ewma_vol(ret: pd.Series, lam: float = 0.94) -> pd.Series:
    """EWMA (RiskMetrics) annualized vol，僅用 up-to-t 報酬。"""
    var = ret.pow(2).ewm(alpha=1 - lam, adjust=False).mean()
    return np.sqrt(var) * np.sqrt(TRADING_DAYS)


def vt_exposure(vol_fc: pd.Series, target_vol: float, cap: float) -> pd.Series:
    """Always-VT 曝險 = target / forecast_vol，clip 到 [0, cap]。"""
    exp = target_vol / vol_fc
    return exp.clip(lower=0.0, upper=cap)


def high_regime(vol_signal: pd.Series, q: float, window: int) -> pd.Series:
    """
    高波動 regime 偵測: rolling window 內 vol_signal 是否 > 其 q 分位數。
    threshold 用 up-to-t 的 rolling quantile，然後與 t 當日 vol_signal 比。
    整條 signal 稍後 shift(1) 進持倉，故無 lookahead。
    """
    thr = vol_signal.rolling(window, min_periods=window).quantile(q)
    return (vol_signal > thr).astype(float)


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #
@dataclass
class Perf:
    ann_return: float
    ann_vol: float
    sharpe: float
    mdd: float
    calmar: float
    ann_turnover: float
    n_days: int


def _max_drawdown(cum: pd.Series) -> float:
    peak = cum.cummax()
    dd = cum / peak - 1.0
    return float(dd.min())


def backtest(ret: pd.Series, exposure: pd.Series, cost_bps: float) -> tuple[Perf, pd.Series, pd.Series]:
    """
    exposure_t 在 t 收盤算 (up-to-t 資訊)。
    pos_t = exposure_{t-1} (shift 1) → 賺 ret_t，turnover 用 pos 的 diff 對齊。
    net_ret_t = pos_t * ret_t - cost_rate * |pos_t - pos_{t-1}|
    """
    cost_rate = cost_bps / 1e4
    pos = exposure.shift(1)
    turnover = pos.diff().abs()
    gross = pos * ret
    net = gross - cost_rate * turnover
    net = net.dropna()
    turnover = turnover.reindex(net.index).fillna(0.0)

    cum = (1.0 + net).cumprod()
    n = len(net)
    years = n / TRADING_DAYS
    final_wealth = float(cum.iloc[-1]) if n > 0 else float("nan")
    # 保護: 若策略爆倉 (cumulative wealth ≤ 0) 則 CAGR 無定義，標 -100% 而非 nan-power
    if not (final_wealth > 0):
        ann_ret = -1.0
    else:
        ann_ret = float(final_wealth ** (1.0 / years) - 1.0)
    ann_vol = float(net.std() * np.sqrt(TRADING_DAYS))
    sharpe = float(net.mean() / net.std() * np.sqrt(TRADING_DAYS)) if net.std() > 0 else float("nan")
    mdd = _max_drawdown(cum)
    calmar = float(ann_ret / abs(mdd)) if mdd != 0 else float("nan")
    ann_turn = float(turnover.sum() / years)
    return Perf(ann_ret, ann_vol, sharpe, mdd, calmar, ann_turn, n), net, pos


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def newey_west_ttest(diff: pd.Series, lag: int) -> tuple[float, float]:
    """HAC (Newey-West) t-test for mean(diff)=0，處理日報酬差自相關。"""
    x = diff.dropna().values
    n = len(x)
    mu = x.mean()
    e = x - mu
    gamma0 = np.dot(e, e) / n
    var = gamma0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1.0)
        cov = np.dot(e[k:], e[:-k]) / n
        var += 2.0 * w * cov
    se = np.sqrt(var / n)
    t = mu / se if se > 0 else float("nan")
    # two-sided p via normal approx
    from scipy import stats

    p = 2.0 * (1.0 - stats.norm.cdf(abs(t)))
    return float(t), float(p)


def _sharpe(x: np.ndarray) -> float:
    s = x.std(ddof=1)  # sample std, 與 Perf.sharpe (pandas ddof=1) 一致
    return x.mean() / s * np.sqrt(TRADING_DAYS) if s > 0 else np.nan


def circular_block_bootstrap_sharpe_diff(
    net_a: pd.Series, net_b: pd.Series, block: int = 20, B: int = 10000, seed: int = SEED
) -> dict:
    """
    Circular block bootstrap on jointly-resampled (net_a, net_b) daily pairs.
    保留兩策略同日 net return 的 cross-correlation。回傳 Sharpe(b)-Sharpe(a) 的 CI。
    net_a = baseline (always-VT), net_b = gated。
    """
    idx = net_a.index.intersection(net_b.index)
    a = net_a.reindex(idx).values
    b = net_b.reindex(idx).values
    n = len(a)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    diffs = np.empty(B)
    point = _sharpe(b) - _sharpe(a)
    for i in range(B):
        starts = rng.integers(0, n, size=n_blocks)
        rows = (starts[:, None] + np.arange(block)[None, :]).ravel() % n
        rows = rows[:n]
        diffs[i] = _sharpe(b[rows]) - _sharpe(a[rows])
    ci_lo, ci_hi = np.percentile(diffs, [2.5, 97.5])
    # bootstrap p-value: fraction crossing zero on the opposite side of point est
    p_two = 2.0 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return {
        "sharpe_diff_point": float(point),
        "ci95_lo": float(ci_lo),
        "ci95_hi": float(ci_hi),
        "boot_p_two_sided": float(min(p_two, 1.0)),
        "B": B,
        "block": block,
        "seed": seed,
    }


# --------------------------------------------------------------------------- #
# Strategy builders
# --------------------------------------------------------------------------- #
def build_exposures(
    ret: pd.Series,
    target_vol: float,
    cap: float,
    regime_q: float,
    regime_window: int,
    vol_method: str,
    rv_window: int = 20,
) -> dict[str, pd.Series]:
    if vol_method == "rolling20":
        vol_fc = realized_vol(ret, rv_window)
    elif vol_method == "ewma94":
        vol_fc = ewma_vol(ret, 0.94)
    else:
        raise ValueError(vol_method)

    # regime 用 20d realized vol 作 signal (穩定、可解讀)
    regime_signal = realized_vol(ret, rv_window)
    regime = high_regime(regime_signal, regime_q, regime_window)

    exp_vt = vt_exposure(vol_fc, target_vol, cap)              # Always-VT baseline
    exp_gated = exp_vt.where(regime > 0.5, 1.0)                 # high→VT, low→BH(=1)

    # 對齊起點: 三策略共用同一 valid mask (regime warm-up 後才交易) → 完全同期比較
    valid = exp_vt.notna() & regime.notna()
    exp_vt = exp_vt.where(valid)
    exp_gated = exp_gated.where(valid)
    exp_bh = pd.Series(1.0, index=ret.index).where(valid)      # Buy & Hold 同期
    return {"always_vt": exp_vt, "buy_hold": exp_bh, "gated_vt": exp_gated, "_regime": regime}


def run_config(
    ret: pd.Series,
    target_vol: float,
    cap: float,
    regime_q: float,
    regime_window: int,
    vol_method: str,
    cost_bps: float,
) -> dict:
    exps = build_exposures(ret, target_vol, cap, regime_q, regime_window, vol_method)
    out = {}
    nets = {}
    for name in ("always_vt", "buy_hold", "gated_vt"):
        perf, net, _ = backtest(ret, exps[name], cost_bps)
        out[name] = asdict(perf)
        nets[name] = net
    # gated vs always-VT tests
    idx = nets["always_vt"].index.intersection(nets["gated_vt"].index)
    diff = (nets["gated_vt"].reindex(idx) - nets["always_vt"].reindex(idx))
    t, p = newey_west_ttest(diff, lag=regime_window if regime_window < 40 else 30)
    boot = circular_block_bootstrap_sharpe_diff(
        nets["always_vt"].reindex(idx), nets["gated_vt"].reindex(idx), block=20, B=10000
    )
    # regime label 對齊實際驅動 pos_t 的 regime_{t-1} (與 exposure 一同 shift)
    regime_frac_high = float(exps["_regime"].shift(1).reindex(idx).mean())
    out["tests_gated_vs_alwaysvt"] = {
        "mean_daily_net_return_diff": float(diff.mean()),
        "nw_hac_tstat": t,
        "nw_hac_pvalue": p,
        "bootstrap_sharpe_diff": boot,
        "regime_frac_high": regime_frac_high,
    }
    return out, nets, exps


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def analyze_asset(ticker: str, start: str, end: str, primary: bool, daily_limit: float | None = None) -> dict:
    price = load_prices(ticker, start, end)
    ret = price.pct_change().dropna()
    ret = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    ret, removed = clean_returns(ret, daily_limit)

    asset = {
        "ticker": ticker,
        "period": f"{ret.index[0].date()} .. {ret.index[-1].date()}",
        "n_return_days": int(len(ret)),
        "data_source": "yfinance auto_adjust close",
        "data_cleaning": {
            "daily_return_limit": daily_limit,
            "rationale": ("TW ±7%/±10% price limit → |ret|>0.11 = yfinance adjustment glitch"
                          if daily_limit is not None else "none (no price-limit market)"),
            "removed_count": len(removed),
            "removed": removed,
        },
    }

    # ---- Primary spec ----
    TARGET, CAP, Q, WIN, VOLM = 0.15, 1.5, 0.60, 252, "rolling20"
    primary_res, nets, exps = run_config(ret, TARGET, CAP, Q, WIN, VOLM, cost_bps=5.0)
    asset["primary_spec"] = {
        "target_vol": TARGET, "exposure_cap": CAP, "regime_quantile": Q,
        "regime_window": WIN, "vol_forecast": VOLM, "cost_bps": 5.0,
        "results": primary_res,
    }

    # ---- Cost sensitivity (primary spec) ----
    cost_sens = {}
    for c in (1.0, 5.0, 10.0, 20.0):
        r, _, _ = run_config(ret, TARGET, CAP, Q, WIN, VOLM, cost_bps=c)
        cost_sens[f"{c:g}bps"] = {
            "always_vt": {k: r["always_vt"][k] for k in ("sharpe", "calmar", "mdd", "ann_turnover")},
            "gated_vt": {k: r["gated_vt"][k] for k in ("sharpe", "calmar", "mdd", "ann_turnover")},
            "buy_hold": {k: r["buy_hold"][k] for k in ("sharpe", "calmar", "mdd", "ann_turnover")},
            "sharpe_diff_gated_minus_vt": r["gated_vt"]["sharpe"] - r["always_vt"]["sharpe"],
            "boot_ci95": r["tests_gated_vs_alwaysvt"]["bootstrap_sharpe_diff"],
        }
    asset["cost_sensitivity"] = cost_sens

    # ---- Regime quantile sensitivity (cost=5bp) ----
    q_sens = {}
    for q in (0.50, 0.60, 0.70, 0.80):
        r, _, _ = run_config(ret, TARGET, CAP, q, WIN, VOLM, cost_bps=5.0)
        q_sens[f"q{q:g}"] = {
            "regime_frac_high": r["tests_gated_vs_alwaysvt"]["regime_frac_high"],
            "gated_sharpe": r["gated_vt"]["sharpe"],
            "always_vt_sharpe": r["always_vt"]["sharpe"],
            "sharpe_diff": r["gated_vt"]["sharpe"] - r["always_vt"]["sharpe"],
            "gated_turnover": r["gated_vt"]["ann_turnover"],
            "always_vt_turnover": r["always_vt"]["ann_turnover"],
        }
    asset["regime_quantile_sensitivity"] = q_sens

    # ---- Cap / vol-method robustness (cost=5bp) ----
    robust = {}
    for cap, volm in ((1.0, "rolling20"), (1.5, "ewma94"), (2.0, "rolling20")):
        r, _, _ = run_config(ret, TARGET, cap, Q, WIN, volm, cost_bps=5.0)
        robust[f"cap{cap:g}_{volm}"] = {
            "gated_sharpe": r["gated_vt"]["sharpe"],
            "always_vt_sharpe": r["always_vt"]["sharpe"],
            "sharpe_diff": r["gated_vt"]["sharpe"] - r["always_vt"]["sharpe"],
            "gated_calmar": r["gated_vt"]["calmar"],
            "always_vt_calmar": r["always_vt"]["calmar"],
        }
    asset["cap_volmethod_robustness"] = robust

    # ---- figures (primary only) ----
    if primary:
        try:
            _plot(ticker, ret, nets, exps)
            asset["figures"] = ["equity_curve.png", "exposure_regime.png"]
        except Exception as e:  # pragma: no cover
            asset["figures_error"] = str(e)
    return asset


def _plot(ticker, ret, nets, exps):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    idx = nets["always_vt"].index
    fig, ax = plt.subplots(figsize=(11, 5))
    for name, lab in (("buy_hold", "Buy&Hold"), ("always_vt", "Always-VT"), ("gated_vt", "Regime-gated VT")):
        cum = (1 + nets[name]).cumprod()
        ax.plot(cum.index, cum.values, label=lab, lw=1.2)
    ax.set_yscale("log")
    ax.set_title(f"K1660 {ticker} — net-of-cost equity (5bp): Always-VT vs Regime-gated VT")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "equity_curve.png"), dpi=110); plt.close(fig)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    a1.plot(exps["always_vt"].index, exps["always_vt"].values, label="Always-VT exposure", lw=0.7, color="tab:blue")
    a1.plot(exps["gated_vt"].index, exps["gated_vt"].values, label="Gated exposure", lw=0.7, color="tab:red", alpha=0.7)
    a1.axhline(1.0, color="k", lw=0.5, ls="--"); a1.legend(); a1.grid(alpha=0.3); a1.set_ylabel("exposure")
    reg = exps["_regime"]
    a2.fill_between(reg.index, 0, reg.values, step="pre", color="tab:orange", alpha=0.5)
    a2.set_ylabel("high-vol regime"); a2.set_xlabel("date"); a2.grid(alpha=0.3)
    a1.set_title(f"K1660 {ticker} — exposure paths & high-vol regime flag")
    fig.tight_layout(); fig.savefig(os.path.join(FIG_DIR, "exposure_regime.png"), dpi=110); plt.close(fig)


def main():
    np.random.seed(SEED)
    results = {
        "experiment_id": "k1660",
        "title": "Conditional (regime-gated) volatility targeting vs always-VT: net-of-cost performance",
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "lag_convention": "exposure computed at close t (up-to-t info), pos_t=exposure.shift(1) earns ret_t; turnover=|pos.diff()|; no lookahead",
        "cost_model": "per-turnover single-sided: net = pos*ret - (bps/1e4)*|pos.diff()|",
        "fairness": "baseline(always-VT) and gated share identical vol forecast, cap, floor, cost, lag; gated only forces exposure=1 in low-vol regime",
        "assets": {},
    }
    specs = [
        # ticker, start, end, primary, daily_return_limit (台股用漲跌幅限制清 glitch)
        ("SPY", "2010-01-01", "2026-07-01", True, None),
        ("0050.TW", "2010-01-01", "2026-07-01", False, 0.11),
    ]
    for ticker, start, end, primary, dlim in specs:
        try:
            results["assets"][ticker] = analyze_asset(ticker, start, end, primary, dlim)
        except Exception as e:
            results["assets"][ticker] = {"error": repr(e)}

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, default=float)
    print(f"wrote {RESULTS_PATH}")

    # concise console summary
    for tk, a in results["assets"].items():
        if "error" in a:
            print(f"{tk}: ERROR {a['error']}"); continue
        p = a["primary_spec"]["results"]
        t = p["tests_gated_vs_alwaysvt"]
        print(f"\n=== {tk} ({a['period']}, n={a['n_return_days']}) primary 5bp ===")
        for name in ("buy_hold", "always_vt", "gated_vt"):
            r = p[name]
            print(f"  {name:11s} Sharpe={r['sharpe']:.3f} Calmar={r['calmar']:.3f} "
                  f"MDD={r['mdd']*100:.1f}% turn={r['ann_turnover']:.2f}")
        b = t["bootstrap_sharpe_diff"]
        print(f"  gated-VT Sharpe diff={b['sharpe_diff_point']:+.4f} "
              f"CI95=[{b['ci95_lo']:+.3f},{b['ci95_hi']:+.3f}] bootP={b['boot_p_two_sided']:.3f} "
              f"| NW t={t['nw_hac_tstat']:.2f} p={t['nw_hac_pvalue']:.3f} "
              f"| high-regime frac={t['regime_frac_high']:.2%}")


if __name__ == "__main__":
    main()
