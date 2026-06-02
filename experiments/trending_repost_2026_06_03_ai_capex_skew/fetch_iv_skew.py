"""
Fetch IV skew data for AI mega-caps + SPY baseline
Evidence package for trending_repost_2026_06_03_ai_capex_skew

Method:
- Pull options chain from yfinance for nearest monthly expiry (>30 days out)
- Compute 25-delta proxy using 90% spot (put) and 110% spot (call) moneyness
- ATM IV approximated at strikes closest to spot
- Realized vol: 30-day trailing daily log return std × sqrt(252)
- IV/RV ratio (vol premium)

Data snapshot only - no historical IV series available via yfinance free API
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

TICKERS = ['META', 'GOOGL', 'MSFT', 'AMZN', 'NVDA', 'SPY']

def get_rv_30d(ticker_obj, period='60d'):
    """30-day realized vol from daily close prices"""
    hist = ticker_obj.history(period=period)
    if len(hist) < 20:
        return np.nan
    log_ret = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
    rv = log_ret.tail(21).std() * np.sqrt(252)
    return rv

def find_nearest_expiry(expirations, min_days=30):
    """Find nearest expiry at least min_days out"""
    today = datetime.today()
    for exp in sorted(expirations):
        exp_date = datetime.strptime(exp, '%Y-%m-%d')
        if (exp_date - today).days >= min_days:
            return exp
    # fallback: return the last available
    return expirations[-1] if expirations else None

def compute_skew(ticker_sym):
    """Compute IV skew metrics for one ticker"""
    t = yf.Ticker(ticker_sym)

    # Current spot price
    info = t.fast_info
    spot = info.last_price
    if spot is None or spot <= 0:
        # fallback to history
        hist = t.history(period='5d')
        spot = float(hist['Close'].iloc[-1]) if len(hist) > 0 else None
    if spot is None:
        return None

    # Find expiry
    expirations = t.options
    if not expirations:
        return None
    expiry = find_nearest_expiry(list(expirations), min_days=25)
    if expiry is None:
        return None

    # Get option chain
    chain = t.option_chain(expiry)
    calls = chain.calls
    puts = chain.puts

    # Strike targets
    atm_target = spot
    put_target = spot * 0.90   # ~25-delta put proxy
    call_target = spot * 1.10  # ~25-delta call proxy

    def find_iv(df, strike_target):
        """Find IV of option closest to target strike"""
        if df.empty:
            return np.nan
        # Filter reasonable strikes
        df = df[(df['strike'] > 0) & (df['impliedVolatility'] > 0.001)]
        if df.empty:
            return np.nan
        idx = (df['strike'] - strike_target).abs().idxmin()
        iv = df.loc[idx, 'impliedVolatility']
        strike_used = df.loc[idx, 'strike']
        return iv, strike_used

    result_atm = find_iv(calls, atm_target)
    result_put = find_iv(puts, put_target)
    result_call = find_iv(calls, call_target)

    atm_iv = result_atm[0] if result_atm and len(result_atm) == 2 else np.nan
    put_iv = result_put[0] if result_put and len(result_put) == 2 else np.nan
    call_iv = result_call[0] if result_call and len(result_call) == 2 else np.nan

    put_strike = result_put[1] if result_put and len(result_put) == 2 else np.nan
    call_strike = result_call[1] if result_call and len(result_call) == 2 else np.nan

    # Skew = put IV - call IV (positive = put premium / downside fear)
    skew = put_iv - call_iv

    # Realized vol
    rv = get_rv_30d(t)

    # IV-RV ratio (vol premium) using ATM IV
    iv_rv_ratio = atm_iv / rv if (not np.isnan(atm_iv) and not np.isnan(rv) and rv > 0) else np.nan

    return {
        'ticker': ticker_sym,
        'spot': round(float(spot), 2),
        'expiry': expiry,
        'atm_iv': round(float(atm_iv), 4) if not np.isnan(atm_iv) else None,
        'put_iv_90pct': round(float(put_iv), 4) if not np.isnan(put_iv) else None,
        'call_iv_110pct': round(float(call_iv), 4) if not np.isnan(call_iv) else None,
        'put_strike': round(float(put_strike), 1) if not np.isnan(put_strike) else None,
        'call_strike': round(float(call_strike), 1) if not np.isnan(call_strike) else None,
        'skew_vol_pts': round(float(skew) * 100, 2) if not np.isnan(skew) else None,  # in vol points %
        'rv_30d': round(float(rv) * 100, 2) if not np.isnan(rv) else None,  # in %
        'iv_rv_ratio': round(float(iv_rv_ratio), 3) if not np.isnan(iv_rv_ratio) else None,
    }

if __name__ == '__main__':
    print("Fetching IV skew data for AI mega-caps + SPY...")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = []
    for sym in TICKERS:
        print(f"  Processing {sym}...", end=' ')
        try:
            row = compute_skew(sym)
            if row:
                results.append(row)
                print(f"spot={row['spot']}, ATM IV={row['atm_iv']}, skew={row['skew_vol_pts']} vol pts")
            else:
                print("FAILED")
        except Exception as e:
            print(f"ERROR: {e}")

    # Save CSV
    df = pd.DataFrame(results)
    out_dir = '/Users/yhlai0911/Desktop/volpred-research/experiments/trending_repost_2026_06_03_ai_capex_skew'
    df.to_csv(f'{out_dir}/data.csv', index=False)
    print(f"\nSaved {len(df)} rows to data.csv")

    # Save JSON
    with open(f'{out_dir}/data.json', 'w') as f:
        json.dump({
            'fetched_at': datetime.now().isoformat(),
            'note': 'Snapshot only — no historical IV series. yfinance free API limitation.',
            'data': results
        }, f, indent=2)

    print("\n=== SUMMARY TABLE ===")
    print(df[['ticker', 'spot', 'atm_iv', 'put_iv_90pct', 'call_iv_110pct',
              'skew_vol_pts', 'rv_30d', 'iv_rv_ratio']].to_string(index=False))
