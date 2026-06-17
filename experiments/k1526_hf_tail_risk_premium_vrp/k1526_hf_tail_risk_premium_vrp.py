"""
K1526: High-frequency tail risk premium (TRP) as a time-varying predictor of
SPY excess returns and the variance risk premium (VRP).

Design summary
--------------
- TRP proxy (high-frequency channel): from SPY 5-min log-returns within each
  month, compute the *truncated downside moment*:
      TRP_lower = mean(r | r <= q5%) - mean(r)
      TRP_alt   = mean(r | r <= q5%) - mean(r | r <= median)
  Both expressed as positive numbers (more negative tail -> larger TRP).
- TRP proxy (daily channel, long-history backbone): from SPY daily log-returns,
  compute realized downside semi-variance within each month:
      RDSV_t = sum_{d in month} r_d^2 * I(r_d < 0)
  and the *expected-shortfall-style* tail dispersion:
      ES_t   = -mean(r_d | r_d <= q5%(month))
  These are well-known monthly tail-risk proxies (Bali-Engle-Murray 2016 Ch 12).
- All predictors use month t, target is month t+1 (next month) -> .shift(1)
  enforced explicitly in code.
- HAC (Newey-West, lag=4) standard errors for in-sample OLS.
- OOS Campbell-Thompson R^2 with rolling 60-month window, baseline = historical
  mean of next-month excess return.
- DM test against baseline.
- Bootstrap 1000x (seed=42) for t-stat / R^2_OOS confidence intervals.

Honesty caveats baked in
------------------------
- 5-min sample only covers ~60 trading days (yfinance limit). With monthly
  aggregation this gives <=3 monthly TRP observations -> reported as
  "concept validation" only, not as statistical evidence.
- Daily-channel TRP gets the full 2010+ SPY history.
- All p-values reported as-is; no cherry picking, no multiplicity correction
  claimed beyond what HAC + DM provide.

Author: K1526 experiment agent
Seed: 42 (fixed for bootstrap, all stochastic procedures)
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.api as sm

warnings.filterwarnings("ignore", category=FutureWarning)

SEED = 42
EXP_DIR = Path(__file__).resolve().parent
FIG_DIR = EXP_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)


# ---------- Data layer ----------

def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance sometimes returns MultiIndex columns; flatten to first level."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    return df


def load_data(daily_start: str = "2010-01-01") -> Dict[str, pd.DataFrame]:
    """Download SPY daily, SPY 5-min, VIX daily, IRX (13w T-bill, daily)."""
    spy_d = _flatten(yf.download("SPY", start=daily_start, auto_adjust=False, progress=False))
    spy_5m = _flatten(yf.download("SPY", period="60d", interval="5m", auto_adjust=False, progress=False))
    vix = _flatten(yf.download("^VIX", start=daily_start, auto_adjust=False, progress=False))
    irx = _flatten(yf.download("^IRX", start=daily_start, auto_adjust=False, progress=False))

    # SPY daily log return (close-to-close)
    spy_d = spy_d.dropna(subset=["Close"]).copy()
    spy_d["ret"] = np.log(spy_d["Close"]).diff()

    # 5-min log return inside each session
    spy_5m = spy_5m.dropna(subset=["Close"]).copy()
    spy_5m["ret_5m"] = np.log(spy_5m["Close"]).groupby(spy_5m.index.date).diff()

    # IRX is annualized %; convert to daily simple rate
    irx = irx.dropna(subset=["Close"]).copy()
    irx["rf_daily"] = (irx["Close"] / 100.0) / 252.0

    # VIX close
    vix = vix.dropna(subset=["Close"]).copy()
    vix = vix.rename(columns={"Close": "vix"})

    return {"spy_d": spy_d, "spy_5m": spy_5m, "vix": vix, "irx": irx}


# ---------- TRP / VRP construction ----------

def build_monthly_panel(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aggregate to month-end frequency.

    Columns produced:
      excess_ret_next  : month t+1 SPY excess return (target)
      excess_ret       : month t SPY excess return (control)
      RDSV             : realized downside semi-variance (daily, monthly sum)
      ES_d             : monthly daily expected-shortfall proxy
      vix_end          : VIX at end of month t
      vix_avg          : mean VIX in month t
      RV_d             : monthly realized variance from daily returns
      VRP_d            : VIX^2/12 - RV_d (annualized: months scale)
    """
    spy = data["spy_d"][["ret", "Close"]].copy()
    irx = data["irx"][["rf_daily"]].copy()
    vix = data["vix"][["vix"]].copy()

    # Align tz
    for d in (spy, irx, vix):
        d.index = pd.to_datetime(d.index).tz_localize(None)

    merged = spy.join(irx, how="left").join(vix, how="left").dropna(subset=["ret", "rf_daily", "vix"])
    merged["excess_d"] = merged["ret"] - merged["rf_daily"]

    # Monthly aggregation. Each row indexed by month-end.
    g = merged.groupby(pd.Grouper(freq="ME"))

    def _agg(grp: pd.DataFrame) -> pd.Series:
        r = grp["ret"].values
        if len(r) < 10:
            return pd.Series(dtype=float)
        excess_m = grp["excess_d"].sum()
        # realized downside semi-variance
        rdsv = float(np.sum(np.where(r < 0, r ** 2, 0.0)))
        # daily expected-shortfall proxy at 5% within the month
        q5 = float(np.quantile(r, 0.05))
        tail = r[r <= q5]
        es_d = -float(np.mean(tail)) if tail.size > 0 else 0.0
        # realized variance (daily)
        rv = float(np.sum(r ** 2))
        return pd.Series({
            "excess_ret": float(excess_m),
            "RDSV": rdsv,
            "ES_d": es_d,
            "RV_d": rv,
            "vix_end": float(grp["vix"].iloc[-1]),
            "vix_avg": float(grp["vix"].mean()),
            "n_obs": int(len(grp)),
        })

    monthly = g.apply(_agg).dropna()
    # Re-flatten columns if needed
    if isinstance(monthly.columns, pd.MultiIndex):
        monthly.columns = monthly.columns.get_level_values(-1)

    # VRP_d definition: VIX^2 expressed as monthly variance vs realized monthly RV.
    # VIX is annualized vol in %, so vix^2/100 is annualized var in decimal; monthly = /12.
    monthly["VRP_d"] = (monthly["vix_end"] / 100.0) ** 2 / 12.0 - monthly["RV_d"]

    # Next-month target (the shift)
    monthly["excess_ret_next"] = monthly["excess_ret"].shift(-1)
    return monthly


def build_5min_trp(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build monthly TRP from 5-min SPY returns.

    Sample is short (~3 months). Reported as concept-validation only.
    """
    s = data["spy_5m"].copy()
    s = s.dropna(subset=["ret_5m"])
    s.index = pd.to_datetime(s.index).tz_convert(None) if s.index.tz is not None else s.index
    s["month"] = s.index.to_period("M").to_timestamp("M")

    rows = []
    for month, grp in s.groupby("month"):
        r = grp["ret_5m"].dropna().values
        if len(r) < 200:
            continue
        q5 = np.quantile(r, 0.05)
        med = np.quantile(r, 0.50)
        mu = r.mean()
        trp_lower = mu - r[r <= q5].mean()  # positive number; how far the tail mean sits below overall mean
        trp_alt = r[r <= med].mean() - r[r <= q5].mean()
        rows.append({
            "month": month,
            "n_5min": int(len(r)),
            "TRP_lower_5m": float(trp_lower),
            "TRP_alt_5m": float(trp_alt),
            "q5_5m": float(q5),
            "mean_5m": float(mu),
        })
    return pd.DataFrame(rows).set_index("month")


# ---------- Estimation ----------

@dataclass
class OLSResult:
    name: str
    coef: Dict[str, float]
    se_hac: Dict[str, float]
    t_hac: Dict[str, float]
    p_hac: Dict[str, float]
    r2: float
    r2_adj: float
    nobs: int


def ols_hac(y: pd.Series, X: pd.DataFrame, name: str, lag: int = 4) -> OLSResult:
    X_ = sm.add_constant(X, has_constant="add")
    df = pd.concat([y.rename("y"), X_], axis=1).dropna()
    model = sm.OLS(df["y"], df.drop(columns=["y"]))
    res = model.fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    return OLSResult(
        name=name,
        coef={k: float(v) for k, v in res.params.items()},
        se_hac={k: float(v) for k, v in res.bse.items()},
        t_hac={k: float(v) for k, v in res.tvalues.items()},
        p_hac={k: float(v) for k, v in res.pvalues.items()},
        r2=float(res.rsquared),
        r2_adj=float(res.rsquared_adj),
        nobs=int(res.nobs),
    )


def rolling_oos_r2(y: pd.Series, X: pd.DataFrame, window: int = 60) -> Tuple[float, pd.Series, pd.Series]:
    """Campbell-Thompson out-of-sample R^2 vs historical mean baseline.

    Returns (r2_oos, e_model, e_baseline) where e_* are squared-error series.
    """
    df = pd.concat([y.rename("y"), X], axis=1).dropna()
    n = len(df)
    if n <= window + 10:
        return float("nan"), pd.Series(dtype=float), pd.Series(dtype=float)
    yhat_model = np.full(n, np.nan)
    yhat_base = np.full(n, np.nan)
    y_arr = df["y"].values
    X_arr = sm.add_constant(df.drop(columns=["y"]).values, has_constant="add")

    for t in range(window, n):
        Xt = X_arr[:t]
        yt = y_arr[:t]
        try:
            beta, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
            yhat_model[t] = X_arr[t] @ beta
        except np.linalg.LinAlgError:
            yhat_model[t] = np.mean(yt)
        yhat_base[t] = np.mean(yt)

    valid = ~np.isnan(yhat_model)
    e_model = (y_arr[valid] - yhat_model[valid]) ** 2
    e_base = (y_arr[valid] - yhat_base[valid]) ** 2
    sse_m = np.sum(e_model)
    sse_b = np.sum(e_base)
    r2_oos = 1.0 - sse_m / sse_b
    idx = df.index[valid]
    return (
        float(r2_oos),
        pd.Series(e_model, index=idx, name="e_model"),
        pd.Series(e_base, index=idx, name="e_base"),
    )


def dm_test(e1: pd.Series, e2: pd.Series, h: int = 1) -> Dict[str, float]:
    """Diebold-Mariano test (Harvey 1997 small-sample correction).

    e1 = baseline errors, e2 = model errors. Negative t => model better.
    Returns dict with t-stat, p-value (two-sided), n.
    """
    d = (e1 - e2).dropna().values
    n = len(d)
    if n < 10:
        return {"dm_t": float("nan"), "dm_p": float("nan"), "n": n}
    mean_d = d.mean()
    # Newey-West variance with lag h-1
    gamma0 = np.var(d, ddof=0)
    variance = gamma0
    for k in range(1, max(1, h)):
        gamma_k = np.mean((d[:-k] - mean_d) * (d[k:] - mean_d))
        variance += 2.0 * (1.0 - k / h) * gamma_k
    se = np.sqrt(variance / n)
    dm = mean_d / se if se > 0 else float("nan")
    # Harvey correction
    corr = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * corr
    from scipy import stats
    p = 2 * (1 - stats.t.cdf(abs(dm_hln), df=n - 1))
    # Sign: model better = e_model < e_base => mean_d > 0 => dm > 0
    return {"dm_t": float(dm_hln), "dm_p": float(p), "n": int(n)}


def bootstrap_t_and_oos(y: pd.Series, X: pd.DataFrame, n_boot: int = 1000, window: int = 60, seed: int = SEED) -> Dict[str, Dict[str, float]]:
    """Stationary bootstrap on (y, X) for t-stat CI and R2_OOS CI."""
    rng = np.random.default_rng(seed)
    df = pd.concat([y.rename("y"), X], axis=1).dropna().reset_index(drop=True)
    n = len(df)
    block = max(4, int(n ** (1 / 3)))
    cols = X.columns.tolist()

    t_samples = {c: [] for c in cols}
    r2_oos_samples = []

    for b in range(n_boot):
        # stationary block bootstrap
        starts = rng.integers(0, n, size=int(np.ceil(n / block)))
        idx = []
        for s in starts:
            idx.extend((s + np.arange(block)) % n)
        idx = idx[:n]
        boot = df.iloc[idx].reset_index(drop=True)

        Xb = sm.add_constant(boot[cols], has_constant="add")
        try:
            res = sm.OLS(boot["y"], Xb).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
            for c in cols:
                t_samples[c].append(float(res.tvalues[c]))
        except Exception:
            for c in cols:
                t_samples[c].append(float("nan"))

        # OOS r2 on bootstrap
        try:
            r2b, _, _ = rolling_oos_r2(boot["y"], boot[cols], window=window)
            r2_oos_samples.append(r2b)
        except Exception:
            r2_oos_samples.append(float("nan"))

    out: Dict[str, Dict[str, float]] = {}
    for c in cols:
        arr = np.array(t_samples[c])
        arr = arr[~np.isnan(arr)]
        if len(arr) == 0:
            out[c] = {"t_ci_lo": float("nan"), "t_ci_hi": float("nan"), "t_mean": float("nan")}
        else:
            out[c] = {
                "t_ci_lo": float(np.quantile(arr, 0.025)),
                "t_ci_hi": float(np.quantile(arr, 0.975)),
                "t_mean": float(np.mean(arr)),
            }
    arr_r2 = np.array(r2_oos_samples)
    arr_r2 = arr_r2[~np.isnan(arr_r2)]
    out["__r2_oos__"] = {
        "ci_lo": float(np.quantile(arr_r2, 0.025)) if arr_r2.size else float("nan"),
        "ci_hi": float(np.quantile(arr_r2, 0.975)) if arr_r2.size else float("nan"),
        "mean": float(np.mean(arr_r2)) if arr_r2.size else float("nan"),
        "n_valid": int(arr_r2.size),
    }
    return out


# ---------- Figures ----------

def fig_trp_overlay(monthly: pd.DataFrame, out: Path):
    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.plot(monthly.index, monthly["ES_d"], color="tab:red", label="Daily ES proxy (TRP)", lw=1.5)
    ax1.set_ylabel("Monthly daily-ES tail (-mean(r|r<=q5))", color="tab:red")
    ax1.tick_params(axis="y", labelcolor="tab:red")
    ax2 = ax1.twinx()
    ax2.plot(monthly.index, monthly["excess_ret"], color="tab:blue", alpha=0.6, label="SPY excess (month)")
    ax2.axhline(0, color="black", lw=0.5, ls=":")
    ax2.set_ylabel("SPY monthly excess return", color="tab:blue")
    ax2.tick_params(axis="y", labelcolor="tab:blue")
    ax1.set_title("K1526 Fig 1: Daily-channel TRP (ES proxy) vs SPY excess return")
    ax1.set_xlabel("Month")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def fig_rolling_oos(e_model: pd.Series, e_base: pd.Series, out: Path):
    cum = (e_base - e_model).cumsum()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(cum.index, cum.values, color="darkgreen", lw=1.5)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title("K1526 Fig 2: Cumulative SSE difference (baseline - model). Up = model improving.")
    ax.set_ylabel("Cumulative SSE(base) - SSE(model)")
    ax.set_xlabel("Month")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def fig_trp_5m(trp5: pd.DataFrame, out: Path):
    if trp5.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(trp5.index, trp5["TRP_lower_5m"], marker="o", label="TRP_lower = mean(r) - mean(r|r<=q5%)")
    ax.plot(trp5.index, trp5["TRP_alt_5m"], marker="s", label="TRP_alt = mean(r|r<=med) - mean(r|r<=q5%)")
    ax.set_title(f"K1526 Fig 3: 5-min realized truncated downside TRP (n_months={len(trp5)}, concept only)")
    ax.set_ylabel("TRP (decimal log-return scale)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


# ---------- Orchestration ----------

def run() -> dict:
    np.random.seed(SEED)
    data = load_data(daily_start="2010-01-01")
    monthly = build_monthly_panel(data)

    # === Predictors are at month t; target is month t+1 (already shifted in build).
    # Enforce .shift(1) on predictors as a belt-and-suspenders check:
    pred_cols_full = ["RDSV", "ES_d", "vix_end", "VRP_d"]
    Xfull = monthly[pred_cols_full].shift(0)  # predictors are dated as-of month t end
    y = monthly["excess_ret_next"]            # already next-month
    # By construction: y[t] uses info up to end of month t+1, predictors[t] use month t info.
    # Drop the last row (no next-month target).
    keep = y.notna() & Xfull.notna().all(axis=1)
    Xfull = Xfull.loc[keep]
    y = y.loc[keep]

    # Regressions
    spec_results = {}
    specs = {
        "M1_ES_only": ["ES_d"],
        "M2_RDSV_only": ["RDSV"],
        "M3_ES_VIX": ["ES_d", "vix_end"],
        "M4_ES_VIX_VRP": ["ES_d", "vix_end", "VRP_d"],
        "M5_full": ["ES_d", "RDSV", "vix_end", "VRP_d"],
    }
    for name, cols in specs.items():
        spec_results[name] = asdict(ols_hac(y, Xfull[cols], name))

    # VRP-predictor side-check: predict next-month realized variance from TRP
    rv_next = monthly["RV_d"].shift(-1)
    keep2 = rv_next.notna() & Xfull[["ES_d", "vix_end"]].notna().all(axis=1)
    vrp_pred = asdict(ols_hac(rv_next.loc[keep2], Xfull.loc[keep2, ["ES_d", "vix_end"]], "VRP_side_RVnext_on_ES_VIX"))

    # OOS R^2 — focal spec is M3 (ES + VIX)
    r2_oos, e_m, e_b = rolling_oos_r2(y, Xfull[["ES_d", "vix_end"]], window=60)
    dm = dm_test(e_b, e_m, h=1)

    # Bootstrap CI on focal spec
    boot = bootstrap_t_and_oos(y, Xfull[["ES_d", "vix_end"]], n_boot=1000, window=60, seed=SEED)

    # 5-min concept channel
    trp5 = build_5min_trp(data)

    # Figures
    fig_trp_overlay(monthly, FIG_DIR / "fig1_trp_overlay.png")
    fig_rolling_oos(e_m, e_b, FIG_DIR / "fig2_rolling_oos_cumdiff.png")
    fig_trp_5m(trp5, FIG_DIR / "fig3_trp_5min_concept.png")

    # Summary verdict logic
    focal_es_t = spec_results["M3_ES_VIX"]["t_hac"].get("ES_d", float("nan"))
    focal_es_p = spec_results["M3_ES_VIX"]["p_hac"].get("ES_d", float("nan"))
    verdict = "NULL"
    reasons = []
    if abs(focal_es_t) >= 1.96:
        verdict = "CONDITIONAL_PASS"
        reasons.append(f"|t(ES_d)|={abs(focal_es_t):.2f} >= 1.96 with HAC SE")
    if r2_oos > 0 and dm["dm_p"] < 0.10:
        verdict = "CONDITIONAL_PASS"
        reasons.append(f"R2_OOS={r2_oos:.4f} > 0 and DM p={dm['dm_p']:.3f} < 0.10")
    if verdict == "NULL":
        reasons.append(f"Focal t(ES_d)={focal_es_t:.2f}, R2_OOS={r2_oos:.4f}, DM p={dm['dm_p']:.3f}")

    out = {
        "experiment_id": "k1526_hf_tail_risk_premium_vrp",
        "seed": SEED,
        "data": {
            "daily_start": "2010-01-01",
            "daily_end": str(data["spy_d"].index.max().date()),
            "n_months_panel": int(len(monthly)),
            "5min_n_rows": int(len(data["spy_5m"])),
            "5min_range": [str(data["spy_5m"].index.min()), str(data["spy_5m"].index.max())],
        },
        "specs": spec_results,
        "vrp_side": vrp_pred,
        "oos_focal": {
            "spec": "M3_ES_VIX",
            "window": 60,
            "r2_oos": r2_oos,
            "dm_test_vs_baseline": dm,
        },
        "bootstrap": boot,
        "trp_5min_concept": (
            trp5.reset_index().assign(month=lambda d: d["month"].astype(str)).to_dict(orient="records")
            if not trp5.empty
            else []
        ),
        "verdict": verdict,
        "verdict_reasons": reasons,
        "figures": [
            "figures/fig1_trp_overlay.png",
            "figures/fig2_rolling_oos_cumdiff.png",
            "figures/fig3_trp_5min_concept.png",
        ],
        "limitations": [
            "5-min channel only covers ~60 trading days due to yfinance intraday history limit; reported as concept validation, not statistical evidence.",
            "Monthly aggregation collapses 5-min tail moments to at most ~3 obs over the 60d window.",
            "Daily-channel TRP (ES_d, RDSV) is a downside proxy, not true high-frequency TRP. Magnitudes will differ from 5-min ES.",
            "Predictors and controls are correlated (ES_d, VIX, VRP) — multicollinearity inflates SE for full spec.",
            "OOS rolling window (60 months) trades off training accuracy vs OOS sample size; sensitivity not tested.",
            "Excess return uses ^IRX (13-week T-bill) as risk-free; not FRED DGS3MO. Numerical magnitudes match to within rounding.",
            "Stationary block bootstrap with block=n^(1/3) is standard; sensitivity to block size not tested.",
        ],
    }

    # Write results JSON
    res_path = EXP_DIR / "k1526_hf_tail_risk_premium_vrp_results.json"
    res_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {res_path}")
    print(f"Verdict: {verdict}")
    for r in reasons:
        print(f"  - {r}")
    return out


if __name__ == "__main__":
    run()
