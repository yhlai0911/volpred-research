"""K1535 data preparation — deterministic OHLC-based realized-variance targets.

Downloads daily OHLC for U.S. equity indices + VIX via yfinance, builds three
realized-variance proxies exactly as in the reproduced paper (no 5-min data
needed), and writes a tidy parquet/CSV per index to ``data/``.

RV proxies (all in *percent-return* variance units, i.e. (100*r)^2 scale, to
match the GARCH likelihood code reused from k1533 which models y = 100*logret):

  - cc   : Close-to-Close squared log return.            (100 * log(C_t/C_{t-1}))^2
  - park : Parkinson (1980) high-low range estimator.
  - yz   : Yang-Zhang (2000) OHLC estimator (per-day decomposition).

Covariates for the GARCH-X / HAR-RV-X fair baselines:
  - vix  : prior-session VIX close (level), to be lagged at use time.
  - rv1/rv5/rv22 : HAR-style lagged RV aggregates (built at use time, not here).

All series are aligned on common trading dates. No imputation: rows with any
missing OHLC are dropped (documented count in the output JSON sidecar).

Lag discipline is enforced at *use* time inside k1535.py (every covariate enters
as value dated <= t-1). This file only builds contemporaneous, causally-clean
daily measures from same-day OHLC (an RV proxy for day t legitimately uses day
t's own OHLC — it is the *target*, not a feature).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)

# Paper standardises on these three indices; VIX is the equity-fear covariate.
INDICES = {"GSPC": "^GSPC", "NDX": "^NDX", "DJI": "^DJI"}
VIX_TICKER = "^VIX"
START = "2000-01-01"


def _parkinson_var(high: pd.Series, low: pd.Series) -> pd.Series:
    """Parkinson (1980) daily variance from the high-low range.

    Var = (1 / (4 ln 2)) * (ln(H/L))^2.  Returned in (100*logret)^2 units.
    """
    log_hl = np.log(high / low)
    var = (log_hl ** 2) / (4.0 * np.log(2.0))
    return var * (100.0 ** 2)


def _yang_zhang_daily(opn, high, low, close, prev_close) -> pd.Series:
    """Per-day Yang-Zhang (2000) variance contribution (decomposed, no window).

    The canonical YZ estimator combines overnight, open-to-close, and
    Rogers-Satchell (1991) drift-independent terms.  For a *daily* target we
    use the single-day Rogers-Satchell estimator plus the overnight jump, which
    together capture the OHLC information without needing a rolling window
    (the rolling YZ k-weight only matters for multi-day variance pooling).

    RS_t = ln(H/C)*ln(H/O) + ln(L/C)*ln(L/O)
    ON_t = (ln(O/C_{t-1}))^2                       (overnight jump variance)
    yz_t = ON_t + RS_t                             (drift-independent intraday + overnight)

    Returned in (100*logret)^2 units.  This is the standard "daily Yang-Zhang
    OHLC variance" reported for single-day RV targets.
    """
    ln_ho = np.log(high / opn)
    ln_hc = np.log(high / close)
    ln_lo = np.log(low / opn)
    ln_lc = np.log(low / close)
    rs = ln_hc * ln_ho + ln_lc * ln_lo  # Rogers-Satchell (drift independent)
    overnight = np.log(opn / prev_close) ** 2
    yz = overnight + rs
    return yz * (100.0 ** 2)


def fetch_one(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(
        ticker, start=START, auto_adjust=False, progress=False, threads=False
    )
    if df is None or len(df) == 0:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    # yfinance can return a MultiIndex column frame for a single ticker.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    cols = ["open", "high", "low", "close"]
    df = df[cols].astype(float)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


def build_index_frame(name: str, ticker: str, vix: pd.Series) -> tuple[pd.DataFrame, dict]:
    raw = fetch_one(ticker)
    before = len(raw)
    raw = raw.dropna(subset=["open", "high", "low", "close"])
    # Drop degenerate rows (non-positive prices) which break log measures.
    raw = raw[(raw[["open", "high", "low", "close"]] > 0).all(axis=1)]
    dropped = before - len(raw)

    close = raw["close"]
    prev_close = close.shift(1)
    logret = np.log(close / prev_close)
    ret_pct = 100.0 * logret  # percent log return (GARCH y-scale)

    cc = (ret_pct ** 2)
    park = _parkinson_var(raw["high"], raw["low"])
    yz = _yang_zhang_daily(raw["open"], raw["high"], raw["low"], close, prev_close)

    out = pd.DataFrame(
        {
            "open": raw["open"],
            "high": raw["high"],
            "low": raw["low"],
            "close": close,
            "ret": ret_pct,         # percent log return
            "rv_cc": cc,            # close-to-close squared return target
            "rv_park": park,        # Parkinson target
            "rv_yz": yz,            # Yang-Zhang daily target
        }
    )
    # Attach contemporaneous VIX (level). Lag applied at use time.
    out = out.join(vix.rename("vix"), how="left")
    # First row has no prev_close → ret/rv_cc/rv_yz NaN; drop it.
    out = out.dropna(subset=["ret", "rv_cc", "rv_park", "rv_yz"])
    # VIX may have isolated gaps; forward-fill ONLY the covariate (never target).
    out["vix"] = out["vix"].ffill()
    out = out.dropna(subset=["vix"])

    meta = {
        "ticker": ticker,
        "n_rows_raw": int(before),
        "n_dropped_bad_ohlc": int(dropped),
        "n_rows_final": int(len(out)),
        "date_start": str(out.index[0].date()),
        "date_end": str(out.index[-1].date()),
    }
    return out, meta


def main(indices=None):
    indices = indices or INDICES
    vix_raw = fetch_one(VIX_TICKER)
    vix = vix_raw["close"]

    meta_all = {}
    for name, ticker in indices.items():
        frame, meta = build_index_frame(name, ticker, vix)
        path = DATA / f"{name.lower()}.parquet"
        frame.to_parquet(path)
        meta_all[name] = meta
        print(
            f"[{name}] {meta['n_rows_final']} rows "
            f"{meta['date_start']}..{meta['date_end']} "
            f"(dropped {meta['n_dropped_bad_ohlc']} bad OHLC) -> {path.name}"
        )

    (DATA / "data_meta.json").write_text(json.dumps(meta_all, indent=2))
    print(f"wrote {DATA / 'data_meta.json'}")


if __name__ == "__main__":
    # Allow `python prepare_data.py GSPC` to fetch a single index (smoke).
    if len(sys.argv) > 1:
        sel = {k: INDICES[k] for k in sys.argv[1:] if k in INDICES}
        main(sel or INDICES)
    else:
        main()
