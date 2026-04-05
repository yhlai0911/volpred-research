#!/usr/bin/env python3
"""
K906: SPY HAR-RV Preliminary Horse Race
========================================
First test of HAR-RV on SPY 5-min data vs GJR-GARCH (daily).

Data source: yfinance 5-min (55 days: 2026-01-14 to 2026-04-02) + daily
Reference: Corsi (2009), Patton (2011), Hansen & Lunde (2005)

PRELIMINARY: OOS ~33 days << 252-day minimum. Direction-finding only.

Error log rules applied:
- GARCH OOS: recursive h[t]=f(h[t-1],r²[t-1]), no stale variance
- DM test: use volpred.stats.model_evaluation functions
- Model-Target matching: report ALL targets, not just favorable ones
- HAR winning on RV is mechanical, not empirical
"""

import json
import glob
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from arch import arch_model

# Use project's own evaluation utilities
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test

warnings.filterwarnings("ignore", category=FutureWarning)


# ═══════════════════════════════════════════════════════════════
# Step 1: Load 5-min data and compute Realized Variance
# ═══════════════════════════════════════════════════════════════

def load_5min_rv(data_dir: str) -> pd.DataFrame:
    """Load all SPY 5-min CSVs, compute daily RV, overnight return, etc."""
    files = sorted(glob.glob(f"{data_dir}/SPY_5min_*.csv"))
    print(f"Found {len(files)} SPY 5-min files")

    records = []
    for f in files:
        df = pd.read_csv(f, header=[0, 1], index_col=0, parse_dates=True)
        df.columns = [c[0] for c in df.columns]

        # 5-min log returns
        close = df["Close"].values
        log_ret = np.diff(np.log(close))

        # Realized variance = sum of squared 5-min returns
        rv_intraday = np.sum(log_ret ** 2)

        # Daily open and close
        day_open = df["Open"].iloc[0]
        day_close = df["Close"].iloc[-1]

        # Extract date
        date_str = Path(f).stem.split("_")[-1]
        date = pd.Timestamp(date_str)

        records.append({
            "date": date,
            "open": day_open,
            "close": day_close,
            "rv_intraday": rv_intraday,
            "n_bars": len(close),
            "n_returns": len(log_ret),
        })

    rv_df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)

    # Compute overnight return squared: (open_t - close_{t-1})^2 in log terms
    rv_df["log_close"] = np.log(rv_df["close"])
    rv_df["log_open"] = np.log(rv_df["open"])
    rv_df["overnight_r2"] = np.nan
    for i in range(1, len(rv_df)):
        overnight = rv_df.loc[i, "log_open"] - rv_df.loc[i - 1, "log_close"]
        rv_df.loc[i, "overnight_r2"] = overnight ** 2

    # RV_total = RV_intraday + overnight_r² (Hansen & Lunde 2005)
    rv_df["rv_total"] = rv_df["rv_intraday"] + rv_df["overnight_r2"].fillna(0)

    # Daily close-to-close return and r²
    rv_df["daily_ret"] = rv_df["log_close"].diff()
    rv_df["daily_r2"] = rv_df["daily_ret"] ** 2

    return rv_df


# ═══════════════════════════════════════════════════════════════
# Step 2: HAR-RV Model (Corsi 2009)
# ═══════════════════════════════════════════════════════════════

def har_rv_forecast(rv_series: np.ndarray, min_train: int = 22) -> np.ndarray:
    """
    HAR-RV: RV_{t+1} = b0 + b1*RV_t + b5*RV_{t-5:t} + b22*RV_{t-22:t} + eps
    Uses expanding window OLS.
    Returns array of 1-step-ahead forecasts aligned with input.
    """
    n = len(rv_series)
    forecasts = np.full(n, np.nan)

    for t in range(min_train, n - 1):
        # Dependent: RV_{s+1} for s in [22..t-1]
        y_start = 22  # need 22 lags
        if t < y_start + 1:
            continue

        y_indices = list(range(y_start, t))
        Y = rv_series[np.array(y_indices) + 1]  # RV_{s+1}

        X = np.zeros((len(y_indices), 4))
        for j, s in enumerate(y_indices):
            X[j, 0] = 1.0                                  # intercept
            X[j, 1] = rv_series[s]                          # RV_t (daily)
            X[j, 2] = np.mean(rv_series[s - 4: s + 1])      # RV_t^(w) (weekly, 5-day)
            X[j, 3] = np.mean(rv_series[s - 21: s + 1])     # RV_t^(m) (monthly, 22-day)

        # OLS: beta = (X'X)^{-1} X'Y
        try:
            XtX = X.T @ X
            XtY = X.T @ Y
            beta = np.linalg.solve(XtX, XtY)
        except np.linalg.LinAlgError:
            continue

        # Forecast for t+1
        x_new = np.array([
            1.0,
            rv_series[t],
            np.mean(rv_series[t - 4: t + 1]),
            np.mean(rv_series[t - 21: t + 1]),
        ])
        fcast = x_new @ beta
        forecasts[t + 1] = max(fcast, 1e-10)  # floor at small positive

    return forecasts


# ═══════════════════════════════════════════════════════════════
# Step 3: GJR-GARCH Baseline
# ═══════════════════════════════════════════════════════════════

def fit_gjr_garch_recursive(daily_returns: pd.Series, oos_dates: pd.DatetimeIndex) -> dict:
    """
    Fit GJR-GARCH(1,1) with Student-t innovations on daily returns.
    Produce recursive 1-step-ahead variance forecasts for OOS dates.

    Uses the full history up to each OOS date for recursive forecasting:
    h[t] = omega + (alpha + gamma*I_{r<0})*r²[t-1] + beta*h[t-1]
    """
    # Find the start of OOS in the returns series
    returns = daily_returns.copy()
    returns.index = pd.to_datetime(returns.index)

    # Fit on all available data before first OOS date
    first_oos = oos_dates.iloc[0]
    train_mask = returns.index < first_oos
    train_returns = returns[train_mask]

    print(f"GJR-GARCH training: {len(train_returns)} days")
    print(f"Training period: {train_returns.index[0].date()} to {train_returns.index[-1].date()}")

    # Scale returns to percentage
    train_pct = train_returns * 100

    am = arch_model(train_pct, vol="GARCH", p=1, o=1, q=1, dist="t", mean="Zero")
    res = am.fit(disp="off", show_warning=False)

    # Extract parameters
    omega = res.params.get("omega", 0)
    alpha = res.params.get("alpha[1]", 0)
    gamma = res.params.get("gamma[1]", 0)
    beta = res.params.get("beta[1]", 0)
    nu = res.params.get("nu", 5)

    print(f"GJR params: omega={omega:.6f}, alpha={alpha:.4f}, gamma={gamma:.4f}, "
          f"beta={beta:.4f}, nu={nu:.2f}")
    print(f"Persistence: {alpha + gamma / 2 + beta:.4f}")

    # Get conditional variance at end of training
    # Use last conditional variance from the fitted model
    cond_var = res.conditional_volatility.iloc[-1] ** 2  # in pct² units

    # Recursive forecasting
    h_prev = cond_var  # in pct²
    forecasts = {}

    all_returns_pct = returns * 100

    for date in oos_dates:
        # h[t] = omega + (alpha + gamma*I)*r²[t-1] + beta*h[t-1]
        # This IS the forecast for date t (made using info up to t-1)
        forecasts[date] = h_prev / (100 ** 2)  # convert back to decimal variance

        # Update for next step: need r[t] (today's return)
        if date in all_returns_pct.index:
            r_t_pct = all_returns_pct.loc[date]
            indicator = 1.0 if r_t_pct < 0 else 0.0
            h_new = omega + (alpha + gamma * indicator) * (r_t_pct ** 2) + beta * h_prev
            h_prev = h_new
        # else: use last h (stale, but shouldn't happen with aligned dates)

    return {
        "forecasts": forecasts,
        "params": {
            "omega": float(omega),
            "alpha": float(alpha),
            "gamma": float(gamma),
            "beta": float(beta),
            "nu": float(nu),
            "persistence": float(alpha + gamma / 2 + beta),
            "train_days": int(len(train_returns)),
        },
    }


# ═══════════════════════════════════════════════════════════════
# Step 4: Fair Comparison Framework
# ═══════════════════════════════════════════════════════════════

def compute_comparison_metrics(
    har_fcast: np.ndarray,
    gjr_fcast: np.ndarray,
    rv_intraday: np.ndarray,
    rv_total: np.ndarray,
    daily_r2: np.ndarray,
    dates: np.ndarray,
) -> dict:
    """
    Comprehensive fair comparison following Patton (2011) and Hansen & Lunde (2005).
    """
    results = {}

    # Identify valid indices (all non-NaN)
    valid = (
        np.isfinite(har_fcast)
        & np.isfinite(gjr_fcast)
        & np.isfinite(rv_intraday)
        & np.isfinite(rv_total)
        & np.isfinite(daily_r2)
        & (har_fcast > 0)
        & (gjr_fcast > 0)
        & (rv_intraday > 0)
        & (rv_total > 0)
        & (daily_r2 > 0)
    )

    h = har_fcast[valid]
    g = gjr_fcast[valid]
    rv_id = rv_intraday[valid]
    rv_tot = rv_total[valid]
    r2 = daily_r2[valid]
    valid_dates = dates[valid]

    n_oos = len(h)
    results["n_oos"] = int(n_oos)
    results["oos_start"] = str(valid_dates[0])
    results["oos_end"] = str(valid_dates[-1])

    print(f"\n{'=' * 60}")
    print(f"Fair Comparison: {n_oos} OOS days")
    print(f"Period: {valid_dates[0]} to {valid_dates[-1]}")
    print(f"{'=' * 60}")

    # ─── Layer 1: Native Target Performance ───
    print("\n--- Layer 1: Native Target QLIKE ---")

    # HAR on RV_intraday (its native target)
    qlike_har_on_rv = qlike(rv_id, h)
    print(f"HAR  on RV_intraday: QLIKE = {qlike_har_on_rv:.6f}")

    # GJR on r² (its native target)
    qlike_gjr_on_r2 = qlike(r2, g)
    print(f"GJR  on r²:          QLIKE = {qlike_gjr_on_r2:.6f}")

    results["native_target"] = {
        "har_on_rv_intraday": float(qlike_har_on_rv),
        "gjr_on_r2": float(qlike_gjr_on_r2),
        "note": "These are on DIFFERENT targets — not directly comparable (mechanical advantage)",
    }

    # ─── Layer 2: Unified QLIKE on r² (Patton 2011 proxy-robust) ───
    print("\n--- Layer 2: QLIKE on r² (Patton 2011, primary ranking) ---")

    qlike_har_r2 = qlike(r2, h)
    qlike_gjr_r2 = qlike(r2, g)
    print(f"HAR  on r²: QLIKE = {qlike_har_r2:.6f}")
    print(f"GJR  on r²: QLIKE = {qlike_gjr_r2:.6f}")
    winner_r2 = "HAR" if qlike_har_r2 < qlike_gjr_r2 else "GJR"
    print(f"Winner on r²: {winner_r2}")

    results["qlike_on_r2"] = {
        "har": float(qlike_har_r2),
        "gjr": float(qlike_gjr_r2),
        "winner": winner_r2,
        "note": "Patton (2011) proxy-robust: r² is unbiased for σ², ranking consistent",
    }

    # ─── Layer 2b: QLIKE on RV_total (Hansen & Lunde 2005) ───
    print("\n--- Layer 2b: QLIKE on RV_total (Hansen & Lunde 2005) ---")

    qlike_har_rvtot = qlike(rv_tot, h)
    qlike_gjr_rvtot = qlike(rv_tot, g)
    print(f"HAR  on RV_total: QLIKE = {qlike_har_rvtot:.6f}")
    print(f"GJR  on RV_total: QLIKE = {qlike_gjr_rvtot:.6f}")
    winner_rvtot = "HAR" if qlike_har_rvtot < qlike_gjr_rvtot else "GJR"
    print(f"Winner on RV_total: {winner_rvtot}")

    results["qlike_on_rv_total"] = {
        "har": float(qlike_har_rvtot),
        "gjr": float(qlike_gjr_rvtot),
        "winner": winner_rvtot,
        "note": "RV_total = RV_intraday + overnight_r² (Hansen & Lunde 2005)",
    }

    # ─── Layer 3: Spearman Rank Correlation ───
    print("\n--- Layer 3: Spearman Rank Correlation ---")

    # Each model vs each target
    spearman_har_rv, p_har_rv = stats.spearmanr(h, rv_id)
    spearman_gjr_rv, p_gjr_rv = stats.spearmanr(g, rv_id)
    spearman_har_r2, p_har_r2 = stats.spearmanr(h, r2)
    spearman_gjr_r2, p_gjr_r2 = stats.spearmanr(g, r2)
    spearman_har_rvtot, p_har_rvtot = stats.spearmanr(h, rv_tot)
    spearman_gjr_rvtot, p_gjr_rvtot = stats.spearmanr(g, rv_tot)

    print(f"HAR  vs RV_intraday: rho = {spearman_har_rv:.4f} (p={p_har_rv:.4f})")
    print(f"GJR  vs RV_intraday: rho = {spearman_gjr_rv:.4f} (p={p_gjr_rv:.4f})")
    print(f"HAR  vs r²:          rho = {spearman_har_r2:.4f} (p={p_har_r2:.4f})")
    print(f"GJR  vs r²:          rho = {spearman_gjr_r2:.4f} (p={p_gjr_r2:.4f})")
    print(f"HAR  vs RV_total:    rho = {spearman_har_rvtot:.4f} (p={p_har_rvtot:.4f})")
    print(f"GJR  vs RV_total:    rho = {spearman_gjr_rvtot:.4f} (p={p_gjr_rvtot:.4f})")

    results["spearman"] = {
        "har_vs_rv_intraday": {"rho": float(spearman_har_rv), "p": float(p_har_rv)},
        "gjr_vs_rv_intraday": {"rho": float(spearman_gjr_rv), "p": float(p_gjr_rv)},
        "har_vs_r2": {"rho": float(spearman_har_r2), "p": float(p_har_r2)},
        "gjr_vs_r2": {"rho": float(spearman_gjr_r2), "p": float(p_gjr_r2)},
        "har_vs_rv_total": {"rho": float(spearman_har_rvtot), "p": float(p_har_rvtot)},
        "gjr_vs_rv_total": {"rho": float(spearman_gjr_rvtot), "p": float(p_gjr_rvtot)},
    }

    # ─── Layer 4: DM Test (preliminary, N too small) ───
    print("\n--- Layer 4: DM Test (PRELIMINARY, N too small for Harvey threshold) ---")

    # DM on r² target (Patton 2011)
    loss_har_r2 = qlike_pointwise(r2, h)
    loss_gjr_r2 = qlike_pointwise(r2, g)
    dm_r2_t, dm_r2_p = dm_test(loss_har_r2, loss_gjr_r2)
    print(f"DM on r² target:      t = {dm_r2_t:.4f}, p = {dm_r2_p:.4f}")
    print(f"  → {'HAR better' if dm_r2_t < 0 else 'GJR better'} (need |t|>3.0 for Harvey)")

    # DM on RV_total target
    loss_har_rvtot = qlike_pointwise(rv_tot, h)
    loss_gjr_rvtot = qlike_pointwise(rv_tot, g)
    dm_rvtot_t, dm_rvtot_p = dm_test(loss_har_rvtot, loss_gjr_rvtot)
    print(f"DM on RV_total target: t = {dm_rvtot_t:.4f}, p = {dm_rvtot_p:.4f}")
    print(f"  → {'HAR better' if dm_rvtot_t < 0 else 'GJR better'}")

    # DM on RV_intraday target (HAR's native — expect HAR to win, mechanical)
    loss_har_rv = qlike_pointwise(rv_id, h)
    loss_gjr_rv = qlike_pointwise(rv_id, g)
    dm_rv_t, dm_rv_p = dm_test(loss_har_rv, loss_gjr_rv)
    print(f"DM on RV_intraday:     t = {dm_rv_t:.4f}, p = {dm_rv_p:.4f}")
    print(f"  → {'HAR better' if dm_rv_t < 0 else 'GJR better'} (mechanical if HAR wins)")

    results["dm_test"] = {
        "on_r2": {
            "t_stat": float(dm_r2_t),
            "p_value": float(dm_r2_p),
            "better": "HAR" if dm_r2_t < 0 else "GJR",
            "significant_harvey": abs(dm_r2_t) > 3.0,
        },
        "on_rv_total": {
            "t_stat": float(dm_rvtot_t),
            "p_value": float(dm_rvtot_p),
            "better": "HAR" if dm_rvtot_t < 0 else "GJR",
            "significant_harvey": abs(dm_rvtot_t) > 3.0,
        },
        "on_rv_intraday": {
            "t_stat": float(dm_rv_t),
            "p_value": float(dm_rv_p),
            "better": "HAR" if dm_rv_t < 0 else "GJR",
            "significant_harvey": abs(dm_rv_t) > 3.0,
            "note": "HAR winning here is MECHANICAL (native target), not empirical",
        },
        "warning": "PRELIMINARY: N too small for reliable DM test. Need 200+ OOS days.",
    }

    # ─── Layer 5: MSE and MAE for additional comparison ───
    print("\n--- Layer 5: MSE and MAE (supplementary) ---")

    # On r²
    mse_har_r2 = np.mean((r2 - h) ** 2)
    mse_gjr_r2 = np.mean((r2 - g) ** 2)
    mae_har_r2 = np.mean(np.abs(r2 - h))
    mae_gjr_r2 = np.mean(np.abs(r2 - g))

    print(f"MSE on r²: HAR={mse_har_r2:.2e}, GJR={mse_gjr_r2:.2e}")
    print(f"MAE on r²: HAR={mae_har_r2:.2e}, GJR={mae_gjr_r2:.2e}")

    # On RV_total
    mse_har_rvtot = np.mean((rv_tot - h) ** 2)
    mse_gjr_rvtot = np.mean((rv_tot - g) ** 2)
    mae_har_rvtot = np.mean(np.abs(rv_tot - h))
    mae_gjr_rvtot = np.mean(np.abs(rv_tot - g))

    print(f"MSE on RV_total: HAR={mse_har_rvtot:.2e}, GJR={mse_gjr_rvtot:.2e}")
    print(f"MAE on RV_total: HAR={mae_har_rvtot:.2e}, GJR={mae_gjr_rvtot:.2e}")

    results["mse_mae"] = {
        "on_r2": {
            "mse_har": float(mse_har_r2),
            "mse_gjr": float(mse_gjr_r2),
            "mae_har": float(mae_har_r2),
            "mae_gjr": float(mae_gjr_r2),
        },
        "on_rv_total": {
            "mse_har": float(mse_har_rvtot),
            "mse_gjr": float(mse_gjr_rvtot),
            "mae_har": float(mae_har_rvtot),
            "mae_gjr": float(mae_gjr_rvtot),
        },
    }

    # ─── Descriptive statistics ───
    print("\n--- Descriptive Stats ---")
    print(f"RV_intraday: mean={np.mean(rv_id):.6f}, std={np.std(rv_id):.6f}")
    print(f"RV_total:    mean={np.mean(rv_tot):.6f}, std={np.std(rv_tot):.6f}")
    print(f"r²:          mean={np.mean(r2):.6f}, std={np.std(r2):.6f}")
    print(f"HAR fcast:   mean={np.mean(h):.6f}, std={np.std(h):.6f}")
    print(f"GJR fcast:   mean={np.mean(g):.6f}, std={np.std(g):.6f}")

    # Variance ratio: overnight / total
    overnight_share = np.mean(rv_tot - rv_id) / np.mean(rv_tot)
    print(f"Overnight share of total vol: {overnight_share:.1%}")

    results["descriptive"] = {
        "rv_intraday_mean": float(np.mean(rv_id)),
        "rv_intraday_std": float(np.std(rv_id)),
        "rv_total_mean": float(np.mean(rv_tot)),
        "rv_total_std": float(np.std(rv_tot)),
        "r2_mean": float(np.mean(r2)),
        "r2_std": float(np.std(r2)),
        "har_fcast_mean": float(np.mean(h)),
        "har_fcast_std": float(np.std(h)),
        "gjr_fcast_mean": float(np.mean(g)),
        "gjr_fcast_std": float(np.std(g)),
        "overnight_share_of_total": float(overnight_share),
    }

    # ─── Correlation between models ───
    model_corr = np.corrcoef(h, g)[0, 1]
    model_spearman, _ = stats.spearmanr(h, g)
    print(f"\nModel correlation: Pearson={model_corr:.4f}, Spearman={model_spearman:.4f}")
    results["model_correlation"] = {
        "pearson": float(model_corr),
        "spearman": float(model_spearman),
    }

    return results


# ═══════════════════════════════════════════════════════════════
# Step 5: Simple VaR Comparison
# ═══════════════════════════════════════════════════════════════

def var_comparison(
    har_fcast: np.ndarray,
    gjr_fcast: np.ndarray,
    daily_ret: np.ndarray,
    gjr_nu: float,
    valid: np.ndarray,
) -> dict:
    """
    Simple VaR backtest at 5% and 1% levels.
    GJR: VaR = sigma * t_quantile (Student-t with nu df, scaled)
    HAR: VaR = sqrt(RV_forecast) * z_quantile (assume Normal for simplicity)
    """
    h = har_fcast[valid]
    g = gjr_fcast[valid]
    r = daily_ret[valid]
    n = len(r)

    results = {}
    for alpha, label in [(0.05, "5%"), (0.01, "1%")]:
        # GJR VaR (Student-t)
        t_q = stats.t.ppf(alpha, df=gjr_nu) * np.sqrt((gjr_nu - 2) / gjr_nu)
        gjr_var = np.sqrt(g) * t_q  # negative

        # HAR VaR (Normal approximation)
        z_q = stats.norm.ppf(alpha)
        har_var = np.sqrt(h) * z_q  # negative

        # Count violations
        gjr_violations = np.sum(r < gjr_var)
        har_violations = np.sum(r < har_var)

        gjr_vr = gjr_violations / n
        har_vr = har_violations / n

        # Kupiec LR test (if enough violations)
        def kupiec_lr(violations, total, expected_alpha):
            if violations == 0 or violations == total:
                return np.nan, np.nan
            p_hat = violations / total
            lr = -2 * (
                violations * np.log(expected_alpha / p_hat)
                + (total - violations) * np.log((1 - expected_alpha) / (1 - p_hat))
            )
            p_val = 1 - stats.chi2.cdf(lr, df=1)
            return float(lr), float(p_val)

        gjr_kupiec_lr, gjr_kupiec_p = kupiec_lr(gjr_violations, n, alpha)
        har_kupiec_lr, har_kupiec_p = kupiec_lr(har_violations, n, alpha)

        results[label] = {
            "expected_violations": float(alpha * n),
            "gjr": {
                "violations": int(gjr_violations),
                "violation_rate": float(gjr_vr),
                "kupiec_lr": gjr_kupiec_lr,
                "kupiec_p": gjr_kupiec_p,
            },
            "har": {
                "violations": int(har_violations),
                "violation_rate": float(har_vr),
                "kupiec_lr": har_kupiec_lr,
                "kupiec_p": har_kupiec_p,
            },
            "note": f"N={n} too small for reliable {label} VaR backtest",
        }

        print(f"\nVaR {label}: expected {alpha * n:.1f} violations out of {n}")
        print(f"  GJR: {gjr_violations} violations ({gjr_vr:.1%}), Kupiec p={gjr_kupiec_p:.4f}" if not np.isnan(gjr_kupiec_p) else f"  GJR: {gjr_violations} violations ({gjr_vr:.1%})")
        print(f"  HAR: {har_violations} violations ({har_vr:.1%}), Kupiec p={har_kupiec_p:.4f}" if not np.isnan(har_kupiec_p) else f"  HAR: {har_violations} violations ({har_vr:.1%})")

    return results


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    print("K906: SPY HAR-RV Preliminary Horse Race")
    print("=" * 60)

    # Paths — try worktree first, fall back to main repo
    base = Path(__file__).resolve().parent.parent
    data_dir = base / "data" / "intraday"
    if not data_dir.exists():
        # Try main repo
        data_dir = Path("/Users/yhlai0911/Desktop/volpred-research/data/intraday")

    print(f"Data directory: {data_dir}")

    # Step 1: Load 5-min data
    rv_df = load_5min_rv(str(data_dir))
    print(f"\nLoaded {len(rv_df)} trading days")
    print(f"Date range: {rv_df['date'].iloc[0].date()} to {rv_df['date'].iloc[-1].date()}")
    print(f"RV_intraday range: [{rv_df['rv_intraday'].min():.6f}, {rv_df['rv_intraday'].max():.6f}]")
    print(f"Annualized vol from RV_intraday: {np.sqrt(rv_df['rv_intraday'].mean() * 252) * 100:.1f}%")

    # Step 2: HAR-RV forecasts
    print("\n" + "=" * 60)
    print("Fitting HAR-RV model...")
    rv_series = rv_df["rv_intraday"].values
    har_forecasts = har_rv_forecast(rv_series, min_train=22)
    n_har_valid = np.sum(np.isfinite(har_forecasts))
    print(f"HAR produced {n_har_valid} valid forecasts")

    # Step 3: GJR-GARCH
    print("\n" + "=" * 60)
    print("Fitting GJR-GARCH(1,1) on daily data...")

    import yfinance as yf
    spy = yf.download("SPY", start="2015-01-01", end="2026-04-03", progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = [c[0] for c in spy.columns]
    spy_ret = np.log(spy["Close"] / spy["Close"].shift(1)).dropna()
    spy_ret.index = pd.to_datetime(spy_ret.index)

    # Remove timezone if present
    if spy_ret.index.tz is not None:
        spy_ret.index = spy_ret.index.tz_localize(None)

    print(f"SPY daily returns: {len(spy_ret)} days")
    print(f"Period: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()}")

    # OOS dates are the dates where we have RV and need forecasts
    # HAR produces forecasts starting from index min_train+1 (day 23+)
    # We want to compare on the same dates
    har_valid_mask = np.isfinite(har_forecasts)
    oos_rv_dates = rv_df.loc[har_valid_mask, "date"]
    oos_rv_dates_tz_free = pd.to_datetime(oos_rv_dates).dt.tz_localize(None) if oos_rv_dates.dt.tz is not None else pd.to_datetime(oos_rv_dates)

    # Make sure these dates exist in the daily returns
    common_dates = oos_rv_dates_tz_free[oos_rv_dates_tz_free.isin(spy_ret.index)]
    print(f"Common OOS dates: {len(common_dates)}")

    gjr_result = fit_gjr_garch_recursive(spy_ret, common_dates)

    # Align all arrays to common dates
    gjr_fcast_aligned = np.array([gjr_result["forecasts"][d] for d in common_dates])

    # Get HAR forecasts for common dates
    date_to_har = {}
    for i, row in rv_df.iterrows():
        if np.isfinite(har_forecasts[i]):
            d = row["date"]
            if d.tz is not None:
                d = d.tz_localize(None)
            date_to_har[d] = har_forecasts[i]
    har_fcast_aligned = np.array([date_to_har[d] for d in common_dates])

    # Get realized values for common dates
    date_to_rv = {}
    date_to_rv_total = {}
    date_to_r2 = {}
    date_to_ret = {}
    for i, row in rv_df.iterrows():
        d = row["date"]
        if hasattr(d, "tz") and d.tz is not None:
            d = d.tz_localize(None)
        date_to_rv[d] = row["rv_intraday"]
        date_to_rv_total[d] = row["rv_total"]
        date_to_r2[d] = row["daily_r2"]
        date_to_ret[d] = row["daily_ret"]

    rv_id_aligned = np.array([date_to_rv[d] for d in common_dates])
    rv_tot_aligned = np.array([date_to_rv_total[d] for d in common_dates])
    r2_aligned = np.array([date_to_r2[d] for d in common_dates])
    ret_aligned = np.array([date_to_ret[d] for d in common_dates])
    dates_aligned = np.array([str(d.date()) for d in common_dates])

    # Step 4: Fair comparison
    comparison = compute_comparison_metrics(
        har_fcast=har_fcast_aligned,
        gjr_fcast=gjr_fcast_aligned,
        rv_intraday=rv_id_aligned,
        rv_total=rv_tot_aligned,
        daily_r2=r2_aligned,
        dates=dates_aligned,
    )

    # Step 5: VaR comparison
    print("\n" + "=" * 60)
    print("VaR Backtest (PRELIMINARY)")
    valid_all = (
        np.isfinite(har_fcast_aligned)
        & np.isfinite(gjr_fcast_aligned)
        & np.isfinite(ret_aligned)
        & (har_fcast_aligned > 0)
        & (gjr_fcast_aligned > 0)
    )
    var_results = var_comparison(
        har_fcast=har_fcast_aligned,
        gjr_fcast=gjr_fcast_aligned,
        daily_ret=ret_aligned,
        gjr_nu=gjr_result["params"]["nu"],
        valid=valid_all,
    )

    # ═══════════════════════════════════════════════════════════
    # Compile final results
    # ═══════════════════════════════════════════════════════════

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY (PRELIMINARY — OOS < 252 days)")
    print("=" * 60)

    winner_r2 = comparison["qlike_on_r2"]["winner"]
    winner_rvtot = comparison["qlike_on_rv_total"]["winner"]

    print(f"QLIKE on r² (Patton 2011, primary): {winner_r2} wins")
    print(f"QLIKE on RV_total (Hansen & Lunde): {winner_rvtot} wins")
    print(f"DM on r²: t={comparison['dm_test']['on_r2']['t_stat']:.3f}, "
          f"{'significant' if comparison['dm_test']['on_r2']['significant_harvey'] else 'NOT significant'} (Harvey |t|>3)")
    print(f"Overnight share of total vol: {comparison['descriptive']['overnight_share_of_total']:.1%}")

    # Determine empirical conclusion
    if winner_r2 == winner_rvtot:
        conclusion = f"{winner_r2} preliminarily better on both unified targets"
    else:
        conclusion = f"Mixed: {winner_r2} better on r², {winner_rvtot} better on RV_total"

    print(f"\nConclusion: {conclusion}")
    print("⚠️ PRELIMINARY: Only ~33 OOS days. Must extend to 252+ for publication.")

    final_results = {
        "experiment_id": "K906",
        "title": "SPY HAR-RV Preliminary Horse Race",
        "data_source": "yfinance 5-min intraday (55 days) + daily (2500+ days)",
        "sample_period": f"{rv_df['date'].iloc[0].date()} to {rv_df['date'].iloc[-1].date()}",
        "oos_days": comparison["n_oos"],
        "oos_period": f"{comparison.get('oos_start', 'N/A')} to {comparison.get('oos_end', 'N/A')}",
        "status": "PRELIMINARY — OOS < 252-day minimum",
        "models": {
            "har_rv": {
                "specification": "Corsi (2009) HAR-RV: RV_{t+1} = b0 + b1*RV_t + b5*RV^(w) + b22*RV^(m)",
                "estimation": "Expanding window OLS, 22-day warm-up",
                "native_target": "5-min RV (intraday)",
            },
            "gjr_garch": {
                "specification": "GJR-GARCH(1,1) with Student-t innovations",
                "estimation": f"Fit on {gjr_result['params']['train_days']} daily returns, recursive OOS",
                "native_target": "r² (squared daily return)",
                "params": gjr_result["params"],
            },
        },
        "comparison": comparison,
        "var_backtest": var_results,
        "conclusion": conclusion,
        "limitations": [
            f"Only {comparison['n_oos']} OOS days — far below 252-day minimum",
            "HAR warm-up uses 22 of 55 available days, leaving small OOS",
            "DM test unreliable with N < 50",
            "VaR backtest statistically meaningless with ~30 observations",
            "HAR on Normal innovations (no HAR residual distribution fitting with this sample)",
            "No ES backtest (sample too small)",
            "Single asset (SPY only)",
        ],
        "references": [
            "Corsi (2009) 'A Simple Approximate Long-Memory Model of Realized Volatility' J. Fin. Econometrics",
            "Patton (2011) 'Volatility Forecast Comparison Using Imperfect Volatility Proxies' J. Econometrics",
            "Hansen & Lunde (2005) 'A Forecast Comparison of Volatility Models' J. Applied Econometrics",
            "Harvey (2016) 'Testing for Predictability' — |t| > 3.0 threshold",
        ],
        "next_steps": [
            "Extend 5-min data collection to 252+ trading days",
            "Add log-HAR variant",
            "Fit HAR residual distribution for proper VaR",
            "Include EGARCH in the horse race",
            "Test on 0050.TW with TAIFEX data for cross-market validation",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Save results (replace NaN with None for valid JSON)
    def sanitize_for_json(obj):
        if isinstance(obj, dict):
            return {k: sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [sanitize_for_json(v) for v in obj]
        elif isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
            return None
        return obj

    final_results = sanitize_for_json(final_results)
    results_path = Path(__file__).resolve().parent / "k906_spy_har_rv_preliminary_results.json"
    with open(results_path, "w") as f:
        json.dump(final_results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")

    return final_results


if __name__ == "__main__":
    main()
