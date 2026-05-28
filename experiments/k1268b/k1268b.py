#!/usr/bin/env python3
"""
K1268b scaffold: GDELT 5-minute bars vs SPY 5-minute realized variance.

This file intentionally stops at a reviewable scaffold. It does not ship a
live Polygon/Databento adapter or execute the experiment end-to-end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "k1268b"
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1268_DIR = PROJECT_ROOT / "experiments" / "k1268"
GDELT_PATH = K1268_DIR / "gdelt_5min_bars.parquet"
RESULTS_PATH = SCRIPT_DIR / "k1268b_results.json"
CRISIS_DATES = ("2020-03-12", "2023-03-13", "2024-08-05")
LAG_BARS = (1, 2, 3, 6)


@dataclass(frozen=True)
class IntradaySourceConfig:
    name: str
    bars_path: Path | None = None
    timestamp_col: str = "timestamp"
    price_col: str = "close"


def load_gdelt_bars(path: Path = GDELT_PATH) -> pd.DataFrame:
    """Load K1268's pre-fetched 5-minute GDELT bars."""
    if not path.exists():
        raise FileNotFoundError(f"Missing GDELT source parquet: {path}")
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        raise ValueError("Expected 'timestamp' column in GDELT parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def load_intraday_bars(config: IntradaySourceConfig) -> pd.DataFrame:
    """
    Load SPY intraday bars from a paid or self-hosted source export.

    The adapter is intentionally file-based in the scaffold so the main thread
    can review the methodology before wiring any vendor-specific API client.
    """
    if config.bars_path is None:
        raise ValueError("IntradaySourceConfig.bars_path is required")
    if not config.bars_path.exists():
        raise FileNotFoundError(
            "Backtest-grade intraday source unavailable. "
            f"Expected local export at: {config.bars_path}"
        )

    if config.bars_path.suffix == ".parquet":
        bars = pd.read_parquet(config.bars_path)
    else:
        bars = pd.read_csv(config.bars_path)

    required = {config.timestamp_col, config.price_col}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"Intraday bars missing required columns: {sorted(missing)}")

    bars[config.timestamp_col] = pd.to_datetime(bars[config.timestamp_col], utc=True)
    return bars.sort_values(config.timestamp_col).reset_index(drop=True)


def compute_5min_realized_variance(
    bars: pd.DataFrame,
    timestamp_col: str = "timestamp",
    price_col: str = "close",
) -> pd.DataFrame:
    """Aggregate intraday prices into 5-minute realized variance."""
    ts = pd.to_datetime(bars[timestamp_col], utc=True)
    px = pd.Series(bars[price_col].astype(float).to_numpy(), index=ts)
    log_ret = np.log(px / px.shift(1))
    rv5 = log_ret.pow(2).groupby(pd.Grouper(freq="5min")).sum(min_count=1)
    out = rv5.rename("rv5").dropna().reset_index().rename(columns={"index": "timestamp"})
    return out


def build_lagged_gdelt_features(
    gdelt_bars: pd.DataFrame,
    signal_cols: Iterable[str],
    lags: tuple[int, ...] = LAG_BARS,
) -> pd.DataFrame:
    """
    Build causal lagged predictors.

    Hard research-honesty rule: use signal from t-1, target at t.
    The explicit signal.shift(1) below is the first lag; higher lags stack on top.
    """
    features = gdelt_bars.copy()
    features = features.sort_values("timestamp").reset_index(drop=True)
    for col in signal_cols:
        shifted = features[col].shift(1)  # signal.shift(1): no same-bar leakage
        features[f"{col}_lag1"] = shifted
        for lag in lags:
            if lag == 1:
                continue
            features[f"{col}_lag{lag}"] = shifted.shift(lag - 1)
    return features


def align_features_and_target(
    gdelt_features: pd.DataFrame,
    spy_rv5: pd.DataFrame,
) -> pd.DataFrame:
    merged = gdelt_features.merge(spy_rv5, on="timestamp", how="inner")
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    return merged


def scaffold_manifest() -> dict:
    gdelt_exists = GDELT_PATH.exists()
    return {
        "experiment_id": EXPERIMENT_ID,
        "status": "scaffold_only",
        "seed": SEED,
        "crisis_dates": list(CRISIS_DATES),
        "lag_bars": list(LAG_BARS),
        "gdelt_path": str(GDELT_PATH),
        "gdelt_path_exists": gdelt_exists,
        "required_intraday_sources": [
            "polygon_paid_export",
            "databento_export",
            "self_hosted_spy_1min_archive",
        ],
        "next_step": "Wire IntradaySourceConfig to a local paid-data export and run main-thread review.",
    }


def main() -> None:
    manifest = scaffold_manifest()
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
