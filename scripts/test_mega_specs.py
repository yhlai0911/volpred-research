
import yfinance as yf
from arch import arch_model
import pandas as pd
import numpy as np

def test_mega_specs():
    ticker = "2886.TW"
    df = yf.download(ticker, start="2008-01-01", end="2026-03-31", auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Try Adj Close
    price_col = 'Adj Close'
    print(f"\n{'='*40}\nPrice column: {price_col}\n{'='*40}")
    prices = df[price_col].dropna()
    returns = prices.pct_change().dropna()
    ret_pct = returns * 100
    
    for dist in ['normal', 't']:
        for mean in ['Constant', 'Zero']:
            for cov in ['robust', 'classic']:
                print(f"\nSpec: {dist}, {mean} mean, {cov} SE")
                am = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist=dist, mean=mean)
                res = am.fit(disp='off', cov_type=cov)
                gamma = res.params.get('gamma[1]')
                t_stat = res.tvalues.get('gamma[1]')
                alpha = res.params.get('alpha[1]')
                beta = res.params.get('beta[1]')
                persist = alpha + 0.5 * gamma + beta
                print(f"gamma: {gamma:.4f}, t-stat: {t_stat:.3f}, alpha: {alpha:.4f}, beta: {beta:.4f}, persist: {persist:.4f}")

if __name__ == "__main__":
    test_mega_specs()
