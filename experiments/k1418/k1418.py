#!/usr/bin/env python3
"""
K1418: Paper 8 (volatility-absorption) cross-asset NSI absorption regression
rerun under the 2026-04-19 pinned snapshot.

Motivation:
  main_v3.tex Table cross_asset_detail (lines 800-805) still reports
  paper-drafting-time (2025 yfinance pull) values:
    SPY:     beta = -0.00028  (t=-3.42, N=893)
    GLD:     beta = -0.00043  (t=-4.17, N=893)
    TLT:     beta = -0.00044  (t=-3.89, N=893)
    0050.TW: beta = +0.00019  (t=+1.62, N=612)
  while the main-text NSI regression footnote (line 67), the threshold and
  sub-period robustness tables (sec. 8) are already on the pinned snapshot.
  This inconsistency violates the paper's data-snapshot discipline.

Action: rerun the absorption regression
        NSI_t = alpha + beta * V_t + eps_t,  on shock days |dV_t| > 2,
        with Newey-West SE (10 lags), under the pinned snapshot:
          paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv
        For 0050.TW, refetch with auto_adjust=False from yfinance and log
        the snapshot date.

Lookahead: pure same-day cross-section. NSI_t and V_t are both date-t. No
forecasting -> no lag needed (this is a descriptive regression following
Paper 8 main-text spec, not a predictive one).

Output: experiments/k1418/k1418_results.json + tables/k1418_cross_asset.csv.
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PINNED_CSV = os.path.join(
    REPO_ROOT,
    "paper",
    "volatility-absorption",
    "data",
    "spy_gld_tlt_qqq_eem_vix_2005-2026.csv",
)
TW_CSV_FALLBACK = os.path.join(REPO_ROOT, "storage", "macro", "yf_0050.TW.csv")
OUT_DIR = os.path.dirname(__file__)
TABLES_DIR = os.path.join(OUT_DIR, "tables")
os.makedirs(TABLES_DIR, exist_ok=True)

SHOCK_TAU = 2.0  # |dVIX| > 2 shock definition (paper baseline)
NW_LAGS = 10     # Newey-West HAC lags
SAMPLE_START = "2006-01-01"  # match paper line 42 "from 2006 to 2026"
SAMPLE_END = "2026-04-19"    # pinned snapshot date


def _newey_west_se(X: np.ndarray, resid: np.ndarray, lags: int) -> np.ndarray:
    """Newey-West HAC covariance (Bartlett kernel)."""
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    S = np.zeros((k, k))
    u = resid.reshape(-1, 1)
    Xu = X * u  # n x k
    S += Xu.T @ Xu / n
    for l in range(1, lags + 1):
        w = 1.0 - l / (lags + 1.0)
        Gamma = (Xu[l:].T @ Xu[:-l]) / n
        S += w * (Gamma + Gamma.T)
    cov = n * XtX_inv @ S @ XtX_inv
    return np.sqrt(np.diag(cov))


def run_regression(returns: pd.Series, vix: pd.Series, label: str) -> dict:
    """NSI = |r_pct| / V regressed on V, on shock days |dV| > tau.

    Returns are converted to percent (r*100) to match Paper 8 convention
    (main_v3.tex line 327 reports alpha=0.091 which is only consistent with
    percent returns; see also K903 paper-drafting numbers beta_x1e4 ~ -2.8).
    """
    r_pct = returns * 100.0
    df = pd.concat([r_pct.rename("r"), vix.rename("V")], axis=1).dropna()
    df["dV"] = df["V"].diff()
    df = df.dropna()
    df = df[df["dV"].abs() > SHOCK_TAU].copy()
    df["NSI"] = df["r"].abs() / df["V"]
    df = df.replace([np.inf, -np.inf], np.nan).dropna()

    n = len(df)
    if n < 30:
        return {"asset": label, "n": n, "skipped": True}

    y = df["NSI"].values
    X = np.column_stack([np.ones(n), df["V"].values])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    se = _newey_west_se(X, resid, NW_LAGS)
    t_stat = coef / se

    y_mean = y.mean()
    ss_res = float(((y - X @ coef) ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    r2_adj = 1.0 - (1.0 - r2) * (n - 1) / (n - 2)

    return {
        "asset": label,
        "n": int(n),
        "alpha": float(coef[0]),
        "alpha_se": float(se[0]),
        "alpha_t": float(t_stat[0]),
        "beta": float(coef[1]),
        "beta_se": float(se[1]),
        "beta_t": float(t_stat[1]),
        "r2": float(r2),
        "r2_adj": float(r2_adj),
        "sample_start": str(df.index.min().date()),
        "sample_end": str(df.index.max().date()),
        "tau": SHOCK_TAU,
        "nw_lags": NW_LAGS,
    }


def _load_pinned() -> pd.DataFrame:
    df = pd.read_csv(PINNED_CSV, parse_dates=["date"])
    df = df.set_index("date").sort_index()
    df = df.loc[(df.index >= pd.Timestamp(SAMPLE_START)) & (df.index <= pd.Timestamp(SAMPLE_END))]
    return df


def _load_0050() -> tuple[pd.Series, pd.Series, str]:
    """Return (returns, vix_series, snapshot_note).

    Strategy: try fresh yfinance fetch with auto_adjust=False; fall back to
    storage cache if network fails.
    """
    note = ""
    try:
        import yfinance as yf  # type: ignore

        t = yf.Ticker("0050.TW")
        h = t.history(start="2005-01-01", end=SAMPLE_END, auto_adjust=False)
        if len(h) > 0:
            ret = h["Close"].pct_change().dropna()
            ret.index = ret.index.tz_localize(None) if ret.index.tz else ret.index
            note = f"0050.TW fetched via yfinance auto_adjust=False, snapshot_at={datetime.now(timezone.utc).date()}"
            # Pair with VIX from pinned CSV
            pinned = _load_pinned()
            vix = pinned["vix_close"]
            common = ret.index.intersection(vix.index)
            return ret.loc[common], vix.loc[common], note
    except Exception as exc:
        note = f"yfinance failed ({exc!s}); falling back to {TW_CSV_FALLBACK}"

    # Fallback path
    cache = pd.read_csv(TW_CSV_FALLBACK, parse_dates=["Date"]).set_index("Date").sort_index()
    cache.index = cache.index.tz_localize(None) if cache.index.tz else cache.index
    ret = cache["Close"].pct_change().dropna()
    pinned = _load_pinned()
    vix = pinned["vix_close"]
    common = ret.index.intersection(vix.index)
    return ret.loc[common], vix.loc[common], note


def main() -> None:
    print(f"[K1418] loading pinned snapshot: {PINNED_CSV}")
    pinned = _load_pinned()
    print(f"[K1418] pinned date range: {pinned.index.min().date()} -> {pinned.index.max().date()}, rows={len(pinned)}")

    vix = pinned["vix_close"]
    results = []

    for ticker, col in (("SPY", "spy_close"), ("GLD", "gld_close"), ("TLT", "tlt_close")):
        ret = pinned[col].pct_change().dropna()
        res = run_regression(ret, vix.loc[ret.index], ticker)
        print(f"[K1418] {ticker}: beta={res.get('beta', 'NA'):.6f} t={res.get('beta_t', 0):.3f} N={res['n']}")
        results.append(res)

    print("[K1418] running 0050.TW with auto_adjust=False ...")
    ret_tw, vix_tw, note_tw = _load_0050()
    res_tw = run_regression(ret_tw, vix_tw, "0050.TW")
    res_tw["snapshot_note"] = note_tw
    print(f"[K1418] 0050.TW: beta={res_tw.get('beta', 'NA'):.6f} t={res_tw.get('beta_t', 0):.3f} N={res_tw['n']}")
    results.append(res_tw)

    out = {
        "experiment_id": "K1418",
        "title": "Paper 8 cross-asset NSI absorption regression rerun under 2026-04-19 pinned snapshot",
        "data_sources": {
            "pinned_csv": os.path.relpath(PINNED_CSV, REPO_ROOT),
            "0050_tw_note": note_tw,
            "sample_period": [SAMPLE_START, SAMPLE_END],
            "shock_tau": SHOCK_TAU,
            "nw_lags": NW_LAGS,
        },
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict_summary": (
            "Cross-asset NSI absorption regression results under 2026-04-19 pinned "
            "snapshot. Paper 8 main_v3.tex Table 'cross_asset_detail' should be "
            "updated to reflect these values."
        ),
    }

    json_path = os.path.join(OUT_DIR, "k1418_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[K1418] wrote {json_path}")

    # Also write a CSV table for easy ingestion
    csv_path = os.path.join(TABLES_DIR, "k1418_cross_asset.csv")
    rows = [
        {
            "asset": r["asset"],
            "alpha": round(r.get("alpha", float("nan")), 6),
            "beta_x1e4": round(r.get("beta", float("nan")) * 1e4, 3),
            "beta_t": round(r.get("beta_t", float("nan")), 3),
            "r2_adj": round(r.get("r2_adj", float("nan")), 4),
            "n": r["n"],
        }
        for r in results
    ]
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    print(f"[K1418] wrote {csv_path}")


if __name__ == "__main__":
    main()
