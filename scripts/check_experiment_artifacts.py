#!/usr/bin/env python3
"""Mechanical gate: an experiment that lands finished results must land its artifacts too.

THE BUG CLASS
-------------
On 2026-07-19 CI went red three dispatch hours in a row (k1732 missing a knowledge
entry -> k1719 missing one -> a test writing canonical state). The first two were the
same bug: an experiment merged into main whose *artifacts* -- the ``knowledge.json``
entry and the ``reproduce_spec.json`` -- were never written. Each was patched one
experiment at a time, by a human noticing a red build. Nothing stopped the next one.

Clearing the stock is not the fix. This gate freezes the class: an experiment
directory carrying archived ``*_results.json`` must, at the moment it is merged,
already have

  1. an entry in ``storage/memory/knowledge.json`` mentioning its K-id, and
  2. a ``reproduce_spec.json`` that parses and points at files that exist, and
  3. -- if that spec was machine-generated at run time (it declares
     ``entrypoint.sha256``) -- an entrypoint that still hashes to the declared value,
     or the original bytes preserved under ``gate_history/``. See
     ``_entrypoint_drift_violation`` for the K1708 incident this closes, and
     ``src/volpred/research/reproduce_spec.py`` for the emitter that produces the sha.

SCOPE, AND WHY IT IS DRAWN HERE
-------------------------------
Only directories with archived ``*_results.json`` are gated. This is the same scope
``scripts/tests/test_knowledge_unrecorded_ratchet.py`` already uses, and it is the only
defensible one: a directory with no results has no finding to record and no canonical
output to pin, so demanding artifacts of it would force someone to invent them. The
2026-07-19 repo-wide sweep found 108 result-less directories (paper-writing sessions,
``.gitkeep`` placeholders, abandoned stubs) -- fabricating 108 knowledge entries to make
a number go green would be exactly the failure this gate exists to prevent.

The knowledge half is further scoped to directories carrying a K-id, because
``knowledge.json`` is keyed by K-id: for ``paper2_taiwan_indiv_rolling_gamma`` the gate
has no key to look up, so demanding an entry would be an instruction nobody can carry
out — and unsatisfiable gates get bypassed, not obeyed. Those directories still owe a
``reproduce_spec.json``; their finding's home is the paper, not the K-record.

The gate fires on experiments being ADDED OR MODIFIED, not on the 1,265-experiment
backlog. ``reproduce_spec.json`` only became a convention in 2026-07 (k1683, k1699,
K1710, and k1719 backfilled here); retroactively synthesising ~1,260 specs would mean
inventing entrypoints, input hashes and seeds for runs nobody can re-execute. Forward
ratchet, documented exclusions, no invented history.

CALLED FROM TWO PLACES, ON PURPOSE
----------------------------------
* ``scripts/merge_worktree.sh``   -- pre-merge gate (blocks the merge)
* ``.github/workflows/experiment-artifacts.yml`` -- CI gate (blocks the push/PR)

Both invoke THIS script. Do not reimplement the check in either caller: two copies of a
rule drift, and the drift is always discovered by the incident the rule was meant to stop.

STDLIB ONLY
-----------
``merge_worktree.sh`` runs gates with bare ``python3``, never ``uv run`` -- a gate that
cannot start is a gate that abstains (see the comment at its certify call site). So the
module-level imports here are stdlib only. Strict spec validation lives in
``scripts/reproduce_check.py``; this script uses it when the richer environment makes it
importable and falls back to a structural check when it does not. The fallback is
weaker, never absent, and the mode is printed so nobody has to guess which ran.

Run:
    python3 scripts/check_experiment_artifacts.py check --path experiments/k1719
    python3 scripts/check_experiment_artifacts.py check --changed-since main
    uv run python scripts/check_experiment_artifacts.py sweep --out storage/ops/sweep.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_REL = Path("storage/memory/knowledge.json")
SPEC_NAME = "reproduce_spec.json"
SPEC_SCHEMA = "volpred.reproduce_spec.v1"
COMMIT_NAME = "reproduce_commit.json"
COMMIT_SCHEMA = "volpred.reproduce_commit.v1"
EXCLUSIONS_REL = Path("config/experiment_artifact_exclusions.json")

# Same shape reproduce_check.knowledge_recorded_ids scans for. Two entry shapes coexist
# in knowledge.json (modern item_id/content, legacy title/experiment_id) and neither has
# a dedicated K-id field, so the whole entry is serialised and scanned. A field whitelist
# was tried once and silently skipped every legacy entry.
K_IN_BLOB_RE = re.compile(r"[Kk]\d{3,}")
K_DIR_RE = re.compile(r"^([Kk]\d+)")


def k_id(dir_name: str) -> str | None:
    """Leading K-number of an experiment dir (``k1538_bond_fund...`` -> ``k1538``)."""
    match = K_DIR_RE.match(dir_name)
    return match.group(1).casefold() if match else None


def _canonical_root() -> Path:
    """The main checkout, not a worktree's copy.

    knowledge.json is canonical shared state that agents must not write (K1259), so at
    merge time the authoritative copy is the one in the main checkout -- a worktree
    branch's stale copy would let an experiment pass against a knowledge base that no
    longer exists. Mirrors ``experiment_gates._canonical_registry_path``.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True, text=True, timeout=10, check=True,
        )
        common = Path(proc.stdout.strip())
        if not common.is_absolute():
            common = (Path(__file__).resolve().parent / common).resolve()
        return common.parent
    except (OSError, subprocess.SubprocessError):
        return REPO_ROOT


def knowledge_ids_from_entries(entries: object) -> set[str] | None:
    """Extract the K-id coverage from an already selected knowledge snapshot."""
    if not isinstance(entries, list):
        return None
    recorded: set[str] = set()
    for entry in entries:
        blob = json.dumps(entry, ensure_ascii=False) if isinstance(entry, dict) else str(entry)
        recorded.update(m.casefold() for m in K_IN_BLOB_RE.findall(blob))
    return recorded


def load_knowledge_ids(root: Path | None = None) -> set[str] | None:
    """K-ids mentioned anywhere in the knowledge base. ``None`` = unreadable."""
    path = (root or _canonical_root()) / KNOWLEDGE_REL
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[artifacts] WARN — knowledge base unreadable at {path}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    recorded = knowledge_ids_from_entries(entries)
    if recorded is None:
        print(f"[artifacts] WARN — knowledge base at {path} is "
              f"{type(entries).__name__}, expected a list.", file=sys.stderr)
    return recorded


def load_knowledge_ids_at_ref(ref: str, root: Path | None = None) -> set[str] | None:
    """K-ids in the knowledge base as COMMITTED at ``ref``. ``None`` = unreadable.

    The merge-side gate and the CI gate are the same script, but until 2026-08-04
    they evaluated different states: merge read the working tree, CI read the
    pushed commit. The k1735 merge passed against an uncommitted working-tree
    entry, then CI went red on the push that carried no entry (run 30879353621).
    Reading the committed blob closes that split-brain — dirty working-tree
    state can no longer satisfy the merge gate.
    """
    base = root or _canonical_root()
    try:
        proc = subprocess.run(
            ["git", "show", f"{ref}:{KNOWLEDGE_REL.as_posix()}"],
            cwd=str(base), capture_output=True, text=True, timeout=30, check=True,
        )
        entries = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[artifacts] WARN — knowledge base unreadable at {ref}:{KNOWLEDGE_REL} "
              f"(root {base}): {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    recorded = knowledge_ids_from_entries(entries)
    if recorded is None:
        print(f"[artifacts] WARN — knowledge base at {ref}:{KNOWLEDGE_REL} is "
              f"{type(entries).__name__}, expected a list.", file=sys.stderr)
    return recorded


def load_exclusions(root: Path | None = None) -> dict[str, str]:
    """``{k_id: reason}`` for experiments legitimately exempt from this gate."""
    path = (root or REPO_ROOT) / EXCLUSIONS_REL
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}  # silent-ok: no exclusions file means no exclusions, the normal case
    except (OSError, ValueError) as exc:
        # An empty dict here is indistinguishable from "nothing is excluded", so a
        # corrupt file would silently re-gate every documented exemption.
        print(f"[artifacts] WARN — exclusions unreadable at {path}, proceeding with "
              f"NO exclusions: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {}
    parsed = exclusions_from_payload(raw)
    if parsed is None:
        print(f"[artifacts] WARN — exclusions at {path} have invalid schema; "
              "proceeding with NO exclusions.", file=sys.stderr)
        return {}
    return parsed


def exclusions_from_payload(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for item in raw.get("exclusions", []):
        if isinstance(item, dict) and isinstance(item.get("experiment"), str):
            out[item["experiment"].casefold()] = str(item.get("reason", "")).strip()
    return out


def result_files(exp_dir: Path) -> list[Path]:
    return sorted(exp_dir.glob("*_results.json"))


def _spec_violation(exp_dir: Path) -> tuple[str | None, str]:
    """``(violation_or_None, mode)`` for the reproduce_spec check."""
    path = exp_dir / SPEC_NAME
    if not path.is_file():
        return f"missing {SPEC_NAME}", "existence"

    # Strict path: reuse reproduce_check.load_spec so the gate and the reproducibility
    # audit can never disagree about what a valid spec is.
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import reproduce_check  # type: ignore
    except Exception:  # noqa: BLE001 - stdlib-only merge context; fall back, never abstain
        reproduce_check = None  # type: ignore

    if reproduce_check is not None:
        spec, err = reproduce_check.load_spec(exp_dir)
        if not spec:
            return f"{SPEC_NAME} is invalid: {err}", "strict"
        return None, "strict"

    # Fallback: structural check only. Weaker than load_spec (no seed/tolerance/input
    # -hash validation), but it still catches the empty, truncated and mislabelled files
    # that are the common real failure.
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"{SPEC_NAME} does not parse: {exc}", "structural"
    if not isinstance(raw, dict) or raw.get("schema_version") != SPEC_SCHEMA:
        return f"{SPEC_NAME} schema_version must equal {SPEC_SCHEMA!r}", "structural"
    entry = raw.get("entrypoint")
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        return f"{SPEC_NAME} needs an entrypoint.path", "structural"
    if not (exp_dir / entry["path"]).is_file():
        return f"{SPEC_NAME} entrypoint.path does not exist: {entry['path']}", "structural"
    canonical = raw.get("canonical_result")
    if not isinstance(canonical, str) or not (exp_dir / canonical).is_file():
        return f"{SPEC_NAME} canonical_result does not exist: {canonical!r}", "structural"
    return None, "structural"


def _entrypoint_drift_violation(exp_dir: Path) -> tuple[str | None, str]:
    """``(violation_or_None, status)`` for the entrypoint-drift / gate-history check.

    THE BUG CLASS (K1708, 2026-07)
    ------------------------------
    ``K1708_results.json`` records ``code_trace`` sha ``43bffdd...`` at 91,752 bytes.
    ``experiments/k1708/K1708.py`` on disk is 126,998 bytes. The spec describes a
    program that did not produce the results it pins, and nobody noticed for weeks
    because nothing compared the two. Separately, the pre-fix verdict gate was never
    committed, so "does the new gate turn an old NULL into a positive finding?" could
    only be answered against a RECONSTRUCTION -- circular, and review rejected it.

    Both collapse into one observable: the entrypoint no longer hashes to what the
    spec says produced the archived results. When that is true, the bytes that DID
    produce them must still exist in the tree, under ``gate_history/``. Then a
    reviewer can diff the original against the current gate instead of arguing about
    a rebuild.

    FORWARD RATCHET -- why the 1,256-experiment backlog stays green
    --------------------------------------------------------------
    The rule fires ONLY when ``entrypoint.sha256`` is present. That field is written
    by ``volpred.research.reproduce_spec``, at run time, by the process that wrote the
    results -- so its presence certifies "this spec was machine-generated and its sha
    is trustworthy". Hand-written pre-convention specs have no such field and are
    returned as ``skipped-no-sha``: silence, not a pass claim. Synthesising shas for
    runs nobody can re-execute is the invented history this gate exists to prevent
    (see the module docstring), and 2026-07-19 already showed what a batch of
    retroactive red does to a dispatch day.
    """
    path = exp_dir / SPEC_NAME
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "skipped-unreadable"  # _spec_violation already reported this
    if not isinstance(spec, dict):
        return None, "skipped-unreadable"

    entry = spec.get("entrypoint")
    if not isinstance(entry, dict):
        return None, "skipped-unreadable"
    declared = entry.get("sha256")
    if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{64}", declared):
        return None, "skipped-no-sha"

    rel = entry.get("path")
    if not isinstance(rel, str):
        return None, "skipped-unreadable"
    target = exp_dir / rel
    try:
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError:
        return None, "skipped-unreadable"  # _spec_violation reports a missing entrypoint

    if actual == declared:
        return None, "clean"

    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import preserve_gate_blob  # type: ignore
        preserved = preserve_gate_blob.preserved_shas(exp_dir)
    except Exception:  # noqa: BLE001 - stdlib-only merge context; verify inline instead
        preserved = _preserved_shas_fallback(exp_dir)

    if declared in preserved:
        return None, "drifted-preserved"
    return (
        f"{rel} no longer matches the sha its {SPEC_NAME} pins "
        f"(spec {declared[:12]}, on disk {actual[:12]}) and the original bytes are "
        f"not preserved under gate_history/ — a reviewer cannot diff the gate that "
        f"produced the archived results against the one on disk",
        "drifted-unpreserved",
    )


def _canonical_result_identity_violation(
    exp_dir: Path,
) -> tuple[str | None, str]:
    """Verify the independent runtime commitment to the complete result bytes.

    This is a forward ratchet.  Specs created before
    ``canonical_result_identity`` existed remain valid, while every result
    finalized by the current runtime emitter is value-bound.  The distinction
    from ``entrypoint.sha256`` is deliberate: code identity cannot detect a
    hand-edited CW statistic, QLIKE value, or verdict.
    """
    path = exp_dir / SPEC_NAME
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "skipped-unreadable"
    if not isinstance(spec, dict):
        return None, "skipped-unreadable"

    identity = spec.get("canonical_result_identity")
    if identity is None:
        return None, "skipped-no-result-identity"
    if not isinstance(identity, dict):
        return "canonical result identity must be an object", "invalid"

    canonical = spec.get("canonical_result")
    rel = identity.get("path")
    digest = identity.get("sha256")
    size = identity.get("size_bytes")
    if (
        not isinstance(canonical, str)
        or rel != canonical
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
    ):
        return (
            "canonical result identity is malformed or does not bind canonical_result",
            "invalid",
        )

    try:
        data = (exp_dir / canonical).read_bytes()
    except OSError as exc:
        return f"canonical result identity target is unreadable: {exc}", "unreadable"
    actual_digest = hashlib.sha256(data).hexdigest()
    if actual_digest != digest or len(data) != size:
        return (
            (
                "canonical result identity mismatch: the archived result bytes changed "
                f"after runtime finalization (spec {digest[:12]}/{size}, "
                f"disk {actual_digest[:12]}/{len(data)})"
            ),
            "mismatch",
        )
    return None, "clean"


def _artifact_generation_violation(exp_dir: Path) -> tuple[str | None, str]:
    """Verify a runtime generation's last-written completion receipt and outputs.

    This is a forward ratchet: old specs without ``artifact_generation`` remain
    valid. New finalizer runs carry the block and therefore cannot pass while a
    killed writer has exposed a mixed result/spec/figure generation.
    """
    try:
        spec_bytes = (exp_dir / SPEC_NAME).read_bytes()
        spec = json.loads(spec_bytes)
    except (OSError, ValueError):
        return None, "skipped-unreadable"
    generation = spec.get("artifact_generation") if isinstance(spec, dict) else None
    if generation is None:
        return None, "skipped-legacy"
    if not isinstance(generation, dict):
        return "artifact_generation must be an object", "invalid"
    generation_id = generation.get("generation_id")
    commit_name = generation.get("commit_file")
    identities = generation.get("output_identities")
    if (
        generation.get("schema_version") != COMMIT_SCHEMA
        or not isinstance(generation_id, str)
        or not re.fullmatch(r"[0-9a-f]{64}", generation_id)
        or commit_name != COMMIT_NAME
        or not isinstance(identities, list)
    ):
        return "artifact_generation metadata is malformed", "invalid"

    for item in identities:
        if not isinstance(item, dict):
            return "declared output identity is malformed", "invalid"
        rel, digest, size = item.get("path"), item.get("sha256"), item.get("size_bytes")
        if (
            not isinstance(rel, str)
            or Path(rel).is_absolute()
            or ".." in Path(rel).parts
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(size, int)
            or isinstance(size, bool)
        ):
            return "declared output identity is malformed", "invalid"
        try:
            data = (exp_dir / rel).read_bytes()
        except OSError as exc:
            return f"declared output identity target is unreadable: {rel}: {exc}", "output-unreadable"
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest or len(data) != size:
            return (
                (
                    f"declared output identity mismatch for {rel}: "
                    f"receipt {digest[:12]}/{size}, disk {actual[:12]}/{len(data)}"
                ),
                "output-mismatch",
            )

    try:
        commit = json.loads((exp_dir / COMMIT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"artifact completion receipt is missing or unreadable: {exc}", "commit-missing"
    if (
        not isinstance(commit, dict)
        or commit.get("schema_version") != COMMIT_SCHEMA
        or commit.get("generation_id") != generation_id
        or commit.get("output_identities") != identities
    ):
        return "artifact completion receipt does not match the spec generation", "commit-mismatch"
    if commit.get("canonical_result_identity") != spec.get("canonical_result_identity"):
        return "artifact completion receipt does not match the canonical result", "result-mismatch"
    result_identity = commit.get("canonical_result_identity")
    canonical = spec.get("canonical_result")
    if not isinstance(result_identity, dict) or not isinstance(canonical, str):
        return "artifact completion receipt lacks canonical result identity", "result-mismatch"
    try:
        result_bytes = (exp_dir / canonical).read_bytes()
    except OSError as exc:
        return f"artifact completion result is unreadable: {exc}", "result-mismatch"
    if (
        result_identity.get("path") != canonical
        or result_identity.get("sha256") != hashlib.sha256(result_bytes).hexdigest()
        or result_identity.get("size_bytes") != len(result_bytes)
    ):
        return "artifact completion receipt does not match canonical result bytes", "result-mismatch"
    spec_identity = commit.get("spec_identity")
    if not isinstance(spec_identity, dict):
        return "artifact completion receipt lacks spec identity", "commit-mismatch"
    if (
        spec_identity.get("path") != SPEC_NAME
        or spec_identity.get("sha256") != hashlib.sha256(spec_bytes).hexdigest()
        or spec_identity.get("size_bytes") != len(spec_bytes)
    ):
        return "artifact completion receipt does not match reproduce_spec.json", "commit-mismatch"
    return None, "clean"


def _preserved_shas_fallback(exp_dir: Path) -> set[str]:
    """``preserve_gate_blob.preserved_shas`` inlined for the bare-python3 merge path.

    Kept byte-verifying, not manifest-trusting: an entry whose blob is missing or
    edited is a claim, not evidence, and passing on a claim is the failure mode.
    """
    manifest = exp_dir / "gate_history" / "manifest.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    out: set[str] = set()
    for item in raw.get("entries", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        digest, blob = item.get("sha256"), item.get("blob")
        if not isinstance(digest, str) or not isinstance(blob, str):
            continue
        candidate = exp_dir / "gate_history" / Path(blob).name
        try:
            if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
                out.add(digest)
        except OSError:  # silent-ok: missing/unreadable evidence is rejected below
            # A missing or unreadable blob is precisely the "claim, not evidence"
            # case this helper exists to reject (see docstring). Dropping the digest is the
            # verdict, not a swallowed error — and this path runs under bare python3 during
            # merge, where volpred.ops.diagnostics is deliberately not importable.
            continue
    return out


def audit_experiment(
    exp_dir: Path,
    knowledge_ids: set[str] | None,
    exclusions: dict[str, str],
) -> dict[str, Any]:
    """Audit one experiment directory. ``violations == []`` means it may be merged."""
    name = exp_dir.name
    kid = k_id(name)
    record: dict[str, Any] = {
        "experiment_id": name,
        "path": f"experiments/{name}",
        "k_id": kid,
        "results_count": len(result_files(exp_dir)),
        "has_knowledge_entry": None,
        "has_reproduce_spec": (exp_dir / SPEC_NAME).is_file(),
        "gated": False,
        "excluded": False,
        "exclusion_reason": None,
        "violations": [],
        "spec_check_mode": None,
        "entrypoint_drift": None,
        "canonical_result_identity": None,
        "artifact_generation": None,
    }

    if kid and kid in exclusions:
        record["excluded"] = True
        record["exclusion_reason"] = exclusions[kid]
        return record
    if name.casefold() in exclusions:
        record["excluded"] = True
        record["exclusion_reason"] = exclusions[name.casefold()]
        return record

    # Scope: no archived results -> nothing to record, nothing to pin. See module docstring.
    if record["results_count"] == 0:
        return record
    record["gated"] = True

    if kid is None:
        # knowledge.json is keyed by K-id and this directory has none (paper-support
        # runs such as ``paper2_taiwan_indiv_rolling_gamma``). Demanding "an entry
        # mentioning paper2_..." would be unsatisfiable — the lookup the gate performs
        # could never match it — and an unsatisfiable gate gets bypassed, not obeyed.
        # The reproduce_spec requirement below still applies: the run has real output
        # to pin. ``sweep`` draws the same K-id scope, so the two agree.
        record["has_knowledge_entry"] = None
    elif knowledge_ids is None:
        # Unreadable knowledge base is itself a blocking condition: a gate that cannot
        # read its evidence must not wave the merge through.
        record["violations"].append(
            f"{KNOWLEDGE_REL} is unreadable — cannot verify the knowledge entry"
        )
    else:
        recorded = kid in knowledge_ids
        record["has_knowledge_entry"] = recorded
        if not recorded:
            record["violations"].append(
                f"no entry in {KNOWLEDGE_REL} mentions {kid or name} — the finding is "
                "invisible to topic dedup and article selection"
            )

    spec_violation, mode = _spec_violation(exp_dir)
    record["spec_check_mode"] = mode
    if spec_violation:
        record["violations"].append(spec_violation)
    else:
        # Only meaningful once the spec itself is valid: drift is a statement about
        # what the spec says, so a spec that does not parse has nothing to say.
        drift_violation, drift_status = _entrypoint_drift_violation(exp_dir)
        record["entrypoint_drift"] = drift_status
        if drift_violation:
            record["violations"].append(drift_violation)
        result_violation, result_status = _canonical_result_identity_violation(exp_dir)
        record["canonical_result_identity"] = result_status
        if result_violation:
            record["violations"].append(result_violation)
        generation_violation, generation_status = _artifact_generation_violation(exp_dir)
        record["artifact_generation"] = generation_status
        if generation_violation:
            record["violations"].append(generation_violation)

    return record


def _remedy(record: dict[str, Any]) -> list[str]:
    """Copy-pasteable remediation. A gate that only says 'no' costs the next shift an hour."""
    name = record["experiment_id"]
    lines: list[str] = []
    joined = " ".join(record["violations"])
    if "knowledge.json" in joined:
        lines += [
            f"  # 1. Write the knowledge entry for {name} — MAIN THREAD ONLY (K1259: agents",
            "  #    must not write knowledge.json). Take every number PROGRAMMATICALLY from",
            f"  #    experiments/{name}/*_results.json — never retype from a README or an",
            "  #    agent's summary (that is how fabricated findings enter the record).",
            f"  uv run python -c \"import json,pathlib; "
            f"print(json.dumps(json.loads(pathlib.Path('experiments/{name}')"
            f".glob('*_results.json').__next__().read_text()), indent=2, ensure_ascii=False))\"",
            "  #    then append the entry via the memory writer (m.add_knowledge / "
            "src/volpred/memory/system.py), which stamps provenance.",
        ]
    if SPEC_NAME in joined:
        lines += [
            f"  # 2. Write experiments/{name}/{SPEC_NAME} (schema {SPEC_SCHEMA}).",
            f"  #    Copy the shape from experiments/k1719/{SPEC_NAME}; hash every input",
            "  #    with sha256 and declare the seeds the script actually sets.",
            f"  uv run python scripts/reproduce_check.py inventory  # confirms {name} -> runnable",
        ]
    if "gate_history/" in joined:
        lines += [
            f"  # 2b. experiments/{name}'s entrypoint drifted from the sha its spec pins.",
            "  #     Recover the bytes that produced the archived results and preserve them:",
            f"  git log --oneline -- experiments/{name}/    # find the commit at that sha",
            f"  git show <sha>:experiments/{name}/<entrypoint> > /tmp/prefix_gate.py",
            "  uv run python scripts/preserve_gate_blob.py preserve \\",
            f"      --path /tmp/prefix_gate.py --exp-dir experiments/{name} \\",
            '      --reason "pre-fix verdict gate, recovered from git"',
            "  #     If instead the script legitimately changed AND was re-run, regenerate",
            "  #     results + spec together via volpred.research.reproduce_spec.finalize_experiment",
            "  #     so the pinned sha describes the run that actually produced them.",
        ]
    if "canonical result identity" in joined:
        lines += [
            f"  # 2c. experiments/{name}'s archived result bytes changed after the run.",
            "  #     Do not refresh the checksum around edited numbers. Restore the runtime",
            "  #     output, or rerun the experiment and let finalize_experiment regenerate",
            "  #     both the results and reproduce_spec.json from that execution.",
        ]
    lines += [
        "  # 3. If this experiment is genuinely exempt (archived legacy work, no",
        "  #    reproducible output), add it WITH A REASON to:",
        f"  #    {EXCLUSIONS_REL}",
    ]
    return lines


def caller_root() -> Path:
    """The checkout the *caller* is standing in, which is not always ours.

    REPO_ROOT is derived from this file's location, so it always points at the
    canonical checkout. When a worktree agent runs us from
    `.claude/worktrees/<name>`, resolving its relative paths against REPO_ROOT
    looks for `experiments/kXXXX` in a checkout where that directory does not
    exist yet — targets comes back empty and we print PASS. That is the exact
    failure this file's docstring warns about: a gate that cannot start is a
    gate that abstains. So resolve against the caller's checkout instead.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        top = Path(proc.stdout.strip())
        if top.is_dir():
            return top
    except (OSError, subprocess.SubprocessError):
        pass  # silent-ok: not in a git checkout; REPO_ROOT is the honest fallback
    return REPO_ROOT


def cmd_check(args: argparse.Namespace) -> int:
    root = caller_root()
    targets: list[Path] = []
    missing: list[str] = []
    if args.path:
        for raw in args.path:
            p = Path(raw)
            if p.is_absolute():
                targets.append(p)
                if not p.is_dir():
                    missing.append(raw)
                continue
            # Caller's checkout first, ours second — a relative path means
            # "relative to where I am standing", not "relative to the script".
            for candidate in (root / p, REPO_ROOT / p):
                if candidate.is_dir():
                    targets.append(candidate)
                    break
            else:
                missing.append(raw)
    if missing:
        # An explicit --path that resolves to nothing is the caller asking us to
        # check something specific. Answering PASS would be answering a question
        # we never looked at. Fail loudly instead, and say where we looked.
        print("[artifacts] ERROR — --path given but no such experiment directory:", file=sys.stderr)
        for raw in missing:
            print(f"    {raw}", file=sys.stderr)
        print(f"[artifacts] looked in: {root}", file=sys.stderr)
        if root != REPO_ROOT:
            print(f"[artifacts]        and: {REPO_ROOT}", file=sys.stderr)
        print("[artifacts] WHY exit 2 and not PASS: a gate that cannot find its target has not", file=sys.stderr)
        print("  checked anything. Passing here is how a worktree experiment reaches main unaudited.", file=sys.stderr)
        return 2
    if args.changed_since:
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only", f"{args.changed_since}...HEAD", "--", "experiments/"],
                cwd=str(root), capture_output=True, text=True, timeout=60, check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[artifacts] error: git diff failed: {exc}", file=sys.stderr)
            return 2
        names = sorted({
            line.split("/")[1] for line in proc.stdout.splitlines()
            if line.startswith("experiments/") and len(line.split("/")) >= 2
        })
        targets += [root / "experiments" / n for n in names]

    targets = [t for t in dict.fromkeys(targets) if t.is_dir()]
    if not targets:
        print("[artifacts] PASS — no experiment directory added or modified.")
        return 0

    if args.knowledge_ref:
        knowledge_ids = load_knowledge_ids_at_ref(args.knowledge_ref)
    else:
        knowledge_ids = load_knowledge_ids()
    exclusions = load_exclusions()
    records = [audit_experiment(t, knowledge_ids, exclusions) for t in targets]
    failed = [r for r in records if r["violations"]]

    if args.knowledge_ref and failed:
        # The most common way to fail ref-mode is an entry that exists but was
        # never committed — say so explicitly instead of sending the author off
        # to write a second entry.
        worktree_ids = load_knowledge_ids()
        for r in failed:
            kid = k_id(Path(r["path"]).name)
            if (kid and worktree_ids and kid in worktree_ids
                    and any("no entry in" in v for v in r["violations"])):
                print(f"[artifacts] NOTE — {kid}: a knowledge entry EXISTS in the working "
                      f"tree but not at {args.knowledge_ref}. Commit "
                      f"{KNOWLEDGE_REL} (via scripts/git_writer_lock.py) and rerun — "
                      "CI validates committed state, so an uncommitted entry goes red on push.")

    for r in records:
        if r["excluded"]:
            print(f"[artifacts] SKIP — {r['path']} (excluded: {r['exclusion_reason']})")
        elif not r["gated"]:
            print(f"[artifacts] SKIP — {r['path']} (no archived *_results.json to record)")
        elif not r["violations"]:
            # Say which halves actually ran. A dir with no K-id was never checked
            # against knowledge.json, and a PASS that implies otherwise is the kind
            # of quiet overclaim that makes people trust a gate past its scope.
            knowledge = "knowledge entry" if r["k_id"] else "no K-id (knowledge check n/a)"
            print(f"[artifacts] PASS — {r['path']} ({knowledge} + {SPEC_NAME}, "
                  f"spec check: {r['spec_check_mode']}, result identity: "
                  f"{r['canonical_result_identity']})")

    if not failed:
        return 0

    print("", file=sys.stderr)
    print("[artifacts] BLOCKED — experiment(s) merged without their artifacts:", file=sys.stderr)
    for r in failed:
        print(f"\n  {r['path']}", file=sys.stderr)
        for v in r["violations"]:
            print(f"    - {v}", file=sys.stderr)
    print("\n[artifacts] WHY: 2026-07-19 turned CI red three dispatch hours in a row "
          "(k1732, k1719) because\n"
          "  experiments reached main while their knowledge entry / reproduce_spec did not. "
          "Writing the\n  artifact now, while the author is still here, is cheaper than the "
          "archaeology later.\n", file=sys.stderr)
    print("[artifacts] FIX — run these:", file=sys.stderr)
    for r in failed:
        print(f"\n  ## {r['experiment_id']}", file=sys.stderr)
        for line in _remedy(r):
            print(line, file=sys.stderr)
    return 1


def cmd_sweep(args: argparse.Namespace) -> int:
    exp_root = REPO_ROOT / "experiments"
    dirs = sorted(
        p for p in exp_root.iterdir()
        if p.is_dir() and K_DIR_RE.match(p.name)
    )
    knowledge_ids = load_knowledge_ids()
    exclusions = load_exclusions()
    records = [audit_experiment(p, knowledge_ids, exclusions) for p in dirs]

    gated = [r for r in records if r["gated"]]
    missing = [r for r in gated if r["violations"]]
    report = {
        "schema_version": "volpred.experiment_artifact_sweep.v1",
        "generated_at": args.generated_at,
        "scope": {
            "experiment_root": "experiments/",
            "gated_rule": "directories with at least one archived *_results.json",
            "rationale": (
                "A directory with no archived results has no finding to record and no "
                "canonical output to pin. Demanding artifacts of it would force someone "
                "to invent them, which is the failure this gate exists to prevent."
            ),
        },
        "counts": {
            "experiment_dirs": len(records),
            "gated": len(gated),
            "not_gated_no_results": sum(
                1 for r in records if not r["gated"] and not r["excluded"]
            ),
            "excluded": sum(1 for r in records if r["excluded"]),
            "missing_knowledge_only": sum(
                1 for r in missing
                if any("knowledge.json" in v for v in r["violations"])
                and not any(SPEC_NAME in v for v in r["violations"])
            ),
            "missing_spec_only": sum(
                1 for r in missing
                if any(SPEC_NAME in v for v in r["violations"])
                and not any("knowledge.json" in v for v in r["violations"])
            ),
            "missing_both": sum(
                1 for r in missing
                if any("knowledge.json" in v for v in r["violations"])
                and any(SPEC_NAME in v for v in r["violations"])
            ),
            # Drift is reported separately from the artifact counts so the forward
            # ratchet stays legible: specs_with_runtime_sha is how many experiments
            # the drift rule can even see, and it should only ever grow.
            "specs_with_runtime_sha": sum(
                1 for r in records
                if r["entrypoint_drift"] in {"clean", "drifted-preserved", "drifted-unpreserved"}
            ),
            "entrypoint_drift_unpreserved": sum(
                1 for r in records if r["entrypoint_drift"] == "drifted-unpreserved"
            ),
            "entrypoint_drift_preserved": sum(
                1 for r in records if r["entrypoint_drift"] == "drifted-preserved"
            ),
        },
        "knowledge_base_readable": knowledge_ids is not None,
        "missing": missing,
        "not_gated_no_results": [
            {
                "experiment_id": r["experiment_id"],
                "path": r["path"],
                "reason": "no archived *_results.json — nothing to record or pin",
            }
            for r in records if not r["gated"] and not r["excluded"]
        ],
        "excluded": [
            {
                "experiment_id": r["experiment_id"],
                "path": r["path"],
                "reason": r["exclusion_reason"],
            }
            for r in records if r["excluded"]
        ],
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    c = report["counts"]
    print(f"[sweep] {c['experiment_dirs']} experiment dirs; {c['gated']} gated; "
          f"{len(missing)} with missing artifacts "
          f"(knowledge-only {c['missing_knowledge_only']}, spec-only {c['missing_spec_only']}, "
          f"both {c['missing_both']}); {c['not_gated_no_results']} not gated (no results); "
          f"{c['excluded']} excluded")
    print(f"[sweep] runtime-generated specs (drift rule in scope): {c['specs_with_runtime_sha']}; "
          f"drifted-preserved {c['entrypoint_drift_preserved']}; "
          f"drifted-UNPRESERVED {c['entrypoint_drift_unpreserved']}")
    print(f"[sweep] wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The one place the CLI surface is defined.

    Exposed so tests can build args through it instead of hand-rolling an
    argparse.Namespace. A hand-rolled namespace is a copy of this signature,
    and copies drift: --knowledge-ref was added here on 2026-08-04 and two
    tests carrying their own Namespace went red with AttributeError, having
    asserted on an args object no caller ever produces.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    chk = sub.add_parser("check", help="Gate one or more experiment directories.")
    chk.add_argument("--path", action="append", help="experiments/<kid> (repeatable)")
    chk.add_argument("--changed-since", help="gate every experiment touched since this ref")
    chk.add_argument(
        "--knowledge-ref",
        help="verify the knowledge entry against this git ref's committed "
             "storage/memory/knowledge.json instead of the working tree (the "
             "merge gate passes HEAD so it evaluates the same state CI will see)",
    )
    chk.set_defaults(func=cmd_check)

    swp = sub.add_parser("sweep", help="Repo-wide artifact-completeness report.")
    swp.add_argument("--out", required=True, help="write the JSON report here")
    swp.add_argument("--generated-at", default="", help="timestamp to stamp into the report")
    swp.set_defaults(func=cmd_sweep)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
