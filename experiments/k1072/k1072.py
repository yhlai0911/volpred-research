#!/usr/bin/env python3
"""
K1072: Realized Kernel vs Standard RV — Microstructure Noise Robustness for 5-min SPY

Research Questions:
1. Is there detectable microstructure noise in SPY 5-min data? (RK < RV significantly?)
2. Signal-to-noise ratio estimate
3. HAR-RV vs HAR-RK predictive performance
4. A4f DM proxy-sensitivity: are K1054 conclusions robust to proxy choice (RV vs RK)?
5. Subsampled RV (Zhang et al. 2005) as intermediate estimator

Data:
- SPY 5-min: data/intraday/SPY_5min_YYYY-MM-DD.csv (60 days, 2026-01-14 ~ 2026-04-10)
- Pre-computed daily RV: data/intraday/SPY_daily_rv.csv
- Daily SPY/VIX: yfinance

Methods:
- Realized Kernel (Barndorff-Nielsen, Hansen, Lunde & Shephard 2008, Econometrica):
    RK = gamma_0 + sum_{h=1}^{H} k(h/(H+1)) * 2*gamma_h
  with Parzen kernel. Bandwidth H via BNHLS (2008) formula.
- Subsampled RV (Zhang, Mykland & Aït-Sahalia 2005, JASA): 5 offset averages.
- HAR (Corsi 2009) fitted with each estimator.
- DM test (Harvey 2016 |t|>3.0 threshold).
- Random seed: 42.

References:
- Barndorff-Nielsen, Hansen, Lunde & Shephard (2008). Econometrica 76.
- Zhang, Mykland & Aït-Sahalia (2005). JASA 100.
- Patton (2011). JoE (proxy-robust loss).
- Corsi (2009). JFEC (HAR).

Status: PRELIMINARY (60 days, 28-30 OOS << 252).
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from glob import glob

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'
DATA_DIR = os.path.join(MAIN_REPO, 'data', 'intraday')
OUTPUT_DIR = BASE_DIR

print("=" * 70)
print("K1072: Realized Kernel vs Standard RV — Microstructure Noise Robustness")
print("=" * 70)


# ═══════════════════════════════════════════════════════════════════════
# 1. KERNEL AND ESTIMATOR FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def parzen_kernel(x):
    """Parzen kernel function (BNHLS 2008 preferred).

    k(x) = 1 - 6x^2 + 6x^3           for 0 <= x <= 0.5
         = 2(1-x)^3                  for 0.5 < x <= 1
         = 0                         otherwise
    """
    x = np.asarray(x, dtype=float)
    out = np.zeros_like(x)
    mask1 = (x >= 0) & (x <= 0.5)
    mask2 = (x > 0.5) & (x <= 1.0)
    out[mask1] = 1 - 6 * x[mask1] ** 2 + 6 * x[mask1] ** 3
    out[mask2] = 2 * (1 - x[mask2]) ** 3
    return out


def autocov(r, h):
    """Biased autocovariance at lag h: gamma_h = sum_{i} r_i r_{i-h}.
    (Not divided by n, following BNHLS convention — uses raw sum.)
    Note: gamma_h is treated as the empirical sum (same units as RV).
    """
    r = np.asarray(r, dtype=float)
    if h == 0:
        return float(np.sum(r ** 2))
    if h >= len(r):
        return 0.0
    return float(np.sum(r[h:] * r[:-h]))


def realized_variance(r):
    """Standard realized variance: RV = sum r^2."""
    return float(np.sum(np.asarray(r, dtype=float) ** 2))


def realized_kernel(r, H=None):
    """Realized Kernel estimator (BNHLS 2008) with Parzen kernel.

    RK = gamma_0 + sum_{h=1}^{H} k(h/(H+1)) * (gamma_h + gamma_{-h})
       = gamma_0 + sum_{h=1}^{H} k(h/(H+1)) * 2*gamma_h   (time reversible)

    H: bandwidth. If None, use rule-of-thumb H* = max(1, round(c* * n^0.6))
       where c* ~ 3.5134 * xi^0.8 in BNHLS notation, but we provide default
       H=max(1, round(4 * (n/100)^0.5)) (common practical choice with n~78).
       Actual optimal bandwidth is computed separately (see optimal_bandwidth).
    """
    r = np.asarray(r, dtype=float)
    n = len(r)
    if n < 2:
        return realized_variance(r)

    if H is None:
        # Simple rule-of-thumb default (will be overridden by optimal_bandwidth)
        H = max(1, int(round(4 * (n / 100.0) ** 0.5)))

    H = min(H, n - 1)  # cannot exceed n-1

    rk = autocov(r, 0)
    for h in range(1, H + 1):
        w = parzen_kernel(np.array([h / (H + 1)]))[0]
        rk += 2.0 * w * autocov(r, h)

    # RK should be non-negative (Parzen kernel guarantees positive semi-definiteness)
    return max(rk, 1e-20)


def optimal_bandwidth_bnhls(r, kernel_type='parzen'):
    """Approximate optimal bandwidth for Parzen kernel (BNHLS 2008 eq. 4.1).

    H* = c* * (xi^2)^{2/5} * n^{3/5}
    where xi^2 = omega^2 / sqrt(IQ), omega^2 = noise variance,
    IQ = integrated quarticity.

    We estimate:
    - omega^2 from average of RV at highest frequency divided by 2n (if noise iid)
      Crude estimate: omega^2 ≈ -gamma_1 (if noise dominates at high frequency,
      first autocovariance is approximately -omega^2).
      Alternative: omega^2 = gamma_0 / (2n) under pure noise.
    - IQ estimated by (RV^2) / 3 (rough) — for exact need RQ from higher moments.

    For Parzen kernel, c* ~ 3.5134 (BNHLS Table 2).
    """
    r = np.asarray(r, dtype=float)
    n = len(r)
    if n < 10:
        return max(1, int(round(4 * (n / 100.0) ** 0.5)))

    rv = realized_variance(r)
    gamma_1 = autocov(r, 1)

    # Noise variance estimate: if noise iid with var omega^2,
    # cov(r_i, r_{i+1}) ≈ -omega^2 (from differenced mid-prices with additive noise).
    # We use max(−gamma_1 / n, rv/(2n) * fallback) as proxy.
    # Bandi & Russell (2008) style: omega2_hat = sum(r^2) / (2n) under pure noise.
    # More robust: use the ratio gamma_1/gamma_0.
    omega2 = max(-gamma_1 / n, rv / (2.0 * n * 10))  # floor to avoid zero
    omega2 = max(omega2, 1e-20)

    # Integrated quarticity (rough Barndorff-Nielsen & Shephard 2002 estimator):
    # RQ = (n/3) * sum r^4
    rq = (n / 3.0) * np.sum(r ** 4)
    rq = max(rq, 1e-20)

    # xi^2 = omega^2 / sqrt(IQ / n) — noise-to-signal ratio
    sigma2_est = max(rv, 1e-20)  # rough integrated variance
    xi_sq = omega2 / (sigma2_est / n)  # per-observation ratio

    # BNHLS: H* = c* * (xi^2)^{2/5} * n^{3/5}
    c_star = 3.5134  # Parzen kernel constant
    H_star = c_star * (xi_sq ** 0.4) * (n ** 0.6)
    H = max(1, min(n - 1, int(round(H_star))))
    return H


def subsampled_rv(prices, K=5):
    """Subsampled RV (Zhang, Mykland & Ait-Sahalia 2005, JASA).

    Given M total tick prices, compute RV using K different offset start points
    and average. Reduces noise variance by factor ~1/K (under iid noise).

    prices: 1-d array of prices (not returns).
    K: number of subgrids.
    """
    p = np.asarray(prices, dtype=float)
    M = len(p)
    if M < K + 2:
        r = np.diff(np.log(p))  # fallback to log returns
        return realized_variance(r)

    # Each subgrid takes prices at indices [k, k+K, k+2K, ...] and computes RV.
    rv_subs = []
    for k in range(K):
        idx = np.arange(k, M, K)
        if len(idx) < 2:
            continue
        p_sub = p[idx]
        r_sub = np.diff(np.log(p_sub))
        rv_subs.append(np.sum(r_sub ** 2))

    if len(rv_subs) == 0:
        return 0.0
    # Zhang et al. average, plus bias correction (sparse estimator):
    # RV_subs_avg = (1/K) sum_k RV^(k)
    return float(np.mean(rv_subs))


# ═══════════════════════════════════════════════════════════════════════
# 2. LOAD DATA: 5-MIN PRICES AND COMPUTE ESTIMATORS
# ═══════════════════════════════════════════════════════════════════════

print("\n[1] Loading SPY 5-min prices and computing RV / RK / subsampled RV...")

files = sorted(glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv')))
print(f"  Found {len(files)} 5-min CSV files")

estimator_records = []

for fpath in files:
    date_str = os.path.basename(fpath).replace('SPY_5min_', '').replace('.csv', '')
    df_raw = pd.read_csv(fpath, header=[0, 1], index_col=0, parse_dates=True)

    close_col = [c for c in df_raw.columns if 'Close' in str(c)][0]
    prices = df_raw[close_col].dropna().astype(float).values

    n_bars = len(prices)
    if n_bars < 20:
        # Skip gap-filled or severely incomplete days (e.g., 2026-01-30 has 10 bars)
        continue

    # 5-min log returns
    log_r = np.diff(np.log(prices))
    # Standard RV on log returns
    rv = realized_variance(log_r)

    # Realized Kernel with optimal bandwidth
    H_opt = optimal_bandwidth_bnhls(log_r)
    rk = realized_kernel(log_r, H=H_opt)

    # Subsampled RV (K=5)
    rv_sub = subsampled_rv(prices, K=5)

    # Autocovariance diagnostics
    gamma_0 = autocov(log_r, 0)
    gamma_1 = autocov(log_r, 1)
    gamma_2 = autocov(log_r, 2)
    ac1_ratio = gamma_1 / gamma_0 if abs(gamma_0) > 1e-20 else 0.0

    # Noise variance estimate (Bandi-Russell style)
    omega2_hat = max(-gamma_1 / n_bars, 0.0)

    estimator_records.append({
        'date': date_str,
        'n_bars': int(n_bars),
        'rv': float(rv),
        'rk': float(rk),
        'rv_sub': float(rv_sub),
        'H_opt': int(H_opt),
        'gamma_0': float(gamma_0),
        'gamma_1': float(gamma_1),
        'gamma_2': float(gamma_2),
        'ac1_ratio': float(ac1_ratio),
        'omega2_hat': float(omega2_hat),
    })

est_df = pd.DataFrame(estimator_records)
est_df['date'] = pd.to_datetime(est_df['date'])
est_df = est_df.set_index('date').sort_index()

# Exclude days with anomalous n_bars (below 70) for comparison
keep_mask = est_df['n_bars'] >= 70
est_df_full = est_df[keep_mask].copy()

print(f"  Processed {len(est_df)} days, {len(est_df_full)} with >=70 bars (full session)")
print(f"  Sample period: {est_df_full.index[0].date()} to {est_df_full.index[-1].date()}")

# ── Summary statistics of estimators ──
summary_stats = {}
for col in ['rv', 'rk', 'rv_sub']:
    vals = est_df_full[col].values
    summary_stats[col] = {
        'mean': float(np.mean(vals)),
        'std': float(np.std(vals, ddof=1)),
        'min': float(np.min(vals)),
        'max': float(np.max(vals)),
        'median': float(np.median(vals)),
    }

print(f"\n  Estimator summary (n={len(est_df_full)} days):")
print(f"  {'Estimator':<10} | {'Mean':>12} | {'Std':>12} | {'Median':>12}")
print(f"  {'-'*10}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}")
for col in ['rv', 'rk', 'rv_sub']:
    s = summary_stats[col]
    print(f"  {col:<10} | {s['mean']:12.6e} | {s['std']:12.6e} | {s['median']:12.6e}")

# Correlations
corr_rv_rk = float(np.corrcoef(est_df_full['rv'], est_df_full['rk'])[0, 1])
corr_rv_sub = float(np.corrcoef(est_df_full['rv'], est_df_full['rv_sub'])[0, 1])
corr_rk_sub = float(np.corrcoef(est_df_full['rk'], est_df_full['rv_sub'])[0, 1])
print(f"\n  Correlations:")
print(f"    corr(RV, RK)    = {corr_rv_rk:.4f}")
print(f"    corr(RV, RV_sub)= {corr_rv_sub:.4f}")
print(f"    corr(RK, RV_sub)= {corr_rk_sub:.4f}")

# Bandwidth stats
H_stats = {
    'mean': float(est_df_full['H_opt'].mean()),
    'std': float(est_df_full['H_opt'].std(ddof=1)),
    'min': int(est_df_full['H_opt'].min()),
    'max': int(est_df_full['H_opt'].max()),
}
print(f"\n  Optimal bandwidth H* (Parzen, BNHLS): mean={H_stats['mean']:.2f}, range=[{H_stats['min']}, {H_stats['max']}]")


# ═══════════════════════════════════════════════════════════════════════
# 3. NOISE DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════

print("\n[2] Microstructure noise diagnostics...")

# RK vs RV paired test
rv_arr = est_df_full['rv'].values
rk_arr = est_df_full['rk'].values
rvsub_arr = est_df_full['rv_sub'].values

# Relative gap (RV - RK) / RV  — positive means RV > RK (noise inflates RV)
rel_gap_rk = (rv_arr - rk_arr) / np.maximum(rv_arr, 1e-20)
rel_gap_sub = (rv_arr - rvsub_arr) / np.maximum(rv_arr, 1e-20)

print(f"  (RV - RK) / RV:")
print(f"    mean = {np.mean(rel_gap_rk):.4f}")
print(f"    median = {np.median(rel_gap_rk):.4f}")
print(f"    % days RV > RK = {100 * (rel_gap_rk > 0).mean():.1f}%")

print(f"  (RV - RV_sub) / RV:")
print(f"    mean = {np.mean(rel_gap_sub):.4f}")
print(f"    median = {np.median(rel_gap_sub):.4f}")
print(f"    % days RV > RV_sub = {100 * (rel_gap_sub > 0).mean():.1f}%")

# Paired t-test: RV vs RK
t_rv_rk, p_rv_rk = stats.ttest_rel(rv_arr, rk_arr)
# Wilcoxon signed rank (non-parametric robustness)
try:
    w_rv_rk, pw_rv_rk = stats.wilcoxon(rv_arr, rk_arr)
except Exception:
    w_rv_rk, pw_rv_rk = np.nan, np.nan

t_rv_sub, p_rv_sub = stats.ttest_rel(rv_arr, rvsub_arr)

print(f"\n  Paired t-test RV vs RK:   t={t_rv_rk:.3f}, p={p_rv_rk:.4f}")
print(f"  Wilcoxon RV vs RK:         W={w_rv_rk:.2f}, p={pw_rv_rk:.4f}")
print(f"  Paired t-test RV vs sub:   t={t_rv_sub:.3f}, p={p_rv_sub:.4f}")

# Signal-to-noise ratio q: BNHLS define q ≈ omega^2 / IV
# Approximate with omega2_hat and IV ≈ RK
q_daily = est_df_full['omega2_hat'].values / np.maximum(rk_arr / est_df_full['n_bars'].values, 1e-20)
# Actually define q as noise variance / per-observation variance:
q_daily_clean = q_daily[np.isfinite(q_daily) & (q_daily > 0)]
print(f"\n  Noise-to-signal ratio q (omega^2 / (IV/n)):")
if len(q_daily_clean) > 0:
    print(f"    mean = {np.mean(q_daily_clean):.4f}")
    print(f"    median = {np.median(q_daily_clean):.4f}")
    print(f"    range = [{np.min(q_daily_clean):.4f}, {np.max(q_daily_clean):.4f}]")
else:
    print(f"    No positive values — noise negligible at 5-min frequency")

# gamma_1 / gamma_0 : direct first-order noise diagnostic
ac1_arr = est_df_full['ac1_ratio'].values
print(f"\n  First-order autocorrelation gamma_1/gamma_0:")
print(f"    mean = {np.mean(ac1_arr):.4f}")
print(f"    median = {np.median(ac1_arr):.4f}")
print(f"    % days negative (typical for bid-ask bounce) = {100 * (ac1_arr < 0).mean():.1f}%")

noise_diag = {
    'rel_gap_rv_rk_mean': float(np.mean(rel_gap_rk)),
    'rel_gap_rv_rk_median': float(np.median(rel_gap_rk)),
    'pct_rv_gt_rk': float(100 * (rel_gap_rk > 0).mean()),
    'rel_gap_rv_sub_mean': float(np.mean(rel_gap_sub)),
    'rel_gap_rv_sub_median': float(np.median(rel_gap_sub)),
    'pct_rv_gt_sub': float(100 * (rel_gap_sub > 0).mean()),
    't_rv_rk': float(t_rv_rk),
    'p_rv_rk': float(p_rv_rk),
    'wilcoxon_W_rv_rk': float(w_rv_rk) if np.isfinite(w_rv_rk) else None,
    'wilcoxon_p_rv_rk': float(pw_rv_rk) if np.isfinite(pw_rv_rk) else None,
    't_rv_sub': float(t_rv_sub),
    'p_rv_sub': float(p_rv_sub),
    'ac1_ratio_mean': float(np.mean(ac1_arr)),
    'ac1_ratio_median': float(np.median(ac1_arr)),
    'pct_ac1_negative': float(100 * (ac1_arr < 0).mean()),
    'q_mean': float(np.mean(q_daily_clean)) if len(q_daily_clean) > 0 else None,
    'q_median': float(np.median(q_daily_clean)) if len(q_daily_clean) > 0 else None,
}


# ═══════════════════════════════════════════════════════════════════════
# 4. HAR MODELS: HAR-RV vs HAR-RK (and HAR-sub)
# ═══════════════════════════════════════════════════════════════════════

print("\n[3] HAR Models: HAR-RV vs HAR-RK vs HAR-sub...")


def fit_har_and_forecast(series, initial_window=30):
    """Expanding window HAR-RV estimation. Returns forecasts from t=initial_window.

    HAR_t = beta0 + beta_d * x_{t-1} + beta_w * mean(x_{t-1:t-5}) + beta_m * mean(x_{t-1:t-22}) + eps
    """
    s = series.sort_index()
    x = s.values
    n = len(x)

    forecasts = {}
    betas_log = []

    for t in range(initial_window, n):
        train = x[:t]
        n_train = len(train)

        Y, X = [], []
        for i in range(22, n_train):
            Y.append(train[i])
            rv_d = train[i - 1]
            rv_w = np.mean(train[max(0, i - 5):i])
            rv_m = np.mean(train[max(0, i - 22):i])
            X.append([1.0, rv_d, rv_w, rv_m])

        if len(Y) < 5:
            continue
        Y = np.array(Y)
        X = np.array(X)

        try:
            if len(Y) < 15:
                lam = 0.01
                XtX = X.T @ X + lam * np.eye(X.shape[1])
                XtY = X.T @ Y
                beta = np.linalg.solve(XtX, XtY)
            else:
                beta = np.linalg.lstsq(X, Y, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue

        rv_d_f = train[-1]
        rv_w_f = np.mean(train[-5:])
        rv_m_f = np.mean(train[-22:]) if n_train >= 22 else np.mean(train)
        fcast = beta[0] + beta[1] * rv_d_f + beta[2] * rv_w_f + beta[3] * rv_m_f

        rv_mean_train = np.mean(train)
        fcast = np.clip(fcast, rv_mean_train * 0.1, rv_mean_train * 10.0)
        fcast = max(fcast, 1e-12)

        forecasts[s.index[t]] = float(fcast)

        if t == initial_window or t == n - 1:
            betas_log.append({
                'date': str(s.index[t].date()),
                'n_train_obs': int(len(Y)),
                'beta_0': float(beta[0]),
                'beta_d': float(beta[1]),
                'beta_w': float(beta[2]),
                'beta_m': float(beta[3]),
            })

    return pd.Series(forecasts), betas_log


# Fit HAR for each estimator — use est_df_full (58 days) so expanding window is consistent
rv_series = est_df_full['rv']
rk_series = est_df_full['rk']
sub_series = est_df_full['rv_sub']

INITIAL_WINDOW = 30
har_rv_fcast, har_rv_betas = fit_har_and_forecast(rv_series, initial_window=INITIAL_WINDOW)
har_rk_fcast, har_rk_betas = fit_har_and_forecast(rk_series, initial_window=INITIAL_WINDOW)
har_sub_fcast, har_sub_betas = fit_har_and_forecast(sub_series, initial_window=INITIAL_WINDOW)

print(f"  HAR-RV  forecasts: {len(har_rv_fcast)} days")
print(f"  HAR-RK  forecasts: {len(har_rk_fcast)} days")
print(f"  HAR-sub forecasts: {len(har_sub_fcast)} days")


# ═══════════════════════════════════════════════════════════════════════
# 5. HAR EVALUATION ON RK TARGET (RK = noise-robust proxy)
# ═══════════════════════════════════════════════════════════════════════

print("\n[4] Evaluate HAR forecasts against RK target (noise-robust proxy)...")


def qlike_loss(target, forecast):
    f = np.maximum(forecast, 1e-20)
    return target / f + np.log(f)


def mse_loss(target, forecast):
    return (target - forecast) ** 2


def dm_test(loss1, loss2):
    """Diebold-Mariano test with HAC(1) variance.
    Guards against near-identical loss series (var ~ 0) by checking
    relative scale — if d is essentially zero (below numerical noise),
    return t=0 rather than a spurious huge t-stat.
    """
    d = np.asarray(loss1) - np.asarray(loss2)
    n = len(d)
    if n < 2:
        return 0.0, 1.0
    d_bar = d.mean()
    # If d is numerically indistinguishable from zero, no meaningful test
    scale = max(abs(np.mean(loss1)), abs(np.mean(loss2)), 1e-30)
    if abs(d_bar) < 1e-12 * scale and np.std(d) < 1e-12 * scale:
        return 0.0, 1.0
    gamma_0 = np.var(d, ddof=1)
    gamma_1 = np.cov(d[:-1], d[1:])[0, 1] if n > 2 else 0.0
    var_d = gamma_0 + 2 * gamma_1
    # Require variance to be meaningful relative to |d_bar|
    if var_d < 1e-20 or var_d < (abs(d_bar) * 1e-16):
        return 0.0, 1.0
    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_bar / se
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value)


# Align all HAR forecasts to common OOS dates
common_har_dates = har_rv_fcast.index.intersection(
    har_rk_fcast.index
).intersection(har_sub_fcast.index)
print(f"  Common HAR OOS dates: {len(common_har_dates)}")

har_rv_f = har_rv_fcast.loc[common_har_dates].values
har_rk_f = har_rk_fcast.loc[common_har_dates].values
har_sub_f = har_sub_fcast.loc[common_har_dates].values

rv_tgt = est_df_full.loc[common_har_dates, 'rv'].values
rk_tgt = est_df_full.loc[common_har_dates, 'rk'].values
sub_tgt = est_df_full.loc[common_har_dates, 'rv_sub'].values

har_models = {
    'HAR-RV': har_rv_f,
    'HAR-RK': har_rk_f,
    'HAR-sub': har_sub_f,
}
har_targets = {
    'RV': rv_tgt,
    'RK': rk_tgt,
    'RV_sub': sub_tgt,
}

har_eval = {'QLIKE': {}, 'MSE': {}}
har_loss_detail = {}
for tgt_name, tgt in har_targets.items():
    har_eval['QLIKE'][tgt_name] = {}
    har_eval['MSE'][tgt_name] = {}
    har_loss_detail[tgt_name] = {}
    for mod_name, fcast in har_models.items():
        ql = qlike_loss(tgt, fcast)
        ms = mse_loss(tgt, fcast)
        har_eval['QLIKE'][tgt_name][mod_name] = float(ql.mean())
        har_eval['MSE'][tgt_name][mod_name] = float(ms.mean())
        har_loss_detail[tgt_name][mod_name] = ql

print(f"\n  HAR QLIKE (by target):")
print(f"  {'Target':<10} | {'HAR-RV':>10} | {'HAR-RK':>10} | {'HAR-sub':>10}")
print(f"  {'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")
for tgt_name in har_targets:
    row = har_eval['QLIKE'][tgt_name]
    print(f"  {tgt_name:<10} | {row['HAR-RV']:10.4f} | {row['HAR-RK']:10.4f} | {row['HAR-sub']:10.4f}")

# DM test on RK target (key comparison)
har_dm = {}
for tgt_name in har_targets:
    har_dm[tgt_name] = {}
    for m1, m2 in [('HAR-RV', 'HAR-RK'), ('HAR-RV', 'HAR-sub'), ('HAR-RK', 'HAR-sub')]:
        t, p = dm_test(har_loss_detail[tgt_name][m1], har_loss_detail[tgt_name][m2])
        har_dm[tgt_name][f"{m1}_vs_{m2}"] = {
            't_stat': t,
            'p_value': p,
            'harvey_significant': str(abs(t) > 3.0),
            'direction': f"{m2} better" if t > 0 else f"{m1} better",
        }

print(f"\n  DM tests (HAR models, QLIKE, various targets):")
for tgt_name, pairs in har_dm.items():
    for pair, res in pairs.items():
        sig = "***" if res['harvey_significant'] == 'True' else ""
        print(f"    {tgt_name:<8} | {pair:<24} t={res['t_stat']:+.3f} p={res['p_value']:.4f} => {res['direction']}{sig}")


# ═══════════════════════════════════════════════════════════════════════
# 6. A4f PROXY SENSITIVITY — REPLICATE K1054 A4f ON RK TARGET
# ═══════════════════════════════════════════════════════════════════════

print("\n[5] A4f proxy sensitivity: re-evaluate K1054 A4f using RK target...")

# Load daily SPY returns and VIX
import yfinance as yf
start_date = '2015-01-01'
end_date = '2026-04-15'

print(f"  Downloading SPY/VIX daily data...")
spy_daily = yf.download('SPY', start=start_date, end=end_date, progress=False)
vix_daily = yf.download('^VIX', start=start_date, end=end_date, progress=False)

if isinstance(spy_daily.columns, pd.MultiIndex):
    spy_daily.columns = spy_daily.columns.get_level_values(0)
if isinstance(vix_daily.columns, pd.MultiIndex):
    vix_daily.columns = vix_daily.columns.get_level_values(0)

spy_close = spy_daily['Close'].squeeze()
vix_close = vix_daily['Close'].squeeze()
spy_returns = np.log(spy_close / spy_close.shift(1)).dropna()
r_squared = spy_returns ** 2

# OOS dates = HAR common OOS dates (same as K1054 convention)
oos_dates = common_har_dates

# Fit GJR-GARCH and A4f on expanding window (K1054-style), produce forecasts on oos_dates
GARCH_WINDOW = 2000
ret_pct = spy_returns * 100

print(f"  Fitting GJR-GARCH and A4f-VIX² on {len(oos_dates)} OOS days...")
gjr_f = {}
a4f_f = {}

for date in oos_dates:
    # ── GJR-GARCH ──
    train_ret = ret_pct[ret_pct.index < date]
    if len(train_ret) < 500:
        continue
    if len(train_ret) > GARCH_WINDOW:
        train_ret = train_ret.iloc[-GARCH_WINDOW:]
    try:
        m = arch_model(train_ret, vol='GARCH', p=1, o=1, q=1, dist='normal')
        r = m.fit(disp='off', show_warning=False)
        fc = r.forecast(horizon=1, reindex=False)
        var_dec = float(fc.variance.values[-1, 0]) / 10000.0
        gjr_f[date] = max(var_dec, 1e-12)
    except Exception:
        pass

    # ── A4f-VIX² ──
    train_ret_a = spy_returns[spy_returns.index < date]
    train_vix = vix_close.reindex(train_ret_a.index).ffill().dropna()
    common_idx = train_ret_a.index.intersection(train_vix.index)
    if len(common_idx) < 500:
        continue
    train_ret_a = train_ret_a.loc[common_idx]
    train_vix = train_vix.loc[common_idx]
    if len(train_ret_a) > GARCH_WINDOW:
        train_ret_a = train_ret_a.iloc[-GARCH_WINDOW:]
        train_vix = train_vix.iloc[-GARCH_WINDOW:]

    vix_sq = (train_vix / 100) ** 2 / 252
    vix_sq_lag = vix_sq.shift(1).dropna()
    r_sq_t = (train_ret_a ** 2).reindex(vix_sq_lag.index).dropna()
    vix_sq_lag = vix_sq_lag.reindex(r_sq_t.index)
    X_tau = np.column_stack([np.ones(len(vix_sq_lag)), vix_sq_lag.values])
    Y_tau = r_sq_t.values
    try:
        theta = np.linalg.lstsq(X_tau, Y_tau, rcond=None)[0]
    except np.linalg.LinAlgError:
        continue
    theta[0] = max(theta[0], 1e-10)
    if theta[1] < 0:
        theta[1] = 0
    tau_tr = theta[0] + theta[1] * vix_sq_lag.values
    tau_tr = np.maximum(tau_tr, 1e-10)
    aligned_r = train_ret_a.reindex(vix_sq_lag.index).values
    u_tr = aligned_r / np.sqrt(tau_tr)
    u_s = pd.Series(u_tr * 100, index=vix_sq_lag.index)
    try:
        mu = arch_model(u_s, vol='GARCH', p=1, o=1, q=1, dist='normal')
        ru = mu.fit(disp='off', show_warning=False)
        fcu = ru.forecast(horizon=1, reindex=False)
        g_pct = float(fcu.variance.values[-1, 0]) / 10000.0
        vix_for_f = vix_close[vix_close.index < date]
        if len(vix_for_f) == 0:
            continue
        last_vix = float(vix_for_f.iloc[-1])
        vix_sq_f = (last_vix / 100) ** 2 / 252
        tau_f = theta[0] + theta[1] * vix_sq_f
        tau_f = max(tau_f, 1e-10)
        a4f_f[date] = max(tau_f * g_pct, 1e-12)
    except Exception:
        pass

gjr_s = pd.Series(gjr_f)
a4f_s = pd.Series(a4f_f)

# Common forecast dates (a4f, gjr, har_rv, rk target)
a4f_common = oos_dates.intersection(gjr_s.index).intersection(a4f_s.index).intersection(r_squared.index)
print(f"  A4f common OOS dates: {len(a4f_common)}")

har_rv_v = har_rv_fcast.loc[a4f_common].values
gjr_v = gjr_s.loc[a4f_common].values
a4f_v = a4f_s.loc[a4f_common].values
r2_t = r_squared.loc[a4f_common].values
rv_t = est_df_full.loc[a4f_common, 'rv'].values
rk_t = est_df_full.loc[a4f_common, 'rk'].values
sub_t = est_df_full.loc[a4f_common, 'rv_sub'].values

models = {'HAR-RV': har_rv_v, 'GJR-GARCH': gjr_v, 'A4f-VIX²': a4f_v}
proxies = {'RV_5min': rv_t, 'RK': rk_t, 'RV_sub': sub_t, 'r2_daily': r2_t}

main_eval = {'QLIKE': {}, 'MSE': {}}
main_loss_detail = {}
for pname, tgt in proxies.items():
    main_eval['QLIKE'][pname] = {}
    main_eval['MSE'][pname] = {}
    main_loss_detail[pname] = {}
    for mname, fc in models.items():
        ql = qlike_loss(tgt, fc)
        ms = mse_loss(tgt, fc)
        main_eval['QLIKE'][pname][mname] = float(ql.mean())
        main_eval['MSE'][pname][mname] = float(ms.mean())
        main_loss_detail[pname][mname] = ql

print(f"\n  QLIKE by proxy and model (K1054 + RK + RV_sub):")
header = f"  {'Proxy':<10} |" + "".join(f" {m:>12} |" for m in models)
print(header)
print(f"  {'-'*10}-+-" + "-+-".join(["-"*12 for _ in models]))
for pname in proxies:
    row = main_eval['QLIKE'][pname]
    rowstr = f"  {pname:<10} |" + "".join(f" {row[m]:12.4f} |" for m in models)
    print(rowstr)

# DM tests on each proxy
main_dm = {}
pairs = [('HAR-RV', 'GJR-GARCH'), ('HAR-RV', 'A4f-VIX²'), ('GJR-GARCH', 'A4f-VIX²')]
for pname in proxies:
    main_dm[pname] = {}
    for m1, m2 in pairs:
        t, p = dm_test(main_loss_detail[pname][m1], main_loss_detail[pname][m2])
        main_dm[pname][f"{m1}_vs_{m2}"] = {
            't_stat': t,
            'p_value': p,
            'harvey_significant': str(abs(t) > 3.0),
            'direction': f"{m2} better" if t > 0 else f"{m1} better",
        }

print(f"\n  DM tests (QLIKE) under each proxy:")
for pname in proxies:
    for pair, res in main_dm[pname].items():
        sig = "***" if res['harvey_significant'] == 'True' else ""
        print(f"    {pname:<10} | {pair:<26} t={res['t_stat']:+.3f} p={res['p_value']:.4f} => {res['direction']}{sig}")

# Cross-proxy ranking consistency
rankings = {}
for pname in proxies:
    ql_d = main_eval['QLIKE'][pname]
    sorted_m = sorted(ql_d.keys(), key=lambda k: ql_d[k])
    rankings[pname] = sorted_m

print(f"\n  QLIKE Rankings across proxies:")
for pname, rk in rankings.items():
    print(f"    {pname:<10}: {' > '.join(rk)}")

all_same_ranking = all(rankings[p] == rankings['RK'] for p in rankings)
print(f"  Rankings identical across all proxies: {all_same_ranking}")


# ═══════════════════════════════════════════════════════════════════════
# 7. FIGURES
# ═══════════════════════════════════════════════════════════════════════

print("\n[6] Generating figures...")

# ── Figure 1: Estimator comparison ──
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K1072: Realized Kernel vs RV vs Subsampled RV (SPY 5-min, 58 days)',
             fontsize=13, fontweight='bold')

ax = axes[0, 0]
ax.plot(est_df_full.index, est_df_full['rv'], label='RV (standard)', color='steelblue', linewidth=1.2)
ax.plot(est_df_full.index, est_df_full['rk'], label='RK (Parzen)', color='coral', linewidth=1.2)
ax.plot(est_df_full.index, est_df_full['rv_sub'], label='RV_sub (K=5)', color='seagreen', linewidth=1.2, linestyle='--')
ax.set_title('(A) Time Series of Three Estimators')
ax.set_ylabel('Estimator value')
ax.legend(fontsize=8)
ax.grid(alpha=0.3)
ax.tick_params(axis='x', rotation=30)

ax = axes[0, 1]
ax.scatter(est_df_full['rv'], est_df_full['rk'], alpha=0.7, label='RV vs RK', color='coral')
ax.scatter(est_df_full['rv'], est_df_full['rv_sub'], alpha=0.5, label='RV vs RV_sub', color='seagreen', marker='^')
mx = max(est_df_full['rv'].max(), est_df_full['rk'].max(), est_df_full['rv_sub'].max())
ax.plot([0, mx], [0, mx], 'k--', linewidth=0.6, label='45° line')
ax.set_xlabel('RV (standard)')
ax.set_ylabel('RK or RV_sub')
ax.set_title(f'(B) Scatter (corr RV/RK={corr_rv_rk:.3f})')
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

ax = axes[1, 0]
ax.bar(['RV', 'RK', 'RV_sub'], [summary_stats['rv']['mean'], summary_stats['rk']['mean'], summary_stats['rv_sub']['mean']],
       color=['steelblue', 'coral', 'seagreen'], alpha=0.8)
ax.set_title('(C) Mean of Each Estimator')
ax.set_ylabel('Mean (sample avg)')
ax.grid(axis='y', alpha=0.3)
for i, v in enumerate([summary_stats['rv']['mean'], summary_stats['rk']['mean'], summary_stats['rv_sub']['mean']]):
    ax.text(i, v * 1.02, f'{v:.2e}', ha='center', fontsize=8)

ax = axes[1, 1]
ax.hist(rel_gap_rk, bins=15, alpha=0.6, color='coral', label=f'(RV-RK)/RV, mean={np.mean(rel_gap_rk):.3f}')
ax.hist(rel_gap_sub, bins=15, alpha=0.4, color='seagreen', label=f'(RV-sub)/RV, mean={np.mean(rel_gap_sub):.3f}')
ax.axvline(0, color='k', linewidth=0.6)
ax.set_title('(D) Relative Gap vs RV')
ax.set_xlabel('Relative gap')
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1072_estimator_comparison.png'), dpi=130, bbox_inches='tight')
plt.close()

# ── Figure 2: Noise diagnostics ──
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K1072: Microstructure Noise Diagnostics', fontsize=13, fontweight='bold')

ax = axes[0, 0]
ax.plot(est_df_full.index, est_df_full['ac1_ratio'], color='purple', linewidth=1.2)
ax.axhline(0, color='k', linewidth=0.6)
ax.set_title('(A) First-order Autocorrelation (gamma_1/gamma_0)')
ax.set_ylabel('gamma_1 / gamma_0')
ax.grid(alpha=0.3)
ax.tick_params(axis='x', rotation=30)

ax = axes[0, 1]
ax.hist(est_df_full['ac1_ratio'], bins=15, color='purple', alpha=0.7)
ax.axvline(0, color='k', linewidth=0.6)
ax.axvline(est_df_full['ac1_ratio'].mean(), color='red', linewidth=1.0, label=f"mean={est_df_full['ac1_ratio'].mean():.3f}")
ax.set_xlabel('gamma_1 / gamma_0')
ax.set_title(f"(B) Distribution (%<0 = {noise_diag['pct_ac1_negative']:.0f}%)")
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

ax = axes[1, 0]
ax.plot(est_df_full.index, est_df_full['omega2_hat'], color='teal', linewidth=1.2)
ax.set_title('(C) Noise Variance Estimate ω² = max(-γ₁/n, 0)')
ax.set_ylabel('omega^2 (per-obs)')
ax.grid(alpha=0.3)
ax.tick_params(axis='x', rotation=30)

ax = axes[1, 1]
ax.plot(est_df_full.index, est_df_full['H_opt'], color='darkorange', linewidth=1.2, marker='o', markersize=3)
ax.set_title(f"(D) Optimal Bandwidth H* (Parzen, BNHLS 2008), mean={H_stats['mean']:.1f}")
ax.set_ylabel('H*')
ax.grid(alpha=0.3)
ax.tick_params(axis='x', rotation=30)

plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1072_noise_diagnostics.png'), dpi=130, bbox_inches='tight')
plt.close()

# ── Figure 3: HAR comparison ──
fig, ax = plt.subplots(1, 1, figsize=(10, 6))
tgt_names = list(har_targets.keys())
mod_names = list(har_models.keys())
x = np.arange(len(tgt_names))
width = 0.27

colors = ['steelblue', 'coral', 'seagreen']
for i, (mname, color) in enumerate(zip(mod_names, colors)):
    vals = [har_eval['QLIKE'][t][mname] for t in tgt_names]
    bars = ax.bar(x + (i - 1) * width, vals, width, label=mname, color=color, alpha=0.8)
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02,
                f'{b.get_height():.3f}', ha='center', fontsize=7)

ax.set_xticks(x)
ax.set_xticklabels(tgt_names)
ax.set_ylabel('QLIKE (lower is better)')
ax.set_title('K1072: HAR-RV vs HAR-RK vs HAR-sub (QLIKE by target)')
ax.legend()
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1072_har_comparison.png'), dpi=130, bbox_inches='tight')
plt.close()

# ── Figure 4: A4f proxy sensitivity ──
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle('K1072: A4f Proxy Sensitivity (K1054 re-evaluated across proxies)', fontsize=13, fontweight='bold')

# Panel A: QLIKE heatmap
ax = axes[0]
proxy_names = list(proxies.keys())
model_names = list(models.keys())
data = np.array([[main_eval['QLIKE'][p][m] for m in model_names] for p in proxy_names])
im = ax.imshow(data, aspect='auto', cmap='RdYlGn_r')
ax.set_xticks(range(len(model_names)))
ax.set_xticklabels(model_names)
ax.set_yticks(range(len(proxy_names)))
ax.set_yticklabels(proxy_names)
for i in range(len(proxy_names)):
    for j in range(len(model_names)):
        ax.text(j, i, f'{data[i, j]:.3f}', ha='center', va='center', fontsize=9,
                color='black' if abs(data[i, j]) < abs(data).mean() else 'white')
ax.set_title('(A) QLIKE (Model × Proxy)')
plt.colorbar(im, ax=ax)

# Panel B: DM t-stats (HAR vs A4f) under different proxies
ax = axes[1]
proxy_plot = list(proxies.keys())
pair_plot = ('HAR-RV', 'A4f-VIX²')
ts_a = []
for pname in proxy_plot:
    ts_a.append(main_dm[pname][f"{pair_plot[0]}_vs_{pair_plot[1]}"]['t_stat'])
ax.bar(proxy_plot, ts_a, color=['steelblue', 'coral', 'seagreen', 'purple'], alpha=0.8)
ax.axhline(3.0, color='red', linestyle='--', linewidth=0.8, label='Harvey |t|>3.0')
ax.axhline(-3.0, color='red', linestyle='--', linewidth=0.8)
ax.set_ylabel('DM t-stat (HAR-RV vs A4f, positive = A4f better)')
ax.set_title('(B) DM t-stat for HAR-RV vs A4f across proxies')
ax.legend(fontsize=8)
ax.grid(axis='y', alpha=0.3)
for i, v in enumerate(ts_a):
    ax.text(i, v + 0.1 * np.sign(v), f'{v:+.2f}', ha='center', fontsize=8,
            va='bottom' if v >= 0 else 'top')

plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1072_a4f_proxy_sensitivity.png'), dpi=130, bbox_inches='tight')
plt.close()

print(f"  Figures saved to {OUTPUT_DIR}/")


# ═══════════════════════════════════════════════════════════════════════
# 8. SAVE RESULTS JSON
# ═══════════════════════════════════════════════════════════════════════

print("\n[7] Saving results JSON...")

results = {
    'experiment_id': 'K1072',
    'title': 'Realized Kernel vs RV — Microstructure Noise Robustness for 5-min SPY',
    'status': 'PRELIMINARY',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'research_questions': [
        'H1: Is there detectable microstructure noise in SPY 5-min data (RK < RV)?',
        'H2: What is the signal-to-noise ratio?',
        'H3: Does HAR-RK outperform HAR-RV on RK target?',
        'H4: Is K1054 A4f DM result robust to proxy choice (RV vs RK)?',
        'H5: Does subsampled RV land between RV and RK?',
    ],
    'data': {
        'asset': 'SPY',
        'source': 'data/intraday/SPY_5min_*.csv (yfinance)',
        'n_files': len(files),
        'n_days_full': int(len(est_df_full)),
        'period': f"{est_df_full.index[0].date()} to {est_df_full.index[-1].date()}",
        'min_bars_kept': 70,
    },
    'methods': {
        'kernel': 'Parzen (BNHLS 2008)',
        'bandwidth_rule': 'Optimal H* via BNHLS (2008) eq. 4.1 approximation',
        'subsampling': 'Zhang et al. (2005), K=5 subgrids averaged',
        'HAR': 'Corsi (2009), expanding window OLS, initial=30 days, ridge fallback for small n',
        'a4f': 'Engle & Rangel (2008) style: tau = theta0 + theta1 * VIX^2, GJR on u',
        'dm_threshold': 'Harvey (2016) |t|>3.0',
        'random_seed': 42,
    },
    'estimator_summary': summary_stats,
    'correlations': {
        'rv_rk': corr_rv_rk,
        'rv_sub': corr_rv_sub,
        'rk_sub': corr_rk_sub,
    },
    'bandwidth_stats': H_stats,
    'noise_diagnostics': noise_diag,
    'har_evaluation': {
        'common_oos_days': int(len(common_har_dates)),
        'oos_period': f"{common_har_dates[0].date()} to {common_har_dates[-1].date()}" if len(common_har_dates) > 0 else None,
        'betas_har_rv_first_last': har_rv_betas,
        'betas_har_rk_first_last': har_rk_betas,
        'betas_har_sub_first_last': har_sub_betas,
        'qlike': har_eval['QLIKE'],
        'mse': har_eval['MSE'],
        'dm_tests': har_dm,
    },
    'a4f_proxy_sensitivity': {
        'common_oos_days': int(len(a4f_common)),
        'models_evaluated': list(models.keys()),
        'proxies_evaluated': list(proxies.keys()),
        'qlike': main_eval['QLIKE'],
        'mse': main_eval['MSE'],
        'dm_tests': main_dm,
        'rankings': {p: rankings[p] for p in rankings},
        'rankings_identical_across_proxies': all_same_ranking,
    },
    'per_day_estimators': est_df_full.reset_index().to_dict(orient='records'),
    'files': {
        'script': 'experiments/k1072/k1072.py',
        'results_json': 'experiments/k1072/k1072_results.json',
        'figures': [
            'experiments/k1072/k1072_estimator_comparison.png',
            'experiments/k1072/k1072_noise_diagnostics.png',
            'experiments/k1072/k1072_har_comparison.png',
            'experiments/k1072/k1072_a4f_proxy_sensitivity.png',
        ],
        'readme': 'experiments/k1072/README.md',
    },
    'references': [
        'Barndorff-Nielsen, Hansen, Lunde & Shephard (2008). Econometrica 76.',
        'Zhang, Mykland & Ait-Sahalia (2005). JASA 100.',
        'Patton (2011). Journal of Econometrics.',
        'Corsi (2009). Journal of Financial Econometrics.',
        'Harvey (2016). International Journal of Forecasting.',
    ],
    'limitations': [
        'Only 58 days of 5-min data (OOS ~28) — PRELIMINARY, not publishable alone.',
        'Noise variance estimate omega^2 = max(-gamma_1/n, 0) is crude; better estimates need realized autocovariance at multiple lags.',
        'Subsampled RV K=5 chosen heuristically; Zhang et al. also propose two-scales RV (TSRV) which is not implemented here.',
        'OOS period extends K1054 (roughly same dates); full-sample conclusions require >=252 OOS days.',
    ],
}


def convert_numpy(obj):
    """Convert numpy types to Python natives for JSON."""
    if isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_numpy(x) for x in obj]
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


results_clean = convert_numpy(results)

json_path = os.path.join(OUTPUT_DIR, 'k1072_results.json')
with open(json_path, 'w') as fh:
    json.dump(results_clean, fh, indent=2, default=str)

print(f"  Saved: {json_path}")

# ── Final summary print ──
print("\n" + "=" * 70)
print("K1072 SUMMARY")
print("=" * 70)
print(f"Sample: {len(est_df_full)} full-session days ({est_df_full.index[0].date()} ~ {est_df_full.index[-1].date()})")
print(f"RV mean  = {summary_stats['rv']['mean']:.4e}")
print(f"RK mean  = {summary_stats['rk']['mean']:.4e}")
print(f"RV_sub   = {summary_stats['rv_sub']['mean']:.4e}")
print(f"(RV-RK)/RV mean   = {noise_diag['rel_gap_rv_rk_mean']:+.4f}")
print(f"paired t RV vs RK = {noise_diag['t_rv_rk']:+.3f} (p={noise_diag['p_rv_rk']:.4f})")
print(f"gamma_1/gamma_0 mean = {noise_diag['ac1_ratio_mean']:+.4f}")
print(f"% days RV > RK = {noise_diag['pct_rv_gt_rk']:.1f}%")
print(f"A4f rankings identical across all proxies: {all_same_ranking}")
print(f"HAR OOS days: {len(common_har_dates)}; A4f OOS days: {len(a4f_common)}")
print("=" * 70)
print("K1072 COMPLETE")
