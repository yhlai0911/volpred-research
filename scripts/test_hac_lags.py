
import yfinance as yf
from arch import arch_model
import pandas as pd
import numpy as np

def test_hac_lags():
    ticker = "2317.TW"
    df = yf.download(ticker, start="2008-01-01", end="2026-03-31", auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    returns = df['Close'].pct_change().dropna()
    ret_pct = returns * 100
    
    am = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
    res_base = am.fit(disp='off')
    print(f"Robust t: {res_base.tvalues.get('gamma[1]'):.3f}")
    
    for lags in [0, 2, 5, 10, 20, 50, 100]:
        # arch.fit uses bandwidth, which for Newey-West is lags + 1
        res = am.fit(disp='off', cov_type='hac', cov_config={'bandwidth': lags})
        print(f"HAC (bandwidth={lags}) t: {res.tvalues.get('gamma[1]'):.3f}")

if __name__ == "__main__":
    test_hac_lags()
