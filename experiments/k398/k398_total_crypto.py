#!/usr/bin/env python3
"""K398: Total Crypto Market Volatility — Beyond BTC (跳躍式探索)

Pre-experiment check: ZERO mentions of total crypto market. K277 BTC deep structure.
K334 DeFi pilot. K381 UNI/AAVE. But never the TOTAL crypto market.

Related: K277 BTC no leverage. K381 DeFi 98% vol. K334 crypto features flip OOS.

Research Questions:
1. Construct crypto market index (60% BTC + 30% ETH + 10% small caps if available)
2. Total crypto vol vs BTC vol — does intra-crypto diversification reduce vol?
3. Crypto market cycle: bull/bear/accumulation — vol dynamics by phase
4. Crypto-equity decorrelation: has crypto become MORE correlated post-2020?
5. Can GARCH work for total crypto? (K277: BTC ACF(1)=0.106, very weak clustering)

Data: yfinance — BTC-USD, ETH-USD, SPY, ^VIX, SOL-USD, ADA-USD, AVAX-USD, DOT-USD
OOS: 2023-01-01 ~ 2025-12-31

[提出: 用戶, 執行: Claude]
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime
import json

# ─── Configuration ──────────────────────────────────────────────
CRYPTO_TICKERS = {
    "BTC-USD": 0.60,   # 60% — dominates market cap
    "ETH-USD": 0.30,   # 30% — second largest
    # Small cap basket: 10% split equally
    "SOL-USD": 0.025,
    "ADA-USD": 0.025,
    "AVAX-USD": 0.025,
    "DOT-USD": 0.025,
}
BENCHMARK_TICKERS = ["SPY", "^VIX"]
START_DATE = "2020-01-01"  # SOL/AVAX have limited history
END_DATE = "2025-12-31"
OOS_START = "2023-01-01"
IS_START = "2020-06-01"    # Allow some warm-up for small caps

print("=" * 80)
print("K398: Total Crypto Market Volatility — Beyond BTC")
print("=" * 80)

# ─── Helper functions ───────────────────────────────────────────
def qlike_loss(realized_var, forecast_var):
    """QLIKE loss: lower is better."""
    valid = (forecast_var > 0) & (realized_var > 0) & np.isfinite(realized_var) & np.isfinite(forecast_var)
    r = realized_var[valid]
    f = forecast_var[valid]
    return np.mean(np.log(f) + r / f)


def dm_test(loss1, loss2):
    """Diebold-Mariano test. Negative t = model1 better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    lag = max(1, int(n ** (1 / 3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag + 1):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k
    var_d = gamma0 + gamma_sum
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d / n)
    p_val = 2 * stats.t.cdf(-abs(t_stat), df=n - 1)
    return t_stat, p_val


def rolling_correlation(x, y, window=60):
    """Rolling correlation with given window."""
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    return df["x"].rolling(window).corr(df["y"])


# ─── 1. Data Download ───────────────────────────────────────────
print("\n[1] Downloading data...")
all_tickers = list(CRYPTO_TICKERS.keys()) + BENCHMARK_TICKERS
data = {}
for ticker in all_tickers:
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if len(df) > 100:
            data[ticker] = df
            print(f"  {ticker}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")
        else:
            print(f"  {ticker}: Only {len(df)} days — SKIPPING")
    except Exception as e:
        print(f"  {ticker}: FAILED — {e}")

# Check what we got
crypto_available = [t for t in CRYPTO_TICKERS if t in data]
print(f"\nCrypto available: {len(crypto_available)}/{len(CRYPTO_TICKERS)}")
print(f"Benchmark available: {[t for t in BENCHMARK_TICKERS if t in data]}")

if "BTC-USD" not in data or "ETH-USD" not in data:
    print("FATAL: Need at least BTC and ETH")
    exit(1)

# ─── 2. Construct Crypto Market Index ────────────────────────────
print("\n" + "=" * 80)
print("[2] Constructing Crypto Market Index")
print("=" * 80)

# Compute daily returns for all crypto assets
crypto_returns = {}
for ticker in crypto_available:
    prices = data[ticker]["Close"]
    ret = np.log(prices / prices.shift(1))
    crypto_returns[ticker] = ret

# Align all crypto returns to common dates
ret_df = pd.DataFrame(crypto_returns).dropna()
print(f"Common date range: {ret_df.index[0].date()} to {ret_df.index[-1].date()}")
print(f"Common observations: {len(ret_df)}")

# Normalize weights to available assets
available_weights = {t: CRYPTO_TICKERS[t] for t in crypto_available}
total_w = sum(available_weights.values())
norm_weights = {t: w / total_w for t, w in available_weights.items()}
print(f"\nNormalized weights:")
for t, w in norm_weights.items():
    print(f"  {t}: {w:.3f}")

# Construct index return
index_returns = sum(ret_df[t] * norm_weights[t] for t in crypto_available)
index_returns.name = "CryptoIndex"

# BTC-only returns for comparison
btc_returns = crypto_returns["BTC-USD"].reindex(index_returns.index)
eth_returns = crypto_returns["ETH-USD"].reindex(index_returns.index)

# SPY returns
spy_returns = np.log(data["SPY"]["Close"] / data["SPY"]["Close"].shift(1))
spy_returns = spy_returns.reindex(index_returns.index)  # align to crypto trading days (crypto 365, SPY ~252)

# VIX levels
vix = data["^VIX"]["Close"].reindex(index_returns.index, method="ffill")

print(f"\nCrypto Index constructed: {len(index_returns)} observations")

# ─── 3. Descriptive Statistics ───────────────────────────────────
print("\n" + "=" * 80)
print("[3] Descriptive Statistics: Crypto Index vs BTC vs ETH vs SPY")
print("=" * 80)

def desc_stats(ret, name):
    """Compute descriptive stats for a return series."""
    r = ret.dropna()
    ann_ret = r.mean() * 365
    ann_vol = r.std() * np.sqrt(365)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    skew = stats.skew(r)
    kurt = stats.kurtosis(r)  # excess kurtosis
    min_r = r.min()
    max_r = r.max()
    acf1 = r.autocorr(lag=1) if len(r) > 10 else np.nan
    # ACF of squared returns (vol clustering)
    r2 = r ** 2
    acf1_sq = r2.autocorr(lag=1) if len(r2) > 10 else np.nan
    return {
        "name": name,
        "n": len(r),
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "skewness": skew,
        "excess_kurtosis": kurt,
        "min_daily": min_r,
        "max_daily": max_r,
        "acf1_returns": acf1,
        "acf1_sq_returns": acf1_sq,
    }

series_list = [
    (index_returns, "CryptoIndex"),
    (btc_returns, "BTC"),
    (eth_returns, "ETH"),
    (spy_returns, "SPY"),
]

stats_table = []
for ret, name in series_list:
    s = desc_stats(ret, name)
    stats_table.append(s)
    print(f"\n  {name}:")
    print(f"    N={s['n']}, Ann.Return={s['ann_return']:.3f}, Ann.Vol={s['ann_vol']:.3f}")
    print(f"    Sharpe={s['sharpe']:.3f}, Skew={s['skewness']:.3f}, ExKurt={s['excess_kurtosis']:.3f}")
    print(f"    Min={s['min_daily']:.4f}, Max={s['max_daily']:.4f}")
    print(f"    ACF(1) returns={s['acf1_returns']:.3f}, ACF(1) sq.returns={s['acf1_sq_returns']:.3f}")

# ─── 4. Intra-Crypto Diversification ─────────────────────────────
print("\n" + "=" * 80)
print("[4] Intra-Crypto Diversification: Does index vol < BTC vol?")
print("=" * 80)

# Rolling 30d realized vol comparison
window_rv = 30
btc_rv = btc_returns.rolling(window_rv).std() * np.sqrt(365)
idx_rv = index_returns.rolling(window_rv).std() * np.sqrt(365)
eth_rv = eth_returns.rolling(window_rv).std() * np.sqrt(365)

# Vol ratio: index / BTC
vol_ratio = idx_rv / btc_rv
vol_ratio_clean = vol_ratio.dropna()

print(f"\n  30d Rolling Vol Ratio (CryptoIndex / BTC):")
print(f"    Mean: {vol_ratio_clean.mean():.4f}")
print(f"    Median: {vol_ratio_clean.median():.4f}")
print(f"    Min: {vol_ratio_clean.min():.4f}")
print(f"    Max: {vol_ratio_clean.max():.4f}")
print(f"    % days index vol < BTC vol: {(vol_ratio_clean < 1).mean():.1%}")

# Vol reduction
vol_reduction = 1 - vol_ratio_clean.mean()
print(f"\n  Average vol reduction from diversification: {vol_reduction:.1%}")

# Pairwise correlations within crypto
print(f"\n  Full-sample pairwise correlations:")
corr_matrix = ret_df.corr()
for i, t1 in enumerate(crypto_available):
    for t2 in crypto_available[i + 1:]:
        print(f"    {t1} vs {t2}: {corr_matrix.loc[t1, t2]:.3f}")

# Rolling BTC-ETH correlation
btc_eth_corr = rolling_correlation(btc_returns, eth_returns, window=90)
btc_eth_corr_clean = btc_eth_corr.dropna()
print(f"\n  90d Rolling BTC-ETH Correlation:")
print(f"    Mean: {btc_eth_corr_clean.mean():.3f}")
print(f"    Min: {btc_eth_corr_clean.min():.3f}")
print(f"    Max: {btc_eth_corr_clean.max():.3f}")

# ─── 5. Crypto Market Cycle Analysis ─────────────────────────────
print("\n" + "=" * 80)
print("[5] Crypto Market Cycle: Vol Dynamics by Phase")
print("=" * 80)

# Define cycles using BTC cumulative return and drawdown
btc_price = data["BTC-USD"]["Close"].reindex(index_returns.index).ffill()
btc_cum = btc_price / btc_price.iloc[0]
btc_peak = btc_cum.cummax()
btc_dd = (btc_cum - btc_peak) / btc_peak

# Classify: Bull (new highs or within 10%), Bear (DD > 30%), Accumulation (between)
def classify_cycle(dd_series):
    phases = pd.Series(index=dd_series.index, dtype=str)
    phases[dd_series > -0.10] = "Bull"
    phases[(dd_series <= -0.10) & (dd_series > -0.30)] = "Accumulation"
    phases[dd_series <= -0.30] = "Bear"
    return phases

cycle_phase = classify_cycle(btc_dd)
print(f"\n  Phase distribution:")
for phase in ["Bull", "Accumulation", "Bear"]:
    mask = cycle_phase == phase
    n_days = mask.sum()
    pct = n_days / len(cycle_phase)
    if n_days > 0:
        phase_vol = index_returns[mask].std() * np.sqrt(365)
        phase_btc_vol = btc_returns[mask].std() * np.sqrt(365)
        phase_ret = index_returns[mask].mean() * 365
        print(f"    {phase}: {n_days} days ({pct:.1%})")
        print(f"      Index Ann.Vol={phase_vol:.3f}, BTC Ann.Vol={phase_btc_vol:.3f}")
        print(f"      Index Ann.Return={phase_ret:.3f}")
        print(f"      Vol ratio (Index/BTC)={phase_vol/phase_btc_vol:.3f}")

# Vol asymmetry: does crypto vol spike more in bear than bull?
bull_vol = index_returns[cycle_phase == "Bull"].std() * np.sqrt(365)
bear_vol = index_returns[cycle_phase == "Bear"].std() * np.sqrt(365)
print(f"\n  Bear/Bull vol ratio: {bear_vol/bull_vol:.2f}x")
print(f"  (SPY leverage effect typically 1.5-2.0x)")

# ─── 6. Crypto-Equity Decorrelation Over Time ────────────────────
print("\n" + "=" * 80)
print("[6] Crypto-Equity Correlation: Has Crypto Become More Correlated?")
print("=" * 80)

# Align crypto index and SPY returns
aligned = pd.DataFrame({
    "crypto": index_returns,
    "spy": spy_returns,
    "btc": btc_returns,
    "vix": vix,
}).dropna()

print(f"  Aligned observations (trading days with both): {len(aligned)}")

# Full-sample correlation
full_corr = aligned["crypto"].corr(aligned["spy"])
btc_spy_corr = aligned["btc"].corr(aligned["spy"])
print(f"\n  Full-sample Crypto Index-SPY correlation: {full_corr:.3f}")
print(f"  Full-sample BTC-SPY correlation: {btc_spy_corr:.3f}")

# Year-by-year correlation
print(f"\n  Year-by-year Crypto-SPY correlation:")
for year in sorted(aligned.index.year.unique()):
    mask = aligned.index.year == year
    if mask.sum() > 20:
        c = aligned.loc[mask, "crypto"].corr(aligned.loc[mask, "spy"])
        c_btc = aligned.loc[mask, "btc"].corr(aligned.loc[mask, "spy"])
        print(f"    {year}: CryptoIdx-SPY={c:.3f}, BTC-SPY={c_btc:.3f} (n={mask.sum()})")

# Rolling 90d correlation
roll_corr_idx = rolling_correlation(aligned["crypto"], aligned["spy"], window=90)
roll_corr_btc = rolling_correlation(aligned["btc"], aligned["spy"], window=90)

# Pre-2022 vs post-2022 (institutional adoption marker)
pre_inst = aligned[aligned.index < "2022-01-01"]
post_inst = aligned[aligned.index >= "2022-01-01"]

if len(pre_inst) > 30 and len(post_inst) > 30:
    pre_corr = pre_inst["crypto"].corr(pre_inst["spy"])
    post_corr = post_inst["crypto"].corr(post_inst["spy"])
    print(f"\n  Pre-2022 (pre-institutional): CryptoIdx-SPY = {pre_corr:.3f}")
    print(f"  Post-2022 (post-institutional): CryptoIdx-SPY = {post_corr:.3f}")
    print(f"  Change: {post_corr - pre_corr:+.3f}")

    # Fisher z-test for difference in correlations
    def fisher_z(r, n):
        z = 0.5 * np.log((1 + r) / (1 - r))
        se = 1 / np.sqrt(n - 3)
        return z, se

    z1, se1 = fisher_z(pre_corr, len(pre_inst))
    z2, se2 = fisher_z(post_corr, len(post_inst))
    z_diff = (z2 - z1) / np.sqrt(se1 ** 2 + se2 ** 2)
    p_diff = 2 * stats.norm.cdf(-abs(z_diff))
    print(f"  Fisher z-test: z={z_diff:.2f}, p={p_diff:.4f}")
    if p_diff < 0.05:
        print(f"  → SIGNIFICANT change in correlation (p<0.05)")
    else:
        print(f"  → No significant change (p={p_diff:.3f})")

# ─── 7. GARCH Modeling for Crypto Index ──────────────────────────
print("\n" + "=" * 80)
print("[7] GARCH Modeling: Can GARCH Capture Crypto Index Volatility?")
print("=" * 80)

# Scale returns to percentage for GARCH
idx_ret_pct = (index_returns * 100).dropna()
btc_ret_pct = (btc_returns * 100).dropna()

# Split IS/OOS
is_mask = idx_ret_pct.index < OOS_START
oos_mask = idx_ret_pct.index >= OOS_START

print(f"  IS period: {idx_ret_pct[is_mask].index[0].date()} to {idx_ret_pct[is_mask].index[-1].date()} ({is_mask.sum()} days)")
print(f"  OOS period: {idx_ret_pct[oos_mask].index[0].date()} to {idx_ret_pct[oos_mask].index[-1].date()} ({oos_mask.sum()} days)")

# Models to test
models_config = [
    ("GARCH(1,1)", "Garch", 1, 1, "normal", None),
    ("GJR-GARCH", "Garch", 1, 1, "normal", 1),  # o=1 for GJR
    ("EGARCH(1,1)", "EGARCH", 1, 1, "normal", None),
    ("GARCH-t", "Garch", 1, 1, "t", None),
    ("GJR-t", "Garch", 1, 1, "t", 1),
    ("EWMA(0.94)", None, None, None, None, None),  # Special case
    ("EWMA(0.97)", None, None, None, None, None),
]

results = {}

for model_name, vol_type, p, q, dist, o in models_config:
    print(f"\n  Fitting {model_name}...")

    if model_name.startswith("EWMA"):
        # EWMA — compute manually
        lam = float(model_name.split("(")[1].rstrip(")"))
        oos_data = idx_ret_pct[oos_mask]

        # Initialize with full-sample variance
        var_t = idx_ret_pct[is_mask].var()
        forecasts = []
        for t in oos_data.index:
            forecasts.append(var_t)
            r_t = idx_ret_pct.loc[t]
            var_t = lam * var_t + (1 - lam) * r_t ** 2

        oos_forecasts = pd.Series(forecasts, index=oos_data.index)
        oos_realized = oos_data ** 2  # squared return as realized var proxy

        ql = qlike_loss(oos_realized.values, oos_forecasts.values)
        results[model_name] = {
            "qlike": ql,
            "forecasts": oos_forecasts,
            "realized": oos_realized,
            "gamma": None,
        }
        print(f"    QLIKE={ql:.4f}")
        continue

    try:
        # Expanding window OOS forecasts
        oos_dates = idx_ret_pct[oos_mask].index
        forecasts = []

        # Use rolling window of 500 days minimum
        min_window = 500

        for i, date in enumerate(oos_dates):
            # All data up to (not including) this date
            train_end_loc = idx_ret_pct.index.get_loc(date)
            if train_end_loc < min_window:
                forecasts.append(np.nan)
                continue

            train_data = idx_ret_pct.iloc[max(0, train_end_loc - 2000):train_end_loc]

            try:
                if o is not None:
                    am = arch_model(train_data, vol=vol_type, p=p, o=o, q=q, dist=dist, mean="Constant")
                else:
                    am = arch_model(train_data, vol=vol_type, p=p, q=q, dist=dist, mean="Constant")

                res = am.fit(disp="off", show_warning=False)
                fcast = res.forecast(horizon=1)
                forecasts.append(fcast.variance.values[-1, 0])

                # Extract gamma for first fit
                if i == 0 and model_name in ("GJR-GARCH", "GJR-t"):
                    gamma = res.params.get("gamma[1]", np.nan)
                    print(f"    gamma = {gamma:.4f}")
            except Exception:
                forecasts.append(np.nan)

        oos_forecasts = pd.Series(forecasts, index=oos_dates)
        oos_realized = idx_ret_pct[oos_mask] ** 2

        # Remove NaNs
        valid = oos_forecasts.notna() & oos_realized.notna() & (oos_forecasts > 0)
        oos_f = oos_forecasts[valid]
        oos_r = oos_realized[valid]

        ql = qlike_loss(oos_r.values, oos_f.values)

        # Get gamma from last fit for GJR
        gamma_val = None
        if model_name in ("GJR-GARCH", "GJR-t"):
            try:
                # Re-fit on full IS for parameter reporting
                if o is not None:
                    am_full = arch_model(idx_ret_pct[is_mask], vol=vol_type, p=p, o=o, q=q, dist=dist, mean="Constant")
                else:
                    am_full = arch_model(idx_ret_pct[is_mask], vol=vol_type, p=p, q=q, dist=dist, mean="Constant")
                res_full = am_full.fit(disp="off", show_warning=False)
                gamma_val = res_full.params.get("gamma[1]", None)
            except Exception:
                pass

        results[model_name] = {
            "qlike": ql,
            "forecasts": oos_f,
            "realized": oos_r,
            "gamma": gamma_val,
        }
        print(f"    QLIKE={ql:.4f}, valid OOS days={len(oos_f)}")

    except Exception as e:
        print(f"    FAILED: {e}")
        results[model_name] = {"qlike": np.nan, "forecasts": None, "realized": None, "gamma": None}

# ─── 8. Model Comparison ─────────────────────────────────────────
print("\n" + "=" * 80)
print("[8] Model Comparison — QLIKE Rankings & DM Tests")
print("=" * 80)

# Sort by QLIKE
ranked = sorted(results.items(), key=lambda x: x[1]["qlike"] if np.isfinite(x[1]["qlike"]) else 999)

print(f"\n  {'Rank':<5} {'Model':<15} {'QLIKE':<10} {'gamma':<10}")
print(f"  {'─' * 5} {'─' * 15} {'─' * 10} {'─' * 10}")
for rank, (name, res) in enumerate(ranked, 1):
    gamma_str = f"{res['gamma']:.4f}" if res['gamma'] is not None else "—"
    ql_str = f"{res['qlike']:.4f}" if np.isfinite(res['qlike']) else "FAILED"
    print(f"  {rank:<5} {name:<15} {ql_str:<10} {gamma_str:<10}")

# DM test: best vs others
best_name, best_res = ranked[0]
print(f"\n  DM tests (best model: {best_name}):")

if best_res["forecasts"] is not None and best_res["realized"] is not None:
    best_loss = np.log(best_res["forecasts"].values) + best_res["realized"].values / best_res["forecasts"].values

    for name, res in ranked[1:]:
        if res["forecasts"] is not None and res["realized"] is not None:
            # Align
            common = best_res["forecasts"].index.intersection(res["forecasts"].index)
            if len(common) > 20:
                bl = np.log(best_res["forecasts"].reindex(common).values) + best_res["realized"].reindex(common).values / best_res["forecasts"].reindex(common).values
                ol = np.log(res["forecasts"].reindex(common).values) + res["realized"].reindex(common).values / res["forecasts"].reindex(common).values
                t_stat, p_val = dm_test(bl, ol)
                sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
                print(f"    {best_name} vs {name}: DM t={t_stat:.3f}, p={p_val:.4f} {sig}")

# ─── 9. ACF Analysis: Index vs BTC ───────────────────────────────
print("\n" + "=" * 80)
print("[9] ACF Analysis: Crypto Index vs BTC (Vol Clustering)")
print("=" * 80)

for name, ret in [("CryptoIndex", index_returns), ("BTC", btc_returns), ("ETH", eth_returns)]:
    r = ret.dropna()
    r2 = r ** 2
    abs_r = r.abs()

    acf_lags = [1, 5, 10, 22]
    print(f"\n  {name}:")
    print(f"    {'Lag':<6} {'ACF(r)':<12} {'ACF(r²)':<12} {'ACF(|r|)':<12}")
    for lag in acf_lags:
        acf_r = r.autocorr(lag=lag)
        acf_r2 = r2.autocorr(lag=lag)
        acf_abs = abs_r.autocorr(lag=lag)
        print(f"    {lag:<6} {acf_r:<12.4f} {acf_r2:<12.4f} {acf_abs:<12.4f}")

# ─── 10. Compare GARCH: Crypto Index vs BTC ──────────────────────
print("\n" + "=" * 80)
print("[10] GARCH Comparison: Crypto Index vs BTC-only")
print("=" * 80)

# Fit GARCH(1,1) on BTC for OOS comparison
print("  Fitting GARCH(1,1) on BTC OOS...")
btc_oos_dates = btc_ret_pct[btc_ret_pct.index >= OOS_START].index
btc_forecasts = []
for date in btc_oos_dates:
    loc = btc_ret_pct.index.get_loc(date)
    if loc < 500:
        btc_forecasts.append(np.nan)
        continue
    train = btc_ret_pct.iloc[max(0, loc - 2000):loc]
    try:
        am = arch_model(train, vol="Garch", p=1, q=1, dist="normal", mean="Constant")
        res = am.fit(disp="off", show_warning=False)
        fcast = res.forecast(horizon=1)
        btc_forecasts.append(fcast.variance.values[-1, 0])
    except:
        btc_forecasts.append(np.nan)

btc_oos_f = pd.Series(btc_forecasts, index=btc_oos_dates)
btc_oos_r = btc_ret_pct[btc_ret_pct.index >= OOS_START] ** 2
valid_btc = btc_oos_f.notna() & btc_oos_r.notna() & (btc_oos_f > 0)
btc_ql = qlike_loss(btc_oos_r[valid_btc].values, btc_oos_f[valid_btc].values)

# Find best crypto index GARCH QLIKE
idx_best_ql = ranked[0][1]["qlike"] if ranked else np.nan
idx_best_name = ranked[0][0] if ranked else "N/A"

print(f"\n  BTC GARCH(1,1) OOS QLIKE: {btc_ql:.4f}")
print(f"  Crypto Index best ({idx_best_name}) OOS QLIKE: {idx_best_ql:.4f}")
if np.isfinite(btc_ql) and np.isfinite(idx_best_ql):
    print(f"  Difference: {idx_best_ql - btc_ql:+.4f}")
    if idx_best_ql < btc_ql:
        print(f"  → Index GARCH easier to forecast (lower QLIKE)")
    else:
        print(f"  → BTC GARCH easier to forecast")

# ─── 11. Crypto-VIX Relationship ─────────────────────────────────
print("\n" + "=" * 80)
print("[11] Crypto-VIX Relationship")
print("=" * 80)

# Does VIX predict crypto vol?
crypto_rv22 = index_returns.rolling(22).std() * np.sqrt(365)
vix_aligned = vix.reindex(crypto_rv22.index)

both_valid = crypto_rv22.notna() & vix_aligned.notna()
corr_vix_cryptovol = crypto_rv22[both_valid].corr(vix_aligned[both_valid])
print(f"  Correlation(VIX, CryptoIndex 22d RV): {corr_vix_cryptovol:.3f}")

# Year by year
print(f"\n  Year-by-year VIX vs Crypto RV correlation:")
for year in sorted(aligned.index.year.unique()):
    mask = (crypto_rv22.index.year == year) & both_valid
    if mask.sum() > 20:
        c = crypto_rv22[mask].corr(vix_aligned[mask])
        print(f"    {year}: {c:.3f}")

# Can VIX be used for crypto VT? (like it works for equities)
print(f"\n  Can VIX serve as crypto vol proxy?")
# Regression: crypto_rv = a + b * VIX
from numpy.polynomial.polynomial import polyfit
x = vix_aligned[both_valid].values
y = (crypto_rv22[both_valid] * 100).values  # annualized %
if len(x) > 30:
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot
    print(f"    Regression: CryptoRV = {intercept:.2f} + {slope:.2f} * VIX")
    print(f"    R² = {r2:.4f}")
    print(f"    → VIX explains {r2:.1%} of crypto vol variation")

# ─── 12. Tail Risk Analysis ──────────────────────────────────────
print("\n" + "=" * 80)
print("[12] Tail Risk: Index vs BTC")
print("=" * 80)

for name, ret in [("CryptoIndex", index_returns), ("BTC", btc_returns)]:
    r = ret.dropna()
    p1 = np.percentile(r, 1)
    p5 = np.percentile(r, 5)
    p95 = np.percentile(r, 95)
    p99 = np.percentile(r, 99)

    # Worst 5 days
    worst5 = r.nsmallest(5)

    print(f"\n  {name}:")
    print(f"    VaR(1%): {p1:.4f} ({p1*100:.2f}%)")
    print(f"    VaR(5%): {p5:.4f} ({p5*100:.2f}%)")
    print(f"    CVaR(5%): {r[r <= p5].mean():.4f} ({r[r <= p5].mean()*100:.2f}%)")
    print(f"    99th percentile: {p99:.4f}")
    print(f"    Worst 5 days:")
    for dt, val in worst5.items():
        print(f"      {dt.date()}: {val:.4f} ({val*100:.2f}%)")

# Diversification benefit in tails
idx_var5 = np.percentile(index_returns.dropna(), 5)
btc_var5 = np.percentile(btc_returns.dropna(), 5)
print(f"\n  Tail risk reduction (VaR 5%):")
print(f"    BTC VaR(5%): {btc_var5:.4f}")
print(f"    Index VaR(5%): {idx_var5:.4f}")
print(f"    Reduction: {(1 - idx_var5/btc_var5):.1%}")

# ─── 13. Summary & JSON Output ───────────────────────────────────
print("\n" + "=" * 80)
print("[13] SUMMARY")
print("=" * 80)

# Collect key findings
summary = {
    "experiment": "K398",
    "title": "Total Crypto Market Volatility — Beyond BTC",
    "data_source": "yfinance",
    "period": f"{ret_df.index[0].date()} to {ret_df.index[-1].date()}",
    "oos_period": f"{OOS_START} to {ret_df.index[-1].date()}",
    "n_observations": len(ret_df),
    "crypto_assets": crypto_available,
    "weights": norm_weights,
    "findings": {},
}

# Finding 1: Intra-crypto diversification
summary["findings"]["intra_crypto_diversification"] = {
    "index_ann_vol": float(stats_table[0]["ann_vol"]),
    "btc_ann_vol": float(stats_table[1]["ann_vol"]),
    "vol_ratio_mean": float(vol_ratio_clean.mean()),
    "vol_reduction": float(vol_reduction),
    "pct_days_index_lower": float((vol_ratio_clean < 1).mean()),
}

# Finding 2: Crypto cycle vol
cycle_stats = {}
for phase in ["Bull", "Accumulation", "Bear"]:
    mask = cycle_phase == phase
    if mask.sum() > 0:
        cycle_stats[phase] = {
            "n_days": int(mask.sum()),
            "pct": float(mask.mean()),
            "index_ann_vol": float(index_returns[mask].std() * np.sqrt(365)),
            "btc_ann_vol": float(btc_returns[mask].std() * np.sqrt(365)),
        }
summary["findings"]["crypto_cycles"] = cycle_stats

# Finding 3: Crypto-SPY correlation
summary["findings"]["crypto_spy_correlation"] = {
    "full_sample": float(full_corr),
    "pre_2022": float(pre_corr) if 'pre_corr' in dir() else None,
    "post_2022": float(post_corr) if 'post_corr' in dir() else None,
}

# Finding 4: GARCH results
garch_results = {}
for name, res in ranked:
    garch_results[name] = {
        "qlike": float(res["qlike"]) if np.isfinite(res["qlike"]) else None,
        "gamma": float(res["gamma"]) if res["gamma"] is not None else None,
    }
summary["findings"]["garch_models"] = garch_results

# Finding 5: ACF analysis
idx_r2 = index_returns.dropna() ** 2
btc_r2 = btc_returns.dropna() ** 2
summary["findings"]["vol_clustering"] = {
    "index_acf1_sq": float(idx_r2.autocorr(lag=1)),
    "btc_acf1_sq": float(btc_r2.autocorr(lag=1)),
    "index_acf5_sq": float(idx_r2.autocorr(lag=5)),
    "btc_acf5_sq": float(btc_r2.autocorr(lag=5)),
}

# Finding 6: VIX relationship
summary["findings"]["vix_crypto"] = {
    "corr_vix_cryptoRV": float(corr_vix_cryptovol),
    "regression_r2": float(r2) if 'r2' in dir() else None,
}

# Save results
output_path = "experiments/k398_total_crypto_results.json"
with open(output_path, "w") as f:
    json.dump(summary, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

# Print key conclusions
print(f"\n{'─' * 80}")
print("KEY CONCLUSIONS:")
print(f"{'─' * 80}")
print(f"1. Intra-crypto diversification: vol reduced by {vol_reduction:.1%}")
print(f"   (Index vol / BTC vol = {vol_ratio_clean.mean():.3f})")
print(f"2. Index ACF(1) of r²: {idx_r2.autocorr(lag=1):.3f} vs BTC: {btc_r2.autocorr(lag=1):.3f}")
print(f"   → {'Stronger' if idx_r2.autocorr(lag=1) > btc_r2.autocorr(lag=1) else 'Weaker'} vol clustering in index")
print(f"3. Best GARCH model for crypto index: {ranked[0][0]} (QLIKE={ranked[0][1]['qlike']:.4f})")
if ranked[0][1]["gamma"] is not None:
    gamma = ranked[0][1]["gamma"]
    print(f"   gamma={gamma:.4f} → {'NO' if abs(gamma) < 0.05 else 'YES'} leverage effect")
print(f"4. Crypto-SPY correlation: {full_corr:.3f}")
if 'pre_corr' in dir() and 'post_corr' in dir():
    print(f"   Pre-2022: {pre_corr:.3f} → Post-2022: {post_corr:.3f}")
print(f"5. VIX-CryptoRV correlation: {corr_vix_cryptovol:.3f}")
if 'r2' in dir():
    print(f"   VIX R² for crypto vol: {r2:.4f} → {'Useful' if r2 > 0.10 else 'NOT useful'} as proxy")
print(f"6. Bear/Bull vol asymmetry: {bear_vol/bull_vol:.2f}x")

print("\n" + "=" * 80)
print("K398 COMPLETE")
print("=" * 80)
