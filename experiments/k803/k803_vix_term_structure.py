"""
K803: VIX Term Structure Spread as VT Overlay Signal
=====================================================
Purpose: Test whether VIX3M/VIX ratio (term structure) improves 12/VIX VT strategy
as an orthogonal overlay signal.

Context:
- K801 E037: Only test VIX-derived overlays ORTHOGONAL to VIX level
- K731: Term structure NULL for GARCH forecasting (1-step)
- T13: VT+TS Reduce Sharpe 0.94 vs 12/VIX 0.88 (DM t=0.44, NS) — older proxy test
- VIX3M/VIX < 1 = backwardation (stress); > 1 = contango (normal)

Strategies tested:
  - Baseline: 12/VIX (standard VT, cap=1.5, floor=0)
  - Contango Guard: 12/VIX, but if VIX3M/VIX < 0.95 → weight *= 0.50
  - Contango Smooth: 12/VIX × min(1, VIX3M/VIX) — smooth reduction in backwardation
  - Contango Binary: 12/VIX, but if VIX3M/VIX < 0.90 → weight=0 for 5 days

Data: SPY, VIX (^VIX), VIX3M (^VIX3M) via yfinance
Period: Full (from VIX3M availability), OOS: 2023-2024
signal.shift(1) — STRICTLY lag=1 day

References:
- Chang (2016): VIX backwardation predicts positive monthly returns
- T13 (internal): Daily TS signal NS (DM t=0.44)
- K731 (internal): Term structure NULL for GARCH-X 1-step

[提出: User, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

# ── Parameters ──────────────────────────────────────────────────────────────
VIX_SCALE = 12.0
WEIGHT_CAP = 1.5
WEIGHT_FLOOR = 0.0
TX_COST = 0.001          # 10bp one-way per unit weight change
BACKWARDATION_GUARD = 0.95   # Contango Guard threshold
BACKWARDATION_SMOOTH = 1.0   # Smooth uses ratio directly
BACKWARDATION_BINARY = 0.90  # Binary cash threshold
BINARY_CASH_DAYS = 5         # Cash hold duration after trigger
OOS_START = "2023-01-01"
FULL_START = "2008-01-01"    # VIX3M availability starts ~2008


def download_data():
    """Download SPY, VIX, VIX3M data."""
    print("Downloading data...")
    spy = yf.download("SPY", start=FULL_START, auto_adjust=True, progress=False)
    vix = yf.download("^VIX", start=FULL_START, auto_adjust=True, progress=False)
    vix3m = yf.download("^VIX3M", start=FULL_START, auto_adjust=True, progress=False)

    spy_ret = spy["Close"].pct_change().squeeze()
    vix_close = vix["Close"].squeeze()
    vix3m_close = vix3m["Close"].squeeze()

    # Align all series
    df = pd.DataFrame({
        "spy_ret": spy_ret,
        "vix": vix_close,
        "vix3m": vix3m_close
    }).dropna()

    print(f"Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    print(f"VIX3M availability starts: {df.index[0].date()}")
    print(f"VIX range: [{df['vix'].min():.1f}, {df['vix'].max():.1f}]")
    print(f"VIX3M range: [{df['vix3m'].min():.1f}, {df['vix3m'].max():.1f}]")

    # Compute term structure ratio
    df["ts_ratio"] = df["vix3m"] / df["vix"]  # >1 = contango, <1 = backwardation
    print(f"\nTS ratio stats:")
    print(f"  Mean: {df['ts_ratio'].mean():.4f}")
    print(f"  Backwardation (<1): {(df['ts_ratio'] < 1).mean():.1%} of days")
    print(f"  Strong backwardation (<0.95): {(df['ts_ratio'] < BACKWARDATION_GUARD).mean():.1%}")
    print(f"  Very strong back (<0.90): {(df['ts_ratio'] < BACKWARDATION_BINARY).mean():.1%}")

    return df


def compute_weights(df):
    """Compute all strategy weights with STRICT lag=1."""
    # === BASELINE: 12/VIX ===
    base_w = (VIX_SCALE / df["vix"]).clip(WEIGHT_FLOOR, WEIGHT_CAP)
    # LAG=1: use yesterday's VIX signal for today's return
    df["w_baseline"] = base_w.shift(1)

    # === Contango Guard: reduce to 50% when VIX3M/VIX < 0.95 ===
    guard_multiplier = np.where(df["ts_ratio"] < BACKWARDATION_GUARD, 0.5, 1.0)
    guard_w = base_w * guard_multiplier
    df["w_guard"] = pd.Series(guard_w, index=df.index).clip(WEIGHT_FLOOR, WEIGHT_CAP).shift(1)

    # === Contango Smooth: weight *= min(1, VIX3M/VIX) ===
    smooth_multiplier = df["ts_ratio"].clip(upper=1.0)  # Only reduce, never amplify
    smooth_w = base_w * smooth_multiplier
    df["w_smooth"] = smooth_w.clip(WEIGHT_FLOOR, WEIGHT_CAP).shift(1)

    # === Contango Binary: cash for 5 days when VIX3M/VIX < 0.90 ===
    trigger = (df["ts_ratio"] < BACKWARDATION_BINARY).astype(int)
    # Expand trigger: any trigger in next 5 days → cash today
    # Forward-looking version is NOT allowed (lookahead).
    # Correct: trigger today → cash for next 5 days (including today)
    # Implement: rolling max over past 5 days of trigger
    in_cash = trigger.rolling(BINARY_CASH_DAYS, min_periods=1).max()
    binary_multiplier = 1 - in_cash  # 0 = cash, 1 = invest
    binary_w = base_w * binary_multiplier
    df["w_binary"] = binary_w.clip(WEIGHT_FLOOR, WEIGHT_CAP).shift(1)

    return df


def apply_tx_cost(weights_series, cost=TX_COST):
    """
    Apply transaction costs based on daily weight changes.
    The first valid weight incurs full entry cost (fillna with 0 captures this:
    diff of [NaN, w0] → NaN, then fillna(0) → 0, but first actual position
    is treated as entering from 0 weight via the shift(1) already applied).
    Note: since weights are computed via shift(1), the first non-NaN weight
    after dropna() is the first live day; diff() there gives w_0 - NaN = NaN → 0.
    We explicitly charge the initial position entry to be conservative.
    """
    w = weights_series.copy()
    # First live position entered from 0
    first_valid_idx = w.first_valid_index()
    delta_w = w.diff().abs()
    if first_valid_idx is not None:
        delta_w.iloc[w.index.get_loc(first_valid_idx)] = abs(w.iloc[w.index.get_loc(first_valid_idx)])
    delta_w = delta_w.fillna(0)
    tx = delta_w * cost
    return tx


def compute_strategy_returns(df, w_col):
    """Compute net returns for a strategy."""
    # Weight × SPY return (both already lag-correct after shift(1))
    gross_ret = df[w_col] * df["spy_ret"]
    tx = apply_tx_cost(df[w_col])
    net_ret = gross_ret - tx
    return net_ret.dropna()


def compute_metrics(returns, label=""):
    """Compute Sharpe, CAGR, MDD, and annualized vol."""
    if len(returns) == 0:
        return {}
    ann_factor = 252
    sharpe = returns.mean() / returns.std() * np.sqrt(ann_factor)
    cagr = (1 + returns).prod() ** (ann_factor / len(returns)) - 1
    cum = (1 + returns).cumprod()
    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    mdd = drawdown.min()
    vol = returns.std() * np.sqrt(ann_factor)
    return {
        "label": label,
        "sharpe": round(float(sharpe), 4),
        "cagr": round(float(cagr), 4),
        "mdd": round(float(mdd), 4),
        "ann_vol": round(float(vol), 4),
        "n_days": len(returns)
    }


def hac_return_comparison(ret1, ret2):
    """
    HAC (Newey-West) t-test on mean daily return differential.
    H0: E[ret2 - ret1] = 0 (strategies have equal mean return).
    This is the correct framework for strategy comparison per Harvey (2016).
    Note: NOT a proper Diebold-Mariano forecast-loss test.
    The Harvey (2016) t>3.0 threshold applies to this kind of return-spread test.

    Returns: t_stat (positive = ret2 > ret1 = strategy 2 better), p_val
    """
    d = ret2 - ret1  # daily return spread; positive = strategy 2 better
    n = len(d)
    d_mean = d.mean()
    # Newey-West HAC variance (Bartlett kernel, lags ~ n^(1/3))
    nw_lags = int(np.ceil(n ** (1 / 3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = gamma_0
    for lag in range(1, nw_lags + 1):
        cov_mat = np.cov(d.values[lag:], d.values[:-lag], ddof=1)
        gamma_l = cov_mat[0, 1]
        gamma_sum += 2 * (1 - lag / (nw_lags + 1)) * gamma_l
    # Guard against negative variance from rounding
    gamma_sum = max(gamma_sum, 1e-16)
    se = np.sqrt(gamma_sum / n)
    if se == 0:
        return 0.0, 1.0
    t_stat = d_mean / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


def main():
    print("=" * 60)
    print("K803: VIX Term Structure Spread as VT Overlay Signal")
    print("=" * 60)

    # Step 1: Download data
    df = download_data()

    # Step 2: Compute weights
    df = compute_weights(df)

    # Step 3: Compute returns (drop NaN from shift)
    df = df.dropna()
    strategies = ["w_baseline", "w_guard", "w_smooth", "w_binary"]
    labels = ["12/VIX (Baseline)", "Contango Guard (0.95)", "Contango Smooth", "Contango Binary (0.90)"]

    returns = {}
    for col, lbl in zip(strategies, labels):
        returns[col] = compute_strategy_returns(df, col)

    # Step 4: Full period metrics
    print("\n── FULL PERIOD METRICS ──")
    full_metrics = []
    for col, lbl in zip(strategies, labels):
        m = compute_metrics(returns[col], lbl)
        full_metrics.append(m)
        print(f"  {lbl:<30} Sharpe={m['sharpe']:.4f}  CAGR={m['cagr']:.2%}  MDD={m['mdd']:.2%}  N={m['n_days']}")

    # Step 5: OOS period metrics
    oos_mask = df.index >= OOS_START
    print(f"\n── OOS PERIOD ({OOS_START} to end) ──")
    oos_metrics = []
    for col, lbl in zip(strategies, labels):
        oos_ret = returns[col][returns[col].index >= OOS_START]
        m = compute_metrics(oos_ret, lbl + " [OOS]")
        oos_metrics.append(m)
        print(f"  {lbl:<30} Sharpe={m['sharpe']:.4f}  CAGR={m['cagr']:.2%}  MDD={m['mdd']:.2%}  N={m['n_days']}")

    # Step 6: HAC return-comparison tests (all vs baseline, Harvey t>3.0)
    print("\n── HAC RETURN COMPARISON vs Baseline (Harvey t>3.0 threshold) ──")
    print("   (NW-HAC t-test on daily return spread; positive t = strategy better)")
    dm_results = []
    baseline_ret = returns["w_baseline"]
    for col, lbl in zip(strategies[1:], labels[1:]):
        strat_ret = returns[col]
        # Align
        common_idx = baseline_ret.index.intersection(strat_ret.index)
        t_stat, p_val = hac_return_comparison(
            baseline_ret[common_idx], strat_ret[common_idx]
        )
        significant = abs(t_stat) > 3.0
        verdict = "SIGNIFICANT (t>3)" if significant else "NS"
        dm_results.append({
            "strategy": lbl,
            "t_stat": round(t_stat, 4),
            "p_value": round(p_val, 4),
            "significant": significant,
            "test": "HAC NW return-spread t-test (Harvey 2016 t>3.0)"
        })
        print(f"  {lbl:<30} t={t_stat:+.4f}  p={p_val:.4f}  [{verdict}]")
        print(f"    (negative t = strategy worse than baseline)")

    # Step 7: Term structure summary stats
    print("\n── TERM STRUCTURE DESCRIPTIVES ──")
    back_mask = df["ts_ratio"] < 1.0
    cont_mask = df["ts_ratio"] >= 1.0
    print(f"  Backwardation days: {back_mask.sum()} ({back_mask.mean():.1%})")
    print(f"  Contango days: {cont_mask.sum()} ({cont_mask.mean():.1%})")
    if back_mask.sum() > 0:
        print(f"  Avg SPY return in backwardation: {df.loc[back_mask, 'spy_ret'].mean():.4f}")
        print(f"  Avg SPY return in contango: {df.loc[cont_mask, 'spy_ret'].mean():.4f}")
        print(f"  Avg |SPY return| in backwardation: {df.loc[back_mask, 'spy_ret'].abs().mean():.4f}")
        print(f"  Avg |SPY return| in contango: {df.loc[cont_mask, 'spy_ret'].abs().mean():.4f}")

    # Step 8: Backwardation OOS analysis
    oos_df = df[df.index >= OOS_START]
    back_oos = oos_df["ts_ratio"] < 1.0
    print(f"\n  OOS Backwardation days: {back_oos.sum()} ({back_oos.mean():.1%})")

    # Step 9: Save results
    results = {
        "experiment_id": "K803",
        "title": "VIX Term Structure Spread as VT Overlay Signal",
        "data_source": "yfinance: SPY, ^VIX, ^VIX3M",
        "data_period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "n_days": len(df),
        "oos_start": OOS_START,
        "parameters": {
            "vix_scale": VIX_SCALE,
            "weight_cap": WEIGHT_CAP,
            "weight_floor": WEIGHT_FLOOR,
            "tx_cost": TX_COST,
            "backwardation_guard_threshold": BACKWARDATION_GUARD,
            "backwardation_binary_threshold": BACKWARDATION_BINARY,
            "binary_cash_days": BINARY_CASH_DAYS,
            "lag": 1
        },
        "full_period_metrics": full_metrics,
        "oos_metrics": oos_metrics,
        "dm_tests_vs_baseline": dm_results,
        "term_structure_stats": {
            "backwardation_fraction": float(back_mask.mean()),
            "backwardation_days": int(back_mask.sum()),
            "mean_spy_ret_backwardation": float(df.loc[back_mask, "spy_ret"].mean()),
            "mean_spy_ret_contango": float(df.loc[cont_mask, "spy_ret"].mean()),
            "mean_abs_spy_ret_backwardation": float(df.loc[back_mask, "spy_ret"].abs().mean()),
            "mean_abs_spy_ret_contango": float(df.loc[cont_mask, "spy_ret"].abs().mean()),
        },
        "conclusion": "",  # will fill after seeing results
        "references": [
            "Chang (2016): VIX backwardation predicts monthly SPY returns",
            "K731 (internal): VIX TS NULL for GARCH-X 1-step forecast",
            "T13 (internal): Daily TS signal NS on VT (DM t=0.44)",
            "E037 (internal): VIX level absorbs event overlays — orthogonality test"
        ]
    }

    # Determine conclusion from results
    guard_dm = next(r for r in dm_results if "Guard" in r["strategy"])
    smooth_dm = next(r for r in dm_results if "Smooth" in r["strategy"])
    binary_dm = next(r for r in dm_results if "Binary" in r["strategy"])

    # Compare Sharpe
    base_sharpe = full_metrics[0]["sharpe"]
    guard_sharpe = full_metrics[1]["sharpe"]
    smooth_sharpe = full_metrics[2]["sharpe"]
    binary_sharpe = full_metrics[3]["sharpe"]

    all_ns = all(not r["significant"] for r in dm_results)
    any_worse = any(
        full_metrics[i+1]["sharpe"] < full_metrics[0]["sharpe"]
        for i in range(3)
    )

    if all_ns and any_worse:
        conclusion = (
            f"NULL RESULT. All 3 VIX term structure overlay variants fail to improve 12/VIX. "
            f"Sharpe: Baseline={base_sharpe}, Guard={guard_sharpe}, Smooth={smooth_sharpe}, Binary={binary_sharpe}. "
            f"No DM test exceeds Harvey t>3.0. "
            f"Consistent with T13 (DM t=0.44) and E037 lesson: VIX level already absorbs stress information."
        )
    elif not all_ns:
        # Some significant improvement
        best_idx = np.argmax([m["sharpe"] for m in full_metrics])
        best_lbl = labels[best_idx]
        best_sharpe = full_metrics[best_idx]["sharpe"]
        conclusion = (
            f"MIXED/POSITIVE. {best_lbl} shows improvement (Sharpe={best_sharpe:.4f} vs baseline {base_sharpe:.4f}). "
            f"DM t-stats: Guard={guard_dm['t_stat']:.3f}, Smooth={smooth_dm['t_stat']:.3f}, "
            f"Binary={binary_dm['t_stat']:.3f}. Harvey t>3.0 requirement: check individual tests."
        )
    else:
        conclusion = (
            f"NULL RESULT. Term structure overlays provide no statistically significant improvement. "
            f"Sharpe: Baseline={base_sharpe}, Guard={guard_sharpe}, Smooth={smooth_sharpe}, Binary={binary_sharpe}. "
            f"DM t-stats all below Harvey threshold."
        )

    results["conclusion"] = conclusion
    print(f"\n── CONCLUSION ──")
    print(f"  {conclusion}")

    # Save
    out_path = "experiments/k803_vix_term_structure_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
