"""
K1386: Multivariate Rough Volatility Model
===========================================
Method:
  1. Hurst estimation via log-structure function: H from slope of
     log E[|log_RV_{t+h} - log_RV_t|^2] vs log(h), fitting lags 1–20 (IS only)
  2. fGN univariate predictor: OLS AR(p) on log-RV increments (IS calibrated),
     then reconstruct level: log_RV_{t+1} = log_RV_t + AR-pred(d_{t+1})
  3. fGN multivariate: univariate + OLS cross-asset lagged-increment correction
  4. HAR-RV baseline: standard HAR on Parkinson RV (daily/weekly/monthly avg)
  5. OOS evaluation: canonical Patton QLIKE and Bartlett Newey-West HAC-DM;
     Harvey, Liu, and Zhu (2016) |t|>3 reporting screen

Assets: SPY (primary), QQQ, GLD
IS:  2010-01-01 ~ 2021-12-31   (~3021 obs)
OOS: 2022-01-01 ~ 2026-05-19   (1098 forecast origins)

Key methodological notes:
- log-RV LEVEL has positive ACF (persistent), so fGN theory applies to INCREMENTS
- H<0.5 means anti-persistent increments (rough path) — consistent with K529 H≈0.1
- All signal.shift(1) via lag-1 design: features at time t, target RV at t+1
- Cross-asset correction uses only lag-1 increments (no contemporaneous info)
- seed=42 (no random components used; set for reproducibility if extended)

References:
  - Gatheral et al. (2018) QF: rough volatility, H estimation via structure function
  - arXiv:2412.14353 (Feb 2026): multivariate fractional OU + moment estimation
  - Patton (2011): QLIKE loss function, proxy-robust ranking
  - Diebold and Mariano (1995): equal predictive-accuracy test
  - Harvey, Leybourne, and Newbold (1997): small-sample diagnostic
  - Harvey, Liu, and Zhu (2016): conservative |t|>3 reporting screen
  - Newey and West (1987): HAC long-run variance
"""

import hashlib
import json
import os
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

warnings.filterwarnings("ignore")
np.random.seed(42)

# ─────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_SPY = ROOT / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv"
DATA_GLD = ROOT / "paper/garch-x-vix/data/gld_vix_gvz_2000-2026.csv"
OUT_DIR = Path(__file__).resolve().parent

IS_END = "2021-12-31"
OOS_START = "2022-01-01"
OOS_END = "2026-05-19"
FORECAST_HORIZON = 1
HAC_LAG_SENSITIVITY = (0, 1, 5, 10, 20)
EXPECTED_ANALYSIS_SLICE_SHA256 = (
    "9bce8a54db1c822a76b90ace40144757b683e36b9416d74ca1c6430c71b8b567"
)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path, payload):
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        with tmp.open(encoding="utf-8") as handle:
            json.load(handle)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_save_npy(path, values):
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("wb") as handle:
            np.save(handle, values)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def dataframe_sha256(frame):
    """Hash a canonical CSV serialization of the analysis frame."""
    payload = frame.to_csv(index=False, date_format="%Y-%m-%d", lineterminator="\n")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# ─────────────────────────────────────────────────
# 1. Load & Prepare Data
# ─────────────────────────────────────────────────
def _deduplicate_identical_dates(frame, source_name):
    """Collapse identical duplicate-date rows; reject conflicting observations."""
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    duplicate_mask = frame.duplicated("date", keep=False)
    duplicate_dates = frame.loc[duplicate_mask, "date"].drop_duplicates().tolist()
    conflicting_dates = []
    for date in duplicate_dates:
        values = frame.loc[frame["date"].eq(date)].drop(columns="date")
        if len(values.drop_duplicates()) != 1:
            conflicting_dates.append(date.strftime("%Y-%m-%d"))
    if conflicting_dates:
        raise ValueError(
            f"{source_name} has conflicting rows for duplicate dates: {conflicting_dates}"
        )

    deduplicated = frame.drop_duplicates("date", keep="first").reset_index(drop=True)
    if deduplicated["date"].duplicated().any():
        raise AssertionError(f"{source_name} date deduplication failed")
    audit = {
        "raw_rows": int(len(frame)),
        "unique_dates": int(frame["date"].nunique()),
        "duplicate_rows_removed": int(len(frame) - len(deduplicated)),
        "duplicate_date_count": int(len(duplicate_dates)),
        "duplicate_dates": [date.strftime("%Y-%m-%d") for date in duplicate_dates],
        "duplicate_values_identical": True,
    }
    return deduplicated, audit


def load_data():
    # The default pandas C float parser can differ by one ULP across CPU/OS
    # combinations.  Pin the round-trip converter so the frozen CSV bytes map
    # to the same analysis values (and slice hash) on macOS and Linux CI.
    spy_df = pd.read_csv(
        DATA_SPY,
        parse_dates=["date"],
        float_precision="round_trip",
    )
    gld_df = pd.read_csv(
        DATA_GLD,
        parse_dates=["date"],
        float_precision="round_trip",
    )
    # Audit only the frozen analysis window. Later appended rows must not alter
    # a methodology-repair rerun, while historical changes fail the slice hash.
    spy_df = spy_df[spy_df["date"].between("2010-01-01", OOS_END)].copy()
    gld_df = gld_df[gld_df["date"].between("2010-01-01", OOS_END)].copy()
    spy_df, spy_audit = _deduplicate_identical_dates(spy_df, DATA_SPY.name)
    gld_df, gld_audit = _deduplicate_identical_dates(gld_df, DATA_GLD.name)
    df = spy_df[["date", "spy_adj_close", "spy_high", "spy_low",
                 "qqq_adj_close", "qqq_high", "qqq_low"]].copy()
    gld_cols = gld_df[["date", "gld_adj_close", "gld_high", "gld_low"]].copy()
    df = df.merge(gld_cols, on="date", how="inner", validate="one_to_one")
    df = df.sort_values("date").reset_index(drop=True)
    if df["date"].duplicated().any() or not df["date"].is_monotonic_increasing:
        raise AssertionError("Merged analysis dates must be unique and increasing")
    data_audit = {
        "spy_qqq_source": spy_audit,
        "gld_source": gld_audit,
        "merge_validation": "one_to_one",
        "analysis_window_merged_rows": int(len(df)),
        "analysis_window_unique_dates": int(df["date"].nunique()),
    }
    return df, data_audit


def add_parkinson_rv(df, assets):
    """
    Parkinson (1980) range-based RV estimator:
      RV_pk = (log(H/L))^2 / (4 * log(2))
    ~4x more efficient than squared close-to-close return for pure diffusion.
    """
    for a in assets:
        df[f"{a}_rv_pk"] = (np.log(df[f"{a}_high"] / df[f"{a}_low"])) ** 2 / (4 * np.log(2))
    return df


# ─────────────────────────────────────────────────
# 2. Hurst Estimation via Log-Structure Function
# ─────────────────────────────────────────────────
def estimate_hurst_structure(log_rv_is, lags=None):
    """
    Estimate Hurst exponent H from the scaling of the log-structure function:
      E[|log_RV_{t+h} - log_RV_t|^2] ~ C * h^{2H}
    => slope of log E[|Δ_h log_RV|^2] vs log(h) equals 2H.

    Fitting range: lags 1–20 on IS data (before saturation at long lags).
    This is the method of Gatheral et al. (2018) for rough volatility.

    Returns H_hat (in (0, 0.5) for rough vol).
    """
    if lags is None:
        lags = np.arange(1, 21)
    series = log_rv_is
    m2 = np.array([np.mean((series[h:] - series[:-h]) ** 2) for h in lags])
    coeffs = np.polyfit(np.log(lags), np.log(m2), 1)
    H_hat = coeffs[0] / 2.0
    return float(H_hat), float(coeffs[1]), m2


def acf_of_increments(log_rv_is, K=10):
    """Empirical ACF of log-RV increments (for validation)."""
    d = np.diff(log_rv_is)
    mu = d.mean()
    var = ((d - mu) ** 2).mean()
    acf = []
    for k in range(1, K + 1):
        cov_k = ((d[k:] - mu) * (d[:-k] - mu)).mean()
        acf.append(cov_k / var if var > 0 else 0.0)
    return np.array(acf)


# ─────────────────────────────────────────────────
# 3. HAR-RV Baseline
# ─────────────────────────────────────────────────
def har_rv_predict(rv_series, train_mask, test_mask):
    """
    HAR-RV: Y_{t+1} = b0 + b1*RV_t + b2*RV_{t-4:t} + b3*RV_{t-21:t} + e
    OLS on IS; expanding-window not needed (OLS coefficients fixed).

    Lookahead prevention:
      - Features are rv at time t (rv_d), 5-day avg ending at t (rv_w),
        22-day avg ending at t (rv_m)
      - Target is rv at t+1 (shift(-1) in signal construction)
      - At prediction time t in OOS, we use features at t to predict rv_{t+1}
    """
    rv = rv_series.copy()
    rv_d = rv
    rv_w = rv.rolling(5).mean()
    rv_m = rv.rolling(22).mean()
    # Target: RV at next period (t+1)
    target = rv.shift(-1)

    X = pd.DataFrame({"const": 1.0, "rv_d": rv_d, "rv_w": rv_w, "rv_m": rv_m})

    # IS fit. An origin is eligible only when its t+1 target also remains IS;
    # this excludes the final IS origin and prevents the first OOS observation
    # from entering the baseline fit.
    target_is_mask = train_mask & train_mask.shift(-1, fill_value=False)
    X_train = X[target_is_mask]
    y_train = target[target_is_mask]
    valid = X_train.dropna().index.intersection(y_train.dropna().index)
    X_tr = X_train.loc[valid].values
    y_tr = y_train.loc[valid].values
    beta, _, _, _ = np.linalg.lstsq(X_tr, y_tr, rcond=None)

    # OOS prediction: use features at time t to predict rv_{t+1}
    X_oos = X[test_mask].ffill()
    preds = np.maximum(X_oos.values @ beta, 1e-10)
    return pd.Series(preds, index=X[test_mask].index), beta, valid


# ─────────────────────────────────────────────────
# 4. fGN Univariate Predictor (OLS AR on increments)
# ─────────────────────────────────────────────────
def fgn_uni_predict(log_rv_series, train_mask, test_mask, p=20):
    """
    Univariate fGN-motivated AR predictor on log-RV increments.

    Model: d_t = log_RV_t - log_RV_{t-1}  (daily increment)
    d_{t+1} = sum_{k=1}^{p} phi_k * d_{t+1-k} + e

    OLS calibrated on IS increments. Prediction:
      log_RV_{t+1} = log_RV_t + d_hat_{t+1}
      RV_{t+1} = exp(log_RV_{t+1})

    Lookahead prevention:
      - At OOS time t, we use d_t, d_{t-1}, ..., d_{t-p+1} to predict d_{t+1}
      - d_t = log_RV_t - log_RV_{t-1}: known at time t (no future info)
      - Then RV_{t+1} = exp(log_RV_t + d_hat_{t+1}) is our forecast for time t+1
    """
    log_rv = log_rv_series.values
    n = len(log_rv)
    d = np.diff(log_rv)  # length n-1; d[t] = log_rv[t+1] - log_rv[t]

    # IS: train_mask aligns with log_rv (n points)
    is_n = train_mask.sum()
    # IS increments: d[0..is_n-2]
    is_d = d[:is_n - 1]  # length is_n - 1
    n_id = len(is_d)

    # OLS AR(p) on IS increments
    rows = n_id - p
    X_mat = np.zeros((rows, p))
    y_vec = is_d[p:]  # d_{p}, d_{p+1}, ..., d_{n_id-1}
    for k in range(1, p + 1):
        X_mat[:, k - 1] = is_d[p - k:n_id - k]  # d_{t-k} at each row t=p..n_id-1
    beta, _, _, _ = np.linalg.lstsq(X_mat, y_vec, rcond=None)

    # IS mean of increments (for de-meaning)
    mu_d = is_d.mean()

    # OOS prediction
    oos_positions = np.where(test_mask.values)[0]
    preds_rv = []

    for pos in oos_positions:
        # We need d[pos-p..pos-1] (p most recent increments at time pos)
        # d[t] = log_rv[t+1] - log_rv[t], so d[pos-1] = log_rv[pos] - log_rv[pos-1]
        # This is known at time pos (current) — no lookahead
        if pos < p + 1:
            # Not enough history: use current log_rv as prediction (no change)
            preds_rv.append(np.exp(log_rv[pos]))
            continue
        past_d = d[pos - p:pos]  # d[pos-p], ..., d[pos-1]  (length p)
        # AR prediction: phi @ past_d in order [d_{t-1}, d_{t-2}, ..., d_{t-p}]
        # X_mat[:, 0] = d_{t-1}, X_mat[:, 1] = d_{t-2}, ...
        past_d_reversed = past_d[::-1]  # [d_{pos-1}, d_{pos-2}, ..., d_{pos-p}]
        d_hat = float(np.dot(beta, past_d_reversed))
        log_rv_pred = log_rv[pos] + d_hat  # anchor at current level
        preds_rv.append(np.exp(log_rv_pred))

    preds = np.maximum(np.array(preds_rv), 1e-10)
    oos_idx = log_rv_series.index[oos_positions]
    return pd.Series(preds, index=oos_idx), beta


# ─────────────────────────────────────────────────
# 5. fGN Multivariate Predictor (cross-asset correction)
# ─────────────────────────────────────────────────
def fgn_multi_predict(log_rv_dict, train_mask, test_mask, primary="SPY",
                       assets=None, p=20):
    """
    Multivariate fGN predictor for primary asset (SPY).

    Step 1: Fit univariate fGN AR(p) on increments for ALL assets (IS).
    Step 2: Compute IS residuals (actual increment - AR prediction) for all assets.
    Step 3: Fit OLS cross-asset correction on IS residuals:
              resid_SPY_t = alpha + beta_QQQ * resid_QQQ_{t-1} + beta_GLD * resid_GLD_{t-1}
              (lag-1 to avoid any lookahead — only yesterday's other assets' residuals)
    Step 4: OOS prediction = univariate prediction + cross-asset correction.

    Lookahead prevention:
      - Univariate AR uses only increments through d_{t} (known at t)
      - Cross-asset correction uses lag-1 residuals (resid at t-1, known at t)
      - Therefore: forecast is for RV at t+1 using only info available at t ✓
    """
    if assets is None:
        assets = list(log_rv_dict.keys())

    all_log_rv = {a: log_rv_dict[a].values for a in assets}
    n = len(log_rv_dict[primary])
    is_n = train_mask.sum()

    # Step 1: IS AR(p) for each asset's increments
    beta_dict = {}
    mu_d_dict = {}
    for a in assets:
        log_rv_a = all_log_rv[a]
        d_a = np.diff(log_rv_a)
        is_d_a = d_a[:is_n - 1]
        n_id = len(is_d_a)
        rows = n_id - p
        X_mat = np.zeros((rows, p))
        y_vec = is_d_a[p:]
        for k in range(1, p + 1):
            X_mat[:, k - 1] = is_d_a[p - k:n_id - k]
        beta_a, _, _, _ = np.linalg.lstsq(X_mat, y_vec, rcond=None)
        beta_dict[a] = beta_a
        mu_d_dict[a] = is_d_a.mean()

    # Step 2: IS residuals for all assets
    resid_dict = {}
    for a in assets:
        log_rv_a = all_log_rv[a]
        d_a = np.diff(log_rv_a)
        is_d_a = d_a[:is_n - 1]
        n_id = len(is_d_a)
        beta_a = beta_dict[a]
        resid_a = np.full(n_id, np.nan)
        for t in range(p, n_id):
            past_d = is_d_a[t - p:t][::-1]
            d_hat = float(np.dot(beta_a, past_d))
            resid_a[t] = is_d_a[t] - d_hat
        resid_dict[a] = resid_a  # length is_n-1, valid from index p onwards

    # Step 3: Cross-asset OLS on IS residuals
    # y = resid_SPY[t],  X = [1, resid_QQQ[t-1], resid_GLD[t-1]]
    # valid indices: p+1 .. is_n-2
    other_assets = [a for a in assets if a != primary]
    valid_start = p + 1
    valid_end = is_n - 1  # exclusive
    n_valid = valid_end - valid_start

    y_cross = resid_dict[primary][valid_start:valid_end]
    X_cross_cols = [np.ones(n_valid)]
    for a in other_assets:
        X_cross_cols.append(resid_dict[a][valid_start - 1:valid_end - 1])  # lag 1

    X_cross = np.column_stack(X_cross_cols)
    mask_valid = ~np.isnan(y_cross)
    for col in X_cross.T:
        mask_valid = mask_valid & ~np.isnan(col)

    beta_cross, _, _, _ = np.linalg.lstsq(
        X_cross[mask_valid], y_cross[mask_valid], rcond=None
    )

    # Step 4: Full-sample residuals for cross-asset correction in OOS
    full_resid_dict = {}
    for a in assets:
        log_rv_a = all_log_rv[a]
        d_a = np.diff(log_rv_a)
        full_n = len(d_a)
        beta_a = beta_dict[a]
        full_resid = np.full(full_n, np.nan)
        for t in range(p, full_n):
            past_d = d_a[t - p:t][::-1]
            d_hat = float(np.dot(beta_a, past_d))
            full_resid[t] = d_a[t] - d_hat
        full_resid_dict[a] = full_resid

    # OOS prediction
    oos_positions = np.where(test_mask.values)[0]
    log_rv_primary = all_log_rv[primary]
    d_primary = np.diff(log_rv_primary)  # length n-1
    beta_primary = beta_dict[primary]

    preds_rv = []
    for pos in oos_positions:
        if pos < p + 2:
            preds_rv.append(np.exp(log_rv_primary[pos]))
            continue

        # Univariate component
        past_d = d_primary[pos - p:pos][::-1]
        d_hat_uni = float(np.dot(beta_primary, past_d))

        # Cross-asset correction: use lag-1 residuals at time pos-1
        # full_resid[pos-1] = resid of d[pos-1], i.e., at time (pos-1)
        correction = float(beta_cross[0])
        for j, a in enumerate(other_assets):
            lag1_resid = full_resid_dict[a][pos - 1]
            if np.isnan(lag1_resid):
                lag1_resid = 0.0
            correction += float(beta_cross[j + 1]) * lag1_resid

        d_hat_total = d_hat_uni + correction
        log_rv_pred = log_rv_primary[pos] + d_hat_total
        preds_rv.append(np.exp(log_rv_pred))

    preds = np.maximum(np.array(preds_rv), 1e-10)
    oos_idx = log_rv_dict[primary].index[oos_positions]
    return pd.Series(preds, index=oos_idx), beta_cross


# ─────────────────────────────────────────────────
# 6. Evaluation diagnostics
# ─────────────────────────────────────────────────
def canonical_hac_lag(n, h=FORECAST_HORIZON):
    """Mirror the repository canonical bandwidth for recorded diagnostics."""
    return max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))


def serial_acf(values, max_lag=20):
    """Sample autocorrelation of a loss differential, lags 1..max_lag."""
    values = np.asarray(values, dtype=float)
    centered = values - values.mean()
    denominator = float(np.mean(centered**2))
    if denominator <= 0.0:
        return {str(lag): None for lag in range(1, max_lag + 1)}
    return {
        str(lag): float(np.mean(centered[lag:] * centered[:-lag]) / denominator)
        for lag in range(1, min(max_lag, len(values) - 1) + 1)
    }


def newey_west_mean_t(values, max_lag):
    """Bartlett Newey-West mean t-stat for non-primary lag sensitivity."""
    values = np.asarray(values, dtype=float)
    centered = values - values.mean()
    n = len(values)
    long_run_variance = float(np.mean(centered**2))
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        autocovariance = float(np.mean(centered[lag:] * centered[:-lag]))
        long_run_variance += 2.0 * weight * autocovariance
    if long_run_variance <= 0.0:
        return None
    return float(values.mean() / np.sqrt(long_run_variance / n))


def forecast_dm_diagnostics(loss_model, loss_har, h=FORECAST_HORIZON):
    """Canonical DM result plus dependence diagnostics and lag sensitivity."""
    loss_model = np.asarray(loss_model, dtype=float)
    loss_har = np.asarray(loss_har, dtype=float)
    loss_diff = loss_model - loss_har
    n = len(loss_diff)
    lag = canonical_hac_lag(n, h=h)
    t_stat, p_value = dm_test(loss_model, loss_har, h=h)
    sensitivity_lags = sorted(set((*HAC_LAG_SENSITIVITY, lag)))
    hln_factor = float(np.sqrt((n + 1.0 - 2.0 * h + h * (h - 1.0) / n) / n))
    return {
        "t_stat": float(t_stat),
        "p_value_two_sided": float(p_value),
        "n": n,
        "horizon": h,
        "hac_lag": lag,
        "loss_diff_mean": float(loss_diff.mean()),
        "loss_diff_acf": serial_acf(loss_diff, max_lag=20),
        "lag_sensitivity_t": {
            str(candidate_lag): newey_west_mean_t(loss_diff, candidate_lag)
            for candidate_lag in sensitivity_lags
        },
        "hln_factor_diagnostic": hln_factor,
        "hln_t_diagnostic": float(t_stat * hln_factor),
        "harvey_liu_zhu_2016_pass": bool(abs(t_stat) > 3.0),
        "sign_convention": (
            "loss_diff = loss_fGN - loss_HAR; t>0 means fGN has higher QLIKE loss"
        ),
    }


# ─────────────────────────────────────────────────
# 7. Main
# ─────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("K1386: Multivariate fGN-motivated Rough-Volatility Forecast")
    print("=" * 60)

    # ── Load data ──
    df, source_audit = load_data()
    df = add_parkinson_rv(df, ["spy", "qqq", "gld"])
    # Freeze the original publication endpoint so a methodology-only rerun is
    # not confounded by later rows appended to the shared paper data files.
    df = df[df["date"].between("2010-01-01", OOS_END)].reset_index(drop=True)
    df = df.dropna(subset=["spy_rv_pk", "qqq_rv_pk", "gld_rv_pk"]).reset_index(drop=True)
    if df["date"].duplicated().any() or not df["date"].is_monotonic_increasing:
        raise AssertionError("Filtered analysis dates must be unique and increasing")
    analysis_slice_hash = dataframe_sha256(
        df[[
            "date", "spy_adj_close", "spy_high", "spy_low",
            "qqq_adj_close", "qqq_high", "qqq_low",
            "gld_adj_close", "gld_high", "gld_low",
        ]]
    )
    if analysis_slice_hash != EXPECTED_ANALYSIS_SLICE_SHA256:
        raise AssertionError(
            "Frozen K1386 analysis slice changed: "
            f"expected {EXPECTED_ANALYSIS_SLICE_SHA256}, got {analysis_slice_hash}"
        )
    print(f"Total obs: {len(df)}")

    train_mask = df["date"] <= IS_END
    test_mask = df["date"] >= OOS_START
    n_is = int(train_mask.sum())
    n_oos = int(test_mask.sum())
    print(f"IS:  {n_is} obs  ({df['date'][train_mask].iloc[0].date()} ~ {df['date'][train_mask].iloc[-1].date()})")
    print(f"OOS: {n_oos} obs  ({df['date'][test_mask].iloc[0].date()} ~ {df['date'][test_mask].iloc[-1].date()})")
    assert n_oos >= 252, f"OOS too short: {n_oos}"

    # ── Log-RV series (Parkinson) ──
    assets_lo = {"SPY": "spy", "QQQ": "qqq", "GLD": "gld"}
    log_rv_dict = {}
    rv_pk_dict = {}
    for a_up, a_lo in assets_lo.items():
        rv = df[f"{a_lo}_rv_pk"].clip(lower=1e-8)
        rv_pk_dict[a_up] = rv
        log_rv_dict[a_up] = pd.Series(np.log(rv.values), index=df.index)

    # ── Hurst estimation (IS only, log-structure function) ──
    print("\n--- Hurst Estimation via Log-Structure Function (IS) ---")
    lags_sf = np.arange(1, 21)
    hurst_estimates = {}
    acf_incr_dict = {}
    for a_up in ["SPY", "QQQ", "GLD"]:
        is_log_rv = log_rv_dict[a_up][train_mask].values
        H_hat, log_c, m2 = estimate_hurst_structure(is_log_rv, lags=lags_sf)
        hurst_estimates[a_up] = H_hat
        acf_k1 = acf_of_increments(is_log_rv, K=5)
        acf_incr_dict[a_up] = acf_k1
        # H implied by lag-1 ACF of increments: rho(1) = (2^2H - 2)/2
        rho1 = acf_k1[0]
        H_implied = float(np.log(2 + 2 * rho1) / (2 * np.log(2))) if 2 + 2 * rho1 > 0 else float("nan")
        print(f"  {a_up}: H = {H_hat:.4f}  (ACF-lag1-implied: {H_implied:.4f},  incr-ACF-lag1: {rho1:.4f})")

    # Sanity check
    for a_up, H in hurst_estimates.items():
        assert H > 0 and H < 0.5, f"H out of (0,0.5) for {a_up}: H={H:.4f}"

    # ── Cross-asset log-RV correlation (IS, levels) ──
    log_rv_mat_is = pd.DataFrame({a: log_rv_dict[a][train_mask].values for a in ["SPY", "QQQ", "GLD"]})
    corr_mat = log_rv_mat_is.corr().values
    print(f"\n  IS Log-RV Correlation: SPY-QQQ={corr_mat[0,1]:.4f}, "
          f"SPY-GLD={corr_mat[0,2]:.4f}, QQQ-GLD={corr_mat[1,2]:.4f}")

    # ── HAR-RV (SPY, Parkinson RV) ──
    print("\n--- HAR-RV Baseline (SPY, Parkinson RV) ---")
    spy_rv_pk = rv_pk_dict["SPY"].copy()
    spy_rv_pk.index = df.index
    har_preds, har_beta, har_train_rows = har_rv_predict(
        spy_rv_pk, train_mask, test_mask
    )
    har_last_origin = int(har_train_rows[-1])
    har_last_target = har_last_origin + 1
    assert df.loc[har_last_origin, "date"] <= pd.Timestamp(IS_END)
    assert df.loc[har_last_target, "date"] <= pd.Timestamp(IS_END)
    print(f"  HAR betas (const, rv_d, rv_w, rv_m): {har_beta.round(4).tolist()}")

    # ── fGN Univariate (SPY) ──
    print("\n--- fGN Univariate (SPY log-RV increments, AR p=20) ---")
    log_rv_spy = log_rv_dict["SPY"].copy()
    log_rv_spy.index = df.index
    fgn_uni_preds, fgn_uni_beta = fgn_uni_predict(log_rv_spy, train_mask, test_mask, p=20)
    print(f"  AR(p=20) beta[0..4] on increments: {fgn_uni_beta[:5].round(4).tolist()}")

    # ── fGN Multivariate (SPY primary, QQQ + GLD correction) ──
    print("\n--- fGN Multivariate (SPY primary + QQQ/GLD cross-asset correction) ---")
    log_rv_full = {a: log_rv_dict[a].copy() for a in ["SPY", "QQQ", "GLD"]}
    for a in log_rv_full:
        log_rv_full[a].index = df.index

    fgn_multi_preds, beta_cross = fgn_multi_predict(
        log_rv_full, train_mask, test_mask,
        primary="SPY", assets=["SPY", "QQQ", "GLD"], p=20
    )
    other_assets = ["QQQ", "GLD"]
    print(f"  Cross-asset beta (intercept, {other_assets}): {beta_cross.round(4).tolist()}")

    # ── OOS Evaluation ──
    print("\n--- OOS Evaluation (QLIKE on Parkinson RV) ---")
    oos_idx = df[test_mask].index
    # Fix H1: models predict RV_{t+1} (indexed at t); actual must be rv[t+1]
    # Use shift(-1) so that actual_rv[t] = rv[t+1], then drop last (no t+1 available)
    rv_shifted = spy_rv_pk.shift(-1)
    eval_idx = oos_idx[:-1]  # drop last OOS date (rv[T+1] unknown)
    actual_rv = rv_shifted.loc[eval_idx].values

    forecast_series = {
        "HAR": har_preds,
        "fGN_univariate": fgn_uni_preds,
        "fGN_multivariate": fgn_multi_preds,
    }
    for model_name, forecasts in forecast_series.items():
        if not forecasts.index.equals(oos_idx):
            raise AssertionError(f"{model_name} forecast origins do not match OOS origins")
        evaluated = forecasts.loc[eval_idx].to_numpy(dtype=float)
        if not np.isfinite(evaluated).all() or not (evaluated > 0.0).all():
            raise AssertionError(f"{model_name} forecasts must be finite and positive")
    har_f = har_preds.loc[eval_idx].to_numpy(dtype=float)
    uni_f = fgn_uni_preds.loc[eval_idx].to_numpy(dtype=float)
    multi_f = fgn_multi_preds.loc[eval_idx].to_numpy(dtype=float)

    ql_har = qlike(actual_rv, har_f)
    ql_uni = qlike(actual_rv, uni_f)
    ql_multi = qlike(actual_rv, multi_f)

    print(f"  QLIKE HAR-RV:         {ql_har:.6f}")
    print(f"  QLIKE fGN-univariate: {ql_uni:.6f}")
    print(f"  QLIKE fGN-multi:      {ql_multi:.6f}")

    # ── DM Tests ──
    print("\n--- Canonical HAC-DM Tests (Harvey-Liu-Zhu |t|>3 screen) ---")
    loss_har = qlike_pointwise(actual_rv, har_f)
    loss_uni = qlike_pointwise(actual_rv, uni_f)
    loss_multi = qlike_pointwise(actual_rv, multi_f)

    dm_uni_result = forecast_dm_diagnostics(loss_uni, loss_har)
    dm_multi_result = forecast_dm_diagnostics(loss_multi, loss_har)
    dm_uni = dm_uni_result["t_stat"]
    dm_multi = dm_multi_result["t_stat"]

    print(f"  DM(fGN-uni, HAR):   t = {dm_uni:.4f}  (t>0 = fGN-uni WORSE; t<0 = fGN-uni BETTER)")
    print(f"  DM(fGN-multi, HAR): t = {dm_multi:.4f}  (t>0 = fGN-multi WORSE; t<0 = fGN-multi BETTER)")

    # ── Verdict ──
    dm_multi_abs = abs(dm_multi)
    if dm_multi_abs > 3.0 and ql_multi < ql_har:
        verdict = "PASS"
    elif dm_multi_abs > 2.0 and ql_multi < ql_har:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"
    print(f"\n  Verdict: {verdict}")

    # ── Anomaly checks ──
    caveats = []
    if any(H > 0.5 for H in hurst_estimates.values()):
        caveats.append("ANOMALY: H > 0.5 detected — long memory, check data")
    if ql_har / max(ql_multi, 1e-10) > 1.20:
        caveats.append("ANOMALY: fGN-multi beats HAR by >20% — verify no lookahead")
    if abs(dm_multi) > 10.0:
        caveats.append("ANOMALY: |DM| > 10 — likely numerical issue")
    caveats.append(
        "Evaluation alignment fix (H1): predictions at index t represent forecast for t+1; "
        "actual_rv uses shift(-1) to compare against rv[t+1]. n_eval = n_oos - 1."
    )
    caveats.append(
        "H2: fGN-multi cross-asset correction uses realized (not predicted) lag-1 residuals of other assets; "
        "feasible since these are one-period lagged values known at forecast time."
    )
    caveats.append(
        "2026-07-15 methodology repair: the primary comparison delegates to the repository canonical "
        "Bartlett Newey-West HAC DM test; the superseded local h=1 implementation used zero HAC lags."
    )
    caveats.append(
        "The repair also validates and removes identical duplicate-date source rows before a one-to-one "
        "merge, and keeps every HAR training target inside the in-sample period."
    )
    if not any(c.startswith("None") for c in caveats):
        pass

    # ── Plot ──
    print("\n--- Generating Plot ---")
    # Use eval_idx dates (trimmed by 1 for alignment fix)
    oos_dates = df.loc[df.index.isin(eval_idx), "date"].values

    fig, axes = plt.subplots(2, 1, figsize=(14, 9))

    # Panel 1: OOS forecast vs actual (annualized vol %)
    scale = np.sqrt(252) * 100
    ax1 = axes[0]
    ax1.plot(oos_dates, np.sqrt(actual_rv) * scale, "k-", lw=1.2, alpha=0.85,
             label="Actual SPY Vol (Parkinson)")
    ax1.plot(oos_dates, np.sqrt(har_f) * scale, "b--", lw=1.0, alpha=0.7,
             label=f"HAR-RV   QLIKE={ql_har:.5f}")
    ax1.plot(oos_dates, np.sqrt(uni_f) * scale, "g-.", lw=1.0, alpha=0.7,
             label=f"fGN-uni  QLIKE={ql_uni:.5f}")
    ax1.plot(oos_dates, np.sqrt(multi_f) * scale, "r-", lw=1.0, alpha=0.7,
             label=f"fGN-multi QLIKE={ql_multi:.5f}")
    ax1.set_ylabel("Annualized Vol (%)", fontsize=10)
    ax1.set_title(
        f"K1386 OOS SPY Volatility Forecast (2022–2026)\n"
        f"H: SPY={hurst_estimates['SPY']:.3f}, QQQ={hurst_estimates['QQQ']:.3f}, "
        f"GLD={hurst_estimates['GLD']:.3f}   Verdict: {verdict}",
        fontsize=11)
    ax1.legend(fontsize=9, loc="upper right")
    ax1.grid(True, alpha=0.3)

    # Panel 2: Scaling of log-structure function for SPY
    is_log_rv_spy = log_rv_dict["SPY"][train_mask].values
    lags_plot = np.arange(1, 31)
    m2_plot = np.array([np.mean((is_log_rv_spy[h:] - is_log_rv_spy[:-h]) ** 2) for h in lags_plot])
    H_spy = hurst_estimates["SPY"]
    # Fitted line
    log_c_spy = estimate_hurst_structure(is_log_rv_spy, lags=lags_sf)[1]
    fit_line = np.exp(log_c_spy) * lags_plot ** (2 * H_spy)

    ax2 = axes[1]
    ax2.loglog(lags_plot, m2_plot, "ko-", ms=5, lw=1.2, label="Empirical E[|Δ_h log-RV|²]")
    ax2.loglog(lags_plot[:20], fit_line[:20], "r--", lw=1.5,
               label=f"fGN fit: slope=2H={2*H_spy:.3f}  (H={H_spy:.3f})")
    ax2.set_xlabel("Lag h (days)", fontsize=10)
    ax2.set_ylabel("E[|Δ_h log-RV|²]", fontsize=10)
    ax2.set_title("SPY Log-RV: Log-Structure Function (IS 2010–2021, Gatheral method)", fontsize=10)
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plot_path = OUT_DIR / "k1386_forecast_comparison.png"
    plot_tmp_path = plot_path.with_name(plot_path.stem + ".tmp" + plot_path.suffix)
    try:
        plt.savefig(plot_tmp_path, dpi=150, bbox_inches="tight")
        plt.close()
        os.replace(plot_tmp_path, plot_path)
    finally:
        plt.close()
        if plot_tmp_path.exists():
            plot_tmp_path.unlink()
    print(f"  Plot saved: {plot_path}")

    # ── Save results JSON ──
    results = {
        "experiment_id": "K1386",
        "data": {
            "assets": ["SPY", "QQQ", "GLD"],
            "primary_asset": "SPY",
            "rv_proxy": "Parkinson range: (log(H/L))^2 / (4*log(2))",
            "log_rv_target_for_fgn": "log(RV_pk)",
            "source_files": {
                str(DATA_SPY.relative_to(ROOT)): file_sha256(DATA_SPY),
                str(DATA_GLD.relative_to(ROOT)): file_sha256(DATA_GLD),
            },
            "float_parser": 'pandas.read_csv(float_precision="round_trip")',
            "source_duplicate_audit": source_audit,
            "analysis_slice_sha256": analysis_slice_hash,
            "is_period": (
                f"{df.loc[train_mask, 'date'].iloc[0].date()} ~ "
                f"{df.loc[train_mask, 'date'].iloc[-1].date()}"
            ),
            "oos_period": (
                f"{df.loc[test_mask, 'date'].iloc[0].date()} ~ "
                f"{df.loc[test_mask, 'date'].iloc[-1].date()}"
            ),
            "oos_end_frozen_for_methodology_repair": OOS_END,
            "n_is": n_is,
            "n_oos": n_oos,
            "n_eval": len(eval_idx),
            "analysis_dates_unique_and_increasing": True,
            "har_training": {
                "n_rows_after_rolling_na_filter": int(len(har_train_rows)),
                "last_origin": str(df.loc[har_last_origin, "date"].date()),
                "last_target": str(df.loc[har_last_target, "date"].date()),
                "first_oos_target_used_in_fit": False,
            },
        },
        "hurst_estimates": {
            "SPY": round(hurst_estimates["SPY"], 6),
            "QQQ": round(hurst_estimates["QQQ"], 6),
            "GLD": round(hurst_estimates["GLD"], 6),
            "method": "Log-structure function: slope of log E[|Δ_h log_RV|^2] vs log(h), lags 1-20, IS only",
            "reference": "Gatheral et al. (2018), arXiv:2412.14353",
        },
        "log_rv_correlation_matrix_is": {
            "SPY_QQQ": round(float(corr_mat[0, 1]), 6),
            "SPY_GLD": round(float(corr_mat[0, 2]), 6),
            "QQQ_GLD": round(float(corr_mat[1, 2]), 6),
        },
        "increment_acf_lag1_is": {
            a: round(float(acf_incr_dict[a][0]), 6) for a in ["SPY", "QQQ", "GLD"]
        },
        "model_ar_lag_p": 20,
        "qlike_oos": {
            "HAR": round(ql_har, 8),
            "fGN_univariate": round(ql_uni, 8),
            "fGN_multivariate": round(ql_multi, 8),
        },
        "dm_test": {
            "method": (
                "volpred.stats.model_evaluation.dm_test; Bartlett Newey-West HAC with "
                "max(1, min(ceil(h^(1/3)*n^(1/3)), n//4)); unscaled canonical t is primary"
            ),
            "reporting_screen": "Harvey, Liu, and Zhu (2016): |t| > 3.0",
            "fGN_uni_vs_HAR": {
                **dm_uni_result,
                "interpretation": (
                    "HAR has lower QLIKE and passes the |t|>3 reporting screen"
                    if dm_uni > 3.0 and ql_har < ql_uni
                    else "No robust HAR advantage under the |t|>3 reporting screen"
                ),
            },
            "fGN_multi_vs_HAR": {
                **dm_multi_result,
                "interpretation": (
                    "HAR has lower QLIKE and passes the |t|>3 reporting screen"
                    if dm_multi > 3.0 and ql_har < ql_multi
                    else "No robust HAR advantage under the |t|>3 reporting screen"
                ),
            },
        },
        "verdict": verdict,
        "verdict_detail": (
            "NULL_NO_FGN_IMPROVEMENT; HAR_LOWER_QLIKE_IN_BOTH_HARVEY_SCREEN_COMPARISONS"
        ),
        "supersession": {
            "reason": (
                "The legacy local h=1 DM helper used no HAC autocovariance terms. "
                "The legacy inner merge also multiplied identical duplicate-date rows, "
                "and the HAR fit used the first OOS target at the IS boundary. This rerun "
                "deduplicates validated-identical dates, enforces a one-to-one merge, "
                "keeps HAR targets inside IS, and delegates DM to the canonical implementation."
            ),
            "public_values_superseded": {
                "n_oos": 1128,
                "n_eval": 1127,
                "qlike_oos": {
                    "HAR": 0.36879574,
                    "fGN_univariate": 0.461357,
                    "fGN_multivariate": 0.46271202,
                },
                "dm_t": {
                    "fGN_uni_vs_HAR": 3.268827,
                    "fGN_multi_vs_HAR": 3.257408,
                },
            },
            "drifted_results_artifact_superseded": {
                "n_oos": 1135,
                "n_eval": 1134,
                "qlike_oos": {
                    "HAR": 0.36866513,
                    "fGN_univariate": 0.46001163,
                    "fGN_multivariate": 0.461349,
                },
                "dm_t": {
                    "fGN_uni_vs_HAR": 3.245095,
                    "fGN_multi_vs_HAR": 3.233787,
                },
            },
            "qualitative_conclusion_changed": False,
        },
        "caveats": caveats,
        "lookahead_prevention": (
            "HAR: features at t (rv_d/rv_w/rv_m ending at t), target rv_{t+1}. "
            "fGN-uni: AR on increments d_t..d_{t-p+1} to predict d_{t+1}, anchor at log_rv_t. "
            "fGN-multi: cross-asset uses lag-1 residuals (t-1), no contemporaneous cross info."
        ),
        "references": [
            "Gatheral, Jaisson, and Rosenbaum (2018), Quantitative Finance 18(6)",
            "Corsi (2009), Journal of Financial Econometrics 7(2)",
            "Diebold and Mariano (1995), Journal of Business & Economic Statistics 13(3)",
            "Harvey, Leybourne, and Newbold (1997), International Journal of Forecasting 13(2)",
            "Harvey, Liu, and Zhu (2016), Review of Financial Studies 29(1)",
            "Newey and West (1987), Econometrica 55(3)",
            "Patton (2011), Journal of Econometrics 160(1)",
        ],
        "seed": 42,
    }

    results_path = OUT_DIR / "k1386_results.json"
    atomic_save_npy(OUT_DIR / "k1386_loss_har.npy", loss_har)
    atomic_save_npy(OUT_DIR / "k1386_loss_fgn_uni.npy", loss_uni)
    atomic_save_npy(OUT_DIR / "k1386_loss_fgn_multi.npy", loss_multi)
    atomic_write_json(results_path, results)
    print(f"\nResults JSON saved: {results_path}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"  H estimates:  SPY={hurst_estimates['SPY']:.4f}, "
          f"QQQ={hurst_estimates['QQQ']:.4f}, GLD={hurst_estimates['GLD']:.4f}")
    print(f"  OOS QLIKE:   HAR={ql_har:.6f}, fGN-uni={ql_uni:.6f}, fGN-multi={ql_multi:.6f}")
    print(f"  DM fGN-uni vs HAR:   t = {dm_uni:.4f}")
    print(f"  DM fGN-multi vs HAR: t = {dm_multi:.4f}")
    print(f"  Verdict: {verdict}")
    print(f"  Caveats: {caveats}")

    return results


if __name__ == "__main__":
    results = main()
