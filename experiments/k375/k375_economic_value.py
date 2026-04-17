"""
K375: Economic Value of Vol Forecasts — How Much Money Can Better Vol Prediction Make?
======================================================================================
[提出: 用戶, 執行: Claude]

Pre-experiment check:
  K372: 48.7% of return variance is noise
  K373: Parkinson +31% R²
  K374: evaluation artifact in QLIKE
  K147: Execution Alpha ≈ $0.20/trade
  K229: VT insurance costs 3.05%/yr
  K262: Protection cost menu (5 levels)

But NONE of these ask: what is the DOLLAR VALUE of a better vol forecast?

Background:
  We've measured vol forecast quality by QLIKE/MSE. But what's the ECONOMIC value?
  If GJR-GARCH is 1% better than EWMA in QLIKE, how many dollars does that translate to?

Data: SPY, GLD, VIX daily from yfinance, 2005-2024.

Methodology:
  1. Three vol forecasters (all bias-free, lagged — no look-ahead):
     - EWMA(0.94)
     - GJR-GARCH(1,1,1)
     - VIX/sqrt(252) (market-implied)
  2. Each forecaster sets VT weight: w = min(1, target_vol / forecast_vol)
     with target_vol = 12% annualized
  3. Portfolio: 50/50 SPY/GLD with VT overlay
  4. Economic value = Sharpe(better forecast) - Sharpe(worse forecast)
  5. Dollar value: on $1M portfolio, 20 years
     - Terminal wealth difference
     - MDD difference (in dollars)
  6. Marginal value: QLIKE improvement → Sharpe improvement
     - Sweep EWMA lambda from 0.80 to 0.99 (20 variants)
     - Plot QLIKE vs Sharpe: linear? diminishing returns?

Output: Console + JSON to storage/results/k375_economic_value.json
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime
import json

np.random.seed(42)

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2004-01-01"       # buffer for warm-up
BACKTEST_START = "2005-01-03"   # GLD available from Nov 2004
BACKTEST_END = "2024-12-31"
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252
INITIAL_CAPITAL = 1_000_000     # $1M portfolio
TARGET_VOL = 0.12               # 12% annualized target vol
GJR_WINDOW = 2000               # rolling window for GJR-GARCH
TX_COST_BPS = 5                 # 5 bps one-way transaction cost

# EWMA lambda sweep for marginal value analysis
EWMA_LAMBDAS = np.arange(0.80, 0.995, 0.01)

print("=" * 90)
print("K375: ECONOMIC VALUE OF VOL FORECASTS")
print("How Much Money Can Better Vol Prediction Make?")
print("[提出: 用戶, 執行: Claude]")
print("=" * 90)
print(f"  Data source: yfinance (SPY, GLD, ^VIX)")
print(f"  Period: {BACKTEST_START} to {BACKTEST_END}")
print(f"  Initial capital: ${INITIAL_CAPITAL:,.0f}")
print(f"  Target vol: {TARGET_VOL*100:.0f}% annualized")
print(f"  GJR window: {GJR_WINDOW}")
print(f"  TX cost: {TX_COST_BPS} bps one-way")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n" + "=" * 90)
print("[1/7] DOWNLOADING DATA FROM YFINANCE")
print("=" * 90)

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw_data = {}

for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2025-06-01", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    raw_data[name] = df[[col]].rename(columns={col: name.lower()})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Merge on common dates
data = raw_data["SPY"].join(raw_data["GLD"], how="inner") \
                       .join(raw_data["VIX"], how="inner")
data = data.loc[BACKTEST_START:BACKTEST_END].copy()
print(f"\n  Merged dataset: {len(data)} trading days")
print(f"  Date range: {data.index[0].date()} to {data.index[-1].date()}")

# Compute daily log returns
data["spy_ret"] = np.log(data["spy"] / data["spy"].shift(1))
data["gld_ret"] = np.log(data["gld"] / data["gld"].shift(1))
data = data.dropna()
n_days = len(data)
n_years = n_days / 252
print(f"  Usable days after returns: {n_days} ({n_years:.1f} years)")

# Realized variance proxy: squared return
data["rv_spy"] = data["spy_ret"] ** 2

# ==================================================================
# 2. Build Vol Forecasters (all t-1 lagged, no look-ahead)
# ==================================================================
print("\n" + "=" * 90)
print("[2/7] BUILDING VOL FORECASTERS (ALL LAGGED, NO LOOK-AHEAD)")
print("=" * 90)

# --- 2a. EWMA(0.94) ---
print("  Computing EWMA(0.94) forecasts...")
ewma_var = np.zeros(n_days)
lam = 0.94
ret_arr = data["spy_ret"].values
# Initialize with first 60 days sample variance
init_var = np.var(ret_arr[:60])
ewma_var[0] = init_var
for t in range(1, n_days):
    ewma_var[t] = lam * ewma_var[t-1] + (1 - lam) * ret_arr[t-1]**2
# ewma_var[t] is the forecast MADE at end of day t-1 for day t's variance
data["ewma_forecast"] = ewma_var  # already lagged: uses info up to t-1
print(f"    Mean daily var forecast: {np.mean(ewma_var):.6f}")

# --- 2b. GJR-GARCH(1,1,1) rolling ---
print(f"  Computing GJR-GARCH(1,1,1) rolling forecasts (window={GJR_WINDOW})...")
gjr_forecast = np.full(n_days, np.nan)
ret_pct = ret_arr * 100  # arch package uses percentage returns

n_fitted = 0
n_failed = 0
for t in range(GJR_WINDOW, n_days):
    window_ret = ret_pct[t-GJR_WINDOW:t]
    try:
        am = arch_model(window_ret, vol='Garch', p=1, o=1, q=1,
                        mean='Zero', dist='normal', rescale=False)
        res = am.fit(disp='off', show_warning=False)
        # One-step-ahead forecast (variance in pct^2)
        fc = res.forecast(horizon=1, reindex=False)
        var_pct2 = fc.variance.values[-1, 0]
        gjr_forecast[t] = var_pct2 / (100**2)  # convert back to decimal
        n_fitted += 1
    except Exception:
        # Fallback to EWMA
        gjr_forecast[t] = ewma_var[t]
        n_failed += 1

    if (t - GJR_WINDOW) % 500 == 0:
        print(f"    Progress: {t-GJR_WINDOW}/{n_days-GJR_WINDOW} days fitted...")

print(f"    Fitted: {n_fitted}, Failed: {n_failed} ({n_failed/(n_fitted+n_failed)*100:.1f}%)")

# Fill early period with EWMA
gjr_forecast[:GJR_WINDOW] = ewma_var[:GJR_WINDOW]
data["gjr_forecast"] = gjr_forecast
print(f"    Mean daily var forecast (GJR, OOS): {np.nanmean(gjr_forecast[GJR_WINDOW:]):.6f}")

# --- 2c. VIX-implied ---
print("  Computing VIX-implied forecasts...")
vix_arr = data["vix"].values
# VIX is annualized vol in %, convert to daily variance
# VIX(t) uses yesterday's info effectively (closing VIX at day t)
# We use VIX(t-1) to forecast day t's vol
vix_daily_var = (vix_arr / 100)**2 / 252
data["vix_forecast"] = pd.Series(vix_daily_var, index=data.index).shift(1).values
# Fill first value
data.loc[data.index[0], "vix_forecast"] = vix_daily_var[0]
print(f"    Mean daily var forecast: {np.nanmean(data['vix_forecast'].values):.6f}")

# ==================================================================
# 3. QLIKE Evaluation of Forecasters
# ==================================================================
print("\n" + "=" * 90)
print("[3/7] FORECAST ACCURACY (QLIKE)")
print("=" * 90)

# Only evaluate where all forecasts are available (after GJR warm-up)
eval_mask = data.index >= data.index[GJR_WINDOW]
eval_data = data.loc[eval_mask].copy()
n_eval = len(eval_data)
print(f"  Evaluation period: {eval_data.index[0].date()} to {eval_data.index[-1].date()}")
print(f"  Evaluation days: {n_eval}")

rv = eval_data["rv_spy"].values
forecasters = {
    "EWMA(0.94)": eval_data["ewma_forecast"].values,
    "GJR-GARCH":  eval_data["gjr_forecast"].values,
    "VIX-implied": eval_data["vix_forecast"].values,
}

def compute_qlike(rv, h):
    """QLIKE loss: rv/h - log(rv/h) - 1. Lower = better."""
    ratio = rv / h
    # Avoid log(0) or div by 0
    ratio = np.clip(ratio, 1e-10, 1e10)
    return np.mean(ratio - np.log(ratio) - 1)

print(f"\n  {'Model':<16s} {'QLIKE':>10s} {'QLIKE rank':>12s}")
print(f"  {'-'*16} {'-'*10} {'-'*12}")

qlike_scores = {}
for name, h in forecasters.items():
    q = compute_qlike(rv, h)
    qlike_scores[name] = q

# Rank
ranked = sorted(qlike_scores.items(), key=lambda x: x[1])
for rank, (name, q) in enumerate(ranked, 1):
    print(f"  {name:<16s} {q:>10.4f} {rank:>12d}")

best_model = ranked[0][0]
print(f"\n  Best forecaster by QLIKE: {best_model}")

# Diebold-Mariano tests
print(f"\n  Diebold-Mariano Tests (pairwise):")
print(f"  {'Pair':<35s} {'DM stat':>10s} {'p-value':>10s} {'Better':>12s}")
print(f"  {'-'*35} {'-'*10} {'-'*10} {'-'*12}")

model_names = list(forecasters.keys())
dm_results = {}
for i in range(len(model_names)):
    for j in range(i+1, len(model_names)):
        m1, m2 = model_names[i], model_names[j]
        h1 = forecasters[m1]
        h2 = forecasters[m2]
        # QLIKE loss difference
        d = (rv/h1 - np.log(rv/h1)) - (rv/h2 - np.log(rv/h2))
        dm_stat = np.mean(d) / (np.std(d) / np.sqrt(len(d)))
        p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
        better = m1 if dm_stat < 0 else m2
        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
        print(f"  {m1} vs {m2:<15s} {dm_stat:>10.3f} {p_val:>9.4f}{sig:>3s} {better:>12s}")
        dm_results[f"{m1}_vs_{m2}"] = {"dm_stat": round(dm_stat, 4), "p": round(p_val, 4)}

# ==================================================================
# 4. Portfolio Simulation with Each Forecaster
# ==================================================================
print("\n" + "=" * 90)
print("[4/7] PORTFOLIO SIMULATION — EACH FORECASTER DRIVES VT WEIGHTS")
print("=" * 90)

def simulate_vt_portfolio(spy_ret, gld_ret, vol_forecast_daily_var,
                          target_vol=TARGET_VOL, tx_bps=TX_COST_BPS,
                          label=""):
    """
    Simulate a 50/50 SPY/GLD portfolio with VT overlay.

    VT weight = min(1, target_vol / forecast_vol)
    where forecast_vol = sqrt(forecast_daily_var * 252)

    Returns dict with performance metrics + wealth path.
    """
    n = len(spy_ret)

    # Annualized vol forecast from daily variance
    forecast_vol = np.sqrt(np.maximum(vol_forecast_daily_var, 1e-10) * 252)

    # VT weight (lagged — set at end of previous day)
    vt_weight = np.minimum(1.0, target_vol / forecast_vol)

    # Portfolio returns: 50/50 base, scaled by VT weight
    base_ret = 0.5 * spy_ret + 0.5 * gld_ret
    port_ret = vt_weight * base_ret

    # Transaction costs from weight changes
    weight_change = np.abs(np.diff(vt_weight, prepend=vt_weight[0]))
    tx_cost = weight_change * (tx_bps / 10000)
    port_ret_net = port_ret - tx_cost

    # Wealth path
    wealth = INITIAL_CAPITAL * np.cumprod(1 + port_ret_net)

    # Metrics
    ann_ret = np.mean(port_ret_net) * 252
    ann_vol = np.std(port_ret_net) * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # CAGR
    total_return = wealth[-1] / INITIAL_CAPITAL
    cagr = total_return ** (1 / (n / 252)) - 1

    # Max drawdown
    peak = np.maximum.accumulate(wealth)
    drawdown = (wealth - peak) / peak
    mdd = np.min(drawdown)
    mdd_dollars = np.min(wealth - peak)

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside_ret = port_ret_net[port_ret_net < 0]
    downside_vol = np.std(downside_ret) * np.sqrt(252) if len(downside_ret) > 0 else ann_vol
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    # Average VT weight
    avg_weight = np.mean(vt_weight)

    # Turnover (annualized)
    turnover = np.mean(weight_change) * 252

    return {
        "label": label,
        "terminal_wealth": wealth[-1],
        "cagr": cagr,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "mdd": mdd,
        "mdd_dollars": mdd_dollars,
        "calmar": calmar,
        "avg_vt_weight": avg_weight,
        "turnover_annual": turnover,
        "tx_cost_total": np.sum(tx_cost) * INITIAL_CAPITAL,
        "wealth_path": wealth,
        "vt_weights": vt_weight,
        "port_ret_net": port_ret_net,
    }

# Also compute Buy & Hold 50/50 (no VT) as benchmark
spy_ret_arr = data["spy_ret"].values
gld_ret_arr = data["gld_ret"].values
bh_ret = 0.5 * spy_ret_arr + 0.5 * gld_ret_arr
bh_wealth = INITIAL_CAPITAL * np.cumprod(1 + bh_ret)
bh_ann_ret = np.mean(bh_ret) * 252
bh_ann_vol = np.std(bh_ret) * np.sqrt(252)
bh_sharpe = (bh_ann_ret - RF_ANNUAL) / bh_ann_vol
bh_total = bh_wealth[-1] / INITIAL_CAPITAL
bh_cagr = bh_total ** (1 / n_years) - 1
bh_peak = np.maximum.accumulate(bh_wealth)
bh_dd = (bh_wealth - bh_peak) / bh_peak
bh_mdd = np.min(bh_dd)
bh_mdd_dollars = np.min(bh_wealth - bh_peak)

print(f"\n  BENCHMARK: Buy & Hold 50/50 SPY/GLD (no VT)")
print(f"    Terminal wealth: ${bh_wealth[-1]:,.0f}")
print(f"    CAGR: {bh_cagr*100:.2f}%")
print(f"    Sharpe: {bh_sharpe:.3f}")
print(f"    MDD: {bh_mdd*100:.1f}% (${bh_mdd_dollars:,.0f})")

# Simulate with each forecaster
forecast_vars = {
    "EWMA(0.94)":  data["ewma_forecast"].values,
    "GJR-GARCH":   data["gjr_forecast"].values,
    "VIX-implied":  data["vix_forecast"].values,
}

results = {}
print(f"\n  {'Model':<16s} {'Terminal $':>14s} {'CAGR':>8s} {'Sharpe':>8s} "
      f"{'Sortino':>8s} {'MDD':>8s} {'MDD $':>12s} {'Avg Wt':>8s} {'Turn':>8s}")
print(f"  {'-'*16} {'-'*14} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12} {'-'*8} {'-'*8}")

# Add B&H row
print(f"  {'B&H 50/50':<16s} {bh_wealth[-1]:>14,.0f} {bh_cagr*100:>7.2f}% {bh_sharpe:>8.3f} "
      f"{'N/A':>8s} {bh_mdd*100:>7.1f}% {bh_mdd_dollars:>11,.0f} {'100%':>8s} {'0%':>8s}")

for name, fvar in forecast_vars.items():
    res = simulate_vt_portfolio(spy_ret_arr, gld_ret_arr, fvar, label=name)
    results[name] = res
    print(f"  {name:<16s} {res['terminal_wealth']:>14,.0f} {res['cagr']*100:>7.2f}% "
          f"{res['sharpe']:>8.3f} {res['sortino']:>8.3f} {res['mdd']*100:>7.1f}% "
          f"{res['mdd_dollars']:>11,.0f} {res['avg_vt_weight']*100:>7.1f}% "
          f"{res['turnover_annual']*100:>7.1f}%")

# ==================================================================
# 5. Economic Value: Pairwise Comparisons
# ==================================================================
print("\n" + "=" * 90)
print("[5/7] ECONOMIC VALUE — PAIRWISE COMPARISONS")
print("=" * 90)

print(f"\n  On a ${INITIAL_CAPITAL:,.0f} portfolio over {n_years:.0f} years:")
print(f"\n  {'Comparison':<35s} {'Sharpe Δ':>10s} {'CAGR Δ':>10s} "
      f"{'Terminal $ Δ':>14s} {'MDD Δ':>10s} {'MDD $ Δ':>12s}")
print(f"  {'-'*35} {'-'*10} {'-'*10} {'-'*14} {'-'*10} {'-'*12}")

comparisons = [
    ("GJR-GARCH", "EWMA(0.94)"),
    ("VIX-implied", "EWMA(0.94)"),
    ("GJR-GARCH", "VIX-implied"),
    # vs B&H
]

econ_value = {}
for better, worse in comparisons:
    rb = results[better]
    rw = results[worse]
    sharpe_d = rb["sharpe"] - rw["sharpe"]
    cagr_d = rb["cagr"] - rw["cagr"]
    terminal_d = rb["terminal_wealth"] - rw["terminal_wealth"]
    mdd_d = rb["mdd"] - rw["mdd"]  # less negative = better
    mdd_d_dollars = rb["mdd_dollars"] - rw["mdd_dollars"]

    label = f"{better} vs {worse}"
    print(f"  {label:<35s} {sharpe_d:>+10.4f} {cagr_d*100:>+9.2f}% "
          f"{terminal_d:>+14,.0f} {mdd_d*100:>+9.1f}% {mdd_d_dollars:>+11,.0f}")

    econ_value[label] = {
        "sharpe_delta": round(sharpe_d, 4),
        "cagr_delta_pct": round(cagr_d * 100, 3),
        "terminal_wealth_delta": round(terminal_d, 0),
        "mdd_delta_pct": round(mdd_d * 100, 2),
        "mdd_delta_dollars": round(mdd_d_dollars, 0),
    }

# Value vs B&H
print(f"\n  Value of VT (vs Buy & Hold 50/50):")
print(f"  {'Comparison':<35s} {'Sharpe Δ':>10s} {'CAGR Δ':>10s} "
      f"{'Terminal $ Δ':>14s} {'MDD Δ':>10s}")
print(f"  {'-'*35} {'-'*10} {'-'*10} {'-'*14} {'-'*10}")

for name, res in results.items():
    sharpe_d = res["sharpe"] - bh_sharpe
    cagr_d = res["cagr"] - bh_cagr
    terminal_d = res["terminal_wealth"] - bh_wealth[-1]
    mdd_d = res["mdd"] - bh_mdd
    label = f"{name} VT vs B&H"
    print(f"  {label:<35s} {sharpe_d:>+10.4f} {cagr_d*100:>+9.2f}% "
          f"{terminal_d:>+14,.0f} {mdd_d*100:>+9.1f}%")

    econ_value[f"VT({name})_vs_BH"] = {
        "sharpe_delta": round(sharpe_d, 4),
        "cagr_delta_pct": round(cagr_d * 100, 3),
        "terminal_wealth_delta": round(terminal_d, 0),
        "mdd_delta_pct": round(mdd_d * 100, 2),
    }

# ==================================================================
# 6. Marginal Value: QLIKE vs Sharpe (EWMA Lambda Sweep)
# ==================================================================
print("\n" + "=" * 90)
print("[6/7] MARGINAL VALUE: QLIKE vs SHARPE (EWMA LAMBDA SWEEP)")
print("=" * 90)
print(f"  Sweeping EWMA lambda from {EWMA_LAMBDAS[0]:.2f} to {EWMA_LAMBDAS[-1]:.2f}")
print(f"  Total variants: {len(EWMA_LAMBDAS)}")

sweep_results = []

for lam_i in EWMA_LAMBDAS:
    # Compute EWMA with this lambda
    ew = np.zeros(n_days)
    ew[0] = init_var
    for t in range(1, n_days):
        ew[t] = lam_i * ew[t-1] + (1 - lam_i) * ret_arr[t-1]**2

    # QLIKE (on eval period)
    h_eval = ew[data.index >= data.index[GJR_WINDOW]][:n_eval]
    if len(h_eval) < n_eval:
        h_eval = np.pad(h_eval, (0, n_eval - len(h_eval)), mode='edge')
    q = compute_qlike(rv[:len(h_eval)], h_eval[:len(rv)])

    # Simulate VT portfolio
    res = simulate_vt_portfolio(spy_ret_arr, gld_ret_arr, ew,
                                label=f"EWMA({lam_i:.2f})")

    sweep_results.append({
        "lambda": round(lam_i, 3),
        "qlike": round(q, 6),
        "sharpe": round(res["sharpe"], 4),
        "cagr": round(res["cagr"] * 100, 3),
        "terminal_wealth": round(res["terminal_wealth"], 0),
        "mdd": round(res["mdd"] * 100, 2),
        "avg_vt_weight": round(res["avg_vt_weight"], 4),
        "sortino": round(res["sortino"], 4),
    })

# Display sweep
print(f"\n  {'Lambda':>8s} {'QLIKE':>10s} {'Sharpe':>8s} {'CAGR':>8s} "
      f"{'Terminal $':>14s} {'MDD':>8s} {'Avg Wt':>8s}")
print(f"  {'-'*8} {'-'*10} {'-'*8} {'-'*8} {'-'*14} {'-'*8} {'-'*8}")

for sr in sweep_results:
    print(f"  {sr['lambda']:>8.3f} {sr['qlike']:>10.4f} {sr['sharpe']:>8.4f} "
          f"{sr['cagr']:>7.2f}% {sr['terminal_wealth']:>14,.0f} "
          f"{sr['mdd']:>7.1f}% {sr['avg_vt_weight']*100:>7.1f}%")

# Regression: QLIKE → Sharpe
qlikes = np.array([s["qlike"] for s in sweep_results])
sharpes = np.array([s["sharpe"] for s in sweep_results])
cagrs = np.array([s["cagr"] for s in sweep_results])
terminals = np.array([s["terminal_wealth"] for s in sweep_results])

# Linear regression
slope_qs, intercept_qs, r_qs, p_qs, se_qs = stats.linregress(qlikes, sharpes)
slope_qt, intercept_qt, r_qt, p_qt, se_qt = stats.linregress(qlikes, terminals)
slope_qc, intercept_qc, r_qc, p_qc, se_qc = stats.linregress(qlikes, cagrs)

print(f"\n  REGRESSION: QLIKE → Sharpe")
print(f"    Slope: {slope_qs:.4f} (1 unit QLIKE improvement → {abs(slope_qs):.4f} Sharpe change)")
print(f"    R²: {r_qs**2:.4f}")
print(f"    p-value: {p_qs:.6f}")

print(f"\n  REGRESSION: QLIKE → Terminal Wealth ($)")
print(f"    Slope: ${slope_qt:,.0f} (1 unit QLIKE improvement → ${abs(slope_qt):,.0f} on ${INITIAL_CAPITAL:,.0f})")
print(f"    R²: {r_qt**2:.4f}")
print(f"    p-value: {p_qt:.6f}")

print(f"\n  REGRESSION: QLIKE → CAGR (%)")
print(f"    Slope: {slope_qc:.4f}% (1 unit QLIKE improvement → {abs(slope_qc):.4f}% CAGR change)")
print(f"    R²: {r_qc**2:.4f}")
print(f"    p-value: {p_qc:.6f}")

# Best and worst EWMA variants
best_ewma = max(sweep_results, key=lambda x: x["sharpe"])
worst_ewma = min(sweep_results, key=lambda x: x["sharpe"])
best_qlike_ewma = min(sweep_results, key=lambda x: x["qlike"])
worst_qlike_ewma = max(sweep_results, key=lambda x: x["qlike"])

print(f"\n  Best Sharpe EWMA:  lambda={best_ewma['lambda']:.3f}, "
      f"Sharpe={best_ewma['sharpe']:.4f}, QLIKE={best_ewma['qlike']:.4f}")
print(f"  Worst Sharpe EWMA: lambda={worst_ewma['lambda']:.3f}, "
      f"Sharpe={worst_ewma['sharpe']:.4f}, QLIKE={worst_ewma['qlike']:.4f}")
print(f"  Best QLIKE EWMA:   lambda={best_qlike_ewma['lambda']:.3f}, "
      f"Sharpe={best_qlike_ewma['sharpe']:.4f}, QLIKE={best_qlike_ewma['qlike']:.4f}")

# Range of outcomes across EWMA variants
sharpe_range = max(sharpes) - min(sharpes)
terminal_range = max(terminals) - min(terminals)
cagr_range = max(cagrs) - min(cagrs)
print(f"\n  Outcome range across {len(EWMA_LAMBDAS)} EWMA variants:")
print(f"    Sharpe range: {sharpe_range:.4f}")
print(f"    CAGR range: {cagr_range:.2f}%")
print(f"    Terminal wealth range: ${terminal_range:,.0f}")

# ==================================================================
# 7. Summary & Dollar Translation
# ==================================================================
print("\n" + "=" * 90)
print("[7/7] SUMMARY: THE DOLLAR VALUE OF VOL FORECASTING")
print("=" * 90)

# Per-year dollar value
print(f"\n  A. ANNUAL DOLLAR VALUE OF BETTER FORECASTING (on ${INITIAL_CAPITAL:,.0f})")
print(f"  {'Upgrade path':<35s} {'Sharpe Δ':>10s} {'$/year':>12s} {'$/20yr':>14s}")
print(f"  {'-'*35} {'-'*10} {'-'*12} {'-'*14}")

for label, ev in econ_value.items():
    if "vs_BH" not in label:
        # Approximate annual dollar value from CAGR difference
        annual_dollar = INITIAL_CAPITAL * abs(ev["cagr_delta_pct"]) / 100
        total_dollar = abs(ev["terminal_wealth_delta"])
        print(f"  {label:<35s} {ev['sharpe_delta']:>+10.4f} "
              f"${annual_dollar:>11,.0f} ${total_dollar:>13,.0f}")

print(f"\n  B. VALUE OF VT ITSELF (any forecaster vs B&H)")
for label, ev in econ_value.items():
    if "vs_BH" in label:
        annual_dollar = INITIAL_CAPITAL * abs(ev["cagr_delta_pct"]) / 100
        total_dollar = abs(ev["terminal_wealth_delta"])
        print(f"  {label:<35s} {ev['sharpe_delta']:>+10.4f} "
              f"${annual_dollar:>11,.0f}/yr ${total_dollar:>13,.0f}/20yr")

# Marginal value interpretation
print(f"\n  C. MARGINAL VALUE: QLIKE → DOLLARS")
if slope_qt != 0:
    qlike_range = max(qlikes) - min(qlikes)
    dollars_per_qlike = abs(slope_qt)
    print(f"    QLIKE range across EWMA variants: {qlike_range:.4f}")
    print(f"    1 unit QLIKE improvement = ${dollars_per_qlike:,.0f} over {n_years:.0f} years")
    print(f"    0.01 QLIKE improvement = ${dollars_per_qlike * 0.01:,.0f} over {n_years:.0f} years")

    # GJR vs EWMA QLIKE difference and its dollar value
    gjr_qlike = qlike_scores.get("GJR-GARCH", 0)
    ewma_qlike = qlike_scores.get("EWMA(0.94)", 0)
    qlike_diff = ewma_qlike - gjr_qlike
    predicted_dollar_diff = qlike_diff * slope_qt
    actual_dollar_diff = results["GJR-GARCH"]["terminal_wealth"] - results["EWMA(0.94)"]["terminal_wealth"]

    print(f"\n    GJR vs EWMA QLIKE difference: {qlike_diff:.4f}")
    print(f"    Predicted $ difference (from regression): ${predicted_dollar_diff:,.0f}")
    print(f"    Actual $ difference (from simulation): ${actual_dollar_diff:,.0f}")

# Diminishing returns check
print(f"\n  D. IS THERE DIMINISHING RETURNS?")
# Split QLIKE range into halves
median_qlike = np.median(qlikes)
lower_half = [(q, s) for q, s in zip(qlikes, sharpes) if q <= median_qlike]
upper_half = [(q, s) for q, s in zip(qlikes, sharpes) if q > median_qlike]

if len(lower_half) >= 3 and len(upper_half) >= 3:
    lq, ls = zip(*lower_half)
    uq, us = zip(*upper_half)
    slope_lower, _, _, _, _ = stats.linregress(lq, ls)
    slope_upper, _, _, _, _ = stats.linregress(uq, us)
    print(f"    Slope (better half, low QLIKE): {slope_lower:.4f}")
    print(f"    Slope (worse half, high QLIKE): {slope_upper:.4f}")
    if abs(slope_lower) < abs(slope_upper):
        print(f"    → DIMINISHING RETURNS: improving an already-good forecast yields less Sharpe gain")
    else:
        print(f"    → NO diminishing returns detected (improving good forecasts still pays off)")

# Final key numbers
print(f"\n  E. KEY TAKEAWAYS")
best_vt = max(results.items(), key=lambda x: x[1]["sharpe"])
worst_vt = min(results.items(), key=lambda x: x[1]["sharpe"])
print(f"    Best VT forecaster: {best_vt[0]} (Sharpe={best_vt[1]['sharpe']:.3f})")
print(f"    Worst VT forecaster: {worst_vt[0]} (Sharpe={worst_vt[1]['sharpe']:.3f})")
print(f"    Forecaster choice Sharpe gap: {best_vt[1]['sharpe'] - worst_vt[1]['sharpe']:.4f}")
print(f"    Forecaster choice $ gap (terminal): "
      f"${best_vt[1]['terminal_wealth'] - worst_vt[1]['terminal_wealth']:,.0f}")
print(f"    Forecaster choice $ gap (annual approx): "
      f"${(best_vt[1]['cagr'] - worst_vt[1]['cagr']) * INITIAL_CAPITAL:,.0f}")
print(f"    B&H → any VT: Sharpe improvement = "
      f"+{np.mean([r['sharpe'] for r in results.values()]) - bh_sharpe:.4f}")

# Statistical significance of forecaster choice
# Bootstrap the Sharpe difference between best and worst VT
print(f"\n  F. STATISTICAL SIGNIFICANCE OF FORECASTER CHOICE")
best_name = best_vt[0]
worst_name = worst_vt[0]
best_rets = results[best_name]["port_ret_net"]
worst_rets = results[worst_name]["port_ret_net"]
ret_diff = best_rets - worst_rets

n_boot = 10000
boot_sharpe_diff = np.zeros(n_boot)
for b in range(n_boot):
    idx = np.random.randint(0, len(ret_diff), size=len(ret_diff))
    d = ret_diff[idx]
    boot_sharpe_diff[b] = np.mean(d) / np.std(d) * np.sqrt(252)

ci_low = np.percentile(boot_sharpe_diff, 2.5)
ci_high = np.percentile(boot_sharpe_diff, 97.5)
observed = (np.mean(ret_diff) / np.std(ret_diff)) * np.sqrt(252)
p_zero = np.mean(boot_sharpe_diff <= 0)

print(f"    {best_name} vs {worst_name}:")
print(f"    Observed Sharpe difference: {observed:.4f}")
print(f"    95% CI: [{ci_low:.4f}, {ci_high:.4f}]")
print(f"    P(Sharpe diff <= 0): {p_zero:.4f}")
if ci_low > 0:
    print(f"    → SIGNIFICANT: {best_name} reliably outperforms {worst_name}")
elif p_zero < 0.05:
    print(f"    → MARGINALLY SIGNIFICANT at 5% level")
else:
    print(f"    → NOT SIGNIFICANT: forecaster choice does NOT reliably matter for Sharpe")

# ==================================================================
# 8. Save Results
# ==================================================================
print("\n" + "=" * 90)
print("SAVING RESULTS")
print("=" * 90)

output = {
    "experiment": "K375",
    "title": "Economic Value of Vol Forecasts",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "period": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_days": n_days,
    "n_years": round(n_years, 1),
    "initial_capital": INITIAL_CAPITAL,
    "target_vol": TARGET_VOL,
    "tx_cost_bps": TX_COST_BPS,
    "qlike_scores": {k: round(v, 6) for k, v in qlike_scores.items()},
    "dm_tests": dm_results,
    "benchmark_bh": {
        "terminal_wealth": round(bh_wealth[-1], 0),
        "cagr_pct": round(bh_cagr * 100, 3),
        "sharpe": round(bh_sharpe, 4),
        "mdd_pct": round(bh_mdd * 100, 2),
        "mdd_dollars": round(bh_mdd_dollars, 0),
    },
    "vt_portfolios": {
        name: {
            "terminal_wealth": round(r["terminal_wealth"], 0),
            "cagr_pct": round(r["cagr"] * 100, 3),
            "sharpe": round(r["sharpe"], 4),
            "sortino": round(r["sortino"], 4),
            "mdd_pct": round(r["mdd"] * 100, 2),
            "mdd_dollars": round(r["mdd_dollars"], 0),
            "calmar": round(r["calmar"], 4),
            "avg_vt_weight": round(r["avg_vt_weight"], 4),
            "turnover_annual": round(r["turnover_annual"], 4),
            "tx_cost_total": round(r["tx_cost_total"], 0),
        }
        for name, r in results.items()
    },
    "economic_value": econ_value,
    "marginal_value_regression": {
        "qlike_to_sharpe": {
            "slope": round(slope_qs, 6),
            "r_squared": round(r_qs**2, 4),
            "p_value": round(p_qs, 6),
        },
        "qlike_to_terminal_wealth": {
            "slope": round(slope_qt, 0),
            "r_squared": round(r_qt**2, 4),
            "p_value": round(p_qt, 6),
        },
        "qlike_to_cagr": {
            "slope": round(slope_qc, 6),
            "r_squared": round(r_qc**2, 4),
            "p_value": round(p_qc, 6),
        },
    },
    "ewma_sweep": sweep_results,
    "bootstrap_significance": {
        "comparison": f"{best_name} vs {worst_name}",
        "observed_sharpe_diff": round(observed, 4),
        "ci_95": [round(ci_low, 4), round(ci_high, 4)],
        "p_zero": round(p_zero, 4),
        "n_bootstrap": n_boot,
    },
    "key_finding": {
        "best_forecaster": best_vt[0],
        "worst_forecaster": worst_vt[0],
        "sharpe_gap": round(best_vt[1]["sharpe"] - worst_vt[1]["sharpe"], 4),
        "terminal_wealth_gap": round(best_vt[1]["terminal_wealth"] - worst_vt[1]["terminal_wealth"], 0),
        "forecaster_choice_significant": ci_low > 0,
    },
}

import os
results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "storage", "results")
os.makedirs(results_dir, exist_ok=True)
output_path = os.path.join(results_dir, "k375_economic_value.json")
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Saved to: {output_path}")

print("\n" + "=" * 90)
print("K375 COMPLETE")
print("=" * 90)
