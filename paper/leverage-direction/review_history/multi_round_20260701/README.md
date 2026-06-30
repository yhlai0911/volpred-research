# Multi-Round Review Summary — 2026-07-01

Task: `paper_multi_round_review_leverage_direction`

Scope: ran three independent Codex review passes requested by the task brief:

1. `latex-academic-reviewer` style academic/LaTeX consistency review.
2. `citation-verifier` style citation and reference-claim review.
3. `journal-review` JBF submission-gate review.

No manuscript source files were edited in this review pass.

2026-07-01 active-v3 addendum: after the compliance scrub, a second read-only
gate was run against `main_v3.tex` / `body_v3.tex` / `tables.tex` and current
submission materials. That active-v3 pass is recorded in
`active_v3_final_gate_20260701.md` and supersedes any stale package-ready
interpretation.

## Gate Result

Overall result: **not converged**.

The earlier contribution gate already recorded `CONTRIBUTION BORDERLINE - needs reframing` in `review_history/codex_contribution_gate_20260701.md`. The three follow-up reviews all independently returned `FAIL_MAJOR_REVISION`, so the paper should remain in `revision` status and should not be treated as arXiv-ready or JBF-submission-ready.

The active-v3 addendum also returns `NEEDS_MAJOR_REVISION` with arXiv `HOLD`.

## Review Outputs

| Review | File | Verdict | High | Medium |
|---|---|---:|---:|---:|
| Latex academic review | `latex_academic_review.md` | `FAIL_MAJOR_REVISION` | 8 | 7 |
| Citation verification | `citation_verification_review.md` | `FAIL_MAJOR_REVISION` | 3 | 6 |
| JBF submission gate | `jbf_submission_gate_review.md` | `FAIL_MAJOR_REVISION` | 5 | 4 |
| Active v3 final gate | `active_v3_final_gate_20260701.md` | `NEEDS_MAJOR_REVISION` | n/a | n/a |

## Main Blocking Themes

1. **Contribution still unsettled.** The paper does not yet tell one JBF-clean story; it still combines taxonomy, model selection, risk management, volatility targeting, complexity ceiling, VIX/HAR/crowding discussion, crisis validation, and stale time-zone material.
2. **Gold/inverted-leverage claim remains overextended.** The credible claim is regime dependence and model-selection/allocation use, not discovery of inverted gold leverage.
3. **OOS/sample-map discipline is not submission-grade.** The source mixes 2017--2025, 2023--2024, 2025, and 2026 validation/OOS language across abstract, body, and tables.
4. **Submission package is not JBF-compliant.** The package is not double-blind, required files are missing or mis-specified, highlights are too long, and the cover letter/package still mention an unsupported third contribution.
5. **Citation base needs tightening.** Missing or stale references affect leverage-effect mechanisms, gold asymmetric volatility, VT metadata, model-family claims, event facts, and data-source justification.

## Operational Decision

Do not advance `leverage-direction` to `review_converged`, arXiv upload, or JBF submission. The next productive step is a focused reframing pass:

1. Choose one contribution anchor: leverage direction as an economically interpretable state variable for model selection and allocation.
2. Demote or remove time-zone, broad complexity-ceiling, HAR/VIX/crowding, and crisis-validation side claims unless they directly support that anchor.
3. Rebuild the sample/OOS map and model-selection rule as a pre-specified, auditable protocol.
4. Repair JBF package compliance only after the contribution and evidence map are stable.
