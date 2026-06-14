"""
Risk-regime correlation breakdown early-warning test.

Question
--------
Does instability in the SPY/TLT correlation process warn that the stock-bond
diversification regime is about to fail?

Design
------
- Data: yfinance adjusted daily closes for SPY and TLT. auto_adjust=True is
  intentional because ETF total-return proxies are the target here.
- Primary signal: 21-day volatility of the 60-day SPY/TLT rolling correlation.
- Lookahead guard: every predictive feature is explicitly shifted by one day.
- Target: whether the 60-day SPY/TLT correlation crosses into a positive
  "breakdown" regime over the next 21 trading days.
- Inference: HAC(21) linear probability model and stationary bootstrap.
- DCC-GARCH: included only as a full-sample descriptive sanity check, not as a
  predictive signal, because full-sample parameter estimation would otherwise
  leak future information.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from arch import arch_model
from scipy import stats
from scipy.optimize import minimize


warnings.filterwarnings("ignore")

SEED = 42
START = "2003-01-01"
END = "2026-06-14"
TICKERS = ["SPY", "TLT"]
TRADING_DAYS = 252
CORR_WINDOW = 60
CORR_VOL_WINDOW = 21
FORWARD_HORIZON = 21
EXPANDING_MIN = 504
HIGH_Q = 0.80
POSITIVE_CORR_THRESHOLD = 0.20
BOOTSTRAP_B = 1000
BOOTSTRAP_MEAN_BLOCK = 21

BASE_DIR = Path(__file__).resolve().parent
RESULTS_PATH = BASE_DIR / "research_risk_regime_correlation_breakdown_results.json"
FIG_CORR_PATH = BASE_DIR / "fig_correlation_breakdown_signal.png"
FIG_EVENT_PATH = BASE_DIR / "fig_event_rate_and_drawdown.png"
FIG_DCC_PATH = BASE_DIR / "fig_dcc_vs_rolling_correlation.png"


@dataclass
class MeanDiffTest:
    metric: str
    n_high: int
    n_non_high: int
    high_mean: float
    non_high_mean: float
    diff_high_minus_non_high: float
    welch_t: float
    welch_p: float
    bootstrap_ci_95: list[float]
    bootstrap_p_two_sided: float


def stationary_bootstrap_indices(n: int, mean_block: int, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / mean_block
    out = np.empty(n, dtype=int)
    i = 0
    while i < n:
        start = int(rng.integers(0, n))
        block = int(rng.geometric(p))
        block = min(block, n - i)
        for j in range(block):
            out[i + j] = (start + j) % n
        i += block
    return out


def bootstrap_mean_diff(
    values: pd.Series,
    high_flag: pd.Series,
    mean_block: int = BOOTSTRAP_MEAN_BLOCK,
    b: int = BOOTSTRAP_B,
    seed: int = SEED,
) -> tuple[list[float], float]:
    df = pd.DataFrame({"value": values, "high": high_flag}).dropna()
    n = len(df)
    rng = np.random.default_rng(seed)
    draws: list[float] = []
    while len(draws) < b:
        idx = stationary_bootstrap_indices(n, mean_block=mean_block, rng=rng)
        sample = df.iloc[idx]
        if sample["high"].nunique() < 2:
            continue
        diff = sample.loc[sample["high"] == 1, "value"].mean() - sample.loc[sample["high"] == 0, "value"].mean()
        draws.append(float(diff))

    draws_arr = np.asarray(draws)
    ci = np.quantile(draws_arr, [0.025, 0.975]).tolist()
    p_left = (1.0 + float(np.sum(draws_arr <= 0.0))) / (len(draws_arr) + 1.0)
    p_right = (1.0 + float(np.sum(draws_arr >= 0.0))) / (len(draws_arr) + 1.0)
    p_two = float(min(1.0, 2.0 * min(p_left, p_right)))
    return [float(ci[0]), float(ci[1])], p_two


def run_mean_diff_test(df: pd.DataFrame, metric: str, high_col: str = "high_corr_vol_signal") -> MeanDiffTest:
    high = df.loc[df[high_col] == 1, metric]
    non_high = df.loc[df[high_col] == 0, metric]
    welch_t, welch_p = stats.ttest_ind(high, non_high, equal_var=False, nan_policy="omit")
    ci, p_two = bootstrap_mean_diff(df[metric], df[high_col])
    high_mean = float(high.mean())
    non_high_mean = float(non_high.mean())
    return MeanDiffTest(
        metric=metric,
        n_high=int(high.notna().sum()),
        n_non_high=int(non_high.notna().sum()),
        high_mean=high_mean,
        non_high_mean=non_high_mean,
        diff_high_minus_non_high=float(high_mean - non_high_mean),
        welch_t=float(welch_t),
        welch_p=float(welch_p),
        bootstrap_ci_95=ci,
        bootstrap_p_two_sided=float(p_two),
    )


def future_window_stat(series: pd.Series, horizon: int, func: Callable[[np.ndarray], float], name: str) -> pd.Series:
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(len(values) - horizon):
        window = values[i + 1 : i + 1 + horizon]
        if np.isfinite(window).any():
            out[i] = func(window)
    return pd.Series(out, index=series.index, name=name)


def future_worst_cum_return(log_ret: pd.Series, horizon: int, name: str) -> pd.Series:
    values = log_ret.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(len(values) - horizon):
        window = values[i + 1 : i + 1 + horizon]
        if np.isfinite(window).all():
            out[i] = float(np.expm1(np.cumsum(window)).min())
    return pd.Series(out, index=log_ret.index, name=name)


def hac_regression(df: pd.DataFrame, y_col: str, x_cols: list[str], maxlags: int = FORWARD_HORIZON) -> dict:
    reg_df = df[[y_col] + x_cols].replace([np.inf, -np.inf], np.nan).dropna()
    X = sm.add_constant(reg_df[x_cols])
    model = sm.OLS(reg_df[y_col], X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    params = {
        name: {
            "coef": float(model.params[name]),
            "t": float(model.tvalues[name]),
            "p": float(model.pvalues[name]),
        }
        for name in model.params.index
    }
    return {
        "n_obs": int(model.nobs),
        "r_squared": float(model.rsquared),
        "maxlags": int(maxlags),
        "params": params,
    }


def fit_gjr_std_resid(log_ret: pd.Series, name: str) -> tuple[pd.Series, dict]:
    scaled = log_ret.dropna() * 100.0
    model = arch_model(scaled, mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="t", rescale=False)
    res = model.fit(disp="off", options={"maxiter": 3000})
    std_resid = pd.Series(res.std_resid, index=scaled.index, name=name).replace([np.inf, -np.inf], np.nan).dropna()
    params = {k: float(v) for k, v in res.params.items()}
    params["convergence_flag"] = int(res.convergence_flag)
    return std_resid, params


def dcc_negative_loglik(params: np.ndarray, z: np.ndarray, q_bar: np.ndarray) -> float:
    a, b = params
    if a < 0.0 or b < 0.0 or a + b >= 0.999:
        return 1e12
    q_t = q_bar.copy()
    total = 0.0
    for t in range(1, z.shape[0]):
        z_prev = z[t - 1 : t].T
        q_t = (1.0 - a - b) * q_bar + a * (z_prev @ z_prev.T) + b * q_t
        diag = np.sqrt(np.maximum(np.diag(q_t), 1e-10))
        r_t = q_t / np.outer(diag, diag)
        sign, log_det = np.linalg.slogdet(r_t)
        if sign <= 0:
            return 1e12
        inv_r = np.linalg.solve(r_t, np.eye(r_t.shape[0]))
        z_t = z[t : t + 1].T
        quad = (z_t.T @ inv_r @ z_t - z_t.T @ z_t).item()
        total += float(-0.5 * (log_det + quad))
    return -total


def estimate_dcc_pair(std_resid: pd.DataFrame) -> tuple[pd.Series, dict]:
    z_df = std_resid.dropna()
    z = z_df.to_numpy(dtype=float)
    q_bar = np.corrcoef(z.T)

    starts = [(0.01, 0.95), (0.02, 0.90), (0.05, 0.90), (0.01, 0.85)]
    best_start = min(starts, key=lambda p: dcc_negative_loglik(np.asarray(p), z, q_bar))
    result = minimize(
        dcc_negative_loglik,
        np.asarray(best_start, dtype=float),
        args=(z, q_bar),
        method="SLSQP",
        bounds=[(1e-6, 0.30), (1e-6, 0.998)],
        constraints=[{"type": "ineq", "fun": lambda p: 0.9985 - p[0] - p[1]}],
        options={"maxiter": 3000, "ftol": 1e-10},
    )

    a_hat, b_hat = [float(x) for x in result.x]
    q_t = q_bar.copy()
    rho = np.full(z.shape[0], np.nan, dtype=float)
    for t in range(z.shape[0]):
        if t > 0:
            z_prev = z[t - 1 : t].T
            q_t = (1.0 - a_hat - b_hat) * q_bar + a_hat * (z_prev @ z_prev.T) + b_hat * q_t
        diag = np.sqrt(np.maximum(np.diag(q_t), 1e-10))
        r_t = q_t / np.outer(diag, diag)
        rho[t] = float(r_t[0, 1])

    rho_ser = pd.Series(rho, index=z_df.index, name="dcc_rho_spy_tlt")
    diagnostics = {
        "descriptive_only": True,
        "reason_not_used_as_predictive_feature": (
            "DCC parameters and univariate GARCH parameters are estimated on the full sample; "
            "using them as predictors would introduce estimation-window leakage."
        ),
        "n_obs": int(len(z_df)),
        "a": a_hat,
        "b": b_hat,
        "persistence": float(a_hat + b_hat),
        "success": bool(result.success),
        "message": str(result.message),
        "q_bar_spy_tlt": float(q_bar[0, 1]),
    }
    return rho_ser, diagnostics


def classify_regime(corr: pd.Series) -> pd.Series:
    labels = np.select(
        [corr <= -POSITIVE_CORR_THRESHOLD, corr >= POSITIVE_CORR_THRESHOLD],
        ["hedging_negative_corr", "positive_breakdown"],
        default="decoupled_near_zero",
    )
    return pd.Series(labels, index=corr.index, name="corr_regime")


def make_figures(df: pd.DataFrame, event_df: pd.DataFrame, dcc_rho: pd.Series) -> None:
    recent = df.loc[df.index >= "2018-01-01"].copy()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    ax1.plot(recent.index, recent["corr60_spy_tlt"], color="#1f5aa6", linewidth=1.0, label="60d SPY/TLT correlation")
    ax1.axhline(POSITIVE_CORR_THRESHOLD, color="#c0392b", linewidth=0.9, linestyle="--", label="+0.20 breakdown threshold")
    ax1.axhline(-POSITIVE_CORR_THRESHOLD, color="#2c7a4b", linewidth=0.9, linestyle="--", label="-0.20 hedge threshold")
    ax1.fill_between(
        recent.index,
        -1,
        1,
        where=recent["high_corr_vol_signal"] == 1,
        color="#f2c14e",
        alpha=0.18,
        label="Lagged high corr-vol signal",
    )
    ax1.set_title("SPY/TLT Correlation Regime and Lagged Instability Signal", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Correlation", fontsize=10)
    ax1.set_ylim(-1.0, 1.0)
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=8, loc="upper left")

    ax2.plot(recent.index, recent["corr_vol21_lag1"], color="#222222", linewidth=1.0, label="Lagged 21d corr-vol")
    ax2.plot(recent.index, recent["corr_vol_q80_lag1"], color="#c75b12", linewidth=1.0, linestyle="--", label="Lagged expanding 80th pct")
    ax2.set_title("Correlation-of-Correlation Volatility Signal", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Std of corr changes", fontsize=10)
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=8, loc="upper left")
    ax2.xaxis.set_major_locator(mdates.YearLocator(1))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(FIG_CORR_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)

    high = event_df[event_df["high_corr_vol_signal"] == 1]
    non_high = event_df[event_df["high_corr_vol_signal"] == 0]
    fig2, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    axes[0].bar(
        ["High corr-vol", "Not high"],
        [high["transition_to_positive_corr_21"].mean(), non_high["transition_to_positive_corr_21"].mean()],
        color=["#d95f02", "#4c78a8"],
    )
    axes[0].set_title("Forward 21d Positive-Corr Transition Rate", fontsize=11, fontweight="bold")
    axes[0].set_ylabel("Event rate", fontsize=10)
    axes[0].grid(alpha=0.3, axis="y")

    axes[1].boxplot(
        [high["fwd_6040_worst_cumret_21"].dropna(), non_high["fwd_6040_worst_cumret_21"].dropna()],
        tick_labels=["High corr-vol", "Not high"],
        patch_artist=True,
        boxprops={"facecolor": "#a8dadc"},
        medianprops={"color": "#d62828", "linewidth": 1.5},
    )
    axes[1].set_title("Forward 21d Worst 60/40 Cumulative Return", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Worst cumulative return", fontsize=10)
    axes[1].grid(alpha=0.3, axis="y")
    fig2.tight_layout()
    fig2.savefig(FIG_EVENT_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig2)

    dcc_recent = pd.concat([df["corr60_spy_tlt"], dcc_rho], axis=1).dropna().loc["2018-01-01":]
    if not dcc_recent.empty:
        fig3, ax = plt.subplots(figsize=(12, 4.8))
        ax.plot(dcc_recent.index, dcc_recent["corr60_spy_tlt"], color="#1f5aa6", linewidth=1.0, label="60d rolling corr")
        ax.plot(dcc_recent.index, dcc_recent["dcc_rho_spy_tlt"], color="#d95f02", linewidth=1.0, label="Full-sample DCC-GARCH rho")
        ax.axhline(POSITIVE_CORR_THRESHOLD, color="#c0392b", linewidth=0.9, linestyle="--")
        ax.set_title("DCC-GARCH Descriptive Check vs Rolling Correlation", fontsize=12, fontweight="bold")
        ax.set_ylabel("Correlation", fontsize=10)
        ax.set_ylim(-1.0, 1.0)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=9, loc="upper left")
        ax.xaxis.set_major_locator(mdates.YearLocator(1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        fig3.tight_layout()
        fig3.savefig(FIG_DCC_PATH, dpi=150, bbox_inches="tight")
        plt.close(fig3)


def main() -> None:
    np.random.seed(SEED)

    raw = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].copy()
    prices = prices[TICKERS].dropna()
    if prices.empty:
        raise RuntimeError("No yfinance data returned for SPY/TLT.")

    log_prices = np.log(prices)
    log_ret = log_prices.diff().dropna()
    port_6040_log_ret = (0.60 * log_ret["SPY"] + 0.40 * log_ret["TLT"]).rename("port_6040_log_ret")

    corr60 = log_ret["SPY"].rolling(CORR_WINDOW).corr(log_ret["TLT"]).rename("corr60_spy_tlt")
    corr_vol21 = corr60.diff().rolling(CORR_VOL_WINDOW).std().rename("corr_vol21")
    corr_vol_q80 = corr_vol21.expanding(EXPANDING_MIN).quantile(HIGH_Q).rename("corr_vol_q80")

    rv21_spy = (log_ret["SPY"].rolling(CORR_VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).rename("rv21_spy")
    rv21_tlt = (log_ret["TLT"].rolling(CORR_VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).rename("rv21_tlt")
    rv21_6040 = (port_6040_log_ret.rolling(CORR_VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).rename("rv21_6040")

    fwd_corr60_max = future_window_stat(corr60, FORWARD_HORIZON, np.nanmax, "fwd_corr60_max_21")
    fwd_corr60_mean = future_window_stat(corr60, FORWARD_HORIZON, np.nanmean, "fwd_corr60_mean_21")
    fwd_6040_worst = future_worst_cum_return(port_6040_log_ret, FORWARD_HORIZON, "fwd_6040_worst_cumret_21")
    fwd_spy_worst = future_worst_cum_return(log_ret["SPY"], FORWARD_HORIZON, "fwd_spy_worst_cumret_21")

    df = pd.concat(
        [
            prices,
            log_ret.add_prefix("log_ret_"),
            port_6040_log_ret,
            corr60,
            corr_vol21,
            corr_vol_q80,
            rv21_spy,
            rv21_tlt,
            rv21_6040,
            fwd_corr60_max,
            fwd_corr60_mean,
            fwd_6040_worst,
            fwd_spy_worst,
        ],
        axis=1,
    )

    # Formal predictive features. Every one is explicitly lagged by one day.
    df["corr60_lag1"] = df["corr60_spy_tlt"].shift(1)
    df["corr_vol21_lag1"] = df["corr_vol21"].shift(1)
    df["corr_vol_q80_lag1"] = df["corr_vol_q80"].shift(1)
    df["high_corr_vol_signal"] = (df["corr_vol21_lag1"] >= df["corr_vol_q80_lag1"]).astype(float)
    df["rv21_spy_lag1"] = df["rv21_spy"].shift(1)
    df["rv21_tlt_lag1"] = df["rv21_tlt"].shift(1)
    df["rv21_6040_lag1"] = df["rv21_6040"].shift(1)
    df["corr_regime_lag1"] = classify_regime(df["corr60_lag1"])
    df["at_risk_positive_breakdown"] = (df["corr60_lag1"] < POSITIVE_CORR_THRESHOLD).astype(float)
    df["transition_to_positive_corr_21"] = (
        (df["at_risk_positive_breakdown"] == 1.0)
        & (df["fwd_corr60_max_21"] >= POSITIVE_CORR_THRESHOLD)
    ).astype(float)

    required_cols = [
        "corr60_lag1",
        "corr_vol21_lag1",
        "corr_vol_q80_lag1",
        "high_corr_vol_signal",
        "rv21_spy_lag1",
        "rv21_tlt_lag1",
        "rv21_6040_lag1",
        "fwd_corr60_max_21",
        "fwd_corr60_mean_21",
        "fwd_6040_worst_cumret_21",
        "fwd_spy_worst_cumret_21",
        "transition_to_positive_corr_21",
    ]
    analysis_df = df.dropna(subset=required_cols).copy()
    event_df = analysis_df[analysis_df["at_risk_positive_breakdown"] == 1.0].copy()

    mean_tests = {
        "transition_to_positive_corr_21": asdict(run_mean_diff_test(event_df, "transition_to_positive_corr_21")),
        "fwd_corr60_mean_21": asdict(run_mean_diff_test(event_df, "fwd_corr60_mean_21")),
        "fwd_6040_worst_cumret_21": asdict(run_mean_diff_test(event_df, "fwd_6040_worst_cumret_21")),
        "fwd_spy_worst_cumret_21": asdict(run_mean_diff_test(event_df, "fwd_spy_worst_cumret_21")),
    }

    x_cols = ["high_corr_vol_signal", "corr60_lag1", "rv21_spy_lag1", "rv21_tlt_lag1"]
    transition_reg = hac_regression(event_df, "transition_to_positive_corr_21", x_cols)
    corr_mean_reg = hac_regression(event_df, "fwd_corr60_mean_21", x_cols)
    drawdown_reg = hac_regression(event_df, "fwd_6040_worst_cumret_21", x_cols)

    std_spy, garch_spy = fit_gjr_std_resid(log_ret["SPY"], "SPY")
    std_tlt, garch_tlt = fit_gjr_std_resid(log_ret["TLT"], "TLT")
    std_resid = pd.concat([std_spy, std_tlt], axis=1).dropna()
    dcc_rho, dcc_diag = estimate_dcc_pair(std_resid)
    dcc_aligned = pd.concat([analysis_df["corr60_spy_tlt"], dcc_rho], axis=1).dropna()
    dcc_diag["corr_with_rolling60"] = float(dcc_aligned["corr60_spy_tlt"].corr(dcc_aligned["dcc_rho_spy_tlt"]))
    dcc_diag["mean_rho"] = float(dcc_aligned["dcc_rho_spy_tlt"].mean())
    dcc_diag["positive_breakdown_share"] = float((dcc_aligned["dcc_rho_spy_tlt"] >= POSITIVE_CORR_THRESHOLD).mean())

    make_figures(analysis_df, event_df, dcc_rho)

    h1_diff = mean_tests["transition_to_positive_corr_21"]["diff_high_minus_non_high"]
    h1_ci = mean_tests["transition_to_positive_corr_21"]["bootstrap_ci_95"]
    h1_reg = transition_reg["params"]["high_corr_vol_signal"]
    h2_diff = mean_tests["fwd_6040_worst_cumret_21"]["diff_high_minus_non_high"]
    h2_ci = mean_tests["fwd_6040_worst_cumret_21"]["bootstrap_ci_95"]
    h2_reg = drawdown_reg["params"]["high_corr_vol_signal"]

    h1_pass = h1_diff > 0.0 and h1_ci[0] > 0.0 and h1_reg["coef"] > 0.0 and h1_reg["p"] < 0.05
    h2_pass = h2_diff < 0.0 and h2_ci[1] < 0.0 and h2_reg["coef"] < 0.0 and h2_reg["p"] < 0.05
    if h1_pass and h2_pass:
        verdict = "PASS"
    elif h1_pass or (h1_diff > 0.0 and h1_reg["coef"] > 0.0 and h1_reg["p"] < 0.10):
        verdict = "PARTIAL_PASS"
    else:
        verdict = "NULL"

    results = {
        "experiment_id": "research_risk_regime_correlation_breakdown",
        "title": "Risk-regime correlation breakdown early detection",
        "date_run": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "source": "yfinance adjusted daily close; auto_adjust=True intentionally used as total-return ETF proxy",
            "tickers": TICKERS,
            "download_period": {"start": START, "end": END},
            "effective_period": {
                "start": str(analysis_df.index.min().date()),
                "end": str(analysis_df.index.max().date()),
            },
            "n_obs_analysis": int(len(analysis_df)),
            "n_obs_at_risk_event_sample": int(len(event_df)),
        },
        "methodology": {
            "rolling_corr_window": CORR_WINDOW,
            "corr_vol_window": CORR_VOL_WINDOW,
            "forward_horizon": FORWARD_HORIZON,
            "positive_corr_breakdown_threshold": POSITIVE_CORR_THRESHOLD,
            "high_corr_vol_rule": "corr_vol21.shift(1) >= expanding_q80(corr_vol21).shift(1)",
            "lookahead_protection": [
                "corr60_lag1 = corr60.shift(1)",
                "corr_vol21_lag1 = corr_vol21.shift(1)",
                "corr_vol_q80_lag1 = corr_vol_q80.shift(1)",
                "rv controls use shift(1)",
                "forward outcomes use t+1..t+21 windows",
            ],
            "inference": {
                "hac_maxlags": FORWARD_HORIZON,
                "stationary_bootstrap_draws": BOOTSTRAP_B,
                "stationary_bootstrap_mean_block": BOOTSTRAP_MEAN_BLOCK,
            },
            "dcc_garch": {
                "role": "descriptive sanity check only",
                "leakage_note": dcc_diag["reason_not_used_as_predictive_feature"],
            },
        },
        "related_knowledge": [
            "research_program.md line 81: K534 and eight prior checks support that SPY/GLD correlation dynamics are not easily predictable.",
            "knowledge K1460: simple stock-bond correlation-regime adaptation failed to beat the best static 60/40 benchmark.",
            "knowledge K1387: Gaussian vs Student-t DCC ERC on SPY/TLT/GLD was NULL for allocation improvement.",
        ],
        "literature": [
            {
                "title": "Why Static Portfolios Fail When Risk Regimes Change",
                "source": "CFA Institute Enterprising Investor, 2026",
                "url": "https://rpc.cfainstitute.org/blogs/enterprising-investor/2026/why-static-portfolios-fail-when-risk-regimes-change",
                "use": "Motivates regime-dependent diversification failure and 2022 stock-bond co-movement risk.",
            },
            {
                "title": "A Changing Stock-Bond Correlation: Drivers and Implications",
                "source": "AQR / Journal of Portfolio Management, 2023",
                "url": "https://www.aqr.com/Insights/Research/Journal-Article/A-Changing-Stock-Bond-Correlation",
                "use": "Frames stock-bond correlation as a key portfolio-risk parameter driven by growth vs inflation uncertainty.",
            },
            {
                "title": "Flight-to-quality or Contagion? An Empirical Analysis of Stock-bond Correlations",
                "source": "IIIS Discussion Paper, 2006",
                "url": "https://ideas.repec.org/p/iis/dispap/iiisdp122.html",
                "use": "Defines stock-bond negative-correlation flight-to-quality vs positive-correlation contagion regimes.",
            },
            {
                "title": "The Performance of the 60/40 Portfolio: A Historical Perspective",
                "source": "CFA Institute Research Foundation, 2024",
                "url": "https://rpc.cfainstitute.org/sites/default/files/docs/research-reports/monash-report-1_performance-of-the-6040_online.pdf",
                "use": "Documents 2022 as a difficult 60/40 episode because bonds did not protect when stocks fell.",
            },
        ],
        "descriptive": {
            "corr60_mean": float(analysis_df["corr60_spy_tlt"].mean()),
            "corr60_median": float(analysis_df["corr60_spy_tlt"].median()),
            "corr60_min": float(analysis_df["corr60_spy_tlt"].min()),
            "corr60_max": float(analysis_df["corr60_spy_tlt"].max()),
            "positive_breakdown_share": float((analysis_df["corr60_spy_tlt"] >= POSITIVE_CORR_THRESHOLD).mean()),
            "lagged_high_corr_vol_share": float(analysis_df["high_corr_vol_signal"].mean()),
            "at_risk_transition_base_rate": float(event_df["transition_to_positive_corr_21"].mean()),
        },
        "tests": mean_tests,
        "regressions": {
            "transition_lpm_hac21": transition_reg,
            "forward_corr_mean_hac21": corr_mean_reg,
            "forward_6040_drawdown_hac21": drawdown_reg,
        },
        "dcc_garch_descriptive": {
            "garch_spy": garch_spy,
            "garch_tlt": garch_tlt,
            "dcc": dcc_diag,
        },
        "figures": [FIG_CORR_PATH.name, FIG_EVENT_PATH.name, FIG_DCC_PATH.name],
        "research_honesty_notes": [
            "The DCC-GARCH series is not used as a predictive feature because full-sample DCC parameter estimation would leak future information.",
            "The experiment tests an early-warning state variable, not a tradable allocation rule.",
            "Overlapping 21-day outcomes make iid t-statistics insufficient; HAC(21) and stationary bootstrap are the primary inference tools.",
            "A positive result should be phrased as conditional association with regime transition risk, not proof that correlation regimes are reliably forecastable.",
        ],
        "verdict": verdict,
        "verdict_rationale": (
            f"H1 transition diff={h1_diff:.6f}, CI=[{h1_ci[0]:.6f},{h1_ci[1]:.6f}], "
            f"HAC high-signal coef={h1_reg['coef']:.6f}, p={h1_reg['p']:.4f}; "
            f"H2 60/40 worst-return diff={h2_diff:.6f}, CI=[{h2_ci[0]:.6f},{h2_ci[1]:.6f}], "
            f"HAC coef={h2_reg['coef']:.6f}, p={h2_reg['p']:.4f}."
        ),
    }

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({"verdict": verdict, "descriptive": results["descriptive"]}, ensure_ascii=False, indent=2))
    print(json.dumps(results["tests"]["transition_to_positive_corr_21"], ensure_ascii=False, indent=2))
    print(json.dumps(results["regressions"]["transition_lpm_hac21"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
