from pathlib import Path

from volpred.ops import pending_replay


def test_mark_self_replayed_warns_on_invalid_pending_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    pending = tmp_path / "pending_sessions.json"
    pending.write_text("{bad-json", encoding="utf-8")
    monkeypatch.setattr(pending_replay, "PENDING_PATH", pending)

    updated = pending_replay.mark_self_replayed("continue_task")

    assert updated is False
    captured = capsys.readouterr()
    assert "[pending_replay] WARN pending_sessions read failed; replay marker not written" in captured.err
    assert "pending_sessions.json" in captured.err
    assert "JSONDecodeError" in captured.err
