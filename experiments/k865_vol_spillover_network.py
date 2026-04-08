"""
K865: Volatility Spillover Network — 2026 Tariff Crisis Update

Research Questions:
1. Has the vol spillover network become MORE connected during the tariff crisis?
2. Which assets are the biggest vol transmitters vs receivers in 2026?
3. Does the network structure predict the severity of the tariff sell-off?

Methodology: Diebold-Yilmaz (2012) spillover framework
- VAR(5) on realized volatilities
- Forecast Error Variance Decomposition (FEVD) h=10
- Total Spillover Index = off-diagonal / total × 100
- Rolling 63-day windows for temporal evolution

References:
- Diebold & Yilmaz (2012) "Better to Give than to Receive: Predictive Directional
  Measurement of Volatility Spillovers", IJF 28(1), 57-66
- K7: Vol spillover Granger network — SPY hub, TW50 most affected
- K356: Vol causal directed graph — SPY+TLT output vol, OIL absorbs
- K422: Commodity vol spillover

Data: yfinance, 2020-01 to 2026-04
Assets: SPY, QQQ, GLD, TLT, EEM, CL=F, BTC-USD

Error log rules applied:
- Sanity check: compute actual values, never hard-code
- Harvey threshold |t| > 3.0
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import grangercausalitytests
from scipy import stats

warnings.filterwarnings('ignore')

# ── Configuration ──
ASSETS = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'CL=F', 'BTC-USD']
ASSET_LABELS = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'OIL', 'BTC']
START_DATE = '2020-01-01'
END_DATE = '2026-04-05'
RV_WINDOW = 22  # 22-day rolling std for realized vol
VAR_LAGS = 5
FEVD_HORIZON = 10
ROLLING_WINDOW = 63  # ~3 months

# Time windows for comparison
WINDOWS = {
    'covid_crisis': ('2020-01-02', '2020-06-30'),
    'post_covid_recovery': ('2020-07-01', '2021-12-31'),
    'rate_hike': ('2022-01-01', '2023-06-30'),
    'calm_2024_25': ('2024-01-01', '2026-02-28'),
    'tariff_crisis_narrow': ('2026-03-01', '2026-04-04'),  # 34 obs, too short for VAR
    'tariff_crisis_extended': ('2025-10-01', '2026-04-04'),  # ~130 obs, enough for VAR
}


def download_data():
    """Download price data for all assets."""
    print("Downloading data...")
    data = {}
    for asset, label in zip(ASSETS, ASSET_LABELS):
        try:
            df = yf.download(asset, start=START_DATE, end=END_DATE, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            data[label] = df['Close']
            print(f"  {label}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        except Exception as e:
            print(f"  {label}: FAILED - {e}")

    prices = pd.DataFrame(data)
    prices = prices.ffill().dropna()
    print(f"Combined: {len(prices)} obs after alignment")
    return prices


def compute_realized_vol(prices, window=RV_WINDOW):
    """Compute annualized realized volatility (22-day rolling std of log returns).
    Then Z-score standardize each series to remove scale differences (BTC >> SPY).
    """
    log_returns = np.log(prices / prices.shift(1))
    rv = log_returns.rolling(window).std() * np.sqrt(252)
    rv = rv.dropna()

    # Store raw RV for reporting
    rv_raw = rv.copy()

    # Z-score standardize each asset's RV for VAR analysis
    # This prevents BTC (40-50% vol) from dominating SPY (15-20% vol)
    rv_standardized = (rv - rv.mean()) / rv.std()

    return rv_standardized, rv_raw


def fit_var_fevd(rv_data, lags=VAR_LAGS, horizon=FEVD_HORIZON):
    """
    Fit VAR model and compute FEVD-based spillover table.
    Returns spillover matrix where entry (i,j) = contribution of j to i's FEV.
    """
    model = VAR(rv_data)
    try:
        results = model.fit(maxlags=lags, ic=None)
    except Exception as e:
        print(f"  VAR fit failed: {e}")
        return None, None

    fevd = results.fevd(horizon)
    # fevd.decomp is (horizon, n, n) — we want the final horizon step
    # Each row i: how much of asset i's FEV is explained by shocks to each asset j
    spillover_matrix = fevd.decomp[-1]  # shape (n, n)

    # Normalize rows to sum to 100
    row_sums = spillover_matrix.sum(axis=1, keepdims=True)
    spillover_matrix = (spillover_matrix / row_sums) * 100

    return spillover_matrix, results


def compute_spillover_metrics(spillover_matrix, labels):
    """
    Compute Diebold-Yilmaz spillover metrics from FEVD matrix.

    spillover_matrix[i,j] = % of asset i's FEV due to shock from j
    """
    n = len(labels)

    # Total Spillover Index: sum of off-diagonal / total * 100
    total = spillover_matrix.sum()
    diagonal = np.trace(spillover_matrix)
    off_diagonal = total - diagonal
    total_spillover_index = off_diagonal / total * 100

    # FROM others: how much of asset i's FEV comes from OTHER assets
    from_others = {}
    for i, label in enumerate(labels):
        from_val = sum(spillover_matrix[i, j] for j in range(n) if j != i)
        from_others[label] = round(float(from_val), 2)

    # TO others: how much asset j contributes to OTHER assets' FEV
    to_others = {}
    for j, label in enumerate(labels):
        to_val = sum(spillover_matrix[i, j] for i in range(n) if i != j)
        to_others[label] = round(float(to_val), 2)

    # NET spillover: TO - FROM (positive = net transmitter)
    net_spillover = {}
    for label in labels:
        net_spillover[label] = round(to_others[label] - from_others[label], 2)

    # Pairwise spillover table
    pairwise = {}
    for i, li in enumerate(labels):
        for j, lj in enumerate(labels):
            if i != j:
                pairwise[f"{lj}->{li}"] = round(float(spillover_matrix[i, j]), 2)

    return {
        'total_spillover_index': round(float(total_spillover_index), 2),
        'from_others': from_others,
        'to_others': to_others,
        'net_spillover': net_spillover,
        'top_transmitters': sorted(net_spillover.items(), key=lambda x: -x[1])[:3],
        'top_receivers': sorted(net_spillover.items(), key=lambda x: x[1])[:3],
    }


def compute_rolling_spillover(rv_data, labels, window=ROLLING_WINDOW,
                                lags=VAR_LAGS, horizon=FEVD_HORIZON):
    """Compute rolling total spillover index."""
    dates = []
    spillover_indices = []

    n_obs = len(rv_data)
    print(f"  Computing rolling spillover ({n_obs - window} windows)...")

    for end in range(window, n_obs, 5):  # step=5 for speed
        window_data = rv_data.iloc[end-window:end]

        try:
            sm, _ = fit_var_fevd(window_data, lags=min(lags, window//10), horizon=horizon)
            if sm is not None:
                total = sm.sum()
                diagonal = np.trace(sm)
                tsi = (total - diagonal) / total * 100
                dates.append(rv_data.index[end-1])
                spillover_indices.append(float(tsi))
        except:
            pass

    return pd.Series(spillover_indices, index=dates, name='Total_Spillover_Index')


def granger_causality_test(rv_data, labels, maxlag=5):
    """Pairwise Granger causality tests."""
    results = {}
    n = len(labels)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            pair = f"{labels[j]}->{labels[i]}"
            try:
                test_data = rv_data[[labels[i], labels[j]]].dropna()
                if len(test_data) < 50:
                    results[pair] = {'p_value': None, 'significant': False, 'note': 'insufficient data'}
                    continue
                gc = grangercausalitytests(test_data, maxlag=maxlag, verbose=False)
                # Get minimum p-value across all lags
                min_p = min(gc[lag][0]['ssr_ftest'][1] for lag in range(1, maxlag+1))
                results[pair] = {
                    'p_value': round(float(min_p), 6),
                    'significant_005': min_p < 0.05,
                    'significant_001': min_p < 0.01,
                }
            except Exception as e:
                results[pair] = {'p_value': None, 'significant': False, 'note': str(e)[:50]}

    return results


def analyze_window(rv_data, labels, window_name, start, end):
    """Full analysis for a given time window."""
    print(f"\n{'='*60}")
    print(f"Window: {window_name} ({start} to {end})")
    print(f"{'='*60}")

    mask = (rv_data.index >= start) & (rv_data.index <= end)
    window_rv = rv_data.loc[mask].copy()
    n_obs = len(window_rv)
    print(f"  Observations: {n_obs}")

    if n_obs < 50:
        print(f"  WARNING: Only {n_obs} obs — too few for VAR(5). Skipping FEVD.")
        # Still compute descriptive stats
        desc = {}
        for label in labels:
            if label in window_rv.columns:
                desc[label] = {
                    'mean_rv': round(float(window_rv[label].mean()), 4),
                    'max_rv': round(float(window_rv[label].max()), 4),
                    'std_rv': round(float(window_rv[label].std()), 4),
                }
        return {
            'window': window_name,
            'period': f"{start} to {end}",
            'n_obs': n_obs,
            'descriptive_stats': desc,
            'note': 'Too few observations for VAR/FEVD analysis',
        }

    # Descriptive statistics of RV
    desc = {}
    for label in labels:
        if label in window_rv.columns:
            desc[label] = {
                'mean_rv': round(float(window_rv[label].mean()), 4),
                'max_rv': round(float(window_rv[label].max()), 4),
                'std_rv': round(float(window_rv[label].std()), 4),
            }

    # VAR + FEVD spillover
    sm, var_results = fit_var_fevd(window_rv, lags=min(VAR_LAGS, n_obs // 15), horizon=FEVD_HORIZON)

    if sm is None:
        return {
            'window': window_name,
            'period': f"{start} to {end}",
            'n_obs': n_obs,
            'descriptive_stats': desc,
            'note': 'VAR fitting failed',
        }

    spillover_metrics = compute_spillover_metrics(sm, labels)

    # Granger causality
    gc_results = granger_causality_test(window_rv, labels, maxlag=min(5, n_obs // 15))
    sig_gc = {k: v for k, v in gc_results.items() if v.get('significant_005', False)}

    print(f"  Total Spillover Index: {spillover_metrics['total_spillover_index']:.1f}%")
    print(f"  Top transmitters: {spillover_metrics['top_transmitters']}")
    print(f"  Top receivers: {spillover_metrics['top_receivers']}")
    print(f"  Significant Granger pairs (p<0.05): {len(sig_gc)}/{len(gc_results)}")

    return {
        'window': window_name,
        'period': f"{start} to {end}",
        'n_obs': n_obs,
        'descriptive_stats': desc,
        'spillover': spillover_metrics,
        'granger_causality': {
            'total_pairs': len(gc_results),
            'significant_005': len(sig_gc),
            'significant_pairs': {k: v for k, v in sorted(sig_gc.items(), key=lambda x: x[1].get('p_value', 1))},
        },
        'spillover_matrix': [[round(float(sm[i,j]), 2) for j in range(len(labels))] for i in range(len(labels))],
        'matrix_labels': labels,
    }


def compute_tariff_impact_severity(prices, rv_raw):
    """Measure the severity of the tariff crisis sell-off."""
    # Use March as pre-tariff reference, look at late March + early April
    results = {}

    # Daily returns in the tariff announcement week
    log_returns = np.log(prices / prices.shift(1))

    # Tariff announcement was April 2, 2026 — look at March 31 to latest
    for window_name, (ws, we) in [
        ('march_2026', ('2026-03-01', '2026-03-31')),
        ('tariff_week', ('2026-03-31', '2026-04-04')),
        ('full_tariff_period', ('2026-03-01', '2026-04-04')),
    ]:
        mask = (prices.index >= ws) & (prices.index <= we)
        window_prices = prices.loc[mask]
        if len(window_prices) >= 2:
            rets = {}
            for col in window_prices.columns:
                total_return = (window_prices[col].iloc[-1] / window_prices[col].iloc[0]) - 1
                rets[col] = round(float(total_return) * 100, 2)
            results[f'{window_name}_returns_pct'] = rets

    # Max RV during tariff crisis (use RAW RV, not standardized)
    tariff_mask = (rv_raw.index >= '2026-03-01') & (rv_raw.index <= '2026-04-04')
    tariff_rv = rv_raw.loc[tariff_mask]
    max_rv = {}
    mean_rv = {}
    for col in tariff_rv.columns:
        max_rv[col] = round(float(tariff_rv[col].max()), 4)
        mean_rv[col] = round(float(tariff_rv[col].mean()), 4)

    # Compare with calm period RV
    calm_mask = (rv_raw.index >= '2024-01-01') & (rv_raw.index <= '2026-02-28')
    calm_rv = rv_raw.loc[calm_mask]
    rv_ratio = {}
    for col in calm_rv.columns:
        calm_mean = calm_rv[col].mean()
        tariff_mean = tariff_rv[col].mean() if col in tariff_rv.columns else 0
        rv_ratio[col] = round(float(tariff_mean / calm_mean), 2) if calm_mean > 0 else None

    results['max_rv_tariff_period'] = max_rv
    results['mean_rv_tariff_period'] = mean_rv
    results['rv_ratio_tariff_vs_calm'] = rv_ratio

    # Worst single-day returns during March-April 2026
    mar_apr_mask = (log_returns.index >= '2026-03-01') & (log_returns.index <= '2026-04-04')
    mar_apr_rets = log_returns.loc[mar_apr_mask]
    worst_days = {}
    for col in mar_apr_rets.columns:
        worst_idx = mar_apr_rets[col].idxmin()
        worst_days[col] = {
            'date': worst_idx.strftime('%Y-%m-%d'),
            'return_pct': round(float(mar_apr_rets[col].min()) * 100, 2),
        }
    results['worst_single_day'] = worst_days

    return results


def compare_crisis_networks(results_dict):
    """Compare network metrics across crisis periods."""
    comparison = {}
    for window_name, res in results_dict.items():
        if 'spillover' in res:
            comparison[window_name] = {
                'total_spillover_index': res['spillover']['total_spillover_index'],
                'n_significant_granger': res['granger_causality']['significant_005'],
                'top_transmitter': res['spillover']['top_transmitters'][0] if res['spillover']['top_transmitters'] else None,
                'top_receiver': res['spillover']['top_receivers'][0] if res['spillover']['top_receivers'] else None,
            }
    return comparison


# ── Main Execution ──
if __name__ == '__main__':
    start_time = datetime.now()
    print("K865: Volatility Spillover Network — 2026 Tariff Crisis Update")
    print("=" * 70)

    # 1. Download data
    prices = download_data()

    # 2. Compute realized volatility (standardized for VAR + raw for reporting)
    print("\nComputing realized volatility (22-day rolling, z-score standardized for VAR)...")
    rv, rv_raw = compute_realized_vol(prices)
    print(f"RV series: {len(rv)} obs, {rv.index[0].strftime('%Y-%m-%d')} to {rv.index[-1].strftime('%Y-%m-%d')}")

    # Available labels (intersection with actual data)
    available_labels = [l for l in ASSET_LABELS if l in rv.columns]
    rv_clean = rv[available_labels].dropna()
    rv_raw_clean = rv_raw[available_labels].dropna()
    print(f"Using {len(available_labels)} assets: {available_labels}")
    print(f"Clean RV: {len(rv_clean)} obs")

    # Report raw RV stats for context
    print("\nRaw RV summary (annualized):")
    for label in available_labels:
        print(f"  {label}: mean={rv_raw_clean[label].mean():.3f}, "
              f"max={rv_raw_clean[label].max():.3f}, "
              f"latest={rv_raw_clean[label].iloc[-1]:.3f}")

    # 3. Analyze each time window
    window_results = {}
    for wname, (ws, we) in WINDOWS.items():
        window_results[wname] = analyze_window(rv_clean, available_labels, wname, ws, we)

    # 4. Rolling spillover index (full sample)
    print("\n" + "=" * 60)
    print("Computing rolling 63-day spillover index (full sample)...")
    rolling_tsi = compute_rolling_spillover(rv_clean, available_labels, window=ROLLING_WINDOW)
    print(f"  Computed {len(rolling_tsi)} rolling windows")

    # Key statistics of rolling TSI
    rolling_stats = {
        'mean': round(float(rolling_tsi.mean()), 2),
        'std': round(float(rolling_tsi.std()), 2),
        'min': round(float(rolling_tsi.min()), 2),
        'max': round(float(rolling_tsi.max()), 2),
        'min_date': rolling_tsi.idxmin().strftime('%Y-%m-%d'),
        'max_date': rolling_tsi.idxmax().strftime('%Y-%m-%d'),
    }

    # Recent values (2026)
    recent_mask = rolling_tsi.index >= '2026-01-01'
    if recent_mask.any():
        recent_tsi = rolling_tsi[recent_mask]
        rolling_stats['mean_2026'] = round(float(recent_tsi.mean()), 2)
        rolling_stats['max_2026'] = round(float(recent_tsi.max()), 2)
        rolling_stats['max_date_2026'] = recent_tsi.idxmax().strftime('%Y-%m-%d')
        rolling_stats['latest'] = round(float(recent_tsi.iloc[-1]), 2)
        rolling_stats['latest_date'] = recent_tsi.index[-1].strftime('%Y-%m-%d')

    print(f"  Full-sample mean TSI: {rolling_stats['mean']:.1f}%")
    print(f"  Full-sample max TSI: {rolling_stats['max']:.1f}% ({rolling_stats['max_date']})")
    if 'latest' in rolling_stats:
        print(f"  Latest TSI: {rolling_stats['latest']:.1f}% ({rolling_stats['latest_date']})")

    # 5. Tariff impact severity (use raw RV for interpretability)
    print("\n" + "=" * 60)
    print("Tariff crisis impact severity...")
    tariff_impact = compute_tariff_impact_severity(prices, rv_raw_clean)
    if tariff_impact:
        for key in ['march_2026_returns_pct', 'tariff_week_returns_pct', 'full_tariff_period_returns_pct']:
            if key in tariff_impact:
                print(f"  {key}: {tariff_impact[key]}")
        print(f"  Max RV during tariff crisis: {tariff_impact.get('max_rv_tariff_period', {})}")
        print(f"  RV ratio (tariff/calm): {tariff_impact.get('rv_ratio_tariff_vs_calm', {})}")
        print(f"  Worst single days: {tariff_impact.get('worst_single_day', {})}")

    # 6. Compare crisis networks
    print("\n" + "=" * 60)
    print("Comparing crisis network structures...")
    crisis_comparison = compare_crisis_networks(window_results)
    for wname, comp in crisis_comparison.items():
        print(f"  {wname}: TSI={comp['total_spillover_index']:.1f}%, "
              f"Granger pairs={comp['n_significant_granger']}, "
              f"Top TX={comp['top_transmitter']}, Top RX={comp['top_receiver']}")

    # 7. Network connectivity change test
    # Compare calm period vs tariff crisis Granger connectivity
    calm = window_results.get('calm_2024_25', {})
    tariff = window_results.get('tariff_crisis_extended', {})

    connectivity_change = {}
    if 'granger_causality' in calm and 'spillover' in tariff:
        calm_sig = calm['granger_causality']['significant_005']
        calm_total = calm['granger_causality']['total_pairs']

        # For tariff (if available)
        if 'granger_causality' in tariff:
            tariff_sig = tariff['granger_causality']['significant_005']
            tariff_total = tariff['granger_causality']['total_pairs']

            connectivity_change = {
                'calm_granger_fraction': round(calm_sig / calm_total, 3) if calm_total > 0 else None,
                'tariff_granger_fraction': round(tariff_sig / tariff_total, 3) if tariff_total > 0 else None,
                'calm_tsi': calm['spillover']['total_spillover_index'] if 'spillover' in calm else None,
                'tariff_tsi': tariff['spillover']['total_spillover_index'] if 'spillover' in tariff else None,
            }

    # If tariff window too short, compare using rolling values
    if 'mean_2026' in rolling_stats:
        # Get calm period rolling TSI
        calm_mask = (rolling_tsi.index >= '2024-01-01') & (rolling_tsi.index <= '2026-02-28')
        if calm_mask.any():
            calm_tsi_rolling = rolling_tsi[calm_mask]
            tariff_mask_r = rolling_tsi.index >= '2026-03-01'
            tariff_tsi_rolling = rolling_tsi[tariff_mask_r]

            if len(calm_tsi_rolling) > 10 and len(tariff_tsi_rolling) > 2:
                # t-test: is tariff TSI significantly higher?
                t_stat, p_val = stats.ttest_ind(tariff_tsi_rolling.values, calm_tsi_rolling.values,
                                                 alternative='greater')
                connectivity_change['rolling_tsi_ttest'] = {
                    'calm_mean': round(float(calm_tsi_rolling.mean()), 2),
                    'tariff_mean': round(float(tariff_tsi_rolling.mean()), 2),
                    'calm_n': len(calm_tsi_rolling),
                    'tariff_n': len(tariff_tsi_rolling),
                    't_stat': round(float(t_stat), 3),
                    'p_value': round(float(p_val), 6),
                    'significant_harvey': abs(t_stat) > 3.0,
                }
                print(f"\n  Rolling TSI t-test (tariff > calm): t={t_stat:.3f}, p={p_val:.6f}")
                print(f"    Calm mean: {calm_tsi_rolling.mean():.1f}%, Tariff mean: {tariff_tsi_rolling.mean():.1f}%")

    # 8. Robustness: repeat key analysis WITHOUT BTC (traditional asset network)
    print("\n" + "=" * 60)
    print("ROBUSTNESS: Traditional asset network (excluding BTC)...")
    trad_labels = [l for l in available_labels if l != 'BTC']
    rv_trad = rv_clean[trad_labels].dropna()

    trad_results = {}
    for wname in ['covid_crisis', 'calm_2024_25', 'tariff_crisis_extended']:
        ws, we = WINDOWS[wname]
        mask = (rv_trad.index >= ws) & (rv_trad.index <= we)
        window_rv = rv_trad.loc[mask]
        if len(window_rv) >= 50:
            sm, _ = fit_var_fevd(window_rv, lags=min(VAR_LAGS, len(window_rv)//15),
                                  horizon=FEVD_HORIZON)
            if sm is not None:
                metrics = compute_spillover_metrics(sm, trad_labels)
                trad_results[wname] = metrics
                print(f"  {wname}: TSI={metrics['total_spillover_index']:.1f}%, "
                      f"Top TX={metrics['top_transmitters'][0]}, "
                      f"Top RX={metrics['top_receivers'][0]}")

    # 9. RV correlation matrix comparison (tariff narrow window vs calm)
    print("\n" + "=" * 60)
    print("RV correlation matrices by period...")

    rv_corr_by_period = {}
    for wname in ['calm_2024_25', 'tariff_crisis_narrow', 'tariff_crisis_extended']:
        ws, we = WINDOWS[wname]
        mask = (rv_raw_clean.index >= ws) & (rv_raw_clean.index <= we)
        window_rv = rv_raw_clean.loc[mask]
        if len(window_rv) >= 10:
            corr = window_rv.corr()
            rv_corr_by_period[wname] = {
                f"{i}-{j}": round(float(corr.loc[i, j]), 3)
                for i in trad_labels for j in trad_labels if i < j
            }
            # Mean off-diagonal correlation
            mask_upper = np.triu(np.ones(corr.shape), k=1).astype(bool)
            mean_corr = corr.values[mask_upper].mean()
            rv_corr_by_period[wname]['mean_offdiag'] = round(float(mean_corr), 3)
            print(f"  {wname}: mean off-diag RV corr = {mean_corr:.3f} (n={len(window_rv)})")

    # 10. SPY role change analysis
    print("\n" + "=" * 60)
    print("SPY role change analysis (transmitter vs receiver)...")
    spy_role = {}
    for wname, res in window_results.items():
        if 'spillover' in res:
            net = res['spillover']['net_spillover'].get('SPY', 0)
            spy_role[wname] = {
                'net_spillover': net,
                'role': 'transmitter' if net > 0 else 'receiver',
                'to_others': res['spillover']['to_others'].get('SPY', 0),
                'from_others': res['spillover']['from_others'].get('SPY', 0),
            }
            print(f"  {wname}: SPY net={net:.1f} ({spy_role[wname]['role']})")

    # 11. Rolling TSI as time series for charting (sample every 5th point)
    rolling_tsi_series = {
        d.strftime('%Y-%m-%d'): round(float(v), 2)
        for d, v in rolling_tsi.items()
    }

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'='*70}")
    print(f"Total runtime: {elapsed:.1f}s")

    # ── Compile Results ──
    results = {
        'experiment_id': 'K865',
        'title': 'Volatility Spillover Network — 2026 Tariff Crisis Update',
        'methodology': 'Diebold-Yilmaz (2012) FEVD spillover + Granger causality',
        'data_source': 'yfinance',
        'assets': available_labels,
        'period': f"{rv_clean.index[0].strftime('%Y-%m-%d')} to {rv_clean.index[-1].strftime('%Y-%m-%d')}",
        'total_observations': len(rv_clean),
        'parameters': {
            'rv_window': RV_WINDOW,
            'var_lags': VAR_LAGS,
            'fevd_horizon': FEVD_HORIZON,
            'rolling_window': ROLLING_WINDOW,
        },
        'window_analysis': window_results,
        'rolling_spillover_stats': rolling_stats,
        'tariff_impact': tariff_impact,
        'crisis_comparison': crisis_comparison,
        'connectivity_change': connectivity_change,
        'traditional_asset_network': trad_results,
        'rv_correlation_by_period': rv_corr_by_period,
        'spy_role_change': spy_role,
        'rolling_tsi_series': rolling_tsi_series,
        'runtime_seconds': round(elapsed, 1),
        'references': [
            'Diebold & Yilmaz (2012) IJF 28(1)',
            'K7: Vol spillover Granger network',
            'K356: Vol causal directed graph',
            'K422: Commodity vol spillover',
        ],
        'timestamp': datetime.now().isoformat(),
    }

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    for wname in ['covid_crisis', 'calm_2024_25', 'tariff_crisis_narrow', 'tariff_crisis_extended']:
        wr = window_results.get(wname, {})
        if 'spillover' in wr:
            sp = wr['spillover']
            print(f"\n{wname}:")
            print(f"  Total Spillover Index: {sp['total_spillover_index']:.1f}%")
            print(f"  Net transmitters: {[(k,v) for k,v in sorted(sp['net_spillover'].items(), key=lambda x: -x[1]) if v > 0]}")
            print(f"  Net receivers: {[(k,v) for k,v in sorted(sp['net_spillover'].items(), key=lambda x: x[1]) if v < 0]}")
        elif 'note' in wr:
            print(f"\n{wname}: {wr['note']}")

    if 'rolling_tsi_ttest' in connectivity_change:
        tt = connectivity_change['rolling_tsi_ttest']
        print(f"\nConnectivity change (rolling TSI):")
        print(f"  Calm (2024-2026.02): {tt['calm_mean']:.1f}% (n={tt['calm_n']})")
        print(f"  Tariff (2026.03+): {tt['tariff_mean']:.1f}% (n={tt['tariff_n']})")
        print(f"  t-stat: {tt['t_stat']:.3f}, p: {tt['p_value']:.6f}")
        print(f"  Harvey |t|>3.0: {'YES' if tt['significant_harvey'] else 'NO'}")

    # Save results
    output_path = 'experiments/k865_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")
