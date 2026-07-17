"""PHASE-Z owns the commit; the agent owns only the reason (2026-07-13 3-strike).

Each test here pins one of the three incidents that produced the strike
(docs/refactor_plan_agent_output_ownership.md §1):

  1. 2026-07-12 21:29 / 22:16 / 23:30 — agent produced output, did not commit it,
     PHASE-Z's "safety-net" caption made a working shift read as a failing one.
  2. 2026-07-10 — the agent's own `git add -A` swept a foreign session's edits in.
  3. a receipt from one fire captioning the next fire's commit.

The load-bearing assertion is the LAST one: a receipt must not survive its fire.
Everything else here would still pass if `_read_and_consume_fire_receipt` merely
read without consuming — that is the bug this file exists to catch.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A hermetic repo — never the real one (per feedback_hermetic_git_in_tests)."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    _git(r, "config", "user.email", "t@t.t")
    _git(r, "config", "user.name", "t")
    hook = r / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    (r / "seed.txt").write_text("seed\n")
    _git(r, "add", "seed.txt")
    _git(r, "commit", "-qm", "seed")
    return r


def _subject(repo: Path) -> str:
    return _git(repo, "log", "-1", "--format=%s").strip()


def _fire(repo: Path, *, baseline: set[str] | list[str], **kw) -> dict:
    """Run PHASE-Z with the fire-start baseline injected (no daemon involved)."""
    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="07:07", pre_fire_dirty=baseline,
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: kw.setdefault("alerts", []).append(k) or {},
        **{k: v for k, v in kw.items() if k not in ("alerts",)},
    )


def test_receipt_becomes_the_commit_subject(repo: Path):
    """Incident 1: the shift's own account of WHY reaches git log."""
    phase_z.write_fire_receipt(repo, subject="K1702 收件：raw-MDD 是 scale artifact",
                               body="掃 12 筆", task_id="k1702_followup")
    (repo / "out.txt").write_text("agent output\n")

    out = _fire(repo, baseline=set())

    assert out["committed"] is True
    assert _subject(repo) == "dispatch(07:07): K1702 收件：raw-MDD 是 scale artifact"
    body = _git(repo, "log", "-1", "--format=%b")
    assert "k1702_followup" in body and "掃 12 筆" in body


def test_no_receipt_still_commits_and_warns(repo: Path):
    """Incident 1, the failure mode: forgetting the receipt costs a MESSAGE, not the work.

    This is the whole point of moving git out of the prompt — the agent's
    unreliability now lands on an audit-quality axis, never on a data-loss one.
    """
    (repo / "out.txt").write_text("agent output\n")
    alerts: list[dict] = []

    out = phase_z.run_phase_z(
        repo_root=repo, now_hhmm="07:07", pre_fire_dirty=set(),
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: alerts.append(k) or {},
    )

    assert out["committed"] is True, "work must land even with no receipt"
    subject = _subject(repo)
    assert "未留 receipt" in subject
    # The 2026-07-17 fallback names WHAT moved (the diff knows that much) instead of
    # the old content-free 「本班產出未附說明」. It still cannot know WHY — that gap is
    # what the Stop gate exists to prevent, and what the warn below reports.
    assert "out.txt" in subject
    assert [a for a in alerts if a["level"] == "warn" and "沒交代原因" in a["title"]]


def test_normal_commit_no_longer_reads_as_a_failure(repo: Path):
    """Incident 1's *visible* half: the caption that made every healthy shift look broken.

    Pins the retired strings. If anyone reintroduces "safety-net auto-commit
    (agent left uncommitted)" on the normal path, the owner starts seeing
    「還是一直出錯啊」 again — and this test goes red first.
    """
    phase_z.write_fire_receipt(repo, subject="正常產出")
    (repo / "out.txt").write_text("x\n")

    _fire(repo, baseline=set())

    subject = _subject(repo)
    assert "safety-net" not in subject
    assert "left uncommitted" not in subject


def test_foreign_paths_are_never_swept_in(repo: Path):
    """Incident 2: the agent's `git add -A` stealing another session's work.

    PHASE-Z stages only what appeared AFTER the fire started; a path already dirty
    at fire start belongs to whoever is mid-edit on it.
    """
    (repo / "someone_elses.txt").write_text("interactive session, mid-edit\n")
    (repo / "mine.txt").write_text("this fire's output\n")
    phase_z.write_fire_receipt(repo, subject="只收自己的")

    out = _fire(repo, baseline={"someone_elses.txt"})  # dirty BEFORE the fire

    assert out["committed"] is True
    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert "mine.txt" in committed
    assert "someone_elses.txt" not in committed, "PHASE-Z committed a foreign path"
    assert (repo / "someone_elses.txt").exists()  # left in the tree for its author


def test_receipt_does_not_survive_its_fire(repo: Path):
    """Incident 3 — the one that only a consume-on-read design prevents.

    A fire that writes a receipt and commits must not leave it behind: the NEXT
    fire would then caption its own, unrelated commit with the previous shift's
    reasons — a false audit trail, which is worse than a generated one.
    """
    phase_z.write_fire_receipt(repo, subject="第一班的原因")
    (repo / "a.txt").write_text("a\n")
    _fire(repo, baseline=set())
    assert _subject(repo) == "dispatch(07:07): 第一班的原因"

    # Second fire: different work, no receipt of its own.
    (repo / "b.txt").write_text("b\n")
    _fire(repo, baseline=set())

    assert "第一班的原因" not in _subject(repo), "a stale receipt captioned the next fire"
    assert "未留 receipt" in _subject(repo)


def test_cli_refuses_mangled_cjk_argv_with_an_actionable_message(repo: Path):
    """CJK through a shell arg can arrive as lone surrogates.

    2026-07-14: `fire_receipt.py --body "<中文>"` died with
    `UnicodeEncodeError: surrogates not allowed` inside f.write() — an error that
    tells the caller nothing about the fix. The CLI must catch it at the argument
    boundary and name --body-file, the path that works.
    """
    import sys

    cli = Path(__file__).resolve().parents[1] / "fire_receipt.py"
    mangled = "\udc89".join(("本班", "修好了"))  # what a bad-bytes argv looks like after decoding

    res = subprocess.run(
        [sys.executable, str(cli), "--subject", "ok", "--body", mangled, "--repo-root", str(repo)],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )

    assert res.returncode == 2, f"mangled body was accepted:\n{res.stdout}{res.stderr}"
    assert "--body-file" in res.stderr, f"error does not name the fix:\n{res.stderr}"


def test_stale_receipt_is_refused(repo: Path):
    """A receipt older than a fire's lifetime describes a fire that never finished."""
    phase_z.write_fire_receipt(repo, subject="上上班留下的")
    path = phase_z._receipt_path(repo, subprocess.run)
    payload = json.loads(path.read_text())
    payload["written_at"] -= phase_z._RECEIPT_MAX_AGE_S + 60
    path.write_text(json.dumps(payload))

    (repo / "out.txt").write_text("x\n")
    _fire(repo, baseline=set())

    assert "上上班留下的" not in _subject(repo)
