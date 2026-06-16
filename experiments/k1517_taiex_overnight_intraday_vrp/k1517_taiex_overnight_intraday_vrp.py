#!/usr/bin/env python3
"""K1517 — TAIEX overnight vs intraday pseudo-VRP decomposition.

Adapted from `experiments/research_intraday_vs_overnight_vrp` (parent SPY/QQQ/IWM/EFA
study). Methodology kept identical for cross-asset comparability:

- Returns:  overnight = log(Open_t / Close_{t-1});  intraday = log(Close_t / Open_t);
            close_to_close = log(Close_t / Close_{t-1}).
- Realized session variance = overnight^2 + intraday^2.
- Rolling zero-mean GARCH(1,1) variance forecast (window=1000, refit every 21d)
  on close-to-close returns. Forecast for day t uses returns through t-1.
- Total GARCH variance allocated into overnight/intraday using **lagged** trailing
  252d overnight share.
- pseudo-VRP_session = expected_session_var - realized_session_var.
- Predictive regression of log(session_var_t) on lagged session pseudo-VRPs
  (HAC SE lag=5) + 1000-rep moving-block (21d) bootstrap, seed=42.

Why not real VRP: VIXTWN only has 129 obs from 2025-12-01, far too short for the
2007-2026 window. We use the same pseudo-VRP proxy as the parent SPY study so
cross-market numbers are like-for-like (see `data_constraints.md`).

Asset universe: ^TWII (TAIEX) daily OHLC from local `storage/macro/yf_TWII.csv`.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from arch import arch_model


SEED = 42
TICKER = "^TWII"
ANALYSIS_START = pd.Timestamp("2001-01-01")
OOS_START = pd.Timestamp("2007-01-03")  # aligned to parent SPY study OOS span concept

GARCH_WINDOW = 1000
GARCH_REFIT_EVERY = 21
SHARE_WINDOW = 252
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
HAC_LAGS = 5
EPS = 1e-12

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "k1517_taiex_overnight_intraday_vrp_results.json"
FIG_SHARE = HERE / "fig_session_variance_shares.png"
FIG_PREDICT = HERE / "fig_predictive_tstats.png"
FIG_XASSET = HERE / "fig_taiex_vs_spy_overnight_vrp.png"

# Repo root: prefer main repo for parent SPY results (worktree experiments/ tree
# is sparse). TWII_CSV is replicated via storage/, which is symlinked / synced.
REPO_ROOT = HERE.parents[1]
TWII_CSV = REPO_ROOT / "storage" / "macro" / "yf_TWII.csv"
# Look for parent SPY results in worktree first, fallback to main repo.
_CANDIDATE_PARENTS = [
    REPO_ROOT / "experiments" / "research_intraday_vs_overnight_vrp" / "research_intraday_vs_overnight_vrp_results.json",
    Path("/Users/yhlai0911/Desktop/volpred-research/experiments/research_intraday_vs_overnight_vrp/research_intraday_vs_overnight_vrp_results.json"),
]
PARENT_RESULTS = next((p for p in _CANDIDATE_PARENTS if p.exists()), _CANDIDATE_PARENTS[-1])


@dataclass(frozen=True)
class RegressionResult:
    nobs: int
    coef_overnight: float
    t_overnight: float
    p_overnight: float
    coef_intraday: float
    t_intraday: float
    p_intraday: float
    r2: float


def load_taiex_ohlc() -> pd.DataFrame:
    """Load TWII from local yfinance-pulled CSV (header has 3 metadata rows)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Row 0 = Price/Close/High/Low/Open/Volume
    # Row 1 = Ticker/^TWII x5
    # Row 2 = Date/empty x5
    # Row 3+ = data
    df = pd.read_csv(TWII_CSV, skiprows=3, header=None,
                     names=["Date", "Close", "High", "Low", "Open", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "Close"])
    # Save processed
    df.to_csv(DATA_DIR / "twii_daily_processed.csv")
    return df


def one_step_garch_variance(close_to_close: pd.Series) -> pd.Series:
    """Rolling/refit one-step GARCH variance forecast in decimal-return-squared units.

    The forecast for day t is computed from returns through t-1. Parameters are
    refit every GARCH_REFIT_EVERY observations on a trailing GARCH_WINDOW sample.

    Note: r_pct units are returns x 100; forecast in pct^2; divided by 1e4 at end.
    """
    r_pct = close_to_close.dropna() * 100.0
    values = r_pct.to_numpy(dtype=float)
    index = r_pct.index
    forecasts_pct2 = np.full(len(r_pct), np.nan, dtype=float)

    for fit_start in range(GARCH_WINDOW, len(r_pct), GARCH_REFIT_EVERY):
        sample = values[fit_start - GARCH_WINDOW: fit_start]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = arch_model(sample, mean="Zero", vol="GARCH", p=1, q=1,
                               dist="normal", rescale=False)
            fit = model.fit(disp="off", show_warning=False)

        params = fit.params
        omega = float(params["omega"])
        alpha = float(params["alpha[1]"])
        beta = float(params["beta[1]"])
        h_prev = float(np.asarray(fit.conditional_volatility)[-1] ** 2)
        block_end = min(fit_start + GARCH_REFIT_EVERY, len(r_pct))

        for i in range(fit_start, block_end):
            # h_t is forecast for day t using info through t-1: uses r_{t-1}^2 and h_{t-1}
            h_t = omega + alpha * values[i - 1] ** 2 + beta * h_prev
            forecasts_pct2[i] = max(h_t, EPS)
            h_prev = h_t

    return pd.Series(forecasts_pct2 / 10000.0, index=index, name="garch_total_var")


def build_components(ohlc: pd.DataFrame) -> pd.DataFrame:
    open_px = ohlc["Open"]
    close_px = ohlc["Close"]
    overnight = np.log(open_px / close_px.shift(1))
    intraday = np.log(close_px / open_px)
    close_to_close = np.log(close_px / close_px.shift(1))

    df = pd.DataFrame({
        "overnight_ret": overnight,
        "intraday_ret": intraday,
        "close_to_close_ret": close_to_close,
    }).dropna()
    df = df[df.index >= ANALYSIS_START].copy()
    df["overnight_var"] = df["overnight_ret"] ** 2
    df["intraday_var"] = df["intraday_ret"] ** 2
    df["session_var"] = df["overnight_var"] + df["intraday_var"]
    df["close_to_close_var"] = df["close_to_close_ret"] ** 2
    df["covariance_residual_var"] = df["close_to_close_var"] - df["session_var"]

    garch_total = one_step_garch_variance(df["close_to_close_ret"]).reindex(df.index)
    share_raw = (
        df["overnight_var"].rolling(SHARE_WINDOW).sum()
        / df["session_var"].rolling(SHARE_WINDOW).sum().replace(0.0, np.nan)
    )
    # t-1 info → predict t (lagged share allocation; never uses day-t realized share)
    overnight_share_lag1 = share_raw.shift(1).clip(lower=0.0, upper=1.0)
    df["garch_total_var"] = garch_total
    df["expected_overnight_var"] = df["garch_total_var"] * overnight_share_lag1
    df["expected_intraday_var"] = df["garch_total_var"] * (1.0 - overnight_share_lag1)
    df["overnight_pseudo_vrp"] = df["expected_overnight_var"] - df["overnight_var"]
    df["intraday_pseudo_vrp"] = df["expected_intraday_var"] - df["intraday_var"]

    # Lagged predictors (explicit .shift(1) — Lookahead red-line guarded)
    df["overnight_pseudo_vrp_lag1"] = df["overnight_pseudo_vrp"].shift(1)
    df["intraday_pseudo_vrp_lag1"] = df["intraday_pseudo_vrp"].shift(1)
    df["log_session_var"] = np.log(df["session_var"] + EPS)
    df["log_session_var_lag1"] = df["log_session_var"].shift(1)
    df["log_garch_total_var_lag1"] = np.log(df["garch_total_var"].shift(1) + EPS)
    return df


def moving_block_indices(n: int, rng: np.random.Generator) -> np.ndarray:
    chosen: list[int] = []
    while len(chosen) < n:
        start = int(rng.integers(0, max(1, n - BOOTSTRAP_BLOCK + 1)))
        chosen.extend(range(start, min(start + BOOTSTRAP_BLOCK, n)))
    return np.asarray(chosen[:n], dtype=int)


def bootstrap_share_and_premium(df: pd.DataFrame) -> dict:
    sample = df[df.index >= OOS_START][
        ["overnight_var", "intraday_var", "session_var",
         "overnight_pseudo_vrp", "intraday_pseudo_vrp"]
    ].dropna()
    arr = sample.to_numpy(dtype=float)
    rng = np.random.default_rng(SEED)
    rows = []
    for _ in range(BOOTSTRAP_REPS):
        b = arr[moving_block_indices(len(arr), rng)]
        overnight_sum = b[:, 0].sum()
        intraday_sum = b[:, 1].sum()
        session_sum = b[:, 2].sum()
        ov_prem = b[:, 3].mean()
        in_prem = b[:, 4].mean()
        rows.append({
            "overnight_share": overnight_sum / session_sum if session_sum > 0 else np.nan,
            "intraday_share": intraday_sum / session_sum if session_sum > 0 else np.nan,
            "premium_diff_overnight_minus_intraday": ov_prem - in_prem,
            "mean_overnight_premium": ov_prem,
            "mean_intraday_premium": in_prem,
        })
    boot = pd.DataFrame(rows)
    out = {}
    for col in boot.columns:
        values = boot[col].dropna().to_numpy()
        out[col] = {
            "mean": round(float(values.mean()), 8),
            "ci_2p5": round(float(np.quantile(values, 0.025)), 8),
            "ci_97p5": round(float(np.quantile(values, 0.975)), 8),
            "p_gt_0": round(float((values > 0).mean()), 4),
            "p_gt_half": round(float((values > 0.5).mean()), 4) if "share" in col else None,
        }
    return out


def standardize(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return s * np.nan
    return (s - s.mean()) / sd


def predictive_regression(df: pd.DataFrame, target_col: str) -> RegressionResult:
    """Regress target log-variance on lagged session pseudo-VRPs + AR controls."""
    oos = df[df.index >= OOS_START].copy()
    reg = pd.DataFrame({
        "target": oos[target_col],
        "overnight": standardize(oos["overnight_pseudo_vrp_lag1"]),
        "intraday": standardize(oos["intraday_pseudo_vrp_lag1"]),
        "log_session_lag1": oos["log_session_var_lag1"],
        "log_garch_lag1": oos["log_garch_total_var_lag1"],
    }).replace([np.inf, -np.inf], np.nan).dropna()
    x = sm.add_constant(reg[["overnight", "intraday", "log_session_lag1", "log_garch_lag1"]])
    fit = sm.OLS(reg["target"], x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return RegressionResult(
        nobs=int(fit.nobs),
        coef_overnight=round(float(fit.params["overnight"]), 6),
        t_overnight=round(float(fit.tvalues["overnight"]), 4),
        p_overnight=round(float(fit.pvalues["overnight"]), 6),
        coef_intraday=round(float(fit.params["intraday"]), 6),
        t_intraday=round(float(fit.tvalues["intraday"]), 4),
        p_intraday=round(float(fit.pvalues["intraday"]), 6),
        r2=round(float(fit.rsquared), 6),
    )


def summarize_asset(df: pd.DataFrame) -> dict:
    oos = df[df.index >= OOS_START].dropna(subset=[
        "overnight_var", "intraday_var", "session_var",
        "garch_total_var", "overnight_pseudo_vrp",
    ])
    overnight_sum = float(oos["overnight_var"].sum())
    intraday_sum = float(oos["intraday_var"].sum())
    session_sum = float(oos["session_var"].sum())
    total_sum = float(oos["close_to_close_var"].sum())
    covariance_sum = float(oos["covariance_residual_var"].sum())
    expected_sum = float(oos["garch_total_var"].sum())
    overnight_premium = float(oos["overnight_pseudo_vrp"].mean())
    intraday_premium = float(oos["intraday_pseudo_vrp"].mean())

    # Primary regression on log session_var (matches parent SPY methodology)
    reg_session = predictive_regression(df, target_col="log_session_var")
    boot = bootstrap_share_and_premium(df)

    return {
        "ticker": TICKER,
        "n_oos": int(len(oos)),
        "oos_start": str(oos.index[0].date()),
        "oos_end": str(oos.index[-1].date()),
        "realized_session_variance": {
            "overnight_share": round(overnight_sum / session_sum, 6),
            "intraday_share": round(intraday_sum / session_sum, 6),
            "covariance_residual_share_of_close_to_close_var": round(covariance_sum / total_sum, 6),
            "mean_daily_overnight_var_pct2": round(float(oos["overnight_var"].mean() * 10000.0), 6),
            "mean_daily_intraday_var_pct2": round(float(oos["intraday_var"].mean() * 10000.0), 6),
            "mean_daily_close_to_close_var_pct2": round(float(oos["close_to_close_var"].mean() * 10000.0), 6),
        },
        "garch_proxy": {
            "mean_expected_total_var_pct2": round(float(oos["garch_total_var"].mean() * 10000.0), 6),
            "mean_realized_session_var_pct2": round(float(oos["session_var"].mean() * 10000.0), 6),
            "expected_minus_realized_total_var_pct2": round((expected_sum - session_sum) / len(oos) * 10000.0, 6),
            "mean_overnight_pseudo_vrp_pct2": round(overnight_premium * 10000.0, 6),
            "mean_intraday_pseudo_vrp_pct2": round(intraday_premium * 10000.0, 6),
            "mean_premium_diff_overnight_minus_intraday_pct2": round(
                (overnight_premium - intraday_premium) * 10000.0, 6
            ),
        },
        "bootstrap_oos": boot,
        "predictive_regression_oos": reg_session.__dict__,
    }


def load_parent_spy_results() -> dict:
    """Load SPY/QQQ/IWM/EFA results from parent experiment for cross-asset comparison."""
    if not PARENT_RESULTS.exists():
        return {}
    return json.loads(PARENT_RESULTS.read_text())


def build_figures(summary: dict, parent_results: dict) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")

    # Figure 1: TAIEX session variance shares (single asset bar)
    ov_share = summary["realized_session_variance"]["overnight_share"]
    in_share = summary["realized_session_variance"]["intraday_share"]
    fig, ax = plt.subplots(figsize=(6, 5.5))
    ax.bar(["^TWII (TAIEX)"], [ov_share], label="Overnight", color="#4c78a8")
    ax.bar(["^TWII (TAIEX)"], [in_share], bottom=[ov_share], label="Intraday", color="#f58518")
    ax.axhline(0.5, color="#444444", linewidth=1, linestyle="--")
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Share of OOS session variance")
    ax.set_title(f"TAIEX: Overnight vs Intraday Realized Variance Shares\n(OOS {summary['oos_start']} → {summary['oos_end']})")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_SHARE, dpi=180)
    plt.close(fig)

    # Figure 2: Predictive HAC t-stats for TAIEX
    t_ov = summary["predictive_regression_oos"]["t_overnight"]
    t_in = summary["predictive_regression_oos"]["t_intraday"]
    fig2, ax2 = plt.subplots(figsize=(6, 5.5))
    width = 0.36
    ax2.bar([-width/2], [t_ov], width=width, label="Lagged overnight pseudo-VRP", color="#4c78a8")
    ax2.bar([+width/2], [t_in], width=width, label="Lagged intraday pseudo-VRP", color="#f58518")
    ax2.axhline(3.0, color="#444444", linewidth=1, linestyle="--")
    ax2.axhline(-3.0, color="#444444", linewidth=1, linestyle="--")
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_xticks([0])
    ax2.set_xticklabels(["^TWII (TAIEX)"])
    ax2.set_ylabel("HAC t-stat (lag=5)")
    ax2.set_title("TAIEX Next-Day log(session var) Predictive Regression")
    ax2.legend(frameon=False)
    fig2.tight_layout()
    fig2.savefig(FIG_PREDICT, dpi=180)
    plt.close(fig2)

    # Figure 3: Cross-asset overnight VRP / shares vs SPY universe
    parent_assets = parent_results.get("asset_results", {})
    if not parent_assets:
        return

    labels = list(parent_assets.keys()) + ["^TWII"]
    ov_shares = [parent_assets[a]["realized_session_variance"]["overnight_share"] for a in parent_assets] + [ov_share]
    t_ovs = [parent_assets[a]["predictive_regression_oos"]["t_overnight"] for a in parent_assets] + [t_ov]
    ov_vrps = [parent_assets[a]["garch_proxy"]["mean_overnight_pseudo_vrp_pct2"] for a in parent_assets] + [
        summary["garch_proxy"]["mean_overnight_pseudo_vrp_pct2"]
    ]

    fig3, axes = plt.subplots(1, 3, figsize=(16, 5))
    x = np.arange(len(labels))
    bar_colors = ["#4c78a8"] * (len(labels) - 1) + ["#e45756"]

    axes[0].bar(x, ov_shares, color=bar_colors)
    axes[0].axhline(0.5, color="#444444", linestyle="--", linewidth=1)
    axes[0].set_xticks(x); axes[0].set_xticklabels(labels)
    axes[0].set_ylim(0, 1.0)
    axes[0].set_ylabel("Overnight share of session variance")
    axes[0].set_title("Overnight share of OOS realized session variance")

    axes[1].bar(x, ov_vrps, color=bar_colors)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_xticks(x); axes[1].set_xticklabels(labels)
    axes[1].set_ylabel("Mean overnight pseudo-VRP (pct^2)")
    axes[1].set_title("Mean overnight pseudo-VRP\n(GARCH expected − realized)")

    axes[2].bar(x, t_ovs, color=bar_colors)
    axes[2].axhline(3.0, color="#444444", linestyle="--", linewidth=1)
    axes[2].axhline(-3.0, color="#444444", linestyle="--", linewidth=1)
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].set_xticks(x); axes[2].set_xticklabels(labels)
    axes[2].set_ylabel("HAC t-stat (lag overnight pseudo-VRP)")
    axes[2].set_title("Predictive regression HAC t-stat\n(overnight pseudo-VRP → next-day log session var)")

    fig3.suptitle("TAIEX vs SPY/QQQ/IWM/EFA — Overnight Variance Decomposition (Pseudo-VRP)", fontsize=12)
    fig3.tight_layout()
    fig3.savefig(FIG_XASSET, dpi=180)
    plt.close(fig3)


def determine_verdict(summary: dict, parent_assets: dict) -> dict:
    """Match parent decision rule + comparative sign-check narrative."""
    boot = summary["bootstrap_oos"]
    ov_ci_lower = boot["overnight_share"]["ci_2p5"]
    t_ov = summary["predictive_regression_oos"]["t_overnight"]
    t_in = summary["predictive_regression_oos"]["t_intraday"]

    overnight_majority = ov_ci_lower > 0.5
    overnight_predict_pass = t_ov > 3.0

    # Compare TAIEX overnight VRP sign vs SPY's
    taiex_ov_vrp = summary["garch_proxy"]["mean_overnight_pseudo_vrp_pct2"]
    spy_ov_vrp = parent_assets.get("SPY", {}).get("garch_proxy", {}).get("mean_overnight_pseudo_vrp_pct2", None)
    if spy_ov_vrp is None or not np.isfinite(spy_ov_vrp):
        sign_str = "SPY comparison unavailable (parent results missing)"
    elif np.sign(taiex_ov_vrp) == np.sign(spy_ov_vrp):
        sign_str = f"TAIEX ({taiex_ov_vrp:+.4f}) and SPY ({spy_ov_vrp:+.4f}) overnight pseudo-VRP have SAME sign"
    else:
        sign_str = f"TAIEX ({taiex_ov_vrp:+.4f}) and SPY ({spy_ov_vrp:+.4f}) overnight pseudo-VRP have OPPOSITE sign"

    if overnight_majority and overnight_predict_pass:
        overall = "PSEUDO_VRP_SUPPORT"
        plain = "TAIEX shows robust overnight variance majority AND lagged overnight pseudo-VRP predicts next-day session variance."
    elif overnight_majority or overnight_predict_pass:
        overall = "CONDITIONAL_PASS"
        plain = "TAIEX shows partial overnight-dominance evidence: one of two pre-specified gates passes."
    else:
        overall = "NULL"
        plain = ("Like SPY/QQQ/IWM (US ETFs), TAIEX does not satisfy both gates of the "
                 "overnight-dominance + next-day predictability test. Cross-market finding: "
                 "the pseudo-VRP framework (GARCH-based) yields NULL across SPY-family AND TAIEX, "
                 "suggesting the option-implied VRP literature's overnight finding may not survive "
                 "the model-implied VRP proxy.")

    return {
        "overall": overall,
        "overnight_majority_pass": overnight_majority,
        "overnight_predict_pass": overnight_predict_pass,
        "taiex_overnight_pseudo_vrp_pct2": taiex_ov_vrp,
        "spy_overnight_pseudo_vrp_pct2": (None if (spy_ov_vrp is None or not np.isfinite(spy_ov_vrp)) else spy_ov_vrp),
        "sign_comparison": sign_str,
        "plain_english": plain,
    }


def main() -> None:
    np.random.seed(SEED)

    ohlc = load_taiex_ohlc()
    print(f"[K1517] Loaded TWII OHLC: {len(ohlc):,} rows from {ohlc.index[0].date()} to {ohlc.index[-1].date()}")

    df = build_components(ohlc)
    print(f"[K1517] Components built: {len(df):,} rows after dropna; OOS subset starts {OOS_START.date()}.")
    n_oos = (df.index >= OOS_START).sum()
    print(f"[K1517] OOS sample size: {n_oos:,}")

    summary = summarize_asset(df)
    print(f"[K1517] OOS overnight share = {summary['realized_session_variance']['overnight_share']}, "
          f"intraday share = {summary['realized_session_variance']['intraday_share']}")
    print(f"[K1517] Mean overnight pseudo-VRP (pct^2) = {summary['garch_proxy']['mean_overnight_pseudo_vrp_pct2']}, "
          f"intraday = {summary['garch_proxy']['mean_intraday_pseudo_vrp_pct2']}")
    print(f"[K1517] HAC t-stats: t_overnight = {summary['predictive_regression_oos']['t_overnight']}, "
          f"t_intraday = {summary['predictive_regression_oos']['t_intraday']}")

    parent_results = load_parent_spy_results()
    parent_assets = parent_results.get("asset_results", {})

    build_figures(summary, parent_results)
    verdict = determine_verdict(summary, parent_assets)
    print(f"[K1517] Verdict: {verdict['overall']}")

    # Compare to SPY family — build cross-asset table for results JSON
    cross_asset_table = []
    for a, s in parent_assets.items():
        cross_asset_table.append({
            "ticker": a,
            "overnight_share": s["realized_session_variance"]["overnight_share"],
            "mean_overnight_pseudo_vrp_pct2": s["garch_proxy"]["mean_overnight_pseudo_vrp_pct2"],
            "mean_intraday_pseudo_vrp_pct2": s["garch_proxy"]["mean_intraday_pseudo_vrp_pct2"],
            "t_overnight": s["predictive_regression_oos"]["t_overnight"],
            "t_intraday": s["predictive_regression_oos"]["t_intraday"],
        })
    cross_asset_table.append({
        "ticker": "^TWII",
        "overnight_share": summary["realized_session_variance"]["overnight_share"],
        "mean_overnight_pseudo_vrp_pct2": summary["garch_proxy"]["mean_overnight_pseudo_vrp_pct2"],
        "mean_intraday_pseudo_vrp_pct2": summary["garch_proxy"]["mean_intraday_pseudo_vrp_pct2"],
        "t_overnight": summary["predictive_regression_oos"]["t_overnight"],
        "t_intraday": summary["predictive_regression_oos"]["t_intraday"],
    })

    results = {
        "experiment_id": "k1517_taiex_overnight_intraday_vrp",
        "title": "K1517 — TAIEX overnight vs intraday pseudo-VRP decomposition and cross-market comparison vs SPY/QQQ/IWM/EFA",
        "date_run_utc": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "ticker": TICKER,
            "source": "Local CSV at storage/macro/yf_TWII.csv (pre-fetched yfinance daily OHLC).",
            "raw_rows": int(len(ohlc)),
            "raw_first_date": str(ohlc.index[0].date()),
            "raw_last_date": str(ohlc.index[-1].date()),
            "analysis_start": str(ANALYSIS_START.date()),
            "oos_start": str(OOS_START.date()),
            "n_oos": int(summary["n_oos"]),
            "vix_taiwan_note": (
                "VIXTWN only has 129 daily obs from 2025-12-01 — too short for "
                "true option-IV-based VRP over 2007-2026. We use the same GARCH-based "
                "pseudo-VRP proxy as the parent SPY/QQQ/IWM/EFA study for like-for-like "
                "comparison. See data_constraints.md."
            ),
        },
        "method": {
            "returns": {
                "overnight": "log(Open_t / Close_{t-1})",
                "intraday": "log(Close_t / Open_t)",
                "close_to_close": "log(Close_t / Close_{t-1})",
            },
            "pseudo_vrp_definition": (
                "GARCH one-step expected component variance minus realized component variance; "
                "NOT an option-implied model-free VRP."
            ),
            "garch_proxy": {
                "model": "Zero-mean GARCH(1,1) on close-to-close log returns in percent units",
                "window": GARCH_WINDOW,
                "refit_every": GARCH_REFIT_EVERY,
                "forecast_timing": "forecast for day t uses returns through t-1",
            },
            "component_allocation": (
                "total GARCH variance is allocated by trailing 252d overnight share shifted by one day"
            ),
            "predictive_regression": {
                "target": "current-day log(session variance)",
                "features": [
                    "overnight_pseudo_vrp.shift(1)",
                    "intraday_pseudo_vrp.shift(1)",
                    "log_session_var.shift(1)",
                    "log_garch_total_var.shift(1)",
                ],
                "standard_errors": f"Newey-West HAC maxlags={HAC_LAGS}",
                "success_rule": (
                    "Joint gate: overnight variance-share CI lower > 0.5 AND lagged overnight "
                    "pseudo-VRP HAC t > 3."
                ),
            },
            "bootstrap": {"reps": BOOTSTRAP_REPS, "block_length": BOOTSTRAP_BLOCK, "seed": SEED},
            "lookahead_protection": [
                "GARCH forecast for day t uses close-to-close returns through t-1",
                "component allocation share is shifted by one day",
                "predictive features use explicit .shift(1)",
            ],
        },
        "asset_results": {"^TWII": summary},
        "cross_asset_comparison_table": cross_asset_table,
        "figures": [FIG_SHARE.name, FIG_PREDICT.name, FIG_XASSET.name],
        "literature": [
            {"citation": "Papagelis and Dotsis (2025), The Variance Risk Premium Over Trading and Nontrading Periods",
             "url": "https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589"},
            {"citation": "Carr and Wu (2009), Variance Risk Premia",
             "url": "https://doi.org/10.1093/rfs/hhn038"},
            {"citation": "Bollerslev, Tauchen, and Zhou (2009), Expected Stock Returns and Variance Risk Premia",
             "url": "https://www.federalreserve.gov/pubs/feds/2007/200711/"},
            {"citation": "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility",
             "url": "https://doi.org/10.1093/jjfinec/nbp001"},
        ],
        "related_experiments": [
            "experiments/research_intraday_vs_overnight_vrp/ (parent SPY/QQQ/IWM/EFA study, verdict=NULL)",
            "experiments/experiment_0dte_intraday_overnight_vol_2026_06_13/",
            "experiments/research_vrp_vrp_horizon/",
        ],
        "research_honesty_notes": [
            "Daily yfinance OHLC cannot identify true option-implied VRP; this is a pseudo-VRP proxy only.",
            "No same-day realized pseudo-VRP is used as a predictor; predictive regressions use lagged features.",
            "Because GARCH is a physical-measure forecast, mean pseudo-premia should not be interpreted as investable option carry.",
            "Cross-market sign of pseudo-VRP is interpretable but magnitude is dominated by GARCH bias relative to realized — not the option-implied premium.",
            "TAIEX has only day-session trading (no formal overnight session in cash index); 'overnight' here is the close-to-open gap captured by ^TWII Open vs prior Close, which is the natural analog used in the literature.",
        ],
        "verdict": verdict,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[K1517] Results saved to {RESULTS_PATH}")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
