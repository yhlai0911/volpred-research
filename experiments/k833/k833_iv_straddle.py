#!/usr/bin/env python3
"""
K833: CBOE IV Weekly Short-Straddle Validation
================================================
Variance Risk Premium (VRP) proxy strategies using real CBOE IV indices.

Literature:
- Bollerslev, Tauchen & Zhou (2009) "Expected Stock Returns and Variance Risk Premia" RFS
- Carr & Wu (2009) "Variance Risk Premiums" RFS
- Coval & Shumway (2001) "Expected Option Returns" JF
- Bakshi & Kapadia (2003) "Delta-Hedged Gains and the Negative Market Volatility Risk Premium"

Data sources: yfinance (^VIX, ^VXN, ^GVZ, SPY, QQQ, GLD)
Period: 2010-01-01 ~ 2024-12-31

Strategies:
- S1: Always Short Vol (collect VRP every week)
- S2: VRP Timing (IV/RV ratio threshold)
- S3: GARCH-Enhanced (GJR-GARCH sigma replaces RV)

VRP Proxy Model:
  Weekly short-straddle P&L proxy:
    Premium collected = IV_weekly * S (proportional to ATM implied vol)
    Loss incurred = |actual weekly move| = |S_end - S_start|
    Net P&L = IV_weekly * sqrt(1/52) * S - |S_end - S_start|
    Normalized return = Net P&L / S = IV_weekly * sqrt(1/52) - |weekly_return|

  This captures the essence: you earn the implied vol premium but lose
  the actual realized move. VRP > 0 when IV overestimates realized vol.

Error Log rules applied:
- signal.shift(1): weekly signal uses PRIOR week's IV/RV ratio
- VRP proxy != real option P&L: clearly stated in results
- IV indices are in percentage points (VIX=18 means 18%), must /100
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
START = "2010-01-01"
END = "2024-12-31"
RISK_FREE_ANNUAL = 0.02
TRADING_DAYS_PER_YEAR = 252
WEEKS_PER_YEAR = 52

ASSETS = {
    "SPY": {"iv_ticker": "^VIX", "name": "S&P 500"},
    "QQQ": {"iv_ticker": "^VXN", "name": "Nasdaq 100"},
    "GLD": {"iv_ticker": "^GVZ", "name": "Gold"},
}

VRP_RATIO_HIGH = 1.2   # Full position threshold (IV/RV > 1.2)
VRP_RATIO_LOW = 0.8    # No position threshold (IV/RV < 0.8)
GARCH_WINDOW = 1000    # GJR-GARCH estimation window (trading days)
TX_COST_PER_TRADE = 0.002  # 20bps per week for option spread + slippage


def download_data(ticker, start, end):
    """Download price data from yfinance."""
    try:
        df = yf.download(ticker, start=start, end=end, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"  Failed to download {ticker}: {e}")
        return None


def fit_gjr_garch_sigma(daily_returns, window=1000):
    """
    Fit GJR-GARCH(1,1) rolling, return annualized conditional sigma series.
    """
    n = len(daily_returns)
    sigma = pd.Series(np.nan, index=daily_returns.index, dtype=float)
    ret_pct = daily_returns * 100

    for i in range(window, n):
        try:
            sub = ret_pct.iloc[max(0, i - window):i]
            model = arch_model(sub, vol='GARCH', p=1, o=1, q=1,
                             mean='Zero', dist='t', rescale=False)
            result = model.fit(disp='off', show_warning=False)
            fcast = result.forecast(horizon=1)
            # Convert daily vol to annualized decimal
            daily_vol = np.sqrt(fcast.variance.iloc[-1, 0]) / 100
            sigma.iloc[i] = daily_vol * np.sqrt(TRADING_DAYS_PER_YEAR)
        except Exception:
            sigma.iloc[i] = daily_returns.iloc[max(0, i - window):i].std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    return sigma


def build_weekly_data(price_df, iv_df, daily_returns):
    """
    Build weekly dataset for VRP analysis.

    Key unit handling:
    - IV indices (VIX etc.) are in percentage points: VIX=18 means 18% annualized
    - Convert to decimal: iv_decimal = VIX / 100
    - Weekly implied vol = iv_decimal * sqrt(1/52)
    - RV = annualized realized vol from daily returns (decimal)
    """
    # Weekly prices (Friday close)
    weekly_close = price_df['Close'].resample('W-FRI').last().dropna()
    weekly_return = weekly_close.pct_change().dropna()
    abs_weekly_return = weekly_return.abs()

    # IV: resample to Friday, convert percentage points to decimal
    weekly_iv_pct = iv_df['Close'].resample('W-FRI').last().dropna()
    weekly_iv = weekly_iv_pct / 100.0  # Now in decimal (0.18 = 18%)

    # Realized vol: 5-day rolling std of daily returns, annualized
    # Compute on daily, then sample Fridays
    daily_rv_5d = daily_returns.rolling(5).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    weekly_rv = daily_rv_5d.resample('W-FRI').last().dropna()

    # Align
    idx = weekly_return.index.intersection(weekly_iv.index).intersection(weekly_rv.index)
    idx = idx.intersection(abs_weekly_return.index)

    df = pd.DataFrame({
        'weekly_return': weekly_return.loc[idx],
        'abs_weekly_return': abs_weekly_return.loc[idx],
        'iv_ann': weekly_iv.loc[idx],         # annualized IV (decimal)
        'rv_ann': weekly_rv.loc[idx],         # annualized RV (decimal)
    })
    df = df.dropna()

    # Derived
    df['iv_weekly'] = df['iv_ann'] * np.sqrt(1.0 / 52)   # weekly IV
    df['rv_weekly'] = df['rv_ann'] * np.sqrt(1.0 / 52)   # weekly RV

    # IV/RV ratio (annualized, same units)
    df['iv_rv_ratio'] = df['iv_ann'] / df['rv_ann'].replace(0, np.nan)

    # VRP proxy: short-straddle weekly return
    # Collect premium = iv_weekly (proportional to ATM straddle value)
    # Lose = |actual weekly return| (the realized move)
    # Net = iv_weekly - |weekly_return|
    # This is a simplified but directionally correct proxy
    df['straddle_pnl'] = df['iv_weekly'] - df['abs_weekly_return']

    return df


def strategy_s1_always_short(weekly_df):
    """
    S1: Always Short Vol -- collect VRP every week.
    Position = 1 every week. Return = straddle_pnl - TX cost.
    """
    ret = weekly_df['straddle_pnl'].copy() - TX_COST_PER_TRADE
    pos = pd.Series(1.0, index=ret.index)
    return ret, pos


def strategy_s2_vrp_timing(weekly_df):
    """
    S2: VRP Timing -- position based on IV/RV ratio from PRIOR week.
    """
    ratio = weekly_df['iv_rv_ratio'].copy()
    # CRITICAL: shift(1) -- use PRIOR week's ratio to decide THIS week
    signal = ratio.shift(1)

    pos = pd.Series(0.0, index=signal.index)
    pos[signal > VRP_RATIO_HIGH] = 1.0
    pos[(signal >= VRP_RATIO_LOW) & (signal <= VRP_RATIO_HIGH)] = 0.5
    pos[signal < VRP_RATIO_LOW] = 0.0

    # Apply TX cost only when in position
    ret = weekly_df['straddle_pnl'] * pos - TX_COST_PER_TRADE * (pos > 0).astype(float)
    return ret.dropna(), pos.dropna()


def strategy_s3_garch_enhanced(weekly_df, daily_returns):
    """
    S3: GARCH-Enhanced -- use GJR-GARCH sigma instead of RV for timing.
    """
    print("    Fitting GJR-GARCH (may take 1-2 minutes)...")
    garch_sigma = fit_gjr_garch_sigma(daily_returns, window=GARCH_WINDOW)

    weekly_garch = garch_sigma.resample('W-FRI').last().dropna()
    idx = weekly_df.index.intersection(weekly_garch.index)

    if len(idx) < 52:
        print("    WARNING: Too few GARCH observations")
        return None, None

    df = weekly_df.loc[idx].copy()
    df['garch_sigma'] = weekly_garch.loc[idx]
    df['iv_garch_ratio'] = df['iv_ann'] / df['garch_sigma'].replace(0, np.nan)

    # Signal from PRIOR week
    signal = df['iv_garch_ratio'].shift(1)

    pos = pd.Series(0.0, index=signal.index)
    pos[signal > VRP_RATIO_HIGH] = 1.0
    pos[(signal >= VRP_RATIO_LOW) & (signal <= VRP_RATIO_HIGH)] = 0.5
    pos[signal < VRP_RATIO_LOW] = 0.0

    ret = df['straddle_pnl'] * pos - TX_COST_PER_TRADE * (pos > 0).astype(float)
    return ret.dropna(), pos.dropna()


def compute_metrics(returns, name=""):
    """Compute strategy performance metrics for weekly returns."""
    returns = returns.dropna()
    if len(returns) < 20:
        return None

    n = len(returns)
    ann = WEEKS_PER_YEAR

    mean_w = returns.mean()
    std_w = returns.std()
    if std_w < 1e-12:
        return None

    ann_ret = mean_w * ann
    ann_vol = std_w * np.sqrt(ann)
    rf_w = RISK_FREE_ANNUAL / ann

    sharpe = (mean_w - rf_w) / std_w * np.sqrt(ann)

    down = returns[returns < 0]
    down_std = down.std() if len(down) > 5 else std_w
    sortino = (mean_w - rf_w) / down_std * np.sqrt(ann) if down_std > 1e-12 else np.nan

    cum = (1 + returns).cumprod()
    mdd = ((cum - cum.cummax()) / cum.cummax()).min()
    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-8 else np.nan

    skew_val = float(stats.skew(returns.values))
    kurt_val = float(stats.kurtosis(returns.values))
    win_rate = float((returns > 0).mean())

    gp = returns[returns > 0].sum()
    gl = abs(returns[returns < 0].sum())
    pf = gp / gl if gl > 1e-12 else np.inf

    t_stat, p_val = stats.ttest_1samp(returns.values, 0)

    return {
        'name': name,
        'n_weeks': int(n),
        'ann_return': round(float(ann_ret), 4),
        'ann_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 3),
        'sortino': round(float(sortino), 3) if not np.isnan(sortino) else None,
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 3) if not np.isnan(calmar) else None,
        'skewness': round(skew_val, 3),
        'kurtosis': round(kurt_val, 3),
        'win_rate': round(win_rate, 4),
        'profit_factor': round(float(pf), 3) if pf != np.inf else 999.0,
        'mean_weekly': round(float(mean_w), 6),
        'std_weekly': round(float(std_w), 6),
        't_stat': round(float(t_stat), 3),
        'p_value': round(float(p_val), 4),
    }


def descriptive_stats(series, name):
    """Print diagnostics."""
    s = series.dropna()
    print(f"\n  --- {name} ---")
    print(f"  N={len(s)}, Mean={s.mean():.4f}, Std={s.std():.4f}, "
          f"Skew={stats.skew(s.values):.2f}, Kurt={stats.kurtosis(s.values):.2f}")
    print(f"  Min={s.min():.4f}, Q25={s.quantile(0.25):.4f}, "
          f"Med={s.median():.4f}, Q75={s.quantile(0.75):.4f}, Max={s.max():.4f}")


def main():
    print("=" * 70)
    print("K833: CBOE IV Weekly Short-Straddle Validation")
    print("=" * 70)
    print(f"Period: {START} to {END}")
    print(f"VRP Timing thresholds: IV/RV high={VRP_RATIO_HIGH}, low={VRP_RATIO_LOW}")
    print(f"GARCH window: {GARCH_WINDOW} days, TX cost: {TX_COST_PER_TRADE:.1%}/week")
    print()
    print("VRP Proxy: straddle_pnl = IV_weekly - |weekly_return|")
    print("  where IV_weekly = (VIX/100) * sqrt(1/52)")
    print()

    all_results = {}

    for asset, config in ASSETS.items():
        iv_ticker = config['iv_ticker']

        print(f"\n{'='*60}")
        print(f"  {asset} ({config['name']}) + {iv_ticker}")
        print(f"{'='*60}")

        price_df = download_data(asset, START, END)
        iv_df = download_data(iv_ticker, START, END)

        if price_df is None or iv_df is None:
            print(f"  SKIP: data unavailable")
            continue
        if len(price_df) < 200 or len(iv_df) < 200:
            print(f"  SKIP: insufficient data (price={len(price_df)}, iv={len(iv_df)})")
            continue

        print(f"  Price: {len(price_df)} days, IV: {len(iv_df)} days")

        daily_ret = price_df['Close'].pct_change().dropna()

        # Diagnostics
        descriptive_stats(daily_ret, f"{asset} Daily Returns")
        iv_decimal = iv_df['Close'] / 100.0
        descriptive_stats(iv_decimal, f"{iv_ticker} IV (decimal)")

        # Build weekly
        weekly = build_weekly_data(price_df, iv_df, daily_ret)
        print(f"\n  Weekly obs: {len(weekly)}")

        if len(weekly) < 52:
            print("  SKIP: too few weekly obs")
            continue

        # Diagnostics
        descriptive_stats(weekly['iv_rv_ratio'], f"IV/RV Ratio")
        descriptive_stats(weekly['straddle_pnl'], f"Straddle P&L proxy")

        vrp_pos = (weekly['straddle_pnl'] > 0).mean()
        iv_gt_rv = (weekly['iv_rv_ratio'] > 1).mean()
        print(f"\n  VRP positive (straddle profitable): {vrp_pos:.1%}")
        print(f"  IV > RV: {iv_gt_rv:.1%}")
        print(f"  Mean IV/RV ratio: {weekly['iv_rv_ratio'].mean():.3f}")
        print(f"  Median IV/RV ratio: {weekly['iv_rv_ratio'].median():.3f}")

        asset_res = {
            'asset': asset,
            'iv_ticker': iv_ticker,
            'n_daily': len(price_df),
            'n_weekly': len(weekly),
            'period': f"{weekly.index[0].date()} to {weekly.index[-1].date()}",
            'vrp_positive_frac': round(float(vrp_pos), 4),
            'iv_gt_rv_frac': round(float(iv_gt_rv), 4),
            'mean_iv_rv_ratio': round(float(weekly['iv_rv_ratio'].mean()), 4),
            'median_iv_rv_ratio': round(float(weekly['iv_rv_ratio'].median()), 4),
            'mean_straddle_pnl': round(float(weekly['straddle_pnl'].mean()), 6),
            'strategies': {},
        }

        # ---- S1: Always Short Vol ----
        print(f"\n  --- S1: Always Short Vol ---")
        s1_ret, s1_pos = strategy_s1_always_short(weekly)
        s1_m = compute_metrics(s1_ret, f"S1_AlwaysShort_{asset}")
        if s1_m:
            print(f"  Sharpe={s1_m['sharpe']:.3f}, AnnRet={s1_m['ann_return']:.2%}, "
                  f"AnnVol={s1_m['ann_vol']:.2%}, MDD={s1_m['mdd']:.2%}")
            print(f"  Win={s1_m['win_rate']:.1%}, Skew={s1_m['skewness']:.2f}, "
                  f"Kurt={s1_m['kurtosis']:.2f}, t={s1_m['t_stat']:.2f} (p={s1_m['p_value']:.4f})")
            asset_res['strategies']['S1_AlwaysShort'] = s1_m

        # ---- S2: VRP Timing ----
        print(f"\n  --- S2: VRP Timing ---")
        s2_ret, s2_pos = strategy_s2_vrp_timing(weekly)
        s2_m = compute_metrics(s2_ret, f"S2_VRPTiming_{asset}")
        if s2_m:
            full = (s2_pos == 1.0).mean()
            half = (s2_pos == 0.5).mean()
            zero = (s2_pos == 0.0).mean()
            print(f"  Positions: Full={full:.1%}, Half={half:.1%}, Out={zero:.1%}")
            print(f"  Sharpe={s2_m['sharpe']:.3f}, AnnRet={s2_m['ann_return']:.2%}, "
                  f"AnnVol={s2_m['ann_vol']:.2%}, MDD={s2_m['mdd']:.2%}")
            print(f"  Win={s2_m['win_rate']:.1%}, Skew={s2_m['skewness']:.2f}, "
                  f"Kurt={s2_m['kurtosis']:.2f}, t={s2_m['t_stat']:.2f} (p={s2_m['p_value']:.4f})")
            s2_m['pos_full'] = round(float(full), 4)
            s2_m['pos_half'] = round(float(half), 4)
            s2_m['pos_zero'] = round(float(zero), 4)
            asset_res['strategies']['S2_VRPTiming'] = s2_m

        # ---- S3: GARCH-Enhanced ----
        print(f"\n  --- S3: GARCH-Enhanced ---")
        s3_ret, s3_pos = strategy_s3_garch_enhanced(weekly, daily_ret)
        if s3_ret is not None:
            s3_m = compute_metrics(s3_ret, f"S3_GARCHEnhanced_{asset}")
            if s3_m:
                full = (s3_pos == 1.0).mean()
                half = (s3_pos == 0.5).mean()
                zero = (s3_pos == 0.0).mean()
                print(f"  Positions: Full={full:.1%}, Half={half:.1%}, Out={zero:.1%}")
                print(f"  Sharpe={s3_m['sharpe']:.3f}, AnnRet={s3_m['ann_return']:.2%}, "
                      f"AnnVol={s3_m['ann_vol']:.2%}, MDD={s3_m['mdd']:.2%}")
                print(f"  Win={s3_m['win_rate']:.1%}, Skew={s3_m['skewness']:.2f}, "
                      f"Kurt={s3_m['kurtosis']:.2f}, t={s3_m['t_stat']:.2f} (p={s3_m['p_value']:.4f})")
                s3_m['pos_full'] = round(float(full), 4)
                s3_m['pos_half'] = round(float(half), 4)
                s3_m['pos_zero'] = round(float(zero), 4)
                asset_res['strategies']['S3_GARCHEnhanced'] = s3_m

        all_results[asset] = asset_res

    # ============================================================
    # Cross-Asset Summary
    # ============================================================
    print("\n" + "=" * 70)
    print("CROSS-ASSET SUMMARY")
    print("=" * 70)

    rows = []
    for asset, res in all_results.items():
        for sname, m in res['strategies'].items():
            rows.append({
                'Asset': asset, 'Strategy': sname,
                'Sharpe': m['sharpe'], 'AnnRet': f"{m['ann_return']:.2%}",
                'AnnVol': f"{m['ann_vol']:.2%}", 'MDD': f"{m['mdd']:.2%}",
                'Sortino': m['sortino'], 'Skew': m['skewness'],
                'Kurt': m['kurtosis'], 'Win%': f"{m['win_rate']:.1%}",
                't': m['t_stat'], 'p': m['p_value'],
            })

    if rows:
        print(pd.DataFrame(rows).to_string(index=False))

    # ============================================================
    # Sanity Checks
    # ============================================================
    print("\n" + "=" * 70)
    print("SANITY CHECKS")
    print("=" * 70)

    any_suspicious = False
    for asset, res in all_results.items():
        for sname, m in res['strategies'].items():
            if abs(m['sharpe']) > 3.0:
                print(f"  WARNING: {asset}/{sname} Sharpe={m['sharpe']:.2f} > 3.0 -- may still have scaling issues")
                any_suspicious = True
            if m['win_rate'] > 0.9:
                print(f"  WARNING: {asset}/{sname} Win={m['win_rate']:.1%} -- unusually high for weekly vol strategy")
                any_suspicious = True
            if m['mdd'] == 0:
                print(f"  WARNING: {asset}/{sname} MDD=0 -- impossible for real strategy")
                any_suspicious = True

    if not any_suspicious:
        print("  All checks passed -- results in plausible range")

    # ============================================================
    # Key Findings
    # ============================================================
    print("\n" + "=" * 70)
    print("KEY FINDINGS")
    print("=" * 70)

    findings = []
    for asset, res in all_results.items():
        for sname, m in res['strategies'].items():
            sig = "***" if m['p_value'] < 0.01 else "**" if m['p_value'] < 0.05 else "*" if m['p_value'] < 0.10 else ""
            f = (f"{asset}/{sname}: Sharpe {m['sharpe']:.3f}, "
                 f"AnnRet {m['ann_return']:.2%}, MDD {m['mdd']:.2%}, "
                 f"t={m['t_stat']:.2f}{sig}")
            findings.append(f)
            print(f"  {f}")

    print("\n  CAVEATS:")
    print("  1. VRP PROXY -- not real option P&L (no gamma, no delta hedge)")
    print("  2. TX cost 20bps/week is conservative estimate")
    print("  3. Real short-straddle has unlimited loss potential + margin")
    print("  4. Weekly frequency ignores intra-week vol-of-vol risk")
    print("  5. Straddle P&L = IV_weekly - |weekly_return| is simplified")
    print("  6. Sharpe NOT directly comparable to equity long-only strategies")

    # ============================================================
    # Save
    # ============================================================
    out_path = Path(__file__).parent / "k833_iv_straddle_results.json"

    output = {
        'experiment_id': 'K833',
        'title': 'CBOE IV Weekly Short-Straddle Validation',
        'description': 'VRP proxy strategies using real CBOE IV indices (VIX/VXN/GVZ). '
                       'Models weekly short-straddle P&L as: premium_collected(IV) - realized_move.',
        'methodology': {
            'vrp_proxy': 'straddle_pnl = IV_weekly - |weekly_return|',
            'iv_weekly': 'IV_ann/100 * sqrt(1/52)',
            'rv_weekly': 'rolling 5-day std(daily_ret) * sqrt(252) * sqrt(1/52)',
            'iv_source': 'CBOE indices: ^VIX (SPY), ^VXN (QQQ), ^GVZ (GLD)',
            'signal_lag': 'shift(1) on IV/RV ratio for S2 and S3',
            'tx_cost': f'{TX_COST_PER_TRADE:.1%} per week when in position',
        },
        'data_source': 'yfinance',
        'period': f'{START} to {END}',
        'references': [
            'Bollerslev, Tauchen & Zhou (2009) "Expected Stock Returns and Variance Risk Premia" RFS',
            'Carr & Wu (2009) "Variance Risk Premiums" RFS',
            'Coval & Shumway (2001) "Expected Option Returns" JF',
        ],
        'parameters': {
            'vrp_ratio_high': VRP_RATIO_HIGH,
            'vrp_ratio_low': VRP_RATIO_LOW,
            'garch_window': GARCH_WINDOW,
            'tx_cost_per_week': TX_COST_PER_TRADE,
        },
        'caveats': [
            'VRP PROXY -- simplified straddle, no gamma/delta hedge',
            'TX cost 20bps/week is estimate (real bid-ask wider)',
            'Real short-straddle has unlimited loss + margin calls',
            'Weekly frequency misses intra-week vol-of-vol',
            'Not directly comparable to equity strategies',
        ],
        'results': all_results,
        'findings': findings,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to: {out_path}")
    return output


if __name__ == '__main__':
    main()
