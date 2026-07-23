"""
Kurtosis Collapse vs Correlation Asymmetry Analysis
====================================================
Tests whether the kurtosis reduction from volatility targeting is related to
correlation asymmetry (Ang-Chen style: down-correlation vs up-correlation with SPY).

Hypothesis: Stocks with higher correlation asymmetry (more correlated on down days)
should show different kurtosis reduction patterns under VT, because the conditional
vol structure differs between up and down markets.
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import statsmodels.api as sm
from datetime import datetime

# ============================================================
# Configuration
# ============================================================
TICKERS = ["SPY", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "UNH", "JNJ"]
START_DATE = "2004-01-01"
END_DATE = "2025-12-31"
OOS_START = "2020-01-01"
OOS_END = "2025-12-31"
WINDOW = 2000  # Rolling estimation window
TARGET_VOL = 0.12  # 12% annualized
MAX_LEVERAGE = 1.5  # Cap weight at 150%
ANNUALIZE = np.sqrt(252)

print("=" * 80)
print("Kurtosis Collapse vs Correlation Asymmetry Analysis")
print("=" * 80)
print(f"Tickers: {TICKERS}")
print(f"Data: {START_DATE} to {END_DATE}, OOS: {OOS_START} to {OOS_END}")
print(f"GARCH window: {WINDOW}, Target vol: {TARGET_VOL*100}%, Max leverage: {MAX_LEVERAGE*100}%")
print()

# ============================================================
# 1. Download data
# ============================================================
print("Downloading data...")
data = yf.download(TICKERS, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
prices = data["Close"]
# Handle MultiIndex columns if needed
if isinstance(prices.columns, pd.MultiIndex):
    prices.columns = prices.columns.droplevel(1)
prices = prices.dropna()

returns = np.log(prices / prices.shift(1)).dropna()
print(f"  Prices shape: {prices.shape}")
print(f"  Returns shape: {returns.shape}")
print(f"  Date range: {returns.index[0].date()} to {returns.index[-1].date()}")
print()

# ============================================================
# 2. Rolling GJR-GARCH(1,1) forecasts + VT returns
# ============================================================
def rolling_gjr_garch_forecast(ret_series, window=2000, oos_start="2020-01-01"):
    """
    Rolling GJR-GARCH(1,1) 1-step-ahead volatility forecasts.
    Returns: DataFrame with columns [date, return, forecast_vol, vt_return]
    """
    ret = ret_series.dropna()
    oos_mask = ret.index >= pd.Timestamp(oos_start)
    oos_dates = ret.index[oos_mask]

    forecasts = []

    for i, date in enumerate(oos_dates):
        idx = ret.index.get_loc(date)
        if idx < window:
            continue

        train = ret.iloc[idx - window:idx] * 100  # Scale to percentage for arch

        try:
            model = arch_model(train, vol="GARCH", p=1, o=1, q=1, dist="t", mean="Zero")
            result = model.fit(disp="off", show_warning=False)
            fcast = result.forecast(horizon=1)
            sigma2 = fcast.variance.iloc[-1, 0]
            sigma_daily = np.sqrt(sigma2) / 100  # Back to decimal
        except Exception:
            # Fallback: use realized vol
            sigma_daily = ret.iloc[idx - 60:idx].std()

        sigma_ann = sigma_daily * ANNUALIZE
        weight = min(TARGET_VOL / sigma_ann, MAX_LEVERAGE) if sigma_ann > 0 else 1.0

        r = ret.iloc[idx]
        vt_r = weight * r

        forecasts.append({
            "date": date,
            "return": r,
            "forecast_vol_ann": sigma_ann,
            "weight": weight,
            "vt_return": vt_r,
            "sigma_daily": sigma_daily,
        })

        if (i + 1) % 200 == 0:
            print(f"    ... {i+1}/{len(oos_dates)} forecasts done")

    return pd.DataFrame(forecasts).set_index("date")


print("Running rolling GJR-GARCH forecasts for each ticker...")
print("-" * 60)

results = {}
spy_returns_oos = None

for ticker in TICKERS:
    print(f"\n  [{ticker}] Starting GJR-GARCH rolling forecasts...")
    if ticker not in returns.columns:
        print(f"  [{ticker}] SKIPPED - no data")
        continue

    df = rolling_gjr_garch_forecast(returns[ticker], window=WINDOW, oos_start=OOS_START)

    if len(df) == 0:
        print(f"  [{ticker}] SKIPPED - insufficient data")
        continue

    results[ticker] = df
    print(f"  [{ticker}] Done: {len(df)} forecasts, "
          f"mean weight={df['weight'].mean():.2f}, "
          f"raw_kurt={stats.kurtosis(df['return'], fisher=True):.2f}, "
          f"vt_kurt={stats.kurtosis(df['vt_return'], fisher=True):.2f}")

    if ticker == "SPY":
        spy_returns_oos = df["return"]

print("\n" + "=" * 80)

# ============================================================
# 3. Compute metrics for each stock
# ============================================================
print("\nComputing metrics...")

metrics = []

for ticker in TICKERS:
    if ticker not in results:
        continue

    df = results[ticker]
    raw_ret = df["return"].values
    vt_ret = df["vt_return"].values

    # 3a. Kurtosis (excess kurtosis, Fisher=True)
    raw_kurt = stats.kurtosis(raw_ret, fisher=True)
    vt_kurt = stats.kurtosis(vt_ret, fisher=True)
    kurt_reduction_pct = (raw_kurt - vt_kurt) / abs(raw_kurt) * 100 if raw_kurt != 0 else 0

    # 3b. Ang-Chen asymmetric correlation with SPY
    if ticker == "SPY":
        # For SPY itself, use autocorrelation-based asymmetry or set to baseline
        corr_down = 1.0
        corr_up = 1.0
        corr_asymmetry = 0.0
    else:
        # Align dates
        common_idx = df.index.intersection(results["SPY"].index)
        stock_ret = df.loc[common_idx, "return"]
        spy_ret = results["SPY"].loc[common_idx, "return"]

        # Down days: SPY return < 0
        down_mask = spy_ret < 0
        up_mask = spy_ret >= 0

        if down_mask.sum() > 30 and up_mask.sum() > 30:
            corr_down = np.corrcoef(stock_ret[down_mask], spy_ret[down_mask])[0, 1]
            corr_up = np.corrcoef(stock_ret[up_mask], spy_ret[up_mask])[0, 1]
            corr_asymmetry = corr_down - corr_up  # Positive = more correlated on down days
        else:
            corr_down = corr_up = corr_asymmetry = np.nan

    # 3c. Vol-of-vol (std of rolling GARCH sigma series, annualized)
    vol_of_vol = df["forecast_vol_ann"].std()
    mean_vol = df["forecast_vol_ann"].mean()
    vol_of_vol_ratio = vol_of_vol / mean_vol if mean_vol > 0 else 0  # Normalized

    # 3d. Additional metrics
    skew_raw = stats.skew(raw_ret)
    skew_vt = stats.skew(vt_ret)
    mean_weight = df["weight"].mean()
    pct_capped = (df["weight"] >= MAX_LEVERAGE * 0.99).mean() * 100

    metrics.append({
        "ticker": ticker,
        "raw_kurtosis": raw_kurt,
        "vt_kurtosis": vt_kurt,
        "kurt_reduction_pct": kurt_reduction_pct,
        "corr_down": corr_down,
        "corr_up": corr_up,
        "corr_asymmetry": corr_asymmetry,
        "vol_of_vol": vol_of_vol,
        "vol_of_vol_ratio": vol_of_vol_ratio,
        "mean_vol": mean_vol,
        "skew_raw": skew_raw,
        "skew_vt": skew_vt,
        "mean_weight": mean_weight,
        "pct_capped": pct_capped,
    })

metrics_df = pd.DataFrame(metrics).set_index("ticker")

# ============================================================
# 4. Summary table
# ============================================================
print("\n" + "=" * 80)
print("SUMMARY TABLE: Kurtosis, Correlation Asymmetry, Vol-of-Vol")
print("=" * 80)

display_cols = ["raw_kurtosis", "vt_kurtosis", "kurt_reduction_pct",
                "corr_down", "corr_up", "corr_asymmetry",
                "vol_of_vol_ratio", "mean_vol", "mean_weight", "pct_capped"]

print(metrics_df[display_cols].round(3).to_string())

print("\n" + "-" * 80)
print("Key:")
print("  raw_kurtosis    = Excess kurtosis of raw log returns (OOS period)")
print("  vt_kurtosis     = Excess kurtosis of vol-targeted returns")
print("  kurt_reduction   = % reduction in kurtosis from VT")
print("  corr_down/up    = Correlation with SPY on down/up days")
print("  corr_asymmetry  = corr_down - corr_up (positive = more correlated when market falls)")
print("  vol_of_vol_ratio = Std(GARCH sigma) / Mean(GARCH sigma)")
print("  pct_capped      = % of days weight was at max leverage cap")

# ============================================================
# 5. Cross-sectional regressions (exclude SPY since it's the benchmark)
# ============================================================
print("\n" + "=" * 80)
print("CROSS-SECTIONAL REGRESSIONS")
print("=" * 80)

reg_df = metrics_df.drop("SPY", errors="ignore").dropna()

if len(reg_df) >= 5:
    # Regression 1: kurt_reduction ~ corr_asymmetry
    print("\n--- Regression 1: Kurt_Reduction ~ Corr_Asymmetry ---")
    Y = reg_df["kurt_reduction_pct"]
    X1 = sm.add_constant(reg_df["corr_asymmetry"])
    model1 = sm.OLS(Y, X1).fit()
    print(model1.summary2().tables[1].to_string())
    print(f"\n  R² = {model1.rsquared:.4f}, Adj-R² = {model1.rsquared_adj:.4f}")
    print(f"  F-stat = {model1.fvalue:.3f}, p(F) = {model1.f_pvalue:.4f}")

    # Regression 2: kurt_reduction ~ corr_asymmetry + vol_of_vol_ratio
    print("\n--- Regression 2: Kurt_Reduction ~ Corr_Asymmetry + Vol_of_Vol ---")
    X2 = sm.add_constant(reg_df[["corr_asymmetry", "vol_of_vol_ratio"]])
    model2 = sm.OLS(Y, X2).fit()
    print(model2.summary2().tables[1].to_string())
    print(f"\n  R² = {model2.rsquared:.4f}, Adj-R² = {model2.rsquared_adj:.4f}")
    print(f"  F-stat = {model2.fvalue:.3f}, p(F) = {model2.f_pvalue:.4f}")

    # Regression 3: kurt_reduction ~ corr_asymmetry + vol_of_vol + mean_vol
    print("\n--- Regression 3: Kurt_Reduction ~ Corr_Asymmetry + Vol_of_Vol + Mean_Vol ---")
    X3 = sm.add_constant(reg_df[["corr_asymmetry", "vol_of_vol_ratio", "mean_vol"]])
    model3 = sm.OLS(Y, X3).fit()
    print(model3.summary2().tables[1].to_string())
    print(f"\n  R² = {model3.rsquared:.4f}, Adj-R² = {model3.rsquared_adj:.4f}")
    print(f"  F-stat = {model3.fvalue:.3f}, p(F) = {model3.f_pvalue:.4f}")

    # Regression 4: vt_kurtosis ~ corr_asymmetry + vol_of_vol
    print("\n--- Regression 4: VT_Kurtosis (level) ~ Corr_Asymmetry + Vol_of_Vol ---")
    Y4 = reg_df["vt_kurtosis"]
    X4 = sm.add_constant(reg_df[["corr_asymmetry", "vol_of_vol_ratio"]])
    model4 = sm.OLS(Y4, X4).fit()
    print(model4.summary2().tables[1].to_string())
    print(f"\n  R² = {model4.rsquared:.4f}, Adj-R² = {model4.rsquared_adj:.4f}")
    print(f"  F-stat = {model4.fvalue:.3f}, p(F) = {model4.f_pvalue:.4f}")

    # Correlation matrix
    print("\n--- Correlation Matrix (Cross-Sectional) ---")
    corr_cols = ["kurt_reduction_pct", "vt_kurtosis", "corr_asymmetry", "vol_of_vol_ratio", "mean_vol", "raw_kurtosis"]
    print(reg_df[corr_cols].corr().round(3).to_string())

    # Rank correlation (Spearman) - more robust with small N
    print("\n--- Spearman Rank Correlations ---")
    for col in ["corr_asymmetry", "vol_of_vol_ratio", "mean_vol"]:
        rho, pval = stats.spearmanr(reg_df["kurt_reduction_pct"], reg_df[col])
        print(f"  kurt_reduction vs {col:20s}: rho={rho:+.3f}, p={pval:.4f}")

else:
    print(f"  Only {len(reg_df)} valid stocks - need at least 5 for regression")

# ============================================================
# 6. SPY vs Individual Stocks Comparison
# ============================================================
print("\n" + "=" * 80)
print("SPY (INDEX) vs INDIVIDUAL STOCKS COMPARISON")
print("=" * 80)

spy_row = metrics_df.loc["SPY"] if "SPY" in metrics_df.index else None
stock_avg = reg_df.mean() if len(reg_df) > 0 else None

if spy_row is not None and stock_avg is not None:
    print(f"\n  {'Metric':<25s} {'SPY':>10s} {'Stock Avg':>12s} {'Stock Std':>12s}")
    print(f"  {'-'*60}")
    for col in ["raw_kurtosis", "vt_kurtosis", "kurt_reduction_pct", "vol_of_vol_ratio", "mean_vol"]:
        spy_val = spy_row[col]
        avg_val = stock_avg[col]
        std_val = reg_df[col].std()
        print(f"  {col:<25s} {spy_val:>10.3f} {avg_val:>12.3f} {std_val:>12.3f}")

    print(f"\n  Interpretation:")
    if spy_row["kurt_reduction_pct"] > stock_avg["kurt_reduction_pct"]:
        print(f"  → SPY has HIGHER kurtosis reduction ({spy_row['kurt_reduction_pct']:.1f}%) vs stock avg ({stock_avg['kurt_reduction_pct']:.1f}%)")
        print(f"  → Index VT benefits more from diversification + volatility clustering alignment")
    else:
        print(f"  → SPY has LOWER kurtosis reduction ({spy_row['kurt_reduction_pct']:.1f}%) vs stock avg ({stock_avg['kurt_reduction_pct']:.1f}%)")
        print(f"  → Individual stocks may have stronger volatility clustering that VT can exploit")

# ============================================================
# 7. Key Findings
# ============================================================
print("\n" + "=" * 80)
print("KEY FINDINGS")
print("=" * 80)

if len(reg_df) >= 5:
    # Check significance
    ca_coef = model2.params.get("corr_asymmetry", 0)
    ca_pval = model2.pvalues.get("corr_asymmetry", 1)
    vov_coef = model2.params.get("vol_of_vol_ratio", 0)
    vov_pval = model2.pvalues.get("vol_of_vol_ratio", 1)

    print(f"\n1. Correlation Asymmetry → Kurtosis Reduction:")
    print(f"   Coefficient: {ca_coef:+.2f}, p-value: {ca_pval:.4f}")
    if ca_pval < 0.1:
        direction = "MORE" if ca_coef > 0 else "LESS"
        print(f"   ✓ SIGNIFICANT (p<0.1): Higher corr asymmetry → {direction} kurtosis reduction")
    else:
        print(f"   ✗ NOT significant at 10% level")

    print(f"\n2. Vol-of-Vol → Kurtosis Reduction:")
    print(f"   Coefficient: {vov_coef:+.2f}, p-value: {vov_pval:.4f}")
    if vov_pval < 0.1:
        direction = "MORE" if vov_coef > 0 else "LESS"
        print(f"   ✓ SIGNIFICANT (p<0.1): Higher vol-of-vol → {direction} kurtosis reduction")
    else:
        print(f"   ✗ NOT significant at 10% level")

    print(f"\n3. Model R²: {model2.rsquared:.4f}")
    if model2.rsquared > 0.5:
        print(f"   → Corr asymmetry + vol-of-vol explain >{model2.rsquared*100:.0f}% of cross-sectional variation")
    else:
        print(f"   → Only {model2.rsquared*100:.0f}% explained — other factors dominate")

    # Check if corr_asymmetry explains index vs stock difference
    print(f"\n4. Does correlation asymmetry explain why SPY kurtosis reduction differs from stocks?")
    if spy_row is not None:
        spy_kurt_red = spy_row["kurt_reduction_pct"]
        stock_kurt_red = reg_df["kurt_reduction_pct"]
        print(f"   SPY kurtosis reduction: {spy_kurt_red:.1f}%")
        print(f"   Stock range: {stock_kurt_red.min():.1f}% to {stock_kurt_red.max():.1f}% (mean: {stock_kurt_red.mean():.1f}%)")

        # Stocks with high vs low corr asymmetry
        median_ca = reg_df["corr_asymmetry"].median()
        high_ca = reg_df[reg_df["corr_asymmetry"] > median_ca]["kurt_reduction_pct"].mean()
        low_ca = reg_df[reg_df["corr_asymmetry"] <= median_ca]["kurt_reduction_pct"].mean()
        print(f"   High corr-asymmetry stocks avg kurt reduction: {high_ca:.1f}%")
        print(f"   Low corr-asymmetry stocks avg kurt reduction: {low_ca:.1f}%")

print("\n" + "=" * 80)
print("Analysis complete.")
print("=" * 80)
