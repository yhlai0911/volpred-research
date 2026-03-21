"""Data preprocessing utilities for volatility estimation."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_log_returns(prices: pd.Series) -> pd.Series:
    """Compute log returns: ln(P_t / P_{t-1}).

    Parameters
    ----------
    prices : pd.Series
        Price series (e.g. close prices).

    Returns
    -------
    pd.Series
        Log returns with the first NaN dropped.
    """
    log_ret = np.log(prices / prices.shift(1))
    return log_ret.dropna()


def compute_simple_returns(prices: pd.Series) -> pd.Series:
    """Compute simple returns: (P_t - P_{t-1}) / P_{t-1}.

    Parameters
    ----------
    prices : pd.Series
        Price series.

    Returns
    -------
    pd.Series
        Simple returns with the first NaN dropped.
    """
    simple_ret = prices.pct_change()
    return simple_ret.dropna()


def compute_parkinson_vol(high: pd.Series, low: pd.Series) -> pd.Series:
    """Compute Parkinson volatility estimator.

    Formula: (1 / (4 * ln(2))) * (ln(H/L))^2

    Parameters
    ----------
    high : pd.Series
        High prices.
    low : pd.Series
        Low prices.

    Returns
    -------
    pd.Series
        Parkinson variance proxy for each observation.
    """
    log_hl = np.log(high / low)
    return (1.0 / (4.0 * np.log(2.0))) * log_hl ** 2


def compute_garman_klass_vol(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.Series:
    """Compute Garman-Klass volatility estimator.

    Formula:
        0.5 * (ln(H/L))^2 - (2*ln(2) - 1) * (ln(C/O))^2

    Parameters
    ----------
    open_ : pd.Series
        Open prices.
    high : pd.Series
        High prices.
    low : pd.Series
        Low prices.
    close : pd.Series
        Close prices.

    Returns
    -------
    pd.Series
        Garman-Klass variance proxy for each observation.
    """
    log_hl = np.log(high / low)
    log_co = np.log(close / open_)
    return 0.5 * log_hl ** 2 - (2.0 * np.log(2.0) - 1.0) * log_co ** 2


def compute_realized_variance_proxy(
    df: pd.DataFrame,
    method: str = "parkinson",
) -> pd.Series:
    """Dispatch to a variance-proxy estimator.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain OHLC columns: ``open``, ``high``, ``low``, ``close``.
    method : str
        Either ``'parkinson'`` or ``'garman_klass'``.

    Returns
    -------
    pd.Series
        Variance proxy series.

    Raises
    ------
    ValueError
        If *method* is unknown or required columns are missing.
    """
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    if method == "parkinson":
        return compute_parkinson_vol(df["high"], df["low"])
    elif method == "garman_klass":
        return compute_garman_klass_vol(
            df["open"], df["high"], df["low"], df["close"]
        )
    else:
        raise ValueError(
            f"Unknown method '{method}'. Use 'parkinson' or 'garman_klass'."
        )


def prepare_model_data(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare raw OHLCV data for model consumption.

    Adds the following columns to a copy of *df*:
    - ``log_return``: log returns from close prices
    - ``simple_return``: simple returns from close prices
    - ``rv_parkinson``: Parkinson variance proxy
    - ``rv_garman_klass``: Garman-Klass variance proxy

    Parameters
    ----------
    df : pd.DataFrame
        Raw OHLCV DataFrame with columns: open, high, low, close, volume.

    Returns
    -------
    pd.DataFrame
        Enriched DataFrame with NaN rows dropped.
    """
    out = df.copy()
    out["log_return"] = np.log(out["close"] / out["close"].shift(1))
    out["returns"] = out["log_return"]  # standard alias for models
    out["simple_return"] = out["close"].pct_change()
    out["rv_parkinson"] = compute_parkinson_vol(out["high"], out["low"])
    out["rv_proxy"] = out["rv_parkinson"]  # default RV proxy
    out["rv_garman_klass"] = compute_garman_klass_vol(
        out["open"], out["high"], out["low"], out["close"]
    )
    out.dropna(inplace=True)
    return out
