
import yfinance as yf
from arch import arch_model
import pandas as pd
import numpy as np

def test_mega_expanding():
    ticker = "2886.TW"
    df = yf.download(ticker, start="2000-01-01", end="2026-03-31", auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    returns = df['Close'].pct_change().dropna()
    ret_pct = returns * 100
    
    for end_year in [2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026]:
        sub = ret_pct[ret_pct.index < f"{end_year}-01-01"]
        if len(sub) < 500: continue
        
        am = arch_model(sub, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
        res = am.fit(disp='off')
        gamma = res.params.get('gamma[1]')
        t_stat = res.tvalues.get('gamma[1]')
        print(f"End {end_year}: N={len(sub)}, gamma={gamma:.4f}, t={t_stat:.3f}")

if __name__ == "__main__":
    test_mega_expanding()
