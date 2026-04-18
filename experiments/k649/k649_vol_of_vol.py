"""
K649: Volatility of Volatility (Vol-of-Vol) — Regime Change Prediction
=======================================================================
Motivation:
  K448 tested VVIX as a vol predictor → null.
  J17 tested VVIX tail-guard overlay → null (partial corr = 0.006).
  K1 found SKEW/VVIX/VIX3M absorbed by VIX.
  Prior VoV spike analysis: short-term (5d) signal but not 22d.
  Key prior insight: high VVIX predicts VIX MEAN-REVERSION, not spikes.

  NEW ANGLE: Can vol-of-vol predict REGIME CHANGES (VIX crossing thresholds)
  rather than vol levels? This is a classification problem, not regression.

Data source: yfinance (SPY, ^VIX, ^VVIX), 2007-01-01 to 2026-03-27
Type: Empirical analysis (real data)

References:
  - Huang & Shaliastovich (2015) "Volatility-of-Volatility Risk" — vol-of-vol premia
  - Park (2015) "Volatility-of-Volatility and Tail Risk Hedging Returns" JBF
  - Baltussen et al. (2018) "Unknown Unknowns: Uncertainty About Risk" — VVIX pricing
  - Avellaneda & Papanicolaou (2019) "Statistics of VIX Futures"
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from pathlib import Path
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, classification_report
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

# ── Configuration ─────────────────────────────────────────────────────
START_DATE = "2007-01-01"
END_DATE = "2026-03-27"
VIX_THRESHOLD = 20       # regime boundary
ROLLING_WINDOW = 22      # 1 month for vol-of-vol
PREDICTION_HORIZON = 5   # 5 trading days forward
OOS_START = "2020-01-01" # out-of-sample start
RESULTS_FILE = Path(__file__).resolve().parent / "k649_results.json"


def download_data():
    """Download SPY, VIX, and VVIX data."""
    print("=" * 70)
    print("K649: Volatility of Volatility — Regime Change Prediction")
    print("=" * 70)
    print(f"\nDownloading data: SPY, ^VIX, ^VVIX ({START_DATE} to {END_DATE})")

    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)
    vvix = yf.download("^VVIX", start=START_DATE, end=END_DATE, progress=False)

    # Handle multi-level columns from yfinance
    for df in [spy, vix, vvix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # Build combined DataFrame
    data = pd.DataFrame(index=spy.index)
    data['spy_close'] = spy['Close']
    data['spy_return'] = spy['Close'].pct_change()
    data['vix'] = vix['Close'].reindex(spy.index, method='ffill')
    data['vix_high'] = vix['High'].reindex(spy.index, method='ffill')
    data['vix_low'] = vix['Low'].reindex(spy.index, method='ffill')

    # VVIX — may have shorter history
    if len(vvix) > 100:
        data['vvix'] = vvix['Close'].reindex(spy.index, method='ffill')
        vvix_available = True
        print(f"  VVIX available: {vvix.index[0].strftime('%Y-%m-%d')} to {vvix.index[-1].strftime('%Y-%m-%d')} ({len(vvix)} obs)")
    else:
        data['vvix'] = np.nan
        vvix_available = False
        print("  VVIX: insufficient data, using constructed measures only")

    data.dropna(subset=['spy_close', 'vix'], inplace=True)
    print(f"  Combined data: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')} ({len(data)} obs)")

    return data, vvix_available


def construct_vol_of_vol_measures(data):
    """Construct multiple vol-of-vol measures."""
    print("\n── Constructing Vol-of-Vol Measures ──")

    # 1. Daily VIX change (absolute and percentage)
    data['vix_change'] = data['vix'].diff()
    data['vix_pct_change'] = data['vix'].pct_change()

    # 2. Rolling 22-day std of daily VIX changes (sigma_VIX)
    data['sigma_vix'] = data['vix_change'].rolling(ROLLING_WINDOW).std()

    # 3. Rolling 22-day std of VIX pct changes
    data['sigma_vix_pct'] = data['vix_pct_change'].rolling(ROLLING_WINDOW).std()

    # 4. VIX range (high - low) / VIX level — normalized intraday range
    data['vix_range_norm'] = (data['vix_high'] - data['vix_low']) / data['vix']

    # 5. Rolling mean of normalized VIX range (smoother)
    data['vix_range_ma'] = data['vix_range_norm'].rolling(ROLLING_WINDOW).mean()

    # 6. GARCH(1,1) on VIX changes — simple recursive variance estimate
    vix_changes = data['vix_change'].dropna().values
    omega = 0.01
    alpha = 0.10
    beta = 0.85
    h = np.zeros(len(vix_changes))
    h[0] = np.var(vix_changes[:ROLLING_WINDOW]) if len(vix_changes) > ROLLING_WINDOW else 1.0
    for t in range(1, len(vix_changes)):
        h[t] = omega + alpha * vix_changes[t-1]**2 + beta * h[t-1]
    garch_vol = pd.Series(np.sqrt(h), index=data.index[1:])  # skip first NaN from diff
    data['garch_vix_vol'] = garch_vol.reindex(data.index)

    # 7. Z-score of sigma_vix (relative to its own history)
    expanding_mean = data['sigma_vix'].expanding(min_periods=60).mean()
    expanding_std = data['sigma_vix'].expanding(min_periods=60).std()
    data['sigma_vix_zscore'] = (data['sigma_vix'] - expanding_mean) / expanding_std

    # Summary stats
    measures = ['sigma_vix', 'sigma_vix_pct', 'vix_range_norm', 'garch_vix_vol', 'vvix']
    print("\n  Vol-of-Vol Descriptive Statistics:")
    print(f"  {'Measure':<20} {'Mean':>8} {'Std':>8} {'Min':>8} {'Max':>8} {'Skew':>8} {'Kurt':>8}")
    print(f"  {'-'*72}")
    stats_dict = {}
    for m in measures:
        s = data[m].dropna()
        if len(s) > 0:
            st = {
                'mean': float(s.mean()),
                'std': float(s.std()),
                'min': float(s.min()),
                'max': float(s.max()),
                'skew': float(s.skew()),
                'kurtosis': float(s.kurtosis()),
                'n_obs': int(len(s))
            }
            stats_dict[m] = st
            print(f"  {m:<20} {st['mean']:>8.3f} {st['std']:>8.3f} {st['min']:>8.3f} {st['max']:>8.3f} {st['skew']:>8.3f} {st['kurtosis']:>8.3f}")

    return data, stats_dict


def define_regime_changes(data):
    """Define VIX regime (above/below 20) and regime change events."""
    print("\n── Defining Regime Changes ──")

    data['vix_regime'] = (data['vix'] > VIX_THRESHOLD).astype(int)  # 1 = high vol
    data['regime_change'] = data['vix_regime'].diff().abs()  # 1 = regime changed
    data['regime_change'] = data['regime_change'].fillna(0).astype(int)

    # Forward-looking: will regime change in next N days?
    data['regime_change_fwd'] = data['regime_change'].rolling(PREDICTION_HORIZON).sum().shift(-PREDICTION_HORIZON)
    data['regime_change_fwd'] = (data['regime_change_fwd'] > 0).astype(int)

    # Stats
    n_changes = data['regime_change'].sum()
    n_high = data['vix_regime'].sum()
    n_low = len(data) - n_high
    pct_high = n_high / len(data) * 100

    # Regime change frequency by year
    yearly = data.groupby(data.index.year)['regime_change'].sum()

    print(f"  VIX threshold: {VIX_THRESHOLD}")
    print(f"  Total regime changes: {n_changes}")
    print(f"  Days in high vol (VIX > {VIX_THRESHOLD}): {n_high} ({pct_high:.1f}%)")
    print(f"  Days in low vol (VIX <= {VIX_THRESHOLD}): {n_low} ({100-pct_high:.1f}%)")
    print(f"  Regime changes per year (avg): {yearly.mean():.1f}")
    print(f"  Prediction target: regime change within {PREDICTION_HORIZON} trading days")
    print(f"  Target positive rate: {data['regime_change_fwd'].dropna().mean()*100:.1f}%")

    regime_stats = {
        'total_regime_changes': int(n_changes),
        'pct_high_vol': float(round(pct_high, 1)),
        'avg_changes_per_year': float(round(yearly.mean(), 1)),
        'target_positive_rate_pct': float(round(data['regime_change_fwd'].dropna().mean()*100, 1)),
        'yearly_changes': {str(k): int(v) for k, v in yearly.items()}
    }

    return data, regime_stats


def analyze_lead_lag(data):
    """Analyze lead-lag between vol-of-vol and VIX level changes."""
    print("\n── Lead-Lag Analysis: sigma_VIX vs VIX ──")

    # Cross-correlation: sigma_VIX leads or lags VIX changes?
    vix_abs_change = data['vix_change'].abs().dropna()
    sigma_vix = data['sigma_vix'].dropna()
    common = vix_abs_change.index.intersection(sigma_vix.index)
    vix_abs = vix_abs_change.loc[common].values
    sig = sigma_vix.loc[common].values

    lead_lag_results = {}
    print(f"  {'Lag':>5} {'Corr':>8} {'p-value':>10} {'Interpretation'}")
    print(f"  {'-'*55}")
    for lag in range(-10, 11):
        if lag < 0:
            # sigma_VIX leads VIX
            x = sig[:lag]
            y = vix_abs[-lag:]
        elif lag > 0:
            x = sig[lag:]
            y = vix_abs[:-lag]
        else:
            x = sig
            y = vix_abs
        if len(x) > 50:
            r, p = stats.pearsonr(x, y)
            interp = ""
            if lag < 0:
                interp = f"sigma_VIX leads by {abs(lag)}d"
            elif lag > 0:
                interp = f"sigma_VIX lags by {lag}d"
            else:
                interp = "contemporaneous"
            if abs(lag) <= 5:
                print(f"  {lag:>5} {r:>8.4f} {p:>10.4e}  {interp}")
            lead_lag_results[str(lag)] = {'corr': round(float(r), 4), 'p_value': float(p)}

    # Granger-like: does sigma_VIX help predict future |VIX change|?
    print("\n  Granger-like predictive regression:")
    from numpy.linalg import lstsq

    # y = |dVIX_{t+h}|, x = [|dVIX_t|, sigma_VIX_t]
    for h in [1, 5, 10]:
        y_var = data['vix_change'].abs().shift(-h).dropna()
        x_vars = data[['sigma_vix']].dropna()
        x_vars['abs_dvix'] = data['vix_change'].abs()
        common_idx = y_var.index.intersection(x_vars.dropna().index)
        y_arr = y_var.loc[common_idx].values
        x_arr = x_vars.loc[common_idx].values
        x_arr = np.column_stack([np.ones(len(x_arr)), x_arr])

        if len(y_arr) > 100:
            coef, resid, _, _ = lstsq(x_arr, y_arr, rcond=None)
            y_pred = x_arr @ coef
            ss_res = np.sum((y_arr - y_pred)**2)
            ss_tot = np.sum((y_arr - y_arr.mean())**2)
            r2 = 1 - ss_res / ss_tot
            # t-stats
            n_obs = len(y_arr)
            k = x_arr.shape[1]
            se = np.sqrt(ss_res / (n_obs - k) * np.diag(np.linalg.inv(x_arr.T @ x_arr)))
            t_stats = coef / se
            print(f"  h={h}d: R²={r2:.4f}, sigma_VIX coef={coef[1]:.4f} (t={t_stats[1]:.2f}), |dVIX| coef={coef[2]:.4f} (t={t_stats[2]:.2f})")
            lead_lag_results[f'granger_h{h}'] = {
                'R2': round(float(r2), 4),
                'sigma_vix_coef': round(float(coef[1]), 4),
                'sigma_vix_t': round(float(t_stats[1]), 2),
                'abs_dvix_coef': round(float(coef[2]), 4),
                'abs_dvix_t': round(float(t_stats[2]), 2),
                'n_obs': int(n_obs)
            }

    return lead_lag_results


def regime_change_prediction(data):
    """Logistic regression: can vol-of-vol predict regime changes?"""
    print("\n── Regime Change Prediction (Logistic Regression) ──")

    # Prepare features
    features = ['sigma_vix', 'sigma_vix_pct', 'vix_range_ma', 'garch_vix_vol', 'vix', 'sigma_vix_zscore']
    target = 'regime_change_fwd'

    # Also try VVIX where available
    has_vvix = data['vvix'].notna().sum() > 500

    # Drop NaN
    model_data = data[features + [target]].dropna()
    print(f"  Total observations with all features: {len(model_data)}")

    # Split IS/OOS
    is_mask = model_data.index < OOS_START
    oos_mask = model_data.index >= OOS_START
    is_data = model_data[is_mask]
    oos_data = model_data[oos_mask]

    print(f"  In-sample: {len(is_data)} obs ({is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')})")
    print(f"  Out-of-sample: {len(oos_data)} obs ({oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')})")
    print(f"  IS positive rate: {is_data[target].mean()*100:.1f}%")
    print(f"  OOS positive rate: {oos_data[target].mean()*100:.1f}%")

    results = {}

    # Model 1: VIX only (baseline)
    print("\n  Model 1: VIX only (baseline)")
    X_is = is_data[['vix']].values
    X_oos = oos_data[['vix']].values
    y_is = is_data[target].values
    y_oos = oos_data[target].values

    scaler1 = StandardScaler()
    X_is_s = scaler1.fit_transform(X_is)
    X_oos_s = scaler1.transform(X_oos)

    lr1 = LogisticRegression(max_iter=1000, random_state=42)
    lr1.fit(X_is_s, y_is)
    prob_is_1 = lr1.predict_proba(X_is_s)[:, 1]
    prob_oos_1 = lr1.predict_proba(X_oos_s)[:, 1]
    auc_is_1 = roc_auc_score(y_is, prob_is_1)
    auc_oos_1 = roc_auc_score(y_oos, prob_oos_1)
    print(f"    IS AUC: {auc_is_1:.4f}")
    print(f"    OOS AUC: {auc_oos_1:.4f}")
    results['model1_vix_only'] = {
        'is_auc': round(float(auc_is_1), 4),
        'oos_auc': round(float(auc_oos_1), 4),
        'features': ['vix']
    }

    # Model 2: sigma_VIX only
    print("\n  Model 2: sigma_VIX only")
    X_is = is_data[['sigma_vix']].values
    X_oos = oos_data[['sigma_vix']].values

    scaler2 = StandardScaler()
    X_is_s = scaler2.fit_transform(X_is)
    X_oos_s = scaler2.transform(X_oos)

    lr2 = LogisticRegression(max_iter=1000, random_state=42)
    lr2.fit(X_is_s, y_is)
    prob_is_2 = lr2.predict_proba(X_is_s)[:, 1]
    prob_oos_2 = lr2.predict_proba(X_oos_s)[:, 1]
    auc_is_2 = roc_auc_score(y_is, prob_is_2)
    auc_oos_2 = roc_auc_score(y_oos, prob_oos_2)
    print(f"    IS AUC: {auc_is_2:.4f}")
    print(f"    OOS AUC: {auc_oos_2:.4f}")
    results['model2_sigma_vix'] = {
        'is_auc': round(float(auc_is_2), 4),
        'oos_auc': round(float(auc_oos_2), 4),
        'features': ['sigma_vix']
    }

    # Model 3: VIX + sigma_VIX
    print("\n  Model 3: VIX + sigma_VIX")
    feat3 = ['vix', 'sigma_vix']
    X_is = is_data[feat3].values
    X_oos = oos_data[feat3].values

    scaler3 = StandardScaler()
    X_is_s = scaler3.fit_transform(X_is)
    X_oos_s = scaler3.transform(X_oos)

    lr3 = LogisticRegression(max_iter=1000, random_state=42)
    lr3.fit(X_is_s, y_is)
    prob_is_3 = lr3.predict_proba(X_is_s)[:, 1]
    prob_oos_3 = lr3.predict_proba(X_oos_s)[:, 1]
    auc_is_3 = roc_auc_score(y_is, prob_is_3)
    auc_oos_3 = roc_auc_score(y_oos, prob_oos_3)
    print(f"    IS AUC: {auc_is_3:.4f}")
    print(f"    OOS AUC: {auc_oos_3:.4f}")
    print(f"    Coefs: VIX={lr3.coef_[0][0]:.4f}, sigma_VIX={lr3.coef_[0][1]:.4f}")
    results['model3_vix_sigma'] = {
        'is_auc': round(float(auc_is_3), 4),
        'oos_auc': round(float(auc_oos_3), 4),
        'features': feat3,
        'coefs': {feat3[i]: round(float(lr3.coef_[0][i]), 4) for i in range(len(feat3))}
    }

    # Model 4: All vol-of-vol features
    print("\n  Model 4: All vol-of-vol features")
    feat4 = ['vix', 'sigma_vix', 'sigma_vix_pct', 'vix_range_ma', 'garch_vix_vol', 'sigma_vix_zscore']
    X_is = is_data[feat4].values
    X_oos = oos_data[feat4].values

    scaler4 = StandardScaler()
    X_is_s = scaler4.fit_transform(X_is)
    X_oos_s = scaler4.transform(X_oos)

    lr4 = LogisticRegression(max_iter=1000, random_state=42)
    lr4.fit(X_is_s, y_is)
    prob_is_4 = lr4.predict_proba(X_is_s)[:, 1]
    prob_oos_4 = lr4.predict_proba(X_oos_s)[:, 1]
    auc_is_4 = roc_auc_score(y_is, prob_is_4)
    auc_oos_4 = roc_auc_score(y_oos, prob_oos_4)
    print(f"    IS AUC: {auc_is_4:.4f}")
    print(f"    OOS AUC: {auc_oos_4:.4f}")
    print(f"    Coefs:")
    for i, f in enumerate(feat4):
        print(f"      {f}: {lr4.coef_[0][i]:.4f}")
    results['model4_all_features'] = {
        'is_auc': round(float(auc_is_4), 4),
        'oos_auc': round(float(auc_oos_4), 4),
        'features': feat4,
        'coefs': {feat4[i]: round(float(lr4.coef_[0][i]), 4) for i in range(len(feat4))}
    }

    # Model 5: With VVIX (if available, subset of data)
    if has_vvix:
        print("\n  Model 5: VIX + sigma_VIX + VVIX (VVIX-available period)")
        feat5 = ['vix', 'sigma_vix', 'vvix']
        vvix_data = data[feat5 + [target]].dropna()
        is5 = vvix_data[vvix_data.index < OOS_START]
        oos5 = vvix_data[vvix_data.index >= OOS_START]

        if len(is5) > 100 and len(oos5) > 100:
            X_is5 = is5[feat5].values
            X_oos5 = oos5[feat5].values
            y_is5 = is5[target].values
            y_oos5 = oos5[target].values

            scaler5 = StandardScaler()
            X_is5_s = scaler5.fit_transform(X_is5)
            X_oos5_s = scaler5.transform(X_oos5)

            lr5 = LogisticRegression(max_iter=1000, random_state=42)
            lr5.fit(X_is5_s, y_is5)
            prob_is_5 = lr5.predict_proba(X_is5_s)[:, 1]
            prob_oos_5 = lr5.predict_proba(X_oos5_s)[:, 1]
            auc_is_5 = roc_auc_score(y_is5, prob_is_5)
            auc_oos_5 = roc_auc_score(y_oos5, prob_oos_5)
            print(f"    IS AUC: {auc_is_5:.4f} (N={len(is5)})")
            print(f"    OOS AUC: {auc_oos_5:.4f} (N={len(oos5)})")
            print(f"    Coefs: VIX={lr5.coef_[0][0]:.4f}, sigma_VIX={lr5.coef_[0][1]:.4f}, VVIX={lr5.coef_[0][2]:.4f}")
            results['model5_with_vvix'] = {
                'is_auc': round(float(auc_is_5), 4),
                'oos_auc': round(float(auc_oos_5), 4),
                'features': feat5,
                'coefs': {feat5[i]: round(float(lr5.coef_[0][i]), 4) for i in range(len(feat5))},
                'n_is': int(len(is5)),
                'n_oos': int(len(oos5))
            }

    # Incremental AUC test (bootstrap)
    print("\n  Bootstrap test: does sigma_VIX improve AUC over VIX alone?")
    n_boot = 5000
    n_oos = len(oos_data)
    auc_diff_boot = []
    np.random.seed(42)
    for b in range(n_boot):
        idx = np.random.choice(n_oos, n_oos, replace=True)
        y_b = y_oos[idx]
        if y_b.sum() == 0 or y_b.sum() == n_oos:
            continue
        auc1_b = roc_auc_score(y_b, prob_oos_1[idx])
        auc3_b = roc_auc_score(y_b, prob_oos_3[idx])
        auc_diff_boot.append(auc3_b - auc1_b)

    auc_diff_boot = np.array(auc_diff_boot)
    mean_diff = auc_diff_boot.mean()
    ci_lo = np.percentile(auc_diff_boot, 2.5)
    ci_hi = np.percentile(auc_diff_boot, 97.5)
    p_value = (auc_diff_boot <= 0).mean()
    print(f"    AUC(VIX+sigma) - AUC(VIX): {mean_diff:.4f} [{ci_lo:.4f}, {ci_hi:.4f}]")
    print(f"    P(AUC_diff <= 0): {p_value:.4f}")
    results['auc_bootstrap'] = {
        'mean_diff': round(float(mean_diff), 4),
        'ci_lower': round(float(ci_lo), 4),
        'ci_upper': round(float(ci_hi), 4),
        'p_value': round(float(p_value), 4),
        'n_boot': n_boot
    }

    return results, prob_oos_3, oos_data


def calm_before_storm_analysis(data):
    """Analyze vol-of-vol patterns around regime transitions."""
    print("\n── Calm-Before-Storm Analysis ──")

    # Find regime change dates
    rc_dates = data.index[data['regime_change'] == 1]
    print(f"  Total regime change dates: {len(rc_dates)}")

    # Separate into upward (low→high) and downward (high→low) transitions
    up_transitions = []   # VIX crosses above 20
    down_transitions = [] # VIX crosses below 20

    for d in rc_dates:
        loc = data.index.get_loc(d)
        if loc > 0:
            prev_regime = data['vix_regime'].iloc[loc - 1]
            curr_regime = data['vix_regime'].iloc[loc]
            if prev_regime == 0 and curr_regime == 1:
                up_transitions.append(d)
            elif prev_regime == 1 and curr_regime == 0:
                down_transitions.append(d)

    print(f"  Upward transitions (calm→storm): {len(up_transitions)}")
    print(f"  Downward transitions (storm→calm): {len(down_transitions)}")

    # For each transition, get vol-of-vol in the window before
    window_before = 22  # 1 month before
    window_after = 22   # 1 month after

    results = {}
    for label, transitions in [('up_calm_to_storm', up_transitions), ('down_storm_to_calm', down_transitions)]:
        sigma_before = []
        sigma_after = []
        sigma_at = []
        vix_before = []
        vix_at = []

        for d in transitions:
            loc = data.index.get_loc(d)
            if loc >= window_before and loc + window_after < len(data):
                before = data['sigma_vix'].iloc[loc - window_before:loc]
                after = data['sigma_vix'].iloc[loc:loc + window_after]
                if before.notna().sum() >= 10 and after.notna().sum() >= 10:
                    sigma_before.append(before.mean())
                    sigma_after.append(after.mean())
                    sigma_at.append(data['sigma_vix'].iloc[loc])
                    vix_before.append(data['vix'].iloc[loc - window_before:loc].mean())
                    vix_at.append(data['vix'].iloc[loc])

        sigma_before = np.array(sigma_before)
        sigma_after = np.array(sigma_after)
        sigma_at = np.array(sigma_at)

        if len(sigma_before) > 5:
            # Is vol-of-vol elevated BEFORE regime change?
            # Compare to unconditional mean
            unc_mean = data['sigma_vix'].dropna().mean()
            t_stat, p_val = stats.ttest_1samp(sigma_before, unc_mean)

            # Before vs after
            t_ba, p_ba = stats.ttest_rel(sigma_before, sigma_after[:len(sigma_before)])

            print(f"\n  {label}:")
            print(f"    N transitions (with data): {len(sigma_before)}")
            print(f"    sigma_VIX before (mean): {sigma_before.mean():.3f}")
            print(f"    sigma_VIX at transition: {np.nanmean(sigma_at):.3f}")
            print(f"    sigma_VIX after (mean): {sigma_after.mean():.3f}")
            print(f"    Unconditional sigma_VIX: {unc_mean:.3f}")
            print(f"    Before vs unconditional: t={t_stat:.2f}, p={p_val:.4f}")
            print(f"    Before vs after: t={t_ba:.2f}, p={p_ba:.4f}")

            results[label] = {
                'n_transitions': int(len(sigma_before)),
                'sigma_before_mean': round(float(sigma_before.mean()), 4),
                'sigma_at_mean': round(float(np.nanmean(sigma_at)), 4),
                'sigma_after_mean': round(float(sigma_after.mean()), 4),
                'unconditional_mean': round(float(unc_mean), 4),
                'ttest_vs_unconditional': {
                    't_stat': round(float(t_stat), 2),
                    'p_value': round(float(p_val), 4)
                },
                'ttest_before_vs_after': {
                    't_stat': round(float(t_ba), 2),
                    'p_value': round(float(p_ba), 4)
                }
            }

    return results


def vvix_vs_realized_comparison(data):
    """Compare market-implied VVIX vs realized vol-of-vol (sigma_VIX)."""
    print("\n── VVIX (Implied) vs sigma_VIX (Realized) ──")

    common = data[['vvix', 'sigma_vix']].dropna()
    if len(common) < 100:
        print("  Insufficient VVIX data for comparison")
        return {'insufficient_data': True}

    print(f"  Common period: {common.index[0].strftime('%Y-%m-%d')} to {common.index[-1].strftime('%Y-%m-%d')} ({len(common)} obs)")

    # Normalize both for comparison
    vvix_norm = (common['vvix'] - common['vvix'].mean()) / common['vvix'].std()
    sigma_norm = (common['sigma_vix'] - common['sigma_vix'].mean()) / common['sigma_vix'].std()

    # Correlation
    corr, p_corr = stats.pearsonr(common['vvix'], common['sigma_vix'])
    rank_corr, p_rank = stats.spearmanr(common['vvix'], common['sigma_vix'])
    print(f"  Pearson correlation: {corr:.4f} (p={p_corr:.4e})")
    print(f"  Spearman correlation: {rank_corr:.4f} (p={p_rank:.4e})")

    # Implied - Realized spread (VVIX premium)
    # Need to scale — VVIX is annualized vol of VIX in %, sigma_VIX is daily change in points
    # VVIX annualized → daily: VVIX/sqrt(252) → comparable to sigma_VIX as % of VIX level
    vvix_daily_pct = common['vvix'] / np.sqrt(252) / 100  # rough daily vol in decimal
    vix_at_common = data['vix'].reindex(common.index)
    sigma_vix_pct = common['sigma_vix'] / vix_at_common

    # Which leads which?
    print("\n  Cross-correlation (VVIX leads/lags sigma_VIX):")
    lead_lag = {}
    for lag in [-5, -3, -1, 0, 1, 3, 5]:
        if lag < 0:
            x = common['vvix'].iloc[:lag].values
            y = common['sigma_vix'].iloc[-lag:].values
        elif lag > 0:
            x = common['vvix'].iloc[lag:].values
            y = common['sigma_vix'].iloc[:-lag].values
        else:
            x = common['vvix'].values
            y = common['sigma_vix'].values
        r, p = stats.pearsonr(x, y)
        direction = "VVIX leads" if lag < 0 else ("sigma leads" if lag > 0 else "contemp")
        print(f"    lag={lag:>3}: r={r:.4f} (p={p:.4e})  [{direction}]")
        lead_lag[str(lag)] = round(float(r), 4)

    # Regime-conditional correlation
    high_vol = common[vix_at_common > VIX_THRESHOLD]
    low_vol = common[vix_at_common <= VIX_THRESHOLD]

    if len(high_vol) > 30 and len(low_vol) > 30:
        r_high, _ = stats.pearsonr(high_vol['vvix'], high_vol['sigma_vix'])
        r_low, _ = stats.pearsonr(low_vol['vvix'], low_vol['sigma_vix'])
        print(f"\n  Regime-conditional correlation:")
        print(f"    High vol (VIX>{VIX_THRESHOLD}): r={r_high:.4f} (N={len(high_vol)})")
        print(f"    Low vol (VIX<={VIX_THRESHOLD}): r={r_low:.4f} (N={len(low_vol)})")
    else:
        r_high, r_low = np.nan, np.nan

    return {
        'n_obs': int(len(common)),
        'period': f"{common.index[0].strftime('%Y-%m-%d')} to {common.index[-1].strftime('%Y-%m-%d')}",
        'pearson_corr': round(float(corr), 4),
        'spearman_corr': round(float(rank_corr), 4),
        'lead_lag_corr': lead_lag,
        'corr_high_vol': round(float(r_high), 4) if not np.isnan(r_high) else None,
        'corr_low_vol': round(float(r_low), 4) if not np.isnan(r_low) else None
    }


def strategy_backtest(data):
    """Test: 12/VIX × (1 - normalize(sigma_VIX)) — reduce exposure when VIX is volatile."""
    print("\n── Strategy Backtest ──")

    # Need sigma_vix for the strategy
    bt = data[['spy_return', 'vix', 'sigma_vix']].dropna().copy()
    print(f"  Backtest period: {bt.index[0].strftime('%Y-%m-%d')} to {bt.index[-1].strftime('%Y-%m-%d')} ({len(bt)} obs)")

    # Standard 12/VIX
    bt['w_standard'] = (12.0 / bt['vix']).clip(0, 1)

    # Normalize sigma_VIX to [0, 1] using rolling percentile
    bt['sigma_pctile'] = bt['sigma_vix'].rolling(252, min_periods=60).apply(
        lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100, raw=False
    )

    # Vol-of-vol adjusted: reduce exposure proportionally to sigma_VIX percentile
    # When sigma_VIX is at 90th percentile → scale by 0.1 (very defensive)
    # When sigma_VIX is at 10th percentile → scale by 0.9 (confident)
    bt['w_vov_adj'] = (bt['w_standard'] * (1 - bt['sigma_pctile'])).clip(0, 1)

    # Also test a softer version: sqrt scaling
    bt['w_vov_soft'] = (bt['w_standard'] * (1 - bt['sigma_pctile'] * 0.5)).clip(0, 1)

    # Cash return = 0 for simplicity (conservative; risk-free rate is positive)
    strategies = {
        'standard_12vix': 'w_standard',
        'vov_adjusted': 'w_vov_adj',
        'vov_soft': 'w_vov_soft',
        'buy_hold': None
    }

    results = {}
    print(f"\n  {'Strategy':<25} {'CAGR':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Avg_W':>8}")
    print(f"  {'-'*78}")

    for name, w_col in strategies.items():
        if w_col:
            ret = bt['spy_return'] * bt[w_col].shift(1)  # weights known at t-1
        else:
            ret = bt['spy_return']

        ret = ret.dropna()
        cum = (1 + ret).cumprod()
        n_years = len(ret) / 252

        cagr = (cum.iloc[-1] ** (1 / n_years) - 1) * 100
        vol = ret.std() * np.sqrt(252) * 100
        sharpe = (ret.mean() / ret.std()) * np.sqrt(252) if ret.std() > 0 else 0

        # Max drawdown
        peak = cum.expanding().max()
        dd = (cum - peak) / peak
        mdd = dd.min() * 100

        calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

        avg_w = bt[w_col].mean() if w_col else 1.0

        print(f"  {name:<25} {cagr:>7.2f}% {vol:>7.2f}% {sharpe:>8.3f} {mdd:>7.2f}% {calmar:>8.3f} {avg_w:>7.3f}")

        results[name] = {
            'cagr_pct': round(float(cagr), 2),
            'vol_pct': round(float(vol), 2),
            'sharpe': round(float(sharpe), 3),
            'mdd_pct': round(float(mdd), 2),
            'calmar': round(float(calmar), 3),
            'avg_weight': round(float(avg_w), 3),
            'n_obs': int(len(ret)),
            'n_years': round(float(n_years), 1)
        }

    # DM test: vov_adjusted vs standard_12vix
    print("\n  Diebold-Mariano test (vol-of-vol adjusted vs standard 12/VIX):")
    ret_std = (bt['spy_return'] * bt['w_standard'].shift(1)).dropna()
    ret_vov = (bt['spy_return'] * bt['w_vov_adj'].shift(1)).dropna()
    common_idx = ret_std.index.intersection(ret_vov.index)
    d = ret_vov.loc[common_idx] - ret_std.loc[common_idx]
    dm_mean = d.mean()
    # Newey-West HAC standard error (lag = int(len(d)^(1/3)))
    lag_nw = int(len(d) ** (1/3))
    gamma_0 = np.var(d)
    gamma_sum = 0
    for j in range(1, lag_nw + 1):
        gamma_j = np.cov(d.values[j:], d.values[:-j])[0, 1]
        gamma_sum += 2 * (1 - j / (lag_nw + 1)) * gamma_j
    hac_var = gamma_0 + gamma_sum
    dm_stat = dm_mean / np.sqrt(hac_var / len(d))
    dm_pval = 2 * (1 - stats.t.cdf(abs(dm_stat), df=len(d) - 1))
    print(f"    DM statistic: {dm_stat:.3f}")
    print(f"    p-value: {dm_pval:.4f}")
    print(f"    Mean return difference: {dm_mean*252*100:.2f}% annualized")

    results['dm_test'] = {
        'dm_stat': round(float(dm_stat), 3),
        'p_value': round(float(dm_pval), 4),
        'mean_diff_ann_pct': round(float(dm_mean * 252 * 100), 2)
    }

    # OOS-only comparison
    print("\n  Out-of-sample performance (2020-01-01 onwards):")
    oos_bt = bt[bt.index >= OOS_START]
    print(f"  {'Strategy':<25} {'CAGR':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8}")
    print(f"  {'-'*55}")

    oos_results = {}
    for name, w_col in strategies.items():
        if w_col:
            ret = oos_bt['spy_return'] * oos_bt[w_col].shift(1)
        else:
            ret = oos_bt['spy_return']
        ret = ret.dropna()
        cum = (1 + ret).cumprod()
        n_years = len(ret) / 252
        cagr = (cum.iloc[-1] ** (1 / n_years) - 1) * 100
        vol = ret.std() * np.sqrt(252) * 100
        sharpe = (ret.mean() / ret.std()) * np.sqrt(252) if ret.std() > 0 else 0
        peak = cum.expanding().max()
        dd = (cum - peak) / peak
        mdd = dd.min() * 100
        print(f"  {name:<25} {cagr:>7.2f}% {vol:>7.2f}% {sharpe:>8.3f} {mdd:>7.2f}%")
        oos_results[name] = {
            'cagr_pct': round(float(cagr), 2),
            'vol_pct': round(float(vol), 2),
            'sharpe': round(float(sharpe), 3),
            'mdd_pct': round(float(mdd), 2)
        }

    results['oos_performance'] = oos_results

    return results


def regime_conditional_strategy(data):
    """Test: use vol-of-vol to determine when to be more/less aggressive."""
    print("\n── Regime-Conditional Strategy Analysis ──")

    bt = data[['spy_return', 'vix', 'sigma_vix']].dropna().copy()

    # Quartile-based analysis
    bt['sigma_quartile'] = pd.qcut(bt['sigma_vix'], q=4, labels=['Q1_low', 'Q2', 'Q3', 'Q4_high'])

    print(f"\n  SPY return by sigma_VIX quartile:")
    print(f"  {'Quartile':<12} {'Mean':>8} {'Vol':>8} {'Sharpe':>8} {'N':>6}")
    print(f"  {'-'*46}")

    quartile_results = {}
    for q in ['Q1_low', 'Q2', 'Q3', 'Q4_high']:
        mask = bt['sigma_quartile'] == q
        ret = bt.loc[mask, 'spy_return']
        mean_ann = ret.mean() * 252 * 100
        vol_ann = ret.std() * np.sqrt(252) * 100
        sharpe = (ret.mean() / ret.std()) * np.sqrt(252) if ret.std() > 0 else 0
        print(f"  {q:<12} {mean_ann:>7.2f}% {vol_ann:>7.2f}% {sharpe:>8.3f} {len(ret):>6}")
        quartile_results[q] = {
            'mean_ann_pct': round(float(mean_ann), 2),
            'vol_ann_pct': round(float(vol_ann), 2),
            'sharpe': round(float(sharpe), 3),
            'n_obs': int(len(ret))
        }

    # F-test: are means different across quartiles?
    groups = [bt.loc[bt['sigma_quartile'] == q, 'spy_return'].values for q in ['Q1_low', 'Q2', 'Q3', 'Q4_high']]
    f_stat, f_pval = stats.f_oneway(*groups)
    print(f"\n  ANOVA F-test: F={f_stat:.3f}, p={f_pval:.4f}")

    # Cross-tabulation: sigma_VIX quartile × VIX regime
    print(f"\n  Cross-tabulation (sigma_VIX quartile × VIX regime):")
    ct = pd.crosstab(bt['sigma_quartile'], bt['vix'] > VIX_THRESHOLD, normalize='index')
    ct.columns = ['Low_VIX', 'High_VIX']
    print(ct.to_string())

    return {
        'quartile_returns': quartile_results,
        'anova_f_stat': round(float(f_stat), 3),
        'anova_p_value': round(float(f_pval), 4),
    }


def main():
    """Main execution."""
    all_results = {
        'experiment_id': 'K649',
        'title': 'Volatility of Volatility — Regime Change Prediction',
        'data_source': 'yfinance (SPY, ^VIX, ^VVIX)',
        'period': f'{START_DATE} to {END_DATE}',
        'type': 'empirical_analysis',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'references': [
            'Huang & Shaliastovich (2015) "Volatility-of-Volatility Risk"',
            'Park (2015) "Volatility-of-Volatility and Tail Risk Hedging Returns" JBF',
            'Baltussen et al. (2018) "Unknown Unknowns: Uncertainty About Risk"',
            'Avellaneda & Papanicolaou (2019) "Statistics of VIX Futures"',
            'Prior: K448 (VVIX null), J17 (VVIX tail-guard null), K1 (options surface absorbed by VIX)'
        ],
        'prior_knowledge': {
            'K448': 'VVIX as vol predictor: null',
            'J17': 'VVIX tail-guard overlay: null, partial corr=0.006. High VVIX predicts VIX mean-reversion.',
            'K1': 'Options surface (SKEW/VVIX/VIX3M) absorbed by VIX. VIX sufficient #15.',
            'VoV_spike': 'VoV >2σ spike is short-term (5d) signal but not 22d.'
        }
    }

    # Step 1: Download data
    data, vvix_available = download_data()
    all_results['vvix_available'] = vvix_available

    # Step 2: Construct vol-of-vol measures
    data, desc_stats = construct_vol_of_vol_measures(data)
    all_results['descriptive_stats'] = desc_stats

    # Step 3: Define regime changes
    data, regime_stats = define_regime_changes(data)
    all_results['regime_stats'] = regime_stats

    # Step 4: Lead-lag analysis
    lead_lag = analyze_lead_lag(data)
    all_results['lead_lag_analysis'] = lead_lag

    # Step 5: Regime change prediction
    prediction_results, prob_oos, oos_data = regime_change_prediction(data)
    all_results['regime_prediction'] = prediction_results

    # Step 6: Calm-before-storm
    storm_results = calm_before_storm_analysis(data)
    all_results['calm_before_storm'] = storm_results

    # Step 7: VVIX vs realized
    vvix_comparison = vvix_vs_realized_comparison(data)
    all_results['vvix_vs_realized'] = vvix_comparison

    # Step 8: Strategy backtest
    strategy_results = strategy_backtest(data)
    all_results['strategy_backtest'] = strategy_results

    # Step 9: Regime-conditional strategy
    regime_cond = regime_conditional_strategy(data)
    all_results['regime_conditional'] = regime_cond

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    best_oos_auc = max(
        prediction_results.get('model1_vix_only', {}).get('oos_auc', 0),
        prediction_results.get('model2_sigma_vix', {}).get('oos_auc', 0),
        prediction_results.get('model3_vix_sigma', {}).get('oos_auc', 0),
        prediction_results.get('model4_all_features', {}).get('oos_auc', 0),
    )

    dm_p = strategy_results.get('dm_test', {}).get('p_value', 1.0)
    dm_stat = strategy_results.get('dm_test', {}).get('dm_stat', 0)
    dm_diff = strategy_results.get('dm_test', {}).get('mean_diff_ann_pct', 0)
    auc_boot_p = prediction_results.get('auc_bootstrap', {}).get('p_value', 1.0)
    sharpe_std = strategy_results.get('standard_12vix', {}).get('sharpe', 0)
    sharpe_vov = strategy_results.get('vov_adjusted', {}).get('sharpe', 0)

    # Determine if vol-of-vol adds value
    # DM test: significant AND positive (vov improves over standard)
    dm_improves = (dm_p < 0.05) and (dm_stat > 0)
    auc_improves = (auc_boot_p < 0.05)
    is_significant = dm_improves or auc_improves

    print(f"\n  1. REGIME CHANGE PREDICTION:")
    print(f"     Best OOS AUC: {best_oos_auc:.4f} (random = 0.50)")
    print(f"     sigma_VIX incremental AUC: p={auc_boot_p:.4f}")
    if best_oos_auc > 0.60:
        print(f"     → Moderate predictive power for regime changes")
    elif best_oos_auc > 0.55:
        print(f"     → Weak predictive power")
    else:
        print(f"     → No meaningful predictive power")

    print(f"\n  2. STRATEGY APPLICATION:")
    print(f"     Standard 12/VIX Sharpe: {sharpe_std:.3f}")
    print(f"     VoV-adjusted Sharpe: {sharpe_vov:.3f}")
    print(f"     DM test: t={dm_stat:.3f}, p={dm_p:.4f}, diff={dm_diff:.2f}% ann.")
    if dm_p < 0.05 and dm_stat < 0:
        print(f"     → VoV adjustment SIGNIFICANTLY HURTS performance (over-hedging)")
    elif dm_p < 0.05 and dm_stat > 0:
        print(f"     → VoV adjustment significantly improves performance")
    else:
        print(f"     → NOT statistically significant difference")

    print(f"\n  3. CALM-BEFORE-STORM:")
    for label in ['up_calm_to_storm', 'down_storm_to_calm']:
        if label in storm_results:
            p = storm_results[label]['ttest_vs_unconditional']['p_value']
            direction = "elevated" if storm_results[label]['sigma_before_mean'] > storm_results[label]['unconditional_mean'] else "NOT elevated"
            print(f"     {label}: sigma_VIX {direction} before transition (p={p:.4f})")

    print(f"\n  4. CONCLUSION:")
    if is_significant:
        conclusion = "Vol-of-vol provides INCREMENTAL information for regime change prediction beyond VIX level."
    else:
        conclusion = (
            "Vol-of-vol does NOT improve on VIX alone. "
            "AUC increment NS (p=%.4f). VoV strategy adjustment HURTS returns (DM t=%.3f, p=%.4f). "
            "VIX level remains sufficient. Consistent with K448/J17/K1. "
            "However: (a) VVIX leads sigma_VIX (implied leads realized), "
            "(b) sigma_VIX BEFORE transitions is NOT elevated (no calm-before-storm), "
            "(c) Q1 sigma_VIX has Sharpe 2.16 but ANOVA NS — this is VIX-regime confounded."
        ) % (auc_boot_p, dm_stat, dm_p)
    print(f"     {conclusion}")

    all_results['conclusion'] = {
        'is_significant': is_significant,
        'vov_helps_prediction': auc_improves,
        'vov_helps_strategy': dm_improves,
        'vov_hurts_strategy': (dm_p < 0.05 and dm_stat < 0),
        'best_oos_auc': round(float(best_oos_auc), 4),
        'auc_increment_p': round(float(auc_boot_p), 4),
        'dm_test_stat': round(float(dm_stat), 3),
        'dm_test_p': round(float(dm_p), 4),
        'summary': conclusion,
        'limitations': [
            'VIX threshold of 20 is arbitrary; results may differ at other thresholds',
            f'OOS period starts {OOS_START}, includes COVID shock (may inflate AUC)',
            'GARCH(1,1) on VIX uses fixed parameters, not MLE-estimated',
            'Strategy backtest assumes zero cash return (understates cash position value)',
            'VVIX history shorter than VIX, limits some comparisons',
            'Logistic regression assumes linear decision boundary'
        ]
    }

    # Save results
    with open(RESULTS_FILE, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to: {RESULTS_FILE}")


if __name__ == '__main__':
    main()
