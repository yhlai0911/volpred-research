"""Rough-volatility ARRV/fOU race on local 5-minute RV data.

This experiment resolves the backlog item:

  Rough volatility / ARRV / fractional OU race using TAIFEX/SPY 5-minute RV.

Design discipline:
- TAIFEX TX uses the existing K1100h tick-derived 5-minute cache.
- SPY uses the local 2026 yfinance 5-minute CSV archive only as a short-sample
  diagnostic. It is not treated as a submission-grade OOS test.
- All forecasts for date t use information through t-1.
- QLIKE/DM use the repo's volpred.stats.model_evaluation helpers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS_PATH = HERE / "research_rough_volatility_arrv_fractional_ou_joe_2023_fou_results.json"
FIG_PATH = HERE / "rough_vol_model_race.png"

TAIFEX_5MIN_CACHE = ROOT / "experiments/k1100h/data/_taifex_5min_2017-2021.parquet"
VIX_CSV = ROOT / "storage/sentiment/vix_historical.csv"
SPY_INTRADAY_DIR = ROOT / "data/intraday"

MAX_LAG = 66
REFIT_FREQ = 21
EPS = 1e-12

REFERENCES = [
    {
        "key": "wang_xiao_yu_2023",
        "citation": "Wang, Xiao, and Yu (2023), Journal of Econometrics 232(2), 389-415",
        "role": "fractional Ornstein-Uhlenbeck RV forecasting and change-of-frequency H estimator",
        "url": "https://doi.org/10.1016/j.jeconom.2021.08.001",
    },
    {
        "key": "bibinger_yu_zhang_2025",
        "citation": "Bibinger, Yu, and Zhang (2025), arXiv:2504.15985",
        "role": "multivariate fractional Brownian motion RV forecasting benchmark motivation",
        "url": "https://arxiv.org/abs/2504.15985",
    },
    {
        "key": "arrv_2023",
        "citation": "Volatility forecast with regularity modifications (2023), Finance Research Letters 58",
        "role": "ARRV model motivation: combine fGn-style roughness with autoregressive volatility forecasting",
        "url": "https://ideas.repec.org/a/eee/finlet/v58y2023ipas154461232300380x.html",
    },
    {
        "key": "corsi_2009",
        "citation": "Corsi (2009), Journal of Financial Econometrics 7(2), 174-196",
        "role": "HAR-RV benchmark",
        "url": "https://academic.oup.com/jfec/article-abstract/7/2/174/787440",
    },
    {
        "key": "patton_2011",
        "citation": "Patton (2011), Journal of Econometrics 160(1), 246-256",
        "role": "QLIKE forecast comparison with imperfect volatility proxies",
        "url": "https://doi.org/10.1016/j.jeconom.2010.03.034",
    },
]


@dataclass
class HurstEstimate:
    h: float
    method: str
    r2: Optional[float] = None
    se_h: Optional[float] = None
    n_points: Optional[int] = None


def _clean_positive(s: pd.Series) -> pd.Series:
    out = pd.to_numeric(s, errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    return out[out > 0]


def realized_quarticity(rets: np.ndarray) -> float:
    """Realized quarticity proxy from intraday returns."""
    rets = np.asarray(rets, dtype=float)
    rets = rets[np.isfinite(rets)]
    if len(rets) < 2:
        return np.nan
    return float((len(rets) / 3.0) * np.sum(rets ** 4))


def load_taifex_day_rv() -> pd.DataFrame:
    """Build day-session RV/RQ from the K1100h 5-minute bar cache."""
    bars = pd.read_parquet(TAIFEX_5MIN_CACHE)
    bars = bars[bars["session"] == "day"].copy()
    bars["session_date"] = pd.to_datetime(bars["session_date"])
    bars["bar_start"] = pd.to_datetime(bars["bar_start"])
    bars = bars.sort_values(["session_date", "bar_start"])

    rows = []
    for date, g in bars.groupby("session_date", sort=True):
        closes = _clean_positive(g["close"])
        if len(closes) < 20:
            continue
        rets = np.diff(np.log(closes.values))
        if len(rets) < 20:
            continue
        rows.append(
            {
                "date": pd.Timestamp(date).normalize(),
                "rv": float(np.sum(rets ** 2)),
                "rq": realized_quarticity(rets),
                "n_intraday_returns": int(len(rets)),
                "source": "experiments/k1100h/data/_taifex_5min_2017-2021.parquet",
            }
        )
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df[(df["rv"] > 0) & np.isfinite(df["rv"])].copy()


def parse_spy_5min_file(path: Path) -> Optional[dict]:
    """Parse one yfinance-style 5-minute CSV and return daily RV/RQ."""
    df = pd.read_csv(path)
    raw_time = df.get("Price").astype(str)
    valid = raw_time.str.match(r"^\d{4}-\d{2}-\d{2} ")
    if valid.sum() < 20:
        return None
    close = pd.to_numeric(df.loc[valid, "Close"], errors="coerce")
    close = close.dropna()
    close = close[close > 0]
    if len(close) < 20:
        return None
    rets = np.diff(np.log(close.values))
    date_str = path.stem.replace("SPY_5min_", "")
    return {
        "date": pd.Timestamp(date_str),
        "rv": float(np.sum(rets ** 2)),
        "rq": realized_quarticity(rets),
        "n_intraday_returns": int(len(rets)),
        "source": "data/intraday/SPY_5min_YYYY-MM-DD.csv",
    }


def load_spy_2026_rv() -> pd.DataFrame:
    rows = []
    for path in sorted(SPY_INTRADAY_DIR.glob("SPY_5min_2026-*.csv")):
        row = parse_spy_5min_file(path)
        if row is not None:
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["rv", "rq", "n_intraday_returns", "source"])
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df[(df["rv"] > 0) & np.isfinite(df["rv"])].copy()


def load_vix() -> pd.Series:
    """Load local VIX close series from yfinance-style CSV."""
    df = pd.read_csv(VIX_CSV)
    raw_date = df["Price"].astype(str)
    date_like = raw_date.str.match(r"^\d{4}-\d{2}-\d{2}$")
    dates = pd.to_datetime(raw_date.where(date_like), errors="coerce", format="%Y-%m-%d")
    close = pd.to_numeric(df["Close"], errors="coerce")
    valid = dates.notna() & close.notna()
    out = pd.Series(close.loc[valid].values, index=dates.loc[valid], name="vix")
    return out.sort_index()


def estimate_hurst_variogram(log_rv: pd.Series, max_lag: int = 20) -> HurstEstimate:
    x = log_rv.dropna().values.astype(float)
    lags = []
    moments = []
    for lag in range(1, max_lag + 1):
        if len(x) <= lag + 10:
            continue
        diff = x[lag:] - x[:-lag]
        m = np.mean(diff ** 2)
        if np.isfinite(m) and m > 0:
            lags.append(lag)
            moments.append(m)
    if len(lags) < 6:
        return HurstEstimate(h=float("nan"), method="variogram", n_points=len(lags))
    reg = stats.linregress(np.log(lags), np.log(moments))
    return HurstEstimate(
        h=float(reg.slope / 2.0),
        method="variogram",
        r2=float(reg.rvalue ** 2),
        se_h=float(reg.stderr / 2.0) if reg.stderr is not None else None,
        n_points=len(lags),
    )


def estimate_hurst_frequency_ratio(log_rv: pd.Series) -> HurstEstimate:
    """Second-difference change-of-frequency estimator inspired by fOU work.

    For fractional paths, the average squared second difference scales with
    sampling interval as Delta^(2H). Ratioing lag-2 to lag-1 moments gives H.
    """
    x = log_rv.dropna().values.astype(float)
    if len(x) < 30:
        return HurstEstimate(h=float("nan"), method="second_difference_frequency_ratio")
    d1 = x[2:] - 2.0 * x[1:-1] + x[:-2]
    d2 = x[4:] - 2.0 * x[2:-2] + x[:-4]
    m1 = float(np.mean(d1 ** 2))
    m2 = float(np.mean(d2 ** 2))
    if m1 <= 0 or m2 <= 0 or not np.isfinite(m1) or not np.isfinite(m2):
        return HurstEstimate(h=float("nan"), method="second_difference_frequency_ratio")
    h = 0.5 * math.log(m2 / m1, 2)
    return HurstEstimate(
        h=float(h),
        method="second_difference_frequency_ratio",
        n_points=int(min(len(d1), len(d2))),
    )


def fractional_weights(h: float, max_lag: int = MAX_LAG) -> np.ndarray:
    h_use = float(np.clip(h if np.isfinite(h) else 0.1, 0.01, 0.49))
    k = np.arange(1, max_lag + 1, dtype=float)
    w = k ** (h_use - 0.5)
    w = w / np.sum(w)
    return w


def build_feature_row(
    model: str,
    log_rv: np.ndarray,
    rq: np.ndarray,
    t: int,
    h: float,
    train_mean: float,
    max_lag: int = MAX_LAG,
) -> List[float]:
    lag1 = float(log_rv[t - 1])
    lag5 = float(np.mean(log_rv[t - 5:t]))
    lag22 = float(np.mean(log_rv[t - 22:t]))

    if model == "HAR":
        return [lag1, lag5, lag22]

    if model == "HARQ":
        rq_lag = float(max(rq[t - 1], EPS))
        return [lag1, lag5, lag22, lag1 * math.log(rq_lag)]

    if model == "ARRV":
        w = fractional_weights(h, max_lag)
        frac = float(np.dot(w, log_rv[t - max_lag:t][::-1]))
        return [lag1, frac]

    if model == "fOU_lite":
        w = fractional_weights(h, max_lag)
        frac_dev = float(np.dot(w, (log_rv[t - max_lag:t][::-1] - train_mean)))
        return [frac_dev]

    raise ValueError(f"Unknown model {model}")


def fit_standardized_ols(y: np.ndarray, x: np.ndarray) -> dict:
    x_mean = x.mean(axis=0)
    x_std = x.std(axis=0)
    x_std[x_std < 1e-12] = 1.0
    xs = (x - x_mean) / x_std
    design = np.column_stack([np.ones(len(xs)), xs])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    resid = y - design @ beta
    return {
        "beta": beta,
        "x_mean": x_mean,
        "x_std": x_std,
        "resid_var": float(np.var(resid, ddof=max(1, x.shape[1]))),
    }


def forecast_with_fit(fit: dict, row: Iterable[float]) -> float:
    x = np.asarray(list(row), dtype=float)
    xs = (x - fit["x_mean"]) / fit["x_std"]
    pred_log = float(np.r_[1.0, xs] @ fit["beta"])
    return float(max(math.exp(pred_log + 0.5 * fit["resid_var"]), EPS))


def fit_model_for_pos(
    model: str,
    log_rv: np.ndarray,
    rq: np.ndarray,
    pos: int,
    h: float,
    max_lag: int = MAX_LAG,
) -> Optional[dict]:
    start = max(22, max_lag)
    if pos <= start + 50:
        return None
    train_mean = float(np.mean(log_rv[:pos]))
    rows = []
    y = []
    for t in range(start, pos):
        row = build_feature_row(model, log_rv, rq, t, h, train_mean, max_lag=max_lag)
        if np.all(np.isfinite(row)) and np.isfinite(log_rv[t]):
            rows.append(row)
            y.append(float(log_rv[t]))
    if len(y) < 50:
        return None
    fit = fit_standardized_ols(np.asarray(y), np.asarray(rows))
    fit["h"] = float(h)
    fit["train_mean"] = train_mean
    return fit


def oos_model_race(
    panel: pd.DataFrame,
    oos_start: str,
    min_train: int,
    vix: Optional[pd.Series] = None,
    formal: bool = True,
    max_lag: int = MAX_LAG,
) -> dict:
    panel = panel[["rv", "rq"]].dropna().copy()
    panel = panel[(panel["rv"] > 0) & (panel["rq"] > 0)]
    dates = panel.index
    rv = panel["rv"].values.astype(float)
    rq = panel["rq"].values.astype(float)
    log_rv = np.log(np.maximum(rv, EPS))

    oos_idx = int(dates.searchsorted(pd.Timestamp(oos_start)))
    oos_idx = max(oos_idx, min_train, max(22, max_lag) + 50)
    models = ["HAR", "HARQ", "ARRV", "fOU_lite"]

    actual = []
    eval_dates = []
    forecasts = {m: [] for m in models}
    h_path = []
    last_fit_pos = -10**9
    fits: Dict[str, dict] = {}

    for pos in range(oos_idx, len(panel)):
        if pos - last_fit_pos >= REFIT_FREQ or not fits:
            h_train = estimate_hurst_frequency_ratio(pd.Series(log_rv[:pos])).h
            if not np.isfinite(h_train):
                h_train = estimate_hurst_variogram(pd.Series(log_rv[:pos])).h
            h_train = float(np.clip(h_train if np.isfinite(h_train) else 0.1, 0.01, 0.49))
            fits = {}
            for model in models:
                fit = fit_model_for_pos(model, log_rv, rq, pos, h_train, max_lag=max_lag)
                if fit is not None:
                    fits[model] = fit
            last_fit_pos = pos
        if set(models) - set(fits):
            continue

        actual.append(float(rv[pos]))
        eval_dates.append(pd.Timestamp(dates[pos]))
        for model in models:
            row = build_feature_row(
                model,
                log_rv,
                rq,
                pos,
                fits[model]["h"],
                fits[model]["train_mean"],
                max_lag=max_lag,
            )
            forecasts[model].append(forecast_with_fit(fits[model], row))
        h_path.append(float(fits["HAR"]["h"]))

    if not actual:
        return {
            "formal_oos": formal,
            "n_oos": 0,
            "error": "No OOS forecasts generated",
        }

    actual_arr = np.asarray(actual, dtype=float)
    forecast_arr = {m: np.asarray(v, dtype=float) for m, v in forecasts.items()}
    losses = {m: qlike_pointwise(actual_arr, forecast_arr[m]) for m in models}
    qlikes = {m: float(qlike(actual_arr, forecast_arr[m])) for m in models}

    dm_vs_har = {}
    for model in models:
        if model == "HAR":
            continue
        t_stat, p_val = dm_test(losses[model], losses["HAR"], h=1)
        dm_vs_har[model] = {
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "harvey_sig": bool(abs(t_stat) > 3.0),
            "sign_convention": "negative => candidate lower QLIKE loss than HAR",
        }

    high_vix_summary = None
    if vix is not None:
        vix_aligned = vix.reindex(pd.DatetimeIndex(eval_dates), method=None)
        mask = (vix_aligned >= 20.0).fillna(False).values
        if int(mask.sum()) >= 20:
            high_vix_summary = {
                "threshold": "VIX >= 20",
                "n": int(mask.sum()),
                "qlike": {
                    m: float(qlike(actual_arr[mask], forecast_arr[m][mask]))
                    for m in models
                },
            }
            high_dm = {}
            for model in models:
                if model == "HAR":
                    continue
                t_stat, p_val = dm_test(losses[model][mask], losses["HAR"][mask], h=1)
                high_dm[model] = {
                    "t_stat": float(t_stat),
                    "p_value": float(p_val),
                    "harvey_sig": bool(abs(t_stat) > 3.0),
                    "sign_convention": "negative => candidate lower QLIKE loss than HAR",
                }
            high_vix_summary["dm_vs_har"] = high_dm
        else:
            high_vix_summary = {
                "threshold": "VIX >= 20",
                "n": int(mask.sum()),
                "status": "too_few_high_vix_oos_days_for_regime_dm",
            }

    best = min(qlikes, key=qlikes.get)
    rough_models = ["ARRV", "fOU_lite"]
    rough_better = [m for m in rough_models if qlikes[m] < qlikes["HAR"]]
    rough_harvey = [
        m
        for m in rough_models
        if dm_vs_har[m]["t_stat"] < 0 and dm_vs_har[m]["harvey_sig"]
    ]

    return {
        "formal_oos": formal,
        "n_oos": int(len(actual_arr)),
        "start": str(eval_dates[0].date()),
        "end": str(eval_dates[-1].date()),
        "min_train": int(min_train),
        "fractional_kernel_max_lag": int(max_lag),
        "refit_freq_days": REFIT_FREQ,
        "models": models,
        "qlike": qlikes,
        "best_model_by_qlike": best,
        "dm_vs_har": dm_vs_har,
        "high_vix_regime": high_vix_summary,
        "h_train_path": {
            "mean": float(np.mean(h_path)),
            "min": float(np.min(h_path)),
            "max": float(np.max(h_path)),
            "n_oos_forecast_days": int(len(h_path)),
        },
        "summary": {
            "rough_models_with_lower_qlike_than_har": rough_better,
            "rough_models_harvey_significant_vs_har": rough_harvey,
            "any_rough_harvey_pass": bool(len(rough_harvey) > 0),
        },
    }


def summarize_hurst(panel: pd.DataFrame) -> dict:
    log_rv = np.log(panel["rv"])
    variogram = estimate_hurst_variogram(log_rv)
    freq = estimate_hurst_frequency_ratio(log_rv)

    n = len(log_rv)
    subperiods = {}
    for i, (lo, hi) in enumerate([(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)], start=1):
        segment = log_rv.iloc[lo:hi]
        subperiods[f"tercile_{i}"] = {
            "start": str(segment.index[0].date()) if len(segment) else None,
            "end": str(segment.index[-1].date()) if len(segment) else None,
            "frequency_ratio_H": float(estimate_hurst_frequency_ratio(segment).h),
            "variogram_H": float(estimate_hurst_variogram(segment).h),
        }

    return {
        "full_sample": {
            "frequency_ratio_H": float(freq.h),
            "variogram_H": float(variogram.h),
            "variogram_r2": variogram.r2,
            "variogram_se_H": variogram.se_h,
            "is_rough_by_frequency_ratio": bool(freq.h < 0.5),
            "is_rough_by_variogram": bool(variogram.h < 0.5),
        },
        "subperiods": subperiods,
    }


def make_figure(results: dict) -> None:
    datasets = ["TAIFEX_TX_day_5min", "SPY_2026_5min_short"]
    labels = ["TAIFEX", "SPY 2026"]
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.6))

    h_freq = [results["datasets"][d]["hurst"]["full_sample"]["frequency_ratio_H"] for d in datasets]
    h_var = [results["datasets"][d]["hurst"]["full_sample"]["variogram_H"] for d in datasets]
    x = np.arange(len(datasets))
    width = 0.35
    axes[0].bar(x - width / 2, h_freq, width, label="Frequency ratio H", color="#2F6B9A")
    axes[0].bar(x + width / 2, h_var, width, label="Variogram H", color="#E07A5F")
    axes[0].axhline(0.5, color="black", linestyle="--", linewidth=1)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels)
    axes[0].set_ylabel("Hurst estimate")
    axes[0].set_title("5-minute RV roughness")
    axes[0].legend(frameon=False)

    taifex_q = results["datasets"]["TAIFEX_TX_day_5min"]["oos_model_race"]["qlike"]
    models = list(taifex_q)
    vals = [taifex_q[m] for m in models]
    colors = ["#4C78A8" if m == "HAR" else "#59A14F" if m in ("ARRV", "fOU_lite") else "#F28E2B" for m in models]
    axes[1].bar(np.arange(len(models)), vals, color=colors)
    axes[1].set_xticks(np.arange(len(models)))
    axes[1].set_xticklabels(models, rotation=25, ha="right")
    axes[1].set_ylabel("QLIKE")
    axes[1].set_title("TAIFEX formal OOS model race")
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    taifex = load_taifex_day_rv()
    spy = load_spy_2026_rv()
    vix = load_vix()

    taifex_oos = oos_model_race(
        taifex,
        oos_start="2020-01-01",
        min_train=500,
        vix=vix,
        formal=True,
        max_lag=66,
    )
    spy_oos = oos_model_race(
        spy,
        oos_start="2026-05-01",
        min_train=60,
        vix=vix,
        formal=False,
        max_lag=22,
    )

    datasets = {
        "TAIFEX_TX_day_5min": {
            "sample": {
                "source": str(TAIFEX_5MIN_CACHE.relative_to(ROOT)),
                "start": str(taifex.index[0].date()),
                "end": str(taifex.index[-1].date()),
                "n_days": int(len(taifex)),
                "median_intraday_returns_per_day": float(taifex["n_intraday_returns"].median()),
            },
            "rv_definition": "day-session realized variance from 5-minute TX futures bar-close log returns",
            "hurst": summarize_hurst(taifex),
            "oos_model_race": taifex_oos,
        },
        "SPY_2026_5min_short": {
            "sample": {
                "source": "data/intraday/SPY_5min_2026-*.csv",
                "start": str(spy.index[0].date()) if len(spy) else None,
                "end": str(spy.index[-1].date()) if len(spy) else None,
                "n_days": int(len(spy)),
                "median_intraday_returns_per_day": float(spy["n_intraday_returns"].median()) if len(spy) else None,
            },
            "rv_definition": "US regular-session yfinance 5-minute realized variance; local archive only covers 2026 YTD",
            "hurst": summarize_hurst(spy) if len(spy) else {},
            "oos_model_race": spy_oos,
            "formal_inference_status": "diagnostic_only_n_below_252_oos_days",
        },
    }

    taifex_rough_pass = taifex_oos.get("summary", {}).get("any_rough_harvey_pass", False)
    conclusion = (
        "TAIFEX 5-minute RV is rough by Hurst diagnostics, but the rough-volatility "
        "ARRV/fOU-lite forecasts do not clear the Harvey |t|>3 contribution bar "
        "against plain HAR in the formal OOS race."
        if not taifex_rough_pass
        else
        "TAIFEX 5-minute RV roughness translates into a Harvey-significant OOS gain for at least one rough model."
    )

    results = {
        "experiment_id": "research_rough_volatility_arrv_fractional_ou_joe_2023_fou",
        "title": "Rough Volatility ARRV/fOU Race on Local 5-Minute RV",
        "timestamp_utc": pd.Timestamp.now("UTC").isoformat(),
        "seed": SEED,
        "task_id": "research_rough_volatility_arrv_fractional_ou_joe_2023_fou",
        "references": REFERENCES,
        "datasets": datasets,
        "primary_test": {
            "dataset": "TAIFEX_TX_day_5min",
            "oos_start": "2020-01-01",
            "target": "5-minute realized variance",
            "loss": "QLIKE",
            "statistical_gate": "Harvey multiple-testing heuristic |DM t| > 3.0",
        },
        "conclusion": conclusion,
        "research_implication": (
            "This is another measurement-versus-allocation result: local 5-minute RV makes roughness visible "
            "in the daily sequence of realized-variance estimates, "
            "but in this bounded sample roughness does not yet beat the HAR ceiling as a forecasting signal. "
            "A publishable rough-vol result would need either a longer SPY 5-minute archive or a stronger "
            "multivariate channel than the univariate ARRV/fOU-lite proxies used here."
        ),
        "limitations": [
            "ARRV and fOU are transparent lite approximations, not full structural maximum-likelihood implementations.",
            "TAIFEX test uses day-session futures RV only; night-session and contract-roll variants are left for follow-up.",
            "SPY local 5-minute archive has 114 raw files and 113 valid parsed sample days in 2026; it is diagnostic rather than formal.",
            "VIX high-regime analysis uses local VIX history; missing 2026-03-18 onward VIX prevents a SPY high-VIX OOS split.",
        ],
        "outputs": {
            "results_json": str(RESULTS_PATH.relative_to(ROOT)),
            "figure": str(FIG_PATH.relative_to(ROOT)),
        },
    }

    make_figure(results)
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({
        "taifex_n_oos": taifex_oos.get("n_oos"),
        "taifex_best_model": taifex_oos.get("best_model_by_qlike"),
        "taifex_rough_harvey_pass": taifex_rough_pass,
        "spy_status": spy_oos.get("formal_oos"),
        "conclusion": conclusion,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
