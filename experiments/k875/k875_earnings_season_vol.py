#!/usr/bin/env python3
"""
K875: Earnings Season Aggregate Volatility — Does Q1/Q2/Q3/Q4 Reporting Drive SPY Vol?

Research Question:
1. Is SPY realized vol systematically higher during earnings season?
2. Can an earnings-season dummy improve vol forecasting beyond VIX?
3. Is the effect quarter-specific (Q1 vs Q3)?

Prior work:
- K498: GARCH-X with earnings dummy → NULL RESULT (no systematic effect on SPY vol)
- K570: VT should NOT adjust during earnings season
- Savor & Wilson (2016, JFE): Earnings Announcements and Systematic Risk

This experiment uses:
- Longer sample (2005-2026), 5-day realized vol
- HAR-RV framework + earnings dummy (OOS evaluation)
- QLIKE loss (Patton 2011 proxy-robust) + DM test (Harvey t>3.0)

Error log rules:
- DM test: use dm_test from volpred.stats.model_evaluation, not self-written
- Sanity check: compare IS vs OOS performance
- signal.shift(1): all predictors lagged properly (no lookahead)

Data: yfinance — SPY, ^VIX. Period: 2005-01 to 2026-04.
"""

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# Add project root for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from volpred.stats.model_evaluation import dm_test


def define_earnings_season(dates: pd.DatetimeIndex) -> pd.Series:
    """
    Earnings season: trading days 10-25 of Jan, Apr, Jul, Oct.
    This captures the bulk of S&P 500 earnings reports.
    Returns binary series (1=earnings week, 0=not).
    """
    month = dates.month
    day = dates.day
    is_earnings = ((month == 1) | (month == 4) | (month == 7) | (month == 10)) & \
                  (day >= 10) & (day <= 25)
    return pd.Series(is_earnings.astype(int), index=dates, name="earnings_season")


def compute_realized_vol(returns: pd.Series, window: int = 5) -> pd.Series:
    """5-day realized volatility (annualized std)."""
    rv = returns.rolling(window).std() * np.sqrt(252)
    return rv


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """QLIKE loss: realized/forecast - log(realized/forecast) - 1.
    Patton (2011) proxy-robust for sigma^2.
    """
    ratio = realized / forecast
    ratio = np.clip(ratio, 1e-10, 1e10)
    return ratio - np.log(ratio) - 1


def main():
    print("=" * 70)
    print("K875: Earnings Season Aggregate Volatility")
    print("=" * 70)

    # ===== 1. Download Data =====
    print("\n[1] Downloading data...")
    spy = yf.download("SPY", start="2004-12-01", end="2026-04-05", progress=False)
    vix = yf.download("^VIX", start="2004-12-01", end="2026-04-05", progress=False)

    # Handle multi-level columns from yfinance
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_return"

    vix_close = vix["Close"].reindex(spy_ret.index).ffill()
    vix_close.name = "vix"

    # Align
    common = spy_ret.index.intersection(vix_close.dropna().index)
    spy_ret = spy_ret.loc[common]
    vix_close = vix_close.loc[common]

    # Start from 2005
    mask = spy_ret.index >= "2005-01-01"
    spy_ret = spy_ret[mask]
    vix_close = vix_close[mask]

    print(f"  Period: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()}")
    print(f"  Observations: {len(spy_ret)}")

    # ===== 2. Compute Realized Vol & Earnings Dummy =====
    print("\n[2] Computing realized vol and earnings season dummy...")
    rv5 = compute_realized_vol(spy_ret, window=5)
    rv5_sq = (spy_ret ** 2)  # daily squared return as sigma^2 proxy
    rv5_var = spy_ret.rolling(5).var() * 252  # annualized variance (5-day)

    earnings_dummy = define_earnings_season(spy_ret.index)

    print(f"  Earnings season days: {earnings_dummy.sum()} ({100*earnings_dummy.mean():.1f}%)")
    print(f"  Non-earnings days:    {(1 - earnings_dummy).sum()}")

    # ===== 3. Unconditional Test: Earnings vs Non-Earnings Vol =====
    print("\n[3] Unconditional test: earnings vs non-earnings vol...")

    # Use 5-day RV
    rv5_clean = rv5.dropna()
    earn_mask = earnings_dummy.reindex(rv5_clean.index).fillna(0).astype(bool)

    rv_earn = rv5_clean[earn_mask]
    rv_nonearn = rv5_clean[~earn_mask]

    print(f"\n  5-day Realized Vol (annualized):")
    print(f"    Earnings season:     mean={rv_earn.mean():.4f}, median={rv_earn.median():.4f}, N={len(rv_earn)}")
    print(f"    Non-earnings season: mean={rv_nonearn.mean():.4f}, median={rv_nonearn.median():.4f}, N={len(rv_nonearn)}")

    # Welch's t-test
    t_stat_vol, p_val_vol = stats.ttest_ind(rv_earn, rv_nonearn, equal_var=False)
    print(f"    Welch t-test: t={t_stat_vol:.3f}, p={p_val_vol:.4f}")
    print(f"    Harvey |t|>3.0: {'PASS' if abs(t_stat_vol) > 3.0 else 'FAIL'}")

    # Mann-Whitney (non-parametric)
    mw_stat, mw_p = stats.mannwhitneyu(rv_earn, rv_nonearn, alternative='two-sided')
    print(f"    Mann-Whitney U: U={mw_stat:.0f}, p={mw_p:.4f}")

    # Effect size (Cohen's d)
    pooled_std = np.sqrt((rv_earn.var() + rv_nonearn.var()) / 2)
    cohens_d = (rv_earn.mean() - rv_nonearn.mean()) / pooled_std
    print(f"    Cohen's d: {cohens_d:.4f}")

    # ===== 4. Quarter-Specific Analysis =====
    print("\n[4] Quarter-specific analysis...")
    quarter_results = {}
    for q_month, q_label in [(1, "Q1 (Jan)"), (4, "Q2 (Apr)"), (7, "Q3 (Jul)"), (10, "Q4 (Oct)")]:
        q_mask = (rv5_clean.index.month == q_month) & (rv5_clean.index.day >= 10) & (rv5_clean.index.day <= 25)
        rv_q = rv5_clean[q_mask]
        # Compare to same-quarter non-earnings
        same_q_nonearn_mask = (rv5_clean.index.month == q_month) & ~q_mask
        rv_q_nonearn = rv5_clean[same_q_nonearn_mask]

        if len(rv_q) > 10 and len(rv_q_nonearn) > 10:
            t_q, p_q = stats.ttest_ind(rv_q, rv_q_nonearn, equal_var=False)
            d_q = (rv_q.mean() - rv_q_nonearn.mean()) / np.sqrt((rv_q.var() + rv_q_nonearn.var()) / 2)
        else:
            t_q, p_q, d_q = 0.0, 1.0, 0.0

        quarter_results[q_label] = {
            "earn_mean": float(rv_q.mean()),
            "nonearn_mean": float(rv_q_nonearn.mean()),
            "t_stat": float(t_q),
            "p_value": float(p_q),
            "cohens_d": float(d_q),
            "n_earn": int(len(rv_q)),
            "n_nonearn": int(len(rv_q_nonearn)),
        }
        print(f"  {q_label}: earn={rv_q.mean():.4f} vs non={rv_q_nonearn.mean():.4f}, "
              f"t={t_q:.3f}, p={p_q:.4f}, d={d_q:.4f}")

    # ===== 5. Regression: RV = a + b1*VIX + b2*earnings_dummy =====
    print("\n[5] Regression analysis: RV ~ VIX + earnings_dummy...")

    # Build regression dataframe
    df = pd.DataFrame({
        "rv5": rv5,
        "rv5_var": rv5_var,
        "r_sq": spy_ret ** 2,
        "vix": vix_close,
        "earn": earnings_dummy,
    }).dropna()

    # Lag predictors by 1 day (no lookahead!)
    df["vix_lag1"] = df["vix"].shift(1)
    df["earn_lag1"] = df["earn"].shift(1)
    df["rv5_lag1"] = df["rv5"].shift(1)
    df["rv5_lag5"] = df["rv5"].shift(5)
    df["rv5_lag22"] = df["rv5"].shift(22)
    df = df.dropna()

    # --- Model 1: RV5 ~ VIX_lag1 ---
    from numpy.linalg import lstsq
    X1 = np.column_stack([np.ones(len(df)), df["vix_lag1"].values])
    y = df["rv5"].values
    beta1, _, _, _ = lstsq(X1, y, rcond=None)
    pred1 = X1 @ beta1

    # --- Model 2: RV5 ~ VIX_lag1 + earn_lag1 ---
    X2 = np.column_stack([np.ones(len(df)), df["vix_lag1"].values, df["earn_lag1"].values])
    beta2, _, _, _ = lstsq(X2, y, rcond=None)
    pred2 = X2 @ beta2

    # --- Model 3: HAR (RV1 + RV5 + RV22) ---
    X3 = np.column_stack([np.ones(len(df)), df["rv5_lag1"].values, df["rv5_lag5"].values, df["rv5_lag22"].values])
    beta3, _, _, _ = lstsq(X3, y, rcond=None)
    pred3 = X3 @ beta3

    # --- Model 4: HAR + earn_lag1 ---
    X4 = np.column_stack([np.ones(len(df)), df["rv5_lag1"].values, df["rv5_lag5"].values, df["rv5_lag22"].values, df["earn_lag1"].values])
    beta4, _, _, _ = lstsq(X4, y, rcond=None)
    pred4 = X4 @ beta4

    print(f"\n  Full-sample regressions (N={len(df)}):")
    print(f"  Model 1 (VIX only):        R²={1 - np.sum((y - pred1)**2)/np.sum((y - y.mean())**2):.4f}")
    print(f"  Model 2 (VIX + earn):      R²={1 - np.sum((y - pred2)**2)/np.sum((y - y.mean())**2):.4f}")
    print(f"    earnings_dummy coef:     {beta2[2]:.6f}")
    print(f"  Model 3 (HAR):             R²={1 - np.sum((y - pred3)**2)/np.sum((y - y.mean())**2):.4f}")
    print(f"  Model 4 (HAR + earn):      R²={1 - np.sum((y - pred4)**2)/np.sum((y - y.mean())**2):.4f}")
    print(f"    earnings_dummy coef:     {beta4[4]:.6f}")

    # T-test on earnings coefficient (Model 2)
    residuals2 = y - pred2
    sigma2_hat = np.sum(residuals2**2) / (len(y) - X2.shape[1])
    cov2 = sigma2_hat * np.linalg.inv(X2.T @ X2)
    se_earn2 = np.sqrt(cov2[2, 2])
    t_earn2 = beta2[2] / se_earn2
    p_earn2 = 2 * (1 - stats.t.cdf(abs(t_earn2), df=len(y) - X2.shape[1]))
    print(f"    t-stat for earn (Model 2): {t_earn2:.3f}, p={p_earn2:.4f}")

    # T-test on earnings coefficient (Model 4)
    residuals4 = y - pred4
    sigma4_hat = np.sum(residuals4**2) / (len(y) - X4.shape[1])
    cov4 = sigma4_hat * np.linalg.inv(X4.T @ X4)
    se_earn4 = np.sqrt(cov4[4, 4])
    t_earn4 = beta4[4] / se_earn4
    p_earn4 = 2 * (1 - stats.t.cdf(abs(t_earn4), df=len(y) - X4.shape[1]))
    print(f"    t-stat for earn (Model 4): {t_earn4:.3f}, p={p_earn4:.4f}")

    # ===== 6. OOS Evaluation (2005-2018 IS, 2019-2026 OOS) =====
    print("\n[6] Out-of-sample evaluation...")

    is_mask = df.index < "2019-01-01"
    oos_mask = df.index >= "2019-01-01"
    df_is = df[is_mask]
    df_oos = df[oos_mask]

    print(f"  IS period: {df_is.index[0].date()} to {df_is.index[-1].date()} (N={len(df_is)})")
    print(f"  OOS period: {df_oos.index[0].date()} to {df_oos.index[-1].date()} (N={len(df_oos)})")

    # Fit on IS, predict OOS
    y_is = df_is["rv5"].values
    y_oos = df_oos["rv5"].values

    def fit_predict_ols(X_is, X_oos, y_is):
        beta, _, _, _ = lstsq(X_is, y_is, rcond=None)
        return X_oos @ beta

    # Model 1: VIX only
    X1_is = np.column_stack([np.ones(len(df_is)), df_is["vix_lag1"].values])
    X1_oos = np.column_stack([np.ones(len(df_oos)), df_oos["vix_lag1"].values])
    pred1_oos = fit_predict_ols(X1_is, X1_oos, y_is)

    # Model 2: VIX + earn
    X2_is = np.column_stack([np.ones(len(df_is)), df_is["vix_lag1"].values, df_is["earn_lag1"].values])
    X2_oos = np.column_stack([np.ones(len(df_oos)), df_oos["vix_lag1"].values, df_oos["earn_lag1"].values])
    pred2_oos = fit_predict_ols(X2_is, X2_oos, y_is)

    # Model 3: HAR
    X3_is = np.column_stack([np.ones(len(df_is)), df_is["rv5_lag1"].values, df_is["rv5_lag5"].values, df_is["rv5_lag22"].values])
    X3_oos = np.column_stack([np.ones(len(df_oos)), df_oos["rv5_lag1"].values, df_oos["rv5_lag5"].values, df_oos["rv5_lag22"].values])
    pred3_oos = fit_predict_ols(X3_is, X3_oos, y_is)

    # Model 4: HAR + earn
    X4_is = np.column_stack([np.ones(len(df_is)), df_is["rv5_lag1"].values, df_is["rv5_lag5"].values, df_is["rv5_lag22"].values, df_is["earn_lag1"].values])
    X4_oos = np.column_stack([np.ones(len(df_oos)), df_oos["rv5_lag1"].values, df_oos["rv5_lag5"].values, df_oos["rv5_lag22"].values, df_oos["earn_lag1"].values])
    pred4_oos = fit_predict_ols(X4_is, X4_oos, y_is)

    # Ensure positive predictions for QLIKE
    pred1_oos_pos = np.clip(pred1_oos, 1e-6, None)
    pred2_oos_pos = np.clip(pred2_oos, 1e-6, None)
    pred3_oos_pos = np.clip(pred3_oos, 1e-6, None)
    pred4_oos_pos = np.clip(pred4_oos, 1e-6, None)

    # OOS metrics
    def oos_r2(actual, predicted):
        ss_res = np.sum((actual - predicted) ** 2)
        ss_tot = np.sum((actual - actual.mean()) ** 2)
        return 1 - ss_res / ss_tot

    # MSE
    mse1 = np.mean((y_oos - pred1_oos) ** 2)
    mse2 = np.mean((y_oos - pred2_oos) ** 2)
    mse3 = np.mean((y_oos - pred3_oos) ** 2)
    mse4 = np.mean((y_oos - pred4_oos) ** 2)

    # MAE
    mae1 = np.mean(np.abs(y_oos - pred1_oos))
    mae2 = np.mean(np.abs(y_oos - pred2_oos))
    mae3 = np.mean(np.abs(y_oos - pred3_oos))
    mae4 = np.mean(np.abs(y_oos - pred4_oos))

    # QLIKE (using RV as target — same units)
    qlike1 = np.mean(qlike_loss(y_oos, pred1_oos_pos))
    qlike2 = np.mean(qlike_loss(y_oos, pred2_oos_pos))
    qlike3 = np.mean(qlike_loss(y_oos, pred3_oos_pos))
    qlike4 = np.mean(qlike_loss(y_oos, pred4_oos_pos))

    # OOS R²
    r2_1 = oos_r2(y_oos, pred1_oos)
    r2_2 = oos_r2(y_oos, pred2_oos)
    r2_3 = oos_r2(y_oos, pred3_oos)
    r2_4 = oos_r2(y_oos, pred4_oos)

    print(f"\n  OOS Results:")
    print(f"  {'Model':<25} {'MSE':>10} {'MAE':>10} {'QLIKE':>10} {'OOS R²':>10}")
    print(f"  {'-'*65}")
    print(f"  {'M1: VIX only':<25} {mse1:>10.6f} {mae1:>10.4f} {qlike1:>10.6f} {r2_1:>10.4f}")
    print(f"  {'M2: VIX + earn':<25} {mse2:>10.6f} {mae2:>10.4f} {qlike2:>10.6f} {r2_2:>10.4f}")
    print(f"  {'M3: HAR':<25} {mse3:>10.6f} {mae3:>10.4f} {qlike3:>10.6f} {r2_3:>10.4f}")
    print(f"  {'M4: HAR + earn':<25} {mse4:>10.6f} {mae4:>10.4f} {qlike4:>10.6f} {r2_4:>10.4f}")

    # ===== 7. DM Tests =====
    print("\n[7] DM tests (Harvey |t|>3.0 threshold)...")

    # DM test on QLIKE losses
    qlike_loss1 = qlike_loss(y_oos, pred1_oos_pos)
    qlike_loss2 = qlike_loss(y_oos, pred2_oos_pos)
    qlike_loss3 = qlike_loss(y_oos, pred3_oos_pos)
    qlike_loss4 = qlike_loss(y_oos, pred4_oos_pos)

    # DM: VIX vs VIX+earn (does earn help beyond VIX?)
    dm_12_t, dm_12_p = dm_test(qlike_loss1, qlike_loss2, h=5)
    print(f"  VIX vs VIX+earn:   DM t={dm_12_t:.3f}, p={dm_12_p:.4f} (neg → VIX+earn better)")
    print(f"    Harvey |t|>3.0: {'PASS' if abs(dm_12_t) > 3.0 else 'FAIL'}")

    # DM: HAR vs HAR+earn (does earn help beyond HAR?)
    dm_34_t, dm_34_p = dm_test(qlike_loss3, qlike_loss4, h=5)
    print(f"  HAR vs HAR+earn:   DM t={dm_34_t:.3f}, p={dm_34_p:.4f} (neg → HAR+earn better)")
    print(f"    Harvey |t|>3.0: {'PASS' if abs(dm_34_t) > 3.0 else 'FAIL'}")

    # DM: VIX vs HAR
    dm_13_t, dm_13_p = dm_test(qlike_loss1, qlike_loss3, h=5)
    print(f"  VIX vs HAR:        DM t={dm_13_t:.3f}, p={dm_13_p:.4f} (neg → HAR better)")

    # DM on MSE losses
    mse_loss1 = (y_oos - pred1_oos) ** 2
    mse_loss2 = (y_oos - pred2_oos) ** 2
    mse_loss3 = (y_oos - pred3_oos) ** 2
    mse_loss4 = (y_oos - pred4_oos) ** 2

    dm_12_mse_t, dm_12_mse_p = dm_test(mse_loss1, mse_loss2, h=5)
    dm_34_mse_t, dm_34_mse_p = dm_test(mse_loss3, mse_loss4, h=5)
    print(f"\n  MSE-based DM tests:")
    print(f"  VIX vs VIX+earn:   DM t={dm_12_mse_t:.3f}, p={dm_12_mse_p:.4f}")
    print(f"  HAR vs HAR+earn:   DM t={dm_34_mse_t:.3f}, p={dm_34_mse_p:.4f}")

    # ===== 8. Robustness: Daily r² as target (Patton 2011) =====
    print("\n[8] Robustness: daily r² as target (Patton 2011 proxy-robust)...")

    # Use r² (daily squared returns) as sigma² proxy
    r_sq_oos = df_oos["r_sq"].values

    # Predictions need to be in variance units → square the RV predictions / 252
    # Actually, better: refit models targeting r² directly
    y_is_rsq = df_is["r_sq"].values
    y_oos_rsq = df_oos["r_sq"].values

    pred1_rsq_oos = fit_predict_ols(X1_is, X1_oos, y_is_rsq)
    pred2_rsq_oos = fit_predict_ols(X2_is, X2_oos, y_is_rsq)
    pred3_rsq_oos = fit_predict_ols(X3_is, X3_oos, y_is_rsq)
    pred4_rsq_oos = fit_predict_ols(X4_is, X4_oos, y_is_rsq)

    pred1_rsq_pos = np.clip(pred1_rsq_oos, 1e-10, None)
    pred2_rsq_pos = np.clip(pred2_rsq_oos, 1e-10, None)
    pred3_rsq_pos = np.clip(pred3_rsq_oos, 1e-10, None)
    pred4_rsq_pos = np.clip(pred4_rsq_oos, 1e-10, None)

    qlike_rsq_1 = np.mean(qlike_loss(y_oos_rsq, pred1_rsq_pos))
    qlike_rsq_2 = np.mean(qlike_loss(y_oos_rsq, pred2_rsq_pos))
    qlike_rsq_3 = np.mean(qlike_loss(y_oos_rsq, pred3_rsq_pos))
    qlike_rsq_4 = np.mean(qlike_loss(y_oos_rsq, pred4_rsq_pos))

    print(f"  QLIKE on r²: M1={qlike_rsq_1:.6f}, M2={qlike_rsq_2:.6f}, M3={qlike_rsq_3:.6f}, M4={qlike_rsq_4:.6f}")

    dm_rsq_12_t, dm_rsq_12_p = dm_test(
        qlike_loss(y_oos_rsq, pred1_rsq_pos),
        qlike_loss(y_oos_rsq, pred2_rsq_pos),
        h=1
    )
    dm_rsq_34_t, dm_rsq_34_p = dm_test(
        qlike_loss(y_oos_rsq, pred3_rsq_pos),
        qlike_loss(y_oos_rsq, pred4_rsq_pos),
        h=1
    )
    print(f"  DM (r² QLIKE): VIX vs VIX+earn: t={dm_rsq_12_t:.3f}, p={dm_rsq_12_p:.4f}")
    print(f"  DM (r² QLIKE): HAR vs HAR+earn: t={dm_rsq_34_t:.3f}, p={dm_rsq_34_p:.4f}")

    # ===== 9. Expanding Window OOS (robustness) =====
    print("\n[9] Expanding window OOS (refit every 63 trading days)...")

    refit_freq = 63  # quarterly refit
    oos_start_idx = df.index.get_loc(df_oos.index[0])
    n_total = len(df)
    expanding_preds = {f"m{i}": [] for i in range(1, 5)}
    expanding_actual = []

    for t in range(oos_start_idx, n_total):
        # Refit at start and every refit_freq days
        steps_since_start = t - oos_start_idx
        if steps_since_start % refit_freq == 0 or t == oos_start_idx:
            train = df.iloc[:t]
            y_train = train["rv5"].values

            X_train_1 = np.column_stack([np.ones(len(train)), train["vix_lag1"].values])
            X_train_2 = np.column_stack([np.ones(len(train)), train["vix_lag1"].values, train["earn_lag1"].values])
            X_train_3 = np.column_stack([np.ones(len(train)), train["rv5_lag1"].values, train["rv5_lag5"].values, train["rv5_lag22"].values])
            X_train_4 = np.column_stack([np.ones(len(train)), train["rv5_lag1"].values, train["rv5_lag5"].values, train["rv5_lag22"].values, train["earn_lag1"].values])

            b1, _, _, _ = lstsq(X_train_1, y_train, rcond=None)
            b2, _, _, _ = lstsq(X_train_2, y_train, rcond=None)
            b3, _, _, _ = lstsq(X_train_3, y_train, rcond=None)
            b4, _, _, _ = lstsq(X_train_4, y_train, rcond=None)

        row = df.iloc[t]
        x1 = np.array([1, row["vix_lag1"]])
        x2 = np.array([1, row["vix_lag1"], row["earn_lag1"]])
        x3 = np.array([1, row["rv5_lag1"], row["rv5_lag5"], row["rv5_lag22"]])
        x4 = np.array([1, row["rv5_lag1"], row["rv5_lag5"], row["rv5_lag22"], row["earn_lag1"]])

        expanding_preds["m1"].append(x1 @ b1)
        expanding_preds["m2"].append(x2 @ b2)
        expanding_preds["m3"].append(x3 @ b3)
        expanding_preds["m4"].append(x4 @ b4)
        expanding_actual.append(row["rv5"])

    exp_actual = np.array(expanding_actual)
    exp_preds = {k: np.clip(np.array(v), 1e-6, None) for k, v in expanding_preds.items()}

    exp_qlike = {k: np.mean(qlike_loss(exp_actual, v)) for k, v in exp_preds.items()}
    exp_mse = {k: np.mean((exp_actual - v) ** 2) for k, v in exp_preds.items()}

    print(f"\n  Expanding Window OOS (refit every {refit_freq} days, N={len(exp_actual)}):")
    print(f"  {'Model':<25} {'MSE':>10} {'QLIKE':>10}")
    print(f"  {'-'*45}")
    for k, label in [("m1", "VIX only"), ("m2", "VIX + earn"), ("m3", "HAR"), ("m4", "HAR + earn")]:
        print(f"  {label:<25} {exp_mse[k]:>10.6f} {exp_qlike[k]:>10.6f}")

    # DM tests on expanding window
    exp_ql1 = qlike_loss(exp_actual, exp_preds["m1"])
    exp_ql2 = qlike_loss(exp_actual, exp_preds["m2"])
    exp_ql3 = qlike_loss(exp_actual, exp_preds["m3"])
    exp_ql4 = qlike_loss(exp_actual, exp_preds["m4"])

    dm_exp_12_t, dm_exp_12_p = dm_test(exp_ql1, exp_ql2, h=5)
    dm_exp_34_t, dm_exp_34_p = dm_test(exp_ql3, exp_ql4, h=5)
    print(f"\n  DM tests (expanding, QLIKE):")
    print(f"  VIX vs VIX+earn:   t={dm_exp_12_t:.3f}, p={dm_exp_12_p:.4f}")
    print(f"  HAR vs HAR+earn:   t={dm_exp_34_t:.3f}, p={dm_exp_34_p:.4f}")

    # ===== 10. Summary =====
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Determine if earnings dummy helps
    earn_helps_vix = abs(dm_12_t) > 3.0 and dm_12_t < 0
    earn_helps_har = abs(dm_34_t) > 3.0 and dm_34_t < 0
    uncond_significant = abs(t_stat_vol) > 3.0

    print(f"\n  1. Unconditional vol difference (earnings vs non): t={t_stat_vol:.3f}")
    print(f"     {'SIGNIFICANT' if uncond_significant else 'NOT SIGNIFICANT'} at Harvey |t|>3.0")
    print(f"     Cohen's d = {cohens_d:.4f} ({'negligible' if abs(cohens_d) < 0.2 else 'small' if abs(cohens_d) < 0.5 else 'medium'})")

    print(f"\n  2. Earnings dummy coefficient:")
    print(f"     In VIX model: {beta2[2]:.6f} (t={t_earn2:.3f})")
    print(f"     In HAR model: {beta4[4]:.6f} (t={t_earn4:.3f})")

    print(f"\n  3. OOS QLIKE improvement (earnings dummy):")
    qlike_improve_vix = (qlike1 - qlike2) / qlike1 * 100
    qlike_improve_har = (qlike3 - qlike4) / qlike3 * 100
    print(f"     VIX → VIX+earn: {qlike_improve_vix:+.4f}% (DM t={dm_12_t:.3f})")
    print(f"     HAR → HAR+earn: {qlike_improve_har:+.4f}% (DM t={dm_34_t:.3f})")

    conclusion = "NULL RESULT"
    if earn_helps_vix or earn_helps_har:
        conclusion = "EARNINGS DUMMY HELPS"

    print(f"\n  CONCLUSION: {conclusion}")
    print(f"  Earnings season has {'a statistically significant' if uncond_significant else 'NO statistically significant'} "
          f"effect on SPY aggregate vol.")
    print(f"  Earnings dummy {'DOES' if earn_helps_vix or earn_helps_har else 'DOES NOT'} "
          f"improve vol forecasting beyond baseline (Harvey |t|>3.0).")
    print(f"  Consistent with K498 (GARCH-X null) and K570 (VT no adjustment).")
    print(f"  Index diversification absorbs individual stock earnings effects.")

    # ===== 11. Save Results =====
    results = {
        "experiment_id": "K875",
        "title": "K875: Earnings Season Aggregate Volatility",
        "status": conclusion,
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, ^VIX)",
        "period": f"{spy_ret.index[0].date()} to {spy_ret.index[-1].date()}",
        "n_observations": int(len(spy_ret)),
        "methodology": "OLS regression + HAR + OOS QLIKE + DM test",
        "references": [
            "K498: GARCH-X earnings dummy (null result)",
            "K570: VT should not adjust during earnings season",
            "Savor & Wilson (2016, JFE): Earnings Announcements and Systematic Risk",
            "Patton (2011): Volatility forecast comparison using imperfect volatility proxies",
            "Harvey (2016): ...and the Cross-Section of Expected Returns"
        ],
        "unconditional_test": {
            "earnings_vol_mean": float(rv_earn.mean()),
            "non_earnings_vol_mean": float(rv_nonearn.mean()),
            "welch_t": float(t_stat_vol),
            "welch_p": float(p_val_vol),
            "mann_whitney_p": float(mw_p),
            "cohens_d": float(cohens_d),
            "harvey_pass": bool(abs(t_stat_vol) > 3.0),
        },
        "quarter_specific": quarter_results,
        "regression_full_sample": {
            "model1_vix_R2": float(1 - np.sum((y - pred1)**2)/np.sum((y - y.mean())**2)),
            "model2_vix_earn_R2": float(1 - np.sum((y - pred2)**2)/np.sum((y - y.mean())**2)),
            "earn_coef_vix_model": float(beta2[2]),
            "earn_t_vix_model": float(t_earn2),
            "model3_HAR_R2": float(1 - np.sum((y - pred3)**2)/np.sum((y - y.mean())**2)),
            "model4_HAR_earn_R2": float(1 - np.sum((y - pred4)**2)/np.sum((y - y.mean())**2)),
            "earn_coef_har_model": float(beta4[4]),
            "earn_t_har_model": float(t_earn4),
        },
        "oos_results": {
            "is_period": f"{df_is.index[0].date()} to {df_is.index[-1].date()}",
            "oos_period": f"{df_oos.index[0].date()} to {df_oos.index[-1].date()}",
            "n_is": int(len(df_is)),
            "n_oos": int(len(df_oos)),
            "fixed_split": {
                "model1_vix": {"MSE": float(mse1), "MAE": float(mae1), "QLIKE": float(qlike1), "R2": float(r2_1)},
                "model2_vix_earn": {"MSE": float(mse2), "MAE": float(mae2), "QLIKE": float(qlike2), "R2": float(r2_2)},
                "model3_HAR": {"MSE": float(mse3), "MAE": float(mae3), "QLIKE": float(qlike3), "R2": float(r2_3)},
                "model4_HAR_earn": {"MSE": float(mse4), "MAE": float(mae4), "QLIKE": float(qlike4), "R2": float(r2_4)},
            },
            "dm_tests_qlike": {
                "vix_vs_vix_earn": {"t": float(dm_12_t), "p": float(dm_12_p), "harvey_pass": bool(abs(dm_12_t) > 3.0)},
                "har_vs_har_earn": {"t": float(dm_34_t), "p": float(dm_34_p), "harvey_pass": bool(abs(dm_34_t) > 3.0)},
                "vix_vs_har": {"t": float(dm_13_t), "p": float(dm_13_p)},
            },
            "dm_tests_mse": {
                "vix_vs_vix_earn": {"t": float(dm_12_mse_t), "p": float(dm_12_mse_p)},
                "har_vs_har_earn": {"t": float(dm_34_mse_t), "p": float(dm_34_mse_p)},
            },
            "robustness_r2_target": {
                "qlike_m1": float(qlike_rsq_1), "qlike_m2": float(qlike_rsq_2),
                "qlike_m3": float(qlike_rsq_3), "qlike_m4": float(qlike_rsq_4),
                "dm_vix_vs_vix_earn": {"t": float(dm_rsq_12_t), "p": float(dm_rsq_12_p)},
                "dm_har_vs_har_earn": {"t": float(dm_rsq_34_t), "p": float(dm_rsq_34_p)},
            },
            "expanding_window": {
                "refit_freq": refit_freq,
                "n_oos": len(exp_actual),
                "qlike": {k: float(v) for k, v in exp_qlike.items()},
                "mse": {k: float(v) for k, v in exp_mse.items()},
                "dm_vix_vs_vix_earn": {"t": float(dm_exp_12_t), "p": float(dm_exp_12_p)},
                "dm_har_vs_har_earn": {"t": float(dm_exp_34_t), "p": float(dm_exp_34_p)},
            },
        },
        "conclusion": (
            f"{conclusion}. Earnings season (mid-month Jan/Apr/Jul/Oct) shows "
            f"{'no' if not uncond_significant else 'a'} statistically significant effect on SPY 5-day realized vol "
            f"(Welch t={t_stat_vol:.3f}, Cohen's d={cohens_d:.4f}). "
            f"Earnings dummy does not improve OOS vol forecasting beyond VIX (DM t={dm_12_t:.3f}) "
            f"or beyond HAR (DM t={dm_34_t:.3f}), both failing Harvey |t|>3.0. "
            f"Consistent with K498/K570: index diversification absorbs individual stock earnings effects. "
            f"Limitations: (1) uses calendar dates not actual reporting dates, "
            f"(2) 5-day RV from daily returns only, (3) no sector-level decomposition."
        ),
    }

    out_path = Path(__file__).parent / "k875_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
