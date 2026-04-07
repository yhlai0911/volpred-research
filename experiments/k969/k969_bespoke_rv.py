"""
K969: Bespoke RV — Optimal Daily Volatility Proxy Weighting

Based on Patton & Zhang (JoE 2026, "Bespoke Realized Volatility"):
- Original: ML-optimized weights on 5-min return² across time slots
- Our version: Optimized weights on daily vol proxies (OHLCV-based)

Data: SPY 2006-01-01 to 2026-04-07 (yfinance)
IS: 2006-2018, OOS: 2019-2026
Seed: 42

References:
- Patton & Zhang (2026), "Bespoke Realized Volatility", Journal of Econometrics
- Patton (2011), "Volatility forecast comparison using imperfect volatility proxies", JoE
- Garman & Klass (1980), "On the estimation of security price volatilities from historical data"
- Yang & Zhang (2000), "Drift independent volatility estimation"
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime
from sklearn.linear_model import LinearRegression
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTPUT_DIR = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a8a170fc/experiments/k969'


# =============================================================================
# 1. Data Download & Volatility Proxy Calculation
# =============================================================================

def download_data():
    """Download SPY OHLCV data."""
    print("Downloading SPY data from yfinance...")
    spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
    # Flatten multi-level columns if needed
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    print(f"Downloaded {len(spy)} observations: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
    return spy


def compute_vol_proxies(df):
    """
    Compute 5 daily volatility proxies from OHLCV data.

    Returns DataFrame with columns: r2, parkinson, gk, rs, yz
    All represent variance (not std dev).
    """
    O = df['Open'].values.astype(float)
    H = df['High'].values.astype(float)
    L = df['Low'].values.astype(float)
    C = df['Close'].values.astype(float)

    n = len(df)

    # 1. Close-to-close squared return
    r2 = np.full(n, np.nan)
    for i in range(1, n):
        ret = np.log(C[i] / C[i-1])
        r2[i] = ret ** 2

    # 2. Parkinson (1980) — range-based
    parkinson = np.full(n, np.nan)
    for i in range(n):
        if H[i] > 0 and L[i] > 0:
            parkinson[i] = (np.log(H[i] / L[i])) ** 2 / (4 * np.log(2))

    # 3. Garman-Klass (1980) — range + close-open
    gk = np.full(n, np.nan)
    for i in range(n):
        if H[i] > 0 and L[i] > 0 and C[i] > 0 and O[i] > 0:
            gk[i] = 0.5 * (np.log(H[i] / L[i])) ** 2 - (2 * np.log(2) - 1) * (np.log(C[i] / O[i])) ** 2

    # 4. Rogers-Satchell (1991) — drift-adjusted
    rs = np.full(n, np.nan)
    for i in range(n):
        if H[i] > 0 and L[i] > 0 and C[i] > 0 and O[i] > 0:
            rs[i] = (np.log(H[i] / C[i]) * np.log(H[i] / O[i]) +
                     np.log(L[i] / C[i]) * np.log(L[i] / O[i]))

    # 5. Yang-Zhang (2000) — overnight + intraday
    yz = np.full(n, np.nan)
    # Need overnight return
    k = 0.34 / (1.34 + 2 * 1 / (1 + 1))  # simplified k for n=1
    # Actually k = 0.34/(1.34 + (n+1)/(n-1)) where n is sample size
    # For daily, use k = 0.34/1.34 ≈ 0.254 (simplified)
    k_yz = 0.34 / (1.34 + 2.0)  # standard simplification

    for i in range(1, n):
        if O[i] > 0 and C[i-1] > 0 and H[i] > 0 and L[i] > 0 and C[i] > 0:
            overnight = np.log(O[i] / C[i-1]) ** 2
            open_close = np.log(C[i] / O[i]) ** 2
            rs_i = (np.log(H[i] / C[i]) * np.log(H[i] / O[i]) +
                    np.log(L[i] / C[i]) * np.log(L[i] / O[i]))
            yz[i] = overnight + k_yz * open_close + (1 - k_yz) * rs_i

    result = pd.DataFrame({
        'r2': r2,
        'parkinson': parkinson,
        'gk': gk,
        'rs': rs,
        'yz': yz
    }, index=df.index)

    return result


# =============================================================================
# 2. Model Definitions
# =============================================================================

def ar1_forecast(y_train, y_test_len):
    """AR(1) model: y_t = a + b * y_{t-1}. Expanding window."""
    forecasts = []
    y = list(y_train)
    for i in range(y_test_len):
        Y = np.array(y[1:])
        X = np.array(y[:-1]).reshape(-1, 1)
        reg = LinearRegression().fit(X, Y)
        pred = reg.predict(np.array([[y[-1]]]))[0]
        forecasts.append(max(pred, 1e-10))  # floor at small positive
        # Expanding: add actual OOS value (will be set by caller)
        y.append(None)  # placeholder
    return forecasts


def ar1_forecast_expanding(y_all, split_idx):
    """AR(1) with expanding window. Returns OOS forecasts."""
    n = len(y_all)
    forecasts = []
    for t in range(split_idx, n):
        y_hist = y_all[:t]
        Y = y_hist[1:]
        X = y_hist[:-1].reshape(-1, 1)
        reg = LinearRegression().fit(X, Y)
        pred = reg.predict(np.array([[y_hist[-1]]]))[0]
        forecasts.append(max(pred, 1e-10))
    return np.array(forecasts)


def equal_weight_forecast(proxies_all, split_idx):
    """Equal-weight average of all proxies, then AR(1) on that."""
    eq = proxies_all.mean(axis=1).values
    return ar1_forecast_expanding(eq, split_idx)


def bespoke_ols_forecast(proxies_all, target_all, split_idx):
    """
    Bespoke (OLS): Learn optimal weights on proxies to predict next-day target.
    σ²_{t+1} = α + Σ w_i × proxy_i,t + ε
    Expanding window.
    """
    n = len(target_all)
    proxy_names = proxies_all.columns.tolist()
    forecasts = []
    weights_history = []

    for t in range(split_idx, n):
        # Target: σ²_{t+1}, Features: proxies at t
        Y = target_all[1:t]  # target from day 2 to day t
        X = proxies_all.iloc[:t-1][proxy_names].values  # proxies from day 1 to day t-1

        reg = LinearRegression().fit(X, Y)

        # Predict using today's proxies
        x_today = proxies_all.iloc[t-1:t][proxy_names].values
        pred = reg.predict(x_today)[0]
        forecasts.append(max(pred, 1e-10))

        if t == split_idx:
            weights_history.append({
                'intercept': reg.intercept_,
                'weights': dict(zip(proxy_names, reg.coef_))
            })

    # Also get final weights
    Y_final = target_all[1:n]
    X_final = proxies_all.iloc[:n-1][proxy_names].values
    reg_final = LinearRegression().fit(X_final, Y_final)
    final_weights = {
        'intercept': float(reg_final.intercept_),
        'weights': {k: float(v) for k, v in zip(proxy_names, reg_final.coef_)},
        'r2_is': float(reg_final.score(X_final, Y_final))
    }

    return np.array(forecasts), final_weights


def _ridge_fit(X, Y, alpha=1.0):
    """Manual Ridge regression: (X'X + alpha*I)^{-1} X'Y, with intercept."""
    n, p = X.shape
    X_mean = X.mean(axis=0)
    Y_mean = Y.mean()
    Xc = X - X_mean
    Yc = Y - Y_mean
    A = Xc.T @ Xc + alpha * np.eye(p)
    coef = np.linalg.solve(A, Xc.T @ Yc)
    intercept = Y_mean - X_mean @ coef
    return coef, intercept


def bespoke_ridge_forecast(proxies_all, target_all, split_idx, alpha=1.0):
    """
    Bespoke (Ridge): Same as OLS but with L2 regularization.
    """
    n = len(target_all)
    proxy_names = proxies_all.columns.tolist()
    forecasts = []

    for t in range(split_idx, n):
        Y = target_all[1:t]
        X = proxies_all.iloc[:t-1][proxy_names].values

        coef, intercept = _ridge_fit(X, Y, alpha)
        x_today = proxies_all.iloc[t-1:t][proxy_names].values
        pred = float(x_today @ coef + intercept)
        forecasts.append(max(pred, 1e-10))

    # Final weights
    Y_final = target_all[1:n]
    X_final = proxies_all.iloc[:n-1][proxy_names].values
    coef_final, intercept_final = _ridge_fit(X_final, Y_final, alpha)
    y_pred = X_final @ coef_final + intercept_final
    ss_res = np.sum((Y_final - y_pred) ** 2)
    ss_tot = np.sum((Y_final - Y_final.mean()) ** 2)
    r2_is = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    final_weights = {
        'intercept': float(intercept_final),
        'weights': {k: float(v) for k, v in zip(proxy_names, coef_final)},
        'r2_is': float(r2_is)
    }

    return np.array(forecasts), final_weights


def har_bespoke_forecast(proxies_all, target_all, split_idx):
    """
    HAR-Bespoke: Use daily, weekly (5d avg), monthly (22d avg) of bespoke vol.
    First compute equal-weight bespoke, then apply HAR structure.
    """
    # Use equal-weight average as base vol
    eq = proxies_all.mean(axis=1).values

    n = len(target_all)
    forecasts = []

    for t in range(split_idx, n):
        if t < 22:
            forecasts.append(np.mean(eq[:t]))
            continue

        # Build HAR features: daily, weekly avg, monthly avg
        Y = target_all[22:t]
        X_list = []
        for s in range(22, t):
            daily = eq[s-1]
            weekly = np.mean(eq[s-5:s])
            monthly = np.mean(eq[s-22:s])
            X_list.append([daily, weekly, monthly])
        X = np.array(X_list)

        reg = LinearRegression().fit(X, Y)

        # Predict
        daily_t = eq[t-1]
        weekly_t = np.mean(eq[t-5:t])
        monthly_t = np.mean(eq[t-22:t])
        pred = reg.predict(np.array([[daily_t, weekly_t, monthly_t]]))[0]
        forecasts.append(max(pred, 1e-10))

    return np.array(forecasts)


# =============================================================================
# 3. Evaluation Metrics
# =============================================================================

def qlike(actual, forecast):
    """QLIKE loss (Patton 2011): mean(actual/forecast - log(actual/forecast) - 1)
    Filter out zero actual values to avoid inf/nan."""
    mask = (actual > 0) & (forecast > 0)
    a = actual[mask]
    f = forecast[mask]
    ratio = a / f
    return np.mean(ratio - np.log(ratio) - 1)


def mse(actual, forecast):
    """Mean Squared Error."""
    return np.mean((actual - forecast) ** 2)


def mincer_zarnowitz(actual, forecast):
    """
    Mincer-Zarnowitz regression: actual = a + b * forecast + e
    Returns: intercept, slope, R², p-value for H0: b=1
    """
    X = forecast.reshape(-1, 1)
    Y = actual
    reg = LinearRegression().fit(X, Y)
    a = float(reg.intercept_)
    b = float(reg.coef_[0])
    r2 = float(reg.score(X, Y))

    # t-test for b=1
    n = len(Y)
    y_pred = reg.predict(X)
    resid = Y - y_pred
    s2 = np.sum(resid**2) / (n - 2)
    x_var = np.sum((forecast - np.mean(forecast))**2)
    se_b = np.sqrt(s2 / x_var) if x_var > 0 else np.inf
    t_stat = (b - 1) / se_b if se_b > 0 else 0
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n - 2))

    return {'intercept': a, 'slope': b, 'r2': r2, 't_stat_b1': float(t_stat), 'p_value_b1': float(p_val)}


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Negative DM stat means model 1 is better.
    Returns: DM statistic, p-value
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.sum((d[k:] - d_mean) * (d[:-k] - d_mean)) / n
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0

    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return float(dm_stat), float(p_value)


# =============================================================================
# 4. Main Experiment
# =============================================================================

def main():
    print("=" * 70)
    print("K969: Bespoke RV — Optimal Daily Volatility Proxy Weighting")
    print("=" * 70)

    # Download data
    spy = download_data()

    # Compute vol proxies
    proxies = compute_vol_proxies(spy)

    # Drop NaN rows (first row for r2 and yz)
    valid_idx = proxies.dropna().index
    proxies = proxies.loc[valid_idx]
    print(f"\nValid observations after NaN removal: {len(proxies)}")

    # Descriptive statistics
    print("\n--- Descriptive Statistics (annualized vol = sqrt(252 * mean proxy)) ---")
    desc = proxies.describe()
    print(desc.to_string())

    ann_vol = np.sqrt(252 * proxies.mean()) * 100
    print("\nAnnualized volatility (%) from each proxy:")
    for col in proxies.columns:
        print(f"  {col:12s}: {ann_vol[col]:.2f}%")

    # Correlations
    corr = proxies.corr()
    print("\n--- Proxy Correlations ---")
    print(corr.round(3).to_string())

    # Split IS/OOS
    is_end = '2018-12-31'
    split_idx = proxies.index.get_indexer([pd.Timestamp(is_end)], method='ffill')[0] + 1

    n_is = split_idx
    n_oos = len(proxies) - split_idx
    print(f"\nIS: {n_is} obs ({proxies.index[0].strftime('%Y-%m-%d')} to {proxies.index[split_idx-1].strftime('%Y-%m-%d')})")
    print(f"OOS: {n_oos} obs ({proxies.index[split_idx].strftime('%Y-%m-%d')} to {proxies.index[-1].strftime('%Y-%m-%d')})")

    # Target = r² (close-to-close squared return)
    target = proxies['r2'].values

    # =================================================================
    # Model 1-5: Individual proxy AR(1) forecasts
    # =================================================================
    print("\n--- Running AR(1) on individual proxies ---")
    individual_forecasts = {}
    for col in proxies.columns:
        y = proxies[col].values
        fc = ar1_forecast_expanding(y, split_idx)
        individual_forecasts[col] = fc
        print(f"  {col}: {len(fc)} OOS forecasts")

    # =================================================================
    # Model 6: Equal-weight average
    # =================================================================
    print("\n--- Running Equal-Weight forecast ---")
    eq_fc = equal_weight_forecast(proxies, split_idx)
    print(f"  equal_weight: {len(eq_fc)} OOS forecasts")

    # =================================================================
    # Model 7: Bespoke OLS
    # =================================================================
    print("\n--- Running Bespoke OLS forecast ---")
    bespoke_ols_fc, ols_weights = bespoke_ols_forecast(proxies, target, split_idx)
    print(f"  bespoke_ols: {len(bespoke_ols_fc)} OOS forecasts")
    print(f"  Final weights: {ols_weights['weights']}")
    print(f"  IS R²: {ols_weights['r2_is']:.4f}")

    # =================================================================
    # Model 8: Bespoke Ridge
    # =================================================================
    print("\n--- Running Bespoke Ridge forecast ---")
    bespoke_ridge_fc, ridge_weights = bespoke_ridge_forecast(proxies, target, split_idx, alpha=1.0)
    print(f"  bespoke_ridge: {len(bespoke_ridge_fc)} OOS forecasts")
    print(f"  Final weights: {ridge_weights['weights']}")

    # =================================================================
    # Model 9: HAR-Bespoke
    # =================================================================
    print("\n--- Running HAR-Bespoke forecast ---")
    har_bespoke_fc = har_bespoke_forecast(proxies, target, split_idx)
    print(f"  har_bespoke: {len(har_bespoke_fc)} OOS forecasts")

    # =================================================================
    # Evaluation
    # =================================================================
    actual_oos = target[split_idx:]

    # Collect all models
    all_models = {}
    for col in proxies.columns:
        all_models[f'AR1_{col}'] = individual_forecasts[col]
    all_models['Equal_Weight'] = eq_fc
    all_models['Bespoke_OLS'] = bespoke_ols_fc
    all_models['Bespoke_Ridge'] = bespoke_ridge_fc
    all_models['HAR_Bespoke'] = har_bespoke_fc

    print("\n" + "=" * 70)
    print("OOS EVALUATION (Target = r², Close-to-Close squared return)")
    print("=" * 70)

    results = {}
    print(f"\n{'Model':<20s} {'QLIKE':>10s} {'MSE(×1e6)':>12s} {'MZ_slope':>10s} {'MZ_R²':>8s}")
    print("-" * 62)

    for name, fc in all_models.items():
        q = qlike(actual_oos, fc)
        m = mse(actual_oos, fc)
        mz = mincer_zarnowitz(actual_oos, fc)

        results[name] = {
            'qlike': float(q),
            'mse': float(m),
            'mz_intercept': mz['intercept'],
            'mz_slope': mz['slope'],
            'mz_r2': mz['r2'],
            'mz_t_stat_b1': mz['t_stat_b1'],
            'mz_p_value_b1': mz['p_value_b1']
        }

        print(f"{name:<20s} {q:>10.4f} {m*1e6:>12.4f} {mz['slope']:>10.4f} {mz['r2']:>8.4f}")

    # Best model by QLIKE
    best_qlike = min(results.items(), key=lambda x: x[1]['qlike'])
    best_mse = min(results.items(), key=lambda x: x[1]['mse'])
    print(f"\nBest by QLIKE: {best_qlike[0]} ({best_qlike[1]['qlike']:.4f})")
    print(f"Best by MSE:   {best_mse[0]} ({best_mse[1]['mse']*1e6:.4f} ×1e-6)")

    # =================================================================
    # DM Tests (all pairs vs best QLIKE model)
    # =================================================================
    print("\n--- Diebold-Mariano Tests (QLIKE loss, vs best model) ---")
    best_name = best_qlike[0]
    best_fc = all_models[best_name]

    dm_results = {}
    # Compute QLIKE losses element-wise, masking zeros
    valid_mask = actual_oos > 0
    actual_v = actual_oos[valid_mask]
    best_fc_v = best_fc[valid_mask]
    best_losses = actual_v / best_fc_v - np.log(actual_v / best_fc_v) - 1

    print(f"\n{'Model':<20s} {'vs ' + best_name:>20s} {'DM stat':>10s} {'p-value':>10s} {'Signif':>8s}")
    print("-" * 70)

    for name, fc in all_models.items():
        if name == best_name:
            continue
        fc_v = fc[valid_mask]
        losses_i = actual_v / fc_v - np.log(actual_v / fc_v) - 1
        dm_stat, p_val = dm_test(losses_i, best_losses, h=1)
        signif = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''

        dm_results[name] = {
            'dm_stat': dm_stat,
            'p_value': p_val,
            'significant_10pct': p_val < 0.10,
            'significant_5pct': p_val < 0.05
        }

        print(f"{name:<20s} {'':>20s} {dm_stat:>10.3f} {p_val:>10.4f} {signif:>8s}")

    # Also DM test: Bespoke OLS vs AR1_r2 (most natural comparison)
    print("\n--- Key Comparison: Bespoke OLS vs AR1_r2 ---")
    ar1_r2_v = individual_forecasts['r2'][valid_mask]
    bespoke_v = bespoke_ols_fc[valid_mask]
    losses_ar1_r2 = actual_v / ar1_r2_v - np.log(actual_v / ar1_r2_v) - 1
    losses_bespoke = actual_v / bespoke_v - np.log(actual_v / bespoke_v) - 1
    dm_s, dm_p = dm_test(losses_ar1_r2, losses_bespoke, h=1)
    print(f"  DM stat = {dm_s:.3f}, p-value = {dm_p:.4f}")
    print(f"  Positive DM → AR1_r2 has higher loss → Bespoke is better")

    # Also compare Bespoke OLS vs Equal Weight
    print("\n--- Key Comparison: Bespoke OLS vs Equal Weight ---")
    eq_v = eq_fc[valid_mask]
    losses_eq = actual_v / eq_v - np.log(actual_v / eq_v) - 1
    dm_s2, dm_p2 = dm_test(losses_eq, losses_bespoke, h=1)
    print(f"  DM stat = {dm_s2:.3f}, p-value = {dm_p2:.4f}")

    # =================================================================
    # Weight Analysis
    # =================================================================
    print("\n--- Weight Analysis ---")
    print("\nOLS Final Weights:")
    for k, v in ols_weights['weights'].items():
        print(f"  {k:12s}: {v:.6f}")
    print(f"  Intercept   : {ols_weights['intercept']:.6f}")

    print("\nRidge Final Weights:")
    for k, v in ridge_weights['weights'].items():
        print(f"  {k:12s}: {v:.6f}")
    print(f"  Intercept   : {ridge_weights['intercept']:.6f}")

    # Normalized weights (absolute value shares)
    ols_abs = {k: abs(v) for k, v in ols_weights['weights'].items()}
    total = sum(ols_abs.values())
    print("\nOLS Normalized Weights (|w_i| / Σ|w_j|):")
    for k, v in ols_abs.items():
        print(f"  {k:12s}: {v/total:.3f}")

    # =================================================================
    # Rolling Window Analysis (stability check)
    # =================================================================
    print("\n--- Rolling Weight Stability (250-day rolling OLS) ---")
    window = 250
    proxy_names = proxies.columns.tolist()
    rolling_weights = {p: [] for p in proxy_names}
    rolling_dates = []

    for t in range(split_idx, len(proxies) - 1, 50):  # every 50 days
        start = max(1, t - window)
        Y = target[start+1:t+1]
        X = proxies.iloc[start:t][proxy_names].values
        min_len = min(len(Y), len(X))
        Y = Y[:min_len]
        X = X[:min_len]

        if len(Y) < 50:
            continue

        reg = LinearRegression().fit(X, Y)
        for i, p in enumerate(proxy_names):
            rolling_weights[p].append(reg.coef_[i])
        rolling_dates.append(proxies.index[t])

    print(f"\n{'Proxy':<12s} {'Mean w':>10s} {'Std w':>10s} {'Min w':>10s} {'Max w':>10s}")
    print("-" * 55)
    for p in proxy_names:
        w = np.array(rolling_weights[p])
        print(f"{p:<12s} {np.mean(w):>10.4f} {np.std(w):>10.4f} {np.min(w):>10.4f} {np.max(w):>10.4f}")

    # =================================================================
    # Plots
    # =================================================================

    # Plot 1: Weight Analysis
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # OLS weights bar chart
    ax = axes[0]
    names = list(ols_weights['weights'].keys())
    vals_ols = [ols_weights['weights'][n] for n in names]
    vals_ridge = [ridge_weights['weights'][n] for n in names]
    x = np.arange(len(names))
    width = 0.35
    ax.bar(x - width/2, vals_ols, width, label='OLS', color='steelblue')
    ax.bar(x + width/2, vals_ridge, width, label='Ridge', color='coral')
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=45)
    ax.set_ylabel('Weight')
    ax.set_title('Bespoke Volatility Weights\n(Full-sample estimation)')
    ax.legend()
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.grid(axis='y', alpha=0.3)

    # Rolling weights
    ax = axes[1]
    for p in proxy_names:
        ax.plot(rolling_dates, rolling_weights[p], label=p, linewidth=1)
    ax.set_title('Rolling OLS Weights (250-day window)')
    ax.set_ylabel('Weight')
    ax.legend(fontsize=8)
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45)

    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/k969_weight_analysis.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nSaved: k969_weight_analysis.png")

    # Plot 2: Forecast Comparison
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    oos_dates = proxies.index[split_idx:].to_numpy()

    # Cumulative QLIKE over time (using MSE instead to avoid zero issues)
    ax = axes[0, 0]
    for name in ['AR1_r2', 'AR1_parkinson', 'Equal_Weight', 'Bespoke_OLS', 'Bespoke_Ridge', 'HAR_Bespoke']:
        fc = all_models[name]
        losses = (actual_oos - fc) ** 2
        cum_loss = np.cumsum(losses) / np.arange(1, len(losses) + 1)
        ax.plot(oos_dates, cum_loss, label=name, linewidth=1)
    ax.set_title('Cumulative Average MSE (OOS)')
    ax.set_ylabel('Avg MSE')
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)

    # QLIKE bar chart
    ax = axes[0, 1]
    model_names = list(results.keys())
    qlike_vals = [results[m]['qlike'] for m in model_names]
    colors = ['coral' if m.startswith('Bespoke') or m == 'HAR_Bespoke' else 'steelblue'
              for m in model_names]
    ax.barh(model_names, qlike_vals, color=colors)
    ax.set_xlabel('QLIKE')
    ax.set_title('OOS QLIKE by Model')
    ax.grid(axis='x', alpha=0.3)

    # MZ R²
    ax = axes[1, 0]
    mz_r2_vals = [results[m]['mz_r2'] for m in model_names]
    ax.barh(model_names, mz_r2_vals, color=colors)
    ax.set_xlabel('MZ R²')
    ax.set_title('Mincer-Zarnowitz R² (OOS)')
    ax.grid(axis='x', alpha=0.3)

    # Actual vs forecast scatter (Bespoke OLS)
    ax = axes[1, 1]
    ax.scatter(bespoke_ols_fc, actual_oos, alpha=0.1, s=5, color='steelblue')
    max_val = np.percentile(np.concatenate([bespoke_ols_fc, actual_oos]), 99)
    ax.plot([0, max_val], [0, max_val], 'r--', linewidth=1, label='45° line')
    ax.set_xlabel('Bespoke OLS Forecast')
    ax.set_ylabel('Actual r²')
    ax.set_title('Bespoke OLS: Actual vs Forecast')
    ax.set_xlim(0, max_val)
    ax.set_ylim(0, max_val)
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(f'{OUTPUT_DIR}/k969_forecast_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: k969_forecast_comparison.png")

    # =================================================================
    # Save Results
    # =================================================================

    output = {
        'experiment_id': 'K969',
        'title': 'Bespoke RV — Optimal Daily Volatility Proxy Weighting',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'yfinance (SPY)',
        'sample_period': f"{proxies.index[0].strftime('%Y-%m-%d')} to {proxies.index[-1].strftime('%Y-%m-%d')}",
        'n_total': len(proxies),
        'n_is': int(n_is),
        'n_oos': int(n_oos),
        'is_period': f"{proxies.index[0].strftime('%Y-%m-%d')} to {proxies.index[split_idx-1].strftime('%Y-%m-%d')}",
        'oos_period': f"{proxies.index[split_idx].strftime('%Y-%m-%d')} to {proxies.index[-1].strftime('%Y-%m-%d')}",
        'target': 'r2 (close-to-close squared return)',
        'seed': 42,
        'method': 'Daily-frequency Bespoke Volatility (Patton & Zhang 2026 concept)',
        'references': [
            'Patton & Zhang (2026), Bespoke Realized Volatility, Journal of Econometrics',
            'Patton (2011), Volatility forecast comparison using imperfect volatility proxies, JoE',
            'Garman & Klass (1980), On the estimation of security price volatilities',
            'Yang & Zhang (2000), Drift independent volatility estimation'
        ],
        'proxy_descriptive_stats': {
            col: {
                'mean': float(proxies[col].mean()),
                'std': float(proxies[col].std()),
                'annualized_vol_pct': float(np.sqrt(252 * proxies[col].mean()) * 100)
            }
            for col in proxies.columns
        },
        'proxy_correlations': {
            col: {c: float(corr.loc[col, c]) for c in proxies.columns}
            for col in proxies.columns
        },
        'oos_results': results,
        'best_model_qlike': best_qlike[0],
        'best_model_mse': best_mse[0],
        'dm_tests_vs_best': dm_results,
        'dm_bespoke_ols_vs_ar1_r2': {
            'dm_stat': float(dm_s),
            'p_value': float(dm_p),
            'interpretation': 'Positive DM stat means AR1_r2 has higher loss (Bespoke better)'
        },
        'dm_bespoke_ols_vs_equal_weight': {
            'dm_stat': float(dm_s2),
            'p_value': float(dm_p2)
        },
        'ols_weights': ols_weights,
        'ridge_weights': ridge_weights,
        'rolling_weight_stability': {
            p: {
                'mean': float(np.mean(rolling_weights[p])),
                'std': float(np.std(rolling_weights[p]))
            }
            for p in proxy_names
        },
        'conclusions': []
    }

    # Determine conclusions
    conclusions = []

    # 1. Is Bespoke better than individual proxies?
    bespoke_qlike = results['Bespoke_OLS']['qlike']
    ar1_r2_qlike = results['AR1_r2']['qlike']
    if bespoke_qlike < ar1_r2_qlike:
        pct_improve = (ar1_r2_qlike - bespoke_qlike) / ar1_r2_qlike * 100
        conclusions.append(f"Bespoke OLS improves QLIKE by {pct_improve:.1f}% over AR1(r²)")
    else:
        conclusions.append(f"Bespoke OLS does NOT improve over AR1(r²) in QLIKE")

    # 2. Best individual proxy
    individual_qlikes = {k: v for k, v in results.items() if k.startswith('AR1_')}
    best_individual = min(individual_qlikes.items(), key=lambda x: x[1]['qlike'])
    conclusions.append(f"Best individual proxy: {best_individual[0]} (QLIKE={best_individual[1]['qlike']:.4f})")

    # 3. Largest weight proxy
    abs_weights = {k: abs(v) for k, v in ols_weights['weights'].items()}
    largest_weight_proxy = max(abs_weights.items(), key=lambda x: x[1])
    conclusions.append(f"Largest OLS weight: {largest_weight_proxy[0]} ({ols_weights['weights'][largest_weight_proxy[0]]:.4f})")

    # 4. Ridge vs OLS
    ridge_qlike = results['Bespoke_Ridge']['qlike']
    if ridge_qlike < bespoke_qlike:
        conclusions.append(f"Ridge ({ridge_qlike:.4f}) outperforms OLS ({bespoke_qlike:.4f}) — regularization helps")
    else:
        conclusions.append(f"OLS ({bespoke_qlike:.4f}) outperforms Ridge ({ridge_qlike:.4f}) — no overfitting issue")

    # 5. Statistical significance
    if dm_p < 0.05:
        conclusions.append(f"Bespoke vs AR1(r²) is statistically significant (DM p={dm_p:.4f})")
    elif dm_p < 0.10:
        conclusions.append(f"Bespoke vs AR1(r²) is marginally significant (DM p={dm_p:.4f})")
    else:
        conclusions.append(f"Bespoke vs AR1(r²) is NOT statistically significant (DM p={dm_p:.4f})")

    output['conclusions'] = conclusions

    # Print conclusions
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)
    for i, c in enumerate(conclusions, 1):
        print(f"  {i}. {c}")

    # Save JSON
    with open(f'{OUTPUT_DIR}/k969_bespoke_rv_results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved: k969_bespoke_rv_results.json")

    print("\n✓ K969 experiment complete.")
    return output


if __name__ == '__main__':
    main()
