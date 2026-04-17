"""K359: Quantile Regression for Volatility — Predicting Tail Risk Directly

Standard volatility regression predicts the MEAN of realized variance.
But for risk management, EXTREME vol (the 90th percentile) matters more.

Quantile regression (Koenker & Bassett 1978) estimates conditional quantiles:
  Q_τ(Y|X) = X'β(τ)
allowing coefficients to VARY across quantiles.

Key questions:
1. Does VIX predict extreme vol (τ=0.90) better than mean vol (OLS)?
2. Do coefficients change across quantiles? (quantile-varying effect)
3. Is the τ=0.90 forecast well-calibrated OOS?
4. Can a quantile-based VT strategy beat standard VT?

Data: SPY + VIX daily from yfinance, 2005-2024.
Method: Linear quantile regression via statsmodels.

Related: K173 Hill tail index (r=-0.083), K168 GARCH VoV, K351 conformal prediction.
Pre-check: ZERO prior quantile regression experiments in this project.

[提出: User, 執行: Claude]
Author: VolPred Research System
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2005-01-01"
END_DATE = "2024-12-31"
OOS_START = "2015-01-02"  # 10yr IS, 10yr OOS
QUANTILES = [0.10, 0.25, 0.50, 0.75, 0.90]
RV_WINDOW = 22  # 22-day realized vol
ROLLING_WINDOW = 1000  # rolling estimation window for OOS

# ============================================================================
# Data Download
# ============================================================================
print("=" * 70)
print("K359: Quantile Regression for Volatility Prediction")
print("=" * 70)
print(f"\nDownloading SPY and VIX data ({START_DATE} to {END_DATE})...")

spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False)
vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  SPY: {len(spy)} rows ({spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX: {len(vix)} rows ({vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')})")

# ============================================================================
# Feature Engineering
# ============================================================================
print("\nBuilding features...")

df = pd.DataFrame(index=spy.index)
df["ret"] = np.log(spy["Close"] / spy["Close"].shift(1))
df["ret_sq"] = df["ret"] ** 2
df["vix"] = vix["Close"].reindex(spy.index, method="ffill")

# Target: forward 22-day realized volatility (annualized)
df["rv_fwd_22d"] = df["ret_sq"].rolling(RV_WINDOW).sum().shift(-RV_WINDOW)
df["rv_fwd_22d_ann"] = np.sqrt(df["rv_fwd_22d"] * 252 / RV_WINDOW)  # annualized

# Features (all lagged — no look-ahead)
# 1. VIX level (divided by 100 to match vol scale)
df["f_vix"] = df["vix"] / 100.0

# 2. Lagged 22-day realized vol
df["rv_past_22d"] = np.sqrt(df["ret_sq"].rolling(RV_WINDOW).sum() * 252 / RV_WINDOW)
df["f_rv_lag"] = df["rv_past_22d"]

# 3. Range ratio (High-Low)/Close as intraday vol proxy
df["range_ratio"] = (spy["High"] - spy["Low"]) / spy["Close"]
df["f_range"] = df["range_ratio"].rolling(5).mean()  # 5-day smoothed

# 4. VIX change (momentum)
df["f_vix_chg"] = df["vix"].pct_change(5)  # 5-day VIX change

# Drop NaN
df = df.dropna(subset=["rv_fwd_22d_ann", "f_vix", "f_rv_lag", "f_range", "f_vix_chg"])

print(f"  Total usable observations: {len(df)}")
print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================================
# Part 1: Full-Sample Quantile Regression
# ============================================================================
print("\n" + "=" * 70)
print("PART 1: Full-Sample Quantile Regression")
print("=" * 70)

try:
    import statsmodels.api as sm
    from statsmodels.regression.quantile_regression import QuantReg
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False
    print("WARNING: statsmodels not available, using scipy-based implementation")

Y = df["rv_fwd_22d_ann"].values
X_raw = df[["f_vix", "f_rv_lag", "f_range", "f_vix_chg"]].values
feature_names = ["VIX/100", "Lagged_RV", "Range_5d", "VIX_chg_5d"]

if HAS_STATSMODELS:
    X = sm.add_constant(X_raw)

    print(f"\nY = Forward 22d Realized Vol (annualized)")
    print(f"X = [const, VIX/100, Lagged_RV, Range_5d, VIX_chg_5d]")
    print(f"N = {len(Y)}")

    # OLS baseline
    ols_model = sm.OLS(Y, X).fit()
    print(f"\n--- OLS (Mean Regression) ---")
    print(f"  R² = {ols_model.rsquared:.4f}")
    for i, name in enumerate(["const"] + feature_names):
        print(f"  β({name}) = {ols_model.params[i]:.4f} (t={ols_model.tvalues[i]:.2f})")

    # Quantile regression at each τ
    qr_results = {}
    print(f"\n--- Quantile Regression Coefficients ---")
    header = f"{'τ':>6s} | {'Pseudo R²':>10s} | {'const':>8s} | {'VIX/100':>8s} | {'Lag_RV':>8s} | {'Range':>8s} | {'VIX_chg':>8s}"
    print(header)
    print("-" * len(header))

    for tau in QUANTILES:
        qr = QuantReg(Y, X).fit(q=tau, max_iter=5000)
        qr_results[tau] = qr

        # Pseudo R² (compare to constant-only quantile model)
        qr_null = QuantReg(Y, sm.add_constant(np.ones(len(Y)))).fit(q=tau, max_iter=5000)
        rho_tau = lambda u, t: u * (t - (u < 0).astype(float))
        loss_full = np.sum(rho_tau(qr.resid, tau))
        loss_null = np.sum(rho_tau(qr_null.resid, tau))
        pseudo_r2 = 1 - loss_full / loss_null

        params = qr.params
        print(f"  {tau:.2f} | {pseudo_r2:10.4f} | {params[0]:8.4f} | {params[1]:8.4f} | {params[2]:8.4f} | {params[3]:8.4f} | {params[4]:8.4f}")

    # ============================================================================
    # Part 2: Quantile-Varying Effects — Does VIX matter MORE for extreme vol?
    # ============================================================================
    print("\n" + "=" * 70)
    print("PART 2: Quantile-Varying VIX Effect")
    print("=" * 70)

    print("\nVIX coefficient across quantiles:")
    print(f"  {'τ':>6s} | {'β(VIX)':>10s} | {'SE':>8s} | {'t-stat':>8s} | {'p-value':>8s}")
    print("-" * 55)

    vix_betas = []
    vix_ses = []
    for tau in QUANTILES:
        qr = qr_results[tau]
        beta_vix = qr.params[1]
        se_vix = qr.bse[1]
        t_vix = qr.tvalues[1]
        p_vix = qr.pvalues[1]
        vix_betas.append(beta_vix)
        vix_ses.append(se_vix)
        print(f"  {tau:.2f} | {beta_vix:10.4f} | {se_vix:8.4f} | {t_vix:8.2f} | {p_vix:8.4f}")

    # Test: β_VIX(0.90) vs β_VIX(0.10)
    diff = vix_betas[-1] - vix_betas[0]
    se_diff = np.sqrt(vix_ses[-1]**2 + vix_ses[0]**2)  # conservative (ignores covariance)
    t_diff = diff / se_diff
    print(f"\n  β_VIX(0.90) - β_VIX(0.10) = {diff:.4f}")
    print(f"  Approximate t-stat = {t_diff:.2f}")
    print(f"  → VIX effect {'INCREASES' if diff > 0 else 'DECREASES'} for extreme vol quantiles")

    # ============================================================================
    # Part 3: OOS Quantile Forecasts + Calibration
    # ============================================================================
    print("\n" + "=" * 70)
    print("PART 3: Out-of-Sample Quantile Forecasts")
    print("=" * 70)

    oos_mask = df.index >= OOS_START
    oos_idx = np.where(oos_mask)[0]
    print(f"\n  IS: {df.index[0].strftime('%Y-%m-%d')} to {OOS_START}")
    print(f"  OOS: {OOS_START} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  OOS observations: {len(oos_idx)}")

    # Rolling OOS forecasts
    oos_forecasts = {tau: np.full(len(df), np.nan) for tau in QUANTILES}
    ols_forecasts = np.full(len(df), np.nan)

    print("\n  Running rolling OOS estimation (this may take a minute)...")

    for i, idx in enumerate(oos_idx):
        if idx < ROLLING_WINDOW:
            continue

        # Training window
        train_slice = slice(idx - ROLLING_WINDOW, idx)
        Y_train = Y[train_slice]
        X_train = X[train_slice]
        X_test = X[idx:idx+1]

        # OLS forecast
        try:
            ols_fit = sm.OLS(Y_train, X_train).fit()
            ols_forecasts[idx] = ols_fit.predict(X_test)[0]
        except Exception:
            pass

        # Quantile forecasts
        for tau in QUANTILES:
            try:
                qr_fit = QuantReg(Y_train, X_train).fit(q=tau, max_iter=3000)
                oos_forecasts[tau][idx] = qr_fit.predict(X_test)[0]
            except Exception:
                pass

        if (i + 1) % 500 == 0:
            print(f"    ... {i+1}/{len(oos_idx)} done")

    print(f"    ... {len(oos_idx)}/{len(oos_idx)} done")

    # Calibration check: P(RV > q_hat_τ) should ≈ 1-τ
    print("\n--- Calibration Check ---")
    print(f"  {'τ':>6s} | {'Expected':>10s} | {'Actual':>10s} | {'Gap':>8s} | {'Status':>10s}")
    print("-" * 55)

    calibration_results = {}
    for tau in QUANTILES:
        valid = ~np.isnan(oos_forecasts[tau]) & ~np.isnan(Y)
        if np.sum(valid) < 100:
            continue
        q_hat = oos_forecasts[tau][valid]
        y_actual = Y[valid]
        exceed_rate = np.mean(y_actual > q_hat)
        expected_rate = 1 - tau
        gap = exceed_rate - expected_rate
        status = "GOOD" if abs(gap) < 0.05 else ("OVER" if gap > 0 else "UNDER")
        calibration_results[tau] = {
            "expected": expected_rate,
            "actual": float(exceed_rate),
            "gap": float(gap)
        }
        print(f"  {tau:.2f} | {expected_rate:10.2%} | {exceed_rate:10.2%} | {gap:8.2%} | {status:>10s}")

    # OOS prediction accuracy: MAE at median vs OLS
    valid_ols = ~np.isnan(ols_forecasts) & ~np.isnan(Y)
    valid_q50 = ~np.isnan(oos_forecasts[0.50]) & ~np.isnan(Y)

    if np.sum(valid_ols) > 100 and np.sum(valid_q50) > 100:
        mae_ols = np.mean(np.abs(Y[valid_ols] - ols_forecasts[valid_ols]))
        mae_q50 = np.mean(np.abs(Y[valid_q50] - oos_forecasts[0.50][valid_q50]))
        mse_ols = np.mean((Y[valid_ols] - ols_forecasts[valid_ols])**2)
        mse_q50 = np.mean((Y[valid_q50] - oos_forecasts[0.50][valid_q50])**2)

        print(f"\n--- OOS Forecast Accuracy ---")
        print(f"  OLS   MAE = {mae_ols:.4f}  MSE = {mse_ols:.6f}")
        print(f"  QR50  MAE = {mae_q50:.4f}  MSE = {mse_q50:.6f}")

    # ============================================================================
    # Part 4: Quantile Loss Comparison across quantiles
    # ============================================================================
    print("\n--- Quantile Loss (check function) OOS ---")
    print(f"  {'τ':>6s} | {'QR Loss':>12s} | {'OLS Loss':>12s} | {'QR wins?':>10s}")
    print("-" * 55)

    ql_results = {}
    for tau in QUANTILES:
        valid = ~np.isnan(oos_forecasts[tau]) & ~np.isnan(ols_forecasts) & ~np.isnan(Y)
        if np.sum(valid) < 100:
            continue
        y = Y[valid]
        qr_pred = oos_forecasts[tau][valid]
        ols_pred = ols_forecasts[valid]

        # Check function (quantile loss)
        def quantile_loss(y, pred, tau):
            resid = y - pred
            return np.mean(np.where(resid >= 0, tau * resid, (tau - 1) * resid))

        ql_qr = quantile_loss(y, qr_pred, tau)
        ql_ols = quantile_loss(y, ols_pred, tau)
        wins = "YES" if ql_qr < ql_ols else "NO"
        ql_results[tau] = {"qr": float(ql_qr), "ols": float(ql_ols), "qr_wins": ql_qr < ql_ols}
        print(f"  {tau:.2f} | {ql_qr:12.6f} | {ql_ols:12.6f} | {wins:>10s}")

    # ============================================================================
    # Part 5: Quantile-Based VT Strategy
    # ============================================================================
    print("\n" + "=" * 70)
    print("PART 5: Quantile-Based VT Strategy")
    print("=" * 70)

    # Standard VT: 12/VIX
    df["vt_std_weight"] = (12.0 / df["vix"]).clip(0, 1)
    df["vt_std_weight_lag"] = df["vt_std_weight"].shift(1)  # lagged to avoid look-ahead
    df["ret_vt_std"] = df["vt_std_weight_lag"] * df["ret"]

    # Quantile-based VT: use τ=0.90 forecast to size position
    # Idea: when predicted extreme vol is high, reduce exposure more aggressively
    # Weight = target_vol / q90_forecast, capped at 1
    TARGET_VOL = 0.12  # 12% annual target vol

    df["q90_forecast"] = oos_forecasts[0.90]
    df["q50_forecast"] = oos_forecasts[0.50]

    # Strategy A: Use q90 for sizing (tail-risk aware)
    df["vt_q90_weight"] = (TARGET_VOL / df["q90_forecast"]).clip(0, 1)
    df["vt_q90_weight_lag"] = df["vt_q90_weight"].shift(1)
    df["ret_vt_q90"] = df["vt_q90_weight_lag"] * df["ret"]

    # Strategy B: Use q50 for sizing (median vol, should be similar to OLS)
    df["vt_q50_weight"] = (TARGET_VOL / df["q50_forecast"]).clip(0, 1)
    df["vt_q50_weight_lag"] = df["vt_q50_weight"].shift(1)
    df["ret_vt_q50"] = df["vt_q50_weight_lag"] * df["ret"]

    # Strategy C: Adaptive — use q50 normally, switch to q90 when q90/q50 ratio is high
    df["tail_ratio"] = df["q90_forecast"] / df["q50_forecast"]
    tail_threshold = df["tail_ratio"].quantile(0.75)  # top 25% tail risk regime
    df["vt_adaptive_weight"] = np.where(
        df["tail_ratio"] > tail_threshold,
        (TARGET_VOL / df["q90_forecast"]).clip(0, 1),
        (TARGET_VOL / df["q50_forecast"]).clip(0, 1)
    )
    df["vt_adaptive_weight_lag"] = df["vt_adaptive_weight"].shift(1)
    df["ret_vt_adaptive"] = df["vt_adaptive_weight_lag"] * df["ret"]

    # Buy & hold
    df["ret_bh"] = df["ret"]

    # Evaluate OOS period only
    oos_df = df[df.index >= OOS_START].dropna(subset=["ret_vt_std", "ret_vt_q90", "ret_vt_q50", "ret_vt_adaptive"])

    print(f"\n  OOS period: {oos_df.index[0].strftime('%Y-%m-%d')} to {oos_df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  OOS trading days: {len(oos_df)}")

    # Performance metrics
    def calc_metrics(returns, name):
        ann_ret = returns.mean() * 252
        ann_vol = returns.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + returns).cumprod()
        mdd = (cum / cum.cummax() - 1).min()
        calmar = ann_ret / abs(mdd) if mdd != 0 else 0
        downside_vol = returns[returns < 0].std() * np.sqrt(252)
        sortino = ann_ret / downside_vol if downside_vol > 0 else 0
        return {
            "name": name,
            "ann_return": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe),
            "mdd": float(mdd),
            "calmar": float(calmar),
            "sortino": float(sortino)
        }

    strategies = {
        "Buy & Hold": oos_df["ret_bh"],
        "12/VIX VT": oos_df["ret_vt_std"],
        "QR(τ=0.90) VT": oos_df["ret_vt_q90"],
        "QR(τ=0.50) VT": oos_df["ret_vt_q50"],
        "QR Adaptive VT": oos_df["ret_vt_adaptive"],
    }

    print(f"\n{'Strategy':>20s} | {'Return':>8s} | {'Vol':>8s} | {'Sharpe':>8s} | {'MDD':>8s} | {'Calmar':>8s} | {'Sortino':>8s}")
    print("-" * 85)

    strategy_results = {}
    for name, rets in strategies.items():
        m = calc_metrics(rets, name)
        strategy_results[name] = m
        print(f"  {name:>18s} | {m['ann_return']:7.2%} | {m['ann_vol']:7.2%} | {m['sharpe']:8.3f} | {m['mdd']:7.2%} | {m['calmar']:8.3f} | {m['sortino']:8.3f}")

    # ============================================================================
    # Part 6: Statistical Tests — DM test for Sharpe difference
    # ============================================================================
    print("\n" + "=" * 70)
    print("PART 6: Statistical Significance")
    print("=" * 70)

    # DM-like test for strategy comparison
    def dm_test_returns(r1, r2):
        """Test if two return series have significantly different Sharpe ratios."""
        d = r1 - r2
        d_mean = d.mean()
        d_se = d.std() / np.sqrt(len(d))
        t_stat = d_mean / d_se if d_se > 0 else 0
        p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=len(d)-1))
        return t_stat, p_val

    print("\n--- Sharpe Difference Tests (vs 12/VIX VT) ---")
    base = oos_df["ret_vt_std"]
    for name, rets in strategies.items():
        if name == "12/VIX VT":
            continue
        t, p = dm_test_returns(rets, base)
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else "n.s."
        print(f"  {name:>18s} vs 12/VIX: t={t:6.3f}, p={p:.4f} {sig}")

    # ============================================================================
    # Part 7: Weight Analysis
    # ============================================================================
    print("\n" + "=" * 70)
    print("PART 7: Weight Distribution Analysis")
    print("=" * 70)

    weight_cols = {
        "12/VIX": "vt_std_weight_lag",
        "QR(τ=0.90)": "vt_q90_weight_lag",
        "QR(τ=0.50)": "vt_q50_weight_lag",
        "QR Adaptive": "vt_adaptive_weight_lag"
    }

    print(f"\n{'Strategy':>15s} | {'Mean':>8s} | {'Std':>8s} | {'Min':>8s} | {'P25':>8s} | {'Median':>8s} | {'P75':>8s} | {'Max':>8s}")
    print("-" * 90)

    weight_stats = {}
    for name, col in weight_cols.items():
        w = oos_df[col].dropna()
        if len(w) == 0:
            continue
        stats = {
            "mean": float(w.mean()),
            "std": float(w.std()),
            "min": float(w.min()),
            "p25": float(w.quantile(0.25)),
            "median": float(w.median()),
            "p75": float(w.quantile(0.75)),
            "max": float(w.max()),
        }
        weight_stats[name] = stats
        print(f"  {name:>13s} | {stats['mean']:7.3f} | {stats['std']:7.3f} | {stats['min']:7.3f} | {stats['p25']:7.3f} | {stats['median']:7.3f} | {stats['p75']:7.3f} | {stats['max']:7.3f}")

    # ============================================================================
    # Part 8: Crisis Performance (COVID 2020)
    # ============================================================================
    print("\n" + "=" * 70)
    print("PART 8: Crisis Period Performance (COVID: 2020-02 to 2020-04)")
    print("=" * 70)

    crisis_start = "2020-02-19"
    crisis_end = "2020-04-30"
    crisis = oos_df[(oos_df.index >= crisis_start) & (oos_df.index <= crisis_end)]

    if len(crisis) > 20:
        print(f"\n  Crisis period: {crisis.index[0].strftime('%Y-%m-%d')} to {crisis.index[-1].strftime('%Y-%m-%d')} ({len(crisis)} days)")

        for name, col in [("Buy & Hold", "ret_bh"), ("12/VIX VT", "ret_vt_std"),
                          ("QR(τ=0.90) VT", "ret_vt_q90"), ("QR Adaptive VT", "ret_vt_adaptive")]:
            crisis_ret = crisis[col].dropna()
            if len(crisis_ret) == 0:
                continue
            cum = (1 + crisis_ret).cumprod()
            crisis_mdd = (cum / cum.cummax() - 1).min()
            crisis_total = cum.iloc[-1] - 1
            print(f"  {name:>18s}: Total={crisis_total:7.2%}, MDD={crisis_mdd:7.2%}")

    # Average weight during crisis
    print("\n  Average weights during crisis:")
    for name, col in weight_cols.items():
        w = crisis[col].dropna()
        if len(w) > 0:
            print(f"    {name:>15s}: {w.mean():.3f}")

    # ============================================================================
    # Part 9: Interquantile Range as Uncertainty
    # ============================================================================
    print("\n" + "=" * 70)
    print("PART 9: Interquantile Range as Uncertainty Measure")
    print("=" * 70)

    df["iqr_90_10"] = oos_forecasts[0.90] - np.array([oos_forecasts[0.10][i] if not np.isnan(oos_forecasts[0.10][i]) else np.nan for i in range(len(df))])
    # Fix: properly compute using the arrays
    f90 = pd.Series(oos_forecasts[0.90], index=df.index)
    f10 = pd.Series(oos_forecasts[0.10], index=df.index)
    f50 = pd.Series(oos_forecasts[0.50], index=df.index)

    iqr = f90 - f10
    iqr_oos = iqr[oos_mask].dropna()

    if len(iqr_oos) > 100:
        print(f"\n  IQR (Q90-Q10) statistics:")
        print(f"    Mean = {iqr_oos.mean():.4f}")
        print(f"    Std  = {iqr_oos.std():.4f}")
        print(f"    Min  = {iqr_oos.min():.4f}")
        print(f"    Max  = {iqr_oos.max():.4f}")

        # Does high IQR predict larger forecast errors?
        abs_error_50 = np.abs(Y - oos_forecasts[0.50])
        abs_error_s = pd.Series(abs_error_50, index=df.index)

        valid_both = ~iqr.isna() & ~abs_error_s.isna() & oos_mask
        if valid_both.sum() > 100:
            corr_iqr_err = np.corrcoef(iqr[valid_both], abs_error_s[valid_both])[0, 1]
            print(f"\n  Corr(IQR, |forecast error|) = {corr_iqr_err:.4f}")
            print(f"  → IQR {'IS' if corr_iqr_err > 0.1 else 'is NOT'} a useful uncertainty proxy")

    # ============================================================================
    # Part 10: Formal Quantile Equality Test (Wald test)
    # ============================================================================
    print("\n" + "=" * 70)
    print("PART 10: Formal Test of Coefficient Equality Across Quantiles")
    print("=" * 70)

    # Compare β(VIX) at τ=0.10 vs τ=0.90 using bootstrap
    print("\n  Bootstrap test: β_VIX(0.90) = β_VIX(0.10)?")
    print("  Running 1000 bootstrap replications...")

    n_boot = 1000
    n_obs = len(Y)
    boot_diffs = []

    np.random.seed(42)
    for b in range(n_boot):
        idx_boot = np.random.choice(n_obs, size=n_obs, replace=True)
        Y_b = Y[idx_boot]
        X_b = X[idx_boot]
        try:
            qr90 = QuantReg(Y_b, X_b).fit(q=0.90, max_iter=2000)
            qr10 = QuantReg(Y_b, X_b).fit(q=0.10, max_iter=2000)
            boot_diffs.append(qr90.params[1] - qr10.params[1])
        except Exception:
            pass

        if (b + 1) % 250 == 0:
            print(f"    ... {b+1}/{n_boot} done")

    boot_diffs = np.array(boot_diffs)
    if len(boot_diffs) > 100:
        point_diff = vix_betas[-1] - vix_betas[0]
        boot_se = boot_diffs.std()
        boot_t = point_diff / boot_se
        boot_p = 2 * (1 - sp_stats.norm.cdf(abs(boot_t)))

        ci_lo = np.percentile(boot_diffs, 2.5)
        ci_hi = np.percentile(boot_diffs, 97.5)

        print(f"\n  Point estimate: β_VIX(0.90) - β_VIX(0.10) = {point_diff:.4f}")
        print(f"  Bootstrap SE = {boot_se:.4f}")
        print(f"  Bootstrap t = {boot_t:.3f}")
        print(f"  Bootstrap p = {boot_p:.4f}")
        print(f"  95% CI = [{ci_lo:.4f}, {ci_hi:.4f}]")
        print(f"  → {'REJECT' if boot_p < 0.05 else 'FAIL TO REJECT'} equality at 5% level")
        print(f"  → VIX effect {'varies significantly' if boot_p < 0.05 else 'does NOT vary significantly'} across quantiles")

    # ============================================================================
    # Summary & Save Results
    # ============================================================================
    print("\n" + "=" * 70)
    print("SUMMARY: K359 Quantile Regression for Vol")
    print("=" * 70)

    results = {
        "experiment": "K359",
        "title": "Quantile Regression for Volatility — Predicting Tail Risk Directly",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data": {
            "asset": "SPY",
            "source": "yfinance",
            "period": f"{START_DATE} to {END_DATE}",
            "oos_start": OOS_START,
            "n_obs": len(df),
            "n_oos": int(len(oos_df)) if len(oos_df) > 0 else 0
        },
        "methodology": {
            "model": "Linear Quantile Regression (Koenker & Bassett 1978)",
            "target": "Forward 22d Realized Vol (annualized)",
            "features": feature_names,
            "quantiles": QUANTILES,
            "rolling_window": ROLLING_WINDOW,
            "implementation": "statsmodels QuantReg"
        },
        "full_sample": {
            "ols_r2": float(ols_model.rsquared),
            "vix_coefficients": {str(tau): float(vix_betas[i]) for i, tau in enumerate(QUANTILES)},
        },
        "calibration": calibration_results,
        "quantile_loss": ql_results,
        "strategy_performance": strategy_results,
        "weight_stats": weight_stats,
        "bootstrap_test": {
            "null": "β_VIX(0.90) = β_VIX(0.10)",
            "point_diff": float(point_diff) if len(boot_diffs) > 100 else None,
            "bootstrap_t": float(boot_t) if len(boot_diffs) > 100 else None,
            "bootstrap_p": float(boot_p) if len(boot_diffs) > 100 else None,
            "n_boot": int(len(boot_diffs))
        }
    }

    # Key findings summary
    print("\n1. QUANTILE-VARYING VIX EFFECT:")
    print(f"   β_VIX(0.10) = {vix_betas[0]:.4f}")
    print(f"   β_VIX(0.50) = {vix_betas[2]:.4f}")
    print(f"   β_VIX(0.90) = {vix_betas[-1]:.4f}")
    if len(boot_diffs) > 100:
        print(f"   Difference test p = {boot_p:.4f} → {'Significant' if boot_p < 0.05 else 'Not significant'}")

    print(f"\n2. OOS CALIBRATION:")
    for tau in QUANTILES:
        if tau in calibration_results:
            cr = calibration_results[tau]
            print(f"   τ={tau:.2f}: Expected {cr['expected']:.0%} exceedance, Actual {cr['actual']:.1%} (gap={cr['gap']:+.1%})")

    print(f"\n3. STRATEGY COMPARISON (OOS):")
    for name in ["Buy & Hold", "12/VIX VT", "QR(τ=0.90) VT", "QR Adaptive VT"]:
        if name in strategy_results:
            s = strategy_results[name]
            print(f"   {name:>18s}: Sharpe={s['sharpe']:.3f}, MDD={s['mdd']:.1%}")

    q90_sharpe = strategy_results.get("QR(τ=0.90) VT", {}).get("sharpe", 0)
    std_sharpe = strategy_results.get("12/VIX VT", {}).get("sharpe", 0)
    print(f"\n4. CONCLUSION:")
    if q90_sharpe > std_sharpe + 0.05:
        print(f"   ★ QR(τ=0.90) VT beats 12/VIX VT by {q90_sharpe - std_sharpe:.3f} Sharpe")
    elif q90_sharpe < std_sharpe - 0.05:
        print(f"   12/VIX VT beats QR(τ=0.90) VT by {std_sharpe - q90_sharpe:.3f} Sharpe")
    else:
        print(f"   QR(τ=0.90) VT ≈ 12/VIX VT (difference < 0.05 Sharpe)")

    # Save results
    out_path = Path(__file__).parent / "k359_quantile_reg_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

else:
    # Fallback: manual quantile regression using scipy minimize
    print("\n  Using scipy-based quantile regression (statsmodels not available)...")

    def quantile_loss_fn(beta, X, Y, tau):
        resid = Y - X @ beta
        return np.sum(np.where(resid >= 0, tau * resid, (tau - 1) * resid))

    from scipy.optimize import minimize

    X = np.column_stack([np.ones(len(Y)), X_raw])

    # OLS for comparison
    beta_ols = np.linalg.lstsq(X, Y, rcond=None)[0]
    Y_hat_ols = X @ beta_ols
    ss_res = np.sum((Y - Y_hat_ols)**2)
    ss_tot = np.sum((Y - Y.mean())**2)
    r2_ols = 1 - ss_res / ss_tot

    print(f"\n  OLS R² = {r2_ols:.4f}")

    for tau in QUANTILES:
        res = minimize(quantile_loss_fn, beta_ols, args=(X, Y, tau), method="Nelder-Mead",
                       options={"maxiter": 10000})
        beta_qr = res.x
        print(f"  τ={tau:.2f}: β_VIX = {beta_qr[1]:.4f}")

    print("\n  Install statsmodels for full analysis: pip install statsmodels")

print("\n" + "=" * 70)
print("K359 COMPLETE")
print("=" * 70)
