"""K1333: VIX vol-of-vol (self-constructed) as predictor of next-day VIX change.

Research question
-----------------
Does a self-constructed vol-of-vol on VIX log-returns (short=5d, long=22d
realized vol of dlog(VIX)) predict next-day VIX level and |Delta VIX|,
beyond an AR(1) baseline on VIX changes?

Honesty hard rules enforced here
--------------------------------
- All predictors `.shift(1)`: t-1 features predict t outcome. Realized vol
  windows themselves use returns up to and including t-1 (no t leakage).
- Seed = 42 for bootstrap.
- Baselines:
    * naive (random walk on VIX level / zero-change naive on |dVIX|)
    * AR(1) on dVIX (using only past info, expanding fit on train+val).
- Splits: 2010-2019 train, 2020-2023 validation, 2024-2026 OOS test.
  Coefficients are estimated by expanding window on train+val data using only
  information up to t-1 (so OOS forecasts are out-of-sample in the strict sense).
- Tests: HAC-DM (Newey-West, h=1; this is NOT Harvey-Leybourne-Newbold
  finite-sample adjusted), Patton QLIKE on positive targets, MSE / MAE,
  paired stationary bootstrap CI (B=2000).
- Reports R^2_OOS (Campbell-Thompson) vs each baseline.
- NULL result reported as-is; no over-claim.

Outputs
-------
- experiments/k1333/k1333_results.json
- experiments/k1333/k1333_vix_volofvol.png
"""

from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise  # noqa: E402

# ---- Configuration ----
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "k1333_results.json"
FIG_PATH = HERE / "k1333_vix_volofvol.png"

START = "2010-01-01"
END = "2026-06-14"

SHORT_WIN = 5
LONG_WIN = 22
ANN = 252

# Split boundaries (inclusive on the lower side, exclusive on the upper)
TRAIN_END = "2020-01-01"   # 2010 - 2019
VAL_END = "2024-01-01"     # 2020 - 2023
TEST_END = "2026-06-14"    # 2024 - 2026

BOOT_B = 2000
BLOCK_LEN = 10  # stationary bootstrap geometric mean block length

EPS = 1e-12


# ---- Data fetch ----
def fetch_vix() -> pd.Series:
    raw = yf.download(
        "^VIX",
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty VIX frame")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
    else:
        close = raw["Close"]
    close = close.dropna().astype(float)
    close.index = pd.to_datetime(close.index)
    close.name = "VIX"
    return close


# ---- Feature build ----
def build_features(vix: pd.Series) -> pd.DataFrame:
    """Build vol-of-vol features. All predictors will be .shift(1) at use.

    The realized vol at time t uses returns r_{t-w+1}, ..., r_t. To predict
    target at t+1, we then shift the entire predictor frame by 1, so
    information used is only up to t (no future leak).
    """
    df = pd.DataFrame({"VIX": vix})
    df["r"] = np.log(df["VIX"]).diff()
    df["r2"] = df["r"] ** 2

    # Realized vol annualized (square root of sample variance * 252)
    df["rv_short"] = np.sqrt(ANN * df["r2"].rolling(SHORT_WIN, min_periods=SHORT_WIN).mean())
    df["rv_long"] = np.sqrt(ANN * df["r2"].rolling(LONG_WIN, min_periods=LONG_WIN).mean())

    # Lag-1 jump proxy: |r_{t-1}| if it exceeded 2 * rv_long_{t-1}
    r_lag1 = df["r"].shift(1)
    rv_long_lag1 = df["rv_long"].shift(1)
    # rv_long is annualized in log-return space -> daily sigma = rv_long / sqrt(252)
    sigma_daily_lag1 = rv_long_lag1 / np.sqrt(ANN)
    jump_mask = (r_lag1.abs() > 2.0 * sigma_daily_lag1).astype(float)
    df["jump_proxy"] = r_lag1.abs() * jump_mask

    # Targets at time t (today)
    df["target_level"] = df["VIX"]
    df["target_abs_change"] = df["VIX"].diff().abs()

    df["delta_vix"] = df["VIX"].diff()

    df = df.dropna(subset=["rv_short", "rv_long"]).copy()
    return df


# ---- Expanding-window OOS forecast ----
def expanding_ols_forecast(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    train_val_end_idx: int,
    test_idx_start: int,
    refit_freq: int = 21,
) -> np.ndarray:
    """Expanding OLS using only information up to row i-1 for the prediction at row i.

    - The model fits OLS on rows [0 : i] (features already shifted) with
      target on the same rows. Because features are .shift(1)-aligned, the
      regression uses past info only.
    - Refits every `refit_freq` steps to keep cost manageable.
    """
    n = len(df)
    X = df[feature_cols].to_numpy(dtype=np.float64)
    y = df[target_col].to_numpy(dtype=np.float64)
    # add intercept
    Xc = np.column_stack([np.ones(n), X])

    preds = np.full(n, np.nan)

    # Use train_val_end_idx as anchor for minimum training size for OOS preds.
    last_beta = None
    last_fit_at = -10**9
    for i in range(test_idx_start, n):
        # fit using rows [0 : i] (predicting i, fit ends at i-1)
        if last_beta is None or (i - last_fit_at) >= refit_freq:
            Xtr = Xc[:i]
            ytr = y[:i]
            valid = np.all(np.isfinite(Xtr), axis=1) & np.isfinite(ytr)
            if valid.sum() < Xc.shape[1] + 10:
                continue
            Xtr = Xtr[valid]
            ytr = ytr[valid]
            try:
                beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
            except np.linalg.LinAlgError:
                continue
            last_beta = beta
            last_fit_at = i

        xi = Xc[i]
        if not np.all(np.isfinite(xi)):
            continue
        preds[i] = float(xi @ last_beta)

    return preds


def ar1_forecast(
    df: pd.DataFrame,
    target_col: str,
    target_kind: str,
    test_idx_start: int,
    refit_freq: int = 21,
) -> np.ndarray:
    """AR(1) baseline on dVIX (target_kind='level') or on |dVIX| (target_kind='abs').

    For target_level (= VIX_t), the AR(1) on delta gives prediction
    VIX_hat_t = VIX_{t-1} + alpha + phi * dVIX_{t-1}.

    For target_abs_change (= |dVIX_t|), the AR(1) on |dVIX| gives
    yhat_t = alpha + phi * |dVIX_{t-1}|.
    """
    n = len(df)
    if target_kind == "level":
        # use lagged delta as feature
        feat_full = df["delta_vix"].shift(1).to_numpy(dtype=np.float64)
        y = df["delta_vix"].to_numpy(dtype=np.float64)
        vix = df["VIX"].to_numpy(dtype=np.float64)
    elif target_kind == "abs":
        feat_full = df["target_abs_change"].shift(1).to_numpy(dtype=np.float64)
        y = df["target_abs_change"].to_numpy(dtype=np.float64)
        vix = None
    else:
        raise ValueError(target_kind)

    preds = np.full(n, np.nan)
    last_beta = None
    last_fit_at = -10**9
    Xc_full = np.column_stack([np.ones(n), feat_full])

    for i in range(test_idx_start, n):
        if last_beta is None or (i - last_fit_at) >= refit_freq:
            Xtr = Xc_full[:i]
            ytr = y[:i]
            valid = np.all(np.isfinite(Xtr), axis=1) & np.isfinite(ytr)
            if valid.sum() < 30:
                continue
            try:
                beta, *_ = np.linalg.lstsq(Xtr[valid], ytr[valid], rcond=None)
            except np.linalg.LinAlgError:
                continue
            last_beta = beta
            last_fit_at = i

        xi = Xc_full[i]
        if not np.all(np.isfinite(xi)):
            continue
        yhat = float(xi @ last_beta)
        if target_kind == "level":
            preds[i] = vix[i - 1] + yhat
        else:
            # ensure non-negative for |dVIX|
            preds[i] = max(yhat, EPS)

    return preds


def naive_forecast(df: pd.DataFrame, target_kind: str, test_idx_start: int) -> np.ndarray:
    """Naive baseline.

    - target_kind='level': random walk -> VIX_hat_t = VIX_{t-1}.
    - target_kind='abs': last-value -> |dVIX|_hat_t = |dVIX|_{t-1}.
    """
    n = len(df)
    preds = np.full(n, np.nan)
    if target_kind == "level":
        v = df["VIX"].to_numpy(dtype=np.float64)
        for i in range(test_idx_start, n):
            preds[i] = v[i - 1]
    else:
        a = df["target_abs_change"].to_numpy(dtype=np.float64)
        for i in range(test_idx_start, n):
            preds[i] = max(a[i - 1], EPS)
    return preds


# ---- Predictor specifications ----
def build_predictor_frames(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return shifted predictor frames for each spec.

    Predictors at time t use info up to t-1. We achieve this by .shift(1)
    on the raw feature columns whose latest input is r_t.
    """
    base = df.copy()
    base["rv_short_lag1"] = base["rv_short"].shift(1)
    base["rv_long_lag1"] = base["rv_long"].shift(1)
    base["VIX_lag1"] = base["VIX"].shift(1)
    base["r_lag1"] = base["r"].shift(1)
    # jump_proxy was already a t-1 quantity by construction
    return {
        "M1": base[["rv_short_lag1", "rv_long_lag1"]],
        "M2": base[["rv_short_lag1", "rv_long_lag1", "jump_proxy",
                    "VIX_lag1", "r_lag1"]],
    }


# ---- Coefficient table (full-sample, with HAC SE) ----
def hac_se(X: np.ndarray, y: np.ndarray, lag: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """OLS beta + Newey-West HAC SE (Bartlett kernel)."""
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    S = (resid[:, None] * X)
    omega = S.T @ S / n
    for L in range(1, lag + 1):
        w = 1.0 - L / (lag + 1)
        S1 = S[L:]
        S2 = S[:-L]
        gamma = S1.T @ S2 / n
        omega += w * (gamma + gamma.T)
    cov = XtX_inv @ omega @ XtX_inv * n
    se = np.sqrt(np.diag(cov))
    return beta, se


def coef_table(df: pd.DataFrame, X_frame: pd.DataFrame, target: str) -> list[dict]:
    cols = list(X_frame.columns)
    Xy = pd.concat([X_frame, df[target].rename("__y__")], axis=1).dropna()
    X = np.column_stack([np.ones(len(Xy)), Xy[cols].to_numpy(dtype=np.float64)])
    y = Xy["__y__"].to_numpy(dtype=np.float64)
    beta, se = hac_se(X, y, lag=5)
    names = ["intercept"] + cols
    rows = []
    for name, b, s in zip(names, beta, se):
        t = b / s if s > 0 else math.nan
        rows.append({"name": name, "coef": float(b), "se": float(s),
                     "t_stat": float(t)})
    return rows


# ---- R^2_OOS Campbell-Thompson ----
def r2_oos(actual: np.ndarray, pred_model: np.ndarray, pred_bench: np.ndarray) -> float:
    valid = np.isfinite(actual) & np.isfinite(pred_model) & np.isfinite(pred_bench)
    if valid.sum() < 30:
        return float("nan")
    a = actual[valid]
    m = pred_model[valid]
    b = pred_bench[valid]
    num = np.sum((a - m) ** 2)
    den = np.sum((a - b) ** 2)
    if den <= 0:
        return float("nan")
    return float(1.0 - num / den)


# ---- Paired stationary bootstrap CI on loss differential ----
def stationary_bootstrap_ci(
    d: np.ndarray, B: int = BOOT_B, block_len: int = BLOCK_LEN, seed: int = SEED
) -> tuple[float, float]:
    """95% percentile CI for mean(d) under stationary bootstrap."""
    rng = np.random.default_rng(seed)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return (float("nan"), float("nan"))
    p = 1.0 / block_len
    means = np.empty(B)
    for b in range(B):
        idx = np.empty(n, dtype=np.int64)
        i = int(rng.integers(0, n))
        for t in range(n):
            idx[t] = i
            if rng.random() < p:
                i = int(rng.integers(0, n))
            else:
                i = (i + 1) % n
        means[b] = float(np.mean(d[idx]))
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(lo), float(hi)


# ---- Main ----
def main() -> dict:
    print("[K1333] fetching VIX...")
    vix = fetch_vix()
    print(f"[K1333] {len(vix)} VIX observations from {vix.index[0].date()} to {vix.index[-1].date()}")

    df = build_features(vix)
    n = len(df)
    print(f"[K1333] {n} observations after feature build")

    # split indices
    dates = df.index
    train_end = pd.Timestamp(TRAIN_END)
    val_end = pd.Timestamp(VAL_END)
    test_start_idx = int(np.searchsorted(dates, val_end))
    # test_idx_start anchors where OOS forecasts begin
    train_n = int(np.searchsorted(dates, train_end))
    val_n = test_start_idx - train_n
    test_n = n - test_start_idx
    print(f"[K1333] train={train_n} val={val_n} test={test_n}")

    spec_frames = build_predictor_frames(df)

    results: dict = {
        "k_id": "K1333",
        "title": "VIX vol-of-vol (self-constructed) for next-day VIX prediction",
        "created_at": datetime.now(UTC).isoformat(),
        "config": {
            "start": START, "end": END,
            "short_window": SHORT_WIN, "long_window": LONG_WIN,
            "train_end": TRAIN_END, "val_end": VAL_END, "test_end": TEST_END,
            "boot_B": BOOT_B, "block_len": BLOCK_LEN, "seed": SEED,
        },
        "data": {
            "n_total": int(n),
            "n_train": int(train_n),
            "n_val": int(val_n),
            "n_test": int(test_n),
            "first_date": str(dates[0].date()),
            "last_date": str(dates[-1].date()),
            "test_first_date": str(dates[test_start_idx].date()),
        },
        "targets": {},
    }

    # Targets we evaluate
    target_specs = [
        {"key": "level", "col": "target_level", "kind": "level",
         "label": "VIX level (t+1)"},
        {"key": "abs_change", "col": "target_abs_change", "kind": "abs",
         "label": "|Delta VIX| (t+1)"},
    ]

    for tspec in target_specs:
        tkey = tspec["key"]
        col = tspec["col"]
        kind = tspec["kind"]
        actual = df[col].to_numpy(dtype=np.float64)

        # baselines
        pred_naive = naive_forecast(df, kind, test_start_idx)
        pred_ar1 = ar1_forecast(df, col, kind, test_start_idx)

        # vol-of-vol specs
        spec_preds: dict[str, np.ndarray] = {}
        for spec_name, X_frame in spec_frames.items():
            df_for_fit = pd.concat([X_frame, df[col].rename("__y__"), df["VIX"]], axis=1)
            # Build a temporary frame for the forecaster: index aligned
            feat_cols = list(X_frame.columns)
            tmp = df_for_fit.dropna(subset=feat_cols + ["__y__"]).copy()
            # We need indices that align with full df for OOS evaluation
            # Strategy: run expanding OLS on the *full* df with NaNs handled in fit
            full = pd.concat([X_frame, df[col].rename(col)], axis=1)
            preds_raw = expanding_ols_forecast(
                full.rename(columns={col: col}),
                feature_cols=feat_cols,
                target_col=col,
                train_val_end_idx=train_n,
                test_idx_start=test_start_idx,
            )
            # For target_kind='level' we modelled VIX_t directly via features.
            # For target_kind='abs' we modelled |dVIX_t| directly.
            if kind == "abs":
                preds_raw = np.where(np.isfinite(preds_raw),
                                     np.maximum(preds_raw, EPS), np.nan)
            spec_preds[spec_name] = preds_raw

        # Restrict to OOS test region
        oos_slice = slice(test_start_idx, n)
        a_oos = actual[oos_slice]
        naive_oos = pred_naive[oos_slice]
        ar1_oos = pred_ar1[oos_slice]

        per_spec_results = {}
        for spec_name, preds_full in spec_preds.items():
            p_oos = preds_full[oos_slice]
            valid = np.isfinite(a_oos) & np.isfinite(p_oos) & np.isfinite(ar1_oos) & np.isfinite(naive_oos)
            a_v = a_oos[valid]
            p_v = p_oos[valid]
            ar_v = ar1_oos[valid]
            nv_v = naive_oos[valid]

            mse_model = float(np.mean((a_v - p_v) ** 2))
            mae_model = float(np.mean(np.abs(a_v - p_v)))
            mse_ar1 = float(np.mean((a_v - ar_v) ** 2))
            mae_ar1 = float(np.mean(np.abs(a_v - ar_v)))
            mse_naive = float(np.mean((a_v - nv_v) ** 2))
            mae_naive = float(np.mean(np.abs(a_v - nv_v)))

            r2_vs_naive = r2_oos(a_v, p_v, nv_v)
            r2_vs_ar1 = r2_oos(a_v, p_v, ar_v)

            # DM tests using SE loss (consistent with MSE comparisons)
            se_model = (a_v - p_v) ** 2
            se_ar1 = (a_v - ar_v) ** 2
            se_naive = (a_v - nv_v) ** 2
            dm_vs_ar1 = dm_test(se_model, se_ar1, h=1)
            dm_vs_naive = dm_test(se_model, se_naive, h=1)

            # QLIKE only valid for positive targets (level and abs)
            if (a_v > 0).all() and (p_v > 0).all() and (ar_v > 0).all() and (nv_v > 0).all():
                ql_model = qlike(a_v, p_v)
                ql_ar1 = qlike(a_v, ar_v)
                ql_naive = qlike(a_v, nv_v)
                ql_model_pt = qlike_pointwise(a_v, p_v)
                ql_ar1_pt = qlike_pointwise(a_v, ar_v)
                ql_naive_pt = qlike_pointwise(a_v, nv_v)
                dm_qlike_vs_ar1 = dm_test(ql_model_pt, ql_ar1_pt, h=1)
                dm_qlike_vs_naive = dm_test(ql_model_pt, ql_naive_pt, h=1)
            else:
                ql_model = ql_ar1 = ql_naive = float("nan")
                dm_qlike_vs_ar1 = dm_qlike_vs_naive = (float("nan"), float("nan"))

            # Bootstrap CI on loss differential (model - AR1) using SE losses
            d_se = se_model - se_ar1
            lo, hi = stationary_bootstrap_ci(d_se)

            # Coefficient table (full-sample OLS w/ HAC SE, for reporting)
            coefs = coef_table(df, spec_frames[spec_name], col)

            per_spec_results[spec_name] = {
                "n_oos": int(valid.sum()),
                "mse": {"model": mse_model, "ar1": mse_ar1, "naive": mse_naive},
                "mae": {"model": mae_model, "ar1": mae_ar1, "naive": mae_naive},
                "qlike": {"model": ql_model, "ar1": ql_ar1, "naive": ql_naive},
                "r2_oos_vs_naive": r2_vs_naive,
                "r2_oos_vs_ar1": r2_vs_ar1,
                "dm_vs_ar1_mse": {"t_stat": dm_vs_ar1[0], "p_value": dm_vs_ar1[1]},
                "dm_vs_naive_mse": {"t_stat": dm_vs_naive[0], "p_value": dm_vs_naive[1]},
                "dm_vs_ar1_qlike": {"t_stat": dm_qlike_vs_ar1[0],
                                    "p_value": dm_qlike_vs_ar1[1]},
                "dm_vs_naive_qlike": {"t_stat": dm_qlike_vs_naive[0],
                                      "p_value": dm_qlike_vs_naive[1]},
                "bootstrap_mean_se_diff_vs_ar1_ci95": [lo, hi],
                "coefficients_full_sample_hac": coefs,
            }

        results["targets"][tkey] = {
            "label": tspec["label"],
            "specs": per_spec_results,
        }

    # ---- Figure ----
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(df.index, df["VIX"], color="steelblue", lw=0.9, label="VIX")
    axes[0].set_ylabel("VIX")
    axes[0].legend(loc="upper right")
    axes[0].set_title("K1333: VIX and self-constructed vol-of-vol")

    axes[1].plot(df.index, df["rv_short"], color="tomato", lw=0.8,
                 label=f"rv_{SHORT_WIN}d (ann.)")
    axes[1].plot(df.index, df["rv_long"], color="black", lw=0.8,
                 label=f"rv_{LONG_WIN}d (ann.)")
    axes[1].set_ylabel("Vol-of-vol (ann.)")
    axes[1].legend(loc="upper right")
    axes[1].axvline(pd.Timestamp(TRAIN_END), color="grey", ls="--", lw=0.6)
    axes[1].axvline(pd.Timestamp(VAL_END), color="grey", ls="--", lw=0.6)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=130)
    plt.close(fig)

    # ---- Verdict logic ----
    # We test 4 (target, spec) cells. To avoid data-snooping false positives
    # we require: (a) at least one cell beats AR1 at unadjusted p<0.05 with
    # positive R^2_OOS AND (b) survives Bonferroni correction across 4 tests
    # (p < 0.05/4 = 0.0125) for a strong PASS. Otherwise we tier:
    #   - "NULL"             — no cell beats AR1 at p<0.05
    #   - "CONDITIONAL_PASS" — >=1 cell beats AR1 unadjusted but none survive
    #                         Bonferroni; report as weak positive evidence
    #   - "PASS"             — at least one cell survives Bonferroni
    notes = []
    any_unadj = False
    any_bonf = False
    bonf_alpha = 0.05 / 4
    for tkey in ("level", "abs_change"):
        for spec_name in ("M1", "M2"):
            r = results["targets"][tkey]["specs"][spec_name]
            t_ar1 = r["dm_vs_ar1_mse"]["t_stat"]
            p_ar1 = r["dm_vs_ar1_mse"]["p_value"]
            r2_ar1 = r["r2_oos_vs_ar1"]
            notes.append(
                f"{tkey}/{spec_name}: R2_oos vs AR1={r2_ar1:.4f}, "
                f"DM(t)={t_ar1:.2f}, p={p_ar1:.3f}"
            )
            beats = (
                np.isfinite(t_ar1) and t_ar1 < 0
                and np.isfinite(r2_ar1) and r2_ar1 > 0
            )
            if beats and p_ar1 < 0.05:
                any_unadj = True
            if beats and p_ar1 < bonf_alpha:
                any_bonf = True

    if any_bonf:
        verdict = "PASS"
    elif any_unadj:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"
    results["verdict"] = verdict
    results["verdict_notes"] = notes
    results["verdict_method"] = (
        "Bonferroni across 4 (target,spec) DM tests at family alpha=0.05; "
        "cell-level HAC-DM only (NOT HLN finite-sample adjusted)."
    )

    # ---- Write JSON ----
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[K1333] wrote results to {RESULTS_PATH}")
    print(f"[K1333] figure: {FIG_PATH}")
    print(f"[K1333] verdict: {verdict}")
    for note in notes:
        print("  -", note)
    return results


if __name__ == "__main__":
    main()
