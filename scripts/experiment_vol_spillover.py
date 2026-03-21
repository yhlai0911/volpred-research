#!/usr/bin/env python3
"""
Cross-Asset Volatility Spillover Experiment
============================================
Tests whether SPY volatility Granger-causes GLD/TLT/EEM/QQQ volatility,
and whether vol spillover information can improve portfolio VT.

Key questions:
1. Does SPY vol predict GLD/TLT vol? (Granger causality)
2. What is the lead-lag structure? (cross-correlation)
3. Can vol spillover improve 50/50 portfolio risk management?

[提出: 用戶, 執行: Claude]
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────
TICKERS = ["SPY", "GLD", "TLT", "EEM", "QQQ"]
VIX_TICKER = "^VIX"
START_DATE = "2007-01-01"
RV_WINDOW = 22  # 22-day rolling std for realized vol
GRANGER_MAX_LAG = 5
OOS_START = "2023-01-01"
STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
OUTPUT_FILE = STORAGE_DIR / "experiments" / "vol_spillover.json"


def download_data():
    """Download price data for all assets + VIX."""
    print("Downloading price data...")
    all_tickers = TICKERS + [VIX_TICKER]
    data = yf.download(all_tickers, start=START_DATE, progress=False, auto_adjust=True)

    # Handle multi-level columns
    if isinstance(data.columns, pd.MultiIndex):
        closes = data["Close"]
    else:
        closes = data

    # Rename ^VIX column
    if "^VIX" in closes.columns:
        closes = closes.rename(columns={"^VIX": "VIX"})

    closes = closes.dropna(how="all")
    closes = closes.ffill()
    print(f"  Data range: {closes.index[0].strftime('%Y-%m-%d')} to {closes.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Observations: {len(closes)}")
    return closes


def compute_realized_vol(closes: pd.DataFrame, window: int = RV_WINDOW):
    """Compute annualized realized volatility (22-day rolling std of returns)."""
    returns = np.log(closes / closes.shift(1))
    rv = returns.rolling(window).std() * np.sqrt(252)
    return returns, rv


def granger_causality_test(y: pd.Series, x: pd.Series, max_lag: int = 5):
    """
    Manual Granger causality test: does x Granger-cause y?
    Uses OLS F-test comparing restricted (y lags only) vs unrestricted (y + x lags).
    Returns results for each lag order.
    """
    from numpy.linalg import lstsq

    # Align and drop NaN
    df = pd.DataFrame({"y": y, "x": x}).dropna()
    n = len(df)

    results = {}
    for lag in range(1, max_lag + 1):
        # Build lag matrices
        Y = df["y"].values[lag:]
        n_obs = len(Y)

        # Restricted model: only y lags
        X_r = np.column_stack([df["y"].shift(i).values[lag:] for i in range(1, lag + 1)])
        X_r = np.column_stack([np.ones(n_obs), X_r])

        # Unrestricted model: y lags + x lags
        X_u = np.column_stack([
            np.ones(n_obs),
            *[df["y"].shift(i).values[lag:] for i in range(1, lag + 1)],
            *[df["x"].shift(i).values[lag:] for i in range(1, lag + 1)],
        ])

        # Remove any NaN rows
        mask = ~(np.isnan(Y) | np.isnan(X_r).any(axis=1) | np.isnan(X_u).any(axis=1))
        Y, X_r, X_u = Y[mask], X_r[mask], X_u[mask]
        n_obs = len(Y)

        # OLS
        beta_r = lstsq(X_r, Y, rcond=None)[0]
        beta_u = lstsq(X_u, Y, rcond=None)[0]

        ssr_r = np.sum((Y - X_r @ beta_r) ** 2)
        ssr_u = np.sum((Y - X_u @ beta_u) ** 2)

        # F-test
        df_diff = lag  # number of restrictions
        df_denom = n_obs - X_u.shape[1]

        if ssr_u > 0 and df_denom > 0:
            f_stat = ((ssr_r - ssr_u) / df_diff) / (ssr_u / df_denom)
            p_value = 1 - stats.f.cdf(f_stat, df_diff, df_denom)
        else:
            f_stat = np.nan
            p_value = np.nan

        results[lag] = {
            "f_stat": round(float(f_stat), 4),
            "p_value": round(float(p_value), 6),
            "n_obs": int(n_obs),
            "significant_5pct": bool(p_value < 0.05),
            "significant_1pct": bool(p_value < 0.01),
        }

    return results


def var_model_aic(data: pd.DataFrame, max_lag: int = 10):
    """
    Select optimal VAR lag order by AIC.
    Uses manual OLS implementation to avoid statsmodels dependency issues.
    """
    from numpy.linalg import lstsq

    n_vars = data.shape[1]
    n = len(data)
    values = data.values

    best_aic = np.inf
    best_lag = 1
    aic_by_lag = {}

    for lag in range(1, min(max_lag + 1, n // (2 * n_vars))):
        # Build Y and X matrices for VAR
        Y = values[lag:]
        n_obs = len(Y)

        # Lagged values + constant
        X_parts = [np.ones((n_obs, 1))]
        for i in range(1, lag + 1):
            X_parts.append(values[lag - i:n - i])
        X = np.hstack(X_parts)

        # Remove NaN
        mask = ~(np.isnan(Y).any(axis=1) | np.isnan(X).any(axis=1))
        Y_clean = Y[mask]
        X_clean = X[mask]
        n_clean = len(Y_clean)

        if n_clean < X_clean.shape[1] + 10:
            continue

        # OLS for each equation
        residuals = np.zeros_like(Y_clean)
        for j in range(n_vars):
            beta = lstsq(X_clean, Y_clean[:, j], rcond=None)[0]
            residuals[:, j] = Y_clean[:, j] - X_clean @ beta

        # Covariance matrix of residuals
        sigma = (residuals.T @ residuals) / n_clean
        log_det = np.log(np.linalg.det(sigma))

        # AIC = log|Σ| + 2k/T where k = n_vars * (1 + lag * n_vars)
        k = n_vars * (1 + lag * n_vars)
        aic = log_det + 2 * k / n_clean

        aic_by_lag[lag] = round(float(aic), 4)
        if aic < best_aic:
            best_aic = aic
            best_lag = lag

    return best_lag, aic_by_lag


def cross_correlation_analysis(rv: pd.DataFrame, max_lag: int = 5):
    """Compute cross-correlation of vol changes at various lags."""
    vol_changes = rv.diff().dropna()

    results = {}
    pairs = [
        ("SPY", "GLD"), ("SPY", "TLT"), ("SPY", "EEM"), ("SPY", "QQQ"),
        ("GLD", "TLT"), ("VIX", "GLD"), ("VIX", "TLT"), ("VIX", "EEM"),
    ]

    for asset1, asset2 in pairs:
        if asset1 not in vol_changes.columns or asset2 not in vol_changes.columns:
            continue

        pair_key = f"{asset1}_to_{asset2}"
        pair_results = {}

        for lag in range(-max_lag, max_lag + 1):
            if lag == 0:
                corr = vol_changes[asset1].corr(vol_changes[asset2])
            elif lag > 0:
                # asset1 leads asset2 by 'lag' days
                corr = vol_changes[asset1].shift(lag).corr(vol_changes[asset2])
            else:
                # asset2 leads asset1 by 'lag' days
                corr = vol_changes[asset1].corr(vol_changes[asset2].shift(-lag))

            pair_results[f"lag_{lag}"] = round(float(corr), 4) if not np.isnan(corr) else None

        # Find peak lag
        valid = {k: v for k, v in pair_results.items() if v is not None}
        if valid:
            peak_key = max(valid, key=lambda k: abs(valid[k]))
            peak_lag = int(peak_key.split("_")[1])
            peak_corr = valid[peak_key]
        else:
            peak_lag = 0
            peak_corr = 0.0

        results[pair_key] = {
            "correlations": pair_results,
            "peak_lag": peak_lag,
            "peak_correlation": peak_corr,
            "interpretation": (
                f"{asset1} leads {asset2}" if peak_lag > 0
                else f"{asset2} leads {asset1}" if peak_lag < 0
                else "Contemporaneous"
            ),
        }

    return results


def impulse_response_analysis(rv: pd.DataFrame, shock_asset: str = "SPY", response_assets: list = None):
    """
    Simplified impulse response: regress future vol changes on current vol shock.
    How much does a 1-std SPY vol shock affect other assets' vol over 1-5 days?
    """
    if response_assets is None:
        response_assets = ["GLD", "TLT", "EEM", "QQQ"]

    vol_changes = rv.diff().dropna()
    shock = vol_changes[shock_asset]
    shock_std = shock.std()

    results = {}
    for asset in response_assets:
        if asset not in vol_changes.columns:
            continue

        horizon_results = {}
        for h in range(1, 6):
            # Cumulative vol change over h days after shock
            cum_response = vol_changes[asset].rolling(h).sum().shift(-h)

            # Align
            df_temp = pd.DataFrame({"shock": shock, "response": cum_response}).dropna()

            if len(df_temp) < 100:
                continue

            slope, intercept, r_value, p_value, std_err = stats.linregress(
                df_temp["shock"], df_temp["response"]
            )

            horizon_results[f"h{h}"] = {
                "beta": round(float(slope), 4),
                "t_stat": round(float(slope / std_err), 2) if std_err > 0 else None,
                "p_value": round(float(p_value), 4),
                "r_squared": round(float(r_value**2), 4),
                "impact_1std": round(float(slope * shock_std), 6),
            }

        results[asset] = horizon_results

    return results


def practical_vt_test(closes: pd.DataFrame, rv: pd.DataFrame, returns: pd.DataFrame):
    """
    Test whether vol spillover can improve portfolio VT.
    Compare:
    1. GLD weight = 12/VIX (baseline)
    2. GLD weight = target/own_RV (asset-specific VT)
    3. GLD weight = f(VIX, SPY_RV) (spillover-informed VT)
    """
    vix = closes["VIX"] if "VIX" in closes.columns else None
    if vix is None:
        return {"error": "No VIX data"}

    # Use OOS period
    oos_mask = closes.index >= OOS_START

    # Simple returns for portfolio
    spy_ret = returns["SPY"]
    gld_ret = returns["GLD"]

    # Strategy 1: Static 50/50 (benchmark)
    port_static = 0.5 * spy_ret + 0.5 * gld_ret

    # Strategy 2: 12/VIX uniform (both assets same weight)
    vix_weight = (12 / vix).clip(0.3, 1.0).shift(1)  # lagged
    port_vix = vix_weight * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - vix_weight) * 0

    # Strategy 3: Asset-specific VT (each asset gets own target/RV weight)
    spy_rv = rv["SPY"]
    gld_rv = rv["GLD"]
    target_vol = 0.12  # 12% target

    spy_w_own = (target_vol / spy_rv).clip(0.0, 1.5).shift(1)
    gld_w_own = (target_vol / gld_rv).clip(0.0, 1.5).shift(1)
    port_own_vt = 0.5 * spy_w_own * spy_ret + 0.5 * gld_w_own * gld_ret

    # Strategy 4: Spillover-informed — when SPY vol is high, reduce GLD weight too
    # (hypothesis: SPY vol predicts GLD vol increase → preemptive de-risk)
    spy_vol_z = ((spy_rv - spy_rv.rolling(252).mean()) / spy_rv.rolling(252).std()).shift(1)
    spillover_adj = 1 - 0.2 * spy_vol_z.clip(0, 3)  # reduce GLD by up to 60% when SPY vol is high
    gld_w_spillover = (gld_w_own * spillover_adj).clip(0.0, 1.5)
    port_spillover = 0.5 * spy_w_own * spy_ret + 0.5 * gld_w_spillover * gld_ret

    # Strategy 5: Cross-vol signal — use SPY vol change to predict GLD vol regime
    spy_vol_chg = spy_rv.pct_change(5).shift(1)  # 5-day SPY vol momentum, lagged
    gld_w_cross = gld_w_own.copy()
    gld_w_cross[spy_vol_chg > 0.2] *= 0.7  # reduce when SPY vol rising fast
    gld_w_cross[spy_vol_chg < -0.2] *= 1.1  # increase when SPY vol falling
    gld_w_cross = gld_w_cross.clip(0.0, 1.5)
    port_cross = 0.5 * spy_w_own * spy_ret + 0.5 * gld_w_cross * gld_ret

    # Evaluate all strategies in OOS
    strategies = {
        "static_5050": port_static,
        "vix_uniform_vt": port_vix,
        "asset_specific_vt": port_own_vt,
        "spillover_informed_vt": port_spillover,
        "cross_vol_signal_vt": port_cross,
    }

    eval_results = {}
    for name, ret_series in strategies.items():
        oos = ret_series[oos_mask].dropna()
        if len(oos) < 100:
            continue

        ann_ret = oos.mean() * 252
        ann_vol = oos.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + oos).cumprod()
        mdd = (cum / cum.cummax() - 1).min()
        calmar = ann_ret / abs(mdd) if mdd != 0 else 0

        eval_results[name] = {
            "annual_return": round(float(ann_ret), 4),
            "annual_vol": round(float(ann_vol), 4),
            "sharpe": round(float(sharpe), 4),
            "mdd": round(float(mdd), 4),
            "calmar": round(float(calmar), 4),
            "n_obs": int(len(oos)),
        }

    # DM test: spillover vs asset-specific
    oos_idx = returns.index[oos_mask]
    common_idx = oos_idx.intersection(port_own_vt.dropna().index).intersection(port_spillover.dropna().index)
    if len(common_idx) > 100:
        d = port_spillover.loc[common_idx] - port_own_vt.loc[common_idx]
        dm_stat = d.mean() / (d.std() / np.sqrt(len(d)))
        dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
        eval_results["dm_test_spillover_vs_own"] = {
            "dm_stat": round(float(dm_stat), 4),
            "p_value": round(float(dm_p), 4),
            "significant_5pct": bool(dm_p < 0.05),
        }

    return eval_results


def run_regime_analysis(rv: pd.DataFrame, returns: pd.DataFrame):
    """
    Check if vol spillover is regime-dependent.
    Does SPY → GLD vol causality change in high-vol vs low-vol regimes?
    """
    spy_rv = rv["SPY"]
    median_vol = spy_rv.median()

    regimes = {
        "low_vol": spy_rv < spy_rv.quantile(0.33),
        "mid_vol": (spy_rv >= spy_rv.quantile(0.33)) & (spy_rv < spy_rv.quantile(0.67)),
        "high_vol": spy_rv >= spy_rv.quantile(0.67),
    }

    results = {}
    for regime_name, mask in regimes.items():
        regime_rv = rv[mask].dropna()
        if len(regime_rv) < 200:
            results[regime_name] = {"n_obs": len(regime_rv), "note": "Too few observations"}
            continue

        # Test SPY → GLD Granger causality in this regime
        spy_vol = regime_rv["SPY"] if "SPY" in regime_rv.columns else None
        gld_vol = regime_rv["GLD"] if "GLD" in regime_rv.columns else None
        tlt_vol = regime_rv["TLT"] if "TLT" in regime_rv.columns else None

        regime_results = {"n_obs": len(regime_rv)}

        if spy_vol is not None and gld_vol is not None:
            gc = granger_causality_test(gld_vol, spy_vol, max_lag=3)
            regime_results["spy_to_gld"] = gc

        if spy_vol is not None and tlt_vol is not None:
            gc = granger_causality_test(tlt_vol, spy_vol, max_lag=3)
            regime_results["spy_to_tlt"] = gc

        results[regime_name] = regime_results

    return results


def main():
    print("=" * 70)
    print("Cross-Asset Volatility Spillover Experiment")
    print("=" * 70)

    # ── Step 1: Download and prepare data ──
    closes = download_data()
    returns, rv = compute_realized_vol(closes)

    # Remove VIX from rv (it's already a vol measure, not a price)
    rv_assets = rv[TICKERS].copy()

    # Add VIX level directly as a "vol" measure for comparison
    rv_with_vix = rv_assets.copy()
    rv_with_vix["VIX"] = closes["VIX"] / 100  # scale to comparable units

    print(f"\n  RV computed ({RV_WINDOW}-day window)")
    print(f"  Assets: {list(rv_assets.columns)}")

    # ── Step 2: Granger Causality Tests ──
    print("\n" + "=" * 70)
    print("Section 1: Granger Causality Tests")
    print("=" * 70)

    granger_pairs = [
        ("SPY", "GLD", "SPY vol → GLD vol?"),
        ("SPY", "TLT", "SPY vol → TLT vol?"),
        ("SPY", "EEM", "SPY vol → EEM vol?"),
        ("SPY", "QQQ", "SPY vol → QQQ vol?"),
        ("GLD", "SPY", "GLD vol → SPY vol?"),
        ("TLT", "SPY", "TLT vol → SPY vol?"),
        ("GLD", "TLT", "GLD vol → TLT vol?"),
        ("TLT", "GLD", "TLT vol → GLD vol?"),
    ]

    # Also test VIX → each asset
    vix_pairs = [
        ("VIX", "GLD", "VIX → GLD vol?"),
        ("VIX", "TLT", "VIX → TLT vol?"),
        ("VIX", "EEM", "VIX → EEM vol?"),
        ("VIX", "QQQ", "VIX → QQQ vol?"),
    ]

    granger_results = {}
    for cause, effect, desc in granger_pairs + vix_pairs:
        cause_series = rv_with_vix[cause] if cause in rv_with_vix.columns else rv_assets.get(cause)
        effect_series = rv_assets[effect] if effect in rv_assets.columns else None

        if cause_series is None or effect_series is None:
            continue

        key = f"{cause}_to_{effect}"
        gc = granger_causality_test(effect_series, cause_series, max_lag=GRANGER_MAX_LAG)
        granger_results[key] = gc

        # Print summary
        best_lag = min(gc, key=lambda l: gc[l]["p_value"])
        best = gc[best_lag]
        sig = "***" if best["p_value"] < 0.01 else "**" if best["p_value"] < 0.05 else "*" if best["p_value"] < 0.10 else ""
        print(f"  {desc:30s} Best lag={best_lag}: F={best['f_stat']:8.2f}, p={best['p_value']:.6f} {sig}")

    # ── Step 3: VAR Model with AIC ──
    print("\n" + "=" * 70)
    print("Section 2: VAR Optimal Lag Selection (AIC)")
    print("=" * 70)

    # VAR for equity vol block
    var_data = rv_assets[["SPY", "GLD", "TLT"]].dropna()
    best_lag, aic_table = var_model_aic(var_data, max_lag=10)
    print(f"  SPY-GLD-TLT VAR: Optimal lag = {best_lag}")
    for lag, aic in sorted(aic_table.items()):
        marker = " ← best" if lag == best_lag else ""
        print(f"    Lag {lag}: AIC = {aic:.4f}{marker}")

    var_results = {
        "spy_gld_tlt": {
            "optimal_lag": best_lag,
            "aic_table": aic_table,
        }
    }

    # Full 5-asset VAR
    var_data_5 = rv_assets.dropna()
    best_lag_5, aic_table_5 = var_model_aic(var_data_5, max_lag=10)
    print(f"\n  Full 5-asset VAR: Optimal lag = {best_lag_5}")
    var_results["full_5_asset"] = {
        "optimal_lag": best_lag_5,
        "aic_table": aic_table_5,
    }

    # ── Step 4: Cross-Correlation Analysis ──
    print("\n" + "=" * 70)
    print("Section 3: Lead-Lag Cross-Correlation (Vol Changes)")
    print("=" * 70)

    xcorr_results = cross_correlation_analysis(rv_with_vix, max_lag=GRANGER_MAX_LAG)

    for pair, data in xcorr_results.items():
        print(f"  {pair:20s}: peak lag={data['peak_lag']:+d}, corr={data['peak_correlation']:+.4f}  ({data['interpretation']})")

    # ── Step 5: Impulse Response ──
    print("\n" + "=" * 70)
    print("Section 4: Impulse Response (SPY vol shock → other assets)")
    print("=" * 70)

    irf_results = impulse_response_analysis(rv_assets, shock_asset="SPY")

    for asset, horizons in irf_results.items():
        print(f"\n  SPY shock → {asset}:")
        for h, vals in horizons.items():
            sig = "***" if vals["p_value"] < 0.01 else "**" if vals["p_value"] < 0.05 else ""
            print(f"    {h}: β={vals['beta']:+.4f}, t={vals['t_stat']:+.2f}, R²={vals['r_squared']:.4f} {sig}")

    # VIX as shock source too
    irf_vix = impulse_response_analysis(rv_with_vix, shock_asset="VIX", response_assets=["SPY", "GLD", "TLT", "EEM", "QQQ"])

    print(f"\n  VIX shock → assets:")
    for asset, horizons in irf_vix.items():
        h1 = horizons.get("h1", {})
        if h1:
            sig = "***" if h1["p_value"] < 0.01 else "**" if h1["p_value"] < 0.05 else ""
            print(f"    → {asset}: β={h1['beta']:+.4f}, t={h1['t_stat']:+.2f} {sig}")

    # ── Step 6: Regime Analysis ──
    print("\n" + "=" * 70)
    print("Section 5: Regime-Dependent Spillover")
    print("=" * 70)

    regime_results = run_regime_analysis(rv_assets, returns)

    for regime, data in regime_results.items():
        print(f"\n  {regime} (n={data['n_obs']}):")
        if "spy_to_gld" in data:
            for lag, vals in data["spy_to_gld"].items():
                sig = "***" if vals["p_value"] < 0.01 else "**" if vals["p_value"] < 0.05 else ""
                print(f"    SPY→GLD lag={lag}: F={vals['f_stat']:8.2f}, p={vals['p_value']:.4f} {sig}")

    # ── Step 7: Practical VT Test ──
    print("\n" + "=" * 70)
    print("Section 6: Practical VT Portfolio Test (OOS: {})".format(OOS_START))
    print("=" * 70)

    vt_results = practical_vt_test(closes, rv_assets, returns[TICKERS])

    print(f"\n  {'Strategy':<30s} {'Sharpe':>8s} {'MDD':>8s} {'Calmar':>8s} {'AnnRet':>8s}")
    print("  " + "-" * 70)
    for name, metrics in vt_results.items():
        if name.startswith("dm_test"):
            continue
        print(f"  {name:<30s} {metrics['sharpe']:>8.4f} {metrics['mdd']:>8.4f} {metrics['calmar']:>8.4f} {metrics['annual_return']:>8.4f}")

    if "dm_test_spillover_vs_own" in vt_results:
        dm = vt_results["dm_test_spillover_vs_own"]
        print(f"\n  DM test (spillover vs asset-specific): t={dm['dm_stat']:.4f}, p={dm['p_value']:.4f}")

    # ── Step 8: Summary statistics ──
    print("\n" + "=" * 70)
    print("Section 7: Volatility Correlation Matrix (Levels)")
    print("=" * 70)

    vol_corr = rv_assets.corr()
    print("\n  Realized Vol Correlation Matrix:")
    print(vol_corr.round(3).to_string(float_format=lambda x: f"{x:+.3f}"))

    vol_change_corr = rv_assets.diff().corr()
    print("\n  Vol-Change Correlation Matrix:")
    print(vol_change_corr.round(3).to_string(float_format=lambda x: f"{x:+.3f}"))

    # ── Compile results ──
    # Count significant Granger tests
    sig_count = 0
    total_tests = 0
    for pair, lags in granger_results.items():
        for lag, vals in lags.items():
            total_tests += 1
            if vals["significant_5pct"]:
                sig_count += 1

    # Key finding summary
    key_findings = []

    # Check SPY → GLD
    spy_gld = granger_results.get("SPY_to_GLD", {})
    spy_gld_sig = any(v["significant_5pct"] for v in spy_gld.values())
    key_findings.append(f"SPY vol → GLD vol Granger causality: {'YES' if spy_gld_sig else 'NO'}")

    # Check SPY → TLT
    spy_tlt = granger_results.get("SPY_to_TLT", {})
    spy_tlt_sig = any(v["significant_5pct"] for v in spy_tlt.values())
    key_findings.append(f"SPY vol → TLT vol Granger causality: {'YES' if spy_tlt_sig else 'NO'}")

    # Check VIX → GLD
    vix_gld = granger_results.get("VIX_to_GLD", {})
    vix_gld_sig = any(v["significant_5pct"] for v in vix_gld.values())
    key_findings.append(f"VIX → GLD vol Granger causality: {'YES' if vix_gld_sig else 'NO'}")

    # VT practical value
    baseline_sharpe = vt_results.get("asset_specific_vt", {}).get("sharpe", 0)
    spillover_sharpe = vt_results.get("spillover_informed_vt", {}).get("sharpe", 0)
    sharpe_diff = spillover_sharpe - baseline_sharpe
    key_findings.append(f"Spillover VT Sharpe improvement: {sharpe_diff:+.4f}")

    dm_test = vt_results.get("dm_test_spillover_vs_own", {})
    if dm_test:
        key_findings.append(f"DM test p-value: {dm_test.get('p_value', 'N/A')}")

    print("\n" + "=" * 70)
    print("KEY FINDINGS")
    print("=" * 70)
    for f in key_findings:
        print(f"  • {f}")

    # ── Save results ──
    experiment = {
        "experiment_id": "vol_spillover_20260321",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "title": "Cross-Asset Volatility Spillover: Does SPY Vol Predict GLD/TLT Vol?",
        "proposed_by": "用戶",
        "executed_by": "Claude",
        "methodology": {
            "realized_vol": f"{RV_WINDOW}-day rolling std of log returns, annualized",
            "granger_test": f"F-test with lags 1-{GRANGER_MAX_LAG}",
            "var_model": "AIC lag selection, up to 10 lags",
            "cross_correlation": f"Vol-change cross-correlation at lags ±{GRANGER_MAX_LAG}",
            "impulse_response": "OLS regression of cumulative vol response on vol shock",
            "oos_period": f"{OOS_START} onwards",
            "data_range": f"{closes.index[0].strftime('%Y-%m-%d')} to {closes.index[-1].strftime('%Y-%m-%d')}",
            "n_observations": int(len(closes)),
        },
        "section_1_granger_causality": granger_results,
        "section_2_var_lag_selection": var_results,
        "section_3_cross_correlation": xcorr_results,
        "section_4_impulse_response": {
            "spy_shock": irf_results,
            "vix_shock": irf_vix,
        },
        "section_5_regime_analysis": regime_results,
        "section_6_practical_vt": vt_results,
        "section_7_correlation_matrices": {
            "vol_level_corr": {
                f"{a}_{b}": round(float(vol_corr.loc[a, b]), 4)
                for a in vol_corr.index for b in vol_corr.columns
            },
            "vol_change_corr": {
                f"{a}_{b}": round(float(vol_change_corr.loc[a, b]), 4)
                for a in vol_change_corr.index for b in vol_change_corr.columns
            },
        },
        "key_findings": key_findings,
        "conclusion": "",  # filled below
    }

    # Generate conclusion
    conclusions = []
    if spy_gld_sig:
        conclusions.append("SPY vol Granger-causes GLD vol — equity stress propagates to gold volatility.")
    else:
        conclusions.append("SPY vol does NOT Granger-cause GLD vol — gold vol is largely independent.")

    if spy_tlt_sig:
        conclusions.append("SPY vol Granger-causes TLT vol — equity-bond vol linkage exists.")
    else:
        conclusions.append("SPY vol does NOT Granger-cause TLT vol — bond vol is independent of equity vol.")

    if dm_test and not dm_test.get("significant_5pct", False):
        conclusions.append("Vol spillover does NOT improve portfolio VT (DM test insignificant).")
        conclusions.append("Practical implication: asset-specific VT is sufficient; cross-asset vol info adds no value.")
    elif dm_test and dm_test.get("significant_5pct", False):
        conclusions.append("Vol spillover DOES improve portfolio VT (DM test significant).")

    experiment["conclusion"] = " ".join(conclusions)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(experiment, f, indent=2, default=str, ensure_ascii=False)

    print(f"\n  Results saved to {OUTPUT_FILE}")
    print(f"\n  Conclusion: {experiment['conclusion']}")

    return experiment


if __name__ == "__main__":
    main()
