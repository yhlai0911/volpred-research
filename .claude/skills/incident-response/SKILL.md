---
name: incident-response
description: Diagnose, contain, fix, and close VolPred incidents. Use whenever a bug, alert, failed workflow, stale projection, or user request may be reported as fixed or resolved.
---

# Resolve an incident

Follow the five-step closure gate in `AGENTS.md`. Use `src/volpred/ops/incident.py` as the
machine owner for incident lifecycle and sustained-clean state.

## Workflow

1. **Evidence the symptom.** Read the live source, log, receipt, timestamps, upstream handoff,
   and downstream acknowledgement. Preserve the evidence before changing the system.
2. **Locate the root-cause layer.** Classify it as logic, workflow contract, schedule,
   state machine, API, permission, checker, or architecture. An unknown root cause is blocked.
3. **Fix the reusable owner.** Change repeatable code, configuration, schema, or enforcement.
   A rerun, manual data edit, copied artifact, or cleared flag is containment only.
4. **Regress and read back.** Reproduce the original case, run relevant tests, and verify the
   real downstream state through its API, database, hash, receipt, or rendered surface.
5. **Institutionalize.** Put the prevention in the owning script, contract, test, automation,
   skill, dashboard, or error-log entry so the same class cannot fail silently.

Use `docs/error_log.md` only to find prior classes and lessons; do not copy an old incident's
remediation without re-establishing current evidence.

## Status vocabulary

- Report `contained` when the immediate symptom is stopped but any gate remains incomplete.
- Report `blocked` when the root cause cannot yet be established or required authority is absent.
- Report `root_cause_fixed_and_verified` only after all five steps and any required
  sustained-clean window pass.

Never equate a successful command exit with downstream correctness.
