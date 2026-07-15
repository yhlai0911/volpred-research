"""Focused timing and feature-construction tests for K1718."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from experiments.k1718.k1718 import (
    _json_safe,
    build_frame,
    normalize_topix_vendor_scale,
    strict_asof_signal,
)


def test_strict_asof_never_uses_same_day_us_close() -> None:
    signal = pd.Series(
        [18.0, 21.0, 19.0],
        index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
    )
    targets = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    values, sources = strict_asof_signal(signal, targets)
    assert values.tolist() == [18.0, 21.0, 19.0]
    assert (sources.to_numpy() < targets.to_numpy()).all()


def test_har_features_end_at_previous_japan_return() -> None:
    dates = pd.bdate_range("2025-01-02", periods=45)
    close = pd.Series(100.0 * np.exp(np.linspace(0.0, 0.12, len(dates))), index=dates)
    ohlc = pd.DataFrame({"Open": close * 0.999, "Close": close}, index=dates)
    vix_dates = pd.bdate_range("2024-12-30", periods=50)
    vix = pd.Series(np.linspace(15.0, 20.0, len(vix_dates)), index=vix_dates)
    frame, diagnostics = build_frame(ohlc, vix, dates.min())
    target = frame.index[0]
    raw_r2 = np.log(close).diff().pow(2)
    assert np.isclose(frame.loc[target, "har_d"], np.log(raw_r2.shift(1).loc[target]))
    assert pd.Timestamp(frame.loc[target, "vix_source_date"]) < target
    assert diagnostics["duplicate_dates"] == 0


def test_topix_vendor_scale_normalization_is_explicit_and_continuous() -> None:
    dates = pd.to_datetime(
        [
            "2014-12-30",
            "2015-01-05",
            "2015-01-06",
            "2026-03-27",
            "2026-03-30",
            "2026-03-31",
            "2026-04-01",
        ]
    )
    frame = pd.DataFrame(
        {
            "Open": [1000.0, 100.0, 101.0, 100.0, 10.1, 10.2, 103.0],
            "Close": [1000.0, 100.0, 101.0, 100.0, 10.1, 10.2, 103.0],
        },
        index=dates,
    )
    normalized, diagnostics = normalize_topix_vendor_scale(frame)
    assert normalized.index.min() == pd.Timestamp("2015-01-05")
    assert np.isclose(normalized.loc["2026-03-30", "Close"], 101.0)
    assert np.isclose(normalized.loc["2026-03-31", "Open"], 102.0)
    assert diagnostics["pre_start_rows_dropped"] == 1
    assert diagnostics["official_split"]["ratio"] == "1:10"
    assert np.log(normalized["Close"]).diff().abs().max() < 0.05
    assert json.loads(json.dumps(_json_safe(diagnostics)))["vendor_rows_rescaled"] == [
        "2026-03-30T00:00:00",
        "2026-03-31T00:00:00",
    ]
