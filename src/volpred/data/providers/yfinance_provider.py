"""Yahoo Finance data provider using the yfinance library."""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from volpred.core.exceptions import DataError


class YFinanceProvider:
    """Fetches OHLCV data from Yahoo Finance via :pypi:`yfinance`."""

    # Mapping from yfinance column names to our internal lowercase names.
    _COLUMN_MAP = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "Adj Close": "adj_close",
    }

    def fetch(
        self,
        ticker: str,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV data from Yahoo Finance.

        Parameters
        ----------
        ticker : str
            Ticker symbol (e.g. ``"AAPL"``).
        start, end : str
            ISO-format date strings (``"YYYY-MM-DD"``).
        interval : str
            Bar interval, default ``"1d"``.

        Returns
        -------
        pd.DataFrame
            DataFrame with columns: open, high, low, close, volume, adj_close.

        Raises
        ------
        DataError
            If the download fails or returns no data.
        """
        import time

        max_retries = 3
        last_exc = None

        for attempt in range(1, max_retries + 1):
            try:
                df = yf.download(
                    ticker,
                    start=start,
                    end=end,
                    interval=interval,
                    progress=False,
                    auto_adjust=False,
                )
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(5 * attempt)
                    continue
                raise DataError(
                    f"Failed to download data for '{ticker}' after {max_retries} attempts: {exc}"
                ) from exc

            if df is not None and not df.empty:
                break

            if attempt < max_retries:
                time.sleep(5 * attempt)
            else:
                raise DataError(
                    f"No data returned for '{ticker}' after {max_retries} attempts "
                    f"(start={start}, end={end}, interval={interval})."
                )

        # yfinance may return MultiIndex columns when downloading a single
        # ticker — flatten if needed.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Rename to our internal convention.
        df = df.rename(columns=self._COLUMN_MAP)

        # Keep only expected columns (ignore extras like 'Capital Gains').
        keep = ["open", "high", "low", "close", "volume", "adj_close"]
        existing = [c for c in keep if c in df.columns]
        df = df[existing]

        # If 'adj_close' is missing, fall back to 'close'.
        if "adj_close" not in df.columns:
            df["adj_close"] = df["close"]

        return df
