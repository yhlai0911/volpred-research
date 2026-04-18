#!/usr/bin/env python3
"""
K1250: K718 Rebuild — Paper 8 Cross-Asset Absorption Fix (Option A per K1231)
==============================================================================
Parent: K718 (experiments/k718/k718.py) — RECONSTRUCTED but APPROXIMATE diff.
Trigger: K1231 decision doc (experiments/k1231/k1231_reconstruction_decisions.json)
         assigned K718 = option (a) rebuild with priority HIGH.

Problem diagnosed by K1231:
  - 0050.TW slope drift 57.9% (orig +0.00019 vs recon +0.00008)
  - n_shocks off for all assets (US: 767→744, TW: 612→572)
  - t-statistics not emitted by K718 reconstruction (paper Table 4 lists 4 t-stats)
  - Table T4 in paper/volatility-absorption/reproduce_report.json: 5/9 match,
    4 untraceable (all t-stats).

Paper canonical (Table 4 in paper/volatility-absorption/main.tex, line 340-343):
  SPY     & -0.00028 & t = -3.42 & p < 0.001 & n_shocks ≈ 767
  GLD     & -0.00043 & t = -4.17 & p < 0.001 & n_shocks ≈ 767
  TLT     & -0.00044 & t = -3.89 & p < 0.001 & n_shocks ≈ 767
  0050.TW & +0.00019 & t = +1.62 & p = 0.106 & n_shocks ≈ 612

Root cause hypotheses (tested in this rebuild):
  H1: Multi-ticker yf.download injects NaN for non-Taiwan days on 0050.TW column,
      causing intersection over {SPY, 0050.TW, VIX} to lose rows; per-asset
      independent download should resolve.
  H2: vix.diff() first-row NaN + end-of-sample NaN drops ≥1 row per asset.
      Explicitly drop ΔVIX NaN only (not VIX-level NaN).
  H3: 0050.TW Taiwan calendar may include half-days or US-holiday/TW-trading
      mismatches; align strictly by common trading days.

Fix applied (Option A):
  1. Per-asset independent yf.download (no multi-ticker cascade).
  2. Compute dvix on VIX-only index, then inner-join with each asset's return
     index — do NOT pre-intersect before diff.
  3. Emit HAC/Newey-West t-stats explicitly in results JSON (recover Table 4
     t-statistics that K718 never emitted).
  4. Paper vs K1250 side-by-side comparison with allclose atol=1e-3, rtol=5%.
  5. Additional sanity: n_shocks target 767 (US) / 612 (TW); R² and intercept
     also emitted.

Data:
  - Yahoo Finance (yfinance): SPY, GLD, TLT, 0050.TW, ^VIX
  - Sample: 2006-01-01 to 2026-03-31
  - Log returns in percent; VIX in levels

Methodology:
  - NSI_t = |r_t| / V_t, shock days only (|ΔV_t| > 2)
  - Regression: NSI_t = α + β · V_t + ε_t, OLS with Newey-West 10 lags HAC SE
  - Lookahead guard: NSI and V at time t are both contemporaneous on shock day;
    no forecasting involved here (this is a contemporaneous decomposition
    regression, not a predictive strategy); no signal.shift() needed.

Seeds:
  - SEED = 42 (for consistency; no stochastic components in OLS/NW, but set for
    any downstream bootstrap).

Outputs:
  - k1250_results.json
  - k1250_vs_paper.md
  - README.md
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

# Config
TAU = 2.0  # |ΔVIX| > TAU defines shock days
START = "2006-01-01"
END = "2026-03-31"
NW_LAGS = 10
OUT_DIR = Path(__file__).parent
ASSETS = ["SPY", "GLD", "TLT", "0050.TW"]

# Paper canonical (from paper/volatility-absorption/main.tex Table 4)
PAPER_CANONICAL = {
    "SPY": {"slope": -0.00028, "t_stat": -3.42, "p_val": 0.001, "n_shocks": 767},
    "GLD": {"slope": -0.00043, "t_stat": -4.17, "p_val": 0.001, "n_shocks": 767},
    "TLT": {"slope": -0.00044, "t_stat": -3.89, "p_val": 0.001, "n_shocks": 767},
    "0050.TW": {"slope": 0.00019, "t_stat": 1.62, "p_val": 0.106, "n_shocks": 612},
}


def download_asset(ticker):
    """Per-asset independent download; returns Close series."""
    df = yf.download(ticker, start=START, end=END, auto_adjust=True, progress=False)
    if df.empty:
        return None
    # yf may return MultiIndex columns when ticker passed as list; take Close
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].iloc[:, 0]
    else:
        close = df["Close"]
    close = close.dropna()
    close.name = ticker
    return close


def newey_west_ols(y, x, lags=NW_LAGS):
    """OLS with Newey-West HAC SE. Returns dict with coefficients, SE, t, p, R²."""
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_arr, y_arr = x_arr[mask], y_arr[mask]
    n = len(y_arr)

    X = np.column_stack([np.ones(n), x_arr])
    beta, *_ = np.linalg.lstsq(X, y_arr, rcond=None)
    y_hat = X @ beta
    resid = y_arr - y_hat
    # R²
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y_arr - y_arr.mean()) ** 2))
    r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    # Bartlett-kernel Newey-West
    XtX_inv = np.linalg.inv(X.T @ X)
    score = X * resid[:, np.newaxis]
    S = score.T @ score
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1)
        gamma_l = score[lag:].T @ score[:-lag]
        S += w * (gamma_l + gamma_l.T)
    cov_nw = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov_nw))
    t_slope = beta[1] / se[1]
    # Two-sided t-test with n-k dof (k=2)
    p_slope = 2 * (1 - stats.t.cdf(abs(t_slope), df=n - 2))

    return {
        "intercept": float(beta[0]),
        "slope": float(beta[1]),
        "se_intercept": float(se[0]),
        "se_slope": float(se[1]),
        "t_slope": float(t_slope),
        "p_slope": float(p_slope),
        "r_squared": float(r_sq),
        "n_obs": int(n),
    }


def sar_3bucket(abs_r, vix, dvix):
    """3-bucket SAR: calm (VIX<20), normal (20-25), high (>=25)."""
    buckets = {
        "calm": vix < 20,
        "normal": (vix >= 20) & (vix < 25),
        "high": vix >= 25,
    }
    is_shock = dvix.abs() > TAU
    ratios = {}
    for label, mask in buckets.items():
        shock_mean = abs_r[mask & is_shock].mean()
        normal_mean = abs_r[mask & ~is_shock].mean()
        ratios[label] = (
            round(float(shock_mean / normal_mean), 2)
            if normal_mean and np.isfinite(normal_mean) and normal_mean > 0
            else np.nan
        )
    return ratios


def process_asset(asset, asset_close, vix_series, dvix_series):
    """Process one asset independently; aligned on common trading days."""
    # Log returns in percent (paper convention)
    r = np.log(asset_close / asset_close.shift(1)) * 100
    r = r.dropna()

    # Join on VIX calendar (inner join); dvix NaN-free by construction
    # because dvix_series was built from vix_series.diff().dropna()
    idx = r.index.intersection(vix_series.index).intersection(dvix_series.index)
    r_a = r.loc[idx]
    vix_a = vix_series.loc[idx]
    dvix_a = dvix_series.loc[idx]

    abs_r = r_a.abs()

    # Shock definition
    is_shock = dvix_a.abs() > TAU
    n_shocks = int(is_shock.sum())

    # SAR 3-bucket
    ratios = sar_3bucket(abs_r, vix_a, dvix_a)

    # NSI regression on shock days only
    nsi_shock = abs_r[is_shock] / vix_a[is_shock]
    vix_shock = vix_a[is_shock]

    reg = newey_west_ols(nsi_shock, vix_shock, lags=NW_LAGS)

    paralysis = "YES" if reg["slope"] < 0 and reg["p_slope"] < 0.15 else "NO"

    return {
        "ratios": ratios,
        "normalized_slope": round(reg["slope"], 5),
        "intercept": round(reg["intercept"], 5),
        "se_slope": round(reg["se_slope"], 6),
        "t_stat": round(reg["t_slope"], 2),
        "p_value": round(reg["p_slope"], 4),
        "r_squared": round(reg["r_squared"], 4),
        "paralysis": paralysis,
        "n_shocks": n_shocks,
        "n_obs_regression": reg["n_obs"],
    }


def compare_to_paper(recon, paper_canonical):
    """Side-by-side comparison; returns comparison dict + verdict."""
    rows = []
    for asset in ASSETS:
        p = paper_canonical[asset]
        r = recon.get(asset, {})
        slope_diff = abs(r.get("normalized_slope", np.nan) - p["slope"])
        slope_pct = slope_diff / max(abs(p["slope"]), 1e-9) * 100
        t_diff = abs(r.get("t_stat", np.nan) - p["t_stat"])
        t_pct = t_diff / max(abs(p["t_stat"]), 1e-9) * 100
        n_diff = r.get("n_shocks", 0) - p["n_shocks"]
        rows.append({
            "asset": asset,
            "paper_slope": p["slope"],
            "k1250_slope": r.get("normalized_slope"),
            "slope_pct_drift": round(slope_pct, 2),
            "paper_t": p["t_stat"],
            "k1250_t": r.get("t_stat"),
            "t_pct_drift": round(t_pct, 2),
            "paper_n_shocks": p["n_shocks"],
            "k1250_n_shocks": r.get("n_shocks"),
            "n_shocks_delta": n_diff,
            "slope_allclose_5pct": slope_pct <= 5.0,
            "slope_allclose_atol1e3": slope_diff <= 1e-3,
        })

    all_5pct = all(r["slope_allclose_5pct"] for r in rows)
    all_atol = all(r["slope_allclose_atol1e3"] for r in rows)
    verdict = (
        "ALLCLOSE_PASS" if (all_5pct and all_atol)
        else ("PARTIAL_TSTATS_RECOVERED" if all(r.get("k1250_t") is not None for r in rows) else "RESIDUAL_DRIFT")
    )
    max_drift = max(r["slope_pct_drift"] for r in rows)
    return {"rows": rows, "verdict": verdict, "max_slope_drift_pct": round(max_drift, 2)}


def main():
    print("K1250: K718 rebuild per K1231 option (a) — Paper 8 cross-asset absorption")
    print("=" * 75)

    # Step 1: download VIX independently
    print("[1/4] Downloading VIX...")
    vix_close = download_asset("^VIX")
    if vix_close is None:
        raise RuntimeError("VIX download failed; cannot proceed")
    # Build dvix independent of any asset
    dvix = vix_close.diff().dropna()
    vix = vix_close.loc[dvix.index]  # align
    print(f"   VIX period: {vix.index[0].date()} to {vix.index[-1].date()}, n={len(vix)}")

    # Step 2: download each asset independently
    print("[2/4] Downloading assets independently...")
    asset_closes = {}
    for a in ASSETS:
        c = download_asset(a)
        if c is None:
            print(f"   WARNING: {a} download empty — will mark BLOCKED")
            continue
        asset_closes[a] = c
        print(f"   {a}: {c.index[0].date()} to {c.index[-1].date()}, n={len(c)}")

    # Step 3: per-asset analysis
    print("[3/4] Running per-asset absorption regressions...")
    output = {"_meta": {
        "seed": SEED,
        "tau": TAU,
        "start": START,
        "end": END,
        "nw_lags": NW_LAGS,
        "experiment": "K1250",
        "parent": "K718",
        "trigger": "K1231 option (a)",
        "run_date": pd.Timestamp.utcnow().isoformat(),
    }}
    for a in ASSETS:
        if a not in asset_closes:
            output[a] = {"status": "BLOCKED", "reason": "yfinance returned empty"}
            continue
        print(f"   Processing {a}...")
        res = process_asset(a, asset_closes[a], vix, dvix)
        output[a] = res
        print(
            f"     slope={res['normalized_slope']:+.5f}, "
            f"t={res['t_stat']:+.2f}, "
            f"n_shocks={res['n_shocks']}, "
            f"paralysis={res['paralysis']}"
        )

    # Summary
    paralysis_count = sum(1 for a in ASSETS if output.get(a, {}).get("paralysis") == "YES")
    output["summary"] = {
        "paralysis_count": paralysis_count,
        "total_assets": len([a for a in ASSETS if "normalized_slope" in output.get(a, {})]),
    }

    # Step 4: paper comparison
    print("[4/4] Comparing to paper canonical (Table 4 main.tex)...")
    comp = compare_to_paper(output, PAPER_CANONICAL)
    output["paper_comparison"] = comp
    print(f"   Verdict: {comp['verdict']}, max_slope_drift={comp['max_slope_drift_pct']}%")

    # Save
    out_path = OUT_DIR / "k1250_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved: {out_path}")

    # Diff markdown
    write_vs_paper_md(output, comp, OUT_DIR / "k1250_vs_paper.md")

    return output


def write_vs_paper_md(output, comp, out_path):
    """Side-by-side K1250 vs paper canonical markdown."""
    lines = [
        "# K1250 vs Paper 8 Canonical (Table 4 main.tex)",
        "",
        f"Run date: {output['_meta']['run_date']}",
        f"Seed: {output['_meta']['seed']} | TAU: {output['_meta']['tau']} | NW lags: {output['_meta']['nw_lags']}",
        f"Sample: {output['_meta']['start']} to {output['_meta']['end']}",
        "",
        "## Cross-Asset Absorption Coefficients",
        "",
        "| Asset | Paper slope | K1250 slope | slope drift% | Paper t | K1250 t | t drift% | Paper n_shocks | K1250 n_shocks | Δn | allclose (5%) |",
        "|-------|-------------|-------------|--------------|---------|---------|----------|----------------|-----------------|-----|---------------|",
    ]
    for r in comp["rows"]:
        lines.append(
            f"| {r['asset']} | {r['paper_slope']:+.5f} | "
            f"{(r['k1250_slope'] if r['k1250_slope'] is not None else float('nan')):+.5f} | "
            f"{r['slope_pct_drift']:.2f}% | "
            f"{r['paper_t']:+.2f} | "
            f"{(r['k1250_t'] if r['k1250_t'] is not None else float('nan')):+.2f} | "
            f"{r['t_pct_drift']:.2f}% | "
            f"{r['paper_n_shocks']} | {r['k1250_n_shocks']} | "
            f"{r['n_shocks_delta']:+d} | "
            f"{'YES' if r['slope_allclose_5pct'] else 'NO'} |"
        )

    lines += [
        "",
        "## Verdict",
        "",
        f"- **Status**: {comp['verdict']}",
        f"- **Max slope drift**: {comp['max_slope_drift_pct']}%",
        f"- **t-statistics recovered**: {'YES' if all(r['k1250_t'] is not None for r in comp['rows']) else 'NO'}",
        "",
        "## Interpretation",
        "",
    ]
    if comp["verdict"] == "ALLCLOSE_PASS":
        lines += [
            "K1250 reproduces Table 4 within 5% / atol=1e-3 tolerance. All t-statistics",
            "now emitted in `k1250_results.json` — Paper 8 T4 traceability should reach",
            "9/9 (SPY/GLD/TLT/0050.TW slopes + t-stats = 8 fields, plus p-value column).",
            "Recommend replacing K718 as the canonical source for Paper 8 Table 4.",
        ]
    elif comp["verdict"] == "PARTIAL_TSTATS_RECOVERED":
        lines += [
            "K1250 recovers all t-statistics (previously untraceable in K718 JSON),",
            "but residual slope drift remains > 5% for at least one asset. Options for",
            "main thread:",
            "",
            "  (a) Accept K1250 as improved reconstruction; disclose divergence in",
            "      commit message and `reproduce_report.json` issues section.",
            "  (b) Update paper body `main.tex` Table 4 to reflect K1250 numbers",
            "      (research honesty path — revise slopes/t-stats to match current",
            "      yfinance data vintage).",
            "  (c) Note pending errata with magnitude disclosure per paper-workflow rule.",
        ]
    else:
        lines += [
            "Residual drift beyond 5% threshold AND/OR t-stats not fully emitted.",
            "Debug paths:",
            "",
            "  - Inspect `n_shocks_delta` column — if non-zero, investigate calendar",
            "    alignment or ΔVIX threshold.",
            "  - Check data vintage: yfinance may revise older prices; consider pinning",
            "    to a saved CSV snapshot.",
            "  - Per K1231: 0050.TW 57.9% drift was the primary concern. Current",
            "    drift % indicates whether option (a) rebuild sufficed.",
        ]
    lines += ["", "## Files", "", "- `k1250.py`: rebuild script",
              "- `k1250_results.json`: structured results (includes per-asset t-stat, R², intercept)",
              "- `k1250_vs_paper.md`: this file", ""]
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
