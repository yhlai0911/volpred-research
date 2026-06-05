# Paper 9 (garch-x-vix) — Next-Action Decision

**Date**: 2026-06-06  
**Decision owner**: Codex hourly tick  
**Task**: `gen_paper_decision_P9`

## Decision

**Keep P9 in `submitted under review / amber`, freeze `main.tex`, and do not push a body rewrite before R1 reviewer response.**

The current bottleneck is no longer a core model invalidation. It is a combination of:

1. **replication-packet inconsistency** (`README.md`, `reproduce_report.json`, shelf errata wording),
2. **claim-discipline issues already identified in Codex v7 review**, and
3. **known snapshot/live drift that is qualitatively invariant but not numerically frozen in a reviewer-facing way**.

These issues justify **preparing** an R1 response package, but they do **not** justify changing the submitted paper body before the reviewer actually asks for clarification.

## Why this is the correct action

### 1. Research-program policy already points to shelf errata, not pre-emptive body mutation

`research_program.md` currently records P9 as:

- `submitted under review`
- `snapshot 53.8% / live 84.6%`
- `shelf errata ready`
- `無 body edit 直到 R1 reviewer response`

That should remain the canonical stance unless the paper is formally withdrawn or returned with comments.

### 2. The remaining issues are mostly packet/wording precision, not fresh empirical invalidation

Codex adversarial review v7 found four reviewer-visible problems:

1. replication-facing metadata is stale,
2. “statistically non-inferior” is too strong,
3. `g_t` is conflated with the `g`-proxy,
4. the conclusion overstates cross-asset generalization relative to the paper’s own Bonferroni caveat.

These are real issues, but they are **R1-fix issues**, not “withdraw immediately” issues.

### 3. The drift is known, documented, and qualitatively invariant

`errata_pending.md` already records the snapshot/live DM drift and explicitly states:

- Harvey qualitative conclusion is invariant,
- pinned snapshot files exist,
- no body edit is required pre-reviewer-response.

That means the right move is to **tighten the shelf package**, not to rewrite the submitted manuscript in place.

## Immediate next action

### A. Do now: packet-cleanup queue only

Prepare, but do not yet deploy to the submitted body:

1. **Replication metadata sync**
   - update `paper/garch-x-vix/README.md`
   - update `paper/garch-x-vix/reproduce_report.json` generation logic / interpretation layer
   - make all reviewer-facing metadata distinguish:
     - paper-frozen values,
     - pinned-snapshot reruns,
     - live reruns

2. **R1 wording patch queue**
   - replace “statistically non-inferior” with “not statistically distinguishable under these comparisons”
   - replace `g_t tracks VRP at rho≈0.80` with explicit `g-proxy` wording
   - soften cross-asset conclusion to the dual-threshold version:
     - baseline Harvey screen: five of seven
     - conservative Bonferroni framing: four of seven

3. **Reviewer-response bundle readiness**
   - ensure `errata_pending.md` is the canonical shelf note
   - ensure snapshot provenance and the meaning of amber/red reproduce states are explainable in one paragraph

### B. Do not do yet

1. do **not** rewrite `main.tex` pre-emptively,
2. do **not** resubmit / withdraw / pivot journal on current evidence,
3. do **not** claim P9 is green or submission-clean.

## Trigger to reopen body edits

Reopen `main.tex` only if one of the following happens:

1. **R1 reviewer response arrives** and asks for clarification, replication, or claim softening,
2. **user explicitly asks** to convert the shelf errata into a formal revised manuscript before reviewer feedback,
3. a **new empirical contradiction** appears that overturns the paper’s qualitative conclusion rather than just drifting point estimates.

## Operational status after this decision

- **Paper status**: keep `submitted under review / amber`
- **Narrative state**: shelf-errata / R1-prep
- **Body state**: frozen
- **Allowed work before R1**: metadata cleanup, response drafting, snapshot/provenance hardening
- **Disallowed work before R1**: unsolicited body rewrite

## One-line summary

**P9 should remain submitted and body-frozen; the correct next step is to harden the replication packet and queue R1-safe wording fixes, not to mutate the manuscript before reviewer contact.**
