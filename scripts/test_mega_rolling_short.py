
import yfinance as yf
from arch import arch_model
import pandas as pd
import numpy as np

def test_mega_rolling_short():
    ticker = "2886.TW"
    df = yf.download(ticker, start="2000-01-01", end="2026-03-31", auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    returns = df['Close'].pct_change().dropna()
    ret_pct = returns * 100
    
    for window in [250, 500, 1000]:
        gammas = []
        for i in range(window, len(ret_pct), 250):
            sub = ret_pct.iloc[i-window:i]
            am = arch_model(sub, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
            res = am.fit(disp='off')
            gammas.append(res.params.get('gamma[1]'))
        
        print(f"w={window}: mean={np.mean(gammas):.4f}, max={np.max(gammas):.4f}, min={np.min(gammas):.4f}")

if __name__ == "__main__":
    test_mega_rolling_short()
