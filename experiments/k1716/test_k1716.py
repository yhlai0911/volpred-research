import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


MODULE_PATH = Path(__file__).with_name("K1716.py")
SPEC = importlib.util.spec_from_file_location("k1716_module", MODULE_PATH)
K1716 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(K1716)


def test_holm_adjust_is_monotone_and_bounded():
    adjusted = K1716.holm_adjust({"a": 0.01, "b": 0.03, "c": 0.20})
    assert adjusted == {"a": 0.03, "b": 0.06, "c": 0.20}


def test_prepare_daily_uses_previous_close_for_overnight():
    raw = pd.DataFrame(
        {
            "Date": pd.date_range("2022-01-03", periods=8, freq="B"),
            "Open": [100, 102, 101, 103, 104, 105, 106, 107],
            "High": [102, 103, 103, 105, 106, 107, 108, 109],
            "Low": [99, 100, 100, 102, 103, 104, 105, 106],
            "Close": [101, 101, 102, 104, 105, 106, 107, 108],
            "Adj Close": [101, 101, 102, 104, 105, 106, 107, 108],
            "Volume": [1_000] * 8,
        }
    )
    daily, checks = K1716.prepare_daily(raw)
    expected = np.log(102 / 101) ** 2
    assert np.isclose(daily.iloc[1]["overnight_var"], expected)
    assert checks["invalid_ohlc_rows_removed"] == 0


def test_point_in_time_controls_are_lagged():
    raw = pd.DataFrame(
        {
            "Date": pd.date_range("2022-01-03", periods=10, freq="B"),
            "Open": np.arange(100, 110, dtype=float),
            "High": np.arange(102, 112, dtype=float),
            "Low": np.arange(99, 109, dtype=float),
            "Close": np.arange(101, 111, dtype=float),
            "Adj Close": np.arange(101, 111, dtype=float),
            "Volume": [1_000] * 10,
        }
    )
    daily, _ = K1716.prepare_daily(raw)
    expected = np.log(daily["proxy_total_var"].clip(lower=K1716.EPS)).rolling(5).mean().shift(1)
    pd.testing.assert_series_equal(daily["lag5_log_total"], expected, check_names=False)


def test_atomic_json_writer_round_trips(tmp_path):
    path = tmp_path / "result.json"
    payload = {"verdict": "NULL", "values": [1, 2, 3]}
    K1716.atomic_write_json(path, payload)
    assert path.read_text(encoding="utf-8").endswith("\n")
    import json

    assert json.loads(path.read_text(encoding="utf-8")) == payload
