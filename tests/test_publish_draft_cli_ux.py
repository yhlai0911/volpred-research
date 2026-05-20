"""Tests for CLI UX papercuts in publish_draft.py.

Background (2026-05-08, K852 mile_8dc39724 agent feedback):
    Three CLI ergonomics issues caught in production by daily_article agents:

      1. `--draft <path>` flag did not exist; agents reflexively typed
         `--draft <path>` and got argparse errors. Only positional accepted.
      2. `--phase` was mandatory; agents had to specify it even when the
         frontmatter already declared it (no fallback default).
      3. Drafts in `/tmp/` raised `ValueError: <path> is not in subpath of
         <repo>` because `parse_draft()` / print() called `path.relative_to(ROOT)`
         which only works for paths under the repo.

    Per CLAUDE.md "永遠修流程，不修資料" the publisher must accept these
    forms cleanly so agents stop hitting recurring friction.

Test surface:
    - --draft flag accepted as alias for positional
    - --phase defaults to 'research' when absent + no frontmatter phase
    - frontmatter `phase:` overrides CLI default
    - explicit --phase overrides frontmatter phase
    - /tmp/ draft paths read successfully
    - existing positional path still works (no regression)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import publish_draft  # noqa: E402


def _write_draft(path: Path, frontmatter: dict | None, body: str = "Body content.") -> None:
    if frontmatter is None:
        path.write_text(body, encoding="utf-8")
        return
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, list):
            fm_lines.append(f"{k}: [{', '.join(v)}]")
        else:
            fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append(body)
    path.write_text("\n".join(fm_lines), encoding="utf-8")


# Stub subprocess.run so tests don't actually call the publisher CLI; capture
# the args we'd pass instead.
class _StubResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# --draft flag alias
# ---------------------------------------------------------------------------


def test_draft_flag_accepted_as_positional_alias(tmp_path, monkeypatch, capsys):
    """`--draft <path>` works the same as positional."""
    draft = tmp_path / "test.md"
    _write_draft(draft, {
        "title": "Test",
        "audience": "general",
        "tags": ["a", "b"],
    },
    body="Body para.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n",
    )

    captured_cmd = []

    def _fake_run(cmd, *a, **k):
        captured_cmd.append(cmd)
        return _StubResult(0, "ok", "")

    monkeypatch.setattr(publish_draft.subprocess, "run", _fake_run)
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        "--draft", str(draft),
        "--phase", "robustness",
        "--force-duplicate",
    ])
    rc = publish_draft.main()
    assert rc == 0
    assert captured_cmd, "publisher CLI should have been invoked"


def test_positional_still_works(tmp_path, monkeypatch):
    """Existing positional path still works (no regression)."""
    draft = tmp_path / "test.md"
    _write_draft(draft, {
        "title": "Test",
        "audience": "general",
        "tags": ["a"],
    },
    body="Body para.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n",
    )

    captured = []
    monkeypatch.setattr(publish_draft.subprocess, "run",
                        lambda cmd, *a, **k: (captured.append(cmd) or _StubResult(0)))
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        str(draft),  # positional
        "--phase", "research",
        "--force-duplicate",
    ])
    rc = publish_draft.main()
    assert rc == 0
    assert captured


def test_draft_flag_wins_when_both_provided(tmp_path, monkeypatch):
    """If both positional and --draft given, --draft wins (explicit-flag preference)."""
    draft_pos = tmp_path / "positional.md"
    draft_flag = tmp_path / "flag.md"
    _write_draft(draft_pos, {"title": "POS", "audience": "general", "tags": ["a"]},
                 body="Pos body.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n")
    _write_draft(draft_flag, {"title": "FLAG", "audience": "general", "tags": ["a"]},
                 body="Flag body.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n")

    captured_titles = []

    def _fake_run(cmd, *a, **k):
        # Capture --title arg
        for i, c in enumerate(cmd):
            if c == "--title":
                captured_titles.append(cmd[i + 1])
        return _StubResult(0)

    monkeypatch.setattr(publish_draft.subprocess, "run", _fake_run)
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        str(draft_pos),
        "--draft", str(draft_flag),
        "--phase", "research",
        "--force-duplicate",
    ])
    rc = publish_draft.main()
    assert rc == 0
    assert captured_titles == ["FLAG"], f"--draft should win: {captured_titles}"


def test_no_draft_path_returns_error(monkeypatch, capsys):
    """No positional and no --draft → error message + exit 1."""
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        "--phase", "research",
    ])
    rc = publish_draft.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "draft path required" in err.lower()


# ---------------------------------------------------------------------------
# --phase default = 'research' + frontmatter precedence
# ---------------------------------------------------------------------------


def test_phase_defaults_to_research_when_absent(tmp_path, monkeypatch):
    """No --phase + no frontmatter phase → defaults to 'research'."""
    draft = tmp_path / "test.md"
    _write_draft(draft, {"title": "T", "audience": "general", "tags": ["a"]},
                 body="Body.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n")

    captured_phases = []

    def _fake_run(cmd, *a, **k):
        for i, c in enumerate(cmd):
            if c == "--phase":
                captured_phases.append(cmd[i + 1])
        return _StubResult(0)

    monkeypatch.setattr(publish_draft.subprocess, "run", _fake_run)
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        str(draft),
        "--force-duplicate",
        # no --phase
    ])
    rc = publish_draft.main()
    assert rc == 0
    assert captured_phases == ["research"], f"expected 'research' default, got {captured_phases}"


def test_frontmatter_phase_overrides_default(tmp_path, monkeypatch):
    """frontmatter `phase:` overrides default when --phase not provided."""
    draft = tmp_path / "test.md"
    _write_draft(draft, {
        "title": "T",
        "audience": "general",
        "phase": "robustness",
        "tags": ["a"],
    },
    body="Body.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n",
    )

    captured_phases = []

    def _fake_run(cmd, *a, **k):
        for i, c in enumerate(cmd):
            if c == "--phase":
                captured_phases.append(cmd[i + 1])
        return _StubResult(0)

    monkeypatch.setattr(publish_draft.subprocess, "run", _fake_run)
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        str(draft),
        "--force-duplicate",
    ])
    rc = publish_draft.main()
    assert rc == 0
    assert captured_phases == ["robustness"]


def test_explicit_phase_overrides_frontmatter(tmp_path, monkeypatch):
    """Explicit --phase wins over frontmatter phase (CLI is explicit override surface)."""
    draft = tmp_path / "test.md"
    _write_draft(draft, {
        "title": "T",
        "audience": "general",
        "phase": "robustness",  # frontmatter says robustness
        "tags": ["a"],
    },
    body="Body.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n",
    )

    captured_phases = []

    def _fake_run(cmd, *a, **k):
        for i, c in enumerate(cmd):
            if c == "--phase":
                captured_phases.append(cmd[i + 1])
        return _StubResult(0)

    monkeypatch.setattr(publish_draft.subprocess, "run", _fake_run)
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        str(draft),
        "--phase", "tail-risk",  # CLI override
        "--force-duplicate",
    ])
    rc = publish_draft.main()
    assert rc == 0
    assert captured_phases == ["tail-risk"]


# ---------------------------------------------------------------------------
# /tmp/ paths accepted (no relative_to subpath restriction)
# ---------------------------------------------------------------------------


def test_tmp_path_draft_publishes_without_subpath_error(tmp_path, monkeypatch, capsys):
    """A draft in /tmp-style path (outside repo) publishes without ValueError."""
    # tmp_path itself is outside repo (pytest tmp); use it directly to simulate
    # /tmp/test.md scenarios. The bug surfaced at the print-line
    # `draft_path.relative_to(ROOT)` which raises ValueError outside repo.
    draft = tmp_path / "out_of_repo_draft.md"
    _write_draft(draft, {
        "title": "OutOfRepo",
        "audience": "general",
        "tags": ["a"],
    },
    body="Body.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n",
    )

    monkeypatch.setattr(publish_draft.subprocess, "run",
                        lambda cmd, *a, **k: _StubResult(0))
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        str(draft),  # absolute, NOT under ROOT
        "--phase", "research",
        "--force-duplicate",
    ])
    # Critical: no ValueError raised before publisher invocation
    rc = publish_draft.main()
    assert rc == 0
    out = capsys.readouterr().out
    # The print should display the absolute path verbatim, not crash
    assert str(draft) in out or draft.name in out


# ---------------------------------------------------------------------------
# Combined: --draft + frontmatter phase + tmp path (regression)
# ---------------------------------------------------------------------------


def test_draft_flag_with_tmp_path_and_frontmatter_phase(tmp_path, monkeypatch):
    """All three fixes working together: --draft + tmp path + frontmatter phase."""
    draft = tmp_path / "combined.md"
    _write_draft(draft, {
        "title": "Combined",
        "audience": "general",
        "phase": "tail-risk",
        "tags": ["a"],
    },
    body="Body.\n\n![x](https://example.com/a.png)\n![y](https://example.com/b.png)\n",
    )

    captured = {}

    def _fake_run(cmd, *a, **k):
        for i, c in enumerate(cmd):
            if c == "--phase":
                captured["phase"] = cmd[i + 1]
            elif c == "--title":
                captured["title"] = cmd[i + 1]
        return _StubResult(0)

    monkeypatch.setattr(publish_draft.subprocess, "run", _fake_run)
    monkeypatch.setattr(sys, "argv", [
        "publish_draft.py",
        "--draft", str(draft),
        "--force-duplicate",
        # no --phase, expecting frontmatter to win
    ])
    rc = publish_draft.main()
    assert rc == 0
    assert captured.get("phase") == "tail-risk"
    assert captured.get("title") == "Combined"
