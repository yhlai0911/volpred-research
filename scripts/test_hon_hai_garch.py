
import yfinance as yf
from arch import arch_model
import numpy as np

def test_hon_hai():
    ticker = "2317.TW"
    df = yf.download(ticker, start="2008-01-01", end="2026-03-31")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    returns = df['Close'].pct_change().dropna()
    ret_pct = returns * 100
    
    print(f"Sample: {returns.index[0]} to {returns.index[-1]}, N={len(returns)}")
    
    # Paper 2 Table 2 target: gamma = 0.052, t = 1.14
    
    print("\nSpec 1: GJR-Normal, Constant Mean, Robust SE (arch default)")
    am = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
    res = am.fit(disp='off')
    print(res.summary().tables[1])
    
    print("\nSpec 2: GJR-Normal, Zero Mean, Robust SE")
    am2 = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
    res2 = am2.fit(disp='off')
    print(res2.summary().tables[1])

    print("\nSpec 3: GJR-Normal, Constant Mean, Non-robust SE")
    res3 = am.fit(disp='off', cov_type='classic')
    print(res3.summary().tables[1])

if __name__ == "__main__":
    import pandas as pd
    test_hon_hai()
