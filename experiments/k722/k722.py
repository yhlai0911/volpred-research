#!/usr/bin/env python3
"""
K722: Robustness — RV-Normalized Absorption (Alternative Normalizer)
=====================================================================
RECONSTRUCTED from paper/volatility-absorption/main_v2.tex (2026-04-17)
Reason: original .py never committed; replication package recovery.

NOTE: k722_results.json contains:
    {"corr_raw": 0.6803, "corr_adjusted": 0.6686, "r2_raw": 0.4628, "r2_adjusted": 0.447, "conclusion": "not improved"}

This maps to Section 7.3 (Alternative Normalization) and possibly the
sub-period robustness (Section 7.2) of main_v2.tex.

The "corr_raw" / "corr_adjusted" / "r2_raw" / "r2_adjusted" structure suggests:
    - A regression of NSI^RV on RV (or VIX) with raw vs. adjusted R² comparison
    - The key question: does normalizing by RV instead of VIX improve the regression fit?
    - conclusion="not improved" → RV normalization does NOT improve fit over VIX normalization

Methodology (Section 3.7 / Section 7.3 of main_v2.tex):
    NSI^RV_t = |r_t| / sqrt(RV_t^(20))
    where RV_t^(20) = sum_{i=1}^{20} r_{t-i}^2

    Regression: NSI^RV ~ sqrt(RV) (analog of NSI ~ VIX)
    Compare R² of: NSI^RV ~ sqrt(RV)  vs  NSI ~ VIX
    If R² does not improve substantially → "not improved"

    Alternative interpretation: corr(NSI, NSI^RV) and R² comparison between
    two models explaining |r_t| via VIX vs RV normalization.

    Most natural: corr_raw = corr(|r_t|, VIX_t) on shock days = 0.6803
                  corr_adjusted = corr(|r_t|, sqrt(RV)) on shock days = 0.6686
                  r2_raw = 0.6803^2 ≈ 0.4628 (yes, matches)
                  r2_adjusted = 0.6686^2 ≈ 0.4470 (yes, matches)
                  conclusion = "not improved" → RV normalization slightly worse

Expected (from k722_results.json):
    corr_raw: 0.6803 → R²=0.4628
    corr_adjusted: 0.6686 → R²=0.4470
    conclusion: "not improved"

Data:
    - SPY, ^VIX: yfinance, 2006-01-01 to 2026-03-31

Output:
    k722_results_reconstructed.json
    k722_reconstruction_diff.md
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
RV_WINDOW = 20  # Section 7.3: 20-day RV
START = "2006-01-01"
END = "2026-03-31"
OUT_DIR = Path(__file__).parent


def download_data():
    """Download SPY and VIX."""
    tickers = ["SPY", "^VIX"]
    raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)
    close = raw["Close"].copy()
    close.columns = [c.replace("^", "") for c in close.columns]
    return close


def compute_features(close):
    """Compute returns, realized vol, NSI measures."""
    spy_r = np.log(close["SPY"] / close["SPY"].shift(1)) * 100
    vix = close["VIX"]
    dvix = vix.diff()

    # 20-day backward-looking RV (no lookahead)
    rv_20 = spy_r.pow(2).rolling(RV_WINDOW).sum()

    df = pd.DataFrame({
        "r_spy": spy_r,
        "vix": vix,
        "dvix": dvix,
        "rv_20": rv_20,
    }).dropna()

    df["abs_r"] = df["r_spy"].abs()
    df["nsi_vix"] = df["abs_r"] / df["vix"]
    df["sqrt_rv"] = np.sqrt(df["rv_20"])
    df["nsi_rv"] = df["abs_r"] / df["sqrt_rv"]

    return df


def main():
    print("K722: RV-normalization robustness — downloading data...")
    close = download_data()
    df = compute_features(close)

    # Filter to shock days
    shock_df = df[df["dvix"].abs() > TAU].copy()
    print(f"Shock days: {len(shock_df)}")

    # Corr(|r|, VIX) on shock days — "raw" normalization
    corr_raw = float(shock_df["abs_r"].corr(shock_df["vix"]))
    r2_raw = corr_raw ** 2

    # Corr(|r|, sqrt(RV)) on shock days — "adjusted" (RV normalization)
    corr_adjusted = float(shock_df["abs_r"].corr(shock_df["sqrt_rv"]))
    r2_adjusted = corr_adjusted ** 2

    print(f"corr_raw (|r| ~ VIX): {corr_raw:.4f}, R²={r2_raw:.4f}")
    print(f"corr_adjusted (|r| ~ sqrt(RV)): {corr_adjusted:.4f}, R²={r2_adjusted:.4f}")

    # Conclusion: "not improved" if R² with RV normalization not higher than VIX
    conclusion = "not improved" if r2_adjusted <= r2_raw else "improved"

    output = {
        "corr_raw": round(corr_raw, 4),
        "corr_adjusted": round(corr_adjusted, 4),
        "r2_raw": round(r2_raw, 4),
        "r2_adjusted": round(r2_adjusted, 4),
        "conclusion": conclusion,
    }

    # Save
    out_path = OUT_DIR / "k722_results_reconstructed.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved: {out_path}")

    # Diff
    orig_path = OUT_DIR / "k722_results.json"
    if orig_path.exists():
        with open(orig_path) as f:
            orig = json.load(f)
        generate_diff_report(orig, output, OUT_DIR / "k722_reconstruction_diff.md")

    return output


def generate_diff_report(orig, recon, out_path):
    """Generate diff markdown for K722."""
    lines = [
        "# K722 Reconstruction Diff Report",
        "",
        "Comparison: `k722_results.json` (original) vs `k722_results_reconstructed.json` (reconstructed)",
        "",
        f"Reconstruction date: 2026-04-17",
        f"Threshold: rtol=0.01, atol=1e-4",
        "",
        "## Notes on Interpretation",
        "",
        "k722 measures whether RV-based normalization outperforms VIX-based normalization.",
        "corr_raw = corr(|r_SPY|, VIX) on shock days → measures how well VIX predicts |r|",
        "corr_adjusted = corr(|r_SPY|, sqrt(RV_20)) on shock days → RV predictor",
        "R² values are squares of correlations (verified: 0.6803² ≈ 0.4628, 0.6686² ≈ 0.4470).",
        "",
        "## Field Comparison",
        "",
        "| Field | Original | Reconstructed | Diff | Match? |",
        "|-------|----------|---------------|------|--------|",
    ]

    all_match = True
    fields = ["corr_raw", "corr_adjusted", "r2_raw", "r2_adjusted", "conclusion"]
    for field in fields:
        o_val = orig.get(field, "MISSING")
        r_val = recon.get(field, "MISSING")
        if isinstance(o_val, (int, float)) and isinstance(r_val, (int, float)):
            diff = abs(o_val - r_val)
            rtol = diff / max(abs(o_val), 1e-9)
            match = "YES" if rtol <= 0.01 else "NO"
            if match == "NO":
                all_match = False
            lines.append(f"| {field} | {o_val} | {r_val} | {diff:.6f} | {match} |")
        else:
            match = "YES" if str(o_val) == str(r_val) else "NO"
            if match == "NO":
                all_match = False
            lines.append(f"| {field} | {o_val} | {r_val} | string | {match} |")

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
            "- Exact formula for corr_raw may use different pairs (e.g., NSI_VIX vs |r|)",
            "- Different shock filter (all shocks vs only negative SPY)",
            "- Different RV window (Section 7.3 says 20 days, Section 3.7 says h=22)",
            "- Data revisions in yfinance since original computation",
            "",
            "**Paper errata risk**: K722 supports Section 7.3 robustness. The key claim is",
            "'alternative normalization produces qualitatively identical results' (slope remains",
            "negative). If our conclusion='not improved' matches, the paper's robustness",
            "claim is verified. Low direct errata risk — these are supporting robustness stats.",
        ]
    else:
        lines.append("Paper numbers confirmed reproducible. No errata needed from K722.")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Diff report: {out_path}")


if __name__ == "__main__":
    main()
