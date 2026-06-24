from __future__ import annotations

from pathlib import Path

from scripts.lookahead_audit import audit_file


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "experiment.py"
    path.write_text(text, encoding="utf-8")
    return path


def test_audit_file_warns_when_source_cannot_be_decoded(tmp_path: Path, capsys) -> None:
    path = tmp_path / "bad_encoding.py"
    path.write_bytes(b"\xff\xfe\xfa")

    findings = audit_file(path)

    captured = capsys.readouterr()
    assert findings == []
    assert "[lookahead_audit] WARN source read failed; skipping file" in captured.err
    assert "UnicodeDecodeError" in captured.err
    assert str(path) in captured.err


def test_arch_origin_aligned_oos_loss_is_flagged(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
res = am.fit(disp="off", last_obs=oos_start)
forecasts = res.forecast(horizon=1, start=oos_start, reindex=False)
common_idx = forecasts.index.intersection(realized_sq.index)
f_var = forecasts.loc[common_idx, "h.1"].to_numpy()
r_sq = realized_sq.loc[common_idx].to_numpy()
qlike = np.mean(np.log(f_var) + r_sq / f_var)
""",
    )

    findings = audit_file(path)

    assert findings
    assert findings[0]["shape"] == "arch_origin_forecast_alignment"
    assert findings[0]["has_lag_marker_nearby"] is False


def test_arch_target_aligned_oos_loss_is_verified(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
res = am.fit(disp="off", last_obs=oos_start)
forecasts = res.forecast(horizon=1, start=oos_start, reindex=False, align="target")
common_idx = forecasts.index.intersection(realized_sq.index)
f_var = forecasts.loc[common_idx, "h.1"].to_numpy()
r_sq = realized_sq.loc[common_idx].to_numpy()
qlike = np.mean(np.log(f_var) + r_sq / f_var)
""",
    )

    findings = audit_file(path)

    assert findings
    assert findings[0]["shape"] == "arch_origin_forecast_alignment"
    assert findings[0]["has_lag_marker_nearby"] is True
