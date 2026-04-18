"""
K699: Contrarian Tilt Cross-OOS Validation

Motivation:
K698 found contrarian tilt (BH 50/50 ±20% on >1% SPY moves) NET Sharpe 0.878
vs BH 0.843 (+0.035). Best config (2% threshold, ±30% tilt) NET 0.941.
Cross-OOS validation required to confirm robustness (K459/K474/K476 found
53% false positive rate in single-period OOS).

Configs:
  a. Default: threshold 1%, tilt ±20%
  b. Optimized: threshold 2%, tilt ±30%

Cross-OOS periods (5 non-overlapping):
  OOS1: 2008-2009 (GFC)
  OOS2: 2011-2013 (Recovery)
  OOS3: 2015-2017 (Low volatility)
  OOS4: 2020-2021 (COVID)
  OOS5: 2023-2024 (Tariff/rate)

Robustness criteria: Must win ≥4/5 periods on NET Sharpe vs BH 50/50.

Data: SPY, GLD daily via yfinance (2006-01-01 to 2026-03-27)

References:
- Jegadeesh (1990) JF — Evidence of short-term return reversals
- Lehmann (1990) QJE — Fads, martingales, and market efficiency
- DeMiguel, Garlappi, Uppal (2009) RFS — 1/N benchmark hard to beat
- Moreira & Muir (2017) JF — Volatility managed portfolios
- Harvey, Liu & Zhu (2016) RFS — ...and the cross-section of expected returns (t>3.0)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats as sp_stats

# ── Data ─────────────────────────────────────────────────────────────
print("=" * 80)
print("K699: Contrarian Tilt — Cross-OOS Validation")
print("=" * 80)

print("\nDownloading data...")
tickers = {"SPY": "SPY", "GLD": "GLD"}
data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2006-01-01", end="2026-03-28", auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df["Close"].rename(name)

prices = pd.DataFrame(data).dropna()
print(f"Data: {prices.index[0].strftime('%Y-%m-%d')} to "
      f"{prices.index[-1].strftime('%Y-%m-%d')}, {len(prices)} days")

# Returns
ret_spy = prices["SPY"].pct_change().dropna()
ret_gld = prices["GLD"].pct_change().dropna()

# Align
common_idx = ret_spy.index.intersection(ret_gld.index)
ret_spy = ret_spy.loc[common_idx]
ret_gld = ret_gld.loc[common_idx]

print(f"Return series: {len(ret_spy)} observations "
      f"({ret_spy.index[0].strftime('%Y-%m-%d')} to "
      f"{ret_spy.index[-1].strftime('%Y-%m-%d')})")


# ── Helper: compute strategy stats for a period ──────────────────────
def strategy_stats(weights_spy, ret_spy_p, ret_gld_p, tx_bps=5):
    """Compute Sharpe, CAGR, MaxDD, Turnover for a period."""
    weights_gld = 1.0 - weights_spy
    port_ret = weights_spy * ret_spy_p + weights_gld * ret_gld_p

    # Gross Sharpe
    if port_ret.std() == 0:
        sharpe_gross = 0.0
    else:
        sharpe_gross = port_ret.mean() / port_ret.std() * np.sqrt(252)

    # Turnover
    turnover_daily = weights_spy.diff().abs()
    turnover_ann = turnover_daily.mean() * 252

    # Net returns
    tx_cost = tx_bps / 10000.0
    daily_tx = turnover_daily * tx_cost
    net_ret = port_ret - daily_tx

    # Net Sharpe
    if net_ret.std() == 0:
        sharpe_net = 0.0
    else:
        sharpe_net = net_ret.mean() / net_ret.std() * np.sqrt(252)

    # CAGR (net)
    cumret = (1 + net_ret).cumprod()
    years = len(net_ret) / 252
    if years > 0 and cumret.iloc[-1] > 0:
        cagr_net = cumret.iloc[-1] ** (1 / years) - 1
    else:
        cagr_net = 0.0

    # Max Drawdown (net)
    running_max = cumret.cummax()
    drawdown = (cumret - running_max) / running_max
    max_dd_net = drawdown.min()

    # Annualized volatility
    ann_vol = port_ret.std() * np.sqrt(252)

    return {
        "sharpe_gross": round(float(sharpe_gross), 4),
        "sharpe_net": round(float(sharpe_net), 4),
        "cagr_net": round(float(cagr_net), 4),
        "max_dd_net": round(float(max_dd_net), 4),
        "ann_vol": round(float(ann_vol), 4),
        "turnover_ann": round(float(turnover_ann), 2),
        "n_days": len(net_ret),
        "port_ret_series": net_ret,  # keep for DM test
        "gross_ret_series": port_ret,
    }


# ── Contrarian tilt weight construction ──────────────────────────────
def build_contrarian_weights(ret_spy_full, threshold, tilt):
    """
    Build contrarian tilt weights for SPY.
    Base: 0.5 (BH 50/50).
    After SPY daily return < -threshold: next day weight = 0.5 + tilt
    After SPY daily return > +threshold: next day weight = 0.5 - tilt
    ALL LAGGED by 1 day (shift(1)).
    """
    ret_lag1 = ret_spy_full.shift(1)  # yesterday's return
    w = pd.Series(0.5, index=ret_spy_full.index)
    w[ret_lag1 < -threshold] = 0.5 + tilt
    w[ret_lag1 > threshold] = 0.5 - tilt
    w.iloc[0] = 0.5  # no signal on first day
    return w


# ── Diebold-Mariano test ─────────────────────────────────────────────
def dm_test(ret1, ret2, h=1):
    """
    Diebold-Mariano test comparing two return series.
    H0: both strategies have equal expected returns.
    Uses loss = -return (so higher return = lower loss).
    Returns t-stat and p-value.
    """
    # Ensure numpy arrays, drop NaN
    r1 = np.asarray(ret1, dtype=float)
    r2 = np.asarray(ret2, dtype=float)
    valid = ~(np.isnan(r1) | np.isnan(r2))
    r1 = r1[valid]
    r2 = r2[valid]

    d = r1 - r2  # loss differential (positive = strategy 1 better)
    n = len(d)
    if n < 10:
        return 0.0, 1.0

    d_mean = d.mean()
    # Newey-West HAC variance with automatic lag selection
    max_lag = max(1, int(np.floor(n ** (1/3))))
    gamma_0 = np.var(d, ddof=1)
    for k in range(1, max_lag + 1):
        weight = 1.0 - k / (max_lag + 1)  # Bartlett kernel
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_0 += 2 * weight * gamma_k

    if gamma_0 <= 0:
        return 0.0, 1.0

    dm_stat = d_mean / np.sqrt(gamma_0 / n)
    p_value = 2 * (1 - sp_stats.norm.cdf(abs(float(dm_stat))))
    return round(float(dm_stat), 4), round(float(p_value), 4)


# ── Cross-OOS periods ────────────────────────────────────────────────
oos_periods = [
    ("OOS1: 2008-2009 (GFC)",      "2008-01-01", "2010-01-01"),
    ("OOS2: 2011-2013 (Recovery)",  "2011-01-01", "2014-01-01"),
    ("OOS3: 2015-2017 (Low Vol)",   "2015-01-01", "2018-01-01"),
    ("OOS4: 2020-2021 (COVID)",     "2020-01-01", "2022-01-01"),
    ("OOS5: 2023-2024 (Tariff)",    "2023-01-01", "2025-01-01"),
]

# Configs to test
configs = [
    {"name": "Default (1%, ±20%)", "threshold": 0.01, "tilt": 0.20},
    {"name": "Optimized (2%, ±30%)", "threshold": 0.02, "tilt": 0.30},
]


# ── Run Cross-OOS ────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("CROSS-OOS VALIDATION")
print("=" * 80)

all_results = {}

for cfg in configs:
    cfg_name = cfg["name"]
    threshold = cfg["threshold"]
    tilt = cfg["tilt"]

    print(f"\n{'─' * 70}")
    print(f"Config: {cfg_name} (threshold={threshold}, tilt=±{tilt:.0%})")
    print(f"{'─' * 70}")

    # Build weights on FULL series (signal uses lagged returns, no lookahead)
    w_contra = build_contrarian_weights(ret_spy, threshold, tilt)
    w_bh = pd.Series(0.5, index=ret_spy.index)

    period_results = []
    n_wins = 0
    n_significant_wins = 0

    print(f"\n  {'Period':<30} {'N':>5} {'BH_SR':>7} {'CT_SR':>7} {'Delta':>7} {'DM_t':>7} {'DM_p':>7} {'Win':>4}")
    print("  " + "-" * 85)

    for period_name, start, end in oos_periods:
        pmask = (ret_spy.index >= start) & (ret_spy.index < end)

        if pmask.sum() < 30:
            print(f"  {period_name:<30} — insufficient data ({pmask.sum()} days)")
            continue

        # Slice to period
        ret_spy_p = ret_spy[pmask]
        ret_gld_p = ret_gld[pmask]
        w_contra_p = w_contra[pmask]
        w_bh_p = w_bh[pmask]

        # Stats
        stats_bh = strategy_stats(w_bh_p, ret_spy_p, ret_gld_p, tx_bps=5)
        stats_ct = strategy_stats(w_contra_p, ret_spy_p, ret_gld_p, tx_bps=5)

        # DM test on NET returns
        dm_t, dm_p = dm_test(
            stats_ct["port_ret_series"].values,
            stats_bh["port_ret_series"].values
        )

        delta = stats_ct["sharpe_net"] - stats_bh["sharpe_net"]
        win = delta > 0
        sig_win = win and dm_p < 0.10

        if win:
            n_wins += 1
        if sig_win:
            n_significant_wins += 1

        win_str = "Y" if win else "N"
        if sig_win:
            win_str += "*"

        print(f"  {period_name:<30} {stats_ct['n_days']:>5} "
              f"{stats_bh['sharpe_net']:>7.4f} {stats_ct['sharpe_net']:>7.4f} "
              f"{delta:>+7.4f} {dm_t:>7.4f} {dm_p:>7.4f} {win_str:>4}")

        period_results.append({
            "period": period_name,
            "start": start,
            "end": end,
            "n_days": stats_ct["n_days"],
            "bh_sharpe_net": stats_bh["sharpe_net"],
            "bh_cagr_net": stats_bh["cagr_net"],
            "bh_max_dd_net": stats_bh["max_dd_net"],
            "ct_sharpe_net": stats_ct["sharpe_net"],
            "ct_cagr_net": stats_ct["cagr_net"],
            "ct_max_dd_net": stats_ct["max_dd_net"],
            "ct_ann_vol": stats_ct["ann_vol"],
            "ct_turnover_ann": stats_ct["turnover_ann"],
            "delta_sharpe": round(delta, 4),
            "dm_tstat": dm_t,
            "dm_pvalue": dm_p,
            "win": win,
            "significant_at_10pct": sig_win,
        })

    n_periods = len(period_results)
    passes = n_wins >= 4

    print(f"\n  Wins: {n_wins}/{n_periods} (need ≥4/5)")
    print(f"  Significant wins (p<0.10): {n_significant_wins}/{n_periods}")
    print(f"  PASS: {'YES' if passes else 'NO'}")

    # Aggregate stats across all OOS periods
    all_deltas = [r["delta_sharpe"] for r in period_results]
    mean_delta = np.mean(all_deltas)
    std_delta = np.std(all_deltas, ddof=1) if len(all_deltas) > 1 else 0

    # t-test on deltas: H0: mean delta = 0
    if std_delta > 0 and len(all_deltas) > 1:
        t_delta = mean_delta / (std_delta / np.sqrt(len(all_deltas)))
        p_delta = 2 * (1 - sp_stats.t.cdf(abs(t_delta), df=len(all_deltas) - 1))
    else:
        t_delta = 0.0
        p_delta = 1.0

    print(f"\n  Mean delta Sharpe: {mean_delta:+.4f} (std={std_delta:.4f})")
    print(f"  t-test on deltas: t={t_delta:.3f}, p={p_delta:.4f}")
    print(f"  Harvey (2016) threshold t>3.0: {'PASS' if abs(t_delta) > 3.0 else 'FAIL'}")

    all_results[cfg_name] = {
        "config": {
            "threshold": threshold,
            "tilt": tilt,
            "tx_bps": 5,
        },
        "periods": period_results,
        "summary": {
            "n_periods": n_periods,
            "n_wins": n_wins,
            "n_significant_wins_10pct": n_significant_wins,
            "passes_4_of_5": passes,
            "mean_delta_sharpe": round(float(mean_delta), 4),
            "std_delta_sharpe": round(float(std_delta), 4),
            "tstat_deltas": round(float(t_delta), 3),
            "pvalue_deltas": round(float(p_delta), 4),
            "harvey_t3_pass": abs(t_delta) > 3.0,
        },
    }


# ── Full-period confirmation ─────────────────────────────────────────
print("\n" + "=" * 80)
print("FULL-PERIOD CONFIRMATION (2007-2026)")
print("=" * 80)

bt_start = "2007-01-01"
bt_mask = ret_spy.index >= bt_start
ret_spy_bt = ret_spy[bt_mask]
ret_gld_bt = ret_gld[bt_mask]
w_bh_bt = pd.Series(0.5, index=ret_spy_bt.index)

full_period_results = {}
for cfg in configs:
    w_ct = build_contrarian_weights(ret_spy, cfg["threshold"], cfg["tilt"])
    w_ct_bt = w_ct[bt_mask]

    stats_bh = strategy_stats(w_bh_bt, ret_spy_bt, ret_gld_bt, tx_bps=5)
    stats_ct = strategy_stats(w_ct_bt, ret_spy_bt, ret_gld_bt, tx_bps=5)

    dm_t, dm_p = dm_test(
        stats_ct["port_ret_series"].values,
        stats_bh["port_ret_series"].values
    )

    delta = stats_ct["sharpe_net"] - stats_bh["sharpe_net"]

    # Count trigger days
    ret_lag1 = ret_spy.shift(1)
    n_down = (ret_lag1[bt_mask] < -cfg["threshold"]).sum()
    n_up = (ret_lag1[bt_mask] > cfg["threshold"]).sum()
    n_total = bt_mask.sum()
    pct_active = (n_down + n_up) / n_total * 100

    print(f"\n  {cfg['name']}:")
    print(f"    BH 50/50  NET Sharpe: {stats_bh['sharpe_net']:.4f}")
    print(f"    Contrarian NET Sharpe: {stats_ct['sharpe_net']:.4f} (delta={delta:+.4f})")
    print(f"    DM test: t={dm_t:.4f}, p={dm_p:.4f}")
    print(f"    CAGR (net): {stats_ct['cagr_net']:.4f}, MaxDD: {stats_ct['max_dd_net']:.4f}")
    print(f"    Turnover: {stats_ct['turnover_ann']:.1f}x/yr, Active: {pct_active:.1f}%")
    print(f"    Trigger days: {n_down} down, {n_up} up (of {n_total})")

    full_period_results[cfg["name"]] = {
        "bh_sharpe_net": stats_bh["sharpe_net"],
        "ct_sharpe_net": stats_ct["sharpe_net"],
        "delta_sharpe": round(delta, 4),
        "dm_tstat": dm_t,
        "dm_pvalue": dm_p,
        "ct_cagr_net": stats_ct["cagr_net"],
        "ct_max_dd_net": stats_ct["max_dd_net"],
        "ct_ann_vol": stats_ct["ann_vol"],
        "ct_turnover_ann": stats_ct["turnover_ann"],
        "n_trigger_down": int(n_down),
        "n_trigger_up": int(n_up),
        "pct_active": round(pct_active, 1),
        "n_days": int(n_total),
    }


# ── Autocorrelation by OOS period ────────────────────────────────────
print("\n" + "=" * 80)
print("AUTOCORRELATION DIAGNOSTIC BY PERIOD")
print("=" * 80)

print(f"\n  {'Period':<30} {'ACF(1)':>8} {'t-stat':>8} {'p-val':>8} {'Neg?':>5}")
print("  " + "-" * 65)

acf_by_period = []
for period_name, start, end in oos_periods:
    pmask = (ret_spy.index >= start) & (ret_spy.index < end)
    ret_p = ret_spy[pmask]

    acf1 = ret_p.autocorr(lag=1)
    n_p = len(ret_p)
    se_acf = 1.0 / np.sqrt(n_p)
    t_acf = acf1 / se_acf
    p_acf = 2 * (1 - sp_stats.norm.cdf(abs(t_acf)))
    is_neg = acf1 < 0

    print(f"  {period_name:<30} {acf1:>8.4f} {t_acf:>8.2f} {p_acf:>8.4f} {'Y' if is_neg else 'N':>5}")

    acf_by_period.append({
        "period": period_name,
        "acf_lag1": round(float(acf1), 4),
        "tstat": round(float(t_acf), 2),
        "pvalue": round(float(p_acf), 4),
        "is_negative": is_neg,
    })

# Check correlation between ACF and delta Sharpe
for cfg_name, cfg_results in all_results.items():
    acf_vals = [a["acf_lag1"] for a in acf_by_period]
    delta_vals = [r["delta_sharpe"] for r in cfg_results["periods"]]
    if len(acf_vals) == len(delta_vals) and len(acf_vals) > 2:
        corr, p_corr = sp_stats.pearsonr(acf_vals, delta_vals)
        print(f"\n  Correlation(ACF_lag1, delta_Sharpe) for {cfg_name}: "
              f"r={corr:.3f}, p={p_corr:.4f}")
        all_results[cfg_name]["acf_delta_correlation"] = {
            "pearson_r": round(float(corr), 4),
            "pvalue": round(float(p_corr), 4),
        }


# ── Final Verdict ─────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("FINAL VERDICT")
print("=" * 80)

for cfg_name, res in all_results.items():
    s = res["summary"]
    print(f"\n  {cfg_name}:")
    print(f"    Cross-OOS wins: {s['n_wins']}/{s['n_periods']} "
          f"(need ≥4) → {'PASS' if s['passes_4_of_5'] else 'FAIL'}")
    print(f"    Mean delta Sharpe: {s['mean_delta_sharpe']:+.4f}")
    print(f"    t-test on deltas: t={s['tstat_deltas']:.3f}, p={s['pvalue_deltas']:.4f}")
    print(f"    Harvey t>3.0: {'PASS' if s['harvey_t3_pass'] else 'FAIL'}")

    if s['passes_4_of_5'] and s['harvey_t3_pass']:
        verdict = "ROBUST — passes both criteria"
    elif s['passes_4_of_5']:
        verdict = "MARGINAL — wins ≥4/5 but fails Harvey t>3.0 threshold"
    elif s['harvey_t3_pass']:
        verdict = "INCONSISTENT — passes Harvey but not ≥4/5 wins"
    else:
        verdict = "REJECTED — fails both criteria"

    print(f"    Verdict: {verdict}")
    all_results[cfg_name]["verdict"] = verdict


# ── Overall conclusion ────────────────────────────────────────────────
default_res = all_results["Default (1%, ±20%)"]
optimized_res = all_results["Optimized (2%, ±30%)"]

default_robust = default_res["summary"]["passes_4_of_5"]
optimized_robust = optimized_res["summary"]["passes_4_of_5"]

if default_robust and optimized_robust:
    conclusion = ("Both configs pass cross-OOS validation (≥4/5 wins). "
                  "Contrarian tilt is robust across market regimes.")
elif default_robust:
    conclusion = ("Default config (1%, ±20%) passes but optimized (2%, ±30%) fails. "
                  "The optimized config may be overfitted to certain regimes.")
elif optimized_robust:
    conclusion = ("Optimized config (2%, ±30%) passes but default (1%, ±20%) fails. "
                  "Higher threshold with stronger tilt is more robust.")
else:
    conclusion = ("Neither config passes cross-OOS validation (≥4/5 wins). "
                  "Contrarian tilt alpha is regime-dependent and not robust. "
                  "K698's full-period result may reflect in-sample overfitting.")

# Add Harvey threshold assessment
default_harvey = default_res["summary"]["harvey_t3_pass"]
optimized_harvey = optimized_res["summary"]["harvey_t3_pass"]

if not default_harvey and not optimized_harvey:
    conclusion += (" Both fail Harvey (2016) t>3.0 threshold, suggesting the "
                   "alpha, if any, is not statistically significant by modern standards.")

print(f"\n  OVERALL CONCLUSION:")
print(f"  {conclusion}")


# ── Save Results ──────────────────────────────────────────────────────
# Remove non-serializable series
for cfg_name in all_results:
    for period in all_results[cfg_name]["periods"]:
        period.pop("port_ret_series", None)
        period.pop("gross_ret_series", None)
        # Convert numpy bools to Python bools
        for k, v in period.items():
            if isinstance(v, (np.bool_, np.integer)):
                period[k] = bool(v) if isinstance(v, np.bool_) else int(v)

# Clean full_period_results too
for cfg_name in full_period_results:
    full_period_results[cfg_name].pop("port_ret_series", None)
    full_period_results[cfg_name].pop("gross_ret_series", None)

results = {
    "experiment_id": "K699",
    "title": "Contrarian Tilt — Cross-OOS Validation",
    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "data_source": "yfinance (SPY, GLD)",
    "data_period": f"{ret_spy.index[0].strftime('%Y-%m-%d')} to "
                   f"{ret_spy.index[-1].strftime('%Y-%m-%d')}",
    "n_observations_total": len(ret_spy),
    "tx_cost_bps": 5,
    "motivation": ("K698 found contrarian tilt (BH 50/50 ±20% on >1% SPY moves) "
                   "NET Sharpe 0.878 vs BH 0.843 (+0.035). Best config (2% threshold, "
                   "±30% tilt) NET 0.941. Cross-OOS validation required."),
    "oos_periods": [
        {"name": name, "start": start, "end": end}
        for name, start, end in oos_periods
    ],
    "robustness_criteria": "Must win ≥4/5 OOS periods on NET Sharpe vs BH 50/50",
    "cross_oos_results": all_results,
    "full_period_confirmation": full_period_results,
    "acf_by_period": acf_by_period,
    "conclusion": conclusion,
    "references": [
        "Jegadeesh (1990) JF — Evidence of short-term return reversals",
        "Lehmann (1990) QJE — Fads, martingales, and market efficiency",
        "DeMiguel, Garlappi, Uppal (2009) RFS — 1/N benchmark hard to beat",
        "Moreira & Muir (2017) JF — Volatility managed portfolios",
        "Harvey, Liu & Zhu (2016) RFS — t>3.0 threshold for new factors",
    ],
}

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

out_path = "experiments/k699_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)

print(f"\nResults saved to {out_path}")
print("Done.")
