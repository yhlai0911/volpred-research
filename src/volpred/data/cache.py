"""SQLite-based cache for price data."""
from __future__ import annotations

import os
import sqlite3
from typing import Optional

import pandas as pd


class DataCache:
    """Persistent SQLite cache for OHLCV price data.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file. Parent directories are created
        automatically if they do not exist.
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS price_data (
            ticker    TEXT NOT NULL,
            date      TEXT NOT NULL,
            open      REAL,
            high      REAL,
            low       REAL,
            close     REAL,
            volume    REAL,
            adj_close REAL,
            PRIMARY KEY (ticker, date)
        )
    """

    def __init__(self, db_path: str = "data/cache/price_cache.db") -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(self._CREATE_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, ticker: str, df: pd.DataFrame) -> None:
        """Upsert rows from *df* into the cache.

        Parameters
        ----------
        ticker : str
            Ticker symbol (e.g. ``"AAPL"``).
        df : pd.DataFrame
            Must have a DatetimeIndex (or a ``date`` column) and OHLCV
            columns.
        """
        records = self._df_to_records(ticker, df)
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO price_data
                (ticker, date, open, high, low, close, volume, adj_close)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        self._conn.commit()

    def load(
        self,
        ticker: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Load cached data for *ticker* within the date range.

        Parameters
        ----------
        ticker : str
            Ticker symbol.
        start, end : str or None
            ISO-format date strings for filtering. ``None`` means no bound.

        Returns
        -------
        pd.DataFrame or None
            Cached data, or ``None`` if no rows match.
        """
        query = "SELECT date, open, high, low, close, volume, adj_close FROM price_data WHERE ticker = ?"
        params: list = [ticker]

        if start is not None:
            query += " AND date >= ?"
            params.append(start)
        if end is not None:
            query += " AND date <= ?"
            params.append(end)

        query += " ORDER BY date"

        rows = self._conn.execute(query, params).fetchall()
        if not rows:
            return None

        df = pd.DataFrame(
            rows,
            columns=["date", "open", "high", "low", "close", "volume", "adj_close"],
        )
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        return df

    def get_date_range(self, ticker: str) -> Optional[tuple[str, str]]:
        """Return ``(min_date, max_date)`` for *ticker*, or ``None``."""
        row = self._conn.execute(
            "SELECT MIN(date), MAX(date) FROM price_data WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return (row[0], row[1])

    def clear(self, ticker: Optional[str] = None) -> None:
        """Clear cached data.

        Parameters
        ----------
        ticker : str or None
            If given, only clear data for that ticker. Otherwise clear all.
        """
        if ticker is not None:
            self._conn.execute(
                "DELETE FROM price_data WHERE ticker = ?", (ticker,)
            )
        else:
            self._conn.execute("DELETE FROM price_data")
        self._conn.commit()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _df_to_records(ticker: str, df: pd.DataFrame) -> list[tuple]:
        """Convert a DataFrame to a list of tuples for SQL insertion."""
        records: list[tuple] = []
        for idx, row in df.iterrows():
            date_str = (
                idx.strftime("%Y-%m-%d")
                if hasattr(idx, "strftime")
                else str(idx)
            )
            records.append((
                ticker,
                date_str,
                float(row.get("open", 0)),
                float(row.get("high", 0)),
                float(row.get("low", 0)),
                float(row.get("close", 0)),
                float(row.get("volume", 0)),
                float(row.get("adj_close", row.get("close", 0))),
            ))
        return records
