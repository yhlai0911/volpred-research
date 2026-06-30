"""K1584: HAR-CJ jump decomposition pilot with TX active-contract daily RV.

Research question
-----------------
Does splitting realized variance into a continuous component and a jump
component improve next-day realized-variance forecasts on the locally available
TAIFEX TX intraday panel?

This is intentionally a pilot, not a claim of full co-jump network replication.
The long gateable sample is the TAIFEX TX day-session active-contract panel.
SPY / 0050 5-minute data exist only for a short 2026 overlap and are used as a
descriptive co-jump diagnostic only.

Lookahead policy
----------------
Target at row t is RV_t. Forecast features at row t are computed only from
lagged values using explicit .shift(1) before any rolling window:

    RV_{t-1}, mean(RV_{t-5..t-1}), mean(RV_{t-22..t-1})

The same lag discipline is applied to continuous and jump components. The
co-jump diagnostic uses only previous-day overlap indicators.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
TAIFEX_DIR = Path.home() / "Dropbox" / "TAIFEXDATA" / "TAIFEXDATA" / "python"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

EXPERIMENT_ID = "K1584"
SEED = 42
EPS = 1e-12
MIN_TRAIN_MAIN = 500
MIN_TRAIN_OVERLAP = 60
REFIT_EVERY = 1
HAC_LAGS = 5
JUMP_SHARE_FLAG = 0.05
TX_START = pd.Timestamp("2012-01-02")
TX_END = pd.Timestamp("2026-06-29")
OVERLAP_START = pd.Timestamp("2026-01-20")
TX_CACHE = DATA_DIR / "tx_active_daily_measures_2012_2026.parquet"
SPY_CACHE = DATA_DIR / "spy_daily_measures_2026.parquet"
TW50_CACHE = DATA_DIR / "0050_daily_measures_2026.parquet"
OVERLAP_CACHE = DATA_DIR / "spy_0050_overlap_2026.parquet"
MAIN_FORECASTS_CSV = DATA_DIR / "tx_main_oos_forecasts.csv"
OVERLAP_FORECASTS_CSV = DATA_DIR / "tx_overlap_oos_forecasts.csv"
FIG_PATH = FIG_DIR / "k1584_qlike_jump_cojump.png"
RESULTS_PATH = EXP_DIR / "k1584_results.json"


@dataclass(frozen=True)
class ModelStats:
    qlike: float
    mse: float
    mean_actual_rv: float
    mean_pred_rv: float
    dm_t_vs_baseline: float | None = None
    dm_p_vs_baseline: float | None = None
    harvey_pass_vs_baseline: bool | None = None
    qlike_improvement_pct_vs_baseline: float | None = None
    bootstrap_mean_diff: float | None = None
    bootstrap_ci_95: list[float] | None = None
    bootstrap_p_better: float | None = None


def _round_float(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (np.floating, np.integer)):
        value = float(value)
    return float(value)


def compute_bpv(rets: np.ndarray) -> float:
    """Barndorff-Nielsen and Shephard bipower variation."""
    rets = np.asarray(rets, dtype=float)
    if len(rets) < 2:
        return float("nan")
    abs_r = np.abs(rets)
    n = len(rets)
    return float((np.pi / 2.0) * (n / (n - 1.0)) * np.sum(abs_r[1:] * abs_r[:-1]))


def daily_measures_from_prices(
    date: pd.Timestamp,
    prices: Iterable[float],
    n_bars: int,
    source: str,
) -> dict | None:
    """Convert a 5-minute close series into daily realized measures."""
    prices_arr = np.asarray(list(prices), dtype=float)
    prices_arr = prices_arr[np.isfinite(prices_arr) & (prices_arr > 0)]
    if len(prices_arr) < 12:
        return None

    rets = np.diff(np.log(prices_arr))
    rets = rets[np.isfinite(rets)]
    if len(rets) < 10:
        return None

    rv = float(np.sum(rets**2))
    if rv <= EPS:
        return None

    bpv = compute_bpv(rets)
    continuous = float(min(rv, bpv)) if np.isfinite(bpv) else float(rv)
    jump = float(max(rv - bpv, 0.0)) if np.isfinite(bpv) else 0.0
    jump_share = float(jump / rv) if rv > EPS else 0.0
    total_ret = float(np.sum(rets))
    signed_jump = float(jump if total_ret >= 0 else -jump)
    signed_jump_share = float(signed_jump / rv) if rv > EPS else 0.0

    return {
        "date": pd.Timestamp(date).normalize(),
        "source": source,
        "rv": rv,
        "bpv": float(bpv),
        "continuous": continuous,
        "jump": jump,
        "jump_share": jump_share,
        "jump_indicator": int(jump_share >= JUMP_SHARE_FLAG),
        "signed_jump": signed_jump,
        "signed_jump_share": signed_jump_share,
        "ret": total_ret,
        "n_bars": int(n_bars),
        "n_returns": int(len(rets)),
    }


def _read_taifex_file(path: Path) -> pd.DataFrame:
    last_err: Exception | None = None
    for enc in ("big5", "cp950", "utf-8"):
        try:
            with path.open("r", encoding=enc, newline="") as fh:
                header = fh.readline().strip("\r\n")
            n_cols = len(header.split(","))
            if n_cols == 9:
                names = [
                    "trade_date",
                    "symbol",
                    "contract_mo",
                    "trade_time",
                    "price",
                    "qty",
                    "near_price",
                    "far_price",
                    "ts",
                ]
            elif n_cols == 10:
                names = [
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
            else:
                raise RuntimeError(f"Unexpected TAIFEX header width: {n_cols}")
            df = pd.read_csv(
                path,
                encoding=enc,
                skiprows=1,
                header=None,
                names=names,
                dtype=str,
                low_memory=False,
                na_values=["-"],
            )
            return df
        except UnicodeDecodeError as exc:
            last_err = exc
            continue
    raise RuntimeError(f"Decode failed for {path.name}: {last_err}")


def _list_taifex_files(start: pd.Timestamp, end: pd.Timestamp) -> list[Path]:
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
    frame = raw.copy()
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
        .agg(close=("price", "last"))
        .reset_index()
    )
    if len(bars) < 20:
        return None

    return bars["close"].to_numpy(dtype=float), int(len(bars)), active_contract


def load_tx_active_daily(force: bool = False) -> pd.DataFrame:
    """Build or load TAIFEX TX active-contract daily measures."""
    if TX_CACHE.exists() and not force:
        return pd.read_parquet(TX_CACHE)
    if not TAIFEX_DIR.exists():
        raise FileNotFoundError(f"TAIFEX directory not found: {TAIFEX_DIR}")

    rows: list[dict] = []
    files = _list_taifex_files(TX_START, TX_END)
    print(f"[TX] building active-contract measures from {len(files)} raw files")
    t0 = time.time()
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
            row = daily_measures_from_prices(file_date, prices, n_bars, source=path.name)
            if row is None:
                continue
            row["active_contract"] = active_contract
            row["source_file"] = path.name
            rows.append(row)
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"[TX][WARN] skip {path.name}: {exc}")

        if i % 300 == 0:
            elapsed = time.time() - t0
            print(f"[TX] processed {i}/{len(files)} files, rows={len(rows)}, elapsed={elapsed:.1f}s")

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if df.empty:
        raise RuntimeError("No TX daily rows built")
    df.to_parquet(TX_CACHE, index=False)
    return df


def _read_yf_5min_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, skiprows=[1, 2], low_memory=False)
    if df.empty:
        return df
    cols = list(df.columns)
    cols[0] = "Datetime"
    df.columns = cols
    df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce")
    for col in ["Close", "High", "Low", "Open", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Datetime", "Close"])
    return df


def load_intraday_daily(prefix: str, cache_path: Path) -> pd.DataFrame:
    """Build or load a short 5-minute intraday daily panel from yfinance CSVs."""
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    files = sorted((ROOT / "data" / "intraday").glob(f"{prefix}_5min_*.csv"))
    rows: list[dict] = []
    for path in files:
        match = re.match(rf"{re.escape(prefix)}_5min_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$", path.name)
        if not match:
            continue
        date = pd.Timestamp(match.group(1))
        raw = _read_yf_5min_file(path)
        if raw.empty:
            continue
        closes = raw["Close"].dropna().to_numpy(dtype=float)
        row = daily_measures_from_prices(date, closes, n_bars=int(len(closes)), source=path.name)
        if row is None:
            continue
        row["source_file"] = path.name
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if df.empty:
        raise RuntimeError(f"No rows built for {prefix}")
    df.to_parquet(cache_path, index=False)
    return df


def prepare_features(daily: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Add lagged HAR / HAR-CJ features using explicit lag-1 before rolling."""
    d = daily.sort_values("date").reset_index(drop=True).copy()
    d[f"{prefix}_log_rv"] = np.log(d["rv"].clip(lower=EPS))
    d[f"{prefix}_log_cont"] = np.log(d["continuous"].clip(lower=EPS))
    d[f"{prefix}_jump_share"] = d["jump_share"].clip(lower=0.0)
    d[f"{prefix}_jump_ind"] = d["jump_indicator"].astype(float)
    d[f"{prefix}_signed_jump_share"] = d["signed_jump_share"].clip(lower=-1.0, upper=1.0)

    for base in ["log_rv", "log_cont"]:
        s = d[f"{prefix}_{base}"]
        d[f"{prefix}_{base}_d"] = s.shift(1)
        d[f"{prefix}_{base}_w"] = s.shift(1).rolling(5).mean()
        d[f"{prefix}_{base}_m"] = s.shift(1).rolling(22).mean()

    s = d[f"{prefix}_jump_share"]
    d[f"{prefix}_jump_share_d"] = s.shift(1)
    d[f"{prefix}_jump_share_w"] = s.shift(1).rolling(5).mean()
    d[f"{prefix}_jump_share_m"] = s.shift(1).rolling(22).mean()

    s = d[f"{prefix}_jump_ind"]
    d[f"{prefix}_jump_ind_d"] = s.shift(1)
    d[f"{prefix}_jump_ind_w"] = s.shift(1).rolling(5).mean()
    d[f"{prefix}_jump_ind_m"] = s.shift(1).rolling(22).mean()

    s = d[f"{prefix}_signed_jump_share"]
    d[f"{prefix}_signed_jump_share_d"] = s.shift(1)
    d[f"{prefix}_signed_jump_share_w"] = s.shift(1).rolling(5).mean()
    d[f"{prefix}_signed_jump_share_m"] = s.shift(1).rolling(22).mean()

    d[f"{prefix}_log_target"] = np.log(d["rv"].clip(lower=EPS))
    d = d.dropna().reset_index(drop=True)
    return d


def _block_bootstrap_mean(diff: np.ndarray, reps: int = 1000, block: int = 5, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    diff = np.asarray(diff, dtype=float)
    n = len(diff)
    if n == 0:
        return {"mean_diff": None, "ci_95": None, "p_better": None}
    block = max(1, min(block, n))
    boot = np.empty(reps, dtype=float)
    max_start = max(0, n - block)
    n_blocks = int(np.ceil(n / block))

    for i in range(reps):
        samples = []
        for _ in range(n_blocks):
            start = int(rng.integers(0, max_start + 1)) if max_start > 0 else 0
            samples.append(diff[start : start + block])
        draw = np.concatenate(samples)[:n]
        boot[i] = float(np.mean(draw))

    lo, hi = np.quantile(boot, [0.025, 0.975])
    return {
        "mean_diff": float(np.mean(diff)),
        "ci_95": [float(lo), float(hi)],
        "p_better": float(np.mean(boot < 0.0)),
    }


def fit_expanding_oos(
    frame: pd.DataFrame,
    target_col: str,
    actual_col: str,
    model_specs: dict[str, list[str]],
    min_train: int,
    date_col: str = "date",
    label: str = "main",
) -> tuple[pd.DataFrame, dict[str, ModelStats]]:
    """Expanding-window OOS forecast with per-row refit."""
    if len(frame) <= min_train:
        raise RuntimeError(f"Not enough rows for {label}: {len(frame)} <= {min_train}")

    dates: list[str] = []
    actual: list[float] = []
    preds: dict[str, list[float]] = {name: [] for name in model_specs}

    start_idx = min_train
    for i in range(start_idx, len(frame)):
        train = frame.iloc[:i].copy()
        row = frame.iloc[[i]].copy()
        dates.append(str(pd.Timestamp(row[date_col].iloc[0]).date()))
        actual.append(float(row[actual_col].iloc[0]))
        train_y = train[target_col].to_numpy(dtype=float)
        row_y = float(row[target_col].iloc[0])
        if not np.isfinite(row_y):
            continue

        for name, feats in model_specs.items():
            X_train = sm.add_constant(train[feats], has_constant="add")
            X_row = sm.add_constant(row[feats], has_constant="add")
            fit = sm.OLS(train_y, X_train).fit()
            pred_log = float(fit.predict(X_row).iloc[0])
            preds[name].append(float(np.exp(pred_log)))

    actual_arr = np.asarray(actual, dtype=float)
    out = pd.DataFrame({date_col: dates, "actual_rv": actual_arr})
    for name, values in preds.items():
        out[f"{name}_pred_rv"] = np.asarray(values, dtype=float)

    stats: dict[str, ModelStats] = {}
    baseline = next(iter(model_specs))
    baseline_loss = qlike_pointwise(actual_arr, out[f"{baseline}_pred_rv"].to_numpy(dtype=float))

    for name in model_specs:
        pred = out[f"{name}_pred_rv"].to_numpy(dtype=float)
        loss = qlike_pointwise(actual_arr, pred)
        mse = float(np.mean((actual_arr - pred) ** 2))
        stats[name] = ModelStats(
            qlike=float(np.mean(loss)),
            mse=mse,
            mean_actual_rv=float(np.mean(actual_arr)),
            mean_pred_rv=float(np.mean(pred)),
        )
        if name != baseline:
            t_stat, p_val = dm_test(loss, baseline_loss, h=1)
            diff = loss - baseline_loss
            boot = _block_bootstrap_mean(diff, reps=1000, block=5, seed=SEED)
            stats[name] = ModelStats(
                qlike=stats[name].qlike,
                mse=stats[name].mse,
                mean_actual_rv=stats[name].mean_actual_rv,
                mean_pred_rv=stats[name].mean_pred_rv,
                dm_t_vs_baseline=float(t_stat),
                dm_p_vs_baseline=float(p_val),
                harvey_pass_vs_baseline=bool(abs(t_stat) > 3.0 and t_stat < 0.0),
                qlike_improvement_pct_vs_baseline=float(
                    (stats[baseline].qlike - stats[name].qlike) / abs(stats[baseline].qlike) * 100.0
                ),
                bootstrap_mean_diff=_round_float(boot["mean_diff"]),
                bootstrap_ci_95=boot["ci_95"],
                bootstrap_p_better=boot["p_better"],
            )

    return out, stats


def build_overlap_panel(tx: pd.DataFrame, spy: pd.DataFrame, tw50: pd.DataFrame) -> pd.DataFrame:
    """Short SPY/0050 overlap diagnostic and lagged co-jump proxy."""
    overlap = (
        tx[
            [
                "date",
                "rv",
                "continuous",
                "jump",
                "jump_share",
                "jump_indicator",
                "signed_jump_share",
                "tx_log_rv",
                "tx_log_cont",
            ]
        ]
        .rename(
            columns={
                "jump_indicator": "tx_jump_indicator",
                "jump_share": "tx_jump_share",
                "signed_jump_share": "tx_signed_jump_share",
                "rv": "tx_rv",
                "continuous": "tx_continuous",
                "jump": "tx_jump",
                "tx_log_rv": "tx_log_rv",
                "tx_log_cont": "tx_log_cont",
            }
        )
        .merge(
            spy[["date", "jump_indicator", "jump_share", "signed_jump_share"]].rename(
                columns={
                    "jump_indicator": "spy_jump_indicator",
                    "jump_share": "spy_jump_share",
                    "signed_jump_share": "spy_signed_jump_share",
                }
            ),
            on="date",
            how="inner",
        )
        .merge(
            tw50[["date", "jump_indicator", "jump_share", "signed_jump_share"]].rename(
                columns={
                    "jump_indicator": "tw50_jump_indicator",
                    "jump_share": "tw50_jump_share",
                    "signed_jump_share": "tw50_signed_jump_share",
                }
            ),
            on="date",
            how="inner",
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    if overlap.empty:
        return overlap

    overlap["cojump_proxy"] = (
        (overlap["spy_jump_indicator"] > 0)
        & (overlap["tw50_jump_indicator"] > 0)
        & (np.sign(overlap["spy_signed_jump_share"]) == np.sign(overlap["tw50_signed_jump_share"]))
    ).astype(float)
    overlap["cojump_proxy_d"] = overlap["cojump_proxy"].shift(1)
    overlap["cojump_proxy_w"] = overlap["cojump_proxy"].shift(1).rolling(5).mean()
    overlap["cojump_proxy_m"] = overlap["cojump_proxy"].shift(1).rolling(22).mean()
    overlap["jump_overlap_share"] = np.minimum(overlap["spy_jump_share"], overlap["tw50_jump_share"])
    overlap["same_sign_jump"] = (
        (overlap["spy_jump_indicator"] > 0)
        & (overlap["tw50_jump_indicator"] > 0)
        & (np.sign(overlap["spy_signed_jump_share"]) == np.sign(overlap["tw50_signed_jump_share"]))
    ).astype(int)
    overlap["cojump_overlap_share"] = overlap["jump_overlap_share"].shift(1)
    overlap["cojump_overlap_share_w"] = overlap["jump_overlap_share"].shift(1).rolling(5).mean()
    overlap["cojump_overlap_share_m"] = overlap["jump_overlap_share"].shift(1).rolling(22).mean()
    overlap = overlap.dropna().reset_index(drop=True)
    return overlap


def make_figure(
    main_stats: dict[str, ModelStats],
    main_forecasts: pd.DataFrame,
    overlap_stats: dict[str, ModelStats] | None,
    overlap_forecasts: pd.DataFrame | None,
    overlap_panel: pd.DataFrame,
) -> None:
    """Create a compact figure for forecast comparison and co-jump diagnostics."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("K1584: HAR-CJ jump decomposition and co-jump diagnostic", fontsize=15, fontweight="bold")

    # Panel A: main QLIKE / MSE comparison.
    ax = axes[0, 0]
    labels = list(main_stats.keys())
    qlikes = [main_stats[k].qlike for k in labels]
    ax.bar(labels, qlikes, color=["#355C7D", "#C06C84"], alpha=0.9)
    ax.set_title("TX main panel: OOS QLIKE")
    ax.set_ylabel("QLIKE (lower is better)")
    for i, val in enumerate(qlikes):
        ax.text(i, val, f"{val:.4f}", ha="center", va="bottom", fontsize=9)

    ax2 = ax.twinx()
    mses = [main_stats[k].mse for k in labels]
    ax2.plot(labels, mses, color="#2F4858", marker="o", linewidth=2)
    ax2.set_ylabel("MSE")
    ax2.tick_params(axis="y", labelsize=8)

    # Panel B: main loss differential over time.
    ax = axes[0, 1]
    if len(main_forecasts) > 0:
        diff = qlike_pointwise(
            main_forecasts["actual_rv"].to_numpy(dtype=float),
            main_forecasts["HAR_CJ_pred_rv"].to_numpy(dtype=float),
        ) - qlike_pointwise(
            main_forecasts["actual_rv"].to_numpy(dtype=float),
            main_forecasts["HAR_RV_pred_rv"].to_numpy(dtype=float),
        )
        roll = pd.Series(diff).rolling(21, min_periods=5).mean()
        ax.plot(pd.to_datetime(main_forecasts["date"]), roll, color="#4ECDC4", linewidth=1.5)
        ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--")
        ax.set_title("TX main panel: 21-day rolling QLIKE diff\n(HAR-CJ minus HAR-RV; negative favors HAR-CJ)")
        ax.set_ylabel("QLIKE diff")
    else:
        ax.text(0.5, 0.5, "No main forecast rows", ha="center", va="center")

    # Panel C: overlap scatter of jump shares.
    ax = axes[1, 0]
    if len(overlap_panel) > 0:
        colors = np.where(overlap_panel["cojump_proxy"] > 0, "#E74C3C", "#95A5A6")
        ax.scatter(
            overlap_panel["spy_jump_share"],
            overlap_panel["tw50_jump_share"],
            c=colors,
            alpha=0.8,
            s=28,
            edgecolor="none",
        )
        lim = max(
            float(overlap_panel["spy_jump_share"].max()),
            float(overlap_panel["tw50_jump_share"].max()),
        )
        ax.plot([0, lim], [0, lim], color="black", linestyle="--", linewidth=1)
        ax.set_xlim(0, lim * 1.02)
        ax.set_ylim(0, lim * 1.02)
        ax.set_xlabel("SPY jump share")
        ax.set_ylabel("0050 jump share")
        ax.set_title("2026 overlap: daily jump-share scatter")
    else:
        ax.text(0.5, 0.5, "No overlap rows", ha="center", va="center")

    # Panel D: overlap cojump proxy model if available.
    ax = axes[1, 1]
    if overlap_stats and overlap_forecasts is not None and len(overlap_forecasts) > 0:
        labels = list(overlap_stats.keys())
        vals = [overlap_stats[k].qlike for k in labels]
        ax.bar(labels, vals, color=["#1ABC9C", "#F39C12"], alpha=0.9)
        ax.set_title("Overlap panel: OOS QLIKE")
        ax.set_ylabel("QLIKE")
        for i, val in enumerate(vals):
            ax.text(i, val, f"{val:.4f}", ha="center", va="bottom", fontsize=8)
    else:
        ax.text(
            0.5,
            0.5,
            "Overlap proxy model unavailable\n(or too short for stable gate)",
            ha="center",
            va="center",
        )

    for ax in axes.flat:
        ax.grid(True, alpha=0.25)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def build_results(
    tx: pd.DataFrame,
    spy: pd.DataFrame,
    tw50: pd.DataFrame,
    main_panel: pd.DataFrame,
    main_stats: dict[str, ModelStats],
    overlap_panel: pd.DataFrame,
    overlap_stats: dict[str, ModelStats] | None,
    main_forecasts: pd.DataFrame,
    overlap_forecasts: pd.DataFrame | None,
) -> dict:
    tx_period = {
        "start": str(tx["date"].min().date()),
        "end": str(tx["date"].max().date()),
        "observations": int(len(tx)),
        "source_files": int(tx["source_file"].nunique()),
        "active_contracts": int(tx["active_contract"].nunique()),
    }
    overlap_period = {
        "start": str(overlap_panel["date"].min().date()) if len(overlap_panel) else None,
        "end": str(overlap_panel["date"].max().date()) if len(overlap_panel) else None,
        "observations": int(len(overlap_panel)),
        "cojump_proxy_rate": float(overlap_panel["cojump_proxy"].mean()) if len(overlap_panel) else None,
        "same_sign_jump_rate": float(overlap_panel["same_sign_jump"].mean()) if len(overlap_panel) else None,
        "mean_overlap_jump_share": float(overlap_panel["jump_overlap_share"].mean()) if len(overlap_panel) else None,
    }

    main_comparison = {}
    baseline_name = "HAR_RV"
    candidate_name = "HAR_CJ"
    if baseline_name in main_stats and candidate_name in main_stats:
        candidate = main_stats[candidate_name]
        baseline = main_stats[baseline_name]
        main_comparison = {
            "baseline": baseline_name,
            "candidate": candidate_name,
            "qlike_baseline": _round_float(baseline.qlike),
            "qlike_candidate": _round_float(candidate.qlike),
            "mse_baseline": _round_float(baseline.mse),
            "mse_candidate": _round_float(candidate.mse),
            "dm_t": _round_float(candidate.dm_t_vs_baseline),
            "dm_p": _round_float(candidate.dm_p_vs_baseline),
            "harvey_pass": candidate.harvey_pass_vs_baseline,
            "qlike_improvement_pct": _round_float(candidate.qlike_improvement_pct_vs_baseline),
            "bootstrap": {
                "mean_diff": _round_float(candidate.bootstrap_mean_diff),
                "ci_95": candidate.bootstrap_ci_95,
                "p_better": _round_float(candidate.bootstrap_p_better),
            },
        }

    overlap_comparison = {}
    if overlap_stats and "HAR_CJ" in overlap_stats and "HAR_CJ_COJ" in overlap_stats:
        candidate = overlap_stats["HAR_CJ_COJ"]
        baseline = overlap_stats["HAR_CJ"]
        overlap_comparison = {
            "baseline": "HAR_CJ",
            "candidate": "HAR_CJ_COJ",
            "qlike_baseline": _round_float(baseline.qlike),
            "qlike_candidate": _round_float(candidate.qlike),
            "mse_baseline": _round_float(baseline.mse),
            "mse_candidate": _round_float(candidate.mse),
            "dm_t": _round_float(candidate.dm_t_vs_baseline),
            "dm_p": _round_float(candidate.dm_p_vs_baseline),
            "harvey_pass": candidate.harvey_pass_vs_baseline,
            "qlike_improvement_pct": _round_float(candidate.qlike_improvement_pct_vs_baseline),
            "bootstrap": {
                "mean_diff": _round_float(candidate.bootstrap_mean_diff),
                "ci_95": candidate.bootstrap_ci_95,
                "p_better": _round_float(candidate.bootstrap_p_better),
            },
        }

    if main_comparison.get("harvey_pass"):
        verdict = "GATEABLE_SUPPORT"
    elif candidate_name in main_stats and candidate.qlike < baseline.qlike:
        verdict = "WEAK_RAW_ONLY"
    else:
        verdict = "NULL"

    return {
        "experiment_id": EXPERIMENT_ID,
        "title": "K1584: HAR-CJ jump decomposition pilot with TX active-contract daily RV",
        "seed": SEED,
        "status": "completed",
        "verdict": verdict,
        "research_question": "Does splitting realized variance into continuous and jump components improve next-day RV forecasts on the local TX intraday panel, and can a short SPY/0050 overlap yield a conservative co-jump diagnostic?",
        "target_definition": {
            "main_target": "next-day TX day-session realized variance RV_t from 5-minute active-contract bars",
            "main_forecast_scale": "log RV regression with exponentiated predictions for QLIKE/MSE evaluation",
            "cojump_scope": "short 2026 SPY/0050 overlap diagnostic only; not systemic network evidence",
        },
        "lookahead_policy": {
            "main": "Every predictor is built with explicit shift(1) before rolling windows.",
            "overlap": "Co-jump proxy uses previous-day overlap flags only.",
            "status": "CLEAN",
        },
        "data_sources": {
            "tx_active_contract": {
                "source": str(TAIFEX_DIR),
                "period": tx_period,
                "session": "TAIFEX TX day session 08:45-13:45 local time",
            },
            "spy_5min": {
                "source": str(ROOT / "data" / "intraday"),
                "period": {
                    "start": str(spy["date"].min().date()),
                    "end": str(spy["date"].max().date()),
                    "observations": int(len(spy)),
                    "files": int(spy["source_file"].nunique()),
                },
            },
            "0050_5min": {
                "source": str(ROOT / "data" / "intraday"),
                "period": {
                    "start": str(tw50["date"].min().date()),
                    "end": str(tw50["date"].max().date()),
                    "observations": int(len(tw50)),
                    "files": int(tw50["source_file"].nunique()),
                },
            },
        },
        "sample_sizes": {
            "tx_main_panel": {
                "rows_before_dropna": int(len(tx)),
                "rows_after_feature_build": int(len(main_panel)),
                "oos_rows": int(len(main_forecasts)),
                "min_train": MIN_TRAIN_MAIN,
            },
            "overlap_panel": {
                "rows_after_feature_build": int(len(overlap_panel)),
                "oos_rows": int(len(overlap_forecasts)) if overlap_forecasts is not None else 0,
                "min_train": MIN_TRAIN_OVERLAP,
            },
        },
        "jump_decomposition": {
            "rv": "sum of squared 5-minute log returns",
            "bpv": "Barndorff-Nielsen and Shephard bipower variation",
            "continuous": "min(RV, BPV)",
            "jump": "max(RV - BPV, 0)",
            "jump_share": "jump / RV",
            "jump_indicator": f"1{{jump_share >= {JUMP_SHARE_FLAG:.2f}}}; coarse event flag for diagnostics only",
        },
        "main_panel": {
            "feature_set": {
                "HAR_RV": ["tx_log_rv_d", "tx_log_rv_w", "tx_log_rv_m"],
                "HAR_CJ": [
                    "tx_log_cont_d",
                    "tx_log_cont_w",
                    "tx_log_cont_m",
                    "tx_jump_share_d",
                    "tx_jump_share_w",
                    "tx_jump_share_m",
                ],
            },
            "model_stats": {name: asdict(stat) for name, stat in main_stats.items()},
            "comparison": main_comparison,
            "forecast_file": str(MAIN_FORECASTS_CSV.relative_to(EXP_DIR)),
        },
        "overlap_diagnostic": {
            "definition": {
                "cojump_proxy": "same-day SPY/0050 jump-day overlap with same sign, lagged by 1 day for forecasting",
                "same_sign_jump": "binary same-day same-sign jump overlap",
            },
            "panel_summary": overlap_period,
            "model_stats": {name: asdict(stat) for name, stat in (overlap_stats or {}).items()},
            "comparison": overlap_comparison,
            "forecast_file": str(OVERLAP_FORECASTS_CSV.relative_to(EXP_DIR)) if overlap_forecasts is not None else None,
        },
        "figures": [str(FIG_PATH.relative_to(EXP_DIR))],
        "caveats": [
            "The long gateable sample is TX only. SPY/0050 are short 2026 panels and are descriptive only.",
            "jump_indicator is a variance-share threshold flag, not a count of jump events.",
            "The co-jump proxy is a conservative overlap diagnostic, not systemic network evidence.",
            "If the candidate fails the Harvey |t| > 3 gate, the result is directional or null even if raw QLIKE improves.",
        ],
        "literature_reviewed": [
            {
                "citation": "Caporin, Kolokolov, Reno (2017)",
                "use": "Systemic co-jump motivation and the need to avoid overstating short-panel overlap as network evidence.",
            },
            {
                "citation": "Ding, Li, Liu, Zheng (2024)",
                "use": "Stock co-jump network framing; relevant only as a high-level motivation because this experiment does not estimate a full network.",
            },
            {
                "citation": "Corsi, Pirino, Reno (2010)",
                "use": "Continuous/jump variance decomposition and HAR-CJ-style forecasting design.",
            },
            {
                "citation": "Bormetti et al. (2015)",
                "use": "Jump clustering / Hawkes-factor motivation for considering co-jump diagnostics.",
            },
        ],
        "limitations": [
            "This is not a TAQ/tick-perfect multi-asset co-jump network replication.",
            "The SPY/0050 overlap is short and should not be interpreted as strong systemic evidence.",
            "The jump-event threshold is a coarse diagnostic rule; jump_share itself is the main variance metric.",
        ],
    }


def main() -> int:
    np.random.seed(SEED)

    tx = load_tx_active_daily(force=False)
    spy = load_intraday_daily("SPY", SPY_CACHE)
    tw50 = load_intraday_daily("0050_TW", TW50_CACHE)

    tx_feat = prepare_features(tx, prefix="tx")
    main_specs = {
        "HAR_RV": ["tx_log_rv_d", "tx_log_rv_w", "tx_log_rv_m"],
        "HAR_CJ": [
            "tx_log_cont_d",
            "tx_log_cont_w",
            "tx_log_cont_m",
            "tx_jump_share_d",
            "tx_jump_share_w",
            "tx_jump_share_m",
        ],
    }
    main_forecasts, main_stats = fit_expanding_oos(
        tx_feat,
        target_col="tx_log_target",
        actual_col="rv",
        model_specs=main_specs,
        min_train=MIN_TRAIN_MAIN,
        label="main_tx_panel",
    )
    main_forecasts.to_csv(MAIN_FORECASTS_CSV, index=False)

    overlap_panel = build_overlap_panel(tx_feat, spy, tw50)
    overlap_stats: dict[str, ModelStats] | None = None
    overlap_forecasts: pd.DataFrame | None = None
    if len(overlap_panel) >= MIN_TRAIN_OVERLAP + 10:
        overlap_specs = {
            "HAR_CJ": [
                "tx_log_cont_d",
                "tx_log_cont_w",
                "tx_log_cont_m",
                "tx_jump_share_d",
                "tx_jump_share_w",
                "tx_jump_share_m",
            ],
            "HAR_CJ_COJ": [
                "tx_log_cont_d",
                "tx_log_cont_w",
                "tx_log_cont_m",
                "tx_jump_share_d",
                "tx_jump_share_w",
                "tx_jump_share_m",
                "cojump_proxy_d",
                "cojump_proxy_w",
                "cojump_proxy_m",
            ],
        }
        overlap_forecasts, overlap_stats = fit_expanding_oos(
            overlap_panel.assign(tx_log_target=np.log(overlap_panel["tx_rv"].clip(lower=EPS))),
            target_col="tx_log_target",
            actual_col="tx_rv",
            model_specs=overlap_specs,
            min_train=MIN_TRAIN_OVERLAP,
            label="overlap_proxy_panel",
        )
        overlap_forecasts.to_csv(OVERLAP_FORECASTS_CSV, index=False)

    make_figure(main_stats, main_forecasts, overlap_stats, overlap_forecasts, overlap_panel)
    results = build_results(
        tx=tx,
        spy=spy,
        tw50=tw50,
        main_panel=tx_feat,
        main_stats=main_stats,
        overlap_panel=overlap_panel,
        overlap_stats=overlap_stats,
        main_forecasts=main_forecasts,
        overlap_forecasts=overlap_forecasts,
    )

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[K1584] wrote {RESULTS_PATH}")
    print(f"[K1584] figure {FIG_PATH}")
    print(f"[K1584] verdict={results['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
