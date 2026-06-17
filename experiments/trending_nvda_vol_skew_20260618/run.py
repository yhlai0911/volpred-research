"""
NVDA Vol Skew 快照分析 — trending_repost_2026_06_18_ai_波動
目的：抓取 NVDA 當前選擇權 implied volatility skew 狀況
     計算 ATM IV、近似 25Δ put/call IV、realized vol、IV-RV gap
"""

import json
import os
import sys
from datetime import datetime, timedelta

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm


def bs_delta(S, K, T, r, sigma, option_type='call'):
    """Black-Scholes delta calculation."""
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    if option_type == 'call':
        return norm.cdf(d1)
    else:  # put
        return norm.cdf(d1) - 1


def find_25delta_strike(chain_df, S, T, r, option_type, target_delta=0.25):
    """
    Given an option chain, find the strike closest to |delta| = 0.25.
    Returns (strike, iv) or (None, None).
    """
    best_strike = None
    best_iv = None
    min_diff = float('inf')

    for _, row in chain_df.iterrows():
        K = row['strike']
        iv = row['impliedVolatility']
        if iv <= 0 or np.isnan(iv):
            continue
        delta = bs_delta(S, K, T, r, iv, option_type)
        if np.isnan(delta):
            continue
        diff = abs(abs(delta) - target_delta)
        if diff < min_diff:
            min_diff = diff
            best_strike = K
            best_iv = iv

    return best_strike, best_iv


def main():
    output_dir = os.path.dirname(os.path.abspath(__file__))

    print("=== NVDA Vol Skew Snapshot ===")
    print(f"Data retrieval time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ─── 1. 抓 NVDA 現貨價格 ───
    ticker = yf.Ticker("NVDA")
    hist = ticker.history(period="65d")  # 保險 buffer
    if hist.empty:
        print("ERROR: Could not fetch NVDA price history")
        sys.exit(1)

    # 取最新收盤價
    spot = float(hist['Close'].iloc[-1])
    spot_date = hist.index[-1].date()
    print(f"Spot price (latest close): ${spot:.2f} on {spot_date}")

    # 計算 30d realized vol
    returns = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
    rv30 = float(returns.iloc[-30:].std() * np.sqrt(252))
    print(f"30-day Realized Vol (annualized): {rv30:.1%}")

    # ─── 2. 抓 option chain ───
    expiry_dates = ticker.options
    if not expiry_dates:
        print("ERROR: No option expiry dates available")
        sys.exit(1)

    print(f"Available expiry dates: {expiry_dates[:5]}")

    # 選 1-2 個到期日（最近 + 約 30 天後）
    # 找最近一個到期日 (≥7 天後) 和次近的
    today = datetime.now().date()
    valid_expiries = []
    for exp in expiry_dates:
        exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
        days_to_exp = (exp_date - today).days
        if days_to_exp >= 5:  # 排除太近的到期日
            valid_expiries.append((exp, days_to_exp))

    if not valid_expiries:
        print("ERROR: No valid expiry dates found")
        sys.exit(1)

    # 取最近的到期日
    primary_exp, primary_days = valid_expiries[0]
    print(f"Using primary expiry: {primary_exp} ({primary_days} days to expiry)")

    # 取 T (年化)
    T_primary = primary_days / 365.0
    r = 0.053  # 近似美國無風險利率

    chain = ticker.option_chain(primary_exp)
    calls = chain.calls.copy()
    puts = chain.puts.copy()

    print(f"Calls available: {len(calls)} strikes")
    print(f"Puts available: {len(puts)} strikes")

    # ─── 3. 計算關鍵 IV metrics ───

    # ATM IV: 最接近 spot 的 call + put 平均
    calls['dist_atm'] = abs(calls['strike'] - spot)
    puts['dist_atm'] = abs(puts['strike'] - spot)

    atm_call = calls.nsmallest(1, 'dist_atm').iloc[0]
    atm_put = puts.nsmallest(1, 'dist_atm').iloc[0]
    iv_atm_call = float(atm_call['impliedVolatility'])
    iv_atm_put = float(atm_put['impliedVolatility'])
    iv_atm = (iv_atm_call + iv_atm_put) / 2
    atm_strike = float(atm_call['strike'])
    print(f"ATM strike: ${atm_strike:.1f}")
    print(f"ATM Call IV: {iv_atm_call:.1%}, ATM Put IV: {iv_atm_put:.1%}")
    print(f"ATM IV (avg): {iv_atm:.1%}")

    # 25Δ approximation via BS delta
    # 先試精準 BS delta
    print("\nSearching for 25-delta strikes...")

    # 25Δ put (negative delta, |delta| ≈ 0.25) → OTM put (strike < spot)
    otm_puts = puts[puts['strike'] < spot * 0.99].copy()
    otm_calls = calls[calls['strike'] > spot * 1.01].copy()

    strike_25p, iv_25p = find_25delta_strike(otm_puts, spot, T_primary, r, 'put', 0.25)
    strike_25c, iv_25c = find_25delta_strike(otm_calls, spot, T_primary, r, 'call', 0.25)

    # Fallback: spot ±5% 近似
    fallback_used = False
    if strike_25p is None or iv_25p is None or iv_25p == 0:
        print("Fallback: using spot*0.95 for 25Δ put")
        target_k_put = spot * 0.95
        close_puts = puts[(puts['strike'] >= target_k_put * 0.98) &
                          (puts['strike'] <= target_k_put * 1.02)]
        if not close_puts.empty:
            row = close_puts.iloc[0]
            strike_25p = float(row['strike'])
            iv_25p = float(row['impliedVolatility'])
            fallback_used = True

    if strike_25c is None or iv_25c is None or iv_25c == 0:
        print("Fallback: using spot*1.05 for 25Δ call")
        target_k_call = spot * 1.05
        close_calls = calls[(calls['strike'] >= target_k_call * 0.98) &
                             (calls['strike'] <= target_k_call * 1.02)]
        if not close_calls.empty:
            row = close_calls.iloc[0]
            strike_25c = float(row['strike'])
            iv_25c = float(row['impliedVolatility'])
            fallback_used = True

    print(f"25Δ Put — Strike: ${strike_25p:.1f}, IV: {iv_25p:.1%}")
    print(f"25Δ Call — Strike: ${strike_25c:.1f}, IV: {iv_25c:.1%}")

    # Skew = 25Δ put IV - 25Δ call IV (正值 = put skew，左偏，怕崩盤)
    skew_25 = iv_25p - iv_25c
    print(f"25Δ Skew (put - call): {skew_25:+.1%}")

    # IV-RV gap
    iv_rv_gap = iv_atm - rv30
    print(f"IV-RV gap (ATM IV - RV30): {iv_rv_gap:+.1%}")

    # ─── 4. 解讀 ───
    if skew_25 > 0.05:
        skew_signal = "明顯 put skew → 市場更怕下跌（防泡沫態）"
    elif skew_25 > 0.01:
        skew_signal = "溫和 put skew → 防禦意識存在但不強烈"
    elif skew_25 < -0.01:
        skew_signal = "call skew 異常 → 市場更傾向追漲、願意付更高溢價買上行"
    else:
        skew_signal = "skew 接近對稱 → 市場對上下行風險看法均衡"

    print(f"\nSkew 解讀: {skew_signal}")

    # ─── 5. 畫 IV Skew Curve ───
    # 篩選有效 IV 的 puts 和 calls
    puts_plot = puts[
        (puts['impliedVolatility'] > 0.05) &
        (puts['impliedVolatility'] < 2.0) &
        (puts['volume'] > 0)
    ].copy()
    calls_plot = calls[
        (calls['impliedVolatility'] > 0.05) &
        (calls['impliedVolatility'] < 2.0) &
        (calls['volume'] > 0)
    ].copy()

    fig, ax = plt.subplots(figsize=(10, 6))

    if not puts_plot.empty:
        ax.plot(puts_plot['strike'], puts_plot['impliedVolatility'] * 100,
                'b-o', markersize=4, alpha=0.7, label='Put IV')
    if not calls_plot.empty:
        ax.plot(calls_plot['strike'], calls_plot['impliedVolatility'] * 100,
                'r-o', markersize=4, alpha=0.7, label='Call IV')

    # 標記關鍵點
    ax.axvline(spot, color='green', linestyle='--', linewidth=2,
               label=f'Spot ${spot:.0f}')
    if strike_25p:
        ax.axvline(strike_25p, color='blue', linestyle=':', linewidth=1.5,
                   label=f'25Δ Put ${strike_25p:.0f} ({iv_25p:.0%})')
    if strike_25c:
        ax.axvline(strike_25c, color='red', linestyle=':', linewidth=1.5,
                   label=f'25Δ Call ${strike_25c:.0f} ({iv_25c:.0%})')

    # 標 ATM IV
    ax.scatter([atm_strike], [iv_atm * 100], color='gold', s=100, zorder=5,
               label=f'ATM IV {iv_atm:.0%}')

    # 範圍：spot ±30%
    x_min = spot * 0.70
    x_max = spot * 1.30
    ax.set_xlim(x_min, x_max)

    ax.set_xlabel('Strike Price ($)', fontsize=12)
    ax.set_ylabel('Implied Volatility (%)', fontsize=12)
    ax.set_title(f'NVDA IV Skew Curve — {primary_exp} expiry\n'
                 f'Spot ${spot:.0f} | ATM IV {iv_atm:.0%} | '
                 f'25Δ Skew {skew_25:+.0%} | RV30 {rv30:.0%}',
                 fontsize=11)
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.3)

    # 在圖上標注 skew 說明
    ax.text(0.02, 0.98,
            f'Skew 25Δ: {skew_25:+.1%}\n'
            f'解讀: {"Put skew" if skew_25 > 0 else "Call skew"}\n'
            f'IV-RV gap: {iv_rv_gap:+.1%}',
            transform=ax.transAxes, fontsize=9,
            verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))

    plt.tight_layout()
    chart_path = os.path.join(output_dir, 'skew_curve.png')
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nChart saved: {chart_path}")

    # ─── 6. 存 results.json ───
    results = {
        "timestamp": datetime.now().isoformat(),
        "data_date": str(spot_date),
        "asset": "NVDA",
        "source": "yfinance",
        "spot": round(spot, 2),
        "expiry_used": primary_exp,
        "days_to_expiry": primary_days,
        "risk_free_rate": r,
        "sample_N_price_history": len(returns),
        "sample_N_rv30": 30,
        "IV_ATM": round(iv_atm, 4),
        "IV_ATM_call": round(iv_atm_call, 4),
        "IV_ATM_put": round(iv_atm_put, 4),
        "ATM_strike": round(atm_strike, 2),
        "strike_25p": round(strike_25p, 2) if strike_25p else None,
        "IV_25p": round(iv_25p, 4) if iv_25p else None,
        "strike_25c": round(strike_25c, 2) if strike_25c else None,
        "IV_25c": round(iv_25c, 4) if iv_25c else None,
        "skew_25delta": round(skew_25, 4) if (iv_25p and iv_25c) else None,
        "RV30": round(rv30, 4),
        "IV_RV_gap": round(iv_rv_gap, 4),
        "fallback_approximation_used": fallback_used,
        "skew_signal": skew_signal,
        "n_calls_chain": len(calls),
        "n_puts_chain": len(puts),
        "chart_file": "skew_curve.png"
    }

    results_path = os.path.join(output_dir, 'results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Results saved: {results_path}")

    # ─── 7. Summary ───
    print("\n=== SUMMARY ===")
    print(f"NVDA spot: ${spot:.2f}")
    print(f"Expiry: {primary_exp} ({primary_days} days)")
    print(f"ATM IV: {iv_atm:.1%}")
    print(f"25Δ Put IV: {iv_25p:.1%} @ ${strike_25p:.0f}")
    print(f"25Δ Call IV: {iv_25c:.1%} @ ${strike_25c:.0f}")
    print(f"Skew (25Δ put-call): {skew_25:+.1%}")
    print(f"RV30: {rv30:.1%}")
    print(f"IV-RV gap: {iv_rv_gap:+.1%}")
    print(f"Fallback used: {fallback_used}")
    print(f"Signal: {skew_signal}")

    return results


if __name__ == '__main__':
    main()
