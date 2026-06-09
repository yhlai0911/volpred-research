"""
K1435: GLD-DXY DCC-GARCH FOMC Event Study (2010-2026)

Hypothesis: FOMC announcement days exhibit elevated dynamic correlation
between GLD (gold) and DXY (US dollar) returns compared to non-FOMC days.

Method:
1. Download GLD + UUP (DXY proxy ETF) daily log returns 2010-2026.
2. Fit univariate GARCH(1,1) to each series; obtain standardized residuals.
3. Fit DCC(1,1) on the standardized residuals via custom MLE (scipy.minimize).
4. Compute dynamic correlation rho_t time series.
5. Two-sample t-test: rho on FOMC days vs other days.
6. Event window [-2, +2] robustness.
7. Hedge effectiveness: dynamic DCC vs naive 60/40, in-sample (2010-2019) and OOS (2020-2026).

Lookahead protection:
- DCC rho_t at time t uses t-1 conditional info (standard DCC convention).
- FOMC dates are public calendar (no leakage).
- Log returns are close-to-close.

Seed: 42
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy.optimize import minimize
from scipy.stats import ttest_ind

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

START = "2010-01-01"
END = "2026-06-09"


# -------------------------------------------------------------------------
# FOMC announcement dates (official Federal Reserve calendar 2010-2026)
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Listed dates are the LAST day of each scheduled meeting (announcement day).
# -------------------------------------------------------------------------
FOMC_DATES = [
    # 2010
    "2010-01-27", "2010-03-16", "2010-04-28", "2010-06-23",
    "2010-08-10", "2010-09-21", "2010-11-03", "2010-12-14",
    # 2011
    "2011-01-26", "2011-03-15", "2011-04-27", "2011-06-22",
    "2011-08-09", "2011-09-21", "2011-11-02", "2011-12-13",
    # 2012
    "2012-01-25", "2012-03-13", "2012-04-25", "2012-06-20",
    "2012-08-01", "2012-09-13", "2012-10-24", "2012-12-12",
    # 2013
    "2013-01-30", "2013-03-20", "2013-05-01", "2013-06-19",
    "2013-07-31", "2013-09-18", "2013-10-30", "2013-12-18",
    # 2014
    "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18",
    "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
    # 2015
    "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
    "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
    # 2016
    "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
    "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
    # 2017
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
    "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    # 2018
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
    "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020 (incl. emergency cuts 2020-03-03, 2020-03-15)
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29",
    "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 (projected through 2026-06-09)
    "2026-01-28", "2026-03-18", "2026-04-29",
]
FOMC_DATES = pd.to_datetime(FOMC_DATES)


# -------------------------------------------------------------------------
# Data
# -------------------------------------------------------------------------
def download_data() -> pd.DataFrame:
    print(f"[K1435] Downloading GLD + UUP {START} -> {END}")
    df = yf.download(
        ["GLD", "UUP"], start=START, end=END, auto_adjust=True, progress=False
    )
    # auto_adjust => Close is adjusted close
    close = df["Close"][["GLD", "UUP"]].dropna()
    print(f"[K1435] Raw close shape: {close.shape}")
    rets = np.log(close / close.shift(1)).dropna() * 100  # in pct for GARCH stability
    print(f"[K1435] Returns shape: {rets.shape}")
    print(f"[K1435] Period: {rets.index.min().date()} -> {rets.index.max().date()}")
    return rets


# -------------------------------------------------------------------------
# Univariate GARCH(1,1)
# -------------------------------------------------------------------------
def fit_garch(returns: pd.Series, name: str) -> tuple[pd.Series, dict]:
    am = arch_model(returns, mean="Constant", vol="Garch", p=1, q=1, dist="normal")
    res = am.fit(disp="off", show_warning=False)
    params = {
        "mu": float(res.params["mu"]),
        "omega": float(res.params["omega"]),
        "alpha": float(res.params["alpha[1]"]),
        "beta": float(res.params["beta[1]"]),
        "loglik": float(res.loglikelihood),
    }
    cond_vol = res.conditional_volatility
    std_resid = (returns - res.params["mu"]) / cond_vol
    print(f"[K1435] GARCH {name}: alpha={params['alpha']:.4f} beta={params['beta']:.4f} persist={params['alpha']+params['beta']:.4f}")
    return std_resid, params


# -------------------------------------------------------------------------
# DCC(1,1) custom MLE on standardized residuals
# -------------------------------------------------------------------------
def dcc_loglik(params: np.ndarray, z: np.ndarray) -> float:
    """Negative log-likelihood of DCC(1,1) on bivariate standardized residuals z.

    z: T x 2 standardized residuals (mean 0, var ~1)
    """
    a, b = params
    if a < 0 or b < 0 or a + b >= 0.999:
        return 1e10
    T = z.shape[0]
    Q_bar = np.cov(z.T)
    # Normalize Q_bar to correlation matrix scale (it should already be ~corr since z std)
    Q = Q_bar.copy()
    nll = 0.0
    for t in range(T):
        # diag normalize Q -> R_t
        d = np.sqrt(np.diag(Q))
        R = Q / np.outer(d, d)
        rho = R[0, 1]
        # Bivariate gaussian log-density component from correlation only
        det = 1 - rho * rho
        if det <= 0:
            return 1e10
        q_form = (z[t, 0] ** 2 + z[t, 1] ** 2 - 2 * rho * z[t, 0] * z[t, 1]) / det
        nll += 0.5 * (np.log(det) + q_form - z[t, 0] ** 2 - z[t, 1] ** 2)
        # update Q for next period
        zz = np.outer(z[t], z[t])
        Q = (1 - a - b) * Q_bar + a * zz + b * Q
    return nll


def fit_dcc(z: np.ndarray) -> tuple[dict, np.ndarray]:
    print("[K1435] Fitting DCC(1,1) via scipy.minimize ...")
    # multistart with seed
    rng = np.random.default_rng(SEED)
    best = None
    for trial in range(8):
        a0 = rng.uniform(0.01, 0.10)
        b0 = rng.uniform(0.80, 0.95)
        if a0 + b0 >= 0.99:
            b0 = 0.95 - a0
        try:
            r = minimize(
                dcc_loglik,
                x0=np.array([a0, b0]),
                args=(z,),
                method="L-BFGS-B",
                bounds=[(1e-6, 0.3), (0.5, 0.999)],
                options={"maxiter": 200, "ftol": 1e-7},
            )
            if r.success and (best is None or r.fun < best.fun):
                best = r
        except Exception as e:
            print(f"[K1435] DCC trial {trial} failed: {e}")
    if best is None:
        raise RuntimeError("DCC MLE all trials failed")
    a, b = best.x
    print(f"[K1435] DCC params: a={a:.4f} b={b:.4f} loglik={-best.fun:.2f}")

    # recompute rho_t series at optimum
    T = z.shape[0]
    Q_bar = np.cov(z.T)
    Q = Q_bar.copy()
    rho_series = np.zeros(T)
    for t in range(T):
        d = np.sqrt(np.diag(Q))
        R = Q / np.outer(d, d)
        rho_series[t] = R[0, 1]
        zz = np.outer(z[t], z[t])
        Q = (1 - a - b) * Q_bar + a * zz + b * Q

    dcc_params = {
        "a": float(a),
        "b": float(b),
        "persistence": float(a + b),
        "loglik": float(-best.fun),
        "q_bar_offdiag": float(Q_bar[0, 1]),
    }
    return dcc_params, rho_series


# -------------------------------------------------------------------------
# FOMC event test
# -------------------------------------------------------------------------
def fomc_test(rho: pd.Series) -> dict:
    fomc_in_sample = [d for d in FOMC_DATES if d in rho.index]
    fomc_mask = rho.index.isin(fomc_in_sample)
    rho_fomc = rho[fomc_mask].values
    rho_other = rho[~fomc_mask].values
    t_stat, p_val = ttest_ind(rho_fomc, rho_other, equal_var=False)
    return {
        "n_fomc_days": int(fomc_mask.sum()),
        "n_other_days": int((~fomc_mask).sum()),
        "n_fomc_calendar_dates": len(FOMC_DATES),
        "n_fomc_matched_trading_days": len(fomc_in_sample),
        "rho_fomc_mean": float(np.mean(rho_fomc)),
        "rho_fomc_std": float(np.std(rho_fomc)),
        "rho_other_mean": float(np.mean(rho_other)),
        "rho_other_std": float(np.std(rho_other)),
        "rho_diff": float(np.mean(rho_fomc) - np.mean(rho_other)),
        "t_stat": float(t_stat),
        "p_value": float(p_val),
    }


def event_window_test(rho: pd.Series, window: int = 2) -> dict:
    """Test [-window, +window] around FOMC days vs other."""
    idx_list = rho.index
    event_idx = set()
    for d in FOMC_DATES:
        if d in idx_list:
            pos = idx_list.get_loc(d)
            lo = max(0, pos - window)
            hi = min(len(idx_list) - 1, pos + window)
            for p in range(lo, hi + 1):
                event_idx.add(idx_list[p])
    event_mask = rho.index.isin(event_idx)
    rho_event = rho[event_mask].values
    rho_other = rho[~event_mask].values
    t_stat, p_val = ttest_ind(rho_event, rho_other, equal_var=False)
    return {
        "window_days": window,
        "n_event_days": int(event_mask.sum()),
        "n_other_days": int((~event_mask).sum()),
        "rho_event_mean": float(np.mean(rho_event)),
        "rho_other_mean": float(np.mean(rho_other)),
        "rho_diff": float(np.mean(rho_event) - np.mean(rho_other)),
        "t_stat": float(t_stat),
        "p_value": float(p_val),
    }


# -------------------------------------------------------------------------
# Hedge effectiveness
# Hedge GLD with UUP. Position: long 1 GLD, short h_t UUP.
# Naive: h = cov_const/var_uup_const (full-sample OLS) or simple 60/40 portfolio var.
# Use HE = 1 - Var(hedged)/Var(unhedged_GLD).
# -------------------------------------------------------------------------
def hedge_effectiveness(
    rets: pd.DataFrame,
    rho_series: pd.Series,
    sigma_gld: pd.Series,
    sigma_uup: pd.Series,
    in_sample_end: str = "2019-12-31",
) -> dict:
    common = rets.index.intersection(rho_series.index)
    rets = rets.loc[common]
    rho = rho_series.loc[common]
    sg = sigma_gld.loc[common]
    su = sigma_uup.loc[common]

    # Dynamic optimal hedge ratio h_t = rho_t * sigma_gld_t / sigma_uup_t
    h_dyn = rho * sg / su
    # Apply at t with t-1 conditional info => shift(1) for OOS realism
    h_dyn_lag = h_dyn.shift(1)

    # Naive: constant OLS on in-sample
    in_mask = rets.index <= pd.Timestamp(in_sample_end)
    cov_in = np.cov(rets["GLD"][in_mask], rets["UUP"][in_mask])
    h_naive = cov_in[0, 1] / cov_in[1, 1]  # scalar

    hedged_dyn = rets["GLD"] - h_dyn_lag * rets["UUP"]
    hedged_naive = rets["GLD"] - h_naive * rets["UUP"]

    def he(unhedged: pd.Series, hedged: pd.Series, mask: pd.Series) -> float:
        u = unhedged[mask].dropna()
        h = hedged[mask].dropna()
        common_idx = u.index.intersection(h.index)
        return float(1 - h.loc[common_idx].var() / u.loc[common_idx].var())

    oos_mask = rets.index > pd.Timestamp(in_sample_end)
    is_mask = rets.index <= pd.Timestamp(in_sample_end)

    return {
        "h_naive_constant": float(h_naive),
        "h_dyn_mean": float(h_dyn.mean()),
        "h_dyn_std": float(h_dyn.std()),
        "in_sample": {
            "period": f"{START} to {in_sample_end}",
            "he_dcc": he(rets["GLD"], hedged_dyn, is_mask),
            "he_naive": he(rets["GLD"], hedged_naive, is_mask),
        },
        "oos": {
            "period": f"{in_sample_end} to {END}",
            "he_dcc": he(rets["GLD"], hedged_dyn, oos_mask),
            "he_naive": he(rets["GLD"], hedged_naive, oos_mask),
        },
    }


# -------------------------------------------------------------------------
# Verdict
# -------------------------------------------------------------------------
def determine_verdict(fomc: dict, ev: dict, hedge: dict) -> tuple[str, str]:
    p = fomc["p_value"]
    diff = fomc["rho_diff"]
    he_imp = hedge["oos"]["he_dcc"] - hedge["oos"]["he_naive"]

    if p < 0.05 and diff > 0:
        verdict = "PASS"
        reason = (
            f"FOMC days exhibit significantly elevated DCC correlation "
            f"(diff={diff:+.4f}, p={p:.4f}). "
        )
    elif p < 0.05 and diff < 0:
        verdict = "PASS_REVERSE"
        reason = (
            f"FOMC days exhibit significantly LOWER DCC correlation "
            f"(diff={diff:+.4f}, p={p:.4f}) — opposite of hypothesis. "
        )
    elif p < 0.10:
        verdict = "MARGINAL"
        reason = (
            f"Weak evidence of FOMC effect (diff={diff:+.4f}, p={p:.4f}, "
            f"marginal at 10%). "
        )
    else:
        verdict = "NULL"
        reason = (
            f"No significant FOMC effect on DCC correlation "
            f"(diff={diff:+.4f}, p={p:.4f}). "
        )
    reason += f"OOS hedge improvement DCC vs naive: {he_imp:+.4f}."
    return verdict, reason


# -------------------------------------------------------------------------
# Plots
# -------------------------------------------------------------------------
def make_plots(rho: pd.Series, hedge: dict, fomc_in_sample: list) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(rho.index, rho.values, lw=0.7, color="navy", label="DCC rho_t")
    for d in fomc_in_sample:
        ax.axvline(d, color="red", alpha=0.12, lw=0.5)
    ax.axhline(0, color="grey", lw=0.5, ls="--")
    ax.set_title("K1435: GLD-UUP DCC Dynamic Correlation with FOMC days (red)")
    ax.set_xlabel("Date")
    ax.set_ylabel("rho_t")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "rho_fomc_timeseries.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 5))
    cats = ["In-sample", "Out-of-sample"]
    naive_vals = [hedge["in_sample"]["he_naive"], hedge["oos"]["he_naive"]]
    dcc_vals = [hedge["in_sample"]["he_dcc"], hedge["oos"]["he_dcc"]]
    x = np.arange(len(cats))
    w = 0.35
    ax.bar(x - w / 2, naive_vals, w, label="Naive OLS", color="grey")
    ax.bar(x + w / 2, dcc_vals, w, label="DCC dynamic", color="steelblue")
    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    ax.set_ylabel("Hedge Effectiveness (1 - Var(h)/Var(unh))")
    ax.set_title("K1435: Hedge Effectiveness DCC vs Naive")
    ax.legend()
    ax.axhline(0, color="black", lw=0.5)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "hedge_effectiveness.png", dpi=120)
    plt.close(fig)


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def main() -> dict:
    rets = download_data()
    n_obs = len(rets)

    z_gld, gp_gld = fit_garch(rets["GLD"], "GLD")
    z_uup, gp_uup = fit_garch(rets["UUP"], "UUP")

    # GARCH conditional vols for hedge calc
    am_gld = arch_model(rets["GLD"], mean="Constant", vol="Garch", p=1, q=1).fit(disp="off")
    am_uup = arch_model(rets["UUP"], mean="Constant", vol="Garch", p=1, q=1).fit(disp="off")
    sigma_gld = am_gld.conditional_volatility
    sigma_uup = am_uup.conditional_volatility

    z = np.column_stack([z_gld.values, z_uup.values])
    dcc_params, rho_arr = fit_dcc(z)
    rho_series = pd.Series(rho_arr, index=rets.index, name="rho_t")

    fomc = fomc_test(rho_series)
    ev = event_window_test(rho_series, window=2)
    hedge = hedge_effectiveness(rets, rho_series, sigma_gld, sigma_uup)

    fomc_in_sample = [d for d in FOMC_DATES if d in rho_series.index]
    make_plots(rho_series, hedge, fomc_in_sample)

    verdict, reason = determine_verdict(fomc, ev, hedge)

    results = {
        "experiment_id": "K1435",
        "hypothesis": (
            "FOMC announcement days exhibit elevated DCC dynamic correlation "
            "between GLD (gold ETF) and UUP (USD index ETF) returns vs other days."
        ),
        "data": {
            "source": "yfinance",
            "tickers": ["GLD", "UUP"],
            "start": str(rets.index.min().date()),
            "end": str(rets.index.max().date()),
            "n_obs": int(n_obs),
            "returns_scale": "log returns x 100 (pct)",
        },
        "garch_params": {"GLD": gp_gld, "UUP": gp_uup},
        "dcc_params": dcc_params,
        "rho_summary": {
            "mean": float(rho_series.mean()),
            "std": float(rho_series.std()),
            "min": float(rho_series.min()),
            "max": float(rho_series.max()),
        },
        "fomc_test": fomc,
        "event_window_pm2": ev,
        "hedge_effectiveness": hedge,
        "verdict": verdict,
        "verdict_reason": reason,
        "lookahead_check": (
            "FOMC dates from public Fed calendar (no leakage). "
            "DCC rho_t at time t uses t-1 conditional Q (standard DCC). "
            "Hedge ratio h_t shifted by 1 day (signal.shift(1)) for OOS realism. "
            "Log returns are close-to-close."
        ),
        "seed": SEED,
        "reviewer_source": "pending_codex_review",
    }

    out_path = OUT_DIR / "k1435_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\n[K1435] VERDICT: {verdict}")
    print(f"[K1435] {reason}")
    print(f"[K1435] Results -> {out_path}")
    return results


if __name__ == "__main__":
    main()
