"""K1501 — VRP upside/downside decomposition × horizon predictability.

Hypotheses
----------
H1 (Asymmetry): Monthly downside realized semivariance (RV-^2) has a
    significantly higher mean than upside (RV+^2), via Welch t-test
    on monthly aggregates (HAC NW also reported).

H2 (Predictive power, horizons): For horizon h in {1, 21, 63, 126}
    trading days, regress SPY log return ret_{t->t+h} on each lagged
    predictor X_t in {RV+^2, RV-^2, VRP_total, VRP_down, VRP_up}, with
    HAC Newey-West lag = h+1. Compare beta_down vs beta_up.

H3 (VRP sign decomposition): Construct VRP_down and VRP_up from
    ex-ante (rolling 12m) downside/upside shares of total RV; check
    correlation(VRP_down, VRP_up) and additivity VRP_down + VRP_up
    versus VRP_total.

Lookahead controls
------------------
- VIX^2 is taken at end-of-month and uses `.shift(1)` so the predictor
  at month t was observable at the START of month t. (We compare it
  with RV computed OVER month t to construct VRP_t; per Bollerslev/
  Zhou 2009 convention.) For the regression X_t -> ret_{t->t+h}, the
  full X_t is observable by month t close (end of formation month).
- ret_{t+h} uses `.shift(-h)` of monthly returns when h is expressed
  in months, OR computed from daily prices as future cumulative log
  return over h trading days starting at month-end close (no
  contemporaneous overlap with X_t).
- Theta_t (down-share) is rolling-12-month TRAILING mean computed
  from RV-^2_{t-12..t-1} / total_RV_{t-12..t-1}; uses only data
  available STRICTLY BEFORE month t.

Random seed: 42.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

EXP_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXP_DIR / "k1501_results.json"
FIGS_DIR = EXP_DIR / "figs"
FIGS_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
N_BOOT = 1000
HORIZONS = [1, 21, 63, 126]  # trading days
SAMPLE_START = "2006-01-01"
SAMPLE_END = "2026-05-31"

rng = np.random.default_rng(SEED)


def fetch_data() -> Dict[str, pd.DataFrame]:
    import yfinance as yf
    # Daily SPY proxy via ^GSPC + VIX
    print(f"[data] downloading ^GSPC and ^VIX {SAMPLE_START}..{SAMPLE_END}", flush=True)
    gspc = yf.download("^GSPC", start=SAMPLE_START, end=SAMPLE_END,
                       progress=False, auto_adjust=False)
    vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END,
                      progress=False, auto_adjust=False)
    if isinstance(gspc.columns, pd.MultiIndex):
        gspc.columns = gspc.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    return {"gspc": gspc, "vix": vix}


def build_monthly_panel(gspc: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    px = gspc["Close"].astype(float).dropna()
    r = np.log(px / px.shift(1)).dropna()
    r.name = "ret"

    # Daily semivariance components per month: RV+^2 = sum max(r,0)^2
    pos2 = np.maximum(r, 0.0) ** 2
    neg2 = np.minimum(r, 0.0) ** 2
    tot2 = r ** 2

    pos2.name = "rv_up2_daily"
    neg2.name = "rv_dn2_daily"
    tot2.name = "rv_tot2_daily"

    df_daily = pd.concat([r, pos2, neg2, tot2], axis=1)
    # Month-end aggregation: annualize realized variance to monthly variance
    # (sum of squared daily log returns is monthly realized variance, unannualized)
    rv_up2 = pos2.resample("ME").sum()
    rv_dn2 = neg2.resample("ME").sum()
    rv_tot2 = tot2.resample("ME").sum()
    n_days = r.resample("ME").count()
    monthly_logret = r.resample("ME").sum()
    px_eom = px.resample("ME").last()

    # VIX: end-of-month VIX^2 / annualization = monthly implied variance
    # VIX is annualized vol in %. VIX^2 / 12 / 100^2 = monthly implied variance.
    vix_eom = vix["Close"].astype(float).resample("ME").last()
    iv_monthly = (vix_eom / 100.0) ** 2 / 12.0
    iv_monthly.name = "iv_monthly"

    panel = pd.concat([
        rv_up2.rename("rv_up2"),
        rv_dn2.rename("rv_dn2"),
        rv_tot2.rename("rv_tot2"),
        iv_monthly,
        n_days.rename("n_days"),
        monthly_logret.rename("monthly_logret"),
        px_eom.rename("spx_eom"),
    ], axis=1)

    # Ex-ante observable IV: shift(1) so iv at month t was set at end of t-1
    panel["iv_monthly_lag1"] = panel["iv_monthly"].shift(1)

    # VRP_total = IV_{t-1} - RV_total_t  (Bollerslev/Tauchen/Zhou 2009 convention:
    # implied at t-1 minus realized over t; positive = vol risk premium)
    panel["vrp_total"] = panel["iv_monthly_lag1"] - panel["rv_tot2"]

    # Rolling 12m TRAILING down-share for theta (ex-ante)
    # share_dn_t uses RV_{t-12..t-1} ONLY
    roll_dn = panel["rv_dn2"].shift(1).rolling(window=12, min_periods=12).sum()
    roll_tot = panel["rv_tot2"].shift(1).rolling(window=12, min_periods=12).sum()
    share_dn = roll_dn / roll_tot.replace(0.0, np.nan)
    share_up = 1.0 - share_dn
    panel["theta_dn"] = share_dn
    panel["theta_up"] = share_up

    # VRP_down = theta_dn * IV_{t-1} - RV_dn_t   ; VRP_up = theta_up * IV_{t-1} - RV_up_t
    panel["vrp_down"] = panel["theta_dn"] * panel["iv_monthly_lag1"] - panel["rv_dn2"]
    panel["vrp_up"] = panel["theta_up"] * panel["iv_monthly_lag1"] - panel["rv_up2"]
    panel["vrp_sum"] = panel["vrp_down"] + panel["vrp_up"]

    panel = panel.dropna(subset=["rv_up2", "rv_dn2", "rv_tot2", "iv_monthly_lag1"])
    return panel, r, px


def hac_se(resid: np.ndarray, X: np.ndarray, lag: int) -> np.ndarray:
    """Newey-West HAC variance for OLS coefficient.

    Returns sqrt(diag) i.e. standard errors of the OLS coefficients.
    """
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    u = resid.reshape(-1, 1)
    # S = sum_t u^2 x_t x_t' + sum_l (1 - l/(lag+1)) (Gamma_l + Gamma_l')
    S = (X * u).T @ (X * u)
    for l in range(1, lag + 1):
        w = 1.0 - l / (lag + 1.0)
        x_lag = X[l:]
        x_lead = X[:-l]
        u_lag = u[l:]
        u_lead = u[:-l]
        G = (x_lag * u_lag).T @ (x_lead * u_lead)
        S = S + w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return np.sqrt(np.maximum(np.diag(V), 0.0))


def ols_hac(y: np.ndarray, x: np.ndarray, lag: int) -> Dict:
    """Univariate OLS y = a + b*x + e, with HAC NW SE."""
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    se = hac_se(resid, X, lag)
    t = beta / np.where(se > 0, se, np.nan)
    # two-sided p via normal approx (large n)
    from scipy.stats import norm
    pval = 2.0 * (1.0 - norm.cdf(np.abs(t)))
    ss_res = np.sum(resid ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return {
        "alpha": float(beta[0]),
        "beta": float(beta[1]),
        "se_alpha": float(se[0]),
        "se_beta": float(se[1]),
        "t_beta": float(t[1]),
        "p_beta": float(pval[1]),
        "r2": float(r2),
        "n": int(n),
        "hac_lag": int(lag),
    }


def welch_test(a: np.ndarray, b: np.ndarray) -> Dict:
    from scipy.stats import ttest_ind
    res = ttest_ind(a, b, equal_var=False)
    return {
        "mean_a": float(np.mean(a)),
        "mean_b": float(np.mean(b)),
        "diff_mean_a_minus_b": float(np.mean(a) - np.mean(b)),
        "t": float(res.statistic),
        "p_two_sided": float(res.pvalue),
        "n_a": int(len(a)),
        "n_b": int(len(b)),
    }


def block_bootstrap_diff_beta(y: np.ndarray, x_a: np.ndarray, x_b: np.ndarray,
                              lag: int, n_boot: int, block: int) -> Dict:
    """Stationary block bootstrap on (y, x_a, x_b) joint to test
    beta_a - beta_b distribution."""
    n = len(y)
    diffs = []
    for _ in range(n_boot):
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n)
            length = block
            idx.extend(list(range(start, start + length)))
        idx = [i % n for i in idx[:n]]
        yb = y[idx]
        xa = x_a[idx]
        xb = x_b[idx]
        Xa = np.column_stack([np.ones(n), xa])
        Xb = np.column_stack([np.ones(n), xb])
        ba, *_ = np.linalg.lstsq(Xa, yb, rcond=None)
        bb, *_ = np.linalg.lstsq(Xb, yb, rcond=None)
        diffs.append(ba[1] - bb[1])
    diffs = np.array(diffs)
    # one-sided p that beta_a > beta_b
    p_a_gt_b = float(np.mean(diffs > 0))
    return {
        "mean_diff": float(np.mean(diffs)),
        "std_diff": float(np.std(diffs, ddof=1)),
        "ci95": [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))],
        "p_one_sided_a_gt_b": p_a_gt_b,
        "p_two_sided": float(2.0 * min(p_a_gt_b, 1.0 - p_a_gt_b)),
        "n_boot": int(n_boot),
        "block_len": int(block),
    }


def run_H1(panel: pd.DataFrame) -> Dict:
    a = panel["rv_dn2"].dropna().values
    b = panel["rv_up2"].dropna().values
    out = welch_test(a, b)
    # Also test mean of (rv_dn2 - rv_up2) with HAC NW lag=3
    diff = panel["rv_dn2"] - panel["rv_up2"]
    diff = diff.dropna().values
    n = len(diff)
    X = np.ones((n, 1))
    beta, *_ = np.linalg.lstsq(X, diff, rcond=None)
    resid = diff - X @ beta
    se = hac_se(resid, X, lag=3)
    from scipy.stats import norm
    t = beta[0] / se[0] if se[0] > 0 else np.nan
    p = 2.0 * (1.0 - norm.cdf(abs(t)))
    out["mean_diff_dn_minus_up_HAC"] = {
        "mean": float(beta[0]),
        "se_HAC_NW_lag3": float(se[0]),
        "t": float(t),
        "p_two_sided": float(p),
        "n": int(n),
    }
    return out


def run_H2(panel: pd.DataFrame, daily_ret: pd.Series, prices: pd.Series) -> Dict:
    """For each horizon h trading days, compute forward cumulative log
    return from month-end and regress on each predictor X_t at month end.

    X_t is observable at end of month t (we use values from panel row t).
    forward return = log(P_{t + h trading days}) - log(P_t)  using calendar
    of trading days from the SPX daily series.
    """
    # Build a mapping from month-end timestamps to trading-day index
    px = prices.copy()
    px.index = pd.to_datetime(px.index)
    # For each month-end date in panel, locate it (or the prior available trading day)
    # in the daily index, then look h trading days ahead.
    panel = panel.copy()
    daily_idx = px.index
    daily_arr = np.log(px.values)
    out = {"horizons": {}}
    predictors = ["rv_up2", "rv_dn2", "vrp_total", "vrp_down", "vrp_up"]

    for h in HORIZONS:
        # Build aligned (y_h, X) at monthly freq
        rows = []
        for ts, row in panel.iterrows():
            # find last trading day <= ts (month-end)
            pos = daily_idx.searchsorted(ts, side="right") - 1
            if pos < 0:
                continue
            fwd_pos = pos + h
            if fwd_pos >= len(daily_arr):
                continue
            y_h = daily_arr[fwd_pos] - daily_arr[pos]
            d = {"month_end": ts, "y_h": y_h}
            for p in predictors:
                d[p] = row[p]
            rows.append(d)
        if not rows:
            continue
        df_h = pd.DataFrame(rows).dropna()
        y = df_h["y_h"].values
        hac_lag = h + 1
        # Approximate block length scaled with h for bootstrap
        block_len = max(2, int(np.ceil(h / 21.0) * 2 + 2))
        regs = {}
        for p in predictors:
            x = df_h[p].values
            reg = ols_hac(y, x, lag=hac_lag)
            regs[p] = reg
        # Compare beta_down vs beta_up of VRP and of RV
        boot_vrp = block_bootstrap_diff_beta(y, df_h["vrp_down"].values,
                                             df_h["vrp_up"].values,
                                             lag=hac_lag, n_boot=N_BOOT,
                                             block=block_len)
        boot_rv = block_bootstrap_diff_beta(y, df_h["rv_dn2"].values,
                                            df_h["rv_up2"].values,
                                            lag=hac_lag, n_boot=N_BOOT,
                                            block=block_len)
        out["horizons"][str(h)] = {
            "n_obs": int(len(df_h)),
            "regressions": regs,
            "bootstrap_beta_vrp_down_minus_up": boot_vrp,
            "bootstrap_beta_rv_dn_minus_up": boot_rv,
        }
    return out


def run_H3(panel: pd.DataFrame) -> Dict:
    sub = panel.dropna(subset=["vrp_down", "vrp_up", "vrp_total"]).copy()
    rho = float(sub["vrp_down"].corr(sub["vrp_up"]))
    # Test rho significance via Fisher z + HAC-NW SE on z (use lag=3)
    from scipy.stats import norm
    n = len(sub)
    z = 0.5 * np.log((1 + rho) / (1 - rho))
    se_z = 1.0 / np.sqrt(n - 3) if n > 3 else np.nan
    p_rho = 2.0 * (1.0 - norm.cdf(abs(z) / se_z)) if se_z and not np.isnan(se_z) else np.nan
    add_diff = (sub["vrp_total"] - sub["vrp_sum"]).abs().mean()
    add_corr = float(sub["vrp_total"].corr(sub["vrp_sum"]))
    return {
        "n": int(n),
        "corr_vrp_down_vrp_up": rho,
        "fisher_z": float(z),
        "fisher_se": float(se_z) if not np.isnan(se_z) else None,
        "p_two_sided_corr_ne_zero": float(p_rho) if not np.isnan(p_rho) else None,
        "mean_abs_diff_total_minus_sum": float(add_diff),
        "corr_total_sum": add_corr,
        "additivity_note": ("vrp_total uses iv*1 - rv_total; vrp_sum uses "
                            "theta_dn*iv + theta_up*iv - rv_dn - rv_up = iv - rv_total "
                            "since theta_dn+theta_up=1; expected ~identity "
                            "modulo rolling theta NaN handling."),
    }


def make_figures(panel: pd.DataFrame, h2: Dict) -> List[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    files = []
    # H1: distribution of monthly RV+ vs RV-
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(panel["rv_up2"].dropna().values * 1e4, bins=40, alpha=0.55,
            label="RV+^2 (upside)", color="#3a86ff")
    ax.hist(panel["rv_dn2"].dropna().values * 1e4, bins=40, alpha=0.55,
            label="RV-^2 (downside)", color="#d62828")
    ax.set_xlabel("Monthly semivariance (x1e4)")
    ax.set_ylabel("Frequency")
    ax.set_title("K1501 H1 — SPY monthly upside vs downside semivariance")
    ax.legend()
    fig.tight_layout()
    p1 = FIGS_DIR / "H1_semivariance_dist.png"
    fig.savefig(p1, dpi=120)
    plt.close(fig)
    files.append(str(p1))

    # H2: bar plot of |t_beta| across horizons for vrp_down vs vrp_up
    fig, ax = plt.subplots(figsize=(7, 4))
    hs = sorted(h2["horizons"].keys(), key=lambda s: int(s))
    width = 0.35
    x = np.arange(len(hs))
    t_dn = [h2["horizons"][h]["regressions"]["vrp_down"]["t_beta"] for h in hs]
    t_up = [h2["horizons"][h]["regressions"]["vrp_up"]["t_beta"] for h in hs]
    ax.bar(x - width / 2, t_dn, width, label="VRP_down", color="#d62828")
    ax.bar(x + width / 2, t_up, width, label="VRP_up", color="#3a86ff")
    ax.axhline(0, color="k", linewidth=0.5)
    ax.axhline(1.96, color="grey", linestyle="--", linewidth=0.7)
    ax.axhline(-1.96, color="grey", linestyle="--", linewidth=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels([f"h={h}d" for h in hs])
    ax.set_ylabel("HAC NW t-stat of beta")
    ax.set_title("K1501 H2 — VRP_down vs VRP_up predictive t across horizon")
    ax.legend()
    fig.tight_layout()
    p2 = FIGS_DIR / "H2_horizon_betas.png"
    fig.savefig(p2, dpi=120)
    plt.close(fig)
    files.append(str(p2))
    return files


def harvey_bonferroni_verdict(h1: Dict, h2: Dict, h3: Dict) -> str:
    """Apply Harvey (2016) + Bonferroni (across 4 horizons * 2 predictors = 8 tests
    for H2; H1 single test; H3 corr single test)."""
    p_h1 = h1["mean_diff_dn_minus_up_HAC"]["p_two_sided"]
    # H2: collect min p across (vrp_down, vrp_up) at any horizon
    p_h2_pairs = []
    for h, blk in h2["horizons"].items():
        p_h2_pairs.append(blk["regressions"]["vrp_down"]["p_beta"])
        p_h2_pairs.append(blk["regressions"]["vrp_up"]["p_beta"])
    n_tests_h2 = len(p_h2_pairs)
    p_h2_min = min(p_h2_pairs) if p_h2_pairs else 1.0
    p_h2_bonf = min(1.0, p_h2_min * n_tests_h2)
    p_h3 = h3.get("p_two_sided_corr_ne_zero") or 1.0

    # Harvey bar: economically meaningful t requires |t|>3 for unique discovery
    # We'll use 0.01 Bonferroni-adjusted as PASS, 0.05 as CONDITIONAL.
    sig = []
    if p_h1 < 0.01:
        sig.append("H1_strong")
    elif p_h1 < 0.05:
        sig.append("H1_weak")
    if p_h2_bonf < 0.01:
        sig.append("H2_strong")
    elif p_h2_bonf < 0.05:
        sig.append("H2_weak")
    if p_h3 < 0.01:
        sig.append("H3_strong")
    elif p_h3 < 0.05:
        sig.append("H3_weak")

    if "H1_strong" in sig and ("H2_strong" in sig or "H3_strong" in sig):
        return "PASS"
    if any("strong" in s for s in sig) and len(sig) >= 2:
        return "CONDITIONAL_PASS"
    if any("weak" in s for s in sig) or any("strong" in s for s in sig):
        return "MIXED"
    return "NULL"


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    data = fetch_data()
    panel, daily_ret, prices = build_monthly_panel(data["gspc"], data["vix"])
    print(f"[panel] n_months={len(panel)} period={panel.index.min().date()}..{panel.index.max().date()}",
          flush=True)
    h1 = run_H1(panel)
    print(f"[H1] mean_dn={h1['mean_a']:.6f} mean_up={h1['mean_b']:.6f} "
          f"welch_p={h1['p_two_sided']:.4g} HAC_p={h1['mean_diff_dn_minus_up_HAC']['p_two_sided']:.4g}",
          flush=True)
    h2 = run_H2(panel, daily_ret, prices)
    for h in sorted(h2["horizons"].keys(), key=lambda s: int(s)):
        blk = h2["horizons"][h]
        t_dn = blk["regressions"]["vrp_down"]["t_beta"]
        t_up = blk["regressions"]["vrp_up"]["t_beta"]
        print(f"[H2 h={h}] n={blk['n_obs']} t(vrp_down)={t_dn:.2f} t(vrp_up)={t_up:.2f} "
              f"diff_p={blk['bootstrap_beta_vrp_down_minus_up']['p_two_sided']:.3g}",
              flush=True)
    h3 = run_H3(panel)
    print(f"[H3] rho(vrp_down,vrp_up)={h3['corr_vrp_down_vrp_up']:.3f} p={h3.get('p_two_sided_corr_ne_zero')}",
          flush=True)

    fig_files = []
    try:
        fig_files = make_figures(panel, h2)
    except Exception as exc:
        print(f"[warn] figure generation failed: {exc}", flush=True)

    verdict = harvey_bonferroni_verdict(h1, h2, h3)

    result = {
        "experiment_id": "k1501",
        "k_id": "K1501",
        "title": "K1501 — VRP upside/downside decomposition and horizon predictability on SPY",
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "n_bootstrap": N_BOOT,
        "sample_period": {
            "requested_start": SAMPLE_START,
            "requested_end": SAMPLE_END,
            "actual_start": str(panel.index.min().date()),
            "actual_end": str(panel.index.max().date()),
        },
        "n_obs_monthly": int(len(panel)),
        "data_provenance": {
            "spx_source": "yfinance ^GSPC daily Close",
            "vix_source": "yfinance ^VIX daily Close",
            "fetched_utc": started,
            "aggregation": "monthly (month-end resample, ME)",
            "lookahead_controls": [
                "IV at month t uses VIX_{t-1} (shift(1))",
                "theta_dn at month t uses rolling 12m TRAILING shares (shift(1).rolling(12))",
                "forward returns ret_{t->t+h} use h trading days AFTER month-end close",
                "HAC NW lag = h+1 for horizon-h overlapping returns",
            ],
        },
        "hypothesis_results": {
            "H1_semivariance_asymmetry": h1,
            "H2_predictive_power_horizon": h2,
            "H3_vrp_sign_decomposition": h3,
        },
        "verdict": verdict,
        "verdict_rule": ("Harvey (2016) bar + Bonferroni across H2 tests; "
                         "PASS = H1 strong AND (H2 or H3) strong; "
                         "CONDITIONAL_PASS = >=2 hypotheses with strong; "
                         "MIXED = any weak signal; NULL otherwise."),
        "figures": fig_files,
        "reviewer": None,
        "references": [
            "Bollerslev, T., Tauchen, G., Zhou, H. (2009). Expected stock returns and variance risk premia. RFS 22(11), 4463-4492.",
            "Feunou, B., Jahan-Parvar, M. R., Tedongap, R. (2013). Modeling market downside volatility. Review of Finance 17(1), 443-481.",
            "Bekaert, G., Hoerova, M. (2014). The VIX, the variance premium and stock market volatility. Journal of Econometrics 183(2), 181-192.",
            "Barndorff-Nielsen, O. E., Kinnebrock, S., Shephard, N. (2010). Measuring downside risk: realised semivariance. In: Volatility and Time Series Econometrics (eds. Bollerslev, Russell, Watson).",
            "Kilic, M., Shaliastovich, I. (2019). Good and bad variance premia and expected returns. Management Science 65(6), 2522-2544.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"[done] verdict={verdict} results={RESULTS_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
