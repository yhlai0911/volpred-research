from __future__ import annotations

from scripts import collect_vixtwn


def test_fetch_month_warns_and_skips_bad_numeric_rows(monkeypatch, capsys) -> None:
    payload = (
        "20260601\t\t\t\tbad\t\t18.0\n"
        "20260602\t\t\t\t18.1\t\t18.2\n"
    ).encode("utf-8")

    class Response:
        content = payload
        text = payload.decode("utf-8")

        def raise_for_status(self):
            return None

    monkeypatch.setattr(collect_vixtwn.requests, "get", lambda *args, **kwargs: Response())

    records = collect_vixtwn.fetch_month("202606")

    captured = capsys.readouterr()
    assert records == [
        {
            "date": "2026-06-02",
            "vixtwn_close": 18.1,
            "vixtwn_1min_avg": 18.2,
        }
    ]
    assert "[collect_vixtwn] WARN row parse failed; skipping row" in captured.err
    assert "year_month=202606" in captured.err
    assert "line_no=1" in captured.err
    assert "ValueError" in captured.err
