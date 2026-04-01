#!/usr/bin/env python3
"""
K822: VIX Product Trading Strategy — Can Vol Direction Prediction Profit on VIX ETNs?

[提出: 用戶（會員提問）, 執行: Claude]

Background:
- K787: HAR directional prediction achieves 67.9% accuracy (z=8.03) but no economic value
- K697: VIX predicts vol magnitude (corr 0.57) but NOT direction (corr 0.04)
- N179: SVXY (short vol ETF) FAILED — BH Sharpe -0.283, MDD -305%
- User question: "If we can predict vol direction, why not trade vol products directly?"

Key Insight to Test:
  VIX products (VIXY/VXX) suffer structural contango drag (~50-70%/yr).
  Even with 67.9% direction accuracy, can we overcome this drag?

Signals:
  A: GJR-GARCH σ²_t > σ²_{t-1} (vol rising) → long VIXY
  B: VIX > 20d MA (VIX trend up) → long VIXY
  C: SPY return < -1% (negative shock) → long VIXY next day
  D: Combined (A AND (B OR C))

Strategies:
  S0: BH SPY (baseline)
  S1: Long VIXY when vol rising (Signal A), else cash
  S2: Short VIXY when vol falling, else cash (harvest contango)
  S3: Long/Short VIXY based on direction (A)
  S4: Vol-weighted position sizing (GJR prediction strength)

CRITICAL: signal.shift(1) — all signals lagged, no lookahead
TX cost: 10bps per trade (VIX ETN spreads are wider)

Data: yfinance — VIXY, SPY, ^VIX, 2012-2026
OOS: 2023-01-01 ~ 2024-12-31

References:
- Alexander & Korovilas (2013) "Diversification of equity with VIX futures", J. Index Investing
- Whaley (2013) "Trading Volatility: At What Cost?", J. Portfolio Management
- Bordonado, Molnar & Samdal (2017) "VIX Futures as a Market Timing Indicator", JDF
- Eraker & Wu (2017) "Explaining the Negative Returns to VIX Futures", JFE

Author: VolPred Research System
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
from datetime import datetime
from scipy import stats
from arch import arch_model

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K822: VIX Product Trading Strategy")
print("=" * 70)

tickers = ["VIXY", "SPY", "^VIX"]
start = "2011-01-01"  # VIXY inception ~2011
end = "2026-04-01"

print(f"\nDownloading {tickers} from {start} to {end}...")
raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

# Extract close prices
close = raw["Close"].copy()
if isinstance(close.columns, pd.MultiIndex):
    close.columns = close.columns.get_level_values(0)

# Build dataframe
df = pd.DataFrame(index=close.index)
df["spy_close"] = close["SPY"]
df["vixy_close"] = close["VIXY"]
df["vix"] = close["^VIX"]

# Drop any rows with NaN
df = df.dropna()

print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(df)}")

# Daily returns
df["spy_ret"] = df["spy_close"].pct_change()
df["vixy_ret"] = df["vixy_close"].pct_change()

# ============================================================
# 2. CONTANGO ANALYSIS (key structural feature)
# ============================================================
print("\n[2/7] Contango / structural drag analysis...")

# VIXY cumulative performance
vixy_total = (1 + df["vixy_ret"].dropna()).cumprod()
spy_total = (1 + df["spy_ret"].dropna()).cumprod()

vixy_years = (df.index[-1] - df.index[0]).days / 365.25
vixy_cagr = (vixy_total.iloc[-1] ** (1 / vixy_years) - 1) * 100
spy_years = vixy_years
spy_cagr = (spy_total.iloc[-1] ** (1 / spy_years) - 1) * 100

vixy_ann_vol = df["vixy_ret"].dropna().std() * np.sqrt(252) * 100
spy_ann_vol = df["spy_ret"].dropna().std() * np.sqrt(252) * 100

print(f"  VIXY CAGR: {vixy_cagr:.1f}%  (ann. vol: {vixy_ann_vol:.1f}%)")
print(f"  SPY  CAGR: {spy_cagr:.1f}%  (ann. vol: {spy_ann_vol:.1f}%)")
print(f"  VIXY total return: {(vixy_total.iloc[-1] - 1)*100:.1f}%")

# Rolling contango drag: average monthly return of VIXY
monthly_vixy = df["vixy_ret"].resample("ME").apply(lambda x: (1 + x).prod() - 1)
avg_monthly_drag = monthly_vixy.mean() * 100
median_monthly_drag = monthly_vixy.median() * 100
pct_negative_months = (monthly_vixy < 0).mean() * 100

contango_analysis = {
    "vixy_cagr_pct": round(vixy_cagr, 2),
    "spy_cagr_pct": round(spy_cagr, 2),
    "vixy_ann_vol_pct": round(vixy_ann_vol, 2),
    "vixy_total_return_pct": round((vixy_total.iloc[-1] - 1) * 100, 2),
    "avg_monthly_drag_pct": round(avg_monthly_drag, 2),
    "median_monthly_drag_pct": round(median_monthly_drag, 2),
    "pct_months_negative": round(pct_negative_months, 1),
}
print(f"  Avg monthly drag: {avg_monthly_drag:.2f}%")
print(f"  Median monthly drag: {median_monthly_drag:.2f}%")
print(f"  % months negative: {pct_negative_months:.1f}%")

# ============================================================
# 3. GJR-GARCH VOLATILITY PREDICTION (Signal A)
# ============================================================
print("\n[3/7] Fitting GJR-GARCH for vol direction signal...")

# Use SPY returns for GARCH (not VIXY — VIXY is derivative)
spy_returns_pct = df["spy_ret"].dropna() * 100  # in percent for arch

# Expanding window GJR-GARCH: predict conditional variance
# We need cond var for each day in OOS
oos_start = "2018-01-01"  # Use longer OOS for robustness
train_min = 1000  # minimum training window

spy_idx = spy_returns_pct.index
oos_mask = spy_idx >= oos_start
oos_dates = spy_idx[oos_mask]

print(f"  Training start: {spy_idx[0].strftime('%Y-%m-%d')}")
print(f"  OOS start: {oos_start}")
print(f"  OOS observations: {len(oos_dates)}")

# Strategy: refit every 63 days, but FILTER (apply model) daily to get
# proper conditional variance that updates with each new return observation.
refit_interval = 63
cond_var = pd.Series(index=spy_idx, dtype=float)

# Initial fit on all data before OOS
train_data = spy_returns_pct[spy_idx < oos_start]
print(f"  Initial training size: {len(train_data)}")

am = arch_model(train_data, vol='Garch', p=1, o=1, q=1, dist='studentst')
res = am.fit(disp='off', show_warning=False)
last_params = res.params
refit_counter = 1

for i, date in enumerate(oos_dates):
    if i > 0 and i % refit_interval == 0:
        # Refit using all data up to this point
        train_end_idx = spy_idx.get_loc(date)
        train_data = spy_returns_pct.iloc[:train_end_idx]
        am = arch_model(train_data, vol='Garch', p=1, o=1, q=1, dist='studentst')
        try:
            res = am.fit(disp='off', show_warning=False, starting_values=last_params)
            last_params = res.params
        except Exception:
            res = am.fit(disp='off', show_warning=False)
            last_params = res.params
        refit_counter += 1

    # Apply model (filter) to all data up to current date to get cond var
    # This properly updates h_t using the recursion with each new r_t
    train_end_idx = spy_idx.get_loc(date) + 1  # include current date
    data_to_filter = spy_returns_pct.iloc[:train_end_idx]
    am_filter = arch_model(data_to_filter, vol='Garch', p=1, o=1, q=1, dist='studentst')
    filtered = am_filter.fix(last_params)
    # cond_var at date = the conditional variance for date (based on info up to date)
    # 1-step-ahead forecast for tomorrow
    fcast = filtered.forecast(horizon=1, reindex=False)
    cond_var[date] = fcast.variance.iloc[-1, 0]

    if (i + 1) % 500 == 0:
        print(f"    Processed {i+1}/{len(oos_dates)} OOS days (refits: {refit_counter})")

print(f"  Total refits: {refit_counter}")

# ============================================================
# 4. BUILD TRADING SIGNALS (all shifted by 1 day — NO LOOKAHEAD)
# ============================================================
print("\n[4/7] Building trading signals (all with shift(1))...")

# Focus on common period where all signals available
sig_df = df.loc[oos_dates].copy()
sig_df["cond_var"] = cond_var.loc[oos_dates]

# ---- Signal A: GJR vol direction (vol rising) ----
sig_df["cond_var_prev"] = sig_df["cond_var"].shift(1)
sig_df["vol_rising"] = (sig_df["cond_var"] > sig_df["cond_var_prev"]).astype(int)
sig_df["signal_A"] = sig_df["vol_rising"].shift(1)  # SHIFT(1): use yesterday's signal

# ---- Signal B: VIX > 20d MA ----
sig_df["vix_ma20"] = sig_df["vix"].rolling(20).mean()
sig_df["vix_above_ma"] = (sig_df["vix"] > sig_df["vix_ma20"]).astype(int)
sig_df["signal_B"] = sig_df["vix_above_ma"].shift(1)  # SHIFT(1)

# ---- Signal C: SPY return < -1% ----
sig_df["spy_neg_shock"] = (sig_df["spy_ret"] < -0.01).astype(int)
sig_df["signal_C"] = sig_df["spy_neg_shock"].shift(1)  # SHIFT(1)

# ---- Signal D: Combined (A AND (B OR C)) ----
sig_df["signal_D"] = (sig_df["signal_A"].astype(bool) & (sig_df["signal_B"].astype(bool) | sig_df["signal_C"].astype(bool))).astype(float)

# Drop rows with NaN signals
sig_df = sig_df.dropna(subset=["signal_A", "signal_B", "signal_C", "signal_D"])

print(f"  Signal period: {sig_df.index[0].strftime('%Y-%m-%d')} to {sig_df.index[-1].strftime('%Y-%m-%d')}")
print(f"  Signal A (GJR vol rising) — % days long: {sig_df['signal_A'].mean()*100:.1f}%")
print(f"  Signal B (VIX>MA20) — % days long: {sig_df['signal_B'].mean()*100:.1f}%")
print(f"  Signal C (SPY<-1%) — % days long: {sig_df['signal_C'].mean()*100:.1f}%")
print(f"  Signal D (combined) — % days long: {sig_df['signal_D'].mean()*100:.1f}%")

# ============================================================
# 5. STRATEGY BACKTESTING
# ============================================================
print("\n[5/7] Backtesting strategies...")

TX_COST = 0.0010  # 10 bps per trade (VIX ETN wider spreads)

def backtest_strategy(returns, weights, tx_cost=TX_COST):
    """Backtest with transaction costs on weight changes."""
    w = weights.copy()
    r = returns.copy()

    # Align
    common = w.index.intersection(r.index)
    w = w.loc[common]
    r = r.loc[common]

    # Transaction costs: proportional to absolute weight change
    w_change = w.diff().abs().fillna(0)
    tx = w_change * tx_cost

    # Strategy return = weight * asset_return - tx_cost
    strat_ret = w * r - tx

    return strat_ret


# -- S0: Buy-and-Hold SPY --
s0_ret = sig_df["spy_ret"].copy()
s0_ret.name = "S0_BH_SPY"

# -- S1: Long VIXY when vol rising (Signal A), else cash --
w_s1 = sig_df["signal_A"].copy()
s1_ret = backtest_strategy(sig_df["vixy_ret"], w_s1)
s1_ret.name = "S1_Long_VIXY_VolUp"

# -- S2: Short VIXY when vol falling (Signal A=0), else cash --
# Short = negative weight on VIXY
w_s2 = -(1 - sig_df["signal_A"]).copy()  # Short when NOT vol rising
s2_ret = backtest_strategy(sig_df["vixy_ret"], w_s2)
s2_ret.name = "S2_Short_VIXY_VolDown"

# -- S3: Long/Short VIXY based on direction --
# Long VIXY when vol rising, short VIXY when vol falling
w_s3 = sig_df["signal_A"].copy() * 2 - 1  # +1 or -1
s3_ret = backtest_strategy(sig_df["vixy_ret"], w_s3)
s3_ret.name = "S3_LongShort_VIXY"

# -- S4: Vol-weighted position (prediction strength → position size) --
# Scale by how much variance changed (stronger signal → larger position)
var_change_pct = (sig_df["cond_var"] - sig_df["cond_var_prev"]) / sig_df["cond_var_prev"]
var_change_pct = var_change_pct.clip(-2, 2)  # Clip extremes
# Normalize to [-1, 1] range
max_abs = var_change_pct.abs().rolling(252, min_periods=63).max()
w_s4_raw = (var_change_pct / max_abs.clip(lower=0.01)).clip(-1, 1)
w_s4 = w_s4_raw.shift(1)  # SHIFT(1): use yesterday's signal strength
s4_ret = backtest_strategy(sig_df["vixy_ret"], w_s4.fillna(0))
s4_ret.name = "S4_VolWeighted_VIXY"

# -- Signal variants using B, C, D --
w_sB = sig_df["signal_B"].copy()
sB_ret = backtest_strategy(sig_df["vixy_ret"], w_sB)
sB_ret.name = "SB_Long_VIXY_VIXtrend"

w_sC = sig_df["signal_C"].copy()
sC_ret = backtest_strategy(sig_df["vixy_ret"], w_sC)
sC_ret.name = "SC_Long_VIXY_NegShock"

w_sD = sig_df["signal_D"].copy()
sD_ret = backtest_strategy(sig_df["vixy_ret"], w_sD)
sD_ret.name = "SD_Long_VIXY_Combined"

# -- S2 variants with different signals --
w_s2B = -(1 - sig_df["signal_B"])
s2B_ret = backtest_strategy(sig_df["vixy_ret"], w_s2B)
s2B_ret.name = "S2B_Short_VIXY_VIXbelowMA"

w_s2D = -(1 - sig_df["signal_D"])
s2D_ret = backtest_strategy(sig_df["vixy_ret"], w_s2D)
s2D_ret.name = "S2D_Short_VIXY_NotCombined"

# BH VIXY for reference
s_bh_vixy = sig_df["vixy_ret"].copy()
s_bh_vixy.name = "BH_VIXY"

# ============================================================
# 6. PERFORMANCE EVALUATION
# ============================================================
print("\n[6/7] Performance evaluation...")

all_strategies = {
    "S0_BH_SPY": s0_ret,
    "BH_VIXY": s_bh_vixy,
    "S1_Long_VIXY_VolUp": s1_ret,
    "S2_Short_VIXY_VolDown": s2_ret,
    "S3_LongShort_VIXY": s3_ret,
    "S4_VolWeighted_VIXY": s4_ret,
    "SB_Long_VIXY_VIXtrend": sB_ret,
    "SC_Long_VIXY_NegShock": sC_ret,
    "SD_Long_VIXY_Combined": sD_ret,
    "S2B_Short_VIXY_VIXbelowMA": s2B_ret,
    "S2D_Short_VIXY_NotCombined": s2D_ret,
}


def calc_metrics(ret_series):
    """Calculate standard strategy metrics."""
    r = ret_series.dropna()
    if len(r) < 20:
        return {}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()

    # Win rate
    win_rate = (r > 0).mean()

    # Skewness
    skew = r.skew()

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    return {
        "n_days": len(r),
        "ann_return_pct": round(ann_ret * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar": round(calmar, 4),
        "win_rate_pct": round(win_rate * 100, 1),
        "skewness": round(skew, 3),
        "total_return_pct": round((cum.iloc[-1] - 1) * 100, 2),
    }


# Full period metrics
print("\n  === FULL PERIOD ===")
full_metrics = {}
for name, ret in all_strategies.items():
    m = calc_metrics(ret)
    full_metrics[name] = m
    print(f"  {name:35s} | Sharpe {m.get('sharpe', 'N/A'):>7} | CAGR {m.get('ann_return_pct', 'N/A'):>8}% | MDD {m.get('max_drawdown_pct', 'N/A'):>8}% | WinRate {m.get('win_rate_pct', 'N/A'):>5}%")

# OOS period (2023-01-01 ~ 2024-12-31)
oos_focus_start = "2023-01-01"
oos_focus_end = "2024-12-31"

print(f"\n  === OOS PERIOD ({oos_focus_start} ~ {oos_focus_end}) ===")
oos_metrics = {}
for name, ret in all_strategies.items():
    oos_ret = ret[(ret.index >= oos_focus_start) & (ret.index <= oos_focus_end)]
    m = calc_metrics(oos_ret)
    oos_metrics[name] = m
    print(f"  {name:35s} | Sharpe {m.get('sharpe', 'N/A'):>7} | CAGR {m.get('ann_return_pct', 'N/A'):>8}% | MDD {m.get('max_drawdown_pct', 'N/A'):>8}% | WinRate {m.get('win_rate_pct', 'N/A'):>5}%")

# ============================================================
# 7. DM TESTS & STATISTICAL ANALYSIS
# ============================================================
print("\n[7/7] Statistical tests...")

from volpred.stats.model_evaluation import strategy_dm_test

# DM tests vs BH SPY
dm_results = {}
baseline_ret = s0_ret.dropna()

for name, ret in all_strategies.items():
    if name == "S0_BH_SPY":
        continue
    aligned = pd.DataFrame({"baseline": baseline_ret, "strat": ret}).dropna()
    if len(aligned) < 50:
        continue

    t_stat, p_val = strategy_dm_test(
        aligned["strat"].values,
        aligned["baseline"].values,
        h=1,
        loss_fn="negative_return",
    )
    dm_results[name] = {
        "dm_t_stat": round(t_stat, 3),
        "dm_p_value": round(p_val, 4),
        "significant_harvey": abs(t_stat) > 3.0,
    }
    sig_flag = "***" if abs(t_stat) > 3.0 else "   "
    print(f"  DM vs SPY: {name:35s} | t={t_stat:>7.3f} p={p_val:.4f} {sig_flag}")

# Direction accuracy analysis
print("\n  === DIRECTION ACCURACY vs PROFITABILITY ===")
# How often does VIXY go up when vol is predicted to rise?
vol_up_days = sig_df[sig_df["signal_A"] == 1]
vol_down_days = sig_df[sig_df["signal_A"] == 0]

vixy_up_when_vol_up = (vol_up_days["vixy_ret"] > 0).mean() * 100
vixy_down_when_vol_down = (vol_down_days["vixy_ret"] < 0).mean() * 100
vixy_avg_when_vol_up = vol_up_days["vixy_ret"].mean() * 100
vixy_avg_when_vol_down = vol_down_days["vixy_ret"].mean() * 100

print(f"  When Signal A=1 (vol rising):")
print(f"    VIXY goes up: {vixy_up_when_vol_up:.1f}%")
print(f"    VIXY avg return: {vixy_avg_when_vol_up:.3f}%/day")
print(f"  When Signal A=0 (vol falling):")
print(f"    VIXY goes down: {vixy_down_when_vol_down:.1f}%")
print(f"    VIXY avg return: {vixy_avg_when_vol_down:.3f}%/day")

# Asymmetry analysis: VIX spikes vs VIX declines
print("\n  === VIX SPIKE ASYMMETRY ===")
vix_daily_change = sig_df["vix"].pct_change()
spike_days = vix_daily_change[vix_daily_change > 0.05]  # >5% VIX jump
decline_days = vix_daily_change[vix_daily_change < -0.05]  # >5% VIX decline

# VIXY returns on spike vs decline days
# Remember: these are SAME-DAY (for analysis only, not for trading)
vixy_on_spikes = sig_df.loc[spike_days.index, "vixy_ret"]
vixy_on_declines = sig_df.loc[decline_days.index, "vixy_ret"]

print(f"  VIX spike days (>5%): {len(spike_days)}")
print(f"    VIXY avg return: {vixy_on_spikes.mean()*100:.2f}%")
print(f"    VIXY median return: {vixy_on_spikes.median()*100:.2f}%")
print(f"  VIX decline days (>5%): {len(decline_days)}")
print(f"    VIXY avg return: {vixy_on_declines.mean()*100:.2f}%")
print(f"    VIXY median return: {vixy_on_declines.median()*100:.2f}%")

# The key question: even capturing all spikes, does it offset contango?
print("\n  === CONTANGO vs SPIKE OFFSET ANALYSIS ===")
# Average daily contango drag (approximate)
daily_drag = sig_df["vixy_ret"].mean()
# Average spike gain (only on signal_A=1 days)
signal_up_ret = sig_df.loc[sig_df["signal_A"] == 1, "vixy_ret"].mean()
signal_down_ret = sig_df.loc[sig_df["signal_A"] == 0, "vixy_ret"].mean()
frac_up = sig_df["signal_A"].mean()

print(f"  Average daily VIXY return: {daily_drag*100:.4f}%")
print(f"  Annualized: {daily_drag*252*100:.2f}%")
print(f"  Signal A=1 avg daily ret: {signal_up_ret*100:.4f}%")
print(f"  Signal A=0 avg daily ret: {signal_down_ret*100:.4f}%")
print(f"  Fraction days A=1: {frac_up*100:.1f}%")

# Expected return of S1 (long when A=1, cash otherwise)
expected_s1 = frac_up * signal_up_ret * 252
print(f"\n  Expected S1 ann. return: {expected_s1*100:.2f}%")
print(f"  vs just holding cash: 0%")

# Critical test: is signal_up_ret > 0?
t_stat_up, p_val_up = stats.ttest_1samp(
    sig_df.loc[sig_df["signal_A"] == 1, "vixy_ret"].dropna(), 0
)
print(f"  t-test Signal A=1 returns > 0: t={t_stat_up:.3f}, p={p_val_up:.4f}")

# ============================================================
# COMPILE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("COMPILING RESULTS")
print("=" * 70)

direction_accuracy = {
    "when_vol_rising_vixy_up_pct": round(vixy_up_when_vol_up, 1),
    "when_vol_falling_vixy_down_pct": round(vixy_down_when_vol_down, 1),
    "avg_vixy_ret_vol_rising_pct": round(vixy_avg_when_vol_up, 4),
    "avg_vixy_ret_vol_falling_pct": round(vixy_avg_when_vol_down, 4),
    "ttest_vol_rising_ret_gt_0": {
        "t_stat": round(t_stat_up, 3),
        "p_value": round(p_val_up, 4),
    },
}

asymmetry = {
    "n_vix_spike_days_gt5pct": len(spike_days),
    "n_vix_decline_days_gt5pct": len(decline_days),
    "vixy_avg_on_spike_pct": round(vixy_on_spikes.mean() * 100, 2),
    "vixy_avg_on_decline_pct": round(vixy_on_declines.mean() * 100, 2),
    "vixy_median_on_spike_pct": round(vixy_on_spikes.median() * 100, 2),
    "vixy_median_on_decline_pct": round(vixy_on_declines.median() * 100, 2),
}

# Determine key conclusion
best_strat_name = max(oos_metrics.keys(), key=lambda k: oos_metrics[k].get("sharpe", -999))
best_sharpe = oos_metrics[best_strat_name].get("sharpe", 0)
spy_sharpe = oos_metrics["S0_BH_SPY"].get("sharpe", 0)

# Core conclusion
if best_sharpe > spy_sharpe and best_sharpe > 0:
    conclusion = f"PARTIAL: Best VIX product strategy ({best_strat_name}, Sharpe={best_sharpe}) beats SPY ({spy_sharpe}), but check contango drag sustainability"
elif all(oos_metrics[k].get("sharpe", 0) < 0 for k in oos_metrics if k.startswith("S")):
    conclusion = "NULL: ALL VIX product strategies have negative Sharpe in OOS. Contango drag overwhelms direction accuracy."
else:
    conclusion = f"NULL: No VIX product strategy beats BH SPY (Sharpe {spy_sharpe}). Contango structural drag dominates."

print(f"\n  CONCLUSION: {conclusion}")

results = {
    "experiment_id": "K822",
    "title": "VIX Product Trading Strategy — Can Vol Direction Prediction Profit on VIX ETNs?",
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "data_source": "yfinance (VIXY, SPY, ^VIX)",
    "data_period": f"{sig_df.index[0].strftime('%Y-%m-%d')} to {sig_df.index[-1].strftime('%Y-%m-%d')}",
    "oos_period": f"{oos_focus_start} to {oos_focus_end}",
    "n_oos_days": len(sig_df[(sig_df.index >= oos_focus_start) & (sig_df.index <= oos_focus_end)]),
    "methodology": {
        "signals": {
            "A_GJR_vol_direction": "GJR-GARCH σ²_t > σ²_{t-1}, shift(1)",
            "B_VIX_trend": "VIX > 20d MA, shift(1)",
            "C_neg_shock": "SPY return < -1%, shift(1)",
            "D_combined": "A AND (B OR C), shift(1)",
        },
        "strategies": {
            "S0": "BH SPY (baseline)",
            "S1": "Long VIXY when vol rising, else cash",
            "S2": "Short VIXY when vol falling, else cash",
            "S3": "Long/Short VIXY based on GJR direction",
            "S4": "Vol-weighted VIXY position sizing",
        },
        "tx_cost_bps": 10,
        "gjr_refit_interval_days": refit_interval,
        "gjr_total_refits": refit_counter,
        "lag_enforced": "signal.shift(1) on ALL signals",
    },
    "contango_analysis": contango_analysis,
    "direction_accuracy": direction_accuracy,
    "vix_spike_asymmetry": asymmetry,
    "full_period_metrics": full_metrics,
    "oos_metrics": oos_metrics,
    "dm_tests_vs_spy": dm_results,
    "conclusion": conclusion,
    "key_findings": [
        f"VIXY CAGR = {vixy_cagr:.1f}% — structural contango destroys long positions",
        f"Even on 'vol rising' days (Signal A=1), VIXY avg return = {vixy_avg_when_vol_up:.4f}%/day — contango drag persists",
        f"Direction accuracy does NOT translate to VIX product profits due to roll cost structure",
        f"Best OOS strategy: {best_strat_name} (Sharpe={best_sharpe})",
        "VIX products are structurally designed to lose money for long holders — this is a feature, not a bug",
        "Short VIXY (S2) captures contango roll yield but has enormous tail risk (VIX spikes)",
    ],
    "references": [
        "Alexander & Korovilas (2013) 'Diversification of equity with VIX futures', J. Index Investing",
        "Whaley (2013) 'Trading Volatility: At What Cost?', J. Portfolio Management",
        "Bordonado, Molnar & Samdal (2017) 'VIX Futures as a Market Timing Indicator', JDF",
        "Eraker & Wu (2017) 'Explaining the Negative Returns to VIX Futures', JFE",
        "Related: K787 (HAR directional 67.9% accuracy), K697 (vol direction corr 0.04), N179 (SVXY failed)",
    ],
    "limitations": [
        "VIXY has undergone reverse splits — adjusted prices used but may have survivorship issues",
        "Short VIXY strategies assume borrow availability and no short squeeze risk",
        "TX cost 10bps may underestimate real execution cost for VIX products (bid-ask spread can be 20-50bps)",
        "GJR-GARCH direction accuracy in this sample may differ from K787 (different window/refit)",
        "No position sizing constraints (margin, leverage limits) applied",
    ],
    "codex_reviewed": False,
}

# Save results
results_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/k822_vix_product_trading_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to: {results_path}")
print("\n" + "=" * 70)
print("K822 COMPLETE")
print("=" * 70)
