#!/usr/bin/env python3
"""Move local `main` onto a rewritten head that is already on the remote.

History surgery leaves the shared checkout pointing at the pre-rewrite chain.
Realigning it is a ref move, which `scripts/hooks/git_mutation_guard.py`
correctly refuses to let an agent do with a bare `git update-ref`: a raw ref
write on the shared checkout is exactly the class of operation that guard
exists to stop. The sanctioned answer -- the one the guard's own message points
at -- is a canonical helper that takes the writer lease and proves its
preconditions, which is this.

On 2026-08-04 the absence of that helper cost four hand-run rounds. Each time
`update-ref` was issued by hand it silently failed to stick, the supervisor came
back up, and PHASE-Z laid another commit on the stale chain, so the divergence
grew instead of closing.

The safety property is tree equality, not trust:

    replay every local-only commit onto the target, then refuse to move the ref
    unless the resulting tree is byte-identical to the tree `main` has now.

That makes losing work structurally impossible rather than merely unlikely. If
a replay conflicts or changes the tree, this aborts and leaves `main` alone.
The ref write itself is a compare-and-swap against the value observed at entry,
so a supervisor commit landing mid-run makes this fail rather than clobber.

    uv run python scripts/align_local_main.py --to <sha> --actor claude-main
    uv run python scripts/align_local_main.py --to <sha> --actor claude-main --apply
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))


def _git(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    leased: bool = False,
) -> str:
    """Run git; pass `leased=True` for anything that writes a ref.

    A reference-transaction hook rejects writes to refs/heads/main unless the
    caller holds the canonical writer lease, and the lease lives in an inherited
    env var plus a kernel lock FD. A plain subprocess does not carry either, so
    it is refused even when the Python parent is inside `git_writer_lock`.

    This is also why four hand-run `git update-ref` attempts failed on
    2026-08-04: a terminal holds no lease either, so the hook declined every
    one of them. The ref simply never moved.
    """
    kwargs: dict = {}
    if leased:
        from volpred.ops.git_writer_lock import git_writer_subprocess_kwargs

        kwargs = dict(git_writer_subprocess_kwargs())
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        **kwargs,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed rc={proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[:400]}"
        )
    return (proc.stdout or "").strip()


def _tree(rev: str) -> str:
    return _git("rev-parse", f"{rev}^{{tree}}")


def _remote_main() -> str | None:
    out = _git("ls-remote", "origin", "refs/heads/main", check=False)
    return out.split()[0] if out else None


def plan(target: str) -> dict:
    """Everything decided before a single byte is written."""
    if _git("cat-file", "-t", target, check=False) != "commit":
        raise RuntimeError(f"target {target} is not a commit in this object store")

    target_sha = _git("rev-parse", target)
    main_sha = _git("rev-parse", "refs/heads/main")
    remote_sha = _remote_main()

    already = target_sha == main_sha
    # Commits local main has that the target does not: these must survive.
    #
    # Neither reachability nor patch-id answers this after a history rewrite.
    # `rev-list target..main` reports the whole old chain, because every
    # replayed commit got a new sha. `git cherry` is no better: the rewrite
    # changed those commits' patches on purpose (it removed a file from them),
    # so patch-id marks them absent too. Both readings make the replay
    # re-apply work the target already has, which is how this helper's first
    # run died on an empty cherry-pick.
    #
    # Tree equality is the invariant that actually holds: the rewrite preserved
    # content and changed only history, so the local commit whose tree matches
    # the target's tree IS the rewrite base. Everything after it is the
    # genuinely new work, and everything before is already represented.
    target_tree = _tree(target_sha)
    rewrite_base = None
    for commit in _git("rev-list", main_sha).split():
        if commit and _tree(commit) == target_tree:
            rewrite_base = commit
            break
    if rewrite_base is None:
        raise RuntimeError(
            f"no commit on main has the target's tree ({target_tree[:12]}); "
            "this target is not a content-preserving rewrite of local history, "
            "so realigning could silently drop work"
        )
    local_only = [
        c for c in _git("rev-list", "--reverse", f"{rewrite_base}..{main_sha}").split() if c
    ]
    return {
        "target": target_sha,
        "main": main_sha,
        "remote_main": remote_sha,
        "target_is_remote_head": remote_sha == target_sha,
        "already_aligned": already,
        "local_only": local_only,
        "rewrite_base": rewrite_base,
        "local_only_subjects": [
            _git("log", "-1", "--format=%h %s", c) for c in local_only
        ],
        "main_tree": _tree(main_sha) if not already else None,
    }


def _replay(target_sha: str, local_only: list[str], expected_tree: str) -> str:
    """Cherry-pick local-only commits onto target in a throwaway worktree."""
    with tempfile.TemporaryDirectory(prefix="volpred-align-") as tmp:
        wt = Path(tmp) / "wt"
        branch = f"align-tmp-{target_sha[:8]}"
        _git("worktree", "add", "--detach", str(wt), target_sha)
        try:
            for commit in local_only:
                _git("cherry-pick", "--allow-empty", commit, cwd=wt)
            head = _git("rev-parse", "HEAD", cwd=wt)
            got = _tree(head)
            if got != expected_tree:
                raise RuntimeError(
                    "replayed tree does not match the current main tree "
                    f"({got} != {expected_tree}); refusing to move the ref"
                )
            return head
        finally:
            # Detached worktree: nothing to delete but the checkout itself.
            _git("worktree", "remove", "--force", str(wt), check=False)
            _git("worktree", "prune", check=False)
            del branch


def align(target: str, *, actor: str, apply: bool) -> dict:
    from volpred.ops.git_writer_lock import git_writer_lock

    decided = plan(target)
    if decided["already_aligned"]:
        return {**decided, "action": "noop_already_aligned", "applied": False}

    if not decided["local_only"]:
        new_head = decided["target"]
        action = "fast_forward_ref_only"
    else:
        new_head = _replay(
            decided["target"], decided["local_only"], decided["main_tree"]
        )
        action = f"replayed_{len(decided['local_only'])}_commit(s)"

    result = {**decided, "new_head": new_head, "action": action, "applied": False}
    if not apply:
        return result

    with git_writer_lock(REPO_ROOT, actor=actor):
        # CAS against the value observed at entry: if the supervisor committed
        # while we were replaying, fail rather than discard its commit.
        observed = _git("rev-parse", "refs/heads/main")
        if observed != decided["main"]:
            raise RuntimeError(
                f"main moved during replay ({decided['main'][:9]} -> {observed[:9]}); "
                "re-run so the new commit is replayed too"
            )
        _git("update-ref", "refs/heads/main", new_head, decided["main"], leased=True)
        readback = _git("rev-parse", "refs/heads/main")

    if readback != new_head:
        raise RuntimeError(f"ref read-back mismatch: {readback} != {new_head}")
    result["applied"] = True
    result["readback"] = readback
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", required=True, help="the head already on the remote")
    ap.add_argument("--actor", required=True)
    ap.add_argument("--apply", action="store_true", help="without this, plan only")
    args = ap.parse_args()

    try:
        out = align(args.to, actor=args.actor, apply=args.apply)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **out}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
