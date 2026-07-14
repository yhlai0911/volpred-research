"""What a failed `claude -p` run's output looks like — one definition, two callers.

Two places in this repo spawn `claude -p` and must decide what a nonzero exit
MEANS: the supervisor (`worker.py`, one dispatch fire) and the agent-job runner
(`scripts/run_agent_job.py`, one long research agent under the compute worker).

Until 2026-07-14 only the supervisor could tell the classes apart. The runner
treated every nonzero exit as "the job failed" — so when the CLI answered
`Not logged in · Please run /login` five seconds in, a 60-minute K1709 review
was filed as a research failure and routed to `triage_failed`, which spends a
whole later fire concluding "the agent never ran; re-enqueue it".

The classes differ in what the caller should DO, which is why they are worth
separating at all:

  auth      credentials are gone. Nothing was computed, no tokens were spent.
            Retrying the same second cannot help; retrying in a couple of
            minutes can (a token refresh races the spawn), and if it still
            fails, a human has to log in.
  quota     the window is exhausted. It resolves on a clock, not on an action —
            so never burn a retry ladder on it and never demand a manual unblock.
  transient the network wobbled (529 / reset / rate-limit). A short backoff is
            exactly the right answer.

Everything else is a real failure of the work itself, and the caller owns it.
"""
from __future__ import annotations

import re

# Order matters where these overlap; see classify_output.
AUTH_RE = re.compile(r"(Not logged in|Please run /login|invalid_api_key|authentication)", re.I)
# 2026-07-05 incident: the weekly quota ran out 11:07-16:00 and "You've hit your
# weekly limit · resets 4pm" matched NO class → hard_failure → the full retry
# ladder (opus→opus→sonnet) burned on every hourly fire (15 wasted attempts over
# 5h). Quota is neither transient (90s cannot help) nor auth (it auto-resolves,
# and demanding a manual unblock would strand the loop). It gets its own class.
QUOTA_RE = re.compile(
    r"(hit your (?:weekly|5.?hour|monthly|usage|session) limit|usage limit (?:reached|exceeded))",
    re.I,
)
TRANSIENT_RE = re.compile(r"(529|Overloaded|ECONNRESET|ETIMEDOUT|Connection reset|rate.?limit)", re.I)


def classify_output(output: str | None) -> str | None:
    """Name the failure class visible in a failed run's output, or None.

    Callers must pass ONLY the output of the attempt being classified. A log tail
    carrying a stale `Not logged in` from an earlier attempt would freeze the
    whole loop on a false auth verdict (2026-07-05 fix in worker.py).
    """
    text = output or ""
    if AUTH_RE.search(text):
        return "auth"
    # quota BEFORE transient: both mean "come back later", but transient's short
    # backoff is pointless against an hours-long quota window.
    if QUOTA_RE.search(text):
        return "quota"
    if TRANSIENT_RE.search(text):
        return "transient"
    return None
