"""K1582: HARQ / SHARK-style measurement-error corrections for HAR-RV.

Research question
-----------------
Do realized-quarticity measurement-error corrections and signed intraday
components improve one-step-ahead realized-variance forecasts beyond a plain
HAR-RV baseline?

Lookahead policy
----------------
Target at row t is RV_t. Every forecast feature at row t is computed from
lagged values only:

    RV_{t-1}, mean(RV_{t-5..t-1}), mean(RV_{t-22..t-1})

The code uses explicit .shift(1) before all rolling features. Expanding OOS
fits train on rows strictly before the forecast row.

This experiment is intentionally scoped as a pilot. The only long local
intraday panel is TAIFEX TX tick data. US/Taiwan ETF 5-minute snapshots are
short 2026 panels and are marked non-gateable when OOS n < 252.
"""

from __future__ import annotations

import glob
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.stats.mcs import model_confidence_set
from volpred.stats.model_evaluation import dm_test, qlike_pointwise


EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
INTRADAY_DIR = ROOT / "data" / "intraday"
TAIFEX_DIR = Path.home() / "Dropbox" / "TAIFEXDATA" / "TAIFEXDATA" / "python"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
EPS = 1e-12
HORIZON = 1
MCS_BOOT = 1000
MCS_ALPHA = 0.10
TX_START = pd.Timestamp("2017-05-16")
TX_END = pd.Timestamp("2026-06-30")
TX_CACHE = DATA_DIR / "tx_active_daily_measures_2017_2026.parquet"


@dataclass(frozen=True)
class MarketConfig:
    name: str
    role: str
    source: str
    min_train: int
    gateable_min_oos: int = 252


def compute_bpv(rets: np.ndarray) -> float:
    """Barndorff-Nielsen-Shephard bipower variation."""
    rets = np.asarray(rets, dtype=float)
    n = len(rets)
    if n < 2:
        return float("nan")
    abs_r = np.abs(rets)
    return float((np.pi / 2.0) * (n / (n - 1.0)) * np.sum(abs_r[1:] * abs_r[:-1]))


def daily_measures_from_prices(date: pd.Timestamp, prices: Iterable[float], n_bars: int) -> dict | None:
    prices_arr = np.asarray(list(prices), dtype=float)
    prices_arr = prices_arr[np.isfinite(prices_arr) & (prices_arr > 0)]
    if len(prices_arr) < 12:
        return None
    rets = np.diff(np.log(prices_arr))
    rets = rets[np.isfinite(rets)]
    n = int(len(rets))
    if n < 10:
        return None

    r2 = rets * rets
    rv = float(np.sum(r2))
    if rv <= EPS:
        return None
    rq = float((n / 3.0) * np.sum(rets ** 4))
    bpv = compute_bpv(rets)
    raw_jump = max(rv - bpv, 0.0) if np.isfinite(bpv) else 0.0
    total_ret = float(np.sum(rets))
    signed_jump = raw_jump * (1.0 if total_ret >= 0 else -1.0)
    rs_plus = float(np.sum(r2[rets > 0]))
    rs_minus = float(np.sum(r2[rets < 0]))

    return {
        "date": pd.Timestamp(date).normalize(),
        "rv": rv,
        "rq": max(rq, EPS),
        "bpv": bpv,
        "raw_jump": raw_jump,
        "signed_jump": signed_jump,
        "rs_plus": rs_plus,
        "rs_minus": rs_minus,
        "ret": total_ret,
        "n_bars": int(n_bars),
        "n_returns": n,
    }


def _standardize_taifex_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.shape[1] != 10:
        raise RuntimeError(f"Expected 10 TAIFEX columns, got {df.shape[1]}")
    out = df.copy()
    out.columns = [
        "trade_date",
        "symbol",
        "contract_mo",
        "trade_time",
        "price",
        "qty",
        "near_price",
        "far_price",
        "auction_flag",
        "ts",
    ]
    return out


def _read_taifex_file(path: Path) -> pd.DataFrame:
    last_err: Exception | None = None
    for enc in ("big5", "cp950", "utf-8"):
        try:
            return _standardize_taifex_columns(
                pd.read_csv(path, encoding=enc, low_memory=False, na_values=["-"])
            )
        except UnicodeDecodeError as exc:
            last_err = exc
            continue
    raise RuntimeError(f"Decode failed for {path.name}: {last_err}")


def _list_tx_files(start: pd.Timestamp, end: pd.Timestamp) -> list[Path]:
    pattern = re.compile(r"Daily_(\d{4})_(\d{2})_(\d{2})TX\.csv$")
    files: list[tuple[pd.Timestamp, Path]] = []
    for path in TAIFEX_DIR.glob("Daily_*TX.csv"):
        match = pattern.match(path.name)
        if not match:
            continue
        date = pd.Timestamp(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if start <= date <= end:
            files.append((date, path))
    return [path for _, path in sorted(files)]


def _tx_active_day_prices(file_date: pd.Timestamp, raw: pd.DataFrame) -> tuple[np.ndarray, int, str] | None:
    frame = raw[raw["auction_flag"] != "*"].copy()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["qty"] = pd.to_numeric(frame["qty"], errors="coerce")
    frame["contract_mo"] = frame["contract_mo"].astype(str)
    frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce")
    frame = frame.dropna(subset=["price", "qty", "contract_mo", "ts"])
    frame = frame[(frame["price"] > 0) & (frame["qty"] > 0)]
    if frame.empty:
        return None

    day_start = file_date.normalize() + pd.Timedelta(hours=8, minutes=45)
    day_end = file_date.normalize() + pd.Timedelta(hours=13, minutes=45)
    day = frame[(frame["ts"] >= day_start) & (frame["ts"] <= day_end)].copy()
    if day.empty:
        return None

    volume = day.groupby("contract_mo")["qty"].sum().sort_values(ascending=False)
    if volume.empty:
        return None
    active_contract = str(volume.index[0])
    active = day[day["contract_mo"] == active_contract].copy()
    if len(active) < 20:
        return None

    active["bar_start"] = active["ts"].dt.floor("5min")
    endpoint = active["bar_start"] >= day_end
    if endpoint.any():
        active.loc[endpoint, "bar_start"] = day_end - pd.Timedelta(minutes=5)
    bars = (
        active.groupby("bar_start", sort=True)
        .agg(close=("price", "last"), n_ticks=("price", "count"))
        .reset_index()
    )
    if len(bars) < 20:
        return None
    return bars["close"].to_numpy(dtype=float), int(len(bars)), active_contract


def load_tx_active_daily(force: bool = False) -> pd.DataFrame:
    """Build or load active-contract TAIFEX TX day-session daily measures."""
    if TX_CACHE.exists() and not force:
        return pd.read_parquet(TX_CACHE)
    if not TAIFEX_DIR.exists():
        raise FileNotFoundError(f"TAIFEX directory not found: {TAIFEX_DIR}")

    rows: list[dict] = []
    files = _list_tx_files(TX_START, TX_END)
    t0 = time.time()
    print(f"[TX_ACTIVE] building measures from {len(files)} TX files")
    for i, path in enumerate(files, start=1):
        match = re.match(r"Daily_(\d{4})_(\d{2})_(\d{2})TX\.csv$", path.name)
        if not match:
            continue
        file_date = pd.Timestamp(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        try:
            raw = _read_taifex_file(path)
            active = _tx_active_day_prices(file_date, raw)
            if active is None:
                continue
            prices, n_bars, active_contract = active
            row = daily_measures_from_prices(file_date, prices, n_bars)
            if row is None:
                continue
            row["active_contract"] = active_contract
            row["source_file"] = path.name
            rows.append(row)
        except Exception as exc:
            print(f"[TX_ACTIVE] WARN {path.name}: {type(exc).__name__}: {exc}")
        if i % 250 == 0:
            print(f"[TX_ACTIVE] {i}/{len(files)} files, rows={len(rows)}, elapsed={time.time() - t0:.1f}s")

    if not rows:
        raise RuntimeError("No TX active-contract daily rows built")
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    out.to_parquet(TX_CACHE, index=False)
    print(f"[TX_ACTIVE] cached {len(out)} rows -> {TX_CACHE}")
    return out


def _date_from_intraday_path(path: Path) -> pd.Timestamp:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if not match:
        raise ValueError(f"Cannot infer date from {path.name}")
    return pd.Timestamp(match.group(1))


def read_yfinance_5min_file(path: Path) -> dict | None:
    frame = pd.read_csv(path, skiprows=[1, 2])
    if frame.empty or "Close" not in frame.columns:
        return None
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    return daily_measures_from_prices(_date_from_intraday_path(path), close.to_numpy(), len(close))


def load_local_intraday_daily(label: str, pattern: str) -> pd.DataFrame:
    rows = []
    for name in sorted(glob.glob(str(INTRADAY_DIR / pattern))):
        row = read_yfinance_5min_file(Path(name))
        if row is not None:
            rows.append(row)
    if not rows:
        raise ValueError(f"No valid local intraday rows for {label}")
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def add_forecast_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Create lag-clean HARQ / SHARK features.

    Measurement-error proxy:
        me_t = sqrt(RQ_t) / RV_t

    This is dimensionless and uses no full-sample standardization. HARQ lets the
    daily HAR coefficient vary with me_{t-1} via log_rv_d_x_me.
    """
    d = daily.copy().sort_values("date").reset_index(drop=True)
    d["rq"] = d["rq"].clip(lower=EPS)
    d["rv"] = d["rv"].clip(lower=EPS)
    d["me"] = np.sqrt(d["rq"]) / d["rv"]
    d["rs_minus_share"] = d["rs_minus"] / d["rv"]
    d["rs_imbalance"] = (d["rs_minus"] - d["rs_plus"]) / d["rv"]
    d["signed_jump_share"] = d["signed_jump"] / d["rv"]
    d["abs_jump_share"] = d["raw_jump"] / d["rv"]

    lagged = {
        "rv": d["rv"].shift(1),
        "me": d["me"].shift(1),
        "rs_minus_share": d["rs_minus_share"].shift(1),
        "rs_imbalance": d["rs_imbalance"].shift(1),
        "signed_jump_share": d["signed_jump_share"].shift(1),
        "abs_jump_share": d["abs_jump_share"].shift(1),
    }

    for base_name, series in lagged.items():
        d[f"{base_name}_d"] = series
        d[f"{base_name}_w"] = series.rolling(5, min_periods=5).mean()
        d[f"{base_name}_m"] = series.rolling(22, min_periods=22).mean()

    for col in ["rv_d", "rv_w", "rv_m"]:
        d[f"log_{col}"] = np.log(d[col].clip(lower=EPS))

    d["log_rv_d_x_me_d"] = d["log_rv_d"] * d["me_d"]
    d["log_rv_w_x_me_w"] = d["log_rv_w"] * d["me_w"]
    d["log_rv_m_x_me_m"] = d["log_rv_m"] * d["me_m"]
    d["log_rv"] = np.log(d["rv"].clip(lower=EPS))

    feature_cols = sorted(
        {
            "log_rv_d",
            "log_rv_w",
            "log_rv_m",
            "log_rv_d_x_me_d",
            "log_rv_w_x_me_w",
            "log_rv_m_x_me_m",
            "rs_minus_share_d",
            "rs_minus_share_w",
            "rs_imbalance_d",
            "rs_imbalance_w",
            "signed_jump_share_d",
            "signed_jump_share_w",
            "abs_jump_share_d",
        }
    )
    d = d.dropna(subset=feature_cols + ["log_rv", "rv"]).reset_index(drop=True)
    return d


MODEL_FEATURES = {
    "HAR": ["log_rv_d", "log_rv_w", "log_rv_m"],
    "HARQ": ["log_rv_d", "log_rv_w", "log_rv_m", "log_rv_d_x_me_d"],
    "HARQ_full": [
        "log_rv_d",
        "log_rv_w",
        "log_rv_m",
        "log_rv_d_x_me_d",
        "log_rv_w_x_me_w",
        "log_rv_m_x_me_m",
    ],
    "SHARK_like": [
        "log_rv_d",
        "log_rv_w",
        "log_rv_m",
        "log_rv_d_x_me_d",
        "rs_minus_share_d",
        "rs_minus_share_w",
        "rs_imbalance_d",
        "rs_imbalance_w",
        "signed_jump_share_d",
        "signed_jump_share_w",
        "abs_jump_share_d",
    ],
}


def fit_predict_log_ols(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> tuple[float, dict[str, float], float]:
    x_train = train[cols].to_numpy(dtype=float)
    x_train = np.column_stack([np.ones(len(x_train)), x_train])
    y_train = train["log_rv"].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
    resid = y_train - x_train @ beta
    denom = max(len(resid) - len(beta), 1)
    resid_var = float(np.sum(resid * resid) / denom)

    x_test = test[cols].to_numpy(dtype=float)
    x_test = np.column_stack([np.ones(len(x_test)), x_test])
    pred_log = float(x_test[0] @ beta)
    pred_level = math.exp(pred_log + 0.5 * max(resid_var, 0.0))
    beta_dict = {name: float(value) for name, value in zip(["intercept"] + cols, beta)}
    return max(pred_level, EPS), beta_dict, resid_var


def expanding_oos_forecasts(features: pd.DataFrame, min_train: int) -> pd.DataFrame:
    if len(features) <= min_train + 10:
        raise ValueError(f"insufficient rows after warm-up: rows={len(features)}, min_train={min_train}")

    rows: list[dict] = []
    for pos in range(min_train, len(features)):
        train = features.iloc[:pos]
        test = features.iloc[[pos]]
        row: dict[str, object] = {
            "date": str(pd.Timestamp(test["date"].iloc[0]).date()),
            "actual_rv": float(test["rv"].iloc[0]),
            "position": int(pos),
        }
        for model_name, cols in MODEL_FEATURES.items():
            pred, beta, resid_var = fit_predict_log_ols(train, test, cols)
            row[f"{model_name}_forecast"] = pred
            row[f"{model_name}_resid_var"] = resid_var
            if pos == min_train:
                row[f"{model_name}_first_beta"] = json.dumps(beta, sort_keys=True)
        rows.append(row)
    return pd.DataFrame(rows)


def _r2_oos(actual: np.ndarray, predicted: np.ndarray) -> float:
    ss_res = float(np.sum((actual - predicted) ** 2))
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def evaluate_market(config: MarketConfig, daily: pd.DataFrame) -> dict:
    daily = daily.sort_values("date").reset_index(drop=True)
    features = add_forecast_features(daily)
    min_train = min(config.min_train, max(40, len(features) // 2))
    forecasts = expanding_oos_forecasts(features, min_train=min_train)
    actual = forecasts["actual_rv"].to_numpy(dtype=float)

    losses: dict[str, np.ndarray] = {}
    model_results: dict[str, dict] = {}
    for model_name in MODEL_FEATURES:
        pred = forecasts[f"{model_name}_forecast"].to_numpy(dtype=float)
        loss = qlike_pointwise(actual, pred)
        losses[model_name] = loss
        model_results[model_name] = {
            "qlike": float(np.mean(loss)),
            "mse_level": float(np.mean((actual - pred) ** 2)),
            "r2_oos_level": _r2_oos(actual, pred),
            "mean_forecast_rv": float(np.mean(pred)),
        }

    har_loss = losses["HAR"]
    pairwise_vs_har: dict[str, dict] = {}
    for model_name in MODEL_FEATURES:
        if model_name == "HAR":
            continue
        t_stat, p_value = dm_test(losses[model_name], har_loss, h=HORIZON)
        improvement = (model_results["HAR"]["qlike"] - model_results[model_name]["qlike"]) / abs(
            model_results["HAR"]["qlike"]
        )
        pairwise_vs_har[model_name] = {
            "dm_t_model_minus_har": float(t_stat),
            "dm_p": float(p_value),
            "qlike_improvement_pct": float(improvement * 100.0),
            "harvey_pass_model_better": bool((t_stat < -3.0) and (improvement > 0)),
            "interpretation": "negative DM t means candidate has lower QLIKE than HAR",
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
    oos_path = DATA_DIR / f"{config.name.replace('.', '_')}_oos_forecasts.csv"
    forecasts.to_csv(oos_path, index=False)

    best_model = min(model_results, key=lambda key: model_results[key]["qlike"])
    gateable = int(len(forecasts)) >= config.gateable_min_oos
    candidate_pass = [
        name
        for name, stats in pairwise_vs_har.items()
        if stats["harvey_pass_model_better"] and name in set(mcs.get("members", []))
    ]
    if not gateable:
        verdict = "INSUFFICIENT_DATA"
    elif candidate_pass:
        verdict = "PASS"
    elif best_model != "HAR" and model_results[best_model]["qlike"] < model_results["HAR"]["qlike"]:
        verdict = "DIRECTIONAL_ONLY"
    else:
        verdict = "NULL"

    return {
        "market": config.name,
        "role": config.role,
        "source": config.source,
        "date_range_raw": [str(pd.Timestamp(daily["date"].min()).date()), str(pd.Timestamp(daily["date"].max()).date())],
        "n_daily_raw": int(len(daily)),
        "n_feature_rows": int(len(features)),
        "n_oos": int(len(forecasts)),
        "min_train": int(min_train),
        "gateable_min_oos": int(config.gateable_min_oos),
        "gateable": bool(gateable),
        "median_n_returns_per_day": float(daily["n_returns"].median()),
        "mean_measurement_error_proxy": float((np.sqrt(daily["rq"].clip(lower=EPS)) / daily["rv"].clip(lower=EPS)).mean()),
        "mean_abs_signed_jump_share": float((daily["signed_jump"].abs() / daily["rv"].clip(lower=EPS)).mean()),
        "mean_rs_minus_share": float((daily["rs_minus"] / daily["rv"].clip(lower=EPS)).mean()),
        "models": model_results,
        "pairwise_vs_har": pairwise_vs_har,
        "mcs": mcs,
        "best_model_by_qlike": best_model,
        "verdict": verdict,
        "oos_forecast_file": str(oos_path.relative_to(ROOT)),
    }


def make_summary_plot(results: dict) -> None:
    markets = results["markets"]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    labels = []
    values = []
    colors = []
    palette = {"HARQ": "#4C78A8", "HARQ_full": "#F58518", "SHARK_like": "#54A24B"}
    for market in markets:
        for model in ["HARQ", "HARQ_full", "SHARK_like"]:
            labels.append(f"{market['market']}\n{model}")
            values.append(market["pairwise_vs_har"][model]["qlike_improvement_pct"])
            colors.append(palette[model])
    ax.bar(range(len(values)), values, color=colors)
    ax.axhline(0, color="black", lw=0.8)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("QLIKE improvement vs HAR (%)")
    ax.set_title("K1582 HARQ / SHARK-style measurement-error corrections")
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1582_qlike_improvement.png", dpi=160)
    plt.close(fig)


def determine_overall_verdict(markets: list[dict]) -> tuple[str, str]:
    gateable = [m for m in markets if m["gateable"]]
    passes = [m for m in gateable if m["verdict"] == "PASS"]
    directional = [m for m in gateable if m["verdict"] == "DIRECTIONAL_ONLY"]
    if passes:
        return (
            "CONDITIONAL_PASS",
            "At least one gateable market has a HARQ/SHARK-style candidate that beats HAR by QLIKE, passes Harvey |DM|>3, and remains in MCS. Treat as conditional because model class was selected in a pilot.",
        )
    if directional:
        return (
            "DIRECTIONAL_ONLY",
            "A gateable market has lower QLIKE for a candidate model, but the improvement fails the Harvey |DM|>3 gate and/or MCS screen.",
        )
    if gateable:
        return (
            "NULL",
            "No gateable market shows a statistically defensible HARQ/SHARK-style improvement over HAR-RV.",
        )
    return (
        "NULL_INSUFFICIENT_DATA",
        "No market has at least 252 OOS forecasts; results are feasibility-only.",
    )


def main() -> dict:
    np.random.seed(SEED)
    markets_input: list[tuple[MarketConfig, pd.DataFrame]] = []

    tx_daily = load_tx_active_daily(force=False)
    markets_input.append(
        (
            MarketConfig(
                name="TX_active",
                role="TAIFEX TX active-contract day-session futures",
                source=f"{TAIFEX_DIR}/Daily_*TX.csv; active contract by day-session volume",
                min_train=500,
            ),
            tx_daily,
        )
    )

    markets_input.append(
        (
            MarketConfig(
                name="SPY",
                role="US equity ETF; local 5-minute snapshot panel",
                source="data/intraday/SPY_5min_2026-*.csv",
                min_train=40,
            ),
            load_local_intraday_daily("SPY", "SPY_5min_2026-*.csv"),
        )
    )
    markets_input.append(
        (
            MarketConfig(
                name="0050.TW",
                role="Taiwan index ETF proxy; local 5-minute snapshot panel",
                source="data/intraday/0050_TW_5min_2026-*.csv",
                min_train=40,
            ),
            load_local_intraday_daily("0050.TW", "0050_TW_5min_2026-*.csv"),
        )
    )

    market_results = []
    for config, daily in markets_input:
        print(f"\n=== {config.name} ===")
        result = evaluate_market(config, daily)
        market_results.append(result)
        print(
            f"{config.name}: verdict={result['verdict']} n_oos={result['n_oos']} "
            f"best={result['best_model_by_qlike']} "
            f"HARQ_impr={result['pairwise_vs_har']['HARQ']['qlike_improvement_pct']:.2f}% "
            f"SHARK_impr={result['pairwise_vs_har']['SHARK_like']['qlike_improvement_pct']:.2f}%"
        )

    overall_verdict, summary = determine_overall_verdict(market_results)
    results = {
        "experiment_id": "K1582",
        "title": "HARQ / SHARK-style measurement-error corrections for HAR-RV",
        "run_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "verdict": overall_verdict,
        "summary": summary,
        "research_question": "Do RQ-based measurement-error interactions and signed intraday components improve one-step-ahead HAR-RV forecasts?",
        "forecast_timing": {
            "target": "RV_t from 5-minute intraday returns",
            "features": "All daily / weekly / monthly predictors are built from series.shift(1), so row t uses t-1 and older information.",
            "oos_fit": "Expanding OLS; each forecast row trains on rows strictly before that row.",
            "lookahead_status": "CLEAN for the implemented one-step RV forecast target.",
        },
        "models": {
            "HAR": "log RV_t on log RV_{t-1}, log mean RV_{t-5..t-1}, log mean RV_{t-22..t-1}",
            "HARQ": "HAR plus log RV_{t-1} interacted with sqrt(RQ_{t-1}) / RV_{t-1}",
            "HARQ_full": "HAR plus daily/weekly/monthly RQ measurement-error interactions",
            "SHARK_like": "HARQ plus lagged realized semivariance shares and raw signed BNS jump-share controls",
        },
        "statistics": {
            "primary_loss": "Patton QLIKE on RV_t",
            "dm_test": "volpred.stats.model_evaluation.dm_test with h=1; negative t means candidate lower QLIKE than HAR",
            "harvey_gate": "candidate better only if DM t < -3 and QLIKE improvement > 0",
            "mcs": f"volpred.stats.mcs.model_confidence_set alpha={MCS_ALPHA}, n_boot={MCS_BOOT}, seed={SEED}",
        },
        "data_limitations": [
            "TX_active is the only gateable long local intraday panel.",
            "SPY and 0050.TW local 5-minute CSV panels are short 2026 snapshots and cannot support publication-grade cross-market inference.",
            "SHARK_like is an implementable approximation using RQ interactions, semivariance shares, and raw signed BNS jump shares; it is not a byte-for-byte replication of Buccheri-Corsi's full SHARK estimator.",
        ],
        "literature": [
            {
                "citation": "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility",
                "url": "https://academic.oup.com/jfec/article-abstract/7/2/174/959428",
                "use": "HAR-RV baseline and daily/weekly/monthly components.",
            },
            {
                "citation": "Bollerslev, Patton and Quaedvlieg (2016), Exploiting the errors",
                "url": "https://public.econ.duke.edu/~ap172/BPQ_Exploiting_Errors_JoE_2016.pdf",
                "use": "HARQ motivation: realized quarticity proxies measurement error and lets HAR coefficients vary with measurement-error precision.",
            },
            {
                "citation": "Buccheri and Corsi (2021), SHARK-related realized-volatility forecasting work",
                "url": "https://www.sciencedirect.com/science/article/abs/pii/S1062976921000453",
                "use": "Motivates testing richer realized-measure and signed-component corrections around HAR.",
            },
            {
                "citation": "Patton and Zhang (2026), Bespoke Realized Volatility",
                "url": "https://www.sciencedirect.com/science/article/abs/pii/S0304407625000557",
                "use": "Motivates treating realized measures as design choices subject to measurement-error and forecast-target alignment.",
            },
        ],
        "markets": market_results,
    }

    make_summary_plot(results)
    results["figures"] = ["experiments/k1582/figures/k1582_qlike_improvement.png"]

    out_path = EXP_DIR / "K1582_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"\n[done] verdict={overall_verdict}")
    print(f"[done] wrote {out_path}")
    return results


if __name__ == "__main__":
    main()
