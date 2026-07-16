"""Download VIX / OVX / WTI daily data for digest_20260716."""
import json
import yfinance as yf
import pandas as pd

OUT = "/Users/yhlai0911/volpred-research/storage/drafts/assets/digest_20260716"

def dl(ticker, start):
    df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

vix = dl("^VIX", "2025-02-01")  # extra buffer for 20d baseline
ovx = dl("^OVX", "2025-02-01")
wti = dl("CL=F", "2026-05-01")

for name, df in [("vix", vix), ("ovx", ovx), ("wti", wti)]:
    if df is not None:
        df[["Close"]].to_csv(f"{OUT}/{name}_close.csv")
        print(name, "rows:", len(df), "first:", df.index[0].date(), "last:", df.index[-1].date(),
              "last close:", round(float(df['Close'].iloc[-1]), 2))
    else:
        print(name, "FAILED")
