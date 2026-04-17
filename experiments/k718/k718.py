#!/usr/bin/env python3
"""
K718: Endogenous/Exogenous Shock Decomposition — Cross-Asset Absorption
========================================================================
RECONSTRUCTED from paper/volatility-absorption/main_v2.tex (2026-04-17)
Reason: original .py never committed; replication package recovery.

NOTE: k718_results.json contains CROSS-ASSET SAR results (SPY, GLD, TLT, 0050.TW)
      with absorption slopes and paralysis flags. This matches Table (tab:cross_asset)
      and the multi-asset absorption regression in Section 5.2 of main_v2.tex.
      (NOT the shock-type decomposition, which is K721.)

Research Question (from k718_results.json structure):
    Does the absorption effect (negative NSI~VIX slope) hold across
    SPY, GLD, TLT, and 0050.TW? Is there a "paralysis" conclusion?

Methodology (Section 3.6 of main_v2.tex):
    - NSI_t = |r_t| / VIX_t for each asset
    - OLS: NSI ~ VIX, shock days only (|ΔVIX| > 2)
    - Newey-West SE, 10 lags
    - SAR ratios: calm, normal, high (3-bucket aggregation)
    - Paralysis: slope < 0 AND significant

Expected (from k718_results.json):
    SPY: slope=-0.00028, GLD: -0.00043, TLT: -0.00044, 0050.TW: +0.00019
    SPY n_shocks=767, 0050.TW n_shocks=612

Data:
    - SPY, GLD, TLT, 0050.TW, ^VIX: yfinance, 2006-01-01 to 2026-03-31

Output:
    k718_results_reconstructed.json
    k718_reconstruction_diff.md
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

TAU = 2.0
START = "2006-01-01"
END = "2026-03-31"
NW_LAGS = 10
OUT_DIR = Path(__file__).parent

ASSETS = ["SPY", "GLD", "TLT", "0050.TW"]


def download_data():
    """Download all assets + VIX."""
    tickers = ASSETS + ["^VIX"]
    raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)
    close = raw["Close"].copy()
    close.columns = [c.replace("^", "") for c in close.columns]
    return close


def newey_west_ols(y, x, lags=NW_LAGS):
    """OLS with Newey-West standard errors. Returns (slope, intercept, t_stat, p_val)."""
    x_arr = np.array(x, dtype=float)
    y_arr = np.array(y, dtype=float)
    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_arr, y_arr = x_arr[mask], y_arr[mask]
    n = len(y_arr)

    X = np.column_stack([np.ones(n), x_arr])
    beta = np.linalg.lstsq(X, y_arr, rcond=None)[0]
    resid = y_arr - X @ beta

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
    p_slope = 2 * (1 - stats.t.cdf(abs(t_slope), df=n - 2))
    return float(beta[1]), float(beta[0]), float(t_slope), float(p_slope)


def sar_3bucket(abs_r, vix, dvix):
    """Compute 3-bucket SAR: calm(<20), normal(20-25 approx), high(≥25)."""
    # k718 uses 3 buckets: calm, normal, high (simplified from 5-bucket)
    # Based on the JSON structure: keys are "calm", "normal", "high"
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
        ratios[label] = round(float(shock_mean / normal_mean) if normal_mean > 0 else np.nan, 2)
    return ratios


def process_asset(asset, close, vix_series, dvix_series):
    """Process one asset: compute SAR + NSI regression."""
    asset_close = close[asset].dropna()

    # Log returns
    r = np.log(asset_close / asset_close.shift(1)) * 100

    # Align with VIX
    common = r.index.intersection(vix_series.index).intersection(dvix_series.index)
    r_a = r.loc[common]
    vix_a = vix_series.loc[common]
    dvix_a = dvix_series.loc[common]

    # Drop NAs
    valid = r_a.notna() & vix_a.notna() & dvix_a.notna()
    r_a = r_a[valid]
    vix_a = vix_a[valid]
    dvix_a = dvix_a[valid]

    abs_r = r_a.abs()

    # Shock days
    is_shock = dvix_a.abs() > TAU
    n_shocks = int(is_shock.sum())

    # SAR 3-bucket
    ratios = sar_3bucket(abs_r, vix_a, dvix_a)

    # NSI regression on shock days
    shock_mask = is_shock
    nsi = abs_r[shock_mask] / vix_a[shock_mask]
    vix_shock = vix_a[shock_mask]

    slope, intercept, t_stat, p_val = newey_west_ols(nsi, vix_shock, lags=NW_LAGS)

    paralysis = "YES" if slope < 0 and p_val < 0.15 else "NO"

    return {
        "ratios": ratios,
        "normalized_slope": round(float(slope), 5),
        "paralysis": paralysis,
        "n_shocks": n_shocks,
    }


def main():
    print("K718: Cross-asset absorption — downloading data...")
    close = download_data()

    vix = close["VIX"]
    dvix = vix.diff()

    output = {}
    for asset in ASSETS:
        if asset not in close.columns:
            print(f"WARNING: {asset} not in data, skipping")
            continue
        print(f"Processing {asset}...")
        result = process_asset(asset, close, vix, dvix)
        output[asset] = result
        print(
            f"  slope={result['normalized_slope']:.5f}, paralysis={result['paralysis']}, n_shocks={result['n_shocks']}"
        )

    # Summary
    paralysis_count = sum(1 for v in output.values() if v.get("paralysis") == "YES")
    output["summary"] = {
        "paralysis_count": paralysis_count,
        "total_assets": len(ASSETS),
    }

    # Save
    out_path = OUT_DIR / "k718_results_reconstructed.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved: {out_path}")

    # Diff report
    orig_path = OUT_DIR / "k718_results.json"
    if orig_path.exists():
        with open(orig_path) as f:
            orig = json.load(f)
        generate_diff_report(orig, output, OUT_DIR / "k718_reconstruction_diff.md")

    return output


def generate_diff_report(orig, recon, out_path):
    """Generate diff markdown for K718."""
    lines = [
        "# K718 Reconstruction Diff Report",
        "",
        "Comparison: `k718_results.json` (original) vs `k718_results_reconstructed.json` (reconstructed)",
        "",
        f"Reconstruction date: 2026-04-17",
        f"Threshold: rtol=0.01, atol=1e-4",
        "",
        "## Per-Asset Comparison",
        "",
        "| Asset | Field | Original | Reconstructed | Diff | Match? |",
        "|-------|-------|----------|---------------|------|--------|",
    ]

    all_match = True
    assets = ["SPY", "GLD", "TLT", "0050.TW"]

    for asset in assets:
        if asset not in orig or asset not in recon:
            lines.append(f"| {asset} | ALL | MISSING | MISSING | N/A | BLOCKED |")
            all_match = False
            continue

        o = orig[asset]
        r = recon[asset]

        # normalized_slope
        for field in ["normalized_slope", "n_shocks"]:
            o_val = o.get(field, "MISSING")
            r_val = r.get(field, "MISSING")
            if isinstance(o_val, (int, float)) and isinstance(r_val, (int, float)):
                diff = abs(o_val - r_val)
                rtol = diff / max(abs(o_val), 1e-9)
                match = "YES" if rtol <= 0.01 else "NO"
                if match == "NO":
                    all_match = False
                lines.append(f"| {asset} | {field} | {o_val} | {r_val} | {diff:.6f} | {match} |")

        # paralysis
        o_p = o.get("paralysis", "MISSING")
        r_p = r.get("paralysis", "MISSING")
        match = "YES" if o_p == r_p else "NO"
        if match == "NO":
            all_match = False
        lines.append(f"| {asset} | paralysis | {o_p} | {r_p} | string | {match} |")

        # SAR ratios
        for bucket in ["calm", "normal", "high"]:
            o_val = o.get("ratios", {}).get(bucket, "MISSING")
            r_val = r.get("ratios", {}).get(bucket, "MISSING")
            if isinstance(o_val, (int, float)) and isinstance(r_val, (int, float)):
                diff = abs(o_val - r_val)
                rtol = diff / max(abs(o_val), 1e-9)
                match = "YES" if rtol <= 0.01 else "NO"
                if match == "NO":
                    all_match = False
                lines.append(f"| {asset} | ratio_{bucket} | {o_val} | {r_val} | {diff:.4f} | {match} |")

    lines += [
        "",
        "## Summary",
        "",
        "| Field | Original | Reconstructed | Match? |",
        "|-------|----------|---------------|--------|",
    ]
    o_sum = orig.get("summary", {})
    r_sum = recon.get("summary", {})
    for field in ["paralysis_count", "total_assets"]:
        o_v = o_sum.get(field, "MISSING")
        r_v = r_sum.get(field, "MISSING")
        match = "YES" if o_v == r_v else "NO"
        if match == "NO":
            all_match = False
        lines.append(f"| {field} | {o_v} | {r_v} | {match} |")

    lines += [
        "",
        "## Overall Status",
        "",
        f"**Reconstruction result: {'MATCHED (allclose rtol=0.01)' if all_match else 'APPROXIMATE — see divergences above'}**",
        "",
    ]
    if not all_match:
        lines += [
            "### Likely causes of divergence:",
            "- SAR 3-bucket mapping may differ from 5-bucket (original may use different regime boundaries)",
            "- 0050.TW trading calendar differences",
            "- Newey-West computation differences (exact kernel weights)",
            "- Data revisions in yfinance since original computation",
            "",
            "**Paper errata risk**: Slopes -0.00028 (SPY), -0.00043 (GLD), -0.00044 (TLT), +0.00019 (0050.TW)",
            "in Table 3 of main_v2.tex. If divergence >1%, errata may be needed.",
        ]
    else:
        lines.append("Paper numbers confirmed reproducible. No errata needed from K718.")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Diff report: {out_path}")


if __name__ == "__main__":
    main()
