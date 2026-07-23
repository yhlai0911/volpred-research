#!/usr/bin/env python3
"""Put the PRE-CHANGE bytes of a verdict gate into git, before the gate is changed.

THE BUG CLASS
-------------
K1708 (2026-07) failed Codex primary-path review three rounds running. One of the
two root causes:

  The verdict gate was found to be producing a false positive and was fixed. The
  bytes of the *pre-fix* gate were never committed. When review asked the obvious
  question -- "prove the new gate does not turn an old NULL into a positive
  finding" -- there was no original to compare against. The author answered by
  RECONSTRUCTING the old gate as ``legacy_derive_verdict()`` and testing the new
  gate against that. Review, correctly, refused: proving a reconstruction correct
  with the reconstruction is circular.

The evidence needed to answer that question exists for exactly one moment: just
before someone edits the file. After the edit it is gone, and no amount of care
brings it back. So the preservation has to be mechanical, and it has to happen at
that moment. This script is that moment.

WHAT IT DOES
------------
Copies the CURRENT bytes of a gate-bearing file into

    experiments/<kid>/gate_history/<sha8>__<filename>
    experiments/<kid>/gate_history/manifest.json

A plain file in the working tree, not a stash and not a reconstruction: it gets
committed with the change, and ``git show`` on it returns the real original.

    uv run python scripts/preserve_gate_blob.py preserve \
        --path experiments/k1750/K1750.py \
        --reason "verdict gate comparator switched to cw_vs_own_restriction_primary"

    uv run python scripts/preserve_gate_blob.py status --path experiments/k1750

HOW IT IS ENFORCED
------------------
There is no central verdict-gate module to hook. A repo-wide grep for
``def *verdict*`` returns 40+ private functions, one per experiment script; the
gate is wherever that experiment put it. Enforcement therefore has two layers:

* ``scripts/hooks/gate_edit_guard.py`` intercepts Edit/Write operations when the
  current runtime-pinned bytes exist only in the working tree. It refuses to
  destroy that sole copy until this command preserves it.
* ``scripts/check_experiment_artifacts.py`` detects every runtime-pinned
  entrypoint drift before merge/CI. If the pre-image was already committed, the
  hook stays quiet because the exact bytes remain recoverable from git; the
  artifact gate still requires them under ``gate_history/`` before landing.

The drift trigger is observable after the fact:

  ``scripts/check_experiment_artifacts.py`` fails an experiment whose
  ``reproduce_spec.json`` declares ``entrypoint.sha256`` (i.e. the spec was
  emitted at run time by ``volpred.research.reproduce_spec``) when the entrypoint
  on disk no longer hashes to that value AND no ``gate_history/`` blob carries
  the declared sha. Changed the script after publishing results? Then the bytes
  that produced those results must still be in the tree.

KNOWN GAPS -- read before trusting this.
  1. Shell/editor operations outside Claude's Edit/Write hooks are detected only
     at merge/CI time. Post-hoc preservation of the wrong bytes still fails: the
     preserved sha must match the runtime spec. If the original was committed it
     is recoverable with ``git show``; if it was never committed and a non-hooked
     editor overwrites it, no software can reconstruct the destroyed evidence.
     This is why the edit hook and downstream artifact gate are both required.
  2. It only binds experiments whose spec was machine-generated. Every
     pre-2026-07 experiment is invisible to it, on purpose (see the forward
     ratchet in check_experiment_artifacts.py). It fixes the next K1708, not the
     1,256 historical directories.
  3. Nothing verifies the preserved file actually CONTAINS a verdict function.
     The unit of preservation is the entrypoint, not the gate function, because
     a gate's behaviour depends on the helpers around it. Coarse, but honest --
     and a coarse original beats a precise reconstruction.

NEXT STEP if shell/editor bypasses recur: add an installed pre-commit hook that
refuses a diff touching a ``def *verdict*`` body in an experiment with archived
results unless the pre-image sha appears under ``gate_history/``. The existing
artifact gate already blocks landing the drift; this would move that feedback
earlier for non-Claude editors.

STDLIB ONLY -- same constraint as check_experiment_artifacts.py: this may be
called from ``merge_worktree.sh``, which runs bare ``python3``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_HISTORY_DIRNAME = "gate_history"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = "volpred.gate_history.v1"


def blob_dir(exp_dir: Path) -> Path:
    return exp_dir / GATE_HISTORY_DIRNAME


def manifest_path(exp_dir: Path) -> Path:
    return blob_dir(exp_dir) / MANIFEST_NAME


def sha256_of(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def load_manifest(exp_dir: Path) -> dict[str, Any]:
    path = manifest_path(exp_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": MANIFEST_SCHEMA, "entries": []}
    except (OSError, ValueError) as exc:
        # Do NOT silently restart from empty: that would erase the record of every
        # blob already preserved and let the gate believe nothing was ever saved.
        raise SystemExit(f"[gate-blob] ERROR — {path} is unreadable: {exc}")
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        raise SystemExit(f"[gate-blob] ERROR — {path} is not a v1 manifest")
    return raw


def preserved_shas(exp_dir: Path) -> set[str]:
    """Shas whose blob is present AND hashes to what the manifest claims.

    Re-hashing is the point. A manifest entry is a claim; the blob is the
    evidence. An entry pointing at a missing or edited file is worth nothing, and
    counting it would let the gate pass on a promise instead of an original.
    """
    try:
        manifest = load_manifest(exp_dir)
    except SystemExit:
        return set()
    out: set[str] = set()
    for entry in manifest.get("entries", []):
        if not isinstance(entry, dict):
            continue
        digest = entry.get("sha256")
        blob = entry.get("blob")
        if not isinstance(digest, str) or not isinstance(blob, str):
            continue
        candidate = blob_dir(exp_dir) / Path(blob).name
        if not candidate.is_file():
            continue
        actual, _ = sha256_of(candidate)
        if actual == digest:
            out.add(digest)
    return out


def preserve(exp_dir: Path, source: Path, reason: str, *, now: str | None = None) -> dict[str, Any]:
    """Copy ``source``'s current bytes into ``gate_history/`` and record them."""
    digest, size = sha256_of(source)
    target_dir = blob_dir(exp_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    blob_name = f"{digest[:8]}__{source.name}"
    target = target_dir / blob_name
    if not target.exists():
        target.write_bytes(source.read_bytes())

    manifest = load_manifest(exp_dir)
    entries = [e for e in manifest["entries"] if not (
        isinstance(e, dict) and e.get("sha256") == digest
    )]
    entry = {
        "sha256": digest,
        "size_bytes": size,
        "source": source.name,
        "blob": blob_name,
        "reason": reason,
        "preserved_at": now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    entries.append(entry)
    manifest["schema_version"] = MANIFEST_SCHEMA
    manifest["entries"] = sorted(entries, key=lambda e: e["preserved_at"])
    manifest.setdefault("_readme", [
        "Pre-change bytes of gate-bearing experiment scripts, preserved BEFORE the edit.",
        "Written by scripts/preserve_gate_blob.py. Never edit a blob: it is evidence,",
        "and an edited original is a reconstruction, which is what K1708 was rejected for.",
    ])
    manifest_path(exp_dir).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return entry


def cmd_preserve(args: argparse.Namespace) -> int:
    source = Path(args.path)
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    if not source.is_file():
        print(f"[gate-blob] ERROR — no such file: {args.path}", file=sys.stderr)
        return 2
    reason = (args.reason or "").strip()
    if not reason:
        # An unlabelled blob is a file nobody can interpret in six months. The
        # reason is what makes the before/after comparison answerable.
        print("[gate-blob] ERROR — --reason is required: say what the gate change is.",
              file=sys.stderr)
        return 2
    exp_dir = Path(args.exp_dir).resolve() if args.exp_dir else source.parent
    entry = preserve(exp_dir, source, reason)
    print(f"[gate-blob] preserved {entry['source']} "
          f"({entry['sha256'][:12]}, {entry['size_bytes']} bytes) "
          f"-> {exp_dir.name}/{GATE_HISTORY_DIRNAME}/{entry['blob']}")
    print("[gate-blob] commit this file with the gate change; it is the only original "
          "a reviewer can diff against.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    exp_dir = Path(args.path)
    if not exp_dir.is_absolute():
        exp_dir = (Path.cwd() / exp_dir).resolve()
    if not exp_dir.is_dir():
        print(f"[gate-blob] ERROR — no such experiment directory: {args.path}", file=sys.stderr)
        return 2
    manifest = load_manifest(exp_dir)
    verified = preserved_shas(exp_dir)
    entries = manifest.get("entries", [])
    if not entries:
        print(f"[gate-blob] {exp_dir.name}: no preserved gate blobs")
        return 0
    for entry in entries:
        mark = "OK " if entry.get("sha256") in verified else "BAD"
        print(f"[gate-blob] {mark} {entry.get('sha256', '?')[:12]} "
              f"{entry.get('size_bytes')}B {entry.get('source')} — {entry.get('reason')}")
    return 0 if len(verified) == len(entries) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    pre = sub.add_parser("preserve", help="save a file's current bytes before editing it")
    pre.add_argument("--path", required=True, help="the gate-bearing file, e.g. experiments/k1750/K1750.py")
    pre.add_argument("--reason", help="what gate change is about to be made (required)")
    pre.add_argument("--exp-dir", help="experiment dir (defaults to the file's parent)")
    pre.set_defaults(func=cmd_preserve)

    st = sub.add_parser("status", help="list preserved blobs and verify their bytes")
    st.add_argument("--path", required=True, help="experiments/<kid>")
    st.set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
