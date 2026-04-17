"""
K512: Taiwan Ex-Dividend (除權息) Volatility Study
====================================================
[提出: 用戶, 執行: Claude]

研究問題:
1. 0050.TW 除息日前後 vol 是否系統性改變？
2. 高股息 ETF（0056）除息日前後的價格和 vol 行為
3. 填息率和 vol 的關係——填息快的期間 vol 是否較低？
4. 除息月份（6-8月旺季）vs 其他月份的 vol 差異

資料來源: yfinance (0050.TW, 0056.TW)
資料期間: 2008-01-01 ~ present
方法: Event study, rolling volatility, conditional analysis

文獻背景:
- 台灣除權息為台灣特有之稅務/市場結構議題
- Ex-dividend date anomaly 在國際文獻中有討論 (Elton & Gruber 1970, Frank & Jagannathan 1998)
- 台灣市場除息跳空明顯，因為個股可能配發 5-8% 現金股利
- ETF 除息更集中（0050 通常 7 月、0056 通常 10-12 月）
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats

warnings.filterwarnings('ignore')

def detect_ex_dividend_dates(ticker_symbol, start='2008-01-01'):
    """偵測除息日：使用 yfinance dividends + Adj Close/Close ratio 交叉驗證"""
    ticker = yf.Ticker(ticker_symbol)

    # Method 1: yfinance dividends
    dividends = ticker.dividends
    if dividends is not None and len(dividends) > 0:
        div_dates_m1 = dividends.index.tz_localize(None) if dividends.index.tz else dividends.index
        div_amounts = dividends.values
    else:
        div_dates_m1 = pd.DatetimeIndex([])
        div_amounts = np.array([])

    # Download price data
    df = yf.download(ticker_symbol, start=start, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Method 2: Adj Close / Close ratio change
    if 'Adj Close' in df.columns and 'Close' in df.columns:
        adj_ratio = df['Adj Close'] / df['Close']
        ratio_change = adj_ratio.pct_change()
        # Ex-div days: ratio drops by > 0.3%
        ex_div_m2 = ratio_change[ratio_change < -0.003].index
    else:
        ex_div_m2 = pd.DatetimeIndex([])

    # Combine and deduplicate (within 5 trading days = same event)
    all_dates = set()

    # Add Method 1 dates
    for d in div_dates_m1:
        # Find nearest trading day in df
        ts = pd.Timestamp(d)
        mask = abs((df.index - ts).days) <= 5
        if mask.any():
            nearest = df.index[mask][0]
            all_dates.add(nearest)

    # Add Method 2 dates (only if not already captured)
    for d in ex_div_m2:
        already = False
        for existing in all_dates:
            if abs((d - existing).days) <= 5:
                already = True
                break
        if not already:
            all_dates.add(d)

    sorted_dates = sorted(all_dates)

    # Build dividend info
    div_info = []
    for d in sorted_dates:
        # Find dividend amount
        amount = np.nan
        for i, dd in enumerate(div_dates_m1):
            if abs((pd.Timestamp(dd) - d).days) <= 5:
                amount = float(div_amounts[i])
                break

        # Get close price before ex-div
        idx = df.index.get_loc(d)
        if idx > 0:
            prev_close = float(df['Close'].iloc[idx - 1])
            div_yield = amount / prev_close if not np.isnan(amount) and prev_close > 0 else np.nan
        else:
            prev_close = np.nan
            div_yield = np.nan

        div_info.append({
            'date': d,
            'amount': amount,
            'prev_close': prev_close,
            'div_yield': div_yield,
            'month': d.month,
            'year': d.year
        })

    return df, pd.DataFrame(div_info), dividends


def compute_realized_vol(returns, window=22):
    """計算年化已實現波動率"""
    return returns.rolling(window).std() * np.sqrt(252)


def event_study_vol(df, ex_div_dates, pre_window=10, post_window=22):
    """
    Event study: 除息日前後的波動率行為

    Windows:
    - [-10, -6]: 遠除息前
    - [-5, -1]: 近除息前
    - [0]: 除息日
    - [+1, +5]: 近除息後
    - [+6, +22]: 填息期
    """
    returns = df['Close'].pct_change().dropna()

    results = []
    for ex_date in ex_div_dates:
        if ex_date not in returns.index:
            continue

        idx = returns.index.get_loc(ex_date)

        # Need enough data around the event
        if idx < pre_window or idx + post_window >= len(returns):
            continue

        # Extract windows
        pre_far = returns.iloc[idx - pre_window: idx - 5]   # [-10, -6]
        pre_near = returns.iloc[idx - 5: idx]                # [-5, -1]
        day_of = returns.iloc[idx: idx + 1]                  # [0]
        post_near = returns.iloc[idx + 1: idx + 6]           # [+1, +5]
        post_fill = returns.iloc[idx + 6: idx + post_window + 1]  # [+6, +22]

        # Control: random 22-day window (at least 60 days away from any ex-div)
        control_candidates = []
        for c_idx in range(60, len(returns) - 22):
            c_date = returns.index[c_idx]
            far_enough = all(abs((c_date - ed).days) > 60 for ed in ex_div_dates)
            if far_enough:
                control_candidates.append(c_idx)

        if len(control_candidates) > 0:
            # Sample one control window
            np.random.seed(int(ex_date.timestamp()) % (2**31))
            c_idx = np.random.choice(control_candidates)
            control = returns.iloc[c_idx: c_idx + 22]
            control_vol = float(control.std() * np.sqrt(252))
        else:
            control_vol = np.nan

        event = {
            'ex_date': ex_date,
            'pre_far_vol': float(pre_far.std() * np.sqrt(252)),
            'pre_near_vol': float(pre_near.std() * np.sqrt(252)),
            'day_of_return': float(day_of.values[0]),
            'day_of_abs_return': float(abs(day_of.values[0])),
            'post_near_vol': float(post_near.std() * np.sqrt(252)),
            'post_fill_vol': float(post_fill.std() * np.sqrt(252)),
            'full_post_vol': float(returns.iloc[idx + 1: idx + post_window + 1].std() * np.sqrt(252)),
            'control_vol': control_vol,
            'pre_far_mean_ret': float(pre_far.mean()),
            'pre_near_mean_ret': float(pre_near.mean()),
            'post_near_mean_ret': float(post_near.mean()),
            'post_fill_mean_ret': float(post_fill.mean()),
        }
        results.append(event)

    return pd.DataFrame(results)


def fill_rate_analysis(df, ex_div_info, max_days=60):
    """
    填息率分析：除息後幾天回到除息前價格？

    填息 = 除息後股價回到除息前一天收盤價
    """
    results = []

    for _, row in ex_div_info.iterrows():
        ex_date = row['date']
        if ex_date not in df.index:
            continue

        idx = df.index.get_loc(ex_date)
        if idx == 0:
            continue

        prev_close = float(df['Close'].iloc[idx - 1])

        # Check if price recovers within max_days
        fill_day = None
        for d in range(1, min(max_days + 1, len(df) - idx)):
            if float(df['Close'].iloc[idx + d]) >= prev_close:
                fill_day = d
                break

        # Compute vol during fill period
        returns = df['Close'].pct_change()
        if fill_day is not None:
            fill_returns = returns.iloc[idx + 1: idx + fill_day + 1]
            fill_vol = float(fill_returns.std() * np.sqrt(252)) if len(fill_returns) > 1 else np.nan
        else:
            # Not filled within max_days
            fill_returns = returns.iloc[idx + 1: idx + max_days + 1]
            fill_vol = float(fill_returns.std() * np.sqrt(252)) if len(fill_returns) > 1 else np.nan

        results.append({
            'ex_date': ex_date,
            'year': row['year'],
            'month': row['month'],
            'div_amount': row['amount'],
            'div_yield': row['div_yield'],
            'prev_close': prev_close,
            'filled': fill_day is not None,
            'fill_days': fill_day if fill_day is not None else np.nan,
            'fill_vol': fill_vol,
        })

    return pd.DataFrame(results)


def monthly_vol_analysis(df):
    """月份效應：各月份的平均波動率"""
    returns = df['Close'].pct_change().dropna()

    monthly_vol = {}
    for month in range(1, 13):
        mask = returns.index.month == month
        month_rets = returns[mask]
        monthly_vol[month] = {
            'mean_abs_ret': float(month_rets.abs().mean()),
            'std_ret': float(month_rets.std()),
            'annualized_vol': float(month_rets.std() * np.sqrt(252)),
            'n_days': int(mask.sum()),
            'skewness': float(month_rets.skew()),
            'kurtosis': float(month_rets.kurtosis()),
        }

    return monthly_vol


def run_experiment():
    """主實驗"""
    print("=" * 70)
    print("K512: Taiwan Ex-Dividend (除權息) Volatility Study")
    print("=" * 70)

    results = {
        'experiment_id': 'K512',
        'title': 'Taiwan Ex-Dividend Volatility Study',
        'proposed_by': '用戶',
        'executed_by': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'assets': ['0050.TW', '0056.TW'],
    }

    # =========================================================================
    # Part 1: Download and prepare data
    # =========================================================================
    print("\n[1] 下載資料...")

    assets = {
        '0050.TW': '元大台灣50',
        '0056.TW': '元大高股息',
    }

    all_results = {}

    for symbol, name in assets.items():
        print(f"\n{'='*50}")
        print(f"分析 {symbol} ({name})")
        print(f"{'='*50}")

        # Download and detect ex-dividend dates
        df, div_info, raw_dividends = detect_ex_dividend_dates(symbol)

        print(f"資料期間: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
        print(f"交易日數: {len(df)}")
        print(f"偵測到除息次數: {len(div_info)}")

        if len(div_info) == 0:
            print(f"  [警告] {symbol} 未偵測到除息日，跳過")
            all_results[symbol] = {'error': 'no ex-dividend dates detected'}
            continue

        # =====================================================================
        # Part 2: Descriptive statistics
        # =====================================================================
        print(f"\n[2] 描述性統計")
        returns = df['Close'].pct_change().dropna()

        desc_stats = {
            'n_obs': int(len(returns)),
            'mean_daily_ret': float(returns.mean()),
            'std_daily_ret': float(returns.std()),
            'annualized_vol': float(returns.std() * np.sqrt(252)),
            'skewness': float(returns.skew()),
            'kurtosis': float(returns.kurtosis()),
            'min_ret': float(returns.min()),
            'max_ret': float(returns.max()),
        }
        print(f"  日均報酬: {desc_stats['mean_daily_ret']:.6f}")
        print(f"  年化波動率: {desc_stats['annualized_vol']:.4f}")
        print(f"  偏態: {desc_stats['skewness']:.4f}")
        print(f"  峰態: {desc_stats['kurtosis']:.4f}")

        # Dividend summary
        print(f"\n[3] 除息記錄摘要")
        print(f"  除息次數: {len(div_info)}")
        valid_yields = div_info['div_yield'].dropna()
        if len(valid_yields) > 0:
            print(f"  平均殖利率: {valid_yields.mean():.4f} ({valid_yields.mean()*100:.2f}%)")
            print(f"  殖利率範圍: {valid_yields.min()*100:.2f}% ~ {valid_yields.max()*100:.2f}%")

        # Month distribution of ex-div dates
        month_dist = div_info['month'].value_counts().sort_index()
        print(f"  除息月份分佈:")
        for m, c in month_dist.items():
            print(f"    {m}月: {c}次")

        div_summary = {
            'n_events': int(len(div_info)),
            'avg_yield': float(valid_yields.mean()) if len(valid_yields) > 0 else None,
            'min_yield': float(valid_yields.min()) if len(valid_yields) > 0 else None,
            'max_yield': float(valid_yields.max()) if len(valid_yields) > 0 else None,
            'month_distribution': {int(k): int(v) for k, v in month_dist.items()},
            'years': sorted(div_info['year'].unique().tolist()),
        }

        # =====================================================================
        # Part 3: Event Study
        # =====================================================================
        print(f"\n[4] Event Study: 除息日前後波動率")

        ex_dates = div_info['date'].tolist()
        event_df = event_study_vol(df, ex_dates)

        if len(event_df) == 0:
            print("  [警告] Event study 無有效事件")
            event_results = {'error': 'no valid events'}
        else:
            print(f"  有效事件數: {len(event_df)}")

            # Average across events
            vol_cols = ['pre_far_vol', 'pre_near_vol', 'post_near_vol', 'post_fill_vol', 'full_post_vol', 'control_vol']

            print(f"\n  === 除息日前後平均年化波動率 ===")
            print(f"  遠除息前 [-10,-6]:  {event_df['pre_far_vol'].mean():.4f}")
            print(f"  近除息前 [-5,-1]:   {event_df['pre_near_vol'].mean():.4f}")
            print(f"  除息日絕對報酬:     {event_df['day_of_abs_return'].mean():.4f}")
            print(f"  近除息後 [+1,+5]:   {event_df['post_near_vol'].mean():.4f}")
            print(f"  填息期 [+6,+22]:    {event_df['post_fill_vol'].mean():.4f}")
            print(f"  完整除息後 [+1,+22]:{event_df['full_post_vol'].mean():.4f}")
            print(f"  控制組 (非除息期):  {event_df['control_vol'].mean():.4f}")

            # Statistical tests
            # Test 1: pre_near vs control
            t_pre, p_pre = stats.ttest_rel(
                event_df['pre_near_vol'].dropna(),
                event_df['control_vol'].dropna()[:len(event_df['pre_near_vol'].dropna())]
            ) if len(event_df) > 2 else (np.nan, np.nan)

            # Test 2: post_near vs control
            t_post, p_post = stats.ttest_rel(
                event_df['post_near_vol'].dropna(),
                event_df['control_vol'].dropna()[:len(event_df['post_near_vol'].dropna())]
            ) if len(event_df) > 2 else (np.nan, np.nan)

            # Test 3: pre_near vs post_near (paired)
            valid = event_df[['pre_near_vol', 'post_near_vol']].dropna()
            t_prepost, p_prepost = stats.ttest_rel(
                valid['pre_near_vol'], valid['post_near_vol']
            ) if len(valid) > 2 else (np.nan, np.nan)

            # Test 4: day-of absolute return vs average absolute return
            avg_abs_ret = float(returns.abs().mean())
            t_dayof, p_dayof = stats.ttest_1samp(
                event_df['day_of_abs_return'].dropna(), avg_abs_ret
            ) if len(event_df) > 2 else (np.nan, np.nan)

            print(f"\n  === 統計檢定 ===")
            print(f"  除息前 vs 控制組: t={t_pre:.3f}, p={p_pre:.4f}")
            print(f"  除息後 vs 控制組: t={t_post:.3f}, p={p_post:.4f}")
            print(f"  除息前 vs 除息後: t={t_prepost:.3f}, p={p_prepost:.4f}")
            print(f"  除息日|ret| vs 平均|ret|: t={t_dayof:.3f}, p={p_dayof:.4f}")
            print(f"  (平均|日報酬|={avg_abs_ret:.6f}, 除息日平均|報酬|={event_df['day_of_abs_return'].mean():.6f})")

            # Return patterns
            print(f"\n  === 除息日前後平均報酬 ===")
            print(f"  遠除息前 [-10,-6] 日均報酬: {event_df['pre_far_mean_ret'].mean():.6f}")
            print(f"  近除息前 [-5,-1] 日均報酬:  {event_df['pre_near_mean_ret'].mean():.6f}")
            print(f"  除息日報酬:                 {event_df['day_of_return'].mean():.6f}")
            print(f"  近除息後 [+1,+5] 日均報酬:  {event_df['post_near_mean_ret'].mean():.6f}")
            print(f"  填息期 [+6,+22] 日均報酬:   {event_df['post_fill_mean_ret'].mean():.6f}")

            event_results = {
                'n_events': int(len(event_df)),
                'avg_vol': {
                    'pre_far': float(event_df['pre_far_vol'].mean()),
                    'pre_near': float(event_df['pre_near_vol'].mean()),
                    'post_near': float(event_df['post_near_vol'].mean()),
                    'post_fill': float(event_df['post_fill_vol'].mean()),
                    'full_post': float(event_df['full_post_vol'].mean()),
                    'control': float(event_df['control_vol'].mean()),
                },
                'median_vol': {
                    'pre_far': float(event_df['pre_far_vol'].median()),
                    'pre_near': float(event_df['pre_near_vol'].median()),
                    'post_near': float(event_df['post_near_vol'].median()),
                    'post_fill': float(event_df['post_fill_vol'].median()),
                    'control': float(event_df['control_vol'].median()),
                },
                'avg_returns': {
                    'pre_far': float(event_df['pre_far_mean_ret'].mean()),
                    'pre_near': float(event_df['pre_near_mean_ret'].mean()),
                    'day_of': float(event_df['day_of_return'].mean()),
                    'post_near': float(event_df['post_near_mean_ret'].mean()),
                    'post_fill': float(event_df['post_fill_mean_ret'].mean()),
                },
                'day_of_abs_return': {
                    'mean': float(event_df['day_of_abs_return'].mean()),
                    'median': float(event_df['day_of_abs_return'].median()),
                    'avg_abs_return_all_days': avg_abs_ret,
                },
                'tests': {
                    'pre_near_vs_control': {'t': float(t_pre), 'p': float(p_pre)},
                    'post_near_vs_control': {'t': float(t_post), 'p': float(p_post)},
                    'pre_vs_post': {'t': float(t_prepost), 'p': float(p_prepost)},
                    'day_of_vs_avg': {'t': float(t_dayof), 'p': float(p_dayof)},
                },
                # Per-event detail
                'events': [
                    {
                        'date': str(row['ex_date'].date()),
                        'day_of_return': float(row['day_of_return']),
                        'pre_near_vol': float(row['pre_near_vol']),
                        'post_near_vol': float(row['post_near_vol']),
                        'control_vol': float(row['control_vol']),
                    }
                    for _, row in event_df.iterrows()
                ],
            }

        # =====================================================================
        # Part 4: Fill Rate Analysis
        # =====================================================================
        print(f"\n[5] 填息率分析")

        fill_df = fill_rate_analysis(df, div_info)

        if len(fill_df) == 0:
            print("  [警告] 填息分析無有效事件")
            fill_results = {'error': 'no valid events'}
        else:
            filled = fill_df[fill_df['filled'] == True]
            not_filled = fill_df[fill_df['filled'] == False]

            fill_rate = len(filled) / len(fill_df)
            print(f"  填息率: {fill_rate:.2%} ({len(filled)}/{len(fill_df)})")

            if len(filled) > 0:
                print(f"  平均填息天數: {filled['fill_days'].mean():.1f} 天")
                print(f"  填息天數中位數: {filled['fill_days'].median():.1f} 天")
                print(f"  最快填息: {filled['fill_days'].min():.0f} 天")
                print(f"  最慢填息: {filled['fill_days'].max():.0f} 天")

            if len(not_filled) > 0:
                print(f"  未填息次數: {len(not_filled)} (60天內未回到除息前價格)")

            # Vol comparison: fast fill vs slow fill
            if len(filled) >= 4:
                median_fill = filled['fill_days'].median()
                fast = filled[filled['fill_days'] <= median_fill]
                slow = filled[filled['fill_days'] > median_fill]

                fast_vol = fast['fill_vol'].dropna()
                slow_vol = slow['fill_vol'].dropna()

                if len(fast_vol) > 1 and len(slow_vol) > 1:
                    t_fill, p_fill = stats.ttest_ind(fast_vol, slow_vol)
                    print(f"\n  快填息 (≤{median_fill:.0f}天) 平均 vol: {fast_vol.mean():.4f}")
                    print(f"  慢填息 (>{median_fill:.0f}天) 平均 vol: {slow_vol.mean():.4f}")
                    print(f"  t-test: t={t_fill:.3f}, p={p_fill:.4f}")
                else:
                    t_fill, p_fill = np.nan, np.nan
            else:
                t_fill, p_fill = np.nan, np.nan

            # Vol: filled vs not filled
            if len(filled) > 1 and len(not_filled) > 1:
                filled_vol = filled['fill_vol'].dropna()
                notfilled_vol = not_filled['fill_vol'].dropna()
                if len(filled_vol) > 1 and len(notfilled_vol) > 1:
                    t_fn, p_fn = stats.ttest_ind(filled_vol, notfilled_vol)
                    print(f"\n  填息組 vol: {filled_vol.mean():.4f}")
                    print(f"  未填息組 vol: {notfilled_vol.mean():.4f}")
                    print(f"  t-test: t={t_fn:.3f}, p={p_fn:.4f}")
                else:
                    t_fn, p_fn = np.nan, np.nan
            else:
                t_fn, p_fn = np.nan, np.nan

            fill_results = {
                'fill_rate': float(fill_rate),
                'n_filled': int(len(filled)),
                'n_not_filled': int(len(not_filled)),
                'n_total': int(len(fill_df)),
                'avg_fill_days': float(filled['fill_days'].mean()) if len(filled) > 0 else None,
                'median_fill_days': float(filled['fill_days'].median()) if len(filled) > 0 else None,
                'fast_vs_slow_fill_vol': {
                    't': float(t_fill) if not np.isnan(t_fill) else None,
                    'p': float(p_fill) if not np.isnan(p_fill) else None,
                },
                'filled_vs_notfilled_vol': {
                    't': float(t_fn) if not np.isnan(t_fn) else None,
                    'p': float(p_fn) if not np.isnan(p_fn) else None,
                },
                'events': [
                    {
                        'date': str(row['ex_date'].date()),
                        'year': int(row['year']),
                        'div_yield': float(row['div_yield']) if not np.isnan(row['div_yield']) else None,
                        'filled': bool(row['filled']),
                        'fill_days': int(row['fill_days']) if not np.isnan(row['fill_days']) else None,
                        'fill_vol': float(row['fill_vol']) if not np.isnan(row['fill_vol']) else None,
                    }
                    for _, row in fill_df.iterrows()
                ],
            }

        # =====================================================================
        # Part 5: Monthly Vol Analysis
        # =====================================================================
        print(f"\n[6] 月份波動率效應")

        monthly_vol = monthly_vol_analysis(df)

        # Ex-dividend season (based on detected months)
        ex_div_months = set(div_info['month'].unique())
        non_ex_months = set(range(1, 13)) - ex_div_months

        ex_season_vols = [monthly_vol[m]['annualized_vol'] for m in ex_div_months if m in monthly_vol]
        non_season_vols = [monthly_vol[m]['annualized_vol'] for m in non_ex_months if m in monthly_vol]

        print(f"\n  除息月份 {sorted(ex_div_months)}: 平均年化vol = {np.mean(ex_season_vols):.4f}")
        print(f"  非除息月份: 平均年化vol = {np.mean(non_season_vols):.4f}")

        # Also check summer months (6-8) specifically
        summer_vols = [monthly_vol[m]['annualized_vol'] for m in [6, 7, 8]]
        other_vols = [monthly_vol[m]['annualized_vol'] for m in range(1, 13) if m not in [6, 7, 8]]

        print(f"\n  6-8月（傳統除息旺季）: 平均年化vol = {np.mean(summer_vols):.4f}")
        print(f"  其他月份: 平均年化vol = {np.mean(other_vols):.4f}")

        # Monthly detail
        print(f"\n  月份別波動率:")
        for m in range(1, 13):
            v = monthly_vol[m]
            ex_marker = " ★" if m in ex_div_months else ""
            print(f"    {m:2d}月: vol={v['annualized_vol']:.4f}, n={v['n_days']:4d}{ex_marker}")

        # Welch t-test on daily returns by season
        returns = df['Close'].pct_change().dropna()
        summer_rets = returns[returns.index.month.isin([6, 7, 8])]
        other_rets = returns[~returns.index.month.isin([6, 7, 8])]

        # Levene test for variance equality
        levene_stat, levene_p = stats.levene(summer_rets, other_rets)
        # F-test for variance ratio
        f_stat = float(summer_rets.var() / other_rets.var())

        print(f"\n  Levene test (variance equality): stat={levene_stat:.3f}, p={levene_p:.4f}")
        print(f"  F-ratio (summer/other variance): {f_stat:.4f}")

        monthly_results = {
            'monthly_vol': {str(k): v for k, v in monthly_vol.items()},
            'ex_div_months': sorted(list(ex_div_months)),
            'ex_season_avg_vol': float(np.mean(ex_season_vols)),
            'non_season_avg_vol': float(np.mean(non_season_vols)),
            'summer_avg_vol': float(np.mean(summer_vols)),
            'other_avg_vol': float(np.mean(other_vols)),
            'levene_test': {'stat': float(levene_stat), 'p': float(levene_p)},
            'f_ratio_summer_other': float(f_stat),
        }

        # =====================================================================
        # Part 6: VT Strategy Implications
        # =====================================================================
        print(f"\n[7] 對 VT 策略的影響分析")

        # Compare: vol around ex-div vs normal
        # Key question: Is the ex-div day return "real" volatility or just mechanical?

        # Compute vol excluding ex-div day returns
        returns_no_exdiv = returns.copy()
        for ex_date in ex_dates:
            if ex_date in returns_no_exdiv.index:
                returns_no_exdiv.loc[ex_date] = np.nan
        returns_no_exdiv = returns_no_exdiv.dropna()

        vol_with_exdiv = float(returns.std() * np.sqrt(252))
        vol_without_exdiv = float(returns_no_exdiv.std() * np.sqrt(252))
        vol_reduction = (vol_with_exdiv - vol_without_exdiv) / vol_with_exdiv

        print(f"  含除息日 vol: {vol_with_exdiv:.4f}")
        print(f"  排除除息日 vol: {vol_without_exdiv:.4f}")
        print(f"  vol 減少比例: {vol_reduction:.4%}")

        # Rolling 22-day vol comparison: ex-div months vs other months
        rv22 = compute_realized_vol(returns, window=22).dropna()
        rv22_summer = rv22[rv22.index.month.isin([6, 7, 8])]
        rv22_other = rv22[~rv22.index.month.isin([6, 7, 8])]

        print(f"\n  22日滾動vol — 6-8月: mean={rv22_summer.mean():.4f}, median={rv22_summer.median():.4f}")
        print(f"  22日滾動vol — 其他月: mean={rv22_other.mean():.4f}, median={rv22_other.median():.4f}")

        # Mannwhitney U test (non-parametric)
        u_stat, u_p = stats.mannwhitneyu(rv22_summer, rv22_other, alternative='two-sided')
        print(f"  Mann-Whitney U test: U={u_stat:.0f}, p={u_p:.4f}")

        vt_implications = {
            'vol_with_exdiv': vol_with_exdiv,
            'vol_without_exdiv': vol_without_exdiv,
            'vol_reduction_pct': float(vol_reduction),
            'rv22_summer_mean': float(rv22_summer.mean()),
            'rv22_summer_median': float(rv22_summer.median()),
            'rv22_other_mean': float(rv22_other.mean()),
            'rv22_other_median': float(rv22_other.median()),
            'mannwhitney_u': {'U': float(u_stat), 'p': float(u_p)},
        }

        # =====================================================================
        # Compile results for this asset
        # =====================================================================
        all_results[symbol] = {
            'name': name,
            'data_period': f"{df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}",
            'n_trading_days': int(len(df)),
            'descriptive_stats': desc_stats,
            'dividend_summary': div_summary,
            'event_study': event_results,
            'fill_rate': fill_results,
            'monthly_vol': monthly_results,
            'vt_implications': vt_implications,
        }

    # =========================================================================
    # Part 7: Cross-asset comparison (0050 vs 0056)
    # =========================================================================
    print(f"\n{'='*70}")
    print("跨資產比較: 0050.TW vs 0056.TW")
    print(f"{'='*70}")

    cross_comparison = {}
    if '0050.TW' in all_results and '0056.TW' in all_results:
        r50 = all_results['0050.TW']
        r56 = all_results['0056.TW']

        if 'error' not in r50 and 'error' not in r56:
            # Compare dividend characteristics
            print(f"\n  0050 除息次數: {r50['dividend_summary']['n_events']}, "
                  f"平均殖利率: {r50['dividend_summary']['avg_yield']*100 if r50['dividend_summary']['avg_yield'] else 'N/A':.2f}%")
            print(f"  0056 除息次數: {r56['dividend_summary']['n_events']}, "
                  f"平均殖利率: {r56['dividend_summary']['avg_yield']*100 if r56['dividend_summary']['avg_yield'] else 'N/A':.2f}%")

            # Compare event study vol patterns
            if 'error' not in r50.get('event_study', {}) and 'error' not in r56.get('event_study', {}):
                print(f"\n  Event Study 波動率比較:")
                print(f"  {'Window':<25} {'0050':>10} {'0056':>10}")
                print(f"  {'-'*45}")
                for key in ['pre_far', 'pre_near', 'post_near', 'post_fill', 'control']:
                    v50 = r50['event_study']['avg_vol'].get(key, 'N/A')
                    v56 = r56['event_study']['avg_vol'].get(key, 'N/A')
                    labels = {
                        'pre_far': '遠除息前 [-10,-6]',
                        'pre_near': '近除息前 [-5,-1]',
                        'post_near': '近除息後 [+1,+5]',
                        'post_fill': '填息期 [+6,+22]',
                        'control': '控制組',
                    }
                    if isinstance(v50, float) and isinstance(v56, float):
                        print(f"  {labels[key]:<25} {v50:>10.4f} {v56:>10.4f}")

            # Compare fill rates
            if 'error' not in r50.get('fill_rate', {}) and 'error' not in r56.get('fill_rate', {}):
                print(f"\n  填息率比較:")
                print(f"  0050: {r50['fill_rate']['fill_rate']:.2%} "
                      f"(avg {r50['fill_rate']['avg_fill_days']:.1f} days)" if r50['fill_rate']['avg_fill_days'] else "")
                print(f"  0056: {r56['fill_rate']['fill_rate']:.2%} "
                      f"(avg {r56['fill_rate']['avg_fill_days']:.1f} days)" if r56['fill_rate']['avg_fill_days'] else "")

            cross_comparison = {
                'note': '0050 is broad market ETF, 0056 is high-dividend ETF',
                'div_yield_comparison': {
                    '0050_avg_yield': r50['dividend_summary']['avg_yield'],
                    '0056_avg_yield': r56['dividend_summary']['avg_yield'],
                },
            }

    results['assets_results'] = all_results
    results['cross_comparison'] = cross_comparison

    # =========================================================================
    # Summary & Conclusions
    # =========================================================================
    print(f"\n{'='*70}")
    print("總結與結論")
    print(f"{'='*70}")

    conclusions = []

    for symbol in ['0050.TW', '0056.TW']:
        if symbol not in all_results or 'error' in all_results[symbol]:
            continue
        r = all_results[symbol]
        es = r.get('event_study', {})

        if 'error' in es:
            continue

        name = r['name']

        # Conclusion 1: Vol around ex-div
        avg_vol = es['avg_vol']
        ctrl = avg_vol['control']
        pre = avg_vol['pre_near']
        post = avg_vol['post_near']

        if abs(pre - ctrl) / ctrl > 0.1:
            direction = "高於" if pre > ctrl else "低於"
            conclusions.append(f"{name}: 除息前5天 vol ({pre:.4f}) {direction}控制組 ({ctrl:.4f})")
        else:
            conclusions.append(f"{name}: 除息前5天 vol ({pre:.4f}) 與控制組 ({ctrl:.4f}) 無顯著差異")

        # Conclusion 2: Day-of return
        day_abs = es['day_of_abs_return']['mean']
        avg_abs = es['day_of_abs_return']['avg_abs_return_all_days']
        ratio = day_abs / avg_abs
        conclusions.append(f"{name}: 除息日平均|報酬| ({day_abs:.4f}) 是普通日 ({avg_abs:.4f}) 的 {ratio:.1f}x")

        # Conclusion 3: Fill rate
        fr = r.get('fill_rate', {})
        if 'error' not in fr:
            conclusions.append(f"{name}: 填息率 {fr['fill_rate']:.0%}, 平均填息 {fr['avg_fill_days']:.0f} 天"
                             if fr['avg_fill_days'] else f"{name}: 填息率 {fr['fill_rate']:.0%}")

        # Conclusion 4: Monthly effect
        mv = r.get('monthly_vol', {})
        summer = mv.get('summer_avg_vol', 0)
        other = mv.get('other_avg_vol', 0)
        if other > 0:
            diff_pct = (summer - other) / other * 100
            conclusions.append(f"{name}: 6-8月 vol ({summer:.4f}) vs 其他月 ({other:.4f}), 差異 {diff_pct:+.1f}%")

    for i, c in enumerate(conclusions, 1):
        print(f"  {i}. {c}")

    results['conclusions'] = conclusions

    # Limitations
    limitations = [
        "除息日偵測可能遺漏部分事件（yfinance 資料可能不完整）",
        "填息分析使用 60 天上限，長期填息（>60天）被歸為未填息",
        "控制組為隨機選取的非除息期，可能包含其他事件",
        "ETF 除息與個股除息的機制不同（ETF 是淨值調整，非公司決策）",
        "台灣 ETF 除息制度歷年有變化（如半年配、季配的引入）",
        "未控制整體市場趨勢（牛市/熊市期間的填息率自然不同）",
    ]
    results['limitations'] = limitations

    # References
    results['references'] = [
        "Elton, E.J. & Gruber, M.J. (1970). Marginal Stockholder Tax Rates and the Clientele Effect. RES.",
        "Frank, M. & Jagannathan, R. (1998). Why do stock prices drop by less than the value of the dividend? JFE.",
        "台灣證交所除權息參考價計算規則",
        "元大投信 0050/0056 公開說明書",
    ]

    print(f"\n  局限性:")
    for l in limitations:
        print(f"    - {l}")

    return results


if __name__ == '__main__':
    results = run_experiment()

    # Save results
    output_path = 'experiments/k512_tw_exdividend_results.json'

    # Clean up non-serializable types
    def clean_for_json(obj):
        if isinstance(obj, dict):
            return {k: clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_for_json(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Timestamp):
            return str(obj)
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        elif obj is np.nan or (isinstance(obj, float) and np.isnan(obj)):
            return None
        return obj

    results_clean = clean_for_json(results)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results_clean, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n結果已儲存: {output_path}")
