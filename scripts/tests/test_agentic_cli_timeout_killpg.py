"""Class gate: a timed-out agentic CLI must be killed as a process group.

`subprocess.run(timeout=)` / `communicate(timeout=)` kill exactly one pid — the one
Python spawned. An *agentic* CLI (`claude`, `codex`, `agy`) does its real work in
subprocesses of its own. Kill only the parent and those children survive, reparent
to init, and keep running: writing files, burning quota, committing nothing, with
no supervisor left to collect them. The job is marked `failed` while the work is
still happening. "Timed out" and "still running" become the same observation.

This has now happened three times, in three different files:

  2026-07-11  gen_lazypack_codex   codex worker outlived its kill and wrote
                                   render_lazypack.py 11 minutes after the job failed
  2026-07-12  run_agent_job        agent killed at its bound; its compute child kept
                                   going and wrote a 37KB K1685 results.json 24 min
                                   later, into a worktree nobody was going to merge
  2026-07-12  scan_trending_agy    `agy -p` under subprocess.run(timeout=180) — same
                                   shape, found by the sweep this gate came from

The first fix was scoped to gen_lazypack_codex and guarded by a behavioural test on
that one file. The bug came back the next day in a file that test could not see. So
the gate belongs at the level of the CLASS, which is what this is: it does not care
which file you are writing, only that if you put a timeout on an agentic CLI you
must also be able to kill what it spawned.

The invariant, per file:
    spawns an agentic CLI  AND  bounds it with a timeout
        =>  spawns with start_new_session=True   (gives it its own process group)
        AND kills that group on timeout          (procutil.kill_pgid, or os.killpg)

`scripts.dispatch_supervisor.procutil.kill_pgid` is the owner of the kill itself
(SIGTERM -> grace -> SIGKILL, macOS EPERM fallback to per-pid, confirms the group is
gone). Prefer it over a hand-rolled killpg; every hand-rolled copy is a place the
next person forgets.

Run: uv run --extra dev python -m pytest scripts/tests/test_agentic_cli_timeout_killpg.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SEARCH_DIRS = ("scripts", "src")

# Binaries that spawn subprocesses of their own. Launching one of these means the
# pid you hold is not the work — it is only the root of the work.
AGENTIC_MARKERS = ("claude", "codex", "agy")

SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}
TIMEOUT_CALLS = {"run", "call", "check_call", "check_output", "communicate", "wait"}

# Files that launch an agentic CLI but genuinely need no group kill, with the reason.
# Keep this list short and argued; it is the blind spot of this gate.
EXEMPT: dict[str, str] = {
    # Detached, deliberately outlives us: the fire is *meant* to keep running after
    # the launcher returns, and the supervisor owns its lifecycle (and does killpg).
    "scripts/dispatch_supervisor/worker.py": "supervisor owns the fire lifecycle; already killpgs via procutil",
}

# Known-unfixed instances, frozen. This is a debt ledger, not an exemption: these
# files DO leak orphans on timeout. They are listed so the gate can still fail on
# anything NEW while a real fix is scheduled, rather than being switched off.
#
# The number may only go DOWN. Fixing one = delete its line. Adding one is not a
# thing you may do — the assertion below fails on any file not already listed.
KNOWN_UNFIXED: dict[str, str] = {
    "src/volpred/ops/execution_brief.py": (
        "3 x subprocess.run(['claude', '-p', ...], timeout=...) in the coordinator/executor "
        "retry loops. Needs the same Popen + start_new_session + kill_pgid treatment, but it "
        "sits on a src/ publishing path with retry semantics worth verifying properly rather "
        "than at the tail of a dispatch fire. Queued: platform_ops_execution_brief_killpg."
    ),
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for d in SEARCH_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            rel = p.relative_to(ROOT).as_posix()
            if "/tests/" in rel or rel.startswith("scripts/_legacy/"):
                continue
            out.append(p)
    return out


def _string_constants(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _head_candidates(node: ast.AST, const_map: dict[str, list[str]]) -> list[str]:
    """Every string argv[0] could evaluate to."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        return const_map.get(node.id, [])
    if isinstance(node, ast.Call):  # e.g. shutil.which("codex")
        return _string_constants(node)
    return []


def _analyze(path: Path) -> dict:
    """Return what this file does about spawning/bounding/killing an agentic CLI."""
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=str(path))

    # Resolve names back to the strings they might hold, so an argv assembled anywhere
    # but the call site still resolves. Three shapes, all of which occur in this repo:
    #   AGY = "/Users/.../agy"                                       -> Constant
    #   CLAUDE_BIN = os.environ.get("VOLPRED_CLAUDE_BIN", "claude")  -> Call, several
    #                                                                   candidate strings
    #   argv = [CLAUDE_BIN, "-p", ...]; Popen(argv)                  -> List of the above
    #
    # A name maps to a LIST of candidates, not one string: os.environ.get yields both
    # the env var's name and its default, and only the default is the binary. Collapse
    # them and "VOLPRED_CLAUDE_BIN" wins over "claude", which matches nothing.
    const_map: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not names:
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for n in names:
                const_map[n] = [node.value.value]
        elif isinstance(node.value, ast.Call):
            strs = _string_constants(node.value)
            if strs:
                for n in names:
                    const_map.setdefault(n, strs)

    # Second pass: argv lists. We only need the candidates for element 0 — the program.
    head_map: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not names or not node.value.elts:
            continue
        head_map_val = _head_candidates(node.value.elts[0], const_map)
        if head_map_val:
            for n in names:
                head_map.setdefault(n, head_map_val)

    spawns_agentic = False
    has_timeout = False
    new_session = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")

        if fname in TIMEOUT_CALLS and any(k.arg == "timeout" for k in node.keywords):
            has_timeout = True

        if fname in SPAWNERS and node.args:
            # Only argv[0] — the program actually being executed. Matching any element
            # makes `pgrep -f scripts/codex_loop.sh` look like a codex launch, which it
            # very much is not (scripts/email_fast_path.py, caught doing exactly that).
            argv = node.args[0]
            if isinstance(argv, (ast.List, ast.Tuple)) and argv.elts:
                heads = _head_candidates(argv.elts[0], const_map)
            elif isinstance(argv, ast.Name):
                heads = head_map.get(argv.id, const_map.get(argv.id, []))
            elif isinstance(argv, ast.Constant) and isinstance(argv.value, str):
                heads = [argv.value]
            else:
                heads = []

            for cand in heads:
                base = cand.rsplit("/", 1)[-1].lower()
                if any(base == m or base.startswith(m) for m in AGENTIC_MARKERS):
                    spawns_agentic = True
                    break

        if any(k.arg == "start_new_session" for k in node.keywords):
            new_session = True

    kills_group = ("killpg" in src) or ("kill_pgid" in src)
    return {
        "spawns_agentic": spawns_agentic,
        "has_timeout": has_timeout,
        "new_session": new_session,
        "kills_group": kills_group,
    }


def test_timed_out_agentic_cli_is_killed_as_a_group() -> None:
    violations: list[str] = []
    covered: list[str] = []
    still_broken: list[str] = []

    for path in _iter_py_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT:
            continue
        info = _analyze(path)
        if not (info["spawns_agentic"] and info["has_timeout"]):
            continue

        covered.append(rel)
        missing = []
        if not info["new_session"]:
            missing.append("start_new_session=True (no process group to kill)")
        if not info["kills_group"]:
            missing.append("killpg / procutil.kill_pgid (orphans survive the timeout)")
        if not missing:
            continue
        if rel in KNOWN_UNFIXED:
            still_broken.append(rel)
        else:
            violations.append(f"{rel}: {', '.join(missing)}")

    assert covered, (
        "gate found no agentic-CLI launcher at all — the detector is broken, not the repo. "
        "It should at minimum see scripts/run_agent_job.py."
    )
    assert not violations, (
        "A timed-out agentic CLI would leave orphaned children still writing:\n  "
        + "\n  ".join(violations)
        + "\n\nSpawn it with start_new_session=True and kill the group on timeout "
          "(scripts.dispatch_supervisor.procutil.kill_pgid). See this file's docstring."
    )

    # Ratchet: the debt ledger may only shrink. A file that got fixed must be removed
    # from KNOWN_UNFIXED, otherwise the ledger rots into a list of things that are
    # actually fine and nobody trusts it any more.
    fixed_but_still_listed = sorted(set(KNOWN_UNFIXED) - set(still_broken))
    assert not fixed_but_still_listed, (
        "These are listed in KNOWN_UNFIXED but now pass — delete their entries:\n  "
        + "\n  ".join(fixed_but_still_listed)
    )


@pytest.mark.parametrize("rel", ["scripts/run_agent_job.py", "scripts/scan_trending_agy.py"])
def test_known_launchers_are_actually_seen_by_the_detector(rel: str) -> None:
    """Pin the detector to the files it was built from.

    A static gate that silently stops matching is worse than no gate: it reports
    green forever. If a refactor moves how these files spawn their CLI, this fails
    and the detector gets updated with them.
    """
    info = _analyze(ROOT / rel)
    assert info["spawns_agentic"], f"{rel}: detector no longer recognises the agentic CLI launch"
    assert info["has_timeout"], f"{rel}: detector no longer sees a timeout bound"
