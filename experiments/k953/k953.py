"""K953: HAR-RV Pilot with 56 Days 5-Min SPY Data (PRELIMINARY)

Problem: SPY 5-min data has accumulated ~56 days. Do a preliminary evaluation of:
1. 5-min RV descriptive statistics
2. HAR-RV in-sample fit quality
3. Short-window OOS (train 30d / test remaining)
4. Comparison with GJR, MF-GJR(VIX), EWMA on r² target

⚠️ PRELIMINARY — 56 days < 252 day formal OOS threshold.
No formal DM test (sample too small).

Data source: yfinance 5-min SPY (data/intraday/SPY_5min_YYYY-MM-DD.csv)
Reference: Corsi (2009), Patton (2011), Hansen & Lunde (2005)
"""

import sys
import os
import json
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import statsmodels.api as sm
from scipy import stats

np.random.seed(42)
warnings.filterwarnings('ignore')

# Project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

# Data may be in main repo, not worktree
_main_repo = Path('/Users/yhlai0911/Desktop/volpred-research')
INTRADAY_DIR = _main_repo / 'data' / 'intraday'
if not INTRADAY_DIR.exists():
    INTRADAY_DIR = PROJECT_ROOT / 'data' / 'intraday'
OUTPUT_DIR = Path(__file__).resolve().parent


# ============================================================
# 1. Load 5-min data and compute daily Realized Variance
# ============================================================
def load_5min_data():
    """Load all SPY 5-min CSV files, compute daily RV."""
    files = sorted(INTRADAY_DIR.glob('SPY_5min_*.csv'))
    if not files:
        raise FileNotFoundError("No SPY 5-min data found")

    daily_rv = {}
    daily_close = {}
    daily_open = {}
    daily_n_obs = {}

    for f in files:
        date_str = f.stem.split('_5min_')[-1]
        try:
            df = pd.read_csv(f, header=[0, 1], index_col=0, parse_dates=True)
            # Flatten multi-level columns
            close = df[('Close', 'SPY')].dropna()
        except Exception:
            # Try simpler parse
            df = pd.read_csv(f, skiprows=[1, 2], index_col=0, parse_dates=True)
            close = df['Close'].dropna()

        if len(close) < 5:
            continue

        # 5-min log returns
        log_ret = np.log(close / close.shift(1)).dropna()

        # RV = sum of squared intraday returns
        rv = (log_ret ** 2).sum()
        daily_rv[date_str] = rv
        daily_close[date_str] = float(close.iloc[-1])
        daily_open[date_str] = float(close.iloc[0])
        daily_n_obs[date_str] = len(log_ret)

    rv_series = pd.Series(daily_rv, name='RV').sort_index()
    rv_series.index = pd.to_datetime(rv_series.index)

    close_series = pd.Series(daily_close, name='Close').sort_index()
    close_series.index = pd.to_datetime(close_series.index)

    open_series = pd.Series(daily_open, name='Open').sort_index()
    open_series.index = pd.to_datetime(open_series.index)

    nobs_series = pd.Series(daily_n_obs, name='N_obs').sort_index()
    nobs_series.index = pd.to_datetime(nobs_series.index)

    return rv_series, close_series, open_series, nobs_series


def compute_daily_returns(close_series):
    """Compute daily close-to-close log returns."""
    return np.log(close_series / close_series.shift(1)).dropna()


# ============================================================
# 2. HAR-RV Model (Corsi 2009)
# ============================================================
def har_rv_features(rv_series):
    """Compute HAR-RV features: RV_d (lag1), RV_w (avg lag1-5), RV_m (avg lag1-22)."""
    df = pd.DataFrame({'RV': rv_series})
    df['RV_d'] = df['RV'].shift(1)
    df['RV_w'] = df['RV'].shift(1).rolling(5).mean()
    df['RV_m'] = df['RV'].shift(1).rolling(22).mean()
    df['RV_target'] = df['RV']
    return df.dropna()


def fit_har_rv(df, train_idx=None):
    """Fit HAR-RV by OLS. Returns model, coefficients, R²."""
    if train_idx is not None:
        data = df.iloc[:train_idx]
    else:
        data = df

    X = sm.add_constant(data[['RV_d', 'RV_w', 'RV_m']])
    y = data['RV_target']
    model = sm.OLS(y, X).fit()
    return model


def har_rv_predict(model, df, start_idx):
    """Out-of-sample HAR-RV predictions from start_idx."""
    preds = []
    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        x = np.array([1.0, row['RV_d'], row['RV_w'], row['RV_m']])
        pred = model.params @ x
        preds.append(max(pred, 1e-10))  # floor at tiny positive
    return np.array(preds)


# ============================================================
# 3. Benchmark models (on daily returns)
# ============================================================
def fit_gjr_garch(returns, out_of_sample=0):
    """Fit GJR(1,1,1) using arch package."""
    from arch import arch_model
    am = arch_model(returns * 100, vol='GARCH', p=1, o=1, q=1,
                    mean='Constant', dist='t')
    res = am.fit(disp='off', last_obs=len(returns) - out_of_sample if out_of_sample > 0 else None)
    return res


def ewma_forecast(returns, lam=0.94):
    """EWMA variance forecast."""
    r2 = (returns ** 2).values
    var = np.zeros(len(r2))
    var[0] = r2[0]
    for t in range(1, len(r2)):
        var[t] = lam * var[t-1] + (1 - lam) * r2[t-1]
    return pd.Series(var, index=returns.index, name='EWMA_var')


def mf_gjr_vix_forecast(returns, vix_data=None):
    """MF-GJR(VIX): multiply GJR short-run by VIX long-run component.
    Simplified version: scale GJR variance by (VIX/mean_VIX)².
    """
    from arch import arch_model
    am = arch_model(returns * 100, vol='GARCH', p=1, o=1, q=1,
                    mean='Constant', dist='t')
    res = am.fit(disp='off')
    cond_var = res.conditional_volatility ** 2 / 1e4  # back to decimal

    if vix_data is not None and len(vix_data) > 0:
        # Align VIX with returns
        common = cond_var.index.intersection(vix_data.index)
        if len(common) > 10:
            vix_aligned = vix_data.loc[common]
            vix_ratio = (vix_aligned / vix_aligned.mean()) ** 2
            cond_var_aligned = cond_var.loc[common]
            mf_var = cond_var_aligned * vix_ratio
            return mf_var

    return cond_var


# ============================================================
# 4. Main analysis
# ============================================================
def main():
    print("=" * 70)
    print("K953: HAR-RV Pilot with 5-Min SPY Data (PRELIMINARY)")
    print("=" * 70)

    # --- Load data ---
    rv_series, close_series, open_series, nobs_series = load_5min_data()
    daily_returns = compute_daily_returns(close_series)
    r_squared = daily_returns ** 2  # noisy proxy for σ²

    print(f"\n📊 Data Summary:")
    print(f"  Period: {rv_series.index[0].date()} to {rv_series.index[-1].date()}")
    print(f"  Trading days: {len(rv_series)}")
    print(f"  Avg 5-min obs/day: {nobs_series.mean():.1f}")
    print(f"  Min/Max obs/day: {nobs_series.min()}/{nobs_series.max()}")

    # --- Descriptive statistics ---
    print(f"\n📈 RV Descriptive Statistics:")
    rv_ann = rv_series * 252  # annualized
    rv_vol = np.sqrt(rv_series) * np.sqrt(252) * 100  # annualized vol %

    stats_dict = {
        'mean_daily_rv': float(rv_series.mean()),
        'std_daily_rv': float(rv_series.std()),
        'median_daily_rv': float(rv_series.median()),
        'skewness': float(stats.skew(rv_series)),
        'kurtosis': float(stats.kurtosis(rv_series)),
        'min_rv': float(rv_series.min()),
        'max_rv': float(rv_series.max()),
        'mean_ann_vol_pct': float(rv_vol.mean()),
        'std_ann_vol_pct': float(rv_vol.std()),
    }

    print(f"  Mean daily RV: {stats_dict['mean_daily_rv']:.6f}")
    print(f"  Std daily RV:  {stats_dict['std_daily_rv']:.6f}")
    print(f"  Skewness:      {stats_dict['skewness']:.2f}")
    print(f"  Kurtosis:      {stats_dict['kurtosis']:.2f}")
    print(f"  Mean ann. vol: {stats_dict['mean_ann_vol_pct']:.2f}%")
    print(f"  Min/Max daily: {stats_dict['min_rv']:.6f} / {stats_dict['max_rv']:.6f}")

    # --- Autocorrelation ---
    print(f"\n📐 RV Autocorrelation:")
    acf_lags = [1, 2, 3, 5, 10]
    acf_values = {}
    max_lag = min(max(acf_lags) + 1, len(rv_series) // 3)
    if max_lag > 1:
        acf_full = sm.tsa.acf(rv_series, nlags=max_lag, fft=False)
        for lag in acf_lags:
            if lag < len(acf_full):
                acf_values[f'lag_{lag}'] = float(acf_full[lag])
                print(f"  ACF(lag {lag:2d}): {acf_full[lag]:.4f}")

    # --- RV vs r² correlation ---
    common_idx = rv_series.index.intersection(r_squared.index)
    if len(common_idx) > 5:
        rv_common = rv_series.loc[common_idx]
        r2_common = r_squared.loc[common_idx]
        corr_rv_r2 = float(np.corrcoef(rv_common, r2_common)[0, 1])
        rank_corr = float(stats.spearmanr(rv_common, r2_common).correlation)
        print(f"\n🔗 RV vs r² (noisy σ² proxy):")
        print(f"  Pearson correlation:  {corr_rv_r2:.4f}")
        print(f"  Spearman correlation: {rank_corr:.4f}")
    else:
        corr_rv_r2 = np.nan
        rank_corr = np.nan

    # --- HAR-RV ---
    print(f"\n{'='*70}")
    print("HAR-RV Model (Corsi 2009)")
    print(f"{'='*70}")

    har_df = har_rv_features(rv_series)
    print(f"  Usable observations (after lag construction): {len(har_df)}")

    # In-sample fit on all data
    har_model_is = fit_har_rv(har_df)
    print(f"\n  In-Sample Results:")
    print(f"  R²: {har_model_is.rsquared:.4f}")
    print(f"  Adj R²: {har_model_is.rsquared_adj:.4f}")
    print(f"  Coefficients:")
    for name, coef, se, pval in zip(har_model_is.params.index,
                                      har_model_is.params,
                                      har_model_is.bse,
                                      har_model_is.pvalues):
        sig = '***' if pval < 0.001 else '**' if pval < 0.01 else '*' if pval < 0.05 else ''
        print(f"    {name:8s}: {coef:10.6f} (SE={se:.6f}, p={pval:.4f}) {sig}")

    # Short-window OOS: train first N, test rest (need at least 3 test days)
    train_size = min(30, len(har_df) - 3)
    if train_size >= 20 and len(har_df) > train_size + 2:
        har_model_oos = fit_har_rv(har_df, train_idx=train_size)
        har_preds_oos = har_rv_predict(har_model_oos, har_df, train_size)
        har_actual_oos = har_df['RV_target'].iloc[train_size:].values

        # Loss functions on RV target (native for HAR)
        har_mse_oos = float(np.mean((har_actual_oos - har_preds_oos) ** 2))
        har_mae_oos = float(np.mean(np.abs(har_actual_oos - har_preds_oos)))
        # QLIKE = mean(RV/pred - log(RV/pred) - 1)
        ratio = har_actual_oos / har_preds_oos
        har_qlike_rv_oos = float(np.mean(ratio - np.log(ratio) - 1))

        oos_days = len(har_actual_oos)
        print(f"\n  Out-of-Sample (train={train_size}, test={oos_days}):")
        print(f"  MSE:   {har_mse_oos:.10f}")
        print(f"  MAE:   {har_mae_oos:.8f}")
        print(f"  QLIKE (on RV): {har_qlike_rv_oos:.6f}")
    else:
        har_mse_oos = np.nan
        har_mae_oos = np.nan
        har_qlike_rv_oos = np.nan
        oos_days = 0
        har_preds_oos = np.array([])
        har_actual_oos = np.array([])

    # --- Benchmark: GJR-GARCH ---
    print(f"\n{'='*70}")
    print("Benchmark: GJR-GARCH(1,1,1)")
    print(f"{'='*70}")

    # Need longer daily returns for GARCH
    import yfinance as yf
    spy = yf.download('SPY', start='2023-01-01', end=rv_series.index[-1].strftime('%Y-%m-%d'),
                       progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy_close = spy[('Close', 'SPY')]
    else:
        spy_close = spy['Close']
    spy_ret = np.log(spy_close / spy_close.shift(1)).dropna()
    spy_r2 = spy_ret ** 2

    from arch import arch_model

    # GJR on full history, extract conditional variance for our 5-min period
    gjr_am = arch_model(spy_ret * 100, vol='GARCH', p=1, o=1, q=1,
                        mean='Constant', dist='t')
    gjr_res = gjr_am.fit(disp='off')
    gjr_cond_var = (gjr_res.conditional_volatility ** 2) / 1e4  # decimal

    print(f"  GJR params: ω={gjr_res.params['omega']:.6f}, "
          f"α={gjr_res.params['alpha[1]']:.4f}, "
          f"γ={gjr_res.params['gamma[1]']:.4f}, "
          f"β={gjr_res.params['beta[1]']:.4f}")
    persistence = gjr_res.params['alpha[1]'] + gjr_res.params['gamma[1]']/2 + gjr_res.params['beta[1]']
    print(f"  Persistence: {persistence:.4f}")

    # EWMA
    ewma_var = ewma_forecast(spy_ret, lam=0.94)

    # VIX for MF-GJR
    vix = yf.download('^VIX', start='2023-01-01',
                       end=rv_series.index[-1].strftime('%Y-%m-%d'), progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix_close = vix[('Close', '^VIX')]
    else:
        vix_close = vix['Close']
    vix_close.index = pd.to_datetime(vix_close.index)
    if hasattr(vix_close.index, 'tz') and vix_close.index.tz is not None:
        vix_close.index = vix_close.index.tz_localize(None)

    mf_gjr_var = mf_gjr_vix_forecast(spy_ret, vix_close)

    # --- Cross-model comparison on COMMON period ---
    print(f"\n{'='*70}")
    print("Cross-Model Comparison (PRELIMINARY)")
    print(f"{'='*70}")

    # Align all models to the 5-min RV period
    # Make all indices tz-naive
    for s in [rv_series, r_squared, gjr_cond_var, ewma_var]:
        if hasattr(s.index, 'tz') and s.index.tz is not None:
            s.index = s.index.tz_localize(None)
    if hasattr(mf_gjr_var.index, 'tz') and mf_gjr_var.index.tz is not None:
        mf_gjr_var.index = mf_gjr_var.index.tz_localize(None)

    # Start from har_df index (smallest set due to 22-day lag construction)
    common = har_df.index
    for s in [rv_series, r_squared, gjr_cond_var, ewma_var, mf_gjr_var]:
        common = common.intersection(s.index)

    if len(common) < 10:
        print(f"  WARNING: Only {len(common)} common dates. Results highly unreliable.")

    rv_c = rv_series.loc[common].values
    r2_c = r_squared.loc[common].values
    gjr_c = gjr_cond_var.loc[common].values
    ewma_c = ewma_var.loc[common].values
    mf_c = mf_gjr_var.loc[common].values

    # HAR IS predictions for common period
    har_is_preds = har_model_is.predict(sm.add_constant(har_df.loc[common, ['RV_d', 'RV_w', 'RV_m']]))
    har_c = np.maximum(har_is_preds.values, 1e-10)

    def qlike(actual, pred):
        """QLIKE loss: mean(actual/pred - log(actual/pred) - 1)"""
        ratio = actual / np.maximum(pred, 1e-12)
        return float(np.mean(ratio - np.log(ratio) - 1))

    def mse(actual, pred):
        return float(np.mean((actual - pred) ** 2))

    # Evaluation on TWO targets (as per preamble)
    results_comparison = {}
    models = {
        'HAR-RV': har_c,
        'GJR': gjr_c,
        'EWMA': ewma_c,
        'MF-GJR(VIX)': mf_c,
    }

    print(f"\n  Common period: {common[0].date()} to {common[-1].date()} ({len(common)} days)")

    # Target 1: RV (native for HAR)
    print(f"\n  --- Target: 5-min RV (native for HAR-RV) ---")
    print(f"  {'Model':<15s} {'QLIKE':>10s} {'MSE':>14s} {'Corr(RV)':>10s} {'Rank Corr':>10s}")
    for name, pred in models.items():
        q = qlike(rv_c, pred)
        m = mse(rv_c, pred)
        corr = float(np.corrcoef(rv_c, pred)[0, 1]) if np.std(pred) > 0 else 0
        rcorr = float(stats.spearmanr(rv_c, pred).correlation) if np.std(pred) > 0 else 0
        print(f"  {name:<15s} {q:10.6f} {m:14.10f} {corr:10.4f} {rcorr:10.4f}")
        results_comparison[f'{name}_qlike_rv'] = q
        results_comparison[f'{name}_mse_rv'] = m
        results_comparison[f'{name}_corr_rv'] = corr
        results_comparison[f'{name}_rankcorr_rv'] = rcorr

    # Target 2: r² (native for GARCH, proxy-robust per Patton 2011)
    print(f"\n  --- Target: r² (native for GARCH, Patton 2011 proxy-robust) ---")
    print(f"  {'Model':<15s} {'QLIKE':>10s} {'MSE':>14s} {'Corr(r²)':>10s} {'Rank Corr':>10s}")
    for name, pred in models.items():
        q = qlike(r2_c, pred)
        m = mse(r2_c, pred)
        corr = float(np.corrcoef(r2_c, pred)[0, 1]) if np.std(pred) > 0 else 0
        rcorr = float(stats.spearmanr(r2_c, pred).correlation) if np.std(pred) > 0 else 0
        print(f"  {name:<15s} {q:10.6f} {m:14.10f} {corr:10.4f} {rcorr:10.4f}")
        results_comparison[f'{name}_qlike_r2'] = q
        results_comparison[f'{name}_mse_r2'] = m
        results_comparison[f'{name}_corr_r2'] = corr
        results_comparison[f'{name}_rankcorr_r2'] = rcorr

    # RV information ratio: how much better is RV than r² as proxy?
    print(f"\n  --- RV vs r² as σ² proxy ---")
    noise_r2 = r2_c - rv_c
    print(f"  Mean(r² - RV): {np.mean(noise_r2):.6f} (overnight component + microstructure)")
    print(f"  Std(r² - RV):  {np.std(noise_r2):.6f}")
    print(f"  Corr(RV, r²):  {corr_rv_r2:.4f}")
    print(f"  Rank Corr:     {rank_corr:.4f}")

    # --- Note on mechanical results ---
    print(f"\n  ⚠️  NOTE: HAR winning on RV target is a MECHANICAL result (HAR is")
    print(f"      designed to predict RV). GARCH winning on r² target is similarly")
    print(f"      expected. Cross-target QLIKE on r² (Patton 2011) is the fair comparison.")

    # ============================================================
    # 5. Plots
    # ============================================================
    fig = plt.figure(figsize=(16, 14))
    gs = GridSpec(3, 2, figure=fig, hspace=0.35, wspace=0.3)

    # Plot 1: RV time series
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(rv_series.index, np.sqrt(rv_series) * np.sqrt(252) * 100,
             'b-', linewidth=1.5, label='Realized Vol (ann. %)')
    ax1.fill_between(rv_series.index, 0, np.sqrt(rv_series) * np.sqrt(252) * 100,
                      alpha=0.2, color='blue')
    ax1.set_title('SPY 5-min Realized Volatility (Annualized %)', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Volatility (%)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Plot 2: ACF of RV
    ax2 = fig.add_subplot(gs[1, 0])
    max_acf_lag = min(15, len(rv_series) // 3)
    if max_acf_lag > 1:
        acf_vals = sm.tsa.acf(rv_series, nlags=max_acf_lag, fft=False)
        ax2.bar(range(len(acf_vals)), acf_vals, color='steelblue', alpha=0.7)
        # Confidence bands
        n = len(rv_series)
        ci = 1.96 / np.sqrt(n)
        ax2.axhline(ci, color='red', linestyle='--', alpha=0.5)
        ax2.axhline(-ci, color='red', linestyle='--', alpha=0.5)
    ax2.set_title('ACF of Realized Variance', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Lag')
    ax2.set_ylabel('ACF')
    ax2.grid(True, alpha=0.3)

    # Plot 3: RV vs r²
    ax3 = fig.add_subplot(gs[1, 1])
    if len(common_idx) > 5:
        ax3.scatter(rv_common * 1e4, r2_common * 1e4, alpha=0.6, s=40, color='teal')
        ax3.plot([0, rv_common.max() * 1e4], [0, rv_common.max() * 1e4],
                 'r--', alpha=0.5, label='45° line')
        ax3.set_xlabel('5-min RV (×10⁴)')
        ax3.set_ylabel('r² (×10⁴)')
        ax3.set_title(f'RV vs r² (ρ={corr_rv_r2:.3f}, ρ_s={rank_corr:.3f})',
                       fontsize=12, fontweight='bold')
        ax3.legend()
    ax3.grid(True, alpha=0.3)

    # Plot 4: HAR-RV IS fit
    ax4 = fig.add_subplot(gs[2, 0])
    if len(har_df) > 0:
        har_is_full = har_model_is.predict(
            sm.add_constant(har_df[['RV_d', 'RV_w', 'RV_m']]))
        ax4.plot(har_df.index, np.sqrt(har_df['RV_target']) * np.sqrt(252) * 100,
                 'b-', alpha=0.7, label='Actual RV', linewidth=1.5)
        ax4.plot(har_df.index, np.sqrt(np.maximum(har_is_full, 0)) * np.sqrt(252) * 100,
                 'r--', alpha=0.8, label=f'HAR-RV (R²={har_model_is.rsquared:.3f})', linewidth=1.5)
        ax4.set_title('HAR-RV In-Sample Fit', fontsize=12, fontweight='bold')
        ax4.set_ylabel('Vol (%)')
        ax4.legend()
    ax4.grid(True, alpha=0.3)

    # Plot 5: Model comparison QLIKE
    ax5 = fig.add_subplot(gs[2, 1])
    model_names = list(models.keys())
    qlike_rv_vals = [results_comparison.get(f'{n}_qlike_rv', 0) for n in model_names]
    qlike_r2_vals = [results_comparison.get(f'{n}_qlike_r2', 0) for n in model_names]

    x_pos = np.arange(len(model_names))
    width = 0.35
    ax5.bar(x_pos - width/2, qlike_rv_vals, width, label='QLIKE(RV)', color='steelblue', alpha=0.8)
    ax5.bar(x_pos + width/2, qlike_r2_vals, width, label='QLIKE(r²)', color='coral', alpha=0.8)
    ax5.set_xticks(x_pos)
    ax5.set_xticklabels(model_names, rotation=15)
    ax5.set_ylabel('QLIKE Loss (lower = better)')
    ax5.set_title('Model Comparison: QLIKE on Two Targets', fontsize=12, fontweight='bold')
    ax5.legend()
    ax5.grid(True, alpha=0.3, axis='y')

    fig.suptitle('K953: HAR-RV Pilot with 56 Days 5-Min SPY Data (PRELIMINARY)',
                  fontsize=16, fontweight='bold', y=0.98)

    plt.savefig(OUTPUT_DIR / 'k953_rv_analysis.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n  Plot saved: k953_rv_analysis.png")

    # ============================================================
    # 6. Save results JSON
    # ============================================================
    results = {
        'experiment_id': 'K953',
        'title': 'HAR-RV Pilot with 56 Days 5-Min SPY Data',
        'status': 'PRELIMINARY',
        'warning': '56 days < 252 day formal OOS threshold. All results are preliminary.',
        'data_source': 'yfinance 5-min SPY',
        'period': f"{rv_series.index[0].date()} to {rv_series.index[-1].date()}",
        'n_trading_days': len(rv_series),
        'avg_obs_per_day': float(nobs_series.mean()),
        'descriptive_stats': stats_dict,
        'autocorrelation': acf_values,
        'rv_vs_r2': {
            'pearson_corr': corr_rv_r2,
            'spearman_corr': rank_corr,
            'mean_r2_minus_rv': float(np.mean(noise_r2)) if len(common_idx) > 5 else None,
        },
        'har_rv_insample': {
            'R2': float(har_model_is.rsquared),
            'adj_R2': float(har_model_is.rsquared_adj),
            'coefficients': {name: float(val) for name, val in har_model_is.params.items()},
            'p_values': {name: float(val) for name, val in har_model_is.pvalues.items()},
            'n_obs': int(har_model_is.nobs),
        },
        'har_rv_oos': {
            'train_days': train_size,
            'test_days': oos_days,
            'MSE': har_mse_oos,
            'MAE': har_mae_oos,
            'QLIKE_on_RV': har_qlike_rv_oos,
        },
        'cross_model_comparison': results_comparison,
        'cross_model_common_days': len(common),
        'gjr_params': {
            'omega': float(gjr_res.params['omega']),
            'alpha': float(gjr_res.params['alpha[1]']),
            'gamma': float(gjr_res.params['gamma[1]']),
            'beta': float(gjr_res.params['beta[1]']),
            'persistence': float(persistence),
        },
        'methodology_notes': [
            'HAR-RV predicts intraday RV (its native target)',
            'GJR/EWMA/MF-GJR predict close-to-close σ² (their native target is r²)',
            'HAR winning on RV target is MECHANICAL (expected by design)',
            'Fair cross-model comparison uses QLIKE on r² (Patton 2011)',
            'No formal DM test due to small sample size (56 days)',
        ],
        'timestamp': datetime.now().isoformat(),
    }

    with open(OUTPUT_DIR / 'k953_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n  Results saved: k953_results.json")

    # Summary
    print(f"\n{'='*70}")
    print("PRELIMINARY CONCLUSIONS")
    print(f"{'='*70}")
    print(f"  1. 5-min RV shows strong autocorrelation (typical for volatility)")
    if acf_values.get('lag_1', 0) > 0:
        print(f"     ACF(1) = {acf_values.get('lag_1', 0):.4f}")
    print(f"  2. HAR-RV IS R² = {har_model_is.rsquared:.4f}")
    print(f"  3. RV vs r² correlation = {corr_rv_r2:.4f} (r² is noisy but correlated)")
    if not np.isnan(har_qlike_rv_oos):
        print(f"  4. HAR-RV OOS QLIKE(RV) = {har_qlike_rv_oos:.6f} (train={train_size}, test={oos_days})")
    print(f"\n  ⚠️ These results are PRELIMINARY. Need 252+ days for formal evaluation.")
    print(f"  ⚠️ HAR vs GARCH comparison on RV target is MECHANICAL, not empirical.")
    print(f"  ⚠️ Continue collecting 5-min data for formal HAR-RV evaluation.")

    return results


if __name__ == '__main__':
    results = main()
