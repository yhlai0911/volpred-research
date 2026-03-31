"""VolPred utility functions for data cleaning and common operations."""

import pandas as pd


def clean_tw50_data(prices: pd.Series, returns: pd.Series = None) -> tuple:
    """Fix 0050.TW stock split artifacts in yfinance data.

    yfinance data for 0050.TW has a KNOWN ISSUE:
    - 官方分割日是 2025-06-11（1:4），但 yfinance 原始價格從 2014-01-02 起就已反映分割
    - 2013-12-31 Close=58.70 → 2014-01-02 Close=14.64（÷4.01）
    - yfinance splits metadata 完全沒記錄此分割（Stock Splits 全 0.0）
    - Adj Close 也沒有回溯調整 → 造成 2014-01-02 假 -75% 回報
    - 原因不明（可能是 yfinance 提前應用 2025 分割，或台灣證交所數據問題）

    This function:
    1. Detects split days (|return| > 50%)
    2. Replaces split-day return with 0
    3. Reconstructs clean price series

    Args:
        prices: 0050.TW price series (Close or Adj Close)
        returns: pre-computed returns (optional, will compute if None)

    Returns:
        (clean_prices, clean_returns) tuple

    Usage:
        prices = df['Close']
        clean_p, clean_r = clean_tw50_data(prices)
    """
    if returns is None:
        returns = prices.pct_change()

    # Detect split artifacts: |return| > 50% on a single day
    split_mask = returns.abs() > 0.50
    n_splits = split_mask.sum()

    if n_splits > 0:
        # Replace split returns with 0
        clean_returns = returns.copy()
        clean_returns[split_mask] = 0.0

        # Reconstruct clean prices from returns
        clean_prices = prices.copy()
        base = prices.iloc[0]
        cum = (1 + clean_returns.fillna(0)).cumprod()
        clean_prices = base * cum

        return clean_prices, clean_returns

    return prices, returns


def download_tw50_clean(start="2006-01-01", end=None):
    """Download and clean 0050.TW data from yfinance.

    Handles:
    - Stock split artifacts (2014-01-02 1:4 split)
    - Returns auto_adjust=True (yfinance default)
    - Returns both clean prices and clean returns

    Returns:
        pd.DataFrame with columns: Close, Return (both cleaned)
    """
    import yfinance as yf
    from datetime import datetime

    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    df = yf.download("0050.TW", start=start, end=end, progress=False)
    prices = df["Close"].squeeze()
    clean_p, clean_r = clean_tw50_data(prices)

    result = pd.DataFrame({"Close": clean_p, "Return": clean_r})
    return result
