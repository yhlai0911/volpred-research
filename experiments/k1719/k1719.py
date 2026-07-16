"""K1719: conservative daily ASIA-5 volatility spillover ladder.

The experiment intentionally uses only previous-session information.  Daily
bars cannot identify the overlapping intraday Japan/Taiwan/SEA close sequence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import (
    clark_west_test,
    dm_test,
    qlike_pointwise,
    spearman_corr,
)


SEED = 42
START = "2005-01-01"
END = "2025-12-31"
WINDOW = 756
MIN_TRAIN = 504
EPSILON = 1e-10
HERE = Path(__file__).resolve().parent
SNAPSHOT = HERE / "k1719_source_snapshot.csv"
RESULTS = HERE / "k1719_results.json"
CHART = HERE / "k1719_qlike_improvement.png"

TICKERS = {
    "SPY": "SPY",
    "VIX": "^VIX",
    "JAPAN": "^N225",
    "TAIWAN": "^TWII",
    "SINGAPORE": "^STI",
    "INDONESIA": "^JKSE",
    "MALAYSIA": "^KLSE",
    "THAILAND": "^SET.BK",
}
TARGETS = {
    "JAPAN": ["SPY", "VIX"],
    "TAIWAN": ["SPY", "VIX", "JAPAN"],
    "SINGAPORE": ["SPY", "VIX", "JAPAN", "TAIWAN"],
    "INDONESIA": ["SPY", "VIX", "JAPAN", "TAIWAN"],
    "MALAYSIA": ["SPY", "VIX", "JAPAN", "TAIWAN"],
    "THAILAND": ["SPY", "VIX", "JAPAN", "TAIWAN"],
}


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_snapshot() -> pd.DataFrame:
    """Download once, freeze close prices, and return canonical columns."""
    raw = yf.download(
        list(TICKERS.values()),
        start=START,
        end=END,
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=False,
        group_by="column",
    )
    if raw.empty:
        raise RuntimeError("Yahoo Finance returned no observations")
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    inverse = {ticker: name for name, ticker in TICKERS.items()}
    close = close.rename(columns=inverse).reindex(columns=list(TICKERS))
    close.index = pd.to_datetime(close.index, utc=True).tz_localize(None)
    close.index.name = "date"
    counts = close.notna().sum()
    missing = [name for name in TICKERS if counts.get(name, 0) < 2_500]
    if missing:
        raise RuntimeError(f"insufficient history for: {missing}; counts={counts.to_dict()}")
    csv_text = close.sort_index().to_csv(date_format="%Y-%m-%d", float_format="%.10f")
    _atomic_write_text(SNAPSHOT, csv_text)
    return close


def load_or_download_snapshot() -> pd.DataFrame:
    if SNAPSHOT.exists():
        frame = pd.read_csv(SNAPSHOT, index_col="date", parse_dates=["date"], float_precision="round_trip")
        if list(frame.columns) != list(TICKERS):
            raise RuntimeError("snapshot columns do not match the registered ticker order")
        return frame
    return download_snapshot()


def build_model_frame(close: pd.DataFrame, target: str, upstream: list[str]) -> pd.DataFrame:
    """Build an inner-joined frame after market-local signal lagging."""
    series: dict[str, pd.Series] = {}
    target_ret = np.log(close[target]).diff()
    target_variance = target_ret.pow(2)
    series["actual_variance"] = target_variance

    # Explicit task-required lag.  The shift is applied within each market
    # before joining dates, so same-date foreign closes never enter features.
    signal = target_variance
    series["own_lag1"] = signal.shift(1)
    series["own_mean5"] = signal.rolling(5, min_periods=5).mean().shift(1)
    series["own_mean22"] = signal.rolling(22, min_periods=22).mean().shift(1)

    for name in upstream:
        if name == "VIX":
            signal = np.log(close[name].clip(lower=1.0))
        else:
            signal = np.log(close[name]).diff().pow(2)
        series[f"upstream_{name}"] = signal.shift(1)

    frame = pd.concat(series, axis=1, join="inner").dropna()
    frame = frame[(frame["actual_variance"] > 0) & np.isfinite(frame).all(axis=1)]
    if len(frame) < MIN_TRAIN + 252:
        raise RuntimeError(f"{target}: only {len(frame)} complete observations")
    return frame


def _ols_predict(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> float:
    design = np.column_stack([np.ones(len(x_train)), x_train])
    beta, *_ = np.linalg.lstsq(design, y_train, rcond=None)
    return float(np.r_[1.0, x_test] @ beta)


def walk_forward(frame: pd.DataFrame, upstream: list[str]) -> pd.DataFrame:
    baseline_cols = ["own_lag1", "own_mean5", "own_mean22"]
    full_cols = baseline_cols + [f"upstream_{name}" for name in upstream]
    log_features = [col for col in full_cols if col != "upstream_VIX"]
    model = frame.copy()
    model[log_features] = np.log(model[log_features].clip(lower=EPSILON))
    model["log_target"] = np.log(model["actual_variance"].clip(lower=EPSILON))

    rows: list[dict[str, Any]] = []
    for i in range(MIN_TRAIN, len(model)):
        start = max(0, i - WINDOW)
        train = model.iloc[start:i]
        test = model.iloc[i]
        y_train = train["log_target"].to_numpy(dtype=float)
        pred_base_log = _ols_predict(
            train[baseline_cols].to_numpy(dtype=float),
            y_train,
            test[baseline_cols].to_numpy(dtype=float),
        )
        pred_full_log = _ols_predict(
            train[full_cols].to_numpy(dtype=float),
            y_train,
            test[full_cols].to_numpy(dtype=float),
        )
        variance_train = train["actual_variance"].to_numpy(dtype=float)
        lower, upper = np.quantile(variance_train, [0.01, 0.99])
        rows.append(
            {
                "date": model.index[i],
                "actual": float(test["actual_variance"]),
                "actual_log": float(test["log_target"]),
                "baseline": float(np.clip(np.exp(pred_base_log), lower, upper)),
                "ladder": float(np.clip(np.exp(pred_full_log), lower, upper)),
                "baseline_log": pred_base_log,
                "ladder_log": pred_full_log,
            }
        )
    forecasts = pd.DataFrame(rows).set_index("date")
    assert forecasts.index.is_monotonic_increasing
    assert np.isfinite(forecasts.to_numpy()).all()
    return forecasts


def evaluate_target(forecasts: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    actual = forecasts["actual"].to_numpy()
    base = forecasts["baseline"].to_numpy()
    ladder = forecasts["ladder"].to_numpy()
    base_loss = qlike_pointwise(actual, base)
    ladder_loss = qlike_pointwise(actual, ladder)
    # nested-dm: diagnostic-only.  The ladder nests the own-history baseline,
    # so Clark-West below, not raw DM, owns the inferential claim/verdict.
    dm_t, dm_p = dm_test(ladder_loss, base_loss, h=1)
    rho_base, rho_base_p = spearman_corr(actual, base)
    rho_ladder, rho_ladder_p = spearman_corr(actual, ladder)
    cw = clark_west_test(
        forecasts["actual_log"].to_numpy(),
        forecasts["baseline_log"].to_numpy(),
        forecasts["ladder_log"].to_numpy(),
        h=1,
    )
    cw["harvey_strength_abs_t_gt_3"] = bool(abs(cw["t_stat"]) > 3.0)
    q_base = float(np.mean(base_loss))
    q_ladder = float(np.mean(ladder_loss))
    metrics = {
        "n_oos": int(len(forecasts)),
        "oos_start": forecasts.index.min().date().isoformat(),
        "oos_end": forecasts.index.max().date().isoformat(),
        "qlike_baseline": q_base,
        "qlike_ladder": q_ladder,
        "qlike_improvement_pct": 100.0 * (q_base - q_ladder) / q_base,
        "mse_baseline": float(np.mean((actual - base) ** 2)),
        "mse_ladder": float(np.mean((actual - ladder) ** 2)),
        "dm_ladder_vs_baseline_t": dm_t,
        "dm_two_sided_p": dm_p,
        "dm_harvey_strength_diagnostic": bool(abs(dm_t) > 3.0),
        "spearman_baseline": {"rho": rho_base, "p": rho_base_p},
        "spearman_ladder": {"rho": rho_ladder, "p": rho_ladder_p},
        "clark_west_log_variance": cw,
    }
    losses = pd.DataFrame({"baseline": base_loss, "ladder": ladder_loss}, index=forecasts.index)
    return metrics, losses


def panel_clark_west(sea_forecasts: dict[str, pd.DataFrame]) -> dict[str, Any]:
    common_dates = sorted(set.intersection(*(set(frame.index) for frame in sea_forecasts.values())))
    if len(common_dates) < 10:
        raise RuntimeError(f"SEA panel has only {len(common_dates)} common forecast dates")
    actual = np.column_stack(
        [frame.loc[common_dates, "actual_log"].to_numpy() for frame in sea_forecasts.values()]
    )
    baseline = np.column_stack(
        [frame.loc[common_dates, "baseline_log"].to_numpy() for frame in sea_forecasts.values()]
    )
    ladder = np.column_stack(
        [frame.loc[common_dates, "ladder_log"].to_numpy() for frame in sea_forecasts.values()]
    )
    result = clark_west_test(actual, baseline, ladder, h=1, aggregate_axis=1)
    result["aggregation"] = "Clark-West adjusted loss averaged across assets by common date before HAC"
    result["n_assets"] = len(sea_forecasts)
    result["harvey_strength_abs_t_gt_3"] = bool(abs(result["t_stat"]) > 3.0)
    return result


def render_chart(target_results: dict[str, dict[str, Any]]) -> None:
    names = list(target_results)
    values = [target_results[name]["qlike_improvement_pct"] for name in names]
    colors = ["#1677ff" if value > 0 else "#d94a4a" for value in values]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(names, values, color=colors)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_ylabel("QLIKE improvement vs own-history baseline (%)")
    ax.set_title("K1719: previous-session upstream information")
    ax.tick_params(axis="x", rotation=25)
    fig.tight_layout()
    fig.savefig(CHART, dpi=160)
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    close = load_or_download_snapshot()
    target_results: dict[str, dict[str, Any]] = {}
    sea_forecasts: dict[str, pd.DataFrame] = {}
    sample_counts = {name: int(close[name].notna().sum()) for name in TICKERS}

    for target, upstream in TARGETS.items():
        frame = build_model_frame(close, target, upstream)
        forecasts = walk_forward(frame, upstream)
        metrics, _losses = evaluate_target(forecasts)
        target_results[target] = metrics
        if target in {"SINGAPORE", "INDONESIA", "MALAYSIA", "THAILAND"}:
            sea_forecasts[target] = forecasts

    panel = panel_clark_west(sea_forecasts)
    improved = sum(item["qlike_improvement_pct"] > 0 for item in target_results.values())
    significant = sum(
        item["clark_west_log_variance"]["harvey_strength_abs_t_gt_3"]
        for item in target_results.values()
    )
    supported = improved >= 4 and significant >= 2 and panel["harvey_strength_abs_t_gt_3"]
    if supported:
        verdict = "SUPPORTED"
    elif improved == 0 and significant == 0:
        verdict = "NULL"
    else:
        verdict = "MIXED"

    render_chart(target_results)
    payload = {
        "experiment_id": "K1719",
        "generated_at_policy": "omitted for byte reproducibility",
        "seed": SEED,
        "data": {
            "source": "Yahoo Finance via yfinance 1.2.0",
            "request_start": START,
            "request_end_exclusive": END,
            "tickers": TICKERS,
            "observations_by_ticker": sample_counts,
            "snapshot_file": SNAPSHOT.name,
            "snapshot_sha256": _sha256(SNAPSHOT),
        },
        "method": {
            "target": "daily squared close-to-close log return",
            "forecast_target": "log variance; evaluated on variance scale",
            "window": WINDOW,
            "minimum_training_observations": MIN_TRAIN,
            "information_set": "all own/upstream signals shifted one market-local observation before date join",
            "dm": "volpred.stats.model_evaluation.dm_test, h=1, diagnostic-only under nesting",
            "formal_nested_test": "volpred.stats.model_evaluation.clark_west_test on log variance",
            "harvey_threshold": 3.0,
        },
        "targets": target_results,
        "southeast_asia_panel": panel,
        "success_criteria": {
            "qlike_improves_targets_required": 4,
            "clark_west_abs_t_gt_3_targets_required": 2,
            "panel_clark_west_abs_t_gt_3_required": True,
            "qlike_improved_targets": improved,
            "clark_west_abs_t_gt_3_targets": significant,
            "met": bool(supported),
        },
        "verdict": verdict,
        "limitations": [
            "Daily bars cannot isolate overlapping intraday Tokyo/Taipei/Southeast-Asia transmission.",
            "Squared daily return is a noisy variance proxy, not realized variance.",
            "Inner joining common dates may select globally open trading days and omits holiday-specific transmission.",
            "Results establish predictive association only, not a structural causal channel.",
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = RESULTS.with_suffix(".json.tmp")
    tmp.write_text(serialized, encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, RESULTS)
    print(json.dumps({"verdict": verdict, "success_criteria": payload["success_criteria"]}, indent=2))


if __name__ == "__main__":
    main()
