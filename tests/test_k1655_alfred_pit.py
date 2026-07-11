from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from statsmodels.tools.sm_exceptions import IterationLimitWarning


@pytest.fixture(scope="module")
def k1655():
    path = Path(__file__).resolve().parents[1] / "experiments" / "K1655" / "K1655.py"
    spec = importlib.util.spec_from_file_location("k1655_pit_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _history(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["realtime_start"] = pd.to_datetime(frame["realtime_start"])
    frame["realtime_end"] = pd.to_datetime(frame["realtime_end"], errors="coerce")
    return frame


def test_pit_blocks_prelaunch_and_selects_latest_active_observation(k1655):
    history = _history(
        [
            {
                "date": "2011-05-20",
                "realtime_start": "2011-05-25",
                "realtime_end": "2011-06-09",
                "value": -0.60,
            },
            {
                "date": "2011-05-20",
                "realtime_start": "2011-06-10",
                "realtime_end": None,
                "value": -0.70,
            },
            {
                "date": "2011-05-27",
                "realtime_start": "2011-06-02",
                "realtime_end": "2011-06-16",
                "value": -0.50,
            },
            {
                "date": "2011-06-03",
                "realtime_start": "2011-06-08",
                "realtime_end": None,
                "value": -0.40,
            },
        ]
    )
    origins = pd.to_datetime(["2011-05-20", "2011-05-27", "2011-06-03", "2011-06-10"])
    pit, audit = k1655.build_nfci_pit_weekly(
        history,
        origins,
        "2011-05-25",
        min_unique_values=2,
        max_information_lag_days=28,
    )

    assert np.isnan(pit.loc["2011-05-20", "nfci"])
    assert pit.loc["2011-05-27", "nfci"] == pytest.approx(-0.60)
    assert pit.loc["2011-06-03", "nfci"] == pytest.approx(-0.50)
    assert pit.loc["2011-06-10", "nfci"] == pytest.approx(-0.40)
    assert audit["pre_first_vintage_origins_excluded"] == 1
    assert all(audit["timing_gates"].values())


def test_realtime_end_is_inclusive_and_revision_switches_next_day(k1655):
    history = _history(
        [
            {
                "date": "2011-05-20",
                "realtime_start": "2011-05-25",
                "realtime_end": "2011-06-09",
                "value": 1.0,
            },
            {
                "date": "2011-05-20",
                "realtime_start": "2011-06-10",
                "realtime_end": None,
                "value": 2.0,
            },
        ]
    )
    index, _ = k1655._revision_index(history)
    on_end = k1655._active_revision_as_of(
        index, pd.Timestamp("2011-05-20"), pd.Timestamp("2011-06-09")
    )
    after_end = k1655._active_revision_as_of(
        index, pd.Timestamp("2011-05-20"), pd.Timestamp("2011-06-10")
    )
    assert on_end is not None and on_end[0] == pytest.approx(1.0)
    assert after_end is not None and after_end[0] == pytest.approx(2.0)


def test_overlapping_revision_intervals_fail_closed(k1655):
    history = _history(
        [
            {
                "date": "2011-05-20",
                "realtime_start": "2011-05-25",
                "realtime_end": "2011-06-10",
                "value": 1.0,
            },
            {
                "date": "2011-05-20",
                "realtime_start": "2011-06-01",
                "realtime_end": None,
                "value": 2.0,
            },
        ]
    )
    index, _ = k1655._revision_index(history)
    with pytest.raises(RuntimeError, match="Overlapping ALFRED revision intervals"):
        k1655._active_revision_as_of(
            index, pd.Timestamp("2011-05-20"), pd.Timestamp("2011-06-03")
        )


def test_old_two_column_final_vintage_cache_schema_is_rejected(k1655):
    old_cache = pd.DataFrame({"DATE": ["2011-05-20"], "VALUE": [-0.6]})
    with pytest.raises(ValueError, match="missing ALFRED columns"):
        k1655._validate_vintage_history(old_cache, "old final-vintage cache")


def test_full_history_fetch_paginates_and_pins_cache(k1655, monkeypatch, tmp_path):
    monkeypatch.setattr(k1655, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(k1655, "ALFRED_PAGE_LIMIT", 2)
    monkeypatch.setattr(k1655, "get_fred_api_key", lambda: "x" * 32)

    pages = {
        0: [
            {
                "date": "2011-01-07",
                "realtime_start": "2011-05-25",
                "realtime_end": "2011-06-01",
                "value": "-0.20",
            },
            {
                "date": "2011-01-07",
                "realtime_start": "2011-06-02",
                "realtime_end": "9999-12-31",
                "value": "-0.30",
            },
        ],
        2: [
            {
                "date": "2011-01-14",
                "realtime_start": "2011-05-25",
                "realtime_end": "9999-12-31",
                "value": "-0.25",
            }
        ],
    }

    def fake_request(url, params, label):
        if "vintagedates" in url:
            return {
                "count": 2,
                "vintage_dates": ["2011-05-25", "2011-06-02"],
            }
        offset = int(params["offset"])
        return {"count": 3, "observations": pages[offset]}

    monkeypatch.setattr(k1655, "_sanitized_json_request", fake_request)
    history, audit = k1655.fetch_alfred_vintage_history("NFCI", force_refresh=True)

    assert len(history) == 3
    assert audit["pages_fetched"] == 2
    assert audit["pagination_complete"] is True
    assert audit["first_public_vintage"] == "2011-05-25"
    assert history["realtime_end"].isna().sum() == 2
    cache = tmp_path / "alfred_NFCI_vintage_history.csv.gz"
    audit_path = tmp_path / "alfred_NFCI_vintage_audit.json"
    assert cache.exists() and audit_path.exists()
    pinned = json.loads(audit_path.read_text())
    assert pinned["cache_sha256"] == k1655.sha256_file(str(cache))


def test_full_history_fetch_rejects_early_empty_page(k1655, monkeypatch, tmp_path):
    monkeypatch.setattr(k1655, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(k1655, "ALFRED_PAGE_LIMIT", 2)
    monkeypatch.setattr(k1655, "get_fred_api_key", lambda: "x" * 32)

    def fake_request(url, params, label):
        if "vintagedates" in url:
            return {"count": 1, "vintage_dates": ["2011-05-25"]}
        if int(params["offset"]) == 0:
            return {
                "count": 3,
                "observations": [
                    {
                        "date": "2011-01-07",
                        "realtime_start": "2011-05-25",
                        "realtime_end": "9999-12-31",
                        "value": "-0.20",
                    },
                    {
                        "date": "2011-01-14",
                        "realtime_start": "2011-05-25",
                        "realtime_end": "9999-12-31",
                        "value": "-0.25",
                    },
                ],
            }
        return {"count": 3, "observations": []}

    monkeypatch.setattr(k1655, "_sanitized_json_request", fake_request)
    with pytest.raises(RuntimeError, match="pagination stopped early"):
        k1655.fetch_alfred_vintage_history("NFCI", force_refresh=True)


def test_http_failure_never_echoes_api_key(k1655, monkeypatch):
    secret = "a" * 32

    class FakeResponse:
        status_code = 400
        url = f"https://example.test?api_key={secret}"

        @staticmethod
        def json():
            return {"error_code": 400, "error_message": "bad request"}

    monkeypatch.setattr(k1655.requests, "get", lambda *args, **kwargs: FakeResponse())
    with pytest.raises(RuntimeError) as caught:
        k1655._sanitized_json_request(
            "https://example.test",
            {"api_key": secret},
            "secret-safety test",
        )
    assert secret not in str(caught.value)
    assert "request URL redacted" in str(caught.value)


def test_quantreg_iteration_limit_retries_then_resolves(k1655, monkeypatch):
    calls: list[int] = []

    class FakeResult:
        params = np.array([0.0, 0.0])

    class FakeModel:
        def __init__(self, y, x):
            pass

        def fit(self, *, q, max_iter, p_tol):
            calls.append(max_iter)
            if len(calls) == 1:
                import warnings

                warnings.warn("retry me", IterationLimitWarning)
            return FakeResult()

    monkeypatch.setattr(k1655, "QuantReg", FakeModel)
    k1655.FIT_DIAGNOSTICS.clear()
    k1655.FIT_DIAGNOSTICS.update(k1655._empty_fit_diagnostics())
    result = k1655.fit_quantreg(np.array([[1.0], [2.0]]), np.array([1.0, 2.0]), 0.05)

    assert result.params.tolist() == [0.0, 0.0]
    assert calls == [5_000, 20_000]
    assert k1655.FIT_DIAGNOSTICS["iteration_limit_retry_events"] == 1
    assert k1655.FIT_DIAGNOSTICS["unresolved_iteration_limit_failures"] == 0
