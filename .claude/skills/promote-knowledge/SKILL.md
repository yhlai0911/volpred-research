---
name: promote-knowledge
description: Promote verified VolPred experiment findings into the research knowledge system. Use after code/result review when adding or correcting a K entry, provenance, or experiment-derived research conclusion.
---

# Promote experiment knowledge

Treat experiment results as evidence and the memory system as the only writer. Read
`src/volpred/memory/system.py`, the K1259 provenance rule in `AGENTS.md`, and
`scripts/check_experiment_artifacts.py` before mutation.

## Workflow

1. Confirm the experiment has passed code review, result verification, and the required
   reproducibility/artifact gates.
2. Read numbers programmatically from the canonical result JSON. Do not transcribe from a README,
   agent summary, or conversation.
3. Verify the result's code trace, reproduce spec, data period, sample size, seed, and limitations.
4. Use an existing canonical memory writer whose current interface has been verified. If no public
   writer exists for the required transition, stop as blocked and create an implementation task.
5. Read the local knowledge entry back, then verify each configured Supabase/Mirror projection and
   acknowledgement.
6. Re-run the experiment artifact checker.

## Completion

Return the K ID, canonical result hash, writer receipt, local entry identity, remote
acknowledgements, and artifact-gate result. Never rewrite `knowledge.json` directly or repair a
finding by editing projected data.
