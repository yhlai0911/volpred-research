"""K1437: USD/TWD vs TWII Volatility Spillover (VAR + DCC-GARCH).

Hypothesis: USD/TWD large moves transmit to TWII volatility (export-driven
economy). Asymmetric: TWD appreciation shock > depreciation shock for TWII.

Methodology:
1. Sample: 2012-01-01 to 2026-03-30 (matched to USDTWD snapshot end)
2. Daily log-returns from close prices
3. Volatility proxy: log(r^2 + eps) (Patton-robust under log link)
4. Lookahead guard: explicit .shift(1) on all RHS regressors
5. VAR(p) by BIC on log-RV proxies (max_lag=5)
6. Granger causality both directions (TWD-vol -> TWII-vol and reverse)
7. DCC-GARCH on standardized returns (asymmetric univariate GJR-GARCH,
   then DCC(1,1) on standardized residuals); 100 multistart for DCC params
8. Asymmetry test: split TWD return into appreciation (r<0) vs depreciation
   (r>0) parts and run augmented VAR

Author: K1437 worktree agent (2026-06-09)
Seed: 42
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from arch import arch_model
from scipy import optimize
from scipy.stats import chi2, jarque_bera
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller, grangercausalitytests

SEED = 42
EXP_DIR = Path(__file__).resolve().parent
FIG_DIR = EXP_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True, parents=True)

# ----------------------------------------------------------------------
# Data loading (use pinned snapshots — no live network)
# ----------------------------------------------------------------------
USDTWD_PATH = Path("paper/taiwan-vt/data/_usdtwd_snapshot.csv")
TWII_PATH = Path(
    "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
)


def _clean_usdtwd(twd: pd.DataFrame, threshold: float = 0.04) -> tuple[pd.DataFrame, list[dict]]:
    """Detect & drop obvious bad ticks in USDTWD (yfinance historic-import errors).

    Real USDTWD daily log-returns rarely exceed |3%|. Any single-day |log-return|
    above `threshold` (default 4%) on this currency pair is treated as a bad
    tick (likely missing leading digit; we saw 2011-10-25=1.80 and
    2014-12-31=3.67 in the pinned snapshot — both clearly corrupted from
    ~31.5). We drop such rows.

    Returns cleaned twd DataFrame + list of dropped rows for audit trail.
    """
    log_ret = np.log(twd["twd"]).diff()
    BAD_THRESHOLD = threshold
    bad_mask = log_ret.abs() > BAD_THRESHOLD
    dropped = []
    if bad_mask.any():
        bad_rows = twd[bad_mask].copy()
        for ts, row in bad_rows.iterrows():
            dropped.append({
                "date": str(ts.date()),
                "twd_close": float(row["twd"]),
                "log_return_vs_prev": float(log_ret.loc[ts]),
            })
        twd = twd[~bad_mask].copy()
    return twd, dropped


def load_data(bad_tick_threshold: float = 0.04) -> tuple[pd.DataFrame, dict]:
    """Load TWD and TWII close prices, align to TWII trading calendar.

    Returns (df, metadata). Calendar policy: TWII trading days are the panel
    (Taiwan stock market is the spillover target); USDTWD is forward-aligned
    by taking the most recent available USDTWD close at-or-before each TWII
    trading day. This preserves all TWII observations and avoids losing
    information on US/Taiwan holiday asymmetries (which a strict-intersection
    dropna would discard — see Codex review CONCERN #8 on 2026-06-09).
    """
    twd = pd.read_csv(USDTWD_PATH, comment="#", parse_dates=["date"])
    twd = twd.rename(columns={"usdtwd_close": "twd"})
    twd = twd.drop_duplicates(subset="date", keep="last").set_index("date").sort_index()
    twd, bad_ticks = _clean_usdtwd(twd, threshold=bad_tick_threshold)

    twii = pd.read_csv(TWII_PATH, parse_dates=["date"])[["date", "twii_close"]]
    twii = twii.rename(columns={"twii_close": "twii"})
    twii = twii.drop_duplicates(subset="date", keep="last").set_index("date").sort_index()

    # Restrict each series to study window FIRST, then align to TWII calendar
    twd = twd.loc["2012-01-01":"2026-03-30"]
    twii = twii.loc["2012-01-01":"2026-03-30"]

    # Forward-align USDTWD to TWII trading days (last available close)
    twd_aligned = twd.reindex(twii.index, method="ffill")

    df = pd.concat([twd_aligned, twii], axis=1).dropna()

    meta = {
        "calendar": "TWII trading days; USDTWD forward-aligned (last close at-or-before each TWII day)",
        "bad_tick_threshold_log_return": bad_tick_threshold,
        "n_twii_days": int(len(twii)),
        "n_twd_days_in_window": int(len(twd)),
        "n_joined": int(len(df)),
        "usdtwd_bad_ticks_dropped": bad_ticks,
    }
    return df, meta


# ----------------------------------------------------------------------
# Feature engineering: returns + log-RV proxy
# ----------------------------------------------------------------------
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute daily log-returns (in %) and log(r^2) volatility proxy."""
    feat = pd.DataFrame(index=df.index)
    feat["twd_ret"] = 100.0 * np.log(df["twd"]).diff()
    feat["twii_ret"] = 100.0 * np.log(df["twii"]).diff()
    # Squared returns as RV proxy (close-to-close r^2 follows Patton 2011
    # QLIKE-consistent proxy class)
    feat["twd_rv"] = feat["twd_ret"] ** 2
    feat["twii_rv"] = feat["twii_ret"] ** 2
    # Log-RV (eps to avoid log(0) for stale/holiday days)
    eps = 1e-8
    feat["twd_logrv"] = np.log(feat["twd_rv"] + eps)
    feat["twii_logrv"] = np.log(feat["twii_rv"] + eps)
    feat = feat.dropna()
    # Drop extreme zero-rv outliers from holiday alignment (Pacific holidays)
    feat = feat[(feat["twd_rv"] > 1e-6) & (feat["twii_rv"] > 1e-6)]
    return feat


# ----------------------------------------------------------------------
# Diagnostics
# ----------------------------------------------------------------------
def descriptive_stats(feat: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for col in ("twd_ret", "twii_ret", "twd_logrv", "twii_logrv"):
        s = feat[col]
        jb_stat, jb_p = jarque_bera(s)
        adf_stat, adf_p, *_ = adfuller(s, autolag="AIC")
        out[col] = {
            "mean": float(s.mean()),
            "std": float(s.std()),
            "skew": float(s.skew()),
            "kurt": float(s.kurt()),
            "jarque_bera_stat": float(jb_stat),
            "jarque_bera_p": float(jb_p),
            "adf_stat": float(adf_stat),
            "adf_p": float(adf_p),
            "n": int(s.shape[0]),
        }
    return out


# ----------------------------------------------------------------------
# VAR(p) by BIC on log-RV; Granger both directions
# ----------------------------------------------------------------------
def fit_var_and_granger(feat: pd.DataFrame, max_lag: int = 5) -> dict[str, Any]:
    """Fit VAR(p) on (twd_logrv, twii_logrv); choose p by BIC; Granger tests."""
    Y = feat[["twd_logrv", "twii_logrv"]].copy()
    var_model = VAR(Y)
    selection = var_model.select_order(maxlags=max_lag)
    # Use BIC ("bic" key in selected_orders dict)
    p_bic = int(selection.bic)
    if p_bic < 1:
        p_bic = 1
    res = var_model.fit(p_bic)

    # Granger: TWD-vol -> TWII-vol  (does past twd_logrv help predict twii_logrv?)
    # statsmodels grangercausalitytests expects [y, x] where x -> y is tested
    granger_twd_to_twii = grangercausalitytests(
        Y[["twii_logrv", "twd_logrv"]], maxlag=p_bic, verbose=False
    )
    granger_twii_to_twd = grangercausalitytests(
        Y[["twd_logrv", "twii_logrv"]], maxlag=p_bic, verbose=False
    )

    def _pick_ssr_f(g: dict[int, tuple], lag: int) -> tuple[float, float]:
        f_stat, p_value, df1, df2 = g[lag][0]["ssr_ftest"]
        return float(f_stat), float(p_value)

    f_twd, p_twd = _pick_ssr_f(granger_twd_to_twii, p_bic)
    f_twii, p_twii = _pick_ssr_f(granger_twii_to_twd, p_bic)

    # Extract pretty coef summary
    coefs = {}
    for eq in ("twd_logrv", "twii_logrv"):
        params = res.params[eq]
        coefs[eq] = {k: float(v) for k, v in params.items()}

    return {
        "p_bic": p_bic,
        "selection_orders": {
            "aic": int(selection.aic),
            "bic": int(selection.bic),
            "hqic": int(selection.hqic),
            "fpe": int(selection.fpe),
        },
        "n_obs": int(res.nobs),
        "loglik": float(res.llf),
        "bic": float(res.bic),
        "aic": float(res.aic),
        "coefs": coefs,
        "granger_twd_vol_to_twii_vol": {"F": f_twd, "p_value": p_twd, "lag": p_bic},
        "granger_twii_vol_to_twd_vol": {"F": f_twii, "p_value": p_twii, "lag": p_bic},
    }, res


# ----------------------------------------------------------------------
# Univariate GJR-GARCH for each series (asymmetric GARCH per K1213 lesson)
# ----------------------------------------------------------------------
def fit_gjr_garch(returns: pd.Series, label: str) -> dict[str, Any]:
    """Fit GJR-GARCH(1,1) with Student-t innovations. Returns std resid + h_t."""
    am = arch_model(
        returns, mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="t",
        rescale=False,
    )
    res = am.fit(disp="off", show_warning=False)
    sigma2 = res.conditional_volatility ** 2
    std_resid = (returns - res.params["mu"]) / res.conditional_volatility
    return {
        "label": label,
        "params": {k: float(v) for k, v in res.params.items()},
        "loglik": float(res.loglikelihood),
        "aic": float(res.aic),
        "bic": float(res.bic),
        "sigma2": sigma2,
        "std_resid": std_resid,
        "converged": bool(res.convergence_flag == 0),
    }


# ----------------------------------------------------------------------
# DCC(1,1) with 100 multistart (Engle 2002 — asymptotic equivalent to BEKK
# for variance spillover but numerically far more tractable)
# ----------------------------------------------------------------------
def _dcc_nll(params: np.ndarray, eps: np.ndarray) -> float:
    """Negative log-likelihood of DCC(1,1).

    eps: (T, 2) standardized residuals from univariate GARCH.
    Q_t = (1-a-b)*Qbar + a*eps_{t-1}eps_{t-1}' + b*Q_{t-1}
    R_t = diag(Q_t)^{-1/2} Q_t diag(Q_t)^{-1/2}
    """
    a, b = params
    if a < 0 or b < 0 or a + b >= 0.9999:
        return 1e10
    T = eps.shape[0]
    Qbar = np.cov(eps.T, ddof=0)
    Q = Qbar.copy()
    nll = 0.0
    for t in range(1, T):
        e_prev = eps[t - 1].reshape(2, 1)
        Q = (1.0 - a - b) * Qbar + a * (e_prev @ e_prev.T) + b * Q
        d = np.sqrt(np.diag(Q))
        # Guard tiny d
        if np.any(d <= 1e-12):
            return 1e10
        R = Q / np.outer(d, d)
        # 2x2 closed form: |R| = 1 - r12^2; R^-1 = [[1,-r],[-r,1]]/(1-r^2)
        r = R[0, 1]
        det = 1.0 - r * r
        if det <= 1e-12:
            return 1e10
        e = eps[t]
        quad = (e[0] ** 2 - 2 * r * e[0] * e[1] + e[1] ** 2) / det
        # DCC contribution (omit constant + univariate part)
        nll += 0.5 * (math.log(det) + quad - (e[0] ** 2 + e[1] ** 2))
    return float(nll)


def fit_dcc(eps: np.ndarray, n_starts: int = 100, seed: int = SEED) -> dict[str, Any]:
    """Fit DCC(1,1) with multistart. eps shape: (T, 2)."""
    rng = np.random.default_rng(seed)
    bounds = [(1e-4, 0.3), (0.6, 0.999)]
    best = None
    nlls = []
    for i in range(n_starts):
        a0 = rng.uniform(0.005, 0.15)
        b0 = rng.uniform(0.7, 0.97)
        if a0 + b0 >= 0.999:
            b0 = 0.99 - a0
        try:
            r = optimize.minimize(
                _dcc_nll, x0=[a0, b0], args=(eps,),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 200, "ftol": 1e-8},
            )
            if r.success and r.fun < 1e9:
                nlls.append(float(r.fun))
                if best is None or r.fun < best.fun:
                    best = r
        except Exception:
            continue
    if best is None:
        return {"converged": False, "n_starts": n_starts}
    a_hat, b_hat = float(best.x[0]), float(best.x[1])
    # Compute fitted R_t time series
    Qbar = np.cov(eps.T, ddof=0)
    Q = Qbar.copy()
    T = eps.shape[0]
    rho = np.empty(T)
    rho[0] = Qbar[0, 1] / math.sqrt(Qbar[0, 0] * Qbar[1, 1])
    for t in range(1, T):
        e_prev = eps[t - 1].reshape(2, 1)
        Q = (1.0 - a_hat - b_hat) * Qbar + a_hat * (e_prev @ e_prev.T) + b_hat * Q
        d = np.sqrt(np.diag(Q))
        rho[t] = Q[0, 1] / (d[0] * d[1])
    # Multistart-quality stat: "within tolerance of best" — using absolute
    # tolerance on NLL (avoid the sign bug where best.fun * 1.01 is STRICTER
    # for negative NLL; see Codex review CONCERN #4 on 2026-06-09).
    nll_arr = np.array(nlls)
    TOL_ABS = 1.0  # within 1 NLL unit of best (~ 1 log-likelihood point)
    n_close = int(np.sum(nll_arr <= best.fun + TOL_ABS))
    return {
        "converged": True,
        "n_starts": int(n_starts),
        "n_success": int(len(nlls)),
        "alpha": a_hat,
        "beta": b_hat,
        "persistence": a_hat + b_hat,
        "nll_best": float(best.fun),
        "nll_distribution": {
            "min": float(np.min(nlls)),
            "median": float(np.median(nlls)),
            "max": float(np.max(nlls)),
            "n_within_1_nll_unit_of_best": n_close,
            "tolerance_used": "absolute_1.0_NLL_units",
        },
        "Qbar": Qbar.tolist(),
        "rho_series": rho,  # ndarray for plotting; popped before JSON dump
    }


# ----------------------------------------------------------------------
# Asymmetry test: split TWD return into appreciation (r<0) and depreciation (r>0)
# Add lagged abs(twd_ret_neg) and abs(twd_ret_pos) as exogenous in twii_logrv eq.
# Test joint significance + Wald for asymmetry (H0: coef_neg == coef_pos).
# ----------------------------------------------------------------------
def asymmetry_test(feat: pd.DataFrame, lag: int = 1) -> dict[str, Any]:
    """OLS: twii_logrv_t = const + sum_{k=1..lag} [a_k * |twd_neg|_{t-k} +
                                                   b_k * |twd_pos|_{t-k}]
                                                + c_k * twii_logrv_{t-k}
       Test:
         H0 (no spillover): a_k = b_k = 0 for all k  (F-test)
         H0 (symmetric):    a_k = b_k for all k       (F-test)
    """
    df = feat.copy()
    # USDTWD up = TWD weaker (depreciation). TWD APPRECIATION = USDTWD return < 0.
    twd_neg = (-df["twd_ret"]).clip(lower=0.0)   # |r| when r<0 (TWD APPRECIATION)
    twd_pos = df["twd_ret"].clip(lower=0.0)      # |r| when r>0 (TWD DEPRECIATION)
    cols = ["const"]
    for k in range(1, lag + 1):
        df[f"twd_neg_l{k}"] = twd_neg.shift(k)  # LOOKAHEAD GUARD: shift(k) — lag k
        df[f"twd_pos_l{k}"] = twd_pos.shift(k)
        df[f"twii_logrv_l{k}"] = df["twii_logrv"].shift(k)
        # Control for TWD's own past vol state (Codex CONCERN #7, 2026-06-09)
        df[f"twd_logrv_l{k}"] = df["twd_logrv"].shift(k)
        cols.extend([
            f"twd_neg_l{k}", f"twd_pos_l{k}",
            f"twii_logrv_l{k}", f"twd_logrv_l{k}",
        ])
    df = df.dropna(subset=cols[1:] + ["twii_logrv"])
    X = pd.concat([pd.Series(1.0, index=df.index, name="const"), df[cols[1:]]], axis=1)
    y = df["twii_logrv"]
    # OLS solution
    XtX = X.values.T @ X.values
    XtX_inv = np.linalg.inv(XtX)
    beta = XtX_inv @ X.values.T @ y.values
    yhat = X.values @ beta
    resid = y.values - yhat
    n = len(y)
    k_full = X.shape[1]
    rss_full = float(resid @ resid)
    sigma2 = rss_full / (n - k_full)
    cov_beta = sigma2 * XtX_inv

    # Joint test 1: a_k = b_k = 0 (drop twd_neg/pos cols)
    keep_idx = [i for i, c in enumerate(X.columns)
                if not (c.startswith("twd_neg") or c.startswith("twd_pos"))]
    X_r1 = X.iloc[:, keep_idx]
    beta_r1 = np.linalg.solve(X_r1.values.T @ X_r1.values, X_r1.values.T @ y.values)
    resid_r1 = y.values - X_r1.values @ beta_r1
    rss_r1 = float(resid_r1 @ resid_r1)
    q1 = X.shape[1] - X_r1.shape[1]
    F_no_spill = ((rss_r1 - rss_full) / q1) / (rss_full / (n - k_full))
    p_no_spill = 1.0 - chi2.cdf(q1 * F_no_spill, df=q1)  # approx; use F dist below
    from scipy.stats import f as f_dist
    p_no_spill = float(1.0 - f_dist.cdf(F_no_spill, q1, n - k_full))

    # Joint test 2: a_k == b_k (symmetric)  — restriction R*beta = 0
    R_rows = []
    col_idx = {c: i for i, c in enumerate(X.columns)}
    for k in range(1, lag + 1):
        row = np.zeros(k_full)
        row[col_idx[f"twd_neg_l{k}"]] = 1.0
        row[col_idx[f"twd_pos_l{k}"]] = -1.0
        R_rows.append(row)
    R = np.array(R_rows)
    Rbeta = R @ beta
    middle = R @ cov_beta @ R.T
    wald = float(Rbeta @ np.linalg.solve(middle, Rbeta))
    p_sym = float(1.0 - chi2.cdf(wald, df=R.shape[0]))

    # Per-lag coefficient table
    se = np.sqrt(np.diag(cov_beta))
    tstat = beta / se
    from scipy.stats import t as t_dist
    pvals = 2.0 * (1.0 - t_dist.cdf(np.abs(tstat), df=n - k_full))
    coef_table = {
        col: {"coef": float(beta[i]), "se": float(se[i]),
              "t": float(tstat[i]), "p": float(pvals[i])}
        for i, col in enumerate(X.columns)
    }

    return {
        "lag": lag,
        "n_obs": n,
        "k_full": k_full,
        "rss_full": rss_full,
        "rss_no_spill": rss_r1,
        "F_no_spillover": float(F_no_spill),
        "p_no_spillover": p_no_spill,
        "wald_symmetric": wald,
        "p_symmetric": p_sym,
        "coef_table": coef_table,
        "note": "twd_neg = (-twd_ret).clip(0,inf) measures TWD APPRECIATION (USDTWD return < 0); twd_pos = twd_ret.clip(0,inf) measures TWD DEPRECIATION (USDTWD return > 0).",
    }


# ----------------------------------------------------------------------
# Bad-tick threshold sensitivity sweep (Codex 2026-06-09 residual #2)
# ----------------------------------------------------------------------
def threshold_sensitivity(thresholds=(0.03, 0.04, 0.05)) -> dict[str, Any]:
    """Run only the Granger + asymmetry pieces at multiple bad-tick thresholds.

    Skips DCC (heavy) for speed; the relevant sensitivity question is whether
    spillover conclusions flip across reasonable thresholds.
    """
    out = {}
    for thr in thresholds:
        df_t, meta_t = load_data(bad_tick_threshold=thr)
        feat_t = build_features(df_t)
        var_t, _ = fit_var_and_granger(feat_t, max_lag=5)
        asym_t = asymmetry_test(feat_t, lag=var_t["p_bic"])
        out[f"threshold_{thr:.2f}"] = {
            "n_dropped": len(meta_t["usdtwd_bad_ticks_dropped"]),
            "n_obs": int(len(feat_t)),
            "p_bic": var_t["p_bic"],
            "granger_twd_to_twii_p": var_t["granger_twd_vol_to_twii_vol"]["p_value"],
            "granger_twii_to_twd_p": var_t["granger_twii_vol_to_twd_vol"]["p_value"],
            "asym_no_spillover_p": asym_t["p_no_spillover"],
            "asym_symmetry_p": asym_t["p_symmetric"],
        }
    return out


# ----------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------
def plot_dual_vol(feat: pd.DataFrame) -> Path:
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax2 = ax1.twinx()
    # 21-day rolling sqrt(RV) annualized
    twd_vol = np.sqrt(feat["twd_rv"].rolling(21).mean() * 252)
    twii_vol = np.sqrt(feat["twii_rv"].rolling(21).mean() * 252)
    ax1.plot(feat.index, twd_vol, color="C0", lw=1.0, label="USD/TWD vol (21d, ann.)")
    ax2.plot(feat.index, twii_vol, color="C3", lw=1.0, label="TWII vol (21d, ann.)")
    ax1.set_ylabel("USD/TWD annualized vol (%)", color="C0")
    ax2.set_ylabel("TWII annualized vol (%)", color="C3")
    ax1.set_title("USD/TWD vs TWII rolling 21-day annualized volatility (2012-2026)")
    ax1.grid(alpha=0.3)
    fig.tight_layout()
    p = FIG_DIR / "k1437_dual_vol.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return p


def plot_dcc_rho(dates: pd.DatetimeIndex, rho: np.ndarray) -> Path:
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(dates, rho, color="C2", lw=0.8)
    ax.axhline(0, color="k", lw=0.5, ls="--")
    ax.axhline(float(np.mean(rho)), color="C1", lw=0.8,
               label=f"mean = {np.mean(rho):.3f}")
    ax.set_title("DCC(1,1) time-varying correlation USD/TWD vs TWII (standardized GJR-residuals)")
    ax.set_ylabel("rho_t")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = FIG_DIR / "k1437_dcc_rho.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return p


# ----------------------------------------------------------------------
# Main pipeline
# ----------------------------------------------------------------------
def main() -> None:
    np.random.seed(SEED)
    print("[K1437] Loading data...")
    df, load_meta = load_data()
    print(f"  Joined sample: {df.index.min().date()} -> {df.index.max().date()} N={len(df)}")
    print(f"  USDTWD bad ticks dropped: {len(load_meta['usdtwd_bad_ticks_dropped'])}")
    for bt in load_meta["usdtwd_bad_ticks_dropped"]:
        print(f"    - {bt['date']}: close={bt['twd_close']}, logret={bt['log_return_vs_prev']:.3f}")
    feat = build_features(df)
    print(f"  After feature build & RV filter: N={len(feat)}")

    desc = descriptive_stats(feat)

    print("[K1437] VAR(p) selection by BIC + Granger (both directions)...")
    var_result, _ = fit_var_and_granger(feat, max_lag=5)
    print(f"  p_BIC = {var_result['p_bic']}")
    print(f"  TWD-vol -> TWII-vol Granger F={var_result['granger_twd_vol_to_twii_vol']['F']:.3f}, p={var_result['granger_twd_vol_to_twii_vol']['p_value']:.4f}")
    print(f"  TWII-vol -> TWD-vol Granger F={var_result['granger_twii_vol_to_twd_vol']['F']:.3f}, p={var_result['granger_twii_vol_to_twd_vol']['p_value']:.4f}")

    print("[K1437] Univariate GJR-GARCH(1,1)-t for each series...")
    gjr_twd = fit_gjr_garch(feat["twd_ret"], "USDTWD")
    gjr_twii = fit_gjr_garch(feat["twii_ret"], "TWII")
    print(f"  USDTWD converged={gjr_twd['converged']}; params={gjr_twd['params']}")
    print(f"  TWII   converged={gjr_twii['converged']}; params={gjr_twii['params']}")

    # Align standardized residuals
    std_resid = pd.DataFrame({
        "twd": gjr_twd["std_resid"],
        "twii": gjr_twii["std_resid"],
    }).dropna()
    eps = std_resid.values

    print(f"[K1437] DCC(1,1) with 100 multistart on standardized residuals (T={len(eps)})...")
    dcc = fit_dcc(eps, n_starts=100, seed=SEED)
    if dcc["converged"]:
        print(f"  alpha={dcc['alpha']:.4f}  beta={dcc['beta']:.4f}  alpha+beta={dcc['persistence']:.4f}")
        print(f"  NLL best={dcc['nll_best']:.2f}; n_within_1_NLL={dcc['nll_distribution']['n_within_1_nll_unit_of_best']}/{dcc['n_success']}")
    else:
        print(f"  DCC failed to converge")

    print("[K1437] Asymmetry test (TWD appreciation vs depreciation shocks on TWII vol)...")
    asym = asymmetry_test(feat, lag=var_result["p_bic"])
    print(f"  No-spillover F={asym['F_no_spillover']:.3f}, p={asym['p_no_spillover']:.4f}")
    print(f"  Symmetry Wald={asym['wald_symmetric']:.3f}, p={asym['p_symmetric']:.4f}")

    print("[K1437] Threshold sensitivity sweep (3%/4%/5%)...")
    sens = threshold_sensitivity(thresholds=(0.03, 0.04, 0.05))
    for thr_key, vals in sens.items():
        print(f"  {thr_key}: n_drop={vals['n_dropped']} p_bic={vals['p_bic']} "
              f"twd->twii p={vals['granger_twd_to_twii_p']:.3f} "
              f"sym p={vals['asym_symmetry_p']:.3f}")

    print("[K1437] Figures...")
    fig1 = plot_dual_vol(feat)
    fig2 = (
        plot_dcc_rho(std_resid.index, dcc["rho_series"])
        if dcc.get("converged", False) else None
    )
    print(f"  saved {fig1}")
    if fig2:
        print(f"  saved {fig2}")

    # Verdict logic
    p_twd_to_twii = var_result["granger_twd_vol_to_twii_vol"]["p_value"]
    p_twii_to_twd = var_result["granger_twii_vol_to_twd_vol"]["p_value"]
    p_no_spill = asym["p_no_spillover"]
    p_sym = asym["p_symmetric"]

    spill_real_direction = []
    if p_twd_to_twii < 0.05:
        spill_real_direction.append("TWD_vol -> TWII_vol")
    if p_twii_to_twd < 0.05:
        spill_real_direction.append("TWII_vol -> TWD_vol")

    if len(spill_real_direction) == 0:
        verdict_spill = "NULL — no Granger causal vol spillover in either direction"
    elif len(spill_real_direction) == 2:
        verdict_spill = "BIDIRECTIONAL — both directions Granger significant"
    else:
        verdict_spill = f"UNIDIRECTIONAL — {spill_real_direction[0]} only"

    if p_sym < 0.05:
        verdict_asym = "ASYMMETRIC — TWD appreciation shocks differ from depreciation shocks (Wald rejects symmetry)"
    else:
        verdict_asym = "SYMMETRIC — null cannot reject equal effect of appreciation vs depreciation"

    summary = {
        "experiment_id": "K1437",
        "title": "USD/TWD vs TWII volatility spillover (VAR + DCC-GARCH + asymmetry)",
        "seed": SEED,
        "sample_period": {
            "start": str(feat.index.min().date()),
            "end": str(feat.index.max().date()),
            "n_obs": int(len(feat)),
            "years": float((feat.index.max() - feat.index.min()).days / 365.25),
        },
        "data_sources": {
            "usdtwd": str(USDTWD_PATH),
            "twii": str(TWII_PATH),
        },
        "data_quality": load_meta,
        "descriptive_stats": desc,
        "var": var_result,
        "univariate_gjr_garch": {
            "twd": {k: v for k, v in gjr_twd.items() if k not in ("sigma2", "std_resid")},
            "twii": {k: v for k, v in gjr_twii.items() if k not in ("sigma2", "std_resid")},
        },
        "dcc": {k: v for k, v in dcc.items() if k != "rho_series"},
        "dcc_rho_summary": (
            {
                "mean": float(np.mean(dcc["rho_series"])) if dcc.get("converged") else None,
                "median": float(np.median(dcc["rho_series"])) if dcc.get("converged") else None,
                "min": float(np.min(dcc["rho_series"])) if dcc.get("converged") else None,
                "max": float(np.max(dcc["rho_series"])) if dcc.get("converged") else None,
                "std": float(np.std(dcc["rho_series"])) if dcc.get("converged") else None,
            }
        ),
        "asymmetry": asym,
        "bad_tick_sensitivity": sens,
        "verdict": {
            "spillover": verdict_spill,
            "asymmetry": verdict_asym,
            "decision": (
                "SPILLOVER_PRESENT" if p_twd_to_twii < 0.05 or p_twii_to_twd < 0.05
                else "NULL_RESULT"
            ),
        },
        "figures": [
            str(fig1.relative_to(EXP_DIR.parent.parent)),
            str(fig2.relative_to(EXP_DIR.parent.parent)) if fig2 else None,
        ],
        "diff_vs_prior": {
            "T5b_2015_2024": "T5b tested TWD RETURN -> TWII vol with p=0.08 (NS). K1437 tests vol -> vol (log-RV) bidirectional + DCC time-varying correlation + asymmetric appreciation/depreciation decomposition over the longer 2012-2026 window (14yr). Methodologically distinct: T5b used return->vol granger F; K1437 uses log-RV VAR + multistart DCC.",
            "paper2_sec3_twd_usd_test": "That test was nested OLS F-test of TWD return adding power to VIX-controlled regression of r^2. K1437 drops VIX and tests pure pairwise vol-vol bidirectional spillover + structural asymmetry.",
        },
    }

    with open(EXP_DIR / "k1437_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"[K1437] Wrote {EXP_DIR / 'k1437_results.json'}")
    print(f"[K1437] Verdict: {summary['verdict']['decision']}")
    print(f"  Spillover: {summary['verdict']['spillover']}")
    print(f"  Asymmetry: {summary['verdict']['asymmetry']}")


if __name__ == "__main__":
    main()
