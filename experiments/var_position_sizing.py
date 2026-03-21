"""VaR-Based Position Sizing vs 12/VIX Strategy Comparison

Hypothesis: Using Skewed-t VaR to size positions should be more precise than
the heuristic 12/VIX formula, because VaR incorporates both GARCH volatility
AND distributional shape (skewness, kurtosis).

Strategies:
1. 12/VIX baseline: weight = min(12/VIX, 1.0), cash in SHY
2. VaR-based (Student-t): weight = min(target_loss / VaR_1pct, 1.0)
3. VaR-based (Skewed-t): same but GJR-GARCH dist='skewt'
4. VaR-based (CF-VaR): Cornish-Fisher expansion VaR

Author: VolPred Research System
Date: 2026-03-16
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
WINDOW = 2000          # Rolling window for GARCH
TARGET_LOSS = 0.02     # 2% max daily loss
VAR_ALPHA = 0.01       # 1% VaR
START_DATE = "2006-01-01"  # Need data before 2014 for w=2000 warmup
END_DATE = "2025-12-31"
EVAL_START = "2014-01-02"  # Evaluation period start
TC_BPS = [1, 5, 10]   # Transaction cost in basis points


def download_data():
    """Download SPY, VIX, SHY data."""
    print("Downloading SPY, ^VIX, SHY data...")
    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    shy = yf.download("SHY", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)

    # Handle MultiIndex columns from newer yfinance
    for df in [spy, vix, shy]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    vix_close = vix["Close"]
    vix_close.name = "vix"
    shy_ret = shy["Close"].pct_change().dropna()
    shy_ret.name = "shy_ret"

    data = pd.concat([spy_ret, vix_close, shy_ret], axis=1).dropna()
    print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}, {len(data)} days")
    return data


def fit_gjr_garch(returns_pct, dist="normal"):
    """Fit GJR-GARCH(1,1) and return result object."""
    dist_map = {"normal": "normal", "studentt": "t", "skewt": "skewt"}
    model = arch_model(
        returns_pct, vol="GARCH", p=1, o=1, q=1,
        dist=dist_map.get(dist, dist), mean="Zero", rescale=False
    )
    result = model.fit(disp="off", show_warning=False)
    return result


def compute_student_t_var(sigma, nu, alpha=0.01):
    """Compute 1-day VaR using Student-t distribution.

    VaR = sigma * t_inv(alpha, nu) * sqrt((nu-2)/nu)
    The sqrt((nu-2)/nu) factor adjusts for the variance of t-distribution.
    """
    t_quantile = sp_stats.t.ppf(alpha, df=nu)
    # For standardized t with unit variance: multiply by sqrt((nu-2)/nu)
    # But arch package already standardizes, so we use the raw quantile
    var = -sigma * t_quantile  # positive number = loss
    return var


def compute_skewt_var(sigma, nu, lam, alpha=0.01):
    """Compute 1-day VaR using Hansen's Skewed-t distribution.

    Uses the arch package's SkewStudent distribution for consistency.
    """
    from arch.univariate.distribution import SkewStudent
    skewt = SkewStudent()
    # ppf expects (q, parameters) where parameters = [nu, lambda]
    q = skewt.ppf(alpha, parameters=np.array([nu, lam]))
    var = -sigma * q  # positive number = loss
    return var


def compute_cf_var(sigma, skew, kurt_excess, alpha=0.01):
    """Compute Cornish-Fisher VaR.

    CF expansion adjusts the normal quantile for skewness and kurtosis:
    z_cf = z + (z^2 - 1)*S/6 + (z^3 - 3*z)*K/24 - (2*z^3 - 5*z)*S^2/36

    where S = skewness, K = excess kurtosis, z = normal quantile
    """
    z = sp_stats.norm.ppf(alpha)
    z_cf = (z
            + (z**2 - 1) * skew / 6
            + (z**3 - 3*z) * kurt_excess / 24
            - (2*z**3 - 5*z) * skew**2 / 36)
    var = -sigma * z_cf  # positive number = loss
    return var


def rolling_garch_var(data, dist="normal", window=WINDOW, alpha=VAR_ALPHA):
    """Rolling GJR-GARCH VaR computation.

    Returns DataFrame with columns: sigma, var_1pct, weight
    """
    eval_mask = data.index >= EVAL_START
    eval_dates = data.index[eval_mask]

    results = []
    total = len(eval_dates)
    fail_count = 0

    for i, date in enumerate(eval_dates):
        if (i+1) % 250 == 0:
            print(f"    {dist}: {i+1}/{total} ({(i+1)/total*100:.0f}%)")

        # Get position of this date
        pos = data.index.get_loc(date)
        if pos < window:
            continue

        # Training data: returns in percentage for arch
        train_ret = data["spy_ret"].iloc[pos-window:pos].values * 100

        try:
            res = fit_gjr_garch(train_ret, dist=dist)

            # Forecast 1-step variance
            fcast = res.forecast(horizon=1)
            sigma_pct = float(np.sqrt(fcast.variance.iloc[-1, 0]))
            sigma = sigma_pct / 100  # Convert back to decimal

            params = dict(res.params)

            if dist == "normal":
                z = sp_stats.norm.ppf(alpha)
                var_1pct = -sigma * z
            elif dist == "studentt":
                # arch 't' distribution: nu parameter
                nu = params.get("nu", 5.0)
                var_1pct = compute_student_t_var(sigma, nu, alpha)
            elif dist == "skewt":
                nu = params.get("nu", 5.0)
                lam = params.get("lambda", 0.0)
                var_1pct = compute_skewt_var(sigma, nu, lam, alpha)
            else:
                var_1pct = -sigma * sp_stats.norm.ppf(alpha)

            # Position weight
            weight = min(TARGET_LOSS / var_1pct, 1.0) if var_1pct > 0 else 1.0
            weight = max(weight, 0.0)

            results.append({
                "date": date,
                "sigma": sigma,
                "var_1pct": var_1pct,
                "weight": weight,
                "params": params,
            })

        except Exception as e:
            fail_count += 1
            # Use previous result or default
            if results:
                prev = results[-1].copy()
                prev["date"] = date
                results.append(prev)
            else:
                results.append({
                    "date": date,
                    "sigma": 0.01,
                    "var_1pct": 0.023,
                    "weight": 0.87,
                    "params": {},
                })

    if fail_count > 0:
        print(f"    {dist}: {fail_count} fitting failures ({fail_count/total*100:.1f}%)")

    df = pd.DataFrame(results).set_index("date")
    return df


def rolling_cf_var(data, window=WINDOW, alpha=VAR_ALPHA):
    """Rolling Cornish-Fisher VaR using GJR-GARCH(1,1) normal + rolling moments."""
    eval_mask = data.index >= EVAL_START
    eval_dates = data.index[eval_mask]

    results = []
    total = len(eval_dates)
    fail_count = 0

    for i, date in enumerate(eval_dates):
        if (i+1) % 250 == 0:
            print(f"    CF-VaR: {i+1}/{total} ({(i+1)/total*100:.0f}%)")

        pos = data.index.get_loc(date)
        if pos < window:
            continue

        train_ret = data["spy_ret"].iloc[pos-window:pos].values
        train_ret_pct = train_ret * 100

        try:
            res = fit_gjr_garch(train_ret_pct, dist="normal")
            fcast = res.forecast(horizon=1)
            sigma_pct = float(np.sqrt(fcast.variance.iloc[-1, 0]))
            sigma = sigma_pct / 100

            # Compute standardized residuals for moment estimation
            cond_vol = np.array(res.conditional_volatility) / 100
            std_resid = train_ret / np.maximum(cond_vol, 1e-8)

            # Rolling skewness and excess kurtosis from standardized residuals
            skew = float(sp_stats.skew(std_resid))
            kurt_excess = float(sp_stats.kurtosis(std_resid))  # excess kurtosis

            var_1pct = compute_cf_var(sigma, skew, kurt_excess, alpha)

            weight = min(TARGET_LOSS / var_1pct, 1.0) if var_1pct > 0 else 1.0
            weight = max(weight, 0.0)

            results.append({
                "date": date,
                "sigma": sigma,
                "var_1pct": var_1pct,
                "weight": weight,
                "skew": skew,
                "kurt_excess": kurt_excess,
            })

        except Exception as e:
            fail_count += 1
            if results:
                prev = results[-1].copy()
                prev["date"] = date
                results.append(prev)
            else:
                results.append({
                    "date": date, "sigma": 0.01, "var_1pct": 0.023,
                    "weight": 0.87, "skew": -0.5, "kurt_excess": 3.0,
                })

    if fail_count > 0:
        print(f"    CF-VaR: {fail_count} fitting failures ({fail_count/total*100:.1f}%)")

    df = pd.DataFrame(results).set_index("date")
    return df


def compute_12vix_weights(data):
    """Compute 12/VIX strategy weights."""
    eval_mask = data.index >= EVAL_START
    eval_data = data[eval_mask].copy()

    weights = np.minimum(12.0 / eval_data["vix"].values, 1.0)
    weights = np.maximum(weights, 0.0)

    df = pd.DataFrame({
        "weight": weights,
        "vix": eval_data["vix"].values,
    }, index=eval_data.index)

    return df


def backtest_strategy(data, weights_df, strategy_name, tc_bps=0):
    """Backtest a strategy given weights.

    Args:
        data: Full data with spy_ret, shy_ret
        weights_df: DataFrame with 'weight' column (indexed by date)
        strategy_name: Name for reporting
        tc_bps: Transaction cost in basis points (one-way)

    Returns:
        dict with performance metrics
    """
    eval_data = data[data.index >= EVAL_START].copy()

    # Align weights with eval data
    common_dates = eval_data.index.intersection(weights_df.index)
    eval_data = eval_data.loc[common_dates]
    weights = weights_df.loc[common_dates, "weight"].values

    spy_ret = eval_data["spy_ret"].values
    shy_ret = eval_data["shy_ret"].values

    # Portfolio returns: w * SPY + (1-w) * SHY
    port_ret = weights * spy_ret + (1 - weights) * shy_ret

    # Transaction costs
    if tc_bps > 0:
        tc_rate = tc_bps / 10000
        weight_changes = np.abs(np.diff(weights, prepend=weights[0]))
        tc = weight_changes * tc_rate
        port_ret = port_ret - tc

    # Cumulative returns
    cum_ret = np.cumprod(1 + port_ret)

    # Sharpe ratio (annualized)
    ann_ret = np.mean(port_ret) * 252
    ann_vol = np.std(port_ret) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Maximum drawdown
    peak = np.maximum.accumulate(cum_ret)
    drawdown = (cum_ret - peak) / peak
    max_dd = float(np.min(drawdown))

    # Average weight
    avg_weight = float(np.mean(weights))

    # Turnover: fraction of days with weight change > 5%
    weight_changes = np.abs(np.diff(weights))
    turnover_pct = float(np.mean(weight_changes > 0.05) * 100)
    avg_daily_turnover = float(np.mean(weight_changes))

    # Year-by-year returns
    port_series = pd.Series(port_ret, index=common_dates)
    yearly = port_series.groupby(port_series.index.year).apply(
        lambda x: float(np.prod(1 + x) - 1)
    )

    # Buy-and-hold SPY for reference
    spy_cum = np.cumprod(1 + spy_ret)
    spy_peak = np.maximum.accumulate(spy_cum)
    spy_dd = (spy_cum - spy_peak) / spy_peak
    spy_max_dd = float(np.min(spy_dd))
    spy_sharpe = (np.mean(spy_ret) * 252) / (np.std(spy_ret) * np.sqrt(252))

    return {
        "strategy": strategy_name,
        "annual_return": round(ann_ret * 100, 2),
        "annual_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd * 100, 2),
        "avg_weight": round(avg_weight, 3),
        "turnover_pct_days_gt5pct": round(turnover_pct, 1),
        "avg_daily_turnover": round(avg_daily_turnover, 4),
        "total_return": round(float(cum_ret[-1] - 1) * 100, 2),
        "yearly_returns": {str(k): round(v * 100, 2) for k, v in yearly.items()},
        "n_days": len(port_ret),
        "spy_sharpe": round(spy_sharpe, 3),
        "spy_max_dd": round(spy_max_dd * 100, 2),
    }


def main():
    print("=" * 70)
    print("VaR-Based Position Sizing vs 12/VIX Strategy")
    print("=" * 70)

    # Download data
    data = download_data()

    # ====================================================================
    # Strategy 1: 12/VIX Baseline
    # ====================================================================
    print("\n[1/4] Computing 12/VIX baseline weights...")
    vix_weights = compute_12vix_weights(data)
    print(f"  Done. Avg weight: {vix_weights['weight'].mean():.3f}")

    # ====================================================================
    # Strategy 2: VaR-based (Student-t)
    # ====================================================================
    print("\n[2/4] Rolling GJR-GARCH(1,1) Student-t VaR...")
    studentt_results = rolling_garch_var(data, dist="studentt")
    print(f"  Done. Avg weight: {studentt_results['weight'].mean():.3f}, "
          f"Avg VaR: {studentt_results['var_1pct'].mean():.4f}")

    # ====================================================================
    # Strategy 3: VaR-based (Skewed-t)
    # ====================================================================
    print("\n[3/4] Rolling GJR-GARCH(1,1) Skewed-t VaR...")
    skewt_results = rolling_garch_var(data, dist="skewt")
    print(f"  Done. Avg weight: {skewt_results['weight'].mean():.3f}, "
          f"Avg VaR: {skewt_results['var_1pct'].mean():.4f}")

    # ====================================================================
    # Strategy 4: VaR-based (Cornish-Fisher)
    # ====================================================================
    print("\n[4/4] Rolling GJR-GARCH(1,1) + Cornish-Fisher VaR...")
    cf_results = rolling_cf_var(data)
    print(f"  Done. Avg weight: {cf_results['weight'].mean():.3f}, "
          f"Avg VaR: {cf_results['var_1pct'].mean():.4f}")

    # ====================================================================
    # Backtest all strategies
    # ====================================================================
    print("\n" + "=" * 70)
    print("BACKTESTING (no transaction costs)")
    print("=" * 70)

    strategies = {
        "12/VIX": vix_weights,
        "VaR Student-t": studentt_results,
        "VaR Skewed-t": skewt_results,
        "VaR CF": cf_results,
    }

    all_results = {}
    for name, weights_df in strategies.items():
        result = backtest_strategy(data, weights_df, name, tc_bps=0)
        all_results[name] = result

    # ====================================================================
    # Print results
    # ====================================================================
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    header = f"{'Strategy':<20} {'Sharpe':>8} {'Ann Ret%':>9} {'Ann Vol%':>9} {'MaxDD%':>8} {'AvgWt':>7} {'Turn%':>7}"
    print(header)
    print("-" * 70)
    for name, r in all_results.items():
        print(f"{name:<20} {r['sharpe']:>8.3f} {r['annual_return']:>9.2f} {r['annual_vol']:>9.2f} "
              f"{r['max_drawdown']:>8.2f} {r['avg_weight']:>7.3f} {r['turnover_pct_days_gt5pct']:>7.1f}")

    print(f"\n{'SPY Buy&Hold':<20} {all_results['12/VIX']['spy_sharpe']:>8.3f} {'':>9} {'':>9} "
          f"{all_results['12/VIX']['spy_max_dd']:>8.2f}")

    # Year-by-year comparison
    print("\n" + "=" * 70)
    print("YEAR-BY-YEAR RETURNS (%)")
    print("=" * 70)

    years = sorted(set().union(*[r["yearly_returns"].keys() for r in all_results.values()]))
    header = f"{'Year':<6}"
    for name in strategies:
        header += f" {name:>15}"
    print(header)
    print("-" * (6 + 16 * len(strategies)))

    for year in years:
        row = f"{year:<6}"
        for name in strategies:
            yr = all_results[name]["yearly_returns"].get(year, 0)
            row += f" {yr:>15.2f}"
        print(row)

    # ====================================================================
    # Transaction cost sensitivity
    # ====================================================================
    print("\n" + "=" * 70)
    print("TRANSACTION COST SENSITIVITY")
    print("=" * 70)

    tc_results = {}
    for tc in TC_BPS:
        tc_results[tc] = {}
        for name, weights_df in strategies.items():
            r = backtest_strategy(data, weights_df, name, tc_bps=tc)
            tc_results[tc][name] = r

    for tc in TC_BPS:
        print(f"\n--- {tc} bps one-way ---")
        header = f"{'Strategy':<20} {'Sharpe':>8} {'Ann Ret%':>9} {'MaxDD%':>8}"
        print(header)
        print("-" * 46)
        for name in strategies:
            r = tc_results[tc][name]
            print(f"{name:<20} {r['sharpe']:>8.3f} {r['annual_return']:>9.2f} {r['max_drawdown']:>8.2f}")

    # ====================================================================
    # VaR distribution parameters analysis
    # ====================================================================
    print("\n" + "=" * 70)
    print("DISTRIBUTION PARAMETERS (average over evaluation period)")
    print("=" * 70)

    # Student-t: extract nu
    nu_vals = [p.get("nu", np.nan) for p in studentt_results["params"]]
    nu_vals = [v for v in nu_vals if not np.isnan(v)]
    if nu_vals:
        print(f"Student-t nu: mean={np.mean(nu_vals):.2f}, std={np.std(nu_vals):.2f}, "
              f"min={np.min(nu_vals):.2f}, max={np.max(nu_vals):.2f}")

    # Skewed-t: extract nu and lambda
    nu_vals_sk = [p.get("nu", np.nan) for p in skewt_results["params"]]
    lam_vals = [p.get("lambda", np.nan) for p in skewt_results["params"]]
    nu_vals_sk = [v for v in nu_vals_sk if not np.isnan(v)]
    lam_vals = [v for v in lam_vals if not np.isnan(v)]
    if nu_vals_sk:
        print(f"Skewed-t nu: mean={np.mean(nu_vals_sk):.2f}, std={np.std(nu_vals_sk):.2f}")
    if lam_vals:
        print(f"Skewed-t lambda: mean={np.mean(lam_vals):.4f}, std={np.std(lam_vals):.4f}")

    # CF-VaR: skewness and kurtosis
    if "skew" in cf_results.columns:
        print(f"CF-VaR skewness: mean={cf_results['skew'].mean():.3f}, std={cf_results['skew'].std():.3f}")
        print(f"CF-VaR excess kurtosis: mean={cf_results['kurt_excess'].mean():.2f}, "
              f"std={cf_results['kurt_excess'].std():.2f}")

    # ====================================================================
    # Weight correlation analysis
    # ====================================================================
    print("\n" + "=" * 70)
    print("WEIGHT CORRELATION ANALYSIS")
    print("=" * 70)

    # Align all weights on common dates
    common = vix_weights.index.intersection(studentt_results.index)\
        .intersection(skewt_results.index).intersection(cf_results.index)

    weight_matrix = pd.DataFrame({
        "12/VIX": vix_weights.loc[common, "weight"],
        "Student-t": studentt_results.loc[common, "weight"],
        "Skewed-t": skewt_results.loc[common, "weight"],
        "CF-VaR": cf_results.loc[common, "weight"],
    })

    corr = weight_matrix.corr()
    print("\nWeight correlations:")
    print(corr.round(3).to_string())

    # Weight summary statistics
    print("\nWeight statistics:")
    print(weight_matrix.describe().round(4).to_string())

    # ====================================================================
    # VaR vs actual losses analysis
    # ====================================================================
    print("\n" + "=" * 70)
    print("VaR ACCURACY (1% violation rate expected)")
    print("=" * 70)

    eval_data = data[data.index >= EVAL_START]

    for name, df in [("Student-t", studentt_results), ("Skewed-t", skewt_results), ("CF-VaR", cf_results)]:
        common = eval_data.index.intersection(df.index)
        actual_ret = eval_data.loc[common, "spy_ret"].values
        var_vals = df.loc[common, "var_1pct"].values

        violations = actual_ret < -var_vals
        violation_rate = np.mean(violations) * 100
        n_violations = np.sum(violations)

        # Conditional loss given violation
        if n_violations > 0:
            avg_loss_given_viol = np.mean(np.abs(actual_ret[violations]))
            avg_var_given_viol = np.mean(var_vals[violations])
            severity_ratio = avg_loss_given_viol / avg_var_given_viol
        else:
            avg_loss_given_viol = 0
            severity_ratio = 0

        print(f"\n{name}:")
        print(f"  Violation rate: {violation_rate:.2f}% (expected: 1.00%)")
        print(f"  N violations: {n_violations}/{len(actual_ret)}")
        print(f"  Avg loss given violation: {avg_loss_given_viol*100:.2f}%")
        print(f"  Severity ratio (loss/VaR): {severity_ratio:.2f}")

    # Also check 12/VIX implied VaR
    # 12/VIX uses sigma_implied = VIX/sqrt(252)/100
    common_vix = eval_data.index.intersection(vix_weights.index)
    vix_sigma = vix_weights.loc[common_vix, "vix"].values / 100 / np.sqrt(252)
    vix_var = -sp_stats.norm.ppf(0.01) * vix_sigma
    actual_ret_vix = eval_data.loc[common_vix, "spy_ret"].values
    vix_violations = actual_ret_vix < -vix_var
    print(f"\n12/VIX implied VaR (normal assumption):")
    print(f"  Violation rate: {np.mean(vix_violations)*100:.2f}% (expected: 1.00%)")
    print(f"  N violations: {np.sum(vix_violations)}/{len(actual_ret_vix)}")

    # ====================================================================
    # Regime analysis: how do strategies differ in high-vol vs low-vol?
    # ====================================================================
    print("\n" + "=" * 70)
    print("REGIME ANALYSIS")
    print("=" * 70)

    common_all = weight_matrix.index.intersection(eval_data.index)
    vix_vals = eval_data.loc[common_all, "vix"].values

    regimes = {
        "VIX < 15 (calm)": vix_vals < 15,
        "15 <= VIX < 25 (normal)": (vix_vals >= 15) & (vix_vals < 25),
        "25 <= VIX < 35 (elevated)": (vix_vals >= 25) & (vix_vals < 35),
        "VIX >= 35 (crisis)": vix_vals >= 35,
    }

    for regime_name, mask in regimes.items():
        n_days = np.sum(mask)
        if n_days < 10:
            continue

        print(f"\n{regime_name} ({n_days} days):")

        weights_in_regime = weight_matrix.loc[common_all].iloc[mask]
        spy_ret_regime = eval_data.loc[common_all, "spy_ret"].values[mask]

        # Average weights
        for col in weights_in_regime.columns:
            w = weights_in_regime[col].values
            r = w * spy_ret_regime + (1 - w) * 0  # simplified (SHY ≈ 0 within regime)
            sharpe_approx = np.mean(r) / np.std(r) * np.sqrt(252) if np.std(r) > 0 else 0
            print(f"  {col:>12}: avg_wt={np.mean(w):.3f}, regime_sharpe≈{sharpe_approx:.2f}")

    # ====================================================================
    # Statistical significance: DM test between strategies
    # ====================================================================
    print("\n" + "=" * 70)
    print("DIEBOLD-MARIANO TEST (utility loss comparison)")
    print("=" * 70)

    # Use daily utility as loss function: U = r - 0.5 * gamma * r^2, gamma=5
    gamma = 5.0
    common_all_list = list(common_all)

    strat_utils = {}
    for name, weights_df in strategies.items():
        c = eval_data.index.intersection(weights_df.index)
        w = weights_df.loc[c, "weight"].values
        r = eval_data.loc[c, "spy_ret"].values
        shy_r = eval_data.loc[c, "shy_ret"].values
        port_r = w * r + (1 - w) * shy_r
        utility = port_r - 0.5 * gamma * port_r**2
        strat_utils[name] = pd.Series(utility, index=c)

    # Pairwise DM tests
    strat_names = list(strategies.keys())
    for i in range(len(strat_names)):
        for j in range(i+1, len(strat_names)):
            n1, n2 = strat_names[i], strat_names[j]
            c = strat_utils[n1].index.intersection(strat_utils[n2].index)
            d = strat_utils[n1].loc[c].values - strat_utils[n2].loc[c].values

            # DM statistic
            T = len(d)
            d_bar = np.mean(d)
            # HAC variance (Newey-West with lag = int(T^(1/3)))
            lag = int(T**(1/3))
            gamma_0 = np.var(d, ddof=1)
            gamma_sum = 0
            for k in range(1, lag+1):
                gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
                gamma_sum += 2 * (1 - k/(lag+1)) * gamma_k
            var_d = (gamma_0 + gamma_sum) / T

            if var_d > 0:
                dm_stat = d_bar / np.sqrt(var_d)
                p_val = 2 * (1 - sp_stats.norm.cdf(abs(dm_stat)))
                sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
                winner = n1 if d_bar > 0 else n2
                print(f"  {n1} vs {n2}: DM={dm_stat:+.3f}, p={p_val:.4f} {sig} → {winner}")
            else:
                print(f"  {n1} vs {n2}: variance too small")

    # ====================================================================
    # Save results
    # ====================================================================
    output = {
        "experiment": "VaR Position Sizing vs 12/VIX",
        "date": datetime.now().isoformat(),
        "config": {
            "window": WINDOW,
            "target_loss": TARGET_LOSS,
            "var_alpha": VAR_ALPHA,
            "eval_start": EVAL_START,
        },
        "results_no_tc": {k: v for k, v in all_results.items()},
        "results_with_tc": {
            f"{tc}bps": {k: v for k, v in tc_results[tc].items()}
            for tc in TC_BPS
        },
        "weight_correlations": corr.to_dict(),
        "weight_stats": weight_matrix.describe().to_dict(),
    }

    output_path = Path("experiments/var_position_sizing_results.json")
    output_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nResults saved to {output_path}")

    # ====================================================================
    # CONCLUSION
    # ====================================================================
    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)

    best = max(all_results.items(), key=lambda x: x[1]["sharpe"])
    worst = min(all_results.items(), key=lambda x: x[1]["sharpe"])

    print(f"\nBest Sharpe: {best[0]} ({best[1]['sharpe']:.3f})")
    print(f"Worst Sharpe: {worst[0]} ({worst[1]['sharpe']:.3f})")
    print(f"Sharpe difference: {best[1]['sharpe'] - worst[1]['sharpe']:.3f}")

    # Is VaR better?
    var_sharpes = {k: v["sharpe"] for k, v in all_results.items() if "VaR" in k}
    vix_sharpe = all_results["12/VIX"]["sharpe"]
    best_var = max(var_sharpes.items(), key=lambda x: x[1])

    if best_var[1] > vix_sharpe:
        print(f"\n→ Best VaR strategy ({best_var[0]}) BEATS 12/VIX by {best_var[1]-vix_sharpe:.3f} Sharpe")
    else:
        print(f"\n→ 12/VIX BEATS all VaR strategies by {vix_sharpe-best_var[1]:.3f} Sharpe")

    print(f"\nMDD comparison:")
    for name, r in sorted(all_results.items(), key=lambda x: x[1]["max_drawdown"]):
        print(f"  {name:<20}: {r['max_drawdown']:.2f}%")

    return output


if __name__ == "__main__":
    main()
