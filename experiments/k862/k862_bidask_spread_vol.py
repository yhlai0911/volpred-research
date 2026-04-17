"""
K862: Market Microstructure — OHLC Bid-Ask Spread as Volatility Predictor

Research Question:
    Does the Corwin-Schultz (2012) OHLC-estimated bid-ask spread predict
    next-day realized volatility? Does it add information beyond VIX?

Methodology:
    - Corwin & Schultz (2012) spread estimator from daily OHLC data
    - Univariate: r^2_{t+1} = a + b*S_t + e
    - Bivariate: r^2_{t+1} = a + b1*S_t + b2*VIX_t + e (incremental beyond VIX?)
    - HAR-S: HAR(1,5,22) + spread as extra regressor
    - Regime analysis: high-VIX vs low-VIX
    - Cross-asset: SPY, QQQ, 0050.TW
    - OOS evaluation: IS 70%, OOS 30%. QLIKE + DM test.

Data Sources:
    - yfinance: SPY, QQQ, 0050.TW (2010-01 to 2026-04)
    - VIX: ^VIX from yfinance

References:
    - Corwin, S.A. & Schultz, P. (2012) "A simple way to estimate bid-ask spreads
      from daily high and low prices" Journal of Finance, 67(2), 719-760.
    - Hasbrouck, J. (2009) "Trading Costs and Returns for US Equities" JF.
    - Abdi, F. & Ranaldo, A. (2017) "A Simple Estimation of Bid-Ask Spreads
      from Daily Close, High, and Low Prices" RFS, 30(12), 4437-4480.
    - Patton, A. (2011) "Volatility forecast comparison using imperfect proxies" JoE.
    - Harvey, C. (2016) "...and the Cross-Section of Expected Returns" RFS.

Error Log Rules Applied:
    - Sanity check: compute actual values, never hard-code
    - Harvey threshold |t| > 3.0 for significance claims
    - signal.shift(1): all predictors use strictly past data (lag enforced in code)
    - DM test: use from volpred.stats.model_evaluation import dm_test
    - 0050.TW: use from volpred.utils import clean_tw50_data

Author: [提出: Claude (跳躍式探索 — 市場微結構), 執行: Claude]
"""

import json
import warnings
import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from volpred.stats.model_evaluation import dm_test, spearman_corr
from volpred.utils import clean_tw50_data

warnings.filterwarnings("ignore")

RESULTS = {
    "experiment_id": "K862",
    "title": "Market Microstructure: OHLC Bid-Ask Spread as Volatility Predictor",
    "data_source": "yfinance (SPY, QQQ, 0050.TW, ^VIX)",
    "period": "2010-01 to 2026-04",
    "references": [
        "Corwin & Schultz (2012) Journal of Finance",
        "Abdi & Ranaldo (2017) RFS",
        "Patton (2011) JoE",
        "Harvey (2016) RFS",
    ],
    "methodology": "Corwin-Schultz OHLC spread estimator → vol prediction regressions",
    "assets": {},
}

# ============================================================
# 1. CORWIN-SCHULTZ SPREAD ESTIMATOR
# ============================================================

def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    """
    Corwin & Schultz (2012) bid-ask spread estimator from daily OHLC.

    Uses 2-day rolling windows:
        beta = sum of squared log(H/L) over 2 consecutive days
        gamma = squared log(2-day-high / 2-day-low)
        alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2)) - sqrt(gamma / (3 - 2*sqrt(2)))
        S = 2*(exp(alpha) - 1) / (1 + exp(alpha))

    Returns:
        Series of estimated spreads (same index as input, first value NaN).
    """
    log_hl = np.log(high / low)
    log_hl_sq = log_hl ** 2

    # beta: sum of squared log(H/L) for day t and t-1
    beta = log_hl_sq + log_hl_sq.shift(1)

    # gamma: 2-day high-low range
    high_2d = pd.concat([high, high.shift(1)], axis=1).max(axis=1)
    low_2d = pd.concat([low, low.shift(1)], axis=1).min(axis=1)
    gamma = (np.log(high_2d / low_2d)) ** 2

    # Constants
    k = 3 - 2 * np.sqrt(2)  # approx 0.1716

    # alpha
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)

    # Spread: S = 2*(exp(alpha) - 1) / (1 + exp(alpha))
    # Clamp alpha to avoid overflow; negative alpha → spread = 0
    alpha_clamped = alpha.clip(lower=0, upper=5)
    spread = 2 * (np.exp(alpha_clamped) - 1) / (1 + np.exp(alpha_clamped))

    # Set negative alpha to 0 spread (no information)
    spread[alpha < 0] = 0.0

    return spread


def qlike(actual: np.ndarray, predicted: np.ndarray) -> float:
    """QLIKE loss: mean(actual/predicted - log(actual/predicted) - 1).
    Patton (2011) proxy-robust loss. Lower is better."""
    a = np.asarray(actual, dtype=np.float64)
    p = np.asarray(predicted, dtype=np.float64)
    valid = (a > 0) & (p > 0) & np.isfinite(a) & np.isfinite(p)
    a, p = a[valid], p[valid]
    if len(a) < 10:
        return np.nan
    ratio = a / p
    return float(np.mean(ratio - np.log(ratio) - 1))


def ols_predict(X_train, y_train, X_test):
    """Simple OLS with intercept. Returns (coefficients, predictions, residuals_train)."""
    n_train = len(X_train)
    X_tr = np.column_stack([np.ones(n_train), X_train])
    X_te = np.column_stack([np.ones(len(X_test)), X_test])
    # OLS: beta = (X'X)^{-1} X'y
    try:
        beta = np.linalg.lstsq(X_tr, y_train, rcond=None)[0]
    except np.linalg.LinAlgError:
        beta = np.zeros(X_tr.shape[1])
    pred_train = X_tr @ beta
    pred_test = X_te @ beta
    return beta, pred_test, pred_train


def newey_west_tstat(X, y, lag=5):
    """OLS with Newey-West HAC standard errors. Returns t-stats and p-values for each coef."""
    n = len(y)
    k = X.shape[1]
    X_with_const = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_with_const, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return np.zeros(k + 1), np.ones(k + 1), np.zeros(k + 1)

    resid = y - X_with_const @ beta
    # Meat of sandwich
    S = np.zeros((k + 1, k + 1))
    for i in range(n):
        xi = X_with_const[i:i+1].T
        S += (resid[i] ** 2) * (xi @ xi.T)
    # Newey-West lags
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        for i in range(l, n):
            xi = X_with_const[i:i+1].T
            xj = X_with_const[i-l:i-l+1].T
            cross = resid[i] * resid[i-l] * (xi @ xj.T + xj @ xi.T)
            S += w * cross
    S /= n

    bread = np.linalg.inv(X_with_const.T @ X_with_const / n)
    V = bread @ S @ bread / n
    se = np.sqrt(np.diag(V).clip(min=1e-20))
    t_stats = beta / se
    p_vals = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n - k - 1))
    return t_stats, p_vals, beta


# ============================================================
# 2. DATA COLLECTION
# ============================================================
print("=" * 70)
print("K862: Market Microstructure — OHLC Bid-Ask Spread as Vol Predictor")
print("=" * 70)

start_date = "2010-01-01"
end_date = "2026-04-05"

print("\n[1] Downloading data...")

# Download OHLC data for SPY, QQQ
ohlc_data = {}
for ticker in ["SPY", "QQQ"]:
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    ohlc_data[ticker] = df[["Open", "High", "Low", "Close"]].copy()
    print(f"  {ticker}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Download 0050.TW
df_tw = yf.download("0050.TW", start=start_date, end=end_date, progress=False)
if isinstance(df_tw.columns, pd.MultiIndex):
    df_tw.columns = df_tw.columns.get_level_values(0)
# Clean split artifacts for Close (for returns), but keep OHLC for spread calc
tw_close = df_tw["Close"].squeeze()
tw_close_clean, tw_ret_clean = clean_tw50_data(tw_close)
# For OHLC, apply same logic: if pre-2014 data exists and ratio ~4x, divide
tw_ohlc = df_tw[["Open", "High", "Low", "Close"]].copy()
split_date = pd.Timestamp("2014-01-02")
if split_date in tw_ohlc.index:
    pre_mask = tw_ohlc.index < split_date
    if pre_mask.any():
        last_pre_close = tw_ohlc.loc[pre_mask, "Close"].iloc[-1]
        first_post_close = tw_ohlc.loc[split_date, "Close"]
        if isinstance(first_post_close, pd.Series):
            first_post_close = first_post_close.iloc[0]
        ratio = last_pre_close / first_post_close
        if 3.5 < ratio < 4.5:
            tw_ohlc.loc[pre_mask] = tw_ohlc.loc[pre_mask] / 4.0
ohlc_data["0050.TW"] = tw_ohlc
print(f"  0050.TW: {len(df_tw)} days (cleaned for split)")

# Download VIX
vix_df = yf.download("^VIX", start=start_date, end=end_date, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix = vix_df["Close"].squeeze()
vix.name = "VIX"
print(f"  VIX: {len(vix)} days")

# ============================================================
# 3. COMPUTE SPREAD AND VOLATILITY PROXIES FOR EACH ASSET
# ============================================================
print("\n[2] Computing Corwin-Schultz spread estimates...")

asset_results = {}

for asset_name, df_ohlc in ohlc_data.items():
    print(f"\n{'='*60}")
    print(f"  Processing: {asset_name}")
    print(f"{'='*60}")

    H = df_ohlc["High"].squeeze()
    L = df_ohlc["Low"].squeeze()
    C = df_ohlc["Close"].squeeze()

    # Returns
    ret = C.pct_change()

    # Raw Corwin-Schultz spread
    raw_spread = corwin_schultz_spread(H, L)

    # Smoothed spread (5-day rolling mean for stability)
    spread_5d = raw_spread.rolling(5, min_periods=3).mean()
    spread_22d = raw_spread.rolling(22, min_periods=10).mean()

    # Volatility proxies
    r_squared = ret ** 2  # squared return (noisy but unbiased proxy for sigma^2)
    abs_ret = ret.abs()   # |return|

    # HAR-style RV components (using r^2)
    rv_1 = r_squared  # daily
    rv_5 = r_squared.rolling(5, min_periods=3).mean()   # weekly
    rv_22 = r_squared.rolling(22, min_periods=10).mean() # monthly

    # Merge VIX (align on trading days)
    if asset_name == "0050.TW":
        # Taiwan market: use previous-day VIX (lag due to timezone)
        vix_aligned = vix.reindex(C.index, method="ffill").shift(1)
    else:
        vix_aligned = vix.reindex(C.index, method="ffill")

    # Build analysis DataFrame
    analysis = pd.DataFrame({
        "ret": ret,
        "r_sq": r_squared,
        "abs_ret": abs_ret,
        "spread_raw": raw_spread,
        "spread_5d": spread_5d,
        "spread_22d": spread_22d,
        "rv_1": rv_1,
        "rv_5": rv_5,
        "rv_22": rv_22,
        "vix": vix_aligned,
    }, index=C.index)

    analysis = analysis.dropna()
    n_obs = len(analysis)
    print(f"  Observations after dropna: {n_obs}")

    # ── DESCRIPTIVE STATISTICS ──
    print(f"\n  --- Descriptive Statistics ---")
    for col in ["spread_raw", "spread_5d", "r_sq", "abs_ret", "vix"]:
        s = analysis[col]
        print(f"  {col:12s}: mean={s.mean():.6f}  std={s.std():.6f}  "
              f"skew={s.skew():.2f}  kurt={s.kurtosis():.2f}  "
              f"min={s.min():.6f}  max={s.max():.6f}")

    # ── CORRELATION ANALYSIS ──
    print(f"\n  --- Correlations (contemporaneous) ---")
    corr_spread_vix = analysis["spread_5d"].corr(analysis["vix"])
    corr_spread_absret = analysis["spread_5d"].corr(analysis["abs_ret"])
    corr_spread_rsq = analysis["spread_5d"].corr(analysis["r_sq"])
    print(f"  spread_5d vs VIX:     {corr_spread_vix:.4f}")
    print(f"  spread_5d vs |ret|:   {corr_spread_absret:.4f}")
    print(f"  spread_5d vs r^2:     {corr_spread_rsq:.4f}")

    # ============================================================
    # 4. PREDICTIVE REGRESSIONS (with shift(1) — NO LOOKAHEAD)
    # ============================================================
    print(f"\n  --- Predictive Regressions (target = r^2_{{t+1}}) ---")

    # CRITICAL: shift(1) — predictor from yesterday, target from today
    # This means: spread_5d[t-1] predicts r_sq[t]
    target = analysis["r_sq"].values
    spread_lag = analysis["spread_5d"].shift(1).values  # ← signal.shift(1)
    vix_lag = analysis["vix"].shift(1).values            # ← signal.shift(1)
    rv1_lag = analysis["rv_1"].shift(1).values
    rv5_lag = analysis["rv_5"].shift(1).values
    rv22_lag = analysis["rv_22"].shift(1).values

    # Drop first row (NaN from shift)
    valid = np.isfinite(target) & np.isfinite(spread_lag) & np.isfinite(vix_lag) \
            & np.isfinite(rv1_lag) & np.isfinite(rv5_lag) & np.isfinite(rv22_lag)
    idx_valid = np.where(valid)[0]

    target_v = target[idx_valid]
    spread_v = spread_lag[idx_valid]
    vix_v = vix_lag[idx_valid]
    rv1_v = rv1_lag[idx_valid]
    rv5_v = rv5_lag[idx_valid]
    rv22_v = rv22_lag[idx_valid]

    n_valid = len(target_v)
    print(f"  Valid obs for regressions: {n_valid}")

    # Train/Test split: IS 70%, OOS 30%
    split_idx = int(n_valid * 0.70)
    print(f"  IS: {split_idx} obs, OOS: {n_valid - split_idx} obs")

    # Targets
    y_is = target_v[:split_idx]
    y_oos = target_v[split_idx:]

    # --- (a) Univariate: spread only ---
    X_spread_is = spread_v[:split_idx].reshape(-1, 1)
    X_spread_oos = spread_v[split_idx:].reshape(-1, 1)

    t_uni, p_uni, beta_uni = newey_west_tstat(X_spread_is, y_is, lag=10)
    _, pred_uni_oos, pred_uni_is = ols_predict(X_spread_is, y_is, X_spread_oos)
    pred_uni_oos = np.clip(pred_uni_oos, 1e-10, None)

    print(f"\n  (a) Univariate: r^2_{{t+1}} = a + b*spread_t")
    print(f"      b(spread)  = {beta_uni[1]:.6f}, t = {t_uni[1]:.3f}, p = {p_uni[1]:.4f}")
    print(f"      IS R^2     = {1 - np.sum((y_is - pred_uni_is)**2)/np.sum((y_is - y_is.mean())**2):.4f}")

    # --- (b) Bivariate: spread + VIX ---
    X_bi_is = np.column_stack([spread_v[:split_idx], vix_v[:split_idx]])
    X_bi_oos = np.column_stack([spread_v[split_idx:], vix_v[split_idx:]])

    t_bi, p_bi, beta_bi = newey_west_tstat(X_bi_is, y_is, lag=10)
    _, pred_bi_oos, pred_bi_is = ols_predict(X_bi_is, y_is, X_bi_oos)
    pred_bi_oos = np.clip(pred_bi_oos, 1e-10, None)

    print(f"\n  (b) Bivariate: r^2_{{t+1}} = a + b1*spread_t + b2*VIX_t")
    print(f"      b(spread)  = {beta_bi[1]:.6f}, t = {t_bi[1]:.3f}, p = {p_bi[1]:.4f}")
    print(f"      b(VIX)     = {beta_bi[2]:.6f}, t = {t_bi[2]:.3f}, p = {p_bi[2]:.4f}")

    # --- (c) VIX only (benchmark) ---
    X_vix_is = vix_v[:split_idx].reshape(-1, 1)
    X_vix_oos = vix_v[split_idx:].reshape(-1, 1)

    t_vix, p_vix, beta_vix = newey_west_tstat(X_vix_is, y_is, lag=10)
    _, pred_vix_oos, _ = ols_predict(X_vix_is, y_is, X_vix_oos)
    pred_vix_oos = np.clip(pred_vix_oos, 1e-10, None)

    print(f"\n  (c) VIX-only benchmark: r^2_{{t+1}} = a + b*VIX_t")
    print(f"      b(VIX)     = {beta_vix[1]:.6f}, t = {t_vix[1]:.3f}, p = {p_vix[1]:.4f}")

    # --- (d) HAR(1,5,22) baseline ---
    X_har_is = np.column_stack([rv1_v[:split_idx], rv5_v[:split_idx], rv22_v[:split_idx]])
    X_har_oos = np.column_stack([rv1_v[split_idx:], rv5_v[split_idx:], rv22_v[split_idx:]])

    t_har, p_har, beta_har = newey_west_tstat(X_har_is, y_is, lag=10)
    _, pred_har_oos, _ = ols_predict(X_har_is, y_is, X_har_oos)
    pred_har_oos = np.clip(pred_har_oos, 1e-10, None)

    print(f"\n  (d) HAR(1,5,22) baseline: r^2_{{t+1}} = a + b1*RV1 + b2*RV5 + b3*RV22")
    print(f"      b(RV1)  = {beta_har[1]:.6f}, t = {t_har[1]:.3f}")
    print(f"      b(RV5)  = {beta_har[2]:.6f}, t = {t_har[2]:.3f}")
    print(f"      b(RV22) = {beta_har[3]:.6f}, t = {t_har[3]:.3f}")

    # --- (e) HAR + spread (HAR-S) ---
    X_hars_is = np.column_stack([rv1_v[:split_idx], rv5_v[:split_idx],
                                  rv22_v[:split_idx], spread_v[:split_idx]])
    X_hars_oos = np.column_stack([rv1_v[split_idx:], rv5_v[split_idx:],
                                   rv22_v[split_idx:], spread_v[split_idx:]])

    t_hars, p_hars, beta_hars = newey_west_tstat(X_hars_is, y_is, lag=10)
    _, pred_hars_oos, _ = ols_predict(X_hars_is, y_is, X_hars_oos)
    pred_hars_oos = np.clip(pred_hars_oos, 1e-10, None)

    print(f"\n  (e) HAR-S: HAR(1,5,22) + spread")
    print(f"      b(RV1)    = {beta_hars[1]:.6f}, t = {t_hars[1]:.3f}")
    print(f"      b(RV5)    = {beta_hars[2]:.6f}, t = {t_hars[2]:.3f}")
    print(f"      b(RV22)   = {beta_hars[3]:.6f}, t = {t_hars[3]:.3f}")
    print(f"      b(spread) = {beta_hars[4]:.6f}, t = {t_hars[4]:.3f}, p = {p_hars[4]:.4f}")

    # ============================================================
    # 5. OOS EVALUATION: QLIKE + DM Test
    # ============================================================
    print(f"\n  --- OOS Evaluation ---")

    # Compute QLIKE for each model
    ql_uni = qlike(y_oos, pred_uni_oos)
    ql_bi = qlike(y_oos, pred_bi_oos)
    ql_vix = qlike(y_oos, pred_vix_oos)
    ql_har = qlike(y_oos, pred_har_oos)
    ql_hars = qlike(y_oos, pred_hars_oos)

    # Historical mean as naive benchmark
    hist_mean = np.full_like(y_oos, y_is.mean())
    ql_naive = qlike(y_oos, hist_mean)

    print(f"  QLIKE (lower=better):")
    print(f"    Naive (hist mean): {ql_naive:.6f}")
    print(f"    Spread only:       {ql_uni:.6f}")
    print(f"    VIX only:          {ql_vix:.6f}")
    print(f"    Spread + VIX:      {ql_bi:.6f}")
    print(f"    HAR(1,5,22):       {ql_har:.6f}")
    print(f"    HAR-S (+spread):   {ql_hars:.6f}")

    # DM tests: compare HAR-S vs HAR (does spread help?)
    loss_har = y_oos / pred_har_oos - np.log(y_oos / pred_har_oos) - 1
    loss_hars = y_oos / pred_hars_oos - np.log(y_oos / pred_hars_oos) - 1
    loss_vix = y_oos / pred_vix_oos - np.log(y_oos / pred_vix_oos) - 1
    loss_bi = y_oos / pred_bi_oos - np.log(y_oos / pred_bi_oos) - 1
    loss_uni = y_oos / pred_uni_oos - np.log(y_oos / pred_uni_oos) - 1
    loss_naive = y_oos / hist_mean - np.log(y_oos / hist_mean) - 1

    dm_hars_vs_har = dm_test(loss_hars, loss_har)
    dm_bi_vs_vix = dm_test(loss_bi, loss_vix)
    dm_uni_vs_naive = dm_test(loss_uni, loss_naive)
    dm_har_vs_naive = dm_test(loss_har, loss_naive)

    print(f"\n  DM tests (QLIKE loss, negative t → model 1 better):")
    print(f"    HAR-S vs HAR:        t = {dm_hars_vs_har[0]:+.3f}, p = {dm_hars_vs_har[1]:.4f}")
    print(f"    Spread+VIX vs VIX:   t = {dm_bi_vs_vix[0]:+.3f}, p = {dm_bi_vs_vix[1]:.4f}")
    print(f"    Spread vs Naive:     t = {dm_uni_vs_naive[0]:+.3f}, p = {dm_uni_vs_naive[1]:.4f}")
    print(f"    HAR vs Naive:        t = {dm_har_vs_naive[0]:+.3f}, p = {dm_har_vs_naive[1]:.4f}")

    # Spearman rank correlation (OOS)
    sp_uni = spearman_corr(y_oos, pred_uni_oos)
    sp_vix = spearman_corr(y_oos, pred_vix_oos)
    sp_bi = spearman_corr(y_oos, pred_bi_oos)
    sp_har = spearman_corr(y_oos, pred_har_oos)
    sp_hars = spearman_corr(y_oos, pred_hars_oos)

    print(f"\n  Spearman rank correlation (OOS, actual vs predicted):")
    print(f"    Spread only:     rho = {sp_uni[0]:.4f}, p = {sp_uni[1]:.4f}")
    print(f"    VIX only:        rho = {sp_vix[0]:.4f}, p = {sp_vix[1]:.4f}")
    print(f"    Spread + VIX:    rho = {sp_bi[0]:.4f}, p = {sp_bi[1]:.4f}")
    print(f"    HAR(1,5,22):     rho = {sp_har[0]:.4f}, p = {sp_har[1]:.4f}")
    print(f"    HAR-S (+spread): rho = {sp_hars[0]:.4f}, p = {sp_hars[1]:.4f}")

    # ============================================================
    # 6. REGIME ANALYSIS: High-VIX vs Low-VIX
    # ============================================================
    print(f"\n  --- Regime Analysis (VIX median split) ---")

    vix_median = np.nanmedian(vix_v)
    high_vix = vix_v >= vix_median
    low_vix = vix_v < vix_median

    for regime_name, mask in [("Low VIX", low_vix), ("High VIX", high_vix)]:
        n_regime = mask.sum()
        if n_regime < 50:
            print(f"  {regime_name}: too few obs ({n_regime}), skipping")
            continue

        X_reg = spread_v[mask].reshape(-1, 1)
        y_reg = target_v[mask]

        t_reg, p_reg, beta_reg = newey_west_tstat(X_reg, y_reg, lag=10)
        # Also Spearman
        sp_reg = stats.spearmanr(X_reg.flatten(), y_reg)

        print(f"  {regime_name} (n={n_regime}):")
        print(f"    b(spread) = {beta_reg[1]:.6f}, t = {t_reg[1]:.3f}, p = {p_reg[1]:.4f}")
        print(f"    Spearman  = {sp_reg.statistic:.4f}, p = {sp_reg.pvalue:.4f}")

    # ============================================================
    # 7. STORE RESULTS
    # ============================================================
    asset_results[asset_name] = {
        "n_obs": int(n_obs),
        "n_valid": int(n_valid),
        "is_size": int(split_idx),
        "oos_size": int(n_valid - split_idx),
        "descriptive": {
            "spread_raw_mean": float(analysis["spread_raw"].mean()),
            "spread_raw_std": float(analysis["spread_raw"].std()),
            "spread_5d_mean": float(analysis["spread_5d"].mean()),
            "spread_5d_std": float(analysis["spread_5d"].std()),
            "r_sq_mean": float(analysis["r_sq"].mean()),
            "abs_ret_mean": float(analysis["abs_ret"].mean()),
        },
        "correlations": {
            "spread_vs_vix": float(corr_spread_vix),
            "spread_vs_absret": float(corr_spread_absret),
            "spread_vs_rsq": float(corr_spread_rsq),
        },
        "regressions": {
            "univariate_spread": {
                "beta": float(beta_uni[1]),
                "t_stat": float(t_uni[1]),
                "p_value": float(p_uni[1]),
            },
            "bivariate_spread_vix": {
                "beta_spread": float(beta_bi[1]),
                "t_spread": float(t_bi[1]),
                "p_spread": float(p_bi[1]),
                "beta_vix": float(beta_bi[2]),
                "t_vix": float(t_bi[2]),
                "p_vix": float(p_bi[2]),
            },
            "vix_only": {
                "beta_vix": float(beta_vix[1]),
                "t_vix": float(t_vix[1]),
                "p_vix": float(p_vix[1]),
            },
            "har_baseline": {
                "t_rv1": float(t_har[1]),
                "t_rv5": float(t_har[2]),
                "t_rv22": float(t_har[3]),
            },
            "har_s": {
                "beta_spread": float(beta_hars[4]),
                "t_spread": float(t_hars[4]),
                "p_spread": float(p_hars[4]),
            },
        },
        "oos_qlike": {
            "naive": float(ql_naive),
            "spread_only": float(ql_uni),
            "vix_only": float(ql_vix),
            "spread_vix": float(ql_bi),
            "har": float(ql_har),
            "har_s": float(ql_hars),
        },
        "oos_spearman": {
            "spread_only": float(sp_uni[0]),
            "vix_only": float(sp_vix[0]),
            "spread_vix": float(sp_bi[0]),
            "har": float(sp_har[0]),
            "har_s": float(sp_hars[0]),
        },
        "dm_tests": {
            "hars_vs_har": {"t": float(dm_hars_vs_har[0]), "p": float(dm_hars_vs_har[1])},
            "spread_vix_vs_vix": {"t": float(dm_bi_vs_vix[0]), "p": float(dm_bi_vs_vix[1])},
            "spread_vs_naive": {"t": float(dm_uni_vs_naive[0]), "p": float(dm_uni_vs_naive[1])},
            "har_vs_naive": {"t": float(dm_har_vs_naive[0]), "p": float(dm_har_vs_naive[1])},
        },
    }

RESULTS["assets"] = asset_results

# ============================================================
# 8. CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

summary_rows = []
for asset, r in asset_results.items():
    row = {
        "asset": asset,
        "spread_mean": r["descriptive"]["spread_5d_mean"],
        "spread_vs_vix_corr": r["correlations"]["spread_vs_vix"],
        "uni_t": r["regressions"]["univariate_spread"]["t_stat"],
        "bi_t_spread": r["regressions"]["bivariate_spread_vix"]["t_spread"],
        "hars_t_spread": r["regressions"]["har_s"]["t_spread"],
        "ql_har": r["oos_qlike"]["har"],
        "ql_hars": r["oos_qlike"]["har_s"],
        "dm_hars_vs_har_t": r["dm_tests"]["hars_vs_har"]["t"],
    }
    summary_rows.append(row)

print(f"\n{'Asset':>10s} | {'Spread':>8s} | {'Spr-VIX':>8s} | {'Uni t':>8s} | {'Bi t(S)':>8s} | "
      f"{'HAR-S t':>8s} | {'QL HAR':>8s} | {'QL HARS':>8s} | {'DM t':>8s}")
print("-" * 100)
for row in summary_rows:
    print(f"{row['asset']:>10s} | {row['spread_mean']:8.5f} | {row['spread_vs_vix_corr']:+8.4f} | "
          f"{row['uni_t']:+8.3f} | {row['bi_t_spread']:+8.3f} | {row['hars_t_spread']:+8.3f} | "
          f"{row['ql_har']:8.5f} | {row['ql_hars']:8.5f} | {row['dm_hars_vs_har_t']:+8.3f}")

# ============================================================
# 9. CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)

conclusions = []

# Check if spread is significant as univariate predictor
for asset, r in asset_results.items():
    uni_t = abs(r["regressions"]["univariate_spread"]["t_stat"])
    if uni_t > 3.0:
        conclusions.append(f"{asset}: Spread IS significant univariate predictor (|t|={uni_t:.2f} > 3.0)")
    else:
        conclusions.append(f"{asset}: Spread NOT significant univariate predictor (|t|={uni_t:.2f} < 3.0)")

# Check incremental value beyond VIX
for asset, r in asset_results.items():
    bi_t = abs(r["regressions"]["bivariate_spread_vix"]["t_spread"])
    if bi_t > 3.0:
        conclusions.append(f"{asset}: Spread adds info beyond VIX (bivariate |t|={bi_t:.2f} > 3.0)")
    else:
        conclusions.append(f"{asset}: Spread DOES NOT add beyond VIX (bivariate |t|={bi_t:.2f} < 3.0)")

# Check HAR-S improvement
for asset, r in asset_results.items():
    dm_t = r["dm_tests"]["hars_vs_har"]["t"]
    if dm_t < -3.0:
        conclusions.append(f"{asset}: HAR-S significantly improves over HAR (DM t={dm_t:.2f})")
    else:
        conclusions.append(f"{asset}: HAR-S does NOT significantly improve over HAR (DM t={dm_t:.2f})")

for c in conclusions:
    print(f"  - {c}")

RESULTS["conclusions"] = conclusions

# Overall assessment
any_harvey_pass = any(
    abs(r["regressions"]["univariate_spread"]["t_stat"]) > 3.0
    for r in asset_results.values()
)
any_incremental = any(
    abs(r["regressions"]["bivariate_spread_vix"]["t_spread"]) > 3.0
    for r in asset_results.values()
)
any_har_improve = any(
    r["dm_tests"]["hars_vs_har"]["t"] < -3.0
    for r in asset_results.values()
)

overall = []
if any_harvey_pass:
    overall.append("OHLC spread has some predictive power for next-day vol (passes Harvey threshold in at least one asset)")
else:
    overall.append("OHLC spread FAILS Harvey threshold as univariate predictor for all tested assets")

if any_incremental:
    overall.append("Spread provides incremental information beyond VIX in at least one asset")
else:
    overall.append("Spread does NOT provide incremental information beyond VIX for any tested asset")

if any_har_improve:
    overall.append("HAR-S improves over HAR (spread adds to RV forecasting)")
else:
    overall.append("HAR-S does NOT improve over HAR — spread adds nothing to RV forecasting")

RESULTS["overall_assessment"] = overall
for o in overall:
    print(f"\n  ** {o}")

# ============================================================
# 10. SAVE RESULTS
# ============================================================
results_path = Path(__file__).parent / "k862_results.json"
with open(results_path, "w") as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n\nResults saved to: {results_path}")

print("\n" + "=" * 70)
print("K862 COMPLETE")
print("=" * 70)
