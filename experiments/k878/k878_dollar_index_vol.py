#!/usr/bin/env python3
"""
K878: US Dollar Index (DXY) as Equity Volatility Predictor

Research question: Does DXY add predictive power for SPY realized vol beyond VIX?
- Strong dollar ↔ risk-off (capital flows to USD safety)
- DXY spikes during crises (2008 GFC, 2020 COVID, 2022 rate hikes)
- VIX sufficiency confirmed 27 times — does DXY add anything?

Data: yfinance — DX-Y.NYB (USD Index), SPY, ^VIX
Period: 2005-01 to 2026-04
IS: 2005–2018, OOS: 2019–2026

Methodology:
  1. DXY variables: level, 22d change, 22d vol, z-score (252d)
  2. Target: forward 22d SPY realized vol (annualized)
  3. Models (all with signal.shift(1) — no lookahead):
     a. VIX only
     b. VIX + DXY_change
     c. VIX + DXY_vol
     d. DXY only (no VIX)
  4. QLIKE + MSE + DM test (Harvey |t|>3.0) + Spearman rank corr
  5. Lead-lag: DXY vs VIX cross-correlation

Error log rules applied:
  - DM test: use from volpred.stats.model_evaluation import dm_test
  - signal.shift(1) enforced in code — lag verified by structure
  - Sharpe > 2x baseline = bug → but this is forecast eval, not strategy

References:
  - Harvey (2016) — t>3.0 threshold for multiple testing
  - Patton (2011) — QLIKE loss for volatility proxy robustness
  - DXY ↔ equity vol: Baur & Lucey (2010) flight-to-quality, Coudert et al. (2011)
"""

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import LinearRegression

warnings.filterwarnings("ignore")

# ── Import standard DM test ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from volpred.stats.model_evaluation import dm_test


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """QLIKE loss: realized/forecast - log(realized/forecast) - 1
    Patton (2011): robust to noisy volatility proxy.
    Lower = better.
    """
    ratio = realized / np.maximum(forecast, 1e-10)
    return ratio - np.log(np.maximum(ratio, 1e-10)) - 1


def mse_loss(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """MSE loss for volatility."""
    return (realized - forecast) ** 2


def fetch_data():
    """Fetch SPY, VIX, DXY from yfinance."""
    print("Fetching data from yfinance...")
    tickers = {"SPY": "SPY", "VIX": "^VIX", "DXY": "DX-Y.NYB"}
    data = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start="2004-06-01", end="2026-04-05",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[name] = df["Close"].dropna()
        print(f"  {name}: {len(data[name])} obs, {data[name].index[0].date()} to {data[name].index[-1].date()}")
    return data


def build_features(data: dict) -> pd.DataFrame:
    """Build feature DataFrame with proper alignment."""
    spy = data["SPY"].rename("spy_close")
    vix = data["VIX"].rename("vix")
    dxy = data["DXY"].rename("dxy")

    df = pd.concat([spy, vix, dxy], axis=1).dropna()
    print(f"  Aligned data: {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")

    # SPY returns
    df["spy_ret"] = np.log(df["spy_close"] / df["spy_close"].shift(1))

    # Forward 22d realized vol (target) — annualized
    df["fwd_rv22"] = df["spy_ret"].rolling(22).std().shift(-22) * np.sqrt(252)

    # DXY features (all lagged by 1 to avoid lookahead)
    df["dxy_level"] = df["dxy"]
    df["dxy_change_22d"] = df["dxy"].pct_change(22)  # 22d % change
    df["dxy_vol_22d"] = np.log(df["dxy"] / df["dxy"].shift(1)).rolling(22).std() * np.sqrt(252)
    df["dxy_zscore"] = (df["dxy"] - df["dxy"].rolling(252).mean()) / df["dxy"].rolling(252).std()

    # VIX (already a level, convert to annualized vol scale: VIX/100)
    df["vix_vol"] = df["vix"] / 100.0

    # *** CRITICAL: shift all predictors by 1 day to enforce no-lookahead ***
    predictor_cols = ["vix_vol", "dxy_level", "dxy_change_22d", "dxy_vol_22d", "dxy_zscore"]
    for col in predictor_cols:
        df[col] = df[col].shift(1)  # signal from t-1, target at t

    df = df.dropna()
    print(f"  After feature construction + dropna: {len(df)} obs")
    return df


def run_ols_forecast(df: pd.DataFrame, feature_cols: list, target_col: str,
                     is_end: str, oos_start: str) -> pd.Series:
    """Rolling OOS forecast using expanding-window OLS.
    IS: start to is_end. OOS: oos_start onward. Refit every 63 days.
    """
    is_mask = df.index <= is_end
    oos_mask = df.index >= oos_start

    X_is = df.loc[is_mask, feature_cols].values
    y_is = df.loc[is_mask, target_col].values
    X_oos = df.loc[oos_mask, feature_cols].values
    oos_idx = df.index[oos_mask]

    forecasts = np.full(len(oos_idx), np.nan)
    model = LinearRegression()
    last_refit = 0
    refit_interval = 63  # quarterly refit

    for i in range(len(oos_idx)):
        # Expanding window: all IS data + OOS data up to i-1
        if i == 0:
            X_train = X_is
            y_train = y_is
        else:
            X_train = np.vstack([X_is, X_oos[:i]])
            y_train = np.concatenate([y_is, df.loc[oos_idx[:i], target_col].values])

        # Refit every refit_interval days or at start
        if i == 0 or (i - last_refit) >= refit_interval:
            model.fit(X_train, y_train)
            last_refit = i

        pred = model.predict(X_oos[i:i+1])[0]
        forecasts[i] = max(pred, 0.01)  # floor at 1% vol

    return pd.Series(forecasts, index=oos_idx, name="forecast")


def cross_correlation_analysis(vix: pd.Series, dxy: pd.Series, max_lag: int = 30):
    """Compute cross-correlation between DXY changes and VIX changes."""
    dxy_ret = dxy.pct_change().dropna()
    vix_ret = vix.pct_change().dropna()
    common = dxy_ret.index.intersection(vix_ret.index)
    dxy_ret = dxy_ret.loc[common].values
    vix_ret = vix_ret.loc[common].values

    results = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            corr = np.corrcoef(dxy_ret[:-lag], vix_ret[lag:])[0, 1]
        elif lag < 0:
            corr = np.corrcoef(dxy_ret[-lag:], vix_ret[:lag])[0, 1]
        else:
            corr = np.corrcoef(dxy_ret, vix_ret)[0, 1]
        results[lag] = corr

    return results


def main():
    results = {
        "experiment_id": "K878",
        "title": "US Dollar Index (DXY) as Equity Volatility Predictor",
        "data_source": "yfinance (DX-Y.NYB, SPY, ^VIX)",
        "period": "2005-01 to 2026-04",
        "is_period": "2005-01 to 2018-12",
        "oos_period": "2019-01 to 2026-04",
        "methodology": "Expanding-window OLS, 63d refit, forward 22d RV target",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # ── Step 1: Fetch data ──
    data = fetch_data()

    # ── Step 2: Build features ──
    df = build_features(data)

    # ── Step 3: Descriptive statistics ──
    print("\n=== Descriptive Statistics ===")
    desc_cols = ["vix_vol", "dxy_change_22d", "dxy_vol_22d", "dxy_zscore", "fwd_rv22"]
    desc = df[desc_cols].describe().T
    desc["skew"] = df[desc_cols].skew()
    desc["kurtosis"] = df[desc_cols].kurtosis()
    print(desc[["mean", "std", "skew", "kurtosis"]].round(4))
    results["descriptive_stats"] = {
        col: {
            "mean": round(float(df[col].mean()), 6),
            "std": round(float(df[col].std()), 6),
            "skew": round(float(df[col].skew()), 4),
            "kurtosis": round(float(df[col].kurtosis()), 4),
        }
        for col in desc_cols
    }

    # ── Step 4: Unconditional correlations ──
    print("\n=== Unconditional Correlations with Forward 22d RV ===")
    corr_results = {}
    for col in ["vix_vol", "dxy_change_22d", "dxy_vol_22d", "dxy_zscore", "dxy_level"]:
        r_pearson = df[col].corr(df["fwd_rv22"])
        r_spearman, p_spearman = stats.spearmanr(df[col].values, df["fwd_rv22"].values)
        print(f"  {col:20s}: Pearson={r_pearson:.4f}, Spearman={r_spearman:.4f} (p={p_spearman:.4e})")
        corr_results[col] = {
            "pearson": round(float(r_pearson), 4),
            "spearman": round(float(r_spearman), 4),
            "spearman_pvalue": round(float(p_spearman), 6),
        }
    results["unconditional_correlations"] = corr_results

    # ── Step 5: DXY ↔ VIX cross-correlation (lead-lag) ──
    print("\n=== DXY ↔ VIX Cross-Correlation (Lead-Lag) ===")
    xcorr = cross_correlation_analysis(data["VIX"], data["DXY"], max_lag=22)
    # Find peak
    peak_lag = max(xcorr, key=lambda k: abs(xcorr[k]))
    peak_corr = xcorr[peak_lag]
    print(f"  Peak |correlation|: lag={peak_lag}, corr={peak_corr:.4f}")
    print(f"  Lag 0: {xcorr[0]:.4f}")
    print(f"  DXY leads VIX (lag +1 to +5): {[round(xcorr[i],4) for i in range(1,6)]}")
    print(f"  VIX leads DXY (lag -1 to -5): {[round(xcorr[i],4) for i in range(-1,-6,-1)]}")
    results["cross_correlation"] = {
        "peak_lag": int(peak_lag),
        "peak_corr": round(float(peak_corr), 4),
        "lag_0": round(float(xcorr[0]), 4),
        "dxy_leads_vix": {str(i): round(float(xcorr[i]), 4) for i in range(1, 6)},
        "vix_leads_dxy": {str(i): round(float(xcorr[i]), 4) for i in range(-1, -6, -1)},
    }

    # ── Step 6: Define models and run OOS forecasts ──
    print("\n=== OOS Forecast Models ===")
    is_end = "2018-12-31"
    oos_start = "2019-01-02"

    models = {
        "A_vix_only": ["vix_vol"],
        "B_vix_dxy_change": ["vix_vol", "dxy_change_22d"],
        "C_vix_dxy_vol": ["vix_vol", "dxy_vol_22d"],
        "D_dxy_only": ["dxy_change_22d", "dxy_vol_22d", "dxy_zscore"],
        "E_vix_dxy_full": ["vix_vol", "dxy_change_22d", "dxy_vol_22d", "dxy_zscore"],
    }

    forecasts = {}
    for name, features in models.items():
        print(f"  Running model {name} ({features})...")
        fc = run_ols_forecast(df, features, "fwd_rv22", is_end, oos_start)
        forecasts[name] = fc
        print(f"    OOS obs: {len(fc)}, mean forecast: {fc.mean():.4f}")

    # Get common OOS realized vol
    oos_mask = df.index >= oos_start
    common_idx = df.index[oos_mask]
    for name in forecasts:
        common_idx = common_idx.intersection(forecasts[name].index)

    realized = df.loc[common_idx, "fwd_rv22"].values
    oos_n = len(realized)
    print(f"\n  Common OOS observations: {oos_n}")
    results["oos_n"] = oos_n

    # ── Step 7: Evaluate — QLIKE, MSE, R², Spearman ──
    print("\n=== OOS Evaluation ===")
    print(f"{'Model':25s} {'QLIKE':>10s} {'MSE':>12s} {'R²_oos':>10s} {'Spearman':>10s} {'Spearman_p':>12s}")
    print("-" * 85)

    eval_results = {}
    for name in models:
        fc = forecasts[name].loc[common_idx].values

        ql = float(np.mean(qlike_loss(realized, fc)))
        mse = float(np.mean(mse_loss(realized, fc)))

        # OOS R² (vs mean benchmark)
        ss_res = np.sum((realized - fc) ** 2)
        ss_tot = np.sum((realized - np.mean(realized)) ** 2)
        r2_oos = 1 - ss_res / ss_tot

        sp_corr, sp_p = stats.spearmanr(realized, fc)

        print(f"  {name:23s} {ql:10.6f} {mse:12.6f} {r2_oos:10.4f} {sp_corr:10.4f} {sp_p:12.4e}")

        eval_results[name] = {
            "qlike": round(ql, 6),
            "mse": round(mse, 6),
            "r2_oos": round(float(r2_oos), 4),
            "spearman": round(float(sp_corr), 4),
            "spearman_pvalue": round(float(sp_p), 6),
        }

    results["oos_evaluation"] = eval_results

    # ── Step 8: Pairwise DM tests (Harvey |t|>3.0) ──
    print("\n=== Pairwise DM Tests (QLIKE loss, Harvey threshold |t|>3.0) ===")
    print(f"{'Comparison':45s} {'DM_t':>10s} {'p-value':>10s} {'Significant':>12s}")
    print("-" * 80)

    dm_results = {}
    baseline = "A_vix_only"
    for name in models:
        if name == baseline:
            continue
        fc_base = forecasts[baseline].loc[common_idx].values
        fc_alt = forecasts[name].loc[common_idx].values

        loss_base = qlike_loss(realized, fc_base)
        loss_alt = qlike_loss(realized, fc_alt)

        t_stat, p_val = dm_test(loss_base, loss_alt, h=22)
        sig = "YES" if abs(t_stat) > 3.0 else "no"
        direction = "alt better" if t_stat > 0 else "base better"
        label = f"{baseline} vs {name}"
        print(f"  {label:43s} {t_stat:10.4f} {p_val:10.4e} {sig:>12s} ({direction})")

        dm_results[label] = {
            "dm_t": round(float(t_stat), 4),
            "p_value": round(float(p_val), 6),
            "significant_harvey": abs(t_stat) > 3.0,
            "direction": direction,
        }

    # Also: D_dxy_only vs A_vix_only (is DXY alone viable?)
    fc_dxy = forecasts["D_dxy_only"].loc[common_idx].values
    fc_vix = forecasts["A_vix_only"].loc[common_idx].values
    loss_dxy = qlike_loss(realized, fc_dxy)
    loss_vix = qlike_loss(realized, fc_vix)
    t_stat, p_val = dm_test(loss_dxy, loss_vix, h=22)
    label = "D_dxy_only vs A_vix_only (standalone)"
    sig = "YES" if abs(t_stat) > 3.0 else "no"
    direction = "DXY better" if t_stat < 0 else "VIX better"
    print(f"  {label:43s} {t_stat:10.4f} {p_val:10.4e} {sig:>12s} ({direction})")
    dm_results[label] = {
        "dm_t": round(float(t_stat), 4),
        "p_value": round(float(p_val), 6),
        "significant_harvey": abs(t_stat) > 3.0,
        "direction": direction,
    }

    results["dm_tests"] = dm_results

    # ── Step 9: Regime analysis — does DXY help more during crises? ──
    print("\n=== Regime Analysis: DXY Contribution During High-Vol Periods ===")
    oos_vix = df.loc[common_idx, "vix_vol"].values
    vix_median = np.median(oos_vix)
    high_vol = oos_vix >= vix_median
    low_vol = ~high_vol

    regime_results = {}
    for regime_name, mask in [("high_vol", high_vol), ("low_vol", low_vol)]:
        n_regime = int(np.sum(mask))
        realized_r = realized[mask]
        fc_vix_r = forecasts["A_vix_only"].loc[common_idx].values[mask]
        fc_combo_r = forecasts["E_vix_dxy_full"].loc[common_idx].values[mask]

        ql_vix = float(np.mean(qlike_loss(realized_r, fc_vix_r)))
        ql_combo = float(np.mean(qlike_loss(realized_r, fc_combo_r)))
        improvement_pct = (ql_vix - ql_combo) / ql_vix * 100 if ql_vix != 0 else 0

        sp_vix, _ = stats.spearmanr(realized_r, fc_vix_r)
        sp_combo, _ = stats.spearmanr(realized_r, fc_combo_r)

        print(f"  {regime_name} (n={n_regime}):")
        print(f"    VIX-only QLIKE: {ql_vix:.6f}, Spearman: {sp_vix:.4f}")
        print(f"    VIX+DXY QLIKE:  {ql_combo:.6f}, Spearman: {sp_combo:.4f}")
        print(f"    QLIKE improvement: {improvement_pct:.2f}%")

        regime_results[regime_name] = {
            "n": n_regime,
            "vix_only_qlike": round(ql_vix, 6),
            "vix_dxy_full_qlike": round(ql_combo, 6),
            "qlike_improvement_pct": round(improvement_pct, 2),
            "vix_only_spearman": round(float(sp_vix), 4),
            "vix_dxy_full_spearman": round(float(sp_combo), 4),
        }

    results["regime_analysis"] = regime_results

    # ── Step 10: IS R² (sanity check — IS should be better than OOS) ──
    print("\n=== IS Fit (Sanity Check) ===")
    is_mask = df.index <= is_end
    X_is = df.loc[is_mask]
    y_is = X_is["fwd_rv22"].values

    is_r2 = {}
    for name, features in models.items():
        model = LinearRegression()
        model.fit(X_is[features].values, y_is)
        pred = model.predict(X_is[features].values)
        ss_res = np.sum((y_is - pred) ** 2)
        ss_tot = np.sum((y_is - np.mean(y_is)) ** 2)
        r2 = 1 - ss_res / ss_tot
        print(f"  {name:25s}: IS R² = {r2:.4f}")
        is_r2[name] = round(float(r2), 4)

    results["is_r_squared"] = is_r2

    # ── Step 11: Incremental F-test (does DXY add to VIX?) ──
    print("\n=== Incremental F-test: DXY Features Beyond VIX ===")
    # Restricted: VIX only. Unrestricted: VIX + all DXY
    n_is = len(y_is)
    r2_restricted = is_r2["A_vix_only"]
    r2_unrestricted = is_r2["E_vix_dxy_full"]
    k_restricted = 1  # VIX only
    k_unrestricted = 4  # VIX + 3 DXY features
    df_num = k_unrestricted - k_restricted
    df_den = n_is - k_unrestricted - 1

    f_stat = ((r2_unrestricted - r2_restricted) / df_num) / ((1 - r2_unrestricted) / df_den)
    f_pval = 1 - stats.f.cdf(f_stat, df_num, df_den)
    print(f"  F-statistic: {f_stat:.4f}")
    print(f"  p-value: {f_pval:.4e}")
    print(f"  Significant at 1%: {'YES' if f_pval < 0.01 else 'no'}")

    results["incremental_f_test"] = {
        "f_statistic": round(float(f_stat), 4),
        "p_value": round(float(f_pval), 6),
        "df_numerator": df_num,
        "df_denominator": df_den,
        "r2_restricted": r2_restricted,
        "r2_unrestricted": r2_unrestricted,
        "significant_1pct": f_pval < 0.01,
    }

    # ── Step 12: Summary and conclusions ──
    print("\n" + "=" * 70)
    print("SUMMARY: K878 — DXY as Equity Volatility Predictor")
    print("=" * 70)

    # Best OOS model by QLIKE
    best_model = min(eval_results, key=lambda k: eval_results[k]["qlike"])
    worst_model = max(eval_results, key=lambda k: eval_results[k]["qlike"])

    vix_qlike = eval_results["A_vix_only"]["qlike"]
    best_qlike = eval_results[best_model]["qlike"]

    any_significant = any(v["significant_harvey"] for v in dm_results.values()
                         if "D_dxy_only" not in v.get("direction", ""))

    print(f"\n  Best OOS model (QLIKE): {best_model} ({best_qlike:.6f})")
    print(f"  VIX-only baseline:      A_vix_only ({vix_qlike:.6f})")
    print(f"  Improvement over VIX:   {(vix_qlike - best_qlike)/vix_qlike*100:.2f}%")
    print(f"  Any DM test significant (|t|>3.0): {any_significant}")
    print(f"  Incremental F-test significant: {f_pval < 0.01}")

    # VIX sufficiency verdict
    if not any_significant:
        verdict = "VIX SUFFICIENCY CONFIRMED (28th time): DXY does NOT significantly improve vol forecasts beyond VIX"
    else:
        verdict = "DXY ADDS SIGNIFICANT VALUE beyond VIX"

    print(f"\n  ★ VERDICT: {verdict}")

    results["summary"] = {
        "best_oos_model": best_model,
        "best_oos_qlike": best_qlike,
        "vix_baseline_qlike": vix_qlike,
        "improvement_pct": round((vix_qlike - best_qlike) / vix_qlike * 100, 2),
        "any_dm_significant": any_significant,
        "f_test_significant": f_pval < 0.01,
        "verdict": verdict,
    }

    results["conclusions"] = [
        f"DXY cross-correlation with VIX at lag 0: {xcorr[0]:.4f} (contemporaneous, not predictive)",
        f"Best OOS model: {best_model} (QLIKE={best_qlike:.6f})",
        f"VIX-only QLIKE: {vix_qlike:.6f}",
        f"No DM test exceeds Harvey |t|>3.0 threshold" if not any_significant else "DXY significantly improves forecasts",
        f"DXY alone (model D) vs VIX: {dm_results.get('D_dxy_only vs A_vix_only (standalone)', {}).get('dm_t', 'N/A')}",
        f"IS incremental F-test: F={f_stat:.2f}, p={f_pval:.4e}",
    ]

    results["limitations"] = [
        "OLS linear models only — nonlinear DXY effects not tested",
        "Forward 22d RV uses overlapping windows (autocorrelation in target)",
        "DXY is a basket (EUR 57.6%, JPY 13.6%, GBP 11.9%) — individual FX may differ",
        "Post-2022 USD strength may be regime-specific (rate hike cycle)",
        "No intraday DXY data — daily only",
    ]

    results["references"] = [
        "Harvey (2016) '...and the Cross-Section of Expected Returns' — t>3.0 threshold",
        "Patton (2011) 'Volatility forecast comparison using imperfect volatility proxies' — QLIKE robustness",
        "Baur & Lucey (2010) 'Is gold a hedge or a safe haven?' — flight-to-quality dynamics",
        "Coudert, Couharde & Mignon (2011) 'Does euro or dollar pegging impact the real exchange rate?'",
    ]

    # ── Save results ──
    output_path = Path(__file__).parent / "k878_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to {output_path}")

    return results


if __name__ == "__main__":
    main()
