# PHASE-Z receipt attribution three-strike closure

Task: `dreaming_persistent_alert_8e08e46929dc07ef`  
Alert: `PHASE-Z 產出已 commit，但 agent 沒交代原因`

## Evidence and diagnosis

The detector was still live at revalidation: the alert had sent 8 times from
2026-07-14 through 2026-07-22 and the dreaming baseline had reached five strikes.
The exact 2026-07-22 16:21 recurrence landed commit `1629ae7b128a`; all five paths
that its message called agent output were supervisor/worker state under
`storage/ops/agent_jobs/**` and `storage/ops/compute_queue/**`.

The existing ownership definition was already unambiguous:
`_is_machine_state("storage/ops/...")` is true, and the Stop hook excludes those
paths because machine state has no agent-authored why. The split occurred later:
`run_phase_z` assigned every `dirty_now - baseline` path to `owned`, including
machine files changed after the agent stopped. The hook could not observe those
future updates, yet the commit path accused the agent and emitted the warning.

This is one sustained root cause across the dreaming runs, not five independent
receipt omissions. It also bypassed `_classify_machine_churn`, so newly dirty
control state missed the normal lock and parse checks.

## Root-cause change

Partition the during-fire delta by the existing namespace owner before any
receipt decision:

- non-machine paths remain `owned` for the legacy unisolated safety net;
- machine paths, whether dirty before or during the fire, go through the same
  `_classify_machine_churn` lock+parse gate and land as `churn`;
- only non-machine `owned` paths can select an agent receipt/generated subject
  or emit the missing-receipt warning.

No new detector, allowlist, or reminder channel is added. The fix reconnects the
commit path to the existing single ownership definition.

## Verification contract

`test_machine_state_created_during_fire_is_not_agent_output` reproduces the live
ordering: take a clean fire baseline, create a compute-queue status file after
the agent phase, and close PHASE-Z without a receipt. It must commit the path as
machine churn, report `owned=[]`, emit no warning, and use the state-churn subject.

Existing tests retain the opposite boundary: a during-fire code/research path is
still agent-owned, uses the generated receipt-less subject, and remains eligible
for the warning. Machine state dirty before the fire continues to use the same
validated adoption path.
