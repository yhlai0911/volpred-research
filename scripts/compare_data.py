
import pandas as pd
import yfinance as yf
import numpy as np

def compare_data():
    csv_path = "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
    csv_df = pd.read_csv(csv_path)
    csv_df['date'] = pd.to_datetime(csv_df['date'])
    csv_df.set_index('date', inplace=True)
    
    ticker = "2317.TW"
    yf_df = yf.download(ticker, start="2008-01-01", end="2026-03-31", auto_adjust=True)
    if isinstance(yf_df.columns, pd.MultiIndex):
        yf_df.columns = yf_df.columns.get_level_values(0)
    
    # Align
    common_dates = csv_df.index.intersection(yf_df.index)
    csv_prices = csv_df.loc[common_dates, '2317_tw_adj_close']
    yf_prices = yf_df.loc[common_dates, 'Close']
    
    print(f"Comparing 2317.TW prices (N={len(common_dates)}):")
    print(f"  CSV first 5:\n{csv_prices.head()}")
    print(f"  YF first 5:\n{yf_prices.head()}")
    
    diff = (csv_prices - yf_prices).abs().max()
    print(f"\n  Max abs price diff: {diff}")
    
    csv_ret = csv_prices.pct_change().dropna()
    yf_ret = yf_prices.pct_change().dropna()
    
    ret_diff = (csv_ret - yf_ret).abs().max()
    print(f"  Max abs return diff: {ret_diff}")

if __name__ == "__main__":
    compare_data()
