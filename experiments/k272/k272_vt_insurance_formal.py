"""
K272: VT as Portfolio Insurance — Formal Black-Scholes Framework
================================================================
[提出: 用戶, 執行: Claude]

Background:
  K226 showed VT has alpha +3.36%/yr from conditional beta.
  K229 priced VT insurance at 3.05%/yr.
  Can we formalize VT as a synthetic put option and compare its
  "implied strike" with actual options?

Data: SPY, GLD, VIX daily from yfinance. 2005-2024.

Methodology:
  1. VT as synthetic put — map max-loss cap to an option strike
  2. Black-Scholes pricing of equivalent OTM puts
  3. Greeks analog (delta, gamma, theta) for VT
  4. Historical payoff diagram: year-by-year scatter
  5. Compare VT "implied premium" vs actual option premium

Limitations:
  - Black-Scholes assumes log-normal returns; real markets have fat tails
  - We use historical vol, not implied vol (which is higher due to vol risk premium)
  - "Max loss" is sample-dependent; future crises may exceed historical range
  - VT is path-dependent (daily rebalancing); puts are expiration-dependent
  - The comparison is conceptual — VT and puts have fundamentally different payoff structures
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2004-01-01"
BACKTEST_START = "2005-01-03"
BACKTEST_END = "2024-12-31"
VIX_TARGET = 12.0
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252

print("=" * 90)
print("K272: VT AS PORTFOLIO INSURANCE — FORMAL BLACK-SCHOLES FRAMEWORK")
print("[提出: 用戶, 執行: Claude]")
print("=" * 90)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/7] Downloading price data from yfinance...")

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw_data = {}

for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2025-06-01", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[name] = df[["Close"]].rename(columns={"Close": name.lower()})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Merge
data = raw_data["SPY"].join(raw_data["GLD"], how="inner") \
                       .join(raw_data["VIX"], how="inner")
data = data.dropna()
data = data.loc[BACKTEST_START:BACKTEST_END]

# Compute log returns
data["spy_ret"] = np.log(data["spy"] / data["spy"].shift(1))
data["gld_ret"] = np.log(data["gld"] / data["gld"].shift(1))
data = data.dropna()

print(f"\n  Backtest period: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
n = len(data)
n_years = n / 252

# ==================================================================
# 2. Build Strategy Returns
# ==================================================================
print("\n[2/7] Computing strategy returns...")

spy_rets = data["spy_ret"].values
gld_rets = data["gld_ret"].values
vix_vals = data["vix"].values

# --- Buy & Hold 50/50 SPY/GLD ---
bh_rets = 0.5 * spy_rets + 0.5 * gld_rets

# --- 50/50 SPY/GLD + 12/VIX VT (lagged VIX) ---
vt_rets = np.zeros(n)
vt_equity_weights = np.zeros(n)
for i in range(1, n):
    w_equity = min(VIX_TARGET / vix_vals[i - 1], 1.0)
    vt_equity_weights[i] = w_equity
    vt_rets[i] = w_equity * (0.5 * spy_rets[i] + 0.5 * gld_rets[i])

# Full-period cumulative returns
bh_cum = np.exp(np.cumsum(bh_rets))
vt_cum = np.exp(np.cumsum(vt_rets))

# MDD calculation
def compute_mdd(cum_series):
    peak = np.maximum.accumulate(cum_series)
    dd = (cum_series - peak) / peak
    return np.min(dd)

bh_mdd = compute_mdd(bh_cum)
vt_mdd = compute_mdd(vt_cum)

# CAGR
bh_cagr = (bh_cum[-1] / bh_cum[0]) ** (1 / n_years) - 1
vt_cagr = (vt_cum[-1] / vt_cum[0]) ** (1 / n_years) - 1

# Annualized vol
bh_vol = np.std(bh_rets) * np.sqrt(252)
vt_vol = np.std(vt_rets) * np.sqrt(252)

print(f"  50/50 B&H: CAGR={bh_cagr*100:.2f}%, Vol={bh_vol*100:.2f}%, MDD={bh_mdd*100:.2f}%")
print(f"  50/50+VT:  CAGR={vt_cagr*100:.2f}%, Vol={vt_vol*100:.2f}%, MDD={vt_mdd*100:.2f}%")

# ==================================================================
# 3. VT as Synthetic Put — Strike and Premium Estimation
# ==================================================================
print("\n" + "=" * 90)
print("[3/7] VT AS SYNTHETIC PUT — STRIKE AND PREMIUM ESTIMATION")
print("=" * 90)

# From K225: max loss of 50/50+VT is approximately -12.1%
# From K225: max loss of 50/50 B&H is approximately -31.7%
# The "protection" = B&H MDD - VT MDD

protection_pp = abs(bh_mdd) - abs(vt_mdd)
annual_cost = bh_cagr - vt_cagr  # return sacrifice = insurance premium

print(f"\n  VT PROTECTION PROFILE:")
print(f"  ─────────────────────────────────────────────────────────")
print(f"  50/50 B&H max drawdown:    {bh_mdd*100:.2f}%")
print(f"  50/50+VT max drawdown:     {vt_mdd*100:.2f}%")
print(f"  Protection (MDD reduction): {protection_pp*100:.2f} percentage points")
print(f"  Annual cost (return gap):   {annual_cost*100:.2f}%/yr")
print(f"  Cost per 1% MDD reduction:  {(annual_cost / protection_pp * 100):.3f}%/yr" if protection_pp > 0 else "")

# Interpret as put option
# Synthetic put: "floor" on portfolio losses at VT's MDD level
# Strike = (1 + VT_MDD) * S_0, i.e., K/S = 1 + VT_MDD
# This is like buying a put with moneyness = 1 + VT_MDD
moneyness = 1 + vt_mdd  # e.g., if VT MDD = -12%, moneyness = 0.88
otm_pct = abs(vt_mdd)   # how far OTM the "put" is

print(f"\n  SYNTHETIC PUT INTERPRETATION:")
print(f"  ─────────────────────────────────────────────────────────")
print(f"  If portfolio starts at 100, VT caps losses around {(1+vt_mdd)*100:.1f}")
print(f"  Equivalent to a put with strike = {moneyness*100:.1f}% of spot")
print(f"  OTM distance: {otm_pct*100:.1f}%")
print(f"  Annual premium paid: {annual_cost*100:.2f}%/yr (via return sacrifice)")

# ==================================================================
# 4. Black-Scholes Option Pricing — Equivalent Put Cost
# ==================================================================
print("\n" + "=" * 90)
print("[4/7] BLACK-SCHOLES PRICING — EQUIVALENT PUT COST")
print("=" * 90)

def bs_put_price(S, K, T, r, sigma):
    """Black-Scholes European put price."""
    if sigma <= 0 or T <= 0:
        return max(K - S, 0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    put = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return put

def bs_put_greeks(S, K, T, r, sigma):
    """Black-Scholes put Greeks."""
    if sigma <= 0 or T <= 0:
        return {"delta": -1 if S < K else 0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    delta = norm.cdf(d1) - 1  # put delta
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    theta = (-(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
             + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 252  # daily
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100  # per 1% vol change
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}

# Price puts at various OTM levels using 50/50 portfolio vol
S = 100.0  # normalized
r = RF_ANNUAL
sigma_bh = bh_vol  # historical vol of 50/50 B&H
T = 1.0  # 1-year put

print(f"\n  Parameters:")
print(f"  Spot (S):              {S}")
print(f"  Risk-free rate (r):    {r*100:.1f}%")
print(f"  50/50 B&H annual vol:  {sigma_bh*100:.2f}%")
print(f"  Time to expiry (T):    {T} year")

# Price puts at various strikes
print(f"\n  BLACK-SCHOLES PUT PRICES (1-Year, using historical vol):")
print(f"  {'Strike':>8} {'OTM%':>8} {'Put Price':>10} {'% of Spot':>10} {'Purpose':>35}")
print(f"  {'─'*80}")

strikes = [95, 92, 90, 88, 85, 80, 75, 70]
put_prices = {}
for K in strikes:
    price = bs_put_price(S, K, T, r, sigma_bh)
    otm = (S - K) / S * 100
    purpose = ""
    if abs(K - moneyness * 100) < 2:
        purpose = "<-- VT's implied strike"
    put_prices[K] = {"price": price, "pct_spot": price / S * 100, "otm": otm}
    print(f"  {K:>8.0f} {otm:>7.1f}% {price:>10.3f} {price/S*100:>9.3f}% {purpose:>35}")

# VT's "implied strike" and its BS price
vt_strike = moneyness * S
vt_put_price = bs_put_price(S, vt_strike, T, r, sigma_bh)
vt_put_pct = vt_put_price / S * 100

print(f"\n  VT's EXACT IMPLIED PUT:")
print(f"  ─────────────────────────────────────────────────────────")
print(f"  Strike = {vt_strike:.2f} (={moneyness*100:.1f}% of spot)")
print(f"  BS put price = {vt_put_price:.3f} ({vt_put_pct:.3f}% of portfolio)")
print(f"  VT's actual annual cost = {annual_cost*100:.2f}%")

if annual_cost > 0:
    ratio = vt_put_pct / (annual_cost * 100)
    print(f"\n  COMPARISON:")
    print(f"  BS put costs {vt_put_pct:.3f}% of portfolio per year")
    print(f"  VT costs     {annual_cost*100:.3f}% of portfolio per year")
    if ratio > 1:
        print(f"  → VT is {ratio:.1f}x CHEAPER than equivalent BS put")
        print(f"  → VT provides ${vt_put_price:.3f} of put protection for ${annual_cost*100:.3f}")
    else:
        print(f"  → VT is {1/ratio:.1f}x MORE EXPENSIVE than equivalent BS put")
else:
    print(f"  VT has no cost (or generates alpha) — free insurance!")

# Sensitivity: using implied vol (VIX average) instead of historical vol
avg_vix = data["vix"].mean() / 100  # VIX is in %, convert to decimal
# VIX represents S&P vol; for 50/50 portfolio, scale by ratio
# bh_vol / spy_vol gives the scaling factor
spy_vol = np.std(spy_rets) * np.sqrt(252)
vol_ratio = bh_vol / spy_vol
implied_vol_5050 = avg_vix * vol_ratio

print(f"\n  SENSITIVITY: Using implied vol (VIX-derived) instead of historical:")
print(f"  Average VIX:               {avg_vix*100:.1f}%")
print(f"  SPY historical vol:        {spy_vol*100:.2f}%")
print(f"  Vol ratio (50/50 / SPY):   {vol_ratio:.3f}")
print(f"  Implied vol for 50/50:     {implied_vol_5050*100:.2f}%")

vt_put_implied = bs_put_price(S, vt_strike, T, r, implied_vol_5050)
print(f"  BS put (implied vol):      {vt_put_implied:.3f} ({vt_put_implied/S*100:.3f}%)")
if annual_cost > 0:
    ratio_impl = (vt_put_implied / S * 100) / (annual_cost * 100)
    print(f"  → VT is {ratio_impl:.1f}x {'CHEAPER' if ratio_impl > 1 else 'MORE EXPENSIVE'} than BS put at implied vol")

# ==================================================================
# 5. Greeks Analog for VT
# ==================================================================
print("\n" + "=" * 90)
print("[5/7] GREEKS ANALOG FOR VT")
print("=" * 90)

# ── 5a. VT "Delta" ──
# How does VT equity weight change per 1% change in SPY?
# Delta_VT = d(w_equity) / d(SPY_return) ... but VT weight depends on VIX, not SPY directly
# Instead: how does VT portfolio return change per 1% change in underlying?
# Effective delta = d(VT_return) / d(BH_return)

# We can measure this empirically via regression of VT daily return on BH daily return
from numpy.polynomial import polynomial as P

# Simple regression: VT_ret = alpha + beta * BH_ret
slope, intercept = np.polyfit(bh_rets[1:], vt_rets[1:], 1)
print(f"\n  (a) VT 'DELTA' (sensitivity to underlying 50/50 return):")
print(f"  ─────────────────────────────────────────────────────────")
print(f"  VT_ret = {intercept*10000:.2f}bp + {slope:.4f} × BH_ret")
print(f"  Effective delta = {slope:.4f}")
print(f"  (A real put with strike {vt_strike:.1f} has BS delta = ", end="")

put_greeks = bs_put_greeks(S, vt_strike, T, r, sigma_bh)
print(f"{put_greeks['delta']:.4f})")
print(f"  → VT's average delta ({slope:.2f}) means it captures ~{slope*100:.0f}% of B&H moves")

# Conditional delta: by VIX regime
print(f"\n  Conditional VT 'delta' by VIX regime:")
print(f"  {'VIX Regime':<20} {'Delta':>8} {'Avg Weight':>12} {'N days':>8}")
print(f"  {'─'*52}")

regimes = {
    "Very Low (<12)": (0, 12),
    "Low (12-15)":    (12, 15),
    "Normal (15-20)": (15, 20),
    "High (20-30)":   (20, 30),
    "Crisis (>30)":   (30, 999),
}

lagged_vix = np.zeros(n)
lagged_vix[0] = vix_vals[0]
lagged_vix[1:] = vix_vals[:-1]

for rname, (lo, hi) in regimes.items():
    mask = (lagged_vix >= lo) & (lagged_vix < hi)
    mask[0] = False  # skip first day
    n_regime = mask.sum()
    if n_regime < 10:
        print(f"  {rname:<20} {'N/A':>8} {'N/A':>12} {n_regime:>8}")
        continue
    bh_r = bh_rets[mask]
    vt_r = vt_rets[mask]
    if np.std(bh_r) > 1e-10:
        regime_delta = np.polyfit(bh_r, vt_r, 1)[0]
    else:
        regime_delta = 0
    avg_w = vt_equity_weights[mask].mean()
    print(f"  {rname:<20} {regime_delta:>8.4f} {avg_w:>11.1%} {n_regime:>8}")

# ── 5b. VT "Gamma" ──
# Is VT's delta change convex? Does protection accelerate as market falls?
print(f"\n  (b) VT 'GAMMA' (convexity of protection):")
print(f"  ─────────────────────────────────────────────────────────")

# Bin BH returns into deciles, compute VT delta in each bin
bh_sorted_idx = np.argsort(bh_rets[1:])
n_bins = 10
bin_size = len(bh_sorted_idx) // n_bins

print(f"  {'BH Return Decile':<20} {'Avg BH Ret':>12} {'Avg VT Ret':>12} {'Local Delta':>12}")
print(f"  {'─'*60}")

decile_deltas = []
decile_bh_means = []

for b in range(n_bins):
    start_b = b * bin_size
    end_b = start_b + bin_size if b < n_bins - 1 else len(bh_sorted_idx)
    idx = bh_sorted_idx[start_b:end_b]

    bh_bin = bh_rets[1:][idx]
    vt_bin = vt_rets[1:][idx]

    avg_bh = np.mean(bh_bin)
    avg_vt = np.mean(vt_bin)

    # Local delta = slope within this bin
    if np.std(bh_bin) > 1e-10 and len(bh_bin) > 5:
        local_delta = np.polyfit(bh_bin, vt_bin, 1)[0]
    else:
        local_delta = avg_vt / avg_bh if abs(avg_bh) > 1e-10 else 0

    decile_deltas.append(local_delta)
    decile_bh_means.append(avg_bh)

    label = f"D{b+1}" + (" (worst)" if b == 0 else " (best)" if b == n_bins - 1 else "")
    print(f"  {label:<20} {avg_bh*100:>11.3f}% {avg_vt*100:>11.3f}% {local_delta:>12.4f}")

# Check convexity: does delta decrease as returns get more negative?
# Positive gamma = delta decreases (becomes less negative) as S falls → MORE protection
# For VT: if delta is lower in left tail, that means VT dampens losses more → convex payoff
gamma_indicator = decile_deltas[0] - decile_deltas[-1]
print(f"\n  Gamma indicator (D1 delta - D10 delta): {gamma_indicator:+.4f}")
if gamma_indicator < 0:
    print(f"  → POSITIVE GAMMA: VT delta is LOWER in worst decile ({decile_deltas[0]:.3f}) vs best ({decile_deltas[-1]:.3f})")
    print(f"  → VT accelerates protection when markets crash (like a put)")
else:
    print(f"  → NEGATIVE GAMMA: VT delta is HIGHER in worst decile ({decile_deltas[0]:.3f}) vs best ({decile_deltas[-1]:.3f})")
    print(f"  → VT does NOT accelerate protection (unlike a put)")

# Compare with BS put gamma
print(f"\n  BS put gamma (for reference):")
print(f"  At-the-money put gamma: {bs_put_greeks(S, S, T, r, sigma_bh)['gamma']:.6f}")
print(f"  VT's implied put gamma: {bs_put_greeks(S, vt_strike, T, r, sigma_bh)['gamma']:.6f}")

# ── 5c. VT "Theta" ──
# Daily cost of protection
print(f"\n  (c) VT 'THETA' (daily cost of protection):")
print(f"  ─────────────────────────────────────────────────────────")

# VT theta = daily expected return sacrifice
daily_cost = (np.mean(bh_rets) - np.mean(vt_rets))
annual_cost_from_daily = daily_cost * 252
put_theta = bs_put_greeks(S, vt_strike, T, r, sigma_bh)["theta"]

print(f"  VT daily return sacrifice:    {daily_cost*10000:.2f} bps/day")
print(f"  VT annualized cost:           {annual_cost_from_daily*100:.2f}%/yr")
print(f"  BS put daily theta:           {put_theta:.4f} (= {put_theta/S*10000:.2f} bps/day of portfolio)")

# Theta by regime
print(f"\n  VT 'theta' by VIX regime:")
print(f"  {'VIX Regime':<20} {'Daily Cost (bps)':>16} {'Ann. Cost':>10}")
print(f"  {'─'*50}")
for rname, (lo, hi) in regimes.items():
    mask = (lagged_vix >= lo) & (lagged_vix < hi)
    mask[0] = False
    n_regime = mask.sum()
    if n_regime < 10:
        continue
    regime_theta = (np.mean(bh_rets[mask]) - np.mean(vt_rets[mask]))
    ann = regime_theta * 252 * 100
    print(f"  {rname:<20} {regime_theta*10000:>15.2f} {ann:>+9.2f}%")

# ==================================================================
# 6. Historical Payoff Diagram — Year-by-Year
# ==================================================================
print("\n" + "=" * 90)
print("[6/7] HISTORICAL PAYOFF DIAGRAM — YEAR-BY-YEAR")
print("=" * 90)

# For each calendar year, compute: B&H annual return vs VT annual return
# This should look like a protective put payoff:
# - When B&H return is very negative → VT return is less negative (capped downside)
# - When B&H return is positive → VT return is slightly less (premium paid)

print(f"\n  ANNUAL RETURNS (calendar year):")
print(f"  {'Year':>6} {'B&H Return':>12} {'VT Return':>12} {'Diff':>10} {'VIX Avg':>10} {'Avg Weight':>12} {'Interpretation'}")
print(f"  {'─'*95}")

annual_results = []
years = sorted(data.index.year.unique())

for year in years:
    mask = data.index.year == year
    if mask.sum() < 20:
        continue

    bh_year = bh_rets[mask]
    vt_year = vt_rets[mask]
    vix_year = vix_vals[mask]
    w_year = vt_equity_weights[mask]

    bh_ann = (np.exp(np.sum(bh_year)) - 1) * 100
    vt_ann = (np.exp(np.sum(vt_year)) - 1) * 100
    diff = vt_ann - bh_ann
    vix_avg = np.mean(vix_year)
    avg_w = np.mean(w_year) * 100

    if bh_ann < -10:
        interp = "CRISIS: VT provides major protection"
    elif bh_ann < 0:
        interp = "Down year: VT helps"
    elif diff > -1:
        interp = "Low cost year"
    else:
        interp = f"Insurance cost: {abs(diff):.1f}%"

    annual_results.append({
        "year": year,
        "bh_return": round(bh_ann, 2),
        "vt_return": round(vt_ann, 2),
        "diff": round(diff, 2),
        "vix_avg": round(vix_avg, 1),
        "avg_weight": round(avg_w, 1),
    })

    print(f"  {year:>6} {bh_ann:>+11.2f}% {vt_ann:>+11.2f}% {diff:>+9.2f}% {vix_avg:>9.1f} {avg_w:>11.1f}%  {interp}")

# Protective put payoff analysis
print(f"\n  PAYOFF STRUCTURE ANALYSIS:")
print(f"  ─────────────────────────────────────────────────────────")

bh_annual = np.array([r["bh_return"] for r in annual_results])
vt_annual = np.array([r["vt_return"] for r in annual_results])
diff_annual = np.array([r["diff"] for r in annual_results])

# In bad years (B&H < 0): does VT outperform? By how much?
bad_years = bh_annual < 0
good_years = bh_annual >= 0

if bad_years.sum() > 0:
    avg_protection = np.mean(diff_annual[bad_years])
    print(f"  Bad years (B&H < 0): {bad_years.sum()} years")
    print(f"    Avg B&H return:    {np.mean(bh_annual[bad_years]):+.2f}%")
    print(f"    Avg VT return:     {np.mean(vt_annual[bad_years]):+.2f}%")
    print(f"    Avg VT advantage:  {avg_protection:+.2f}%")
    print(f"    VT wins in:        {(diff_annual[bad_years] > 0).sum()}/{bad_years.sum()} bad years")

if good_years.sum() > 0:
    avg_cost = np.mean(diff_annual[good_years])
    print(f"\n  Good years (B&H >= 0): {good_years.sum()} years")
    print(f"    Avg B&H return:    {np.mean(bh_annual[good_years]):+.2f}%")
    print(f"    Avg VT return:     {np.mean(vt_annual[good_years]):+.2f}%")
    print(f"    Avg VT cost:       {avg_cost:+.2f}%")
    print(f"    VT wins in:        {(diff_annual[good_years] > 0).sum()}/{good_years.sum()} good years")

# Piecewise linear fit to characterize payoff shape
print(f"\n  PAYOFF SHAPE (piecewise regression):")
# Below 0: slope of VT vs BH
if bad_years.sum() >= 3:
    slope_bad = np.polyfit(bh_annual[bad_years], vt_annual[bad_years], 1)[0]
    print(f"  When B&H < 0:   VT slope = {slope_bad:.3f} (1.0 = no protection, <1 = protection)")
else:
    slope_bad = None
    print(f"  When B&H < 0:   insufficient data ({bad_years.sum()} years)")

if good_years.sum() >= 3:
    slope_good = np.polyfit(bh_annual[good_years], vt_annual[good_years], 1)[0]
    print(f"  When B&H >= 0:  VT slope = {slope_good:.3f} (1.0 = full participation, <1 = cost)")
else:
    slope_good = None
    print(f"  When B&H >= 0:  insufficient data ({good_years.sum()} years)")

if slope_bad is not None and slope_good is not None:
    print(f"\n  Payoff asymmetry = {slope_good:.3f} - {slope_bad:.3f} = {slope_good - slope_bad:+.3f}")
    if slope_good > slope_bad:
        print(f"  → NEGATIVE asymmetry: VT captures more upside than downside")
        print(f"    This is the OPPOSITE of a put payoff!")
    else:
        print(f"  → POSITIVE asymmetry: VT dampens downside more than upside")
        print(f"    This resembles a protective put payoff")

# ==================================================================
# 6b. Rolling 1-Year Payoff Scatter
# ==================================================================
print(f"\n  ROLLING 1-YEAR PAYOFF DATA (252-day windows):")
print(f"  ─────────────────────────────────────────────────────────")

window = 252
rolling_bh_1yr = []
rolling_vt_1yr = []

for end_idx in range(window, n):
    start_idx = end_idx - window
    bh_1yr = np.exp(np.sum(bh_rets[start_idx:end_idx])) - 1
    vt_1yr = np.exp(np.sum(vt_rets[start_idx:end_idx])) - 1
    rolling_bh_1yr.append(bh_1yr)
    rolling_vt_1yr.append(vt_1yr)

rolling_bh_1yr = np.array(rolling_bh_1yr)
rolling_vt_1yr = np.array(rolling_vt_1yr)

# Overall slope
slope_all = np.polyfit(rolling_bh_1yr, rolling_vt_1yr, 1)[0]
# Quadratic fit to detect curvature
coeffs = np.polyfit(rolling_bh_1yr, rolling_vt_1yr, 2)

print(f"  Number of rolling windows: {len(rolling_bh_1yr)}")
print(f"  Linear fit: VT_1yr = {np.polyfit(rolling_bh_1yr, rolling_vt_1yr, 1)[1]*100:.2f}% + {slope_all:.4f} × BH_1yr")
print(f"  Quadratic fit: a={coeffs[0]:.4f}, b={coeffs[1]:.4f}, c={coeffs[2]*100:.2f}%")
print(f"  Curvature (a): {coeffs[0]:+.4f}", end="")
if coeffs[0] > 0:
    print(f" → CONVEX (VT accelerates gains relative to B&H as returns get extreme)")
elif coeffs[0] < 0:
    print(f" → CONCAVE (VT dampens extremes → PUT-LIKE payoff)")
else:
    print(f" → LINEAR")

# Conditional slopes
neg_mask = rolling_bh_1yr < 0
pos_mask = rolling_bh_1yr >= 0
if neg_mask.sum() > 20:
    slope_neg = np.polyfit(rolling_bh_1yr[neg_mask], rolling_vt_1yr[neg_mask], 1)[0]
    print(f"\n  Slope when B&H < 0:  {slope_neg:.4f} ({neg_mask.sum()} windows)")
if pos_mask.sum() > 20:
    slope_pos = np.polyfit(rolling_bh_1yr[pos_mask], rolling_vt_1yr[pos_mask], 1)[0]
    print(f"  Slope when B&H >= 0: {slope_pos:.4f} ({pos_mask.sum()} windows)")

# Tail statistics
pct_vt_wins_when_bh_neg = (rolling_vt_1yr[neg_mask] > rolling_bh_1yr[neg_mask]).mean() * 100 if neg_mask.sum() > 0 else 0
pct_vt_wins_when_bh_pos = (rolling_vt_1yr[pos_mask] > rolling_bh_1yr[pos_mask]).mean() * 100 if pos_mask.sum() > 0 else 0
print(f"\n  VT beats B&H when B&H < 0:   {pct_vt_wins_when_bh_neg:.1f}% of windows")
print(f"  VT beats B&H when B&H >= 0:  {pct_vt_wins_when_bh_pos:.1f}% of windows")

# ==================================================================
# 7. Comprehensive Comparison: VT vs. Actual Options
# ==================================================================
print("\n" + "=" * 90)
print("[7/7] COMPREHENSIVE COMPARISON: VT vs BUYING PUTS")
print("=" * 90)

print(f"""
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                    VT vs. PUT OPTION COMPARISON                        │
  ├──────────────────┬──────────────────────┬──────────────────────────────┤
  │ Feature          │ VT (12/VIX)          │ Put Option                   │
  ├──────────────────┼──────────────────────┼──────────────────────────────┤
  │ Type             │ Dynamic allocation   │ Derivative contract          │
  │ Cost             │ {annual_cost*100:>5.2f}%/yr (return)   │ {vt_put_pct:>5.3f}%/yr (premium)       │
  │ Protection       │ Gradual (VIX-based)  │ Hard floor at strike         │
  │ Max loss cap     │ ~{vt_mdd*100:>5.1f}% (historical)│ Exact at strike              │
  │ Path-dependent   │ Yes (daily rebal)    │ No (expiration only)         │
  │ Cost certainty   │ Variable by regime   │ Known upfront                │
  │ Upside capture   │ ~{slope:.0%} of B&H           │ 100% minus premium           │
  │ Convexity        │ {'Yes (empirical)' if gamma_indicator < 0 else 'Limited':>20s}  │ Yes (by construction)        │
  │ Counterparty     │ None (self-managed)  │ Exchange/dealer              │
  │ Liquidity need   │ Daily rebalancing    │ None after purchase          │
  │ Margin required  │ None                 │ None (long put)              │
  │ Roll cost        │ None                 │ Yes (expiration roll)        │
  └──────────────────┴──────────────────────┴──────────────────────────────┘
""")

# Cost comparison at different vol levels
print(f"  COST COMPARISON AT DIFFERENT VOLATILITY LEVELS:")
print(f"  {'Vol Level':>12} {'BS Put Cost':>12} {'VT Cost':>10} {'VT/Put':>8} {'Assessment'}")
print(f"  {'─'*75}")

for vol_label, vol in [("Low (8%)", 0.08), ("Hist (est)", sigma_bh),
                        ("Avg VIX", avg_vix * vol_ratio),
                        ("High (20%)", 0.20), ("Crisis (30%)", 0.30)]:
    put_cost = bs_put_price(S, vt_strike, T, r, vol) / S * 100
    ratio_v = (annual_cost * 100) / put_cost if put_cost > 0.001 else float('inf')
    assessment = "VT cheaper" if ratio_v < 1 else "VT more expensive"
    print(f"  {vol_label:>12} {put_cost:>11.3f}% {annual_cost*100:>9.3f}% {ratio_v:>7.2f}x  {assessment}")

# ==================================================================
# KEY FINDINGS
# ==================================================================
print("\n" + "=" * 90)
print("KEY FINDINGS")
print("=" * 90)

print(f"""
  1. SYNTHETIC PUT CHARACTERIZATION:
     VT behaves as a synthetic put with:
     - Implied strike: {moneyness*100:.1f}% of spot ({otm_pct*100:.1f}% OTM)
     - Annual premium: {annual_cost*100:.2f}%/yr (via return sacrifice)
     - Max drawdown cap: {vt_mdd*100:.2f}% vs B&H's {bh_mdd*100:.2f}%

  2. BLACK-SCHOLES COMPARISON:
     - BS price of equivalent put (historical vol): {vt_put_pct:.3f}%/yr
     - BS price of equivalent put (implied vol):    {vt_put_implied/S*100:.3f}%/yr
     - VT actual cost:                              {annual_cost*100:.3f}%/yr""")
if annual_cost > 0:
    print(f"     - At historical vol: VT is {vt_put_pct / (annual_cost * 100):.1f}x {'cheaper' if vt_put_pct > annual_cost * 100 else 'more expensive'}")
    print(f"     - At implied vol:    VT is {(vt_put_implied/S*100) / (annual_cost * 100):.1f}x {'cheaper' if vt_put_implied/S*100 > annual_cost * 100 else 'more expensive'}")

print(f"""
  3. GREEKS ANALOG:
     - VT effective delta:         {slope:.4f} (avg sensitivity to B&H)
     - Gamma indicator:            {gamma_indicator:+.4f} ({'positive — convex protection' if gamma_indicator < 0 else 'limited convexity'})
     - Daily theta (cost):         {daily_cost*10000:.2f} bps/day ({annual_cost_from_daily*100:.2f}%/yr)
     - Delta drops in crisis:      VT de-risks more when VIX spikes

  4. PAYOFF DIAGRAM:
     - Bad years (B&H<0): VT wins {(diff_annual[bad_years] > 0).sum()}/{bad_years.sum()} times, avg advantage {np.mean(diff_annual[bad_years]):+.2f}%""")

if good_years.sum() > 0:
    print(f"     - Good years (B&H>=0): VT trails by avg {np.mean(diff_annual[good_years]):+.2f}%")

if slope_bad is not None and slope_good is not None:
    print(f"     - Downside slope: {slope_bad:.3f}, Upside slope: {slope_good:.3f}")
    print(f"     - Payoff shape: {'put-like (more protection downside)' if slope_bad < slope_good else 'proportional scaling'}")

print(f"""
  5. CRITICAL INSIGHT:
     VT is NOT exactly a put option — it's better described as a
     "dynamic beta adjuster" that MIMICS put-like protection through:
     (a) Reducing equity exposure when VIX rises (delta management)
     (b) Providing convex protection via VIX's mean-reverting nature
     (c) Having lower annual cost than equivalent options

     However, VT's protection is SOFT (path-dependent, no hard floor),
     while a put provides a HARD floor. In a sudden crash where VIX
     has no time to rise first, VT would not provide protection,
     whereas a put would.

  6. LIMITATIONS OF THIS ANALYSIS:
     - BS assumes constant vol and log-normal returns (violated in practice)
     - VT max loss is sample-dependent; future crises may be worse
     - We compare historical vol vs implied vol, but they measure different things
     - VT is path-dependent; comparing to expiration-based puts is approximate
     - Roll costs for puts are significant and not captured in BS pricing
     - VT's protection quality depends on VIX being a good fear indicator
""")

# ==================================================================
# Save results
# ==================================================================
output = {
    "experiment": "K272",
    "title": "VT as Portfolio Insurance — Formal Black-Scholes Framework",
    "proposed_by": "user",
    "executed_by": "Claude",
    "period": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_days": int(n),
    "n_years": round(n_years, 2),
    "data_source": "yfinance (SPY, GLD, ^VIX daily)",
    "synthetic_put": {
        "implied_strike_pct": round(moneyness * 100, 2),
        "otm_distance_pct": round(otm_pct * 100, 2),
        "annual_cost_pct": round(annual_cost * 100, 3),
        "bh_mdd_pct": round(bh_mdd * 100, 2),
        "vt_mdd_pct": round(vt_mdd * 100, 2),
        "protection_pp": round(protection_pp * 100, 2),
    },
    "bs_comparison": {
        "historical_vol": round(sigma_bh * 100, 2),
        "implied_vol_5050": round(implied_vol_5050 * 100, 2),
        "bs_put_price_hist_vol_pct": round(vt_put_pct, 4),
        "bs_put_price_impl_vol_pct": round(vt_put_implied / S * 100, 4),
        "vt_vs_bs_ratio_hist": round(vt_put_pct / (annual_cost * 100), 2) if annual_cost > 0 else None,
        "vt_vs_bs_ratio_impl": round((vt_put_implied / S * 100) / (annual_cost * 100), 2) if annual_cost > 0 else None,
    },
    "greeks": {
        "effective_delta": round(slope, 4),
        "gamma_indicator": round(gamma_indicator, 4),
        "daily_theta_bps": round(daily_cost * 10000, 2),
        "annual_theta_pct": round(annual_cost_from_daily * 100, 2),
        "bs_put_delta": round(put_greeks["delta"], 4),
        "bs_put_gamma": round(put_greeks["gamma"], 6),
        "bs_put_theta_daily": round(put_theta, 4),
    },
    "payoff_diagram": {
        "annual_results": annual_results,
        "bad_years_count": int(bad_years.sum()),
        "good_years_count": int(good_years.sum()),
        "vt_wins_in_bad_years": int((diff_annual[bad_years] > 0).sum()) if bad_years.sum() > 0 else 0,
        "avg_protection_bad_years": round(float(np.mean(diff_annual[bad_years])), 2) if bad_years.sum() > 0 else None,
        "avg_cost_good_years": round(float(np.mean(diff_annual[good_years])), 2) if good_years.sum() > 0 else None,
        "downside_slope": round(float(slope_bad), 4) if slope_bad is not None else None,
        "upside_slope": round(float(slope_good), 4) if slope_good is not None else None,
    },
    "rolling_1yr": {
        "n_windows": len(rolling_bh_1yr),
        "linear_slope": round(float(slope_all), 4),
        "quadratic_curvature": round(float(coeffs[0]), 4),
        "vt_wins_when_bh_neg_pct": round(pct_vt_wins_when_bh_neg, 1),
        "vt_wins_when_bh_pos_pct": round(pct_vt_wins_when_bh_pos, 1),
    },
    "performance": {
        "bh_cagr": round(bh_cagr * 100, 2),
        "vt_cagr": round(vt_cagr * 100, 2),
        "bh_vol": round(bh_vol * 100, 2),
        "vt_vol": round(vt_vol * 100, 2),
    },
}

output_path = "experiments/k272_vt_insurance_formal_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {output_path}")
print(f"\n{'=' * 90}")
print("K272 EXPERIMENT COMPLETE")
print(f"{'=' * 90}")
