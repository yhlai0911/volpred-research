# Quota alert ownership three-strike closure

Task: `dreaming_persistent_alert_e46b1923cd3787a9`  
Alert: `supervisor quota_blocked（額度恢復後自動復工）`

## Evidence and diagnosis

Fresh revalidation on 2026-07-23 still reproduced the original finding: the alert
had sent 13 times across 15.7 days, most recently on 2026-07-22 03:02 UTC. The
production dispatch receipts after that fire show repeated
`codex_failover_recovered` outcomes, so the affected slots were being handled by
the supervisor's existing fallback rather than silently dropped.

This notification already has an outage-scoped lifecycle in
`scripts/dispatch_supervisor/alerts.py`: one notice per Claude quota outage,
automatic probing on later fires, and reset after Claude succeeds. The worker then
records Codex failover success or failure separately. Generic dreaming detectors
nevertheless treated the quota notice as an unowned persistent/unfiled incident,
creating a second remediation owner. The same ownership split remained visible
across more than three dreaming runs.

## Root-cause change

Add the exact supervisor quota title to the shared
`PERSISTENT_ALERT_DELEGATED_OWNERS` registry used by both generic detectors. Its
canonical owner is `dispatch_supervisor.quota_failover`:

- the supervisor quota notice owns detection, outage dedup, probing, and recovery;
- the successful failover notice is recovery telemetry and is also delegated;
- the failover-failed notice is deliberately not delegated, because it represents
  real slot loss that still requires generic persistence and filing checks;
- auth and unrelated provider alerts remain visible.

No alert ledger or historical task data is edited. Existing findings resolve on
the next detector run because their source title no longer belongs to the generic
detector.

## Verification contract

`tests/test_dreaming_review.py` now covers both consumers of the registry:

- persistent detection skips the exact quota notice and successful failover, but
  keeps `Claude→Codex failover 接手失敗（Claude 端：quota）`;
- unfiled-incident detection skips the supervisor-owned quota notice, while a
  failover failure still produces a filing candidate.

The full dreaming test module passes (99 tests). Replaying the production
`alert_dedup.json` after the change returns no
`persistent_alert:e46b1923cd3787a9`; before the change, the same replay returned
the 13-fire finding.
