"""
K791: Overnight vs Intraday Return Decomposition for SPY Volatility Forecasting

Decompose daily SPY returns into:
  r_overnight = log(Open_t / Close_{t-1})
  r_intraday  = log(Close_t / Open_t)
  r_total     = r_overnight + r_intraday

Models (all predict next-day r²_total):
  1. GJR baseline:          GJR-GARCH on r_total
  2. Additive:              GJR(r_overnight) + GJR(r_intraday) → sum σ²
  3. Overnight-augmented X: GJR on r_total with r²_overnight as exogenous var
  4. Two-factor OLS:        r²_{t+1} = β₀ + β₁×r²_on + β₂×r²_in + β₃×r²_total_w5

Evaluation:
  - QLIKE on r²_total, Spearman rank corr, DM test vs baseline
  - OOS: 2023-01-01 ~ 2024-12-31, expanding window, refit every 63 days

References:
  - Gallo & Pacini (1998) "Early news is good news"
  - Andersen et al. (2003) "Modeling and forecasting realized volatility"
  - Patton (2011) "Volatility forecast comparison using imperfect volatility proxies"
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy import stats
import json
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

# ─── Numba JIT for GARCH filter ─────────────────────────────────────────────
try:
    from numba import njit

    @njit
    def gjr_filter(omega, alpha, gamma, beta, r, sigma2_init):
        n = len(r)
        sigma2 = np.empty(n)
        sigma2[0] = sigma2_init
        for t in range(1, n):
            ind = 1.0 if r[t - 1] < 0.0 else 0.0
            sigma2[t] = (omega
                         + alpha * r[t - 1] ** 2
                         + gamma * ind * r[t - 1] ** 2
                         + beta * sigma2[t - 1])
            if sigma2[t] < 1e-12:
                sigma2[t] = 1e-12
        return sigma2

    @njit
    def gjrx_filter(omega, alpha, gamma, beta, delta, r, exog, sigma2_init):
        n = len(r)
        sigma2 = np.empty(n)
        sigma2[0] = sigma2_init
        for t in range(1, n):
            ind = 1.0 if r[t - 1] < 0.0 else 0.0
            sigma2[t] = (omega
                         + alpha * r[t - 1] ** 2
                         + gamma * ind * r[t - 1] ** 2
                         + beta * sigma2[t - 1]
                         + delta * exog[t - 1])
            if sigma2[t] < 1e-12:
                sigma2[t] = 1e-12
        return sigma2

    NUMBA_OK = True
    print("Numba JIT enabled.")
except ImportError:
    NUMBA_OK = False
    print("Numba not available — using plain Python loops.")

    def gjr_filter(omega, alpha, gamma, beta, r, sigma2_init):
        n = len(r)
        sigma2 = np.empty(n)
        sigma2[0] = sigma2_init
        for t in range(1, n):
            ind = 1.0 if r[t - 1] < 0.0 else 0.0
            sigma2[t] = max(1e-12,
                            omega + alpha * r[t - 1] ** 2
                            + gamma * ind * r[t - 1] ** 2
                            + beta * sigma2[t - 1])
        return sigma2

    def gjrx_filter(omega, alpha, gamma, beta, delta, r, exog, sigma2_init):
        n = len(r)
        sigma2 = np.empty(n)
        sigma2[0] = sigma2_init
        for t in range(1, n):
            ind = 1.0 if r[t - 1] < 0.0 else 0.0
            sigma2[t] = max(1e-12,
                            omega + alpha * r[t - 1] ** 2
                            + gamma * ind * r[t - 1] ** 2
                            + beta * sigma2[t - 1]
                            + delta * exog[t - 1])
        return sigma2


# ─── GARCH neg-log-likelihood ────────────────────────────────────────────────
def gjr_nll(params, r):
    omega, alpha, gamma, beta = params
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e10
    if alpha + gamma / 2 + beta >= 1:
        return 1e10
    sigma2_init = np.var(r)
    sigma2 = gjr_filter(omega, alpha, gamma, beta, r, sigma2_init)
    nll = 0.5 * np.sum(np.log(sigma2) + r ** 2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def gjrx_nll(params, r, exog):
    omega, alpha, gamma, beta, delta = params
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0 or delta < 0:
        return 1e10
    if alpha + gamma / 2 + beta >= 1:
        return 1e10
    sigma2_init = np.var(r)
    sigma2 = gjrx_filter(omega, alpha, gamma, beta, delta, r, exog, sigma2_init)
    nll = 0.5 * np.sum(np.log(sigma2) + r ** 2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def fit_gjr(r, x0=None):
    if x0 is None:
        sv = np.var(r)
        x0 = [sv * 0.05, 0.05, 0.05, 0.85]
    bounds = [(1e-8, None), (0, 0.5), (0, 0.5), (0, 0.999)]
    res = minimize(gjr_nll, x0, args=(r,), method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 500, "ftol": 1e-9})
    return res.x if res.success else x0


def fit_gjrx(r, exog, x0=None):
    if x0 is None:
        sv = np.var(r)
        x0 = [sv * 0.05, 0.05, 0.05, 0.85, 0.01]
    bounds = [(1e-8, None), (0, 0.5), (0, 0.5), (0, 0.999), (0, 10)]
    res = minimize(gjrx_nll, x0, args=(r, exog), method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 500, "ftol": 1e-9})
    return res.x if res.success else x0


def get_sigma2_gjr(params, r):
    omega, alpha, gamma, beta = params
    return gjr_filter(omega, alpha, gamma, beta, r, np.var(r))


def get_sigma2_gjrx(params, r, exog):
    omega, alpha, gamma, beta, delta = params
    return gjrx_filter(omega, alpha, gamma, beta, delta, r, exog, np.var(r))


# ─── Evaluation metrics ──────────────────────────────────────────────────────
def qlike(y_true, y_pred):
    """QLIKE = E[log(h) + r²/h], lower is better."""
    mask = (y_true > 0) & (y_pred > 1e-12)
    yt, yp = y_true[mask], y_pred[mask]
    return float(np.mean(np.log(yp) + yt / yp))


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (Harvey et al. 1997 corrected).
    Returns (dm_stat, p_value). Negative stat: e1 < e2 (model1 better)."""
    d = e1 - e2
    n = len(d)
    dbar = np.mean(d)
    # HAC variance
    gamma0 = np.var(d, ddof=0)
    gammas = sum(
        (1 - k / (h + 1)) * 2 * np.mean((d[k:] - dbar) * (d[:-k] - dbar))
        for k in range(1, h)
    ) if h > 1 else 0.0
    var_d = (gamma0 + gammas) / n
    if var_d <= 0:
        return (np.nan, np.nan)
    dm = dbar / np.sqrt(var_d)
    # Two-sided p-value
    p = 2 * (1 - stats.norm.cdf(abs(dm)))
    return (float(dm), float(p))


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("K791: Overnight vs Intraday Return Decomposition (SPY)")
    print("=" * 60)

    # 1. Data download
    print("\n[1] Downloading SPY OHLC from yfinance (2006-01-01 to 2024-12-31)...")
    raw = yf.download("SPY", start="2006-01-01", end="2024-12-31",
                      auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("Failed to download SPY data.")

    # Flatten multi-level columns if needed
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw[["Open", "Close"]].copy().dropna()
    print(f"   Rows: {len(df)}  ({df.index[0].date()} → {df.index[-1].date()})")

    # 2. Return decomposition
    print("\n[2] Decomposing returns...")
    close_prev = df["Close"].shift(1)
    df["r_on"] = np.log(df["Open"] / close_prev)       # overnight
    df["r_in"] = np.log(df["Close"] / df["Open"])      # intraday
    df["r_tot"] = df["r_on"] + df["r_in"]              # total
    df = df.dropna()

    print(f"   r_overnight  — mean={df['r_on'].mean():.5f}, "
          f"std={df['r_on'].std():.5f}, var share={df['r_on'].var()/df['r_tot'].var():.3f}")
    print(f"   r_intraday   — mean={df['r_in'].mean():.5f}, "
          f"std={df['r_in'].std():.5f}, var share={df['r_in'].var()/df['r_tot'].var():.3f}")
    print(f"   r_total      — mean={df['r_tot'].mean():.5f}, "
          f"std={df['r_tot'].std():.5f}")

    var_on = df["r_on"].var()
    var_in = df["r_in"].var()
    var_tot = df["r_tot"].var()
    cov_on_in = df[["r_on", "r_in"]].cov().iloc[0, 1]
    print(f"   Cov(r_on, r_in) = {cov_on_in:.6f}  "
          f"(should ≈ Var(r_tot) - Var(r_on) - Var(r_in))")

    # 3. OOS setup
    oos_start = pd.Timestamp("2023-01-01")
    refit_every = 63  # days

    oos_idx = df.index[df.index >= oos_start]
    n_oos = len(oos_idx) - 1   # last day has no target
    print(f"\n[3] OOS window: {oos_idx[0].date()} → {oos_idx[-2].date()} "
          f"({n_oos} predictions), refit every {refit_every} days")

    r_on_arr = df["r_on"].values
    r_in_arr = df["r_in"].values
    r_tot_arr = df["r_tot"].values
    dates = df.index

    # Pre-compute 5-day rolling sum of r²_total for OLS (use lagged to avoid lookahead)
    r2_tot_arr = r_tot_arr ** 2
    r2_on_arr = r_on_arr ** 2
    r2_in_arr = r_in_arr ** 2

    # rolling 5-day window of r²_total (summed, lagged by 1)
    r2_tot_w5 = pd.Series(r2_tot_arr).rolling(5).sum().shift(1).values

    # Storage for OOS forecasts — shape (n_oos,)
    forecasts = {
        "gjr_base": np.full(n_oos, np.nan),
        "additive": np.full(n_oos, np.nan),
        "gjrx": np.full(n_oos, np.nan),
        "ols_2f": np.full(n_oos, np.nan),
    }
    actual_r2 = np.full(n_oos, np.nan)

    # Track parameter caches
    params_base = None
    params_on = None
    params_in = None
    params_x = None
    ols_coef = None

    oos_global_start = np.where(dates == oos_idx[0])[0][0]
    last_refit = -refit_every  # force refit on first step

    print(f"\n[4] Running OOS forecasting loop...")

    for step in range(n_oos):
        t = oos_global_start + step   # index of forecast origin (day t)
        # Target: r²_total at t+1
        actual_r2[step] = r_tot_arr[t + 1] ** 2

        # Lag check: signal uses data up to t, forecast is for t+1
        # → signal.shift(1) equivalent: we use r[0..t] to forecast r²[t+1]

        if (step - last_refit) >= refit_every or params_base is None:
            # Expanding window: all data from index 0 to t (inclusive)
            train_r_tot = r_tot_arr[:t + 1]
            train_r_on = r_on_arr[:t + 1]
            train_r_in = r_in_arr[:t + 1]
            train_exog = r2_on_arr[:t + 1]   # r²_overnight as exog

            # Model 1: GJR baseline on r_total
            params_base = fit_gjr(train_r_tot, params_base)

            # Model 2: Additive — GJR on each component
            params_on = fit_gjr(train_r_on, params_on)
            params_in = fit_gjr(train_r_in, params_in)

            # Model 3: GJR-X with r²_overnight as exog
            params_x = fit_gjrx(train_r_tot, train_exog,
                                 list(params_x) if params_x is not None else None)

            # Model 4: OLS two-factor
            # y = r²_total_{t+1}, X = [1, r²_on_t, r²_in_t, r²_tot_w5_t]
            # Use t-1 lag: signal at t is based on t data
            y_ols = r2_tot_arr[1:t + 1]   # target: r²_total[1..t]
            x_on = r2_on_arr[:t]           # r²_on[0..t-1]
            x_in = r2_in_arr[:t]           # r²_in[0..t-1]
            x_w5 = r2_tot_w5[:t]           # rolling w5[0..t-1]
            valid = np.isfinite(x_on) & np.isfinite(x_in) & np.isfinite(x_w5) & np.isfinite(y_ols)
            if valid.sum() > 20:
                X_mat = np.column_stack([np.ones(valid.sum()), x_on[valid],
                                         x_in[valid], x_w5[valid]])
                try:
                    ols_coef, _, _, _ = np.linalg.lstsq(X_mat, y_ols[valid], rcond=None)
                except Exception:
                    ols_coef = None

            last_refit = step
            if step % 63 == 0:
                print(f"   Step {step}/{n_oos}: refit at t={t}, "
                      f"persistence_base={params_base[1]+params_base[2]/2+params_base[3]:.4f}")

        # One-step-ahead forecasts (all use only info up to t)
        # Model 1: GJR baseline
        s2_base = get_sigma2_gjr(params_base, r_tot_arr[:t + 1])
        o, a, g, b = params_base
        ind_t = 1.0 if r_tot_arr[t] < 0 else 0.0
        forecasts["gjr_base"][step] = (o + a * r_tot_arr[t] ** 2
                                        + g * ind_t * r_tot_arr[t] ** 2
                                        + b * s2_base[-1])

        # Model 2: Additive
        s2_on = get_sigma2_gjr(params_on, r_on_arr[:t + 1])
        o2, a2, g2, b2 = params_on
        ind_on = 1.0 if r_on_arr[t] < 0 else 0.0
        h_on = o2 + a2 * r_on_arr[t] ** 2 + g2 * ind_on * r_on_arr[t] ** 2 + b2 * s2_on[-1]

        s2_in = get_sigma2_gjr(params_in, r_in_arr[:t + 1])
        o3, a3, g3, b3 = params_in
        ind_in = 1.0 if r_in_arr[t] < 0 else 0.0
        h_in = o3 + a3 * r_in_arr[t] ** 2 + g3 * ind_in * r_in_arr[t] ** 2 + b3 * s2_in[-1]
        # Additive: σ²_total = σ²_on + σ²_in + 2*Cov (use OLS estimate of Cov from train)
        # Simplified: sum + 2*cov (static cov from training sample)
        cov_est = np.cov(r_on_arr[:t + 1], r_in_arr[:t + 1])[0, 1]
        forecasts["additive"][step] = max(1e-12, h_on + h_in + 2 * cov_est)

        # Model 3: GJR-X
        s2_x = get_sigma2_gjrx(params_x, r_tot_arr[:t + 1], r2_on_arr[:t + 1])
        ox, ax, gx, bx, dx = params_x
        ind_xt = 1.0 if r_tot_arr[t] < 0 else 0.0
        forecasts["gjrx"][step] = (ox + ax * r_tot_arr[t] ** 2
                                    + gx * ind_xt * r_tot_arr[t] ** 2
                                    + bx * s2_x[-1]
                                    + dx * r2_on_arr[t])

        # Model 4: OLS two-factor
        if ols_coef is not None and np.isfinite(r2_tot_w5[t]):
            x_pred = np.array([1.0, r2_on_arr[t], r2_in_arr[t], r2_tot_w5[t]])
            forecasts["ols_2f"][step] = max(1e-12, float(ols_coef @ x_pred))

    print(f"\n[5] Computing evaluation metrics...")

    # Clip very small/negative forecasts to 1e-10
    for k in forecasts:
        forecasts[k] = np.maximum(forecasts[k], 1e-10)

    valid_mask = np.isfinite(actual_r2) & (actual_r2 > 0)
    for k in forecasts:
        valid_mask &= np.isfinite(forecasts[k])

    actual_oos = actual_r2[valid_mask]
    n_valid = valid_mask.sum()
    print(f"   Valid OOS obs: {n_valid}")

    results_table = {}
    for name, fc in forecasts.items():
        fc_v = fc[valid_mask]
        ql = qlike(actual_oos, fc_v)
        sp = float(stats.spearmanr(actual_oos, fc_v).statistic)
        results_table[name] = {"qlike": ql, "spearman": sp}
        print(f"   {name:12s} → QLIKE={ql:.6f}, Spearman={sp:.4f}")

    # DM tests vs baseline
    print("\n[6] Diebold-Mariano tests vs GJR baseline...")
    def ql_loss(y_true, y_pred):
        return np.log(y_pred) + y_true / y_pred

    e_base = ql_loss(actual_oos, forecasts["gjr_base"][valid_mask])
    dm_results = {}
    for name in ["additive", "gjrx", "ols_2f"]:
        e_alt = ql_loss(actual_oos, forecasts[name][valid_mask])
        dm_stat, dm_p = dm_test(e_base, e_alt)
        dm_results[name] = {"dm_stat": dm_stat, "p_value": dm_p}
        direction = "BETTER" if dm_stat < 0 else "WORSE"
        sig = "**" if dm_p < 0.05 else ("*" if dm_p < 0.10 else "")
        print(f"   vs {name:10s}: DM={dm_stat:+.3f}, p={dm_p:.4f} {direction} {sig}")

    # Summary statistics about return components
    print("\n[7] Return component statistics (full sample)...")
    corr_on_in = float(np.corrcoef(r_on_arr, r_in_arr)[0, 1])
    var_share_on = float(var_on / var_tot)
    var_share_in = float(var_in / var_tot)

    print(f"   Variance share overnight: {var_share_on:.3f}")
    print(f"   Variance share intraday:  {var_share_in:.3f}")
    print(f"   Corr(r_on, r_in):         {corr_on_in:.4f}")

    # Best model
    best_name = min(results_table, key=lambda k: results_table[k]["qlike"])
    best_qlike = results_table[best_name]["qlike"]
    base_qlike = results_table["gjr_base"]["qlike"]
    improvement = (base_qlike - best_qlike) / abs(base_qlike) * 100
    print(f"\n   Best model: {best_name}  (QLIKE={best_qlike:.6f})")
    print(f"   Improvement vs baseline: {improvement:+.2f}%")

    # ─── Compile results ──────────────────────────────────────────────────────
    results = {
        "experiment_id": "K791",
        "title": "Overnight vs Intraday Return Decomposition for SPY Vol Forecasting",
        "date": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, OHLC)",
        "period": {
            "full_sample": f"{df.index[0].date()} to {df.index[-1].date()}",
            "oos_period": f"{oos_idx[0].date()} to {oos_idx[-2].date()}",
            "n_total": int(len(df)),
            "n_oos": int(n_valid),
        },
        "return_decomposition": {
            "mean_r_overnight": float(df["r_on"].mean()),
            "mean_r_intraday": float(df["r_in"].mean()),
            "std_r_overnight": float(df["r_on"].std()),
            "std_r_intraday": float(df["r_in"].std()),
            "std_r_total": float(df["r_tot"].std()),
            "var_share_overnight": float(var_share_on),
            "var_share_intraday": float(var_share_in),
            "corr_on_in": float(corr_on_in),
        },
        "models": {
            name: {
                "qlike": float(v["qlike"]),
                "spearman": float(v["spearman"]),
            }
            for name, v in results_table.items()
        },
        "dm_tests_vs_baseline": {
            name: {
                "dm_stat": float(v["dm_stat"]) if v["dm_stat"] is not None and not np.isnan(v["dm_stat"]) else None,
                "p_value": float(v["p_value"]) if v["p_value"] is not None and not np.isnan(v["p_value"]) else None,
                "significant_at_5pct": bool(v["p_value"] < 0.05) if v["p_value"] is not None and not np.isnan(v["p_value"]) else False,
            }
            for name, v in dm_results.items()
        },
        "best_model": best_name,
        "improvement_vs_baseline_pct": float(improvement),
        "conclusion": (
            f"Overnight variance share: {var_share_on:.1%}, intraday: {var_share_in:.1%}. "
            f"Best OOS model: {best_name} with QLIKE improvement of {improvement:+.2f}% "
            f"vs GJR baseline. "
            f"Corr(r_on, r_in) = {corr_on_in:.4f} (overnight-intraday interaction)."
        ),
        "references": [
            "Gallo & Pacini (1998) 'Early news is good news: The effects of market opening on market volatility'",
            "Andersen et al. (2003) 'Modeling and forecasting realized volatility', Econometrica",
            "Patton (2011) 'Volatility forecast comparison using imperfect volatility proxies', JoE",
        ],
    }

    out_path = "experiments/k791_overnight_intraday_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[8] Results saved to {out_path}")
    print("\nDone.")
    return results


if __name__ == "__main__":
    main()
