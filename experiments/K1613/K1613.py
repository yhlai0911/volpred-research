"""K1613: noise-robust realized measures as HAR-RV inputs.

Question
--------
Do microstructure-noise / jump-robust realized measures improve one-day-ahead
HAR forecasts beyond the standard 5-minute realized-variance HAR baseline?

Primary design
--------------
All models forecast the same target: next-day standard 5-minute realized
variance.  Alternative realized measures replace the HAR input series; they are
not allowed to change the target, which avoids a mechanical "measure predicts
itself" advantage.

Formal market:
    TAIFEX TX day-session 5-minute bar cache from K1100h, 2017-2021.

Diagnostic market:
    Local SPY 5-minute yfinance archive, 2026 snapshot only.  It is below the
    252-OOS gate and is not treated as formal evidence.

Lookahead policy
----------------
For forecast date t, all HAR features are built from realized measures through
t-1 only via explicit shift(1).  Expanding OOS fits each forecast using rows
strictly before t.

Seed: 42 for MCS bootstrap.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from volpred.stats.mcs import model_confidence_set
from volpred.stats.model_evaluation import dm_test, qlike_pointwise


EXPERIMENT_ID = "K1613"
SEED = 42
EPS = 1e-12
HARVEY_THRESHOLD = 3.0
MCS_ALPHA = 0.10
MCS_BOOT = 1000

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

TAIFEX_5MIN_CACHE = ROOT / "experiments/k1100h/data/_taifex_5min_2017-2021.parquet"
SPY_INTRADAY_DIR = ROOT / "data/intraday"


REFERENCES = [
    {
        "key": "barndorff_nielsen_hansen_lunde_shephard_2008",
        "citation": "Barndorff-Nielsen, Hansen, Lunde, and Shephard (2008), Econometrica, 'Designing Realized Kernels to Measure the Ex-Post Variation of Equity Prices in the Presence of Noise'",
        "role": "realized-kernel motivation for microstructure-noise robust integrated-variance estimation",
        "url": "https://doi.org/10.3982/ECTA6495",
    },
    {
        "key": "zhang_mykland_ait_sahalia_2005",
        "citation": "Zhang, Mykland, and Ait-Sahalia (2005), JASA, 'A Tale of Two Time Scales: Determining Integrated Volatility with Noisy High-Frequency Data'",
        "role": "two-scale realized volatility estimator",
        "url": "https://doi.org/10.1198/016214505000000169",
    },
    {
        "key": "andersen_dobrev_schaumburg_2012",
        "citation": "Andersen, Dobrev, and Schaumburg (2012), Journal of Econometrics, 'Jump-Robust Volatility Estimation Using Nearest Neighbor Truncation'",
        "role": "MedRV jump-robust realized-volatility estimator",
        "url": "https://doi.org/10.1016/j.jeconom.2012.01.011",
    },
    {
        "key": "corsi_2009",
        "citation": "Corsi (2009), Journal of Financial Econometrics, 'A Simple Approximate Long-Memory Model of Realized Volatility'",
        "role": "HAR-RV benchmark",
        "url": "https://academic.oup.com/jfec/article-abstract/7/2/174/787440",
    },
    {
        "key": "patton_2011",
        "citation": "Patton (2011), Journal of Econometrics, 'Volatility forecast comparison using imperfect volatility proxies'",
        "role": "QLIKE volatility forecast comparison",
        "url": "https://doi.org/10.1016/j.jeconom.2010.03.034",
    },
]


@dataclass(frozen=True)
class MarketConfig:
    name: str
    role: str
    source: str
    min_train: int
    oos_start: str | None = None
    gateable_min_oos: int = 252


MARKETS = [
    MarketConfig(
        name="TAIFEX_TX_day_K1100h",
        role="formal_primary",
        source="experiments/k1100h/data/_taifex_5min_2017-2021.parquet; TX1 day-session cache rebuilt after endpoint bin fix; K1613 drops third-Wednesday settlement days before forecasting",
        min_train=500,
        oos_start="2020-01-01",
        gateable_min_oos=252,
    ),
    MarketConfig(
        name="SPY_2026_local_5min",
        role="diagnostic_short_sample",
        source="data/intraday/SPY_5min_2026-*.csv collected by local yfinance cron",
        min_train=45,
        oos_start=None,
        gateable_min_oos=252,
    ),
]

MEASURE_COLUMNS = ["rv", "medrv", "rk_bartlett_h5", "tsrv_k5"]
MODEL_SPECS = {
    "HAR_RV": "rv",
    "HAR_MedRV_input": "medrv",
    "HAR_RK_input": "rk_bartlett_h5",
    "HAR_TSRV_input": "tsrv_k5",
}


def _finite_json(value):
    if isinstance(value, dict):
        return {str(k): _finite_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite_json(v) for v in value]
    if isinstance(value, tuple):
        return [_finite_json(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    return value


def clean_positive(values: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    return arr


def realized_kernel_bartlett(rets: np.ndarray, bandwidth: int = 5) -> float:
    """Simple Bartlett realised kernel / HAC variance estimator."""
    r = np.asarray(rets, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return float("nan")
    h_max = min(int(bandwidth), n - 1)
    gamma0 = float(np.sum(r * r))
    total = gamma0
    for h in range(1, h_max + 1):
        weight = 1.0 - h / (h_max + 1.0)
        gamma_h = float(np.sum(r[h:] * r[:-h]))
        total += 2.0 * weight * gamma_h
    return float(max(total, EPS))


def two_scale_rv(prices: np.ndarray, k: int = 5) -> float:
    """Zhang-Mykland-Ait-Sahalia style two-scale RV on regular bars."""
    p = clean_positive(prices)
    if len(p) < k + 5:
        return float("nan")
    logp = np.log(p)
    fine_rets = np.diff(logp)
    n = len(fine_rets)
    rv_all = float(np.sum(fine_rets * fine_rets))

    sparse_rvs = []
    sparse_counts = []
    for offset in range(k):
        sub = logp[offset::k]
        if len(sub) < 2:
            continue
        ret = np.diff(sub)
        sparse_rvs.append(float(np.sum(ret * ret)))
        sparse_counts.append(int(len(ret)))
    if not sparse_rvs:
        return float("nan")
    rv_sparse_avg = float(np.mean(sparse_rvs))
    n_bar = float(np.mean(sparse_counts))
    ratio = min(max(n_bar / max(n, 1), 0.0), 0.95)
    tsrv = (rv_sparse_avg - ratio * rv_all) / max(1.0 - ratio, 1e-6)
    return float(max(tsrv, EPS))


def median_rv(rets: np.ndarray) -> float:
    """Andersen-Dobrev-Schaumburg MedRV estimator."""
    r = np.asarray(rets, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3:
        return float("nan")
    abs_r = np.abs(r)
    triples = np.vstack([abs_r[:-2], abs_r[1:-1], abs_r[2:]]).T
    med = np.median(triples, axis=1)
    const = math.pi / (6.0 - 4.0 * math.sqrt(3.0) + math.pi)
    return float(max(const * (n / (n - 2.0)) * np.sum(med * med), EPS))


def measures_from_prices(date: pd.Timestamp, prices: Iterable[float], source: str, n_bars: int | None = None) -> dict | None:
    prices_arr = clean_positive(prices)
    if len(prices_arr) < 20:
        return None
    rets = np.diff(np.log(prices_arr))
    rets = rets[np.isfinite(rets)]
    if len(rets) < 20:
        return None
    rv = float(np.sum(rets * rets))
    if not math.isfinite(rv) or rv <= EPS:
        return None
    return {
        "date": pd.Timestamp(date).normalize(),
        "rv": rv,
        "medrv": median_rv(rets),
        "rk_bartlett_h5": realized_kernel_bartlett(rets, bandwidth=5),
        "tsrv_k5": two_scale_rv(prices_arr, k=5),
        "ret": float(np.sum(rets)),
        "n_bars": int(n_bars if n_bars is not None else len(prices_arr)),
        "n_returns": int(len(rets)),
        "source": source,
    }


def is_taifex_third_wednesday(date: pd.Timestamp) -> bool:
    ts = pd.Timestamp(date)
    return bool(ts.weekday() == 2 and 15 <= ts.day <= 21)


def load_taifex_k1100h_day() -> pd.DataFrame:
    bars = pd.read_parquet(TAIFEX_5MIN_CACHE)
    bars = bars[bars["session"] == "day"].copy()
    bars["session_date"] = pd.to_datetime(bars["session_date"])
    bars["bar_start"] = pd.to_datetime(bars["bar_start"])
    bars = bars.sort_values(["session_date", "bar_start"])
    rows = []
    for date, group in bars.groupby("session_date", sort=True):
        closes = clean_positive(group["close"])
        row = measures_from_prices(
            pd.Timestamp(date),
            closes,
            source="experiments/k1100h/data/_taifex_5min_2017-2021.parquet",
            n_bars=len(closes),
        )
        if row is not None:
            row["contract_mo"] = str(group["contract_mo"].iloc[0]) if "contract_mo" in group else None
            rows.append(row)
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    out["is_settlement_day"] = out["date"].map(is_taifex_third_wednesday)
    out = out.loc[~out["is_settlement_day"]].copy()
    return out.dropna(subset=MEASURE_COLUMNS)


def _date_from_spy_path(path: Path) -> pd.Timestamp:
    match = re.search(r"SPY_5min_(\d{4}-\d{2}-\d{2})\.csv$", path.name)
    if not match:
        raise ValueError(f"Cannot infer date from {path.name}")
    return pd.Timestamp(match.group(1))


def read_yfinance_5min_close(path: Path) -> np.ndarray:
    frame = pd.read_csv(path, skiprows=[1, 2])
    if "Close" not in frame.columns:
        return np.array([])
    close = pd.to_numeric(frame["Close"], errors="coerce")
    return clean_positive(close)


def load_spy_local_5min() -> pd.DataFrame:
    rows = []
    for path in sorted(SPY_INTRADAY_DIR.glob("SPY_5min_2026-*.csv")):
        closes = read_yfinance_5min_close(path)
        row = measures_from_prices(
            _date_from_spy_path(path),
            closes,
            source="data/intraday/SPY_5min_2026-*.csv",
            n_bars=len(closes),
        )
        if row is not None:
            rows.append(row)
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return out.dropna(subset=MEASURE_COLUMNS)


def add_har_features(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy().sort_values("date").reset_index(drop=True)
    for col in MEASURE_COLUMNS:
        d[col] = pd.to_numeric(d[col], errors="coerce").clip(lower=EPS)
        lag = d[col].shift(1)
        d[f"log_{col}_d"] = np.log(lag)
        d[f"log_{col}_w"] = np.log(lag.rolling(5, min_periods=5).mean())
        d[f"log_{col}_m"] = np.log(lag.rolling(22, min_periods=22).mean())
    d["log_target_rv"] = np.log(d["rv"].clip(lower=EPS))
    required = []
    for measure in MEASURE_COLUMNS:
        required.extend([f"log_{measure}_d", f"log_{measure}_w", f"log_{measure}_m"])
    return d.dropna(subset=required + ["rv", "log_target_rv"]).reset_index(drop=True)


def fit_predict_log_ols(train: pd.DataFrame, test: pd.Series, cols: list[str]) -> tuple[float, float]:
    x_train = train[cols].to_numpy(dtype=float)
    x_train = np.column_stack([np.ones(len(x_train)), x_train])
    y_train = train["log_target_rv"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
    resid = y_train - x_train @ beta
    denom = max(len(resid) - len(beta), 1)
    resid_var = float(np.sum(resid * resid) / denom)
    x_test = np.array([1.0] + [float(test[col]) for col in cols])
    pred_log = float(x_test @ beta)
    pred = math.exp(np.clip(pred_log + 0.5 * max(resid_var, 0.0), -40, 5))
    return max(pred, EPS), resid_var


def expanding_oos_forecasts(features: pd.DataFrame, config: MarketConfig) -> pd.DataFrame:
    start_pos = int(config.min_train)
    if config.oos_start is not None:
        positions = np.flatnonzero(pd.to_datetime(features["date"]) >= pd.Timestamp(config.oos_start))
        if len(positions):
            start_pos = max(start_pos, int(positions[0]))
    if len(features) <= start_pos + 5:
        raise ValueError(f"{config.name}: insufficient rows after warm-up; rows={len(features)} start={start_pos}")

    rows = []
    for pos in range(start_pos, len(features)):
        train = features.iloc[:pos]
        test = features.iloc[pos]
        row: dict[str, object] = {
            "date": str(pd.Timestamp(test["date"]).date()),
            "actual_rv": float(test["rv"]),
            "position": int(pos),
        }
        for model_name, measure in MODEL_SPECS.items():
            cols = [f"log_{measure}_d", f"log_{measure}_w", f"log_{measure}_m"]
            pred, resid_var = fit_predict_log_ols(train, test, cols)
            row[f"{model_name}_forecast"] = pred
            row[f"{model_name}_resid_var"] = resid_var
        rows.append(row)
    return pd.DataFrame(rows)


def oos_r2(actual: np.ndarray, pred: np.ndarray) -> float:
    denom = float(np.sum((actual - np.mean(actual)) ** 2))
    if denom <= 0:
        return float("nan")
    return float(1.0 - np.sum((actual - pred) ** 2) / denom)


def evaluate_market(config: MarketConfig, daily: pd.DataFrame) -> dict:
    daily = daily.sort_values("date").reset_index(drop=True)
    features = add_har_features(daily)
    forecasts = expanding_oos_forecasts(features, config)
    actual = forecasts["actual_rv"].to_numpy(dtype=float)

    losses: dict[str, np.ndarray] = {}
    model_results: dict[str, dict] = {}
    for model_name in MODEL_SPECS:
        pred = forecasts[f"{model_name}_forecast"].to_numpy(dtype=float)
        loss = qlike_pointwise(actual, pred)
        losses[model_name] = loss
        model_results[model_name] = {
            "qlike": float(np.mean(loss)),
            "mse_level": float(np.mean((actual - pred) ** 2)),
            "r2_oos_level": oos_r2(actual, pred),
            "mean_forecast_rv": float(np.mean(pred)),
        }

    baseline_loss = losses["HAR_RV"]
    pairwise_vs_har: dict[str, dict] = {}
    for model_name in MODEL_SPECS:
        if model_name == "HAR_RV":
            continue
        t_stat, p_value = dm_test(losses[model_name], baseline_loss, h=1)
        improvement = (
            (model_results["HAR_RV"]["qlike"] - model_results[model_name]["qlike"])
            / abs(model_results["HAR_RV"]["qlike"])
        )
        pairwise_vs_har[model_name] = {
            "dm_t_model_minus_har": float(t_stat),
            "dm_p": float(p_value),
            "qlike_improvement_pct": float(improvement * 100.0),
            "harvey_pass_model_better": bool((t_stat < -HARVEY_THRESHOLD) and (improvement > 0)),
            "interpretation": "negative DM t means candidate has lower QLIKE than standard RV-HAR",
        }

    mcs_raw = model_confidence_set(losses, alpha=MCS_ALPHA, n_boot=MCS_BOOT, seed=SEED)
    mcs = {
        "members": list(mcs_raw.get("mcs_models", [])),
        "eliminated": mcs_raw.get("eliminated", []),
        "p_values": mcs_raw.get("p_values", {}),
        "method": "HLN2011_stationary_bootstrap",
        "alpha": MCS_ALPHA,
        "n_boot": MCS_BOOT,
        "seed": SEED,
    }

    forecast_path = DATA_DIR / f"{config.name}_oos_forecasts.csv"
    forecasts.to_csv(forecast_path, index=False)
    daily_path = DATA_DIR / f"{config.name}_daily_measures.csv"
    daily.to_csv(daily_path, index=False)

    best_model = min(model_results, key=lambda key: model_results[key]["qlike"])
    gateable = int(len(forecasts)) >= config.gateable_min_oos
    strict_winners = [
        name
        for name, stats in pairwise_vs_har.items()
        if stats["harvey_pass_model_better"] and name in set(mcs["members"])
    ]
    if not gateable:
        verdict = "INSUFFICIENT_DATA"
    elif strict_winners:
        verdict = "PASS"
    elif best_model != "HAR_RV" and model_results[best_model]["qlike"] < model_results["HAR_RV"]["qlike"]:
        verdict = "DIRECTIONAL_ONLY"
    else:
        verdict = "NULL"

    corr = daily[MEASURE_COLUMNS].corr().round(6).to_dict()
    ratios = {}
    for measure in [m for m in MEASURE_COLUMNS if m != "rv"]:
        ratio = daily[measure] / daily["rv"]
        ratios[measure] = {
            "mean_ratio_to_rv": float(ratio.mean()),
            "median_ratio_to_rv": float(ratio.median()),
            "p05_ratio_to_rv": float(ratio.quantile(0.05)),
            "p95_ratio_to_rv": float(ratio.quantile(0.95)),
        }

    return {
        "market": config.name,
        "role": config.role,
        "source": config.source,
        "date_range_raw": [
            str(pd.Timestamp(daily["date"].min()).date()),
            str(pd.Timestamp(daily["date"].max()).date()),
        ],
        "n_daily_raw": int(len(daily)),
        "n_feature_rows": int(len(features)),
        "n_oos": int(len(forecasts)),
        "oos_start_date": str(pd.Timestamp(forecasts["date"].iloc[0]).date()) if len(forecasts) else None,
        "oos_end_date": str(pd.Timestamp(forecasts["date"].iloc[-1]).date()) if len(forecasts) else None,
        "min_train": int(config.min_train),
        "gateable_min_oos": int(config.gateable_min_oos),
        "gateable": bool(gateable),
        "median_n_returns_per_day": float(daily["n_returns"].median()),
        "measure_correlations": corr,
        "measure_ratios_to_standard_rv": ratios,
        "models": model_results,
        "pairwise_vs_standard_har": pairwise_vs_har,
        "mcs": mcs,
        "best_model_by_qlike": best_model,
        "verdict": verdict,
        "daily_measure_file": str(daily_path.relative_to(ROOT)),
        "oos_forecast_file": str(forecast_path.relative_to(ROOT)),
    }


def make_figures(results: dict) -> list[str]:
    paths = []
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    for market in results["markets"]:
        daily = pd.read_csv(ROOT / market["daily_measure_file"], parse_dates=["date"])
        fig, ax = plt.subplots(figsize=(11, 4.8))
        for col, label in [
            ("rv", "RV"),
            ("medrv", "MedRV"),
            ("rk_bartlett_h5", "RK"),
            ("tsrv_k5", "TSRV"),
        ]:
            ax.plot(daily["date"], np.sqrt(daily[col] * 252) * 100, label=label, linewidth=1.2)
        ax.set_title(f"{market['market']}: realized-measure estimates")
        ax.set_ylabel("Annualized volatility estimate (%)")
        ax.legend(frameon=False, ncol=4)
        ax.grid(alpha=0.25)
        fig.autofmt_xdate()
        path = FIG_DIR / f"{market['market']}_realized_measures.png"
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        paths.append(str(path.relative_to(ROOT)))

    formal = results["markets"][0]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    labels = []
    values = []
    for model in ["HAR_MedRV_input", "HAR_RK_input", "HAR_TSRV_input"]:
        labels.append(model.replace("HAR_", "").replace("_input", ""))
        values.append(formal["pairwise_vs_standard_har"][model]["qlike_improvement_pct"])
    colors = ["#4C78A8" if v >= 0 else "#C44E52" for v in values]
    ax.bar(labels, values, color=colors)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_ylabel("QLIKE improvement vs standard RV-HAR (%)")
    ax.set_title("TAIFEX formal OOS: robust-measure HAR inputs")
    ax.grid(axis="y", alpha=0.25)
    path = FIG_DIR / "taifex_qlike_improvement_vs_har.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    forecasts = pd.read_csv(ROOT / formal["oos_forecast_file"])
    actual = forecasts["actual_rv"].to_numpy(dtype=float)
    base_loss = qlike_pointwise(actual, forecasts["HAR_RV_forecast"].to_numpy(dtype=float))
    fig, ax = plt.subplots(figsize=(10, 5))
    for model, label in [
        ("HAR_MedRV_input", "MedRV input"),
        ("HAR_RK_input", "RK input"),
        ("HAR_TSRV_input", "TSRV input"),
    ]:
        loss = qlike_pointwise(actual, forecasts[f"{model}_forecast"].to_numpy(dtype=float))
        cumulative = np.cumsum(loss - base_loss)
        ax.plot(pd.to_datetime(forecasts["date"]), cumulative, label=label, linewidth=1.4)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title("TAIFEX cumulative QLIKE loss difference vs standard RV-HAR")
    ax.set_ylabel("Cumulative candidate minus baseline loss")
    ax.legend(frameon=False)
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    path = FIG_DIR / "taifex_cumulative_loss_difference.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    return paths


def run() -> dict:
    np.random.seed(SEED)
    market_data = {
        "TAIFEX_TX_day_K1100h": load_taifex_k1100h_day(),
        "SPY_2026_local_5min": load_spy_local_5min(),
    }
    markets = []
    for config in MARKETS:
        markets.append(evaluate_market(config, market_data[config.name]))

    formal = markets[0]
    if formal["verdict"] == "PASS":
        verdict = "PASS_ROBUST_MEASURE_INPUT"
    elif formal["verdict"] == "DIRECTIONAL_ONLY":
        verdict = "DIRECTIONAL_ONLY_NO_HARVEY_PASS"
    else:
        verdict = "NULL_NO_ROBUST_INPUT_EDGE"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "references": REFERENCES,
        "task": "Replace standard 5-minute RV HAR inputs with MedRV / realized-kernel / TSRV inputs and compare OOS QLIKE/DM/Harvey against standard RV-HAR.",
        "lookahead_policy": {
            "target": "next-day standard 5-minute realized variance",
            "feature_timing": "all HAR daily/weekly/monthly features are computed from measure.shift(1)",
            "training_rule": "expanding OOS train rows strictly before forecast row",
            "why_same_target": "prevents robust estimator self-target alignment from creating a mechanical advantage",
        },
        "estimator_specs": {
            "rv": "sum of squared 5-minute log returns",
            "medrv": "Andersen-Dobrev-Schaumburg nearest-neighbor median realized variance",
            "rk_bartlett_h5": "Bartlett realized kernel / HAC variance estimator with bandwidth 5",
            "tsrv_k5": "two-scale realized variance with 5 sparse subgrids",
        },
        "markets": markets,
        "formal_market": formal["market"],
        "formal_verdict": formal["verdict"],
        "verdict": verdict,
        "harvey_threshold_abs_t": HARVEY_THRESHOLD,
        "mcs_alpha": MCS_ALPHA,
        "mcs_boot": MCS_BOOT,
        "limitations": [
            "Primary TAIFEX cache is the K1100h 2017-2021 day-session TX1-derived 5-minute bar cache after the endpoint bin fix; K1613 drops third-Wednesday settlement days before forecasting, but it is still not the newer K1582 full-TX active-contract 2017-2026 aggregate cache because K1582 does not retain intraday return paths needed for RK/TSRV/MedRV.",
            "SPY local 5-minute data are a 2026 snapshot and remain below the 252-OOS gate.",
            "Realized-kernel and TSRV settings are transparent fixed-parameter implementations, not fully optimal bandwidth/noise-variance estimation.",
            "The primary target is standard RV; results answer input-substitution value, not which realized measure is the best ex-post integrated-variance estimator.",
        ],
    }
    results["figures"] = make_figures(results)
    with open(HERE / "K1613_results.json", "w", encoding="utf-8") as f:
        json.dump(_finite_json(results), f, indent=2, ensure_ascii=False)
    print(json.dumps(_finite_json({"verdict": verdict, "formal": formal}), indent=2, ensure_ascii=False)[:6000])
    return results


if __name__ == "__main__":
    run()
