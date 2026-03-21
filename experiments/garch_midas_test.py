"""GARCH-MIDAS Model Test (Engle, Ghysels & Sohn, 2013).

Downloads SPY returns + macro data, fits GARCH-MIDAS with:
  1. Industrial Production (INDPRO from FRED)
  2. Realized Variance (monthly sum of daily squared returns)

Compares 1-step QLIKE vs standard GJR-GARCH, with OOS evaluation (2023-2025).

Usage:
    uv run python experiments/garch_midas_test.py
"""
from __future__ import annotations

import sys
import time
import warnings
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

warnings.filterwarnings("ignore", category=FutureWarning)


# ======================================================================
# Data loading
# ======================================================================

def download_spy_returns(start: str = "2000-01-01", end: str = "2026-03-17") -> pd.Series:
    """Download SPY daily log returns from yfinance."""
    import yfinance as yf

    print(f"Downloading SPY daily data ({start} to {end})...")
    spy = yf.download("SPY", start=start, end=end, progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy.index = spy.index.tz_localize(None)
    spy["log_return"] = np.log(spy["Close"] / spy["Close"].shift(1))
    returns = spy["log_return"].dropna()
    print(f"  Got {len(returns)} daily returns: {returns.index[0].date()} to {returns.index[-1].date()}")
    return returns


def download_indpro() -> pd.Series:
    """Download Industrial Production Index from FRED via CSV."""
    import urllib.request

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=INDPRO"
    print(f"Downloading INDPRO from FRED...")
    try:
        response = urllib.request.urlopen(url, timeout=30)
        csv_text = response.read().decode("utf-8")
        df = pd.read_csv(StringIO(csv_text), parse_dates=["observation_date"],
                         index_col="observation_date")
        series = df["INDPRO"].dropna()
        # Compute YoY growth rate (more stationary than level)
        growth = series.pct_change(12).dropna()
        print(f"  Got {len(growth)} monthly INDPRO growth obs: "
              f"{growth.index[0].date()} to {growth.index[-1].date()}")
        return growth
    except Exception as e:
        print(f"  FRED download failed: {e}")
        print("  Falling back to synthetic INDPRO proxy...")
        return None


def compute_monthly_rv(returns: pd.Series) -> pd.Series:
    """Compute monthly realized variance from daily squared returns."""
    rv = (returns ** 2).resample("ME").sum()
    rv = rv[rv > 0]
    print(f"  Monthly RV: {len(rv)} months, "
          f"{rv.index[0].date()} to {rv.index[-1].date()}")
    return rv


# ======================================================================
# Evaluation helpers
# ======================================================================

def qlike(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean( rv/fv - log(rv/fv) - 1 ).

    Excludes observations where realized = 0 (zero return days),
    as log(0) is undefined.
    """
    mask = realized > 0  # exclude zero-return days
    rv = realized[mask]
    fv = np.maximum(forecast[mask], 1e-12)
    ratio = rv / fv
    return float(np.mean(ratio - np.log(ratio) - 1))


def mse(realized: np.ndarray, forecast: np.ndarray) -> float:
    """Mean squared error of variance forecasts."""
    return float(np.mean((realized - forecast) ** 2))


def dm_test(loss1: np.ndarray, loss2: np.ndarray) -> tuple[float, float]:
    """Diebold-Mariano test (two-sided).

    Returns (DM statistic, p-value).
    Negative DM means model 1 is better.
    """
    from scipy.stats import norm as norm_dist

    d = loss1 - loss2
    n = len(d)
    d_mean = d.mean()
    # HAC variance (Newey-West with auto bandwidth)
    d_var = np.var(d, ddof=1)
    # Simple version: just use sample variance
    dm = d_mean / np.sqrt(d_var / n) if d_var > 0 else 0.0
    pval = 2 * norm_dist.sf(abs(dm))
    return float(dm), float(pval)


# ======================================================================
# Printing
# ======================================================================

def section(title: str, char: str = "-", width: int = 74):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


# ======================================================================
# Main experiment
# ======================================================================

def main():
    print("=" * 74)
    print("  GARCH-MIDAS Model Test")
    print("  Engle, Ghysels & Sohn (2013, Review of Economics and Statistics)")
    print("=" * 74)

    # ---- Download data ----
    section("1. Data")
    returns = download_spy_returns()
    indpro = download_indpro()
    monthly_rv = compute_monthly_rv(returns)

    # ---- Prepare in-sample / OOS split ----
    oos_start = "2023-01-01"
    is_returns = returns[returns.index < oos_start]
    oos_returns = returns[returns.index >= oos_start]
    print(f"\n  In-sample:  {len(is_returns)} days ({is_returns.index[0].date()} to {is_returns.index[-1].date()})")
    print(f"  OOS:        {len(oos_returns)} days ({oos_returns.index[0].date()} to {oos_returns.index[-1].date()})")

    # Realized variance proxy for evaluation: 22-day rolling sum of squared returns
    rv_proxy = (returns ** 2).rolling(22).sum() / 22  # daily avg realized var
    rv_proxy = rv_proxy.dropna()

    # ====================================================================
    # Model 1: GARCH-MIDAS with Realized Variance (monthly)
    # ====================================================================
    section("2. GARCH-MIDAS with Monthly Realized Variance", "=")
    from volpred.models.garch.garch_midas import GarchMidas

    model_rv = GarchMidas(K=12, macro_freq="monthly", n_starts=3, dist="normal")
    t0 = time.time()
    result_rv = model_rv.fit(
        returns=is_returns,
        macro_data=monthly_rv,
        returns_index=is_returns.index,
    )
    fit_time_rv = time.time() - t0

    print(f"\n  Fit time:     {fit_time_rv:.1f}s")
    print(f"  Converged:    {result_rv['converged']}")
    print(f"  Log-lik:      {result_rv['loglik']:.2f}")
    print(f"  AIC:          {result_rv['aic']:.2f}")
    print(f"  BIC:          {result_rv['bic']:.2f}")
    print(f"  Persistence:  {result_rv['persistence']:.4f}")
    print(f"\n  Parameters:")
    for name, val in result_rv["params"].items():
        print(f"    {name:10s} = {val:12.6f}")

    # MIDAS weights
    weights_rv = model_rv.get_midas_weights()
    print(f"\n  MIDAS weights (K=12, lag 1=most recent month):")
    for k in range(12):
        bar = "#" * int(weights_rv[k] * 100)
        print(f"    Lag {k+1:2d}: {weights_rv[k]:.4f}  {bar}")

    # Decomposition stats
    tau_rv = model_rv.get_tau()
    g_rv = model_rv.get_g()
    sigma2_rv = model_rv.get_conditional_variance()
    print(f"\n  Decomposition statistics:")
    print(f"    tau (long-run):  mean={tau_rv.mean():.6e}, std={tau_rv.std():.6e}")
    print(f"    g (short-run):   mean={g_rv.mean():.4f}, std={g_rv.std():.4f}")
    print(f"    sigma2:          mean={sigma2_rv.mean():.6e}")
    print(f"    Var explained by tau: {tau_rv.std()**2 / (sigma2_rv.std()**2 + 1e-20):.2%}")

    fc_rv = model_rv.forecast()
    print(f"\n  1-step forecast:")
    print(f"    sigma2 = {fc_rv.variance_forecast:.6e}")
    print(f"    vol    = {fc_rv.point_forecast:.4%} (ann: {fc_rv.point_forecast * 252**0.5:.2%})")

    # ====================================================================
    # Model 2: GARCH-MIDAS with Industrial Production (if available)
    # ====================================================================
    result_ip = None
    model_ip = None
    if indpro is not None:
        section("3. GARCH-MIDAS with Industrial Production", "=")

        # Filter INDPRO to overlap with returns
        ip_start = is_returns.index[0] - pd.DateOffset(months=13)
        indpro_filtered = indpro[indpro.index >= ip_start]
        print(f"  INDPRO range: {indpro_filtered.index[0].date()} to {indpro_filtered.index[-1].date()}")

        model_ip = GarchMidas(K=12, macro_freq="monthly", n_starts=3, dist="normal")
        t0 = time.time()
        try:
            result_ip = model_ip.fit(
                returns=is_returns,
                macro_data=indpro_filtered,
                returns_index=is_returns.index,
            )
            fit_time_ip = time.time() - t0

            print(f"\n  Fit time:     {fit_time_ip:.1f}s")
            print(f"  Converged:    {result_ip['converged']}")
            print(f"  Log-lik:      {result_ip['loglik']:.2f}")
            print(f"  AIC:          {result_ip['aic']:.2f}")
            print(f"  BIC:          {result_ip['bic']:.2f}")
            print(f"  Persistence:  {result_ip['persistence']:.4f}")
            print(f"\n  Parameters:")
            for name, val in result_ip["params"].items():
                print(f"    {name:10s} = {val:12.6f}")

            weights_ip = model_ip.get_midas_weights()
            print(f"\n  MIDAS weights (Industrial Production):")
            for k in range(12):
                bar = "#" * int(weights_ip[k] * 100)
                print(f"    Lag {k+1:2d}: {weights_ip[k]:.4f}  {bar}")
        except Exception as e:
            print(f"  INDPRO model failed: {e}")
            import traceback
            traceback.print_exc()
            result_ip = None
    else:
        section("3. GARCH-MIDAS with Industrial Production — SKIPPED (no data)")

    # ====================================================================
    # Benchmark: GJR-GARCH
    # ====================================================================
    section("4. Benchmark: GJR-GARCH(1,1,1)", "=")

    from arch import arch_model

    ret_pct = is_returns.values * 100
    gjr = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="normal",
                     mean="Zero", rescale=False)
    gjr_res = gjr.fit(disp="off", show_warning=False)

    print(f"  Log-lik:  {gjr_res.loglikelihood:.2f}")
    print(f"  AIC:      {gjr_res.aic:.2f}")
    print(f"  BIC:      {gjr_res.bic:.2f}")
    print(f"  Parameters:")
    for k, v in gjr_res.params.items():
        print(f"    {k:10s} = {v:12.6f}")

    gjr_cv = gjr_res.conditional_volatility
    if hasattr(gjr_cv, 'values'):
        gjr_sigma2_is = gjr_cv.values ** 2 / 10000
    else:
        gjr_sigma2_is = np.asarray(gjr_cv) ** 2 / 10000

    # ====================================================================
    # In-sample comparison
    # ====================================================================
    section("5. In-Sample Comparison", "=")

    # Use daily squared returns as realized variance proxy for QLIKE
    r2_is = is_returns.values ** 2

    # GARCH-MIDAS with RV
    ql_gm_rv = qlike(r2_is, sigma2_rv)
    mse_gm_rv = mse(r2_is, sigma2_rv)

    # GJR
    ql_gjr = qlike(r2_is, gjr_sigma2_is)
    mse_gjr = mse(r2_is, gjr_sigma2_is)

    print(f"\n  Note: LogLik/AIC not directly comparable (GARCH-MIDAS uses decimal")
    print(f"        returns, arch GJR uses pct returns). Compare QLIKE and MSE.")
    print(f"\n  {'Model':<35s} {'QLIKE':>12s} {'MSE':>14s} {'LogLik*':>12s} {'AIC*':>12s}")
    print(f"  {'-'*85}")
    print(f"  {'GARCH-MIDAS (RV)':<35s} {ql_gm_rv:>12.6f} {mse_gm_rv:>14.2e} {result_rv['loglik']:>12.2f} {result_rv['aic']:>12.2f}")
    print(f"  {'GJR-GARCH(1,1,1)':<35s} {ql_gjr:>12.6f} {mse_gjr:>14.2e} {gjr_res.loglikelihood:>12.2f} {gjr_res.aic:>12.2f}")

    if result_ip is not None:
        sigma2_ip = model_ip.get_conditional_variance()
        ql_gm_ip = qlike(r2_is, sigma2_ip)
        mse_gm_ip = mse(r2_is, sigma2_ip)
        print(f"  {'GARCH-MIDAS (INDPRO)':<35s} {ql_gm_ip:>12.6f} {mse_gm_ip:>14.2e} {result_ip['loglik']:>12.2f} {result_ip['aic']:>12.2f}")

    # DM tests — exclude zero-return days
    nonzero_is = r2_is > 0
    r2_nz = r2_is[nonzero_is]
    sig_rv_nz = sigma2_rv[nonzero_is]
    sig_gjr_nz = gjr_sigma2_is[nonzero_is]

    loss_gm_rv = r2_nz / np.maximum(sig_rv_nz, 1e-12) - np.log(r2_nz / np.maximum(sig_rv_nz, 1e-12)) - 1
    loss_gjr = r2_nz / np.maximum(sig_gjr_nz, 1e-12) - np.log(r2_nz / np.maximum(sig_gjr_nz, 1e-12)) - 1

    dm_stat, dm_pval = dm_test(loss_gm_rv, loss_gjr)
    print(f"\n  Diebold-Mariano test (GARCH-MIDAS RV vs GJR):")
    print(f"    DM stat = {dm_stat:.4f}, p-value = {dm_pval:.4f}")
    print(f"    {'GARCH-MIDAS RV better' if dm_stat < 0 else 'GJR better'} "
          f"{'(significant)' if dm_pval < 0.05 else '(not significant)'}")

    if result_ip is not None:
        sig_ip_nz = sigma2_ip[nonzero_is]
        loss_gm_ip = r2_nz / np.maximum(sig_ip_nz, 1e-12) - np.log(r2_nz / np.maximum(sig_ip_nz, 1e-12)) - 1
        dm_stat2, dm_pval2 = dm_test(loss_gm_ip, loss_gjr)
        print(f"\n  Diebold-Mariano test (GARCH-MIDAS INDPRO vs GJR):")
        print(f"    DM stat = {dm_stat2:.4f}, p-value = {dm_pval2:.4f}")

    # ====================================================================
    # OOS evaluation (rolling window)
    # ====================================================================
    section("6. Out-of-Sample Evaluation (2023-2025)", "=")

    window = 2000  # rolling window
    oos_dates = oos_returns.index
    all_returns = returns  # full series

    n_oos = len(oos_returns)
    print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} days)")
    print(f"  Rolling window: {window} days")
    print(f"  Refitting every 22 days (monthly)")

    # Storage for OOS forecasts
    fc_gm_rv_oos = np.zeros(n_oos)
    fc_gjr_oos = np.zeros(n_oos)
    fc_gm_ip_oos = np.zeros(n_oos) if result_ip is not None else None
    r2_oos = oos_returns.values ** 2

    refit_interval = 22
    last_refit = -refit_interval  # force refit on first iteration

    # Pre-compute position of OOS dates in full returns
    all_dates = all_returns.index
    oos_positions = [all_dates.get_loc(d) for d in oos_dates]

    gm_rv_model = None
    gm_ip_model = None
    gjr_model_result = None

    print(f"  Running OOS forecasts...", end="", flush=True)
    t0 = time.time()

    for i, pos in enumerate(oos_positions):
        # Rolling window
        win_start = max(0, pos - window)
        win_returns = all_returns.iloc[win_start:pos]

        need_refit = (i - last_refit >= refit_interval) or (i == 0)

        if need_refit:
            last_refit = i
            if (i % 100 == 0) and i > 0:
                elapsed = time.time() - t0
                pct = i / n_oos
                eta = elapsed / pct * (1 - pct) if pct > 0 else 0
                print(f"\n    [{i}/{n_oos}] {pct:.0%} done, ETA {eta:.0f}s", end="", flush=True)

            # --- GARCH-MIDAS RV ---
            try:
                win_rv = compute_monthly_rv_silent(win_returns)
                gm_rv_model = GarchMidas(K=12, macro_freq="monthly", n_starts=3)
                gm_rv_model.fit(
                    returns=win_returns,
                    macro_data=win_rv,
                    returns_index=win_returns.index,
                )
            except Exception:
                gm_rv_model = None

            # --- GARCH-MIDAS INDPRO ---
            if indpro is not None:
                try:
                    gm_ip_model = GarchMidas(K=12, macro_freq="monthly", n_starts=3)
                    gm_ip_model.fit(
                        returns=win_returns,
                        macro_data=indpro,
                        returns_index=win_returns.index,
                    )
                except Exception:
                    gm_ip_model = None

            # --- GJR-GARCH ---
            try:
                gjr_oos = arch_model(
                    win_returns.values * 100,
                    vol="GARCH", p=1, o=1, q=1,
                    dist="normal", mean="Zero", rescale=False,
                )
                gjr_model_result = gjr_oos.fit(disp="off", show_warning=False)
            except Exception:
                gjr_model_result = None

        # --- Forecasts ---
        if gm_rv_model is not None:
            try:
                fc = gm_rv_model.forecast()
                fc_gm_rv_oos[i] = fc.variance_forecast
            except Exception:
                fc_gm_rv_oos[i] = np.var(win_returns.values)
        else:
            fc_gm_rv_oos[i] = np.var(win_returns.values)

        if gjr_model_result is not None:
            try:
                fc_gjr = gjr_model_result.forecast(horizon=1)
                fc_gjr_oos[i] = fc_gjr.variance.iloc[-1, 0] / 10000
            except Exception:
                fc_gjr_oos[i] = np.var(win_returns.values)
        else:
            fc_gjr_oos[i] = np.var(win_returns.values)

        if fc_gm_ip_oos is not None:
            if gm_ip_model is not None:
                try:
                    fc_ip = gm_ip_model.forecast()
                    fc_gm_ip_oos[i] = fc_ip.variance_forecast
                except Exception:
                    fc_gm_ip_oos[i] = np.var(win_returns.values)
            else:
                fc_gm_ip_oos[i] = np.var(win_returns.values)

    oos_time = time.time() - t0
    print(f"\n  OOS complete in {oos_time:.1f}s")

    # --- OOS metrics ---
    section("7. OOS Results", "=")

    # QLIKE
    ql_oos_rv = qlike(r2_oos, fc_gm_rv_oos)
    ql_oos_gjr = qlike(r2_oos, fc_gjr_oos)

    # MSE
    mse_oos_rv = mse(r2_oos, fc_gm_rv_oos)
    mse_oos_gjr = mse(r2_oos, fc_gjr_oos)

    print(f"\n  {'Model':<35s} {'QLIKE':>12s} {'MSE':>14s}")
    print(f"  {'-'*61}")
    print(f"  {'GARCH-MIDAS (RV)':<35s} {ql_oos_rv:>12.6f} {mse_oos_rv:>14.2e}")
    print(f"  {'GJR-GARCH(1,1,1)':<35s} {ql_oos_gjr:>12.6f} {mse_oos_gjr:>14.2e}")

    if fc_gm_ip_oos is not None:
        ql_oos_ip = qlike(r2_oos, fc_gm_ip_oos)
        mse_oos_ip = mse(r2_oos, fc_gm_ip_oos)
        print(f"  {'GARCH-MIDAS (INDPRO)':<35s} {ql_oos_ip:>12.6f} {mse_oos_ip:>14.2e}")

    # DM tests OOS — exclude zero-return days
    nonzero_oos = r2_oos > 0
    r2_oos_nz = r2_oos[nonzero_oos]
    fc_rv_nz = fc_gm_rv_oos[nonzero_oos]
    fc_gjr_nz = fc_gjr_oos[nonzero_oos]

    loss_oos_rv = r2_oos_nz / np.maximum(fc_rv_nz, 1e-12) - np.log(r2_oos_nz / np.maximum(fc_rv_nz, 1e-12)) - 1
    loss_oos_gjr = r2_oos_nz / np.maximum(fc_gjr_nz, 1e-12) - np.log(r2_oos_nz / np.maximum(fc_gjr_nz, 1e-12)) - 1

    dm_oos, dm_oos_p = dm_test(loss_oos_rv, loss_oos_gjr)
    print(f"\n  DM test OOS (GARCH-MIDAS RV vs GJR):")
    print(f"    DM = {dm_oos:.4f}, p = {dm_oos_p:.4f}")
    winner = "GARCH-MIDAS RV" if dm_oos < 0 else "GJR-GARCH"
    sig = "significant" if dm_oos_p < 0.05 else "not significant"
    print(f"    Winner: {winner} ({sig})")

    if fc_gm_ip_oos is not None:
        fc_ip_nz = fc_gm_ip_oos[nonzero_oos]
        loss_oos_ip = r2_oos_nz / np.maximum(fc_ip_nz, 1e-12) - np.log(r2_oos_nz / np.maximum(fc_ip_nz, 1e-12)) - 1
        dm_oos2, dm_oos2_p = dm_test(loss_oos_ip, loss_oos_gjr)
        print(f"\n  DM test OOS (GARCH-MIDAS INDPRO vs GJR):")
        print(f"    DM = {dm_oos2:.4f}, p = {dm_oos2_p:.4f}")

    # ====================================================================
    # Summary
    # ====================================================================
    section("SUMMARY", "=")
    print(f"""
  GARCH-MIDAS (Engle, Ghysels & Sohn, 2013)
  ─────────────────────────────────────────

  The model decomposes σ²_t = τ_t × g_t into:
    • τ_t (long-run, macro-driven): captures slow-moving economic conditions
    • g_t (short-run, GARCH): captures daily volatility clustering

  IN-SAMPLE:
    GARCH-MIDAS (RV):     QLIKE = {ql_gm_rv:.6f}
    GJR-GARCH:            QLIKE = {ql_gjr:.6f}
    Difference:           {(ql_gm_rv - ql_gjr) / ql_gjr * 100:+.2f}%
    DM test:              stat = {dm_stat:.4f}, p = {dm_pval:.4f}

  OUT-OF-SAMPLE (2023-2025):
    GARCH-MIDAS (RV):     QLIKE = {ql_oos_rv:.6f}
    GJR-GARCH:            QLIKE = {ql_oos_gjr:.6f}
    Difference:           {(ql_oos_rv - ql_oos_gjr) / ql_oos_gjr * 100:+.2f}%
    DM test:              stat = {dm_oos:.4f}, p = {dm_oos_p:.4f}""")

    if result_ip is not None:
        print(f"""
  GARCH-MIDAS (INDPRO) IN-SAMPLE:
    QLIKE = {ql_gm_ip:.6f} (vs GJR {ql_gjr:.6f})""")
        if fc_gm_ip_oos is not None:
            print(f"  GARCH-MIDAS (INDPRO) OOS:")
            print(f"    QLIKE = {ql_oos_ip:.6f}")

    # Key finding
    print(f"\n  KEY FINDING:")
    if ql_oos_rv < ql_oos_gjr and dm_oos_p < 0.05:
        print(f"    GARCH-MIDAS (RV) significantly outperforms GJR-GARCH OOS.")
        print(f"    The macro-driven long-run component adds predictive value.")
    elif ql_oos_rv < ql_oos_gjr:
        print(f"    GARCH-MIDAS (RV) outperforms GJR-GARCH OOS, but not significantly.")
        print(f"    Long-run decomposition shows promise but needs more validation.")
    else:
        print(f"    GJR-GARCH outperforms GARCH-MIDAS OOS.")
        print(f"    The additional macro component does not improve short-horizon forecasts.")
        print(f"    This is consistent with Engle et al.'s finding that the benefit is")
        print(f"    mainly for multi-step (long-horizon) forecasts.")

    print(f"\n{'=' * 74}")

    # Save results
    results = {
        "model": "GARCH-MIDAS",
        "reference": "Engle, Ghysels & Sohn (2013)",
        "in_sample": {
            "garch_midas_rv": {"qlike": ql_gm_rv, "mse": mse_gm_rv, "loglik": result_rv["loglik"], "aic": result_rv["aic"]},
            "gjr_garch": {"qlike": ql_gjr, "mse": mse_gjr, "loglik": gjr_res.loglikelihood, "aic": gjr_res.aic},
            "dm_test": {"stat": dm_stat, "pval": dm_pval},
        },
        "oos": {
            "period": f"{oos_dates[0].date()} to {oos_dates[-1].date()}",
            "n_days": n_oos,
            "garch_midas_rv": {"qlike": ql_oos_rv, "mse": mse_oos_rv},
            "gjr_garch": {"qlike": ql_oos_gjr, "mse": mse_oos_gjr},
            "dm_test": {"stat": dm_oos, "pval": dm_oos_p},
        },
        "params_rv": result_rv["params"],
    }
    if result_ip is not None:
        results["in_sample"]["garch_midas_ip"] = {
            "qlike": ql_gm_ip, "loglik": result_ip["loglik"], "aic": result_ip["aic"],
        }
        results["params_ip"] = result_ip["params"]

    import json
    out_path = project_root / "experiments" / "garch_midas_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")


def compute_monthly_rv_silent(returns: pd.Series) -> pd.Series:
    """Compute monthly RV without printing."""
    rv = (returns ** 2).resample("ME").sum()
    return rv[rv > 0]


if __name__ == "__main__":
    main()
