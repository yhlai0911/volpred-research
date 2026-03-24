"""
K254: Cross-Asset Volatility Dispersion as Alpha Signal
========================================================
K164-K165 found dispersion absorbed by VIX for vol prediction.
But can dispersion serve as a TRADING signal?

Hypothesis:
- High dispersion → assets have very different vol levels → diversification benefit HIGH → equal-weight
- Low dispersion → all assets move similarly → correlation likely high → concentrate in lowest-vol

Strategies tested:
  1. Dispersion Binary: high disp → EW 6 assets, low disp → lowest-vol asset
  2. Continuous Corr-Weighted: weight inversely proportional to avg pairwise correlation
  3. Dispersion Quintile: 5-level allocation (gradual shift from concentrated to diversified)

Benchmarks:
  A. SPY Buy & Hold
  B. 50/50 SPY/GLD (proven best simple combo)
  C. Equal-weight 6 assets (static)

Data: SPY, QQQ, GLD, TLT, EEM, IWM daily from yfinance, 2005-2024
Cross-OOS: 5 periods (2005-08, 2009-12, 2013-16, 2017-20, 2021-24)
Harvey t > 3.0 threshold, DM test, TX cost 0.1%

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
from datetime import datetime

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K254: Cross-Asset Volatility Dispersion as Alpha Signal")
print("=" * 70)

print("\n[1/7] Downloading data from yfinance...")

ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM", "IWM"]
START = "2004-01-01"
END = "2025-01-01"

prices = {}
returns = {}

for asset in ASSETS:
    raw = yf.download(asset, start=START, end=END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    p = raw[col].copy()
    p.name = asset
    prices[asset] = p
    r = p.pct_change().dropna()
    r.name = asset
    returns[asset] = r
    print(f"  {asset}: {len(p)} days ({p.index[0].strftime('%Y-%m-%d')} to {p.index[-1].strftime('%Y-%m-%d')})")

# Merge into aligned DataFrame
ret_df = pd.DataFrame(returns).dropna()
price_df = pd.DataFrame(prices).dropna()
print(f"\n  Aligned dataset: {len(ret_df)} days ({ret_df.index[0].strftime('%Y-%m-%d')} to {ret_df.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. Compute volatility dispersion signal
# ============================================================
print("\n[2/7] Computing volatility dispersion signal...")

VOL_WINDOW = 22  # ~1 month rolling window

# Rolling volatility for each asset (annualized)
rolling_vols = ret_df.rolling(VOL_WINDOW).std() * np.sqrt(252)

# Cross-asset volatility dispersion = std of vols across assets on each day
vol_dispersion = rolling_vols.apply(lambda row: row.std(), axis=1)
vol_dispersion.name = "vol_dispersion"

# Also compute average pairwise correlation (rolling 22d)
def rolling_avg_corr(ret_df, window=22):
    """Compute average pairwise correlation using rolling window."""
    n = len(ret_df.columns)
    avg_corr = pd.Series(index=ret_df.index, dtype=float)

    for i in range(window, len(ret_df)):
        sub = ret_df.iloc[i-window:i]
        corr_matrix = sub.corr()
        # Extract upper triangle (excluding diagonal)
        upper_tri = corr_matrix.values[np.triu_indices(n, k=1)]
        avg_corr.iloc[i] = upper_tri.mean()

    return avg_corr

avg_corr = rolling_avg_corr(ret_df, VOL_WINDOW)
avg_corr.name = "avg_pairwise_corr"

# Combine signals
signals = pd.DataFrame({
    "vol_dispersion": vol_dispersion,
    "avg_corr": avg_corr
}).dropna()

print(f"  Vol dispersion: mean={signals['vol_dispersion'].mean():.4f}, std={signals['vol_dispersion'].std():.4f}")
print(f"  Avg pairwise corr: mean={signals['avg_corr'].mean():.3f}, std={signals['avg_corr'].std():.3f}")
print(f"  Correlation(disp, avg_corr): {signals['vol_dispersion'].corr(signals['avg_corr']):.3f}")

# ============================================================
# 3. Build trading strategies
# ============================================================
print("\n[3/7] Building trading strategies...")

# Align data
common_idx = ret_df.index.intersection(signals.index)
# Use signals from day t to determine weights for day t+1 (lagged)
ret_aligned = ret_df.loc[common_idx]
sig_aligned = signals.loc[common_idx]

# Expanding median of dispersion (avoid lookahead)
expanding_median_disp = sig_aligned["vol_dispersion"].expanding(min_periods=252).median()

# Strategy 1: Dispersion Binary
# High disp → EW 6 assets; Low disp → lowest-vol asset (lagged)
def strategy_dispersion_binary(ret_df, rolling_vols, vol_dispersion, expanding_median):
    """Binary: above median disp = EW, below = lowest vol asset."""
    strat_ret = pd.Series(index=ret_df.index, dtype=float)
    weights_record = []
    turnover_total = 0
    prev_weights = np.zeros(len(ASSETS))
    n_trades = 0

    for i in range(1, len(ret_df)):
        date = ret_df.index[i]
        prev_date = ret_df.index[i-1]

        if prev_date not in vol_dispersion.index or pd.isna(expanding_median.get(prev_date)):
            strat_ret.iloc[i] = ret_df.iloc[i].mean()  # default EW
            continue

        disp = vol_dispersion.loc[prev_date]
        med = expanding_median.loc[prev_date]

        if disp > med:
            # High dispersion → equal weight
            w = np.ones(len(ASSETS)) / len(ASSETS)
        else:
            # Low dispersion → lowest vol asset
            if prev_date in rolling_vols.index:
                vols = rolling_vols.loc[prev_date]
                if vols.isna().any():
                    w = np.ones(len(ASSETS)) / len(ASSETS)
                else:
                    min_vol_idx = vols.values.argmin()
                    w = np.zeros(len(ASSETS))
                    w[min_vol_idx] = 1.0
            else:
                w = np.ones(len(ASSETS)) / len(ASSETS)

        strat_ret.iloc[i] = np.sum(w * ret_df.iloc[i].values)

        # Track turnover
        turnover_total += np.sum(np.abs(w - prev_weights))
        if np.any(w != prev_weights):
            n_trades += 1
        prev_weights = w.copy()

    return strat_ret.dropna(), turnover_total, n_trades


# Strategy 2: Continuous Correlation-Weighted
# Weight inversely proportional to avg pairwise correlation
# High corr → concentrate in min-vol; Low corr → diversify
def strategy_corr_weighted(ret_df, rolling_vols, avg_corr):
    """Continuous: blend between EW and min-vol based on correlation."""
    strat_ret = pd.Series(index=ret_df.index, dtype=float)
    turnover_total = 0
    prev_weights = np.zeros(len(ASSETS))

    # Expanding percentile for normalization
    expanding_pctl = avg_corr.expanding(min_periods=252).rank(pct=True)

    for i in range(1, len(ret_df)):
        date = ret_df.index[i]
        prev_date = ret_df.index[i-1]

        if prev_date not in avg_corr.index or pd.isna(expanding_pctl.get(prev_date)):
            strat_ret.iloc[i] = ret_df.iloc[i].mean()
            continue

        corr_pctl = expanding_pctl.loc[prev_date]

        # EW weights
        ew_w = np.ones(len(ASSETS)) / len(ASSETS)

        # Min-vol weights
        if prev_date in rolling_vols.index:
            vols = rolling_vols.loc[prev_date]
            if vols.isna().any():
                minvol_w = ew_w.copy()
            else:
                # Inverse vol weighting
                inv_vol = 1.0 / vols.values
                minvol_w = inv_vol / inv_vol.sum()
        else:
            minvol_w = ew_w.copy()

        # Blend: high corr → more min-vol; low corr → more EW
        # corr_pctl close to 1 = high corr = concentrate
        w = (1 - corr_pctl) * ew_w + corr_pctl * minvol_w
        w = w / w.sum()

        strat_ret.iloc[i] = np.sum(w * ret_df.iloc[i].values)
        turnover_total += np.sum(np.abs(w - prev_weights))
        prev_weights = w.copy()

    return strat_ret.dropna(), turnover_total


# Strategy 3: Dispersion Quintile
# 5 levels from most concentrated to most diversified
def strategy_dispersion_quintile(ret_df, rolling_vols, vol_dispersion):
    """Quintile: gradual shift based on dispersion percentile."""
    strat_ret = pd.Series(index=ret_df.index, dtype=float)
    turnover_total = 0
    prev_weights = np.zeros(len(ASSETS))

    expanding_pctl = vol_dispersion.expanding(min_periods=252).rank(pct=True)

    for i in range(1, len(ret_df)):
        date = ret_df.index[i]
        prev_date = ret_df.index[i-1]

        if prev_date not in vol_dispersion.index or pd.isna(expanding_pctl.get(prev_date)):
            strat_ret.iloc[i] = ret_df.iloc[i].mean()
            continue

        disp_pctl = expanding_pctl.loc[prev_date]

        # EW weights
        ew_w = np.ones(len(ASSETS)) / len(ASSETS)

        # Min-vol concentration
        if prev_date in rolling_vols.index:
            vols = rolling_vols.loc[prev_date]
            if vols.isna().any():
                conc_w = ew_w.copy()
            else:
                min_vol_idx = vols.values.argmin()
                conc_w = np.zeros(len(ASSETS))
                conc_w[min_vol_idx] = 1.0
        else:
            conc_w = ew_w.copy()

        # Quintile mapping: Q1(low disp)→concentrated, Q5(high disp)→EW
        # disp_pctl: 0=lowest dispersion, 1=highest
        blend = disp_pctl  # 0→concentrated, 1→diversified
        w = (1 - blend) * conc_w + blend * ew_w
        w = w / w.sum()

        strat_ret.iloc[i] = np.sum(w * ret_df.iloc[i].values)
        turnover_total += np.sum(np.abs(w - prev_weights))
        prev_weights = w.copy()

    return strat_ret.dropna(), turnover_total


# Benchmarks
# A. SPY B&H
spy_bh = ret_aligned["SPY"].copy()
spy_bh.name = "SPY_BH"

# B. 50/50 SPY/GLD
spygld = 0.5 * ret_aligned["SPY"] + 0.5 * ret_aligned["GLD"]
spygld.name = "50/50_SPY/GLD"

# C. Equal-weight 6 assets
ew6 = ret_aligned.mean(axis=1)
ew6.name = "EW_6_assets"

# Run strategies
print("  Running Strategy 1: Dispersion Binary...")
s1_ret, s1_turnover, s1_trades = strategy_dispersion_binary(
    ret_aligned, rolling_vols, vol_dispersion, expanding_median_disp)

print("  Running Strategy 2: Correlation-Weighted...")
s2_ret, s2_turnover = strategy_corr_weighted(ret_aligned, rolling_vols, avg_corr)

print("  Running Strategy 3: Dispersion Quintile...")
s3_ret, s3_turnover = strategy_dispersion_quintile(ret_aligned, rolling_vols, vol_dispersion)

# ============================================================
# 4. Full-sample performance metrics
# ============================================================
print("\n[4/7] Full-sample performance evaluation...")

def compute_metrics(returns, name, turnover_total=0, tx_cost=0.001):
    """Compute Sharpe, MDD, Calmar, Sortino, and net metrics."""
    r = returns.dropna()
    n_years = len(r) / 252

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Turnover and net metrics
    annual_turnover = turnover_total / n_years if n_years > 0 else 0
    tx_drag = annual_turnover * tx_cost
    net_ret = ann_ret - tx_drag
    net_sharpe = net_ret / ann_vol if ann_vol > 0 else 0

    # Sharpe t-stat
    sharpe_se = 1.0 / np.sqrt(n_years)
    sharpe_t = sharpe / sharpe_se

    return {
        "name": name,
        "n_days": len(r),
        "n_years": round(n_years, 1),
        "ann_ret": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sharpe_t": round(sharpe_t, 2),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "annual_turnover": round(annual_turnover, 1),
        "tx_drag_bps": round(tx_drag * 10000, 1),
        "net_sharpe": round(net_sharpe, 3),
    }


all_strategies = {
    "S1_Binary": s1_ret,
    "S2_CorrWeight": s2_ret,
    "S3_Quintile": s3_ret,
    "BM_SPY_BH": spy_bh,
    "BM_50/50": spygld,
    "BM_EW6": ew6,
}

turnovers = {
    "S1_Binary": s1_turnover,
    "S2_CorrWeight": s2_turnover,
    "S3_Quintile": s3_turnover,
    "BM_SPY_BH": 0,
    "BM_50/50": 0,
    "BM_EW6": 0,
}

print(f"\n{'Strategy':<20} {'Sharpe':>7} {'t-stat':>7} {'MDD%':>7} {'Calmar':>7} {'Sortino':>8} {'Turn/yr':>8} {'NetSh':>7}")
print("-" * 82)

metrics_all = {}
for key, ret_series in all_strategies.items():
    m = compute_metrics(ret_series, key, turnovers[key])
    metrics_all[key] = m
    print(f"  {m['name']:<18} {m['sharpe']:>7.3f} {m['sharpe_t']:>7.2f} {m['mdd']:>7.2f} {m['calmar']:>7.3f} {m['sortino']:>8.3f} {m['annual_turnover']:>8.1f} {m['net_sharpe']:>7.3f}")

# ============================================================
# 5. Statistical tests (DM test vs benchmarks)
# ============================================================
print("\n[5/7] Statistical tests...")

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test. e1, e2 are loss series.
    H0: equal predictive accuracy. Negative t → e1 < e2 (e1 better)."""
    d = np.asarray(e1) - np.asarray(e2)
    mask = ~np.isnan(d)
    d = d[mask]
    n = len(d)
    mean_d = d.mean()
    var_d = d.var()
    if var_d == 0:
        return 0.0, 1.0
    # Newey-West HAC variance
    gamma_0 = var_d
    for k in range(1, h + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_0 += 2 * gamma_k
    se = np.sqrt(gamma_0 / n)
    if se == 0:
        return 0.0, 1.0
    t_stat = mean_d / se
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return t_stat, p_val


# Use squared returns as loss (portfolio Sharpe comparison via returns)
# For trading strategy comparison, we use daily returns directly
# DM test on returns: positive t → strategy 1 has higher returns
print("\n  DM Test on daily returns (positive t = S beats benchmark):")
print(f"  {'Comparison':<40} {'DM t':>8} {'p-val':>8} {'Sig':>5}")
print("  " + "-" * 65)

strat_keys = ["S1_Binary", "S2_CorrWeight", "S3_Quintile"]
bench_keys = ["BM_SPY_BH", "BM_50/50", "BM_EW6"]

dm_results = []
for sk in strat_keys:
    for bk in bench_keys:
        s_ret = all_strategies[sk]
        b_ret = all_strategies[bk]
        common = s_ret.index.intersection(b_ret.index)
        # Loss = negative return (lower loss = higher return)
        loss_s = -s_ret.loc[common]
        loss_b = -b_ret.loc[common]
        t_stat, p_val = dm_test(loss_s.values, loss_b.values)
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.1 else ""
        dm_results.append({
            "comparison": f"{sk} vs {bk}",
            "dm_t": round(t_stat, 3),
            "p_val": round(p_val, 4),
            "sig": sig
        })
        print(f"  {sk} vs {bk:<20} {t_stat:>8.3f} {p_val:>8.4f} {sig:>5}")

# Harvey threshold check
print("\n  Harvey (2016) threshold for strategy Sharpe t > 3.0:")
for key in strat_keys:
    m = metrics_all[key]
    harvey_pass = "PASS" if abs(m["sharpe_t"]) > 3.0 else "FAIL"
    print(f"    {key}: t = {m['sharpe_t']:.2f} → {harvey_pass}")

# ============================================================
# 6. Cross-OOS validation (5 periods)
# ============================================================
print("\n[6/7] Cross-OOS validation (5 periods)...")

OOS_PERIODS = [
    ("2005-01-01", "2008-12-31", "2005-2008 (GFC)"),
    ("2009-01-01", "2012-12-31", "2009-2012 (Recovery)"),
    ("2013-01-01", "2016-12-31", "2013-2016 (Low Vol)"),
    ("2017-01-01", "2020-12-31", "2017-2020 (COVID)"),
    ("2021-01-01", "2024-12-31", "2021-2024 (Post-COVID)"),
]

cross_oos_results = {}
for key in list(strat_keys) + list(bench_keys):
    cross_oos_results[key] = []

print(f"\n  {'Period':<25}", end="")
for key in strat_keys + bench_keys:
    short_name = key.replace("BM_", "").replace("S1_", "S1:").replace("S2_", "S2:").replace("S3_", "S3:")
    print(f" {short_name:>12}", end="")
print()
print("  " + "-" * (25 + 13 * 6))

for start, end, label in OOS_PERIODS:
    print(f"  {label:<25}", end="")
    for key in strat_keys + bench_keys:
        ret_series = all_strategies[key]
        mask = (ret_series.index >= start) & (ret_series.index <= end)
        period_ret = ret_series[mask]
        if len(period_ret) > 50:
            ann_ret_p = period_ret.mean() * 252
            ann_vol_p = period_ret.std() * np.sqrt(252)
            sharpe_p = ann_ret_p / ann_vol_p if ann_vol_p > 0 else 0
            cross_oos_results[key].append(sharpe_p)
            print(f" {sharpe_p:>12.3f}", end="")
        else:
            cross_oos_results[key].append(np.nan)
            print(f" {'N/A':>12}", end="")
    print()

# Win counts vs benchmarks
print(f"\n  Win counts (strategy Sharpe > benchmark Sharpe across 5 OOS periods):")
print(f"  {'Strategy vs Benchmark':<35} {'Wins':>5} {'Losses':>7} {'Rate':>6}")
print("  " + "-" * 55)

for sk in strat_keys:
    for bk in bench_keys:
        s_vals = np.array(cross_oos_results[sk])
        b_vals = np.array(cross_oos_results[bk])
        valid = ~(np.isnan(s_vals) | np.isnan(b_vals))
        wins = np.sum(s_vals[valid] > b_vals[valid])
        losses = np.sum(valid) - wins
        rate = wins / np.sum(valid) if np.sum(valid) > 0 else 0
        print(f"  {sk} vs {bk:<20} {wins:>5} {losses:>7} {rate:>6.1%}")


# Cross-OOS consistency: paired t-test of Sharpe differences
print(f"\n  Cross-OOS paired t-test (strategy - benchmark Sharpe):")
print(f"  {'Comparison':<35} {'Mean diff':>10} {'t-stat':>8} {'p-val':>8}")
print("  " + "-" * 65)

for sk in strat_keys:
    for bk in bench_keys:
        s_vals = np.array(cross_oos_results[sk])
        b_vals = np.array(cross_oos_results[bk])
        valid = ~(np.isnan(s_vals) | np.isnan(b_vals))
        if np.sum(valid) >= 3:
            diffs = s_vals[valid] - b_vals[valid]
            t_stat, p_val = stats.ttest_1samp(diffs, 0)
            print(f"  {sk} vs {bk:<20} {diffs.mean():>10.3f} {t_stat:>8.3f} {p_val:>8.4f}")

# ============================================================
# 7. Additional analysis
# ============================================================
print("\n[7/7] Additional analysis...")

# 7a. Dispersion regime characteristics
print("\n  7a. Dispersion regime characteristics:")
# Align indices before comparison
common_disp_idx = vol_dispersion.dropna().index.intersection(expanding_median_disp.dropna().index)
high_disp_mask_raw = vol_dispersion.loc[common_disp_idx] > expanding_median_disp.loc[common_disp_idx]
high_disp_mask = high_disp_mask_raw.reindex(ret_aligned.index).fillna(False).astype(bool)

# Stats for high vs low dispersion regimes
for regime, mask in [("High Dispersion", high_disp_mask), ("Low Dispersion", ~high_disp_mask)]:
    regime_rets = ret_aligned.loc[mask]
    if len(regime_rets) > 50:
        avg_corr_regime = avg_corr.reindex(ret_aligned.index)[mask].mean()
        ew_sharpe = (regime_rets.mean(axis=1).mean() * 252) / (regime_rets.mean(axis=1).std() * np.sqrt(252))
        spy_sharpe = (regime_rets["SPY"].mean() * 252) / (regime_rets["SPY"].std() * np.sqrt(252))
        print(f"    {regime}: n={len(regime_rets)}, avg_corr={avg_corr_regime:.3f}, "
              f"EW Sharpe={ew_sharpe:.3f}, SPY Sharpe={spy_sharpe:.3f}")

# 7b. Does dispersion predict future diversification benefit?
print("\n  7b. Predictive regression: dispersion(t) → diversification_benefit(t+22)")
# Diversification benefit = EW return - max single-asset return (positive = diversification helps)
ew_ret_daily = ret_aligned.mean(axis=1)
max_asset_ret = ret_aligned.max(axis=1)
div_benefit = (ew_ret_daily - max_asset_ret).rolling(22).sum()

# Lagged regression
y_vals = div_benefit.iloc[22:].values
x_vals = vol_dispersion.reindex(div_benefit.index).shift(22).iloc[22:].values
valid = ~(np.isnan(y_vals) | np.isnan(x_vals))
if np.sum(valid) > 100:
    slope, intercept, r_val, p_val, se = stats.linregress(x_vals[valid], y_vals[valid])
    print(f"    slope={slope:.4f}, R²={r_val**2:.4f}, p={p_val:.4f}")
    print(f"    Interpretation: dispersion {'positively' if slope > 0 else 'negatively'} predicts future diversification benefit")

# 7c. Correlation between dispersion and VIX
print("\n  7c. Dispersion vs VIX level:")
vix_raw = yf.download("^VIX", start=START, end=END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw["Close"].copy()
common_vix_idx = vol_dispersion.dropna().index.intersection(vix_close.dropna().index)
if len(common_vix_idx) > 100:
    rho = vol_dispersion.loc[common_vix_idx].corr(vix_close.loc[common_vix_idx])
    print(f"    corr(vol_dispersion, VIX) = {rho:.3f}")
    print(f"    {'High correlation → dispersion largely proxies VIX level' if abs(rho) > 0.5 else 'Moderate/Low → dispersion carries independent info'}")

# 7d. Bootstrap comparison vs 50/50 SPY/GLD
print("\n  7d. Bootstrap test: Strategy vs 50/50 SPY/GLD (10,000 reps):")
np.random.seed(42)
N_BOOT = 10000

for sk in strat_keys:
    s_ret = all_strategies[sk]
    b_ret = all_strategies["BM_50/50"]
    common = s_ret.index.intersection(b_ret.index)
    diff = (s_ret.loc[common] - b_ret.loc[common]).values
    n = len(diff)

    boot_means = np.array([
        np.random.choice(diff, size=n, replace=True).mean()
        for _ in range(N_BOOT)
    ])

    p_val = np.mean(boot_means <= 0)  # H0: strategy <= benchmark
    ci_lo = np.percentile(boot_means, 2.5) * 252 * 100
    ci_hi = np.percentile(boot_means, 97.5) * 252 * 100
    mean_diff_ann = diff.mean() * 252 * 100

    print(f"    {sk}: mean diff = {mean_diff_ann:.2f}%/yr, "
          f"95% CI = [{ci_lo:.2f}%, {ci_hi:.2f}%], "
          f"p(S>BM) = {1-p_val:.4f}")

# ============================================================
# Summary and conclusions
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K254 Cross-Asset Volatility Dispersion as Alpha Signal")
print("=" * 70)

print(f"""
Data: {', '.join(ASSETS)}, {ret_aligned.index[0].strftime('%Y-%m-%d')} to {ret_aligned.index[-1].strftime('%Y-%m-%d')}
Signal: Cross-asset vol dispersion (std of 22d rolling vols across 6 assets)
         + Average pairwise correlation (22d rolling)

Key Findings:
""")

# Compare best strategy vs best benchmark
best_strat = max(strat_keys, key=lambda k: metrics_all[k]["sharpe"])
best_bench = max(bench_keys, key=lambda k: metrics_all[k]["sharpe"])
print(f"  Best strategy: {best_strat} (Sharpe={metrics_all[best_strat]['sharpe']:.3f})")
print(f"  Best benchmark: {best_bench} (Sharpe={metrics_all[best_bench]['sharpe']:.3f})")

diff_sharpe = metrics_all[best_strat]["sharpe"] - metrics_all[best_bench]["sharpe"]
print(f"  Sharpe difference: {diff_sharpe:+.3f}")

# Check Harvey
best_t = metrics_all[best_strat]["sharpe_t"]
print(f"  Harvey t-stat: {best_t:.2f} ({'PASS' if best_t > 3.0 else 'FAIL'} threshold 3.0)")

# Cross-OOS consistency
s_oos = np.array(cross_oos_results[best_strat])
b_oos = np.array(cross_oos_results[best_bench])
valid_mask = ~(np.isnan(s_oos) | np.isnan(b_oos))
if np.sum(valid_mask) > 0:
    win_rate = np.mean(s_oos[valid_mask] > b_oos[valid_mask])
    print(f"  Cross-OOS win rate vs {best_bench}: {win_rate:.0%} ({int(np.sum(s_oos[valid_mask] > b_oos[valid_mask]))}/5)")

# Final verdict
print(f"""
CONCLUSION:
  Vol dispersion as a trading signal is {'EFFECTIVE' if diff_sharpe > 0.05 and best_t > 3.0 else 'NOT EFFECTIVE'}.
  {'Dispersion provides meaningful alpha over simple benchmarks.' if diff_sharpe > 0.05 and best_t > 3.0 else 'Dispersion does not reliably outperform simple static allocation benchmarks.'}

  Consistent with K164-K165: dispersion is largely absorbed by VIX for prediction,
  and its trading signal value {'exceeds' if diff_sharpe > 0.1 else 'does not exceed'} simple diversification strategies.

  Limitations:
  - Rolling vol window fixed at 22d (not optimized)
  - TX cost assumed 0.1% per unit turnover
  - No short-selling considered
  - Signal is backward-looking (rolling vol), not forward-looking
""")

# ============================================================
# Save results
# ============================================================
results = {
    "experiment": "K254",
    "title": "Cross-Asset Volatility Dispersion as Alpha Signal",
    "timestamp": datetime.now().isoformat(),
    "data": {
        "assets": ASSETS,
        "start": ret_aligned.index[0].strftime("%Y-%m-%d"),
        "end": ret_aligned.index[-1].strftime("%Y-%m-%d"),
        "n_days": len(ret_aligned),
        "vol_window": VOL_WINDOW,
    },
    "signal_stats": {
        "vol_dispersion_mean": round(signals["vol_dispersion"].mean(), 4),
        "vol_dispersion_std": round(signals["vol_dispersion"].std(), 4),
        "avg_corr_mean": round(signals["avg_corr"].mean(), 3),
        "avg_corr_std": round(signals["avg_corr"].std(), 3),
        "corr_disp_vs_avgcorr": round(signals["vol_dispersion"].corr(signals["avg_corr"]), 3),
    },
    "full_sample_metrics": metrics_all,
    "dm_test_results": dm_results,
    "cross_oos": {
        "periods": [label for _, _, label in OOS_PERIODS],
        "sharpe_by_strategy": {k: [round(v, 3) if not np.isnan(v) else None for v in vals]
                               for k, vals in cross_oos_results.items()},
    },
    "conclusion": {
        "best_strategy": best_strat,
        "best_benchmark": best_bench,
        "sharpe_diff": round(diff_sharpe, 3),
        "harvey_pass": best_t > 3.0,
        "effective": diff_sharpe > 0.05 and best_t > 3.0,
    }
}

results_path = "experiments/k254_vol_dispersion_trade_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {results_path}")
print("Done.")
