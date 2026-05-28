from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "daily_update_launchagent_observation.py"
)
SPEC = importlib.util.spec_from_file_location("daily_update_launchagent_observation", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_expected_fire_points_for_observation_window():
    fires = module._expected_fire_points(
        "3 8 * * 1-6",
        start=module.WINDOW_START,
        end=module.WINDOW_END,
    )
    iso_dates = [dt.date().isoformat() for dt in fires]
    assert iso_dates == [
        "2026-05-26",
        "2026-05-27",
        "2026-05-28",
        "2026-05-29",
        "2026-05-30",
        "2026-06-01",
    ]


def test_match_observed_dates_marks_future_and_missing():
    expected = [
        datetime(2026, 5, 26, 8, 3, tzinfo=module.LOCAL_TZ),
        datetime(2026, 5, 27, 8, 3, tzinfo=module.LOCAL_TZ),
    ]
    observed = [datetime(2026, 5, 26, 8, 10, tzinfo=module.LOCAL_TZ)]
    result = module._match_observed_dates(
        expected,
        observed,
        as_of=datetime(2026, 5, 26, 23, 0, tzinfo=module.LOCAL_TZ),
    )
    assert result["miss_count_so_far"] == 0
    assert result["rows"][0]["status"] == "observed"
    assert result["rows"][1]["status"] == "future"
