"""
K637: Volatility Regime Identification via Unsupervised Clustering

Motivation:
- Our strategies use VIX thresholds (15, 20, 25, 30) chosen somewhat arbitrarily
- Can unsupervised learning identify the "natural" volatility regimes?
- Both a methodological question and a practical one for strategy design

Methodology:
- Features: VIX level, VIX 5d change, VIX 22d percentile, |r_SPY|, σ_22, VIX/σ_22 ratio
- Clustering: K-Means (k=2..5), GMM (k=2..5), HMM (2/3 states), fixed threshold baseline
- Evaluation: Silhouette, BIC, regime characteristics, transition probabilities, duration
- Economic test: cluster-based vs fixed-bracket allocation in 12/VIX strategy

Data source: yfinance (SPY, ^VIX), 2006-01-01 to 2026-03-27
References:
- Hamilton (1989) "A New Approach to Economic Analysis of Nonstationary Time Series" - HMM for regime switching
- Ang & Bekaert (2002) "Regime Switches in Interest Rates" JFE - Markov regime switching in finance
- Guidolin & Timmermann (2007) "Asset allocation under multivariate regime switching" JEE - multi-regime portfolio allocation
"""

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.metrics import silhouette_score
from scipy import stats
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download & Feature Engineering
# ============================================================
print("=" * 70)
print("K637: Volatility Regime Identification via Unsupervised Clustering")
print("=" * 70)

print("\n[1] Downloading data...")
spy = yf.download("SPY", start="2006-01-01", end="2026-03-28", progress=False)
vix = yf.download("^VIX", start="2006-01-01", end="2026-03-28", progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Build feature dataframe
df = pd.DataFrame(index=spy.index)
df['spy_close'] = spy['Close']
df['spy_return'] = np.log(spy['Close'] / spy['Close'].shift(1))
df['vix'] = vix['Close'].reindex(spy.index, method='ffill')

# Feature engineering
df['vix_5d_change'] = df['vix'] - df['vix'].shift(5)
df['vix_22d_pctile'] = df['vix'].rolling(252).apply(
    lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100.0, raw=False
)
df['abs_return'] = df['spy_return'].abs()
df['rv_22d'] = df['spy_return'].rolling(22).std() * np.sqrt(252)  # annualized
df['vrp_proxy'] = df['vix'] / (df['rv_22d'] * 100 + 1e-8)  # VIX / realized vol ratio

# Drop NaN rows
df = df.dropna()
print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(df)}")

# ============================================================
# 2. Descriptive Statistics
# ============================================================
print("\n[2] Descriptive Statistics (features)")
feature_cols = ['vix', 'vix_5d_change', 'vix_22d_pctile', 'abs_return', 'rv_22d', 'vrp_proxy']
desc_stats = {}
for col in feature_cols:
    s = df[col]
    desc_stats[col] = {
        'mean': float(s.mean()),
        'std': float(s.std()),
        'skew': float(s.skew()),
        'kurtosis': float(s.kurtosis()),
        'min': float(s.min()),
        'max': float(s.max()),
        'median': float(s.median()),
    }
    print(f"  {col:20s}: mean={s.mean():.4f}, std={s.std():.4f}, skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

# ============================================================
# 3. Standardize features for clustering
# ============================================================
print("\n[3] Standardizing features...")
X = df[feature_cols].values
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
print(f"  Feature matrix shape: {X_scaled.shape}")

# ============================================================
# 4. K-Means Clustering
# ============================================================
print("\n[4] K-Means Clustering (k=2..5)")
kmeans_results = {}
for k in range(2, 6):
    km = KMeans(n_clusters=k, n_init=20, random_state=42, max_iter=500)
    labels = km.fit_predict(X_scaled)
    sil = silhouette_score(X_scaled, labels)
    inertia = km.inertia_

    # Compute BIC-like criterion for K-Means
    # BIC = n*ln(SSE/n) + k*d*ln(n)
    n, d = X_scaled.shape
    bic_km = n * np.log(inertia / n) + k * d * np.log(n)

    kmeans_results[k] = {
        'silhouette': float(sil),
        'inertia': float(inertia),
        'bic': float(bic_km),
        'labels': labels,
    }
    print(f"  k={k}: silhouette={sil:.4f}, inertia={inertia:.1f}, BIC={bic_km:.1f}")

best_k_km = max(kmeans_results.keys(), key=lambda k: kmeans_results[k]['silhouette'])
print(f"  Best K-Means k by silhouette: {best_k_km}")

# ============================================================
# 5. Gaussian Mixture Model (GMM)
# ============================================================
print("\n[5] Gaussian Mixture Model (k=2..5)")
gmm_results = {}
for k in range(2, 6):
    gmm = GaussianMixture(n_components=k, covariance_type='full',
                           n_init=5, random_state=42, max_iter=500)
    gmm.fit(X_scaled)
    labels = gmm.predict(X_scaled)
    sil = silhouette_score(X_scaled, labels)
    bic = gmm.bic(X_scaled)
    aic = gmm.aic(X_scaled)

    gmm_results[k] = {
        'silhouette': float(sil),
        'bic': float(bic),
        'aic': float(aic),
        'labels': labels,
        'converged': bool(gmm.converged_),
    }
    print(f"  k={k}: silhouette={sil:.4f}, BIC={bic:.1f}, AIC={aic:.1f}, converged={gmm.converged_}")

best_k_gmm_bic = min(gmm_results.keys(), key=lambda k: gmm_results[k]['bic'])
best_k_gmm_sil = max(gmm_results.keys(), key=lambda k: gmm_results[k]['silhouette'])
print(f"  Best GMM k by BIC: {best_k_gmm_bic}")
print(f"  Best GMM k by silhouette: {best_k_gmm_sil}")

# ============================================================
# 6. Hidden Markov Model (HMM)
# ============================================================
print("\n[6] Hidden Markov Model (2 and 3 states)")
hmm_results = {}
try:
    from hmmlearn.hmm import GaussianHMM

    # Use VIX + abs_return + rv_22d for HMM (key vol features)
    hmm_features = df[['vix', 'abs_return', 'rv_22d']].values
    hmm_scaler = StandardScaler()
    hmm_features_scaled = hmm_scaler.fit_transform(hmm_features)

    for n_states in [2, 3]:
        best_score = -np.inf
        best_model = None
        # Run multiple initializations to find best
        for trial in range(10):
            try:
                model = GaussianHMM(
                    n_components=n_states,
                    covariance_type='full',
                    n_iter=200,
                    random_state=42 + trial,
                    tol=1e-4
                )
                model.fit(hmm_features_scaled)
                score = model.score(hmm_features_scaled)
                if score > best_score:
                    best_score = score
                    best_model = model
            except Exception:
                continue

        if best_model is not None:
            labels = best_model.predict(hmm_features_scaled)
            transmat = best_model.transmat_
            sil = silhouette_score(hmm_features_scaled, labels)

            hmm_results[n_states] = {
                'silhouette': float(sil),
                'log_likelihood': float(best_score),
                'transition_matrix': transmat.tolist(),
                'labels': labels,
                'converged': True,
            }
            print(f"  {n_states}-state HMM: silhouette={sil:.4f}, log_L={best_score:.1f}")
            print(f"    Transition matrix:")
            for i in range(n_states):
                row = ", ".join([f"{transmat[i,j]:.4f}" for j in range(n_states)])
                print(f"      State {i}: [{row}]")
        else:
            print(f"  {n_states}-state HMM: FAILED to converge")
            hmm_results[n_states] = {'converged': False}

    hmm_available = True
except ImportError:
    print("  hmmlearn not available, skipping HMM")
    hmm_available = False

# ============================================================
# 7. Fixed Threshold Baseline (Our current brackets)
# ============================================================
print("\n[7] Fixed Threshold Baseline [0-15, 15-20, 20-30, 30+]")
def assign_fixed_regime(vix_val):
    if vix_val < 15:
        return 0  # Low vol
    elif vix_val < 20:
        return 1  # Normal
    elif vix_val < 30:
        return 2  # Elevated
    else:
        return 3  # Crisis

df['fixed_regime'] = df['vix'].apply(assign_fixed_regime)
fixed_labels = df['fixed_regime'].values
fixed_sil = silhouette_score(X_scaled, fixed_labels)
print(f"  Fixed threshold silhouette: {fixed_sil:.4f}")

# ============================================================
# 8. Regime Characteristics Analysis
# ============================================================
print("\n[8] Regime Characteristics Analysis")

def analyze_regimes(labels, name, df_data):
    """Analyze characteristics of identified regimes."""
    results = {}
    unique_labels = sorted(np.unique(labels))
    n_regimes = len(unique_labels)

    print(f"\n  --- {name} ({n_regimes} regimes) ---")

    for regime in unique_labels:
        mask = labels == regime
        n_obs = int(mask.sum())
        pct = n_obs / len(labels) * 100

        regime_data = df_data[mask]

        mean_vix = float(regime_data['vix'].mean())
        mean_ret = float(regime_data['spy_return'].mean() * 252)  # annualized
        mean_vol = float(regime_data['rv_22d'].mean())
        mean_abs_ret = float(regime_data['abs_return'].mean() * np.sqrt(252))
        mean_vrp = float(regime_data['vrp_proxy'].mean())
        sharpe = mean_ret / (mean_vol + 1e-8)

        results[int(regime)] = {
            'n_obs': n_obs,
            'pct': float(pct),
            'mean_vix': mean_vix,
            'mean_annual_return': mean_ret,
            'mean_rv_22d': mean_vol,
            'mean_abs_return_ann': mean_abs_ret,
            'mean_vrp_proxy': mean_vrp,
            'sharpe_ratio': float(sharpe),
            'vix_range': [float(regime_data['vix'].min()), float(regime_data['vix'].max())],
        }

        print(f"    Regime {regime}: n={n_obs} ({pct:.1f}%), VIX={mean_vix:.1f}, "
              f"Return={mean_ret*100:.1f}%, Vol={mean_vol*100:.1f}%, Sharpe={sharpe:.2f}")

    return results

# Analyze all methods
regime_chars = {}

# K-Means best
km_labels = kmeans_results[best_k_km]['labels']
regime_chars['kmeans'] = analyze_regimes(km_labels, f"K-Means (k={best_k_km})", df)

# GMM best by BIC
gmm_labels = gmm_results[best_k_gmm_bic]['labels']
regime_chars['gmm'] = analyze_regimes(gmm_labels, f"GMM (k={best_k_gmm_bic})", df)

# HMM
if hmm_available:
    for n_states in [2, 3]:
        if n_states in hmm_results and hmm_results[n_states].get('converged', False):
            hmm_labels = hmm_results[n_states]['labels']
            regime_chars[f'hmm_{n_states}'] = analyze_regimes(
                hmm_labels, f"HMM ({n_states}-state)", df)

# Fixed threshold
regime_chars['fixed'] = analyze_regimes(fixed_labels, "Fixed Threshold", df)

# ============================================================
# 9. Transition Probabilities & Duration Analysis
# ============================================================
print("\n[9] Transition Probabilities & Average Duration")

def compute_transitions(labels, name):
    """Compute transition matrix and average duration in each regime."""
    unique_labels = sorted(np.unique(labels))
    n_regimes = len(unique_labels)
    label_map = {l: i for i, l in enumerate(unique_labels)}

    # Transition counts
    trans_counts = np.zeros((n_regimes, n_regimes))
    for i in range(len(labels) - 1):
        fr = label_map[labels[i]]
        to = label_map[labels[i + 1]]
        trans_counts[fr, to] += 1

    # Normalize to probabilities
    row_sums = trans_counts.sum(axis=1, keepdims=True)
    trans_probs = np.where(row_sums > 0, trans_counts / row_sums, 0)

    # Average duration (consecutive days in same regime)
    durations = {l: [] for l in unique_labels}
    current_label = labels[0]
    current_duration = 1
    for i in range(1, len(labels)):
        if labels[i] == current_label:
            current_duration += 1
        else:
            durations[current_label].append(current_duration)
            current_label = labels[i]
            current_duration = 1
    durations[current_label].append(current_duration)

    avg_durations = {}
    for l in unique_labels:
        if durations[l]:
            avg_durations[int(l)] = {
                'mean_days': float(np.mean(durations[l])),
                'median_days': float(np.median(durations[l])),
                'max_days': int(np.max(durations[l])),
                'n_episodes': len(durations[l]),
            }

    print(f"\n  --- {name} Transitions ---")
    print(f"    Transition matrix:")
    for i in range(n_regimes):
        row = ", ".join([f"{trans_probs[i,j]:.4f}" for j in range(n_regimes)])
        print(f"      Regime {unique_labels[i]}: [{row}]")

    print(f"    Average durations:")
    for l in unique_labels:
        d = avg_durations.get(int(l), {})
        print(f"      Regime {l}: mean={d.get('mean_days', 0):.1f}d, "
              f"median={d.get('median_days', 0):.1f}d, "
              f"max={d.get('max_days', 0)}d, "
              f"episodes={d.get('n_episodes', 0)}")

    return {
        'transition_matrix': trans_probs.tolist(),
        'avg_durations': avg_durations,
    }

transition_results = {}
transition_results['kmeans'] = compute_transitions(km_labels, f"K-Means (k={best_k_km})")
transition_results['gmm'] = compute_transitions(gmm_labels, f"GMM (k={best_k_gmm_bic})")
if hmm_available:
    for n_states in [2, 3]:
        if n_states in hmm_results and hmm_results[n_states].get('converged', False):
            transition_results[f'hmm_{n_states}'] = compute_transitions(
                hmm_results[n_states]['labels'], f"HMM ({n_states}-state)")
transition_results['fixed'] = compute_transitions(fixed_labels, "Fixed Threshold")

# ============================================================
# 10. Regime-VIX Mapping Analysis
# ============================================================
print("\n[10] Do Data-Driven Regimes Match Fixed Brackets?")

def regime_vix_overlap(labels, name, df_data):
    """Analyze how cluster-identified regimes map to VIX levels."""
    unique_labels = sorted(np.unique(labels))

    # Sort regimes by mean VIX (low to high)
    regime_mean_vix = []
    for regime in unique_labels:
        mask = labels == regime
        mean_v = df_data.loc[mask, 'vix'].mean()
        regime_mean_vix.append((regime, mean_v))
    regime_mean_vix.sort(key=lambda x: x[1])

    print(f"\n  --- {name}: VIX distribution by regime (sorted by mean VIX) ---")
    mapping = {}
    for rank, (regime, mean_v) in enumerate(regime_mean_vix):
        mask = labels == regime
        vix_vals = df_data.loc[mask, 'vix']
        q25, q75 = float(vix_vals.quantile(0.25)), float(vix_vals.quantile(0.75))
        print(f"    Rank {rank} (Regime {regime}): VIX range [{vix_vals.min():.1f}, {vix_vals.max():.1f}], "
              f"mean={mean_v:.1f}, IQR=[{q25:.1f}, {q75:.1f}]")
        mapping[int(regime)] = {
            'rank': rank,
            'mean_vix': float(mean_v),
            'vix_range': [float(vix_vals.min()), float(vix_vals.max())],
            'iqr': [q25, q75],
        }

    # Check overlap with fixed brackets
    fixed_brackets = [(0, 15, 'Low'), (15, 20, 'Normal'), (20, 30, 'Elevated'), (30, 100, 'Crisis')]
    print(f"\n    Regime vs Fixed Bracket cross-tab:")
    cross_tab = {}
    for regime in unique_labels:
        mask = labels == regime
        vix_vals = df_data.loc[mask, 'vix']
        bracket_counts = {}
        for lo, hi, bname in fixed_brackets:
            cnt = int(((vix_vals >= lo) & (vix_vals < hi)).sum())
            bracket_counts[bname] = cnt
        cross_tab[int(regime)] = bracket_counts
        total = sum(bracket_counts.values())
        pcts = {k: f"{v/total*100:.0f}%" for k, v in bracket_counts.items()}
        print(f"      Regime {regime}: {pcts}")

    return {'mapping': mapping, 'cross_tab': cross_tab}

overlap_results = {}
overlap_results['kmeans'] = regime_vix_overlap(km_labels, f"K-Means (k={best_k_km})", df)
overlap_results['gmm'] = regime_vix_overlap(gmm_labels, f"GMM (k={best_k_gmm_bic})", df)

# ============================================================
# 11. Economic Test: Cluster-Based vs Fixed-Bracket 12/VIX Strategy
# ============================================================
print("\n[11] Economic Test: Cluster-Based vs Fixed-Bracket 12/VIX Strategy")

def backtest_12vix_fixed(df_data, start_date='2010-01-01'):
    """Standard 12/VIX strategy with fixed brackets."""
    bt = df_data.loc[start_date:].copy()
    bt['weight'] = np.clip(12.0 / bt['vix'], 0, 1)
    bt['strategy_return'] = bt['weight'].shift(1) * bt['spy_return']
    bt['buy_hold_return'] = bt['spy_return']
    bt = bt.dropna()

    cum_strat = (1 + bt['strategy_return']).cumprod()
    cum_bh = (1 + bt['buy_hold_return']).cumprod()

    n_years = len(bt) / 252
    cagr_strat = float(cum_strat.iloc[-1] ** (1 / n_years) - 1)
    cagr_bh = float(cum_bh.iloc[-1] ** (1 / n_years) - 1)
    vol_strat = float(bt['strategy_return'].std() * np.sqrt(252))
    vol_bh = float(bt['buy_hold_return'].std() * np.sqrt(252))
    sharpe_strat = cagr_strat / (vol_strat + 1e-8)
    sharpe_bh = cagr_bh / (vol_bh + 1e-8)

    # Max drawdown
    rolling_max = cum_strat.cummax()
    drawdown = (cum_strat - rolling_max) / rolling_max
    mdd_strat = float(drawdown.min())

    rolling_max_bh = cum_bh.cummax()
    drawdown_bh = (cum_bh - rolling_max_bh) / rolling_max_bh
    mdd_bh = float(drawdown_bh.min())

    return {
        'cagr': cagr_strat,
        'vol': vol_strat,
        'sharpe': sharpe_strat,
        'mdd': mdd_strat,
        'cagr_bh': cagr_bh,
        'vol_bh': vol_bh,
        'sharpe_bh': sharpe_bh,
        'mdd_bh': mdd_bh,
        'n_days': len(bt),
        'returns': bt['strategy_return'],
    }

def backtest_cluster_based(df_data, labels, start_date='2010-01-01'):
    """
    Cluster-based allocation: assign weight = 12/mean_VIX_in_regime for each regime.
    This is analogous to 12/VIX but using the cluster's central VIX rather than daily VIX.
    Alternative: use regime-specific optimal weights calibrated from data.
    """
    unique_labels = sorted(np.unique(labels))

    # Sort regimes by mean VIX
    regime_mean_vix = {}
    for regime in unique_labels:
        mask = labels == regime
        regime_mean_vix[regime] = df_data.loc[mask, 'vix'].mean()

    # Assign weight = 12 / regime_mean_VIX (capped at 1)
    weights_by_regime = {}
    for regime in unique_labels:
        w = min(12.0 / regime_mean_vix[regime], 1.0)
        weights_by_regime[regime] = w

    bt = df_data.loc[start_date:].copy()
    # Map labels to backtest period
    bt_labels = labels[df_data.index >= pd.Timestamp(start_date)]
    if len(bt_labels) != len(bt):
        bt_labels = bt_labels[:len(bt)]

    bt['weight'] = [weights_by_regime.get(l, 0.5) for l in bt_labels]
    bt['strategy_return'] = bt['weight'].shift(1) * bt['spy_return']
    bt = bt.dropna()

    cum_strat = (1 + bt['strategy_return']).cumprod()
    n_years = len(bt) / 252
    cagr = float(cum_strat.iloc[-1] ** (1 / n_years) - 1)
    vol = float(bt['strategy_return'].std() * np.sqrt(252))
    sharpe = cagr / (vol + 1e-8)

    rolling_max = cum_strat.cummax()
    drawdown = (cum_strat - rolling_max) / rolling_max
    mdd = float(drawdown.min())

    return {
        'cagr': cagr,
        'vol': vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'weights_by_regime': {int(k): float(v) for k, v in weights_by_regime.items()},
        'regime_mean_vix': {int(k): float(v) for k, v in regime_mean_vix.items()},
        'n_days': len(bt),
        'returns': bt['strategy_return'],
    }

def backtest_cluster_optimal(df_data, labels, start_date='2010-01-01', train_end='2019-12-31'):
    """
    Regime-optimal allocation: calibrate weights from IS period, test on OOS.
    For each regime, find the weight that maximizes Sharpe in the training period.
    """
    unique_labels = sorted(np.unique(labels))

    # Training period
    train_mask = df_data.index <= pd.Timestamp(train_end)
    train_labels = labels[train_mask]
    train_data = df_data[train_mask]

    # Find optimal weight per regime in training period
    optimal_weights = {}
    for regime in unique_labels:
        regime_mask = train_labels == regime
        if regime_mask.sum() < 50:  # need enough obs
            optimal_weights[regime] = 0.5
            continue

        regime_returns = train_data.loc[regime_mask, 'spy_return']
        best_sharpe = -np.inf
        best_w = 0.5
        for w in np.arange(0.0, 1.05, 0.05):
            strat_ret = w * regime_returns
            if strat_ret.std() > 0:
                s = strat_ret.mean() / strat_ret.std() * np.sqrt(252)
                if s > best_sharpe:
                    best_sharpe = s
                    best_w = w
        optimal_weights[regime] = best_w

    # OOS backtest
    oos_mask = df_data.index > pd.Timestamp(train_end)
    bt = df_data[oos_mask].copy()
    bt_labels = labels[oos_mask]

    bt['weight'] = [optimal_weights.get(l, 0.5) for l in bt_labels]
    bt['strategy_return'] = bt['weight'].shift(1) * bt['spy_return']
    bt = bt.dropna()

    if len(bt) < 100:
        return None

    cum_strat = (1 + bt['strategy_return']).cumprod()
    n_years = len(bt) / 252
    cagr = float(cum_strat.iloc[-1] ** (1 / n_years) - 1)
    vol = float(bt['strategy_return'].std() * np.sqrt(252))
    sharpe = cagr / (vol + 1e-8)

    rolling_max = cum_strat.cummax()
    drawdown = (cum_strat - rolling_max) / rolling_max
    mdd = float(drawdown.min())

    return {
        'cagr': cagr,
        'vol': vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'optimal_weights': {int(k): float(v) for k, v in optimal_weights.items()},
        'n_days': len(bt),
        'oos_period': f"{bt.index[0].strftime('%Y-%m-%d')} to {bt.index[-1].strftime('%Y-%m-%d')}",
        'returns': bt['strategy_return'],
    }

# Run backtests
print("\n  Baseline: Standard 12/VIX")
fixed_bt = backtest_12vix_fixed(df)
print(f"    CAGR={fixed_bt['cagr']*100:.1f}%, Vol={fixed_bt['vol']*100:.1f}%, "
      f"Sharpe={fixed_bt['sharpe']:.2f}, MDD={fixed_bt['mdd']*100:.1f}%")

econ_results = {'baseline_12vix': {k: v for k, v in fixed_bt.items() if k != 'returns'}}

# Test each clustering method
for method_name, method_labels in [
    (f'kmeans_k{best_k_km}', km_labels),
    (f'gmm_k{best_k_gmm_bic}', gmm_labels),
]:
    print(f"\n  Cluster-based: {method_name}")

    # Method 1: 12/regime_mean_VIX
    cb = backtest_cluster_based(df, method_labels)
    print(f"    12/regime_mean_VIX: CAGR={cb['cagr']*100:.1f}%, Vol={cb['vol']*100:.1f}%, "
          f"Sharpe={cb['sharpe']:.2f}, MDD={cb['mdd']*100:.1f}%")
    econ_results[f'{method_name}_regime_mean'] = {k: v for k, v in cb.items() if k != 'returns'}

    # Method 2: Regime-optimal (IS/OOS)
    co = backtest_cluster_optimal(df, method_labels)
    if co is not None:
        print(f"    Regime-optimal (OOS): CAGR={co['cagr']*100:.1f}%, Vol={co['vol']*100:.1f}%, "
              f"Sharpe={co['sharpe']:.2f}, MDD={co['mdd']*100:.1f}%")
        econ_results[f'{method_name}_optimal'] = {k: v for k, v in co.items() if k != 'returns'}

# HMM-based backtest
if hmm_available:
    for n_states in [2, 3]:
        if n_states in hmm_results and hmm_results[n_states].get('converged', False):
            hmm_labels_arr = hmm_results[n_states]['labels']
            method_name = f'hmm_{n_states}state'
            print(f"\n  Cluster-based: {method_name}")

            cb = backtest_cluster_based(df, hmm_labels_arr)
            print(f"    12/regime_mean_VIX: CAGR={cb['cagr']*100:.1f}%, Vol={cb['vol']*100:.1f}%, "
                  f"Sharpe={cb['sharpe']:.2f}, MDD={cb['mdd']*100:.1f}%")
            econ_results[f'{method_name}_regime_mean'] = {k: v for k, v in cb.items() if k != 'returns'}

            co = backtest_cluster_optimal(df, hmm_labels_arr)
            if co is not None:
                print(f"    Regime-optimal (OOS): CAGR={co['cagr']*100:.1f}%, Vol={co['vol']*100:.1f}%, "
                      f"Sharpe={co['sharpe']:.2f}, MDD={co['mdd']*100:.1f}%")
                econ_results[f'{method_name}_optimal'] = {k: v for k, v in co.items() if k != 'returns'}

# ============================================================
# 12. Statistical Comparison (DM-like test)
# ============================================================
print("\n[12] Statistical Comparison: Cluster vs Fixed 12/VIX")

# Compare returns series where available
baseline_returns = fixed_bt['returns']

dm_test_results = {}
for method_name, method_labels in [
    (f'kmeans_k{best_k_km}', km_labels),
    (f'gmm_k{best_k_gmm_bic}', gmm_labels),
]:
    cb = backtest_cluster_based(df, method_labels)
    cb_returns = cb['returns']

    # Align returns
    common_idx = baseline_returns.index.intersection(cb_returns.index)
    r_base = baseline_returns.loc[common_idx]
    r_clust = cb_returns.loc[common_idx]

    # Difference in squared returns (loss differential for variance comparison)
    diff = r_clust - r_base  # return difference
    t_stat, p_val = stats.ttest_1samp(diff, 0)

    dm_test_results[method_name] = {
        'mean_diff': float(diff.mean()),
        'mean_diff_ann': float(diff.mean() * 252),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'n_obs': len(common_idx),
        'significant_5pct': bool(p_val < 0.05),
    }
    print(f"  {method_name} vs 12/VIX: mean_diff_ann={diff.mean()*252*100:.2f}%, "
          f"t={t_stat:.3f}, p={p_val:.4f}")

# ============================================================
# 13. Key Questions Summary
# ============================================================
print("\n[13] Summary: Key Questions")

# Q1: How many regimes?
print("\n  Q1: How many regimes does the data suggest?")
print(f"    K-Means best k (silhouette): {best_k_km}")
print(f"    GMM best k (BIC): {best_k_gmm_bic}")
print(f"    GMM best k (silhouette): {best_k_gmm_sil}")

# Collect all silhouette scores for comparison
all_sil = {}
for k in range(2, 6):
    all_sil[f'kmeans_k{k}'] = kmeans_results[k]['silhouette']
    all_sil[f'gmm_k{k}'] = gmm_results[k]['silhouette']
if hmm_available:
    for n in [2, 3]:
        if n in hmm_results and 'silhouette' in hmm_results[n]:
            all_sil[f'hmm_{n}state'] = hmm_results[n]['silhouette']
all_sil['fixed_threshold'] = fixed_sil
print(f"\n    All silhouette scores: {json.dumps({k: round(v, 4) for k, v in all_sil.items()}, indent=6)}")

# Q2: Do data-driven regimes match intuitive brackets?
print("\n  Q2: Do data-driven regimes match intuitive brackets?")
# This is answered by the overlap analysis in section 10

# Q3: VIX-only vs multivariate?
print("\n  Q3: VIX-only vs multivariate regimes?")
# Compare fixed (VIX-only) vs K-Means/GMM (multivariate) silhouette
print(f"    Fixed threshold (VIX-only) silhouette: {fixed_sil:.4f}")
print(f"    K-Means k={best_k_km} (multivariate) silhouette: {kmeans_results[best_k_km]['silhouette']:.4f}")
print(f"    GMM k={best_k_gmm_bic} (multivariate) silhouette: {gmm_results[best_k_gmm_bic]['silhouette']:.4f}")

multivariate_better = (
    kmeans_results[best_k_km]['silhouette'] > fixed_sil or
    gmm_results[best_k_gmm_bic]['silhouette'] > fixed_sil
)
print(f"    Multivariate better than VIX-only? {multivariate_better}")

# ============================================================
# 14. Also test k=4 specifically for fair comparison with fixed
# ============================================================
print("\n[14] Fair Comparison: k=4 methods vs 4-bracket fixed")
for method_name, results_dict in [('kmeans', kmeans_results), ('gmm', gmm_results)]:
    if 4 in results_dict:
        k4_sil = results_dict[4]['silhouette']
        print(f"  {method_name} k=4 silhouette: {k4_sil:.4f} vs fixed: {fixed_sil:.4f} "
              f"({'better' if k4_sil > fixed_sil else 'worse'})")

# ============================================================
# 15. Save Results
# ============================================================
print("\n[15] Saving results...")

results = {
    'experiment_id': 'K637',
    'title': 'Volatility Regime Identification via Unsupervised Clustering',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': len(df),
    'analysis_type': 'empirical',
    'references': [
        'Hamilton (1989) - HMM regime switching',
        'Ang & Bekaert (2002) - Regime switches in finance, JFE',
        'Guidolin & Timmermann (2007) - Multi-regime asset allocation, JEE',
    ],
    'features_used': feature_cols,
    'descriptive_statistics': desc_stats,
    'kmeans_results': {
        str(k): {key: val for key, val in v.items() if key != 'labels'}
        for k, v in kmeans_results.items()
    },
    'gmm_results': {
        str(k): {key: val for key, val in v.items() if key != 'labels'}
        for k, v in gmm_results.items()
    },
    'hmm_results': {
        str(k): {key: val for key, val in v.items() if key != 'labels'}
        for k, v in hmm_results.items()
    } if hmm_available else {'note': 'hmmlearn not available'},
    'fixed_threshold': {
        'brackets': '0-15, 15-20, 20-30, 30+',
        'silhouette': fixed_sil,
    },
    'best_k': {
        'kmeans_silhouette': best_k_km,
        'gmm_bic': best_k_gmm_bic,
        'gmm_silhouette': best_k_gmm_sil,
    },
    'regime_characteristics': regime_chars,
    'transition_analysis': transition_results,
    'vix_overlap_analysis': overlap_results,
    'economic_test': econ_results,
    'statistical_comparison': dm_test_results,
    'all_silhouette_scores': {k: round(v, 4) for k, v in all_sil.items()},
    'key_findings': {
        'suggested_n_regimes': {
            'kmeans': best_k_km,
            'gmm_bic': best_k_gmm_bic,
            'gmm_silhouette': best_k_gmm_sil,
        },
        'multivariate_vs_vix_only': {
            'fixed_sil': float(fixed_sil),
            'best_multivariate_sil': float(max(
                kmeans_results[best_k_km]['silhouette'],
                gmm_results[best_k_gmm_bic]['silhouette']
            )),
            'multivariate_adds_value': multivariate_better,
        },
        'cluster_beat_fixed_12vix': {
            method: {
                'sharpe_cluster': r['sharpe'],
                'sharpe_fixed': econ_results['baseline_12vix']['sharpe'],
                'improvement': r['sharpe'] - econ_results['baseline_12vix']['sharpe'],
            }
            for method, r in econ_results.items() if method != 'baseline_12vix'
        },
    },
    'limitations': [
        'Clustering is in-sample — regimes identified on full dataset including future data',
        'HMM forward-filtering would be needed for true OOS regime identification',
        'Economic test uses simplified weight mapping, not fully optimized allocation',
        'Regime identification may be unstable with different rolling windows',
        'VRP proxy (VIX/RV) is crude — proper VRP requires options data',
    ],
}

# Save
output_path = 'experiments/k637_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Saved to {output_path}")

# ============================================================
# Final Summary
# ============================================================
print("\n" + "=" * 70)
print("FINAL SUMMARY")
print("=" * 70)
print(f"\n  Data: {len(df)} observations, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"\n  Best number of regimes:")
print(f"    K-Means (silhouette): k={best_k_km}")
print(f"    GMM (BIC): k={best_k_gmm_bic}")
print(f"    GMM (silhouette): k={best_k_gmm_sil}")
print(f"\n  Fixed threshold silhouette: {fixed_sil:.4f}")
print(f"  Best multivariate silhouette: {max(kmeans_results[best_k_km]['silhouette'], gmm_results[best_k_gmm_bic]['silhouette']):.4f}")
print(f"  Multivariate adds value? {multivariate_better}")
print(f"\n  12/VIX baseline Sharpe: {econ_results['baseline_12vix']['sharpe']:.3f}")
for method, r in econ_results.items():
    if method != 'baseline_12vix':
        delta = r['sharpe'] - econ_results['baseline_12vix']['sharpe']
        print(f"  {method}: Sharpe={r['sharpe']:.3f} (delta={delta:+.3f})")
print("\n  Done!")
