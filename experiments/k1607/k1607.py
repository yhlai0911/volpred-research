"""K1607: Mega-cap options-market crowding gauge for the AI-capex bull case.

trending_repost angle (VolPred lens on "Big Tech capex questioned"):
Q1/Q2 2026 earnings pushed combined hyperscaler AI capex guidance toward
$650-700B (Meta $125-145B FY26, Microsoft Q3 capex +84% YoY, Amazon $44.2B/
quarter, Alphabet Q1 capex $35.67B, more than doubling YoY — public press
aggregating primary 10-Q/8-K disclosures; see README references). The
mainstream debate is "will AI capex pay off". This experiment does NOT try to
answer that — it asks a narrower, independently VERIFIABLE question: **is the
options market currently pricing extra downside/tail-risk protection into the
mega-cap names most exposed to this capex story, relative to their own
realized volatility?**

Three independently computable, reproducible metrics per MAG7 name, all built
from the SAME options-chain snapshot (yfinance, single run date):

1. **25-delta risk reversal / skew** = IV(25-delta put) - IV(25-delta call),
   in vol points. Positive & large = market pays up for crash protection
   relative to upside calls (classic equity-index-style "smirk"; single names
   are often flatter or even inverted, so cross-sectional dispersion here is
   itself informative).
2. **ATM IV - trailing 21-day realized vol gap** (vol risk premium proxy):
   how rich is the options market pricing forward risk vs what actually
   happened recently.
3. **Put/Call volume ratio** on the same expiry chain — a simple positioning
   signal, cross-checked against open-interest ratio.

Honest scope: this is a SINGLE-DATE cross-sectional snapshot (not a time
series, not a forecast, not a backtest). No model is fit and no OOS claim is
made — the "evidence package" here is descriptive/cross-sectional, per the
trending_repost skill's minimum bar (>=3 verifiable numbers + 1 table + 1
chart + 1 analytical layer beyond narration). Lookahead is a non-issue: every
number is computed from data available *as of* the single run timestamp; nothing
is used to predict a future value.

Data sources (all yfinance, live pull, run date embedded in results JSON):
- Options chain (calls/puts DataFrames) -> `Ticker.option_chain(expiry)`
- Spot price -> `Ticker.history(period="5d")['Close']`
- Trailing realized vol -> `Ticker.history(period="3mo")['Close']` daily log
  returns, last 21 trading days, annualized by sqrt(252)
- Risk-free proxy -> `^IRX` (13-week T-bill discount yield, /100)

BS delta is computed by us (yfinance does not return delta) using the
yfinance-reported `impliedVolatility` per contract, spot, strike, time-to-
expiry and the ^IRX risk-free proxy — standard Black-Scholes with continuous
dividend yield assumed 0 (a simplification; noted as a limitation, not
material for delta *selection* which is monotonic in strike for a given
smile).

Seed: none required (no stochastic step; every number is a direct closed-form
calculation from live market data. Re-running on a different date/time will
produce different numbers because options prices move — that is not
"unseeded randomness", it's live market data, and is disclosed in the results
JSON `run_at` field for reproducibility-of-method (not reproducibility-of-
value)).

Author: K1607 experiment (trending_repost), 2026-07-03
"""
from __future__ import annotations

import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

warnings.filterwarnings("ignore", category=FutureWarning)

HERE = Path(__file__).resolve().parent
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)

MAG7 = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]

# Public-press aggregated FY2026 capex context (NOT computed by this script;
# cited from named secondary sources aggregating primary 10-Q/8-K disclosures,
# per trending_repost rule "numbers must be independently verifiable" — the
# PRIMARY, script-computed numbers are the options-derived panel below; this
# dict is narrative scene-setting only, disclosed as such in README/article).
CAPEX_CONTEXT_NOTE = (
    "Q1/Q2 2026 earnings season: combined hyperscaler 2026 capex guidance "
    "tracking ~$650-700B (Yahoo Finance / heygotrade aggregation of company "
    "disclosures). Meta raised FY2026 capex guidance to $125-145B; Microsoft "
    "Q3 FY capex +84% YoY (~$30.9B in-quarter); Amazon ~$44.2B quarterly "
    "capex; Alphabet Q1 capex $35.67B (>2x YoY)."
)

TARGET_DTE = 35
DTE_RANGE = (18, 65)
DELTA_TARGET = 0.25
MIN_IV = 0.01
MAX_IV = 5.0
RV_WINDOW = 21
TRADING_DAYS = 252


def get_risk_free_rate() -> float:
    """13-week T-bill discount yield (^IRX) as a risk-free proxy for BS delta."""
    try:
        irx = yf.Ticker("^IRX").history(period="5d")["Close"]
        irx = irx.dropna()
        if len(irx) == 0:
            raise ValueError("empty ^IRX series")
        return float(irx.iloc[-1]) / 100.0
    except Exception:
        # Documented fallback if ^IRX is unavailable at run time.
        return 0.04


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, is_call: bool) -> float:
    """Black-Scholes delta, continuous dividend yield = 0 (simplification)."""
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1) if is_call else norm.cdf(d1) - 1.0


DELTA_ERROR_WARN = 0.07  # Codex review: flag (not drop) contracts whose realized
# delta misses the 25-delta target by more than this — otherwise a sparse/stale
# chain can silently pick a contract that is not really "25-delta".


def pick_target_delta_contract(df: pd.DataFrame, spot: float, target_delta: float, side: str) -> dict:
    """Pick the contract closest to `target_delta`, preferring the OTM side and
    liquid quotes (Codex CRITICAL fixes: OTM constraint + liquidity filter +
    reported delta_error so a bad pick is visible, not silently returned)."""
    if side == "call":
        otm = df[df["strike"] >= spot]
    else:
        otm = df[df["strike"] <= spot]
    otm_constrained = len(otm) > 0
    pool = otm if otm_constrained else df

    liquid = pool
    if "bid" in pool.columns and "ask" in pool.columns:
        liquid_pool = pool[(pool["bid"] > 0) | (pool["ask"] > 0)]
        if len(liquid_pool) > 0:
            liquid = liquid_pool

    idx = (liquid["delta"] - target_delta).abs().idxmin()
    row = liquid.loc[idx]
    delta_error = float(abs(row["delta"] - target_delta))
    return {
        "row": row,
        "delta_error": round(delta_error, 4),
        "otm_constrained": otm_constrained,
        "quality_flag": delta_error > DELTA_ERROR_WARN,
        "bid": float(row.get("bid", np.nan)),
        "ask": float(row.get("ask", np.nan)),
        "last_trade_date": str(row.get("lastTradeDate", "")),
    }


def pick_expiry(options: list[str]) -> tuple[str, int] | None:
    """Pick the expiry closest to TARGET_DTE within DTE_RANGE (fallback: closest overall)."""
    today = datetime.now(timezone.utc).date()
    candidates = []
    for exp_str in options:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days
        candidates.append((exp_str, dte))
    if not candidates:
        return None
    in_range = [c for c in candidates if DTE_RANGE[0] <= c[1] <= DTE_RANGE[1]]
    pool = in_range if in_range else candidates
    best = min(pool, key=lambda c: abs(c[1] - TARGET_DTE))
    return best


def realized_vol_21d(ticker: str) -> float | None:
    hist = yf.Ticker(ticker).history(period="3mo")["Close"].dropna()
    if len(hist) < RV_WINDOW + 1:
        return None
    log_ret = np.log(hist / hist.shift(1)).dropna()
    last21 = log_ret.iloc[-RV_WINDOW:]
    return float(last21.std(ddof=1) * np.sqrt(TRADING_DAYS))


def collect_ticker(ticker: str, r_free: float) -> dict:
    """Full options-derived panel for one ticker. Raises on unrecoverable failure."""
    tk = yf.Ticker(ticker)

    spot_hist = tk.history(period="5d")["Close"].dropna()
    if len(spot_hist) == 0:
        raise ValueError("no spot price history")
    spot = float(spot_hist.iloc[-1])

    options = tk.options
    if not options:
        raise ValueError("no options expirations listed")
    expiry, dte = pick_expiry(list(options))
    if dte <= 0:
        raise ValueError(f"non-positive DTE for expiry {expiry}")
    T = dte / 365.0

    chain = tk.option_chain(expiry)
    calls, puts = chain.calls.copy(), chain.puts.copy()

    for df in (calls, puts):
        df.dropna(subset=["impliedVolatility", "strike"], inplace=True)
        df.query("@MIN_IV <= impliedVolatility <= @MAX_IV", inplace=True)

    if len(calls) == 0 or len(puts) == 0:
        raise ValueError(f"empty calls/puts after IV filter for expiry {expiry}")

    calls["delta"] = calls.apply(
        lambda row: bs_delta(spot, row["strike"], T, r_free, row["impliedVolatility"], True),
        axis=1,
    )
    puts["delta"] = puts.apply(
        lambda row: bs_delta(spot, row["strike"], T, r_free, row["impliedVolatility"], False),
        axis=1,
    )
    calls.dropna(subset=["delta"], inplace=True)
    puts.dropna(subset=["delta"], inplace=True)
    if len(calls) == 0 or len(puts) == 0:
        raise ValueError(f"empty calls/puts after delta compute for expiry {expiry}")

    call25_pick = pick_target_delta_contract(calls, spot, DELTA_TARGET, "call")
    put25_pick = pick_target_delta_contract(puts, spot, -DELTA_TARGET, "put")
    call25 = call25_pick["row"]
    put25 = put25_pick["row"]

    atm_calls_idx = (calls["strike"] - spot).abs().idxmin()
    atm_puts_idx = (puts["strike"] - spot).abs().idxmin()
    atm_iv = float(
        np.mean([calls.loc[atm_calls_idx, "impliedVolatility"], puts.loc[atm_puts_idx, "impliedVolatility"]])
    )

    rv21 = realized_vol_21d(ticker)
    if rv21 is None:
        raise ValueError("insufficient history for RV21")

    call_vol = float(calls["volume"].fillna(0).sum())
    put_vol = float(puts["volume"].fillna(0).sum())
    call_oi = float(calls["openInterest"].fillna(0).sum())
    put_oi = float(puts["openInterest"].fillna(0).sum())

    skew_25d_vol_pts = (float(put25["impliedVolatility"]) - float(call25["impliedVolatility"])) * 100.0
    iv_rv_gap_vol_pts = (atm_iv - rv21) * 100.0

    return {
        "ticker": ticker,
        "spot": round(spot, 2),
        "expiry": expiry,
        "dte": dte,
        "r_free_used": round(r_free, 4),
        "n_calls_chain": int(len(calls)),
        "n_puts_chain": int(len(puts)),
        "call25_strike": float(call25["strike"]),
        "call25_iv": round(float(call25["impliedVolatility"]) * 100, 3),
        "call25_delta": round(float(call25["delta"]), 4),
        "call25_delta_error": call25_pick["delta_error"],
        "call25_otm_constrained": call25_pick["otm_constrained"],
        "call25_quality_flag": call25_pick["quality_flag"],
        "call25_bid": call25_pick["bid"],
        "call25_ask": call25_pick["ask"],
        "call25_last_trade_date": call25_pick["last_trade_date"],
        "put25_strike": float(put25["strike"]),
        "put25_iv": round(float(put25["impliedVolatility"]) * 100, 3),
        "put25_delta": round(float(put25["delta"]), 4),
        "put25_delta_error": put25_pick["delta_error"],
        "put25_otm_constrained": put25_pick["otm_constrained"],
        "put25_quality_flag": put25_pick["quality_flag"],
        "put25_bid": put25_pick["bid"],
        "put25_ask": put25_pick["ask"],
        "put25_last_trade_date": put25_pick["last_trade_date"],
        "data_quality_flag": bool(call25_pick["quality_flag"] or put25_pick["quality_flag"]),
        "skew_25d_vol_pts": round(skew_25d_vol_pts, 3),
        "atm_iv_pct": round(atm_iv * 100, 3),
        "rv21_pct": round(rv21 * 100, 3),
        "iv_rv_gap_vol_pts": round(iv_rv_gap_vol_pts, 3),
        "call_volume": call_vol,
        "put_volume": put_vol,
        "pc_volume_ratio": round(put_vol / call_vol, 3) if call_vol > 0 else None,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "pc_oi_ratio": round(put_oi / call_oi, 3) if call_oi > 0 else None,
    }


def zscore(arr: np.ndarray) -> np.ndarray:
    mu, sd = np.mean(arr), np.std(arr, ddof=1)
    if sd == 0:
        return np.zeros_like(arr)
    return (arr - mu) / sd


def build_cross_section(records: list[dict]) -> dict:
    # Codex MINOR fix: "composite_crowding_z" was a mean-of-z-scores, not itself
    # a formal z-score -> renamed "composite_crowding_score". Also explicitly
    # guard the all-missing pc_volume_ratio case (would otherwise silently
    # produce NaN -> non-strict JSON) instead of relying on .median() alone.
    df = pd.DataFrame(records)
    skew = df["skew_25d_vol_pts"].to_numpy()
    gap = df["iv_rv_gap_vol_pts"].to_numpy()

    pc_raw = df["pc_volume_ratio"]
    if pc_raw.notna().sum() == 0:
        pc = np.zeros(len(df))  # no positioning signal available for any ticker
        pc_ratio_data_quality = "all_missing_defaulted_zero"
    else:
        pc = pc_raw.fillna(pc_raw.median()).to_numpy()
        pc_ratio_data_quality = "ok" if pc_raw.notna().all() else "partial_missing_median_filled"

    z_skew = zscore(skew)
    z_gap = zscore(gap)
    z_pc = zscore(pc)
    composite = (z_skew + z_gap + z_pc) / 3.0
    df["composite_crowding_score"] = composite

    corr_skew_pc = float(np.corrcoef(skew, pc)[0, 1]) if len(skew) > 2 and np.std(pc) > 0 else None
    corr_skew_gap = float(np.corrcoef(skew, gap)[0, 1]) if len(skew) > 2 else None

    ranked = df.sort_values("composite_crowding_score", ascending=False)[
        ["ticker", "skew_25d_vol_pts", "iv_rv_gap_vol_pts", "pc_volume_ratio", "composite_crowding_score"]
    ].to_dict(orient="records")

    return {
        "n_tickers": int(len(df)),
        "inference_note": (
            "DESCRIPTIVE ONLY, n={} — correlations and composite ranking are "
            "cross-sectional descriptive statistics, not hypothesis tests; no "
            "significance or causal claim is made or supported at this sample size."
        ).format(len(df)),
        "pc_ratio_data_quality": pc_ratio_data_quality,
        "n_data_quality_flagged_tickers": int(df.get("data_quality_flag", pd.Series(dtype=bool)).sum())
        if "data_quality_flag" in df.columns
        else 0,
        "mean_skew_25d_vol_pts": round(float(np.mean(skew)), 3),
        "std_skew_25d_vol_pts": round(float(np.std(skew, ddof=1)), 3),
        "mean_iv_rv_gap_vol_pts": round(float(np.mean(gap)), 3),
        "corr_skew_vs_pc_ratio": round(corr_skew_pc, 3) if corr_skew_pc is not None else None,
        "corr_skew_vs_iv_rv_gap": round(corr_skew_gap, 3) if corr_skew_gap is not None else None,
        "composite_crowding_ranked": ranked,
    }, df


def make_figures(df: pd.DataFrame, run_date: str) -> list[str]:
    paths = []

    df_sorted = df.sort_values("skew_25d_vol_pts", ascending=False)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    axes[0].bar(df_sorted["ticker"], df_sorted["skew_25d_vol_pts"], color="#4C6EF5")
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_title("25-Delta Put-Call IV Skew (vol pts)\n" + run_date)
    axes[0].set_ylabel("IV(25Δ put) − IV(25Δ call), pts")
    axes[0].tick_params(axis="x", rotation=0)

    df_sorted2 = df.sort_values("iv_rv_gap_vol_pts", ascending=False)
    colors = ["#F76707" if v > 0 else "#2F9E44" for v in df_sorted2["iv_rv_gap_vol_pts"]]
    axes[1].bar(df_sorted2["ticker"], df_sorted2["iv_rv_gap_vol_pts"], color=colors)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("ATM IV − 21D Realized Vol Gap (vol pts)\n" + run_date)
    axes[1].set_ylabel("vol risk premium, pts")

    fig.tight_layout()
    p1 = FIG_DIR / "k1607_skew_and_gap.png"
    fig.savefig(p1, dpi=150)
    plt.close(fig)
    paths.append(str(p1))

    fig2, ax2 = plt.subplots(figsize=(6.5, 5.5))
    ax2.scatter(df["pc_volume_ratio"], df["skew_25d_vol_pts"], s=90, color="#5F3DC4")
    for _, row in df.iterrows():
        ax2.annotate(row["ticker"], (row["pc_volume_ratio"], row["skew_25d_vol_pts"]),
                     xytext=(5, 5), textcoords="offset points", fontsize=9)
    ax2.set_xlabel("Put/Call volume ratio (same-expiry chain)")
    ax2.set_ylabel("25-delta IV skew (vol pts)")
    ax2.set_title("Skew vs. Put/Call Volume Ratio\n" + run_date)
    fig2.tight_layout()
    p2 = FIG_DIR / "k1607_skew_vs_pcratio.png"
    fig2.savefig(p2, dpi=150)
    plt.close(fig2)
    paths.append(str(p2))

    return paths


def main():
    run_at = datetime.now(timezone.utc).isoformat()
    run_date = run_at[:10]
    r_free = get_risk_free_rate()

    records, failures = [], []
    for t in MAG7:
        for attempt in range(2):
            try:
                rec = collect_ticker(t, r_free)
                records.append(rec)
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(2)
                    continue
                failures.append({"ticker": t, "reason": str(e)})

    if len(records) < 4:
        raise RuntimeError(
            f"Only {len(records)}/{len(MAG7)} tickers succeeded (need >=4). Failures: {failures}"
        )

    cross_section, df = build_cross_section(records)
    fig_paths = make_figures(df, run_date)

    results = {
        "experiment_id": "k1607",
        "title": "Mega-cap options-market crowding gauge for the AI-capex bull case",
        "task_type": "trending_repost",
        "framing": (
            "Single-date cross-sectional snapshot of MAG7 options-derived skew / "
            "vol-risk-premium / positioning metrics. Not a forecast, not a backtest, "
            "no OOS claim. Descriptive + cross-sectional analytical layer only."
        ),
        "run_at": run_at,
        "run_date": run_date,
        "risk_free_proxy": "^IRX (13-week T-bill discount yield)",
        "r_free_used": round(r_free, 4),
        "data_source": (
            "yfinance option_chain (per-ticker, single nearest-to-35-DTE expiry), "
            "yfinance history (spot + 21d realized vol), yfinance ^IRX"
        ),
        "tickers_universe": MAG7,
        "tickers_succeeded": [r["ticker"] for r in records],
        "tickers_failed": failures,
        "n_succeeded": len(records),
        "capex_context_note_NOT_computed_by_script": CAPEX_CONTEXT_NOTE,
        "methodology": {
            "expiry_selection": f"closest to {TARGET_DTE} DTE within {DTE_RANGE} day range",
            "delta_model": "Black-Scholes, q=0 dividend yield assumption, r=^IRX proxy",
            "skew_definition": (
                "put-call IV skew = IV(25-delta put) - IV(25-delta call), in vol points "
                "(IV*100). NOTE: this is the 'put-call IV skew' convention, not the "
                "'risk reversal' convention some desks quote as call-IV minus put-IV — "
                "sign is put-minus-call throughout this experiment/article."
            ),
            "delta_selection_quality": (
                "25-delta contract restricted to the OTM side (call: strike>=spot; "
                "put: strike<=spot) and to quotes with bid>0 or ask>0 when available; "
                "delta_error = |realized_delta - 0.25| reported per contract; "
                f"quality_flag=True when delta_error > {DELTA_ERROR_WARN} (Codex review fix)"
            ),
            "atm_iv": "mean of nearest-to-spot-strike call IV and put IV on same expiry chain",
            "rv21": "trailing 21 trading-day daily log-return stdev, annualized by sqrt(252)",
            "iv_rv_gap": "ATM IV - RV21, in vol points",
            "pc_ratio": "put volume / call volume on the same expiry chain (open interest ratio also reported)",
            "lookahead_note": (
                "No forecasting model is fit; this is a same-timestamp cross-sectional "
                "descriptive comparison. RV21 uses only trailing (already-realized) daily "
                "closes strictly at or before the run timestamp. No train/test split exists."
            ),
        },
        "per_ticker": records,
        "cross_section": cross_section,
        "figures": fig_paths,
    }

    out_path = HERE / "k1607_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Wrote {out_path}")
    print(f"n_succeeded={len(records)} failures={failures}")
    print(json.dumps(cross_section, indent=2))


if __name__ == "__main__":
    main()
