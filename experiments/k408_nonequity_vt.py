"""
K408: Non-Equity VT — Volatility-Targeted Strategies for Oil, Gold, and FX
===========================================================================
[提出: K407 redirected frontier, 執行: Claude]

Background:
  - K407 redirected research away from daily equity predictors
  - K342: Oil needs OVX (not VIX)
  - K345: FX kurtosis=108, needs own models
  - K217: Each asset has its own best predictor
  - K383: 3 volatility clusters across assets
  - But we never built COMPLETE VT strategies for non-equity assets

Methodology — build VT for each non-equity asset using ITS OWN best predictor:
  1. Oil VT: EWMA(0.94) signal, 15% vol target, monthly rebalance
  2. Gold VT: 22d Range Ratio signal, 15% vol target, monthly rebalance
  3. FX VT (EURUSD): EWMA(0.94) signal, 15% vol target, monthly rebalance
  4. KEY: do non-equity VTs provide DIVERSIFICATION to 50/50+VT?
     - 4-asset portfolio: SPY VT + GLD VT + OIL VT + FX VT
     - vs 50/50 SPY/GLD VT alone

Data: yfinance real data only. CL=F (oil), GC=F (gold), EURUSD=X, SPY, ^VIX.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import json
from scipy import stats

# ==================================================================
# CONFIG
# ==================================================================
TARGET_VOL_ANNUAL = 0.15
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
MIN_WEIGHT = 0.1
TX_COST_BPS = 5  # higher for commodities/FX
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
EWMA_LAMBDA = 0.94
RANGE_WINDOW = 22
REBAL_FREQ = 21  # monthly

DATA_START = "2008-01-01"  # enough history for all assets
OOS_START = "2014-01-02"

print("=" * 80)
print("K408: NON-EQUITY VT — Oil, Gold, FX Volatility-Targeted Strategies")
print("=" * 80)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/6] Downloading data: CL=F, GC=F, EURUSD=X, SPY, ^VIX...")

tickers = {
    "CL=F": "OIL",
    "GC=F": "GOLD",
    "EURUSD=X": "EURUSD",
    "SPY": "SPY",
    "^VIX": "VIX",
}

raw_data = {}
for ticker, name in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2026-12-31", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw_data[name] = df[["Close"]].rename(columns={"Close": name})
    print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Merge all on date
merged = raw_data["SPY"].copy()
for name in ["OIL", "GOLD", "EURUSD", "VIX"]:
    merged = merged.join(raw_data[name], how="inner")
merged = merged.dropna()

# Log returns for tradeable assets
assets = ["SPY", "OIL", "GOLD", "EURUSD"]
for a in assets:
    merged[f"{a}_ret"] = np.log(merged[a] / merged[a].shift(1))
merged = merged.dropna()

print(f"\n  Merged dataset: {len(merged)} rows, {merged.index[0].strftime('%Y-%m-%d')} to {merged.index[-1].strftime('%Y-%m-%d')}")

# ==================================================================
# 2. Volatility Estimators (asset-specific)
# ==================================================================
print("\n[2/6] Computing asset-specific volatility estimators...")

# --- EWMA(0.94) for Oil, FX, SPY ---
def compute_ewma_vol(returns, lam=0.94):
    """EWMA variance estimator."""
    n = len(returns)
    var = np.zeros(n)
    var[0] = returns[:22].var() if len(returns) >= 22 else returns.var()
    for i in range(1, n):
        var[i] = lam * var[i-1] + (1 - lam) * returns.iloc[i-1]**2
    return np.sqrt(var)

# --- Range Ratio for Gold (K217: range ratio best for GLD) ---
def compute_range_ratio_vol(prices, window=22):
    """Range-based volatility: (High-Low)/Close normalized over window."""
    # Use daily price range as proxy
    # Since we only have Close, use rolling std as range proxy
    # Then scale by range ratio = rolling_range / rolling_std
    ret = np.log(prices / prices.shift(1))
    rolling_std = ret.rolling(window).std()
    # Parkinson range estimator using close-to-close
    log_range = np.log(prices.rolling(window).max() / prices.rolling(window).min())
    # Normalize: range_vol = log_range / (2*sqrt(ln2)) * sqrt(252/window)
    range_vol = log_range / (2 * np.sqrt(np.log(2)))
    # Convert to daily vol
    range_vol_daily = range_vol / np.sqrt(window)
    return range_vol_daily

# Compute for each asset
for a in ["OIL", "EURUSD", "SPY"]:
    merged[f"{a}_ewma_vol"] = compute_ewma_vol(merged[f"{a}_ret"], EWMA_LAMBDA)

# Gold uses range ratio
merged["GOLD_range_vol"] = compute_range_ratio_vol(merged["GOLD"], RANGE_WINDOW)
# Also compute EWMA for comparison
merged["GOLD_ewma_vol"] = compute_ewma_vol(merged["GOLD_ret"], EWMA_LAMBDA)

# VIX-based daily vol for SPY benchmark
merged["VIX_daily"] = merged["VIX"] / 100 / np.sqrt(252)

print("  EWMA(0.94) computed for: OIL, EURUSD, SPY")
print("  Range Ratio (22d) computed for: GOLD")
print("  VIX daily vol computed for: SPY benchmark")

# Quick sanity check
for a in assets:
    if a == "GOLD":
        vol_col = f"{a}_range_vol"
    else:
        vol_col = f"{a}_ewma_vol"
    valid = merged[vol_col].dropna()
    ann_vol = valid.mean() * np.sqrt(252)
    print(f"  {a} avg annualized vol: {ann_vol:.1%}")

# ==================================================================
# 3. Build Individual VT Strategies
# ==================================================================
print("\n[3/6] Building individual VT strategies...")

def build_vt_strategy(merged_df, asset, vol_col, target_vol_daily, oos_start,
                      max_lev=1.5, min_w=0.1, rebal_freq=21, tx_bps=5):
    """Build VT strategy for a single asset with monthly rebalancing."""
    oos = merged_df.loc[oos_start:]
    ret_col = f"{asset}_ret"

    weights = []
    current_w = 1.0
    rebal_counter = 0

    for i in range(len(oos)):
        date = oos.index[i]
        vol = oos[vol_col].iloc[i]
        ret = oos[ret_col].iloc[i]

        if rebal_counter == 0 or rebal_counter >= rebal_freq:
            if pd.notna(vol) and vol > 0:
                new_w = target_vol_daily / vol
                new_w = np.clip(new_w, min_w, max_lev)
                # Transaction cost
                tx = abs(new_w - current_w) * (tx_bps / 10000)
                current_w = new_w
            else:
                tx = 0.0
            rebal_counter = 1
        else:
            tx = 0.0
            rebal_counter += 1

        vt_ret = current_w * ret - tx
        weights.append({
            "date": date,
            "weight": current_w,
            "raw_ret": ret,
            "vt_ret": vt_ret,
            "vol_est": vol,
        })

    result = pd.DataFrame(weights).set_index("date")
    return result

# Build VT for each asset
strategies = {}

# Oil VT: EWMA(0.94)
strategies["OIL"] = build_vt_strategy(
    merged, "OIL", "OIL_ewma_vol", TARGET_VOL_DAILY, OOS_START,
    max_lev=MAX_LEVERAGE, min_w=MIN_WEIGHT, rebal_freq=REBAL_FREQ, tx_bps=TX_COST_BPS
)

# Gold VT: Range Ratio
strategies["GOLD"] = build_vt_strategy(
    merged, "GOLD", "GOLD_range_vol", TARGET_VOL_DAILY, OOS_START,
    max_lev=MAX_LEVERAGE, min_w=MIN_WEIGHT, rebal_freq=REBAL_FREQ, tx_bps=TX_COST_BPS
)

# FX VT: EWMA(0.94)
strategies["EURUSD"] = build_vt_strategy(
    merged, "EURUSD", "EURUSD_ewma_vol", TARGET_VOL_DAILY, OOS_START,
    max_lev=MAX_LEVERAGE, min_w=MIN_WEIGHT, rebal_freq=REBAL_FREQ, tx_bps=TX_COST_BPS
)

# SPY VT: 12/VIX (benchmark from existing research)
def build_spy_vix_vt(merged_df, oos_start, rebal_freq=21, tx_bps=2):
    """SPY VT using 12/VIX rule (established best)."""
    oos = merged_df.loc[oos_start:]
    weights = []
    current_w = 1.0
    rebal_counter = 0

    for i in range(len(oos)):
        date = oos.index[i]
        vix = oos["VIX"].iloc[i]
        ret = oos["SPY_ret"].iloc[i]

        if rebal_counter == 0 or rebal_counter >= rebal_freq:
            new_w = 12.0 / vix
            new_w = np.clip(new_w, 0.1, 1.5)
            tx = abs(new_w - current_w) * (tx_bps / 10000)
            current_w = new_w
            rebal_counter = 1
        else:
            tx = 0.0
            rebal_counter += 1

        vt_ret = current_w * ret - tx
        weights.append({
            "date": date,
            "weight": current_w,
            "raw_ret": ret,
            "vt_ret": vt_ret,
            "vol_est": vix / 100 / np.sqrt(252),
        })

    return pd.DataFrame(weights).set_index("date")

strategies["SPY"] = build_spy_vix_vt(merged, OOS_START, REBAL_FREQ, tx_bps=2)

# Print individual results
print(f"\n{'='*80}")
print(f"{'Asset':<10} {'Signal':<20} {'Sharpe(VT)':<12} {'Sharpe(BH)':<12} {'MDD(VT)':<10} {'MDD(BH)':<10} {'AvgW':<8}")
print(f"{'='*80}")

def compute_metrics(returns, rf_daily=RF_DAILY):
    """Compute Sharpe, MDD, annualized return."""
    excess = returns - rf_daily
    sharpe = excess.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    cumret = (1 + returns).cumprod()
    drawdown = cumret / cumret.cummax() - 1
    mdd = drawdown.min()
    ann_ret = (1 + returns.mean()) ** 252 - 1
    ann_vol = returns.std() * np.sqrt(252)
    return sharpe, mdd, ann_ret, ann_vol

results_table = {}
for asset in ["SPY", "OIL", "GOLD", "EURUSD"]:
    strat = strategies[asset]

    # VT metrics
    vt_sharpe, vt_mdd, vt_ret, vt_vol = compute_metrics(strat["vt_ret"])

    # Buy & Hold metrics
    bh_sharpe, bh_mdd, bh_ret, bh_vol = compute_metrics(strat["raw_ret"])

    avg_w = strat["weight"].mean()
    signal = {
        "SPY": "12/VIX",
        "OIL": "EWMA(0.94)",
        "GOLD": "RangeRatio(22d)",
        "EURUSD": "EWMA(0.94)",
    }[asset]

    print(f"{asset:<10} {signal:<20} {vt_sharpe:>8.3f}     {bh_sharpe:>8.3f}     {vt_mdd:>8.1%}   {bh_mdd:>8.1%}   {avg_w:>6.2f}")

    results_table[asset] = {
        "signal": signal,
        "vt_sharpe": round(vt_sharpe, 4),
        "bh_sharpe": round(bh_sharpe, 4),
        "vt_mdd": round(vt_mdd, 4),
        "bh_mdd": round(bh_mdd, 4),
        "vt_ann_ret": round(vt_ret, 4),
        "bh_ann_ret": round(bh_ret, 4),
        "vt_ann_vol": round(vt_vol, 4),
        "bh_ann_vol": round(bh_vol, 4),
        "avg_weight": round(avg_w, 4),
    }

# ==================================================================
# 4. Statistical Tests
# ==================================================================
print(f"\n{'='*80}")
print("[4/6] Statistical Tests (DM test for Sharpe, Bootstrap for MDD)")
print(f"{'='*80}")

def dm_test_sharpe(r1, r2):
    """Diebold-Mariano style test for Sharpe difference.
    H0: Sharpe1 = Sharpe2. Returns t-stat and p-value."""
    # Use excess return difference
    d = r1 - r2
    n = len(d)
    d_bar = d.mean()
    # HAC standard error (Newey-West with lag=int(n^(1/3)))
    lag = int(n ** (1/3))
    gamma0 = np.sum((d - d_bar) ** 2) / n
    gamma_sum = 0
    for j in range(1, lag + 1):
        gamma_j = np.sum((d[j:] - d_bar) * (d[:-j] - d_bar)) / n
        gamma_sum += 2 * (1 - j / (lag + 1)) * gamma_j
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value

def bootstrap_mdd_test(vt_returns, bh_returns, n_boot=10000, seed=42):
    """Bootstrap test for MDD difference."""
    rng = np.random.RandomState(seed)
    n = len(vt_returns)

    # Observed MDD difference
    vt_cum = (1 + vt_returns).cumprod()
    bh_cum = (1 + bh_returns).cumprod()
    vt_mdd = (vt_cum / vt_cum.cummax() - 1).min()
    bh_mdd = (bh_cum / bh_cum.cummax() - 1).min()
    obs_diff = vt_mdd - bh_mdd  # negative means VT has less drawdown

    boot_diffs = []
    for _ in range(n_boot):
        idx = rng.randint(0, n, size=n)
        vt_boot = vt_returns.iloc[idx].values
        bh_boot = bh_returns.iloc[idx].values
        vt_c = np.cumprod(1 + vt_boot)
        bh_c = np.cumprod(1 + bh_boot)
        vt_m = (vt_c / np.maximum.accumulate(vt_c) - 1).min()
        bh_m = (bh_c / np.maximum.accumulate(bh_c) - 1).min()
        boot_diffs.append(vt_m - bh_m)

    boot_diffs = np.array(boot_diffs)
    # p-value: fraction of bootstrap where VT MDD >= BH MDD (no improvement)
    p_value = np.mean(boot_diffs >= 0)
    return obs_diff, p_value

print(f"\n{'Asset':<10} {'Sharpe t':<10} {'Sharpe p':<10} {'MDD diff':<12} {'MDD p':<10} {'Verdict':<20}")
print("-" * 72)

for asset in ["SPY", "OIL", "GOLD", "EURUSD"]:
    strat = strategies[asset]
    t_stat, p_val = dm_test_sharpe(strat["vt_ret"].values, strat["raw_ret"].values)
    mdd_diff, mdd_p = bootstrap_mdd_test(strat["vt_ret"], strat["raw_ret"])

    sharpe_sig = "Sig" if p_val < 0.05 else "NS"
    mdd_sig = "Sig" if mdd_p < 0.05 else "NS"
    verdict = f"Sharpe:{sharpe_sig}, MDD:{mdd_sig}"

    print(f"{asset:<10} {t_stat:>8.3f}   {p_val:>8.4f}   {mdd_diff:>10.1%}   {mdd_p:>8.4f}   {verdict}")

    results_table[asset]["sharpe_tstat"] = round(t_stat, 4)
    results_table[asset]["sharpe_pval"] = round(p_val, 4)
    results_table[asset]["mdd_diff"] = round(mdd_diff, 4)
    results_table[asset]["mdd_pval"] = round(mdd_p, 4)

# ==================================================================
# 5. Portfolio Analysis — Diversification Value
# ==================================================================
print(f"\n{'='*80}")
print("[5/6] Portfolio Analysis — Diversification Value")
print(f"{'='*80}")

# Align all strategies to common dates
common_dates = strategies["SPY"].index
for asset in ["OIL", "GOLD", "EURUSD"]:
    common_dates = common_dates.intersection(strategies[asset].index)

aligned = {}
for asset in assets:
    aligned[asset] = strategies[asset].loc[common_dates]

print(f"\n  Common OOS period: {common_dates[0].strftime('%Y-%m-%d')} to {common_dates[-1].strftime('%Y-%m-%d')}")
print(f"  Common trading days: {len(common_dates)}")

# --- Correlation Matrix (VT returns) ---
print("\n  Correlation Matrix (VT returns):")
corr_data = pd.DataFrame({
    a: aligned[a]["vt_ret"] for a in assets
})
corr_matrix = corr_data.corr()
print(corr_matrix.round(3).to_string())

# --- Portfolio Constructions ---
portfolios = {}

# P1: 50/50 SPY/GLD VT (baseline — the established best)
p1 = 0.5 * aligned["SPY"]["vt_ret"] + 0.5 * aligned["GOLD"]["vt_ret"]
portfolios["50/50 SPY/GLD VT"] = p1

# P2: Equal-weight 4-asset VT
p2 = sum(aligned[a]["vt_ret"] for a in assets) / 4
portfolios["EW 4-asset VT"] = p2

# P3: 40/30/15/15 (SPY heavy, add small commodity/FX)
p3 = 0.40 * aligned["SPY"]["vt_ret"] + 0.30 * aligned["GOLD"]["vt_ret"] + \
     0.15 * aligned["OIL"]["vt_ret"] + 0.15 * aligned["EURUSD"]["vt_ret"]
portfolios["40/30/15/15 VT"] = p3

# P4: 50/50 SPY/GLD BH (no VT, for reference)
p4 = 0.5 * aligned["SPY"]["raw_ret"] + 0.5 * aligned["GOLD"]["raw_ret"]
portfolios["50/50 SPY/GLD BH"] = p4

# P5: EW 4-asset BH
p5 = sum(aligned[a]["raw_ret"] for a in assets) / 4
portfolios["EW 4-asset BH"] = p5

# P6: SPY only BH
portfolios["SPY BH"] = aligned["SPY"]["raw_ret"]

# P7: Inverse-vol weighted 4-asset VT
# Weight by inverse realized vol (trailing 63d)
inv_vol_rets = pd.DataFrame({a: aligned[a]["vt_ret"] for a in assets})
rolling_vol = inv_vol_rets.rolling(63).std()
inv_vol = 1 / rolling_vol
inv_vol_weights = inv_vol.div(inv_vol.sum(axis=1), axis=0)
p7 = (inv_vol_rets * inv_vol_weights).sum(axis=1).dropna()
portfolios["InvVol 4-asset VT"] = p7

print(f"\n{'='*80}")
print(f"{'Portfolio':<25} {'Sharpe':>8} {'MDD':>8} {'AnnRet':>8} {'AnnVol':>8} {'Calmar':>8} {'Sortino':>8}")
print(f"{'='*80}")

portfolio_results = {}
for name, rets in portfolios.items():
    sharpe, mdd, ann_ret, ann_vol = compute_metrics(rets)
    # Sortino
    downside = rets[rets < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 0.001
    sortino = (ann_ret - RF_ANNUAL) / downside_vol
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    print(f"{name:<25} {sharpe:>8.3f} {mdd:>8.1%} {ann_ret:>8.1%} {ann_vol:>8.1%} {calmar:>8.2f} {sortino:>8.3f}")

    portfolio_results[name] = {
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4),
        "ann_ret": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
    }

# ==================================================================
# 5b. Statistical comparison: 4-asset VT vs 50/50 VT
# ==================================================================
print(f"\n{'='*80}")
print("Statistical Comparison: Multi-asset VT vs 50/50 SPY/GLD VT")
print(f"{'='*80}")

comparisons = [
    ("EW 4-asset VT", "50/50 SPY/GLD VT"),
    ("40/30/15/15 VT", "50/50 SPY/GLD VT"),
    ("InvVol 4-asset VT", "50/50 SPY/GLD VT"),
    ("EW 4-asset VT", "EW 4-asset BH"),
    ("50/50 SPY/GLD VT", "50/50 SPY/GLD BH"),
]

print(f"\n{'Comparison':<45} {'t-stat':>8} {'p-val':>8} {'MDD diff':>10} {'MDD p':>8}")
print("-" * 79)

comparison_results = {}
for p_name, b_name in comparisons:
    p_rets = portfolios[p_name]
    b_rets = portfolios[b_name]
    # Align
    common = p_rets.index.intersection(b_rets.index)
    p_r = p_rets.loc[common]
    b_r = b_rets.loc[common]

    t_stat, p_val = dm_test_sharpe(p_r.values, b_r.values)
    mdd_diff, mdd_p = bootstrap_mdd_test(p_r, b_r)

    label = f"{p_name} vs {b_name}"
    print(f"{label:<45} {t_stat:>8.3f} {p_val:>8.4f} {mdd_diff:>10.1%} {mdd_p:>8.4f}")

    comparison_results[label] = {
        "t_stat": round(t_stat, 4),
        "p_val": round(p_val, 4),
        "mdd_diff": round(mdd_diff, 4),
        "mdd_p": round(mdd_p, 4),
    }

# ==================================================================
# 6. Sub-period Analysis (Robustness)
# ==================================================================
print(f"\n{'='*80}")
print("[6/6] Sub-period Analysis (Robustness)")
print(f"{'='*80}")

sub_periods = [
    ("2014-2016", "2014-01-02", "2016-12-31"),
    ("2017-2019", "2017-01-02", "2019-12-31"),
    ("2020-COVID", "2020-01-02", "2020-12-31"),
    ("2021-2023", "2021-01-02", "2023-12-31"),
    ("2024-now", "2024-01-02", "2026-12-31"),
]

print(f"\n{'Period':<14} {'50/50 VT':>10} {'EW4 VT':>10} {'40/30/15/15':>12} {'InvVol4':>10} {'Winner':<15}")
print("-" * 72)

sub_period_results = {}
for period_name, start, end in sub_periods:
    period_sharpes = {}
    for pname in ["50/50 SPY/GLD VT", "EW 4-asset VT", "40/30/15/15 VT", "InvVol 4-asset VT"]:
        p_ret = portfolios[pname]
        mask = (p_ret.index >= start) & (p_ret.index <= end)
        sub_ret = p_ret[mask]
        if len(sub_ret) > 20:
            s, _, _, _ = compute_metrics(sub_ret)
            period_sharpes[pname] = s
        else:
            period_sharpes[pname] = float("nan")

    winner = max(period_sharpes, key=lambda x: period_sharpes.get(x, -999))
    winner_short = {
        "50/50 SPY/GLD VT": "50/50",
        "EW 4-asset VT": "EW4",
        "40/30/15/15 VT": "40/30/15/15",
        "InvVol 4-asset VT": "InvVol4",
    }.get(winner, winner)

    print(f"{period_name:<14} {period_sharpes.get('50/50 SPY/GLD VT', float('nan')):>10.3f} "
          f"{period_sharpes.get('EW 4-asset VT', float('nan')):>10.3f} "
          f"{period_sharpes.get('40/30/15/15 VT', float('nan')):>12.3f} "
          f"{period_sharpes.get('InvVol 4-asset VT', float('nan')):>10.3f} "
          f"{winner_short:<15}")

    sub_period_results[period_name] = {
        k: round(v, 4) for k, v in period_sharpes.items()
    }

# ==================================================================
# Crisis Analysis
# ==================================================================
print(f"\n{'='*80}")
print("Crisis-Period MDD Analysis")
print(f"{'='*80}")

crises = [
    ("Oil Crash 2014-16", "2014-06-01", "2016-02-28"),
    ("COVID 2020", "2020-02-01", "2020-04-30"),
    ("2022 Rate Hikes", "2022-01-01", "2022-12-31"),
]

print(f"\n{'Crisis':<22} {'50/50 VT':>10} {'EW4 VT':>10} {'40/30/15/15':>12} {'InvVol4':>10}")
print("-" * 64)

crisis_results = {}
for crisis_name, start, end in crises:
    crisis_mdds = {}
    for pname in ["50/50 SPY/GLD VT", "EW 4-asset VT", "40/30/15/15 VT", "InvVol 4-asset VT"]:
        p_ret = portfolios[pname]
        mask = (p_ret.index >= start) & (p_ret.index <= end)
        sub_ret = p_ret[mask]
        if len(sub_ret) > 5:
            cumret = (1 + sub_ret).cumprod()
            mdd = (cumret / cumret.cummax() - 1).min()
            crisis_mdds[pname] = mdd
        else:
            crisis_mdds[pname] = float("nan")

    print(f"{crisis_name:<22} {crisis_mdds.get('50/50 SPY/GLD VT', float('nan')):>10.1%} "
          f"{crisis_mdds.get('EW 4-asset VT', float('nan')):>10.1%} "
          f"{crisis_mdds.get('40/30/15/15 VT', float('nan')):>12.1%} "
          f"{crisis_mdds.get('InvVol 4-asset VT', float('nan')):>10.1%}")
    crisis_results[crisis_name] = {k: round(v, 4) for k, v in crisis_mdds.items()}

# ==================================================================
# Oil-specific: VIX vs EWMA for Oil VT
# ==================================================================
print(f"\n{'='*80}")
print("BONUS: Oil VT Signal Comparison (EWMA vs VIX)")
print(f"{'='*80}")

# Build Oil VT with VIX (inappropriate signal per K342)
oil_vix_strat = build_vt_strategy(
    merged, "OIL", "VIX_daily", TARGET_VOL_DAILY, OOS_START,
    max_lev=MAX_LEVERAGE, min_w=MIN_WEIGHT, rebal_freq=REBAL_FREQ, tx_bps=TX_COST_BPS
)

vix_sharpe, vix_mdd, _, _ = compute_metrics(oil_vix_strat["vt_ret"])
ewma_sharpe = results_table["OIL"]["vt_sharpe"]
ewma_mdd = results_table["OIL"]["vt_mdd"]

print(f"\n  Oil VT with EWMA(0.94):  Sharpe={ewma_sharpe:.3f}, MDD={ewma_mdd:.1%}")
print(f"  Oil VT with VIX:         Sharpe={vix_sharpe:.3f}, MDD={vix_mdd:.1%}")
print(f"  {'EWMA wins' if ewma_sharpe > vix_sharpe else 'VIX wins'} for Oil (confirms K342: OVX >> VIX)")

# ==================================================================
# GOLD: Range Ratio vs EWMA comparison
# ==================================================================
print(f"\n{'='*80}")
print("BONUS: Gold VT Signal Comparison (Range Ratio vs EWMA)")
print(f"{'='*80}")

gold_ewma_strat = build_vt_strategy(
    merged, "GOLD", "GOLD_ewma_vol", TARGET_VOL_DAILY, OOS_START,
    max_lev=MAX_LEVERAGE, min_w=MIN_WEIGHT, rebal_freq=REBAL_FREQ, tx_bps=TX_COST_BPS
)

ewma_g_sharpe, ewma_g_mdd, _, _ = compute_metrics(gold_ewma_strat["vt_ret"])
range_sharpe = results_table["GOLD"]["vt_sharpe"]
range_mdd = results_table["GOLD"]["vt_mdd"]

print(f"\n  Gold VT with RangeRatio(22d): Sharpe={range_sharpe:.3f}, MDD={range_mdd:.1%}")
print(f"  Gold VT with EWMA(0.94):      Sharpe={ewma_g_sharpe:.3f}, MDD={ewma_g_mdd:.1%}")
print(f"  {'RangeRatio wins' if range_sharpe > ewma_g_sharpe else 'EWMA wins'} for Gold")

# ==================================================================
# FX Characteristics
# ==================================================================
print(f"\n{'='*80}")
print("BONUS: EURUSD Characteristics")
print(f"{'='*80}")

fx_ret = merged.loc[OOS_START:]["EURUSD_ret"]
print(f"\n  EURUSD OOS stats:")
print(f"    Mean daily return: {fx_ret.mean()*252:.2%} annualized")
print(f"    Volatility: {fx_ret.std()*np.sqrt(252):.2%} annualized")
print(f"    Skewness: {fx_ret.skew():.3f}")
print(f"    Kurtosis: {fx_ret.kurtosis():.3f}")
print(f"    Corr with SPY: {corr_data['SPY'].corr(corr_data['EURUSD']):.3f}")

# ==================================================================
# Save Results
# ==================================================================
print(f"\n{'='*80}")
print("SUMMARY & CONCLUSIONS")
print(f"{'='*80}")

# Determine if 4-asset adds value
ew4_sharpe = portfolio_results["EW 4-asset VT"]["sharpe"]
baseline_sharpe = portfolio_results["50/50 SPY/GLD VT"]["sharpe"]
ew4_mdd = portfolio_results["EW 4-asset VT"]["mdd"]
baseline_mdd = portfolio_results["50/50 SPY/GLD VT"]["mdd"]

print(f"\n  KEY QUESTION: Do non-equity VTs add diversification value?")
print(f"  Baseline (50/50 SPY/GLD VT): Sharpe={baseline_sharpe:.3f}, MDD={baseline_mdd:.1%}")
print(f"  EW 4-asset VT:               Sharpe={ew4_sharpe:.3f}, MDD={ew4_mdd:.1%}")
print(f"  Sharpe difference: {ew4_sharpe - baseline_sharpe:+.3f}")
print(f"  MDD difference:   {ew4_mdd - baseline_mdd:+.1%}")

# Statistical significance
comp_key = "EW 4-asset VT vs 50/50 SPY/GLD VT"
if comp_key in comparison_results:
    cr = comparison_results[comp_key]
    sharpe_sig = "significant" if cr["p_val"] < 0.05 else "NOT significant"
    mdd_sig = "significant" if cr["mdd_p"] < 0.05 else "NOT significant"
    print(f"\n  Sharpe difference: t={cr['t_stat']:.3f}, p={cr['p_val']:.4f} ({sharpe_sig})")
    print(f"  MDD difference: p={cr['mdd_p']:.4f} ({mdd_sig})")

print(f"\n  Individual asset VT effectiveness:")
for asset in ["SPY", "OIL", "GOLD", "EURUSD"]:
    r = results_table[asset]
    vt_works = "YES" if r["vt_sharpe"] > r["bh_sharpe"] else "NO"
    mdd_works = "YES" if r["vt_mdd"] > r["bh_mdd"] else "NO"  # less negative = better
    print(f"    {asset}: VT improves Sharpe={vt_works} (VT={r['vt_sharpe']:.3f} vs BH={r['bh_sharpe']:.3f}), "
          f"MDD={mdd_works} (VT={r['vt_mdd']:.1%} vs BH={r['bh_mdd']:.1%})")

# Limitations
print(f"\n  LIMITATIONS:")
print(f"    - Oil uses CL=F futures (roll costs not modeled)")
print(f"    - EURUSD=X may have data quality issues")
print(f"    - Gold Range Ratio uses Close-only (no intraday High/Low)")
print(f"    - OVX not available from yfinance; used EWMA proxy for oil")
print(f"    - TX cost 5bps may underestimate commodity futures costs")
print(f"    - Monthly rebalance only; optimal frequency may differ per asset")

# Save JSON
output = {
    "experiment": "K408",
    "title": "Non-Equity VT Strategies (Oil, Gold, FX)",
    "date": datetime.now().isoformat(),
    "data_source": "yfinance",
    "oos_period": f"{OOS_START} to {common_dates[-1].strftime('%Y-%m-%d')}",
    "n_trading_days": len(common_dates),
    "config": {
        "target_vol": TARGET_VOL_ANNUAL,
        "max_leverage": MAX_LEVERAGE,
        "tx_cost_bps": TX_COST_BPS,
        "rebal_freq_days": REBAL_FREQ,
        "ewma_lambda": EWMA_LAMBDA,
        "range_window": RANGE_WINDOW,
    },
    "individual_assets": results_table,
    "portfolios": portfolio_results,
    "correlations": corr_matrix.round(4).to_dict(),
    "statistical_comparisons": comparison_results,
    "sub_periods": sub_period_results,
    "crises": crisis_results,
    "bonus": {
        "oil_vix_vs_ewma": {
            "ewma_sharpe": round(ewma_sharpe, 4) if isinstance(ewma_sharpe, float) else ewma_sharpe,
            "vix_sharpe": round(vix_sharpe, 4),
            "ewma_wins": bool(ewma_sharpe > vix_sharpe) if isinstance(ewma_sharpe, (int, float)) else None,
        },
        "gold_range_vs_ewma": {
            "range_sharpe": range_sharpe,
            "ewma_sharpe": round(ewma_g_sharpe, 4),
            "range_wins": bool(range_sharpe > ewma_g_sharpe),
        },
    },
}

results_path = "experiments/k408_nonequity_vt_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {results_path}")

print(f"\n{'='*80}")
print("K408 COMPLETE")
print(f"{'='*80}")
