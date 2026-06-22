from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class _FailingDataManager:
    def get_model_data(self, *args, **kwargs):
        raise RuntimeError("vix unavailable")


class _EmptyDataManager:
    def get_model_data(self, *args, **kwargs):
        return []


def test_record_forecast_warning_structures_and_prints(capsys) -> None:
    from risk_forecast import _record_forecast_warning  # type: ignore

    warnings: list[dict] = []
    warning = _record_forecast_warning(
        warnings,
        "skewt_fit_failed",
        "SPY skewed-t fit failed; skewt VaR fields omitted",
        RuntimeError("no convergence"),
    )
    output = capsys.readouterr().out

    assert warnings == [warning]
    assert warning == {
        "code": "skewt_fit_failed",
        "message": "SPY skewed-t fit failed; skewt VaR fields omitted",
        "error": "RuntimeError: no convergence",
    }
    assert "SPY skewed-t fit failed" in output
    assert "RuntimeError: no convergence" in output


def test_spy_vix_garch_alert_records_lookup_failure(capsys) -> None:
    from risk_forecast import _append_spy_vix_garch_alert  # type: ignore

    alerts: list[dict] = []
    warnings: list[dict] = []
    _append_spy_vix_garch_alert(alerts, warnings, _FailingDataManager(), "SPY", 0.12)
    output = capsys.readouterr().out

    assert alerts == []
    assert warnings == [{
        "code": "vix_garch_lookup_failed",
        "message": "SPY VIX/GARCH ratio check failed; alert omitted",
        "error": "RuntimeError: vix unavailable",
    }]
    assert "VIX/GARCH ratio check failed" in output


def test_spy_vix_garch_alert_records_empty_lookup(capsys) -> None:
    from risk_forecast import _append_spy_vix_garch_alert  # type: ignore

    alerts: list[dict] = []
    warnings: list[dict] = []
    _append_spy_vix_garch_alert(alerts, warnings, _EmptyDataManager(), "SPY", 0.12)
    output = capsys.readouterr().out

    assert alerts == []
    assert warnings == [{
        "code": "vix_garch_lookup_empty",
        "message": "SPY VIX/GARCH ratio check skipped: ^VIX returned no rows",
    }]
    assert "^VIX returned no rows" in output


def test_try_fit_garch_sigma_records_history_failure(monkeypatch, capsys) -> None:
    import pandas as pd

    import risk_forecast  # type: ignore

    def _raise_fit_failure(_train_pct):
        raise RuntimeError("history fit failed")

    monkeypatch.setattr(risk_forecast, "_fit_garch_sigma_daily", _raise_fit_failure)

    warnings: list[dict] = []
    sigma = risk_forecast._try_fit_garch_sigma_daily(
        pd.Series([0.1, -0.2, 0.3]),
        warnings,
        code="sigma_history_fit_failed",
        message="SPY historical sigma GARCH fit failed at 2026-01-02; point omitted",
    )
    output = capsys.readouterr().out

    assert sigma is None
    assert warnings == [{
        "code": "sigma_history_fit_failed",
        "message": "SPY historical sigma GARCH fit failed at 2026-01-02; point omitted",
        "error": "RuntimeError: history fit failed",
    }]
    assert "history fit failed" in output


def test_try_fit_garch_sigma_records_ytd_failure_and_returns_fallback(monkeypatch, capsys) -> None:
    import pandas as pd

    import risk_forecast  # type: ignore

    def _raise_fit_failure(_train_pct):
        raise RuntimeError("ytd fit failed")

    monkeypatch.setattr(risk_forecast, "_fit_garch_sigma_daily", _raise_fit_failure)

    warnings: list[dict] = []
    sigma = risk_forecast._try_fit_garch_sigma_daily(
        pd.Series([0.1, -0.2, 0.3]),
        warnings,
        code="ytd_basel_sigma_fit_failed",
        message="SPY YTD Basel sigma GARCH fit failed at 2026-01-02; using current sigma fallback",
        fallback=0.0123,
    )
    output = capsys.readouterr().out

    assert sigma == 0.0123
    assert warnings == [{
        "code": "ytd_basel_sigma_fit_failed",
        "message": "SPY YTD Basel sigma GARCH fit failed at 2026-01-02; using current sigma fallback",
        "error": "RuntimeError: ytd fit failed",
    }]
    assert "using current sigma fallback" in output
