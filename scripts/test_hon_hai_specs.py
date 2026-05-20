
import yfinance as yf
from arch import arch_model
import pandas as pd
import numpy as np

def test_hon_hai_all_specs():
    ticker = "2317.TW"
    # Try different data sources/cleanings
    df = yf.download(ticker, start="2008-01-01", end="2026-03-31", auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Try both raw Close and Adj Close
    for price_col in ['Close', 'Adj Close']:
        print(f"\n{'='*40}\nPrice column: {price_col}\n{'='*40}")
        prices = df[price_col].dropna()
        returns = prices.pct_change().dropna()
        # Scale by 100 for arch
        ret_pct = returns * 100
        
        for dist in ['normal', 't']:
            for mean in ['Constant', 'Zero']:
                for cov in ['robust', 'classic']:
                    print(f"\nSpec: {dist}, {mean} mean, {cov} SE")
                    am = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist=dist, mean=mean)
                    res = am.fit(disp='off', cov_type=cov)
                    gamma = res.params.get('gamma[1]')
                    t_stat = res.tvalues.get('gamma[1]')
                    print(f"gamma: {gamma:.4f}, t-stat: {t_stat:.3f}, alpha: {res.params.get('alpha[1]'):.4f}, beta: {res.params.get('beta[1]'):.4f}")

if __name__ == "__main__":
    test_hon_hai_all_specs()
