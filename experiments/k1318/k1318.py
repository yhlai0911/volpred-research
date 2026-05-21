"""
K1318: HAR-RV 5-min Pilot — SPY & 0050.TW Actual Realized Variance

Compares HAR using actual 5-minute intraday realized variance vs daily-frequency
proxies (|r_t|, r²_t) for predicting true realized variance.

Lookahead-free certification:
  - All features at time t computed from data through t-1 only
  - rv_1d[t] = RV[t-1], rv_5d[t] = mean(RV[t-5..t-1]), etc.
  - Daily proxy features: abs_1d[t] = |r[t-1]|, sq_1d[t] = r[t-1]²
  - OLS fit uses only observations 0..t-1 to predict t (expanding window)

References:
  Andersen & Bollerslev (1998) JASA; Corsi (2009) JFEC; Harvey et al. (1997) JBES
"""

import numpy as np
import pandas as pd
import json
from pathlib import Path
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

np.random.seed(42)

# ─── Paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]  # worktree root (script is at experiments/k1318/k1318.py)
# Intraday RV data lives in the main repo, not the worktree (worktrees share git history but not untracked data/)
MAIN_REPO_ROOT = Path("/Users/yhlai0911/Desktop/volpred-research")
DATA_DIR = MAIN_REPO_ROOT / "data" / "intraday"
OUT_DIR = Path(__file__).resolve().parent

# ─── Load 5-min RV data ───────────────────────────────────────────────────────
def load_rv(path: Path) -> pd.Series:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "date"
    rv = df["rv_5min"].dropna()
    rv = rv[rv > 0]  # remove any zero/negative
    return rv.sort_index()

spy_rv = load_rv(DATA_DIR / "SPY_daily_rv.csv")
tw_rv = load_rv(DATA_DIR / "0050_TW_daily_rv.csv")

print(f"SPY RV: {len(spy_rv)} obs, {spy_rv.index[0].date()} ~ {spy_rv.index[-1].date()}")
print(f"0050.TW RV: {len(tw_rv)} obs, {tw_rv.index[0].date()} ~ {tw_rv.index[-1].date()}")

# ─── Load daily prices for proxy construction ─────────────────────────────────
def get_daily_returns(ticker: str, start: str = "2025-01-01", end: str = "2026-05-21") -> pd.Series:
    """Download daily adjusted close and compute log returns."""
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"Empty data for {ticker}")
        close = df["Close"].squeeze()
        ret = np.log(close / close.shift(1)).dropna()
        ret.index = ret.index.tz_localize(None).normalize()
        return ret
    except Exception as e:
        print(f"yfinance error for {ticker}: {e}")
        raise

print("Downloading daily returns from yfinance...")
spy_ret = get_daily_returns("SPY")
tw_ret = get_daily_returns("0050.TW")
print(f"SPY daily returns: {len(spy_ret)} obs")
print(f"0050.TW daily returns: {len(tw_ret)} obs")

# ─── Feature construction helpers ─────────────────────────────────────────────
def har_features_from_rv(rv: pd.Series) -> pd.DataFrame:
    """
    Build HAR features from 5-min RV series.
    # lookahead free: feature from t-1, target at t
    rv_1d[t] = RV[t-1]
    rv_5d[t] = mean(RV[t-5..t-1])
    rv_22d[t] = mean(RV[t-22..t-1])
    """
    df = pd.DataFrame(index=rv.index)
    df["target"] = rv.values  # RV[t]
    # lookahead free: feature from t-1, target at t
    df["rv_1d"] = rv.shift(1)          # RV[t-1]
    df["rv_5d"] = rv.shift(1).rolling(5).mean()   # mean(RV[t-5..t-1])
    df["rv_22d"] = rv.shift(1).rolling(22).mean()  # mean(RV[t-22..t-1])
    df = df.dropna()
    return df

def har_features_from_proxy(proxy: pd.Series, target: pd.Series) -> pd.DataFrame:
    """
    Build HAR features from daily return proxy (|r| or r²), targeting true RV.
    # lookahead free: feature from t-1, target at t
    """
    df = pd.DataFrame(index=target.index)
    df["target"] = target.values

    # Align proxy to target dates
    proxy_aligned = proxy.reindex(target.index).ffill()

    # lookahead free: feature from t-1, target at t
    df["p_1d"] = proxy_aligned.shift(1)
    df["p_5d"] = proxy_aligned.shift(1).rolling(5).mean()
    df["p_22d"] = proxy_aligned.shift(1).rolling(22).mean()
    df = df.dropna()
    return df

def ewma_forecast(daily_ret: pd.Series, target: pd.Series, lam: float = 0.94) -> pd.Series:
    """
    EWMA variance forecast: sigma²[t] = lam*sigma²[t-1] + (1-lam)*r[t-1]²
    Returns series aligned with target index.
    # lookahead free: uses r[t-1]² to forecast t
    """
    # Use daily returns, align to target
    r_sq = (daily_ret ** 2).reindex(target.index).ffill()

    ewma_var = np.full(len(target), np.nan)
    # Initialize with first non-nan r²
    valid_idx = np.where(~np.isnan(r_sq.values))[0]
    if len(valid_idx) == 0:
        return pd.Series(ewma_var, index=target.index)

    # Warm-up: initialize EWMA
    init = valid_idx[0]
    ewma_var[init] = r_sq.iloc[init]
    for i in range(init + 1, len(target)):
        r2 = r_sq.iloc[i - 1] if not np.isnan(r_sq.iloc[i - 1]) else 0.0
        ewma_var[i] = lam * ewma_var[i - 1] + (1 - lam) * r2

    result = pd.Series(ewma_var, index=target.index)
    # lookahead free: EWMA[t] uses r[t-1]
    return result

# ─── Evaluation metrics ────────────────────────────────────────────────────────
def qlike(actual: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(h/sigma² - log(h/sigma²) - 1) where h=forecast, sigma²=actual."""
    # Clip forecasts to avoid division by zero / log(0)
    eps = 1e-12
    f = np.maximum(forecast, eps)
    a = np.maximum(actual, eps)
    return float(np.mean(a / f - np.log(a / f) - 1))

def mse(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean((actual - forecast) ** 2))

def dm_test_hln(e1: np.ndarray, e2: np.ndarray) -> dict:
    """
    Diebold-Mariano test with Harvey-Leybourne-Newbold (1997) small-sample correction.
    e1, e2: loss differentials arrays (e1[i] - e2[i]) where e = QLIKE or MSE loss
    H0: E[d] = 0, d = e1 - e2
    Returns t-stat, p-value, and significance verdict.
    """
    n = len(e1)
    d = e1 - e2
    d_bar = np.mean(d)

    # Newey-West variance with lag h (h=1 for 1-step ahead)
    h = 1
    gamma_0 = np.var(d, ddof=1)
    gamma_k = 0.0
    for k in range(1, h):
        gamma_k += np.cov(d[k:], d[:-k], ddof=1)[0, 1]
    v_d = (gamma_0 + 2 * gamma_k) / n

    # HLN correction factor
    hln_factor = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)

    dm_stat = d_bar / np.sqrt(v_d)
    hln_stat = dm_stat * hln_factor  # corrected statistic

    # t-distribution with n-1 df (HLN)
    p_value = 2 * stats.t.sf(abs(hln_stat), df=n - 1)

    # Verdict
    if abs(hln_stat) > 3.0 and d_bar < 0:
        verdict = "PASS_HARVEY"
    elif abs(hln_stat) > 3.0 and d_bar > 0:
        verdict = "FAIL"
    elif 1.96 <= abs(hln_stat) <= 3.0 and d_bar < 0:
        verdict = "MARGINAL"
    else:
        verdict = "NULL"

    return {
        "dm_stat": float(dm_stat),
        "hln_stat": float(hln_stat),
        "p_value": float(p_value),
        "n_obs": n,
        "verdict": verdict,
        "d_bar": float(d_bar),
        "note": "negative d_bar = model1 better; HLN 1997 small-sample correction applied"
    }

# ─── OLS HAR estimator ─────────────────────────────────────────────────────────
def ols_predict(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray) -> np.ndarray:
    """Simple OLS: beta = (X'X)^-1 X'y, forecast = X_test @ beta."""
    try:
        beta = np.linalg.lstsq(X_train, y_train, rcond=None)[0]
        pred = X_test @ beta
        return np.maximum(pred, 1e-12)  # ensure positive forecasts
    except Exception:
        return np.full(len(X_test), np.mean(y_train))

def expanding_window_ols(feat_df: pd.DataFrame, min_train: int = 30) -> dict:
    """
    Expanding window OLS evaluation.
    feat_df columns: ['target', feat1, feat2, ...]
    Returns OOS predictions and actual values.
    """
    n = len(feat_df)
    targets = feat_df["target"].values
    feature_cols = [c for c in feat_df.columns if c != "target"]
    X = feat_df[feature_cols].values
    X_with_const = np.column_stack([np.ones(n), X])

    preds = np.full(n, np.nan)
    for t in range(min_train, n):
        X_train = X_with_const[:t]
        y_train = targets[:t]
        X_test = X_with_const[t:t+1]
        pred = ols_predict(X_train, y_train, X_test)
        preds[t] = pred[0]

    oos_mask = ~np.isnan(preds)
    return {
        "preds": preds[oos_mask],
        "actuals": targets[oos_mask],
        "oos_start": min_train,
        "n_oos": int(oos_mask.sum()),
        "dates": feat_df.index[oos_mask].tolist()
    }

def expanding_window_ols_log(feat_df: pd.DataFrame, min_train: int = 30) -> dict:
    """HAR on log(RV): log-scale features and target, back-transform for QLIKE/MSE."""
    eps = 1e-10
    log_df = feat_df.copy()
    for col in log_df.columns:
        log_df[col] = np.log(feat_df[col] + eps)

    n = len(log_df)
    log_targets = log_df["target"].values
    feature_cols = [c for c in log_df.columns if c != "target"]
    X = log_df[feature_cols].values
    X_with_const = np.column_stack([np.ones(n), X])

    log_preds = np.full(n, np.nan)
    for t in range(min_train, n):
        X_train = X_with_const[:t]
        y_train = log_targets[:t]
        X_test = X_with_const[t:t+1]
        pred = ols_predict(X_train, y_train, X_test)
        log_preds[t] = pred[0]

    oos_mask = ~np.isnan(log_preds)
    # Back-transform: exp(log_pred) - eps, clipped positive
    raw_preds = np.exp(log_preds[oos_mask]) - eps
    raw_preds = np.maximum(raw_preds, 1e-12)
    actuals = feat_df["target"].values[oos_mask]

    return {
        "preds": raw_preds,
        "actuals": actuals,
        "oos_start": min_train,
        "n_oos": int(oos_mask.sum()),
        "dates": feat_df.index[oos_mask].tolist()
    }

# ─── Main experiment loop ──────────────────────────────────────────────────────
def run_experiment(
    rv: pd.Series,
    daily_ret: pd.Series,
    asset_name: str,
    min_train: int = 30
) -> dict:
    print(f"\n{'='*60}")
    print(f"Asset: {asset_name} | RV obs: {len(rv)} | min_train: {min_train}")
    print(f"{'='*60}")

    # --- HAR-RV-5min features ---
    har_rv_df = har_features_from_rv(rv)
    print(f"HAR-RV-5min usable rows: {len(har_rv_df)}")

    # --- HAR-ABS features (|r|) ---
    abs_proxy = daily_ret.abs()
    har_abs_df = har_features_from_proxy(abs_proxy, rv)
    print(f"HAR-ABS usable rows: {len(har_abs_df)}")

    # --- HAR-SQ features (r²) ---
    sq_proxy = daily_ret ** 2
    har_sq_df = har_features_from_proxy(sq_proxy, rv)
    print(f"HAR-SQ usable rows: {len(har_sq_df)}")

    # --- EWMA-0.94 ---
    ewma_fc = ewma_forecast(daily_ret, rv, lam=0.94)

    # Intersect all dates for fair comparison
    common_dates = (
        har_rv_df.index
        .intersection(har_abs_df.index)
        .intersection(har_sq_df.index)
        .intersection(ewma_fc.dropna().index)
    )
    print(f"Common dates for fair comparison: {len(common_dates)}")

    # Subset to common dates
    har_rv_df = har_rv_df.loc[common_dates]
    har_abs_df = har_abs_df.loc[common_dates]
    har_sq_df = har_sq_df.loc[common_dates]
    ewma_common = ewma_fc.reindex(common_dates)

    # --- Run expanding window OLS ---
    res_rv = expanding_window_ols(har_rv_df, min_train)
    res_rv_log = expanding_window_ols_log(har_rv_df, min_train)
    res_abs = expanding_window_ols(har_abs_df, min_train)
    res_sq = expanding_window_ols(har_sq_df, min_train)

    # EWMA: use same OOS window as HAR-RV for fair comparison
    oos_start = min_train
    ewma_preds = ewma_common.values[oos_start:]
    oos_actuals = har_rv_df["target"].values[oos_start:]

    # Trim to valid EWMA (non-nan)
    valid = ~np.isnan(ewma_preds)
    ewma_preds_valid = ewma_preds[valid]
    oos_actuals_ewma = oos_actuals[valid]
    n_oos = len(ewma_preds_valid)

    print(f"\nOOS sample sizes: HAR-RV={res_rv['n_oos']}, HAR-ABS={res_abs['n_oos']}, "
          f"HAR-SQ={res_sq['n_oos']}, EWMA={n_oos}")

    # Align all to same OOS window length (take min overlap)
    min_oos = min(res_rv["n_oos"], res_abs["n_oos"], res_sq["n_oos"], res_rv_log["n_oos"], n_oos)

    def trim_last(arr, n):
        return arr[-n:]

    rv_p = trim_last(res_rv["preds"], min_oos)
    rv_log_p = trim_last(res_rv_log["preds"], min_oos)
    abs_p = trim_last(res_abs["preds"], min_oos)
    sq_p = trim_last(res_sq["preds"], min_oos)
    ewma_p = trim_last(ewma_preds_valid, min_oos)
    act = trim_last(res_rv["actuals"], min_oos)

    # --- Compute QLIKE and MSE ---
    def metrics(preds, actuals):
        return {
            "QLIKE": round(qlike(actuals, preds), 6),
            "MSE": float(f"{mse(actuals, preds):.6e}")
        }

    qlike_rv = metrics(rv_p, act)
    qlike_rv_log = metrics(rv_log_p, act)
    qlike_abs = metrics(abs_p, act)
    qlike_sq = metrics(sq_p, act)
    qlike_ewma = metrics(ewma_p, act)

    print(f"\nQLIKE results:")
    print(f"  HAR-RV-5min:     {qlike_rv['QLIKE']:.6f}")
    print(f"  HAR-RV-5min-LOG: {qlike_rv_log['QLIKE']:.6f}")
    print(f"  HAR-ABS:         {qlike_abs['QLIKE']:.6f}")
    print(f"  HAR-SQ:          {qlike_sq['QLIKE']:.6f}")
    print(f"  EWMA-0.94:       {qlike_ewma['QLIKE']:.6f}")

    # --- DM tests vs EWMA-0.94 ---
    # Compute per-observation QLIKE losses
    def qlike_loss_arr(actual, forecast):
        eps = 1e-12
        f = np.maximum(forecast, eps)
        a = np.maximum(actual, eps)
        return a / f - np.log(a / f) - 1

    loss_rv = qlike_loss_arr(act, rv_p)
    loss_rv_log = qlike_loss_arr(act, rv_log_p)
    loss_abs = qlike_loss_arr(act, abs_p)
    loss_sq = qlike_loss_arr(act, sq_p)
    loss_ewma = qlike_loss_arr(act, ewma_p)

    dm_rv_vs_ewma = dm_test_hln(loss_rv, loss_ewma)
    dm_rv_log_vs_ewma = dm_test_hln(loss_rv_log, loss_ewma)
    dm_abs_vs_ewma = dm_test_hln(loss_abs, loss_ewma)
    dm_sq_vs_ewma = dm_test_hln(loss_sq, loss_ewma)

    print(f"\nDM tests (HLN 1997) vs EWMA-0.94:")
    print(f"  HAR-RV-5min:     t={dm_rv_vs_ewma['hln_stat']:.3f}, p={dm_rv_vs_ewma['p_value']:.4f} → {dm_rv_vs_ewma['verdict']}")
    print(f"  HAR-RV-5min-LOG: t={dm_rv_log_vs_ewma['hln_stat']:.3f}, p={dm_rv_log_vs_ewma['p_value']:.4f} → {dm_rv_log_vs_ewma['verdict']}")
    print(f"  HAR-ABS:         t={dm_abs_vs_ewma['hln_stat']:.3f}, p={dm_abs_vs_ewma['p_value']:.4f} → {dm_abs_vs_ewma['verdict']}")
    print(f"  HAR-SQ:          t={dm_sq_vs_ewma['hln_stat']:.3f}, p={dm_sq_vs_ewma['p_value']:.4f} → {dm_sq_vs_ewma['verdict']}")

    return {
        "n_rv_obs_total": len(rv),
        "n_common_dates": len(common_dates),
        "n_oos": min_oos,
        "QLIKE": {
            "HAR_RV_5min": qlike_rv["QLIKE"],
            "HAR_RV_5min_LOG": qlike_rv_log["QLIKE"],
            "HAR_ABS": qlike_abs["QLIKE"],
            "HAR_SQ": qlike_sq["QLIKE"],
            "EWMA_094": qlike_ewma["QLIKE"]
        },
        "MSE": {
            "HAR_RV_5min": qlike_rv["MSE"],
            "HAR_RV_5min_LOG": qlike_rv_log["MSE"],
            "HAR_ABS": qlike_abs["MSE"],
            "HAR_SQ": qlike_sq["MSE"],
            "EWMA_094": qlike_ewma["MSE"]
        },
        "DM_vs_EWMA": {
            "HAR_RV_5min": dm_rv_vs_ewma,
            "HAR_RV_5min_LOG": dm_rv_log_vs_ewma,
            "HAR_ABS": dm_abs_vs_ewma,
            "HAR_SQ": dm_sq_vs_ewma
        }
    }

# ─── Run both assets ───────────────────────────────────────────────────────────
print("\nRunning SPY experiment...")
spy_results = run_experiment(spy_rv, spy_ret, "SPY", min_train=30)

print("\nRunning 0050.TW experiment...")
tw_results = run_experiment(tw_rv, tw_ret, "0050.TW", min_train=30)

# ─── Determine overall verdict ────────────────────────────────────────────────
def determine_verdict(spy_res: dict, tw_res: dict) -> tuple:
    """
    Overall verdict logic:
    - PASS_HARVEY: HAR-RV-5min DM PASS_HARVEY in at least one asset, MARGINAL or better in other
    - MARGINAL: HAR-RV-5min DM MARGINAL in at least one asset, NULL in other (small-sample caveat)
    - NULL: both NULL (small sample inconclusive, not evidence against)
    """
    spy_dm = spy_res["DM_vs_EWMA"]["HAR_RV_5min"]["verdict"]
    tw_dm = tw_res["DM_vs_EWMA"]["HAR_RV_5min"]["verdict"]
    spy_qlike_better = spy_res["QLIKE"]["HAR_RV_5min"] < spy_res["QLIKE"]["EWMA_094"]
    tw_qlike_better = tw_res["QLIKE"]["HAR_RV_5min"] < tw_res["QLIKE"]["EWMA_094"]

    both_verdicts = [spy_dm, tw_dm]
    if "PASS_HARVEY" in both_verdicts and all(v != "FAIL" for v in both_verdicts):
        verdict = "PASS_HARVEY"
    elif all(v in ("PASS_HARVEY", "MARGINAL") for v in both_verdicts):
        verdict = "MARGINAL"
    elif "MARGINAL" in both_verdicts and all(v != "FAIL" for v in both_verdicts):
        verdict = "MARGINAL"
    elif spy_qlike_better and tw_qlike_better:
        verdict = "NULL_DIRECTIONALLY_CONSISTENT"
    else:
        verdict = "NULL"

    rationale = (
        f"SPY: HAR-RV-5min DM t={spy_res['DM_vs_EWMA']['HAR_RV_5min']['hln_stat']:.3f} "
        f"({spy_dm}), QLIKE={spy_res['QLIKE']['HAR_RV_5min']:.6f} vs EWMA={spy_res['QLIKE']['EWMA_094']:.6f} "
        f"({'better' if spy_qlike_better else 'worse'}). "
        f"TW50: HAR-RV-5min DM t={tw_res['DM_vs_EWMA']['HAR_RV_5min']['hln_stat']:.3f} "
        f"({tw_dm}), QLIKE={tw_res['QLIKE']['HAR_RV_5min']:.6f} vs EWMA={tw_res['QLIKE']['EWMA_094']:.6f} "
        f"({'better' if tw_qlike_better else 'worse'}). "
        f"Small-sample power issue (SPY n≈{spy_res['n_oos']}, TW50 n≈{tw_res['n_oos']}): NULL = inconclusive."
    )
    return verdict, rationale

verdict, rationale = determine_verdict(spy_results, tw_results)
print(f"\n{'='*60}")
print(f"OVERALL VERDICT: {verdict}")
print(f"Rationale: {rationale}")
print(f"{'='*60}")

# ─── Save results JSON ─────────────────────────────────────────────────────────
results = {
    "experiment_id": "K1318",
    "lookahead_free_certification": (
        "All features computed from past data only (lag >= 1); "
        "rv_1d[t]=RV[t-1], rv_5d[t]=mean(RV[t-5..t-1]), rv_22d[t]=mean(RV[t-22..t-1]); "
        "daily proxy: abs_1d[t]=|r[t-1]|, sq_1d[t]=r[t-1]^2; "
        "EWMA[t] uses r[t-1]^2; expanding OLS fit on [0..t-1] predicts t; "
        "code lines verified: shift(1) throughout"
    ),
    "data_source": {
        "spy_rv": "data/intraday/SPY_daily_rv.csv",
        "tw_rv": "data/intraday/0050_TW_daily_rv.csv",
        "daily_prices": "yfinance SPY & 0050.TW 2025-01-01~2026-05-21"
    },
    "sample_sizes": {
        "spy_rv_total": len(spy_rv),
        "tw_rv_total": len(tw_rv),
        "spy_oos": spy_results["n_oos"],
        "tw_oos": tw_results["n_oos"]
    },
    "models": ["HAR_RV_5min", "HAR_RV_5min_LOG", "HAR_ABS", "HAR_SQ", "EWMA_094"],
    "results": {
        "SPY": spy_results,
        "TW50": tw_results
    },
    "verdict": verdict,
    "verdict_rationale": rationale,
    "methodology": {
        "oos_type": "expanding_window",
        "min_train_days": 30,
        "dm_correction": "HLN_1997_small_sample",
        "significance_level": 0.01,
        "harvey_threshold": 3.0,
        "loss_function": "QLIKE",
        "random_seed": 42
    },
    "prior_context": {
        "K530": "HAR-ABS QLIKE=-3.892 (daily |r| target); HAR expected stronger with true 5-min RV",
        "K782": "HAR loses to GJR on r^2 target; proxy quality matters more than model"
    }
}

out_path = OUT_DIR / "k1318_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {out_path}")
print(f"\nKey numbers for README:")
print(f"SPY  — HAR-RV: {spy_results['QLIKE']['HAR_RV_5min']:.6f} | HAR-ABS: {spy_results['QLIKE']['HAR_ABS']:.6f} | HAR-SQ: {spy_results['QLIKE']['HAR_SQ']:.6f} | EWMA: {spy_results['QLIKE']['EWMA_094']:.6f}")
print(f"TW50 — HAR-RV: {tw_results['QLIKE']['HAR_RV_5min']:.6f} | HAR-ABS: {tw_results['QLIKE']['HAR_ABS']:.6f} | HAR-SQ: {tw_results['QLIKE']['HAR_SQ']:.6f} | EWMA: {tw_results['QLIKE']['EWMA_094']:.6f}")
print(f"SPY DM (HAR-RV vs EWMA): t={spy_results['DM_vs_EWMA']['HAR_RV_5min']['hln_stat']:.3f} → {spy_results['DM_vs_EWMA']['HAR_RV_5min']['verdict']}")
print(f"TW50 DM (HAR-RV vs EWMA): t={tw_results['DM_vs_EWMA']['HAR_RV_5min']['hln_stat']:.3f} → {tw_results['DM_vs_EWMA']['HAR_RV_5min']['verdict']}")
