#!/usr/bin/env python3
"""Phase U1: Panel Data vs Single-Asset GARCH

Experiment design:
- Baseline: GJR-GARCH(1,1) for SPY (w=2000, OOS 2023-01-01~2024-12-31)
- Model A: GARCH-X with QQQ lagged 5d RV as exogenous (variance equation)
- Model B: GARCH-X with {QQQ, GLD, TLT, EEM} lagged 5d RV as exogenous
- Model C: Simple average of 5 individual GARCH forecasts (ensemble)
- Evaluation: QLIKE + DM test vs baseline

GARCH-X implementation: manual MLE since arch library doesn't support
exogenous variables in the variance equation directly.
We use a two-step approach:
  Step 1: Fit GJR-GARCH on SPY to get conditional variance
  Step 2: Augment with lagged cross-asset RV in a post-hoc regression
  This is equivalent to the Engle & Rangel (2008) multiplicative approach.

Alternative cleaner approach used here:
  Rolling window GJR-GARCH forecast + cross-asset RV adjustment via OLS.
"""
import sys
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy import stats
from arch import arch_model

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.data.manager import DataManager


# ── Configuration ──────────────────────────────────────────────────
WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
DATA_START = "2010-01-01"  # enough for 2000-day window before OOS
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM"]
TARGET = "SPY"
RV_WINDOW = 5  # 5-day realized vol


def fetch_all_data():
    """Fetch price data for all assets and compute returns + RV."""
    dm = DataManager()
    all_data = {}
    for asset in ASSETS:
        print(f"  Fetching {asset}...")
        data = dm.get_model_data(asset, DATA_START, "2026-12-31")
        all_data[asset] = data
        print(f"    {asset}: {len(data)} observations, {data.index[0].date()} to {data.index[-1].date()}")
    return all_data


def compute_rv(returns: pd.Series, window: int = 5) -> pd.Series:
    """Compute realized variance as rolling sum of squared returns."""
    return (returns ** 2).rolling(window).sum()


def qlike(rv, sigma2):
    """QLIKE loss: mean(rv/sigma2 - log(rv/sigma2) - 1)."""
    ratio = rv / sigma2
    # Filter out non-positive values
    mask = (ratio > 0) & np.isfinite(ratio)
    r = ratio[mask]
    return np.mean(r - np.log(r) - 1)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Returns t-stat and p-value. Negative t means loss1 < loss2 (model1 better).
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return 0, 1.0

    t_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value


def rolling_gjr_forecast(returns_pct, oos_start_idx, window=WINDOW):
    """Rolling GJR-GARCH(1,1) one-step-ahead forecasts."""
    n = len(returns_pct)
    forecasts = []
    indices = []

    for t in range(oos_start_idx, n):
        train = returns_pct[max(0, t - window):t]
        if len(train) < 500:
            continue
        try:
            am = arch_model(train, vol='GARCH', p=1, o=1, q=1,
                          dist='normal', mean='Zero', rescale=False)
            res = am.fit(disp='off', show_warning=False)
            fc = res.forecast(horizon=1)
            sigma2 = fc.variance.iloc[-1, 0]
            forecasts.append(sigma2)
            indices.append(t)
        except Exception:
            continue

    return np.array(forecasts), np.array(indices)


def rolling_garch_forecast(returns_pct, oos_start_idx, window=WINDOW):
    """Rolling GARCH(1,1) one-step-ahead forecasts (no asymmetry)."""
    n = len(returns_pct)
    forecasts = []
    indices = []

    for t in range(oos_start_idx, n):
        train = returns_pct[max(0, t - window):t]
        if len(train) < 500:
            continue
        try:
            am = arch_model(train, vol='GARCH', p=1, o=0, q=1,
                          dist='normal', mean='Zero', rescale=False)
            res = am.fit(disp='off', show_warning=False)
            fc = res.forecast(horizon=1)
            sigma2 = fc.variance.iloc[-1, 0]
            forecasts.append(sigma2)
            indices.append(t)
        except Exception:
            continue

    return np.array(forecasts), np.array(indices)


def garchx_two_step(spy_sigma2, cross_rv_lagged, rv_target, oos_mask,
                     train_frac=0.5, label="GARCH-X"):
    """Two-step GARCH-X: adjust GJR forecast using cross-asset lagged RV.

    Model: sigma2_adjusted = alpha + beta * spy_sigma2 + gamma' * cross_rv_lagged
    Estimated on first half of OOS (expanding window would be better but
    this is simpler for a first test). Actually, let's use a proper
    rolling OLS approach.
    """
    n_oos = len(spy_sigma2)
    adjusted = np.full(n_oos, np.nan)

    # Need at least 60 observations to start OLS
    min_train = 60

    for t in range(min_train, n_oos):
        # Use all prior OOS data for OLS calibration
        y_train = rv_target[:t]  # realized var (actual)
        X_train = np.column_stack([spy_sigma2[:t]] +
                                  [cross_rv_lagged[k][:t] for k in range(len(cross_rv_lagged))])
        X_train = np.column_stack([np.ones(t), X_train])

        # OLS
        try:
            mask = np.all(np.isfinite(X_train), axis=1) & np.isfinite(y_train)
            if mask.sum() < 30:
                adjusted[t] = spy_sigma2[t]
                continue
            beta = np.linalg.lstsq(X_train[mask], y_train[mask], rcond=None)[0]

            # Forecast
            x_new = np.concatenate([[1, spy_sigma2[t]],
                                    [cross_rv_lagged[k][t] for k in range(len(cross_rv_lagged))]])
            pred = x_new @ beta
            # Ensure positive
            adjusted[t] = max(pred, spy_sigma2[t] * 0.5)
        except Exception:
            adjusted[t] = spy_sigma2[t]

    return adjusted


def main():
    print("=" * 70)
    print("Phase U1: Panel Data Methods vs Single-Asset GARCH")
    print("=" * 70)

    # ── Step 1: Fetch data ──
    print("\n[1/5] Fetching data for all assets...")
    all_data = fetch_all_data()

    # ── Step 2: Align all assets on common dates ──
    print("\n[2/5] Aligning data and computing realized variance...")

    # Get returns for all assets
    returns_dict = {}
    rv_dict = {}
    for asset in ASSETS:
        returns_dict[asset] = all_data[asset]['returns']
        rv_dict[asset] = compute_rv(all_data[asset]['returns'], RV_WINDOW)

    # Create aligned DataFrame
    returns_df = pd.DataFrame(returns_dict)
    rv_df = pd.DataFrame(rv_dict)

    # Drop NaN rows (need all assets present)
    common_idx = returns_df.dropna().index.intersection(rv_df.dropna().index)
    returns_df = returns_df.loc[common_idx]
    rv_df = rv_df.loc[common_idx]

    print(f"  Common dates: {common_idx[0].date()} to {common_idx[-1].date()} ({len(common_idx)} obs)")

    # Find OOS start index
    oos_start_date = pd.Timestamp(OOS_START)
    oos_end_date = pd.Timestamp(OOS_END)
    oos_mask = (common_idx >= oos_start_date) & (common_idx <= oos_end_date)
    oos_start_idx = np.where(oos_mask)[0][0]

    print(f"  OOS period: {common_idx[oos_mask][0].date()} to {common_idx[oos_mask][-1].date()} ({oos_mask.sum()} obs)")
    print(f"  Training window: {WINDOW} observations")

    # SPY returns in percentage
    spy_returns_pct = returns_df[TARGET].values * 100
    spy_returns = returns_df[TARGET].values

    # Realized variance (proxy = squared return)
    rv_actual = spy_returns ** 2  # daily squared return as RV proxy

    # ── Step 3: Baseline - GJR-GARCH ──
    print("\n[3/5] Running Baseline: GJR-GARCH(1,1) for SPY...")
    baseline_sigma2, baseline_idx = rolling_gjr_forecast(spy_returns_pct, oos_start_idx, WINDOW)

    # Convert from percentage squared to decimal
    baseline_sigma2_dec = baseline_sigma2 / 10000.0

    # Get corresponding actual RV
    rv_oos = rv_actual[baseline_idx]
    dates_oos = common_idx[baseline_idx]

    print(f"  Got {len(baseline_sigma2)} OOS forecasts")
    print(f"  Mean forecast vol (ann.): {np.sqrt(np.mean(baseline_sigma2_dec) * 252) * 100:.1f}%")

    # QLIKE for baseline
    qlike_baseline_all = rv_oos / baseline_sigma2_dec - np.log(rv_oos / baseline_sigma2_dec) - 1
    # Handle edge cases
    valid = np.isfinite(qlike_baseline_all) & (rv_oos > 0) & (baseline_sigma2_dec > 0)
    qlike_baseline = np.mean(qlike_baseline_all[valid])
    loss_baseline = qlike_baseline_all.copy()

    print(f"  Baseline QLIKE: {qlike_baseline:.6f}")

    # ── Step 4: Model A - GARCH-X with QQQ lagged RV ──
    print("\n[4a/5] Running Model A: GJR + QQQ lagged 5d RV...")

    # Lagged cross-asset RV (use t-1 to avoid look-ahead)
    rv_qqq_lagged = rv_df['QQQ'].shift(1).values[baseline_idx]

    cross_rv_A = [rv_qqq_lagged]
    adjusted_A = garchx_two_step(baseline_sigma2_dec, cross_rv_A, rv_oos,
                                  oos_mask=None, label="GARCH-X(QQQ)")

    # QLIKE for Model A
    valid_A = np.isfinite(adjusted_A) & (rv_oos > 0) & (adjusted_A > 0)
    loss_A = np.full_like(rv_oos, np.nan)
    loss_A[valid_A] = rv_oos[valid_A] / adjusted_A[valid_A] - np.log(rv_oos[valid_A] / adjusted_A[valid_A]) - 1
    qlike_A = np.nanmean(loss_A)

    print(f"  Model A QLIKE: {qlike_A:.6f}")

    # ── Step 4b: Model B - GARCH-X with 4 cross-asset lagged RVs ──
    print("\n[4b/5] Running Model B: GJR + {QQQ,GLD,TLT,EEM} lagged 5d RV...")

    cross_assets_B = ['QQQ', 'GLD', 'TLT', 'EEM']
    cross_rv_B = []
    for asset in cross_assets_B:
        rv_lagged = rv_df[asset].shift(1).values[baseline_idx]
        cross_rv_B.append(rv_lagged)

    adjusted_B = garchx_two_step(baseline_sigma2_dec, cross_rv_B, rv_oos,
                                  oos_mask=None, label="GARCH-X(4 assets)")

    valid_B = np.isfinite(adjusted_B) & (rv_oos > 0) & (adjusted_B > 0)
    loss_B = np.full_like(rv_oos, np.nan)
    loss_B[valid_B] = rv_oos[valid_B] / adjusted_B[valid_B] - np.log(rv_oos[valid_B] / adjusted_B[valid_B]) - 1
    qlike_B = np.nanmean(loss_B)

    print(f"  Model B QLIKE: {qlike_B:.6f}")

    # ── Step 4c: Model C - Ensemble of 5 individual GARCHs ──
    print("\n[4c/5] Running Model C: Ensemble average of 5 individual GJR-GARCH...")

    # We need individual GARCH forecasts for each asset, then average
    # But we need SPY RV forecast, so we use each asset's GARCH to forecast
    # its own vol, then average the cross-asset signals

    # Actually, Model C = simple average of 5 individual GARCH forecasts
    # for their OWN volatility, then map to SPY vol via correlation.
    #
    # Simpler interpretation: fit GJR-GARCH on each asset, forecast each asset's
    # vol, then use historical correlation-weighted combination to forecast SPY vol.
    #
    # Even simpler: average of 5 assets' GARCH forecasts as a "panel" forecast
    # of common market vol factor, then scale to SPY.

    # Let's do the simplest version: fit GJR on each asset, convert each forecast
    # to SPY-equivalent using vol ratio, then average.

    all_forecasts = {}
    for asset in ASSETS:
        print(f"    Running GJR-GARCH for {asset}...")
        asset_returns_pct = returns_df[asset].values * 100
        fc, idx = rolling_gjr_forecast(asset_returns_pct, oos_start_idx, WINDOW)
        # Convert to decimal
        fc_dec = fc / 10000.0
        all_forecasts[asset] = (fc_dec, idx)
        print(f"      {asset}: {len(fc)} forecasts, mean ann vol = {np.sqrt(np.mean(fc_dec)*252)*100:.1f}%")

    # Align all forecasts to common indices
    # Use baseline indices as reference
    ref_idx = set(baseline_idx)
    common_fc_idx = ref_idx.copy()
    for asset in ASSETS:
        common_fc_idx = common_fc_idx.intersection(set(all_forecasts[asset][1]))
    common_fc_idx = sorted(common_fc_idx)

    print(f"    Common forecast points: {len(common_fc_idx)}")

    # For each common index, compute vol ratio and scale
    # Vol ratio = rolling ratio of SPY vol to asset vol (past 252 days)
    ensemble_sigma2 = np.full(len(baseline_idx), np.nan)

    for i, t in enumerate(baseline_idx):
        if t not in common_fc_idx:
            ensemble_sigma2[i] = baseline_sigma2_dec[i]
            continue

        # Get each asset's forecast at this point
        forecasts_at_t = []
        for asset in ASSETS:
            fc_arr, idx_arr = all_forecasts[asset]
            pos = np.where(idx_arr == t)[0]
            if len(pos) == 0:
                continue
            fc_val = fc_arr[pos[0]]

            if asset == TARGET:
                forecasts_at_t.append(fc_val)
            else:
                # Scale by historical vol ratio (SPY vol / asset vol)
                # Use past 252 days
                lookback = max(0, t - 252)
                spy_hist_var = np.mean(spy_returns[lookback:t] ** 2)
                asset_hist_var = np.mean(returns_df[asset].values[lookback:t] ** 2)
                if asset_hist_var > 0:
                    ratio = spy_hist_var / asset_hist_var
                    forecasts_at_t.append(fc_val * ratio)

        if len(forecasts_at_t) > 0:
            ensemble_sigma2[i] = np.mean(forecasts_at_t)

    valid_C = np.isfinite(ensemble_sigma2) & (rv_oos > 0) & (ensemble_sigma2 > 0)
    loss_C = np.full_like(rv_oos, np.nan)
    loss_C[valid_C] = rv_oos[valid_C] / ensemble_sigma2[valid_C] - np.log(rv_oos[valid_C] / ensemble_sigma2[valid_C]) - 1
    qlike_C = np.nanmean(loss_C)

    print(f"  Model C QLIKE: {qlike_C:.6f}")

    # ── Step 5: DM Tests ──
    print("\n[5/5] Diebold-Mariano Tests vs Baseline...")
    print("=" * 70)

    # For DM test, use only indices where both models have valid losses
    results = {}

    for name, loss_alt, qlike_val in [("Model A (GJR + QQQ RV)", loss_A, qlike_A),
                                       ("Model B (GJR + 4-asset RV)", loss_B, qlike_B),
                                       ("Model C (5-asset ensemble)", loss_C, qlike_C)]:
        mask = np.isfinite(loss_baseline) & np.isfinite(loss_alt)
        if mask.sum() < 30:
            print(f"\n{name}: Insufficient valid observations ({mask.sum()})")
            continue

        t_stat, p_val = dm_test(loss_alt[mask], loss_baseline[mask], h=1)

        improvement = (qlike_baseline - qlike_val) / qlike_baseline * 100

        results[name] = {
            'qlike': qlike_val,
            'improvement': improvement,
            'dm_t': t_stat,
            'dm_p': p_val,
            'n_obs': int(mask.sum()),
        }

        winner = "Panel" if t_stat < 0 else "Baseline"
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else "n.s."

        print(f"\n{name}:")
        print(f"  QLIKE:       {qlike_val:.6f}  (baseline: {qlike_baseline:.6f})")
        print(f"  Improvement: {improvement:+.2f}%")
        print(f"  DM t-stat:   {t_stat:.3f}  (negative = panel better)")
        print(f"  DM p-value:  {p_val:.4f}  [{sig}]")
        print(f"  N obs:       {mask.sum()}")
        print(f"  Favors:      {winner}")

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\n{'Model':<35} {'QLIKE':>10} {'Δ%':>8} {'DM-t':>8} {'DM-p':>8} {'Sig':>5}")
    print("-" * 75)
    print(f"{'Baseline (GJR-GARCH)':<35} {qlike_baseline:>10.6f} {'—':>8} {'—':>8} {'—':>8} {'—':>5}")

    for name, r in results.items():
        sig = "***" if r['dm_p'] < 0.01 else "**" if r['dm_p'] < 0.05 else "*" if r['dm_p'] < 0.10 else "n.s."
        print(f"{name:<35} {r['qlike']:>10.6f} {r['improvement']:>+7.2f}% {r['dm_t']:>8.3f} {r['dm_p']:>8.4f} {sig:>5}")

    # ── Interpretation ──
    print("\n" + "=" * 70)
    print("INTERPRETATION")
    print("=" * 70)

    any_significant = any(r['dm_p'] < 0.10 and r['dm_t'] < 0 for r in results.values())

    if any_significant:
        best = min(results.items(), key=lambda x: x[1]['qlike'])
        print(f"\n✓ Panel methods show promise: {best[0]} achieves best QLIKE")
        print(f"  with {best[1]['improvement']:+.2f}% improvement (DM p={best[1]['dm_p']:.4f})")
    else:
        print("\n✗ No panel method significantly outperforms single-asset GJR-GARCH.")
        print("  Cross-asset information does not improve SPY vol forecasting")
        print("  in this OOS period (2023-2024).")

        # Check if any model is even directionally better
        better = [n for n, r in results.items() if r['improvement'] > 0]
        if better:
            print(f"\n  Directionally better (but n.s.): {', '.join(better)}")
        else:
            print("\n  All panel models have WORSE QLIKE than baseline.")

    # ── Additional diagnostics ──
    print("\n" + "=" * 70)
    print("ADDITIONAL DIAGNOSTICS")
    print("=" * 70)

    # Cross-asset RV correlations
    print("\nCross-asset 5d RV correlations with SPY (full sample):")
    for asset in ['QQQ', 'GLD', 'TLT', 'EEM']:
        corr = rv_df[TARGET].corr(rv_df[asset])
        print(f"  {asset}: ρ = {corr:.3f}")

    # Lagged cross-asset RV predictive power for SPY RV
    print("\nLagged cross-asset RV → SPY squared return (predictive R²):")
    for asset in ['QQQ', 'GLD', 'TLT', 'EEM']:
        x = rv_df[asset].shift(1).dropna()
        y = (returns_df[TARGET] ** 2).loc[x.index]
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() > 100:
            corr = np.corrcoef(x[mask], y[mask])[0, 1]
            r2 = corr ** 2
            print(f"  {asset}(t-1) → SPY²(t): R² = {r2:.4f}, ρ = {corr:.3f}")

    print("\nDone.")
    return results


if __name__ == "__main__":
    main()
