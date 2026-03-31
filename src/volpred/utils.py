"""VolPred utility functions for data cleaning and common operations."""

import pandas as pd

# Known 0050.TW split breakpoints in yfinance data
# Yahoo pre-applied the 2025-06-18 1:4 split, but only from 2014-01-02 onwards.
# Pre-2014 prices are ~4x too high compared to post-2014.
_TW50_SPLIT_DATE = "2014-01-02"
_TW50_SPLIT_RATIO = 4.0


def clean_tw50_data(prices: pd.Series, returns: pd.Series = None) -> tuple:
    """Fix 0050.TW stock split artifacts in yfinance data.

    Problem:
    - Yahoo Finance 把 2025-06-18 的 1:4 分割回溯應用到歷史數據
    - 但只從 2014-01-02 起調整，2013 年以前的價格未除以 4
    - 造成 2014-01-02 出現假 -75% 回報
    - yfinance splits metadata 空，repair=True 也無法修復

    Fix:
    - 偵測 2014-01-02 斷點（pre-split 價格 ÷ split_ratio）
    - 將 2014-01-02 之前的所有價格除以 4，使整個序列連續
    - 重新計算 returns

    Args:
        prices: 0050.TW price series (Close or Adj Close)
        returns: pre-computed returns (optional, will recompute after fix)

    Returns:
        (clean_prices, clean_returns) tuple
    """
    clean_prices = prices.copy()

    # Find the split breakpoint
    split_date = pd.Timestamp(_TW50_SPLIT_DATE)

    # Check if the breakpoint exists in our data
    if split_date in clean_prices.index:
        pre_split_mask = clean_prices.index < split_date

        if pre_split_mask.any():
            # Check if there's actually a discontinuity
            last_pre = clean_prices[pre_split_mask].iloc[-1]
            first_post = clean_prices.loc[split_date]

            ratio = last_pre / first_post
            # If ratio is close to 4 (within 10%), apply the fix
            if 3.5 < ratio < 4.5:
                clean_prices[pre_split_mask] = clean_prices[pre_split_mask] / _TW50_SPLIT_RATIO

    # Also handle any remaining extreme returns (safety net)
    clean_returns = clean_prices.pct_change()
    extreme_mask = clean_returns.abs() > 0.50
    if extreme_mask.any():
        clean_returns[extreme_mask] = 0.0
        # Reconstruct prices from cleaned returns
        base = clean_prices.iloc[0]
        cum = (1 + clean_returns.fillna(0)).cumprod()
        clean_prices = base * cum

    clean_returns = clean_prices.pct_change()
    return clean_prices, clean_returns


def download_tw50_clean(start="2006-01-01", end=None):
    """Download and clean 0050.TW data from yfinance.

    Handles:
    - Stock split price discontinuity (2014-01-02: pre-split prices ÷ 4)
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
