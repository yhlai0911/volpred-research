
import yfinance as yf
from arch import arch_model
import pandas as pd
import numpy as np

def test_hon_hai_rolling():
    ticker = "2317.TW"
    df = yf.download(ticker, start="2008-01-01", end="2026-03-31", auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    returns = df['Close'].pct_change().dropna()
    ret_pct = returns * 100
    
    window = 2000
    gammas = []
    t_stats = []
    
    for i in range(window, len(ret_pct), 250):
        sub = ret_pct.iloc[i-window:i]
        am = arch_model(sub, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
        res = am.fit(disp='off', cov_type='hac')
        gammas.append(res.params.get('gamma[1]'))
        t_stats.append(res.tvalues.get('gamma[1]'))
    
    print(f"Rolling w={window} (Zero Mean, HAC SE):")
    print(f"  Mean gamma: {np.mean(gammas):.4f}")
    print(f"  Last gamma: {gammas[-1]:.4f}")
    print(f"  Last t-stat: {t_stats[-1]:.3f}")

    # Test w=2000 ending at 2024-12-31
    window = 2000
    sub_2024 = ret_pct.loc[ret_pct.index <= '2024-12-31'].iloc[-window:]
    am = arch_model(sub_2024, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
    res = am.fit(disp='off', cov_type='hac')
    print(f"\nw=2000 ending 2024-12-31 (Zero Mean, HAC SE):")
    print(f"  gamma: {res.params.get('gamma[1]'):.4f}, t-stat: {res.tvalues.get('gamma[1]'):.3f}")
    
    am_c = arch_model(sub_2024, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
    res_c = am_c.fit(disp='off', cov_type='hac')
    print(f"w=2000 ending 2024-12-31 (Constant Mean, HAC SE):")
    print(f"  gamma: {res_c.params.get('gamma[1]'):.4f}, t-stat: {res_c.tvalues.get('gamma[1]'):.3f}")

if __name__ == "__main__":
    test_hon_hai_rolling()
