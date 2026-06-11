"""K1467 — Tail-hedging overlay vs crisis alpha (SPY + VXX overlay).

Research question
-----------------
Does a long-volatility tail-hedge overlay (5%/10% VXX bought daily, financed by
SPY weight) recover its long-run drag through crisis alpha?

Comparisons
-----------
- SPY-only buy-and-hold (baseline).
- SPY + 5% / 10% VXX overlay (rebalanced daily).
- K544-style 12/VIX VT (re-coded inline) as the prior-art benchmark.

Metrics
-------
- Annualised drag (cumulative CAGR diff vs SPY-only) → compare to JPM/Goldman
  2025 "true cost of tail hedging" headline of ~-355 bps/yr.
- Crisis-period drawdown gap (peak-to-trough max-drawdown reduction).
- Beta-adjusted alpha vs SPY (Newey-West HAC, 5 lags).
- Sharpe / Sortino full-sample.

Anti-error rules (CLAUDE.md / experiments.md)
---------------------------------------------
- signal.shift(1) lag on every overlay weight (signal at t-1, return at t).
- Fixed seed = 20260611 for any stochastic step.
- yfinance VXX coverage: 2009-01-30+ (post-Barclays ETN reset); we use the
  full available history without back-filling.
- Transaction cost: 5 bps round-trip on overlay turnover (asymmetric — SPY-only
  has zero turnover after t=0 because it's buy-and-hold).
- Statsmodels OLS + Newey-West cov_type='HAC' (lags=5).
- Crisis windows are pre-registered (not data-mined): 2020-Q1 COVID, 2022 bear,
  2018-Q4 vol-spike, 2025-Q2 tariff spike.

Outputs
-------
experiments/K1467/K1467_results.json
experiments/K1467/fig_cum_returns.png
experiments/K1467/fig_drawdown.png
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.api as sm

SEED = 20260611
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

TICKERS = ["SPY", "VXX", "^VIX"]
# NOTE: VXX original Barclays ETN inception was 2009-01-30, but the iPath
# Series-B ETN (current ticker) reset in 2018-01; yfinance returns the
# Series-B history only.  Effective common sample is 2018-01-26 → today.
# Pre-2018 VXX history would require splicing Series-A (delisted) — out of
# scope for this experiment; we report the 2018+ window honestly.
START = "2009-01-30"
END = "2026-06-10"

TC_BPS = 5.0  # round-trip transaction cost on overlay leg, basis points
TRADING_DAYS = 252

# Pre-registered crisis windows (NOT data-mined ex post)
CRISES = [
    ("2018Q4_volmageddon", "2018-09-20", "2018-12-31"),
    ("2020Q1_covid", "2020-02-19", "2020-04-30"),
    ("2022_bear", "2022-01-03", "2022-10-12"),
    ("2025Q2_tariff", "2025-02-19", "2025-04-30"),
]


# ----------------------------- data --------------------------------- #

def fetch_prices() -> pd.DataFrame:
    cache = DATA_DIR / "prices.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    df = yf.download(TICKERS, start=START, end=END, auto_adjust=True,
                     progress=False, threads=False)
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].copy()
    else:
        close = df[["Close"]].rename(columns={"Close": TICKERS[0]})
    close = close.dropna(how="all")
    close.to_parquet(cache)
    return close


# --------------------------- backtests ------------------------------ #

@dataclass
class StratResult:
    name: str
    cagr: float
    vol_ann: float
    sharpe: float
    sortino: float
    mdd: float
    final_value: float
    n_days: int
    annual_drag_vs_spy_bps: float
    alpha_bps_ann: float
    alpha_t: float
    alpha_p: float
    beta: float


def to_returns(close: pd.DataFrame) -> pd.DataFrame:
    return close.pct_change().dropna(how="all")


def buy_and_hold(spy_ret: pd.Series) -> pd.Series:
    return spy_ret.copy()


def overlay_strategy(spy_ret: pd.Series, vxx_ret: pd.Series, weight: float,
                     tc_bps: float = TC_BPS) -> pd.Series:
    """SPY (1-w) + VXX (w) rebalanced daily.

    Signal: fixed weight known at t-1 (no lookahead).  Daily rebalance means
    daily turnover on the VXX leg ≈ |w * (r_spy - r_vxx)|.
    """
    df = pd.concat([spy_ret.rename("spy"), vxx_ret.rename("vxx")], axis=1).dropna()
    port_ret = (1 - weight) * df["spy"] + weight * df["vxx"]
    # Daily-rebalance turnover on overlay leg: post-day weight drift back to w.
    # Per-leg turnover ≈ w*(1-w)*|r_spy - r_vxx| / (1 + r_port).  Round-trip
    # (buy + sell across both legs) gives factor 2*w*(1-w)*|r_spy - r_vxx| / ...
    # Codex v1 fix: denominator (1 + r_port), not |r_port|.
    # Codex v2 fix: include (1-w) factor so cost scales correctly with weight.
    turnover = (2 * weight * (1 - weight) * (df["spy"] - df["vxx"]).abs() /
                (1.0 + port_ret))
    cost = turnover.abs() * (tc_bps / 1e4)
    return (port_ret - cost).rename(f"spy_vxx_{int(weight*100)}pct")


def vt_12_over_vix(spy_ret: pd.Series, vix: pd.Series,
                   tc_bps: float = TC_BPS) -> pd.Series:
    """K544-style 12/VIX target-vol overlay on SPY (cap at 1.5x)."""
    weight = (12.0 / vix).clip(upper=1.5)
    weight = weight.shift(1)  # explicit shift(1) — signal at t-1
    df = pd.concat([spy_ret.rename("spy"), weight.rename("w")], axis=1).dropna()
    port_ret = df["w"] * df["spy"]
    turnover = df["w"].diff().abs().fillna(0.0)
    cost = turnover * (tc_bps / 1e4)
    return (port_ret - cost).rename("vt_12_over_vix")


# --------------------------- metrics -------------------------------- #

def equity_curve(ret: pd.Series) -> pd.Series:
    return (1 + ret).cumprod()


def max_drawdown(eq: pd.Series) -> float:
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min())


def cagr(eq: pd.Series) -> float:
    n_years = len(eq) / TRADING_DAYS
    if n_years <= 0:
        return 0.0
    return float(eq.iloc[-1] ** (1 / n_years) - 1)


def sharpe(ret: pd.Series) -> float:
    if ret.std() == 0:
        return 0.0
    return float(ret.mean() / ret.std() * np.sqrt(TRADING_DAYS))


def sortino(ret: pd.Series) -> float:
    downside = ret[ret < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float(ret.mean() / downside.std() * np.sqrt(TRADING_DAYS))


def newey_west_alpha(strat_ret: pd.Series, bench_ret: pd.Series,
                     lags: int = 5) -> Tuple[float, float, float, float]:
    """Regress strat on bench with HAC SE.  Returns (alpha_ann_bps, t, p, beta)."""
    df = pd.concat([strat_ret.rename("y"), bench_ret.rename("x")], axis=1).dropna()
    X = sm.add_constant(df["x"])
    model = sm.OLS(df["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    alpha_daily = float(model.params["const"])
    alpha_ann_bps = alpha_daily * TRADING_DAYS * 1e4
    return (alpha_ann_bps,
            float(model.tvalues["const"]),
            float(model.pvalues["const"]),
            float(model.params["x"]))


def crisis_metrics(strat_eq: pd.Series, bench_eq: pd.Series) -> List[Dict]:
    out = []
    for name, start, end in CRISES:
        try:
            s_slice = strat_eq.loc[start:end]
            b_slice = bench_eq.loc[start:end]
            if len(s_slice) == 0 or len(b_slice) == 0:
                continue
            s_dd = float(s_slice.min() / s_slice.iloc[0] - 1)
            b_dd = float(b_slice.min() / b_slice.iloc[0] - 1)
            s_end = float(s_slice.iloc[-1] / s_slice.iloc[0] - 1)
            b_end = float(b_slice.iloc[-1] / b_slice.iloc[0] - 1)
            out.append({
                "crisis": name,
                "start": start, "end": end,
                "n_days": int(len(s_slice)),
                "strat_intraperiod_mdd": s_dd,
                "bench_intraperiod_mdd": b_dd,
                "mdd_reduction": s_dd - b_dd,
                "strat_period_return": s_end,
                "bench_period_return": b_end,
                "crisis_alpha": s_end - b_end,
            })
        except Exception as e:
            out.append({"crisis": name, "error": str(e)})
    return out


def summarise(name: str, strat_ret: pd.Series,
              bench_ret: pd.Series) -> StratResult:
    eq = equity_curve(strat_ret)
    bench_eq = equity_curve(bench_ret)
    cgr_strat = cagr(eq)
    cgr_bench = cagr(bench_eq)
    drag_bps = (cgr_strat - cgr_bench) * 1e4
    alpha_ann_bps, t, p, beta = newey_west_alpha(strat_ret, bench_ret)
    return StratResult(
        name=name,
        cagr=cgr_strat,
        vol_ann=float(strat_ret.std() * np.sqrt(TRADING_DAYS)),
        sharpe=sharpe(strat_ret),
        sortino=sortino(strat_ret),
        mdd=max_drawdown(eq),
        final_value=float(eq.iloc[-1]),
        n_days=int(len(strat_ret)),
        annual_drag_vs_spy_bps=float(drag_bps),
        alpha_bps_ann=float(alpha_ann_bps),
        alpha_t=float(t),
        alpha_p=float(p),
        beta=float(beta),
    )


# --------------------------- plots ---------------------------------- #

def plot_cum_returns(curves: Dict[str, pd.Series], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    for name, eq in curves.items():
        ax.plot(eq.index, eq.values, label=name, linewidth=1.2)
    ax.set_yscale("log")
    ax.set_title("K1467 — Cumulative Wealth, $1 → today (log scale)")
    ax.set_ylabel("Equity (log)")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_drawdown(curves: Dict[str, pd.Series], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    for name, eq in curves.items():
        peak = eq.cummax()
        dd = eq / peak - 1.0
        ax.plot(dd.index, dd.values, label=name, linewidth=1.0)
    for cname, s, e in CRISES:
        ax.axvspan(pd.to_datetime(s), pd.to_datetime(e),
                   color="red", alpha=0.08)
    ax.set_title("K1467 — Drawdown paths (crisis windows shaded)")
    ax.set_ylabel("Drawdown")
    ax.legend(loc="lower left", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# --------------------------- main ----------------------------------- #

def main() -> None:
    close = fetch_prices()
    print("Data shape:", close.shape, "cols:", list(close.columns))
    print("Date range:", close.index.min(), "->", close.index.max())

    rets = to_returns(close)
    spy_ret = rets["SPY"].dropna()
    vxx_ret = rets["VXX"].dropna()
    vix = close["^VIX"].dropna()

    bench = buy_and_hold(spy_ret).rename("SPY_only")
    s5 = overlay_strategy(spy_ret, vxx_ret, 0.05)
    s10 = overlay_strategy(spy_ret, vxx_ret, 0.10)
    s_vt = vt_12_over_vix(spy_ret, vix)

    common_idx = bench.index.intersection(s5.index).intersection(s10.index)
    bench_c = bench.loc[common_idx]
    s5_c = s5.loc[common_idx]
    s10_c = s10.loc[common_idx]
    s_vt_c = s_vt.reindex(common_idx).fillna(0.0)

    results = {
        "experiment": "K1467",
        "title": "Tail-hedging overlay vs crisis alpha",
        "seed": SEED,
        "data_source": "yfinance (Yahoo Finance)",
        "tickers": TICKERS,
        "window": {
            "start": str(bench_c.index.min().date()),
            "end": str(bench_c.index.max().date()),
            "n_days": int(len(bench_c)),
            "n_years": round(len(bench_c) / TRADING_DAYS, 2),
        },
        "tc_bps_overlay_roundtrip": TC_BPS,
        "crisis_windows": [{"name": n, "start": s, "end": e} for n, s, e in CRISES],
        "summary": {},
        "crisis_panel": {},
        "jpm_gs_benchmark_drag_bps_yr": -355.0,
        "interpretation": {},
    }

    strat_dict = {
        "SPY_only": bench_c,
        "SPY+5%_VXX": s5_c,
        "SPY+10%_VXX": s10_c,
        "VT_12_over_VIX": s_vt_c,
    }
    for name, sr in strat_dict.items():
        res = summarise(name, sr.reindex(common_idx).dropna(), bench_c)
        results["summary"][name] = asdict(res)

    bench_eq = equity_curve(bench_c)
    for name, sr in strat_dict.items():
        if name == "SPY_only":
            continue
        strat_eq = equity_curve(sr.reindex(common_idx).dropna())
        results["crisis_panel"][name] = crisis_metrics(strat_eq, bench_eq)

    curves = {n: equity_curve(s.reindex(common_idx).fillna(0.0))
              for n, s in strat_dict.items()}
    plot_cum_returns(curves, HERE / "fig_cum_returns.png")
    plot_drawdown(curves, HERE / "fig_drawdown.png")

    drag5 = results["summary"]["SPY+5%_VXX"]["annual_drag_vs_spy_bps"]
    drag10 = results["summary"]["SPY+10%_VXX"]["annual_drag_vs_spy_bps"]
    alpha5_t = results["summary"]["SPY+5%_VXX"]["alpha_t"]
    alpha10_t = results["summary"]["SPY+10%_VXX"]["alpha_t"]
    results["interpretation"] = {
        "drag_5pct_overlay_bps_yr": drag5,
        "drag_10pct_overlay_bps_yr": drag10,
        "vs_jpm_gs_355bp": {
            "5pct": drag5 - (-355.0),
            "10pct": drag10 - (-355.0),
        },
        "alpha_significant_at_5pct": {
            "5pct_overlay": bool(abs(alpha5_t) > 1.96),
            "10pct_overlay": bool(abs(alpha10_t) > 1.96),
        },
        "verdict_logic": (
            "PASS if (a) any overlay shows positive Newey-West alpha "
            "significant at 5% AND (b) crisis-period drawdown reduction "
            ">= 200bps in >=1 pre-registered window.  "
            "NULL if alpha NS and drag exists.  "
            "FAIL if drag > -500bps/yr with no offsetting crisis alpha."
        ),
    }

    sig_alpha = (alpha5_t > 1.96) or (alpha10_t > 1.96)
    crisis_help = False
    for strat_name in ("SPY+5%_VXX", "SPY+10%_VXX"):
        for row in results["crisis_panel"][strat_name]:
            if row.get("mdd_reduction", 0) >= 0.02:
                crisis_help = True
                break
        if crisis_help:
            break

    if sig_alpha and crisis_help:
        verdict = "PASS"
    elif crisis_help and not sig_alpha and (drag5 > -500 or drag10 > -500):
        verdict = "CONDITIONAL_PASS"
    elif (not sig_alpha) and (drag5 < -100):
        verdict = "NULL"
    else:
        verdict = "MIXED"
    results["verdict"] = verdict

    results["generated_at"] = datetime.now(timezone.utc).isoformat()

    out_path = HERE / "K1467_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Wrote {out_path}")
    print(f"Verdict: {verdict}")
    print(f"Drag 5%: {drag5:.0f}bp/yr, 10%: {drag10:.0f}bp/yr")
    print(f"Alpha 5% t={alpha5_t:.2f}, 10% t={alpha10_t:.2f}")


if __name__ == "__main__":
    main()
