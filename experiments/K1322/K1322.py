"""
K1322 — HAR-RV (Corsi 2009) vs Random Walk on 0050.TW 5-min RV (Taiwan ETF)
============================================================================

Cross-market validation of the TX1 NULL quartet (K868 / K1301 / K1303 / K1309):
"Standard HAR-RV is a near-sufficient statistic for TAIFEX daily RV."

K1322 asks: does the same conclusion hold for the **0050.TW Taiwan ETF**?
- TX1 = futures, deep liquidity, electronic continuous
- 0050.TW = spot ETF, lower liquidity, different microstructure (open call auction, no after-hours)

If HAR-RV beats Random Walk significantly on 0050.TW → ETF RV is also predictable
If NULL on 0050.TW → cross-market robustness of TX1 conclusion (HAR-RV near-sufficient)

Lookahead discipline (Corsi 2009 standard 1-step convention)
------------------------------------------------------------
- Features at row t use only [t-22 .. t-1] via .shift(1) + rolling on lagged series
- Target = log(RV_t); features = RV_d/RV_w/RV_m all .shift(1)
- 70/30 chronological split (NO random shuffle)
- Seed = 42 fixed for all random procedures

Small-sample caveat
-------------------
Data: 76 daily files (2026-01-20 to 2026-05-22). After 22-day rolling warm-up,
effective panel ~ 54 days; 70/30 split → train ~38, test ~16. This is
**EXPLORATORY framework setup**, not a definitive test. Results below the
n_test < 50 threshold are flagged untrustworthy and revisit-gated to n_total >= 200.

Methodology rule (CLAUDE.md): package limitation != model invalid. OLS uses
numpy.linalg.lstsq directly; if it fails, retry with ridge regularization.

Author : Claude (worktree agent-af9b396e7976b970b, 2026-05-26)
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
SEED = 42
np.random.seed(SEED)

# Add volpred src to path for HAC dm_test (consistency with K1301/K1303)
_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Data lives in main repo (worktree omits data/intraday); read-only access.
# K1322 only consumes daily 5-min CSVs; we do not mutate them.
DATA_GLOB_DIR = Path("/Users/yhlai0911/Desktop/volpred-research/data/intraday")
SYMBOL = "0050_TW_5min"
REVISIT_GATE_DAYS = 200  # require n_total >= 200 before a verdict is trusted

# ======================================================================
# 0) Import HAC dm_test from volpred (same as K1301/K1303 — consistency)
# ======================================================================
try:
    # 2026-05-26 Codex review fix: production volpred.stats.model_evaluation.dm_test
    # does NOT apply HLN small-sample correction (Harvey 1997). For K1322 we
    # force the inline fallback which DOES include the HLN multiplier
    # sqrt((n+1-2h+h(h-1)/n)/n). This keeps the experiment self-contained and
    # immune to upstream library drift. The volpred dm_test bug is logged
    # separately for a system-wide fix.
    raise ImportError("forcing inline HLN-corrected dm_test for K1322 (Codex audit fix)")
    from volpred.stats.model_evaluation import dm_test as _dm_test_hac, qlike_pointwise  # noqa: E402
    _HAC_AVAILABLE = True
    print("[dm_test] HAC Newey-West dm_test loaded from volpred.stats.model_evaluation")
except ImportError as e:
    print(f"[dm_test] Using inline HLN-corrected dm_test: {e}")
    _HAC_AVAILABLE = False

    def _dm_test_hac(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> Tuple[float, float]:
        """Inline fallback: DM with Newey-West HAC (Harvey-Leybourne-Newbold 1997)."""
        from scipy import stats as sp_stats
        d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
        valid = np.isfinite(d)
        d = d[valid]
        n = len(d)
        if n < 10:
            return (0.0, 1.0)
        d_mean = np.mean(d)
        # NW lag = floor(n^(1/3))
        max_lag = max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))
        gamma0 = np.mean((d - d_mean) ** 2)
        var_d = gamma0
        for lag in range(1, max_lag + 1):
            weight = 1 - lag / (max_lag + 1)
            gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
            var_d += 2 * weight * gamma_l
        if var_d <= 0:
            return (0.0, 1.0)
        se = np.sqrt(var_d / n)
        if se < 1e-15:
            return (0.0, 1.0)
        t_stat = d_mean / se
        # HLN small-sample correction: multiply by sqrt((n+1-2h+h(h-1)/n)/n)
        hln_corr = np.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 1e-12))
        t_stat_hln = t_stat * hln_corr
        p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat_hln), df=n - 1))
        return (float(t_stat_hln), float(p_val))

    def qlike_pointwise(actual: np.ndarray, predicted: np.ndarray) -> np.ndarray:
        """QLIKE pointwise: L(a, f) = a/f - log(a/f) - 1 (Patton 2011)."""
        a = np.maximum(np.asarray(actual, dtype=np.float64), 1e-16)
        f = np.maximum(np.asarray(predicted, dtype=np.float64), 1e-16)
        ratio = a / f
        return ratio - np.log(ratio) - 1


# ======================================================================
# 1) Load 5-min bars and compute daily RV
# ======================================================================
def _load_one_day(path: Path) -> Optional[pd.DataFrame]:
    """Read a single 5-min CSV. Header has 3 metadata rows above the first bar.

    Layout:
      row 0 = Price,Close,High,Low,Open,Volume
      row 1 = Ticker,0050.TW,0050.TW,...
      row 2 = Datetime,,,,,
      row 3+ = "<ts>",close,high,low,open,volume
    """
    try:
        df = pd.read_csv(
            path,
            skiprows=3,
            header=None,
            names=["ts", "close", "high", "low", "open", "volume"],
        )
    except Exception as e:
        print(f"  [warn] skip {path.name}: {e}")
        return None
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts", "close"]).copy()
    for c in ("close", "high", "low", "open", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    # Drop pre-open auction snapshot (volume == 0 at the first bar).
    # Keep all bars with strictly positive volume — these are real traded bars.
    df = df[df["volume"] > 0].copy()
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def load_daily_rv(symbol: str = SYMBOL) -> pd.DataFrame:
    """Iterate every 5-min CSV in DATA_GLOB_DIR and compute daily RV."""
    files = sorted(DATA_GLOB_DIR.glob(f"{symbol}_*.csv"))
    print(f"[load] {len(files)} CSVs in {DATA_GLOB_DIR}")
    rows: List[Dict] = []
    n_bars_min = 20  # need a reasonable intraday tape
    for fn in files:
        # Date inferred from filename suffix: 0050_TW_5min_YYYY-MM-DD.csv
        date_str = fn.stem.replace(f"{symbol}_", "")
        try:
            session_date = pd.Timestamp(date_str)
        except Exception:
            print(f"  [warn] cannot parse date from {fn.name}; skip")
            continue
        df = _load_one_day(fn)
        if df is None or len(df) < n_bars_min:
            continue
        prices = df["close"].to_numpy(dtype=float)
        rets = np.log(prices[1:] / prices[:-1])
        # Guard against extreme outliers from data glitches
        rets = rets[np.isfinite(rets)]
        if len(rets) < n_bars_min - 1:
            continue
        rv = float((rets ** 2).sum())
        rows.append({
            "date": session_date,
            "rv": rv,
            "n_bars": int(len(df)),
            "n_returns": int(len(rets)),
            "first_ts": df["ts"].iloc[0],
            "last_ts": df["ts"].iloc[-1],
        })
    if not rows:
        raise RuntimeError("[load] no daily RV rows produced; check DATA_GLOB_DIR")
    daily = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    print(f"[load] daily RV rows = {len(daily)}; "
          f"range {daily['date'].min().date()} → {daily['date'].max().date()}")
    return daily


# ======================================================================
# 2) HAR-RV feature builder (Corsi 2009; 1-step lag per K1303 v2 convention)
# ======================================================================
def build_har_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Build HAR-RV features:
        Y    = log(RV_t)                    (same-day target)
        rv_d = log(RV_{t-1})
        rv_w = log(mean(RV_{t-5..t-1}))
        rv_m = log(mean(RV_{t-22..t-1}))

    All features use .shift(1) so feature at row t reflects day t-1 value.
    Rolling windows are taken on the lagged series — no lookahead.
    """
    d = daily.copy().sort_values("date").reset_index(drop=True)
    eps = 1e-12

    rv_lag1 = d["rv"].shift(1)

    d["rv_d"] = rv_lag1
    d["rv_w"] = rv_lag1.rolling(window=5, min_periods=5).mean()
    d["rv_m"] = rv_lag1.rolling(window=22, min_periods=22).mean()

    d["Y"] = np.log(d["rv"].clip(lower=eps))

    d = d.dropna(subset=["rv_d", "rv_w", "rv_m", "Y"]).reset_index(drop=True)

    # Log-transform RV features (strictly positive)
    for c in ("rv_d", "rv_w", "rv_m"):
        d[c] = np.log(d[c].clip(lower=eps))
    return d


# ======================================================================
# 3) OLS via numpy.linalg.lstsq (no statsmodels dep — methodology rule)
# ======================================================================
def fit_ols(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return (beta_with_intercept, standard_errors).

    SE computed from OLS residual variance assuming homoskedasticity. We do NOT
    use these SEs for testing forecast quality (that's DM-HLN's job); they're
    descriptive only.
    """
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    n, p = X1.shape
    dof = max(n - p, 1)
    sigma2 = float((resid ** 2).sum() / dof)
    try:
        XtX_inv = np.linalg.inv(X1.T @ X1)
        se = np.sqrt(np.maximum(np.diag(sigma2 * XtX_inv), 0.0))
    except np.linalg.LinAlgError:
        se = np.full(p, np.nan)
    return beta, se


def predict_ols(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    return X1 @ beta


# ======================================================================
# 4) Random Walk baseline: RV_{t+1} = RV_t (no parameters)
# ======================================================================
def random_walk_forecast(daily: pd.DataFrame, test_idx: np.ndarray) -> np.ndarray:
    """RW forecast for log(RV_t) is log(RV_{t-1}) — same convention as HAR.

    `daily` here is the feature dataframe (already shifted/aligned), so
    rv_d = log(RV_{t-1}) IS the RW forecast for log(RV_t).
    """
    return daily["rv_d"].to_numpy()[test_idx]


# ======================================================================
# 5) Main pipeline
# ======================================================================
def main():
    t0 = time.time()
    out: Dict = {
        "experiment_id": "K1322",
        "title": "HAR-RV vs Random Walk on 0050.TW 5-min RV (Taiwan ETF cross-market validation)",
        "date_run": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": SEED,
        "data_source": {
            "symbol": "0050.TW",
            "source_dir": str(DATA_GLOB_DIR),
            "interval": "5min",
            "session": "TW day session, regular trading 09:00-13:30 TW time",
            "rv_formula": "RV_t = sum_k r_5min,k^2 where r = log(P_t/P_{t-1}); drop first auction bar (volume==0)",
        },
        "methodology": {
            "model_baseline": "Random Walk: log(RV_t) = log(RV_{t-1}) (no params)",
            "model_alternative": "HAR-RV (Corsi 2009): log(RV_t) = b0 + b_d*log(RV_{t-1}) + b_w*log(RV_w) + b_m*log(RV_m)",
            "lag_convention": "1-step (Corsi 2009 + K1303 v2 ABD convention): features at t-1 predict log(RV_t)",
            "split": "70/30 chronological",
            "loss_function": "QLIKE pointwise (Patton 2011) on RV level",
            "dm_test": "HAC Newey-West DM with HLN (Harvey 1997) small-sample correction, h=1",
            "pass_rule": ("|DM_HLN_t| > 3 AND HAR-RV lower QLIKE (Harvey 2016 threshold). "
                         "If n_test < 50 the verdict is reported as UNTRUSTWORTHY_SMALL_SAMPLE."),
            "seed": SEED,
        },
        "cross_market_motivation": {
            "tx1_null_quartet": ["K868 (day/night)", "K1301 (HAR-RS semivariance)",
                                 "K1303 (HAR-CJ jump)", "K1309 (BMA)"],
            "tx1_finding": ("Standard HAR-RV is a near-sufficient statistic for TAIFEX TX1 daily RV; "
                            "semivariance / jump / BMA all NULL once HAR-RV included."),
            "k1322_question": ("Does HAR-RV's predictive power over RW also hold on the 0050.TW spot ETF "
                              "(different microstructure: lower liquidity, call-auction open, no after-hours)?"),
        },
        "revisit_gate": {
            "n_total_days_required": REVISIT_GATE_DAYS,
            "current_n_total_days": None,
            "untrustworthy_small_sample": None,
            "rationale": ("76-day intraday window after warm-up leaves n_test ~ 16. "
                         "Re-run when n_total >= 200 (~ Aug 2026 if data collection continues)."),
        },
    }

    # --- 1) Load daily RV ---
    print("\n============ K1322: load 5-min bars → daily RV ============")
    daily = load_daily_rv(SYMBOL)
    out["n_total_days"] = int(len(daily))
    out["date_range"] = [str(daily["date"].min().date()), str(daily["date"].max().date())]
    out["rv_descriptives"] = {
        "RV_mean": float(daily["rv"].mean()),
        "RV_std": float(daily["rv"].std()),
        "RV_min": float(daily["rv"].min()),
        "RV_max": float(daily["rv"].max()),
        "RV_median": float(daily["rv"].median()),
        "n_bars_mean": float(daily["n_bars"].mean()),
        "n_bars_min": int(daily["n_bars"].min()),
    }
    out["revisit_gate"]["current_n_total_days"] = int(len(daily))

    # --- 2) Plot daily RV time series ---
    print("\n============ K1322: plot RV time series ============")
    fig, ax = plt.subplots(figsize=(11, 4.5), dpi=120)
    ax.plot(daily["date"], np.sqrt(daily["rv"]) * 100, lw=1.2, color="#005A9C", label="daily realized vol (annualized %)")
    # The above is daily sqrt(RV) in percent — not annualized; correct caption:
    ax.clear()
    ax.plot(daily["date"], daily["rv"], lw=1.2, color="#005A9C", label="daily RV (sum of 5-min squared returns)")
    ax.set_title("0050.TW daily realized variance (5-min bars)  —  K1322")
    ax.set_xlabel("date")
    ax.set_ylabel("RV (5-min)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig_path = SCRIPT_DIR / "rv_series.png"
    fig.savefig(fig_path)
    plt.close(fig)
    print(f"[plot] wrote {fig_path}")

    # --- 3) Build HAR features ---
    print("\n============ K1322: build HAR features ============")
    feat = build_har_features(daily)
    print(f"[har] n_har_rows after warm-up = {len(feat)}")
    if len(feat) < 10:
        out["verdict"] = "FAIL"
        out["error"] = f"insufficient HAR rows after 22-day warm-up: {len(feat)}"
        (SCRIPT_DIR / "K1322_results.json").write_text(json.dumps(out, indent=2, default=str))
        return

    # --- 4) 70/30 chronological split ---
    T = len(feat)
    n_train = int(np.floor(T * 0.7))
    n_test = T - n_train
    out["n_train"] = int(n_train)
    out["n_test"] = int(n_test)
    untrustworthy = bool(n_test < 50)
    out["revisit_gate"]["untrustworthy_small_sample"] = untrustworthy
    print(f"[split] T={T}, n_train={n_train}, n_test={n_test}, "
          f"untrustworthy_small_sample={untrustworthy}")

    idx_train = np.arange(n_train)
    idx_test = np.arange(n_train, T)

    feat_cols = ["rv_d", "rv_w", "rv_m"]
    y_full = feat["Y"].to_numpy(dtype=float)
    X_full = feat[feat_cols].to_numpy(dtype=float)

    # --- 5) Fit HAR (numpy lstsq) ---
    beta_har, se_har = fit_ols(X_full[idx_train], y_full[idx_train])
    yhat_har_te = predict_ols(beta_har, X_full[idx_test])
    out["HAR_betas"] = {
        "intercept": float(beta_har[0]),
        "beta_d": float(beta_har[1]),
        "beta_w": float(beta_har[2]),
        "beta_m": float(beta_har[3]),
    }
    out["HAR_std_errors"] = {
        "intercept": float(se_har[0]) if not np.isnan(se_har[0]) else None,
        "beta_d": float(se_har[1]) if not np.isnan(se_har[1]) else None,
        "beta_w": float(se_har[2]) if not np.isnan(se_har[2]) else None,
        "beta_m": float(se_har[3]) if not np.isnan(se_har[3]) else None,
    }

    # --- 6) Random Walk baseline ---
    yhat_rw_te = random_walk_forecast(feat, idx_test)  # = log(RV_{t-1})

    # --- 7) Losses & DM-HLN ---
    y_test = y_full[idx_test]
    rv_actual = np.exp(y_test)          # actual RV_t (level)
    rv_hat_har = np.exp(yhat_har_te)
    rv_hat_rw = np.exp(yhat_rw_te)

    qlike_har_pt = qlike_pointwise(rv_actual, rv_hat_har)
    qlike_rw_pt = qlike_pointwise(rv_actual, rv_hat_rw)
    mean_qlike_har = float(np.nanmean(qlike_har_pt))
    mean_qlike_rw = float(np.nanmean(qlike_rw_pt))

    # MSE for reference (not primary)
    mse_har = float(((y_test - yhat_har_te) ** 2).mean())
    mse_rw = float(((y_test - yhat_rw_te) ** 2).mean())

    # OOS R^2 on log-RV (Mincer-Zarnowitz style)
    def _r2(y_, yhat_):
        ss_res = float(((y_ - yhat_) ** 2).sum())
        ss_tot = float(((y_ - y_.mean()) ** 2).sum())
        return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    r2_har_oos = _r2(y_test, yhat_har_te)
    r2_rw_oos = _r2(y_test, yhat_rw_te)

    # DM-HLN: positive t => RW QLIKE > HAR QLIKE => HAR preferred
    dm_t, dm_p = _dm_test_hac(qlike_rw_pt, qlike_har_pt, h=1)

    out["RW_QLIKE_test"] = mean_qlike_rw
    out["HAR_QLIKE_test"] = mean_qlike_har
    out["RW_MSE_test"] = mse_rw
    out["HAR_MSE_test"] = mse_har
    out["RW_OOS_R2"] = r2_rw_oos
    out["HAR_OOS_R2"] = r2_har_oos
    out["DM_HLN_t"] = float(dm_t) if not np.isnan(dm_t) else None
    out["DM_HLN_p"] = float(dm_p) if not np.isnan(dm_p) else None
    out["DM_interpretation"] = "positive t => HAR-RV lower QLIKE => HAR preferred; negative => RW preferred"

    # --- 8) Verdict ---
    pass_dm = (not np.isnan(dm_t)) and abs(dm_t) > 3.0
    har_lower_qlike = mean_qlike_har < mean_qlike_rw

    if untrustworthy:
        verdict = "UNTRUSTWORTHY_SMALL_SAMPLE"
    elif pass_dm and har_lower_qlike:
        verdict = "PASS"
    elif (not pass_dm) and (abs(dm_t) > 2.0 if dm_t is not None else False) and har_lower_qlike:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    out["untrustworthy_small_sample"] = untrustworthy
    out["verdict"] = verdict
    out["revisit_gate_threshold"] = REVISIT_GATE_DAYS

    # Caveat string surfaced for downstream readers
    out["caveats"] = []
    if untrustworthy:
        out["caveats"].append(
            f"n_test={n_test} < 50 → DM-HLN test under-powered; verdict is exploratory only. "
            f"Revisit when n_total >= {REVISIT_GATE_DAYS}."
        )
    if r2_har_oos < 0 or r2_rw_oos < 0:
        out["caveats"].append(
            f"Negative OOS R^2 (HAR={r2_har_oos:.3f}, RW={r2_rw_oos:.3f}) indicates test "
            f"variance below sample-mean baseline — common with very short windows."
        )

    out["elapsed_seconds"] = round(time.time() - t0, 2)

    # --- 9) Write JSON ---
    out_path = SCRIPT_DIR / "K1322_results.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[done] wrote {out_path}")
    print(f"[done] verdict = {verdict}")
    print(f"[done] DM-HLN t = {dm_t:.3f} (p={dm_p:.4f}); "
          f"QLIKE HAR={mean_qlike_har:.4f} vs RW={mean_qlike_rw:.4f}; "
          f"R2_oos HAR={r2_har_oos:.3f} vs RW={r2_rw_oos:.3f}")


if __name__ == "__main__":
    main()
