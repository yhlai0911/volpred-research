from __future__ import annotations

from volpred.ops import writer_log


def test_append_writer_log_warns_but_does_not_raise_on_append_failure(monkeypatch, capsys):
    def _fail_path(storage_dir: str = "storage"):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(writer_log, "_writer_log_path", _fail_path)

    writer_log.append_writer_log(
        "memory",
        "memory/knowledge.json",
        record_id="K_test",
        actor="codex",
    )

    err = capsys.readouterr().err
    assert "[writer_log] WARN append failed" in err
    assert "memory/knowledge.json" in err
    assert "RuntimeError: disk unavailable" in err
