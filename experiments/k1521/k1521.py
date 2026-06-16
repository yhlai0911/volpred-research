"""K1521: realized kurtosis as an incremental HAR-RV predictor.

This is a short-sample intraday-data feasibility pilot, not a production
forecasting result. It uses local 5-minute CSV snapshots for SPY and 0050.TW
only; 0050.TW is a Taiwan index ETF proxy because no long TAIEX 5-minute panel
is available in this workspace.

Forecast timing:
  - Features dated t use intraday returns through the close of t.
  - Target is average realized variance over t+1 ... t+5.
  - Expanding OOS fits use rows strictly before the forecast row.

Usage:
    uv run python experiments/k1521/k1521.py
"""

from __future__ import annotations

import glob
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "k1521"
DATA_DIR = ROOT / "data" / "intraday"
SEED = 42
MIN_TRAIN = 40
HORIZON = 5
EPS = 1e-12


@dataclass(frozen=True)
class MarketSpec:
    label: str
    glob_pattern: str
    role: str


MARKETS = [
    MarketSpec("SPY", "SPY_5min_2026-*.csv", "US equity ETF"),
    MarketSpec("0050.TW", "0050_TW_5min_2026-*.csv", "Taiwan index ETF proxy"),
]


def _date_from_path(path: Path) -> pd.Timestamp:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if not m:
        raise ValueError(f"Cannot infer date from {path}")
    return pd.Timestamp(m.group(1))


def read_5min_file(path: Path) -> dict | None:
    """Read one yfinance-style 5-minute CSV and compute RV/RK."""
    frame = pd.read_csv(path, skiprows=[1, 2])
    if frame.empty or "Close" not in frame.columns:
        return None
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) < 12:
        return None

    ret = np.log(close).diff().dropna()
    ret = ret[np.isfinite(ret)]
    n = int(len(ret))
    if n < 10:
        return None

    rv = float(np.sum(np.square(ret)))
    if rv <= EPS:
        return None
    r4 = float(np.sum(np.power(ret, 4)))
    rk = float(n * r4 / (rv * rv))

    return {
        "date": _date_from_path(path),
        "n_5min_returns": n,
        "rv": rv,
        "rk": rk,
        "close_first": float(close.iloc[0]),
        "close_last": float(close.iloc[-1]),
    }


def build_daily_panel(spec: MarketSpec) -> pd.DataFrame:
    rows = []
    for name in sorted(glob.glob(str(DATA_DIR / spec.glob_pattern))):
        row = read_5min_file(Path(name))
        if row is not None:
            rows.append(row)
    if not rows:
        raise ValueError(f"No valid rows for {spec.label}")

    frame = pd.DataFrame(rows).sort_values("date").set_index("date")
    frame["log_rv_d"] = np.log(frame["rv"].clip(lower=EPS))
    frame["rv_w"] = frame["rv"].rolling(5, min_periods=3).mean()
    frame["rv_m"] = frame["rv"].rolling(22, min_periods=10).mean()
    frame["log_rv_w"] = np.log(frame["rv_w"].clip(lower=EPS))
    frame["log_rv_m"] = np.log(frame["rv_m"].clip(lower=EPS))
    frame["log_rk_d"] = np.log(frame["rk"].clip(lower=EPS))
    frame["rk_w"] = frame["rk"].rolling(5, min_periods=3).mean()
    frame["log_rk_w"] = np.log(frame["rk_w"].clip(lower=EPS))

    target = sum(frame["rv"].shift(-i) for i in range(1, HORIZON + 1)) / HORIZON
    frame["target_5d_avg_rv"] = target
    frame["log_target_5d_avg_rv"] = np.log(frame["target_5d_avg_rv"].clip(lower=EPS))
    return frame


def _design_matrix(frame: pd.DataFrame, cols: list[str]) -> np.ndarray:
    x = frame[cols].to_numpy(dtype=float)
    return np.column_stack([np.ones(len(frame)), x])


def expanding_log_ols_forecast(
    frame: pd.DataFrame,
    feature_cols: list[str],
    min_train: int = MIN_TRAIN,
) -> pd.Series:
    preds: list[tuple[pd.Timestamp, float]] = []
    clean = frame.dropna(subset=feature_cols + ["log_target_5d_avg_rv"]).copy()
    if len(clean) <= min_train + 5:
        return pd.Series(dtype=float, name="forecast")

    for i in range(min_train, len(clean)):
        train = clean.iloc[:i]
        test = clean.iloc[[i]]
        x_train = _design_matrix(train, feature_cols)
        y_train = train["log_target_5d_avg_rv"].to_numpy(dtype=float)
        beta, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
        resid = y_train - x_train @ beta
        resid_var = float(np.var(resid, ddof=min(len(beta), len(resid) - 1)))
        pred_log = float(_design_matrix(test, feature_cols)[0] @ beta)
        pred = math.exp(pred_log + 0.5 * max(resid_var, 0.0))
        preds.append((test.index[0], max(pred, EPS)))

    return pd.Series(dict(preds), name="forecast")


def evaluate_market(spec: MarketSpec) -> dict:
    panel = build_daily_panel(spec)
    har_cols = ["log_rv_d", "log_rv_w", "log_rv_m"]
    rk_cols = har_cols + ["log_rk_d", "log_rk_w"]

    har = expanding_log_ols_forecast(panel, har_cols)
    rk = expanding_log_ols_forecast(panel, rk_cols)
    joined = pd.concat(
        [
            panel["target_5d_avg_rv"].rename("actual"),
            panel["rv"].rename("lagged_rv"),
            panel["rk"].rename("lagged_rk"),
            har.rename("HAR"),
            rk.rename("HAR_RK"),
        ],
        axis=1,
    ).dropna()

    if len(joined) < 10:
        raise ValueError(f"Insufficient OOS rows for {spec.label}: {len(joined)}")

    loss_har = qlike_pointwise(joined["actual"].to_numpy(), joined["HAR"].to_numpy())
    loss_rk = qlike_pointwise(joined["actual"].to_numpy(), joined["HAR_RK"].to_numpy())
    qlike_har = float(np.mean(loss_har))
    qlike_rk = float(np.mean(loss_rk))
    improvement = (qlike_har - qlike_rk) / abs(qlike_har) * 100 if abs(qlike_har) > EPS else float("nan")
    dm_t, dm_p = dm_test(loss_rk, loss_har, h=HORIZON)

    regimes = {}
    threshold = float(joined["lagged_rv"].median())
    for name, mask in {
        "low_lagged_rv": joined["lagged_rv"] <= threshold,
        "high_lagged_rv": joined["lagged_rv"] > threshold,
    }.items():
        sub = joined.loc[mask]
        if len(sub) < 10:
            regimes[name] = {"n": int(len(sub)), "note": "too few OOS rows"}
            continue
        lh = qlike_pointwise(sub["actual"].to_numpy(), sub["HAR"].to_numpy())
        lr = qlike_pointwise(sub["actual"].to_numpy(), sub["HAR_RK"].to_numpy())
        regimes[name] = {
            "n": int(len(sub)),
            "qlike_har": float(np.mean(lh)),
            "qlike_har_rk": float(np.mean(lr)),
            "qlike_improvement_pct": float((np.mean(lh) - np.mean(lr)) / abs(np.mean(lh)) * 100),
            "dm_t_har_rk_vs_har": float(dm_test(lr, lh, h=HORIZON)[0]),
            "dm_p": float(dm_test(lr, lh, h=HORIZON)[1]),
        }

    oos_path = OUT / f"{spec.label.replace('.', '_')}_oos_forecasts.csv"
    joined.to_csv(oos_path, index_label="date")

    return {
        "market": spec.label,
        "role": spec.role,
        "n_intraday_days": int(len(panel)),
        "date_start": str(panel.index.min().date()),
        "date_end": str(panel.index.max().date()),
        "n_oos": int(len(joined)),
        "min_train": MIN_TRAIN,
        "median_5min_returns_per_day": float(panel["n_5min_returns"].median()),
        "mean_rv": float(panel["rv"].mean()),
        "mean_rk": float(panel["rk"].mean()),
        "median_rk": float(panel["rk"].median()),
        "qlike_har": qlike_har,
        "qlike_har_rk": qlike_rk,
        "qlike_improvement_pct": float(improvement),
        "dm_t_har_rk_vs_har": float(dm_t),
        "dm_p": float(dm_p),
        "harvey_pass_abs_t_gt_3": bool(abs(dm_t) > 3.0 and improvement > 0),
        "regime_split": regimes,
        "oos_forecast_file": str(oos_path.relative_to(ROOT)),
    }


def make_plot(results: dict) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for market in results["markets"]:
        oos = pd.read_csv(ROOT / market["oos_forecast_file"], parse_dates=["date"])
        diff = qlike_pointwise(oos["actual"], oos["HAR"]) - qlike_pointwise(oos["actual"], oos["HAR_RK"])
        ax.plot(oos["date"], np.cumsum(diff), label=market["market"])
    ax.axhline(0.0, color="black", lw=0.8)
    ax.set_title("K1521 cumulative QLIKE loss reduction: HAR+RK vs HAR")
    ax.set_ylabel("Cumulative loss(HAR) - loss(HAR+RK)")
    ax.set_xlabel("Forecast date")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "k1521_cumulative_qlike_diff.png", dpi=160)
    plt.close(fig)


def determine_verdict(markets: list[dict]) -> tuple[str, str]:
    enough_oos = all(m["n_oos"] >= 252 for m in markets)
    pass_markets = [m for m in markets if m["harvey_pass_abs_t_gt_3"]]
    positive_markets = [m for m in markets if m["qlike_improvement_pct"] > 0]

    if not enough_oos:
        return (
            "NULL_INSUFFICIENT_DATA",
            "Local 5-minute panels cover only 2026 year-to-date and produce fewer than 252 OOS forecasts per market. Treat as a pipeline feasibility pilot, not evidence for or against realized kurtosis.",
        )
    if len(pass_markets) == len(markets):
        return (
            "PASS",
            "HAR+RK improves QLIKE over HAR in all markets and passes Harvey |DM t|>3.",
        )
    if positive_markets:
        return (
            "CONDITIONAL_PASS",
            "HAR+RK improves at least one market directionally, but not all markets pass Harvey |DM t|>3.",
        )
    return (
        "NULL",
        "HAR+RK does not improve QLIKE over HAR in this sample.",
    )


def main() -> dict:
    np.random.seed(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    markets = [evaluate_market(spec) for spec in MARKETS]
    verdict, summary = determine_verdict(markets)
    results = {
        "experiment_id": "K1521",
        "title": "Realized kurtosis as an incremental HAR-RV predictor",
        "date": "2026-06-17",
        "seed": SEED,
        "verdict": verdict,
        "summary": summary,
        "forecast_timing": {
            "features": "RV/RK at date t computed from local 5-minute bars through that day's close",
            "target": "average RV over t+1 through t+5",
            "oos_fit": "expanding OLS; each forecast uses only rows strictly before the forecast row",
            "lookahead": "CLEAN for the implemented forecast target; no same-day target data enters predictors",
        },
        "data": {
            "source": "local data/intraday yfinance-style 5-minute CSV snapshots",
            "markets": ["SPY", "0050.TW"],
            "taiwan_proxy_note": "0050.TW is used as a Taiwan index ETF proxy; no long TAIEX 5-minute panel was found locally.",
            "sample_limitation": "2026 year-to-date only; below the project's 252-day minimum OOS threshold.",
        },
        "models": {
            "HAR": ["log RV daily", "log RV weekly", "log RV monthly"],
            "HAR_RK": ["HAR features", "log RK daily", "log RK weekly"],
            "estimator": "log-linear OLS with expanding window and lognormal bias correction",
            "loss": "Patton QLIKE on 5-day average realized variance",
        },
        "literature_context": [
            {
                "title": "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility",
                "url": "https://ideas.repec.org/a/oup/jfinec/v7y2009i2p174-196.html",
                "use": "HAR-RV baseline and daily/weekly/monthly realized-volatility components.",
            },
            {
                "title": "Mei et al. (2017), Forecasting stock market volatility: Do realized skewness and kurtosis help?",
                "url": "https://ideas.repec.org/a/eee/phsmap/v481y2017icp153-159.html",
                "use": "Motivates testing realized skewness/kurtosis as HAR-RV extensions; reports mixed horizon-specific evidence.",
            },
            {
                "title": "Bonato et al. (2022), Forecasting realized volatility of international REITs",
                "url": "https://ideas.repec.org/a/wly/jforec/v41y2022i2p303-315.html",
                "use": "Documents cases where realized higher moments improve HAR-RV forecasts across horizons.",
            },
        ],
        "markets": markets,
        "next_steps": [
            "Acquire or build a multi-year SPY and TAIEX/TAIFEX 5-minute panel before drawing a publication-grade conclusion.",
            "Add realized skewness and jump controls in a matched horse race once the long panel exists.",
            "Keep the target as future RV t+1:t+5; do not compare HAR-RV forecasts against close-to-close r^2 without Hansen-Lunde adjustment.",
        ],
    }
    make_plot(results)
    results["figures"] = ["experiments/k1521/k1521_cumulative_qlike_diff.png"]

    with open(OUT / "k1521_results.json", "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    print(json.dumps({"verdict": verdict, "markets": markets}, ensure_ascii=False, indent=2))
    return results


if __name__ == "__main__":
    main()
