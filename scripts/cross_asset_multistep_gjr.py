#!/usr/bin/env python3
"""
Cross-asset verification: Does GJR-GARCH advantage amplify at longer horizons?

For each of 6 assets (SPY, QQQ, GLD, TLT, EEM, 0050.TW):
  - Fit rolling GJR-GARCH(1,1) and GARCH(1,1) with window=2000
  - Produce h-step-ahead variance forecasts for h=1, 5, 22
  - Evaluate with QLIKE loss
  - Diebold-Mariano test comparing GJR vs GARCH

Key question: Does the DM t-stat become more negative (GJR better)
at longer horizons for all asset classes, or only equities?
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import time

# ── Configuration ──────────────────────────────────────────────
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM", "0050.TW"]
HORIZONS = [1, 5, 22]
WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
DATA_START = "2012-01-01"  # enough history for window=2000 before 2023

# ── Helper functions ───────────────────────────────────────────

def fetch_returns(ticker: str) -> pd.Series:
    """Fetch daily returns (percentage) for a ticker."""
    print(f"  Downloading {ticker}...", end=" ", flush=True)
    df = yf.download(ticker, start=DATA_START, end="2025-01-15",
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Use Adj Close if available, else Close
    price_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    prices = df[price_col].dropna()
    returns = 100 * np.log(prices / prices.shift(1)).dropna()
    print(f"got {len(returns)} obs ({returns.index[0].date()} to {returns.index[-1].date()})")
    return returns


def qlike(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """
    QLIKE loss: realized/forecast - ln(realized/forecast) - 1 (element-wise).
    Filter out cases where realized or forecast <= 0.
    """
    # Filter valid entries
    valid = (realized > 1e-10) & (forecast > 1e-10) & np.isfinite(realized) & np.isfinite(forecast)
    r = realized[valid]
    f = forecast[valid]
    ratio = r / f
    loss = np.full_like(realized, np.nan)
    loss[valid] = ratio - np.log(ratio) - 1
    return loss


def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple:
    """
    Diebold-Mariano test with Newey-West HAC.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Negative t-stat means loss1 < loss2 (model 1 better).
    """
    # Remove NaN pairs
    valid = np.isfinite(loss1) & np.isfinite(loss2)
    d = loss1[valid] - loss2[valid]
    n = len(d)

    if n < 30:
        return np.nan, np.nan

    d_bar = np.mean(d)

    # HAC variance (Newey-West)
    bandwidth = max(h - 1, 0)
    gamma_0 = np.mean((d - d_bar) ** 2)
    hac_var = gamma_0
    for k in range(1, bandwidth + 1):
        w = 1 - k / (bandwidth + 1)  # Bartlett kernel
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        hac_var += 2 * w * gamma_k

    # Ensure positive variance
    if hac_var <= 0:
        hac_var = gamma_0

    se = np.sqrt(hac_var / n)
    if se < 1e-12:
        return 0.0, 1.0

    t_stat = d_bar / se
    p_value = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return t_stat, p_value


def multi_step_variance(model_result, h: int) -> float:
    """
    Compute h-step-ahead cumulative variance forecast from GARCH parameters.

    Uses proper recursive formula:
    E[sigma^2_{t+k}] = omega + persistence * E[sigma^2_{t+k-1}]

    Cumulative h-step variance = sum of E[sigma^2_{t+j}] for j=1..h

    For GJR: persistence = alpha + gamma/2 + beta
    (assuming E[I(e<0)] = 0.5 under conditional normality)
    """
    params = model_result.params
    omega = params.get("omega", 0)
    alpha = params.get("alpha[1]", 0)
    beta = params.get("beta[1]", 0)
    gamma_param = params.get("gamma[1]", 0)  # 0 for standard GARCH

    # Persistence for multi-step: alpha + gamma/2 + beta
    persistence = alpha + gamma_param / 2 + beta

    # 1-step conditional variance (from last observation in the fitted window)
    sigma2_1 = model_result.conditional_volatility.iloc[-1] ** 2

    if h == 1:
        return sigma2_1

    # Cumulative h-step variance via recursive formula
    cumulative = sigma2_1  # k=1
    sigma2_k = sigma2_1
    for k in range(2, h + 1):
        sigma2_k = omega + persistence * sigma2_k
        cumulative += sigma2_k

    return cumulative


def rolling_forecast(returns: pd.Series, model_type: str, horizon: int) -> pd.DataFrame:
    """
    Rolling window forecast for a given model type and horizon.
    Returns DataFrame with columns: date, forecast, realized
    """
    all_dates = returns.index
    oos_mask = (all_dates >= OOS_START) & (all_dates <= OOS_END)
    oos_indices = np.where(oos_mask)[0]

    results = []
    n_total = len(oos_indices)
    n_done = 0
    n_failed = 0

    for count, idx in enumerate(oos_indices):
        date = all_dates[idx]

        # Realized variance: sum of squared returns over next h days
        if idx + horizon >= len(returns):
            break

        future_returns = returns.iloc[idx + 1: idx + 1 + horizon]
        if len(future_returns) < horizon:
            break
        realized_var = np.sum(future_returns.values ** 2)

        # Skip if realized is essentially zero (holidays/no movement)
        if realized_var < 1e-10:
            n_failed += 1
            continue

        # Training window
        train_start = max(0, idx - WINDOW + 1)
        train_data = returns.iloc[train_start: idx + 1]

        if len(train_data) < 500:
            continue

        try:
            if model_type == "gjr":
                am = arch_model(train_data, vol="GARCH", p=1, o=1, q=1,
                               dist="StudentsT", mean="Zero")
            else:
                am = arch_model(train_data, vol="GARCH", p=1, o=0, q=1,
                               dist="StudentsT", mean="Zero")

            res = am.fit(disp="off", show_warning=False)

            # Get h-step cumulative variance forecast
            forecast_var = multi_step_variance(res, horizon)

            if np.isfinite(forecast_var) and forecast_var > 1e-10:
                results.append({
                    "date": date,
                    "forecast": forecast_var,
                    "realized": realized_var,
                })
                n_done += 1
            else:
                n_failed += 1
        except Exception:
            n_failed += 1

        # Progress
        if (count + 1) % 100 == 0 or count == n_total - 1:
            print(f"\r    {model_type.upper()} h={horizon}: {count+1}/{n_total} "
                  f"({n_done} ok, {n_failed} fail)", end="", flush=True)

    print()  # newline

    if not results:
        return pd.DataFrame()

    return pd.DataFrame(results)


# ── Main execution ─────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Cross-Asset Multi-Step GJR Advantage Verification")
    print(f"Window={WINDOW}, OOS={OOS_START} to {OOS_END}")
    print(f"Assets: {', '.join(ASSETS)}")
    print(f"Horizons: {HORIZONS}")
    print("=" * 70)

    all_results = []
    asset_gammas = {}

    for asset in ASSETS:
        print(f"\n{'─' * 50}")
        print(f"Asset: {asset}")
        print(f"{'─' * 50}")

        try:
            returns = fetch_returns(asset)
        except Exception as e:
            print(f"  ERROR fetching {asset}: {e}")
            continue

        # Check data sufficiency
        oos_count = ((returns.index >= OOS_START) & (returns.index <= OOS_END)).sum()
        if oos_count < 100:
            print(f"  SKIP: only {oos_count} OOS observations")
            continue

        # Estimate gamma on recent data to classify asset
        try:
            recent = returns[returns.index >= "2020-01-01"]
            am = arch_model(recent, vol="GARCH", p=1, o=1, q=1,
                           dist="StudentsT", mean="Zero")
            res = am.fit(disp="off", show_warning=False)
            gamma_est = res.params.get("gamma[1]", 0)
            asset_gammas[asset] = gamma_est
            print(f"  Estimated gamma = {gamma_est:.4f}")
        except Exception:
            asset_gammas[asset] = np.nan
            print(f"  Could not estimate gamma")

        for h in HORIZONS:
            print(f"\n  Horizon h={h}:")
            t_start = time.time()

            gjr_df = rolling_forecast(returns, "gjr", h)
            garch_df = rolling_forecast(returns, "garch", h)

            elapsed = time.time() - t_start

            if gjr_df.empty or garch_df.empty:
                print(f"    SKIP: insufficient forecasts")
                continue

            # Align dates
            merged = gjr_df.merge(garch_df, on="date", suffixes=("_gjr", "_garch"))

            if len(merged) < 50:
                print(f"    SKIP: only {len(merged)} aligned observations")
                continue

            # QLIKE losses
            qlike_gjr = qlike(merged["realized_gjr"].values, merged["forecast_gjr"].values)
            qlike_garch = qlike(merged["realized_garch"].values, merged["forecast_garch"].values)

            # DM test (negative = GJR better)
            t_stat, p_val = dm_test(qlike_gjr, qlike_garch, h=h)

            # Mean QLIKE (excluding NaN)
            mean_qlike_gjr = np.nanmean(qlike_gjr)
            mean_qlike_garch = np.nanmean(qlike_garch)
            n_valid = np.sum(np.isfinite(qlike_gjr) & np.isfinite(qlike_garch))

            result = {
                "asset": asset,
                "horizon": h,
                "gamma": asset_gammas.get(asset, np.nan),
                "n_obs": int(n_valid),
                "qlike_gjr": mean_qlike_gjr,
                "qlike_garch": mean_qlike_garch,
                "dm_tstat": t_stat,
                "dm_pval": p_val,
                "gjr_better": t_stat < 0 if np.isfinite(t_stat) else False,
                "elapsed_sec": elapsed,
            }
            all_results.append(result)

            sig = ""
            if np.isfinite(p_val):
                sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            direction = "GJR better" if (np.isfinite(t_stat) and t_stat < 0) else "GARCH better"
            t_str = f"{t_stat:.3f}" if np.isfinite(t_stat) else "N/A"
            p_str = f"{p_val:.4f}" if np.isfinite(p_val) else "N/A"
            print(f"    N={n_valid}, QLIKE GJR={mean_qlike_gjr:.4f}, "
                  f"GARCH={mean_qlike_garch:.4f}")
            print(f"    DM t={t_str} (p={p_str}) {sig} -> {direction}")
            print(f"    Time: {elapsed:.1f}s")

    # ── Summary Table ──────────────────────────────────────────
    if not all_results:
        print("\nNo results to summarize!")
        return

    df = pd.DataFrame(all_results)

    print("\n" + "=" * 80)
    print("SUMMARY TABLE: DM t-statistics (negative = GJR better)")
    print("=" * 80)

    # Pivot table: Asset x Horizon
    pivot = df.pivot_table(index="asset", columns="horizon", values="dm_tstat")
    pivot = pivot.reindex(columns=HORIZONS)

    # Add gamma column
    gamma_series = df.groupby("asset")["gamma"].first()

    # Format nicely
    print(f"\n{'Asset':<10} {'gamma':>8} {'h=1':>12} {'h=5':>12} {'h=22':>12} {'Amplifies?':>12}")
    print("-" * 70)

    for asset in ASSETS:
        if asset not in pivot.index:
            print(f"{asset:<10} {'N/A':>8} {'N/A':>12} {'N/A':>12} {'N/A':>12}")
            continue

        row = pivot.loc[asset]
        gamma = gamma_series.get(asset, np.nan)

        vals = {}
        for h in HORIZONS:
            if h in row.index and pd.notna(row[h]):
                vals[h] = row[h]

        # Check amplification
        amplifies = "N/A"
        if all(h in vals for h in HORIZONS):
            if vals[1] < 0 and vals[5] < vals[1] and vals[22] < vals[5]:
                amplifies = "YES"
            elif vals[1] < 0 and vals[22] < vals[1]:
                amplifies = "PARTIAL"
            elif vals[1] >= 0:
                amplifies = "NO (GARCH)"
            else:
                amplifies = "NO"

        def fmt_t(h):
            if h in vals:
                v = vals[h]
                p_row = df[(df["asset"] == asset) & (df["horizon"] == h)]
                s = ""
                if not p_row.empty:
                    p = p_row.iloc[0]["dm_pval"]
                    if np.isfinite(p):
                        s = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
                return f"{v:>8.3f}{s:<4}"
            return f"{'N/A':>12}"

        gamma_str = f"{gamma:.4f}" if np.isfinite(gamma) else "N/A"
        print(f"{asset:<10} {gamma_str:>8} {fmt_t(1)} {fmt_t(5)} {fmt_t(22)} {amplifies:>12}")

    # ── QLIKE comparison table ─────────────────────────────────
    print(f"\n\n{'Asset':<10} {'h':>4} {'N':>6} {'QLIKE_GJR':>12} {'QLIKE_GARCH':>12} {'Diff%':>10}")
    print("-" * 58)
    for _, row in df.iterrows():
        diff_pct = 100 * (row["qlike_gjr"] - row["qlike_garch"]) / row["qlike_garch"] if row["qlike_garch"] != 0 else 0
        print(f"{row['asset']:<10} {row['horizon']:>4} {row['n_obs']:>6} "
              f"{row['qlike_gjr']:>12.4f} {row['qlike_garch']:>12.4f} {diff_pct:>9.2f}%")

    # ── Interpretation ─────────────────────────────────────────
    print("\n" + "=" * 80)
    print("INTERPRETATION")
    print("=" * 80)

    equity_assets = [a for a in ASSETS if a in ["SPY", "QQQ", "EEM", "0050.TW"]]
    non_equity = [a for a in ASSETS if a in ["GLD", "TLT"]]

    for group_name, group_assets in [("EQUITY", equity_assets), ("NON-EQUITY", non_equity)]:
        group_df = df[df["asset"].isin(group_assets)]
        if group_df.empty:
            continue

        print(f"\n{group_name} assets ({', '.join(group_assets)}):")
        for h in HORIZONS:
            h_data = group_df[group_df["horizon"] == h]
            h_data_valid = h_data[h_data["dm_tstat"].apply(np.isfinite)]
            if h_data_valid.empty:
                continue
            mean_t = h_data_valid["dm_tstat"].mean()
            n_better = (h_data_valid["dm_tstat"] < 0).sum()
            n_sig = (h_data_valid["dm_pval"] < 0.05).sum()
            print(f"  h={h:>2}: mean DM t = {mean_t:.3f}, "
                  f"GJR better in {n_better}/{len(h_data_valid)}, "
                  f"significant in {n_sig}/{len(h_data_valid)}")

    # Correlation between gamma and DM t-stat
    print("\n\nGamma vs DM t-stat correlation:")
    for h in HORIZONS:
        h_data = df[df["horizon"] == h].dropna(subset=["gamma", "dm_tstat"])
        h_data = h_data[h_data["dm_tstat"].apply(np.isfinite)]
        if len(h_data) >= 4:
            corr, p = stats.spearmanr(h_data["gamma"], h_data["dm_tstat"])
            print(f"  h={h:>2}: Spearman rho = {corr:.3f} (p={p:.3f}) "
                  f"{'(more gamma -> more GJR advantage)' if corr < 0 else ''}")

    # Overall answer
    print("\n" + "-" * 80)

    amplifying_assets = []
    non_amplifying = []
    for asset in ASSETS:
        asset_df = df[df["asset"] == asset]
        t_vals = {}
        for _, row in asset_df.iterrows():
            if np.isfinite(row["dm_tstat"]):
                t_vals[row["horizon"]] = row["dm_tstat"]
        if all(h in t_vals for h in HORIZONS):
            if t_vals[1] < 0 and t_vals[22] < t_vals[1]:
                amplifying_assets.append(asset)
            else:
                non_amplifying.append(asset)
        elif 5 in t_vals and 22 in t_vals:
            # Partial check: 5->22 amplification
            if t_vals[5] < 0 and t_vals[22] < t_vals[5]:
                amplifying_assets.append(f"{asset}(5->22)")
            elif t_vals[22] < t_vals.get(5, 0):
                amplifying_assets.append(f"{asset}(partial)")
            else:
                non_amplifying.append(asset)

    print(f"\nAmplification pattern (GJR advantage grows with horizon):")
    print(f"  Found in: {amplifying_assets if amplifying_assets else 'none'}")
    print(f"  Not found in: {non_amplifying if non_amplifying else 'none'}")

    # Save results
    df.to_csv("/Users/yhlai0911/Dropbox/自我研究波動預測模型/storage/results/cross_asset_multistep_gjr.csv",
              index=False)
    print(f"\nResults saved to storage/results/cross_asset_multistep_gjr.csv")


if __name__ == "__main__":
    main()
