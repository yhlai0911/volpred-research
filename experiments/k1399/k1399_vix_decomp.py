"""
K1399: VIX Feature Decomposition in HAR
========================================
Asset    : SPY (local CSV: paper/leverage-direction/data/spy_vix_2004-2026.csv)
Period   : IS 2005-01-04 to 2018-12-31, OOS 2019-01-02 to latest
Target   : |r_t|  (daily absolute log return, HAR-ABS paradigm, consistent with K1315)
Models   : HAR-ABS (baseline), HAR-VIX-L, HAR-VIX-dV, HAR-VIX-P, HAR-VIX-T, HAR-VIX-All
Loss     : QLIKE (Patton 2011 form B: mean[log(yhat) + y/yhat])
Tests    : DM-HLN (Harvey et al. 1997) — |t| > 3.0 Harvey threshold

Research Question:
  K1315 confirmed HAR-VIX (DM t=4.58 vs HAR-ABS, Harvey-significant).
  K1399 decomposes: which VIX component drives the advantage?

Hypotheses:
  H1: VIX level provides significant predictive power (expected PASS, replication of K1315)
  H2: DVIX (change) carries incremental info beyond level
  H3: Vol premium (VIX/|r|) carries regime information
  H4: VIX trend (MA5) provides no additional info (trend already in level)
  H5: All-feature HAR-X not significantly better than best single-feature (parsimony)

Lookahead Prevention (CRITICAL):
  rv1_t   = |r_{t-1}|                        → abs_r.shift(1)
  rv5_t   = mean(|r_{t-5}..r_{t-1}|)        → abs_r.rolling(5).mean().shift(1)
  rv22_t  = mean(|r_{t-22}..r_{t-1}|)       → abs_r.rolling(22).mean().shift(1)
  VIX_L_t = VIX_{t-1}                        → vix_close.shift(1)
  dVIX_t  = VIX_{t-1} - VIX_{t-2}           → vix_close.diff().shift(1)
  VIX_P_t = VIX_{t-1} / (|r_{t-1}| * sqrt(252))  → (vix_close / (abs_r * sqrt(252))).shift(1)
  VIX_T_t = MA5_VIX_{t-1}                    → vix_close.rolling(5).mean().shift(1)

All features use t-1 data to predict t; verified by printed index alignment.

References:
  Corsi (2009), JFE — HAR-RV model
  Patton (2011), JFE — robust loss functions for volatility forecasting
  Harvey, Leybourne, Newbold (1997, IJoF) — DM-HLN finite-sample correction
  Harvey et al. (2016) — higher threshold |t|>3 for multiple comparisons
  Whaley (2000), JoD — VIX as fear gauge
  Bollerslev et al. (2009), RFS — variance risk premium
"""

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.stattools import durbin_watson
from statsmodels.stats.outliers_influence import variance_inflation_factor
from scipy.stats import t as t_dist
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import os
import warnings
from datetime import datetime
warnings.filterwarnings('ignore')

np.random.seed(42)

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Navigate up to repo root (worktree root)
REPO_ROOT  = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
DATA_PATH  = os.path.join(REPO_ROOT, 'paper', 'leverage-direction', 'data', 'spy_vix_2004-2026.csv')
RESULTS_JSON = os.path.join(SCRIPT_DIR, 'k1399_vix_decomp_results.json')
CHART_PATH   = os.path.join(SCRIPT_DIR, 'k1399_qlike_comparison.png')

# ─── Constants ────────────────────────────────────────────────────────────────
IS_START  = '2005-01-04'
IS_END    = '2018-12-31'
OOS_START = '2019-01-02'
EPS       = 1e-8           # min forecast floor to avoid log(0)
HARVEY_THRESHOLD = 3.0     # Harvey et al. (2016) stringent significance level
VIF_THRESHOLD    = 10.0    # multicollinearity warning

# ─── 1. Load Data ─────────────────────────────────────────────────────────────
print("=" * 60)
print("K1399: VIX Feature Decomposition in HAR")
print("=" * 60)
print(f"\nLoading data from: {DATA_PATH}")
df_raw = pd.read_csv(DATA_PATH, parse_dates=['date'], index_col='date')
print(f"Raw data shape: {df_raw.shape}")
print(f"Columns available: {list(df_raw.columns)}")
print(f"Date range: {df_raw.index[0].date()} to {df_raw.index[-1].date()}")

# Use spy_adj_close and vix_close
spy_close = df_raw['spy_adj_close'].dropna()
vix_close  = df_raw['vix_close'].dropna()

# Align to common index
common_idx = spy_close.index.intersection(vix_close.index)
spy_close  = spy_close.loc[common_idx]
vix_close  = vix_close.loc[common_idx]

# ─── 2. Compute Returns and Target ───────────────────────────────────────────
log_ret = np.log(spy_close / spy_close.shift(1))  # log returns
abs_r   = log_ret.abs()                            # |r_t| = prediction target

print(f"\nAbsolute return stats (abs_r):")
print(f"  count={abs_r.dropna().shape[0]}, mean={abs_r.mean():.6f}, std={abs_r.std():.6f}")
print(f"  Zero returns (abs_r==0): {(abs_r==0).sum()}")

# ─── 3. Compute HAR Features (all with shift(1) — LOOKAHEAD PROTECTION) ──────
print("\n--- Feature Construction (all shift(1)) ---")

# HAR components
rv1  = abs_r.shift(1)                          # t-1 day |r|
rv5  = abs_r.rolling(5).mean().shift(1)        # t-1 to t-5 average
rv22 = abs_r.rolling(22).mean().shift(1)       # t-1 to t-22 average

# VIX features
vix_level = vix_close.shift(1)                          # H1: VIX level
dvix      = vix_close.diff().shift(1)                    # H2: DVIX (change)

# Vol premium: VIX_t / (|r_t| * sqrt(252)) — proxy for implied/realized spread
# Implementation: compute premium_raw(t) = VIX(t) / (|r(t)| * sqrt(252)) at each date t,
# then shift(1) so that premium used to predict day-t is premium_raw(t-1).
# Equivalent to using both VIX(t-1) and |r(t-1)| as of t-1 — no lookahead.
premium_raw = vix_close / (abs_r * np.sqrt(252))  # premium at t using t-day data
# Handle inf from zero abs_r BEFORE shift — replace inf with NaN, then ffill
premium_raw = premium_raw.replace([np.inf, -np.inf], np.nan)
# Winsorize at 99th percentile to prevent extreme leverage values from dominating OLS
# (e.g. VIX=15, abs_r=0.0001 gives premium~9450 — will destroy OOS forecasts)
# Use IS-sample 99th percentile as cap.
# Use IS_END exclusive of the final date: the last IS predictor row is premium_raw[IS_END-1day]
# (since premium = premium_raw.shift(1)), so we align the percentile range accordingly.
is_end_exclusive = pd.Timestamp(IS_END) - pd.tseries.offsets.BDay(1)
p99_is = premium_raw.loc[:is_end_exclusive].quantile(0.99)
p01_is = premium_raw.loc[:is_end_exclusive].quantile(0.01)
print(f"  IS percentile bound range: {IS_START} to {is_end_exclusive.date()} (aligned IS features)")
print(f"  premium_raw IS 1st-99th pct: [{p01_is:.2f}, {p99_is:.2f}]")
print(f"  premium_raw IS mean: {premium_raw.loc[:is_end_exclusive].mean():.2f}, "
      f"median: {premium_raw.loc[:is_end_exclusive].median():.2f}")
premium_raw_winsor = premium_raw.clip(lower=p01_is, upper=p99_is)
# shift(1): predictor at time t uses winsorized premium_raw from t-1 — lookahead-safe
premium = premium_raw_winsor.shift(1)
# Forward-fill residual NaN (at most limit=5 consecutive missing)
print(f"  premium NaN count before ffill: {premium.isna().sum()}")
premium = premium.ffill(limit=5)
print(f"  premium NaN count after ffill: {premium.isna().sum()}")
print(f"  premium range after winsor+shift: [{premium.min():.2f}, {premium.max():.2f}]")

ma5_vix = vix_close.rolling(5).mean().shift(1)     # H4: VIX trend (MA5)

# ─── LOOKAHEAD VERIFICATION ───────────────────────────────────────────────────
print("\n--- Lookahead Verification (first 5 rows of feature matrix) ---")
feat_check = pd.DataFrame({
    'abs_r(t)': abs_r,
    'rv1(t-1)': rv1,
    'rv5(t-1)': rv5,
    'vix(t)':   vix_close,
    'vix_L(t-1)': vix_level,
    'dvix(t-1)':  dvix,
    'prem(t-1)':  premium,
    'ma5_vix(t-1)': ma5_vix
}).dropna().head(5)
print(feat_check.to_string())
print("\nVerification: rv1[date_i] should equal abs_r[date_{i-1}] (aligned by date index):")
abs_r_check = abs_r.dropna()
rv1_check   = rv1.dropna()
common_check = abs_r_check.index.intersection(rv1_check.index)[:3]
for d in common_check:
    pos = abs_r_check.index.get_loc(d) - 1
    if pos >= 0:
        prev_d = abs_r_check.index[pos]
        match = abs(rv1_check[d] - abs_r_check.iloc[pos]) < 1e-10
        print(f"  rv1[{d.date()}]={rv1_check[d]:.6f} == abs_r[{prev_d.date()}]={abs_r_check.iloc[pos]:.6f}: {match}")

# ─── 4. Build Feature DataFrame ───────────────────────────────────────────────
data = pd.DataFrame({
    'y':       abs_r,
    'rv1':     rv1,
    'rv5':     rv5,
    'rv22':    rv22,
    'vix_L':   vix_level,
    'dvix':    dvix,
    'premium': premium,
    'ma5_vix': ma5_vix
}).dropna()

print(f"\nFull dataset after dropna: {data.shape[0]} observations")
print(f"Date range: {data.index[0].date()} to {data.index[-1].date()}")

# ─── 5. IS / OOS Split ────────────────────────────────────────────────────────
is_data  = data.loc[IS_START:IS_END]
oos_data = data.loc[OOS_START:]

print(f"\nIS:  {is_data.index[0].date()} to {is_data.index[-1].date()}, n={len(is_data)}")
print(f"OOS: {oos_data.index[0].date()} to {oos_data.index[-1].date()}, n={len(oos_data)}")

# ─── 6. Model Specifications ─────────────────────────────────────────────────
model_specs = {
    'HAR_ABS':     ['rv1', 'rv5', 'rv22'],
    'HAR_VIX_L':   ['rv1', 'rv5', 'rv22', 'vix_L'],
    'HAR_VIX_dV':  ['rv1', 'rv5', 'rv22', 'dvix'],
    'HAR_VIX_P':   ['rv1', 'rv5', 'rv22', 'premium'],
    'HAR_VIX_T':   ['rv1', 'rv5', 'rv22', 'ma5_vix'],
    'HAR_VIX_All': ['rv1', 'rv5', 'rv22', 'vix_L', 'dvix', 'premium', 'ma5_vix'],
}

# ─── 7. Fit IS Models (OLS with HC3) and Generate OOS Forecasts ───────────────
def fit_model(is_df, feature_cols):
    """Fit OLS with HC3 robust SEs on IS sample."""
    X = sm.add_constant(is_df[feature_cols])
    y = is_df['y']
    model = sm.OLS(y, X).fit(cov_type='HC3')
    return model

def oos_forecast(model, oos_df, feature_cols):
    """Generate OOS forecasts using IS-fitted coefficients (static)."""
    X_oos = sm.add_constant(oos_df[feature_cols], has_constant='add')
    yhat = model.predict(X_oos)
    # Floor at EPS to avoid log(0) in QLIKE
    yhat = np.maximum(yhat, EPS)
    return yhat

def qlike_loss(y, yhat):
    """
    QLIKE Patton (2011) form B: log(yhat) + y/yhat
    (can be negative for small daily returns)
    """
    return np.log(yhat) + y / yhat

print("\n" + "=" * 60)
print("Fitting models and generating OOS forecasts...")
print("=" * 60)

is_r2    = {}
oos_preds = {}
is_models = {}

for model_name, features in model_specs.items():
    model = fit_model(is_data, features)
    is_r2[model_name]    = model.rsquared
    is_models[model_name] = model
    yhat = oos_forecast(model, oos_data, features)
    oos_preds[model_name] = yhat

    print(f"\n{model_name}:")
    print(f"  IS R²: {model.rsquared:.4f}  (n={len(is_data)})")
    print(f"  IS Coefficients (HC3):")
    for param, coef, pval in zip(model.params.index, model.params.values, model.pvalues.values):
        sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
        print(f"    {param:12s}: {coef:.6f}  (p={pval:.4f}) {sig}")

# ─── 8. OOS QLIKE Computation ─────────────────────────────────────────────────
print("\n" + "=" * 60)
print("OOS QLIKE Results (Patton 2011 Form B)")
print("=" * 60)

y_oos = oos_data['y'].values
oos_qlike = {}
loss_series = {}

for model_name, yhat in oos_preds.items():
    losses = qlike_loss(y_oos, yhat.values)
    loss_series[model_name] = losses
    oos_qlike[model_name] = losses.mean()

# Sort by QLIKE (lower = better)
sorted_models = sorted(oos_qlike.items(), key=lambda x: x[1])
print("\nOOS QLIKE Ranking (lower is better):")
print(f"{'Rank':<5} {'Model':<20} {'QLIKE':<12} {'vs HAR-ABS'}")
har_abs_qlike = oos_qlike['HAR_ABS']
for rank, (name, q) in enumerate(sorted_models, 1):
    diff = q - har_abs_qlike
    print(f"  {rank:<4} {name:<20} {q:.6f}   {diff:+.6f}")

# ─── 9. DM-HLN Test Function ─────────────────────────────────────────────────
def dm_hln_test(loss_a, loss_b, h=1):
    """
    Diebold-Mariano test with Harvey-Leybourne-Newbold (1997) finite-sample correction.
    H0: E[loss_a] = E[loss_b]
    Positive DM means model_a is WORSE than model_b (loss_a > loss_b).

    Uses Newey-West HAC variance with bandwidth = T^(1/3).
    HLN correction: multiply DM by sqrt((T+1-2h+h(h-1)/T)/T) then compare to t(T-1).

    Args:
        loss_a: losses from model_a (being tested)
        loss_b: losses from baseline model_b
        h: forecast horizon (1 for 1-step ahead)
    Returns:
        dm_stat: HLN-corrected t-statistic
        p_value: two-sided p-value from t(T-1) distribution
    """
    d = loss_a - loss_b
    T = len(d)

    # NW bandwidth = T^(1/3), rounded down
    bw = int(T ** (1/3))

    # Compute Newey-West variance of d
    d_demean = d - d.mean()
    nw_var = np.dot(d_demean, d_demean) / T
    for lag in range(1, bw + 1):
        cov_lag = np.dot(d_demean[lag:], d_demean[:-lag]) / T
        nw_var += 2 * (1 - lag / (bw + 1)) * cov_lag

    # SE of mean d
    se_d = np.sqrt(max(nw_var / T, 1e-20))

    # Raw DM statistic
    dm_raw = d.mean() / se_d

    # HLN finite-sample correction factor
    hln_factor = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    dm_stat = dm_raw * hln_factor

    # Two-sided p-value from t(T-1)
    p_value = 2 * t_dist.sf(abs(dm_stat), df=T - 1)

    return dm_stat, p_value

# ─── 10. DM Tests vs HAR-ABS Baseline ────────────────────────────────────────
print("\n" + "=" * 60)
print("DM-HLN Tests vs HAR-ABS Baseline")
print(f"Harvey threshold: |t| > {HARVEY_THRESHOLD}")
print("=" * 60)

dm_vs_baseline = {}
baseline_losses = loss_series['HAR_ABS']

for model_name in model_specs:
    if model_name == 'HAR_ABS':
        dm_vs_baseline[model_name] = {'dm_t': None, 'dm_p': None, 'harvey_pass': None}
        continue

    model_losses = loss_series[model_name]
    dm_t, dm_p = dm_hln_test(model_losses, baseline_losses)
    # Negative DM means model_name is BETTER than baseline (lower loss)
    harvey_pass = abs(dm_t) > HARVEY_THRESHOLD
    dm_vs_baseline[model_name] = {
        'dm_t': float(dm_t),
        'dm_p': float(dm_p),
        'harvey_pass': bool(harvey_pass)
    }
    better_worse = "BETTER" if dm_t < 0 else "WORSE"
    sig_marker = "***" if harvey_pass else "   "
    print(f"  {model_name:<20} vs HAR-ABS: DM t={dm_t:.3f}, p={dm_p:.4f} {sig_marker} ({better_worse})")

# ─── 11. Pairwise DM Tests vs HAR-VIX-L ──────────────────────────────────────
print("\n" + "=" * 60)
print("Pairwise DM-HLN Tests vs HAR-VIX-L")
print("(Tests whether each component adds beyond VIX level alone)")
print("=" * 60)

dm_vs_vix_l = {}
vix_l_losses = loss_series['HAR_VIX_L']

pairwise_candidates = ['HAR_VIX_dV', 'HAR_VIX_P', 'HAR_VIX_T', 'HAR_VIX_All']
for model_name in pairwise_candidates:
    model_losses = loss_series[model_name]
    dm_t, dm_p = dm_hln_test(model_losses, vix_l_losses)
    harvey_pass = abs(dm_t) > HARVEY_THRESHOLD
    dm_vs_vix_l[f"{model_name}_vs_L"] = {
        'dm_t': float(dm_t),
        'dm_p': float(dm_p),
        'harvey_pass': bool(harvey_pass)
    }
    better_worse = "BETTER than L" if dm_t < 0 else "WORSE than L"
    sig_marker = "***" if harvey_pass else "   "
    print(f"  {model_name:<20} vs HAR-VIX-L: DM t={dm_t:.3f}, p={dm_p:.4f} {sig_marker} ({better_worse})")

# ─── 12. VIF Check for HAR-VIX-All ───────────────────────────────────────────
print("\n" + "=" * 60)
print("VIF Check for HAR-VIX-All (Multicollinearity)")
print(f"Warning threshold: VIF > {VIF_THRESHOLD}")
print("=" * 60)

all_features = model_specs['HAR_VIX_All']
X_vif = sm.add_constant(is_data[all_features])
vif_results = {}
for i, col in enumerate(X_vif.columns[1:], 1):  # Skip const
    vif_val = variance_inflation_factor(X_vif.values, i)
    vif_results[col] = float(vif_val)
    flag = " *** HIGH VIF ***" if vif_val > VIF_THRESHOLD else ""
    print(f"  {col:<12}: VIF = {vif_val:.2f}{flag}")

# ─── 13. Hypothesis Verdicts ─────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Hypothesis Verdicts")
print("=" * 60)

# H1: VIX level (HAR-VIX-L) should be Harvey-significant vs baseline
h1_pass = dm_vs_baseline['HAR_VIX_L']['harvey_pass']
h1_verdict = "PASS" if h1_pass else "FAIL"
dm_h1 = dm_vs_baseline['HAR_VIX_L']['dm_t']
print(f"  H1 (VIX level significant): {h1_verdict}")
print(f"     HAR-VIX-L DM t={dm_h1:.3f} vs baseline, Harvey |t|>3: {h1_pass}")
if not h1_pass:
    print("     *** REPLICATION ANOMALY: K1315 reported DM t=4.58, cannot reproduce ***")
else:
    if abs(dm_h1 - 4.58) > 0.5:
        print(f"     NOTE: DM t={dm_h1:.3f} differs from K1315 t=4.58 (diff={abs(dm_h1)-4.58:.2f})")
        print(f"     Likely due to extended OOS period (K1315 OOS to 2024, K1399 to latest)")

# H2: DVIX (HAR-VIX-dV) carries incremental info beyond level
# Test vs HAR-ABS (absolute significance) AND vs HAR-VIX-L (incremental)
h2_abs_pass  = dm_vs_baseline['HAR_VIX_dV']['harvey_pass']
h2_incr_pass = dm_vs_vix_l['HAR_VIX_dV_vs_L']['harvey_pass']
h2_dm_abs  = dm_vs_baseline['HAR_VIX_dV']['dm_t']
h2_dm_incr = dm_vs_vix_l['HAR_VIX_dV_vs_L']['dm_t']
h2_verdict = "PASS" if h2_abs_pass else ("PARTIAL" if h2_incr_pass else "FAIL")
print(f"\n  H2 (DVIX incremental info): {h2_verdict}")
print(f"     vs baseline: DM t={h2_dm_abs:.3f}, Harvey pass: {h2_abs_pass}")
print(f"     vs VIX-L:    DM t={h2_dm_incr:.3f}, Harvey pass: {h2_incr_pass}")

# H3: Vol premium (HAR-VIX-P) carries regime information
h3_abs_pass  = dm_vs_baseline['HAR_VIX_P']['harvey_pass']
h3_incr_pass = dm_vs_vix_l['HAR_VIX_P_vs_L']['harvey_pass']
h3_dm_abs  = dm_vs_baseline['HAR_VIX_P']['dm_t']
h3_dm_incr = dm_vs_vix_l['HAR_VIX_P_vs_L']['dm_t']
h3_verdict = "PASS" if h3_abs_pass else ("PARTIAL" if h3_incr_pass else "FAIL")
print(f"\n  H3 (Vol premium regime info): {h3_verdict}")
print(f"     vs baseline: DM t={h3_dm_abs:.3f}, Harvey pass: {h3_abs_pass}")
print(f"     vs VIX-L:    DM t={h3_dm_incr:.3f}, Harvey pass: {h3_incr_pass}")

# H4: VIX trend (MA5) no additional info — PASS means null confirmed (NOT significant)
h4_abs_pass  = dm_vs_baseline['HAR_VIX_T']['harvey_pass']
h4_incr_pass = dm_vs_vix_l['HAR_VIX_T_vs_L']['harvey_pass']
h4_dm_abs  = dm_vs_baseline['HAR_VIX_T']['dm_t']
h4_dm_incr = dm_vs_vix_l['HAR_VIX_T_vs_L']['dm_t']
# H4 predicts null — "pass" means NOT Harvey-significant (confirming parsimony)
h4_verdict = "PASS" if (not h4_abs_pass and not h4_incr_pass) else "FAIL"
print(f"\n  H4 (VIX trend no extra info): {h4_verdict}")
print(f"     vs baseline: DM t={h4_dm_abs:.3f}, Harvey pass: {h4_abs_pass}")
print(f"     vs VIX-L:    DM t={h4_dm_incr:.3f}, Harvey pass: {h4_incr_pass}")
print(f"     (H4 PASS = trend NOT significant, confirming parsimony hypothesis)")

# H5: HAR-VIX-All not significantly better than best single-feature
# Fix (Codex CONDITIONAL_PASS issue): find best single-feature model by QLIKE,
# then run DM test HAR_VIX_All vs that best single (not always vs HAR_VIX_L).
best_single = min(
    [(n, oos_qlike[n]) for n in ['HAR_VIX_L', 'HAR_VIX_dV', 'HAR_VIX_P', 'HAR_VIX_T']],
    key=lambda x: x[1]
)
best_name = best_single[0]
best_qlike = best_single[1]
# Run DM test: HAR_VIX_All vs actual best single-feature model
h5_dm_t, h5_dm_p = dm_hln_test(loss_series['HAR_VIX_All'], loss_series[best_name])
h5_harvey_pass = abs(h5_dm_t) > HARVEY_THRESHOLD
# H5 predicts null — "PASS" means All NOT Harvey-significantly better than best single
h5_verdict = "PASS" if not h5_harvey_pass else "FAIL"
# Also store in dm_vs_vix_l for reference (if best is L, this is the same; if not, new test)
dm_vs_vix_l[f'HAR_VIX_All_vs_best_single'] = {
    'best_single_model': best_name,
    'dm_t': float(h5_dm_t),
    'dm_p': float(h5_dm_p),
    'harvey_pass': bool(h5_harvey_pass),
}
print(f"\n  H5 (Parsimony — All not better than best single): {h5_verdict}")
print(f"     Best single feature: {best_name} (QLIKE={best_qlike:.6f})")
print(f"     HAR_VIX_All vs {best_name}: DM t={h5_dm_t:.3f}, p={h5_dm_p:.4f}, Harvey pass: {h5_harvey_pass}")

# ─── 14. Chart ────────────────────────────────────────────────────────────────
print("\nGenerating QLIKE comparison chart...")
fig, ax = plt.subplots(figsize=(10, 6))
models_sorted = [m for m, _ in sorted_models]
qlikes_sorted = [oos_qlike[m] for m in models_sorted]
colors = ['#d62728' if m == 'HAR_ABS' else '#2196F3' if m == 'HAR_VIX_L'
          else '#4CAF50' if m == 'HAR_VIX_dV' else '#FF9800' if m == 'HAR_VIX_P'
          else '#9C27B0' if m == 'HAR_VIX_T' else '#795548'
          for m in models_sorted]
bars = ax.bar(range(len(models_sorted)), qlikes_sorted, color=colors, edgecolor='black', linewidth=0.5)
ax.set_xticks(range(len(models_sorted)))
ax.set_xticklabels([m.replace('_', '\n') for m in models_sorted], fontsize=9)
ax.set_ylabel('OOS QLIKE (Patton 2011 Form B)', fontsize=11)
ax.set_title('K1399: VIX Feature Decomposition — OOS QLIKE\n(lower = better; Harvey threshold |t|>3 for significance)', fontsize=12)
for bar, q in zip(bars, qlikes_sorted):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.0002,
            f'{q:.5f}', ha='center', va='bottom', fontsize=8)
ax.axhline(y=oos_qlike['HAR_ABS'], color='red', linestyle='--', linewidth=1, label='HAR-ABS baseline', alpha=0.7)
ax.legend(fontsize=9)
plt.tight_layout()
plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {CHART_PATH}")

# ─── 15. Compile Results JSON ─────────────────────────────────────────────────
verdict_str = "|".join([
    f"H1_{h1_verdict}",
    f"H2_{h2_verdict}",
    f"H3_{h3_verdict}",
    f"H4_{h4_verdict}",
    f"H5_{h5_verdict}",
])

# Build model entries
models_out = {}
for model_name in model_specs:
    entry = {
        'oos_qlike': float(oos_qlike[model_name]),
        'is_r2': float(is_r2[model_name]),
        'oos_rank': [m for m, _ in sorted_models].index(model_name) + 1,
    }
    if model_name != 'HAR_ABS':
        entry['dm_t_vs_baseline'] = dm_vs_baseline[model_name]['dm_t']
        entry['dm_p_vs_baseline'] = dm_vs_baseline[model_name]['dm_p']
        entry['harvey_pass_vs_baseline'] = dm_vs_baseline[model_name]['harvey_pass']
    else:
        entry['dm_t_vs_baseline'] = None
        entry['dm_p_vs_baseline'] = None
        entry['harvey_pass_vs_baseline'] = None
    models_out[model_name] = entry

results = {
    'experiment_id': 'K1399',
    'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
    'data_source': 'paper/leverage-direction/data/spy_vix_2004-2026.csv',
    'data_period': {
        'is_start': IS_START,
        'is_end': IS_END,
        'oos_start': OOS_START,
        'oos_end': str(oos_data.index[-1].date()),
    },
    'n_obs': {
        'is': int(len(is_data)),
        'oos': int(len(oos_data)),
    },
    'models': models_out,
    'pairwise_dm_vs_vix_l': dm_vs_vix_l,
    'vif_check': {'HAR_VIX_All': vif_results},
    'hypothesis_verdicts': {
        'H1_vix_level_significant': h1_verdict,
        'H2_dvix_incremental': h2_verdict,
        'H3_vol_premium_regime': h3_verdict,
        'H4_vix_trend_no_info': h4_verdict,
        'H5_parsimony_all_vs_best': h5_verdict,
    },
    'verdict': verdict_str,
    'qlike_ranking': [(m, float(q)) for m, q in sorted_models],
    'k1315_replication': {
        'expected_dm_t_vix_l_vs_baseline': 4.58,
        'actual_dm_t_vix_l_vs_baseline': float(abs(dm_vs_baseline['HAR_VIX_L']['dm_t'])),
        'replication_within_05': bool(abs(abs(dm_vs_baseline['HAR_VIX_L']['dm_t']) - 4.58) <= 0.5),
        'note': 'K1315 OOS 2019-2024; K1399 OOS 2019-latest. Difference expected.'
    },
    'summary': (
        f"K1399 VIX Feature Decomposition: "
        f"H1={h1_verdict} (VIX level DM t={dm_h1:.2f}), "
        f"H2={h2_verdict} (DVIX vs baseline DM t={h2_dm_abs:.2f}), "
        f"H3={h3_verdict} (vol premium DM t={h3_dm_abs:.2f}), "
        f"H4={h4_verdict} (trend insignificant, DM t={h4_dm_abs:.2f}), "
        f"H5={h5_verdict} (parsimony, All vs {best_name} DM t={h5_dm_t:.2f}). "
        f"Best model: {sorted_models[0][0]} (QLIKE={sorted_models[0][1]:.6f}). "
        f"QLIKE ranking: " + ", ".join([f"{m}={q:.6f}" for m, q in sorted_models])
    ),
    'seed': 42,
    'qlike_formula': 'Patton 2011 form B: mean(log(yhat) + y/yhat)',
    'dm_test': 'HLN-corrected DM, NW bandwidth=T^(1/3), t(T-1) distribution',
    'harvey_threshold': HARVEY_THRESHOLD,
}

with open(RESULTS_JSON, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to: {RESULTS_JSON}")

# ─── 16. Final Summary ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FINAL SUMMARY")
print("=" * 60)
print(f"\nVERDICT: {verdict_str}")
print(f"\nOOS QLIKE Ranking:")
for rank, (m, q) in enumerate(sorted_models, 1):
    dm_info = ""
    if m != 'HAR_ABS':
        dt = dm_vs_baseline[m]['dm_t']
        hp = dm_vs_baseline[m]['harvey_pass']
        dm_info = f"  | DM t={dt:.2f} vs baseline {'***' if hp else ''}"
    print(f"  {rank}. {m:<20} QLIKE={q:.6f}{dm_info}")

print(f"\nHypothesis Summary:")
print(f"  H1 (VIX level significant): {h1_verdict}")
print(f"  H2 (DVIX incremental info): {h2_verdict}")
print(f"  H3 (Vol premium regime):    {h3_verdict}")
print(f"  H4 (VIX trend no info):     {h4_verdict}")
print(f"  H5 (Parsimony principle):   {h5_verdict}")
print(f"\nVIF for HAR-VIX-All:")
for k, v in vif_results.items():
    flag = " HIGH" if v > VIF_THRESHOLD else ""
    print(f"  {k:<12}: {v:.2f}{flag}")

print("\nK1399 complete.")
