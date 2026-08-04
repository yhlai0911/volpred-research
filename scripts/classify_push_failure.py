#!/usr/bin/env python3
"""Say why `git push` actually failed, instead of guessing.

2026-08-04: a push was rejected because
`storage/ops/dispatch_workspace_receipts.jsonl` had grown to 129 MiB and
GitHub's pre-receive hook enforces a 100 MiB ceiling. The alert that went out
said "check auth / network / gh keychain" — a fixed string, three suggestions,
none of them related. The information needed to say the true cause was already
in the log; nothing read it.

So this reads the push output and classifies it. The contract is deliberately
conservative: when the output does not match a known failure shape, this says
so and quotes the remote's own error lines rather than inventing advice. A
wrong lead costs more than an honest "unclassified" — that is the whole lesson
of the incident above.

Usage:
    git push ... 2>&1 | python3 scripts/classify_push_failure.py --ahead 6
"""

from __future__ import annotations

import argparse
import json
import re
import sys

#: Ordered most-specific first: a size rejection also prints "pre-receive hook
#: declined", so the generic hook class must never win over it.
_CLASSES: list[tuple[str, re.Pattern[str]]] = [
    ("file_size_limit", re.compile(r"GH001|exceeds GitHub's file size limit", re.I)),
    ("lfs_required", re.compile(r"git-lfs|Large File Storage", re.I)),
    ("auth", re.compile(
        r"Authentication failed|could not read Username|could not read Password"
        r"|Permission denied|HTTP 403|Invalid username or password|terminal prompts disabled",
        re.I)),
    ("network", re.compile(
        r"Could not resolve host|Connection timed out|Connection refused"
        r"|unable to access|Failed to connect|Operation timed out|TLS|SSL",
        re.I)),
    ("non_fast_forward", re.compile(r"non-fast-forward|fetch first|behind its remote", re.I)),
    ("protected_branch", re.compile(r"protected branch|GH006", re.I)),
    ("hook_declined", re.compile(r"pre-receive hook declined|remote rejected", re.I)),
]

_ACTION = {
    "file_size_limit":
        "A blob already committed exceeds the remote ceiling. Un-tracking the file "
        "going forward does NOT unblock the push: the oversized blobs stay in the "
        "commits that carry them, so the history holding them has to be rewritten "
        "(or the commits recreated without that path). Cap the writer as well, or "
        "the next run rebuilds the same wall.",
    "lfs_required":
        "The remote is asking for Git LFS. Decide whether this file belongs in "
        "version control at all before adopting LFS for it.",
    "auth":
        "Credential problem. Check the keychain credential helper and the token's "
        "scope and expiry.",
    "network":
        "Transport problem. Check connectivity to the remote; this usually clears "
        "on its own and the next scheduled push will retry.",
    "non_fast_forward":
        "The remote moved ahead. Reconcile with the existing divergence path; do "
        "not force-push.",
    "protected_branch":
        "A branch protection rule rejected the push. This needs a policy decision, "
        "not a retry.",
    "hook_declined":
        "A remote hook rejected the push for a reason not matched here. Read the "
        "quoted remote output below before acting.",
}

#: Paths named by the remote in a size rejection, e.g.
#: "remote: error: File storage/ops/x.jsonl is 124.02 MB; this exceeds ..."
_SIZE_FILE = re.compile(
    r"File\s+(?P<path>\S+)\s+is\s+(?P<size>[\d.]+\s*[KMG]B)", re.I
)


def _remote_errors(text: str, limit: int = 6) -> list[str]:
    """The remote's own words, which are the only non-speculative evidence."""
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if re.search(r"^(remote:|\s*!\s|error:|fatal:)", ln.strip(), re.I)
    ]
    seen: list[str] = []
    for ln in lines:
        if ln not in seen:
            seen.append(ln)
    return seen[-limit:]


def classify(output: str, *, ahead: int | None = None) -> dict:
    kind = "unclassified"
    for name, pattern in _CLASSES:
        if pattern.search(output):
            kind = name
            break

    detail = ""
    if kind == "file_size_limit":
        hits = [
            f"{m.group('path')} ({m.group('size')})" for m in _SIZE_FILE.finditer(output)
        ]
        if hits:
            detail = "Offending file(s): " + ", ".join(dict.fromkeys(hits)) + "."

    evidence = _remote_errors(output)
    lead = (
        f"git push origin main failed with {ahead} local commit(s) not backed up."
        if ahead is not None
        else "git push origin main failed."
    )
    action = _ACTION.get(
        kind,
        "Could not classify this failure from the push output. Do not assume auth "
        "or network. Read the remote output quoted below and diagnose from it.",
    )

    body_parts = [lead, "", f"Cause class: {kind}"]
    if detail:
        body_parts.append(detail)
    body_parts += ["", "What to do", action]
    if evidence:
        body_parts += ["", "Remote said", *evidence]

    return {
        "class": kind,
        "offending": detail,
        "evidence": evidence,
        "title": f"git-push-backup: push failed ({kind})",
        "body": "\n".join(body_parts),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ahead", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = classify(sys.stdin.read(), ahead=args.ahead)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result["body"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
