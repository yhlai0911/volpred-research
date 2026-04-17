"""
K352: Bayesian GARCH — Does Prior Information Improve Vol Forecasting?
======================================================================

Hypothesis:
  Standard GARCH uses MLE → point estimates that can overfit to in-sample regime.
  Bayesian GARCH incorporates prior information → stabilises parameters.
  If parameter shrinkage (toward historical cross-period mean) improves OOS QLIKE,
  it means MLE overfits.

Method (Empirical Bayes / James-Stein shrinkage — no MCMC):
  1. Fit GJR-GARCH on 10 overlapping 5-year sub-periods (2005-2024)
     → obtain distribution of (ω, α, β, γ) across regimes
  2. Grand mean & cross-period variance → shrinkage intensity B_i
  3. For each rolling OOS window:
     a) MLE fit → raw θ_MLE
     b) Bayesian-shrunk: θ_Bayes = B*θ_prior + (1-B)*θ_MLE   (James-Stein)
     c) Both produce 1-step-ahead σ² forecasts
  4. Compare OOS QLIKE: MLE vs Bayesian-shrunk
  5. DM test for statistical significance
  6. Cross-asset: SPY, GLD, TLT

Key insight:
  If Bayesian shrinkage helps → MLE overfits to in-sample regime
  If it hurts → MLE is already near-optimal, extra regularisation damages signal

Data: SPY daily from yfinance. 2005-2024. Real data only.

[提出: 用戶 (K352 跳躍式探索), 執行: Claude]
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# CONFIG
# ============================================================
DATA_START = "2005-01-01"
DATA_END = "2024-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
WINDOW = 2000
ASSETS = {"SPY": "SPY", "GLD": "GLD", "TLT": "TLT"}

# Sub-period configuration for empirical prior
# 10 overlapping 5-year windows covering 2005-2024
SUB_PERIOD_YEARS = 5
SUB_PERIOD_STEP = 2  # overlap by sliding 2 years

print("=" * 80)
print("K352: BAYESIAN GARCH — DOES PRIOR INFORMATION IMPROVE VOL FORECASTING?")
print("Empirical Bayes / James-Stein shrinkage vs standard MLE")
print("=" * 80)


# ============================================================
# HELPER: download data
# ============================================================
def get_data(ticker: str) -> pd.DataFrame:
    """Download and prepare daily return data from yfinance."""
    print(f"\n[DATA] Downloading {ticker} from yfinance ({DATA_START} to {DATA_END})...")
    df = yf.download(ticker, start=DATA_START, end=DATA_END, auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna().copy()
    df["return"] = df["Close"].pct_change()
    df = df.dropna()
    df["r_squared"] = df["return"] ** 2
    print(f"  → {len(df)} observations, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    return df


# ============================================================
# STEP 1: Estimate prior from sub-period GJR-GARCH fits
# ============================================================
def estimate_prior(returns: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    """
    Fit GJR-GARCH on overlapping sub-periods → compute empirical prior.
    Returns dict with:
      - param_means: grand mean of (omega, alpha, beta, gamma)
      - param_vars: cross-period variance of each parameter
      - n_periods: how many sub-periods contributed
      - all_params: list of dicts with per-period parameters
    """
    print("\n[PRIOR] Estimating empirical prior from sub-period fits...")

    start_year = dates[0].year
    end_year = dates[-1].year

    all_params = []
    period_info = []

    year = start_year
    while year + SUB_PERIOD_YEARS <= end_year + 1:
        p_start = pd.Timestamp(f"{year}-01-01")
        p_end = pd.Timestamp(f"{year + SUB_PERIOD_YEARS}-01-01")

        mask = (dates >= p_start) & (dates < p_end)
        sub_returns = returns[mask]

        if len(sub_returns) < 500:
            year += SUB_PERIOD_STEP
            continue

        try:
            am = arch_model(sub_returns * 100, vol="GARCH", p=1, o=1, q=1, dist="t")
            res = am.fit(disp="off", show_warning=False)

            params = {
                "omega": res.params.get("omega", np.nan),
                "alpha": res.params.get("alpha[1]", np.nan),
                "gamma": res.params.get("gamma[1]", np.nan),
                "beta": res.params.get("beta[1]", np.nan),
            }

            if any(np.isnan(v) for v in params.values()):
                year += SUB_PERIOD_STEP
                continue

            all_params.append(params)
            period_info.append({
                "start": p_start.strftime("%Y-%m-%d"),
                "end": p_end.strftime("%Y-%m-%d"),
                "n_obs": int(np.sum(mask)),
                **params,
            })

        except Exception:
            pass

        year += SUB_PERIOD_STEP

    if len(all_params) < 3:
        raise ValueError(f"Only {len(all_params)} sub-periods converged; need ≥ 3")

    # Compute grand mean and cross-period variance
    param_names = ["omega", "alpha", "gamma", "beta"]
    param_means = {}
    param_vars = {}

    for pname in param_names:
        values = [p[pname] for p in all_params]
        param_means[pname] = float(np.mean(values))
        param_vars[pname] = float(np.var(values, ddof=1))

    print(f"  → {len(all_params)} sub-periods converged")
    print(f"  Prior means: ω={param_means['omega']:.4f}, α={param_means['alpha']:.4f}, "
          f"γ={param_means['gamma']:.4f}, β={param_means['beta']:.4f}")
    print(f"  Prior stds:  ω={np.sqrt(param_vars['omega']):.4f}, α={np.sqrt(param_vars['alpha']):.4f}, "
          f"γ={np.sqrt(param_vars['gamma']):.4f}, β={np.sqrt(param_vars['beta']):.4f}")

    return {
        "param_means": param_means,
        "param_vars": param_vars,
        "n_periods": len(all_params),
        "all_params": all_params,
        "period_info": period_info,
    }


# ============================================================
# STEP 2: James-Stein shrinkage
# ============================================================
def james_stein_shrink(theta_mle: dict, prior: dict, mle_var: dict) -> tuple[dict, dict]:
    """
    Apply James-Stein shrinkage:
      θ_Bayes = B * θ_prior + (1 - B) * θ_MLE
    where B = σ²_prior / (σ²_prior + σ²_MLE)

    Returns:
      (theta_bayes, shrinkage_factors)
    """
    param_names = ["omega", "alpha", "gamma", "beta"]
    theta_bayes = {}
    shrinkage_B = {}

    for pname in param_names:
        sigma2_prior = prior["param_vars"][pname]
        sigma2_mle = mle_var.get(pname, sigma2_prior)  # fallback to prior var

        # Guard against zero variance
        if sigma2_prior + sigma2_mle < 1e-20:
            B = 0.5
        else:
            B = sigma2_prior / (sigma2_prior + sigma2_mle)

        # B is the weight on the PRIOR (shrinkage toward prior)
        # When B is large → MLE var dominates → shrink more toward prior
        # When B is small → prior var dominates → trust MLE more
        theta_bayes[pname] = B * prior["param_means"][pname] + (1 - B) * theta_mle[pname]
        shrinkage_B[pname] = B

    # Enforce stationarity: alpha + gamma/2 + beta < 1
    persistence = theta_bayes["alpha"] + theta_bayes["gamma"] / 2 + theta_bayes["beta"]
    if persistence >= 0.999:
        scale = 0.998 / persistence
        theta_bayes["alpha"] *= scale
        theta_bayes["gamma"] *= scale
        theta_bayes["beta"] *= scale

    # Enforce positivity
    for pname in ["omega", "alpha", "beta"]:
        theta_bayes[pname] = max(theta_bayes[pname], 1e-8)
    theta_bayes["gamma"] = max(theta_bayes["gamma"], 0.0)

    return theta_bayes, shrinkage_B


# ============================================================
# STEP 3: Generate variance forecast from parameters
# ============================================================
def garch_forecast_manual(returns_pct: np.ndarray, params: dict) -> float:
    """
    Given GJR-GARCH params and a return series (in %),
    compute 1-step-ahead variance forecast using the recursion:
      σ²_t = ω + α·ε²_{t-1} + γ·ε²_{t-1}·I_{t-1} + β·σ²_{t-1}

    Run the recursion through the entire returns_pct series,
    then return the final 1-step-ahead forecast.
    """
    omega = params["omega"]
    alpha = params["alpha"]
    gamma = params["gamma"]
    beta = params["beta"]

    n = len(returns_pct)
    sigma2 = np.zeros(n + 1)

    # Initialise with unconditional variance
    persistence = alpha + gamma / 2 + beta
    if persistence < 1.0:
        sigma2[0] = omega / (1.0 - persistence)
    else:
        sigma2[0] = np.var(returns_pct)

    for t in range(n):
        eps2 = returns_pct[t] ** 2
        leverage = eps2 * (1.0 if returns_pct[t] < 0 else 0.0)
        sigma2[t + 1] = omega + alpha * eps2 + gamma * leverage + beta * sigma2[t]
        # Floor
        sigma2[t + 1] = max(sigma2[t + 1], 1e-8)

    return sigma2[-1]  # 1-step-ahead forecast (in %² units)


# ============================================================
# STEP 4: Rolling OOS comparison
# ============================================================
def rolling_oos_comparison(df: pd.DataFrame, prior: dict, asset: str) -> dict:
    """
    Rolling window OOS:
    For each day in OOS period:
      1. Fit MLE GARCH on trailing WINDOW days
      2. Apply James-Stein shrinkage → Bayesian params
      3. Generate forecasts from both
      4. Collect QLIKE scores
    """
    returns = df["return"].values
    r_squared = df["r_squared"].values
    dates = df.index

    oos_mask = dates >= OOS_START
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) == 0:
        raise ValueError("No OOS data found")

    print(f"\n[OOS] {asset}: Rolling forecast from {dates[oos_indices[0]].strftime('%Y-%m-%d')} "
          f"to {dates[oos_indices[-1]].strftime('%Y-%m-%d')} ({len(oos_indices)} days)")

    mle_qlike = []
    bayes_qlike = []
    mle_forecasts = []
    bayes_forecasts = []
    realized = []
    shrinkage_history = []
    param_distance_history = []

    refit_interval = 21  # refit monthly, forecast daily between refits
    last_mle_params = None
    last_bayes_params = None
    last_mle_var = None

    for i, idx in enumerate(oos_indices):
        if idx < WINDOW:
            continue

        train_start = idx - WINDOW
        train_returns = returns[train_start:idx]
        train_pct = train_returns * 100

        # Refit every refit_interval days
        if i % refit_interval == 0 or last_mle_params is None:
            try:
                am = arch_model(train_pct, vol="GARCH", p=1, o=1, q=1, dist="t")
                res = am.fit(disp="off", show_warning=False)

                last_mle_params = {
                    "omega": res.params.get("omega", np.nan),
                    "alpha": res.params.get("alpha[1]", np.nan),
                    "gamma": res.params.get("gamma[1]", np.nan),
                    "beta": res.params.get("beta[1]", np.nan),
                }

                if any(np.isnan(v) for v in last_mle_params.values()):
                    continue

                # Estimate MLE variance from Hessian (or fallback)
                try:
                    # Use standard errors as proxy for MLE variance
                    se = res.std_err
                    last_mle_var = {
                        "omega": se.get("omega", prior["param_vars"]["omega"]) ** 2,
                        "alpha": se.get("alpha[1]", prior["param_vars"]["alpha"]) ** 2,
                        "gamma": se.get("gamma[1]", prior["param_vars"]["gamma"]) ** 2,
                        "beta": se.get("beta[1]", prior["param_vars"]["beta"]) ** 2,
                    }
                except Exception:
                    last_mle_var = prior["param_vars"]

                # Apply James-Stein shrinkage
                last_bayes_params, shrinkage_B = james_stein_shrink(
                    last_mle_params, prior, last_mle_var
                )

                shrinkage_history.append(shrinkage_B)

                # Track parameter distance
                dist = sum((last_mle_params[k] - last_bayes_params[k]) ** 2
                           for k in ["omega", "alpha", "gamma", "beta"])
                param_distance_history.append(np.sqrt(dist))

            except Exception:
                continue

        if last_mle_params is None or last_bayes_params is None:
            continue

        # Generate forecasts using manual recursion
        # MLE forecast
        mle_var = garch_forecast_manual(train_pct, last_mle_params)
        mle_var_dec = mle_var / 10000  # convert from %² to decimal²

        # Bayesian forecast
        bayes_var = garch_forecast_manual(train_pct, last_bayes_params)
        bayes_var_dec = bayes_var / 10000

        # Realised variance (proxy = r²)
        rv = r_squared[idx]

        if mle_var_dec <= 0 or bayes_var_dec <= 0 or rv <= 0:
            continue

        # QLIKE = log(σ²) + r²/σ²
        ql_mle = np.log(mle_var_dec) + rv / mle_var_dec
        ql_bayes = np.log(bayes_var_dec) + rv / bayes_var_dec

        mle_qlike.append(ql_mle)
        bayes_qlike.append(ql_bayes)
        mle_forecasts.append(mle_var_dec)
        bayes_forecasts.append(bayes_var_dec)
        realized.append(rv)

    mle_qlike = np.array(mle_qlike)
    bayes_qlike = np.array(bayes_qlike)

    # ---- Summary stats ----
    n_oos = len(mle_qlike)
    mean_mle = float(np.mean(mle_qlike))
    mean_bayes = float(np.mean(bayes_qlike))

    # DM test (Bayes vs MLE)
    d = mle_qlike - bayes_qlike  # positive = Bayes wins
    dm_mean = float(np.mean(d))
    dm_se = float(np.std(d, ddof=1) / np.sqrt(n_oos))
    dm_t = dm_mean / dm_se if dm_se > 0 else 0.0
    dm_p = float(1 - stats.t.cdf(abs(dm_t), df=n_oos - 1)) * 2  # two-sided

    # Also one-sided: does Bayes beat MLE?
    dm_p_onesided = float(1 - stats.t.cdf(dm_t, df=n_oos - 1))

    # Shrinkage summary
    avg_shrinkage = {}
    if shrinkage_history:
        for pname in ["omega", "alpha", "gamma", "beta"]:
            vals = [s[pname] for s in shrinkage_history]
            avg_shrinkage[pname] = float(np.mean(vals))

    # Mincer-Zarnowitz regression
    from numpy.polynomial.polynomial import polyfit
    mle_arr = np.array(mle_forecasts)
    bayes_arr = np.array(bayes_forecasts)
    rv_arr = np.array(realized)

    # MZ for MLE
    slope_mle, intercept_mle = np.polyfit(mle_arr, rv_arr, 1)
    ss_res_mle = np.sum((rv_arr - (intercept_mle + slope_mle * mle_arr)) ** 2)
    ss_tot = np.sum((rv_arr - np.mean(rv_arr)) ** 2)
    r2_mle = 1 - ss_res_mle / ss_tot if ss_tot > 0 else 0

    # MZ for Bayes
    slope_bayes, intercept_bayes = np.polyfit(bayes_arr, rv_arr, 1)
    ss_res_bayes = np.sum((rv_arr - (intercept_bayes + slope_bayes * bayes_arr)) ** 2)
    r2_bayes = 1 - ss_res_bayes / ss_tot if ss_tot > 0 else 0

    result = {
        "asset": asset,
        "n_oos": n_oos,
        "mle_qlike_mean": mean_mle,
        "bayes_qlike_mean": mean_bayes,
        "qlike_diff": mean_mle - mean_bayes,  # positive = Bayes wins
        "qlike_diff_pct": (mean_mle - mean_bayes) / abs(mean_mle) * 100,
        "dm_t": dm_t,
        "dm_p_twosided": dm_p,
        "dm_p_onesided": dm_p_onesided,
        "bayes_wins": dm_t > 0,
        "significant_5pct": dm_p < 0.05,
        "avg_shrinkage": avg_shrinkage,
        "avg_param_distance": float(np.mean(param_distance_history)) if param_distance_history else 0,
        "mz_r2_mle": float(r2_mle),
        "mz_r2_bayes": float(r2_bayes),
        "mz_slope_mle": float(slope_mle),
        "mz_slope_bayes": float(slope_bayes),
    }

    return result


# ============================================================
# STEP 5: Additional analysis — shrinkage by volatility regime
# ============================================================
def regime_analysis(df: pd.DataFrame, prior: dict, asset: str) -> dict:
    """
    Split OOS into high-vol and low-vol regimes.
    Does Bayesian shrinkage help more in one regime?
    """
    returns = df["return"].values
    r_squared = df["r_squared"].values
    dates = df.index

    oos_mask = dates >= OOS_START
    oos_indices = np.where(oos_mask)[0]

    # Compute rolling 63-day realised vol for regime classification
    rolling_vol = pd.Series(returns).rolling(63).std().values
    median_vol = np.nanmedian(rolling_vol[oos_indices])

    regime_results = {}

    for regime_name, regime_filter in [("low_vol", lambda v: v <= median_vol),
                                        ("high_vol", lambda v: v > median_vol)]:
        mle_ql = []
        bayes_ql = []

        last_mle_params = None
        last_bayes_params = None
        last_mle_var = None

        for i, idx in enumerate(oos_indices):
            if idx < WINDOW:
                continue

            vol_val = rolling_vol[idx]
            if np.isnan(vol_val) or not regime_filter(vol_val):
                continue

            train_start = idx - WINDOW
            train_pct = returns[train_start:idx] * 100

            if i % 21 == 0 or last_mle_params is None:
                try:
                    am = arch_model(train_pct, vol="GARCH", p=1, o=1, q=1, dist="t")
                    res = am.fit(disp="off", show_warning=False)

                    last_mle_params = {
                        "omega": res.params.get("omega", np.nan),
                        "alpha": res.params.get("alpha[1]", np.nan),
                        "gamma": res.params.get("gamma[1]", np.nan),
                        "beta": res.params.get("beta[1]", np.nan),
                    }

                    if any(np.isnan(v) for v in last_mle_params.values()):
                        continue

                    try:
                        se = res.std_err
                        last_mle_var = {
                            "omega": se.get("omega", prior["param_vars"]["omega"]) ** 2,
                            "alpha": se.get("alpha[1]", prior["param_vars"]["alpha"]) ** 2,
                            "gamma": se.get("gamma[1]", prior["param_vars"]["gamma"]) ** 2,
                            "beta": se.get("beta[1]", prior["param_vars"]["beta"]) ** 2,
                        }
                    except Exception:
                        last_mle_var = prior["param_vars"]

                    last_bayes_params, _ = james_stein_shrink(
                        last_mle_params, prior, last_mle_var
                    )
                except Exception:
                    continue

            if last_mle_params is None or last_bayes_params is None:
                continue

            mle_var = garch_forecast_manual(train_pct, last_mle_params) / 10000
            bayes_var = garch_forecast_manual(train_pct, last_bayes_params) / 10000
            rv = r_squared[idx]

            if mle_var <= 0 or bayes_var <= 0 or rv <= 0:
                continue

            mle_ql.append(np.log(mle_var) + rv / mle_var)
            bayes_ql.append(np.log(bayes_var) + rv / bayes_var)

        if len(mle_ql) >= 20:
            mle_ql = np.array(mle_ql)
            bayes_ql = np.array(bayes_ql)
            d = mle_ql - bayes_ql
            dm_t = float(np.mean(d) / (np.std(d, ddof=1) / np.sqrt(len(d)))) if np.std(d) > 0 else 0

            regime_results[regime_name] = {
                "n_days": len(mle_ql),
                "mle_qlike": float(np.mean(mle_ql)),
                "bayes_qlike": float(np.mean(bayes_ql)),
                "dm_t": dm_t,
                "bayes_wins": dm_t > 0,
            }

    return regime_results


# ============================================================
# STEP 6: Parameter stability analysis
# ============================================================
def parameter_stability_analysis(df: pd.DataFrame, asset: str) -> dict:
    """
    Measure how much MLE parameters fluctuate across rolling windows.
    High instability → shrinkage could help.
    """
    returns = df["return"].values
    dates = df.index

    oos_mask = dates >= OOS_START
    oos_indices = np.where(oos_mask)[0]

    param_series = {k: [] for k in ["omega", "alpha", "gamma", "beta"]}

    for i, idx in enumerate(oos_indices):
        if idx < WINDOW or i % 21 != 0:
            continue

        train_pct = returns[idx - WINDOW:idx] * 100
        try:
            am = arch_model(train_pct, vol="GARCH", p=1, o=1, q=1, dist="t")
            res = am.fit(disp="off", show_warning=False)

            for pname, arch_name in [("omega", "omega"), ("alpha", "alpha[1]"),
                                      ("gamma", "gamma[1]"), ("beta", "beta[1]")]:
                val = res.params.get(arch_name, np.nan)
                if not np.isnan(val):
                    param_series[pname].append(val)
        except Exception:
            pass

    stability = {}
    for pname in ["omega", "alpha", "gamma", "beta"]:
        vals = np.array(param_series[pname])
        if len(vals) >= 3:
            stability[pname] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals, ddof=1)),
                "cv": float(np.std(vals, ddof=1) / np.mean(vals)) if np.mean(vals) != 0 else np.nan,
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
                "range_pct": float((np.max(vals) - np.min(vals)) / np.mean(vals) * 100) if np.mean(vals) != 0 else np.nan,
            }

    return stability


# ============================================================
# MAIN
# ============================================================
def main():
    all_results = {}
    summary_rows = []

    for asset_name, ticker in ASSETS.items():
        print(f"\n{'='*60}")
        print(f"ASSET: {asset_name} ({ticker})")
        print(f"{'='*60}")

        # Download data
        df = get_data(ticker)

        # Step 1: Estimate empirical prior
        prior = estimate_prior(df["return"].values, df.index)

        # Step 2-4: Rolling OOS comparison
        oos_result = rolling_oos_comparison(df, prior, asset_name)

        # Step 5: Regime analysis
        regime_result = regime_analysis(df, prior, asset_name)

        # Step 6: Parameter stability
        stability = parameter_stability_analysis(df, asset_name)

        # Print results
        print(f"\n{'─'*50}")
        print(f"RESULTS: {asset_name}")
        print(f"{'─'*50}")
        print(f"  OOS days:        {oos_result['n_oos']}")
        print(f"  MLE QLIKE:       {oos_result['mle_qlike_mean']:.6f}")
        print(f"  Bayes QLIKE:     {oos_result['bayes_qlike_mean']:.6f}")
        print(f"  QLIKE diff:      {oos_result['qlike_diff']:.6f} ({oos_result['qlike_diff_pct']:+.3f}%)")
        print(f"  DM t-stat:       {oos_result['dm_t']:.3f}")
        print(f"  DM p (2-sided):  {oos_result['dm_p_twosided']:.4f}")
        print(f"  Winner:          {'Bayesian' if oos_result['bayes_wins'] else 'MLE'}")
        print(f"  Significant:     {'YES' if oos_result['significant_5pct'] else 'No'}")
        print(f"  MZ R² (MLE):     {oos_result['mz_r2_mle']:.4f}")
        print(f"  MZ R² (Bayes):   {oos_result['mz_r2_bayes']:.4f}")

        if oos_result["avg_shrinkage"]:
            print(f"  Avg shrinkage B:")
            for pname in ["omega", "alpha", "gamma", "beta"]:
                print(f"    {pname:>6}: {oos_result['avg_shrinkage'][pname]:.3f}")

        if regime_result:
            print(f"\n  Regime analysis:")
            for rname, rdata in regime_result.items():
                print(f"    {rname:>8}: n={rdata['n_days']}, DM t={rdata['dm_t']:.3f}, "
                      f"winner={'Bayes' if rdata['bayes_wins'] else 'MLE'}")

        if stability:
            print(f"\n  MLE parameter stability (CV = coefficient of variation):")
            for pname in ["omega", "alpha", "gamma", "beta"]:
                if pname in stability:
                    s = stability[pname]
                    cv_str = f"{s['cv']:.2f}" if not np.isnan(s.get('cv', np.nan)) else "N/A"
                    print(f"    {pname:>6}: mean={s['mean']:.4f}, std={s['std']:.4f}, CV={cv_str}")

        all_results[asset_name] = {
            "oos": oos_result,
            "regime": regime_result,
            "stability": stability,
            "prior": {
                "n_periods": prior["n_periods"],
                "param_means": prior["param_means"],
                "param_vars": prior["param_vars"],
                "period_info": prior["period_info"],
            },
        }

        summary_rows.append({
            "asset": asset_name,
            "n_oos": oos_result["n_oos"],
            "mle_qlike": oos_result["mle_qlike_mean"],
            "bayes_qlike": oos_result["bayes_qlike_mean"],
            "qlike_diff_pct": oos_result["qlike_diff_pct"],
            "dm_t": oos_result["dm_t"],
            "dm_p": oos_result["dm_p_twosided"],
            "winner": "Bayesian" if oos_result["bayes_wins"] else "MLE",
            "significant": oos_result["significant_5pct"],
        })

    # ============================================================
    # CROSS-ASSET SUMMARY
    # ============================================================
    print("\n" + "=" * 80)
    print("CROSS-ASSET SUMMARY: Bayesian (James-Stein) vs MLE GJR-GARCH")
    print("=" * 80)

    header = f"{'Asset':<8} {'N_OOS':>6} {'MLE QLIKE':>12} {'Bayes QLIKE':>12} {'Diff%':>8} {'DM-t':>7} {'p':>7} {'Winner':>8} {'Sig?':>5}"
    print(header)
    print("─" * len(header))

    for row in summary_rows:
        print(f"{row['asset']:<8} {row['n_oos']:>6} {row['mle_qlike']:>12.6f} {row['bayes_qlike']:>12.6f} "
              f"{row['qlike_diff_pct']:>+7.3f}% {row['dm_t']:>7.3f} {row['dm_p']:>7.4f} "
              f"{row['winner']:>8} {'YES' if row['significant'] else 'No':>5}")

    # Overall conclusion
    n_bayes_wins = sum(1 for r in summary_rows if r["winner"] == "Bayesian")
    n_sig = sum(1 for r in summary_rows if r["significant"])
    n_assets = len(summary_rows)

    print(f"\nBayesian wins: {n_bayes_wins}/{n_assets} assets")
    print(f"Significant:   {n_sig}/{n_assets} assets")

    # Interpretation
    print("\n" + "=" * 80)
    print("INTERPRETATION")
    print("=" * 80)

    if n_bayes_wins == 0:
        print("MLE dominates across all assets → standard MLE is NOT overfitting.")
        print("GARCH parameters are sufficiently stable that shrinkage toward")
        print("historical means only adds bias without reducing variance.")
    elif n_bayes_wins == n_assets:
        print("Bayesian shrinkage wins across all assets → MLE IS overfitting!")
        print("Parameter instability across regimes is large enough that")
        print("James-Stein regularisation provides meaningful improvement.")
    else:
        print(f"Mixed results: Bayesian helps for {n_bayes_wins}/{n_assets} assets.")
        print("The benefit of shrinkage is asset-dependent, likely related to")
        print("parameter stability (higher CV → more benefit from shrinkage).")

    if n_sig == 0:
        print("\nNo statistically significant differences → Bayesian and MLE")
        print("produce economically equivalent forecasts. The QLIKE ceiling")
        print("is binding regardless of estimation method.")

    # Key finding for knowledge base
    avg_diff = np.mean([r["qlike_diff_pct"] for r in summary_rows])
    print(f"\nAverage QLIKE difference: {avg_diff:+.4f}%")
    print(f"This is {'economically negligible' if abs(avg_diff) < 0.5 else 'potentially meaningful'}.")

    # Save results
    results_path = PROJECT_ROOT / "experiments" / "k352_bayesian_garch_results.json"

    # Convert numpy types for JSON serialization
    def convert(obj):
        if isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        return obj

    save_data = {
        "experiment": "K352",
        "title": "Bayesian GARCH — Does Prior Information Improve Vol Forecasting?",
        "method": "Empirical Bayes / James-Stein shrinkage on GJR-GARCH parameters",
        "data_source": "yfinance (SPY, GLD, TLT)",
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "window": WINDOW,
        "n_sub_periods_for_prior": all_results[list(all_results.keys())[0]]["prior"]["n_periods"],
        "summary": summary_rows,
        "detailed_results": json.loads(json.dumps(all_results, default=convert)),
        "conclusion": {
            "bayes_wins_count": n_bayes_wins,
            "total_assets": n_assets,
            "any_significant": n_sig > 0,
            "avg_qlike_diff_pct": float(avg_diff),
            "interpretation": (
                "MLE is near-optimal; Bayesian shrinkage does not break QLIKE ceiling"
                if n_sig == 0
                else f"Bayesian helps in {n_bayes_wins}/{n_assets} cases"
            ),
        },
    }

    with open(results_path, "w") as f:
        json.dump(save_data, f, indent=2, default=convert)

    print(f"\nResults saved to: {results_path}")

    return save_data


if __name__ == "__main__":
    results = main()
