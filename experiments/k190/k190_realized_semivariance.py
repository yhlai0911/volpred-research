"""
K190: Realized Semivariance Decomposition for Volatility Prediction
====================================================================
[提出: 用戶, 執行: Claude]

Research Question:
  Does decomposing daily squared returns into positive and negative
  semivariance (RS+, RS-) improve volatility forecasting over standard
  symmetric measures?

Background:
  Barndorff-Nielsen, Kinnebrock & Shephard (2010) showed that realized
  semivariance captures asymmetric volatility dynamics. RS- (downside)
  should be more persistent and predictable than RS+ (upside), providing
  richer information for forecasting.

Data & Methodology:
  - Assets: SPY, QQQ, GLD, TLT, BTC-USD (daily, yfinance)
  - Sample: 2010-01-01 to 2024-12-31 (or latest available)
  - OOS: 2023-01-01 to 2024-12-31
  - All computations strictly causal (no look-ahead)

  Models tested:
    1. Baseline GJR-GARCH(1,1)
    2. EWMA on total r^2 (lambda=0.94)
    3. EWMA-SemiVar: separate EWMA with different lambdas for RS+ (0.96)
       and RS- (0.92), reflecting asymmetric persistence
    4. Semivariance HAR: RV_t = b0 + b1*RS+_{t-1} + b2*RS-_{t-1}
                                + b3*mean(RS+_{t-5:t-1}) + b4*mean(RS-_{t-5:t-1})
    5. GARCH-X with SJV (Signed Jump Variation) as exogenous regressor

  Evaluation:
    - QLIKE loss (primary)
    - Diebold-Mariano test on QLIKE (all models pairwise vs GJR baseline)
    - SJV regime analysis (SJV<0 -> future vol)
    - Partial correlation of SJV with future RV controlling for VIX
    - Harvey (2016) threshold for strategy claims (t > 3.0)
"""

import json
import traceback
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 0. PATHS
# ---------------------------------------------------------------------------
EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_FILE = EXPERIMENT_DIR / "k190_realized_semivariance_results.json"

# ---------------------------------------------------------------------------
# 1. DATA LOADING (yfinance, daily)
# ---------------------------------------------------------------------------
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "BTC-USD"]
START_DATE = "2010-01-01"
END_DATE = "2024-12-31"
OOS_START = "2023-01-01"
WARMUP = 252


def load_data():
    """Download daily data from yfinance for all assets + VIX."""
    import yfinance as yf

    data = {}
    for asset in ASSETS:
        ticker = yf.Ticker(asset)
        df = ticker.history(start=START_DATE, end=END_DATE, auto_adjust=True)
        if len(df) < 500:
            print(f"  [WARN] {asset}: only {len(df)} rows, skipping")
            continue
        df = df[["Close"]].copy()
        df.columns = ["close"]
        df.index = df.index.tz_localize(None)  # remove timezone
        df["log_return"] = np.log(df["close"] / df["close"].shift(1))
        df = df.dropna()
        data[asset] = df
        print(f"  {asset}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

    # VIX for partial correlation
    vix = yf.Ticker("^VIX")
    vix_df = vix.history(start=START_DATE, end=END_DATE, auto_adjust=True)
    vix_df = vix_df[["Close"]].copy()
    vix_df.columns = ["vix"]
    vix_df.index = vix_df.index.tz_localize(None)
    data["VIX"] = vix_df
    print(f"  VIX: {len(vix_df)} days")

    return data


# ---------------------------------------------------------------------------
# 2. SEMIVARIANCE DECOMPOSITION
# ---------------------------------------------------------------------------

def compute_semivariance(returns: pd.Series):
    """
    Decompose daily squared returns into positive and negative semivariance.
    RS+_t = r_t^2 * I(r_t > 0)
    RS-_t = r_t^2 * I(r_t < 0)
    SJV_t = RS+_t - RS-_t
    """
    r = returns.values
    r_sq = r ** 2
    rs_pos = np.where(r > 0, r_sq, 0.0)
    rs_neg = np.where(r < 0, r_sq, 0.0)
    sjv = rs_pos - rs_neg

    return pd.DataFrame(
        {"rv": r_sq, "rs_pos": rs_pos, "rs_neg": rs_neg, "sjv": sjv},
        index=returns.index,
    )


# ---------------------------------------------------------------------------
# 3. FORECASTING MODELS
# ---------------------------------------------------------------------------

def ewma_forecast(series: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """EWMA: h_{t} = lam*h_{t-1} + (1-lam)*x_{t-1}.  forecast[t] uses info <= t-1."""
    n = len(series)
    h = np.zeros(n)
    h[0] = series[0]
    for t in range(1, n):
        h[t] = lam * h[t - 1] + (1 - lam) * series[t - 1]
    return h


def model_ewma_total(rv: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """Standard EWMA on total squared returns."""
    return ewma_forecast(rv, lam)


def model_ewma_semivar(rs_pos: np.ndarray, rs_neg: np.ndarray,
                       lam_pos: float = 0.96, lam_neg: float = 0.92) -> np.ndarray:
    """
    Asymmetric EWMA on RS+ and RS- with DIFFERENT lambdas.
    Key insight: if lam_pos == lam_neg, this is mathematically identical to
    EWMA on total r^2 (linearity). Using different lambdas allows RS- to
    have shorter memory (faster reaction to downside shocks).

    lam_neg < lam_pos: downside vol reacts faster (half-life ~8d vs ~17d).
    """
    h_pos = ewma_forecast(rs_pos, lam_pos)
    h_neg = ewma_forecast(rs_neg, lam_neg)
    return h_pos + h_neg


def model_semivar_har(df_semi: pd.DataFrame, oos_start_idx: int) -> np.ndarray:
    """
    Semivariance HAR:
    RV_t = b0 + b1*RS+_{t-1} + b2*RS-_{t-1}
              + b3*mean(RS+_{t-5:t-1}) + b4*mean(RS-_{t-5:t-1})
    Expanding window, re-estimate quarterly.
    """
    rv = df_semi["rv"].values
    rs_pos = df_semi["rs_pos"].values
    rs_neg = df_semi["rs_neg"].values
    n = len(rv)
    forecasts = np.full(n, np.nan)
    betas = None

    for t in range(oos_start_idx, n):
        if t < 6:
            continue

        # Re-estimate every 63 days
        if betas is None or (t - oos_start_idx) % 63 == 0:
            # Build training: y[6..t-1], X uses [5..t-2]
            y_list, X_list = [], []
            for s in range(6, t):
                y_list.append(rv[s])
                X_list.append([
                    1.0,
                    rs_pos[s - 1],
                    rs_neg[s - 1],
                    np.mean(rs_pos[s - 5:s]),
                    np.mean(rs_neg[s - 5:s]),
                ])
            y_arr = np.array(y_list)
            X_arr = np.array(X_list)
            mask = np.isfinite(y_arr) & np.all(np.isfinite(X_arr), axis=1)
            if mask.sum() < 30:
                continue
            try:
                betas = np.linalg.lstsq(X_arr[mask], y_arr[mask], rcond=None)[0]
            except np.linalg.LinAlgError:
                continue

        # Forecast day t using info up to t-1
        x_t = np.array([
            1.0,
            rs_pos[t - 1],
            rs_neg[t - 1],
            np.mean(rs_pos[t - 5:t]),
            np.mean(rs_neg[t - 5:t]),
        ])
        forecasts[t] = max(float(x_t @ betas), 1e-10)

    return forecasts


def model_gjr_garch(returns_series: pd.Series, oos_start_idx: int) -> np.ndarray:
    """GJR-GARCH(1,1) baseline. Expanding window, re-estimate quarterly."""
    from arch import arch_model

    n = len(returns_series)
    forecasts = np.full(n, np.nan)
    omega = alpha = gamma_p = beta_p = None
    last_h = None  # pct^2

    for t in range(oos_start_idx, n):
        need_refit = (omega is None) or ((t - oos_start_idx) % 63 == 0)

        if need_refit:
            train_ret_pct = returns_series.iloc[:t] * 100
            try:
                am = arch_model(train_ret_pct, vol="GARCH", p=1, o=1, q=1,
                                dist="normal", mean="Zero")
                res = am.fit(disp="off", show_warning=False)
                params = res.params
                omega = float(params["omega"])
                alpha = float(params["alpha[1]"])
                gamma_p = float(params["gamma[1]"])
                beta_p = float(params["beta[1]"])
                last_h = float(res.conditional_volatility.iloc[-1] ** 2)
            except Exception as e:
                print(f"    [GJR] fit error at t={t}: {e}")
                continue

        if omega is None:
            continue

        r_prev_pct = float(returns_series.iloc[t - 1]) * 100
        ind = 1.0 if r_prev_pct < 0 else 0.0
        h_next = omega + (alpha + gamma_p * ind) * r_prev_pct ** 2 + beta_p * last_h
        h_next = max(h_next, 1e-6)
        forecasts[t] = h_next / 1e4  # decimal
        last_h = h_next

    return forecasts


def model_garch_x_sjv(returns_series: pd.Series, sjv: np.ndarray, oos_start_idx: int) -> np.ndarray:
    """
    GARCH(1,1)-X with SJV as exogenous regressor.
    Two-step: (1) fit GARCH, (2) regress r^2 on GARCH-h + SJV_{t-1}.
    Then forecast = OLS prediction.
    """
    from arch import arch_model

    n = len(returns_series)
    forecasts = np.full(n, np.nan)
    betas_x = None
    omega_g = alpha_g = beta_g = last_h_g = None

    for t in range(oos_start_idx, n):
        need_refit = (betas_x is None) or ((t - oos_start_idx) % 63 == 0)

        if need_refit:
            train_ret_pct = returns_series.iloc[:t] * 100
            try:
                am = arch_model(train_ret_pct, vol="GARCH", p=1, q=1,
                                dist="normal", mean="Zero")
                res = am.fit(disp="off", show_warning=False)
                garch_h = res.conditional_volatility.values ** 2  # pct^2

                omega_g = float(res.params["omega"])
                alpha_g = float(res.params["alpha[1]"])
                beta_g = float(res.params["beta[1]"])

                # OLS: r^2_{s} = c0 + c1*garch_h_{s} + c2*SJV_{s-1}
                returns_np = returns_series.iloc[:t].values
                actual_sq_pct = (returns_np * 100) ** 2
                sjv_pct = sjv[:t] * 1e4

                # s=1..t-1: SJV_{s-1} predicts r^2_s (causal)
                y_reg = actual_sq_pct[1:]
                X_reg = np.column_stack([
                    np.ones(len(y_reg)),
                    garch_h[1:],
                    sjv_pct[:-1],
                ])
                mask = np.isfinite(y_reg) & np.all(np.isfinite(X_reg), axis=1)
                if mask.sum() < 100:
                    continue
                betas_x = np.linalg.lstsq(X_reg[mask], y_reg[mask], rcond=None)[0]
                last_h_g = float(garch_h[-1])
            except Exception as e:
                print(f"    [GARCH-X] fit error at t={t}: {e}")
                continue

        if betas_x is None:
            continue

        r_prev_pct = float(returns_series.iloc[t - 1]) * 100
        h_garch = omega_g + alpha_g * r_prev_pct ** 2 + beta_g * last_h_g
        h_garch = max(h_garch, 1e-6)

        sjv_prev_pct = sjv[t - 1] * 1e4
        h_x = betas_x[0] + betas_x[1] * h_garch + betas_x[2] * sjv_prev_pct
        h_x = max(h_x, 1e-6)

        forecasts[t] = h_x / 1e4
        last_h_g = h_garch

    return forecasts


# ---------------------------------------------------------------------------
# 4. EVALUATION
# ---------------------------------------------------------------------------

def qlike_loss(actual_var, forecast_var):
    """QLIKE = mean(log(h) + r^2/h). Lower is better."""
    mask = (forecast_var > 0) & np.isfinite(forecast_var) & np.isfinite(actual_var) & (actual_var >= 0)
    h = forecast_var[mask]
    y = actual_var[mask]
    return float(np.mean(np.log(h) + y / h))


def qlike_losses_array(actual_var, forecast_var):
    """Element-wise QLIKE for DM test."""
    out = np.full_like(actual_var, np.nan, dtype=float)
    mask = (forecast_var > 0) & np.isfinite(forecast_var) & np.isfinite(actual_var) & (actual_var >= 0)
    out[mask] = np.log(forecast_var[mask]) + actual_var[mask] / forecast_var[mask]
    return out


def dm_test(loss1, loss2):
    """Diebold-Mariano. Negative t => model 1 better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {"t_stat": np.nan, "p_value": np.nan, "n": 0}
    d_mean = np.mean(d)
    bw = max(1, int(np.floor(4 * (n / 100) ** (2 / 9))))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, bw + 1):
        w = 1 - k / (bw + 1)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n
    se = np.sqrt(max(var_d, 1e-20))
    t_stat = d_mean / se
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return {"t_stat": round(t_stat, 4), "p_value": round(p_val, 4), "n": int(n)}


# ---------------------------------------------------------------------------
# 5. SJV ANALYSIS
# ---------------------------------------------------------------------------

def sjv_regime_analysis(df_semi, oos_mask):
    """When SJV<0 (downside dominant), is next-day vol higher?"""
    oos_df = df_semi[oos_mask].copy()
    oos_df["rv_next"] = oos_df["rv"].shift(-1)
    oos_df = oos_df.dropna(subset=["rv_next"])

    down = oos_df["sjv"] < 0
    rv_down = oos_df.loc[down, "rv_next"]
    rv_up = oos_df.loc[~down, "rv_next"]

    if len(rv_down) < 10 or len(rv_up) < 10:
        return {"error": "insufficient data"}

    t, p = stats.ttest_ind(rv_down, rv_up, equal_var=False)
    return {
        "n_down": int(down.sum()), "n_up": int((~down).sum()),
        "mean_rv_after_down": round(float(rv_down.mean()), 8),
        "mean_rv_after_up": round(float(rv_up.mean()), 8),
        "ratio": round(float(rv_down.mean() / rv_up.mean()), 4),
        "t_stat": round(float(t), 4), "p_value": round(float(p), 4),
    }


def partial_correlation_sjv_vix(df_semi, vix_series, oos_mask):
    """Partial correlation of SJV_t with RV_{t+1} controlling for VIX_t."""
    oos_df = df_semi[oos_mask].copy()
    oos_df["rv_next"] = oos_df["rv"].shift(-1)

    # Align by date
    common = oos_df.index.intersection(vix_series.index)
    if len(common) < 50:
        return {"error": f"insufficient VIX overlap ({len(common)})"}

    merged = oos_df.loc[common].copy()
    merged["vix"] = vix_series.loc[common].values
    merged = merged.dropna(subset=["rv_next", "sjv", "vix"])

    if len(merged) < 50:
        return {"error": f"insufficient data after merge ({len(merged)})"}

    sjv_v = merged["sjv"].values
    rv_next_v = merged["rv_next"].values
    vix_v = merged["vix"].values

    # Residualize both on VIX
    X_vix = np.column_stack([np.ones(len(vix_v)), vix_v])
    sjv_resid = sjv_v - X_vix @ np.linalg.lstsq(X_vix, sjv_v, rcond=None)[0]
    rv_resid = rv_next_v - X_vix @ np.linalg.lstsq(X_vix, rv_next_v, rcond=None)[0]

    r_partial, p_partial = stats.pearsonr(sjv_resid, rv_resid)
    r_raw, p_raw = stats.pearsonr(sjv_v, rv_next_v)

    return {
        "partial_r": round(float(r_partial), 4),
        "partial_p": round(float(p_partial), 4),
        "raw_r": round(float(r_raw), 4),
        "raw_p": round(float(p_raw), 4),
        "n": int(len(merged)),
    }


def semivariance_asymmetry_test(df_semi, oos_mask):
    """Test whether RS- is more persistent (higher ACF) than RS+."""
    oos_df = df_semi[oos_mask]
    results = {}

    for comp in ["rs_pos", "rs_neg", "rv"]:
        s = oos_df[comp].values
        acfs = {}
        for lag in [1, 5, 22]:
            if len(s) > lag + 10:
                r, p = stats.pearsonr(s[lag:], s[:-lag])
                acfs[f"lag_{lag}"] = {"r": round(float(r), 4), "p": round(float(p), 4)}
        results[comp] = acfs

    # Fisher z-test: RS- ACF(1) > RS+ ACF(1)?
    neg_v = oos_df["rs_neg"].values
    pos_v = oos_df["rs_pos"].values
    n = len(neg_v) - 1
    r_neg, _ = stats.pearsonr(neg_v[1:], neg_v[:-1])
    r_pos, _ = stats.pearsonr(pos_v[1:], pos_v[:-1])
    z_neg = np.arctanh(min(max(r_neg, -0.999), 0.999))
    z_pos = np.arctanh(min(max(r_pos, -0.999), 0.999))
    z_diff = (z_neg - z_pos) / np.sqrt(2 / max(n - 3, 1))
    p_diff = 1 - stats.norm.cdf(z_diff)

    results["asymmetry_test"] = {
        "rs_neg_acf1": round(float(r_neg), 4),
        "rs_pos_acf1": round(float(r_pos), 4),
        "z_stat": round(float(z_diff), 4),
        "p_one_sided": round(float(p_diff), 4),
        "rs_neg_more_persistent": bool(r_neg > r_pos),
    }
    return results


# ---------------------------------------------------------------------------
# 6. FULL-SAMPLE HAR COEFFICIENT ANALYSIS
# ---------------------------------------------------------------------------

def har_coefficient_analysis(df_semi):
    """Full-sample SemiVar HAR to inspect coefficient magnitudes."""
    rv = df_semi["rv"].values
    rs_pos = df_semi["rs_pos"].values
    rs_neg = df_semi["rs_neg"].values

    y_list, X_list = [], []
    for s in range(6, len(rv)):
        y_list.append(rv[s])
        X_list.append([
            1.0,
            rs_pos[s - 1], rs_neg[s - 1],
            np.mean(rs_pos[s - 5:s]), np.mean(rs_neg[s - 5:s]),
        ])
    y = np.array(y_list)
    X = np.array(X_list)
    mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    if mask.sum() < 30:
        return {"error": "insufficient data"}

    y, X = y[mask], X[mask]
    try:
        betas = np.linalg.lstsq(X, y, rcond=None)[0]
        resids = y - X @ betas
        s2 = np.sum(resids ** 2) / (len(y) - 5)
        cov_b = s2 * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(cov_b))
        t_stats = betas / se
        r2 = 1 - np.sum(resids ** 2) / np.sum((y - y.mean()) ** 2)

        labels = ["intercept", "rs_pos_lag1", "rs_neg_lag1", "rs_pos_5d", "rs_neg_5d"]
        coefs = {}
        for i, lab in enumerate(labels):
            coefs[lab] = {"beta": round(float(betas[i]), 8), "t": round(float(t_stats[i]), 3)}
        coefs["R_squared"] = round(float(r2), 4)
        coefs["n_obs"] = int(mask.sum())
        return coefs
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# 7. MAIN EXPERIMENT
# ---------------------------------------------------------------------------

def run_experiment():
    print("=" * 70)
    print("K190: Realized Semivariance Decomposition for Vol Prediction")
    print("=" * 70)
    print()

    print("[1/6] Loading data...")
    data = load_data()
    vix_df = data.pop("VIX")
    print()

    all_results = {}

    for asset_name, asset_df in data.items():
        print(f"{'='*60}")
        print(f"[2/6] {asset_name} ({len(asset_df)} obs)")
        print(f"{'='*60}")

        returns = asset_df["log_return"]
        df_semi = compute_semivariance(returns)

        # OOS boundary
        oos_dates = df_semi.index >= OOS_START
        oos_start_idx = int(np.argmax(oos_dates))
        n_oos = int(oos_dates.sum())

        if oos_start_idx < WARMUP:
            print(f"  [SKIP] OOS start too early ({oos_start_idx})")
            continue
        print(f"  OOS: {n_oos} days from idx {oos_start_idx}")

        actual_rv = df_semi["rv"].values

        # ---- Run all models ----
        print("  [M1] GJR-GARCH...")
        gjr_fc = model_gjr_garch(returns, oos_start_idx)

        print("  [M2] EWMA total (lam=0.94)...")
        ewma_fc = model_ewma_total(actual_rv, lam=0.94)

        print("  [M3] EWMA SemiVar (lam+=0.96, lam-=0.92)...")
        ewma_sv_fc = model_ewma_semivar(df_semi["rs_pos"].values, df_semi["rs_neg"].values,
                                        lam_pos=0.96, lam_neg=0.92)

        print("  [M4] SemiVar HAR...")
        har_fc = model_semivar_har(df_semi, oos_start_idx)

        print("  [M5] GARCH-X SJV...")
        gx_fc = model_garch_x_sjv(returns, df_semi["sjv"].values, oos_start_idx)

        # ---- Evaluate ----
        oos_sl = slice(oos_start_idx, None)
        actual_oos = actual_rv[oos_sl]

        models = {
            "GJR_GARCH": gjr_fc[oos_sl],
            "EWMA_total": ewma_fc[oos_sl],
            "EWMA_semivar": ewma_sv_fc[oos_sl],
            "SemiVar_HAR": har_fc[oos_sl],
            "GARCH_X_SJV": gx_fc[oos_sl],
        }

        qlike_scores = {}
        qlike_arrs = {}
        for name, fcast in models.items():
            valid = np.isfinite(fcast) & (fcast > 0)
            n_valid = int(valid.sum())
            if n_valid < 50:
                print(f"    {name}: only {n_valid} valid forecasts — skipping QLIKE")
                qlike_scores[name] = None
                qlike_arrs[name] = np.full_like(actual_oos, np.nan)
            else:
                ql = qlike_loss(actual_oos[valid], fcast[valid])
                qlike_scores[name] = round(ql, 6)
                qlike_arrs[name] = qlike_losses_array(actual_oos, fcast)
                print(f"    {name}: QLIKE={ql:.6f}  ({n_valid}/{n_oos} valid)")

        # DM tests vs GJR
        dm_results = {}
        bl = "GJR_GARCH"
        if qlike_scores.get(bl) is not None:
            for name in models:
                if name == bl or qlike_scores.get(name) is None:
                    continue
                dm = dm_test(qlike_arrs[name], qlike_arrs[bl])
                dm_results[f"{name}_vs_GJR"] = dm

        # Also do pairwise: SemiVar_HAR vs EWMA_total
        if qlike_scores.get("SemiVar_HAR") is not None and qlike_scores.get("EWMA_total") is not None:
            dm_results["SemiVar_HAR_vs_EWMA_total"] = dm_test(
                qlike_arrs["SemiVar_HAR"], qlike_arrs["EWMA_total"]
            )
        if qlike_scores.get("EWMA_semivar") is not None and qlike_scores.get("EWMA_total") is not None:
            dm_results["EWMA_semivar_vs_EWMA_total"] = dm_test(
                qlike_arrs["EWMA_semivar"], qlike_arrs["EWMA_total"]
            )

        # ---- SJV analysis ----
        print("  SJV regime...")
        regime = sjv_regime_analysis(df_semi, oos_dates)

        print("  Partial corr SJV|VIX...")
        pcorr = partial_correlation_sjv_vix(df_semi, vix_df["vix"], oos_dates)

        print("  Asymmetry test...")
        asym = semivariance_asymmetry_test(df_semi, oos_dates)

        print("  HAR coefficients (full sample)...")
        har_coefs = har_coefficient_analysis(df_semi)

        # Summary stats
        valid_scores = {k: v for k, v in qlike_scores.items() if v is not None}
        best_model = min(valid_scores, key=valid_scores.get) if valid_scores else "N/A"

        asset_result = {
            "summary": {
                "n_total": int(len(returns)),
                "n_oos": n_oos,
                "oos_range": f"{df_semi.index[oos_start_idx].date()} to {df_semi.index[-1].date()}",
                "annualized_vol_oos_pct": round(float(np.sqrt(actual_oos.mean() * 252) * 100), 2),
                "rs_neg_share": round(float(df_semi["rs_neg"][oos_dates].sum() / df_semi["rv"][oos_dates].sum()), 4),
                "sjv_mean": round(float(df_semi["sjv"][oos_dates].mean()), 10),
            },
            "qlike": qlike_scores,
            "best_model": best_model,
            "dm_tests": dm_results,
            "sjv_regime": regime,
            "partial_corr_sjv_vix": pcorr,
            "asymmetry": asym,
            "har_coefficients": har_coefs,
        }
        all_results[asset_name] = asset_result
        print(f"  >>> Best: {best_model}  QLIKE={qlike_scores.get(best_model)}")
        print()

    # ---- Cross-asset summary ----
    print("\n" + "=" * 80)
    print("CROSS-ASSET SUMMARY")
    print("=" * 80)

    cross = {
        "n_assets": len(all_results),
        "assets": list(all_results.keys()),
        "best_models": {a: r["best_model"] for a, r in all_results.items()},
    }

    # Win counts
    wins = {}
    for a, r in all_results.items():
        b = r["best_model"]
        wins[b] = wins.get(b, 0) + 1
    cross["model_wins"] = wins

    # Significant DM improvements over GJR
    sig_over_gjr = {}
    for a, r in all_results.items():
        for tname, dm in r.get("dm_tests", {}).items():
            if "_vs_GJR" in tname and dm.get("p_value", 1) < 0.05 and dm.get("t_stat", 0) < 0:
                model = tname.replace("_vs_GJR", "")
                sig_over_gjr[model] = sig_over_gjr.get(model, 0) + 1
    cross["significant_dm_over_gjr"] = sig_over_gjr

    # RS- more persistent
    neg_persist = sum(
        1 for r in all_results.values()
        if r.get("asymmetry", {}).get("asymmetry_test", {}).get("rs_neg_more_persistent", False)
    )
    cross["rs_neg_more_persistent"] = f"{neg_persist}/{len(all_results)}"

    # SJV predicts vol
    sjv_sig = sum(
        1 for r in all_results.values()
        if r.get("sjv_regime", {}).get("p_value", 1) < 0.05 and r.get("sjv_regime", {}).get("ratio", 1) > 1
    )
    cross["sjv_predicts_higher_vol"] = f"{sjv_sig}/{len(all_results)}"

    # Partial corr significant
    pc_sig = sum(
        1 for r in all_results.values()
        if r.get("partial_corr_sjv_vix", {}).get("partial_p", 1) < 0.05
    )
    cross["sjv_partial_corr_sig_given_vix"] = f"{pc_sig}/{len(all_results)}"

    # ---- Print tables ----
    print(f"\n{'Asset':<10} {'GJR':>10} {'EWMA':>10} {'EWMA-SV':>10} {'SV-HAR':>10} {'GARCH-X':>10} {'Best':>12}")
    print("-" * 80)
    for a, r in all_results.items():
        ql = r["qlike"]
        row = f"{a:<10}"
        for m in ["GJR_GARCH", "EWMA_total", "EWMA_semivar", "SemiVar_HAR", "GARCH_X_SJV"]:
            v = ql.get(m)
            row += f"{'N/A':>10}" if v is None else f"{v:>10.4f}"
        row += f"{r['best_model']:>12}"
        print(row)

    print(f"\nDM TESTS (negative t = challenger better):")
    print("-" * 80)
    for a, r in all_results.items():
        parts = [f"  {a:<10}"]
        for tname, dm in r.get("dm_tests", {}).items():
            t = dm.get("t_stat", float("nan"))
            p = dm.get("p_value", float("nan"))
            sig = " *" if p < 0.05 else ""
            parts.append(f"{tname}: t={t:.3f} p={p:.3f}{sig}")
        print("  ".join(parts))

    print(f"\nASYMMETRY (RS- more persistent than RS+?):")
    for a, r in all_results.items():
        at = r.get("asymmetry", {}).get("asymmetry_test", {})
        print(f"  {a:<10} ACF1(RS-)={at.get('rs_neg_acf1','?'):>6}  "
              f"ACF1(RS+)={at.get('rs_pos_acf1','?'):>6}  "
              f"z={at.get('z_stat','?'):>6}  p={at.get('p_one_sided','?'):>6}  "
              f"more_persist={at.get('rs_neg_more_persistent','?')}")

    print(f"\nSJV REGIME (downside -> higher future vol?):")
    for a, r in all_results.items():
        rg = r.get("sjv_regime", {})
        print(f"  {a:<10} ratio={rg.get('ratio','?')}  t={rg.get('t_stat','?')}  p={rg.get('p_value','?')}")

    print(f"\nPARTIAL CORR SJV|VIX:")
    for a, r in all_results.items():
        pc = r.get("partial_corr_sjv_vix", {})
        print(f"  {a:<10} partial_r={pc.get('partial_r','?')}  p={pc.get('partial_p','?')}  "
              f"raw_r={pc.get('raw_r','?')}")

    print(f"\nHAR COEFFICIENTS (key: is RS- coef > RS+ coef?):")
    for a, r in all_results.items():
        hc = r.get("har_coefficients", {})
        neg1 = hc.get("rs_neg_lag1", {})
        pos1 = hc.get("rs_pos_lag1", {})
        neg5 = hc.get("rs_neg_5d", {})
        pos5 = hc.get("rs_pos_5d", {})
        r2 = hc.get("R_squared", "?")
        print(f"  {a:<10} RS-_lag1: b={neg1.get('beta','?')} t={neg1.get('t','?')}  |  "
              f"RS+_lag1: b={pos1.get('beta','?')} t={pos1.get('t','?')}  |  "
              f"RS-_5d: b={neg5.get('beta','?')} t={neg5.get('t','?')}  |  R2={r2}")

    print(f"\n{'='*60}")
    print(f"Model wins: {wins}")
    print(f"Sig DM over GJR: {cross['significant_dm_over_gjr']}")
    print(f"RS- more persistent: {cross['rs_neg_more_persistent']}")
    print(f"SJV predicts higher vol: {cross['sjv_predicts_higher_vol']}")
    print(f"SJV partial|VIX sig: {cross['sjv_partial_corr_sig_given_vix']}")

    # ---- Save ----
    final = {
        "experiment": "K190",
        "title": "Realized Semivariance Decomposition for Volatility Prediction",
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now().isoformat(),
        "methodology": {
            "data_source": "yfinance daily",
            "assets": ASSETS,
            "sample": f"{START_DATE} to {END_DATE}",
            "oos": f"{OOS_START} to {END_DATE}",
            "models": [
                "GJR-GARCH(1,1) baseline",
                "EWMA(lam=0.94) on total r^2",
                "EWMA asymmetric (lam+=0.96 lam-=0.92) on RS+/RS-",
                "Semivariance HAR (daily+weekly RS+/RS-)",
                "GARCH-X with SJV exogenous",
            ],
            "semivariance": {
                "RS_plus": "r^2 * I(r>0)", "RS_minus": "r^2 * I(r<0)",
                "SJV": "RS+ - RS- (signed jump variation)",
            },
            "evaluation": "QLIKE (primary), DM test, SJV regime, partial r|VIX",
            "reference": "Barndorff-Nielsen, Kinnebrock & Shephard (2010, JFE)",
            "causal": "All forecasts use only t-1 information",
        },
        "cross_asset_summary": cross,
        "per_asset": all_results,
    }

    print(f"\nSaving to {RESULTS_FILE}...")
    with open(RESULTS_FILE, "w") as f:
        json.dump(final, f, indent=2, default=str)
    print("Done.")

    return final


if __name__ == "__main__":
    run_experiment()
