#!/usr/bin/env python3
"""
K536: Extreme Value Theory (EVT) VaR/ES — Tail Risk Beyond Normal/Student-t
============================================================================
[提出: User, 執行: Claude]

Research Question:
  Does EVT (Peaks-over-Threshold + GPD) improve tail risk capture beyond
  Student-t? And does HAR-ABS vol prediction + EVT tail give the best VaR?

Literature basis:
  - McNeil & Frey (2000, JFE): "Estimation of tail-related risk measures
    for heteroscedastic financial time series" — canonical EVT-GARCH paper
  - Corsi (2009, JFE): HAR-RV model for volatility forecasting
  - K159: EVT-GPD gave 12/12 Kupiec pass but only 3/12 Trinity pass
  - K530: HAR-ABS beat GJR-GARCH (DM=-15.45) for vol forecasting

Method:
  1. Download SPY daily returns from yfinance (2005-2026)
  2. Five VaR models, all rolling window w=2000, OOS 2023-2024:
     A) GJR-GARCH + Normal VaR
     B) GJR-GARCH + Student-t VaR
     C) GJR-GARCH + EVT-GPD VaR (McNeil & Frey 2000)
     D) HAR-ABS + Normal VaR
     E) HAR-ABS + EVT-GPD VaR (novel combination)
     F) Historical Simulation VaR (benchmark)
  3. EVT details:
     - Threshold u = 90th percentile of |z_t| (bottom 10% of returns)
     - Fit GPD via MLE (scipy.stats.genpareto)
     - VaR_α = σ_t * [u + β/ξ * ((N_u/(n*α))^ξ - 1)]  [for ξ≠0]
     - ES_α = VaR_α/(1-ξ) + (β - ξu)/(1-ξ)
  4. Trinity test: Kupiec UC + Christoffersen CC + DQ test
  5. ES backtest: Acerbi-Szekely (2014)
  6. Alpha levels: 1%, 2.5%

Data source: yfinance (SPY, ^VIX)
Statistical constraints:
  - GARCH window >= 500 (using 2000)
  - OOS >= 252 days
  - Harvey threshold t > 3.0 for significance
  - Re-estimate every 21 days (computational efficiency)

Author: VolPred Research System
Date: 2026-03-27
"""

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from scipy.stats import genpareto

warnings.filterwarnings("ignore")

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

# ============================================================================
# Configuration
# ============================================================================
WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
DATA_START = "2005-01-01"
ALPHA_LEVELS = [0.01, 0.025]
POT_THRESHOLD_QUANTILE = 0.90
RE_ESTIMATE_EVERY = 21
HAR_WINDOW = 500  # HAR uses shorter window (OLS, fast)
SEED = 42
np.random.seed(SEED)

RESULTS_PATH = PROJECT_DIR / "experiments" / "k536_evt_var_results.json"

MODEL_NAMES = [
    "GJR-Normal",
    "GJR-Student-t",
    "GJR-EVT",
    "HAR-Normal",
    "HAR-EVT",
    "HistSim",
]


def print_section(title, char="=", width=76):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


# ============================================================================
# Data Loading
# ============================================================================
def load_data():
    """Download SPY + VIX daily data."""
    print_section("Data Loading")
    spy = yf.download("SPY", start=DATA_START, end="2025-06-01", progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=DATA_START, end="2025-06-01", progress=False, auto_adjust=True)

    for df in [spy, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    spy = spy.sort_index()
    vix = vix.sort_index()

    # Build combined DataFrame
    df = pd.DataFrame(index=spy.index)
    df["close"] = spy["Close"]
    df["log_return"] = np.log(spy["Close"] / spy["Close"].shift(1))
    df["vix"] = vix["Close"].reindex(spy.index, method="ffill")
    df = df.dropna()

    print(f"  SPY data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    print(f"  VIX range: {df['vix'].min():.1f} — {df['vix'].max():.1f}")

    # Descriptive stats
    r = df["log_return"].values
    print(f"\n  Return stats:")
    print(f"    Mean:     {r.mean()*252:.4f} (annualized)")
    print(f"    Std:      {r.std()*np.sqrt(252):.4f} (annualized)")
    print(f"    Skewness: {stats.skew(r):.3f}")
    print(f"    Kurtosis: {stats.kurtosis(r):.3f}")
    print(f"    Min:      {r.min():.4f}")
    print(f"    Max:      {r.max():.4f}")

    # ARCH LM test
    from statsmodels.stats.diagnostic import het_arch
    lm_stat, lm_p, _, _ = het_arch(r[~np.isnan(r)], nlags=10)
    print(f"    ARCH LM(10): stat={lm_stat:.2f}, p={lm_p:.6f}")

    return df


# ============================================================================
# EVT-GPD Functions (McNeil & Frey 2000)
# ============================================================================
def fit_gpd_pot(losses, threshold_quantile=0.90):
    """Fit GPD to exceedances over threshold.

    Parameters
    ----------
    losses : array
        Positive loss values (= -z_t for left tail of standardized residuals)
    threshold_quantile : float
        Quantile of losses to use as threshold

    Returns
    -------
    dict or None
    """
    losses = np.asarray(losses)
    threshold = np.quantile(losses, threshold_quantile)
    exceedances = losses[losses > threshold] - threshold
    n_exceed = len(exceedances)
    n_total = len(losses)

    if n_exceed < 20:
        return None

    try:
        # genpareto.fit with floc=0: F(x) = 1 - (1 + ξx/β)^{-1/ξ}
        xi, loc, beta = genpareto.fit(exceedances, floc=0)
    except Exception:
        return None

    # Sanity check
    if xi > 1.0 or xi < -1.0 or beta <= 0:
        return None

    return {
        "xi": float(xi),
        "beta": float(beta),
        "threshold": float(threshold),
        "n_exceed": int(n_exceed),
        "n_total": int(n_total),
    }


def evt_var_es(gpd_params, alpha):
    """Compute VaR and ES from GPD tail model (on standardized scale).

    Returns (var_z, es_z) — both positive (loss magnitudes on z scale).
    """
    xi = gpd_params["xi"]
    beta = gpd_params["beta"]
    u = gpd_params["threshold"]
    Nu = gpd_params["n_exceed"]
    n = gpd_params["n_total"]

    Fu = Nu / n  # exceedance probability

    # McNeil & Frey (2000) VaR formula
    if abs(xi) < 1e-8:
        # xi → 0: exponential tail
        var_z = u + beta * np.log(Fu / alpha)
    else:
        var_z = u + (beta / xi) * ((Fu / alpha) ** xi - 1)

    # ES formula
    if xi < 1.0:
        es_z = var_z / (1 - xi) + (beta - xi * u) / (1 - xi)
    else:
        es_z = var_z * 1.5  # fallback for infinite mean case

    return max(float(var_z), 0.001), max(float(es_z), float(var_z))


# ============================================================================
# HAR-ABS Model
# ============================================================================
def build_har_features(returns):
    """Build HAR-ABS features: RV1, RV5, RV22 from absolute returns."""
    abs_r = np.abs(returns)
    rv1 = abs_r.copy()
    rv5 = pd.Series(abs_r).rolling(5, min_periods=5).mean().values
    rv22 = pd.Series(abs_r).rolling(22, min_periods=22).mean().values
    return rv1, rv5, rv22


def har_ols_fit(X, y):
    """OLS with intercept. Returns coefficients."""
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        beta = np.zeros(X_aug.shape[1])
    return beta


def har_predict(rv1_t, rv5_t, rv22_t, beta):
    """Predict next-day |r| using HAR-ABS coefficients."""
    x = np.array([1.0, rv1_t, rv5_t, rv22_t])
    pred = np.dot(x, beta)
    return max(pred, 1e-8)


# ============================================================================
# Backtesting Functions
# ============================================================================
def kupiec_test(violations, n_obs, alpha):
    """Kupiec (1995) unconditional coverage test. H0: violation rate = α."""
    v = int(np.sum(violations))
    T = n_obs
    if v == 0 or v == T:
        return 0.0, 1.0

    pi_hat = v / T
    lr = 2 * (v * np.log(pi_hat / alpha) + (T - v) * np.log((1 - pi_hat) / (1 - alpha)))
    p_value = 1 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(p_value)


def christoffersen_test(violations):
    """Christoffersen (1998) conditional coverage test."""
    violations = np.asarray(violations, dtype=int)
    T = len(violations)

    n00 = n01 = n10 = n11 = 0
    for i in range(1, T):
        p, c = violations[i - 1], violations[i]
        if p == 0 and c == 0:
            n00 += 1
        elif p == 0 and c == 1:
            n01 += 1
        elif p == 1 and c == 0:
            n10 += 1
        else:
            n11 += 1

    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return 0.0, 1.0

    pi01 = n01 / (n00 + n01)
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    pi_hat = (n01 + n11) / T

    if pi01 <= 0 or pi01 >= 1:
        return 0.0, 1.0

    if pi11 <= 0 or pi11 >= 1:
        lr_ind = 0.0
    else:
        lr_ind = -2 * (
            (n00 + n10) * np.log(1 - pi_hat) + (n01 + n11) * np.log(pi_hat)
            - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
            - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
        )

    p_value = 1 - stats.chi2.cdf(max(lr_ind, 0), df=1)
    return float(lr_ind), float(p_value)


def dq_test(violations, var_series, alpha, n_lags=4):
    """Engle & Manganelli (2004) Dynamic Quantile test.

    Regress hit_t - α on lagged hits and VaR.
    H0: no predictability in violations.
    """
    hits = np.asarray(violations, dtype=float) - alpha
    T = len(hits)

    if T < n_lags + 5:
        return 0.0, 1.0

    # Build regressors: constant + lagged hits + VaR
    X_cols = [np.ones(T - n_lags)]
    for lag in range(1, n_lags + 1):
        X_cols.append(hits[n_lags - lag : T - lag])
    X_cols.append(var_series[n_lags:])

    X = np.column_stack(X_cols)
    y = hits[n_lags:]

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        y_hat = X @ beta
        resid = y - y_hat
        SSR = np.sum(y_hat ** 2)
        SST = np.sum(y ** 2)
        k = X.shape[1]
        n = len(y)
        if SST == 0:
            return 0.0, 1.0
        F_stat = (SSR / k) / (np.sum(resid ** 2) / (n - k)) if (n - k) > 0 else 0
        p_value = 1 - stats.f.cdf(F_stat, k, n - k) if F_stat > 0 else 1.0
    except Exception:
        return 0.0, 1.0

    return float(F_stat), float(p_value)


def acerbi_szekely_test(returns, es_series, var_series, alpha):
    """Acerbi & Szekely (2014) ES backtest.

    Test statistic Z2 = mean(r_t * I(r_t < VaR_t)) / (alpha * ES) + 1
    Under H0: Z2 = 0. Large positive Z2 → ES underestimates risk.
    """
    returns = np.asarray(returns)
    es_series = np.asarray(es_series)
    var_series = np.asarray(var_series)

    violations = returns < var_series
    n_violations = np.sum(violations)
    if n_violations == 0:
        return 0.0, 1.0

    # Z2 statistic
    T = len(returns)
    numerator = np.sum(returns[violations] / es_series[violations])
    Z2 = numerator / (T * alpha) + 1

    # Under H0, Z2 ~ N(0, σ²) approximately
    # Bootstrap p-value or use normal approximation
    # Simple one-sided test: reject H0 if Z2 > 0 (ES underestimates)
    # Approximate variance via bootstrap
    n_boot = 1000
    boot_stats = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.choice(T, T, replace=True)
        r_b = returns[idx]
        es_b = es_series[idx]
        var_b = var_series[idx]
        viol_b = r_b < var_b
        if np.sum(viol_b) > 0:
            num_b = np.sum(r_b[viol_b] / es_b[viol_b])
            boot_stats[b] = num_b / (T * alpha) + 1
        else:
            boot_stats[b] = 0.0

    se = np.std(boot_stats)
    if se > 0:
        t_stat = Z2 / se
        p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    else:
        t_stat = 0.0
        p_value = 1.0

    return float(t_stat), float(p_value)


# ============================================================================
# Main Rolling VaR Estimation
# ============================================================================
def run_rolling_var(df):
    """Run rolling VaR/ES estimation for all models."""
    print_section("Rolling VaR/ES Estimation")

    returns = df["log_return"].values
    dates = df.index

    # Find OOS indices
    oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
    oos_indices = np.where(oos_mask)[0]
    if len(oos_indices) == 0:
        raise ValueError("No OOS data found")

    oos_start_idx = oos_indices[0]
    oos_end_idx = oos_indices[-1]
    n_oos = len(oos_indices)

    print(f"  OOS period: {dates[oos_start_idx].date()} to {dates[oos_end_idx].date()}")
    print(f"  OOS observations: {n_oos}")
    print(f"  Window size: {WINDOW}")
    print(f"  Re-estimate every: {RE_ESTIMATE_EVERY} days")

    # Pre-compute HAR features for entire series
    rv1, rv5, rv22 = build_har_features(returns)

    # Storage for each model × alpha
    results = {
        alpha: {
            model: {
                "var": np.zeros(n_oos),
                "es": np.zeros(n_oos),
            }
            for model in MODEL_NAMES
        }
        for alpha in ALPHA_LEVELS
    }
    oos_returns = np.zeros(n_oos)

    # GARCH + HAR parameters (re-estimated periodically)
    garch_sigma = None
    garch_resid = None
    garch_params = None
    har_beta = None
    t_params = None  # (df, loc, scale)
    gpd_garch = None  # GPD from GARCH residuals
    gpd_har = None  # GPD from HAR residuals

    last_estimate = -RE_ESTIMATE_EVERY  # force first estimation

    t0 = time.time()
    for i, t_idx in enumerate(oos_indices):
        oos_returns[i] = returns[t_idx]

        # Window for estimation
        w_start = t_idx - WINDOW
        if w_start < 0:
            w_start = 0
        w_returns = returns[w_start:t_idx]

        need_refit = (i - last_estimate) >= RE_ESTIMATE_EVERY or i == 0

        if need_refit:
            last_estimate = i

            # ------ GJR-GARCH estimation ------
            try:
                am = arch_model(
                    w_returns * 100,  # scale for numerical stability
                    vol="GARCH", p=1, o=1, q=1, mean="Zero", dist="normal"
                )
                res = am.fit(disp="off", show_warning=False)
                # Get conditional variance for last observation
                cond_var = res.conditional_volatility.values[-1] / 100  # back to decimal
                garch_sigma = cond_var
                # Standardized residuals for distributional fitting
                resids_all = (w_returns * 100) / res.conditional_volatility.values
                garch_resid = resids_all  # standardized residuals

                # Fit Student-t to residuals
                df_t, loc_t, scale_t = stats.t.fit(garch_resid)
                df_t = np.clip(df_t, 2.1, 100)
                t_params = (df_t, loc_t, scale_t)

                # Fit GPD to left tail of residuals (losses = -z)
                losses = -garch_resid  # positive for left tail
                gpd_garch = fit_gpd_pot(losses, POT_THRESHOLD_QUANTILE)

                # Forecast sigma for next period using GARCH recursion
                omega = res.params.get("omega", 0.01)
                alpha1 = res.params.get("alpha[1]", 0.05)
                gamma1 = res.params.get("gamma[1]", 0.05)
                beta1 = res.params.get("beta[1]", 0.9)
                last_r = w_returns[-1] * 100
                last_var = res.conditional_volatility.values[-1] ** 2
                leverage = 1 if last_r < 0 else 0
                next_var = omega + (alpha1 + gamma1 * leverage) * last_r**2 + beta1 * last_var
                garch_sigma = np.sqrt(max(next_var, 1e-10)) / 100

            except Exception:
                if garch_sigma is None:
                    garch_sigma = np.std(w_returns)
                if t_params is None:
                    t_params = (5.0, 0.0, 1.0)

            # ------ HAR-ABS estimation ------
            w_rv1 = rv1[w_start:t_idx]
            w_rv5 = rv5[w_start:t_idx]
            w_rv22 = rv22[w_start:t_idx]

            # Valid indices (no NaN in rv22)
            har_start = max(22, 0)  # rv22 needs 22 obs warmup
            valid = ~(np.isnan(w_rv5) | np.isnan(w_rv22))
            valid[:har_start] = False

            if np.sum(valid) > 50:
                X_har = np.column_stack([
                    w_rv1[valid][:-1],
                    w_rv5[valid][:-1],
                    w_rv22[valid][:-1],
                ])
                y_har = np.abs(w_returns[1:])[valid[:-1] if len(valid) > len(w_returns[1:]) else valid[1:]]
                # Align properly
                idx_valid = np.where(valid)[0]
                idx_valid = idx_valid[idx_valid < len(w_returns) - 1]
                if len(idx_valid) > 50:
                    X_har = np.column_stack([
                        w_rv1[idx_valid],
                        w_rv5[idx_valid],
                        w_rv22[idx_valid],
                    ])
                    y_har = np.abs(w_returns[idx_valid + 1])
                    har_beta = har_ols_fit(X_har, y_har)

                    # HAR standardized residuals
                    har_pred = np.maximum(X_har @ har_beta[1:] + har_beta[0], 1e-8)
                    har_resid = w_returns[idx_valid + 1] / har_pred
                    # Fit GPD to HAR residuals left tail
                    har_losses = -har_resid
                    gpd_har = fit_gpd_pot(har_losses, POT_THRESHOLD_QUANTILE)

        # ------ Compute VaR/ES for each model at time t ------
        # GJR-GARCH sigma
        sigma_gjr = garch_sigma if garch_sigma is not None else np.std(w_returns)

        # HAR-ABS sigma (forecast next-day |r|)
        if har_beta is not None and t_idx > 22:
            sigma_har = har_predict(rv1[t_idx - 1], rv5[t_idx - 1], rv22[t_idx - 1], har_beta)
        else:
            sigma_har = np.mean(np.abs(w_returns[-22:]))

        for alpha in ALPHA_LEVELS:
            # Model A: GJR-Normal
            z_norm = stats.norm.ppf(alpha)
            results[alpha]["GJR-Normal"]["var"][i] = sigma_gjr * z_norm
            results[alpha]["GJR-Normal"]["es"][i] = sigma_gjr * (-stats.norm.pdf(z_norm) / alpha)

            # Model B: GJR-Student-t
            if t_params is not None:
                df_t, loc_t, scale_t = t_params
                z_t = stats.t.ppf(alpha, df_t, loc=loc_t, scale=scale_t)
                results[alpha]["GJR-Student-t"]["var"][i] = sigma_gjr * z_t
                # ES for Student-t
                t_pdf = stats.t.pdf(z_t, df_t, loc=loc_t, scale=scale_t)
                es_z = -scale_t * (df_t + ((z_t - loc_t) / scale_t) ** 2) / (df_t - 1) * t_pdf / alpha + loc_t
                results[alpha]["GJR-Student-t"]["es"][i] = sigma_gjr * es_z
            else:
                results[alpha]["GJR-Student-t"]["var"][i] = results[alpha]["GJR-Normal"]["var"][i]
                results[alpha]["GJR-Student-t"]["es"][i] = results[alpha]["GJR-Normal"]["es"][i]

            # Model C: GJR-EVT
            if gpd_garch is not None:
                var_z, es_z = evt_var_es(gpd_garch, alpha)
                results[alpha]["GJR-EVT"]["var"][i] = -sigma_gjr * var_z
                results[alpha]["GJR-EVT"]["es"][i] = -sigma_gjr * es_z
            else:
                results[alpha]["GJR-EVT"]["var"][i] = results[alpha]["GJR-Normal"]["var"][i]
                results[alpha]["GJR-EVT"]["es"][i] = results[alpha]["GJR-Normal"]["es"][i]

            # Model D: HAR-Normal
            results[alpha]["HAR-Normal"]["var"][i] = sigma_har * z_norm
            results[alpha]["HAR-Normal"]["es"][i] = sigma_har * (-stats.norm.pdf(z_norm) / alpha)

            # Model E: HAR-EVT
            if gpd_har is not None:
                var_z, es_z = evt_var_es(gpd_har, alpha)
                results[alpha]["HAR-EVT"]["var"][i] = -sigma_har * var_z
                results[alpha]["HAR-EVT"]["es"][i] = -sigma_har * es_z
            else:
                results[alpha]["HAR-EVT"]["var"][i] = results[alpha]["HAR-Normal"]["var"][i]
                results[alpha]["HAR-EVT"]["es"][i] = results[alpha]["HAR-Normal"]["es"][i]

            # Model F: Historical Simulation
            hist_returns = w_returns.copy()
            hist_returns.sort()
            hs_idx = max(int(alpha * len(hist_returns)), 1)
            hs_var = hist_returns[hs_idx - 1]
            hs_es = np.mean(hist_returns[:hs_idx])
            results[alpha]["HistSim"]["var"][i] = hs_var
            results[alpha]["HistSim"]["es"][i] = hs_es

        # Progress
        if (i + 1) % 100 == 0 or i == n_oos - 1:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            remaining = (n_oos - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{n_oos}] {elapsed:.1f}s elapsed, ~{remaining:.0f}s remaining")

    return oos_returns, results, dates[oos_indices]


# ============================================================================
# Evaluation
# ============================================================================
def evaluate_models(oos_returns, results, oos_dates):
    """Evaluate all models with Trinity test + ES backtest."""
    print_section("Model Evaluation")

    all_results = {}

    for alpha in ALPHA_LEVELS:
        print(f"\n  --- Alpha = {alpha} ({alpha*100:.1f}% VaR) ---")
        print(f"  {'Model':<18} {'Viol%':>7} {'N_viol':>7} {'Kupiec':>10} {'CC':>10} {'DQ':>10} {'Trinity':>8} {'ES_t':>8}")
        print(f"  {'-'*90}")

        alpha_results = {}

        for model in MODEL_NAMES:
            var_series = results[alpha][model]["var"]
            es_series = results[alpha][model]["es"]

            # Violations
            violations = (oos_returns < var_series).astype(int)
            n_viol = int(np.sum(violations))
            viol_rate = n_viol / len(oos_returns)

            # Kupiec test
            kup_lr, kup_p = kupiec_test(violations, len(oos_returns), alpha)
            kup_pass = kup_p > 0.05

            # Christoffersen test
            cc_lr, cc_p = christoffersen_test(violations)
            cc_pass = cc_p > 0.05

            # DQ test
            dq_f, dq_p = dq_test(violations, var_series, alpha)
            dq_pass = dq_p > 0.05

            # Trinity: all three pass
            trinity = kup_pass and cc_pass and dq_pass

            # Acerbi-Szekely ES test
            es_t, es_p = acerbi_szekely_test(oos_returns, es_series, var_series, alpha)

            print(
                f"  {model:<18} {viol_rate:>7.3f} {n_viol:>7d} "
                f"{'PASS' if kup_pass else 'FAIL':>5}({kup_p:.3f}) "
                f"{'PASS' if cc_pass else 'FAIL':>5}({cc_p:.3f}) "
                f"{'PASS' if dq_pass else 'FAIL':>5}({dq_p:.3f}) "
                f"{'PASS' if trinity else 'FAIL':>8} "
                f"{es_t:>8.2f}"
            )

            alpha_results[model] = {
                "violation_rate": round(viol_rate, 6),
                "n_violations": n_viol,
                "expected_violations": round(alpha * len(oos_returns), 1),
                "kupiec": {
                    "LR": round(kup_lr, 4),
                    "p_value": round(kup_p, 6),
                    "pass": kup_pass,
                },
                "christoffersen": {
                    "LR": round(cc_lr, 4),
                    "p_value": round(cc_p, 6),
                    "pass": cc_pass,
                },
                "dq_test": {
                    "F_stat": round(dq_f, 4),
                    "p_value": round(dq_p, 6),
                    "pass": dq_pass,
                },
                "trinity_pass": trinity,
                "es_backtest": {
                    "t_stat": round(es_t, 4),
                    "p_value": round(es_p, 6),
                    "pass": es_p > 0.05,
                },
            }

        all_results[str(alpha)] = alpha_results

    return all_results


def compute_var_calibration(oos_returns, results):
    """Compute mean absolute VaR calibration error."""
    print_section("VaR Calibration Error")

    calibration = {}
    for alpha in ALPHA_LEVELS:
        print(f"\n  Alpha = {alpha}:")
        for model in MODEL_NAMES:
            var_series = results[alpha][model]["var"]
            violations = oos_returns < var_series
            actual_rate = np.mean(violations)
            abs_error = abs(actual_rate - alpha)
            calibration[f"{model}_{alpha}"] = {
                "actual_rate": round(float(actual_rate), 6),
                "expected_rate": alpha,
                "abs_error": round(float(abs_error), 6),
            }
            print(f"    {model:<18}: actual={actual_rate:.4f}, expected={alpha:.4f}, |error|={abs_error:.4f}")

    return calibration


def compute_gpd_diagnostics(df):
    """Compute GPD parameter diagnostics on full sample."""
    print_section("GPD Parameter Diagnostics (Full Sample)")

    returns = df["log_return"].values

    # Fit GJR-GARCH on full sample for diagnostics
    try:
        am = arch_model(returns * 100, vol="GARCH", p=1, o=1, q=1, mean="Zero", dist="normal")
        res = am.fit(disp="off", show_warning=False)
        cond_vol = np.asarray(res.conditional_volatility)
        resids = (returns * 100) / cond_vol
        losses = -resids

        gpd = fit_gpd_pot(losses, POT_THRESHOLD_QUANTILE)
        if gpd:
            print(f"  GJR-GARCH standardized residuals:")
            print(f"    GPD shape (ξ):     {gpd['xi']:.4f}")
            print(f"    GPD scale (β):     {gpd['beta']:.4f}")
            print(f"    Threshold (u):     {gpd['threshold']:.4f}")
            print(f"    N exceedances:     {gpd['n_exceed']}")
            print(f"    Total observations:{gpd['n_total']}")
            print(f"    ξ > 0 → heavy tail (Fréchet domain)")
            print(f"    ξ interpretation:  {'Heavy tail' if gpd['xi'] > 0 else 'Bounded tail' if gpd['xi'] < 0 else 'Exponential tail'}")

            # Goodness-of-fit: QQ-plot correlation
            exceedances = losses[losses > gpd['threshold']] - gpd['threshold']
            theoretical_q = genpareto.ppf(
                np.linspace(0.01, 0.99, len(exceedances)),
                gpd['xi'], loc=0, scale=gpd['beta']
            )
            empirical_q = np.sort(exceedances)
            qq_corr = np.corrcoef(theoretical_q, empirical_q[:len(theoretical_q)])[0, 1]
            print(f"    QQ-plot correlation: {qq_corr:.4f}")

            return {
                "xi": round(gpd['xi'], 4),
                "beta": round(gpd['beta'], 4),
                "threshold": round(gpd['threshold'], 4),
                "n_exceed": gpd['n_exceed'],
                "qq_correlation": round(qq_corr, 4),
            }
    except Exception as e:
        print(f"  Error: {e}")

    return {}


def analyze_tail_events(oos_returns, results, oos_dates):
    """Analyze model behavior during extreme tail events."""
    print_section("Tail Event Analysis")

    # Find the worst 5 days
    worst_idx = np.argsort(oos_returns)[:5]

    print(f"  Worst 5 return days in OOS:")
    print(f"  {'Date':<12} {'Return':>8}  ", end="")
    for model in MODEL_NAMES:
        print(f"{model[:8]:>10}", end="")
    print()

    tail_analysis = []
    for idx in worst_idx:
        date_str = str(oos_dates[idx].date())
        ret = oos_returns[idx]
        print(f"  {date_str:<12} {ret:>8.4f}  ", end="")

        event = {"date": date_str, "return": round(float(ret), 6), "var_1pct": {}}
        for model in MODEL_NAMES:
            var_1 = results[0.01][model]["var"][idx]
            caught = "✓" if ret >= var_1 else "✗"
            print(f" {var_1:>7.4f}{caught}", end="")
            event["var_1pct"][model] = {
                "var": round(float(var_1), 6),
                "caught": ret >= var_1,
            }
        print()
        tail_analysis.append(event)

    return tail_analysis


# ============================================================================
# Summary and Ranking
# ============================================================================
def compute_rankings(eval_results):
    """Rank models by Trinity pass count and calibration."""
    print_section("Model Rankings")

    scores = {model: 0 for model in MODEL_NAMES}
    for alpha_str, alpha_results in eval_results.items():
        for model, res in alpha_results.items():
            if res["kupiec"]["pass"]:
                scores[model] += 1
            if res["christoffersen"]["pass"]:
                scores[model] += 1
            if res["dq_test"]["pass"]:
                scores[model] += 1
            if res["trinity_pass"]:
                scores[model] += 2  # bonus for full Trinity
            if res["es_backtest"]["pass"]:
                scores[model] += 1

    # Sort by score
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    print(f"\n  Overall Ranking (Kupiec+CC+DQ+Trinity+ES points):")
    for rank, (model, score) in enumerate(ranked, 1):
        print(f"    {rank}. {model:<18} score={score}")

    return {model: score for model, score in ranked}


# ============================================================================
# Main
# ============================================================================
def main():
    t_start = time.time()

    print("=" * 76)
    print("  K536: EVT-VaR — Extreme Value Theory for Tail Risk")
    print("  McNeil & Frey (2000) + HAR-ABS (K530)")
    print("=" * 76)
    print(f"  Date:   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Asset:  SPY")
    print(f"  Window: {WINDOW}")
    print(f"  OOS:    {OOS_START} to {OOS_END}")
    print(f"  Alphas: {ALPHA_LEVELS}")
    print(f"  Models: {MODEL_NAMES}")

    # Step 1: Load data
    df = load_data()

    # Step 2: GPD diagnostics
    gpd_diag = compute_gpd_diagnostics(df)

    # Step 3: Rolling VaR estimation
    oos_returns, results, oos_dates = run_rolling_var(df)

    # Step 4: Evaluate
    eval_results = evaluate_models(oos_returns, results, oos_dates)

    # Step 5: Calibration
    calibration = compute_var_calibration(oos_returns, results)

    # Step 6: Tail events
    tail_events = analyze_tail_events(oos_returns, results, oos_dates)

    # Step 7: Rankings
    rankings = compute_rankings(eval_results)

    # Summary
    elapsed = time.time() - t_start
    print_section("Summary")

    # Key findings
    n_oos = len(oos_returns)
    findings = []

    for alpha in ALPHA_LEVELS:
        alpha_str = str(alpha)
        # Count Trinity passes per model
        for model in MODEL_NAMES:
            r = eval_results[alpha_str][model]
            vr = r["violation_rate"]
            findings.append(
                f"{model} @ {alpha*100:.1f}%: viol_rate={vr:.4f} "
                f"(expected {alpha:.4f}), Trinity={'PASS' if r['trinity_pass'] else 'FAIL'}"
            )

    # GPD summary
    if gpd_diag:
        findings.append(f"GPD shape ξ={gpd_diag['xi']:.4f} ({'heavy tail' if gpd_diag['xi'] > 0 else 'bounded'})")
        findings.append(f"GPD QQ-correlation={gpd_diag.get('qq_correlation', 'N/A')}")

    # Best model
    best = max(rankings.items(), key=lambda x: x[1])
    findings.append(f"Best model: {best[0]} (score={best[1]})")

    print(f"\n  Key findings:")
    for f in findings:
        print(f"    • {f}")

    print(f"\n  Total runtime: {elapsed:.1f}s")

    # Save results
    output = {
        "experiment_id": "K536",
        "title": "K536: EVT-VaR — Extreme Value Theory for Tail Risk Beyond Normal/Student-t",
        "timestamp": datetime.now().isoformat(),
        "proposer": "User",
        "executor": "Claude",
        "references": [
            "McNeil & Frey (2000, JFE): EVT-GARCH canonical paper",
            "Corsi (2009, JFE): HAR-RV model",
            "K159: Prior EVT experiment (12/12 Kupiec, 3/12 Trinity)",
            "K530: HAR-ABS best vol predictor (DM=-15.45 vs GJR)",
        ],
        "data_source": "yfinance (SPY, ^VIX)",
        "data_period": f"{DATA_START} to 2025",
        "config": {
            "asset": "SPY",
            "window": WINDOW,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "alpha_levels": ALPHA_LEVELS,
            "pot_threshold_quantile": POT_THRESHOLD_QUANTILE,
            "re_estimate_every": RE_ESTIMATE_EVERY,
            "har_window": HAR_WINDOW,
            "models": MODEL_NAMES,
        },
        "gpd_diagnostics": gpd_diag,
        "evaluation": eval_results,
        "calibration": calibration,
        "tail_events": tail_events,
        "rankings": rankings,
        "n_oos": n_oos,
        "findings": findings,
        "runtime_seconds": round(elapsed, 1),
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to: {RESULTS_PATH}")
    return output


if __name__ == "__main__":
    main()
