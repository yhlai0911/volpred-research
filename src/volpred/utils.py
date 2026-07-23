"""VolPred utility functions for data cleaning and common operations."""

import warnings

import pandas as pd

# Known 0050.TW split breakpoints in yfinance data
# Yahoo pre-applied the 2025-06-18 1:4 split, but only from 2014-01-02 onwards.
# Pre-2014 prices are ~4x too high compared to post-2014.
_TW50_SPLIT_DATE = "2014-01-02"
_TW50_SPLIT_RATIO = 4.0

# Daily moves beyond this are treated as suspected data artifacts, not as data.
_EXTREME_RETURN_THRESHOLD = 0.50

# Every extreme-return detection, appended in call order. A caller that wants to
# assert "my sample was never touched" reads this instead of trusting silence.
EXTREME_RETURN_INCIDENTS: list[dict] = []


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

    # Residual extreme returns: report, do not silently rewrite.
    #
    # This used to zero every |return| > 50% and rebuild the whole price series
    # by cumprod — silently, with no warning and no record. On 0050 that was
    # meant as a safety net for the split artifact repaired above, but the
    # function is called from ~130 sites, and any genuine extreme single-day
    # move in a longer sample would have been erased without trace.
    #
    # Measured before changing it (2026-07-21): across all 15 real 0050.TW
    # series in the repo (spans from 2009-01-02 to 2026-07-10, 1,700-4,287 obs
    # each) the mask fires on **zero** days — the split repair above already
    # removes the only break that produced one. So warning instead of zeroing
    # is byte-identical on every series this repo actually holds, and the
    # silent-corruption path stops existing for the ones it does not.
    clean_returns = clean_prices.pct_change()
    extreme_mask = clean_returns.abs() > _EXTREME_RETURN_THRESHOLD
    if extreme_mask.any():
        offenders = clean_returns[extreme_mask]
        EXTREME_RETURN_INCIDENTS.append(
            {
                "n_days": int(len(offenders)),
                "dates": [str(d) for d in offenders.index],
                "returns": [float(v) for v in offenders.values],
                "threshold": _EXTREME_RETURN_THRESHOLD,
                "span": (str(clean_prices.index.min()), str(clean_prices.index.max())),
            }
        )
        preview = ", ".join(
            f"{d}: {v:+.2%}" for d, v in list(offenders.items())[:5]
        )
        warnings.warn(
            f"clean_tw50_data: {len(offenders)} day(s) exceed "
            f"|return| > {_EXTREME_RETURN_THRESHOLD:.0%} after the 0050 split "
            f"repair and are PRESERVED, not zeroed ({preview}"
            f"{', ...' if len(offenders) > 5 else ''}). If this series is not "
            f"0050.TW, this function's split repair does not apply to it and "
            f"the caller is likely using the wrong cleaner. If it is 0050.TW, "
            f"an unrepaired data break is present — inspect before using.",
            RuntimeWarning,
            stacklevel=2,
        )

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
