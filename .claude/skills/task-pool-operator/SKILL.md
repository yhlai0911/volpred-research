---
name: task-pool-operator
description: Claim, start, release, hand off, or complete VolPred work items. Use for any interaction with storage/next_tasks.json, task ownership, linked GitHub issues, or worker settlement.
---

# Operate the task pool

The live mode is dynamic. Read `storage/ops/task_pool_mode.json` before creating or claiming work.
Use `storage/ops/handoff_latest.md` for the current snapshot and
`.claude/rules/task-routing.md` for capability routing.

## Workflow

1. Inspect the live mode and list eligible pending work with `scripts/task_pool_claim.py`.
2. Create new work only through a canonical ingress that the live mode permits.
3. Claim atomically with a stable owner. On `already_claimed` or `wrong_status`, choose another
   task; never force ownership.
4. Start the claimed task before executing it.
5. Complete the requested work and verify its actual artifact or downstream effect.
6. Settle through `scripts/task_pool_claim.py`:
   - release when the task is valid but this attempt should not own it;
   - hand off when the work belongs to the main-thread lane;
   - complete only after the task's own acceptance criteria pass.
7. Read the row back and verify terminal status, cleared active claim metadata, and durable result.

## Linked issues

Task success and issue closure are separate. Default to `contained`; request issue closure only
when the whole issue's acceptance criteria and incident closure gate pass. The canonical Git
writer must bind the exact task ID to the real commit SHA before issue-close settlement.

Never edit `storage/next_tasks.json` or `storage/ops/` directly, and never infer the current mode
from a dated document.
