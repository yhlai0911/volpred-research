"""K1590 Merger Arbitrage Deal-Spread Vol — Diagnostic Phase.

Goal: Decide GO / NO-GO for a full-scale merger-arb deal-spread vol experiment by
characterizing whether MNA (IQ Merger Arbitrage ETF) carries deal-spread vol
information distinct from a passive equity / credit proxy.

Pipeline:
  1. Pull yfinance daily adj-close 2020-01-01 .. today for MNA, SPY, IWM, HYG, ^VIX.
  2. Compute MNA daily log returns + benchmark relative excess returns
     (MNA - SPY, MNA - HYG).
  3. Descriptive stats: mean / std / skew / kurt — full sample + VIX regime
     (low <20, mid 20-30, high >30).
  4. Pearson corr matrix: MNA returns vs SPY / IWM / HYG / VIX.
  5. Rolling 21-day MNA realized vol time series.
  6. Vol regime breakpoint t-test: high-VIX-day MNA RV vs low-VIX-day MNA RV.
     Classification uses **same-day VIX close** (t-stat reports next-day RV
     alignment too for transparency).
  7. GO / NO-GO verdict.

Lookahead policy: this is a diagnostic / characterization run — no forecasting,
no signal -> return mapping. Vol regime test classifies day t by VIX_t and
measures RV_t for descriptive symmetry; we also report a t-1 VIX classification
robustness number so any forward inference is not misled.

References (anchors, not fully cited):
  Mitchell & Pulvino (2001) JoF — risk-arb bear/bull asymmetry.
  Baker & Savaşoglu (2002) JFE — deal completion risk pricing.

Author: VolPred autonomous research (K1590).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

# ---- reproducibility ----
np.random.seed(42)

OUT = Path(__file__).resolve().parent
PLOTS = OUT / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)

TICKERS = ["MNA", "SPY", "IWM", "HYG", "^VIX"]
START = "2020-01-01"
END = dt.date.today().isoformat()


def safe_float(x) -> float | None:
    """Convert numpy / pandas scalars to plain float, NaN -> None for JSON."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if np.isnan(f) or np.isinf(f):
        return None
    return f


def pull_data() -> pd.DataFrame:
    """Pull adj-close daily data via yfinance.

    Critical: use auto_adjust=False per error_log 2026-04-13 lesson so we
    explicitly read Adj Close (yfinance changed default in late 2025).
    """
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        progress=False,
        auto_adjust=False,
        group_by="ticker",
    )
    # multi-index columns: (ticker, field). Pull Adj Close per ticker.
    closes = {}
    for t in TICKERS:
        if (t, "Adj Close") in raw.columns:
            closes[t] = raw[(t, "Adj Close")]
        elif (t, "Close") in raw.columns:
            closes[t] = raw[(t, "Close")]
        else:
            raise RuntimeError(f"Missing close column for {t}")
    df = pd.concat(closes, axis=1)
    df.columns = TICKERS
    df = df.dropna(how="all")
    return df


def main() -> dict:
    run_at = dt.datetime.now().isoformat()
    print(f"[K1590] start {run_at}")
    prices = pull_data()
    print(f"[K1590] prices shape={prices.shape} range={prices.index[0].date()}..{prices.index[-1].date()}")

    # ---- log returns ----
    rets = np.log(prices / prices.shift(1)).dropna(how="all")
    # VIX is *level* not return for regime classification, but we keep returns
    # for the corr table.
    vix_level = prices["^VIX"].reindex(rets.index)

    # MNA core
    mna = rets["MNA"].dropna()
    spy = rets["SPY"].reindex(mna.index)
    iwm = rets["IWM"].reindex(mna.index)
    hyg = rets["HYG"].reindex(mna.index)
    vix_ret = rets["^VIX"].reindex(mna.index)
    vix_lvl = vix_level.reindex(mna.index)

    excess_spy = mna - spy
    excess_hyg = mna - hyg

    n = len(mna)
    print(f"[K1590] MNA returns N={n}")

    # ---- descriptives helpers ----
    def desc(series: pd.Series) -> dict:
        s = series.dropna()
        return {
            "n": int(len(s)),
            "mean": safe_float(s.mean()),
            "std": safe_float(s.std(ddof=1)),
            "skew": safe_float(stats.skew(s, bias=False)) if len(s) > 3 else None,
            "kurt_excess": safe_float(stats.kurtosis(s, bias=False, fisher=True)) if len(s) > 3 else None,
            "min": safe_float(s.min()),
            "max": safe_float(s.max()),
        }

    full_stats = {
        "MNA": desc(mna),
        "MNA_minus_SPY": desc(excess_spy),
        "MNA_minus_HYG": desc(excess_hyg),
        "SPY": desc(spy),
        "HYG": desc(hyg),
        "VIX_level": desc(vix_lvl),
    }

    # ---- VIX regime split (classification by SAME-DAY VIX close) ----
    regime_low = vix_lvl < 20
    regime_mid = (vix_lvl >= 20) & (vix_lvl <= 30)
    regime_high = vix_lvl > 30

    regime_stats = {
        "low_vix_lt20": {
            "n_days": int(regime_low.sum()),
            "MNA": desc(mna[regime_low]),
            "MNA_minus_SPY": desc(excess_spy[regime_low]),
            "MNA_minus_HYG": desc(excess_hyg[regime_low]),
        },
        "mid_vix_20_30": {
            "n_days": int(regime_mid.sum()),
            "MNA": desc(mna[regime_mid]),
            "MNA_minus_SPY": desc(excess_spy[regime_mid]),
            "MNA_minus_HYG": desc(excess_hyg[regime_mid]),
        },
        "high_vix_gt30": {
            "n_days": int(regime_high.sum()),
            "MNA": desc(mna[regime_high]),
            "MNA_minus_SPY": desc(excess_spy[regime_high]),
            "MNA_minus_HYG": desc(excess_hyg[regime_high]),
        },
    }

    # ---- correlations ----
    corr_frame = pd.concat(
        {
            "MNA": mna,
            "SPY": spy,
            "IWM": iwm,
            "HYG": hyg,
            "VIX_ret": vix_ret,
            "VIX_lvl": vix_lvl,
        },
        axis=1,
    ).dropna()
    pearson = corr_frame.corr(method="pearson")
    spearman = corr_frame.corr(method="spearman")
    corr_dict = {
        "pearson": pearson.round(4).to_dict(),
        "spearman": spearman.round(4).to_dict(),
        "n_obs_for_corr": int(len(corr_frame)),
    }

    # ---- rolling 21-day realized vol (annualized) ----
    rv21 = mna.rolling(21).std(ddof=1) * np.sqrt(252)
    rv21 = rv21.dropna()

    # Plot rolling vol
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(rv21.index, rv21.values, lw=1.0, color="#1f77b4", label="MNA 21d ann. vol")
    ax2 = ax.twinx()
    ax2.plot(vix_lvl.reindex(rv21.index).index, vix_lvl.reindex(rv21.index).values,
             lw=0.8, color="#d62728", alpha=0.55, label="VIX level")
    ax.set_title("K1590 — MNA 21d annualized realized vol vs VIX level (2020-2026)")
    ax.set_ylabel("MNA RV (annualized)")
    ax2.set_ylabel("VIX")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(PLOTS / "rolling_vol_vs_vix.png", dpi=130)
    plt.close(fig)

    # ---- vol regime t-test: high-VIX days RV vs low-VIX days RV ----
    # Use absolute return as daily proxy for vol (each-day pointwise). Cleaner
    # than 21d RV which leaks across regime boundaries.
    abs_ret = mna.abs()
    high_abs = abs_ret[regime_high].dropna()
    low_abs = abs_ret[regime_low].dropna()

    t_stat, p_value = stats.ttest_ind(high_abs, low_abs, equal_var=False, nan_policy="omit")
    # Robustness: classify by lagged VIX (t-1) -> measure RV on day t.
    vix_lvl_lag1 = vix_lvl.shift(1)
    regime_high_lag = vix_lvl_lag1 > 30
    regime_low_lag = vix_lvl_lag1 < 20
    high_abs_lag = abs_ret[regime_high_lag].dropna()
    low_abs_lag = abs_ret[regime_low_lag].dropna()
    t_stat_lag, p_value_lag = stats.ttest_ind(
        high_abs_lag, low_abs_lag, equal_var=False, nan_policy="omit"
    )

    # Also compute mean abs return per regime explicitly for the verdict.
    mean_abs_high = safe_float(high_abs.mean())
    mean_abs_low = safe_float(low_abs.mean())
    magnitude_ratio = (mean_abs_high / mean_abs_low) if (mean_abs_high and mean_abs_low) else None

    vol_regime_test = {
        "method": "Welch two-sample t-test on |daily log return| (MNA) classified by same-day VIX level",
        "low_vix_lt20": {
            "n": int(len(low_abs)),
            "mean_abs_ret": mean_abs_low,
            "std_abs_ret": safe_float(low_abs.std(ddof=1)),
        },
        "high_vix_gt30": {
            "n": int(len(high_abs)),
            "mean_abs_ret": mean_abs_high,
            "std_abs_ret": safe_float(high_abs.std(ddof=1)),
        },
        "t_stat": safe_float(t_stat),
        "p_value": safe_float(p_value),
        "magnitude_ratio_high_over_low": magnitude_ratio,
        "robustness_lag1_vix_classification": {
            "t_stat": safe_float(t_stat_lag),
            "p_value": safe_float(p_value_lag),
            "n_low": int(len(low_abs_lag)),
            "n_high": int(len(high_abs_lag)),
        },
    }

    # Plot regime split (box / violin)
    fig, ax = plt.subplots(figsize=(8, 5))
    data = [
        mna[regime_low].dropna().values,
        mna[regime_mid].dropna().values,
        mna[regime_high].dropna().values,
    ]
    labels = [
        f"low VIX<20\nn={int(regime_low.sum())}",
        f"mid VIX 20-30\nn={int(regime_mid.sum())}",
        f"high VIX>30\nn={int(regime_high.sum())}",
    ]
    bp = ax.boxplot(data, labels=labels, showfliers=False, patch_artist=True)
    for patch, color in zip(bp["boxes"], ["#a6cee3", "#fdbf6f", "#fb9a99"]):
        patch.set_facecolor(color)
    ax.set_title(
        "K1590 — MNA daily log return distribution across VIX regimes\n"
        f"t-test high vs low |ret|: t={safe_float(t_stat):.2f}, p={safe_float(p_value):.3g}"
    )
    ax.set_ylabel("Daily log return")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(PLOTS / "regime_split_box.png", dpi=130)
    plt.close(fig)

    # ---- VERDICT ----
    # GO conditions:
    #   (a) p < 0.05 on vol regime split
    #   (b) magnitude_ratio_high_over_low >= 1.5 (i.e. high-VIX days carry >=50% larger |ret|)
    #   (c) MNA NOT a near-perfect SPY clone: pearson(MNA, SPY) < 0.9
    # NO-GO if any of (a)(b)(c) hard-fails.
    pearson_mna_spy = safe_float(pearson.loc["MNA", "SPY"]) or 0.0
    p_val = safe_float(p_value) or 1.0
    mag = magnitude_ratio or 0.0

    cond_a = p_val < 0.05
    cond_b = mag >= 1.5
    cond_c = pearson_mna_spy < 0.9

    if cond_a and cond_b and cond_c:
        verdict = "GO"
    elif (cond_a or cond_b) and cond_c:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "NO-GO"

    verdict_reasoning = {
        "cond_a_p_lt_0.05": {"pass": bool(cond_a), "p_value": p_val},
        "cond_b_mag_ratio_ge_1.5": {"pass": bool(cond_b), "ratio": mag},
        "cond_c_not_spy_clone_pearson_lt_0.9": {"pass": bool(cond_c), "pearson_mna_spy": pearson_mna_spy},
        "decision_rule": "GO requires all three; NO-GO if cond_c fails (i.e. MNA is SPY clone) OR neither (a) nor (b) passes; otherwise INCONCLUSIVE.",
    }

    results = {
        "meta": {
            "experiment_id": "k1590",
            "title": "Merger Arbitrage Deal-Spread Vol — Diagnostic Phase",
            "run_at": run_at,
            "data_source": "yfinance Adj Close (auto_adjust=False)",
            "tickers": TICKERS,
            "period": {"start": START, "end": END, "n_trading_days": n},
            "seed": 42,
            "code_path": "experiments/k1590/k1590_diagnostic.py",
        },
        "full_sample_stats": full_stats,
        "vix_regime_stats": regime_stats,
        "correlations": corr_dict,
        "vol_regime_test": vol_regime_test,
        "verdict": verdict,
        "verdict_reasoning": verdict_reasoning,
        "limitations": [
            "MNA is a portfolio-level proxy for cross-deal merger-arb spread vol; individual deal-spread data not used.",
            "Sample window 2020-01-01 onward includes COVID shock + 2022 rate hikes + 2023-24 antitrust activism; small-sample regime stats can be noisy.",
            "VIX regime breakpoints {20,30} are conventional but not optimized; sensitivity to breakpoints not tested in this diagnostic.",
            "No event-study around FTC/DOJ filings (deferred to Phase 2).",
            "No formal GARCH / HAR-RV MLE; descriptive only.",
            "Vol regime test uses |daily log return| not 5-min RV (yfinance daily granularity); legitimate descriptor but coarser than intraday RV.",
        ],
        "next_phase_suggestions": [
            "Phase 2a (if GO): pull individual deal-spread time series from SEC EDGAR DEF14A + cash-merger price data; align deal-window to announcement-to-close.",
            "Phase 2b (if GO): GJR-GARCH on MNA daily returns with VIX exogenous regressor; HAR-RV on intraday MNA tick data (poly via Polygon or Databento).",
            "Phase 2c (event study): FTC second-request / DOJ filing windows -> MNA spread vol pulse.",
            "Phase 2d (regime-switching): Markov 2-state on MNA |ret|, label state-2 as 'antitrust-stress' regime.",
        ],
    }

    out_json = OUT / "k1590_diagnostic_results.json"
    with out_json.open("w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[K1590] wrote {out_json}")
    print(f"[K1590] verdict={verdict}")
    print(f"[K1590] vol_regime p={p_val:.4g} mag_ratio={mag:.3f} pearson(MNA,SPY)={pearson_mna_spy:.3f}")
    return results


if __name__ == "__main__":
    main()
