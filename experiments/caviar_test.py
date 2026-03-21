"""CAViaR (Conditional Autoregressive Value at Risk) — Engle & Manganelli (2004)

CAViaR models the VaR quantile DIRECTLY, without requiring a distribution assumption.
This is fundamentally different from GARCH-based VaR (which estimates sigma then maps to quantile).

Four specifications:
1. Symmetric Absolute Value (SAV): q_t = b0 + b1*q_{t-1} + b2*|r_{t-1}|
2. Asymmetric Slope (AS): q_t = b0 + b1*q_{t-1} + b2*max(r_{t-1},0) + b3*min(r_{t-1},0)
3. Indirect GARCH (IG): q_t = (b0 + b1*q^2_{t-1} + b2*r^2_{t-1})^0.5
4. Adaptive (AD): q_t = q_{t-1} + b1*[1/(1+exp(G*(r_{t-1}-q_{t-1}))) - alpha]

Estimation: Quantile regression via RQ(beta) = sum rho_alpha(r_t - q_t(beta))
where rho_alpha(u) = u*(alpha - I(u<0)) is the check function.

OOS Strategy: Parameters re-estimated monthly, VaR updated daily via recursion.
This is both computationally efficient and realistic (monthly recalibration).

Comparison target: GJR-GARCH Skewed-t VaR (our current best).

[Proposer: User, Executor: Claude]
Author: VolPred Research System
"""

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import optimize, stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
WINDOW = 2000           # Rolling estimation window
START_DATE = "2006-01-01"
END_DATE = "2025-12-31"
EVAL_START = "2020-01-02"   # OOS period 2020-2025
G_ADAPTIVE = 10.0       # Smoothing parameter for adaptive specification
N_RESTARTS = 3           # Number of random restarts for optimizer


# ============================================================================
# Data
# ============================================================================
def download_data():
    """Download SPY data."""
    print("Downloading SPY data...", flush=True)
    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    print(f"  Data: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()}, {len(spy_ret)} days",
          flush=True)
    return spy_ret


# ============================================================================
# CAViaR Specifications
# ============================================================================
def caviar_sav(params, returns, alpha, q0):
    """Symmetric Absolute Value: q_t = b0 + b1*q_{t-1} + b2*|r_{t-1}|"""
    b0, b1, b2 = params
    T = len(returns)
    q = np.empty(T)
    q[0] = q0
    for t in range(1, T):
        q[t] = b0 + b1 * q[t-1] + b2 * abs(returns[t-1])
    return q


def caviar_as(params, returns, alpha, q0):
    """Asymmetric Slope: q_t = b0 + b1*q_{t-1} + b2*max(r,0) + b3*min(r,0)"""
    b0, b1, b2, b3 = params
    T = len(returns)
    q = np.empty(T)
    q[0] = q0
    r_pos = np.maximum(returns, 0.0)
    r_neg = np.minimum(returns, 0.0)
    for t in range(1, T):
        q[t] = b0 + b1 * q[t-1] + b2 * r_pos[t-1] + b3 * r_neg[t-1]
    return q


def caviar_ig(params, returns, alpha, q0):
    """Indirect GARCH: q_t = sqrt(b0 + b1*q^2_{t-1} + b2*r^2_{t-1})"""
    b0, b1, b2 = params
    T = len(returns)
    q = np.empty(T)
    q[0] = abs(q0)
    r2 = returns ** 2
    for t in range(1, T):
        inside = b0 + b1 * q[t-1]**2 + b2 * r2[t-1]
        q[t] = np.sqrt(max(inside, 1e-10))
    return q


def caviar_adaptive(params, returns, alpha, q0):
    """Adaptive: q_t = q_{t-1} + b1*[logistic(G*(r_{t-1}-q_{t-1})) - alpha]"""
    b1 = params[0]
    T = len(returns)
    q = np.empty(T)
    q[0] = q0
    for t in range(1, T):
        z = G_ADAPTIVE * (returns[t-1] - q[t-1])
        z = np.clip(z, -500, 500)
        logistic = 1.0 / (1.0 + np.exp(z))
        q[t] = q[t-1] + b1 * (logistic - alpha)
    return q


SPEC_MAP = {
    "SAV": (caviar_sav, 3),
    "AS":  (caviar_as, 4),
    "IG":  (caviar_ig, 3),
    "AD":  (caviar_adaptive, 1),
}


# ============================================================================
# Quantile Regression Loss
# ============================================================================
def rq_loss(params, returns, alpha, q0, spec_func):
    """Check function loss: RQ(beta) = mean rho_alpha(r_t - q_t)"""
    q = spec_func(params, returns, alpha, q0)
    u = returns - q
    loss = np.where(u >= 0, alpha * u, (alpha - 1.0) * u)
    return np.mean(loss)


# ============================================================================
# Parameter Estimation
# ============================================================================
def get_initial_params(spec_name, emp_q, returns, seed=0):
    """Generate initial parameter guess for a CAViaR specification."""
    rng = np.random.RandomState(seed)
    mean_abs_r = np.mean(np.abs(returns))
    mean_r2 = np.mean(returns**2)

    if spec_name == "SAV":
        b1 = 0.95 + rng.uniform(-0.04, 0.03)
        b2 = rng.uniform(0.01, 0.5)
        b0 = emp_q * (1 - b1) - b2 * mean_abs_r
        return [b0, b1, b2]
    elif spec_name == "AS":
        b1 = 0.95 + rng.uniform(-0.04, 0.03)
        b2 = rng.uniform(-0.5, 0.1)
        b3 = rng.uniform(-1.0, -0.1)
        b0 = emp_q * (1 - b1)
        return [b0, b1, b2, b3]
    elif spec_name == "IG":
        b1 = 0.90 + rng.uniform(-0.05, 0.05)
        b2 = rng.uniform(0.01, 0.3)
        b0 = max(emp_q**2 * (1 - b1) - b2 * mean_r2, 1e-8)
        return [b0, b1, b2]
    elif spec_name == "AD":
        return [rng.uniform(0.01, 1.0)]


def estimate_caviar(returns, alpha, spec_name="SAV"):
    """Estimate CAViaR parameters via quantile regression with multiple restarts."""
    emp_q = np.quantile(returns, alpha)
    spec_func, _ = SPEC_MAP[spec_name]
    q0 = emp_q

    best_result = None
    best_loss = np.inf

    for restart in range(N_RESTARTS):
        x0 = get_initial_params(spec_name, emp_q, returns, seed=restart * 42 + 7)
        try:
            result = optimize.minimize(
                rq_loss, x0=x0,
                args=(returns, alpha, q0, spec_func),
                method="Nelder-Mead",
                options={"maxiter": 5000, "xatol": 1e-7, "fatol": 1e-9}
            )
            if result.fun < best_loss:
                best_loss = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None:
        return {
            "params": get_initial_params(spec_name, emp_q, returns, 0),
            "loss": np.inf, "q_series": np.full(len(returns), emp_q),
            "spec": spec_name, "success": False,
        }

    q_series = spec_func(best_result.x, returns, alpha, q0)
    return {
        "params": best_result.x.tolist(), "loss": float(best_result.fun),
        "q_series": q_series, "spec": spec_name, "success": best_result.success,
    }


# ============================================================================
# 1-Step Forecast
# ============================================================================
def caviar_forecast_1step(params, last_q, last_return, alpha, spec_name):
    """Produce 1-step ahead VaR forecast given estimated params."""
    if spec_name == "SAV":
        b0, b1, b2 = params
        return b0 + b1 * last_q + b2 * abs(last_return)
    elif spec_name == "AS":
        b0, b1, b2, b3 = params
        return b0 + b1 * last_q + b2 * max(last_return, 0.0) + b3 * min(last_return, 0.0)
    elif spec_name == "IG":
        b0, b1, b2 = params
        inside = b0 + b1 * last_q**2 + b2 * last_return**2
        return np.sqrt(max(inside, 1e-10))
    elif spec_name == "AD":
        b1 = params[0]
        z = G_ADAPTIVE * (last_return - last_q)
        z = np.clip(z, -500, 500)
        logistic = 1.0 / (1.0 + np.exp(z))
        return last_q + b1 * (logistic - alpha)


# ============================================================================
# Monthly Re-estimation Rolling Backtest
# ============================================================================
def rolling_caviar_backtest(returns_series, alpha, spec_name, window=WINDOW):
    """OOS backtest with monthly re-estimation, daily VaR updates via recursion.

    Strategy:
    - At the start of each month, re-estimate CAViaR on the trailing `window` days
    - During the month, update VaR daily using the estimated recursion
    - This is computationally tractable (~60 estimations instead of ~1300)
    """
    eval_mask = returns_series.index >= EVAL_START
    eval_dates = returns_series.index[eval_mask]

    # Group OOS dates by (year, month)
    oos_months = pd.Series(eval_dates).groupby(
        [eval_dates.year, eval_dates.month]
    ).apply(list)

    results = []
    fit_failures = 0
    total_months = len(oos_months)

    current_params = None
    current_q = None

    for m_idx, (ym, month_dates) in enumerate(oos_months.items()):
        first_date = month_dates[0]
        first_pos = returns_series.index.get_loc(first_date)

        if first_pos < window:
            continue

        # Re-estimate at month start
        train_ret = returns_series.iloc[first_pos - window:first_pos].values
        print(f"    {spec_name} a={alpha}: month {m_idx+1}/{total_months} "
              f"({first_date.strftime('%Y-%m')})", flush=True)

        try:
            est = estimate_caviar(train_ret, alpha, spec_name)
            if est["success"] or est["loss"] < np.inf:
                current_params = est["params"]
                # Initialize q from end of in-sample fit
                current_q = est["q_series"][-1]
            else:
                fit_failures += 1
                if current_params is None:
                    current_params = est["params"]
                    current_q = np.quantile(train_ret, alpha)
        except Exception:
            fit_failures += 1
            if current_params is None:
                current_params = get_initial_params(
                    spec_name, np.quantile(train_ret, alpha), train_ret, 0
                )
                current_q = np.quantile(train_ret, alpha)

        # Daily forecasts within this month
        for date in month_dates:
            pos = returns_series.index.get_loc(date)
            if pos < window:
                continue

            last_return = returns_series.iloc[pos - 1]

            # 1-step forecast
            var_fcast = caviar_forecast_1step(
                current_params, current_q, last_return, alpha, spec_name
            )

            actual = returns_series.iloc[pos]

            results.append({
                "date": date,
                "var_forecast": float(var_fcast),
                "actual_return": float(actual),
                "violation": int(actual < var_fcast),
            })

            # Update q for next day (use actual return, not forecast)
            current_q = var_fcast

    if fit_failures > 0:
        print(f"    {spec_name}: {fit_failures}/{total_months} month fit failures", flush=True)

    return pd.DataFrame(results).set_index("date")


def rolling_garch_backtest(returns_series, alpha, window=WINDOW):
    """Monthly re-estimation GJR-GARCH Skewed-t benchmark.

    Re-estimates monthly (like CAViaR) for fair comparison.
    Between re-estimations, uses GARCH recursion to update sigma daily.
    """
    from arch import arch_model
    from arch.univariate.distribution import SkewStudent

    eval_mask = returns_series.index >= EVAL_START
    eval_dates = returns_series.index[eval_mask]

    oos_months = pd.Series(eval_dates).groupby(
        [eval_dates.year, eval_dates.month]
    ).apply(list)

    results = []
    fit_failures = 0
    total_months = len(oos_months)

    # Initialize with reasonable defaults
    current_omega = 0.01
    current_alpha1 = 0.05
    current_beta1 = 0.90
    current_gamma = 0.10
    current_nu = 5.0
    current_lam = 0.0
    current_sigma2 = None  # will be set on first fit

    for m_idx, (ym, month_dates) in enumerate(oos_months.items()):
        first_date = month_dates[0]
        first_pos = returns_series.index.get_loc(first_date)

        if first_pos < window:
            continue

        train_ret = returns_series.iloc[first_pos - window:first_pos].values
        train_ret_pct = train_ret * 100

        print(f"    GARCH-SkewT a={alpha}: month {m_idx+1}/{total_months} "
              f"({first_date.strftime('%Y-%m')})", flush=True)

        try:
            model = arch_model(
                train_ret_pct, vol="GARCH", p=1, o=1, q=1,
                dist="skewt", mean="Zero", rescale=False
            )
            res = model.fit(disp="off", show_warning=False)
            params = dict(res.params)

            current_omega = params.get("omega", 0.01)
            current_alpha1 = params.get("alpha[1]", 0.05)
            current_beta1 = params.get("beta[1]", 0.90)
            current_gamma = params.get("gamma[1]", 0.10)
            current_nu = params.get("nu", 5.0)
            current_lam = params.get("lambda", 0.0)

            # Get last conditional variance from fit
            cond_vol = res.conditional_volatility
            current_sigma2 = float(cond_vol.iloc[-1]) ** 2

        except Exception as e:
            fit_failures += 1
            if current_sigma2 is None:
                current_sigma2 = float(np.var(train_ret_pct))

        if current_sigma2 is None:
            current_sigma2 = float(np.var(train_ret_pct))

        skewt = SkewStudent()

        for date in month_dates:
            pos = returns_series.index.get_loc(date)
            if pos < window:
                continue

            last_ret_pct = float(returns_series.iloc[pos - 1]) * 100

            # GARCH(1,1) with leverage: sigma2_t = omega + (alpha + gamma*I)*r^2 + beta*sigma2
            indicator = 1.0 if last_ret_pct < 0 else 0.0
            current_sigma2 = float(current_omega
                              + (current_alpha1 + current_gamma * indicator) * last_ret_pct**2
                              + current_beta1 * current_sigma2)

            sigma_pct = np.sqrt(max(current_sigma2, 1e-10))
            sigma = sigma_pct / 100

            quantile = skewt.ppf(alpha, parameters=np.array([current_nu, current_lam]))
            var_fcast = sigma * quantile  # negative number (left tail)

            actual = returns_series.iloc[pos]

            results.append({
                "date": date,
                "var_forecast": float(var_fcast),
                "actual_return": float(actual),
                "violation": int(actual < var_fcast),
            })

    if fit_failures > 0:
        print(f"    GARCH-SkewT: {fit_failures}/{total_months} month fit failures", flush=True)

    return pd.DataFrame(results).set_index("date")


# ============================================================================
# Statistical Tests
# ============================================================================
def kupiec_test(violations, alpha):
    """Kupiec POF test for unconditional coverage."""
    T = len(violations)
    n = int(np.sum(violations))
    p_hat = n / T
    if n == 0 or n == T:
        return {"statistic": np.inf, "p_value": 0.0, "observed_rate": p_hat,
                "expected_rate": alpha, "n_violations": n, "total": T, "conclusion": "reject"}
    lr = -2 * (np.log((1 - alpha)**(T - n) * alpha**n)
               - np.log((1 - p_hat)**(T - n) * p_hat**n))
    p_value = 1 - sp_stats.chi2.cdf(lr, 1)
    return {
        "statistic": float(lr), "p_value": float(p_value),
        "observed_rate": float(p_hat), "expected_rate": alpha,
        "n_violations": n, "total": T,
        "conclusion": "reject" if p_value < 0.05 else "pass",
    }


def christoffersen_test(violations):
    """Christoffersen independence test."""
    T = len(violations)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        i, j = int(violations[t-1]), int(violations[t])
        if i == 0 and j == 0: n00 += 1
        elif i == 0 and j == 1: n01 += 1
        elif i == 1 and j == 0: n10 += 1
        else: n11 += 1
    pi01 = n01 / max(n00 + n01, 1)
    pi11 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(T - 1, 1)
    if pi01 <= 0 or pi11 <= 0 or pi01 >= 1 or pi11 >= 1 or pi <= 0 or pi >= 1:
        lr_ind = 0.0
    else:
        lr_ind = -2 * (
            (n00 + n10) * np.log(1 - pi) + (n01 + n11) * np.log(pi)
            - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
            - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
        )
    p_ind = 1 - sp_stats.chi2.cdf(max(lr_ind, 0), 1)
    return {
        "independence_stat": float(lr_ind), "independence_pval": float(p_ind),
        "n00": n00, "n01": n01, "n10": n10, "n11": n11,
        "conclusion": "independent" if p_ind >= 0.05 else "clustered",
    }


def dq_test(returns, var_forecasts, alpha, n_lags=4):
    """Dynamic Quantile test (Engle & Manganelli 2004).

    Tests whether Hit_t = I(r_t < VaR_t) - alpha is unpredictable
    given lagged Hits and current VaR.
    """
    hits = (returns < var_forecasts).astype(float) - alpha
    T = len(hits)
    if T <= n_lags + 1:
        return {"dq_statistic": np.nan, "p_value": np.nan, "df": 0, "conclusion": "N/A"}

    X_list = [np.ones(T - n_lags)]
    for lag in range(1, n_lags + 1):
        X_list.append(hits[n_lags - lag: T - lag])
    X_list.append(var_forecasts[n_lags:])
    X = np.column_stack(X_list)
    y = hits[n_lags:]

    try:
        XtX = X.T @ X
        XtX_inv = np.linalg.inv(XtX + 1e-10 * np.eye(XtX.shape[0]))
        beta = XtX_inv @ (X.T @ y)
        dq_stat = float(beta.T @ XtX @ beta / (alpha * (1 - alpha)))
        df = X.shape[1]
        p_value = 1 - sp_stats.chi2.cdf(dq_stat, df)
    except np.linalg.LinAlgError:
        dq_stat, p_value, df = np.nan, np.nan, 0

    return {
        "dq_statistic": float(dq_stat), "p_value": float(p_value),
        "df": df, "conclusion": "pass" if p_value >= 0.05 else "reject",
    }


def dm_test_rq(rq_losses_1, rq_losses_2):
    """Diebold-Mariano test on tick (RQ) losses."""
    d = rq_losses_1 - rq_losses_2
    T = len(d)
    d_bar = np.mean(d)
    lag = max(int(T**(1/3)), 1)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag + 1):
        gk = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * (1 - k / (lag + 1)) * gk
    var_d = (gamma_0 + gamma_sum) / T
    if var_d <= 0:
        return {"dm_stat": 0.0, "p_value": 1.0, "better": "neither"}
    dm_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - sp_stats.norm.cdf(abs(dm_stat)))
    return {"dm_stat": float(dm_stat), "p_value": float(p_val),
            "mean_diff": float(d_bar)}


def compute_tick_losses(returns, var_forecasts, alpha):
    """Compute tick (check function) losses element-wise."""
    u = returns - var_forecasts
    return np.where(u >= 0, alpha * u, (alpha - 1.0) * u)


# ============================================================================
# In-Sample Diagnostics
# ============================================================================
def insample_diagnostics(returns, alpha, spec_name):
    """Fit CAViaR on full sample and report diagnostics."""
    est = estimate_caviar(returns, alpha, spec_name)
    q = est["q_series"]
    violations = (returns < q).astype(int)
    violation_rate = np.mean(violations)

    # Ljung-Box on hit sequence
    hits = violations.astype(float) - alpha
    T = len(hits)
    n_lags = min(10, T // 5)
    acf_vals = []
    for lag in range(1, n_lags + 1):
        c = np.corrcoef(hits[lag:], hits[:-lag])[0, 1]
        acf_vals.append(c)
    acf_vals = np.array(acf_vals)
    lb_stat = T * (T + 2) * np.sum(acf_vals**2 / (T - np.arange(1, n_lags + 1)))
    lb_pval = 1 - sp_stats.chi2.cdf(lb_stat, n_lags)

    return {
        "spec": spec_name, "params": est["params"], "loss": est["loss"],
        "success": est["success"], "violation_rate": float(violation_rate),
        "expected_rate": alpha, "lb_stat": float(lb_stat),
        "lb_pval": float(lb_pval),
        "lb_conclusion": "pass" if lb_pval >= 0.05 else "reject",
    }


# ============================================================================
# Main
# ============================================================================
def main():
    print("=" * 72, flush=True)
    print("CAViaR (Conditional Autoregressive Value at Risk)", flush=True)
    print("Engle & Manganelli (2004)", flush=True)
    print("=" * 72, flush=True)
    sys.stdout.flush()

    returns_series = download_data()

    # ====================================================================
    # Part 1: In-Sample Diagnostics
    # ====================================================================
    print("\n" + "=" * 72, flush=True)
    print("PART 1: IN-SAMPLE DIAGNOSTICS (full sample)", flush=True)
    print("=" * 72, flush=True)

    all_returns = returns_series.values
    specs = ["SAV", "AS", "IG", "AD"]

    for alpha in [0.05, 0.01]:
        print(f"\n--- alpha = {alpha} ({int(alpha*100)}% VaR) ---", flush=True)
        print(f"{'Spec':<6} {'Params':>45} {'Viol%':>7} {'Exp%':>6} "
              f"{'LB_p':>7} {'LB':>6} {'RQ':>10}", flush=True)
        print("-" * 95, flush=True)

        for spec in specs:
            diag = insample_diagnostics(all_returns, alpha, spec)
            param_str = ", ".join([f"{p:.5f}" for p in diag["params"]])
            print(f"{spec:<6} {param_str:>45} {diag['violation_rate']*100:>7.2f} "
                  f"{alpha*100:>6.2f} {diag['lb_pval']:>7.3f} {diag['lb_conclusion']:>6} "
                  f"{diag['loss']:>10.6f}", flush=True)

    # ====================================================================
    # Part 2: OOS Rolling Backtest (monthly re-estimation)
    # ====================================================================
    print("\n" + "=" * 72, flush=True)
    print("PART 2: OUT-OF-SAMPLE BACKTEST (2020-2025)", flush=True)
    print(f"Window={WINDOW}, Monthly re-estimation, Daily VaR update", flush=True)
    print("=" * 72, flush=True)

    all_oos = {}

    for alpha in [0.05, 0.01]:
        print(f"\n{'='*72}", flush=True)
        print(f"alpha = {alpha} ({int(alpha*100)}% VaR)", flush=True)
        print(f"{'='*72}", flush=True)

        oos = {}

        # CAViaR specifications
        for spec in specs:
            print(f"\n  [{spec}] Estimating...", flush=True)
            oos[f"CAViaR-{spec}"] = rolling_caviar_backtest(returns_series, alpha, spec)

        # GJR-GARCH Skewed-t benchmark
        print(f"\n  [GJR-SkewT] Estimating...", flush=True)
        oos["GJR-SkewT"] = rolling_garch_backtest(returns_series, alpha)

        # Historical Simulation (naive)
        print(f"\n  [HistSim] Computing...", flush=True)
        eval_mask = returns_series.index >= EVAL_START
        eval_dates = returns_series.index[eval_mask]
        hs_rows = []
        for date in eval_dates:
            pos = returns_series.index.get_loc(date)
            if pos < WINDOW:
                continue
            train = returns_series.iloc[pos - WINDOW:pos].values
            vf = np.quantile(train, alpha)
            actual = returns_series.iloc[pos]
            hs_rows.append({"date": date, "var_forecast": float(vf),
                            "actual_return": float(actual),
                            "violation": int(actual < vf)})
        oos["HistSim"] = pd.DataFrame(hs_rows).set_index("date")

        all_oos[alpha] = oos

        # ================================================================
        # Results
        # ================================================================
        print(f"\n{'='*72}", flush=True)
        print(f"RESULTS: alpha = {alpha}", flush=True)
        print(f"{'='*72}", flush=True)

        print(f"\n{'Model':<15} {'Viol%':>7} {'Exp%':>6} {'Kup_p':>8} {'Kup':>5} "
              f"{'Chr_p':>7} {'Chr':>6} {'DQ_p':>7} {'DQ':>6} {'RQ':>10}", flush=True)
        print("-" * 95, flush=True)

        for name, df in oos.items():
            v = df["violation"].values
            r = df["actual_return"].values
            vf = df["var_forecast"].values
            vr = np.mean(v)
            kup = kupiec_test(v, alpha)
            chris = christoffersen_test(v)
            dq = dq_test(r, vf, alpha)
            tl = compute_tick_losses(r, vf, alpha)
            rq = np.mean(tl)

            print(f"{name:<15} {vr*100:>7.2f} {alpha*100:>6.2f} "
                  f"{kup['p_value']:>8.4f} {kup['conclusion']:>5} "
                  f"{chris['independence_pval']:>7.4f} {chris['conclusion'][:6]:>6} "
                  f"{dq['p_value']:>7.4f} {dq['conclusion']:>6} "
                  f"{rq:>10.6f}", flush=True)

        # ================================================================
        # Pairwise DM tests vs GJR-SkewT
        # ================================================================
        print(f"\n--- DM Test (Tick Loss) vs GJR-SkewT ---", flush=True)
        garch_df = oos["GJR-SkewT"]

        for name, df in oos.items():
            if name == "GJR-SkewT":
                continue
            common = df.index.intersection(garch_df.index)
            df_c = df.loc[common]
            g_c = garch_df.loc[common]

            tl_model = compute_tick_losses(df_c["actual_return"].values,
                                           df_c["var_forecast"].values, alpha)
            tl_garch = compute_tick_losses(g_c["actual_return"].values,
                                           g_c["var_forecast"].values, alpha)
            dm = dm_test_rq(tl_model, tl_garch)

            sig = "***" if dm["p_value"] < 0.01 else "**" if dm["p_value"] < 0.05 \
                else "*" if dm["p_value"] < 0.10 else ""
            winner = name if dm["mean_diff"] < 0 else "GJR-SkewT"
            print(f"  {name:<15} vs GJR-SkewT: DM={dm['dm_stat']:+.3f}, "
                  f"p={dm['p_value']:.4f} {sig} -> {winner} "
                  f"(dRQ={dm['mean_diff']:+.6f})", flush=True)

    # ====================================================================
    # Part 3: Crisis Periods
    # ====================================================================
    print("\n" + "=" * 72, flush=True)
    print("PART 3: CRISIS PERIOD ANALYSIS", flush=True)
    print("=" * 72, flush=True)

    crises = {
        "COVID (2020-02 to 2020-04)": ("2020-02-01", "2020-04-30"),
        "2022 Bear (2022-01 to 2022-10)": ("2022-01-01", "2022-10-31"),
        "2024 Aug Selloff": ("2024-07-15", "2024-08-15"),
    }

    for ak in [0.05, 0.01]:
        print(f"\n--- alpha = {ak} ---", flush=True)
        oos = all_oos[ak]
        for cname, (s, e) in crises.items():
            print(f"\n  {cname}:", flush=True)
            for mname, df in oos.items():
                mask = (df.index >= s) & (df.index <= e)
                if mask.sum() == 0:
                    continue
                sub = df[mask]
                nd = len(sub)
                nv = sub["violation"].sum()
                vr = nv / nd if nd > 0 else 0
                avgvar = sub["var_forecast"].mean()
                print(f"    {mname:<15}: {nv}/{nd} viols ({vr*100:.1f}%), "
                      f"avg VaR={avgvar*100:.2f}%", flush=True)

    # ====================================================================
    # Part 4: Ranking
    # ====================================================================
    print("\n" + "=" * 72, flush=True)
    print("PART 4: OVERALL RANKING", flush=True)
    print("=" * 72, flush=True)

    for ak in [0.05, 0.01]:
        print(f"\n--- alpha = {ak} ---", flush=True)
        oos = all_oos[ak]

        ranking = []
        for mname, df in oos.items():
            v = df["violation"].values
            r = df["actual_return"].values
            vf = df["var_forecast"].values
            vr = np.mean(v)
            kup = kupiec_test(v, ak)
            chris = christoffersen_test(v)
            dq = dq_test(r, vf, ak)
            tl = compute_tick_losses(r, vf, ak)
            rq = np.mean(tl)

            np_ = sum([kup["conclusion"] == "pass",
                       chris["conclusion"] == "independent",
                       dq["conclusion"] == "pass"])
            ranking.append({
                "model": mname, "rq_loss": rq, "viol_rate": vr,
                "kup": kup["conclusion"] == "pass",
                "chr": chris["conclusion"] == "independent",
                "dq": dq["conclusion"] == "pass",
                "n_pass": np_,
            })

        ranking.sort(key=lambda x: (-x["n_pass"], x["rq_loss"]))

        print(f"\n{'Rank':<5} {'Model':<15} {'RQ':>10} {'Viol%':>7} "
              f"{'Kup':>5} {'Chr':>5} {'DQ':>5} {'Pass':>5}", flush=True)
        print("-" * 65, flush=True)
        for rank, r in enumerate(ranking, 1):
            ks = "Y" if r["kup"] else "N"
            cs = "Y" if r["chr"] else "N"
            ds = "Y" if r["dq"] else "N"
            print(f"{rank:<5} {r['model']:<15} {r['rq_loss']:>10.6f} "
                  f"{r['viol_rate']*100:>7.2f} {ks:>5} {cs:>5} {ds:>5} "
                  f"{r['n_pass']:>5}/3", flush=True)

    # ====================================================================
    # Save
    # ====================================================================
    output = {
        "experiment": "CAViaR (Engle & Manganelli 2004)",
        "date": datetime.now().isoformat(),
        "proposer": "User",
        "executor": "Claude",
        "config": {
            "window": WINDOW, "eval_start": EVAL_START,
            "alpha_levels": [0.05, 0.01],
            "specifications": specs,
            "n_restarts": N_RESTARTS,
            "G_adaptive": G_ADAPTIVE,
            "reestimation": "monthly",
        },
        "results": {},
    }

    for ak in [0.05, 0.01]:
        oos = all_oos[ak]
        ar = {}
        for mname, df in oos.items():
            v = df["violation"].values
            r = df["actual_return"].values
            vf = df["var_forecast"].values
            kup = kupiec_test(v, ak)
            chris = christoffersen_test(v)
            dq = dq_test(r, vf, ak)
            tl = compute_tick_losses(r, vf, ak)
            ar[mname] = {
                "violation_rate": float(np.mean(v)),
                "rq_loss": float(np.mean(tl)),
                "kupiec": kup, "christoffersen": chris, "dq_test": dq,
                "n_oos_days": len(df),
            }
        output["results"][f"alpha_{ak}"] = ar

    out_path = Path("experiments/caviar_results.json")
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nResults saved to {out_path}", flush=True)

    # ====================================================================
    # Conclusion
    # ====================================================================
    print("\n" + "=" * 72, flush=True)
    print("CONCLUSION", flush=True)
    print("=" * 72, flush=True)
    print("""
CAViaR directly models the VaR quantile without assuming a distribution.
Key advantages:
  - No sigma estimation or distribution choice needed
  - Directly optimizes the quantity of interest (quantile)
  - Asymmetric Slope captures leverage effect naturally
  - Adaptive specification is fully nonparametric

Key questions answered:
  1. Does CAViaR pass Kupiec (unconditional coverage)?
  2. Does it pass Christoffersen (independence)?
  3. Does it pass DQ (correct specification)?
  4. How does tick loss compare to GJR-GARCH Skewed-t?
  5. How does it perform in crisis periods?

Note: Monthly re-estimation with daily VaR recursion is both
computationally efficient and practically realistic.
""", flush=True)


if __name__ == "__main__":
    main()
