"""
K622: Window Size Sensitivity Sweep — U-shape validation (Feng & Zhang, J.Forecasting 2025)
Reference: Feng, Y. & Zhang, Y. (2025). Forecasting Realized Volatility: The Choice of Window Size.
           Journal of Forecasting.

Prior knowledge:
- K-knowledge: SPY QLIKE varies <0.5% across 126/252/504 (M1/M4 era)
- User insight (2026-03-16): U-shape w/ w=504 local min, w=5000 global min
- K-knowledge: TLT favors w=504, SPY/GLD favor w=2000
- Cross-period sensitivity: avg 0.43%, max 0.73%

This experiment:
- Systematic sweep: w ∈ {252, 504, 750, 1000, 1500, 2000, 2500, 3000}
- Fixed OOS: 2023-01-01 to 2024-12-31
- GJR-GARCH(1,1) with re-estimation every 21 days
- Metrics: QLIKE, MSE, MAE, HMSE
- DM test vs w=2000 baseline
- Bootstrap 95% CI (5000 reps)
- Multi-asset: SPY, GLD, 0050.TW

Data source: yfinance (2000-01-01 to 2026-03-27)
"""

import json
import time
import warnings
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
WINDOW_SIZES = [252, 504, 750, 1000, 1500, 2000, 2500, 3000]
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_INTERVAL = 21  # re-estimate every 21 trading days
BOOTSTRAP_REPS = 5000
BASELINE_WINDOW = 2000
ASSETS = ['SPY', 'GLD', '0050.TW']
DATA_START = '2000-01-01'
DATA_END = '2026-03-27'

# ============================================================
# Data download
# ============================================================
def download_returns(ticker, start, end):
    """Download adjusted close and compute log returns (%)."""
    print(f"  Downloading {ticker} ({start} to {end})...")
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"No data for {ticker}")
    # Handle MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df['Close'].dropna()
    log_ret = 100.0 * np.log(close / close.shift(1)).dropna()
    print(f"    Got {len(log_ret)} returns ({log_ret.index[0].strftime('%Y-%m-%d')} to {log_ret.index[-1].strftime('%Y-%m-%d')})")
    return log_ret


# ============================================================
# Loss functions
# ============================================================
def qlike(sigma2_hat, sigma2_proxy):
    """QLIKE loss: proxy/hat - log(proxy/hat) - 1"""
    ratio = sigma2_proxy / sigma2_hat
    return np.mean(ratio - np.log(ratio) - 1.0)


def mse_loss(sigma2_hat, sigma2_proxy):
    return np.mean((sigma2_hat - sigma2_proxy) ** 2)


def mae_loss(sigma2_hat, sigma2_proxy):
    return np.mean(np.abs(sigma2_hat - sigma2_proxy))


def hmse_loss(sigma2_hat, sigma2_proxy):
    """Heteroscedasticity-adjusted MSE: mean((1 - proxy/hat)^2)"""
    return np.mean((1.0 - sigma2_proxy / sigma2_hat) ** 2)


# ============================================================
# Rolling forecast
# ============================================================
def rolling_forecast(returns, window_size, oos_start, oos_end, refit_interval=21):
    """
    Rolling 1-step ahead GJR-GARCH(1,1) forecast.
    Re-estimates every `refit_interval` days.
    Returns arrays of (sigma2_hat, sigma2_proxy, dates, persistence_list, convergence_list).
    """
    # Locate OOS indices
    oos_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) == 0:
        raise ValueError(f"No OOS data between {oos_start} and {oos_end}")

    first_oos = oos_indices[0]

    # Check if we have enough in-sample data
    if first_oos < window_size:
        available = first_oos
        print(f"    WARNING: Only {available} obs available before OOS, need {window_size}. Skipping.")
        return None

    sigma2_hat_list = []
    sigma2_proxy_list = []
    dates_list = []
    persistence_list = []
    convergence_list = []

    last_model = None
    last_fit_idx = -refit_interval  # force first fit

    for i, oos_idx in enumerate(oos_indices):
        # Determine if we need to refit
        steps_since_fit = oos_idx - last_fit_idx
        if steps_since_fit >= refit_interval or last_model is None:
            # Estimate on window ending just before this OOS point
            train_start = oos_idx - window_size
            train_end = oos_idx  # exclusive: we use returns[train_start:train_end]
            train_data = returns.iloc[train_start:train_end]

            try:
                model = arch_model(train_data, vol='GARCH', p=1, o=1, q=1,
                                   mean='Constant', dist='normal')
                result = model.fit(disp='off', show_warning=False,
                                   options={'maxiter': 500})
                last_model = result
                last_fit_idx = oos_idx

                # Extract persistence: alpha + beta + gamma/2
                params = result.params
                alpha = params.get('alpha[1]', 0)
                beta = params.get('beta[1]', 0)
                gamma = params.get('gamma[1]', 0)
                persistence = alpha + beta + gamma / 2.0
                persistence_list.append(persistence)
                convergence_list.append(1 if result.convergence_flag == 0 else 0)
            except Exception:
                # If estimation fails, keep last model
                if last_model is None:
                    continue

        # Forecast: use last_model to get 1-step ahead variance
        # We need to feed the model the data up to (but not including) oos_idx
        # and get forecast for oos_idx
        try:
            # Re-create model with data up to current point for forecasting
            forecast_data = returns.iloc[oos_idx - window_size:oos_idx]
            model_fc = arch_model(forecast_data, vol='GARCH', p=1, o=1, q=1,
                                  mean='Constant', dist='normal')
            # Apply parameters from last fit
            fc = model_fc.forecast(params=last_model.params, horizon=1,
                                   reindex=False)
            h_hat = fc.variance.values[-1, 0]  # 1-step ahead variance forecast
        except Exception:
            continue

        # Proxy: squared return at oos_idx
        r_oos = returns.iloc[oos_idx]
        sigma2_proxy = r_oos ** 2

        # Skip if proxy is exactly 0 (holiday/no-trade) or forecast is non-positive
        if sigma2_proxy == 0 or h_hat <= 0:
            continue

        sigma2_hat_list.append(h_hat)
        sigma2_proxy_list.append(sigma2_proxy)
        dates_list.append(returns.index[oos_idx])

    return {
        'sigma2_hat': np.array(sigma2_hat_list),
        'sigma2_proxy': np.array(sigma2_proxy_list),
        'dates': dates_list,
        'persistence': persistence_list,
        'convergence': convergence_list,
    }


# ============================================================
# DM test
# ============================================================
def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test. H0: equal predictive ability.
    loss1, loss2: arrays of losses for two competing forecasts.
    Negative t-stat means model 1 is better.
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)
    # Newey-West HAC variance (h-1 lags)
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value


# ============================================================
# Bootstrap CI
# ============================================================
def bootstrap_qlike_ci(sigma2_hat, sigma2_proxy, n_boot=5000, alpha=0.05):
    """Bootstrap 95% CI for QLIKE."""
    n = len(sigma2_hat)
    boot_qlikes = np.empty(n_boot)
    ratio = sigma2_proxy / sigma2_hat
    losses = ratio - np.log(ratio) - 1.0

    rng = np.random.default_rng(42)
    for b in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        boot_qlikes[b] = np.mean(losses[idx])

    ci_lo = np.percentile(boot_qlikes, 100 * alpha / 2)
    ci_hi = np.percentile(boot_qlikes, 100 * (1 - alpha / 2))
    return ci_lo, ci_hi, boot_qlikes


# ============================================================
# Main experiment
# ============================================================
def run_experiment():
    print("=" * 70)
    print("K622: Window Size Sensitivity Sweep")
    print("=" * 70)
    print(f"Window sizes: {WINDOW_SIZES}")
    print(f"OOS period: {OOS_START} to {OOS_END}")
    print(f"Refit interval: {REFIT_INTERVAL} days")
    print(f"Assets: {ASSETS}")
    print(f"Bootstrap reps: {BOOTSTRAP_REPS}")
    print()

    # Download all data
    print("--- Downloading data ---")
    all_returns = {}
    for ticker in ASSETS:
        try:
            ret = download_returns(ticker, DATA_START, DATA_END)
            all_returns[ticker] = ret
        except Exception as e:
            print(f"  ERROR downloading {ticker}: {e}")
    print()

    results = {
        'experiment_id': 'k622',
        'title': 'Window Size Sensitivity Sweep (Feng & Zhang 2025)',
        'reference': 'Feng, Y. & Zhang, Y. (2025). Forecasting Realized Volatility: The Choice of Window Size. Journal of Forecasting.',
        'config': {
            'window_sizes': WINDOW_SIZES,
            'oos_start': OOS_START,
            'oos_end': OOS_END,
            'refit_interval': REFIT_INTERVAL,
            'model': 'GJR-GARCH(1,1)',
            'distribution': 'Normal',
            'proxy': 'squared_returns',
            'baseline_window': BASELINE_WINDOW,
            'bootstrap_reps': BOOTSTRAP_REPS,
        },
        'data_source': 'yfinance',
        'run_date': datetime.now(timezone.utc).isoformat(),
        'assets': {},
    }

    for ticker in ASSETS:
        if ticker not in all_returns:
            results['assets'][ticker] = {'error': 'Data download failed'}
            continue

        returns = all_returns[ticker]
        print(f"{'='*60}")
        print(f"Asset: {ticker} ({len(returns)} obs)")
        print(f"{'='*60}")

        asset_results = {
            'n_total': len(returns),
            'date_range': f"{returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}",
            'windows': {},
        }

        # Store forecasts for DM test later
        window_forecasts = {}

        for w in WINDOW_SIZES:
            t0 = time.time()
            print(f"\n  Window w={w}:")
            fc = rolling_forecast(returns, w, OOS_START, OOS_END, REFIT_INTERVAL)
            elapsed = time.time() - t0

            if fc is None:
                asset_results['windows'][str(w)] = {
                    'status': 'skipped',
                    'reason': 'insufficient_data',
                }
                print(f"    Skipped (insufficient data)")
                continue

            n_fc = len(fc['sigma2_hat'])
            if n_fc < 10:
                asset_results['windows'][str(w)] = {
                    'status': 'skipped',
                    'reason': f'too_few_forecasts ({n_fc})',
                }
                print(f"    Skipped (only {n_fc} forecasts)")
                continue

            # Compute losses
            q = qlike(fc['sigma2_hat'], fc['sigma2_proxy'])
            m = mse_loss(fc['sigma2_hat'], fc['sigma2_proxy'])
            ma = mae_loss(fc['sigma2_hat'], fc['sigma2_proxy'])
            hm = hmse_loss(fc['sigma2_hat'], fc['sigma2_proxy'])

            # Persistence stats
            avg_persist = np.mean(fc['persistence']) if fc['persistence'] else None
            std_persist = np.std(fc['persistence']) if fc['persistence'] else None
            conv_rate = np.mean(fc['convergence']) if fc['convergence'] else None

            # Bootstrap CI for QLIKE
            ci_lo, ci_hi, _ = bootstrap_qlike_ci(
                fc['sigma2_hat'], fc['sigma2_proxy'], BOOTSTRAP_REPS
            )

            window_forecasts[w] = fc

            asset_results['windows'][str(w)] = {
                'status': 'ok',
                'n_forecasts': n_fc,
                'qlike': round(q, 6),
                'mse': round(m, 6),
                'mae': round(ma, 6),
                'hmse': round(hm, 6),
                'qlike_ci_lo': round(ci_lo, 6),
                'qlike_ci_hi': round(ci_hi, 6),
                'avg_persistence': round(avg_persist, 6) if avg_persist else None,
                'std_persistence': round(std_persist, 6) if std_persist else None,
                'convergence_rate': round(conv_rate, 4) if conv_rate else None,
                'n_refits': len(fc['persistence']),
                'elapsed_sec': round(elapsed, 2),
            }

            print(f"    n={n_fc}, QLIKE={q:.6f} [{ci_lo:.6f}, {ci_hi:.6f}]")
            print(f"    MSE={m:.6f}, MAE={ma:.6f}, HMSE={hm:.6f}")
            print(f"    Persist={avg_persist:.4f}±{std_persist:.4f}, Conv={conv_rate:.1%}")
            print(f"    ({elapsed:.1f}s)")

        # DM tests vs baseline
        print(f"\n  --- DM Tests vs w={BASELINE_WINDOW} ---")
        dm_results = {}
        if BASELINE_WINDOW in window_forecasts:
            baseline_fc = window_forecasts[BASELINE_WINDOW]
            baseline_ratio = baseline_fc['sigma2_proxy'] / baseline_fc['sigma2_hat']
            baseline_losses = baseline_ratio - np.log(baseline_ratio) - 1.0

            for w in WINDOW_SIZES:
                if w == BASELINE_WINDOW or w not in window_forecasts:
                    continue
                fc_w = window_forecasts[w]
                # Align dates
                baseline_dates = set(baseline_fc['dates'])
                w_dates = set(fc_w['dates'])
                common_dates = sorted(baseline_dates & w_dates)

                if len(common_dates) < 30:
                    dm_results[str(w)] = {
                        'status': 'skipped',
                        'reason': f'only {len(common_dates)} common dates',
                    }
                    continue

                # Get aligned losses
                b_date_idx = {d: i for i, d in enumerate(baseline_fc['dates'])}
                w_date_idx = {d: i for i, d in enumerate(fc_w['dates'])}

                b_losses = np.array([baseline_losses[b_date_idx[d]] for d in common_dates])

                w_ratio = fc_w['sigma2_proxy'] / fc_w['sigma2_hat']
                w_losses_all = w_ratio - np.log(w_ratio) - 1.0
                w_losses = np.array([w_losses_all[w_date_idx[d]] for d in common_dates])

                t_stat, p_val = dm_test(w_losses, b_losses)

                dm_results[str(w)] = {
                    'n_common': len(common_dates),
                    't_stat': round(t_stat, 4),
                    'p_value': round(p_val, 4),
                    'significant_5pct': p_val < 0.05,
                    'direction': 'w better' if t_stat < 0 else f'w={BASELINE_WINDOW} better',
                }
                sig = '*' if p_val < 0.05 else ''
                direction = '<' if t_stat < 0 else '>'
                print(f"    w={w} vs w={BASELINE_WINDOW}: t={t_stat:.3f}, p={p_val:.4f} {sig} "
                      f"(w={w} {direction} w={BASELINE_WINDOW})")
        else:
            print(f"    Baseline w={BASELINE_WINDOW} not available")

        asset_results['dm_tests'] = dm_results

        # Find optimal window
        valid_windows = {
            w: asset_results['windows'][str(w)]
            for w in WINDOW_SIZES
            if str(w) in asset_results['windows']
            and asset_results['windows'][str(w)].get('status') == 'ok'
        }
        if valid_windows:
            best_w = min(valid_windows, key=lambda w: valid_windows[w]['qlike'])
            asset_results['optimal_window_qlike'] = best_w
            asset_results['optimal_qlike'] = valid_windows[best_w]['qlike']
            print(f"\n  ** Optimal window for {ticker}: w={best_w} (QLIKE={valid_windows[best_w]['qlike']:.6f})")

        results['assets'][ticker] = asset_results

    # ============================================================
    # Summary table
    # ============================================================
    print("\n" + "=" * 80)
    print("SUMMARY TABLE: QLIKE by Window Size")
    print("=" * 80)
    header = f"{'Window':>8}"
    for ticker in ASSETS:
        if ticker in results['assets'] and 'error' not in results['assets'][ticker]:
            header += f" | {ticker:>14}"
    print(header)
    print("-" * len(header))

    for w in WINDOW_SIZES:
        row = f"{w:>8}"
        for ticker in ASSETS:
            if ticker not in results['assets'] or 'error' in results['assets'][ticker]:
                continue
            wd = results['assets'][ticker]['windows'].get(str(w), {})
            if wd.get('status') == 'ok':
                q_val = wd['qlike']
                ci_lo = wd['qlike_ci_lo']
                ci_hi = wd['qlike_ci_hi']
                row += f" | {q_val:.6f}"
            else:
                row += f" | {'N/A':>14}"
        print(row)

    print()
    for ticker in ASSETS:
        if ticker in results['assets'] and 'optimal_window_qlike' in results['assets'].get(ticker, {}):
            bw = results['assets'][ticker]['optimal_window_qlike']
            bq = results['assets'][ticker]['optimal_qlike']
            print(f"  {ticker}: optimal w={bw} (QLIKE={bq:.6f})")

    # ============================================================
    # Persistence table
    # ============================================================
    print("\n" + "=" * 80)
    print("PERSISTENCE by Window Size (alpha + beta + gamma/2)")
    print("=" * 80)
    header = f"{'Window':>8}"
    for ticker in ASSETS:
        if ticker in results['assets'] and 'error' not in results['assets'][ticker]:
            header += f" | {ticker:>14}"
    print(header)
    print("-" * len(header))

    for w in WINDOW_SIZES:
        row = f"{w:>8}"
        for ticker in ASSETS:
            if ticker not in results['assets'] or 'error' in results['assets'][ticker]:
                continue
            wd = results['assets'][ticker]['windows'].get(str(w), {})
            if wd.get('status') == 'ok' and wd.get('avg_persistence') is not None:
                row += f" | {wd['avg_persistence']:.6f}"
            else:
                row += f" | {'N/A':>14}"
        print(row)

    # ============================================================
    # DM test summary
    # ============================================================
    print("\n" + "=" * 80)
    print(f"DM TEST vs w={BASELINE_WINDOW} (QLIKE, negative t = w better than {BASELINE_WINDOW})")
    print("=" * 80)
    for ticker in ASSETS:
        if ticker not in results['assets'] or 'error' in results['assets'][ticker]:
            continue
        dm = results['assets'][ticker].get('dm_tests', {})
        if not dm:
            continue
        print(f"\n  {ticker}:")
        for w in WINDOW_SIZES:
            if str(w) in dm and dm[str(w)].get('t_stat') is not None:
                d = dm[str(w)]
                sig = '**' if d['p_value'] < 0.01 else ('*' if d['p_value'] < 0.05 else '')
                print(f"    w={w:>5}: t={d['t_stat']:>7.3f}, p={d['p_value']:.4f} {sig}")

    # ============================================================
    # Cross-asset comparison
    # ============================================================
    print("\n" + "=" * 80)
    print("CROSS-ASSET: Does optimal window differ?")
    print("=" * 80)
    cross_asset = {}
    for ticker in ASSETS:
        a = results['assets'].get(ticker, {})
        if 'optimal_window_qlike' in a:
            opt_w = a['optimal_window_qlike']
            opt_q = a['optimal_qlike']
            # Check QLIKE range
            qlikes = {
                int(w): a['windows'][w]['qlike']
                for w in a['windows']
                if a['windows'][w].get('status') == 'ok'
            }
            if qlikes:
                q_range = max(qlikes.values()) - min(qlikes.values())
                q_pct_range = 100 * q_range / min(qlikes.values())
                cross_asset[ticker] = {
                    'optimal_window': opt_w,
                    'optimal_qlike': opt_q,
                    'qlike_range_abs': round(q_range, 6),
                    'qlike_range_pct': round(q_pct_range, 4),
                    'all_qlikes': {str(k): round(v, 6) for k, v in sorted(qlikes.items())},
                }
                print(f"  {ticker}: optimal w={opt_w}, QLIKE range={q_range:.6f} ({q_pct_range:.2f}%)")

    results['cross_asset_comparison'] = cross_asset

    # ============================================================
    # Save results JSON
    # ============================================================
    results_path = 'experiments/k622_results.json'
    with open(results_path, 'w') as f:
        # Convert any non-serializable types
        def default_handler(obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            elif isinstance(obj, (np.floating,)):
                return float(obj)
            elif isinstance(obj, (np.bool_,)):
                return bool(obj)
            elif isinstance(obj, pd.Timestamp):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        json.dump(results, f, indent=2, default=default_handler)
    print(f"\nResults saved to {results_path}")

    # ============================================================
    # Generate plot
    # ============================================================
    generate_plot(results)

    return results


def generate_plot(results):
    """Generate QLIKE vs window size plot with bootstrap CI bands."""
    fig, axes = plt.subplots(1, len(ASSETS), figsize=(6 * len(ASSETS), 5), squeeze=False)
    fig.suptitle('K622: QLIKE vs Window Size (GJR-GARCH(1,1))\n'
                 f'OOS: {OOS_START} to {OOS_END}, Refit every {REFIT_INTERVAL} days',
                 fontsize=13, fontweight='bold')

    colors = {'SPY': '#1f77b4', 'GLD': '#ff7f0e', '0050.TW': '#2ca02c'}

    for col, ticker in enumerate(ASSETS):
        ax = axes[0, col]
        a = results['assets'].get(ticker, {})
        if 'error' in a or not a.get('windows'):
            ax.set_title(f'{ticker}\n(no data)', fontsize=11)
            ax.set_visible(False)
            continue

        windows = []
        qlikes = []
        ci_los = []
        ci_his = []

        for w in WINDOW_SIZES:
            wd = a['windows'].get(str(w), {})
            if wd.get('status') == 'ok':
                windows.append(w)
                qlikes.append(wd['qlike'])
                ci_los.append(wd['qlike_ci_lo'])
                ci_his.append(wd['qlike_ci_hi'])

        if not windows:
            ax.set_title(f'{ticker}\n(no valid windows)', fontsize=11)
            continue

        windows = np.array(windows)
        qlikes = np.array(qlikes)
        ci_los = np.array(ci_los)
        ci_his = np.array(ci_his)

        color = colors.get(ticker, '#333333')

        # CI band
        ax.fill_between(windows, ci_los, ci_his, alpha=0.2, color=color,
                        label='95% Bootstrap CI')

        # Main line
        ax.plot(windows, qlikes, 'o-', color=color, linewidth=2, markersize=7,
                label='QLIKE', zorder=5)

        # Mark optimal
        best_idx = np.argmin(qlikes)
        ax.plot(windows[best_idx], qlikes[best_idx], '*', color='red',
                markersize=15, zorder=10, label=f'Best: w={windows[best_idx]}')

        # Mark baseline w=2000
        if BASELINE_WINDOW in windows:
            bl_idx = np.where(windows == BASELINE_WINDOW)[0][0]
            ax.axvline(x=BASELINE_WINDOW, color='gray', linestyle='--', alpha=0.5,
                       label=f'Baseline w={BASELINE_WINDOW}')

        ax.set_xlabel('Window Size (trading days)', fontsize=10)
        ax.set_ylabel('QLIKE', fontsize=10)
        ax.set_title(f'{ticker}', fontsize=12, fontweight='bold')
        ax.legend(fontsize=8, loc='best')
        ax.set_xticks(WINDOW_SIZES)
        ax.set_xticklabels([str(w) for w in WINDOW_SIZES], rotation=45, fontsize=8)
        ax.grid(True, alpha=0.3)

        # Add QLIKE values as text
        for i, (w_val, q_val) in enumerate(zip(windows, qlikes)):
            ax.annotate(f'{q_val:.4f}', (w_val, q_val),
                        textcoords="offset points", xytext=(0, 12),
                        fontsize=7, ha='center', color='black')

    plt.tight_layout()
    plot_path = 'experiments/k622_window_sweep.png'
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Plot saved to {plot_path}")

    # Also generate a persistence plot
    fig2, axes2 = plt.subplots(1, len(ASSETS), figsize=(6 * len(ASSETS), 4), squeeze=False)
    fig2.suptitle('K622: Average Persistence vs Window Size', fontsize=13, fontweight='bold')

    for col, ticker in enumerate(ASSETS):
        ax = axes2[0, col]
        a = results['assets'].get(ticker, {})
        if 'error' in a or not a.get('windows'):
            ax.set_visible(False)
            continue

        windows = []
        persists = []
        for w in WINDOW_SIZES:
            wd = a['windows'].get(str(w), {})
            if wd.get('status') == 'ok' and wd.get('avg_persistence') is not None:
                windows.append(w)
                persists.append(wd['avg_persistence'])

        if not windows:
            continue

        color = colors.get(ticker, '#333333')
        ax.plot(windows, persists, 's-', color=color, linewidth=2, markersize=7)
        ax.set_xlabel('Window Size', fontsize=10)
        ax.set_ylabel('Persistence (α+β+γ/2)', fontsize=10)
        ax.set_title(f'{ticker}', fontsize=12, fontweight='bold')
        ax.set_xticks(WINDOW_SIZES)
        ax.set_xticklabels([str(w) for w in WINDOW_SIZES], rotation=45, fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=1.0, color='red', linestyle='--', alpha=0.5, label='IGARCH boundary')
        ax.legend(fontsize=8)

    plt.tight_layout()
    persist_path = 'experiments/k622_persistence_vs_window.png'
    plt.savefig(persist_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Persistence plot saved to {persist_path}")


if __name__ == '__main__':
    run_experiment()
