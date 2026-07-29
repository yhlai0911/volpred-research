---
name: reconcile-projections
description: Reconcile VolPred canonical local data with Supabase, Mirror, or live-site projections. Use for feed, paper, memory, strategy, or admin drift and for verifying that downstream systems received the canonical state.
---

# Reconcile projections

Start by naming the canonical branch and the projections in scope. Resolve URLs and targets from
`config/project_targets.json`; resolve scheduled ownership from `config/runtime_schedules.json`.

## Workflow

1. Read the canonical local object, exact status/owner fields, and content hash.
2. Read every in-scope projection without mutation and produce a field-level diff.
3. Identify the single writer/reconcile family that owns that projection.
4. Run its dry-run or preview surface when available.
5. Apply through the verified canonical CLI or writer. Never write a database row or local JSON
   merely to make the diff disappear.
6. Read the remote API/database and live consumer back.
7. Bind the acknowledgement to the canonical hash, object identity, writer family, and receipt.

## Completion

Success requires zero unexpected drift and a typed downstream acknowledgement. If the projection
cannot represent the canonical state, treat it as a schema/workflow incident rather than silently
dropping fields.
