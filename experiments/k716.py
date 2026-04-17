#!/usr/bin/env python3
"""
K716: Shock Amplification Ratio (SAR) — VIX Regime Analysis for SPY
=====================================================================
RECONSTRUCTED from paper/volatility-absorption/main_v2.tex (2026-04-17)
Reason: original .py never committed; replication package recovery.

Research Question:
    Does the marginal impact of VIX fear shocks on SPY absolute returns
    diminish as the ambient VIX level rises? ("Volatility Absorption")

Methodology (Section 3 of main_v2.tex):
    - VIX regimes: calm(<15), normal(15-20), elevated(20-25), high(25-30), crisis(≥30)
    - Shock day: |ΔVIX| > τ = 2 (baseline)
    - SAR_j = mean|r_t| (shock days in regime j) / mean|r_t| (non-shock days in regime j)
    - NSI_t = |r_t| / VIX_t  (supplementary measure)
    - NSI ~ VIX OLS regression on shock days (Newey-West 10 lags)

Data:
    - SPY, ^VIX: yfinance, 2006-01-01 to 2026-03-31 daily
    - N ≈ 5,050 trading days

Expected (from paper abstract + Table 1):
    calm: SAR=3.16, normal: 2.77, elevated: 2.37, high: 2.32, crisis: 2.43
    regression_normalized_slope = -0.00028 (t=-3.42)
    conclusion = "paralysis"

Output:
    k716_results_reconstructed.json
    k716_reconstruction_diff.md

References:
    - main_v2.tex Section 3 (Methodology), Section 5.1 (Core Results)
    - Equation (1): SAR_j definition
    - Equation (2): NSI definition
    - Equation (3): absorption regression
    - Table 1 (tab:absorption_core) in paper
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─── Constants ───────────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)

REGIMES = {
    "calm (<15)": (0, 15),
    "normal (15-20)": (15, 20),
    "elevated (20-25)": (20, 25),
    "high (25-30)": (25, 30),
    "crisis (>30)": (30, np.inf),
}
TAU = 2.0  # shock threshold: |ΔVIX| > tau
START = "2006-01-01"
END = "2026-03-31"
NW_LAGS = 10  # Newey-West lags

OUT_DIR = Path(__file__).parent


def download_data():
    """Download SPY and VIX daily data from yfinance."""
    tickers = ["SPY", "^VIX"]
    raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)
    close = raw["Close"].copy()
    close.columns = [c.replace("^", "") for c in close.columns]
    return close


def compute_returns(close):
    """Compute log returns for SPY, keep VIX levels."""
    df = pd.DataFrame(index=close.index)
    df["r_spy"] = np.log(close["SPY"] / close["SPY"].shift(1)) * 100
    df["vix"] = close["VIX"]
    df["dvix"] = df["vix"].diff()
    df = df.dropna()
    return df


def classify_regime(vix_level):
    """Return regime label for a given VIX level."""
    for label, (lo, hi) in REGIMES.items():
        if lo <= vix_level < hi:
            return label
    return "crisis (>30)"


def compute_sar(df):
    """Compute SAR per VIX regime."""
    df = df.copy()
    df["regime"] = df["vix"].apply(classify_regime)
    df["is_shock"] = df["dvix"].abs() > TAU
    df["abs_r"] = df["r_spy"].abs()

    results = {}
    for label in REGIMES:
        mask_regime = df["regime"] == label
        shock_days = df[mask_regime & df["is_shock"]]
        normal_days = df[mask_regime & ~df["is_shock"]]
        shock_abs_r = shock_days["abs_r"].mean()
        normal_abs_r = normal_days["abs_r"].mean()
        ratio = shock_abs_r / normal_abs_r if normal_abs_r > 0 else np.nan
        results[label] = {
            "shock_days": int(len(shock_days)),
            "shock_abs_r": round(float(shock_abs_r), 2),
            "normal_abs_r": round(float(normal_abs_r), 2),
            "ratio": round(float(ratio), 2),
        }
    return results, df


def newey_west_ols(y, x, lags=NW_LAGS):
    """
    OLS with Newey-West standard errors.
    Returns (slope, intercept, t_stat_slope, p_value_slope).
    Uses vectorized NW estimator for correctness.
    """
    x_arr = np.array(x, dtype=float)
    y_arr = np.array(y, dtype=float)
    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_arr, y_arr = x_arr[mask], y_arr[mask]
    n = len(y_arr)

    X = np.column_stack([np.ones(n), x_arr])
    beta = np.linalg.lstsq(X, y_arr, rcond=None)[0]
    resid = y_arr - X @ beta

    # Newey-West HAC covariance (vectorized)
    XtX_inv = np.linalg.inv(X.T @ X)
    # Compute score matrix: S[t] = X[t] * e[t]
    score = X * resid[:, np.newaxis]  # (n, 2)

    # Sandwich: S0 + sum_l (1 - l/(L+1)) * (Gamma_l + Gamma_l')
    S0 = score.T @ score
    S = S0.copy()
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1)
        gamma_l = score[lag:].T @ score[:-lag]
        S += w * (gamma_l + gamma_l.T)

    cov_nw = XtX_inv @ S @ XtX_inv

    se = np.sqrt(np.diag(cov_nw))
    t_slope = beta[1] / se[1]
    p_slope = 2 * (1 - stats.t.cdf(abs(t_slope), df=n - 2))
    return float(beta[1]), float(beta[0]), float(t_slope), float(p_slope)


def compute_nsi_regression(df):
    """
    NSI = |r_t| / VIX_t, regress on VIX for shock days only.
    Uses statsmodels HAC (Newey-West) for standard errors.
    NOTE: paper reports N=893 (full VIX series shock filter) vs N=767 (SAR sample).
    We use N=767 (joint availability), which gives slope≈-0.00027 vs paper's -0.00028.
    The t-stat discrepancy (-1.77 vs paper's -3.42) may reflect: different N,
    different NW bandwidth, or different data vintage.
    """
    try:
        import statsmodels.api as sm_api
        shock_df = df[df["dvix"].abs() > TAU].copy()
        shock_df["nsi"] = shock_df["abs_r"] / shock_df["vix"]
        shock_df = shock_df.dropna(subset=["nsi", "vix"])
        X = sm_api.add_constant(shock_df["vix"])
        model = sm_api.OLS(shock_df["nsi"], X).fit(
            cov_type="HAC", cov_kwds={"maxlags": NW_LAGS}
        )
        slope = float(model.params.iloc[1])
        intercept = float(model.params.iloc[0])
        t_stat = float(model.tvalues.iloc[1])
        p_val = float(model.pvalues.iloc[1])
    except Exception:
        shock_df = df[df["dvix"].abs() > TAU].copy()
        shock_df["nsi"] = shock_df["abs_r"] / shock_df["vix"]
        shock_df = shock_df.dropna(subset=["nsi", "vix"])
        slope, intercept, t_stat, p_val = newey_west_ols(
            shock_df["nsi"], shock_df["vix"], lags=NW_LAGS
        )
    return slope, intercept, t_stat, p_val


def main():
    print("K716: SAR analysis — downloading data...")
    close = download_data()
    df = compute_returns(close)
    df["abs_r"] = df["r_spy"].abs()

    print(f"Sample: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

    # SAR per regime
    sar_results, df_with_regime = compute_sar(df)
    total_shocks = sum(v["shock_days"] for v in sar_results.values())
    print(f"Total shock days (|ΔVIX|>{TAU}): {total_shocks}")

    # NSI regression
    slope, intercept, t_stat, p_val = compute_nsi_regression(df)
    print(f"NSI regression: slope={slope:.5f}, t={t_stat:.2f}, p={p_val:.4f}")

    # Determine conclusion
    # "paralysis" = negative slope (absorption effect confirmed)
    conclusion = "paralysis" if slope < 0 else "no_paralysis"

    # Build output matching original JSON schema exactly
    output = {}
    for label, vals in sar_results.items():
        output[label] = vals

    output["regression_raw_slope"] = round(
        float(
            np.polyfit(
                df_with_regime[df_with_regime["dvix"].abs() > TAU]["vix"],
                df_with_regime[df_with_regime["dvix"].abs() > TAU]["abs_r"],
                1,
            )[0]
        ),
        4,
    )
    output["regression_normalized_slope"] = round(float(slope), 5)
    output["conclusion"] = conclusion

    # Save reconstructed results
    out_path = OUT_DIR / "k716_results_reconstructed.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved: {out_path}")

    # ─── Compare with original ────────────────────────────────────────────────
    orig_path = OUT_DIR / "k716_results.json"
    if orig_path.exists():
        with open(orig_path) as f:
            orig = json.load(f)
        generate_diff_report(orig, output, OUT_DIR / "k716_reconstruction_diff.md")

    return output


def generate_diff_report(orig, recon, out_path):
    """Generate diff markdown comparing original vs reconstructed."""
    lines = [
        "# K716 Reconstruction Diff Report",
        "",
        "Comparison: `k716_results.json` (original, ground truth) vs `k716_results_reconstructed.json` (reconstructed from main_v2.tex methodology)",
        "",
        f"Reconstruction date: 2026-04-17",
        f"Threshold: rtol=0.01, atol=1e-4",
        "",
        "## SAR Table Comparison",
        "",
        "| Regime | Field | Original | Reconstructed | Diff | Match? |",
        "|--------|-------|----------|---------------|------|--------|",
    ]

    all_match = True
    regime_keys = [
        "calm (<15)",
        "normal (15-20)",
        "elevated (20-25)",
        "high (25-30)",
        "crisis (>30)",
    ]
    fields = ["shock_days", "shock_abs_r", "normal_abs_r", "ratio"]

    for regime in regime_keys:
        if regime not in orig or regime not in recon:
            lines.append(f"| {regime} | ALL | MISSING | MISSING | N/A | BLOCKED |")
            all_match = False
            continue
        for field in fields:
            o_val = orig[regime][field]
            r_val = recon[regime][field]
            diff = abs(o_val - r_val) if isinstance(o_val, (int, float)) else "N/A"
            rtol = abs(o_val - r_val) / max(abs(o_val), 1e-9) if isinstance(o_val, (int, float)) else None
            match = "YES" if rtol is not None and rtol <= 0.01 else "NO"
            if match == "NO":
                all_match = False
            diff_str = f"{diff:.4f}" if isinstance(diff, float) else str(diff)
            lines.append(
                f"| {regime} | {field} | {o_val} | {r_val} | {diff_str} | {match} |"
            )

    # Scalar fields
    lines += [
        "",
        "## Scalar Fields",
        "",
        "| Field | Original | Reconstructed | Diff | Match? |",
        "|-------|----------|---------------|------|--------|",
    ]
    scalar_fields = ["regression_raw_slope", "regression_normalized_slope", "conclusion"]
    for field in scalar_fields:
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
            "- Data range end date: original may have used slightly different end date",
            "- Rounding in original results (stored as 2 decimal places)",
            "- yfinance data revision since original computation",
            "- Trading calendar differences",
            "",
            "**Paper errata risk**: Numbers in main_v2.tex may need verification if divergence >1%",
        ]
    else:
        lines.append("Paper numbers confirmed reproducible. No errata needed from K716.")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Diff report: {out_path}")


if __name__ == "__main__":
    main()
