from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_sb_count_warns_when_head_count_falls_back(monkeypatch, capsys) -> None:
    import list_new_strategy as lns  # type: ignore

    monkeypatch.setattr(lns, "_init_supabase", lambda: None)
    monkeypatch.setattr(lns, "_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(lns, "_headers", lambda: {})

    def _fail_head(*args, **kwargs):
        raise RuntimeError("head unavailable")

    monkeypatch.setattr(lns, "urlopen", _fail_head)
    monkeypatch.setattr(lns, "_sb_select", lambda *args, **kwargs: [{"id": 1}, {"id": 2}])

    count = lns._sb_count("strategy_signals", strategy_key="demo")
    output = capsys.readouterr().out

    assert count == 2
    assert "count HEAD failed; falling back to GET count" in output
    assert "RuntimeError: head unavailable" in output


def test_step_9_warns_when_howto_fetch_fails(monkeypatch, capsys) -> None:
    import list_new_strategy as lns  # type: ignore

    def _raise_select(*args, **kwargs):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(lns, "_sb_select", _raise_select)

    lister = lns.StrategyLister(key="demo_strategy")
    result = lister.step_9_check_howto()
    output = capsys.readouterr().out

    assert result is False
    assert lister.results["9_howto"] == "MISSING"
    assert "howto fetch failed during Step 9" in output
    assert "RuntimeError: supabase down" in output
