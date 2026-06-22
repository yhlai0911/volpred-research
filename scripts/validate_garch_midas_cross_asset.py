#!/usr/bin/env python3
"""
Validate GARCH-MIDAS(INDPRO) on QQQ and EEM.
Check if SPY result (DM p=0.001) generalizes.

Optimized: vectorized macro alignment, flush output, quarterly OOS re-estimation.
"""

import sys
import time
import warnings
from textwrap import dedent
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

# Force unbuffered output
def log(msg=""):
    print(msg, flush=True)


def _warn_validation(message: str, exc: Exception) -> None:
    log(f"[validate_garch_midas] WARN {message}: {type(exc).__name__}: {exc}")


# ── Vectorized MIDAS functions (replacing slow align_macro_to_daily) ─

def beta_weights(K, w1, w2):
    k = np.arange(1, K + 1, dtype=np.float64)
    log_num = (w1 - 1) * np.log(k) + (w2 - 1) * np.log(np.maximum(K - k, 1e-10))
    log_num -= log_num.max()
    raw = np.exp(log_num)
    total = raw.sum()
    if total < 1e-300:
        return np.ones(K) / K
    return raw / total


def align_macro_to_daily_fast(returns_index, macro_series, K):
    """Vectorized monthly macro alignment. Returns (T, K) matrix."""
    T = len(returns_index)
    macro_aligned = np.zeros((T, K))

    # Build a year-month → value lookup
    macro_ym = {}
    for dt, val in macro_series.items():
        macro_ym[(dt.year, dt.month)] = val

    # Get all year-months available, sorted
    available_yms = sorted(macro_ym.keys())
    available_vals = [macro_ym[ym] for ym in available_yms]

    # Vectorize: extract year/month arrays
    years = np.array([d.year for d in returns_index])
    months = np.array([d.month for d in returns_index])

    for k in range(K):
        lag_months = months - (k + 1)
        lag_years = years.copy()

        # Handle month underflow
        mask = lag_months <= 0
        while mask.any():
            lag_months[mask] += 12
            lag_years[mask] -= 1
            mask = lag_months <= 0

        # Look up values
        for t in range(T):
            key = (lag_years[t], lag_months[t])
            val = macro_ym.get(key)
            if val is not None:
                macro_aligned[t, k] = val
            else:
                # Nearest available
                target = lag_years[t] * 12 + lag_months[t]
                best_idx = 0
                best_dist = abs(available_yms[0][0] * 12 + available_yms[0][1] - target)
                for idx2 in range(1, len(available_yms)):
                    dist = abs(available_yms[idx2][0] * 12 + available_yms[idx2][1] - target)
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = idx2
                macro_aligned[t, k] = available_vals[best_idx]

    return macro_aligned


def align_macro_fast_cached(returns_index, macro_series, K, _cache={}):
    """Cached version - returns dates often overlap across refits."""
    key = (returns_index[0], returns_index[-1], len(returns_index), K)
    if key not in _cache:
        _cache[key] = align_macro_to_daily_fast(returns_index, macro_series, K)
    return _cache[key]


def compute_tau(macro_aligned, m, theta, w1, w2, K):
    weights = beta_weights(K, w1, w2)
    weighted_x = macro_aligned @ weights
    tau = m + theta * weighted_x
    return np.maximum(tau, 1e-12)


def compute_g(returns, tau, alpha, beta, gamma):
    T = len(returns)
    g = np.ones(T)
    intercept = 1.0 - alpha - beta - gamma / 2.0
    for t in range(1, T):
        indicator = 1.0 if returns[t - 1] < 0 else 0.0
        r2_scaled = returns[t - 1] ** 2 / max(tau[t - 1], 1e-12)
        g[t] = intercept + (alpha + gamma * indicator) * r2_scaled + beta * g[t - 1]
        g[t] = max(g[t], 1e-6)
    return g


def neg_log_likelihood(params, returns, macro_aligned, K):
    m, theta, w1, w2, alpha, beta, gamma = params[:7]
    if alpha + beta + gamma / 2.0 >= 1.0:
        return 1e10
    if alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if w1 <= 0 or w2 <= 0:
        return 1e10

    tau = compute_tau(macro_aligned, m, theta, w1, w2, K)
    if np.any(tau <= 0):
        return 1e10
    g = compute_g(returns, tau, alpha, beta, gamma)
    sigma2 = np.maximum(tau * g, 1e-12)

    ll = -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns ** 2 / sigma2)
    total = np.sum(ll)
    return -total if np.isfinite(total) else 1e10


def fit_garch_midas(returns, macro_aligned, K=12, n_starts=3):
    """Fit GARCH-MIDAS and return params + conditional variance."""
    sample_var = np.var(returns)

    starts = [
        np.array([sample_var, 0.0, 1.0, 5.0, 0.05, 0.90, 0.05]),
        np.array([sample_var * 0.5, sample_var * 0.1, 1.0, 3.0, 0.08, 0.85, 0.08]),
        np.array([sample_var * 0.8, 0.0, 1.5, 2.0, 0.10, 0.80, 0.04]),
    ]

    bounds = [
        (1e-10, None), (None, None), (1.01, 50.0), (1.01, 50.0),
        (1e-6, 0.499), (1e-6, 0.999), (0.0, 0.499),
    ]

    best_result = None
    best_nll = np.inf

    for x0 in starts[:n_starts]:
        x0c = x0.copy()
        for j, (lo, hi) in enumerate(bounds):
            if lo is not None: x0c[j] = max(x0c[j], lo * 1.01)
            if hi is not None: x0c[j] = min(x0c[j], hi * 0.99)
        try:
            result = minimize(
                neg_log_likelihood, x0c, args=(returns, macro_aligned, K),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 5000, "ftol": 1e-12, "gtol": 1e-8}
            )
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None:
        return None

    params = best_result.x
    m, theta, w1, w2, alpha, beta, gamma = params
    tau = compute_tau(macro_aligned, m, theta, w1, w2, K)
    g = compute_g(returns, tau, alpha, beta, gamma)
    cv = tau * g

    return {
        "params": params,
        "cv": cv,
        "tau": tau,
        "g": g,
        "loglik": -best_nll,
        "converged": best_result.success,
        "persistence": alpha + beta + gamma / 2.0,
    }


# ── Helper functions ─────────────────────────────────────────────

def qlike(rv, fv):
    ratio = rv / np.maximum(fv, 1e-12)
    return np.mean(ratio - np.log(np.maximum(ratio, 1e-12)) - 1)

def qlike_series(rv, fv):
    ratio = rv / np.maximum(fv, 1e-12)
    return ratio - np.log(np.maximum(ratio, 1e-12)) - 1

def dm_test(loss1, loss2):
    """Diebold-Mariano test. Negative t → model1 better."""
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    # HAC variance (Bartlett kernel, bandwidth = int(T^(1/3)))
    bw = max(1, int(T ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for j in range(1, bw + 1):
        w = 1 - j / (bw + 1)
        gamma_j = np.mean((d[j:] - d_bar) * (d[:-j] - d_bar))
        nw_var += 2 * w * gamma_j
    se = np.sqrt(max(nw_var, 1e-20) / T)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_bar / se
    p_value = 2 * stats.t.sf(abs(t_stat), df=T - 1)
    return t_stat, p_value

def compute_monthly_rv(returns_series):
    rv = (returns_series ** 2).resample("ME").sum()
    return rv[rv > 0]


# ── OOS functions ────────────────────────────────────────────────

def oos_gjr(all_returns, oos_start_idx, refit_every=63):
    """OOS GJR-GARCH with periodic re-estimation."""
    from arch import arch_model
    n_oos = len(all_returns) - oos_start_idx
    cv_oos = np.zeros(n_oos)

    omega = alpha = beta_p = gamma = 0
    last_sigma2 = np.var(all_returns[:oos_start_idx])

    for i in range(n_oos):
        we = oos_start_idx + i
        if i % refit_every == 0:
            ret_w = all_returns[:we] * 100
            try:
                m = arch_model(ret_w, vol="GARCH", p=1, o=1, q=1,
                              dist="normal", mean="Zero", rescale=False)
                r = m.fit(disp="off", show_warning=False)
                p = dict(r.params)
                omega = p.get("omega", 0.01)
                alpha = p.get("alpha[1]", 0.05)
                beta_p = p.get("beta[1]", 0.90)
                gamma = p.get("gamma[1]", 0.05)
                cv_r = r.conditional_volatility
                cv_arr = cv_r.values if hasattr(cv_r, 'values') else cv_r
                last_sigma2 = (cv_arr[-1] ** 2) / 10000
            except Exception as exc:
                _warn_validation(
                    f"GJR refit failed at oos_step={i}, train_end={we}; using previous params",
                    exc,
                )

        last_r = all_returns[we - 1]
        ind = 1.0 if last_r < 0 else 0.0
        r2 = (last_r * 100) ** 2
        next_s2 = omega + alpha * r2 + gamma * r2 * ind + beta_p * (last_sigma2 * 10000)
        cv_oos[i] = next_s2 / 10000
        last_sigma2 = cv_oos[i]

    return cv_oos


def oos_garch_midas(all_returns, all_index, macro_series, oos_start_idx,
                     K=12, refit_every=63):
    """OOS GARCH-MIDAS with periodic re-estimation."""
    n_oos = len(all_returns) - oos_start_idx
    cv_oos = np.zeros(n_oos)

    params = None
    last_g = 1.0
    last_tau = np.var(all_returns[:oos_start_idx])

    for i in range(n_oos):
        we = oos_start_idx + i

        if i % refit_every == 0:
            ret_w = all_returns[:we]
            idx_w = all_index[:we]
            t0 = time.time()
            ma = align_macro_to_daily_fast(idx_w, macro_series, K)
            if i == 0:
                log(f"      Macro alignment: {time.time()-t0:.1f}s for T={we}")
            result = fit_garch_midas(ret_w, ma, K=K, n_starts=3)
            if result is not None:
                params = result["params"]
                last_tau = result["tau"][-1]
                last_g = result["g"][-1]
                if i == 0:
                    log(f"      First fit: {time.time()-t0:.1f}s, loglik={result['loglik']:.1f}")

        if params is None:
            cv_oos[i] = np.var(all_returns[:we])
            continue

        m_p, theta, w1, w2, alpha, beta, gamma = params

        # Update tau on month boundary
        if i > 0 and we < len(all_index):
            cur_date = all_index[we] if we < len(all_index) else all_index[-1]
            prev_date = all_index[we - 1]
            if cur_date.month != prev_date.month:
                # Single-row alignment
                macro_ym = {(dt.year, dt.month): val for dt, val in macro_series.items()}
                weights = beta_weights(K, w1, w2)
                y, mo = cur_date.year, cur_date.month
                weighted_sum = 0.0
                for k_idx in range(K):
                    lag_m = mo - (k_idx + 1)
                    lag_y = y
                    while lag_m <= 0:
                        lag_m += 12
                        lag_y -= 1
                    val = macro_ym.get((lag_y, lag_m), 0.0)
                    weighted_sum += weights[k_idx] * val
                last_tau = max(m_p + theta * weighted_sum, 1e-12)

        last_r = all_returns[we - 1]
        indicator = 1.0 if last_r < 0 else 0.0
        intercept = 1.0 - alpha - beta - gamma / 2.0
        r2_scaled = last_r ** 2 / max(last_tau, 1e-12)
        next_g = intercept + (alpha + gamma * indicator) * r2_scaled + beta * last_g
        next_g = max(next_g, 1e-6)

        cv_oos[i] = max(last_tau * next_g, 1e-12)
        last_g = next_g

    return cv_oos


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    log("=" * 70)
    log("GARCH-MIDAS Cross-Asset Validation: QQQ & EEM")
    log("=" * 70)

    # Download INDPRO
    log("\n[1] Downloading INDPRO from FRED...")
    indpro_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=INDPRO"
    indpro_df = pd.read_csv(indpro_url, parse_dates=["observation_date"])
    indpro_df = indpro_df.rename(columns={"observation_date": "date"}).set_index("date").sort_index()
    indpro_df = indpro_df[indpro_df["INDPRO"] != "."]
    indpro_df["INDPRO"] = indpro_df["INDPRO"].astype(float)
    indpro_growth = np.log(indpro_df["INDPRO"]).diff().dropna()
    log(f"  INDPRO growth: {indpro_growth.index[0].date()} to {indpro_growth.index[-1].date()}, N={len(indpro_growth)}")

    # Download assets
    import yfinance as yf
    assets = ["QQQ", "EEM"]
    asset_data = {}

    log("\n[2] Downloading asset data...")
    for ticker in assets:
        df = yf.download(ticker, start="1999-01-01", end="2026-03-17", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.sort_index()
        df["returns"] = np.log(df["Close"] / df["Close"].shift(1))
        df = df.dropna(subset=["returns"])
        asset_data[ticker] = df
        log(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

    # ── Run experiments ──────────────────────────────────────────────

    IS_END = "2022-12-31"
    OOS_START = "2023-01-01"
    REFIT = 63  # quarterly

    results = []

    for ticker in assets:
        log(f"\n{'=' * 70}")
        log(f"Asset: {ticker}")
        log(f"{'=' * 70}")

        df = asset_data[ticker]
        returns = df["returns"]
        all_ret = returns.values
        all_idx = returns.index

        is_mask = returns.index <= IS_END
        oos_mask = returns.index >= OOS_START
        returns_is = returns[is_mask]
        returns_oos = returns[oos_mask]
        oos_si = np.where(all_idx >= OOS_START)[0][0]

        log(f"  IS: {returns_is.index[0].date()} to {returns_is.index[-1].date()}, N={len(returns_is)}")
        log(f"  OOS: {returns_oos.index[0].date()} to {returns_oos.index[-1].date()}, N={len(returns_oos)}")

        rv_is = returns_is.values ** 2
        rv_oos = returns_oos.values ** 2

        # ── A: GJR-GARCH ──
        log(f"\n  [A] GJR-GARCH(1,1)")
        from arch import arch_model
        t0 = time.time()

        ret_pct_is = returns_is.values * 100
        gjr_m = arch_model(ret_pct_is, vol="GARCH", p=1, o=1, q=1,
                           dist="normal", mean="Zero", rescale=False)
        gjr_r = gjr_m.fit(disp="off", show_warning=False)
        gjr_p = dict(gjr_r.params)
        log(f"      omega={gjr_p.get('omega',0):.6f}, alpha={gjr_p.get('alpha[1]',0):.4f}, "
            f"beta={gjr_p.get('beta[1]',0):.4f}, gamma={gjr_p.get('gamma[1]',0):.4f}")
        log(f"      LogLik: {gjr_r.loglikelihood:.2f}")

        cv_raw = gjr_r.conditional_volatility
        gjr_cv_is = (cv_raw.values if hasattr(cv_raw, 'values') else cv_raw) ** 2 / 10000

        log(f"      OOS expanding (refit every {REFIT}d)...")
        gjr_cv_oos = oos_gjr(all_ret, oos_si, REFIT)
        log(f"      Done in {time.time()-t0:.1f}s")

        # ── B: GARCH-MIDAS(INDPRO) ──
        log(f"\n  [B] GARCH-MIDAS(INDPRO, K=12)")
        t0 = time.time()

        log(f"      Aligning macro data (IS)...")
        ma_indpro_is = align_macro_to_daily_fast(returns_is.index, indpro_growth, 12)
        log(f"      Alignment done in {time.time()-t0:.1f}s")

        result_indpro = fit_garch_midas(returns_is.values, ma_indpro_is, K=12, n_starts=3)
        if result_indpro:
            p = result_indpro["params"]
            log(f"      Converged: {result_indpro['converged']}")
            log(f"      m={p[0]:.8f}, theta={p[1]:.8f}, w1={p[2]:.2f}, w2={p[3]:.2f}")
            log(f"      alpha={p[4]:.4f}, beta={p[5]:.4f}, gamma={p[6]:.4f}")
            log(f"      LogLik: {result_indpro['loglik']:.2f}, Persist: {result_indpro['persistence']:.4f}")
            gm_indpro_cv_is = result_indpro["cv"]

            log(f"      OOS expanding (refit every {REFIT}d)...")
            gm_indpro_cv_oos = oos_garch_midas(all_ret, all_idx, indpro_growth, oos_si, K=12, refit_every=REFIT)
            log(f"      Done in {time.time()-t0:.1f}s")
            indpro_ok = True
        else:
            log(f"      FIT FAILED")
            indpro_ok = False

        # ── C: GARCH-MIDAS(RV) ──
        log(f"\n  [C] GARCH-MIDAS(Monthly RV, K=12)")
        t0 = time.time()

        monthly_rv = compute_monthly_rv(returns)
        ma_rv_is = align_macro_to_daily_fast(returns_is.index, monthly_rv, 12)
        log(f"      Alignment done in {time.time()-t0:.1f}s")

        result_rv = fit_garch_midas(returns_is.values, ma_rv_is, K=12, n_starts=3)
        if result_rv:
            p = result_rv["params"]
            log(f"      Converged: {result_rv['converged']}")
            log(f"      m={p[0]:.8f}, theta={p[1]:.8f}, w1={p[2]:.2f}, w2={p[3]:.2f}")
            log(f"      alpha={p[4]:.4f}, beta={p[5]:.4f}, gamma={p[6]:.4f}")
            log(f"      LogLik: {result_rv['loglik']:.2f}, Persist: {result_rv['persistence']:.4f}")
            gm_rv_cv_is = result_rv["cv"]

            log(f"      OOS expanding (refit every {REFIT}d)...")
            gm_rv_cv_oos = oos_garch_midas(all_ret, all_idx, monthly_rv, oos_si, K=12, refit_every=REFIT)
            log(f"      Done in {time.time()-t0:.1f}s")
            rv_ok = True
        else:
            log(f"      FIT FAILED")
            rv_ok = False

        # ── Evaluate ──
        log(f"\n  {'─' * 55}")
        log(f"  RESULTS: {ticker}")
        log(f"  {'─' * 55}")

        gjr_is_q = qlike(rv_is, gjr_cv_is)
        gjr_oos_q = qlike(rv_oos, gjr_cv_oos)

        gm_ind_is_q = qlike(rv_is, gm_indpro_cv_is) if indpro_ok else np.nan
        gm_ind_oos_q = qlike(rv_oos, gm_indpro_cv_oos) if indpro_ok else np.nan
        gm_rv_is_q = qlike(rv_is, gm_rv_cv_is) if rv_ok else np.nan
        gm_rv_oos_q = qlike(rv_oos, gm_rv_cv_oos) if rv_ok else np.nan

        log(f"\n  {'Model':<25} {'IS QLIKE':>12} {'OOS QLIKE':>12}")
        log(f"  {'-'*50}")
        log(f"  {'GJR-GARCH(1,1)':<25} {gjr_is_q:>12.6f} {gjr_oos_q:>12.6f}")
        if indpro_ok:
            log(f"  {'GARCH-MIDAS(INDPRO)':<25} {gm_ind_is_q:>12.6f} {gm_ind_oos_q:>12.6f}")
        if rv_ok:
            log(f"  {'GARCH-MIDAS(RV)':<25} {gm_rv_is_q:>12.6f} {gm_rv_oos_q:>12.6f}")

        # DM tests
        gjr_loss = qlike_series(rv_oos, gjr_cv_oos)

        dm_t_ind = dm_p_ind = dm_t_rv = dm_p_rv = np.nan

        log(f"\n  Diebold-Mariano test (OOS, vs GJR-GARCH):")
        if indpro_ok:
            ind_loss = qlike_series(rv_oos, gm_indpro_cv_oos)
            dm_t_ind, dm_p_ind = dm_test(ind_loss, gjr_loss)
            sig = "***" if dm_p_ind < 0.01 else ("**" if dm_p_ind < 0.05 else ("*" if dm_p_ind < 0.10 else "n.s."))
            direction = "MIDAS better" if dm_t_ind < 0 else "GJR better"
            log(f"    INDPRO: t={dm_t_ind:+.4f}, p={dm_p_ind:.4f} [{sig}] ({direction})")

        if rv_ok:
            rv_loss = qlike_series(rv_oos, gm_rv_cv_oos)
            dm_t_rv, dm_p_rv = dm_test(rv_loss, gjr_loss)
            sig = "***" if dm_p_rv < 0.01 else ("**" if dm_p_rv < 0.05 else ("*" if dm_p_rv < 0.10 else "n.s."))
            direction = "MIDAS better" if dm_t_rv < 0 else "GJR better"
            log(f"    RV:     t={dm_t_rv:+.4f}, p={dm_p_rv:.4f} [{sig}] ({direction})")

        # Store
        for model_name, is_q, oos_q, dm_t, dm_p in [
            ("GJR-GARCH(1,1)", gjr_is_q, gjr_oos_q, "---", "---"),
            ("GM-MIDAS(INDPRO)", gm_ind_is_q, gm_ind_oos_q,
             f"{dm_t_ind:+.4f}" if not np.isnan(dm_t_ind) else "N/A",
             f"{dm_p_ind:.4f}" if not np.isnan(dm_p_ind) else "N/A"),
            ("GM-MIDAS(RV)", gm_rv_is_q, gm_rv_oos_q,
             f"{dm_t_rv:+.4f}" if not np.isnan(dm_t_rv) else "N/A",
             f"{dm_p_rv:.4f}" if not np.isnan(dm_p_rv) else "N/A"),
        ]:
            results.append({"Asset": ticker, "Model": model_name,
                            "IS_QLIKE": is_q, "OOS_QLIKE": oos_q,
                            "DM_t": dm_t, "DM_p": dm_p})


    # ═══════════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════════

    log(f"\n\n{'=' * 78}")
    log("CROSS-ASSET SUMMARY TABLE")
    log(f"{'=' * 78}")
    log(f"{'Asset':<6} {'Model':<20} {'IS QLIKE':>12} {'OOS QLIKE':>12} {'DM t':>10} {'DM p':>10}")
    log("-" * 72)
    for r in results:
        is_q = f"{r['IS_QLIKE']:.6f}" if isinstance(r['IS_QLIKE'], float) and not np.isnan(r['IS_QLIKE']) else "N/A"
        oos_q = f"{r['OOS_QLIKE']:.6f}" if isinstance(r['OOS_QLIKE'], float) and not np.isnan(r['OOS_QLIKE']) else "N/A"
        log(f"{r['Asset']:<6} {r['Model']:<20} {is_q:>12} {oos_q:>12} {r['DM_t']:>10} {r['DM_p']:>10}")

    log(f"\n{'=' * 78}")
    log("GENERALIZATION ASSESSMENT")
    log(f"{'=' * 78}")
    log(dedent("""
    SPY baseline (from prior experiment):
      GARCH-MIDAS(INDPRO) vs GJR: DM p = 0.001 (significant, MIDAS better)

    Criteria for generalization:
      Strong:  Both QQQ/EEM show DM p < 0.05 favoring GARCH-MIDAS(INDPRO)
      Partial: One asset shows p < 0.10, other is n.s.
      Fails:   Neither shows significant improvement

    If INDPRO fails but RV works:
      → Macro channel is SPY-specific; volatility feedback is more universal
    If both fail:
      → SPY result may be sample-specific or driven by SPY-INDPRO correlation
    """))


if __name__ == "__main__":
    main()
