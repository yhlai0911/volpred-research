"""K1512 — Double-ML factor causality test on US factor ETFs.

Research question
-----------------
After controlling for macro / market confounders (VIX, term spread, lagged
SPY return, own lagged return), does each factor's prior-12m exposure still
have a non-zero "treatment effect" on next-month excess-over-SPY return?

Model (Chernozhukov et al. 2018, EJ — Partial Linear DML)
    Y = theta * D + g(X) + epsilon
    D = m(X) + v
where, for each ETF in {MTUM, VLUE, QUAL}:
    Y_{t+1} = excess return next month over SPY
    D_t    = prior-12-month momentum (factor exposure proxy, lagged)
    X_t    = [VIX level, term spread (DGS10-DGS2), lag-1 SPY return,
              lag-1 own return]

Nuisance learners: RandomForestRegressor(n_estimators=100, max_depth=4)
Cross-fitting: 2 folds (small-n monthly panel)
Inference: DoubleML default HC + manual Newey-West (lag=3) as robustness

Lookahead policy
- All D, X are dated at month-end t (signal time = after t close; execution
  assumed at t close or first business day of t+1 with same-month-end data).
- Y is `ret.shift(-1)` so it strictly uses information from t+1.
- D is rolling 12m return ending AT month t (no skip-1); X_lag_* are shift(1).
- VIX_t and term_spread_t are same-date controls — defensible under
  "after market close" execution; flagged in README caveats.

Seed: 42 throughout (np.random.seed, sklearn random_state, DML).

Outputs
- k1512_results.json
- README.md
- fig_a_dml_theta_with_ci.png
- (this script is idempotent — re-running overwrites artifacts)
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestRegressor
from statsmodels.regression.linear_model import OLS
import statsmodels.api as sm

from doubleml import DoubleMLData, DoubleMLPLR

warnings.filterwarnings("ignore", category=FutureWarning)

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "k1512_results.json"
FIG_PATH = HERE / "fig_a_dml_theta_with_ci.png"
PANEL_PATH = HERE / "k1512_panel.parquet"

FACTORS = {
    "MTUM": "iShares MSCI USA Momentum Factor",
    "VLUE": "iShares MSCI USA Value Factor",
    "QUAL": "iShares MSCI USA Quality Factor",
}
START = "2013-01-01"  # need 12m runway before first usable row
END = "2026-05-31"


# -------------------- data --------------------

def _fred_monthly(series: str) -> pd.Series:
    """Fetch a monthly FRED series end-of-month via pandas_datareader; fall back
    to None on failure (we keep the experiment runnable without FRED).
    """
    try:
        from pandas_datareader import data as pdr
        s = pdr.DataReader(series, "fred", START, END)
        return s.iloc[:, 0].resample("ME").last()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] FRED fetch failed for {series}: {e}")
        return None


def load_panel() -> pd.DataFrame:
    """Build monthly panel:
       columns = [ret_<TICKER>, ret_SPY, vix, term_spread]
       index   = month-end timestamps.
    """
    tickers = list(FACTORS.keys()) + ["SPY", "^VIX"]
    raw = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        group_by="column",
    )
    # use Close (adjusted via auto_adjust=True)
    px = raw["Close"].copy()
    mpx = px.resample("ME").last()
    rets = mpx[["MTUM", "VLUE", "QUAL", "SPY"]].pct_change()
    vix = mpx["^VIX"]

    # term spread: DGS10 - DGS2; if FRED unavailable, fall back to a constant
    # zero series and mark in metadata (caveat in README).
    dgs10 = _fred_monthly("DGS10")
    dgs2 = _fred_monthly("DGS2")
    term_spread_available = (dgs10 is not None) and (dgs2 is not None)
    if term_spread_available:
        idx = mpx.index
        ts = (dgs10.reindex(idx, method="ffill")
              - dgs2.reindex(idx, method="ffill"))
    else:
        ts = pd.Series(0.0, index=mpx.index, name="term_spread")

    df = pd.DataFrame({
        "ret_MTUM": rets["MTUM"],
        "ret_VLUE": rets["VLUE"],
        "ret_QUAL": rets["QUAL"],
        "ret_SPY": rets["SPY"],
        "vix": vix,
        "term_spread": ts,
    })
    df.attrs["term_spread_available"] = term_spread_available
    return df


# -------------------- per-factor DML --------------------

@dataclass
class FactorResult:
    factor: str
    n_months: int
    first_date: str
    last_date: str
    theta_hat: float
    se: float
    t_stat: float
    p_value: float
    ci95_low: float
    ci95_high: float
    nw_se: float
    nw_t: float
    nw_p: float
    nw_ci95_low: float
    nw_ci95_high: float
    nw_se_lag1: float
    nw_se_lag6: float
    nw_se_lag12: float
    ols_theta: float
    ols_p: float
    bonferroni_alpha: float
    bonferroni_pass: bool


def _newey_west_se(resid_y_orth: np.ndarray, resid_d_orth: np.ndarray,
                   theta: float, lag: int = 3) -> float:
    """Manual Newey-West SE for DML PLR theta on monthly data.

    Following Chernozhukov et al. (2018) eq (4.7):
       theta = E[V*Y_orth] / E[V*D_orth]   with V = D - m(X)
       psi_i = (Y_orth_i - theta * D_orth_i) * D_orth_i / E[D_orth^2]
       Var(theta) = (1/n^2) * sum_{i,j} K(|i-j|/L) psi_i psi_j
    """
    n = len(resid_y_orth)
    psi = ((resid_y_orth - theta * resid_d_orth) * resid_d_orth
           / np.mean(resid_d_orth ** 2))
    psi = psi - psi.mean()  # mean-center per Codex recommendation
    # Bartlett kernel
    s = np.sum(psi ** 2)
    for L in range(1, lag + 1):
        w = 1.0 - L / (lag + 1)
        s += 2 * w * np.sum(psi[L:] * psi[:-L])
    return float(np.sqrt(s) / n)


def run_dml_for(factor: str, panel: pd.DataFrame, seed: int = SEED) -> FactorResult:
    own = f"ret_{factor}"

    # Build lagged features at month t (signal-time = t close):
    # D_t  = prior-12m own return (rolling window ending at t).
    # X_t  = [VIX_t, term_spread_t, ret_SPY_{t-1}, ret_own_{t-1}]
    # Y_t  = ret_own_{t+1} - ret_SPY_{t+1}    (excess over SPY)
    df = pd.DataFrame(index=panel.index)
    df["D"] = (1.0 + panel[own]).rolling(12).apply(np.prod, raw=True) - 1.0
    df["X_vix"] = panel["vix"]
    df["X_termspread"] = panel["term_spread"]
    df["X_lag_spy"] = panel["ret_SPY"].shift(1)
    df["X_lag_own"] = panel[own].shift(1)
    df["Y"] = panel[own].shift(-1) - panel["ret_SPY"].shift(-1)

    df = df.dropna()
    n = len(df)
    print(f"[{factor}] usable months = {n} (after dropna; "
          f"first={df.index[0].date()} last={df.index[-1].date()})")

    x_cols = ["X_vix", "X_termspread", "X_lag_spy", "X_lag_own"]
    dml_data = DoubleMLData(df, y_col="Y", d_cols="D", x_cols=x_cols)

    ml_g = RandomForestRegressor(n_estimators=100, max_depth=4,
                                 min_samples_leaf=5, random_state=seed)
    ml_m = RandomForestRegressor(n_estimators=100, max_depth=4,
                                 min_samples_leaf=5, random_state=seed)
    # n_rep=20 for fold-randomness robustness (Codex review recommendation)
    plr = DoubleMLPLR(dml_data, ml_g, ml_m, n_folds=2, n_rep=20,
                      score="partialling out")
    plr.fit()

    theta_hat = float(plr.coef[0])
    se = float(plr.se[0])
    t_stat = theta_hat / se if se > 0 else float("nan")
    p_value = float(plr.pval[0])
    ci = plr.confint(level=0.95)
    ci_low = float(ci.iloc[0, 0])
    ci_high = float(ci.iloc[0, 1])

    # Newey-West robustness using cross-fit residuals (average over reps).
    preds = plr.predictions
    y_arr = df["Y"].to_numpy()
    d_arr = df["D"].to_numpy()
    nw_se_by_lag: dict[int, float] = {}
    try:
        # predictions shape is (n_obs, n_rep, n_treatments=1); average reps
        g_hat = preds["ml_l"].mean(axis=1).reshape(-1)
        m_hat = preds["ml_m"].mean(axis=1).reshape(-1)
        resid_y = y_arr - g_hat
        resid_d = d_arr - m_hat
        for L in (1, 3, 6, 12):
            nw_se_by_lag[L] = _newey_west_se(resid_y, resid_d, theta_hat, lag=L)
        nw_se = nw_se_by_lag[3]
        nw_fallback = False
    except Exception as e:  # noqa: BLE001
        print(f"[{factor}] NW residual computation FAILED — using DML SE: {e}")
        nw_se = se
        for L in (1, 3, 6, 12):
            nw_se_by_lag[L] = se
        nw_fallback = True
    nw_t = theta_hat / nw_se if nw_se > 0 else float("nan")
    from scipy.stats import norm
    nw_p = float(2 * (1 - norm.cdf(abs(nw_t))))
    nw_ci_low = theta_hat - 1.96 * nw_se
    nw_ci_high = theta_hat + 1.96 * nw_se

    # Simple OLS baseline (with HAC) for comparison
    X = sm.add_constant(df[["D"] + x_cols].to_numpy())
    ols = OLS(y_arr, X).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
    ols_theta = float(ols.params[1])
    ols_p = float(ols.pvalues[1])

    # Bonferroni: 3 factors → two-sided alpha = 0.05/3 = 0.01667
    bonf_alpha = 0.05 / 3
    bonf_pass = bool(nw_p < bonf_alpha)

    return FactorResult(
        factor=factor,
        n_months=n,
        first_date=str(df.index[0].date()),
        last_date=str(df.index[-1].date()),
        theta_hat=theta_hat,
        se=se,
        t_stat=float(t_stat),
        p_value=p_value,
        ci95_low=ci_low,
        ci95_high=ci_high,
        nw_se=float(nw_se),
        nw_t=float(nw_t),
        nw_p=float(nw_p),
        nw_ci95_low=float(nw_ci_low),
        nw_ci95_high=float(nw_ci_high),
        nw_se_lag1=float(nw_se_by_lag[1]),
        nw_se_lag6=float(nw_se_by_lag[6]),
        nw_se_lag12=float(nw_se_by_lag[12]),
        ols_theta=ols_theta,
        ols_p=ols_p,
        bonferroni_alpha=bonf_alpha,
        bonferroni_pass=bonf_pass,
    )


# -------------------- verdict --------------------

def classify_verdict(results: list[FactorResult]) -> tuple[str, list[str]]:
    """Aggregate verdict using NW SE + Bonferroni correction (3 tests).

    Per-factor:
      Bonferroni-pass (p < 0.0167) AND CI excludes 0 → PASS_PRELIMINARY
      |t|<=1                                          → NULL
      else                                            → EXPLORATORY_SIGNAL

    Aggregate: PASS_PRELIMINARY if any PASS; NULL if all NULL;
               else CONDITIONAL_PASS (covers EXPLORATORY_SIGNAL mix).

    Codex review (2026-06-16): unadjusted p<0.05 single-factor is not strong
    enough to claim "real factor effect" given 3-test family; require
    Bonferroni-corrected significance.
    """
    per = []
    for r in results:
        absT = abs(r.nw_t)
        ci_excl_zero = (r.nw_ci95_low > 0) or (r.nw_ci95_high < 0)
        if r.bonferroni_pass and ci_excl_zero:
            per.append("PASS_PRELIMINARY")
        elif absT <= 1.0:
            per.append("NULL")
        else:
            per.append("EXPLORATORY_SIGNAL")
    if any(v == "PASS_PRELIMINARY" for v in per):
        agg = "PASS_PRELIMINARY"
    elif all(v == "NULL" for v in per):
        agg = "NULL"
    else:
        agg = "CONDITIONAL_PASS"
    return agg, per


# -------------------- figure --------------------

def make_figure(results: list[FactorResult]) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    names = [r.factor for r in results]
    thetas = [r.theta_hat for r in results]
    lows = [r.theta_hat - r.nw_ci95_low for r in results]   # half-width below
    highs = [r.nw_ci95_high - r.theta_hat for r in results] # half-width above
    err = np.array([lows, highs])
    colors = ["#1f77b4" if (l > 0 or h < 0) else "#7f7f7f"
              for l, h in [(r.nw_ci95_low, r.nw_ci95_high) for r in results]]
    ax.bar(names, thetas, color=colors, alpha=0.75, edgecolor="black")
    ax.errorbar(names, thetas, yerr=err, fmt="none", ecolor="black",
                capsize=6, linewidth=1.2)
    ax.axhline(0, color="red", linestyle="--", linewidth=1)
    ax.set_ylabel(r"$\hat{\theta}$ (DML PLR, excess-return per unit of prior-12m exposure)")
    ax.set_title("K1512 — DML factor causality estimates (95% NW CI)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=140)
    plt.close(fig)


# -------------------- main --------------------

def main() -> None:
    print("=== K1512 DML factor causality ===")
    panel = load_panel()
    panel.to_parquet(PANEL_PATH)

    results: list[FactorResult] = []
    for f in FACTORS:
        try:
            r = run_dml_for(f, panel)
            print(f"[{f}] theta={r.theta_hat:+.4f}  DML-se={r.se:.4f}  "
                  f"NW-se={r.nw_se:.4f}  NW-t={r.nw_t:+.2f}  p={r.nw_p:.3f}")
        except Exception as e:  # noqa: BLE001
            print(f"[{f}] FAILED: {e}")
            continue
        results.append(r)

    verdict, per = classify_verdict(results)
    print(f"\nAggregate verdict: {verdict}")
    for r, v in zip(results, per):
        print(f"  {r.factor}: {v}")

    out = {
        "k_id": "K1512",
        "experiment_id": "k1512",
        "method": "DML_PLR_RF",
        "nuisance_learner": "RandomForestRegressor(n_estimators=100, max_depth=4, min_samples_leaf=5)",
        "n_folds": 2,
        "seed": SEED,
        "sample_per_factor": {
            r.factor: {"n_months": r.n_months,
                       "first_date": r.first_date,
                       "last_date": r.last_date}
            for r in results
        },
        "term_spread_available": bool(panel.attrs.get("term_spread_available", False)),
        "verdict": verdict,
        "per_factor_verdict": dict(zip([r.factor for r in results], per)),
        "per_factor": {r.factor: asdict(r) for r in results},
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2))
    print(f"results -> {RESULTS_PATH}")

    make_figure(results)
    print(f"figure -> {FIG_PATH}")


if __name__ == "__main__":
    main()
