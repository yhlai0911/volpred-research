"""
K284: Current Market Assessment (March 2026)
=============================================
What does the CURRENT market environment look like through the lens
of 282+ experiments?

This is a SNAPSHOT experiment — it downloads the most recent data
available and applies every lens our research has developed:
  1. VIX regime classification + term structure
  2. Portfolio recommendation (50/50+VT, TSMOM, risk parity)
  3. Risk assessment (drawdown, correlation, vol clustering)
  4. Historical parallel search
  5. Key risk factors from recent experiments

Data: SPY, GLD, TLT, ^VIX, ^VIX3M, BTC-USD daily from yfinance.
Output: Console report + JSON snapshot.

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
from datetime import datetime, timedelta

# ============================================================
# Helper functions
# ============================================================

def download_clean(ticker, start="2004-01-01", end=None):
    """Download and clean yfinance data."""
    if end is None:
        end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    raw = yf.download(ticker, start=start, end=end, progress=False)
    if raw.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close = raw["Close"].copy()
    close.name = ticker
    ret = close.pct_change().dropna()
    ret.name = f"{ticker}_ret"
    return close, ret


def classify_vix_regime(vix_level):
    """VIX regime classification used throughout research."""
    if vix_level < 15:
        return "Low"
    elif vix_level < 20:
        return "Normal"
    elif vix_level < 30:
        return "High"
    else:
        return "Crisis"


def rolling_trend(series, window=22):
    """Classify rolling trend: rising / falling / stable."""
    if len(series) < window:
        return "insufficient data"
    recent = series.iloc[-window:]
    slope, intercept, r_val, p_val, std_err = stats.linregress(
        np.arange(len(recent)), recent.values
    )
    # slope > 0.1 per day is rising, < -0.1 is falling, otherwise stable
    annualized_slope = slope * 252
    pct_change = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0] * 100
    if p_val < 0.05 and slope > 0:
        return f"Rising (+{pct_change:.1f}% over {window}d, p={p_val:.3f})"
    elif p_val < 0.05 and slope < 0:
        return f"Falling ({pct_change:.1f}% over {window}d, p={p_val:.3f})"
    else:
        return f"Stable ({pct_change:+.1f}% over {window}d, p={p_val:.3f})"


def compute_drawdown(prices):
    """Compute drawdown series from price series."""
    peak = prices.cummax()
    dd = (prices - peak) / peak
    return dd


def tsmom_signal(returns, lookback=126, skip=21):
    """
    Time-series momentum signal (6-1 momentum).
    lookback=126 (6 months), skip last 21 days (1 month reversal).
    Returns True if positive momentum.
    """
    if len(returns) < lookback:
        return None, 0.0
    mom_period = returns.iloc[-(lookback):-skip] if skip > 0 else returns.iloc[-lookback:]
    cum_ret = (1 + mom_period).prod() - 1
    return cum_ret > 0, float(cum_ret)


def vol_cluster_test(returns, window=22):
    """
    Check if we're in a volatility cluster.
    Compare recent vol to trailing 252d vol.
    """
    if len(returns) < 252:
        return "insufficient data", 1.0
    recent_vol = returns.iloc[-window:].std() * np.sqrt(252)
    trailing_vol = returns.iloc[-252:].std() * np.sqrt(252)
    ratio = recent_vol / trailing_vol
    if ratio > 1.5:
        return "Active cluster (vol elevated)", ratio
    elif ratio > 1.2:
        return "Mild elevation", ratio
    elif ratio < 0.7:
        return "Unusually calm", ratio
    else:
        return "Normal", ratio


# ============================================================
# MAIN EXPERIMENT
# ============================================================
print("=" * 72)
print("K284: Current Market Assessment — March 2026 Snapshot")
print("=" * 72)
print(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (local time)")
print()

# ============================================================
# 1. Download all data
# ============================================================
print("[1/5] Downloading market data...")

spy_close, spy_ret = download_clean("SPY", start="2004-01-01")
gld_close, gld_ret = download_clean("GLD", start="2004-01-01")
tlt_close, tlt_ret = download_clean("TLT", start="2004-01-01")
vix_close, _ = download_clean("^VIX", start="2004-01-01")
vix3m_close, _ = download_clean("^VIX3M", start="2007-01-01")
btc_close, btc_ret = download_clean("BTC-USD", start="2015-01-01")

# Align dates
common_idx = spy_close.index.intersection(gld_close.index).intersection(vix_close.index)
latest_date = common_idx[-1]
print(f"  Latest data date: {latest_date.strftime('%Y-%m-%d')}")
print(f"  SPY: ${spy_close.iloc[-1]:.2f} | GLD: ${gld_close.iloc[-1]:.2f} | "
      f"TLT: ${tlt_close.iloc[-1]:.2f}")
if len(btc_close) > 0:
    print(f"  BTC: ${btc_close.iloc[-1]:,.0f}")
print()

# ============================================================
# 2. VIX REGIME ANALYSIS
# ============================================================
print("=" * 72)
print("[2/5] VIX REGIME ANALYSIS")
print("=" * 72)

current_vix = float(vix_close.iloc[-1])
vix_regime = classify_vix_regime(current_vix)
vix_trend = rolling_trend(vix_close, window=22)

# VIX percentile (historical)
vix_pctile = stats.percentileofscore(vix_close.dropna().values, current_vix)

# VIX term structure
if len(vix3m_close) > 0 and vix3m_close.index[-1] >= latest_date - timedelta(days=5):
    current_vix3m = float(vix3m_close.iloc[-1])
    ts_ratio = current_vix / current_vix3m
    if ts_ratio > 1.0:
        ts_state = "BACKWARDATION (stress signal!)"
    elif ts_ratio > 0.95:
        ts_state = "Flat contango"
    elif ts_ratio > 0.85:
        ts_state = "Normal contango"
    else:
        ts_state = "Steep contango (complacency?)"
else:
    current_vix3m = None
    ts_ratio = None
    ts_state = "VIX3M data unavailable"

# 22d realized vol vs VIX (VIX/GARCH ratio proxy)
spy_rvol_22d = float(spy_ret.iloc[-22:].std() * np.sqrt(252) * 100)
vix_rv_ratio = current_vix / spy_rvol_22d

print(f"  Current VIX:           {current_vix:.2f}")
print(f"  VIX Regime:            {vix_regime}")
print(f"  VIX Historical Pctile: {vix_pctile:.0f}th percentile")
print(f"  VIX 22d Trend:         {vix_trend}")
if current_vix3m is not None:
    print(f"  VIX3M:                 {current_vix3m:.2f}")
    print(f"  Term Structure:        {ts_state} (VIX/VIX3M = {ts_ratio:.3f})")
else:
    print(f"  Term Structure:        {ts_state}")
print(f"  SPY 22d RVol:          {spy_rvol_22d:.1f}%")
print(f"  VIX/RVol Ratio:        {vix_rv_ratio:.2f} {'(excess fear)' if vix_rv_ratio > 1.5 else '(normal)' if vix_rv_ratio < 1.3 else '(mild premium)'}")
print()

# ============================================================
# 3. PORTFOLIO RECOMMENDATION
# ============================================================
print("=" * 72)
print("[3/5] PORTFOLIO RECOMMENDATION")
print("=" * 72)

# 3a. 50/50 + VT weight: min(1, 12/VIX) * 50%
w_12vix = min(1.0, 12.0 / current_vix)
w_5050_spy = 0.5 * w_12vix
w_5050_gld = 0.5 * w_12vix
w_5050_cash = max(0, 1.0 - w_5050_spy - w_5050_gld)

print("  [A] 50/50 SPY/GLD + 12/VIX VT (recommended)")
print(f"      Equity weight: {w_12vix*100:.1f}% (12/{current_vix:.1f})")
print(f"      SPY: {w_5050_spy*100:.1f}% | GLD: {w_5050_gld*100:.1f}% | Cash/SHY: {w_5050_cash*100:.1f}%")
print()

# 3b. 12/VIX SPY-only
w_spy_only = w_12vix
cash_spy_only = 1 - w_spy_only
print("  [B] 12/VIX SPY-only + SHY")
print(f"      SPY: {w_spy_only*100:.1f}% | Cash/SHY: {cash_spy_only*100:.1f}%")
print()

# 3c. TSMOM signals (6-1 momentum)
print("  [C] TSMOM Signals (6-month minus 1-month momentum):")
assets_for_mom = {
    "SPY": spy_ret, "GLD": gld_ret, "TLT": tlt_ret
}
if len(btc_ret) > 0:
    assets_for_mom["BTC-USD"] = btc_ret

tsmom_results = {}
for name, rets in assets_for_mom.items():
    is_pos, mom_val = tsmom_signal(rets, lookback=126, skip=21)
    tsmom_results[name] = {"positive": is_pos, "momentum": mom_val}
    signal_str = "LONG" if is_pos else "FLAT" if is_pos is not None else "N/A"
    print(f"      {name:8s}: {signal_str} (6-1 momentum = {mom_val*100:+.2f}%)")

# 3d. TLT conditional (J2 finding: add TLT when 66d mom > 0)
tlt_mom_66 = float(tlt_ret.iloc[-66:].sum()) if len(tlt_ret) >= 66 else None
if tlt_mom_66 is not None:
    print()
    if tlt_mom_66 > 0:
        print(f"  [D] TLT 66d Momentum: POSITIVE ({tlt_mom_66*100:+.2f}%)")
        print("      → Consider Conditional TLT overlay (J2: Sharpe 1.08)")
    else:
        print(f"  [D] TLT 66d Momentum: NEGATIVE ({tlt_mom_66*100:+.2f}%)")
        print("      → Stay with SPY/GLD only (no TLT)")

# 3e. Taiwan 0050.TW (8.63/VIX)
w_tw = min(1.0, 8.63 / current_vix)
cash_tw = 1 - w_tw
print()
print("  [E] Taiwan 0050.TW (8.63/VIX)")
print(f"      0050.TW: {w_tw*100:.1f}% | Cash: {cash_tw*100:.1f}%")
print()

# ============================================================
# 4. RISK ASSESSMENT
# ============================================================
print("=" * 72)
print("[4/5] RISK ASSESSMENT")
print("=" * 72)

# 4a. SPY drawdown from peak
spy_dd = compute_drawdown(spy_close)
current_dd = float(spy_dd.iloc[-1])
peak_date = spy_close.loc[:latest_date].idxmax()
peak_price = float(spy_close.loc[peak_date])

print(f"  SPY Drawdown from Peak:")
print(f"      Current:    {current_dd*100:.2f}%")
print(f"      Peak:       ${peak_price:.2f} on {peak_date.strftime('%Y-%m-%d')}")
print(f"      Current:    ${spy_close.iloc[-1]:.2f}")

# Is this drawdown historically significant?
# Calculate historical rolling 22d returns for context
spy_ret_22d = spy_close.pct_change(22).dropna()
current_22d_ret = float(spy_ret_22d.iloc[-1])
ret_22d_pctile = stats.percentileofscore(spy_ret_22d.values, current_22d_ret)
print(f"      22d Return: {current_22d_ret*100:+.2f}% ({ret_22d_pctile:.0f}th percentile)")
print()

# 4b. GLD-SPY rolling correlation
print("  GLD-SPY Correlation (Is GLD hedge working?):")
for window_label, w in [("22d", 22), ("66d", 66), ("252d", 252)]:
    if len(spy_ret) >= w and len(gld_ret) >= w:
        common = spy_ret.index.intersection(gld_ret.index)
        sp = spy_ret.loc[common].iloc[-w:]
        gl = gld_ret.loc[common].iloc[-w:]
        corr = float(sp.corr(gl))
        print(f"      {window_label}: {corr:+.3f} {'(diversifying)' if corr < 0 else '(positive! less hedge value)' if corr > 0.3 else '(low correlation, OK)'}")
print()

# 4c. Volatility cluster status
print("  Volatility Cluster Status:")
for name, rets in [("SPY", spy_ret), ("GLD", gld_ret), ("TLT", tlt_ret)]:
    status, ratio = vol_cluster_test(rets, window=22)
    print(f"      {name:4s}: {status} (22d/252d ratio = {ratio:.2f})")
print()

# 4d. Overnight gap risk (Phase I4)
if len(spy_close) >= 2:
    # Get OHLC for gap analysis
    spy_raw = yf.download("SPY", start=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                          progress=False)
    if isinstance(spy_raw.columns, pd.MultiIndex):
        spy_raw.columns = spy_raw.columns.get_level_values(0)
    if "Open" in spy_raw.columns and len(spy_raw) >= 2:
        last_gap = float(spy_raw["Open"].iloc[-1]) / float(spy_raw["Close"].iloc[-2]) - 1
        print(f"  Latest Overnight Gap: {last_gap*100:+.3f}%")
        if abs(last_gap) > 0.02:
            print("      → RED ALERT: |gap| > 2% — VaR Lift 4.2x")
        elif abs(last_gap) > 0.015:
            print("      → ORANGE ALERT: |gap| > 1.5% — VaR Lift 4.3x")
        elif abs(last_gap) > 0.01:
            print("      → YELLOW ALERT: |gap| > 1% — VaR Lift 3.1x")
        else:
            print("      → Normal (no gap alert)")
print()

# ============================================================
# 5. HISTORICAL PARALLEL SEARCH
# ============================================================
print("=" * 72)
print("[5/5] HISTORICAL PARALLEL & KEY RISK FACTORS")
print("=" * 72)

# Find historical period most similar to current environment
# Features: VIX level, 22d SPY return, 22d GLD return, VIX trend
print("  Historical Parallel Search:")
print("  (Finding the past period most similar to current conditions)")
print()

# Current features
current_features = {
    "vix": current_vix,
    "spy_22d_ret": current_22d_ret,
}

# Compute GLD 22d return
gld_ret_22d = gld_close.pct_change(22).dropna()
current_gld_22d = float(gld_ret_22d.iloc[-1]) if len(gld_ret_22d) > 0 else 0
current_features["gld_22d_ret"] = current_gld_22d

# Build historical feature matrix (rolling)
# Use VIX, SPY 22d ret, GLD 22d ret
# Align all to common dates
common_hist = vix_close.index.intersection(spy_ret_22d.index).intersection(gld_ret_22d.index)
# Exclude last 22 trading days (too close to current)
if len(common_hist) > 44:
    common_hist = common_hist[:-22]

best_dist = float("inf")
best_date = None
best_features = {}

for dt in common_hist:
    try:
        v = float(vix_close.loc[dt])
        s = float(spy_ret_22d.loc[dt])
        g = float(gld_ret_22d.loc[dt])
    except (KeyError, TypeError):
        continue

    # Normalized distance (VIX in absolute, returns in percentage)
    d_vix = ((v - current_vix) / current_vix) ** 2
    d_spy = ((s - current_22d_ret) / max(abs(current_22d_ret), 0.01)) ** 2
    d_gld = ((g - current_gld_22d) / max(abs(current_gld_22d), 0.01)) ** 2
    dist = d_vix + d_spy + d_gld

    if dist < best_dist:
        best_dist = dist
        best_date = dt
        best_features = {"vix": v, "spy_22d_ret": s, "gld_22d_ret": g}

if best_date is not None:
    print(f"  Most Similar Past Date: {best_date.strftime('%Y-%m-%d')}")
    print(f"      VIX then:      {best_features['vix']:.1f} (now: {current_vix:.1f})")
    print(f"      SPY 22d ret:   {best_features['spy_22d_ret']*100:+.2f}% (now: {current_22d_ret*100:+.2f}%)")
    print(f"      GLD 22d ret:   {best_features['gld_22d_ret']*100:+.2f}% (now: {current_gld_22d*100:+.2f}%)")

    # What happened in the next 22/66/252 days?
    print()
    print("  What Happened Next After That Similar Period:")
    for fwd_label, fwd_days in [("1 month (22d)", 22), ("3 months (66d)", 66), ("1 year (252d)", 252)]:
        fwd_idx = spy_close.index.get_loc(best_date)
        if fwd_idx + fwd_days < len(spy_close):
            fwd_ret = float(spy_close.iloc[fwd_idx + fwd_days]) / float(spy_close.iloc[fwd_idx]) - 1
            fwd_vix = float(vix_close.iloc[min(fwd_idx + fwd_days, len(vix_close) - 1)])
            print(f"      {fwd_label}: SPY {fwd_ret*100:+.2f}%, VIX → {fwd_vix:.1f}")
        else:
            print(f"      {fwd_label}: (not enough forward data)")

print()

# ============================================================
# KEY RISK FACTORS (from recent experiments)
# ============================================================
print("  Key Risk Factors (from K228/K269-K271 findings):")
print()

# Rate hike cycle proxy: TLT trend
if len(tlt_close) >= 252:
    tlt_1yr_ret = float(tlt_close.iloc[-1] / tlt_close.iloc[-252] - 1)
    tlt_6m_ret = float(tlt_close.iloc[-1] / tlt_close.iloc[-126] - 1) if len(tlt_close) >= 126 else None
    print(f"  (a) Interest Rate Cycle (K269-K270 proxy):")
    print(f"      TLT 1-year return:  {tlt_1yr_ret*100:+.2f}%")
    if tlt_6m_ret is not None:
        print(f"      TLT 6-month return: {tlt_6m_ret*100:+.2f}%")
    if tlt_1yr_ret < -0.10:
        print("      → Rates RISING sharply (stress for duration assets)")
    elif tlt_1yr_ret < -0.03:
        print("      → Rates rising moderately")
    elif tlt_1yr_ret > 0.05:
        print("      → Rates FALLING (favorable for bonds)")
    else:
        print("      → Rates roughly stable")
print()

# GLD self-healing (K271): GLD regime
if len(gld_close) >= 252:
    gld_1yr_ret = float(gld_close.iloc[-1] / gld_close.iloc[-252] - 1)
    gld_regime = "BULL" if gld_1yr_ret > 0 else "BEAR"
    print(f"  (b) GLD Self-Healing Status (K271):")
    print(f"      GLD 1-year return: {gld_1yr_ret*100:+.2f}% → Regime: {gld_regime}")
    if gld_regime == "BULL":
        print("      → Inverted leverage → GARCH preferred over GJR for GLD")
    else:
        print("      → Standard leverage → GJR appropriate for GLD")
print()

# Gamma level trend (K228): SPY implied vs realized
print(f"  (c) VIX/Realized Vol Spread (Gamma proxy, K228):")
spy_rvol_66d = float(spy_ret.iloc[-66:].std() * np.sqrt(252) * 100) if len(spy_ret) >= 66 else None
if spy_rvol_66d is not None:
    vix_rv_spread = current_vix - spy_rvol_66d
    print(f"      VIX:         {current_vix:.1f}%")
    print(f"      SPY 66d RVol: {spy_rvol_66d:.1f}%")
    print(f"      Spread:      {vix_rv_spread:+.1f}%")
    if vix_rv_spread > 5:
        print("      → High fear premium (excess fear signal)")
    elif vix_rv_spread > 2:
        print("      → Normal fear premium")
    elif vix_rv_spread < 0:
        print("      → NEGATIVE premium (realized > implied, danger!)")
    else:
        print("      → Low fear premium (complacency?)")
print()

# BTC status
if len(btc_close) > 0 and len(btc_ret) >= 22:
    btc_dd = compute_drawdown(btc_close)
    btc_current_dd = float(btc_dd.iloc[-1])
    btc_vol_22d = float(btc_ret.iloc[-22:].std() * np.sqrt(252) * 100)
    btc_vol_252d = float(btc_ret.iloc[-252:].std() * np.sqrt(252) * 100) if len(btc_ret) >= 252 else None
    print(f"  (d) BTC Risk Status:")
    print(f"      BTC Price:     ${btc_close.iloc[-1]:,.0f}")
    print(f"      BTC Drawdown:  {btc_current_dd*100:.1f}%")
    print(f"      BTC 22d Vol:   {btc_vol_22d:.1f}%")
    if btc_vol_252d:
        print(f"      BTC 252d Vol:  {btc_vol_252d:.1f}%")
    # BTC-SPY correlation
    btc_spy_common = btc_ret.index.intersection(spy_ret.index)
    if len(btc_spy_common) >= 22:
        btc_spy_corr = float(btc_ret.loc[btc_spy_common].iloc[-66:].corr(
            spy_ret.loc[btc_spy_common].iloc[-66:]))
        print(f"      BTC-SPY 66d corr: {btc_spy_corr:+.3f}")
print()

# ============================================================
# COMPOSITE RISK SCORE
# ============================================================
print("=" * 72)
print("COMPOSITE RISK ASSESSMENT")
print("=" * 72)

risk_flags = []
risk_score = 0

# VIX regime
if vix_regime == "Crisis":
    risk_flags.append("VIX in Crisis regime (>30)")
    risk_score += 3
elif vix_regime == "High":
    risk_flags.append("VIX in High regime (20-30)")
    risk_score += 2
elif vix_regime == "Low":
    risk_flags.append("VIX in Low regime (<15) — possible complacency")
    risk_score += 1

# Term structure
if ts_ratio is not None and ts_ratio > 1.0:
    risk_flags.append(f"VIX term structure in BACKWARDATION ({ts_ratio:.3f})")
    risk_score += 2

# Drawdown
if current_dd < -0.10:
    risk_flags.append(f"SPY in significant drawdown ({current_dd*100:.1f}%)")
    risk_score += 2
elif current_dd < -0.05:
    risk_flags.append(f"SPY in moderate drawdown ({current_dd*100:.1f}%)")
    risk_score += 1

# Vol cluster
spy_vol_status, spy_vol_ratio = vol_cluster_test(spy_ret, window=22)
if spy_vol_ratio > 1.5:
    risk_flags.append(f"Active vol cluster (ratio={spy_vol_ratio:.2f})")
    risk_score += 2
elif spy_vol_ratio > 1.2:
    risk_flags.append(f"Mild vol elevation (ratio={spy_vol_ratio:.2f})")
    risk_score += 1

# VIX/RVol ratio
if vix_rv_ratio > 1.5:
    risk_flags.append(f"Excess fear (VIX/RVol={vix_rv_ratio:.2f})")
    risk_score += 1  # Actually protective

# GLD-SPY correlation
if len(spy_ret) >= 66 and len(gld_ret) >= 66:
    common = spy_ret.index.intersection(gld_ret.index)
    gld_spy_corr_66 = float(spy_ret.loc[common].iloc[-66:].corr(gld_ret.loc[common].iloc[-66:]))
    if gld_spy_corr_66 > 0.3:
        risk_flags.append(f"GLD-SPY correlation high ({gld_spy_corr_66:+.3f}) — reduced hedge")
        risk_score += 1

# Rate risk
if len(tlt_close) >= 252 and tlt_1yr_ret < -0.10:
    risk_flags.append(f"Rates rising sharply (TLT {tlt_1yr_ret*100:+.1f}%)")
    risk_score += 1

print()
if risk_score == 0:
    overall = "LOW RISK — Normal conditions, standard allocation appropriate"
elif risk_score <= 2:
    overall = "MODERATE RISK — Some flags, standard allocation OK with monitoring"
elif risk_score <= 4:
    overall = "ELEVATED RISK — Consider defensive tilt (increase cash/GLD)"
elif risk_score <= 6:
    overall = "HIGH RISK — Reduce exposure, increase cash allocation"
else:
    overall = "EXTREME RISK — Maximum defensive posture recommended"

print(f"  Overall Risk Score: {risk_score}/10")
print(f"  Assessment: {overall}")
print()

if risk_flags:
    print("  Active Risk Flags:")
    for i, flag in enumerate(risk_flags, 1):
        print(f"    {i}. {flag}")
else:
    print("  No active risk flags.")
print()

# ============================================================
# FINAL RECOMMENDATION SUMMARY
# ============================================================
print("=" * 72)
print("FINAL RECOMMENDATION SUMMARY")
print("=" * 72)
print()
print(f"  Date:          {latest_date.strftime('%Y-%m-%d')}")
print(f"  VIX:           {current_vix:.2f} ({vix_regime})")
print(f"  Risk Level:    {risk_score}/10")
print()
print("  Recommended Allocation (50/50 SPY/GLD + 12/VIX VT):")
print(f"    SPY:      {w_5050_spy*100:.1f}%")
print(f"    GLD:      {w_5050_gld*100:.1f}%")
print(f"    Cash/SHY: {w_5050_cash*100:.1f}%")
print()

# Actionable insights
print("  Key Actionable Insights:")
insights = []

# VT weight guidance
if w_12vix >= 1.0:
    insights.append(f"VIX ({current_vix:.1f}) below 12 → full equity allocation, no scaling needed")
elif w_12vix >= 0.8:
    insights.append(f"VIX ({current_vix:.1f}) slightly above 12 → near-full allocation ({w_12vix*100:.0f}%)")
elif w_12vix >= 0.5:
    insights.append(f"VIX ({current_vix:.1f}) elevated → reduced allocation ({w_12vix*100:.0f}%), increase cash")
else:
    insights.append(f"VIX ({current_vix:.1f}) very high → significant cash position ({w_5050_cash*100:.0f}% cash)")

# TSMOM guidance
long_assets = [k for k, v in tsmom_results.items() if v["positive"]]
flat_assets = [k for k, v in tsmom_results.items() if v["positive"] is False]
if long_assets:
    insights.append(f"Positive 6-1 momentum: {', '.join(long_assets)}")
if flat_assets:
    insights.append(f"Negative 6-1 momentum (caution): {', '.join(flat_assets)}")

# TLT conditional
if tlt_mom_66 is not None and tlt_mom_66 > 0:
    insights.append("TLT 66d momentum positive → Conditional TLT overlay active (add 10-20% TLT)")
elif tlt_mom_66 is not None:
    insights.append("TLT 66d momentum negative → No TLT exposure")

# Correlation warning
if len(spy_ret) >= 66 and len(gld_ret) >= 66:
    if gld_spy_corr_66 > 0.3:
        insights.append(f"WARNING: GLD-SPY 66d correlation = {gld_spy_corr_66:+.3f} (hedge effectiveness reduced)")

for i, ins in enumerate(insights, 1):
    print(f"    {i}. {ins}")

print()
print("  Limitations:")
print("    - This snapshot reflects one moment in time; conditions change rapidly")
print("    - Historical parallels are rough analogies, not predictions")
print("    - VIX regime thresholds (12/VIX) are empirically robust but not guaranteed")
print("    - All strategies assume monthly rebalancing for best net Sharpe (J10)")
print("    - Based on 282+ experiments but market regimes can be genuinely novel")

# ============================================================
# Save results to JSON
# ============================================================
results = {
    "experiment": "K284",
    "title": "Current Market Assessment — March 2026 Snapshot",
    "timestamp": datetime.now().isoformat(),
    "data_date": latest_date.strftime("%Y-%m-%d"),
    "attribution": "[提出: User, 執行: Claude]",
    "market_data": {
        "SPY": float(spy_close.iloc[-1]),
        "GLD": float(gld_close.iloc[-1]),
        "TLT": float(tlt_close.iloc[-1]),
        "VIX": current_vix,
        "VIX3M": current_vix3m,
        "BTC": float(btc_close.iloc[-1]) if len(btc_close) > 0 else None,
    },
    "vix_analysis": {
        "level": current_vix,
        "regime": vix_regime,
        "percentile": round(vix_pctile, 1),
        "trend_22d": vix_trend,
        "term_structure": {
            "vix3m": current_vix3m,
            "ratio": round(ts_ratio, 4) if ts_ratio else None,
            "state": ts_state,
        },
        "vix_rvol_ratio": round(vix_rv_ratio, 3),
        "spy_rvol_22d": round(spy_rvol_22d, 2),
    },
    "portfolio_recommendation": {
        "strategy": "50/50 SPY/GLD + 12/VIX VT",
        "equity_weight": round(w_12vix, 4),
        "spy_weight": round(w_5050_spy, 4),
        "gld_weight": round(w_5050_gld, 4),
        "cash_weight": round(w_5050_cash, 4),
        "tsmom_signals": {k: {"positive": bool(v["positive"]) if v["positive"] is not None else None,
                              "momentum_6_1": round(float(v["momentum"]), 6)}
                         for k, v in tsmom_results.items()},
        "tlt_66d_momentum": round(float(tlt_mom_66), 6) if tlt_mom_66 is not None else None,
        "tlt_conditional": bool(tlt_mom_66 is not None and tlt_mom_66 > 0),
        "taiwan_0050_weight": round(w_tw, 4),
    },
    "risk_assessment": {
        "spy_drawdown_from_peak": round(current_dd, 6),
        "spy_peak_price": round(peak_price, 2),
        "spy_peak_date": peak_date.strftime("%Y-%m-%d"),
        "spy_22d_return": round(current_22d_ret, 6),
        "spy_22d_return_percentile": round(ret_22d_pctile, 1),
        "gld_spy_correlation": {
            "22d": round(float(spy_ret.loc[spy_ret.index.intersection(gld_ret.index)].iloc[-22:].corr(
                gld_ret.loc[spy_ret.index.intersection(gld_ret.index)].iloc[-22:])), 4),
            "66d": round(gld_spy_corr_66, 4) if 'gld_spy_corr_66' in dir() else None,
        },
        "vol_cluster": {
            "spy": {"status": spy_vol_status, "ratio": round(spy_vol_ratio, 3)},
        },
        "composite_risk_score": risk_score,
        "risk_flags": risk_flags,
        "overall_assessment": overall,
    },
    "historical_parallel": {
        "most_similar_date": best_date.strftime("%Y-%m-%d") if best_date else None,
        "features_then": {k: round(v, 6) if isinstance(v, float) else v
                         for k, v in best_features.items()} if best_features else None,
        "distance": round(best_dist, 6) if best_dist < float("inf") else None,
    },
    "key_risk_factors": {
        "rate_cycle": {
            "tlt_1yr_return": round(tlt_1yr_ret, 6) if 'tlt_1yr_ret' in dir() else None,
            "tlt_6m_return": round(tlt_6m_ret, 6) if tlt_6m_ret is not None else None,
        },
        "gld_regime": {
            "gld_1yr_return": round(gld_1yr_ret, 6) if 'gld_1yr_ret' in dir() else None,
            "regime": gld_regime if 'gld_regime' in dir() else None,
        },
        "gamma_proxy": {
            "vix_rvol_spread": round(vix_rv_spread, 2) if 'vix_rv_spread' in dir() else None,
        },
    },
}

class NumpyEncoder(json.JSONEncoder):
    """Handle numpy types for JSON serialization."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

output_path = "experiments/k284_current_assessment_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
print()
print(f"Results saved to: {output_path}")
print()
print("=" * 72)
print("K284 COMPLETE")
print("=" * 72)
