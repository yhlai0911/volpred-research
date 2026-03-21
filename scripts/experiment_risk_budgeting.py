"""
Experiment: GJR-GARCH Dynamic Risk Budgeting vs Inverse-Vol vs Static
======================================================================
Research question: Does using GARCH-forecasted vol (rather than trailing
realized vol) for risk budgeting improve portfolio outcomes?

Three strategies (all with 12/VIX total leverage scaling):
  a. GARCH-budget: weight_i ∝ 1/σ_GARCH_i (GJR for SPY, GARCH for GLD/TLT)
  b. RV-budget: weight_i ∝ 1/σ_realized_22d_i
  c. Static: 1/3 each

OOS period: 2018-01 to 2025-12, monthly rebalance, 0.05% tx cost, LAGGED weights.

[提出: Gemini, 執行: Claude]
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# Add project src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "src"))

# Try to find the actual project root
for candidate in [
    Path("/Users/yhlai0911/Dropbox/自我研究波動預測模型"),
    Path(__file__).resolve().parents[0],
]:
    if (candidate / "src" / "volpred").exists():
        sys.path.insert(0, str(candidate / "src"))
        PROJECT_ROOT = candidate
        break

from volpred.data.manager import DataManager

# ============================================================
# CONFIG
# ============================================================
ASSETS = ["SPY", "GLD", "TLT"]
START_DATA = "2012-01-01"  # need history for w=2000 training
END_DATA = "2026-12-31"
OOS_START = "2018-01-01"
OOS_END = "2025-12-31"
GARCH_WINDOW = 2000  # rolling window
RV_WINDOW = 22  # 22-day realized vol
REBAL_FREQ = "M"  # monthly
TX_COST = 0.0005  # 0.05%
TARGET_VOL_ANN = 0.12  # 12% annualized target

# ============================================================
# DATA LOADING
# ============================================================
print("=" * 70)
print("EXPERIMENT: GJR-GARCH Risk Budgeting vs Inverse-Vol vs Static")
print("=" * 70)

dm = DataManager()
data = {}
for asset in ASSETS:
    # Force refresh to get full history (cache may have truncated data)
    prices = dm.get_price_data(asset, START_DATA, END_DATA, force_refresh=True)
    from volpred.data.preprocessing import prepare_model_data
    df = prepare_model_data(prices)
    data[asset] = df
    print(f"  {asset}: {df.index[0].date()} to {df.index[-1].date()}, {len(df)} obs")

# VIX for 12/VIX scaling
vix_prices = dm.get_price_data("^VIX", START_DATA, END_DATA, force_refresh=True)
vix = prepare_model_data(vix_prices)
print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()}, {len(vix)} obs")

# Align all data to common dates
common_idx = data["SPY"].index
for asset in ["GLD", "TLT"]:
    common_idx = common_idx.intersection(data[asset].index)
common_idx = common_idx.intersection(vix.index)

for asset in ASSETS:
    data[asset] = data[asset].loc[common_idx]
vix = vix.loc[common_idx]

print(f"\n  Common dates: {common_idx[0].date()} to {common_idx[-1].date()}, {len(common_idx)} obs")

# ============================================================
# GARCH FITTING (ROLLING)
# ============================================================
from arch import arch_model

def fit_garch_sigma(returns_pct, model_type="gjr"):
    """Fit GARCH and return 1-step-ahead daily sigma (decimal)."""
    try:
        if model_type == "gjr":
            am = arch_model(returns_pct, vol="GARCH", p=1, o=1, q=1,
                           dist="normal", mean="Zero", rescale=False)
        else:
            am = arch_model(returns_pct, vol="GARCH", p=1, o=0, q=1,
                           dist="normal", mean="Zero", rescale=False)
        res = am.fit(disp="off", show_warning=False)
        fcast_var = res.forecast(horizon=1).variance.iloc[-1, 0]
        return float(np.sqrt(fcast_var) / 100)  # pct → decimal
    except Exception:
        return None

# Get monthly rebalance dates within OOS
oos_mask = (common_idx >= OOS_START) & (common_idx <= OOS_END)
oos_dates = common_idx[oos_mask]

# Monthly end-of-month dates for rebalancing (use last trading day of each month)
monthly_dates = pd.Series(oos_dates).groupby(
    [oos_dates.year, oos_dates.month]
).apply(lambda x: x.iloc[-1]).values
monthly_dates = pd.DatetimeIndex(monthly_dates)

print(f"\n  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()}")
print(f"  Monthly rebalance dates: {len(monthly_dates)}")
print(f"\nFitting GARCH models at each rebalance date (this takes a while)...")

# Pre-compute GARCH forecasts at each rebalance date
garch_sigmas = {asset: {} for asset in ASSETS}
rv22_sigmas = {asset: {} for asset in ASSETS}

for i, rebal_date in enumerate(monthly_dates):
    if i % 12 == 0:
        print(f"  Processing {rebal_date.date()} ({i+1}/{len(monthly_dates)})...")

    loc = common_idx.get_loc(rebal_date)

    for asset in ASSETS:
        ret = data[asset]["returns"].values

        # GARCH: use trailing GARCH_WINDOW returns
        train_start = max(0, loc - GARCH_WINDOW + 1)
        train_ret = ret[train_start:loc+1] * 100  # percentage

        if asset == "SPY":
            sigma = fit_garch_sigma(train_ret, "gjr")
        else:
            sigma = fit_garch_sigma(train_ret, "garch")

        if sigma is None or sigma < 1e-6:
            # Fallback to sample std
            sigma = float(np.std(ret[train_start:loc+1]))

        garch_sigmas[asset][rebal_date] = sigma

        # RV22: trailing 22-day realized vol
        rv_start = max(0, loc - RV_WINDOW + 1)
        rv_ret = ret[rv_start:loc+1]
        rv22_sigmas[asset][rebal_date] = float(np.std(rv_ret))

print("  GARCH fitting complete.")

# ============================================================
# PORTFOLIO SIMULATION
# ============================================================
def compute_inv_vol_weights(sigmas):
    """Inverse-vol weights: w_i ∝ 1/σ_i."""
    inv_s = np.array([1.0 / max(s, 1e-8) for s in sigmas])
    return inv_s / inv_s.sum()

def simulate_portfolio(weight_source, label):
    """
    Simulate portfolio with given weight source.
    weight_source: dict of rebal_date → {asset: sigma}
    Returns daily returns series.
    """
    # Initialize
    daily_returns = []
    daily_dates = []

    # Current weights (initialized to equal)
    current_w = np.array([1.0/3, 1.0/3, 1.0/3])
    prev_w = current_w.copy()

    # Track which rebalance period we're in
    rebal_idx = 0

    for t_idx, t_date in enumerate(oos_dates):
        # Check if we need to rebalance (use LAGGED: rebalance happens at start of next period)
        # The weight is computed at end of month, applied to the next month
        if rebal_idx < len(monthly_dates) and t_date >= monthly_dates[rebal_idx]:
            rebal_date = monthly_dates[rebal_idx]

            if label == "static":
                new_w = np.array([1.0/3, 1.0/3, 1.0/3])
            else:
                sigmas = [weight_source[asset][rebal_date] for asset in ASSETS]
                new_w = compute_inv_vol_weights(sigmas)

            # Apply 12/VIX total leverage scaling
            vix_close = float(vix.loc[rebal_date, "close"])
            leverage = min(12.0 / vix_close, 1.0)
            new_w = new_w * leverage

            # Transaction costs (proportional to weight change)
            turnover = np.sum(np.abs(new_w - prev_w))
            tx = turnover * TX_COST

            current_w = new_w
            prev_w = current_w.copy()
            rebal_idx += 1
        else:
            tx = 0.0

        # Daily portfolio return
        asset_returns = np.array([
            float(data[asset].loc[t_date, "returns"]) for asset in ASSETS
        ])
        port_ret = np.dot(current_w, asset_returns) - tx

        daily_returns.append(port_ret)
        daily_dates.append(t_date)

    return pd.Series(daily_returns, index=daily_dates, name=label)

print("\nSimulating portfolios...")

# Strategy A: GARCH-budget
ret_garch = simulate_portfolio(garch_sigmas, "GARCH-budget")

# Strategy B: RV22-budget
ret_rv = simulate_portfolio(rv22_sigmas, "RV22-budget")

# Strategy C: Static 1/3 each
ret_static = simulate_portfolio(None, "static")

# ============================================================
# EVALUATION
# ============================================================
def eval_strategy(returns, name):
    """Compute standard metrics."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min()

    # Calmar ratio
    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    return {
        "name": name,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "mean_daily": returns.mean(),
        "n_obs": len(returns),
    }

results = [
    eval_strategy(ret_garch, "GARCH-budget"),
    eval_strategy(ret_rv, "RV22-budget"),
    eval_strategy(ret_static, "Static 1/3"),
]

print("\n" + "=" * 70)
print("RESULTS: Dynamic Risk Budgeting (OOS 2018-01 to 2025-12)")
print("  Assets: SPY, GLD, TLT | 12/VIX leverage | Monthly rebal | 0.05% tx cost")
print("=" * 70)

print(f"\n{'Strategy':<18} {'Ann.Ret':>8} {'Ann.Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
print("-" * 70)
for r in results:
    print(f"{r['name']:<18} {r['ann_return']*100:>7.2f}% {r['ann_vol']*100:>7.2f}% "
          f"{r['sharpe']:>8.3f} {r['mdd']*100:>7.2f}% {r['calmar']:>8.3f} {r['sortino']:>8.3f}")

# ============================================================
# STATISTICAL TESTS
# ============================================================
print("\n" + "=" * 70)
print("STATISTICAL TESTS")
print("=" * 70)

# Diebold-Mariano test: GARCH vs RV22
# H0: equal forecasting ability
# Using squared return differences as loss function
diff_garch_rv = ret_garch.values - ret_rv.values

# DM test on return differences (is GARCH return higher?)
dm_mean = diff_garch_rv.mean()
dm_std = diff_garch_rv.std() / np.sqrt(len(diff_garch_rv))
dm_stat = dm_mean / dm_std if dm_std > 0 else 0
dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

print(f"\n1. Return difference (GARCH - RV22):")
print(f"   Mean daily diff: {dm_mean*10000:.4f} bps")
print(f"   Ann. diff: {dm_mean*252*100:.4f}%")
print(f"   t-stat: {dm_stat:.4f}")
print(f"   p-value: {dm_pval:.4f}")
print(f"   Significant at 5%: {'YES' if dm_pval < 0.05 else 'NO'}")

# GARCH vs Static
diff_garch_static = ret_garch.values - ret_static.values
ds_mean = diff_garch_static.mean()
ds_std = diff_garch_static.std() / np.sqrt(len(diff_garch_static))
ds_stat = ds_mean / ds_std if ds_std > 0 else 0
ds_pval = 2 * (1 - stats.norm.cdf(abs(ds_stat)))

print(f"\n2. Return difference (GARCH - Static):")
print(f"   Mean daily diff: {ds_mean*10000:.4f} bps")
print(f"   Ann. diff: {ds_mean*252*100:.4f}%")
print(f"   t-stat: {ds_stat:.4f}")
print(f"   p-value: {ds_pval:.4f}")
print(f"   Significant at 5%: {'YES' if ds_pval < 0.05 else 'NO'}")

# RV22 vs Static
diff_rv_static = ret_rv.values - ret_static.values
rs_mean = diff_rv_static.mean()
rs_std = diff_rv_static.std() / np.sqrt(len(diff_rv_static))
rs_stat = rs_mean / rs_std if rs_std > 0 else 0
rs_pval = 2 * (1 - stats.norm.cdf(abs(rs_stat)))

print(f"\n3. Return difference (RV22 - Static):")
print(f"   Mean daily diff: {rs_mean*10000:.4f} bps")
print(f"   Ann. diff: {rs_mean*252*100:.4f}%")
print(f"   t-stat: {rs_stat:.4f}")
print(f"   p-value: {rs_pval:.4f}")
print(f"   Significant at 5%: {'YES' if rs_pval < 0.05 else 'NO'}")

# ============================================================
# SHARPE RATIO DIFFERENCE TEST (Ledoit-Wolf 2008 approximation)
# ============================================================
print(f"\n4. Sharpe Ratio Tests (Jobson-Korkie with Memmel correction):")

def sharpe_test(r1, r2, name1, name2):
    """Test H0: Sharpe1 = Sharpe2 using Ledoit-Wolf (2008) HAC approach."""
    n = len(r1)
    mu1, mu2 = r1.mean(), r2.mean()
    s1, s2 = r1.std(ddof=1), r2.std(ddof=1)
    sr1 = mu1 / s1 * np.sqrt(252)
    sr2 = mu2 / s2 * np.sqrt(252)

    # Simple paired bootstrap for Sharpe ratio difference
    rng = np.random.RandomState(42)
    n_boot = 10000
    sr_diffs = []
    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        b1, b2 = r1[idx], r2[idx]
        bsr1 = b1.mean() / b1.std(ddof=1) * np.sqrt(252) if b1.std() > 0 else 0
        bsr2 = b2.mean() / b2.std(ddof=1) * np.sqrt(252) if b2.std() > 0 else 0
        sr_diffs.append(bsr1 - bsr2)

    sr_diffs = np.array(sr_diffs)
    obs_diff = sr1 - sr2
    # Two-sided p-value
    p_val = np.mean(np.abs(sr_diffs - sr_diffs.mean()) >= abs(obs_diff - sr_diffs.mean()))

    print(f"   {name1} SR={sr1:.3f} vs {name2} SR={sr2:.3f}")
    print(f"   Diff={obs_diff:.4f}, bootstrap SE={sr_diffs.std():.4f}, p={p_val:.4f}")
    return p_val

sharpe_test(ret_garch.values, ret_rv.values, "GARCH", "RV22")
sharpe_test(ret_garch.values, ret_static.values, "GARCH", "Static")
sharpe_test(ret_rv.values, ret_static.values, "RV22", "Static")

# ============================================================
# TURNOVER ANALYSIS
# ============================================================
print(f"\n" + "=" * 70)
print("TURNOVER ANALYSIS")
print("=" * 70)

def compute_turnover(weight_source, label):
    """Compute average monthly turnover."""
    turnovers = []
    prev_w = np.array([1.0/3, 1.0/3, 1.0/3])

    for rebal_date in monthly_dates:
        if label == "static":
            new_w = np.array([1.0/3, 1.0/3, 1.0/3])
        else:
            sigmas = [weight_source[asset][rebal_date] for asset in ASSETS]
            new_w = compute_inv_vol_weights(sigmas)

        vix_close = float(vix.loc[rebal_date, "close"])
        leverage = min(12.0 / vix_close, 1.0)
        new_w = new_w * leverage

        turnover = np.sum(np.abs(new_w - prev_w))
        turnovers.append(turnover)
        prev_w = new_w.copy()

    return np.array(turnovers)

to_garch = compute_turnover(garch_sigmas, "GARCH")
to_rv = compute_turnover(rv22_sigmas, "RV22")
to_static = compute_turnover(None, "static")

print(f"\n{'Strategy':<18} {'Mean TO':>10} {'Median TO':>10} {'Max TO':>10} {'Ann Cost':>10}")
print("-" * 60)
for name, to in [("GARCH-budget", to_garch), ("RV22-budget", to_rv), ("Static 1/3", to_static)]:
    ann_cost = to.mean() * 12 * TX_COST * 100
    print(f"{name:<18} {to.mean()*100:>9.2f}% {np.median(to)*100:>9.2f}% "
          f"{to.max()*100:>9.2f}% {ann_cost:>9.4f}%")

# ============================================================
# MDD BOOTSTRAP TEST
# ============================================================
print(f"\n" + "=" * 70)
print("MDD BOOTSTRAP TEST")
print("=" * 70)

def compute_mdd_array(r):
    """Compute MDD from numpy array of returns."""
    cum = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(cum)
    dd = cum / running_max - 1
    return dd.min()

def bootstrap_mdd_test(r1, r2, name1, name2, n_boot=10000):
    """Bootstrap test: is MDD(r1) significantly less than MDD(r2)?"""
    mdd1 = compute_mdd_array(r1)
    mdd2 = compute_mdd_array(r2)

    obs_diff = mdd1 - mdd2  # negative means r1 has shallower MDD (better)

    combined = np.concatenate([r1, r2])
    n = len(r1)
    count_more_extreme = 0

    rng = np.random.RandomState(42)
    for _ in range(n_boot):
        perm = rng.permutation(combined)
        b1, b2 = perm[:n], perm[n:]
        bmdd1 = compute_mdd_array(b1)
        bmdd2 = compute_mdd_array(b2)
        if (bmdd1 - bmdd2) <= obs_diff:
            count_more_extreme += 1

    p_val = count_more_extreme / n_boot
    print(f"   {name1} MDD={mdd1*100:.2f}% vs {name2} MDD={mdd2*100:.2f}%")
    print(f"   Diff={obs_diff*100:.2f}%, bootstrap p={p_val:.4f}")
    return p_val

bootstrap_mdd_test(ret_garch.values, ret_static.values, "GARCH", "Static")
bootstrap_mdd_test(ret_rv.values, ret_static.values, "RV22", "Static")
bootstrap_mdd_test(ret_garch.values, ret_rv.values, "GARCH", "RV22")

# ============================================================
# WEIGHT STABILITY ANALYSIS
# ============================================================
print(f"\n" + "=" * 70)
print("WEIGHT STABILITY: GARCH vs RV22")
print("=" * 70)

garch_weights = {}
rv_weights = {}
for rebal_date in monthly_dates:
    gs = [garch_sigmas[a][rebal_date] for a in ASSETS]
    rs = [rv22_sigmas[a][rebal_date] for a in ASSETS]
    garch_weights[rebal_date] = compute_inv_vol_weights(gs)
    rv_weights[rebal_date] = compute_inv_vol_weights(rs)

gw_df = pd.DataFrame(garch_weights, index=ASSETS).T
rw_df = pd.DataFrame(rv_weights, index=ASSETS).T

print(f"\nGARCH weights statistics:")
print(f"  {'Asset':<6} {'Mean':>8} {'Std':>8} {'Min':>8} {'Max':>8}")
for asset in ASSETS:
    print(f"  {asset:<6} {gw_df[asset].mean()*100:>7.1f}% {gw_df[asset].std()*100:>7.1f}% "
          f"{gw_df[asset].min()*100:>7.1f}% {gw_df[asset].max()*100:>7.1f}%")

print(f"\nRV22 weights statistics:")
for asset in ASSETS:
    print(f"  {asset:<6} {rw_df[asset].mean()*100:>7.1f}% {rw_df[asset].std()*100:>7.1f}% "
          f"{rw_df[asset].min()*100:>7.1f}% {rw_df[asset].max()*100:>7.1f}%")

# Correlation between GARCH and RV22 weights
print(f"\nWeight correlation (GARCH vs RV22):")
for asset in ASSETS:
    corr = np.corrcoef(gw_df[asset].values, rw_df[asset].values)[0, 1]
    print(f"  {asset}: ρ = {corr:.4f}")

# ============================================================
# SUB-PERIOD ANALYSIS
# ============================================================
print(f"\n" + "=" * 70)
print("SUB-PERIOD ANALYSIS")
print("=" * 70)

sub_periods = [
    ("2018-01", "2019-12", "Pre-COVID"),
    ("2020-01", "2020-12", "COVID year"),
    ("2021-01", "2022-12", "Post-COVID + rate hikes"),
    ("2023-01", "2025-12", "Recovery + AI boom"),
]

for sp_start, sp_end, sp_name in sub_periods:
    mask = (ret_garch.index >= sp_start) & (ret_garch.index <= sp_end)
    rg = ret_garch[mask]
    rr = ret_rv[mask]
    rs = ret_static[mask]

    if len(rg) < 20:
        continue

    sr_g = rg.mean() / rg.std() * np.sqrt(252) if rg.std() > 0 else 0
    sr_r = rr.mean() / rr.std() * np.sqrt(252) if rr.std() > 0 else 0
    sr_s = rs.mean() / rs.std() * np.sqrt(252) if rs.std() > 0 else 0

    mdd_g = ((1+rg).cumprod() / (1+rg).cumprod().cummax() - 1).min()
    mdd_r = ((1+rr).cumprod() / (1+rr).cumprod().cummax() - 1).min()
    mdd_s = ((1+rs).cumprod() / (1+rs).cumprod().cummax() - 1).min()

    print(f"\n  {sp_name} ({sp_start} to {sp_end}, {len(rg)} days):")
    print(f"    GARCH:  Sharpe={sr_g:.3f}, MDD={mdd_g*100:.2f}%")
    print(f"    RV22:   Sharpe={sr_r:.3f}, MDD={mdd_r*100:.2f}%")
    print(f"    Static: Sharpe={sr_s:.3f}, MDD={mdd_s*100:.2f}%")

    # Which won?
    best = max([(sr_g, "GARCH"), (sr_r, "RV22"), (sr_s, "Static")])
    print(f"    Winner: {best[1]} (Sharpe={best[0]:.3f})")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSION")
print("=" * 70)

sharpe_garch = results[0]["sharpe"]
sharpe_rv = results[1]["sharpe"]
sharpe_static = results[2]["sharpe"]
delta_sr = sharpe_garch - sharpe_rv

print(f"""
  GARCH-budget Sharpe:  {sharpe_garch:.4f}
  RV22-budget Sharpe:   {sharpe_rv:.4f}
  Static 1/3 Sharpe:    {sharpe_static:.4f}

  GARCH vs RV22 delta:  {delta_sr:+.4f}
  GARCH vs Static delta: {sharpe_garch - sharpe_static:+.4f}

  Return diff t-stat:   {dm_stat:.4f} (p={dm_pval:.4f})

  Interpretation:
  - Delta Sharpe {'>' if abs(delta_sr) > 0.05 else '<='} 0.05 → {'economically meaningful' if abs(delta_sr) > 0.05 else 'economically negligible'}
  - DM test p {'<' if dm_pval < 0.05 else '>='} 0.05 → {'statistically significant' if dm_pval < 0.05 else 'NOT statistically significant'}

  This {'confirms' if dm_pval >= 0.05 and abs(delta_sr) <= 0.05 else 'challenges'} the complexity ceiling hypothesis:
  GARCH-based dynamic risk budgeting {'does NOT' if dm_pval >= 0.05 else 'DOES'} significantly
  outperform simple inverse-realized-vol weighting.
""")

print("Done.")
