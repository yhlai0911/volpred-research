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


def test_receipt_cannot_authorize_canonical_nonmachine_bytes(repo: Path):
    """A receipt is metadata, never proof that shared-checkout bytes are the worker's."""
    phase_z.write_fire_receipt(repo, subject="K1702 收件：raw-MDD 是 scale artifact",
                               body="掃 12 筆", task_id="k1702_followup")
    (repo / "out.txt").write_text("agent output\n")

    out = _fire(repo, baseline=set())

    assert out["committed"] is False
    assert out["reason"] == "nothing_owned"
    assert out["foreign"] == ["out.txt"]
    assert _subject(repo) == "seed"
    assert (repo / "out.txt").read_text() == "agent output\n"


def test_no_receipt_does_not_restore_legacy_timing_autoclaim(repo: Path):
    """Missing metadata cannot turn a canonical non-machine edit into PHASE-Z output."""
    (repo / "out.txt").write_text("agent output\n")
    alerts: list[dict] = []

    out = phase_z.run_phase_z(
        repo_root=repo, now_hhmm="07:07", pre_fire_dirty=set(),
        test_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
        alert_fn=lambda **k: alerts.append(k) or {},
    )

    assert out["committed"] is False
    assert out["reason"] == "nothing_owned"
    assert _subject(repo) == "seed"
    assert not [a for a in alerts if "沒交代原因" in a["title"]]


def test_normal_commit_no_longer_reads_as_a_failure(repo: Path):
    """Incident 1's *visible* half: the caption that made every healthy shift look broken.

    Pins the retired strings. If anyone reintroduces "safety-net auto-commit
    (agent left uncommitted)" on the normal path, the owner starts seeing
    「還是一直出錯啊」 again — and this test goes red first.
    """
    (repo / "storage" / "ops").mkdir(parents=True)
    (repo / "storage" / "ops" / "state.txt").write_text("x\n")

    _fire(repo, baseline=set())

    subject = _subject(repo)
    assert "safety-net" not in subject
    assert "left uncommitted" not in subject


def test_all_canonical_nonmachine_paths_are_never_swept_in(repo: Path):
    """Incident 2: the agent's `git add -A` stealing another session's work.

    Neither pre-fire nor mid-fire timing grants ownership after Issue #43 isolation.
    """
    (repo / "someone_elses.txt").write_text("interactive session, mid-edit\n")
    (repo / "mine.txt").write_text("this fire's output\n")
    phase_z.write_fire_receipt(repo, subject="只收自己的")

    out = _fire(repo, baseline={"someone_elses.txt"})  # dirty BEFORE the fire

    assert out["committed"] is False
    assert out["reason"] == "nothing_owned"
    assert set(out["foreign"]) == {"mine.txt", "someone_elses.txt"}
    assert _subject(repo) == "seed"
    assert (repo / "someone_elses.txt").exists()  # left in the tree for its author
    assert (repo / "mine.txt").exists()


def test_receipt_is_consumed_even_when_no_nonmachine_commit_is_authorized(repo: Path):
    """Incident 3 — the one that only a consume-on-read design prevents.

    Compatibility receipts may still arrive during rollout. Consume them even
    though they can no longer authorize shared-checkout non-machine bytes.
    """
    phase_z.write_fire_receipt(repo, subject="第一班的原因")
    (repo / "a.txt").write_text("a\n")
    _fire(repo, baseline=set())
    assert _subject(repo) == "seed"

    receipt_path = phase_z._receipt_path(repo, subprocess.run)
    assert receipt_path is not None
    assert not receipt_path.exists()


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
