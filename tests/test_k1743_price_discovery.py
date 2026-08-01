from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from experiments.K1743.K1743 import _clean_common_panel


def _panel(*, rows: int = 200, bad_fx: dict[int, float] | None = None) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=rows, freq="B")
    frame = pd.DataFrame(
        {
            "us_Close": np.linspace(50.0, 60.0, rows),
            "tw_Close": np.linspace(300.0, 360.0, rows),
            "fx_Close": np.full(rows, 30.0),
        },
        index=index,
    )
    for offset, value in (bad_fx or {}).items():
        frame.iloc[offset, frame.columns.get_loc("fx_Close")] = value
    return frame


def test_clean_common_panel_drops_and_records_impossible_fx_ticks() -> None:
    panel = _panel(bad_fx={40: 1.8015})

    cleaned, diagnostics = _clean_common_panel(panel)

    assert len(cleaned) == 199
    assert diagnostics == {
        "fx_valid_range_twd_per_usd": [10.0, 100.0],
        "invalid_fx_count": 1,
        "invalid_fx_share": pytest.approx(0.005),
        "invalid_fx_observations": [
            {"date": "2020-02-26", "value": 1.8015},
        ],
        "action": "dropped_not_imputed",
    }
    assert 1.8015 not in cleaned["fx_Close"].tolist()


def test_clean_common_panel_fails_closed_on_material_fx_corruption() -> None:
    panel = _panel(rows=20, bad_fx={1: 1.8, 2: 3.7})

    with pytest.raises(RuntimeError, match="FX corruption exceeds"):
        _clean_common_panel(panel)
