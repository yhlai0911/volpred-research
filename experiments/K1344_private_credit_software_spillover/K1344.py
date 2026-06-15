"""K1344 - Private-credit software stress spillover to IGV/HYG volatility.

Question
--------
Do public BDC/private-credit stress proxies leave an incremental forward
volatility footprint in software equities (IGV), beyond own-HAR and market/tech
controls? HYG is kept as the credit benchmark.

Research-honesty guardrails
---------------------------
* All features entering forecasts are explicit .shift(1).
* Forward-label expanding OLS uses target_end_pos < forecast_pos, not merely
  date < forecast date, avoiding the K1337 horizon-overlap leak.
* Hard-coded OOS split: 2021-01-04 onward.
* Seed fixed at 42 for all bootstrap/event resampling.
* Primary family: 2 targets x 2 horizons = 4 tests; Bonferroni alpha = 0.0125.

Outputs
-------
K1344_results.json plus two diagnostic figures.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1344_private_credit_software_spillover"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_START = "2013-01-01"
DATA_END = "2026-06-15"
OOS_START = pd.Timestamp("2021-01-04")

BDC_TICKERS = ["BIZD", "ARCC", "BXSL", "OBDC", "FSK"]
TARGETS = ["IGV", "HYG"]
CONTROL_TICKERS = ["SPY", "QQQ"]
ALL_TICKERS = sorted(set(BDC_TICKERS + TARGETS + CONTROL_TICKERS))

HORIZONS = [5, 21]
PRIMARY_TESTS = len(TARGETS) * len(HORIZONS)
BONFERRONI_ALPHA = 0.05 / PRIMARY_TESTS

MIN_TRAIN = 504
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
EVENT_COOLDOWN = 21
EPS = 1e-10


@dataclass
class ForecastResult:
    target: str
    horizon: int
    n_oos: int
    baseline_qlike: float
    augmented_qlike: float
    qlike_improvement_pct: float
    dm_t: float
    dm_p_two_sided: float
    bootstrap_mean_diff: float
    bootstrap_ci95: list[float]
    bootstrap_p_improve: float
    passes_bonferroni: bool
    conditional_pass: bool


def download_close(ticker: str) -> pd.Series:
    df = yf.download(
        ticker,
        start=DATA_START,
        end=DATA_END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if df.empty:
        raise RuntimeError(f"No data downloaded for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].dropna().copy()
    close.name = ticker
    return close


def load_prices() -> pd.DataFrame:
    series = [download_close(t) for t in ALL_TICKERS]
    prices = pd.concat(series, axis=1).sort_index()
    return prices


def realized_var(ret: pd.Series, window: int) -> pd.Series:
    return ret.pow(2).rolling(window, min_periods=window).mean() * 252.0


def forward_var(ret: pd.Series, horizon: int) -> pd.Series:
    parts = [ret.shift(-k).pow(2) for k in range(horizon)]
    return pd.concat(parts, axis=1).mean(axis=1) * 252.0


def qlike(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    actual = np.maximum(np.asarray(actual, dtype=float), EPS)
    forecast = np.maximum(np.asarray(forecast, dtype=float), EPS)
    ratio = actual / forecast
    return ratio - np.log(ratio) - 1.0


def moving_block_bootstrap_mean(
    values: np.ndarray,
    block: int = BOOTSTRAP_BLOCK,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> dict[str, float | list[float]]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return {"mean": float("nan"), "ci95": [float("nan"), float("nan")], "p_improve": float("nan")}
    rng = np.random.default_rng(seed)
    n = len(values)
    n_blocks = int(math.ceil(n / block))
    max_start = max(1, n - block + 1)
    means = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, max_start, size=n_blocks)
        sample = np.concatenate([values[s : s + block] for s in starts])[:n]
        means[r] = sample.mean()
    return {
        "mean": float(values.mean()),
        "ci95": [float(x) for x in np.percentile(means, [2.5, 97.5])],
        "p_improve": float((np.sum(means <= 0.0) + 1) / (reps + 1)),
    }


def hac_mean_test(values: pd.Series, maxlags: int) -> tuple[float, float]:
    y = values.dropna().astype(float)
    if len(y) < 5 or y.std(ddof=1) == 0:
        return float("nan"), float("nan")
    x = np.ones((len(y), 1))
    fit = sm.OLS(y.values, x).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return float(fit.tvalues[0]), float(fit.pvalues[0])


def build_feature_panel(prices: pd.DataFrame) -> pd.DataFrame:
    log_prices = np.log(prices)
    returns = log_prices.diff()

    panel = pd.DataFrame(index=prices.index)

    bdc_count = returns[BDC_TICKERS].notna().sum(axis=1)
    panel["bdc_ret"] = returns[BDC_TICKERS].mean(axis=1).where(bdc_count >= 2)
    panel["bdc_member_count"] = bdc_count
    panel["bizd_ret"] = returns["BIZD"]

    for ticker in TARGETS + CONTROL_TICKERS + ["BIZD"]:
        panel[f"{ticker}_ret"] = returns[ticker]
        for w in [5, 21, 63]:
            panel[f"{ticker}_rv{w}"] = realized_var(returns[ticker], w)
        panel[f"{ticker}_ret21"] = returns[ticker].rolling(21, min_periods=21).sum()

    panel["bdc_rv21"] = realized_var(panel["bdc_ret"], 21)
    panel["bdc_ret21"] = panel["bdc_ret"].rolling(21, min_periods=21).sum()
    bdc_rv_mean = panel["bdc_rv21"].rolling(252, min_periods=126).mean()
    bdc_rv_std = panel["bdc_rv21"].rolling(252, min_periods=126).std()
    panel["bdc_rv_z"] = (panel["bdc_rv21"] - bdc_rv_mean) / bdc_rv_std
    panel["bdc_pressure"] = (-panel["bdc_ret21"]).clip(lower=0.0) * panel["bdc_rv_z"].clip(lower=0.0)
    panel["bizd_hyg_gap"] = -(panel["BIZD_ret21"] - panel["HYG_ret21"])

    # Explicit one-day lag: features as of t-1 forecast target returns beginning at t.
    for col in [
        "bdc_rv_z",
        "bdc_pressure",
        "bdc_ret21",
        "bizd_hyg_gap",
        "SPY_rv21",
        "QQQ_rv21",
    ]:
        panel[f"{col}_l1"] = panel[col].shift(1)

    for target in TARGETS:
        for w in [5, 21, 63]:
            panel[f"{target}_rv{w}_l1"] = panel[f"{target}_rv{w}"].shift(1)
        for h in HORIZONS:
            panel[f"{target}_fwd_var_{h}"] = forward_var(panel[f"{target}_ret"], h)
            panel[f"{target}_log_fwd_var_{h}"] = np.log(panel[f"{target}_fwd_var_{h}"] + EPS)

    # Log-transform positive variance controls after lagging.
    for col in [
        "SPY_rv21_l1",
        "QQQ_rv21_l1",
        "IGV_rv5_l1",
        "IGV_rv21_l1",
        "IGV_rv63_l1",
        "HYG_rv5_l1",
        "HYG_rv21_l1",
        "HYG_rv63_l1",
    ]:
        panel[f"log_{col}"] = np.log(panel[col] + EPS)

    return panel


def forecast_one_spec(panel: pd.DataFrame, target: str, horizon: int) -> tuple[ForecastResult, pd.DataFrame]:
    base_cols = [
        f"log_{target}_rv5_l1",
        f"log_{target}_rv21_l1",
        f"log_{target}_rv63_l1",
        "log_SPY_rv21_l1",
        "log_QQQ_rv21_l1",
    ]
    aug_cols = base_cols + [
        "bdc_rv_z_l1",
        "bdc_pressure_l1",
        "bdc_ret21_l1",
        "bizd_hyg_gap_l1",
    ]
    y_col = f"{target}_log_fwd_var_{horizon}"
    actual_col = f"{target}_fwd_var_{horizon}"

    work = panel.copy()
    work["pos"] = np.arange(len(work))
    work["target_end_pos"] = work["pos"] + horizon - 1

    rows = []
    needed = [y_col, actual_col] + aug_cols
    for i, (date, row) in enumerate(work.iterrows()):
        if date < OOS_START:
            continue
        if row[needed].isna().any():
            continue
        train = work.iloc[:i].copy()
        train = train[train["target_end_pos"] < i]
        train = train.dropna(subset=needed)
        if len(train) < MIN_TRAIN:
            continue

        y_train = train[y_col].astype(float)
        x_base = sm.add_constant(train[base_cols].astype(float), has_constant="add")
        x_aug = sm.add_constant(train[aug_cols].astype(float), has_constant="add")

        fit_base = sm.OLS(y_train, x_base).fit()
        fit_aug = sm.OLS(y_train, x_aug).fit()

        current_base = pd.DataFrame([row[base_cols].astype(float).values], columns=base_cols, index=[date])
        current_aug = pd.DataFrame([row[aug_cols].astype(float).values], columns=aug_cols, index=[date])
        current_base = sm.add_constant(current_base, has_constant="add")
        current_aug = sm.add_constant(current_aug, has_constant="add")

        pred_base = float(np.exp(fit_base.predict(current_base).iloc[0]))
        pred_aug = float(np.exp(fit_aug.predict(current_aug).iloc[0]))
        actual = float(row[actual_col])
        rows.append(
            {
                "date": date,
                "actual": actual,
                "forecast_base": pred_base,
                "forecast_aug": pred_aug,
                "qlike_base": float(qlike(np.array([actual]), np.array([pred_base]))[0]),
                "qlike_aug": float(qlike(np.array([actual]), np.array([pred_aug]))[0]),
                "bdc_pressure_l1": float(row["bdc_pressure_l1"]),
                "bdc_rv_z_l1": float(row["bdc_rv_z_l1"]),
            }
        )

    oos = pd.DataFrame(rows)
    if oos.empty:
        raise RuntimeError(f"No OOS forecasts for {target} h={horizon}")
    oos = oos.set_index("date")
    oos["loss_diff"] = oos["qlike_base"] - oos["qlike_aug"]

    dm_t, dm_p = hac_mean_test(oos["loss_diff"], maxlags=horizon + 5)
    boot = moving_block_bootstrap_mean(oos["loss_diff"].values, seed=SEED + horizon + (0 if target == "IGV" else 100))
    base_mean = float(oos["qlike_base"].mean())
    aug_mean = float(oos["qlike_aug"].mean())
    improvement = (base_mean - aug_mean) / base_mean * 100.0 if base_mean > 0 else float("nan")
    pass_bonf = bool(improvement > 0 and dm_t > 0 and dm_p < BONFERRONI_ALPHA)
    cond = bool(improvement > 0 and dm_t > 0 and dm_p < 0.05)
    result = ForecastResult(
        target=target,
        horizon=horizon,
        n_oos=int(len(oos)),
        baseline_qlike=base_mean,
        augmented_qlike=aug_mean,
        qlike_improvement_pct=float(improvement),
        dm_t=float(dm_t),
        dm_p_two_sided=float(dm_p),
        bootstrap_mean_diff=float(boot["mean"]),
        bootstrap_ci95=[float(x) for x in boot["ci95"]],
        bootstrap_p_improve=float(boot["p_improve"]),
        passes_bonferroni=pass_bonf,
        conditional_pass=cond,
    )
    return result, oos


def select_stress_events(panel: pd.DataFrame) -> list[pd.Timestamp]:
    threshold = panel["bdc_pressure"].rolling(756, min_periods=504).quantile(0.90).shift(1)
    signal = panel["bdc_pressure"].shift(1)
    events: list[pd.Timestamp] = []
    last_pos = -10_000
    for pos, date in enumerate(panel.index):
        if date < OOS_START:
            continue
        val = signal.iloc[pos]
        thr = threshold.iloc[pos]
        if not np.isfinite(val) or not np.isfinite(thr):
            continue
        if val > thr and pos - last_pos > EVENT_COOLDOWN:
            events.append(date)
            last_pos = pos
    return events


def event_summary(panel: pd.DataFrame, events: list[pd.Timestamp]) -> dict:
    out = {"n_events": len(events), "cooldown_days": EVENT_COOLDOWN, "by_target": {}}
    event_index = pd.Index(events)
    rng = np.random.default_rng(SEED)
    for target in TARGETS:
        target_out = {}
        for h in HORIZONS:
            col = f"{target}_fwd_var_{h}"
            oos = panel.loc[panel.index >= OOS_START, col].dropna()
            ev = oos[oos.index.isin(event_index)].dropna()
            non = oos[~oos.index.isin(event_index)].dropna()
            if len(ev) < 2 or len(non) < 10:
                target_out[str(h)] = {"n_event_obs": int(len(ev))}
                continue
            diffs = np.empty(BOOTSTRAP_REPS)
            ev_vals = ev.values
            non_vals = non.values
            for r in range(BOOTSTRAP_REPS):
                ev_s = rng.choice(ev_vals, size=len(ev_vals), replace=True)
                non_s = rng.choice(non_vals, size=len(ev_vals), replace=True)
                diffs[r] = ev_s.mean() - non_s.mean()
            target_out[str(h)] = {
                "n_event_obs": int(len(ev)),
                "event_mean_var": float(ev.mean()),
                "non_event_mean_var": float(non.mean()),
                "event_minus_non_event": float(ev.mean() - non.mean()),
                "bootstrap_ci95": [float(x) for x in np.percentile(diffs, [2.5, 97.5])],
                "bootstrap_p_gt_0": float((np.sum(diffs <= 0.0) + 1) / (BOOTSTRAP_REPS + 1)),
            }
        out["by_target"][target] = target_out
    return out


def make_figures(results: list[ForecastResult], forecasts: dict[tuple[str, int], pd.DataFrame]) -> list[str]:
    paths: list[str] = []
    labels = [f"{r.target} h={r.horizon}" for r in results]
    improvements = [r.qlike_improvement_pct for r in results]
    colors = ["#2f6f8f" if r.target == "IGV" else "#8a5a2b" for r in results]

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.bar(labels, improvements, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    y_min = min(0.0, min(improvements) - 1.0)
    y_max = max(0.0, max(improvements) + 1.8)
    ax.set_ylim(y_min, y_max)
    for i, r in enumerate(results):
        text = f"t={r.dm_t:.2f}\np={r.dm_p_two_sided:.3f}"
        offset = 0.25 if improvements[i] >= 0 else -0.25
        ax.text(
            i,
            improvements[i] + offset,
            text,
            ha="center",
            va="bottom" if improvements[i] >= 0 else "top",
            fontsize=8,
        )
    ax.set_ylabel("OOS QLIKE improvement vs HAR+market baseline (%)")
    ax.set_title("K1344: Does lagged BDC stress improve IGV/HYG forward-RV forecasts?")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig_path = os.path.join(OUT_DIR, "fig_qlike_improvement.png")
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)
    paths.append(fig_path)

    fig, ax = plt.subplots(figsize=(10, 5))
    for target, color in [("IGV", "#2f6f8f"), ("HYG", "#8a5a2b")]:
        oos = forecasts[(target, 21)]
        cumulative = oos["loss_diff"].cumsum()
        ax.plot(cumulative.index, cumulative.values, label=f"{target} h=21", color=color, linewidth=1.7)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Cumulative QLIKE loss diff (baseline - augmented)")
    ax.set_title("K1344: Cumulative OOS value of BDC augmentation")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig_path = os.path.join(OUT_DIR, "fig_cumulative_lossdiff.png")
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)
    paths.append(fig_path)
    return paths


def main() -> int:
    prices = load_prices()
    panel = build_feature_panel(prices)

    results: list[ForecastResult] = []
    forecasts: dict[tuple[str, int], pd.DataFrame] = {}
    for target in TARGETS:
        for h in HORIZONS:
            result, oos = forecast_one_spec(panel, target, h)
            results.append(result)
            forecasts[(target, h)] = oos
            print(
                f"{target} h={h}: improve={result.qlike_improvement_pct:.3f}% "
                f"t={result.dm_t:.3f} p={result.dm_p_two_sided:.4f} "
                f"bonf={result.passes_bonferroni}"
            )

    events = select_stress_events(panel)
    ev_summary = event_summary(panel, events)
    figure_paths = make_figures(results, forecasts)

    igv_pass = any(r.target == "IGV" and r.passes_bonferroni for r in results)
    igv_cond = any(r.target == "IGV" and r.conditional_pass for r in results)
    hyg_signal = any(r.target == "HYG" and (r.passes_bonferroni or r.conditional_pass) for r in results)
    if igv_pass:
        verdict = "PASS"
    elif igv_cond:
        verdict = "CONDITIONAL_PASS"
    elif hyg_signal:
        verdict = "NULL_SOFTWARE_SPILLOVER_CREDIT_ONLY"
    else:
        verdict = "NULL"

    result_json = {
        "experiment_id": EXPERIMENT_ID,
        "seed": SEED,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "data": {
            "source": "yfinance auto_adjust=True daily close",
            "start": DATA_START,
            "end_exclusive": DATA_END,
            "actual_last_date": str(prices.index.max().date()),
            "tickers": {
                "bdc_proxy": BDC_TICKERS,
                "targets": TARGETS,
                "controls": CONTROL_TICKERS,
            },
            "bdc_basket_rule": "Equal-weight daily log return over available BDC proxy tickers; require at least 2 members.",
            "bdc_member_count_oos": {
                "min": int(panel.loc[panel.index >= OOS_START, "bdc_member_count"].min()),
                "median": float(panel.loc[panel.index >= OOS_START, "bdc_member_count"].median()),
                "max": int(panel.loc[panel.index >= OOS_START, "bdc_member_count"].max()),
            },
        },
        "split": {"oos_start": str(OOS_START.date()), "min_train_rows": MIN_TRAIN},
        "lookahead_controls": {
            "feature_lag": "All predictive features enter as *_l1 via .shift(1).",
            "forward_label_training_cutoff": "For horizon H, expanding OLS only trains on rows with target_end_pos < forecast_pos.",
            "target_definition": "Forward variance at row t uses daily returns t..t+H-1; feature row uses information through t-1.",
        },
        "tests": {
            "primary_family": "2 targets (IGV,HYG) x 2 horizons (5,21)",
            "n_tests": PRIMARY_TESTS,
            "bonferroni_alpha": BONFERRONI_ALPHA,
            "dm_loss_diff": "QLIKE_baseline - QLIKE_augmented; positive means BDC augmentation helps.",
            "dm_covariance": "Newey-West HAC with maxlags=horizon+5",
            "bootstrap": {"method": "moving block bootstrap of OOS loss diff", "block_size": BOOTSTRAP_BLOCK, "reps": BOOTSTRAP_REPS},
        },
        "forecast_results": [r.__dict__ for r in results],
        "event_study": ev_summary,
        "verdict": verdict,
        "verdict_rationale": {
            "igv_pass_bonferroni": igv_pass,
            "igv_conditional": igv_cond,
            "hyg_credit_signal": hyg_signal,
        },
        "literature_sources": [
            {
                "name": "Financial Stability Board, Report on vulnerabilities in private credit, 2026-05-06",
                "url": "https://www.fsb.org/2026/05/fsb-warns-on-private-credit-vulnerabilities/",
            },
            {
                "name": "Morgan Stanley, The Risks of Private Credit's Software Exposure, 2026",
                "url": "https://www.morganstanley.com/insights/podcasts/thoughts-on-the-market/private-credit-software-ai-disruption-vishy-tirupattur-vishwas-patkar",
            },
            {
                "name": "J.P. Morgan Asset Management, Tech, Software, and BDCs, 2026",
                "url": "https://am.jpmorgan.com/us/en/asset-management/institutional/insights/portfolio-insights/fixed-income/fixed-income-perspectives/tech-software-and-bdcs-navigating-volatility-and-ai-disruption-in-investment-grade-credit/",
            },
            {
                "name": "MSCI, Private Capital in Focus presentation, 2026",
                "url": "https://www.msci.com/downloads/web/msci-com/discover-msci/events/event-assets/2026/may/Presentation_%20Private%20Capital%20in%20Focus_USEurope_May132026.pdf",
            },
        ],
        "figures": [os.path.basename(p) for p in figure_paths],
        "caveats": [
            "Public BDC prices are noisy proxies, not loan-level private-credit exposure or NAV marks.",
            "BDC basket composition is dynamic because BXSL/OBDC histories start later; OOS median member count is reported.",
            "Survivorship and ticker-selection bias remain possible in listed BDC proxies.",
            "IGV is public software equity, not private SaaS borrower collateral.",
            "Result should be interpreted as incremental public-market forecasting evidence, not causal private-credit transmission.",
        ],
    }

    out_path = os.path.join(OUT_DIR, "K1344_results.json")
    with open(out_path, "w") as f:
        json.dump(result_json, f, indent=2)
    print(f"Saved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
