#!/usr/bin/env python3
"""K1727 — Volatility targeting (VT): efficacy on risk assets vs non-risk assets.

Re-validates the JPM ("The Impact of Volatility Targeting", Harvey et al. 2018)
/ Man Group (2025) claim that volatility targeting improves *risk-adjusted*
returns for risky assets (equities, credit) but is near-useless for bonds, FX,
and commodities.

Each asset is analysed INDEPENDENTLY over its own longest available history.

LOOKAHEAD POLICY (single most important guard, see build_vol_target):
    The vol-scaling signal is `signal.shift(1)`.  The realized-vol estimate at
    day t uses returns THROUGH day t; the position actually held on day t is the
    scale computed from data through t-1.  So the return earned on day t,
    `position_{t}  * excess_return_{t}` with `position_{t} = scale_{t-1}`, never
    touches information from day t or later.

Fairness notes:
    * Sharpe is scale-invariant, so "Sharpe gain (VT - fixed)" is a legitimate
      comparison even though VT and fixed run at different exposure.  This is the
      PRIMARY metric and the one the hypothesis is about.
    * Raw max drawdown is NOT scale-invariant.  VT and fixed carry different
      realized volatility, so raw MDD is delegated to the canonical
      `volpred.stats.drawdown.compare_max_drawdown`, which also emits the
      exposure-matched gap.  We never report raw-MDD improvement as evidence of
      timing skill.
    * Left-tail metrics are standardized by each series' own sigma so they are
      scale-invariant and comparable across fixed vs VT.

Usage:
    uv run python experiments/K1727/K1727.py
Outputs:
    experiments/K1727/K1727_results.json
    experiments/K1727/data/prices.csv
    experiments/K1727/K1727_sharpe_gain.png   (best-effort; skipped if no mpl)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.drawdown import compare_max_drawdown

# ----------------------------------------------------------------------------
# Config (all fixed / documented; seed pinned for the bootstrap)
# ----------------------------------------------------------------------------
SEED = 42
TRADING_DAYS = 252
VOL_WINDOW = 20            # trailing days for realized vol (primary spec)
VOL_WINDOW_ROBUST = 60    # robustness spec (report only)
TARGET_VOL = 0.10         # 10% annualized target
LEV_CAP = 2.0             # documented leverage bound
DOWNLOAD_START = "2003-01-01"

BOOT_REPS = 1000
BOOT_BLOCK = 21           # ~1 trading month; respects daily autocorrelation

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "K1727_results.json"
FIG_PATH = HERE / "K1727_sharpe_gain.png"

# One representative liquid ETF per bucket.  group = hypothesis partition.
ASSETS: dict[str, dict[str, str]] = {
    "SPY": {"bucket": "equities", "group": "risky"},
    "QQQ": {"bucket": "equities_tech", "group": "risky"},
    "HYG": {"bucket": "credit_high_yield", "group": "risky"},
    "LQD": {"bucket": "credit_investment_grade", "group": "risky"},
    "TLT": {"bucket": "rates_long_ust", "group": "non_risky"},
    "UUP": {"bucket": "fx_usd_index", "group": "non_risky"},
    "DBC": {"bucket": "commodities_broad", "group": "non_risky"},
    "GLD": {"bucket": "commodities_gold", "group": "non_risky"},
}
RF_TICKER = "^IRX"        # 13-week T-bill discount rate (annualized %); rf proxy


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def download_prices(tickers: list[str], start: str) -> pd.DataFrame:
    """Adjusted close for each ticker, columns = tickers. Cached to data/prices.csv."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "prices.csv"
    raw = yf.download(
        tickers, start=start, auto_adjust=True, progress=False, group_by="column"
    )
    # yfinance returns a column MultiIndex (field, ticker) for >1 ticker.
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:  # single ticker fallback
        close = raw[["Close"]].copy()
        close.columns = tickers
    close = close[[t for t in tickers if t in close.columns]]
    close.index = pd.to_datetime(close.index)
    close = close.sort_index()
    close.to_csv(cache)
    return close


def daily_risk_free(index: pd.DatetimeIndex, start: str) -> tuple[pd.Series, str]:
    """Daily simple risk-free rate from ^IRX; falls back to 0.0 (documented)."""
    try:
        irx = yf.download(RF_TICKER, start=start, progress=False, auto_adjust=False)
        col = irx["Close"]
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        col.index = pd.to_datetime(col.index)
        # ^IRX close is an annualized discount rate in percent (e.g. 5.20 -> 5.2%).
        rf = (col / 100.0 / TRADING_DAYS).reindex(index).ffill().fillna(0.0)
        rf.name = "rf_daily"
        return rf, "^IRX 13-week T-bill (annualized %/100/252, ffill)"
    except Exception as exc:  # pragma: no cover - network fragility
        rf = pd.Series(0.0, index=index, name="rf_daily")
        return rf, f"rf=0.0 fallback (^IRX download failed: {exc!r})"


# ----------------------------------------------------------------------------
# Portfolio construction
# ----------------------------------------------------------------------------
def build_vol_target(
    returns: pd.Series,
    rf_daily: pd.Series,
    vol_window: int,
    target_vol: float,
    lev_cap: float,
) -> pd.DataFrame:
    """Return an aligned frame of fixed-notional and vol-targeted EXCESS returns.

    LOOKAHEAD GUARD lives here: `position = raw_scale.shift(1)`.
    """
    ret = returns.astype(float)
    excess = ret - rf_daily.reindex(ret.index).fillna(0.0)

    # realized-vol estimate uses returns THROUGH day t (inclusive)
    realized_vol = ret.rolling(vol_window).std(ddof=1) * np.sqrt(TRADING_DAYS)
    raw_scale = (target_vol / realized_vol).clip(lower=0.0, upper=lev_cap)

    # THE lookahead guard: position held on day t is built from data through t-1
    position = raw_scale.shift(1)

    frame = pd.DataFrame(
        {
            "ret": ret,
            "excess": excess,
            "realized_vol": realized_vol,
            "position": position,
            "fixed_excess": excess,               # constant unit exposure
            "vt_excess": position * excess,       # vol-targeted exposure
        }
    )
    return frame.dropna(subset=["vt_excess", "fixed_excess"])


# ----------------------------------------------------------------------------
# Metrics (all scale-invariant except raw MDD, which is delegated)
# ----------------------------------------------------------------------------
def sharpe(excess: np.ndarray) -> float:
    x = np.asarray(excess, dtype=float)
    x = x[np.isfinite(x)]
    sd = np.std(x, ddof=1)
    if x.size < 2 or sd == 0:
        return float("nan")
    return float(np.mean(x) / sd * np.sqrt(TRADING_DAYS))


def left_tail_freq_3sigma(series: np.ndarray) -> float:
    """Fraction of days with standardized (own mean/std) return < -3. Scale-invariant."""
    x = np.asarray(series, dtype=float)
    x = x[np.isfinite(x)]
    sd = np.std(x, ddof=1)
    if x.size < 2 or sd == 0:
        return float("nan")
    z = (x - np.mean(x)) / sd
    return float(np.mean(z < -3.0))


def es_1pct_in_sigma(series: np.ndarray) -> float:
    """Mean of the worst 1% of days, expressed in units of the series' own sigma.

    Negative; more negative = heavier left tail. Scale-invariant.
    """
    x = np.asarray(series, dtype=float)
    x = x[np.isfinite(x)]
    sd = np.std(x, ddof=1)
    if x.size < 100 or sd == 0:
        return float("nan")
    q = np.quantile(x, 0.01)
    tail = x[x <= q]
    if tail.size == 0:
        return float("nan")
    return float(np.mean(tail) / sd)


def moving_block_bootstrap_sharpe_gain(
    vt: np.ndarray, fixed: np.ndarray, reps: int, block: int, seed: int
) -> dict:
    """Paired moving-block bootstrap CI on Sharpe(VT) - Sharpe(fixed)."""
    vt = np.asarray(vt, dtype=float)
    fixed = np.asarray(fixed, dtype=float)
    n = vt.size
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    max_start = n - block
    gains = np.empty(reps, dtype=float)
    for r in range(reps):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n]
        gains[r] = sharpe(vt[idx]) - sharpe(fixed[idx])
    gains = gains[np.isfinite(gains)]
    return {
        "reps": int(gains.size),
        "mean": float(np.mean(gains)),
        "ci95": [float(np.quantile(gains, 0.025)), float(np.quantile(gains, 0.975))],
        "p_gain_gt_0": float(np.mean(gains > 0)),
    }


def vol_return_corr(frame: pd.DataFrame) -> float:
    """corr(trailing vol at t-1, return at t). Negative => high vol precedes bad
    returns => the mechanism VT exploits. This is the JPM explanation of *why* VT
    helps risky assets and not others."""
    lagged_vol = frame["realized_vol"].shift(1)
    sub = pd.concat([lagged_vol, frame["ret"]], axis=1).dropna()
    if len(sub) < 3:
        return float("nan")
    return float(np.corrcoef(sub.iloc[:, 0], sub.iloc[:, 1])[0, 1])


# ----------------------------------------------------------------------------
# Per-asset evaluation
# ----------------------------------------------------------------------------
def evaluate_asset(
    ticker: str, prices: pd.Series, rf_daily: pd.Series, vol_window: int
) -> dict:
    returns = prices.dropna().pct_change(fill_method=None).dropna()
    frame = build_vol_target(returns, rf_daily, vol_window, TARGET_VOL, LEV_CAP)

    vt = frame["vt_excess"].to_numpy()
    fixed = frame["fixed_excess"].to_numpy()

    sh_fixed = sharpe(fixed)
    sh_vt = sharpe(vt)
    gain = sh_vt - sh_fixed

    dd = compare_max_drawdown(vt, fixed)  # canonical; emits exposure-matched gap
    boot = moving_block_bootstrap_sharpe_gain(vt, fixed, BOOT_REPS, BOOT_BLOCK, SEED)

    return {
        "ticker": ticker,
        "bucket": ASSETS[ticker]["bucket"],
        "group": ASSETS[ticker]["group"],
        "sample_start": str(frame.index[0].date()),
        "sample_end": str(frame.index[-1].date()),
        "n_obs": int(len(frame)),
        "sharpe_fixed": sh_fixed,
        "sharpe_vt": sh_vt,
        "sharpe_gain": gain,
        "sharpe_gain_bootstrap": boot,
        "realized_vol_fixed": dd.benchmark_vol,
        "realized_vol_vt": dd.strategy_vol,
        "mean_position": float(np.nanmean(frame["position"].to_numpy())),
        "left_tail": {
            "freq_below_neg3sigma_fixed": left_tail_freq_3sigma(fixed),
            "freq_below_neg3sigma_vt": left_tail_freq_3sigma(vt),
            "es_1pct_in_sigma_fixed": es_1pct_in_sigma(fixed),
            "es_1pct_in_sigma_vt": es_1pct_in_sigma(vt),
        },
        "max_drawdown": {
            "raw_fixed": dd.benchmark_mdd,
            "raw_vt": dd.strategy_mdd,
            "vol_ratio_vt_over_fixed": dd.vol_ratio,
            "exposure_mismatch": dd.exposure_mismatch,
            "exposure_matched_gap": dd.exposure_matched_gap,
            "matched_lambda": dd.matched_lambda,
            "note": "raw MDD not comparable alone across different exposure; "
            "see exposure_matched_gap (>0 = shallower than same-risk constant-leverage). "
            "Positive gap is necessary-not-sufficient for timing skill (repo rule).",
            "warnings": dd.warnings,
        },
        "vol_return_corr_lag1": vol_return_corr(frame),
    }


def group_contrast(per_asset: list[dict], key: str = "sharpe_gain") -> dict:
    risky = [a[key] for a in per_asset if a["group"] == "risky" and np.isfinite(a[key])]
    non = [a[key] for a in per_asset if a["group"] == "non_risky" and np.isfinite(a[key])]
    return {
        "risky_tickers": [a["ticker"] for a in per_asset if a["group"] == "risky"],
        "non_risky_tickers": [a["ticker"] for a in per_asset if a["group"] == "non_risky"],
        "risky_mean": float(np.mean(risky)) if risky else float("nan"),
        "non_risky_mean": float(np.mean(non)) if non else float("nan"),
        "risky_values": risky,
        "non_risky_values": non,
        "difference_risky_minus_non_risky": (
            float(np.mean(risky) - np.mean(non)) if risky and non else float("nan")
        ),
        "note": "Descriptive contrast only (n=4 per group). No asset-day pooling "
        "(K1355 rule): each value is one asset's scalar, per-asset time-series "
        "inference is in sharpe_gain_bootstrap.",
    }


def maybe_plot(per_asset: list[dict]) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    order = sorted(per_asset, key=lambda a: (a["group"] != "risky", -a["sharpe_gain"]))
    labels = [a["ticker"] for a in order]
    gains = [a["sharpe_gain"] for a in order]
    colors = ["#1f77b4" if a["group"] == "risky" else "#ff7f0e" for a in order]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(labels, gains, color=colors)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Sharpe gain (VT - fixed)")
    ax.set_title("K1727: VT Sharpe gain by asset  (blue=risky, orange=non-risky)")
    for i, a in enumerate(order):
        lo, hi = a["sharpe_gain_bootstrap"]["ci95"]
        ax.plot([i, i], [lo, hi], color="black", lw=1.2)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=130)
    plt.close(fig)
    return True


def main() -> None:
    np.random.seed(SEED)
    tickers = list(ASSETS.keys())
    prices = download_prices(tickers, DOWNLOAD_START)
    rf_daily, rf_desc = daily_risk_free(prices.index, DOWNLOAD_START)

    per_asset = [
        evaluate_asset(t, prices[t], rf_daily, VOL_WINDOW)
        for t in tickers
        if t in prices.columns
    ]
    # robustness: same pipeline at a 60-day vol window (gain only)
    robust = {}
    for t in tickers:
        if t not in prices.columns:
            continue
        fr = build_vol_target(
            prices[t].dropna().pct_change(fill_method=None).dropna(),
            rf_daily,
            VOL_WINDOW_ROBUST,
            TARGET_VOL,
            LEV_CAP,
        )
        robust[t] = sharpe(fr["vt_excess"].to_numpy()) - sharpe(fr["fixed_excess"].to_numpy())

    figure_written = maybe_plot(per_asset)

    results = {
        "experiment_id": "K1727",
        "title": "Volatility targeting efficacy: risk assets vs non-risk assets "
        "(cross-asset re-validation)",
        "hypothesis": "VT improves risk-adjusted returns for risky assets "
        "(equities, credit) but is near-useless for bonds, FX, commodities.",
        "source": "JPM 'The Impact of Volatility Targeting' (Harvey et al. 2018) + "
        "Man Group 2025",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance auto-adjusted close",
            "download_start": DOWNLOAD_START,
            "download_end": str(prices.index[-1].date()),
            "risk_free": rf_desc,
            "cached_prices": "experiments/K1727/data/prices.csv",
            "note": "each asset uses its own longest available history",
        },
        "method": {
            "realized_vol": f"trailing {VOL_WINDOW}-day std of daily simple returns, "
            f"annualized x sqrt({TRADING_DAYS})",
            "vol_window_days": VOL_WINDOW,
            "vol_window_robustness_days": VOL_WINDOW_ROBUST,
            "target_ann_vol": TARGET_VOL,
            "leverage_cap": LEV_CAP,
            "lookahead_policy": "position = (target_vol / realized_vol).clip(0, cap)"
            ".shift(1); position on day t uses info through t-1 only.",
            "portfolios": {
                "fixed_notional": "constant unit exposure to the asset excess return",
                "vol_targeted": "position(shifted) * excess return",
            },
            "sharpe": "mean(excess)/std(excess, ddof=1) * sqrt(252), scale-invariant",
            "mdd": "volpred.stats.drawdown.compare_max_drawdown (raw + exposure-matched gap)",
            "left_tail": "standardized by own sigma (scale-invariant)",
            "bootstrap": {
                "type": "paired moving-block bootstrap on Sharpe gain",
                "reps": BOOT_REPS,
                "block_length": BOOT_BLOCK,
                "seed": SEED,
            },
        },
        "per_asset": per_asset,
        "group_contrast_sharpe_gain": group_contrast(per_asset, "sharpe_gain"),
        "robustness_sharpe_gain_vol60": robust,
        "figure": "experiments/K1727/K1727_sharpe_gain.png" if figure_written else None,
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    gc = results["group_contrast_sharpe_gain"]
    print(f"Wrote {RESULTS_PATH}")
    print(
        f"Risky mean Sharpe gain   = {gc['risky_mean']:+.4f} "
        f"({', '.join(gc['risky_tickers'])})"
    )
    print(
        f"Non-risky mean Sharpe gain = {gc['non_risky_mean']:+.4f} "
        f"({', '.join(gc['non_risky_tickers'])})"
    )
    print(f"Difference (risky - non_risky) = {gc['difference_risky_minus_non_risky']:+.4f}")
    for a in per_asset:
        b = a["sharpe_gain_bootstrap"]
        print(
            f"  {a['ticker']:4s} [{a['group']:9s}] gain={a['sharpe_gain']:+.3f} "
            f"CI=[{b['ci95'][0]:+.3f},{b['ci95'][1]:+.3f}] "
            f"volcorr={a['vol_return_corr_lag1']:+.2f} n={a['n_obs']}"
        )


if __name__ == "__main__":
    main()
