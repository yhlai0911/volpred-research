"""
K1115 — SPY VaR Breach Clustering with Conditional Framework

Motivation (E055 condition b):
Copula真正適合 3 個必要條件之一：**單一資產的 path-dependent 應用**。
K1100/K1100b/K1100f 全 null 因為 portfolio-level aggregation 把 tail dependence
平均化。K1115 跳出 portfolio 框架，測試 single-asset SPY VaR breach 的 clustering
結構，並評估 breach-history-conditional 模型是否改善 tail risk forecasting。

Design:
- 5 VaR models at both alpha=1% and alpha=5%:
  M1: Empirical rolling 252d quantile
  M2: GARCH(1,1) Normal
  M3: GJR-GARCH Student-t (baseline best univariate)
  M4: GJR-t * (1 + delta_4 * breach_count_lag/5)   <-- path-dependent
  M5: GJR-t * (1 + delta_5 * hawkes_intensity_lag)  <-- self-excitation

- Data: SPY 2010-01-01 to 2026-04-13 (yfinance)
- Train (IS): 2010-2017 (~8 years, ~2015 days)
- Test (OOS): 2018-01 to 2026-04 (~6+ years, ~2080 days)

- Tests:
  Clustering:  Christoffersen (1998) independence, Ljung-Box on breaches
  Trinity:     Kupiec (1995), Christoffersen CC, Acerbi-Szekely (2014) Z2 ES
  Forecast:    DM-HLN on quantile loss (Koenker-Bassett check function)

- H2 PASS criteria (must satisfy ALL three):
  1. OOS Kupiec p > 0.10
  2. OOS Christoffersen CC p > 0.10
  3. OOS |DM-HLN t| > 2 vs M3 baseline

Important: All breach-based features use ONLY lagged breaches (shift(1))
to avoid lookahead. Delta parameters estimated on IS only, applied to OOS.

Author: VolPred Research System (Claude worktree agent K1115)
Date: 2026-04-13
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")
np.random.seed(42)

OUT_DIR = Path(__file__).parent
ALPHAS = [0.01, 0.05]
ROLLING_WINDOW = 252
HAWKES_DECAY = 0.3
BREACH_LOOKBACK = 5

IS_START = pd.Timestamp("2010-01-01")
IS_END = pd.Timestamp("2017-12-31")
OOS_START = pd.Timestamp("2018-01-01")
OOS_END = pd.Timestamp("2026-04-13")


# ---------------------------------------------------------------------------
# 1) Data
# ---------------------------------------------------------------------------
def load_spy_returns() -> pd.Series:
    """Download SPY daily close-to-close returns (2010-01-01 ~ 2026-04-14)."""
    spy = yf.download(
        "SPY",
        start="2010-01-01",
        end="2026-04-14",
        auto_adjust=True,
        progress=False,
    )
    if isinstance(spy.columns, pd.MultiIndex):
        close = spy["Close"].iloc[:, 0]
    else:
        close = spy["Close"]
    ret = np.log(close).diff().dropna() * 100.0
    ret.name = "ret"
    return ret


# ---------------------------------------------------------------------------
# 2) Rolling sigma/dof from GARCH models (one-step-ahead, no lookahead)
# ---------------------------------------------------------------------------
def rolling_garch_forecast(
    ret: pd.Series, vol: str, dist: str, p: int, o: int, q: int, refit_freq: int = 250,
) -> pd.DataFrame:
    """Produce one-step-ahead conditional sigma (and dof if Student-t) for each
    date t, using information only up to t-1. Refit every `refit_freq` days.

    Between refits, update conditional variance recursively using the frozen
    parameters and new observations (standard rolling forecast without lookahead).
    """
    n = len(ret)
    sigma_out = np.full(n, np.nan)
    dof_out = np.full(n, np.nan)

    start_idx = ROLLING_WINDOW  # need at least 252 days of history
    # Initial fit
    res = arch_model(ret.iloc[:start_idx], mean="Zero", vol=vol, p=p, o=o, q=q, dist=dist, rescale=False)
    fit = res.fit(disp="off", show_warning=False)

    def extract_params(fit):
        omega = float(fit.params.get("omega", 0.0))
        alpha = float(fit.params.get("alpha[1]", 0.0))
        gamma = float(fit.params.get("gamma[1]", 0.0)) if o > 0 else 0.0
        beta = float(fit.params.get("beta[1]", 0.0))
        nu = float(fit.params.get("nu", 10.0)) if dist == "t" else np.nan
        return omega, alpha, gamma, beta, nu

    omega, alpha_p, gamma_p, beta_p, nu = extract_params(fit)
    # Initial conditional variance series (in-sample)
    cv = fit.conditional_volatility.values ** 2
    # Current recursive state: h_t (most recent conditional variance) and r_{t-1}
    # After fit we have cv[0..start_idx-1]; forecast h_start_idx using params + r_{start_idx-1}
    h_prev = float(cv[-1])
    r_prev = float(ret.iloc[start_idx - 1])

    last_refit = start_idx
    for t in range(start_idx, n):
        # Refit periodically with all data up to t-1
        if (t - last_refit) >= refit_freq:
            try:
                res = arch_model(ret.iloc[:t], mean="Zero", vol=vol, p=p, o=o, q=q, dist=dist, rescale=False)
                fit = res.fit(disp="off", show_warning=False)
                omega, alpha_p, gamma_p, beta_p, nu = extract_params(fit)
                cv = fit.conditional_volatility.values ** 2
                h_prev = float(cv[-1])
                r_prev = float(ret.iloc[t - 1])
                last_refit = t
            except Exception:
                pass
        # One-step-ahead conditional variance
        # For GJR: h_t = omega + alpha*r_{t-1}^2 + gamma*r_{t-1}^2*I{r_{t-1}<0} + beta*h_{t-1}
        ind_neg = 1.0 if r_prev < 0 else 0.0
        h_t = omega + alpha_p * r_prev ** 2 + gamma_p * r_prev ** 2 * ind_neg + beta_p * h_prev
        if h_t <= 0 or np.isnan(h_t):
            h_t = h_prev
        sigma_out[t] = np.sqrt(h_t)
        dof_out[t] = nu
        # Update state for next iteration
        h_prev = h_t
        r_prev = float(ret.iloc[t])

    return pd.DataFrame({"sigma": sigma_out, "dof": dof_out}, index=ret.index)


# ---------------------------------------------------------------------------
# 3) VaR/ES from sigma (parametric)
# ---------------------------------------------------------------------------
def var_es_normal(sigma: pd.Series, alpha: float) -> tuple[pd.Series, pd.Series]:
    z = stats.norm.ppf(alpha)
    var = sigma * z
    es = -sigma * stats.norm.pdf(z) / alpha  # negative
    return var, es


def var_es_student_t(sigma: pd.Series, dof: pd.Series, alpha: float) -> tuple[pd.Series, pd.Series]:
    """VaR/ES under standardized Student-t (unit variance, dof d).
    Using arch's standardized t => rescale by sqrt((d-2)/d)."""
    var = pd.Series(index=sigma.index, dtype=float)
    es = pd.Series(index=sigma.index, dtype=float)
    for i, (s, d) in enumerate(zip(sigma.values, dof.values)):
        if np.isnan(s) or np.isnan(d) or d <= 2:
            continue
        scale = np.sqrt((d - 2) / d)
        tau = stats.t.ppf(alpha, d)  # unscaled t quantile
        z = tau * scale  # standardized t quantile
        var.iloc[i] = z * s
        # ES under standardized t (Christoffersen 2003):
        # ES_std = -t.pdf(tau,d)/alpha * (d + tau^2)/(d-1)
        es_std = -stats.t.pdf(tau, d) / alpha * (d + tau ** 2) / (d - 1) * scale
        es.iloc[i] = es_std * s
    return var, es


def var_empirical(ret: pd.Series, alpha: float, window: int = ROLLING_WINDOW) -> tuple[pd.Series, pd.Series]:
    """Rolling empirical VaR and ES. Shift by 1 to ensure VaR_t uses info up to t-1."""
    var = ret.rolling(window).quantile(alpha)
    es = pd.Series(index=ret.index, dtype=float)
    # Rolling ES = mean of returns below rolling quantile
    vals = ret.values
    n = len(vals)
    for i in range(window, n):
        w = vals[i - window:i]
        q = np.quantile(w, alpha)
        tail = w[w < q]
        es.iloc[i] = tail.mean() if len(tail) > 0 else np.nan
    return var.shift(1), es.shift(1)


# ---------------------------------------------------------------------------
# 4) Breach-history features (no lookahead, lagged by 1)
# ---------------------------------------------------------------------------
def build_breach_features(ret: pd.Series, var_m3: pd.Series) -> pd.DataFrame:
    """Construct lagged breach-count and Hawkes-intensity features from M3 VaR.
    Both features use ONLY past breaches (shift(1) applied)."""
    breach_raw = (ret < var_m3).astype(float)
    breach_raw[var_m3.isna()] = np.nan
    # Shift by 1 so that breach_shifted at time t only contains breaches up to t-1
    breach_shifted = breach_raw.shift(1)
    # Past-5-day rolling count
    breach_count = breach_shifted.rolling(BREACH_LOOKBACK).sum()
    # Hawkes-like intensity: lambda_t = decay*lambda_{t-1} + breach_{t-1}
    bs_vals = breach_shifted.values
    intensity = np.full(len(bs_vals), np.nan)
    lam = 0.0
    ever_seen = False
    for i, b in enumerate(bs_vals):
        if not np.isnan(b):
            lam = lam * (1 - HAWKES_DECAY) + b
            ever_seen = True
        else:
            lam = lam * (1 - HAWKES_DECAY)
        intensity[i] = lam if ever_seen else np.nan
    return pd.DataFrame({
        "breach": breach_raw.values,  # contemporaneous breach (for plotting)
        "breach_count": breach_count.values,
        "hawkes_intensity": intensity,
    }, index=ret.index)


def fit_delta_is(ret_is: pd.Series, var_m3_is: pd.Series, feat_is: pd.Series, alpha: float) -> float:
    """Grid search delta to match IS breach rate to alpha.

    Objective: minimize |P(r < VaR_adj) - alpha| using IS only.
    """
    # Normalize feature by its in-sample std to make deltas comparable
    scale = feat_is.std() if feat_is.std() > 0 else 1.0
    best_delta = 0.0
    best_obj = np.inf
    valid = (~ret_is.isna()) & (~var_m3_is.isna()) & (~feat_is.isna())
    r = ret_is[valid].values
    v = var_m3_is[valid].values
    f = feat_is[valid].values / scale
    for delta in np.linspace(-0.5, 0.5, 51):
        v_adj = v * (1.0 + delta * f)
        rate = (r < v_adj).mean()
        obj = abs(rate - alpha)
        if obj < best_obj:
            best_obj = obj
            best_delta = delta
    return float(best_delta), float(scale)


# ---------------------------------------------------------------------------
# 5) Backtest statistics
# ---------------------------------------------------------------------------
def kupiec_pof_test(breaches: np.ndarray, alpha: float) -> tuple[float, float]:
    n = len(breaches)
    x = int(breaches.sum())
    if n == 0 or x == 0 or x == n:
        return np.nan, np.nan
    p_hat = x / n
    ll_null = x * np.log(alpha) + (n - x) * np.log(1 - alpha)
    ll_alt = x * np.log(p_hat) + (n - x) * np.log(1 - p_hat)
    lr = -2 * (ll_null - ll_alt)
    return float(lr), float(1 - stats.chi2.cdf(lr, df=1))


def christoffersen_independence_test(breaches: np.ndarray) -> tuple[float, float]:
    b = np.asarray(breaches, dtype=int)
    if len(b) < 2:
        return np.nan, np.nan
    n00 = np.sum((b[:-1] == 0) & (b[1:] == 0))
    n01 = np.sum((b[:-1] == 0) & (b[1:] == 1))
    n10 = np.sum((b[:-1] == 1) & (b[1:] == 0))
    n11 = np.sum((b[:-1] == 1) & (b[1:] == 1))
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return np.nan, np.nan
    pi01 = n01 / (n00 + n01)
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0.0
    pi_ = (n01 + n11) / (n00 + n01 + n10 + n11)
    if pi_ <= 0 or pi_ >= 1:
        return np.nan, np.nan
    eps = 1e-12
    ll_null = (n00 + n10) * np.log(max(1 - pi_, eps)) + (n01 + n11) * np.log(max(pi_, eps))
    ll_alt = (n00 * np.log(max(1 - pi01, eps)) + n01 * np.log(max(pi01, eps))
              + n10 * np.log(max(1 - pi11, eps)) + n11 * np.log(max(pi11, eps)))
    lr = -2 * (ll_null - ll_alt)
    return float(lr), float(1 - stats.chi2.cdf(lr, df=1))


def christoffersen_cc_test(breaches: np.ndarray, alpha: float) -> tuple[float, float]:
    lr_pof, _ = kupiec_pof_test(breaches, alpha)
    lr_ind, _ = christoffersen_independence_test(breaches)
    if np.isnan(lr_pof) or np.isnan(lr_ind):
        return np.nan, np.nan
    lr_cc = lr_pof + lr_ind
    return float(lr_cc), float(1 - stats.chi2.cdf(lr_cc, df=2))


def ljung_box_test(x: np.ndarray, lags: int = 10) -> tuple[float, float]:
    x = np.asarray(x, dtype=float) - np.mean(x)
    n = len(x)
    if n < lags + 5:
        return np.nan, np.nan
    denom = (x ** 2).sum()
    if denom == 0:
        return np.nan, np.nan
    q = 0.0
    for k in range(1, lags + 1):
        num = (x[k:] * x[:-k]).sum()
        rho = num / denom
        q += (rho ** 2) / (n - k - 1)
    q = n * (n + 2) * q
    return float(q), float(1 - stats.chi2.cdf(q, df=lags))


def acerbi_szekely_z2(ret: np.ndarray, var: np.ndarray, es: np.ndarray, alpha: float) -> tuple[float, float]:
    """Acerbi-Szekely (2014) Z2 test. Negative Z2 => ES under-covers tail.
    P-value from 500-sample bootstrap."""
    mask = ~(np.isnan(ret) | np.isnan(var) | np.isnan(es))
    r = ret[mask]; v = var[mask]; e = es[mask]
    breach = (r < v).astype(float)
    N = len(r)
    if N == 0 or breach.sum() == 0 or (e < 0).sum() == 0:
        return np.nan, np.nan
    z2 = (r * breach / np.abs(e)).sum() / (N * alpha) + 1
    rng = np.random.default_rng(42)
    bs = []
    for _ in range(500):
        idx = rng.integers(0, N, size=N)
        br = r[idx]; bv = v[idx]; be = e[idx]
        bb = (br < bv).astype(float)
        if (be < 0).sum() == 0 or bb.sum() == 0:
            continue
        bz = (br * bb / np.abs(be)).sum() / (N * alpha) + 1
        bs.append(bz)
    if len(bs) < 50:
        return float(z2), np.nan
    bs = np.array(bs)
    # Acerbi-Szekely Z2 is one-sided left-tail reject (very negative Z2 => ES insufficient).
    # p-value = P(Z2_boot <= Z2_obs) under H0 via bootstrap.
    pval = (bs <= z2).mean()
    return float(z2), float(max(min(pval, 1.0), 0.0))


# ---------------------------------------------------------------------------
# 6) Quantile loss & DM-HLN
# ---------------------------------------------------------------------------
def quantile_loss_series(ret: np.ndarray, var: np.ndarray, alpha: float) -> np.ndarray:
    """Koenker-Bassett (1978) check function.
    L_alpha(r, q) = (alpha - I{r<q}) * (r - q) = (I{r<q} - alpha) * (q - r).

    Lower loss = better. For DM-HLN(new - base), negative t-stat = new model wins.
    """
    mask = ~(np.isnan(ret) | np.isnan(var))
    r = ret[mask]; v = var[mask]
    ind = (r < v).astype(float)
    # Standard Koenker-Bassett check loss: (alpha - ind) * (r - v)
    return (alpha - ind) * (r - v)


def dm_hln_test(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> tuple[float, float]:
    d = loss_a - loss_b
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = d.mean()
    var_d = np.var(d, ddof=1)
    if var_d <= 0:
        return np.nan, np.nan
    dm = d_mean / np.sqrt(var_d / n)
    k = ((n + 1 - 2 * h + h * (h - 1) / n) / n) ** 0.5
    dm_hln = dm * k
    pval = 2 * (1 - stats.t.cdf(abs(dm_hln), df=n - 1))
    return float(dm_hln), float(pval)


# ---------------------------------------------------------------------------
# 7) Main Experiment
# ---------------------------------------------------------------------------
def run():
    print("[K1115] Loading SPY data...")
    ret = load_spy_returns()
    print(f"  Period: {ret.index[0].date()} to {ret.index[-1].date()}")
    print(f"  N obs: {len(ret)}")

    results: dict[str, Any] = {
        "experiment_id": "K1115",
        "title": "SPY VaR Breach Clustering with Conditional Framework",
        "data_source": "yfinance SPY daily adjusted close",
        "period": {
            "start": str(ret.index[0].date()),
            "end": str(ret.index[-1].date()),
            "n_obs": int(len(ret)),
        },
        "is_period": {"start": str(IS_START.date()), "end": str(IS_END.date())},
        "oos_period": {"start": str(OOS_START.date()), "end": str(OOS_END.date())},
        "alphas": ALPHAS,
        "models": ["M1_empirical", "M2_garch_n", "M3_gjr_t", "M4_gjr_t_breach", "M5_gjr_t_hawkes"],
        "descriptive": {
            "mean": float(ret.mean()),
            "std": float(ret.std()),
            "skew": float(stats.skew(ret)),
            "kurt": float(stats.kurtosis(ret)),
            "min": float(ret.min()),
            "max": float(ret.max()),
        },
    }

    # Fit GARCH models once (they don't depend on alpha)
    print("\n[K1115] Fitting GARCH(1,1) Normal rolling...")
    m2_pg = rolling_garch_forecast(ret, vol="GARCH", dist="normal", p=1, o=0, q=1)
    print("[K1115] Fitting GJR-GARCH Student-t rolling...")
    m3_pg = rolling_garch_forecast(ret, vol="GARCH", dist="t", p=1, o=1, q=1)

    per_alpha = {}

    for alpha in ALPHAS:
        print(f"\n[K1115] === Alpha = {alpha} ===")

        # Model VaRs and ESs
        print("  M1: Empirical rolling quantile...")
        m1_var, m1_es = var_empirical(ret, alpha)

        print("  M2: GARCH(1,1) Normal VaR/ES...")
        m2_var, m2_es = var_es_normal(m2_pg["sigma"], alpha)

        print("  M3: GJR-GARCH Student-t VaR/ES...")
        m3_var, m3_es = var_es_student_t(m3_pg["sigma"], m3_pg["dof"], alpha)

        # Breach features from M3
        print("  Building breach features from M3...")
        features = build_breach_features(ret, m3_var)

        # Fit M4 delta on IS
        is_mask = (ret.index >= IS_START) & (ret.index <= IS_END)
        print("  M4: fitting breach-count delta on IS...")
        delta_m4, scale_m4 = fit_delta_is(
            ret[is_mask], m3_var[is_mask], features.loc[is_mask, "breach_count"], alpha
        )
        print(f"    delta_m4={delta_m4:.4f}, scale={scale_m4:.4f}")

        print("  M5: fitting Hawkes-intensity delta on IS...")
        delta_m5, scale_m5 = fit_delta_is(
            ret[is_mask], m3_var[is_mask], features.loc[is_mask, "hawkes_intensity"], alpha
        )
        print(f"    delta_m5={delta_m5:.4f}, scale={scale_m5:.4f}")

        # Apply to full sample
        bc = features["breach_count"] / scale_m4
        hi = features["hawkes_intensity"] / scale_m5
        m4_var = m3_var * (1.0 + delta_m4 * bc)
        m5_var = m3_var * (1.0 + delta_m5 * hi)
        # ES scales proportionally
        ratio_m4 = (m4_var / m3_var).replace([np.inf, -np.inf], np.nan)
        ratio_m5 = (m5_var / m3_var).replace([np.inf, -np.inf], np.nan)
        m4_es = m3_es * ratio_m4
        m5_es = m3_es * ratio_m5

        # DataFrames
        var_df = pd.DataFrame({
            "ret": ret, "M1": m1_var, "M2": m2_var, "M3": m3_var, "M4": m4_var, "M5": m5_var,
        })
        es_df = pd.DataFrame({
            "M1": m1_es, "M2": m2_es, "M3": m3_es, "M4": m4_es, "M5": m5_es,
        })

        alpha_results = {}
        breach_storage = {}
        for period_name, start, end in [("IS", IS_START, IS_END), ("OOS", OOS_START, OOS_END)]:
            mask = (var_df.index >= start) & (var_df.index <= end)
            period_res = {}
            for model in ["M1", "M2", "M3", "M4", "M5"]:
                v = var_df.loc[mask, model].values
                e = es_df.loc[mask, model].values
                r = var_df.loc[mask, "ret"].values
                valid = ~(np.isnan(r) | np.isnan(v))
                r_v = r[valid]; v_v = v[valid]
                e_v = e[valid] if e is not None else None
                breaches = (r_v < v_v).astype(int)
                if period_name == "OOS" and alpha == 0.01:
                    breach_storage[model] = breaches.tolist()
                lr_k, p_k = kupiec_pof_test(breaches, alpha)
                lr_i, p_i = christoffersen_independence_test(breaches)
                lr_cc, p_cc = christoffersen_cc_test(breaches, alpha)
                lr_lb, p_lb = ljung_box_test(breaches.astype(float), lags=10)
                if e_v is not None and not np.all(np.isnan(e_v)):
                    z2, p_z2 = acerbi_szekely_z2(r_v, v_v, e_v, alpha)
                else:
                    z2, p_z2 = np.nan, np.nan
                ql = quantile_loss_series(r_v, v_v, alpha)
                mean_ql = float(ql.mean()) if len(ql) > 0 else np.nan
                period_res[model] = {
                    "n_obs": int(len(r_v)),
                    "n_breaches": int(breaches.sum()),
                    "breach_rate": float(breaches.mean()) if len(breaches) > 0 else np.nan,
                    "target_alpha": alpha,
                    "kupiec_lr": lr_k, "kupiec_p": p_k,
                    "indep_lr": lr_i, "indep_p": p_i,
                    "cc_lr": lr_cc, "cc_p": p_cc,
                    "ljung_box_q": lr_lb, "ljung_box_p": p_lb,
                    "as_z2": z2, "as_z2_p": p_z2,
                    "mean_quantile_loss": mean_ql,
                    "trinity_pass": bool(
                        (not np.isnan(p_k) and p_k > 0.10) and
                        (not np.isnan(p_cc) and p_cc > 0.10)
                    ),
                }
            # DM-HLN: M4 vs M3 and M5 vs M3
            for m_new in ["M4", "M5"]:
                r_slice = var_df.loc[mask, "ret"].values
                v_base = var_df.loc[mask, "M3"].values
                v_new = var_df.loc[mask, m_new].values
                valid = ~(np.isnan(r_slice) | np.isnan(v_base) | np.isnan(v_new))
                ql_base = quantile_loss_series(r_slice[valid], v_base[valid], alpha)
                ql_new = quantile_loss_series(r_slice[valid], v_new[valid], alpha)
                # Note: negative d_t = loss_new - loss_base means new model better
                dm_t, dm_p = dm_hln_test(ql_new, ql_base)
                period_res[f"DM_{m_new}_vs_M3"] = {"t": dm_t, "p": dm_p}
            alpha_results[period_name] = period_res

        alpha_results["delta_m4"] = float(delta_m4)
        alpha_results["delta_m5"] = float(delta_m5)
        if breach_storage:
            alpha_results["OOS_breach_series"] = breach_storage
        per_alpha[f"alpha_{int(alpha*100):02d}"] = alpha_results

        # Print summary
        print(f"\n  --- IS (alpha={alpha}) ---")
        for m in ["M1", "M2", "M3", "M4", "M5"]:
            r_m = alpha_results["IS"][m]
            print(f"    {m}: n={r_m['n_obs']} br={r_m['n_breaches']} ({r_m['breach_rate']:.4f}) "
                  f"Kupiec p={r_m['kupiec_p']:.3f} CC p={r_m['cc_p']:.3f} LB p={r_m['ljung_box_p']:.3f}")
        print(f"\n  --- OOS (alpha={alpha}) ---")
        for m in ["M1", "M2", "M3", "M4", "M5"]:
            r_m = alpha_results["OOS"][m]
            print(f"    {m}: n={r_m['n_obs']} br={r_m['n_breaches']} ({r_m['breach_rate']:.4f}) "
                  f"Kupiec p={r_m['kupiec_p']:.3f} CC p={r_m['cc_p']:.3f} LB p={r_m['ljung_box_p']:.3f} "
                  f"Trinity={r_m['trinity_pass']}")
        dm4 = alpha_results["OOS"]["DM_M4_vs_M3"]
        dm5 = alpha_results["OOS"]["DM_M5_vs_M3"]
        print(f"    DM(M4 vs M3) OOS: t={dm4['t']:.3f} p={dm4['p']:.3f}")
        print(f"    DM(M5 vs M3) OOS: t={dm5['t']:.3f} p={dm5['p']:.3f}")

        # For alpha=0.01, save breach history CSV
        if alpha == 0.01:
            breach_df = pd.DataFrame({
                "ret": ret, "M3_var": m3_var, "M4_var": m4_var, "M5_var": m5_var,
                "breach_M3": (ret < m3_var).astype(int),
                "breach_M4": (ret < m4_var).astype(int),
                "breach_M5": (ret < m5_var).astype(int),
                "breach_count_lag": features["breach_count"],
                "hawkes_intensity_lag": features["hawkes_intensity"],
            })
            breach_df.to_csv(OUT_DIR / "breach_history.csv")
            print(f"  Saved breach_history.csv")

    results["per_alpha"] = per_alpha

    # H2 PASS evaluation
    h2_eval = {}
    for alpha in ALPHAS:
        key = f"alpha_{int(alpha*100):02d}"
        oos = results["per_alpha"][key]["OOS"]
        for m_new in ["M4", "M5"]:
            k_p = oos[m_new]["kupiec_p"]
            cc_p = oos[m_new]["cc_p"]
            dm_t = oos[f"DM_{m_new}_vs_M3"]["t"]
            cond = (
                (k_p is not None) and (not pd.isna(k_p)) and k_p > 0.10
                and (cc_p is not None) and (not pd.isna(cc_p)) and cc_p > 0.10
                and (dm_t is not None) and (not pd.isna(dm_t)) and abs(dm_t) > 2.0
            )
            h2_eval[f"alpha_{int(alpha*100):02d}_{m_new}"] = {
                "Kupiec_OOS_p": k_p, "CC_OOS_p": cc_p, "DM_HLN_t": dm_t,
                "H2_PASS": bool(cond),
            }
    results["H2_evaluation"] = h2_eval

    # H1 clustering
    h1_eval = {}
    for alpha in ALPHAS:
        key = f"alpha_{int(alpha*100):02d}"
        for m in ["M2", "M3"]:
            is_res = results["per_alpha"][key]["IS"][m]
            oos_res = results["per_alpha"][key]["OOS"][m]
            h1_eval[f"alpha_{int(alpha*100):02d}_{m}"] = {
                "IS_indep_p": is_res["indep_p"],
                "OOS_indep_p": oos_res["indep_p"],
                "H1_IS_cluster": bool(is_res["indep_p"] is not None and not pd.isna(is_res["indep_p"]) and is_res["indep_p"] < 0.05),
                "H1_OOS_cluster": bool(oos_res["indep_p"] is not None and not pd.isna(oos_res["indep_p"]) and oos_res["indep_p"] < 0.05),
            }
    results["H1_evaluation"] = h1_eval

    any_h2 = any(v["H2_PASS"] for v in h2_eval.values())
    results["decision"] = {
        "H2_any_pass": any_h2,
        "Paper_3_niche_confirmed": any_h2,
        "recommendation": (
            "Paper 3 single-asset path-dependent niche CONFIRMED. Write paper."
            if any_h2 else
            "Paper 3 copula niche REJECTED. E055 condition (b) fails for SPY VaR clustering. "
            "Recommend abandoning Paper 3 copula direction or reframing as negative-result paper."
        ),
    }

    # Save
    out_json = OUT_DIR / "k1115_results.json"

    def _clean(o):
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_clean(x) for x in o]
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            v = float(o)
            return None if (np.isnan(v) or np.isinf(v)) else v
        if isinstance(o, (np.ndarray,)):
            return _clean(o.tolist())
        if isinstance(o, float) and (np.isnan(o) or np.isinf(o)):
            return None
        return o

    with open(out_json, "w") as f:
        json.dump(_clean(results), f, indent=2, default=str)
    print(f"\n[K1115] Saved results to {out_json}")

    return results


if __name__ == "__main__":
    run()
