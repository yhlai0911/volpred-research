"""K1343 - BDC pressure as a private-credit shadow volatility signal.

Tests whether listed BDC/private-credit pressure predicts forward realized
variance in HYG, KRE, and IWM after own-HAR, SPY, and VIX controls.

Guardrails:
* seed = 42
* hard-coded OOS split
* every predictive feature enters with explicit .shift(1)
* forward-label training cutoff uses target_end_pos < forecast_pos
* 9 primary tests: 3 targets x 3 horizons, Bonferroni alpha = 0.05/9
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

EXPERIMENT_ID = "K1343_bdc_pressure_private_credit_vol_signal"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_START = "2013-01-01"
DATA_END = "2026-06-15"
OOS_START = pd.Timestamp("2021-01-04")

BDC_TICKERS = ["BIZD", "ARCC", "BXSL", "OBDC", "FSK"]
TARGETS = ["HYG", "KRE", "IWM"]
CONTROLS = ["SPY", "^VIX"]
ALL_TICKERS = sorted(set(BDC_TICKERS + TARGETS + CONTROLS))

HORIZONS = [5, 10, 21]
PRIMARY_TESTS = len(TARGETS) * len(HORIZONS)
BONFERRONI_ALPHA = 0.05 / PRIMARY_TESTS

MIN_TRAIN = 504
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
EVENT_COOLDOWN = 21
EPS = 1e-10


@dataclass
class SpecResult:
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
    df = yf.download(ticker, start=DATA_START, end=DATA_END, auto_adjust=True, progress=False, threads=False)
    if df.empty:
        raise RuntimeError(f"No data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    s = df["Close"].dropna().copy()
    s.name = ticker
    return s


def load_prices() -> pd.DataFrame:
    return pd.concat([download_close(t) for t in ALL_TICKERS], axis=1, sort=True).sort_index()


def rv(ret: pd.Series, window: int) -> pd.Series:
    return ret.pow(2).rolling(window, min_periods=window).mean() * 252.0


def fwd_var(ret: pd.Series, horizon: int) -> pd.Series:
    return pd.concat([ret.shift(-k).pow(2) for k in range(horizon)], axis=1).mean(axis=1) * 252.0


def qlike(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    actual = np.maximum(np.asarray(actual, dtype=float), EPS)
    forecast = np.maximum(np.asarray(forecast, dtype=float), EPS)
    ratio = actual / forecast
    return ratio - np.log(ratio) - 1.0


def hac_t_p(values: pd.Series, maxlags: int) -> tuple[float, float]:
    y = values.dropna().astype(float)
    if len(y) < 5 or y.std(ddof=1) == 0:
        return float("nan"), float("nan")
    fit = sm.OLS(y.values, np.ones((len(y), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return float(fit.tvalues[0]), float(fit.pvalues[0])


def block_bootstrap_mean(values: np.ndarray, seed: int) -> dict:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return {"mean": float("nan"), "ci95": [float("nan"), float("nan")], "p_improve": float("nan")}
    rng = np.random.default_rng(seed)
    n = len(values)
    n_blocks = int(math.ceil(n / BOOTSTRAP_BLOCK))
    max_start = max(1, n - BOOTSTRAP_BLOCK + 1)
    means = np.empty(BOOTSTRAP_REPS)
    for i in range(BOOTSTRAP_REPS):
        starts = rng.integers(0, max_start, size=n_blocks)
        sample = np.concatenate([values[s : s + BOOTSTRAP_BLOCK] for s in starts])[:n]
        means[i] = sample.mean()
    return {
        "mean": float(values.mean()),
        "ci95": [float(x) for x in np.percentile(means, [2.5, 97.5])],
        "p_improve": float((np.sum(means <= 0.0) + 1) / (BOOTSTRAP_REPS + 1)),
    }


def build_panel(prices: pd.DataFrame) -> pd.DataFrame:
    logp = np.log(prices)
    ret = logp.diff()
    panel = pd.DataFrame(index=prices.index)

    bdc_count = ret[BDC_TICKERS].notna().sum(axis=1)
    panel["bdc_member_count"] = bdc_count
    panel["bdc_ret"] = ret[BDC_TICKERS].mean(axis=1).where(bdc_count >= 2)
    panel["bdc_rv21"] = rv(panel["bdc_ret"], 21)
    panel["bdc_ret21"] = panel["bdc_ret"].rolling(21, min_periods=21).sum()

    bdc_mu = panel["bdc_rv21"].rolling(252, min_periods=126).mean()
    bdc_sd = panel["bdc_rv21"].rolling(252, min_periods=126).std()
    panel["bdc_rv_z"] = (panel["bdc_rv21"] - bdc_mu) / bdc_sd
    panel["bdc_pressure"] = (-panel["bdc_ret21"]).clip(lower=0.0) * panel["bdc_rv_z"].clip(lower=0.0)

    for ticker in TARGETS + ["SPY", "BIZD"]:
        panel[f"{ticker}_ret"] = ret[ticker]
        panel[f"{ticker}_ret21"] = ret[ticker].rolling(21, min_periods=21).sum()
        for w in [5, 21, 63]:
            panel[f"{ticker}_rv{w}"] = rv(ret[ticker], w)

    panel["vix_log"] = np.log(prices["^VIX"])
    panel["vix_chg5"] = panel["vix_log"].diff(5)
    panel["bizd_hyg_gap"] = -(panel["BIZD_ret21"] - panel["HYG_ret21"])

    for col in ["bdc_rv_z", "bdc_pressure", "bdc_ret21", "bizd_hyg_gap", "SPY_rv21", "SPY_rv63", "vix_log", "vix_chg5"]:
        panel[f"{col}_l1"] = panel[col].shift(1)

    for target in TARGETS:
        for w in [5, 21, 63]:
            panel[f"{target}_rv{w}_l1"] = panel[f"{target}_rv{w}"].shift(1)
            panel[f"log_{target}_rv{w}_l1"] = np.log(panel[f"{target}_rv{w}_l1"] + EPS)
        for h in HORIZONS:
            panel[f"{target}_fwd_var_{h}"] = fwd_var(panel[f"{target}_ret"], h)
            panel[f"{target}_log_fwd_var_{h}"] = np.log(panel[f"{target}_fwd_var_{h}"] + EPS)

    for col in ["SPY_rv21_l1", "SPY_rv63_l1"]:
        panel[f"log_{col}"] = np.log(panel[col] + EPS)

    return panel


def forecast_spec(panel: pd.DataFrame, target: str, horizon: int) -> tuple[SpecResult, pd.DataFrame]:
    base_cols = [
        f"log_{target}_rv5_l1",
        f"log_{target}_rv21_l1",
        f"log_{target}_rv63_l1",
        "log_SPY_rv21_l1",
        "log_SPY_rv63_l1",
        "vix_log_l1",
        "vix_chg5_l1",
    ]
    aug_cols = base_cols + ["bdc_rv_z_l1", "bdc_pressure_l1", "bdc_ret21_l1", "bizd_hyg_gap_l1"]
    y_col = f"{target}_log_fwd_var_{horizon}"
    actual_col = f"{target}_fwd_var_{horizon}"
    needed = [y_col, actual_col] + aug_cols

    work = panel.copy()
    work["pos"] = np.arange(len(work))
    work["target_end_pos"] = work["pos"] + horizon - 1
    rows = []

    for i, (date, row) in enumerate(work.iterrows()):
        if date < OOS_START or row[needed].isna().any():
            continue
        train = work.iloc[:i].copy()
        train = train[train["target_end_pos"] < i].dropna(subset=needed)
        if len(train) < MIN_TRAIN:
            continue
        y = train[y_col].astype(float)
        xb = sm.add_constant(train[base_cols].astype(float), has_constant="add")
        xa = sm.add_constant(train[aug_cols].astype(float), has_constant="add")
        fit_b = sm.OLS(y, xb).fit()
        fit_a = sm.OLS(y, xa).fit()

        cb = pd.DataFrame([row[base_cols].astype(float).values], columns=base_cols, index=[date])
        ca = pd.DataFrame([row[aug_cols].astype(float).values], columns=aug_cols, index=[date])
        cb = sm.add_constant(cb, has_constant="add")
        ca = sm.add_constant(ca, has_constant="add")
        pred_b = float(np.exp(fit_b.predict(cb).iloc[0]))
        pred_a = float(np.exp(fit_a.predict(ca).iloc[0]))
        actual = float(row[actual_col])
        rows.append(
            {
                "date": date,
                "actual": actual,
                "forecast_base": pred_b,
                "forecast_aug": pred_a,
                "qlike_base": float(qlike(np.array([actual]), np.array([pred_b]))[0]),
                "qlike_aug": float(qlike(np.array([actual]), np.array([pred_a]))[0]),
            }
        )

    oos = pd.DataFrame(rows)
    if oos.empty:
        raise RuntimeError(f"No OOS rows for {target} h={horizon}")
    oos = oos.set_index("date")
    oos["loss_diff"] = oos["qlike_base"] - oos["qlike_aug"]
    dm_t, dm_p = hac_t_p(oos["loss_diff"], maxlags=horizon + 5)
    boot = block_bootstrap_mean(oos["loss_diff"].values, seed=SEED + horizon + 100 * TARGETS.index(target))
    base = float(oos["qlike_base"].mean())
    aug = float(oos["qlike_aug"].mean())
    improve = (base - aug) / base * 100.0 if base > 0 else float("nan")
    pass_bonf = bool(improve > 0 and dm_t > 0 and dm_p < BONFERRONI_ALPHA)
    cond = bool(improve > 0 and dm_t > 0 and dm_p < 0.05)
    return (
        SpecResult(
            target=target,
            horizon=horizon,
            n_oos=int(len(oos)),
            baseline_qlike=base,
            augmented_qlike=aug,
            qlike_improvement_pct=float(improve),
            dm_t=float(dm_t),
            dm_p_two_sided=float(dm_p),
            bootstrap_mean_diff=float(boot["mean"]),
            bootstrap_ci95=[float(x) for x in boot["ci95"]],
            bootstrap_p_improve=float(boot["p_improve"]),
            passes_bonferroni=pass_bonf,
            conditional_pass=cond,
        ),
        oos,
    )


def select_events(panel: pd.DataFrame) -> list[pd.Timestamp]:
    signal = panel["bdc_pressure"].shift(1)
    threshold = panel["bdc_pressure"].rolling(756, min_periods=504).quantile(0.90).shift(1)
    events: list[pd.Timestamp] = []
    last_pos = -10_000
    for pos, date in enumerate(panel.index):
        if date < OOS_START:
            continue
        if pos - last_pos <= EVENT_COOLDOWN:
            continue
        val = signal.iloc[pos]
        thr = threshold.iloc[pos]
        if np.isfinite(val) and np.isfinite(thr) and val > thr:
            events.append(date)
            last_pos = pos
    return events


def event_study(panel: pd.DataFrame, events: list[pd.Timestamp]) -> dict:
    rng = np.random.default_rng(SEED)
    event_idx = pd.Index(events)
    out = {"n_events": len(events), "cooldown_days": EVENT_COOLDOWN, "target_h21": {}}
    for target in TARGETS:
        col = f"{target}_fwd_var_21"
        oos = panel.loc[panel.index >= OOS_START, col].dropna()
        ev = oos[oos.index.isin(event_idx)]
        non = oos[~oos.index.isin(event_idx)]
        if len(ev) < 2:
            out["target_h21"][target] = {"n_event_obs": int(len(ev))}
            continue
        diffs = np.empty(BOOTSTRAP_REPS)
        ev_vals = ev.values
        non_vals = non.values
        for i in range(BOOTSTRAP_REPS):
            diffs[i] = rng.choice(ev_vals, len(ev_vals), replace=True).mean() - rng.choice(non_vals, len(ev_vals), replace=True).mean()
        out["target_h21"][target] = {
            "n_event_obs": int(len(ev)),
            "event_mean_var": float(ev.mean()),
            "non_event_mean_var": float(non.mean()),
            "event_minus_non_event": float(ev.mean() - non.mean()),
            "bootstrap_ci95": [float(x) for x in np.percentile(diffs, [2.5, 97.5])],
            "bootstrap_p_gt_0": float((np.sum(diffs <= 0.0) + 1) / (BOOTSTRAP_REPS + 1)),
        }
    return out


def make_figures(results: list[SpecResult], forecasts: dict[tuple[str, int], pd.DataFrame]) -> list[str]:
    paths = []
    labels = [f"{r.target}\n{r.horizon}d" for r in results]
    vals = [r.qlike_improvement_pct for r in results]
    colors = {"HYG": "#8a5a2b", "KRE": "#2f6f8f", "IWM": "#4b7f3a"}

    fig, ax = plt.subplots(figsize=(10.5, 5))
    ax.bar(labels, vals, color=[colors[r.target] for r in results])
    ax.axhline(0, color="black", lw=0.8)
    ymin = min(0, min(vals) - 1.0)
    ymax = max(0, max(vals) + 2.0)
    ax.set_ylim(ymin, ymax)
    for i, r in enumerate(results):
        offset = 0.25 if vals[i] >= 0 else -0.25
        ax.text(i, vals[i] + offset, f"t={r.dm_t:.2f}\np={r.dm_p_two_sided:.3f}", ha="center", va="bottom" if vals[i] >= 0 else "top", fontsize=7.5)
    ax.set_ylabel("OOS QLIKE improvement vs HAR+SPY+VIX baseline (%)")
    ax.set_title("K1343: Does lagged BDC pressure improve HYG/KRE/IWM volatility forecasts?")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    p = os.path.join(OUT_DIR, "fig_qlike_improvement.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(10.5, 5))
    for target in TARGETS:
        oos = forecasts[(target, 21)]
        ax.plot(oos.index, oos["loss_diff"].cumsum(), label=f"{target} 21d", lw=1.6, color=colors[target])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Cumulative QLIKE loss diff (baseline - augmented)")
    ax.set_title("K1343: Cumulative OOS value of BDC augmentation")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = os.path.join(OUT_DIR, "fig_cumulative_lossdiff.png")
    fig.savefig(p, dpi=130)
    plt.close(fig)
    paths.append(p)
    return paths


def main() -> int:
    prices = load_prices()
    panel = build_panel(prices)
    results: list[SpecResult] = []
    forecasts: dict[tuple[str, int], pd.DataFrame] = {}
    for target in TARGETS:
        for h in HORIZONS:
            result, oos = forecast_spec(panel, target, h)
            results.append(result)
            forecasts[(target, h)] = oos
            print(f"{target} h={h}: improve={result.qlike_improvement_pct:.3f}% t={result.dm_t:.3f} p={result.dm_p_two_sided:.4f} bonf={result.passes_bonferroni}")

    events = select_events(panel)
    ev = event_study(panel, events)
    figures = make_figures(results, forecasts)

    any_pass = any(r.passes_bonferroni for r in results)
    any_cond = any(r.conditional_pass for r in results)
    if any_pass:
        verdict = "PASS"
    elif any_cond:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    output = {
        "experiment_id": EXPERIMENT_ID,
        "seed": SEED,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "data": {
            "source": "yfinance auto_adjust=True daily close",
            "start": DATA_START,
            "end_exclusive": DATA_END,
            "actual_last_date": str(prices.index.max().date()),
            "bdc_proxy_tickers": BDC_TICKERS,
            "targets": TARGETS,
            "controls": CONTROLS,
            "bdc_basket_rule": "Equal-weight daily log return over available BDC proxy tickers; require at least 2 members.",
            "bdc_member_count_oos": {
                "min": int(panel.loc[panel.index >= OOS_START, "bdc_member_count"].min()),
                "median": float(panel.loc[panel.index >= OOS_START, "bdc_member_count"].median()),
                "max": int(panel.loc[panel.index >= OOS_START, "bdc_member_count"].max()),
            },
        },
        "split": {"oos_start": str(OOS_START.date()), "min_train_rows": MIN_TRAIN},
        "lookahead_controls": {
            "feature_lag": "All predictive features enter as *_l1 via explicit .shift(1).",
            "forward_label_training_cutoff": "For horizon H, expanding OLS only trains on rows with target_end_pos < forecast_pos.",
            "target_definition": "Forward variance at row t uses returns t..t+H-1; feature row uses information through t-1.",
        },
        "multiple_testing": {"n_tests": PRIMARY_TESTS, "bonferroni_alpha": BONFERRONI_ALPHA},
        "bootstrap": {"method": "moving block bootstrap of OOS loss diff", "block_size": BOOTSTRAP_BLOCK, "reps": BOOTSTRAP_REPS},
        "forecast_results": [r.__dict__ for r in results],
        "event_study": ev,
        "verdict": verdict,
        "verdict_rationale": {
            "any_bonferroni_pass": any_pass,
            "any_conditional_pass": any_cond,
            "best_spec": max((r.__dict__ for r in results), key=lambda x: x["qlike_improvement_pct"]),
        },
        "literature_sources": [
            {
                "name": "Financial Stability Board, Report on vulnerabilities in private credit, 2026-05-06",
                "url": "https://www.fsb.org/2026/05/fsb-warns-on-private-credit-vulnerabilities/",
            },
            {
                "name": "J.P. Morgan Private Bank, Private Credit Under the Microscope, 2026",
                "url": "https://privatebank.jpmorgan.com/nam/en/insights/markets-and-investing/private-credit-under-the-microscope-separating-headlines-from-fundamentals",
            },
            {
                "name": "European Parliament briefing on private credit market structure and risks, 2026",
                "url": "https://www.europarl.europa.eu/RegData/etudes/BRIE/2026/784039/ECTI_BRI%282026%29784039_EN.pdf",
            },
            {
                "name": "Boston Fed, Could the Growth of Private Credit Pose a Risk to Financial System Stability?, 2025",
                "url": "https://www.bostonfed.org/publications/current-policy-perspectives/2025/could-the-growth-of-private-credit-pose-a-risk-to-financial-system-stability.aspx",
            },
        ],
        "figures": [os.path.basename(p) for p in figures],
        "caveats": [
            "Listed BDC prices are liquid public proxies, not true private loan marks or non-traded BDC redemption flow.",
            "BDC basket has survivorship and dynamic-composition bias because BXSL/OBDC histories start later.",
            "SPY/VIX controls reduce but do not eliminate common beta confounding.",
            "Forecast exercise measures incremental public-market predictive content, not private-credit causality.",
        ],
    }

    out = os.path.join(OUT_DIR, "K1343_results.json")
    with open(out, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
