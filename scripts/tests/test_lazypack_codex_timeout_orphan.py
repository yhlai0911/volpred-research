"""Mechanical gate: a timed-out codex call must not keep writing (2026-07-11).

`gen_lazypack_codex._run_codex` used `subprocess.run(timeout=)`, which kills only
the process Python spawned. codex's own workers outlive it. On 2026-07-11 the
lazypack render for mile_531e4c87 timed out at 360s and was marked failed -- and
then the surviving worker wrote render_lazypack.py 11 minutes later. Fallout:

  * an unowned file sat in the worktree until PHASE-Z flagged it (3 shifts),
  * the "failed" job's script was never exercised by the repair rounds, so its
    broken layout (overflowing text) went unnoticed,
  * two earlier jobs (mile_b5e264a5, mile_de666838) were "rescued" by manually
    re-queuing them -- which only worked *because* the orphan had delivered the
    script. The pipeline was silently depending on a process it thought it killed.

The invariant: after `_run_codex` reports a timeout, nothing further lands on
disk. The fix is a dedicated process group + killpg; this test is its owner.

Run: uv run --extra dev python -m pytest scripts/tests/test_lazypack_codex_timeout_orphan.py -v
"""
from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from volpred.ops import termination

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "gen_lazypack_codex", ROOT / "scripts" / "gen_lazypack_codex.py")
glc = importlib.util.module_from_spec(_spec)
sys.modules["gen_lazypack_codex"] = glc
_spec.loader.exec_module(glc)

_agy_spec = importlib.util.spec_from_file_location(
    "gen_lazypack_agy",
    ROOT / "scripts" / "gen_lazypack_agy.py",
)
gla = importlib.util.module_from_spec(_agy_spec)
_agy_spec.loader.exec_module(gla)


@pytest.fixture(autouse=True)
def _isolated_termination_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        termination, "DEFAULT_LEDGER_PATH",
        tmp_path / "termination_intents.jsonl",
    )
    monkeypatch.setenv(
        termination.LEDGER_PATH_ENV,
        str(tmp_path / "termination_intents.jsonl"),
    )


# A codex stand-in that behaves like the real incident: it forks a worker which
# outlives the parent and writes the render script well after we gave up on it.
_FAKE_CODEX = """#!/bin/sh
cat > /dev/null
( sleep {delay}; echo "written by the orphan" > "{victim}" ) &
sleep {hang}
"""


class _FakeReceipt:
    def __init__(self, executable: str) -> None:
        self.resolved_executable = executable

    def environment(self) -> dict[str, str]:
        return {"VOLPRED_PROVIDER_ID": "codex-cli"}


@pytest.fixture()
def fake_codex(tmp_path, monkeypatch):
    victim = tmp_path / "render_lazypack.py"

    def _install(delay: float, hang: float) -> Path:
        script = tmp_path / "fake_codex"
        script.write_text(_FAKE_CODEX.format(
            delay=delay, hang=hang, victim=victim))
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setattr(glc, "CODEX_BIN", str(script))
        monkeypatch.setattr(
            glc,
            "authorize_provider_spawn",
            lambda **_kwargs: _FakeReceipt(str(script)),
        )
        monkeypatch.setattr(glc, "verify_spawn_receipt", lambda _receipt: None)
        return victim

    return _install


def test_provider_policy_denial_precedes_codex_popen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(glc, "CODEX_BIN", sys.executable)
    monkeypatch.setattr(
        glc,
        "authorize_provider_spawn",
        lambda **_kwargs: (_ for _ in ()).throw(
            glc.ProviderRegistryError("metered provider denied")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        glc.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail(
            "provider policy denial must precede Popen"
        ),
    )

    rc, detail = glc._run_codex(
        "prompt",
        tmp_path,
        timeout_s=10,
        model=None,
    )

    assert rc == 4
    assert "metered provider denied" in detail


def test_provider_policy_denial_precedes_agy_popen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(gla, "AGY_BIN", "/usr/local/bin/agy")
    monkeypatch.setattr(
        gla,
        "authorize_provider_spawn",
        lambda **_kwargs: (_ for _ in ()).throw(
            gla.ProviderRegistryError("unknown billing denied")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        gla.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail(
            "provider policy denial must precede Popen"
        ),
    )

    rc, detail = gla._run_agy(
        "prompt",
        tmp_path,
        timeout_s=10,
        model=None,
    )

    assert rc == 4
    assert "unknown billing denied" in detail


def test_timeout_kills_the_worker_not_just_the_parent(fake_codex, tmp_path):
    """The incident, reproduced: worker writes 2s after we time out at 1s."""
    victim = fake_codex(delay=2.0, hang=30.0)

    rc, tail = glc._run_codex("prompt", tmp_path, timeout_s=1.0, model=None)

    assert rc == 2, f"a timeout must report rc=2, got {rc}: {tail}"

    # Past the point where the orphan would have written. Before the fix this
    # file exists here -- that is the 3-shift PHASE-Z orphan, in miniature.
    time.sleep(3.0)
    assert not victim.exists(), (
        "codex's worker survived the timeout and wrote "
        f"{victim.name} anyway — the process group was not killed"
    )


# The escape the group-kill cannot see. The worker calls setsid() -- a brand-new
# session and process group -- so killpg(codex's group) never reaches it. This is
# what the real codex CLI does, and it is why the killpg fix shipped on
# 2026-07-11 still let mile_aa4713db's worker write render_lazypack.py 5 minutes
# after the job was declared dead on 2026-07-13. The old fake worker used
# `( ... ) &`, which STAYS in the group -- so the test passed while production
# kept bleeding orphans. A fake that cannot escape cannot prove we catch escapes.
_ESCAPING_CODEX = """#!{python}
import subprocess, sys, time
sys.stdin.read()
subprocess.Popen(
    [sys.executable, "-c",
     "import time; time.sleep({delay}); open({victim!r}, 'w').write('escaped')"],
    start_new_session=True,   # <-- setsid: leaves our process group entirely
)
time.sleep({hang})
"""


@pytest.fixture()
def escaping_codex(tmp_path, monkeypatch):
    """A codex stand-in whose worker setsid()s out of the process group."""
    victim = tmp_path / "render_lazypack.py"

    def _install(delay: float, hang: float) -> Path:
        script = tmp_path / "escaping_codex"
        script.write_text(_ESCAPING_CODEX.format(
            python=sys.executable, delay=delay, hang=hang, victim=str(victim)))
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setattr(glc, "CODEX_BIN", str(script))
        monkeypatch.setattr(
            glc,
            "authorize_provider_spawn",
            lambda **_kwargs: _FakeReceipt(str(script)),
        )
        monkeypatch.setattr(glc, "verify_spawn_receipt", lambda _receipt: None)
        return victim

    return _install


def test_timeout_kills_a_worker_that_escaped_the_process_group(
        escaping_codex, tmp_path):
    """mile_aa4713db, reproduced: the worker leaves the group, then writes.

    killpg alone returns cleanly here and the file lands anyway -- the exact
    shape of the two production incidents. Only a descendant-tree kill catches it.
    """
    victim = escaping_codex(delay=3.0, hang=30.0)

    rc, tail = glc._run_codex("prompt", tmp_path, timeout_s=1.0, model=None)

    assert rc == 2, f"a timeout must report rc=2, got {rc}: {tail}"

    time.sleep(5.0)  # past the escaped worker's write
    assert not victim.exists(), (
        "a worker that setsid()'d out of codex's process group survived the "
        f"timeout and wrote {victim.name} anyway — killpg cannot reach it, so "
        "the kill must walk the descendant tree (procutil.kill_tree)"
    )


def test_process_group_is_severed_from_our_own(fake_codex, tmp_path):
    """killpg must target codex's group, never the group running the tests."""
    fake_codex(delay=0.1, hang=30.0)
    ours = os.getpgrp()

    glc._run_codex("prompt", tmp_path, timeout_s=1.0, model=None)

    assert os.getpgrp() == ours, "we signalled our own process group"


def test_write_budget_scales_with_panel_count():
    """A flat 360s starved the 3-panel plan that needed ~1020s (mile_531e4c87).

    That 1020s is measured, not guessed: the orphan that outlived the 360s
    timeout finished its write 11 minutes after the job was declared dead.
    """
    one = glc._codex_write_timeout([{"name": "a"}])
    three = glc._codex_write_timeout([{"name": x} for x in "abc"])

    assert three > one, "more panels must buy more write budget"
    assert three >= 1020, (
        f"a 3-panel plan gets {three:.0f}s — the plan that broke needed ~1020s"
    )
    assert glc._codex_write_timeout([{"name": str(i)} for i in range(50)]) \
        <= glc.CODEX_WRITE_CEILING_S, "the budget must stay bounded"


def test_clean_exit_still_returns_codex_rc(tmp_path, monkeypatch):
    """The rewrite must not break the happy path: rc flows through untouched."""
    script = tmp_path / "fake_codex_ok"
    script.write_text("#!/bin/sh\ncat > /dev/null\necho hello\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(glc, "CODEX_BIN", str(script))
    monkeypatch.setattr(
        glc,
        "authorize_provider_spawn",
        lambda **_kwargs: _FakeReceipt(str(script)),
    )
    monkeypatch.setattr(glc, "verify_spawn_receipt", lambda _receipt: None)

    rc, tail = glc._run_codex("prompt", tmp_path, timeout_s=30.0, model=None)

    assert rc == 0, f"clean codex run reported rc={rc}"
    assert "hello" in tail, "stdout was dropped by the Popen rewrite"


def test_missing_codex_binary_reports_rc3(tmp_path, monkeypatch):
    monkeypatch.setattr(glc, "CODEX_BIN", str(tmp_path / "definitely-not-here"))

    rc, tail = glc._run_codex("prompt", tmp_path, timeout_s=5.0, model=None)

    assert rc == 3, f"a missing codex CLI must stay rc=3, got {rc}: {tail}"


@pytest.mark.parametrize(
    "relative_path",
    [
        "storage/lazypack_jobs/mile_direct/panels/mile_direct_article.md",
        (
            "storage/lazypack_jobs/mile_isolated/runs/lazypack-mile_isolated/"
            "panels/mile_isolated_article.md"
        ),
    ],
)
def test_derived_article_snapshot_is_gitignored_in_every_job_layout(relative_path):
    """Run isolation added one directory level; scratch inputs must stay ignored."""

    result = subprocess.run(
        ["git", "check-ignore", "--quiet", relative_path],
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0, (
        f"derived lazypack article snapshot is not ignored: {relative_path}"
    )
