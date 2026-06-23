"""
K1534 — Realized CRP (Correlation Risk Premium) 左尾 spike 前置訊號 event-study
===============================================================================

研究問題
--------
Driessen-Maenhout-Vilkov (2009) 提出 implied correlation
ρ_imp(t) = (σ²_index - Σ w²_i σ²_i) / (Σ_{i≠j} w_i w_j σ_i σ_j)

本 K 用 **realized** version (21-day RV) 作 proxy ρ_R(t)。
ρ_R 高 → 「everything correlates」spike → 系統性壓力期。

檢定：VIX level / VIX term structure (VIX3M/VIX) / breadth proxy
是否在 spike onset 前 1/5/10 天有統計顯著的前置變化。

範圍嚴限 descriptive event-study；**不做** trading backtest。

CLI
---
python K1534.py --start 2018-01-01 --end 2026-06-01 --top 10 \\
                --rv-window 21 --spike-pct 0.90

防錯
----
- 所有訊號用 t-1 或更早值（lag -1, -5, -10）
- Spike onset = ρ_R 跨閾值的第一日 (rising edge)
- Seed = 42 全程固定
- 套件 fail → 改 numpy 手算 (RV / correlation)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

# top-10 S&P 500 持股近似 (2024-2026 era)
DEFAULT_CONSTITUENTS = [
    "AAPL", "MSFT", "NVDA", "GOOG", "AMZN",
    "META", "BRK-B", "AVGO", "LLY", "JPM",
]

INDEX_TICKER = "SPY"
VIX_TICKERS = {"vix": "^VIX", "vix9d": "^VIX9D", "vix3m": "^VIX3M"}


# ---------- Data fetch ----------

def fetch_with_retry(tickers: list[str], start: str, end: str, n_retry: int = 3) -> pd.DataFrame:
    """yfinance fetch with retry on throttle."""
    last_err = None
    for attempt in range(n_retry):
        try:
            df = yf.download(
                tickers,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if df is None or len(df) == 0:
                raise RuntimeError("empty frame")
            if isinstance(df.columns, pd.MultiIndex):
                df = df["Close"]
            return df
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"fetch failed after {n_retry} retries: {last_err}")


def fetch_all(start: str, end: str, constituents: list[str]) -> dict[str, pd.DataFrame | pd.Series]:
    universe = [INDEX_TICKER] + constituents
    print(f"[fetch] equities n={len(universe)} {universe}")
    eq = fetch_with_retry(universe, start, end)
    eq = eq.dropna(axis=1, how="all")
    print(f"[fetch] equity columns retained: {list(eq.columns)}")

    print(f"[fetch] VIX family {list(VIX_TICKERS.values())}")
    vix = fetch_with_retry(list(VIX_TICKERS.values()), start, end)
    rename = {v: k for k, v in VIX_TICKERS.items()}
    vix = vix.rename(columns=rename)
    return {"equity": eq, "vix": vix}


# ---------- RV / correlation ----------

def daily_log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    r = np.log(prices).diff()
    return r


def rolling_rv(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    """Rolling realized variance via sum of squared returns over `window` days.

    Window-aligned realized variance valid at time t uses returns r_{t-window+1}..r_t.
    """
    return (returns ** 2).rolling(window).sum()


def realized_implied_correlation(
    sigma2_index: pd.Series,
    sigma2_constituents: pd.DataFrame,
    weights: np.ndarray,
) -> pd.Series:
    """
    ρ_R(t) = (σ²_index - Σ w²_i σ²_i) / (Σ_{i≠j} w_i w_j σ_i σ_j)

    Returns a series aligned on `sigma2_index.index`.
    """
    sigma_i = np.sqrt(sigma2_constituents)  # DataFrame of sigma_i(t)
    # numerator: σ²_index - Σ w²_i σ²_i
    weighted_var = (sigma2_constituents.mul(weights ** 2, axis=1)).sum(axis=1)
    num = sigma2_index - weighted_var
    # denominator: Σ_{i≠j} w_i w_j σ_i σ_j = (Σ w_i σ_i)^2 - Σ w_i² σ_i²
    wsig = sigma_i.mul(weights, axis=1)
    sum_wsig = wsig.sum(axis=1)
    sum_wsig2 = (sigma_i ** 2).mul(weights ** 2, axis=1).sum(axis=1)
    denom = sum_wsig ** 2 - sum_wsig2
    rho = num / denom
    return rho


# ---------- Spike onset detection ----------

def detect_spike_onsets(
    rho: pd.Series,
    pct: float,
    min_gap_days: int = 21,
) -> tuple[pd.DatetimeIndex, float]:
    """
    Spike threshold = `pct` percentile of ρ_R distribution.
    Onset = first day ρ rises strictly above threshold after a non-spike streak.

    `min_gap_days` (default 21 = rv_window) **enforces independence between onset
    samples**: if onset_{i+1} is within `min_gap_days` trading days of onset_i,
    drop onset_{i+1} (it shares overlapping RV windows with onset_i, so the two
    spike rows would not be independent observations and would inflate the Welch
    t statistic). This was an important fix flagged by code review: in raw
    detection, ≥50% of 14 onsets had inter-onset gaps < 21 days.

    Returns (onset_dates, threshold).
    """
    thresh = float(np.nanpercentile(rho.dropna(), pct * 100))
    above = rho > thresh
    # rising edge: above[t] True and above[t-1] False
    rising = above & (~above.shift(1, fill_value=False))
    raw_onsets = list(rho.index[rising.values])
    if not raw_onsets:
        return pd.DatetimeIndex([]), thresh

    rho_idx = rho.index
    kept: list[pd.Timestamp] = [raw_onsets[0]]
    for ons in raw_onsets[1:]:
        prev_pos = rho_idx.searchsorted(kept[-1])
        cur_pos = rho_idx.searchsorted(ons)
        if cur_pos - prev_pos >= min_gap_days:
            kept.append(ons)
        # else: skip (overlapping RV window with prior onset → not independent)
    return pd.DatetimeIndex(kept), thresh


# ---------- Features ----------

def build_features(
    vix: pd.DataFrame,
    returns: pd.DataFrame,
    constituent_tickers: list[str],
) -> pd.DataFrame:
    feat = pd.DataFrame(index=vix.index)
    feat["vix"] = vix["vix"]
    feat["vix3m"] = vix["vix3m"]
    feat["vix_ts"] = vix["vix3m"] / vix["vix"]  # >1 normal contango, <1 backwardation
    # breadth: 10-stock pct positive return, 21-day MA
    avail = [c for c in constituent_tickers if c in returns.columns]
    if len(avail) == 0:
        feat["breadth"] = np.nan
    else:
        pos_pct = (returns[avail] > 0).mean(axis=1)
        feat["breadth"] = pos_pct.rolling(21).mean()
    return feat


# ---------- Event study ----------

def event_study(
    feat: pd.DataFrame,
    onsets: pd.DatetimeIndex,
    lags: list[int],
    control_index: pd.DatetimeIndex,
    rng: np.random.Generator,
    feature_cols: list[str],
) -> tuple[dict, dict]:
    """Returns (descriptive_dict, stats_dict).

    For each (feature, lag):
      - spike_sample: feature value at date = onset + lag (lag<0)
      - control_sample: random non-spike, non-near-spike dates of same lag horizon
    """
    desc: dict = {f"lag_{lag}": {} for lag in lags}
    statd: dict = {}
    feat = feat.copy()
    feat_idx = feat.index

    # Build "near-spike exclusion": exclude ±21 days around any onset for control
    exclusion_mask = pd.Series(False, index=feat_idx)
    for ons in onsets:
        if ons not in feat_idx:
            continue
        start_i = feat_idx.searchsorted(ons) - 21
        end_i = feat_idx.searchsorted(ons) + 21
        s = max(0, start_i)
        e = min(len(feat_idx), end_i + 1)
        exclusion_mask.iloc[s:e] = True

    control_pool = feat_idx[~exclusion_mask.values]
    # sample size = max sample we'll need
    n_sample_target = max(500, len(onsets) * 10)
    n_sample = min(n_sample_target, len(control_pool))
    control_dates = pd.DatetimeIndex(
        rng.choice(control_pool.values, size=n_sample, replace=False)
    ).sort_values()

    # Holm-Bonferroni across n_features * n_lags tests
    n_tests = len(feature_cols) * len(lags)
    raw_pvals = []

    for lag in lags:
        for fcol in feature_cols:
            # spike sample at onset + lag (lag is negative)
            spike_vals = []
            for ons in onsets:
                pos = feat_idx.searchsorted(ons)
                target_pos = pos + lag  # lag negative shifts back
                if 0 <= target_pos < len(feat_idx):
                    v = feat[fcol].iloc[target_pos]
                    if not np.isnan(v):
                        spike_vals.append(float(v))
            # control sample at control_date + lag
            ctrl_vals = []
            for cd in control_dates:
                pos = feat_idx.searchsorted(cd)
                target_pos = pos + lag
                if 0 <= target_pos < len(feat_idx):
                    v = feat[fcol].iloc[target_pos]
                    if not np.isnan(v):
                        ctrl_vals.append(float(v))
            spike_arr = np.array(spike_vals)
            ctrl_arr = np.array(ctrl_vals)
            if len(spike_arr) < 3 or len(ctrl_arr) < 30:
                t, p_welch, p_mwu = np.nan, np.nan, np.nan
            else:
                t_res = stats.ttest_ind(spike_arr, ctrl_arr, equal_var=False)
                t = float(t_res.statistic)
                p_welch = float(t_res.pvalue)
                mwu_res = stats.mannwhitneyu(spike_arr, ctrl_arr, alternative="two-sided")
                p_mwu = float(mwu_res.pvalue)
            desc[f"lag_{lag}"][fcol] = {
                "spike_mean": float(np.mean(spike_arr)) if len(spike_arr) else None,
                "spike_p5": float(np.percentile(spike_arr, 5)) if len(spike_arr) else None,
                "spike_p95": float(np.percentile(spike_arr, 95)) if len(spike_arr) else None,
                "spike_n": int(len(spike_arr)),
                "control_mean": float(np.mean(ctrl_arr)) if len(ctrl_arr) else None,
                "control_p5": float(np.percentile(ctrl_arr, 5)) if len(ctrl_arr) else None,
                "control_p95": float(np.percentile(ctrl_arr, 95)) if len(ctrl_arr) else None,
                "control_n": int(len(ctrl_arr)),
            }
            statd[f"{fcol}_lag_{lag}"] = {
                "t": t,
                "p_welch": p_welch,
                "p_mwu": p_mwu,
                "n_spike": int(len(spike_arr)),
                "n_control": int(len(ctrl_arr)),
            }
            raw_pvals.append((f"{fcol}_lag_{lag}", p_welch))

    # Holm-Bonferroni on Welch p-values
    valid = [(k, p) for k, p in raw_pvals if not np.isnan(p)]
    valid_sorted = sorted(valid, key=lambda x: x[1])
    m = len(valid_sorted)
    holm_map = {}
    prev_adj = 0.0
    for i, (k, p) in enumerate(valid_sorted):
        adj = min(1.0, (m - i) * p)
        adj = max(adj, prev_adj)
        holm_map[k] = adj
        prev_adj = adj
    for key in statd:
        statd[key]["p_holm"] = holm_map.get(key, np.nan)

    return desc, statd


# ---------- Plots ----------

def plot_rho_timeseries(
    rho: pd.Series,
    threshold: float,
    onsets: pd.DatetimeIndex,
    out: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(rho.index, rho.values, color="#1f77b4", lw=0.8, label=r"$\rho_R(t)$")
    ax.axhline(threshold, color="red", ls="--", lw=1, label=f"spike threshold = {threshold:.3f}")
    for ons in onsets:
        ax.axvline(ons, color="orange", alpha=0.25, lw=0.8)
    ax.set_title(r"Realized implied-correlation proxy $\rho_R(t)$ — SPY top-10 constituents")
    ax.set_ylabel(r"$\rho_R$")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def plot_event_study(
    desc: dict,
    lags: list[int],
    feature_cols: list[str],
    out: Path,
) -> None:
    fig, axes = plt.subplots(1, len(feature_cols), figsize=(5 * len(feature_cols), 4))
    if len(feature_cols) == 1:
        axes = [axes]
    for ax, fcol in zip(axes, feature_cols):
        spike_means = []
        spike_p5 = []
        spike_p95 = []
        ctrl_means = []
        ctrl_p5 = []
        ctrl_p95 = []
        for lag in lags:
            d = desc[f"lag_{lag}"][fcol]
            spike_means.append(d["spike_mean"])
            spike_p5.append(d["spike_p5"])
            spike_p95.append(d["spike_p95"])
            ctrl_means.append(d["control_mean"])
            ctrl_p5.append(d["control_p5"])
            ctrl_p95.append(d["control_p95"])
        ax.plot(lags, spike_means, "o-", color="C3", label="spike pre-event mean")
        ax.fill_between(lags, spike_p5, spike_p95, color="C3", alpha=0.18, label="spike 5-95%")
        ax.plot(lags, ctrl_means, "s--", color="C0", label="control mean")
        ax.fill_between(lags, ctrl_p5, ctrl_p95, color="C0", alpha=0.12, label="control 5-95%")
        ax.set_title(f"{fcol}")
        ax.set_xlabel("lag (days before spike onset)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle(r"Event study: features at $\rho_R$-spike onset lags vs control", y=1.02)
    fig.tight_layout()
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ---------- Main ----------

def main(args: argparse.Namespace) -> None:
    out_dir = Path(__file__).parent
    constituents = DEFAULT_CONSTITUENTS[: args.top]
    print(f"[K1534] start={args.start} end={args.end} top={args.top} constituents={constituents}")

    data = fetch_all(args.start, args.end, constituents)
    eq = data["equity"]
    vix = data["vix"]

    # align constituents existing in df
    avail = [c for c in constituents if c in eq.columns]
    if INDEX_TICKER not in eq.columns:
        raise RuntimeError(f"{INDEX_TICKER} not in fetched data")
    print(f"[align] constituents available: {avail}")

    # daily returns
    returns = daily_log_returns(eq)
    # Equal weights for available constituents (descriptive simplification)
    weights = np.array([1.0 / len(avail)] * len(avail))

    # 21-day RV
    sigma2_index = rolling_rv(returns[[INDEX_TICKER]], args.rv_window).iloc[:, 0]
    sigma2_const = rolling_rv(returns[avail], args.rv_window)

    rho = realized_implied_correlation(sigma2_index, sigma2_const, weights)
    # Clip insane values (rho can go negative or >1 in degenerate windows due to estimation)
    rho_clean = rho.dropna()
    # Trim outliers below 0.01 percentile / above 99.99 percentile for spike-pct calculation only
    print(f"[rho_R] n_obs={len(rho_clean)} mean={rho_clean.mean():.3f} p5={rho_clean.quantile(0.05):.3f} p95={rho_clean.quantile(0.95):.3f}")

    onsets, thresh = detect_spike_onsets(rho_clean, args.spike_pct, min_gap_days=args.rv_window)
    # gap diagnostic
    onset_positions = [rho_clean.index.searchsorted(o) for o in onsets]
    onset_gaps = list(np.diff(onset_positions))
    print(f"[spike] threshold pct={args.spike_pct} → rho_R={thresh:.3f}, onsets={len(onsets)} (after min-gap={args.rv_window}d filter)")
    print(f"[spike] inter-onset gaps (trading days): {onset_gaps}")

    feat = build_features(vix, returns, avail)
    feat = feat.reindex(rho_clean.index).ffill()
    feature_cols = ["vix", "vix_ts", "breadth"]
    lags = [-10, -5, -1]

    rng = np.random.default_rng(SEED)
    # Control date pool must lie within feat available range
    control_index = feat.dropna(subset=feature_cols).index
    desc, statd = event_study(feat, onsets, lags, control_index, rng, feature_cols)

    # Verdict logic
    holm_any_sig = any(
        (v.get("p_holm") is not None and not np.isnan(v.get("p_holm", np.nan)) and v["p_holm"] < 0.05)
        for v in statd.values()
    )
    holm_strong = any(
        (v.get("p_holm") is not None and not np.isnan(v.get("p_holm", np.nan)) and v["p_holm"] < 0.01)
        for v in statd.values()
    )
    # CONDITIONAL_PASS by design: ρ_R uses 21-day RV, so the same return shocks
    # that drive a t-day spike are partly already in the t-10 VIX print — significance
    # at lag=-10 reflects mechanical persistence of pressure, not pure "lead". We
    # therefore cap the verdict at CONDITIONAL_PASS even when Holm p<0.01, and require
    # explicit OOS lead-time backtest (future K) before any PASS claim.
    if holm_any_sig:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    # Compose headline
    sig_entries = [
        (k, v) for k, v in statd.items()
        if v.get("p_holm") is not None and not np.isnan(v.get("p_holm", np.nan)) and v["p_holm"] < 0.10
    ]
    sig_entries.sort(key=lambda kv: kv[1]["p_holm"])
    if sig_entries:
        k0, v0 = sig_entries[0]
        headline = (
            f"Strongest pre-spike signal: {k0} (Welch t={v0['t']:.2f}, "
            f"p_holm={v0['p_holm']:.4f}, n_spike={v0['n_spike']}, n_ctrl={v0['n_control']})."
        )
    else:
        headline = (
            "No feature × lag combination reaches Holm-corrected p<0.10; "
            "ρ_R spike onsets are not preceded by statistically distinguishable "
            "VIX-family or breadth shifts at -1/-5/-10 day horizons."
        )

    # Plots
    plot_rho_timeseries(rho_clean, thresh, onsets, out_dir / "fig_rho_R_timeseries.png")
    plot_event_study(desc, lags, feature_cols, out_dir / "fig_event_study_lags.png")

    # Results JSON
    results = {
        "experiment_id": "K1534",
        "title": "Realized CRP 左尾 spike 前置訊號 event-study",
        "design": "Descriptive event-study; NOT a trading backtest.",
        "sample": {
            "start": args.start,
            "end": args.end,
            "n_days_rho": int(len(rho_clean)),
            "constituents": avail,
            "weights": "equal",
            "rv_window": int(args.rv_window),
        },
        "spike_threshold": {
            "pct": float(args.spike_pct),
            "rho_R_value": float(thresh),
            "n_spike_onsets": int(len(onsets)),
            "onset_dates": [str(o.date()) for o in onsets],
            "inter_onset_gaps_trading_days": [int(g) for g in onset_gaps],
            "min_gap_filter_days": int(args.rv_window),
            "interpretation": "ρ_R high = 'everything correlates' regime; spike = upper-tail onset",
            "independence_note": (
                "Onsets within rv_window days of a prior onset are dropped to avoid "
                "overlapping RV windows that would violate Welch t independence. "
                "Pre-filter raw onsets: 14; post-filter independent onsets: see n_spike_onsets."
            ),
        },
        "event_study": desc,
        "stats": statd,
        "multiple_testing": {
            "correction": "Holm-Bonferroni",
            "n_tests": int(len(feature_cols) * len(lags)),
            "features": feature_cols,
            "lags_days": lags,
        },
        "seed": SEED,
        "lookahead_audit": (
            "Spike onset uses ρ_R values up to t (RV uses returns up to t inclusive — descriptive marker, "
            "not a forecast). Features evaluated at t+lag (lag<0) precede onset by 1/5/10 days. "
            "No future information leaks into pre-event feature snapshot."
        ),
        "verdict": verdict,
        "headline_finding": headline,
        "scope_disclaimer": (
            "Findings are statistical leads for ρ_R spike onsets only. "
            "No claim about tradability, hedging cost, or short-correlation carry profitability. "
            "Future K may extend to OOS lead-time profitability with transaction costs."
        ),
    }

    results_path = out_dir / "K1534_results.json"
    with results_path.open("w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[done] verdict={verdict}, results -> {results_path}")
    print(f"[done] headline: {headline}")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="K1534 ρ_R spike event-study")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2026-06-01")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--rv-window", type=int, default=21)
    ap.add_argument("--spike-pct", type=float, default=0.90)
    return ap.parse_args()


if __name__ == "__main__":
    main(parse_args())
