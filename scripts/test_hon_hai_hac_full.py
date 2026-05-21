
import yfinance as yf
from arch import arch_model
import pandas as pd
import numpy as np

def test_hon_hai_hac_full():
    ticker = "2317.TW"
    df = yf.download(ticker, start="2008-01-01", end="2026-03-31", auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    returns = df['Close'].pct_change().dropna()
    ret_pct = returns * 100
    
    print(f"Full Sample: N={len(ret_pct)}")
    
    am = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
    res = am.fit(disp='off', cov_type='hac')
    print("\nFull Sample (Zero Mean, HAC SE):")
    print(f"  gamma: {res.params.get('gamma[1]'):.4f}, t-stat: {res.tvalues.get('gamma[1]'):.3f}")

    am2 = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
    res2 = am2.fit(disp='off', cov_type='hac')
    print("\nFull Sample (Constant Mean, HAC SE):")
    print(f"  gamma: {res2.params.get('gamma[1]'):.4f}, t-stat: {res2.tvalues.get('gamma[1]'):.3f}")

if __name__ == "__main__":
    test_hon_hai_hac_full()
