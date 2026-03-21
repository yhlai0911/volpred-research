"""Central data access layer for the volpred system."""
from __future__ import annotations

import os

import pandas as pd

from volpred.core.exceptions import DataError
from volpred.core.types import DataRequirement
from volpred.data.cache import DataCache
from volpred.data.preprocessing import prepare_model_data
from volpred.data.providers.yfinance_provider import YFinanceProvider


class DataManager:
    """Orchestrates data fetching, caching, and preprocessing.

    Parameters
    ----------
    cache_dir : str
        Directory where the SQLite cache database is stored.
    """

    def __init__(self, cache_dir: str = "data/cache") -> None:
        self._cache = DataCache(os.path.join(cache_dir, "price_cache.db"))
        self._provider = YFinanceProvider()

    def get_price_data(
        self,
        ticker: str,
        start: str,
        end: str,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Get OHLCV data, using cache when available.

        Parameters
        ----------
        ticker : str
            Ticker symbol.
        start, end : str
            ISO-format date strings.
        force_refresh : bool
            If ``True``, bypass the cache and re-download from provider.

        Returns
        -------
        pd.DataFrame
            OHLCV DataFrame with DatetimeIndex.
        """
        if not force_refresh:
            cached = self._cache.load(ticker, start, end)
            if cached is not None and len(cached) > 0:
                return cached

        df = self._provider.fetch(ticker, start, end)
        self._cache.save(ticker, df)
        return df

    def get_model_data(
        self,
        ticker: str,
        start: str,
        end: str,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Get price data enriched with returns and RV proxies.

        Parameters
        ----------
        ticker : str
            Ticker symbol.
        start, end : str
            ISO-format date strings.
        force_refresh : bool
            If ``True``, bypass the cache and re-download from provider.

        Returns
        -------
        pd.DataFrame
            DataFrame ready for model consumption (NaN rows dropped).
        """
        prices = self.get_price_data(ticker, start, end, force_refresh=force_refresh)
        return prepare_model_data(prices)

    def fulfill_requirement(
        self,
        ticker: str,
        start: str,
        end: str,
        requirement: DataRequirement,
    ) -> pd.DataFrame:
        """Fetch data and validate it meets a model's :class:`DataRequirement`.

        Parameters
        ----------
        ticker : str
            Ticker symbol.
        start, end : str
            ISO-format date strings.
        requirement : DataRequirement
            The specification of what the model needs.

        Returns
        -------
        pd.DataFrame
            Validated, model-ready DataFrame.

        Raises
        ------
        DataError
            If required fields are missing or insufficient data is available.
        """
        data = self.get_model_data(ticker, start, end)

        # Validate required fields exist.
        missing = [f for f in requirement.fields if f not in data.columns]
        if missing:
            raise DataError(f"Missing required fields: {missing}")

        # Validate minimum number of observations.
        if len(data) < requirement.min_periods:
            raise DataError(
                f"Need {requirement.min_periods} periods, got {len(data)}"
            )

        return data
