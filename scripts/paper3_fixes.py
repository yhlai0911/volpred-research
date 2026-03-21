#!/usr/bin/env python3
"""
Paper 3 Fixes: VIX Threshold Sensitivity + Dual Mechanism Generalization
Codex K77 + Gemini K76

Fix 1: Show TSMOM decomposition holds for VIX targets 8, 10, 12, 15, 18, 20
Fix 2: Run pure VT alpha extraction (K49) on SPY, QQQ, EEM, EFA, GLD

Both raw and orthogonalized TSMOM reported:
- Raw TSMOM: shows alpha absorption (alpha drops when TSMOM added)
- Orthogonalized TSMOM: shows significance of TSMOM loading net of MKT
"""
import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
import statsmodels.api as sm
from datetime import datetime

warnings.filterwarnings("ignore")

# ── Config ──
ASSETS = ["SPY", "QQQ", "EEM", "EFA", "GLD"]
VIX_THRESHOLDS = [8, 10, 12, 15, 18, 20]
START = "2005-01-01"
TSMOM_LOOKBACKS = [21, 63, 252]
ROLLING_WINDOW = 252
NW_LAGS = 10  # Newey-West lags

# ── Data Download ──
print("Downloading data...")
price_data = {}
for t in ASSETS:
    df = yf.download(t, start=START, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    price_data[t] = df["Close"].dropna()
    print(f"  {t}: {len(price_data[t])} obs ({price_data[t].index[0].date()} to {price_data[t].index[-1].date()})")

vix = yf.download("^VIX", start=START, progress=False)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix = vix["Close"].dropna()
print(f"  VIX: {len(vix)} obs")

irx = yf.download("^IRX", start=START, progress=False)
if isinstance(irx.columns, pd.MultiIndex):
    irx.columns = irx.columns.get_level_values(0)
irx = irx["Close"].dropna()
print(f"  IRX: {len(irx)} obs")

# Risk-free rate: IRX is 13-week T-bill annualized %, convert to daily
rf_daily = (irx / 100 / 252).reindex(vix.index).ffill().fillna(0)


def compute_returns(prices):
    return prices.pct_change().dropna()


def compute_tsmom(prices, lookback):
    """TSMOM signal: sign(past return) × today's return."""
    ret = compute_returns(prices)
    past_ret = prices.pct_change(lookback).shift(1)
    signal = np.sign(past_ret)
    tsmom = signal * ret
    return tsmom.dropna()


def compute_tsmom_avg(prices, lookbacks=TSMOM_LOOKBACKS):
    tsmoms = [compute_tsmom(prices, lb) for lb in lookbacks]
    df = pd.concat(tsmoms, axis=1).dropna()
    return df.mean(axis=1)


def build_vt_returns(prices, vix_series, threshold, rf_series, monthly_rebal=True):
    """
    VT strategy: weight_t = target/VIX_t, capped [0,1], lagged, monthly rebalance.
    Returns excess returns (VT - rf).
    """
    ret = compute_returns(prices)
    common = ret.index.intersection(vix_series.index).intersection(rf_series.index)
    ret = ret.loc[common]
    vix_aligned = vix_series.loc[common]
    rf = rf_series.loc[common]

    # Lagged weight: VIX_t determines weight for t+1
    raw_weight = (threshold / vix_aligned).clip(0, 1)
    weight = raw_weight.shift(1)

    if monthly_rebal:
        weight_monthly = weight.copy()
        months = weight.index.to_period("M")
        for m in months.unique():
            mask = months == m
            idx = weight.index[mask]
            if len(idx) > 0:
                weight_monthly.loc[idx] = weight.loc[idx[0]]
        weight = weight_monthly

    weight = weight.dropna()
    common2 = weight.index.intersection(ret.index)

    vt_ret = weight.loc[common2] * ret.loc[common2] + (1 - weight.loc[common2]) * rf.loc[common2]
    bh_ret = ret.loc[common2]

    vt_excess = vt_ret - rf.loc[common2]
    mkt_excess = bh_ret - rf.loc[common2]

    return vt_excess, mkt_excess, weight.loc[common2]


def nw_reg(y, X, max_lags=NW_LAGS):
    """OLS with Newey-West HAC standard errors."""
    X_const = sm.add_constant(X)
    model = sm.OLS(y, X_const).fit(cov_type="HAC", cov_kwds={"maxlags": max_lags})
    return model


def orthogonalize(x, z):
    """Orthogonalize x w.r.t. z: x_orth = x - proj(x|z)."""
    common = x.index.intersection(z.index)
    x, z = x.loc[common], z.loc[common]
    X = sm.add_constant(z)
    return sm.OLS(x, X).fit().resid


def metrics(returns):
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cumret = (1 + returns).cumprod()
    dd = cumret / cumret.cummax() - 1
    mdd = dd.min()
    return {
        "ann_return": round(float(ann_ret), 6),
        "ann_vol": round(float(ann_vol), 6),
        "sharpe": round(float(sharpe), 4),
        "mdd": round(float(mdd), 4),
        "n_obs": int(len(returns)),
    }


def extract_reg(model, var_names):
    """Extract regression results into dict."""
    out = {}
    for v in var_names:
        out[f"{v}_beta"] = round(float(model.params[v]), 8)
        out[f"{v}_t"] = round(float(model.tvalues[v]), 4)
        out[f"{v}_p"] = round(float(model.pvalues[v]), 6)
    out["r2"] = round(float(model.rsquared), 6)
    out["n_obs"] = int(model.nobs)
    return out


# ═══════════════════════════════════════════════════════════════
# Fix 1: VIX Threshold Sensitivity (SPY only)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("FIX 1: VIX Threshold Sensitivity — SPY TSMOM Decomposition")
print("="*70)

spy_prices = price_data["SPY"]
spy_tsmom_avg = compute_tsmom_avg(spy_prices)

fix1_results = {}

for threshold in VIX_THRESHOLDS:
    print(f"\n--- Threshold = {threshold} ---")

    vt_excess, mkt_excess, weights = build_vt_returns(
        spy_prices, vix, threshold, rf_daily, monthly_rebal=True
    )

    # Align all series
    common = vt_excess.index.intersection(mkt_excess.index).intersection(spy_tsmom_avg.index)
    common = common[common >= "2007-01-01"]

    vt_ex = vt_excess.loc[common]
    mkt_ex = mkt_excess.loc[common]
    tsmom_raw = spy_tsmom_avg.loc[common]

    # Orthogonalize TSMOM w.r.t. MKT
    tsmom_orth = orthogonalize(tsmom_raw, mkt_ex)
    common2 = vt_ex.index.intersection(tsmom_orth.index)
    vt_ex = vt_ex.loc[common2]
    mkt_ex = mkt_ex.loc[common2]
    tsmom_raw = tsmom_raw.loc[common2]
    tsmom_orth = tsmom_orth.loc[common2]

    # Model 1: CAPM only
    X1 = pd.DataFrame({"MKT": mkt_ex})
    m1 = nw_reg(vt_ex, X1)

    # Model 2: CAPM + raw TSMOM (shows alpha absorption)
    X2_raw = pd.DataFrame({"MKT": mkt_ex, "TSMOM": tsmom_raw})
    m2_raw = nw_reg(vt_ex, X2_raw)

    # Model 3: CAPM + orthogonalized TSMOM (shows β_TSMOM net of MKT)
    X2_orth = pd.DataFrame({"MKT": mkt_ex, "TSMOM_orth": tsmom_orth})
    m2_orth = nw_reg(vt_ex, X2_orth)

    # Alpha reduction with raw TSMOM
    a1 = m1.params["const"]
    a2 = m2_raw.params["const"]
    alpha_reduction = (1 - a2 / a1) * 100 if a1 != 0 else np.nan

    result = {
        "threshold": threshold,
        "avg_weight": round(float(weights.mean()), 4),
        "vt_metrics": metrics(vt_ex),
        "model1_capm": extract_reg(m1, ["const", "MKT"]),
        "model2_raw_tsmom": extract_reg(m2_raw, ["const", "MKT", "TSMOM"]),
        "model3_orth_tsmom": extract_reg(m2_orth, ["const", "MKT", "TSMOM_orth"]),
        "alpha_reduction_pct": round(float(alpha_reduction), 2) if not np.isnan(alpha_reduction) else None,
    }

    fix1_results[str(threshold)] = result

    print(f"  Avg weight: {weights.mean():.3f}")
    print(f"  M1 CAPM:      α={a1*252:.4f} (t={m1.tvalues['const']:.2f})")
    print(f"  M2 +TSMOM:    α={a2*252:.4f} (t={m2_raw.tvalues['const']:.2f})  β_TSMOM={m2_raw.params['TSMOM']:.4f} (t={m2_raw.tvalues['TSMOM']:.2f})")
    print(f"  M3 +TSMOM_⊥:  α={m2_orth.params['const']*252:.4f} (t={m2_orth.tvalues['const']:.2f})  β_TSMOM⊥={m2_orth.params['TSMOM_orth']:.4f} (t={m2_orth.tvalues['TSMOM_orth']:.2f})")
    print(f"  Alpha reduction (M1→M2): {alpha_reduction:.1f}%  |  ΔR²: {m2_raw.rsquared - m1.rsquared:.4f}")


# ═══════════════════════════════════════════════════════════════
# Fix 2: Dual Mechanism Generalization (5 assets)
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("FIX 2: Dual Mechanism — Cross-Asset TSMOM Decomposition")
print("="*70)

fix2_results = {}

for asset in ASSETS:
    print(f"\n{'='*50}")
    print(f"Asset: {asset}")
    print(f"{'='*50}")

    prices = price_data[asset]
    asset_tsmom_avg = compute_tsmom_avg(prices)

    # VT with 12/VIX
    vt_excess, mkt_excess, weights = build_vt_returns(
        prices, vix, 12, rf_daily, monthly_rebal=True
    )

    # Align
    common = vt_excess.index.intersection(mkt_excess.index).intersection(asset_tsmom_avg.index)
    common = common[common >= "2007-01-01"]

    vt_ex = vt_excess.loc[common]
    mkt_ex = mkt_excess.loc[common]
    tsmom_raw = asset_tsmom_avg.loc[common]

    tsmom_orth = orthogonalize(tsmom_raw, mkt_ex)
    common2 = vt_ex.index.intersection(tsmom_orth.index)
    vt_ex = vt_ex.loc[common2]
    mkt_ex = mkt_ex.loc[common2]
    tsmom_raw = tsmom_raw.loc[common2]
    tsmom_orth = tsmom_orth.loc[common2]

    # ── Regression decomposition ──
    X1 = pd.DataFrame({"MKT": mkt_ex})
    m1 = nw_reg(vt_ex, X1)

    X2_raw = pd.DataFrame({"MKT": mkt_ex, "TSMOM": tsmom_raw})
    m2_raw = nw_reg(vt_ex, X2_raw)

    X2_orth = pd.DataFrame({"MKT": mkt_ex, "TSMOM_orth": tsmom_orth})
    m2_orth = nw_reg(vt_ex, X2_orth)

    a1 = m1.params["const"]
    a2 = m2_raw.params["const"]
    alpha_reduction = (1 - a2 / a1) * 100 if a1 != 0 else np.nan

    # ── TSMOM-hedged VT (rolling 252d regression) ──
    hedged_returns = []
    rolling_betas_raw = []
    rolling_betas_orth = []

    for i in range(ROLLING_WINDOW, len(common2)):
        window_idx = common2[i - ROLLING_WINDOW:i]
        y_win = vt_ex.loc[window_idx]

        # Rolling regression with raw TSMOM
        X_win_raw = pd.DataFrame({
            "MKT": mkt_ex.loc[window_idx],
            "TSMOM": tsmom_raw.loc[window_idx]
        })
        X_win_raw_c = sm.add_constant(X_win_raw)

        # Rolling regression with orth TSMOM (for comparison)
        X_win_orth = pd.DataFrame({
            "MKT": mkt_ex.loc[window_idx],
            "TSMOM_orth": tsmom_orth.loc[window_idx]
        })
        X_win_orth_c = sm.add_constant(X_win_orth)

        try:
            reg_raw = sm.OLS(y_win, X_win_raw_c).fit()
            reg_orth = sm.OLS(y_win, X_win_orth_c).fit()
            bt_raw = reg_raw.params["TSMOM"]
            bt_orth = reg_orth.params["TSMOM_orth"]
            rolling_betas_raw.append(bt_raw)
            rolling_betas_orth.append(bt_orth)

            # Hedged return using raw TSMOM beta
            today = common2[i]
            hedged_ret = vt_ex.loc[today] - bt_raw * tsmom_raw.loc[today]
            hedged_returns.append((today, hedged_ret))
        except Exception:
            continue

    hedged_series = pd.Series(
        [x[1] for x in hedged_returns],
        index=pd.DatetimeIndex([x[0] for x in hedged_returns])
    )

    # ── Metrics comparison ──
    hedged_start = hedged_series.index[0]
    vt_comparable = vt_ex.loc[hedged_start:]
    mkt_comparable = mkt_ex.loc[hedged_start:]

    # Also compute BH returns properly
    bh_ret = compute_returns(prices)
    rf_aligned = rf_daily.reindex(bh_ret.index).ffill().fillna(0)
    bh_excess = bh_ret - rf_aligned
    bh_comparable = bh_excess.loc[hedged_start:].reindex(hedged_series.index).dropna()

    vt_m = metrics(vt_comparable)
    hedged_m = metrics(hedged_series)
    bh_m = metrics(bh_comparable)

    # Sharpe change
    sharpe_change_pct = (hedged_m["sharpe"] - vt_m["sharpe"]) / abs(vt_m["sharpe"]) * 100 if vt_m["sharpe"] != 0 else np.nan

    # TSMOM Sharpe contribution (% of VT Sharpe attributable to TSMOM)
    tsmom_sharpe_contribution = (vt_m["sharpe"] - hedged_m["sharpe"]) / vt_m["sharpe"] * 100 if vt_m["sharpe"] != 0 else np.nan

    # MDD preservation
    bh_mdd_abs = abs(bh_m["mdd"])
    vt_mdd_improvement = bh_mdd_abs - abs(vt_m["mdd"])
    hedged_mdd_improvement = bh_mdd_abs - abs(hedged_m["mdd"])
    mdd_preservation_pct = hedged_mdd_improvement / vt_mdd_improvement * 100 if vt_mdd_improvement > 0.001 else np.nan

    asset_result = {
        "regression_decomposition": {
            "model1_capm": extract_reg(m1, ["const", "MKT"]),
            "model2_raw_tsmom": extract_reg(m2_raw, ["const", "MKT", "TSMOM"]),
            "model3_orth_tsmom": extract_reg(m2_orth, ["const", "MKT", "TSMOM_orth"]),
            "alpha_reduction_pct": round(float(alpha_reduction), 2) if not np.isnan(alpha_reduction) else None,
            "r2_increase_raw": round(float(m2_raw.rsquared - m1.rsquared), 6),
            "r2_increase_orth": round(float(m2_orth.rsquared - m1.rsquared), 6),
        },
        "hedged_vt_analysis": {
            "rolling_beta_tsmom_mean": round(float(np.mean(rolling_betas_raw)), 4),
            "rolling_beta_tsmom_std": round(float(np.std(rolling_betas_raw)), 4),
            "pct_positive_beta": round(float(np.mean(np.array(rolling_betas_raw) > 0) * 100), 1),
            "buy_and_hold": bh_m,
            "vt_12_vix": vt_m,
            "tsmom_hedged_vt": hedged_m,
            "sharpe_change_from_hedging_pct": round(float(sharpe_change_pct), 2) if not np.isnan(sharpe_change_pct) else None,
            "tsmom_sharpe_contribution_pct": round(float(tsmom_sharpe_contribution), 2) if not np.isnan(tsmom_sharpe_contribution) else None,
            "mdd_preservation_pct": round(float(mdd_preservation_pct), 2) if not np.isnan(mdd_preservation_pct) else None,
        },
    }

    fix2_results[asset] = asset_result

    print(f"\n  Regression Decomposition:")
    print(f"    M1 CAPM:      α(ann)={a1*252:.4f} (t={m1.tvalues['const']:.2f})")
    print(f"    M2 +TSMOM:    α(ann)={a2*252:.4f} (t={m2_raw.tvalues['const']:.2f})  β={m2_raw.params['TSMOM']:.4f} (t={m2_raw.tvalues['TSMOM']:.2f})")
    print(f"    α reduction: {alpha_reduction:.1f}%  ΔR²={m2_raw.rsquared - m1.rsquared:.4f}")
    print(f"\n  Hedged VT Analysis (comparable period):")
    print(f"    B&H    Sharpe={bh_m['sharpe']:.3f}  MDD={bh_m['mdd']:.3f}")
    print(f"    VT     Sharpe={vt_m['sharpe']:.3f}  MDD={vt_m['mdd']:.3f}")
    print(f"    Hedged Sharpe={hedged_m['sharpe']:.3f}  MDD={hedged_m['mdd']:.3f}")
    print(f"    TSMOM Sharpe contrib: {tsmom_sharpe_contribution:.1f}%" if not np.isnan(tsmom_sharpe_contribution) else "    TSMOM Sharpe contrib: N/A")
    mps = f"{mdd_preservation_pct:.1f}%" if not np.isnan(mdd_preservation_pct) else "N/A"
    print(f"    MDD preservation: {mps}")


# ═══════════════════════════════════════════════════════════════
# Summary Tables
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*80)
print("SUMMARY TABLE — Fix 1: VIX Threshold Sensitivity (SPY)")
print("="*80)
print(f"{'Thr':>4} | {'AvgW':>5} | {'CAPM α(ann)':>12} {'t':>6} | {'+TSMOM α(ann)':>14} {'t':>6} | {'β_TSMOM':>8} {'t':>7} | {'α↓%':>6} | {'ΔR²':>7}")
print("-"*95)
for th in VIX_THRESHOLDS:
    r = fix1_results[str(th)]
    m1 = r["model1_capm"]
    m2 = r["model2_raw_tsmom"]
    ar = r["alpha_reduction_pct"]
    dr2 = m2["r2"] - m1["r2"]
    a1_ann = m1["const_beta"] * 252
    a2_ann = m2["const_beta"] * 252
    print(f"{th:>4} | {r['avg_weight']:>5.3f} | {a1_ann:>12.4f} {m1['const_t']:>6.2f} | {a2_ann:>14.4f} {m2['const_t']:>6.2f} | {m2['TSMOM_beta']:>8.4f} {m2['TSMOM_t']:>7.2f} | {ar:>5.1f}% | {dr2:>7.4f}")

print("\n" + "="*80)
print("SUMMARY TABLE — Fix 2: Cross-Asset Dual Mechanism (12/VIX)")
print("="*80)
print(f"{'Asset':>5} | {'CAPM α':>8} {'t':>6} | {'+TSMOM α':>9} {'t':>6} | {'α↓%':>6} | {'VT SR':>6} | {'Hdg SR':>7} | {'TSMOM%':>7} | {'MDD%':>6}")
print("-"*90)
for asset in ASSETS:
    r = fix2_results[asset]
    rd = r["regression_decomposition"]
    ha = r["hedged_vt_analysis"]
    m1 = rd["model1_capm"]
    m2 = rd["model2_raw_tsmom"]
    ar = rd["alpha_reduction_pct"]
    ar_str = f"{ar:.1f}%" if ar is not None else "N/A"
    tsc = ha["tsmom_sharpe_contribution_pct"]
    tsc_str = f"{tsc:.1f}%" if tsc is not None else "N/A"
    mp = ha["mdd_preservation_pct"]
    mp_str = f"{mp:.1f}%" if mp is not None else "N/A"
    a1_ann = m1["const_beta"] * 252
    a2_ann = m2["const_beta"] * 252
    print(f"{asset:>5} | {a1_ann:>8.4f} {m1['const_t']:>6.2f} | {a2_ann:>9.4f} {m2['const_t']:>6.2f} | {ar_str:>6} | {ha['vt_12_vix']['sharpe']:>6.3f} | {ha['tsmom_hedged_vt']['sharpe']:>7.3f} | {tsc_str:>7} | {mp_str:>6}")

# Cross-asset summary
alpha_reductions = [fix2_results[a]["regression_decomposition"]["alpha_reduction_pct"] for a in ASSETS if fix2_results[a]["regression_decomposition"]["alpha_reduction_pct"] is not None]
mdd_preservations = [fix2_results[a]["hedged_vt_analysis"]["mdd_preservation_pct"] for a in ASSETS if fix2_results[a]["hedged_vt_analysis"]["mdd_preservation_pct"] is not None]
tsmom_contributions = [fix2_results[a]["hedged_vt_analysis"]["tsmom_sharpe_contribution_pct"] for a in ASSETS if fix2_results[a]["hedged_vt_analysis"]["tsmom_sharpe_contribution_pct"] is not None]
beta_ts_raw = [fix2_results[a]["regression_decomposition"]["model2_raw_tsmom"]["TSMOM_t"] for a in ASSETS]

print(f"\n  Cross-asset summary:")
print(f"    Alpha reduction: mean={np.mean(alpha_reductions):.1f}% (range {np.min(alpha_reductions):.1f}% – {np.max(alpha_reductions):.1f}%)")
print(f"    MDD preservation: mean={np.mean(mdd_preservations):.1f}% (range {np.min(mdd_preservations):.1f}% – {np.max(mdd_preservations):.1f}%)")
print(f"    TSMOM Sharpe contribution: mean={np.mean(tsmom_contributions):.1f}% (range {np.min(tsmom_contributions):.1f}% – {np.max(tsmom_contributions):.1f}%)")
print(f"    β_TSMOM significant (|t|>2): {sum(abs(t)>2 for t in beta_ts_raw)}/{len(beta_ts_raw)}")
print(f"    β_TSMOM t-stats: {', '.join(f'{t:.2f}' for t in beta_ts_raw)}")


# ═══════════════════════════════════════════════════════════════
# Save Results
# ═══════════════════════════════════════════════════════════════
output = {
    "experiment": "Paper 3 Fixes: VIX Threshold Sensitivity + Dual Mechanism Generalization",
    "description": "Fix 1 (Codex K77 + Gemini K76): Show TSMOM decomposition holds across VIX targets 8-20. Fix 2 (Codex K77): Generalize dual mechanism to SPY/QQQ/EEM/EFA/GLD. Both raw and orthogonalized TSMOM reported.",
    "proposed_by": "Codex K77 + Gemini K76",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "assets": ASSETS,
        "vix_thresholds": VIX_THRESHOLDS,
        "start": "2007-01-01",
        "data_start": START,
        "tsmom_lookbacks": TSMOM_LOOKBACKS,
        "rolling_window": ROLLING_WINDOW,
        "nw_lags": NW_LAGS,
        "monthly_rebalance": True,
        "lagged_weights": True,
    },
    "fix1_threshold_sensitivity": {
        "description": "TSMOM decomposition for SPY across VIX thresholds (8,10,12,15,18,20). Both raw TSMOM (alpha absorption) and orth TSMOM (net significance) reported.",
        "results": fix1_results,
        "summary": {
            "all_beta_tsmom_significant_raw": all(
                abs(fix1_results[str(th)]["model2_raw_tsmom"]["TSMOM_t"]) > 2
                for th in VIX_THRESHOLDS
            ),
            "alpha_reduction_range": [
                min(fix1_results[str(th)]["alpha_reduction_pct"] for th in VIX_THRESHOLDS),
                max(fix1_results[str(th)]["alpha_reduction_pct"] for th in VIX_THRESHOLDS),
            ],
            "mean_alpha_reduction": round(np.mean([fix1_results[str(th)]["alpha_reduction_pct"] for th in VIX_THRESHOLDS]), 2),
        },
    },
    "fix2_cross_asset": {
        "description": "Dual mechanism (alpha absorption + MDD preservation) generalized across 5 assets with 12/VIX.",
        "results": fix2_results,
        "summary": {
            "mean_alpha_reduction_pct": round(float(np.mean(alpha_reductions)), 2),
            "mean_mdd_preservation_pct": round(float(np.mean(mdd_preservations)), 2),
            "mean_tsmom_sharpe_contribution_pct": round(float(np.mean(tsmom_contributions)), 2),
            "n_significant_beta_tsmom": sum(abs(t) > 2 for t in beta_ts_raw),
            "n_total_assets": len(ASSETS),
            "alpha_reduction_range": [round(float(np.min(alpha_reductions)), 2), round(float(np.max(alpha_reductions)), 2)],
            "mdd_preservation_range": [round(float(np.min(mdd_preservations)), 2), round(float(np.max(mdd_preservations)), 2)],
        },
    },
}

output_path = "/Users/yhlai0911/Desktop/volpred-research/storage/experiments/paper3_fixes.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
print("\nDone!")
