"""A push-failure alert must name the cause it observed, not a stock guess.

2026-08-04: a push was rejected because a tracked ledger had grown to 129 MiB
and hit GitHub's 100 MiB pre-receive ceiling. The alert said "check auth /
network / gh keychain" — a fixed string. All three leads were wrong and cost a
full diagnostic round before anyone read the actual push output, which had been
sitting in the log the whole time.

The rule these lock in: classify from the remote's own words, and when the
output does not match a known shape, say "unclassified" and quote it rather
than invent a lead.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from classify_push_failure import classify  # noqa: E402


REAL_SIZE_REJECTION = """
remote: error: Trace: 4245fdd8c343904f85f9e3d22a3245956332d40b0862cf4340178697cc2ea6bf
remote: error: See https://gh.io/lfs for more information.
remote: error: File storage/ops/dispatch_workspace_receipts.jsonl is 124.02 MB; this exceeds GitHub's file size limit of 100.00 MB
remote: error: GH001: Large files detected. You may want to try Git Large File Storage - https://git-lfs.github.com.
To https://github.com/yhlai0911/volpred-research.git
 ! [remote rejected]     6fea17196 -> main (pre-receive hook declined)
error: failed to push some refs to 'https://github.com/yhlai0911/volpred-research.git'
"""


def test_the_real_incident_names_the_file_and_never_says_keychain() -> None:
    out = classify(REAL_SIZE_REJECTION, ahead=6)

    assert out["class"] == "file_size_limit"
    assert "dispatch_workspace_receipts.jsonl" in out["body"]
    assert "124.02 MB" in out["body"]
    # The three leads that wasted a diagnostic round must not appear.
    lowered = out["body"].lower()
    assert "keychain" not in lowered
    assert "認證" not in out["body"]
    # And it must say the thing that was non-obvious: untracking is not enough.
    assert "rewritten" in lowered or "rewrite" in lowered


def test_size_rejection_wins_over_the_generic_hook_message() -> None:
    """A size rejection also prints 'pre-receive hook declined'.

    Ordering matters: the generic hook class would be technically true and
    useless.
    """
    assert classify(REAL_SIZE_REJECTION)["class"] == "file_size_limit"


def test_auth_failure_is_the_only_case_that_mentions_credentials() -> None:
    out = classify(
        "remote: Invalid username or password.\n"
        "fatal: Authentication failed for 'https://github.com/x/y.git/'\n"
    )
    assert out["class"] == "auth"
    assert "keychain" in out["body"].lower()


def test_network_failure_is_not_reported_as_auth() -> None:
    out = classify("fatal: unable to access 'https://github.com/x/y.git/': Could not resolve host: github.com\n")
    assert out["class"] == "network"
    assert "keychain" not in out["body"].lower()


def test_divergence_does_not_suggest_force_push() -> None:
    out = classify(
        " ! [rejected]        main -> main (non-fast-forward)\n"
        "hint: Updates were rejected because the tip of your current branch is behind\n"
    )
    assert out["class"] == "non_fast_forward"
    assert "do not force-push" in out["body"].lower()


def test_unknown_output_admits_it_and_quotes_the_remote() -> None:
    """The important negative case: no cause found means no invented cause."""
    out = classify(
        "remote: error: something entirely new and unmatched\n"
        "error: failed to push some refs\n"
    )
    assert out["class"] == "unclassified"
    body = out["body"].lower()
    assert "could not classify" in body
    assert "do not assume auth" in body
    assert "something entirely new and unmatched" in out["body"]


def test_evidence_is_deduplicated_and_bounded() -> None:
    noisy = "\n".join(["remote: error: same line"] * 50)
    out = classify(noisy)
    assert out["evidence"] == ["remote: error: same line"]


def test_ahead_count_is_reported_when_known() -> None:
    assert "6 local commit(s)" in classify(REAL_SIZE_REJECTION, ahead=6)["body"]
    assert "local commit(s)" not in classify(REAL_SIZE_REJECTION)["body"]


def test_cli_round_trip_matches_the_library() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "classify_push_failure.py"), "--ahead", "6", "--json"],
        input=REAL_SIZE_REJECTION,
        capture_output=True,
        text=True,
        check=True,
    )
    import json

    assert json.loads(proc.stdout)["class"] == "file_size_limit"
