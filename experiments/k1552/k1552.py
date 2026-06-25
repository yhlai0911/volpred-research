"""K1552 - Public proxy for investor-memory cue and volatility persistence.

Question
--------
When today's recent return pattern resembles prior crash/rally episodes, does
that similarity-based recall cue predict next-day/next-week activity and
volatility in US sector ETFs?

Lookahead discipline
--------------------
Raw memory cues are computed at the close of day d from returns through day d
and a trailing historical episode library that ends at d-22. The predictive
signal used for day-t outcomes is always:

    signal = raw_memory_cue.shift(1)

so day-t outcomes only see information available at t-1.

Run
---
uv run python experiments/k1552/k1552.py
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf


SEED = 42
EXPERIMENT_ID = "K1552"
START = "2000-01-01"
END = "2026-06-26"
TRADING_DAYS = 252
LIBRARY_WINDOW = 1260
LIBRARY_GAP = 22
EXTREME_Q = 0.05
HAC_LAGS = 5
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FIG_DIR = BASE_DIR / "figures"
RESULT_PATH = BASE_DIR / "k1552_results.json"

ASSET_TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
    "XLRE",
]
CONTROL_TICKERS = ["^VIX"]
ALL_TICKERS = ASSET_TICKERS + CONTROL_TICKERS

PRIMARY_TARGETS = [
    "log_range_var",
    "log_fwd5_rv",
    "volume_z",
    "downside_ret",
]
SIGNALS = ["loss_memory_lag1", "rally_memory_lag1"]
TARGET_LAG_CONTROL = {
    "log_range_var": "log_range_var_lag1",
    "log_fwd5_rv": "log_past5_rv_lag1",
    "volume_z": "volume_z_lag1",
    "downside_ret": "downside_ret_lag1",
    "ret": "ret_lag1",
    "log_abs_ret": "log_abs_ret_lag1",
}


@dataclass(frozen=True)
class RegressionCell:
    target: str
    signal: str
    coef: float
    t_stat: float
    p_value: float
    bonferroni_pass: bool
    expected_direction_pass: bool


@dataclass(frozen=True)
class EventSpread:
    target: str
    signal: str
    high_n: int
    other_n: int
    high_mean: float
    other_mean: float
    high_minus_other: float


def _json_float(value: object, ndigits: int = 8) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x):
        return None
    return round(x, ndigits)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def download_prices() -> pd.DataFrame:
    cache = DATA_DIR / "prices.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty or not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("yfinance returned empty or non-MultiIndex data")
    raw = raw.sort_index()
    raw.to_parquet(cache)
    return raw


def _field(raw: pd.DataFrame, field: str) -> pd.DataFrame:
    if field not in raw.columns.get_level_values(0):
        raise KeyError(f"missing yfinance field: {field}")
    return raw[field].copy()


def trailing_z(series: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    mu = series.rolling(window, min_periods=min_periods).mean()
    sigma = series.rolling(window, min_periods=min_periods).std(ddof=1)
    return (series - mu) / sigma.replace(0.0, np.nan)


def forward_sum_including_current(series: pd.Series, horizon: int) -> pd.Series:
    total = pd.Series(0.0, index=series.index)
    for step in range(horizon):
        total = total + series.shift(-step)
    return total


def compute_memory_cues(ret5: pd.Series, ret21: pd.Series) -> pd.DataFrame:
    """Compute trailing similarity to prior extreme loss/rally episodes.

    For each date d, the library is [d-1260, d-22]. Extreme loss/rally labels
    and standardization are recomputed from that library only. This makes the
    raw cue observable at the close of d; predictive use happens after an
    explicit shift(1) in `build_asset_panel`.
    """
    index = ret5.index
    f5 = ret5.to_numpy(dtype=float)
    f21 = ret21.to_numpy(dtype=float)
    loss = np.full(len(index), np.nan)
    rally = np.full(len(index), np.nan)

    for i in range(LIBRARY_WINDOW + LIBRARY_GAP, len(index)):
        cur = np.array([f5[i], f21[i]], dtype=float)
        if not np.isfinite(cur).all():
            continue
        start = max(0, i - LIBRARY_GAP - LIBRARY_WINDOW)
        stop = i - LIBRARY_GAP
        lib = np.column_stack([f5[start:stop], f21[start:stop]])
        valid = np.isfinite(lib).all(axis=1)
        lib = lib[valid]
        if len(lib) < 500:
            continue

        ret21_lib = lib[:, 1]
        loss_cut = np.nanquantile(ret21_lib, EXTREME_Q)
        rally_cut = np.nanquantile(ret21_lib, 1.0 - EXTREME_Q)
        scale = np.nanstd(lib, axis=0, ddof=1)
        scale = np.where(np.isfinite(scale) & (scale > 1e-12), scale, np.nan)
        if not np.isfinite(scale).all():
            continue

        dist2 = np.sum(((lib - cur) / scale) ** 2, axis=1)
        sim = np.exp(-0.5 * dist2)
        loss_mask = ret21_lib <= loss_cut
        rally_mask = ret21_lib >= rally_cut
        if loss_mask.any():
            loss[i] = float(np.nanmax(sim[loss_mask]))
        if rally_mask.any():
            rally[i] = float(np.nanmax(sim[rally_mask]))

    return pd.DataFrame({"loss_memory_raw": loss, "rally_memory_raw": rally}, index=index)


def build_asset_panel(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = _field(raw, "Close")
    high = _field(raw, "High")
    low = _field(raw, "Low")
    volume = _field(raw, "Volume")

    rows: list[pd.DataFrame] = []
    availability: list[dict] = []

    for ticker in ASSET_TICKERS:
        if ticker not in close.columns:
            continue
        df = pd.DataFrame(
            {
                "close": close[ticker],
                "high": high[ticker],
                "low": low[ticker],
                "volume": volume[ticker],
            }
        ).replace([np.inf, -np.inf], np.nan)
        df = df.dropna(subset=["close", "high", "low"])
        if len(df) < 1500:
            continue

        df["ticker"] = ticker
        df["ret"] = np.log(df["close"] / df["close"].shift(1))
        df["ret5"] = df["ret"].rolling(5).sum()
        df["ret21"] = df["ret"].rolling(21).sum()
        df["abs_ret"] = df["ret"].abs()
        df["downside_ret"] = df["ret"].clip(upper=0.0)
        df["range_var"] = (np.log(df["high"] / df["low"]) ** 2) / (4.0 * math.log(2.0))
        df["range_var_ann"] = df["range_var"] * TRADING_DAYS
        df["fwd5_rv"] = forward_sum_including_current(df["ret"] ** 2, 5) * TRADING_DAYS / 5.0
        df["volume_z"] = trailing_z(np.log1p(df["volume"]))
        df["rv21_lag1"] = (df["ret"] ** 2).rolling(21).mean().shift(1) * TRADING_DAYS
        df["past5_rv_lag1"] = (df["ret"] ** 2).rolling(5).mean().shift(1) * TRADING_DAYS
        df["ret5_lag1"] = df["ret5"].shift(1)
        df["abs_ret21_lag1"] = df["ret21"].abs().shift(1)

        cues = compute_memory_cues(df["ret5"], df["ret21"])
        df = df.join(cues)
        # Explicit lag required by project rule: signal from t-1, target at t.
        df["loss_memory_lag1"] = df["loss_memory_raw"].shift(1)
        df["rally_memory_lag1"] = df["rally_memory_raw"].shift(1)
        df["any_memory_lag1"] = df[["loss_memory_lag1", "rally_memory_lag1"]].max(axis=1)

        df["log_range_var"] = np.log(df["range_var_ann"].clip(lower=1e-12))
        df["log_fwd5_rv"] = np.log(df["fwd5_rv"].clip(lower=1e-12))
        df["log_abs_ret"] = np.log(df["abs_ret"].clip(lower=1e-8))
        df["log_rv21_lag1"] = np.log(df["rv21_lag1"].clip(lower=1e-12))
        df["log_past5_rv_lag1"] = np.log(df["past5_rv_lag1"].clip(lower=1e-12))

        valid_signal = df[["loss_memory_lag1", "rally_memory_lag1"]].dropna()
        availability.append(
            {
                "ticker": ticker,
                "first_price_date": str(df.index.min().date()),
                "last_price_date": str(df.index.max().date()),
                "price_rows": int(len(df)),
                "valid_memory_signal_rows": int(len(valid_signal)),
            }
        )
        rows.append(df.reset_index(names="date"))

    panel = pd.concat(rows, ignore_index=True)
    panel = panel.sort_values(["ticker", "date"])
    availability_df = pd.DataFrame(availability)
    panel.to_parquet(DATA_DIR / "asset_panel.parquet")
    availability_df.to_csv(DATA_DIR / "data_availability.csv", index=False)
    panel.head(1000).to_csv(DATA_DIR / "asset_panel_preview.csv", index=False)
    return panel, availability_df


def build_aggregate(panel: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "ret",
        "abs_ret",
        "downside_ret",
        "log_range_var",
        "log_fwd5_rv",
        "log_abs_ret",
        "volume_z",
        "loss_memory_lag1",
        "rally_memory_lag1",
        "any_memory_lag1",
        "ret5_lag1",
        "abs_ret21_lag1",
        "log_rv21_lag1",
        "log_past5_rv_lag1",
    ]
    agg = panel.groupby("date")[numeric_cols].mean(numeric_only=True).sort_index()
    agg["coverage_n"] = panel.groupby("date")["ticker"].nunique()

    close = _field(raw, "Close")
    if "^VIX" in close.columns:
        vix = close["^VIX"].replace([np.inf, -np.inf], np.nan)
        agg["log_vix_lag1"] = np.log(vix).shift(1).reindex(agg.index)
    else:
        agg["log_vix_lag1"] = np.nan

    for target in ["log_range_var", "volume_z", "downside_ret", "ret", "log_abs_ret"]:
        agg[f"{target}_lag1"] = agg[target].shift(1)

    agg.to_csv(DATA_DIR / "aggregate_daily.csv")
    return agg


def expected_direction(target: str, signal: str, coef: float) -> bool:
    if target in {"log_range_var", "log_fwd5_rv", "log_abs_ret", "volume_z"}:
        return coef > 0
    if target == "downside_ret":
        return coef < 0
    if target == "ret" and signal == "loss_memory_lag1":
        return coef < 0
    if target == "ret" and signal == "rally_memory_lag1":
        return coef > 0
    return False


def fit_primary_regressions(agg: pd.DataFrame) -> tuple[list[RegressionCell], dict[str, float]]:
    rows: list[RegressionCell] = []
    models: dict[str, object] = {}
    n_tests = len(PRIMARY_TARGETS) * len(SIGNALS)

    for target in PRIMARY_TARGETS:
        lag_control = TARGET_LAG_CONTROL[target]
        cols = [
            target,
            "loss_memory_lag1",
            "rally_memory_lag1",
            lag_control,
            "ret5_lag1",
            "abs_ret21_lag1",
            "log_rv21_lag1",
            "log_vix_lag1",
            "coverage_n",
        ]
        d = agg[cols].replace([np.inf, -np.inf], np.nan).dropna()
        y = d[target]
        x = sm.add_constant(d.drop(columns=[target]), has_constant="add")
        model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
        models[target] = model
        for signal in SIGNALS:
            coef = float(model.params[signal])
            t_stat = float(model.tvalues[signal])
            p_value = float(model.pvalues[signal])
            rows.append(
                RegressionCell(
                    target=target,
                    signal=signal,
                    coef=coef,
                    t_stat=t_stat,
                    p_value=p_value,
                    bonferroni_pass=p_value < 0.05 / n_tests,
                    expected_direction_pass=expected_direction(target, signal, coef),
                )
            )

    best = max(rows, key=lambda cell: abs(cell.t_stat))
    return rows, {"target": best.target, "signal": best.signal, "t_stat": best.t_stat}


def moving_block_bootstrap_coef(agg: pd.DataFrame, target: str, signal: str) -> dict:
    cols = [
        target,
        "loss_memory_lag1",
        "rally_memory_lag1",
        TARGET_LAG_CONTROL[target],
        "ret5_lag1",
        "abs_ret21_lag1",
        "log_rv21_lag1",
        "log_vix_lag1",
        "coverage_n",
    ]
    d = agg[cols].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    n = len(d)
    rng = np.random.default_rng(SEED)
    coefs: list[float] = []
    for _ in range(BOOTSTRAP_REPS):
        chunks = []
        while sum(len(chunk) for chunk in chunks) < n:
            start = int(rng.integers(0, max(1, n - BOOTSTRAP_BLOCK + 1)))
            chunks.append(d.iloc[start : start + BOOTSTRAP_BLOCK])
        sample = pd.concat(chunks, ignore_index=True).iloc[:n]
        y = sample[target]
        x = sm.add_constant(sample.drop(columns=[target]), has_constant="add")
        try:
            fit = sm.OLS(y, x).fit()
            coefs.append(float(fit.params[signal]))
        except Exception:
            continue
    arr = np.asarray(coefs, dtype=float)
    return {
        "target": target,
        "signal": signal,
        "reps_requested": BOOTSTRAP_REPS,
        "reps_completed": int(len(arr)),
        "block_size_days": BOOTSTRAP_BLOCK,
        "coef_mean": _json_float(np.nanmean(arr)),
        "coef_ci_2_5": _json_float(np.nanpercentile(arr, 2.5)),
        "coef_ci_97_5": _json_float(np.nanpercentile(arr, 97.5)),
    }


def event_spreads(agg: pd.DataFrame) -> list[EventSpread]:
    out: list[EventSpread] = []
    for signal in SIGNALS:
        threshold = agg[signal].rolling(756, min_periods=252).quantile(0.80).shift(1)
        high = agg[signal] > threshold
        for target in PRIMARY_TARGETS:
            d = agg[[target, signal]].replace([np.inf, -np.inf], np.nan).dropna()
            h = high.reindex(d.index).fillna(False)
            high_vals = d.loc[h, target]
            other_vals = d.loc[~h, target]
            out.append(
                EventSpread(
                    target=target,
                    signal=signal,
                    high_n=int(high_vals.notna().sum()),
                    other_n=int(other_vals.notna().sum()),
                    high_mean=float(high_vals.mean()),
                    other_mean=float(other_vals.mean()),
                    high_minus_other=float(high_vals.mean() - other_vals.mean()),
                )
            )
    return out


def per_ticker_summary(panel: pd.DataFrame) -> pd.DataFrame:
    records: list[dict] = []
    for ticker, df in panel.groupby("ticker"):
        for target in ["log_range_var", "log_fwd5_rv", "volume_z"]:
            lag_control = TARGET_LAG_CONTROL[target]
            cols = [
                target,
                "loss_memory_lag1",
                "rally_memory_lag1",
                lag_control if lag_control in df.columns else None,
                "ret5_lag1",
                "abs_ret21_lag1",
                "log_rv21_lag1",
            ]
            cols = [c for c in cols if c is not None]
            work = df.copy()
            if lag_control not in work.columns:
                work[lag_control] = work[target].shift(1)
                cols.append(lag_control)
            d = work[cols].replace([np.inf, -np.inf], np.nan).dropna()
            if len(d) < 500:
                continue
            y = d[target]
            x = sm.add_constant(d.drop(columns=[target]), has_constant="add")
            fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
            for signal in SIGNALS:
                records.append(
                    {
                        "ticker": ticker,
                        "target": target,
                        "signal": signal,
                        "n": int(fit.nobs),
                        "coef": float(fit.params[signal]),
                        "t_stat": float(fit.tvalues[signal]),
                        "expected_direction_pass": expected_direction(target, signal, float(fit.params[signal])),
                    }
                )
    out = pd.DataFrame(records)
    out.to_csv(DATA_DIR / "per_ticker_regressions.csv", index=False)
    return out


def make_figures(agg: pd.DataFrame, cells: list[RegressionCell], spreads: list[EventSpread]) -> list[str]:
    paths: list[str] = []

    fig, ax1 = plt.subplots(figsize=(11, 5))
    agg[["loss_memory_lag1", "rally_memory_lag1"]].rolling(63).mean().plot(ax=ax1)
    ax1.set_title("K1552 aggregate memory-cue intensity (63d mean)")
    ax1.set_ylabel("Similarity to prior extreme episodes")
    ax1.grid(True, alpha=0.25)
    path = FIG_DIR / "k1552_memory_cues.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(BASE_DIR)))

    coef_df = pd.DataFrame([asdict(c) for c in cells])
    coef_df["label"] = coef_df["target"] + "\n" + coef_df["signal"].str.replace("_memory_lag1", "")
    colors = ["#2A9D8F" if ok else "#E76F51" for ok in coef_df["expected_direction_pass"]]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(coef_df["label"], coef_df["t_stat"], color=colors)
    ax.axhline(3.0, color="black", lw=1, ls="--")
    ax.axhline(-3.0, color="black", lw=1, ls="--")
    ax.set_title("Primary HAC t-statistics (Harvey reference lines at +/-3)")
    ax.set_ylabel("HAC t-stat")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, axis="y", alpha=0.25)
    path = FIG_DIR / "k1552_primary_tstats.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(BASE_DIR)))

    spread_df = pd.DataFrame([asdict(s) for s in spreads])
    spread_df["label"] = spread_df["target"] + "\n" + spread_df["signal"].str.replace("_memory_lag1", "")
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(spread_df["label"], spread_df["high_minus_other"], color="#52796F")
    ax.axhline(0.0, color="black", lw=1)
    ax.set_title("High-memory days minus other days (rolling 80th percentile trigger)")
    ax.set_ylabel("Mean target spread")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, axis="y", alpha=0.25)
    path = FIG_DIR / "k1552_event_spreads.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(BASE_DIR)))

    return paths


def main() -> None:
    ensure_dirs()
    raw = download_prices()
    panel, availability = build_asset_panel(raw)
    agg = build_aggregate(panel, raw)
    cells, best_cell = fit_primary_regressions(agg)
    bootstrap = moving_block_bootstrap_coef(agg, best_cell["target"], best_cell["signal"])
    spreads = event_spreads(agg)
    ticker_regs = per_ticker_summary(panel)
    figure_paths = make_figures(agg, cells, spreads)

    primary_passes = [c for c in cells if c.bonferroni_pass and c.expected_direction_pass]
    harvey_passes = [c for c in cells if abs(c.t_stat) >= 3.0 and c.expected_direction_pass]
    opposite_bonferroni = [c for c in cells if c.bonferroni_pass and not c.expected_direction_pass]
    if primary_passes:
        verdict = "WEAK_ACTIVITY_SUPPORT_NOT_ROBUST_RV"
    elif opposite_bonferroni:
        verdict = "NULL_AMPLIFICATION_WITH_OPPOSITE_RALLY_DECOMPRESSION"
    else:
        verdict = "NULL_MEMORY_CUE_PROXY"

    result = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "source": "yfinance daily adjusted OHLCV for US ETFs and ^VIX",
            "download_window": {"start": START, "end": END},
            "asset_tickers": ASSET_TICKERS,
            "control_tickers": CONTROL_TICKERS,
            "asset_panel_rows": int(len(panel)),
            "aggregate_rows": int(len(agg.dropna(subset=["loss_memory_lag1", "rally_memory_lag1"]))),
            "availability": availability.to_dict(orient="records"),
        },
        "method": {
            "episode_library_window_days": LIBRARY_WINDOW,
            "episode_library_gap_days": LIBRARY_GAP,
            "extreme_episode_quantile": EXTREME_Q,
            "lookahead_guard": "raw memory cue computed at d; predictive variables use signal = raw_memory_cue.shift(1)",
            "primary_targets": PRIMARY_TARGETS,
            "signals": SIGNALS,
            "hac_lags": HAC_LAGS,
            "multiple_testing": f"Bonferroni 5% over {len(PRIMARY_TARGETS) * len(SIGNALS)} primary signal-target cells",
            "bootstrap": {
                "reps": BOOTSTRAP_REPS,
                "block_size_days": BOOTSTRAP_BLOCK,
                "seed": SEED,
            },
        },
        "primary_regressions": [asdict(c) | {"coef": _json_float(c.coef), "t_stat": _json_float(c.t_stat), "p_value": _json_float(c.p_value)} for c in cells],
        "harvey_expected_direction_passes": [asdict(c) for c in harvey_passes],
        "bonferroni_expected_direction_passes": [asdict(c) for c in primary_passes],
        "bonferroni_opposite_direction_cells": [asdict(c) for c in opposite_bonferroni],
        "best_abs_t_cell": best_cell,
        "bootstrap_best_cell": bootstrap,
        "event_spreads": [asdict(s) | {"high_mean": _json_float(s.high_mean), "other_mean": _json_float(s.other_mean), "high_minus_other": _json_float(s.high_minus_other)} for s in spreads],
        "per_ticker_summary": {
            "rows": int(len(ticker_regs)),
            "expected_direction_harvey_pass_count": int(((ticker_regs["t_stat"].abs() >= 3.0) & ticker_regs["expected_direction_pass"]).sum()) if not ticker_regs.empty else 0,
            "expected_direction_positive_share": _json_float(ticker_regs["expected_direction_pass"].mean()) if not ticker_regs.empty else None,
        },
        "figures": figure_paths,
        "limitations": [
            "This is not a replication of investor-level memory survey or transaction data.",
            "Sector ETF similarity cues are public-market proxies and may capture momentum/volatility clustering despite lagged controls.",
            "Daily OHLCV cannot observe news headline salience or investor recall directly.",
            "XLRE has shorter history; aggregate coverage varies over time.",
            "Per-ticker tests are secondary diagnostics and not promoted as independent discoveries.",
        ],
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "verdict": verdict, "result_path": str(RESULT_PATH), "figures": figure_paths}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
