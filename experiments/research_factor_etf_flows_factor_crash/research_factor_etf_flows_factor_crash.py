"""Factor ETF flow-pressure crowding and factor-crash risk.

This is a yfinance-only proxy experiment. Historical ETF AUM / shares
outstanding are not consistently available for MTUM/QUAL/USMV/VLUE, so the
experiment does NOT claim to observe true fund flows. Instead it uses signed
dollar-volume pressure:

    sign(ETF excess return vs SPY) * Close * Volume

aggregated over 30 trading days and standardized with a rolling 252-day z-score.

Hypotheses:
1. High factor ETF crowding pressure predicts factor reversal.
2. High factor ETF crowding pressure predicts factor-basket volatility spikes.

Guardrails:
* seed = 42
* OOS split hard-coded
* signal = raw_signal.shift(1)
* forward targets start at t, so row t uses information through t-1
* 2 outcomes x 3 horizons = 6 primary tests; Bonferroni alpha = 0.05/6
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "research_factor_etf_flows_factor_crash"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_START = "2013-01-01"
DATA_END = "2026-06-15"
OOS_START = pd.Timestamp("2020-01-02")

FACTOR_ETFS = ["MTUM", "QUAL", "USMV", "VLUE"]
CONTROLS = ["SPY", "^VIX"]
ALL_TICKERS = sorted(set(FACTOR_ETFS + CONTROLS))
HORIZONS = [5, 21, 63]
OUTCOMES = ["reversal", "vol_spike"]
PRIMARY_TESTS = len(HORIZONS) * len(OUTCOMES)
BONFERRONI_ALPHA = 0.05 / PRIMARY_TESTS

BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
EVENT_COOLDOWN = 21
EPS = 1e-10


@dataclass
class TestResult:
    outcome: str
    horizon: int
    n_oos: int
    coefficient: float
    hac_t: float
    hac_p_two_sided: float
    expected_sign: str
    direction_supportive: bool
    passes_bonferroni: bool
    conditional_pass: bool


def download_ohlcv(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start=DATA_START, end=DATA_END, auto_adjust=True, progress=False, threads=False)
    if df.empty:
        raise RuntimeError(f"No data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Close", "Volume"]].dropna().copy()
    out.columns = pd.MultiIndex.from_product([[ticker], out.columns])
    return out


def load_data() -> pd.DataFrame:
    return pd.concat([download_ohlcv(t) for t in ALL_TICKERS], axis=1, sort=True).sort_index()


def realized_var(ret: pd.Series, window: int) -> pd.Series:
    return ret.pow(2).rolling(window, min_periods=window).mean() * 252.0


def forward_sum(x: pd.Series, horizon: int) -> pd.Series:
    return pd.concat([x.shift(-k) for k in range(horizon)], axis=1).sum(axis=1)


def forward_var(ret: pd.Series, horizon: int) -> pd.Series:
    return pd.concat([ret.shift(-k).pow(2) for k in range(horizon)], axis=1).mean(axis=1) * 252.0


def zscore_rolling(x: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    mu = x.rolling(window, min_periods=min_periods).mean()
    sd = x.rolling(window, min_periods=min_periods).std()
    return (x - mu) / sd


def build_panel(data: pd.DataFrame) -> pd.DataFrame:
    close = data.xs("Close", level=1, axis=1)
    volume = data.xs("Volume", level=1, axis=1)
    logret = np.log(close).diff()
    panel = pd.DataFrame(index=close.index)

    factor_excess = pd.DataFrame(index=close.index)
    pressure_z = pd.DataFrame(index=close.index)
    for etf in FACTOR_ETFS:
        factor_excess[etf] = logret[etf] - logret["SPY"]
        dollar_volume = close[etf] * volume[etf]
        signed_dollar_volume = np.sign(factor_excess[etf]) * dollar_volume
        pressure_30 = signed_dollar_volume.rolling(30, min_periods=20).sum() / (
            dollar_volume.rolling(252, min_periods=126).mean() + EPS
        )
        pressure_z[etf] = zscore_rolling(pressure_30)

    panel["factor_excess_ret"] = factor_excess.mean(axis=1)
    panel["factor_basket_ret"] = logret[FACTOR_ETFS].mean(axis=1)
    panel["crowding_raw"] = pressure_z.mean(axis=1)
    panel["crowding_z"] = zscore_rolling(panel["crowding_raw"])

    panel["spy_rv21"] = realized_var(logret["SPY"], 21)
    panel["spy_rv63"] = realized_var(logret["SPY"], 63)
    panel["factor_rv21"] = realized_var(panel["factor_basket_ret"], 21)
    panel["factor_rv63"] = realized_var(panel["factor_basket_ret"], 63)
    panel["factor_excess_ret21"] = panel["factor_excess_ret"].rolling(21, min_periods=21).sum()
    panel["vix_log"] = np.log(close["^VIX"])
    panel["vix_chg5"] = panel["vix_log"].diff(5)

    # Explicit lag: all predictors at row t are known by close t-1.
    for col in [
        "crowding_z",
        "spy_rv21",
        "spy_rv63",
        "factor_rv21",
        "factor_rv63",
        "factor_excess_ret21",
        "vix_log",
        "vix_chg5",
    ]:
        panel[f"{col}_l1"] = panel[col].shift(1)

    for h in HORIZONS:
        panel[f"fwd_excess_ret_{h}"] = forward_sum(panel["factor_excess_ret"], h)
        panel[f"fwd_factor_var_{h}"] = forward_var(panel["factor_basket_ret"], h)

    return panel


def fit_hac(panel: pd.DataFrame, outcome: str, horizon: int) -> TestResult:
    if outcome == "reversal":
        y_col = f"fwd_excess_ret_{horizon}"
        expected_sign = "negative"
    elif outcome == "vol_spike":
        y_col = f"fwd_factor_var_{horizon}"
        expected_sign = "positive"
    else:
        raise ValueError(outcome)

    cols = [
        "crowding_z_l1",
        "factor_excess_ret21_l1",
        "factor_rv21_l1",
        "factor_rv63_l1",
        "spy_rv21_l1",
        "spy_rv63_l1",
        "vix_log_l1",
        "vix_chg5_l1",
    ]
    df = panel.loc[panel.index >= OOS_START, [y_col] + cols].dropna()
    y = df[y_col].astype(float)
    x = sm.add_constant(df[cols].astype(float), has_constant="add")
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": horizon + 5})
    coef = float(fit.params["crowding_z_l1"])
    tval = float(fit.tvalues["crowding_z_l1"])
    pval = float(fit.pvalues["crowding_z_l1"])
    supportive = bool((coef < 0) if expected_sign == "negative" else (coef > 0))
    return TestResult(
        outcome=outcome,
        horizon=horizon,
        n_oos=int(len(df)),
        coefficient=coef,
        hac_t=tval,
        hac_p_two_sided=pval,
        expected_sign=expected_sign,
        direction_supportive=supportive,
        passes_bonferroni=bool(supportive and pval < BONFERRONI_ALPHA),
        conditional_pass=bool(supportive and pval < 0.05),
    )


def block_bootstrap_diff(values_a: np.ndarray, values_b: np.ndarray, seed: int) -> dict:
    values_a = np.asarray(values_a, dtype=float)
    values_b = np.asarray(values_b, dtype=float)
    rng = np.random.default_rng(seed)
    if len(values_a) < 2 or len(values_b) < 10:
        return {"diff": float("nan"), "ci95": [float("nan"), float("nan")], "p_direction": float("nan")}
    diffs = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        a = rng.choice(values_a, size=len(values_a), replace=True)
        b = rng.choice(values_b, size=len(values_a), replace=True)
        diffs[i] = a.mean() - b.mean()
    return {
        "diff": float(values_a.mean() - values_b.mean()),
        "ci95": [float(x) for x in np.percentile(diffs, [2.5, 97.5])],
        "p_gt_0": float((np.sum(diffs <= 0.0) + 1) / (BOOTSTRAP_REPS + 1)),
        "p_lt_0": float((np.sum(diffs >= 0.0) + 1) / (BOOTSTRAP_REPS + 1)),
    }


def select_events(panel: pd.DataFrame) -> list[pd.Timestamp]:
    signal = panel["crowding_z"].shift(1)
    threshold = panel["crowding_z"].rolling(756, min_periods=504).quantile(0.90).shift(1)
    events: list[pd.Timestamp] = []
    last_pos = -10_000
    for pos, date in enumerate(panel.index):
        if date < OOS_START or pos - last_pos <= EVENT_COOLDOWN:
            continue
        val = signal.iloc[pos]
        thr = threshold.iloc[pos]
        if np.isfinite(val) and np.isfinite(thr) and val > thr:
            events.append(date)
            last_pos = pos
    return events


def event_study(panel: pd.DataFrame, events: list[pd.Timestamp]) -> dict:
    event_idx = pd.Index(events)
    out = {"n_events": len(events), "cooldown_days": EVENT_COOLDOWN, "horizons": {}}
    for h in HORIZONS:
        oos = panel.loc[panel.index >= OOS_START]
        ev = oos[oos.index.isin(event_idx)]
        non = oos[~oos.index.isin(event_idx)]
        ret_ev = ev[f"fwd_excess_ret_{h}"].dropna()
        ret_non = non[f"fwd_excess_ret_{h}"].dropna()
        var_ev = ev[f"fwd_factor_var_{h}"].dropna()
        var_non = non[f"fwd_factor_var_{h}"].dropna()
        out["horizons"][str(h)] = {
            "return_event_minus_non_event": block_bootstrap_diff(ret_ev.values, ret_non.values, seed=SEED + h),
            "variance_event_minus_non_event": block_bootstrap_diff(var_ev.values, var_non.values, seed=SEED + h + 100),
        }
    return out


def make_figures(panel: pd.DataFrame, results: list[TestResult], events: list[pd.Timestamp]) -> list[str]:
    paths: list[str] = []

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=False)
    for ax, outcome, title in [
        (axes[0], "reversal", "Reversal tests: crowding coefficient"),
        (axes[1], "vol_spike", "Vol-spike tests: crowding coefficient"),
    ]:
        subset = [r for r in results if r.outcome == outcome]
        labels = [f"{r.horizon}d" for r in subset]
        vals = [r.hac_t for r in subset]
        colors = ["#8a5a2b" if r.direction_supportive else "#777777" for r in subset]
        ax.bar(labels, vals, color=colors)
        ax.axhline(0, color="black", lw=0.8)
        ax.axhline(3, color="firebrick", lw=0.9, ls=":")
        ax.axhline(-3, color="firebrick", lw=0.9, ls=":")
        for i, r in enumerate(subset):
            ax.text(i, vals[i] + (0.12 if vals[i] >= 0 else -0.12), f"p={r.hac_p_two_sided:.3f}", ha="center", va="bottom" if vals[i] >= 0 else "top", fontsize=8)
        ax.set_title(title)
        ax.set_ylabel("HAC t-stat")
        ax.grid(axis="y", alpha=0.25)
    fig.suptitle("Factor ETF crowding proxy: primary OOS tests")
    fig.tight_layout()
    p = os.path.join(OUT_DIR, "fig_primary_hac_tests.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    oos = panel.loc[panel.index >= OOS_START, "crowding_z"]
    ax.plot(oos.index, oos.values, lw=1.4, color="#2f6f8f", label="crowding proxy z-score")
    if events:
        ev_vals = panel.loc[events, "crowding_z"]
        ax.scatter(ev_vals.index, ev_vals.values, s=24, color="#8a2b2b", label="top-decile events")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title("Factor ETF signed dollar-volume pressure proxy")
    ax.set_ylabel("Rolling z-score")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = os.path.join(OUT_DIR, "fig_crowding_proxy_events.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    paths.append(p)
    return paths


def main() -> int:
    data = load_data()
    panel = build_panel(data)
    results = [fit_hac(panel, outcome, h) for outcome in OUTCOMES for h in HORIZONS]
    for r in results:
        print(
            f"{r.outcome} h={r.horizon}: coef={r.coefficient:.6g} "
            f"t={r.hac_t:.3f} p={r.hac_p_two_sided:.4f} "
            f"support={r.direction_supportive} bonf={r.passes_bonferroni}"
        )

    events = select_events(panel)
    ev = event_study(panel, events)
    figs = make_figures(panel, results, events)

    any_pass = any(r.passes_bonferroni for r in results)
    any_cond = any(r.conditional_pass for r in results)
    if any_pass:
        verdict = "PASS"
    elif any_cond:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    output = {
        "experiment_id": EXPERIMENT_ID,
        "seed": SEED,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "data": {
            "source": "yfinance auto_adjust=True daily close/volume",
            "start": DATA_START,
            "end_exclusive": DATA_END,
            "actual_last_date": str(data.index.max().date()),
            "factor_etfs": FACTOR_ETFS,
            "controls": CONTROLS,
            "flow_data_limitation": "Historical AUM/shares outstanding unavailable or incomplete for most ETFs; proxy uses signed dollar-volume pressure, not true AUM flow.",
        },
        "method": {
            "proxy": "30d sum(sign(ETF excess return vs SPY) * close * volume) / 252d average dollar volume, rolling z-scored per ETF then averaged.",
            "oos_start": str(OOS_START.date()),
            "feature_lag": "crowding_z_l1 = crowding_z.shift(1); all controls also shift(1)",
            "targets": {
                "reversal": "forward sum of equal-weight factor ETF excess return vs SPY",
                "vol_spike": "forward annualized variance of equal-weight factor ETF basket return",
            },
            "controls": "21d factor excess return, 21/63d factor RV, 21/63d SPY RV, VIX log level, VIX 5d change",
            "primary_tests": PRIMARY_TESTS,
            "bonferroni_alpha": BONFERRONI_ALPHA,
            "hac_maxlags": "horizon + 5",
        },
        "primary_results": [r.__dict__ for r in results],
        "event_study": ev,
        "verdict": verdict,
        "verdict_rationale": {
            "any_bonferroni_pass": any_pass,
            "any_conditional_pass": any_cond,
            "supportive_cells": sum(1 for r in results if r.direction_supportive),
        },
        "literature_sources": [
            {
                "name": "Smart beta, smarter flows, Journal of Empirical Finance, 2025",
                "url": "https://ideas.repec.org/a/eee/empfin/v81y2025ics0927539825000027.html",
            },
            {
                "name": "Competition for Attention in the ETF Space, Review of Financial Studies",
                "url": "https://academic.oup.com/rfs/advance-article/doi/10.1093/rfs/hhac048/6655702",
            },
            {
                "name": "The Smart Beta Mirage, 2025",
                "url": "https://ira.lib.polyu.edu.hk/bitstream/10397/102732/1/Huang_Smart_Beta_Mirage.pdf",
            },
            {
                "name": "iShares ETF and ETP Market Trends Q1 2026",
                "url": "https://www.ishares.com/us/insights/inside-the-market/2026-etf-market-trends-and-flows",
            },
        ],
        "figures": [os.path.basename(p) for p in figs],
        "caveats": [
            "This is not a true AUM-flow study; historical ETF shares/AUM were unavailable for most tickers through yfinance.",
            "Signed dollar-volume pressure mixes investor flow, liquidity demand, and price impact.",
            "The ETF set is narrow: MTUM/QUAL/USMV/VLUE only.",
            "Regression study is not a tradable strategy backtest.",
        ],
    }
    out = os.path.join(OUT_DIR, f"{EXPERIMENT_ID}_results.json")
    with open(out, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
