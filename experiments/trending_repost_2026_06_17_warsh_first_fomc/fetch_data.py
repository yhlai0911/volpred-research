"""
fetch_data.py — 抓取 FOMC/Vol 跨資產數據
數據來源：yfinance + FRED
"""
import json
import os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

import yfinance as yf
import pandas as pd
import numpy as np

try:
    import fredapi
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False
    print("fredapi not available, will use yfinance for rates data")

# 時間範圍：近 90 日
END_DATE = datetime(2026, 6, 17)
START_DATE = END_DATE - timedelta(days=120)

def fetch_yfinance_data():
    """抓取 VIX, VIX9D, MOVE"""
    tickers = {
        '^VIX': 'vix',
        '^VIX9D': 'vix9d',
        '^MOVE': 'move',
    }

    data = {}
    for ticker, name in tickers.items():
        try:
            df = yf.download(ticker, start=START_DATE.strftime('%Y-%m-%d'),
                           end=END_DATE.strftime('%Y-%m-%d'), progress=False)
            if not df.empty:
                # yfinance 可能返回 MultiIndex columns
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                data[name] = df['Close']
                print(f"✓ {ticker}: {len(df)} rows, latest={df['Close'].iloc[-1]:.2f} on {df.index[-1].date()}")
            else:
                print(f"✗ {ticker}: no data returned")
                data[name] = pd.Series(dtype=float)
        except Exception as e:
            print(f"✗ {ticker}: {e}")
            data[name] = pd.Series(dtype=float)

    return data

def fetch_fred_data():
    """抓取 FRED 數據：CPI, T10Y2Y, SOFR"""
    fred_series = {}

    if FRED_AVAILABLE:
        try:
            # 嘗試無 API key 方式（某些 series 公開可取）
            fred = fredapi.Fred()

            for series_id in ['CPIAUCSL', 'T10Y2Y', 'DFEDTARU', 'SOFR']:
                try:
                    s = fred.get_series(series_id,
                                       observation_start=START_DATE.strftime('%Y-%m-%d'),
                                       observation_end=END_DATE.strftime('%Y-%m-%d'))
                    fred_series[series_id] = s
                    print(f"✓ FRED {series_id}: {len(s)} obs, latest={s.iloc[-1]:.4f}")
                except Exception as e:
                    print(f"✗ FRED {series_id}: {e}")
        except Exception as e:
            print(f"FRED API error: {e}")

    # Fallback：用 yfinance 的替代品
    # ^TNX = 10Y Treasury, ^TYX = 30Y Treasury
    fallback_tickers = {
        '^TNX': 'us10y_yield',
        '^IRX': 'us3m_yield',
        '^FVX': 'us5y_yield',
    }

    for ticker, name in fallback_tickers.items():
        try:
            df = yf.download(ticker, start=START_DATE.strftime('%Y-%m-%d'),
                           end=END_DATE.strftime('%Y-%m-%d'), progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                fred_series[name] = df['Close']
                print(f"✓ {ticker}: {len(df)} rows, latest={df['Close'].iloc[-1]:.2f}")
        except Exception as e:
            print(f"✗ {ticker}: {e}")

    return fred_series

if __name__ == '__main__':
    print("=" * 60)
    print("Fetching Vol + Rates data for FOMC 2026-06-17")
    print("=" * 60)

    yf_data = fetch_yfinance_data()
    fred_data = fetch_fred_data()

    # Save raw data summary
    summary = {
        'fetch_date': END_DATE.strftime('%Y-%m-%d'),
        'start_date': START_DATE.strftime('%Y-%m-%d'),
        'yfinance': {},
        'fred': {}
    }

    for name, series in yf_data.items():
        if len(series) > 0:
            summary['yfinance'][name] = {
                'latest_value': float(series.iloc[-1]),
                'latest_date': str(series.index[-1].date()),
                'n_obs': len(series),
                'mean_30d': float(series.iloc[-30:].mean()),
                'std_30d': float(series.iloc[-30:].std())
            }

    for name, series in fred_data.items():
        if isinstance(series, pd.Series) and len(series) > 0:
            summary['fred'][name] = {
                'latest_value': float(series.iloc[-1]),
                'latest_date': str(series.index[-1].date()),
                'n_obs': len(series),
            }

    out_path = os.path.join(os.path.dirname(__file__), 'raw_data_summary.json')
    with open(out_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n✓ Summary saved to {out_path}")

    # Also save the actual series for analyze.py
    all_series = {}
    for name, s in yf_data.items():
        if len(s) > 0:
            all_series[name] = s
    for name, s in fred_data.items():
        if isinstance(s, pd.Series) and len(s) > 0:
            all_series[name] = s

    # Combine into DataFrame
    if all_series:
        df_combined = pd.DataFrame(all_series)
        csv_path = os.path.join(os.path.dirname(__file__), 'raw_data.csv')
        df_combined.to_csv(csv_path)
        print(f"✓ Raw data CSV saved to {csv_path}")

    print("\nFetch complete.")
