"""
K927: Macro Regime Detection — Can Macro Variables Predict VIX Regime Changes?

Research Question:
Can macroeconomic variables (yield curve, credit spread, financial conditions)
predict VIX regime transitions (calm → elevated volatility)?

Related: K278 (regime asymmetry), K259 (VIX absorbs macro), K504 (STLFSI4 null),
K526 (GARCH-MIDAS regime advantage), K752 (era-dependent R²), K856 (Fed null)

Data Sources:
- yfinance: ^VIX (daily)
- FRED: GS10, GS2, BAA10Y, NFCI, ICSA

References:
- Hamilton (1989) regime-switching
- Estrella & Mishkin (1998) yield curve as predictor
- Adrian, Boyarchenko & Giannone (2019) Vulnerable Growth
- Moreira & Muir (2017) Volatility-managed portfolios

Author: Yi-Hao Lai + VolPred Research System
"""

import numpy as np
np.random.seed(42)

import pandas as pd
import json
import warnings
import os
from datetime import datetime

warnings.filterwarnings('ignore')

# ── Step 1: Data Collection ──────────────────────────────────────────────

print("=" * 70)
print("K927: Macro Regime Detection — VIX Regime Prediction with Macro Variables")
print("=" * 70)

import yfinance as yf
import requests
import io

START = '2005-01-01'  # extra year for lag construction
END = '2026-03-31'
ANALYSIS_START = '2006-01-03'

# 1a. VIX
print("\n[1] Downloading VIX...")
vix_raw = yf.download('^VIX', start=START, end=END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw['Close'].copy()
vix.name = 'VIX'
vix.index = pd.to_datetime(vix.index).tz_localize(None)
print(f"  VIX: {len(vix)} obs, {vix.index[0].date()} to {vix.index[-1].date()}")
print(f"  VIX stats: mean={vix.mean():.2f}, std={vix.std():.2f}, min={vix.min():.2f}, max={vix.max():.2f}")

# 1b. FRED macro variables (direct CSV download, no API key needed)
print("\n[2] Downloading FRED macro variables...")

def fetch_fred_series(series_id, start_date, end_date):
    """Fetch FRED data directly via CSV download."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}&coed={end_date}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    s = pd.read_csv(io.StringIO(resp.text))
    # FRED CSV uses 'observation_date' as the date column
    date_col = [c for c in s.columns if 'date' in c.lower()][0]
    s[date_col] = pd.to_datetime(s[date_col])
    s = s.set_index(date_col)
    # Replace '.' with NaN (FRED uses '.' for missing)
    val_col = [c for c in s.columns if c != date_col][0]
    s[val_col] = pd.to_numeric(s[val_col], errors='coerce')
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s[val_col].dropna()

fred_series = {
    'GS10': 'GS10',       # 10-year Treasury rate
    'GS2': 'GS2',         # 2-year Treasury rate
    'BAA10Y': 'BAA10Y',   # BAA corporate - 10Y Treasury spread
    'NFCI': 'NFCI',       # Chicago Fed National Financial Conditions Index
    'ICSA': 'ICSA',       # Initial Jobless Claims
}

macro_data = {}
for name, code in fred_series.items():
    try:
        s = fetch_fred_series(code, START, END)
        macro_data[name] = s
        freq_days = s.index.to_series().diff().median().days
        print(f"  {name}: {len(s)} obs, freq ~{freq_days}d")
    except Exception as e:
        print(f"  {name}: FAILED ({e})")

# Construct term spread
if 'GS10' in macro_data and 'GS2' in macro_data:
    ts_df = pd.DataFrame({'GS10': macro_data['GS10'], 'GS2': macro_data['GS2']})
    ts_df = ts_df.dropna()
    macro_data['TERM_SPREAD'] = ts_df['GS10'] - ts_df['GS2']
    print(f"  TERM_SPREAD: {len(macro_data['TERM_SPREAD'])} obs (GS10 - GS2)")

# ── Step 2: Merge and Align ──────────────────────────────────────────────

print("\n[3] Building aligned daily dataset...")

# Create daily business-day index from VIX
df = pd.DataFrame({'VIX': vix})

# Forward-fill macro variables to daily
for name in ['TERM_SPREAD', 'BAA10Y', 'NFCI', 'ICSA']:
    if name in macro_data:
        df[name] = macro_data[name].reindex(df.index, method='ffill')

# Drop initial NaN period
df = df.loc[ANALYSIS_START:]
df = df.dropna()
print(f"  Aligned dataset: {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")
print(f"  Columns: {list(df.columns)}")

# ── Step 3: VIX Regime Classification ────────────────────────────────────

print("\n[4] VIX Regime Classification...")

def classify_regime(vix_val):
    if vix_val < 15:
        return 0  # calm
    elif vix_val < 25:
        return 1  # normal
    else:
        return 2  # high

df['regime'] = df['VIX'].apply(classify_regime)
regime_counts = df['regime'].value_counts().sort_index()
regime_pcts = regime_counts / len(df) * 100
print(f"  Regime 0 (calm, VIX<15):  {regime_counts.get(0, 0):5d} ({regime_pcts.get(0, 0):.1f}%)")
print(f"  Regime 1 (normal, 15-25): {regime_counts.get(1, 0):5d} ({regime_pcts.get(1, 0):.1f}%)")
print(f"  Regime 2 (high, VIX>25):  {regime_counts.get(2, 0):5d} ({regime_pcts.get(2, 0):.1f}%)")

# Regime transitions
df['regime_change'] = (df['regime'] != df['regime'].shift(1)).astype(int)
df['regime_up'] = ((df['regime'] > df['regime'].shift(1))).astype(int)
df['regime_down'] = ((df['regime'] < df['regime'].shift(1))).astype(int)

n_transitions = df['regime_change'].sum()
n_up = df['regime_up'].sum()
n_down = df['regime_down'].sum()
print(f"\n  Total transitions: {n_transitions}")
print(f"  Regime escalations (↑): {n_up}")
print(f"  Regime de-escalations (↓): {n_down}")

# Transition from calm (0) to normal/high (1/2) — the key prediction target
df['calm_to_trouble'] = ((df['regime'].shift(1) == 0) & (df['regime'] > 0)).astype(int)
n_calm_trouble = df['calm_to_trouble'].sum()
print(f"  Calm→Trouble transitions: {n_calm_trouble}")

# ── Step 4: Forward-Looking Regime Change Targets ─────────────────────

print("\n[5] Building forward-looking targets (h=5, 10, 22 days)...")

horizons = [5, 10, 22]
macro_vars = [c for c in ['TERM_SPREAD', 'BAA10Y', 'NFCI', 'ICSA'] if c in df.columns]
print(f"  Macro variables available: {macro_vars}")

# For each horizon h: did regime escalate at any point in next h days?
for h in horizons:
    # Future regime max in next h days
    future_regime_max = df['regime'].rolling(h).max().shift(-h)
    # Escalation: future max regime > current regime
    df[f'regime_up_h{h}'] = (future_regime_max > df['regime']).astype(float)
    # Also: any transition from calm to trouble
    calm_mask = df['regime'] == 0
    df[f'calm_trouble_h{h}'] = 0.0
    for i in range(1, h + 1):
        future_regime = df['regime'].shift(-i)
        df.loc[calm_mask & (future_regime > 0), f'calm_trouble_h{h}'] = 1.0

    n_esc = df[f'regime_up_h{h}'].sum()
    n_ct = df[f'calm_trouble_h{h}'].sum()
    print(f"  h={h:2d}: regime escalations={n_esc:.0f}, calm→trouble={n_ct:.0f}")

# ── Step 5: Descriptive Statistics ───────────────────────────────────────

print("\n[6] Descriptive Statistics of Macro Variables by Regime...")

desc_by_regime = {}
for regime in [0, 1, 2]:
    regime_data = df[df['regime'] == regime][macro_vars]
    desc_by_regime[regime] = {
        'mean': regime_data.mean().to_dict(),
        'std': regime_data.std().to_dict(),
        'n': len(regime_data)
    }
    regime_label = ['Calm', 'Normal', 'High'][regime]
    print(f"\n  Regime {regime} ({regime_label}, n={len(regime_data)}):")
    for var in macro_vars:
        print(f"    {var:15s}: mean={regime_data[var].mean():8.3f}, std={regime_data[var].std():8.3f}")

# ── Step 6: Granger Causality Tests ──────────────────────────────────────

print("\n[7] Granger Causality: Macro → VIX Regime...")

from statsmodels.tsa.stattools import grangercausalitytests

granger_results = {}
for var in macro_vars:
    test_df = df[['VIX', var]].dropna()
    try:
        gc = grangercausalitytests(test_df[['VIX', var]], maxlag=5, verbose=False)
        # Extract F-stat and p-value for each lag
        best_lag = min(gc.keys(), key=lambda k: gc[k][0]['ssr_ftest'][1])
        f_stat = gc[best_lag][0]['ssr_ftest'][0]
        p_val = gc[best_lag][0]['ssr_ftest'][1]
        granger_results[var] = {
            'best_lag': best_lag,
            'F_stat': round(f_stat, 3),
            'p_value': round(p_val, 6),
            'significant': p_val < 0.05
        }
        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
        print(f"  {var:15s}: best_lag={best_lag}, F={f_stat:.3f}, p={p_val:.6f} {sig}")
    except Exception as e:
        print(f"  {var:15s}: FAILED ({e})")
        granger_results[var] = {'error': str(e)}

# ── Step 7: Probit Model Estimation ──────────────────────────────────────

print("\n[8] Probit Model: Predicting Regime Escalation...")

from sklearn.metrics import roc_auc_score, precision_score, recall_score, brier_score_loss, classification_report
from sklearn.preprocessing import StandardScaler
import statsmodels.api as sm

# IS/OOS split
IS_END = '2018-12-31'
OOS_START = '2019-01-02'

df_is = df.loc[:IS_END].copy()
df_oos = df.loc[OOS_START:].copy()
print(f"  IS period: {df_is.index[0].date()} to {df_is.index[-1].date()} (n={len(df_is)})")
print(f"  OOS period: {df_oos.index[0].date()} to {df_oos.index[-1].date()} (n={len(df_oos)})")

# Standardize macro variables
scaler = StandardScaler()
X_is = scaler.fit_transform(df_is[macro_vars])
X_oos = scaler.transform(df_oos[macro_vars])

probit_results = {}

for h in horizons:
    target_col = f'regime_up_h{h}'
    print(f"\n  ─── Horizon h={h} days ───")

    # Clean IS data
    y_is = df_is[target_col].dropna()
    valid_is = y_is.index
    X_is_clean = pd.DataFrame(X_is, index=df_is.index, columns=macro_vars).loc[valid_is]

    # Clean OOS data
    y_oos = df_oos[target_col].dropna()
    valid_oos = y_oos.index
    X_oos_clean = pd.DataFrame(X_oos, index=df_oos.index, columns=macro_vars).loc[valid_oos]

    if len(y_is) < 100 or len(y_oos) < 50:
        print(f"    Insufficient data (IS={len(y_is)}, OOS={len(y_oos)}), skipping")
        continue

    # ── Model 1: Macro Only ──
    X_is_const = sm.add_constant(X_is_clean.values)
    X_oos_const = sm.add_constant(X_oos_clean.values)

    try:
        probit_macro = sm.Probit(y_is.values, X_is_const).fit(disp=0)

        # IS performance
        prob_is = probit_macro.predict(X_is_const)
        auc_is = roc_auc_score(y_is.values, prob_is)
        brier_is = brier_score_loss(y_is.values, prob_is)

        # OOS performance
        prob_oos = probit_macro.predict(X_oos_const)
        auc_oos = roc_auc_score(y_oos.values, prob_oos)
        brier_oos = brier_score_loss(y_oos.values, prob_oos)

        # Optimal threshold (Youden's J on IS)
        from sklearn.metrics import roc_curve
        fpr, tpr, thresholds = roc_curve(y_is.values, prob_is)
        j_scores = tpr - fpr
        best_thresh = thresholds[np.argmax(j_scores)]

        # OOS classification with best threshold
        pred_oos = (prob_oos >= best_thresh).astype(int)
        prec_oos = precision_score(y_oos.values, pred_oos, zero_division=0)
        rec_oos = recall_score(y_oos.values, pred_oos, zero_division=0)

        print(f"    Macro-only Probit:")
        print(f"      IS:  AUC={auc_is:.4f}, Brier={brier_is:.4f}")
        print(f"      OOS: AUC={auc_oos:.4f}, Brier={brier_oos:.4f}")
        print(f"      OOS: Precision={prec_oos:.4f}, Recall={rec_oos:.4f} (thresh={best_thresh:.3f})")

        # Coefficients
        coef_dict = {}
        coef_names = ['const'] + macro_vars
        for i, name in enumerate(coef_names):
            coef_dict[name] = {
                'coef': round(probit_macro.params[i], 4),
                'se': round(probit_macro.bse[i], 4),
                'z': round(probit_macro.tvalues[i], 4),
                'p': round(probit_macro.pvalues[i], 6)
            }
            sig = "***" if probit_macro.pvalues[i] < 0.001 else "**" if probit_macro.pvalues[i] < 0.01 else "*" if probit_macro.pvalues[i] < 0.05 else ""
            print(f"      {name:15s}: β={probit_macro.params[i]:7.4f}, z={probit_macro.tvalues[i]:7.3f} {sig}")

    except Exception as e:
        print(f"    Macro-only Probit FAILED: {e}")
        coef_dict = {}
        auc_oos = np.nan
        brier_oos = np.nan
        prec_oos = np.nan
        rec_oos = np.nan

    # ── Model 2: VIX Level Only (baseline) ──
    vix_is = df_is.loc[valid_is, 'VIX'].values.reshape(-1, 1)
    vix_oos = df_oos.loc[valid_oos, 'VIX'].values.reshape(-1, 1)

    vix_scaler = StandardScaler()
    vix_is_sc = vix_scaler.fit_transform(vix_is)
    vix_oos_sc = vix_scaler.transform(vix_oos)

    try:
        X_vix_is = sm.add_constant(vix_is_sc)
        X_vix_oos = sm.add_constant(vix_oos_sc)

        probit_vix = sm.Probit(y_is.values, X_vix_is).fit(disp=0)
        prob_vix_oos = probit_vix.predict(X_vix_oos)
        auc_vix_oos = roc_auc_score(y_oos.values, prob_vix_oos)
        brier_vix_oos = brier_score_loss(y_oos.values, prob_vix_oos)

        fpr_v, tpr_v, thresh_v = roc_curve(y_is.values, probit_vix.predict(X_vix_is))
        best_thresh_v = thresh_v[np.argmax(tpr_v - fpr_v)]
        pred_vix_oos = (prob_vix_oos >= best_thresh_v).astype(int)
        prec_vix_oos = precision_score(y_oos.values, pred_vix_oos, zero_division=0)
        rec_vix_oos = recall_score(y_oos.values, pred_vix_oos, zero_division=0)

        print(f"\n    VIX-only Probit (baseline):")
        print(f"      OOS: AUC={auc_vix_oos:.4f}, Brier={brier_vix_oos:.4f}")
        print(f"      OOS: Precision={prec_vix_oos:.4f}, Recall={rec_vix_oos:.4f}")

    except Exception as e:
        print(f"    VIX-only Probit FAILED: {e}")
        auc_vix_oos = np.nan
        brier_vix_oos = np.nan

    # ── Model 3: VIX + Macro (full) ──
    try:
        vix_is_full = scaler.fit_transform(
            df_is.loc[valid_is, macro_vars + ['VIX']].values
        ) if 'VIX' not in macro_vars else X_is_clean.values
        vix_oos_full = scaler.transform(
            df_oos.loc[valid_oos, macro_vars + ['VIX']].values
        ) if 'VIX' not in macro_vars else X_oos_clean.values

        # Rebuild with VIX included
        full_vars = macro_vars + ['VIX']
        scaler_full = StandardScaler()
        X_full_is = scaler_full.fit_transform(df_is.loc[valid_is, full_vars].values)
        X_full_oos = scaler_full.transform(df_oos.loc[valid_oos, full_vars].values)

        X_full_is_c = sm.add_constant(X_full_is)
        X_full_oos_c = sm.add_constant(X_full_oos)

        probit_full = sm.Probit(y_is.values, X_full_is_c).fit(disp=0)
        prob_full_oos = probit_full.predict(X_full_oos_c)
        auc_full_oos = roc_auc_score(y_oos.values, prob_full_oos)
        brier_full_oos = brier_score_loss(y_oos.values, prob_full_oos)

        fpr_f, tpr_f, thresh_f = roc_curve(y_is.values, probit_full.predict(X_full_is_c))
        best_thresh_f = thresh_f[np.argmax(tpr_f - fpr_f)]
        pred_full_oos = (prob_full_oos >= best_thresh_f).astype(int)
        prec_full_oos = precision_score(y_oos.values, pred_full_oos, zero_division=0)
        rec_full_oos = recall_score(y_oos.values, pred_full_oos, zero_division=0)

        print(f"\n    VIX+Macro Probit (full):")
        print(f"      OOS: AUC={auc_full_oos:.4f}, Brier={brier_full_oos:.4f}")
        print(f"      OOS: Precision={prec_full_oos:.4f}, Recall={rec_full_oos:.4f}")

        # Incremental AUC
        delta_auc = auc_full_oos - auc_vix_oos
        print(f"      Δ AUC (macro increment over VIX): {delta_auc:+.4f}")

        # Coefficients of full model
        full_coef_dict = {}
        full_names = ['const'] + full_vars
        for i, name in enumerate(full_names):
            full_coef_dict[name] = {
                'coef': round(probit_full.params[i], 4),
                'z': round(probit_full.tvalues[i], 4),
                'p': round(probit_full.pvalues[i], 6)
            }
            sig = "***" if probit_full.pvalues[i] < 0.001 else "**" if probit_full.pvalues[i] < 0.01 else "*" if probit_full.pvalues[i] < 0.05 else ""
            print(f"      {name:15s}: β={probit_full.params[i]:7.4f}, z={probit_full.tvalues[i]:7.3f} {sig}")

        # LR test: full vs VIX-only
        lr_stat = -2 * (probit_vix.llf - probit_full.llf)
        lr_df = len(macro_vars)
        from scipy import stats as sp_stats
        lr_pval = 1 - sp_stats.chi2.cdf(lr_stat, lr_df)
        print(f"\n    LR test (VIX+Macro vs VIX-only): χ²={lr_stat:.2f}, df={lr_df}, p={lr_pval:.6f}")

    except Exception as e:
        print(f"    VIX+Macro Probit FAILED: {e}")
        auc_full_oos = np.nan
        brier_full_oos = np.nan
        delta_auc = np.nan
        lr_stat = np.nan
        lr_pval = np.nan
        full_coef_dict = {}

    # ── Model 4: Naive baseline (constant probability) ──
    base_rate = y_is.mean()
    brier_naive = brier_score_loss(y_oos.values, np.full(len(y_oos), base_rate))
    print(f"\n    Naive baseline (constant p={base_rate:.3f}):")
    print(f"      OOS: Brier={brier_naive:.4f}")
    print(f"      AUC=0.5000 (by definition)")

    probit_results[f'h{h}'] = {
        'horizon': h,
        'n_is': int(len(y_is)),
        'n_oos': int(len(y_oos)),
        'base_rate_is': round(float(base_rate), 4),
        'base_rate_oos': round(float(y_oos.mean()), 4),
        'macro_only': {
            'AUC_oos': round(float(auc_oos), 4) if not np.isnan(auc_oos) else None,
            'Brier_oos': round(float(brier_oos), 4) if not np.isnan(brier_oos) else None,
            'Precision_oos': round(float(prec_oos), 4),
            'Recall_oos': round(float(rec_oos), 4),
            'coefficients': coef_dict
        },
        'vix_only': {
            'AUC_oos': round(float(auc_vix_oos), 4) if not np.isnan(auc_vix_oos) else None,
            'Brier_oos': round(float(brier_vix_oos), 4) if not np.isnan(brier_vix_oos) else None,
            'Precision_oos': round(float(prec_vix_oos), 4),
            'Recall_oos': round(float(rec_vix_oos), 4),
        },
        'vix_plus_macro': {
            'AUC_oos': round(float(auc_full_oos), 4) if not np.isnan(auc_full_oos) else None,
            'Brier_oos': round(float(brier_full_oos), 4) if not np.isnan(brier_full_oos) else None,
            'Precision_oos': round(float(prec_full_oos), 4),
            'Recall_oos': round(float(rec_full_oos), 4),
            'delta_AUC_vs_vix': round(float(delta_auc), 4) if not np.isnan(delta_auc) else None,
            'LR_test_chi2': round(float(lr_stat), 2) if not np.isnan(lr_stat) else None,
            'LR_test_pval': round(float(lr_pval), 6) if not np.isnan(lr_pval) else None,
            'coefficients': full_coef_dict
        },
        'naive_baseline': {
            'Brier_oos': round(float(brier_naive), 4)
        }
    }

# ── Step 8: Lead-Lag Analysis ────────────────────────────────────────────

print("\n\n[9] Lead-Lag Cross-Correlation: Macro(t) vs VIX_regime(t+lag)...")

lead_lag_results = {}
lags_to_test = list(range(-22, 23))  # -22 to +22 days

for var in macro_vars:
    corrs = []
    for lag in lags_to_test:
        if lag >= 0:
            # macro leads: macro(t) vs regime(t+lag)
            corr = df[var].corr(df['regime'].shift(-lag))
        else:
            # macro lags: macro(t) vs regime(t-|lag|) = regime(t+lag) for lag<0
            corr = df[var].corr(df['regime'].shift(-lag))
        corrs.append(corr)

    # Find peak correlation lag
    abs_corrs = [abs(c) if not np.isnan(c) else 0 for c in corrs]
    best_idx = np.argmax(abs_corrs)
    best_lag = lags_to_test[best_idx]
    best_corr = corrs[best_idx]

    lead_lag_results[var] = {
        'best_lag': int(best_lag),
        'best_corr': round(float(best_corr), 4),
        'interpretation': 'macro leads' if best_lag > 0 else 'concurrent' if best_lag == 0 else 'macro lags'
    }

    print(f"  {var:15s}: best_lag={best_lag:+3d}d, corr={best_corr:+.4f} "
          f"({'macro leads' if best_lag > 0 else 'concurrent' if best_lag == 0 else 'macro lags'})")

# ── Step 9: VIX Sufficiency Test ─────────────────────────────────────────

print("\n[10] VIX Sufficiency: Partial Correlations (Macro | VIX)...")

from scipy import stats as sp_stats

sufficiency_results = {}
for var in macro_vars:
    clean = df[['VIX', var, 'regime']].dropna()

    # Full correlation: macro vs regime
    r_full, p_full = sp_stats.spearmanr(clean[var], clean['regime'])

    # Partial correlation: macro vs regime | VIX
    # Using residual method
    from sklearn.linear_model import LinearRegression
    lr = LinearRegression()

    # Residualize macro on VIX
    lr.fit(clean[['VIX']], clean[var])
    resid_macro = clean[var] - lr.predict(clean[['VIX']])

    # Residualize regime on VIX
    lr.fit(clean[['VIX']], clean['regime'])
    resid_regime = clean['regime'] - lr.predict(clean[['VIX']])

    r_partial, p_partial = sp_stats.spearmanr(resid_macro, resid_regime)

    sufficiency_results[var] = {
        'r_full': round(float(r_full), 4),
        'p_full': round(float(p_full), 6),
        'r_partial_given_VIX': round(float(r_partial), 4),
        'p_partial': round(float(p_partial), 6),
        'vix_absorbs': abs(r_partial) < 0.05 or p_partial > 0.05
    }

    absorb = "VIX absorbs" if abs(r_partial) < 0.05 or p_partial > 0.05 else "incremental"
    print(f"  {var:15s}: r_full={r_full:+.4f} (p={p_full:.4f}), "
          f"r_partial|VIX={r_partial:+.4f} (p={p_partial:.4f}) → {absorb}")

# ── Step 10: Rolling Window Analysis ─────────────────────────────────────

print("\n[11] Rolling AUC: Macro Prediction Stability Over Time...")

window_size = 504  # ~2 years
step_size = 63     # ~3 months
rolling_auc_results = []

target_col = 'regime_up_h22'  # Use 1-month horizon
valid_df = df[[target_col] + macro_vars + ['VIX']].dropna()

for start_idx in range(0, len(valid_df) - window_size, step_size):
    window = valid_df.iloc[start_idx:start_idx + window_size]
    y_w = window[target_col]

    if y_w.nunique() < 2:  # skip if no variation
        continue

    X_w = window[macro_vars].values
    X_w_sc = StandardScaler().fit_transform(X_w)
    X_w_c = sm.add_constant(X_w_sc)

    try:
        m = sm.Probit(y_w.values, X_w_c).fit(disp=0)
        prob_w = m.predict(X_w_c)
        auc_w = roc_auc_score(y_w.values, prob_w)

        # VIX-only for comparison
        X_vix_w = StandardScaler().fit_transform(window[['VIX']].values)
        X_vix_w_c = sm.add_constant(X_vix_w)
        m_vix = sm.Probit(y_w.values, X_vix_w_c).fit(disp=0)
        prob_vix_w = m_vix.predict(X_vix_w_c)
        auc_vix_w = roc_auc_score(y_w.values, prob_vix_w)

        mid_date = window.index[len(window) // 2]
        rolling_auc_results.append({
            'date': mid_date.strftime('%Y-%m-%d'),
            'auc_macro': round(auc_w, 4),
            'auc_vix': round(auc_vix_w, 4),
            'delta': round(auc_w - auc_vix_w, 4)
        })
    except:
        pass

if rolling_auc_results:
    macro_wins = sum(1 for r in rolling_auc_results if r['delta'] > 0)
    total_windows = len(rolling_auc_results)
    avg_delta = np.mean([r['delta'] for r in rolling_auc_results])
    print(f"  Rolling windows: {total_windows}")
    print(f"  Macro > VIX: {macro_wins}/{total_windows} ({macro_wins/total_windows*100:.1f}%)")
    print(f"  Mean Δ AUC (macro - VIX): {avg_delta:+.4f}")

# ── Step 11: Charts ──────────────────────────────────────────────────────

print("\n[12] Generating charts...")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CHART_DIR = os.path.dirname(os.path.abspath(__file__))

# Chart 1: VIX Regime Timeline with Macro Overlays
fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)

# VIX with regime coloring
ax = axes[0]
ax.plot(df.index, df['VIX'], color='black', linewidth=0.5, alpha=0.8)
ax.axhline(15, color='green', linestyle='--', alpha=0.5, label='Calm/Normal boundary')
ax.axhline(25, color='red', linestyle='--', alpha=0.5, label='Normal/High boundary')
ax.fill_between(df.index, 0, df['VIX'], where=df['regime'] == 0, alpha=0.3, color='green', label='Calm')
ax.fill_between(df.index, 0, df['VIX'], where=df['regime'] == 1, alpha=0.3, color='orange', label='Normal')
ax.fill_between(df.index, 0, df['VIX'], where=df['regime'] == 2, alpha=0.3, color='red', label='High')
ax.set_ylabel('VIX')
ax.set_title('K927: VIX Regime Classification & Macro Variables', fontsize=14, fontweight='bold')
ax.legend(loc='upper right', fontsize=8)

# Term Spread
if 'TERM_SPREAD' in df.columns:
    ax = axes[1]
    ax.plot(df.index, df['TERM_SPREAD'], color='navy', linewidth=0.8)
    ax.axhline(0, color='red', linestyle='--', alpha=0.5)
    ax.set_ylabel('Term Spread\n(10Y-2Y)')
    ax.fill_between(df.index, df['TERM_SPREAD'], 0,
                    where=df['TERM_SPREAD'] < 0, alpha=0.3, color='red', label='Inverted')
    ax.legend(loc='upper right', fontsize=8)

# Credit Spread
if 'BAA10Y' in df.columns:
    ax = axes[2]
    ax.plot(df.index, df['BAA10Y'], color='darkred', linewidth=0.8)
    ax.set_ylabel('Credit Spread\n(BAA-10Y)')

# NFCI
if 'NFCI' in df.columns:
    ax = axes[3]
    ax.plot(df.index, df['NFCI'], color='purple', linewidth=0.8)
    ax.axhline(0, color='gray', linestyle='--', alpha=0.5)
    ax.set_ylabel('NFCI')
    ax.set_xlabel('Date')

plt.tight_layout()
chart1_path = os.path.join(CHART_DIR, 'k927_regime_transitions.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart1_path}")

# Chart 2: ROC Curves for OOS prediction
fig, axes = plt.subplots(1, 3, figsize=(15, 5))

for i, h in enumerate(horizons):
    ax = axes[i]
    target_col = f'regime_up_h{h}'

    try:
        # Re-fit scalers independently for chart
        y_is_h = df_is[target_col].dropna()
        valid_is_h = y_is_h.index
        y_oos_h = df_oos[target_col].dropna()
        valid_oos_h = y_oos_h.index

        # Macro-only scaler
        sc_macro = StandardScaler()
        X_m_is = sm.add_constant(sc_macro.fit_transform(df_is.loc[valid_is_h, macro_vars].values))
        X_m_oos = sm.add_constant(sc_macro.transform(df_oos.loc[valid_oos_h, macro_vars].values))
        m_macro = sm.Probit(y_is_h.values, X_m_is).fit(disp=0)
        prob_m = m_macro.predict(X_m_oos)
        fpr_m, tpr_m, _ = roc_curve(y_oos_h.values, prob_m)
        auc_m = roc_auc_score(y_oos_h.values, prob_m)

        # VIX-only scaler
        sc_vix = StandardScaler()
        X_v_is = sm.add_constant(sc_vix.fit_transform(df_is.loc[valid_is_h, ['VIX']].values))
        X_v_oos = sm.add_constant(sc_vix.transform(df_oos.loc[valid_oos_h, ['VIX']].values))
        m_vix = sm.Probit(y_is_h.values, X_v_is).fit(disp=0)
        prob_v = m_vix.predict(X_v_oos)
        fpr_v, tpr_v, _ = roc_curve(y_oos_h.values, prob_v)
        auc_v = roc_auc_score(y_oos_h.values, prob_v)

        # Full (VIX+Macro) scaler
        full_vars = macro_vars + ['VIX']
        sc_full = StandardScaler()
        X_f_is = sm.add_constant(sc_full.fit_transform(df_is.loc[valid_is_h, full_vars].values))
        X_f_oos = sm.add_constant(sc_full.transform(df_oos.loc[valid_oos_h, full_vars].values))
        m_full = sm.Probit(y_is_h.values, X_f_is).fit(disp=0)
        prob_f = m_full.predict(X_f_oos)
        fpr_f, tpr_f, _ = roc_curve(y_oos_h.values, prob_f)
        auc_f = roc_auc_score(y_oos_h.values, prob_f)

        ax.plot(fpr_m, tpr_m, 'b-', label=f'Macro only (AUC={auc_m:.3f})')
        ax.plot(fpr_v, tpr_v, 'r-', label=f'VIX only (AUC={auc_v:.3f})')
        ax.plot(fpr_f, tpr_f, 'g-', label=f'VIX+Macro (AUC={auc_f:.3f})')
        ax.plot([0, 1], [0, 1], 'k--', alpha=0.3)

    except Exception as e:
        ax.text(0.5, 0.5, f'Error: {str(e)[:50]}', ha='center', va='center', transform=ax.transAxes)

    ax.set_xlabel('False Positive Rate')
    ax.set_ylabel('True Positive Rate')
    ax.set_title(f'h = {h} days')
    ax.legend(fontsize=8, loc='lower right')

plt.suptitle('K927: OOS ROC Curves — Regime Escalation Prediction', fontsize=14, fontweight='bold')
plt.tight_layout()
chart2_path = os.path.join(CHART_DIR, 'k927_prediction_roc.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart2_path}")

# ── Step 12: Summary & Conclusions ───────────────────────────────────────

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Key findings
print("\n[A] Macro Variable Predictive Power (OOS AUC):")
for h in horizons:
    key = f'h{h}'
    if key in probit_results:
        r = probit_results[key]
        auc_m = r['macro_only']['AUC_oos']
        auc_v = r['vix_only']['AUC_oos']
        auc_f = r['vix_plus_macro']['AUC_oos']
        delta = r['vix_plus_macro']['delta_AUC_vs_vix']
        print(f"  h={h:2d}d: Macro={auc_m}, VIX={auc_v}, VIX+Macro={auc_f}, Δ={delta:+.4f}")

print("\n[B] VIX Sufficiency (Partial Correlations):")
for var, r in sufficiency_results.items():
    print(f"  {var:15s}: r_partial|VIX = {r['r_partial_given_VIX']:+.4f} → {'VIX absorbs' if r['vix_absorbs'] else 'INCREMENTAL'}")

print("\n[C] Lead-Lag Analysis:")
for var, r in lead_lag_results.items():
    print(f"  {var:15s}: best_lag={r['best_lag']:+3d}d → {r['interpretation']}")

print("\n[D] Granger Causality (Macro → VIX):")
for var, r in granger_results.items():
    if 'F_stat' in r:
        sig_text = "SIGNIFICANT" if r['significant'] else "not significant"
        print(f"  {var:15s}: F={r['F_stat']:.3f}, p={r['p_value']:.6f} → {sig_text}")

# Overall conclusion
print("\n" + "-" * 70)
print("CONCLUSION:")

# Determine if macro adds value
macro_adds = False
for h in horizons:
    key = f'h{h}'
    if key in probit_results:
        delta = probit_results[key]['vix_plus_macro'].get('delta_AUC_vs_vix')
        if delta is not None and delta > 0.02:
            macro_adds = True
            break

all_absorbed = all(r.get('vix_absorbs', True) for r in sufficiency_results.values())

if not macro_adds and all_absorbed:
    conclusion = ("NULL RESULT: Macro variables do NOT meaningfully predict VIX regime "
                  "transitions beyond what VIX level itself provides. VIX sufficiency "
                  "confirmed again (consistent with K259, K504). Macro variables are "
                  "either concurrent with or lag VIX regime changes.")
elif macro_adds:
    conclusion = ("POSITIVE: Macro variables provide incremental predictive power for "
                  "VIX regime transitions beyond VIX level alone.")
else:
    conclusion = ("MIXED: Some macro variables show statistical significance but limited "
                  "practical incremental value over VIX alone.")

print(f"  {conclusion}")
print("-" * 70)

# ── Step 13: Save Results JSON ───────────────────────────────────────────

results = {
    'experiment_id': 'K927',
    'title': 'Macro Regime Detection — VIX Regime Prediction with Macro Variables',
    'timestamp': datetime.utcnow().isoformat(),
    'data_sources': {
        'VIX': 'yfinance (^VIX)',
        'macro': 'FRED (GS10, GS2, BAA10Y, NFCI, ICSA)',
    },
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': int(len(df)),
    'regime_distribution': {
        'calm_pct': round(float(regime_pcts.get(0, 0)), 1),
        'normal_pct': round(float(regime_pcts.get(1, 0)), 1),
        'high_pct': round(float(regime_pcts.get(2, 0)), 1),
    },
    'transitions': {
        'total': int(n_transitions),
        'escalations': int(n_up),
        'de_escalations': int(n_down),
        'calm_to_trouble': int(n_calm_trouble),
    },
    'descriptive_stats_by_regime': desc_by_regime,
    'granger_causality': granger_results,
    'probit_models': probit_results,
    'lead_lag_analysis': lead_lag_results,
    'vix_sufficiency': sufficiency_results,
    'rolling_auc': {
        'n_windows': len(rolling_auc_results) if rolling_auc_results else 0,
        'macro_wins_pct': round(macro_wins / total_windows * 100, 1) if rolling_auc_results else None,
        'mean_delta_auc': round(float(avg_delta), 4) if rolling_auc_results else None,
    },
    'conclusion': conclusion,
    'references': [
        'Hamilton (1989) A New Approach to Economic Analysis of Nonstationary Time Series, Econometrica',
        'Estrella & Mishkin (1998) Predicting U.S. Recessions, REStat',
        'Adrian, Boyarchenko & Giannone (2019) Vulnerable Growth, AER',
        'Moreira & Muir (2017) Volatility-Managed Portfolios, JF',
    ],
    'charts': ['k927_regime_transitions.png', 'k927_prediction_roc.png'],
}

results_path = os.path.join(CHART_DIR, 'k927_macro_regime_vix_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved: {results_path}")

print("\n✓ K927 complete.")
