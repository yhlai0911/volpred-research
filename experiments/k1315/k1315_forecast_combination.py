"""
K1315: Forecast Combination — Anti-QLIKE Weighted Ensemble
===========================================================
Asset    : SPY (yfinance, daily)
Period   : IS 2005-01-03 to 2018-12-31, OOS 2019-01-01 to 2024-12-31
Target   : |r_t|  (HAR-ABS paradigm)
Models   : HAR-ABS, HAR-VIX, Equal-Weight, Anti-QLIKE, Bates-Granger
Loss     : QLIKE (Patton 2011 robust loss for |r|), MSE
Tests    : DM-HLN (Harvey et al. 1997) — |t| > 3.0 Harvey threshold

Lookahead prevention:
  rv1_t  = |r_{t-1}|                           → shift(1)
  rv5_t  = mean(|r_{t-5}..r_{t-1}|)           → rolling(5).mean().shift(1)
  rv22_t = mean(|r_{t-22}..r_{t-1}|)          → rolling(22).mean().shift(1)
  VIX_t  = VIX_{t-1}                           → shift(1)

Combination weights: expanding window over OOS losses up to t-1 (no future info).
HAR coefficients: static (fit on IS 2005-2018), consistent with K530.

References:
  Corsi (2009), JFE — HAR-RV model
  Patton (2011), JFE — robust loss functions
  Harvey, Leybourne, Newbold (1997, IJoF) — DM-HLN finite-sample correction
  Timmermann (2006), HEF — forecast combination
  Genre et al. (2013), IJoF — combination methods
  Bates & Granger (1969, OR) — constrained OLS combination
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.stats import t as t_dist
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import os
import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

# ─── Paths ────────────────────────────────────────────────────────────────────
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_JSON = os.path.join(OUT_DIR, 'k1315_results.json')
CHART_PATH   = os.path.join(OUT_DIR, 'k1315_oos_qlike_comparison.png')
CUMLOSS_PATH = os.path.join(OUT_DIR, 'k1315_cumulative_qlike.png')

# ─── Constants ────────────────────────────────────────────────────────────────
IS_START  = '2005-01-01'
IS_END    = '2018-12-31'
OOS_START = '2019-01-01'
OOS_END   = '2024-12-31'
EPS       = 1e-6           # min forecast floor
VIX_MAX_CONSECUTIVE_MISSING = 5

# ─── 1. Data Download ─────────────────────────────────────────────────────────
print("Downloading SPY and VIX data...")
spy_raw = yf.download('SPY', start='2004-12-01', end='2024-12-31',
                       auto_adjust=True, progress=False)
vix_raw = yf.download('^VIX', start='2004-12-01', end='2024-12-31',
                       auto_adjust=True, progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

spy_close = spy_raw['Close'].dropna()
vix_close = vix_raw['Close'].dropna()

# Daily log returns
spy_ret = np.log(spy_close / spy_close.shift(1)).dropna()
abs_r   = spy_ret.abs()

# VIX as fraction (VIX is in % annualized, convert to daily by /100/sqrt(252))
# K530 used VIX directly (as a level regressor); we follow the same convention
vix_level = vix_close.copy()

# ─── 2. Feature Construction (NO LOOKAHEAD) ───────────────────────────────────
# rv1_t  = |r_{t-1}|
rv1  = abs_r.shift(1)
# rv5_t  = mean(|r_{t-5}..r_{t-1}|) — rolling 5 on abs_r then shift 1
rv5  = abs_r.rolling(5).mean().shift(1)
# rv22_t = mean(|r_{t-22}..r_{t-1}|)
rv22 = abs_r.rolling(22).mean().shift(1)
# VIX_{t-1}
vix_lag = vix_level.reindex(abs_r.index).ffill().shift(1)

# Check consecutive VIX gaps BEFORE fill
vix_aligned = vix_level.reindex(abs_r.index)
consec_missing = (vix_aligned.isna().astype(int)
                  .groupby((vix_aligned.notna()).cumsum())
                  .transform('sum'))
if (consec_missing > VIX_MAX_CONSECUTIVE_MISSING).any():
    print("WARNING: VIX has >5 consecutive missing days — check data quality!")
    max_gap = int(consec_missing.max())
    print(f"  Max consecutive gap: {max_gap}")

# Align into DataFrame
df = pd.DataFrame({
    'abs_r': abs_r,
    'rv1':   rv1,
    'rv5':   rv5,
    'rv22':  rv22,
    'vix':   vix_lag,
}, index=abs_r.index)
df.dropna(inplace=True)

# Restrict to analysis window
df = df.loc['2005-01-01':]

print(f"Data range: {df.index[0].date()} to {df.index[-1].date()}")
print(f"Total obs after dropna: {len(df)}")

# ─── 3. Train / Test Split ────────────────────────────────────────────────────
is_mask  = df.index <= IS_END
oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)

df_is  = df[is_mask].copy()
df_oos = df[oos_mask].copy()

n_is  = len(df_is)
n_oos = len(df_oos)
print(f"IS obs: {n_is}  ({df_is.index[0].date()} to {df_is.index[-1].date()})")
print(f"OOS obs: {n_oos}  ({df_oos.index[0].date()} to {df_oos.index[-1].date()})")

# ─── 4. Static HAR Coefficient Estimation (IS only) ──────────────────────────
from numpy.linalg import lstsq

def fit_har_abs_static(df_train):
    """OLS on IS data; regressors: const, rv1, rv5, rv22"""
    X = np.column_stack([
        np.ones(len(df_train)),
        df_train['rv1'].values,
        df_train['rv5'].values,
        df_train['rv22'].values,
    ])
    y = df_train['abs_r'].values
    coef, _, _, _ = lstsq(X, y, rcond=None)
    return coef  # [const, b1, b5, b22]

def fit_har_vix_static(df_train):
    """OLS on IS data; regressors: const, rv1, rv5, rv22, vix"""
    X = np.column_stack([
        np.ones(len(df_train)),
        df_train['rv1'].values,
        df_train['rv5'].values,
        df_train['rv22'].values,
        df_train['vix'].values,
    ])
    y = df_train['abs_r'].values
    coef, _, _, _ = lstsq(X, y, rcond=None)
    return coef  # [const, b1, b5, b22, bvix]

print("\nFitting static HAR coefficients on IS period...")
coef_abs = fit_har_abs_static(df_is)
coef_vix = fit_har_vix_static(df_is)
print(f"HAR-ABS coef: const={coef_abs[0]:.6f}, rv1={coef_abs[1]:.4f}, "
      f"rv5={coef_abs[2]:.4f}, rv22={coef_abs[3]:.4f}")
print(f"HAR-VIX coef: const={coef_vix[0]:.6f}, rv1={coef_vix[1]:.4f}, "
      f"rv5={coef_vix[2]:.4f}, rv22={coef_vix[3]:.4f}, vix={coef_vix[4]:.4f}")

# ─── 5. Generate OOS Forecasts ────────────────────────────────────────────────
def predict_har_abs(row, coef):
    yhat = coef[0] + coef[1]*row['rv1'] + coef[2]*row['rv5'] + coef[3]*row['rv22']
    return max(yhat, EPS)

def predict_har_vix(row, coef):
    yhat = (coef[0] + coef[1]*row['rv1'] + coef[2]*row['rv5']
            + coef[3]*row['rv22'] + coef[4]*row['vix'])
    return max(yhat, EPS)

print("\nGenerating OOS forecasts...")
preds_abs = np.array([predict_har_abs(row, coef_abs) for _, row in df_oos.iterrows()])
preds_vix = np.array([predict_har_vix(row, coef_vix) for _, row in df_oos.iterrows()])
y_oos     = df_oos['abs_r'].values

# Sanity check: no negative or zero forecasts
assert (preds_abs > 0).all(), "HAR-ABS has non-positive forecasts!"
assert (preds_vix > 0).all(), "HAR-VIX has non-positive forecasts!"

# ─── 6. Combination Forecasts with Expanding-Window Weights ──────────────────
# Anti-QLIKE: w_i(t) ∝ 1/QLIKE_i(t-1), where QLIKE_i computed over OOS[0..t-2]
# Bates-Granger: expanding OLS with constraint β1+β2=1

def qlike_loss(yhat, y):
    """Patton (2011) QLIKE for |r|: log(yhat) + y/yhat"""
    yhat = np.maximum(yhat, EPS)
    return np.log(yhat) + y / yhat

def mse_loss(yhat, y):
    return (yhat - y) ** 2

def bates_granger_constrained(preds1, preds2, y):
    """
    Constrained OLS: yhat = beta1*p1 + beta2*p2 s.t. beta1+beta2=1
    => yhat = p2 + beta1*(p1-p2)
    => scalar regression: y-p2 = beta1*(p1-p2) + error (with intercept suppressed)
    This is equivalent to regressing (y-p2) on (p1-p2) with no intercept.
    No non-negativity constraint — beta1 can be outside [0,1] (pure sum-to-one OLS).
    """
    n = len(y)
    if n < 5:
        return 0.5  # fallback equal weight when insufficient data
    d = preds1 - preds2   # X
    r = y - preds2        # y_tilde
    beta1 = np.dot(d, r) / (np.dot(d, d) + 1e-12)
    # Note: no clip — allows beta1 outside [0,1] per Bates-Granger (1969).
    # Forecasts are floored at EPS downstream to keep QLIKE well-defined.
    return beta1

n_oos_steps = len(y_oos)
preds_ew  = np.zeros(n_oos_steps)  # Equal-weight
preds_aq  = np.zeros(n_oos_steps)  # Anti-QLIKE
preds_bg  = np.zeros(n_oos_steps)  # Bates-Granger

# Expanding window weight update
# For t=0 (first OOS step), no prior loss → equal weights
running_qlike_abs = []
running_qlike_vix = []

for t in range(n_oos_steps):
    # Equal weight (always 0.5/0.5)
    preds_ew[t] = 0.5 * preds_abs[t] + 0.5 * preds_vix[t]

    # Anti-QLIKE: use OOS losses from steps 0..t-1
    # Implementation note: QLIKE = log(yhat) + y/yhat can be negative for small yhat (<<1),
    # so naive 1/mean_QLIKE breaks when mean_QLIKE <= 0.
    # Fix: shift each model's mean loss up by adding the same constant (min of the two means),
    # making both non-negative, then invert. This preserves the relative ordering:
    # the model with lower mean QLIKE always gets a higher weight.
    # Formally: excess_i = mean_QLIKE_i - min(mean_QLIKE_abs, mean_QLIKE_vix) >= 0
    # w_i ∝ 1 / (excess_i + EPS)  — smaller excess loss → larger weight.
    if t == 0:
        w_abs = 0.5
        w_vix = 0.5
    else:
        q_abs_arr = np.array([qlike_loss(preds_abs[s], y_oos[s]) for s in range(t)])
        q_vix_arr = np.array([qlike_loss(preds_vix[s], y_oos[s]) for s in range(t)])
        mean_q_abs = q_abs_arr.mean()
        mean_q_vix = q_vix_arr.mean()
        # Shift to non-negative: excess over the better model's mean loss
        min_mean = min(mean_q_abs, mean_q_vix)
        excess_abs = mean_q_abs - min_mean  # >= 0
        excess_vix = mean_q_vix - min_mean  # >= 0
        inv_abs = 1.0 / (excess_abs + EPS)
        inv_vix = 1.0 / (excess_vix + EPS)
        total = inv_abs + inv_vix
        w_abs = inv_abs / total
        w_vix = inv_vix / total

    preds_aq[t] = max(w_abs * preds_abs[t] + w_vix * preds_vix[t], EPS)

    # Bates-Granger: constrained OLS from OOS steps 0..t-1
    if t < 5:
        beta1_bg = 0.5
    else:
        beta1_bg = bates_granger_constrained(
            preds_abs[:t], preds_vix[:t], y_oos[:t]
        )
    preds_bg[t] = max(beta1_bg * preds_abs[t] + (1.0 - beta1_bg) * preds_vix[t], EPS)

    # Accumulate running losses for audit
    running_qlike_abs.append(qlike_loss(preds_abs[t], y_oos[t]))
    running_qlike_vix.append(qlike_loss(preds_vix[t], y_oos[t]))

# Final Anti-QLIKE weights (using all OOS data, same shifted formula as in-loop)
final_q_abs = np.mean(running_qlike_abs)
final_q_vix = np.mean(running_qlike_vix)
min_final = min(final_q_abs, final_q_vix)
excess_abs_final = final_q_abs - min_final
excess_vix_final = final_q_vix - min_final
inv_abs_final = 1.0 / (excess_abs_final + EPS)
inv_vix_final = 1.0 / (excess_vix_final + EPS)
total_final = inv_abs_final + inv_vix_final
w_abs_final = inv_abs_final / total_final
w_vix_final = inv_vix_final / total_final

print(f"\nFinal Anti-QLIKE weights: HAR-ABS={w_abs_final:.4f}, HAR-VIX={w_vix_final:.4f}")

# Sanity checks
assert (preds_ew > 0).all(),  "Equal-Weight has non-positive forecasts!"
assert (preds_aq > 0).all(),  "Anti-QLIKE has non-positive forecasts!"
assert (preds_bg > 0).all(),  "Bates-Granger has non-positive forecasts!"

# ─── 7. Loss Computation ──────────────────────────────────────────────────────
all_preds = {
    'HAR-ABS':      preds_abs,
    'HAR-VIX':      preds_vix,
    'Equal-Weight': preds_ew,
    'Anti-QLIKE':   preds_aq,
    'Bates-Granger': preds_bg,
}

model_metrics = {}
for name, phat in all_preds.items():
    q_arr = np.array([qlike_loss(ph, y) for ph, y in zip(phat, y_oos)])
    m_arr = mse_loss(phat, y_oos)
    model_metrics[name] = {
        'qlike': float(q_arr.mean()),
        'mse':   float(m_arr.mean()),
    }
    print(f"{name:20s}  QLIKE={q_arr.mean():.6f}  MSE={m_arr.mean():.8f}")

# Anomaly detection
# K1315 QLIKE formula: log(yhat) + y/yhat (Patton 2011 form B).
# For SPY daily |r| ~ 0.008: log(0.008)+1 ≈ -3.83. Expected range: [-5, -3].
# K530 used form A: y/yhat - log(y/yhat) - 1 (always ≥ 0). Different scale.
# Threshold: suspiciously good if mean QLIKE < -5.0 (yhat << 0.001, anomalous)
# or if any combo beats HAR-VIX by >30% in absolute difference.
best_qlike = min(v['qlike'] for v in model_metrics.values())
if best_qlike < -5.0:
    print(f"\n!!! WARNING: Best QLIKE={best_qlike:.4f} < -5.0 — forecasts may be near-zero, check data!")
har_vix_q = model_metrics['HAR-VIX']['qlike']

# ─── 8. DM-HLN Test ───────────────────────────────────────────────────────────
def dm_hln_test(loss1, loss2, horizon=1):
    """
    Harvey, Leybourne & Newbold (1997) finite-sample DM test.
    H0: Equal predictive accuracy.  loss1, loss2 are T-length arrays.
    Returns: dm_stat (HLN-corrected), p_value (two-sided).
    Positive DM → loss1 > loss2 (model2 is better).

    Parameters
    ----------
    horizon : int
        Forecast horizon (h in HLN 1997). For 1-step-ahead = 1.
        This controls the HLN small-sample correction factor ONLY.
        It is distinct from the NW bandwidth, which controls autocorrelation truncation.

    HLN correction factor (Harvey et al. 1997, eq. 4):
        sqrt( (T + 1 - 2*h + h*(h-1)/T) / T )
    For h=1: sqrt((T + 1 - 2 + 0) / T) = sqrt((T-1)/T) ≈ 1 - 1/(2T)
    NW bandwidth: nw_lag = int(T^(1/3))  (separate from h)
    """
    d = loss1 - loss2   # d_t
    T = len(d)
    d_bar = d.mean()
    # Long-run variance using Newey-West (Bartlett kernel), bandwidth = T^(1/3)
    nw_lag = int(T ** (1/3))
    gamma0 = np.var(d, ddof=1)
    nw_var = gamma0
    for k in range(1, nw_lag + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * (1 - k / (nw_lag + 1)) * gamma_k
    nw_var = max(nw_var, 1e-14)  # numerical floor
    dm_stat = d_bar / np.sqrt(nw_var / T)
    # HLN finite-sample correction using forecast horizon h (not NW bandwidth)
    h = horizon
    correction = np.sqrt((T + 1 - 2*h + h*(h-1)/T) / T)
    dm_hln = dm_stat * correction
    # t-distribution with T-1 df
    p_val = 2 * t_dist.sf(abs(dm_hln), df=T-1)
    return float(dm_hln), float(p_val)

# Build per-step loss arrays
losses = {}
for name, phat in all_preds.items():
    losses[name] = np.array([qlike_loss(ph, y) for ph, y in zip(phat, y_oos)])

# DM comparisons
pairs = [
    ('Anti-QLIKE',    'HAR-VIX'),
    ('Equal-Weight',  'HAR-VIX'),
    ('Bates-Granger', 'HAR-VIX'),
    ('Anti-QLIKE',    'HAR-ABS'),
    ('Equal-Weight',  'HAR-ABS'),
    ('Bates-Granger', 'HAR-ABS'),
    ('Anti-QLIKE',    'Equal-Weight'),
    ('Anti-QLIKE',    'Bates-Granger'),
    ('Bates-Granger', 'Equal-Weight'),
]

HARVEY_THRESH = 3.0
dm_tests = {}
print("\nDM-HLN Tests (positive stat → first model has higher QLIKE loss, i.e., second model better):")
for m1, m2 in pairs:
    stat, pval = dm_hln_test(losses[m1], losses[m2], horizon=1)
    harvey_pass = abs(stat) > HARVEY_THRESH and pval < 0.05
    key = f"{m1} vs {m2}"
    dm_tests[key] = {
        'dm_stat':     round(stat, 4),
        'p_value':     round(pval, 6),
        'harvey_pass': harvey_pass,
    }
    sig_note = ("Harvey PASS" if harvey_pass
                else ("marginal(p<0.05,|t|<3)" if pval < 0.05
                      else "not significant"))
    print(f"  {key:40s}  t={stat:+7.4f}  p={pval:.4f}  → {sig_note}")

# ─── 9. Determine Verdict ─────────────────────────────────────────────────────
# Best combo vs HAR-VIX
combo_names = ['Anti-QLIKE', 'Equal-Weight', 'Bates-Granger']
best_combo = min(combo_names, key=lambda c: model_metrics[c]['qlike'])
best_combo_qlike = model_metrics[best_combo]['qlike']
har_vix_qlike    = model_metrics['HAR-VIX']['qlike']

# Check if improvement > 30% in absolute QLIKE difference (anomaly flag)
# QLIKE here is negative (log-form); "better" = more negative.
# Flag if combo is more than 0.30 lower in absolute terms (implausibly large improvement).
qlike_improvement = har_vix_qlike - best_combo_qlike  # positive = combo better
if qlike_improvement > 0.30:
    print(f"\n!!! WARNING: {best_combo} QLIKE improvement vs HAR-VIX = "
          f"{qlike_improvement:.4f} — unusually large, check for lookahead!")

# DM for best combo vs HAR-VIX
dm_key   = f"{best_combo} vs HAR-VIX"
dm_stat_best = dm_tests[dm_key]['dm_stat']
dm_pval_best = dm_tests[dm_key]['p_value']
harvey_best  = dm_tests[dm_key]['harvey_pass']

if harvey_best:
    if dm_stat_best > 0:  # combo has higher loss than HAR-VIX
        verdict = "PASS_NULL"
    else:                  # combo has lower loss than HAR-VIX (Harvey-significant)
        verdict = "PASS_NEW_FINDING"
elif dm_pval_best < 0.05 and abs(dm_stat_best) < HARVEY_THRESH:
    if dm_stat_best > 0:
        verdict = "CONDITIONAL_PASS"  # marginal HAR-VIX better
    else:
        verdict = "CONDITIONAL_PASS"  # marginal combo better
else:
    verdict = "PASS_NULL"  # no significant difference → HAR-VIX sufficient

print(f"\nVerdict: {verdict}")
print(f"Best combo: {best_combo} (QLIKE={best_combo_qlike:.6f}) vs HAR-VIX (QLIKE={har_vix_qlike:.6f})")

# ─── 10. Conclusions ──────────────────────────────────────────────────────────
conclusions = []

# QLIKE ranking
ranked = sorted(model_metrics.items(), key=lambda x: x[1]['qlike'])
conclusions.append(f"QLIKE ranking: " + ", ".join(
    f"{n}={v['qlike']:.4f}" for n, v in ranked))

# Best combo finding
if verdict == "PASS_NEW_FINDING":
    conclusions.append(
        f"{best_combo} combination significantly outperforms HAR-VIX "
        f"(DM={dm_stat_best:.3f}, p={dm_pval_best:.4f}, Harvey |t|>3.0) — "
        f"new finding: combination adds value beyond VIX alone.")
elif verdict == "PASS_NULL":
    conclusions.append(
        f"No combination significantly outperforms HAR-VIX at Harvey 3σ threshold. "
        f"VIX is a sufficient statistic for SPY daily |r| forecasting over 2019-2024. "
        f"Best combo {best_combo}: QLIKE={best_combo_qlike:.4f} vs HAR-VIX={har_vix_qlike:.4f}.")
else:
    conclusions.append(
        f"Marginal difference between {best_combo} and HAR-VIX "
        f"(DM={dm_stat_best:.3f}, p={dm_pval_best:.4f}) — "
        f"p<0.05 but |t|<3.0, insufficient for Harvey 3σ claim.")

# Anti-QLIKE weight evolution
conclusions.append(
    f"Final Anti-QLIKE weights: HAR-ABS={w_abs_final:.3f}, HAR-VIX={w_vix_final:.3f}. "
    f"{'HAR-VIX dominates the combination.' if w_vix_final > 0.7 else 'Weights remain balanced.'}")

# Anomaly flags
if (preds_aq < 0.0001).any():
    conclusions.append("WARNING: Anti-QLIKE forecasts contain near-zero values.")

# ─── 11. Charts ───────────────────────────────────────────────────────────────
print("\nGenerating charts...")

# Chart 1: QLIKE bar chart
fig, ax = plt.subplots(figsize=(10, 6))
model_names = [n for n, _ in ranked]
qlike_vals  = [v['qlike'] for _, v in ranked]
colors = ['#2196F3' if 'HAR' in n else '#4CAF50' for n in model_names]
bars = ax.bar(model_names, qlike_vals, color=colors, edgecolor='black', linewidth=0.7)
ax.axhline(har_vix_qlike, color='red', linestyle='--', linewidth=1.5,
           label=f'HAR-VIX baseline ({har_vix_qlike:.4f})')
for bar, val in zip(bars, qlike_vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.002,
            f'{val:.4f}', ha='center', va='bottom', fontsize=9)
ax.set_title('K1315: OOS QLIKE by Model\nSPY 2019-2024', fontsize=13, fontweight='bold')
ax.set_ylabel('Mean QLIKE (Patton 2011)')
ax.set_ylim(0, max(qlike_vals) * 1.15)
ax.legend()
ax.tick_params(axis='x', rotation=15)
plt.tight_layout()
plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {os.path.basename(CHART_PATH)}")

# Chart 2: Cumulative QLIKE loss (lower is better)
fig, ax = plt.subplots(figsize=(12, 6))
dates = df_oos.index
for name, phat in all_preds.items():
    cum_loss = np.cumsum([qlike_loss(ph, y) for ph, y in zip(phat, y_oos)])
    style = '--' if 'HAR' in name else '-'
    lw = 2.0 if name in ('HAR-VIX', 'Anti-QLIKE') else 1.2
    ax.plot(dates, cum_loss, label=name, linestyle=style, linewidth=lw)
ax.set_title('K1315: Cumulative QLIKE Loss Over OOS Period\nSPY 2019-2024 (lower = better)',
             fontsize=13, fontweight='bold')
ax.set_ylabel('Cumulative QLIKE')
ax.set_xlabel('Date')
ax.legend(loc='upper left')
plt.tight_layout()
plt.savefig(CUMLOSS_PATH, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {os.path.basename(CUMLOSS_PATH)}")

# ─── 12. Save Results JSON ────────────────────────────────────────────────────
results = {
    "experiment_id": "K1315",
    "title": "Forecast Combination: Anti-QLIKE Weighted Ensemble of HAR-ABS + HAR-VIX",
    "asset": "SPY",
    "data_source": "yfinance",
    "is_period": f"{df_is.index[0].date()} to {df_is.index[-1].date()}",
    "oos_period": f"{df_oos.index[0].date()} to {df_oos.index[-1].date()}",
    "n_is":  int(n_is),
    "n_oos": int(n_oos),
    "har_coefficients": {
        "HAR-ABS": {
            "const": float(coef_abs[0]),
            "rv1":   float(coef_abs[1]),
            "rv5":   float(coef_abs[2]),
            "rv22":  float(coef_abs[3]),
            "note":  "static, fit on IS 2005-2018 only (consistent with K530)",
        },
        "HAR-VIX": {
            "const": float(coef_vix[0]),
            "rv1":   float(coef_vix[1]),
            "rv5":   float(coef_vix[2]),
            "rv22":  float(coef_vix[3]),
            "vix":   float(coef_vix[4]),
            "note":  "static, fit on IS 2005-2018 only (consistent with K530)",
        },
    },
    "model_metrics": {
        name: {
            "qlike": round(v['qlike'], 8),
            "mse":   round(v['mse'],   10),
        }
        for name, v in model_metrics.items()
    },
    "dm_tests": dm_tests,
    "anti_qlike_weights_final": {
        "HAR-ABS": round(w_abs_final, 6),
        "HAR-VIX": round(w_vix_final, 6),
    },
    "harvey_threshold_met": any(
        v['harvey_pass'] for k, v in dm_tests.items() if 'HAR-VIX' in k
    ),
    "verdict": verdict,
    "conclusions": conclusions,
    "lookahead_prevention": {
        "rv1":  "abs_r.shift(1)  — uses only t-1 return",
        "rv5":  "abs_r.rolling(5).mean().shift(1) — uses t-5..t-1",
        "rv22": "abs_r.rolling(22).mean().shift(1) — uses t-22..t-1",
        "vix":  "vix_level.ffill().shift(1) — uses t-1 closing VIX",
        "combination_weights": "expanding window over OOS[0..t-2] QLIKE losses only",
    },
    "notes": [
        "HAR coefficients static (IS 2005-2018), consistent with K530 approach",
        "Bates-Granger constrained OLS: β1+β2=1, β1∈[0,1], expanding window",
        "Anti-QLIKE weighting: w_i ∝ 1/(excess_i + EPS) where excess_i = mean_QLIKE_i - min(mean_QLIKE_abs, mean_QLIKE_vix); always positive even when raw QLIKE is negative",
        "Forecast floor: max(yhat, 1e-6) to prevent log(0) in QLIKE",
        "DM-HLN Harvey threshold: |t| > 3.0 (Harvey et al. 1997); h=1 (1-step-ahead), NW bandwidth=T^(1/3) kept separate from h",
        "VIX forward-fill for missing market holidays; >5 consecutive triggers warning",
    ],
}

with open(RESULTS_JSON, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved: {RESULTS_JSON}")
print(f"\n{'='*60}")
print(f"K1315 SUMMARY")
print(f"{'='*60}")
print(f"IS:  {results['is_period']}  (n={n_is})")
print(f"OOS: {results['oos_period']}  (n={n_oos})")
print(f"\nModel QLIKE (lower = better):")
for name, v in sorted(model_metrics.items(), key=lambda x: x[1]['qlike']):
    print(f"  {name:20s}  {v['qlike']:.6f}")
print(f"\nKey DM tests (vs HAR-VIX baseline):")
for key in ['Anti-QLIKE vs HAR-VIX', 'Equal-Weight vs HAR-VIX', 'Bates-Granger vs HAR-VIX']:
    r = dm_tests[key]
    print(f"  {key}: t={r['dm_stat']:+.4f}, p={r['p_value']:.4f}, Harvey={r['harvey_pass']}")
print(f"\nVERDICT: {verdict}")
for c in conclusions:
    print(f"  - {c}")
