#!/usr/bin/env python3
"""Shared daily-panel builder for the P1 computation assets (Fig 1 + share CI).

Rebuilds the day-level strategy series (weights, gross returns, tx costs, net
returns, VoV regimes) from the bundled snapshot CSVs, following
reproduce.compute_insurance_decomposition line-for-line and reusing its
primitives (load_panel / classify_regime / apply_tx_cost / constants) so no
second convention can drift in. reproduce.py itself only returns aggregated
summaries, which is why the day-level series are materialized here.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

PAPER_DIR = Path(__file__).resolve().parent.parent
if str(PAPER_DIR) not in sys.path:
    sys.path.insert(0, str(PAPER_DIR))

import reproduce  # noqa: E402  (paper/vt-insurance-cost/reproduce.py)


@dataclass(frozen=True)
class DailyPanel:
    dates: pd.DatetimeIndex
    spy_rets: np.ndarray          # log returns
    gld_rets: np.ndarray          # log returns
    vov_zscore_lag: np.ndarray
    regimes: np.ndarray           # str array incl. "Unknown"
    s1_weights: np.ndarray
    s2_weights: np.ndarray
    s1_tx: np.ndarray
    s2_tx: np.ndarray

    @property
    def s0_net(self) -> np.ndarray:
        return self.spy_rets

    @property
    def s1_gross(self) -> np.ndarray:
        return self.s1_weights * self.spy_rets

    @property
    def s2_gross(self) -> np.ndarray:
        return self.s2_weights * self.spy_rets

    @property
    def s1_net(self) -> np.ndarray:
        return self.s1_gross - self.s1_tx

    @property
    def s2_net(self) -> np.ndarray:
        return self.s2_gross - self.s2_tx

    @property
    def s4_net(self) -> np.ndarray:
        # Table 1 note: constant daily 50/50 weights, continuous costless
        # rebalancing (K811v2 convention: average of the two log returns).
        return 0.5 * self.spy_rets + 0.5 * self.gld_rets


def build_daily_panel() -> DailyPanel:
    data = reproduce.load_panel().copy()
    data["spy_ret"] = np.log(data["spy"] / data["spy"].shift(1))
    data["gld_ret"] = np.log(data["gld"] / data["gld"].shift(1))
    data["vix_chg_5d"] = data["vix"] - data["vix"].shift(5)
    data["vix_rising"] = (data["vix_chg_5d"] > 0).astype(int)
    data = data.dropna(subset=["spy_ret", "gld_ret", "vvix", "vix_rising"])

    vov_mean = data["vvix"].expanding(min_periods=60).mean()
    vov_std = data["vvix"].expanding(min_periods=60).std()
    data["vov_zscore_lag"] = ((data["vvix"] - vov_mean) / vov_std).shift(1)
    data["vix_rising_lag"] = data["vix_rising"].shift(1)
    data["vix_lag"] = data["vix"].shift(1)

    regimes = np.array(
        [
            reproduce.classify_regime(z, rising)
            for z, rising in zip(
                data["vov_zscore_lag"].to_numpy(),
                data["vix_rising_lag"].to_numpy(),
            )
        ]
    )

    spy_rets = data["spy_ret"].to_numpy(dtype=np.float64)
    vix_vals = data["vix_lag"].to_numpy(dtype=np.float64)

    s1_weights = np.where(
        np.isfinite(vix_vals) & (vix_vals > 0.0),
        np.minimum(reproduce.VT_TARGET / vix_vals, 1.0),
        1.0,
    )
    s2_weights = np.ones(len(data), dtype=np.float64)
    high_vov_rising = regimes == "HighVoV_Rising"
    s2_weights[high_vov_rising] = s1_weights[high_vov_rising]

    return DailyPanel(
        dates=data.index,
        spy_rets=spy_rets,
        gld_rets=data["gld_ret"].to_numpy(dtype=np.float64),
        vov_zscore_lag=data["vov_zscore_lag"].to_numpy(dtype=np.float64),
        regimes=regimes,
        s1_weights=s1_weights,
        s2_weights=s2_weights,
        s1_tx=reproduce.apply_tx_cost(s1_weights, reproduce.TX_COST_BPS_VT),
        s2_tx=reproduce.apply_tx_cost(s2_weights, reproduce.TX_COST_BPS_VT),
    )
