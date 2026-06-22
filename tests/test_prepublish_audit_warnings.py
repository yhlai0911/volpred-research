from pathlib import Path

from volpred.publisher.prepublish_audit import load_source_values


def test_load_source_values_warns_on_invalid_existing_results(tmp_path: Path, capsys):
    kdir = tmp_path / "experiments" / "k9999"
    kdir.mkdir(parents=True)
    (kdir / "k9999_results.json").write_text("{bad-json", encoding="utf-8")

    vals = load_source_values(["K9999"], root=str(tmp_path))

    assert vals == set()
    captured = capsys.readouterr()
    assert "[prepublish_audit] WARN source results JSON read failed; skipping" in captured.err
    assert "k9999_results.json" in captured.err
    assert "JSONDecodeError" in captured.err
