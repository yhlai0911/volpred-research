#!/usr/bin/env python3
"""K1291 scaffold: DEX priority-fee pressure as crypto RV covariate.

This file is intentionally a scaffold. The task that created it explicitly said
not to run the experiment. No empirical result is computed here.

Implementation guardrails for the future full run:
- SEED is fixed.
- Chain-side signals must be lagged with ``signal.shift(1)`` before testing.
- Forward RV labels must use returns strictly after the forecast origin.
- OOS model-training rows must satisfy target_end < forecast_origin.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXPERIMENT_ID = "K1291"
SEED = 42
START = "2019-01-01"
END = "2026-06-30"
TRADING_DAYS = 365  # crypto trades every calendar day

ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "k1291_results.json"

PRIMARY_ASSETS = ("ETH-USD", "BTC-USD")
DIAGNOSTIC_ASSETS = ("COIN", "IBIT", "ETHA")
HORIZONS = (1, 5)


@dataclass(frozen=True)
class PlannedSignal:
    name: str
    source: str
    required: bool
    description: str


PLANNED_SIGNALS = (
    PlannedSignal(
        name="priority_fee_pressure",
        source="public Ethereum priority-fee / mempool-pressure source",
        required=True,
        description=(
            "Priority-fee pressure standardized by a rolling baseline ending at t-1. "
            "Must not be replaced by aggregate average gas price unless the verdict "
            "is downgraded to DATA_BLOCKED / proxy-only."
        ),
    ),
    PlannedSignal(
        name="base_fee_pressure",
        source="Ethereum base-fee source",
        required=True,
        description="Base-fee control to separate congestion trend from priority-fee pressure.",
    ),
    PlannedSignal(
        name="dex_volume_pressure",
        source="DefiLlama / Uniswap / reproducible DEX volume source",
        required=False,
        description="Secondary DEX liquidity-pressure proxy.",
    ),
)


def forward_realized_variance(log_returns: pd.Series, horizon: int) -> pd.Series:
    """Annualized forward RV over strictly future returns [t+1, t+horizon]."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    future_sq = log_returns.pow(2).shift(-1)
    return future_sq.iloc[::-1].rolling(horizon, min_periods=horizon).sum().iloc[::-1] * (
        TRADING_DAYS / horizon
    )


def build_price_targets(close: pd.DataFrame) -> pd.DataFrame:
    """Build future RV labels and lagged price-only controls.

    No same-day signal/target comparison is allowed. All controls are lagged.
    """
    out = pd.DataFrame(index=close.index)
    for asset in PRIMARY_ASSETS:
        ret = np.log(close[asset]).diff()
        out[f"{asset}_ret_1d_lag1"] = ret.shift(1)
        out[f"{asset}_rv_1d_lag1"] = ret.pow(2).shift(1) * TRADING_DAYS
        out[f"{asset}_rv_5d_lag1"] = (
            ret.pow(2).rolling(5, min_periods=5).sum().shift(1) * (TRADING_DAYS / 5)
        )
        out[f"{asset}_rv_22d_lag1"] = (
            ret.pow(2).rolling(22, min_periods=22).sum().shift(1) * (TRADING_DAYS / 22)
        )
        for horizon in HORIZONS:
            rv = forward_realized_variance(ret, horizon)
            out[f"{asset}_fwd_log_rv_{horizon}d"] = np.log(rv)
            out[f"{asset}_target_end_pos_{horizon}d"] = np.arange(len(out)) + horizon
    return out


def rolling_zscore(raw_signal: pd.Series, window: int = 90) -> pd.Series:
    """Rolling z-score whose baseline excludes current date t."""
    mean = raw_signal.rolling(window, min_periods=window).mean().shift(1)
    std = raw_signal.rolling(window, min_periods=window).std(ddof=0).shift(1)
    return (raw_signal - mean) / std.replace(0.0, np.nan)


def apply_signal_lag(signals: pd.DataFrame) -> pd.DataFrame:
    """Apply mandatory t-1 signal lag.

    The explicit ``signal.shift(1)`` line is part of the scaffold contract.
    """
    lagged = pd.DataFrame(index=signals.index)
    for name, signal in signals.items():
        lagged[name] = signal.shift(1)
    return lagged


def build_signal_panel(raw_chain_data: pd.DataFrame) -> pd.DataFrame:
    """Convert raw chain-side data into lagged testable signals.

    Expected input columns for the full implementation:
    - priority_fee
    - base_fee
    - dex_volume
    """
    required = {"priority_fee", "base_fee"}
    missing = sorted(required - set(raw_chain_data.columns))
    if missing:
        raise ValueError(f"Missing required chain-side columns: {missing}")

    signals = pd.DataFrame(index=raw_chain_data.index)
    signals["priority_fee_pressure"] = rolling_zscore(np.log(raw_chain_data["priority_fee"]))
    signals["base_fee_pressure"] = rolling_zscore(np.log(raw_chain_data["base_fee"]))
    if "dex_volume" in raw_chain_data.columns:
        signals["dex_volume_pressure"] = rolling_zscore(np.log(raw_chain_data["dex_volume"]))
    return apply_signal_lag(signals)


def validate_oos_training_cutoff(
    train_positions: pd.Series,
    target_end_positions: pd.Series,
    forecast_position: int,
) -> bool:
    """Return True only if all training labels end before forecast origin."""
    if len(train_positions) != len(target_end_positions):
        raise ValueError("train_positions and target_end_positions length mismatch")
    return bool((target_end_positions.loc[train_positions.index] < forecast_position).all())


def placeholder_results() -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "status": "scaffold_only_not_run",
        "seed": SEED,
        "data_sources_planned": {
            "market": {
                "provider": "yfinance",
                "primary_assets": list(PRIMARY_ASSETS),
                "diagnostic_assets": list(DIAGNOSTIC_ASSETS),
                "price_field": "adjusted close / OHLCV",
            },
            "chain_side": [asdict(signal) for signal in PLANNED_SIGNALS],
        },
        "lookahead_policy": {
            "signal_lag": "apply_signal_lag() uses signal.shift(1)",
            "target_window": "forward RV labels use [t+1, t+H]",
            "oos_training_gate": "target_end < forecast_origin",
        },
        "planned_tests": {
            "primary_assets": list(PRIMARY_ASSETS),
            "horizons_days": list(HORIZONS),
            "primary_signals": [s.name for s in PLANNED_SIGNALS if s.required],
            "baseline": "HAR-style price-only RV regression",
            "augmented": "same baseline plus lagged chain-side pressure signal",
            "primary_metric": "OOS QLIKE or log-RV loss improvement vs fair baseline",
            "gate": "DM-HLN Harvey |t| > 3 after horizon-correct inference",
        },
        "result_fields_reserved": {
            "sample": None,
            "data_quality": None,
            "oos_loss_table": [],
            "dm_hln_tests": [],
            "hac_diagnostics": [],
            "verdict": None,
        },
        "research_honesty_notes": [
            "No empirical results have been computed.",
            "Do not claim priority-fee alpha unless a true priority-fee source is available.",
            "If only average gas price is available, use K1566 or mark K1291 DATA_BLOCKED/proxy-only.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-placeholder",
        action="store_true",
        help="Write the scaffold-only k1291_results.json schema.",
    )
    args = parser.parse_args()

    if args.write_placeholder:
        RESULTS_PATH.write_text(
            json.dumps(placeholder_results(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"wrote {RESULTS_PATH}")
        return 0

    print("K1291 scaffold only. Use --write-placeholder to regenerate k1291_results.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
